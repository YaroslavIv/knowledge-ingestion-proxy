import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import OriginalFileBlob


def _originals_dir() -> Path:
    path = Path(settings.originals_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def save_original(
    db: AsyncSession, session_id: str, filename: str, content_type: str, data: bytes
) -> None:
    """Cache one just-uploaded document's real bytes, keyed by its ingestion
    session — there's no Open WebUI file_id yet at this point.
    """
    blob_id = str(uuid.uuid4())
    stored_path = _originals_dir() / blob_id
    stored_path.write_bytes(data)

    db.add(
        OriginalFileBlob(
            id=blob_id,
            session_id=session_id,
            file_id=None,
            content_type=content_type or "application/octet-stream",
            filename=filename,
            stored_path=str(stored_path),
        )
    )
    await db.flush()


async def attach_to_file(db: AsyncSession, session_id: str, file_id: str) -> None:
    """Point a cached original at the Open WebUI file_id it just became —
    replacing whatever was previously cached for that file_id (a "Replace
    file…" really is a new original, not an edit of the old one).
    """
    existing_for_session = (
        await db.execute(select(OriginalFileBlob).where(OriginalFileBlob.session_id == session_id))
    ).scalar_one_or_none()
    if existing_for_session is None:
        return

    stale = (
        await db.execute(
            select(OriginalFileBlob).where(
                OriginalFileBlob.file_id == file_id, OriginalFileBlob.id != existing_for_session.id
            )
        )
    ).scalar_one_or_none()
    if stale is not None:
        await _delete_blob(db, stale)

    existing_for_session.file_id = file_id
    await db.flush()


async def get_original(db: AsyncSession, file_id: str) -> tuple[bytes, str, str] | None:
    blob = (
        await db.execute(select(OriginalFileBlob).where(OriginalFileBlob.file_id == file_id))
    ).scalar_one_or_none()
    if blob is None:
        return None
    path = Path(blob.stored_path)
    if not path.is_file():
        return None
    return path.read_bytes(), blob.content_type, blob.filename


async def has_original(db: AsyncSession, file_id: str) -> bool:
    """Cheap existence check for the file list — whether a real original
    (e.g. an actual PDF) is cached for this file_id, without reading its
    bytes off disk the way get_original does. Drives the "has original"
    indicator so it's obvious which files only ever had extracted text
    pushed to Open WebUI (no real original captured) versus which ones
    this proxy actually ingested and can show the true source document for.
    """
    stored_path = (
        await db.execute(select(OriginalFileBlob.stored_path).where(OriginalFileBlob.file_id == file_id))
    ).scalar_one_or_none()
    return stored_path is not None and Path(stored_path).is_file()


async def delete_original_by_file_id(db: AsyncSession, file_id: str) -> None:
    blob = (
        await db.execute(select(OriginalFileBlob).where(OriginalFileBlob.file_id == file_id))
    ).scalar_one_or_none()
    if blob is not None:
        await _delete_blob(db, blob)


async def purge_orphaned(db: AsyncSession, older_than_hours: int) -> None:
    """Cached originals whose ingestion session ended (finalized into a
    different blob already, expired, or was simply abandoned) without ever
    being attached to a file_id — nothing will ever claim these.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    rows = (
        await db.execute(
            select(OriginalFileBlob).where(
                OriginalFileBlob.file_id.is_(None), OriginalFileBlob.created_at < cutoff
            )
        )
    ).scalars().all()
    for blob in rows:
        await _delete_blob(db, blob)


async def _delete_blob(db: AsyncSession, blob: OriginalFileBlob) -> None:
    Path(blob.stored_path).unlink(missing_ok=True)
    await db.execute(delete(OriginalFileBlob).where(OriginalFileBlob.id == blob.id))
