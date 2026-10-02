"""Pinned expansion static/wild facts and disclosed pending fixture construction."""

from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from tools import (  # noqa: E402
    gen3_fixtures as fixture,
    gen3_gift_egg_rows as acquisition,
    gen_gen3_profile as profile,
)
from tools.gba_map import Rom  # noqa: E402
from tools.gen_gen3_exp_trainers import enum_values  # noqa: E402
from tools.gen_gen3_trainers import map_keys  # noqa: E402
from tools.verify_gen3_exp_wild import readback  # noqa: E402

CASES = ("static", "static_run", "grass", "surf", "rock", "fish", "altering0", "altering1")
MASTER_CASES = {"static", "surf", "rock", "fish", "altering0", "altering1"}


def rock_rng_state(seed=0):
    """Native random.c SFC32_Seed warmup, stream1; state is a SYNTH precondition."""
    state = [0, 0, seed, 1]
    for _ in range(16):
        a, b, c, counter = state
        result = (a + b + counter) & 0xFFFFFFFF
        state = [b ^ (b >> 9), (c * 9) & 0xFFFFFFFF,
                 (result + ((c << 21) | (c >> 11))) & 0xFFFFFFFF,
                 (counter + 1) & 0xFFFFFFFF]
    return struct.pack("<4I", *state)


