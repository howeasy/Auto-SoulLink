"""EMERALD-RIVAL: native read -> hello/tick -> each player's trainer panel."""
import json
import os
import re
from pathlib import Path

import pytest

from server.adapters.gen3_frlge import Gen3Adapter
from server.server import SLinkServer
from tests.unit import gen3_world as gw
from tests.unit.gen3_world import SB2_ADDR, World, mon_record
from tests.unit.protocol_schema import validate_event


def _panel_server(rom_type="emerald"):
    server = SLinkServer.__new__(SLinkServer)
    server.adapter = Gen3Adapter(rom_type=rom_type, is_rr=rom_type == "firered_rr")
    server._player_adapters = {}
    server.player_gender = {"a": 0, "b": 1}
    return server


@pytest.mark.parametrize("area", ["route_103", "route_110"])
def test_emerald_panel_shows_each_players_opposite_gender_rival(area):
    server = _panel_server()
    a = server._trainer_panel_html(area, "a")
    b = server._trainer_panel_html(area, "b")
    assert "May" in a and "Brendan" not in a
    assert "Brendan" in b and "May" not in b
    assert a.count('class="tr-variant-count">3 variants') == b.count('class="tr-variant-count">3 variants') == 1


@pytest.mark.parametrize("gender", [0, 1])
def test_emerald_hello_and_tick_report_native_player_gender(gender, monkeypatch):
    monkeypatch.setitem(gw.PACK_DIRS, "gen3_emerald", gw.REPO / "data/games/gen3_emerald")
    world = World("gen3_emerald", "emerald")
    world.set_party([mon_record(0x11111111, 0x0000ABCD)])
    # pokeemerald c65e93f2 include/global.h:510-513: playerGender at +0x08.
    world.poke_int(SB2_ADDR + 0x08, gender, 1)
    world.step_to(60)
    hello, = world.events("hello")
    assert hello.get("player_gender") == gender
    assert world.events("tick")[-1].get("player_gender") == gender


@pytest.mark.parametrize("gender", [None, False, True, -1, 2, 255, "0", "1", 0.0, [], {}])
def test_missing_or_invalid_gender_keeps_both_emerald_rivals(gender):
    server = _panel_server()
    server.player_gender["a"] = gender
    html = server._trainer_panel_html("route_103", "a")
    assert "May" in html and "Brendan" in html


@pytest.mark.parametrize("rom_type,area", [("firered", "oaks_lab"), ("leafgreen", "oaks_lab"),
                                          ("firered_rr", "pewter_city")])
def test_gender_does_not_change_frlg_or_rr_panels(rom_type, area):
    server = _panel_server(rom_type)
    server.player_gender = {}
    baseline = server._trainer_panel_html(area, "a")
    assert baseline
    for gender in (0, 1):
        server.player_gender["a"] = gender
        assert server._trainer_panel_html(area, "a") == baseline
    for tid in server.adapter.trainers_for_area(area):
        assert "required_player_gender" not in server.adapter.trainer_brief(tid)


@pytest.mark.parametrize("pack,title", [("gen3_frlg", "firered"), ("gen3_frlg", "leafgreen"),
                                       ("gen3_rr", "radical_red")])
def test_other_packs_do_not_publish_an_unproven_gender(pack, title):
    world = World(pack, title)
    world.set_party([mon_record(0x11111111, 0x0000ABCD)])
    world.poke_int(SB2_ADDR + 0x08, 1, 1)
    world.step_to(60)
    assert "SB2_PLAYER_GENDER_OFFSET" not in world.d
    assert all("player_gender" not in event for event in world.events("hello") + world.events("tick"))


def _emerald_world(monkeypatch):
    monkeypatch.setitem(gw.PACK_DIRS, "gen3_emerald", gw.REPO / "data/games/gen3_emerald")
    world = World("gen3_emerald", "emerald")
    world.set_party([mon_record(0x11111111, 0x0000ABCD)])
    return world


def test_gender_reader_follows_the_profile_and_unreadable_reads_are_absent(monkeypatch):
    world = _emerald_world(monkeypatch)
    # A moved profile field defeats a hardcoded +8 read.
    world.parts.profile.derived.SB2_PLAYER_GENDER_OFFSET = 0x30
    world.poke_int(SB2_ADDR + 0x08, 0, 1)
    world.poke_int(SB2_ADDR + 0x30, 1, 1)
    assert world.client.driver.hello_fields()["player_gender"] == 1
    assert world.client.driver.tick_fields()["player_gender"] == 1
    world.poke_int(SB2_ADDR + 0x30, 255, 1)
    assert world.client.driver.hello_fields()["player_gender"] is None
    world.poke_int(world.ram["SB2_PTR_ADDR"], 0, 4)
    assert world.client.driver.tick_fields()["player_gender"] is None


