#!/usr/bin/env python3
"""Generate the Gen 3 packs' profile.json from Lua literals and pinned pret facts.

The primary source is the literal address database in `lua/games/gen3_frlge.lua`
(`GEN3.profiles.vanilla` / `.ap` / `.radical_red` and the additive
`GEN3.profiles.emerald`).  Nothing here re-types an address: the tables are parsed
out of the Lua text by a small strict parser for the subset those tables use
(`KEY = 0xHEX | integer | "string" | true/false/nil | { ... }` plus `+`/`*`
arithmetic and comments).  The file is never `require`d under a Lua runtime.

Packs (PLAN §4, §5.1):
    data/games/gen3_frlg/profile.json   titles firered, leafgreen (admitted; both read the
                                        `vanilla` table today) + the unadmitted titles
                                        firered_ap (`.ap`) and emerald (`.emerald`), copied
                                        verbatim so no data is lost
    data/games/gen3_rr/profile.json     title radical_red (`.radical_red`) + a `native` block
                                        for kind `companion`: the companion-patch mailbox ABI
                                        (lua/mailbox.lua) and the ghost/object-event addresses
                                        (lua/peer_ghost_npc.lua), each with its source file:line
                                        in the sibling `_src` map

    python tools/gen_gen3_profile.py            # rewrite both profiles
    python tools/gen_gen3_profile.py --check    # exit 1 if either committed file is stale
                                                # (the P2 exit condition "profile diff = 0")
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = "lua/games/gen3_frlge.lua"
MAILBOX_SRC = "lua/mailbox.lua"
GHOST_SRC = "lua/peer_ghost_npc.lua"
PRET_PIN = "pret/pokefirered@c75f352304d529f6ba92d4f74b9cf8b5c3810788"
STORAGE_HEADER = f"{PRET_PIN}:include/pokemon_storage_system.h"

# Pinned C layout facts, independent of the optional local pret checkout.
# boxes follows u8 currentBox, but BoxPokemon begins with u32 personality:
# ARM alignment inserts three padding bytes (the header's 0x0001 comment is wrong).
FRLG_DERIVED = {
    "BOX_DATA_OFFSET": (4, f"{STORAGE_HEADER}:44-48; "
                         f"{PRET_PIN}:include/pokemon.h:105-108 (u32 alignment)"),
    "BOXES_PER_STORE": (14, f"{STORAGE_HEADER}:7 (TOTAL_BOXES_COUNT)"),
    "MONS_PER_BOX": (5 * 6, f"{STORAGE_HEADER}:8-10 (IN_BOX_ROWS * IN_BOX_COLUMNS)"),
    "PARTY_CAPACITY": (6, f"{PRET_PIN}:include/constants/global.h:78 (PARTY_SIZE)"),
}

SCHEMA = "gen3-profile-v1"

# ── pins (P0 card C0-2/C0-4, docs/gen3/research/pins_inventory.md) ───────────────
ROM_HASHES = {
    "firered": {"rom_sha1": "41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc"},
    "leafgreen": {"rom_sha1": "574fa542ffebb14be69902d1d36f1ec0a4afd71e"},
    "radical_red": {"rom_sha1": "964f951a0fdaf209e4ea1344883ef0d557bb3a80",
                    "rom_md5": "8529f3a45d32bce4da637976fcf269d4"},
}

# pack -> [(title, profile key in GEN3.profiles, admitted)]
PACKS = {
    "gen3_frlg": [
        ("firered", "vanilla", True),
        ("leafgreen", "vanilla", True),
        ("firered_ap", "ap", False),
        ("emerald", "emerald", False),
    ],
    "gen3_rr": [
        ("radical_red", "radical_red", True),
    ],
}

# Every key the Lua tables carry, and the section it lands in.  A key that is not
# listed fails the run: the generator stays honest about what it understands.
#   ram      EWRAM/IWRAM addresses the client reads or writes
#   rom      ROM addresses (incl. SE_SONG_HEADERS, BASESTATS_ADDR, CB2_* callbacks)
#   derived  sizes, offsets, counts, modes and flags
SECTION = {
    # ── ram ──
    "PARTY_COUNT_ADDR": "ram", "PARTY_BASE": "ram",
    "ENEMY_COUNT_ADDR": "ram", "ENEMY_BASE": "ram",
    "BATTLE_TYPE_ADDR": "ram", "BATTLE_OUTCOME_ADDR": "ram", "BATTLE_MONS_ADDR": "ram",
    "BATTLER_PARTY_INDEXES_ADDR": "ram", "BATTLERS_COUNT_ADDR": "ram",
    "BATTLE_MAIN_FUNC_ADDR": "ram", "LOCKED_MOVES_ADDR": "ram",
    "GMAIN_ADDR": "ram", "SB1_PTR_ADDR": "ram", "SB2_PTR_ADDR": "ram", "PSP_PTR_ADDR": "ram",
    "SPECIAL_VAR_BOX_ID_ADDR": "ram", "SPECIAL_VAR_BOX_POS_ADDR": "ram",
    "TASKS_BASE_ADDR": "ram", "BATTLE_RESULTS_ADDR": "ram",
    "CHOSEN_MOVE_ADDRS": "ram", "CHOSEN_ACTION_ADDR": "ram", "CHOSEN_MOVE_ADDR": "ram",
    "BATTLE_COMM_ADDR": "ram", "BATTLE_STRUCT_PTR_ADDR": "ram",
    "POKEMON_STORAGE_BASE": "ram", "CFRU_BOX_NAME_BASE": "ram",
    "BALL_POCKET_ADDR": "ram", "TRAINER_OPPONENT_ADDR": "ram",
    "REAL_PARTY_BACKUP_ADDR": "ram",
    # ── rom ──
    "RETURN_FROM_BATTLE_ADDR": "rom", "SE_SONG_HEADERS": "rom", "BASESTATS_ADDR": "rom",
    "POST_BATTLE_WRITER_TASKS": "rom", "CB2_EVOLUTION_LOAD_ADDR": "rom",
    "CB2_EVOLUTION_BEGIN_ADDR": "rom", "CB2_EVOLUTION_UPDATE_ADDR": "rom",
    "CB2_TRADE_EVOLUTION_UPDATE_ADDR": "rom", "CFRU_BASESTATS_PTR": "rom",
    # ── derived ──
    "SB2_ENC_KEY_OFFSET": "derived", "SB1_BALL_POCKET_OFFSET": "derived",
    "SB1_BALL_POCKET_COUNT": "derived", "SB1_FLAGS_OFFSET": "derived",
    "SB1_VARS_OFFSET": "derived", "OVERWORLD_MODE": "derived",
    "BASESTATS_ENTRY_SIZE": "derived", "TASK_STRUCT_SIZE": "derived",
    "GMAIN_CB2_OFFSET": "derived",
    "BATTLE_RESULTS_PLAYER_FAINTS_OFF": "derived", "BATTLE_RESULTS_FOE_FAINTS_OFF": "derived",
    "PARTY_IN_SB1": "derived", "SB1_PARTY_BASE_OFFSET": "derived",
    "BATTLE_STRUCT_MOVE_TARGET_OFF": "derived", "BATTLE_STRUCT_CHOSEN_MOVE_POS_OFF": "derived",
    "CFRU_COMPRESSED_BOX": "derived", "COMPRESSED_MON_SIZE": "derived",
    "BOXES_PER_STORE": "derived", "CFRU_BOX_BASES": "derived", "BOX_NAMES_OFFSET": "derived",
    "BAG_IN_EWRAM": "derived", "BALL_POCKET_ENC": "derived",
    "OUTCOME_CAUGHT": "derived", "OUTCOME_RAN": "derived",
    "SE_NUZLOCKE_START": "derived", "SE_GAME_OVER": "derived",
    "SE_NEW_LINK": "derived", "SE_LINKED_KO": "derived",
    "CFRU_NO_ENCRYPT": "derived",
}


# ── the Lua subset parser ────────────────────────────────────────────────────────
_TOK = re.compile(r"""
      (?P<ws>\s+)
    | (?P<comment>--\[\[.*?\]\]|--[^\n]*)
    | (?P<str>"[^"\n]*")
    | (?P<num>0[xX][0-9A-Fa-f]+|\d+)
    | (?P<name>[A-Za-z_]\w*)
    | (?P<punct>[{}\[\],=+*./\-])
