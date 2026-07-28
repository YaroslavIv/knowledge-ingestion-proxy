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
