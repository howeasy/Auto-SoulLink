#!/usr/bin/env python3
"""Build encounter_census.json + area_map_purergb.json for pureRGB v2.7.6, and
verify the grass_water.asm parse against the built ROM (pokered.gbc)."""
import json
import os
import re

P = r"C:\Users\howar\AppData\Local\Temp\claude\E--Google-Drive-SLink--claude-worktrees-recursing-hopper-86c382\27f97123-cfa0-473c-aed8-f288963eedeb\scratchpad\purergb"
B = r"C:\Users\howar\AppData\Local\Temp\claude\E--Google-Drive-SLink--claude-worktrees-recursing-hopper-86c382\27f97123-cfa0-473c-aed8-f288963eedeb\scratchpad\build"
OUT = r"C:\Users\howar\AppData\Local\Temp\claude\E--Google-Drive-SLink--claude-worktrees-recursing-hopper-86c382\2eefad46-f87d-42d5-a71b-d9e3807a4bb1\scratchpad\workers\w1"

SLOT_RATES_256 = [51, 51, 39, 25, 25, 25, 13, 13, 11, 3]  # WildMonEncounterSlotChances (probabilities.asm)
SLOT_RATES_PCT = [20, 20, 15, 10, 10, 10, 5, 5, 4, 1]     # vanilla SLOT_RATES from gen_gen1_encounters.py

# ---------- 1. map_constants.asm -> map_id -> NAME ----------
def parse_map_constants(path):
    id_to_name = {}
    name_to_id = {}
    idx = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split(";", 1)[0].strip()
            m = re.match(r"^map_const\s+([A-Z0-9_]+)\s*,", line)
            if m:
                id_to_name[idx] = m.group(1)
                name_to_id[m.group(1)] = idx
                idx += 1
    return id_to_name, name_to_id

# ---------- 2. pokemon_constants.asm -> internal name -> id ----------
def parse_pokemon_constants(path):
    out = {}
    idx = -1
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split(";", 1)[0].strip()
            if line == "const_def":
                idx = 0
                continue
            if line == "const_skip":
                if idx >= 0:
                    idx += 1
                continue
            m = re.match(r"^const\s+([A-Za-z_0-9]+)\s*$", line)
            if m and idx >= 0:
                out[m.group(1)] = idx
                idx += 1
            if line.startswith("DEF NUM_POKEMON_INDEXES"):
                break
    return out

# ---------- 3. pokedex_constants.asm -> DEX_XXX -> number ----------
def parse_pokedex_constants(path):
    out = {}
    idx = -1
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split(";", 1)[0].strip()
            if line == "const_def":
                idx = 0
                continue
            if line == "const_skip":
                if idx >= 0:
                    idx += 1
                continue
            m = re.match(r"^const\s+([A-Za-z_0-9]+)\s*$", line)
            if m and idx >= 0:
                out[m.group(1)] = idx
                idx += 1
    return out

# ---------- 4. dex_order.asm -> internal_id (index+1) -> dex number ----------
def parse_dex_order(path, dex_const_to_num):
    entries = []
    in_table = False
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split(";", 1)[0].strip()
            if line.startswith("PokedexOrder"):
                in_table = True
                continue
            if not in_table:
                continue
            if line.startswith("assert_table_length"):
                break
            m = re.match(r"^db\s+(\S+)\s*$", line)
            if m:
                tok = m.group(1)
                if tok.startswith("DEX_"):
                    entries.append(dex_const_to_num[tok])
                else:
                    entries.append(int(tok, 0))
    return entries  # index i -> dex number for internal id (i+1)

# ---------- 5. names.asm -> internal_id (index+1) -> display name ----------
def parse_names(path):
    names = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            m = re.match(r'^dname\s+"(.*)"\s*$', line)
            if m:
                names.append(m.group(1))
    return names  # index i -> name for internal id (i+1)

