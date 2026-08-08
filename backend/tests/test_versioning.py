import json

import respx
from httpx import Response

from app.versioning import suggest_next_version_tag


def test_suggest_next_version_tag_bumps_trailing_minor():
    assert suggest_next_version_tag("uvss 2.0") == "uvss 2.1"
    assert suggest_next_version_tag("v1.9") == "v1.10"


def test_suggest_next_version_tag_falls_back_without_numeric_pattern():
    assert suggest_next_version_tag("release") == "release v2"


@respx.mock
async def test_create_knowledge_base_records_version_tag(client):
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-1", "name": "Docs", "description": ""})
    )

    resp = await client.post("/api/kb", json={"name": "Docs", "version_tag": "uvss 2.0"})
    assert resp.status_code == 200
    assert resp.json()["version_tag"] == "uvss 2.0"

    respx.get("http://fake-owui.test/api/v1/knowledge/").mock(
        return_value=Response(200, json=[{"id": "kb-1", "name": "Docs", "description": ""}])
    )
    list_resp = await client.get("/api/kb")
    assert list_resp.json()[0]["version_tag"] == "uvss 2.0"


@respx.mock
async def test_text_edit_bumps_only_the_edited_file_to_current_tag(client):
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-1", "name": "Docs", "description": ""})
    )
    await client.post("/api/kb", json={"name": "Docs", "version_tag": "uvss 2.0"})

    respx.post("http://fake-owui.test/api/v1/files/file-a/data/content/update").mock(return_value=Response(200))
    respx.get("http://fake-owui.test/api/v1/retrieval/config").mock(
        return_value=Response(200, json={"CHUNK_SIZE": 1000, "CHUNK_OVERLAP": 100, "TEXT_SPLITTER": ""})
    )

    update_resp = await client.post(
        "/api/kb/kb-1/files/file-a/content", json={"text": "new content", "redactions": []}
    )
    assert update_resp.status_code == 200

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-1/files").mock(
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
    files_resp = await client.get("/api/kb/kb-1/files")
    files = {f["id"]: f for f in files_resp.json()}

    assert files["file-a"]["version_tag"] == "uvss 2.0"
    assert files["file-a"]["changed"] is True
    assert files["file-a"]["last_change_method"] == "text_edit"

    # file-b was never touched — synthesized fresh, also "changed" since it
    # has no prior tracked history (matches the collection's only tag so far).
    assert files["file-b"]["last_change_method"] is None


@respx.mock
async def test_finalize_new_file_is_tracked_as_introduced_in_current_version(client):
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-1", "name": "Docs", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-1/file/add").mock(return_value=Response(200))
    await client.post("/api/kb", json={"name": "Docs", "version_tag": "uvss 2.0"})

    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-new", "filename": "doc.md"})
    )
    respx.post("http://fake-owui.test/api/v1/files/file-new/rename").mock(return_value=Response(200, json={}))

    files = {"file": ("doc.txt", b"hello world", "text/plain")}
    upload_resp = await client.post("/api/documents", files=files)
    session_id = upload_resp.json()["session_id"]
    await client.patch(f"/api/documents/{session_id}", json={"target_knowledge_id": "kb-1"})
    finalize_resp = await client.post(f"/api/documents/{session_id}/finalize")
    assert finalize_resp.status_code == 200
    assert finalize_resp.json()["owui_file_id"] == "file-new"

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-1/files").mock(
        return_value=Response(200, json={"items": [{"id": "file-new", "filename": "doc.md", "meta": {}}]})
    )
    files_resp = await client.get("/api/kb/kb-1/files")
    file_entry = files_resp.json()[0]
    assert file_entry["version_tag"] == "uvss 2.0"
    assert file_entry["changed"] is True
    assert file_entry["last_change_method"] is None


