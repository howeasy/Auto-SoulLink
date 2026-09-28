"""RR reset-interruption gate over the native ABI witness, without an emulator."""

import struct
from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
TRADE_BASE = 0x0203FE50  # patch/src/handlers.c RT_BASE
WITNESS = 0x50           # patch/src/trade_targets/abi.h SLINK_WITNESS_OFFSET
OLD_KEY = "11223344:55667788"


def _memory():
    raw = bytearray(0xA0)

    def put(off, width, value):
        raw[off:off + width] = value.to_bytes(width, "little")

    put(0x00, 4, 0x4B4E4C53)     # shadow 'SLNK' signature
    put(0x44, 4, 7)              # shadow mailbox session_epoch
    put(0x48, 4, 3)              # producer SCENE
    w = WITNESS
    put(w + 0x00, 4, 7)          # epoch
    put(w + 0x04, 4, 11)         # visit
    raw[w + 0x08:w + 0x18] = b"T3FR" + struct.pack("<III", 7, 11, (~11) & 0xFFFFFFFF)
    put(w + 0x18, 2, 2)          # stable even publication revision
    put(w + 0x1A, 2, 3)          # accepted and native save consent
    put(w + 0x1C, 4, 3)          # PRE_SAVE_OK + COMMIT_ENTERED, no POST_SAVE_OK
    put(w + 0x20, 2, 12)         # PREPARE sequence
    put(w + 0x22, 2, 13)         # SCENE sequence
    put(w + 0x2B, 1, 1)          # native pre-save status OK
    put(w + 0x40, 4, 0x11223344)
    put(w + 0x44, 4, 0x55667788)
    return raw, put


def _probe(raw, *, old_key=OLD_KEY, before=4, after=5):
    lua = LuaRuntime(unpack_returned_tuples=True)
    witness = lua.execute((ROOT / "lua/tests/duo/gen3_rr_reset_witness.lua").read_text(encoding="utf-8"))

    def read(addr, width):
        off = int(addr) - TRADE_BASE
        return int.from_bytes(raw[off:off + width], "little")

    io = lua.table(u8=lambda addr: read(addr, 1),
                   u16=lambda addr: read(addr, 2),
                   u32=lambda addr: read(addr, 4))
    return witness.sample(io, TRADE_BASE, old_key, before, after)


def _success(raw, *, new_key="AABBCCDD:00112233", before=4, after=6):
    lua = LuaRuntime(unpack_returned_tuples=True)
    witness = lua.execute((ROOT / "lua/tests/duo/gen3_rr_reset_witness.lua").read_text(encoding="utf-8"))

    def read(addr, width):
        off = int(addr) - TRADE_BASE
        return int.from_bytes(raw[off:off + width], "little")

    io = lua.table(u8=lambda addr: read(addr, 1),
                   u16=lambda addr: read(addr, 2),
                   u32=lambda addr: read(addr, 4))
    return witness.success(io, TRADE_BASE, OLD_KEY, new_key, before, after)


def _successful_memory():
    raw, put = _memory()
    put(0x48, 4, 4)                   # producer DONE
    put(WITNESS + 0x1C, 4, 31)        # all five native milestones
    for i, seq in enumerate((12, 13, 13, 13, 14)):
        put(WITNESS + 0x20 + 2 * i, 2, seq)
    put(WITNESS + 0x2A, 1, 1)         # committed
    put(WITNESS + 0x48, 4, 0xAABBCCDD)
    put(WITNESS + 0x4C, 4, 0x00112233)
    return raw, put


def test_native_success_control_requires_post_save_and_received_identity():
    raw, _ = _successful_memory()
    report, why = _success(raw)
    assert why is None
    assert report["bits"] == 31 and report["counter_before"] == 4
    assert report["counter_after"] == 6 and report["new_key"] == "AABBCCDD:00112233"


@pytest.mark.parametrize("offset,width,value", [
    (0x48, 4, 3),                   # still in SCENE
    (WITNESS + 0x1C, 4, 15),       # final milestone missing
    (WITNESS + 0x24, 2, 0),        # scene milestone sequence missing
    (WITNESS + 0x2A, 1, 0),        # no committed final result
    (WITNESS + 0x2B, 1, 0),        # post-save status not OK
    (WITNESS + 0x48, 4, 0),        # received PID does not match partner
])
def test_native_success_control_refuses_missing_post_save_or_wrong_mon(offset, width, value):
    raw, put = _successful_memory()
    put(offset, width, value)
    report, why = _success(raw)
    assert report is None and why


def test_reset_gate_accepts_only_the_commit_before_post_save_window():
    raw, _ = _memory()
    report, why = _probe(raw)
    assert why is None
    assert {k: report[k] for k in ("bits", "epoch", "visit", "revision", "pre_seq", "scene_seq",
                                   "counter_before", "counter_after", "old_key")} == {
        "bits": 3, "epoch": 7, "visit": 11, "revision": 2, "pre_seq": 12,
        "scene_seq": 13, "counter_before": 4, "counter_after": 5, "old_key": OLD_KEY}


@pytest.mark.parametrize("offset,width,value", [
    (0x00, 4, 0),                  # shadow signature missing
    (0x44, 4, 8),                  # mailbox/witness epoch disagreement
    (WITNESS + 0x18, 2, 3),        # torn publication
    (WITNESS + 0x1A, 2, 1),        # consent absent
    (WITNESS + 0x1C, 4, 1),        # no COMMIT_ENTERED
    (WITNESS + 0x1C, 4, 7),        # scene already ended
    (WITNESS + 0x1C, 4, 11),       # POST_SAVE_OK already set
    (WITNESS + 0x20, 2, 0),        # no PREPARE sequence
    (WITNESS + 0x22, 2, 0),        # no SCENE sequence
    (WITNESS + 0x2A, 1, 1),        # final result already published
    (WITNESS + 0x2B, 1, 0),        # pre-save not OK
    (WITNESS + 0x40, 4, 0),        # wrong outgoing PID
])
def test_reset_gate_refuses_ambiguous_or_post_saved_witness(offset, width, value):
    raw, put = _memory()
    put(offset, width, value)
    report, why = _probe(raw)
    assert report is None and why


def test_reset_gate_refuses_missing_native_pre_save_counter():
    raw, _ = _memory()
    report, why = _probe(raw, after=4)
    assert report is None and why
