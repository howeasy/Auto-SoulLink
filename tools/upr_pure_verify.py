"""tools/upr_pure_verify.py — semantic verifier for the fork's pureRGB output (PLAN §6 M5).

tools/upr_write_domain_diff.py proves the fork writes only inside each category's byte
domain; nothing proved that what it writes is a valid game, or that a MODE did what its UI
label claims (review cx-795d1423 #13-#17). This walks the same tables and checks the CONTENT
against the facts pack (data/games/gen1_purergb/) and the record grammars the ROM uses:

    wild         species randomizable (see below), rate/count/pointer bytes unchanged; a slot
                 that held an opaque id (MissingNo in Sea Routes) is fixed
    starters     every site of starter N holds one species; three distinct randomizables
    statics      every Species site of a record agrees (roof Zapdos x3, Moltres x2 — W2); the
                 MissingNo static is fixed whole
    trainers     per record: tag ($FF/$FE/$FD or fixed level), custom-moveset id, palette
                 bit, terminator and record length identical (A12); the RookieData block is
                 aliased by exactly the classes trainers.json says; the two AI-table sites
                 stock UPR NOPs are untouched
    tms          50 distinct valid move ids disjoint from the 5 HM moves; HMs unchanged
    tm_compat    only the 55 flag bits move; the padding bit is unchanged
    field_items  in a map reachable from map 0 (UPR's preloadMap walk) a site holding one of
                 UPR's 49 placeable ids stays in that pool and a TM site stays a TM; every
                 other site (key items, HMs, pureRGB's own ids, unreachable maps) is fixed
    catch_rate   the +8 byte of the 151 dex records
    names        the whole InternalPokemonCount-row species-name table equals camel_names()
                 of the clean one (the lowercase_names tweak, fork revision 3), or is unchanged
    everywhere   audit() reports no stray byte; an enabled category changed something and a
                 disabled one changed nothing

and, when the settings SPEC is given (server.upr_settings.OPTIONS keys), what each mode
guarantees — every rule below is read from the fork's AbstractRomHandler / Gen1RomHandler /
Gen1Constants (.cache/slink-upr/src), never from UPR's log:

    level curves   out = min(100, floor(clean * (1 + N/100) + 0.5))   [Java Math.round]
    wild=area      within one table the clean->out species map is a function (injective for
                   restriction none / type_themed); wild=global: one map across every table,
                   except that the ghost-Marowak species is re-rolled in Pokemon Tower and
                   fishing tables (EncounterSet.bannedPokemon); catch_em_all: every pool
                   species appears; type_themed: a table's species share a type;
                   block_legendaries: dex 144-146/150/151 absent; the ghost species is absent
                   from Tower/fishing tables in every mode
    catch tier T   out = max(clean, tier) with (75/37, 128/64, 200/100, 255/255) for
                   ordinary/legendary; tier 5 leaves them and turns the Master-Ball
                   `jp z` into `jp` (one opcode byte, CA -> C3)
    starters       two_evos: each starter is a base species whose evolution evolves again
    statics        random/matching/similar draw without replacement -> all records distinct;
                   matching keeps legendary <-> legendary
    trainers       type_themed: a party shares a type; force_evolved N: a mon at level >= N
                   has no evolution left; block_legendaries as wild; "distributed" has no
                   seed-independent property (see _trainer_modes)
    tms            keep_field: a TM holding cut/fly/surf/strength/flash/dig/teleport is fixed;
                   compat full: all 55 bits of every record; sanity: a TM whose move is in a
                   species' level-up list is learnable
    field_items    shuffle: the multiset of pool items / of TMs is preserved; random and
                   random_even: field TMs are distinct and include the 18 required ones
                   ("evenly spread" has no seed-independent property, see field_items)

"Randomizable" = classification ordinary in species_index.json. The fork never emits the 13
NonDexSpecies[] ids (forms/spirits/MissingNo are opaque: FORK_CHANGES.md patch 2), so a form
appearing in a slot that did not hold it is a fork bug, not a feature.

    python tools/upr_pure_verify.py --clean ROM --out ROM --title purered --enable wild [...]
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from server.upr_settings import OPTIONS  # noqa: E402
from tools.upr_write_domain_diff import (  # noqa: E402
    INI,
    SECTION,
    _flat,
    _word,
    audit,
    domains_for_spec,
    field_item_bytes,
    guaranteed_catch_byte,
    load_entry,
    name_table_bytes,
)

FACTS = REPO / "data" / "games" / "gen1_purergb"
CATEGORIES = ("wild", "starters", "statics", "trainers", "tms", "tm_compat", "field_items", "catch_rate",
              "names")
OPAQUE_CLASSES = {"form", "spirit", "missingno"}
LEGENDARY_DEX = {144, 145, 146, 150, 151}          # Pokemon.legendaries, the Gen 1 members
FIELD_MOVES = {15, 19, 57, 70, 148, 91, 100}       # Gen1Constants.fieldMoves (ROM move ids == UPR ids: 165 real moves)
REQUIRED_FIELD_TMS = {3, 4, 8, 10, 12, 14, 16, 19, 20, 22, 25, 26, 30, 40, 43, 44, 45, 47}   # Gen1Constants.requiredFieldTMs
CATCH_TIERS = {1: (75, 37), 2: (128, 64), 3: (200, 100), 4: (255, 255)}   # changeCatchRates (ordinary, legendary)
TOWER_MAPS = range(0x90, 0x95)                     # Gen1Constants.towerMapsStart/EndIndex
TM_ITEM0 = 201                                     # Gen1Items.tm01; TMs 201..250
BANNED_TM_MOVES = {144, 165}     # Transform (Gen1Constants.java:64-65 bannedLevelupMoves, folded into
                                  # randomizeTMMoves' `banned` via getMovesBannedFromLevelup, A:4476/4497)
                                  # and Struggle (GlobalConstants.java:38 bannedRandomMoves[struggle]=true,
                                  # A:4493-4497) -- both excluded from TM selection unconditionally
EARLY_REQUIRED_HM = 15           # Cut: Gen1Constants.earlyRequiredHMs (the only entry) -- the move
                                  # getMoveCompatibilityProbability (A:4623-4640) treats as "required early"
HM01_BIT = 50                    # HM01 is compat flag 51 of 55 (1-based) = bit 50 (0-based); HM01 is
                                  # always Cut (the HM bytes are unchanged, see same("tms","HM move",...))
WARN_UNCHANGED = {"starters"}    # starters draws 3 without duplicates among themselves (A:4019-4028)
                                  # but never excludes the ORIGINAL trio -- drawing the same 3 back is a
                                  # legal outcome, not a bug (cx-73e80e05 #6). Every other category's
                                  # write domain is tens to hundreds of bytes (wild ~190+ slots, trainers'
                                  # every party, tms' 50 slots, ...) or is explicitly self-avoiding (wild=
                                  # global rerolls on a self-match, A:1207-1211), so a fully-unchanged run
                                  # there means the writer didn't run, not an unlucky draw


def _upr_field_pool() -> set[int]:
    """Gen1Constants.setupAllowedItems transcribed: ids 1..250 minus banSingles (townMap,
    bicycle, ?7, safariBall, pokedex, oldAmber, cardKey, ppUpGlitch, coin, ssTicket,
    goldTeeth), the badge / fossil-key / coinCase / unused / HM ranges; TMs are their own
    class. The fork uses vanilla's table on pure entries, so pureRGB ids that vanilla bans
    (HYPER BALL 0x05, SAFARI BALL 0x08, OLD COIN 0x17, POCKET ABRA 0x2C, APEX CHIP 0x32,
    COIN 0x3B, BOOSTER CHIP 0x4B) are never placed and a pickup holding one is fixed."""
    pool = set(range(1, 251))
    pool -= {5, 6, 7, 8, 9, 31, 48, 50, 59, 63, 64}
    for start, n in ((21, 8), (41, 5), (69, 10), (84, 112), (196, 5)):
        pool -= set(range(start, start + n))
    return pool - set(range(TM_ITEM0, TM_ITEM0 + 50))


FIELD_POOL = _upr_field_pool()


def _off(bank: int, ptr: int) -> int:
    """AbstractGBCRomHandler.calculateOffset: a pointer below 0x4000 is bank 0."""
    return ptr if ptr < 0x4000 else bank * 0x4000 + ptr - 0x4000


def _upr_item_sites(rom: bytes, e: dict) -> set[int]:
    """Gen1RomHandler.getItemOffsets: the item byte of every item-ball object in a map
    REACHED from map 0 through connections and warps (preloadMap), plus every hidden-item
    row of the special-map tables whose routine is a HiddenItemRoutineEntries[] one. The
    audit's field_item_bytes walks all 0xF8 map ids instead; pickups in maps nothing leads
    to (pureRGB's unused ids) are never rewritten."""
    banks, ptrs = e["MapBanks"], e["MapAddresses"]
    sites: set[int] = set()
    seen: set[int] = set()
    todo = [0]
    while todo:
        map_id = todo.pop()
        if map_id in seen or map_id in (0xED, 0xFF):
            continue
        seen.add(map_id)
        hdr = _off(rom[banks + map_id], _word(rom, ptrs + map_id * 2))
        bank = hdr // 0x4000
        ncons = bin(rom[hdr + 9] & 0xF).count("1")
        for i in range(ncons):
            todo.append(rom[hdr + 10 + i * 11])
        obj = _off(bank, _word(rom, hdr + 10 + ncons * 11))
        offs = obj + 2
        for _ in range(rom[obj + 1]):
            todo.append(rom[offs + 3])
            offs += 4
        offs += 1 + rom[offs] * 3
        n = rom[offs]
        offs += 1
        for _ in range(n):
            tid = rom[offs + 5]
            if tid & 0x40:
                offs += 8
            elif tid & 0x80 and rom[offs + 6] != 0:
                sites.add(offs + 6)
                offs += 7
            else:
                offs += 6
    routines = set(e.get("HiddenItemRoutineEntries", [e["HiddenItemRoutine"]]))
    lst, tbl = e["SpecialMapList"], e["SpecialMapPointerTable"]
    tbank = tbl // 0x4000
    idx = 0
    while rom[lst] != 0xFF:
        row = _off(tbank, _word(rom, tbl + idx))
        while rom[row] != 0xFF:
            if _off(rom[row + 3], _word(rom, row + 4)) in routines:
                sites.add(row + 2)
            row += 6
        lst += 1
        idx += 2
    return sites


def _curve(level: int, pct: int) -> int:
    """AbstractRomHandler level modifiers, all four sites: Math.min(100, (int) Math.round(level
    * (1 + levelModifier / 100.0))); Java Math.round(double) is floor(x + 0.5)."""
    return min(100, math.floor(level * (1 + pct / 100.0) + 0.5)) if pct else level


def _facts() -> dict:
    species = json.loads((FACTS / "species_index.json").read_text(encoding="utf-8"))["species"]
    items = json.loads((FACTS / "items.json").read_text(encoding="utf-8"))["items"]
    moves = json.loads((FACTS / "moves.json").read_text(encoding="utf-8"))["moves"]
    trainers = json.loads((FACTS / "trainers.json").read_text(encoding="utf-8"))
    evos = json.loads((FACTS / "evolutions.json").read_text(encoding="utf-8"))["evolutions"]
    types_doc = json.loads((FACTS / "types.json").read_text(encoding="utf-8"))
    name_to_type = {v: int(k) for k, v in types_doc["type_names"].items()}
    ordinary = {int(k) for k, v in species.items() if v["classification"] == "ordinary"}
    pre_evos: dict[int, list[int]] = collections.defaultdict(list)
    for k, targets in evos.items():
        for t in targets:
            pre_evos[t].append(int(k))
    return {
        "ordinary": ordinary,
        "opaque": {int(k) for k, v in species.items() if v["classification"] in OPAQUE_CLASSES},
        "names": {int(k): v["name"] for k, v in species.items()},
        "dex": {int(k): v["dex"] for k, v in species.items()},
        "types": {int(k): set(v["types"] or ()) for k, v in species.items()},
        "legendary": {int(k) for k, v in species.items() if v["dex"] in LEGENDARY_DEX and int(k) in ordinary},
        "evos": {int(k): v for k, v in evos.items()},
        "pre_evos": dict(pre_evos),
        "item_names": {int(k): v["name"] for k, v in items.items()},
        "moves": {m["id"] for m in moves},
        "trainers": trainers,
        # bstForPowerLevels (Gen1Pokemon.java:134-136): hp+attack+defense+special+speed, no Shedinja
        # exception in Gen 1 -- exactly the 5 base_stats fields the facts pack already carries
        "bst": {int(k): sum(v["stats"].values()) for k, v in species.items() if v["stats"]},
        "move_types": {m["id"]: name_to_type[m["type"]] for m in moves if m["type"] in name_to_type},
    }


def _strength_band(bst: int, pool_bsts, max_rounds: int, *, dedup: bool = True) -> tuple[int, int]:
    """The expanding-BST-window loop three callers share, each with its own ``canPick`` list
    and its own "reach 3 candidate Pokemon" stopping rule (never counted by distinct BST value
    -- two species sharing one BST are two candidates, not one, cx-86594273 #1):

    * pickWildPowerLvlReplacement (A:6980-7005): `while (canPick.isEmpty() || (canPick.size()
      < 3 && expandRounds < 3))`; each scan does `if (... && !canPick.contains(pk)) canPick.add`
      -- a per-OBJECT dedup, so ``canPick.size()`` after a scan is exactly the count of distinct
      species matched so far (``dedup=True``, cap 3: initial scan + at most two widened ones).
      ``pokemonPool`` there is the per-table/per-encounter local pool, not modeled here beyond
      the block_legendaries gate (see the wild=similar comment above).
    * pickStaticPowerLvlReplacement (A:7059-7082): identical shape and the same per-object
      `!canPick.contains(pk)` dedup (``dedup=True``, cap 3). ``pokemonPool`` there is
      ``pokemonLeft``, which the caller shrinks by removing each static's chosen replacement as
      it goes (A:4272) and excludes the record's own original species via ``banSamePokemon``
      (A:4269, A:7071, modeled separately above) -- the "previously chosen" shrinkage across
      static records is NOT modeled (same class of approximation as wild=global's aggregate
      bound: the true pool at any one static depends on the unknown draw order of every static
      before it in this run).
    * pickTrainerPokeReplacement's ``usePowerLevels`` branch (A:6925-6946): `while
      (canPick.isEmpty() || (canPick.size() < 3 && expandRounds < 2))`; each scan does
      `canPick.add(pk)` with NO contains-check, rescanning the WHOLE (unshrinking) `pickFrom`
      every round -- so a species matching both the initial and the widened band is counted
      TWICE toward "reach 3" (``dedup=False``, cap 2: initial scan + at most one widened one).
      This is what made a 2-widened-value fixture (two same-BST species, e.g. Kabuto/Omanyte at
      300) undercount to "2 distinct values" and wrongly widen past a band Java had already
      locked at the initial +-10% window.

    Returns the (lo, hi) bounds of the last scan that ran."""
    lo, hi = bst - bst // 10, bst + bst // 10
    step = max(bst // 20, 1)
    count = 0
    rounds = 0
    used_lo, used_hi = lo, hi
    while count == 0 or (count < 3 and rounds < max_rounds):
        used_lo, used_hi = lo, hi
        this_scan = sum(1 for v in pool_bsts if lo <= v <= hi)
        count = this_scan if dedup else count + this_scan
        lo -= step
        hi += step
        rounds += 1
    return used_lo, used_hi


def _ancestors_or_self(sp: int, pre_evos: dict) -> set[int]:
    """Every species whose fullyEvolve (A:6794-6832: a forward-only walk to a terminal, no
    backtracking) could end at ``sp`` -- ``sp``'s transitive pre-evolutions, plus ``sp`` itself
    (fullyEvolve is a no-op on an already-fully-evolved pick)."""
    reach, todo = {sp}, [sp]
    while todo:
        for p in pre_evos.get(todo.pop(), ()):
            if p not in reach:
                reach.add(p)
                todo.append(p)
    return reach


def _terminal_evolutions(sp: int, evos: dict) -> set[int]:
    """Every terminal fullyEvolve (A:6794-6832) could reach from ``sp`` by walking every
    evolutionsFrom edge (branch-exhaustive: Gen 1's only branch is Eevee). Used alone, for a
    single slot's own evolvesIntoTheWrongType exclusion, treating every branch as reachable
    cannot under-INCLUDE a candidate Java's real run excluded -- it can only keep something
    Java's real (seed-selected) branch would also have kept eligible, same direction as every
    other pool approximation here. It is NOT safe on its own once more than one slot in a party
    can each be credited via a *different* branch of the SAME split ancestor: fullyEvolve picks
    one branch per trainer (A:6826), so `_trainer_similar_strength`'s branch-consistency check
    is what actually closes that gap (cx-288123ae #3) -- this function only supplies the
    candidate terminals, it doesn't by itself rule out crediting two branches at once. A cyclic
    guard mirrors Java's ``seenMons`` check."""
    terms: set[int] = set()

    def walk(p: int, seen: frozenset[int]) -> None:
        nxt = [n for n in evos.get(p, ()) if n not in seen]
        if not nxt:
            terms.add(p)
            return
        for n in nxt:
            walk(n, seen | {n})

    walk(sp, frozenset({sp}))
    return terms


def _ghost_site(title: str, ini: pathlib.Path) -> int | None:
    """The species byte UPR reads as the ghost Marowak (StaticPokemonGhostMarowak{}): that
    species is EncounterSet.bannedPokemon in the Pokemon Tower and fishing tables."""
    text = ini.read_text(encoding="utf-8")
    m = re.search(r"^\[" + re.escape(SECTION[title]) + r"\]\n(.*?)(?=^\[|\Z)", text, re.S | re.M)
    g = re.search(r"StaticPokemonGhostMarowak\{\}=\{Species=\[\s*(0x[0-9A-Fa-f]+|\d+)", m.group(1)) if m else None
    return int(g.group(1), 0) if g else None


def camel_names(table: bytes, row: int) -> bytes:
    """RomFunctions.camelCase as the fork's lossless byte transform (Gen1RomHandler.
    applyCamelCaseNamesInPlace): per row, the first letter of each word keeps its case and
    the rest of A-Z ($80-$99) drop to a-z (+$20); a-z, the 'x ligatures ($BB-$BF, $E4, $E5)
    and the apostrophe ($E0) continue a word, anything else (space $7F, '.', the gender
    glyphs) ends one; the row ends at the first $50 pad. MR.MIME -> Mr.Mime, FARFETCH'D ->
    Farfetch'd, THE MAW -> The Maw, MISSINGNO. -> Missingno."""
    out = bytearray(table)
    for start in range(0, len(out), row):
        docap = True
        for j in range(start, start + row):
            b = out[j]
            if b == 0x50:
                break
            if 0x80 <= b <= 0x99:
                if not docap:
                    out[j] = b + 0x20
                docap = False
            elif 0xA0 <= b <= 0xB9 or 0xBB <= b <= 0xBF or b in (0xE0, 0xE4, 0xE5):
                docap = False
            else:
                docap = True
    return bytes(out)


class _Check:
    """One verification run: the two ROMs, the entry, the facts and the accumulators."""

    def __init__(self, title, clean, out, categories, trainers_levels, static_levels, ini, spec):
        self.title, self.clean, self.out = title, clean, out
        self.spec = spec
        self.cats = set(categories) if categories is not None else domains_for_spec(spec or {})
        self.tl, self.sl = trainers_levels, static_levels
        self.e = load_entry(title, ini)
        self.ghost_site = _ghost_site(title, ini)
        self.f = _facts()
        self.fails: list[str] = []
        self.warnings: list[str] = []
        self.domain: dict[str, set[int]] = {c: set() for c in CATEGORIES}

    # ── primitives ───────────────────────────────────────────────────────────────────
    def opt(self, key: str):
        """A setting from the spec, or OPTIONS' default; None when no spec was given."""
        return None if self.spec is None else self.spec.get(key, OPTIONS[key]["default"])

    def fail(self, msg: str) -> None:
        self.fails.append(msg)

    def same(self, cat: str, where: str, offs) -> None:
        for o in offs:
            if self.clean[o] != self.out[o]:
                self.fail(f"{cat}: {where} 0x{o:X} must be unchanged: {self.clean[o]:02X} -> {self.out[o]:02X}")

    def name(self, sp: int) -> str:
        return f"{self.f['names'].get(sp, 'no such id')} ({sp:02X})"

    def species(self, cat: str, where: str, o: int, fixed: bool = False) -> bool:
        """A species byte: fixed if it held an opaque id, else a randomizable id. Returns
        whether the slot is randomizable (clean species ordinary)."""
        self.domain[cat].add(o)
        c, v = self.clean[o], self.out[o]
        if c in self.f["opaque"]:
            if v != c:
                self.fail(f"{cat}: {where} 0x{o:X} held opaque {self.name(c)} and must be fixed, got {v:02X}")
            return False
        if c not in self.f["ordinary"]:
            self.fail(f"{cat}: {where} 0x{o:X} clean byte {c:02X} is neither ordinary nor opaque (facts/INI)")
            return False
        if v not in self.f["ordinary"]:
            self.fail(f"{cat}: {where} 0x{o:X} species {self.name(v)} is not randomizable")
            return False
        if fixed and v != c:
            self.fail(f"{cat}: {where} 0x{o:X} species must be unchanged on this mode: {self.name(c)} -> {self.name(v)}")
        return True

    def level(self, cat: str, where: str, o: int, may_change: bool, mask: int = 0xFF, pct: int | None = None) -> None:
        self.domain[cat].add(o)
        c, v = self.clean[o] & mask, self.out[o] & mask
        if pct is not None:                      # spec-driven: the exact curve
            if v != _curve(c, pct):
                self.fail(f"{cat}: {where} level 0x{o:X}: {c} -> {v}, the {pct:+d}% curve gives {_curve(c, pct)}")
        elif not may_change and v != c:
            self.fail(f"{cat}: {where} level 0x{o:X} must be unchanged: {c} -> {v}")
        elif not 1 <= v <= 100:
            self.fail(f"{cat}: {where} level 0x{o:X} = {v} is outside 1..100")

    def no_legendary(self, cat: str, where: str, o: int) -> None:
        if self.out[o] in self.f["legendary"]:
            self.fail(f"{cat}: {where} 0x{o:X} holds legendary {self.name(self.out[o])} with block_legendaries on")

    def shared_type(self, cat: str, where: str, offs: list[int]) -> None:
        common = set.intersection(*(self.f["types"][self.out[o]] for o in offs)) if offs else {0}
        if not common:
            self.fail(f"{cat}: {where} species share no type: "
                      + ", ".join(self.name(self.out[o]) for o in offs))

    # ── wild ─────────────────────────────────────────────────────────────────────────
    def _wild_tables(self) -> list[dict]:
        """Every EncounterSet the fork builds (Gen1RomHandler.getEncounters): one per unique
        grass / water table, the old-rod sites, each good-rod table, each unique super-rod
        set. `exempt` = the sets whose bannedPokemon holds the ghost species."""
        e, rom = self.e, self.clean
        tables: list[dict] = []
        tbl = e["WildPokemonTableOffset"]
        bank = tbl // 0x4000
        by_off: dict[int, list[int]] = {}
        map_id = -1
        while _word(rom, tbl) != 0xFFFF:
            map_id += 1
            self.same("wild", "table pointer", (tbl, tbl + 1))
            root = off = _flat(bank, _word(rom, tbl))
            tbl += 2
            if root in by_off:
                by_off[root].append(map_id)       # an aliased table: the list below sees it
                continue
            by_off[root] = [map_id]
            for kind in ("grass", "water"):
                self.same("wild", f"{kind} rate", (off,))
                rate = rom[off]
                off += 1
                if rate:
                    tables.append({"name": f"{kind} table @0x{off:X}", "maps": by_off[root],
                                   "slots": [(off + 2 * i, off + 2 * i + 1) for i in range(10)]})
                    off += 20
        for t in tables:
            t["exempt"] = any(m in TOWER_MAPS for m in t["maps"])
        tables.append({"name": "old rod", "exempt": True,
                       "slots": [(o + 2, o + 1) for o in e.get("OldRodOffsets", [e["OldRodOffset"]])]})
        for t in [e["GoodRodOffset"]] + ([e["GoodRodMonsOcean"]] if "GoodRodMonsOcean" in e else []):
            tables.append({"name": f"good rod @0x{t:X}", "exempt": True,
                           "slots": [(t + 2 * i, t + 2 * i + 1) for i in range(e.get("GoodRodPairCount", 2))]})
        sr = e["SuperRodTableOffset"]
        srbank = sr // 0x4000
        seen: set[int] = set()
        while rom[sr] != 0xFF:
            self.same("wild", "super rod map row", range(sr, sr + 3))
            set_off = _flat(srbank, _word(rom, sr + 1))
            sr += 3
            if set_off in seen:
                continue
            seen.add(set_off)
            self.same("wild", "super rod count", (set_off,))
            tables.append({"name": f"super rod @0x{set_off:X}", "exempt": True,
                           "slots": [(set_off + 1 + 2 * i, set_off + 2 + 2 * i) for i in range(rom[set_off])]})
        return tables

    def wild(self) -> None:
        mode, pct = self.opt("wild"), self.opt("wild_levels")
        tables = self._wild_tables()
        live: list[tuple[dict, int, int]] = []          # (table, level site, species site) of randomizable slots
        for t in tables:
            for lv, sp in t["slots"]:
                where = f"{t['name']} slot @0x{sp:X}"
                if self.clean[sp] in self.f["opaque"]:   # the fork skips BOTH bytes (Sea Routes rows carry level 120)
                    self.domain["wild"].add(lv)
                    self.same("wild", f"{where} level of an opaque slot", (lv,))
                    self.species("wild", where, sp)
                    continue
                self.level("wild", where, lv, True, pct=pct)
                if self.species("wild", where, sp, fixed=(mode == "unchanged")):
                    live.append((t, lv, sp))
        if mode in (None, "unchanged"):
            return
        restriction = self.opt("wild_restriction")
        if self.opt("wild_block_legendaries"):
            for t, _lv, sp in live:
                self.no_legendary("wild", f"{t['name']} slot", sp)
        ghost = self.out[self.ghost_site] if self.ghost_site is not None else None
        for t, _lv, sp in live:
            if t["exempt"] and self.out[sp] == ghost:
                self.fail(f"wild: {t['name']} slot 0x{sp:X} holds the ghost-Marowak species {self.name(ghost)}, "
                          f"which every mode bans from Tower and fishing tables")
        if mode == "area":
            for t in tables:
                m: dict[int, set[int]] = collections.defaultdict(set)
                for _t, _lv, sp in (x for x in live if x[0] is t):
                    m[self.clean[sp]].add(self.out[sp])
                for c, outs in m.items():
                    if len(outs) > 1:
                        self.fail(f"wild: area 1-to-1 broken in {t['name']}: {self.name(c)} -> "
                                  + ", ".join(self.name(v) for v in sorted(outs)))
                # restriction=similar (A:1096-1110): pickWildPowerLvlReplacement is called with
                # this table's `usedPks` history and excludes every entry in it, so it too is
                # per-table injective, same as none/type_themed
                if restriction in ("none", "type_themed", "similar"):
                    img = collections.Counter(next(iter(v)) for v in m.values() if len(v) == 1)
                    for v, n in img.items():
                        if n > 1:
                            self.fail(f"wild: area map not injective in {t['name']}: {n} species -> {self.name(v)}")
        elif mode == "global":
            m = collections.defaultdict(set)
            for t, _lv, sp in live:
                if not t["exempt"]:
                    m[self.clean[sp]].add(self.out[sp])
            for c, outs in m.items():
                if len(outs) > 1:
                    self.fail(f"wild: global 1-to-1 broken: {self.name(c)} -> "
                              + ", ".join(self.name(v) for v in sorted(outs)))
            # game1to1Encounters (A:1162-1225): remainingLeft is every species, remainingRight is
            # the destination pool (all species, or non-legendaries under block_legendaries); each
            # draw removes one from each and refills remainingRight from a fresh copy of the pool
            # when it empties. Gen 1 bans nothing for wild encounters (bannedForWildEncounters is
            # the AbstractRomHandler default, empty -- Gen1RomHandler doesn't override it, and Gen 1
            # has no alt formes so getBannedFormesForPlayerPokemon/getAbilityDependentFormes/
            # getIrregularFormes are all empty too), so with legendaries allowed remainingLeft and
            # remainingRight are the SAME 151-species list: they hit zero together, no refill ever
            # happens, and the map is a genuine bijection (max 1 use per destination). With
            # legendaries blocked remainingRight (146) is smaller than remainingLeft (151) by
            # exactly the 5 legendaries, so it refills once partway through: a destination can be
            # reused, but only across a refill, bounding any single destination's use count by
            # ceil(151/146) = 2
            # A per-destination bound alone is necessary but not sufficient: 151 sources onto a
            # 146-destination pool could otherwise pair 131 sources onto 74 destinations (57
            # excess pairings, each reused only twice) and slip past a bound of 2. But exactly
            # ONE refill ever happens (the first 146 draws exhaust remainingRight bijectively,
            # using every one of its 146 members exactly once; the remaining 151-146=5 draws
            # then reuse 5 of those same 146 a second time) -- so across the WHOLE map, at most
            # (total - pool_size) destinations can be reused at all, once each
            total, pool_size = len(self.f["ordinary"]), len(self.f["ordinary"] - self.f["legendary"])
            max_reuse = 1 if not self.opt("wild_block_legendaries") else -(-total // pool_size)
            excess_budget = 0 if not self.opt("wild_block_legendaries") else total - pool_size
            img = collections.Counter(next(iter(v)) for v in m.values() if len(v) == 1)
            for v, n in img.items():
                if n > max_reuse:
                    self.fail(f"wild: global map not injective (block_legendaries allows at most "
                              f"{max_reuse} reuse): {n} species -> {self.name(v)}")
            total_excess = sum(n - 1 for n in img.values() if n > 1)
            if total_excess > excess_budget:
                self.fail(f"wild: global map not injective (block_legendaries allows at most "
                          f"{excess_budget} reused destinations in total, from the one refill): "
                          f"{total_excess} excess pairings found")
            for t, _lv, sp in live:
                if t["exempt"] and self.clean[sp] in m:
                    want = next(iter(m[self.clean[sp]]))
                    if want != ghost and self.out[sp] != want:
                        self.fail(f"wild: global 1-to-1 broken in {t['name']} 0x{sp:X}: {self.name(self.clean[sp])} "
                                  f"-> {self.name(self.out[sp])}, elsewhere -> {self.name(want)}")
        if restriction == "catch_em_all":
            want = self.f["ordinary"] - (self.f["legendary"] if self.opt("wild_block_legendaries") else set())
            missing = want - {self.out[sp] for _t, _lv, sp in live}
            # random: a pick landing on an opaque slot is lost but the pool cycles 5+ times;
            # area: one pick per (table, clean species), so a table holding an opaque slot can
            # lose one species for good -- allow that many
            slack = 0 if mode == "random" else sum(any(self.clean[sp] in self.f["opaque"] for _lv, sp in t["slots"])
                                                   for t in tables)
            if len(missing) > slack:
                self.fail(f"wild: catch_em_all misses {len(missing)} species (slack {slack}): "
                          + ", ".join(self.name(v) for v in sorted(missing)[:8]))
        elif restriction == "type_themed":
            for t in tables:
                self.shared_type("wild", t["name"], [sp for _t, _lv, sp in live if _t is t])
        elif restriction == "similar" and mode in ("area", "random"):
            # pickWildPowerLvlReplacement(localAllowed, ..., 100) (A:6980-7005) is the SAME
            # helper and 3-scan loop (`expandRounds < 3`) for both area1to1EncountersImpl
            # (A:1104, per-table `usedPks` exclusion) and randomEncounters' usePowerLevels
            # branch (A:854-893, `usedUp=null` -- every Encounter is an independent draw, no
            # per-table exclusion at all). Approximation as before: area.bannedPokemon and
            # usedPks aren't modeled here (the pool used can only be a SUPERSET of Java's true,
            # smaller one, so this can reach 3 candidates in fewer widenings and compute a
            # narrower-than-true band -- a false reject is possible in principle, not observed
            # against a real jar run). wild=global+similar is NOT modeled -- game1to1Encounters'
            # pool (remainingRight) shrinks across the WHOLE map, so a snapshot band would be
            # wrong by an unknown, seed-dependent amount as it empties.
            pool = self.f["ordinary"] - (self.f["legendary"] if self.opt("wild_block_legendaries") else set())
            pool_bsts = [self.f["bst"][p] for p in pool]
            for t, _lv, sp in live:
                c, v = self.clean[sp], self.out[sp]
                lo, hi = _strength_band(self.f["bst"][c], pool_bsts, max_rounds=3)
                if not lo <= self.f["bst"][v] <= hi:
                    self.fail(f"wild: {t['name']} slot 0x{sp:X} {self.name(v)} (BST {self.f['bst'][v]}) is "
                              f"outside the similar_strength band [{lo},{hi}] around {self.name(c)} "
                              f"(BST {self.f['bst'][c]})")

    def catch_rate(self) -> None:
        tier = self.opt("wild_min_catch_rate") or 0
        size = self.e.get("BaseStatsEntrySize", 28)
        for i in range(151):
            o = self.e["PokemonStatsOffset"] + i * size + 8
            self.domain["catch_rate"].add(o)
            c, v = self.clean[o], self.out[o]
            want = max(c, CATCH_TIERS[tier][(i + 1) in LEGENDARY_DEX]) if tier in CATCH_TIERS else c
            if v != want:
                self.fail(f"catch_rate: dex {i + 1} 0x{o:X}: {c} -> {v}, tier {tier} gives {want}")
        # tier 5 (enableGuaranteedPokemonCatching): the `jp z, .captured` after `cp MASTER_BALL`
        # (prefix CF 7E FE 01) becomes an unconditional `jp` -- one opcode byte CA -> C3
        site = guaranteed_catch_byte(self.clean)
        if site is None:
            self.fail("catch_rate: the guaranteed-catch prefix CF7EFE01 is not in this ROM")
            return
        self.domain["catch_rate"].add(site)
        want = 0xC3 if tier == 5 else self.clean[site]
        if self.out[site] != want:
            self.fail(f"catch_rate: Master-Ball jump opcode 0x{site:X} is {self.out[site]:02X}, tier {tier} "
                      f"gives {want:02X}")

    # ── starters / statics ───────────────────────────────────────────────────────────
    def starters(self) -> None:
        chosen = []
        fixed = self.opt("starters") == "unchanged"
        for n in (1, 2, 3):
            sites = self.e[f"StarterOffsets{n}"]
            vals = {self.out[o] for o in sites}
            if len(vals) != 1:
                self.fail(f"starters: starter {n} sites disagree: "
                          + ", ".join(f"0x{o:X}={self.out[o]:02X}" for o in sites))
            for o in sites:
                self.species("starters", f"starter {n}", o, fixed=fixed)
            chosen.append(self.out[sites[0]])
        if len(set(chosen)) != 3:
            self.fail(f"starters: not three distinct species: {[f'{v:02X}' for v in chosen]}")
        if self.opt("starters") == "two_evos":   # random2EvosPokemon: no pre-evolution, an evolution that evolves
            evos = self.f["evos"]
            pre = {t for targets in evos.values() for t in targets}
            for n, v in enumerate(chosen, 1):
                if v in pre or not any(evos.get(t) for t in evos.get(v, [])):
                    self.fail(f"starters: starter {n} {self.name(v)} is not a base species with two evolutions ahead")

    def statics(self) -> None:
        mode, pct = self.opt("statics"), self.opt("static_levels")
        legacy_may_change = self.sl if self.spec is None else None
        live: list[int] = []
        for sp, lv in self.e["statics"]:
            where = f"static @0x{sp[0]:X}"
            vals = {self.out[o] for o in sp}
            if len(vals) != 1:
                self.fail(f"statics: {where} species sites disagree: "
                          + ", ".join(f"0x{o:X}={self.out[o]:02X}" for o in sp))
            randomizable = False
            for o in sp:
                randomizable = self.species("statics", where, o, fixed=(mode == "unchanged")) or randomizable
            for o in lv:
                if self.clean[sp[0]] in self.f["opaque"]:     # the fork skips the whole record
                    self.domain["statics"].add(o)              # (MissingNo sits at level 120)
                    self.same("statics", f"{where} level of an opaque record", (o,))
                else:
                    self.level("statics", where, o, bool(legacy_may_change), pct=pct)
            if len({self.out[o] for o in lv}) != 1:
                self.fail(f"statics: {where} level sites disagree: "
                          + ", ".join(f"0x{o:X}={self.out[o]}" for o in lv))
            if randomizable:
                live.append(sp[0])
        if mode in (None, "unchanged"):
            return
        # random / matching / similar all draw from a pool without replacement (refilled only
        # when empty: 146 non-legendaries, 5 legendaries) -> the records are pairwise distinct
        dupes = {v: n for v, n in collections.Counter(self.out[o] for o in live).items() if n > 1}
        for v, n in dupes.items():
            self.fail(f"statics: {self.name(v)} placed {n} times on mode {mode} (draws are without replacement)")
        if mode == "matching":                # RANDOM_MATCHING: onlyLegendaryList <-> noLegendaryList
            for o in live:
                c, v = self.clean[o], self.out[o]
                if (c in self.f["legendary"]) != (v in self.f["legendary"]):
                    self.fail(f"statics: matching broken @0x{o:X}: {self.name(c)} -> {self.name(v)}")
        elif mode == "similar":
            # pickStaticPowerLvlReplacement(pokemonLeft, oldPK, true, limitBST) (A:4265-4269):
            # pokemonLeft is the full 151-species pool (limitMainGameLegendaries/limit600 are
            # never set by our specs, so limitBST is always false and the >=600 BST branch never
            # triggers) -- the shared BST-window (_strength_band, cap 3: initial scan + at most
            # two widened ones). banSamePokemon=true (A:4269, A:7071) excludes the original
            # species itself from canPick, so a static's replacement must always differ from it
            pool_bsts = [self.f["bst"][p] for p in self.f["ordinary"]]
            for o in live:
                c, v = self.clean[o], self.out[o]
                if v == c:
                    self.fail(f"statics: @0x{o:X} {self.name(v)} is unchanged; similar_strength "
                              f"(banSamePokemon=true) always excludes the original species")
                    continue
                lo, hi = _strength_band(self.f["bst"][c], pool_bsts, max_rounds=3)
                if not lo <= self.f["bst"][v] <= hi:
                    self.fail(f"statics: @0x{o:X} {self.name(v)} (BST {self.f['bst'][v]}) is outside the "
                              f"similar_strength band [{lo},{hi}] around {self.name(c)} (BST {self.f['bst'][c]})")

    # ── trainers ─────────────────────────────────────────────────────────────────────
    def trainers(self) -> None:
        e, rom = self.e, self.clean
        tbl = e["TrainerDataTableOffset"]
        bank = tbl // 0x4000
        counts = e["TrainerDataClassCounts"]
        nclass = e.get("TrainerClassCount", 47)
        facts = self.f["trainers"]
        base = facts["opp_id_offset"]
        blocks: dict[int, list[int]] = {}
        for cls in range(1, nclass + 1):
            self.same("trainers", "class pointer", (tbl + (cls - 1) * 2, tbl + (cls - 1) * 2 + 1))
            blocks.setdefault(_flat(bank, _word(rom, tbl + (cls - 1) * 2)), []).append(cls)
        # the alias groups the ROM shows must be the ones the facts pack shows (RookieData)
        by_label: dict[str, list[int]] = {}
        for cls in range(1, nclass + 1):
            by_label.setdefault(facts["classes"][str(base + cls)]["data_label"], []).append(cls)
        want = {tuple(v) for v in by_label.values() if len(v) > 1}
        got = {tuple(v) for v in blocks.values() if len(v) > 1}
        if want != got:
            self.fail(f"trainers: aliased class groups {sorted(got)} != facts {sorted(want)}")
        # Gen1RomHandler.getTrainers (A:1396-1407): a global `index` counter increments once
        # per (class, record) pair as classes are visited in order 1..nclass, REGARDLESS of
        # aliasing -- two aliased classes each re-walk the same bytes and each record gets its
        # own trainer index. class_start[cls] is the index of that class's record 0.
        #
        # But setTrainers (A:1477-1518) writes classes back in the SAME order 1..nclass, to the
        # SAME per-class offset -- so for an aliased pointer, every class in the group writes the
        # record in turn and only the LAST one's bytes survive in the ROM. The effective trainer
        # index for an aliased record is therefore class_start[max(classes)] + idx, never any of
        # the earlier (overwritten) aliases' indices (cx-636b45dd #1).
        class_start: dict[int, int] = {}
        running = 1
        for cls in range(1, nclass + 1):
            class_start[cls] = running
            running += counts[cls]
        self.party_indices: dict[str, int] = {}          # where -> the FINAL WRITER's trainer index
        self.parties: list[tuple[str, list[tuple[int, int, int]]]] = []    # (where, [(lvl, species, mask)])
        for offs, classes in blocks.items():
            cls = classes[0]
            final_writer = classes[-1]                    # blocks lists classes in ascending order
            frecs = facts["classes"][str(base + cls)]["records"]
            if len({counts[c] for c in classes}) != 1:
                self.fail(f"trainers: aliased classes {classes} have different counts")
            if counts[cls] != len(frecs):
                self.fail(f"trainers: class {cls} count {counts[cls]} != facts {len(frecs)}")
            for idx in range(counts[cls]):
                where = f"class {cls} record {idx} @0x{offs:X}"
                self.party_indices[where] = class_start[final_writer] + idx
                offs = self._trainer_record(cls, idx, offs, frecs[idx] if idx < len(frecs) else None)
        etm = e["ExtraTrainerMovesTableOffset"]
        glm = e["GymLeaderMovesTableOffset"] - 0x44
        self.same("trainers", "ExtraTrainerMovesTable (stock UPR writes $FF)", (etm,))
        self.same("trainers", "champion-rival jump (stock UPR NOPs)", (glm, glm + 1))
        self._trainer_modes()

    def _trainer_record(self, cls: int, idx: int, p: int, frec: dict | None) -> int:
        rom, out = self.clean, self.out
        where = f"class {cls} record {idx} @0x{p:X}"
        tag = rom[p]
        grammar = {0xFF: "FF", 0xFE: "FE", 0xFD: "FD"}.get(tag, "fixed")
        if frec is not None and frec["grammar"] != grammar:
            self.fail(f"trainers: {where} grammar {grammar} != facts {frec['grammar']}")
        start = p
        p += 1
        mode, pct = self.opt("trainers"), self.opt("trainers_levels")
        legacy = self.tl if self.spec is None else None
        fixed = mode == "unchanged" and not self.opt("trainers_force_evolved")   # _trainer_modes walks the chain
        slots: list[tuple[int, int, int]] = []
        if grammar == "fixed":
            # the record byte IS the shared level: setTrainers writes pokemon[0].level there
            # unconditionally, so it follows the curve even when the party holds a form
            self.level("trainers", f"{where} shared", start, bool(legacy), pct=pct)
            while rom[p] != 0:
                if self.species("trainers", where, p, fixed=fixed):
                    slots.append((start, p, 0xFF))
                p += 1
        else:
            self.same("trainers", f"{where} tag", (start,))
            if grammar == "FD":
                self.same("trainers", f"{where} custom-moveset id", (p,))
                p += 1
            while rom[p] != 0:
                mask = 0xFF if grammar == "FF" else 0x7F
                if grammar != "FF":
                    if rom[p] & 0x80 != out[p] & 0x80:
                        self.fail(f"trainers: {where} palette bit 0x{p:X} changed: {rom[p]:02X} -> {out[p]:02X}")
                    self.domain["trainers"].add(p)
                if rom[p + 1] in self.f["opaque"]:      # setTrainers skips the whole pair of an opaque slot
                    self.domain["trainers"].add(p)
                    self.same("trainers", f"{where} level of an opaque slot", (p,))
                else:
                    self.level("trainers", where, p, bool(legacy), mask=mask, pct=pct)
                if self.species("trainers", where, p + 1, fixed=fixed):
                    slots.append((p, p + 1, mask))
                p += 2
        if out[p] != 0:
            self.fail(f"trainers: {where} terminator 0x{p:X} is {out[p]:02X}, not 00")
        # the record must end where the clean one does: no earlier 00 was introduced
        if 0 in out[start + 1:p]:
            self.fail(f"trainers: {where} contains a 00 before its terminator: length changed")
        if frec is not None:
            got_n = (p - start - 1 - (grammar == "FD")) // (1 if grammar == "fixed" else 2)
            if got_n != frec["party_size"]:
                self.fail(f"trainers: {where} party size {got_n} != facts {frec['party_size']}")
        self.parties.append((where, slots))
        return p + 1

    def _trainer_modes(self) -> None:
        mode, force = self.opt("trainers"), self.opt("trainers_force_evolved") or 0
        if mode is None:
            return
        evos = self.f["evos"]
        branch_parents = {p: tuple(targets) for p, targets in evos.items() if len(targets) > 1}
        branch_reqs: dict[int, list[tuple[str, int]]] = collections.defaultdict(list)
        if force:
            for where, slots in self.parties:
                for lv, sp, mask in slots:
                    c, v = self.clean[sp], self.out[sp]
                    lvl = self.out[lv] & mask
                    if mode == "unchanged":
                        # forceFullyEvolvedTrainerPokes (A:2069-2089) only touches a slot when
                        # tp.level >= minLevel; below that, the species must be byte-identical
                        # (nothing else in "unchanged" trainers touches it)
                        if lvl < force:
                            if v != c:
                                self.fail(f"trainers: {where} 0x{sp:X} {self.name(c)} -> {self.name(v)} changed "
                                          f"below the force_evolved threshold {force} (level {lvl})")
                        else:                                # walks evolutionsFrom (fullyEvolve)
                            reach, todo = {c}, [c]
                            while todo:
                                for n in evos.get(todo.pop(), []):
                                    if n not in reach:
                                        reach.add(n)
                                        todo.append(n)
                            if v not in reach:
                                self.fail(f"trainers: {where} 0x{sp:X} {self.name(c)} -> {self.name(v)} is not an "
                                          f"evolution of it (trainers unchanged, force_evolved {force})")
                            elif c in branch_parents and v in branch_parents[c]:
                                # "unchanged" makes no substitution before forceFullyEvolvedTrainer
                                # Pokes runs, so the pre-force selection is certainly `c` itself --
                                # this pins a required branch for the ROM's one seed regardless of
                                # trainers_similar_strength (cx-636b45dd #2)
                                branch_reqs[c].append((where, v))
                    if lvl >= force and evos.get(v):
                        self.fail(f"trainers: {where} 0x{sp:X} {self.name(v)} at level {lvl} >= "
                                  f"{force} still evolves (force_evolved)")
        if self.opt("trainers_similar_strength") and mode in ("random", "type_themed", "distributed"):
            for p, reqs in self._trainer_similar_strength(force, branch_parents).items():
                branch_reqs[p].extend(reqs)
        if branch_reqs:
            self._reconcile_branches(branch_reqs, branch_parents)
        if mode == "unchanged":
            return
        if self.opt("trainers_block_legendaries"):
            for where, slots in self.parties:
                for _lv, sp, _m in slots:
                    self.no_legendary("trainers", where, sp)
        if mode == "type_themed":
            for where, slots in self.parties:
                self.shared_type("trainers", where, [sp for _lv, sp, _m in slots])
        # "distributed" (pickTrainerPokeReplacement with usePlacementHistory) only refuses a
        # species whose count is >= 2x the mean over the species placed SO FAR, in a shuffled
        # trainer order. Every final multiset is reachable under that rule (place the most
        # frequent species first, then the next: the k-th copy of the j-th species needs
        # (j-2)(k-1) < 2*sum of the larger counts, which holds), so no seed-independent
        # property beyond pool membership exists to assert. (cx-758c671d #3) similar_strength's
        # own band (above) is unaffected by this and applies to distributed just like random.

    def _trainer_similar_strength(self, force: int, branch_parents: dict[int, tuple[int, ...]]
                                   ) -> dict[int, list[tuple[str, int]]]:
        # pickTrainerPokeReplacement(usePowerLevels=True) (A:6863-6978): cachedAllList is
        # noLegendaryList/mainPokemonList (A:1693-1694) -- the same block_legendaries-gated pool
        # wild/statics use, first narrowed to the party's theme type under type_themed
        # (A:6892-6918: pickFrom = cachedReplacementLists.get(type), itself built from
        # pokemonOfType(type, noLegendaries)); "distributed" and "random" never set a type, so
        # they always use the theme-less pool (A:6892 `type != null` is false either way).
        # Filtered further by a dynamic usedAsUniqueList/illegalIfEvolvedList that's empty here
        # (elite-four-unique-pokemon and illegal-evolution-chain blocking aren't in scope), then
        # the shared BST-window (_strength_band, cap 2: initial scan + at most one widened one).
        #
        # Randomizer.java:451-476 runs randomizeTrainerPokes (the selection this band
        # constrains) BEFORE forceFullyEvolvedTrainerPokes, so when this slot's level clears
        # trainers_force_evolved, `out` may be the fully-evolved TERMINAL of whatever was
        # selected (A:6794-6832), not the selection itself -- accept if any ancestor-or-self of
        # `out` (a legal pre-force selection) falls in the band. That ancestor must also be an
        # ELIGIBLE member of the pool it's credited against (cx-201b85a7 #2): a species can be
        # near the right BST while belonging to the wrong theme pool entirely (or none), which a
        # BST-only check can't catch.
        #
        # Under type_themed, a themed candidate that would force-evolve OUT of the theme is
        # excluded from selection before the window ever runs (evolvesIntoTheWrongType,
        # A:1849-1858, added to bannedList only when willForceEvolve for THIS slot, A:1897-1898)
        # -- with a fallback to the unfiltered pool if that leaves nothing (A:6920-6923,
        # `withoutBannedPokemon` is only used `if (!isEmpty())`).
        #
        # typeForTrainer is chosen ONCE per trainer (A:1836-1847), not per slot (cx-288123ae #2):
        # "some theme works for this slot" checked independently per slot is too permissive --
        # the SAME theme must explain every slot in the party. Every branch requirement this
        # collects is merged into the caller's ROM-wide reconciliation (_reconcile_branches,
        # cx-86594273 #2, cx-636b45dd #2) alongside whatever "trainers unchanged" forced directly.
        base_pool = self.f["ordinary"] - (self.f["legendary"] if self.opt("trainers_block_legendaries") else set())
        evos, pre_evos = self.f["evos"], self.f["pre_evos"]

        def pool_for(theme: int | None, will_force: bool) -> set[int]:
            pool = base_pool if theme is None else {p for p in base_pool if theme in self.f["types"][p]}
            if will_force and theme is not None:
                filtered = {p for p in pool if _terminal_evolutions(p, evos) & pool}
                if filtered:
                    pool = filtered
            return pool

        mode = self.opt("trainers")
        branch_reqs: dict[int, list[tuple[str, int]]] = collections.defaultdict(list)  # parent -> [(where, branch)]
        for where, slots in self.parties:
            if mode == "type_themed":
                # the actual theme type isn't recorded anywhere observable; every party member's
                # true type is IN the party's shared-type intersection (already required by
                # shared_type() above), so trying each candidate in it is a necessary, not
                # stronger-than-proven, check
                outs = [self.out[s] for _lv, s, _m in slots]
                common = set.intersection(*(self.f["types"][o] for o in outs)) if outs else set()
                themes: list[int | None] = sorted(common)
                if not themes:                        # shared_type() already reported the empty intersection
                    continue
            else:
                themes = [None]

            party_failure: str | None = None
            for theme in themes:
                slot_data = []                        # (sp, v, v_bst, justifying) per slot
                for lv, sp, mask in slots:
                    c_bst, v = self.f["bst"][self.clean[sp]], self.out[sp]
                    lvl = self.out[lv] & mask
                    will_force = bool(force) and lvl >= force
                    candidates = _ancestors_or_self(v, pre_evos) if will_force else {v}
                    pool = pool_for(theme, will_force)
                    pool_bsts = [self.f["bst"][p] for p in pool]
                    lo, hi = _strength_band(c_bst, pool_bsts, max_rounds=2, dedup=False)
                    justifying = {x for x in candidates if x in pool and lo <= self.f["bst"][x] <= hi}
                    slot_data.append((sp, v, c_bst, justifying))
                unjustified = [(sp, v, c_bst) for sp, v, c_bst, j in slot_data if not j]
                if unjustified:
                    sp, v, c_bst = unjustified[0]
                    party_failure = (f"trainers: {where} 0x{sp:X} {self.name(v)} (BST {self.f['bst'][v]}) is "
                                     f"outside the similar_strength band around {self.name(self.clean[sp])} "
                                     f"(BST {c_bst})")
                    continue
                # every slot has a justifying candidate under this theme -- check that any
                # branching ancestor relied on exclusively resolves to one branch throughout
                branch_used: dict[int, set[int]] = collections.defaultdict(set)
                for _sp, v, _c_bst, justifying in slot_data:
                    for p, targets in branch_parents.items():
                        if justifying == {p}:
                            branch = next((t for t in targets if t in _ancestors_or_self(v, pre_evos)), None)
                            if branch is not None:
                                branch_used[p].add(branch)
                split = {p: b for p, b in branch_used.items() if len(b) > 1}
                if split:
                    p, b = next(iter(split.items()))
                    party_failure = (f"trainers: {where} similar_strength needs {self.name(p)} to evolve into "
                                     + " AND ".join(self.name(x) for x in sorted(b))
                                     + " at once (fullyEvolve's branch is fixed per trainer, A:6826)")
                    continue
                party_failure = None
                for p, b in branch_used.items():
                    branch_reqs[p].append((where, next(iter(b))))
                break
            if party_failure:
                self.fail(party_failure)
        return branch_reqs

    def _reconcile_branches(self, branch_reqs: dict[int, list[tuple[str, int]]],
                             branch_parents: dict[int, tuple[int, ...]]) -> None:
        # ROM-wide branch reconciliation (cx-86594273 #2): evolutionIndex = (fullyEvolvedRandomSeed
        # + trainerIndex) % branches.size() (A:6826) draws fullyEvolvedRandomSeed ONCE per ROM
        # (A:6795-6797), so the branch a party needs isn't independent per trainer -- it's pinned
        # to that ONE seed value via the trainer's own index (party_indices: the FINAL WRITER's
        # index for an aliased record, cx-636b45dd #1). Runs for every source of a forced split
        # evolution (trainers=unchanged's direct reachability walk, or similar_strength's
        # ancestor-crediting) regardless of trainer mode (cx-636b45dd #2) -- the whole ROM is
        # legal only if some single S satisfies every one of these requirements at once.
        for p, reqs in branch_reqs.items():
            targets = branch_parents[p]
            n = len(targets)
            allowed = [(where, branch, {seed for seed in range(n)
                                         if (seed + self.party_indices.get(where, 0)) % n == targets.index(branch)})
                       for where, branch in reqs]
            combined = set(range(n))
            for _w, _b, s in allowed:
                combined &= s
            if not combined:
                conflict = next(((a, b) for i, a in enumerate(allowed) for b in allowed[i + 1:]
                                  if not (a[2] & b[2])), (allowed[0], allowed[-1]))
                (w0, b0, _), (w1, b1, _) = conflict
                self.fail(f"trainers: {self.name(p)}'s evolution needs {self.name(b0)} for {w0} "
                          f"(trainer index {self.party_indices.get(w0, '?')}) and {self.name(b1)} for {w1} "
                          f"(trainer index {self.party_indices.get(w1, '?')}) at once -- fullyEvolve's branch "
                          f"depends only on one seed drawn per ROM and the trainer's own index "
                          f"(A:6795-6797, 6826), so no single seed satisfies both")

    # ── TMs ──────────────────────────────────────────────────────────────────────────
    def tms(self) -> None:
        t = self.e["TMMovesOffset"]
        tm = list(self.out[t:t + 50])
        hm = list(self.clean[t + 50:t + 55])
        self.domain["tms"].update(range(t, t + 50))
        for i, m in enumerate(tm):
            if m not in self.f["moves"]:
                self.fail(f"tms: TM{i + 1:02d} @0x{t + i:X} = {m:02X} is not a move id")
            elif m in BANNED_TM_MOVES:
                self.fail(f"tms: TM{i + 1:02d} @0x{t + i:X} = {m:02X} is Transform/Struggle, banned from "
                          f"random TM selection")
        dupes = sorted({m for m in tm if tm.count(m) > 1})
        if dupes:
            self.fail(f"tms: duplicate TM moves {[f'{m:02X}' for m in dupes]}")
        clash = sorted(set(tm) & set(hm))
        if clash:
            self.fail(f"tms: TM moves duplicate HM moves {[f'{m:02X}' for m in clash]}")
        self.same("tms", "HM move", range(t + 50, t + 55))
        if self.opt("tms") == "unchanged":
            self.same("tms", "TM move (tms unchanged)", range(t, t + 50))
        elif self.opt("tm_keep_field"):     # randomizeTMMoves: newTMs.add(oldTMs.get(i)) for a field move
            for i in range(50):
                if self.clean[t + i] in FIELD_MOVES and tm[i] != self.clean[t + i]:
                    self.fail(f"tms: TM{i + 1:02d} held field move {self.clean[t + i]:02X} and keep_field is on, "
                              f"got {tm[i]:02X}")

    def _learnset(self, internal: int) -> set[int]:
        """Level-up moves as getMovesLearnt reads them: the four level-1 moves of the base
        stats record, then the (level, move) pairs after the evolution list."""
        rom, e = self.clean, self.e
        size = e.get("BaseStatsEntrySize", 28)
        stats = e["PokemonStatsOffset"] + (self.f["dex"][internal] - 1) * size
        moves = {rom[stats + d] for d in range(15, 19)} - {0}
        pt = e["PokemonMovesetsTableOffset"]
        p = _flat(pt // 0x4000, _word(rom, pt + (internal - 1) * 2))
        while rom[p] != 0:
            p += {1: 3, 2: 4, 3: 3}[rom[p]]
        p += 1
        while rom[p] != 0:
            moves.add(rom[p + 1])
            p += 2
        return moves

    def tm_compat(self) -> None:
        size = self.e.get("BaseStatsEntrySize", 28)
        sanity, compat_mode = self.opt("tm_sanity"), self.opt("tm_compat")
        t = self.e["TMMovesOffset"]
        by_dex = {self.f["dex"][i]: i for i in self.f["ordinary"]}
        for i in range(151):
            base = self.e["PokemonStatsOffset"] + i * size + 0x14
            self.domain["tm_compat"].update(range(base, base + 7))
            if (self.clean[base + 6] ^ self.out[base + 6]) & 0x80:     # 55 flags in 56 bits
                self.fail(f"tm_compat: dex {i + 1} padding bit 0x{base + 6:X} changed")
            if compat_mode == "full":            # fullTMHMCompatibility: flags 1..55 all true
                got = int.from_bytes(self.out[base:base + 7], "little") & (1 << 55) - 1
                if got != (1 << 55) - 1:
                    self.fail(f"tm_compat: dex {i + 1} lacks TM/HM bits {[n + 1 for n in range(55) if not got >> n & 1][:6]} "
                              f"on mode full")
            elif compat_mode == "unchanged" and not sanity:
                self.same("tm_compat", f"dex {i + 1} compat byte", range(base, base + 7))
            elif compat_mode == "prefer_type":
                # getMoveCompatibilityProbability (A:4623-4640): preferSameType gives a 0.9
                # chance for a same-type move, then requiredEarlyOn multiplies by 1.8 capped at
                # 1.0 -- 0.9*1.8=1.62->1.0 is the ONLY combination that reaches certainty, and
                # Cut is the only move in Gen1Constants.earlyRequiredHMs, so any species sharing
                # Cut's type is guaranteed to learn HM01
                if (self.f["move_types"][EARLY_REQUIRED_HM] in self.f["types"][by_dex[i + 1]]
                        and not self.out[base + HM01_BIT // 8] >> (HM01_BIT % 8) & 1):
                    self.fail(f"tm_compat: dex {i + 1} shares Cut's type and must learn HM01 "
                              f"(probability 1) under prefer_type")
            if not sanity:
                continue
            if compat_mode == "unchanged":       # ensureTMCompatSanity only SETS bits
                for j in range(7):
                    if self.clean[base + j] & ~self.out[base + j] & 0xFF:
                        self.fail(f"tm_compat: dex {i + 1} byte 0x{base + j:X} lost a bit with only tm_sanity on")
            learnt = self._learnset(by_dex[i + 1])
            for n in range(1, 51):
                if self.out[t + n - 1] in learnt and not self.out[base + (n - 1) // 8] >> ((n - 1) % 8) & 1:
                    self.fail(f"tm_compat: dex {i + 1} learns move {self.out[t + n - 1]:02X} by level but cannot "
                              f"use TM{n:02d} (tm_sanity)")

    # ── names ────────────────────────────────────────────────────────────────────────
    def names(self) -> None:
        tbl = name_table_bytes(self.e)
        self.domain["names"].update(tbl)
        clean, out = self.clean[tbl.start:tbl.stop], self.out[tbl.start:tbl.stop]
        on = "names" in self.cats if self.spec is None else self.opt("lowercase_names")
        want = camel_names(clean, self.e["PokemonNamesLength"]) if on else clean
        if out != want:
            i = next(i for i in range(len(out)) if out[i] != want[i])
            self.fail(f"names: row {i // self.e['PokemonNamesLength'] + 1} 0x{tbl.start + i:X}: "
                      f"{out[i]:02X}, camel rule gives {want[i]:02X}")

    # ── field items ──────────────────────────────────────────────────────────────────
    def field_items(self) -> None:
        f = self.f
        mode = self.opt("field_items")
        pool_sites, tm_sites = [], []
        reachable = _upr_item_sites(self.clean, self.e)
        for o in sorted(field_item_bytes(self.clean, self.e) | reachable):
            self.domain["field_items"].add(o)
            c, v = self.clean[o], self.out[o]
            cname, vname = f["item_names"].get(c, "not in items.json"), f["item_names"].get(v, "not in items.json")
            if o not in reachable:
                if v != c:
                    self.fail(f"field_items: 0x{o:X} {cname} ({c:02X}) sits in a map no connection or warp reaches "
                              f"(UPR never loads it) and must be fixed, got {vname} ({v:02X})")
            elif c in FIELD_POOL:
                pool_sites.append(o)
                if v not in FIELD_POOL:
                    self.fail(f"field_items: 0x{o:X} {cname} ({c:02X}) -> {vname} ({v:02X}) is not in UPR's pool")
            elif TM_ITEM0 <= c < TM_ITEM0 + 50:
                tm_sites.append(o)
                if not TM_ITEM0 <= v < TM_ITEM0 + 50:
                    self.fail(f"field_items: 0x{o:X} {cname} ({c:02X}) -> {vname} ({v:02X}) is not a TM")
            elif v != c:
                self.fail(f"field_items: 0x{o:X} {cname} ({c:02X}) is outside UPR's pool and must be fixed, "
                          f"got {vname} ({v:02X})")
        if mode in (None, "unchanged"):
            if mode == "unchanged":
                self.same("field_items", "pickup (field_items unchanged)", pool_sites + tm_sites)
            return
        tms = collections.Counter(self.out[o] - TM_ITEM0 + 1 for o in tm_sites)
        if mode == "shuffle":
            for label, sites in (("items", pool_sites), ("TMs", tm_sites)):
                a, b = collections.Counter(self.clean[o] for o in sites), collections.Counter(self.out[o] for o in sites)
                if a != b:
                    diff = {f["item_names"].get(k, k): (a[k], b[k]) for k in set(a) | set(b) if a[k] != b[k]}
                    self.fail(f"field_items: shuffle changed the multiset of {label}: {diff}")
        else:                                     # randomizeFieldItems: required TMs + distinct random others
            dupes = {n: k for n, k in tms.items() if k > 1}
            if dupes:
                self.fail(f"field_items: field TMs repeat on mode {mode}: {dupes}")
            missing = REQUIRED_FIELD_TMS - set(tms) if len(tm_sites) >= len(REQUIRED_FIELD_TMS) else set()
            if missing:
                self.fail(f"field_items: required field TMs missing on mode {mode}: {sorted(missing)}")
            # "random_even" re-rolls (up to 100 times) an item whose count exceeds the mean over
            # the items placed SO FAR, then shuffles the placements: as for trainers
            # "distributed", every multiset is reachable (the most frequent item first is always
            # at count == mean), so nothing beyond pool membership is assertable. (cx-758c671d #3)

    # ── driver ───────────────────────────────────────────────────────────────────────
    def run(self) -> dict:
        if len(self.clean) != len(self.out):
            return {"ok": False, "failures": [f"length differs: {len(self.clean)} vs {len(self.out)}"],
                    "changed": {}}
        want_opaque = set(self.e.get("NonDexSpecies", []))
        if want_opaque != self.f["opaque"]:
            self.fail(f"facts: INI NonDexSpecies {sorted(want_opaque)} != species_index opaque "
                      f"{sorted(self.f['opaque'])}")
        for cat in CATEGORIES:
            getattr(self, cat)()
        changed = {cat: sum(self.clean[o] != self.out[o] for o in dom) for cat, dom in self.domain.items()}
        for cat in CATEGORIES:
            if cat in self.cats and changed[cat] == 0:
                if cat in WARN_UNCHANGED:
                    self.warnings.append(f"{cat}: enabled but nothing changed (a legal outcome for this mode)")
                else:
                    self.fail(f"{cat}: enabled but nothing in its domain changed")
            elif cat not in self.cats and changed[cat]:
                first = sorted(o for o in self.domain[cat] if self.clean[o] != self.out[o])[:5]
                self.fail(f"{cat}: disabled but {changed[cat]} byte(s) changed, first "
                          + ", ".join(f"0x{o:X}" for o in first))
        stray = audit(self.title, self.clean, self.out, self.cats)["stray"]
        if stray:
            self.fail(f"audit: {len(stray)} stray byte(s) outside the enabled domains, first "
                      + ", ".join(f"0x{o:X}: {self.clean[o]:02X}->{self.out[o]:02X}" for o in stray[:5]))
        return {"ok": not self.fails, "failures": self.fails, "warnings": self.warnings, "changed": changed}


def verify(title: str, clean_bytes: bytes, out_bytes: bytes, categories=None, *,
           trainers_levels: bool = False, static_levels: bool = False, ini: pathlib.Path = INI,
           spec: dict | None = None) -> dict:
    """{"ok", "failures": [str], "changed": {category: bytes changed}} for one output ROM.

    ``categories`` gates the write domains (default: domains_for_spec(spec)); ``spec`` (the
    OPTIONS keys the .rnqs was built from) turns on the per-mode guarantees. Without a spec
    only validity is checked and the two level bools say whether levels may move at all."""
    if categories is None and spec is None:
        raise ValueError("give categories, a spec, or both")
    unknown = set(categories or ()) - set(CATEGORIES)
    if unknown:
        raise ValueError(f"unknown categories: {sorted(unknown)}")
    return _Check(title, clean_bytes, out_bytes, categories, trainers_levels, static_levels, ini, spec).run()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--clean", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="purered", choices=sorted(SECTION))
    ap.add_argument("--enable", action="append", default=[], choices=CATEGORIES)
    ap.add_argument("--spec", help="JSON of the OPTIONS keys the settings file was built from")
    ap.add_argument("--trainers-levels", action="store_true", help="trainer levels were curved (no --spec)")
    ap.add_argument("--static-levels", action="store_true", help="static levels were curved (no --spec)")
    ap.add_argument("--ini", default=str(INI))
    args = ap.parse_args()
    spec = json.loads(args.spec) if args.spec else None
    r = verify(args.title, pathlib.Path(args.clean).read_bytes(), pathlib.Path(args.out).read_bytes(),
               set(args.enable) if args.enable or spec is None else None,
               trainers_levels=args.trainers_levels, static_levels=args.static_levels,
               ini=pathlib.Path(args.ini), spec=spec)
    print(f"enabled={sorted(args.enable)} changed={r['changed']}")
    for msg in r["failures"]:
        print(f"  FAIL {msg}")
    print("SEMANTICS OK" if r["ok"] else f"SEMANTICS VIOLATED ({len(r['failures'])})")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
