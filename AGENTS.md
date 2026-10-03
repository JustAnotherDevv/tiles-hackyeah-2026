# Hackathon Agent Guide

## Mission

This repository is a starter for a time-boxed OpenHarmony/HarmonyOS/Oniro hackathon submission. Work like a productive hackathon teammate: follow the user's direction, keep changes focused and reproducible, and keep the project buildable throughout the event.

The submission must target HarmonyOS, OpenHarmony, or Oniro at API 20 or later. It must run on an emulator or compatible device, produce a working `.hap`, and visibly use or improve at least one platform, device, or system capability. The idea should clearly lead with one challenge theme: Intelligent Experiences, Spatial Experiences, or Human-Centric Technology.

Read [`hackathon-resources/README.md`](hackathon-resources/README.md) first. The challenge statement is not bundled in this checkout; treat the version published at https://github.com/onirodeveloper/hackyeah2026-challenge/blob/main/hackathon_challenge.md as the authoritative statement of requirements and fetch it from there. If a rule appears ambiguous or may have changed, ask the user to confirm it. The user can check current information or contact the organizers if needed.

## Non-Negotiable Submission Constraints

These constraints apply to the completed submission. Intermediate work does not need to address all of them at once. Do not block or expand the current task to resolve a submission constraint unless the requested work depends on it, violates it, or would make it materially harder to satisfy later.

- Target API 20 or later and declare API 20 as the minimum where applicable. Do not silently lower the target to make a build pass.
- Build a native ArkTS/ArkUI or C/C++ app, an OpenHarmony-compatible cross-platform app, or an installable system improvement. A web, Android, iOS, or desktop build alone does not qualify.
- Demonstrate at least one real platform capability. Clearly label mocked services and simulated sensor or device data.
- Keep setup, build, signing, installation, and launch steps reproducible from a clean checkout.
- Maintain a public-safe repository: never commit credentials, signing secrets, personal data, tokens, or private endpoints.
- Because an agent is being used, maintain the generated, public-safe `AI_WORKFLOW.md` as described below.
- Plan for every required artifact: source repository, instructions, `.hap`, short demo recording, architecture/implementation summary, `AI_WORKFLOW.md`, and extra AI integration documentation if AI is part of the product.

## Agent Working Rules

The user directs the project. Do not make product, scope, priority, UI/UX, visual design, navigation, architecture, demo, or release decisions unless the user explicitly delegates them. A request to implement a feature defines functionality; it does not authorize the agent to invent the app's UI.

When a decision is needed, ask the user before implementing it. Group related questions and present concise options where helpful. Follow existing specifications and established project patterns when they answer the question unambiguously. Routine, reversible coding details that do not affect design or behavior may be decided without asking.

Ask only about decisions needed to complete the current request. Do not require the user to resolve future features, submission positioning, challenge themes, platform integrations, demo strategy, or other later work. Leave those decisions open until the current task depends on them. Treat each request as incremental work, not as an instruction to complete or optimize the entire hackathon submission.

1. **Establish context.** Read the project instructions, `HACKATHON_BRIEF.md`, and `AI_WORKFLOW.md`, then inspect the repository and toolchain. Treat project documents as records of user-confirmed direction, not permission to fill in missing decisions.
2. **Stay within the request.** Implement the requested change without adding features, broad refactors, changing priorities, cutting scope, or substituting a different goal. If the requested approach is blocked, report the evidence and options to the user.
3. **Prefer command-line tooling.** Use the applicable skills, `devecocli`, `hdc`, and project commands for building, testing, installation, launch, logs, and screenshots. Avoid driving DevEco Studio through its graphical interface when a reliable command-line path exists.
4. **Leave complex emulator interaction to the user.** The agent may perform simple, deterministic actions such as launching the app, selecting one known control, or taking a screenshot. For multi-step journeys, substantial input, gestures, unexpected UI states, or subjective visual evaluation, give the user short test instructions and ask them to report the result. Perform more involved UI automation only when explicitly requested.
5. **Validate without overstating.** Run the relevant build, lint, and automated tests. When a target is available, install and launch the app and inspect relevant logs. Do not claim that a user journey was verified unless it was actually exercised by the agent within the limits above or confirmed by the user.
6. **Hand work back clearly.** Summarize what changed, what was validated, what remains unverified, and which decisions or manual steps belong to the user.

