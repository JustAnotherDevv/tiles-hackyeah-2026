"""Comment-preserving patch applier for config/policy.yaml.

`apply_patch_text(text, ops)` applies `PatchOp`s (set | append | remove) to the YAML text.

Path grammar (consumed by budgets-ledger, BUD-01 drafts, dashboard):
    dotted keys; `[3]` = list index; `[k=v]` / `[k1=v1,k2=v2]` = first list item whose every
    `str(item[k]) == v`. `set` through a non-matching selector in a list of mappings UPSERTS
    (appends `{k1: v1, ...}` then sets the rest of the path) -> `budget.add`.
    `append` targets a list (created if missing); `remove` deletes a key or a list item.
Examples:
    {op: set,    path: "budgets.limits[scope=team:trading,window=day].usd", value: 75}
    {op: append, path: "budgets.kill_switch.agents", value: "chaos-agent@platform"}
    {op: set,    path: "controls[id=DLP-02].enabled", value: false}
    {op: set,    path: "destinations.matrix.CONFIDENTIAL.remote", value: block}

Strategy: a *surgical textual* edit located with PyYAML node marks (exact character offsets),
so everything outside the edited value stays byte-identical (comments, alignment, flow style,
blank lines). Every edit is verified by re-parsing; if a textual edit is not possible or does
not verify, the op falls back to a ruamel.yaml round-trip (comments survive, formatting of
flow collections may be normalized).
"""

from __future__ import annotations

import io
import json
import re
from collections.abc import Iterable
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from aegis.core.policy_schema import PatchOp
from aegis.policy.loader import compose


class PatchError(ValueError):
    def __init__(self, path: str, message: str):
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


class _Missing:
    pass


MISSING = _Missing()

Token = tuple[str, Any]  # ("key", str) | ("index", int) | ("sel", dict[str, str])


# ---------------------------------------------------------------- path parsing
def parse_path(path: str) -> list[Token]:
    tokens: list[Token] = []
    i, n = 0, len(path)
    buf = ""

    def flush() -> None:
        nonlocal buf
        if buf:
            tokens.append(("key", buf))
            buf = ""

    while i < n:
        ch = path[i]
        if ch == ".":
            flush()
            i += 1
        elif ch == "[":
            flush()
            j = path.find("]", i)
            if j < 0:
                raise PatchError(path, "unclosed '['")
            inner = path[i + 1 : j].strip()
            if re.fullmatch(r"-?\d+", inner):
                tokens.append(("index", int(inner)))
            elif "=" in inner:
                sel: dict[str, str] = {}
                for part in inner.split(","):
                    if "=" not in part:
                        raise PatchError(path, f"bad selector part '{part}'")
                    k, v = part.split("=", 1)
                    sel[k.strip()] = v.strip()
                tokens.append(("sel", sel))
            else:
                raise PatchError(path, f"bad selector '[{inner}]'")
            i = j + 1
        else:
            buf += ch
            i += 1
    flush()
    if not tokens:
        raise PatchError(path, "empty path")
    return tokens


def _sel_match(item: Any, sel: dict[str, str]) -> bool:
    return isinstance(item, dict) and all(k in item and str(item[k]) == v for k, v in sel.items())


def get_path(data: Any, tokens: list[Token]) -> Any:
    cur = data
    for kind, val in tokens:
        if kind == "key":
            if not isinstance(cur, dict) or val not in cur:
                return MISSING
            cur = cur[val]
        elif kind == "index":
            if not isinstance(cur, list) or not -len(cur) <= val < len(cur):
                return MISSING
            cur = cur[val]
        else:
            if not isinstance(cur, list):
                return MISSING
            cur = next((x for x in cur if _sel_match(x, val)), MISSING)
            if cur is MISSING:
                return MISSING
    return cur


# ---------------------------------------------------------------- rendering
_PLAIN_OK = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-\.@/\*\+]*$")


def render_scalar(v: Any, *, style: str | None = None, flow: bool = True) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return ".nan" if v != v else (".inf" if v > 0 else "-.inf")
        r = repr(v)
        if "e" in r or "E" in r:
            r = f"{v:.12f}".rstrip("0")
            if r.endswith("."):
                r += "0"
        return r
    s = str(v)
    if style == "'":
        return "'" + s.replace("'", "''") + "'"
    if style == '"':
        return json.dumps(s, ensure_ascii=False)
    if _PLAIN_OK.match(s):
        try:
            if yaml.safe_load(s) == s:
                return s
        except yaml.YAMLError:
            pass
    return json.dumps(s, ensure_ascii=False)


