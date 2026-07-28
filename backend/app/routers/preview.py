from fastapi import APIRouter, Depends

from app.chunking import preview_with_redactions, with_token_overrides
from app.config_cache import get_chunking_config
from app.deps import get_owui_client
from app.owui_client import OwuiClient
from app.schemas import ChunkPreviewRequest, ChunkPreviewResponse, ChunkRangeModel

router = APIRouter(prefix="/api/preview", tags=["preview"])


@router.post("/chunks", response_model=ChunkPreviewResponse)
async def preview_chunks(body: ChunkPreviewRequest, client: OwuiClient = Depends(get_owui_client)):
    """Stateless chunk-boundary preview for arbitrary text — used by the
    "edit an already-committed file" pane, which has no ingestion session to
    read from (unlike /api/documents/{id}/chunk-preview).

    `chunk_size`/`chunk_overlap`, when provided, override the instance's real
    (character-based, by default) config with a token-based preview so the
    user can explore "what if chunks were N tokens" without changing Open
    WebUI's actual settings.
    """
    config = with_token_overrides(await get_chunking_config(client), body.chunk_size, body.chunk_overlap)
    chunks = preview_with_redactions(body.text, body.redactions, config)

    return ChunkPreviewResponse(
        chunks=[ChunkRangeModel(start=c.start, end=c.end) for c in chunks],
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        text_splitter=config.text_splitter,
    )
