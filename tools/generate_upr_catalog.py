"""Extract the entire settings bit layout from pinned UPR ZX 4.6.1 source.

Only format facts are generated. Generation admission policy lives separately.
The manually described packed integer expressions are checked by the source hash;
every one of the 408 bits must have exactly one owner, including reserved bits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_HASH = "60d7956fe074c95e9fdb939d07566315c6031102dbc92597b3cecad9d1a25178"
COMMIT = "7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c"


def extract(path):
    raw = Path(path).read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(raw).hexdigest() != SOURCE_HASH:
        raise ValueError("UPR Settings.java source pin differs")
    source = raw.decode("utf-8")
    start = source.index("    public String toString() {")
    encoder = source[start:source.index("        try {\n            byte[] romName", start)]
    sections = list(re.finditer(r"// (\d+)(?:\s*-\s*(\d+))?[: ]", encoder))
    fields, owned = {}, {}

    def add(name, kind, positions, **details):
        for byte, bit in positions:
            if (byte, bit) in owned:
                raise ValueError("overlapping setting bits: " + name)
            owned[byte, bit] = name
        if name in fields:
            if kind != "enum" or fields[name]["kind"] != "enum":
                raise ValueError("duplicate setting name: " + name)
            fields[name]["choices"].update(details["choices"])
            fields[name]["positions"].extend(positions)
        else:
            fields[name] = {"kind": kind, "positions": positions, **details}

    for index, match in enumerate(sections):
        byte = int(match[1])
        section = encoder[match.end():sections[index+1].start() if index+1 < len(sections) else len(encoder)]
        call = re.search(r"makeByteSelected\((.*?)\)", section, re.S)
        if not call:
            continue
        for bit, expression in enumerate(call[1].split(",")):
            expression = expression.strip()
            enum = re.fullmatch(r"(\w+) == (\w+)\.(\w+)", expression)
            positions = [[byte, bit]]
            if enum:
                add(enum[1], "enum", positions, choices={enum[3]: positions[0]}, java_type=enum[2])
            elif expression == "false":
                add(f"reserved_{byte}_{bit}", "reserved", positions)
            elif re.fullmatch(r"\w+", expression):
                add(expression, "boolean", positions)
            else:
                raise ValueError("unrecognized source expression: " + expression)

    def scalar(name, byte, bit, width, bias=0):
        add(name, "integer", [[byte+(bit+i)//8, (bit+i)%8] for i in range(width)], bias=bias)

    for slot, byte in enumerate((5, 7, 9)):
        scalar(f"customStarters[{slot}]", byte, 0, 16, 1)
    scalar("guaranteedMoveCount", 11, 6, 2, 2)
    for byte, flag, value, bias in (
        (12, "movesetsForceGoodDamaging", "movesetsGoodDamagingPercent", 0),
        (14, "trainersForceFullyEvolved", "trainersForceFullyEvolvedLevel", 0),
        (20, "tmsForceGoodDamaging", "tmsGoodDamagingPercent", 0),
        (22, "tutorsForceGoodDamaging", "tutorsGoodDamagingPercent", 0),
        (36, "trainersLevelModified", "trainersLevelModifier", -50),
        (38, "wildLevelsModified", "wildLevelModifier", -50),
        (43, "totemLevelsModified", "totemLevelModifier", -50),
        (47, "staticLevelModified", "staticLevelModifier", -50),
    ):
        add(flag, "boolean", [[byte, 7]])
        scalar(value, byte, 0, 7, bias)
    for name, byte in (("currentRestrictions", 28), ("currentMiscTweaks", 32)):
        add(name, "integer", [[b, bit] for b in range(byte+3, byte-1, -1) for bit in range(8)], bias=0)
    add("doubleBattleMode", "boolean", [[40, 0]])
    scalar("additionalBossTrainerPokemon", 40, 1, 3)
    scalar("additionalImportantTrainerPokemon", 40, 4, 3)
    add("weighDuplicateAbilitiesTogether", "boolean", [[40, 7]])
    scalar("additionalRegularTrainerPokemon", 41, 0, 3)
    add("auraMod", "enum", [[41, bit] for bit in (3, 4, 5)],
        choices={name: [41, bit] for name, bit in (("UNCHANGED", 3), ("RANDOM", 4), ("SAME_STRENGTH", 5))}, java_type="AuraMod")
    add("evolutionMovesForAll", "boolean", [[41, 6]])
    add("guaranteeXItems", "boolean", [[41, 7]])
    for name, byte in (("updateBaseStatsToGeneration", 44), ("updateMovesToGeneration", 45), ("selectedEXPCurve", 46)):
        scalar(name, byte, 0, 8)
    scalar("eliteFourUniquePokemonNumber", 50, 0, 3)
    scalar("minimumCatchRateLevel", 50, 3, 3, 1)
    for byte in range(51):
        for bit in range(8):
            if (byte, bit) not in owned:
                add(f"reserved_{byte}_{bit}", "reserved", [[byte, bit]])
    assert len(owned) == 408
    return {"schema": "slink-upr-layout-v1", "version": 322, "upr_version": "4.6.1", "data_bytes": 51,
            "source_commit": COMMIT, "settings_source_sha256": SOURCE_HASH,
            "fields": dict(sorted(fields.items()))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    options = parser.parse_args()
    output = ROOT/"data/upr_zx_4_6_1_settings.json"
    output.write_text(json.dumps(extract(options.source), indent=2)+"\n", encoding="utf-8")
    print(output)
