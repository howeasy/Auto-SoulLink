"""Search exact GBA ROM anchors; stdout only, never silently choose an occurrence."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROM_BASE = 0x08000000
ROM_SPECS = {
    "fr": ("gen3_frlg", "firered", "clean",
           Path("E:/Google Drive/SLink/Pokemon - FireRed Version (USA).gba"),
           "41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc"),
    "lg": ("gen3_frlg", "leafgreen", "clean",
           Path("E:/Google Drive/SLink/Pokemon - LeafGreen Version (USA).gba"),
           "574fa542ffebb14be69902d1d36f1ec0a4afd71e"),
    "rr": ("gen3_rr", "radical_red", "clean",
           Path("E:/Google Drive/SLink/Pokemon - Radical Red.gba"),
           "964f951a0fdaf209e4ea1344883ef0d557bb3a80"),
    "rr_companion": ("gen3_rr", "radical_red", "companion",
                     ROOT / "patch/build/slink_RR.gba",
                     "ea5352f8a3b9073f8ae20870ad12857925d442cd"),
}


def parse_symbols(text: str) -> dict[str, dict]:
    """Read local AND global nonempty ROM functions from agbcc's symbol output."""
    result, ambiguous = {}, set()
    for line, raw in enumerate(text.splitlines(), 1):
        match = re.fullmatch(r"([0-9a-fA-F]{8})\s+[lg]\s+([0-9a-fA-F]{8})\s+(\S+)", raw.strip())
        if not match:
            continue
        address, size, name = match.groups()
        address, size = int(address, 16), int(size, 16)
        if not ROM_BASE <= address < 0x0A000000 or not size:
            continue
        if name in result:
            ambiguous.add(name)
        result[name] = {"address": address, "size": size, "line": line}
    for name in ambiguous:
        del result[name]  # callers may not guess between same-named local symbols
    return result


def decode_thumb_detour(rom: bytes, address: int) -> dict:
    """Decode exactly Thumb LDR literal; BX same low register, without guessing."""
    offset = address - ROM_BASE
    if address % 2 or not 0 <= offset <= len(rom) - 4:
        raise ValueError("detour entry outside ROM or unaligned")
    ldr = int.from_bytes(rom[offset:offset + 2], "little")
    bx = int.from_bytes(rom[offset + 2:offset + 4], "little")
    register = (ldr >> 8) & 7
    if ldr & 0xF800 != 0x4800 or bx != 0x4700 | (register << 3):
        raise ValueError("not a Thumb literal-load/BX-same-register detour")
    literal = ((address + 4) & ~3) + (ldr & 255) * 4
    flat = literal - ROM_BASE
    if not 0 <= flat <= len(rom) - 4:
        raise ValueError("detour literal outside ROM")
    raw = int.from_bytes(rom[flat:flat + 4], "little")
    target = raw & ~1
    if not raw & 1 or not ROM_BASE <= target < ROM_BASE + len(rom):
        raise ValueError("detour target not Thumb ROM code")
    return {"address": address, "register": register, "literal_address": literal,
            "literal_value": raw, "target": target,
            "instruction_hex": rom[offset:offset + 4].hex().upper(),
            "literal_hex": rom[flat:flat + 4].hex().upper()}


def pattern_bytes(text: str) -> bytes:
    data = bytes.fromhex(text)
    if not 8 <= len(data) <= 16:
        raise ValueError("anchor must contain 8..16 exact bytes")
    return data


def find_offsets(rom: bytes, pattern: bytes) -> list[int]:
    if not pattern:
        raise ValueError("empty pattern")
    result, start = [], 0
    while (offset := rom.find(pattern, start)) >= 0:
        result.append(offset)
        start = offset + 1  # include overlapping matches
    return result


def instruction_offsets(data: bytes, mode: str) -> set[int]:
    """Thumb-1 BL pairs are indivisible; this checks geometry, NOT code identity."""
    if mode == "arm":
        return set(range(0, len(data) - 3, 4))
    if mode != "thumb":
        raise ValueError("mode must be thumb or arm")
    offsets, pos = set(), 0
    while pos + 2 <= len(data):
        half = int.from_bytes(data[pos:pos + 2], "little")
        offsets.add(pos)
        if half & 0xF800 == 0xF000:
            if pos + 4 > len(data) or int.from_bytes(data[pos + 2:pos + 4], "little") & 0xF800 != 0xF800:
                raise ValueError("truncated/invalid Thumb-1 BL pair")
            pos += 4
        else:
            pos += 2
    return offsets


def make_site(rom: bytes, offset: int, pattern: bytes, *, capture_offset: int = 0,
              mode: str = "thumb", symbol: str = "", point: list[str] | None = None) -> dict:
    alignment = 2 if mode == "thumb" else 4
    if offset < 0 or offset % alignment or capture_offset < 0 or capture_offset % alignment:
        raise ValueError("unaligned or negative anchor/capture")
    if rom[offset:offset + len(pattern)] != pattern:
        raise ValueError("anchor differs from ROM or extends beyond ROM")
    if capture_offset not in instruction_offsets(pattern, mode):
        raise ValueError("capture is outside anchor or inside an instruction")
    return {"symbol": symbol, "mode": mode, "address": ROM_BASE + offset,
            "rom_offset": offset, "capture_offset": capture_offset,
            "expected_hex": pattern.hex().upper(), "point": point or []}


def load_rom(name: str, path: Path | None = None) -> bytes:
    spec = ROM_SPECS[name]
    rom = (path or spec[3]).read_bytes()
    if hashlib.sha1(rom).hexdigest() != spec[4]:
        raise ValueError(f"{name}: ROM SHA-1 differs from admitted research pin")
    return rom


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pattern", help="8..16 bytes of exact hex")
    parser.add_argument("--rom", action="append", help="fr/lg/rr/rr_companion or a ROM path; default all four")
    parser.add_argument("--capture-offset", type=lambda x: int(x, 0), default=0)
    parser.add_argument("--mode", choices=("thumb", "arm"), default="thumb")
    parser.add_argument("--symbol", default="candidate")
    parser.add_argument("--symbol-file", type=Path, help="optional .sym to bounds-check --symbol")
    args = parser.parse_args()
    try:
        pattern = pattern_bytes(args.pattern)
        rows = {}
        for item in args.rom or list(ROM_SPECS):
            rom = load_rom(item) if item in ROM_SPECS else Path(item).read_bytes()
            offsets = find_offsets(rom, pattern)
            row = {"offsets": offsets, "offsets_hex": [hex(x) for x in offsets],
                   "rom_sha1": hashlib.sha1(rom).hexdigest(), "status": "UNVERIFIED",
                   "reason": "byte search alone does not establish semantic capture"}
            if len(offsets) == 1:
                row["site"] = make_site(rom, offsets[0], pattern, capture_offset=args.capture_offset,
                                        mode=args.mode, symbol=args.symbol)
                if args.symbol_file:
                    symbol = parse_symbols(args.symbol_file.read_text())[args.symbol]
                    pc = row["site"]["address"] + args.capture_offset
                    if not symbol["address"] <= pc < symbol["address"] + symbol["size"]:
                        raise ValueError("capture outside symbol function")
                    row["site"]["function"] = symbol
            rows[item] = row
        print(json.dumps(rows, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
