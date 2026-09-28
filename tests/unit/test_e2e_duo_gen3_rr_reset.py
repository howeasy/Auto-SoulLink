"""RR reset carrier falsifiers: interruption is a partial phase, never trade success."""

import json
import re
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
    staged = [{"area_id": "duo", "a": {"key": A}, "b": {"key": B}, "status": "alive"}]
    rekeyed = [{"area_id": "duo", "a": {"key": B}, "b": {"key": A}, "status": "alive"}]
    incidental = {"area_id": "route_1", "a": None, "b": None, "status": "dead",
                  "cause": "dead_zone"}
    assert duo.rr_reset_link_problems("commit", keys, staged, staged, staged) == []
    assert duo.rr_reset_link_problems("commit", keys, staged,
                                       staged + [incidental], staged + [incidental]) == []
    assert duo.rr_reset_link_problems("commit", keys, staged, rekeyed, rekeyed)
    assert duo.rr_reset_link_problems("commit", keys, rekeyed, rekeyed, rekeyed)
    assert duo.rr_reset_link_problems("commit", keys, staged, staged,
                                       staged + rekeyed)
    assert duo.rr_reset_link_problems("success", keys, staged, rekeyed, rekeyed) == []


def test_server_must_persist_token_bound_hello_only_uncertainty():
    pending = {"pending_trade": {"token": "t1", "phase": "uncertain",
                                 "hello_only": {"a": True}, "verdict": {"a": "await"}}}
    assert duo.rr_reset_pending_problems("commit", "t1", pending) == []
    conflict = {"pending_trade": {**pending["pending_trade"], "phase": "conflict",
                                  "verdict": {"a": "none", "b": "traded"},
                                  "problem": "split native outcome"}}
    assert duo.rr_reset_pending_problems("commit", "t1", conflict) == []
    assert duo.rr_reset_pending_problems("commit", "t1", {"pending_trade": None})
    for changed in ({"token": "other"}, {"phase": "applying"},
                    {"hello_only": {"a": False}}, {"verdict": {"a": None}}):
        row = {**pending["pending_trade"], **changed}
        assert duo.rr_reset_pending_problems("commit", "t1", {"pending_trade": row})
    assert duo.rr_reset_pending_problems("success", "t1", {"pending_trade": None}) == []
    assert duo.rr_reset_pending_problems("success", "t1", pending)
    assert duo.rr_reset_pending_problems("commit", "t1", {"pending_trade": {
        **conflict["pending_trade"], "problem": ""}})


def test_server_wire_must_respond_to_same_token_bound_after_reset_report():
    request = {"dir": "c2s", "t": 17, "conn": 2,
               "msg": {"event": "trade_done", "token": "t1", "uncertain": True,
                       "after_reset": True}}
    response = {"dir": "s2c", "t": 18, "conn": 2, "req": 17,
                "msg": {"commands": []}}
    assert duo.rr_reset_wire_problems([request, response], "t1") == []
    assert duo.rr_reset_wire_problems([request], "t1")
    assert duo.rr_reset_wire_problems([request, {**response, "req": 16}], "t1")
    assert duo.rr_reset_wire_problems([request, {**response, "conn": 3}], "t1")
    assert duo.rr_reset_wire_problems([{k: v for k, v in request.items()
                                        if k not in ("t", "conn")},
                                       {k: v for k, v in response.items()
                                        if k not in ("req", "conn")}], "t1")
    assert duo.rr_reset_wire_problems([{**request, "msg": {**request["msg"], "token": "other"}},
                                       response], "t1")


def test_b_native_done_consumption_accepts_persisted_verdict_after_early_return():
    wire = [{"dir": "c2s", "t": 600, "conn": 2,
             "msg": {"event": "trade_done", "token": "t1", "new_key": A}},
            {"dir": "s2c", "t": 601, "conn": 2, "req": 600, "msg": {"commands": []}}]
    pending = {"pending_trade": {"phase": "applying", "token": "t1",
                                 "done": {"a": False, "b": False},
                                 "new": {"a": None, "b": [A, 1324]},
                                 "verdict": {"a": None, "b": "traded"}}}
    assert duo.rr_reset_b_consumed_problems(wire, "t1", A, pending) == []
    assert duo.rr_reset_b_consumed_problems(wire[:1], "t1", A, pending)
    assert duo.rr_reset_b_consumed_problems(wire, "other", A, pending)
    assert duo.rr_reset_b_consumed_problems(wire, "t1", B, pending)
    assert duo.rr_reset_b_consumed_problems(wire, "t1", A, {"pending_trade": None})
    assert duo.rr_reset_b_consumed_problems(wire, "t1", A, {"pending_trade": {
        **pending["pending_trade"], "new": {"b": [B, 1324]}}})


