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
