import respx
from httpx import Response

from app.models import OriginalFileBlob
from app.original_storage import purge_orphaned, save_original


@respx.mock
async def test_get_original_file_streams_bytes_and_content_type(client):
    respx.get("http://fake-owui.test/api/v1/files/file-a/content").mock(
        return_value=Response(
            200,
            content=b"%PDF-1.4 fake pdf bytes",
            headers={
                "content-type": "application/pdf",
                "content-disposition": "inline; filename*=UTF-8''manual.pdf",
            },
        )
    )

    resp = await client.get("/api/kb/kb-1/files/file-a/original")
    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 fake pdf bytes"
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["x-original-filename"] == "manual.pdf"


@respx.mock
async def test_get_original_file_surfaces_owui_errors(client):
    respx.get("http://fake-owui.test/api/v1/files/missing-file/content").mock(
        return_value=Response(404, json={"detail": "Not found"})
    )

    resp = await client.get("/api/kb/kb-1/files/missing-file/original")
    assert resp.status_code == 502


@respx.mock
async def test_finalize_caches_the_true_pre_redaction_original(client):
    """The proxy's own local cache keeps the real original — including
    anything later redacted before it ever reached Open WebUI. That's the
    whole point: Open WebUI only sees the cleaned text, but the "existing
    file" pane can still show a faithful original on this machine.
    """
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-1", "name": "Docs", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-1/file/add").mock(return_value=Response(200))
    await client.post("/api/kb", json={"name": "Docs", "version_tag": "v1.0"})

    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-new", "filename": "doc.md"})
    )

    files = {"file": ("doc.txt", b"secret: ABC123\nnormal content", "text/plain")}
    upload_resp = await client.post("/api/documents", files=files)
    session_id = upload_resp.json()["session_id"]
    await client.patch(
        f"/api/documents/{session_id}",
        json={
            "text": "secret: ABC123\nnormal content",
            "redactions": [{"start": 8, "end": 14}],
            "target_knowledge_id": "kb-1",
        },
    )
    finalize_resp = await client.post(f"/api/documents/{session_id}/finalize")
    assert finalize_resp.status_code == 200

    original_resp = await client.get("/api/kb/kb-1/files/file-new/original")
    assert original_resp.status_code == 200
    assert original_resp.headers["x-original-source"] == "proxy-cache"
    assert b"ABC123" in original_resp.content  # the true original, unredacted
    assert original_resp.headers["x-original-filename"] == "doc.txt"


@respx.mock
async def test_replace_file_recaches_new_original_and_drops_old_one(client):
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-1", "name": "Docs", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-1/file/add").mock(return_value=Response(200))
    await client.post("/api/kb", json={"name": "Docs", "version_tag": "v1.0"})

    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-a", "filename": "a.md"})
    )
    files = {"file": ("first.txt", b"first version", "text/plain")}
    upload_resp = await client.post("/api/documents", files=files)
    session_id = upload_resp.json()["session_id"]
    await client.patch(f"/api/documents/{session_id}", json={"target_knowledge_id": "kb-1"})
    await client.post(f"/api/documents/{session_id}/finalize")

    first_original = await client.get("/api/kb/kb-1/files/file-a/original")
    assert first_original.content == b"first version"

    respx.post("http://fake-owui.test/api/v1/files/file-a/data/content/update").mock(return_value=Response(200))
    files = {"file": ("second.txt", b"second version", "text/plain")}
    upload_resp2 = await client.post("/api/documents", files=files)
    session_id2 = upload_resp2.json()["session_id"]
    await client.patch(
        f"/api/documents/{session_id2}",
        json={"target_knowledge_id": "kb-1", "replace_file_id": "file-a"},
    )
    finalize_resp2 = await client.post(f"/api/documents/{session_id2}/finalize")
    assert finalize_resp2.status_code == 200

    second_original = await client.get("/api/kb/kb-1/files/file-a/original")
    assert second_original.content == b"second version"
    assert second_original.headers["x-original-filename"] == "second.txt"


