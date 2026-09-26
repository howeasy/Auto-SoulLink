#!/usr/bin/env python3
"""Generate data/games/gen3_frlge/frlg_trainers.json from the pinned pret pokefirered source.

Owner ruling 28 (2026-09-26): trainer names, Upcoming Key Trainers and the calc Prep tab on
vanilla FireRed/LeafGreen. The adapter (server/adapters/gen3_frlge.py) reads this file and holds
no game facts of its own. Written against pokefirered; the pret root, area map, setdex and output
are arguments so the Emerald lane can point it at pokeemerald.

Facts and where they come from (all pret, never Radical Red):
  id        gTrainers index = the TRAINER_* value in include/constants/opponents.h. gTrainers is a
            designated-initializer array (`[TRAINER_X] = {...}` in src/data/trainers.h), and the
            Gen 3 client reports gTrainerBattleOpponent_A, which CreateNPCTrainerParty indexes
            gTrainers with (src/battle_main.c). So wire trainer_id == json key, no offset.
  name      .trainerName, title-cased. RIVAL_EARLY / RIVAL_LATE / CHAMPION print the player-chosen
            rival name instead (src/battle_message.c), so those get name "" and rival: true.
  class     gTrainerClassNames (src/data/text/trainer_class_names.h), title-cased.
  party     src/data/trainer_parties.h. Explicit .moves when the struct has them, otherwise the
            level-up moves GiveBoxMonInitialMoveset (src/pokemon.c) gives: walk the learnset up to
            the level, skip a known move, push out the first move when all four are full
            (gen3_frlge.default_moves; `learnsets` ships the tables it walks).
            Species/move/item ids are named through the server's own vanilla Gen 3 tables in
            calc spelling, the same names the live battle feed uses.
  area      the map whose script runs the trainerbattle (data/maps/*/scripts.inc directly, or a
            data/scripts/*.inc label named by a map's object event), then the nearest map over
            warps/connections that the area map knows. The client keeps the last known area
            while it stands in an unmapped map (a gym, a hideout floor), and that is the town or
            dungeon it walked in from. Vs Seeker rematch tiers take their base trainer's area
            (sRematches in src/vs_seeker.c).
  key       KEY RULE: class LEADER, ELITE_FOUR, CHAMPION, RIVAL_EARLY, RIVAL_LATE or BOSS, or a
            TEAM_ROCKET trainer whose constant says ADMIN. Key trainers carry level_cap (their
            highest party level) and, for starter-dependent or rematch fights, fight_label.
  calc_label the setdex trainer key (text before " | ") whose fight has exactly this party's
            species/level set; failing that, the key naming this trainer that shares the most of
            it (the setdex splits a fight with a repeated species over "(1)"/"(2)" keys). None
            found -> omitted, and the bridge falls back to species/level.

FR and LG share one table: pret has no FIRERED/LEAFGREEN conditional in trainers.h,
trainer_parties.h or the class names (checked here, the build fails if one appears).

    python tools/gen_gen3_trainers.py            # regenerate
    python tools/gen_gen3_trainers.py --check    # exit 1 if the committed json is stale
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# GiveBoxMonInitialMoveset lives with the adapter: a randomized cartridge's default-move parties
# (read from the ROM) get their moves from the same rule and the learnsets emitted below.
from server.adapters.gen3_frlge import default_moves  # noqa: E402

OUT = ROOT / "data/games/gen3_frlge/frlg_trainers.json"
AREA_MAP = ROOT / "data/games/gen3_frlge/area_map.json"
SETDEX = ROOT / "calc/src/js/data/sets/games/FRLG.js"
LOCK = ROOT / "data/gen3_sources.lock.json"
TITLES = ["firered", "leafgreen"]

KEY_CLASSES = {"LEADER", "ELITE_FOUR", "CHAMPION", "RIVAL_EARLY", "RIVAL_LATE", "BOSS"}
RIVAL_NAME_CLASSES = {"RIVAL_EARLY", "RIVAL_LATE", "CHAMPION"}
STARTERS = ("BULBASAUR", "CHARMANDER", "SQUIRTLE")


def find_pret(env=os.environ) -> Path:
    """tests/unit/gen3_pret.py's lookup: $SLINK_PRET_FIRERED_SRC, else .cache/pret up the tree."""
    if env.get("SLINK_PRET_FIRERED_SRC"):
        return Path(env["SLINK_PRET_FIRERED_SRC"])
    rel = ".cache/pret/pokefirered"
    return next((d / rel for d in (ROOT, *ROOT.parents) if (d / rel).exists()), ROOT / rel)


