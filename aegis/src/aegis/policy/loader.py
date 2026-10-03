"""Fast, safe YAML parsing for the policy file with 1-based line/col positions.

`parse_yaml(text)` composes the document once with PyYAML's C parser (`CSafeLoader`, falling
back to the pure-Python `SafeLoader`), checks size / alias / depth limits on the node tree,
reports duplicate keys as warnings (last one wins, like PyYAML) and then constructs plain
Python data from the same node tree. `LineIndex.locate(loc)` maps a pydantic-style location
tuple (`("controls", 3, "threshold")`) to the position of that node in the source text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from aegis.core.policy_schema import ValidationIssue

try:  # libyaml is present in the scaffold venv; keep a pure-Python fallback anyway
    _Loader: type = yaml.CSafeLoader
except AttributeError:  # pragma: no cover
    _Loader = yaml.SafeLoader

MAX_BYTES = 2 * 1024 * 1024
MAX_ALIASES = 100
MAX_DEPTH = 64


class PolicyParseError(ValueError):
    def __init__(self, issues: list[ValidationIssue]):
        super().__init__("; ".join(i.message for i in issues))
        self.issues = issues


@dataclass
class LineIndex:
    """Locates nodes of the composed YAML tree by a path of keys / list indices."""

    root: Node | None

    def node_at(self, loc: tuple[Any, ...] | list[Any]) -> tuple[Node | None, Node | None]:
        """(deepest node reached, key node of the last mapping step if any)."""
        node = self.root
        key_node: Node | None = None
        for part in loc:
            if node is None:
                break
            if isinstance(node, MappingNode):
                found = None
                for k, v in node.value:
                    if isinstance(k, ScalarNode) and str(k.value) == str(part):
                        found = (k, v)
                if found is None:
                    break
                key_node, node = found
            elif isinstance(node, SequenceNode):
                if isinstance(part, int) and 0 <= part < len(node.value):
                    node = node.value[part]
                    key_node = None
                else:
                    break
            else:
                break
        return node, key_node

    def locate(self, loc: tuple[Any, ...] | list[Any], *, prefer_key: bool = False) -> tuple[int | None, int | None]:
        node, key_node = self.node_at(loc)
        target = key_node if (prefer_key and key_node is not None) else node
        if target is None:
            return None, None
        mark = target.start_mark
        return mark.line + 1, mark.column + 1


@dataclass
class ParsedYaml:
    raw: Any
    index: LineIndex
    warnings: list[ValidationIssue] = field(default_factory=list)


def _issue_from_marked(exc: yaml.MarkedYAMLError) -> ValidationIssue:
    mark = exc.problem_mark or exc.context_mark
    problem = exc.problem or "invalid YAML"
    msg = problem if not exc.context else f"{problem} ({exc.context})"
    if mark is None:
        return ValidationIssue(message=msg)
    return ValidationIssue(line=mark.line + 1, col=mark.column + 1, message=msg)


def _path_str(path: list[Any]) -> str:
    out = ""
    for p in path:
        if isinstance(p, int):
            out += f"[{p}]"
        else:
            out += ("." if out else "") + str(p)
    return out


def _check_tree(root: Node) -> list[ValidationIssue]:
    """Alias count, depth and duplicate keys. Never recurses into an already-visited node,
    so alias bombs cost O(nodes) here and are rejected before construction."""
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    seen: set[int] = set()
    aliases = 0
    stack: list[tuple[Node, int, list[Any]]] = [(root, 1, [])]
    while stack:
        node, depth, path = stack.pop()
        if id(node) in seen:
            aliases += 1
            if aliases > MAX_ALIASES:
                m = node.start_mark
                errors.append(ValidationIssue(line=m.line + 1, col=m.column + 1,
                                              message=f"too many YAML aliases (> {MAX_ALIASES})"))
                return errors
            continue
        seen.add(id(node))
        if depth > MAX_DEPTH:
            m = node.start_mark
            errors.append(ValidationIssue(line=m.line + 1, col=m.column + 1,
                                          message=f"YAML nesting deeper than {MAX_DEPTH} levels"))
            return errors
        if isinstance(node, MappingNode):
            keys: dict[str, Node] = {}
            for k, v in node.value:
                if isinstance(k, ScalarNode):
                    if k.value in keys and k.value != "<<":
                        m = k.start_mark
                        warnings.append(ValidationIssue(
                            path=_path_str([*path, k.value]), line=m.line + 1, col=m.column + 1,
                            severity="warning",
                            message=f"duplicate key '{k.value}' (the last one wins)"))
                    keys[k.value] = v
                    stack.append((v, depth + 1, [*path, k.value]))
                else:
                    stack.append((k, depth + 1, path))
                    stack.append((v, depth + 1, path))
        elif isinstance(node, SequenceNode):
            for i, item in enumerate(node.value):
                stack.append((item, depth + 1, [*path, i]))
    return errors + warnings


def parse_yaml(text: str) -> ParsedYaml:
    """Parse policy YAML. Raises PolicyParseError(issues) on syntax errors or limit breaches."""
    if len(text.encode("utf-8", errors="replace")) > MAX_BYTES:
        raise PolicyParseError([ValidationIssue(message=f"policy file larger than {MAX_BYTES // 1024} KB")])
    loader = _Loader(text)
    try:
        try:
            root = loader.get_single_node()
        except yaml.MarkedYAMLError as exc:
            raise PolicyParseError([_issue_from_marked(exc)]) from None
        except yaml.YAMLError as exc:
            raise PolicyParseError([ValidationIssue(message=f"invalid YAML: {exc}")]) from None
        if root is None:
            return ParsedYaml(raw=None, index=LineIndex(None))
        issues = _check_tree(root)
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            raise PolicyParseError(errors)
        try:
            raw = loader.construct_document(root)
        except yaml.MarkedYAMLError as exc:
            raise PolicyParseError([_issue_from_marked(exc)]) from None
        except (yaml.YAMLError, RecursionError, ValueError, TypeError) as exc:
            raise PolicyParseError([ValidationIssue(message=f"invalid YAML: {exc}")]) from None
        return ParsedYaml(raw=raw, index=LineIndex(root), warnings=[i for i in issues if i.severity == "warning"])
    finally:
        loader.dispose()


def compose(text: str) -> Node | None:
    """Compose only (node tree with marks); used by the textual patcher."""
    loader = _Loader(text)
    try:
        return loader.get_single_node()
    finally:
        loader.dispose()
