"""E3-CLIENT: lua/gen3/client.lua reads Emerald's title facts from the pack, not FR literals.

The production Entry refuses Emerald by name until EG4 (ruling 24), so these tests build the
REAL production client over a tmp copy of lua/ + data/games/gen3_emerald whose profile says
admitted=true. Nothing else in the copy is changed unless a test doctors it on purpose.

Falsifiers (red on the FR-literal client, green here):
  * force_faint's P+H plan writes gBattleCommunication[0] = 4 (Emerald's
    STATE_WAIT_ACTION_CONFIRMED_STANDBY, battle.commit_guard.value) and safety accepts it;
  * play_sound(26) (wire = FR numbering) lands SE 32's song header (Emerald SE_FAILURE);
  * a pack without gift_areas / commit_guard.value / se_ids fails closed.
FR keeps 3 and the wire ids unchanged: tests/unit/test_gen3_client.py (P+H, explode, sfx).
"""
from __future__ import annotations

import json
import shutil

import pytest

from tests.unit import gen3_world as gw
from tests.unit.gen3_world import World, key_of, mon_record

OT = 0x0000ABCD
A, B = 0x11111111, 0x22222222
KA = key_of(A, OT)
FOE = mon_record(0x77777777, 0x1234, species=19, level=3)
PACK = "gen3_emerald"
TRACK0 = 0x03006300


def _seq(t):
    return [t[i] for i in range(1, len(t) + 1)]


@pytest.fixture
def emerald(tmp_path, monkeypatch):
    """World(gen3_emerald) factory; doctor(wc) may edit the title's write_checkpoint first."""
    shutil.copytree(gw.REPO / "lua", tmp_path / "lua")
    pack_dir = tmp_path / "data" / "games" / PACK
    shutil.copytree(gw.REPO / "data" / "games" / PACK, pack_dir)
    prof = json.loads((pack_dir / "profile.json").read_text("utf-8"))
    prof["titles"]["emerald"]["admitted"] = True          # test-only: see the module docstring
    (pack_dir / "profile.json").write_text(json.dumps(prof), "utf-8")
    monkeypatch.setattr(gw, "REPO", tmp_path)
    monkeypatch.setattr(gw, "ENTRY", (tmp_path / "lua" / "gen3" / "entry.lua").as_posix())
    monkeypatch.setitem(gw.PACK_DIRS, PACK, pack_dir)
    # The schema still maps rom_type emerald to gen3_frlg (the server foundation
    # emerald -> gen3_emerald is carried from EG1, EG2_request.md §5): only that one problem is
    # waived; every other schema check on every line still runs.
    real_validate = gw.ps.validate_event
    waived = "foundation 'gen3_emerald' but rom_type 'emerald' is 'gen3_frlg'"
    monkeypatch.setattr(gw.ps, "validate_event",
                        lambda msg: [p for p in real_validate(msg) if not p.endswith(waived)])

    def make(doctor=None):
        if doctor:
            path = pack_dir / "write_checkpoint.json"
            wc = json.loads(path.read_text("utf-8"))
            doctor(wc["emerald"])
            path.write_text(json.dumps(wc), "utf-8")
        w = World(PACK, "emerald")
        w.set_party([mon_record(p, OT, species=4 + i, nickname=f"MON{i}") for i, p in enumerate((A, B))])
        w.step_to(60)
        assert w.client.writes_enabled is True
        return w
    return make


def _battle(w):
    w.battle_ok = True
    w.enter_battle([FOE], active=(0,))
    return w


# ── 1. the committed battle state is the pack's (Emerald 4) ─────────────────────────────────

def test_emerald_perish_plan_commits_the_packs_standby_4_and_safety_accepts_it(emerald):
    w = _battle(emerald())
    comm = w.ram["BATTLE_COMM_ADDR"]
    assert w.wc["battle"]["commit_guard"]["value"] == 4
    w.command(cmd="force_faint", key=KA)
    w.step()
    writes = [(a, v) for a, v, _f in w.writes]
    assert (comm, 4) in writes and (comm, 3) not in writes
    assert {str(r.reason) for r in _seq(w.parts.writes.log)} == {"battle_commit"}
    assert any("force_faint: Perish commit battler=0 handoff=1 " in line for line in w.logs), w.logs
    (held,) = _seq(w.client.battle_pending)
    assert str(held.why) == "active faint committed"
    n = len(w.writes)
    w.step(3)                          # comm reads 4 >= STANDBY: held, nothing re-armed
    assert len(w.writes) == n


