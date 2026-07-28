import json

import respx
from httpx import Response


@respx.mock
async def test_finalize_strips_redacted_text_before_sending_to_owui(client):
    upload_route = respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-999", "filename": "doc.md"})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-1/file/add").mock(return_value=Response(200))

    files = {"file": ("doc.md", b"# Heading\n\nkeep this SECRET-VALUE drop this\n", "text/markdown")}
    resp = await client.post("/api/documents", files=files)
    assert resp.status_code == 200
    body = resp.json()
    session_id = body["session_id"]
    text = body["text"]

    start = text.index("SECRET-VALUE")
    end = start + len("SECRET-VALUE")

    patch_resp = await client.patch(
        f"/api/documents/{session_id}",
        json={"redactions": [{"start": start, "end": end}], "target_knowledge_id": "kb-1"},
    )
    assert patch_resp.status_code == 200

    finalize_resp = await client.post(f"/api/documents/{session_id}/finalize")
    assert finalize_resp.status_code == 200
    assert finalize_resp.json() == {"owui_file_id": "file-999", "knowledge_id": "kb-1"}

    assert upload_route.called
    sent_request = upload_route.calls.last.request
    sent_metadata = json.loads(_extract_form_field(sent_request, "metadata"))
    assert sent_metadata == {"knowledge_id": "kb-1"}

    sent_content = _extract_file_content(sent_request)
    assert "SECRET-VALUE" not in sent_content
    assert "keep this" in sent_content
    assert "drop this" in sent_content

    # session must be gone after a successful finalize
    get_resp = await client.get(f"/api/documents/{session_id}")
    assert get_resp.status_code == 404


@respx.mock
async def test_finalize_without_target_kb_is_rejected(client):
    files = {"file": ("doc.txt", b"just some text", "text/plain")}
    resp = await client.post("/api/documents", files=files)
    session_id = resp.json()["session_id"]

    finalize_resp = await client.post(f"/api/documents/{session_id}/finalize")
    assert finalize_resp.status_code == 400


@respx.mock
async def test_finalize_surfaces_owui_error_and_keeps_session_editable(client):
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(400, json={"detail": "Duplicate content detected"})
    )

    files = {"file": ("doc.txt", b"some content", "text/plain")}
    resp = await client.post("/api/documents", files=files)
    session_id = resp.json()["session_id"]

    await client.patch(f"/api/documents/{session_id}", json={"target_knowledge_id": "kb-1"})

    finalize_resp = await client.post(f"/api/documents/{session_id}/finalize")
    assert finalize_resp.status_code == 502
    assert "Duplicate content" in finalize_resp.json()["detail"]

    # session should still be retrievable/editable after a failed finalize
    get_resp = await client.get(f"/api/documents/{session_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "failed"


def _extract_form_field(request, field_name: str) -> str:
    import email

    content_type = request.headers["content-type"]
    raw = b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + request.content
    msg = email.message_from_bytes(raw)
    for part in msg.get_payload():
        disposition = part.get("Content-Disposition", "")
        if f'name="{field_name}"' in disposition:
            return part.get_payload(decode=True).decode("utf-8")
    raise AssertionError(f"field {field_name} not found in multipart body")


def _extract_file_content(request) -> str:
    import email

    content_type = request.headers["content-type"]
    raw = b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + request.content
    msg = email.message_from_bytes(raw)
    for part in msg.get_payload():
        disposition = part.get("Content-Disposition", "")
        if 'name="file"' in disposition:
            return part.get_payload(decode=True).decode("utf-8")
    raise AssertionError("file field not found in multipart body")
