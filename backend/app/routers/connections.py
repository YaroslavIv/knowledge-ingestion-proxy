from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.connections import activate_connection, get_active_connection, sign_in
from app.db import get_db
from app.models import OwuiConnection
from app.owui_client import OwuiError
from app.schemas import ConnectionSummary, ConnectRequest

router = APIRouter(prefix="/api/connections", tags=["connections"])


def _to_summary(row: OwuiConnection) -> ConnectionSummary:
    return ConnectionSummary(
        id=row.id, label=row.label, base_url=row.base_url, email=row.email, is_active=row.is_active
    )


@router.get("", response_model=list[ConnectionSummary])
async def list_connections(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(OwuiConnection).order_by(OwuiConnection.created_at.desc()))).scalars().all()
    return [_to_summary(row) for row in rows]


@router.get("/active", response_model=ConnectionSummary | None)
async def get_active(db: AsyncSession = Depends(get_db)):
    connection = await get_active_connection(db)
    return _to_summary(connection) if connection else None


@router.post("", response_model=ConnectionSummary)
async def connect(body: ConnectRequest, db: AsyncSession = Depends(get_db)):
    try:
        token, resolved_email = await sign_in(body.base_url, body.email, body.password)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.detail) from e

    await db.execute(update(OwuiConnection).values(is_active=False))

    row = OwuiConnection(
        label=body.label.strip() or body.base_url,
        base_url=body.base_url.rstrip("/"),
        email=resolved_email,
        token=token,
        is_active=True,
    )
    db.add(row)
    await db.commit()
    return _to_summary(row)


@router.post("/{connection_id}/activate", response_model=ConnectionSummary)
async def activate(connection_id: str, db: AsyncSession = Depends(get_db)):
    target = await activate_connection(db, connection_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    await db.commit()
    return _to_summary(target)


@router.delete("/{connection_id}", response_model=bool)
async def delete_connection(connection_id: str, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(OwuiConnection).where(OwuiConnection.id == connection_id))
    await db.commit()
    return True
