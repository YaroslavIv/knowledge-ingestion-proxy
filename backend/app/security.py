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
