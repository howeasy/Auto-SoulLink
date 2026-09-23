"""lua/core/deferred.lua (P4 C4-1): the deferred command FIFO lifted from
lua/gen1/client.lua:717-822, driven under lupa with injected executors.

Covers: one command per frame behind the gate, arm/disarm around every executor call, the keyed
replies (shapes checked against tests/unit/protocol_schema.py), the tail retries on exactly
"party full" (budgeted) and "last party mon", the game_over drop, and the one deliberate delta
from Gen 1: stats_cache is snapshotted before the deposit and SENT only after it is confirmed
(docs/gen3/PLAN.md:57).
"""
from __future__ import annotations

import json
import pathlib

import pytest

from tests.unit import protocol_schema as ps

lupa = pytest.importorskip("lupa")

REPO = pathlib.Path(__file__).resolve().parents[2]
DEFERRED = (REPO / "lua" / "core" / "deferred.lua").as_posix()
IDENTITY = (REPO / "lua" / "core" / "identity.lua").as_posix()
JSON = (REPO / "lua" / "json_codec.lua").as_posix()

A, B, C = "0000000A:12345678", "0000000B:12345678", "0000000C:12345678"
NEW = "000000FF:12345678"
MEMORIAL = 13


class Queue:
    """The FIFO over a scripted executor. `timeline` interleaves exec calls and sends."""

    def __init__(self, stats_of=False):
        self.lua = L = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.timeline: list[tuple] = []
        self.logs: list[str] = []
        self.hud: list[str] = []
        self.party = [{"key": A, "slot": 0, "level": 12, "max_hp": 40, "nick": [1], "moves": [1]},
                      {"key": B, "slot": 1, "level": 9, "max_hp": 31, "nick": [2], "moves": [2]}]
        self.results: dict[str, list] = {"deposit": [], "withdraw": [], "memorialize": []}
        self.explode: set[str] = set()
        self.gate = (True, None)
        json_mod = L.eval(f'dofile("{JSON}")')
        send = L.eval("function(json, sink) return function(e, f) f = f or {}; f.event = e; "
                      "sink(json.encode(f)); return true end end")(json_mod, self._sink)
        Identity = L.eval(f'dofile("{IDENTITY}")')
        self.identity = Identity.new(L.table(key=L.eval("function(m) return m.key end")))
        exec_ = L.table(
            arm=lambda: self.timeline.append(("arm",)),
            disarm=lambda: self.timeline.append(("disarm",)),
            faint_slot=lambda s, c: self._exec("faint_slot", s),
            deposit=lambda k, h: self._exec("deposit", str(k), h),
            withdraw=lambda k, st, n: self._exec("withdraw", str(k)),
            memorialize=lambda k, h: self._exec("memorialize", str(k), h),
            rescan=lambda: self.timeline.append(("rescan",)),
        )
        if stats_of:
            exec_.stats_of = lambda m: L.table(level=m.level, maxHP=m.max_hp, attack=7)
        Deferred = L.eval(f'dofile("{DEFERRED}")')
        self.q = Deferred.new(L.table(
            send=send, log=lambda t: self.logs.append(str(t)),
            hud=L.table(show=lambda t, *a: self.hud.append(str(t))),
            identity=self.identity, read_party=self._read_party, memorial_box=MEMORIAL, exec=exec_))

    # -- fakes --------------------------------------------------------------------------
    def _sink(self, line):
        self.timeline.append(("send", json.loads(str(line))))

    def _read_party(self):
        L = self.lua
        return L.table_from([L.table_from({"key": m["key"], "slot": m["slot"], "level": m["level"],
                                           "max_hp": m["max_hp"], "nickname": "N",
                                           "nickname_bytes": L.table_from(m["nick"]),
                                           "moves": L.table_from(m["moves"])}) for m in self.party])

    def _exec(self, name, *args):
        self.timeline.append((name,) + args)
        if name in self.explode:
            raise RuntimeError(f"{name} blew up")
        if name == "faint_slot":
            return None
        script = self.results[name]
        ok, reason = script.pop(0) if script else (True, None)
        if ok and name in ("deposit", "memorialize"):
            key = args[0]
            for m in self.party:
                if m["key"] == key:
                    m["level"] = 0  # party-only fields zeroed by the move
            self.party = [m for m in self.party if m["key"] != key]
        return (True, None) if ok else (None, reason)

    # -- driving ------------------------------------------------------------------------
    def push(self, **cmd):
        self.q.push(self.q, self.lua.table_from(cmd))

    def run(self, frame=1, game_over=False):
        return self.q.run(self.q, lambda: self.gate, frame, game_over)

    def drain(self, frames=20, game_over=False):
        for f in range(frames):
            self.run(f + 1, game_over)

    def size(self):
        return self.q.size(self.q)

    def sends(self, event=None):
        return [e for kind, *rest in self.timeline if kind == "send"
                for e in rest if event is None or e["event"] == event]

    def calls(self, name):
        return [t for t in self.timeline if t[0] == name]


