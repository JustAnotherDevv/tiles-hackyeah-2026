# 08 · org-rbac: organization, members, roles & permissions

> Workstream **org-rbac** · task prefix **ORG** · planner output for ONE implementer (~60–120 min must+should).
> Binding inputs: `docs/BRIEF.md` §Product vision 4 (org governance), `docs/CONTRACTS.md` §1.2, §2.1, §3.1–3.5, §4.4–4.5, §5.2–5.5, §6.1–6.5, §7, §8 (F4, F5).
> Staging inputs: `staging/seed/org.seed.yaml` (the seed), `staging/seed/policy.yaml` (GOV-01/GOV-02 entries), `staging/seed/approvals.yaml` (`principals:` block), `staging/seed/SCENARIOS.md` (scenario 11 and Appendix A), `staging/design/prototype/assets/view-org.js` (capability matrix), `staging/submission/DEMO_RUNBOOK.md` (`X-Aegis-View-As: admin`), `staging/spikes/claude-code/FINDINGS.md` (`X-Aegis-Agent: claude-code`).

---

## 1. Goal & demo value

Aegis needs a real **who-is-who** layer, because every other control depends on it: budgets are scoped per org, team or agent; approvals route by role and sponsor; the live feed attributes each decision to a principal. This workstream delivers:

1. **The Acme Capital org from the seed, persisted in SQLite**: 1 org, 3 teams, 8 human members (1 owner, 2 admins, 5 members) and 5 agents. Agents are service identities, each with a human sponsor; one is disabled for demo purposes. The org also has HMAC-hashed API keys (one revoked and one expired example) and a resources inventory (databases, tables by sensitivity, vendors, hosts).
2. **Identity resolution on the hot path** (`rt.org.resolve_identity`). Every model, MCP, hook and egress request becomes a principal such as `agent:trading-copilot@trading` (team `trading`, sponsor `u_piotr`). Order of precedence: an `aegis_…` key, then `X-Aegis-Agent`, then `X-Aegis-Member`, then hints, then anonymous. All lookups are in-memory, about 10–30 µs.
3. **"View as" demo auth** (`rt.org.resolve_viewer`). Sources: the `X-Aegis-View-As` header, `?view_as=`, or the `aegis_view_as` cookie. Values can be member ids, role aliases (`owner`/`admin`/`member`, as used in DEMO_RUNBOOK) or short names (`emily`). This drives the dashboard role switcher and every RBAC check in `/api/*`.
4. **A permission matrix**: what owner, admin, member and agent may do (view/edit policy, budgets, members, agents, keys, kill switch, audit export) and **which approval levels each role satisfies**. Policy-dependent rows are computed live from the current policy's approval rules, so when a judge edits a rule, the "Roles & permissions" tab changes too.
5. **Governed org changes.** An admin may manage members, but **promoting someone to admin, any owner grant or revoke, and deactivating a privileged member need an owner**. The change becomes a real approval request (`rt.approvals.create_manual`, action type `org.*`). An owner approves it in the same Approvals inbox, an executor applies it, and the audit log gets `org.changed` (pending → applied). The SSE event `org.updated` refreshes the org page live. Invariants are hard-coded: you can't change your own role, the last owner can't be removed, and the person being promoted can't approve their own promotion.
6. **Two MVP controls.** **GOV-01** covers caller identity and attribution: it blocks revoked, expired or unknown keys, principal spoofing (key ≠ `X-Aegis-Agent`) and disabled agents, and it applies `require_auth`. **GOV-02** covers the model allowlist and destination tiering: the policy allowlist ∩ the agent's allowlist, plus the tier ceiling. `research-agent@research` is local-only, so it can never reach a remote model. Optionally, a RESTRICTED-data reroute to the local model.

**What judges see:**
- The org page: members with role badges and sponsored agents, agents with status and spend today, teams.
- The view-as switcher changes what's enabled in the UI.
- *"Marek (admin) promotes Piotr to admin → 403 approval_required, needs owner → switch to Katarzyna → Approve → Piotr is now admin, audit shows who/when/via apr_…"*.
- A revoked key replayed against `/v1/messages` is blocked by GOV-01.
- The trading copilot asking for `gpt-4.1-mini` is blocked by GOV-02 ("model not in agent allowlist").
- The research agent pointed at a remote model is blocked ("local-only agent").

**Judging criteria served:**
- Guardrail robustness: authn/authz is the deterministic leg of "hybrid guardrails".
- Security reporting: attribution on every decision, plus audited org changes.
- Practical implementability & scalability: multi-tenant columns, HMAC-only key storage, O(1) identity lookup, approvals for privilege escalation.
- Architecture: a clean service boundary through `rt.org`.

---

## 2. Design

### 2.1 Files (all inside org-rbac ownership, CONTRACTS §1.2)

| Path | Purpose |
|---|---|
| `config/org.seed.yaml` | Port of `staging/seed/org.seed.yaml` with contract fixes (§3). |
| `config/snippets/org-rbac.yaml` | Policy entries: GOV-01, GOV-02 and the `org.*` approval rules (§9). |
| `src/aegis/org/__init__.py` | Docstring only (no import-time side effects). |
| `src/aegis/org/models.py` | Private pydantic models: `SeedDoc` (+ `SeedTeam/SeedMember/SeedAgent/SeedApiKey`, `extra="allow"`), `KeyRecord`, `OrgChange`, `Authz`, `CapabilityCell`, `ResolvedIdentity(Identity)`. |
| `src/aegis/org/seed.py` | `load_seed(path) -> SeedDoc`, `map_seed(doc) -> SeedBundle` (contract §4.5 mapping), `apply_seed(conn, bundle, *, reset)`, CLI `main(argv) -> int` (`--check`, `--reset`, `--path`). Target of `python -m aegis seed`. |
| `src/aegis/org/store.py` | Sync SQLite layer, called via `asyncio.to_thread`: DDL (contract tables + `org_changes`, `org_meta`), row ↔ model mapping, CRUD, `busy_timeout=5000`. |
| `src/aegis/org/identity.py` | Pure functions over the in-memory cache: `extract_aegis_key(headers)`, `resolve(cache, headers, hints, now) -> ResolvedIdentity`, `resolve_alias(cache, value)`, `parse_cookie(headers)`. |
| `src/aegis/org/permissions.py` | Capability table, op → action_type/default level/hard floor, `authorize(...) -> Authz`, `whoami_permissions(...)`, `matrix(...)`. |
| `src/aegis/org/changes.py` | Governed-change workflow: `request_change`, `apply_change`, `org_executor`, `reconcile`. |
| `src/aegis/org/service.py` | `OrgServiceImpl` (implements `OrgService` + private helpers) and `create(rt)`. |
| `src/aegis/controls/governance/__init__.py` | Empty. |
| `src/aegis/controls/governance/_common.py` | Helpers: `DEST_RANK`, `norm_model(name)`, `first_glob(patterns, value)`, `peek_agent(rt, id)` (fast path to the org cache). |
| `src/aegis/controls/governance/gov01_identity.py` | `CONTROLS = [CallerIdentity()]`. |
| `src/aegis/controls/governance/gov02_models.py` | `CONTROLS = [ModelAllowlist()]`. |
| `src/aegis/api/routes/org.py` | `router` (absolute paths), `ORDER = 100`, `async def on_startup(rt)` (registers the executor, starts the approval listener, runs the first reconcile). |
| `tests/unit/org_rbac/{conftest,test_seed,test_store,test_identity,test_viewer,test_permissions,test_changes,test_routes,test_gov01,test_gov02,test_perf,test_integration}.py` | Unit tests with a fake runtime (§2.10). |

### 2.2 Data model and persistence

Contract tables (CONTRACTS §6.1, verbatim): `orgs`, `teams`, `members`, `agents`, `api_keys`. Two additional **org-rbac-private** tables (additive, see Contract gaps G7):

```sql
CREATE TABLE IF NOT EXISTS org_meta (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
  -- seed_version, seed_sha256, seeded_at, hmac_canary (hmac_hex("aegis-org-canary", purpose="apikey"))
CREATE TABLE IF NOT EXISTS org_changes (id TEXT PRIMARY KEY, op TEXT NOT NULL, action_type TEXT NOT NULL,
  target_type TEXT NOT NULL, target_id TEXT, patch_json TEXT NOT NULL, before_json TEXT NOT NULL DEFAULT '{}',
  requested_by_json TEXT NOT NULL, approval_id TEXT, required_role TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending','applied','denied','expired','cancelled','failed')),
  created_at TEXT NOT NULL, decided_at TEXT, result_json TEXT);
CREATE INDEX IF NOT EXISTS ix_org_changes_status ON org_changes(status, created_at);
```

- `api_keys.principal` is stored as `agent:<id>` or `member:<id>`, matching `Identity.principal`. `key_hmac = aegis.core.crypto.hmac_hex(key, purpose="apikey")`. **Plaintext keys are never stored or logged.**
- `members` and `agents` preserve seed order through `rowid`. "First owner" means the lowest `rowid` with `role='owner'`.
- **In-memory cache (`OrgCache`)**: `org`, `teams{id}`, `members{id}`, `agents{id}`, `keys_by_hmac{hmac: KeyRecord}`, `sponsored{member_id: [agent_ids]}`, `aliases{lower: member_id}`, `agent_aliases{short: agent_id}` and `resources` (dict). It is loaded in `start()` and rebuilt after every write. The service is the only writer, guarded by an `asyncio.Lock`.
- **`resources()`** returns the seed's `resources` section, parsed at every start (the config file is the source of truth for inventory; it is cheap).
- **HMAC canary.** At start, compare `org_meta.hmac_canary` with the current `hmac_hex`. On mismatch (the HMAC key rotated without a DB wipe), re-hash the seed-origin keys from the seed file and log a WARNING. Runtime-issued keys become invalid, which is logged.

