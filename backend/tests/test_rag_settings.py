import json

import respx
from httpx import Response


@respx.mock
async def test_get_rag_settings_reports_current_chunk_and_embedding_config(client):
    respx.get("http://fake-owui.test/api/v1/retrieval/config").mock(
        return_value=Response(200, json={"CHUNK_SIZE": 1000, "CHUNK_OVERLAP": 150, "TEXT_SPLITTER": ""})
    )
    respx.get("http://fake-owui.test/api/v1/retrieval/embedding").mock(
        return_value=Response(
            200,
            json={
                "RAG_EMBEDDING_ENGINE": "ollama",
                "RAG_EMBEDDING_MODEL": "qwen3-embedding:0.6b",
                "openai_config": {"url": "", "key": ""},
                "ollama_config": {"url": "http://ollama:11434", "key": ""},
                "azure_openai_config": {"url": "", "key": "", "version": ""},
            },
        )
    )
    resp = await client.get("/api/rag-settings")
    assert resp.status_code == 200
    assert resp.json() == {
        "chunk_size": 1000,
        "chunk_overlap": 150,
        "embedding_engine": "ollama",
        "embedding_model": "qwen3-embedding:0.6b",
    }


@respx.mock
async def test_update_rag_settings_only_touches_chunking_when_only_chunk_fields_given(client):
    # First GET (inside the handler, to fill in defaults) returns the old
    # values; final GET (via _current_settings, after the update) returns
    # what a real Open WebUI would now report post-update.
    respx.get("http://fake-owui.test/api/v1/retrieval/config").mock(
        side_effect=[
            Response(200, json={"CHUNK_SIZE": 1000, "CHUNK_OVERLAP": 150}),
            Response(200, json={"CHUNK_SIZE": 1200, "CHUNK_OVERLAP": 200}),
        ]
    )
    config_route = respx.post("http://fake-owui.test/api/v1/retrieval/config/update").mock(
        return_value=Response(200, json={})
    )
    embedding_route = respx.post("http://fake-owui.test/api/v1/retrieval/embedding/update").mock(
        return_value=Response(200, json={})
    )
    respx.get("http://fake-owui.test/api/v1/retrieval/embedding").mock(
        return_value=Response(
            200,
            json={
                "RAG_EMBEDDING_ENGINE": "ollama",
                "RAG_EMBEDDING_MODEL": "qwen3-embedding:0.6b",
                "openai_config": {"url": "", "key": ""},
                "ollama_config": {"url": "http://ollama:11434", "key": ""},
                "azure_openai_config": {"url": "", "key": "", "version": ""},
            },
        )
    )

    resp = await client.post("/api/rag-settings", json={"chunk_size": 1200, "chunk_overlap": 200})
    assert resp.status_code == 200
    assert resp.json()["chunk_size"] == 1200
    assert resp.json()["chunk_overlap"] == 200

    assert config_route.called
    assert json.loads(config_route.calls[0].request.content) == {"CHUNK_SIZE": 1200, "CHUNK_OVERLAP": 200}
    assert not embedding_route.called


@respx.mock
async def test_update_rag_settings_switches_embedding_model_without_wiping_connection(client):
    respx.get("http://fake-owui.test/api/v1/retrieval/config").mock(
        return_value=Response(200, json={"CHUNK_SIZE": 1000, "CHUNK_OVERLAP": 150})
    )
    respx.get("http://fake-owui.test/api/v1/retrieval/embedding").mock(
        side_effect=[
            Response(
                200,
                json={
                    "RAG_EMBEDDING_ENGINE": "ollama",
                    "RAG_EMBEDDING_MODEL": "qwen3-embedding:0.6b",
                    "RAG_EMBEDDING_BATCH_SIZE": 1,
                    "openai_config": {"url": "", "key": ""},
                    "ollama_config": {"url": "http://ollama:11434", "key": "real-key"},
                    "azure_openai_config": {"url": "", "key": "", "version": ""},
                },
            ),
            Response(
                200,
                json={
                    "RAG_EMBEDDING_ENGINE": "ollama",
                    "RAG_EMBEDDING_MODEL": "new-model:latest",
                    "RAG_EMBEDDING_BATCH_SIZE": 1,
                    "openai_config": {"url": "", "key": ""},
                    "ollama_config": {"url": "http://ollama:11434", "key": "real-key"},
                    "azure_openai_config": {"url": "", "key": "", "version": ""},
                },
            ),
        ]
    )
    embedding_route = respx.post("http://fake-owui.test/api/v1/retrieval/embedding/update").mock(
        return_value=Response(200, json={})
    )

    resp = await client.post("/api/rag-settings", json={"embedding_model": "new-model:latest"})
    assert resp.status_code == 200
    assert resp.json()["embedding_model"] == "new-model:latest"
    assert resp.json()["embedding_engine"] == "ollama"

    sent = json.loads(embedding_route.calls[0].request.content)
    assert sent["RAG_EMBEDDING_MODEL"] == "new-model:latest"
    assert sent["ollama_config"] == {"url": "http://ollama:11434", "key": "real-key"}


@respx.mock
async def test_get_rag_settings_surfaces_owui_errors(client):
    respx.get("http://fake-owui.test/api/v1/retrieval/config").mock(
        return_value=Response(401, json={"detail": "Unauthorized"})
    )
    resp = await client.get("/api/rag-settings")
    assert resp.status_code == 502
