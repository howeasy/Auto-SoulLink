"""Physical receptionist gate on patched Red/Blue; normal-button town-to-Center walk.

Run only when the owner releases the emulator lane:
    SLINK_LIVE=1 python -m pytest tests/live/test_gen1_trade_gates.py -q -p no:cacheprovider

The gate boots the qualified, unmodified red_town/blue_town battery saves at
Oak's Lab and walks to Viridian Center. It does not stage RAM, registers or a
savestate, and it does not manufacture a Center fixture. A passed gate proves
the live local receptionist query/offer/refusal path, not a paired physical trade.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

from tests.unit import protocol_schema as schema

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

GATE = "lua/tests/test_gen1_receptionist_gate.lua"

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                       reason="live receptionist gate requires SLINK_LIVE=1 and the owner's EmuHawk lane"),
]


@pytest.fixture(scope="module")
def emuhawk():
    import gen1_playthrough as play

    if not os.path.exists(play.EMUHAWK):
        pytest.skip(f"EmuHawk not found at {play.EMUHAWK}")
    return play.EMUHAWK


@pytest.mark.parametrize("rom", ("red", "blue"))
def test_receptionist_query_offer_and_native_notices(rom, emuhawk):
    from run_gb_gate import PATCHED, run_gate

    assert PATCHED[f"{rom}_patched"][0] == rom  # existing key seeds <rom>_town.SaveRAM
    fixture = ROOT / f"tests/fixtures/gen1/{rom}_town.SaveRAM"
    patched_rom = ROOT / f"patch/gen1/build/slink_{rom}.gb"
    if not fixture.is_file() or not patched_rom.is_file():
        pytest.skip(f"{rom}: qualified town SaveRAM or patched trade ROM absent")
    passed, result_path, text = run_gate(GATE, rom_key=f"{rom}_patched", target="town",
                                         timeout=900, quiet=True)
    # the gate overwrites one result file per run; keep a receipt per cartridge
    kept = Path(result_path).with_name(f"test_gen1_receptionist_gate_{rom}_result.txt")
    kept.write_text(text, encoding="utf-8")
    assert passed, f"{rom}: receptionist gate failed ({result_path}):\n{text[-3000:]}"
    assert "[ok] trade_enabled on the patched build" in text
    assert "[ok] bank-qualified trade service site registered" in text
    assert "[ok] walked from Oak's Lab to the physical Center receptionist" in text
    assert text.count("[ok] native receptionist emitted trade_query within 30 frames") == 2
    assert text.count("[ok] selected slot zero emitted trade_offer within 180 frames") == 2
    # wait_for logs nothing on success; the gate prints the tilemap row it saw
    assert "NOTICE Trade unavailable." in text
    assert "NOTICE Trade offer sent." in text
    assert text.count("[ok] native offer returned cleanly to the overworld") == 2
    assert "MENU SLINK" in text and "MENU CABLE" in text and "MENU CANCEL" in text

    lines = re.findall(r"^SENT (\{.*\})$", text, re.M)
    assert lines, f"{rom}: gate did not record outbound client lines"
    messages = [json.loads(line) for line in lines]
    for index, message in enumerate(messages):
        assert schema.validate_event(message) == [], (rom, index, message)
    seq = [message["seq"] for message in messages]
    assert seq == list(range(seq[0], seq[0] + len(seq))), f"{rom}: client seq discontinuity"
    assert sum(message["event"] == "trade_query" for message in messages) == 2
    offers = [message for message in messages if message["event"] == "trade_offer"]
    assert len(offers) == 2 and [offer["slot"] for offer in offers] == [0, 0]
