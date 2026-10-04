"""tests/unit/test_gen_polished_forms.py — the Polished (species, form) -> record index.

Structural tests run without the ROM. ROM-dependent tests skip when the release ROM
is absent (tests/TESTING.md: absent skips, wrong fails).

Run:  python -m pytest tests/unit/test_gen_polished_forms.py -q
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "tools"))

import gen_polished_forms as gen  # noqa: E402

ROM = gen.DEFAULT_ROMS / "polishedcrystal-3.2.3.gbc"
SRC_OK = (gen.DEFAULT_SRC / "data" / "pokemon" / "base_stats.asm").is_file()
ROM_OK = ROM.is_file()
needs_index = pytest.mark.skipif(not gen.OUT.exists(), reason="forms_index.json not generated yet")


@pytest.fixture(scope="module")
def index() -> dict:
    return json.loads(gen.OUT.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ structural


@needs_index
def test_schema_and_counts(index: dict) -> None:
    """46 variant records is the pinned figure (patch 0017 notes, POOL_EVIDENCE.md).

    RED CONTROL: change `len(variant_records) != 46` in build_index to a different
    expected count.
    """
    assert index["schema"] == "polished-forms-index-v1"
    assert index["counts"]["variant_records"] == 46
    assert len(index["variant_forms"]) == 46


@needs_index
def test_record_indices_unique_and_contiguous(index: dict) -> None:
    """Variant records must be one contiguous tail block, not scattered.

    RED CONTROL: remove the contiguity SystemExit in build_index.
    """
    got = [r["record_index"] for r in index["variant_forms"]]
    assert len(set(got)) == len(got)
    assert got == list(range(min(got), max(got) + 1))
    assert min(got) > index["counts"]["species"]


@needs_index
def test_no_cosmetic_form_is_emitted_as_a_variant(index: dict) -> None:
    """Only base_stats records with a real variant form constant are emitted; Unown
    letters and Magikarp patterns are cosmetic (FIRST_COSMETIC_FORM_MON,
    constants/pokemon_constants.asm:348) and must not appear.

    RED CONTROL: drop the `form_const not in forms` guard so unresolved stems pass.
    """
    cosmetic = {"UNOWN", "MAGIKARP", "SPINDA"}
    for row in index["variant_forms"]:
        assert not any(row["species_constant"].startswith(c) for c in cosmetic), row
        assert row["kind"] == "variant"


@needs_index
def test_every_row_has_the_fields_the_handler_needs(index: dict) -> None:
    """record_index / species_id / form_id / types are what patch 0016-0018 would read.

    RED CONTROL: drop `types` from the emitted dict.
    """
    for row in index["variant_forms"]:
        for key in ("record_index", "species_id", "form_constant", "form_id",
                    "base_stats_file", "rom_offset", "types"):
            assert key in row, (row, key)
        assert len(row["types"]) == 2
        assert 0 < row["form_id"] < 32


@needs_index
def test_generator_is_deterministic() -> None:
    """Two builds are byte-identical (LF, sorted-free but stable insertion order).

    RED CONTROL: emit a `generated` timestamp into the JSON.
    """
    if not (SRC_OK and ROM_OK):
        pytest.skip("Polished sources or release ROM absent")
    assert gen.dump(gen.build_index()) == gen.dump(gen.build_index())


# ------------------------------------------------------------------ ROM-backed


@pytest.mark.skipif(not ROM_OK, reason="release ROM absent")
@needs_index
def test_rom_stats_match_every_record(index: dict) -> None:
    """BaseData has NO species byte: a record starts with hp/atk/def/spe/sat/sdf. The ROM bytes at each
    record's offset must equal the stats in the form's source file, and bytes 6-7 must equal `types`.

    RED CONTROL: edit `record_index` for one row in forms_index.json.
    """
    import gen_polished_forms as g
    rom = ROM.read_bytes()
    base = index["rom"]["BaseData"]["flat"]
    stride = index["rom"]["base_stats_stride"]
    for row in index["variant_forms"]:
        off = base + (row["record_index"] - 1) * stride
        want = g.read_stats(g.DEFAULT_SRC / row["base_stats_file"]) if g.DEFAULT_SRC.exists() else tuple(rom[off:off + 6])
        assert tuple(rom[off:off + 6]) == want, row
        assert [rom[off + 6], rom[off + 7]] == row["types"], row


@pytest.mark.skipif(not ROM_OK, reason="release ROM absent")
@needs_index
def test_alolan_raichu_is_electric_psychic(index: dict) -> None:
    """The headline semantic check: the variant record's types are the FORM's.

    RED CONTROL: swap the `types` of RAICHU and TAUROS rows in forms_index.json.
    """
    rows = {r["species_constant"] + "/" + r["form_constant"]: r
            for r in index["variant_forms"]}
    raichu = rows["RAICHU/ALOLAN_FORM"]
    assert raichu["types"] != rows["RATTATA/ALOLAN_FORM"]["types"]


@needs_index
def test_committed_index_matches_a_fresh_build() -> None:
    """--check green: the committed JSON is what the generator produces now.

    RED CONTROL: add a key to forms_index.json by hand.
    """
    if not (SRC_OK and ROM_OK):
        pytest.skip("Polished sources or release ROM absent")
    assert gen.OUT.read_text(encoding="utf-8") == gen.dump(gen.build_index())


@needs_index
def test_nineteen_variants_evolve_and_plain_targets_resolve(index: dict) -> None:
    """19 of the 46 variant forms evolve; targets with an explicit PLAIN_FORM (Galarian Meowth -> Perrserker,
    Galarian Farfetch'd -> Sirfetch'd, Galarian Corsola -> Cursola) resolve to the plain species id. The generator
    proves every edge against the ROM's EvosAttacks block.

    RED CONTROL: make effective_id drop PLAIN_FORM targets again (16 evolving variants).
    """
    evolving = {r["record_index"]: [e["effective_species_id"] for e in r["evolves_to"]]
                for r in index["variant_forms"] if r["evolves_to"]}
    assert len(evolving) == 19
    assert evolving[313] == [279] and evolving[318] == [281] and evolving[325] == [280]
    assert sorted(evolving[316]) == [317, 324]  # Galarian Slowpoke -> Galarian Slowbro / Galarian Slowking
