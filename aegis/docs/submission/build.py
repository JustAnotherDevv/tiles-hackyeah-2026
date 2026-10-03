"""Submission build tool: measured numbers -> rendered docs -> deck PDF, plus limit checks.

Usage (repo root):
    uv run --frozen python docs/submission/build.py collect [--url http://127.0.0.1:8787]
    uv run --frozen python docs/submission/build.py render [--pdf] [--check] [--strict]
    uv run --frozen python docs/submission/build.py collect render --pdf --check
    uv run --frozen python docs/submission/build.py apply        # fill resolved numbers in README/docs in place
    uv run --frozen python docs/submission/build.py --check [--strict]
    uv run --frozen python docs/submission/build.py --screens --url http://127.0.0.1:8787

Rules: every number comes from reports/* (or a live API call recorded with its source and timestamp in
numbers.json). Unresolved placeholders render as a visible "[TBD: key]"; --strict fails on them.
Only the standard library (+ httpx when --url is used) and an installed Google Chrome are needed.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REPORTS = Path(os.environ.get("AEGIS_REPORTS_DIR", ROOT / "reports"))
if not REPORTS.is_absolute():
    REPORTS = ROOT / REPORTS
OUT = HERE / "out"
NUMBERS = HERE / "numbers.json"
DECK = HERE / "deck" / "deck.html"
PDF_NAME = "Aegis_HackYeah2026_GS_AIControlLayer.pdf"
SLIDES = 10

# files rendered into out/ (paste/upload from there)
RENDER_FILES = [
    HERE / "HACKTRIBE.md",
    HERE / "DECK.md",
    HERE / "VIDEO_60S.md",
    ROOT / "docs" / "demo-script.md",
]
# files where `apply` replaces resolved placeholders in place (final pass only)
APPLY_FILES = [
    ROOT / "README.md",
    ROOT / "docs" / "JUDGES.md",
    ROOT / "docs" / "demo-script.md",
    ROOT / "docs" / "architecture.md",
]
# markdown files whose relative links must resolve
LINK_FILES = [
    ROOT / "README.md",
    ROOT / "docs" / "JUDGES.md",
    ROOT / "docs" / "architecture.md",
    ROOT / "docs" / "policy-reference.md",
    ROOT / "docs" / "api.md",
    ROOT / "docs" / "demo-script.md",
    HERE / "README.md",
    HERE / "HACKTRIBE.md",
    HERE / "DECK.md",
    HERE / "VIDEO_60S.md",
]
SCREENS = {  # docs/assets/screens/<name>.png <- /ui route (viewed as the given member)
    "overview": ("/ui/", "u_katarzyna"),
    "live": ("/ui/security/live", "u_katarzyna"),
    "playground": ("/ui/security/playground", "u_katarzyna"),
    "approvals": ("/ui/governance/approvals", "u_piotr"),
    "budgets": ("/ui/governance/budgets", "u_emily"),
    "policy": ("/ui/governance/policy", "u_katarzyna"),
    "perf": ("/ui/system/perf", "u_katarzyna"),
}

PLACEHOLDER = re.compile(
    r"\{\{\s*(?:TBD:\s*)?([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+|[a-z][a-z0-9_]*)\s*\}\}"
)
TBD_LEFT = re.compile(r"\[TBD: [a-z][a-z0-9_.]*\]|\{\{\s*TBD:\s*[a-z][^}]*\}\}")


# ---------------------------------------------------------------------------------------- helpers
def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _dig(obj: Any, *paths: str) -> Any:
    """First non-None value among dotted paths."""
    for path in paths:
        cur = obj
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        if cur is not None:
            return cur
    return None


def fmt_pct(value: Any) -> str | None:
    """0.912 -> '91.2 %'; 91.2 -> '91.2 %'."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    pct = value * 100 if value <= 1 else value
    return f"{pct:.1f} %" if pct not in (0, 100) else f"{pct:.0f} %"