# ---------- 6. grass_water.asm -> WildDataPointers list of (map_id, label) ----------
def parse_wild_pointers(path):
    out = []
    in_table = False
    idx = 0
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split(";", 1)[0].strip()
            if line.startswith("WildDataPointers"):
                in_table = True
                continue
            if not in_table:
                continue
            if line.startswith("assert_table_length") or line.startswith("dw -1"):
                break
            m = re.match(r"^dw\s+([A-Za-z_0-9]+)\s*$", line)
            if m:
                out.append((idx, m.group(1)))
                idx += 1
    return out

# ---------- 7. per-map wild asm parse (grass/water rate + 10 (level,species) slots) ----------
IF_DEF_RE = re.compile(r"^IF\s+DEF\(\s*([A-Za-z_0-9]+)\s*\)\s*$")

def parse_map_asm(path):
    """Returns (grass_rate, grass_slots, water_rate, water_slots, had_conditional)
    grass_slots/water_slots = list of (level, species_const), always the ELSE/real branch
    (excludes _DEBUG)."""
    grass_rate = 0
    water_rate = 0
    grass = []
    water = []
    section = None
    cond_stack = []  # list of (name, taking_this_branch)
    had_conditional = False
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split(";", 1)[0].strip()
            if not line:
                continue
            m = IF_DEF_RE.match(line)
            if m:
                had_conditional = True
                # we want the REAL (non-debug/non-version) branch; take False branch of _DEBUG,
                # i.e. skip content directly inside "IF DEF(_DEBUG)" and take the ELSE.
                cond_stack.append([m.group(1), False])
                continue
            if line == "ELSE":
                if cond_stack:
                    cond_stack[-1][1] = not cond_stack[-1][1]
                continue
            if line == "ENDC":
                if cond_stack:
                    cond_stack.pop()
                continue
            if any(not taken for _, taken in cond_stack):
                continue
            m = re.match(r"^def_grass_wildmons\s+(\d+)\s*$", line)
            if m:
                grass_rate = int(m.group(1))
                section = "grass"
                continue
            m = re.match(r"^def_water_wildmons\s+(\d+)\s*$", line)
            if m:
                water_rate = int(m.group(1))
                section = "water"
                continue
            if line in ("end_grass_wildmons", "end_water_wildmons"):
                section = None
                continue
            m = re.match(r"^db\s+(\d+)\s*,\s*([A-Za-z_0-9]+)\s*$", line)
            if m and section is not None:
                (grass if section == "grass" else water).append((int(m.group(1)), m.group(2)))
    return grass_rate, grass, water_rate, water, had_conditional