@respx.mock
async def test_delete_file_removes_cached_original(client):
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-1", "name": "Docs", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-1/file/add").mock(return_value=Response(200))
    await client.post("/api/kb", json={"name": "Docs", "version_tag": "v1.0"})
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-a", "filename": "a.md"})
    )
    files = {"file": ("first.txt", b"content", "text/plain")}
    upload_resp = await client.post("/api/documents", files=files)
    session_id = upload_resp.json()["session_id"]
    await client.patch(f"/api/documents/{session_id}", json={"target_knowledge_id": "kb-1"})
    await client.post(f"/api/documents/{session_id}/finalize")

    respx.post("http://fake-owui.test/api/v1/knowledge/kb-1/file/remove").mock(return_value=Response(200, json=True))
    delete_resp = await client.delete("/api/kb/kb-1/files/file-a")
    assert delete_resp.status_code == 200

    respx.get("http://fake-owui.test/api/v1/files/file-a/content").mock(
        return_value=Response(404, json={"detail": "Not found"})
    )
    original_resp = await client.get("/api/kb/kb-1/files/file-a/original")
    assert original_resp.status_code == 502  # cache is gone, and Open WebUI has nothing either


@respx.mock
async def test_original_for_a_course_output_file_serves_its_current_html_not_owuis_frozen_upload(client):
    """A course-generator output file's Open WebUI content gets replaced in
    place on every republish (update_file_content -> .../data/content/update),
    but Open WebUI's raw .../content endpoint keeps serving whatever bytes
    were uploaded the FIRST time for that file_id, forever — confirmed live
    against a real instance. So /original for these files must come from our
    own current cached HTML, not that frozen blob (which get_file_raw would
    otherwise return, showing a stale, possibly many-versions-old page).
    """
    project = (
        await client.post(
            "/api/courses",
            json={"name": "Original Test Project", "product_knowledge_ids": ["kb-p"], "instructions_knowledge_ids": ["kb-i"]},
        )
    ).json()
    module = (
        await client.post(f"/api/courses/{project['id']}/modules", json={"title": "Module 01"})
    ).json()

    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-out-1", "filename": "m.md"})
    )
    v1_html = "<html><body>version one</body></html>"
    await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output",
        files={"file": ("module_01.html", v1_html.encode("utf-8"), "text/html")},
    )

    respx.post("http://fake-owui.test/api/v1/files/file-out-1/data/content/update").mock(return_value=Response(200))
    v2_html = "<html><body>version two, republished</body></html>"
    await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output",
        files={"file": ("module_01.html", v2_html.encode("utf-8"), "text/html")},
    )

    # Even if Open WebUI's raw endpoint is hit, it must never win for this file.
    respx.get("http://fake-owui.test/api/v1/files/file-out-1/content").mock(
        return_value=Response(
            200,
            content=v1_html.encode("utf-8"),
            headers={"content-type": "text/html", "content-disposition": "inline; filename*=UTF-8''module_01.html"},
        )
    )

    resp = await client.get(f"/api/kb/kb-output/files/file-out-1/original")
    assert resp.status_code == 200
    assert resp.content == v2_html.encode("utf-8")
    assert resp.headers["x-original-source"] == "course-generator-current-version"


async def test_purge_orphaned_removes_unclaimed_originals(client, tmp_path):
    import app.db as db_module

    async with db_module.AsyncSessionLocal() as session:
        await save_original(session, "abandoned-session", "ghost.pdf", "application/pdf", b"bytes")
        await session.commit()

    async with db_module.AsyncSessionLocal() as session:
        await purge_orphaned(session, older_than_hours=-1)  # treat everything as old enough
        await session.commit()

    async with db_module.AsyncSessionLocal() as session:
        from sqlalchemy import select

        rows = (await session.execute(select(OriginalFileBlob))).scalars().all()
        assert rows == []