def test_reset_oracle_loads_the_real_gen3_codec_before_flash_checks():
    class StopOracle(Exception):
        pass

    run = object.__new__(duo.DuoRun)

    def reached_flush():
        raise StopOracle

    run._gen3_flush_boundary = reached_flush
    with pytest.raises(StopOracle):
        run.assert_rr_trade_reset_saved({})


@pytest.mark.parametrize("settled", [False, True])
def test_success_host_releases_clean_exit_only_after_server_rekey(settled):
    run = object.__new__(duo.DuoRun)
    run.scenario = "trade_reset_success_gen3"
    run.cfg = {"reset_case": "success"}
    events = []

    def prelude(*, link_slot):
        assert link_slot == 1
        run._link_keys = {"a": A, "b": B}

    run._gen3_prelude = prelude
    run._gen3_linked_lines = lambda: {"a": [], "b": []}
    run._links_json = lambda: [{"a": {"key": A}, "b": {"key": B}}]
    run.go = lambda lines: events.append("GO")
    run._gen3_mark = lambda inst, *_args: events.append(f"NATIVE_{inst}")
    run._reconnect_document = lambda: {
        "pending_trade": None if settled else {"token": "t1"},
        "links": [{"a": {"key": B if settled else A},
                   "b": {"key": A if settled else B}}],
    }

    def wait_for_server(_desc, predicate, _timeout):
        events.append("SERVER_CHECK")
        if not predicate():
            raise TimeoutError("server has not settled")

    def release(inst, marker):
        assert marker == "RESET_EXIT"
        events.append(f"EXIT_{inst}")
        if inst == "b":
            raise StopIteration

    run.wait_for = wait_for_server
    run._append_reconnect_marker = release
    with pytest.raises(StopIteration if settled else TimeoutError):
        run.orchestrate_trade_reset_success_gen3()
    assert events == (["GO", "NATIVE_a", "NATIVE_b", "SERVER_CHECK", "EXIT_a", "EXIT_b"]
                      if settled else ["GO", "NATIVE_a", "NATIVE_b", "SERVER_CHECK"])


def test_commit_host_waits_for_b_despite_a_expected_partial_result(monkeypatch):
    run = object.__new__(duo.DuoRun)
    run.scenario = "trade_reset_commit_gen3"
    run.cfg = {"reset_case": "commit", "timeout": 1800}
    run._gen3_prelude = lambda *, link_slot: setattr(run, "_link_keys", {"a": A, "b": B})
    run._gen3_linked_lines = lambda: {"a": [], "b": []}
    run._links_json = lambda: [{"a": {"key": A}, "b": {"key": B}}]
    run.go = lambda _lines: None
    run._gen3_mark = lambda inst, *_args: True if inst == "a" else pytest.fail(
        "B marker must not use self.wait_for after A's expected FAIL")
    run.wait_for = lambda *_args: pytest.fail("expected A FAIL must not abort B/server wait")
    run._read_receipt = lambda inst: (_initial()["a"] if inst == "a" else
                                      'RESET_NATIVE_SUCCESS_NO_MANUAL_SAVE {"token":"t1"}\n')
    run._reconnect_document = lambda: {"pending_trade": {
        "phase": "applying", "token": "t1", "verdict": {"b": "traded"},
        "new": {"b": [A, 1324]}}}
    run._rr_reset_wire_rows = lambda inst: [
        {"dir": "c2s", "t": 17, "conn": 2,
         "msg": {"event": "trade_done", "token": "t1", "new_key": A}},
        {"dir": "s2c", "t": 18, "conn": 2, "req": 17}]
    waited = []

    def plain_wait(description, predicate, _timeout):
        waited.append(description)
        return predicate()

    monkeypatch.setattr(duo, "wait_for", plain_wait)

    def release(inst, marker):
        assert inst == "b" and marker == "RESET_EXIT"
        raise StopIteration

    run._append_reconnect_marker = release
    with pytest.raises(StopIteration):
        run.orchestrate_trade_reset_commit_gen3()
    assert len(waited) == 2
    assert re.search(r"native post-save|consumed B", " ".join(waited))


def test_commit_phase_wait_rejects_unexpected_a_or_b_failure(monkeypatch):
    run = object.__new__(duo.DuoRun)
    run._link_keys = {"a": A, "b": B}
    run._process_exited = lambda _inst: False
    monkeypatch.setattr(duo, "wait_for", lambda _desc, pred, _timeout: pred())
    good_a = _initial()["a"]
    for a, b in ((good_a.replace("EXPECTED_RESET_PARTIAL_COMMIT", "unexpected"), ""),
                 (good_a.replace('"bits": 3', '"bits": 31'), ""),
                 (good_a, "RESULT: FAIL (B native save failed)\n")):
        run._read_receipt = lambda inst, aa=a, bb=b: aa if inst == "a" else bb
        with pytest.raises(RuntimeError):
            run._rr_reset_wait_commit_initial("B's marker", lambda: None, 10)
