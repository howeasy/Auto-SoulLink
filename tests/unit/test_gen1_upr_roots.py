"""upr_layout.json's UPR pointer roots are source- and byte-pinned on every clean ROM.

`server/gen1_upr_scan.py` walks tables from these roots to admit a randomized cartridge, so
tools/verify_gen1_rom_layout.py pins each one to its pret symbol (+ documented displacement)
and to the clean-ROM bytes pret's source says are there. This runs that row through
`_rows_for` for every present ROM, and proves the check is not vacuous by shifting one root.
"""
from __future__ import annotations

import copy
import json
import os

import pytest

from tools.verify_gen1_rom_layout import ROMS, UPR_ROOTS_CHECK, _rows_for

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_LAYOUT = os.path.join(_REPO, "data", "games", "gen1_rby", "upr_layout.json")


def _rom(title: str) -> bytes:
    path = os.path.join(_REPO, ROMS[title])
    if not os.path.exists(path):
        pytest.skip(f"{path} not present")
    pret = os.path.join(_REPO, ".cache", "pret", "pokeyellow" if title == "yellow" else "pokered")
    if not os.path.isdir(pret):
        pytest.skip(f"{pret} not present")
    with open(path, "rb") as f:
        return f.read()


def _row(title: str, layout=None):
    rows = [r for r in _rows_for(title, _rom(title), layout) if r[0] == UPR_ROOTS_CHECK]
    assert len(rows) == 1, rows
    return rows[0]


@pytest.mark.parametrize("title", sorted(ROMS))
def test_upr_roots_row_ok(title):
    name, ok, detail = _row(title)
    assert ok, detail
    assert "roots pinned" in detail


@pytest.mark.parametrize("title", sorted(ROMS))
def test_shifted_root_is_named(title):
    with open(_LAYOUT, encoding="utf-8") as f:
        layout = json.load(f)
    mutated = copy.deepcopy(layout)
    mutated["profiles"][title]["settings"]["PokemonStatsOffset"] += 1
    name, ok, detail = _row(title, mutated)
    assert not ok
    assert "PokemonStatsOffset" in detail and "BaseStats" in detail
