"""POL-16 snippet check / merge: fold `config/snippets/*.yaml` into `config/policy.yaml`.

    uv run --frozen python -m aegis.policy.snippets check            # per-snippet delta, nothing written
    uv run --frozen python -m aegis.policy.snippets merge            # merge + validate + write policy & golden
    uv run --frozen python -m aegis.policy.snippets merge --dry-run  # show what merge would do
    options: --policy PATH  --snippets DIR  --only a.yaml,b.yaml  --no-golden  --report out.json  --diff

Merge rules (CONTRACTS 2.3 + Addendum A-34):
* mappings are deep-merged; on scalar conflicts the **snippet wins**, except values whose policy
  line carries a `[SF-..]` seed-fix tag (policy keeps them; reported as `kept`).
* keyed lists merge by identity: controls / actions / approval rules / feeds.sources by `id`,
  tests by `name`, budgets.limits by (`scope`, `window`), models.downgrade by `from`. Matching
  items are deep-merged; new items are inserted after the previous snippet item, so ordered lists
  (`approvals.rules`, `actions`) keep the snippet's order (first match wins).
* lists of scalars are unioned (missing values appended); other unkeyed lists that differ are
  replaced by the snippet's list (reported).
* edits are surgical text edits (comments, alignment and flow style of untouched lines survive);
  the result is validated against the frozen PolicyDoc before anything is written.
Snippets are processed in file-name order; a value set by an earlier snippet and changed by a
later one is reported as a conflict (last snippet wins).
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, SequenceNode

from aegis.core.policy_schema import PatchOp
from aegis.policy.loader import compose
from aegis.policy.patch import (
    PatchError,
    _find_item,
    _line_start,
    _load,
    _map_get,
    _node_end_line,
    apply_op,
    render_flow,
    render_scalar,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SKIP_TOP = {"version"}
_UNSAFE_SEL = set(",=[]")


# ---------------------------------------------------------------- report
@dataclass
class Item:
    snippet: str
    path: str
    kind: str  # add | set | append | replace | kept | conflict | error
    before: Any = None
    after: Any = None
    note: str = ""

    def line(self) -> str:
        def short(v: Any) -> str:
            s = json.dumps(v, ensure_ascii=False, default=str) if not isinstance(v, str) else v
            return s if len(s) <= 70 else s[:67] + "..."

        if self.kind in ("add", "append"):
            body = f"+ {self.path}"
        elif self.kind in ("set", "replace"):
            body = f"~ {self.path}: {short(self.before)} -> {short(self.after)}"
        elif self.kind == "kept":
            body = f"= {self.path}: kept {short(self.before)} (snippet wanted {short(self.after)})"
        elif self.kind == "conflict":
            body = f"! {self.path}: {short(self.before)} -> {short(self.after)}"
        elif self.kind == "skipped":
            body = f"- {self.path}: skipped"
        else:
            body = f"x {self.path}"
        return body + (f"   # {self.note}" if self.note else "")


@dataclass
class MergeResult:
    text: str
    items: list[Item] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def changed(self) -> int:
        return sum(1 for i in self.items if i.kind in ("add", "set", "append", "replace", "conflict"))

    def by_snippet(self) -> dict[str, list[Item]]:
        out: dict[str, list[Item]] = {}
        for it in self.items:
            out.setdefault(it.snippet, []).append(it)
        return out


# ---------------------------------------------------------------- identity rules
def _list_key(path: str, items: list[Any]) -> tuple[str, ...] | None:
    dicts = [x for x in items if isinstance(x, dict)]
    if not dicts or len(dicts) != len(items):
        return None
    tail = path.rsplit(".", 1)[-1]
    if tail == "limits":
        return ("scope", "window", "match_agents")
    if tail == "downgrade":
        return ("from",)
    if tail == "tests" or all("name" in d and "id" not in d for d in dicts):
        return ("name",) if all("name" in d for d in dicts) else None
    if all("id" in d for d in dicts):
        return ("id",)
    return None


_OPTIONAL_KEYS = {"match_agents"}


def _key_of(item: dict[str, Any], key: tuple[str, ...]) -> tuple[str, ...] | None:
    if not all(k in item or k in _OPTIONAL_KEYS for k in key):
        return None
    return tuple(json.dumps(item.get(k), sort_keys=True) if k in _OPTIONAL_KEYS else str(item[k]) for k in key)


def _sel(key: tuple[str, ...], item: dict[str, Any], old: list[Any], idx: int) -> str:
    """`[k=v,...]` selector for old[idx] when it is unambiguous, else `[idx]`."""
    parts = {k: str(item[k]) for k in key if k not in _OPTIONAL_KEYS and k in item}
    safe = parts and not any(set(v) & _UNSAFE_SEL for v in parts.values())
    if safe:
        first = next((i for i, o in enumerate(old) if isinstance(o, dict)
                      and all(k in o and str(o[k]) == v for k, v in parts.items())), -1)
        if first == idx:
            return "[" + ",".join(f"{k}={v}" for k, v in parts.items()) + "]"
    return f"[{idx}]"


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


# ---------------------------------------------------------------- node helpers
def _find_node(root: Node | None, path: str) -> Node | None:
    from aegis.policy.patch import parse_path

    node = root
    for kind, val in parse_path(path):
        if node is None:
            return None
        if kind == "key":
            if not isinstance(node, MappingNode):
                return None
            hit = _map_get(node, val)
            node = hit[1] if hit else None
        elif kind == "index":
            if not isinstance(node, SequenceNode) or not -len(node.value) <= val < len(node.value):
                return None
            node = node.value[val]
        else:
            if not isinstance(node, SequenceNode):
                return None
            i = _find_item(node, val)
            node = node.value[i] if i >= 0 else None
    return node


def _sf_tagged(text: str, node: Node | None) -> bool:
    if node is None:
        return False
    start = _line_start(text, node.start_mark.index)
    end = text.find("\n", node.end_mark.index)
    return "[SF-" in text[start : (len(text) if end < 0 else end)]


def _render_block_item(value: Any, dash_col: int) -> str:
    """A new list item; complex mappings in block style (one key per line), else one flow line."""
    pad = " " * dash_col
    if not isinstance(value, dict) or len(render_flow(value)) <= 110:
        return f"{pad}- {render_flow(value)}\n"
    lines: list[str] = []
    kpad = " " * (dash_col + 2)
    for i, (k, v) in enumerate(value.items()):
        lead = f"{pad}- " if i == 0 else kpad
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            lines.append(f"{lead}{render_scalar(str(k))}:")
            lines.extend(f"{kpad}  - {render_flow(x)}" for x in v)
        else:
            lines.append(f"{lead}{render_scalar(str(k))}: {render_flow(v)}")
    return "\n".join(lines) + "\n"


def _insert_seq_item(text: str, seq_path: str, after: int, value: Any) -> str:
    """Insert `value` after item index `after` (-1 = first) of the sequence at `seq_path`."""
    seq = _find_node(compose(text), seq_path)
    if not isinstance(seq, SequenceNode) or not seq.value:
        raise PatchError(seq_path, "not a non-empty list")
    if seq.flow_style:
        if after == len(seq.value) - 1:
            return apply_op(text, PatchOp(op="append", path=seq_path, value=value))
        nxt = seq.value[after + 1]
        return text[: nxt.start_mark.index] + render_flow(value) + ", " + text[nxt.start_mark.index :]
    first = seq.value[0]
    dash = text.rfind("-", _line_start(text, first.start_mark.index), first.start_mark.index)
    if dash < 0:
        raise PatchError(seq_path, "cannot locate list indentation")
    dash_col = dash - _line_start(text, dash)
    rendered = _render_block_item(value, dash_col)
    if after < 0:
        pos = _line_start(text, dash)
    else:
        pos = _node_end_line(text, seq.value[after])
    out = text[:pos] + rendered + text[pos:]
    _verify_insert(text, out, seq_path, after, value)
    return out


def _verify_insert(before: str, after_text: str, seq_path: str, after: int, value: Any) -> None:
    from aegis.policy.loader import parse_yaml
    from aegis.policy.patch import get_path, parse_path

    tokens = parse_path(seq_path)
    old = get_path(_load(before), tokens)
    parsed = parse_yaml(after_text)  # raises on syntax errors; duplicate keys are reported as issues
    new = get_path(parsed.raw, tokens)
    dup = [i for i in parsed.warnings if "duplicate" in i.message]
    if not isinstance(new, list) or len(new) != len(old) + 1 or new[after + 1] != value or dup:
        raise PatchError(seq_path, "insertion did not verify")


def _replace_seq(text: str, seq_path: str, value: list[Any]) -> str:
    node = _find_node(compose(text), seq_path)
    if isinstance(node, SequenceNode) and not node.flow_style and node.value and value:
        first = node.value[0]
        dash = text.rfind("-", _line_start(text, first.start_mark.index), first.start_mark.index)
        if dash >= 0:
            dash_col = dash - _line_start(text, dash)
            start = _line_start(text, dash)
            end = _node_end_line(text, node.value[-1])
            body = "".join(_render_block_item(v, dash_col) for v in value)
            out = text[:start] + body + text[end:]
            with contextlib.suppress(yaml.YAMLError):
                _load(out)
                return out
    return apply_op(text, PatchOp(op="set", path=seq_path, value=value))


# ---------------------------------------------------------------- merge engine
class _Merger:
    def __init__(self, text: str):
        self.text = text
        self.raw: dict[str, Any] = _load(text) or {}
        self.items: list[Item] = []
        self.errors: list[str] = []
        self.touched: dict[str, str] = {}
        self.snippet = ""

    def _rec(self, kind: str, path: str, before: Any = None, after: Any = None, note: str = "") -> None:
        prev = self.touched.get(path)
        if prev and prev != self.snippet and kind in ("set", "replace"):
            kind, note = "conflict", f"also set by {prev}; {self.snippet} wins" + (f"; {note}" if note else "")
        if kind in ("add", "set", "append", "replace", "conflict"):
            self.touched[path] = self.snippet
        self.items.append(Item(self.snippet, path, kind, before, after, note))

    def _op(self, op: str, path: str, value: Any = None) -> bool:
        try:
            self.text = apply_op(self.text, PatchOp(op=op, path=path, value=value))  # type: ignore[arg-type]
            return True
        except Exception as exc:
            self.errors.append(f"{self.snippet}: {path}: {exc}")
            self._rec("error", path, note=str(exc))
            return False

    # -- entry
    def merge_snippet(self, name: str, data: dict[str, Any]) -> None:
        self.snippet = name
        from aegis.core.policy_schema import PolicyDoc

        known = {f.alias or n for n, f in PolicyDoc.model_fields.items()} | set(PolicyDoc.model_fields)
        for k, v in data.items():
            if k in SKIP_TOP or str(k).startswith("x-"):
                continue
            if str(k) not in known:
                self._rec("skipped", str(k), note="not a policy.yaml section (left for its owner)")
                continue
            self._merge(str(k), self.raw, k, v)

    # -- recursion over (parent container, key) so we can mutate the raw mirror
    def _merge(self, path: str, parent: dict[str, Any], key: str, new: Any) -> None:
        if not isinstance(parent, dict):
            return
        if key not in parent:
            if "." in key or "[" in key:
                self.errors.append(f"{self.snippet}: {path}: key needs a manual merge")
                return
            if self._op("set", path, new):
                parent[key] = copy.deepcopy(new)
                self._rec("add", path, None, new)
            return
        old = parent[key]
        if isinstance(old, dict) and isinstance(new, dict):
            for k, v in new.items():
                if "." in str(k) or "[" in str(k):
                    if old.get(k) != v:
                        self.errors.append(f"{self.snippet}: {path}.{k}: key needs a manual merge")
                    continue
                self._merge(_join(path, str(k)), old, str(k), v)
            return
        if isinstance(old, list) and isinstance(new, list):
            self._merge_list(path, parent, key, old, new)
            return
        if old == new:
            return
        node = _find_node(compose(self.text), path)
        if _sf_tagged(self.text, node):
            self._rec("kept", path, old, new, note="seed-fix [SF-..] value")
            return
        if self._op("set", path, new):
            parent[key] = copy.deepcopy(new)
            self._rec("set", path, old, new)

    def _merge_list(self, path: str, parent: dict[str, Any], key: str, old: list[Any], new: list[Any]) -> None:
        if old == new:
            return
        if not old:
            if self._op("set", path, new):
                parent[key] = copy.deepcopy(new)
                self._rec("replace", path, old, new)
            return
        if all(not isinstance(x, dict | list) for x in new) and all(not isinstance(x, dict | list) for x in old):
            for v in new:
                if v not in old and self._op("append", path, v):
                    old.append(v)
                    self._rec("append", f"{path}[+{v}]", None, v)
            return
        lk = _list_key(path, new)
        if lk is None or _list_key(path, old) != lk:
            if self._replace(path, new):
                parent[key] = copy.deepcopy(new)
                self._rec("replace", path, f"{len(old)} items", f"{len(new)} items", note="unkeyed list replaced")
            return
        last_idx = -1  # policy index of the previous snippet item (insertion anchor)
        for item in new:
            ident = _key_of(item, lk)
            idx = -1
            if ident is not None:
                idx = next((i for i, o in enumerate(old) if isinstance(o, dict) and _key_of(o, lk) == ident), -1)
            elif item in old:
                idx = old.index(item)
            if idx >= 0:
                ipath = f"{path}{_sel(lk, old[idx], old, idx)}" if ident is not None else f"{path}[{idx}]"
                for k, v in item.items():
                    if lk and k in lk:
                        continue
                    self._merge(_join(ipath, str(k)), old[idx], str(k), v)
                last_idx = idx
                continue
            label = f"{path}[{'/'.join(x for x in ident if x != 'null')}]" if ident else f"{path}[+]"
            pos = last_idx if last_idx >= 0 else len(old) - 1
            try:
                self.text = _insert_seq_item(self.text, path, pos, item)
            except Exception as exc:
                self.errors.append(f"{self.snippet}: {label}: {exc}")
                self._rec("error", label, note=str(exc))
                continue
            old.insert(pos + 1, copy.deepcopy(item))
            last_idx = pos + 1
            self._rec("add", label, None, ident)

    def _replace(self, path: str, value: list[Any]) -> bool:
        try:
            self.text = _replace_seq(self.text, path, value)
            return True
        except Exception as exc:
            self.errors.append(f"{self.snippet}: {path}: {exc}")
            self._rec("error", path, note=str(exc))
            return False


def load_snippets(snippets_dir: Path, only: list[str] | None = None) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for f in sorted(snippets_dir.glob("*.yaml")):
        if only and f.name not in only and f.stem not in only:
            continue
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict) and data:
            out.append((f.name, data))
    return out


def merge_text(policy_text: str, snippets: list[tuple[str, dict[str, Any]]]) -> MergeResult:
    m = _Merger(policy_text)
    for name, data in snippets:
        try:
            m.merge_snippet(name, data)
        except Exception as exc:  # keep going: report and continue with the next snippet
            m.errors.append(f"{name}: merge failed: {exc}")
    return MergeResult(text=m.text, items=m.items, errors=m.errors)


def validate_merged(text: str, policy_path: Path) -> tuple[list[str], list[str]]:
    from aegis.policy.profiles import ProfileSet
    from aegis.policy.validate import validate_text

    v = validate_text(text, profiles=ProfileSet.load(policy_path=policy_path))
    fmt = lambda i: (f"line {i.line} col {i.col}: " if i.line else "") + (f"{i.path}: " if i.path else "") + i.message  # noqa: E731
    return [fmt(e) for e in v.errors], [fmt(w) for w in v.warnings]


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.parent / f".{path.name}.tmp-{os.getpid()}"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m aegis.policy.snippets", description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=["check", "merge"])
    ap.add_argument("--policy", default=os.environ.get("AEGIS_POLICY") or str(REPO_ROOT / "config" / "policy.yaml"))
    ap.add_argument("--snippets", default=str(REPO_ROOT / "config" / "snippets"))
    ap.add_argument("--only", default="", help="comma-separated snippet file names / stems")
    ap.add_argument("--dry-run", action="store_true", help="merge: do not write anything")
    ap.add_argument("--no-golden", action="store_true", help="merge: do not copy the result to policy.golden.yaml")
    ap.add_argument("--force", action="store_true", help="merge: write even if validation reports errors")
    ap.add_argument("--diff", action="store_true", help="print the unified diff of the merged policy")
    ap.add_argument("--report", default="", help="write a JSON report here")
    args = ap.parse_args(argv)

    policy_path = Path(args.policy)
    text = policy_path.read_text(encoding="utf-8")
    snippets = load_snippets(Path(args.snippets), [s.strip() for s in args.only.split(",") if s.strip()] or None)
    res = merge_text(text, snippets)
    errors, warnings = validate_merged(res.text, policy_path)

    print(f"policy: {policy_path}  snippets: {len(snippets)}  ({', '.join(n for n, _ in snippets) or '-'})")
    groups = res.by_snippet()
    for name, _ in snippets:
        items = groups.get(name, [])
        changed = [i for i in items if i.kind not in ("kept", "skipped")]
        print(f"\n== {name}: {len(changed)} change(s)" + (f", {len(items) - len(changed)} kept/skipped" if len(items) != len(changed) else "")
              + ("" if items else " (already merged)"))
        for it in items:
            print("   " + it.line())
    if res.errors:
        print("\nmerge errors (manual merge needed):")
        for e in res.errors:
            print("   x " + e)
    if errors:
        print("\nvalidation errors in the merged policy:")
        for e in errors[:30]:
            print("   x " + e)
    if warnings:
        print(f"\nvalidation warnings: {len(warnings)}")
        for w in warnings[:15]:
            print("   - " + w)
    if args.diff and res.text != text:
        from aegis.policy.diff import unified_diff

        print("\n" + unified_diff(text, res.text, "policy.yaml", "policy.yaml (merged)"))
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps({
            "policy": str(policy_path), "snippets": [n for n, _ in snippets],
            "items": [it.__dict__ for it in res.items], "merge_errors": res.errors,
            "validation_errors": errors, "validation_warnings": warnings, "changed": res.changed,
        }, indent=2, default=str), encoding="utf-8")

    summary = f"\n{res.changed} change(s), {len(res.errors)} merge error(s), {len(errors)} validation error(s)"
    if args.command == "check":
        print(summary + " - check only, nothing written")
        return 1 if (errors or res.errors) else 0
    if errors and not args.force:
        print(summary + " - NOT written (fix the errors or use --force)")
        return 1
    if args.dry_run or res.text == text:
        print(summary + (" - dry run, nothing written" if args.dry_run else " - policy already up to date"))
        return 1 if res.errors else 0
    _atomic_write(policy_path, res.text)
    msg = f" - wrote {policy_path}"
    if not args.no_golden:
        golden = policy_path.parent / "policy.golden.yaml"
        _atomic_write(golden, res.text)
        msg += f" and {golden.name}"
    print(summary + msg)
    print("next: a running gateway hot-reloads it (or POST /api/policy/reload); "
          "run `uv run --frozen python -m aegis selftest` to check the inline tests")
    return 1 if res.errors else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
