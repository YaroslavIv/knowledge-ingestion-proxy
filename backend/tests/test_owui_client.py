import json

import httpx
import pytest
import respx
from httpx import Response

from app.owui_client import OwuiClient, OwuiError


@respx.mock
async def test_list_knowledge_bases_returns_a_flat_list_unchanged():
    """Older Open WebUI versions: one unpaginated list, no items/total
    wrapper at all."""
    respx.get("http://fake-owui.test/api/v1/knowledge/").mock(
        return_value=Response(200, json=[{"id": "kb-1", "name": "Docs"}, {"id": "kb-2", "name": "More"}])
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    result = await client.list_knowledge_bases()
    assert [kb["id"] for kb in result] == ["kb-1", "kb-2"]


@respx.mock
async def test_list_knowledge_bases_follows_pagination_across_every_page():
    """Confirmed live: v0.11.0 caps GET /api/v1/knowledge/ at 30 items per
    page (items/total), with no way to ask for a bigger page — a single
    call silently truncated anything past page 1. Must keep paging until
    every item `total` promised has actually been collected."""
    route = respx.get("http://fake-owui.test/api/v1/knowledge/").mock(
        side_effect=[
            Response(200, json={"items": [{"id": f"kb-{i}"} for i in range(30)], "total": 40}),
            Response(200, json={"items": [{"id": f"kb-{i}"} for i in range(30, 40)], "total": 40}),
        ]
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    result = await client.list_knowledge_bases()
    assert len(result) == 40
    assert [kb["id"] for kb in result] == [f"kb-{i}" for i in range(40)]
    assert route.calls[1].request.url.params["page"] == "2"


@respx.mock
async def test_list_knowledge_bases_stops_if_a_later_page_comes_back_empty():
    """A defensive stop against an infinite loop if `total` is ever wrong
    (stale/miscounted) — an empty page always ends pagination, regardless
    of what `total` claimed."""
    respx.get("http://fake-owui.test/api/v1/knowledge/").mock(
        side_effect=[
            Response(200, json={"items": [{"id": "kb-1"}], "total": 99}),
            Response(200, json={"items": [], "total": 99}),
        ]
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    result = await client.list_knowledge_bases()
    assert [kb["id"] for kb in result] == ["kb-1"]


@respx.mock
async def test_list_models_unwraps_data_field():
    respx.get("http://fake-owui.test/api/v1/models").mock(
        return_value=Response(200, json={"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4o"}]})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    models = await client.list_models()
    assert [m["id"] for m in models] == ["gpt-4o-mini", "gpt-4o"]


@respx.mock
async def test_list_models_falls_back_to_plain_models_endpoint():
    """Confirmed live against a real corporate instance: /api/v1/models 200s
    with the SPA's own index.html (no backend route matches it) instead of
    JSON. /api/models (Open WebUI's own "models visible in this instance's
    chat UI" list) works reliably there and is a strictly better fallback
    than failing outright."""
    respx.get("http://fake-owui.test/api/v1/models").mock(
        return_value=Response(200, html="<html><body>Open WebUI</body></html>")
    )
    respx.get("http://fake-owui.test/api/models").mock(
        return_value=Response(200, json={"data": [{"id": "gpt-5.4"}, {"id": "arena-model"}]})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    models = await client.list_models()
    assert [m["id"] for m in models] == ["gpt-5.4", "arena-model"]


@respx.mock
async def test_chat_completion_returns_message_content():
    route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": '{"status": "ok"}'}}]},
        )
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    content = await client.chat_completion(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    assert content == '{"status": "ok"}'

    sent_body = route.calls[0].request.content
    import json as _json

    body = _json.loads(sent_body)
    assert body["model"] == "gpt-4o-mini"
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.1


@respx.mock
async def test_chat_completion_surfaces_owui_errors():
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(400, json={"detail": "Model not found"})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    with pytest.raises(OwuiError):
        await client.chat_completion(model="nope", messages=[{"role": "user", "content": "hi"}])


@respx.mock
async def test_chat_completion_falls_back_to_the_non_v1_endpoint_on_405():
    """Confirmed live against a real corporate instance: /api/v1/chat/completions
    can 405 independently of the rest of the API (same failure family as
    /api/v1/models and /api/v1/knowledge/{id}/files) while the plain
    /api/chat/completions endpoint works fine. This must recover instead of
    surfacing a confusing 502 for every single generate/revise/split call."""
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(405, json={"detail": "Method Not Allowed"})
    )
    fallback_route = respx.post("http://fake-owui.test/api/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": "hi there"}}]})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    content = await client.chat_completion(model="gpt-5.4", messages=[{"role": "user", "content": "hi"}])
    assert content == "hi there"
    assert fallback_route.called


