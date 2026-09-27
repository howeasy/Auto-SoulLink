#!/usr/bin/env python3
"""Generate the vanilla Gen 3 trainer tables from pinned pret source, one schema, one code path:
data/games/gen3_frlge/frlg_trainers.json (pret pokefirered) and
data/games/gen3_emerald/emerald_trainers.json (pret pokeemerald). GAMES holds the per-game rules.

Owner ruling 28 (2026-09-26): trainer names, Upcoming Key Trainers and the calc Prep tab on
vanilla FireRed/LeafGreen and Emerald. The adapter (server/adapters/gen3_frlge.py) reads these
files and holds no game facts of its own.

Facts and where they come from (all pret, never Radical Red):
  id        gTrainers index = the TRAINER_* value in include/constants/opponents.h. gTrainers is a
            designated-initializer array (`[TRAINER_X] = {...}` in src/data/trainers.h), and the
            Gen 3 client reports gTrainerBattleOpponent_A, which CreateNPCTrainerParty indexes
            gTrainers with (src/battle_main.c). So wire trainer_id == json key, no offset.
  name      .trainerName, title-cased. FR/LG RIVAL_EARLY / RIVAL_LATE / CHAMPION print the
            player-chosen rival name instead (src/battle_message.c), so those get name "" and
            rival: true. Emerald has no such substitution: May, Brendan and Wally keep theirs.
  class     gTrainerClassNames (src/data/text/trainer_class_names.h), title-cased.
  party     src/data/trainer_parties.h. Explicit .moves when the struct has them, otherwise the
            level-up moves GiveBoxMonInitialMoveset (src/pokemon.c) gives: walk the learnset up to
            the level, skip a known move, push out the first move when all four are full
            (gen3_frlge.default_moves; `learnsets` ships the tables it walks).
            Learnsets are PER TITLE: pret level_up_learnsets.h has #if FIRERED / LEAFGREEN
            branches (Deoxys's forme, Dugtrio's move order), evaluated by title_branch().
            `learnsets` is the first title's table; `learnsets_by_title` holds, for each other
            title, only the species whose learnset differs. Trainer parties are shared, and the
            build fails if another title's learnsets would change any trainer's default moves.
            Species/move/item ids are named through the server's own vanilla Gen 3 tables in
            calc spelling, the same names the live battle feed uses.
  area      the map whose script runs the trainerbattle (every TRAINER_* on the line but the
            TRAINER_BATTLE_* mode, so `trainerbattle TRAINER_BATTLE_SET_TRAINER_A,
            TRAINER_MAXIE_MOSSDEEP` counts; data/maps/*/scripts.inc directly, or a
            data/scripts/*.inc label named by a map's object event), including the opponent
            arguments of expansion's multi-battle macros, then the nearest map over
            warps/connections that the area map knows. The client keeps the last known area
            while it stands in an unmapped map (a gym, a hideout floor), and that is the town or
            dungeon it walked in from. Rematch tiers take their base trainer's area (FR/LG
            sRematches in src/vs_seeker.c, Emerald gRematchTable in src/battle_setup.c).
  key       KEY RULE: a trainer with a party that some map script fights (it has an area) and a
            key class. FR/LG: LEADER, ELITE_FOUR, CHAMPION, RIVAL_EARLY, RIVAL_LATE, BOSS, or a
            TEAM_ROCKET trainer whose constant says ADMIN. Emerald: LEADER, ELITE_FOUR, CHAMPION,
            RIVAL (May, Brendan, Wally, Steven), MAGMA_LEADER, AQUA_LEADER, MAGMA_ADMIN,
            AQUA_ADMIN (the team bosses and admins, as Giovanni and the Rocket admins in FR/LG).
            Key trainers carry level_cap (their highest party level) and, for starter-dependent
            or rematch fights, fight_label: "Rival has <starter>" (the starter whose evolution
            line is in the party; the constant suffix names the rival's starter in FR/LG but the
            player's in Emerald); FR/LG "Rematch"; Emerald "Rematch <n>" for the _<n+1> tier.
  calc_label the setdex trainer key (text before " | ") whose fight has exactly this party's
            species/level set; failing that, the key naming this trainer that shares the most of
            it (the setdex splits a fight with a repeated species over "(1)"/"(2)" keys).
            Emerald.js keys a Brendan fight "<Town> Rival", so a named RIVAL-class trainer with
            no label retries as "Rival". None found -> omitted; the bridge falls back to
            species/level.

FR and LG share one trainer table: pret has no FIRERED/LEAFGREEN conditional in trainers.h,
trainer_parties.h or the class names (checked here, the build fails if one appears).

    python tools/gen_gen3_trainers.py [--game frlg|emerald]            # regenerate
    python tools/gen_gen3_trainers.py [--game frlg|emerald] --check    # exit 1 if stale
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
# the pokeemerald commit data/gen3/pret/pokeemerald.sym was published from (PLAN.md E0)
EMERALD_PROVENANCE = ROOT / "data/gen3/pret/pokeemerald_provenance.json"
TITLES = ["firered", "leafgreen"]


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _frlg_rematch(const: str, cls: str) -> str:
    return "Rematch" if "_REMATCH" in const or (cls == "ELITE_FOUR" and re.search(r"_\d+$", const)) else ""


def _emerald_rematch(const: str, cls: str) -> str:
    m = re.search(r"_(\d+)$", const)
    return f"Rematch {int(m[1]) - 1}" if m and int(m[1]) > 1 else ""


GAMES = {
    "frlg": {
        "repo": "pret/pokefirered", "clone": "pokefirered", "env": "SLINK_PRET_FIRERED_SRC",
        "pin": lambda: json.loads(read(LOCK))["source"]["commit"],
        "titles": TITLES, "out": OUT, "area_map": AREA_MAP, "setdex": SETDEX,
        "key_classes": {"LEADER", "ELITE_FOUR", "CHAMPION", "RIVAL_EARLY", "RIVAL_LATE", "BOSS"},
        "admin_class": "TEAM_ROCKET",
        "rival_name_classes": {"RIVAL_EARLY", "RIVAL_LATE", "CHAMPION"},
        "starters": ("BULBASAUR", "CHARMANDER", "SQUIRTLE"),
        "rematches": ("src/vs_seeker.c", "sRematches[]", r"\{\s*\{([^}]*)\}"),
        "rematch_label": _frlg_rematch,
        "unused": set(),
    },
    "emerald": {
        "repo": "pret/pokeemerald", "clone": "pokeemerald", "env": "SLINK_PRET_EMERALD_SRC",
        "pin": lambda: json.loads(read(EMERALD_PROVENANCE))["origin"]["source_commit"],
        "titles": ["emerald"],
        "out": ROOT / "data/games/gen3_emerald/emerald_trainers.json",
        "area_map": ROOT / "data/games/gen3_emerald/area_map.json",
        "setdex": ROOT / "calc/src/js/data/sets/games/Emerald.js",
        "key_classes": {"LEADER", "ELITE_FOUR", "CHAMPION", "RIVAL", "MAGMA_LEADER", "AQUA_LEADER",
                        "MAGMA_ADMIN", "AQUA_ADMIN"},
        "admin_class": None,
        "rival_name_classes": set(),
        "starters": ("TREECKO", "TORCHIC", "MUDKIP"),
        "rematches": ("src/battle_setup.c", "gRematchTable[", r"REMATCH\(([^)]*)\)"),
        "rematch_label": _emerald_rematch,
        # link-battle save-slot placeholders (RED/LEAF/BRENDAN_PLACEHOLDER/MAY_PLACEHOLDER carry
        # Charmander/Bulbasaur/Groudon/Kyogre Lv5): no data/maps or data/scripts trainerbattle, nor
        # any other reference, fights them (verified 2026-09-26 against pret pokeemerald
        # c65e93f20a5275ab03b07d6f6411096a82a60ffd). Excluded so trainer_brief never surfaces one.
        "unused": {"TRAINER_RED", "TRAINER_LEAF", "TRAINER_BRENDAN_PLACEHOLDER", "TRAINER_MAY_PLACEHOLDER"},
    },
}
KEY_CLASSES = GAMES["frlg"]["key_classes"]
RIVAL_NAME_CLASSES = GAMES["frlg"]["rival_name_classes"]
STARTERS = GAMES["frlg"]["starters"]


def find_pret(env=os.environ, game: str = "frlg") -> Path:
    """tests/unit/gen3_pret.py's lookup: the game's $SLINK_PRET_*_SRC, else .cache/pret up the tree."""
    g = GAMES[game]
    if env.get(g["env"]):
        return Path(env[g["env"]])
    rel = f".cache/pret/{g['clone']}"
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


def _title_cond(cond: str, title: str) -> bool:
    """A pret #if condition over FIRERED/LEAFGREEN, `title`'s macro the one defined."""
    py = re.sub(r"defined\s*\(\s*(\w+)\s*\)|defined\s+(\w+)", lambda m: m[1] or m[2], cond)
    py = re.sub(r"\b(FIRERED|LEAFGREEN)\b", lambda m: str(m[1] == title.upper()), py)
    py = py.replace("&&", " and ").replace("||", " or ").replace("!", " not ")
    if not re.fullmatch(r"(\s|True|False|and|or|not|\(|\))*", py):
        raise SystemExit(f"unsupported per-title #if condition: {cond.strip()!r}")
    return bool(eval(py))  # noqa: S307 - the fullmatch above admits only booleans and logic


