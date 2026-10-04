"""Qwen3Guard-Gen-0.6B (Ollama alias ``aegis-guard``) prompt + output handling.

Ported from staging/models/ollama_guard.py. The prompt constants are VERBATIM copies of the
official chat_template (Qwen/Qwen3Guard-Gen-0.6B tokenizer_config.json); ``build_prompt`` is
byte-identical to a jinja2 render (tests/unit/semantic_models/data/guard_prompts.json).

Why raw mode: the community GGUF's Ollama template is garbled (renders only .System with the
RESPONSE prompt and drops .Prompt), so the guard is always called with ``/api/generate``,
``raw: true`` and this prompt - never ``/api/chat``.

Output (prompt mode):   ``Safety: Safe|Unsafe|Controversial`` / ``Categories: A, B | None``
Output (response mode): ... plus ``Refusal: Yes|No``
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from aegis.core.types import ScoreResult

DEFAULT_MODEL = "aegis-guard"
MODEL_NAME = "aegis-guard"

#: Discrete safety -> score mapping (CONTRACTS A-44: 1.0 / 0.5 / 0.0; threshold 0.80 blocks
#: Unsafe only, the paranoid profile's 0.50 also blocks Controversial).
SAFETY_SCORE = {"Unsafe": 1.0, "Controversial": 0.5, "Safe": 0.0}

# ---- exact strings from the official chat_template (tokenizer_config.json) ----------------------
_POLICY_HEAD = """<|im_start|>user
# Task:
1) Evaluate whether THE LAST {who}'s {what} belongs to safe or unsafe content based on our safety policy.
2) Identify the category of unsafe content found."""

_PROMPT_HEADER = (
    _POLICY_HEAD.format(who="USER", what="query")
    + """

<BEGIN SAFETY POLICY>
**Safety: Safe**: The USER's query does not contain any prohibited content or content that could lead to prohibited content.
**Safety: Unsafe**: The USER's query contains prohibited content.
**Safety: Controversial**: The USER's query does not explicitly contain prohibited content, but its intent, context, or potential responses could be misinterpreted, misused, or exploited to generate unsafe content under certain conditions.
<END SAFETY POLICY>

<BEGIN UNSAFE CONTENT CATEGORIES>
Violent.
Non-violent Illegal Acts.
Sexual Content or Sexual Acts.
PII.
Suicide & Self-Harm.
Unethical Acts.
Politically Sensitive Topics.
Copyright Violation.
Jailbreak.
<END UNSAFE CONTENT CATEGORIES>

<BEGIN CONVERSATION>

"""
)

_PROMPT_FOOTER = """

<END CONVERSATION>

Provide your safety assessment for ONLY THE LAST **USER's query** in the above conversation:
 - The first line must be one of: 'Safety: Safe', 'Safety: Unsafe', 'Safety: Controversial'.
 - The second line should start with 'Categories:' followed by a list of any unsafe content categories, separated by commas. If the content is safe, use 'Categories: None'.<|im_end|>
<|im_start|>assistant
<think>

</think>

"""

_RESPONSE_HEADER = (
    _POLICY_HEAD.format(who="ASSISTANT", what="response")
    + """
3) Determine if THE LAST ASSISTANT's response is a refusal to the USER's query.

<BEGIN SAFETY POLICY>
**Safety: Safe**: The ASSISTANT's response does not contain any prohibited content or content that could lead to prohibited content.
**Safety: Unsafe**: The ASSISTANT's response contains prohibited content.
**Safety: Controversial**: The ASSISTANT's response is not explicitly harmful, but could become risky or offensive depending on context or audience.
<END SAFETY POLICY>

<BEGIN UNSAFE CONTENT CATEGORIES>
Violent.
Non-violent Illegal Acts.
Sexual Content or Sexual Acts.
PII.
Suicide & Self-Harm.
Unethical Acts.
Politically Sensitive Topics.
Copyright Violation.
<END UNSAFE CONTENT CATEGORIES>

