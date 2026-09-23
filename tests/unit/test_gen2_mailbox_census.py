"""Gen 2 SLink mailbox writer-exclusion census (card P4.1b, owner ruling O-27).

The real-title tests are the exit evidence: all three built titles must come back PROVEN
against the pinned pokecrystal/pokegold decomps. The control tests are the falsifier this
card requires (docs/gen2/reviews/P4_PLAN_2026-09-23.md P4.1b): they patch a COPY of a small
synthetic source corpus, never the real checkout, with one added bulk write and one
hard-coded literal address, and assert the census goes red and names the exact writer -
then assert reverting the patch goes back to green.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools import gen2_mailbox_census as census_tool
from tools.gen2_mailbox_census import (
    MAILBOX_SPANS,
    Symbol,
    _next_wram0_symbol_gap,
    _resolve_address,
    _resolve_length,
    census,
    neighbours,
    read_sources,
    region_bounds,
    run_title,
)

REPO = Path(__file__).resolve().parents[2]

# A small, self-contained fake WRAM0: 0xC000-0xD000, span 0xC100-0xC110 (16 bytes), matching
# the real evidence's shape (an EMPTY linker gap with no symbol inside it) without needing a
# real pinned checkout. (start, end_exclusive) - the internal convention `census()` builds
# from `region_bounds()`'s (start, size), not that same (start, size) shape itself.
FAKE_WRAM0 = (0xC000, 0xD000)
FAKE_SPAN = (0xC100, 0xC110)
FAKE_MAP = {
    "banks": [{"type": "WRAM0", "bank": 0, "start": 0xC000, "end_exclusive": 0xD000, "size": 0x1000}],
    "gaps": [{"type": "WRAM0", "start": 0xC100, "end_exclusive": 0xC110}],
}
FAKE_SYMBOLS = {
    "wFoo": Symbol(0, 0xC000), "wFooEnd": Symbol(0, 0xC010),
    "wBar": Symbol(0, 0xC0F0),  # 16 bytes below the span: a literal length of 0x20 reaches it
    "wBaz": Symbol(0, 0xC0FE),  # 2 bytes below the span, no closer neighbour before it
}
CLEAN_SOURCE = {
    "engine/safe.asm": (
        "SafeClear::\n"
        "\tld hl, wFoo\n"
        "\tld bc, wFooEnd - wFoo\n"
        "\txor a\n"
        "\tcall ByteFill\n"
    ),
}


def _run(sources):
    return census("faketitle", FAKE_SPAN, FAKE_SYMBOLS, FAKE_MAP, sources)


def test_clean_fixture_is_proven():
    result = _run(CLEAN_SOURCE)
    assert result["verdict"] == "PROVEN"
    assert result["w1_span_empty_in_map"] is True
    assert result["w2_literal_or_arithmetic_hits"] == []
    assert result["violations"] == []
    assert result["unproven_writers"] == []


def test_planted_bulk_write_is_flagged_and_reverts(tmp_path):
    """CONTROL: one added ByteFill with an exact, resolvable length reaching the span."""
    patched_dir = tmp_path / "patched_pokecrystal"
    patched_dir.mkdir()
    (patched_dir / "engine").mkdir()
    (patched_dir / "engine/safe.asm").write_text(CLEAN_SOURCE["engine/safe.asm"], "utf-8")
    (patched_dir / "engine/planted.asm").write_text(
        "PlantedOverrun::\n"
        "\tld hl, wBar\n"
        "\tld bc, $20\n"
        "\txor a\n"
        "\tcall ByteFill\n",
        "utf-8",
    )

    patched_sources = read_sources(patched_dir)  # exercises the real (non-git) read path
    result = _run(patched_sources)
    assert result["verdict"] == "UNPROVEN"
    assert len(result["violations"]) == 1
    violation = result["violations"][0]
    assert violation["file"] == "engine/planted.asm"
    assert violation["dest_expr"] == "wBar"
    assert violation["length_method"] == "EXACT_LITERAL"

    # Revert: remove the plant, the same corpus (read the same way) goes back to green.
    (patched_dir / "engine/planted.asm").unlink()
    reverted_sources = read_sources(patched_dir)
    reverted = _run(reverted_sources)
    assert reverted["verdict"] == "PROVEN"


def test_planted_hardcoded_address_is_flagged_and_reverts():
    """CONTROL: one added literal address ($xxxx) inside the span."""
    violated = {**CLEAN_SOURCE, "engine/planted_literal.asm":
                "PlantedLiteral::\n\tld hl, $C105\n\tld [hl], 0\n"}
    result = _run(violated)
    assert result["verdict"] == "UNPROVEN"
    assert len(result["w2_literal_or_arithmetic_hits"]) == 1
    hit = result["w2_literal_or_arithmetic_hits"][0]
    assert hit["file"] == "engine/planted_literal.asm"
    assert hit["value"] == "0xc105"

    reverted = _run(CLEAN_SOURCE)
    assert reverted["verdict"] == "PROVEN"


def test_unresolvable_length_reaching_the_span_is_unproven_not_silently_passed():
    """A counted write whose length can't be resolved and whose upper bound reaches the span
    must be UNPROVEN, never silently accepted as safe."""
    violated = {**CLEAN_SOURCE, "engine/opaque.asm":
                "OpaqueFill::\n\tld hl, wBaz\n\tld bc, SOME_UNKNOWN_LENGTH\n\tcall ByteFill\n"}
    result = _run(violated)
    assert result["verdict"] == "UNPROVEN"
    unproven = [w for w in result["unproven_writers"] if w["file"] == "engine/opaque.asm"]
    assert len(unproven) == 1
    assert unproven[0]["length_method"] == "STRUCTURAL_NEXT_SYMBOL_BOUND"


def test_symbol_arithmetic_into_span_is_flagged():
    violated = {**CLEAN_SOURCE, "engine/arith.asm": "\tld hl, wBar + 20\n"}
    result = _run(violated)
    assert result["verdict"] == "UNPROVEN"
    assert any(hit["kind"] == "SYMBOL_ARITHMETIC" for hit in result["w2_literal_or_arithmetic_hits"])


def test_region_wide_wram0_clear_outside_init_is_not_silently_accepted():
    """Only the known Init lifecycle clear is accepted; the same shape elsewhere must not be."""
    violated = {**CLEAN_SOURCE, "engine/rogue_clear.asm":
                "RogueClear::\n\tld hl, STARTOF(WRAM0)\n\tld bc, SIZEOF(WRAM0)\n\tcall ByteFill\n"}
    result = _run(violated)
    assert result["verdict"] == "UNPROVEN"
    assert any(w["file"] == "engine/rogue_clear.asm" and w["verdict"] == "VIOLATION"
               for w in result["violations"])


def test_neighbours_and_next_symbol_gap():
    # wBaz (0xc0fe) sits closer to the span than wBar (0xc0f0): it is the true boundary symbol.
    assert neighbours(FAKE_SYMBOLS, FAKE_WRAM0, FAKE_SPAN[0]) == ["wBaz"]
    assert _next_wram0_symbol_gap(0xC010, FAKE_SYMBOLS, FAKE_WRAM0) == 0xC0F0 - 0xC010


def test_resolve_address_and_length_forms():
    bounds = region_bounds(FAKE_MAP)
    assert _resolve_address("wFoo", FAKE_SYMBOLS, bounds) == 0xC000
    assert _resolve_address("wFoo + 4", FAKE_SYMBOLS, bounds) == 0xC004
    assert _resolve_address("STARTOF(WRAM0)", FAKE_SYMBOLS, bounds) == 0xC000
    assert _resolve_address("$c105", FAKE_SYMBOLS, bounds) == 0xC105
    assert _resolve_length("wFooEnd - wFoo", FAKE_SYMBOLS, bounds) == (0x10, "EXACT_SYMBOL_DIFF")
    assert _resolve_length("SIZEOF(WRAM0)", FAKE_SYMBOLS, bounds) == (0x1000, "EXACT_REGION")
    assert _resolve_length("$20", FAKE_SYMBOLS, bounds) == (0x20, "EXACT_LITERAL")
    assert _resolve_length("SOME_UNKNOWN_LENGTH", FAKE_SYMBOLS, bounds) == (None, None)


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_real_pinned_title_mailbox_is_proven(title):
    """Exit evidence: W1-W5 green for all three built titles against the pinned decomps."""
    result = run_title(REPO, title)
    assert result["w1_span_empty_in_map"] is True, result
    assert result["w2_literal_or_arithmetic_hits"] == [], result["w2_literal_or_arithmetic_hits"]
    assert result["unproven_writers"] == [], result["unproven_writers"]
    assert result["violations"] == [], result["violations"]
    assert result["verdict"] == "PROVEN"
    span_start = int(result["span"]["start"], 16)
    assert MAILBOX_SPANS[title] == (span_start, int(result["span"]["end_exclusive"], 16))


def test_committed_report_matches_the_tool(tmp_path):
    """The committed data/gen2/mailbox_census.json is not stale."""
    assert census_tool.main(["--root", str(REPO), "--check"]) == 0