@respx.mock
async def test_finalize_replace_file_bumps_the_same_file_id(client):
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-1", "name": "Docs", "description": ""})
    )
    await client.post("/api/kb", json={"name": "Docs", "version_tag": "uvss 2.1"})

    respx.post("http://fake-owui.test/api/v1/files/existing-file/data/content/update").mock(return_value=Response(200))

    files = {"file": ("doc.txt", b"replacement content", "text/plain")}
    upload_resp = await client.post("/api/documents", files=files)
    session_id = upload_resp.json()["session_id"]
    await client.patch(
        f"/api/documents/{session_id}",
        json={"target_knowledge_id": "kb-1", "replace_file_id": "existing-file"},
    )
    finalize_resp = await client.post(f"/api/documents/{session_id}/finalize")
    assert finalize_resp.status_code == 200
    assert finalize_resp.json()["owui_file_id"] == "existing-file"

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-1/files").mock(
        return_value=Response(200, json={"items": [{"id": "existing-file", "filename": "doc.md", "meta": {}}]})
    )
    files_resp = await client.get("/api/kb/kb-1/files")
    file_entry = files_resp.json()[0]
    assert file_entry["version_tag"] == "uvss 2.1"
    assert file_entry["last_change_method"] == "file_replace"


@respx.mock
async def test_update_file_tags(client):
    resp = await client.patch("/api/kb/kb-1/files/file-a/tags", json={"tags": ["important", "reviewed"]})
    assert resp.status_code == 200
    assert resp.json()["tags"] == ["important", "reviewed"]


@respx.mock
async def test_clone_knowledge_base_copies_files_with_inherited_tag(client):
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        side_effect=[
            Response(200, json={"id": "kb-old", "name": "Docs", "description": ""}),
            Response(200, json={"id": "kb-new", "name": "Docs v2", "description": ""}),
        ]
    )
    await client.post("/api/kb", json={"name": "Docs", "version_tag": "uvss 2.0"})

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-old/files").mock(
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
    respx.get("http://fake-owui.test/api/v1/files/file-a/data/content").mock(
        return_value=Response(200, json={"content": "content A"})
    )
    respx.get("http://fake-owui.test/api/v1/files/file-b/data/content").mock(
        return_value=Response(200, json={"content": "content B"})
    )
    upload_route = respx.post("http://fake-owui.test/api/v1/files/").mock(
        side_effect=[
            Response(200, json={"id": "file-a2", "filename": "a.md"}),
            Response(200, json={"id": "file-b2", "filename": "b.md"}),
        ]
    )
    respx.post("http://fake-owui.test/api/v1/files/file-a2/rename").mock(return_value=Response(200, json={}))
    respx.post("http://fake-owui.test/api/v1/files/file-b2/rename").mock(return_value=Response(200, json={}))
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-new/file/add").mock(return_value=Response(200))

    clone_resp = await client.post("/api/kb/kb-old/clone", json={"name": "Docs v2", "version_tag": "uvss 2.1"})
    assert clone_resp.status_code == 200
    body = clone_resp.json()
    assert body == {"id": "kb-new", "name": "Docs v2", "version_tag": "uvss 2.1", "files_copied": 2, "skipped": []}

    # both copies uploaded into the *new* knowledge base
    for call in upload_route.calls:
        metadata = json.loads(_form_field(call.request, "metadata"))
        assert metadata == {"knowledge_id": "kb-new"}

    respx.get("http://fake-owui.test/api/v1/knowledge/").mock(
        return_value=Response(
            200,
            json=[
                {"id": "kb-old", "name": "Docs", "description": ""},
                {"id": "kb-new", "name": "Docs v2", "description": ""},
            ],
        )
    )
    detail_resp = await client.get("/api/kb/kb-new")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["version_tag"] == "uvss 2.1"
    assert detail["parent"] == {"knowledge_id": "kb-old", "name": "Docs", "version_tag": "uvss 2.0"}

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-new/files").mock(
        return_value=Response(
            200,
            json={
                "items": [
                    {"id": "file-a2", "filename": "a.md", "meta": {}},
                    {"id": "file-b2", "filename": "b.md", "meta": {}},
                ]
            },
        )
    )
    files_resp = await client.get("/api/kb/kb-new/files")
    for f in files_resp.json():
        # freshly cloned files inherit the *old* tag — nothing changed yet
        assert f["version_tag"] == "uvss 2.0"
        assert f["changed"] is False
        assert f["cloned_from_file_id"] in ("file-a", "file-b")


