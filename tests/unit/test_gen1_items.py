"""The Gen 1 item table must match the cartridge, id for id.

The hand-written table had 17 of its 45 entries wrong: every id from $2D upward was
shifted by one, so `X Accuracy` named the Bike Voucher, `Poké Doll` named a Full Heal
and `X Special` named Oak's Parcel. Nothing caught it because a wrong name renders
exactly as convincingly as a right one -- the failure mode this whole sweep exists to
find.

It is generated now (tools/gen_gen1_items.py), so this file pins the generator's output
against the decomp rather than against a copy of itself.
"""
from __future__ import annotations

import os
import re

import pytest

from server.data.items.gen1 import ITEM_NAMES

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def _find_pret() -> str:
    """A worktree has no .cache of its own; walk up to the main checkout."""
    d = _REPO
    for _ in range(6):
        cand = os.path.join(d, ".cache", "pret", "pokered")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.join(_REPO, ".cache", "pret", "pokered")


@pytest.fixture(scope="module")
def asm_names():
    path = os.path.join(_find_pret(), "data", "items", "names.asm")
    if not os.path.exists(path):
        pytest.skip("pokered not cloned — run tools/build_pret_syms.py")
    out, item_id = {}, 0
    with open(path, encoding="utf-8") as f:
        for raw in f:
            m = re.match(r'^\s*li\s+"([^"]*)"', raw)
            if not m:
                continue
            item_id += 1
            if m.group(1).strip("?"):
                out[item_id] = m.group(1)
    return out


def test_the_fixture_is_not_vacuous(asm_names):
    """Control: every assertion below passes trivially on an empty parse."""
    assert len(asm_names) > 40, f"only parsed {len(asm_names)} names"
    assert asm_names[1] == "MASTER BALL"


def test_every_id_matches_the_decomp(asm_names):
    """Compared case-insensitively with punctuation stripped: the table is display
    text, the decomp is cartridge text, and the only thing under test is WHICH id
    carries WHICH item."""
    def norm(s):
        return re.sub(r"[^a-z0-9]", "", s.lower())

    wrong = {i: (ITEM_NAMES[i], asm_names[i])
             for i in asm_names
             if i in ITEM_NAMES and norm(ITEM_NAMES[i]) != norm(asm_names[i])}
    assert not wrong, "item ids naming the wrong item: " + ", ".join(
        f"0x{i:02X} says {got!r}, cartridge says {want!r}" for i, (got, want) in wrong.items())


def test_the_shifted_ids_specifically(asm_names):
    """The exact off-by-one that shipped. Named so a regression says what broke."""
    for item_id, expected in ((0x2D, "BIKE VOUCHER"), (0x2E, "X ACCURACY"),
                              (0x34, "FULL HEAL"), (0x35, "REVIVE"),
                              (0x43, "X SPEED"), (0x46, "OAK's PARCEL")):
        assert asm_names[item_id] == expected, "test's own expectation is stale"
        assert ITEM_NAMES[item_id].lower().replace(".", "").replace("'", "") \
            == expected.lower().replace(".", "").replace("'", "")


def test_unused_ids_are_absent():
    """`?????` placeholders must not be given names — an unknown item should read as
    unknown, not as a plausible wrong one."""
    assert 0x07 not in ITEM_NAMES, "SURFBOARD is an unused id in RBY"


def test_tms_and_hms_are_covered():
    """The engine formats these at runtime from the id rather than from ItemNames,
    so they have to be generated the same way."""
    assert ITEM_NAMES[0xC4] == "HM01"
    assert ITEM_NAMES[0xC9] == "TM01"
    assert ITEM_NAMES[0xFA] == "TM50"
