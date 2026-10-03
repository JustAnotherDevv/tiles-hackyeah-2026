"""POST /egress - governed third-party HTTP egress (stub; filled in by META-06)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/egress")
async def egress() -> JSONResponse:
    return JSONResponse(status_code=501, content={"error": {
        "type": "not_implemented", "message": "egress proxy not implemented yet"}})


async def on_startup(rt) -> None:  # noqa: ANN001
    return None


async def on_shutdown(rt) -> None:  # noqa: ANN001
    return None