def render_flow(v: Any) -> str:
    if isinstance(v, dict):
        return "{" + ", ".join(f"{render_scalar(str(k))}: {render_flow(x)}" for k, x in v.items()) + "}"
    if isinstance(v, list | tuple):
        return "[" + ", ".join(render_flow(x) for x in v) + "]"
    return render_scalar(v)


# ---------------------------------------------------------------- textual engine
class _NoText(Exception):
    """Textual edit not possible -> ruamel fallback."""


def _node_end_line(text: str, node: Node) -> int:
    """Index just after the newline that ends the last line of `node`."""
    end = node.end_mark.index
    if node.end_mark.column == 0 and end > 0 and text[end - 1] == "\n":
        # block collections end at the start of the following line; walk back over blank lines
        k = end
        while k > 0 and text[k - 1] == "\n" and k - 2 >= 0 and text[k - 2] == "\n":
            k -= 1
        return k
    nl = text.find("\n", end)
    return len(text) if nl < 0 else nl + 1


def _line_start(text: str, idx: int) -> int:
    return text.rfind("\n", 0, idx) + 1


def _single_line(node: Node) -> bool:
    return node.start_mark.line == node.end_mark.line or (
        node.end_mark.column == 0 and node.end_mark.line == node.start_mark.line + 1)


def _find_item(seq: SequenceNode, sel: dict[str, str]) -> int:
    for i, item in enumerate(seq.value):
        if isinstance(item, MappingNode):
            vals = {k.value: v for k, v in item.value if isinstance(k, ScalarNode)}
            if all(isinstance(vals.get(k), ScalarNode) and str(vals[k].value) == v for k, v in sel.items()):
                return i
    return -1


def _map_get(node: MappingNode, key: str) -> tuple[ScalarNode, Node] | None:
    found = None
    for k, v in node.value:
        if isinstance(k, ScalarNode) and str(k.value) == key:
            found = (k, v)
    return found


def _coerce_sel_value(v: str) -> Any:
    try:
        parsed = yaml.safe_load(v)
    except yaml.YAMLError:
        return v
    return parsed if isinstance(parsed, int | float) and not isinstance(parsed, bool) else v


def _nest(tokens: list[Token], value: Any) -> Any:
    out = value
    for kind, val in reversed(tokens):
        if kind != "key":
            raise _NoText()
        out = {val: out}
    return out


def _insert_into_mapping(text: str, mapping: MappingNode, key: str, value: Any) -> str:
    entry = f"{render_scalar(key)}: {render_flow(value)}"
    if mapping.flow_style:
        close = mapping.end_mark.index - 1
        if text[close] != "}":
            raise _NoText()
        if mapping.value:
            return text[:close].rstrip(" ") + f", {entry}" + text[close:]
        return text[:close] + entry + text[close:]
    if not mapping.value:
        raise _NoText()
    indent = mapping.value[0][0].start_mark.column
    # insert after the last leading run of single-line entries (keeps `tests:` blocks last)
    anchor: Node | None = None
    for _k, v in mapping.value:
        if not _single_line(v) or (isinstance(v, MappingNode | SequenceNode) and not v.flow_style):
            break
        anchor = v
    if anchor is None:
        anchor = mapping.value[-1][1]
    pos = _node_end_line(text, anchor)
    return text[:pos] + " " * indent + entry + "\n" + text[pos:]


def _append_to_seq(text: str, seq: SequenceNode, value: Any) -> str:
    rendered = render_flow(value)
    if seq.flow_style:
        close = seq.end_mark.index - 1
        if text[close] != "]":
            raise _NoText()
        if seq.value:
            return text[:close].rstrip(" ") + f", {rendered}" + text[close:]
        return text[:close] + rendered + text[close:]
    if not seq.value:
        raise _NoText()
    first = seq.value[0]
    dash = text.rfind("-", _line_start(text, first.start_mark.index), first.start_mark.index)
    if dash < 0:
        raise _NoText()
    dash_col = dash - _line_start(text, dash)
    pos = _node_end_line(text, seq.value[-1])
    return text[:pos] + " " * dash_col + "- " + rendered + "\n" + text[pos:]


