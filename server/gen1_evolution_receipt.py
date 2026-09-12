"""Complete original-engine evolution publication, without identity mutation."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from server.gen1_capture_receipt import box_records, party_mons
from server.gen1_engine_signals import integer, raw
from server.gen1_initial_observation import display_name
from server.gen1_party_codec import PartyCodec, PartyCodecError
from server.gen1_trade_result import TradeResultRules
from server.protocol import digest
from server.protocol_journal import JournalError

DATA = json.loads(
    (Path(__file__).resolve().parents[1] / "data/games/gen1_rby/evolution_sites.json").read_text()
)
SCHEMA = "rby-evolution-receipt-v1"
HEADER = {
    "schema",
    "source_sha256",
    "variant",
    "context_generation",
    "physical_instance",
    "final_sha1",
    "outcome",
    "before",
    "after",
}
POINT = {
    "party_hex",
    "box_hex",
    "trainer_hex",
    "player_id_hex",
    "dex_hex",
    "map_id",
    "battle_flag",
    "link_state",
    "slot",
    "table_species",
    "current_item",
    "force",
    "current_box",
    "mon_location",
}


@lru_cache(maxsize=12)
def rules_for(variant, final_sha1, rom=None):
    if rom is not None:
        if not isinstance(rom, bytes) or hashlib.sha1(rom).hexdigest() != final_sha1:
            raise JournalError("evolution ROM differs from admission")
        return TradeResultRules.from_rom(variant, rom, expected_sha1=final_sha1)
    from server.gen1_cartridge_profiles import companion_profiles

    allowed = {
        DATA["titles"][variant]["clean_sha1"],
        companion_profiles()[variant]["final_rom_sha1"],
    }
    if final_sha1 not in allowed:
        raise JournalError("randomized evolution requires its complete admitted ROM")
    data = DATA["titles"][variant]["rules"]
    return TradeResultRules(
        variant,
        names={int(k): bytes.fromhex(v) for k, v in data["names"].items()},
        records={int(k): v for k, v in data["records"].items()},
        hm_moves=data["hm_moves"],
        rom_sha1=final_sha1,
    )


def _target(profile, index, pointer, rom):
    entries = profile["rules"]["entries"].get(str(index))
    if entries is None:
        raise JournalError("evolution table species is invalid")
    if rom is not None:
        base = profile["table"]["rom_offset"] + (index - 1) * 2
        cursor = int.from_bytes(rom[base : base + 2], "little")
        entries = []
        for _ in range(8):
            if not 0x4000 <= cursor < 0x8000:
                raise JournalError("evolution pointer leaves its source bank")
            offset = profile["table"]["bank"] * 0x4000 + cursor - 0x4000
            method = rom[offset]
            if method == 0:
                break
            if method not in (1, 2, 3):
                raise JournalError("unsupported evolution method")
            size = 4 if method == 2 else 3
            entries.append(
                {
                    "pointer": cursor + size - 1,
                    "method": method,
                    "parameter": rom[offset + 1],
                    "minimum_level": rom[offset + 2] if method == 2 else rom[offset + 1],
                    "target": rom[offset + size - 1],
                }
            )
            cursor += size
    selected = [entry for entry in entries if entry["pointer"] == pointer]
    if len(selected) != 1:
        raise JournalError("evolution selection is not an entry of its admitted table")
    return selected[0]


def _point(value, variant, identity):
    if not isinstance(value, dict) or set(value) != POINT:
        raise JournalError("complete evolution party/current-box point required")
    for field in POINT - {"party_hex", "box_hex", "trainer_hex", "player_id_hex", "dex_hex"}:
        integer(value[field], 0, 255, field)
    codec = PartyCodec(variant)
    name = raw(value["trainer_hex"], 11)
    codec._name(name, "evolution save name")
    raw(value["player_id_hex"], 2)
    if identity != {"ot_id": value["player_id_hex"], "trainer_name": display_name(name)}:
        raise JournalError("evolution belongs to another save")
    party = raw(value["party_hex"], 404)
    box = raw(value["box_hex"], 1122)
    dex = raw(value["dex_hex"], 38)
    mons = party_mons(codec, party)
    boxed = box_records(codec, box)
    keys = [m.key for m in mons] + [key for _, key in boxed]
    if len(keys) != len(set(keys)):
        raise JournalError("evolution physical roster has colliding keys")
    if value["current_box"] & 127 >= 12 or value["mon_location"] != 0 or value["slot"] >= len(mons):
        raise JournalError("ordinary evolution must select an existing party member")
    if value["link_state"] == DATA["titles"][variant]["link_state_trading"]:
        raise JournalError("trade evolution belongs to its native or NPC receipt")
    if value["link_state"] != 0 or value["battle_flag"] not in (0, 1, 2):
        raise JournalError("unsupported evolution battle/link context")
    return mons, party, box, dex, {key for _, key in boxed}


def _validate(
    receipt, *, variant, identity, context_generation, physical_instance, final_sha1, rom=None
):
    if not isinstance(variant, str) or variant not in DATA["titles"]:
        raise JournalError("RBY evolution variant required")
    if (
        not isinstance(receipt, dict)
        or set(receipt) != HEADER
        or receipt["outcome"] not in ("evolved", "cancelled")
    ):
        raise JournalError("complete evolution source receipt required")
    if (
        receipt["schema"] != SCHEMA
        or receipt["source_sha256"] != DATA["sha256"]
        or receipt["variant"] != variant
        or receipt["context_generation"] != context_generation
        or receipt["physical_instance"] != physical_instance
        or receipt["final_sha1"] != final_sha1
    ):
        raise JournalError("evolution source/admission differs")
    profile = DATA["titles"][variant]
    for label, kind in (("before", "begin"), ("after", receipt["outcome"])):
        value = receipt[label]
        fields = {"frame", "pc", "bank", "sp", "point"} | (
            {"selection"} if label == "before" else set()
        )
        if not isinstance(value, dict) or set(value) != fields:
            raise JournalError("complete evolution " + label + " witness required")
        site = profile["sites"][kind]
        if (
            type(value["pc"]) is not int
            or value["pc"] != site["address"]
            or type(value["bank"]) is not int
            or value["bank"] != site["bank"]
        ):
            raise JournalError("evolution publication site differs")
        integer(value["frame"], 0, 2**53 - 1, "evolution frame")
        integer(value["sp"], 0xC000, 0xDFFF, "evolution stack")
    a, b = receipt["before"], receipt["after"]
    if b["frame"] < a["frame"] or a["sp"] != b["sp"]:
        raise JournalError("evolution result does not continue its original attempt")
    before, party, box, dex, boxed = _point(a["point"], variant, identity)
    after, after_party, after_box, after_dex, _ = _point(b["point"], variant, identity)
    stable = (
        "trainer_hex",
        "player_id_hex",
        "map_id",
        "battle_flag",
        "link_state",
        "slot",
        "table_species",
        "force",
        "current_box",
        "mon_location",
    )
    if any(a["point"][k] != b["point"][k] for k in stable) or box != after_box:
        raise JournalError("evolution changed its save/slot/current-box context")
    slot = a["point"]["slot"]
    old = before[slot]
    new = after[slot]
    selected = a["selection"]
    if not isinstance(selected, dict) or set(selected) != {"pointer", "level"}:
        raise JournalError("complete evolution table selection required")
    integer(selected["pointer"], 0x4000, 0x7FFF, "evolution target pointer")
    integer(selected["level"], 1, 100, "evolution level register")
    if selected["level"] != old.level or a["point"]["table_species"] != old.species_index:
        raise JournalError("multi-transition or inconsistent evolution source is not supported")
    policy = rules_for(variant, final_sha1, rom)
    entry = _target(profile, old.species_index, selected["pointer"], rom)
    if entry["method"] == 3:
        raise JournalError("trade method cannot become ordinary evolution")
    if old.level < entry["minimum_level"] or entry["method"] == 1 and a["point"]["force"] != 0:
        raise JournalError("evolution attempt did not meet its level/force source condition")
    if entry["method"] == 2:
        if (
            a["point"]["current_item"] != entry["parameter"]
            or variant == "yellow"
            and a["point"]["battle_flag"] != 0
        ):
            raise JournalError("evolution item does not meet the cartridge condition")
        if (
            variant == "yellow"
            and old.species_index == 84
            and old.ot_id == int(identity["ot_id"], 16)
            and old.ot_name[:5] == raw(a["point"]["trainer_hex"], 11)[:5]
        ):
            raise JournalError("Yellow following starter refuses the stone before evolution")
    if receipt["outcome"] == "cancelled":
        if a["point"]["force"] != 0 or party != after_party or dex != after_dex:
            raise JournalError("cancelled evolution changed party/dex or bypassed forced evolution")
    else:
        expected_dex = bytearray(dex)
        index = policy.codec.profile["species"][str(entry["target"])]["dex"] - 1
        for offset in (0, 19):
            expected_dex[offset + index // 8] |= 1 << (index % 8)
        candidates = policy.evolution_outcomes(old.raw, entry["target"], allow_zero_hp=True)
        valid = False
        for candidate in candidates:
            expected = bytearray(party)
            expected[1 + slot] = entry["target"]
            for start, part in (
                (8 + 44 * slot, candidate.blob[:44]),
                (272 + 11 * slot, candidate.blob[44:55]),
                (338 + 11 * slot, candidate.blob[55:]),
            ):
                expected[start : start + len(part)] = part
            if after_party == bytes(expected):
                valid = True
                break
        if not valid or after_dex != bytes(expected_dex):
            raise JournalError("evolution differs from exact stat/name/move/dex result")
        if new.key in ({mon.key for i, mon in enumerate(before) if i != slot} | boxed):
            raise JournalError("evolution collides with another owned key")
    return {
        "kind": "evolution",
        "outcome": receipt["outcome"],
        "slot": slot,
        "map_id": a["point"]["map_id"],
        "call_frame": a["frame"],
        "return_frame": b["frame"],
        "receipt_digest": digest(receipt),
        "outgoing": {"key": old.key, "blob_hex": old.raw.hex().upper()},
        "incoming": {"key": new.key, "blob_hex": new.raw.hex().upper()},
        "table_target": entry["target"],
        "method": entry["method"],
    }


def validate(receipt, **scope):
    try:
        return _validate(receipt, **scope)
    except (PartyCodecError, KeyError, TypeError, IndexError, ValueError) as error:
        raise JournalError(str(error)) from error
