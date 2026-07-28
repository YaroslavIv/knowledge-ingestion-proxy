import respx
from httpx import Response


@respx.mock
async def test_connect_signs_in_and_becomes_the_active_connection(client):
    respx.post("http://second-owui.test/api/v1/auths/signin").mock(
        return_value=Response(200, json={"token": "jwt-abc", "token_type": "Bearer", "email": "second@example.com"})
    )

    resp = await client.post(
        "/api/connections",
        json={
            "label": "Docker instance",
            "base_url": "http://second-owui.test",
            "email": "second@example.com",
            "password": "hunter2",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["base_url"] == "http://second-owui.test"
    assert body["email"] == "second@example.com"
    assert body["is_active"] is True
    assert "token" not in body  # never exposed to the frontend

    list_resp = await client.get("/api/connections")
    by_url = {c["base_url"]: c for c in list_resp.json()}
    assert by_url["http://second-owui.test"]["is_active"] is True
    assert by_url["http://fake-owui.test"]["is_active"] is False  # the seeded test connection got deactivated


@respx.mock
async def test_connect_surfaces_bad_credentials(client):
    respx.post("http://second-owui.test/api/v1/auths/signin").mock(
        return_value=Response(400, json={"detail": "Invalid credentials"})
    )

    resp = await client.post(
        "/api/connections",
        json={"label": "", "base_url": "http://second-owui.test", "email": "x@example.com", "password": "wrong"},
    )
    assert resp.status_code == 400
    assert "Invalid credentials" in resp.json()["detail"]

    # the bad attempt must not have been saved or touched the active connection
    active_resp = await client.get("/api/connections/active")
    assert active_resp.json()["base_url"] == "http://fake-owui.test"


@respx.mock
async def test_activate_switches_which_connection_is_active(client):
    respx.post("http://second-owui.test/api/v1/auths/signin").mock(
        return_value=Response(200, json={"token": "jwt-abc", "email": "second@example.com"})
    )
    await client.post(
        "/api/connections",
        json={"label": "Second", "base_url": "http://second-owui.test", "email": "second@example.com", "password": "p"},
    )

    connections = (await client.get("/api/connections")).json()
    first_id = next(c["id"] for c in connections if c["base_url"] == "http://fake-owui.test")

    activate_resp = await client.post(f"/api/connections/{first_id}/activate")
    assert activate_resp.status_code == 200
    assert activate_resp.json()["is_active"] is True

    active_resp = await client.get("/api/connections/active")
    assert active_resp.json()["id"] == first_id


async def test_delete_connection(client):
    connections = (await client.get("/api/connections")).json()
    conn_id = connections[0]["id"]

    delete_resp = await client.delete(f"/api/connections/{conn_id}")
    assert delete_resp.status_code == 200

    remaining = (await client.get("/api/connections")).json()
    assert all(c["id"] != conn_id for c in remaining)


async def test_endpoints_require_an_active_connection(client):
    connections = (await client.get("/api/connections")).json()
    for c in connections:
        await client.delete(f"/api/connections/{c['id']}")

    resp = await client.get("/api/kb")
    assert resp.status_code == 400
    assert "connect one first" in resp.json()["detail"]
