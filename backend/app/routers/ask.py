from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import get_owui_client
from app.owui_client import OwuiClient, OwuiError
from app.retrieval_router import ask_joint, ask_with_routing
from app.schemas import AskJointRequest, AskRoutedRequest

router = APIRouter(prefix="/api/ask", tags=["ask"])


@router.post("/route")
async def ask_routed(body: AskRoutedRequest, client: OwuiClient = Depends(get_owui_client)):
    """Score each candidate collection with a cheap vector search, answer
    using only the closest match. Returns Open WebUI's own raw chat-
    completion shape (same as calling /api/chat/completions with `files`
    directly — choices, sources with per-chunk file/score attribution,
    usage, etc.), plus `winning_collection_id`/`collection_scores` so the
    caller can see which collection won and why."""
    try:
        return await ask_with_routing(client, body.model, body.collection_ids, body.query, k=body.k)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/joint")
async def ask_joint_endpoint(body: AskJointRequest, client: OwuiClient = Depends(get_owui_client)):
    """Answer using the best-matching chunks pooled from ALL given
    collections at once — no routing/scoring, just one chat completion.
    Returns Open WebUI's own raw response, unmodified."""
    try:
        return await ask_joint(client, body.model, body.collection_ids, body.query)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e