def test_emerald_without_commit_guard_value_refuses_every_battle_commit(emerald):
    w = _battle(emerald(lambda wc: wc["battle"]["commit_guard"].pop("value")))
    assert any("pack has no battle.commit_guard.value" in line for line in w.logs)
    w.command(cmd="force_faint", key=KA)
    w.step(3)
    assert w.writes == []
    (held,) = _seq(w.client.battle_pending)
    assert str(held.why) == "pack has no battle.commit_guard.value"


# ── 2. play_sound: FR wire ids through the pack's se_ids ────────────────────────────────────

def _m4a(w, title_se):
    snd = w.wc["sound"]
    player = snd["player_se1"]["address"]
    w.poke_int(player + snd["ident_off"], snd["ident_magic"], 4)
    w.poke_int(player + snd["tracks_off"], TRACK0, 4)
    hdr = w.profile["rom"]["SE_SONG_HEADERS"][str(title_se)]
    for i, b in enumerate([1, 0, 5, 0, 0, 0, 0, 0, 0x10, 0x20, 0x30, 0x08]):
        w.rom[hdr - 0x08000000 + i] = b
    return player, hdr


def test_emerald_play_sound_26_lands_se_32_the_emerald_failure_song(emerald):
    w = emerald()
    assert w.wc["sound"]["se_ids"]["26"] == 32
    player, hdr = _m4a(w, 32)
    w.command(cmd="play_sound", sound=26)
    w.step()
    assert w._read(player + 0, 4) == hdr                       # songHeader = SE 32's
    assert w._read(player + 4, 4) == 1                         # status: 1 track, published
    assert w._read(TRACK0 + 64, 4) == 0x08302010               # cmdPtr from SE 32's 12 bytes
    assert {str(r.reason) for r in _seq(w.parts.writes.log)} == {"sound"}


def test_emerald_a_title_song_id_is_not_a_wire_id(emerald):
    """31 is Emerald's SE_SUCCESS but no wire id: the map, not the header table, admits ids."""
    w = emerald()
    _m4a(w, 31)
    w.command(cmd="play_sound", sound=31)
    w.step()
    assert w.writes == []
    assert any("sound refused: pack maps no title SE for wire id 31" in line for line in w.logs)


def test_emerald_without_se_ids_refuses_every_sound(emerald):
    w = emerald(lambda wc: wc["sound"].pop("se_ids"))
    _m4a(w, 32)
    w.command(cmd="play_sound", sound=26)
    w.step()
    assert w.writes == []
    assert any("pack maps no title SE for wire id 26" in line for line in w.logs)


# ── 3. gift areas ───────────────────────────────────────────────────────────────────────────

def _failed_wild_encounter(w):
    w.set_location(0, 17)                                      # route_102 (area_map 0:17)
    w.set_balls(3)
    w.step(30)
    w.enter_battle([FOE])
    w.step(30)
    w.leave_battle(outcome=4)
    w.step()


def test_emerald_gift_areas_is_empty_so_a_route_still_dead_zones(emerald):
    w = emerald()
    assert w.wc["gift_areas"]["ids"] == []
    _failed_wild_encounter(w)
    (nc,) = w.events("no_catch")
    assert nc["area_id"] == "route_102"


def test_emerald_without_gift_areas_treats_every_area_as_a_gift_area(emerald):
    """Fail closed: no list means no dead-zone on a guess (no no_catch), logged once."""
    w = emerald(lambda wc: wc.pop("gift_areas"))
    _failed_wild_encounter(w)
    assert w.events("no_catch") == []
    assert sum("pack has no gift_areas.ids" in line for line in w.logs) == 1
