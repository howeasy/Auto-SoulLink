"""The old Gen 3 client's substructure permutation table must equal the Python codec's, which is
pinned to pret src/pokemon.c SUBSTRUCT_CASE at c75f352 (tests/unit/test_gen3_codec.py). Found by the
P2 codec card: rows 3 and 4 were swapped in lua/memory_gba.lua (vanilla FRLG only; RR is unencrypted).
This is the smallest PYDEC-style differential: parse the Lua literal, no runtime."""
import re
from pathlib import Path

from server.adapters import gen3_codec

REPO = Path(__file__).resolve().parents[2]


def _lua_table():
    src = (REPO / "lua" / "memory_gba.lua").read_text(encoding="utf-8")
    body = re.search(r"M\.SUBSTRUCT_ORDER\s*=\s*\{(.*?)\n\}", src, re.S).group(1)
    rows = re.findall(r"\{(\d),(\d),(\d),(\d)\}", body)
    return [tuple(int(x) for x in r) for r in rows]


def test_lua_permutation_table_matches_codec_and_pret():
    lua = _lua_table()
    assert len(lua) == 24
    assert lua == [tuple(r) for r in gen3_codec.SUBSTRUCT_ORDER]
    assert lua[3] == (0, 3, 1, 2) and lua[4] == (0, 2, 3, 1)