@respx.mock
async def test_chat_completion_falls_back_when_v1_returns_html_instead_of_json():
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, html="<html><body>Open WebUI</body></html>")
    )
    respx.post("http://fake-owui.test/api/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": "hi there"}}]})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    content = await client.chat_completion(model="gpt-5.4", messages=[{"role": "user", "content": "hi"}])
    assert content == "hi there"


@respx.mock
async def test_chat_completion_retries_without_temperature_when_the_model_rejects_it():
    """Some newer reasoning-style models (GPT-5-class and similar) reject any
    non-default temperature via the OpenAI-compatible API. This must retry
    once with the parameter omitted entirely instead of failing the whole
    generation/revision call outright."""
    route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        side_effect=[
            Response(400, json={"detail": "Unsupported value: 'temperature' does not support 0.2 with this model."}),
            Response(200, json={"choices": [{"message": {"content": "ok"}}]}),
        ]
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    content = await client.chat_completion(
        model="gpt-5.6-sol", messages=[{"role": "user", "content": "hi"}], temperature=0.2
    )
    assert content == "ok"
    assert route.call_count == 2
    first_body = json.loads(route.calls[0].request.content)
    retry_body = json.loads(route.calls[1].request.content)
    assert first_body["temperature"] == 0.2
    assert "temperature" not in retry_body


@respx.mock
async def test_chat_completion_does_not_retry_on_an_unrelated_400():
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(400, json={"detail": "Invalid request payload"})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    with pytest.raises(OwuiError):
        await client.chat_completion(model="nope", messages=[{"role": "user", "content": "hi"}])


@respx.mock
async def test_chat_completion_wraps_transport_errors_as_owui_error():
    """A slow model or a dead Open WebUI instance raises an httpx transport
    error (timeout, connect failure) — this must surface as a clean
    OwuiError (-> 502 to our own API's caller), not bubble up as an
    unhandled 500 past every route that calls chat_completion."""
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(side_effect=httpx.ReadTimeout("timed out"))
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    with pytest.raises(OwuiError):
        await client.chat_completion(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])


@respx.mock
async def test_chat_completion_passes_files_through_when_given():
    route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": "answer"}}]})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    content = await client.chat_completion(
        model="gpt-5.4",
        messages=[{"role": "user", "content": "hi"}],
        files=[{"type": "collection", "id": "kb-1"}],
    )
    assert content == "answer"
    sent_body = json.loads(route.calls[0].request.content)
    assert sent_body["files"] == [{"type": "collection", "id": "kb-1"}]


@respx.mock
async def test_chat_completion_return_raw_gives_the_full_response_body():
    """When `files` retrieves context, Open WebUI adds a `sources` field
    alongside the usual choices/usage — return_raw=True must expose that
    whole body, not just the extracted message content."""
    raw = {
        "choices": [{"message": {"content": "answer"}}],
        "usage": {"total_tokens": 5},
        "sources": [{"source": {"type": "collection", "id": "kb-1"}, "document": ["chunk"], "metadata": [{}]}],
    }
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(return_value=Response(200, json=raw))
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    result = await client.chat_completion(
        model="gpt-5.4",
        messages=[{"role": "user", "content": "hi"}],
        files=[{"type": "collection", "id": "kb-1"}],
        return_raw=True,
    )
    assert result == raw


