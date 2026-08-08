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

from app.chunking.preview import ChunkRange, compute_chunk_preview
from app.config_cache import get_chunking_config
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


def _chunk_index_for_text(full_text: str, ranges: list[ChunkRange], chunk_text: str) -> int | None:
    """Which of this file's real chunk boundaries a retrieved chunk's text
    falls into — an exact slice match first (the common case: the retrieved
    text IS one of these ranges verbatim), falling back to locating the
    text's own offset and finding which computed range contains it (covers
    the rare case where our approximate splitter's boundaries drift slightly
    from Open WebUI's real ones — see compute_chunk_preview's docstring)."""
    for i, r in enumerate(ranges):
        if full_text[r.start : r.end] == chunk_text:
            return i
    offset = full_text.find(chunk_text)
    if offset == -1:
        return None
    for i, r in enumerate(ranges):
        if r.start <= offset < r.end:
            return i
    return None


async def _chunk_ranges_for_file(client: OwuiClient, cache: dict, file_id: str) -> tuple[str, list[ChunkRange]]:
    if file_id not in cache:
        full_text = await client.get_file_content(file_id)
        config = await get_chunking_config(client)
        cache[file_id] = (full_text, compute_chunk_preview(full_text, config))
    return cache[file_id]


async def _chunk_distance(client: OwuiClient, cache: dict, file_id: str, text_a: str, text_b: str) -> int | None:
    """How many chunk-widths apart two retrieved chunks from the same file
    really are — 0 for the literal same chunk, otherwise the gap between
    their positions in that file's real chunking (see compute_chunk_preview),
    or None if either couldn't be located (e.g. the file changed since these
    were embedded). Lets a robustness check ("do two phrasings of the same
    question retrieve the same content?") distinguish "same chunk" from
    "neighboring chunk" from "unrelated part of the file", not just
    same-file-or-not.
    """
    if text_a == text_b:
        return 0
    full_text, ranges = await _chunk_ranges_for_file(client, cache, file_id)
    idx_a = _chunk_index_for_text(full_text, ranges, text_a)
    idx_b = _chunk_index_for_text(full_text, ranges, text_b)
    if idx_a is None or idx_b is None:
        return None
    return abs(idx_a - idx_b)


async def compare_searches(
    client: OwuiClient, collection_ids: list[str], query_a: str, query_b: str, k: int = 10
) -> dict:
    """Runs two independent retrieval-only searches (see search_collections)
    and diffs them — built for checking retrieval stability across
    paraphrases, translations, or reordered wording of "the same" question.

    Returns `{results_a, results_b, comparison}`: the two plain result lists,
    plus a `comparison` with `file_overlap`/`file_total` (how many distinct
    files show up in both result sets vs either), and `matches` — chunk-level
    pairings across the two sets for every file present in both, greedily
    paired by chunk proximity (see _chunk_distance), each carrying both
    scores and their difference alongside the chunk distance.
    """
    results_a = await search_collections(client, collection_ids, query_a, k=k)
    results_b = await search_collections(client, collection_ids, query_b, k=k)

    files_a = {r["file_id"] for r in results_a if r["file_id"]}
    files_b = {r["file_id"] for r in results_b if r["file_id"]}
    shared_files = files_a & files_b

    cache: dict = {}
    matches = []
    for file_id in shared_files:
        a_chunks = [(i, r) for i, r in enumerate(results_a) if r["file_id"] == file_id]
        b_chunks = [(i, r) for i, r in enumerate(results_b) if r["file_id"] == file_id]
        used_b: set[int] = set()

        for _, a in a_chunks:
            best: tuple[int, int, dict] | None = None
            for b_i, b in b_chunks:
                if b_i in used_b:
                    continue
                distance = await _chunk_distance(client, cache, file_id, a["document"], b["document"])
                if distance is None:
                    continue
                if best is None or distance < best[0]:
                    best = (distance, b_i, b)
            if best is not None:
                distance, b_i, b = best
                used_b.add(b_i)
                matches.append(
                    {
                        "file_id": file_id,
                        "filename": a["filename"] or b["filename"],
                        "document_a": a["document"],
                        "document_b": b["document"],
                        "score_a": a["score"],
                        "score_b": b["score"],
                        "score_delta": (
                            None if a["score"] is None or b["score"] is None else a["score"] - b["score"]
                        ),
                        "chunk_distance": distance,
                    }
                )

    return {
        "results_a": results_a,
        "results_b": results_b,
        "comparison": {
            "file_overlap": len(shared_files),
            "file_total": len(files_a | files_b),
            "matches": matches,
        },
    }
