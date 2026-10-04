# HackTribe submission: Aegis Pocket (Huawei "Imagine What's Next")

Copy-paste text for the HackTribe entry. The Goldman Sachs submission (Aegis, in `aegis/`) is a separate entry.

## Title (≤5 words)

**Aegis Pocket: Approve AI Agents**

## Team

JustAnotherDevv

> Before submitting, replace this line on HackTribe with each member's real name and email (not stored in this public repo).

## Links

- Repository: https://github.com/JustAnotherDevv/tiles-hackyeah-2026 (Aegis Pocket at the root; build, install and launch steps in `README.md`)
- `.hap`: GitHub Release of the repository
- Demo video: (add the link after recording)

## Description (≤500 words)

AI agents are starting to act for us: they buy subscriptions, read company databases, deploy code and email
customers. When one of them wants to do something risky, someone has to say yes or no, quickly and safely, and
usually that person is not at a desk. Aegis Pocket puts that human back in the loop, on a HarmonyOS phone.

When an agent governed by our Aegis gateway asks for a risky action ("Research agent wants to spend $50 on a SaaS
subscription"), the request appears at once as a **notification**. Tapping it opens the request with everything
needed to decide: who asked, which agent sponsor is responsible, the amount, the policy checks that passed or
failed, and an expiry countdown. A **"Why a human is asked"** card explains the risk in plain words and gives it a
score from 0 to 100. The score is computed **on the device** from the gateway's policy data: which control fired,
how much money moves, whether production or personal data is involved. The agent's own justification is shown but
labelled untrusted and never scored, because an agent can be manipulated by prompt injection.

Approval rules follow the person's role: members approve small actions for agents they sponsor, admins approve
mid-size spend and sensitive data access, and owners approve large spend and budget raises, sometimes with a second
approver (two-person rule). A sponsor can never approve their own agent's request. When a request is risky, tapping
**Approve** first asks for the user's **face, fingerprint or PIN** through HarmonyOS User Authentication Kit, so a
stolen or unlocked phone cannot approve a $480 purchase. Denying never needs it: saying no is always the safe
direction. Approve and deny give distinct **haptic** confirmations.

A **home-screen service widget** (Form Kit, 2x2 and 2x4) shows the AI security posture at a glance: pending
approvals, blocked threats, redacted personal data and budget left. A **WorkScheduler background task** keeps the
widget current and raises notifications while the app is closed. The **"What data leaves"** preview shows exactly
which personal data (emails, phone numbers, PESEL, IBAN, card numbers, validated by checksum) would be replaced with
placeholders before a prompt goes to an AI model. It runs entirely on the device.

Aegis Pocket is built natively in ArkTS/ArkUI for HarmonyOS (minimum API 20, compiled against API 24). It uses User
Authentication Kit, Notification Kit, Form Kit, Background Tasks Kit, Sensor Service Kit, Network Kit and ArkData.
Screen-reader labels and font scaling make it usable for everyone. It works in two clearly labelled modes: a
**mock mode** that simulates the gateway on the device for demos, and a **live mode** that talks to the real Aegis
gateway over HTTP.

Themes: **Human-Centric Technology** (human oversight of autonomous AI, privacy and accessibility) with an
**Intelligent Experiences** angle (on-device risk explanation for AI agent requests).

AI-assisted development is documented in `AI_WORKFLOW.md`.

## Demo video script (≤60 s)

Record on the DevEco phone emulator in mock mode, with the 2x4 widget already on the home screen. Keep the MOCK
label visible. The emulator cannot simulate biometrics: if no lock-screen PIN is set, the labelled fallback dialog
appears, so say so on screen.

| Time | Screen | Voice-over |
|---|---|---|
| 0-6 s | Home screen with the **AI posture** widget, tap it | "AI agents now spend money and touch our data. Aegis Pocket puts a human back in the loop, on HarmonyOS." |
| 6-14 s | App Home: pending count, threats blocked, data redacted, budget | "Live AI security posture, on the home screen and in the app." |
| 14-22 s | Notification arrives; tap it | "An agent wants to act. The request reaches me instantly, as a notification." |
| 22-32 s | Detail: "Why a human is asked" card, checks, untrusted agent note | "The phone explains the risk itself, on the device. The agent's own excuse is never trusted." |
| 32-38 s | Switch persona to Piotr (member): Approve is LOCKED with the reason | "Rules follow my role. Nobody approves their own agent." |
| 38-50 s | As Emily (admin): Approve → face / fingerprint / PIN sheet (or the labelled fallback) → toast | "Risky approvals need my face, fingerprint or PIN. Saying no never does." |
| 50-56 s | Preview tab: text with email and PESEL becomes `[EMAIL_1]`, `[PESEL_1]` | "And I see exactly what personal data would leave this phone." |
| 56-60 s | Home screen widget, pending count lower | "Aegis Pocket: approve AI agents, safely, from your pocket." |