def _remove_span_flow(text: str, start: int, end: int) -> str:
    """Remove [start, end) from a flow collection together with one adjacent comma."""
    j = end
    while j < len(text) and text[j] in " \t":
        j += 1
    if j < len(text) and text[j] == ",":
        j += 1
        while j < len(text) and text[j] in " \t":
            j += 1
        return text[:start] + text[j:]
    i = start
    while i > 0 and text[i - 1] in " \t":
        i -= 1
    if i > 0 and text[i - 1] == ",":
        return text[: i - 1] + text[end:]
    return text[:start] + text[end:]


def _textual(text: str, op: PatchOp, tokens: list[Token]) -> str:
    root = compose(text)
    if root is None:
        raise _NoText()
    node: Node = root
    parents: list[tuple[Node, Token, Node | None]] = []  # (container, token, key node)
    for ti, tok in enumerate(tokens):
        kind, val = tok
        last = ti == len(tokens) - 1
        if kind == "key":
            if not isinstance(node, MappingNode):
                raise PatchError(op.path, f"'{val}' is not inside a mapping")
            hit = _map_get(node, val)
            if hit is None:
                if op.op == "remove":
                    raise PatchError(op.path, f"key '{val}' not found")
                rest = tokens[ti + 1 :]
                if op.op == "append":
                    if rest:
                        return _insert_into_mapping(text, node, val, _nest(rest, [op.value]))
                    return _insert_into_mapping(text, node, val, [op.value])
                return _insert_into_mapping(text, node, val, _nest(rest, op.value))
            parents.append((node, tok, hit[0]))
            node = hit[1]
        elif kind == "index":
            if not isinstance(node, SequenceNode) or not -len(node.value) <= val < len(node.value):
                raise PatchError(op.path, f"index [{val}] out of range")
            parents.append((node, tok, None))
            node = node.value[val]
        else:
            if not isinstance(node, SequenceNode):
                raise PatchError(op.path, f"selector {val} used on a non-list")
            idx = _find_item(node, val)
            if idx < 0:
                if op.op == "remove":
                    raise PatchError(op.path, f"no list item matches {val}")
                rest = tokens[ti + 1 :]
                item: dict[str, Any] = {k: _coerce_sel_value(v) for k, v in val.items()}
                tail = [op.value] if op.op == "append" else op.value
                if rest:
                    nested = _nest(rest, tail)
                    if not isinstance(nested, dict):
                        raise _NoText()
                    item.update(nested)
                elif op.op == "set" and isinstance(op.value, dict):
                    item.update(op.value)
                return _append_to_seq(text, node, item)
            parents.append((node, tok, None))
            node = node.value[idx]
        _ = last

    container, tok, key_node = parents[-1] if parents else (None, None, None)
    if op.op == "set":
        if isinstance(node, ScalarNode) and not isinstance(op.value, dict | list):
            style = node.style if node.style in ('"', "'") and isinstance(op.value, str) else None
            new = render_scalar(op.value, style=style)
            return text[: node.start_mark.index] + new + text[node.end_mark.index :]
        if isinstance(node, ScalarNode) or (isinstance(node, MappingNode | SequenceNode) and node.flow_style):
            return text[: node.start_mark.index] + render_flow(op.value) + text[node.end_mark.index :]
        raise _NoText()
    if op.op == "append":
        if not isinstance(node, SequenceNode):
            if isinstance(node, ScalarNode) and node.value in ("", "null", "~"):
                return text[: node.start_mark.index] + render_flow([op.value]) + text[node.end_mark.index :]
            raise PatchError(op.path, "append target is not a list")
        return _append_to_seq(text, node, op.value)
    if op.op == "remove":
        if container is None:
            raise PatchError(op.path, "cannot remove the document root")
        if isinstance(container, MappingNode):
            assert key_node is not None
            if container.flow_style:
                return _remove_span_flow(text, key_node.start_mark.index, node.end_mark.index)
            start = _line_start(text, key_node.start_mark.index)
            if text[start:key_node.start_mark.index].strip() not in ("", "-"):
                raise _NoText()
            if text[start:key_node.start_mark.index].strip() == "-":
                raise _NoText()  # first key of a block list item: ruamel handles it
            return text[:start] + text[_node_end_line(text, node):]
        if isinstance(container, SequenceNode):
            if container.flow_style:
                return _remove_span_flow(text, node.start_mark.index, node.end_mark.index)
            start = _line_start(text, node.start_mark.index)
            if text[start:node.start_mark.index].strip() != "-":
                raise _NoText()
            return text[:start] + text[_node_end_line(text, node):]
    raise _NoText()