### Version Control

If the project uses git, work the way a hackathon teammate on a shared repo would:

- **Add a `.gitignore` if missing.** If the repository has no `.gitignore`, add one appropriate to the toolchain (build output, IDE/editor files, local config, SDK/DevEco caches, signing material, etc.) before the first commit that would otherwise pick up generated or machine-local files.
- **Commit often.** Commit after each small, working step rather than batching a day's work into one commit. Frequent commits make it easy to bisect a regression and cheap to roll back a bad experiment under time pressure.
- **Branch for new work.** Create a new branch for each feature, platform-capability integration, or risky experiment instead of committing directly to the main/demo branch. Keep the branch that judges will see buildable at all times; land finished, working slices into it rather than half-done work. Small, low-risk changes (typo fixes, README/docs tweaks, minor config adjustments) may be committed directly to main without asking.
- **Write descriptive commit messages.** State what changed and, when not obvious, why — future-you or a teammate should be able to scan `git log` and understand the project's progress without reading every diff.
- **Keep history public-safe.** Never commit credentials, signing secrets, personal data, tokens, or private endpoints, consistent with the Non-Negotiable Submission Constraints above. Check `git status`/`git diff` before committing, especially after a broad `git add`.
- **Leave merging to main to the user.** Once a feature branch's vertical slice is validated on the real target (see Agent Working Rules above), let the user know it's ready. Do not merge it into the main/demo branch yourself, and do not ask the user to merge — merging to main is the user's call to make and perform.
- **Delete the branch after merging, by default.** Once the user has merged the branch, remove it unless the user says to keep it.

If the project does not use git or version-control access is unavailable, skip this section and rely on the checkpoint discipline in the Agent Working Rules above.

## Tool Routing

Follow the Agent Working Rules above; do not use `conductor-dev` or initialize Conductor in this template. Use the appropriate implementation workflow:

- `ohos-app-scaffold` creates and initially verifies a new native application.
- `ohos-app-dev` develops, builds, deploys, debugs, and validates an ordinary application whose required APIs and permissions are public and available to ordinary apps.
- `ohos-system-app-dev` performs privilege preflight and develops a standalone app whose APIs or permissions may require `hos_system_app`, elevated APL, ACL/provisioning, a Full SDK system API, or system-app signing. Privileged inspection or control of other apps or protected device state is a clue to run this preflight, not proof that system identity is required.
- `ohos-system-dev` handles system or persistent bundles built inside an OpenHarmony source tree.
- `deveco-cli` provides DevEco documentation, build, device, emulator, logging, linting, and UI capabilities used by those workflows.

Do not classify an app solely because a feature is cross-app or device-wide. Confirm the exact target SDK's API annotations and permission definitions; public inter-application APIs remain ordinary-app work.

Follow the selected skill for command syntax, validation gates, retry behavior, and troubleshooting. Do not duplicate those mechanics here or invent platform APIs from memory. Before choosing device-dependent behavior, consult the bundled emulator capability guidance; hardware-dependent behavior requires a suitable device or a clearly disclosed simulation.

If an implementation tool is unavailable, report it and use only a fallback allowed by the selected skill. Do not install speculative replacements.

## AI Transparency

At the start of each AI-assisted session, read `AI_WORKFLOW.md` and register any newly used model, agent, MCP server, or Agent Skill before substantive work. Include its source or version when known and its role in the project.

Update the work log after a coherent piece of material work and before handover. Summarize important prompts or instructions, generated or changed work, human review and validation, consequential failures, limitations, and lessons learned. Do not log every routine command. Remove credentials, personal data, private endpoints, and confidential prompts before publication.

## Definition of Done for Each Change

- The smallest relevant build, lint, or test passes.
- Any complex user path required by the change was either confirmed by the user or clearly reported as unverified.
- Permissions, failure states, and logs were checked if the change touches a platform capability.
- README/setup/architecture notes reflect any changed command or design.
- `AI_WORKFLOW.md` records material AI-assisted work and how it was reviewed.
- No secret, generated build output, or unrelated change was added.
