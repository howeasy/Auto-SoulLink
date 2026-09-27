"""RR field poison is N/A, not unpinned: DoPoisonFieldEffect is a no-op stub on Radical Red.

Vanilla FRLG decrements HP in DoPoisonFieldEffect (pret pokefirered.sym:6887 -> 080A0618,
0x82 bytes) and stores it with SetMonData, which is where SLink's `poison_hp_before` (+0x34)
and `poison_faint` (+0x4E) rows were pinned. RR keeps the vanilla symbol ADDRESS but replaces the
entry with a Thumb literal-load trampoline, so the vanilla capture offsets describe bytes that
are not the function any more. Reading the trampoline's own literal is the only way to the real
target, and the target is a four-byte stub: MOVS r0,#0 ; BX lr -- no party loop, no GetMonData,
no SetMonData, no HP store. Field poison therefore cannot even DAMAGE a party mon outside
battle, so the field-poison faint row is N/A on RR and the pack must carry no poison site at all
(`data/games/gen3_rr/engine_signals.json`). This is a positive, byte-measured fact about the
admitted cartridge, not a coverage gap: the vanilla-style tail is unreachable, so a "we have not
found the RR poison site yet" reading is wrong.

`tools/gen_gen3_engine_signals.py:rr_resolution` already classifies the row as UNVERIFIED, and
tests/unit/test_gen3_engine_sites.py checks the classification -- but only when the dump sits at
the hardcoded owner path. This test pins the four bytes themselves, and resolves the clean dump
the way the rest of the suite does: $SLINK_GEN3_ROMS, the staged patch/build copy, then the
admitted path. Absent skips by name, a present-but-wrong sha1 fails (tests/TESTING.md,
"Absent input skips; present-but-wrong input fails").
"""
import hashlib
import json
import os
from pathlib import Path

import pytest

from tools import gen_gen3_engine_signals as gen
from tools.pin_gen3_site import ROM_BASE, ROM_SPECS, decode_thumb_detour

ROOT = Path(__file__).resolve().parents[2]
RR_SHA1 = "964f951a0fdaf209e4ea1344883ef0d557bb3a80"
RR_DUMP_NAME = "Pokemon - Radical Red.gba"
STAGED_CLEAN = Path("patch/build/rr_clean.gba")
PACK_JSON = ROOT / "data/games/gen3_rr/engine_signals.json"  # read inside the test, never at import

# The entry address is a pinned pret symbol, not a guess: data/gen3/pret/pokefirered.sym:6887.
# The target and its body are measured out of the admitted ROM by decode_thumb_detour.
RR_POISON_ENTRY = 0x080A0618
RR_POISON_STUB = 0x090B20D4
RR_POISON_BODY = bytes.fromhex("00207047")  # MOVS r0,#0 ; BX lr
FR_POISON_ENTRY_BYTES = bytes.fromhex("F0B581B0194C002700260525201C0521")


@pytest.fixture(scope="module")
def clean_rr():
    """The pinned clean RR 4.1 dump. Absent skips naming every path tried; wrong sha1 fails."""
    candidates = [STAGED_CLEAN, ROM_SPECS["rr"][3]]
    if os.environ.get("SLINK_GEN3_ROMS"):
        candidates.insert(0, Path(os.environ["SLINK_GEN3_ROMS"]) / RR_DUMP_NAME)
    tried = [ROOT / c if not c.is_absolute() else c for c in candidates]
    path = next((p for p in tried if p.is_file()), None)
    if path is None:
        pytest.skip(f"clean Radical Red dump absent; looked for {', '.join(map(str, tried))} "
                    "-- set SLINK_GEN3_ROMS")
    rom = path.read_bytes()
    if hashlib.sha1(rom).hexdigest() != RR_SHA1:
        pytest.fail(f"{path} is not the pinned clean Radical Red dump {RR_SHA1}")
    return rom


def test_the_repo_pin_is_the_dump_this_test_qualifies_against():
    """The card's sha1 and tools/pin_gen3_site.py's admitted pin are one value, checked here so
    a silent re-pin of ROM_SPECS cannot quietly qualify a different cartridge."""
    assert ROM_SPECS["rr"][4] == RR_SHA1
    assert ROM_SPECS["rr"][2] == "clean", "this test is about the CLEAN dump, not the companion"


def test_rr_detours_the_vanilla_poison_entry_to_the_no_op_stub(clean_rr):
    """080A0618 is a Thumb literal-load trampoline; its own literal is the only route to the
    real body, and it lands on the stub -- not on a relocated copy of the vanilla function."""
    detour = decode_thumb_detour(clean_rr, RR_POISON_ENTRY)
    assert detour["address"] == RR_POISON_ENTRY
    assert detour["target"] == RR_POISON_STUB
    entry_flat = RR_POISON_ENTRY - ROM_BASE
    assert clean_rr[entry_flat:entry_flat + 16] != FR_POISON_ENTRY_BYTES, (
        "the admitted entry still carries the vanilla body; the RR detour claim no longer holds")
    flat = RR_POISON_STUB - ROM_BASE
    assert clean_rr[flat:flat + 4] == RR_POISON_BODY


def test_the_stub_is_two_instructions_and_mutates_nothing(clean_rr):
    """MOVS r0,#0 (2000) ; BX lr (4770). R0=0 is FLDPSN_NONE, and a body this short cannot hold
    the vanilla party loop, so there is no HP store for a faint to come from."""
    flat = RR_POISON_STUB - ROM_BASE
    assert int.from_bytes(clean_rr[flat:flat + 2], "little") == 0x2000  # MOVS r0,#0
    assert int.from_bytes(clean_rr[flat + 2:flat + 4], "little") == 0x4770  # BX lr


@pytest.mark.parametrize("kind", ("poison_hp_before", "poison_faint"))
def test_the_unverified_label_is_derived_from_those_bytes_not_hardcoded(kind, clean_rr):
    """Revert-check: perturbing the stub must move the classification off "NO HP mutation". A
    generator that printed the label regardless of the ROM would pass the unmutated case."""
    c = next(c for c in gen.CANDIDATES if c["kind"] == kind)
    clean = gen.resolve(c, "rr", clean_rr)
    assert clean["status"] == "UNVERIFIED", "a stubbed body must never be promoted to a site"
    assert "site" not in clean, "N/A is a refusal, not a site with low confidence"
    assert "NO HP mutation" in clean["reason"]

    flat = RR_POISON_STUB - ROM_BASE
    mutated = bytearray(clean_rr)
    mutated[flat:flat + 4] = bytes.fromhex("01217047")  # MOVS r0,#1 ; BX lr -- not the no-op
    result = gen.resolve(c, "rr", bytes(mutated))
    assert "NO HP mutation" not in result["reason"]
    assert result["status"] == "UNVERIFIED"


def test_the_rr_pack_carries_no_poison_row():
    """The consequence, on the artifact the client actually reads: neither artifact's site table
    may name poison, so no capture offset is ever armed for it."""
    pack = json.loads(PACK_JSON.read_text(encoding="utf-8"))
    for artifact in ("clean", "companion"):
        sites = pack["titles"]["radical_red"]["artifacts"][artifact]["sites"]
        assert [k for k in sites if k.startswith("poison")] == [], (artifact, sorted(sites))

