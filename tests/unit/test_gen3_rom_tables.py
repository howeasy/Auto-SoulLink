"""FRLG-R2a: pinned pret SOURCE versus cartridge bytes, plus ROM-free falsifiers.

The expected parties, wild slots and evolutions are parsed from the pinned pret
clone, independently of the decoder and generated server data. Missing local
ROMs/source skip by name; present-but-wrong hashes/commits fail.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path

import pytest

from server.adapters.gen3_rom_tables import (
    ROM_BASE,
    decode_evolutions,
    decode_rom_tables,
    decode_trainers,
    decode_wild_encounters,
    table_symbols,
)
from tests.unit import gen3_pret
from tools.gen3_final_cut import STAGED, rom_pins

ROOT = Path(__file__).resolve().parents[2]


def _party_mon(flags, species, level, item=0, moves=(0, 0, 0, 0)):
    # Deliberately nonzero alignment/padding and IV bytes catch wrong offsets.
    raw = bytearray(b"\xA5" * (16 if flags & 1 else 8))
    struct.pack_into("<H", raw, 0, 200)
    raw[2] = level
    struct.pack_into("<H", raw, 4, species)
    if flags & 2:
        struct.pack_into("<H", raw, 6, item)
    if flags & 1:
        struct.pack_into("<4H", raw, 8 if flags & 2 else 6, *moves)
    return raw


def _trainer_rom(flags=0):
    rom = bytearray(0x400)
    rom[0x40] = flags
    rom[0x41] = 84
    rom[0x44:0x50] = b"\xBC\xCC\xC9\xBD\xC5\xFF" + bytes(6)  # BROCK, FR charmap
    rom[0x60] = 2
    struct.pack_into("<I", rom, 0x64, ROM_BASE + 0x100)
    expected = []
    position = 0x100
    for species, level, item, moves in (
        (0x123, 12, 0x145, (0x156, 2, 3, 0)),
        (0x134, 14, 0x167, (4, 5, 6, 0x178)),
    ):
        raw = _party_mon(flags, species, level, item, moves)
        rom[position:position + len(raw)] = raw
        position += len(raw)
        mon = {"species": species, "level": level}
        if flags & 1:
            mon["moves"] = list(moves)
            if flags & 2:
                mon["held_item"] = item
        expected.append(mon)
    return rom, {0: {"class": 84, "name": "BROCK", "party": expected}}


@pytest.mark.parametrize("flags", range(4), ids=(
    "NoItemDefaultMoves", "NoItemCustomMoves", "ItemDefaultMoves", "ItemCustomMoves",
))
def test_all_party_layouts_follow_a_repointed_party(flags):
    rom, expected = _trainer_rom(flags)
    assert decode_trainers(bytes(rom), ROM_BASE + 0x40, 1) == expected
    # Move the entire party, update only the pointer and destroy the old bytes.
    size = 32 if flags & 1 else 16
    rom[0x300:0x300 + size] = rom[0x100:0x100 + size]
    rom[0x100:0x100 + size] = b"\xEE" * size
    struct.pack_into("<I", rom, 0x64, ROM_BASE + 0x300)
    assert decode_trainers(bytes(rom), ROM_BASE + 0x40, 1) == expected


def test_exact_sparse_ranges_follow_a_party_in_expanded_rom_space():
    rom, expected = _trainer_rom(3)
    moved = 0x09123400
    struct.pack_into("<I", rom, 0x64, moved)
    # Adjacent chunks deliberately split the name and first party member.
    ranges = {ROM_BASE + 0x40: bytes(rom[0x40:0x45]),
              ROM_BASE + 0x45: bytes(rom[0x45:0x68]),
              moved: bytes(rom[0x100:0x103]), moved + 3: bytes(rom[0x103:0x120])}
    assert decode_trainers(ranges, ROM_BASE + 0x40, 1) == expected
    del ranges[moved + 3]
    with pytest.raises(ValueError, match="missing bytes at 0x09123403"):
        decode_trainers(ranges, ROM_BASE + 0x40, 1)


@pytest.mark.parametrize("pointer", [
    0, 0x02000000, ROM_BASE - 1, ROM_BASE + 0x3FC, ROM_BASE + 0x400,
    0x0A000000, 0xFFFFFFFF,
])
def test_bad_party_pointer_raises_with_pointer_bytes(pointer):
    rom, _ = _trainer_rom()
    struct.pack_into("<I", rom, 0x64, pointer)
    with pytest.raises(ValueError, match=rf"trainer\[0\].*{pointer:#010x}") as error:
        decode_trainers(bytes(rom), ROM_BASE + 0x40, 1)
    assert struct.pack("<I", pointer).hex() in str(error.value)


@pytest.mark.parametrize("offset,value", [(0x40, 4), (0x60, 7)])
def test_invalid_trainer_layout_fails_with_bytes(offset, value):
    rom, _ = _trainer_rom()
    rom[offset] = value
    with pytest.raises(ValueError, match="invalid party flags/count; bytes="):
        decode_trainers(bytes(rom), ROM_BASE + 0x40, 1)


def test_empty_trainer_has_no_null_pointer_dereference():
    assert decode_trainers(bytes(40), ROM_BASE, 1)[0]["party"] == []


def _wild_rom():
    rom = bytearray(0x400)
    rom[0x40:0x42] = bytes((3, 19))
    habitats = {}
    for index, (kind, count) in enumerate((
        ("land", 12), ("water", 5), ("rock_smash", 5), ("fishing", 10),
    )):
        info, slots = 0x80 + index * 8, 0x100 + index * 0x40
        struct.pack_into("<I", rom, 0x44 + index * 4, ROM_BASE + info)
        rom[info] = 21 + index
        struct.pack_into("<I", rom, info + 4, ROM_BASE + slots)
        mons = []
        for slot in range(count):
            struct.pack_into("<BBH", rom, slots + slot * 4, 2 + slot, 4 + slot, 0x100 + slot)
            mons.append({"min_level": 2 + slot, "max_level": 4 + slot, "species": 0x100 + slot})
        habitats[kind] = {"rate": 21 + index, "mons": mons}
    # A second header for the same map must survive, in ROM order.
    rom[0x54:0x56] = bytes((3, 19))
    struct.pack_into("<I", rom, 0x58, ROM_BASE + 0xA0)
    rom[0xA0] = 9
    struct.pack_into("<I", rom, 0xA4, ROM_BASE + 0x240)
    for slot in range(12):
        struct.pack_into("<BBH", rom, 0x240 + slot * 4, 8, 10, 0x124)
    alternative = dict.fromkeys(habitats)
    alternative["land"] = {"rate": 9, "mons": [
        {"min_level": 8, "max_level": 10, "species": 0x124} for _ in range(12)
    ]}
    rom[0x68:0x6A] = b"\xFF\xFF"
    return rom, {(3, 19): [habitats, alternative]}


def test_all_wild_habitats_follow_both_pointers_and_keep_map_variants():
    rom, expected = _wild_rom()
    assert decode_wild_encounters(bytes(rom), ROM_BASE + 0x40, 3) == expected
    # Repoint both the info and slots, then poison their previous locations.
    rom[0x300:0x330] = rom[0x100:0x130]
    rom[0x380:0x388] = rom[0x80:0x88]
    struct.pack_into("<I", rom, 0x384, ROM_BASE + 0x300)
    struct.pack_into("<I", rom, 0x44, ROM_BASE + 0x380)
    rom[0x100:0x130] = b"\xEE" * 48
    rom[0x80:0x88] = b"\xEE" * 8
    assert decode_wild_encounters(bytes(rom), ROM_BASE + 0x40, 3) == expected


@pytest.mark.parametrize("offset", (0x44, 0x84), ids=("info", "slots"))
@pytest.mark.parametrize("pointer", (0x02000000, ROM_BASE + 0x3FC, 0x0A000000))
def test_bad_wild_pointer_raises(offset, pointer):
    rom, _ = _wild_rom()
    struct.pack_into("<I", rom, offset, pointer)
    with pytest.raises(ValueError, match="out-of-range ROM pointer"):
        decode_wild_encounters(bytes(rom), ROM_BASE + 0x40, 3)


def test_missing_wild_sentinel_fails_instead_of_returning_partial_data():
    rom, _ = _wild_rom()
    with pytest.raises(ValueError, match="no 0xFF map-group sentinel"):
        decode_wild_encounters(bytes(rom), ROM_BASE + 0x40, 2)


def test_evolution_stride_padding_and_noncontiguous_slots():
    rom = bytearray(0x100)
    struct.pack_into("<HHHH", rom, 0x40 + 40, 4, 16, 2, 0xEEEE)
    struct.pack_into("<HHHH", rom, 0x40 + 40 + 4 * 8, 7, 0x123, 0x134, 0xDDDD)
    assert decode_evolutions(bytes(rom), ROM_BASE + 0x40, 3) == {
        0: [], 1: [(4, 16, 2), (7, 0x123, 0x134)], 2: [],
    }


@pytest.mark.parametrize("decoder", (decode_trainers, decode_wild_encounters, decode_evolutions))
def test_truncated_or_invalid_table_head_raises(decoder):
    for pointer in (0x02000000, ROM_BASE + 1, 0x0A000000):
        with pytest.raises(ValueError, match="out-of-range ROM pointer"):
            decoder(bytes(8), pointer, 1)


def test_overlapping_ranges_are_ambiguous_and_rejected():
    with pytest.raises(ValueError, match="overlapping ROM ranges"):
        decode_trainers({ROM_BASE: bytes(40), ROM_BASE + 8: bytes(8)}, ROM_BASE, 1)


def test_only_frlg_titles_are_accepted():
    with pytest.raises(ValueError, match="unsupported FR/LG title"):
        decode_rom_tables(b"", "emerald")


@pytest.fixture(scope="module")
def pret():
    return gen3_pret.require(gen3_pret.find())


@pytest.fixture(scope="module")
def constants(pret):
    result, aliases = {}, {}
    for header in ("species", "moves", "items", "pokemon", "opponents", "trainers"):
        text = (pret / f"include/constants/{header}.h").read_text(encoding="utf-8")
        for name, token in re.findall(r"^#define\s+(\w+)\s+(\w+)\s*(?://.*)?$", text, re.M):
            if re.fullmatch(r"0x[0-9a-fA-F]+|\d+", token):
                result[name] = int(token, 0)
            else:
                aliases[name] = token
    while resolved := {name: result[token] for name, token in aliases.items() if token in result}:
        result.update(resolved)
        for name in resolved:
            del aliases[name]
    return result


def _number(token, constants):
    return int(token, 0) if re.fullmatch(r"0x[0-9a-fA-F]+|\d+", token) else constants[token]


def _body(text, pattern):
    """Read a balanced C initializer; pattern consumes its opening brace."""
    match = re.search(pattern, text)
    assert match, pattern
    depth = 1
    for end in range(match.end(), len(text)):
        depth += (text[end] == "{") - (text[end] == "}")
        if depth == 0:
            return text[match.end():end]
    pytest.fail(f"unterminated pret initializer: {pattern}")


@pytest.fixture(scope="module", params=("firered", "leafgreen"))
def clean(request):
    title = request.param
    # test_gen3_profile.py's staged paths; ancestor fallback serves bare worktrees.
    candidates = [base / STAGED[title] for base in (ROOT, *ROOT.parents)]
    path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    if not path.exists():
        pytest.skip(f"pinned clean {title} ROM absent: {path}")
    rom = path.read_bytes()
    digest = hashlib.sha1(rom).hexdigest()
    expected = rom_pins(str(ROOT))[title]
    assert digest == expected, f"{path} present but wrong {title} SHA-1: {digest} != {expected}"
    return title, rom, decode_rom_tables(rom, title)


@pytest.mark.parametrize("trainer", (
    "TRAINER_LEADER_BROCK", "TRAINER_YOUNGSTER_BEN", "TRAINER_CAMPER_LIAM",
    "TRAINER_BLACK_BELT_KOICHI", "TRAINER_ELITE_FOUR_LORELEI",
))
def test_clean_trainer_parties_and_names_match_pret_source(clean, pret, constants, trainer):
    _, _, decoded = clean
    text = (pret / "src/data/trainers.h").read_text(encoding="utf-8")
    row = _body(text, rf"\[{trainer}\]\s*=\s*\{{")
    party_ref = re.search(r"\.party\s*=\s*(\w+)\((sParty_\w+)\)", row)
    assert party_ref, trainer
    kind, name = party_ref.groups()
    party_text = (pret / "src/data/trainer_parties.h").read_text(encoding="utf-8")
    party_body = _body(party_text, rf"\b{name}\[\]\s*=\s*\{{")
    expected_party = []
    for member in re.findall(r"\{\s*\.iv\s*=[^,]+,(.*?)\n\s*\},", party_body, re.S):
        fields = dict(re.findall(r"\.(\w+)\s*=\s*(\w+)\s*,", member))
        mon = {"species": constants[fields["species"]], "level": int(fields["lvl"])}
        if kind.endswith("CUSTOM_MOVES"):
            move_names = re.search(r"\.moves\s*=\s*\{([^}]+)\}", member)[1]
            mon["moves"] = [constants[token.strip()] for token in move_names.split(",")]
            if kind == "ITEM_CUSTOM_MOVES":
                mon["held_item"] = constants[fields["heldItem"]]
        expected_party.append(mon)
    assert expected_party, name
    expected = {
        "class": constants[re.search(r"\.trainerClass\s*=\s*(\w+)", row)[1]],
        "name": re.search(r'\.trainerName\s*=\s*_\("([^"]*)"\)', row)[1],
        "party": expected_party,
    }
    assert decoded["trainers"][constants[trainer]] == expected


@pytest.fixture(scope="module")
def map_ids(pret):
    groups = json.loads((pret / "data/maps/map_groups.json").read_text(encoding="utf-8"))
    result = {}
    for group, name in enumerate(groups["group_order"]):
        for num, map_name in enumerate(groups[name]):
            row = json.loads((pret / f"data/maps/{map_name}/map.json").read_text(encoding="utf-8"))
            result[row["id"]] = (group, num)
    return result


def test_clean_route1_and_all_wild_headers_match_pret_source(clean, pret, constants, map_ids):
    title, _, decoded = clean
    source = json.loads((pret / "src/data/wild_encounters.json").read_text(encoding="utf-8"))
    group = next(g for g in source["wild_encounter_groups"] if g["label"] == "gWildMonHeaders")
    suffix = "_FireRed" if title == "firered" else "_LeafGreen"
    expected = {}
    for row in group["encounters"]:
        if not row["base_label"].endswith(suffix):
            continue
        habitats = {}
        for kind in ("land", "water", "rock_smash", "fishing"):
            raw = row.get(f"{kind}_mons")
            habitats[kind] = None if raw is None else {
                "rate": raw["encounter_rate"], "mons": [
                    {**mon, "species": constants[mon["species"]]} for mon in raw["mons"]
                ],
            }
        expected.setdefault(map_ids[row["map"]], []).append(habitats)
    route1 = map_ids["MAP_ROUTE1"]
    assert expected[route1][0]["land"]["mons"], "Route 1 source oracle is empty"
    assert decoded["wild_encounters"][route1][0]["land"] == expected[route1][0]["land"]
    assert decoded["wild_encounters"] == expected
    assert sum(map(len, expected.values())) == table_symbols(title)["gWildMonHeaders"]["count"] - 1
    assert len(expected[map_ids["MAP_SIX_ISLAND_ALTERING_CAVE"]]) == 9


def test_clean_bulbasaur_and_all_evolutions_match_pret_source(clean, pret, constants):
    _, _, decoded = clean
    source = (pret / "src/data/pokemon/evolution.h").read_text(encoding="utf-8")
    expected = {i: [] for i in range(constants["NUM_SPECIES"])}
    for species in re.findall(r"\[(SPECIES_\w+)\]\s*=", source):
        body = _body(source, rf"\[{species}\]\s*=\s*\{{")
        entries = re.findall(r"\{\s*(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*\}", body)
        assert entries, species
        expected[constants[species]] = [tuple(_number(v, constants) for v in row) for row in entries]
    assert expected[constants["SPECIES_BULBASAUR"]] == [
        (constants["EVO_LEVEL"], 16, constants["SPECIES_IVYSAUR"])
    ]
    assert decoded["evolutions"] == expected


def test_clean_table_counts_symbol_provenance_and_name_bytes(clean, constants):
    title, rom, decoded = clean
    symbols = table_symbols(title)
    provenance = json.loads((ROOT / "data/gen3/pret/provenance.json").read_text(encoding="utf-8"))
    name = f"poke{title}.sym"
    assert provenance["source"]["commit"] == gen3_pret.PIN
    assert hashlib.sha256((ROOT / "data/gen3/pret" / name).read_bytes()).hexdigest() == provenance["files"][name]
    assert len(decoded["trainers"]) == symbols["gTrainers"]["count"] == constants["NUM_TRAINERS"]
    assert len(decoded["evolutions"]) == symbols["gEvolutionTable"]["count"] == constants["NUM_SPECIES"]
    assert constants["EVOS_PER_MON"] == 5
    start = symbols["gTrainers"]["address"] - ROM_BASE
    unknown = [(tid, row["name"], rom[start + tid * 40 + 4:start + tid * 40 + 16].hex())
               for tid, row in decoded["trainers"].items() if "<$" in row["name"]]
    assert not unknown, f"undecoded trainer names (id, text, raw bytes): {unknown}"
