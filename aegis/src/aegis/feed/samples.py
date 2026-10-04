"""Runtime generators of **benign** model-artifact samples for SIG-02 tests and demos.

Nothing malicious is committed or generated: the "bad" pickles only reference harmless stdlib
globals (`collections.Counter`, `datetime.date`) that sit outside the tensor-rebuild allowlist,
which is exactly how the gate decides. The GGUF "SSTI" sample carries a template string that is
never rendered.
"""

from __future__ import annotations

import collections
import datetime
import io
import json
import pickle
import struct
import zipfile
from collections.abc import Callable
from pathlib import Path


def clean_safetensors() -> bytes:
    hdr = json.dumps(
        {
            "w": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]},
            "__metadata__": {"format": "pt"},
        }
    ).encode()
    return len(hdr).to_bytes(8, "little") + hdr + b"\x00\x00\x80\x3f"


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def clean_torch_zip() -> bytes:
    """torch.save-shaped ZIP whose pickle only uses allowlisted globals."""
    return _zip(
        {
            "archive/data.pkl": pickle.dumps(collections.OrderedDict(w=1), protocol=2),
            "archive/version": b"3\n",
            "archive/data/0": b"\x00" * 16,
        }
    )


def counter_pickle() -> bytes:
    return pickle.dumps(collections.Counter(a=1), protocol=2)  # GLOBAL collections Counter


def date_pickle() -> bytes:
    return pickle.dumps(datetime.date(2025, 2, 6), protocol=4)  # STACK_GLOBAL datetime.date


def truncated_pickle() -> bytes:
    """nullifAI-style: valid prefix, broken stream (no STOP) - must fail closed."""
    return pickle.dumps(collections.OrderedDict(w=1), protocol=2)[:-1]


def zip_hidden_pickle() -> bytes:
    """Off-allowlist pickle hidden in a ZIP member without a pickle extension."""
    return _zip({"weights/tensor.dat": counter_pickle(), "archive/version": b"3\n"})


def sevenzip_bin() -> bytes:
    return b"7z\xbc\xaf\x27\x1c\x00\x04" + b"\x00" * 56


def keras_lambda_config() -> bytes:
    cfg = {
        "class_name": "Sequential",
        "config": {
            "name": "seq",
            "layers": [
                {"class_name": "InputLayer", "config": {"batch_shape": [None, 4]}},
                {
                    "class_name": "Lambda",
                    "config": {
                        "name": "lambda",
                        "function": {
                            "class_name": "__lambda__",
                            "config": {"code": "<base64 bytecode elided>"},
                        },
                    },
                },
            ],
        },
    }
    return json.dumps(cfg).encode()


def keras_lambda_zip() -> bytes:
    return _zip(
        {"config.json": keras_lambda_config(), "metadata.json": b'{"keras_version":"3.6.0"}'}
    )


def _gguf(kv: dict[str, str]) -> bytes:
    out = (
        bytearray(b"GGUF")
        + struct.pack("<I", 3)
        + struct.pack("<Q", 0)
        + struct.pack("<Q", len(kv))
    )
    for k, v in kv.items():
        kb, vb = k.encode(), v.encode()
        out += (
            struct.pack("<Q", len(kb)) + kb + struct.pack("<I", 8) + struct.pack("<Q", len(vb)) + vb
        )
    return bytes(out)


def gguf_clean() -> bytes:
    return _gguf(
        {
            "general.architecture": "llama",
            "tokenizer.chat_template": "{% for m in messages %}{{ m['content'] }}{% endfor %}",
        }
    )


def gguf_ssti() -> bytes:
    return _gguf(
        {
            "general.architecture": "llama",
            "tokenizer.chat_template": "{{ ''.__class__.__mro__[1].__subclasses__() }}",
        }
    )


def gguf_truncated() -> bytes:
    return gguf_clean()[:-7]


def unknown_blob() -> bytes:
    return b"\x13\x37MODEL" + b"\x01" * 32


#: filename -> (generator, expected SIG-02 verdict)
SAMPLES: dict[str, tuple[Callable[[], bytes], str]] = {
    "model.safetensors": (clean_safetensors, "allow"),
    "pytorch_model.bin": (clean_torch_zip, "allow"),
    "weights.bin": (counter_pickle, "block"),
    "date.pkl": (date_pickle, "block"),
    "truncated.pt": (truncated_pickle, "block"),
    "hidden.pt": (zip_hidden_pickle, "block"),
    "nullifai.bin": (sevenzip_bin, "block"),
    "config.json": (keras_lambda_config, "block"),
    "lambda.keras": (keras_lambda_zip, "block"),
    "ssti.gguf": (gguf_ssti, "block"),
    "clean.gguf": (gguf_clean, "allow"),
    "broken.gguf": (gguf_truncated, "block"),
    "model.xyz": (unknown_blob, "block"),
}


def write_samples(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, (gen, _) in SAMPLES.items():
        p = out / name
        p.write_bytes(gen())
        paths.append(p)
    return paths
