from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.connections import get_active_connection
from app.db import get_db
from app.owui_client import OwuiClient


async def get_owui_client(db: AsyncSession = Depends(get_db)) -> OwuiClient:
    connection = await get_active_connection(db)
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Open WebUI connection configured — connect one first.",
        )
    return OwuiClient(base_url=connection.base_url, api_key=connection.token)
