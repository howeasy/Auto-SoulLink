"""Gen 2 played-fixture plans and independent qualification binding.

Authoring/inspection is read-only. This module never creates ROM/save/fixture
bytes, repairs a save, or treats a Lua RESULT line as fixture qualification.
An authorized coordinator supplies the game observer and boot/re-save callbacks.
Process, frame, timeout and qualification orchestration remain shared.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

if __package__:
    from . import fixture_qualification as qualification
    from .gen2_source_data import ROOT, load_context, rom_offset
    from .gen_gen2_area_map import build_area_map, constants, rom_bytes, source_lines
    from .gen_gen2_charmap import integer, verify_table
    from .gen_gen2_items import item_ids
    from .gen_gen2_species import const_block
    from .gen_gen2_area_map import constants as const_values
else:
    import fixture_qualification as qualification
    from gen2_source_data import ROOT, load_context, rom_offset
    from gen_gen2_area_map import build_area_map, constants, rom_bytes, source_lines
    from gen_gen2_charmap import integer, verify_table
    from gen_gen2_items import item_ids
    from gen_gen2_species import const_block
    from gen_gen2_area_map import constants as const_values


@dataclass(frozen=True)
class FixtureSpec:
    name: str
    title: str
    target: str
    identity: str
    title_idle_frames: int


FIXTURES = tuple(FixtureSpec(f"{title}_{target}", title, target, "default", 0)
                 for title in ("crystal", "gold", "silver") for target in ("town", "battle")) + tuple(
    FixtureSpec(f"crystal_{target}_ot2", "crystal", target, "ot2", 240) for target in ("town", "battle"))
MAPS = ("PlayersHouse2F", "PlayersHouse1F", "NewBarkTown", "ElmsLab", "Route29")
BY_NAME = {spec.name: spec for spec in FIXTURES}
# docs/gen2/reviews/OMP_RTC_SOURCE_2026-09-22.md: 32 KiB CartRAM plus the 22-byte BizHawk 2.11.1
# gambatte RTC trailer. Only the CartRAM is compared; the trailer changes on every save.
CART_RAM_BYTES = 0x8000
SAVERAM_BYTES = CART_RAM_BYTES + 22
# The reviewed played-route gate; run_gb_gate reads its terminal result path from the source.
GATE_SCRIPT = "lua/tests/test_gen2_scripted_gate.lua"
PASSABLE_COLLISION = ("FLOOR", "TALL_GRASS", "LONG_GRASS", "DOOR", "LADDER", "CAVE", "STAIRCASE",
                      "WARP_CARPET_DOWN", "WARP_CARPET_LEFT", "WARP_CARPET_UP", "WARP_CARPET_RIGHT")
# Yes/no prompt -> on-screen text anchors, each verified as a quoted literal in the pinned source.
# The Elm mission yes/no exists only in Crystal (Gold/Silver ElmsLab.asm has no intro yesorno).
PROMPT_ANCHORS = {
    "clock_confirm": ("What?", "Whoa!"), "mom_dst": ("Saving Time now?",), "mom_dst_confirm": ("is that OK?",),
    "mom_phone": ("the PHONE?",), "elm_mission": ("that I recently",), "starter_confirm": ("TOTODILE, the",),
    "nickname": ("Give a nickname to",), "save_confirm": ("save the game?",),
    # SetDayOfWeek confirm: _OakTimeIsItText, C data/text/common_1.asm:212-213, G :152-153.
    "day_confirm": (", is it?",),
}
PROMPT_SOURCES = ("data/text/common_1.asm", "data/text/common_2.asm", "data/text/common_3.asm",
                  "maps/PlayersHouse1F.asm", "maps/ElmsLab.asm")
if not __package__:
    sys.path.insert(0, str(ROOT))


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def cart_ram(raw):
    """The compared CartRAM of an exact-length SaveRAM; the RTC trailer is never compared."""
    _require(isinstance(raw, bytes) and len(raw) == SAVERAM_BYTES,
             f"Gen 2 SaveRAM must be exactly {SAVERAM_BYTES} bytes (CartRAM + RTC trailer)")
    return raw[:CART_RAM_BYTES]


def _facts_sha256(facts):
    return hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()


def _json(raw):
    value = json.loads(raw)
    _require(isinstance(value, dict), "expected JSON object")
    return value


def _numeric_definitions(text):
    return {name: integer(value) for name, value in re.findall(
        r"^DEF (\w+)\s+EQU\s+(\$[0-9a-fA-F]+|\d+)\s*(?:;[^\n]*)?$", text, re.M)}


def _map_facts(ctx, row, areas):
    name, map_const = row["map_name"], row["map_const"]
    dimensions = re.search(rf"^\s*map_const {map_const},\s*(\d+),\s*(\d+)",
                           ctx.read_source("constants/map_constants.asm"), re.M)
    _require(dimensions is not None, f"missing map dimensions: {name}")
    width, height = map(int, dimensions.groups())
    block_symbol = ctx.symbol(name + "_Blocks")
    _, attrs = rom_bytes(ctx, name + "_MapAttributes", 6)
    _require((attrs[1], attrs[2], attrs[3], int.from_bytes(attrs[4:6], "little")) ==
             (height, width, block_symbol.bank, block_symbol.address), "map block header mismatch")
    _, blocks = rom_bytes(ctx, name + "_Blocks", width * height)
    source_blocks = (ctx.source_dir / "maps" / (name + ".blk")).read_bytes()
    _require(source_blocks == blocks, f"source/ROM block data mismatch: {name}")
    header = next(line for _, line in source_lines(ctx.read_source("data/maps/maps.asm"), ctx.title)
                  if line.startswith("map " + name + ","))
    tileset = header.split(",")[1].strip()
    tilesets = constants(ctx.read_source("constants/tileset_constants.asm"), "TILESET_", ctx.title)
    index = tilesets[tileset]
    _require(bytes.fromhex(row["source"]["header_hex"])[1] == index, "map tileset byte mismatch")
    table = [line.split()[1] for _, line in source_lines(ctx.read_source("data/tilesets.asm"), ctx.title)
             if line.startswith("tileset ")]
    symbol = table[index] + "Coll"
    gfx = ctx.read_source("gfx/tilesets.asm")
    include = re.search(rf"^{symbol}::?\s*\nINCLUDE \"([^\"]+)\"", gfx, re.M)
    _require(include is not None, f"collision source not found: {symbol}")
    collision_values = _numeric_definitions(ctx.read_source("constants/collision_constants.asm"))
    collision = []
    for _, line in source_lines(ctx.read_source(include[1]), ctx.title):
        _require(line.startswith("tilecoll "), "unsupported collision row")
        tokens = [part.strip() for part in line[9:].split(",")]
        _require(len(tokens) == 4, "collision row width")
        collision.extend(collision_values["COLL_" + token] for token in tokens)
    verify_table(ctx, symbol, bytes(collision))
    allowed = {collision_values["COLL_" + value] for value in PASSABLE_COLLISION if "COLL_" + value in collision_values}
    grid, codes = [], []
    for y in range(height * 2):
        for x in range(width * 2):
            block = blocks[(y // 2) * width + x // 2]
            at = block * 4 + (y % 2) * 2 + x % 2
            _require(at < len(collision), "block indexes unknown collision row")
            code = collision[at]
            codes.append(code)
            grid.append(2 if code == collision_values["COLL_TALL_GRASS"] else 1 if code in allowed else 0)
    carpets = {collision_values["COLL_WARP_CARPET_" + side.upper()]: side for side in ("Down", "Left", "Up", "Right")}
    text = ctx.read_source("maps/" + name + ".asm")
    warps, scenes, objects, coords = [], {}, {}, []
    for line_no, line in source_lines(text, ctx.title):
        if line.startswith("warp_event "):
            x, y, destination, warp = [part.strip() for part in line[11:].split(",")]
            warps.append({"x": int(x), "y": int(y), "destination": destination,
                          "warp": int(warp), "source_line": line_no,
                          "carpet": carpets.get(codes[int(y) * width * 2 + int(x)])})
        elif line.startswith(("scene_script ", "scene_const ")):
            scene = line.split(",")[-1].strip() if line.startswith("scene_script ") else line.split()[1]
            scenes[scene] = len(scenes)
        elif line.startswith("coord_event "):
            x, y, scene, script = [part.strip() for part in line[12:].split(",")]
            coords.append({"x": int(x), "y": int(y), "scene": scene, "script": script})
        elif line.startswith("object_event "):
            fields = [part.strip() for part in line[13:].split(",")]
            objects[fields[11]] = {"x": int(fields[0]), "y": int(fields[1])}
    expected = bytearray([len(warps)])
    for warp in warps:
        destination = areas[warp["destination"]]
        expected.extend([warp["y"], warp["x"], warp["warp"], destination["map_group"], destination["map_number"]])
    _, observed = rom_bytes(ctx, name + "_MapEvents", len(expected), 2)
    _require(observed == expected, "source/ROM warp table mismatch")
    return {"map_group": row["map_group"], "map_number": row["map_number"], "map_const": map_const,
            "width": width * 2, "height": height * 2, "grid": grid, "warps": warps,
            "scenes": scenes, "objects": objects, "coord_events": coords,
            "source": f"{ctx.source_commit} maps/{name}.asm; {include[1]}"}


def _code_site(ctx, symbol, offset=0):
    bank, address = ctx.symbol(symbol)
    flat = rom_offset(bank, address + offset)
    return {"symbol": symbol, "symbol_offset": offset, "bank": bank, "addr": address + offset,
            "flat": flat, "hex": ctx.rom[flat:flat + 1].hex()}


def _observer_facts(ctx, root):
    """Source constants and code sites the played-route gate observes; RAM addresses stay in the profile."""
    ram_constants = ctx.read_source("constants/ram_constants.asm")
    objects = ctx.read_source("constants/map_object_constants.asm")
    directions = const_block(ram_constants, "DOWN")
    shifts = dict(re.findall(r"^DEF OW_(DOWN|UP|LEFT|RIGHT)\s+EQU\s+\1\s*<<\s*(\d+)", objects, re.M))
    _require(len(shifts) == 4, "overworld facing constants missing")
    facing = {name.title(): directions[name] << int(shifts[name]) for name in ("DOWN", "UP", "LEFT", "RIGHT")}
    fields, offset = {}, None
    for line in objects.splitlines():
        line = line.split(";", 1)[0].strip()
        if line == "rsreset" and offset is None:
            offset = 0
        elif offset is None:
            continue
        elif match := re.fullmatch(r"DEF (OBJECT_\w+)\s+rb(?:\s+(\d+))?", line):
            fields[match[1]] = offset
            offset += int(match[2] or 1)
        elif match := re.fullmatch(r"rb_skip(?:\s+(\d+))?", line):
            offset += int(match[1] or 1)
        elif line == "DEF OBJECT_LENGTH EQU _RS":
            fields["OBJECT_LENGTH"] = offset
            break
    count = _numeric_definitions(objects)["NUM_OBJECT_STRUCTS"]
    structs = ctx.symbol("wObjectStructs")
    _require(ctx.symbol("wObject1Struct").address - structs.address == fields.get("OBJECT_LENGTH")
             and ctx.symbol("wPlayerDirection").address - structs.address == fields.get("OBJECT_DIRECTION"),
             "object struct geometry disagrees with symbols")
    collision = _numeric_definitions(ctx.read_source("constants/collision_constants.asm"))
    hardware = ctx.read_source("constants/hardware.inc")
    screen = {key: int(re.search(rf"^def SCREEN_{key.upper()}\s+equ\s+(\d+)", hardware, re.M | re.I)[1])
              for key in ("width", "height")}
    events = const_block(ctx.read_source("constants/event_flags.asm"), "EVENT_GOT_A_POKEMON_FROM_ELM")
    prompts = {}
    texts = [ctx.read_source(path) for path in PROMPT_SOURCES]
    for prompt, anchors in PROMPT_ANCHORS.items():
        found = [anchor for anchor in anchors
                 if any(re.search(r'^\s*(?:text|line|cont|para)\s+"[^"]*' + re.escape(anchor), text, re.M)
                        for text in texts)]
        _require(found == list(anchors) or (not found and prompt == "elm_mission" and ctx.title != "crystal"),
                 f"prompt anchor missing from source: {prompt}")
        if found:
            prompts[prompt] = found
    signals = _json((Path(root) / f"data/games/gen2_{ctx.title}/engine_signals.json").read_bytes())
    save = signals["titles"][ctx.title]["sites"]["save_completed"]
    start = save["rom_offset"]
    _require(signals["source"]["rom_sha1"] == ctx.source_record()["rom_sha1"]
             and ctx.rom[start:start + len(save["expected_hex"]) // 2].hex() == save["expected_hex"]
             and rom_offset(save["bank"], save["addr"]) == start, "save-completed site differs from ROM")
    scenes = {name: f"w{name}SceneID" for name in ("PlayersHouse1F", "ElmsLab", "NewBarkTown")}
    for symbol in scenes.values():
        ctx.symbol(symbol)
    return {"overworld_tick": _code_site(ctx, "OWPlayerInput"),
            "save_completed": {"symbol": save["symbol"], "symbol_offset": save["symbol_offset"], "bank": save["bank"],
                               "addr": save["addr"], "flat": start, "hex": save["expected_hex"]},
            "facing": facing, "screen": screen, "scene_symbols": scenes, "prompts": prompts,
            "object": {"length": fields["OBJECT_LENGTH"], "count": count, "sprite": fields["OBJECT_SPRITE"],
                       "direction": fields["OBJECT_DIRECTION"], "map_x": fields["OBJECT_MAP_X"],
                       "map_y": fields["OBJECT_MAP_Y"]},
            "passable_collision": sorted({collision["COLL_" + name] for name in PASSABLE_COLLISION
                                          if "COLL_" + name in collision}),
            "pokegear_obtained_bit": const_values(ram_constants, "POKEGEAR_OBTAINED_F", ctx.title)["POKEGEAR_OBTAINED_F"],
            "got_starter_event": events["EVENT_GOT_A_POKEMON_FROM_ELM"]}


def route_facts(title, root=ROOT):
    """Source/ROM-bound candidate navigation facts; no live route qualification."""
    ctx = load_context(title, root=root)
    profile_path = Path(root) / "data/games" / f"gen2_{title}/profile.json"
    wrapper = _json(profile_path.read_bytes())
    _require(wrapper["source"] == ctx.source_record(), "profile provenance mismatch")
    selected = wrapper["titles"][title]
    areas = {row["map_const"]: row for row in build_area_map(ctx).values()}
    by_name = {row["map_name"]: row for row in areas.values()}
    maps = {name: _map_facts(ctx, by_name[name], areas) for name in MAPS}
    script = ctx.read_source("maps/ElmsLab.asm")
    _require("setmapscene NEW_BARK_TOWN, SCENE_NEWBARKTOWN_NOOP" in script,
             "starter west-exit release source missing")
    _require("givepoke TOTODILE, 5, BERRY" in script, "starter source changed")
    species = const_block(ctx.read_source("constants/pokemon_constants.asm"), "TOTODILE")
    item_names, _ = item_ids(ctx.read_source("constants/item_constants.asm"))
    items = {name: number for number, name in item_names.items()}
    capacity = _numeric_definitions(ctx.read_source("constants/item_data_constants.asm"))["MAX_BALLS"]
    ui_labels = {"title": "StartTitleScreen", "main_menu": "MainMenu", "name_choices": "NamePlayer",
                 "clock_hour": "InitClock.SetHourLoop", "clock_minute": "InitClock.SetMinutesLoop",
                 "yes_no": "YesNoBox", "text": "WaitPressAorB_BlinkCursor", "start_menu": "StartMenu",
                 "battle_menu": "BattleMenu"}
    if title == "crystal":
        ui_labels["gender"] = "InitGender"
    ui = {kind: {key: value for key, value in _code_site(ctx, symbol).items() if key != "symbol_offset"}
          for kind, symbol in ui_labels.items()}
    result = {"schema": "gen2-scripted-route-facts-v1", "title": title,
              "rom_sha1": ctx.source_record()["rom_sha1"], "source": ctx.source_record(),
              "core_mode": "CGB", "qualified": False, "maps": maps, "ui_origins": ui,
              "starter": {"species": species["TOTODILE"], "level": 5, "object": "TotodilePokeBallScript"},
              "balls": {"item": items["POKE_BALL"], "quantity": 10, "capacity": capacity,
                        "count_address": ctx.symbol("wNumBalls").address,
                        "data_address": ctx.symbol("wBalls").address, "bank": ctx.symbol("wBalls").bank},
              "observer": _observer_facts(ctx, root),
              "required_observer": ["source-bound UI context", "CGB bank-valid point", "script-idle overworld input",
                                    "live movement blocking", "native successful-save counter"],
              "open_obligations": ["live_point_observer_binding", "played_route_and_OT_separation",
                                   "RTC_and_cold_boot_continue_resave_reload_GAME_witnesses"]}
    _require(selected["ram"]["wNumBalls"] + 1 == result["balls"]["data_address"], "ball pocket geometry")
    result["fingerprint"] = _facts_sha256(result)
    return result


def fixture_manifest(root=ROOT):
    facts = {title: route_facts(title, root) for title in ("crystal", "gold", "silver")}
    return {"schema": "gen2-fixture-plan-v1", "qualified": False, "facts": facts,
            "fixtures": [{**vars(spec), "filename": spec.name + ".SaveRAM", "core_mode": "CGB",
                          "route_speed_percent": 300, "qualification_speed_percent": 100,
                          "max_frames": 120000, "max_phase_frames": 40000, "settle_frames": 30,
                          "budgets_measured": False,
                          "ball_exception": "O-10" if spec.target == "battle" else None}
                         for spec in FIXTURES]}


def run_play(spec, binding, *, root=ROOT, runner=None):
    """Dispatch only through an explicit reviewed gate binding; return a candidate."""
    _require(spec in FIXTURES, "unknown fixture case")
    _require(isinstance(binding, dict) and binding.get("observer_qualified") is True,
             "qualified Gen2 point observer/gate binding missing")
    from tools import run_gb_gate

    describe = getattr(run_gb_gate, "describe_gen2", None)
    _require(callable(describe), "shared runner Gen2 descriptor binding missing")
    descriptor = describe(spec.title + "_cold")
    facts = route_facts(spec.title, root)
    _require(descriptor["cold"] is True and descriptor["core_mode"] == "CGB"
             and descriptor["rom_sha1"] == facts["rom_sha1"] and descriptor["title"] == spec.title,
             "shared runner descriptor differs from selected source")
    attempt = binding.get("attempt_id")
    _require(isinstance(attempt, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", attempt), "bounded attempt ID required")
    script = binding.get("gate_script")
    _require(isinstance(script, str) and script.startswith("lua/tests/") and ".." not in Path(script).parts,
             "reviewed game gate script required")
    directory = Path(root).resolve() / ".cache/gen2-fixtures" / attempt / spec.name / "saveram"
    case = {**vars(spec), "attempt_id": attempt, "max_frames": binding.get("max_frames", 120000),
            "max_phase_frames": binding.get("max_phase_frames", 40000), "settle_frames": 30}
    passed, path, text = (runner or run_gb_gate.run_gate)(
        script, rom_key=spec.title + "_cold", target=spec.target, timeout=binding.get("timeout", 1200),
        saveram_dir=str(directory), fixture_path=None, speed_percent=300,
        env_overrides={"SLINK_GEN2_FIXTURE_CASE": json.dumps(case), "SLINK_GEN2_ROUTE_FACTS": json.dumps(facts)})
    return {"case": spec.name, "route_candidate": bool(passed), "qualified": False,
            "result_path": path, "diagnostic": text,
            "candidate_path": str(directory / descriptor["saveram_name"]),
            "receipt_path": str(directory / (spec.name + ".played.json")),
            "requires": list(qualification.FULL_CHAIN)}


def _saved_field(raw, layout, symbol, size):
    address = layout.addresses[symbol]
    starts = {"player": "wPlayerData", "player1": "wPlayerData1", "player2": "wPlayerData2",
              "player3": "wPlayerData3", "map": "wCurMapData", "pokemon": "wPokemonData"}
    for region in layout.regions:
        base = layout.addresses[starts[region.name]]
        if base <= address and address + size <= base + region.length:
            start = region.primary + address - base
            return raw[start:start + size]
    raise ValueError(f"saved field outside source copy regions: {symbol}")


def inspect_candidate(raw, profile, rom, spec):
    """Independent PYDEC checks; a structurally valid model is not a played save."""
    from server.adapters import gen2_codec as codec
    from server.adapters.gen2_rom_scan import Rom

    raw = cart_ram(raw)
    layout = codec.Gen2Layout.from_profile(profile, spec.title)
    witness = codec.strict_checksum_witness(raw, layout)
    _require(witness["valid"], "independent checksum/marker/copy witness refused")
    party = codec.decode_saved_party(raw, layout, copy_name="primary")
    _require(party["count"] == 1, "fixture must contain one played starter")
    mon = party["mons"][0]
    _require(mon["species_id"] == 158 and not mon["is_egg"], "fixture starter identity mismatch")
    player_id = int.from_bytes(_saved_field(raw, layout, "wPlayerID", 2), "big")
    _require(mon["ot_id"] == player_id, "starter OT differs from saved player")
    base = Rom(rom, profile["titles"][spec.title]).base_stats(mon["species_id"])
    curves = ("GROWTH_MEDIUM_FAST", "GROWTH_SLIGHTLY_FAST", "GROWTH_SLIGHTLY_SLOW",
              "GROWTH_MEDIUM_SLOW", "GROWTH_FAST", "GROWTH_SLOW")
    _require(mon["level"] == 5 and mon["exp"] == codec.exp_for_level(5, curves[base["growth_rate"]]),
             "starter level/experience is not a fresh level-5 grant")
    computed = codec.calc_stats(base, mon["dvs"], mon["stat_exp"], mon["level"])
    _require(mon["max_hp"] == computed["hp"] and mon["stats"] == {k: v for k, v in computed.items() if k != "hp"},
             "independent stored-stat control mismatch")
    _require(0 < mon["hp"] <= mon["max_hp"], "starter is fainted or HP is invalid")
    location = tuple(_saved_field(raw, layout, key, 1)[0] for key in ("wMapGroup", "wMapNumber"))
    position = tuple(_saved_field(raw, layout, key, 1)[0] for key in ("wXCoord", "wYCoord"))
    count = _saved_field(raw, layout, "wNumBalls", 1)[0]
    _require(count <= 12, "saved Ball pocket exceeds source capacity")
    pocket = _saved_field(raw, layout, "wBalls", count * 2 + 1)
    _require(pocket[-1] == 255, "saved Ball pocket terminator missing")
    items = [(pocket[index * 2], pocket[index * 2 + 1]) for index in range(count)]
    _require(all(1 <= item < 255 and 1 <= quantity <= 99 for item, quantity in items), "invalid saved Ball slot")
    return {"player_id": player_id, "location": location, "position": position, "ball_items": items,
            "party_raw_hex": party["raw_hex"],
            "identity_key": codec.key(mon), "cartram_sha256": hashlib.sha256(raw).hexdigest(),
            "physical_qualification": False}


def validate_played_receipt(receipt, spec, facts, inspection):
    _require(receipt.get("schema") == "gen2-played-route-v1" and receipt.get("case") == spec.name,
             "played-origin receipt missing or misbound")
    _require(receipt.get("facts_fingerprint") == facts["fingerprint"]
             and receipt.get("cartram_sha256") == inspection["cartram_sha256"]
             and receipt.get("rom_sha1") == facts["rom_sha1"], "played-origin byte/source binding mismatch")
    _require(receipt.get("core_mode") == "CGB" and receipt.get("speed_percent") == 300
             and receipt.get("input_mode") == "normal_buttons", "played-origin input/core witness incomplete")
    required = ["new-game", "leave-bedroom", "mom", "to-elm", "starter"]
    if spec.target == "battle":
        required += ["o10-balls", "leave-elm", "to-route29", "route29-grass"]
    required += ["native-save", "route-saved"]
    trace = receipt.get("phases")
    _require(isinstance(trace, list) and all(isinstance(row, dict) for row in trace), "played phase trace missing")
    labels = [row.get("phase") for row in trace]
    _require(spec.target == "battle" or "o10-balls" not in labels, "town fixture recorded an O-10 injection")
    previous = -1
    for label in required:
        positions = [i for i, value in enumerate(labels) if value == label and i > previous]
        _require(bool(positions), f"played route phase missing/out of order: {label}")
        previous = positions[0]
    frames = [row.get("frame") for row in trace]
    _require(all(type(frame) is int and frame >= 0 for frame in frames)
             and all(b > a for a, b in zip(frames, frames[1:], strict=False)), "played trace frame order invalid")
    allowed = ["O-10:BallPocket"] if spec.target == "battle" else []
    _require(receipt.get("harness_write_scopes") == allowed, "unauthorized or unrecorded fixture staging")


def validate_game_witness(game, context, inspection, stage, fingerprint):
    _require(game.get("schema") == "gen2-fixture-game-witness-v1"
             and game.get("case") == context.fixture and game.get("stage") == stage
             and game.get("stage_fingerprint") == fingerprint, "independent GAME witness missing/stale/misbound")
    _require(game.get("rom_sha1") == context.provenance["rom_sha1"]
             and game.get("cartram_sha256") == inspection["cartram_sha256"], "GAME source/save binding mismatch")
    _require(game.get("core_mode") == "CGB" and game.get("speed_percent") == 100
             and game.get("observer") == "independent_GAME"
             and game.get("continue_selected") is True and game.get("native_load_completed") is True
             and game.get("rtc_validated") is True, "GAME boot/RTC/CGB qualification incomplete")
    _require(game.get("party_raw_hex") == inspection["party_raw_hex"], "GAME/PYDEC loaded-party mismatch")


def validate_identity_cohorts(rows):
    ids = {row["name"]: row["stages"][0]["evidence"]["player_id"] for row in rows}
    for title in ("crystal", "gold", "silver"):
        _require(ids[f"{title}_town"] == ids[f"{title}_battle"], "town/battle OT cohort differs")
    _require(ids["crystal_town_ot2"] == ids["crystal_battle_ot2"]
             and ids["crystal_town_ot2"] != ids["crystal_town"], "Crystal OT2 is not a distinct played identity")


def qualify_stage(context):
    """Independent PYDEC static oracle for one candidate; never a played-origin or GAME proof."""
    try:
        spec = BY_NAME[context.fixture]
        rom = context.artifacts["rom"]
        profile = _json(context.artifacts["profile"])
        _require(context.provenance["title"] == spec.title
                 and hashlib.sha1(rom).hexdigest() == context.provenance["rom_sha1"],
                 "ROM differs from the pinned sha1 of the selected title")
        _require((profile.get("source") or {}).get("rom_sha1") == context.provenance["rom_sha1"],
                 "profile belongs to another ROM")
        result = inspect_candidate(context.artifacts["fixture"], profile, rom, spec)
        facts = _json(context.artifacts["route_facts"])
        _require(_facts_sha256(facts) == context.provenance["route_facts_sha256"], "route facts differ from verified source")
        target = facts["maps"]["ElmsLab" if spec.target == "town" else "Route29"]
        _require(result["location"] == (target["map_group"], target["map_number"]), "saved target map mismatch")
        x, y = result["position"]
        _require(0 <= x < target["width"] and 0 <= y < target["height"], "saved coordinate outside source map")
        tile = target["grid"][y * target["width"] + x]
        _require(tile == 2 if spec.target == "battle" else tile == 1, "saved fixture terrain is not the required floor/grass")
        if spec.target == "battle":
            _require(any(item == facts["balls"]["item"] and quantity > 0 for item, quantity in result["ball_items"]),
                     "battle fixture has no real Poke Ball in the Ball pocket")
        validate_played_receipt(_json(context.artifacts["played_receipt"]), spec, facts, result)
        # O-10: fixture balls are harness-injected for tests/validation, never a ball_received witness.
        return qualification.StageReceipt(context.stage, context.fingerprint, "PASS",
            evidence={"oracle": "independent Gen2 PYDEC", "player_id": str(result["player_id"]),
                      "ball_origin": "O-10 harness injection" if spec.target == "battle" else "none",
                      "natural_ball_acquisition": "false"},
            notes=("Static bytes do not prove played origin, RTC or GAME qualification.",))
    except (ValueError, KeyError, TypeError) as exc:
        return qualification.StageReceipt(context.stage, context.fingerprint, "FAIL", problems=(str(exc),))


def post_oracle_stage(context):
    """Independent re-save PYDEC plus GAME raw-party witnesses; CartRAM only, never the RTC trailer."""
    try:
        spec = BY_NAME[context.fixture]
        profile = _json(context.artifacts["profile"])
        original = inspect_candidate(context.artifacts["fixture"], profile, context.artifacts["rom"], spec)
        saved = inspect_candidate(context.artifacts["resave:fixture"], profile, context.artifacts["rom"], spec)
        stages = {row["stage"]: row["fingerprint"] for row in context.previous}
        validate_game_witness(_json(context.artifacts["boot:game_witness"]), context, original, "boot", stages["boot"])
        validate_game_witness(_json(context.artifacts["resave:reload_witness"]), context, saved, "reload", stages["resave"])
        _require(saved["player_id"] == original["player_id"] and saved["identity_key"] == original["identity_key"],
                 "re-save changed fixture identity")
        return qualification.StageReceipt(context.stage, context.fingerprint, "PASS",
            evidence={"oracle": "independent re-save PYDEC + GAME raw-party witness"})
    except (ValueError, KeyError, TypeError) as exc:
        return qualification.StageReceipt(context.stage, context.fingerprint, "FAIL", problems=(str(exc),))


def qualification_report(directory, *, root=ROOT, scope="static", game_callbacks=None):
    """Exactly eight cases; full mode requires independent GAME callbacks."""
    callbacks = {"qualify": qualify_stage, "post_oracle": post_oracle_stage}
    by_name = BY_NAME
    if game_callbacks:
        _require(set(game_callbacks) <= {"boot", "resave"}, "independent PYDEC callbacks cannot be replaced")
        callbacks.update(game_callbacks)
    try:
        paths = qualification.enumerate_fixtures(Path(directory), suffix=".SaveRAM", max_fixtures=8)
        _require({path.stem for path in paths} == set(by_name), "exact eight played-fixture inventory required")
        # Facts files are supplied by the coordinator's immutable attempt snapshot.
        cases, facts_by_title = [], {}
        for path in paths:
            spec = by_name[path.stem]
            ctx = load_context(spec.title, root=root)
            if spec.title not in facts_by_title:
                facts_by_title[spec.title] = route_facts(spec.title, root)
            cases.append(qualification.FixtureCase(spec.name,
                {"fixture": path, "profile": Path(root) / f"data/games/gen2_{spec.title}/profile.json",
                 "rom": ctx.source_dir / ctx.lock["outputs"][ctx.artifact]["filename"],
                 "route_facts": Path(directory) / (spec.title + "_route_facts.json"),
                 "played_receipt": Path(directory) / (spec.name + ".played.json")},
                {"title": spec.title, "rom_sha1": ctx.source_record()["rom_sha1"], "scope": "candidate fixture",
                 "route_facts_sha256": _facts_sha256(facts_by_title[spec.title])}))
        report = qualification.qualify_fixtures(cases, callbacks, scope=scope, max_fixtures=8)
        if report["passed"]:
            try:
                validate_identity_cohorts(report["fixtures"])
            except (ValueError, KeyError) as exc:
                report["passed"] = False
                report["errors"].append(str(exc))
    except (ValueError, OSError) as exc:
        report = qualification.qualify_fixtures([], callbacks, scope=scope, max_fixtures=8)
        report["errors"].append(str(exc))
    report["physical_qualification"] = False
    report["open_obligations"] = ["coordinator GAME/RTC/played-origin review", "recorded source/physical gate sign-off"]
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--qualify", type=Path, help="read-only candidate inventory")
    parser.add_argument("--scope", choices=("static", "full"), default="static")
    args = parser.parse_args(argv)
    try:
        result = qualification_report(args.qualify, root=args.root, scope=args.scope) if args.qualify else fixture_manifest(args.root)
        print(json.dumps(result, indent=2))
        return 0 if args.qualify is None or result["passed"] else 1
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({"passed": False, "qualified": False, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