def fmt_ms(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return f"{value:.2f}" if value < 10 else f"{value:.1f}" if value < 100 else f"{value:.0f}"


def fmt_int(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return f"{int(value):,}"


def fmt_ratio(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return f"{value:.3f}".rstrip("0").rstrip(".") if value < 1 else "1.0"


class Numbers:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def put(self, key: str, raw: Any, text: str | None, source: str) -> None:
        if text is None:
            return
        self.items[key] = {"value": text, "raw": raw, "source": source, "collected_at": _now()}


# ---------------------------------------------------------------------------------------- collect
def collect_results(n: Numbers) -> None:
    path = REPORTS / "results.json"
    d = _load_json(path)
    if not d:
        return
    src = "reports/results.json"
    t = d.get("totals") or {}
    n.put("tests.total", t.get("cases"), fmt_int(t.get("cases")), src)
    passed = (t.get("passed") or 0) + (t.get("pass_other") or 0) if "passed" in t else None
    n.put("tests.passed", passed, fmt_int(passed), src)
    n.put("tests.failed", t.get("failed"), fmt_int(t.get("failed")), src)
    n.put("tests.skipped", t.get("skipped"), fmt_int(t.get("skipped")), src)
    n.put("tests.xfailed", t.get("xfailed"), fmt_int(t.get("xfailed")), src)
    n.put("tests.untested", t.get("untested_controls"), fmt_int(t.get("untested_controls")), src)
    ctl = d.get("controls")
    if isinstance(ctl, list):
        n.put("tests.controls", len(ctl), fmt_int(len(ctl)), src)
    dur = d.get("duration_s")
    n.put("tests.duration_s", dur, f"{dur:.0f}" if isinstance(dur, (int, float)) else None, src)
    perf = d.get("perf") or {}
    n.put("policy.reload_ms", perf.get("reload_ms"), fmt_ms(perf.get("reload_ms")), src)
    n.put(
        "feed.activation_ms",
        perf.get("feed_activation_ms"),
        fmt_ms(perf.get("feed_activation_ms")),
        src,
    )


def collect_junit(n: Numbers) -> None:
    """Fallback test totals from JUnit XML when results.json is missing."""
    if "tests.total" in n.items:
        return
    path = REPORTS / "junit.xml"
    if not path.exists():
        return
    import xml.etree.ElementTree as ET

    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = sum(int(s.get("tests", 0)) for s in suites)
    failed = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
    n.put("tests.total", total, fmt_int(total), "reports/junit.xml")
    n.put("tests.failed", failed, fmt_int(failed), "reports/junit.xml")


def collect_bench(n: Numbers) -> None:
    d = _load_json(REPORTS / "bench.json")
    if not d:
        return
    src = "reports/bench.json"
    h = d.get("headline") or {}
    for key, path, fmt in [
        ("perf.overhead_p50_ms", "det_overhead_p50_ms", fmt_ms),
        ("perf.overhead_p95_ms", "det_overhead_p95_ms", fmt_ms),
        ("perf.sem_overhead_p50_ms", "sem_overhead_p50_ms", fmt_ms),
        ("perf.sem_overhead_p95_ms", "sem_overhead_p95_ms", fmt_ms),
        ("perf.rps", "rps_det", fmt_int),
        ("perf.overhead_share_pct", "overhead_share_pct", fmt_pct),
        ("eval.detection_rate", "detection_rate_balanced", fmt_pct),
        ("eval.fpr", "fpr_balanced", fmt_pct),
        ("eval.obfuscation_coverage", "obfuscation_coverage", fmt_pct),
    ]:
        v = h.get(path)
        n.put(key, v, fmt(v), f"{src}#headline.{path}")
    if "policy.reload_ms" not in n.items:
        v = h.get("reload_p95_ms")
        n.put("policy.reload_ms", v, fmt_ms(v), f"{src}#headline.reload_p95_ms")


def collect_eval(n: Numbers) -> None:
    if "eval.detection_rate" in n.items and "eval.fpr" in n.items:
        return
    d = _load_json(REPORTS / "eval.json")
    if not d:
        return
    runs = [r for r in d.get("runs") or [] if isinstance(r, dict)]
    run = next((r for r in runs if r.get("profile") == "balanced"), runs[0] if runs else None)
    if not run:
        return
    ov = run.get("overall") or {}
    det = _dig(ov, "detection_rate", "tpr", "recall", "detection.rate")
    fpr = _dig(ov, "fpr", "false_positive_rate", "fpr.rate")
    src = f"reports/eval.json#runs[profile={run.get('profile')}]"
    n.put("eval.detection_rate", det, fmt_pct(det), src)
    n.put("eval.fpr", fpr, fmt_pct(fpr), src)


def collect_dlp(n: Numbers) -> None:
    d = _load_json(REPORTS / "dlp-metrics.json")
    if not d:
        return
    src = "reports/dlp-metrics.json"
    ov = d.get("overall") or {}
    n.put("dlp.cases", d.get("cases"), fmt_int(d.get("cases")), src)
    n.put(
        "dlp.leak_rate_validated",
        ov.get("leak_rate_validated"),
        fmt_pct(ov.get("leak_rate_validated")),
        src,
    )
    n.put("dlp.precision", ov.get("precision"), fmt_ratio(ov.get("precision")), src)
    n.put("dlp.recall", ov.get("recall"), fmt_ratio(ov.get("recall")), src)
    lat = (d.get("latency_ms") or {}).get("p95")
    n.put("dlp.latency_p95_ms", lat, fmt_ms(lat), src)


def collect_live(n: Numbers, url: str) -> None:
    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx is a project dependency
        print("httpx missing; skipping live numbers", file=sys.stderr)
        return
    headers = {"X-Aegis-View-As": "u_katarzyna"}
    try:
        with httpx.Client(base_url=url, headers=headers, timeout=10) as c:
            ver = c.get("/api/audit/verify")
            if ver.status_code == 200:
                v = ver.json()
                n.put(
                    "audit.records",
                    v.get("records"),
                    fmt_int(v.get("records")),
                    f"{url}/api/audit/verify",
                )
                n.put(
                    "audit.ok",
                    v.get("ok"),
                    "OK" if v.get("ok") else "BROKEN",
                    f"{url}/api/audit/verify",
                )
            cov = c.get("/api/coverage")
            if cov.status_code == 200:
                names = {"OWASP-LLM-2026": "llm", "OWASP-ASI-2026": "asi", "OWASP-MCP-2025": "mcp"}
                for fw in cov.json().get("frameworks") or []:
                    short = names.get(fw.get("id"))
                    items = fw.get("items") or []
                    if not short or not items:
                        continue
                    covered = sum(1 for i in items if i.get("status") == "covered")
                    n.put(
                        f"coverage.{short}",
                        [covered, len(items)],
                        f"{covered}/{len(items)}",
                        f"{url}/api/coverage",
                    )
            pol = c.get("/api/policy")
            if pol.status_code == 200:
                p = pol.json()
                n.put(
                    "policy.version", p.get("version"), str(p.get("version")), f"{url}/api/policy"
                )
            ctl = c.get("/api/controls")
            if ctl.status_code == 200:
                items = ctl.json().get("items") or []
                n.put("controls.count", len(items), fmt_int(len(items)), f"{url}/api/controls")
    except httpx.HTTPError as exc:
        print(f"live numbers unavailable ({exc.__class__.__name__}): {url}", file=sys.stderr)


def collect(url: str | None) -> dict[str, dict[str, Any]]:
    n = Numbers()
    collect_results(n)
    collect_junit(n)
    collect_bench(n)
    collect_eval(n)
    collect_dlp(n)
    if url:
        collect_live(n, url)
    doc = {
        "generated_at": _now(),
        "reports_dir": str(REPORTS.relative_to(ROOT))
        if REPORTS.is_relative_to(ROOT)
        else str(REPORTS),
        "numbers": dict(sorted(n.items.items())),
    }
    NUMBERS.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"numbers.json: {len(n.items)} measured values")
    for k, v in sorted(n.items.items()):
        print(f"  {k:28} {v['value']:>14}   {v['source']}")
    return n.items


def load_numbers() -> dict[str, dict[str, Any]]:
    d = _load_json(NUMBERS) or {}
    nums = d.get("numbers")
    return nums if isinstance(nums, dict) else {}


# ---------------------------------------------------------------------------------------- render
def substitute(
    text: str, nums: dict[str, dict[str, Any]], *, html: bool, keep_unresolved: bool = False
) -> tuple[str, list[str]]:
    missing: list[str] = []

    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key in nums:
            return str(nums[key]["value"])
        missing.append(key)
        if keep_unresolved:
            return m.group(0)
        return f'<span class="tbd">[TBD: {key}]</span>' if html else f"[TBD: {key}]"

    return PLACEHOLDER.sub(repl, text), missing


def render() -> list[str]:
    nums = load_numbers()
    OUT.mkdir(exist_ok=True)
    unresolved: set[str] = set()
    for src in RENDER_FILES:
        if not src.exists():
            continue
        text, missing = substitute(src.read_text(encoding="utf-8"), nums, html=False)
        (OUT / src.name).write_text(text, encoding="utf-8")
        unresolved.update(missing)
    text, missing = substitute(DECK.read_text(encoding="utf-8"), nums, html=True)
    (OUT / "deck.html").write_text(text, encoding="utf-8")  # same depth as deck/ -> ../../assets ok
    unresolved.update(missing)
    print(f"rendered {len(RENDER_FILES) + 1} files into {OUT.relative_to(ROOT)}/")
    if unresolved:
        print("unresolved (shown as [TBD: key]): " + ", ".join(sorted(unresolved)))
    return sorted(unresolved)


def apply_in_place() -> None:
    nums = load_numbers()
    for path in APPLY_FILES:
        if not path.exists():
            continue
        before = path.read_text(encoding="utf-8")
        after, missing = substitute(before, nums, html=False, keep_unresolved=True)
        if after != before:
            path.write_text(after, encoding="utf-8")
        filled = len(PLACEHOLDER.findall(before)) - len(missing)
        print(f"{path.relative_to(ROOT)}: filled {filled}, left {len(missing)}")


# ---------------------------------------------------------------------------------------- chrome
def find_chrome() -> str | None:
    cands = [
        os.environ.get("CHROME", ""),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome") or "",
        shutil.which("chromium") or "",
        shutil.which("chromium-browser") or "",
    ]
    return next((c for c in cands if c and Path(c).exists()), None)


def _chrome(args: list[str], out: Path, timeout: float = 90.0) -> bool:
    """Run headless Chrome until `out` is written and stable, then stop it (Chrome may linger)."""
    chrome = find_chrome()
    if not chrome:
        raise SystemExit(
            "Google Chrome not found (set CHROME=/path/to/chrome). Manual fallback: open "
            "docs/submission/out/deck.html in Chrome -> Print -> Save as PDF, "
            "margins none, background graphics on."
        )
    out.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="aegis-chrome-") as prof:
        cmd = [
            chrome,
            "--headless",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--hide-scrollbars",
            f"--user-data-dir={prof}",
            *args,
        ]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
        deadline = time.monotonic() + timeout
        last, stable = -1, 0
        try:
            while time.monotonic() < deadline:
                size = out.stat().st_size if out.exists() else -1
                stable = stable + 1 if size > 0 and size == last else 0
                last = size
                if stable >= 3 or (proc.poll() is not None and size > 0):
                    break
                if proc.poll() is not None and size <= 0:
                    break
                time.sleep(0.5)
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proc.pid, signal.SIGKILL)
    return out.exists() and out.stat().st_size > 0