def main():
    map_id_to_name, map_name_to_id = parse_map_constants(os.path.join(P, "constants", "map_constants.asm"))
    species_to_id = parse_pokemon_constants(os.path.join(P, "constants", "pokemon_constants.asm"))
    dex_const_to_num = parse_pokedex_constants(os.path.join(P, "constants", "pokedex_constants.asm"))
    dex_order = parse_dex_order(os.path.join(P, "data", "pokemon", "dex_order.asm"), dex_const_to_num)
    names = parse_names(os.path.join(P, "data", "pokemon", "names.asm"))

    print(f"map_constants: {len(map_id_to_name)} maps")
    print(f"pokemon_constants: {len(species_to_id)} species (incl NO_MON)")
    print(f"pokedex_constants: {len(dex_const_to_num)} dex consts")
    print(f"dex_order entries: {len(dex_order)}")
    print(f"names entries: {len(names)}")

    def species_lookup(const_name):
        if const_name == "MISSINGNO":
            # MISSINGNO real internal id ($B5 in pureRGB) -- still resolvable via species_to_id
            pass
        internal_id = species_to_id.get(const_name)
        if internal_id is None:
            return {"species_internal": None, "species_dex": None, "species_name": const_name,
                    "_unresolved": True}
        idx = internal_id - 1  # names/dex_order arrays are 0-indexed starting at internal id 1
        dex_num = dex_order[idx] if 0 <= idx < len(dex_order) else None
        name = names[idx] if 0 <= idx < len(names) else const_name
        return {"species_internal": internal_id, "species_dex": dex_num, "species_name": name}

    # sanity: MISSINGNO const and NO_MON const
    print("MISSINGNO internal id:", species_to_id.get("MISSINGNO"))
    print("NO_MON internal id:", species_to_id.get("NO_MON"))
    print("sample lookup RHYDON:", species_lookup("RHYDON"))
    print("sample lookup PIKACHU:", species_lookup("PIKACHU"))
    print("sample lookup MISSINGNO:", species_lookup("MISSINGNO"))

    wild_pointers = parse_wild_pointers(os.path.join(P, "data", "wild", "grass_water.asm"))
    print(f"WildDataPointers entries: {len(wild_pointers)}")

    # parse every referenced label's .asm (labels map to files via CamelCase name minus "WildMons")
    label_to_asmfile = {}
    maps_dir = os.path.join(P, "data", "wild", "maps")
    for fn in os.listdir(maps_dir):
        if fn.endswith(".asm"):
            label_to_asmfile[fn[:-4] + "WildMons"] = os.path.join(maps_dir, fn)
    label_to_asmfile["NothingWildMons"] = os.path.join(maps_dir, "nothing.asm")

    conditional_labels = []
    per_map = {}
    unknown_species = set()
    for map_id, label in wild_pointers:
        name = map_id_to_name.get(map_id, f"UNKNOWN_{map_id}")
        entry = {"name": name, "wild_label": label}
        path = label_to_asmfile.get(label)
        if path is None:
            entry["_error"] = f"no asm file found for label {label}"
            per_map[map_id] = entry
            continue
        grass_rate, grass, water_rate, water, had_cond = parse_map_asm(path)
        if had_cond:
            conditional_labels.append((map_id, label))

        def build_block(rate, slots):
            if rate == 0 or not slots:
                return {"rate": rate, "slots": []}
            out_slots = []
            for i, (level, sp) in enumerate(slots):
                info = species_lookup(sp)
                if info.get("_unresolved"):
                    unknown_species.add(sp)
                out_slots.append({
                    "slot": i,
                    "level": level,
                    "species_internal": info["species_internal"],
                    "species_dex": info["species_dex"],
                    "species_name": info["species_name"],
                    "species_const": sp,
                    "pct_of_100": SLOT_RATES_PCT[i],
                    "chance_of_256": SLOT_RATES_256[i],
                })
            return {"rate": rate, "slots": out_slots}

        entry["grass"] = build_block(grass_rate, grass)
        entry["water"] = build_block(water_rate, water)
        per_map[map_id] = entry

    print("Maps with IF DEF conditional in wild asm:", conditional_labels)
    print("Unresolved species consts:", unknown_species)

    # ---------- good_rod.asm / super_rod.asm / OldRod / OceanMaps ----------
    def parse_good_rod():
        path = os.path.join(P, "data", "wild", "good_rod.asm")
        pools = {}
        cur = None
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.split(";", 1)[0].strip()
                m = re.match(r"^(GoodRodMons|GoodRodMonsOcean):\s*$", line)
                if m:
                    cur = m.group(1)
                    pools[cur] = []
                    continue
                m = re.match(r"^db\s+(-?\d+)\s*,\s*(\S+)\s*$", line)
                if m and cur:
                    lvl, sp = m.group(1), m.group(2)
                    if lvl == "-1":
                        cur = None
                        continue
                    pools[cur].append((int(lvl), sp))
        return pools

    good_rod_pools = parse_good_rod()
    print("good_rod pools:", {k: len(v) for k, v in good_rod_pools.items()})

    def parse_ocean_maps():
        path = os.path.join(P, "data", "maps", "ocean_maps.asm")
        maps = []
        in_table = False
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.split(";", 1)[0].strip()
                if line.startswith("OceanMaps:"):
                    in_table = True
                    continue
                if not in_table:
                    continue
                m = re.match(r"^db\s+(-?\d+|\S+)\s*$", line)
                if m:
                    tok = m.group(1)
                    if tok == "-1":
                        break
                    maps.append(tok)
                elif line and not line.startswith(";"):
                    break
        return maps

    ocean_map_names = parse_ocean_maps()
    ocean_map_ids = {map_name_to_id[n] for n in ocean_map_names if n in map_name_to_id}
    print("OceanMaps:", ocean_map_names, "-> ids", sorted(ocean_map_ids))

    def parse_super_rod():
        path = os.path.join(P, "data", "wild", "super_rod.asm")
        rows = []
        groups = {}
        in_table = False
        cur_group = None
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.split(";", 1)[0].strip()
                if line.startswith("SuperRodData:"):
                    in_table = True
                    continue
                if in_table:
                    if line.startswith("db -1"):
                        in_table = False
                        continue
                    m = re.match(r"^dbw\s+(\S+)\s*,\s*(\S+)\s*$", line)
                    if m:
                        rows.append((m.group(1), m.group(2)))
                        continue
                m = re.match(r"^(Group\d+):\s*$", line)
                if m:
                    cur_group = m.group(1)
                    groups[cur_group] = []
                    continue
                m = re.match(r"^db\s+(\d+)\s*$", line)
                if m and cur_group and not groups[cur_group]:
                    continue  # count line, ignore (we just read pairs below)
                m = re.match(r"^db\s+(\d+)\s*,\s*(\S+)\s*$", line)
                if m and cur_group:
                    groups[cur_group].append((int(m.group(1)), m.group(2)))
        return rows, groups

    super_rod_rows, super_rod_groups = parse_super_rod()
    print("SuperRodData rows:", len(super_rod_rows), "groups:", {k: len(v) for k, v in super_rod_groups.items()})

    # ---------- attach fishing tables to the "area" maps ----------
    def build_fish_list(pairs):
        out = []
        for lvl, sp in pairs:
            info = species_lookup(sp)
            out.append({
                "level": lvl, "species_internal": info["species_internal"],
                "species_dex": info["species_dex"], "species_name": info["species_name"],
                "species_const": sp,
            })
        return out

    old_rod_universal = [
        {"level": 10, "species_const": "GOLDEEN", **{k: v for k, v in species_lookup("GOLDEEN").items() if k != "species_name"}, "species_name": species_lookup("GOLDEEN")["species_name"], "chance": "50%"},
        {"level": 10, "species_const": "MAGIKARP", **{k: v for k, v in species_lookup("MAGIKARP").items() if k != "species_name"}, "species_name": species_lookup("MAGIKARP")["species_name"], "chance": "50%"},
    ]
    good_rod_fresh = build_fish_list(good_rod_pools["GoodRodMons"])
    good_rod_ocean = build_fish_list(good_rod_pools["GoodRodMonsOcean"])

    super_rod_by_map = {}
    for map_name, group in super_rod_rows:
        mid = map_name_to_id.get(map_name)
        if mid is None:
            continue
        super_rod_by_map[mid] = build_fish_list(super_rod_groups[group])

    # Fishing (old/good/super rod) is gated by actual water tiles near the player, not by the
    # walk-in wild table. We don't have per-map tileset/blk data parsed here, so approximate
    # "fishable" as: has a nonzero WATER wild-encounter rate (implies water tiles exist), OR is
    # explicitly listed in OceanMaps (good rod pool selector), OR has a SuperRodData row.
    # ponytail: approximation, not a tile-level fishability scan -- flagged in REPORT.md.
    water_wild_ids = {mid for mid, e in per_map.items() if e.get("water", {}).get("rate", 0) > 0}
    fishable_map_ids = water_wild_ids | ocean_map_ids | set(super_rod_by_map.keys())
    for mid in fishable_map_ids:
        entry = per_map.setdefault(mid, {"name": map_id_to_name.get(mid, f"UNKNOWN_{mid}")})
        entry["old_rod"] = old_rod_universal
        entry["good_rod"] = good_rod_ocean if mid in ocean_map_ids else good_rod_fresh
        entry["good_rod_pool"] = "ocean" if mid in ocean_map_ids else "fresh"
        entry["super_rod"] = super_rod_by_map.get(mid, [])

    # write encounter_census.json (string keys since JSON requires string keys)
    census_out = {str(k): v for k, v in sorted(per_map.items())}
    with open(os.path.join(OUT, "encounter_census.json"), "w", encoding="utf-8") as f:
        json.dump(census_out, f, indent=2, ensure_ascii=False)
    print("Wrote encounter_census.json,", len(census_out), "map entries")

    # ---------- verify against ROM ----------
    verify_against_rom(wild_pointers, label_to_asmfile, map_id_to_name)

    return {
        "map_id_to_name": map_id_to_name,
        "map_name_to_id": map_name_to_id,
        "wild_pointers": wild_pointers,
        "ocean_map_ids": ocean_map_ids,
        "super_rod_by_map": super_rod_by_map,
        "per_map": per_map,
    }


