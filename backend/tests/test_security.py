import respx
from httpx import Response

from app.config import settings


async def test_api_is_open_when_no_api_key_is_configured(client):
    # settings.api_key defaults to "" — no Authorization header at all
    resp = await client.get("/api/connections")
    assert resp.status_code == 200


async def test_requires_bearer_token_once_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret123")

    resp = await client.get("/api/connections")
    assert resp.status_code == 401


async def test_rejects_a_wrong_token(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret123")

    resp = await client.get("/api/connections", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


async def test_accepts_the_correct_bearer_token(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret123")

    resp = await client.get("/api/connections", headers={"Authorization": "Bearer secret123"})
    assert resp.status_code == 200


async def test_health_endpoint_stays_open_even_when_a_key_is_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret123")

    resp = await client.get("/api/health")
    assert resp.status_code == 200


async def test_owui_auth_is_off_by_default(client):
    # settings.require_owui_auth defaults to False — no Authorization header,
    # no Open WebUI reachable at all, still succeeds.
    resp = await client.get("/api/connections")
    assert resp.status_code == 200


async def test_requires_a_bearer_token_once_owui_auth_is_enabled(client, monkeypatch):
    monkeypatch.setattr(settings, "require_owui_auth", True)

    resp = await client.get("/api/connections")
    assert resp.status_code == 401


@respx.mock
async def test_rejects_a_token_open_webui_does_not_recognize(client, monkeypatch):
    monkeypatch.setattr(settings, "require_owui_auth", True)
    respx.get("http://fake-owui.test/api/v1/auths/").mock(return_value=Response(401))

    resp = await client.get("/api/connections", headers={"Authorization": "Bearer sk-notreal"})
    assert resp.status_code == 401


@respx.mock
async def test_accepts_a_token_open_webui_confirms_is_valid(client, monkeypatch):
    monkeypatch.setattr(settings, "require_owui_auth", True)
    respx.get("http://fake-owui.test/api/v1/auths/").mock(
        return_value=Response(200, json={"id": "u1", "name": "Test User", "email": "test@example.com", "role": "user"})
    )

    resp = await client.get("/api/connections", headers={"Authorization": "Bearer sk-real"})
    assert resp.status_code == 200


async def test_health_endpoint_stays_open_even_when_owui_auth_is_enabled(client, monkeypatch):
    monkeypatch.setattr(settings, "require_owui_auth", True)

    resp = await client.get("/api/health")
    assert resp.status_code == 200
