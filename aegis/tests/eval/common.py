"""Shared helpers for eval + bench: paths, machine block, atomic JSON writes, bench.json merge."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BENCH_SCHEMA = "aegis.bench/1"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def reports_dir(out: str | Path | None = None) -> Path:
    p = Path(out or os.environ.get("AEGIS_REPORTS_DIR") or "reports")
    if not p.is_absolute():
        p = ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def ensure_import_paths() -> None:
    """Make `tests.*` and `aegis` importable when run as a file (not -m) or without the package."""
    for p in (str(ROOT), str(ROOT / "src")):
        if p not in sys.path:
            sys.path.insert(0, p)


def _cpu() -> str:
    try:
        return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True,
                              timeout=2).stdout.strip() or platform.processor()
    except Exception:
        return platform.processor() or platform.machine()


def machine_info(load_generator: str | None = None) -> dict[str, Any]:
    info: dict[str, Any] = {"cpu": _cpu(), "arch": platform.machine(), "python": platform.python_version()}
    mac = platform.mac_ver()[0]
    info["os"] = f"macOS {mac}" if mac else f"{platform.system()} {platform.release()}"
    try:
        import psutil

        vm = psutil.virtual_memory()
        info["ram_gb"] = round(vm.total / 2**30, 1)
        info["available_gb_at_start"] = round(vm.available / 2**30, 2)
        info["cpu_count"] = psutil.cpu_count(logical=True)
    except Exception:
        pass
    try:  # metadata only - importing onnxruntime itself costs RAM and crashes at interpreter exit
        from importlib.metadata import version

        info["onnxruntime"] = version("onnxruntime")
    except Exception:
        info["onnxruntime"] = None
    if load_generator:
        info["load_generator"] = load_generator
    return info


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            f.write("\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def minimal_bench() -> dict[str, Any]:
    return {"schema": BENCH_SCHEMA, "generated_at": now_iso(), "status": "partial", "profiles": [],
            "by_control": [], "modes": {}, "headline": {}, "note": "no load benchmark yet - run `make bench`"}


def merge_bench(out_dir: Path, updates: dict[str, Any], headline: dict[str, Any] | None = None) -> Path:
    """Atomic read-modify-write of reports/bench.json (keeps every key we don't update)."""
    path = out_dir / "bench.json"
    cur = read_json(path) or minimal_bench()
    cur.update(updates)
    if headline:
        h = dict(cur.get("headline") or {})
        h.update(headline)
        cur["headline"] = h
    write_json_atomic(path, cur)
    return path


__all__ = ["BENCH_SCHEMA", "ROOT", "ensure_import_paths", "machine_info", "merge_bench", "minimal_bench",
           "now_iso", "read_json", "reports_dir", "write_json_atomic", "write_text_atomic"]