def title_branch(text: str, title: str) -> str:
    """`text` as the C preprocessor builds it for `title`, for the #if/#ifdef/#ifndef/#elif/#else
    blocks that name FIRERED or LEAFGREEN (their directives dropped). A conditional that names
    neither is kept whole (directives and body) ONLY when it is a proven top-of-file include
    guard -- the file's very first non-blank line is `#ifndef NAME`, `NAME` a bare identifier,
    and its matching #endif is the file's last non-blank line. Any other non-title conditional,
    or a per-title #ifdef/#ifndef with anything past the bare macro name (e.g. `#ifdef
    FIRERED && X`, which is not valid C but was silently evaluated False), is unresolvable and
    raises (Codex review cx-6b3b8309 finding 1: both branches, or a wrong silent False, used to
    ship instead)."""
    lines = text.splitlines(keepends=True)
    nonblank = [i for i, ln in enumerate(lines) if ln.strip()]
    first_nb, last_nb = (nonblank[0], nonblank[-1]) if nonblank else (None, None)
    out, stack = [], []   # per open block: [names a title, branch is live, a branch was taken, is guard]
    for idx, line in enumerate(lines):
        m = re.match(r"\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)", line)
        kind, cond = (m[1], m[2]) if m else ("", "")
        titled = bool(re.search(r"\b(FIRERED|LEAFGREEN)\b", cond))
        if kind in ("if", "ifdef", "ifndef"):
            if titled:
                if kind == "if":
                    live = _title_cond(cond, title)
                else:
                    name = cond.strip()
                    if name not in ("FIRERED", "LEAFGREEN"):
                        raise SystemExit(f"unsupported #{kind} condition: {cond.strip()!r}")
                    live = (name == title.upper()) != (kind == "ifndef")
                stack.append([True, live, live, False])
                continue
            is_guard = (kind == "ifndef" and not stack and idx == first_nb
                        and re.fullmatch(r"\w+", cond.strip()))
            if not is_guard:
                raise SystemExit("unsupported conditional (names neither FIRERED nor LEAFGREEN, "
                                  f"and isn't a top-of-file include guard): {line.strip()!r}")
            stack.append([False, True, True, True])
        elif kind == "elif":
            if not stack:
                raise SystemExit(f"#elif with no open #if: {line.strip()!r}")
            if titled != stack[-1][0]:
                raise SystemExit(f"#elif mixes per-title and other conditions: {line.strip()!r}")
            if titled:
                live = not stack[-1][2] and _title_cond(cond, title)
                stack[-1][1:3] = [live, stack[-1][2] or live]
                continue
        elif kind == "else":
            if not stack:
                raise SystemExit(f"#else with no open #if: {line.strip()!r}")
            if stack[-1][0]:
                stack[-1][1] = not stack[-1][2]
                continue
        elif kind == "endif":
            if not stack:
                raise SystemExit(f"#endif with no open #if: {line.strip()!r}")
            frame = stack.pop()
            if frame[3] and idx != last_nb:
                raise SystemExit(f"include guard's #endif is not the file's last line: {line.strip()!r}")
            if frame[0]:
                continue
        if all(f[1] for f in stack):
            out.append(line)
    return "".join(out)


