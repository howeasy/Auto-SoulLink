"""R0 table heads are per-title symbol facts, separate from companion ABI."""

import json
import re

import pytest

from tools import gen_gen3_profile as g


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_rom_tables_match_each_titles_pinned_symbols(title):
    text = (g.REPO / f"data/gen3/pret/poke{title}.sym").read_text()
    rows, provenance = g.rom_tables(title, text)
    expected = {"gTrainers": (40, 743), "gWildMonHeaders": (20, 133),
                "gEvolutionTable": (40, 412), "gSpeciesInfo": (28, 412),
                "gTrainerClassNames": (13, 107)}
    assert set(rows) == set(expected)
    for name, (stride, count) in expected.items():
        match = re.search(rf"^([0-9a-f]{{8}}) [lg] ([0-9a-f]{{8}}) {name}$", text, re.M)
        assert match
        assert rows[name] == {"address": int(match[1], 16), "size": int(match[2], 16),
                              "stride": stride, "count": count}
        assert rows[name]["size"] % stride == 0
        assert f"pret/pokefirered@c75f3523 {name}" in provenance[name]


def test_table_partial_stride_is_fatal():
    text = (g.REPO / "data/gen3/pret/pokefirered.sym").read_text()
    bad = re.sub(r"(^[0-9a-f]{8} [lg] )[0-9a-f]{8}( gSpeciesInfo$)", r"\g<1>00002d11\2", text, flags=re.M)
    with pytest.raises(ValueError, match="gSpeciesInfo"):
        g.rom_tables("firered", bad)


def test_committed_metadata_is_on_frlg_and_emerald_only():
    frlg = json.loads((g.REPO / "data/games/gen3_frlg/profile.json").read_text())
    for title in ("firered", "leafgreen"):
        text = (g.REPO / f"data/gen3/pret/poke{title}.sym").read_text()
        assert frlg["titles"][title]["rom_tables"] == g.rom_tables(title, text)[0]
        assert frlg["titles"][title]["rom_tables_provenance"] == g.rom_tables(title, text)[1]
    emerald = json.loads((g.REPO / "data/games/gen3_emerald/profile.json").read_text())["titles"]["emerald"]
    text = (g.REPO / "data/gen3/pret/pokeemerald.sym").read_text()
    assert emerald["rom_tables"] == g.rom_tables("emerald", text)[0]
    assert emerald["rom_tables_provenance"] == g.rom_tables("emerald", text)[1]
    rr = json.loads((g.REPO / "data/games/gen3_rr/profile.json").read_text())
    assert all("rom_tables" not in entry for entry in rr["titles"].values())
    assert "rom_tables" not in frlg["titles"]["firered_ap"]