@respx.mock
async def test_clone_skips_a_file_with_no_extracted_content_and_still_copies_the_rest(client):
    """Confirmed live: one source file with no extracted content in Open
    WebUI (a binary/unprocessed file, or one whose extraction genuinely
    failed) made /file/add 400 on that single file and aborted the ENTIRE
    clone at 0 files copied — even though every other file was fine. The
    clone must skip the bad file and keep going instead."""
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        side_effect=[
            Response(200, json={"id": "kb-old", "name": "Docs", "description": ""}),
            Response(200, json={"id": "kb-new", "name": "Docs v2", "description": ""}),
        ]
    )
    await client.post("/api/kb", json={"name": "Docs", "version_tag": "v1.0"})

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-old/files").mock(
        return_value=Response(
            200,
            json={
                "items": [
                    {"id": "file-bad", "filename": "scan.pdf", "meta": {}},
                    {"id": "file-a", "filename": "a.md", "meta": {}},
                    {"id": "file-b", "filename": "b.md", "meta": {}},
                ]
            },
        )
    )
    respx.get("http://fake-owui.test/api/v1/files/file-bad/data/content").mock(
        return_value=Response(200, json={"content": ""})
    )
    respx.get("http://fake-owui.test/api/v1/files/file-a/data/content").mock(
        return_value=Response(200, json={"content": "content A"})
    )
    respx.get("http://fake-owui.test/api/v1/files/file-b/data/content").mock(
        return_value=Response(200, json={"content": "content B"})
    )
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        side_effect=[
            Response(200, json={"id": "file-bad2", "filename": "scan.pdf"}),
            Response(200, json={"id": "file-a2", "filename": "a.md"}),
            Response(200, json={"id": "file-b2", "filename": "b.md"}),
        ]
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-new/file/add").mock(
        side_effect=[
            Response(400, json={"detail": "Extracted content is not available for this file."}),
            Response(200),
            Response(200),
        ]
    )
    respx.post("http://fake-owui.test/api/v1/files/file-a2/rename").mock(return_value=Response(200, json={}))
    respx.post("http://fake-owui.test/api/v1/files/file-b2/rename").mock(return_value=Response(200, json={}))

    resp = await client.post("/api/kb/kb-old/clone", json={"name": "Docs v2", "version_tag": "v1.1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["files_copied"] == 2
    assert body["skipped"] == [
        {"filename": "scan.pdf", "reason": "Extracted content is not available for this file."}
    ]


@respx.mock
async def test_clone_rolls_back_the_empty_destination_kb_when_every_file_fails(client):
    """If literally every source file fails to copy, the resulting 'clone'
    is just an empty, useless KB — not a real partial clone. Must be cleaned
    up (deleted from Open WebUI, never committed locally) rather than left
    behind as an orphan, and reported as a real failure."""
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        side_effect=[
            Response(200, json={"id": "kb-old", "name": "Docs", "description": ""}),
            Response(200, json={"id": "kb-new", "name": "Docs v2", "description": ""}),
        ]
    )
    await client.post("/api/kb", json={"name": "Docs", "version_tag": "v1.0"})

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-old/files").mock(
        return_value=Response(200, json={"items": [{"id": "file-bad", "filename": "scan.pdf", "meta": {}}]})
    )
    respx.get("http://fake-owui.test/api/v1/files/file-bad/data/content").mock(
        return_value=Response(200, json={"content": ""})
    )
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-bad2", "filename": "scan.pdf"})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-new/file/add").mock(
        return_value=Response(400, json={"detail": "Extracted content is not available for this file."})
    )
    delete_route = respx.delete("http://fake-owui.test/api/v1/knowledge/kb-new/delete").mock(
        return_value=Response(200, json=True)
    )

    resp = await client.post("/api/kb/kb-old/clone", json={"name": "Docs v2", "version_tag": "v1.1"})
    assert resp.status_code == 502
    assert "scan.pdf" in resp.json()["detail"]
    assert delete_route.called

    # never shows up as a real knowledge base afterward
    respx.get("http://fake-owui.test/api/v1/knowledge/").mock(
        return_value=Response(200, json=[{"id": "kb-old", "name": "Docs", "description": ""}])
    )
    list_resp = await client.get("/api/kb")
    assert all(kb["id"] != "kb-new" for kb in list_resp.json())


