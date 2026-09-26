"""Physical receptionist gate on patched Red/Blue AND the pureRGB companion overlay
(purered_overlay, PLAN M3/P4); normal-button town-to-Center walk.

Run only when the owner releases the emulator lane:
    SLINK_LIVE=1 python -m pytest tests/live/test_gen1_trade_gates.py -q -p no:cacheprovider

The gate boots the qualified, unmodified <rom>_town battery save at Oak's Lab and walks to
Viridian Center. It does not stage RAM, registers or a savestate, and it does not manufacture a
Center fixture. A passed gate proves the live local receptionist query/offer/refusal path, not a
paired physical trade. The overlay case reuses the clean purered_town fixture (A4: a clean pure
SaveRAM loads unchanged on the overlay build).
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


# (rom_key, fixture_key, legacy patched-ROM path or None). The overlay case has no fixed build
# path: its cartridge is staged on demand by g1.staged_rom (apply the UPS, verify the sha1
# against admission_overlay.json — tools/gen1_playthrough.purergb_overlay_dump, PLAN M3 A4).
CASES = (
    ("red_patched", "red", "patch/gen1/build/slink_red.gb"),
    ("blue_patched", "blue", "patch/gen1/build/slink_blue.gb"),
    ("purered_overlay", "purered", None),
)


@pytest.mark.parametrize(("rom_key", "fixture_key", "legacy_rom_path"), CASES)
def test_receptionist_query_offer_and_native_notices(rom_key, fixture_key, legacy_rom_path, emuhawk):
    import gen1_playthrough as play
    from run_gb_gate import PATCHED, run_gate

    assert PATCHED[rom_key][0] == fixture_key  # seeds <fixture_key>_town.SaveRAM (A4: shared pure fixture)
    fixture = ROOT / f"tests/fixtures/gen1/{fixture_key}_town.SaveRAM"
    if not fixture.is_file():
        pytest.skip(f"{rom_key}: qualified town SaveRAM absent")
    if legacy_rom_path is not None:
        if not (ROOT / legacy_rom_path).is_file():
            pytest.skip(f"{rom_key}: patched trade ROM absent ({legacy_rom_path})")
    else:
        try:
            play.staged_rom(rom_key)   # applies the UPS and sha1-verifies the overlay cartridge
        except Exception as exc:  # noqa: BLE001 - any staging failure just skips a live gate
            pytest.skip(f"{rom_key}: overlay cartridge unavailable ({exc})")
    passed, result_path, text = run_gate(GATE, rom_key=rom_key, target="town",
                                         timeout=900, quiet=True)
    # the gate overwrites one result file per run; keep a receipt per cartridge
    kept = Path(result_path).with_name(f"test_gen1_receptionist_gate_{rom_key}_result.txt")
    kept.write_text(text, encoding="utf-8")
    assert passed, f"{rom_key}: receptionist gate failed ({result_path}):\n{text[-3000:]}"
    assert "[ok] trade_enabled on the patched build" in text
    assert "[ok] bank-qualified trade service site registered" in text
    assert "[ok] walked from Oak's Lab to the physical Center receptionist" in text
    assert text.count("[ok] native receptionist emitted trade_query within 30 frames") == 2
    assert "[ok] CABLE CLUB fell through to vanilla and returned to the overworld" in text
    assert "[ok] CANCEL closed the native menu with no offer" in text
    assert "VANILLA Welcome to the" in text
    # both SLINK TRADE visits answer the must-save YES before the picker (trade_receptionist.asm:53-57)
    assert text.count("MUST_SAVE We have to save") == 2
    assert text.count("[ok] must-save prompt defaulted to YES") == 2
    assert text.count("[ok] selected slot zero emitted trade_offer within 180 frames") == 2
    # wait_for logs nothing on success; the gate prints the tilemap row it saw
    assert "NOTICE Trade unavailable." in text
    assert "NOTICE Trade offer sent." in text
    assert text.count("[ok] native offer returned cleanly to the overworld") == 2
    assert "MENU SLINK" in text and "MENU CABLE" in text and "MENU CANCEL" in text

    lines = re.findall(r"^SENT (\{.*\})$", text, re.M)
    assert lines, f"{rom_key}: gate did not record outbound client lines"
    messages = [json.loads(line) for line in lines]
    for index, message in enumerate(messages):
        assert schema.validate_event(message) == [], (rom_key, index, message)
    seq = [message["seq"] for message in messages]
    assert seq == list(range(seq[0], seq[0] + len(seq))), f"{rom_key}: client seq discontinuity"
    assert sum(message["event"] == "trade_query" for message in messages) == 4  # 2 offers + CABLE CLUB + CANCEL
    offers = [message for message in messages if message["event"] == "trade_offer"]
    assert len(offers) == 2 and [offer["slot"] for offer in offers] == [0, 0]