def facts(rom, case):
    if case not in CASES:
        raise ValueError("unknown static/wild case")
    base = acquisition.expansion_facts(rom)
    context = profile.expansion_inputs()
    src = fixture.expansion_src()
    ids = enum_values((src / "include/constants/species.h").read_text(), "SPECIES_")
    moves = enum_values((src / "include/constants/moves.h").read_text(), "MOVE_")
    balls = enum_values((src / "include/constants/pokeball.h").read_text(encoding="utf-8"), "BALL_")
    abilities = enum_values((src / "include/constants/abilities.h").read_text(encoding="utf-8"), "ABILITY_")
    items = enum_values((src / "include/constants/items.h").read_text(), "ITEM_")

    def flag(name):
        match = re.search(
            r"^#define\s+" + name + r"\s+(0x[\da-fA-F]+|\d+)\b",
            (src / "include/constants/flags.h").read_text(),
            re.M,
        )
        if not match:
            raise ValueError("source flag missing: " + name)
        return int(match[1], 0)

    name = (
        "AquaHideout_B1F"
        if case.startswith("static")
        else "AlteringCave"
        if case.startswith("altering")
        else "Route111"
        if case == "rock"
        else "Route102"
    )
    doc = json.loads((src / "data/maps" / name / "map.json").read_text())
    group, number = map(int, map_keys(src)[doc["id"]].split(":"))
    groups = profile.expansion_symbol(context, "gMapGroups")["address"]
    geometry = Rom(rom, groups, game="emerald").map(group, number)
    blocked = {(obj.x, obj.y) for obj in geometry.objects}

    def free(x, y):
        return (
            0 <= x < geometry.width
            and 0 <= y < geometry.height
            and geometry.collision[y][x] == 0
            and (x, y) not in blocked
            and not any((w.x, w.y) == (x, y) for w in geometry.warps)
        )

    directions = [(1, 0, "Left"), (-1, 0, "Right"), (0, 1, "Up"), (0, -1, "Down")]

    def adjacent(x, y):
        return next((x + dx, y + dy, face) for dx, dy, face in directions if free(x + dx, y + dy))

    rocks = []
    if case.startswith("static"):
        index, obj = next(
            (i, o)
            for i, o in enumerate(doc["object_events"])
            if o["script"] == "AquaHideout_B1F_EventScript_Electrode1"
        )
        x, y, face = adjacent(obj["x"], obj["y"])
        method, slots = "static", [(30, 30, ids["SPECIES_ELECTRODE"])]
        script = profile.expansion_symbol(context, obj["script"])["address"]
        native_flag = flag("FLAG_DEFEATED_ELECTRODE_1_AQUA_HIDEOUT")
    elif case == "rock":
        for obj in doc["object_events"]:
            if obj["graphics_id"] == "OBJ_EVENT_GFX_BREAKABLE_ROCK":
                rx, ry, rface = adjacent(obj["x"], obj["y"])
                rocks.append(
                    {"x": rx, "y": ry, "face": rface, "object_x": obj["x"], "object_y": obj["y"]}
                )
        x, y, face = rocks[0]["x"], rocks[0]["y"], rocks[0]["face"]
        method, script, native_flag = "rock_smash_mons", 0, base["flag"]
    elif case in ("surf", "fish"):
        water = geometry.find_behaviour(16)
        pairs = [
            (wx, wy, *adjacent(wx, wy))
            for wx, wy in water
            if any(
                free(wx + dx, wy + dy) and geometry.behaviour[wy + dy][wx + dx] != 16
                for dx, dy, _face in directions
            )
        ]
        wx, wy, x, y, face = pairs[0]
        # Select an actual DRY neighbouring tile, never another pond tile for the initial step.
        x, y, face = next(
            (wx + dx, wy + dy, d)
            for dx, dy, d in directions
            if free(wx + dx, wy + dy) and geometry.behaviour[wy + dy][wx + dx] != 16
        )
        method, script, native_flag = (
            "water_mons" if case == "surf" else "fishing_mons",
            0,
            base["flag"],
        )
    else:
        behaviour = 8 if case.startswith("altering") else 2
        cells = geometry.find_behaviour(behaviour)
        x, y = next(
            (x, y)
            for x, y in cells
            if free(x, y) and free(x + 1, y) and geometry.behaviour[y][x + 1] == behaviour
        )
        face, method, script, native_flag = "Right", "land_mons", 0, base["flag"]
    symbol = profile.expansion_symbol(context, "gMapGroups")["address"]

    def u32(address):
        return struct.unpack_from("<I", rom, address - 0x08000000)[0]

    header = u32(u32(symbol + 4 * group) + 4 * number)
    selector = 1 if case == "altering1" else 0
    if not case.startswith("static"):
        headers = [h for h in readback(rom, context, src)["headers"] if h["map"] == [group, number]]
        selected = headers[selector]
        slots = selected["habitats"][method]["slots"]
        if case == "fish":
            slots = slots[:2]  # native OLD_ROD range, deliberately not all fishing tiers
    # SOURCE: battle_scripts_2.s getexp on capture; battle_script_commands.c:2269
    # grants EVs even at MAX_LEVEL. Keep an exact species yield, never a blanket EV waiver.
    reverse_ids = {value: name for name, value in ids.items()}
    families = "\n".join(path.read_text(encoding="utf-8") for path in sorted(
        (src / "src/data/pokemon/species_info").glob("*.h")
    ))
    stat_names = {"hp": "HP", "attack": "Attack", "defense": "Defense", "speed": "Speed",
                  "sp_attack": "SpAttack", "sp_defense": "SpDefense"}
    ev_yields = {}
    for species in {row[2] for row in slots}:
        species_name = reverse_ids[species]
        blocks = re.findall(r"\[" + re.escape(species_name) + r"\]\s*=\s*\{(.*?)^    \},", families, re.M | re.S)
        if len(blocks) != 1:
            raise ValueError("native EV yield source block not unique: " + species_name)
        yields = {}
        for stat, field in stat_names.items():
            values = re.findall(r"\.evYield_" + field + r"\s*=\s*([^,]+),", blocks[0])
            if len(values) > 1 or any(not value.strip().isdigit() for value in values):
                raise ValueError("conditional/nonliteral EV yield needs own-build proof: " + species_name)
            yields[stat] = int(values[0]) if values else 0  # C aggregate zero initializer
        ev_yields[species] = yields
    fishing = {}
    if case == "fish":
        fishing_steps = enum_values((src / "src/fishing.c").read_text(encoding="utf-8"), "FISHING_")
        expected = {"FISHING_SHOW_DOTS": 4, "FISHING_WAIT_FOR_A": 8, "FISHING_A_PRESS_NO_MINIGAME": 9,
                    "FISHING_CHECK_MORE_DOTS": 10, "FISHING_MON_ON_HOOK": 11, "FISHING_START_ENCOUNTER": 12,
                    "FISHING_NOT_EVEN_NIBBLE": 13, "FISHING_END_NO_MON": 17}
        if any(fishing_steps.get(name) != value for name, value in expected.items()):
            raise ValueError("native fishing state enum changed")
        task = context["facts"]["structs"]["Task"]
        fishing = {
            "fishing_task": profile.expansion_symbol(context, "Task_Fishing")["address"],
            "tasks": profile.expansion_symbol(context, "gTasks")["address"],
            "task_size": task["size"], "task_active_off": task["fields"]["isActive"]["offset"],
            "task_data_off": task["fields"]["data"]["offset"],
            "task_count": profile.expansion_symbol(context, "gTasks")["size"] // task["size"],
        }
    if case == "rock":
        rng = profile.expansion_symbol(context, "gRngValue")
        if rng["size"] != 16:
            raise ValueError("own SFC32 RNG state size changed")
        rng_header = (src / "include/random.h").read_text(encoding="utf-8")
        native = (src / "src/random.c").read_text(encoding="utf-8")
        if "return Random32() >> 16;" not in rng_header or "ldmia r5!, {r1, r2, r3, r4}" not in native:
            raise ValueError("own SFC32 native RNG proof changed")
        random_symbol = profile.expansion_symbol(context, "Random32")
        offset = random_symbol["address"] - 0x08000000
        body = rom[offset:offset + random_symbol["size"]]
        returns = [i for i in range(0,len(body)-1,2) if body[i:i+2] == bytes.fromhex("7047")]
        if len(returns) != 1:
            raise ValueError("native Random32 return proof is not unique")
        modulus = int(re.search(r"^#define\s+MAX_ENCOUNTER_RATE\s+(\d+)",
                               (src/"src/wild_encounter.c").read_text(),re.M).group(1))
        repel_var = int(re.search(r"^#define\s+VAR_REPEL_STEP_COUNT\s+(0x[\da-fA-F]+)",
                                 (src/"include/constants/vars.h").read_text(),re.M).group(1),0)
        tip_name="Route111_EventScript_RockSmashTipFatMan"
        tip=next(o for o in doc["object_events"]if o["script"]==tip_name)
        if tip["trainer_type"]!="TRAINER_TYPE_NONE" or (tip["x"],tip["y"])!=(x+1,y-1):
            raise ValueError("native player-probe object is not the adjacent non-trainer")
        native_scripts=(src/"data/maps/Route111/scripts.inc").read_text()
        tip_body=native_scripts.split(tip_name+"::",1)[1].split("\n\n",1)[0]
        if any(op in tip_body for op in ("trainerbattle","givemon","giveegg","warp")) or "MSGBOX_DEFAULT"not in tip_body:
            raise ValueError("native player-probe object is not harmless default dialogue")
        object_symbol=profile.expansion_symbol(context,"gObjectEvents")
        count=int(re.search(r"^#define\s+OBJECT_EVENTS_COUNT\s+(\d+)",
                           (src/"include/constants/global.h").read_text(),re.M).group(1))
        object_header=(src/"include/global.fieldmap.h").read_text()
        if "/*0x04*/ u16 graphicsId"not in object_header or "/*0x10*/ struct Coords16 currentCoords"not in object_header or object_symbol["size"]!=count*0x24:
            raise ValueError("source-bound diagnostic ObjectEvent geometry drifted")
        graphics=enum_values((src/"include/constants/event_objects.h").read_text(),"OBJ_EVENT_GFX_")
        fishing["rock_player_probe"]={"npc_x":tip["x"],"npc_y":tip["y"],
            "object_events":object_symbol["address"],"object_count":count,"object_stride":0x24,
            "graphics_id":graphics[tip["graphics_id"]],"active_mask":1,
            "graphics_off":4,"coords_off":0x10,"map_num_off":9,"map_group_off":10,"map_offset":7,
            "hidden_flag":flag(tip["flag"]),"script":tip_name,
            "script_address":profile.expansion_symbol(context,tip_name)["address"],
            "source":"data/maps/Route111/map.json + scripts.inc:416-426; harmless native dialogue"}
        fishing["post_capture_probes"]={name:profile.expansion_symbol(context,name)["address"] for name in (
            "CB2_EndWildBattle","CB2_EndScriptedWildBattle","Task_ReturnToFieldNoScript",
            "Task_WaitForFadeAndEnableScriptCtx","ScriptContext_Enable")}
        fishing.update(rock_encounter_rate=selected["habitats"][method]["rate"], rock_rng_modulus=modulus, rock_rng_return=random_symbol["address"]+returns[0],
                       repel_var=repel_var, keen_eye_id=abilities["ABILITY_KEEN_EYE"],
                       rock_rng_address=rng["address"], rock_rng_size=rng["size"],
                       rock_rng_state_hex=rock_rng_state().hex(),
                       rock_rng_function=profile.expansion_symbol(context, "Random32")["address"],
                       rock_rng_scope="SYNTH native SeedRng(0)-equivalent SFC32 state at native RockSmash entry before first Random32; not persisted or a forced result")
    base.update(**fishing)
    base.update(
        ball_item=items["ITEM_MASTER_BALL"] if case in MASTER_CASES else items["ITEM_POKE_BALL"],
        ball_id=balls["BALL_MASTER"] if case in MASTER_CASES else balls["BALL_POKE"],
        damp_slot=2 if case.startswith("static") else None,
        damp_ability=abilities["ABILITY_DAMP"],
        self_ko_moves=[moves["MOVE_SELF_DESTRUCT"], moves["MOVE_EXPLOSION"]],
        faint_probe=profile.expansion_symbol(context, "SetValuesOnFaint")["address"],
        damp_probe=profile.expansion_symbol(context, "CancelerExplodingDamp")["address"],
        current_move=profile.expansion_symbol(context, "gCurrentMove")["address"],
        last_used_ability=profile.expansion_symbol(context, "gLastUsedAbility")["address"],
        sb1_pointer=profile.expansion_symbol(context, "gSaveBlock1Ptr")["address"],
        selector_var=0x403E,  # include/constants/vars.h VAR_ALTERING_CAVE_WILD_SET
        ev_yields=ev_yields,
        case=case,
        map=name,
        group=group,
        num=number,
        x=x,
        y=y,
        face=face,
        method=method,
        layout_id=struct.unpack_from("<H", rom, header - 0x08000000 + 18)[0],
        area=json.loads((ROOT / "data/games/gen3_exp/28877d73/area_map.json").read_text())[
            f"{group}:{number}"
        ],
        mirage_visible=flag("FLAG_MIRAGE_TOWER_VISIBLE"),
        mirage_var=int(re.search(r"^#define\s+VAR_MIRAGE_TOWER_STATE\s+(0x[\da-fA-F]+)",
                                (src / "include/constants/vars.h").read_text(), re.M).group(1),0),
        no_tower_layout=next(i+1 for i,row in enumerate(json.loads((src/"data/layouts/layouts.json").read_text())["layouts"])
                            if row["id"]=="LAYOUT_ROUTE111_NO_MIRAGE_TOWER"),
        flag=native_flag,
        script=script,
        slots=slots,
        rocks=rocks,
        selector=selector,
        projection_scope="set0; nonzero is selection-characterization only",
        surf_move=moves["MOVE_SURF"],
        rock_move=moves["MOVE_ROCK_SMASH"],
        old_rod=items["ITEM_OLD_ROD"],
        badges=[
            profile.expansion_inputs()["facts"]["constants"]["FLAG_BADGE01_GET"] + i
            for i in range(8)
        ],
        hide_static=flag("FLAG_HIDE_AQUA_HIDEOUT_B1F_ELECTRODE_1"),
        method_probes={
            name: profile.expansion_symbol(context, name)["address"]
            for name in (
                "StandardWildEncounter",
                "RockSmashWildEncounter",
                "FishingWildEncounter",
                "BattleSetup_StartScriptedWildBattle",
            )
        },
    )
    base["avatar"] = profile.expansion_symbol(context, "gPlayerAvatar")["address"]
    base["expected_probe"] = (
        "BattleSetup_StartScriptedWildBattle"
        if case.startswith("static")
        else "FishingWildEncounter"
        if case == "fish"
        else "RockSmashWildEncounter"
        if case == "rock"
        else "StandardWildEncounter"
    )
    if case == "surf":
        # The native Surf prompt moves onto the faced pond tile; swim between two pond tiles.
        dx, dy = {"Right": (1, 0), "Left": (-1, 0), "Up": (0, -1), "Down": (0, 1)}[face]
        wx, wy = x + dx, y + dy
        options = [
            (a, b, d)
            for a, b, d in [(1, 0, "Right"), (-1, 0, "Left"), (0, 1, "Down"), (0, -1, "Up")]
            if 0 <= wx + a < geometry.width
            and 0 <= wy + b < geometry.height
            and geometry.behaviour[wy + b][wx + a] == 16
            and (wx + a, wy + b) not in blocked
        ]
        direction = options[0][2]
        base["swim_direction"], base["swim_back"] = (
            direction,
            {"Right": "Left", "Left": "Right", "Up": "Down", "Down": "Up"}[direction],
        )
    return base