def git_head(path: Path) -> str | None:
    r = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def canon(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def pretty(s: str) -> str:
    s = s.replace("{PKMN}", "POKéMON").strip()
    return s.title() if s else ""


def defines(text: str, prefix: str) -> dict[str, int]:
    return {m[0]: int(m[1], 0) for m in re.findall(rf"#define\s+({prefix}\w+)\s+(\w+)\b", text)
            if re.fullmatch(r"0x[0-9A-Fa-f]+|\d+", m[1])}


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def learnsets(root: Path) -> dict[str, list[tuple[int, str]]]:
    arrays = {name: [(int(lv), mv) for lv, mv in re.findall(r"LEVEL_UP_MOVE\(\s*(\d+),\s*(MOVE_\w+)\)", body)]
              for name, body in re.findall(r"const u16 (s\w+LevelUpLearnset)\[\] = \{(.*?)\};",
                                           read(root / "src/data/pokemon/level_up_learnsets.h"), re.S)}
    return {sp: arrays[arr] for sp, arr in re.findall(r"\[(SPECIES_\w+)\]\s*=\s*(s\w+LevelUpLearnset)",
                                                      read(root / "src/data/pokemon/level_up_learnset_pointers.h"))}


def parse_parties(root: Path) -> dict[str, list[dict]]:
    out = {}
    # one-line bodies are the RS dummies (`= {DUMMY_TRAINER_MON};`): no fields, empty party
    for name, body in re.findall(r"static const struct TrainerMon\w+ (sParty_\w+)\[\] = \{(\n.*?\n|[^\n]*)\};",
                                 read(root / "src/data/trainer_parties.h"), re.S):
        mons = []
        for blk in re.findall(r"\{([^{}]*(?:\{[^{}]*\}[^{}]*)?)\}", body):
            lvl = re.search(r"\.lvl\s*=\s*(\d+)", blk)
            sp = re.search(r"\.species\s*=\s*(SPECIES_\w+)", blk)
            if not (lvl and sp):
                continue
            item = re.search(r"\.heldItem\s*=\s*(ITEM_\w+)", blk)
            mv = re.search(r"\.moves\s*=\s*\{([^}]*)\}", blk)
            mons.append({"species": sp[1], "level": int(lvl[1]), "item": item[1] if item else None,
                         "moves": [m.strip() for m in mv[1].split(",") if m.strip()] if mv else None})
        out[name] = mons
    return out


def parse_trainers(root: Path) -> list[dict]:
    rows = []
    for const, body in re.findall(r"\[(TRAINER_\w+)\]\s*=\s*\{(.*?)\n    \},", read(root / "src/data/trainers.h"), re.S):
        cls = re.search(r"\.trainerClass\s*=\s*TRAINER_CLASS_(\w+)", body)
        name = re.search(r'\.trainerName\s*=\s*_\("([^"]*)"\)', body)
        party = re.search(r"\.party\s*=\s*(?:\w+\(\s*(sParty_\w+)\s*\)|\{\s*\.\w+\s*=\s*(sParty_\w+)\s*\})", body)
        rows.append({"const": const, "class": cls[1] if cls else "",  # TRAINER_NONE: no class
                     "name": name[1] if name else "",
                     "party": (party[1] or party[2]) if party else None})
    return rows


def map_keys(root: Path) -> dict[str, str]:
    """MAP_* id -> 'group:num' (data/maps/map_groups.json order, as the client reads it)."""
    groups = json.loads(read(root / "data/maps/map_groups.json"))
    out = {}
    for g, gname in enumerate(groups["group_order"]):
        for n, mname in enumerate(groups[gname]):
            out[json.loads(read(root / "data/maps" / mname / "map.json"))["id"]] = f"{g}:{n}"
    return out


def map_jsons(root: Path) -> dict[str, dict]:
    return {p.parent.name: json.loads(read(p)) for p in sorted((root / "data/maps").glob("*/map.json"))}


def trainer_maps(root: Path, maps: dict[str, dict]) -> dict[str, set[str]]:
    """TRAINER_* -> {MAP_*} whose script runs its trainerbattle."""
    by_label: dict[str, set[str]] = {}
    out: dict[str, set[str]] = {}
    for inc in sorted([*(root / "data/maps").glob("*/scripts.inc"), *(root / "data/scripts").glob("*.inc")]):
        owner = maps[inc.parent.name]["id"] if inc.parent.parent.name == "maps" else None
        label = None
        for line in read(inc).splitlines():
            m = re.match(r"^(\w+)::?\s*$", line)
            if m:
                label = m[1]
                continue
            t = re.match(r"\s*trainerbattle\w*\s+(TRAINER_\w+)", line)
            if t:
                if owner:
                    out.setdefault(t[1], set()).add(owner)
                elif label:
                    by_label.setdefault(label, set()).add(t[1])
    for m in maps.values():
        for ev in m.get("object_events") or []:
            for tr in by_label.get(ev.get("script", ""), ()):
                out.setdefault(tr, set()).add(m["id"])
    return out


def area_of_map(maps: dict[str, dict], keys: dict[str, str], area_map: dict[str, str]) -> dict[str, str]:
    """MAP_* -> area id: its own, else the nearest mapped map over warps/connections (BFS, ties
    broken by area id)."""
    adj: dict[str, set[str]] = {}
    for m in maps.values():
        nb = {w["dest_map"] for w in m.get("warp_events") or []}
        nb |= {c["map"] for c in m.get("connections") or []}
        adj[m["id"]] = {x for x in nb if x in keys}
    out = {}
    for mid in adj:
        seen, frontier = {mid}, [mid]
        while frontier:
            hits = sorted({area_map[keys[x]] for x in frontier if keys[x] in area_map})
            if hits:
                out[mid] = hits[0]
                break
            nxt = sorted({y for x in frontier for y in adj.get(x, ()) if y not in seen})
            seen |= set(nxt)
            frontier = nxt
    return out


def load_setdex(path: Path) -> dict:
    text = "\n".join(ln for ln in read(path).splitlines() if not ln.strip().startswith("//")).strip()
    body = text[text.index("=") + 1:].strip().rstrip(";")
    return json.loads(re.sub(r",\s*([\]}])", r"\1", body))


def setdex_fights(setdex: dict) -> tuple[dict[frozenset, set[str]], dict[str, set]]:
    """(fight pairs -> {trainer key}, trainer key -> every pair under it). Pairs are
    (canon species, level) SETS: the setdex is keyed species -> fight, so it can't hold a species
    twice in one fight and splits such a fight over "... (1)" / "... (2)" keys instead. The trainer
    key is the text before " | ", the bridge's _buildTrainerIndex key."""
    fights: dict[str, set] = {}
    for species, sets in setdex.items():
        for full, s in sets.items():
            fights.setdefault(full, set()).add((canon(species), s["level"]))
    exact: dict[frozenset, set[str]] = {}
    by_key: dict[str, set] = {}
    for full, c in fights.items():
        key = full.split(" | ")[0].strip()
        exact.setdefault(frozenset(c), set()).add(key)
        by_key.setdefault(key, set()).update(c)
    return exact, by_key


def names_trainer(key: str, who: str) -> bool:
    """`key` spells `who` in some run of its words, allowing the setdex's typos (Glen for GLENN,
    Valeri for VALERIE, "Gia and Ges" for GIA & JES)."""
    words, w = key.split(), canon(who)
    return any(difflib.SequenceMatcher(None, canon(" ".join(words[i:j])), w).ratio() >= 0.66
               for i in range(len(words)) for j in range(i + 1, len(words) + 1))


def calc_label(pairs: frozenset, who: str, exact: dict, by_key: dict) -> str | None:
    """Among the setdex keys that name `who` -- those fighting exactly `pairs` if any, else all --
    the one sharing the most pairs, and at least half: a fight the setdex split, or a setdex level
    typo. Parties alone aren't enough: Black Belt Shea's set equals Takashi's once duplicates fold."""
    named = [k for k in (exact.get(pairs) or by_key) if names_trainer(k, who)]
    scored = sorted(((len(pairs & by_key[k]), k) for k in named), reverse=True)
    if scored and 2 * scored[0][0] >= len(pairs) and (len(scored) == 1 or scored[1][0] < scored[0][0]):
        return scored[0][1]
    return None


def build(root: Path, area_map_path: Path = AREA_MAP, setdex_path: Path = SETDEX) -> dict:
    from server.adapters.gen3_frlge import Gen3Adapter  # vanilla id -> calc-spelling names
    names = Gen3Adapter(is_rr=False, rom_type="firered")

    for f in ("src/data/trainers.h", "src/data/trainer_parties.h", "src/data/text/trainer_class_names.h"):
        if re.search(r"^\s*#\s*if.*(FIRERED|LEAFGREEN)", read(root / f), re.M):
            raise SystemExit(f"{f} has a FIRERED/LEAFGREEN conditional: split the table by title")

    opp = defines(read(root / "include/constants/opponents.h"), "TRAINER_")
    species = defines(read(root / "include/constants/species.h"), "SPECIES_")
    moves = defines(read(root / "include/constants/moves.h"), "MOVE_")
    items = defines(read(root / "include/constants/items.h"), "ITEM_")
    class_names = dict(re.findall(r'\[TRAINER_CLASS_(\w+)\]\s*=\s*_\("([^"]*)"\)',
                                  read(root / "src/data/text/trainer_class_names.h")))
    parties = parse_parties(root)
    ls = learnsets(root)
    maps = map_jsons(root)
    keys = map_keys(root)
    area_map = json.loads(read(area_map_path))
    map_area = area_of_map(maps, keys, area_map)
    tmaps = trainer_maps(root, maps)
    exact, by_key = setdex_fights(load_setdex(setdex_path))

    def move_name(m: str) -> str:
        return names.calc_name("move", names.move_name(moves[m]))

    trainers: dict[int, dict] = {}
    for row in parse_trainers(root):
        tid = opp[row["const"]]
        rival = row["class"] in RIVAL_NAME_CLASSES
        party = []
        for mon in parties.get(row["party"], []):
            entry = {"species": names.calc_species(species[mon["species"]]), "level": mon["level"]}
            if mon["item"] and items[mon["item"]]:
                entry["item"] = names.calc_name("item", names.item_name(items[mon["item"]]))
            mv = ([m for m in mon["moves"] if m != "MOVE_NONE"] if mon["moves"] is not None
                  else default_moves(ls[mon["species"]], mon["level"]))
            entry["moves"] = [move_name(m) for m in mv]
            party.append(entry)
        t = {"const": row["const"], "name": "" if rival else pretty(row["name"]),
             "class": pretty(class_names.get(row["class"], "")), "party": party}
        if rival:
            t["rival"] = True
        areas = sorted({map_area[m] for m in tmaps.get(row["const"], ()) if m in map_area})
        if areas:
            t["area"] = areas[0]
        key = row["class"] in KEY_CLASSES or (row["class"] == "TEAM_ROCKET" and "ADMIN" in row["const"])
        if key and party:
            t["key"] = True
            t["level_cap"] = max(p["level"] for p in party)
            label = next((f"Rival has {s.title()}" for s in STARTERS if row["const"].endswith("_" + s)), "")
            if "_REMATCH" in row["const"] or (row["class"] == "ELITE_FOUR" and re.search(r"_\d+$", row["const"])):
                label = " · ".join(filter(None, ["Rematch", label]))
            if label:
                t["fight_label"] = label
        label = party and calc_label(frozenset((canon(p["species"]), p["level"]) for p in party),
                                     t["name"] or "Rival", exact, by_key)
        if label:
            t["calc_label"] = label
        trainers[tid] = t

    # Vs Seeker rematch tiers fight where their base trainer stands.
    for row in re.findall(r"\{\s*\{([^}]*)\}", read(root / "src/vs_seeker.c").split("sRematches[]", 1)[1].split("};", 1)[0]):
        ids = [opp[c] for c in re.findall(r"TRAINER_\w+", row)]
        base = trainers.get(ids[0], {}).get("area") if ids else None
        for i in ids[1:]:
            if base and "area" not in trainers[i]:
                trainers[i]["area"] = base

    by_area: dict[str, list[int]] = {}
    for tid, t in sorted(trainers.items()):
        if t.get("key") and t.get("area"):
            by_area.setdefault(t["area"], []).append(tid)
    return {
        "_note": "GENERATED by tools/gen_gen3_trainers.py from pret pokefirered -- do not edit. "
                 "Keys are gTrainers indexes = the wire trainer_id (gTrainerBattleOpponent_A). "
                 "See the tool docstring for every rule (key, area, calc_label, default moves).",
        "source": {"repo": "pret/pokefirered", "commit": git_head(root)},
        "titles": TITLES,
        "shared": True,
        "trainers": {str(k): v for k, v in sorted(trainers.items())},
        "trainers_by_area": dict(sorted(by_area.items())),
        # species id -> [[level, move id], ...]: pret's level-up learnsets (movesets may not be
        # randomized, owner ruling 31), for the default moves of a randomized cartridge's parties.
        "learnsets": {str(species[sp]): [[lv, moves[m]] for lv, m in learnset]
                      for sp, learnset in sorted(ls.items(), key=lambda kv: species[kv[0]])},
    }


def dump(data: dict) -> str:
    lines = ["{"]
    items = list(data.items())
    for i, (k, v) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        if isinstance(v, dict) and k in ("trainers", "trainers_by_area", "learnsets"):
            lines.append(f"  {json.dumps(k)}: {{")
            sub = list(v.items())
            for j, (sk, sv) in enumerate(sub):
                lines.append(f"    {json.dumps(sk)}: {json.dumps(sv, ensure_ascii=False)}" + ("," if j < len(sub) - 1 else ""))
            lines.append("  }" + comma)
        else:
            lines.append(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}{comma}")
    return "\n".join(lines + ["}"]) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pret", type=Path, default=None, help="pret checkout (default: pinned pokefirered)")
    ap.add_argument("--area-map", type=Path, default=AREA_MAP)
    ap.add_argument("--setdex", type=Path, default=SETDEX)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--check", action="store_true", help="exit 1 if --out differs from a regeneration")
    a = ap.parse_args()
    root = a.pret or find_pret()
    if not root.exists():
        print(f"pret source not found: {root} (set SLINK_PRET_FIRERED_SRC)", file=sys.stderr)
        return 2
    if a.pret is None:
        pin = json.loads(read(LOCK))["source"]["commit"]
        if git_head(root) != pin:
            print(f"{root} is at {git_head(root)}, not the pin {pin} ({LOCK.name})", file=sys.stderr)
            return 2
    text = dump(build(root, a.area_map, a.setdex))
    if a.check:
        if not a.out.exists() or a.out.read_text(encoding="utf-8") != text:
            print(f"{a.out} is stale -- re-run tools/gen_gen3_trainers.py", file=sys.stderr)
            return 1
        print(f"{a.out.name} is up to date")
        return 0
    a.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
