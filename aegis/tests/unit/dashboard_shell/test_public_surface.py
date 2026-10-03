"""UIS-V02: the dashboard-shell public surface that sibling dashboards import still exists.

Static checks only (no node needed): names in CONTRACTS §5.4 / plan 15 §4.2 must stay exported.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "web" / "src"


def _read(rel: str) -> str:
    return (WEB / rel).read_text(encoding="utf-8")


def test_api_client_surface() -> None:
    src = _read("api/client.ts")
    for name in ("api", "ApiResult", "ApiRequestError", "isApiRequestError"):
        assert re.search(rf"export (const|function|class|interface|type) {name}\b", src), name
    for method in ("get", "post", "patch", "download", "url"):
        assert re.search(rf"\b{method}\b", src), method


def test_hooks_surface() -> None:
    src = _read("api/hooks.ts")
    for name in (
        "useApi",
        "useEvents",
        "useLiveDecisions",
        "useViewAs",
        "usePendingApprovals",
        "usePendingApprovalsDetail",
        "useSseStatus",
        "useStatsTick",
        "useVersions",
        "useWhoAmI",
        "useMembers",
    ):
        assert re.search(rf"export function {name}\b", src), name


def test_sse_runtime_list() -> None:
    src = _read("api/sse.ts")
    assert "export const SSE_EVENTS" in src
    assert "export const eventHub" in src


@pytest.mark.parametrize(
    "name",
    "PageHeader Panel KpiTile ActionBadge RoleBadge DestBadge IdentityChip StatusDot MockBadge EmptyState "
    "JsonView TimeAgo RoleGate AnimatedNumber UsageBar LiveDot Kbd ErrorBoundary Segmented".split(),
)
def test_shell_barrel(name: str) -> None:
    assert re.search(rf"\b{name}\b", _read("components/shell/index.ts")), name


@pytest.mark.parametrize("name", ["AreaTimeseries", "BarList", "Gauge", "Sparkline"])
def test_charts_barrel(name: str) -> None:
    assert name in _read("components/charts/index.ts")


@pytest.mark.parametrize(
    "f",
    "button card badge table tabs dialog sheet dropdown-menu select input textarea label switch slider tooltip "
    "popover command separator scroll-area skeleton avatar progress alert toggle toggle-group sonner".split(),
)
def test_ui_primitives(f: str) -> None:
    assert (WEB / "components" / "ui" / f"{f}.tsx").is_file(), f


def test_format_helpers() -> None:
    src = _read("lib/format.ts")
    found = re.findall(r"export function (fmtUsd|fmtNum|fmtPct|fmtMs|fmtTime|fmtAgo)\b", src)
    assert len(set(found)) == 6


@pytest.mark.parametrize(
    ("rel", "path"),
    [("pages/overview.page.tsx", "/"), ("pages/system/perf.page.tsx", "/system/perf"), ("pages/system/health.page.tsx", "/system/health")],
)
def test_shell_pages_have_meta(rel: str, path: str) -> None:
    src = _read(rel)
    assert "export const meta: PageMeta" in src
    assert f"path: '{path}'" in src
    assert "export default function" in src


def test_no_cdn_urls_in_source() -> None:
    cdn = re.compile(r"fonts\.googleapis|gstatic|jsdelivr|unpkg|cdnjs")
    owned = ["main.tsx", "App.tsx", "router.tsx", "styles", "lib", "components/shell", "components/charts", "components/ui", "pages/system"]
    for rel in owned:
        p = WEB / rel
        files = [p] if p.is_file() else list(p.rglob("*.ts*")) + list(p.rglob("*.css"))
        for f in files:
            assert not cdn.search(f.read_text(encoding="utf-8")), f
