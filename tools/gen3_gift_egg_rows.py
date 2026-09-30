"""GIFT-EGG-ROWS-G3: own-ROM gift facts, disclosed SYNTH setup, native-row oracle.

No emulator entrypoint. Run this module to prepare a seed, then e2e_duo.py runs
ordinary buttons against the production client. Pins are SOURCE, tests MODEL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
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


def own_facts(run, inst):
    cache = run.__dict__.setdefault("_acquisition_facts", {})
    if inst not in cache:
        cache[inst] = title_facts((ROOT / run._gen3_rom(inst)).read_bytes(), run._gen3_title(inst))
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
        marker = run._gen3_mark(inst, r"^ACQUISITION_READY (\{.*\})$", "native acquisition ready")
        run._acquisition_caps[inst] = one("ACQUISITION_READY " + marker.group(1), "ACQUISITION_READY")
    run._link_keys = {i: c["key"] for i, c in run._acquisition_caps.items()}
    run.wait_for("one native gift link", lambda: any(
        all((row.get(i) or {}).get("key") == run._link_keys[i] for i in ("a", "b"))
        and row.get("status") == "alive" for row in run._links_json()), 120)
    for inst in ("a", "b"):
        run._append_reconnect_marker(inst, "SAVE")


def saved_oracle(run, results):
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