# ---------------------------------------------------------------- ruamel fallback
def _ruamel_yaml() -> Any:
    from ruamel.yaml import YAML

    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _ruamel_apply(text: str, op: PatchOp, tokens: list[Token]) -> str:
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    y = _ruamel_yaml()
    data = y.load(text)
    cur: Any = data
    for ti, (kind, val) in enumerate(tokens):
        last = ti == len(tokens) - 1
        if kind == "key":
            if not isinstance(cur, dict):
                raise PatchError(op.path, f"'{val}' is not inside a mapping")
            if last:
                if op.op == "set":
                    cur[val] = op.value
                elif op.op == "append":
                    if val not in cur or cur[val] is None:
                        cur[val] = CommentedSeq()
                    if not isinstance(cur[val], list):
                        raise PatchError(op.path, "append target is not a list")
                    cur[val].append(op.value)
                else:
                    if val not in cur:
                        raise PatchError(op.path, f"key '{val}' not found")
                    del cur[val]
                break
            if val not in cur:
                if op.op == "remove":
                    raise PatchError(op.path, f"key '{val}' not found")
                cur[val] = CommentedMap() if tokens[ti + 1][0] == "key" else CommentedSeq()
            cur = cur[val]
        elif kind == "index":
            if not isinstance(cur, list) or not -len(cur) <= val < len(cur):
                raise PatchError(op.path, f"index [{val}] out of range")
            if last:
                if op.op == "set":
                    cur[val] = op.value
                elif op.op == "remove":
                    del cur[val]
                else:
                    if not isinstance(cur[val], list):
                        raise PatchError(op.path, "append target is not a list")
                    cur[val].append(op.value)
                break
            cur = cur[val]
        else:
            if not isinstance(cur, list):
                raise PatchError(op.path, f"selector {val} used on a non-list")
            idx = next((i for i, x in enumerate(cur) if _sel_match(x, val)), -1)
            if idx < 0:
                if op.op == "remove":
                    raise PatchError(op.path, f"no list item matches {val}")
                item = CommentedMap((k, _coerce_sel_value(v)) for k, v in val.items())
                cur.append(item)
                idx = len(cur) - 1
            if last:
                if op.op == "set":
                    if isinstance(op.value, dict):
                        cur[idx].update(op.value)
                    else:
                        raise PatchError(op.path, "set on a selector needs a mapping value")
                elif op.op == "remove":
                    del cur[idx]
                else:
                    raise PatchError(op.path, "append target is not a list")
                break
            cur = cur[idx]
    buf = io.StringIO()
    y.dump(data, buf)
    return buf.getvalue()


# ---------------------------------------------------------------- public API
def _verify(text: str, op: PatchOp, tokens: list[Token]) -> bool:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return False
    got = get_path(data, tokens)
    if op.op == "set":
        return got == op.value or (isinstance(op.value, dict) and isinstance(got, dict)
                                   and all(got.get(k) == v for k, v in op.value.items()))
    if op.op == "append":
        return isinstance(got, list) and len(got) > 0 and got[-1] == op.value
    return True


def apply_op(text: str, op: PatchOp) -> str:
    tokens = parse_path(op.path)
    try:
        before = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PatchError(op.path, f"current policy is not valid YAML: {exc}") from None
    if op.op == "remove" and get_path(before, tokens) is MISSING:
        raise PatchError(op.path, "nothing to remove at this path")
    try:
        out = _textual(text, op, tokens)
        if _verify(out, op, tokens) and (op.op != "remove" or get_path(yaml.safe_load(out), tokens) is MISSING
                                         or tokens[-1][0] == "sel"):
            return out
    except _NoText:
        pass
    except PatchError:
        raise
    except Exception:  # pragma: no cover - any textual surprise -> ruamel
        pass
    out = _ruamel_apply(text, op, tokens)
    if not _verify(out, op, tokens):
        raise PatchError(op.path, "patch did not produce the expected value")
    return out


def apply_patch_text(text: str, ops: Iterable[PatchOp | dict[str, Any]]) -> str:
    """Apply ops in order; raises PatchError(path, message). No ops -> text unchanged."""
    for raw_op in ops:
        op = raw_op if isinstance(raw_op, PatchOp) else PatchOp.model_validate(raw_op)
        if op.op not in ("set", "append", "remove"):
            raise PatchError(op.path, f"unknown op '{op.op}'")
        text = apply_op(text, op)
    return text
