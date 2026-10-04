"""FastAPI dependencies (public surface, CONTRACTS section 3.3).

```python
from fastapi import Depends
from aegis.core.deps import get_rt, viewer, require_role

@router.post("/api/things")
async def create(rt=Depends(get_rt), who=Depends(require_role("admin"))): ...
```
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request

from aegis.core.errors import AegisHTTPError
from aegis.core.protocols import RuntimeProto
from aegis.core.types import ROLE_RANK, Identity, Role


async def get_rt(request: Request) -> RuntimeProto:
    """The running `Runtime` (app.state.rt, else the module-global one)."""
    rt = getattr(request.app.state, "rt", None)
    if rt is not None:
        return rt
    from aegis.core.runtime import get_runtime

    try:
        return get_runtime()
    except RuntimeError as exc:
        raise AegisHTTPError(503, "unavailable", "gateway runtime not started") from exc


#: Methods that never change state (reads stay open to anonymous viewers and agents).
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
#: Dashboard POSTs that only compute a preview / validation and change nothing.
READ_ONLY_POSTS = frozenset({
    "/api/policy/validate",
    "/api/policy/diff",
    "/api/budgets/raise/preview",
    "/api/semantic/score",
    "/api/approvals/simulate",
})


def is_human(ident: Identity) -> bool:
    """A known org member acting as themselves (not an agent, not the anonymous viewer)."""
    return bool(ident.member_id) and not ident.agent_id and ident.role not in ("agent", "viewer")


def _non_human_forbidden(ident: Identity) -> AegisHTTPError:
    if ident.agent_id or ident.role == "agent":
        who = ident.agent_id or "agent"
        return AegisHTTPError(
            403,
            "forbidden",
            f"{who}: agents cannot act on the dashboard API - a human member must decide "
            "(agent credentials override X-Aegis-View-As)",
        )
    return AegisHTTPError(
        403,
        "forbidden",
        "anonymous viewer is read-only - send X-Aegis-View-As: <member id> to act",
    )


def _mutating(request: Request) -> bool:
    if request.method.upper() in SAFE_METHODS:
        return False
    path = request.url.path.rstrip("/") or "/"
    return path.startswith("/api/") and path not in READ_ONLY_POSTS


async def viewer(request: Request) -> Identity:
    """Dashboard viewer: `rt.org.resolve_viewer(headers, query)` (X-Aegis-View-As / ?view_as=).

    A mutating `/api/*` request from a non-human viewer (agent credentials, unknown or absent
    view-as) is refused here with 403 `forbidden` (R5/R6), before any route logic runs.
    """
    cached = getattr(request.state, "aegis_viewer", None)
    if isinstance(cached, Identity):
        ident = cached
    else:
        rt = await get_rt(request)
        ident = await rt.org.resolve_viewer(request.headers, dict(request.query_params))
        request.state.aegis_viewer = ident
    if not is_human(ident) and _mutating(request):
        raise _non_human_forbidden(ident)
    return ident


def require_role(min_role: Role) -> Callable[[Request], Awaitable[Identity]]:
    """Dependency factory: returns the viewer or raises 403 `forbidden`."""
    need = ROLE_RANK.get(min_role, 99)

    async def _dep(request: Request) -> Identity:
        ident = await viewer(request)
        have = ROLE_RANK.get(ident.role, -1)
        if (
            have < need
            and min_role == "member"
            and request.method.upper() in SAFE_METHODS
            and not is_human(ident)
        ):
            return ident  # member-level reads stay open to the anonymous viewer (pre-R6 parity)
        if have < need:
            who = ident.member_id or ident.agent_id or "anonymous"
            raise AegisHTTPError(
                403,
                "forbidden",
                f"{who} ({ident.role}) may not do this - requires {min_role}",
                required_role=min_role if min_role in ("admin", "owner") else None,
            )
        return ident

    _dep.__name__ = f"require_{min_role}"
    return _dep


def client_ip(request: Request) -> str | None:
    client: Any = request.client
    return getattr(client, "host", None)


__all__ = ["client_ip", "get_rt", "is_human", "require_role", "viewer"]
