"""Independent Gen 2 byte oracle, derived from the pinned pret ASM.

SOURCE anchors (Crystal 7a7881d0, Gold/Silver 656583c9): macros/ram.asm
box_struct/party_struct/box; constants/pokemon_data_constants.asm; move_mon.asm
CalcMonStatC; experience.asm CalcExpAtLevel; engine/menus/save.asm Checksum,
TryLoadSaveData and TryLoadSaveFile. Address facts are injected from generated
profiles and verified symbols. This module imports neither Lua nor a Gen 1 codec.

MODEL only: checksum selection returns a read-only projection, not a simulated
full save repair. Mail/options/RTC tails and durable trade witnesses remain OPEN.
Names retain their exact bytes; text decoding requires an injected decoder.
Standalone records require their separately observed species-list marker: eggs
store their actual species in the record. Identity follows spec.md:149's full
DV:OT:species key; evolution is an explicit identity transition.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from math import isqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAT_NAMES = ("hp", "attack", "defense", "speed", "special_attack", "special_defense")
EXP_NAMES = ("hp", "attack", "defense", "speed", "special")
OFFSETS = {
    "MON_SPECIES": "Species", "MON_ITEM": "Item", "MON_MOVES": "Moves", "MON_OT_ID": "ID",
    "MON_EXP": "Exp", "MON_HP_EXP": "HPExp", "MON_ATK_EXP": "AtkExp", "MON_DEF_EXP": "DefExp",
    "MON_SPD_EXP": "SpdExp", "MON_SPC_EXP": "SpcExp", "MON_DVS": "DVs", "MON_PP": "PP",
    "MON_HAPPINESS": "Happiness", "MON_POKERUS": "PokerusStatus", "MON_LEVEL": "Level",
    "MON_STATUS": "Status", "MON_HP": "HP", "MON_MAXHP": "MaxHP", "MON_ATK": "Attack",
    "MON_DEF": "Defense", "MON_SPD": "Speed", "MON_SAT": "SpclAtk", "MON_SDF": "SpclDef",
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _integer(value, low, high, label):
    _require(type(value) is int and low <= value <= high, f"{label}: expected integer {low}..{high}")
    return value


def _raw(raw, length, label):
    _require(isinstance(raw, bytes) and len(raw) == length, f"{label}: expected exactly {length} bytes")
    return raw


@dataclass(frozen=True)
class SaveRegion:
    name: str
    primary: int
    backup: int
    length: int


@dataclass(frozen=True)
class Gen2Layout:
    title: str
    profile: dict
    constants: dict
    addresses: dict
    sram_banks: dict
    regions: tuple[SaveRegion, ...]
    checksum_spans: dict
    checksum_offsets: dict
    markers: dict
    storage_boxes: tuple[tuple[int, int], ...]
    active_box: tuple[int, int]
    party_size: int
    box_mon_size: int
    box_size: int
    name_size: int
    nickname_size: int

    @classmethod
    def from_profile(cls, profile, title, *, symbols=None, save_check_values=None):
        _require(title in ("crystal", "gold", "silver"), "unsupported Gen 2 title")
        _require(profile.get("schema") == "gen2-profile-v1" and set(profile.get("titles", {})) == {title},
                 "wrong/malformed selected profile")
        row = profile["titles"][title]
        constants = dict(row["constants"])
        addresses = dict(row["ram"])
        banks = dict(row["sram_bank"])
        for name, symbol in (symbols or {}).items():
            bank, address = symbol
            if name.startswith(("w", "s")):
                if name in addresses:
                    _require(addresses[name] == address, f"profile/symbol address mismatch: {name}")
                addresses[name] = address
                if name.startswith("s") and 0xA000 <= address < 0xC000:
                    if name in banks:
                        _require(banks[name] == bank, f"profile/symbol bank mismatch: {name}")
                    banks[name] = bank
        try:
            sizes = [constants[name] for name in ("PARTYMON_STRUCT_LENGTH", "BOXMON_STRUCT_LENGTH",
                                                 "BOX_LENGTH", "NAME_LENGTH", "MON_NAME_LENGTH")]
            _require(sizes == [48, 32, 1104, 11, 11], "unsupported source record lengths")
            _require(constants["PARTY_LENGTH"] == 6 and constants["MONS_PER_BOX"] == 20
                     and constants["NUM_BOXES"] == 14 and constants["EGG"] == 253 and constants["NUM_MOVES"] == 4,
                     "unsupported source collection bounds")
            for field, suffix in OFFSETS.items():
                value = constants[field]
                _require(value == addresses["wPartyMon1" + suffix] - addresses["wPartyMon1"],
                         f"profile record offset mismatch: {field}")

            def flat(name):
                bank, address = banks[name], addresses[name]
                _require(type(bank) is int and 0 <= bank < 4 and 0xA000 <= address < 0xC000,
                         f"invalid CartRAM symbol: {name}")
                return bank * 0x2000 + address - 0xA000

            def length(start, end):
                value = addresses[end] - addresses[start]
                _require(0 < value <= 0x2000, f"invalid source span: {start}/{end}")
                return value

            pairs = (("player", "PlayerData", "wPlayerData", "wPlayerDataEnd"),) if title == "crystal" else (
                ("player1", "PlayerData1", "wPlayerData1", "wPlayerData1End"),
                ("player2", "PlayerData2", "wPlayerData2", "wPlayerData2End"),
                ("player3", "PlayerData3", "wPlayerData3", "wPlayerData3End"))
            pairs += (("map", "CurMapData", "wCurMapData", "wCurMapDataEnd"),
                      ("pokemon", "PokemonData", "wPokemonData", "wPokemonDataEnd"))
            regions = tuple(SaveRegion(label, flat("s" + stem), flat("sBackup" + stem), length(start, end))
                            for label, stem, start, end in pairs)
            primary = (flat("sGameData"), flat("sGameDataEnd") - flat("sGameData"))
            _require(sum(r.length for r in regions) == primary[1]
                     and regions[0].primary == primary[0], "save regions do not cover primary data")
            for first, second in zip(regions, regions[1:], strict=False):
                _require(first.primary + first.length == second.primary, "primary source regions are not contiguous")
            if title == "crystal":
                backup = ((flat("sBackupGameData"), flat("sBackupGameDataEnd") - flat("sBackupGameData")),)
                _require(backup[0][1] == primary[1], "Crystal save copies differ in length")
            else:
                backup = tuple((region.backup, region.length) for region in regions)
            for start, size in (primary, *backup):
                _require(0 < size <= 0x2000 and 0 <= start <= 0x8000 - size
                         and start // 0x2000 == (start + size - 1) // 0x2000,
                         "checksum span exceeds its CartRAM bank")
            checks = save_check_values
            if checks is None:
                checks = (constants["SAVE_CHECK_VALUE_1"], constants["SAVE_CHECK_VALUE_2"])
            _require(len(checks) == 2, "two explicit source save check values required")
            markers = {}
            for copy_name, prefix in (("primary", "s"), ("backup", "sBackup")):
                markers[copy_name] = tuple((flat(prefix + f"CheckValue{n}"),
                                           _integer(value, 0, 255, "save check value"))
                                          for n, value in enumerate(checks, 1))
            boxes = tuple((entry["bank"] * 0x2000 + entry["addr"] - 0xA000, entry["length"])
                          for entry in row["storage_boxes"])
            _require(len(boxes) == 14 and all(size == sizes[2] and 0 <= pos <= 0x8000 - size
                                            for pos, size in boxes), "invalid storage box inventory")
            _require(all(entry["number"] == n and boxes[n - 1][0] == flat(f"sBox{n}")
                         for n, entry in enumerate(row["storage_boxes"], 1)), "storage box symbols mismatch")
            return cls(title, profile, constants, addresses, banks, regions,
                       {"primary": (primary,), "backup": backup},
                       {"primary": flat("sChecksum"), "backup": flat("sBackupChecksum")}, markers,
                       boxes, (flat("sBox"), addresses["sBoxEnd"] - addresses["sBox"]), *sizes)
        except (KeyError, TypeError) as exc:
            raise ValueError(f"required profile/symbol/source constant missing: {exc}") from exc


def for_foundation(title, *, root=ROOT):
    """Offline factory: verify the source build, then inject exact profile/symbol facts."""
    from tools.gen2_source_data import load_context

    ctx = load_context(title, root=Path(root))
    profile = json.loads((Path(root) / "data/games" / f"gen2_{title}" / "profile.json").read_text(encoding="utf-8"))
    _require(profile.get("source") == ctx.source_record(), "profile source provenance differs from verified build")
    source = ctx.read_source("constants/misc_constants.asm")
    checks = []
    for n in (1, 2):
        match = re.search(rf"^DEF SAVE_CHECK_VALUE_{n}\s+EQU\s+(\d+)\s*$", source, re.M)
        _require(match is not None, "save check constants missing from pinned source")
        checks.append(int(match[1]))
    return Gen2Layout.from_profile(profile, title, symbols=ctx.symbols, save_check_values=checks)


def decode_dvs(word):
    _integer(word, 0, 65535, "DV word")
    attack, defense, speed, special = (word >> shift & 15 for shift in (12, 8, 4, 0))
    return {"attack": attack, "defense": defense, "speed": speed, "special": special,
            "hp": (attack & 1) << 3 | (defense & 1) << 2 | (speed & 1) << 1 | (special & 1)}


def _decode(raw, layout, party, species_marker, ot, nickname, name_decoder):
    _raw(raw, layout.party_size if party else layout.box_mon_size, "Pokemon record")
    c = layout.constants

    def u8(field):
        return raw[c[field]]

    def be(field, size=2):
        return int.from_bytes(raw[c[field]:c[field] + size], "big")

    species = _integer(u8("MON_SPECIES"), 1, 251, "record species")
    _require(species_marker is not None, "explicit species_marker required; record bytes cannot determine egg status")
    marker = species_marker
    _require(type(marker) is int and marker in (species, c["EGG"]), "species-list marker contradicts record")
    word = be("MON_DVS")
    result = {
        "species_id": species, "species_marker": marker, "is_egg": marker == c["EGG"],
        "held_item": u8("MON_ITEM"), "moves": list(raw[c["MON_MOVES"]:c["MON_MOVES"] + 4]),
        "ot_id": be("MON_OT_ID"), "exp": be("MON_EXP", 3),
        "stat_exp": {name: be(field) for name, field in zip(EXP_NAMES,
                     ("MON_HP_EXP", "MON_ATK_EXP", "MON_DEF_EXP", "MON_SPD_EXP", "MON_SPC_EXP"), strict=True)},
        "dvs": decode_dvs(word), "dv_word": word,
        "pp": [value & 63 for value in raw[c["MON_PP"]:c["MON_PP"] + 4]],
        "pp_ups": [value >> 6 for value in raw[c["MON_PP"]:c["MON_PP"] + 4]],
        "happiness": u8("MON_HAPPINESS"), "pokerus": u8("MON_POKERUS"),
        "aux_bytes_hex": raw[c["MON_LEVEL"] - 2:c["MON_LEVEL"]].hex(),
        "level": _integer(u8("MON_LEVEL"), 1, 100, "record level"), "raw_hex": raw.hex(),
    }
    if party:
        result.update(status=u8("MON_STATUS"), hp=be("MON_HP"), max_hp=be("MON_MAXHP"),
                      stats={name: be(field) for name, field in zip(STAT_NAMES[1:],
                             ("MON_ATK", "MON_DEF", "MON_SPD", "MON_SAT", "MON_SDF"), strict=True)})
    for label, value, size in (("ot", ot, layout.name_size), ("nickname", nickname, layout.nickname_size)):
        if value is not None:
            _raw(value, size, label)
            result[label + "_raw_hex"] = value.hex()
            if name_decoder is not None:
                result["ot_name" if label == "ot" else label] = name_decoder(value)
    return result


def decode_party_mon(raw, layout, *, species_marker=None, ot=None, nickname=None, name_decoder=None):
    return _decode(raw, layout, True, species_marker, ot, nickname, name_decoder)


def decode_box_mon(raw, layout, *, species_marker=None, ot=None, nickname=None, name_decoder=None):
    return _decode(raw, layout, False, species_marker, ot, nickname, name_decoder)


def decode_party_blob(raw, layout, *, species_marker=None, name_decoder=None):
    _raw(raw, layout.party_size + layout.name_size + layout.nickname_size, "party transfer blob")
    start = layout.party_size
    return decode_party_mon(raw[:start], layout, species_marker=species_marker,
                            ot=raw[start:start + layout.name_size], nickname=raw[start + layout.name_size:],
                            name_decoder=name_decoder)


def _encode(mon, layout, party):
    c = layout.constants
    raw = bytearray(_raw(bytes.fromhex(mon["raw_hex"]), layout.party_size if party else layout.box_mon_size,
                         "original record"))

    def put(field, value, size=1):
        _integer(value, 0, (1 << (8 * size)) - 1, field)
        raw[c[field]:c[field] + size] = value.to_bytes(size, "big")

    put("MON_SPECIES", _integer(mon["species_id"], 1, 251, "species"))
    for field, key in (("MON_ITEM", "held_item"), ("MON_HAPPINESS", "happiness"), ("MON_POKERUS", "pokerus")):
        put(field, mon[key])
    put("MON_LEVEL", _integer(mon["level"], 1, 100, "level"))
    put("MON_OT_ID", mon["ot_id"], 2)
    put("MON_EXP", mon["exp"], 3)
    put("MON_DVS", mon["dv_word"], 2)
    _require(mon["dvs"] == decode_dvs(mon["dv_word"]), "contradictory DV fields")
    for name, field in zip(EXP_NAMES, ("MON_HP_EXP", "MON_ATK_EXP", "MON_DEF_EXP", "MON_SPD_EXP", "MON_SPC_EXP"), strict=True):
        put(field, mon["stat_exp"][name], 2)
    _require(len(mon["moves"]) == len(mon["pp"]) == len(mon["pp_ups"]) == 4, "four move/PP slots required")
    raw[c["MON_MOVES"]:c["MON_MOVES"] + 4] = bytes(_integer(move, 0, 255, "move") for move in mon["moves"])
    raw[c["MON_PP"]:c["MON_PP"] + 4] = bytes(_integer(pp, 0, 63, "PP") | _integer(up, 0, 3, "PP Ups") << 6
                                             for pp, up in zip(mon["pp"], mon["pp_ups"], strict=True))
    raw[c["MON_LEVEL"] - 2:c["MON_LEVEL"]] = _raw(bytes.fromhex(mon["aux_bytes_hex"]), 2, "aux bytes")
    if party:
        put("MON_STATUS", mon["status"])
        put("MON_HP", mon["hp"], 2)
        put("MON_MAXHP", mon["max_hp"], 2)
        for name, field in zip(STAT_NAMES[1:], ("MON_ATK", "MON_DEF", "MON_SPD", "MON_SAT", "MON_SDF"), strict=True):
            put(field, mon["stats"][name], 2)
    return bytes(raw)


def encode_party_mon(mon, layout):
    return _encode(mon, layout, True)


def encode_box_mon(mon, layout):
    return _encode(mon, layout, False)


def encode_party_blob(mon, layout):
    return (encode_party_mon(mon, layout)
            + _raw(bytes.fromhex(mon["ot_raw_hex"]), layout.name_size, "OT")
            + _raw(bytes.fromhex(mon["nickname_raw_hex"]), layout.nickname_size, "nickname"))


def key(mon):
    """Full published identity, DDDD:OOOO:SS; evolution changes its species part."""
    return (f"{_integer(mon['dv_word'], 0, 65535, 'DV word'):04X}:"
            f"{_integer(mon['ot_id'], 0, 65535, 'OT ID'):04X}:"
            f"{_integer(mon['species_id'], 1, 251, 'record species'):02X}")


def decode_box(raw, layout, *, name_decoder=None):
    capacity = layout.constants["MONS_PER_BOX"]
    body_size = layout.addresses["sBoxEnd"] - layout.addresses["sBox"]
    _require(isinstance(raw, bytes) and len(raw) in (body_size, layout.box_size), "box must include its full fixed payload")
    count = _integer(raw[0], 0, capacity, "box count")
    _require(raw[count + 1] == 255, "box species list is not terminated")
    records = layout.addresses["sBoxMon1"] - layout.addresses["sBox"]
    ots = layout.addresses["sBoxMonOTs"] - layout.addresses["sBox"]
    nicknames = layout.addresses["sBoxMonNicknames"] - layout.addresses["sBox"]
    mons = []
    for slot in range(count):
        start = records + slot * layout.box_mon_size
        mon = decode_box_mon(raw[start:start + layout.box_mon_size], layout, species_marker=raw[slot + 1],
                             ot=raw[ots + slot * layout.name_size:ots + (slot + 1) * layout.name_size],
                             nickname=raw[nicknames + slot * layout.nickname_size:nicknames + (slot + 1) * layout.nickname_size],
                             name_decoder=name_decoder)
        mon["slot"] = slot
        mons.append(mon)
    return {"count": count, "mons": mons, "raw_hex": raw.hex(), "checksummed": False}


def encode_box(box, layout):
    """Reencode occupied slots while preserving unused slots and optional padding."""
    raw = bytearray(bytes.fromhex(box["raw_hex"]))
    decode_box(bytes(raw), layout)  # establish the original complete buffer shape
    count = _integer(box["count"], 0, layout.constants["MONS_PER_BOX"], "box count")
    _require(len(box["mons"]) == count, "box count/member mismatch")
    raw[0], raw[count + 1] = count, 255
    records = layout.addresses["sBoxMon1"] - layout.addresses["sBox"]
    ots = layout.addresses["sBoxMonOTs"] - layout.addresses["sBox"]
    nicknames = layout.addresses["sBoxMonNicknames"] - layout.addresses["sBox"]
    for slot, mon in enumerate(box["mons"]):
        marker = mon["species_marker"]
        _require(marker in (mon["species_id"], layout.constants["EGG"]), "box species marker mismatch")
        raw[slot + 1] = marker
        start = records + slot * layout.box_mon_size
        raw[start:start + layout.box_mon_size] = encode_box_mon(mon, layout)
        for base, field, size in ((ots, "ot_raw_hex", layout.name_size),
                                  (nicknames, "nickname_raw_hex", layout.nickname_size)):
            start = base + slot * size
            raw[start:start + size] = _raw(bytes.fromhex(mon[field]), size, field)
    return bytes(raw)


def decode_party(raw, layout, *, name_decoder=None):
    """Decode the fixed wPartyCount..wPartyMonNicknamesEnd collection snapshot."""
    addresses = layout.addresses
    base = addresses["wPartyCount"]
    _raw(raw, addresses["wPartyMonNicknamesEnd"] - base, "party collection")
    count = _integer(raw[0], 0, layout.constants["PARTY_LENGTH"], "party count")
    markers = addresses["wPartySpecies"] - base
    _require(raw[markers + count] == 255, "party species list is not terminated")
    records, ots, nicknames = (addresses[name] - base for name in
                               ("wPartyMon1", "wPartyMonOTs", "wPartyMonNicknames"))
    mons = []
    for slot in range(count):
        start = records + slot * layout.party_size
        mon = decode_party_mon(raw[start:start + layout.party_size], layout,
                               species_marker=raw[markers + slot],
                               ot=raw[ots + slot * layout.name_size:ots + (slot + 1) * layout.name_size],
                               nickname=raw[nicknames + slot * layout.nickname_size:nicknames + (slot + 1) * layout.nickname_size],
                               name_decoder=name_decoder)
        mon["slot"] = slot
        mons.append(mon)
    return {"count": count, "mons": mons, "raw_hex": raw.hex()}


def decode_saved_party(raw, layout, *, copy_name, name_decoder=None):
    """Read an explicitly chosen saved copy; selection/qualification is separate."""
    _raw(raw, 0x8000, "CartRAM")
    _require(copy_name in ("primary", "backup"), "unknown save copy")
    region = next(region for region in layout.regions if region.name == "pokemon")
    start = getattr(region, copy_name) + layout.addresses["wPartyCount"] - layout.addresses["wPokemonData"]
    size = layout.addresses["wPartyMonNicknamesEnd"] - layout.addresses["wPartyCount"]
    _require(start + size <= getattr(region, copy_name) + region.length, "party exceeds saved Pokemon region")
    return decode_party(raw[start:start + size], layout, name_decoder=name_decoder)


def calc_stat(base, dv, stat_exp, level, *, is_hp=False, use_stat_exp=True):
    _integer(base, 0, 255, "base stat")
    _integer(dv, 0, 15, "DV")
    _integer(stat_exp, 0, 65535, "stat experience")
    _integer(level, 1, 100, "level")
    _require(type(is_hp) is bool and type(use_stat_exp) is bool, "stat flags must be booleans")
    root = min(255, 1 + isqrt(max(0, stat_exp - 1)))
    bonus = root // 4 if use_stat_exp else 0
    result = ((2 * (base + dv) + bonus) * level) // 100
    return min(999, result + (level + 10 if is_hp else 5))


def calc_stats(base_stats, dvs, stat_exp, level, *, use_stat_exp=True):
    for name in ("attack", "defense", "speed", "special"):
        _integer(dvs[name], 0, 15, name + " DV")
    hp_dv = sum((dvs[name] & 1) << shift for name, shift in zip(("attack", "defense", "speed", "special"), (3, 2, 1, 0), strict=True))
    result = {}
    for name in STAT_NAMES:
        source = "special" if name.startswith("special_") else name
        result[name] = calc_stat(base_stats[name], hp_dv if name == "hp" else dvs[source],
                                 stat_exp[source], level, is_hp=name == "hp", use_stat_exp=use_stat_exp)
    return result


# data/growth_rates.asm, identical at both exact pins. Arithmetic wraps to 24 bits,
# including the source-documented Medium-Slow level-1 underflow.
GROWTH_RATES = {
    "GROWTH_MEDIUM_FAST": (1, 1, 0, 0, 0), "GROWTH_SLIGHTLY_FAST": (3, 4, 10, 0, 30),
    "GROWTH_SLIGHTLY_SLOW": (3, 4, 20, 0, 70), "GROWTH_MEDIUM_SLOW": (6, 5, -15, 100, 140),
    "GROWTH_FAST": (4, 5, 0, 0, 0), "GROWTH_SLOW": (5, 4, 0, 0, 0),
}


def exp_for_level(level, growth_rate):
    _integer(level, 1, 100, "level")
    _require(growth_rate in GROWTH_RATES, "unknown source growth rate")
    a, b, c, d, e = GROWTH_RATES[growth_rate]
    return (a * level**3 // b + c * level**2 + d * level - e) & 0xFFFFFF


def level_from_exp(exp, growth_rate):
    _integer(exp, 0, 0xFFFFFF, "experience")
    for level in range(2, 101):
        if exp < exp_for_level(level, growth_rate):
            return level - 1
    return 100


def sav_checksum(raw, layout, copy_name="primary"):
    _raw(raw, 0x8000, "CartRAM (RTC-tail normalization is not implemented)")
    _require(copy_name in layout.checksum_spans, "unknown save copy")
    return sum(sum(raw[start:start + length]) for start, length in layout.checksum_spans[copy_name]) & 0xFFFF


def checksum_report(raw, layout):
    _raw(raw, 0x8000, "CartRAM (RTC-tail normalization is not implemented)")
    report = {"boxes_checksummed": False}
    for copy_name in ("primary", "backup"):
        computed = sav_checksum(raw, layout, copy_name)
        offset = layout.checksum_offsets[copy_name]
        stored = int.from_bytes(raw[offset:offset + 2], "little")
        report[copy_name] = {"computed": computed, "stored": stored, "checksum_valid": computed == stored,
                             "markers_valid": all(raw[address] == value for address, value in layout.markers[copy_name])}
    return report


def strict_checksum_witness(raw, layout):
    """Strict structural witness, never a physical durability or box-integrity receipt."""
    if not isinstance(raw, bytes) or len(raw) != 0x8000:
        return {"valid": False, "reason": "requires exact 0x8000 CartRAM; RTC-tail normalization OPEN"}
    report = checksum_report(raw, layout)
    report["copies_agree"] = all(raw[r.primary:r.primary + r.length] == raw[r.backup:r.backup + r.length]
                                 for r in layout.regions)
    report["valid"] = report["copies_agree"] and all(report[copy_name]["checksum_valid"] and report[copy_name]["markers_valid"]
                                                    for copy_name in ("primary", "backup"))
    report["physical_durability"] = "UNQUALIFIED"
    return report


def game_menu_candidate(raw, layout):
    """TryLoadSaveData's primary-then-backup sentinel decision, no checksum claim."""
    _raw(raw, 0x8000, "CartRAM")
    for copy_name in ("primary", "backup"):
        if all(raw[address] == value for address, value in layout.markers[copy_name]):
            return copy_name
    return None


def game_recovery_view(raw, layout):
    """TryLoadSaveFile's checksum fallback projection; does not alter any bytes."""
    report = checksum_report(raw, layout)
    selected = next((name for name in ("primary", "backup") if report[name]["checksum_valid"]), None)
    _require(selected is not None, "both primary and backup checksums are bad")
    regions = {}
    for region in layout.regions:
        start = getattr(region, selected)
        regions[region.name] = raw[start:start + region.length]
    return {"selected_copy": selected, "regions": regions,
            "game_rewrites_copy": "backup" if selected == "primary" else "primary",
            "boxes_recovered": False, "full_repair_modeled": False, "physical_durability": "UNQUALIFIED"}


def verify_boxes(raw, layout, *, name_decoder: Callable[[bytes], str] | None = None):
    _raw(raw, 0x8000, "CartRAM")
    return [decode_box(raw[start:start + length], layout, name_decoder=name_decoder)
            for start, length in layout.storage_boxes]
