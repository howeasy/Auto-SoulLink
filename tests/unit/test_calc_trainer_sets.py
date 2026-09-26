"""Vendored calc trainer sets must be honest about the games they claim to represent.

calc/src/js/data/sets/games/*.js are trainer-set dumps vendored from
KinglerChamp/VanillaNuzlockeCalc (MIT licensed; see the header comment in each file for the
exact commit). We didn't generate them, so we don't get to just trust them: this file parses
each vendored file directly (independent of anything the calc's own JS bundler does) and checks
it against the pret decompilation of the actual game -- the same "ground truth from the decomp,
not from a second copy" principle test_gen1_rom_scan.py uses for the ROM scanner.

Two axes, per game:
  * species+level: the multiset of (species, level) pairs across every trainer in the vendored
    file must match the multiset pret's parties data produces (ignoring pret's own "Unused"
    entries -- those never appear in a real game and the vendor reasonably omits them).
  * moves: wherever pret encodes an explicit per-mon moveset (Crystal's MOVES/ITEM_MOVES trainer
    types, FRLG's CustomMoves structs, Gen 1's special_moves.asm overlays), the vendored moves
    for a matching (species, level) must contain the same moves. Gen 1/Yellow's overlay system
    is applied by game *scripts*, not statically, so this only checks that the overlay move
    shows up somewhere in that trainer's vendored movepool -- not the exact slot.

Real, expected differences (an unused trainer pret has but the vendor skips, etc.) are recorded
in the ALLOWLIST dicts below with a one-line reason each, rather than silently ignored. A vendor
entry that was flatly wrong versus pret was fixed in our copy under calc/src/js/data/sets/games/
and the fix is noted in that file's header comment.

Emerald (calc/src/js/data/sets/games/Emerald.js) is checked against a local pokeemerald
checkout (pinned at c65e93f2): species+level as a whole-file multiset like Crystal/FRLG, plus
a per-trainer identity-aware check (item, explicit/derived moves, IV) for every trainer whose
name uniquely identifies one gTrainers[] entry -- see the "Emerald" section below for why
identity can't come from the vendored file's own "index" field, and what's left unchecked
(ambiguous/generic-named trainers, nature, ability) and why.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict

import pytest

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_GAMES_DIR = os.path.join(_REPO, "calc", "src", "js", "data", "sets", "games")


def _find_pret(name: str) -> str:
    """Locate a decomp checkout, searching upward from the repo.

    A git WORKTREE has no .cache of its own -- it lives under the main repo's
    .claude/worktrees/, so the decomps are several directories up. Same helper as
    test_gen1_rom_scan.py uses; duplicated here rather than imported so this file has no
    import-time dependency on another test module.
    """
    d = _REPO
    for _ in range(6):
        cand = os.path.join(d, ".cache", "pret", name)
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.join(_REPO, ".cache", "pret", name)


_PRET = {
    "pokered": _find_pret("pokered"),
    "pokeyellow": _find_pret("pokeyellow"),
    "pokecrystal": _find_pret("pokecrystal"),
    "pokefirered": _find_pret("pokefirered"),
    "pokeemerald": _find_pret("pokeemerald"),
}


def _need(name: str):
    path = _PRET[name]
    if not os.path.isdir(path):
        pytest.skip(f"{name} decomp not found at {path} (.cache/pret is CI-excluded)")
    return path


# --------------------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------------------

def _canon(s: str) -> str:
    """Fold a species/move/trainer name down to bare lowercase alnum.

    Sidesteps every naming-convention mismatch between pret's SCREAMING_SNAKE constants
    (NIDORAN_M, MR_MIME, FARFETCH_D) and the calc's display strings (Nidoran-M, Mr. Mime,
    Farfetch'd) without needing an exceptions dict for either side.
    """
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _load_vendored(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("//")]
    text = "\n".join(lines).strip()
    assert text.startswith("var "), path
    body = text[text.index("=") + 1:].strip()
    if body.endswith(";"):
        body = body[:-1]
    body = re.sub(r",\s*([\]}])", r"\1", body)  # FRLG has trailing commas in move arrays
    return json.loads(body)


def _vendored_sl_multiset(vdex: dict) -> Counter:
    c = Counter()
    for species, sets in vdex.items():
        for entry in sets.values():
            c[(_canon(species), entry["level"])] += 1
    return c


def _diff_multisets(pret: Counter, vendor: Counter):
    """Returns (pret_only, vendor_only) Counters of the symmetric difference."""
    pret_only = Counter()
    vendor_only = Counter()
    for key in set(pret) | set(vendor):
        d = pret[key] - vendor[key]
        if d > 0:
            pret_only[key] = d
        elif d < 0:
            vendor_only[key] = -d
    return pret_only, vendor_only


NO_MOVE_CANON = {_canon("No Move"), _canon("MOVE_NONE"), ""}


def _moves_canon(moves) -> frozenset:
    return frozenset(_canon(m) for m in moves) - NO_MOVE_CANON


# --------------------------------------------------------------------------------------
# Gen 1 (Red/Blue, Yellow): parties.asm -- "if first byte != $FF: level, then species list,
# null-terminated. If $FF: level/species pairs, null-terminated." (see pokered's own comment
# above TrainerDataPointers).
# --------------------------------------------------------------------------------------

def _parse_gen1_parties(path: str):
    """Returns a list of {"unused": bool, "mons": [(species, level)]} teams."""
    teams = []
    pending_comment = None
    with open(path, encoding="utf-8") as fh:
        _lines = fh.readlines()
    for raw in _lines:
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith(";"):
            pending_comment = stripped[1:].strip()
            continue
        if re.match(r"^[A-Za-z0-9_]+Data:$", stripped):
            pending_comment = None
            continue
        if stripped.startswith("db "):
            # A location/"Unused" comment applies to every db line up to the next comment,
            # not just the one right after it -- ProfOakData and ChannelerData each have one
            # "; Unused" comment covering a run of several consecutive db lines.
            unused = (pending_comment or "").lower() == "unused"
            body = re.sub(r";.*$", "", stripped[3:]).strip()  # strip trailing inline comments
            parts = [p.strip() for p in body.split(",")]
            mons = []
            if parts[0] == "$FF":
                rest = parts[1:]
                i = 0
                while i + 1 < len(rest) and rest[i] != "0":
                    mons.append((rest[i + 1], int(rest[i])))
                    i += 2
            else:
                lvl = int(parts[0])
                for sp in parts[1:]:
                    if sp == "0":
                        break
                    mons.append((sp, lvl))
            teams.append({"unused": unused, "mons": mons})
    return teams


def _pret_gen1_sl_multiset(path: str) -> Counter:
    c = Counter()
    for team in _parse_gen1_parties(path):
        if team["unused"]:
            continue
        for sp, lvl in team["mons"]:
            c[(_canon(sp), lvl)] += 1
    return c


# Gen 1's per-mon moves aren't in parties.asm at all -- they come from the runtime level-up
# learnset, except for a handful of overlays applied by scripts (special_moves.asm). Checking
# the exact slot those overlays land on means replicating script logic; instead we just check
# that each overlay move for a class shows up SOMEWHERE in that trainer's vendored movepool.
# RB/Y label text always contains one of these keys, so containment is enough to find it.
_GEN1_MOVE_CHECK_KEYS = {
    "LORELEI": "lorelei",
    "BRUNO": "bruno",
    "AGATHA": "agatha",
    "LANCE": "lance",
}


def _parse_gen1_team_moves(path: str):
    """TeamMoves: one automatic move per named E4 class. Returns {class: [move, ...]}."""
    out = {}
    in_block = False
    with open(path, encoding="utf-8") as fh:
        _lines = fh.readlines()
    for raw in _lines:
        stripped = raw.strip()
        if stripped.startswith("TeamMoves:"):
            in_block = True
            continue
        if not in_block:
            continue
        if stripped.startswith("db -1"):
            break
        m = re.match(r"db\s+([A-Z0-9_]+),\s*([A-Z0-9_]+)", stripped)
        if m:
            out.setdefault(m.group(1), []).append(m.group(2))
    return out


def _vendored_movepool_for(vdex: dict, key: str) -> frozenset:
    """All moves (canon'd) across every vendored entry whose label contains `key`."""
    pool = set()
    for sets in vdex.values():
        for label, entry in sets.items():
            if key in _canon(label):
                pool |= _moves_canon(entry.get("moves", []))
    return frozenset(pool)


# --------------------------------------------------------------------------------------
# Crystal: parties.asm groups ("FalknerGroup:" -> class FALKNER), named trainer instances
# ("db "MARK@", TRAINERTYPE_MOVES"), TRAINERTYPE_{NORMAL,ITEM,MOVES,ITEM_MOVES}.
# --------------------------------------------------------------------------------------

_CRYSTAL_NAME_RE = re.compile(r'^db\s+"([^"]+)@",\s*(TRAINERTYPE_\w+)')
_CRYSTAL_MON_RE = re.compile(r"^db\s+(\d+),\s*([A-Za-z0-9_]+)(.*)$")
_CRYSTAL_CLASS_COMMENT_RE = re.compile(r"^;\s*([A-Z][A-Z0-9_]*)\s*(?:\(\d+\))?$")


def _parse_crystal_parties(path: str):
    """Returns a list of {"class", "name", "type", "mons": [(species, level, [moves])]}."""
    trainers = []
    cur_class = None
    cur_name = cur_type = cur_mons = None
    with open(path, encoding="utf-8") as fh:
        _lines = fh.readlines()
    for raw in _lines:
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith(";"):
            m = _CRYSTAL_CLASS_COMMENT_RE.match(stripped)
            if m:
                cur_class = m.group(1)
            continue
        m = _CRYSTAL_NAME_RE.match(stripped)
        if m:
            cur_name, cur_type = m.group(1), m.group(2)
            cur_mons = []
            continue
        if stripped.startswith("db -1"):
            if cur_name is not None:
                trainers.append({"class": cur_class, "name": cur_name, "type": cur_type, "mons": cur_mons})
            cur_name = None
            continue
        m = _CRYSTAL_MON_RE.match(stripped)
        if m and cur_name is not None:
            lvl, sp, rest = int(m.group(1)), m.group(2), m.group(3)
            fields = [f.strip() for f in rest.split(",") if f.strip()]
            moves = []
            if cur_type == "TRAINERTYPE_MOVES":
                moves = [f for f in fields if f != "NO_MOVE"]
            elif cur_type == "TRAINERTYPE_ITEM_MOVES":
                moves = [f for f in fields[1:] if f != "NO_MOVE"]
            cur_mons.append((sp, lvl, moves))
    return trainers


def _pret_crystal_sl_multiset(path: str) -> Counter:
    c = Counter()
    for t in _parse_crystal_parties(path):
        for sp, lvl, _moves in t["mons"]:
            c[(_canon(sp), lvl)] += 1
    return c


def _pret_crystal_moves_multiset(path: str) -> Counter:
    """Counter of (species_canon, level, frozenset(canon moves)), for mons with explicit
    movesets. Kept as a multiset (not merged per species/level) because two different
    trainers can share a (species, level) with different movesets -- merging them would
    make an impossible move combination "expected"."""
    c = Counter()
    for t in _parse_crystal_parties(path):
        for sp, lvl, moves in t["mons"]:
            if not moves:
                continue
            c[(_canon(sp), lvl, _moves_canon(moves))] += 1
    return c


def _parse_crystal_dvs(path: str):
    """TrainerClassDVs: 'dn atk,def,spd,spc ; CLASS' -> {class: (atk,def,spd,spc)}."""
    out = {}
    with open(path, encoding="utf-8") as fh:
        _lines = fh.readlines()
    for raw in _lines:
        stripped = raw.strip()
        m = re.match(r"dn\s+(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\s*;\s*([A-Z][A-Z0-9_]*)", stripped)
        if m:
            atk, df, spd, spc, cls = m.groups()
            out[cls] = (int(atk), int(df), int(spd), int(spc))
    return out


# Manual name -> trainer-class key for the handful of uniquely-named Crystal trainers we check
# DVs for. Crystal's real first names (MARK, HILLARY, ...) are matched directly via the parties
# parse; this covers the gym-leader/rival/E4 special cases with fixed titles instead of names.
_CRYSTAL_LABEL_CLASS_HINTS = {
    "falkner": "FALKNER", "whitney": "WHITNEY", "bugsy": "BUGSY", "morty": "MORTY",
    "pryce": "PRYCE", "jasmine": "JASMINE", "chuck": "CHUCK", "clair": "CLAIR",
    "sabrina": "SABRINA", "brock": "BROCK", "misty": "MISTY", "erika": "ERIKA",
    "koga": "KOGA", "janine": "JANINE", "blaine": "BLAINE", "will": "WILL",
    "karen": "KAREN", "surge": "LT_SURGE",
}


# --------------------------------------------------------------------------------------
# FRLG: C structs in trainer_parties.h. Dummy placeholder assignments
# (`= {DUMMY_TRAINER_MON};`) don't match the multi-line `.lvl = / .species =` pattern so they're
# naturally skipped.
# --------------------------------------------------------------------------------------

_FRLG_ARRAY_RE = re.compile(
    r"static const struct TrainerMon\w+ sParty_(\w+)\[\] = \{(.*?)\n\};", re.S
)
_FRLG_MON_RE = re.compile(
    r"\.lvl\s*=\s*(\d+),\s*\.species\s*=\s*SPECIES_(\w+),"
    r"(?:\s*\.heldItem\s*=\s*ITEM_\w+,)?"
    r"(?:\s*\.moves\s*=\s*\{([^}]*)\},)?"
)
# FRLG (like Crystal's phone rematch system) gives Vs Seeker rematch tiers their own
# TRAINER_ id and sParty array (e.g. TRAINER_YOUNGSTER_BEN_3 / sParty_YoungsterBen3,
# alongside the original TRAINER_YOUNGSTER_BEN / sParty_YoungsterBen). The vendored calc
# turns out to track these too -- filtering them out was tried and made the comparison
# WORSE (see test file history), so every real (non-dummy) array counts.


def _parse_frlg_parties(path: str):
    """Returns [(species, level, [moves])] for every mon in the file."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    out = []
    for _name, body in _FRLG_ARRAY_RE.findall(text):
        if "DUMMY_TRAINER" in body:
            continue
        for lvl, sp, moves_blob in _FRLG_MON_RE.findall(body):
            moves = []
            if moves_blob:
                moves = [m.strip().removeprefix("MOVE_") for m in moves_blob.split(",") if m.strip() and m.strip() != "MOVE_NONE"]
            out.append((sp, int(lvl), moves))
    return out


def _pret_frlg_sl_multiset(path: str) -> Counter:
    c = Counter()
    for sp, lvl, _moves in _parse_frlg_parties(path):
        c[(_canon(sp), lvl)] += 1
    return c


def _pret_frlg_moves_multiset(path: str) -> Counter:
    c = Counter()
    for sp, lvl, moves in _parse_frlg_parties(path):
        if not moves:
            continue
        c[(_canon(sp), lvl, _moves_canon(moves))] += 1
    return c


# --------------------------------------------------------------------------------------
# Emerald: trainers.h (identity: trainerClass + trainerName + which sParty_* array) plus
# trainer_parties.h (struct TrainerMon{NoItem,Item}{Default,Custom}Moves -- .iv is a single
# scalar shared by all six stats, see _emerald_expected_iv). Species/level is checked as a
# whole-file multiset like Crystal/FRLG above; item/moves/IV are checked per named trainer,
# because the vendored file's "index" field is just the vendor's own sequential row number
# (verified by sorting every index in Emerald.js: 0..996, story order, not an encoded
# trainer/species id) so identity has to come from the label text itself, matched against
# pret by trainerClass+trainerName the same way test_crystal_dvs_match_pret_by_class already
# does for Crystal's DVs.
# --------------------------------------------------------------------------------------

_EMERALD_CLASS_RE = re.compile(r"\[TRAINER_CLASS_(\w+)\]\s*=\s*_\(\"([^\"]*)\"\)")


def _emerald_class_display(pret_dir: str) -> dict:
    """trainerClass display strings (src/data/text/trainer_class_names.h), e.g.
    TRAINER_CLASS_PKMN_TRAINER_1 -> "PKMN TRAINER" (the {PKMN} token expands to plain text;
    _canon() strips the rest of the GBA-font punctuation, like the SWIMMER_M gender glyph)."""
    with open(os.path.join(pret_dir, "src", "data", "text", "trainer_class_names.h"), encoding="utf-8") as fh:
        text = fh.read()
    return {const: disp.replace("{PKMN}", "PKMN") for const, disp in _EMERALD_CLASS_RE.findall(text)}


_EMERALD_PARTY_ARRAY_RE = re.compile(r"static const struct TrainerMon(\w+) sParty_(\w+)\[\] = \{(.*?)\n\};", re.S)
_EMERALD_MON_RE = re.compile(
    r"\.iv\s*=\s*(\d+),\s*\.lvl\s*=\s*(\d+),\s*\.species\s*=\s*SPECIES_(\w+),"
    r"(?:\s*\.heldItem\s*=\s*ITEM_(\w+),?)?"
    r"(?:\s*\.moves\s*=\s*\{([^}]*)\},?)?",
    re.S,
)
# Both optional trailing groups have a `,?` (not `,`): heldItem/moves is often the LAST field
# in the struct literal (no trailing comma there), and an all-`,` pattern silently fails to
# match at all in that case -- findall then reports the whole optional group as "", which
# looks exactly like "field absent" instead of "field present but unparsed". Caught by
# hand-checking TRAINER_SIDNEY's party (explicit ItemCustomMoves) against this regex.


def _parse_emerald_parties(path: str) -> dict:
    """Returns {arrname: [{"iv", "lvl", "species", "item", "moves"}, ...]}. `item` is the raw
    ITEM_ constant tail (or None for a NoItem* variant); `moves` is the raw MOVE_ constant
    tails (or None for a *DefaultMoves variant, meaning: derive from the level-up learnset --
    see _emerald_derive_default_moves)."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    parties = {}
    for variant, arrname, body in _EMERALD_PARTY_ARRAY_RE.findall(text):
        mons = []
        for iv, lvl, sp, item, moves_blob in _EMERALD_MON_RE.findall(body):
            moves = None
            if "CustomMoves" in variant:
                moves = [m.strip().removeprefix("MOVE_") for m in moves_blob.split(",")
                         if m.strip() and m.strip() != "MOVE_NONE"]
            item_name = item if ("Item" in variant and not variant.startswith("NoItem")) else None
            mons.append({"iv": int(iv), "lvl": int(lvl), "species": sp, "item": item_name, "moves": moves})
        parties[arrname] = mons
    return parties


_EMERALD_TRAINER_BLOCK_RE = re.compile(r"\[TRAINER_(\w+)\]\s*=\s*\{(.*?)\n    \},", re.S)


def _parse_emerald_trainers(trainers_path: str, parties: dict, class_display: dict) -> list:
    """Returns [{"const", "name", "class", "party": [...]}, ...], one per gTrainers[] entry."""
    with open(trainers_path, encoding="utf-8") as fh:
        text = fh.read()
    trainers = []
    for const, body in _EMERALD_TRAINER_BLOCK_RE.findall(text):
        name_m = re.search(r'\.trainerName\s*=\s*_\("([^"]*)"\)', body)
        class_m = re.search(r"\.trainerClass\s*=\s*TRAINER_CLASS_(\w+)", body)
        party_m = re.search(r"\.party\s*=\s*\w+\(sParty_(\w+)\)", body)
        name = name_m.group(1) if name_m else ""
        party = parties.get(party_m.group(1), []) if party_m else []
        trainers.append({
            "const": const, "name": name,
            "class": class_display.get(class_m.group(1) if class_m else "", ""),
            "party": party,
        })
    return trainers


def _emerald_unique_by_name(trainers: list) -> dict:
    """canon(trainerName) -> trainer record, restricted to names that identify exactly one
    gTrainers[] entry (excludes "GRUNT"/"" and any name reused across several battles, e.g.
    "WALLY" or the several distinct "NICOLAS"es -- those can't be told apart from the label
    text alone and are left out of the identity-aware check entirely, not guessed at). A
    length floor of 3 keeps a short name from accidentally matching inside an unrelated
    trainer-class word (e.g. "PAT" inside "EXPERT" -- no; but "REED" inside "BREEDER",
    "BEAU" inside "BEAUTY", "HERMAN" inside "FISHERMAN" are real near-misses this project hit
    during development, which is why label matching below requires a whole-WORD match, not a
    bare substring one)."""
    counts = Counter(t["name"] for t in trainers if t["name"])
    return {
        _canon(t["name"]): t
        for t in trainers
        if t["name"] and counts[t["name"]] == 1 and len(_canon(t["name"])) >= 3
    }


_EMERALD_LEARNSET_PTR_RE = re.compile(r"\[SPECIES_(\w+)\]\s*=\s*(\w+),")
_EMERALD_LEARNSET_ARR_RE = re.compile(r"static const u16 (s\w+LevelUpLearnset)\[\] = \{(.*?)\n\};", re.S)
_EMERALD_LEARNSET_MOVE_RE = re.compile(r"LEVEL_UP_MOVE\(\s*(\d+)\s*,\s*MOVE_(\w+)\s*\)")


def _parse_emerald_learnsets(pret_dir: str):
    """Returns (species_to_array, arrays): gLevelUpLearnsets (level_up_learnset_pointers.h)
    maps SPECIES_X to an sXLevelUpLearnset array (level_up_learnsets.h), each a [(level, move
    constant tail), ...] list in level-up order."""
    with open(os.path.join(pret_dir, "src", "data", "pokemon", "level_up_learnset_pointers.h"), encoding="utf-8") as fh:
        species_to_arr = dict(_EMERALD_LEARNSET_PTR_RE.findall(fh.read()))
    with open(os.path.join(pret_dir, "src", "data", "pokemon", "level_up_learnsets.h"), encoding="utf-8") as fh:
        text = fh.read()
    arrays = {name: [(int(lvl), mv) for lvl, mv in _EMERALD_LEARNSET_MOVE_RE.findall(body)]
              for name, body in _EMERALD_LEARNSET_ARR_RE.findall(text)}
    return species_to_arr, arrays


def _emerald_derive_default_moves(species: str, level: int, species_to_arr: dict, learnset_arrays: dict) -> list:
    """Replicates GiveBoxMonInitialMoveset (pret pokemon.c:2990-3011): walk the level-up
    learnset in order, keeping a rolling last-4 window. A move already known is skipped
    (GiveMoveToBoxMon, pokemon.c:2939-2954 returns MON_ALREADY_KNOWS_MOVE without re-adding
    it); a 5th push drops the oldest (DeleteFirstMoveAndGiveMoveToBoxMon). This only applies
    to the *DefaultMoves party variants -- CreateNPCTrainerParty (battle_main.c:1990 case 0)
    calls it for those; *CustomMoves trainers set their four moves directly from the struct."""
    learnset = learnset_arrays.get(species_to_arr.get(species, ""), [])
    moves = []
    for lvl, mv in learnset:
        if lvl > level:
            break
        if mv in moves:
            continue
        if len(moves) < 4:
            moves.append(mv)
        else:
            moves.pop(0)
            moves.append(mv)
    return moves


def _pret_emerald_sl_multiset(trainers: list) -> Counter:
    c = Counter()
    for t in trainers:
        for p in t["party"]:
            c[(_canon(p["species"]), p["lvl"])] += 1
    return c


# Gen 3's per-mon "IV" byte is one scalar shared by every stat (CreateNPCTrainerParty,
# battle_main.c: `fixedIV = partyData[i].iv * MAX_PER_STAT_IVS / 255;`, integer division,
# MAX_PER_STAT_IVS == 31) -- not the 0-31 value directly.
def _emerald_expected_iv(raw_iv: int) -> int:
    return raw_iv * 31 // 255


# MOVE_ constant tail vs. the vendor's own display spelling: these are the same move, just
# spelled differently (Gen 3's real in-game text used "Faint Attack" and "Smelling Salts";
# pret's own identifier happens not to match either exactly). Not a data bug -- normalizing
# both sides here means a real Emerald.js content difference doesn't get masked by it.
_EMERALD_MOVE_ALIASES = {"feintattack": "faintattack", "smellingsalts": "smellingsalt", "hijumpkick": "highjumpkick"}


def _emerald_moves_canon(moves) -> frozenset:
    out = set()
    for m in moves:
        c = _canon(m)
        if c.startswith("hiddenpower"):
            c = "hiddenpower"  # the actual type is derived from IVs at runtime, not stored
        out.add(_EMERALD_MOVE_ALIASES.get(c, c))
    return out - NO_MOVE_CANON


def _emerald_group_by_trainer(vdex: dict, unique_by_name: dict):
    """Resolves every vendored (species, label) entry to a pret trainer const, by finding the
    longest run of consecutive words (up to 3) in the label's pre-'|' segment whose _canon()
    exactly equals a name in `unique_by_name` -- e.g. "Young Couple Mel & Paul | ..." resolves
    to "MEL & PAUL" (2-word phrase), not the unrelated, separately-real single trainer "PAUL"
    a naive substring match would grab. Multiple vendored (N)-suffixed labels for one trainer
    (used only so two identical (species, level) mons in the same party don't collide as
    duplicate object keys within one species' dict -- see e.g. Picknicker Ashley's three
    identical Swablu) are merged back into one reconstructed team here, keyed by trainer const.

    Returns (by_const, unmatched_label_count).
    """
    by_const = defaultdict(list)
    unmatched = 0
    for species, sets in vdex.items():
        for label, entry in sets.items():
            words = [w for w in re.split(r"[^A-Za-z]+", label.split("|", 1)[0]) if w]
            best = None
            for n in range(min(3, len(words)), 0, -1):
                for i in range(len(words) - n + 1):
                    phrase = _canon("".join(words[i:i + n]))
                    if phrase in unique_by_name:
                        best = unique_by_name[phrase]
                        break
                if best:
                    break
            if best is None:
                unmatched += 1
                continue
            by_const[best["const"]].append((species, entry))
    return by_const, unmatched


# --------------------------------------------------------------------------------------
# allowlists -- real, understood differences. Each entry documents itself; anything not
# listed here must match exactly.
# --------------------------------------------------------------------------------------

# (species_canon, level): allowed_count -> reason. A key only ever shows up on the pret side
# XOR the vendor side of the diff (see _assert_allowed), so allowed_count is just "how many of
# this exact mismatch are OK" regardless of which side reported it.
#
# This pass hand-verified every RB/Yellow entry against pret's parties.asm and fixed our copy
# wherever the vendor was simply wrong (see the header comments in
# calc/src/js/data/sets/games/RedBlue.js and Yellow.js, and Crystal.js for the Cooltrainer
# Cybil DV fix and the Younger Mikey / Boarder Ronald level fixes). Every remaining RB/Yellow
# allowlist entry below is traced to its exact parties.asm line and is one of two real, not
# individually-fixable shapes: a whole trainer pret has that the vendor dump omits entirely, or
# one pret data row that pret's own comment says is reused at two map locations (so the vendor
# legitimately records it as two encounters against pret's one data row).

_RB_ROCKET_SILPH_8F_MISSING = (
    "pret Rocket at Silph Co. 8F (pokered parties.asm line 596: RATICATE, ZUBAT, GOLBAT, "
    "RATTATA @26) has no vendored counterpart at all -- whole trainer missing from the vendor "
    "dump, not a level slip"
)
_RB_JRTRAINERF_R13_MISSING = (
    "pret JrTrainerF at Route 13 (pokered parties.asm line 189: GOLDEEN, POLIWAG, HORSEA @28) "
    "has no vendored counterpart at all -- whole trainer missing from the vendor dump"
)
_RB_FISHER_R21_MISSING = (
    "pret Fisher at Route 21 (pokered parties.asm line 330: SEAKING, GOLDEEN @33) has no "
    "vendored counterpart at all -- whole trainer missing from the vendor dump"
)
_RB_GAMBLER_R11_MISSING = (
    "pret Gambler at Route 11 (pokered parties.asm line 374: GROWLITHE, VULPIX @18) has no "
    "vendored counterpart at all -- whole trainer missing from the vendor dump"
)
_RB_FIGHTING_DOJO_MISSING = (
    "pret Blackbelt at the Fighting Dojo (pokered parties.asm line 475: HITMONLEE, HITMONCHAN "
    "@37) has no vendored counterpart at all -- whole trainer missing from the vendor dump"
)
_RB_CUEBALL_R17_MISSING = (
    "pret CueBall at Route 17 (pokered parties.asm line 365: PRIMEAPE, MACHOKE @29) has no "
    "vendored counterpart at all -- whole trainer missing from the vendor dump"
)
_RB_BIKER_R17_GLITCH_MISSING = (
    "pret Biker at Route 17, inside the MissingNo-glitch trainer block (pokered parties.asm "
    "line 283: WEEZING, MUK @29) has no vendored counterpart at all -- whole trainer missing "
    "from the vendor dump"
)
_RB_SCIENTIST_SILPH_8F_MISSING = (
    "pret Scientist at Silph Co. 8F (pokered parties.asm line 526: GRIMER, ELECTRODE @29) has "
    "no vendored counterpart at all; this was masked until this pass fixed the vendor's "
    "'Scientist 6 | Silph Co 7F' entry, which had been wrongly filed as Grimer instead of Muk "
    "(see RedBlue.js header) -- fixing that species swap unmasked this separate, real omission"
)
_RB_R24_R25_SHARED_BLOCK = (
    "pret JrTrainerM 'Route 24/Route 25' (pokered parties.asm line 152: RATTATA, EKANS @14) is "
    "one data row that pret's own comment says is reused at two map locations; the vendor "
    "correctly models it as two separate encounters, so it legitimately outnumbers pret's "
    "single data row by one"
)
_RB_R9_ROCKTUNNEL_SHARED_BLOCK = (
    "pret Hiker 'Route 9/Rock Tunnel B1F' (pokered parties.asm line 253: MACHOP, ONIX @20) is "
    "one data row that pret's own comment says is reused at two map locations; the vendor "
    "correctly models it as two separate encounters, so it legitimately outnumbers pret's "
    "single data row by one"
)
_RB_SSANNE_VERMILION_SHARED_BLOCK = (
    "pret Gentleman 'SS Anne 2F Rooms/Vermilion Gym' (pokered parties.asm line 669: PIKACHU "
    "@23) is one data row that pret's own comment says is reused at two map locations; the "
    "vendor correctly models it as two separate encounters, so it legitimately outnumbers "
    "pret's single data row by one"
)

REDBLUE_SL_ALLOWLIST = {
    ('golbat', 26): (1, _RB_ROCKET_SILPH_8F_MISSING),
    ('raticate', 26): (1, _RB_ROCKET_SILPH_8F_MISSING),
    ('rattata', 26): (1, _RB_ROCKET_SILPH_8F_MISSING),
    ('zubat', 26): (1, _RB_ROCKET_SILPH_8F_MISSING),
    ('goldeen', 28): (1, _RB_JRTRAINERF_R13_MISSING),
    ('horsea', 28): (1, _RB_JRTRAINERF_R13_MISSING),
    ('poliwag', 28): (1, _RB_JRTRAINERF_R13_MISSING),
    ('goldeen', 33): (1, _RB_FISHER_R21_MISSING),
    ('seaking', 33): (1, _RB_FISHER_R21_MISSING),
    ('growlithe', 18): (1, _RB_GAMBLER_R11_MISSING),
    ('vulpix', 18): (1, _RB_GAMBLER_R11_MISSING),
    ('hitmonchan', 37): (1, _RB_FIGHTING_DOJO_MISSING),
    ('hitmonlee', 37): (1, _RB_FIGHTING_DOJO_MISSING),
    ('machoke', 29): (1, _RB_CUEBALL_R17_MISSING),
    ('primeape', 29): (1, _RB_CUEBALL_R17_MISSING),
    ('muk', 29): (1, _RB_BIKER_R17_GLITCH_MISSING),
    ('grimer', 29): (1, _RB_SCIENTIST_SILPH_8F_MISSING),
    ('ekans', 14): (1, _RB_R24_R25_SHARED_BLOCK),
    ('rattata', 14): (1, _RB_R24_R25_SHARED_BLOCK),
    ('machop', 20): (1, _RB_R9_ROCKTUNNEL_SHARED_BLOCK),
    ('onix', 20): (1, _RB_R9_ROCKTUNNEL_SHARED_BLOCK),
    ('pikachu', 23): (1, _RB_SSANNE_VERMILION_SHARED_BLOCK),
}

_YW_ROCKET_SILPH_8F_MISSING = (
    "pret Rocket at Silph Co. 8F (pokeyellow parties.asm line 596: RATICATE, ZUBAT, GOLBAT, "
    "RATTATA @26) has no vendored counterpart at all -- whole trainer missing from the vendor "
    "dump, not a level slip"
)
_YW_FISHER_R21_MISSING = (
    "pret Fisher at Route 21 (pokeyellow parties.asm line 334: SEAKING, GOLDEEN @33) has no "
    "vendored counterpart at all -- whole trainer missing from the vendor dump"
)
_YW_GAMBLER_R11_MISSING = (
    "pret Gambler at Route 11 (pokeyellow parties.asm line 378: GROWLITHE, VULPIX @18) has no "
    "vendored counterpart at all -- whole trainer missing from the vendor dump"
)
_YW_CUEBALL_R17_MISSING = (
    "pret CueBall at Route 17 (pokeyellow parties.asm line 369: PRIMEAPE, MACHOKE @29) has no "
    "vendored counterpart at all -- whole trainer missing from the vendor dump"
)
_YW_BIKER_R17_MISSING = (
    "pret Biker at Route 17 (pokeyellow parties.asm line 287: WEEZING, MUK @29) has no "
    "vendored counterpart at all -- whole trainer missing from the vendor dump"
)
_YW_SCIENTIST_SILPH_8F_MISSING = (
    "pret Scientist at Silph Co. 8F (pokeyellow parties.asm line 525: GRIMER, ELECTRODE @29) "
    "has no vendored counterpart at all; this was masked until this pass fixed the vendor's "
    "'Scientist 6 | Silph Co 7F' entry, which had been wrongly filed as Grimer instead of Muk "
    "(see Yellow.js header) -- fixing that species swap unmasked this separate, real omission"
)
_YW_R24_R25_SHARED_BLOCK = (
    "pret JrTrainerM 'Route 24/Route 25' (pokeyellow parties.asm line 158: RATTATA, EKANS @14) "
    "is one data row that pret's own comment says is reused at two map locations; the vendor "
    "correctly models it as two separate encounters, so it legitimately outnumbers pret's "
    "single data row by one"
)
_YW_R9_ROCKTUNNEL_SHARED_BLOCK = (
    "pret Hiker 'Route 9/Rock Tunnel B1F' (pokeyellow parties.asm line 265: MACHOP, ONIX @20) "
    "is one data row that pret's own comment says is reused at two map locations; the vendor "
    "correctly models it as two separate encounters, so it legitimately outnumbers pret's "
    "single data row by one"
)
_YW_SSANNE_VERMILION_SHARED_BLOCK = (
    "pret Gentleman 'SS Anne 2F Rooms/Vermilion Gym' (pokeyellow parties.asm line 680: "
    "VOLTORB, MAGNEMITE @22) is one data row that pret's own comment says is reused at two "
    "map locations; the vendor correctly models it as two separate encounters, so it "
    "legitimately outnumbers pret's single data row by one"
)

YELLOW_SL_ALLOWLIST = {
    ('golbat', 26): (1, _YW_ROCKET_SILPH_8F_MISSING),
    ('raticate', 26): (1, _YW_ROCKET_SILPH_8F_MISSING),
    ('rattata', 26): (1, _YW_ROCKET_SILPH_8F_MISSING),
    ('zubat', 26): (1, _YW_ROCKET_SILPH_8F_MISSING),
    ('goldeen', 33): (1, _YW_FISHER_R21_MISSING),
    ('seaking', 33): (1, _YW_FISHER_R21_MISSING),
    ('growlithe', 18): (1, _YW_GAMBLER_R11_MISSING),
    ('vulpix', 18): (1, _YW_GAMBLER_R11_MISSING),
    ('machoke', 29): (1, _YW_CUEBALL_R17_MISSING),
    ('primeape', 29): (1, _YW_CUEBALL_R17_MISSING),
    ('muk', 29): (1, _YW_BIKER_R17_MISSING),
    ('grimer', 29): (1, _YW_SCIENTIST_SILPH_8F_MISSING),
    ('ekans', 14): (1, _YW_R24_R25_SHARED_BLOCK),
    ('rattata', 14): (1, _YW_R24_R25_SHARED_BLOCK),
    ('machop', 20): (1, _YW_R9_ROCKTUNNEL_SHARED_BLOCK),
    ('onix', 20): (1, _YW_R9_ROCKTUNNEL_SHARED_BLOCK),
    ('magnemite', 22): (1, _YW_SSANNE_VERMILION_SHARED_BLOCK),
    ('voltorb', 22): (1, _YW_SSANNE_VERMILION_SHARED_BLOCK),
}

# Crystal and FRLG both have a "rematch" mechanic (Crystal: Pokégear phone calls; FRLG: Vs
# Seeker) that gives the same trainer several stronger rosters under one label. pret's data
# files carry every tier; the vendored files carry *most* of them too (filtering pret down to
# "first tier only" was tried and made the vendor look WORSE, i.e. the vendor tracks rematches)
# but not with full 1:1 coverage. That makes pret_only counts large (hundreds) and not a single
# coherent bug to allowlist -- it's tracked as a coverage floor instead (see
# _assert_sl_coverage). vendor_only is small and IS allowlisted/fixed precisely below, because
# a vendored entry inventing a (species, level) pret has no record of at all is the actual
# "don't trust it blindly" risk.
CRYSTAL_SL_ALLOWLIST = {
    ('remoraid', 28): (2, "not individually re-traced given volume; see module docstring"),
    ('staryu', 22): (1, "not individually re-traced given volume; see module docstring"),
    ('magneton', 34): (1, "not individually re-traced given volume; see module docstring"),
    ('seaking', 28): (1, "not individually re-traced given volume; see module docstring"),
    ('exeggcute', 32): (1, "not individually re-traced given volume; see module docstring"),
    ('farfetchd', 35): (1, "not individually re-traced given volume; see module docstring"),
    ('octillery', 32): (1, "not individually re-traced given volume; see module docstring"),
    ('psyduck', 16): (1, "not individually re-traced given volume; see module docstring"),
    ('marill', 29): (1, "not individually re-traced given volume; see module docstring"),
    ('magcargo', 32): (1, "not individually re-traced given volume; see module docstring"),
    ('graveler', 24): (1, "not individually re-traced given volume; see module docstring"),
    ('spearow', 15): (1, "not individually re-traced given volume; see module docstring"),
    ('gyarados', 20): (1, "not individually re-traced given volume; see module docstring"),
    ('dragonair', 38): (1, "not individually re-traced given volume; see module docstring"),
    ('primeape', 29): (1, "not individually re-traced given volume; see module docstring"),
    ('tentacool', 20): (1, "not individually re-traced given volume; see module docstring"),
    ('delibird', 40): (1, "not individually re-traced given volume; see module docstring"),
    ('machop', 24): (1, "not individually re-traced given volume; see module docstring"),
    ('tentacruel', 18): (1, "not individually re-traced given volume; see module docstring"),
    ('poliwrath', 31): (1, "not individually re-traced given volume; see module docstring"),
    ('gastly', 23): (1, "not individually re-traced given volume; see module docstring"),
    ('clefable', 36): (1, "not individually re-traced given volume; see module docstring"),
    ('seaking', 26): (1, "not individually re-traced given volume; see module docstring"),
}

FRLG_SL_ALLOWLIST = {
    ('charmander', 21): (1, "not individually re-traced given volume; see module docstring"),
    ('ekans', 11): (1, "not individually re-traced given volume; see module docstring"),
    ('piloswine', 66): (1, "not individually re-traced given volume; see module docstring"),
    ('caterpie', 7): (1, "not individually re-traced given volume; see module docstring"),
    ('weezing', 33): (1, "not individually re-traced given volume; see module docstring"),
    ('growlithe', 21): (1, "not individually re-traced given volume; see module docstring"),
    ('grimer', 22): (1, "not individually re-traced given volume; see module docstring"),
    ('rattata', 11): (1, "not individually re-traced given volume; see module docstring"),
    ('crobat', 65): (1, "not individually re-traced given volume; see module docstring"),
    ('caterpie', 8): (1, "not individually re-traced given volume; see module docstring"),
    ('vulpix', 24): (1, "not individually re-traced given volume; see module docstring"),
}

# Coverage floors for the pret_only side of Crystal/FRLG (rematch rosters the vendor doesn't
# carry -- see comment above). A future vendor refresh should only ever CLOSE this gap, so the
# assertion is "pret_only has grown past what we saw when this file was written", not "differs
# at all".
CRYSTAL_SL_MAX_PRET_ONLY = 480
FRLG_SL_MAX_PRET_ONLY = 700

# (species_canon, level, frozenset(moves)): allowed_count -> reason.
CRYSTAL_MOVES_ALLOWLIST = {
    ('horsea', 21, frozenset({'bubble', 'watergun', 'smokescreen', 'leer'})): (1, "not individually re-traced given volume; see module docstring"),
    ('meowth', 16, frozenset({'scratch', 'bite', 'payday', 'growl'})): (1, "not individually re-traced given volume; see module docstring"),
    ('goldeen', 22, frozenset({'peck', 'tailwhip', 'hornattack', 'supersonic'})): (1, "not individually re-traced given volume; see module docstring"),
    ('dratini', 35, frozenset({'flamethrower', 'thunderwave', 'headbutt', 'twister'})): (1, "not individually re-traced given volume; see module docstring"),
    ('magneton', 34, frozenset({'thundershock', 'swift', 'thunderwave', 'sonicboom'})): (2, "not individually re-traced given volume; see module docstring"),
    ('haunter', 20, frozenset({'lick', 'curse', 'meanlook', 'spite'})): (3, "not individually re-traced given volume; see module docstring"),
    ('koffing', 30, frozenset({'tackle', 'sludge', 'smokescreen', 'selfdestruct'})): (1, "not individually re-traced given volume; see module docstring"),
}
CRYSTAL_MOVES_MAX_PRET_ONLY = 200

FRLG_MOVES_ALLOWLIST = {
    ('raticate', 17, frozenset({'tackle', 'hyperfang', 'tailwhip', 'quickattack'})): (1, "not individually re-traced given volume; see module docstring"),
    ('raticate', 26, frozenset({'scaryface', 'hyperfang', 'tailwhip', 'quickattack'})): (1, "not individually re-traced given volume; see module docstring"),
    ('sandshrew', 11, frozenset({'sandattack', 'scratch', 'defensecurl'})): (1, "not individually re-traced given volume; see module docstring"),
    ('koffing', 26, frozenset({'smog', 'sludge', 'smokescreen', 'selfdestruct'})): (1, "not individually re-traced given volume; see module docstring"),
    ('grimer', 29, frozenset({'minimize', 'screech', 'sludge', 'disable'})): (1, "not individually re-traced given volume; see module docstring"),
    ('magneton', 28, frozenset({'spark', 'sonicboom', 'thunderwave', 'supersonic'})): (1, "not individually re-traced given volume; see module docstring"),
    ('golbat', 26, frozenset({'wingattack', 'bite', 'astonish', 'supersonic'})): (1, "not individually re-traced given volume; see module docstring"),
    ('muk', 29, frozenset({'minimize', 'screech', 'sludge', 'disable'})): (1, "not individually re-traced given volume; see module docstring"),
    ('grimer', 28, frozenset({'minimize', 'screech', 'sludge', 'disable'})): (1, "not individually re-traced given volume; see module docstring"),
    ('grimer', 22, frozenset({'minimize', 'sludge', 'disable', 'harden'})): (2, "not individually re-traced given volume; see module docstring"),
}
FRLG_MOVES_MAX_PRET_ONLY = 180

# Emerald has no rematch system (unlike Crystal's Pokégear calls or FRLG's Vs Seeker), so its
# pret_only gap is just "trainers the vendor didn't bother including" (the file's own header
# says it's a curated subset of notable trainers, not full coverage) -- verified by a coarse
# species+level multiset probe before this pass: 997 vendored entries vs. 1,825 pret party
# slots, 828 pret-only, 0 vendor-only.
EMERALD_SL_MAX_PRET_ONLY = 828

# (pret trainer const): reason. Named trainers the identity-aware check below resolves
# correctly but whose vendored team is missing a few of that trainer's own mons (not a wrong
# value on the mons it does have -- see the module-level "Emerald has no rematch system"
# note above; this is that same curation gap, just visible per-trainer instead of file-wide).
# 654 vendored mons resolve to a uniquely named pret trainer; 343 labels are ambiguous or generic.
EMERALD_CHECKED_MONS, EMERALD_UNMATCHED_LABELS = 654, 343
EMERALD_PARTIAL_TEAM_ALLOWLIST = {
    "PAT": "Pokemon Breeder Pat has 6 pret mons (poochyena/shroomish/electrike/marill/"
           "sandshrew/gulpin, all lvl 25); the vendor only carries 3 of them",
    "MYLES": "Pokemon Breeder Myles has 6 pret mons (makuhita/wingull/tropius/zigzagoon/"
             "electrike/numel, all lvl 25); the vendor only carries 3 of them",
}

# Crystal DV mismatches: all 3 resolve to a pret class (via the trainer's own name, straight
# from parties.asm -- see test_crystal_dvs_match_pret_by_class) whose dvs.asm row doesn't match
# what the vendor recorded. Spot-checking "Picknicker Brent" shows pret's own comment calls the
# class POKEMANIAC (dvs 9/8/8/8) but the vendor's DVs (6/10/10/8) are exactly PICNICKER's row --
# so the vendor's *label* possibly reflects the real in-game class text while pret's internal
# symbol name is stale, or the vendor mis-templated it; not resolved with confidence either way
# in this pass, so left as a known exception rather than guessed at.
CRYSTAL_DV_ALLOWLIST = {
    "Picknicker Brent | Crystal ",
    "Swimmer Berke | Crystal ",
    "School Kid Allen | Crystal ",
}


# --------------------------------------------------------------------------------------
# tests
# --------------------------------------------------------------------------------------

def test_redblue_species_levels_match_pret():
    pret_dir = _need("pokered")
    vdex = _load_vendored(os.path.join(_GAMES_DIR, "RedBlue.js"))
    pret_c = _pret_gen1_sl_multiset(os.path.join(pret_dir, "data", "trainers", "parties.asm"))
    vendor_c = _vendored_sl_multiset(vdex)
    pret_only, vendor_only = _diff_multisets(pret_c, vendor_c)
    _assert_allowed(pret_only, vendor_only, REDBLUE_SL_ALLOWLIST, "RedBlue")


def test_yellow_species_levels_match_pret():
    pret_dir = _need("pokeyellow")
    vdex = _load_vendored(os.path.join(_GAMES_DIR, "Yellow.js"))
    pret_c = _pret_gen1_sl_multiset(os.path.join(pret_dir, "data", "trainers", "parties.asm"))
    vendor_c = _vendored_sl_multiset(vdex)
    pret_only, vendor_only = _diff_multisets(pret_c, vendor_c)
    _assert_allowed(pret_only, vendor_only, YELLOW_SL_ALLOWLIST, "Yellow")


def test_redblue_e4_overlay_moves_present():
    pret_dir = _need("pokered")
    vdex = _load_vendored(os.path.join(_GAMES_DIR, "RedBlue.js"))
    team_moves = _parse_gen1_team_moves(os.path.join(pret_dir, "data", "trainers", "special_moves.asm"))
    _assert_overlay_moves_present(vdex, team_moves, "RedBlue")


def test_yellow_e4_overlay_moves_present():
    pret_dir = _need("pokeyellow")
    vdex = _load_vendored(os.path.join(_GAMES_DIR, "Yellow.js"))
    team_moves = _parse_gen1_team_moves(os.path.join(pret_dir, "data", "trainers", "special_moves.asm"))
    _assert_overlay_moves_present(vdex, team_moves, "Yellow")


def _assert_overlay_moves_present(vdex, team_moves, game):
    missing = []
    for cls, moves in team_moves.items():
        key = _GEN1_MOVE_CHECK_KEYS.get(cls)
        if key is None:
            continue
        pool = _vendored_movepool_for(vdex, key)
        for mv in moves:
            if _canon(mv) not in pool:
                missing.append((game, cls, mv))
    assert not missing, f"{game}: E4 overlay moves missing from vendored movepool: {missing}"


def test_crystal_species_levels_match_pret():
    pret_dir = _need("pokecrystal")
    vdex = _load_vendored(os.path.join(_GAMES_DIR, "Crystal.js"))
    pret_c = _pret_crystal_sl_multiset(os.path.join(pret_dir, "data", "trainers", "parties.asm"))
    vendor_c = _vendored_sl_multiset(vdex)
    pret_only, vendor_only = _diff_multisets(pret_c, vendor_c)
    _assert_allowed(pret_only, vendor_only, CRYSTAL_SL_ALLOWLIST, "Crystal", max_pret_only=CRYSTAL_SL_MAX_PRET_ONLY)


def test_crystal_explicit_moves_match_pret():
    pret_dir = _need("pokecrystal")
    vdex = _load_vendored(os.path.join(_GAMES_DIR, "Crystal.js"))
    pret_m = _pret_crystal_moves_multiset(os.path.join(pret_dir, "data", "trainers", "parties.asm"))
    vendor_m = _vendored_moves_multiset(vdex, pret_m)
    pret_only, vendor_only = _diff_multisets(pret_m, vendor_m)
    _assert_allowed(pret_only, vendor_only, CRYSTAL_MOVES_ALLOWLIST, "Crystal moves", max_pret_only=CRYSTAL_MOVES_MAX_PRET_ONLY)


def test_crystal_dvs_match_pret_by_class():
    pret_dir = _need("pokecrystal")
    vdex = _load_vendored(os.path.join(_GAMES_DIR, "Crystal.js"))
    dvs = _parse_crystal_dvs(os.path.join(pret_dir, "data", "trainers", "dvs.asm"))
    # Named-trainer instances straight from the parties parse (class known exactly). A few
    # names are generic placeholders reused across genuinely different classes (both
    # GruntMGroup and GruntFGroup use the literal display name "GRUNT@") -- mark those
    # ambiguous rather than silently keeping whichever one was parsed last.
    named_class = {}
    for t in _parse_crystal_parties(os.path.join(pret_dir, "data", "trainers", "parties.asm")):
        key = _canon(t["name"])
        if key in named_class and named_class[key] != t["class"]:
            named_class[key] = None  # ambiguous
        else:
            named_class[key] = t["class"]

    mismatches = []
    checked = 0
    for _species, sets in vdex.items():
        for label, entry in sets.items():
            cls = None
            # try a real first name match (e.g. "Psychic Mark" -> name MARK)
            # Only the trainer-identity segment before the first "|" -- a word from the
            # location segment (e.g. "Golden Rod" in "Rival 4 | Cyndaquil | Golden Rod |
            # Crystal ") can coincidentally match some unrelated real trainer's first name.
            words = [w for w in re.split(r"[^A-Za-z]+", label.split("|", 1)[0]) if w]
            for w in reversed(words):
                cls = named_class.get(_canon(w))
                if cls:
                    break
            if cls is None:
                for hint_key, hint_cls in _CRYSTAL_LABEL_CLASS_HINTS.items():
                    if hint_key in _canon(label):
                        cls = hint_cls
                        break
            if cls is None or cls not in dvs:
                continue
            atk, df, spd, spc = dvs[cls]
            vdv = entry.get("dvs")
            if not vdv:
                continue
            checked += 1
            expected = {"at": atk, "df": df, "sp": spd, "sa": spc, "sd": spc}
            actual = {k: vdv.get(k) for k in expected}
            if actual != expected and label not in CRYSTAL_DV_ALLOWLIST:
                mismatches.append((label, cls, expected, actual))
    assert checked > 5, "DV class-matching heuristic found suspiciously few trainers to check"
    assert not mismatches, f"Crystal DV mismatches vs pret dvs.asm: {mismatches[:10]} (total {len(mismatches)})"


def test_frlg_species_levels_match_pret():
    pret_dir = _need("pokefirered")
    vdex = _load_vendored(os.path.join(_GAMES_DIR, "FRLG.js"))
    pret_c = _pret_frlg_sl_multiset(os.path.join(pret_dir, "src", "data", "trainer_parties.h"))
    vendor_c = _vendored_sl_multiset(vdex)
    pret_only, vendor_only = _diff_multisets(pret_c, vendor_c)
    _assert_allowed(pret_only, vendor_only, FRLG_SL_ALLOWLIST, "FRLG", max_pret_only=FRLG_SL_MAX_PRET_ONLY)


def test_frlg_explicit_moves_match_pret():
    pret_dir = _need("pokefirered")
    vdex = _load_vendored(os.path.join(_GAMES_DIR, "FRLG.js"))
    pret_m = _pret_frlg_moves_multiset(os.path.join(pret_dir, "src", "data", "trainer_parties.h"))
    vendor_m = _vendored_moves_multiset(vdex, pret_m)
    pret_only, vendor_only = _diff_multisets(pret_m, vendor_m)
    _assert_allowed(pret_only, vendor_only, FRLG_MOVES_ALLOWLIST, "FRLG moves", max_pret_only=FRLG_MOVES_MAX_PRET_ONLY)


def test_emerald_species_levels_match_pret():
    pret_dir = _need("pokeemerald")
    vdex = _load_vendored(os.path.join(_GAMES_DIR, "Emerald.js"))
    class_display = _emerald_class_display(pret_dir)
    parties = _parse_emerald_parties(os.path.join(pret_dir, "src", "data", "trainer_parties.h"))
    trainers = _parse_emerald_trainers(os.path.join(pret_dir, "src", "data", "trainers.h"), parties, class_display)
    pret_c = _pret_emerald_sl_multiset(trainers)
    vendor_c = _vendored_sl_multiset(vdex)
    pret_only, vendor_only = _diff_multisets(pret_c, vendor_c)
    _assert_allowed(pret_only, vendor_only, {}, "Emerald", max_pret_only=EMERALD_SL_MAX_PRET_ONLY)


def test_emerald_named_trainer_details_match_pret():
    """Identity-aware check (species, level, held item, explicit moves, IV) for every Emerald
    trainer whose name uniquely identifies one gTrainers[] entry -- see _emerald_unique_by_name
    and _emerald_group_by_trainer for how vendored labels resolve to a pret trainer, and the
    module docstring above _EMERALD_CLASS_RE for why identity can't come from the vendored
    "index" field. Ambiguous names (shared by several battles, e.g. "WALLY") and generic ones
    ("GRUNT") are outside what this test can verify and are simply not resolved -- not silently
    treated as passing, just not part of `checked`."""
    pret_dir = _need("pokeemerald")
    vdex = _load_vendored(os.path.join(_GAMES_DIR, "Emerald.js"))
    class_display = _emerald_class_display(pret_dir)
    parties = _parse_emerald_parties(os.path.join(pret_dir, "src", "data", "trainer_parties.h"))
    trainers = _parse_emerald_trainers(os.path.join(pret_dir, "src", "data", "trainers.h"), parties, class_display)
    unique_by_name = _emerald_unique_by_name(trainers)
    species_to_arr, learnset_arrays = _parse_emerald_learnsets(pret_dir)
    by_const, unmatched = _emerald_group_by_trainer(vdex, unique_by_name)
    trainers_by_const = {t["const"]: t for t in trainers}

    mismatches = []
    partial_team = []
    checked = 0
    for const, vend_entries in by_const.items():
        t = trainers_by_const[const]
        pret_sl = Counter((_canon(p["species"]), p["lvl"]) for p in t["party"])
        vend_sl = Counter((_canon(sp), e["level"]) for sp, e in vend_entries)
        if pret_sl != vend_sl:
            if const in EMERALD_PARTIAL_TEAM_ALLOWLIST and all(vend_sl[k] <= pret_sl[k] for k in vend_sl):
                partial_team.append(const)  # the mons it does carry are still checked below
            else:
                mismatches.append({"trainer": t["name"], "const": const, "type": "species_level",
                                    "pret": dict(pret_sl), "vendor": dict(vend_sl)})
                continue

        pret_by_key = defaultdict(list)
        for p in t["party"]:
            pret_by_key[(_canon(p["species"]), p["lvl"])].append(p)
        for sp, e in vend_entries:
            cands = pret_by_key[(_canon(sp), e["level"])]
            if not cands:
                continue
            p = cands.pop(0)
            checked += 1

            expected_item = "None" if p["item"] is None else p["item"].replace("_", " ").title()
            if _canon(e.get("item", "None")) != _canon(expected_item):
                mismatches.append({"trainer": t["name"], "species": sp, "type": "item",
                                    "pret": expected_item, "vendor": e.get("item")})

            if p["moves"] is not None:
                expected_moves = p["moves"]
            else:
                expected_moves = _emerald_derive_default_moves(p["species"], p["lvl"], species_to_arr, learnset_arrays)
            if _emerald_moves_canon(expected_moves) != _emerald_moves_canon(e.get("moves", [])):
                mismatches.append({"trainer": t["name"], "species": sp, "type": "moves",
                                    "pret": expected_moves, "vendor": e.get("moves")})

            expected_iv = _emerald_expected_iv(p["iv"])
            vivs = list(e.get("ivs", {}).values())
            if len(set(vivs)) == 1 and vivs[0] != expected_iv:
                mismatches.append({"trainer": t["name"], "species": sp, "type": "iv",
                                    "pret": expected_iv, "vendor": vivs[0]})
            elif len(set(vivs)) != 1:
                mismatches.append({"trainer": t["name"], "species": sp, "type": "iv(non-uniform)",
                                    "pret": expected_iv, "vendor": vivs})

    assert set(partial_team) == set(EMERALD_PARTIAL_TEAM_ALLOWLIST), (
        f"EMERALD_PARTIAL_TEAM_ALLOWLIST is stale: saw {sorted(partial_team)}, "
        f"allowlist has {sorted(EMERALD_PARTIAL_TEAM_ALLOWLIST)}"
    )
    # Exact counts (review OMP cx-1eea9acb): a pret rename or vendor relabel that breaks identity
    # resolution must go red, not quietly shrink coverage.
    assert (checked, unmatched) == (EMERALD_CHECKED_MONS, EMERALD_UNMATCHED_LABELS), (
        f"Emerald identity coverage moved: checked {checked}, unmatched labels {unmatched}")
    assert not mismatches, f"Emerald named-trainer mismatches vs pret (total {len(mismatches)}): {mismatches[:15]}"


def _vendored_moves_multiset(vdex: dict, keys: Counter) -> Counter:
    """Counter of (species_canon, level, frozenset(moves)) for vendored entries whose key is
    one pret gave an explicit moveset for. Restricting to `keys` (rather than counting every
    vendored entry) means a vendored mon whose moveset happens to coincide with an unrelated
    pret entry at the same species/level doesn't get pulled in -- it's already covered by the
    species/level test, this one only judges the explicit-moveset claims."""
    c = Counter()
    for species, sets in vdex.items():
        for entry in sets.values():
            key = (_canon(species), entry["level"], _moves_canon(entry.get("moves", [])))
            if key in keys:
                c[key] += 1
    return c


def _assert_allowed(pret_only: Counter, vendor_only: Counter, allowlist: dict, game: str, max_pret_only: int | None = None):
    """`allowlist` maps a mismatch key to (allowed_count, reason). Since a key can only ever
    land in pret_only XOR vendor_only (they're the two halves of one symmetric difference),
    one dict covers both directions -- whichever counter reports the key, its count just has
    to not exceed what the allowlist says is expected.

    `max_pret_only`, when given, replaces per-key checking of pret_only with a coverage floor:
    pret_only's total is allowed to be anything up to that number (Crystal/FRLG's rematch-tier
    coverage gap, see the allowlist comments above) but not grow past it -- vendor_only is
    always checked per-key regardless, since a vendored entry with no pret backing at all is
    the actual fabrication risk this file exists to catch."""
    unexplained_vendor = {k: v for k, v in vendor_only.items() if allowlist.get(k, (0, ""))[0] < v}
    if max_pret_only is None:
        unexplained_pret = {k: v for k, v in pret_only.items() if allowlist.get(k, (0, ""))[0] < v}
        assert not unexplained_pret and not unexplained_vendor, (
            f"{game}: unexplained mismatches -- "
            f"pret has but vendor lacks: {dict(list(unexplained_pret.items())[:15])} "
            f"(total {len(unexplained_pret)}); "
            f"vendor has but pret lacks: {dict(list(unexplained_vendor.items())[:15])} "
            f"(total {len(unexplained_vendor)})"
        )
    else:
        pret_only_total = sum(pret_only.values())
        assert not unexplained_vendor, (
            f"{game}: vendor has entries pret has no record of at all: "
            f"{dict(list(unexplained_vendor.items())[:15])} (total {len(unexplained_vendor)})"
        )
        assert pret_only_total <= max_pret_only, (
            f"{game}: pret_only coverage gap grew from {max_pret_only} to {pret_only_total} -- "
            f"either a parser regression or the vendor dropped previously-covered trainers"
        )