@respx.mock
async def test_delete_knowledge_base_removes_tracked_rows(client):
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-1", "name": "Docs", "description": ""})
    )
    await client.post("/api/kb", json={"name": "Docs", "version_tag": "uvss 2.0"})

    respx.delete("http://fake-owui.test/api/v1/knowledge/kb-1/delete").mock(return_value=Response(200, json=True))
    delete_resp = await client.delete("/api/kb/kb-1")
    assert delete_resp.status_code == 200

    # re-creating a KB reusing the same id should start fresh (no leftover tag)
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-1", "name": "Docs", "description": ""})
    )
    recreate_resp = await client.post("/api/kb", json={"name": "Docs", "version_tag": "v1.0"})
    assert recreate_resp.json()["version_tag"] == "v1.0"


@respx.mock
async def test_lineage_returns_ancestors_root_first_and_children(client):
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        side_effect=[
            Response(200, json={"id": "kb-root", "name": "Root", "description": ""}),
            Response(200, json={"id": "kb-mid", "name": "Mid", "description": ""}),
        ]
    )
    await client.post("/api/kb", json={"name": "Root", "version_tag": "v1.0"})

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-root/files").mock(
        return_value=Response(200, json={"items": []})
    )
    clone_resp = await client.post("/api/kb/kb-root/clone", json={"name": "Mid", "version_tag": "v1.1"})
    assert clone_resp.status_code == 200

    respx.get("http://fake-owui.test/api/v1/knowledge/").mock(
        return_value=Response(
            200,
            json=[
                {"id": "kb-root", "name": "Root", "description": ""},
                {"id": "kb-mid", "name": "Mid", "description": ""},
            ],
        )
    )

    lineage_resp = await client.get("/api/kb/kb-mid/lineage")
    assert lineage_resp.status_code == 200
    body = lineage_resp.json()
    assert body["ancestors"] == [
        {
            "knowledge_id": "kb-root",
            "name": "Root",
            "version_tag": "v1.0",
            "exists": True,
            "changed_file_count": 0,
            "total_file_count": 0,
        }
    ]
    assert body["children"] == []

    root_lineage_resp = await client.get("/api/kb/kb-root/lineage")
    assert root_lineage_resp.status_code == 200
    root_body = root_lineage_resp.json()
    assert root_body["ancestors"] == []
    assert root_body["children"] == [
        {
            "knowledge_id": "kb-mid",
            "name": "Mid",
            "version_tag": "v1.1",
            "exists": True,
            "changed_file_count": 0,
            "total_file_count": 0,
        }
    ]


@respx.mock
async def test_lineage_survives_deleted_parent(client):
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        side_effect=[
            Response(200, json={"id": "kb-root", "name": "Root", "description": ""}),
            Response(200, json={"id": "kb-mid", "name": "Mid", "description": ""}),
        ]
    )
    await client.post("/api/kb", json={"name": "Root", "version_tag": "v1.0"})
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-root/files").mock(
        return_value=Response(200, json={"items": []})
    )
    await client.post("/api/kb/kb-root/clone", json={"name": "Mid", "version_tag": "v1.1"})

    respx.delete("http://fake-owui.test/api/v1/knowledge/kb-root/delete").mock(return_value=Response(200, json=True))
    await client.delete("/api/kb/kb-root")

    respx.get("http://fake-owui.test/api/v1/knowledge/").mock(
        return_value=Response(200, json=[{"id": "kb-mid", "name": "Mid", "description": ""}])
    )
    lineage_resp = await client.get("/api/kb/kb-mid/lineage")
    assert lineage_resp.status_code == 200
    body = lineage_resp.json()
    assert body["ancestors"] == [
        {
            "knowledge_id": "kb-root",
            "name": "(deleted)",
            "version_tag": "v1.0",
            "exists": False,
            "changed_file_count": 0,
            "total_file_count": 0,
        }
    ]


@respx.mock
async def test_tag_dictionary_persists_after_tag_removed_from_file(client):
    resp = await client.patch("/api/kb/kb-1/files/file-a/tags", json={"tags": ["reviewed", "urgent"]})
    assert resp.status_code == 200

    tags_resp = await client.get("/api/tags")
    assert tags_resp.status_code == 200
    assert set(tags_resp.json()) == {"reviewed", "urgent"}

    # removing the tag from the file must not remove it from the dictionary
    remove_resp = await client.patch("/api/kb/kb-1/files/file-a/tags", json={"tags": []})
    assert remove_resp.status_code == 200

    tags_resp_after = await client.get("/api/tags")
    assert set(tags_resp_after.json()) == {"reviewed", "urgent"}


