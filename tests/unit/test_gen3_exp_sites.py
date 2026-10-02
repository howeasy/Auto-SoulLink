"""EXP-ENGINE-SITES: expansion hatch binding + frame-window PC-release pairing (MODEL + SOURCE).

The expansion's pc_release_begin/pc_release are both mid-body in Task_ReleaseMon (no push/pop between
+0xFA and +0x17C), so the vanilla SP+4 pairing can never hold there. The pack declares a
frame_window pairing instead; vanilla packs carry no `pairing` key and keep the SP rule.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit.gen3_world import World, mon_record
from tests.unit.test_gen3_client import KB, OT, A, B, live, party

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "data/games/gen3_exp/28877d73"
ARTIFACT_DIR = ROOT / ".cache/expansion-output/reference"


def with_pairing(w, **pairing):
    """Give the in-memory pack the expansion's per-site `pairing` field (FR geometry otherwise)."""
    w.parts.sites.pc_release.pairing = w.lua.table(mode="frame_window", **pairing)
    return w


# -- (a)/(b)/(c): release pairing -----------------------------------------------------------
def test_frame_window_pairs_begin_and_done_in_one_invocation_despite_equal_sp():
    w = with_pairing(live(), window=0)
    w.fire("pc_release_begin")
    w.set_party(party(A))
    w.fire("pc_release")  # same frame, SP unchanged: the expansion's mid-body shape
    w.step(2)
    assert [e["key"] for e in w.events("release")] == [KB]


def test_frame_window_never_pairs_across_frames():
    w = with_pairing(live(), window=0)
    w.fire("pc_release_begin")
    w.step()  # begin left unanswered (cancel/early-exit), a later frame completes
    w.set_party(party(A))
    w.fire("pc_release")
    w.step(2)
    assert w.events("release") == []
    # and the stale latch was consumed: a second done in a fresh invocation has no begin
    w.set_party(party(A))
    w.fire("pc_release")
    w.step(2)
    assert w.events("release") == []


def test_frame_window_done_without_begin_is_refused():
    w = with_pairing(live(), window=0)
    w.set_party(party(A))
    w.fire("pc_release")
    w.step(2)
    assert w.events("release") == []


def test_vanilla_without_pairing_still_requires_sp_plus_four():
    w = live()
    w.fire("pc_release_begin")
    w.set_party(party(A))
    w.fire("pc_release")  # equal SP: refused
    w.step(2)
    assert w.events("release") == []
    w.set_party(party(A, B))
    w.fire("pc_release_begin")
    w.set_party(party(A))
    w.regs["R13"] -= 4
    w.fire("pc_release")
    w.step(2)
    assert [e["key"] for e in w.events("release")] == [KB]


def test_frame_window_does_not_accept_the_sp_rule_alone_across_frames():
    w = with_pairing(live(), window=0)
    w.fire("pc_release_begin")
    w.step()
    w.set_party(party(A))
    w.regs["R13"] -= 4  # vanilla-shaped delta, but a different frame: refused under frame_window
    w.fire("pc_release")
    w.step(2)
    assert w.events("release") == []


def test_an_unknown_pairing_mode_is_refused_not_downgraded_to_the_sp_rule():
    w = live()
    w.parts.sites.pc_release.pairing = w.lua.table(mode="mystery", window=0)
    w.fire("pc_release_begin")
    w.set_party(party(A))
    w.regs["R13"] -= 4  # satisfies the vanilla SP+4 rule, but the declared mode is unknown
    w.fire("pc_release")
    w.step(2)
    assert w.events("release") == []


# -- (d): hatch register -------------------------------------------------------------------
EGG = mon_record(0x22222222, OT, is_egg=1)
HATCHED = dict(EGG, is_egg=0, is_egg_flag=0, friendship=120)


def hatch_world(point):
    w = World()
    w.set_party([mon_record(A, OT), EGG])
    w.step_to(60)
    assert w.client.writes_enabled
    w.fire("mon_given")  # GiveEgg: observed, not acquired
    w.step(60)
    w.parts.sites.hatch.point = w.lua.table(*point)
    w.set_party([mon_record(A, OT), HATCHED])
    return w


def test_capture_hatch_accepts_an_r4_only_point():
    w = hatch_world(["R4", "R15", "CPSR"])
    w.regs["R4"] = w.party_base() + 100
    w.fire("hatch")
    w.step()
    assert [e["area_id"] for e in w.events("capture")] == ["gift_daycare"]


def test_capture_hatch_prefers_r5_when_both_are_present():
    w = hatch_world(["R4", "R5", "R15", "CPSR"])
    w.regs["R4"] = w.party_base()  # the lead, not the hatchling
    w.regs["R5"] = w.party_base() + 100
    w.fire("hatch")
    w.step()
    assert [e["area_id"] for e in w.events("capture")] == ["gift_daycare"]


def test_capture_hatch_r4_pointing_at_the_wrong_slot_publishes_nothing():
    w = hatch_world(["R4", "R15", "CPSR"])
    w.regs["R4"] = w.party_base() + 101
    w.fire("hatch")
    w.step(5)
    assert w.events("capture") == []


# -- (e): the generated expansion pack -------------------------------------------------------
def pack_sites():
    sites = json.loads((PACK / "engine_signals.json").read_text(encoding="utf-8"))
    return sites["titles"]["emerald_expansion_28877d73"]["artifacts"]["clean"]["sites"]


def test_expansion_pack_binds_hatch_at_the_verified_site():
    site = pack_sites()["hatch"]
    f = site["function"]
    assert (f["symbol"], f["address"], f["size"]) == ("AddHatchedMonToParty", 0x0811B284, 0xF4)
    assert (f["anchor_offset"], f["capture_offset"]) == (0xD6, 0xDA)
    assert site["expected_hex"] == "A4F05FFF0AB070BC01BC0047C046641B"
    assert site["rom_offset"] == 0x0011B35A and site["capture_offset"] == 4
    assert site["point"] == ["R4", "R15", "CPSR"]
    assert site["context"]["expected_hex"] == "70B5642400264443364B8AB0E41804AA"
    assert "R4" in site["capture_contract"] and "O-15" in site["capture_contract"]


def test_expansion_hatch_site_bytes_in_the_reference_rom():
    rom = ARTIFACT_DIR / "pokeemerald.gba"
    if not rom.is_file():
        pytest.skip("reference expansion ROM absent")
    data, site = rom.read_bytes(), pack_sites()["hatch"]
    assert data[site["rom_offset"]:site["rom_offset"] + 16].hex().upper() == site["expected_hex"]
    assert data.count(bytes.fromhex(site["expected_hex"])) == 1


def test_expansion_release_sites_declare_frame_window_pairing():
    sites = pack_sites()
    for kind in ("pc_release_begin", "pc_release"):
        pairing = sites[kind]["pairing"]
        assert pairing["mode"] == "frame_window" and pairing["window"] == 0 and pairing["reason"]
    assert all("pairing" not in s for k, s in sites.items() if not k.startswith("pc_release"))


def test_expansion_pack_generator_check_is_current():
    if not (ARTIFACT_DIR / "pokeemerald.gba").is_file():
        pytest.skip("reference expansion artifacts absent")
    run = subprocess.run([sys.executable, "tools/gen_gen3_engine_signals.py", "--expansion", "28877d73", "--check"],
                         cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
