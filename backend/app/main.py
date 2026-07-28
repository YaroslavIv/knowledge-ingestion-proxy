import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, select

from app.config import settings
from app.db import AsyncSessionLocal, init_db
from app.models import IngestionSession, OwuiConnection
from app.original_storage import purge_orphaned
from app.routers import ask, connections, courses, documents, kb, preview, tags
from app.security import require_api_key

log = logging.getLogger(__name__)


async def _purge_expired_sessions() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(IngestionSession).where(IngestionSession.expires_at < datetime.now(timezone.utc)))
        await session.commit()

    async with AsyncSessionLocal() as session:
        # Cached originals never claimed by a successful finalize (abandoned
        # or failed uploads) — nothing will ever attach to these.
        await purge_orphaned(session, older_than_hours=settings.session_ttl_hours)
        await session.commit()


async def _bootstrap_default_connection() -> None:
    """Back-compat for the old PROXY_OWUI_BASE_URL/PROXY_OWUI_API_KEY env-var
    setup: seed it as a saved connection on first run only, so existing
    deployments don't have to sign in again. Once any connection has been
    saved (via the real login flow or this bootstrap), this never runs again.
    """
    if not settings.owui_api_key:
        return
    async with AsyncSessionLocal() as session:
        existing = (await session.execute(select(OwuiConnection))).scalars().first()
        if existing is not None:
            return
        session.add(
            OwuiConnection(
                label="Default (from env)",
                base_url=settings.owui_base_url.rstrip("/"),
                email="(configured via PROXY_OWUI_API_KEY)",
                token=settings.owui_api_key,
                is_active=True,
            )
        )
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _bootstrap_default_connection()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(_purge_expired_sessions, "interval", minutes=30)
    scheduler.start()

    yield

    scheduler.shutdown(wait=False)


app = FastAPI(title="Knowledge Ingestion Proxy", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Original-Filename", "X-Original-Source"],
)

# /api/health stays open (monitoring/health checks) by simply not being
# part of any of these routers — every real API route requires the key
# once PROXY_API_KEY is set.
_auth = [Depends(require_api_key)]
app.include_router(ask.router, dependencies=_auth)
app.include_router(connections.router, dependencies=_auth)
app.include_router(courses.router, dependencies=_auth)
app.include_router(documents.router, dependencies=_auth)
app.include_router(kb.router, dependencies=_auth)
app.include_router(preview.router, dependencies=_auth)
app.include_router(tags.router, dependencies=_auth)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
