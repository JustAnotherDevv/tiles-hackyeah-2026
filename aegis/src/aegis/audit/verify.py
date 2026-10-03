"""Tamper verification of the hash-chained audit log + CLI.

`python -m aegis verify-audit [--data-dir D] [--json] [--tamper-demo]` dispatches to `main(argv)`;
`python -m aegis.audit.verify ...` works too. The CLI only reads: it never appends to the chain.

    chain OK (128 records, 1 files, head 41d9...c07e)                       exit 0
    chain BROKEN at seq 20 (audit-20261003.jsonl:20): hash mismatch          exit 1

`--tamper-demo` copies the audit dir to a temp dir, flips one byte in the middle record of the
COPY, verifies both and exits 0. The real log is never touched.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from aegis.audit.chain import GENESIS, audit_files, chain_hash, read_head
from aegis.core.types import AuditVerifyResult


def _short(h: str) -> str:
    return f"{h[:4]}…{h[-4:]}" if len(h) >= 8 else h


def verify_dir(audit_dir: Path | str) -> AuditVerifyResult:
    """Walk every chain file in order; check parse, seq, prev_hash, hash, then HEAD.json.

    HEAD.json is read BEFORE the walk (the writer updates it after each line), so a record
    appended concurrently by a running gateway never shows up as a false "HEAD ahead".
    """
    audit_dir = Path(audit_dir)
    head = read_head(audit_dir)
    files = audit_files(audit_dir)
    expected = 1
    running = GENESIS
    records = 0
    newest = files[-1] if files else None
    for path in files:
        try:
            fh = path.open("rb")
        except OSError as exc:
            return AuditVerifyResult(
                ok=False, records=records, head_hash=running, broken_at_seq=expected,
                files=len(files), message=f"cannot read {path.name}: {exc}",
            )
        with fh:
            lineno = 0
            for raw in fh:
                lineno += 1
                if not raw.endswith(b"\n"):
                    if path == newest:
                        # torn last line of the live file: a write in flight (or a crash) - not
                        # part of the verified chain yet
                        break
                    return _broken(records, running, expected, files, path, lineno, "torn line")
                line = raw[:-1]
                if not line.strip():
                    return _broken(records, running, expected, files, path, lineno, "empty line")
                try:
                    rec = json.loads(line)
                except ValueError:
                    return _broken(records, running, expected, files, path, lineno, "unparseable record")
                if not isinstance(rec, dict):
                    return _broken(records, running, expected, files, path, lineno, "not an object")
                seq = rec.get("seq")
                if seq != expected:
                    return _broken(
                        records, running, expected, files, path, lineno,
                        f"sequence gap (expected {expected}, found {seq})",
                    )
                if rec.get("prev_hash") != running:
                    return _broken(records, running, expected, files, path, lineno, "prev_hash mismatch")
                if chain_hash(running, rec) != rec.get("hash"):
                    return _broken(records, running, expected, files, path, lineno, "hash mismatch")
                running = rec["hash"]
                records += 1
                expected += 1
    if head:
        hseq = int(head.get("seq") or 0)
        if hseq > records:
            return AuditVerifyResult(
                ok=False, records=records, head_hash=running, broken_at_seq=records + 1,
                files=len(files),
                message=f"HEAD ahead of log: HEAD seq {hseq}, log ends at seq {records} (tail truncated)",
            )
        if hseq == records and records and head.get("hash") != running:
            return AuditVerifyResult(
                ok=False, records=records, head_hash=running, broken_at_seq=records,
                files=len(files), message="HEAD hash does not match the last record",
            )
    msg = (
        f"chain OK ({records} records, {len(files)} files, head {_short(running)})"
        if records
        else "chain OK (0 records)"
    )
    return AuditVerifyResult(ok=True, records=records, head_hash=running, files=len(files), message=msg)


def _broken(
    records: int, running: str, seq: int, files: list[Path], path: Path, lineno: int, why: str
) -> AuditVerifyResult:
    return AuditVerifyResult(
        ok=False,
        records=records,
        head_hash=running,
        broken_at_seq=seq,
        files=len(files),
        message=f"chain BROKEN at seq {seq} ({path.name}:{lineno}): {why}",
    )


def human(result: AuditVerifyResult) -> str:
    return result.message or ("chain OK" if result.ok else "chain BROKEN")


def tamper_copy(audit_dir: Path, dest: Path) -> tuple[int, str] | None:
    """Copy audit_dir -> dest and flip one byte inside the middle record. (seq, file) or None."""
    shutil.copytree(audit_dir, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".lock"))
    files = audit_files(dest)
    lines: list[tuple[Path, int, int, bytes]] = []  # (file, offset, lineno, raw)
    for path in files:
        offset = 0
        with path.open("rb") as fh:
            for i, raw in enumerate(fh, 1):
                lines.append((path, offset, i, raw))
                offset += len(raw)
    if not lines:
        return None
    path, offset, _lineno, raw = lines[len(lines) // 2]
    try:
        rec = json.loads(raw)
        seq = int(rec.get("seq") or 0)
    except ValueError:
        seq = 0
    # flip a byte inside the value of "event_type"/"ts" region: pick the middle of the line,
    # avoiding the newline; prefer a digit so the JSON stays parseable (pure content tamper)
    mid = len(raw) // 2
    pos = None
    for delta in range(len(raw)):
        for cand in (mid + delta, mid - delta):
            if 0 <= cand < len(raw) - 1 and chr(raw[cand]).isdigit():
                pos = cand
                break
        if pos is not None:
            break
    if pos is None:
        pos = mid
    data = bytearray(path.read_bytes())
    ch = data[offset + pos]
    data[offset + pos] = (ord("0") + (ch - ord("0") + 1) % 10) if chr(ch).isdigit() else ch ^ 0x01
    path.write_bytes(bytes(data))
    return seq, path.name


def _default_data_dir() -> Path:
    try:
        from aegis.settings import get_settings

        return Path(get_settings().data_dir)
    except Exception:
        return Path("data")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m aegis verify-audit", description="Verify the Aegis hash-chained audit log."
    )
    parser.add_argument("--data-dir", type=Path, default=None, help="AEGIS_DATA_DIR (default: settings)")
    parser.add_argument("--json", action="store_true", help="print AuditVerifyResult JSON")
    parser.add_argument(
        "--tamper-demo",
        action="store_true",
        help="flip one byte in a temp COPY of the log and show that verify catches it",
    )
    args = parser.parse_args(argv)
    data_dir = args.data_dir or _default_data_dir()
    audit_dir = Path(data_dir) / "audit"

    result = verify_dir(audit_dir)
    if not args.tamper_demo:
        if args.json:
            print(json.dumps(result.model_dump(mode="json"), indent=2))
        else:
            print(human(result))
        return 0 if result.ok else 1

    out: dict[str, Any] = {"original": result.model_dump(mode="json")}
    with tempfile.TemporaryDirectory(prefix="aegis-tamper-") as tmp:
        target = tamper_copy(audit_dir, Path(tmp) / "audit")
        if target is None:
            print("tamper demo: no audit records yet (send some traffic first)")
            return 0
        tampered = verify_dir(Path(tmp) / "audit")
        out["tampered"] = tampered.model_dump(mode="json")
        out["flipped"] = {"seq": target[0], "file": target[1]}
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"tamper demo: flipped one byte in record seq {target[0]} of a temp copy ({target[1]})")
        print(f"tampered copy: {human(tampered)}")
        print(f"original:      {human(result)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
