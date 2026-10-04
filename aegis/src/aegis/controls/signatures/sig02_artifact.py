"""SIG-02 · Model-artifact gate (pickle, GGUF, Keras, registries).

Two interception points the gateway really owns (plan 13 section 2.9):
1. `model.admin` - the gateway's Ollama front `/ollama/api/{pull|push|create|copy|delete}`:
   registry allowlist + `insecure` for pull/create-from, push blocked (weights exfiltration),
   Modelfile template SSTI markers on create, copy/delete logged.
2. `artifact.file` - model bytes (raw / meta.artifact_b64 / tool_args.artifact_b64 /
   meta.artifact_path under `artifact_roots`), sniffed by magic bytes and scanned fail-closed
   by `aegis.feed.gate.scan_artifact` in a worker thread.
HF namespace reuse (`AEGIS-TI-018`) and Modelfile SSTI signatures (`AEGIS-TI-005`) come from the
signed feed via SIG-01.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from pathlib import Path
from typing import Any

from aegis.controls.signatures import _common as C
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Finding
from aegis.feed import gate

log = logging.getLogger(__name__)

_FROM_RE = re.compile(r"(?im)^\s*FROM\s+(\S+)")


class SIG02Params(C.Params):
    allowed_formats: list[str] = list(gate.DEFAULT_ALLOWED_FORMATS)
    pickle_global_allow: list[str] = list(gate.DEFAULT_ALLOW)
    pickle_global_deny: list[str] = list(gate.DEFAULT_DENY)
    malformed_action: str = "block"
    max_scan_mb: int = 512
    gguf_template_markers: list[str] = list(gate.DEFAULT_MARKERS)
    keras_reject_lambda: bool = True
    registries_allow: list[str] = ["registry.ollama.ai", "hf.co", "huggingface.co"]
    admin_ops_block: list[str] = ["push"]
    admin_ops_log: list[str] = ["copy", "delete"]
    artifact_roots: list[str] = ["data/artifacts", "models", "demo"]


def _root() -> Path:
    try:
        from aegis.settings import ROOT

        return Path(ROOT)
    except Exception:  # TODO(integration): settings without ROOT
        return Path.cwd()


def admin_op(i: Any) -> str | None:
    meta = getattr(i, "meta", None) or {}
    op = meta.get("ollama_op")
    if not op:
        tn = str(getattr(i, "tool_name", "") or "")
        if tn.startswith("ollama."):
            op = tn.split(".", 1)[1]
    if not op:
        url = str(getattr(i, "url", "") or "")
        mt = re.search(r"/api/([a-z]+)", url)
        op = mt.group(1) if mt else None
    return str(op).lower() if op else None


def _strings(args: dict, *keys: str) -> list[str]:
    return [str(args[k]) for k in keys if isinstance(args.get(k), str) and args.get(k)]


class ModelArtifactGate(BaseControl):
    id, family, name, kind = "SIG-02", "SIG", "Model-artifact gate", "deterministic"
    applies_to = AppliesTo(surfaces={"model.admin", "artifact.file"})
    owasp = ["LLM04:2026", "LLM05:2026", "ASI04", "ASI05"]
    priority = 100

    async def evaluate(self, ctx: Any, interaction: Any, cfg: Any) -> Decision | None:
        p = C.params(self.id, SIG02Params, cfg)
        surface = str(getattr(interaction, "surface", ""))
        if surface == "model.admin":
            findings = self._admin(interaction, p)
        elif surface == "artifact.file":
            findings = await self._artifact(interaction, p, cfg)
        else:
            return None
        if findings is None:
            return None
        return self._decide(findings, cfg)

    # ------------------------------------------------------------------ model.admin
    def _admin(self, i: Any, p: SIG02Params) -> list[dict] | None:
        op = admin_op(i)
        if not op:
            return None
        args = dict(getattr(i, "tool_args", None) or {})
        model = getattr(i, "model", None) or (_strings(args, "model", "name") or [None])[0]
        if op in p.admin_ops_block:
            return [
                gate._f(
                    "admin_op",
                    f"ollama {op} blocked: model weights leaving the machine ({model or '?'})",
                    "block",
                    op=op,
                    model=model,
                )
            ]
        if op in p.admin_ops_log:
            return [
                gate._f("admin_op", f"ollama {op} {model or ''}".strip(), "log", op=op, model=model)
            ]
        out: list[dict] = []
        refs: list[str] = []
        if op == "pull" and model:
            refs.append(str(model))
        if op == "create":
            refs += _strings(args, "from")
            for text in _strings(args, "modelfile"):
                refs += _FROM_RE.findall(text)
        for ref in refs:
            if ref.startswith((".", "/", "~", "sha256:", "@")):
                continue  # local files are imported as blobs (artifact.file)
            reg = gate.registry_of(ref)
            if reg not in {r.lower() for r in p.registries_allow}:
                out.append(
                    gate._f(
                        "registry",
                        f"model registry {reg} is not allowlisted ({ref})",
                        "block",
                        op=op,
                        registry=reg,
                        model=ref,
                    )
                )
        if op in ("pull", "create", "push") and args.get("insecure") is True:
            out.append(
                gate._f(
                    "registry",
                    f"ollama {op} with insecure: true (TLS disabled)",
                    "block",
                    op=op,
                    model=model,
                )
            )
        if op == "create":
            texts = _strings(args, "template", "system", "modelfile")
            files = args.get("files")
            if isinstance(files, dict):
                texts += [str(v) for v in files.values() if isinstance(v, str)]
            for t in texts:
                hit = gate.template_markers(t, p.gguf_template_markers)
                if hit:
                    out.append(
                        gate._f(
                            "gguf_ssti",
                            f"Modelfile template contains SSTI gadget {hit[0]} ({gate.SSTI_CVE})",
                            "block",
                            op=op,
                            markers=hit[:8],
                        )
                    )
                    break
        return out or None

    # ------------------------------------------------------------------ artifact.file
    async def _artifact(self, i: Any, p: SIG02Params, cfg: Any) -> list[dict] | None:
        from aegis.feed.matchers import artifact_bytes
        from aegis.feed.matchers.core import FeedError

        cap = max(1, p.max_scan_mb) * 1024 * 1024
        meta = getattr(i, "meta", None) or {}
        try:
            data = artifact_bytes(
                i, artifact_roots=p.artifact_roots, base_dir=_root(), max_bytes=cap
            )
        except FeedError as e:
            return [gate._f("format", f"artifact rejected: {e}", p.malformed_action)]
        if data is None:
            return None
        if len(data) > cap:
            return [
                gate._f(
                    "format",
                    f"artifact larger than max_scan_mb={p.max_scan_mb}",
                    p.malformed_action,
                    size=len(data),
                )
            ]
        filename = meta.get("filename") or (getattr(i, "tool_args", None) or {}).get("filename")
        params = p.model_dump()
        params["action"] = str(getattr(cfg, "action", None) or "block")
        try:
            fmt, findings = await asyncio.to_thread(gate.scan_artifact, data, filename, params)
        except Exception as e:  # fail closed
            log.warning("artifact scan error=%s", type(e).__name__)
            return [
                gate._f(
                    "format",
                    f"artifact scanner error ({type(e).__name__}) - fail closed",
                    p.malformed_action,
                )
            ]
        meta_note = {"format": fmt, "bytes": len(data)}
        for f in findings:
            f["meta"] = {**meta_note, **f.get("meta", {})}
        if not findings:
            log.debug("artifact allowed format=%s bytes=%s", fmt, len(data))
            return []
        return findings

    # ------------------------------------------------------------------ decision
    def _decide(self, findings: list[dict], cfg: Any) -> Decision | None:
        if not findings:
            return Decision(
                action="allow", control_id=self.id, reason="model artifact clean", severity="info"
            )
        action = C.strongest([f["action"] for f in findings])
        primary = next(f for f in findings if f["action"] == action)
        sev = (
            "critical" if action == "block" else ("high" if action == "require_approval" else "low")
        )
        out = [
            Finding(
                control_id=self.id,
                detector=f["detector"],
                category="model",
                severity=sev if f["action"] == action else "medium",  # type: ignore[arg-type]
                excerpt=C.mask(f["reason"], 160),
                meta=dict(f.get("meta") or {}),
            )
            for f in findings
        ]
        return Decision(
            action=action,
            control_id=self.id,
            reason=primary["reason"],  # type: ignore[arg-type]
            severity=sev,  # type: ignore[arg-type]
            findings=out,
            owasp=list(getattr(cfg, "owasp", None) or self.owasp),
            meta={"artifact": primary.get("meta", {})},
        )


def b64(data: bytes) -> str:
    """Helper for callers/tests building `meta.artifact_b64`."""
    return base64.b64encode(data).decode("ascii")


CONTROLS = [ModelArtifactGate()]
