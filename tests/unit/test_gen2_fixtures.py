"""MODEL controls for the Gen 2 fixture tooling and scripted route.

Synthetic CartRAM buffers live only in tmp_path; they are never played saves, and nothing here
launches an emulator (the qualification gate is a model runner). The routes stay UNRUN: passing
these controls is no PHYSICAL evidence.
"""
from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
from pathlib import Path

import pytest
from lupa import LuaRuntime

from server.adapters import gen2_codec as codec
from server.adapters.gen2_rom_scan import Rom
from tools import fixture_qualification as qualification, gen2_fixtures as g, run_gb_gate
from tools.gen2_source_data import load_context

ROOT = Path(__file__).resolve().parents[2]
TITLES = ("crystal", "gold", "silver")
_FACTS, _CTX = {}, {}
STARTS = {"player": "wPlayerData", "player1": "wPlayerData1", "player2": "wPlayerData2",
          "player3": "wPlayerData3", "map": "wCurMapData", "pokemon": "wPokemonData"}
TRAILER = bytes(range(22))
ROUTE_FACTS = g.route_facts


def facts(title, errand=False):
    if (title, errand) not in _FACTS:
        _FACTS[title, errand] = ROUTE_FACTS(title, ROOT, errand=True) if errand else ROUTE_FACTS(title, ROOT)
    return _FACTS[title, errand]


def spec_facts(spec):
    return facts(spec.title, spec.name in g.ERRAND_FIXTURES)


def facts_file(spec):
    return f"{spec.title}{'_errand' if spec.name in g.ERRAND_FIXTURES else ''}_route_facts.json"


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
    monkeypatch.setattr(g, "route_facts", lambda title, root=ROOT, errand=False: facts(title, errand))
    monkeypatch.setattr(g, "load_context", lambda title, root=ROOT: context(title))


def cart(title, target, player_id):
    """Independent synthetic CartRAM: one fresh L5 Totodile, both copies, both checksums."""
    layout = codec.Gen2Layout.from_profile(profile(title), title)
    raw = bytearray(0x8000)

    def put(symbol, data):
        address = layout.addresses[symbol] if symbol in layout.addresses else context(title).symbol(symbol).address
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
    # New-game state the fresh-fixture guards require (C engine/menus/intro_menu.asm:163-183): no roamer
    # released, Mystery Gift item 0 / unlocked -1; a one-day countdown stamped day 0 (as the played fixtures);
    # the roamer history already at its CONTINUE fixed point, so an identical re-save is a valid transition.
    for n in (1, 2, 3):
        put(f"wRoamMon{n}MapGroup", b"\xff\xff")
    raw[sram_offset(title, "sMysteryGiftUnlocked")] = 0xFF
    put("wDailyResetTimer", b"\x01\x00")
    put("wRoamMons_CurMapNumber", bytes([area["map_number"], area["map_group"]] * 2))
    if title != "crystal":   # Gold/Silver save the play-time counter already counting (Crystal: unsaved byte)
        put("wGameTimerPaused", b"\x01")
    for copy_name in ("primary", "backup"):
        for address, value in layout.markers[copy_name]:
            raw[address] = value
        at = layout.checksum_offsets[copy_name]
        raw[at:at + 2] = codec.sav_checksum(bytes(raw), layout, copy_name).to_bytes(2, "little")
    return bytes(raw)