### 2.3 Seed loading (`aegis.org.seed`)

- `start()` creates the tables and, **if `orgs` is empty**, seeds from `settings.org_seed` (env `AEGIS_ORG_SEED`, default `config/org.seed.yaml`). A relative path is resolved against the CWD, then against the repo root (`Path(__file__).parents[3]`).
- Seed changed on disk since the last seed (sha differs): INFO log "run `python -m aegis seed --reset`". Never auto-wipe runtime changes.
- Invalid seed with an empty DB: ERROR. Fall back to a minimal org (`acme-capital`, owner `u_katarzyna` only) and set `health()="degraded"`, so the gateway stays usable.
- **Mapping (CONTRACTS §4.5, exactly):**
  - member `teams[0]` → `team_id` (all teams in `meta.teams`); `title` → `title`; `locale`, `view_as_label`, `avatar_color`, `owner_delegate` → `meta`.
  - agent `sponsor` → `owner_member_id`; `display_name` → `name`.
  - `kind`: `coding_agent` → `claude-code`, `local_agent` → `scripted`, `remote_agent` → `sdk`, anything else (incl. `red_team`) → `other`. The original value goes to `meta.seed_kind`.
  - `models.allowed` → `allowed_models`. Strip provider prefixes `anthropic/ openai/ ollama/ openrouter/ mock/` (but not `meta-llama/`). Map `qwen3.5:0.8b` → also add `aegis-judge*`, and `mock/echo-llm` → `mock-echo`.
  - `tools.allow/deny` → `allowed_tools/denied_tools`, converting `mcp__<server>__<tool>` → `<server>.<tool>` (globs preserved: `mcp__*__send_*` → `*.send_*`).
  - `max_destination_tier` T0/T1/T2 → `max_destination` local/remote/third_party (`max_destination:` is also accepted directly).
  - `profile_override` → `profile`.
  - `data_grants`, `action_types`, `location`, `integration`, `demo`, `models.default` → `meta`.
  - `status: disabled` or `active: false` → `active=False`.
  - teams: `lead`, `data_ceiling`, `default_destination_tier` → `meta`.
  - `api_keys[]` → hashed rows. `revoked_at` and `expires_at` are kept; datetimes are parsed with offsets and stored as ISO UTC.
  - `control_plane.view_as_aliases` / `default_viewer` → alias map.
  - `budgets`, `demo_state` and `roles` are **ignored** by org-rbac (budgets are ported into policy by policy-engine).
- **Validation (fail loudly in `--check`):** unique ids; every sponsor/team/principal exists; at least one active owner; roles ∈ {owner, admin, member}; keys start with `aegis_`.
- **CLI** `main(argv)`:
  - `--check`: parse and validate, print a summary, no DB access. Exit 1 on error.
  - `--reset`: delete the org-rbac tables, then reseed.
  - Default: seed only if empty.
  - Opens `<data_dir>/aegis.db` directly (WAL) when there is no Runtime.
  - Example summary: `org acme-capital: teams=3 members=8 (owners=1 admins=2) agents=5 (inactive=1) keys=6 (revoked=1 expired=1)`.

### 2.4 Identity resolution (`resolve_identity`, data plane)

`ResolvedIdentity(Identity)` is a private subclass that adds `auth_method: Literal["api_key","header","hint","anonymous"]`, `key_id`, `key_scopes: list[str]`, `credential_error: Literal["unknown_key","revoked","expired"] | None`, `asserted_agent_id`, `principal_mismatch: bool`, `known: bool` and `principal_active: bool`. Pydantic v2 keeps subclass instances in `RequestContext.identity: Identity` and serializes them **as `Identity`**, so the extra fields never reach JSON or SSE (see Contract gap G1).

Algorithm (headers lower-cased; never raises; on internal error returns an anonymous identity and logs a WARNING):
1. **Key**: the first value starting with `aegis_` among `authorization: Bearer …` (case-insensitive scheme), `x-api-key`, `x-aegis-key`. Non-`aegis_` values are ignored and never consumed. `hmac_hex(key, purpose="apikey")` → `keys_by_hmac`:
   - not found → `credential_error="unknown_key"`, principal anonymous.
   - `revoked_at` → `"revoked"`; `expires_at < now` → `"expired"`. In both cases the identity is attributed to the key's principal with `authenticated=False`.
   - valid → principal identity with `authenticated=True`, `auth_method="api_key"`, `key_id`, `key_scopes`.
   - If `x-aegis-agent` is also present and resolves to a different agent → `principal_mismatch=True`, `asserted_agent_id=…`. The key still wins for attribution.
