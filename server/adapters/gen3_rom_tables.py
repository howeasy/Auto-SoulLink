"""Decode English revision-0 FR/LG/Emerald cartridge tables, including repointed data.

``decode_rom_tables(rom, "firered" | "leafgreen" | "emerald")`` obtains table heads and sizes
by symbol name from data/gen3/pret/poke<title>.sym. No party or encounter-data
address is taken from a clean-ROM symbol: every child pointer is read from ROM.
The lower-level decoders take an explicit head and count for extracted tables.

Input is either full ROM ``bytes`` (file offset zero is GBA address 0x08000000),
or ``{GBA_address: bytes}`` containing the exact, nonoverlapping ROM ranges the
client supplied. Adjacent ranges may split a record; missing bytes fail closed.
Pointers must be in 0x08000000..0x09FFFFFF and backed by supplied bytes.

Output uses cartridge IDs, without National Dex conversion or learned moves:
* trainers: {trainer_id: {"class": int, "name": str, "party": [mon, ...]}}.
  All mons contain species/level. Custom-move mons additionally contain four
  moves; both item layouts contain held_item (FRLG-R2c, owner ruling 31).
* wild_encounters: {(map_group, map_num): [habitats, ...]}, where habitats maps
  land/water/rock_smash/fishing to None or {"rate": int, "mons": [mon, ...]}.
  Each wild mon has min_level/max_level/species. Multiple headers for one map
  stay in ROM order: Altering Cave has nine alternatives; selecting the active
  one needs VAR_ALTERING_CAVE_WILD_SET (src/wild_encounter.c:175-201).
* evolutions: {species: [(method, param, target), ...]}, including empty lists
  for species without evolutions and the species-zero row.

Layout authority: pret/pokefirered@c75f352304d529f6ba92d4f74b9cf8b5c3810788,
include/battle.h:71-128, include/wild_encounter.h:6-34,
include/pokemon.h:266-271, include/constants/pokemon.h:282. The matching agbcc
build pads the 6-byte Evolution and NoItemDefaultMoves structs to 8 bytes and
the 14-byte NoItemCustomMoves struct to 16. The pinned .sym sizes and the clean
ROM controls in test_gen3_rom_tables.py verify these strides independently.
This is a decoder, not ROM admission or validation of a randomizer's patches.
Emerald c65e93f2 uses the same fields/strides (include/data.h, include/pokemon.h);
test_gen3_emerald_rand.py verifies all 854 nonempty trainer parties against their ROM spans.
"""

from __future__ import annotations

import hashlib
import json
import struct
from bisect import bisect_right
from collections.abc import Mapping
from functools import cache
from pathlib import Path

from .gen3_codec import decode_name

ROM_BASE = 0x08000000
ROM_LIMIT = 0x0A000000
TRAINER_SIZE = 40
WILD_HEADER_SIZE = 20
EVOLUTION_SIZE = 8
EVOS_PER_MON = 5
PARTY_SIZES = (8, 16, 8, 16)  # flags: custom moves=1, held item=2
WILD_COUNTS = {"land": 12, "water": 5, "rock_smash": 5, "fishing": 10}
SPECIES_INFO_SIZE = 28
TABLE_STRIDES = {
    "gTrainers": TRAINER_SIZE,
    "gWildMonHeaders": WILD_HEADER_SIZE,
    "gEvolutionTable": EVOLUTION_SIZE * EVOS_PER_MON,
    "gSpeciesInfo": SPECIES_INFO_SIZE,
}
SYMBOL_DIR = Path(__file__).resolve().parents[2] / "data/gen3/pret"
RomData = bytes | Mapping[int, bytes]
DEOXYS = 410
# pret pokemon.c sDeoxysBaseStats: UPR saves the title's already-used forme into its row.
DEOXYS_NORMAL = bytes((50, 150, 50, 150, 150, 50))
DEOXYS_FORME = {"firered": bytes((50, 180, 20, 150, 180, 20)),
                "leafgreen": bytes((50, 70, 160, 90, 70, 160)),
                # pokeemerald c65e93f2 src/pokemon.c:1885-1893 sDeoxysBaseStats.
                "emerald": bytes((50, 95, 90, 180, 95, 90))}