def static_damp_record(raw):
    """One masked ability edit through native substruct reordering and checksum encoding."""
    c = fixture.codec
    layout = fixture._record_layout(c.TITLE_EXPANSION)
    before = c.decode_party_mon_masked(raw, layout=layout)
    if before["species"] != 258 or before["ability_num"] not in (0, 1):
        raise ValueError("static Damp prep requires own base Mudkip ordinary abilityNum0/1")
    mon = c.decode_party_mon(raw)
    field = fixture._exp_derived()["ABILITY_NUM_FIELD"]
    shift = fixture._lane_shift(field, 8, 4)
    mask = ((1 << field["width"]) - 1) << shift
    mon["ribbons"] = (mon["ribbons"] & ~mask) | (2 << shift)
    result = c.encode_party_mon(mon)
    after = c.decode_party_mon_masked(result, layout=layout)
    if after["ability_num"] != 2 or not after["checksum_ok"]:
        raise ValueError("static Damp packed round-trip failed")
    if c.decode_party_mon(result)["ribbons"] & ~mask != c.decode_party_mon(raw)["ribbons"] & ~mask:
        raise ValueError("static Damp prep changed neighbouring ribbon bits")
    for key in before.keys() - {"ability_num", "checksum", "ribbons"}:
        if before[key] != after[key]:
            raise ValueError("static Damp prep changed " + key)
    return result


