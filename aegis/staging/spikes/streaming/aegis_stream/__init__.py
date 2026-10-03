"""aegis_stream: streaming response path of the Aegis gateway.

Sans-IO transformers (bytes in -> bytes out) for Anthropic Messages SSE,
OpenAI chat-completions SSE and Ollama NDJSON that

* rehydrate vault placeholders (``[EMAIL_1]`` -> real value) for the local user,
  including placeholders split across deltas and inside tool-call JSON,
* scan model output for leaks (secrets, PII, image exfil links) with a sliding
  window + hold-back, and alert / mask / block,
* terminate early with protocol-valid closing events (no client retries),
* extract usage for budgets.

See README.md for the gateway integration recipe.
"""

from .aio import StreamController, stream_transform
from .anthropic import AnthropicStreamTransformer
from .base import StreamOptions, StreamReport, StreamTransformer, Termination
from .channel import TextChannel, process_json_value
from .detectors import (
    CreditCardDetector,
    Detector,
    EmailDetector,
    IbanDetector,
    KnownValueDetector,
    MarkdownImageDetector,
    Match,
    PeselDetector,
    SecretDetector,
    default_detectors,
)
from .jsonlex import JsonStreamLexer, json_escape
from .ollama import OllamaStreamTransformer
from .openai import OpenAIChatStreamTransformer, prepare_openai_request
from .placeholders import MappingVault, Vault, canonical_key, rehydrate_json_value, rehydrate_text
from .scanner import DEFAULT_ACTIONS, Finding, LeakScanner
from .sse import NDJSONLine, NDJSONParser, SSEComment, SSEEvent, SSEParser, encode_sse
from .usage import Usage

__all__ = [
    "AnthropicStreamTransformer",
    "OpenAIChatStreamTransformer",
    "OllamaStreamTransformer",
    "StreamTransformer",
    "StreamOptions",
    "StreamReport",
    "Termination",
    "StreamController",
    "stream_transform",
    "prepare_openai_request",
    "transformer_for",
    "TextChannel",
    "process_json_value",
    "LeakScanner",
    "Finding",
    "DEFAULT_ACTIONS",
    "Detector",
    "Match",
    "CreditCardDetector",
    "PeselDetector",
    "IbanDetector",
    "EmailDetector",
    "SecretDetector",
    "MarkdownImageDetector",
    "KnownValueDetector",
    "default_detectors",
    "Vault",
    "MappingVault",
    "canonical_key",
    "rehydrate_text",
    "rehydrate_json_value",
    "JsonStreamLexer",
    "json_escape",
    "SSEParser",
    "SSEEvent",
    "SSEComment",
    "NDJSONParser",
    "NDJSONLine",
    "encode_sse",
    "Usage",
]


def transformer_for(protocol: str, options: StreamOptions | None = None, **kwargs) -> StreamTransformer:
    """Factory: ``"anthropic" | "openai" | "ollama"``."""
    cls = {
        "anthropic": AnthropicStreamTransformer,
        "openai": OpenAIChatStreamTransformer,
        "ollama": OllamaStreamTransformer,
    }[protocol]
    return cls(options, **kwargs)