def pdf_pages(path: Path) -> int:
    data = path.read_bytes()
    count = len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", data))
    if count:
        return count
    if sys.platform == "darwin":  # Spotlight fallback (may lag for brand-new files)
        res = subprocess.run(
            ["mdls", "-raw", "-name", "kMDItemNumberOfPages", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.stdout.strip().isdigit():
            return int(res.stdout.strip())
    return 0


def build_pdf() -> Path:
    deck = OUT / "deck.html"
    if not deck.exists():
        render()
    pdf = OUT / PDF_NAME
    ok = _chrome(["--no-pdf-header-footer", f"--print-to-pdf={pdf}", deck.as_uri()], pdf)
    if not ok:
        raise SystemExit("PDF not written by headless Chrome (see manual fallback in --help)")
    pages = pdf_pages(pdf)
    size_kb = pdf.stat().st_size // 1024
    print(f"PDF: {pdf.relative_to(ROOT)} · {pages} pages · {size_kb} KB")
    if pages != SLIDES:
        raise SystemExit(f"expected {SLIDES} pages, got {pages}")
    return pdf


def screens(url: str) -> None:
    dest = ROOT / "docs" / "assets" / "screens"
    dest.mkdir(parents=True, exist_ok=True)
    for name, (route, member) in SCREENS.items():
        out = dest / f"{name}.png"
        target = f"{url.rstrip('/')}{route}?view_as={member}"
        _chrome(
            [
                "--window-size=1920,1080",
                "--virtual-time-budget=6000",
                f"--screenshot={out}",
                target,
            ],
            out,
        )
        print(f"{'ok ' if out.exists() else 'ERR'} {out.relative_to(ROOT)}  <- {target}")


# ---------------------------------------------------------------------------------------- check
def _block(text: str, name: str) -> str:
    m = re.search(rf"<!-- {name}:start -->(.*?)<!-- {name}:end -->", text, re.S)
    if not m:
        return ""
    return "\n".join(ln for ln in m.group(1).splitlines() if not ln.strip().startswith("```"))


def words(text: str) -> int:
    return len(text.split())


def broken_links(path: Path) -> list[str]:
    bad = []
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"```.*?```", "", text, flags=re.S)  # ignore code blocks
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"^(https?:|mailto:|#)", target) or "{" in target:
            continue
        rel = target.split("#", 1)[0]
        if rel and not (path.parent / rel).exists():
            bad.append(f"{path.relative_to(ROOT)} -> {target}")
    return bad


