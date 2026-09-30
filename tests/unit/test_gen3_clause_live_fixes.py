"""Live clause failures replayed at production-client and driver seams (MODEL)."""
import json

import pytest

from tests.unit import gen3_world as gw
from tests.unit.gen3_world import ARTIFACTS, mon_record
from tests.unit.test_gen3_client import KB, OT, A, B, live, party
from tools import e2e_duo as duo


@pytest.mark.parametrize("pack,title,kind", ARTIFACTS + [("gen3_emerald", "emerald", "clean")])
@pytest.mark.parametrize("boxed", [False, True])
def test_pc_release_is_durable_and_reports_party_or_box_key_once(monkeypatch, pack, title, kind, boxed):
    monkeypatch.setitem(gw.PACK_DIRS, "gen3_emerald", gw.REPO / "data/games/gen3_emerald")
    w = live(pack, title, kind)
    if boxed:
        w.set_party(party(A))
        w.set_box(0, 0, mon_record(B, OT, species=5))
        w.fire("pc_deposit")
        w.step(2)
    w.fire("pc_release_begin")
    w.step()
    assert w.events("release") == []  # choosing NO or cancelling removes nothing
    if boxed:
        w.set_box(0, 0, None)
    else:
        w.set_party(party(A))
    w.regs["R13"] -= 4  # ReleaseMon PUSH {LR}, completion hook before POP
    w.fire("pc_release")
    w.step(2)
    assert [e["key"] for e in w.events("release")] == [KB]
    w.fire("pc_release")
    w.step(2)
    assert len(w.events("release")) == 1
    # No response to the release reached the client. Reconnect must replay it.
    w.connected = False
    w.step(2)
    w.connected = True
    w.step(60)
    assert [e["key"] for e in w.events("release")] == [KB, KB]
    # Every line through the replay is now answered; retire the debt.
    w.replies += [json.dumps({"commands": []}) for _ in range(len(w.sent))]
    w.step(60)
    w.connected = False
    w.step(2)
    w.connected = True
    w.step(60)
    assert len(w.events("release")) == 2


@pytest.mark.parametrize("control", ["no_begin", "wrong_stack", "ambiguous", "unreadable"])
def test_pc_release_refuses_missing_or_unproven_preimage(control):
    w = live()
    if control != "no_begin":
        w.fire("pc_release_begin")
    w.set_party(party() if control == "ambiguous" else party(A))
    if control == "unreadable":
        w.poke_int(w.wc["pointers"]["gPokemonStoragePtr"]["address"], 0, 4)
    if control != "wrong_stack":
        w.regs["R13"] -= 4
    w.fire("pc_release")
    w.step(60)
    assert w.events("release") == []


def test_release_reads_the_hook_preimage_instead_of_the_old_box_cache():
    w = live(pids=(A,))
    # This mon appeared after the previous quiet/PC scan. Only the native entry
    # snapshot contains it; the subsequent purge has erased all record bytes.
    w.set_box(0, 0, mon_record(B, OT, species=5))
    w.fire("pc_release_begin")
    w.set_box(0, 0, None)
    w.regs["R13"] -= 4
    w.fire("pc_release")
    w.step(2)
    assert [e["key"] for e in w.events("release")] == [KB]


def test_native_lead_faint_is_rng_but_unwitnessed_flee_is_not():
    fail = "RESULT: FAIL (hunt ended lead fainted while catching)"
    partner = "RESULT: FAIL (runner never released B (A_PENDING))"
    assert duo.classify_gen1_result(fail) == "CAUSE_RNG"
    assert duo.classify_gen1_result(partner) == "CONSEQUENCE"
    assert duo.retryable_gen1_rng("gen3_frlg", {"a": fail, "b": partner}, 1, 8)
    assert duo.classify_gen1_result("RESULT: FAIL (hunt ended the battle ended with outcome 4 (ctrl0=0x12345679 action_cursor=2))") == "FINAL"


@pytest.mark.parametrize("game", ["gen3_frlg", "gen3_lgfr", "gen3_emerald", "gen3_rr"])
def test_one_ball_gate_has_eight_honest_whole_run_attempts(game):
    limit = duo.scenario_attempt_limit("ball_gate_gen3", game)
    assert limit == 8
    receipts = {"a": duo.RNG_OUT_OF_BALLS, "b": None}
    assert duo.retryable_gen1_rng(game, receipts, 7, limit, scenario="ball_gate_gen3")
    assert not duo.retryable_gen1_rng(game, receipts, 8, limit, scenario="ball_gate_gen3")
    assert not duo.retryable_gen1_rng(game, receipts, 3, 8, scenario="link_gen3")
    assert not duo.retryable_gen1_rng(game, {"a": duo.RNG_OUT_OF_BALLS,
                                            "b": "RESULT: FAIL (native pickup failed)"}, 3, limit,
                                    scenario="ball_gate_gen3")
