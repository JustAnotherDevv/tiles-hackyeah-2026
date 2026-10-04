"""Hash chain primitives and the append-only JSONL writer (CONTRACTS section 6.2).

    hash = sha256(prev_hash + canonical_json(record_without_"hash"))
    canonical_json = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                default=str)
    genesis prev_hash = "0" * 64, first seq = 1

The line written is `canonical_json(record_with_hash) + "\\n"`, so whatever is on disk is exactly
what was hashed (verify re-parses the line). stdlib `json` is used on purpose (not orjson) so
third parties can reproduce the hash from the contract formula.

Files: `data/audit/audit-YYYYMMDD.jsonl` (UTC date at write time; the chain continues across
files) + `data/audit/HEAD.json` `{"seq", "hash", "file"}` rewritten atomically after each append.
`data/audit/.lock` (fcntl.flock) guarantees a single writer process. Not thread-safe by itself:
callers serialize `append_record()` (AuditService holds a lock).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:  # POSIX only; Windows runs without the single-writer guard
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

GENESIS = "0" * 64
FILE_PREFIX = "audit-"
FILE_SUFFIX = ".jsonl"
HEAD_NAME = "HEAD.json"
LOCK_NAME = ".lock"
HEAD_EVERY = 100  # with deferred HEAD writes: rewrite HEAD.json at least every N records


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def chain_hash(prev_hash: str, record: dict[str, Any]) -> str:
    """sha256(prev_hash + canonical_json(record minus "hash")) as hex."""
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256((prev_hash + canonical_json(body)).encode("utf-8")).hexdigest()


def audit_files(audit_dir: Path) -> list[Path]:
    """Chain files in chain order (names sort by UTC date)."""
    if not audit_dir.is_dir():
        return []
    return sorted(
        p
        for p in audit_dir.iterdir()
        if p.is_file() and p.name.startswith(FILE_PREFIX) and p.name.endswith(FILE_SUFFIX)
    )


def file_name_for(dt: datetime) -> str:
    return f"{FILE_PREFIX}{dt.astimezone(UTC):%Y%m%d}{FILE_SUFFIX}"


def read_last_line(path: Path) -> bytes | None:
    """Last complete line (without the newline) of a file, None if the file has none."""
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size == 0:
        return None
    with path.open("rb") as fh:
        chunk = 65536
        end = size
        buf = b""
        while end > 0:
            start = max(0, end - chunk)
            fh.seek(start)
            buf = fh.read(end - start) + buf
            end = start
            stripped = buf.rstrip(b"\n")
            idx = stripped.rfind(b"\n")
            if idx >= 0:
                return stripped[idx + 1 :]
            if end == 0:
                return stripped or None
    return None


def read_head(audit_dir: Path) -> dict[str, Any] | None:
    try:
        return json.loads((audit_dir / HEAD_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_head(audit_dir: Path, seq: int, head: str, file: str | None) -> None:
    tmp = audit_dir / (HEAD_NAME + ".tmp")
    tmp.write_text(json.dumps({"seq": seq, "hash": head, "file": file}), encoding="utf-8")
    os.replace(tmp, audit_dir / HEAD_NAME)


@dataclass
class Appended:
    file: str
    line: int  # 1-based line number in `file`
    offset: int  # byte offset of the line start
    length: int  # bytes incl. the trailing newline


class ChainWriter:
    """Single-writer appender with resume, partial-line repair and HEAD tracking."""

    def __init__(self, audit_dir: Path, clock: Callable[[], datetime] | None = None) -> None:
        self.audit_dir = Path(audit_dir)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.seq = 0
        self.head = GENESIS
        self.file: str | None = None
        self.locked = False  # True once we own .lock (append allowed)
        self.notes: list[str] = []  # resume/repair notes (surfaced as `system` events)
        self.head_ahead: str | None = None  # set when HEAD.json is ahead of the log (truncation)
        self._lock_fh: Any = None
        self._fh: Any = None
        self._fh_name: str | None = None
        self._lines: dict[str, int] = {}
        self._sizes: dict[str, int] = {}
        # HEAD.json lags the chain by at most HEAD_EVERY records / one deferred flush when
        # defer_head is set (AuditService flushes ~250 ms after the last append and on close).
        # A lagging HEAD never fails verify; only a HEAD *ahead* of the log does.
        self.defer_head = False
        self.head_dirty = False
        self._head_written_seq = 0

    # ------------------------------------------------------------------ lifecycle
    def open(self) -> bool:
        """Create dirs, take the writer lock, resume from disk. Returns True if appends allowed."""
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.locked = self._acquire_lock()
        self._resume(repair=self.locked)
        if self.locked:
            with contextlib.suppress(OSError):
                write_head(self.audit_dir, self.seq, self.head, self.file)
                self._head_written_seq = self.seq
        return self.locked

    def close(self, fsync: bool = True) -> None:
        self.flush_head()
        if self._fh is not None:
            try:
                self._fh.flush()
                if fsync:
                    os.fsync(self._fh.fileno())
            except OSError:
                log.warning("audit flush failed on close")
            with contextlib.suppress(OSError):
                self._fh.close()
            self._fh = None
            self._fh_name = None
        if self._lock_fh is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(self._lock_fh.fileno(), fcntl.LOCK_UN)
                self._lock_fh.close()
            except OSError:
                pass
            self._lock_fh = None
        self.locked = False

    def _acquire_lock(self) -> bool:
        if fcntl is None:  # pragma: no cover
            return True
        try:
            fh = (self.audit_dir / LOCK_NAME).open("a+")
        except OSError:
            log.exception("audit lock file unavailable dir=%s", self.audit_dir)
            return False
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            log.error("audit log locked by another process dir=%s (log-only mode)", self.audit_dir)
            return False
        self._lock_fh = fh
        return True

    def _resume(self, *, repair: bool) -> None:
        files = audit_files(self.audit_dir)
        last: dict[str, Any] | None = None
        last_file: str | None = None
        for path in reversed(files):
            if repair:
                self._repair_partial(path)
            raw = read_last_line(path)
            if raw is None:
                continue
            try:
                last = json.loads(raw)
                last_file = path.name
                break
            except ValueError:
                self.notes.append(f"unparseable last line in {path.name}")
                log.warning("audit resume: unparseable last line file=%s", path.name)
                break
        if last is not None:
            self.seq = int(last.get("seq") or 0)
            self.head = str(last.get("hash") or GENESIS)
            self.file = last_file
        head = read_head(self.audit_dir)
        if head and int(head.get("seq") or 0) > self.seq:
            self.head_ahead = (
                f"HEAD ahead of log: HEAD seq {head.get('seq')}, log ends at seq {self.seq} "
                "(tail truncated)"
            )
            self.notes.append(self.head_ahead)
            log.error("audit resume: %s", self.head_ahead)
        if self.seq:
            self.notes.append(f"resumed at seq {self.seq}")

    def _repair_partial(self, path: Path) -> None:
        """Truncate a crash-torn trailing line back to the last newline."""
        try:
            size = path.stat().st_size
            if size == 0:
                return
            with path.open("rb+") as fh:
                fh.seek(size - 1)
                if fh.read(1) == b"\n":
                    return
                pos = size
                chunk = 65536
                cut = 0
                while pos > 0:
                    start = max(0, pos - chunk)
                    fh.seek(start)
                    data = fh.read(pos - start)
                    idx = data.rfind(b"\n")
                    if idx >= 0:
                        cut = start + idx + 1
                        break
                    pos = start
                fh.truncate(cut)
            msg = f"repaired partial trailing line in {path.name} ({size - cut} bytes dropped)"
            self.notes.append(msg)
            log.warning("audit %s", msg)
        except OSError:
            log.exception("audit partial-line repair failed file=%s", path.name)

    # ------------------------------------------------------------------ append
    def _handle_for(self, name: str) -> Any:
        if self._fh is not None and self._fh_name == name:
            return self._fh
        if self._fh is not None:
            with contextlib.suppress(OSError):
                self._fh.flush()
                self._fh.close()
        path = self.audit_dir / name
        fh = path.open("ab")
        if name not in self._lines:
            try:
                with path.open("rb") as rf:
                    self._lines[name] = sum(
                        chunk.count(b"\n") for chunk in iter(lambda: rf.read(1 << 20), b"")
                    )
            except OSError:
                self._lines[name] = 0
        self._sizes[name] = fh.tell()
        self._fh, self._fh_name = fh, name
        return fh

    def append_record(self, record: dict[str, Any]) -> tuple[dict[str, Any], Appended]:
        """Assign seq/prev_hash/hash, append the canonical line, update HEAD. Caller serializes."""
        if not self.locked:
            raise RuntimeError("audit writer not locked (log-only mode)")
        rec = dict(record)
        rec["seq"] = self.seq + 1
        rec["prev_hash"] = self.head
        rec.pop("hash", None)
        rec["hash"] = chain_hash(self.head, rec)
        data = (canonical_json(rec) + "\n").encode("utf-8")
        name = file_name_for(self.clock())
        fh = self._handle_for(name)
        offset = self._sizes.get(name, 0)
        fh.write(data)
        fh.flush()
        self._sizes[name] = offset + len(data)
        self._lines[name] = self._lines.get(name, 0) + 1
        self.seq = rec["seq"]
        self.head = rec["hash"]
        self.file = name
        self.head_dirty = True
        if not self.defer_head or self.seq - self._head_written_seq >= HEAD_EVERY:
            self.flush_head()
        return rec, Appended(file=name, line=self._lines[name], offset=offset, length=len(data))

    def flush_head(self) -> None:
        """Rewrite HEAD.json (atomic) if it lags the chain. Callers serialize with appends."""
        if not self.head_dirty or not self.locked:
            return
        try:
            write_head(self.audit_dir, self.seq, self.head, self.file)
            self._head_written_seq = self.seq
            self.head_dirty = False
        except OSError:
            log.warning("audit HEAD.json update failed seq=%s", self.seq)


__all__ = [
    "GENESIS",
    "Appended",
    "ChainWriter",
    "audit_files",
    "canonical_json",
    "chain_hash",
    "file_name_for",
    "read_head",
    "read_last_line",
    "write_head",
]
