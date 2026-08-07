from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import get_owui_client
from app.owui_client import OwuiClient, OwuiError
from app.schemas import RagSettingsSummary, UpdateRagSettingsRequest

router = APIRouter(prefix="/api/rag-settings", tags=["rag-settings"])


async def _current_settings(client: OwuiClient) -> RagSettingsSummary:
    retrieval = await client.get_retrieval_config()
    embedding = await client.get_embedding_config()
    return RagSettingsSummary(
        chunk_size=retrieval.get("CHUNK_SIZE") or 1000,
        chunk_overlap=retrieval.get("CHUNK_OVERLAP") or 100,
        embedding_engine=embedding.get("RAG_EMBEDDING_ENGINE") or "",
        embedding_model=embedding.get("RAG_EMBEDDING_MODEL") or "",
    )


@router.get("", response_model=RagSettingsSummary)
async def get_rag_settings(client: OwuiClient = Depends(get_owui_client)):
    try:
        return await _current_settings(client)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e


@router.post("", response_model=RagSettingsSummary)
async def update_rag_settings(body: UpdateRagSettingsRequest, client: OwuiClient = Depends(get_owui_client)):
    """Change chunk size/overlap and/or the embedding engine/model Open
    WebUI uses — through the same config endpoints Open WebUI's own Admin
    Settings UI uses, which only update the given fields and never delete
    anything (deleting lives on entirely separate reset/db and
    reset/uploads endpoints this proxy never calls).

    This alone does not re-embed a single existing file — old content
    keeps whatever vectors it already has until something re-pushes it
    (see the per-file /api/kb/{id}/files/{file_id}/reembed endpoint, which
    the frontend loops over every collection/file for after a config
    change like this).
    """
    try:
        if body.chunk_size is not None or body.chunk_overlap is not None:
            current = await client.get_retrieval_config()
            await client.update_chunking_config(
                chunk_size=body.chunk_size if body.chunk_size is not None else (current.get("CHUNK_SIZE") or 1000),
                chunk_overlap=body.chunk_overlap
                if body.chunk_overlap is not None
                else (current.get("CHUNK_OVERLAP") or 100),
            )

        if body.embedding_model is not None or body.embedding_engine is not None:
            await client.update_embedding_config(engine=body.embedding_engine, model=body.embedding_model)

        return await _current_settings(client)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e
