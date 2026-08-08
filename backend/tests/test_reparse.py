import respx
from httpx import Response


@respx.mock
async def test_reparse_uses_the_cached_true_original_and_returns_fresh_text_without_saving(client):
    """Re-running our own parser against the real original must return the
    freshly extracted text but never push it anywhere on its own — the user
    still has to press Update, exactly like any other edit."""
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-1", "name": "Docs", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-1/file/add").mock(return_value=Response(200))
    await client.post("/api/kb", json={"name": "Docs", "version_tag": "v1.0"})

    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-new", "filename": "doc.md"})
    )
    respx.post("http://fake-owui.test/api/v1/files/file-new/rename").mock(return_value=Response(200, json={}))

    files = {"file": ("doc.txt", b"Line one.\nLine two.", "text/plain")}
    upload_resp = await client.post("/api/documents", files=files)
    session_id = upload_resp.json()["session_id"]
    await client.patch(
        f"/api/documents/{session_id}",
        json={"text": "Line one.\nLine two. EDITED BY USER", "target_knowledge_id": "kb-1"},
    )
    finalize_resp = await client.post(f"/api/documents/{session_id}/finalize")
    assert finalize_resp.status_code == 200

    respx.get("http://fake-owui.test/api/v1/retrieval/config").mock(
        return_value=Response(200, json={"CHUNK_SIZE": 1000, "CHUNK_OVERLAP": 100, "TEXT_SPLITTER": ""})
    )

    reparse_resp = await client.post("/api/kb/kb-1/files/file-new/reparse")
    assert reparse_resp.status_code == 200
    body = reparse_resp.json()
    # comes back from the true original, not the user's edited/pushed text
    assert "Line one." in body["content"]
    assert "Line two." in body["content"]
    assert "EDITED BY USER" not in body["content"]

    # nothing was pushed anywhere by the reparse call itself
    respx.get("http://fake-owui.test/api/v1/files/file-new/data/content").mock(
        return_value=Response(200, json={"content": "Line one.\nLine two. EDITED BY USER"})
    )
    content_resp = await client.get("/api/kb/kb-1/files/file-new")
    assert content_resp.json()["content"] == "Line one.\nLine two. EDITED BY USER"


@respx.mock
async def test_reparse_falls_back_to_owuis_raw_bytes_when_no_local_original_is_cached(client):
    """Files with no proxy-side original cache (entered the collection some
    other way) still reparse — from whatever Open WebUI itself has stored."""
    respx.get("http://fake-owui.test/api/v1/files/file-x/content").mock(
        return_value=Response(
            200,
            content=b"Raw plain text from Open WebUI.",
            headers={"content-type": "text/plain", "content-disposition": "inline; filename*=UTF-8''raw.txt"},
        )
    )
    respx.get("http://fake-owui.test/api/v1/retrieval/config").mock(
        return_value=Response(200, json={"CHUNK_SIZE": 1000, "CHUNK_OVERLAP": 100, "TEXT_SPLITTER": ""})
    )

    resp = await client.post("/api/kb/kb-1/files/file-x/reparse")
    assert resp.status_code == 200
    assert "Raw plain text from Open WebUI." in resp.json()["content"]


@respx.mock
async def test_reparse_surfaces_owui_errors_when_no_cache_and_owui_has_nothing(client):
    respx.get("http://fake-owui.test/api/v1/files/missing/content").mock(
        return_value=Response(404, json={"detail": "Not found"})
    )
    resp = await client.post("/api/kb/kb-1/files/missing/reparse")
    assert resp.status_code == 502
