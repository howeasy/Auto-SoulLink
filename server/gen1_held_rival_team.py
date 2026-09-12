"""Verify one pending replace_rival_team write under the battle_init hold, and its receipt.

P5-rival-team-executor.md sections 2 to 4. The checkpoint profile is
data/games/gen1_rby/rival_team_checkpoint.json (tools/gen_gen1_rival_team_checkpoint.py:
WRAM from the pinned pret symbols, ROM anchors from the verified write_safe profile). The
Lua twin drives lua/gen1_held_rival_team.lua; verify_battle_init_checkpoint mirrors its
check byte for byte, as gen1_held_faint.verify_checkpoint mirrors gen1_write_safety.lua.
"""
import json
import re
from pathlib import Path

from server.adapters import get_adapter
from server.gen1_held_faint import verify_owned_host
from server.gen1_party_codec import PartyCodec, PartyCodecError
from server.held_write_permit import VerifiedHeldWrite
from server.operation_scope import command_scope
from server.protocol import digest
from server.protocol_journal import JournalError

DATA = json.loads((Path(__file__).resolve().parents[1] / "data/games/gen1_rby/rival_team_checkpoint.json").read_text())
PROFILES = DATA["titles"]
SCHEMA = "rby-held-rival-evidence-v1"
INTENT = "rby-rival-team-intent-v1"
RECEIPT = "gen1-rival-team-receipt-v1"
COMMAND = "replace_rival_team"


def blobs_of(body):
    """The client rule (lua/clients/gen1_rby_client.lua:340-355): 1..6 blobs of 132 hex characters."""
    hexes = body.get("blobs_hex")
    if (not isinstance(hexes, list) or not 1 <= len(hexes) <= 6
            or any(not isinstance(h, str) or not re.fullmatch("[0-9A-Fa-f]{132}", h) for h in hexes)
            or body.get("n") != len(hexes)):
        raise JournalError("invalid complete rival payload")
    return [bytes.fromhex(h) for h in hexes]


def validate_party(body, variant):
    blobs = blobs_of(body)
    try:
        party = PartyCodec(variant).validate_party(blobs)
    except PartyCodecError as exc:
        raise JournalError(str(exc)) from exc
    if not any(mon.hp for mon in party):
        # StartBattle scans for the first living enemy with no exit (core.asm:139-150).
        raise JournalError("rival party needs a living member")
    return blobs, party


def expected_image(blobs):
    """The 67n+2 bytes writeEnemyParty writes, in write order (lua/memory_gb.lua:795-807): per mon
    the 44-byte struct, 11-byte OT, 11-byte nick (the blob itself) and the species-list byte; then
    the 0xFF terminator and wEnemyPartyCount."""
    return "".join(blob.hex().upper() + f"{blob[0]:02X}" for blob in blobs) + f"FF{len(blobs):02X}"


def validate_image(image, n):
    if (not isinstance(image, dict) or set(image) != {"count", "species_list", "image_hex"}
            or type(image["count"]) is not int or not 0 <= image["count"] <= 255
            or not isinstance(image["species_list"], list) or len(image["species_list"]) != min(image["count"], 6) + 1
            or any(type(v) is not int or not 0 <= v <= 255 for v in image["species_list"])
            or not isinstance(image["image_hex"], str) or not re.fullmatch("[0-9A-F]{" + str(2 * (67 * n + 2)) + "}", image["image_hex"])):
        raise JournalError("complete enemy party image required")
    return image


def rivals(variant):
    return get_adapter("gen1_rby", rom_type=variant.capitalize()).rival_trainer_ids()