2. **`X-Aegis-Agent`**: exact id; else alias (`claude-code` → `claude-code@platform` when unique); else an unknown agent (`known=False`, `agent_id` = the value, trimmed to 64 chars).
3. **`X-Aegis-Member`**: member id or alias → member identity (`role` = the member's role).
4. **hints** (`agent_id`, `member_id`, `team_id`) → same as 2 or 3 with `auth_method="hint"`.
5. Else **anonymous agent**: `Identity(org_id=<org>, agent_id="anonymous", role="agent")`.

Field filling:
- **Agent identity**: `org_id`, `team_id=agent.team_id`, `agent_id`, `member_id=agent.owner_member_id` (the sponsor, as the frozen docstring says), `role="agent"`, `display_name=agent.name`, `principal_active=agent.active`.
- **Member identity**: `team_id` = `X-Aegis-Team` if the member belongs to that team, else `member.team_id`.

**`last_seen`**: updated in memory on every agent resolution. Flushed to SQLite at most once per 30 s per agent via `asyncio.create_task(asyncio.to_thread(...))`. Skipped in `AEGIS_TEST_MODE=1`; flushed on `stop()`.

### 2.5 Viewer resolution (`resolve_viewer`, dashboard)

**Sources, in order:** the `x-aegis-view-as` header, then `query["view_as"]`, then the `aegis_view_as` cookie (parsed from the `cookie` header).

**Value resolution:**
- A member id.
- Role aliases (`owner` → `u_katarzyna`, `admin` → `u_emily`, `member` → `u_piotr`, from `control_plane.view_as_aliases`).
- A case-insensitive short name (`emily` → `u_emily`, `u_` prefix optional).
- Otherwise (or when no value is given) the default viewer: `settings.default_viewer` (`AEGIS_DEFAULT_VIEWER`), else the first active owner. An unknown value logs a WARNING.

**Result:** `Identity(org_id, team_id, member_id, role=member.role, display_name=member.name, authenticated=False)`. An inactive member keeps its role in the Identity, but `permissions.py` treats it as having no capabilities.

**`AEGIS_DEMO_MODE=0` (could):**
- View-as is honoured only with `Authorization: Bearer <AEGIS_ADMIN_TOKEN>` or the seed's `control_plane.admin_token`, compared with `hmac.compare_digest`. In that case the viewer is resolved normally with `authenticated=True`.
- Otherwise the viewer is a read-only `Identity(role="member", member_id=None, display_name="anonymous viewer")`.

### 2.6 Permission matrix (`aegis.org.permissions`)

**Roles:** `owner > admin > member > agent`, using the frozen `ROLE_RANK`. Approver levels map onto ranks through the frozen `APPROVER_RANK` (`self` = 1, `admin` = 2, `owner` = 3). **No `viewer` role**: `Role`/`ViewRole` are frozen and `members.role` has a CHECK constraint, so a read-only persona would need every other owner to honour a flag. It is out of scope (see Risks).

**Capabilities** (rows of `GET /api/org/permissions`; also used by `whoami`):

| Capability id | Owner | Admin | Member | Agent | Source |
|---|---|---|---|---|---|
| `org.view` (dashboards, decisions, audit) | yes | yes | yes | no | static |
| `approvals.self` (own requests, or the sponsored agent's `self`-level ones) | yes | yes | yes (own) | no | contract §3.5 |
| `approvals.admin` (data access, $20–200 spend, deploys, MCP re-pins…) | yes | yes | no | no | approval levels from `approvals.rules` |
| `approvals.owner` (>$200 spend, prod writes, large raises, control disables) | yes | no | no | no | same |
| `policy.edit` | yes | partial (tightening and small changes; loosening → owner) | approval | no | `rt.approvals.route(kind="config_change", …)` over representative `PolicyChange`s |
| `budgets.raise` | yes | partial (≤ +50% team, ≤ +100% member/agent) | approval | no | same |
| `killswitch.engage` / `killswitch.release` | yes / yes | yes / yes | approval / approval | no | same (`killswitch.on/off`) |
| `audit.export` | yes | yes | no | no | contract §5.4 |
| `members.manage` | yes | partial (members; admin/owner grants need owner) | no | no | org op table below |
| `agents.manage`, `agents.keys` | yes | yes | no | no | org op table |
| `feed.refresh`, `mcp.repin` | yes | yes | no | no | contract §5.4 |

**Org ops** (each has an `action_type` for approval routing, a **default level** that the snippet rules mirror, and a **hard floor** that policy cannot lower):

| op | action_type | default level | hard floor |
|---|---|---|---|
| create member (role member) | `org.member.create` | admin | admin |
| create member (role admin) | `org.member.create_admin` | owner | admin |
| create member (role owner) | `org.member.create_owner` | owner | **owner** |
| update name/title/team | `org.member.update` | admin | admin |
| member → admin | `org.role.promote_admin` | owner | admin |
| → owner | `org.role.promote_owner` | owner | **owner** |
| admin → member | `org.role.demote_admin` | owner | admin |
| owner → * | `org.role.demote_owner` | owner | **owner** |
| deactivate/reactivate a member | `org.member.deactivate` | admin | admin |
| deactivate/reactivate an admin/owner | `org.member.deactivate_privileged` | owner | **owner** |
| agent update (active/models/tools/profile/denied_tools) | `org.agent.update` | admin | admin |
| agent `max_destination` loosened (e.g. local → remote) | `org.agent.widen_destination` | owner | admin |
| agent key issue/revoke | `org.agent.key` | admin | admin |
| agent create (could) | `org.agent.create` | admin | admin |

**`authorize(viewer, op, target, patch) -> Authz(decision: "direct"|"approval"|"forbidden"|"conflict", required: ApproverLevel, action_type, rule_id, reason)`:**
1. The viewer is an agent, inactive, or below admin (no `members.manage`) → `forbidden`.
2. **Invariants:**
   - Changing your own role or deactivating yourself → `forbidden`.
   - Demoting or deactivating the **last active owner** → `conflict` (409).
   - An unknown team, role or member → `invalid` (400).
3. Determine the level:
   - `route = rt.approvals.route(kind="action", action_type=…, requester=viewer, resource=f"member:{id}", labels={"category": "org", "to_role": …})`. If it raises, use the default level.
   - `level = max(route.required_role, floor)`.
   - `deny` → `forbidden` ("denied by rule <id>").
4. If the viewer's rank satisfies `level` and `route.two_person` is false (and the level is not `auto`-below-floor) → `direct` ("authorized: owner ≥ owner"). Otherwise → `approval`.

**`whoami_permissions(viewer, snap) -> Permissions`** (frozen TS shape):
- `can_apply_policy`: `yes` if the viewer satisfies the highest non-deny level among `config_rules` ∪ `default_config_approver` (owner in practice); `approval` for active members and admins; `no` for agents and inactive members.
- `can_manage_members`: admin and above.
- `can_killswitch`: the viewer satisfies the level routed for `killswitch.on` (admin by default).
- `can_export_audit`: admin and above.
- `approver_levels`: `self` for active members; `+admin` for admins; `+owner` for owners.

### 2.7 Governed org changes (`aegis.org.changes`)

Flow for `POST /api/members` and `PATCH /api/members/{id}` (and `PATCH /api/agents/{id}` when widening the destination):
1. Validate the body, compute `before`, and run `authorize(...)`. A patch that mixes gated and ungated fields is **gated as a whole** and applied atomically on approval.
2. **`direct`**:
   - `apply_change` runs the DB write in a thread under the lock and refreshes the cache.
   - It records `org.changed` (with `data = {op, target, before, after, via: "direct", authz}`) and publishes `org.updated` ({member} or {agent}).
   - It returns 200 (POST: 201) with the `Member` or `Agent`.
3. **`approval`**:
   - Dedupe: if an `org_changes` row is pending for the same `(target, op)` and its approval is still pending, reuse it.
   - Otherwise insert `org_changes(status=pending)`, then call `apr = await rt.approvals.create_manual(viewer, ApprovalDraft(kind="action", action_type, title, summary, resource, labels, payload))`.
     - Example `title`: "Promote Piotr Zieliński to admin".
     - Example `summary`: "Requested by Marek Kowalczyk (admin): member → admin. Needs owner."
     - `resource`: `member:u_piotr`.
     - `labels`: `{"category": "org", "op": op, "to_role": "admin"}`.
     - `payload`: `{"org_change_id", "op", "target", "patch", "before"}`, with emails masked (`k***@acme-capital.example`).
   - Store `approval_id`.
   - If `apr.status == "approved"` (auto) → apply now. If `"denied"` (e.g. the Null approvals service fails closed) → mark the change denied and return **403 `forbidden`** "approvals unavailable — ask an owner".
   - Otherwise return **403 `approval_required`** using the §5.3 envelope: `{type, message: "Promoting Piotr Zieliński to admin needs owner approval", approval_id, required_role: "owner", expires_at}`. Audit `org.changed` with `data.outcome="pending_approval"`.
4. **`forbidden` / `conflict`** → 403 / 409 envelopes. Denied privilege-escalation attempts are also audited (`org.changed`, `data.outcome="forbidden"`), so the audit log shows the attempt.

**Execution on approval** (three layers, idempotent through `org_changes.status` transitions under the lock):
- **Primary:** `on_startup` calls `rt.approvals.register_executor("action", org_executor)`. `org_executor(req)`:
  - Returns `None` immediately unless `req.action_type.startswith("org.")`, so it preserves the contract's "action → none".
  - Loads the change and re-checks the **hard floor against the actual approvers** (`decided_by` members' roles). The **target member must not be among the approvers**, and the last-owner invariant must still hold.
  - Applies the change. Audit actor = the last approver, `data.via="approval"`, `approval_id`, `requested_by`.
  - Returns `{"applied": true, "org_change_id", "target", "after"}`, or `{"applied": false, "reason"}` (never raises).
- **Secondary:** an `on_startup` background task, `rt.bus.subscribe({"approval.updated"})`, calls `reconcile(apr_id)` for `org.*` action types. Skipped when `AEGIS_TEST_MODE=1`.
- **Fallback:** `reconcile()` (all pending changes) runs at the start of `GET /api/members`, `GET /api/org/changes` and `GET /api/whoami`. For each pending change it calls `rt.approvals.get(id)`:
  - `approved` and not applied → apply.
  - `denied`, `expired` or `cancelled` → mark the change accordingly and audit it.

### 2.8 Controls

**GOV-01 Caller identity & attribution** (`gov01_identity.py`):
- `kind="deterministic"`, `priority=1`, `applies_to=AppliesTo()` (all surfaces).
- `owasp=["ASI03","ASI07","MCP07:2025","LLM03:2026"]`.
- Params (pydantic, all optional): `require_auth: bool|None` (None → `snap.doc.defaults.require_auth`), `require_auth_sources=["proxy","mcp","hook","egress","guard"]`, `anonymous_action="allow"`, `unknown_agent_action=None` (None → `cfg.action`, i.e. `log`), `block_inactive=True`, `block_invalid_keys=True`, `block_principal_mismatch=True`, `enforce_key_scopes=False`, `exempt_agents=["selftest"]`.

Evaluation order (`id = ctx.identity`; `ResolvedIdentity` fields are read via `getattr(..., default)`, so a plain `Identity` from self-tests still works):
1. `agent_id ∈ exempt_agents` → `None`.
2. `credential_error` → **block**: `http_status=401`, `error_type="unauthenticated"`, reason "Aegis API key key_revoked_demo revoked", finding `gov.key_revoked|gov.key_expired|gov.key_unknown` with `category="governance"` and `meta={"key_id"}`. The key itself is never included.
3. `principal_mismatch` → **block**, 403 `policy_blocked`: "X-Aegis-Agent 'trading-copilot@trading' does not match key principal 'research-agent@research'".
4. The principal is known but inactive (agent `active=False` via `peek_agent`/`rt.org.get_agent`; member inactive) → **block**, 403: "agent legacy-bot@platform is disabled".
5. `require_auth` effective, `ctx.source ∈ require_auth_sources` and not `authenticated` → **block**, 401: "authentication required".
6. Unknown agent id (header-asserted, not registered) → `unknown_agent_action` (default `log`): "unregistered agent 'x' (header-asserted)".
7. Anonymous → `anonymous_action` (default `allow` → `None`). Attribution as `agent:anonymous` is already on the decision.
8. (Could) `enforce_key_scopes`: map source/surface → scope (`hook`→`hooks`, `mcp`→`mcp`, model surfaces → any of `anthropic.messages|openai.chat|ollama.chat`). If the scope is missing → `log` finding (or `block` when the param is `"block"`).

**GOV-02 Model allowlist & destination tiering** (`gov02_models.py`):
- `kind="deterministic"`, `priority=15`, `applies_to.surfaces={"model.request","model.admin"}`.
- `owasp=["LLM03:2026","LLM06:2026","LLM02:2026","ASI10"]`.
- Params: `enforce_policy_allowlist=True`, `enforce_agent_allowlist=True`, `enforce_tier_ceiling=True`, `on_tier_violation="block"` (`"reroute"` → route mutation), `reroute_on_class: dict[DataClass, DestClass] = {}`, `reroute_model=None` (None → `snap.doc.models.default_local`).
- `snap = ctx.policy or rt.policy.snapshot()`. The agent comes from `peek_agent` (members and unknown agents only get the policy checks).

Evaluation:
1. **Tier ceiling** (also without a model name): `DEST_RANK[interaction.destination.dest_class] > DEST_RANK[agent.max_destination]`.
   - `block`: "research-agent@research is local-only; destination remote not allowed".
   - Or reroute: `Decision(action="redact", mutations=[Mutation(target="route", path="model", value=reroute_model, reason="tier ceiling")])` when the reroute model is in the agent's allowlist.
2. `model = norm_model(interaction.model)` (strip whitespace; keep `:tag`). If `None` → done.
3. **Policy:**
   - Matching `models.denied` → **block** "model qwen3:cloud denied by policy (*:cloud)".
   - Not matching `models.allowed` → **block** "model x not in policy allowlist".
4. **Agent:** the model doesn't match `agent.allowed_models` → **block** "model gpt-4.1-mini not in agent trading-copilot@trading allowlist". The finding meta includes `allowed` (globs).
5. (Should) `reroute_on_class`: if the destination is not local, run `await asyncio.to_thread(rt.redactor.detect, interaction.text())` (deterministic, no NER). If any span's data class is a key in the map and the reroute model is allowed for the agent → `redact` + route mutation: "RESTRICTED data → rerouted to aegis-judge (local)".

All reasons are short and human-readable. They are shown verbatim in the synthetic `[Aegis] Blocked by GOV-02: …` reply.

### 2.9 HTTP endpoints served (`src/aegis/api/routes/org.py`)

**Contract endpoints (§5.4)**: shapes are the frozen TS types:

| Method & path | Min role | Response | Notes |
|---|---|---|---|
| `GET /api/org` | member | `OrgResponse` | + additive `meta: {description, timezone, email_domain, seed_version, policy_profile}` |
| `GET /api/members` | member | `{items: Member[]}` | each item + `agents: string[]` (sponsored ids) + `meta.pending_changes: [{org_change_id, approval_id, op, to, required_role, expires_at}]`; optional `?team_id=&role=&active=`; runs `reconcile()` first |
| `POST /api/members` | admin (owner/admin creation per §2.6) | `Member` (201) or 403 `approval_required`/`forbidden` | body `{name, email, role, team_id}`; id = `u_<slug(first name)>` (+ digit if taken) |
| `PATCH /api/members/{id}` | admin (role gating §2.6) | `Member` or 403/409 | body `{role?, team_id?, active?}` (+ additive `title?`, `name?`) |
| `GET /api/agents` | member | `{items: Agent[]}` | each item + `status` (`killed` if `active=false` or the kill switch (global/team/agent glob) hits it in `snap.doc.budgets.kill_switch`; `active` if `last_seen` < 10 min; else `idle`), `spend_today_usd` (from `rt.ledger.status(scope="agent:<id>")`, usd/day `used`, 0.0 if absent; gathered with a 200 ms timeout), + additive `keys: ApiKeyView[]` (no hashes) |
| `PATCH /api/agents/{id}` | admin | `Agent` | body `{active?, allowed_models?, allowed_tools?, profile?}` (+ additive `denied_tools?`, `max_destination?`, `owner_member_id?`) |
| `GET /api/whoami` | any | `WhoAmI` | + additive `capabilities: Record<string, 'yes'|'approval'|'partial'|'no'>`, `view_as_options: [{member_id, name, role, label, team_id}]` |

**Additive endpoints** (under org-rbac-owned prefixes `/api/org*`, `/api/members*`, `/api/agents*`; see Contract gap G4):

| Method & path | Min role | Response |
|---|---|---|
| `GET /api/members/{id}` | member | `Member` (+ `agents`, `meta.pending_changes`) |
| `GET /api/org/permissions` | member | `OrgPermissionsResponse` (§4.3) |
| `GET /api/org/changes?status=` | member | `{items: OrgChange[]}` (pending and history) |
| `GET /api/agents/{id}/keys` | admin | `{items: ApiKeyView[]}` |
| `POST /api/agents/{id}/keys` | admin | `ApiKeyCreated` (plaintext `key` shown **once**, `aegis_` + `secrets.token_urlsafe(32)`) |
| `POST /api/agents/{id}/keys/{key_id}/revoke` | admin | `ApiKeyView` (immediate effect: cache refresh) |
| `POST /api/agents` (could) | admin | `Agent` (body `{id, name, team_id, owner_member_id, kind, allowed_models, allowed_tools, max_destination}`) |

**Errors** use `aegis.core.errors.api_error` (§5.3 envelope). If that import fails, a local fallback builds the same envelope. Types used: `forbidden` (403), `approval_required` (403), `conflict` (409), `invalid_request` (400), `not_found` (404, additive), `unavailable` (503, when `rt.org` is not `OrgServiceImpl`; read endpoints still work via protocol methods with the Null org).

**RBAC in routes:** `viewer = await rt.org.resolve_viewer(request.headers, request.query_params)`, then `permissions.authorize(...)`. `rt` comes from `aegis.core.deps.get_rt` if importable, else `request.app.state.rt`. The `AEGIS_ADMIN_TOKEN` check stays in core-gateway.

**Events and audit:**
- Bus `org.updated` (`{member}` or `{agent}`, `mode="json"`) after every applied change (not for `last_seen`).
- `AuditEvent(event_id=new_id("evt"), event_type="org.changed", actor=<viewer or approver Identity>, resource="member:<id>"|"agent:<id>", reason=<summary>, data={op, target, before, after, via, outcome, approval_id, rule_id, requested_by})` for: seeding (`op="seed"` with counts and seed_version), direct changes, pending requests, approvals applied/denied/expired, forbidden attempts, key issue/revoke.

### 2.10 Config keys read

- **Settings** (via `getattr(rt.settings, …, default)`): `org_seed`, `demo_mode`, `default_viewer`, `admin_token`, `test_mode`, `data_dir`.
- **Policy snapshot:** `defaults.require_auth`; `models.allowed/denied/default_local`; `budgets.kill_switch`; `approvals.rules/config_rules/defaults` (only through `rt.approvals.route`, plus a read of `config_rules` for the permission matrix); `controls[GOV-01|GOV-02].params`.

**Test harness (`tests/unit/org_rbac/conftest.py`):** `FakeRT` with:
- `settings` (SimpleNamespace)
- `db()` → tmp sqlite (WAL, Row factory)
- `bus` (captures `publish`; `subscribe` yields nothing)
- `audit` (captures events)
- `policy.snapshot()` → `PolicySnapshot(version=1, sha256="t", doc=PolicyDoc.model_validate(<dict with snippet rules + contract §4.3 models/approvals>), controls={GOV-01, GOV-02})`
- `approvals`: `FakeApprovals` with first-match `route` over the doc rules, `create_manual` → pending `ApprovalRequest`, `get`, `vote` that sets approved/decided_by and runs the registered executor, `register_executor`
- `ledger.status()` → `[]`
- `redactor.detect` → regex PAN stub

Route tests mount `router` on a bare `FastAPI()` with `app.state.rt = FakeRT`.

---

## 3. Reuse map (staging → owned paths)

| Staging file | Destination | Adaptation |
|---|---|---|
| `staging/seed/org.seed.yaml` | `config/org.seed.yaml` | Keep all binding ids (§4.5). Changes: (1) header comments updated (contract mapping; stale `approvals.yaml`/`limit_overrides` references removed). (2) `agents[].models.allowed` → wire globs: claude-code `["claude-*","aegis-judge*","qwen*","mock-*"]`; research-agent `["aegis-judge*","qwen*","hf.co/*"]`; trading-copilot `["claude-haiku-*","claude-sonnet-*","meta-llama/*","aegis-judge*","qwen*","mock-*"]` (no `gpt-4.1-mini` and no `claude-opus-*`, so GOV-02 demo blocks work); chaos-agent `["aegis-judge*","qwen*","claude-haiku-*","mock-*"]`. (3) Tools in `<server>.<tool>` form and broadened so GOV-03 doesn't pre-empt MCP/approval demos: claude-code allow built-ins `[Read, Glob, Grep, LS, Edit, MultiEdit, Write, NotebookEdit, Bash, TodoWrite, Task, WebSearch]` + `"*.*"` (all MCP tools), deny `["acme-crm.export_*", "WebFetch"]`; research-agent allow `["acme-db.*","filesystem.read_*","marketpulse.*","payments.create_charge","web.fetch_url","weather.*"]`, deny `["*.send_*","mailer.*"]`; trading-copilot allow `["acme-crm.lookup_*","acme-db.*","marketpulse.*","mailer.send_email","payments.create_charge","web.fetch_url"]`, deny `["acme-crm.delete_*","trade.execute"]`; chaos-agent `["*"]`. (4) `max_destination: local|remote|third_party` (tier names still accepted). (5) **New disabled agent** `legacy-bot@platform` (sponsor `u_marek`, `active: false`, "retired after vendor ToS change"), used by the GOV-01 must-block self-test and the org page. (6) API key expiries → `2027-10-31`, so tests don't rot after 4 Oct; **new** `key_expired_demo` = `aegis_demo_expired_key_0000000000000098_NOT_A_SECRET` (chaos-agent, expired 2026-10-02); revoked key kept. (7) `resources.databases[].tables[].contains` → canonical entities (`PERSON, EMAIL, PHONE, PESEL, IBAN, ADDRESS, DOB`; `PAN, CARD_EXPIRY`); `mock:` → `mcp_server: acme-db`; `external_hosts[].tier` kept + `dest_class`. (8) `control_plane.view_as_aliases: {owner: u_katarzyna, admin: u_emily, member: u_piotr}`, `default_viewer: u_katarzyna`. (9) `budgets:` and `demo_state:` kept verbatim, with a comment saying they are consumed by policy-engine/budgets-ledger/approvals-engine, not by org-rbac. |
| `staging/seed/policy.yaml` GOV-01 / GOV-02 entries | `config/snippets/org-rbac.yaml` + control params | Translate per §1.4: `config` → `params`, `surfaces` → contract surfaces, `T0` → `local`, `examples` → `tests` (only cases expressible with `PolicyTest`). The staged key/spoof/no-key examples become unit tests and test-suite cases (§5, ORG-V08). The staged no-key → block 401 becomes `require_auth: true` behaviour, which is not the default (demo uses header identities). |
| `staging/seed/approvals.yaml` `principals:` | `permissions.py`, `changes.py` | `agents_can_approve: false` → agents never manage or approve; separation of duties → no self role change, the target can't approve their own promotion; `sole_owner_fallback` → **no** two-person rule for owner grants (one owner in the org); `owner_delegate` kept in `Member.meta` for approvals-engine. |
| `staging/seed/SCENARIOS.md` scenario 11 + Appendix A | GOV-02 tests, permission matrix examples | "Opus not in copilot allowlist" and "research agent can never reach T1" become GOV-02 unit tests. |
| `staging/design/prototype/assets/view-org.js` `CAPS` | `permissions.py` capability rows | Same rows, now computed from policy instead of hard-coded. |
| `staging/submission/DEMO_RUNBOOK.md` (`X-Aegis-View-As: admin`) | `identity.py` role aliases | `owner`/`admin`/`member` accepted as view-as values. |
| `staging/spikes/claude-code/FINDINGS.md` (`X-Aegis-Agent: claude-code`) | `identity.py` agent short aliases | `claude-code` → `claude-code@platform`. |

---

## 4. Interfaces

### 4.1 Provided (exactly as CONTRACTS)

**Service factory:** `aegis.org.service:create(rt) -> OrgServiceImpl` (cheap; tables, seed and cache in `async start()`; `async stop()` flushes `last_seen`). It implements `aegis.core.protocols.OrgService` verbatim:

```python
async def resolve_identity(self, headers: Mapping[str, str], *, hints: Mapping[str, str] | None = None) -> Identity
async def resolve_viewer(self, headers: Mapping[str, str], query: Mapping[str, str] | None = None) -> Identity
async def org(self) -> Org
async def list_teams(self) -> list[Team]
async def list_members(self) -> list[Member]
async def list_agents(self) -> list[Agent]
async def get_member(self, member_id: str) -> Member | None
async def get_agent(self, agent_id: str) -> Agent | None
async def members_with_role(self, min_role: Role, team_id: str | None = None) -> list[Member]
    # active members with ROLE_RANK >= min_role; team filter = team in meta.teams or team_id; owners always included (org-wide)
async def resources(self) -> dict[str, Any]   # {"databases": [...], "vendors": [...], "external_hosts": [...]}
```

All return copies (`model_copy(deep=True)`), so callers can't mutate the cache. Private extras (used only by org-rbac routes and controls): `peek_agent(id)`, `peek_member(id)` (no copy, hot path), `create_member`, `update_member`, `update_agent`, `issue_key`, `revoke_key`, `list_keys`, `list_changes`, `reconcile`, `health() -> "ok"|"degraded"`.

**Other provided items:**
- **Controls:** `CONTROLS = [CallerIdentity()]` (GOV-01) and `CONTROLS = [ModelAllowlist()]` (GOV-02), both `BaseControl` subclasses with the ClassVars of §2.8.
- **Route module:** `router: APIRouter`, `ORDER = 100`, `async def on_startup(rt)`.
- **CLI:** `aegis.org.seed:main(argv: list[str] | None = None) -> int` (dispatched by `python -m aegis seed`; also runnable as `python -m aegis.org.seed`).
- **SQLite:** contract org-rbac tables (§6.1) + `org_meta`, `org_changes`.
- **SSE:** `org.updated` → `{member?: Member; agent?: Agent}`.
- **Audit:** `org.changed`.
- **Config:** `config/org.seed.yaml` (`schema: aegis.org-seed/v1`), `config/snippets/org-rbac.yaml`.

### 4.2 Consumed

| From | What | If missing |
|---|---|---|
| scaffold (frozen) | `aegis.core.types` (`Identity, Org, Team, Member, Agent, Decision, Finding, Mutation, ApprovalDraft, ApprovalRequest, AuditEvent, ROLE_RANK, APPROVER_RANK, new_id, utcnow`), `aegis.core.protocols` (`OrgService, BaseControl`), `aegis.core.policy_schema` (`ControlConfig, PolicyDoc, PolicySnapshot, PolicyChange`) | n/a (frozen) |
| core-gateway | `rt.db()`, `rt.settings`, `aegis.core.crypto.hmac_hex`, `aegis.core.paths.glob_match`, `aegis.core.errors.api_error`, `aegis.core.deps.get_rt`, route discovery + `on_startup`, `python -m aegis seed` dispatch | Guarded imports with local fallbacks (`fnmatchcase`; local HMAC using `AEGIS_HMAC_KEY` or `data/keys/hmac.key`, same algorithm; local envelope; `request.app.state.rt`) |
| policy-engine | `rt.policy.snapshot()` (`doc.defaults.require_auth`, `doc.models`, `doc.budgets.kill_switch`, `doc.approvals`) | `PolicyDoc()` defaults |
| approvals-engine | `rt.approvals.route`, `create_manual`, `get`, `register_executor`; bus `approval.updated` | Default levels table; the Null service fails closed → gated org changes return 403 "approvals unavailable"; owners still apply directly |
| audit-metrics | `rt.audit.record` | no-op |
| budgets-ledger | `rt.ledger.status(scope)` for `spend_today_usd` | 0.0 |
| redaction-engine | `rt.redactor.detect` (GOV-02 `reroute_on_class` only) | reroute skipped |
| core-gateway pipeline | `ctx.identity` = the instance returned by `resolve_identity` (unmodified); `ctx.source`, `ctx.policy` | GOV-01 falls back to registry lookups (loses the revoked-key/spoof signals) |

### 4.3 Page-local TS shapes for the additive endpoints (dashboard-governance copies them into `web/src/pages/governance/`)

```ts
type Cell = { value: 'yes' | 'approval' | 'partial' | 'no'; approver?: ApproverLevel | null; note?: string | null };
interface OrgPermissionsResponse {
  policy_version: number;
  roles: Role[];                                   // ['owner','admin','member','agent']
  capabilities: { id: string; label: string; group: 'org' | 'policy' | 'budgets' | 'approvals' | 'security' | 'agents';
                  cells: Record<Role, Cell> }[];
  approval_levels: { rule_id: string; set: 'rules' | 'config_rules'; actions: string[]; kinds: string[];
                     approver: ApproverLevel; two_person: boolean; roles: Role[]; description: string | null }[];
}
interface OrgChange { id: string; op: string; action_type: string; target_type: 'member' | 'agent'; target_id: string | null;
  patch: Record<string, unknown>; before: Record<string, unknown>; requested_by: Identity; approval_id: string | null;
  required_role: ApproverLevel; status: 'pending' | 'applied' | 'denied' | 'expired' | 'cancelled' | 'failed';
  created_at: ISODate; decided_at: ISODate | null; result: Record<string, unknown> | null }
interface ApiKeyView { key_id: string; principal: string; scopes: string[]; created_by: string | null; created_at: ISODate | null;
  expires_at: ISODate | null; revoked_at: ISODate | null; status: 'active' | 'expired' | 'revoked' }
interface ApiKeyCreated extends ApiKeyView { key: string }   // shown once
```

---

## 5. Tasks

Order = graceful degradation: interfaces → seed + store → identity → read API → controls → governed writes → extras.

### ORG-01 · Public skeleton and safe stubs
- [ ] Create every file in §2.1 with exact names: `create(rt)`, `OrgServiceImpl` with protocol methods returning defaults, `router` with the 7 contract endpoints (stub 200 bodies), `CONTROLS` lists with no-op controls, `seed.main` printing "not implemented" with exit 1.
- [ ] Guarded imports for core-gateway modules (`crypto`, `paths`, `errors`, `deps`) with local fallbacks.
- [ ] Import smoke passes.
- **Priority:** must · **demo_critical:** yes · **Estimate:** 10 min · **Depends on:** CONTRACTS §2.1, §3.2, §3.3.

### ORG-02 · Seed file port and loader
- [ ] Write `config/org.seed.yaml` with all §3 fixes (wire-glob models, `<server>.<tool>` tools, `legacy-bot@platform`, key expiries, `key_expired_demo`, canonical entities, `view_as_aliases`).
- [ ] `models.py`: `SeedDoc` + subsections (`extra="allow"`).
- [ ] `seed.py`: `load_seed`, `map_seed` (exact §4.5 mapping incl. prefix stripping, tool renaming, tier mapping, kind mapping), validation errors with a path.
- [ ] `main(argv)`: `--check` summary, `--reset`, `--path`; `if __name__ == "__main__"`.
- **Priority:** must · **demo_critical:** yes · **Estimate:** 15 min · **Depends on:** ORG-01, CONTRACTS §4.5.

### ORG-03 · SQLite store, seeding and read side of `OrgService`
- [ ] `store.py`: DDL (contract tables verbatim + `org_meta`, `org_changes`), `busy_timeout`, row ↔ model mapping (`*_json` columns), `apply_seed` in one transaction, CRUD helpers.
- [ ] `start()`: create tables via `to_thread`, seed if empty, record `org_meta`, audit `org.changed op=seed`, build `OrgCache`. Handle invalid seed → minimal org + `health()="degraded"`.
- [ ] HMAC canary check + re-hash of seed keys on mismatch (WARNING).
- [ ] `org`, `list_teams`, `list_members`, `list_agents`, `get_member`, `get_agent`, `members_with_role`, `resources`, `peek_*` from the cache (deep copies for protocol methods).
- **Priority:** must · **demo_critical:** yes · **Estimate:** 15 min · **Depends on:** ORG-02, core-gateway `rt.db()` (fallback: the test FakeRT).

### ORG-04 · Identity and viewer resolution
- [ ] `ResolvedIdentity(Identity)` (`models.py`).
- [ ] `identity.py`: key extraction (`authorization` Bearer / `x-api-key` / `x-aegis-key`; only `aegis_` values), HMAC lookup, revoked/expired/unknown, principal mismatch, agent/member aliases, hints, anonymous; never raises.
- [ ] `resolve_identity`: fills `org_id/team_id/member_id(sponsor)/role/display_name/authenticated`; `X-Aegis-Team` override for members; `last_seen` in memory + throttled flush (skipped in test mode).
- [ ] `resolve_viewer`: header > `?view_as=` > cookie `aegis_view_as`; member id, role alias, short name; default viewer (`AEGIS_DEFAULT_VIEWER` or first active owner); WARNING on unknown values.
- **Priority:** must · **demo_critical:** yes · **Estimate:** 15 min · **Depends on:** ORG-03.

### ORG-05 · Permission matrix and `whoami`
- [ ] `permissions.py`: capability table, org-op table (action_type, default level, hard floor), `authorize()` (invariants, `rt.approvals.route` with fallback, level = max(route, floor), two_person ⇒ approval), `whoami_permissions()` (frozen `Permissions` shape), `capabilities()` map.
- [ ] `matrix(snap, rt)`: cells for policy-dependent rows via `rt.approvals.route(kind="config_change", changes=[PolicyChange(...)])` with representative changes (team raise +25% / +150%, `control.disable`, `killswitch.on/off`, `model.allow`); static fallback when `route` raises.
- **Priority:** must (matrix → should) · **demo_critical:** yes · **Estimate:** 10 min · **Depends on:** ORG-04.

### ORG-06 · Read endpoints
- [ ] `GET /api/org` (team member/agent counts, additive `meta`).
- [ ] `GET /api/members` (+ `agents`, `meta.pending_changes`, filters).
- [ ] `GET /api/members/{id}`.
- [ ] `GET /api/agents` (+ `status`, `spend_today_usd` via `rt.ledger.status` with timeout, `keys` summary).
- [ ] `GET /api/whoami` (+ `capabilities`, `view_as_options`).
- [ ] Error envelope helpers; `not_found`.
- **Priority:** must · **demo_critical:** yes · **Estimate:** 10 min · **Depends on:** ORG-04, ORG-05.

### ORG-07 · Governed mutations, executor, audit and SSE
- [ ] `changes.py`:
  - `request_change` (validate, `before`, authorize, dedupe pending, `org_changes` row, `create_manual` with masked payload, auto/denied/pending handling).
  - `apply_change` (lock + DB thread + cache refresh + audit `org.changed` + bus `org.updated`).
  - `org_executor` (only `org.*`; re-check hard floor vs approvers, target ∉ approvers, last-owner invariant).
  - `reconcile(apr_id=None)`.
- [ ] Routes: `POST /api/members` (201 / 403 `approval_required` / 403 `forbidden`), `PATCH /api/members/{id}` (invariants: self change 403, last owner 409), `PATCH /api/agents/{id}` (widening `max_destination` gated).
- [ ] `on_startup(rt)`: `register_executor("action", org_executor)`; `approval.updated` listener task (skipped in test mode); initial `reconcile()`.
- [ ] Audit forbidden attempts and pending requests (`data.outcome`).
- **Priority:** must · **demo_critical:** yes · **Estimate:** 20 min · **Depends on:** ORG-05, ORG-06, approvals-engine `create_manual/get/register_executor` (fake in tests).

### ORG-08 · GOV-01 Caller identity & attribution
- [ ] `Gov01Params` pydantic model with defaults (§2.8); unknown params → WARNING once.
- [ ] Evaluation order 1–7 (§2.8); findings `category="governance"`, detectors `gov.key_revoked|gov.key_expired|gov.key_unknown|gov.principal_mismatch|gov.principal_inactive|gov.auth_required|gov.unregistered_agent`; never include key material.
- [ ] Fast agent lookup via `_common.peek_agent` (falls back to `await rt.org.get_agent`).
- **Priority:** must · **demo_critical:** yes · **Estimate:** 8 min · **Depends on:** ORG-04.

### ORG-09 · GOV-02 Model allowlist & destination tiering
- [ ] `Gov02Params`; tier ceiling (block, or reroute when `on_tier_violation: reroute`); policy denied/allowed; agent allowlist; readable reasons; `owasp`.
- [ ] `model.admin`: same allowlist checks on the pulled/created model name.
- **Priority:** must · **demo_critical:** yes · **Estimate:** 10 min · **Depends on:** ORG-03.

### ORG-10 · Policy snippet
- [ ] Write `config/snippets/org-rbac.yaml` (§9): GOV-01 and GOV-02 entries with params and **only robust inline tests**, `approvals.rules` for `org.*` (to be merged **at the top** of `approvals.rules`), suggested profile overrides (strict/paranoid) as comments.
- **Priority:** must · **demo_critical:** yes · **Estimate:** 5 min · **Depends on:** ORG-08, ORG-09.

### ORG-11 · Permissions-matrix and org-changes endpoints
- [ ] `GET /api/org/permissions` (`OrgPermissionsResponse`, live from the policy snapshot; `approval_levels` from `approvals.rules` + `config_rules` with the roles that satisfy each level).
- [ ] `GET /api/org/changes?status=`.
- **Priority:** should · **demo_critical:** no (the UI can fall back to a mock) · **Estimate:** 10 min · **Depends on:** ORG-05, ORG-07.

### ORG-12 · Agent API key management
- [ ] `GET /api/agents/{id}/keys`, `POST /api/agents/{id}/keys` (plaintext once; HMAC stored; audit without the key), `POST /api/agents/{id}/keys/{key_id}/revoke` (immediate cache update → the next request with that key is blocked by GOV-01).
- **Priority:** should · **demo_critical:** no · **Estimate:** 12 min · **Depends on:** ORG-03, ORG-07.

### ORG-13 · GOV-02 `reroute_on_class` + GOV-01 key scopes
- [ ] RESTRICTED-data reroute via `rt.redactor.detect` in a thread (deterministic only) → `redact` + route mutation.
- [ ] Key-scope mapping and `enforce_key_scopes` (log/block).
- **Priority:** could · **demo_critical:** no · **Estimate:** 15 min · **Depends on:** ORG-08, ORG-09.

### ORG-14 · Non-demo viewer hardening
- [ ] `AEGIS_DEMO_MODE=0`: view-as only with a valid admin token (`AEGIS_ADMIN_TOKEN` or the seed's `control_plane.admin_token`, `compare_digest`), else a read-only anonymous viewer; `authenticated=True` for token viewers.
- [ ] Optional `POST /api/whoami {view_as}` → sets the `aegis_view_as` cookie (SameSite=Lax) for browser downloads.
- **Priority:** could · **demo_critical:** no · **Estimate:** 10 min · **Depends on:** ORG-04.

### ORG-15 · Register agents from the dashboard
- [ ] `POST /api/agents` (admin; validation: id `<name>@<team>`, sponsor active, models/tools globs) + optional first key; audit + SSE.
- **Priority:** could · **demo_critical:** no · **Estimate:** 10 min · **Depends on:** ORG-07, ORG-12.

**Estimate totals:** must ≈ 118 min (ORG-01…10) · should ≈ 22 min · could ≈ 35 min. Verification ≈ 25 min (mostly written alongside the tasks). **If time runs short, cut in this order:** ORG-15 → ORG-14 → ORG-13 → ORG-12 → ORG-11 (the dashboard uses mocks for those).

### Verification tasks

| ID | Verifies | Command / check | Expected |
|---|---|---|---|
| **ORG-V01** | ORG-01 | `uv run --frozen python -c "import aegis.org.service, aegis.org.seed, aegis.org.identity, aegis.org.permissions, aegis.org.changes, aegis.api.routes.org, aegis.controls.governance.gov01_identity, aegis.controls.governance.gov02_models; print('ok')"` | `ok`, no side effects (no `data/` files created) |
| **ORG-V02** | ORG-02 | `uv run --frozen python -m aegis.org.seed --check` (also `python -m aegis seed --check` once core-gateway dispatches) | `org acme-capital: teams=3 members=8 (owners=1 admins=2) agents=5 (inactive=1) keys=6 (revoked=1 expired=1)`, exit 0; a broken copy (sponsor `u_nobody`) → exit 1 with path `agents[1].sponsor` |
| **ORG-V03** | ORG-02/03 | `uv run --frozen pytest tests/unit/org_rbac/test_seed.py tests/unit/org_rbac/test_store.py -q` | Mapping asserts: `claude-code@platform.kind=="claude-code"`, `owner_member_id=="u_tomasz"`, `max_destination` of research-agent `=="local"`, `allowed_tools` contains `acme-db.*` (no `mcp__`), `u_emily.meta.teams==["trading","research"]`, `resources()["databases"][0]["tables"]` has `customers`/CONFIDENTIAL; re-start doesn't reseed; `--reset` reseeds |
| **ORG-V04** | ORG-03 (privacy) | In `test_store.py`: after seeding, `sqlite3` dump of `data/aegis.db` contains no `NOT_A_SECRET` and no `aegis_demo_` substrings; `api_keys.key_hmac` is 64 hex chars | passes |
| **ORG-V05** | ORG-04 | `pytest tests/unit/org_rbac/test_identity.py -q`, a table-driven test: valid key → `agent:research-agent@research`, `authenticated=True`, `member_id=u_agnieszka`, team `research`; revoked key → `credential_error="revoked"`, attributed to chaos-agent; expired key → `"expired"`; unknown `aegis_x` → `"unknown_key"`; non-aegis Bearer (`sk-ant-oat…`) ignored → falls to the `X-Aegis-Agent` header; key + mismatching `X-Aegis-Agent` → `principal_mismatch`; `X-Aegis-Agent: claude-code` → `claude-code@platform`; `X-Aegis-Member: u_piotr` + `X-Aegis-Team: research` → team stays `trading` (not a member of research); hints → `auth_method="hint"`; nothing → `agent:anonymous`; `ctx = RequestContext(request_id="r", identity=resolved)` keeps the subclass and `ctx.model_dump(mode="json")["identity"]` has **no** `credential_error` key | all pass |
| **ORG-V06** | ORG-04 | `pytest tests/unit/org_rbac/test_viewer.py -q`: `X-Aegis-View-As: admin` → `u_emily`; `?view_as=u_piotr` → member; cookie `aegis_view_as=marek` → `u_marek`; none → `u_katarzyna`; unknown → default + WARNING (caplog); `AEGIS_DEFAULT_VIEWER=u_marek` respected | all pass |
| **ORG-V07** | ORG-05/06 | `pytest tests/unit/org_rbac/test_permissions.py tests/unit/org_rbac/test_routes.py -q`: `whoami` for u_piotr → `can_manage_members=false`, `approver_levels==["self"]`, `can_apply_policy=="approval"`; for u_katarzyna → `"yes"` and `["self","admin","owner"]`; `GET /api/org` counts `{members: 8, agents: 5, teams: 3}`; `GET /api/members` u_tomasz `agents == ["claude-code@platform","chaos-agent@platform"]`; `GET /api/agents` `legacy-bot@platform.status=="killed"`; response bodies validate against pydantic mirrors of the TS `Member/Agent/OrgResponse/WhoAmI` | all pass |
| **ORG-V08** | ORG-07 (F-org flow) | `pytest tests/unit/org_rbac/test_changes.py -q` (fake approvals). (1) View as u_piotr: PATCH u_olivia team → 403 `forbidden`. (2) View as u_marek: PATCH u_olivia `{team_id: research}` → 200, audit `org.changed via=direct`, bus `org.updated`. (3) View as u_marek: PATCH u_piotr `{role: admin}` → **403 `approval_required`**, `required_role=="owner"`, `approval_id` set; `GET /api/members` shows `meta.pending_changes[0].to=="admin"`; the role is still `member`. (4) u_piotr votes approve on his own promotion (fake allows) → executor refuses (`applied:false`, "target cannot approve own promotion"). (5) u_katarzyna approves → executor applies, u_piotr role `admin`, audit `org.changed via=approval approval_id=apr_…`, bus `org.updated`. (6) A second identical PATCH while pending → same `approval_id`. (7) Demote u_katarzyna (last owner) as owner → 409 `conflict`. (8) u_marek PATCH self role → 403. (9) Approvals service returning `denied` → 403 `forbidden` "approvals unavailable". (10) Executor not called (simulate approvals-engine ignoring `action`) → `reconcile()` applies on the next `GET /api/members` | all pass |
| **ORG-V09** | ORG-08 | `pytest tests/unit/org_rbac/test_gov01.py -q`: revoked key → `block`, `http_status==401`, detector `gov.key_revoked`, finding contains no `aegis_`; expired → block; spoof → block 403; `legacy-bot@platform` (plain `Identity`, source `selftest`) → block; `ghost@nowhere` header → `log`; anonymous → `None`; valid key → `None`; `require_auth=True` + header identity + source `proxy` → block 401; same with source `selftest` → `None`; agent `selftest` → `None` | all pass |
| **ORG-V10** | ORG-09 | `pytest tests/unit/org_rbac/test_gov02.py -q`: copilot + `gpt-4.1-mini` → block "not in agent … allowlist"; copilot + `claude-opus-4-1` → block; claude-code + `claude-sonnet-4-5` → `None`; research-agent + destination `remote` + `mock-echo` → block "local-only"; same with `on_tier_violation: reroute` → `redact` with `Mutation(target="route", path="model", value="aegis-judge")`; chaos-agent + `qwen3:cloud` → block (policy denied `*:cloud`); member identity + `claude-haiku-4-5` → `None`; `model=None` + known agent within tier → `None`; `model.admin` pull of `evil/model` with `models.allowed` lacking it → block | all pass |
| **ORG-V11** | ORG-04 perf | `pytest tests/unit/org_rbac/test_perf.py -q`: 10,000 `resolve_identity` calls with a valid key | total < 1.0 s (≈ < 100 µs each; target ~20 µs) |
| **ORG-V12** | all | `uv run --frozen ruff check src/aegis/org src/aegis/controls/governance src/aegis/api/routes/org.py tests/unit/org_rbac` and `ruff format --check` on the same paths; `uv run --frozen pytest tests/unit/org_rbac -q` | clean; the whole suite < 10 s |
| **ORG-V13** | integration (once core-gateway, policy-engine and approvals-engine land) | `tests/unit/org_rbac/test_integration.py` (skips if `aegis.app` is not importable): `create_app()` under `LifespanManager`, `httpx.AsyncClient(ASGITransport)`. (a) `GET /api/whoami` with `X-Aegis-View-As: member` → `u_piotr`. (b) `POST /v1/guard` with `Authorization: Bearer aegis_demo_revoked_key_0000000000000099_NOT_A_SECRET` and a `model.request` interaction → `verdict.action=="block"`, `primary.control_id=="GOV-01"`. (c) `POST /v1/guard` with `X-Aegis-Agent: trading-copilot@trading`, `model: gpt-4.1-mini` → block GOV-02. (d) The promotion flow through the real `/api/approvals/{id}/approve` | all pass |
| **ORG-V14** | snippet + self-test (after policy-engine merges the snippet) | `uv run --frozen python -m aegis selftest` | `GOV-01/registered-agent-allowed` and `GOV-01/disabled-agent-blocked` (+ `GOV-02/local-agent-to-remote`) pass; no candidate rejected because of GOV tests |
| **ORG-V15** | manual demo check (stack up via `make up`, by the integrator) | `curl -s 127.0.0.1:8787/api/whoami -H 'X-Aegis-View-As: admin' \| jq .permissions`; `curl -s -X PATCH 127.0.0.1:8787/api/members/u_piotr -H 'X-Aegis-View-As: u_marek' -H 'content-type: application/json' -d '{"role":"admin"}'` → 403 `approval_required` + `apr_…`; approve as `u_katarzyna` via `/api/approvals/<id>/approve`; `/api/members` shows u_piotr admin; `/api/audit?event_type=org.changed` shows pending + applied. In the UI: Org page as Marek → change role → toast "needs owner" → switch to Katarzyna → Approvals inbox → Approve → the org page updates live | as described |

**Proposed black-box cases for test-suite (`tests/cases/governance.yaml`)** (test-suite owns these; listed so every catalog control has must-block + must-allow):
- GOV-01: revoked key → block; expired key → block; key + spoofed `X-Aegis-Agent` → block; `X-Aegis-Agent: legacy-bot@platform` → block; valid research key → allow.
- GOV-02: copilot `gpt-4.1-mini` → block; research-agent → `mock-echo` (remote) → block; claude-code `claude-sonnet-4-5` → allow; research-agent `aegis-judge` → allow.

---

## 6. Demo cut

**Must really work live:**
- Seeded Acme Capital (ids from §4.5) in SQLite.
- `resolve_identity` for keys and headers (every live-feed row shows the right principal, team and sponsor).
- `resolve_viewer` with member ids and role aliases; `whoami` permissions gating the dashboard.
- `GET /api/org|members|agents`.
- `members_with_role` / `get_agent` used by approvals-engine (sponsor = `self` approver, F4).
- GOV-01 blocks revoked keys and disabled agents; GOV-02 blocks off-allowlist models and local-only agents reaching remote.
- **Admin → owner-gated role promotion** through the real approvals inbox, with `org.changed` audit and live `org.updated`.

**May be simplified or stubbed convincingly:**
- `spend_today_usd` (0 when the ledger has no agent status).
- `status` idle/active heuristic.
- `/api/org/permissions` (static matrix if `rt.approvals.route` is unavailable; the UI may use mocks).
- Key-management endpoints (UI may be mock-backed).
- `reroute_on_class` (off by default; strict profile only).
- Key-scope enforcement (log-only).
- Non-demo-mode auth.
- Agent registration.
- `last_seen` persistence (in-memory is enough on stage).

---

## 7. Dependencies

- **Python (all already in CONTRACTS §7.6; no new packages requested):** `pydantic>=2.9`, `fastapi`, `pyyaml` (seed parsing; `ruamel.yaml` not needed), stdlib `sqlite3`, `hmac`, `hashlib`, `secrets`, `fnmatch`, `asyncio`, `http.cookies`.
- **Dev:** `pytest`, `pytest-asyncio`, `httpx`, `asgi-lifespan`.
- **npm:** none (org-rbac has no frontend files).
- **Runtime services consumed:** see §4.2. **Deps requested:** none.

---

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Frozen `Identity` has no room for credential status, key scopes or spoof flags | `ResolvedIdentity` subclass (pydantic v2 keeps the instance, serializes as `Identity`). GOV-01 uses `getattr` defaults, so if core-gateway rebuilds the Identity, GOV-01 still blocks disabled agents and attributes correctly; only the revoked/spoof signals degrade. Request to core-gateway: pass the instance through unchanged (G1). ORG-V05 asserts both behaviours. |
| Executor collision: one executor per kind; org changes use kind `action` | The executor only handles `org.*` and returns `None` otherwise. It is registered in route `on_startup` (runs after approvals-engine's) and backed by the `approval.updated` listener and read-time `reconcile()`. Request to approvals-engine (G2). |
| GOV-01 noise: the catalog default action `log` on every unauthenticated call would turn all demo/test traffic slate and break `expect: allow` tests | `log` only for **unregistered** agent ids. Anonymous callers → allow (attribution only). Blocks only for real problems. `require_auth` limited to data-plane sources. `selftest` agent exempt. Judges can flip `anonymous_action: block` / `require_auth: true` live (G6). |
| Inline self-tests rejecting policy candidates (a failing must-block rejects the policy) | Only seed-backed GOV tests that need no extra `PolicyTest` fields (`registered-agent-allowed`, `disabled-agent-blocked`, `local-agent-to-remote`). Model-name cases stay in unit tests and test-suite until policy-engine honours the extra key `model` (G9). |
| GOV-03 (action-guards) pre-empts MCP and approval demos because of seed tool allowlists | Seed tool lists broadened and converted to `<server>.<tool>` (claude-code allows `*.*` minus `acme-crm.export_*`). Flagged to action-guards. |
| HMAC key rotation or `make reset` makes stored key hashes invalid | `org_meta.hmac_canary` check + automatic re-hash of seed keys. `reset` wipes the DB and reseeds anyway. |
| Seed key expiry dates would make tests fail after 4 Oct | Expiries moved to 2027; explicit `key_expired_demo` for the negative case. |
| Approvals service unavailable (Null, fail-closed) | Gated org changes → 403 "approvals unavailable — ask an owner"; owners still change roles directly; reads unaffected. |
| Only one owner, so a two-person rule for owner grants could never complete | No `two_person` on `org.*` rules (documented in the snippet; turn it on once there are 2 owners). |
| Hot-path latency | Cache-only lookups, one HMAC per keyed request, throttled `last_seen` writes in threads; perf test ORG-V11. |
| SQLite write contention with other workstreams (shared `aegis.db`, WAL) | Writes are rare, short, in `to_thread`, serialized by an `asyncio.Lock`, `busy_timeout=5000`. |
| The dashboard may not expect 403 `approval_required` from `PATCH /api/members` | It is the §5.3 envelope; the message names the required role and `apr_…`. Request to dashboard-governance to toast it with a link (G5). |
| "viewer" role requested in scope | Not feasible without changing frozen `Role`/`ViewRole` and the SQL CHECK. Every page is readable by `member`; read-only personas would need all owners to cooperate. Documented as out of scope. |
| Privacy: emails in approval payloads and audit | Emails masked in `ApprovalRequest.payload` and audit `data`; plaintext keys never stored or logged; key creation returns the plaintext once in the HTTP response only. |

---

## 9. Snippet: `config/snippets/org-rbac.yaml`

```yaml
# org-rbac policy entries. policy-engine merges these into config/policy.yaml.
# NOTE: put the approvals.rules below at the TOP of approvals.rules (first match wins).
controls:
  - id: GOV-01
    name: Caller identity & attribution
    action: log                       # used for UNREGISTERED agent ids; blocks below are explicit
    severity: high
    fail_mode: closed
    timeout_ms: 50
    owasp: [ASI03, ASI07, MCP07:2025, LLM03:2026]
    params:
      require_auth: null              # null = defaults.require_auth; true => unauthenticated data-plane calls are blocked (401)
      require_auth_sources: [proxy, mcp, hook, egress, guard]
      anonymous_action: allow         # allow (attribution only) | log | block
      unknown_agent_action: null      # null = control action (log)
      block_inactive: true            # disabled agents / deactivated members
      block_invalid_keys: true        # revoked, expired or unknown aegis_ keys
      block_principal_mismatch: true  # key principal != X-Aegis-Agent
      enforce_key_scopes: false       # could: log | block when a key is used outside its scopes
      exempt_agents: [selftest]
    tests:
      - {name: registered-agent-allowed, agent: research-agent@research, destination: local, text: "Summarise today's research notes.", expect: allow}
      - {name: disabled-agent-blocked, agent: legacy-bot@platform, text: "hello", expect: block, control: GOV-01}

  - id: GOV-02
    name: Model allowlist & destination tiering
    action: block
    severity: high
    fail_mode: closed
    timeout_ms: 50
    owasp: [LLM03:2026, LLM06:2026, LLM02:2026, ASI10]
    params:
      enforce_policy_allowlist: true  # models.allowed / models.denied
      enforce_agent_allowlist: true   # Agent.allowed_models (org seed)
      enforce_tier_ceiling: true      # Agent.max_destination (research-agent is local-only)
      on_tier_violation: block        # block | reroute (route mutation to reroute_model)
      reroute_on_class: {}            # e.g. {RESTRICTED: local}; strict profile suggestion
      reroute_model: null             # null = models.default_local (aegis-judge)
    tests:
      - {name: local-agent-to-remote, agent: research-agent@research, destination: remote, text: "hi", expect: block, control: GOV-02}
      # Needs PolicyTest extra key `model` honoured by the self-test runner (contract gap G9):
      # - {name: copilot-model-not-in-allowlist, agent: trading-copilot@trading, model: gpt-4.1-mini, text: "hi", expect: block, control: GOV-02}
      # - {name: claude-code-sonnet-allowed, agent: claude-code@platform, model: claude-sonnet-4-5, text: "hi", expect: allow}

approvals:
  rules:                              # org governance; kind=action, action_type=org.* (created by org-rbac)
    - id: org-owner-grants
      description: "Granting or revoking the owner role always needs an owner (hard floor in code too)"
      when: {kind: [action], action: ["org.role.promote_owner", "org.role.demote_owner", "org.member.create_owner"]}
      approver: owner
      ttl_s: 3600
    - id: org-privileged
      description: "Promote/demote admins, add an admin, deactivate an admin/owner, widen an agent's destination tier"
      when: {kind: [action], action: ["org.role.*", "org.member.create_admin", "org.member.deactivate_privileged", "org.agent.widen_destination"]}
      approver: owner                 # judges may lower to admin (code floor stays admin)
      ttl_s: 3600
    - id: org-routine
      description: "Routine member/agent administration (direct for admins; listed for the matrix)"
      when: {kind: [action], action: ["org.member.create", "org.member.update", "org.member.deactivate", "org.agent.update", "org.agent.key", "org.agent.create"]}
      approver: admin

# Suggested profile overrides (policy-engine owns config/profiles/*):
#   strict:   {controls: {GOV-02: {params: {reroute_on_class: {RESTRICTED: local}}}}}
#   paranoid: {controls: {GOV-01: {params: {anonymous_action: block, require_auth: true}},
#                         GOV-02: {params: {reroute_on_class: {RESTRICTED: local}}}}}
```

---

## 10. Contract gaps (proposed addenda; none conflict with existing shapes)

- **G1 · Identity carrier.** `resolve_identity` returns `aegis.org.models.ResolvedIdentity`, a subclass of the frozen `Identity` with `auth_method, key_id, key_scopes, credential_error, asserted_agent_id, principal_mismatch, known, principal_active`. **Request to core-gateway:** put the returned instance into `pipeline.new_context(identity=…)` unchanged (no `Identity(**dump)`), resolve once per inbound request, and also strip `x-aegis-key` (accepted alias of `x-api-key`, from staging) before forwarding upstream.
- **G2 · Executor for org changes.** Org changes are `ApprovalDraft(kind="action", action_type="org.*")` via `create_manual`. org-rbac registers the `action` executor (it only handles `org.*`, returns `None` otherwise). **Request to approvals-engine:** do not register an `action` executor yourself (or chain executors / dispatch by `action_type` prefix); call the executor for auto-approved requests too; keep `approval.updated` on the bus for every transition.
- **G3 · Action-type vocabulary (§3.4 addendum).** `org.member.create`, `org.member.create_admin`, `org.member.create_owner`, `org.member.update`, `org.member.deactivate`, `org.member.deactivate_privileged`, `org.role.promote_admin`, `org.role.promote_owner`, `org.role.demote_admin`, `org.role.demote_owner`, `org.agent.update`, `org.agent.widen_destination`, `org.agent.key`, `org.agent.create`; `resource` format `member:<id>` / `agent:<id>`; labels `category=org`. ID prefix `och` for org changes.
- **G4 · Additive endpoints under org-rbac prefixes:** `GET /api/members/{id}`, `GET /api/org/permissions`, `GET /api/org/changes`, `GET|POST /api/agents/{id}/keys`, `POST /api/agents/{id}/keys/{key_id}/revoke`, `POST /api/agents` (could), `POST /api/whoami` (could, sets cookie). Shapes in §4.3 (page-local TS for dashboard-governance). Additive response fields: `Member.meta.pending_changes`, `Agent.keys`, `OrgResponse.meta`, `WhoAmI.capabilities`, `WhoAmI.view_as_options`.
- **G5 · Gated member changes answer 403 `approval_required`** (§5.3 envelope with `approval_id`, `required_role`, `expires_at`) instead of `Member`. **Request to dashboard-governance:** show a toast "Sent for owner approval" with a link to `/governance/approvals?id=apr_…`, render `meta.pending_changes` chips, and gate the "Change role" control with `whoami.capabilities['members.manage']`.
- **G6 · GOV-01 default semantics.** Clarifies the catalog's "`log` (unauthenticated)": `log` is applied to unregistered agent ids. Anonymous → allow (attribution only). Invalid/revoked/expired keys, principal spoofing, disabled principals and `require_auth` violations → block (401 `unauthenticated` / 403). New `error_type` value `unauthenticated` (401) and the `not_found` (404) API error type.
- **G7 · Extra SQLite tables** `org_meta`, `org_changes` (owned by org-rbac, `CREATE IF NOT EXISTS`, wiped by `make reset`).
- **G8 · View-as extensions:** the `aegis_view_as` cookie, role aliases `owner|admin|member` (configurable in the seed's `control_plane.view_as_aliases`; used by DEMO_RUNBOOK curl commands), short names (`emily`), agent short aliases for `X-Aegis-Agent` (`claude-code`).
- **G9 · `PolicyTest` extras.** **Request to policy-engine:** the self-test runner should map the extra keys `model` → `Interaction.model` (and optionally `headers` → `ctx.headers`). Build the test identity as `Identity(agent_id=<agent>, …)`, team via `rt.org.get_agent`. Merge the org-rbac `approvals.rules` at the top of `approvals.rules`. Port `budgets:` amounts from `config/org.seed.yaml` (unchanged).
- **G10 · Seed format additions** (org-rbac-owned file): `max_destination:` (contract vocabulary) accepted next to `max_destination_tier`; `control_plane.view_as_aliases`, `control_plane.default_viewer`; disabled agent `legacy-bot@platform`; key `key_expired_demo`. All binding ids unchanged.
- **Notes to other owners (no shape changes):**
  - **action-guards:** `Agent.allowed_tools/denied_tools` are `<server>.<tool>` globs; `Agent.meta["data_grants"]` = `[{database, tables, operations}]`; `rt.org.resources()` = `{databases[{id, environment, tables[{name, sensitivity, categories, contains}]}], vendors[{id, name, approved, host, plans[{id, usd, recurring}]}], external_hosts[{host, tier, dest_class, purpose}]}`.
  - **approvals-engine:** the sponsor is `Agent.owner_member_id`, also present as `Identity.member_id` for agent identities; `members_with_role` includes owners for any team; `Member.meta.owner_delegate` marks escalation delegates.
  - **budgets-ledger:** `status(scope="agent:<id>")` should return the usd/day `used` even without a configured limit (for `spend_today_usd`).
  - **core-gateway:** `/healthz` `components.org` = `rt.org.health()` if present; settings fields `org_seed, demo_mode, default_viewer, admin_token, test_mode, data_dir`.
  - **test-suite:** use the seed keys and `legacy-bot@platform` for the GOV-01 cases; send `X-Aegis-Agent` on traffic that must be attributed.
