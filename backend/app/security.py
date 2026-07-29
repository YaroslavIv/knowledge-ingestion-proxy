import httpx
from fastapi import Header, HTTPException, status

from app.config import settings


async def require_api_key(authorization: str | None = Header(default=None)) -> None:
    """Gate this proxy's own API behind a shared bearer token — Open WebUI's
    own convention (`Authorization: Bearer <key>`), so the same tooling/curl
    scripts work against either just by swapping the base URL.

    A no-op when PROXY_API_KEY isn't configured (default), so existing
    deployments and the test suite are unaffected unless it's explicitly set.
    """
    if not settings.api_key:
        return
    if authorization != f"Bearer {settings.api_key}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid API key")


async def require_owui_bearer(authorization: str | None = Header(default=None)) -> None:
    """Require the caller's Authorization header to be a real, currently
    valid Open WebUI credential — checked live against this instance's own
    GET /api/v1/auths/ ("who am I"), which accepts both a session JWT and an
    `sk-...` API key (see Open WebUI's get_current_user). This ties access to
    this proxy to having an actual, still-enabled Open WebUI account, instead
    of a separate secret that lives only in this proxy's own .env.

    A no-op when PROXY_REQUIRE_OWUI_AUTH isn't enabled (default).
    """
    if not settings.require_owui_auth:
        return
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    async with httpx.AsyncClient(base_url=settings.owui_base_url, timeout=10) as client:
        try:
            resp = await client.get("/api/v1/auths/", headers={"Authorization": authorization})
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Could not reach Open WebUI to verify token: {e}",
            ) from e

    if resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired Open WebUI token")