def read_sym(path):
    """bank:addr Label -> flat file offset, keyed by label AND by (bank,addr)."""
    label_to_flat = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            m = re.match(r"^([0-9a-fA-F]+):([0-9a-fA-F]+)\s+(\S+)$", line)
            if not m:
                continue
            bank = int(m.group(1), 16)
            addr = int(m.group(2), 16)
            label = m.group(3)
            flat = addr if (bank == 0 and addr < 0x4000) else bank * 0x4000 + (addr - 0x4000)
            label_to_flat[label] = (bank, addr, flat)
    return label_to_flat


def verify_against_rom(wild_pointers, label_to_asmfile, map_id_to_name):
    rom_path = os.path.join(B, "pokered.gbc")
    sym_path = os.path.join(B, "pokered.sym")
    with open(rom_path, "rb") as f:
        rom = f.read()
    syms = read_sym(sym_path)

    bank, addr, flat = syms["WildDataPointers"]
    print(f"\nVERIFY: WildDataPointers at {bank:02x}:{addr:04x} flat=0x{flat:x}")
    assert (bank, addr) == (0x2C, 0x484A), "WildDataPointers address mismatch vs task spec!"

    mismatches = []
    n_checked = 0
    idx = 0
    off = flat
    rom_ptrs = []
    while True:
        ptr = rom[off] | (rom[off + 1] << 8)
        off += 2
        if ptr == 0xFFFF:
            break
        rom_ptrs.append(ptr)
        idx += 1
    print(f"ROM table has {len(rom_ptrs)} pointers before $FFFF terminator (source had {len(wild_pointers)})")
    if len(rom_ptrs) != len(wild_pointers):
        mismatches.append(f"pointer count mismatch: rom={len(rom_ptrs)} source={len(wild_pointers)}")

    def read_block(flat_off):
        rate = rom[flat_off]
        if rate == 0:
            return rate, [], flat_off + 1
        slots = []
        p = flat_off + 1
        for _ in range(10):
            level = rom[p]
            species = rom[p + 1]
            slots.append((level, species))
            p += 2
        return rate, slots, p

    species_to_id = parse_pokemon_constants(os.path.join(P, "constants", "pokemon_constants.asm"))
    id_to_species = {v: k for k, v in species_to_id.items()}

    for (map_id, label), ptr in zip(wild_pointers, rom_ptrs):
        # pointer is bank-relative address within bank 0x2C
        rom_flat = 0x2C * 0x4000 + (ptr - 0x4000)
        grass_rate, grass_slots, next_off = read_block(rom_flat)
        water_rate, water_slots, _ = read_block(next_off)

        # cross-check vs sym label address if we have it (not all Wild labels resolved above, but most)
        if label in syms:
            sb, sa, sflat = syms[label]
            if sflat != rom_flat:
                mismatches.append(f"map {map_id} {label}: sym flat=0x{sflat:x} != pointer-derived flat=0x{rom_flat:x}")

        # parse source
        path = label_to_asmfile.get(label)
        if path is None:
            mismatches.append(f"map {map_id} {label}: no source file")
            continue
        s_grass_rate, s_grass, s_water_rate, s_water, _ = parse_map_asm(path)

        n_checked += 1
        if grass_rate != s_grass_rate:
            mismatches.append(f"map {map_id} {label}: grass_rate ROM={grass_rate} SRC={s_grass_rate}")
        if water_rate != s_water_rate:
            mismatches.append(f"map {map_id} {label}: water_rate ROM={water_rate} SRC={s_water_rate}")

        def cmp_slots(rom_slots, src_slots, kind):
            if len(rom_slots) != len(src_slots):
                mismatches.append(f"map {map_id} {label} {kind}: slot count ROM={len(rom_slots)} SRC={len(src_slots)}")
                return
            for i, ((rl, rs), (sl, ssp)) in enumerate(zip(rom_slots, src_slots)):
                sid = species_to_id.get(ssp)
                if rl != sl:
                    mismatches.append(f"map {map_id} {label} {kind} slot{i}: level ROM={rl} SRC={sl}")
                if sid is None:
                    mismatches.append(f"map {map_id} {label} {kind} slot{i}: unknown source species const {ssp}")
                elif rs != sid:
                    mismatches.append(
                        f"map {map_id} {label} {kind} slot{i}: species ROM=0x{rs:02x}({id_to_species.get(rs,'?')}) "
                        f"SRC=0x{sid:02x}({ssp})")

        cmp_slots(grass_slots, s_grass, "grass")
        cmp_slots(water_slots, s_water, "water")

    print(f"Checked {n_checked} maps byte-for-byte against ROM.")
    print(f"Mismatches: {len(mismatches)}")
    for m in mismatches[:50]:
        print("  MISMATCH:", m)

    with open(os.path.join(OUT, "rom_verify_report.json"), "w", encoding="utf-8") as f:
        json.dump({"checked": n_checked, "mismatches": mismatches,
                   "rom_pointer_count": len(rom_ptrs), "source_pointer_count": len(wild_pointers)},
                  f, indent=2)

    # also verify GoodRodMons / GoodRodMonsOcean / SuperRodData against ROM bytes at given addresses
    verify_rod_tables(rom, syms, species_to_id, id_to_species, mismatches)


