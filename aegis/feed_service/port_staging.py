"""One-off converter: staging/feed-seed signatures -> contract YAML in feed_service/signatures/.

Kept for provenance; idempotent. Reads `staging/feed-seed/{signatures,pending}` (read-only) and
writes `feed_service/signatures/AEGIS-TI-*.yaml` using the per-signature surface table of
docs/plan/13-threat-feed.md section 2.3 (ruamel round-trip keeps comments). AEGIS-TI-022 gets
`enabled: false`. The demo host moves from aegis-corp to acme-capital (the demo cast).

    uv run --frozen python feed_service/port_staging.py          # convert + check
    uv run --frozen python feed_service/port_staging.py --check  # only check the output
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "staging" / "feed-seed"
OUT = ROOT / "feed_service" / "signatures"
DEMO_OUT = ROOT / "feed_service" / "demo"

ALL_SURFACES = [
    "prompt.user", "model.request", "model.response", "model.admin", "tool.input", "tool.output",
    "artifact.file", "mcp.init", "mcp.list", "mcp.call", "mcp.result", "egress.request",
    "egress.response", "a2a.message", "a2a.result",
]

# id -> surfaces, action (None = keep), overrides, extra keys, example surface map
TABLE: dict[str, dict[str, Any]] = {
    "AEGIS-TI-000": {"surfaces": ALL_SURFACES,
                     "ex": {"model_call": "model.request", "tool_call": "tool.input",
                            "output": "model.response", "mcp": "mcp.call", "egress": "egress.request",
                            "model_download": "artifact.file"}},
    "AEGIS-TI-001": {"surfaces": ["artifact.file"], "ex": {"model_download": "artifact.file"}},
    "AEGIS-TI-002": {"surfaces": ["artifact.file"], "ex": {"model_download": "artifact.file"}},
    "AEGIS-TI-003": {"surfaces": ["egress.request", "model.admin", "model.response", "tool.output"],
                     "overrides": {"model.response": "log", "tool.output": "log"},
                     "ex": {"model_download": "egress.request", "output": "model.response"}},
    "AEGIS-TI-004": {"surfaces": ["artifact.file"], "ex": {"model_download": "artifact.file"}},
    "AEGIS-TI-005": {"surfaces": ["artifact.file", "model.admin", "egress.request"],
                     "ex": {"model_download": "artifact.file", "egress": "egress.request"}},
    "AEGIS-TI-006": {"surfaces": ["egress.request"], "ex": {"egress": "egress.request"}},
    "AEGIS-TI-007": {"surfaces": ["egress.request", "tool.input", "mcp.call"],
                     "ex": {"egress": "egress.request", "tool_call": "tool.input"}},
    "AEGIS-TI-008": {"surfaces": ["egress.request"], "ex": {"egress": "egress.request"}},
    "AEGIS-TI-009": {"surfaces": ["tool.input", "mcp.call", "model.response"],
                     "overrides": {"model.response": "log"},
                     "ex": {"tool_call": "tool.input", "output": "model.response"}},
    "AEGIS-TI-010": {"surfaces": ["mcp.init", "mcp.result", "egress.response"],
                     "ex": {"mcp": "mcp.result"}},
    "AEGIS-TI-011": {"surfaces": ["egress.request", "mcp.call", "tool.input"],
                     "ex": {"egress": "egress.request", "mcp": "mcp.call", "tool_call": "tool.input"}},
    "AEGIS-TI-012": {"surfaces": ["mcp.list", "tool.output", "mcp.result"], "action": "redact",
                     "extra": {"redact_scope": "tool"}, "ex": {"tool_call": "mcp.list"}},
    "AEGIS-TI-013": {"surfaces": ["prompt.user", "model.request", "model.response", "mcp.list",
                                  "tool.input", "mcp.call"],
                     "action": "redact",
                     "overrides": {"mcp.list": "block", "tool.input": "block", "mcp.call": "block"},
                     "extra": {"redact_with": ""},
                     "ex": {"model_call": "model.request", "tool_call": "mcp.list",
                            "output": "model.response"}},
    "AEGIS-TI-014": {"surfaces": ["model.response", "tool.output", "mcp.result", "tool.input",
                                  "mcp.call"],
                     "ex": {"output": "model.response", "tool_call": "tool.input"}},
    "AEGIS-TI-015": {"surfaces": ["tool.input", "mcp.call"], "ex": {"tool_call": "tool.input"}},
    "AEGIS-TI-016": {"surfaces": ["tool.input", "mcp.call", "model.response"],
                     "overrides": {"model.response": "log"},
                     "ex": {"tool_call": "tool.input", "output": "model.response"}},
    "AEGIS-TI-017": {"surfaces": ["tool.input", "mcp.call", "mcp.init", "model.response",
                                  "egress.request"],
                     "ex": {"tool_call": "tool.input", "egress": "egress.request",
                            "output": "model.response", "mcp": "mcp.init"}},
    "AEGIS-TI-018": {"surfaces": ["egress.request", "model.admin"],
                     "ex": {"model_download": "egress.request"}},
    "AEGIS-TI-019": {"surfaces": ["prompt.user", "model.request", "tool.output", "mcp.result",
                                  "model.response"],
                     "overrides": {"tool.output": "redact", "mcp.result": "redact",
                                   "model.response": "log"},
                     "extra": {"redact_scope": "segment"},
                     "ex": {"model_call": "model.request", "tool_call": "tool.output",
                            "output": "model.response"}},
    "AEGIS-TI-022": {"surfaces": ["model.response", "tool.output", "mcp.result", "tool.input",
                                  "mcp.call"],
                     "extra": {"enabled": False},
                     "ex": {"output": "model.response", "tool_call": "tool.input"}},
}

LEAF_ALIASES = {"literal": "literal_set", "pickle_opcode": "pickle_globals",
                "jsonpath": "json_path", "semantic_exemplar": "semantic"}
ACTION_ALIASES = {"quarantine": "redact", "strip_tool": "redact", "alert": "log"}
OLD_HOST, NEW_HOST = "aegis-corp.example", "acme-capital.example"


def _yaml() -> Any:
    from ruamel.yaml import YAML

    y = YAML()  # round-trip
    y.preserve_quotes = True
    y.width = 4096  # never fold long base64 vectors
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _rename_key(cm: Any, old: str, new: str) -> None:
    if old not in cm or new in cm:
        return
    keys = list(cm.keys())
    pos = keys.index(old)
    value = cm.pop(old)
    cm.insert(pos, new, value)


def _set_after(cm: Any, after: str, key: str, value: Any) -> None:
    if key in cm:
        cm[key] = value
        return
    keys = list(cm.keys())
    pos = keys.index(after) + 1 if after in keys else len(keys)
    cm.insert(pos, key, value)


def _canon_leaves(node: Any) -> None:
    if isinstance(node, dict):
        t = node.get("type")
        if isinstance(t, str) and t in LEAF_ALIASES:
            node["type"] = LEAF_ALIASES[t]
        for v in node.values():
            _canon_leaves(v)
    elif isinstance(node, list):
        for v in node:
            _canon_leaves(v)


def _replace_host(node: Any) -> Any:
    """Recursively switch aegis-corp -> acme-capital in strings (demo cast)."""
    from ruamel.yaml.scalarstring import ScalarString

    if isinstance(node, dict):
        for k in list(node.keys()):
            node[k] = _replace_host(node[k])
        return node
    if isinstance(node, list):
        for i, v in enumerate(node):
            node[i] = _replace_host(v)
        return node
    if isinstance(node, str) and OLD_HOST in node:
        new = node.replace(OLD_HOST, NEW_HOST)
        if isinstance(node, ScalarString):
            return type(node)(new)
        return new
    return node


def _contract_example_keys(ex: Any) -> None:
    """A-49: vectors use text / tool_name / tool_args / url / http_method / raw / meta so the
    test-suite can replay them through /v1/guard (staging keys stay accepted by the engine)."""
    import base64

    from ruamel.yaml.comments import CommentedMap

    if isinstance(ex.get("json"), dict):
        _rename_key(ex, "json", "tool_args")
    if "method" in ex:
        _rename_key(ex, "method", "http_method")
    if "body" in ex:
        _rename_key(ex, "body", "raw")
    meta = CommentedMap()
    if "bytes_hex" in ex:
        meta["artifact_b64"] = base64.b64encode(bytes.fromhex("".join(str(ex.pop("bytes_hex")).split()))).decode()
    elif "bytes_b64" in ex:
        meta["artifact_b64"] = "".join(str(ex.pop("bytes_b64")).split())
    if "filename" in ex:
        meta["filename"] = str(ex.pop("filename"))
    if "json" in ex:  # non-dict JSON payload (rare) travels in meta.json
        meta["json"] = ex.pop("json")
    if meta:
        if "artifact_b64" not in meta:
            meta.fa.set_flow_style()
        ex["meta"] = meta


def convert(sig_path: Path) -> tuple[str, str]:
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    y = _yaml()
    doc = y.load(sig_path.read_text(encoding="utf-8"))
    sid = str(doc["id"])
    spec = TABLE[sid]
    if sid in ("AEGIS-TI-014", "AEGIS-TI-022"):
        key = "host_not_in" if sid == "AEGIS-TI-014" else "host_in"
        hosts = doc["matcher"][key]
        for h in ("assets.acme-capital.example", "*.acme-capital.example"):
            if h not in hosts:
                hosts.append(h)
        # vectors + description switch to the demo cast; matcher keeps the aegis-corp entries
        for k in ("tests", "description"):
            if k in doc:
                doc[k] = _replace_host(doc[k])
    _rename_key(doc, "matcher", "match")
    _canon_leaves(doc["match"])
    surfaces = CommentedSeq(spec["surfaces"])
    surfaces.fa.set_flow_style()
    at = CommentedMap([("surfaces", surfaces)])
    doc["applies_to"] = at
    action = spec.get("action") or ACTION_ALIASES.get(str(doc["action"]), str(doc["action"]))
    doc["action"] = action
    if "overrides" in spec:
        ov = CommentedMap(spec["overrides"])
        ov.fa.set_flow_style()
        _set_after(doc, "action", "action_overrides", ov)
    elif "action_overrides" in doc:
        del doc["action_overrides"]
    after = "action_overrides" if "action_overrides" in doc else "action"
    for k, v in (spec.get("extra") or {}).items():
        if k == "enabled":
            continue
        _set_after(doc, after, k, v)
        after = k
    ex_map = spec["ex"]
    for kind in ("positive", "negative"):
        for ex in doc["tests"][kind]:
            s = str(ex["surface"])
            if s not in ex_map:
                raise SystemExit(f"{sid}: no example surface mapping for {s!r}")
            ex["surface"] = ex_map[s]
            _contract_example_keys(ex)
    if (spec.get("extra") or {}).get("enabled") is False:
        _set_after(doc, "id", "enabled", False)
        doc.yaml_add_eol_comment("draft: authoring-only flag, enable + Publish to ship it", "enabled")
    buf = io.StringIO()
    header = (f"# {sid} - ported from staging/feed-seed by feed_service/port_staging.py "
              "(contract shape, CONTRACTS 4.7)\n")
    y.dump(doc, buf)
    return sid, header + buf.getvalue()


def port() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    DEMO_OUT.mkdir(parents=True, exist_ok=True)
    paths = sorted((STAGING / "signatures").glob("AEGIS-TI-*.yaml"))
    paths += sorted((STAGING / "pending").glob("AEGIS-TI-*.yaml"))
    for p in paths:
        sid, text = convert(p)
        (OUT / f"{sid}.yaml").write_text(text, encoding="utf-8")
    payload = (STAGING / "demo" / "echoleak-proxy-payload.md").read_text(encoding="utf-8")
    (DEMO_OUT / "echoleak-proxy-payload.md").write_text(payload.replace(OLD_HOST, NEW_HOST),
                                                        encoding="utf-8")
    print(f"ported {len(paths)} signatures -> {OUT.relative_to(ROOT)}")
    return len(paths)


def check() -> int:
    """21 signatures, every vector passes, test surfaces in applies_to, demo invariant."""
    import yaml

    from aegis.feed.matchers import Event, compile_signature, run_tests, scan_event
    from aegis.feed.schema import signature_problems

    files = sorted(OUT.glob("AEGIS-TI-*.yaml"))
    total = failures = 0
    published, drafts = [], []
    for f in files:
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        probs = signature_problems(d)
        c = compile_signature(d)
        n, fails = run_tests(c)
        total += n
        failures += len(fails) + len(probs)
        for msg in probs + fails:
            print(f"FAIL {d['id']}: {msg}")
        (drafts if d.get("enabled") is False else published).append(c)
    payload = (DEMO_OUT / "echoleak-proxy-payload.md").read_text(encoding="utf-8")
    before, _ = scan_event(published, Event(surface="model.response", text=payload))
    after, hits = scan_event(published + drafts, Event(surface="model.response", text=payload))
    demo_ok = before == "allow" and after == "block" and any(
        h["signature_id"] == "AEGIS-TI-022" for h in hits)
    ok = len(files) == 21 and failures == 0 and demo_ok
    print(f"{'OK' if ok else 'FAILED'}: {len(files)} signatures ({len(drafts)} draft), {total} vectors, "
          f"{failures} failures; demo invariant {'PASS' if demo_ok else 'FAIL'} "
          f"(before={before}, after={after})")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="only check feed_service/signatures")
    args = ap.parse_args(argv)
    if not args.check:
        port()
    return check()


if __name__ == "__main__":
    sys.exit(main())