def verify_battle_init_checkpoint(point, variant, trainer_id):
    if not isinstance(point, dict) or set(point) != {"pc", "sp", "rom", "system"}:
        raise JournalError("complete battle-init checkpoint required")
    p = PROFILES[variant]
    sp = point["sp"]
    if (type(point["pc"]) is not int or point["pc"] != p["irq_vector"] or type(sp) is not int
            or not p["stack_min"] <= sp <= p["stack_end"] - 1):
        raise JournalError("held CPU is not at the qualified battle-init checkpoint")
    rom = {}
    for i, value in enumerate((0xC3, p["vblank_entry"] & 255, p["vblank_entry"] >> 8)):
        rom[str(p["irq_vector"] + i)] = value
    for i, value in enumerate((0x3E, 1, 0xE0, p["vblank_flag"] & 255, 0x76, 0xF0, p["vblank_flag"] & 255, 0xA7)):
        rom[str(p["delay_frame"] + i)] = value
    if point["rom"] != rom or any(type(value) is not int for value in point["rom"].values()):
        raise JournalError("held checkpoint ROM instructions differ")
    fixed = {p["is_in_battle"]: p["trainer_battle"], p["enemy_mon_party_pos"]: 0xFF, p["cur_opponent"]: trainer_id,
             p["link_state"]: p["link_none"], p["battle_type"]: 0, p["vblank_flag"]: 1}
    expected = {str(addr) for addr in fixed} | {str(p["enemy_party_count"]), str(sp), str(sp + 1)}
    values = point["system"]
    if (not isinstance(values, dict) or set(values) != expected
            or any(type(v) is not int or not 0 <= v <= 255 for v in values.values())):
        raise JournalError("complete bounded checkpoint bytes required")
    if any(values[str(addr)] != value for addr, value in fixed.items()) or not 1 <= values[str(p["enemy_party_count"])] <= 6:
        raise JournalError("CPU is not inside the trainer battle-init window")
    if values[str(sp)] + 256 * values[str(sp + 1)] != p["delay_frame"] + 5:
        raise JournalError("main thread is not waiting in DelayFrame")


def verify(player, command, evidence, state, binding):
    """None for other commands; VerifiedHeldWrite for an exact rival swap at the battle-init hold."""
    body = command["body"]
    if body.get("cmd") != COMMAND:
        return None
    if (not isinstance(evidence, dict) or set(evidence) != {"schema", "command_id", "command_sequence", "context_generation",
            "final_sha1", "host", "checkpoint", "intent", "current"} or evidence["schema"] != SCHEMA):
        raise JournalError("complete held rival evidence required")
    metadata = verify_owned_host(player, command, evidence, state, binding)
    variant = metadata["gen1_metadata"]["cartridge"]["variant"]
    trainer = body.get("trainer_id")
    if type(trainer) is not int or trainer not in rivals(variant):
        raise JournalError("rival team swap targets a non-rival opponent")
    blobs, _ = validate_party(body, variant)
    verify_battle_init_checkpoint(evidence["checkpoint"], variant, trainer)
    intent = evidence["intent"]
    if (not isinstance(intent, dict) or set(intent) != {"schema", "trainer_id", "n", "before"} or intent["schema"] != INTENT
            or intent["trainer_id"] != trainer or intent["n"] != len(blobs)):
        raise JournalError("exact prepared rival intent required")
    before = validate_image(intent["before"], len(blobs))
    current = validate_image(evidence["current"], len(blobs))
    if current["image_hex"] not in (before["image_hex"], expected_image(blobs)):
        raise JournalError("rival readback diverged from prepared intent")
    return VerifiedHeldWrite(command_scope(command, binding, phase=COMMAND), digest(evidence), 1000, digest(state))


def verify_rival_team_receipt(body, receipt, *, variant):
    """The readback proves the written block, count and species list; the effect is informational."""
    if (not isinstance(receipt, dict) or set(receipt) != {"schema", "trainer_id", "before", "after"}
            or receipt["schema"] != RECEIPT or receipt["trainer_id"] != body.get("trainer_id")):
        raise JournalError("versioned rival team receipt required")
    blobs, _ = validate_party(body, variant)
    validate_image(receipt["before"], len(blobs))
    after = validate_image(receipt["after"], len(blobs))
    if (after["image_hex"] != expected_image(blobs) or after["count"] != len(blobs)
            or after["species_list"] != [blob[0] for blob in blobs] + [255]):
        raise JournalError("rival readback differs from the written party")
    return {"trainer_id": body["trainer_id"], "n": len(blobs), "species_list": after["species_list"][:-1]}
