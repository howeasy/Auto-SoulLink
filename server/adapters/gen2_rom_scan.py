"""Independent, read-only Gen 2 ROM table decoder; no runtime admission or writes.

SOURCE pins: pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651 and
pokegold@656583c939d30f920a316177311a502dd222b57c. Formats are derived from
constants/pokemon_data_constants.asm:1-32,179-199, data/wild/*.asm,
engine/events/fish.asm, engine/events/treemons.asm and engine/overworld/wildmons.asm.
No Lua decoder or generated encounter table supplies this implementation's oracle.

Input is ROM bytes and a selected-title profile with title, rom_sha1, rom symbol
facts {bank, addr, flat}, ram bus addresses, and derived source constants. Every
location comes from that profile. A missing fact or unsupported layout refuses;
an empty table is returned only after reading its explicit terminator.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping

SCHEMA = "gen2-rom-tables-v1"
OPEN_OBLIGATIONS = (
    "fishing_map_association", "contest_encounters", "runtime_encounter_selection",
)
TIMES = ("morning", "day", "night")


class RomScanError(ValueError):
    """The supplied ROM/profile cannot establish the requested table facts."""


def _integer(value, label: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise RomScanError(f"{label}: expected integer {low}..{high}")
    return value


def _object(value, label: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise RomScanError(f"{label}: missing or invalid object")
    return value


def rom_offset(bank: int, address: int) -> int:
    """Strict ROM0/ROMX bus-to-file conversion, independent of the Lua reader."""
    _integer(bank, "ROM bank", 0, 0x1ff)
    _integer(address, "ROM address", 0 if bank == 0 else 0x4000,
             0x3fff if bank == 0 else 0x7fff)
    return address if bank == 0 else bank * 0x4000 + address - 0x4000


class _Cursor:
    def __init__(self, rom: bytes, offset: int, label: str):
        if not 0 <= offset < len(rom):
            raise RomScanError(f"{label}: address outside ROM")
        self.rom, self.position, self.label = rom, offset, label
        self.end = min(len(rom), (offset // 0x4000 + 1) * 0x4000)

    def take(self, size: int) -> bytes:
        if size < 0 or self.position + size > self.end:
            raise RomScanError(f"{self.label}: truncated record or missing bank-local terminator")
        result = self.rom[self.position:self.position + size]
        self.position += size
        return result

    def byte(self) -> int:
        return self.take(1)[0]

    def word(self) -> int:
        return int.from_bytes(self.take(2), "little")


class Rom:
    """Read one explicitly identified title; profile hash matching is mandatory unless
    ``pinned=False``. That mode exists ONLY for the randomizer pipeline's content check
    (server/upr_pipeline.py `_check_content_gen2`), which reads the companion overlay and UPR's
    output of it: neither is the profile's clean build, but both keep its table addresses
    (BaseData and EvosAttacksPointers sit at the same bank:addr in the clean and SLink maps)."""

    def __init__(self, rom: bytes, profile: Mapping, *, pinned: bool = True):
        self.profile = _object(profile, "profile")
        self.title = profile.get("title")
        if self.title not in ("crystal", "gold", "silver"):
            raise RomScanError("unsupported selected title")
        if not isinstance(rom, bytes) or not rom:
            raise RomScanError("ROM must be nonempty bytes")
        expected = profile.get("rom_sha1")
        if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{40}", expected) is None:
            raise RomScanError("profile rom_sha1 is missing or malformed")
        if pinned and hashlib.sha1(rom).hexdigest() != expected:
            raise RomScanError("ROM SHA1 differs from selected profile")
        self.rom = rom
        self.symbols = _object(profile.get("rom"), "profile.rom")
        self.constants = _object(profile.get("constants"), "profile.constants")
        self._constant("NUM_POKEMON", 251)

    def _constant(self, name: str, expected: int | None = None) -> int:
        value = _integer(self.constants.get(name), f"constants.{name}", 0, 65535)
        if expected is not None and value != expected:
            raise RomScanError(f"unsupported {name}: {value}, expected {expected}")
        return value

    def _location(self, name: str) -> tuple[int, int]:
        symbol = _object(self.symbols.get(name), f"ROM symbol {name}")
        bank, address = symbol.get("bank"), symbol.get("addr")
        offset = rom_offset(bank, address)
        if "flat" in symbol and symbol["flat"] != offset:
            raise RomScanError(f"{name}: contradictory flat offset")
        return bank, offset

    def _cursor(self, name: str) -> _Cursor:
        return _Cursor(self.rom, self._location(name)[1], name)

    def _pointer(self, bank: int, address: int, label: str) -> _Cursor:
        return _Cursor(self.rom, rom_offset(bank, address), label)

    def _slot(self, species: int, level: int) -> dict:
        _integer(species, "species", 1, 251)
        _integer(level, "level", 1, 100)
        return {"species": species, "level": level}

    @staticmethod
    def _map(group: int, number: int) -> dict:
        _integer(group, "map group", 1, 254)
        _integer(number, "map number", 1, 255)
        return {"map_group": group, "map_number": number}

    def base_stats(self, species: int) -> dict:
        """BaseData ordinal records, including distinct Special base bytes."""
        _integer(species, "species", 1, 251)
        stride = self._constant("BASE_DATA_SIZE", 32)
        tm_start = self._constant("BASE_TMHM", 24)
        cursor = self._cursor("BaseData")
        cursor.take((species - 1) * stride)
        data = cursor.take(stride)
        if data[0] != species:
            raise RomScanError("BaseData species ordinal mismatch")
        keys = ("species", "hp", "attack", "defense", "speed", "special_attack",
                "special_defense", "type1", "type2", "catch_rate", "base_exp",
                "item1", "item2", "gender_ratio")
        result = dict(zip(keys, data[:14], strict=True))
        result.update(hatch_cycles=data[15], growth_rate=data[22],
                      egg_group1=data[23] >> 4, egg_group2=data[23] & 15,
                      tmhm_bytes=list(data[tm_start:]))
        return result

    def evos_attacks(self, species: int) -> dict:
        """One EvosAttacks record: evolutions [kind, *params, species] up to the 0 terminator,
        then the level-up learnset [level, move] up to its 0 (C/G data/pokemon/evos_attacks.asm;
        EVOLVE_LEVEL..EVOLVE_STAT = 1..5 in constants/pokemon_data_constants.asm, EVOLVE_STAT
        carrying a third parameter). Records are compared logically: UPR repacks and repoints
        the whole bank on every save."""
        _integer(species, "species", 1, 251)
        bank, _ = self._location("EvosAttacksPointers")
        pointers = self._cursor("EvosAttacksPointers")
        pointers.take((species - 1) * 2)
        cursor = self._pointer(bank, pointers.word(), f"EvosAttacks {species}")
        evolutions, learnset = [], []
        while kind := cursor.byte():
            if not 1 <= kind <= 5:
                raise RomScanError(f"EvosAttacks {species}: unknown evolution kind {kind}")
            evolutions.append([kind, *cursor.take(3 if kind == 5 else 2)])
        while level := cursor.byte():
            learnset.append([level, cursor.byte()])
        return {"evolutions": evolutions, "learnset": learnset}

    def _probabilities(self, name: str, count: int) -> list[dict]:
        cursor, previous, seen, rows = self._cursor(name), 0, set(), []
        for _ in range(count):
            threshold, offset = cursor.take(2)
            if not previous < threshold <= 100 or offset % 2 or offset >= count * 2 or offset in seen:
                raise RomScanError(f"{name}: malformed probability table")
            rows.append({"threshold": threshold, "slot_offset": offset})
            previous = threshold
            seen.add(offset)
        if previous != 100:
            raise RomScanError(f"{name}: probability table does not cover 100")
        return rows

    def _wild_table(self, name: str, grass: bool) -> list[dict]:
        count = self._constant("NUM_GRASSMON" if grass else "NUM_WATERMON", 7 if grass else 3)
        stride = self._constant("GRASS_WILDDATA_LENGTH" if grass else "WATER_WILDDATA_LENGTH",
                                47 if grass else 9)
        cursor, rows, seen = self._cursor(name), [], set()
        while True:
            group = cursor.byte()
            if group == 255:
                return rows
            data = bytes([group]) + cursor.take(stride - 1)
            identity = self._map(data[0], data[1])
            key = (data[0], data[1])
            if key in seen:
                raise RomScanError(f"{name}: duplicate map row")
            seen.add(key)
            for time_index, time in enumerate(TIMES if grass else ("all",)):
                start = (5 if grass else 3) + time_index * count * 2
                slots = [self._slot(data[i + 1], data[i])
                         for i in range(start, start + count * 2, 2)]
                rows.append({"table": name, **identity, "time": time,
                             "rate": data[2 + time_index], "slots": slots})

    def wild(self) -> dict:
        return {
            "grass": [row for region in ("Johto", "Kanto", "Swarm")
                      for row in self._wild_table(f"{region}GrassWildMons", True)],
            "water": [row for region in ("Johto", "Kanto", "Swarm")
                      for row in self._wild_table(f"{region}WaterWildMons", False)],
            "grass_probabilities": self._probabilities("GrassMonProbTable", 7),
            "water_probabilities": self._probabilities("WaterMonProbTable", 3),
        }

    def _tree_maps(self, name: str, count: int) -> list[dict]:
        cursor, rows, seen = self._cursor(name), [], set()
        while True:
            group = cursor.byte()
            if group == 255:
                return rows
            number, set_id = cursor.take(2)
            identity = self._map(group, number)
            if (group, number) in seen or set_id >= count:
                raise RomScanError(f"{name}: duplicate map or invalid tree set")
            seen.add((group, number))
            rows.append({**identity, "set_id": set_id})

    def _tree_slots(self, cursor: _Cursor) -> list[dict]:
        slots, total = [], 0
        while True:
            weight = cursor.byte()
            if weight == 255:
                if total != 100:
                    raise RomScanError("tree slot weights must total 100")
                return slots
            species, level = cursor.take(2)
            if weight == 0 or total + weight > 100:
                raise RomScanError("invalid tree slot weight")
            total += weight
            slots.append({"weight": weight, **self._slot(species, level)})

    def tree(self) -> dict:
        count = self._constant("NUM_TREEMON_SETS", 8 if self.title == "crystal" else 6)
        rock = self._constant("TREEMON_SET_ROCK", 7 if self.title == "crystal" else 3)
        # Generated profile fact (tools/gen_gen2_profile.py): GetTreeMons refuses set 0
        # and every set >= limit (C engine/events/treemons.asm:100-105, G :98-102).
        limit = self._constant("TREEMON_ENABLED_LIMIT")
        if not rock < limit <= count:
            raise RomScanError("TREEMON_ENABLED_LIMIT outside the decodable tree sets")
        bank, _ = self._location("TreeMons")
        pointers = self._cursor("TreeMons")
        addresses = [pointers.word() for _ in range(count)]
        sets = []
        for set_id in range(1, limit):  # Disabled sets are not decoded, even when pointers alias data.
            cursor = self._pointer(bank, addresses[set_id], f"tree set {set_id}")
            common = self._tree_slots(cursor)
            rare = [] if set_id == rock else self._tree_slots(cursor)
            sets.append({"set_id": set_id, "kind": "rock_smash" if set_id == rock else "headbutt",
                         "common": common, "rare": rare})
        return {"headbutt_maps": self._tree_maps("TreeMonMaps", count),
                "rock_smash_maps": self._tree_maps("RockMonMaps", count), "sets": sets,
                "enabled_set_limit": limit}

    def _fish_slots(self, cursor: _Cursor, time_count: int) -> list[dict]:
        rows, previous = [], -1
        while True:
            threshold, species, level = cursor.take(3)
            if threshold <= previous:
                raise RomScanError("fishing thresholds must strictly increase")
            if species == 0:
                _integer(level, "fishing time-group index", 0, time_count - 1)
                slot = {"species": 0, "level": level}
            else:
                slot = self._slot(species, level)
            rows.append({"threshold": threshold, **slot})
            if threshold == 255:
                return rows
            previous = threshold

    def fishing(self) -> dict:
        count = self._constant("NUM_FISHGROUPS", 13)
        self._constant("FISHGROUP_DATA_LENGTH", 7)
        time_count = self._constant("NUM_TIME_FISHGROUPS", 22)
        bank, _ = self._location("FishGroups")
        cursor, groups = self._cursor("FishGroups"), []
        for group_id in range(1, count + 1):
            row = {"group_id": group_id, "bite_threshold": cursor.byte()}
            for rod in ("old", "good", "super"):
                slots = self._pointer(bank, cursor.word(), f"fish group {group_id}/{rod}")
                row[rod] = self._fish_slots(slots, time_count)
            groups.append(row)
        cursor, timed = self._cursor("TimeFishGroups"), []
        for group_id in range(time_count):
            species, level, night_species, night_level = cursor.take(4)
            timed.append({"group_id": group_id, "day": self._slot(species, level),
                          "night": self._slot(night_species, night_level)})
        return {"groups": groups, "time_groups": timed}

    def _roamer_initial(self) -> list[dict]:
        # Exact instruction form: C wildmons.asm:493-524; G:488-529.
        cursor, ram = self._cursor("InitRoamMons"), _object(self.profile.get("ram"), "profile.ram")
        count = 2 if self.title == "crystal" else 3

        def immediate() -> int:
            if cursor.byte() != 0x3e:  # ld a, immediate
                raise RomScanError("unsupported InitRoamMons immediate instruction")
            return cursor.byte()

        def store(index: int, field: str) -> None:
            expected = _integer(ram.get(f"wRoamMon{index}{field}"), "roamer RAM symbol", 0xc000, 0xdfff)
            if cursor.byte() != 0xea or cursor.word() != expected:  # ld [absolute], a
                raise RomScanError("unsupported InitRoamMons store instruction")

        rows = []
        for index in range(1, count + 1):
            species = immediate()
            store(index, "Species")
            rows.append({"species": species})
        level = immediate()
        for index, row in enumerate(rows, 1):
            store(index, "Level")
            row.update(self._slot(row["species"], level))
        for index, row in enumerate(rows, 1):
            group = immediate()
            store(index, "MapGroup")
            number = immediate()
            store(index, "MapNumber")
            row.update(self._map(group, number))
        if cursor.byte() != 0xaf:  # xor a; remaining HP stores initialize later stat generation.
            raise RomScanError("unsupported InitRoamMons HP initialization")
        for index in range(1, count + 1):
            store(index, "HP")
        if cursor.byte() != 0xc9:
            raise RomScanError("unsupported InitRoamMons return")
        return rows

    def roamers(self) -> dict:
        expected_count = self._constant("NUM_ROAMMON_MAPS", 16)
        cursor, rows, seen = self._cursor("RoamMaps"), [], set()
        while True:
            group = cursor.byte()
            if group == 255:
                break
            number, count = cursor.take(2)
            identity = self._map(group, number)
            if (group, number) in seen or count == 0:
                raise RomScanError("duplicate roam map or empty destination list")
            seen.add((group, number))
            destinations = [self._map(*cursor.take(2)) for _ in range(count)]
            if cursor.byte() != 0:
                raise RomScanError("missing roam-map record terminator")
            rows.append({**identity, "destinations": destinations})
        if len(rows) != expected_count:
            raise RomScanError("unexpected RoamMaps record count")
        for row in rows:
            if any((d["map_group"], d["map_number"]) not in seen for d in row["destinations"]):
                raise RomScanError("roamer destination is not a roaming map")
        return {"initial": self._roamer_initial(), "maps": rows}

    def scan_all(self) -> dict:
        return {"schema": SCHEMA, "title": self.title,
                "base_stats": [self.base_stats(species) for species in range(1, 252)],
                "wild": self.wild(), "tree": self.tree(), "fishing": self.fishing(),
                "roamers": self.roamers(), "open_obligations": list(OPEN_OBLIGATIONS)}


def scan_all(rom: bytes, profile: Mapping) -> dict:
    return Rom(rom, profile).scan_all()