def build_seed(seed, case, rom):
    c = fixture.codec
    f = facts(rom, case)
    parsed = c.parse_flash(seed, title=c.TITLE_EXPANSION)
    if not c.qualify_flash(seed, title=c.TITLE_EXPANSION)[0]:
        raise ValueError("unqualified expansion base seed")
    sb1, sb2 = bytearray(parsed["sb1"]), bytearray(parsed["sb2"])
    count, party = c._TITLE_PARTY_OFFSETS[c.TITLE_EXPANSION]
    edits = []

    def flag(value, enabled):
        at, mask = f["flags_off"] + value // 8, 1 << (value % 8)
        sb1[at] = (sb1[at] | mask) if enabled else (sb1[at] & ~mask)
        edits.append(f"SYNTH flag {value:#x}={int(enabled)}")

    flag(f["flag"], False)
    if case.startswith("static"):
        flag(f["hide_static"], False)
    if case == "rock":
        flag(f["mirage_visible"], False)
        at = f["vars_off"] + 2 * (f["mirage_var"] - 0x4000)
        sb1[at:at + 2] = (3).to_bytes(2, "little")
        edits.append("SYNTH Mirage Tower resolved VAR3/visibleclear; native transition selects no-tower layout; avoids nonallowlisted pulse task")
    for b in f["badges"]:
        flag(b, True)
    data = json.loads((ROOT / "data/games/gen3_exp/28877d73/data.json").read_text())
    for slot in range(1):
        at = party + slot * 100
        mon = c.decode_party_mon(bytes(sb1[at : at + 100]))
        masked = c.decode_party_mon_masked(
            bytes(sb1[at : at + 100]), layout=fixture._record_layout(c.TITLE_EXPANSION)
        )
        species = data["species"][masked["species"]]
        if species["growthRate"] != 3:
            raise ValueError("fixture strength recipe is bounded to medium-slow base species")
        mon.update(level=100, experience=fixture._exp_medium_slow(100), status=0, unknown=0)
        stats = {
            key: species[field]
            for key, field in [
                ("hp", "baseHP"),
                ("attack", "baseAttack"),
                ("defense", "baseDefense"),
                ("speed", "baseSpeed"),
                ("sp_attack", "baseSpAttack"),
                ("sp_defense", "baseSpDefense"),
            ]
        }
        mon.update(fixture._gen3_stats(stats, mon, 100))
        mon["hp"] = mon["max_hp"]
        if slot == 0:
            mon["moves"][2:] = [f["surf_move"], f["rock_move"]]
            mon["pp"][2:] = [data["moves"][m]["pp"] for m in mon["moves"][2:]]
        if f["damp_slot"] is not None:
            if masked["species"] != 258 or species["abilities"] != [67, 0, f["damp_ability"]]:
                raise ValueError("static Damp prep requires own Mudkip hidden slot2")
            # battle_move_resolution.c:1585-1601 has no Damp config toggle: the per-move
            # dampBanned flag governs its native cancellation of Self-Destruct/Explosion.
            edits.append("SYNTH static lead abilityNum1->2 (Damp, hidden slot) in pack Misc abilityNum lane; native self-KO prevention only")
        record = c.encode_party_mon(mon)
        sb1[at : at + 100] = static_damp_record(record) if f["damp_slot"] is not None else record
    edits.append(
        "SYNTH own medium-slow party level100/full HP; slot0 Surf/Rock Smash with own-ROM PP; no battle forced"
    )
    key = (
        int.from_bytes(sb2[fixture.SB2_ENCRYPTION_KEY : fixture.SB2_ENCRYPTION_KEY + 4], "little")
        & 0xFFFF
    )
    pocket = fixture.SB1_BALL_POCKET_EMERALD
    # Keep the expansion helper's source-derived ITEM_POKE_BALL in native bag row0.
    ball_quantity = 1 if case in MASTER_CASES else 20
    sb1[pocket : pocket + 4] = struct.pack("<HH", f["ball_item"], ball_quantity ^ key)
    edits.append(f"SYNTH item add: row0 Ball item {f['ball_item']}, quantity{ball_quantity}; native throw pending")
    if case == "fish":
        registered = 0x496  # pinned global.h SaveBlock1.registeredItem (source offset)
        sb1[registered : registered + 2] = f["old_rod"].to_bytes(2, "little")
        # Registering alone is insufficient: append the rod to a free native key-item pocket slot.
        fields = profile.expansion_inputs()["facts"]["structs"]["SaveBlock1"]["fields"]
        bag = profile.expansion_inputs()["facts"]["structs"]["Bag"]["fields"]["keyItems"]
        key_offset = fields["bag"]["offset"] + bag["offset"]
        size = bag["size"]
        empty = next(
            at for at in range(key_offset, key_offset + size, 4) if sb1[at : at + 2] == b"\0\0"
        )
        sb1[empty : empty + 4] = struct.pack("<HH", f["old_rod"], 1 ^ key)
        edits.append("SYNTH own OLD_ROD registered and present in key pocket")
    at = f["vars_off"] + 2 * (0x403E - 0x4000)
    sb1[at : at + 2] = f["selector"].to_bytes(2, "little")
    x, y = f["x"], f["y"]
    sb1[:4] = struct.pack("<hh", x, y)
    warp = struct.pack("<bbbBhh", f["group"], f["num"], -1, 0, x, y)
    sb1[4:12] = sb1[12:20] = warp
    sb1[0x32:0x34] = f["layout_id"].to_bytes(2, "little")
    sb2[9] |= 1
    edits.append(
        f"SYNTH continue warp {f['group']}.{f['num']} ({x},{y}); selector{f['selector']}; acquisition pending"
    )
    result = fixture.exp_write_slot(
        {"sb1": bytes(sb1), "sb2": bytes(sb2), "storage": parsed["storage"]},
        counter=parsed["counter"],
    )
    if seed_problems(result, f):
        raise ValueError("invalid static/wild pending seed")
    return result, edits