def verify_rod_tables(rom, syms, species_to_id, id_to_species, mismatches):
    def flat_of(bank_addr_str):
        bank_s, addr_s = bank_addr_str.split(":")
        bank = int(bank_s, 16)
        addr = int(addr_s, 16)
        return bank * 0x4000 + (addr - 0x4000) if not (bank == 0 and addr < 0x4000) else addr

    # GoodRodMons 03:5F28 (4 pairs + terminator -1,-1)
    off = flat_of("03:5f28")
    good_rod_mons = []
    for _ in range(4):
        lvl = rom[off]; sp = rom[off+1]; off += 2
        good_rod_mons.append((lvl, sp))
    term = (rom[off], rom[off+1])
    print("\nGoodRodMons ROM bytes:", good_rod_mons, "terminator", term)

    off = flat_of("03:5f32")
    good_rod_ocean = []
    for _ in range(4):
        lvl = rom[off]; sp = rom[off+1]; off += 2
        good_rod_ocean.append((lvl, sp))
    term2 = (rom[off], rom[off+1])
    print("GoodRodMonsOcean ROM bytes:", good_rod_ocean, "terminator", term2)

    # cross check vs source good_rod.asm
    path = os.path.join(P, "data", "wild", "good_rod.asm")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    for label, rom_pairs in (("GoodRodMons", good_rod_mons), ("GoodRodMonsOcean", good_rod_ocean)):
        block = re.search(label + r":\n((?:\s*;.*\n|\s*db.*\n)*)", text)
        pairs = re.findall(r"db\s+(-?\d+)\s*,\s*(\S+)", block.group(1))
        pairs = [(int(l), s) for l, s in pairs if l != "-1"]
        for i, ((rl, rs), (sl, ssp)) in enumerate(zip(rom_pairs, pairs)):
            sid = species_to_id.get(ssp)
            if rl != sl or rs != sid:
                mismatches.append(f"{label} slot{i}: ROM=({rl},{rs}/{id_to_species.get(rs)}) SRC=({sl},{ssp}/{sid})")
    print("GoodRod ROM-vs-source mismatches so far:", len(mismatches))


if __name__ == "__main__":
    result = main()
