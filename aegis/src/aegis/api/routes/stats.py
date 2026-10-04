"""GET /api/stats · GET /api/perf · GET /api/stats/posture · GET|POST|DELETE /api/stats/warmup ·
GET /api/selftest · GET /api/selftest/report · POST /api/selftest/run (A-53).

on_startup(rt): SSE `stats` ticker (every 2 s), demo warm-up (synthetic history backfill / top-up),
dry-run primer (real per-control latencies), primer re-run on `policy.applied`.
All background work is skipped when AEGIS_TEST_MODE=1. Owner: audit-metrics.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from aegis.audit.log import open_db
from aegis.metrics import stats as st
from aegis.metrics import warmup as wu
from aegis.metrics.perf import build_perf_response, reports_dir
from aegis.metrics.timing import WINDOWS
from aegis.metrics.web import (
    api_error,
    demo_mode,
    forbidden,
    has_role,
    parse_bool,
    rt_of,
    test_mode,
    viewer_of,
    warmup_mode,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["stats"])

TICK_S = 2.0
PRIMER_DELAY_S = 3.0
_tasks: dict[int, list[asyncio.Task[Any]]] = {}


@router.get("/api/stats")
async def get_stats(request: Request, window: str = "24h", synthetic: str | None = None) -> Any:
    if window not in WINDOWS:
        return api_error(
            400, "invalid_request", f"window must be one of {', '.join(WINDOWS)} (got {window!r})"
        )
    rt = rt_of(request)
    if rt is None:
        return api_error(503, "unavailable", "runtime not started")
    include = parse_bool(synthetic, demo_mode(rt))
    try:
        return await st.build_stats(rt, window, include)
    except Exception as exc:
        log.exception("stats failed window=%s", window)
        return api_error(500, "internal_error", f"stats failed: {exc}")


@router.get("/api/perf")
async def get_perf(request: Request) -> Any:
    rt = rt_of(request)
    return build_perf_response(rt)


@router.get("/api/stats/posture")
async def get_posture(request: Request) -> Any:
    rt = rt_of(request)
    if rt is None:
        return api_error(503, "unavailable", "runtime not started")
    return await st.posture(rt, wu.PRIMER.public() if wu.PRIMER.state == "done" else None)


@router.get("/api/stats/warmup")
async def get_warmup(request: Request) -> Any:
    rt = rt_of(request)
    if rt is None:
        return api_error(503, "unavailable", "runtime not started")
    out = await wu.status(rt, wu.PRIMER.public())
    out["mode"] = warmup_mode(rt)
    return out


@router.post("/api/stats/warmup")
async def post_warmup(request: Request) -> Any:
    viewer = await viewer_of(request)
    if not has_role(viewer, "admin"):
        return forbidden(viewer, "admin", "Demo warm-up")
    rt = rt_of(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body if isinstance(body, dict) else {}
    try:
        days = float(body.get("days", 7))
        per_day = int(body.get("per_day", 900))
    except (TypeError, ValueError):
        return api_error(400, "invalid_request", "days / per_day must be numbers")
    if not (0 < days <= 31 and 0 < per_day <= 20000):
        return api_error(400, "invalid_request", "days must be in (0, 31], per_day in (0, 20000]")
    n = await wu.backfill(rt, days=days, per_day=per_day, clear=bool(body.get("clear", False)))
    audit = getattr(rt, "audit", None)
    if n and hasattr(audit, "system"):
        with contextlib.suppress(Exception):
            await audit.system(
                "demo.backfill",
                f"demo warm-up: {n} synthetic history rows (manual)",
                actor=viewer,
                rows=n,
                window_days=days,
                by=viewer.member_id,
                note="synthetic history for charts; flagged synthetic=1; not part of the decision chain",
            )
    out = await wu.status(rt, wu.PRIMER.public())
    out["inserted"] = n
    return out


@router.delete("/api/stats/warmup")
async def delete_warmup(request: Request) -> Any:
    viewer = await viewer_of(request)
    if not has_role(viewer, "admin"):
        return forbidden(viewer, "admin", "Demo warm-up")
    rt = rt_of(request)

    def _clear() -> int:
        conn = open_db(rt, Path(getattr(getattr(rt, "settings", None), "data_dir", None) or "data"))
        try:
            return wu.clear_synthetic(conn)
        finally:
            conn.close()

    n = await asyncio.to_thread(_clear)
    audit = getattr(rt, "audit", None)
    if hasattr(audit, "system"):
        with contextlib.suppress(Exception):
            await audit.system(
                "demo.clear",
                f"demo warm-up cleared: {n} synthetic rows removed",
                actor=viewer,
                rows=n,
                by=viewer.member_id,
            )
    out = await wu.status(rt, wu.PRIMER.public())
    out["removed"] = n
    return out


# ------------------------------------------------------------------ self-test reports (A-53)
SELFTEST_CMD = [
    "-m",
    "pytest",
    "tests/e2e",
    "tests/test_coverage.py",
    "-m",
    "not semantic and not slow and not live",
    "-q",
]
_selftest: dict[str, Any] = {"running": False, "task": None}
_selftest_lock = asyncio.Lock()


def _repo_root(rt: Any) -> Path:
    root = getattr(getattr(rt, "settings", None), "root", None)
    return Path(root) if root else Path(__file__).resolve().parents[4]


@router.get("/api/selftest")
async def get_selftest(request: Request) -> Any:
    rt = rt_of(request)
    path = reports_dir(rt) / "results.json"

    def _read() -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        data = await asyncio.to_thread(_read)
    except FileNotFoundError:
        return api_error(
            404,
            "not_found",
            f"no self-test report yet ({path.name}); run POST /api/selftest/run",
            running=bool(_selftest["running"]),
        )
    except (OSError, ValueError) as exc:
        return api_error(500, "internal_error", f"self-test report unreadable: {exc}")
    if not isinstance(data, dict):
        data = {"data": data}
    data["running"] = bool(_selftest["running"])
    return data


@router.get("/api/selftest/report")
async def get_selftest_report(request: Request) -> Any:
    path = reports_dir(rt_of(request)) / "selftest.html"
    if not path.is_file():
        return api_error(404, "not_found", "no self-test HTML report yet")
    return FileResponse(path, media_type="text/html")


def _summarize(rt: Any, rc: int, tail: str) -> str:
    with contextlib.suppress(Exception):
        data = json.loads((reports_dir(rt) / "results.json").read_text(encoding="utf-8"))
        summ = data.get("summary") if isinstance(data.get("summary"), dict) else data
        passed, total = summ.get("passed"), summ.get("total")
        if isinstance(passed, int) and isinstance(total, int) and total:
            return f"self-test finished: {passed}/{total} pass"
    m_pass = re.search(r"(\d+) passed", tail)
    m_fail = re.search(r"(\d+) failed", tail)
    if m_pass or m_fail:
        p_ = int(m_pass.group(1)) if m_pass else 0
        f_ = int(m_fail.group(1)) if m_fail else 0
        return f"self-test finished: {p_}/{p_ + f_} pass"
    return f"self-test finished (exit {rc})"


async def _run_selftest(rt: Any) -> None:
    rc, tail = -1, ""
    proc: Any = None
    try:
        env = {**os.environ, "AEGIS_REPORTS_DIR": str(reports_dir(rt))}
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            *SELFTEST_CMD,
            cwd=str(_repo_root(rt)),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        rc = proc.returncode or 0
        tail = out.decode("utf-8", "replace")[-2000:] if out else ""
    except asyncio.CancelledError:
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        raise
    except Exception as exc:
        log.exception("self-test run failed")
        tail = str(exc)
    finally:
        _selftest["running"] = False
    msg = _summarize(rt, rc, tail)
    bus = getattr(rt, "bus", None)
    if bus is not None:
        with contextlib.suppress(Exception):
            bus.publish(
                "system",
                {
                    "level": "info" if rc == 0 else "warning",
                    "message": msg,
                    "component": "selftest",
                },
            )
    log.info("%s (exit %s)", msg, rc)


@router.post("/api/selftest/run")
async def run_selftest(request: Request) -> Any:
    viewer = await viewer_of(request)
    if not has_role(viewer, "admin"):
        return forbidden(viewer, "admin", "Self-test run")
    rt = rt_of(request)
    async with _selftest_lock:  # single-flight
        if _selftest["running"]:
            return JSONResponse(status_code=202, content={"status": "running"})
        _selftest["running"] = True
        _selftest["task"] = asyncio.get_running_loop().create_task(
            _run_selftest(rt), name="aegis-selftest"
        )
    return JSONResponse(status_code=202, content={"status": "started"})


# ------------------------------------------------------------------ background tasks
async def _ticker(rt: Any) -> None:
    state = st.TickState()
    bus = getattr(rt, "bus", None)
    if bus is None:
        return
    include = demo_mode(rt)
    while True:
        try:
            await state.refresh(rt, include)
            bus.publish("stats", st.build_stats_tick(rt, state))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.debug("stats tick failed", exc_info=True)
        await asyncio.sleep(TICK_S)


async def _warmup_then_prime(rt: Any) -> None:
    mode = warmup_mode(rt)
    if mode == "off":
        wu.PRIMER.state = "skipped"
        return
    if demo_mode(rt):
        try:
            await wu.auto_warmup(rt, mode)
        except Exception:
            log.exception("demo warm-up failed")
    await asyncio.sleep(PRIMER_DELAY_S)
    try:
        await wu.prime(rt)
    except Exception:
        log.exception("primer failed")


async def _reprime_on_policy(rt: Any) -> None:
    bus = getattr(rt, "bus", None)
    if bus is None or warmup_mode(rt) == "off":
        return
    pending: asyncio.Task[Any] | None = None

    async def _later() -> None:
        await asyncio.sleep(2.0)
        with contextlib.suppress(Exception):
            await wu.prime(rt, passes=1)

    async for _msg in bus.subscribe({"policy.applied"}):
        if pending is None or pending.done():
            pending = asyncio.get_running_loop().create_task(_later())


async def on_startup(rt: Any) -> None:
    if test_mode(rt):
        return
    loop = asyncio.get_running_loop()
    _tasks[id(rt)] = [
        loop.create_task(_ticker(rt), name="aegis-stats-ticker"),
        loop.create_task(_warmup_then_prime(rt), name="aegis-warmup"),
        loop.create_task(_reprime_on_policy(rt), name="aegis-reprime"),
    ]


async def on_shutdown(rt: Any) -> None:
    task = _selftest.get("task")
    if task is not None and not task.done():
        task.cancel()
    for t in _tasks.pop(id(rt), []):
        t.cancel()
        with contextlib.suppress(BaseException):
            await t