# Native species IDs whose ORIGINAL second ability is zero in BOTH SHA-1-pinned
# FR/LG gSpeciesInfo tables (pret c75f3523 src/data/pokemon/species_info.h).
# UPR may fill only these empty slots with ability 1. In particular, Vibrava's
# two LEVITATE slots are both nonzero: erasing its second slot changes the ability
# selected by pokemon.c:3791-3798 for an inherited abilityNum=1.
_SPECIES_RULES_DIR = Path(__file__).resolve().parents[2] / "data/games"
_HEX_DIGITS = "0123456789abcdef"
# Both pinned tables classify 284 originally-empty second-ability slots across their 412
# species (gen3_frlg/species_rules.json:235-520, gen3_emerald/species_rules.json:229-514).
ZERO_SECOND_ABILITY_SPECIES_COUNT = 284
# The SpeciesInfo tables hold 412 rows; an ID above this is a corrupted list, not a species.
SPECIES_ID_LIMIT = 512


def _sha256_pin(facts, keys, label):
    node = facts
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            raise ValueError(f"{label} is missing {'.'.join(keys)}")
        node = node[key]
    if (not isinstance(node, str) or len(node) != 64
            or any(c not in _HEX_DIGITS for c in node)):
        raise ValueError(f"invalid {label} {'.'.join(keys)}")


def _load_species_rule_facts(name, required, pins):
    """Load one required species_rules.json, refusing a broken installation at import.

    These are admission facts, not optional display data: a silently dropped pin or a
    truncated species list would admit a cartridge the rules never classified. FR/LG and
    Emerald pin different keys, so the CHECK is shared and the pin lists are not.
    """
    label = f"{name}/species_rules.json"
    with (_SPECIES_RULES_DIR / label).open(encoding="utf-8") as _rules_file:
        facts = json.load(_rules_file)
    if not isinstance(facts, dict):
        raise ValueError(f"invalid {label}")
    for key in required:
        if key not in facts:
            raise ValueError(f"{label} is missing {key}")
    slots = facts["zero_second_ability_species"]
    if (not isinstance(slots, list) or len(slots) != ZERO_SECOND_ABILITY_SPECIES_COUNT
            or any(not isinstance(s, int) or isinstance(s, bool)
                   or not 0 <= s < SPECIES_ID_LIMIT for s in slots)
            or any(low >= high for low, high in zip(slots, slots[1:], strict=False))):
        raise ValueError(f"invalid {label} zero_second_ability_species")
    for pin in pins:
        _sha256_pin(facts, pin, label)
    return facts


FRLG_SPECIES_RULES_FACTS = _load_species_rule_facts(
    "gen3_frlg",
    required=("bytes", "zero_second_ability_species", "titles"),
    pins=(("titles", "firered", "symbols_sha256"),
          ("titles", "firered", "species_info_sha256"),
          ("titles", "leafgreen", "symbols_sha256"),
          ("titles", "leafgreen", "species_info_sha256")))
FRLG_ZERO_SECOND_ABILITY_SPECIES = frozenset(
    FRLG_SPECIES_RULES_FACTS["zero_second_ability_species"])
SPECIES_RULE_BYTES = tuple(row["offset"] for row in FRLG_SPECIES_RULES_FACTS["bytes"] if row["projected"])


# These are required admission facts, not optional display data. Refuse a broken
# installation at import instead of leaving a None pin to look like a changed ROM.
EMERALD_SPECIES_RULES_FACTS = _load_species_rule_facts(
    "gen3_emerald",
    required=("bytes", "zero_second_ability_species",
              "normalised_species_rules_sha256", "evolutions_sha256", "clean_content_sha256"),
    pins=(("normalised_species_rules_sha256",), ("evolutions_sha256",), ("clean_content_sha256",)))


def normalised_species_rules(raw: bytes, title: str) -> bytes:
    """The shared Manager/server rule projection of gSpeciesInfo (pret SpeciesInfo).

    Preserve the classified rule fields, including gender and growth rate. Only the fork's known
    Deoxys forme write and ability-1 fill of a pinned originally-empty slot are equivalent
    to retail. Other fields (e.g. held items and catch rate) are open randomizer options.
    """
    if title not in DEOXYS_FORME:
        raise ValueError(f"unsupported Gen 3 title: {title!r}")
    if title == "emerald":
        facts = EMERALD_SPECIES_RULES_FACTS
        zero_slots = frozenset(facts["zero_second_ability_species"])
        rule_bytes = tuple(row["offset"] for row in facts["bytes"] if row["projected"])
    else:
        zero_slots, rule_bytes = FRLG_ZERO_SECOND_ABILITY_SPECIES, SPECIES_RULE_BYTES
    return _normalised_species_rule_rows(raw, zero_slots, rule_bytes, DEOXYS_FORME[title])


