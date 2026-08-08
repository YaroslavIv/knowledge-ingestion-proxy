import json

import pytest
import respx
from httpx import Response

from app.chunking.preview import ChunkRange
from app.owui_client import OwuiClient, OwuiError
from app.retrieval_router import ask_joint, ask_with_routing, compare_searches, search_collections

# Mirrors the real shape Open WebUI returns for a `files`-augmented chat
# completion (confirmed live): the usual OpenAI fields plus a `sources`
# field listing which chunks/files fed the answer.
RAW_COMPLETION = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "model": "gpt-5.4",
    "choices": [{"message": {"role": "assistant", "content": "the answer"}}],
    "usage": {"total_tokens": 42},
    "sources": [
        {
            "source": {"type": "collection", "id": "kb-b"},
            "document": ["relevant chunk text"],
            "metadata": [{"file_id": "file-1", "name": "doc.txt", "score": 0.31}],
        }
    ],
}


@respx.mock
async def test_ask_with_routing_picks_the_collection_with_the_highest_score():
    """Despite being called `distances`, this field is a similarity score —
    confirmed empirically against a real instance (for a fixed query,
    results come back sorted highest-first, decreasing from there). The
    collection with the HIGHEST score must win, not the lowest."""
    respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        side_effect=[
            Response(200, json={"documents": [["a"]], "distances": [[0.9]], "metadatas": [[{}]]}),  # kb-a (best)
            Response(200, json={"documents": [["b"]], "distances": [[0.3]], "metadatas": [[{}]]}),  # kb-b
            Response(200, json={"documents": [["c"]], "distances": [[0.6]], "metadatas": [[{}]]}),  # kb-c
        ]
    )
    chat_route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json=RAW_COMPLETION)
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")

    result = await ask_with_routing(client, "gpt-5.4", ["kb-a", "kb-b", "kb-c"], "some question")

    # the raw Open WebUI completion shape passes through untouched...
    assert result["choices"][0]["message"]["content"] == "the answer"
    assert result["sources"] == RAW_COMPLETION["sources"]
    assert result["usage"] == {"total_tokens": 42}
    # ...plus our own routing-decision fields on top
    assert result["winning_collection_id"] == "kb-a"
    assert result["collection_scores"] == {"kb-a": 0.9, "kb-b": 0.3, "kb-c": 0.6}

    sent_body = json.loads(chat_route.calls[0].request.content)
    assert sent_body["files"] == [{"type": "collection", "id": "kb-a"}]


@respx.mock
async def test_ask_with_routing_ignores_collections_with_no_matches():
    respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        side_effect=[
            Response(200, json={"documents": [[]], "distances": [[]], "metadatas": [[]]}),  # kb-a: empty
            Response(200, json={"documents": [["b"]], "distances": [[0.5]], "metadatas": [[{}]]}),  # kb-b
        ]
    )
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json=RAW_COMPLETION)
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")

    result = await ask_with_routing(client, "gpt-5.4", ["kb-a", "kb-b"], "q")
    assert result["winning_collection_id"] == "kb-b"
    assert result["collection_scores"] == {"kb-a": None, "kb-b": 0.5}


@respx.mock
async def test_ask_with_routing_raises_if_every_collection_is_empty():
    respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        return_value=Response(200, json={"documents": [[]], "distances": [[]], "metadatas": [[]]})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")

    with pytest.raises(ValueError, match="matching content"):
        await ask_with_routing(client, "gpt-5.4", ["kb-a", "kb-b"], "q")


@respx.mock
async def test_ask_with_routing_surfaces_scoring_errors():
    respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        return_value=Response(400, json={"detail": "bad request"})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")

    with pytest.raises(OwuiError):
        await ask_with_routing(client, "gpt-5.4", ["kb-a"], "q")


@respx.mock
async def test_ask_joint_queries_every_collection_in_one_chat_completion_call():
    chat_route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json=RAW_COMPLETION)
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")

    result = await ask_joint(client, "gpt-5.4", ["kb-a", "kb-b", "kb-c"], "some question")

    # raw Open WebUI shape, unmodified — no routing fields added in joint mode
    assert result == RAW_COMPLETION
    sent_body = json.loads(chat_route.calls[0].request.content)
    assert sent_body["files"] == [
        {"type": "collection", "id": "kb-a"},
        {"type": "collection", "id": "kb-b"},
        {"type": "collection", "id": "kb-c"},
    ]
    # no scoring call — joint mode never touches /query/collection (respx
    # would raise AllMockedAssertionError if it tried, since only
    # /chat/completions is mocked in this test)