def learnsets(root: Path, title: str) -> dict[str, list[tuple[int, str]]]:
    """SPECIES_* -> [(level, MOVE_*)], as `title` is built."""
    src = title_branch(read(root / "src/data/pokemon/level_up_learnsets.h"), title)
    arrays = {name: [(int(lv), mv) for lv, mv in re.findall(r"LEVEL_UP_MOVE\(\s*(\d+),\s*(MOVE_\w+)\)", body)]
              for name, body in re.findall(r"const u16 (s\w+LevelUpLearnset)\[\] = \{(.*?)\};", src, re.S)}
    ptrs = title_branch(read(root / "src/data/pokemon/level_up_learnset_pointers.h"), title)
    return {sp: arrays[arr] for sp, arr in re.findall(r"\[(SPECIES_\w+)\]\s*=\s*(s\w+LevelUpLearnset)", ptrs)}


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


# expansion e8bd1cd7: asm/macros/battle_frontier/battle_tower.inc:121-160 and
# asm/macros/event.inc:2674-2682. Zero-based opponent slots only: loss text and
# partner ids are not opponents. multi_wild/multi_do (and fixed variants) have none.
_MULTI_TRAINER_ARGS = {
    "multi_2_vs_2": (0, 2), "multi_fixed_2_vs_2": (0, 2),
    "multi_2_vs_1": (0,), "multi_fixed_2_vs_1": (0,),
    "setmultitrainerbattle": (0, 2),
}


