"""AUD-V03: hash chain, tamper evidence, resume, UTC-midnight rollover, CLI (AUD-V03b)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from am_fakes import make_rt

from aegis.audit import verify as verify_mod
from aegis.audit.chain import GENESIS, audit_files, canonical_json, chain_hash
from aegis.audit.log import AuditService
from aegis.audit.verify import verify_dir
from aegis.core.types import AuditEvent, new_id


def _ev(i: int) -> AuditEvent:
    return AuditEvent(
        event_id=new_id("evt"),
        event_type="system",
        reason=f"event {i}",
        data={"kind": "test", "i": i},
    )


async def _write(rt, n: int) -> None:
    for i in range(n):
        await rt.audit.record(_ev(i))


def _lines(audit_dir: Path) -> tuple[Path, list[bytes]]:
    f = audit_files(audit_dir)[0]
    return f, f.read_bytes().splitlines(keepends=True)


async def test_contiguous_chain_and_formula(am_rt):
    await _write(am_rt, 100)
    _f, lines = _lines(am_rt.audit.audit_dir)
    assert len(lines) == 100
    prev = GENESIS
    for i, raw in enumerate(lines, 1):
        rec = json.loads(raw)
        assert rec["seq"] == i
        assert rec["prev_hash"] == prev
        assert rec["hash"] == chain_hash(prev, rec)
        assert raw == (canonical_json(rec) + "\n").encode()  # what is written is what is hashed
        prev = rec["hash"]
    res = await am_rt.audit.verify()  # flushes the deferred HEAD.json first
    head = json.loads((am_rt.audit.audit_dir / "HEAD.json").read_text())
    assert head["seq"] == 100 and head["hash"] == prev
    assert res.ok and res.records == 100
    assert res.message.startswith("chain OK (100 records")


async def test_record_returns_seq_and_hash(am_rt):
    out = await am_rt.audit.record(_ev(0))
    assert out.seq == 1 and out.prev_hash == GENESIS and len(out.hash) == 64


async def test_tamper_byte_flip_delete_swap_truncate(tmp_path):
    rt = make_rt(tmp_path)
    await rt.audit.start()
    await _write(rt, 50)
    await rt.audit.stop()
    audit_dir = rt.audit.audit_dir
    f, lines = _lines(audit_dir)
    original = list(lines)

    # byte flip in line 20
    l20 = bytearray(lines[19])
    pos = l20.index(b"event 19") + 6
    l20[pos] = ord("8")
    f.write_bytes(b"".join([*lines[:19], bytes(l20), *lines[20:]]))
    r = verify_dir(audit_dir)
    assert not r.ok and r.broken_at_seq == 20 and "hash mismatch" in r.message

    # delete line 30
    f.write_bytes(b"".join(original[:29] + original[30:]))
    r = verify_dir(audit_dir)
    assert not r.ok and r.broken_at_seq == 30

    # swap lines 10/11
    sw = list(original)
    sw[9], sw[10] = sw[10], sw[9]
    f.write_bytes(b"".join(sw))
    r = verify_dir(audit_dir)
    assert not r.ok and r.broken_at_seq == 10

    # truncate the last 5 -> HEAD ahead
    f.write_bytes(b"".join(original[:45]))
    r = verify_dir(audit_dir)
    assert not r.ok and "HEAD ahead" in r.message

    # restore -> OK
    f.write_bytes(b"".join(original))
    assert verify_dir(audit_dir).ok


async def test_utc_midnight_rollover_two_files(tmp_path):
    t = [datetime(2026, 10, 3, 23, 59, 58, tzinfo=UTC)]
    rt = make_rt(tmp_path)
    rt.audit = AuditService(rt, clock=lambda: t[0])
    await rt.audit.start()
    for i in range(6):
        await rt.audit.record(_ev(i))
        t[0] += timedelta(seconds=1)
    await rt.audit.stop()
    files = audit_files(rt.audit.audit_dir)
    assert [p.name for p in files] == ["audit-20261003.jsonl", "audit-20261004.jsonl"]
    r = verify_dir(rt.audit.audit_dir)
    assert r.ok and r.records == 6 and r.files == 2


async def test_restart_continues_chain(tmp_path):
    rt = make_rt(tmp_path)
    await rt.audit.start()
    await _write(rt, 5)
    await rt.audit.stop()
    rt2 = make_rt(tmp_path)
    await rt2.audit.start()
    out = await rt2.audit.record(_ev(99))
    await rt2.audit.stop()
    assert out.seq == 6
    r = verify_dir(rt2.audit.audit_dir)
    assert r.ok and r.records == 6


async def test_partial_trailing_line_repaired_on_resume(tmp_path):
    rt = make_rt(tmp_path)
    await rt.audit.start()
    await _write(rt, 3)
    await rt.audit.stop()
    f = audit_files(rt.audit.audit_dir)[0]
    with f.open("ab") as fh:
        fh.write(b'{"seq":4,"torn')
    rt2 = make_rt(tmp_path)
    await rt2.audit.start()
    out = await rt2.audit.record(_ev(4))
    await rt2.audit.stop()
    assert out.seq == 4
    assert verify_dir(rt2.audit.audit_dir).ok


async def test_second_writer_is_log_only(tmp_path):
    rt = make_rt(tmp_path)
    await rt.audit.start()
    rt2 = make_rt(tmp_path)
    await rt2.audit.start()
    assert rt2.audit.log_only
    out = await rt2.audit.record(_ev(0))
    assert out.seq == 0  # not appended: no chain fork
    await rt2.audit.stop()
    await rt.audit.record(_ev(1))
    await rt.audit.stop()
    assert verify_dir(rt.audit.audit_dir).ok


async def test_cli_verify_and_tamper_demo(tmp_path, capsys):
    rt = make_rt(tmp_path)
    await rt.audit.start()
    await _write(rt, 12)
    await rt.audit.stop()
    data_dir = str(tmp_path / "data")
    assert verify_mod.main(["--data-dir", data_dir]) == 0
    out = capsys.readouterr().out
    assert out.startswith("chain OK (12 records, 1 files, head ")
    before = audit_files(rt.audit.audit_dir)[0].read_bytes()
    assert verify_mod.main(["--data-dir", data_dir, "--tamper-demo"]) == 0
    out = capsys.readouterr().out
    assert "tampered copy: chain BROKEN at seq" in out
    assert "original:      chain OK" in out
    assert audit_files(rt.audit.audit_dir)[0].read_bytes() == before  # real log untouched
    assert verify_mod.main(["--data-dir", data_dir, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


async def test_batched_projection_production_path(tmp_path):
    from am_fakes import decision_event

    rt = make_rt(tmp_path)
    rt.audit.test_mode = False  # batched SQLite projection, no background verify loop started here
    await rt.audit.start()
    evs = [decision_event() for _ in range(40)]
    for ev in evs:
        await rt.audit.record(ev)
    assert rt.audit.recent_detail(evs[-1].decision_id)["audit_seq"] >= 40  # LRU is immediate
    await rt.audit.stop()  # drains the queue and flushes HEAD
    conn = rt.audit.connection()
    try:
        n_idx = conn.execute("SELECT COUNT(*) FROM audit_index").fetchone()[0]
        n_dec = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    finally:
        conn.close()
    assert n_dec == 40 and n_idx >= 41  # + the audit.started system event
    head = json.loads((rt.audit.audit_dir / "HEAD.json").read_text())
    r = verify_dir(rt.audit.audit_dir)
    assert r.ok and head["seq"] == r.records
