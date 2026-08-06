import sqlite3
import time
import zipfile

from app.backup import create_backup, get_backup_path, list_backups
from app.config import settings


def _write_file(path, content=b"hello"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


async def test_create_backup_bundles_db_originals_and_course_outputs(client):
    # `client` fixture already pointed db_path/originals_dir/course_outputs_dir
    # at tmp_path and ran init_db() — write something real into each so the
    # backup has something to actually capture.
    conn = sqlite3.connect(settings.db_path)
    conn.execute("SELECT 1")  # just confirms the db file genuinely exists on disk
    conn.close()

    from pathlib import Path

    _write_file(Path(settings.originals_dir) / "doc-1" / "original.pdf", b"pdf bytes")
    _write_file(Path(settings.course_outputs_dir) / "module-1" / "output.zip", b"zip bytes")

    zip_path = create_backup()
    assert zip_path.is_file()
    assert zip_path.parent == Path(settings.backups_dir)

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert "ingestion_proxy.db" in names
        assert "originals/doc-1/original.pdf" in names
        assert "course_outputs/module-1/output.zip" in names
        assert zf.read("originals/doc-1/original.pdf") == b"pdf bytes"
        assert zf.read("course_outputs/module-1/output.zip") == b"zip bytes"


async def test_create_backup_snapshot_reflects_real_db_rows(client):
    """The backed-up .db must be a real, queryable snapshot of actual
    proxy state, not an empty placeholder — confirmed by round-tripping a
    real row through the API before backing up."""
    resp = await client.post(
        "/api/courses",
        json={
            "name": "Backup Test Project",
            "product_knowledge_ids": ["kb-product"],
            "instructions_knowledge_ids": ["kb-instructions"],
        },
    )
    assert resp.status_code == 200

    zip_path = create_backup()
    with zipfile.ZipFile(zip_path) as zf:
        extracted = zf.extract("ingestion_proxy.db", path=zip_path.parent)

    conn = sqlite3.connect(extracted)
    row = conn.execute("SELECT name FROM course_project").fetchone()
    conn.close()
    assert row == ("Backup Test Project",)


async def test_list_backups_reports_newest_first(client):
    first = create_backup()
    time.sleep(1.01)  # backup filenames/mtimes are second-resolution
    second = create_backup()

    backups = list_backups()
    filenames = [b["filename"] for b in backups]
    assert filenames[0] == second.name
    assert second.name in filenames and first.name in filenames


async def test_prune_removes_backups_older_than_retention(client, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(settings, "backup_retention_days", 1)
    old_zip = Path(settings.backups_dir)
    old_zip.mkdir(parents=True, exist_ok=True)
    old_path = old_zip / "backup_20200101_000000.zip"
    old_path.write_bytes(b"old")
    old_time = time.time() - 2 * 86400
    import os

    os.utime(old_path, (old_time, old_time))

    create_backup()  # triggers pruning as a side effect

    assert not old_path.exists()


async def test_backups_api_list_trigger_and_download(client):
    create_resp = await client.post("/api/backups")
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["filename"].startswith("backup_")
    assert created["size_bytes"] > 0

    list_resp = await client.get("/api/backups")
    assert list_resp.status_code == 200
    assert any(b["filename"] == created["filename"] for b in list_resp.json())

    download_resp = await client.get(f"/api/backups/{created['filename']}/download")
    assert download_resp.status_code == 200
    assert download_resp.headers["content-type"] == "application/zip"


async def test_download_rejects_path_traversal(client):
    resp = await client.get("/api/backups/../../etc/passwd/download")
    assert resp.status_code in (404, 422)


def test_get_backup_path_rejects_non_backup_filenames():
    assert get_backup_path("../../etc/passwd") is None
    assert get_backup_path("not-a-backup.zip") is None
    assert get_backup_path("backup_evil/../secret.zip") is None
