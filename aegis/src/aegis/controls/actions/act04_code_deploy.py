"""ctl ACT-04 - Code execution & deploy guard (action-guards).

Over the structural shell analysis (every segment, nested bodies included):
* ``code.deploy``: terraform apply/destroy, kubectl apply/delete/rollout/scale, helm
  install/upgrade/uninstall, ``git push`` to ``protected_branches`` or ``--force``, vercel --prod,
  fly deploy, serverless deploy, gcloud run deploy, docker push; MCP ``params.deploy_tools``;
* ``package.install`` (pip/uv/npm/pnpm/yarn/brew/apt/gem/cargo/go) - SIG-03 owns unknown packages;
* ``code.exec`` (docker/podman run, ssh/scp/rsync, ``python -c``, ``node -e``).
``env`` from ``-n/--namespace/--context``, ``-var-file=prod.tfvars``, ``workspace select``, ``--prod``,
protected branch -> ``mainline``. Labels ``env``, ``pattern``, ``force``. Action per
``params.category_actions`` (balanced: deploy -> require_approval, package.install -> log).
A push to a feature branch is allowed.
"""

from __future__ import annotations

import re
from fnmatch import fnmatchcase
from typing import Any, ClassVar

from aegis.actions.base import ActionGuardBase
from aegis.actions.classify import normalize_tool_name, refine
from aegis.actions.commands import analysis_for, matches_any
from aegis.actions.explain import Explain, mask
from aegis.actions.params import Act04Params
from aegis.actions.shell import Segment
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import AppliesTo, ControlKind, Decision, Interaction, RequestContext

P = "controls[ACT-04].params"
META = "act.code"
_PKG = {
    "pip": "pypi",
    "pip3": "pypi",
    "uv": "pypi",
    "poetry": "pypi",
    "npm": "npm",
    "pnpm": "npm",
    "yarn": "npm",
    "brew": "brew",
    "apt": "apt",
    "apt-get": "apt",
    "gem": "rubygems",
    "cargo": "crates",
    "go": "go",
}
_PKG_VERBS = {"install", "add", "i"}
_RANK = {"code.deploy": 3, "code.exec": 2, "package.install": 1}


def _first_pos(args: list[str]) -> list[str]:
    return [a for a in args if not a.startswith("-")]


def _classify_segment(seg: Segment, p: Act04Params) -> dict[str, Any] | None:
    prog, args = seg.prog, seg.args
    pos = _first_pos(args)
    low = [a.lower() for a in args]
    if prog == "terraform" and pos[:1] and pos[0] in ("apply", "destroy"):
        return {"type": "code.deploy", "pattern": "terraform_apply"}
    if (
        prog in ("kubectl", "oc")
        and pos[:1]
        and pos[0] in ("apply", "delete", "rollout", "scale", "replace", "patch")
    ):
        return {"type": "code.deploy", "pattern": "kubectl_apply"}
    if prog == "helm" and pos[:1] and pos[0] in ("install", "upgrade", "uninstall", "rollback"):
        return {"type": "code.deploy", "pattern": "helm_release"}
    if prog == "git" and pos[:1] == ["push"]:
        force = any(
            a in ("-f", "--force", "--force-with-lease") or a.startswith("--force") for a in args
        ) or any(x.startswith("+") for x in pos[1:])
        refs = [x.lstrip("+").split(":")[-1] for x in pos[2:]]
        protected = [r for r in refs if any(fnmatchcase(r, b) for b in p.protected_branches)]
        if force or protected:
            return {
                "type": "code.deploy",
                "pattern": "git_push_main" if protected else "git_push_force",
                "force": force,
                "branch": (protected or refs or ["?"])[0],
                "protected": bool(protected),
            }
        return {
            "type": "code.deploy",
            "pattern": "git_push",
            "feature": True,
            "branch": (refs or ["?"])[0],
        }
    if prog == "vercel" and ("--prod" in low or "deploy" in pos):
        return {
            "type": "code.deploy",
            "pattern": "vercel_deploy",
            "env": "prod" if "--prod" in low else None,
        }
    if prog in ("fly", "flyctl") and pos[:1] == ["deploy"]:
        return {"type": "code.deploy", "pattern": "fly_deploy"}
    if prog in ("serverless", "sls") and pos[:1] == ["deploy"]:
        return {"type": "code.deploy", "pattern": "serverless_deploy"}
    if prog == "gcloud" and "deploy" in pos:
        return {"type": "code.deploy", "pattern": "gcloud_deploy"}
    if prog in ("docker", "podman") and pos[:1] == ["push"]:
        return {"type": "code.deploy", "pattern": "docker_push"}
    if prog in _PKG and len(pos) >= 1:
        verb_i = 1 if prog == "uv" and pos[0] == "pip" else 0
        if len(pos) > verb_i and pos[verb_i] in _PKG_VERBS:
            names = [x for x in pos[verb_i + 1 :] if not x.startswith(("http", ".", "/"))][:5]
            return {
                "type": "package.install",
                "pattern": "pkg_install",
                "ecosystem": _PKG[prog],
                "packages": names,
            }
    if prog in ("docker", "podman") and pos[:1] == ["run"]:
        return {"type": "code.exec", "pattern": "container_run"}
    if prog in ("ssh", "scp", "rsync", "sftp") and pos:
        return {"type": "code.exec", "pattern": "remote_shell"}
    if (prog.startswith("python") and "-c" in args) or (
        prog in ("node", "nodejs", "deno") and "-e" in args
    ):
        return {"type": "code.exec", "pattern": "python_exec"}
    return None


