"""Gen 1 display defects that were wrong-on-screen rather than blank.

None of these raised. Every one rendered a plausible-looking wrong value, which is why
they survived a green suite: `test_routes_smoke.py` asserts `status < 500`, and all of
these return 200.
"""
import pytest

from server.adapters import gen1_codec as codec, get_adapter

PIKACHU = codec.natdex_to_internal(25)  # the wire carries INTERNAL species indices


@pytest.fixture
def a():
    return get_adapter("gen1_rby")


# ── sprites ──────────────────────────────────────────────────────────────

def test_sprite_html_carries_the_shared_class(a):
    """Shared code keys off `mon-sprite`; without it Gen 1 opted out of the whole
    sprite pipeline. server.py:1659 rewrites the class to `enc-sprite` to shrink
    encounter icons, every responsive rule in slink.css/dashboard.css is written
    against it, the fainted/dead greyscale rules match on it, and dashboard.js
    selects `img.mon-sprite, img.enc-sprite` for the chroma-key pass.
    """
    html = a.sprite_html(PIKACHU)
    assert 'class="mon-sprite"' in html
    assert 'data-species="25"' in html


def test_the_encounter_icon_swap_is_no_longer_a_noop(a):
    """server.py:1659 does exactly this replace to get a 20px icon."""
    swapped = a.sprite_html(PIKACHU).replace('class="mon-sprite"', 'class="enc-sprite"')
    assert 'class="enc-sprite"' in swapped, (
        "the enc-sprite swap silently did nothing, so encounter icons rendered at 40px "
        "in a list sized for 20")


def test_sprite_img_is_decorative(a):
    """The name sits beside every sprite, so the image is alt="" (as Gen 3's is), not unlabelled."""
    assert ' alt="" ' in a.sprite_html(PIKACHU)


def test_sprite_html_is_empty_for_no_species(a):
    assert a.sprite_html(0) == ""


def test_sprite_src_is_period_correct(a):
    """The JSON payload and the HTML must not disagree about which era they render.

    Inheriting the base default served modern artwork here while sprite_html served
    8-bit Red/Blue sprites -- on the same stream layout.
    """
    assert "generation-i/red-blue" in a.sprite_src(PIKACHU)
    assert "generation-i/red-blue" in a.sprite_html(PIKACHU)
    assert a.sprite_src(0) == ""


# ── status ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    (0x00, ""),
    (0x01, "SLP"),   # sleep is a COUNTER in bits 0-2 ...
    (0x03, "SLP"),
    (0x07, "SLP"),   # ... so every nonzero value in that mask means asleep
    (0x08, "PSN"),
    (0x10, "BRN"),
    (0x20, "FRZ"),
    (0x40, "PAR"),
    (0x80, ""),      # bit 7 unused in Gen 1 -- Toxic is a battle-only volatile
])
def test_status_token(a, value, expected):
    assert a.status_token(value) == expected


def test_status_token_agrees_with_the_shared_icon_renderer(a):
    """The board renders a mon's own status through the status_pill macro and the
    PARTNER column through adapter.status_token. If the two disagree, one mon shows PSN
    and its linked half shows nothing."""
    from tests.unit.test_stat_stages import _status_icon_html
    for value in (0x01, 0x07, 0x08, 0x10, 0x20, 0x40):
        tok = a.status_token(value)
        icon = _status_icon_html(value)
        assert tok and tok in icon, f"0x{value:02X}: token={tok!r} icon={icon!r}"


# ── badges + box index ───────────────────────────────────────────────────
# P8-2b: both were source greps against lua/clients/gen1_rby_client.lua. The rewritten
# client reads them through lua/gen1/reads.lua, and the values are pinned against the
# Python codec by tests/unit/test_gen1_reads.py::test_ancillary_reads_and_all_addresses_
# follow_shifted_profile (read_badges returns the raw wObtainedBadges byte, 0xA5 in the
# fixture -- a popcount could not produce it) and ::test_all_twelve_sram_boxes
# (read_current_box_num returns the masked index, so Box 12's contents no longer report as
# box 0 here and box 11 from the memorial read).


def test_sprite_crop_fills_the_box_like_gen2(a):
    """The art is a 56px cell on a 96px canvas; a 40px window must show it at 69px, -14px."""
    html = a.sprite_html(PIKACHU)
    assert "width:40px;height:40px" in html and "width:69px;height:69px" in html
    assert "margin:-14px" in html
