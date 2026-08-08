from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ask_history import list_ask_joint_history, record_ask_joint
from app.db import get_db
from app.deps import get_owui_client
from app.owui_client import OwuiClient, OwuiError
from app.retrieval_router import ask_joint, ask_with_routing, search_collections
from app.schemas import AskJointLogItem, AskJointRequest, AskRoutedRequest, SearchRequest, SearchResponse, SearchResultItem
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
    same resolution as ask_routed above. Every successful call is recorded
    (see app/ask_history.py) for later analysis of what's actually being
    asked against these collections."""
    try:
        collection_ids = await _resolve_collection_ids(body, db, client)
        history = [m.model_dump() for m in body.history]
        result = await ask_joint(client, body.model, collection_ids, body.query, history=history)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e

    await record_ask_joint(
        db,
        query=body.query,
        tag=body.tag,
        collection_ids=collection_ids,
        model=body.model,
        answer=_extract_answer(result),
        embedding=await _embed_query_best_effort(client, body.query),
    )
    return result


def _extract_answer(raw: dict) -> str | None:
    try:
        return raw["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None


async def _embed_query_best_effort(client: OwuiClient, query: str) -> list[float] | None:
    """The query's own embedding vector, for later clustering/classification
    of asked questions (see app/ask_history.py) — not part of answering the
    question itself, so a failure here (embedding model briefly unreachable,
    misconfigured, etc.) must never fail an otherwise-successful ask."""
    try:
        embedding_config = await client.get_embedding_config()
        return await client.embed_text(embedding_config["RAG_EMBEDDING_MODEL"], query)
    except OwuiError:
        return None


@router.get("/joint/history", response_model=list[AskJointLogItem])
async def ask_joint_history(limit: int = 200, db: AsyncSession = Depends(get_db)):
    rows = await list_ask_joint_history(db, limit=limit)
    return [
        AskJointLogItem(
            id=row.id,
            created_at=row.created_at.isoformat(),
            query=row.query,
            tag=row.tag,
            collection_ids=row.collection_ids,
            model=row.model,
            answer=row.answer,
        )
        for row in rows
    ]


@router.post("/search", response_model=SearchResponse)
async def search_endpoint(body: SearchRequest, db: AsyncSession = Depends(get_db), client: OwuiClient = Depends(get_owui_client)):
    """Pure retrieval, no chat completion — the same pooled/ranked chunks
    ask_joint would feed to a model, surfaced directly so embedding-model
    quality can be judged on its own (are the real top matches relevant?),
    without an LLM's phrasing smoothing over mediocre retrieval either way.

    Candidates come either from `collection_ids` directly, or from `tag`,
    same resolution as ask_joint above."""
    try:
        collection_ids = await _resolve_collection_ids(body, db, client)
        results = await search_collections(client, collection_ids, body.query, k=body.k)
        return SearchResponse(results=[SearchResultItem(**r) for r in results])
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e
