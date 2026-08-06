import zipfile
from io import BytesIO

import respx
from httpx import Response

SAMPLE_HTML = """<!DOCTYPE html>
<html><head><style>body{color:red}</style></head>
<body><main class="main">
<h2>Module 01 — Intro</h2>
<p>UVSS is a vehicle inspection system that customers value for its speed.</p>
</main></body></html>"""


def _scorm_zip_bytes() -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("imsmanifest.xml", "<manifest/>")
        zf.writestr("index.html", SAMPLE_HTML)
    return buf.getvalue()


async def _create_project_with_module(client, name="Output Test Project"):
    project = (
        await client.post(
            "/api/courses",
            json={
                "name": name,
                "product_knowledge_ids": ["kb-product"],
                "instructions_knowledge_ids": ["kb-instructions"],
            },
        )
    ).json()
    module = (
        await client.post(f"/api/courses/{project['id']}/modules", json={"title": "Module 01 — Intro"})
    ).json()
    return project, module


@respx.mock
async def test_first_publish_creates_output_kb_and_manifest_file(client):
    project, module = await _create_project_with_module(client)

    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "Output Test Project — Output", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    upload_route = respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-manifest-1", "filename": "Module 01 — Intro.md"})
    )

    files = {"file": ("module_01.zip", b"PK\x03\x04fakezipbytes", "application/zip")}
    resp = await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output",
        files=files,
        data={"notes": "First cut of module 1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["version_tag"] == "v1.0"
    assert body["filename"] == "module_01.zip"
    assert body["is_current"] is True
    assert body["size"] == len(b"PK\x03\x04fakezipbytes")

    assert upload_route.called
    manifest_call = upload_route.calls[-1]  # raw artifact uploads first, then the manifest text
    assert b"First cut of module 1" in manifest_call.request.content

    project_after = (await client.get(f"/api/courses/{project['id']}")).json()
    assert project_after["output_knowledge_id"] == "kb-output"

    modules_after = (await client.get(f"/api/courses/{project['id']}/modules")).json()
    assert modules_after[0]["current_output_version"] == "v1.0"
    assert modules_after[0]["output_filename"] == "module_01.zip"


@respx.mock
async def test_republish_updates_manifest_and_keeps_history(client):
    project, module = await _create_project_with_module(client)

    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-manifest-1", "filename": "m.md"})
    )
    await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output",
        files={"file": ("v1.zip", b"version one bytes", "application/zip")},
    )

    update_route = respx.post("http://fake-owui.test/api/v1/files/file-manifest-1/data/content/update").mock(
        return_value=Response(200)
    )
    resp = await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output",
        files={"file": ("v2.zip", b"version two, longer bytes", "application/zip")},
    )
    assert resp.status_code == 200
    assert update_route.called
    body = resp.json()
    assert body["filename"] == "v2.zip"
    assert body["version_tag"] == "v1.0"  # collection tag hasn't been bumped yet

    versions = (
        await client.get(f"/api/courses/{project['id']}/modules/{module['id']}/output/versions")
    ).json()
    assert len(versions) == 2
    current = next(v for v in versions if v["is_current"])
    old = next(v for v in versions if not v["is_current"])
    assert current["filename"] == "v2.zip"
    assert old["filename"] == "v1.zip"


@respx.mock
async def test_deleting_the_manifest_file_lets_the_next_publish_reupload_instead_of_502ing(client):
    """A course module's output manifest is an ordinary file inside the
    output KB — deletable through the generic KB file-delete endpoint just
    like any other file. Confirmed bug: without clearing owui_file_id there,
    the next publish tried to update_file_content a file Open WebUI no
    longer had, failing with 502 instead of just uploading a fresh one."""
    project, module = await _create_project_with_module(client)

    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-manifest-1", "filename": "m.md"})
    )
    await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output",
        files={"file": ("v1.zip", b"version one bytes", "application/zip")},
    )

    # delete the manifest file exactly like clicking "delete" on it in the
    # Knowledge tab would — the generic KB file-delete endpoint
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/remove").mock(return_value=Response(200))
    delete_resp = await client.delete("/api/kb/kb-output/files/file-manifest-1")
    assert delete_resp.status_code == 200

    # republish: must upload a FRESH manifest (create+link), never try to
    # update the now-nonexistent file-manifest-1
    update_route = respx.post("http://fake-owui.test/api/v1/files/file-manifest-1/data/content/update").mock(
        return_value=Response(200)
    )
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-manifest-2", "filename": "m.md"})
    )
    resp = await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output",
        files={"file": ("v2.zip", b"version two bytes", "application/zip")},
    )
    assert resp.status_code == 200
    assert not update_route.called
    body = resp.json()
    assert body["is_current"] is True