""", re.VERBOSE | re.DOTALL)

NIL = object()


class _Lex:
    """Cursor-based lexer: only the table being parsed is ever lexed."""

    def __init__(self, text: str, pos: int) -> None:
        self.text, self.pos, self._peeked = text, pos, None

    def _lex(self) -> tuple[str, str]:
        while True:
            m = _TOK.match(self.text, self.pos)
            if not m:
                sys.exit(f"gen_gen3_profile: cannot lex {SRC} at {self.text[self.pos:self.pos + 40]!r}")
            self.pos = m.end()
            if m.lastgroup not in ("ws", "comment"):
                return m.lastgroup, m.group()

    def peek(self) -> tuple[str, str]:
        if self._peeked is None:
            self._peeked = self._lex()
        return self._peeked

    def take(self) -> tuple[str, str]:
        tok, self._peeked = self.peek(), None
        return tok

    def expect(self, want: str) -> None:
        kind, val = self.take()
        if val != want:
            sys.exit(f"gen_gen3_profile: expected {want!r}, got {val!r} ({kind})")

    # value ::= table | string | true|false|nil | expr
    def value(self):
        kind, val = self.peek()
        if val == "{":
            return self.table()
        if kind == "str":
            self.take()
            return val[1:-1]
        if kind == "name" and val in ("true", "false", "nil"):
            self.take()
            return {"true": True, "false": False, "nil": NIL}[val]
        return self.expr()

    # expr ::= term ('+' term)*   |   term ::= num ('*' num)*
    def expr(self) -> int:
        total = self.term()
        while self.peek()[1] == "+":
            self.take()
            total += self.term()
        return total

    def term(self) -> int:
        val = self.number()
        while self.peek()[1] == "*":
            self.take()
            val *= self.number()
        return val

    def number(self) -> int:
        kind, val = self.take()
        if kind != "num":
            sys.exit(f"gen_gen3_profile: expected a number, got {val!r}")
        return int(val, 16) if val[:2].lower() == "0x" else int(val)

    def table(self):
        """A Lua table literal.  Positional entries, or keys 1..n, come back as a list;
        anything else as a dict keyed by the literal key (stringified for JSON)."""
        self.expect("{")
        items: list[tuple[object, object]] = []
        while True:
            kind, val = self.peek()
            if val == "}":
                self.take()
                break
            if val == "[":                      # [16] = ...
                self.take()
                key = self.expr()
                self.expect("]")
                self.expect("=")
                items.append((key, self.value()))
            elif kind == "name" and val not in ("true", "false", "nil"):
                self.take()
                self.expect("=")
                items.append((val, self.value()))
            else:                               # positional entry
                items.append((None, self.value()))
            if self.peek()[1] == ",":
                self.take()
        keys = [k for k, _ in items]
        if not items:
            return {}
        if all(k is None for k in keys) or keys == list(range(1, len(items) + 1)):
            return [v for _, v in items]
        return {str(k): v for k, v in items}


def _table_at(text: str, assignment: str):
    """Parse the table literal assigned by `assignment`.  Anchored at line start so the
    prose copy of `GEN3.profiles.emerald = {...}` in a comment is not mistaken for it."""
    m = re.search(r"^" + re.escape(assignment) + r"\s*=\s*\{", text, re.M)
    if not m:
        sys.exit(f"gen_gen3_profile: {SRC} has no `{assignment} = {{`")
    return _Lex(text, m.end() - 1).table()


def parse_profiles(text: str) -> dict:
    """{profile key: table} from GEN3.profiles = {...} plus the additive .emerald."""
    out = {k: v for k, v in _table_at(text, "GEN3.profiles").items() if v is not NIL}
    out["emerald"] = _table_at(text, "GEN3.profiles.emerald")
    return out


# ── the companion-patch native ABI (gen3_rr only) ────────────────────────────────
# Every `MB.NAME = <literal>` module constant in lua/mailbox.lua, plus the
# ghost/object-event addresses lua/peer_ghost_npc.lua carries as inline literals.
MAILBOX_RE = re.compile(r"^MB\.([A-Z][A-Z0-9_]*)\s*=\s*(0x[0-9A-Fa-f]+|\d+)\s*(?:--.*)?$", re.M)

# name -> regex over lua/peer_ghost_npc.lua; group 1 (and 2, when named) is the address.
GHOST_RE = {
    "OBJECT_EVENTS_BASE": re.compile(r"^local OE = (0x[0-9A-Fa-f]+)", re.M),
    "GMAIN_CB2_PTR|CB2_OVERWORLD": re.compile(
        r"memory\.read_u32_le\((0x[0-9A-Fa-f]+)\) ~= (0x[0-9A-Fa-f]+)"),
    "SPRITES_BASE": re.compile(r"memory\.read_u32_le\((0x[0-9A-Fa-f]+) \+ lsid\*0x44"),
    "OBJ_PALETTE_BUF": re.compile(r"memory\.read_u16_le\((0x[0-9A-Fa-f]+) \+ lslot\*0x20"),
    "CAMERA_Y_ADDR": re.compile(r"memory\.read_s16_le\((0x[0-9A-Fa-f]+)\) \+ 8"),
}


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def native_block() -> dict:
    values: dict[str, int] = {}
    src: dict[str, str] = {}
    text = (REPO / MAILBOX_SRC).read_text(encoding="utf-8", errors="replace")
    for m in MAILBOX_RE.finditer(text):
        name, lit = m.group(1), m.group(2)
        values[name] = int(lit, 16) if lit[:2].lower() == "0x" else int(lit)
        src[name] = f"{MAILBOX_SRC}:{_line_of(text, m.start())}"
    ghost = (REPO / GHOST_SRC).read_text(encoding="utf-8", errors="replace")
    for names, pat in GHOST_RE.items():
        m = pat.search(ghost)
        if not m:
            sys.exit(f"gen_gen3_profile: {GHOST_SRC} no longer carries {names}")
        line = f"{GHOST_SRC}:{_line_of(ghost, m.start())}"
        for i, name in enumerate(names.split("|"), start=1):
            if name in values:
                sys.exit(f"gen_gen3_profile: native name collision on {name}")
            values[name] = int(m.group(i), 16)
            src[name] = line
    values["_src"] = src  # type: ignore[assignment]
    return values


# ── assembly ─────────────────────────────────────────────────────────────────────
def _thumb_keys(rom: dict) -> list[str]:
    """ROM keys whose literal already carries the Thumb bit (bit 0 set).  The values are
    kept verbatim -- gTasks[].func / gMain.callback2 are read from RAM with the +1, so
    re-stripping here would make the profile disagree with what the client compares."""
    out = []
    for key, val in rom.items():
        vals = val if isinstance(val, list) else [val]
        nums = [v for v in vals if isinstance(v, int)]
        if nums and all(v & 1 for v in nums):
            out.append(key)
    return sorted(out)


def _title(profile: dict, title: str, key: str, admitted: bool) -> dict:
    sections: dict[str, dict] = {"ram": {}, "rom": {}, "derived": {}}
    for name, val in profile.items():
        section = SECTION.get(name)
        if section is None:
            sys.exit(f"gen_gen3_profile: {key}.{name} is not classified in SECTION")
        sections[section][name] = None if val is NIL else val
    out = {
        "variant": key,
        "admitted": admitted,
        "rom_thumb": _thumb_keys(sections["rom"]),
        **sections,
    }
    out.update(ROM_HASHES.get(title, {}))
    return out


def build(pack: str, profiles: dict, source: dict) -> dict:
    out = {
        "schema": SCHEMA,
        "generator": "tools/gen_gen3_profile.py",
        "pack": pack,
        "source": source,
        "titles": {t: _title(profiles[k], t, k, adm) for t, k, adm in PACKS[pack]},
    }
    if pack == "gen3_frlg":
        for title in ("firered", "leafgreen"):
            entry = out["titles"][title]
            path = f"data/gen3/pret/poke{title}.sym"
            text = (REPO / path).read_text(encoding="utf-8")
            matches = list(re.finditer(
                r"^([0-9a-fA-F]{8})\s+g\s+[0-9a-fA-F]+\s+gPokemonStorage$", text, re.M))
            if len(matches) != 1:
                sys.exit(f"gen_gen3_profile: {path} must name exactly one gPokemonStorage")
            match = matches[0]
            entry["ram"]["POKEMON_STORAGE_BASE"] = int(match[1], 16)
            entry["_src"] = {
                "ram.POKEMON_STORAGE_BASE":
                    f"{path}:{_line_of(text, match.start())} (gPokemonStorage; {PRET_PIN})",
            }
            for name, (value, where) in FRLG_DERIVED.items():
                entry["derived"][name] = value
                entry["_src"][f"derived.{name}"] = where
    if pack == "gen3_rr":
        # The existing RR detector explicitly rejects party counts above this limit.
        text = (REPO / SRC).read_text(encoding="utf-8")
        detector = re.search(r"^local function _detectRR\(\)(.*?)^end", text, re.M | re.S)
        match = re.search(r"^    if partyCount > (\d+) then return false end$",
                          detector[1] if detector else "", re.M)
        if not match:
            sys.exit(f"gen_gen3_profile: {SRC} no longer carries the RR party capacity check")
        entry = out["titles"]["radical_red"]
        entry["derived"]["PARTY_CAPACITY"] = int(match[1])
        entry["_src"] = {
            "derived.PARTY_CAPACITY":
                f"{SRC}:{_line_of(text, detector.start(1) + match.start())} (_detectRR partyCount limit)",
        }
        out["native"] = native_block()
    return out


def source_block(text: str) -> dict:
    head = subprocess.run(["git", "log", "-1", "--format=%H", "--", SRC],
                          cwd=REPO, capture_output=True, text=True).stdout.strip()
    return {
        "file": SRC,
        # the last commit that touched the source table, not the branch tip: a profile that
        # nothing changed must stay byte-identical so --check means "stale", not "rebased"
        "git_head": head or "unknown",
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def render(profile: dict) -> str:
    return json.dumps(profile, indent=2, sort_keys=True) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if a committed profile differs from a fresh generation")
    args = ap.parse_args()

    text = (REPO / SRC).read_text(encoding="utf-8", errors="replace")
    profiles = parse_profiles(text)
    source = source_block(text)
    stale = []
    for pack in PACKS:
        out = REPO / "data" / "games" / pack / "profile.json"
        rendered = render(build(pack, profiles, source))
        if args.check:
            current = out.read_text(encoding="utf-8") if out.exists() else ""
            if current != rendered:
                stale.append(str(out.relative_to(REPO)).replace("\\", "/"))
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8", newline="\n")
        titles = json.loads(rendered)["titles"]
        print(f"wrote data/games/{pack}/profile.json: " + ", ".join(
            f"{t} ram={len(v['ram'])} rom={len(v['rom'])} derived={len(v['derived'])}"
            for t, v in titles.items()))
    if stale:
        print("stale (run tools/gen_gen3_profile.py): " + ", ".join(stale), file=sys.stderr)
        return 1
    if args.check:
        print("data/games/gen3_{frlg,rr}/profile.json are current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