@respx.mock
async def test_update_collection_tags(client):
    respx.get("http://fake-owui.test/api/v1/knowledge/").mock(
        return_value=Response(200, json=[{"id": "kb-1", "name": "Docs", "description": ""}])
    )
    resp = await client.patch("/api/kb/kb-1/tags", json={"tags": ["course", "course/uvss"]})
    assert resp.status_code == 200
    assert resp.json()["tags"] == ["course", "course/uvss"]


@respx.mock
async def test_update_collection_tags_404s_for_an_unknown_knowledge_base(client):
    respx.get("http://fake-owui.test/api/v1/knowledge/").mock(return_value=Response(200, json=[]))
    resp = await client.patch("/api/kb/does-not-exist/tags", json={"tags": ["coe"]})
    assert resp.status_code == 404


@respx.mock
async def test_collection_tags_show_up_in_list_and_detail_and_upsert_into_the_shared_dictionary(client):
    respx.get("http://fake-owui.test/api/v1/knowledge/").mock(
        return_value=Response(200, json=[{"id": "kb-1", "name": "Docs", "description": ""}])
    )
    await client.patch("/api/kb/kb-1/tags", json={"tags": ["coe"]})

    list_resp = await client.get("/api/kb")
    assert list_resp.json()[0]["tags"] == ["coe"]

    detail_resp = await client.get("/api/kb/kb-1")
    assert detail_resp.json()["tags"] == ["coe"]

    tags_resp = await client.get("/api/tags")
    assert "coe" in tags_resp.json()


@respx.mock
async def test_update_collection_tags_works_for_a_collection_with_no_prior_tracked_row(client):
    """A knowledge base that entered Open WebUI some other way (or predates
    this proxy) has no TrackedCollection row yet — tagging it must still
    work via get_or_create_tracked_collection, same as version_tag does."""
    respx.get("http://fake-owui.test/api/v1/knowledge/").mock(
        return_value=Response(200, json=[{"id": "untracked-kb", "name": "Pre-existing", "description": ""}])
    )
    resp = await client.patch("/api/kb/untracked-kb/tags", json={"tags": ["coe"]})
    assert resp.status_code == 200
    assert resp.json()["tags"] == ["coe"]
    assert resp.json()["version_tag"] == "v1.0"  # default, synthesized on first touch


@respx.mock
async def test_reembed_file_pushes_its_current_content_unchanged(client):
    """Changing the embedding model or chunk size in Open WebUI's own
    settings never retroactively re-embeds already-processed files — this
    endpoint forces that for one file by re-pushing its own
    already-extracted text unchanged, which Open WebUI treats as a real
    content update and re-embeds under whatever it currently has
    configured. One file per call (not a whole-collection loop) so the
    frontend can drive its own per-file progress bar."""
    respx.get("http://fake-owui.test/api/v1/files/file-a/data/content").mock(
        return_value=Response(200, json={"content": "content A"})
    )
    update_a = respx.post("http://fake-owui.test/api/v1/files/file-a/data/content/update").mock(
        return_value=Response(200)
    )

    resp = await client.post("/api/kb/kb-1/files/file-a/reembed")
    assert resp.status_code == 200
    assert resp.json() is True
    assert json.loads(update_a.calls[0].request.content) == {"content": "content A"}


@respx.mock
async def test_reembed_file_surfaces_owui_errors(client):
    respx.get("http://fake-owui.test/api/v1/files/file-bad/data/content").mock(
        return_value=Response(200, json={"content": "broken content"})
    )
    respx.post("http://fake-owui.test/api/v1/files/file-bad/data/content/update").mock(
        return_value=Response(400, json={"detail": "Embedding failed"})
    )

    resp = await client.post("/api/kb/kb-1/files/file-bad/reembed")
    assert resp.status_code == 502
    assert resp.json()["detail"] == "Embedding failed"


def _form_field(request, field_name: str) -> str:
    import email

    content_type = request.headers["content-type"]
    raw = b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + request.content
    msg = email.message_from_bytes(raw)
    for part in msg.get_payload():
        disposition = part.get("Content-Disposition", "")
        if f'name="{field_name}"' in disposition:
            return part.get_payload(decode=True).decode("utf-8")
    raise AssertionError(f"field {field_name} not found in multipart body")
