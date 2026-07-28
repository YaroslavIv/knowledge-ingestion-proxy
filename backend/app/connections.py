import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OwuiConnection
from app.owui_client import OwuiError


async def sign_in(base_url: str, email: str, password: str) -> tuple[str, str]:
    """Authenticate directly against an Open WebUI instance's own login
    endpoint (no admin API key needed ahead of time) and return
    (token, resolved_email). Distinct from OwuiClient, which always talks to
    an already-known, already-authenticated instance.
    """
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=30) as client:
        try:
            resp = await client.post("/api/v1/auths/signin", json={"email": email, "password": password})
        except httpx.RequestError as e:
            raise OwuiError(502, f"Could not reach {base_url}: {e}") from e

        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:  # noqa: BLE001
                detail = resp.text
            raise OwuiError(resp.status_code, str(detail))

        data = resp.json()
        token = data.get("token")
        if not token:
            raise OwuiError(502, "Open WebUI did not return a session token")
        return token, data.get("email", email)


async def get_active_connection(db: AsyncSession) -> OwuiConnection | None:
    return (
        await db.execute(select(OwuiConnection).where(OwuiConnection.is_active.is_(True)))
    ).scalar_one_or_none()


async def activate_connection(db: AsyncSession, connection_id: str) -> OwuiConnection | None:
    rows = (await db.execute(select(OwuiConnection))).scalars().all()
    target = None
    for row in rows:
        if row.id == connection_id:
            row.is_active = True
            target = row
        else:
            row.is_active = False
    await db.flush()
    return target
