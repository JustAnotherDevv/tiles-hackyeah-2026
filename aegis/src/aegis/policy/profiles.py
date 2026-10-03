"""Strictness profiles and the effective control configuration.

Profile files (`config/profiles/<name>.yaml`):

    profile: strict
    description: "..."
    floor: true                       # profile values are a floor for knobs pinned in policy.yaml
    kind_defaults: {semantic: {fail_mode: closed}, ...}
    controls: {INJ-02: {threshold: 0.75, params: {untrusted_threshold: 0.60}}, ...}

Effective config of control X (kind K) under profile P, lowest -> highest precedence
(docs/plan/02-policy-engine.md section 2.3; computed on raw dicts so "explicit" = key present):

 1. frozen ControlConfig defaults, then the catalog default `action` (and `mode` for stretch
    controls) so a control works sensibly even when no profile file is found
 2. profiles[P].kind_defaults[K]
 3. explicit `defaults.fail_mode`; explicit `defaults.semantic_timeout_ms` (semantic/hybrid)
 4. profiles[P].controls[X]
 5. the explicit policy.yaml entry (params/scope deep-merged; other fields replaced)
 6. floor (strict/paranoid): stricter of pinned vs profile for threshold (min), adherence_pct
    (max), action (precedence), fail_mode (closed > deterministic_only > open);
    `enabled` and `mode` are never floored
 7. global `defaults.mode: monitor|off`
 8. ControlConfig.model_validate (id forced to X); semantic/hybrid without any timeout_ms
    get `defaults.semantic_timeout_ms`.
A control listed only in a profile but absent from policy.yaml is not activated.
"""

from __future__ import annotations

import copy
import hashlib
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from aegis.core.policy_schema import ControlConfig, PolicyDoc
from aegis.core.types import ACTION_PRECEDENCE
from aegis.policy import catalog

log = logging.getLogger(__name__)

PROFILE_NAMES = ("permissive", "balanced", "strict", "paranoid")
PROFILE_RANK = {"permissive": 0, "balanced": 1, "strict": 2, "paranoid": 3}
FAIL_RANK = {"open": 0, "deterministic_only": 1, "closed": 2}
MODE_RANK = {"off": 0, "monitor": 1, "enforce": 2}
REPO_PROFILES_DIR = Path(__file__).resolve().parents[3] / "config" / "profiles"
_DEEP_KEYS = ("params", "scope")


@dataclass
class Profile:
    name: str
    description: str = ""
    floor: bool = False
    kind_defaults: dict[str, dict[str, Any]] = field(default_factory=dict)
    controls: dict[str, dict[str, Any]] = field(default_factory=dict)
    path: str | None = None


@dataclass
class ProfileSet:
    profiles: dict[str, Profile] = field(default_factory=dict)
    sha256: str = ""
    source_dir: str | None = None
    warnings: list[str] = field(default_factory=list)

    def get(self, name: str) -> Profile:
        return self.profiles.get(name) or Profile(name=name)

    @classmethod
    def search_dirs(cls, policy_path: str | Path | None = None) -> list[Path]:
        dirs: list[Path] = []
        if policy_path:
            dirs.append(Path(policy_path).resolve().parent / "profiles")
        dirs.append(REPO_PROFILES_DIR)
        out: list[Path] = []
        for d in dirs:
            if d not in out:
                out.append(d)
        return out

    @classmethod
    def load(cls, dirs: Iterable[str | Path] | None = None, *, policy_path: str | Path | None = None) -> ProfileSet:
        """First directory containing at least one `<profile>.yaml` wins (no cross-dir mixing)."""
        candidates = [Path(d) for d in dirs] if dirs is not None else cls.search_dirs(policy_path)
        for d in candidates:
            files = [d / f"{n}.yaml" for n in PROFILE_NAMES if (d / f"{n}.yaml").is_file()]
            if not files:
                continue
            ps = cls(source_dir=str(d))
            h = hashlib.sha256()
            for f in files:
                try:
                    text = f.read_text(encoding="utf-8")
                except OSError as exc:
                    ps.warnings.append(f"profile {f.name} unreadable: {exc}")
                    continue
                h.update(f.name.encode() + b"\0" + text.encode("utf-8") + b"\0")
                try:
                    data = yaml.safe_load(text) or {}
                except yaml.YAMLError as exc:
                    ps.warnings.append(f"profile {f.name} invalid YAML: {exc}")
                    continue
                if not isinstance(data, dict):
                    ps.warnings.append(f"profile {f.name} is not a mapping")
                    continue
                name = f.stem
                ps.profiles[name] = Profile(
                    name=name,
                    description=str(data.get("description") or ""),
                    floor=bool(data.get("floor", False)),
                    kind_defaults={str(k): dict(v or {}) for k, v in (data.get("kind_defaults") or {}).items()},
                    controls={str(k): dict(v or {}) for k, v in (data.get("controls") or {}).items()},
                    path=str(f),
                )
            ps.sha256 = h.hexdigest()
            return ps
        ps = cls(sha256=hashlib.sha256(b"no-profiles").hexdigest())
        ps.warnings.append("no profile files found (config/profiles/*.yaml); using policy values only")
        return ps

    @classmethod
    def from_dict(cls, data: dict[str, dict[str, Any]]) -> ProfileSet:
        """Test helper: {name: {floor, kind_defaults, controls}}."""
        ps = cls()
        for name, d in data.items():
            ps.profiles[name] = Profile(
                name=name, floor=bool(d.get("floor", False)),
                kind_defaults=dict(d.get("kind_defaults") or {}), controls=dict(d.get("controls") or {}),
            )
        ps.sha256 = hashlib.sha256(repr(sorted(data.items())).encode()).hexdigest()
        return ps


def deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Maps merge key by key; lists and scalars are replaced. Returns a new dict."""
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _layer(merged: dict[str, Any], layer: dict[str, Any]) -> dict[str, Any]:
    out = dict(merged)
    for k, v in layer.items():
        if k in _DEEP_KEYS and isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _stricter(knob: str, pinned: Any, prof: Any) -> Any:
    if pinned is None:
        return prof if knob in ("threshold", "adherence_pct") and prof is not None else pinned
    if prof is None:
        return pinned
    try:
        if knob == "threshold":
            return min(float(pinned), float(prof))
        if knob == "adherence_pct":
            return max(float(pinned), float(prof))
    except (TypeError, ValueError):
        return pinned
    if knob == "action":
        return pinned if ACTION_PRECEDENCE.get(str(pinned), 0) >= ACTION_PRECEDENCE.get(str(prof), 0) else prof
    if knob == "fail_mode":
        return pinned if FAIL_RANK.get(str(pinned), 0) >= FAIL_RANK.get(str(prof), 0) else prof
    return pinned


_FLOOR_KNOBS = ("threshold", "adherence_pct", "action", "fail_mode")


def effective_control(
    entry_raw: dict[str, Any],
    *,
    raw_defaults: dict[str, Any],
    defaults_mode: str,
    semantic_timeout_ms: int,
    profile: Profile,
    kind: str,
) -> ControlConfig:
    cid = str(entry_raw.get("id"))
    cat = catalog.get(cid)
    merged: dict[str, Any] = {}
    # 1. catalog defaults
    if cat is not None:
        merged["action"] = cat.default_action
        if cat.default_mode:
            merged["mode"] = cat.default_mode
    # 2. profile kind defaults
    merged = _layer(merged, profile.kind_defaults.get(kind, {}))
    # 3. explicit global defaults
    if "fail_mode" in raw_defaults:
        merged["fail_mode"] = raw_defaults["fail_mode"]
    semantic = kind in ("semantic", "hybrid")
    if semantic and "semantic_timeout_ms" in raw_defaults:
        merged["timeout_ms"] = raw_defaults["semantic_timeout_ms"]
    # 4. profile per-control
    prof_ctrl = profile.controls.get(cid, {})
    merged = _layer(merged, prof_ctrl)
    # 5. explicit policy entry
    merged = _layer(merged, entry_raw)
    # 6. floor
    if profile.floor:
        prof_vals = {**profile.kind_defaults.get(kind, {}), **prof_ctrl}
        for knob in _FLOOR_KNOBS:
            if knob in entry_raw and knob in prof_vals:
                merged[knob] = _stricter(knob, entry_raw[knob], prof_vals[knob])
    # 7. global mode
    if defaults_mode == "monitor" and merged.get("mode", "enforce") == "enforce":
        merged["mode"] = "monitor"
    elif defaults_mode == "off":
        merged["mode"] = "off"
    # 8. semantic timeout default + validate
    if semantic and "timeout_ms" not in merged:
        merged["timeout_ms"] = semantic_timeout_ms
    merged["id"] = cid
    return ControlConfig.model_validate(merged)


def effective_controls(
    raw_doc: dict[str, Any] | None,
    doc: PolicyDoc,
    profile_name: str,
    profiles: ProfileSet,
    *,
    kind_lookup: Callable[[str], str] | None = None,
) -> dict[str, ControlConfig]:
    """Effective (profile-merged) ControlConfig per configured control id."""
    raw_doc = raw_doc if isinstance(raw_doc, dict) else {}
    raw_defaults = raw_doc.get("defaults") if isinstance(raw_doc.get("defaults"), dict) else {}
    raw_controls = raw_doc.get("controls") if isinstance(raw_doc.get("controls"), list) else None
    if raw_controls is None:  # doc built programmatically: everything counts as explicit
        raw_controls = [c.model_dump(mode="json", by_alias=True, exclude_unset=True) | {"id": c.id}
                        for c in doc.controls]
    profile = profiles.get(profile_name)
    kind_of = kind_lookup or catalog.kind_of
    out: dict[str, ControlConfig] = {}
    for entry in raw_controls:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        cid = str(entry["id"])
        try:
            out[cid] = effective_control(
                entry,
                raw_defaults=raw_defaults,
                defaults_mode=doc.defaults.mode,
                semantic_timeout_ms=doc.defaults.semantic_timeout_ms,
                profile=profile,
                kind=kind_of(cid),
            )
        except Exception as exc:  # a broken profile value must not drop the control
            log.warning("profile merge failed control=%s profile=%s error=%s", cid, profile_name, exc)
            fallback = next((c for c in doc.controls if c.id == cid), None)
            if fallback is not None:
                out[cid] = fallback
    return out
