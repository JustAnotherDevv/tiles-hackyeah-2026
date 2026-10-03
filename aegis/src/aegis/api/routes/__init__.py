"""Auto-discovered FastAPI routers (CONTRACTS section 2.1).

Every module here exposes `router: fastapi.APIRouter` with absolute paths, optional
`ORDER: int = 100`, `async def on_startup(rt)` and `async def on_shutdown(rt)`. Modules
whose name starts with `_` are skipped. No import-time side effects.

Owner: scaffold (empty package); each route file per CONTRACTS section 1.3 (docs/CONTRACTS.md section 1.2). Scaffold stub - safe to replace.
"""
