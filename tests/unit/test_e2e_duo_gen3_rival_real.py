"""rival_swap_real_gen3 (card G5-RR-RIVAL): the qualifying RR Rival Team Swap oracle."""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(REPO, "tools"), REPO]
import e2e_duo as duo  # noqa: E402

from server.adapters import gen3_codec as codec  # noqa: E402

FIX = os.path.join(REPO, "tests", "fixtures", "gen3")
with open(os.path.join(REPO, "data", "games", "gen3_rr", "profile.json"), encoding="utf-8") as _h:
    NATIVE_LO = json.load(_h)["native"]["BASE"]          # 0x0203F800, the live receipt's arena
NATIVE_HI = NATIVE_LO + 0x800
RIVAL = 331


def _records(name):
    with open(os.path.join(FIX, name), "rb") as handle:
        body = codec.split_rtc(handle.read())[0]
    sb1 = codec.parse_flash(body, cfru=True)["sb1"]
    n = sb1[codec.SB1_PARTY_COUNT_OFFSET]
    at = codec.SB1_PARTY_OFFSET
    return [sb1[at + i * 100:at + (i + 1) * 100] for i in range(n)]


def _receipt(blobs, enemy=None, reply=None, writes=None, tbs_id=RIVAL, cmd_id=RIVAL, opp=RIVAL,
             mon1=None, pre="map=3.41 at=(34,6) var4054=1"):
    enemy = blobs if enemy is None else enemy
    species = [codec.decode_party_mon(b, rr=True)["species"] for b in blobs]
    reply = {"event": "rival_team_replaced", "trainer_id": RIVAL, "species_ids": species} \
        if reply is None else reply
    first = codec.decode_party_mon(enemy[0], rr=True)
    mon1 = f"species={first['species']} pid={first['personality']:08X}" if mon1 is None else mon1
    writes = [f"[client] [SLink-gen3] write native 0x{NATIVE_LO + 0x400:08X} +200 frame 10",
              f"[client] [SLink-gen3] write native 0x{NATIVE_LO:08X} +2 frame 10"] \
        if writes is None else writes
    tbs = json.dumps({"event": "trainer_battle_start", "trainer_id": tbs_id, "battle_id": 1,
                      "session": "s1"})
    lines = [f"RIVAL_PRE {pre}", f"TX trainer_battle_start - {tbs}",
             f"RIVAL_CMD trainer_id={cmd_id} n={len(blobs)} session=s1 battle_id=1 source=auto frame=9",
             *[f"RIVAL_BLOB {i} {b.hex()}" for i, b in enumerate(blobs)],   # server: lower case
             "RX replace_rival_team", *writes,
             f"TX rival_team_replaced - {json.dumps(reply)}",
             f"ENEMY_COUNT {len(enemy)}",
             *[f"ENEMY_SLOT {i} {b.hex().upper()}" for i, b in enumerate(enemy)],
             f"BATTLE_MON1 {mon1}", f"TRAINER_OPPONENT_A {opp}"]
    return "\n".join(lines) + "\n"


@pytest.fixture
def source():
    return _records("rr_battle2_b.sav")


def _check(text, source):
    party = [codec.decode_party_mon(b, rr=True) for b in source]
    return duo.rival_swap_real_problems(text, party, {326, 331}, NATIVE_LO, NATIVE_HI)


def test_a_real_swap_of_bs_party_passes(source):
    problems, fact = _check(_receipt(source), source)
    assert problems == [], problems
    assert "331" in fact and "2" in fact


def test_the_ack_error_fails(source):
    text = _receipt(source, reply={"event": "rival_team_replaced", "trainer_id": RIVAL,
                                   "species_ids": [], "error": "refresh_failed",
                                   "reason": "window_closed"})
    problems, _ = _check(text, source)
    assert any("refresh_failed" in p for p in problems), problems


def test_an_enemy_party_that_is_not_the_staged_team_fails(source):
    own = _records("rr_battle2.sav")[::-1]   # other keys/order: not B's team
    problems, _ = _check(_receipt(source, enemy=own), source)
    assert any("ENEMY_SLOT 0" in p for p in problems), problems
    problems, _ = _check(_receipt(source, enemy=source[:1]), source)
    assert any("ENEMY_COUNT" in p for p in problems), problems


def test_the_command_must_carry_bs_party(source):
    other = _records("rr_battle2.sav")
    problems, _ = _check(_receipt(other), source)
    assert any("B's party" in p for p in problems), problems


def test_trainer_ids_must_agree_and_be_a_rival(source):
    for kw in ({"tbs_id": 325, "cmd_id": 325, "opp": 325}, {"cmd_id": 326}, {"opp": 326}):
        problems, _ = _check(_receipt(source, **kw), source)
        assert problems, kw


def test_a_client_write_outside_the_mailbox_fails(source):
    stray = f"[client] [SLink-gen3] write native 0x{0x0202402C:08X} +100 frame 11"
    problems, _ = _check(_receipt(source, writes=[stray]), source)
    assert any("outside" in p for p in problems), problems
    other = f"[client] [SLink-gen3] write battle_faint 0x{NATIVE_LO:08X} +2 frame 11"
    problems, _ = _check(_receipt(source, writes=[other]), source)
    assert any("outside" in p for p in problems), problems


def test_the_fight_must_use_the_swapped_lead(source):
    problems, _ = _check(_receipt(source, mon1="species=1 pid=00000000"), source)
    assert any("BATTLE_MON1" in p for p in problems), problems


def test_the_precondition_is_the_fixture(source):
    problems, _ = _check(_receipt(source, pre="map=3.19 at=(12,37) var4054=1"), source)
    assert any("RIVAL_PRE" in p for p in problems), problems


def test_the_row_is_registered_rr_only_as_a_qualification():
    entry = duo.SCENARIOS["rival_swap_real_gen3"]
    assert entry["games"] == ("gen3_rr",) and "control" not in entry
    assert "--rival-team-swap" in entry["flags"]
    assert entry["target"] == {"a": "rival", "b": "battle2"}
    assert os.path.isfile(os.path.join(FIX, "rr_rival.sav"))