@respx.mock
async def test_chat_completion_omits_files_field_when_not_given():
    route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": "answer"}}]})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    await client.chat_completion(model="gpt-5.4", messages=[{"role": "user", "content": "hi"}])
    sent_body = json.loads(route.calls[0].request.content)
    assert "files" not in sent_body


@respx.mock
async def test_query_collection_forces_hybrid_false():
    """Confirmed live against a real corporate instance: with hybrid search
    enabled server-side, the hybrid path of /query/collection silently
    returns empty results (a server bug on that version) — plain vector
    search (hybrid=False) returns real, correctly-ranked results there. This
    must always be sent explicitly, never left to the server's default."""
    route = respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        return_value=Response(200, json={"documents": [["chunk text"]], "distances": [[0.42]], "metadatas": [[{}]]})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    result = await client.query_collection(["kb-1"], "some question", k=5)
    assert result["distances"] == [[0.42]]
    sent_body = json.loads(route.calls[0].request.content)
    assert sent_body == {"collection_names": ["kb-1"], "query": "some question", "k": 5, "hybrid": False}


@respx.mock
async def test_query_collection_surfaces_owui_errors():
    respx.post("http://fake-owui.test/api/v1/retrieval/query/collection").mock(
        return_value=Response(400, json={"detail": "bad collection"})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    with pytest.raises(OwuiError):
        await client.query_collection(["kb-1"], "q")


@respx.mock
async def test_upload_file_to_knowledge_explicitly_links_the_file():
    """Confirmed live against a real corporate Open WebUI instance: uploading
    with metadata.knowledge_id alone left the file in its own isolated
    per-file vector collection, invisible in the knowledge base's own file
    list and in Open WebUI's UI, until POST .../file/add was called
    explicitly. This must happen on every upload, not just newer Open WebUI
    versions that auto-link during processing."""
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-1", "filename": "doc.md"})
    )
    add_route = respx.post("http://fake-owui.test/api/v1/knowledge/kb-1/file/add").mock(return_value=Response(200))

    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    result = await client.upload_file_to_knowledge("doc.md", "content", "kb-1")

    assert result["id"] == "file-1"
    assert add_route.called
    import json as _json

    assert _json.loads(add_route.calls[0].request.content) == {"file_id": "file-1"}


@respx.mock
async def test_upload_file_to_knowledge_raises_if_linking_fails():
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-1", "filename": "doc.md"})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-1/file/add").mock(
        return_value=Response(403, json={"detail": "Forbidden"})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    with pytest.raises(OwuiError):
        await client.upload_file_to_knowledge("doc.md", "content", "kb-1")


@respx.mock
async def test_upload_raw_file_uploads_bytes_unprocessed_and_never_links_it():
    """The actual published artifact (e.g. a SCORM zip) must genuinely live
    inside Open WebUI too — but process=false, since it's a finished
    deliverable, not something to extract/embed text from, and (confirmed
    live) a binary file can never be linked into a knowledge base's own file
    list anyway. No /file/add call should ever be made for this path."""
    add_route = respx.post("http://fake-owui.test/api/v1/knowledge/kb-1/file/add").mock(return_value=Response(200))
    upload_route = respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "raw-file-1", "filename": "module.zip"})
    )

    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    result = await client.upload_raw_file("module.zip", b"PK\x03\x04fakezipbytes", "application/zip", "kb-1")

    assert result["id"] == "raw-file-1"
    assert not add_route.called

    sent_request = upload_route.calls[0].request
    assert sent_request.url.params["process"] == "false"
    assert b"PK\x03\x04fakezipbytes" in sent_request.content


@respx.mock
async def test_upload_raw_file_surfaces_owui_errors():
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(400, json={"detail": "Something went wrong"})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    with pytest.raises(OwuiError):
        await client.upload_raw_file("module.zip", b"bytes", "application/zip", "kb-1")


@respx.mock
async def test_delete_file_calls_the_standalone_delete_endpoint():
    route = respx.delete("http://fake-owui.test/api/v1/files/raw-1").mock(return_value=Response(200))
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    await client.delete_file("raw-1")
    assert route.called


