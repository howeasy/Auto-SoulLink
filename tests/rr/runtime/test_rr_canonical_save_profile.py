"""Read-only profile selection against controlled ROM/RAM, not admission proof."""
from tests.rr.runtime.rr_harness import RRHarness


def test_supported_rr_is_identified_before_any_save_pointer_exists(rr_repo):
    h = RRHarness(rr_repo, load=False)
    for address in (0x03005008, 0x0300500C, 0x03003840, 0x03003838):
        h.seed_u32(address, 0)
    assert h.G.detect_variant() == "radical_red"
    assert (h.G.profiles.radical_red.SB1_PTR_ADDR, h.G.profiles.radical_red.SB2_PTR_ADDR) == (0x03005008, 0x0300500C)


def test_vanilla_save_pointer_cannot_impersonate_rr(rr_repo):
    h = RRHarness(rr_repo, load=False)
    h.seed(0x08000108, bytes(32))
    h.seed_u32(0x080001BC, 0x08254784)
    h.seed_u32(0x08000144, 0)
    h.seed_u32(0x03003840, h.SB1)
    assert h.G.detect_variant() == "vanilla"


def test_ap_rom_without_rr_marker_keeps_existing_profile_priority(rr_repo):
    h = RRHarness(rr_repo, load=False)
    h.seed_u32(0x080001BC, 0)
    h.seed_u32(0x08000144, 0)
    h.seed_u32(h.G.profiles.ap.SB1_PTR_ADDR, h.SB1)
    assert h.G.detect_variant() == "ap"
