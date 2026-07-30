import respx
from httpx import Response


@respx.mock
async def test_latest_by_tag_collapses_a_clone_lineage_and_includes_names(client):
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
    await client.patch("/api/kb/kb-old/tags", json={"tags": ["coe"]})

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-old/files").mock(return_value=Response(200, json=[]))
    await client.post("/api/kb/kb-old/clone", json={"name": "CoE New", "version_tag": "v1.1"})
    await client.patch("/api/kb/kb-new/tags", json={"tags": ["coe"]})

    resp = await client.get("/api/tags/coe/collections")
    assert resp.status_code == 200
    body = resp.json()
    assert body == [{"id": "kb-new", "name": "CoE New", "version_tag": "v1.1"}]


@respx.mock
async def test_latest_by_tag_returns_empty_list_for_an_unknown_tag(client):
    respx.get("http://fake-owui.test/api/v1/knowledge/").mock(return_value=Response(200, json=[]))
    resp = await client.get("/api/tags/nope/collections")
    assert resp.status_code == 200
    assert resp.json() == []
