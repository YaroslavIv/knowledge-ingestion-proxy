"""Ask a question routed to the single best-matching knowledge base, or
jointly across a set of them — built entirely on Open WebUI's own retrieval
(query/collection for scoring, chat_completion's `files` hook for the real
answer), no separate reimplementation of embedding/vector search.

Two modes:
- ask_with_routing: scores each candidate collection with a cheap, LLM-free
  vector search, picks the closest match, then answers using only that
  collection's real content.
- ask_joint: skips scoring — answers directly using ALL given collections at
  once; Open WebUI retrieves its own top-k chunks from each and merges them
  into one prompt.
"""
from __future__ import annotations

from app.owui_client import OwuiClient


async def ask_with_routing(
    client: OwuiClient,
    model: str,
    collection_ids: list[str],
    query: str,
    k: int = 3,
    history: list[dict] | None = None,
) -> dict:
    """Returns Open WebUI's own raw chat-completion response (same shape as
    calling /api/chat/completions with `files` directly — `choices`,
    `sources` with per-chunk file/score attribution, `usage`, etc.), plus
    two extra top-level fields: `winning_collection_id` and
    `collection_scores` (every candidate's best/highest score, or None if
    it returned nothing) — so the caller can see why that collection won.

    `history` is prior turns (`[{"role": "user"/"assistant", "content": ...},
    ...]`, oldest first) — prepended to the actual chat-completion call so a
    follow-up question keeps conversational context, same as calling
    /api/chat/completions with a multi-message `messages` array directly.
    Routing/scoring itself still only looks at the current `query`, not the
    whole history — which collection is the best match for *this* question
    shouldn't be diluted by earlier unrelated turns.

    The `distances` field in query/collection's response is, despite the
    name, a similarity score — confirmed empirically against a real
    instance: for one fixed query, results come back sorted with the
    HIGHEST value first (the best match), decreasing from there. Picking
    the collection with the highest score is therefore correct; picking
    the lowest (as an earlier version of this function did, going by the
    field's name) silently routed to the worst match instead of the best.
    """
    scores: dict[str, float | None] = {}
    for collection_id in collection_ids:
        result = await client.query_collection([collection_id], query, k=k)
        distances = (result.get("distances") or [[]])[0]
        scores[collection_id] = max(distances) if distances else None

    scored = {cid: d for cid, d in scores.items() if d is not None}
    if not scored:
        raise ValueError("None of the given collections returned any matching content for this query")
    winning_collection_id = max(scored, key=scored.get)

    raw = await client.chat_completion(
        model=model,
        messages=[*(history or []), {"role": "user", "content": query}],
        files=[{"type": "collection", "id": winning_collection_id}],
        return_raw=True,
    )
    return {**raw, "winning_collection_id": winning_collection_id, "collection_scores": scores}


async def ask_joint(
    client: OwuiClient, model: str, collection_ids: list[str], query: str, history: list[dict] | None = None
) -> dict:
    """Returns Open WebUI's own raw chat-completion response, unmodified —
    identical shape to calling /api/chat/completions directly with multiple
    `{"type": "collection", ...}` files entries. `history` — see
    ask_with_routing above."""
    return await client.chat_completion(
        model=model,
        messages=[*(history or []), {"role": "user", "content": query}],
        files=[{"type": "collection", "id": cid} for cid in collection_ids],
        return_raw=True,
    )


async def search_collections(client: OwuiClient, collection_ids: list[str], query: str, k: int = 10) -> list[dict]:
    """Pure retrieval, no chat completion — the exact pooled/ranked chunks
    ask_joint would hand to the LLM as `files`, surfaced directly instead.
    Built for judging embedding-model quality on its own terms: whether the
    real top-k matches for a query are actually relevant, without an LLM's
    phrasing smoothing over mediocre retrieval either way.

    Returns highest-score-first (same score semantics as ask_with_routing —
    despite the field's name, higher is better), each as
    `{document, score, file_id, filename}`.
    """
    result = await client.query_collection(collection_ids, query, k=k)
    documents = (result.get("documents") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]

    results = []
    for i, document in enumerate(documents):
        metadata = metadatas[i] if i < len(metadatas) else None
        results.append(
            {
                "document": document,
                "score": distances[i] if i < len(distances) else None,
                "file_id": (metadata or {}).get("file_id"),
                "filename": (metadata or {}).get("name"),
            }
        )
    return results
