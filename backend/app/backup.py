"""Daily local safety net for everything this proxy itself persists —
cached original files, published course-module outputs, and its own
database (course projects, tracked file/collection versions, feedback
notes, saved connections). Deliberately NOT anything Open WebUI stores
itself (knowledge-base text, embeddings) — this proxy never holds a copy
of that, and can't back up storage it doesn't own. See app/main.py for the
daily schedule and app/routers/backups.py for the manual-trigger/download
endpoints.
"""
from __future__ import annotations

import hashlib
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings

# Stored inside every backup zip alongside the real content, purely so the
# next run can tell whether anything actually changed since then — see
# _content_hash/_latest_backup_hash.
_HASH_ENTRY_NAME = "BACKUP_CONTENT_HASH.txt"


def _backups_dir() -> Path:
    path = Path(settings.backups_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _content_hash() -> str:
    """A hash of everything create_backup would actually capture, used to
    skip writing an identical daily backup. Deliberately NOT a hash of the
    raw .db file bytes — SQLite's on-disk page layout can shift (vacuuming,
    free-page reuse) with no real change to the data, which would make
    every single day look "changed" even when nothing was. `iterdump()`
    reflects only the logical row content, which is what actually matters
    here.
    """
    conn = sqlite3.connect(settings.db_path)
    try:
        dump = "\n".join(conn.iterdump())
    finally:
        conn.close()

    parts = [hashlib.sha256(dump.encode("utf-8")).hexdigest()]
    for label, dir_path in (
        ("originals", Path(settings.originals_dir)),
        ("course_outputs", Path(settings.course_outputs_dir)),
    ):
        if not dir_path.is_dir():
            continue
        for path in sorted(p for p in dir_path.rglob("*") if p.is_file()):
            rel = path.relative_to(dir_path)
            parts.append(f"{label}/{rel}:{hashlib.sha256(path.read_bytes()).hexdigest()}")

    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _latest_backup_hash(backups_dir: Path) -> str | None:
    existing = sorted(backups_dir.glob("backup_*.zip"), reverse=True)
    if not existing:
        return None
    try:
        with zipfile.ZipFile(existing[0]) as zf:
            return zf.read(_HASH_ENTRY_NAME).decode("utf-8")
    except (KeyError, zipfile.BadZipFile, OSError):
        return None


def _snapshot_sqlite_db(dest_path: Path) -> None:
    """A plain byte-copy of the .db file risks catching it mid-write (this
    process has it open continuously) and producing a corrupt backup —
    SQLite's own online-backup API instead takes a real consistent
    snapshot, safe to run while the app keeps serving requests."""
    source = sqlite3.connect(settings.db_path)
    try:
        dest = sqlite3.connect(str(dest_path))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()


def _add_dir_to_zip(zf: zipfile.ZipFile, source_dir: Path, arc_prefix: str) -> None:
    if not source_dir.is_dir():
        return
    for path in source_dir.rglob("*"):
        if path.is_file():
            zf.write(path, arcname=f"{arc_prefix}/{path.relative_to(source_dir)}")


def create_backup(*, force: bool = False) -> Path | None:
    """Builds one zip with a timestamped name and prunes backups older
    than backup_retention_days. Runs entirely synchronously (SQLite backup
    + filesystem I/O) — callers on the async side must offload this to a
    thread (see routers/backups.py); the daily scheduler job in main.py
    runs it directly since APScheduler already executes plain functions in
    its own worker thread.

    force=False (the default, used by the daily scheduled job) skips
    writing a new zip — returning None — when nothing has actually changed
    since the most recent backup, so routine daily runs don't pile up
    identical copies. force=True (the manual "Back up now" button) always
    writes one: an explicit request for a fresh safety net shouldn't be
    silently turned into a no-op just because nothing changed since
    yesterday.
    """
    backups_dir = _backups_dir()
    content_hash = _content_hash()
    if not force and _latest_backup_hash(backups_dir) == content_hash:
        _prune_old_backups(backups_dir)
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_path = backups_dir / f"backup_{timestamp}.zip"
    db_snapshot_path = backups_dir / f".tmp_db_snapshot_{timestamp}.db"

    try:
        _snapshot_sqlite_db(db_snapshot_path)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_snapshot_path, arcname="ingestion_proxy.db")
            _add_dir_to_zip(zf, Path(settings.originals_dir), "originals")
            _add_dir_to_zip(zf, Path(settings.course_outputs_dir), "course_outputs")
            zf.writestr(_HASH_ENTRY_NAME, content_hash)
    finally:
        db_snapshot_path.unlink(missing_ok=True)

    _prune_old_backups(backups_dir)
    return zip_path


def _prune_old_backups(backups_dir: Path) -> None:
    """Keeps disk usage bounded — daily backups accumulate forever
    otherwise. Age is judged by each file's own mtime, not its name, so
    this stays correct even if the naming scheme ever changes."""
    cutoff = datetime.now(timezone.utc).timestamp() - settings.backup_retention_days * 86400
    for path in backups_dir.glob("backup_*.zip"):
        if path.stat().st_mtime < cutoff:
            path.unlink()


def list_backups() -> list[dict]:
    backups_dir = _backups_dir()
    results = []
    for path in sorted(backups_dir.glob("backup_*.zip"), reverse=True):
        stat = path.stat()
        results.append(
            {
                "filename": path.name,
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            }
        )
    return results


def get_backup_path(filename: str) -> Path | None:
    """Resolves a backup filename to its real path — refuses anything that
    isn't a plain "backup_*.zip" name inside backups_dir, so a filename
    like "../../etc/passwd" can never escape the backups directory."""
    if "/" in filename or "\\" in filename or not filename.startswith("backup_") or not filename.endswith(".zip"):
        return None
    path = _backups_dir() / filename
    return path if path.is_file() else None


def delete_backup(filename: str) -> bool:
    """Removes one backup zip. Reuses get_backup_path's own name validation
    so this can't be tricked into deleting anything outside backups_dir."""
    path = get_backup_path(filename)
    if path is None:
        return False
    path.unlink()
    return True
