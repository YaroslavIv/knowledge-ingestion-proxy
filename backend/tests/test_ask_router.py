import json

import respx
from httpx import Response

RAW_COMPLETION = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "model": "gpt-5.4",
    "choices": [{"message": {"role": "assistant", "content": "answer text"}}],
    "usage": {"total_tokens": 10},
    "sources": [
        {
            "source": {"type": "collection", "id": "kb-b"},
            "document": ["chunk text"],
            "metadata": [{"file_id": "file-1", "name": "doc.txt", "score": 0.2}],
        }
    ],
}


def _mock_embedding_calls(vector=None):
    """Every successful /api/ask/joint call now also fetches the embedding
    config and embeds the query (see app/routers/ask.py's
    _embed_query_best_effort) — real tests mock both rather than relying on
    the best-effort except-clause to swallow respx's own unmocked-route
    error, which would mask real regressions in this path."""
    respx.get("http://fake-owui.test/api/v1/retrieval/embedding").mock(
        return_value=Response(
            200,
            json={
                "RAG_EMBEDDING_ENGINE": "ollama",
                "RAG_EMBEDDING_MODEL": "qwen3-embedding:0.6b",
                "openai_config": {"url": "", "key": ""},
                "ollama_config": {"url": "http://ollama:11434", "key": ""},
                "azure_openai_config": {"url": "", "key": "", "version": ""},
            },
        )
    )
    respx.post("http://fake-owui.test/api/v1/embeddings").mock(
        return_value=Response(200, json={"data": [{"embedding": vector or [0.1, 0.2, 0.3], "index": 0}]})
    )


@respx.mock
async def test_ask_route_endpoint_returns_owuis_raw_shape_plus_routing_fields(client):
    respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        side_effect=[
            Response(200, json={"documents": [["a"]], "distances": [[0.8]], "metadatas": [[{}]]}),
            Response(200, json={"documents": [["b"]], "distances": [[0.2]], "metadatas": [[{}]]}),
        ]
    )
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json=RAW_COMPLETION)
    )

    resp = await client.post(
        "/api/ask/route",
        json={"collection_ids": ["kb-a", "kb-b"], "query": "some question", "model": "gpt-5.4"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # raw Open WebUI fields present, unmodified
    assert body["choices"][0]["message"]["content"] == "answer text"
    assert body["sources"] == RAW_COMPLETION["sources"]
    assert body["usage"] == {"total_tokens": 10}
    # plus our routing decision on top — kb-a's 0.8 is the higher (better) score
    assert body["winning_collection_id"] == "kb-a"
    assert body["collection_scores"] == {"kb-a": 0.8, "kb-b": 0.2}


@respx.mock
async def test_ask_route_endpoint_502s_on_owui_failure(client):
    respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        return_value=Response(400, json={"detail": "boom"})
    )
    resp = await client.post(
        "/api/ask/route",
        json={"collection_ids": ["kb-a"], "query": "q", "model": "gpt-5.4"},
    )
    assert resp.status_code == 502


@respx.mock
async def test_ask_joint_endpoint_returns_owuis_raw_shape_unmodified(client):
    _mock_embedding_calls()
    chat_route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json=RAW_COMPLETION)
    )
    resp = await client.post(
        "/api/ask/joint",
        json={"collection_ids": ["kb-a", "kb-b"], "query": "some question", "model": "gpt-5.4"},
    )
    assert resp.status_code == 200
    assert resp.json() == RAW_COMPLETION
    sent_body = json.loads(chat_route.calls[0].request.content)
    assert sent_body["files"] == [
        {"type": "collection", "id": "kb-a"},
        {"type": "collection", "id": "kb-b"},
    ]


@respx.mock
async def test_ask_joint_passes_history_before_the_current_query(client):
    _mock_embedding_calls()
    chat_route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json=RAW_COMPLETION)
    )
    resp = await client.post(
        "/api/ask/joint",
        json={
            "collection_ids": ["kb-a"],
            "query": "and what about pricing?",
            "model": "gpt-5.4",
            "history": [
                {"role": "user", "content": "what is SecurOS Auto?"},
                {"role": "assistant", "content": "it's a module for..."},
            ],
        },
    )
    assert resp.status_code == 200
    sent_body = json.loads(chat_route.calls[0].request.content)
    assert sent_body["messages"] == [
        {"role": "user", "content": "what is SecurOS Auto?"},
        {"role": "assistant", "content": "it's a module for..."},
        {"role": "user", "content": "and what about pricing?"},
    ]


@respx.mock
async def test_ask_route_defaults_to_no_history(client):
    respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        return_value=Response(200, json={"documents": [["a"]], "distances": [[0.5]], "metadatas": [[{}]]})
    )
    chat_route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json=RAW_COMPLETION)
    )
    await client.post("/api/ask/route", json={"collection_ids": ["kb-a"], "query": "q", "model": "gpt-5.4"})
    sent_body = json.loads(chat_route.calls[0].request.content)
    assert sent_body["messages"] == [{"role": "user", "content": "q"}]


