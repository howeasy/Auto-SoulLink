"""Strict, read-only validation for gen1-rby-party-v1 (44 + 11 + 11 bytes).

Facts come from the pinned canonical generator. Approved UPR changes leave these
species/type/growth/move-PP facts unchanged; this codec does not replace ROM admission.
Computed stats are range checked, not recomputed: stat experience can increase
without a level-up, so a legitimate party tail can precede the next CalcStats call.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

VERSION = "gen1-rby-party-v1"
BLOB_LENGTH = 66
DATA_PATH = Path(__file__).resolve().parents[1] / "data/games/gen1_rby/party_codec.json"


class PartyCodecError(ValueError):
    """The entire operation must be rejected before any cartridge write."""


@dataclass(frozen=True)
class PartyMon:
    raw: bytes
    key: str
    species_index: int
    species_id: int
    level: int
    hp: int
    max_hp: int
    status: int
    moves: tuple[int, ...]
    pp: tuple[int, ...]
    pp_ups: tuple[int, ...]
    box_level: int
    types: tuple[int, int]
    catch_rate: int
    ot_id: int
    dv_word: int
    experience: int
    stat_experience: tuple[int, ...]
    computed_stats: tuple[int, ...]
    ot_name: bytes
    nickname: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()


def _integer(value, low: int, high: int, label: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise PartyCodecError(f"{label} must be an integer in {low}..{high}")
    return value


def _bytes(raw) -> bytes:
    if isinstance(raw, (bytes, bytearray)):
        data = bytes(raw)
    elif isinstance(raw, (list, tuple)):
        if len(raw) != BLOB_LENGTH:
            raise PartyCodecError("party blob must be exactly 66 bytes")
        data = bytes(_integer(value, 0, 255, "blob byte") for value in raw)
    else:
        raise PartyCodecError("party blob must be bytes or an integer array")
    if len(data) != BLOB_LENGTH:
        raise PartyCodecError("party blob must be exactly 66 bytes")
    return data


def _key_set(values) -> set[str]:
    if isinstance(values, (str, bytes)):
        raise PartyCodecError("boxed inventory must contain complete keys")
    try:
        entries = list(values)
        result = set(entries)
    except (TypeError, ValueError) as exc:
        raise PartyCodecError("invalid boxed inventory") from exc
    if any(not isinstance(key, str) or not re.fullmatch(r"[0-9A-F]{4}:[0-9A-F]{4}:[0-9A-F]{2}", key)
           for key in result):
        raise PartyCodecError("invalid boxed key")
    if len(result) != len(entries):
        raise PartyCodecError("duplicate boxed key")
    return result


class PartyCodec:
    def __init__(self, variant: str, data: dict | None = None):
        if variant not in ("red", "blue", "yellow"):
            raise PartyCodecError("party codec is supported only for admitted Red, Blue or Yellow")
        data = data if data is not None else json.loads(DATA_PATH.read_text(encoding="utf-8"))
        if data.get("schema") != "gen1-rby-codec-data-v1":
            raise PartyCodecError("unsupported party-codec data schema")
        content = {key: value for key, value in data.items() if key != "content_sha256"}
        digest = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"),
                                          ensure_ascii=True).encode()).hexdigest()
        if digest != data.get("content_sha256"):
            raise PartyCodecError("party-codec data checksum differs")
        self.variant = variant
        self.profile = data["titles"][variant]
        self.names = frozenset(data["name_bytes"])
        self.curves = data["growth_rates"]

    def experience_for_level(self, growth: int, level: int) -> int:
        _integer(growth, 0, 5, "growth rate")
        _integer(level, 1, 100, "level")
        a, b, c, d, e = self.curves[growth]
        return (a * level ** 3 // b + c * level ** 2 + d * level - e) % 0x1000000

    def level_from_experience(self, growth: int, experience: int) -> int:
        _integer(experience, 0, self.experience_for_level(growth, 100), "experience")
        level = 1
        for candidate in range(2, 101):
            if self.experience_for_level(growth, candidate) > experience:
                break
            level = candidate
        return level

    def max_pp(self, move: int, ups: int) -> int:
        _integer(move, 1, 165, "move")
        _integer(ups, 0, 3, "PP-Up count")
        base = self.profile["move_pp"][str(move)]
        # AddBonusPP caps EACH PP Up's bonus at 7; 40-PP moves therefore max at61.
        return base + ups * min(7, base // 5)

    def _name(self, raw: bytes, label: str) -> None:
        terminator = raw.find(b"\x50")
        if not 1 <= terminator <= 10:
            raise PartyCodecError(f"{label} needs nonempty text and a $50 terminator within 11 bytes")
        if any(value not in self.names for value in raw[:terminator]):
            raise PartyCodecError(f"{label} contains an invalid name glyph or text control")
        # Bytes following the terminator are opaque cartridge padding and are preserved.

    def validate_blob(self, raw, *, expected_key: str | None = None) -> PartyMon:
        data = _bytes(raw)
        species = data[0]
        facts = self.profile["species"].get(str(species))
        if facts is None:
            raise PartyCodecError("invalid internal species")
        key = f"{data[27:29].hex().upper()}:{data[12:14].hex().upper()}:{species:02X}"
        if expected_key is not None and expected_key != key:
            raise PartyCodecError("key does not match species, DVs and OTID")
        level = _integer(data[33], 1, 100, "level")
        _integer(data[3], 0, 100, "box level")  # AddPartyMon initializes this to0.
        experience = int.from_bytes(data[14:17], "big")
        if self.level_from_experience(facts["growth_rate"], experience) != level:
            raise PartyCodecError("level does not match experience")
        if list(data[5:7]) != facts["types"]:
            raise PartyCodecError("types differ from the canonical species")
        status = data[4]
        if status not in (*range(8), 8, 16, 32, 64):
            raise PartyCodecError("invalid or combined Gen1 status")
        stats = tuple(int.from_bytes(data[offset:offset + 2], "big") for offset in range(34, 44, 2))
        for value in stats:
            _integer(value, 1, 999, "computed stat")
        hp = int.from_bytes(data[1:3], "big")
        if hp > stats[0]:
            raise PartyCodecError("current HP exceeds max HP")
        moves, pp, ups = tuple(data[8:12]), [], []
        empty = False
        for index, move in enumerate(moves):
            packed = data[29 + index]
            current, count = packed & 0x3F, packed >> 6
            if move == 0:
                empty = True
                if packed:
                    raise PartyCodecError("empty move slot has PP or PP Ups")
            else:
                if empty:
                    raise PartyCodecError("nonempty move after an empty slot")
                if current > self.max_pp(move, count):
                    raise PartyCodecError("PP exceeds the canonical PP-Up maximum")
            pp.append(current)
            ups.append(count)
        if not moves[0]:
            raise PartyCodecError("Pokemon must have at least one move")
        self._name(data[44:55], "OT name")
        self._name(data[55:66], "nickname")
        return PartyMon(data, key, species, facts["dex"], level, hp, stats[0], status,
                        moves, tuple(pp), tuple(ups), data[3], (data[5], data[6]), data[7],
                        int.from_bytes(data[12:14], "big"), int.from_bytes(data[27:29], "big"),
                        experience, tuple(int.from_bytes(data[i:i + 2], "big") for i in range(17, 27, 2)),
                        stats, data[44:55], data[55:66])

    def validate_party(self, blobs, *, species_list=None, boxed_keys: Iterable[str] = ()) -> tuple[PartyMon, ...]:
        if not isinstance(blobs, (list, tuple)) or not 1 <= len(blobs) <= 6:
            raise PartyCodecError("party must contain 1..6 blobs")
        party = tuple(self.validate_blob(blob) for blob in blobs)
        keys = [mon.key for mon in party]
        if len(set(keys)) != len(keys) or set(keys).intersection(_key_set(boxed_keys)):
            raise PartyCodecError("duplicate party or boxed key")
        if species_list is not None:
            if not isinstance(species_list, (bytes, bytearray, list, tuple)) or len(species_list) not in (len(party) + 1, 7):
                raise PartyCodecError("invalid party species-list length")
            values = [_integer(value, 0, 255, "species-list byte") for value in species_list]
            if values[:len(party) + 1] != [mon.species_index for mon in party] + [255]:
                raise PartyCodecError("party count/species list or $FF terminator differs")
        return party

    def prepare_exchange(self, blobs, selected_slot: int, incoming, *, expected_key: str,
                         incoming_key: str, evolved_species: int, boxed_keys=None) -> tuple[tuple[bytes, ...], str]:
        """Validate representation/order; the coordinator must also verify epochs,
        offer blob digests and the recipient ROM's exact evolution-method outcome.
        """
        if boxed_keys is None:
            raise PartyCodecError("verified boxed inventory is required before trade preparation")
        if expected_key == incoming_key:
            raise PartyCodecError("outgoing and incoming keys collide")
        boxed_keys = _key_set(boxed_keys)
        _key_set((expected_key, incoming_key))
        party = self.validate_party(blobs, boxed_keys=boxed_keys)
        _integer(selected_slot, 0, len(party) - 1, "selected slot")
        outgoing = party[selected_slot]
        if outgoing.key != expected_key or not outgoing.hp:
            raise PartyCodecError("selected Pokemon moved, changed identity or fainted")
        received = self.validate_blob(incoming, expected_key=incoming_key)
        if not received.hp:
            raise PartyCodecError("incoming linked Pokemon is fainted")
        _integer(evolved_species, 1, 190, "predicted evolution species")
        if str(evolved_species) not in self.profile["species"]:
            raise PartyCodecError("invalid predicted evolution species")
        targets = self.profile["species"][str(received.species_index)]["evolution_targets"]
        if evolved_species != received.species_index and evolved_species not in targets:
            raise PartyCodecError("predicted evolution changes the canonical evolution target")
        predicted_key = received.key[:-2] + f"{evolved_species:02X}"
        remaining = tuple(mon for slot, mon in enumerate(party) if slot != selected_slot)
        occupied = {mon.key for mon in remaining}.union(boxed_keys)
        if received.key in occupied or predicted_key in occupied:
            raise PartyCodecError("incoming or post-evolution key collision")
        # The caller must derive evolved_species from the admitted recipient ROM.
        # This returns the pre-evolution physical order; the cartridge evolves it.
        return tuple(mon.raw for mon in remaining) + (received.raw,), predicted_key
