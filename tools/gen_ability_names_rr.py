#!/usr/bin/env python3
"""Generate RR ability names from funnotbun sources.

Usage:
    python tools/gen_ability_names_rr.py
    python tools/gen_ability_names_rr.py --abilities-h path\to\abilities.h --names-string path\to\ability_name_table.string

By default, both inputs are fetched from the authoritative funnotbun raw GitHub URLs.
The generated table is printed to stdout and also written to server\rr_ability_names.py.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

ABILITIES_H_URL = (
    "https://raw.githubusercontent.com/funnotbun/funnotbun.github.io/"
    "main/data/abilities/abilities.h"
)
NAMES_STRING_URL = (
    "https://raw.githubusercontent.com/funnotbun/funnotbun.github.io/"
    "main/data/abilities/ability_name_table.string"
)
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "server" / "rr_ability_names.py"
NORMALIZED_NAME_ALIASES = {
    "neutralizinggas": "neutralisinggas",
    "zerotohero": "herotozero",
    "flamingsoul": "blazingsoul",
}


def read_text(source: str) -> str:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source) as response:
            return response.read().decode("utf-8")
    return Path(source).read_text(encoding="utf-8")


def normalize_name(name: str) -> str:
    return name.removeprefix("ABILITY_").removeprefix("NAME_").replace("_", "").lower()


def parse_abilities_h(text: str) -> dict[int, str]:
    normalized_to_raw: dict[str, str] = {}
    id_to_name: dict[int, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.split("//", 1)[0].strip()
        if not line.startswith("#define "):
            continue

        parts = line.split()
        if len(parts) < 3:
            continue

        constant, value_str = parts[1], parts[2]
        if not constant.startswith("ABILITY_") or constant == "ABILITY_NONE":
            continue

        try:
            ability_id = int(value_str, 0)
        except ValueError:
            continue

        if ability_id == 0:
            continue

        normalized = normalize_name(constant)
        other = normalized_to_raw.get(normalized)
        if other and other != constant:
            raise ValueError(
                f"Duplicate normalized abilities.h key '{normalized}': {other}, {constant}"
            )
        normalized_to_raw[normalized] = constant
        id_to_name.setdefault(ability_id, constant.removeprefix("ABILITY_"))

    return id_to_name


def parse_names_string(text: str) -> dict[str, str]:
    lines = text.splitlines()
    normalized_to_display: dict[str, str] = {}

    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line.startswith("#org @"):
            continue

        label = line[6:].strip()
        if label == "gAbilityNames" or not label.startswith("NAME_"):
            continue

        if index + 1 >= len(lines):
            raise ValueError(f"Missing display name after {raw_line!r}")

        display_name = lines[index + 1].strip()
        if display_name == "-------":
            continue

        normalized = normalize_name(label)
        other = normalized_to_display.get(normalized)
        if other and other != display_name:
            raise ValueError(
                f"Duplicate normalized ability_name_table.string key '{normalized}': "
                f"{other!r}, {display_name!r}"
            )
        normalized_to_display[normalized] = display_name

    return normalized_to_display


def build_rr_ability_names(abilities_h_text: str, names_string_text: str) -> dict[int, str]:
    id_to_constant = parse_abilities_h(abilities_h_text)
    normalized_to_display = parse_names_string(names_string_text)

    rr_ability_names: dict[int, str] = {}
    missing: list[str] = []

    for ability_id in sorted(id_to_constant):
        constant = id_to_constant[ability_id]
        normalized = normalize_name(constant)
        display_name = normalized_to_display.get(normalized)
        if not display_name:
            display_name = normalized_to_display.get(
                NORMALIZED_NAME_ALIASES.get(normalized, normalized)
            )
        if not display_name:
            missing.append(f"{ability_id}: {constant}")
            continue
        rr_ability_names[ability_id] = display_name

    if missing:
        raise ValueError(
            "Missing ability_name_table.string entries for abilities.h constants:\n  "
            + "\n  ".join(missing)
        )

    if len(rr_ability_names) < 200:
        raise ValueError(
            f"RR ability name coverage too low: expected at least 200 entries, got {len(rr_ability_names)}"
        )

    return rr_ability_names


def format_table(rr_ability_names: dict[int, str]) -> str:
    lines = [
        "# RR-specific ability names (generated from funnotbun/funnotbun.github.io)",
        "# Regenerate with: python tools/gen_ability_names_rr.py",
        "RR_ABILITY_NAMES: dict[int, str] = {",
    ]
    for ability_id, name in sorted(rr_ability_names.items()):
        escaped = name.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'    {ability_id}: "{escaped}",')
    lines.append("}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--abilities-h", default=ABILITIES_H_URL, help="Path or URL for abilities.h")
    parser.add_argument(
        "--names-string",
        default=NAMES_STRING_URL,
        help="Path or URL for ability_name_table.string",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rr_ability_names = build_rr_ability_names(
        read_text(args.abilities_h),
        read_text(args.names_string),
    )
    output = format_table(rr_ability_names)
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
