"""Strict, game-neutral RGBDS symbol parsing and standard GB ROM coordinates."""

from __future__ import annotations

import re
from typing import NamedTuple


class Symbol(NamedTuple):
    bank: int
    address: int


def parse_symbols(text: str) -> dict[str, Symbol]:
    """Parse rgblink .sym text, refusing malformed rows and ambiguous names.

    RAM bank numbers are retained. Names (including RGBDS Unicode escapes) are
    preserved verbatim. Numeric exported constants (hex value, space, name) are
    validated but omitted: they do not carry a bank/address or a memory region.
    """
    symbols = {}
    names = set()
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{2,4}):([0-9a-fA-F]{4})\s+([^\s;]+)", line)
        if match is None:
            constant = re.fullmatch(r"[0-9a-fA-F]{2,8}\s+([^\s;]+)", line)
            if constant is not None:
                name = constant.group(1)
                if name in names:
                    raise ValueError(f"duplicate RGBDS symbol {name!r} at line {line_number}")
                names.add(name)
                continue
            raise ValueError(f"malformed RGBDS symbol at line {line_number}: {raw!r}")
        bank, address, name = match.groups()
        if name in names:
            raise ValueError(f"duplicate RGBDS symbol {name!r} at line {line_number}")
        names.add(name)
        symbols[name] = Symbol(int(bank, 16), int(address, 16))
    if not symbols:
        raise ValueError("RGBDS symbol file contains no symbols")
    return symbols


def rom_offset(bank: int, address: int) -> int:
    """Flatten conventional ROM0 ($0000-$3fff) / ROMX ($4000-$7fff).

    Tiny/expanded ROM0 linker modes need a different explicitly qualified policy;
    RAM coordinates and contradictory bank/window pairs are never ROM offsets.
    """
    if type(bank) is not int or type(address) is not int or not 0 <= bank <= 0xFFFF:
        raise ValueError(f"invalid ROM coordinates: {bank!r}:{address!r}")
    if bank == 0 and 0 <= address < 0x4000:
        return address
    if bank > 0 and 0x4000 <= address < 0x8000:
        return bank * 0x4000 + address - 0x4000
    raise ValueError(f"non-ROM or contradictory coordinates: {bank:x}:{address:x}")
