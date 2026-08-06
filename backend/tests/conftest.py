import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings

settings.owui_base_url = "http://fake-owui.test"
settings.owui_api_key = "testkey"
# Pinned regardless of a real .env on the machine running these tests — the
# proxy's own API-key gate must default to open here, same as it did before
# that setting existed. Tests exercising the gate itself override this
# per-test via monkeypatch (see test_security.py).
settings.api_key = ""
# Same reasoning — a machine running these tests may have a real backend/.env
# with PROXY_REQUIRE_OWUI_AUTH=true (needed for that machine's actual
# deployment), which would otherwise make every route in this suite require
# a live, respx-mocked Open WebUI token it doesn't expect. Tests exercising
# this gate itself override it per-test via monkeypatch (see test_security.py,
# test_login.py).
settings.require_owui_auth = False


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(settings, "originals_dir", str(tmp_path / "originals"))
    monkeypatch.setattr(settings, "course_outputs_dir", str(tmp_path / "course_outputs"))
    monkeypatch.setattr(settings, "backups_dir", str(tmp_path / "backups"))

    # db.py binds engine/session at import time using settings.db_path, so
    # re-create them here against the per-test tmp path.
    import app.db as db_module
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    db_module.engine = create_async_engine(f"sqlite+aiosqlite:///{settings.db_path}")
    db_module.AsyncSessionLocal = async_sessionmaker(db_module.engine, expire_on_commit=False)

    from app.main import app

    await db_module.init_db()

    # Every route now resolves its OwuiClient from the active saved
    # connection (see app/deps.py) rather than static settings — seed one so
    # existing tests keep talking to the same fake-owui.test mock server.
    from app.models import OwuiConnection

    async with db_module.AsyncSessionLocal() as session:
        session.add(
            OwuiConnection(
                label="test",
                base_url=settings.owui_base_url,
                email="test@example.com",
                token=settings.owui_api_key,
                is_active=True,
            )
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