@respx.mock
async def test_download_returns_the_exact_bytes_for_each_version(client):
    project, module = await _create_project_with_module(client)
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-manifest-1", "filename": "m.md"})
    )
    await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output",
        files={"file": ("v1.zip", b"THE ORIGINAL BYTES", "application/zip")},
    )
    versions = (
        await client.get(f"/api/courses/{project['id']}/modules/{module['id']}/output/versions")
    ).json()
    version_id = versions[0]["id"]

    download_resp = await client.get(
        f"/api/courses/{project['id']}/modules/{module['id']}/output/versions/{version_id}/download"
    )
    assert download_resp.status_code == 200
    assert download_resp.content == b"THE ORIGINAL BYTES"
    assert "v1.zip" in download_resp.headers["content-disposition"]


@respx.mock
async def test_bump_output_version_then_republish_shows_changed_vs_since(client):
    """Mirrors the ordinary knowledge-base file diff UI: after cutting a new
    release, only the module that actually got a new output shows "changed
    in the new version" — untouched modules still show the old tag."""
    project, module_a = await _create_project_with_module(client, name="Two Module Project")
    module_b = (
        await client.post(f"/api/courses/{project['id']}/modules", json={"title": "Module 02"})
    ).json()

    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        side_effect=[
            Response(200, json={"id": "raw-a-1", "filename": "a-v1.zip"}),  # raw artifact upload
            Response(200, json={"id": "file-a", "filename": "a.md"}),  # manifest text upload
            Response(200, json={"id": "raw-b-1", "filename": "b-v1.zip"}),
            Response(200, json={"id": "file-b", "filename": "b.md"}),
            Response(200, json={"id": "raw-a-2", "filename": "a-v2.zip"}),  # a's republish raw upload
        ]
    )
    await client.post(
        f"/api/courses/{project['id']}/modules/{module_a['id']}/output",
        files={"file": ("a-v1.zip", b"a v1", "application/zip")},
    )
    await client.post(
        f"/api/courses/{project['id']}/modules/{module_b['id']}/output",
        files={"file": ("b-v1.zip", b"b v1", "application/zip")},
    )

    bump_resp = await client.post(f"/api/courses/{project['id']}/bump-output-version", json={"version_tag": "v1.1"})
    assert bump_resp.status_code == 200

    respx.post("http://fake-owui.test/api/v1/files/file-a/data/content/update").mock(return_value=Response(200))
    await client.post(
        f"/api/courses/{project['id']}/modules/{module_a['id']}/output",
        files={"file": ("a-v2.zip", b"a v2 changed", "application/zip")},
    )

    modules = (await client.get(f"/api/courses/{project['id']}/modules")).json()
    by_id = {m["id"]: m for m in modules}
    assert by_id[module_a["id"]]["current_output_version"] == "v1.1"
    assert by_id[module_b["id"]]["current_output_version"] == "v1.0"

    # and the underlying KB file listing shows the same "changed" semantics
    # already used everywhere else in the app
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-output/files").mock(
        return_value=Response(
            200,
            json={
                "items": [
                    {"id": "file-a", "filename": "a.md", "meta": {}},
                    {"id": "file-b", "filename": "b.md", "meta": {}},
                ]
            },
        )
    )
    kb_files = (await client.get("/api/kb/kb-output/files")).json()
    file_a = next(f for f in kb_files if f["id"] == "file-a")
    file_b = next(f for f in kb_files if f["id"] == "file-b")
    assert file_a["changed"] is True
    assert file_a["last_change_method"] == "output_republish"
    assert file_b["changed"] is False


async def test_bump_output_version_requires_an_existing_output(client):
    project = (
        await client.post(
            "/api/courses",
            json={"name": "No output yet", "product_knowledge_ids": ["kb-p"], "instructions_knowledge_ids": ["kb-i"]},
        )
    ).json()
    resp = await client.post(f"/api/courses/{project['id']}/bump-output-version", json={"version_tag": "v1.1"})
    assert resp.status_code == 400


