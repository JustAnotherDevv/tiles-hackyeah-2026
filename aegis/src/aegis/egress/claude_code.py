"""Claude Code context recognizers for DLP-03 (the F1 metadata showcase).

Claude Code sends its environment as `<system-reminder>` text blocks in the first user turn
(working directory, git user/status, CLAUDE.md contents, the account email, platform/date)
plus `metadata.user_id` = JSON string {device_id, account_uuid, session_id} and a set of
`x-stainless-*` client headers (staging/spikes/claude-code/FINDINGS.md).

CLI (demo backup when live Claude Code is unavailable):
    python -m aegis.egress.claude_code replay [--gateway URL] [--mock URL] [--model mock-echo]
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from aegis.egress.textmeta import GENERALIZED, MetaSpan

USER_EMAIL = re.compile(
    r"The user's email address is[ \t]+([A-Za-z0-9._%+\-]{1,64}@(?:[A-Za-z0-9\-]{1,63}\.){1,8}"
    r"[A-Za-z]{2,24})")
GIT_USER = re.compile(r"(?m)^[ \t]*Git user:[ \t]*([^\n<>]{1,80}?)[ \t]*$")
CLAUDE_MD = re.compile(r"Contents of ([^\n]{1,512}?CLAUDE[^\n/]{0,40}\.md) \(([^)\n]{1,200})\):[ \t]*\n")
ENV_LINE = re.compile(r"(?m)^[ \t]*(?:-[ \t]*)?(Platform|OS Version|Shell):[ \t]*([^\n]{1,120}?)[ \t]*$")
STATUS_HDR = re.compile(r"(?m)^Status:[ \t]*$")
BLOCK_END = re.compile(r"</system-reminder>|\n\nContents of (?=[/~A-Za-z]:?)")

WITHHELD_GIT = "[git status withheld by Aegis]"
WITHHELD_USER_MD = "[user CLAUDE.md withheld by Aegis]"
WITHHELD_PROJECT_MD = "[project CLAUDE.md withheld by Aegis]"


def is_claude_code_headers(headers: Mapping[str, str]) -> bool:
    h = {k.lower(): v for k, v in headers.items()}
    ua = h.get("user-agent", "")
    return (
        ua.startswith("claude-cli/") or "claude-code" in ua
        or h.get("x-app", "") == "cli"
        or "x-claude-code-session-id" in h
        or "claude-code-" in h.get("anthropic-beta", "")
    )


def is_claude_code(interaction: Any) -> bool:
    if is_claude_code_headers(getattr(interaction, "headers", {}) or {}):
        return True
    return any("<system-reminder>" in s.text for s in getattr(interaction, "segments", [])[:64])


def _block_end(text: str, start: int) -> int:
    m = BLOCK_END.search(text, start)
    end = m.start() if m else len(text)
    while end > start and text[end - 1] in " \t\r\n":
        end -= 1
    return end


def scan_segment(text: str, params: Any = None, *, style: str = "placeholder") -> list[MetaSpan]:
    """Claude Code context spans in one text (email, git user, whole-block strips)."""
    from aegis.egress.params import ClaudeCodeParams

    p = params if params is not None else ClaudeCodeParams()
    if not text or not p.enabled:
        return []
    out: list[MetaSpan] = []
    gen = style == "generalize"
    if p.user_email and "email address is" in text:
        for m in USER_EMAIL.finditer(text):
            out.append(MetaSpan(m.start(1), m.end(1), "EMAIL", "meta.cc.user_email", m.group(1),
                                GENERALIZED["EMAIL"] if gen else None, 0.99))
    if p.git_user and "Git user:" in text:
        for m in GIT_USER.finditer(text):
            name = m.group(1).strip()
            if name:
                out.append(MetaSpan(m.start(1), m.start(1) + len(name), "USERNAME",
                                    "meta.cc.git_user", name,
                                    GENERALIZED["USERNAME"] if gen else None, 0.99,
                                    meta={"learn": name}))
    if p.git_status == "strip" and "gitStatus" in text:
        g = text.find("gitStatus")
        m = STATUS_HDR.search(text, g)
        if m:
            end_m = re.search(r"</system-reminder>", text[m.start():])
            end = m.start() + end_m.start() if end_m else len(text)
            while end > m.start() and text[end - 1] in " \t\r\n":
                end -= 1
            out.append(MetaSpan(m.start(), end, "FILE_PATH", "meta.cc.git_status",
                                "git status", WITHHELD_GIT, 1.0, meta={"block": "git_status"}))
    if "CLAUDE" in text and "Contents of " in text:
        for m in CLAUDE_MD.finditer(text):
            paren = m.group(2).lower()
            is_user = "private global" in paren or "/.claude/" in m.group(1)
            is_project = "project instructions" in paren or "checked into" in paren
            if is_user and p.user_claude_md == "strip":
                rep, block = WITHHELD_USER_MD, "user_claude_md"
            elif is_project and not is_user and p.project_claude_md == "strip":
                rep, block = WITHHELD_PROJECT_MD, "project_claude_md"
            else:
                continue
            end = _block_end(text, m.end())
            out.append(MetaSpan(m.start(), max(end, m.end()), "FILE_PATH", f"meta.cc.{block}",
                                "CLAUDE.md", rep, 1.0, meta={"block": block}))
    if p.environment == "generalize" and ("Platform:" in text or "OS Version:" in text):
        for m in ENV_LINE.finditer(text):
            out.append(MetaSpan(m.start(2), m.end(2), "HOSTNAME", "meta.cc.environment",
                                m.group(2), "[OS]", 0.9, meta={"block": "environment"}))
    return out


# ---------------------------------------------------------------- replay CLI
def _diff_lines(before: str, after: str) -> list[str]:
    import difflib

    return list(difflib.unified_diff(before.splitlines(), after.splitlines(), "client sent",
                                     "upstream received", lineterm="", n=0))


def replay(gateway: str, mock: str, model: str) -> int:  # pragma: no cover - live helper
    import json

    import httpx

    from aegis.egress.fixtures import claude_code_headers, claude_code_request

    body = claude_code_request(model=model)
    headers = claude_code_headers()
    headers["x-aegis-agent"] = "claude-code@platform"
    with httpx.Client(timeout=30, trust_env=False) as c:
        try:
            c.delete(f"{mock}/_mock/requests")
        except httpx.HTTPError:
            pass
        r = c.post(f"{gateway}/v1/messages", json=body, headers=headers)
        print(f"gateway -> {r.status_code}  decision={r.headers.get('x-aegis-decision')} "
              f"id={r.headers.get('x-aegis-decision-id')}")
        try:
            got = c.get(f"{mock}/_mock/requests", params={"limit": 1}).json()
        except Exception as exc:
            print(f"cannot read mock log: {exc}")
            return 1
    items = got if isinstance(got, list) else got.get("requests") or got.get("items") or []
    if not items:
        print("mock_llm recorded nothing")
        return 1
    last = items[-1] if isinstance(items, list) else items
    up = last.get("body") or last.get("json") or last
    before = json.dumps(body, indent=1, ensure_ascii=False)
    after = json.dumps(up, indent=1, ensure_ascii=False)
    for line in _diff_lines(before, after):
        print(line)
    up_headers = {k.lower() for k in (last.get("headers") or {})}
    gone = sorted(k for k in headers if k.lower().startswith("x-stainless") and k.lower() not in up_headers)
    print(f"headers removed upstream: {', '.join(gone) or '(not recorded by mock)'}")
    return 0


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    import argparse

    ap = argparse.ArgumentParser(prog="python -m aegis.egress.claude_code")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("replay", help="send the synthetic Claude Code request through the gateway")
    rp.add_argument("--gateway", default="http://127.0.0.1:8787")
    rp.add_argument("--mock", default="http://127.0.0.1:8791")
    rp.add_argument("--model", default="mock-echo")
    a = ap.parse_args(argv)
    if a.cmd == "replay":
        return replay(a.gateway, a.mock, a.model)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
