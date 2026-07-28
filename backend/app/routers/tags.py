from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import TagDictionary

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("", response_model=list[str])
async def list_tags(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(TagDictionary.name).order_by(TagDictionary.name))).scalars().all()
    return list(rows)