@respx.mock
async def test_search_collections_returns_pooled_results_with_scores_and_filenames():
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
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")

    results = await search_collections(client, ["kb-a", "kb-b"], "some question", k=5)

    assert results == [
        {"document": "best chunk", "score": 0.91, "file_id": "file-1", "filename": "doc-a.pdf"},
        {"document": "second chunk", "score": 0.42, "file_id": "file-2", "filename": "doc-b.md"},
    ]
    sent_body = json.loads(query_route.calls[0].request.content)
    assert sent_body["collection_names"] == ["kb-a", "kb-b"]
    assert sent_body["query"] == "some question"
    assert sent_body["k"] == 5
    # no chat-completion call at all — pure retrieval, no generation
    # (respx would raise AllMockedAssertionError if one were attempted,
    # since only /query/collection is mocked in this test)


@respx.mock
async def test_search_collections_returns_empty_list_when_nothing_matches():
    respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        return_value=Response(200, json={"documents": [[]], "distances": [[]], "metadatas": [[]]})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")

    results = await search_collections(client, ["kb-a"], "some question")

    assert results == []


@respx.mock
async def test_search_collections_surfaces_owui_errors():
    respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        return_value=Response(401, json={"detail": "Unauthorized"})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")

    with pytest.raises(OwuiError):
        await search_collections(client, ["kb-a"], "some question")


@respx.mock
async def test_compare_searches_treats_identical_chunk_text_as_zero_distance():
    respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        side_effect=[
            Response(
                200,
                json={
                    "documents": [["shared chunk text"]],
                    "distances": [[0.9]],
                    "metadatas": [[{"file_id": "file-1", "name": "doc.pdf"}]],
                },
            ),
            Response(
                200,
                json={
                    "documents": [["shared chunk text"]],
                    "distances": [[0.6]],
                    "metadatas": [[{"file_id": "file-1", "name": "doc.pdf"}]],
                },
            ),
        ]
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")

    result = await compare_searches(client, ["kb-a"], "query A", "query B")

    assert result["comparison"]["file_overlap"] == 1
    assert result["comparison"]["file_total"] == 1
    assert len(result["comparison"]["matches"]) == 1
    match = result["comparison"]["matches"][0]
    assert match["chunk_distance"] == 0
    assert match["score_a"] == 0.9
    assert match["score_b"] == 0.6
    assert match["score_delta"] == pytest.approx(0.3)


@respx.mock
async def test_compare_searches_computes_chunk_distance_for_non_identical_chunks_in_the_same_file(monkeypatch):
    """Two different (but from the same file) retrieved chunks aren't just
    "same file or not" — this measures how many chunk-widths apart they
    really are, using that file's real chunking (see
    app/chunking/preview.py). compute_chunk_preview itself is monkeypatched
    to a known, controlled set of ranges so this test verifies the
    distance/pairing logic, not langchain's actual splitter behavior
    (already covered by the chunking module's own tests)."""
    respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        side_effect=[
            Response(
                200,
                json={"documents": [["AAA"]], "distances": [[0.9]], "metadatas": [[{"file_id": "file-1", "name": "doc.pdf"}]]},
            ),
            Response(
                200,
                json={"documents": [["CCC"]], "distances": [[0.5]], "metadatas": [[{"file_id": "file-1", "name": "doc.pdf"}]]},
            ),
        ]
    )
    respx.get("http://fake-owui.test/api/v1/files/file-1/data/content").mock(
        return_value=Response(200, json={"content": "AAABBBCCC"})
    )
    respx.get("http://fake-owui.test/api/v1/retrieval/config").mock(
        return_value=Response(200, json={"CHUNK_SIZE": 3, "CHUNK_OVERLAP": 0})
    )
    monkeypatch.setattr(
        "app.retrieval_router.compute_chunk_preview",
        lambda text, config: [ChunkRange(0, 3), ChunkRange(3, 6), ChunkRange(6, 9)],
    )

    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    result = await compare_searches(client, ["kb-a"], "query A", "query B")

    assert len(result["comparison"]["matches"]) == 1
    match = result["comparison"]["matches"][0]
    assert match["document_a"] == "AAA"
    assert match["document_b"] == "CCC"
    assert match["chunk_distance"] == 2  # chunk index 0 vs chunk index 2


@respx.mock
async def test_compare_searches_reports_no_matches_when_no_files_overlap():
    respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        side_effect=[
            Response(200, json={"documents": [["a"]], "distances": [[0.9]], "metadatas": [[{"file_id": "file-1", "name": "a.md"}]]}),
            Response(200, json={"documents": [["b"]], "distances": [[0.5]], "metadatas": [[{"file_id": "file-2", "name": "b.md"}]]}),
        ]
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")

    result = await compare_searches(client, ["kb-a"], "query A", "query B")

    assert result["comparison"]["file_overlap"] == 0
    assert result["comparison"]["file_total"] == 2
    assert result["comparison"]["matches"] == []


@respx.mock
async def test_compare_searches_surfaces_owui_errors():
    respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        return_value=Response(401, json={"detail": "Unauthorized"})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")

    with pytest.raises(OwuiError):
        await compare_searches(client, ["kb-a"], "query A", "query B")
