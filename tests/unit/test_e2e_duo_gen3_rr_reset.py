"""RR reset carrier falsifiers: interruption is a partial phase, never trade success."""

import json
from types import SimpleNamespace

import pytest

from tools import e2e_duo as duo

A, B = "11223344:55667788", "AABBCCDD:00112233"


def _mark(tag, **fields):
    return tag + " " + json.dumps(fields) + "\n"


def _initial():
    common = ("RX apply_prepare\n"
              "SAVE_WITNESS_DUMP path=patch/build/witness.bin bytes=131072 saves=1 frame=100 counter=5\n"
              'TX apply_ready - {"event":"apply_ready","ok":true,"token":"t1"}\n'
              "RX apply_trade\n")
    commit = {"bits": 3, "epoch": 7, "visit": 11, "revision": 2, "pre_seq": 12,
              "scene_seq": 13, "counter_before": 4, "counter_after": 5,
              "old_key": A, "token": "t1", "witness_path": "patch/build/commit_native_witness.bin",
              "side": "a", "frame": 120}
    a = (common + _mark("RESET_COMMIT_ENTERED", **commit)
         + _mark("RESET_PARTIAL_COMMIT_EXIT", **commit)
         + "RESULT: FAIL (EXPECTED_RESET_PARTIAL_COMMIT)\n")
    saved = {"bits": 31, "epoch": 7, "visit": 11, "revision": 4, "pre_seq": 12,
             "scene_seq": 13, "final_seq": 14, "counter_before": 4, "counter_after": 6,
             "old_key": B, "new_key": A, "token": "t1",
             "witness_path": "patch/build/success_native_witness.bin", "side": "b",
             "frame": 130}
    b = (common
         + "SAVE_WITNESS_DUMP path=patch/build/witness.bin bytes=131072 saves=2 frame=125 counter=6\n"
         + 'TX trade_done - {"event":"trade_done","token":"t1","new_key":"' + A + '"}\n'
         + "TRADED gave=" + B + " got=" + A + " slot=1 species=4 level=5\n"
         + _mark("RESET_NATIVE_SUCCESS_NO_MANUAL_SAVE", **saved)
         + _mark("RESET_NATIVE_SUCCESS_EXIT", **saved)
         + "RESULT: FAIL (EXPECTED_NATIVE_SUCCESS_NO_MANUAL_SAVE)\n")
    return {"a": a, "b": b}


def test_commit_initial_phase_accepts_only_a_partial_and_b_native_success():
    assert duo.rr_reset_initial_receipt_problems(_initial(), "commit", {"a": A, "b": B}) == []


def test_commit_initial_phase_rejects_forged_or_post_saved_a():
    receipts = _initial()
    a = receipts["a"]
    for changed in (
        a.replace('"bits": 3', '"bits": 31'),
        a.replace('"token": "t1"', '"token": "wrong"', 1),
        a.replace("RESET_COMMIT_ENTERED", "NO_COMMIT"),
        a + 'TX trade_done - {"token":"t1","new_key":"' + B + '"}\n',
        a + "TRADED gave=" + A + " got=" + B + "\n",
        a + "SAVE_WITNESS trade counter=5->6\n",
        a.replace("saves=1", "saves=2"),
    ):
        assert duo.rr_reset_initial_receipt_problems({**receipts, "a": changed},
                                                     "commit", {"a": A, "b": B})


def test_commit_initial_phase_rejects_missing_b_native_post_save():
    receipts = _initial()
    b = receipts["b"].replace(
        "SAVE_WITNESS_DUMP path=patch/build/witness.bin bytes=131072 saves=2 frame=125 counter=6\n", "")
    assert duo.rr_reset_initial_receipt_problems({**receipts, "b": b},
                                                 "commit", {"a": A, "b": B})


def test_reset_cleanup_refuses_forced_emulator_termination(monkeypatch):
    run = object.__new__(duo.DuoRun)
    run.cfg = {"rr_reset_trade": True}
    run.emus = [SimpleNamespace(pid=4242, poll=lambda: None)]

    def forbidden(*_args, **_kwargs):
        raise AssertionError("taskkill must not run for RR reset")

    monkeypatch.setattr(duo.subprocess, "run", forbidden)
    with pytest.raises(RuntimeError, match="clean exit"):
        run.cleanup(False)


def test_commit_server_link_must_match_pretrade_baseline_even_before_reload():
    keys = {"a": A, "b": B}
    staged = [{"a": {"key": A}, "b": {"key": B}, "status": "alive"}]
    rekeyed = [{"a": {"key": B}, "b": {"key": A}, "status": "alive"}]
    assert duo.rr_reset_link_problems("commit", keys, staged, staged, staged) == []
    assert duo.rr_reset_link_problems("commit", keys, staged, rekeyed, rekeyed)
    assert duo.rr_reset_link_problems("commit", keys, rekeyed, rekeyed, rekeyed)
    assert duo.rr_reset_link_problems("success", keys, staged, rekeyed, rekeyed) == []