def _normalised_species_rule_rows(raw: bytes, zero_slots, rule_bytes, forme: bytes) -> bytes:
    """Pure projection shared with the pinned-fact generator; no file reads."""
    if not raw or len(raw) % SPECIES_INFO_SIZE:
        raise ValueError("gSpeciesInfo must contain complete 28-byte records")
    rows = []
    for species, offset in enumerate(range(0, len(raw), SPECIES_INFO_SIZE)):
        row = bytearray(raw[offset:offset + SPECIES_INFO_SIZE])
        if species == DEOXYS and bytes(row[:6]) == forme:
            row[:6] = DEOXYS_NORMAL
        if species in zero_slots and row[23] in (0, row[22]):
            row[23] = row[22]
        rows.append(bytes(row[b] for b in rule_bytes))
    return b"".join(rows)


class _Rom:
    def __init__(self, data: RomData):
        if isinstance(data, bytes):
            ranges = [(ROM_BASE, data)]
        elif isinstance(data, Mapping):
            ranges = list(data.items())
        else:
            raise TypeError("ROM must be bytes or a mapping of GBA addresses to bytes")
        for address, raw in ranges:
            if not isinstance(address, int) or not isinstance(raw, bytes):
                raise TypeError("ROM ranges must map integer GBA addresses to bytes")
            if address < ROM_BASE or address >= ROM_LIMIT or address + len(raw) > ROM_LIMIT:
                raise ValueError(f"ROM range out of bounds: {address:#010x} + {len(raw):#x}")
        self.ranges = sorted((address, raw) for address, raw in ranges if raw)
        for (address, raw), (following, _) in zip(self.ranges, self.ranges[1:], strict=False):
            if address + len(raw) > following:
                raise ValueError(f"overlapping ROM ranges at {following:#010x}")
        self.starts = [address for address, _ in self.ranges]

    def read(self, address: int, size: int, label: str) -> bytes:
        if address < ROM_BASE or address >= ROM_LIMIT or address + size > ROM_LIMIT:
            raise ValueError(f"{label}: out-of-range ROM pointer {address:#010x} + {size:#x}")
        index = bisect_right(self.starts, address) - 1
        remaining, cursor, chunks = size, address, []
        while remaining:
            if index < 0 or index >= len(self.ranges):
                break
            start, raw = self.ranges[index]
            offset = cursor - start
            if offset < 0 or offset >= len(raw):
                break
            chunk = raw[offset:offset + remaining]
            chunks.append(chunk)
            cursor += len(chunk)
            remaining -= len(chunk)
            index += 1
        if remaining:
            raise ValueError(
                f"{label}: out-of-range ROM pointer {address:#010x} + {size:#x}; "
                f"missing bytes at {cursor:#010x}"
            )
        return b"".join(chunks)


