"""Read-only RR native-arena reference inventory, never a safety certificate.

The scanner inventories syntactically possible calls and literal references.
ROM data can resemble instructions; computed branches are not reconstructed.
Every candidate needs code-context review and supported-path runtime evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from array import array
from pathlib import Path

ROM_BASE = 0x08000000
ROM_SIZE = 32 * 1024 * 1024
KNOWN_ROMS = {
    "679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f": "rr41-base",
    "1e8f6e8957c1e8eb7ce2d2e349a7c335e48f13b7dd44bf81350dc1ade1a1ec04": "slink-rr-audit-baseline",
}
ENTRY_POINTS = {0x081E89F4: "_malloc_r", 0x081E8264: "_free_r"}
ARENA_START, ARENA_END = 0x0203F76C, 0x0203FBB0
PATCH_START, PATCH_END = 0x0203F800, 0x02040000


def hexaddr(value: int) -> str:
    return f"0x{value:08X}"


def sign_extend(value: int, bits: int) -> int:
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def thumb_bl_target(address: int, high: int, low: int) -> int | None:
    if high & 0xF800 != 0xF000 or low & 0xF800 != 0xF800:
        return None
    displacement = sign_extend(((high & 0x7FF) << 12) | ((low & 0x7FF) << 1), 23)
    return address + 4 + displacement


def arm_bl_target(address: int, instruction: int) -> int | None:
    # ARMv4T BL, excluding the reserved NV condition (later cores use it for BLX).
    if instruction & 0x0F000000 != 0x0B000000 or instruction >> 28 == 0xF:
        return None
    return address + 8 + (sign_extend(instruction & 0xFFFFFF, 24) << 2)


def reference_candidates(rom: bytes, *, targets=None, arena=None) -> dict:
    targets = ENTRY_POINTS if targets is None else targets
    start, end = (ARENA_START, ARENA_END) if arena is None else arena
    if len(rom) % 4:
        raise ValueError("ROM byte count must be divisible by four")
    halves = array("H")
    halves.frombytes(rom)
    if sys.byteorder != "little":
        halves.byteswap()
    calls, arena_loads = [], []
    for index, high in enumerate(halves[:-1]):
        address = ROM_BASE + index * 2
        if high & 0xF800 == 0xF000:
            target = thumb_bl_target(address, high, halves[index + 1])
            if target in targets:
                calls.append({"at": hexaddr(address), "isa": "thumb", "target": targets[target]})
        if high & 0xF800 == 0x4800:
            literal = ((address + 4) & ~3) + ((high & 0xFF) << 2)
            offset = literal - ROM_BASE
            if 0 <= offset <= len(rom) - 4:
                value = struct.unpack_from("<I", rom, offset)[0]
                if start <= value < end:
                    arena_loads.append({"at": hexaddr(address), "literal_at": hexaddr(literal),
                                        "value": hexaddr(value)})
    literals = []
    for index, (value,) in enumerate(struct.iter_unpack("<I", rom)):
        address = ROM_BASE + index * 4
        target = arm_bl_target(address, value)
        if target in targets:
            calls.append({"at": hexaddr(address), "isa": "arm", "target": targets[target]})
        if start <= value < end:
            literals.append({"at": hexaddr(address), "value": hexaddr(value)})
    pointers = []
    for target, name in sorted(targets.items()):
        for representation in (target, target | 1):
            needle = struct.pack("<I", representation)
            offset = rom.find(needle)
            while offset >= 0:
                pointers.append({"at": hexaddr(ROM_BASE + offset), "target": name,
                                 "value": hexaddr(representation), "aligned": offset % 4 == 0})
                offset = rom.find(needle, offset + 1)
    return {"direct_call_candidates": sorted(calls, key=lambda row: (row["at"], row["isa"])),
            "function_pointer_candidates": sorted(pointers, key=lambda row: (row["at"], row["value"])),
            "arena_literal_candidates": literals, "thumb_arena_load_candidates": arena_loads}


def audit(rom: bytes) -> dict:
    digest = hashlib.sha256(rom).hexdigest()
    if len(rom) != ROM_SIZE or digest not in KNOWN_ROMS:
        raise ValueError("unsupported ROM identity; this evidence tool accepts only the two pinned audit inputs")
    candidates = reference_candidates(rom)
    overlap_start, overlap_end = max(ARENA_START, PATCH_START), min(ARENA_END, PATCH_END)
    return {
        "schema": "slink-rr-arena-evidence-v1", "rom_sha256": digest,
        "rom_kind": KNOWN_ROMS[digest], "rom_size": len(rom),
        "scanner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "evidence_level": "static-reference-candidates", "release_ready": False,
        "arena_ownership": "not-established", "runtime_evidence": [],
        "allocator_metadata": {"start": hexaddr(ARENA_START), "end_exclusive": hexaddr(ARENA_END)},
        "slink_overlap": {"start": hexaddr(overlap_start), "end_exclusive": hexaddr(overlap_end),
                          "byte_count": max(0, overlap_end - overlap_start)},
        "entry_points": {name: hexaddr(address) for address, name in ENTRY_POINTS.items()},
        "counts": {key: len(value) for key, value in candidates.items()}, **candidates,
        "limitations": [
            "Syntactic candidates may occur in data or an incompatible instruction context.",
            "Computed branches, unaligned literals, Thumb tail branches and indirect dispatch are not a complete call graph.",
            "No candidate count, including zero, establishes allocator unreachability or free RAM.",
            "Supported campaign/scene entry and write traces plus ownership review remain required.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        source, target = args.rom.resolve(strict=True), args.output.resolve()
        if source == target:
            raise ValueError("output must not overwrite the input ROM")
        # Refuse an existing output rather than accidentally replacing another task's evidence.
        report = audit(source.read_bytes())
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except (OSError, ValueError) as exc:
        print(f"RR arena audit failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"output": str(target), "rom": report["rom_kind"],
                      "counts": report["counts"], "arena_ownership": report["arena_ownership"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
