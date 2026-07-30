import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TrackedCollection, TrackedFile
from app.owui_client import OwuiClient

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


async def _latest_tracked_collections_by_tag(
    db: AsyncSession, existing_ids: set[str], tag: str
) -> list[TrackedCollection]:
    """Every tracked collection tagged `tag` that still exists in Open WebUI,
    collapsed down to just the newest in each clone lineage — e.g. if a
    "coe"-tagged collection was cloned into a newer "coe"-tagged version
    (parent_knowledge_id chain), only that newer one is returned.
    Independent collections that happen to share the tag without being
    clones of one another are all kept.

    A tagged collection whose parent is ALSO tagged gets dropped in favor of
    the parent's (or further descendant's) more recent copy; a tagged
    collection is only kept when nothing else in this same tagged set names
    it as a parent.
    """
    rows = (await db.execute(select(TrackedCollection))).scalars().all()
    tagged = [row for row in rows if tag in (row.tags or []) and row.knowledge_id in existing_ids]
    tagged_ids = {row.knowledge_id for row in tagged}
    superseded = {row.parent_knowledge_id for row in tagged if row.parent_knowledge_id in tagged_ids}
    return [row for row in tagged if row.knowledge_id not in superseded]


async def resolve_collection_ids_by_tag(db: AsyncSession, client: OwuiClient, tag: str) -> list[str]:
    existing_ids = {item["id"] for item in await client.list_knowledge_bases()}
    rows = await _latest_tracked_collections_by_tag(db, existing_ids, tag)
    return [row.knowledge_id for row in rows]


async def list_latest_by_tag(db: AsyncSession, client: OwuiClient, tag: str) -> list[dict]:
    """Same collapsing as resolve_collection_ids_by_tag, but with each
    collection's display name attached (for a tag-scoped table/listing UI,
    where a bare id isn't enough) — the name only lives on Open WebUI's own
    knowledge-base object, not in our tracked-collection row.
    """
    items = await client.list_knowledge_bases()
    items_by_id = {item["id"]: item for item in items}
    rows = await _latest_tracked_collections_by_tag(db, set(items_by_id), tag)
    return [
        {"id": row.knowledge_id, "name": items_by_id[row.knowledge_id]["name"], "version_tag": row.version_tag}
        for row in rows
    ]


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
