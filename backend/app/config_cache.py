import time

from app.chunking.preview import RetrievalChunkingConfig
from app.owui_client import OwuiClient

_TTL_SECONDS = 60
# Keyed by base_url — a single global cache would serve one connection's
# chunk-size/overlap config to a different instance for up to a minute after
# switching (see app/connections.py), which is silently wrong rather than
# just stale.
_cache: dict[str, tuple[RetrievalChunkingConfig, float]] = {}


async def get_chunking_config(client: OwuiClient, force: bool = False) -> RetrievalChunkingConfig:
    key = client.base_url
    cached = _cache.get(key)
    if not force and cached is not None and (time.monotonic() - cached[1]) < _TTL_SECONDS:
        return cached[0]

    raw = await client.get_retrieval_config()
    config = RetrievalChunkingConfig(
        text_splitter=raw.get("TEXT_SPLITTER") or "",
        chunk_size=raw.get("CHUNK_SIZE") or 1000,
        chunk_overlap=raw.get("CHUNK_OVERLAP") or 100,
    )
    _cache[key] = (config, time.monotonic())
    return config
