"""Compiled expansion wild-table readback, separate from source projection and live checks."""

import json

import pytest

from tools import gen_gen3_profile as profile


ROOT = profile.REPO
OUT = ROOT / "data/games/gen3_exp/28877d73/expansion_encounters_rom_receipt.json"


def test_compiled_wild_table_matches_source_set_zero_and_keeps_duplicate_headers():
    from tools import verify_gen3_exp_wild as wild

    receipt = json.loads(OUT.read_text(encoding="utf-8"))
    assert wild.build() == receipt
    assert receipt["evidence"] == "COMPILED_ROM_SOURCE_READBACK"
    assert receipt["header_count"] == 124
    assert receipt["terminator_count"] == 1
    assert receipt["altering_cave_header_count"] == 9
    assert receipt["source_projection_set"] == 0
    assert receipt["source_projection_match"] is True
    assert receipt["live_verified"] is False


def test_compiled_wild_table_refuses_corrupt_descriptor_pointer():
    from tools import verify_gen3_exp_wild as wild

    context = profile.expansion_inputs(artifacts=ROOT / ".cache/expansion-output/reference")
    source = ROOT / ".cache/expansion-src"
    changed = bytearray(context["rom"])
    first_header = profile.expansion_symbol(context, "gWildMonHeaders")["address"] - 0x08000000
    changed[first_header + 4:first_header + 8] = (0x02000000).to_bytes(4, "little")
    with pytest.raises(ValueError, match="pointer|descriptor"):
        wild.readback(bytes(changed), context, source)
