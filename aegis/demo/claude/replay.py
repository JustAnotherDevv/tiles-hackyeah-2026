#!/usr/bin/env python3
"""Deterministic replay of Claude Code hook events against the Aegis gateway (stdlib only).

    python3 demo/claude/replay.py all                       # every scene, coloured verdicts
    python3 demo/claude/replay.py pipe-to-shell dotenv      # selected scenes (- or _ both work)
    python3 demo/claude/replay.py gpu-480 --hold 20         # approval hold 20 s (deadline 30)
    python3 demo/claude/replay.py read-readme --bench 50    # hook round trip p50 / p95
    python3 demo/claude/replay.py all --via-hook            # through scripts/aegis-hook (bash+curl)
    python3 demo/claude/replay.py --list

Posts the fixture payloads in demo/claude/fixtures/*.json to POST /v1/hooks/claude-code with the
same headers as scripts/aegis-hook, so the live feed shows exactly the rows a real Claude Code
session would produce (source `hook`, agent claude-code@platform). This is the on-stage fallback
when Anthropic or the venue network is flaky, and the deterministic end-to-end check.
Exit code: 0 when every step matched its expectation, 1 otherwise, 2 when the gateway is down.

Fixture templating: {{SESSION}} (one id per run), {{PROJECT}} (demo/claude/project), {{ROOT}}
(repo root), {{HOME}}, {{N}} (run counter), {{FILE:<path under project>}} (file content),
{{TAMPERED_SETTINGS}} (a temp settings file whose hooks were removed).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROJECT = HERE / "project"
FIXTURES = HERE / "fixtures"
HOOK = ROOT / "scripts" / "aegis-hook"
AGENT = os.environ.get("AEGIS_AGENT", "claude-code@platform")
ALIASES = {"dotenv": "read_dotenv", "injection": "setup_md_post", "readme": "read_readme",
           "gpu": "gpu_480", "harness": "edit_hook_settings", "tamper": "config_change",
           "pii": "prompt_pii", "start": "session_start", "curl": "pipe_to_shell"}
ORDER = ["session_start", "read_readme", "git_status", "pipe_to_shell", "read_dotenv", "webfetch",
         "setup_md_post", "prompt_pii", "edit_hook_settings", "config_change", "gpu_480"]

TTY = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if TTY else s


RED, GREEN, YELLOW, BLUE, DIM, BOLD = "31;1", "32;1", "33;1", "36;1", "2", "1"


# ---------------------------------------------------------------- fixtures
def load_fixture(name: str) -> dict[str, Any]:
    key = ALIASES.get(name, name).replace("-", "_")
    path = FIXTURES / f"{key}.json"
    if not path.exists():
        raise SystemExit(f"unknown scene {name!r}; try --list")
    return json.loads(path.read_text(encoding="utf-8"))


def all_scenes() -> list[str]:
    names = sorted(p.stem for p in FIXTURES.glob("*.json"))
    return [n for n in ORDER if n in names] + [n for n in names if n not in ORDER]


class Templater:
    def __init__(self, session: str, n: int) -> None:
        self.vars = {"SESSION": session, "PROJECT": str(PROJECT), "ROOT": str(ROOT),
                     "HOME": str(Path.home()), "N": str(n)}
        self._tampered: str | None = None

    def tampered_settings(self) -> str:
        if self._tampered is None:
            src = HERE / "settings.json"
            try:
                doc = json.loads(src.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                doc = {"hooks": {}, "env": {}}
            doc.pop("hooks", None)  # the "tamper": drop every Aegis hook
            fd, path = tempfile.mkstemp(prefix="aegis-tampered-", suffix=".json")
            with os.fdopen(fd, "w") as f:
                json.dump(doc, f)
            self._tampered = path
        return self._tampered

    def _one(self, s: str) -> str:
        def sub(m: re.Match[str]) -> str:
            key = m.group(1)
            if key.startswith("FILE:"):
                try:
                    return (PROJECT / key[5:]).read_text(encoding="utf-8")
                except OSError:
                    return ""
            if key == "TAMPERED_SETTINGS":
                return self.tampered_settings()
            return self.vars.get(key, m.group(0))

        return re.sub(r"\{\{([A-Z_]+(?::[^}]+)?)\}\}", sub, s)

    def apply(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self._one(obj)
        if isinstance(obj, list):
            return [self.apply(v) for v in obj]
        if isinstance(obj, dict):
            return {k: self.apply(v) for k, v in obj.items()}
        return obj

    def cleanup(self) -> None:
        if self._tampered:
            try:
                os.unlink(self._tampered)
            except OSError:
                pass


# ---------------------------------------------------------------- transport
def agent_key() -> str:
    key = os.environ.get("AEGIS_AGENT_KEY", "")
    if key:
        return key
    f = Path(os.environ.get("AEGIS_AGENT_KEY_FILE") or HERE / ".agent_key")
    try:
        return f.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def post(gateway: str, event: str, payload: dict[str, Any], deadline: float) -> tuple[int, dict[str, Any], dict[str, str], float]:
    body = json.dumps(payload).encode()
    headers = {"content-type": "application/json", "X-Aegis-Agent": AGENT,
               "X-Aegis-Hook-Event": event, "X-Aegis-Hook-Deadline": f"{deadline:g}"}
    key = agent_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(f"{gateway}/v1/hooks/claude-code", data=body, headers=headers,
                                 method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    t = time.perf_counter()
    with opener.open(req, timeout=deadline + 5) as resp:
        raw = resp.read()
        ms = (time.perf_counter() - t) * 1000
        out = json.loads(raw) if raw.strip() else {}
        return resp.status, out, {k.lower(): v for k, v in resp.headers.items()}, ms


def via_hook(gateway: str, event: str, payload: dict[str, Any], deadline: float) -> tuple[int, dict[str, Any], dict[str, str], float]:
    env = {**os.environ, "AEGIS_URL": gateway, "AEGIS_HOOK_TIMEOUT": f"{deadline:g}",
           "AEGIS_HOOK_TIMEOUT_FAST": "10"}
    t = time.perf_counter()
    p = subprocess.run(["/bin/bash", str(HOOK), event], input=json.dumps(payload).encode(),
                       capture_output=True, env=env, timeout=deadline + 10)
    ms = (time.perf_counter() - t) * 1000
    if p.returncode == 2:
        return 0, {"_exit2": p.stderr.decode(errors="replace").strip()}, {}, ms
    raw = p.stdout.decode(errors="replace").strip()
    return 200, (json.loads(raw) if raw else {}), {}, ms


# ---------------------------------------------------------------- classification
def classify(event: str, out: dict[str, Any]) -> tuple[str, str]:
    """(result, text) where result in allow|deny|pending|modify|block|note|banner|fail_closed."""
    if "_exit2" in out:
        return "fail_closed", out["_exit2"]
    hso = out.get("hookSpecificOutput") or {}
    if event == "PreToolUse":
        d = hso.get("permissionDecision")
        reason = str(hso.get("permissionDecisionReason") or "")
        if d == "deny":
            return ("pending" if re.search(r"Approval apr_\S+ pending", reason) else "deny"), reason
        if d == "allow" and "updatedInput" in hso:
            return "modify", reason
        return "allow", reason or "no opinion ({})" if not hso else reason
    if event == "PostToolUse":
        if out.get("decision") == "block":
            return "block", str(out.get("reason") or "")
        if "updatedToolOutput" in hso or "updatedMCPToolOutput" in hso:
            return "modify", str(hso.get("additionalContext") or "")
        return "allow", "no opinion ({})"
    if event in ("UserPromptSubmit", "ConfigChange"):
        if out.get("decision") == "block":
            return "block", str(out.get("reason") or "")
        if out.get("systemMessage"):
            return "note", str(out["systemMessage"])
        return "allow", "no opinion ({})"
    if event == "SessionStart":
        return "banner", str(out.get("systemMessage") or hso.get("additionalContext") or "")
    return "allow", json.dumps(out)[:200]


def matches(expect: dict[str, Any], result: str, text: str) -> bool:
    want = [w for w in str(expect.get("result", "")).split("|") if w]
    if want and result not in want:
        return False
    needles = [n for n in str(expect.get("contains", "")).split("|") if n]
    return not needles or any(n in text for n in needles)


COLOR = {"deny": RED, "block": RED, "fail_closed": RED, "pending": YELLOW, "modify": BLUE,
         "note": BLUE, "allow": GREEN, "banner": GREEN}


def describe(payload: dict[str, Any], event: str) -> str:
    tool = payload.get("tool_name")
    if not tool:
        return event
    ti = payload.get("tool_input") or {}
    arg = ti.get("command") or ti.get("file_path") or ti.get("url") or ""
    if not arg and isinstance(ti, dict):
        arg = ", ".join(f"{k}={v}" for k, v in list(ti.items())[:3])
    arg = str(arg).replace(str(PROJECT) + "/", "").replace(str(ROOT) + "/", "")
    return f"{event} {tool}({arg[:60]})"


# ---------------------------------------------------------------- main
def run_scene(name: str, args: argparse.Namespace, session: str, n: int) -> bool:
    fx = load_fixture(name)
    t = Templater(session, n)
    send = via_hook if args.via_hook else post
    ok_all = True
    print(c(BOLD, f"\n▶ {fx['name']}") + c(DIM, f"  {fx.get('title', '')}"))
    try:
        for step in fx["steps"]:
            event = step["event"]
            payload = t.apply(step["payload"])
            deadline = float(args.hold + 10 if args.hold is not None else 110)
            if event not in ("PreToolUse", "UserPromptSubmit", "ConfigChange"):
                deadline = 10.0
            if event == "PreToolUse" and "approval" in fx.get("title", "").lower() and args.hold is None:
                print(c(DIM, "  … holding for approval (up to 60 s) - approve in the dashboard "
                             "(Governance → Approvals) as the owner"))
            status, out, headers, ms = send(args.gateway, event, payload, deadline)
            result, text = classify(event, out)
            ok = status in (0, 200) and matches(step.get("expect", {}), result, text)
            ok_all &= ok
            mark = c(GREEN, "✔") if ok else c(RED, "✘")
            dec = headers.get("x-aegis-decision-id", "")
            print(f"  {mark} {describe(payload, event):<70} → {c(COLOR.get(result, BOLD), result.upper())}"
                  + c(DIM, f"  {ms:.0f} ms {dec}"))
            if text and (args.verbose or result != "allow"):
                print(c(DIM, "      " + text[:400].replace("\n", " ")))
            if not ok:
                print(c(RED, f"      expected {step.get('expect')}"))
    finally:
        t.cleanup()
    return ok_all


def bench(name: str, args: argparse.Namespace) -> int:
    fx = load_fixture(name)
    step = next(s for s in fx["steps"] if s["event"] == "PreToolUse")
    send = via_hook if args.via_hook else post
    t = Templater(f"bench-{uuid.uuid4().hex[:8]}", 0)
    samples: list[float] = []
    for i in range(args.bench):
        t.vars["N"] = str(i)
        _, _, _, ms = send(args.gateway, "PreToolUse", t.apply(step["payload"]), 110.0)
        samples.append(ms)
    samples.sort()
    p50 = statistics.median(samples)
    p95 = samples[min(len(samples) - 1, int(len(samples) * 0.95))]
    how = "bash+curl hook" if args.via_hook else "HTTP"
    print(f"{name}: {len(samples)} PreToolUse round trips via {how}: p50 {p50:.1f} ms, "
          f"p95 {p95:.1f} ms, max {samples[-1]:.1f} ms")
    ok = p50 < 40 and p95 < 120
    print(c(GREEN, "within budget (p50 < 40 ms, p95 < 120 ms)") if ok
          else c(YELLOW, "over the CC-V14 budget (p50 < 40 ms, p95 < 120 ms)"))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("scenes", nargs="*", help="scene names, or 'all'")
    ap.add_argument("--gateway", default=os.environ.get("AEGIS_URL", "http://127.0.0.1:8787"))
    ap.add_argument("--hold", type=float, default=None,
                    help="approval hold in seconds (sends hook deadline = hold + 10)")
    ap.add_argument("--bench", type=int, default=0, help="N PreToolUse round trips, p50/p95")
    ap.add_argument("--via-hook", action="store_true", help="go through scripts/aegis-hook")
    ap.add_argument("--session", default=None, help="session id (default: replay-<random>)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    args.gateway = args.gateway.rstrip("/")

    if args.list or not args.scenes:
        for n in all_scenes():
            print(f"  {n.replace('_', '-'):<20} {load_fixture(n).get('title', '')}")
        return 0
    names = all_scenes() if args.scenes == ["all"] else args.scenes
    try:
        if args.bench:
            return bench(names[0], args)
        session = args.session or f"replay-{uuid.uuid4().hex[:12]}"
        print(c(DIM, f"Aegis hook replay → {args.gateway}/v1/hooks/claude-code · session {session}"))
        results = [run_scene(n, args, session, i) for i, n in enumerate(names)]
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        print(c(RED, f"gateway unreachable at {args.gateway}: {exc}. Start it with `make up`."))
        return 2
    passed = sum(results)
    print("\n" + c(GREEN if passed == len(results) else RED,
                    f"{passed}/{len(results)} scenes matched their expectation"))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
