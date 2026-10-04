"""Polished Crystal Phone card SLink contact (docs/polished/PHONE_SLOT.md, Stage 1).

The contact is virtual: five same-size `call` operand rewrites in bank $24 route the Phone card's
list walk, row label, Delete rule and Call to ROM0 bridges. These tests pin that shape:
the pure confinement helper (synthetic bytes, with red controls), the published artifacts
against the pinned release ROM (absent skips, wrong fails), and the no-save invariant.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import build_polished_companion as pc  # noqa: E402
from build_gen2_companion import _symbols  # noqa: E402
from make_ups import ups_apply  # noqa: E402

RELEASE = Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work")) / "cache/polished/release/polishedcrystal-3.2.3.gbc"
CLEAN_SYM = REPO / "data/polished/polishedcrystal.sym"
OVERLAY_SYM = REPO / "data/polished/polished_slink.sym"
# patch/upr/0020: the jar recognises the overlay by these bytes; a change forces a jar cut
UPR_SERVICE_PROLOGUE = bytes.fromhex("210bc63e53223e4c223e4e223e4b223e")


# ------------------------------------------------------------------ pure helper, synthetic bytes

def _fixture():
    old, new = {}, {}
    base = bytearray(0x100000)
    for i, (routine, native, bridge) in enumerate(pc.PHONE_HOOKS):
        old.setdefault(routine, (0x24, 0x4100 + 0x80 * len(old)))
        old[native] = (0x24, 0x5000 + 0x10 * i)
        new[bridge] = (0x00, 0x3F34 + 8 * i)
    new.update(old)
    data = bytearray(base)
    for i, (routine, native, bridge) in enumerate(pc.PHONE_HOOKS):
        at = pc._flat(*old[routine]) + 4 + 8 * i
        base[at:at + 3] = data[at:at + 3] = b"\xcd" + old[native][1].to_bytes(2, "little")
        data[at + 1:at + 3] = new[bridge][1].to_bytes(2, "little")
    return bytes(base), data, old, new


def test_every_hook_yields_its_two_operand_bytes():
    base, data, old, new = _fixture()
    spans = pc.phone_hook_spans(base, bytes(data), old, new)
    assert len(spans) == len(pc.PHONE_HOOKS) == 5
    assert all(hi - lo == 2 for lo, hi, _ in spans)


def test_a_call_left_native_is_refused():
    base, data, old, new = _fixture()
    with pytest.raises(RuntimeError, match="is not `call SlinkPhone_CountSetBits`"):
        pc.phone_hook_spans(base, base, old, new)


def test_a_call_retargeted_to_the_wrong_bridge_is_refused():
    base, data, old, new = _fixture()
    new = dict(new, SlinkPhone_CanDelete=(0x00, 0x3FF0))
    with pytest.raises(RuntimeError, match="is not `call SlinkPhone_CanDelete`"):
        pc.phone_hook_spans(base, bytes(data), old, new)


def test_an_ambiguous_routine_is_refused():
    base, data, old, new = _fixture()
    at = pc._flat(*old["PokegearPhone_MakePhoneCall"]) + 0x30
    base = bytearray(base)
    base[at:at + 3] = b"\xcd" + old["GetMapPhoneService"][1].to_bytes(2, "little")
    with pytest.raises(RuntimeError, match="expected exactly one `call GetMapPhoneService`, found 2"):
        pc.phone_hook_spans(bytes(base), bytes(data), old, new)


def test_a_bridge_outside_rom0_is_refused():
    base, data, old, new = _fixture()
    new = dict(new, SlinkPhone_CallerName=(0x7E, 0x4100))
    with pytest.raises(RuntimeError, match="SlinkPhone_CallerName must be ROM0"):
        pc.phone_hook_spans(base, bytes(data), old, new)


# ------------------------------------------------------------------ the published overlay

@pytest.fixture(scope="module")
def roms():
    if not RELEASE.is_file():
        pytest.skip(f"pinned Polished Crystal release absent: {RELEASE}")
    release = RELEASE.read_bytes()
    lock = json.loads((REPO / "data/polished_sources.lock.json").read_text(encoding="utf-8"))
    assert hashlib.sha1(release).hexdigest() == lock["outputs"]["polishedcrystal"]["sha1"], "not the pinned release"
    prov = json.loads((REPO / "data/polished/overlay_provenance.json").read_text(encoding="utf-8"))["output"]
    overlay = ups_apply(release, (REPO / prov["ups"]["file"]).read_bytes())
    assert hashlib.sha1(overlay).hexdigest() == prov["sha1"]
    return release, overlay


def test_bank_24_changes_only_the_five_call_operands(roms):
    release, overlay = roms
    old, new = _symbols(CLEAN_SYM), _symbols(OVERLAY_SYM)
    bank24 = [(a, b) for a, b in pc.diff_spans(release, overlay) if a // 0x4000 == 0x24]
    hooks = pc.phone_hook_spans(release, overlay, old, new)
    assert sorted(bank24) == sorted((lo, hi) for lo, hi, _ in hooks)
    assert len(bank24) == 5 and all(release[a - 1] == overlay[a - 1] == 0xCD for a, _ in bank24)


def test_the_bridge_sits_in_free_rom0_and_the_upr_signature_is_unchanged(roms):
    release, overlay = roms
    new = _symbols(OVERLAY_SYM)
    lo, hi = new["SlinkPhone_CountSetBits"], new["SlinkPhoneBridgeEnd"]
    assert lo[0] == hi[0] == 0 and 0x3F34 <= lo[1] < hi[1] <= 0x4000
    assert release[lo[1]:hi[1]] == b"\xff" * (hi[1] - lo[1])
    assert overlay[0x70:0x77] == pc.DELAY_NATIVE
    assert overlay[0xDA8:0xDAF] == bytes.fromhex("cd700000000000")
    assert overlay[0x1F8000:0x1F8010] == UPR_SERVICE_PROLOGUE


# ------------------------------------------------------------------ the contact is never saved

def test_the_overlay_never_names_the_saved_phone_list():
    """Virtual row: no overlay source touches wPhoneList, so the 40-bit flag array (and the save) is native."""
    for src in (REPO / "patch/polished/src").glob("*.asm"):
        code = [line.split(";")[0] for line in src.read_text(encoding="utf-8").splitlines()]
        assert not any("wPhoneList" in line for line in code), src.name
    assert "DEF SLINK_PHONE_CONTACT EQU NUM_PHONE_CONTACTS + 1" in (REPO / "patch/polished/src/slink.asm").read_text(encoding="utf-8")