@respx.mock
async def test_publish_scorm_zip_pushes_real_lecture_text_not_just_a_manifest(client):
    project, module = await _create_project_with_module(client)
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    upload_route = respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-1", "filename": "m.md"})
    )

    resp = await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output",
        files={"file": ("module_01.zip", _scorm_zip_bytes(), "application/zip")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_html"] is True

    kb_content = upload_route.calls[-1].request.content.decode("utf-8")  # raw artifact uploads first
    # multipart body — just check the real lecture text made it through
    assert "UVSS is a vehicle inspection system that customers value for its speed." in kb_content
    assert "Module 01 — Intro" in kb_content


@respx.mock
async def test_view_output_version_serves_html_inline(client):
    project, module = await _create_project_with_module(client)
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-1", "filename": "m.md"})
    )
    await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output",
        files={"file": ("module_01.zip", _scorm_zip_bytes(), "application/zip")},
    )
    versions = (
        await client.get(f"/api/courses/{project['id']}/modules/{module['id']}/output/versions")
    ).json()
    version_id = versions[0]["id"]

    view_resp = await client.get(
        f"/api/courses/{project['id']}/modules/{module['id']}/output/versions/{version_id}/view"
    )
    assert view_resp.status_code == 200
    assert view_resp.headers["content-type"].startswith("text/html")
    assert "Module 01 — Intro" in view_resp.text
    assert "attachment" not in view_resp.headers.get("content-disposition", "")


async def test_view_output_version_404s_when_no_html_was_found(client):
    project, module = await _create_project_with_module(client)
    with respx.mock:
        respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
            return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
        )
        respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
        respx.post("http://fake-owui.test/api/v1/files/").mock(
            return_value=Response(200, json={"id": "file-1", "filename": "m.md"})
        )
        await client.post(
            f"/api/courses/{project['id']}/modules/{module['id']}/output",
            files={"file": ("notes.txt", b"plain text, not html or a zip", "text/plain")},
        )
    versions = (
        await client.get(f"/api/courses/{project['id']}/modules/{module['id']}/output/versions")
    ).json()
    assert versions[0]["has_html"] is False
    resp = await client.get(
        f"/api/courses/{project['id']}/modules/{module['id']}/output/versions/{versions[0]['id']}/view"
    )
    assert resp.status_code == 404


@respx.mock
async def test_resync_reextracts_content_without_creating_a_new_version(client):
    project, module = await _create_project_with_module(client)
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-1", "filename": "m.md"})
    )
    await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output",
        files={"file": ("module_01.zip", _scorm_zip_bytes(), "application/zip")},
    )

    update_route = respx.post("http://fake-owui.test/api/v1/files/file-1/data/content/update").mock(
        return_value=Response(200)
    )
    resync_resp = await client.post(f"/api/courses/{project['id']}/modules/{module['id']}/output/resync")
    assert resync_resp.status_code == 200
    assert update_route.called
    assert "UVSS is a vehicle inspection system" in update_route.calls[0].request.content.decode("utf-8")

    versions = (
        await client.get(f"/api/courses/{project['id']}/modules/{module['id']}/output/versions")
    ).json()
    assert len(versions) == 1  # resync did not create a new version


@respx.mock
async def test_publish_stores_the_raw_artifact_as_its_own_real_file_in_open_webui(client):
    """The requirement: whatever we publish must genuinely live inside Open
    WebUI too, not just our local disk cache — even a zip, which can never be
    linked into a knowledge base's own file list (see upload_raw_file)."""
    project, module = await _create_project_with_module(client)
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    upload_route = respx.post("http://fake-owui.test/api/v1/files/").mock(
        side_effect=[
            Response(200, json={"id": "raw-file-1", "filename": "module_01.zip"}),
            Response(200, json={"id": "file-manifest-1", "filename": "m.md"}),
        ]
    )

    resp = await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output",
        files={"file": ("module_01.zip", _scorm_zip_bytes(), "application/zip")},
    )
    assert resp.status_code == 200
    assert resp.json()["raw_owui_file_id"] == "raw-file-1"

    raw_upload_call = upload_route.calls[0]
    assert raw_upload_call.request.url.params["process"] == "false"
    assert _scorm_zip_bytes() in raw_upload_call.request.content


@respx.mock
async def test_publish_fails_loudly_if_the_raw_artifact_upload_fails(client):
    """Silently degrading here would quietly break the "every published file
    genuinely lives in Open WebUI" guarantee — it must fail the whole
    publish instead."""
    project, module = await _create_project_with_module(client)
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(500, json={"detail": "Storage backend unavailable"})
    )

    resp = await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output",
        files={"file": ("module_01.zip", _scorm_zip_bytes(), "application/zip")},
    )
    assert resp.status_code == 502

    versions = (
        await client.get(f"/api/courses/{project['id']}/modules/{module['id']}/output/versions")
    ).json()
    assert versions == []  # no partial version left behind