def receipt(spec, cart_bytes, **changes):
    phases = ["new-game", "leave-bedroom", "mom", "to-elm", "starter"]
    if spec.name in g.ERRAND_FIXTURES:
        phases += ["o10-balls", "leave-elm", "to-route29", "errand-west", "errand-mr-pokemon", "errand-egg",
                   "errand-east", "errand-elm", "errand-handoff", "leave-elm", "to-route29", "route29-grass"]
    elif spec.target == "battle":
        phases += ["o10-balls", "leave-elm", "to-route29", "route29-grass"]
    phases += ["native-save", "route-saved"]
    row = {"schema": "gen2-played-route-v1", "case": spec.name, "facts_fingerprint": spec_facts(spec)["fingerprint"],
           "cartram_sha256": hashlib.sha256(cart_bytes).hexdigest(), "rom_sha1": spec_facts(spec)["rom_sha1"],
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
        (directory / facts_file(spec)).write_text(json.dumps(spec_facts(spec)))
        body = cart(spec.title, spec.target, ids(spec))
        (directory / f"{spec.name}.SaveRAM").write_bytes(body + TRAILER)
        row = (receipts or {}).get(spec.name) or receipt(spec, body)
        (directory / f"{spec.name}.played.json").write_text(json.dumps(row))
    return directory


def case(directory, spec, **paths):
    artifacts = {"fixture": directory / f"{spec.name}.SaveRAM",
                 "profile": ROOT / f"data/games/gen2_{spec.title}/profile.json", "rom": rom_path(spec.title),
                 "route_facts": directory / facts_file(spec),
                 "played_receipt": directory / f"{spec.name}.played.json"}
    artifacts.update(paths)
    return qualification.FixtureCase(spec.name, artifacts, {
        "title": spec.title, "rom_sha1": spec_facts(spec)["rom_sha1"], "scope": "candidate fixture",
        "route_facts_sha256": g._facts_sha256(spec_facts(spec))})


def static(directory, spec, **paths):
    return qualification.qualify_fixtures([case(directory, spec, **paths)], {"qualify": g.qualify_stage}, scope="static")


def problems(report):
    return " | ".join(report["errors"] + [p for row in report["fixtures"] for p in row["problems"]])


SPEC = g.BY_NAME


# --- identities and SaveRAM boundary -------------------------------------------------------------

def test_all_ten_fixture_identities_are_enumerated_with_distinct_ot2_controls():
    assert sorted(SPEC) == sorted([f"{t}_{k}" for t in TITLES for k in ("town", "battle")]
                                  + ["crystal_town_ot2", "crystal_battle_ot2", "gold_battle_ot2", "gold_battle_errand"])
    ot2 = [spec for spec in g.FIXTURES if spec.identity == "ot2"]
    assert {(spec.title, spec.target) for spec in ot2} == {("crystal", "town"), ("crystal", "battle"), ("gold", "battle")}
    # The second OT comes from a different played name choice and a shifted title idle.
    assert all(spec.title_idle_frames > 0 for spec in ot2)
    assert all(spec.title_idle_frames == 0 for spec in g.FIXTURES if spec.identity == "default")
    manifest = g.fixture_manifest(ROOT)
    assert manifest["qualified"] is False and len(manifest["fixtures"]) == 10
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

def test_static_inventory_of_nine_passes_and_never_claims_physical_or_natural_balls(tmp_path):
    report = g.qualification_report(write_inventory(tmp_path / "inv"), root=ROOT)
    assert report["passed"], problems(report)
    assert report["physical_qualification"] is False and len(report["fixtures"]) == 9
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
    gold = g.qualification_report(write_inventory(
        tmp_path / "gold", ids=lambda spec: 0x1234 if spec.name == "gold_battle_ot2" else ot_for(spec)), root=ROOT)
    assert not gold["passed"] and "Gold OT2" in problems(gold)


@pytest.mark.parametrize("change,match", [
    ({"remove": "silver_town.SaveRAM"}, "exact played-fixture inventory"),
    ({"rename": ("gold_town.SaveRAM", "Pokemon - Gold Version (USA, Europe).SaveRAM")}, "exact played-fixture inventory"),
    ({"rename": ("crystal_town.SaveRAM", "crystal_town_ot3.SaveRAM")}, "exact played-fixture inventory"),
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

def sram_offset(title, symbol):
    found = context(title).symbol(symbol)
    return found.bank * 0x2000 + found.address - 0xA000


@functools.cache
def layout_of(title):
    return codec.Gen2Layout.from_profile(profile(title), title)


def put_saved(raw, title, symbol, data):
    """Write one saved WRAM field (source symbol address) into both save copies."""
    layout, address = layout_of(title), context(title).symbol(symbol).address
    for region in layout.regions:
        base = layout.addresses[STARTS[region.name]]
        if base <= address and address + len(data) <= base + region.length:
            for at in (region.primary, region.backup):
                raw[at + address - base:at + address - base + len(data)] = data
            return
    raise AssertionError(symbol)


def get_saved(raw, title, symbol, size):
    """One saved WRAM field (source symbol address) from the primary copy."""
    layout, address = layout_of(title), context(title).symbol(symbol).address
    for region in layout.regions:
        base = layout.addresses[STARTS[region.name]]
        if base <= address and address + size <= base + region.length:
            return bytes(raw[region.primary + address - base:region.primary + address - base + size])
    raise AssertionError(symbol)


def reseal(raw, title):
    layout = layout_of(title)
    for copy_name in ("primary", "backup"):
        at = layout.checksum_offsets[copy_name]
        raw[at:at + 2] = codec.sav_checksum(bytes(raw), layout, copy_name).to_bytes(2, "little")


def resave_in_place(raw, spec):
    """A faithful native re-save: only what the source rewrites moves (stack top, play time, the RTC stamp,
    the object engine, the roamer map indices; Gold/Silver menus rewrite the SRAM window stack)."""
    raw[sram_offset(spec.title, "sStackTop")] ^= 0x5A
    for symbol in ("wGameTimeFrames", "wRTC", "wPlayerStruct"):
        put_saved(raw, spec.title, symbol, b"\x2a")
    # JumpRoamMons -> _BackUpMapIndices: last := cur, cur := the saved map (C engine/overworld/wildmons.asm:743-752).
    here = get_saved(raw, spec.title, "wMapNumber", 1) + get_saved(raw, spec.title, "wMapGroup", 1)
    put_saved(raw, spec.title, "wRoamMons_CurMapNumber", here + get_saved(raw, spec.title, "wRoamMons_CurMapNumber", 2))
    if spec.title != "crystal":
        raw[sram_offset(spec.title, "sWindowStackBottom") + 7] ^= 0x33
    reseal(raw, spec.title)


def resave_changes(symbol, data):
    """A re-save that also rewrites one saved field a CONTINUE + save must preserve (checksums stay valid)."""
    def resave(raw, spec):
        resave_in_place(raw, spec)
        put_saved(raw, spec.title, symbol, data)
        reseal(raw, spec.title)
    return resave


def resave_touches_hall_of_fame(raw, spec):
    """A re-save that writes outside every source save span (the Hall of Fame is not saved by SaveMenu)."""
    raw[sram_offset(spec.title, "sHallOfFame") + 3] ^= 0xFF


def fake_gate(*, land=None, resave=resave_in_place, trailer=b"\xff" * 22, witness=True, calls=None, mutate=None):
    """A model of the qualification gate: boots exactly the staged SaveRAM bytes and writes the GAME witness.

    `land(stage, location, position)` moves where CONTINUE lands; `resave(raw, spec)` is the native re-save;
    `mutate(stage, game)` edits the written witness.
    """
    def runner(script, *, rom_key, target, timeout, saveram_dir, fixture_path, speed_percent, env_overrides):
        q = json.loads(env_overrides["SLINK_GEN2_QUALIFY"])
        case = json.loads(env_overrides["SLINK_GEN2_FIXTURE_CASE"])
        spec = SPEC[case["name"]]
        assert script == g.GATE_SCRIPT and rom_key == spec.title and speed_percent == 100 and target == spec.target
        assert json.loads(env_overrides["SLINK_GEN2_ROUTE_FACTS"])["fingerprint"] == spec_facts(spec)["fingerprint"]
        assert q["facts"]["route_facts_fingerprint"] == spec_facts(spec)["fingerprint"]
        if calls is not None:
            calls.append((q["stage"], case["name"], Path(fixture_path).read_bytes()))
        raw = Path(fixture_path).read_bytes()
        inspection = g.inspect_candidate(raw, profile(spec.title), rom_path(spec.title).read_bytes(), spec)
        location, position = list(inspection["location"]), list(inspection["position"])
        if land:
            location, position = land(q["stage"], location, position)
        game = {"schema": "gen2-fixture-game-witness-v1", "case": spec.name, "stage": q["stage"],
                "stage_fingerprint": q["stage_fingerprint"], "rom_sha1": facts(spec.title)["rom_sha1"],
                "cartram_sha256": inspection["cartram_sha256"], "core_mode": "CGB", "speed_percent": 100,
                "observer": "independent_GAME", "continue_selected": True, "native_load_completed": True,
                "rtc_validated": True, "party_raw_hex": inspection["party_raw_hex"],
                "location": location, "position": position, "save_success_counter": 0,
                "site_hits": {"continue": 1, "continue_loaded": 1, "rtc_ok": 1, "restart_clock": 0,
                              "finish_continue": 1, "same_save_file": int(q["stage"] == "resave"), "erase_save": 0},
                "harness_write_scopes": [], "input_mode": "normal_buttons", "qualified": False}
        directory = Path(saveram_dir)
        if q["stage"] == "resave":
            body = bytearray(raw[:0x8000])
            resave(body, spec)
            (directory / run_gb_gate.describe_gen2(spec.title)["saveram_name"]).write_bytes(bytes(body) + trailer)
            game.update(save_success_counter=1, resave_cartram_sha256=hashlib.sha256(bytes(body)).hexdigest())
        if mutate:
            mutate(q["stage"], game)
        (directory / f"{spec.name}.{q['stage']}.witness.json").write_text(json.dumps(game if witness else {}))
        return True, "result.txt", "RESULT: PASS (model)"

    return runner


def game_callbacks(tmp_path, **gate):
    return g.game_callbacks("model-1", root=tmp_path / "work", runner=fake_gate(**gate))


def full_report(tmp_path, **gate):
    return g.qualification_report(write_inventory(tmp_path / "inv"), root=ROOT, scope="full",
                                  game_callbacks=game_callbacks(tmp_path, **gate))


def test_full_chain_passes_with_faithful_boot_resave_and_reload(tmp_path):
    report = full_report(tmp_path)
    assert report["passed"], problems(report)
    assert report["physical_qualification"] is False
    for row in report["fixtures"]:
        assert [s["stage"] for s in row["stages"]] == list(qualification.FULL_CHAIN)
        assert set(row["artifacts"]) >= {"boot:game_witness", "resave:fixture", "resave:save_witness",
                                         "resave:reload_witness"}
        # The re-save output is a fresh immutable copy, never the emulator's mutable save.
        assert Path(row["artifacts"]["resave:fixture"]["path"]).name == row["name"] + ".resaved.SaveRAM"


def test_continue_landing_off_the_recorded_checkpoint_fails_the_full_report(tmp_path):
    report = full_report(tmp_path, land=lambda stage, location, position: (location, [position[0] + 1, position[1]]))
    assert not report["passed"] and "different map/checkpoint" in problems(report)
    assert all(row["stages"][-1]["stage"] == "boot" and row["stages"][-1]["status"] == "FAIL"
               for row in report["fixtures"])


def test_reload_landing_on_another_map_fails_the_full_report(tmp_path):
    def moved(stage, location, position):
        return ([location[0], location[1] + 1] if stage == "reload" else location), position

    report = full_report(tmp_path, land=moved)
    assert not report["passed"] and "different map/checkpoint" in problems(report)


def test_post_oracle_refuses_a_lying_boot_callback_that_lands_elsewhere(tmp_path):
    """Even a boot callback that returns PASS cannot slip a wrong checkpoint past the fixed post-oracle."""
    faithful = game_callbacks(tmp_path)

    def lying_boot(context):
        receipt = faithful["boot"](context)
        path = receipt.outputs["game_witness"]
        game = json.loads(path.read_text())
        game["location"] = [game["location"][0], game["location"][1] + 1]
        path.write_text(json.dumps(game))
        return receipt

    report = g.qualification_report(write_inventory(tmp_path / "inv"), root=ROOT, scope="full",
                                    game_callbacks={"boot": lying_boot, "resave": faithful["resave"]})
    assert not report["passed"] and "different map/checkpoint" in problems(report)
    assert all(row["stages"][-1]["stage"] == "post_oracle" for row in report["fixtures"])


def test_resave_that_changes_cartram_outside_the_save_regions_fails(tmp_path):
    report = full_report(tmp_path, resave=resave_touches_hall_of_fame)
    assert not report["passed"] and "outside the source save regions" in problems(report)
    assert all(row["stages"][-1]["stage"] == "post_oracle" for row in report["fixtures"])


@pytest.mark.parametrize("title", TITLES)
def test_save_write_spans_are_source_bound_and_exclude_other_boxes(title):
    layout = codec.Gen2Layout.from_profile(profile(title), title)
    body = bytearray(cart(title, "town", 0x1234))
    spans = g.save_write_spans(title, layout, bytes(body))

    def inside(at):
        return any(start <= at < end for start, end in spans)

    assert inside(sram_offset(title, "sChecksum")) and inside(sram_offset(title, "sBackupChecksum"))
    assert inside(sram_offset(title, "sBox1")) and not inside(sram_offset(title, "sBox2"))
    assert not inside(sram_offset(title, "sHallOfFame")) and not inside(sram_offset(title, "sLinkBattleStats"))
    changed = bytearray(body)
    changed[sram_offset(title, "sBox2")] ^= 1
    assert g.unexpected_resave_bytes(bytes(body), bytes(changed), layout, title) == [
        (sram_offset(title, "sBox2"), sram_offset(title, "sBox2") + 1)]


# --- R3 review: scratch SRAM, the expected scenario delta, the re-derived GAME verdict ------------

@pytest.mark.parametrize("title", ["gold", "silver"])
def test_gold_silver_sram_window_stack_is_scratch_but_its_neighbours_are_not(title):
    """G ram/sram.asm:79-84: menus rewrite $1800-$1FFF; one byte below it is still a stray."""
    layout, body = layout_of(title), cart(title, "town", 0x1234)
    bottom, top = sram_offset(title, "sWindowStackBottom"), sram_offset(title, "sWindowStackTop")
    assert (bottom, top) == (0x1800, 0x1FFF)
    for at in (bottom, 0x1FFE, top):
        changed = bytearray(body)
        changed[at] ^= 0xFF
        assert g.unexpected_resave_bytes(body, bytes(changed), layout, title) == []
        assert g.resave_scenario_delta(body, bytes(changed), layout, title) == []
    changed = bytearray(body)
    changed[bottom - 1] ^= 1
    assert g.unexpected_resave_bytes(body, bytes(changed), layout, title) == [(bottom - 1, bottom)]


def test_crystal_keeps_its_window_stack_in_wram():
    assert "sWindowStackBottom" not in context("crystal").symbols
    body = cart("crystal", "town", 0x1234)
    changed = bytearray(body)
    changed[0x1FFE] ^= 0xFF
    assert g.unexpected_resave_bytes(body, bytes(changed), layout_of("crystal"), "crystal") == [(0x1FFE, 0x1FFF)]


@pytest.mark.parametrize("title", ["gold", "silver"])
def test_gold_silver_menu_close_tilemap_copy_into_sscratch_is_scratch_not_a_stray(title):
    """G engine/menus/menu.asm:569-591 RestoreOverworldMapTiles copies SCREEN_AREA (20*18 = $168) tilemap
    bytes into sScratch ($0000 flat) whenever an overworld menu closes: live gold_town re-save (review gen2-R18)."""
    body = bytes(cart(title, "town", 0x1234))
    for at in (0x0000, 0x0004, 0x0167):
        changed = bytearray(body)
        changed[at] ^= 0x5A
        assert g.unexpected_resave_bytes(body, bytes(changed), layout_of(title), title) == [], hex(at)
    changed = bytearray(body)
    changed[0x0168] ^= 0x5A
    assert g.unexpected_resave_bytes(body, bytes(changed), layout_of(title), title) == [(0x0168, 0x0169)]


def test_crystal_boot_may_only_zero_the_first_32_scratch_bytes():
    """C home/init.asm:98,205-213 ClearsScratch; Gold has no such routine, but its whole sScratch[0:$168]
    is already allowed UI scratch (RestoreOverworldMapTiles), so a Gold zero there is no stray either."""
    for title, stray in (("crystal", []), ("gold", [])):
        body = bytearray(cart(title, "battle", 0x1234))
        body[0:0x40] = b"\x77" * 0x40  # battle animation graphics left in sScratch
        booted = bytearray(body)
        booted[0:0x20] = bytes(0x20)
        assert g.unexpected_resave_bytes(bytes(body), bytes(booted), layout_of(title), title) == stray
    body = bytearray(cart("crystal", "battle", 0x1234))
    body[0:0x40] = b"\x77" * 0x40
    for at, value in ((0x05, 0x12), (0x20, 0x00)):
        changed = bytearray(body)
        changed[at] = value
        assert g.unexpected_resave_bytes(bytes(body), bytes(changed), layout_of("crystal"), "crystal") == [(at, at + 1)]


@pytest.mark.parametrize("title", TITLES)
def test_resave_scenario_delta_names_preserved_fields_and_allows_source_rewrites(title):
    layout, body = layout_of(title), cart(title, "battle", 0x1234)
    spec = g.BY_NAME[f"{title}_battle"]
    assert g.resave_scenario_delta(body, body, layout, title) == []
    faithful = bytearray(body)
    resave_in_place(faithful, spec)
    assert g.resave_scenario_delta(body, bytes(faithful), layout, title) == []
    balls = bytearray(body)
    put_saved(balls, title, "wNumBalls", b"\x00")
    reseal(balls, title)
    assert g.unexpected_resave_bytes(body, bytes(balls), layout, title) == []
    assert set(g.resave_scenario_delta(body, bytes(balls), layout, title)) == {"wNumBalls", "backup wNumBalls"}
    box = bytearray(body)
    box[sram_offset(title, "sBox")] ^= 1
    assert any(name.startswith("sBox") for name in g.resave_scenario_delta(body, bytes(box), layout, title))


# --- R4 #3: the object engine is enumerated field by field, never blanket-exempt --------------------

@pytest.mark.parametrize("title", TITLES)
def test_resave_frees_only_the_mutable_object_fields(title):
    """CONTINUE never reloads wMapObjects (C home/map.asm:385-417, G :754-786) nor runs RefreshPlayerCoords
    (C engine/overworld/player_object.asm:102-123, G :87-108): on a no-movement re-save the NPC struct IDs and the
    player map object's Y/X are compared byte for byte, like script pointers, event flags, sprites and masks."""
    layout, body = layout_of(title), cart(title, "town", 0x1234)
    moved = bytearray(body)
    for symbol, data in (("wObjectStructs", b"\x11" * 8), ("wObjectFollow_Leader", b"\xff\xff"), ("wCmdQueue", b"\x01")):
        put_saved(moved, title, symbol, data)
    reseal(moved, title)
    assert g.resave_scenario_delta(body, bytes(moved), layout, title) == []
    # N14b #3a/#3b falsifiers: these were free spans before.
    for symbol, data in (("wMap1ObjectStructID", b"\x03"), ("wMap2ObjectStructID", b"\xff"),
                         ("wMap15ObjectStructID", b"\x07"), ("wPlayerObjectYCoord", b"\x09"),
                         ("wPlayerObjectXCoord", b"\x0a"),
                         ("wMap1ObjectScript", b"\x34\x12"), ("wMap1ObjectEventFlag", b"\x01\x00"),
                         ("wMap1ObjectSprite", b"\x07"), ("wMap1ObjectHour1", b"\x05"), ("wObjectMasks", b"\xff"),
                         ("wVariableSprites", b"\x09")):
        changed = bytearray(body)
        put_saved(changed, title, symbol, data)
        reseal(changed, title)
        assert set(g.resave_scenario_delta(body, bytes(changed), layout, title)) == {symbol, "backup " + symbol}
    # The never-written `ds 40` pad between wCmdQueue and wMapObjects (C ram/wram.asm:3047, G :2462) stays compared.
    pad = bytearray(body)
    at = context(title).symbol("wMapObjects").address - 1
    for region in layout.regions:
        base = layout.addresses[STARTS[region.name]]
        if base <= at < base + region.length:
            pad[region.primary + at - base] ^= 1
    reseal(pad, title)
    assert g.resave_scenario_delta(body, bytes(pad), layout, title) != []


# --- R4 S1: ruled fields move only along their source transition ---------------------------------

def with_fields(body, title, *writes):
    changed = bytearray(body)
    for symbol, data in writes:
        put_saved(changed, title, symbol, data)
    reseal(changed, title)
    return bytes(changed)


@pytest.mark.parametrize("title", TITLES)
def test_resave_daily_reset_fields_follow_check_daily_reset_timer(title):
    """C engine/overworld/time.asm:61-81,99-122,288-306; G :47-67,85-96,243-261."""
    layout, fresh = layout_of(title), cart(title, "town", 0x1234)
    # A fired reset also resamples Crystal wKenjiBreakTimer from 0 to 3..6 (C :123-142).
    tick = (("wKenjiBreakTimer", b"\x03"),) if title == "crystal" else ()
    # Falsifier: a re-save that SETS a daily flag (DAILYFLAGS2_UNION_CAVE_LAPRAS_F, C constants/
    # ram_constants.asm:326-329) in both copies with repaired checksums -- the reset only ever clears them.
    lapras = with_fields(fresh, title, ("wDailyFlags2", bytes([1 << 1])))
    assert g.resave_scenario_delta(fresh, lapras, layout, title) == ["wDailyFlags1", "backup wDailyFlags1"]
    assert g.resave_scenario_delta(fresh, with_fields(lapras, title, ("wDailyResetTimer", b"\x01\x05"), *tick),
                                   layout, title) == ["wDailyFlags1", "backup wDailyFlags1"]
    # A candidate stamped day 10 with its one-day countdown running and the Lapras flag set today.
    body = with_fields(fresh, title, ("wDailyResetTimer", b"\x01\x0a"), ("wDailyFlags2", b"\x02"))

    def delta(*writes):
        return g.resave_scenario_delta(body, with_fields(body, title, *writes), layout, title)

    assert delta() == []
    assert delta(("wDailyResetTimer", b"\x01\x0b"), ("wDailyFlags2", b"\x00"), *tick) == []   # next day: reset
    # N14b S1b: a fired reset zeroes EVERY byte of the span; a surviving flag is not a mix it may leave.
    assert delta(("wDailyResetTimer", b"\x01\x0b"), *tick) == ["wDailyFlags1", "backup wDailyFlags1"]
    assert delta(("wDailyFlags2", b"\x00")) == ["wDailyFlags1", "backup wDailyFlags1"]    # no day passed
    assert delta(("wDailyResetTimer", b"\x00\x0b"), ("wDailyFlags2", b"\x00"), *tick) == [
        "wDailyResetTimer", "backup wDailyResetTimer"]
    assert delta(("wDailyResetTimer", b"\x02\x0a")) == ["wDailyResetTimer", "backup wDailyResetTimer"]
    assert delta(("wDailyFlags2", b"\x03"), ("wDailyResetTimer", b"\x01\x0b"), *tick) == [
        "wDailyFlags1", "backup wDailyFlags1"]
    # _CalcDaysSince wraps at 140 days: day 139 -> day 0 is one day.
    wrap = with_fields(fresh, title, ("wDailyResetTimer", b"\x01\x8b"), ("wDailyFlags2", b"\x02"))
    assert g.resave_scenario_delta(wrap, with_fields(wrap, title, ("wDailyResetTimer", b"\x01\x00"),
                                                     ("wDailyFlags2", b"\x00"), *tick), layout, title) == []


@pytest.mark.parametrize("title", TITLES)
def test_resave_day_stamps_must_be_valid_days(title):
    """N14b S1b: each check stamps wCurDay (C engine/overworld/time.asm:73-81,399-408, G :59-67,354-363); the
    mod-140 model holds only for stamps 0..139, so a stamp outside that range, before or after, refuses."""
    layout = layout_of(title)
    body = with_fields(cart(title, "town", 0x1234), title, ("wDailyResetTimer", b"\x01\x0a"))
    tick = (("wKenjiBreakTimer", b"\x03"),) if title == "crystal" else ()   # the reset fires in these

    def delta(base, *writes):
        return g.resave_scenario_delta(base, with_fields(base, title, *writes), layout, title)

    assert delta(body, ("wDailyResetTimer", b"\x01\x8b"), ("wTimerEventStartDay", b"\x8b"), *tick) == []
    assert delta(body, ("wDailyResetTimer", b"\x01\x8c"), *tick) == ["wDailyResetTimer", "backup wDailyResetTimer"]
    assert delta(body, ("wTimerEventStartDay", b"\xc8")) == ["wTimerEventStartDay", "backup wTimerEventStartDay"]
    stale = with_fields(body, title, ("wDailyResetTimer", b"\x01\x91"))
    assert delta(stale, ("wDailyResetTimer", b"\x01\x0a"), *tick) == ["wDailyResetTimer", "backup wDailyResetTimer"]


def test_crystal_kenji_and_map_sign_rules():
    """C engine/overworld/time.asm:123-142; C engine/menus/intro_menu.asm:467-468, map_name_sign.asm:29-31."""
    title, layout = "crystal", layout_of("crystal")
    body = with_fields(cart(title, "town", 0x1234), title, ("wDailyResetTimer", b"\x01\x0a"),
                       ("wKenjiBreakTimer", b"\x05"), ("wDailyRematchFlags", b"\x10"))
    day = ("wDailyResetTimer", b"\x01\x0b")

    def delta(base, *writes):
        return g.resave_scenario_delta(base, with_fields(base, title, *writes), layout, title)

    assert delta(body, day, ("wKenjiBreakTimer", b"\x04"), ("wDailyRematchFlags", b"\x00")) == []
    assert delta(body, ("wKenjiBreakTimer", b"\x04")) == ["wKenjiBreakTimer", "backup wKenjiBreakTimer"]
    assert delta(body, day, ("wKenjiBreakTimer", b"\x03"), ("wDailyRematchFlags", b"\x00")) == [
        "wKenjiBreakTimer", "backup wKenjiBreakTimer"]
    assert delta(body, ("wDailyRematchFlags", b"\x00")) == ["wDailyRematchFlags", "backup wDailyRematchFlags"]
    # N14b S1b: once the reset fires, 01:DC4C-DC57 must be all zero and Kenji must tick; unchanged is not enough.
    assert delta(body, day, ("wKenjiBreakTimer", b"\x04")) == ["wDailyRematchFlags", "backup wDailyRematchFlags"]
    assert delta(body, day, ("wDailyRematchFlags", b"\x00")) == ["wKenjiBreakTimer", "backup wKenjiBreakTimer"]
    one = with_fields(body, title, ("wKenjiBreakTimer", b"\x01"))
    for value, ok in ((3, True), (6, True), (0, False), (7, False)):
        assert (delta(one, day, ("wKenjiBreakTimer", bytes([value])), ("wDailyRematchFlags", b"\x00")) == []) is ok, value
    # The second wKenjiBreakTimer byte is never written: it is compared.
    assert set(delta(body, ("wKenjiBreakTimer", b"\x05\x01"))) == {"wKenjiBreakTimer", "backup wKenjiBreakTimer"}
    assert delta(body, ("wMapNameSignFlags", b"\x02")) == []
    assert delta(body, ("wMapNameSignFlags", b"\x06")) == ["wMapNameSignFlags", "backup wMapNameSignFlags"]


@pytest.mark.parametrize("title", ["gold", "silver"])
def test_gold_silver_timer_counting_and_swarm_rules(title):
    """G engine/menus/intro_menu.asm:347-348; G engine/events/specials.asm:299-314."""
    layout = layout_of(title)
    body = with_fields(cart(title, "town", 0x1234), title, ("wSwarmMapGroup", b"\x03\x04\x01"))

    def delta(base, *writes):
        return g.resave_scenario_delta(base, with_fields(base, title, *writes), layout, title)

    swarm = ("wSwarmMapGroup", b"\x00\x00\x00")   # DAILYFLAGS1_SWARM_F clear: CheckSwarmFlag zeroes them
    paused = with_fields(body, title, ("wGameTimerPaused", b"\x00"))
    assert delta(paused, swarm, ("wGameTimerPaused", b"\x01")) == []
    # FinishContinueFunction sets the bit on every CONTINUE: an unchanged clear bit is not its transition.
    assert delta(paused, swarm) == ["wGameTimerPaused", "backup wGameTimerPaused"]
    assert delta(body, swarm, ("wGameTimerPaused", b"\x03")) == ["wGameTimerPaused", "backup wGameTimerPaused"]
    assert delta(body, swarm) == []
    assert delta(body, ("wSwarmMapGroup", b"\x00\x04\x01")) == ["wSwarmMapGroup", "backup wSwarmMapGroup"]
    # CheckTimeEvents reaches CheckSwarmFlag on every overworld frame (G engine/overworld/events.asm:436-453):
    # stale swarm fields left unchanged with the flag clear cannot survive a CONTINUE.
    assert delta(body) == ["wSwarmMapGroup", "backup wSwarmMapGroup"]
    swarming = with_fields(body, title, ("wDailyFlags1", bytes([1 << 2])))
    assert delta(swarming) == []
    assert delta(swarming, swarm) == ["wSwarmMapGroup", "backup wSwarmMapGroup"]


@pytest.mark.parametrize("title", TITLES)
def test_resaved_rtc_status_flags_must_be_zero(title):
    """SaveRTC writes 0 (C/G engine/rtc/rtc.asm:76-88)."""
    layout, body = layout_of(title), cart(title, "town", 0x1234)
    flagged = bytearray(body)
    flagged[sram_offset(title, "sRTCStatusFlags")] = 1
    assert g.resave_scenario_delta(body, bytes(flagged), layout, title) == ["sRTCStatusFlags"]
    assert g.resave_scenario_delta(bytes(flagged), body, layout, title) == []


@pytest.mark.parametrize("title", TITLES)
def test_resave_roam_history_backup_is_required_on_every_continue(title):
    """N14b S1c: JumpRoamMons -> _BackUpMapIndices runs on every CONTINUE (C engine/menus/intro_menu.asm:372,
    engine/overworld/wildmons.asm:672-703,743-752; G :283, :677-708,748-757): a stale history left unchanged fails."""
    layout, spec = layout_of(title), SPEC[f"{title}_town"]
    body = cart(title, "town", 0x1234)
    here = get_saved(body, title, "wMapNumber", 1) + get_saved(body, title, "wMapGroup", 1)
    stale = with_fields(body, title, ("wRoamMons_CurMapNumber", here + bytes([here[0] - 1, here[1]])))
    assert g.resave_scenario_delta(stale, stale, layout, title) == [
        "wRoamMons_CurMapNumber", "backup wRoamMons_CurMapNumber"]
    faithful = bytearray(stale)
    resave_in_place(faithful, spec)
    assert get_saved(faithful, title, "wRoamMons_CurMapNumber", 4) == here * 2
    assert g.resave_scenario_delta(stale, bytes(faithful), layout, title) == []


# --- N14b fresh-fixture input guards: unmodelled CONTINUE transitions refuse the candidate ----------

def saved_write(symbol, data):
    def change(raw, title):
        put_saved(raw, title, symbol, data)
    return change


def sram_write(symbol, value, offset=0):
    def change(raw, title):
        raw[sram_offset(title, symbol) + offset] = value
    return change


@pytest.mark.parametrize("change, match", [
    (saved_write("wRoamMon1Species", b"\xf3"), "released roamer"),
    (saved_write("wRoamMon2MapGroup", b"\x0a"), "released roamer"),
    (saved_write("wRoamMon3MapNumber", b"\x05"), "released roamer"),
    (saved_write("wPartyMon1PokerusStatus", b"\x13"), "Pokerus"),
    (sram_write("sMysteryGiftItem", 0x01), "Mystery Gift"),
    (sram_write("sMysteryGiftUnlocked", 0x00), "Mystery Gift"),
    (sram_write("sMysteryGiftDecorationsReceived", 0x10, 5), "Mystery Gift"),
    (sram_write("sRTCStatusFlags", 0x40), "RTC fault"),
    (saved_write("wStatusFlags2", bytes([1 << 2])), "Bug Contest"),
])
@pytest.mark.parametrize("title", TITLES)
def test_fresh_fixture_input_guards_refuse_unmodelled_state(title, change, match):
    body = bytearray(cart(title, "town", 0x1234))
    spec, rom = SPEC[f"{title}_town"], rom_path(title).read_bytes()
    g.inspect_candidate(bytes(body) + TRAILER, profile(title), rom, spec)
    change(body, title)
    reseal(body, title)
    with pytest.raises(ValueError, match=match):
        g.inspect_candidate(bytes(body) + TRAILER, profile(title), rom, spec)


def test_crystal_battle_tower_carry_refuses_and_other_status_bits_do_not():
    """C engine/menus/save.asm:286-295,745-753; the played fixtures save wStatusFlags2 = $80 (bit 2 clear)."""
    body = bytearray(cart("crystal", "town", 0x1234))
    spec, rom = SPEC["crystal_town"], rom_path("crystal").read_bytes()
    put_saved(body, "crystal", "wStatusFlags2", b"\xfb")
    reseal(body, "crystal")
    g.inspect_candidate(bytes(body) + TRAILER, profile("crystal"), rom, spec)
    body[sram_offset("crystal", "sBattleTowerChallengeState")] = 4
    with pytest.raises(ValueError, match="Battle Tower"):
        g.inspect_candidate(bytes(body) + TRAILER, profile("crystal"), rom, spec)


def resave_flags_the_rtc(raw, spec):
    resave_in_place(raw, spec)
    raw[sram_offset(spec.title, "sRTCStatusFlags")] = 1


# --- R4 S3: the independent post-oracle requires and validates the native save witness -------------

def edit_save_witness(change):
    def edit(receipt):
        path = receipt.outputs["save_witness"]
        game = json.loads(path.read_text())
        change(game)
        path.write_text(json.dumps(game))
        return receipt
    return edit


@pytest.mark.parametrize("edit, match", [
    (lambda receipt: dataclasses.replace(
        receipt, outputs={k: v for k, v in receipt.outputs.items() if k != "save_witness"}), "resave:save_witness"),
    (edit_save_witness(lambda game: game.update(save_success_counter=0)), "save counter"),
    (edit_save_witness(lambda game: game["site_hits"].update(same_save_file=0)), "overwrite branch"),
    (edit_save_witness(lambda game: game.update(resave_cartram_sha256="0" * 64)), "save witness hash differs"),
])
def test_post_oracle_refuses_a_lying_resave_callback_without_a_valid_save_witness(tmp_path, edit, match):
    faithful = game_callbacks(tmp_path)
    report = g.qualification_report(write_inventory(tmp_path / "inv"), root=ROOT, scope="full",
                                    game_callbacks={"boot": faithful["boot"],
                                                    "resave": lambda context: edit(faithful["resave"](context))})
    assert not report["passed"] and match in problems(report)
    assert all(row["stages"][-1]["stage"] == "post_oracle" and row["stages"][-1]["status"] == "FAIL"
               for row in report["fixtures"])


def resave_moves_the_player(raw, spec):
    x = g._saved_field(bytes(raw), layout_of(spec.title), "wXCoord", 1)[0]
    resave_changes("wXCoord", bytes([(x + 1) % 256]))(raw, spec)


def resave_spends_a_ball(raw, spec):
    if spec.target != "battle":
        return resave_in_place(raw, spec)
    return resave_changes("wBalls", bytes([facts(spec.title)["balls"]["item"], 9, 255]))(raw, spec)


def resave_touches_the_active_box(raw, spec):
    resave_in_place(raw, spec)
    raw[sram_offset(spec.title, "sBox")] ^= 1


@pytest.mark.parametrize("resave, match", [
    (resave_changes("wMoney", b"\x00\x10\x00"), "must preserve: "),
    (resave_moves_the_player, "saved position"),
    (resave_spends_a_ball, "saved ball_items"),
    (resave_touches_the_active_box, "must preserve: sBox"),
    # R4 #3 falsifier: a two-copy wMap1ObjectScript rewrite with repaired checksums (C sym 01:d738, G/S 01:d45f).
    (resave_changes("wMap1ObjectScript", b"\x34\x12"), "must preserve: wMap1ObjectScript"),
    # R4 S1 falsifiers: a daily flag set, a roamer index off its backup rule.
    (resave_changes("wDailyFlags2", bytes([1 << 1])), "must preserve: wDailyFlags1"),
    (resave_changes("wRoamMons_LastMapGroup", b"\x2a"), "must preserve: wRoamMons_CurMapNumber"),
])
def test_resave_that_changes_a_preserved_saved_field_fails(tmp_path, resave, match):
    report = full_report(tmp_path, resave=resave)
    assert not report["passed"] and match in problems(report)
    assert any(row["stages"][-1]["stage"] == "post_oracle" and row["stages"][-1]["status"] == "FAIL"
               for row in report["fixtures"])


def test_resave_that_flushes_an_rtc_fault_fails(tmp_path):
    """R4 S1: a flushed sRTCStatusFlags=1. The N14b input guard in inspect_candidate refuses the re-saved image
    as soon as the resave stage inspects it, before the post-oracle's RESAVE_ZEROED_SRAM check."""
    report = full_report(tmp_path, resave=resave_flags_the_rtc)
    assert not report["passed"] and "RTC fault (sRTCStatusFlags)" in problems(report)


@pytest.mark.parametrize("stage, change, match", [
    ("boot", lambda game: game["site_hits"].update(restart_clock=1), "qualification incomplete"),
    ("boot", lambda game: game["site_hits"].update(continue_loaded=0), "qualification incomplete"),
    ("reload", lambda game: game["site_hits"].update(finish_continue=0), "qualification incomplete"),
    ("resave", lambda game: game["site_hits"].update(erase_save=1), "qualification incomplete"),
    ("resave", lambda game: game["site_hits"].update(same_save_file=0), "overwrite branch"),
    ("boot", lambda game: game.update(save_success_counter=1), "save counter"),
    ("reload", lambda game: game.update(save_success_counter=1), "save counter"),
    ("boot", lambda game: game.pop("site_hits"), "hit counts missing"),
    ("boot", lambda game: game.update(harness_write_scopes=["O-10:BallPocket"]), "staging"),
    ("resave", lambda game: game.update(input_mode="lua_write"), "non-button"),
    ("reload", lambda game: game.update(qualified=True), "qualification claim"),
])
def test_the_game_verdict_is_rederived_from_the_recorded_site_hits(tmp_path, stage, change, match):
    """The gate's own booleans stay True: only the recorded hits/counters/scopes differ."""
    report = full_report(tmp_path, mutate=lambda at, game: change(game) if at == stage else None)
    assert not report["passed"] and match in problems(report)


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


def test_a_failed_gate_run_fails_the_stage(tmp_path):
    callbacks = g.game_callbacks("model-1", root=tmp_path, runner=lambda script, **kw: (False, "r.txt", "RESULT: FAIL route failed"))
    spec = SPEC["crystal_town"]
    context = qualification.StageContext(spec.name, "boot", "a" * 64, {
        "fixture": cart("crystal", "town", 0x1234) + TRAILER, "profile": json.dumps(profile("crystal")).encode(),
        "rom": rom_path("crystal").read_bytes(), "route_facts": json.dumps(facts("crystal")).encode()},
        {"rom_sha1": facts("crystal")["rom_sha1"]}, ())
    receipt = callbacks["boot"](context)
    assert receipt.status == "FAIL" and "boot gate did not pass" in receipt.problems[0]
    with pytest.raises(ValueError, match="attempt ID"):
        g.game_callbacks("../escape")


def test_qualify_one_candidate_runs_boot_resave_reload_on_exact_bytes(tmp_path):
    root = tmp_path / "root"
    for title in TITLES:
        (root / f"data/games/gen2_{title}").mkdir(parents=True)
        (root / f"data/games/gen2_{title}/profile.json").write_text(json.dumps(profile(title)))
    spec = SPEC["crystal_battle"]
    saves = root / ".cache/gen2-fixtures/play-1" / spec.name / "saveram"
    saves.mkdir(parents=True)
    body = cart("crystal", "battle", 0x1234)
    candidate = saves / run_gb_gate.describe_gen2("crystal")["saveram_name"]
    candidate.write_bytes(body + TRAILER)
    (saves / f"{spec.name}.played.json").write_text(json.dumps(receipt(spec, body)))
    calls = []
    report = g.qualify(spec.name, candidate, "qual-1", root=root, runner=fake_gate(calls=calls))
    assert report["passed"], problems(report)
    assert report["attempt_id"] == "qual-1" and report["scope"] == "full" and report["physical_qualification"] is False
    assert [stage for stage, _, _ in calls] == ["boot", "resave", "reload"]
    assert calls[0][2] == calls[1][2] == body + TRAILER and calls[2][2][:0x8000] != body
    work = root / ".cache/gen2-fixtures/qual-1" / spec.name / "qualify"
    assert (work / "crystal_route_facts.json").is_file()
    assert all(Path(p["path"]).is_relative_to(work) for role, p in report["fixtures"][0]["artifacts"].items()
               if ":" in role)
    # A wrong candidate (another title's bytes) fails the very first stage.
    gold = saves / "gold.SaveRAM"
    gold.write_bytes(cart("gold", "battle", 0x1234) + TRAILER)
    bad = g.qualify(spec.name, gold, "qual-2", root=root, receipt_path=saves / f"{spec.name}.played.json",
                    runner=fake_gate())
    assert not bad["passed"] and bad["fixtures"][0]["stages"][0]["status"] == "FAIL"


@pytest.mark.parametrize("title", TITLES)
def test_qualify_facts_are_source_bound_and_leave_the_route_facts_unchanged(title):
    q, ctx = g.qualify_facts(title, ROOT), context(title)
    assert q["route_facts_fingerprint"] == facts(title)["fingerprint"] and q["speed_percent"] == 100
    for kind, site in [*q["sites"].items(), *q["ui_origins"].items()]:
        assert ctx.rom[site["flat"]:site["flat"] + 1].hex() == site["hex"], kind
    assert q["sites"]["continue_loaded"]["symbol"] == "Continue.Check1Pass"
    assert q["ui_origins"]["continue_confirm"]["symbol"] == "ConfirmContinue"
    assert q["prompts"] == {"save_confirm": ["save the game?"], "save_overwrite": ["OK to overwrite?"],
                            "save_overwrite_text": ["There is already a", "There is another"]}
    # The played-route facts carry no qualification-only anchor, so recorded receipts stay bound.
    assert "save_overwrite" not in facts(title)["observer"]["prompts"]


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
    assert {kind: site["symbol"] for kind, site in f["ui_origins"].items()
            if kind in ("yes_no", "text", "prompt_button", "wait_button", "day_picker")} == {
        "yes_no": "_YesNoBox", "text": "WaitPressAorB_BlinkCursor.loop",
        "prompt_button": "PromptButton.input_wait_loop", "wait_button": "JoyWaitAorB", "day_picker": "SetDayOfWeek.loop2"}
    assert obs["prompts"]["nickname"] == ["received?"]   # the row left under the box after the `cont` scroll
    assert ("elm_mission" in obs["prompts"]) == (title == "crystal")
    assert {"clock_confirm", "mom_dst", "mom_dst_confirm", "mom_phone", "starter_confirm", "nickname",
            "save_confirm"} <= set(obs["prompts"])
    assert set(obs["scene_symbols"]) == {"PlayersHouse1F", "ElmsLab", "NewBarkTown"}


@pytest.mark.parametrize("label", ["PromptButton.input_wait_loop", "JoyWaitAorB", "SetDayOfWeek.loop2"])
def test_route_facts_refuse_a_missing_wait_origin_label(monkeypatch, label):
    ctx = context("gold")
    symbols = {name: value for name, value in ctx.symbols.items() if name != label}
    monkeypatch.setattr(g, "load_context", lambda title, root=ROOT: dataclasses.replace(ctx, symbols=symbols))
    with pytest.raises(ValueError, match=f"required symbol '{label}' missing"):
        ROUTE_FACTS("gold", ROOT)


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

