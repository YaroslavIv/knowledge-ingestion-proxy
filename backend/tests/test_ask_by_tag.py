import respx
from httpx import Response

RAW_COMPLETION = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "model": "gpt-5.4",
    "choices": [{"message": {"role": "assistant", "content": "answer text"}}],
    "usage": {"total_tokens": 10},
    "sources": [],
}


@respx.mock
async def test_ask_by_tag_collapses_a_clone_lineage_to_just_the_newest(client):
    respx.get("http://fake-owui.test/api/v1/knowledge/").mock(
        return_value=Response(
            200,
            json=[
                {"id": "kb-old", "name": "CoE Old", "description": ""},
                {"id": "kb-new", "name": "CoE New", "description": ""},
            ],
        )
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        side_effect=[
            Response(200, json={"id": "kb-old", "name": "CoE Old", "description": ""}),
            Response(200, json={"id": "kb-new", "name": "CoE New", "description": ""}),
        ]
    )
    await client.post("/api/kb", json={"name": "CoE Old", "version_tag": "v1.0"})
    tag_resp = await client.patch("/api/kb/kb-old/tags", json={"tags": ["coe"]})
    assert tag_resp.status_code == 200

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-old/files").mock(return_value=Response(200, json=[]))
    clone_resp = await client.post("/api/kb/kb-old/clone", json={"name": "CoE New", "version_tag": "v1.1"})
    assert clone_resp.status_code == 200
    assert clone_resp.json()["id"] == "kb-new"

    await client.patch("/api/kb/kb-new/tags", json={"tags": ["coe"]})

    respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        return_value=Response(200, json={"documents": [["x"]], "distances": [[0.5]], "metadatas": [[{}]]})
    )
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(return_value=Response(200, json=RAW_COMPLETION))

    ask_resp = await client.post("/api/ask/route", json={"tag": "coe", "query": "q", "model": "gpt-5.4"})
    assert ask_resp.status_code == 200
    body = ask_resp.json()
    # kb-old is kb-new's parent and both are tagged "coe" — only the newer
    # kb-new should have been queried at all.
    assert body["collection_scores"] == {"kb-new": 0.5}
    assert body["winning_collection_id"] == "kb-new"


@respx.mock
async def test_ask_by_tag_keeps_unrelated_collections_that_share_a_tag(client):
    respx.get("http://fake-owui.test/api/v1/knowledge/").mock(
        return_value=Response(
            200,
            json=[
                {"id": "kb-a", "name": "A", "description": ""},
                {"id": "kb-b", "name": "B", "description": ""},
            ],
        )
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        side_effect=[
            Response(200, json={"id": "kb-a", "name": "A", "description": ""}),
            Response(200, json={"id": "kb-b", "name": "B", "description": ""}),
        ]
    )
    await client.post("/api/kb", json={"name": "A", "version_tag": "v1.0"})
    await client.post("/api/kb", json={"name": "B", "version_tag": "v1.0"})
    await client.patch("/api/kb/kb-a/tags", json={"tags": ["coe"]})
    await client.patch("/api/kb/kb-b/tags", json={"tags": ["coe"]})

    respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        side_effect=[
            Response(200, json={"documents": [["a"]], "distances": [[0.8]], "metadatas": [[{}]]}),
            Response(200, json={"documents": [["b"]], "distances": [[0.3]], "metadatas": [[{}]]}),
        ]
    )
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(return_value=Response(200, json=RAW_COMPLETION))

    ask_resp = await client.post("/api/ask/route", json={"tag": "coe", "query": "q", "model": "gpt-5.4"})
    assert ask_resp.status_code == 200
    assert ask_resp.json()["collection_scores"] == {"kb-a": 0.8, "kb-b": 0.3}


@respx.mock
async def test_ask_by_unknown_tag_400s(client):
    respx.get("http://fake-owui.test/api/v1/knowledge/").mock(return_value=Response(200, json=[]))
    resp = await client.post("/api/ask/route", json={"tag": "nope", "query": "q", "model": "gpt-5.4"})
    assert resp.status_code == 400
    assert "nope" in resp.json()["detail"]


@respx.mock
async def test_ask_surfaces_a_502_not_a_raw_500_when_owui_rejects_tag_resolution(client):
    """Resolving a tag has to list Open WebUI's own knowledge bases first —
    if that call itself fails (e.g. the proxy's saved connection token got
    invalidated by an Open WebUI upgrade), it must come back as a clean 502
    with the real detail, not an unhandled exception bubbling up as a bare
    500 with no useful information."""
    respx.get("http://fake-owui.test/api/v1/knowledge/").mock(
        return_value=Response(401, json={"detail": "401 Unauthorized"})
    )
    for path in ("/api/ask/route", "/api/ask/joint"):
        resp = await client.post(path, json={"tag": "coe", "query": "q", "model": "gpt-5.4"})
        assert resp.status_code == 502
        assert "401" in resp.json()["detail"]


async def test_ask_rejects_neither_collection_ids_nor_tag(client):
    resp = await client.post("/api/ask/route", json={"query": "q", "model": "gpt-5.4"})
    assert resp.status_code == 400


async def test_ask_rejects_both_collection_ids_and_tag(client):
    resp = await client.post(
        "/api/ask/route", json={"collection_ids": ["kb-a"], "tag": "coe", "query": "q", "model": "gpt-5.4"}
    )
    assert resp.status_code == 400
