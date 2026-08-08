import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.backup import create_backup, delete_backup, get_backup_path, list_backups
from app.schemas import BackupSummary

router = APIRouter(prefix="/api/backups", tags=["backups"])


@router.get("", response_model=list[BackupSummary])
async def list_all_backups():
    return [
        BackupSummary(filename=b["filename"], size_bytes=b["size_bytes"], created_at=b["created_at"].isoformat())
        for b in list_backups()
    ]


@router.post("", response_model=BackupSummary)
async def trigger_backup():
    """Manual "back up right now" — the daily scheduled job (see
    app/main.py) already covers the routine case, but waiting for the next
    scheduled run isn't good enough right after wanting a fresh safety net
    immediately (e.g. right after noticing something's wrong elsewhere).
    Offloaded to a thread since create_backup does blocking file/DB I/O.
    force=True: an explicit request for a fresh safety net right now must
    always produce one, even if nothing's changed since the last daily run.
    """
    path = await asyncio.to_thread(create_backup, force=True)
    stat = path.stat()
    return BackupSummary(
        filename=path.name,
        size_bytes=stat.st_size,
        created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    )


@router.get("/{filename}/download")
async def download_backup(filename: str):
    path = get_backup_path(filename)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")
    return FileResponse(path, media_type="application/zip", filename=filename)


@router.delete("/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backup_endpoint(filename: str):
    if not delete_backup(filename):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")