def check(strict: bool) -> int:
    problems: list[str] = []
    ht = (HERE / "HACKTRIBE.md").read_text(encoding="utf-8")
    title = _block(ht, "title").strip()
    desc = _block(ht, "description")
    ckpt = _block(ht, "checkpoint")
    print(f"title: {title!r} ({words(title)} words, limit 5)")
    print(f"description: {words(desc)} words incl. team lines (limit 500)")
    print(f"checkpoint: {words(ckpt)} words (limit 160)")
    if not title or words(title) > 5:
        problems.append("title missing or > 5 words")
    if not desc or words(desc) > 500:
        problems.append("description missing or > 500 words")
    if words(ckpt) > 160:
        problems.append("checkpoint > 160 words")
    if "Team:" not in desc:
        problems.append("description has no team block")
    team_placeholders = desc.count("[NAME")
    if team_placeholders:
        msg = f"description still has {team_placeholders} [NAME — EMAIL] placeholders"
        (problems.append(msg) if strict else print("warn: " + msg))
    deck = DECK.read_text(encoding="utf-8")
    n_slides = len(re.findall(r'<section class="slide"', deck))
    n_md = len(re.findall(r"^## Slide \d+", (HERE / "DECK.md").read_text(encoding="utf-8"), re.M))
    print(f"deck: {n_slides} slides in deck.html, {n_md} in DECK.md (limit {SLIDES})")
    if n_slides > SLIDES or n_slides != n_md:
        problems.append(f"deck slide count mismatch/limit: html={n_slides} md={n_md}")
    for path in LINK_FILES:
        if path.exists():
            problems += [f"broken link: {b}" for b in broken_links(path)]
    pdf = OUT / PDF_NAME
    if pdf.exists():
        pages = pdf_pages(pdf)
        print(f"pdf: {pages} pages")
        if pages != SLIDES:
            problems.append(f"PDF has {pages} pages, expected {SLIDES}")
    if strict:
        if not OUT.exists():
            problems.append("out/ missing: run render first")
        else:
            for f in sorted(OUT.glob("*.md")) + sorted(OUT.glob("*.html")):
                left = TBD_LEFT.findall(f.read_text(encoding="utf-8"))
                if left:
                    problems.append(
                        f"{f.relative_to(ROOT)}: {len(left)} unresolved, e.g. {left[0]}"
                    )
        for f in (ROOT / "README.md", HERE / "HACKTRIBE.md"):
            if "[PUBLIC REPO URL]" in f.read_text(encoding="utf-8"):
                problems.append(f"{f.relative_to(ROOT)}: [PUBLIC REPO URL] not filled")
    for p in problems:
        print("FAIL: " + p)
    print("check: " + ("OK" if not problems else f"{len(problems)} problem(s)"))
    return 1 if problems else 0


