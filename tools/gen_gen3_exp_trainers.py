#!/usr/bin/env python3
"""Generate data/games/gen3_exp/28877d73/gen3_exp_trainers.json and
calc/src/js/data/sets/games/EmeraldExpansion.js from the pinned pokeemerald-expansion source
(tag expansion/1.17.0, commit e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7 --
data/gen3_exp_sources.lock.json).

Card XC4 (docs/gen3_emerald/research/expansion_calc_design_2026-09-26.md section XC4): trainer
sets for the calc's "Prep" tab (a) and the dashboard's "Upcoming Key Trainers" panel (b), for the
pokeemerald-expansion reference build (ROM 28877d73). Owner ruling (2026-09-26): trainer panels
are mandatory for an RC, not RR-only.

Canonical source: src/data/trainers.h. The DSL (src/data/trainers.party) is compiled into this
header by expansion's own "party" build tool; the checked-in header carries its own comment
("DO NOT MODIFY THIS FILE! It is auto-generated from src/data/trainers.party") and is part of
the SAME pinned commit, so reading it *is* reading the pinned source -- no build tool needs to
run. Only [DIFFICULTY_NORMAL][...] rows carry data in this build (checked: zero
"[DIFFICULTY_HARD][TRAINER_" hits), so DIFFICULTY_HARD is not read.

Per-mon facts, all explicit in this build (unlike vanilla pret Emerald, nothing here needs the
personality-hash reconstruction for nature/ability):
  species    .species = SPECIES_X (include/constants/species.h; a C enum in this fork, not
             #define -- see enum_values()).
  level      .lvl.
  item       .heldItem, optional.
  moves      .moves, when the party author chose one explicitly; otherwise the level-up
             learnset default -- GiveBoxMonInitialMoveset's algorithm, reused via
             server.adapters.gen3_frlge.default_moves(), walking
             src/data/pokemon/level_up_learnsets/gen_*.h through the .levelUpLearnset symbol in
             src/data/pokemon/species_info/gen_*_families.h.
  nature     .nature, always explicit (NATURE_X).
  ivs        .iv = TRAINER_PARTY_IVS(hp, atk, def, speed, spatk, spdef) -- note SPEED is the
             4th slot, not spatk (include/data.h:60).
  ability    never set per-mon in this build (checked: zero ".ability" hits in trainers.h), so
             it is always the species' slot-0 ability -- matches
             include/config/battle.h's B_TRAINER_MON_RANDOM_ABILITY == 0 ("trainers mons with
             no set ability only use the first ability of a mon").

Class display names: src/battle_main.c's gTrainerClasses[] (`[TRAINER_CLASS_X] = { _("NAME"),
... }`), looked up by the same TRAINER_CLASS_X symbol trainers.h uses -- no numeric ordinal
needed. Wire trainer ids: include/constants/opponents.h's `#define TRAINER_X N` (gTrainers
index, no offset -- same convention gen_gen3_trainers.py documents for FR/LG).

Key trainers (Upcoming Key Trainers panel): TRAINER_CLASS_LEADER, ELITE_FOUR, CHAMPION, RIVAL
(Brendan/May -- hardcoded per row in this build, not synthesized like FRLG's player-name
substitution), AQUA_LEADER, MAGMA_LEADER, AQUA_ADMIN, MAGMA_ADMIN. level_cap is the trainer's own
highest party level.

Area: reuse tools/gen_gen3_trainers.py's generic map-graph helpers (map.json/scripts.inc schema
is identical to pret's, since expansion forked pret's map tooling) against the PRE-EXISTING
data/games/gen3_exp/28877d73/area_map.json ("group:num" -> area id; owned by another XC phase,
READ ONLY here). Confirmed against this pin's data/maps/map_groups.json: group 0 index 0 is
PetalburgCity, and area_map.json's "0:0" is "petalburg_city". Vs Seeker rematch tiers (the
TRAINER_X_2.._5 constants that never appear in a map trainerbattle script -- a separate rematch
system re-fights the same NPC in place) get their area from src/battle_setup.c's gRematchTable
(include/battle_setup.h's `struct RematchTrainer {trainerIds[5]; mapGroup; mapNum}`), fed through
the SAME map_area (map id -> area, including its BFS-nearest-mapped-area fallback for a map like
Mt. Chimney that has no area of its own) so a rematch tier lands in the exact map the pinned
source re-fights it in -- never a same-class/same-name guess (OMP cx-081c78d3 F2: Brendan and May
alone share 16 rival fights under one (class, name), so guessing by that pair is not safe; the
rival battles aren't in gRematchTable at all -- they're plain trainerbattle scripts already found
by trainer_maps() -- so they get no fallback and simply keep whatever tmaps found, or no area).

Names (species/move/item/ability) are resolved through Gen3ExpansionAdapter itself
(species_name/move_name/item_name/ability_name + calc_name()) so trainer sets speak the exact
calc-spelling table the rest of the adapter already uses -- no separate name table here.
MOVE_HIDDEN_POWER never carries an explicit type in this build (no field for one exists on
struct TrainerMon -- checked include/data.h; the type is the vanilla per-mon IV formula, which
this generator has no per-mon IV-to-type table for), so it is emitted as the bare move name
"Hidden Power", not "Hidden Power <Type>" (OMP cx-081c78d3 F10).

Prep tab base-name collisions: the Prep tab groups a setdex key by the text before " | "
(calc/src/js/slink_bridge.js's _buildTrainerIndex, `setKey.slice(0, pipeIdx)`) into ONE encounter
list, so two different trainer ids must never render the same base text -- see compute_bases()
(OMP cx-081c78d3 F1: a rematch tier's discriminator used to sit after the pipe, an opaque
uniqueness key that never affects grouping, so a gym leader's five rematch tiers all merged into
one fake combined party). compute_bases() gives every trainer id its own base: a name that's
already unique keeps it bare; a gRematchTable-linked rematch chain (TRAINER_X_1.._5, same
class+name) gets "<base> Rematch N"; any other collision (two unrelated trainers sharing a
generic class+name like "GRUNT") is disambiguated by trainer id order, "<base> (2)", "<base> (3)",
... -- never by how many times a name has been seen for one species (that varies per species and
doesn't track trainer identity). _dedupe_key() still guards the JS object literal against two
mons of the SAME trainer's OWN party (a duplicate species in one party) silently colliding on one
key; that's a within-trainer collision, correctly rendered as one encounter, not the bug above.

Run against a LOCAL copy of the pinned source tree (never point this at a live shared host from
here -- copy only the files you need, see the card's instructions):
    python tools/gen_gen3_exp_trainers.py --src <expansion-checkout-or-partial-copy>
    python tools/gen_gen3_exp_trainers.py --src <...> --check
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.adapters.gen3_expansion import ROM_TYPE, Gen3ExpansionAdapter  # noqa: E402
from server.adapters.gen3_frlge import default_moves  # noqa: E402
from tools.gen_area_map import _expansion_source_sha256  # noqa: E402
from tools.gen_gen3_trainers import (  # noqa: E402
    _emerald_rematch,
    area_of_map,
    defines,
    map_jsons,
    map_keys,
    pretty,
    read,
    trainer_maps,
)

OUT_JSON = ROOT / "data/games/gen3_exp/28877d73/gen3_exp_trainers.json"
OUT_JS = ROOT / "calc/src/js/data/sets/games/EmeraldExpansion.js"
AREA_MAP = ROOT / "data/games/gen3_exp/28877d73/area_map.json"
AREAS_LUA = ROOT / "data/games/gen3_exp/28877d73/gen3_exp_areas.lua"

KEY_CLASSES = {"LEADER", "ELITE_FOUR", "CHAMPION", "RIVAL",
               "AQUA_LEADER", "MAGMA_LEADER", "AQUA_ADMIN", "MAGMA_ADMIN"}

# Vs Seeker rival encounters (Brendan/May route/city fights): the trainer const's own suffix
# names the PLAYER's starter (see module docstring on fight_label). Same three species this
# build's starters use -- GAMES["emerald"]["starters"] in tools/gen_gen3_trainers.py.
STARTERS = ("TREECKO", "TORCHIC", "MUDKIP")

# Card XC4c: gTrainers ids never battled by any trainerbattle/multi-battle script or gRematchTable
# row anywhere in the pinned source (verified: TRAINER_RED/TRAINER_LEAF appear only in
# include/constants/opponents.h and src/data/trainers.h/.party) -- the same two link-battle
# save-slot placeholders vanilla pret Emerald excludes via GAMES["emerald"]["unused"] in
# tools/gen_gen3_trainers.py. Never a key trainer, however key-classed they're declared.
UNBATTLED_KEY_CANDIDATES = {"TRAINER_RED", "TRAINER_LEAF"}


def enum_values(text: str, prefix: str) -> dict[str, int]:
    """NAME = N, NAME = OTHER_NAME (alias), or bare NAME, one per enum-body line -- the pattern
    include/constants/species.h|moves.h|items.h use in this fork (moved off #define)."""
    out: dict[str, int] = {}
    prev = -1
    aliases: list[tuple[str, str]] = []
    for line in text.splitlines():
        m = re.match(rf"\s*({prefix}\w+)\s*(?:=\s*([^,]+?))?\s*,\s*(?://.*)?$", line)
        if not m:
            continue
        name, val = m.group(1), m.group(2)
        if val is None:
            prev += 1
            out[name] = prev
            continue
        val = val.strip()
        if re.fullmatch(r"0x[0-9A-Fa-f]+|\d+", val):
            prev = int(val, 0)
            out[name] = prev
        else:
            aliases.append((name, val))
    for name, val in aliases:
        if val in out:
            out[name] = out[val]
    return out


def class_names(text: str) -> dict[str, str]:
    return dict(re.findall(r'\[TRAINER_CLASS_(\w+)\]\s*=\s*\{\s*_\("([^"]*)"\)', text))


def parse_trainer_blocks(text: str) -> list[tuple[str, str]]:
    return re.findall(r"\[DIFFICULTY_NORMAL\]\[TRAINER_(\w+)\]\s*=\s*\{(.*?)\n    \},\n", text, re.S)


def parse_mons(body: str) -> list[dict]:
    # .party is always the last field of a trainer struct, so its closing "        }," is not
    # followed by a newline within `body` (the caller's outer capture stops right there).
    party_m = re.search(r"\.party = \(const struct TrainerMon\[\]\)\s*\{(.*?)\n        \},", body, re.S)
    if not party_m:
        return []
    mons = []
    for blk in re.findall(r"\{([^{}]*(?:\{[^{}]*\}[^{}]*)?)\}", party_m.group(1)):
        sp = re.search(r"\.species\s*=\s*(SPECIES_\w+)", blk)
        lvl = re.search(r"\.lvl\s*=\s*(\d+)", blk)
        if not (sp and lvl):
            continue
        item = re.search(r"\.heldItem\s*=\s*(ITEM_\w+)", blk)
        nat = re.search(r"\.nature\s*=\s*NATURE_(\w+)", blk)
        ivs = re.search(r"\.iv\s*=\s*TRAINER_PARTY_IVS\(([^)]*)\)", blk)
        mv = re.search(r"\.moves\s*=\s*\{([^}]*)\}", blk)
        mons.append({
            "species": sp[1], "level": int(lvl[1]),
            "item": item[1] if item and item[1] != "ITEM_NONE" else None,
            "nature": nat[1] if nat else None,
            "ivs": [int(x.strip()) for x in ivs[1].split(",")] if ivs else None,
            "moves": [mm.strip() for mm in mv[1].split(",") if mm.strip()] if mv else None,
        })
    return mons


def _species_info_blocks(src: Path) -> list[tuple[str, str]]:
    """[(SPECIES_X, body), ...] across every src/data/pokemon/species_info/gen_*_families.h
    file, in file order -- the same per-species struct-literal blocks
    parse_species_learnset_symbols() and rival_starter_lines() both read fields out of."""
    out = []
    for f in sorted((src / "src/data/pokemon/species_info").glob("gen_*_families.h")):
        out += re.findall(r"\[(SPECIES_\w+)\]\s*=\s*\{(.*?)\n    \},\n", read(f), re.S)
    return out


def parse_species_learnset_symbols(src: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for sp, body in _species_info_blocks(src):
        m = re.search(r"\.levelUpLearnset\s*=\s*(\w+),", body)
        if m:
            out.setdefault(sp, m.group(1))
    return out


def rival_starter_lines(src: Path, starters: tuple[str, ...]) -> dict[str, set[str]]:
    """starter (e.g. "MUDKIP") -> every SPECIES_X macro in its forward evolution family
    (base + each stage reached by that first stage's OWN first-listed .evolutions branch).
    Mirrors tools/gen_gen3_trainers.py's evolution.h-derived `lines` (same algorithm: walk
    forward from the starter), adapted to this fork's schema -- each species_info block
    carries its own targets directly (`.evolutions = EVOLUTION({EVO_METHOD, param,
    SPECIES_X}, ...)`), no separate evolution.h. Only the FIRST branch is followed: this
    build's starter chains (Treecko/Torchic/Mudkip) are single-branch, no CONDITIONS/#if
    (unlike e.g. Eevee) -- verified against src/data/pokemon/species_info/gen_3_families.h
    at the pin, so a second branch here would mean the pin changed and this needs revisiting,
    not a case to silently handle."""
    blocks = dict(_species_info_blocks(src))
    lines: dict[str, set[str]] = {}
    for s in starters:
        line: set[str] = set()
        sp = f"SPECIES_{s}"
        while sp and sp not in line:
            line.add(sp)
            m = re.search(r"\.evolutions\s*=\s*EVOLUTION\(\s*\{\s*EVO_\w+\s*,[^,]*,\s*(SPECIES_\w+)",
                          blocks.get(sp, ""))
            sp = m.group(1) if m else None
        lines[s] = line
    return lines


def parse_learnset_tables(src: Path) -> dict[str, list[tuple[int, str]]]:
    out: dict[str, list[tuple[int, str]]] = {}
    for f in sorted((src / "src/data/pokemon/level_up_learnsets").glob("gen_*.h")):
        for sym, body in re.findall(r"static const struct LevelUpMove (s\w+LevelUpLearnset)\[\] = \{(.*?)\};",
                                    read(f), re.S):
            out[sym] = [(int(lv), mv) for lv, mv in re.findall(r"LEVEL_UP_MOVE\(\s*(\d+),\s*(MOVE_\w+)\)", body)]
    return out


def parse_rematch_groups(battle_setup_c: str) -> list[tuple[list[str], str]]:
    """[(["TRAINER_WATTSON_1", ..., "TRAINER_WATTSON_5"], "MAP_MAUVILLE_CITY"), ...] from
    src/battle_setup.c's gRematchTable -- ground truth for where a Vs Seeker rematch tier is
    fought (include/battle_setup.h's `struct RematchTrainer {trainerIds[5]; mapGroup; mapNum}`,
    filled by this file's own `REMATCH(trainer1..5, map)` macro). Matches only real invocations
    ("[REMATCH_X] = REMATCH(...)"), never the macro's own `#define REMATCH(trainer1, ...)`
    signature line (no "=" precedes "REMATCH(" there)."""
    out = []
    for args in re.findall(r"=\s*REMATCH\(([^)]*)\)", battle_setup_c):
        parts = [p.strip() for p in args.split(",")]
        if len(parts) == 6:
            out.append((parts[:5], parts[5]))
        else:
            print(f"warning: gRematchTable REMATCH({args}) has {len(parts)} args, want 6 -- skipped",
                  file=sys.stderr)
    return out


def _check_area_map_digest(src: Path, area_map_path: Path) -> None:
    """Refuse a stale area_map.json: gen3_exp_areas.lua (its sibling output, owned by the same
    XC phase that owns area_map.json) records a `source_sha256` header over this pin's
    map_groups.json/region_map_sections.json/wild_encounters.json (tools/gen_area_map.py's
    _expansion_source_sha256, the same digest that binds gen3_exp_areas.lua to its inputs).
    If area_map.json/gen3_exp_areas.lua were built from a DIFFERENT source tree than `src` (a
    map reordering between expansion versions, say), map_area()'s "group:num" lookups could
    silently point at the wrong area -- so this must fail loudly, not use stale data quietly."""
    areas_lua = area_map_path.parent / "gen3_exp_areas.lua"
    if not areas_lua.exists():
        raise SystemExit(f"{areas_lua} not found -- can't verify {area_map_path} against this source tree")
    m = re.search(r"source_sha256:\s*([0-9a-f]{64})", read(areas_lua))
    if not m:
        raise SystemExit(f"{areas_lua} has no source_sha256 header to verify {area_map_path} against")
    recorded, actual = m.group(1), _expansion_source_sha256(src)
    if recorded != actual:
        raise SystemExit(f"{area_map_path} was built from a different source tree than {src} "
                          f"({areas_lua.name}'s source_sha256 {recorded} != {actual}) -- "
                          "regenerate the area map against this pin first")


def compute_bases(trainers: dict[int, dict]) -> dict[int, str]:
    """tid -> the Prep tab base name (text before " | ") for that trainer, never shared with any
    OTHER trainer id (see module docstring, OMP cx-081c78d3 F1)."""
    raw_base = {tid: " ".join(filter(None, [t["class"], t["name"]])).strip() or f"Trainer #{tid}"
                for tid, t in trainers.items()}
    groups: dict[str, list[int]] = {}
    for tid, b in raw_base.items():
        groups.setdefault(b, []).append(tid)
    bases: dict[int, str] = {}
    for b, tids in groups.items():
        if len(tids) == 1:
            bases[tids[0]] = b
            continue
        tiers = {}
        for tid in tids:
            m = re.search(r"_(\d+)$", trainers[tid]["const"])
            if m:
                tiers[tid] = int(m.group(1))
        # A recognisable rematch chain: every trainer in the collision has its own numeric
        # tier suffix (TRAINER_X_1..TRAINER_X_N), one trainer per tier, tiers 1..len(tids).
        if len(tiers) == len(tids) and sorted(tiers.values()) == list(range(1, len(tids) + 1)):
            for tid in tids:
                tier = tiers[tid]
                bases[tid] = b if tier == 1 else f"{b} Rematch {tier - 1}"
        else:
            # Generic name collision (e.g. two unrelated "GRUNT" trainers): dedupe by trainer
            # id, never by how many times a species has already seen this base (that count
            # depends on which species is asking, not on trainer identity).
            for i, tid in enumerate(sorted(tids)):
                bases[tid] = b if i == 0 else f"{b} ({i + 1})"
    return bases


def _dedupe_key(slot: dict, base: str) -> str:
    """`slot` is one species' setdex dict; return a "{base} | Emerald Expansion [...]" key that
    isn't already in it, so no party slot is ever silently dropped by a JS object literal
    collapsing two identical keys (see module docstring)."""
    key = f"{base} | Emerald Expansion "
    n = 2
    while key in slot:
        key = f"{base} | Emerald Expansion ({n}) "
        n += 1
    return key


def build(src: Path, area_map_path: Path = AREA_MAP) -> tuple[dict, dict]:
    """Return (gen3_exp_trainers.json dict, EmeraldExpansion.js CUSTOMSETDEX_EE dict)."""
    adapter = Gen3ExpansionAdapter(rom_type=ROM_TYPE)
    species_ids = enum_values(read(src / "include/constants/species.h"), "SPECIES_")
    move_ids = enum_values(read(src / "include/constants/moves.h"), "MOVE_")
    item_ids = enum_values(read(src / "include/constants/items.h"), "ITEM_")
    opp_ids = defines(read(src / "include/constants/opponents.h"), "TRAINER_")
    classes = class_names(read(src / "src/battle_main.c"))
    sp_learnset_sym = parse_species_learnset_symbols(src)
    learnset_tables = parse_learnset_tables(src)

    _check_area_map_digest(src, area_map_path)
    keys = map_keys(src)
    # This fork carries leftover/orphan map dirs (SecretBase_*, AbandonedShip_Underwater*, ...)
    # that have a map.json but are never listed under any data/maps/map_groups.json group.
    # area_of_map()'s BFS indexes `keys[mid]` unconditionally for each map's OWN id before
    # checking membership, so an orphan as its own BFS root raises KeyError; pret's tables never
    # hit this (nothing is left un-grouped there), so it's a fork-specific gap, not one to patch
    # in the shared tools/gen_gen3_trainers.py helper -- drop orphans here instead, before they
    # ever reach it. A trainerbattle in an orphan map (if any) simply gets no area.
    all_maps = map_jsons(src)
    grouped_maps = {name: m for name, m in all_maps.items() if m["id"] in keys}
    area_map = json.loads(read(area_map_path))
    map_area = area_of_map(grouped_maps, keys, area_map)
    tmaps = trainer_maps(src, all_maps)
    rival_lines = rival_starter_lines(src, STARTERS)

    def calc_species(sp_macro: str) -> str | None:
        sid = species_ids.get(sp_macro)
        return adapter.calc_species(sid) if sid is not None else None

    def calc_move(mv_macro: str) -> str:
        mid = move_ids.get(mv_macro)
        return adapter.calc_name("move", adapter.move_name(mid)) if mid else mv_macro

    def calc_item(it_macro: str) -> str:
        iid = item_ids.get(it_macro)
        return adapter.calc_name("item", adapter.item_name(iid)) if iid else it_macro

    def default_moveset(sp_macro: str, level: int) -> list[str]:
        sym = sp_learnset_sym.get(sp_macro)
        return default_moves(learnset_tables.get(sym, []), level) if sym else []

    # trainers.h is emitted with "#line N" directives (mapping back to trainers.party for
    # compiler errors) sprinkled between fields, including inside a `.moves = { ... }` list --
    # strip them before parsing so they never leak into a move/field token.
    trainers_h = re.sub(r"#line \d+\n\s*", "", read(src / "src/data/trainers.h"))

    trainers: dict[int, dict] = {}
    unresolved_species = 0
    for const, body in parse_trainer_blocks(trainers_h):
        tid = opp_ids.get(f"TRAINER_{const}")
        if tid is None:
            continue
        name_m = re.search(r'\.trainerName\s*=\s*_\("([^"]*)"\)', body)
        cls_m = re.search(r"\.trainerClass\s*=\s*TRAINER_CLASS_(\w+)", body)
        cls_key = cls_m.group(1) if cls_m else ""
        mons = parse_mons(body)
        party = []
        for mon in mons:
            sid = species_ids.get(mon["species"])
            if sid is None:
                unresolved_species += 1
                continue
            entry = {"species": adapter.calc_species(sid), "level": mon["level"]}
            if mon["item"]:
                entry["item"] = calc_item(mon["item"])
            mv_macros = ([m for m in mon["moves"] if m != "MOVE_NONE"] if mon["moves"] is not None
                        else default_moveset(mon["species"], mon["level"]))
            if mv_macros:
                entry["moves"] = [calc_move(m) for m in mv_macros]
            if mon["nature"]:
                entry["nature"] = pretty(mon["nature"].replace("_", " ").lower())
            if mon["ivs"] and len(mon["ivs"]) == 6:
                hp, atk, df, spe, spa, spd = mon["ivs"]
                entry["ivs"] = {"hp": hp, "atk": atk, "def": df, "spa": spa, "spd": spd, "spe": spe}
            abilities = adapter.species_abilities(sid)
            if abilities and abilities[0]:
                entry["ability"] = adapter.calc_name("ability", adapter.ability_name(abilities[0], sid))
            party.append(entry)
        t = {"const": f"TRAINER_{const}", "name": pretty(name_m.group(1)) if name_m else "",
             "class": pretty(classes.get(cls_key, "")) if classes.get(cls_key) else "", "party": party}
        areas = sorted({map_area[m] for m in tmaps.get(f"TRAINER_{const}", ()) if m in map_area})
        if areas:
            t["area"] = areas[0]
        if cls_key in KEY_CLASSES and party and f"TRAINER_{const}" not in UNBATTLED_KEY_CANDIDATES:
            t["key"] = True
            t["level_cap"] = max(p["level"] for p in party)
            # Upcoming Key Trainers panel row label (server.py _trainer_panel_html): distinct
            # fight_labels are what let it show Brendan/May's route/city starter-variant fights,
            # or a gym leader's Vs Seeker rematch tiers, as separate rows instead of merging same-
            # name/same-class encounters into one. Mirrors tools/gen_gen3_trainers.py's build()
            # exactly: "Rematch N" component first, starter-variant component second, joined with
            # " · " when both apply (never happens for THIS build's rivals -- see module docstring,
            # OMP cx-081c78d3 F2 -- but Wally's tiers get only the rematch half).
            fl = ""
            if any(const.endswith("_" + s) for s in STARTERS):
                mine = {m["species"] for m in mons}
                hits = [f"Rival has {s.title()}" for s in STARTERS if rival_lines[s] & mine]
                if len(hits) != 1:
                    raise SystemExit(f"TRAINER_{const}: party has {len(hits)} starter evolution "
                                      f"lines, want exactly 1: {sorted(mine)}")
                (fl,) = hits
            fl = " · ".join(filter(None, [_emerald_rematch(const, cls_key), fl]))
            if fl:
                t["fight_label"] = fl
        trainers[tid] = t

    # Rematch tiers (TRAINER_ROXANNE_2.._5 etc.) aren't triggered by a map trainerbattle script
    # at all (a separate rematch system re-fights the same NPC in place), so they never get an
    # area from tmaps. gRematchTable is the pinned source's own record of where each rematch
    # chain is fought -- fed through the same map_area BFS-fallback map every other area comes
    # from, so a map with no area of its own (Mt. Chimney) still resolves the same way a
    # trainerbattle script placed there would. This is the actual data, never a (class, name)
    # guess (OMP cx-081c78d3 F2) -- Brendan/May's 16 rival fights are NOT in gRematchTable at
    # all (they're ordinary trainerbattle scripts already found by tmaps above), so they get no
    # fallback here and simply keep whatever tmaps found, or no area.
    for const_names, map_name in parse_rematch_groups(read(src / "src/battle_setup.c")):
        area = map_area.get(map_name)
        if not area:
            continue
        for const_name in const_names:
            tid = opp_ids.get(const_name)
            if tid in trainers:
                # setdefault, never overwrite: a trainerbattle script area (tmaps, above) is
                # ground truth for where THIS fight actually happens and must win over a
                # gRematchTable guess; among multiple REMATCH rows naming the same trainer (not
                # seen in this build, but the table format allows it), the first row wins too.
                trainers[tid].setdefault("area", area)

    bases = compute_bases(trainers)
    for tid, t in trainers.items():
        t["calc_label"] = bases[tid]

    by_area: dict[str, list[int]] = {}
    for tid, t in sorted(trainers.items()):
        if t.get("key") and t.get("area"):
            by_area.setdefault(t["area"], []).append(tid)

    exp_json = {
        "_note": "GENERATED by tools/gen_gen3_exp_trainers.py from pokeemerald-expansion "
                 "src/data/trainers.h -- do not edit. Keys are gTrainers indexes = the wire "
                 "trainer_id. See the tool docstring for every rule.",
        "source": {"repo": "rh-hideout/pokeemerald-expansion", "tag": "expansion/1.17.0",
                   "commit": "e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7"},
        "trainers": {str(k): v for k, v in sorted(trainers.items())},
        "trainers_by_area": dict(sorted(by_area.items())),
    }

    setdex: dict[str, dict[str, dict]] = {}
    for tid, t in sorted(trainers.items()):
        base = bases[tid]
        for mon in t["party"]:
            sp = mon["species"]
            if not sp:
                continue
            # Every party mon in this build has an explicit .iv = TRAINER_PARTY_IVS(...) (module
            # docstring; verified: one .iv per .species in src/data/trainers.h, always). A
            # missing ivs here means the .iv parse regex silently failed on some mon, not that
            # this trainer really has no IVs -- refuse rather than fake a perfect-31 spread that
            # would read as real (never-verified) data (card XC4c item 5).
            if not mon.get("ivs"):
                raise SystemExit(f"TRAINER_{trainers[tid]['const']}: {sp} lvl {mon['level']} has "
                                  "no ivs -- an .iv = TRAINER_PARTY_IVS(...) parse must have failed")
            iv = mon["ivs"]
            slot = setdex.setdefault(sp, {})
            key = _dedupe_key(slot, base)
            slot[key] = {
                "index": f"32{tid:010d}",
                "level": mon["level"],
                "ability": mon.get("ability", ""),
                "item": mon.get("item", "None") or "None",
                "nature": mon.get("nature", "Hardy"),
                # ivs dict from mon uses atk/def/spa/spd/spe keys; the setdex convention is
                # at/df/sa/sd/sp -- remap here rather than carrying two shapes through the module.
                "ivs": {"hp": iv["hp"], "at": iv["atk"], "df": iv["def"],
                        "sa": iv["spa"], "sd": iv["spd"], "sp": iv["spe"]},
                "moves": (mon.get("moves") or []) + ["No Move"] * (4 - len(mon.get("moves") or [])),
            }

    if unresolved_species:
        print(f"warning: {unresolved_species} party slots had an unresolved SPECIES_ macro", file=sys.stderr)
    return exp_json, setdex


def render_js(setdex: dict) -> str:
    header = '''// Extracted (not hand-vendored) from rh-hideout/pokeemerald-expansion, tag expansion/1.17.0,
// commit e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7 (data/gen3_exp_sources.lock.json), by
// tools/gen_gen3_exp_trainers.py. Full coverage: every DIFFICULTY_NORMAL party slot in
// src/data/trainers.h, not a curated subset -- species, level, held item, moves (explicit or
// the level-up-learnset default), nature and IV are all read directly from the compiled trainer
// table (this build never needs personality-hash reconstruction the way vanilla pret Emerald
// does). Ability is always the species' slot-0 ability (no trainer sets one explicitly in this
// build; include/config/battle.h's B_TRAINER_MON_RANDOM_ABILITY == 0 confirms the game itself
// resolves it the same way).
//
// Trainer name collisions ("GRUNT" x53, "MAY"/"BRENDAN" x16 each) do NOT merge in the Prep
// tab: compute_bases() (tools/gen_gen3_exp_trainers.py) gives every trainer id its own unique
// base text before " | " -- a Vs Seeker rematch chain (TRAINER_X_1..5) gets "<base> Rematch N",
// any other same-name collision gets "<base> (2)", "<base> (3)", ... by trainer id order (OMP
// cx-081c78d3 F1, fixed XC4b; see tests/unit/test_gen3_expansion_trainer_sets.py's
// test_no_base_name_maps_to_more_than_one_trainer_index). Full coverage is still whole-file:
// every DIFFICULTY_NORMAL party slot in src/data/trainers.h is present here, not a subset.
'''
    lines = [header, "var CUSTOMSETDEX_EE = {"]
    species_items = sorted(setdex.items())
    for i, (sp, sets) in enumerate(species_items):
        obj = dict(sorted(sets.items()))  # one compact JSON object per species line (Emerald.js's density)
        lines.append(f'{json.dumps(sp)}:{json.dumps(obj, ensure_ascii=False)}' + ("," if i < len(species_items) - 1 else ""))
    lines.append("};")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", type=Path, required=True, help="local copy of the pinned expansion source tree")
    ap.add_argument("--area-map", type=Path, default=AREA_MAP)
    ap.add_argument("--out-json", type=Path, default=OUT_JSON)
    ap.add_argument("--out-js", type=Path, default=OUT_JS)
    ap.add_argument("--check", action="store_true", help="exit 1 if either output differs from a regeneration")
    a = ap.parse_args()
    if not a.src.exists():
        print(f"source not found: {a.src}", file=sys.stderr)
        return 2
    exp_json, setdex = build(a.src, a.area_map)
    json_text = json.dumps(exp_json, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    js_text = render_js(setdex)
    if a.check:
        ok = True
        for path, text in ((a.out_json, json_text), (a.out_js, js_text)):
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                print(f"{path} is stale -- re-run tools/gen_gen3_exp_trainers.py", file=sys.stderr)
                ok = False
        if ok:
            print("gen3_exp trainer sets are up to date")
        return 0 if ok else 1
    a.out_json.write_text(json_text, encoding="utf-8", newline="\n")
    a.out_js.write_text(js_text, encoding="utf-8", newline="\n")
    print(f"wrote {a.out_json}\nwrote {a.out_js}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
