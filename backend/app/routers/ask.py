from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_owui_client
from app.owui_client import OwuiClient, OwuiError
from app.retrieval_router import ask_joint, ask_with_routing
from app.schemas import AskJointRequest, AskRoutedRequest
from app.versioning import resolve_collection_ids_by_tag

router = APIRouter(prefix="/api/ask", tags=["ask"])


async def _resolve_collection_ids(body, db: AsyncSession, client: OwuiClient) -> list[str]:
    if body.tag and body.collection_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide either collection_ids or tag, not both")
    if body.tag:
        ids = await resolve_collection_ids_by_tag(db, client, body.tag)
        if not ids:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"No collections tagged '{body.tag}' were found")
        return ids
    if not body.collection_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide either collection_ids or tag")
    return body.collection_ids


@router.post("/route")
async def ask_routed(body: AskRoutedRequest, db: AsyncSession = Depends(get_db), client: OwuiClient = Depends(get_owui_client)):
    """Score each candidate collection with a cheap vector search, answer
    using only the closest match. Returns Open WebUI's own raw chat-
    completion shape (same as calling /api/chat/completions with `files`
    directly — choices, sources with per-chunk file/score attribution,
    usage, etc.), plus `winning_collection_id`/`collection_scores` so the
    caller can see which collection won and why.

    Candidates come either from `collection_ids` directly, or from `tag` —
    every collection tagged with it, collapsed to just the newest version
    per clone lineage (see resolve_collection_ids_by_tag)."""
    try:
        collection_ids = await _resolve_collection_ids(body, db, client)
        history = [m.model_dump() for m in body.history]
        return await ask_with_routing(client, body.model, collection_ids, body.query, k=body.k, history=history)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/joint")
async def ask_joint_endpoint(body: AskJointRequest, db: AsyncSession = Depends(get_db), client: OwuiClient = Depends(get_owui_client)):
    """Answer using the best-matching chunks pooled from ALL given
    collections at once — no routing/scoring, just one chat completion.
    Returns Open WebUI's own raw response, unmodified.

    Candidates come either from `collection_ids` directly, or from `tag`,
    same resolution as ask_routed above."""
    try:
        collection_ids = await _resolve_collection_ids(body, db, client)
        history = [m.model_dump() for m in body.history]
        return await ask_joint(client, body.model, collection_ids, body.query, history=history)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e
