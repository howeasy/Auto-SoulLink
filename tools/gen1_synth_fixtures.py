"""Disclosed O-33 Gen 1 setup saves; only catch/explode behavior runs natively."""
from __future__ import annotations

import hashlib

if __package__:
    from .gen1_fixtures import qualify
else:
    from gen1_fixtures import qualify

from server.adapters import gen1_codec as codec

EXPLODE_BALLS = 20
TITLES = frozenset(("red", "blue", "purered", "pureblue", "puregreen"))


def build_explode_synth(title: str, source: bytes, rom: bytes) -> tuple[bytes, dict]:
    """Derive from a qualified played save, changing one quantity and its checksum."""
    if title not in TITLES:
        raise ValueError(f"unsupported explode setup title: {title}")
    problems = qualify(source, rom)
    if problems:
        raise ValueError(f"base fixture does not qualify: {problems}")
    layout = codec.for_foundation("gen1_purergb" if title.startswith("pure") else "gen1_rby")
    count = source[layout.bag_count]
    if count > layout.bag_capacity or source[layout.bag_count + 1 + count * 2] != 0xFF:
        raise ValueError("invalid source bag count/terminator")
    slots = [layout.bag_count + 2 + slot * 2 for slot in range(count)
             if source[layout.bag_count + 1 + slot * 2] == codec.POKE_BALL]
    if len(slots) != 1 or not 1 <= source[slots[0]] <= 99:
        raise ValueError("source must contain one nonempty Poke Ball stack")
    quantity = slots[0]
    output = bytearray(source)
    output[quantity] = EXPLODE_BALLS
    start, end = layout.sram_layout["sPlayerName"], layout.sram_layout["sMainDataCheckSum"]
    output[end] = codec.sav_checksum(output[start:end])
    result = bytes(output)
    problems = qualify(result, rom)
    if problems or not layout.verify_bank1(result):
        raise ValueError(f"derived fixture does not qualify: {problems or ['checksum']}")
    return result, {
        "SYNTH": True, "recipe": "explode_balls", "title": title, "behavior": "native",
        "balls_before": source[quantity], "balls_after": EXPLODE_BALLS,
        "base_sha256": hashlib.sha256(source).hexdigest(),
        "fixture_sha256": hashlib.sha256(result).hexdigest(),
        "rom_sha1": hashlib.sha1(rom).hexdigest(),
    }
