"""Independent RBY physical trade-result prediction and readback validation.

This read-only policy does not admit a ROM, prove native execution, validate a
save-file flush, or commit links. Its caller supplies the separately admitted
cartridge/hash and must require operation-bound animation/completion evidence,
including when before and after party bytes are identical.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from server.adapters.gen1_rom_scan import identify, scan_evos_moves, sym_to_offset
from server.gen1_party_codec import PartyCodec, PartyCodecError, PartyMon, _key_set
from server.stat_experience import calculate_stat, split_dvs


@dataclass(frozen=True)
class TradeOutcome:
    blob: bytes
    evolution_path: tuple[int, ...]
    # (new species, learned move, replaced/filled slot); None means declined.
    learning: tuple[tuple[int, int, int | None], ...] = ()


class TradeResultRules:
    def __init__(self, variant, *, names, records, hm_moves, rom_sha1):
        self.codec = PartyCodec(variant)
        self.variant = variant
        if not isinstance(rom_sha1, str) or not re.fullmatch("[0-9a-f]{40}", rom_sha1):
            raise PartyCodecError("exact cartridge hash required for trade rules")
        self.rom_sha1 = rom_sha1
        species = {int(value) for value in self.codec.profile["species"]}
        if (not isinstance(names, dict) or set(names) != species or any(type(k) is not int for k in names)
                or not isinstance(records, dict) or set(records) != species or any(type(k) is not int for k in records)):
            raise PartyCodecError("complete per-species trade rules required")
        self._names, self._records = {}, {}
        for index in sorted(species):
            name = names[index]
            if not isinstance(name, bytes) or len(name) != 11:
                raise PartyCodecError("canonical names must include all eleven bytes")
            self.codec._name(name, "canonical species name")
            self._names[index] = name
            record = records[index]
            if not isinstance(record, dict) or set(record) != {"evolutions", "moves"}:
                raise PartyCodecError("invalid species trade rule")
            evolutions, moves = record["evolutions"], record["moves"]
            if not isinstance(evolutions, (list, tuple)) or len(evolutions) > 7:
                raise PartyCodecError("invalid evolution count")
            parsed = []
            for entry in evolutions:
                if (not isinstance(entry, (list, tuple)) or len(entry) != 3
                        or entry[0] not in ("level", "item", "trade")
                        or type(entry[1]) is not int or not 0 <= entry[1] <= 255
                        or type(entry[2]) is not int or entry[2] not in species):
                    raise PartyCodecError("invalid evolution entry")
                parsed.append(tuple(entry))
            targets = self.codec.profile["species"][str(index)]["evolution_targets"]
            if sorted(row[2] for row in parsed) != sorted(targets):
                raise PartyCodecError("evolution targets differ from canonical families")
            if not isinstance(moves, (list, tuple)) or len(moves) > 64:
                raise PartyCodecError("invalid learnset count")
            learned = []
            for entry in moves:
                if (not isinstance(entry, (list, tuple)) or len(entry) != 2
                        or type(entry[0]) is not int or not 1 <= entry[0] <= 100
                        or type(entry[1]) is not int or not 1 <= entry[1] <= 165):
                    raise PartyCodecError("invalid level-up move")
                learned.append(tuple(entry))
            self._records[index] = (tuple(parsed), tuple(learned))
        if (not isinstance(hm_moves, (tuple, list)) or len(hm_moves) != 5
                or any(type(move) is not int or not 1 <= move <= 165 for move in hm_moves)
                or len(set(hm_moves)) != 5):
            raise PartyCodecError("five valid HM moves required")
        self._hm_moves = frozenset(hm_moves)

    @classmethod
    def from_rom(cls, variant, rom, *, expected_sha1):
        """Read rules from the exact supplied artifact; does not grant admission."""
        info = identify(rom)
        if info["variant"] != variant or info["sha1"] != expected_sha1:
            raise PartyCodecError("trade-rule cartridge differs from the expected artifact")
        source = Path(__file__).resolve().parents[1] / "data/pret_rom_syms.json"
        symbols = json.loads(source.read_text())[info["syms_key"]]["symbols"]
        codec = PartyCodec(variant)
        names_base = sym_to_offset(symbols["MonsterNames"])
        names = {int(index): rom[names_base + (int(index)-1)*10:names_base + int(index)*10] + b"\x50"
                 for index in codec.profile["species"]}
        hm_base = sym_to_offset(symbols["HMMoves"])
        if rom[hm_base + 5] != 255:
            raise PartyCodecError("HM move table terminator differs")
        records = scan_evos_moves(rom)
        return cls(variant, names=names, records={key: records[key] for key in names},
                   hm_moves=list(rom[hm_base:hm_base+5]), rom_sha1=expected_sha1)

    def _evolve(self, previous: PartyMon, species: int, *, allow_zero_hp=False) -> bytes:
        facts = self.codec.profile["species"][str(species)]
        values = [calculate_stat(base, dv, previous.level, exp, hp=(i == 0))
                  for i, (base, dv, exp) in enumerate(zip(
                      facts["base_stats"], split_dvs(previous.dv_word), previous.stat_experience, strict=True))]
        hp = previous.hp + values[0] - previous.max_hp
        if not (0 if allow_zero_hp else 1) <= hp <= values[0]:
            raise PartyCodecError("evolution would produce invalid HP from the received cached stats")
        raw = bytearray(previous.raw)
        raw[0] = species
        raw[1:3] = hp.to_bytes(2, "big")
        raw[5:7] = bytes(facts["types"])
        for offset, value in zip(range(34, 44, 2), values, strict=True):
            raw[offset:offset+2] = value.to_bytes(2, "big")
        if previous.nickname.split(b"\x50", 1)[0] == self._names[previous.species_index].split(b"\x50", 1)[0]:
            raw[55:66] = self._names[species]
        return bytes(raw)

    def outcomes(self, incoming) -> tuple[TradeOutcome, ...]:
        received = self.codec.validate_blob(incoming)
        if not received.hp:
            raise PartyCodecError("incoming linked Pokemon is fainted")
        outcomes = [TradeOutcome(received.raw, ())]
        # The original loop advances through the incoming species' original
        # evolution list; a non-trade entry or unmet level ends this mon's pass.
        for method, required, target in self._records[received.species_index][0]:
            if method != "trade" or received.level < required:
                break
            staged = []
            for outcome in outcomes:
                old = self.codec.validate_blob(outcome.blob)
                path = outcome.evolution_path + (target,)
                for evolved in self.evolution_outcomes(old.raw, target):
                    staged.append(TradeOutcome(evolved.blob, path, outcome.learning + evolved.learning))
            if len(staged) > 625:
                raise PartyCodecError("trade outcome branching exceeds the supported bound")
            outcomes = staged
        for outcome in outcomes:
            self.codec.validate_blob(outcome.blob)
        return tuple(outcomes)

    def evolution_outcomes(self, before, target, *, allow_zero_hp=False) -> tuple[TradeOutcome, ...]:
        """One engine evolution plus its optional move prompt, shared with source receipts.

        The caller proves why this target was selected. This predicts the exact
        species/stat/HP/default-name writes and allowed learning choices only.
        """
        old = self.codec.validate_blob(before)
        evolved = self._evolve(old, target, allow_zero_hp=allow_zero_hp)
        moves = list(evolved[8:12])
        move = next((move for level, move in self._records[target][1] if level == old.level), None)
        if move is None or move in moves:
            return (TradeOutcome(evolved, (target,)),)
        choices = [moves.index(0)] if 0 in moves else [None] + [
            slot for slot, old_move in enumerate(moves) if old_move not in self._hm_moves]
        result = []
        for slot in choices:
            changed = bytearray(evolved)
            if slot is not None:
                changed[8+slot] = move
                changed[29+slot] = self.codec.max_pp(move, 0)
            self.codec.validate_blob(bytes(changed))
            result.append(TradeOutcome(bytes(changed), (target,), ((target, move, slot),)))
        return tuple(result)

    def verify_party(self, before, slot, incoming, after, *, expected_key, incoming_key, boxed_keys):
        """Verify exact remove/append, legal evolution/learning and local keys."""
        if boxed_keys is None:
            raise PartyCodecError("verified boxed inventory is required")
        boxed_keys = _key_set(boxed_keys)
        candidates = self.outcomes(incoming)
        post = self.codec.validate_party(after, boxed_keys=boxed_keys)
        for candidate in candidates:
            target = candidate.blob[0]
            prepared, _ = self.codec.prepare_exchange(before, slot, incoming, expected_key=expected_key,
                incoming_key=incoming_key, evolved_species=target, boxed_keys=boxed_keys)
            expected = prepared[:-1] + (candidate.blob,)
            if tuple(mon.raw for mon in post) == expected:
                return candidate
        raise PartyCodecError("trade party differs from canonical removal/append/evolution outcomes")

    def digest(self):
        """Bind preparation to this exact ROM's rule inputs, without admission."""
        value = {"variant": self.variant, "rom_sha1": self.rom_sha1,
                 "names": {str(k): v.hex() for k, v in self._names.items()},
                 "records": self._records, "hm_moves": sorted(self._hm_moves)}
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def verify_save_region(self, region, live_party_storage, after, *, before_region, before_dex, incoming, outgoing,
                           outcome, save_id, save_name, before_pikachu=None):
        """Verify canonical CartRAM readback; this is not a host-file flush proof.

        region spans sGameData through sMainDataCheckSum inclusive. The caller
        reads its bank-qualified range from the admitted profile. Geometry is
        derived from packaged canonical symbols rather than a party OT field.
        """
        symbols = json.loads((Path(__file__).resolve().parents[1] / "data/pret_syms.json").read_text())[
            "pokeyellow" if self.variant == "yellow" else "pokered"]
        length = symbols["sMainDataCheckSum"] - symbols["sGameData"] + 1
        party_length = symbols["wPartyDataEnd"] - symbols["wPartyDataStart"]
        if not isinstance(region, bytes) or len(region) != length or (sum(region) & 255) != 255:
            raise PartyCodecError("canonical save region length/checksum differs")
        if not isinstance(before_region, bytes) or len(before_region) != length or (sum(before_region) & 255) != 255:
            raise PartyCodecError("valid pre-trade canonical save required")
        if not isinstance(live_party_storage, bytes) or len(live_party_storage) != party_length:
            raise PartyCodecError("complete live party storage required")
        offset = symbols["sPartyData"] - symbols["sGameData"]
        if region[offset:offset+party_length] != live_party_storage:
            raise PartyCodecError("canonical SRAM party differs from live party storage")
        party = self.codec.validate_party(after)
        count = len(party)
        if live_party_storage[:count+2] != bytes([count, *(mon.species_index for mon in party), 255]):
            raise PartyCodecError("saved party count/species list differs")
        ot_start, nick_start = 8+6*44, 8+6*44+6*11
        for slot, mon in enumerate(party):
            raw = (live_party_storage[8+slot*44:8+(slot+1)*44] +
                   live_party_storage[ot_start+slot*11:ot_start+(slot+1)*11] +
                   live_party_storage[nick_start+slot*11:nick_start+(slot+1)*11])
            if raw != mon.raw:
                raise PartyCodecError("saved party record differs from verified poststate")
        if not isinstance(before_dex, bytes) or len(before_dex) != 38:
            raise PartyCodecError("complete pre-trade owned/seen data required")
        if not isinstance(outcome, TradeOutcome) or outcome not in self.outcomes(incoming):
            raise PartyCodecError("verified trade outcome required for dex readback")
        if party[-1].raw != outcome.blob:
            raise PartyCodecError("saved recipient does not match the verified trade outcome")
        expected_dex = bytearray(before_dex)
        for species in (self.codec.validate_blob(incoming).species_index, *outcome.evolution_path):
            dex = self.codec.profile["species"][str(species)]["dex"] - 1
            for base in (0, 19):
                expected_dex[base + dex//8] |= 1 << (dex % 8)
        main = symbols["sMainData"] - symbols["sGameData"]
        if region[main:main+38] != expected_dex:
            raise PartyCodecError("saved Pokédex differs from native owned/seen changes")
        player = main + symbols["wPlayerID"] - symbols["wMainDataStart"]
        if (not isinstance(save_id, str) or not re.fullmatch("[0-9A-F]{4}", save_id)
                or region[player:player+2].hex().upper() != save_id):
            raise PartyCodecError("save player ID differs from admitted identity")
        if not isinstance(save_name, bytes) or len(save_name) != 11 or region[:11] != save_name:
            raise PartyCodecError("save trainer name differs from admitted identity")
        allowed = set(range(offset, offset+party_length)) | set(range(main, main+38)) | {length-1}
        if self.variant == "yellow":
            if not isinstance(before_pikachu, bytes) or len(before_pikachu) != 2:
                raise PartyCodecError("Yellow happiness/mood snapshot required")
            selected = self.codec.validate_blob(outgoing)
            expected = before_pikachu
            # IsThisPartyMonStarterPikachu compares exactly five raw OT-name
            # bytes (NAME_LENGTH_JP-1), plus species and wPlayerID; not the DVs.
            if selected.species_index == 84 and selected.ot_id == int(save_id, 16) and selected.ot_name[:5] == save_name[:5]:
                expected = bytes((max(0, before_pikachu[0] - (20 if before_pikachu[0] >= 200 else 10)), 0))
            pika = main + symbols["wPikachuHappiness"] - symbols["wMainDataStart"]
            if region[pika:pika+2] != expected:
                raise PartyCodecError("saved Yellow trade happiness/mood differs")
            allowed.update((pika, pika+1))
        elif before_pikachu is not None:
            raise PartyCodecError("Pikachu state belongs only to Yellow")
        if any(value != before_region[i] for i, value in enumerate(region) if i not in allowed):
            raise PartyCodecError("trade save changed unrelated main/sprite/box data")
        return hashlib.sha256(region).hexdigest()
