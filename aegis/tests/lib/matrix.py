"""Per-control / per-suite aggregation of recorded outcomes (plan 18 §2.8).

Every e2e result (data-driven case, `@pytest.mark.aegis` functional test, inline policy/feed test)
becomes an `Entry`. `build_rows()` joins entries with the catalog and the live `/api/controls`
view and assigns a STATUS (first match wins):
DISABLED · NOT_IMPLEMENTED · UNTESTED · FAIL · PARTIAL · SKIPPED · PASS.
"""

from __future__ import annotations

import statistics
import threading
from dataclasses import asdict, dataclass, field
from typing import Any

from tests.lib.catalog import BY_ID, CATALOG, STRETCH, SUITES


@dataclass
class Entry:
    id: str
    control: str | None
    suite: str
    polarity: str  # attack | benign | error
    expect: str
    column: str  # attack | benign | redact | error | other
    outcome: str  # pass | pass_other | fail | skip | xfail | disabled | not_implemented
    got: str | None = None
    got_control: str | None = None
    reason: str = ""
    tier: str = "core"
    via: str = "pytest"
    surface: str | None = None
    latency_ms: float | None = None
    decision_id: str | None = None
    tags: list[str] = field(default_factory=list)
    source: str = ""
    preview: str = ""
    nodeid: str = ""

    def as_case(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("column", None)
        d.pop("nodeid", None)
        return d


class Recorder:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.entries: list[Entry] = []
        self.gateway: dict[str, Any] = {}
        self.controls_live: dict[str, dict[str, Any]] = {}
        self.perf: dict[str, Any] = {
            "reload_ms": None,
            "feed_activation_ms": None,
            "guard_p50_ms": None,
            "guard_p95_ms": None,
        }
        self.obfuscation: dict[str, Any] | None = None
        self.mode = "hermetic"
        self.stack_error: str | None = None
        self.static_coverage: dict[str, dict[str, int]] = {}

    def add(self, entry: Entry) -> None:
        with self.lock:
            self.entries.append(entry)

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]


RESULTS = Recorder()


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 2)
    vs = sorted(values)
    k = max(0, min(len(vs) - 1, round(q * (len(vs) - 1))))
    return round(vs[k], 2)


def _counts(entries: list[Entry], column: str) -> dict[str, int]:
    es = [e for e in entries if e.column == column and e.outcome not in ("skip",)]
    return {"passed": sum(e.outcome in ("pass", "pass_other") for e in es), "total": len(es)}


def control_status(
    cid: str,
    entries: list[Entry],
    live: dict[str, Any] | None,
    static: dict[str, int] | None = None,
    registry_known: bool = False,
) -> str:
    if live is not None:
        if live.get("enabled") is False or live.get("mode") == "off":
            return "DISABLED"
        if live.get("implemented") is False:
            return "NOT_IMPLEMENTED"
    elif live is None and registry_known and cid in BY_ID:
        return "NOT_IMPLEMENTED"
    blocks = sum(e.column in ("attack", "redact") for e in entries)
    allows = sum(e.column == "benign" for e in entries)
    if static:
        blocks += static.get("block", 0)
        allows += static.get("allow", 0)
    if blocks == 0 or allows == 0:
        return "UNTESTED"
    if any(e.outcome == "fail" and e.tier == "core" for e in entries):
        return "FAIL"
    if any(e.outcome in ("fail", "xfail") for e in entries):
        return "PARTIAL"
    ran = [e for e in entries if e.outcome not in ("skip",)]
    if not ran:
        return "SKIPPED"
    if all(e.outcome in ("disabled", "not_implemented") for e in ran):
        return "NOT_IMPLEMENTED" if any(e.outcome == "not_implemented" for e in ran) else "DISABLED"
    return "PASS"


def build_rows(rec: Recorder | None = None) -> list[dict[str, Any]]:
    rec = rec or RESULTS
    ids = [c.id for c in CATALOG]
    for cid in rec.controls_live:
        if cid not in ids and not cid.startswith("A2A"):
            ids.append(cid)
    rows = []
    for cid in ids:
        es = [e for e in rec.entries if e.control == cid]
        live = rec.controls_live.get(cid) if rec.controls_live else None
        cat = BY_ID.get(cid)
        lat = [e.latency_ms for e in es if isinstance(e.latency_ms, (int, float))]
        rows.append(
            {
                "control_id": cid,
                "family": cid.split("-")[0],
                "name": cat.name if cat else (live or {}).get("name", cid),
                "status": control_status(
                    cid,
                    es,
                    live,
                    rec.static_coverage.get(cid),
                    registry_known=bool(rec.controls_live),
                ),
                "enabled": (live or {}).get("enabled") if live else None,
                "mode": (live or {}).get("mode") if live else None,
                "implemented": (live or {}).get("implemented") if live else None,
                "attack": _counts(es, "attack"),
                "benign": _counts(es, "benign"),
                "redact": _counts(es, "redact"),
                "error": _counts(es, "error"),
                "other_control": sum(e.outcome == "pass_other" for e in es),
                "xfail": sum(e.outcome == "xfail" for e in es),
                "p50_ms": _pct(lat, 0.5),
                "p95_ms": _pct(lat, 0.95),
                "owasp": list((live or {}).get("owasp") or []),
                "stretch": cid in STRETCH,
            }
        )
    return rows


def build_suites(rec: Recorder | None = None) -> list[dict[str, Any]]:
    rec = rec or RESULTS
    out = []
    for sid, title in SUITES.items():
        es = [e for e in rec.entries if e.suite == sid and e.outcome != "skip"]
        if not es:
            continue
        passed = sum(e.outcome in ("pass", "pass_other", "xfail") for e in es)
        status = (
            "PASS"
            if all(e.outcome != "fail" for e in es)
            else (
                "FAIL" if any(e.outcome == "fail" and e.tier == "core" for e in es) else "PARTIAL"
            )
        )
        out.append(
            {"id": sid, "title": title, "passed": passed, "total": len(es), "status": status}
        )
    return out


def totals(rec: Recorder | None = None, rows: list[dict[str, Any]] | None = None) -> dict[str, int]:
    rec = rec or RESULTS
    rows = rows if rows is not None else build_rows(rec)
    es = rec.entries
    return {
        "cases": len(es),
        "passed": sum(e.outcome == "pass" for e in es),
        "pass_other": sum(e.outcome == "pass_other" for e in es),
        "failed": sum(e.outcome == "fail" for e in es),
        "skipped": sum(e.outcome == "skip" for e in es),
        "xfailed": sum(e.outcome in ("xfail", "not_implemented") for e in es),
        "disabled": sum(e.outcome == "disabled" for e in es),
        "untested_controls": sum(r["status"] == "UNTESTED" for r in rows),
        "disabled_controls": sum(r["status"] == "DISABLED" for r in rows),
    }


def guard_latency(rec: Recorder | None = None) -> tuple[float | None, float | None]:
    rec = rec or RESULTS
    lat = [
        e.latency_ms
        for e in rec.entries
        if e.via == "guard" and isinstance(e.latency_ms, (int, float))
    ]
    if not lat:
        return None, None
    return round(statistics.median(lat), 2), _pct(lat, 0.95)


__all__ = [
    "RESULTS",
    "Entry",
    "Recorder",
    "build_rows",
    "build_suites",
    "control_status",
    "guard_latency",
    "totals",
]
