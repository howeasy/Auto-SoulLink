"""Polished trade slice 1: the generated item-allow table is the item_constants mail policy.

Run: pytest tests/unit/test_polished_trade_items.py -v
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "tools"))

try:
    import gen_polished_trade_items as gen
    FIRST_MAIL = gen.first_mail()
except Exception as exc:  # absent pinned Polished source: skip, never pass silently
    pytest.skip(f"pinned Polished source unavailable: {exc}", allow_module_level=True)


def _table(text: str) -> list[int]:
    return [int(v) for row in re.findall(r"^\tdb ([01,]+) ;", text, re.M) for v in row.split(",")]


def test_first_mail_is_f5():
    assert FIRST_MAIL == 0xF5


def test_committed_table_policy():
    table = _table(gen.OUT.read_text(encoding="utf-8"))
    assert len(table) == 256 and sum(table) == 245
    assert all(table[i] == 1 for i in range(0xF5))
    assert all(table[i] == 0 for i in range(FIRST_MAIL, 256))  # mail and the $FF sentinel


def test_committed_file_is_generator_output():
    assert gen.OUT.read_text(encoding="utf-8").replace("\r\n", "\n") == gen.render(FIRST_MAIL)


def test_red_control_wrong_first_mail_differs():
    assert gen.render(FIRST_MAIL + 1) != gen.OUT.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert sum(_table(gen.render(FIRST_MAIL - 1))) == 244


def test_asm_pins_service_bank_and_has_no_vanilla_bank_select():
    src = (REPO / "patch/polished/src/trade_items.asm").read_text(encoding="utf-8")
    assert "ASSERT SLINK_SERVICE_BANK == $7E" in src and "_GOLD" not in src and "_SILVER" not in src
    frame = (REPO / "patch/polished/src/trade_frame.asm").read_text(encoding="utf-8")
    assert 'DEF SLINK_TRADE_FRAME EQUS "wSlinkMailbox + SLINK_OFS_TRADE_LEASE"' in frame
