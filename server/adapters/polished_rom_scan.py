"""Read-only decoder of a Polished Crystal 3.2.3 ROM's rule and wild tables, for the randomizer
pipeline (server/upr_pipeline.py `_check_content_polished`) and its tests.

Formats (polishedcrystal@3fa43192, tag v3.2.3; docs/polished/UPR_HANDLER.md §3):
  BaseData        34-byte records (BASE_DATA_SIZE, constants/pokemon_data_constants.asm:35): stats x6,
                  types x2, catch rate, base exp, items x2, gender|hatch, abilities x3, growth rate,
                  egg groups, EV yield x2, 14 TM/HM/tutor bit bytes. Records 1..291 are the species,
                  292..337 the variant forms (NUM_VARIANT_FORMS = 46).
  EvosAttacks     per record: evolutions [method, param (a 2-byte species for EVOLVE_PARTY), extra
                  (EVOLVE_HOLDING / EVOLVE_STAT), target dp] up to $FF, then (level, move) up to $FF.
  wild            eight map-keyed tables ended by $FF: grass = map (2), 3 rates, morn/day/nite x 7 x
                  (level, dp); water = map (2), rate, 3 x (level, dp) (data/wild/*.asm).
  FishGroups      15 rows of 2 chance bytes + 3 rod pointers; a rod list is (chance, dp, level) up to
                  chance $FF inclusive (data/wild/fish.asm).
  TreeMons        10 set pointers; a set is a common then a rare (chance, dp, level) list each ended
                  by $FF, the last set (ROCK) has only one (data/wild/treemons.asm).
  ContestMons     12 x (chance, dp, min, max), no terminator (data/wild/bug_contest_mons.asm).
A dp species is (LOW, HIGH << 5 | form): 9-bit species, form in bits 0-4 (macros/data.asm:89-91).

Offsets come from the generated UPR INI (data/polished/upr_polished_entries.ini, from the release
.sym). The SLink overlay (patch/dist/SLink-Polished.ups) touches only ROM0 $0070, the DelayFrame
lead-in, bank $7E and the header, so the same offsets hold on the overlay and on UPR's output of it.
``pinned=True`` (the default) admits only those two pinned artifacts; ``pinned=False`` exists for
the content check, which must read a randomized output.
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
from pathlib import Path

from server.adapters.gen2_rom_scan import RomScanError, _Cursor

REPO = Path(__file__).resolve().parents[2]
INI = REPO / "data" / "polished" / "upr_polished_entries.ini"
ROM_SIZE = 0x200000
HEADER_TITLE = b"PKPCRYSTAL"
BASE_DATA_SIZE = 34
WILD_TABLES = ("JohtoGrass", "JohtoWater", "KantoGrass", "KantoWater",
               "OrangeGrass", "OrangeWater", "SwarmGrass", "SwarmWater")
GRASS_SLOTS = 7                                 # per time of day (wildmon rows)
FISH_GROUPS = 15                                # NUM_FISHGROUPS, constants/map_data_constants.asm:68
TREE_SETS = 10                                  # NUM_TREEMON_SETS, constants/pokemon_data_constants.asm:381
CONTEST_MONS = 12                               # (ContestMonsEnd - ContestMons) / 5
EVOLVE_HOLDING, EVOLVE_STAT, EVOLVE_PARTY = 4, 6, 10   # constants/pokemon_data_constants.asm:312-323
_MAX_ROWS = 512                                 # bound on every terminator-ended walk


@functools.cache
def offsets() -> dict[str, int]:
    """Every numeric key of the generated INI (comments stripped)."""
    out = {}
    for line in INI.read_text(encoding="utf-8").splitlines():
        key, eq, value = line.split("//")[0].strip().partition("=")
        if eq and re.fullmatch(r"0x[0-9A-Fa-f]+|\d+", value.strip()):
            out[key.strip()] = int(value.strip(), 0)
    return out


@functools.cache
def pinned_sha1s() -> dict[str, str]:
    """sha1 -> kind for the two pinned artifacts: the v3.2.3 release ("clean") and the SLink
    companion overlay ("overlay", data/polished/overlay_provenance.json)."""
    lock = json.loads((REPO / "data" / "polished_sources.lock.json").read_text(encoding="utf-8"))
    prov = json.loads((REPO / "data" / "polished" / "overlay_provenance.json").read_text(encoding="utf-8"))
    return {lock["outputs"]["polishedcrystal"]["sha1"].lower(): "clean", prov["output"]["sha1"].lower(): "overlay"}


def identify(rom: bytes) -> dict | None:
    """{"kind": "clean" | "overlay"} for a pinned Polished artifact, else None (by sha1 only)."""
    kind = pinned_sha1s().get(hashlib.sha1(rom).hexdigest())
    return {"kind": kind} if kind else None


def _dp(lo: int, hi: int) -> list[int]:
    return [lo | (hi & 0x20) << 3, hi & 0x1F]


class Rom:
    def __init__(self, rom: bytes, *, pinned: bool = True):
        if len(rom) != ROM_SIZE or rom[0x134:0x134 + len(HEADER_TITLE)] != HEADER_TITLE:
            raise RomScanError("not a 2 MiB PKPCRYSTAL cartridge")
        if pinned and identify(rom) is None:
            raise RomScanError("ROM SHA1 is neither the pinned Polished Crystal 3.2.3 release nor its SLink overlay")
        self.rom, self.o = rom, offsets()
        self.records = self.o["SpeciesCount"] + self.o["VariantFormCount"]

    def _at(self, offset: int, label: str) -> _Cursor:
        return _Cursor(self.rom, offset, label)

    def _pointer(self, table: int, word: int, label: str) -> _Cursor:
        if not 0x4000 <= word < 0x8000:
            raise RomScanError(f"{label}: pointer {word:04X} is not a ROMX address")
        return self._at(table // 0x4000 * 0x4000 + word - 0x4000, label)

    def _record(self, index: int) -> int:
        if type(index) is not int or not 1 <= index <= self.records:
            raise RomScanError(f"record {index!r} outside 1..{self.records}")
        return index

    def base_stats(self, index: int) -> dict:
        raw = self._at(self.o["PokemonStatsOffset"] + (self._record(index) - 1) * BASE_DATA_SIZE,
                       f"BaseData {index}").take(BASE_DATA_SIZE)
        return {"stats": list(raw[0:6]), "types": list(raw[6:8]), "catch_rate": raw[8], "base_exp": raw[9],
                "items": list(raw[10:12]), "gender_hatch": raw[12], "abilities": list(raw[13:16]),
                "growth_rate": raw[16], "egg_groups": raw[17], "ev_yield": list(raw[18:20]),
                "tmhm": list(raw[20:34])}

    def evos_attacks(self, index: int) -> dict:
        table = self.o["PokemonMovesetsTableOffset"]
        word = self._at(table + (self._record(index) - 1) * 2, "EvosAttacksPointers").word()
        cur = self._pointer(table, word, f"EvosAttacks {index}")
        evolutions, learnset = [], []
        while (method := cur.byte()) != 0xFF:
            if not 1 <= method <= EVOLVE_PARTY or len(evolutions) > 16:
                raise RomScanError(f"EvosAttacks {index}: unknown evolution method {method}")
            params = _dp(*cur.take(2))[:1] if method == EVOLVE_PARTY else [cur.byte()]
            if method in (EVOLVE_HOLDING, EVOLVE_STAT):
                params.append(cur.byte())
            evolutions.append([method, *params, *_dp(*cur.take(2))])
        while (level := cur.byte()) != 0xFF:
            if len(learnset) > 128:
                raise RomScanError(f"EvosAttacks {index}: learnset has no terminator")
            learnset.append([level, cur.byte()])
        return {"evolutions": evolutions, "learnset": learnset}

    def wild(self) -> dict[str, list[dict]]:
        """table -> [{map: [group, number], rates, slots: [[level, species, form], ...]}]; grass rows
        carry 21 slots (morn, day, nite x 7), water rows 3."""
        out = {}
        for table in WILD_TABLES:
            cur, rows = self._at(self.o[f"{table}WildMonsOffset"], f"{table}WildMons"), []
            grass = table.endswith("Grass")
            while cur.rom[cur.position] != 0xFF:
                if len(rows) > _MAX_ROWS:
                    raise RomScanError(f"{table}WildMons has no terminator")
                head = cur.take(2)
                rates = list(cur.take(3 if grass else 1))
                slots = [[s[0], *_dp(s[1], s[2])] for s in (cur.take(3) for _ in range(3 * GRASS_SLOTS if grass else 3))]
                rows.append({"map": list(head), "rates": rates, "slots": slots})
            out[table] = rows
        return out

    def _chance_list(self, cur: _Cursor, *, inclusive: bool) -> list[list[int]]:
        """(chance, dp, level) rows; a fishing list ends ON its chance-$FF row, a tree list after
        a lone $FF byte."""
        rows = []
        while True:
            if len(rows) > _MAX_ROWS:
                raise RomScanError(f"{cur.label}: no terminator")
            if not inclusive and cur.rom[cur.position] == 0xFF:
                cur.take(1)
                return rows
            chance, lo, hi, level = cur.take(4)
            rows.append([chance, *_dp(lo, hi), level])
            if inclusive and chance == 0xFF:
                return rows

    def fishing(self) -> list[dict]:
        table, out = self.o["FishingWildsOffset"], []
        for g in range(FISH_GROUPS):
            row = self._at(table + g * 8, f"FishGroups {g}")
            chances = list(row.take(2))
            rods = [self._chance_list(self._pointer(table, row.word(), f"fish group {g} rod {r}"), inclusive=True)
                    for r in range(3)]
            out.append({"chances": chances, "rods": rods})
        return out

    def trees(self) -> list[list[list[list[int]]]]:
        table, out = self.o["TreemonWildsOffset"], []
        for s in range(TREE_SETS):
            cur = self._pointer(table, self._at(table + s * 2, "TreeMons").word(), f"TreeMons set {s}")
            out.append([self._chance_list(cur, inclusive=False) for _ in range(1 if s == TREE_SETS - 1 else 2)])
        return out

    def contest(self) -> list[list[int]]:
        cur = self._at(self.o["BCCWildsOffset"], "ContestMons")
        return [[r[0], *_dp(r[1], r[2]), r[3], r[4]] for r in (cur.take(5) for _ in range(CONTEST_MONS))]

    def rule_tables(self) -> dict:
        """What the Soul Link rules read, per record 1..337: base data and EvosAttacks."""
        return {"base_stats": [self.base_stats(i) for i in range(1, self.records + 1)],
                "evos_attacks": [self.evos_attacks(i) for i in range(1, self.records + 1)]}

    def scan_all(self) -> dict:
        return {**self.rule_tables(), "wild": self.wild(), "fishing": self.fishing(), "trees": self.trees(),
                "contest": self.contest()}