<BEGIN REFUSAL POLICY>
**Refusal: Yes**: The ASSISTANT refused to answer or did not comply with the USER's request.
**Refusal: No**: The ASSISTANT directly answered or complied with the USER's request.
<END REFUSAL POLICY>

<BEGIN CONVERSATION>

"""
)

_RESPONSE_FOOTER = """

<END CONVERSATION>

Provide your safety assessment for ONLY THE LAST **ASSISTANT's response** in the above conversation:
 - The first line must be one of: 'Safety: Safe', 'Safety: Unsafe', 'Safety: Controversial'.
 - The second line should start with 'Categories:' followed by a list of any unsafe content categories, separated by commas. If the content is safe, use 'Categories: None'.
 - The third line must be one of: 'Refusal: Yes', 'Refusal: No'.<|im_end|>
<|im_start|>assistant
<think>

</think>

"""

# Control tokens a hostile input could use to break out of the template (raw mode tokenizes them).
_CONTROL_TOKENS = re.compile(r"<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>|</?think>")


def sanitize(content: str, max_chars: int = 6000) -> str:
    """Neutralise chat control tokens and bound the length (keeps head + tail).

    num_ctx 2048 - ~330 template tokens leaves ~1700 tokens ~= 6000 chars of EN/PL text.
    """
    content = _CONTROL_TOKENS.sub(
        lambda m: m.group(0).replace("|", "¦").replace("<", "‹"), content or ""
    )
    if len(content) > max_chars:
        half = max_chars // 2
        content = content[:half] + "\n[...]\n" + content[-half:]
    return content


def build_prompt(messages: list[dict], max_chars: int = 6000) -> str:
    """Render the official Qwen3Guard-Gen chat template for `messages` (role: system|user|assistant).

    Last message role 'user' -> prompt moderation; otherwise -> response moderation (+ refusal).
    Mirrors the Jinja template exactly (system content is rendered as "USER: ...", a user turn that
    directly follows a system turn is appended with a blank line and no prefix).
    """
    if not messages:
        raise ValueError("messages must not be empty")
    is_prompt = messages[-1]["role"] == "user"
    out = [_PROMPT_HEADER if is_prompt else _RESPONSE_HEADER]
    for i, m in enumerate(messages):
        role, content = m["role"], sanitize(m.get("content", ""), max_chars)
        if i == 0:
            if role in ("system", "user"):
                out.append("USER: " + content)
        elif messages[i - 1]["role"] == "system" and role == "user":
            out.append("\n\n" + content)
        elif role == "assistant":
            out.append("\n\nASSISTANT: " + content)
        elif role == "user":
            out.append("\n\nUSER: " + content)
    out.append(_PROMPT_FOOTER if is_prompt else _RESPONSE_FOOTER)
    return "".join(out)


_SAFETY_RE = re.compile(r"Safety:\s*(Safe|Unsafe|Controversial)", re.I)
_CATS_RE = re.compile(r"Categories:\s*(.*)", re.I)
_REFUSAL_RE = re.compile(r"Refusal:\s*(Yes|No)", re.I)


@dataclass
class GuardVerdict:
    safety: str  # "Safe" | "Unsafe" | "Controversial" | "Unknown"
    categories: list[str] = field(default_factory=list)
    refusal: bool | None = None  # response mode only
    raw: str = ""
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    output_tokens: int = 0
    p_unsafe: float | None = None  # continuous score from logprobs (SEM-17), when available

    def is_unsafe(self, mode: str = "loose") -> bool:
        """strict: Controversial -> unsafe; loose: Controversial -> safe (but log it)."""
        if self.safety == "Unsafe":
            return True
        return mode == "strict" and self.safety == "Controversial"


def parse_output(text: str) -> GuardVerdict:
    s = _SAFETY_RE.search(text or "")
    c = _CATS_RE.search(text or "")
    r = _REFUSAL_RE.search(text or "")
    cats: list[str] = []
    if c:
        line = c.group(1).split("\n")[0].strip()
        if line and line.lower() != "none":
            cats = [x.strip().rstrip(".") for x in line.split(",") if x.strip()]
    return GuardVerdict(
        safety=s.group(1).capitalize() if s else "Unknown",
        categories=cats,
        refusal=(r.group(1).lower() == "yes") if r else None,
        raw=text or "",
    )


def messages_for(text: str, *, mode: str = "prompt", prompt: str | None = None) -> list[dict]:
    """Prompt mode: [user]. Response mode: [user (the request, may be empty), assistant]."""
    if mode == "response":
        return [{"role": "user", "content": prompt or ""}, {"role": "assistant", "content": text}]
    return [{"role": "user", "content": text}]


def payload(
    model: str, prompt: str, *, keep_alive: str = "30m", num_ctx: int = 2048, logprobs: bool = True
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "raw": True,
        "stream": False,
        "keep_alive": keep_alive,
        "options": {
            "temperature": 0,
            "top_k": 1,
            "num_predict": 32,
            "num_ctx": num_ctx,
            "stop": ["<|im_end|>", "<|im_start|>"],
        },
    }
    if logprobs:
        body["logprobs"] = True
        body["top_logprobs"] = 5
    return body


def _p_unsafe(resp: dict[str, Any]) -> float | None:
    """P(Unsafe) + 0.5 * P(Controversial) at the token right after 'Safety:' (SEM-17)."""
    lps = resp.get("logprobs") or []
    if not isinstance(lps, list):
        return None
    seen = ""
    for item in lps:
        tok = str(item.get("token", ""))
        if "Safety:" in seen and tok.strip():
            probs = {"unsafe": 0.0, "controversial": 0.0, "safe": 0.0}
            for cand in item.get("top_logprobs") or [
                {"token": tok, "logprob": item.get("logprob", 0.0)}
            ]:
                t = str(cand.get("token", "")).strip().lower()
                for k in probs:
                    if t and k.startswith(t) and len(t) >= 2:
                        probs[k] += math.exp(float(cand.get("logprob", -99.0)))
                        break
            total = sum(probs.values())
            if total <= 0:
                return None
            return min(1.0, (probs["unsafe"] + 0.5 * probs["controversial"]) / total)
        seen += tok
    return None


def verdict_from_response(resp: dict[str, Any]) -> GuardVerdict:
    v = parse_output(str(resp.get("response", "")))
    v.prompt_tokens = int(resp.get("prompt_eval_count") or 0)
    v.output_tokens = int(resp.get("eval_count") or 0)
    try:
        v.p_unsafe = _p_unsafe(resp)
    except Exception:
        v.p_unsafe = None
    return v


def verdict_to_score(
    v: GuardVerdict,
    *,
    mode: str = "prompt",
    model: str = MODEL_NAME,
    latency_ms: float = 0.0,
    continuous: bool = False,
) -> ScoreResult:
    """GuardVerdict -> ScoreResult (Unsafe 1.0 / Controversial 0.5 / Safe 0.0).

    ``continuous=True`` blends in the logprob score while keeping the label's band, so the
    discrete verdict stays authoritative (a Safe verdict never crosses 0.5).
    """
    score = SAFETY_SCORE.get(v.safety, 0.0)
    if continuous and v.p_unsafe is not None:
        lo, hi = {"Unsafe": (0.80, 1.0), "Controversial": (0.50, 0.80), "Safe": (0.0, 0.30)}.get(
            v.safety, (0.0, 1.0)
        )
        score = lo + (hi - lo) * v.p_unsafe
    strictness = "strict" if mode == "prompt" else "loose"
    reason = f"safety={v.safety} mode={mode} ({strictness})"
    if mode == "response" and v.refusal is not None:
        reason += f" refusal={'yes' if v.refusal else 'no'}"
    return ScoreResult(
        score=round(score, 4),
        label=v.safety,
        model=model,
        latency_ms=latency_ms,
        categories=list(v.categories),
        reason=reason,
    )


__all__ = [
    "DEFAULT_MODEL",
    "SAFETY_SCORE",
    "GuardVerdict",
    "build_prompt",
    "messages_for",
    "parse_output",
    "payload",
    "sanitize",
    "verdict_from_response",
    "verdict_to_score",
]
