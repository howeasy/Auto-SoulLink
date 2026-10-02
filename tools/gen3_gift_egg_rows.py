"""GIFT-EGG-ROWS-G3: own-ROM gift facts, disclosed SYNTH setup, native-row oracle.

No emulator entrypoint. Run this module to prepare a seed, then e2e_duo.py runs
ordinary buttons against the production client. Pins are SOURCE, tests MODEL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Independently read map object #2 scripts (first 0x120 bytes), each title's ROM.
# RR's salesman flag is 098E, not vanilla's 0249. See the card evidence document.
GIFTS = {
    "firered": {"groups": 0x083526A8, "group": 16, "num": 0, "x": 1, "y": 4, "face": "Up", "species": 129,
                    "flag": 0x249, "price": 500, "script": 0x0816F75F,
                    "sha256": "c2d6ad6fe7561024485dc49028154a92bcdb889e6363aed66ad0c522dac528e5"},
    "leafgreen": {"groups": 0x08352688, "group": 16, "num": 0, "x": 1, "y": 4, "face": "Up", "species": 129,
                      "flag": 0x249, "price": 500, "script": 0x0816F73B,
                      "sha256": "30e8c3b99a996d2f5b5c3e1a099de68b9aef6eda58d224326fa4fd0dc248c354"},
    "radical_red": {"groups": 0x083526A8, "group": 16, "num": 0, "x": 1, "y": 4, "face": "Up", "species": 129,
                        "flag": 0x98E, "price": 500, "script": 0x0904C03D,
                        "sha256": "18cbbec6fcaf175b6c421ba15c221006d9f00bff838a6d6cdbfce9a7825ac169"},
    "emerald": {"groups": 0x08486578, "group": 14, "num": 7, "x": 3, "y": 3, "face": "Right", "species": 398,
                    "flag": 0x12A, "price": 0, "script": 0x08222841,
                    "sha256": "f50718631bda0e4b07ef094a978b729c94021b6d69091ba6170f97d8d354f7ce"},
}
HATCH_CALLBACKS = {"firered": 0x08047338, "leafgreen": 0x08047338,
                   "emerald": 0x08071A94, "radical_red": 0x08047338}
# Source review and independent ROM reads: callback entry (do not borrow RR from FR).
HATCH_ENTRIES = {"firered": "70b556464d46444670b483b005490868",
                 "leafgreen": "70b556464d46444670b483b005490868",
                 "radical_red": "70b556464d46444670b483b005490868",
                 "emerald": "f0b54f464646c0b482b0064908688078"}


def title_facts(rom: bytes, title: str) -> dict:
    """Fail closed on changed script/callback/geometry; no cross-title fallback."""
    if title == "emerald_expansion_28877d73":
        return expansion_facts(rom)
    from tools.gba_map import Rom
    f = dict(GIFTS[title])
    def u32(address):
        return struct.unpack_from("<I", rom, address - 0x08000000)[0]
    header = u32(u32(f["groups"] + f["group"] * 4) + f["num"] * 4)
    events = u32(header + 4)
    obj = u32(events + 4) + 24  # object #2: seller / Beldum ball
    script = u32(obj + 16)
    body = rom[script - 0x08000000:script - 0x08000000 + 0x120]
    if script != f["script"] or hashlib.sha256(body).hexdigest() != f["sha256"]:
        raise ValueError(f"{title}: native gift script is not the reviewed own-title script")
    cb = HATCH_CALLBACKS[title]
    if rom[cb - 0x08000000:cb - 0x08000000 + 16].hex() != HATCH_ENTRIES[title]:
        raise ValueError(f"{title}: unproven hatch scene callback")
    # RR replaces CreatedHatchedMon: its CreateMon R2 is 1, not pret's 5.
    # Pinned own-ROM detour, body (including literal CreateMon 0803DA55),
    # and native step checker; never infer these from the vanilla tail.
    if title == "radical_red" and (
            rom[0x46BFC:0x46C04].hex() != "004a1047f1810809"
            or hashlib.sha256(rom[0x10881F0:0x10883C0]).hexdigest()
            != "1206ca4d7cb5687238bf477e72efc10dfa7544edd43690248d77b6f388443aaa"
            or hashlib.sha256(rom[0x462C4:0x463B8]).hexdigest()
            != "88292d690f32ec15db715eec386e4676430afd080dab098436da2e70a40100a8"):
        raise ValueError("radical_red: unproven native hatch producer")
    if title == "radical_red":
        from server.adapters import gen3_codec as c
        # RR GetFlagAddr is detoured: flags 0900..18FF live in the parasite
        # bank, NOT beyond vanilla SB1.flags into its vars. Own-ROM literals
        # at 090B8FE4/E8/EC are -0900, 0FFF, 0203B174.
        if (rom[0x6E5C0:0x6E5C8].hex() != "00490847ed2d0409"
                or hashlib.sha256(rom[0x1042DEC:0x1042E08]).hexdigest()
                != "ca504fdf0b1e99f32b92d97f3a9e5df8a9ddafad620880becc1e0cb97e99f42f"
                or hashlib.sha256(rom[0x10B8FB0:0x10B9000]).hexdigest()
                != "c48b525b7e735bd36b4590bc40436097cdebdc29bc9ee09663803caab371fca6"):
            raise ValueError("radical_red: unproven extended gift flag bank")
        c.verify_rr_save_layout_rom(rom)
        f.update(flag_address=c.RR_PARASITE_ADDR + (f["flag"] - 0x900) // 8,
                 flag_mask=1 << (f["flag"] % 8))
    m = Rom(rom, f["groups"], game="emerald" if title == "emerald" else "fr").map(f["group"], f["num"])
    # The gift stand is immediately next to its object. The hatch walk is two
    # adjacent indoor, non-warp, non-grass tiles, clear of every object's range.
    hx, hy = (3, 5) if title == "emerald" else (3, 6)
    for x, y in ((f["x"], f["y"]), (hx, hy), (hx + 1, hy)):
        if m.collision[y][x] != 0 or m.behaviour[y][x] in (2, 3):
            raise ValueError(f"{title}: source tile {x},{y} not safe")
    area_file = "gen3_emerald" if title == "emerald" else "gen3_frlge"
    area = json.loads((ROOT / f"data/games/{area_file}/area_map.json").read_text())[f"{f['group']}:{f['num']}"]
    f.update(area=area, hatch_x=hx, hatch_y=hy, hatch_callback=cb, level=5,
             hatch_level=1 if title == "radical_red" else 5)
    return f


EXP_CASES = ("gift", "hatch", "egg_receive", "choice_gift", "gift_box")


def expansion_facts(rom: bytes, case="gift", side="a") -> dict:
    """Own-build script/event bindings; offsets are the pinned global.fieldmap.h layout."""
    from tools import gen3_fixtures as fixture, gen_gen3_profile as p
    from tools.gba_map import Rom
    from tools.gen_gen3_exp_trainers import enum_values
    from tools.gen_gen3_trainers import map_keys

    if case not in EXP_CASES:
        raise ValueError(f"unknown expansion acquisition case {case}")
    context = p.expansion_inputs()
    if hashlib.sha1(rom).hexdigest() != context["facts"]["provenance"]["rom_sha1"]:
        raise ValueError("expansion acquisition ROM identity mismatch")
    src = fixture.expansion_src()
    if subprocess_head(src) != context["facts"]["provenance"]["source_commit"]:
        raise ValueError("expansion acquisition source pin mismatch")
    def define(file, name):
        match = re.search(r"^#define\s+" + name + r"\s+(0x[0-9A-Fa-f]+|\d+)\b",
                          (src / "include/constants" / file).read_text(), re.M)
        if not match:
            raise ValueError(f"unresolved own-source constant {name}")
        return int(match[1], 0)
    def symbol(name):
        return p.expansion_symbol(context, name)
    def u32(address):
        return struct.unpack_from("<I", rom, address - 0x08000000)[0]
    if case == "egg_receive":
        map_name, script, species, level, x, y, face, flag_name = (
            "LavaridgeTown", "LavaridgeTown_EventScript_EggWoman", "SPECIES_WYNAUT", 1,
            4, 8, "Up", "FLAG_RECEIVED_LAVARIDGE_EGG")
    elif case == "choice_gift":
        map_name, script, species, level, x, y, face, flag_name = (
            "RustboroCity_DevonCorp_2F", "RustboroCity_DevonCorp_2F_EventScript_FossilScientist",
            "SPECIES_LILEEP" if side == "a" else "SPECIES_ANORITH", 20,
            13, 8, "Right", "FLAG_RECEIVED_REVIVED_FOSSIL_MON")
    else:
        map_name, script, species, level, x, y, face, flag_name = (
            "MossdeepCity_StevensHouse", "MossdeepCity_StevensHouse_EventScript_BeldumPokeball",
            "SPECIES_BELDUM", 5, 3, 3, "Right", "FLAG_RECEIVED_BELDUM")
    doc = json.loads((src / "data/maps" / map_name / "map.json").read_text())
    group, num = map(int, map_keys(src)[doc["id"]].split(":"))
    groups = symbol("gMapGroups")["address"]
    header = u32(u32(groups + group * 4) + num * 4)
    events = u32(header + 4)
    objects = u32(events + 4)
    index, obj = next((i, o) for i, o in enumerate(doc["object_events"]) if o["script"] == script)
    ptr = symbol(script)["address"]
    if u32(objects + index * 24 + 16) != ptr:
        raise ValueError("expansion NPC compiled script pointer differs from source")
    coord = struct.unpack_from("<hh", rom, objects - 0x08000000 + index * 24 + 4)
    if coord != (obj["x"], obj["y"]):
        raise ValueError("expansion NPC compiled coordinates differ from source")
    geometry = Rom(rom, groups, game="emerald").map(group, num)
    hx, hy = 3, 5
    points = [(x, y)] if case != "hatch" else [(hx, hy), (hx + 1, hy)]
    for px, py in points:
        if geometry.collision[py][px] != 0 or geometry.behaviour[py][px] in (2, 3):
            raise ValueError(f"unsafe acquisition tile {px},{py}")
        if any((o.x, o.y) == (px, py) for o in geometry.objects):
            raise ValueError("acquisition tile occupied by NPC")
    profile = json.loads((ROOT / "data/games/gen3_exp/28877d73/profile.json").read_text())
    d = profile["titles"]["emerald_expansion_28877d73"]["derived"]
    ids = enum_values((src / "include/constants/species.h").read_text(), "SPECIES_")
    areas = json.loads((ROOT / "data/games/gen3_exp/28877d73/area_map.json").read_text())
    sites = json.loads((ROOT / "data/games/gen3_exp/28877d73/engine_signals.json").read_text())["titles"][
        "emerald_expansion_28877d73"]["artifacts"]["clean"]["sites"]
    return {"title": "emerald_expansion_28877d73", "case": case, "map": map_name,
            "probes": ([{"name": name + ("_mirror" if delta else "_canonical_silence_control"),
                         "address": symbol(name)["address"] + delta}
                        for name in ("ScrCmd_createmon", "ScriptGiveMonParameterized", "GiveScriptedMonToPlayer")
                        for delta in (0, *sites["mon_given"].get("mirror_offsets", []))]
                       if os.environ.get("SLINK_EXP_ACQ_PROBES") == "1" else []),
            "group": group, "num": num, "x": hx if case == "hatch" else x,
            "y": hy if case == "hatch" else y, "face": face,
            "hatch_x": hx, "hatch_y": hy, "hatch_callback": symbol("CB2_EggHatch")["address"],
            "hatch_level": 1, "egg_cycle_steps": 128, "species": ids[species], "level": level,
            "area": areas[f"{group}:{num}"], "flag": define("flags.h", flag_name), "price": 0,
            "layout_id": struct.unpack_from("<H", rom, header - 0x08000000 + 18)[0],
            "flags_off": d["SB1_FLAGS_OFFSET"], "vars_off": d["SB1_VARS_OFFSET"],
            "hide_beldum": define("flags.h", "FLAG_HIDE_MOSSDEEP_CITY_STEVENS_HOUSE_BELDUM_POKEBALL"),
            "hide_steven": define("flags.h", "FLAG_HIDE_MOSSDEEP_CITY_STEVENS_HOUSE_STEVEN"),
            "hide_ninja": define("flags.h", "FLAG_HIDE_MOSSDEEP_CITY_STEVENS_HOUSE_INVISIBLE_NINJA_BOY"),
            "steven_var": define("vars.h", "VAR_STEVENS_HOUSE_STATE"),
            "fossil_var": define("vars.h", "VAR_FOSSIL_RESURRECTION_STATE"),
            "which_fossil_var": define("vars.h", "VAR_WHICH_FOSSIL_REVIVED"),
            "script": ptr, "script_sha256": hashlib.sha256(
                rom[ptr - 0x08000000:ptr - 0x08000000 + symbol(script)["size"]]).hexdigest(),
            "source": "e8bd1cd7 global.fieldmap.h:111-243 + own map.json/script/symbols"}


def subprocess_head(path):
    import subprocess
    dirty = subprocess.check_output(["git", "-C", str(path), "status", "--porcelain",
                                     "--untracked-files=no"], text=True)
    if dirty:
        raise ValueError("expansion acquisition source is dirty")
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def build_exp_seed(seed: bytes, case: str, rom: bytes, side="a") -> tuple[bytes, list[str]]:
    """Offline setup edits only, expansion slot writer and raw-packed record round trips."""
    from tools import gen3_fixtures as f
    c = f.codec
    facts = expansion_facts(rom, case, side)
    if not c.qualify_flash(seed, title=c.TITLE_EXPANSION)[0]:
        raise ValueError("expansion acquisition seed does not qualify")
    parsed = c.parse_flash(seed, title=c.TITLE_EXPANSION)
    sb1, sb2 = bytearray(parsed["sb1"]), bytearray(parsed["sb2"])
    count, party = c._TITLE_PARTY_OFFSETS[c.TITLE_EXPANSION]
    raw_lead = bytes(sb1[party:party + c.PARTY_MON_SIZE])
    lead = c.decode_party_mon(raw_lead)
    if not lead["hp"] or lead["is_egg"] or lead["ot_id"] != int.from_bytes(sb2[10:14], "little"):
        raise ValueError("acquisition seed needs an own healthy non-egg lead")
    edits = []
    def flag(value, enabled):
        at, mask = facts["flags_off"] + value // 8, 1 << (value % 8)
        sb1[at] = (sb1[at] | mask) if enabled else (sb1[at] & ~mask)
        edits.append(f"SYNTH flag {value:#x}={int(enabled)}")
    def var(value, number):
        at = facts["vars_off"] + 2 * (value - 0x4000)
        sb1[at:at + 2] = number.to_bytes(2, "little")
        edits.append(f"SYNTH var {value:#x}={number}")
    flag(facts["flag"], False)
    if facts["map"] == "MossdeepCity_StevensHouse":
        flag(facts["hide_beldum"], False)
        flag(facts["hide_steven"], True)
        flag(facts["hide_ninja"], True)
        var(facts["steven_var"], 0)
    if case == "choice_gift":
        var(facts["fossil_var"], 2)
        var(facts["which_fossil_var"], 1 if side == "a" else 2)
    if case == "hatch":
        from tools import gen_gen3_profile as p

        egg = c.decode_party_mon(raw_lead)
        native_species = c.decode_party_mon_masked(raw_lead, layout=f._record_layout(c.TITLE_EXPANSION))["species"]
        growth = json.loads((ROOT / "data/games/gen3_exp/28877d73/data.json").read_text())["species"][native_species]["growthRate"]
        context = p.expansion_inputs()
        exp_table = p.expansion_symbol(context, "gExperienceTables")["address"]
        # Pinned experience_tables.h [MAX_LEVEL+1=101], read the level-1 word from ROM.
        hatch_exp = struct.unpack_from("<I",rom,exp_table-0x08000000+4*(growth*101+1))[0]
        egg.update(personality=egg["personality"] ^ 0x24682468, is_egg=1, is_egg_flag=1,
                   friendship=0, nickname="EGG", held_item=0, status=0, level=1, experience=hatch_exp)
        egg.pop("nickname_raw", None)
        sb1[count] = 2
        sb1[party + 100:party + 200] = c.encode_party_mon(egg)
        sb1[party + 200:party + 600] = bytes(400)
        edits.append(f"SYNTH own-lead-species egg in slot1; cycles0, level1 EXP{hatch_exp} from own ROM growth table; native step counter unchanged")
    if case == "gift_box":
        for slot in range(2, 6):
            mon = c.decode_party_mon(raw_lead)
            mon["personality"] ^= 0x100001 * (slot + 1)
            sb1[party + slot * 100:party + (slot + 1) * 100] = c.encode_party_mon(mon)
        sb1[count] = 6
        edits.append("SYNTH party filled with four uniquely-keyed healthy own-lead clones; boxes unchanged")
    x, y = facts["x"], facts["y"]
    sb1[0:4] = struct.pack("<hh", x, y)
    warp = struct.pack("<bbbBhh", facts["group"], facts["num"], -1, 0, x, y)
    sb1[4:12] = sb1[12:20] = warp
    sb1[0x32:0x34] = facts["layout_id"].to_bytes(2, "little")
    sb2[9] |= 1
    edits.append(f"SYNTH continue warp {facts['group']}.{facts['num']} ({x},{y}); {case} pending")
    body = f.exp_write_slot({"sb1": bytes(sb1), "sb2": bytes(sb2), "storage": parsed["storage"]},
                            counter=parsed["counter"])
    problems = exp_seed_problems(body, facts)
    if problems:
        raise ValueError("; ".join(problems))
    return body, edits


def exp_seed_problems(body, facts):
    from tools import gen3_fixtures as f
    c, problems = f.codec, []
    if not c.qualify_flash(body, title=c.TITLE_EXPANSION)[0]:
        return ["expansion seed/save fails qualification"]
    parsed = c.parse_flash(body, title=c.TITLE_EXPANSION)
    party = c.party_from_save(body, title=c.TITLE_EXPANSION, layout=f._record_layout(c.TITLE_EXPANSION))
    if struct.unpack_from("<hhbb", parsed["sb1"], 0) != (facts["x"], facts["y"], facts["group"], facts["num"]):
        problems.append("wrong acquisition location")
    if int.from_bytes(parsed["sb1"][0x32:0x34], "little") != facts["layout_id"]:
        problems.append("wrong map layout id")
    if parsed["sb1"][facts["flags_off"] + facts["flag"] // 8] & (1 << (facts["flag"] % 8)):
        problems.append("acquisition already received")
    if facts["case"] == "hatch" and (len(party) != 2 or not party[1]["is_egg"] or party[1]["friendship"] != 0):
        problems.append("near-hatch egg absent")
    if facts["case"] == "gift_box" and len(party) != 6:
        problems.append("boxed gift seed party is not full")
    if any(not mon["checksum_ok"] or mon["is_bad_egg"] for mon in party):
        problems.append("invalid party record")
    return problems


def own_facts(run, inst):
    cache = run.__dict__.setdefault("_acquisition_facts", {})
    if inst not in cache:
        rom = (ROOT / run._gen3_rom(inst)).read_bytes()
        cache[inst] = (expansion_facts(rom, run.cfg.get("acquisition_case", run.cfg["acquisition_kind"]), inst)
                      if run._gen3_title(inst) == "emerald_expansion_28877d73" else
                      title_facts(rom, run._gen3_title(inst)))
    return cache[inst]


def rr_gift_flag_offset(parsed, flag):
    """Own-ROM flag bank, first parasite piece; never treat it as SB1 vars."""
    from server.adapters import gen3_codec as c
    if not 0x900 <= flag < 0x900 + c.RR_PARASITE_PIECES[0] * 8:
        raise ValueError("gift flag outside the proven first RR parasite piece")
    section = next(s for s in parsed["sectors"][14 * parsed["slot"]:14 * (parsed["slot"] + 1)] if s["id"] == 0)
    return section["index"] * c.SECTOR_SIZE + c.RR_CHUNK_TABLE[0][1] + (flag - 0x900) // 8


def saved_gift_flag(image, title, facts):
    from server.adapters import gen3_codec as c
    if title == "emerald_expansion_28877d73":
        p = c.parse_flash(image, title=c.TITLE_EXPANSION)
        return bool(p["sb1"][facts["flags_off"] + facts["flag"] // 8] & (1 << (facts["flag"] % 8)))
    p = c.parse_flash(image, cfru=title == "radical_red", title="emerald" if title == "emerald" else "frlg")
    if title == "radical_red":
        return bool(image[rr_gift_flag_offset(p, facts["flag"])] & facts["flag_mask"])
    base = 0x1270 if title == "emerald" else 0xEE0
    return bool(p["sb1"][base + facts["flag"] // 8] & (1 << (facts["flag"] % 8)))


def build_seed(seed: bytes, title: str, kind: str, rom: bytes) -> tuple[bytes, list[str]]:
    """Offline setup only; no gift receipt, hatch, or server link is fabricated."""
    from server.adapters import gen3_codec as c
    from tools import gen3_fixtures as fixture
    if kind not in ("gift", "hatch"):
        raise ValueError(f"unknown acquisition kind {kind}")
    facts = title_facts(rom, title)
    rr, emerald = title == "radical_red", title == "emerald"
    layout_title = "emerald" if emerald else "frlg"
    ok, why = c.qualify_flash(seed, cfru=rr, title=layout_title)
    if not ok:
        raise ValueError(f"unqualified seed: {why}")
    parsed = c.parse_flash(seed, cfru=rr, title=layout_title)
    sb1, sb2 = bytearray(parsed["sb1"]), bytearray(parsed["sb2"])
    party = c.rr_party_from_save(seed) if rr else c.party_from_save(seed, title=layout_title)
    if not party or not 0 < party[0]["hp"] <= party[0]["max_hp"] or party[0]["is_egg"]:
        raise ValueError("seed requires a healthy non-egg lead")
    own = int.from_bytes(sb2[10:14], "little")
    if party[0]["ot_id"] != own:
        raise ValueError("seed lead is not player-owned")
    count_at, party_at = (c.SB1_PARTY_COUNT_OFFSET_EMERALD, c.SB1_PARTY_OFFSET_EMERALD) if emerald else (
        c.SB1_PARTY_COUNT_OFFSET, c.SB1_PARTY_OFFSET)
    flags = 0x1270 if emerald else 0xEE0
    changes, extended_flag_patch = [], None
    def flag(value, enabled):
        at, mask = flags + value // 8, 1 << (value % 8)
        sb1[at] = (sb1[at] | mask) if enabled else (sb1[at] & ~mask)
        changes.append(f"flag {value:#x}={int(enabled)}")
    if emerald:
        # Beldum item visibility is a flag, not a game-clear script gate. The
        # OnFrame Dive scene triggers only state==1; this SYNTH setup has state0.
        flag(0x3C8, False)
        flag(0x3C7, True)  # hide Steven, away from the walk anyway
        # VAR_STEVENS_HOUSE_STATE 0x40C6; no need to claim the champion story.
        sb1[0x139C + 2 * (0x40C6 - 0x4000):0x139C + 2 * (0x40C6 - 0x4000) + 2] = b"\0\0"
        changes.append("VAR_STEVENS_HOUSE_STATE=0 (Dive scene disabled)")
    if kind == "gift":
        if not 1 <= len(party) < 6:
            raise ValueError("native gift requires an empty party slot")
        if rr:
            at = rr_gift_flag_offset(parsed, facts["flag"])
            extended_flag_patch = (at, seed[at] & ~facts["flag_mask"])
            changes.append(f"extended flag {facts['flag']:#x}=0 at parasite RAM {facts['flag_address']:#010x}; section0+0xF35")
        else:
            flag(facts["flag"], False)
        x, y = facts["x"], facts["y"]
        if facts["price"]:
            xor = int.from_bytes(sb2[0xF20:0xF24], "little")
            sb1[0x290:0x294] = (1000 ^ xor).to_bytes(4, "little")
            changes.append("money=1000 (native price=500)")
    else:
        egg = dict(party[0])
        pid = egg["personality"] ^ 0x24682468
        while pid == egg["personality"] or ((pid >> 16) ^ (pid & 0xFFFF) ^ (own >> 16) ^ (own & 0xFFFF)) < 8:
            pid = (pid + 1) & 0xFFFFFFFF
        egg.update(personality=pid, is_egg=1, is_egg_flag=1, is_bad_egg=0,
                   friendship=0, nickname="EGG", held_item=0, status=0)
        egg.pop("nickname_raw", None)
        # A disclosed near-hatch clone of this title's already-decoded native
        # lead: no foreign species/move tables, and hatch recalculates level/stats.
        sb1[count_at] = 2
        sb1[party_at + 100:party_at + 200] = c.encode_party_mon(egg, rr=rr)
        sb1[party_at + 200:party_at + 600] = bytes(400)
        x, y = facts["hatch_x"], facts["hatch_y"]
        changes.append(f"party[1]=SYNTH own species {egg['species']} egg cycles0; count2; remaining slots cleared")
        # Do not invent a daycare step-counter RAM binding. At cycles0 the next
        # native cycle check hatches after at most 256 walked steps.
    sb1[0x0C:0x14] = struct.pack("<bbbBhh", facts["group"], facts["num"], -1, 0, x, y)
    sb2[9] |= 1
    changes.append(f"CONTINUE_GAME_WARP {facts['group']}.{facts['num']} ({x},{y}); native {kind} pending")
    body = bytearray(seed)
    if rr:
        spans, patches = fixture._rr_write_spans(parsed), {}
        write = fixture._rr_field_patcher(spans, patches, "gift/egg SYNTH setup")
        # Patch only actual changed bytes through RR's native span layout;
        # preserve parasites, padding and extension exactly.
        for name, edited, address in (("sb1", sb1, c.RR_SAVEBLOCK1_ADDR), ("sb2", sb2, c.RR_SAVEBLOCK2_ADDR)):
            for i, (old, new) in enumerate(zip(parsed[name], edited, strict=True)):
                if old != new:
                    write(address + i, bytes([new]))
        for at, value in patches.items():
            body[at] = value
        if extended_flag_patch:
            at, value = extended_flag_patch
            body[at] = value  # parasite is serialized but excluded from the native section checksum
        fixture._rr_recompute_touched_checksums(parsed, seed, body, changes)
    else:
        objects = {"sb1": sb1, "sb2": sb2, "storage": parsed["storage"]}
        layout = c.slot_layout(title=layout_title)
        start = parsed["slot"] * c.NUM_SECTORS_PER_SLOT
        for entry in layout:
            sec = next(s for s in parsed["sectors"][start:start + c.NUM_SECTORS_PER_SLOT] if s["id"] == entry["id"])
            at = sec["index"] * c.SECTOR_SIZE
            chunk = objects[entry["object"]][entry["offset"]:entry["offset"] + entry["size"]]
            body[at:at + c.SECTOR_SIZE] = c.write_sector(chunk, entry["id"], parsed["counter"], layout)
    ok, why = c.qualify_flash(bytes(body), cfru=rr, title=layout_title)
    if not ok:
        raise ValueError(f"derived save does not qualify: {why}")
    return bytes(body), ["SYNTH " + line for line in changes]


def orchestrate(run):
    from tools.gen3_clause_rows import one
    run._gen3_prelude()  # no link or pokeball-gate injection
    for inst in ("a", "b"):
        own_facts(run, inst)
    run.go()
    run._acquisition_caps = {}
    for inst in ("a", "b"):
        tag = "EGG_RECEIVED" if run.cfg["acquisition_kind"] == "egg_receive" else "ACQUISITION_READY"
        marker = run._gen3_mark(inst, rf"^{tag} (\{{.*\}})$", "native acquisition ready")
        run._acquisition_caps[inst] = one("ACQUISITION_READY " + marker.group(1), "ACQUISITION_READY")
    if run.cfg["acquisition_kind"] == "egg_receive":
        for inst in ("a", "b"):
            run._append_reconnect_marker(inst, "SAVE")
        return
    run._link_keys = {i: c["key"] for i, c in run._acquisition_caps.items()}
    run.wait_for("one native gift link", lambda: any(
        all((row.get(i) or {}).get("key") == run._link_keys[i] for i in ("a", "b"))
        and row.get("status") == "alive" for row in run._links_json()), 120)
    for inst in ("a", "b"):
        run._append_reconnect_marker(inst, "SAVE")


def saved_oracle(run, results):
    if run._gen3_title("a") == "emerald_expansion_28877d73":
        return saved_exp_oracle(run, results)
    import e2e_duo as h

    from tools.gen3_clause_rows import one, rows
    kind = run.cfg["acquisition_kind"]
    run._gen3_flush_boundary()
    keys, problems = {}, []
    for inst in ("a", "b"):
        text, facts = results.get(inst, ""), own_facts(run, inst)
        before, after, cap = (one(text, tag) for tag in ("ACQUISITION_BEFORE", "ACQUISITION_AFTER", "ACQUISITION_READY"))
        keys[inst] = key = cap.get("key")
        sent = tx_messages(text, "capture")
        if (len(sent) != 1 or len(re.findall(r"^TX capture ", text, re.M)) != 1 or sent[0] != cap
                or cap.get("gift") is not True or cap.get("is_egg") is not False):
            problems.append(f"{inst}: not exactly one production gift capture")
        area = "gift_daycare" if kind == "hatch" else facts["area"]
        level = facts["hatch_level"] if kind == "hatch" else facts["level"]
        if cap.get("area_id") != area or cap.get("level") != level:
            problems.append(f"{inst}: wrong acquisition area or level")
        if before.get("captures") != 0 or before.get("balls") != after.get("balls"):
            problems.append(f"{inst}: early egg/gift capture or Ball pocket changed")
        if any(tx_messages(text, event) for event in ("key_change", "no_catch", "faint")):
            problems.append(f"{inst}: unexpected key_change/no_catch/faint")
        if "RX force_faint" in text or "RX memorialize" in text:
            problems.append(f"{inst}: fixed gift/hatch was rejected")
        signals = rows(text, "ACQUISITION_SIGNAL")
        if not any(s.get("kind") == ("hatch" if kind == "hatch" else "mon_given") for s in signals):
            problems.append(f"{inst}: no native acquisition signal")
        if not all(tag in text for tag in ("ACQUISITION_BEFORE ", "ACQUISITION_SIGNAL ", "TX capture ", "ACQUISITION_AFTER ", "ACQUISITION_READY ")):
            problems.append(f"{inst}: missing acquisition phases")
        elif not (text.index("ACQUISITION_BEFORE ") < text.index("ACQUISITION_SIGNAL ") < text.index("TX capture ")
                  < text.index("ACQUISITION_AFTER ") < text.index("ACQUISITION_READY ")):
            problems.append(f"{inst}: acquisition phases out of order")
        saved, fixture = run._gen3_saved(inst), run._gen3_fixture_saved(inst)
        party, boxes = saved
        fp, fb = fixture
        mon = next((m for m in party if h.gen3_key(m) == key), None)
        if not mon or mon.get("is_egg") or mon.get("is_egg_flag"):
            problems.append(f"{inst}: hatchling/gift missing or still an egg in saved flash")
        elif mon:
            problems += h.gen3_record_problems(inst, mon, run._gen3_rr, run._gen3_limits(inst))
            if mon["species"] != cap.get("species_id") or mon["level"] != level:
                problems.append(f"{inst}: saved mon differs from capture")
        if kind == "gift":
            problems += h.gen3_capture_problems(inst, saved, fixture, key, cap, run._gen3_rr, run._gen3_limits(inst))
            if cap.get("species_id") != facts["species"] or after.get("flag") is not True:
                problems.append(f"{inst}: wrong native gift or script did not finish")
            # Native script completion flag and money are decoded independently of Lua.
            from server.adapters import gen3_codec as c
            p = c.parse_flash(run._gen3_flushed(inst), cfru=run._gen3_rr,
                              title="emerald" if run._gen3_title(inst) == "emerald" else "frlg")
            if not saved_gift_flag(run._gen3_flushed(inst), run._gen3_title(inst), facts):
                problems.append(f"{inst}: saved native gift flag is clear")
            if facts["price"]:
                money = int.from_bytes(p["sb1"][0x290:0x294], "little") ^ int.from_bytes(p["sb2"][0xF20:0xF24], "little")
                if money != 500:
                    problems.append(f"{inst}: native seller price not persisted")
            controls = fp
        else:
            if len(fp) != 2 or fp[1]["is_egg"] != 1 or fp[1]["friendship"] != 0:
                problems.append(f"{inst}: fixture is not the disclosed near-hatch egg")
            elif mon and (h.gen3_key(fp[1]) != key or fp[1]["species"] != mon["species"]):
                problems.append(f"{inst}: wrong hatchling identity/species")
            elif mon and (mon["moves"] != fp[1]["moves"] or mon["ivs"] != fp[1]["ivs"]):
                problems.append(f"{inst}: hatch lost inherited moves or IVs")
            if [h.gen3_key(m) for m in party] != [h.gen3_key(m) for m in fp] or boxes != fb:
                problems.append(f"{inst}: hatch changed party membership or boxes")
            if (before.get("egg") != 1 or after.get("egg") != 0 or after.get("scene") is not True
                    or not 1 <= after.get("steps", 0) <= 600):
                problems.append(f"{inst}: no witnessed walking/hatch scene/egg transition")
            controls = fp[:1]
        for old in controls:
            now = next((m for m in party if h.gen3_key(m) == h.gen3_key(old)), None)
            mutable = {"friendship", "checksum"} if kind == "hatch" else set()
            if now is None or h.gen3_record_diff(old, now, run._gen3_rr, mutable=mutable):
                problems.append(f"{inst}: unrelated party member changed")
            elif now:
                problems += h.gen3_record_problems(inst + " control", now, run._gen3_rr, run._gen3_limits(inst))
    run._link_keys = keys
    link = run._gen3_one_link("alive")
    if any((link.get(inst) or {}).get("key") != keys[inst] for inst in ("a", "b")):
        problems.append("saved gift link crosses player ownership")
    area = "gift_daycare" if kind == "hatch" else own_facts(run, "a")["area"]
    if link.get("area_id") != area or len(run._links_json()) != 1:
        problems.append("native acquisition did not form exactly one gift link")
    if problems:
        raise RuntimeError("; ".join(problems))
    run._pydec_note(f"{kind}: native signal, one gift capture per side, one alive link, independent saved records and controls")


def saved_exp_oracle(run, results):
    import e2e_duo as h

    from tools import gen3_fixtures as f
    from tools.gen3_clause_rows import one, rows

    kind = run.cfg["acquisition_kind"]
    run._gen3_flush_boundary()
    problems, keys = [], {}
    for side in ("a", "b"):
        text, facts = results[side], own_facts(run, side)
        problems += [f"{side}: {p}" for p in exp_trace_problems(text, kind)]
        before, after = one(text, "ACQUISITION_BEFORE"), one(text, "ACQUISITION_AFTER")
        cap = one(text, "EGG_RECEIVED" if kind == "egg_receive" else "ACQUISITION_READY")
        key = keys[side] = cap["key"]
        captures = tx_messages(text, "capture")
        if len(captures) != (0 if kind == "egg_receive" else 1) or len(re.findall(r"^TX capture ",text,re.M)) != len(captures):
            problems.append(f"{side}: wrong production capture count")
        if before["balls"] != after["balls"] or before["captures"] != 0:
            problems.append(f"{side}: balls changed or early capture")
        if any(tx_messages(text, event) for event in ("no_catch", "faint", "key_change")):
            problems.append(f"{side}: unexpected non-acquisition event")
        if kind != "egg_receive":
            area = "gift_daycare" if kind == "hatch" else facts["area"]
            if not captures or captures[0] != cap or cap.get("area_id") != area or cap.get("gift") is not True:
                problems.append(f"{side}: wrong keyed gift namespace/payload")
            signal_kind = "hatch" if kind == "hatch" else "mon_given"
            pack = json.loads((ROOT / "data/games/gen3_exp/28877d73/engine_signals.json").read_text())
            site = pack["titles"][facts["title"]]["artifacts"]["clean"]["sites"][signal_kind]
            address = site["address"] + site["capture_offset"]
            signals = rows(text, "ACQUISITION_SIGNAL")
            if not any(s["kind"] == signal_kind and s["address"] == address for s in signals):
                problems.append(f"{side}: own-build native acquisition site not witnessed")
            if not (text.index("ACQUISITION_BEFORE ") < text.index("ACQUISITION_SIGNAL ") < text.index("TX capture ")
                    < text.index("ACQUISITION_AFTER ") < text.index("ACQUISITION_READY ")):
                problems.append(f"{side}: acquisition phase order changed")
        party, boxes = run._gen3_saved(side)
        fp, fb = run._gen3_fixture_saved(side)
        candidates = saved_records(party, boxes)
        found = [m for m in candidates if h.gen3_key(m) == key]
        if len(found) != 1 or bool(found[0]["is_egg"]) != (kind == "egg_receive"):
            problems.append(f"{side}: saved acquisition missing/duplicated or wrong egg state")
            continue
        mon = found[0]
        if kind == "hatch":
            if (h.gen3_key(fp[1]) != key or mon["species"] != fp[1]["species"] or mon["level"] != 1
                    or mon["moves"] != fp[1]["moves"] or mon["ivs"] != fp[1]["ivs"]
                    or not after.get("scene") or not 1 <= after.get("steps", 0) <= 600):
                problems.append(f"{side}: hatch identity/inheritance/scene not proved")
        elif mon["species"] != facts["species"] or not saved_gift_flag(run._gen3_flushed(side), facts["title"], facts):
            problems.append(f"{side}: script species/completion flag not persisted")
        if kind == "gift_box":
            if len(party) != len(fp) or any(h.gen3_key(m) == key for m in party) or cap.get("in_box") is not True:
                problems.append(f"{side}: gifted mon was not boxed")
            if {position: m for position,m in boxes.items() if h.gen3_key(m) != key} != fb:
                problems.append(f"{side}: unrelated box record changed")
        elif boxes != fb:
            problems.append(f"{side}: unrelated boxes changed")
        controls = fp[:1] if kind == "hatch" else fp
        for old in controls:
            now = next((m for m in party if h.gen3_key(m) == h.gen3_key(old)), None)
            if now is None or h.gen3_record_diff(old, now, False, mutable={"friendship", "checksum"} if kind == "hatch" else set()):
                problems.append(f"{side}: unrelated party record changed")
        raw = run._gen3_flushed(side)
        if not f.codec.qualify_flash(raw, title=f.codec.TITLE_EXPANSION)[0]:
            problems.append(f"{side}: save sectors invalid")
    links = run._links_json()
    if kind == "egg_receive":
        if links:
            problems.append("unhatched NPC egg formed a link")
    else:
        run._link_keys = keys
        link = run._gen3_one_link("alive")
        expected = "gift_daycare" if kind == "hatch" else own_facts(run,"a")["area"]
        if link["area_id"] != expected or any(link[side]["key"] != keys[side] for side in ("a","b")):
            problems.append("acquisition link identity/area mismatch")
    if problems:
        raise RuntimeError("; ".join(problems))
    run._pydec_note(f"exp {kind}: own engine site, keyed native acquisition, independently saved flash/controls")


def saved_records(party, boxes):
    return list(party) + list(boxes.values())


def exp_trace_problems(text, kind):
    """The actual Lua producer-shaped wire/phase contract, independent of save readback."""
    from tools.gen3_clause_rows import one, rows
    problems = []
    before, after = one(text, "ACQUISITION_BEFORE"), one(text, "ACQUISITION_AFTER")
    captures = tx_messages(text, "capture")
    if before["captures"] != 0 or before["balls"] != after["balls"]:
        problems.append("early acquisition or Ball debit")
    if kind == "egg_receive":
        ready = one(text, "EGG_RECEIVED")
        if captures or ready.get("is_egg") is not True or after.get("egg") != 1:
            problems.append("NPC egg capture before hatch or invalid egg witness")
    else:
        ready = one(text, "ACQUISITION_READY")
        expected = "hatch" if kind == "hatch" else "mon_given"
        pack = json.loads((ROOT / "data/games/gen3_exp/28877d73/engine_signals.json").read_text())
        site = pack["titles"]["emerald_expansion_28877d73"]["artifacts"]["clean"]["sites"][expected]
        if not any(s.get("kind") == expected and s.get("address") == site["address"] + site["capture_offset"]
                   for s in rows(text, "ACQUISITION_SIGNAL")):
            problems.append("own-build native acquisition site absent")
        if len(captures) != 1 or len(re.findall(r"^TX capture ",text,re.M)) != 1 or captures[0] != ready or ready.get("is_egg") is not False or ready.get("gift") is not True:
            problems.append("missing/duplicate or incorrect production acquisition capture")
    if any(tx_messages(text,e) for e in ("faint", "no_catch", "key_change")):
        problems.append("unexpected faint/no_catch/key_change")
    return problems


def tx_messages(text, event):
    return [json.loads(raw) for raw in re.findall(r"^TX " + re.escape(event) + r" \S+ (\{.*\})$", text, re.M)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", choices=tuple(GIFTS), required=True)
    parser.add_argument("--kind", choices=("gift", "hatch"), required=True)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    body, manifest = build_seed(args.seed.read_bytes(), args.title, args.kind, args.rom.read_bytes())
    args.out.write_bytes(body)
    print("\n".join(manifest))
    print(f"wrote {args.out} sha256={hashlib.sha256(body).hexdigest()}")


if __name__ == "__main__":
    main()
