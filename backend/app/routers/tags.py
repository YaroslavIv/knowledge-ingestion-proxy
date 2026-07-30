from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_owui_client
from app.models import TagDictionary
from app.owui_client import OwuiClient
from app.schemas import TaggedCollectionSummary
from app.versioning import list_latest_by_tag

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("", response_model=list[str])
async def list_tags(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(TagDictionary.name).order_by(TagDictionary.name))).scalars().all()
    return list(rows)


@router.get("/{tag}/collections", response_model=list[TaggedCollectionSummary])
async def get_latest_collections_by_tag(
    tag: str, db: AsyncSession = Depends(get_db), client: OwuiClient = Depends(get_owui_client)
):
    """Every collection tagged `tag`, collapsed to just the newest per clone
    lineage (see app/versioning.py:list_latest_by_tag) — powers the
    dedicated per-tag tab (e.g. "CoE") that shows only what's actively in
    use under that tag, not every superseded older version too."""
    rows = await list_latest_by_tag(db, client, tag)
    return [TaggedCollectionSummary(**row) for row in rows]
