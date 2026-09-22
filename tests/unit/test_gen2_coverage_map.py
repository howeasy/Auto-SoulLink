"""Gen 2-specific coverage-map controls: sync checks against the real,
checked-in docs/gen2/gen2_coverage_map.md. Generation-neutral contract
controls live in tests/unit/test_coverage_map_contract.py.
"""
from __future__ import annotations

import pathlib

from tools import coverage_map as coverage


# --- F-3 per-family table/JSON binding: the two require explicit sync. ---
# GEN2_MAP_PATH is the real coverage map, not a synthetic fixture: these two
# tests catch a hand-edit to only the table or only the JSON F-3 cell.

GEN2_MAP_PATH = pathlib.Path(__file__).resolve().parents[2] / "docs" / "gen2" / "gen2_coverage_map.md"

F3_FAMILIES = [
    "battle_start_wild", "battle_start_trainer", "battle_end_result", "capture_party",
    "capture_box", "player_faint", "poison_faint", "whiteout", "evolution_publish",
    "npc_trade", "link_trade", "pc_deposit", "pc_withdraw", "pc_release", "pc_changebox",
    "map_load", "ball_received", "save_success", "continue", "new_game", "soft_reset",
    "egg_hatch",
]


def _f3_table_rows():
    """Parse the F-3 Markdown table's four columns, keyed by family."""
    doc_lines = GEN2_MAP_PATH.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(doc_lines) if line.startswith("## F-3"))
    end = next((i for i in range(start + 1, len(doc_lines)) if doc_lines[i].startswith("## ")), len(doc_lines))
    section = doc_lines[start:end]
    rows = {}
    for line in section:
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0] in ("Family", "") or set(cells[0]) == {"-"}:
            continue
        if cells[0] not in F3_FAMILIES:
            continue
        rows[cells[0]] = {"positive": cells[1], "refusal": cells[2], "witness": cells[3]}
    assert set(rows) == set(F3_FAMILIES), f"table family rows do not match the known 22: {sorted(rows)}"
    return rows


def _split_family_field(text, families, delim):
    """Split one JSON F-3 field ("fam1<delim>text1; fam2<delim>text2; ...") by family."""
    positions = []
    search_from = 0
    for family in families:
        needle = family + delim
        idx = text.index(needle, search_from)
        positions.append((family, idx + len(needle)))
        search_from = idx + len(needle)
    result = {}
    for i, (family, content_start) in enumerate(positions):
        end = (text.index(families[i + 1] + delim, content_start) if i + 1 < len(families) else len(text))
        segment = text[content_start:end]
        if segment.endswith("; "):
            segment = segment[:-2]
        result[family] = segment
    return result


def _f3_json_mapping():
    document = coverage.load_document(GEN2_MAP_PATH)
    rows = {row["id"]: row for row in document["rows"]}
    return rows["requirement:F-3"]["mapping"]


def test_f3_table_and_json_agree_for_all_22_families():
    table = _f3_table_rows()
    mapping = _f3_json_mapping()
    stimulus_by_family = _split_family_field(mapping["stimulus"]["description"], F3_FAMILIES, ": ")
    positive_by_family = _split_family_field(mapping["positive_control"], F3_FAMILIES, ": ")
    refusal_by_family = _split_family_field(mapping["refusal_control"], F3_FAMILIES, ": ")
    witness_by_family = _split_family_field(mapping["oracle"], F3_FAMILIES, " => ")
    for family in F3_FAMILIES:
        reconstructed_positive = stimulus_by_family[family] + " " + positive_by_family[family]
        assert reconstructed_positive == table[family]["positive"], f"{family}: stimulus/positive_control drifted from the table"
        assert refusal_by_family[family] == table[family]["refusal"], f"{family}: refusal_control drifted from the table"
        assert witness_by_family[family] == table[family]["witness"], f"{family}: oracle witness drifted from the table"


def test_f3_player_faint_and_soft_reset_keep_their_discriminator_wording():
    table = _f3_table_rows()
    mapping = _f3_json_mapping()
    refusal_by_family = _split_family_field(mapping["refusal_control"], F3_FAMILIES, ": ")
    witness_by_family = _split_family_field(mapping["oracle"], F3_FAMILIES, " => ")

    player_faint_refusal_markers = ("write-permit receipt", "W-1", "wBattleMonHP", "writes.lua")
    for marker in player_faint_refusal_markers:
        assert marker in table["player_faint"]["refusal"], f"table player_faint refusal lost {marker!r}"
        assert marker in refusal_by_family["player_faint"], f"JSON player_faint refusal_control lost {marker!r}"

    soft_reset_witness_markers = ("transition", "in-game", "into the reset/title flow")
    for marker in soft_reset_witness_markers:
        assert marker in table["soft_reset"]["witness"], f"table soft_reset witness lost {marker!r}"
        assert marker in witness_by_family["soft_reset"], f"JSON soft_reset oracle lost {marker!r}"