# ---------------------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument(
        "steps",
        nargs="*",
        default=[],
        help="collect | render | apply (collect numbers, render out/, fill numbers in place)",
    )
    ap.add_argument("--url", default=None, help="live gateway for audit/coverage/policy numbers")
    ap.add_argument(
        "--pdf", action="store_true", help="print out/deck.html to PDF via headless Chrome"
    )
    ap.add_argument("--check", action="store_true", help="limits, slide count, links, PDF pages")
    ap.add_argument("--strict", action="store_true", help="--check also fails on unresolved [TBD]")
    ap.add_argument(
        "--screens", action="store_true", help="capture dashboard screenshots (needs --url)"
    )
    args = ap.parse_args(argv)
    bad = [s for s in args.steps if s not in ("collect", "render", "apply")]
    if bad:
        ap.error(f"unknown step(s): {', '.join(bad)} (choose from collect, render, apply)")
    if not (args.steps or args.pdf or args.check or args.screens):
        ap.print_help()
        return 0
    if "collect" in args.steps:
        collect(args.url)
    if "render" in args.steps or (args.pdf and not (OUT / "deck.html").exists()):
        render()
    if "apply" in args.steps:
        apply_in_place()
    if args.screens:
        if not args.url:
            raise SystemExit(
                "--screens needs --url http://127.0.0.1:8787 (after make demo warm-up)"
            )
        screens(args.url)
    if args.pdf:
        build_pdf()
    if args.check or args.strict:
        return check(args.strict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