def valid(fields):
    msg = dict(fields, player="a", seq=1)
    assert ps.validate_event(msg) == [], (msg, ps.validate_event(msg))
    return fields


def test_one_command_per_frame():
    q = Queue()
    q.push(cmd="force_faint", key=A)
    q.push(cmd="force_faint", key=B)
    q.run()
    assert q.calls("faint_slot") == [("faint_slot", 0)] and q.size() == 1
    q.run(2)
    assert q.calls("faint_slot") == [("faint_slot", 0), ("faint_slot", 1)] and q.size() == 0


def test_a_closed_gate_runs_nothing_keeps_the_queue_and_reports_the_hold():
    q = Queue()
    q.gate = (False, "not at the overworld checkpoint")
    q.push(cmd="box_mon", key=A)
    q.run(100)
    q.run(160)
    assert q.timeline == [] and q.size() == 1
    n, why, age, head = q.q.pending(q.q, 160)
    assert (n, why, age, head) == (1, "not at the overworld checkpoint", 60, "box_mon")
    q.gate = (True, None)
    q.run(161)
    assert q.size() == 0 and q.q.pending(q.q, 161)[0] == 0


def test_the_gate_is_not_consulted_on_an_empty_queue():
    q = Queue()
    q.gate = None  # would raise if called and unpacked
    assert not q.q.run(q.q, lambda: (_ for _ in ()).throw(AssertionError("gate called")), 1, False)


def test_every_executor_call_is_bracketed_by_arm_and_disarm():
    q = Queue()
    q.push(cmd="memorialize", key=A)
    q.run()
    names = [t[0] for t in q.timeline if t[0] != "send"]
    assert names[0] == "arm" and "disarm" in names[names.index("memorialize"):]


def test_an_executor_that_throws_is_logged_disarmed_and_does_not_stop_the_queue():
    q = Queue()
    q.explode = {"deposit"}
    q.push(cmd="box_mon", key=A)
    q.push(cmd="force_faint", key=B)
    q.run()
    assert q.timeline[-1] == ("disarm",)
    assert any("box_mon" in line and "blew up" in line for line in q.logs)
    q.run(2)
    assert q.calls("faint_slot") == [("faint_slot", 1)]


def test_force_faint_for_a_key_that_left_the_party_writes_nothing_and_says_so():
    q = Queue()
    q.push(cmd="force_faint", key=C)
    q.run()
    assert q.calls("faint_slot") == [] and q.sends() == []
    assert any("key not in party" in line for line in q.logs)


def test_stats_cache_is_snapshotted_before_the_deposit_and_sent_after_it_is_confirmed():
    q = Queue()
    q.push(cmd="box_mon", key=A)
    q.run()
    order = [t[0] if t[0] != "send" else t[1]["event"] for t in q.timeline]
    assert order.index("deposit") < order.index("stats_cache")
    (cache,) = q.sends("stats_cache")
    valid(cache)
    assert cache["key"] == A and cache["stats"] == {"level": 12, "maxHP": 40}  # pre-deposit values
    assert q.sends("box_mon_failed") == []


def test_stats_cache_uses_the_injected_stats_of():
    q = Queue(stats_of=True)
    q.push(cmd="box_mon", key=A)
    q.run()
    assert q.sends("stats_cache")[0]["stats"] == {"level": 12, "maxHP": 40, "attack": 7}


def test_a_refused_deposit_sends_box_mon_failed_and_no_stats_cache():
    q = Queue()
    q.results["deposit"] = [(False, "last party mon")]
    q.push(cmd="box_mon", key=A)
    q.run()
    (fail,) = q.sends("box_mon_failed")
    assert valid(fail) == {"event": "box_mon_failed", "key": A, "reason": "last party mon"}
    assert q.sends("stats_cache") == [] and q.size() == 0


def test_a_deposit_of_a_key_already_boxed_acks_silently():
    q = Queue()
    q.push(cmd="box_mon", key=C)  # not in party; executor says it is boxed already
    q.run()
    assert q.sends() == [] and q.calls("deposit") == [("deposit", C, None)]


def test_party_mon_replies_done_or_failed_by_key():
    q = Queue()
    q.results["withdraw"] = [(True, None), (False, "key not boxed")]
    q.push(cmd="party_mon", key=C)
    q.push(cmd="party_mon", key=NEW)
    q.drain(2)
    (done,) = q.sends("sync_retrieve_done")
    (fail,) = q.sends("sync_retrieve_failed")
    assert valid(done) == {"event": "sync_retrieve_done", "key": C}
    assert valid(fail) == {"event": "sync_retrieve_failed", "key": NEW, "reason": "key not boxed"}


