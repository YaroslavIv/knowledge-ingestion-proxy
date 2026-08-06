from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(f"sqlite+aiosqlite:///{settings.db_path}", echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    # SQLite won't create a missing parent directory on its own — without
    # this, a fresh checkout (or a custom PROXY_DB_PATH pointing at a new
    # folder) fails outright instead of just creating the file. Reads
    # settings.db_path fresh (rather than at import time) so tests that
    # monkeypatch it before calling init_db() create the right directory.
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_product_knowledge_ids(conn)
        await _migrate_single_to_list_column(conn, "course_project", "competitors_knowledge_id", "competitors_knowledge_ids")
        await _migrate_single_to_list_column(conn, "course_project", "instructions_knowledge_id", "instructions_knowledge_ids")


async def _migrate_product_knowledge_ids(conn) -> None:
    """course_project.product_knowledge_id (a single collection) became
    product_knowledge_ids (a JSON list) — create_all only creates missing
    tables/columns, it never alters an existing one, so a real deployment's
    existing course_project table still has the old column and is missing
    the new one until this runs. Carries the old single id forward into the
    new list so existing course projects don't lose their product material.
    A no-op on a fresh DB (created directly with the new schema, so the old
    column never existed) and a no-op on subsequent runs (nothing left to
    backfill once migrated).
    """
    await _migrate_single_to_list_column(conn, "course_project", "product_knowledge_id", "product_knowledge_ids")


async def _migrate_single_to_list_column(conn, table: str, old_column: str, new_column: str) -> None:
    """Generic version of the product_knowledge_id(s) migration above —
    competitors_knowledge_id and instructions_knowledge_id went through the
    exact same single-collection -> JSON-list change later on. Same
    no-op-on-fresh-DB / no-op-once-migrated guarantees.
    """
    columns = {row[1] for row in (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).fetchall()}
    if old_column not in columns:
        return
    if new_column not in columns:
        await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {new_column} TEXT")
    await conn.exec_driver_sql(
        f"UPDATE {table} SET {new_column} = json_array({old_column}) "
        f"WHERE {new_column} IS NULL AND {old_column} IS NOT NULL"
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
