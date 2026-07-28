import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TrackedCollection, TrackedFile

_TRAILING_VERSION_RE = re.compile(r"(\d+)\.(\d+)$")


def suggest_next_version_tag(tag: str) -> str:
    """Bump a trailing "N.N" in a version tag, e.g. "uvss 2.0" -> "uvss 2.1".

    Falls back to appending " v2" when no such pattern is found, rather than
    guessing at a scheme that doesn't apply.
    """
    match = _TRAILING_VERSION_RE.search(tag)
    if not match:
        return f"{tag} v2".strip()
    major, minor = match.groups()
    return _TRAILING_VERSION_RE.sub(f"{major}.{int(minor) + 1}", tag)


async def get_tracked_collection(db: AsyncSession, knowledge_id: str) -> TrackedCollection | None:
    return await db.get(TrackedCollection, knowledge_id)


async def get_or_create_tracked_collection(
    db: AsyncSession, knowledge_id: str, default_tag: str = "v1.0"
) -> TrackedCollection:
    """Collections created before this feature shipped (or created directly
    in Open WebUI, bypassing the proxy) have no tracked row yet — synthesize
    one on first touch rather than erroring.
    """
    existing = await db.get(TrackedCollection, knowledge_id)
    if existing:
        return existing
    row = TrackedCollection(knowledge_id=knowledge_id, version_tag=default_tag)
    db.add(row)
    await db.flush()
    return row


async def get_or_synthesize_tracked_file(db: AsyncSession, file_id: str, knowledge_id: str) -> TrackedFile:
    existing = await db.get(TrackedFile, file_id)
    if existing:
        return existing
    collection = await get_or_create_tracked_collection(db, knowledge_id)
    row = TrackedFile(file_id=file_id, knowledge_id=knowledge_id, version_tag=collection.version_tag, tags=[])
    db.add(row)
    await db.flush()
    return row


async def record_new_file(db: AsyncSession, file_id: str, knowledge_id: str) -> TrackedFile:
    """A brand-new file added to a collection is, by definition, introduced
    in the collection's *current* version.
    """
    collection = await get_or_create_tracked_collection(db, knowledge_id)
    row = TrackedFile(file_id=file_id, knowledge_id=knowledge_id, version_tag=collection.version_tag, tags=[])
    db.add(row)
    await db.flush()
    return row


async def count_changed_files(db: AsyncSession, knowledge_id: str, current_version_tag: str) -> tuple[int, int]:
    """(changed, total) file counts for a collection, purely from our own DB —
    no need to reach out to Open WebUI just to render a lineage tree.
    """
    rows = (await db.execute(select(TrackedFile).where(TrackedFile.knowledge_id == knowledge_id))).scalars().all()
    changed = sum(1 for row in rows if row.version_tag == current_version_tag)
    return changed, len(rows)


async def bump_file_version(db: AsyncSession, file_id: str, knowledge_id: str, method: str) -> TrackedFile:
    """Mark a file as changed in the collection's current version. `method`
    is "text_edit" or "file_replace" — recorded for context only, both bump
    the tag the same way.
    """
    collection = await get_or_create_tracked_collection(db, knowledge_id)
    tracked = await get_or_synthesize_tracked_file(db, file_id, knowledge_id)
    tracked.version_tag = collection.version_tag
    tracked.last_change_method = method
    tracked.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return tracked
