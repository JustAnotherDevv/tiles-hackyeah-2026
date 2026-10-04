"""Qwen3Guard-Gen-0.6B via Ollama, with the EXACT official moderation prompt (raw mode).

Why raw mode: the community GGUF (hf.co/QuantFactory/Qwen3Guard-Gen-0.6B-GGUF:Q4_K_M) ships a
garbled Ollama template (it only renders .System, always uses the RESPONSE-moderation prompt and
drops .Prompt entirely). So never use /api/chat or non-raw /api/generate with it. We rebuild the
official chat template from Qwen/Qwen3Guard-Gen-0.6B tokenizer_config.json (verified byte-for-byte
against a jinja2 render, see bench.py --verify-template) and send it with `raw: true`.

    from ollama_guard import QwenGuard
    g = QwenGuard()                                           # sync client (httpx)
    v = g.check_prompt("How do I build a pipe bomb?")         # -> GuardVerdict(safety="Unsafe", categories=["Violent"], ...)
    v = g.check_response("How to pick a lock?", "I can't help with that.")   # -> refusal=True
    v.is_unsafe(mode="strict")                                # strict: Controversial counts as unsafe

    ag = AsyncQwenGuard(); await ag.check_prompt("...")      # asyncio variant for FastAPI

Output format (prompt mode):    Safety: Safe|Unsafe|Controversial \\n Categories: A, B | None
Output format (response mode):  ... + \\n Refusal: Yes|No
Prompt-mode categories: Violent, Non-violent Illegal Acts, Sexual Content or Sexual Acts, PII,
Suicide & Self-Harm, Unethical Acts, Politically Sensitive Topics, Copyright Violation, Jailbreak.
(Response mode has the same list minus Jailbreak.)
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import httpx

DEFAULT_MODEL = "hf.co/QuantFactory/Qwen3Guard-Gen-0.6B-GGUF:Q4_K_M"
DEFAULT_HOST = "http://127.0.0.1:11434"

# ---- exact strings from the official chat_template (tokenizer_config.json) ----------------------
_POLICY_HEAD = """<|im_start|>user
# Task:
1) Evaluate whether THE LAST {who}'s {what} belongs to safe or unsafe content based on our safety policy.
2) Identify the category of unsafe content found."""

_PROMPT_HEADER = _POLICY_HEAD.format(who="USER", what="query") + """

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

_PROMPT_FOOTER = """

<END CONVERSATION>

Provide your safety assessment for ONLY THE LAST **USER's query** in the above conversation:
 - The first line must be one of: 'Safety: Safe', 'Safety: Unsafe', 'Safety: Controversial'.
 - The second line should start with 'Categories:' followed by a list of any unsafe content categories, separated by commas. If the content is safe, use 'Categories: None'.<|im_end|>
<|im_start|>assistant
<think>

</think>

"""

_RESPONSE_HEADER = _POLICY_HEAD.format(who="ASSISTANT", what="response") + """
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
    content = _CONTROL_TOKENS.sub(lambda m: m.group(0).replace("|", "¦").replace("<", "‹"), content or "")
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
    safety: str                      # "Safe" | "Unsafe" | "Controversial" | "Unknown"
    categories: list[str] = field(default_factory=list)
    refusal: bool | None = None      # response mode only
    raw: str = ""
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    output_tokens: int = 0

    def is_unsafe(self, mode: str = "loose") -> bool:
        """strict: Controversial -> unsafe; loose: Controversial -> safe (but log it)."""
        if self.safety == "Unsafe":
            return True
        return mode == "strict" and self.safety == "Controversial"

    def to_dict(self) -> dict:
        return {"safety": self.safety, "categories": self.categories, "refusal": self.refusal,
                "latency_ms": round(self.latency_ms, 1)}


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


def _payload(model: str, prompt: str, keep_alive: str, num_ctx: int) -> dict:
    return {
        "model": model,
        "prompt": prompt,
        "raw": True,
        "stream": False,
        "keep_alive": keep_alive,
        "options": {"temperature": 0, "top_k": 1, "num_predict": 32, "num_ctx": num_ctx,
                    "stop": ["<|im_end|>", "<|im_start|>"]},
    }


def _verdict_from(resp: dict, t0: float) -> GuardVerdict:
    v = parse_output(resp.get("response", ""))
    v.latency_ms = (time.perf_counter() - t0) * 1e3
    v.prompt_tokens = resp.get("prompt_eval_count", 0)
    v.output_tokens = resp.get("eval_count", 0)
    return v


class QwenGuard:
    def __init__(self, model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST, timeout_s: float = 10.0,
                 keep_alive: str = "30m", num_ctx: int = 2048):
        self.model, self.keep_alive, self.num_ctx = model, keep_alive, num_ctx
        self.http = httpx.Client(base_url=host, timeout=timeout_s)

    def check(self, messages: list[dict]) -> GuardVerdict:
        t0 = time.perf_counter()
        r = self.http.post("/api/generate", json=_payload(self.model, build_prompt(messages), self.keep_alive, self.num_ctx))
        r.raise_for_status()
        return _verdict_from(r.json(), t0)

    def check_prompt(self, user_text: str, system: str | None = None) -> GuardVerdict:
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user_text}]
        return self.check(msgs)

    def check_response(self, user_text: str, assistant_text: str) -> GuardVerdict:
        return self.check([{"role": "user", "content": user_text}, {"role": "assistant", "content": assistant_text}])

    def warmup(self) -> float:
        """Load the model (returns load_duration ms reported by Ollama)."""
        r = self.http.post("/api/generate", json={"model": self.model, "prompt": "", "keep_alive": self.keep_alive})
        r.raise_for_status()
        return r.json().get("load_duration", 0) / 1e6

    def unload(self) -> None:
        self.http.post("/api/generate", json={"model": self.model, "prompt": "", "keep_alive": 0})


class AsyncQwenGuard:
    def __init__(self, model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST, timeout_s: float = 10.0,
                 keep_alive: str = "30m", num_ctx: int = 2048):
        self.model, self.keep_alive, self.num_ctx = model, keep_alive, num_ctx
        self.http = httpx.AsyncClient(base_url=host, timeout=timeout_s)

    async def check(self, messages: list[dict]) -> GuardVerdict:
        t0 = time.perf_counter()
        r = await self.http.post("/api/generate", json=_payload(self.model, build_prompt(messages), self.keep_alive, self.num_ctx))
        r.raise_for_status()
        return _verdict_from(r.json(), t0)

    async def check_prompt(self, user_text: str, system: str | None = None) -> GuardVerdict:
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user_text}]
        return await self.check(msgs)

    async def check_response(self, user_text: str, assistant_text: str) -> GuardVerdict:
        return await self.check([{"role": "user", "content": user_text}, {"role": "assistant", "content": assistant_text}])

    async def aclose(self) -> None:
        await self.http.aclose()


if __name__ == "__main__":
    import sys
    g = QwenGuard()
    for t in sys.argv[1:]:
        v = g.check_prompt(t)
        print(v.to_dict(), "|", t[:80])