@cache
def table_symbols(title: str, *, symbol_dir: Path = SYMBOL_DIR) -> dict:
    """Read this title's table symbols and derive counts from their validated sizes.

    ``count`` includes TRAINER_NONE, species zero, and the wild-header sentinel.
    A caller with relocated table heads may use the lower-level decoders, passing
    the new address and count explicitly; this helper describes the pinned heads.
    The pinned file is immutable; callers must not mutate the cached mapping.
    """
    if title not in ("firered", "leafgreen", "emerald"):
        raise ValueError(f"unsupported Gen 3 title: {title!r}")
    result = {}
    path = Path(symbol_dir) / f"poke{title}.sym"
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if not fields or fields[-1] not in TABLE_STRIDES:
            continue
        name = fields[-1]
        if len(fields) != 4 or name in result:
            raise ValueError(f"{path}: malformed or duplicate symbol {name}: {line!r}")
        address, size = int(fields[0], 16), int(fields[2], 16)
        stride = TABLE_STRIDES[name]
        if size <= 0 or size % stride or not ROM_BASE <= address < address + size <= ROM_LIMIT:
            raise ValueError(f"{path}: invalid table span for {name}: {line!r}")
        result[name] = {"address": address, "size": size, "count": size // stride}
    if missing := TABLE_STRIDES.keys() - result.keys():
        raise ValueError(f"{path}: missing table symbols: {', '.join(sorted(missing))}")
    return result


def _count(value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"table count must be a nonnegative integer, got {value!r}")


def decode_trainers(rom: RomData, address: int, count: int) -> dict[int, dict]:
    """Decode all four party layouts; follow the pointer at Trainer + 0x24."""
    _count(count)
    reader = _Rom(rom)
    table = reader.read(address, count * TRAINER_SIZE, "gTrainers")
    trainers = {}
    for trainer_id in range(count):
        raw = table[trainer_id * TRAINER_SIZE:(trainer_id + 1) * TRAINER_SIZE]
        flags, party_count = raw[0], raw[32]
        if flags >= len(PARTY_SIZES) or party_count > 6:
            raise ValueError(f"trainer[{trainer_id}]: invalid party flags/count; bytes={raw.hex()}")
        pointer = struct.unpack_from("<I", raw, 36)[0]
        label = f"trainer[{trainer_id}].party (pointer bytes={raw[36:40].hex()})"
        stride = PARTY_SIZES[flags]
        # TRAINER_NONE has a null pointer and no party. Nonempty parties may not.
        party = reader.read(pointer, party_count * stride, label) if party_count else b""
        if pointer and not party_count:
            reader.read(pointer, 1, label)
        mons = []
        for slot in range(party_count):
            offset = slot * stride
            mon = {"species": struct.unpack_from("<H", party, offset + 4)[0],
                   "level": party[offset + 2]}
            if flags & 1:
                moves_offset = 8 if flags & 2 else 6
                mon["moves"] = list(struct.unpack_from("<4H", party, offset + moves_offset))
            if flags & 2:
                mon["held_item"] = struct.unpack_from("<H", party, offset + 6)[0]
            mons.append(mon)
        trainers[trainer_id] = {"class": raw[1], "name": decode_name(raw[4:16]), "party": mons}
    return trainers


def decode_wild_encounters(rom: RomData, address: int, header_count: int) -> dict:
    """Map IDs to ordered habitat variants; header_count includes the sentinel.

    Follow both header -> WildPokemonInfo and WildPokemonInfo -> WildPokemon
    pointers. A null habitat pointer means absent habitat, not an invalid read.
    The map-group 0xFF sentinel follows src/wild_encounter.c:182-184.
    """
    _count(header_count)
    reader = _Rom(rom)
    table = reader.read(address, header_count * WILD_HEADER_SIZE, "gWildMonHeaders")
    maps = {}
    for index in range(header_count):
        raw = table[index * WILD_HEADER_SIZE:(index + 1) * WILD_HEADER_SIZE]
        if raw[0] == 0xFF:
            return maps
        habitats = {}
        for offset, (kind, count) in zip((4, 8, 12, 16), WILD_COUNTS.items(), strict=True):
            pointer = struct.unpack_from("<I", raw, offset)[0]
            if not pointer:
                habitats[kind] = None
                continue
            label = f"wild[{index}].{kind} (pointer bytes={raw[offset:offset + 4].hex()})"
            info = reader.read(pointer, 8, label)
            slots_pointer = struct.unpack_from("<I", info, 4)[0]
            slots = reader.read(
                slots_pointer, count * 4, f"{label}.mons (pointer bytes={info[4:8].hex()})"
            )
            mons = [{"min_level": lo, "max_level": hi, "species": species}
                    for lo, hi, species in struct.iter_unpack("<BBH", slots)]
            habitats[kind] = {"rate": info[0], "mons": mons}
        maps.setdefault((raw[0], raw[1]), []).append(habitats)
    raise ValueError(f"gWildMonHeaders: no 0xFF map-group sentinel in {header_count} headers")


def decode_evolutions(rom: RomData, address: int, species_count: int) -> dict:
    """Decode the flat array of five padded Evolution records per species.

    Method zero is an unused slot. Examine every slot (do not terminate at the
    first zero), matching the game's EVOS_PER_MON loop in src/pokemon.c:5053.
    """
    _count(species_count)
    reader = _Rom(rom)
    stride = EVOLUTION_SIZE * EVOS_PER_MON
    table = reader.read(address, species_count * stride, "gEvolutionTable")
    evolutions = {}
    for species in range(species_count):
        entries = []
        for slot in range(EVOS_PER_MON):
            entry = struct.unpack_from("<HHH", table, species * stride + slot * EVOLUTION_SIZE)
            if entry[0]:
                entries.append(entry)
        evolutions[species] = entries
    return evolutions


def decode_rom_tables(rom: RomData, title: str, *, symbol_dir: Path = SYMBOL_DIR) -> dict:
    """Decode all three tables using only this title's named .sym table heads."""
    symbols = table_symbols(title, symbol_dir=symbol_dir)
    trainers = symbols["gTrainers"]
    wild = symbols["gWildMonHeaders"]
    evolutions = symbols["gEvolutionTable"]
    return {
        "trainers": decode_trainers(rom, trainers["address"], trainers["count"]),
        "wild_encounters": decode_wild_encounters(rom, wild["address"], wild["count"]),
        "evolutions": decode_evolutions(rom, evolutions["address"], evolutions["count"]),
    }


def rom_content_ranges(rom: RomData, heads: Mapping[str, tuple[int, int]]) -> list[tuple[int, int]]:
    """Exact referenced byte intervals [start, end) for the client table report.

    ``heads`` is the trusted title profile's {symbol: (address, size)} mapping,
    including the species-info and trainer-class-name heads. Shared/overlapping
    references are merged; gaps are not. Reads also prove every required byte is
    present, so a consumer can reject any supplied bytes outside these intervals.
    """
    reader = _Rom(rom)
    intervals = []

    def capture(address, size, label):
        if size <= 0:
            raise ValueError(f"{label}: empty ROM table range")
        raw = reader.read(address, size, label)
        intervals.append((address, address + size))
        return raw

    tables = {name: capture(address, size, name) for name, (address, size) in heads.items()}
    trainers = tables["gTrainers"]
    if len(trainers) % TRAINER_SIZE:
        raise ValueError("gTrainers: truncated record")
    for at in range(0, len(trainers), TRAINER_SIZE):
        flags, count = trainers[at], trainers[at + 32]
        if flags >= len(PARTY_SIZES) or count > 6:
            raise ValueError(f"trainer[{at // TRAINER_SIZE}]: invalid party flags/count")
        pointer = struct.unpack_from("<I", trainers, at + 36)[0]
        if count:
            capture(pointer, count * PARTY_SIZES[flags], "trainer party")
        elif pointer:
            capture(pointer, 1, "empty trainer party pointer")

    wild = tables["gWildMonHeaders"]
    if len(wild) % WILD_HEADER_SIZE:
        raise ValueError("gWildMonHeaders: truncated record")
    for at in range(0, len(wild), WILD_HEADER_SIZE):
        if wild[at] == 0xFF:
            break
        for index, (kind, count) in enumerate(WILD_COUNTS.items(), 1):
            pointer = struct.unpack_from("<I", wild, at + index * 4)[0]
            if pointer:
                info = capture(pointer, 8, f"wild {kind} info")
                capture(struct.unpack_from("<I", info, 4)[0], count * 4, f"wild {kind} slots")
    else:
        raise ValueError("gWildMonHeaders: missing 0xFF map-group sentinel")

    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _canon(obj):
    if isinstance(obj, dict):
        return {repr(k) if not isinstance(k, str) else k: _canon(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canon(v) for v in obj]
    return obj


def gen3_content_fingerprint(tables: dict) -> str:
    """sha256 of the decoded per-ROM tables (decode_rom_tables: trainers, wild encounters,
    evolutions). A pure function of the DECODE, so the server (Gen3Adapter.rom_content_fingerprint,
    from the byte ranges a client ships) and the Manager (server/upr_pipeline.py, from the whole
    file, rom_contract.json) reach the same value."""
    body = {k: tables[k] for k in ("trainers", "wild_encounters", "evolutions")}
    return hashlib.sha256(json.dumps(_canon(body), sort_keys=True, separators=(",", ":"))
                          .encode()).hexdigest()
