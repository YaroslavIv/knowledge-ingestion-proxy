from fastapi import APIRouter, HTTPException, status

from app.config import settings
from app.connections import sign_in
from app.owui_client import OwuiError
from app.schemas import LoginRequest, LoginResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    """This proxy's own front door: sign in directly against this
    deployment's configured Open WebUI instance (PROXY_OWUI_BASE_URL) and
    hand back the resulting personal token. Deliberately not gated by
    require_owui_bearer (see main.py) — a caller with no token yet is
    exactly who needs to reach this endpoint. The returned token is a real
    Open WebUI session JWT, so it's what every subsequent request must send
    as `Authorization: Bearer <token>`, and it carries that person's own
    Open WebUI identity, not a shared service account.
    """
    try:
        token, email = await sign_in(settings.owui_base_url, body.email, body.password)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=e.detail) from e
    return LoginResponse(token=token, email=email)