def trainer_maps(root: Path, maps: dict[str, dict]) -> dict[str, set[str]]:
    """TRAINER_* -> {MAP_*} whose script battles that opponent."""
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
            if re.match(r"\s*trainerbattle\w*\s", line):
                trainers = re.findall(r"\bTRAINER_(?!BATTLE_)\w+", line)
            elif (command := re.match(r"\s*(\w+)\s+(.+)", line)) and command[1] in _MULTI_TRAINER_ARGS:
                args = [arg.strip() for arg in command[2].split("@", 1)[0].split(",")]
                trainers = [args[i] for i in _MULTI_TRAINER_ARGS[command[1]]
                            if i < len(args) and re.fullmatch(r"TRAINER_(?!BATTLE_)\w+", args[i])
                            and args[i] != "TRAINER_NONE"]
            else:
                continue
            for tr in trainers:
                if owner:
                    out.setdefault(tr, set()).add(owner)
                elif label:
                    by_label.setdefault(label, set()).add(tr)
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
    typo. Parties alone aren't enough: Black Belt Shea's set equals Takashi's once duplicates fold.

    A single-mon party has no partial-overlap signal to trust, so it never falls back to `by_key`:
    only an EXACT species+level match counts (Codex review cx-6b3b8309 finding 5 -- the by_key
    fallback let a lone Numel 20 take Mt Chimney's combined Numel+Zubat "Magma Grunt" fight, and a
    lone Mightyena 32 take an unrelated "Magma Grunt 5" fight at the same level)."""
    if len(pairs) == 1:
        named = [k for k in (exact.get(pairs) or ()) if names_trainer(k, who)]
        return named[0] if len(named) == 1 else None
    named = [k for k in (exact.get(pairs) or by_key) if names_trainer(k, who)]
    scored = sorted(((len(pairs & by_key[k]), k) for k in named), reverse=True)
    if scored and 2 * scored[0][0] >= len(pairs) and (len(scored) == 1 or scored[1][0] < scored[0][0]):
        return scored[0][1]
    return None


def build(root: Path, area_map_path: Path | None = None, setdex_path: Path | None = None,
          game: str = "frlg") -> dict:
    from server.adapters.gen3_frlge import Gen3Adapter  # vanilla id -> calc-spelling names
    g = GAMES[game]
    titles = g["titles"]
    names = Gen3Adapter(is_rr=False, rom_type=titles[0])

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
    ls_by_title = {t: learnsets(root, t) for t in titles}
    ls = ls_by_title[titles[0]]
    maps = map_jsons(root)
    keys = map_keys(root)
    area_map = json.loads(read(area_map_path or g["area_map"]))
    map_area = area_of_map(maps, keys, area_map)
    tmaps = trainer_maps(root, maps)
    exact, by_key = setdex_fights(load_setdex(setdex_path or g["setdex"]))

    evos = {sp: set(re.findall(r"SPECIES_\w+", body)) for sp, body in re.findall(
        r"\[(SPECIES_\w+)\]\s*=\s*\{(.*?)\}\},", read(root / "src/data/pokemon/evolution.h"), re.S)}
    lines = {}                                            # starter -> its evolution line
    for s in g["starters"]:
        line, todo = set(), [f"SPECIES_{s}"]
        while todo:
            line.add(sp := todo.pop())
            todo += evos.get(sp, set()) - line
        lines[s] = line

    rows = [r for r in parse_trainers(root) if r["const"] not in g["unused"]]
    area = {}
    for row in rows:
        hits = sorted({map_area[m] for m in tmaps.get(row["const"], ()) if m in map_area})
        if hits:
            area[row["const"]] = hits[0]
    # Rematch tiers fight where their base trainer stands.
    src, start, pattern = g["rematches"]
    for tiers in re.findall(pattern, read(root / src).split(start, 1)[1].split("};", 1)[0]):
        consts = re.findall(r"TRAINER_\w+", tiers)
        for c in consts[1:]:
            if consts[0] in area:
                area.setdefault(c, area[consts[0]])

    def move_name(m: str) -> str:
        return names.calc_name("move", names.move_name(moves[m]))

    trainers: dict[int, dict] = {}
    for row in rows:
        tid = opp[row["const"]]
        rival = row["class"] in g["rival_name_classes"]
        party = []
        for mon in parties.get(row["party"], []):
            entry = {"species": names.calc_species(species[mon["species"]]), "level": mon["level"]}
            if mon["item"] and items[mon["item"]]:
                entry["item"] = names.calc_name("item", names.item_name(items[mon["item"]]))
            if mon["moves"] is not None:
                mv = [m for m in mon["moves"] if m != "MOVE_NONE"]
            else:
                mv = default_moves(ls[mon["species"]], mon["level"])
                for other in titles[1:]:
                    if default_moves(ls_by_title[other][mon["species"]], mon["level"]) != mv:
                        raise SystemExit(f"{row['const']}: {other} default moves differ: split the table by title")
            entry["moves"] = [move_name(m) for m in mv]
            party.append(entry)
        t = {"const": row["const"], "name": "" if rival else pretty(row["name"]),
             "class": pretty(class_names.get(row["class"], "")), "party": party}
        if rival:
            t["rival"] = True
        if row["const"] in area:
            t["area"] = area[row["const"]]
        key = row["class"] in g["key_classes"] or (row["class"] == g["admin_class"] and "ADMIN" in row["const"])
        if key and party and "area" in t:
            t["key"] = True
            t["level_cap"] = max(p["level"] for p in party)
            label = ""
            if any(row["const"].endswith("_" + s) for s in g["starters"]):
                # FR/LG's suffix names the rival's starter, Emerald's the PLAYER's: read the party
                mine = {m["species"] for m in parties[row["party"]]}
                hits = [f"Rival has {s.title()}" for s in g["starters"] if lines[s] & mine]
                if len(hits) != 1:
                    raise SystemExit(f"{row['const']}: party has {len(hits)} starter evolution "
                                      f"lines, want exactly 1: {sorted(mine)}")
                (label,) = hits
            label = " · ".join(filter(None, [g["rematch_label"](row["const"], row["class"]), label]))
            if label:
                t["fight_label"] = label
        if party:
            pairs = frozenset((canon(p["species"]), p["level"]) for p in party)
            label = calc_label(pairs, t["name"] or "Rival", exact, by_key)
            if not label and row["class"] == "RIVAL" and t["name"]:
                label = calc_label(pairs, "Rival", exact, by_key)
            if label:
                t["calc_label"] = label
        trainers[tid] = t

    by_area: dict[str, list[int]] = {}
    for tid, t in sorted(trainers.items()):
        if t.get("key") and t.get("area"):
            by_area.setdefault(t["area"], []).append(tid)
    by_title = {}
    for t in titles[1:]:
        diff = {sp: lst for sp, lst in ls_by_title[t].items() if ls.get(sp) != lst}
        by_title[t] = {str(species[sp]): [[lv, moves[m]] for lv, m in lst]
                       for sp, lst in sorted(diff.items(), key=lambda kv: species[kv[0]])}
    out = {
        "_note": f"GENERATED by tools/gen_gen3_trainers.py from {g['repo']} -- do not edit. "
                 "Keys are gTrainers indexes = the wire trainer_id (gTrainerBattleOpponent_A). "
                 "See the tool docstring for every rule (key, area, calc_label, default moves).",
        "source": {"repo": g["repo"], "commit": git_head(root)},
        "titles": titles,
        "shared": True,
        "trainers": {str(k): v for k, v in sorted(trainers.items())},
        "trainers_by_area": dict(sorted(by_area.items())),
        # species id -> [[level, move id], ...]: pret's level-up learnsets for titles[0] (movesets
        # may not be randomized, owner ruling 31), for the default moves of a randomized
        # cartridge's parties. learnsets_by_title: another title's species that differ.
        "learnsets": {str(species[sp]): [[lv, moves[m]] for lv, m in learnset]
                      for sp, learnset in sorted(ls.items(), key=lambda kv: species[kv[0]])},
    }
    if any(by_title.values()):
        out["learnsets_by_title"] = by_title
    return out


def dump(data: dict) -> str:
    lines = ["{"]
    items = list(data.items())
    for i, (k, v) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        if isinstance(v, dict) and k in ("trainers", "trainers_by_area", "learnsets", "learnsets_by_title"):
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
    ap.add_argument("--game", choices=sorted(GAMES), default="frlg")
    ap.add_argument("--pret", type=Path, default=None, help="pret checkout (default: the pinned clone)")
    ap.add_argument("--area-map", type=Path, default=None)
    ap.add_argument("--setdex", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--check", action="store_true", help="exit 1 if --out differs from a regeneration")
    a = ap.parse_args()
    g = GAMES[a.game]
    out = a.out or g["out"]
    root = a.pret or find_pret(game=a.game)
    if not root.exists():
        print(f"pret source not found: {root} (set {g['env']})", file=sys.stderr)
        return 2
    if a.pret is None and git_head(root) != g["pin"]():
        print(f"{root} is at {git_head(root)}, not the pin {g['pin']()}", file=sys.stderr)
        return 2
    text = dump(build(root, a.area_map, a.setdex, game=a.game))
    if a.check:
        if not out.exists() or out.read_text(encoding="utf-8") != text:
            print(f"{out} is stale -- re-run tools/gen_gen3_trainers.py --game {a.game}", file=sys.stderr)
            return 1
        print(f"{out.name} is up to date")
        return 0
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
