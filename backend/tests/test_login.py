import respx
from httpx import Response

from app.config import settings


@respx.mock
async def test_login_succeeds_and_returns_a_token(client, monkeypatch):
    monkeypatch.setattr(settings, "require_owui_auth", True)
    respx.post("http://fake-owui.test/api/v1/auths/signin").mock(
        return_value=Response(200, json={"token": "jwt-personal", "email": "someone@example.com"})
    )

    resp = await client.post("/api/auth/login", json={"email": "someone@example.com", "password": "hunter2"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"] == "jwt-personal"
    assert body["email"] == "someone@example.com"


@respx.mock
async def test_login_rejects_bad_credentials(client, monkeypatch):
    monkeypatch.setattr(settings, "require_owui_auth", True)
    respx.post("http://fake-owui.test/api/v1/auths/signin").mock(
        return_value=Response(400, json={"detail": "Invalid credentials"})
    )

    resp = await client.post("/api/auth/login", json={"email": "someone@example.com", "password": "wrong"})
    assert resp.status_code == 401


async def test_login_does_not_require_a_bearer_token_itself(client, monkeypatch):
    # Sanity check on the route wiring: /api/auth/login must not be behind
    # require_owui_bearer, or nobody could ever log in in the first place.
    monkeypatch.setattr(settings, "require_owui_auth", True)
    with respx.mock:
        respx.post("http://fake-owui.test/api/v1/auths/signin").mock(
            return_value=Response(200, json={"token": "jwt-x", "email": "x@example.com"})
        )
        resp = await client.post("/api/auth/login", json={"email": "x@example.com", "password": "p"})
    assert resp.status_code == 200
