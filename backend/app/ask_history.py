"""Persists a history of `/api/ask/joint` calls for later analysis — see
app/models.py's AskJointLog for what's actually stored and why.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AskJointLog


async def record_ask_joint(
    db: AsyncSession,
    *,
    query: str,
    tag: str | None,
    collection_ids: list[str],
    model: str,
    answer: str | None,
    embedding: list[float] | None = None,
) -> None:
    db.add(
        AskJointLog(
            query=query,
            tag=tag,
            collection_ids=collection_ids,
            model=model,
            answer=answer,
            embedding=embedding,
        )
    )
    await db.commit()


async def list_ask_joint_history(db: AsyncSession, limit: int = 200) -> list[AskJointLog]:
    rows = (
        await db.execute(select(AskJointLog).order_by(AskJointLog.created_at.desc()).limit(limit))
    ).scalars().all()
    return list(rows)
