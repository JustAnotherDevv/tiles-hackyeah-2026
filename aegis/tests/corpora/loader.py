"""Corpus loader: schema-checked rows, PII fixtures, MANIFEST verification, attribution.

Public API (read-only for other workstreams):

    from tests.corpora.loader import CorpusRow, load_rows, load_pii, verify_manifest, attribution_lines

`load_rows()` returns the 1,194 committed rows (684 attack / 510 benign). The runtime-generated
secret cases are added with `subsets=[..., "secrets"]` and never touch the disk.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "MANIFEST.json"

LABELS = {"attack", "benign"}
LANGS = {"en", "pl", "de", "uk", "ru"}
SURFACES = {"user_prompt", "tool_input", "tool_result", "mcp_tool_description", "model_output"}
EXPECTED = {"block", "redact", "flag", "require_approval", "allow"}

SUBSET_DIRS = {"public": "public", "handwritten": "handwritten", "generated": "generated"}
ALL_SUBSETS = ("public", "handwritten", "generated", "pii", "secrets")
ROW_SUBSETS = ("public", "handwritten", "generated")
PII_FILES = ("positives_en", "positives_pl", "adversarial", "hard_negatives", "holdout")

# Files that injection-defense copies into its fixtures / tunes signatures on (plan 05 §3).
# Their numbers are reported as "tuning", never as held-out generalization.
SEEN_BY_TUNING = {
    "generated/obfuscation_matrix.jsonl": True,
    "handwritten/polish_multilingual.jsonl": True,
    "handwritten/finance_benign.jsonl": True,
    "handwritten/agentic_tools.jsonl": True,
    "public/indirect_injections.jsonl": True,
    "public/deepset_prompt_injections.jsonl": False,
    "public/lakera_gandalf.jsonl": False,
    "public/jailbreakbench_behaviors.jsonl": False,
    "public/xstest_safe.jsonl": False,
}

# Secret-scanner shapes that must never be committed (CONTRACTS §7.3, GitHub push protection).
SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p)
    for p in (
        r"AKIA[0-9A-Z]{16}",
        r"ghp_[A-Za-z0-9]{36}",
        r"github_pat_\w{20,}",
        r"sk_live_\w{10,}",
        r"rk_live_\w{10,}",
        r"sk-ant-[\w-]{10,}",
        r"sk-proj-[\w-]{10,}",
        r"xox[bpas]-",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"eyJ[\w-]+\.[\w-]+\.[\w-]+",
        r"AIza[0-9A-Za-z_-]{35}",
        r"glpat-[\w-]{10,}",
        r"npm_[A-Za-z0-9]{36}",
    )
]


def secret_hits(text: str) -> list[str]:
    """Return the patterns that match `text` (empty = clean)."""
    return [p.pattern for p in SECRET_PATTERNS if p.search(text)]


class CorpusRow(BaseModel):
    """One labelled case. Extra fields (tool, user_task, seed_id, ...) are kept."""

    model_config = ConfigDict(extra="allow")

    id: str
    text: str
    label: str
    category: str
    lang: str
    source: str
    licence: str
    expected_action: str
    notes: str = ""
    surface: str = "user_prompt"
    # loader-added provenance (not in the JSONL)
    file: str = ""
    subset: str = ""

    @field_validator("label")
    @classmethod
    def _label(cls, v: str) -> str:
        if v not in LABELS:
            raise ValueError(f"unknown label {v!r}")
        return v

    @field_validator("lang")
    @classmethod
    def _lang(cls, v: str) -> str:
        if v not in LANGS:
            raise ValueError(f"unknown lang {v!r}")
        return v

    @field_validator("surface")
    @classmethod
    def _surface(cls, v: str) -> str:
        if v not in SURFACES:
            raise ValueError(f"unknown surface {v!r}")
        return v

    @field_validator("expected_action")
    @classmethod
    def _expected(cls, v: str) -> str:
        if v not in EXPECTED:
            raise ValueError(f"unknown expected_action {v!r}")
        return v

    @property
    def top_category(self) -> str:
        return self.category.split(".")[0]

    @property
    def seen_by_tuning(self) -> bool:
        return bool(SEEN_BY_TUNING.get(self.file, self.subset in {"handwritten", "generated"}))

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, None) if key in type(self).model_fields else (
            (self.model_extra or {}).get(key, default)
        )


class PiiRow(BaseModel):
    """PII fixture row (staging/pii format): gold entities with offsets and values."""

    model_config = ConfigDict(extra="allow")

    id: str
    text: str
    lang: str = "en"
    entities: list[dict[str, Any]] = []
    expect: str = "redact"
    tags: list[str] = []
    file: str = ""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:  # pragma: no cover - data error
            raise ValueError(f"{path.name}:{n}: {e}") from e
    return out


def row_files(subsets: Iterable[str] = ROW_SUBSETS) -> list[Path]:
    files: list[Path] = []
    for s in subsets:
        d = SUBSET_DIRS.get(s)
        if d:
            files.extend(sorted((HERE / d).glob("*.jsonl")))
    return files


def load_rows(
    subsets: Iterable[str] | None = None,
    labels: Iterable[str] | None = None,
    langs: Iterable[str] | None = None,
) -> list[CorpusRow]:
    """Load labelled rows. Default subsets: public + handwritten + generated (1,194 rows).

    Pass "secrets" to append runtime-generated secret cases (in memory only).
    """
    subs = list(subsets) if subsets is not None else list(ROW_SUBSETS)
    want_labels = set(labels) if labels else None
    want_langs = set(langs) if langs else None
    rows: list[CorpusRow] = []
    seen: set[str] = set()
    for f in row_files([s for s in subs if s in SUBSET_DIRS]):
        rel = f.relative_to(HERE).as_posix()
        subset = rel.split("/")[0]
        for d in _read_jsonl(f):
            r = CorpusRow.model_validate({**d, "file": rel, "subset": subset})
            if r.id in seen:
                raise ValueError(f"duplicate id {r.id} in {rel}")
            seen.add(r.id)
            rows.append(r)
    if "secrets" in subs:
        from tests.corpora.secrets_gen import generate

        rows.extend(generate())
    if want_labels:
        rows = [r for r in rows if r.label in want_labels]
    if want_langs:
        rows = [r for r in rows if r.lang in want_langs]
    return rows


def load_pii(files: Iterable[str] = PII_FILES) -> list[PiiRow]:
    """PII fixtures with gold entities (secret-shaped rows were dropped at port time)."""
    out: list[PiiRow] = []
    for name in files:
        p = HERE / "pii" / f"{name}.jsonl"
        if not p.exists():
            continue
        for d in _read_jsonl(p):
            out.append(PiiRow.model_validate({**d, "file": f"pii/{name}.jsonl"}))
    return out


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_stats(path: Path) -> dict[str, Any]:
    rows = _read_jsonl(path)
    rel = path.relative_to(HERE).as_posix()
    attack = sum(1 for r in rows if r.get("label") == "attack")
    benign = sum(1 for r in rows if r.get("label") == "benign")
    licences = sorted({str(r.get("licence")) for r in rows if r.get("licence")})
    return {
        "sha256": sha256_file(path),
        "rows": len(rows),
        "attack": attack,
        "benign": benign,
        "licence": licences[0] if len(licences) == 1 else licences,
        "seen_by_tuning": bool(SEEN_BY_TUNING.get(rel, rel.startswith(("handwritten", "generated")))),
    }


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def verify_manifest() -> list[str]:
    """Return drift messages (empty list = every committed file matches MANIFEST.json)."""
    problems: list[str] = []
    try:
        man = load_manifest()
    except FileNotFoundError:
        return [f"missing {MANIFEST_PATH.name}"]
    files = man.get("files", {})
    on_disk = {
        p.relative_to(HERE).as_posix()
        for d in ("public", "handwritten", "generated", "pii")
        for p in (HERE / d).glob("*.jsonl")
    }
    for rel in sorted(on_disk - set(files)):
        problems.append(f"{rel}: not in MANIFEST")
    for rel, meta in sorted(files.items()):
        p = HERE / rel
        if not p.exists():
            problems.append(f"{rel}: missing on disk")
            continue
        got = sha256_file(p)
        if got != meta.get("sha256"):
            problems.append(f"{rel}: sha256 {got[:12]} != manifest {str(meta.get('sha256'))[:12]}")
        n = sum(1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip())
        if n != meta.get("rows"):
            problems.append(f"{rel}: rows {n} != manifest {meta.get('rows')}")
    return problems


# Attribution lines printed in every report (CC-BY-4.0 requires it; the others are courtesy).
_ATTRIBUTION = [
    "XSTest (Röttger et al., 2024) - paul-rottger/xstest - CC-BY-4.0 - 200 safe prompts, unmodified text",
    "JailbreakBench JBB-Behaviors (Chao et al., 2024) @886acc3 - MIT",
    "deepset/prompt-injections @4f61ecb - Apache-2.0",
    "Lakera/gandalf_ignore_instructions @04737b6 - MIT",
    "BIPIA (Microsoft) and InjecAgent (UIUC Kang lab) attack strings in Aegis carriers - MIT",
    "Aegis handwritten / generated sets - Aegis-original",
]


def attribution_lines() -> list[str]:
    return list(_ATTRIBUTION)


__all__ = [
    "ALL_SUBSETS",
    "SECRET_PATTERNS",
    "SEEN_BY_TUNING",
    "CorpusRow",
    "PiiRow",
    "attribution_lines",
    "file_stats",
    "load_manifest",
    "load_pii",
    "load_rows",
    "row_files",
    "secret_hits",
    "sha256_file",
    "verify_manifest",
]
