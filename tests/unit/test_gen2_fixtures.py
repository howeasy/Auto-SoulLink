"""MODEL controls for the Gen 2 fixture tooling and scripted route.

Synthetic CartRAM buffers live only in tmp_path; they are never played saves, and nothing here
launches an emulator. The routes stay UNRUN: passing these controls is no PHYSICAL evidence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from lupa import LuaRuntime

from server.adapters import gen2_codec as codec
from server.adapters.gen2_rom_scan import Rom
from tools import fixture_qualification as qualification, gen2_fixtures as g
from tools.gen2_source_data import load_context

ROOT = Path(__file__).resolve().parents[2]
TITLES = ("crystal", "gold", "silver")
_FACTS, _CTX = {}, {}
STARTS = {"player": "wPlayerData", "player1": "wPlayerData1", "player2": "wPlayerData2",
          "player3": "wPlayerData3", "map": "wCurMapData", "pokemon": "wPokemonData"}
TRAILER = bytes(range(22))
ROUTE_FACTS = g.route_facts


def facts(title):
    if title not in _FACTS:
        _FACTS[title] = ROUTE_FACTS(title, ROOT)
    return _FACTS[title]


def context(title):
    if title not in _CTX:
        _CTX[title] = load_context(title, root=ROOT)
    return _CTX[title]


def rom_path(title):
    ctx = context(title)
    return ctx.source_dir / ctx.lock["outputs"][ctx.artifact]["filename"]


def profile(title):
    return json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def cached_sources(monkeypatch):
    # Route facts are pure functions of the pinned source; recomputing them per test only costs time.
    monkeypatch.setattr(g, "route_facts", lambda title, root=ROOT: facts(title))
    monkeypatch.setattr(g, "load_context", lambda title, root=ROOT: context(title))


def cart(title, target, player_id):
    """Independent synthetic CartRAM: one fresh L5 Totodile, both copies, both checksums."""
    layout = codec.Gen2Layout.from_profile(profile(title), title)
    raw = bytearray(0x8000)

    def put(symbol, data):
        address = layout.addresses[symbol]
        for region in layout.regions:
            base = layout.addresses[STARTS[region.name]]
            if base <= address and address + len(data) <= base + region.length:
                for copy_start in (region.primary, region.backup):
                    start = copy_start + address - base
                    raw[start:start + len(data)] = data
                return
        raise AssertionError(symbol)

    f = facts(title)
    base = Rom(rom_path(title).read_bytes(), profile(title)["titles"][title]).base_stats(158)
    curve = ("GROWTH_MEDIUM_FAST", "GROWTH_SLIGHTLY_FAST", "GROWTH_SLIGHTLY_SLOW",
             "GROWTH_MEDIUM_SLOW", "GROWTH_FAST", "GROWTH_SLOW")[base["growth_rate"]]
    word = 0xA5C3
    stats = codec.calc_stats(base, codec.decode_dvs(word), dict.fromkeys(codec.EXP_NAMES, 0), 5)
    c = layout.constants
    mon = bytearray(48)
    mon[c["MON_SPECIES"]] = 158
    mon[c["MON_LEVEL"]] = 5
    mon[c["MON_OT_ID"]:c["MON_OT_ID"] + 2] = player_id.to_bytes(2, "big")
    mon[c["MON_EXP"]:c["MON_EXP"] + 3] = codec.exp_for_level(5, curve).to_bytes(3, "big")
    mon[c["MON_DVS"]:c["MON_DVS"] + 2] = word.to_bytes(2, "big")
    for field, name in (("MON_HP", "hp"), ("MON_MAXHP", "hp"), ("MON_ATK", "attack"), ("MON_DEF", "defense"),
                        ("MON_SPD", "speed"), ("MON_SAT", "special_attack"), ("MON_SDF", "special_defense")):
        mon[c[field]:c[field] + 2] = stats[name].to_bytes(2, "big")
    put("wPartyCount", bytes([1, 158, 255]))
    put("wPartyMon1", bytes(mon))
    put("wPlayerID", player_id.to_bytes(2, "big"))
    area = f["maps"]["ElmsLab" if target == "town" else "Route29"]
    tile = area["grid"].index(1 if target == "town" else 2)
    put("wMapGroup", bytes([area["map_group"]]))
    put("wMapNumber", bytes([area["map_number"]]))
    put("wXCoord", bytes([tile % area["width"]]))
    put("wYCoord", bytes([tile // area["width"]]))
    pocket = [f["balls"]["item"], f["balls"]["quantity"]] if target == "battle" else []
    put("wNumBalls", bytes([len(pocket) // 2]))
    put("wBalls", bytes(pocket + [255]))
    for copy_name in ("primary", "backup"):
        for address, value in layout.markers[copy_name]:
            raw[address] = value
        at = layout.checksum_offsets[copy_name]
        raw[at:at + 2] = codec.sav_checksum(bytes(raw), layout, copy_name).to_bytes(2, "little")
    return bytes(raw)


def receipt(spec, cart_bytes, **changes):
    phases = ["new-game", "leave-bedroom", "mom", "to-elm", "starter"]
    if spec.target == "battle":
        phases += ["o10-balls", "leave-elm", "to-route29", "route29-grass"]
    phases += ["native-save", "route-saved"]
    row = {"schema": "gen2-played-route-v1", "case": spec.name, "facts_fingerprint": facts(spec.title)["fingerprint"],
           "cartram_sha256": hashlib.sha256(cart_bytes).hexdigest(), "rom_sha1": facts(spec.title)["rom_sha1"],
           "core_mode": "CGB", "speed_percent": 300, "input_mode": "normal_buttons",
           "phases": [{"phase": phase, "frame": 10 * n} for n, phase in enumerate(phases)],
           "harness_write_scopes": ["O-10:BallPocket"] if spec.target == "battle" else []}
    row.update(changes)
    return row


def ot_for(spec):
    return 0x5678 if spec.identity == "ot2" else 0x1234


def write_inventory(directory, *, ids=ot_for, receipts=None):
    directory.mkdir(parents=True, exist_ok=True)
    for title in TITLES:
        (directory / f"{title}_route_facts.json").write_text(json.dumps(facts(title)))
    for spec in g.FIXTURES:
        body = cart(spec.title, spec.target, ids(spec))
        (directory / f"{spec.name}.SaveRAM").write_bytes(body + TRAILER)
        row = (receipts or {}).get(spec.name) or receipt(spec, body)
        (directory / f"{spec.name}.played.json").write_text(json.dumps(row))
    return directory


def case(directory, spec, **paths):
    artifacts = {"fixture": directory / f"{spec.name}.SaveRAM",
                 "profile": ROOT / f"data/games/gen2_{spec.title}/profile.json", "rom": rom_path(spec.title),
                 "route_facts": directory / f"{spec.title}_route_facts.json",
                 "played_receipt": directory / f"{spec.name}.played.json"}
    artifacts.update(paths)
    return qualification.FixtureCase(spec.name, artifacts, {
        "title": spec.title, "rom_sha1": facts(spec.title)["rom_sha1"], "scope": "candidate fixture",
        "route_facts_sha256": g._facts_sha256(facts(spec.title))})


def static(directory, spec, **paths):
    return qualification.qualify_fixtures([case(directory, spec, **paths)], {"qualify": g.qualify_stage}, scope="static")


def problems(report):
    return " | ".join(report["errors"] + [p for row in report["fixtures"] for p in row["problems"]])


SPEC = g.BY_NAME


# --- identities and SaveRAM boundary -------------------------------------------------------------

def test_all_eight_fixture_identities_are_enumerated_with_a_distinct_ot2_pair():
    assert sorted(SPEC) == sorted([f"{t}_{k}" for t in TITLES for k in ("town", "battle")]
                                  + ["crystal_town_ot2", "crystal_battle_ot2"])
    ot2 = [spec for spec in g.FIXTURES if spec.identity == "ot2"]
    assert {spec.title for spec in ot2} == {"crystal"} and {spec.target for spec in ot2} == {"town", "battle"}
    # The second OT comes from a different played name choice and a shifted title idle.
    assert all(spec.title_idle_frames > 0 for spec in ot2)
    assert all(spec.title_idle_frames == 0 for spec in g.FIXTURES if spec.identity == "default")
    manifest = g.fixture_manifest(ROOT)
    assert manifest["qualified"] is False and len(manifest["fixtures"]) == 8
    for row in manifest["fixtures"]:
        assert row["filename"] == row["name"] + ".SaveRAM" and row["core_mode"] == "CGB"
        assert row["ball_exception"] == ("O-10" if row["target"] == "battle" else None)


def test_saveram_must_be_exactly_cartram_plus_rtc_trailer():
    body = bytes(0x8000)
    assert g.SAVERAM_BYTES == 32790 and g.cart_ram(body + TRAILER) == body
    for length in (0x8000, 32789, 32791, 0):
        with pytest.raises(ValueError, match="exactly 32790"):
            g.cart_ram(bytes(length))


@pytest.mark.parametrize("title", TITLES)
def test_played_shape_inspects_and_the_rtc_trailer_is_never_compared(title):
    body = cart(title, "battle", 0x1234)
    spec = SPEC[f"{title}_battle"]
    rom = rom_path(title).read_bytes()
    first = g.inspect_candidate(body + TRAILER, profile(title), rom, spec)
    second = g.inspect_candidate(body + bytes(22), profile(title), rom, spec)
    assert first == second and first["player_id"] == 0x1234 and first["physical_qualification"] is False
    assert first["cartram_sha256"] == hashlib.sha256(body).hexdigest()
    with pytest.raises(ValueError, match="exactly 32790"):
        g.inspect_candidate(body, profile(title), rom, spec)
    damaged = bytearray(body)
    damaged[layout_party_offset(title)] ^= 1
    with pytest.raises(ValueError, match="checksum"):
        g.inspect_candidate(bytes(damaged) + TRAILER, profile(title), rom, spec)


def layout_party_offset(title):
    layout = codec.Gen2Layout.from_profile(profile(title), title)
    region = next(r for r in layout.regions if r.name == "pokemon")
    return region.primary + layout.addresses["wPartyMon1"] - layout.addresses["wPokemonData"]


# --- static oracle: positive and refusal controls ------------------------------------------------

def test_static_inventory_of_eight_passes_and_never_claims_physical_or_natural_balls(tmp_path):
    report = g.qualification_report(write_inventory(tmp_path / "inv"), root=ROOT)
    assert report["passed"], problems(report)
    assert report["physical_qualification"] is False and len(report["fixtures"]) == 8
    for row in report["fixtures"]:
        evidence = row["stages"][0]["evidence"]
        assert evidence["natural_ball_acquisition"] == "false"
        assert evidence["ball_origin"] == ("O-10 harness injection" if "battle" in row["name"] else "none")


def test_ot2_pair_must_carry_a_distinct_ot_and_cohorts_must_agree(tmp_path):
    same = g.qualification_report(write_inventory(tmp_path / "same", ids=lambda spec: 0x1234), root=ROOT)
    assert not same["passed"] and "OT2" in problems(same)
    split = g.qualification_report(write_inventory(
        tmp_path / "split", ids=lambda spec: 0x9999 if spec.name == "gold_battle" else ot_for(spec)), root=ROOT)
    assert not split["passed"] and "cohort" in problems(split)


@pytest.mark.parametrize("change,match", [
    ({"remove": "silver_town.SaveRAM"}, "exact eight"),
    ({"rename": ("gold_town.SaveRAM", "Pokemon - Gold Version (USA, Europe).SaveRAM")}, "exact eight"),
    ({"rename": ("crystal_town.SaveRAM", "crystal_town_ot3.SaveRAM")}, "exact eight"),
])
def test_wrong_or_missing_saveram_name_refuses_the_inventory(tmp_path, change, match):
    directory = write_inventory(tmp_path / "inv")
    if "remove" in change:
        (directory / change["remove"]).unlink()
    else:
        old, new = change["rename"]
        (directory / old).rename(directory / new)
    report = g.qualification_report(directory, root=ROOT)
    assert not report["passed"] and match in problems(report)


def test_wrong_title_rom_or_profile_refuses(tmp_path):
    directory = write_inventory(tmp_path / "inv")
    spec = SPEC["crystal_town"]
    assert static(directory, spec)["passed"]
    tampered = bytearray(rom_path("crystal").read_bytes())
    tampered[-1] ^= 1
    (tmp_path / "rom.gbc").write_bytes(bytes(tampered))
    report = static(directory, spec, rom=tmp_path / "rom.gbc")
    assert not report["passed"] and "pinned sha1" in problems(report)
    report = static(directory, spec, rom=rom_path("gold"))
    assert not report["passed"] and "pinned sha1" in problems(report)
    report = static(directory, spec, profile=ROOT / "data/games/gen2_gold/profile.json")
    assert not report["passed"] and "another ROM" in problems(report)
    # A Gold save presented as the Crystal case: bytes of the wrong title never decode as Crystal.
    report = static(directory, spec, fixture=directory / "gold_town.SaveRAM")
    assert not report["passed"]


def test_wrong_length_saveram_refuses_qualification(tmp_path):
    directory = write_inventory(tmp_path / "inv")
    path = directory / "crystal_town.SaveRAM"
    path.write_bytes(path.read_bytes()[:0x8000])
    report = static(directory, SPEC["crystal_town"])
    assert not report["passed"] and "exactly 32790" in problems(report)


def test_wrong_terrain_or_missing_ball_refuses(tmp_path):
    directory = write_inventory(tmp_path / "inv")
    town = cart("crystal", "town", 0x1234)
    (directory / "crystal_battle.SaveRAM").write_bytes(town + TRAILER)
    (directory / "crystal_battle.played.json").write_text(json.dumps(receipt(SPEC["crystal_battle"], town)))
    report = static(directory, SPEC["crystal_battle"])
    assert not report["passed"] and "target map" in problems(report)


@pytest.mark.parametrize("name,changes,match", [
    ("crystal_town", {"input_mode": "memory_write"}, "input/core"),
    ("crystal_town", {"speed_percent": 100}, "input/core"),
    ("crystal_town", {"harness_write_scopes": ["O-10:BallPocket"]}, "staging"),
    ("crystal_town", {"harness_write_scopes": ["party"]}, "staging"),
    ("crystal_battle", {"harness_write_scopes": ["O-10:BallPocket", "EventFlags"]}, "staging"),
    ("crystal_battle", {"harness_write_scopes": []}, "staging"),
    ("gold_town", {"schema": "gen2-staged-v1"}, "receipt"),
    ("gold_town", {"cartram_sha256": "0" * 64}, "binding"),
    ("gold_town", {"facts_fingerprint": "0" * 64}, "binding"),
    ("silver_battle", {"phases": [{"phase": "native-save", "frame": 1}, {"phase": "route-saved", "frame": 2}]},
     "phase missing"),
    ("silver_battle", {"phases": None}, "trace missing"),
])
def test_staged_or_non_played_input_is_refused(tmp_path, name, changes, match):
    spec = SPEC[name]
    body = cart(spec.title, spec.target, ot_for(spec))
    directory = write_inventory(tmp_path / "inv", receipts={name: receipt(spec, body, **changes)})
    report = static(directory, spec)
    assert not report["passed"] and match in problems(report)


def test_o10_phase_is_required_for_battle_and_refused_for_town(tmp_path):
    town = SPEC["crystal_town"]
    body = cart("crystal", "town", 0x1234)
    rows = receipt(town, body)["phases"]
    rows.insert(5, {"phase": "o10-balls", "frame": 45})
    battle = SPEC["crystal_battle"]
    battle_body = cart("crystal", "battle", 0x1234)
    no_o10 = [row for row in receipt(battle, battle_body)["phases"] if row["phase"] != "o10-balls"]
    directory = write_inventory(tmp_path / "inv", receipts={
        town.name: receipt(town, body, phases=rows), battle.name: receipt(battle, battle_body, phases=no_o10)})
    assert "O-10 injection" in problems(static(directory, town))
    assert "o10-balls" in problems(static(directory, battle))


# --- full chain: boot, re-save, reload -----------------------------------------------------------

def game_callbacks(tmp_path, *, resave_trailer=bytes(22), witness=True):
    def boot(context):
        spec = SPEC[context.fixture]
        inspection = g.inspect_candidate(context.artifacts["fixture"], json.loads(context.artifacts["profile"]),
                                         context.artifacts["rom"], spec)
        out = tmp_path / "out" / context.fixture
        out.mkdir(parents=True, exist_ok=True)
        game = {"schema": "gen2-fixture-game-witness-v1", "case": context.fixture, "stage": "boot",
                "stage_fingerprint": context.fingerprint, "rom_sha1": context.provenance["rom_sha1"],
                "cartram_sha256": inspection["cartram_sha256"], "core_mode": "CGB", "speed_percent": 100,
                "observer": "independent_GAME", "continue_selected": True, "native_load_completed": True,
                "rtc_validated": True, "party_raw_hex": inspection["party_raw_hex"]}
        (out / "boot.json").write_text(json.dumps(game if witness else {}))
        return qualification.StageReceipt("boot", context.fingerprint, "PASS", evidence={"model": "boot"},
                                          outputs={"game_witness": out / "boot.json"})

    def resave(context):
        out = tmp_path / "out" / context.fixture
        saved = out / "resaved.SaveRAM"
        saved.write_bytes(context.artifacts["fixture"][:0x8000] + resave_trailer)
        spec = SPEC[context.fixture]
        inspection = g.inspect_candidate(saved.read_bytes(), json.loads(context.artifacts["profile"]),
                                         context.artifacts["rom"], spec)
        game = {"schema": "gen2-fixture-game-witness-v1", "case": context.fixture, "stage": "reload",
                "stage_fingerprint": context.fingerprint, "rom_sha1": context.provenance["rom_sha1"],
                "cartram_sha256": inspection["cartram_sha256"], "core_mode": "CGB", "speed_percent": 100,
                "observer": "independent_GAME", "continue_selected": True, "native_load_completed": True,
                "rtc_validated": True, "party_raw_hex": inspection["party_raw_hex"]}
        (out / "reload.json").write_text(json.dumps(game))
        return qualification.StageReceipt("resave", context.fingerprint, "PASS", evidence={"model": "resave"},
                                          outputs={"fixture": saved, "reload_witness": out / "reload.json"})

    return {"boot": boot, "resave": resave}


def test_full_chain_passes_with_a_changed_rtc_trailer_after_resave(tmp_path):
    directory = write_inventory(tmp_path / "inv")
    report = g.qualification_report(directory, root=ROOT, scope="full",
                                    game_callbacks=game_callbacks(tmp_path, resave_trailer=b"\xff" * 22))
    assert report["passed"], problems(report)
    assert report["physical_qualification"] is False
    assert all([s["stage"] for s in row["stages"]] == list(qualification.FULL_CHAIN) for row in report["fixtures"])


@pytest.mark.parametrize("callbacks", [None, "boot_only", "resave_only"])
def test_missing_boot_or_resave_stage_refuses_full_qualification(tmp_path, callbacks):
    directory = write_inventory(tmp_path / "inv")
    full = game_callbacks(tmp_path)
    chosen = {None: None, "boot_only": {"boot": full["boot"]}, "resave_only": {"resave": full["resave"]}}[callbacks]
    report = g.qualification_report(directory, root=ROOT, scope="full", game_callbacks=chosen)
    assert not report["passed"] and "required stage callbacks missing" in problems(report)


def test_independent_oracles_cannot_be_replaced_and_a_missing_game_witness_refuses(tmp_path):
    directory = write_inventory(tmp_path / "inv")
    with pytest.raises(ValueError, match="cannot be replaced"):
        g.qualification_report(directory, root=ROOT, scope="full",
                               game_callbacks={**game_callbacks(tmp_path), "post_oracle": lambda c: None})
    report = g.qualification_report(directory, root=ROOT, scope="full",
                                    game_callbacks=game_callbacks(tmp_path, witness=False))
    assert not report["passed"] and "GAME witness" in problems(report)


# --- source route facts --------------------------------------------------------------------------

@pytest.mark.parametrize("title", TITLES)
def test_route_facts_make_stairs_walkable_and_mark_carpet_exits(title):
    maps = facts(title)["maps"]
    for name, x, y in (("PlayersHouse2F", 7, 0), ("PlayersHouse1F", 9, 0)):
        assert maps[name]["grid"][y * maps[name]["width"] + x] == 1, name
    carpets = {(name, w["x"], w["y"]): w["carpet"] for name in ("PlayersHouse1F", "ElmsLab") for w in maps[name]["warps"]}
    assert carpets == {("PlayersHouse1F", 6, 7): "Down", ("PlayersHouse1F", 7, 7): "Down",
                       ("PlayersHouse1F", 9, 0): None, ("ElmsLab", 4, 11): "Down", ("ElmsLab", 5, 11): "Down"}
    assert all(w["carpet"] is None for w in maps["NewBarkTown"]["warps"])
    # Crystal meets Mom on a coord event; Gold/Silver on an on-entry scene script.
    assert bool(maps["PlayersHouse1F"]["coord_events"]) == (title == "crystal")


# --- Lua route driver (pure; no emulator) --------------------------------------------------------

@pytest.fixture
def lua():
    runtime = LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().P = runtime.execute((ROOT / "lua/tests/gen2_scripted_play.lua").read_text(encoding="utf-8"))
    return runtime


def driver(lua, title="crystal", target="town", identity="default"):
    f = facts(title)
    case = {"title": title, "target": target, "identity": identity, "attempt_id": "model",
            "title_idle_frames": 0, "name": f"{title}_{target}"}
    table = lua.table_from(json.loads(json.dumps(f)), recursive=True)
    return lua.globals().P.new(table, lua.table_from(case)), f


def point(lua, f, area, x, y, **fields):
    row = {"title": f["title"], "rom_sha1": f["rom_sha1"], "core_mode": "CGB", "attempt_id": "model",
           "facts_fingerprint": f["fingerprint"], "overworld_ready": True, "battle_mode": 0, "party_count": 0,
           "map_group": f["maps"][area]["map_group"], "map_number": f["maps"][area]["map_number"], "x": x, "y": y}
    row.update(fields)
    value = lua.table_from(row)
    value["can_step"] = lua.table_from({"Up": True, "Down": True, "Left": True, "Right": True})
    value["blocked"] = lua.table()
    return value


def step(d, value, frame=0):
    result = d.step(value, frame)
    buttons, phase = result[0], result[1]
    request = result[2] if len(result) > 2 else None
    return (dict(buttons) if buttons is not None else None), phase, request


def test_lua_refuses_foreign_or_staged_observations(lua):
    d, f = driver(lua)
    buttons, why, _ = step(d, point(lua, f, "PlayersHouse2F", 3, 3, rom_sha1="0" * 40))
    assert buttons is None and "foreign" in why
    buttons, why, _ = step(d, point(lua, f, "PlayersHouse2F", 3, 3, party_count=1))
    assert buttons is None and "empty party" in why
    d, f = driver(lua)
    buttons, why, _ = step(d, point(lua, f, "PlayersHouse2F", 3, 3, has_existing_save=True))
    assert buttons is None and "empty isolated save" in why


def test_lua_bedroom_route_reaches_the_staircase(lua):
    d, f = driver(lua)
    buttons, phase, _ = step(d, point(lua, f, "PlayersHouse2F", 7, 1))
    assert phase == "leave-bedroom" and buttons == {"Up": True}


def test_lua_pushes_through_the_carpet_exit(lua):
    d, f = driver(lua)
    step(d, point(lua, f, "PlayersHouse2F", 3, 3))
    buttons, phase, _ = step(d, point(lua, f, "PlayersHouse1F", 6, 7, mom_scene=1, pokegear_obtained=True))
    assert phase == "mom" and buttons == {"Down": True}


@pytest.mark.parametrize("title", ("gold", "silver"))
def test_lua_waits_for_the_gold_silver_on_entry_mom_scene(lua, title):
    d, f = driver(lua, title)
    step(d, point(lua, f, "PlayersHouse2F", 3, 3))
    buttons, phase, _ = step(d, point(lua, f, "PlayersHouse1F", 9, 1, mom_scene=0, pokegear_obtained=False))
    assert buttons == {} and phase == "mom"


def after_starter(lua, f, area, x, y, **fields):
    base = {"party_count": 1, "starter_species": 158, "starter_level": 5, "got_starter": True,
            "pokegear_obtained": True, "new_bark_scene": f["maps"]["NewBarkTown"]["scenes"]["SCENE_NEWBARKTOWN_NOOP"]}
    base.update(fields)
    return point(lua, f, area, x, y, **base)


def pocket(lua, items):
    return lua.table_from({"count": len(items), "terminator": 255,
                           "items": lua.table_from([lua.table_from({"id": i, "quantity": q}) for i, q in items])})


def test_lua_o10_injection_is_requested_only_at_the_lab_and_never_natural(lua):
    d, f = driver(lua, target="battle")
    step(d, point(lua, f, "PlayersHouse2F", 3, 3))
    buttons, phase, request = step(d, after_starter(lua, f, "ElmsLab", 7, 5, ball_pocket=pocket(lua, [])))
    assert buttons == {} and phase == "o10-balls"
    assert request["kind"] == "o10-ball-pocket" and request["exception"] == "O-10"
    assert request["natural_acquisition"] is False
    d, f = driver(lua, target="battle")
    step(d, point(lua, f, "PlayersHouse2F", 3, 3))
    buttons, why, _ = step(d, after_starter(lua, f, "NewBarkTown", 6, 4, ball_pocket=pocket(lua, [])))
    assert buttons is None and "O-10 only" in why


def test_lua_town_route_saves_inside_the_lab_only(lua):
    d, f = driver(lua)
    step(d, point(lua, f, "PlayersHouse2F", 3, 3))
    buttons, why, _ = step(d, after_starter(lua, f, "NewBarkTown", 6, 4))
    assert buttons is None and "inside Elm" in why
    d, f = driver(lua)
    step(d, point(lua, f, "PlayersHouse2F", 3, 3))
    buttons, phase, _ = step(d, after_starter(lua, f, "ElmsLab", 7, 5, save_success_counter=0))
    assert phase == "native-save" and buttons == {"Start": True}


# --- played-route gate binding --------------------------------------------------------------------

@pytest.mark.parametrize("title", TITLES)
def test_route_facts_carry_the_source_bound_observer_block(title):
    f, ctx = facts(title), context(title)
    obs = f["observer"]
    assert obs["overworld_tick"]["symbol"] == "OWPlayerInput"
    for site in [obs["overworld_tick"], obs["save_completed"], *f["ui_origins"].values()]:
        assert ctx.rom[site["flat"]:site["flat"] + 1].hex() == site["hex"]
    signals = json.loads((ROOT / f"data/games/gen2_{title}/engine_signals.json").read_text(encoding="utf-8"))
    assert obs["save_completed"]["flat"] == signals["titles"][title]["sites"]["save_completed"]["rom_offset"]
    assert obs["facing"] == {"Down": 0, "Up": 4, "Left": 8, "Right": 12}
    structs = ctx.symbol("wObjectStructs").address
    assert ctx.symbol("wPlayerDirection").address == structs + obs["object"]["direction"]
    assert obs["screen"] == {"width": 20, "height": 18}
    # Elm asks a mission yes/no only in Crystal; every other driver prompt has a source anchor.
    assert ("elm_mission" in obs["prompts"]) == (title == "crystal")
    assert {"clock_confirm", "mom_dst", "mom_dst_confirm", "mom_phone", "starter_confirm", "nickname",
            "save_confirm"} <= set(obs["prompts"])
    assert set(obs["scene_symbols"]) == {"PlayersHouse1F", "ElmsLab", "NewBarkTown"}


def test_run_play_dispatches_the_reviewed_gate_and_names_the_receipt(tmp_path):
    spec = g.BY_NAME["crystal_battle"]
    calls = []

    def runner(script, **kwargs):
        calls.append((script, kwargs))
        return True, "result.txt", "RESULT: PASS"

    out = g.run_play(spec, {"observer_qualified": True, "attempt_id": "model-1", "gate_script": g.GATE_SCRIPT},
                     root=ROOT, runner=runner)
    (script, kwargs), = calls
    assert script == g.GATE_SCRIPT and (ROOT / script).is_file()
    assert kwargs["speed_percent"] == 300 and kwargs["rom_key"] == "crystal_cold" and kwargs["fixture_path"] is None
    case = json.loads(kwargs["env_overrides"]["SLINK_GEN2_FIXTURE_CASE"])
    assert case["name"] == spec.name and case["attempt_id"] == "model-1"
    assert json.loads(kwargs["env_overrides"]["SLINK_GEN2_ROUTE_FACTS"])["fingerprint"] == facts("crystal")["fingerprint"]
    assert Path(out["receipt_path"]).name == "crystal_battle.played.json"
    assert Path(out["receipt_path"]).parent == Path(out["candidate_path"]).parent
    assert out["qualified"] is False

