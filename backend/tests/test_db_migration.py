import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db import init_db


async def test_existing_single_product_knowledge_id_is_carried_into_the_new_list(tmp_path, monkeypatch):
    """Simulates a real deployment's existing course_project table — created
    back when product_knowledge_id was a single column, before it became
    product_knowledge_ids — to confirm init_db()'s migration carries the old
    value forward instead of silently dropping every existing course
    project's link to its product material.
    """
    db_path = tmp_path / "legacy.db"
    monkeypatch.setattr(settings, "db_path", str(db_path))

    import app.db as db_module

    legacy_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with legacy_engine.begin() as conn:
        await conn.exec_driver_sql(
            """
            CREATE TABLE course_project (
                id VARCHAR PRIMARY KEY,
                name VARCHAR,
                product_knowledge_id VARCHAR,
                competitors_knowledge_id VARCHAR,
                instructions_knowledge_id VARCHAR,
                pedagogy_version VARCHAR,
                language VARCHAR,
                target_audience VARCHAR,
                created_at DATETIME,
                output_knowledge_id VARCHAR
            )
            """
        )
        await conn.exec_driver_sql(
            "INSERT INTO course_project (id, name, product_knowledge_id, instructions_knowledge_id) "
            "VALUES ('proj-1', 'Auto', 'kb-auto-product', 'kb-auto-instructions')"
        )
    await legacy_engine.dispose()

    db_module.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    db_module.AsyncSessionLocal = async_sessionmaker(db_module.engine, expire_on_commit=False)

    await init_db()

    async with db_module.engine.begin() as conn:
        row = (await conn.exec_driver_sql("SELECT product_knowledge_ids FROM course_project WHERE id = 'proj-1'")).fetchone()
    assert json.loads(row[0]) == ["kb-auto-product"]
