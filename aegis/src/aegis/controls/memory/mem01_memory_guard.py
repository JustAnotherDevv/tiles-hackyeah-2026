"""ctl MEM-01 - Persistent memory guard (OWASP ASI06 Memory & Context Poisoning).

Writes (``tool.input`` / ``mcp.call``) to agent memory - instruction files (``CLAUDE.md``,
``AGENTS.md``, ``.cursorrules``, ``.github/copilot-instructions.md``, ``memory/*.md``,
``.claude/**``), MCP memory-server tools (``*.create_entities``, ``*.add_observations``) and RAG
ingestion tools (``*.upsert``, ``*.ingest``, ``*.add_documents``) - are classified as
``memory.write`` (``aegis.memory.classify``) and their content is scanned
(``aegis.memory.scan``: injection signatures with untrusted weights, agent-directive heuristics,
secrets / PII):

* injection score >= ``block_threshold`` (or a hidden carrier)      -> **block**
* secrets / card data                                              -> ``secret_action`` (block)
* persistent agent directives, weaker signature hits, content derived from an untrusted
  tool / MCP / A2A result in this session (shingle overlap), a session tainted by untrusted
  content (EXE-03 taint, read-only), PII                           -> ``cfg.action`` (require_approval)
* anything else                                                    -> ``benign_action`` (log) with
  a provenance stamp (``Decision.meta["memory"]["provenance"]``).

Reads: a memory read returned into context (``tool.output`` / ``mcp.result``) is forced to
``trusted=False`` in ``enrich`` so INJ-01/INJ-02 scan it as untrusted tool output, and logged
with the provenance of the last write. Every untrusted result is fingerprinted (never stored raw)
so later memory writes can be traced to it. On ``model.request`` the agent-memory files a harness
inlines into the context ("Contents of .../CLAUDE.md") are scanned on every turn: a poisoned
memory file blocks the call even after it scrolled out of INJ-01's latest-turn scope.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from aegis.actions import runtime as art
from aegis.actions.base import ActionGuardBase
from aegis.actions.classify import glob_match, normalize_tool_name
from aegis.actions.explain import Explain, display_path
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import (
    ACTION_PRECEDENCE,
    AppliesTo,
    ControlKind,
    Decision,
    Interaction,
    RequestContext,
)
from aegis.memory import provenance as prov
from aegis.memory.classify import MemoryOp, classify, context_memory_blocks
from aegis.memory.scan import ContentScan, scan_content

P = "controls[MEM-01].params"
RESULT_SURFACES = frozenset({"tool.output", "mcp.result", "a2a.result", "egress.response"})


class Mem01Params(BaseModel):
    model_config = ConfigDict(extra="allow")

    memory_paths: list[str] = [
        "**/CLAUDE.md", "**/CLAUDE.local.md", "**/AGENTS.md", "**/GEMINI.md", "**/MEMORY.md",
        "**/.cursorrules", "**/.cursor/rules/**", "**/.windsurfrules", "**/.clinerules",
        "**/.clinerules/**", "**/.github/copilot-instructions.md", "**/.github/instructions/**",
        "**/memory/*.md", "**/memory/**/*.md", "**/memories/**", "**/.claude/**", "~/.claude/**",
    ]
    write_tools: list[str] = ["Write", "Edit", "MultiEdit", "NotebookEdit", "*.write_file",
                              "*.edit_file", "*.create_file", "*.append_file", "write_file",
                              "edit_file"]
    read_tools: list[str] = ["Read", "NotebookRead", "*.read_file", "*.read_text_file",
                             "*.read_multiple_files", "read_file"]
    shell_tools: list[str] = ["Bash", "shell", "*.run_command", "*.exec", "*.shell"]
    memory_tools: list[str] = ["*.create_entities", "*.add_observations", "*.create_relations",
                               "*.save_memory", "*.store_memory", "*.add_memory", "*.add_memories",
                               "*.update_memory", "*.remember", "*.memorize", "memory.write*"]
    rag_tools: list[str] = ["*.upsert", "*.upsert_*", "*.ingest", "*.ingest_*", "*.add_documents",
                            "*.add_document", "*.add_texts", "*.index_documents", "*.add_points"]
    memory_read_tools: list[str] = ["*.read_graph", "*.search_nodes", "*.open_nodes",
                                    "*.search_memory", "*.search_memories", "*.get_memories",
                                    "*.recall", "*.retrieve", "*.similarity_search",
                                    "*.query_documents", "memory.read*"]
    rag_read_tools: list[str] = ["*.retrieve", "*.similarity_search", "*.query_documents"]
    #: results from these tools mark the session as having seen untrusted content
    untrusted_sources: list[str] = ["WebFetch", "WebSearch", "web.*", "browser.*", "*.fetch",
                                    "*.fetch_url", "*.browse", "*.scrape", "*.search_web"]
    block_threshold: float = 0.6
    review_threshold: float = 0.15
    secret_action: str = "block"
    pii_action: str = "require_approval"
    directive_action: str = "require_approval"
    derived_action: str = "require_approval"
    tainted_session_action: str = "require_approval"
    benign_action: str = "log"
    read_action: str = "log"
    taint_ttl_turns: int = 20
    taint_ttl_s: float = 3600.0
    overlap_min_shared: int = 8
    overlap_min_ratio: float = 0.3
    scan_context: bool = True
    context_block_threshold: float = 0.6
    max_scan_chars: int = 65_536


def _max(a: str, b: str) -> str:
    return a if ACTION_PRECEDENCE.get(a, 0) >= ACTION_PRECEDENCE.get(b, 0) else b


class MemoryGuard(ActionGuardBase):
    id: ClassVar[str] = "MEM-01"
    family: ClassVar[str] = "MEM"
    name: ClassVar[str] = "Persistent memory guard (memory & context poisoning)"
    kind: ClassVar[ControlKind] = "stateful"
    applies_to: ClassVar[AppliesTo] = AppliesTo(
        surfaces={"tool.input", "mcp.call", "tool.output", "mcp.result", "a2a.result",
                  "egress.response", "model.request"}
    )
    owasp: ClassVar[list[str]] = ["ASI06", "ASI01", "LLM01:2026", "LLM04:2026"]
    priority: ClassVar[int] = 33
    params_model = Mem01Params
    default_levers: ClassVar[list[str]] = [
        "controls[MEM-01].action",
        f"{P}.memory_paths",
        f"{P}.block_threshold",
        f"{P}.tainted_session_action",
    ]

    # ------------------------------------------------------------------ enrich
    async def enrich(self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
                     ) -> None:
        p: Mem01Params = self.params(cfg)
        if interaction.surface == "model.request":
            return
        op = classify(interaction, p)
        if op is None:
            return
        interaction.labels["memory"] = op.op
        if op.op == "read":
            # Memory replayed into context is untrusted tool output (INJ-01/02 scan it as such).
            for s in interaction.segments:
                s.trusted = False
            interaction.meta["memory.read"] = op.to_meta()

    # ------------------------------------------------------------------ evaluate
    async def evaluate(self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
                       ) -> Decision | None:
        p: Mem01Params = self.params(cfg)
        if interaction.surface == "model.request":
            return self._context(interaction, cfg, p) if p.scan_context else None
        op = classify(interaction, p)
        if interaction.surface in RESULT_SURFACES:
            return self._result(ctx, interaction, cfg, p, op)
        if op is None or op.op != "write":
            return None
        return await self._write(ctx, interaction, cfg, p, op)

    # ------------------------------------------------------------------ results / reads
    def _result(self, ctx: RequestContext, i: Interaction, cfg: ControlConfig, p: Mem01Params,
                op: MemoryOp | None) -> Decision | None:
        tool = normalize_tool_name(i.tool_name) or (i.destination.host or i.surface)
        if op is None and not (ctx.dry_run or ctx.source == "selftest"):
            untrusted_src = i.surface in ("a2a.result", "egress.response") or any(
                glob_match(pat, tool) for pat in p.untrusted_sources)
            text = "\n".join(s.text for s in i.segments)
            prov.record_untrusted(ctx.session_id, tool, i.surface, text[: p.max_scan_chars],
                                  untrusted_source=untrusted_src)
            return None
        if op is None:
            return None
        last = prov.last_write(op.target)
        ex = Explain(facts={"memory": op.to_meta(), "last_write": last})
        ex.check("untrusted", "memory content returned into context is untrusted tool output",
                 "trusted=False", None, "info", f"{P}.memory_read_tools")
        core = (f"memory read {display_path(op.target) if op.kind == 'file' else op.target} "
                "returned into context; scanned as untrusted tool output (INJ-01/02)")
        if last and last.get("trust") == "untrusted":
            core += f"; last written from untrusted content ({last.get('derived_from') or last.get('tainted_by')})"
        return self.note(cfg, i, core=core, action=p.read_action, explain=ex,
                         action_type="memory.read", memory={**op.to_meta(), "last_write": last})

    # ------------------------------------------------------------------ model context
    def _context(self, i: Interaction, cfg: ControlConfig, p: Mem01Params) -> Decision | None:
        for idx, seg in enumerate(i.segments):
            if "Contents of " not in seg.text:
                continue
            for path, content in context_memory_blocks(seg.text):
                sc = scan_content(content, max_chars=p.max_scan_chars, dlp=False)
                if sc.inj_score >= p.context_block_threshold or (sc.carrier and sc.sig_ids):
                    ex = Explain(facts={"path": display_path(path), "scan": sc.to_meta(),
                                        "segment": idx})
                    ex.check("injection", "injection score of memory file in context",
                             sc.inj_score, p.context_block_threshold, "fail",
                             f"{P}.context_block_threshold")
                    return self.hard(
                        cfg, i,
                        core=(f"poisoned agent memory {display_path(path)} loaded into the model "
                              f"context ({', '.join(sc.families) or 'injection'}, score "
                              f"{sc.inj_score:.2f})"),
                        explain=ex, action_type="memory.context",
                        suffix="Fix or remove the memory file",
                        findings=[self.finding("mem.context.injection", category="injection",
                                               severity="critical",
                                               excerpt=", ".join(sc.sig_ids[:4]),
                                               path=display_path(path))],
                        memory={"op": "context", "target": path, "scan": sc.to_meta()},
                    )
        return None

    # ------------------------------------------------------------------ writes
    async def _write(self, ctx: RequestContext, i: Interaction, cfg: ControlConfig,
                     p: Mem01Params, op: MemoryOp) -> Decision:
        sc: ContentScan = scan_content(op.content, max_chars=p.max_scan_chars)
        live = not (ctx.dry_run or ctx.source == "selftest")
        derived = prov.derived_from(ctx.session_id, op.content, ttl_s=p.taint_ttl_s,
                                    min_shared=p.overlap_min_shared,
                                    min_ratio=p.overlap_min_ratio) if live else None
        tainted = prov.session_taint(art.current_rt(), ctx.session_id,
                                     ttl_turns=p.taint_ttl_turns, ttl_s=p.taint_ttl_s
                                     ) if live else None
        target = display_path(op.target) if op.kind == "file" else op.target
        where = {"file": "agent memory file", "mcp_memory": "memory store",
                 "rag": "RAG store"}[op.kind]
        ex = Explain(facts={"memory": op.to_meta(), "scan": sc.to_meta()})
        findings = []
        action = p.benign_action
        why: list[str] = []
        hard = False

        if sc.errors and cfg.fail_mode == "closed":
            action, hard = "block", True
            why.append("content scanner unavailable (fail-closed)")
        malicious = sc.inj_score >= p.block_threshold or (sc.carrier and bool(sc.sig_ids))
        ex.check("injection", "prompt-injection score of written content", sc.inj_score,
                 p.block_threshold, "fail" if malicious else "pass", f"{P}.block_threshold")
        if malicious:
            action, hard = "block", True
            why.append(f"prompt injection in content ({', '.join(sc.families) or 'hidden carrier'}, "
                       f"score {sc.inj_score:.2f})")
            findings.append(self.finding("mem.write.injection", category="injection",
                                         severity="critical", excerpt=", ".join(sc.sig_ids[:4])))
        if sc.secrets or sc.pci:
            ents = sc.secrets + sc.pci
            ex.check("secrets", "secrets / card data in memory", ents, [], "fail", f"{P}.secret_action")
            action = _max(action, p.secret_action)
            hard = hard or p.secret_action == "block"
            why.append(f"secrets would persist in memory ({', '.join(ents)})")
            findings.append(self.finding("mem.write.secret", category="secret", severity="high",
                                         entity=ents[0]))
        soft_why: list[str] = []
        if 0 < sc.inj_score < p.block_threshold and sc.inj_score >= p.review_threshold:
            soft_why.append(f"suspicious injection signals ({', '.join(sc.families)}, "
                            f"score {sc.inj_score:.2f})")
            action = _max(action, p.directive_action)
        if sc.directives:
            ex.check("directives", "persistent agent directives", sc.directives, [], "fail",
                     f"{P}.directive_action")
            soft_why.append(f"instruction-like content ({', '.join(sc.directives)})")
            action = _max(action, p.directive_action)
            findings.append(self.finding("mem.write.directive", category="injection",
                                         severity="medium", directives=sc.directives))
        if derived:
            ex.check("provenance", "content derived from untrusted tool output",
                     derived["source"], None, "fail", f"{P}.derived_action")
            soft_why.append(f"content copied from untrusted {derived['surface']} "
                            f"({derived['source']}, {derived['shared_shingles']} shared shingles)")
            action = _max(action, p.derived_action)
            findings.append(self.finding("mem.write.untrusted_provenance", category="taint",
                                         severity="high", source=derived["source"]))
        if tainted:
            ex.check("taint", "session saw untrusted content", tainted["source"], None, "fail",
                     f"{P}.tainted_session_action")
            soft_why.append(f"session read untrusted content ({tainted['source']})")
            action = _max(action, p.tainted_session_action)
        if sc.pii:
            ex.check("pii", "personal data in memory", sc.pii, [], "fail", f"{P}.pii_action")
            soft_why.append(f"personal data would persist ({', '.join(sc.pii)})")
            action = _max(action, p.pii_action)
            findings.append(self.finding("mem.write.pii", category="pii", severity="medium",
                                         entity=sc.pii[0]))

        principal = ctx.identity.agent_id or ctx.identity.member_id or "unknown"
        stamp = prov.stamp(target=op.target, kind=op.kind, via=op.via, session_id=ctx.session_id,
                           principal=principal, content=op.content, derived=derived,
                           tainted=tainted, action=action, record=live and action != "block")
        mem_meta = {**op.to_meta(), "scan": sc.to_meta(), "provenance": stamp}
        ex.facts["provenance"] = stamp
        if action == "block":
            core = f"memory poisoning - write to {where} {target} blocked: " + "; ".join(why or soft_why)
            if hard or not soft_why:
                return self.hard(cfg, i, core=core, explain=ex, findings=findings,
                                 action_type="memory.write", memory=mem_meta)
        if ACTION_PRECEDENCE.get(action, 0) >= ACTION_PRECEDENCE["require_approval"]:
            agent = ctx.identity.agent_id or ctx.identity.member_id or "agent"
            core = f"write to {where} {target} needs review: " + "; ".join(why + soft_why)
            return await self.soft(
                ctx, i, cfg, core=core, action_type="memory.write",
                action=None if action == "require_approval" else action,
                title=f"{agent}: persist to {where} {target}",
                resource=f"memory:{target}", explain=ex, findings=findings,
                labels={"memory_kind": op.kind}, memory=mem_meta,
            )
        return self.note(cfg, i, core=f"memory write to {where} {target} (provenance stamped)",
                         action=action, explain=ex, findings=findings,
                         action_type="memory.write", memory=mem_meta)


CONTROLS = [MemoryGuard()]
