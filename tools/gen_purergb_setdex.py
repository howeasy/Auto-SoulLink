"""Generate calc/src/js/data/sets/games/PureRGB.js: pureRGB trainer sets for the damage calc.

Same vendored-set shape as calc/src/js/data/sets/games/RedBlue.js etc:
    var CUSTOMSETDEX_PURERGB = {"<species calc name>": {"<label>": {
        "index": <cosmetic, unread by any calc code - see below>,
        "level": <int>,
        "dvs": {"hp":8,"at":9,"df":8,"sa":8,"sd":8,"sp":8},
        "stat_exp": {"hp":0,"atk":0,"def":0,"spe":0,"spc":0},
        "moves": [<calc move name>, ...] (always length 4, "No Move" padded)
    }, ...}, ...};

Source: data/games/gen1_purergb/trainers.json (56 trainer classes, 492 party records, parsed
from the pureRGB ROM's own TrainerDataPointers table - see that file's "source"/"schema" keys)
plus the pinned pureRGB source checkout (tools/gen1_foundation.py) for the two things
trainers.json does not carry: which moves a trainer's Pokémon actually has, and Gen 1's DVs.

Moves, two cases (docs/purergb/ engine, both traced directly against source, not guessed):
  * Explicit moveset (grammar "FD", trainers.json "moveset" is the custom_movesets.asm constant
    name, e.g. "METRONOME_GAMBLER_MOVESET"): engine/battle/read_trainer_party.asm's
    .CustomMovesetTrainer -> engine/battle/special_moves.asm's LoadTrainerMoveSet copies NUM_MOVES
    (4) bytes per party mon *sequentially* out of one flat per-trainer move list in
    data/trainers/custom_movesets.asm (verified: every one of the 35 explicit-moveset records in
    trainers.json has exactly party_size*4 bytes in its moveset's flat list - see
    _custom_movesets()).
  * No explicit moveset (grammar "fixed"/"FE"/"FF", the other 457 records): every party mon is
    built by engine/pokemon/add_mon.asm's _AddPartyMon, which (a) seeds the mon's 4 move slots
    from its species' base_stats "level 1 learnset" 4-tuple (data/pokemon/base_stats/<name>.asm),
    then (b) unconditionally calls engine/pokemon/evos_moves.asm's WriteMonMoves: walk
    data/pokemon/evos_moves.asm's per-species learnset (ascending level, terminated by the first
    entry above the mon's level, per that file's own "increasing level order" comment) and for
    each learnable move not already known, fill the first empty (NO_MOVE) slot, or once all 4
    slots are full, shift the array left by one and append (drops the oldest move) - see
    default_moves(). Same algorithm vanilla Gen 1 uses for wild/un-scripted trainer Pokémon.

DVs: constants/battle_constants.asm:73-74 (pureRGB, unchanged from vanilla) -
`ATKDEFDV_TRAINER EQU $98` (high nibble 9 = Atk DV, low nibble 8 = Def DV),
`SPDSPCDV_TRAINER EQU $88` (Spd DV 8, Spc DV 8) - _AddPartyMon loads these two bytes verbatim for
every enemy trainer mon. HP DV is the standard Gen 1 derivation (bit 3/2/1/0 = LSB of
Atk/Def/Spd/Spc DV) which for 9/8/8/8 is always 8 - same constant vanilla's own trainers use
(RedBlue.js/Yellow.js's own "dvs" fields agree). Stat exp is 0 per PURERGB_MECHANICS.md §1.9
(pureRGB trainers get nonzero stat exp only under an opt-in options toggle the calc doesn't
model) - shared_controls.js's createPokemon() reads it as an explicit "stat_exp" field
(calc/src/js/shared_controls.js ~990).

"index": every vendored sibling file (RedBlue.js etc) carries this field but nothing in
calc/src/js ever reads a set's `.index` (grepped) - it is cosmetic/vestigial from the upstream
vendor's own generator. Emitted here only to match the sibling files' shape; value is an
arbitrary deterministic counter, never consumed.

One known gap: trainers.json's GYM_GUIDE class (id 250) fields a party-slot MISSINGNO (internal
id 181, classification "missingno"). purergb.ts deliberately drops the "missingno"/"unused"/
"picture_only" classifications (see tools/gen_purergb_calc_patch.py's INCLUDED_CLASSIFICATIONS
and docs/calc_multigen/PURERGB_MECHANICS.md §2), so the calc has no species data for it; that one
party slot is skipped (logged to stderr) rather than emitting a set the calc can't render. Every
other species referenced by trainers.json resolves against purergb.ts's SPECIES_DATA (verified by
tests/unit/test_calc_purergb.py).

Usage:
    python tools/gen_purergb_setdex.py           # write calc/src/js/data/sets/games/PureRGB.js
    python tools/gen_purergb_setdex.py --check    # exit 1 if the file would change

The check ignores LF/CRLF checkout differences, but still rejects generated content drift.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
# Reuses its species-name builders + the git-worktree-safe SLINK_PURERGB_SRC resolver.
import gen_purergb_calc_patch as gpc  # noqa: E402

DATA_DIR = REPO / "data" / "games" / "gen1_purergb"
OUT_PATH = REPO / "calc" / "src" / "js" / "data" / "sets" / "games" / "PureRGB.js"

# The 4 ordinary species whose ROM display name doesn't lowercase straight into its
# base_stats/<file>.asm name (same 4 as gpc.ORDINARY_NAME_FIXUPS, keyed by the ROM's raw
# all-caps species_index.json "name" field rather than the calc's Title Case spelling).
FILENAME_FIXUPS = {"NIDORAN♂": "nidoranm", "NIDORAN♀": "nidoranf",
                    "MR.MIME": "mrmime", "FARFETCH'D": "farfetchd"}

# constants/battle_constants.asm:73-74 - see module docstring.
DVS = {"hp": 8, "at": 9, "df": 8, "sa": 8, "sd": 8, "sp": 8}
STAT_EXP = {"hp": 0, "atk": 0, "def": 0, "spe": 0, "spc": 0}


def load_json(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def _label_blocks(text: str) -> dict[str, str]:
    """{label: its own source slice}, splitting on column-0 `Label:` lines (evos_moves.asm,
    custom_movesets.asm - both plain "one block per Pokemon/moveset" data files, no nested
    labels)."""
    positions = [(m.start(), m.group(1)) for m in re.finditer(r"^(\w+):\s*$", text, re.M)]
    return {name: text[start:(positions[i + 1][0] if i + 1 < len(positions) else len(text))]
            for i, (start, name) in enumerate(positions)}


def species_calc_names(purergb_root: Path, species_index: dict) -> dict[int, str]:
    """internal species id -> the exact calc species name purergb.ts uses (ordinary/form/spirit),
    via the same name builders tools/gen_purergb_calc_patch.py uses for purergb.ts itself."""
    ordinary_names = gpc.build_ordinary_names(purergb_root)
    form_names = gpc.build_form_names(purergb_root)
    out: dict[int, str] = {}
    for idx_str, entry in species_index["species"].items():
        idx = int(idx_str)
        classification = entry["classification"]
        if classification == "ordinary":
            out[idx] = ordinary_names[idx]
        elif classification == "form":
            name = form_names.get(idx)
            if name:
                out[idx] = name
        elif classification == "spirit":
            out[idx] = " ".join(gpc.title_case_word(w) for w in entry["name"].split(" "))
        # "unused"/"missingno"/"picture_only": not in purergb.ts either - left unresolved.
    return out


def constant_to_index(purergb_root: Path) -> dict[str, int]:
    """ROM species constant name (as trainers.json's "species" lists spell it) -> internal id."""
    text = (purergb_root / "constants" / "pokemon_constants.asm").read_text(encoding="utf-8")
    return {m.group(1): int(m.group(2), 16)
            for m in re.finditer(r"const\s+([A-Z0-9_]+)\s*;\s*\$([0-9A-Fa-f]+)", text)}


def load_calc_move_map(purergb_root: Path) -> dict[str, str]:
    """ROM move constant name (asm MOVE_NAME token) -> the calc's display name, via moves.json's
    internal_name field and the same calc_names.json rename table purergb.ts's moves use (see
    docs/calc_multigen/PURERGB_MECHANICS.md's "Naming policy: moves")."""
    moves = load_json("moves.json")["moves"]
    calc_names = gpc.load_calc_move_names()
    out = {"NO_MOVE": "No Move"}
    for m in moves:
        out[m["internal_name"]] = calc_names.get(m["name"], m["name"])
    return out


def base_stats_filename(entry: dict) -> str:
    rom_name = entry["name"]
    return FILENAME_FIXUPS.get(rom_name, rom_name.lower().replace(" ", "_"))


def base_moveset(purergb_root: Path, filename: str) -> list[str]:
    """The species' fixed "level 1 learnset" 4-tuple (data/pokemon/base_stats/<name>.asm) - the
    starting point _AddPartyMon seeds every enemy mon's move slots with."""
    path = purergb_root / "data" / "pokemon" / "base_stats" / f"{filename}.asm"
    text = path.read_text(encoding="utf-8")
    m = re.search(r"db\s+([A-Z0-9_]+),\s*([A-Z0-9_]+),\s*([A-Z0-9_]+),\s*([A-Z0-9_]+)"
                  r"\s*;\s*level 1 learnset", text)
    if not m:
        raise ValueError(f"no level-1 learnset line in {path}")
    return list(m.groups())


def evos_moves_learnsets(purergb_root: Path) -> dict[int, list[tuple[int, str]]]:
    """internal species id -> [(level, move constant), ...] in ascending level order.

    data/pokemon/evos_moves.asm's EvosMovesPointerTable is indexed by internal id directly
    (position i, 1-based, is species id i - verified: entry 1 is RhydonEvosMoves/Rhydon=id 1,
    entry 9 is IvysaurEvosMoves/Ivysaur=id 9, 190 entries total = species_index.json's full slot
    count). Evolution lines (db EVOLVE_LEVEL/EVOLVE_ITEM/EVOLVE_TRADE, ...) never match the
    2-argument "db <digits>, <MOVE>" learnset-line shape, so no separate "skip the evolutions
    section" parsing is needed.
    """
    text = (purergb_root / "data" / "pokemon" / "evos_moves.asm").read_text(encoding="utf-8")
    table = re.search(r"EvosMovesPointerTable:(.*?)\n\s*\n", text, re.S).group(1)
    order = re.findall(r"dw\s+(\w+)", table)
    blocks = _label_blocks(text)
    learnsets: dict[int, list[tuple[int, str]]] = {}
    for idx, label in enumerate(order, start=1):
        pairs = []
        for line in blocks.get(label, "").splitlines():
            line = line.split(";", 1)[0].strip()
            m = re.match(r"db\s+(\d+)\s*,\s*([A-Z0-9_]+)\s*$", line)
            if m:
                pairs.append((int(m.group(1)), m.group(2)))
        learnsets[idx] = pairs
    return learnsets


def custom_movesets(purergb_root: Path) -> dict[str, list[str]]:
    """trainers.json "moveset" constant name -> flat move-constant list (party_size*4 long, 4
    consecutive moves per party mon in order - data/trainers/custom_movesets.asm, applied by
    engine/battle/special_moves.asm's LoadTrainerMoveSet)."""
    text = (purergb_root / "data" / "trainers" / "custom_movesets.asm").read_text(encoding="utf-8")
    consts = re.findall(r"const\s+(\w+)",
                         re.search(r"const_def\s+1(.*?)\n\s*\n", text, re.S).group(1))
    labels = re.findall(r"dw\s+(\w+)",
                         re.search(r"MoveSetMappings:(.*?)\n\s*\n", text, re.S).group(1))
    const_to_label = dict(zip(consts, labels, strict=True))
    blocks = _label_blocks(text)

    def flat(label: str) -> list[str]:
        out = []
        for line in blocks.get(label, "").splitlines():
            line = line.split(";", 1)[0].strip()
            m = re.match(r"db\s+([A-Z0-9_]+)\s*$", line)
            if m:
                out.append(m.group(1))
        return out

    return {const: flat(label) for const, label in const_to_label.items()}


def default_moves(base4: list[str], learnset: list[tuple[int, str]], level: int) -> list[str]:
    """The 4 move slots WriteMonMoves (engine/pokemon/evos_moves.asm) computes: seed with the
    species' base moveset, then apply each learnset move at or below `level` in order - fill an
    empty (NO_MOVE) slot if one exists, else shift the 4 slots left and append (drop the oldest)."""
    slots = list(base4)
    for lvl, move in learnset:
        if lvl > level:
            break  # learnset is level-sorted; WriteMonMoves stops at the first move above level
        if move in slots:
            continue
        if "NO_MOVE" in slots:
            slots[slots.index("NO_MOVE")] = move
        else:
            slots = slots[1:] + [move]
    return slots


def generate() -> tuple[str, list[str]]:
    gpc._resolve_purergb_src_env()
    purergb_root = gpc.gf.source_root("purergb")

    species_index = load_json("species_index.json")
    trainers = load_json("trainers.json")

    sp_names = species_calc_names(purergb_root, species_index)
    const_idx = constant_to_index(purergb_root)
    move_map = load_calc_move_map(purergb_root)
    learnsets = evos_moves_learnsets(purergb_root)
    movesets = custom_movesets(purergb_root)
    base_cache: dict[int, list[str]] = {}

    def species_name(const: str) -> str | None:
        idx = const_idx.get(const)
        return sp_names.get(idx) if idx is not None else None

    def base_of(idx: int, entry: dict) -> list[str]:
        if idx not in base_cache:
            base_cache[idx] = base_moveset(purergb_root, base_stats_filename(entry))
        return base_cache[idx]

    warnings: list[str] = []
    out: dict[str, dict[str, dict]] = {}
    label_counts: dict[tuple[str, str], int] = {}
    counter = 0

    rival_ids = set(trainers["rival_ids"])
    for class_id_str in sorted(trainers["classes"], key=int):
        cls = trainers["classes"][class_id_str]
        class_id = int(class_id_str)
        # Same casing server/adapters/gen1_purergb.py's _display_case()/trainer_info() apply to
        # this exact field, so a label here reads the same as the server's own trainer name.
        class_label = "Rival" if class_id in rival_ids else (
            cls["name"].title() if cls["name"].isupper() else cls["name"])
        for rec_num, rec in enumerate(cls["records"], start=1):
            species_list = rec["species"]
            n = len(species_list)
            levels = rec["level"] if isinstance(rec["level"], list) else [rec["level"]] * n
            moveset_flat = movesets.get(rec["moveset"]) if rec["moveset"] else None
            label_base = f"{class_label} {rec_num} | pureRGB"
            for i, const in enumerate(species_list):
                idx = const_idx.get(const)
                entry = species_index["species"].get(str(idx)) if idx is not None else None
                name = sp_names.get(idx) if idx is not None else None
                if not entry or name is None:
                    warnings.append(f"class {class_id} ({cls['class']}) record {rec_num}: "
                                     f"species {const!r} has no calc name (classification "
                                     f"{entry['classification'] if entry else '?'}); mon skipped")
                    continue
                level = levels[i]
                if moveset_flat is not None:
                    move_consts = moveset_flat[i * 4:(i + 1) * 4]
                else:
                    move_consts = default_moves(base_of(idx, entry), learnsets.get(idx, []), level)
                moves = []
                for mv in move_consts:
                    calc_mv = move_map.get(mv)
                    if calc_mv is None:
                        raise ValueError(f"unknown move constant {mv!r} ({const} in class "
                                          f"{class_id} record {rec_num})")
                    moves.append(calc_mv)

                key = (name, label_base)
                label_counts[key] = label_counts.get(key, 0) + 1
                n_dupe = label_counts[key]
                label = label_base if n_dupe == 1 else f"{label_base} ({n_dupe})"

                counter += 1
                out.setdefault(name, {})[label] = {
                    "index": f"1{counter:011d}",
                    "level": level,
                    "dvs": dict(DVS),
                    "stat_exp": dict(STAT_EXP),
                    "moves": moves,
                }

    # One species per line (like the vendored sets beside it): compact, still diffable.
    body = "{\n" + ",\n".join(
        json.dumps(sp, ensure_ascii=False) + ":"
        + json.dumps(out[sp], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        for sp in sorted(out)) + "\n}"
    header = (
        "// AUTO-GENERATED by tools/gen_purergb_setdex.py --check. Do not hand-edit.\n"
        "// Source: data/games/gen1_purergb/trainers.json (parsed from the pureRGB ROM's own\n"
        "// TrainerDataPointers), plus the pinned pureRGB source checkout for move data (level-up\n"
        "// learnsets, custom trainer movesets) and DVs. See tools/gen_purergb_setdex.py's module\n"
        "// docstring for the exact rule + source citations.\n"
    )
    text = f'{header}var CUSTOMSETDEX_PURERGB = {body};\n'
    return text.replace("\n", "\r\n"), warnings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if the output would change")
    args = ap.parse_args()

    generated, warnings = generate()
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)

    if args.check:
        current = None
        if OUT_PATH.is_file():
            with open(OUT_PATH, encoding="utf-8", newline="") as f:
                current = f.read()
        # Git's LF blob and a Windows CRLF checkout contain the same generated sets.
        if current is None or current.replace("\r\n", "\n") != generated.replace("\r\n", "\n"):
            print(f"{OUT_PATH} is stale; run tools/gen_purergb_setdex.py", file=sys.stderr)
            return 1
        print("PureRGB.js is up to date")
        return 0

    with open(OUT_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(generated)
    print(f"wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
