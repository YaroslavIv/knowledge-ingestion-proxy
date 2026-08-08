import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunking import preview_with_redactions, with_token_overrides
from app.config_cache import get_chunking_config
from app.db import get_db
from app.deps import get_owui_client
from app.models import IngestionSession
from app.original_storage import attach_to_file, save_original
from app.owui_client import OwuiClient, OwuiError
from app.parsing import parse_document
from app.redaction import Redaction, apply_redactions
from app.schemas import (
    ChunkPreviewResponse,
    ChunkRangeModel,
    DocumentCreatedResponse,
    DocumentPatchRequest,
    DocumentStateResponse,
    FinalizeResponse,
)
from app.versioning import bump_file_version, record_new_file

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])


async def _get_session_or_404(session_id: str, db: AsyncSession) -> IngestionSession:
    session = await db.get(IngestionSession, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found or expired")
    return session


def _to_state_response(session: IngestionSession) -> DocumentStateResponse:
    return DocumentStateResponse(
        session_id=session.session_id,
        filename=session.original_filename,
        text=session.current_text,
        redactions=[Redaction(**r) for r in session.redactions],
        target_knowledge_id=session.target_knowledge_id,
        status=session.status,
        error_message=session.error_message,
        owui_file_id=session.owui_file_id,
    )


@router.post("", response_model=DocumentCreatedResponse)
async def upload_document(file: UploadFile, db: AsyncSession = Depends(get_db)):
    data = await file.read()

    # Parsing happens synchronously, in-memory, within this single request.
    # The redacted/cleaned text is what ever reaches Open WebUI — `data` (the
    # true original bytes) only gets cached in this proxy's own local storage
    # (see original_storage.py), purely so the "existing file" pane can show
    # it again later; Open WebUI itself never receives it.
    result = parse_document(file.filename or "document", file.content_type, data)

    session = IngestionSession(
        original_filename=file.filename or "document",
        original_content_type=file.content_type,
        current_text=result.text,
        redactions=[],
        status="editing",
    )
    db.add(session)
    await db.flush()
    await save_original(db, session.session_id, file.filename or "document", file.content_type or "", data)
    await db.commit()
    await db.refresh(session)

    return DocumentCreatedResponse(
        session_id=session.session_id,
        filename=session.original_filename,
        text=session.current_text,
        warnings=result.warnings,
        status=session.status,
    )


@router.get("/{session_id}", response_model=DocumentStateResponse)
async def get_document(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await _get_session_or_404(session_id, db)
    return _to_state_response(session)


@router.patch("/{session_id}", response_model=DocumentStateResponse)
async def patch_document(session_id: str, body: DocumentPatchRequest, db: AsyncSession = Depends(get_db)):
    session = await _get_session_or_404(session_id, db)
    if session.status not in ("editing", "failed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session is '{session.status}' and can no longer be edited",
        )

    if body.text is not None:
        session.current_text = body.text
    if body.redactions is not None:
        session.redactions = [r.model_dump() for r in body.redactions]
    if body.target_knowledge_id is not None:
        session.target_knowledge_id = body.target_knowledge_id
    if body.replace_file_id is not None:
        session.replace_file_id = body.replace_file_id

    session.status = "editing"
    session.error_message = None
    await db.commit()
    await db.refresh(session)
    return _to_state_response(session)


@router.get("/{session_id}/chunk-preview", response_model=ChunkPreviewResponse)
async def chunk_preview(
    session_id: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    db: AsyncSession = Depends(get_db),
    client: OwuiClient = Depends(get_owui_client),
):
    session = await _get_session_or_404(session_id, db)
    redactions = [Redaction(**r) for r in session.redactions]

    config = with_token_overrides(await get_chunking_config(client), chunk_size, chunk_overlap)
    chunks = preview_with_redactions(session.current_text, redactions, config)

    return ChunkPreviewResponse(
        chunks=[ChunkRangeModel(start=c.start, end=c.end) for c in chunks],
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        text_splitter=config.text_splitter,
    )


@router.post("/{session_id}/finalize", response_model=FinalizeResponse)
async def finalize_document(
    session_id: str, db: AsyncSession = Depends(get_db), client: OwuiClient = Depends(get_owui_client)
):
    session = await _get_session_or_404(session_id, db)

    if not session.target_knowledge_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No target knowledge base selected")

    redactions = [Redaction(**r) for r in session.redactions]
    final_text = apply_redactions(session.current_text, redactions)
    if not final_text.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Resulting document is empty")

    session.status = "submitting"
    await db.commit()

    knowledge_id = session.target_knowledge_id
    replace_file_id = session.replace_file_id

    try:
        if replace_file_id:
            # Replace this file's content in place (same OWUI file_id,
            # re-embedded) — a "file-level" change, as opposed to a plain
            # text edit via the existing-file editor's Update button.
            await client.update_file_content(replace_file_id, final_text)
            owui_file_id = replace_file_id
        else:
            result = await client.upload_file_to_knowledge(
                filename=_markdown_filename(session.original_filename),
                content=final_text,
                knowledge_id=knowledge_id,
            )
            owui_file_id = result.get("id")
            # Uploading under the real original name (e.g. "datasheet.pdf")
            # would make Open WebUI try to parse this proxy's own extracted
            # *text* as if it were a real PDF, by extension (see
            # upload_file_to_knowledge's docstring) — .md is required for
            # that to succeed. Renaming afterward is purely cosmetic (see
            # OwuiClient.rename_file) and doesn't touch what already got
            # extracted/embedded, so the file list can show "datasheet.pdf"
            # again without corrupting the actual processing. Best-effort:
            # a rename failure here shouldn't fail an otherwise-successful
            # upload the user is still waiting on.
            try:
                await client.rename_file(owui_file_id, session.original_filename)
            except OwuiError:
                pass
    except OwuiError as e:
        session.status = "failed"
        session.error_message = e.detail
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e

    if replace_file_id:
        await bump_file_version(db, replace_file_id, knowledge_id, method="file_replace")
    else:
        await record_new_file(db, owui_file_id, knowledge_id)

    await attach_to_file(db, session.session_id, owui_file_id)

    # Nothing about this document — clean or otherwise — should linger here
    # once it has been handed off to Open WebUI.
    await db.delete(session)
    await db.commit()

    return FinalizeResponse(owui_file_id=owui_file_id, knowledge_id=knowledge_id)


def _markdown_filename(original_filename: str) -> str:
    stem = original_filename.rsplit(".", 1)[0] if "." in original_filename else original_filename
    return f"{stem}.md"
