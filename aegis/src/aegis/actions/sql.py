"""Lightweight SQL analyzer for the data access guard (ctl ACT-02) and EXE-01 ``drop_table``.

Not a full parser: a quote/comment-aware scanner plus targeted patterns, enough for agent SQL
(stacked queries, ``/**/`` comments, quoted identifiers, ``schema.table``, CTEs, UNION,
literals that merely *mention* ``drop table``). Pure and synchronous; never raises.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

OP_RANK = {"other": -1, "read": 0, "write": 1, "delete": 2, "ddl": 3, "dcl": 3}

_DDL_VERBS = {"DROP", "ALTER", "TRUNCATE", "CREATE", "RENAME", "COMMENT"}
_DCL_VERBS = {"GRANT", "REVOKE"}
_WRITE_VERBS = {"INSERT", "UPDATE", "MERGE", "REPLACE", "UPSERT", "COPY", "CALL", "EXEC", "EXECUTE", "DO", "LOAD"}
_READ_VERBS = {"SELECT", "SHOW", "EXPLAIN", "DESCRIBE", "DESC", "PRAGMA", "VALUES", "TABLE"}
_NOOP_VERBS = {"BEGIN", "COMMIT", "ROLLBACK", "SET", "START", "END", "USE", "SAVEPOINT", "RELEASE"}
_ALL_VERBS = _DDL_VERBS | _DCL_VERBS | _WRITE_VERBS | _READ_VERBS | _NOOP_VERBS | {"DELETE", "WITH"}

_AGG_FUNCS = {"count", "sum", "avg", "min", "max", "stddev", "variance", "median", "percentile_cont",
              "approx_count_distinct", "count_distinct", "bool_and", "bool_or", "every"}
_FROM_FUNCS = {"extract", "substring", "trim", "position", "overlay", "substr"}
_KEYWORDS = {
    "select", "from", "where", "and", "or", "not", "as", "on", "join", "left", "right", "inner", "outer",
    "full", "cross", "group", "by", "order", "having", "limit", "offset", "distinct", "all", "union",
    "case", "when", "then", "else", "end", "is", "null", "in", "like", "ilike", "between", "exists",
    "true", "false", "asc", "desc", "with", "recursive", "lateral", "natural", "using", "top", "into",
    "values", "set", "update", "delete", "insert", "interval", "cast", "over", "partition", "filter",
}

IDENT = r'(?:"[^"]+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$]*)'
QIDENT = rf"{IDENT}(?:\s*\.\s*{IDENT})*"
_TABLE_PATTERNS = [
    re.compile(rf"(?i)\b(?:from|join)\s+(?P<list>{QIDENT}(?:\s+(?:as\s+)?[A-Za-z_]\w*)?(?:\s*,\s*{QIDENT}(?:\s+(?:as\s+)?[A-Za-z_]\w*)?)*)"),
    re.compile(rf"(?i)\binto\s+(?P<one>{QIDENT})"),
    re.compile(rf"(?i)\bupdate\s+(?:only\s+)?(?P<one>{QIDENT})"),
    re.compile(rf"(?i)\btable\s+(?:if\s+(?:not\s+)?exists\s+)?(?:only\s+)?(?P<one>{QIDENT})"),
    re.compile(rf"(?i)\btruncate\s+(?:table\s+)?(?:only\s+)?(?P<one>{QIDENT})"),
    re.compile(rf"(?i)\b(?:view|index)\s+(?:if\s+(?:not\s+)?exists\s+)?{QIDENT}\s+on\s+(?P<one>{QIDENT})"),
    re.compile(rf"(?i)\bcopy\s+(?P<one>{QIDENT})"),
    re.compile(rf"(?i)\b(?:grant|revoke)\b[^;]*?\bon\s+(?:table\s+)?(?P<one>{QIDENT})"),
]
_CTE_RX = re.compile(rf"(?i)(?:\bwith\s+(?:recursive\s+)?|,\s*)(?P<name>{IDENT})\s*(?:\([^)]*\))?\s+as\s+(?:not\s+)?(?:materialized\s+)?\(")
_WORD_RX = re.compile(r"[A-Za-z_][\w$]*")


@dataclass
class SqlStatement:
    verb: str
    operation: str
    tables: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    select_star: bool = False
    aggregate_only: bool = False
    group_by: bool = False
    limit: int | None = None
    has_where: bool = False
    unbounded_write: bool = False
    ddl_verbs: list[str] = field(default_factory=list)


@dataclass
class SqlAnalysis:
    ok: bool
    error: str | None = None
    statements: list[SqlStatement] = field(default_factory=list)
    operation: str = "other"
    verbs: list[str] = field(default_factory=list)
    ddl_verbs: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    select_star: bool = False
    aggregate_only: bool = False
    limit: int | None = None
    has_where: bool = False
    unbounded_write: bool = False
    rows: int | None = None  # estimated rows for reads: LIMIT n / 1 for a plain aggregate / None = unbounded

    @property
    def stacked(self) -> bool:
        return len(self.statements) > 1

    def summary(self) -> str:
        """Op + tables, never literals (privacy)."""
        tables = ", ".join(self.tables[:4]) or "?"
        verbs = "+".join(dict.fromkeys(self.verbs)) or "?"
        return f"{verbs} on {tables}"


def mask_sql(sql: str) -> str:
    """Remove comments and blank out string literals (keeps quoted identifiers)."""
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j
            out.append(" ")
        elif c == "#" and (i == 0 or sql[i - 1] in " \t\n;"):
            j = sql.find("\n", i)  # MySQL comment
            i = n if j == -1 else j
            out.append(" ")
        elif c == "/" and sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j == -1 else j + 2
            out.append(" ")
        elif c == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'" and j + 1 < n and sql[j + 1] == "'":
                    j += 2
                    continue
                if sql[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if sql[j] == "'":
                    break
                j += 1
            out.append("''")
            i = j + 1
        elif c == "$":
            m = re.match(r"\$([A-Za-z_]\w*)?\$", sql[i:])
            if m:
                tag = m.group(0)
                j = sql.find(tag, i + len(tag))
                out.append("''")
                i = n if j == -1 else j + len(tag)
            else:
                out.append(c)
                i += 1
        elif c in '"`':
            j = sql.find(c, i + 1)
            j = n - 1 if j == -1 else j
            out.append(sql[i : j + 1])
            i = j + 1
        elif c == "[":
            j = sql.find("]", i + 1)
            j = n - 1 if j == -1 else j
            out.append(sql[i : j + 1])
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _split(masked: str) -> list[str]:
    parts, buf, quote = [], [], None
    for ch in masked:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in '"`':
            quote = ch
            buf.append(ch)
        elif ch == ";":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p for p in (x.strip() for x in parts) if p]


def _depths(s: str) -> list[int]:
    d, out = 0, []
    for ch in s:
        if ch == "(":
            d += 1
            out.append(d)
            continue
        out.append(d)
        if ch == ")":
            d = max(0, d - 1)
    return out


def _unquote(ident: str) -> str:
    parts = [p.strip().strip('"`[]') for p in re.split(r"\s*\.\s*", ident.strip())]
    return ".".join(p for p in parts if p).lower()


def _enclosing_func(s: str, pos: int) -> str | None:
    """Name of the function whose parentheses enclose ``pos`` (e.g. ``extract``)."""
    depth = 0
    for i in range(pos - 1, -1, -1):
        ch = s[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth == 0:
                m = re.search(r"([A-Za-z_]\w*)\s*$", s[:i])
                return m.group(1).lower() if m else ""
            depth -= 1
    return None


def _tables(stmt: str, ctes: set[str]) -> list[str]:
    found: list[str] = []
    for rx in _TABLE_PATTERNS:
        for m in rx.finditer(stmt):
            func = _enclosing_func(stmt, m.start())
            if func and func in _FROM_FUNCS:
                continue  # EXTRACT(YEAR FROM col), SUBSTRING(x FROM 2) ...
            grp = "list" if m.groupdict().get("list") else "one"
            if re.match(r"\s*\(", stmt[m.end(grp) :]) and "," not in m.group(grp):
                continue  # FROM generate_series(...), INSERT INTO t(cols) handled below
            for it in re.split(r"\s*,\s*", m.group(grp)):
                name = re.match(QIDENT, it.strip())
                if name:
                    found.append(_unquote(name.group(0)))
    # INSERT INTO t (cols) / COPY t (cols): the table is followed by a column list
    for m in re.finditer(rf"(?i)\b(?:into|copy)\s+(?P<one>{QIDENT})\s*\(", stmt):
        found.append(_unquote(m.group("one")))
    out: list[str] = []
    for t in found:
        short = t.rsplit(".", 1)[-1]
        if not t or short in _KEYWORDS or t in ctes or short in ctes or t in out:
            continue
        out.append(t)
    return out


def _select_list(stmt: str, depths: list[int]) -> tuple[str | None, int]:
    """Text of the top-level SELECT list and the index where it ends."""
    for m in re.finditer(r"(?i)\bselect\b", stmt):
        if depths[m.start()] != 0:
            continue
        start = m.end()
        for f in re.finditer(r"(?i)\bfrom\b", stmt[start:]):
            pos = start + f.start()
            if depths[pos] == 0 and not _enclosing_func(stmt, pos):
                return stmt[start:pos], pos
        return stmt[start:], len(stmt)
    return None, 0


def _split_top(s: str) -> list[str]:
    out, buf, d = [], [], 0
    for ch in s:
        if ch == "(":
            d += 1
        elif ch == ")":
            d = max(0, d - 1)
        if ch == "," and d == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [x.strip() for x in out if x.strip()]


def _columns(select_list: str) -> tuple[list[str], bool, bool]:
    s = re.sub(r"(?i)^\s*(distinct(\s+on\s*\([^)]*\))?|all|top\s+\d+)\s+", "", select_list)
    cols: list[str] = []
    star = False
    agg_flags: list[bool] = []
    for expr in _split_top(s):
        e = expr.strip()
        e_noalias = re.sub(r"(?i)\s+as\s+[\w\"`]+\s*$", "", e)
        if re.fullmatch(r"(?:[\w\"`]+\s*\.\s*)?\*", e_noalias.strip()):
            star = True
            agg_flags.append(False)
            continue
        m = re.match(r"\s*([A-Za-z_]\w*)\s*\(", e_noalias)
        agg_flags.append(bool(m and m.group(1).lower() in _AGG_FUNCS))
        for w in _WORD_RX.finditer(e_noalias):
            word = w.group(0)
            after = e_noalias[w.end() : w.end() + 2].lstrip()
            if after.startswith("("):
                continue  # function name
            if word.lower() in _KEYWORDS:
                continue
            nxt = e_noalias[w.end() :]
            if nxt.startswith("."):
                continue  # table qualifier
            if word.lower() not in cols:
                cols.append(word.lower())
    aggregate_only = bool(agg_flags) and all(agg_flags)
    return cols, star, aggregate_only


def _verb(stmt: str, depths: list[int]) -> str | None:
    for m in _WORD_RX.finditer(stmt):
        if depths[m.start()] != 0:
            continue
        w = m.group(0).upper()
        if w == "WITH":
            continue
        if w in _ALL_VERBS:
            return w
    return None


def _operation_of(verb: str, stmt: str) -> tuple[str, list[str]]:
    ddl: list[str] = []
    for m in re.finditer(r"(?i)\b(drop|alter|truncate|create|rename|grant|revoke)\b", stmt):
        word = m.group(1).upper()
        tail = stmt[m.end() : m.end() + 40].lower()
        if word in ("CREATE", "ALTER", "DROP", "RENAME") and not re.match(
            r"\s+(or\s+replace\s+)?(temp(orary)?\s+)?(table|database|schema|index|view|column|user|role|function|procedure|trigger|materialized|sequence|extension|policy|type|unique)\b",
            tail,
        ):
            if word == verb:
                ddl.append(word)
            continue
        ddl.append(word)
    op = "other"
    if verb in _DCL_VERBS or any(v in _DCL_VERBS for v in ddl):
        op = "dcl"
    elif verb in _DDL_VERBS or ddl:
        op = "ddl"
    elif verb == "DELETE" or re.search(r"(?i)\bdelete\s+from\b", stmt):
        op = "delete"
    elif verb in _WRITE_VERBS or re.search(
        r"(?i)\b(insert\s+into|merge\s+into|replace\s+into|update\s+\S+\s+set)\b", stmt
    ):
        op = "write"
    elif verb in _READ_VERBS:
        op = "read"
    return op, list(dict.fromkeys(ddl))


def analyze_sql(sql: str, *, max_chars: int = 20_000) -> SqlAnalysis:
    """Analyze ``sql`` (possibly stacked). Never raises; ``ok=False`` when nothing parseable."""
    if not isinstance(sql, str) or not sql.strip():
        return SqlAnalysis(ok=False, error="empty SQL")
    text = sql if len(sql) <= max_chars else sql[: max_chars // 2] + " ; " + sql[-max_chars // 2 :]
    try:
        masked = mask_sql(text)
        stmts_txt = _split(masked)
    except Exception as exc:  # pragma: no cover - defensive
        return SqlAnalysis(ok=False, error=f"scan error: {type(exc).__name__}")
    res = SqlAnalysis(ok=True)
    for st in stmts_txt:
        depths = _depths(st)
        verb = _verb(st, depths)
        if verb is None:
            res.ok = False
            res.error = "unrecognized statement"
            continue
        if verb in _NOOP_VERBS:
            continue
        op, ddl = _operation_of(verb, st)
        ctes = {_unquote(m.group("name")) for m in _CTE_RX.finditer(st)} if re.match(r"(?is)\s*with\b", st) else set()
        s = SqlStatement(verb=verb, operation=op, tables=_tables(st, ctes), ddl_verbs=ddl)
        sel, _ = _select_list(st, depths)
        if sel is not None and op == "read":
            s.columns, s.select_star, s.aggregate_only = _columns(sel)
        s.group_by = bool(re.search(r"(?i)\bgroup\s+by\b", st))
        lim = [int(x) for x in re.findall(r"(?i)\b(?:limit|top|fetch\s+first)\s+(\d+)", st)]
        s.limit = lim[-1] if lim else None
        where = [m for m in re.finditer(r"(?i)\bwhere\b", st) if depths[m.start()] == 0]
        s.has_where = bool(where)
        tautology = bool(re.search(r"(?i)\bwhere\s+(1\s*=\s*1|true|''\s*=\s*''|1)\s*($|;|\)|\blimit\b|\border\b)", st))
        if op in ("write", "delete") and verb in ("UPDATE", "DELETE"):
            s.unbounded_write = not s.has_where or tautology
        res.statements.append(s)
    if not res.statements:
        if res.ok:
            res.ok = False
            res.error = res.error or "no statements"
        return res
    worst = max(res.statements, key=lambda x: OP_RANK.get(x.operation, -1))
    res.operation = worst.operation
    res.verbs = [x.verb for x in res.statements]
    res.ddl_verbs = list(dict.fromkeys(v for x in res.statements for v in x.ddl_verbs))
    for x in res.statements:
        for t in x.tables:
            if t not in res.tables:
                res.tables.append(t)
    reads = [x for x in res.statements if x.operation == "read"]
    res.columns = list(dict.fromkeys(c for x in reads for c in x.columns))
    res.select_star = any(x.select_star for x in reads)
    res.aggregate_only = bool(reads) and all(x.aggregate_only for x in reads)
    res.has_where = all(x.has_where for x in res.statements)
    res.unbounded_write = any(x.unbounded_write for x in res.statements)
    limits = [x.limit for x in reads]
    if reads and all(lim is not None for lim in limits):
        res.limit = max(lim for lim in limits if lim is not None)
        res.rows = res.limit
    elif reads and all(x.aggregate_only and not x.group_by for x in reads):
        res.rows = 1
    if res.ok is False and res.error is None:
        res.error = "unrecognized statement"
    return res


__all__ = ["OP_RANK", "SqlAnalysis", "SqlStatement", "analyze_sql", "mask_sql"]
