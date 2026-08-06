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

import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings


def _backups_dir() -> Path:
    path = Path(settings.backups_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


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


def create_backup() -> Path:
    """Builds one zip with a timestamped name and prunes backups older
    than backup_retention_days. Runs entirely synchronously (SQLite backup
    + filesystem I/O) — callers on the async side must offload this to a
    thread (see routers/backups.py); the daily scheduler job in main.py
    runs it directly since APScheduler already executes plain functions in
    its own worker thread.
    """
    backups_dir = _backups_dir()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_path = backups_dir / f"backup_{timestamp}.zip"
    db_snapshot_path = backups_dir / f".tmp_db_snapshot_{timestamp}.db"

    try:
        _snapshot_sqlite_db(db_snapshot_path)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_snapshot_path, arcname="ingestion_proxy.db")
            _add_dir_to_zip(zf, Path(settings.originals_dir), "originals")
            _add_dir_to_zip(zf, Path(settings.course_outputs_dir), "course_outputs")
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
