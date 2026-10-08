"""Re-derive the Gen 2 coverage map's protocol SHA256 pins.

Usage: python tools/gen2_coverage_map_pin.py [--check | --write]
The default check prints each pin and exits 1 if stale. --write replaces only
protocol hash literals and prints a unified diff; all other bytes, including
line endings, stay untouched. --protocol and --map allow auditing scratch copies.

Like tools/coverage_map.py's release lane, hash read_bytes(), not normalised
text: converting protocol.md from LF to CRLF changes its digest. This tool does
not validate coverage or re-pin requirements, artifact policy, or receipts.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/protocol.md"
MAP = ROOT / "docs/gen2/gen2_coverage_map.md"
# Match the labelled Markdown table cell and JSON input pin, not other digests
# which happen to have the same value. Operate on bytes to preserve mixed EOLs.
PATTERNS = (
    re.compile(rb'(?m)^\|[ \t]*protocol[ \t]*\|[ \t]*(?P<hash>[0-9a-fA-F]{64})(?=[ \t]*\|)'),
    re.compile(rb'(?m)^[ \t]*"protocol"[ \t]*:[ \t]*"(?P<hash>[0-9a-fA-F]{64})(?=")'),
)


@dataclass(frozen=True)
class Pin:
    start: int
    end: int
    line: int
    value: str


def pins(raw: bytes) -> list[Pin]:
    groups = [list(pattern.finditer(raw)) for pattern in PATTERNS]
    if not all(groups):
        raise ValueError("map must contain both a protocol table pin and a protocol JSON pin")
    return sorted((Pin(match.start("hash"), match.end("hash"),
                       raw.count(b"\n", 0, match.start("hash")) + 1,
                       match.group("hash").decode("ascii"))
                   for matches in groups for match in matches), key=lambda pin: pin.start)


def report(path: Path, found: list[Pin], digest: str) -> bool:
    stale = False
    for pin in found:
        status = "CURRENT" if pin.value == digest else "STALE"
        stale |= status == "STALE"
        print(f"{status} | {path}:{pin.line} | {pin.value}")
    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="check pins without editing (default)")
    mode.add_argument("--write", action="store_true", help="replace only protocol hash literals")
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--map", type=Path, default=MAP)
    args = parser.parse_args(argv)
    try:
        digest = hashlib.sha256(args.protocol.read_bytes()).hexdigest()
        raw = args.map.read_bytes()
        found = pins(raw)
        print(f"protocol SHA256 (raw bytes): {digest}")
        print("STATUS | FILE:LINE | PIN")
        stale = report(args.map, found, digest)
        if not args.write or not stale:
            return int(stale)
        updated = bytearray(raw)
        for pin in found:
            updated[pin.start:pin.end] = digest.encode("ascii")
        # Render before writing: malformed UTF-8 must not leave an edited map
        # behind with an error instead of the promised diff.
        diff = "".join(difflib.unified_diff(
            raw.decode("utf-8").splitlines(keepends=True),
            updated.decode("utf-8").splitlines(keepends=True),
            fromfile=str(args.map), tofile=str(args.map) + " (updated)"))
        args.map.write_bytes(updated)
        print(diff, end="" if diff.endswith("\n") else "\n")
        print("After write:")
        report(args.map, pins(updated), digest)
        return 0
    except (OSError, ValueError) as exc:
        print(f"Coverage protocol pin refused: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
