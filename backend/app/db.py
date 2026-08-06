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
    columns = {row[1] for row in (await conn.exec_driver_sql("PRAGMA table_info(course_project)")).fetchall()}
    if "product_knowledge_id" not in columns:
        return
    if "product_knowledge_ids" not in columns:
        await conn.exec_driver_sql("ALTER TABLE course_project ADD COLUMN product_knowledge_ids TEXT")
    await conn.exec_driver_sql(
        "UPDATE course_project SET product_knowledge_ids = json_array(product_knowledge_id) "
        "WHERE product_knowledge_ids IS NULL AND product_knowledge_id IS NOT NULL"
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