def test_party_full_waits_at_the_tail_behind_the_memorial_that_frees_a_slot():
    q = Queue()
    q.results["withdraw"] = [(False, "party full"), (True, None)]
    q.push(cmd="party_mon", key=C)
    q.push(cmd="memorialize", key=B)
    q.drain(3)
    assert [e["event"] for e in q.sends()] == ["memorialize_done", "sync_retrieve_done"]


def test_party_full_retries_are_bounded_by_the_queue_length_at_the_first_refusal():
    q = Queue()
    q.results["withdraw"] = [(False, "party full")] * 10
    q.results["memorialize"] = [(False, "no memorial box")] * 2
    q.push(cmd="party_mon", key=C)
    q.push(cmd="memorialize", key=A)
    q.push(cmd="memorialize", key=B)
    q.drain(20)
    assert len(q.calls("withdraw")) == 4  # first try + budget of 3 (two behind it + 1)
    (fail,) = q.sends("sync_retrieve_failed")
    assert fail["reason"] == "party full" and q.size() == 0


def test_other_withdraw_reasons_are_final_not_retried():
    q = Queue()
    q.results["withdraw"] = [(False, "party full-ish")]
    q.push(cmd="party_mon", key=C)
    q.push(cmd="force_faint", key=A)
    q.drain(3)
    assert len(q.calls("withdraw")) == 1 and len(q.sends("sync_retrieve_failed")) == 1


def test_memorialize_done_names_the_memorial_box():
    q = Queue()
    q.push(cmd="memorialize", key=A)
    q.run()
    (done,) = q.sends("memorialize_done")
    assert valid(done) == {"event": "memorialize_done", "key": A, "box": MEMORIAL}


def test_memorialize_other_failure_sends_memorialize_failed():
    q = Queue()
    q.results["memorialize"] = [(False, "memorial box full")]
    q.push(cmd="memorialize", key=A)
    q.run()
    (fail,) = q.sends("memorialize_failed")
    assert valid(fail) == {"event": "memorialize_failed", "key": A, "reason": "memorial box full"}


def test_last_party_mon_memorial_goes_to_the_tail_not_the_head():
    q = Queue()
    q.results["memorialize"] = [(False, "last party mon"), (True, None)]
    q.push(cmd="memorialize", key=A)
    q.push(cmd="party_mon", key=C)
    q.drain(2)
    assert [t[0] for t in q.timeline if t[0] in ("memorialize", "withdraw")] == ["memorialize", "withdraw"]
    q.run(3)
    assert [e["event"] for e in q.sends()] == ["sync_retrieve_done", "memorialize_done"]


def test_last_party_mon_memorial_after_game_over_is_dropped_silently():
    q = Queue()
    q.results["memorialize"] = [(False, "last party mon")]
    q.push(cmd="memorialize", key=A)
    q.run(1, game_over=True)
    assert q.size() == 0 and q.sends() == []
    assert any("game over" in line for line in q.logs)


def _retire(q, twins):
    L = q.lua
    before = L.table_from([L.table_from({"key": NEW, "slot": 0, "nickname_bytes": L.table_from([7]),
                                         "moves": L.table_from([7])})])
    q.identity.begin_alias(q.identity, A, NEW, before[1], before)
    q.identity.reject(q.identity, A, before)
    q.party = [{"key": NEW, "slot": s, "level": 5, "max_hp": 20, "nick": [7], "moves": [7]} for s in twins]


def test_a_retired_alias_deposit_moves_the_physical_key_at_the_validated_slot():
    q = Queue()
    _retire(q, [3])
    q.push(cmd="box_mon", key=A)
    q.run()
    assert q.calls("deposit") == [("deposit", NEW, 3)]
    assert q.sends("stats_cache")[0]["key"] == A  # replies keep the key the server tracks


def test_an_ambiguous_retired_alias_is_refused_with_a_keyed_failure_and_no_executor_call():
    q = Queue()
    _retire(q, [0, 4])
    q.push(cmd="memorialize", key=A)
    q.push(cmd="box_mon", key=A)
    q.drain(2)
    assert q.calls("memorialize") == [] and q.calls("deposit") == []
    fails = q.sends("memorialize_failed") + q.sends("box_mon_failed")
    assert len(fails) == 2 and all("ambiguous" in f["reason"] for f in fails)


def test_the_executor_is_told_which_force_command_it_runs():
    q = Queue()
    seen = []
    q.q.exec.faint_slot = lambda s, c: seen.append((s, str(c)))
    q.push(cmd="force_explode", key=B)
    q.run()
    assert seen == [(1, "force_explode")]


def test_a_memorial_that_lands_forgets_the_retired_alias():
    q = Queue()
    _retire(q, [2])
    q.push(cmd="memorialize", key=A)
    q.run()
    assert q.calls("memorialize") == [("memorialize", NEW, 2)]
    assert q.identity.retired(q.identity, A) is None