def seed_problems(body, f):
    c = fixture.codec
    if not c.qualify_flash(body, title=c.TITLE_EXPANSION)[0]:
        return ["invalid sector set"]
    parsed = c.parse_flash(body, title=c.TITLE_EXPANSION)
    problems = []
    if struct.unpack_from("<hhbb", parsed["sb1"], 0) != (f["x"], f["y"], f["group"], f["num"]):
        problems.append("wrong pending tile/map")
    if f["case"].startswith("static") and parsed["sb1"][f["flags_off"] + f["flag"] // 8] & (
        1 << (f["flag"] % 8)
    ):
        problems.append("static already defeated")
    party = c.party_from_save(
        body, title=c.TITLE_EXPANSION, layout=fixture._record_layout(c.TITLE_EXPANSION)
    )
    if f["case"] == "rock":
        repel = f["vars_off"] + 2 * (f["repel_var"] - 0x4000)
        catalog = json.loads((ROOT/"data/games/gen3_exp/28877d73/data.json").read_text())
        if int.from_bytes(parsed["sb1"][repel:repel+2],"little") != 0:
            problems.append("SYNTH Rock eligibility requires no Repel steps")
        if catalog["species"][party[0]["species"]]["abilities"][party[0]["ability_num"]] == f["keen_eye_id"]:
            problems.append("SYNTH Rock eligibility requires no Keen Eye lead")
        off = f["vars_off"] + 2 * (f["mirage_var"] - 0x4000)
        if int.from_bytes(parsed["sb1"][off:off+2], "little") != 3 or parsed["sb1"][f["flags_off"] + f["mirage_visible"] // 8] & (1 << (f["mirage_visible"] % 8)):
            problems.append("Rock seed does not resolve/hide Mirage Tower")
        if not parsed["sb2"][9] & 1 and int.from_bytes(parsed["sb1"][0x32:0x34], "little") != f["no_tower_layout"]:
            problems.append("native Rock seed did not select source no-tower layout")
    if f["case"] in MASTER_CASES and sum(qty for item, qty in fixture.exp_ball_pocket(body) if item == f["ball_item"]) != 1:
        problems.append("positive static pending seed needs exactlyone own Master Ball")
    if f["case"].startswith("static") and (party[0]["species"] != 258 or party[0]["ability_num"] != f["damp_slot"]):
        problems.append("static pending lead lacks own hidden Damp slot2")
    if any(
        m["is_egg"] or m["is_bad_egg"] or not m["checksum_ok"] or m["hp"] != m["max_hp"]
        for m in party
    ):
        problems.append("party not ready")
    return problems


def build_full_box_seed(seed):
    """Disclosed SYNTH clones, using the pack storage offset and native encrypted codec."""
    c = fixture.codec
    parsed = c.parse_flash(seed, title=c.TITLE_EXPANSION)
    fields = profile.expansion_inputs()["facts"]["structs"]["PokemonStorage"]["fields"]["boxes"]
    if (fields["count"], fields["size"], fields["element_size"]) != (14, 14 * 30 * 80, 30 * 80):
        raise ValueError("full-box seed geometry moved")
    storage = bytearray(parsed["storage"])
    start = fields["offset"]
    original = c.decode_box_mon(bytes(storage[start:start + 80]))
    for index in range(14 * 30):
        mon = dict(original, personality=original["personality"] ^ (((index + 1) * 0x01001001) & 0xFFFFFFFF))
        storage[start + index * 80:start + (index + 1) * 80] = c.encode_box_mon(mon)
    return fixture.exp_write_slot({"sb1": parsed["sb1"], "sb2": parsed["sb2"],
                                   "storage": bytes(storage)}, counter=parsed["counter"])


def full_box_seed_problems(body):
    """Independent raw/decrypted occupancy proof, not a native deposit-refusal claim."""
    c = fixture.codec
    if not c.qualify_flash(body, title=c.TITLE_EXPANSION)[0]:
        return ["invalid full-box flash"]
    parsed = c.parse_flash(body, title=c.TITLE_EXPANSION)
    fields = profile.expansion_inputs()["facts"]["structs"]["PokemonStorage"]["fields"]["boxes"]
    records = [parsed["storage"][at:at + 80] for at in range(fields["offset"],
               fields["offset"] + fields["size"], 80)]
    decoded = [c.decode_box_mon_masked(raw, layout=fixture._record_layout(c.TITLE_EXPANSION)) for raw in records]
    if len(records) != 420 or len(set(records)) != 420 or len({(m["personality"], m["ot_id"]) for m in decoded}) != 420:
        return ["full-box records/identities are not exactly420 distinct"]
    if any(not m["checksum_ok"] or not m["species"] or m["is_egg"] or m["is_bad_egg"] for m in decoded):
        return ["full-box record invalid"]
    return []


def build_box0_full_seed(seed):
    """Keep a full box0 and an empty box1 for the same observer's positive sibling."""
    c = fixture.codec
    parsed = c.parse_flash(build_full_box_seed(seed), title=c.TITLE_EXPANSION)
    fields = profile.expansion_inputs()["facts"]["structs"]["PokemonStorage"]["fields"]["boxes"]
    storage = bytearray(parsed["storage"])
    off, stride = fields["offset"], fields["element_size"]
    storage[off + stride:off + fields["size"]] = bytes(fields["size"] - stride)
    return fixture.exp_write_slot({"sb1": parsed["sb1"], "sb2": parsed["sb2"],
                                   "storage": bytes(storage)}, counter=parsed["counter"])


def box0_full_seed_problems(body):
    c = fixture.codec
    if not c.qualify_flash(body, title=c.TITLE_EXPANSION)[0]:
        return ["invalid box0-full flash"]
    parsed = c.parse_flash(body, title=c.TITLE_EXPANSION)
    fields = profile.expansion_inputs()["facts"]["structs"]["PokemonStorage"]["fields"]["boxes"]
    at, size = fields["offset"], fields["element_size"]
    raw = [parsed["storage"][pos:pos + 80] for pos in range(at, at + size, 80)]
    decoded = [c.decode_box_mon_masked(record, layout=fixture._record_layout(c.TITLE_EXPANSION)) for record in raw]
    if len(raw) != 30 or len(set(raw)) != 30 or len({(m["personality"], m["ot_id"]) for m in decoded}) != 30:
        return ["box0 identities/records are not exactly30 distinct"]
    if any(not m["checksum_ok"] or not m["species"] or m["is_egg"] or m["is_bad_egg"] for m in decoded):
        return ["box0 record invalid"]
    if any(parsed["storage"][at + size:at + fields["size"]]):
        return ["boxes1..13 must be empty for the native positive sibling"]
    return []


def own_facts(run, inst):
    cache = run.__dict__.setdefault("_static_wild_facts", {})
    if inst not in cache:
        if run._gen3_title(inst) != "emerald_expansion_28877d73":
            raise ValueError("static/wild carrier requires expansion")
        cache[inst] = facts((ROOT / run._gen3_rom(inst)).read_bytes(), run.cfg["static_wild_case"])
    return cache[inst]


def trace_problems(text, f):
    """Check Lua's native battle and production wire receipt before saved readback."""
    from tools.gen3_clause_rows import one, rows
    from tools.gen3_gift_egg_rows import tx_messages

    problems = []
    case = f["case"]
    if case == "rock":
        rng = rows(text, "SYNTH_ROCK_RNG_PREP")
        if len(rng) != 1 or rng[0].get("address") != f["rock_rng_address"] or rng[0].get("state_hex") != f["rock_rng_state_hex"]:
            problems.append("missing or mismatched one-shot SYNTH Rock RNG precondition")
        draws = rows(text, "SYNTH_ROCK_RNG_DRAW")
        if [(d.get("phase"),d.get("draw"),d.get("counter")) for d in draws] != [
                ("before",1,17),("after",1,18),("before",2,18),("after",2,19)]:
            problems.append("native Rock RNG counters do not prove exactlytwo un-leaked draws")
        elif ((draws[1].get("result",0) >> 16) % f["rock_rng_modulus"]) >= f["rock_encounter_rate"] * 16:
            problems.append("native first Rock RNG draw did not meet own encounter odds")
    before = one(text, "STATIC_WILD_BEFORE")
    battle = one(text, "STATIC_WILD_BATTLE")
    after = one(text, "STATIC_WILD_AFTER")
    captures = tx_messages(text, "capture")
    misses = tx_messages(text, "no_catch")
    if before.get("captures") != 0 or before.get("no_catch") != 0:
        problems.append("fixture had prior capture/no_catch")
    if battle.get("method") != f["method"] or not any(
        lo <= battle.get("level", -1) <= hi and battle.get("species") == species
        for lo, hi, species in f["slots"]
    ):
        problems.append("native battle species/level differs from compiled method slots")
    if "selector" in f and battle.get("selector") != f["selector"]:
        problems.append("observed selector differs from pending fixture")
    if battle.get("field_probe") is not True:
        problems.append("native method entry was not observed")
    if case == "static_run":
        if captures or len(misses) != 1 or after.get("balls") != before.get("balls"):
            problems.append("RUN must send one no_catch, no capture, no Ball debit")
        if len(misses) == 1 and (misses[0].get("area_id"), misses[0].get("species_id"), misses[0].get("level")) != (f["area"], battle.get("species"), battle.get("level")):
            problems.append("RUN no_catch differs from observed native foe/area")
    else:
        if (
            len(captures) != 1
            or misses
            or captures[0].get("area_id") != f["area"]
            or captures[0].get("gift") is True
        ):
            problems.append("expected one ordinary area capture")
        if len(captures) == 1 and (captures[0].get("species_id"), captures[0].get("level")) != (battle.get("species"), battle.get("level")):
            problems.append("capture species/level differs from observed native foe")
        if (
            after.get("balls") is None
            or before.get("balls") is None
            or after["balls"] >= before["balls"]
        ):
            problems.append("native Ball debit missing")
    if any(tx_messages(text, kind) for kind in ("key_change", "faint")):
        problems.append("unexpected identity/faint event")
    if len(re.findall(r"^TX capture ", text, re.M)) != len(captures) or len(
        re.findall(r"^TX no_catch ", text, re.M)
    ) != len(misses):
        problems.append("malformed raw production capture/no_catch")
    return problems


def orchestrate(run):
    from tools.gen3_clause_rows import one

    run._gen3_prelude()
    for inst in "ab":
        own_facts(run, inst)
    run.go()
    run._static_wild_caps = {}
    for inst in "ab":
        marker = run._gen3_mark(inst, r"^STATIC_WILD_READY (\{.*\})$", "native encounter settled")
        run._static_wild_caps[inst] = one(
            "STATIC_WILD_READY " + marker.group(1), "STATIC_WILD_READY"
        )
    if run.cfg["static_wild_case"] != "static_run":
        run._link_keys = {i: cap["key"] for i, cap in run._static_wild_caps.items()}
        run.wait_for(
            "one native static/wild link",
            lambda: any(
                all((row.get(i) or {}).get("key") == run._link_keys[i] for i in "ab")
                and row.get("status") == "alive"
                for row in run._links_json()
            ),
            120,
        )
    for inst in "ab":
        run._append_reconnect_marker(inst, "SAVE")


def party_control_problems(old_party, party, f, battle):
    import e2e_duo as h

    problems = []
    for slot, old in enumerate(old_party):
        now = next((mon for mon in party if h.gen3_key(mon) == h.gen3_key(old)), None)
        # Native battles alter health/PP; captures grant exact SOURCE EV yields to the lead.
        mutable = {"hp", "status", "pp", "friendship", "checksum", "unknown", "evs"}
        expected_evs = dict(old["evs"])
        if slot == 0 and f["case"] != "static_run":
            # Bounded seeds: only the level100 lead participates; no item/Pokerus multiplier.
            if old["level"] != 100 or old["held_item"] or old["pokerus"] or any(old["evs"].values()):
                problems.append("unsupported capture-reward seed")
            for stat, gain in f["ev_yields"][battle["species"]].items():
                expected_evs[stat] += gain
        if now is not None and now["evs"] != expected_evs:
            problems.append("party EVs differ from exact native capture reward")
        if now is None or h.gen3_record_diff(old, now, False, mutable=mutable):
            problems.append("unrelated party control changed")
        elif now:
            if (
                not 0 < now["hp"] <= now["max_hp"]
                or now["hp"] > old["hp"]
                or any(n > o for n, o in zip(now["pp"], old["pp"], strict=True))
            ):
                problems.append("native health/PP bound exceeded")
            if now["unknown"] & 0x3FFF != now["max_hp"] - now["hp"]:
                problems.append("expansion hpLost does not equal native damage")
    return problems


def negative_ledger_problems(document, f, battles):
    """Native no_catch creates one area-lock sentinel, never a formed pair.

    SOURCE state.py:3000-3001,3110-3125; reuse e2e_duo.is_formed_link, also used
    by its vanilla poison oracle. Whichever side sends first owns the sentinel.
    """
    from tools.e2e_duo import is_formed_link

    links = document.get("links") or []
    if len(links) != 1 or any(is_formed_link(row) for row in links):
        return ["RUN ledger must contain one dead-zone sentinel and no formed pair"]
    row = links[0]
    side = row.get("initiating_player")
    if (row.get("status"), row.get("cause"), row.get("area_id"), row.get("a"), row.get("b")) != (
            "dead", "dead_zone", f["area"], None, None) or side not in ("a", "b"):
        return ["RUN ledger differs from native empty-member area-lock shape"]
    encounter = row.get("encounter_" + side) or {}
    foe = battles[side]
    if (encounter.get("key"), encounter.get("species"), encounter.get("level")) != (
            "", foe["species"], foe["level"]) or row.get("encounter_" + ("b" if side == "a" else "a")) is not None:
        return ["RUN sentinel encounter differs from the initiating native foe"]
    if document.get("area_states", {}).get(f["area"]) != "dead_zone" or document.get("pending_captures"):
        return ["RUN persisted area lock/pending captures are inconsistent"]
    return []


def master_bag_problems(before, after, master):
    from collections import Counter

    def counts(body):
        out = Counter()
        for item, qty in fixture.exp_ball_pocket(body):
            if item:
                out[item] += qty
        return out
    was, now = counts(before), counts(after)
    if was[master] != 1 or now[master] != 0:
        return ["saved Master Ball must debit exactly1->0"]
    was.pop(master, None)
    now.pop(master, None)
    if was != now:
        return ["another saved Ball item/quantity changed"]
    return []


def saved_oracle(run, results):
    import e2e_duo as h

    from tools import gen3_fixtures as fixture
    from tools.gen3_gift_egg_rows import saved_records, tx_messages

    run._gen3_flush_boundary()
    problems, keys = [], {}
    negative = run.cfg["static_wild_case"] == "static_run"
    for inst in "ab":
        f, text = own_facts(run, inst), results[inst]
        problems += [f"{inst}: {p}" for p in trace_problems(text, f)]
        party, boxes = run._gen3_saved(inst)
        old_party, old_boxes = run._gen3_fixture_saved(inst)
        captures = tx_messages(text, "capture")
        key = keys[inst] = captures[0].get("key") if captures else None
        found = (
            [mon for mon in saved_records(party, boxes) if h.gen3_key(mon) == key] if key else []
        )
        if f["case"] in MASTER_CASES:
            problems += [f"{inst}: {p}" for p in master_bag_problems(run._gen3_fixture_bytes(inst), run._gen3_flushed(inst), f["ball_item"])]
            if found and found[0]["pokeball"] != f["ball_id"]:
                problems.append(f"{inst}: saved capture is not in own BALL_MASTER")
        if not negative and len(found) != 1:
            problems.append(
                f"{inst}: captured key missing or duplicated in independently saved flash"
            )
        if not negative:
            problems += h.gen3_capture_problems(inst, (party, boxes), (old_party, old_boxes),
                                               key, sent=captures[0] if captures else None,
                                               limits=run._gen3_limits(inst))
        from tools.gen3_clause_rows import one
        problems += [f"{inst}: {p}" for p in party_control_problems(
            old_party, party, f, one(text, "STATIC_WILD_BATTLE")
        )]
        if {pos: mon for pos, mon in boxes.items() if h.gen3_key(mon) != key} != old_boxes:
            problems.append(f"{inst}: unrelated box control changed")
        if not fixture.codec.qualify_flash(
            run._gen3_flushed(inst), title=fixture.codec.TITLE_EXPANSION
        )[0]:
            problems.append(f"{inst}: native saved flash invalid")
        saved_sb1 = fixture.codec.parse_flash(run._gen3_flushed(inst), title=fixture.codec.TITLE_EXPANSION)["sb1"]
        if int.from_bytes(saved_sb1[f["vars_off"] + 2 * (f["selector_var"] - 0x4000):f["vars_off"] + 2 * (f["selector_var"] - 0x4000) + 2], "little") != f["selector"]:
            problems.append(f"{inst}: selector changed in independently saved flash")
        if f["case"].startswith("static"):
            sb1 = fixture.codec.parse_flash(
                run._gen3_flushed(inst), title=fixture.codec.TITLE_EXPANSION
            )["sb1"]
            if not sb1[f["flags_off"] + f["flag"] // 8] & (1 << (f["flag"] % 8)):
                problems.append(f"{inst}: static defeat/removal flag not persisted")
    if negative:
        from tools.gen3_clause_rows import one
        problems += negative_ledger_problems(run._reconnect_document(), own_facts(run, "a"),
                                            {i: one(results[i], "STATIC_WILD_BATTLE") for i in "ab"})
    else:
        run._link_keys = keys
        link = run._gen3_one_link("alive")
        if (
            link.get("area_id") != own_facts(run, "a")["area"]
            or any((link.get(i) or {}).get("key") != keys[i] for i in "ab")
            or len(run._links_json()) != 1
        ):
            problems.append("ordinary capture pair/area differs from saved keys")
    if problems:
        raise RuntimeError("; ".join(problems))
    run._pydec_note(
        "static RUN: native no_catch, exact persisted dead-zone sentinel/no formed pairs, saved controls"
        if negative else "exp static/wild: native battle, ordinary capture, independent saved keys and controls"
    )


def main():
    import argparse
    import uuid

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, required=True)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--qualify", action="store_true")
    args = parser.parse_args()
    rom = profile.expansion_inputs()["rom"]
    seed = args.seed.read_bytes()
    prepared, edits = build_seed(seed, args.case, rom)
    print("\n".join(edits))
    if not args.qualify:
        args.out.write_bytes(prepared)
        return 0
    f = facts(rom, args.case)
    title = fixture.codec.TITLE_EXPANSION
    before = fixture.qualify_one(prepared, rr=False, title=title)
    name = "exp_static_wild_" + args.case + "_" + uuid.uuid4().hex[:8]
    staged, run, battery = fixture._prepare_run(
        name,
        str(ROOT / ".cache/expansion-output/reference/pokeemerald.gba"),
        seed=prepared,
        saveram_name_override=None,
    )
    ok, text = fixture._launch(
        fixture.EMERALD_BOOT_LUA,
        staged,
        run,
        rr=False,
        timeout=300,
        title=title,
        extra_env={
            "SLINK_BOOT_SYM": str(ROOT / ".cache/expansion-output/reference/pokeemerald.sym")
        },
    )
    print(text)
    flushed = fixture._flushed_saveram(run, battery)
    if not ok or flushed is None:
        print("FAIL native pending-seed save")
        return 1
    body = fixture.import_savedata(flushed.read_bytes(), rr=False, title=title)
    after = fixture.qualify_one(body, rr=False, title=title)
    problems = fixture.boot_check_verdict(before, after)[1] + seed_problems(body, f)
    if problems:
        print("FAIL " + "; ".join(problems))
        return 1
    args.out.write_bytes(body)
    print(
        f"SEED_PENDING PASS case={args.case} counter={before['counter']}->{after['counter']} file={args.out} sha256={hashlib.sha256(body).hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