@respx.mock
async def test_delete_file_surfaces_owui_errors():
    respx.delete("http://fake-owui.test/api/v1/files/raw-1").mock(
        return_value=Response(404, json={"detail": "Not found"})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    with pytest.raises(OwuiError):
        await client.delete_file("raw-1")


@respx.mock
async def test_list_knowledge_files_uses_the_dedicated_endpoint_when_it_returns_json():
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-1/files").mock(
        return_value=Response(200, json={"items": [{"id": "file-1", "filename": "doc.md"}]})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    result = await client.list_knowledge_files("kb-1")
    assert result == {"items": [{"id": "file-1", "filename": "doc.md"}]}


@respx.mock
async def test_list_knowledge_files_falls_back_to_embedded_files_field():
    """Confirmed live: an older Open WebUI version has no dedicated
    /knowledge/{id}/files route at all — the request 200s with the SPA's own
    index.html (SvelteKit's catch-all) instead of a JSON error, since no
    backend route matches it. That version exposes the same information as
    a `files` field embedded directly on the knowledge base's own
    GET-by-id response instead."""
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-1/files").mock(
        return_value=Response(200, html="<html><body>Open WebUI</body></html>")
    )
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-1").mock(
        return_value=Response(200, json={"id": "kb-1", "name": "Docs", "files": [{"id": "file-1"}]})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    result = await client.list_knowledge_files("kb-1")
    assert result == [{"id": "file-1"}]


@respx.mock
async def test_list_knowledge_files_fallback_defaults_to_empty_list():
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-1/files").mock(
        return_value=Response(200, html="<html></html>")
    )
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-1").mock(
        return_value=Response(200, json={"id": "kb-1", "name": "Docs", "files": None})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    result = await client.list_knowledge_files("kb-1")
    assert result == []


@respx.mock
async def test_update_chunking_config_sends_only_chunk_fields():
    route = respx.post("http://fake-owui.test/api/v1/retrieval/config/update").mock(return_value=Response(200, json={}))
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    await client.update_chunking_config(chunk_size=1200, chunk_overlap=200)
    sent = json.loads(route.calls[0].request.content)
    assert sent == {"CHUNK_SIZE": 1200, "CHUNK_OVERLAP": 200}


@respx.mock
async def test_update_embedding_config_preserves_existing_connection_details():
    """Open WebUI's embedding-update form treats each connection sub-object
    as all-or-nothing — sending engine/model without the real
    ollama_config/openai_config would blank out a working connection's
    url/key. This must fetch the current config first and pass those
    through unchanged."""
    respx.get("http://fake-owui.test/api/v1/retrieval/embedding").mock(
        return_value=Response(
            200,
            json={
                "RAG_EMBEDDING_ENGINE": "ollama",
                "RAG_EMBEDDING_MODEL": "qwen3-embedding:0.6b",
                "RAG_EMBEDDING_BATCH_SIZE": 4,
                "ENABLE_ASYNC_EMBEDDING": True,
                "RAG_EMBEDDING_CONCURRENT_REQUESTS": 2,
                "openai_config": {"url": "", "key": ""},
                "ollama_config": {"url": "http://ollama:11434", "key": "real-key"},
                "azure_openai_config": {"url": "", "key": "", "version": ""},
            },
        )
    )
    route = respx.post("http://fake-owui.test/api/v1/retrieval/embedding/update").mock(
        return_value=Response(200, json={})
    )
    client = OwuiClient(base_url="http://fake-owui.test", api_key="testkey")
    await client.update_embedding_config(engine="ollama", model="new-embedding-model")

    sent = json.loads(route.calls[0].request.content)
    assert sent["RAG_EMBEDDING_MODEL"] == "new-embedding-model"
    assert sent["RAG_EMBEDDING_ENGINE"] == "ollama"
    assert sent["RAG_EMBEDDING_BATCH_SIZE"] == 4
    # the real connection details survived untouched
    assert sent["ollama_config"] == {"url": "http://ollama:11434", "key": "real-key"}
