import json

import respx
from httpx import Response


@respx.mock
async def test_finalize_restores_the_original_filename_after_upload(client):
    """Open WebUI must receive a .md-suffixed upload (see finalize_document's
    own comment on why), but the file's *display* name should end up back as
    the real original — including its real extension — once uploaded."""
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-1", "name": "Docs", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-1/file/add").mock(return_value=Response(200))
    await client.post("/api/kb", json={"name": "Docs", "version_tag": "v1.0"})

    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-new", "filename": "datasheet.md"})
    )
    rename_route = respx.post("http://fake-owui.test/api/v1/files/file-new/rename").mock(
        return_value=Response(200, json={})
    )

    files = {"file": ("datasheet.txt", b"some plain text content", "text/plain")}
    upload_resp = await client.post("/api/documents", files=files)
    session_id = upload_resp.json()["session_id"]
    await client.patch(f"/api/documents/{session_id}", json={"target_knowledge_id": "kb-1"})
    finalize_resp = await client.post(f"/api/documents/{session_id}/finalize")
    assert finalize_resp.status_code == 200

    assert rename_route.called
    assert json.loads(rename_route.calls[0].request.content) == {"filename": "datasheet.txt"}


@respx.mock
async def test_finalize_still_succeeds_when_the_rename_call_fails(client):
    """The rename is cosmetic — a failure here must not fail an otherwise-
    successful upload the user is waiting on."""
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-1", "name": "Docs", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-1/file/add").mock(return_value=Response(200))
    await client.post("/api/kb", json={"name": "Docs", "version_tag": "v1.0"})

    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-new", "filename": "datasheet.md"})
    )
    respx.post("http://fake-owui.test/api/v1/files/file-new/rename").mock(
        return_value=Response(500, json={"detail": "boom"})
    )

    files = {"file": ("datasheet.txt", b"some plain text content", "text/plain")}
    upload_resp = await client.post("/api/documents", files=files)
    session_id = upload_resp.json()["session_id"]
    await client.patch(f"/api/documents/{session_id}", json={"target_knowledge_id": "kb-1"})
    finalize_resp = await client.post(f"/api/documents/{session_id}/finalize")
    assert finalize_resp.status_code == 200
    assert finalize_resp.json()["owui_file_id"] == "file-new"


@respx.mock
async def test_clone_restores_each_copied_files_original_name(client):
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        side_effect=[
            Response(200, json={"id": "kb-old", "name": "Docs", "description": ""}),
            Response(200, json={"id": "kb-new", "name": "Docs v2", "description": ""}),
        ]
    )
    await client.post("/api/kb", json={"name": "Docs", "version_tag": "v1.0"})

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-old/files").mock(
        return_value=Response(200, json={"items": [{"id": "file-a", "filename": "datasheet.pdf", "meta": {}}]})
    )
    respx.get("http://fake-owui.test/api/v1/files/file-a/data/content").mock(
        return_value=Response(200, json={"content": "content A"})
    )
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-a2", "filename": "datasheet.md"})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-new/file/add").mock(return_value=Response(200))
    rename_route = respx.post("http://fake-owui.test/api/v1/files/file-a2/rename").mock(
        return_value=Response(200, json={})
    )

    resp = await client.post("/api/kb/kb-old/clone", json={"name": "Docs v2", "version_tag": "v1.1"})
    assert resp.status_code == 200
    assert resp.json()["files_copied"] == 1

    assert rename_route.called
    assert json.loads(rename_route.calls[0].request.content) == {"filename": "datasheet.pdf"}


@respx.mock
async def test_rename_knowledge_file_updates_the_display_name(client):
    rename_route = respx.post("http://fake-owui.test/api/v1/files/file-a/rename").mock(
        return_value=Response(200, json={})
    )
    resp = await client.patch("/api/kb/kb-1/files/file-a/name", json={"filename": "datasheet.pdf"})
    assert resp.status_code == 200
    assert resp.json()["filename"] == "datasheet.pdf"
    assert resp.json()["has_pdf_original"] is True

    assert json.loads(rename_route.calls[0].request.content) == {"filename": "datasheet.pdf"}


@respx.mock
async def test_rename_knowledge_file_rejects_an_empty_name(client):
    resp = await client.patch("/api/kb/kb-1/files/file-a/name", json={"filename": "   "})
    assert resp.status_code == 400


@respx.mock
async def test_rename_knowledge_file_surfaces_owui_errors(client):
    respx.post("http://fake-owui.test/api/v1/files/file-a/rename").mock(
        return_value=Response(404, json={"detail": "Not found"})
    )
    resp = await client.patch("/api/kb/kb-1/files/file-a/name", json={"filename": "new-name.txt"})
    assert resp.status_code == 502
