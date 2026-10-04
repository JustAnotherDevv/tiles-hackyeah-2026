"""Micro-benchmark: per-chunk overhead of the streaming path.

    uv run --python 3.13 python bench.py [--deltas 3000] [--repeat 5]

Worst-case granularity: every upstream network chunk carries exactly one SSE
event (real upstreams often coalesce several).  Reports mean / p50 / p99
microseconds per chunk and throughput for each pipeline configuration.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path
from time import perf_counter_ns

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "tests"))

from helpers import anthropic_stream, ollama_chat_stream, openai_stream  # noqa: E402

from aegis_stream import (  # noqa: E402
    AnthropicStreamTransformer,
    LeakScanner,
    MappingVault,
    OllamaStreamTransformer,
    OpenAIChatStreamTransformer,
    SSEParser,
    StreamOptions,
    TextChannel,
)

WORDS = ("the quick brown fox jumps over a lazy dog while the gateway keeps every customer record "
         "local and only placeholders leave the machine for the remote model").split()
PLACEHOLDERS = ["[PERSON_1]", "[EMAIL_1]", "[PL_PESEL_1]", "[IBAN_1]"]
VAULT = MappingVault({"[PERSON_1]": "Jan Kowalski", "[EMAIL_1]": "jan.kowalski@bank.pl",
                      "[PL_PESEL_1]": "44051401359", "[IBAN_1]": "PL61 1090 1014 0000 0712 1981 2874"})


def deltas(n: int, seed: int = 7) -> list[str]:
    """LLM-like token deltas (1-3 words), a placeholder split across 2 deltas every ~40."""
    rnd = random.Random(seed)
    out = []
    while len(out) < n:
        if rnd.random() < 0.025:
            ph = rnd.choice(PLACEHOLDERS)
            k = rnd.randint(1, len(ph) - 1)
            out += [" " + ph[:k], ph[k:]]
        else:
            out.append(" " + " ".join(rnd.choice(WORDS) for _ in range(rnd.randint(1, 2))))
    return out[:n]


def events_of(data: bytes) -> list[bytes]:
    parts = data.split(b"\n\n")
    return [p + b"\n\n" for p in parts if p]


def ndjson_lines(data: bytes) -> list[bytes]:
    return [ln + b"\n" for ln in data.split(b"\n") if ln]


def measure(make, chunks: list[bytes], repeat: int) -> dict:
    per_chunk: list[int] = []
    totals = []
    for _ in range(repeat):
        tr = make()
        t_all = 0
        for c in chunks:
            t0 = perf_counter_ns()
            tr.feed(c)
            dt = perf_counter_ns() - t0
            per_chunk.append(dt)
            t_all += dt
        tr.close()
        totals.append(t_all)
    per_chunk.sort()
    nbytes = sum(map(len, chunks))
    best = min(totals)
    return {
        "mean_us": statistics.fmean(per_chunk) / 1000,
        "p50_us": per_chunk[len(per_chunk) // 2] / 1000,
        "p99_us": per_chunk[int(len(per_chunk) * 0.99)] / 1000,
        "mb_s": nbytes / (best / 1e9) / 1e6,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deltas", type=int, default=3000)
    ap.add_argument("--repeat", type=int, default=5)
    args = ap.parse_args()

    ds = deltas(args.deltas)
    tool_src = json.dumps({"to": "[EMAIL_1]", "body": " ".join(ds[:200])})
    tool_chunks = [tool_src[i : i + 12] for i in range(0, len(tool_src), 12)]
    a_raw = anthropic_stream([("thinking", ds[:300], "sig"), ("text", ds), ("tool_use", "send", "t1", tool_chunks)])
    a_chunks = events_of(a_raw)
    o_chunks = events_of(openai_stream(ds))
    l_chunks = ndjson_lines(ollama_chat_stream(ds))
    scanner = LeakScanner.default()

    def A(**kw):
        return lambda: AnthropicStreamTransformer(StreamOptions(**kw))

    rows = [
        ("SSE parse only (baseline)", lambda: _ParseOnly(), a_chunks),
        ("anthropic passthrough (no vault, no scan)", A(), a_chunks),
        ("anthropic rehydrate", A(vault=VAULT), a_chunks),
        ("anthropic rehydrate + leak scan", A(vault=VAULT, scanner=scanner), a_chunks),
        ("anthropic rehydrate + scan, tool stream mode", A(vault=VAULT, scanner=scanner, tool_input_mode="stream"),
         a_chunks),
        ("openai rehydrate + leak scan",
         lambda: OpenAIChatStreamTransformer(StreamOptions(vault=VAULT, scanner=scanner)), o_chunks),
        ("ollama rehydrate + leak scan",
         lambda: OllamaStreamTransformer(StreamOptions(vault=VAULT, scanner=scanner)), l_chunks),
    ]
    print(f"python {sys.version.split()[0]} · {len(a_chunks)} anthropic events / {len(o_chunks)} openai chunks / "
          f"{len(l_chunks)} ollama lines · one event per network chunk · repeat {args.repeat}\n")
    print("| pipeline | mean µs/chunk | p50 | p99 | MB/s |")
    print("|---|---:|---:|---:|---:|")
    for name, make, chunks in rows:
        r = measure(make, chunks, args.repeat)
        print(f"| {name} | {r['mean_us']:.1f} | {r['p50_us']:.1f} | {r['p99_us']:.1f} | {r['mb_s']:.1f} |")

    # channel-level: cost per text delta (no SSE/JSON framing)
    for label, kw in (("rehydrate", {"vault": VAULT}), ("rehydrate + scan", {"vault": VAULT, "scanner": scanner})):
        best = None
        for _ in range(args.repeat):
            ch = TextChannel("bench", **kw)
            t0 = perf_counter_ns()
            for d in ds:
                ch.feed(d)
            ch.flush()
            dt = perf_counter_ns() - t0
            best = dt if best is None else min(best, dt)
        print(f"\nTextChannel {label}: {best / len(ds) / 1000:.2f} µs per delta", end="")
    print()


class _ParseOnly:
    def __init__(self) -> None:
        self.p = SSEParser()

    def feed(self, c: bytes) -> None:
        for ev in self.p.feed(c):
            json.loads(ev.data)

    def close(self) -> None:
        self.p.close()


if __name__ == "__main__":
    main()
