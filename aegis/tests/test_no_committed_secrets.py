"""No secret-shaped literals in judge-editable test data: use {{gen:*}} macros instead.

Scans tests/cases/** and tests/fixtures/** with gitleaks-style patterns (AWS docs `…EXAMPLE` keys
and values marked NOT_A_SECRET are allowed). Keeps GitHub push protection happy.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = [ROOT / "tests" / "cases", ROOT / "tests" / "fixtures"]

# patterns are assembled from parts so this file itself never contains a matching literal
PATTERNS = {
    "aws_access_key_id": re.compile("AK" + r"IA[0-9A-Z]{16}"),
    "github_pat": re.compile("gh" + r"[pousr]_[A-Za-z0-9]{36}"),
    "stripe_live": re.compile("sk" + r"_live_[A-Za-z0-9]{16,}"),
    "slack_token": re.compile("xo" + r"x[bpas]-[0-9A-Za-z\-]{10,}"),
    "anthropic_key": re.compile("sk" + r"-ant-[A-Za-z0-9_\-]{20,}"),
    "openai_key": re.compile("sk" + r"-(?:proj-)?[A-Za-z0-9]{32,}"),
    "private_key": re.compile("-----BEGIN [A-Z ]*" + "PRIVATE KEY-----"),
    "jwt": re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{20,}"),
}
ALLOW = re.compile(r"EXAMPLE|NOT_A_SECRET|\{\{gen:")


def scan() -> list[str]:
    hits: list[str] = []
    for base in SCAN:
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix in (".png", ".jpg", ".gz", ".onnx"):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                for name, rx in PATTERNS.items():
                    for m in rx.finditer(line):
                        window = line[max(0, m.start() - 40) : m.end() + 40]
                        if ALLOW.search(m.group(0)) or ALLOW.search(window):
                            continue
                        hits.append(
                            f"{p.relative_to(ROOT)}:{n}: {name} literal (use {{{{gen:{name}}}}})"
                        )
    return hits


def test_no_secret_shaped_literals() -> None:
    hits = scan()
    assert not hits, "secret-shaped literals committed:\n" + "\n".join(hits)