def _env(text: str, p: Act04Params) -> str | None:
    m = (
        re.search(r"(?:-var-file[= ]|--var-file[= ])\S*?([A-Za-z]+)\.tfvars", text)
        or re.search(r"\bworkspace\s+select\s+(\S+)", text)
        or re.search(
            r"(?:\s-n\s+|--namespace[= ]|--context[= ]|--env(?:ironment)?[= ]|--stage[= ]|-e\s+)(\S+)",
            text,
        )
    )
    cand = m.group(1).lower() if m else None
    if cand is None and re.search(r"--prod\b", text):
        cand = "prod"
    if cand is None:
        return None
    for env, aliases in p.env_aliases.items():
        if env == "mainline":
            continue
        if any(a in cand for a in aliases):
            return env
    return None


class CodeDeployGuard(ActionGuardBase):
    id: ClassVar[str] = "ACT-04"
    family: ClassVar[str] = "ACT"
    name: ClassVar[str] = "Code execution & deploy guard"
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo(
        surfaces={"tool.input", "mcp.call"}, directions={"out"}
    )
    owasp: ClassVar[list[str]] = ["ASI05", "LLM10:2026", "MCP05:2025"]
    priority: ClassVar[int] = 33
    params_model = Act04Params
    default_levers: ClassVar[list[str]] = [
        f"{P}.category_actions",
        f"{P}.protected_branches",
        "approvals.rules[deploy-*]",
    ]

    def _analyze(self, i: Interaction, p: Act04Params) -> dict[str, Any] | None:
        tool = normalize_tool_name(i.tool_name)
        if matches_any(tool, p.deploy_tools):
            env_arg = (i.tool_args or {}).get("environment") or (i.tool_args or {}).get("env")
            env = None
            if isinstance(env_arg, str):
                env = next(
                    (e for e, al in p.env_aliases.items() if env_arg.lower() in al), env_arg.lower()
                )
            return {"type": "code.deploy", "pattern": "deploy_tool", "env": env, "command": tool}
        a = analysis_for(i, p.shell_tools)
        if a is None:
            return None
        best: dict[str, Any] | None = None
        for seg in a.all_segments():
            hit = _classify_segment(seg, p)
            if hit and (
                best is None
                or _RANK[hit["type"]] > _RANK[best["type"]]
                or (best.get("feature") and not hit.get("feature") and hit["type"] == best["type"])
            ):
                best = hit
        if best is None:
            return None
        env = best.get("env") or _env(a.text, p)
        if env is None and best.get("protected"):
            env = "mainline"
        best["env"] = env
        best["command"] = mask(a.text, 120)
        return best

    async def enrich(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> None:
        await super().enrich(ctx, interaction, cfg)
        p: Act04Params = self.params(cfg)
        f = self._analyze(interaction, p)
        if f is None:
            return
        interaction.meta[META] = f
        labels: dict[str, Any] = {"pattern": f["pattern"]}
        if f.get("env"):
            labels["env"] = f["env"]
        if f.get("force"):
            labels["force"] = "true"
        resource = None
        if f["type"] == "package.install" and f.get("packages"):
            resource = f"pkg:{f['ecosystem']}/{f['packages'][0]}"
        if f.get("feature"):
            refine(interaction, labels=labels)
            return
        refine(interaction, action_type=f["type"], resource=resource, labels=labels)

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        p: Act04Params = self.params(cfg)
        f = interaction.meta.get(META)
        if not isinstance(f, dict):
            f = self._analyze(interaction, p)
        if f is None:
            return None
        ex = Explain(
            facts={
                "environment": f.get("env"),
                "pattern_id": f["pattern"],
                "command": f.get("command"),
                "force": bool(f.get("force")),
            }
        )
        agent = ctx.identity.agent_id or ctx.identity.member_id or "someone"
        if f.get("feature"):
            act = p.feature_branch_push
            ex.check(
                "branch",
                "push target",
                f.get("branch"),
                ",".join(p.protected_branches),
                "pass",
                f"{P}.protected_branches",
            )
            if act in ("allow", "log"):
                return self.note(
                    cfg,
                    interaction,
                    core=f"git push to feature branch {f.get('branch')}",
                    action=act,
                    explain=ex,
                    action_type="code.deploy",
                )
        typ = f["type"]
        act = p.category_actions.get(typ, "require_approval")
        env = f.get("env")
        what = {
            "code.deploy": "deploy",
            "package.install": "package install",
            "code.exec": "code execution",
        }[typ]
        core = f"{what} ({f['pattern'].replace('_', ' ')}{', env ' + env if env else ''}{', force' if f.get('force') else ''})"
        ex.check(
            "category",
            "action for category",
            typ,
            act,
            "fail" if act in ("require_approval", "block") else "info",
            f"{P}.category_actions.{typ}",
        )
        if act == "allow":
            return None
        if act == "log":
            return self.note(cfg, interaction, core=core, action="log", explain=ex, action_type=typ)
        if act == "block":
            return self.hard(cfg, interaction, core=core, explain=ex, action_type=typ)
        return await self.soft(
            ctx,
            interaction,
            cfg,
            action="require_approval",
            core=core,
            explain=ex,
            action_type=typ,
            title=f"{agent} wants to run a {what}{' to ' + env if env else ''}",
            resource=interaction.resource,
            findings=[
                self.finding(
                    f"act.code.{f['pattern']}",
                    category="command",
                    severity="high" if typ == "code.deploy" else "medium",
                    excerpt=f.get("command"),
                )
            ],
        )


CONTROLS = [CodeDeployGuard()]