@respx.mock
async def test_search_endpoint_returns_pooled_results_no_generation(client):
    query_route = respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        return_value=Response(
            200,
            json={
                "documents": [["best chunk", "second chunk"]],
                "distances": [[0.91, 0.42]],
                "metadatas": [[{"file_id": "file-1", "name": "doc-a.pdf"}, {"file_id": "file-2", "name": "doc-b.md"}]],
            },
        )
    )
    resp = await client.post(
        "/api/ask/search",
        json={"collection_ids": ["kb-a", "kb-b"], "query": "some question", "k": 5},
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "results": [
            {"document": "best chunk", "score": 0.91, "file_id": "file-1", "filename": "doc-a.pdf"},
            {"document": "second chunk", "score": 0.42, "file_id": "file-2", "filename": "doc-b.md"},
        ]
    }
    sent_body = json.loads(query_route.calls[0].request.content)
    assert sent_body["collection_names"] == ["kb-a", "kb-b"]
    assert sent_body["k"] == 5
    # no chat-completion call at all — respx would raise AllMockedAssertionError
    # if search hit it, since only /query/collection is mocked here


@respx.mock
async def test_search_endpoint_resolves_collections_by_tag(client):
    respx.get("http://fake-owui.test/api/v1/knowledge/").mock(
        return_value=Response(200, json=[{"id": "kb-coe-1", "name": "Docs", "description": ""}])
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-coe-1", "name": "Docs", "description": ""})
    )
    await client.post("/api/kb", json={"name": "Docs", "version_tag": "v1.0"})
    tag_resp = await client.patch("/api/kb/kb-coe-1/tags", json={"tags": ["coe"]})
    assert tag_resp.status_code == 200

    query_route = respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        return_value=Response(200, json={"documents": [["a"]], "distances": [[0.5]], "metadatas": [[{}]]})
    )
    resp = await client.post("/api/ask/search", json={"tag": "coe", "query": "q"})
    assert resp.status_code == 200
    sent_body = json.loads(query_route.calls[0].request.content)
    assert sent_body["collection_names"] == ["kb-coe-1"]


@respx.mock
async def test_search_endpoint_502s_on_owui_failure(client):
    respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        return_value=Response(400, json={"detail": "boom"})
    )
    resp = await client.post("/api/ask/search", json={"collection_ids": ["kb-a"], "query": "q"})
    assert resp.status_code == 502


async def test_search_endpoint_requires_collection_ids_or_tag(client):
    resp = await client.post("/api/ask/search", json={"query": "q"})
    assert resp.status_code == 400


@respx.mock
async def test_ask_joint_records_the_question_and_answer_in_history(client):
    _mock_embedding_calls(vector=[0.4, 0.5, 0.6])
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(return_value=Response(200, json=RAW_COMPLETION))

    ask_resp = await client.post(
        "/api/ask/joint",
        json={"collection_ids": ["kb-a", "kb-b"], "query": "some question", "model": "gpt-5.4"},
    )
    assert ask_resp.status_code == 200

    history_resp = await client.get("/api/ask/joint/history")
    assert history_resp.status_code == 200
    entries = history_resp.json()
    assert len(entries) == 1
    assert entries[0]["query"] == "some question"
    assert entries[0]["model"] == "gpt-5.4"
    assert entries[0]["collection_ids"] == ["kb-a", "kb-b"]
    assert entries[0]["answer"] == "answer text"
    assert entries[0]["tag"] is None

    # the embedding itself isn't exposed via the history listing endpoint
    # (would bloat every response with a big float array) — read it back
    # straight from the DB instead, confirming it was actually stored.
    import app.db as db_module
    from app.models import AskJointLog
    from sqlalchemy import select

    async with db_module.AsyncSessionLocal() as session:
        row = (await session.execute(select(AskJointLog))).scalars().one()
        assert row.embedding == [0.4, 0.5, 0.6]


@respx.mock
async def test_ask_joint_history_lists_newest_first(client):
    _mock_embedding_calls()
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(return_value=Response(200, json=RAW_COMPLETION))

    await client.post("/api/ask/joint", json={"collection_ids": ["kb-a"], "query": "first", "model": "gpt-5.4"})
    await client.post("/api/ask/joint", json={"collection_ids": ["kb-a"], "query": "second", "model": "gpt-5.4"})

    history_resp = await client.get("/api/ask/joint/history")
    queries = [e["query"] for e in history_resp.json()]
    assert queries == ["second", "first"]


@respx.mock
async def test_ask_joint_does_not_record_history_on_owui_failure(client):
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(return_value=Response(400, json={"detail": "boom"}))

    resp = await client.post(
        "/api/ask/joint", json={"collection_ids": ["kb-a"], "query": "some question", "model": "gpt-5.4"}
    )
    assert resp.status_code == 502

    history_resp = await client.get("/api/ask/joint/history")
    assert history_resp.json() == []


@respx.mock
async def test_ask_route_and_search_do_not_record_joint_history(client):
    respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        return_value=Response(200, json={"documents": [["a"]], "distances": [[0.5]], "metadatas": [[{}]]})
    )
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(return_value=Response(200, json=RAW_COMPLETION))

    await client.post("/api/ask/route", json={"collection_ids": ["kb-a"], "query": "q", "model": "gpt-5.4"})
    await client.post("/api/ask/search", json={"collection_ids": ["kb-a"], "query": "q"})

    history_resp = await client.get("/api/ask/joint/history")
    assert history_resp.json() == []
