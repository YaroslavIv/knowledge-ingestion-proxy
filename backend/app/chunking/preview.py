from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter, TokenTextSplitter
from pydantic import BaseModel

from app.redaction import Redaction, apply_redactions, map_cut_offset_to_original


class RetrievalChunkingConfig(BaseModel):
    text_splitter: str = ""
    chunk_size: int = 1000
    chunk_overlap: int = 100
    tiktoken_encoding_name: str = "cl100k_base"


@dataclass
class ChunkRange:
    start: int
    end: int


def with_token_overrides(
    config: RetrievalChunkingConfig, chunk_size: int | None, chunk_overlap: int | None
) -> RetrievalChunkingConfig:
    """Build a preview-only config that overrides the instance's real chunk
    size/overlap, in *tokens* — for exploring "what if chunks were this big"
    without touching Open WebUI's actual (character-based, by default)
    production settings. A no-op (returns `config` unchanged) when neither
    override is given.

    If only one of the two is overridden, the other falls back to the base
    config's value — but that base value is in a *different unit*
    (characters, typically) from the token-based override, so it can easily
    come out larger than the new chunk_size (e.g. overriding just chunk_size
    to a small number while the real instance's character-based overlap is
    100) — which the underlying TokenTextSplitter rejects outright. The
    overlap is clamped below chunk_size to keep any override combination
    valid instead of erroring.
    """
    if chunk_size is None and chunk_overlap is None:
        return config

    effective_size = chunk_size if chunk_size is not None else config.chunk_size
    effective_overlap = chunk_overlap if chunk_overlap is not None else config.chunk_overlap
    effective_overlap = max(0, min(effective_overlap, effective_size - 1))

    return RetrievalChunkingConfig(
        text_splitter="token",
        chunk_size=effective_size,
        chunk_overlap=effective_overlap,
        tiktoken_encoding_name=config.tiktoken_encoding_name,
    )


def compute_chunk_preview(text: str, config: RetrievalChunkingConfig) -> list[ChunkRange]:
    """Approximate how Open WebUI will chunk this text for embedding.

    This mirrors the *main* splitter step of Open WebUI's `save_docs_to_vector_db()`
    (routers/retrieval.py) using the real CHUNK_SIZE/CHUNK_OVERLAP/TEXT_SPLITTER
    values fetched from the target instance. It deliberately skips replicating the
    optional MarkdownHeaderTextSplitter pre-pass: that step re-segments text at
    header boundaries before the main splitter runs, and reconstructing exact
    character offsets back into the original text through two chained splitters
    is fragile for a preview feature. Running the main splitter directly against
    the original text yields very close (usually identical) boundaries for
    typical documents, at the cost of being an approximation rather than a
    byte-exact replica when markdown header splitting is enabled upstream.
    """
    if not text.strip():
        return []

    if config.text_splitter == "token":
        splitter = TokenTextSplitter(
            encoding_name=config.tiktoken_encoding_name,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
        )
    else:
        # "", "character", and "token_transformers" (HF-tokenizer-length-based,
        # not replicated here to avoid a heavy transformers dependency in this
        # lightweight proxy) all fall back to the plain character splitter.
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            add_start_index=True,
        )

    chunks = splitter.create_documents([text])

    ranges = []
    cursor = 0
    for doc in chunks:
        start = doc.metadata.get("start_index")
        if start is None:
            # TokenTextSplitter doesn't support add_start_index; locate the
            # chunk textually, searching forward from the last match.
            start = text.find(doc.page_content, cursor)
            if start == -1:
                continue
        end = start + len(doc.page_content)
        ranges.append(ChunkRange(start=start, end=end))
        cursor = start + 1

    return ranges


def preview_with_redactions(
    text: str, redactions: list[Redaction], config: RetrievalChunkingConfig
) -> list[ChunkRange]:
    """Compute chunk boundaries on the post-redaction text, then re-express them
    in original-text coordinates so they line up with the (unredacted-looking,
    marks-only) text an editor is displaying. Shared by the in-progress-session
    preview and the "edit an already-committed file" preview.
    """
    effective_text = apply_redactions(text, redactions)
    chunks = compute_chunk_preview(effective_text, config)
    return [
        ChunkRange(
            start=map_cut_offset_to_original(c.start, redactions),
            end=map_cut_offset_to_original(c.end, redactions),
        )
        for c in chunks
    ]