def test_hello_tick_reconnect_and_identity_refusal_keep_gender_per_player(tmp_path, monkeypatch):
    world = _emerald_world(monkeypatch)
    world.poke_int(SB2_ADDR + 0x08, 0, 1)
    world.step_to(60)
    hello, = world.events("hello")
    # the harness builds the clean artifact; the server refuses a clean Emerald (patch-first, 2026-10-02)
    hello = dict(hello, artifact_kind="companion")
    server = SLinkServer(data_dir=str(tmp_path))
    server._dispatch("a", dict(hello))
    server._dispatch("b", dict(hello, player="b", player_gender=1))
    assert server.player_gender == {"a": 0, "b": 1}
    assert "Brendan" not in server._trainer_panel_html("route_103", "a")
    assert "May" not in server._trainer_panel_html("route_103", "b")
    server._dispatch("a", {"event": "tick", "player_gender": 1})
    assert server.player_gender == {"a": 1, "b": 1}
    server._dispatch("a", {"event": "tick"})
    assert server.player_gender == {"a": None, "b": 1}
    server._dispatch("a", dict(hello))
    bad = dict(hello, ot_id=0xFFFFFFFF, player_gender=1)
    server._dispatch("a", bad)
    assert bad.get("_rejected") and server.player_gender["a"] == 0
    server._dispatch("a", {"event": "tick", "player_gender": 1})
    assert server.player_gender["a"] == 0  # rejected identity cannot change the hint
    legacy = {k: v for k, v in hello.items() if k != "player_gender"}
    server._dispatch("a", legacy)
    assert server.player_gender == {"a": None, "b": 1}


def test_rival_selection_uses_script_identity_even_if_names_change(monkeypatch):
    server = _panel_server()
    # The ROM ingest path keeps pret consts and may replace trainer/class names.
    import copy
    table = copy.deepcopy(server.adapter._frlg_trainer_table())
    for tid in table["trainers_by_area"]["route_103"]:
        row = table["trainers"][tid]
        row["name"] = "Chosen" if row["const"].startswith("TRAINER_MAY_") else "Excluded"
    server.adapter._rom_trainers = table
    html = server._trainer_panel_html("route_103", "a")
    assert "Chosen" in html and "Excluded" not in html
    assert all("required_player_gender" not in row for row in table["trainers"].values())


def test_emerald_gender_binding_is_generated_from_the_title_sources():
    root = Path(__file__).resolve().parents[2]
    pret = Path(os.environ.get("SLINK_PRET_EMERALD_SRC", root / ".cache/pret/pokeemerald"))
    if not (pret / "include/global.h").is_file():
        pytest.skip("pinned pokeemerald source unavailable")
    profile = json.loads((root / "data/games/gen3_emerald/profile.json").read_text())["titles"]["emerald"]
    header = (pret / "include/global.h").read_text()
    offset = int(re.search(r"/\*0x([0-9A-Fa-f]+)\*/\s+u8 playerGender;", header)[1], 16)
    assert profile["derived"]["SB2_PLAYER_GENDER_OFFSET"] == offset == 8
    symbol = next(line for line in (root / "data/gen3/pret/pokeemerald.sym").read_text().splitlines()
                  if line.endswith(" gSaveBlock2Ptr"))
    assert profile["ram"]["SB2_PTR_ADDR"] == int(symbol.split()[0], 16) == 0x03005D90
    assert "playerGender" in profile["_src"]["derived.SB2_PLAYER_GENDER_OFFSET"]
    constants = (pret / "include/constants/global.h").read_text()
    assert re.search(r"#define MALE 0\b", constants) and re.search(r"#define FEMALE 1\b", constants)
    for area in ("Route103", "Route110"):
        script = (pret / f"data/maps/{area}/scripts.inc").read_text()
        assert re.search(r"goto_if_eq VAR_RESULT, MALE, \w*May\w*", script)
        assert re.search(r"goto_if_eq VAR_RESULT, FEMALE, \w*Brendan\w*", script)


@pytest.mark.parametrize("gender", [0, 1, None, False, 2, "0"])
def test_protocol_gender_is_optional_and_known_values_are_zero_or_one(gender):
    message = {"event": "tick", "player": "a", "seq": 1}
    assert validate_event(message, strict=True) == []
    message["player_gender"] = gender
    # Like existing optional scalar fields, null is treated as not reported.
    valid = gender is None or (type(gender) is int and gender in (0, 1))
    assert bool(validate_event(message, strict=True)) is not valid
