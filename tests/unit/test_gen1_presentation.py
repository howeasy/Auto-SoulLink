"""Gen 1 display defects that were wrong-on-screen rather than blank.

None of these raised. Every one rendered a plausible-looking wrong value, which is why
they survived a green suite: `test_routes_smoke.py` asserts `status < 500`, and all of
these return 200.
"""
import os
import re

import pytest

from server.adapters import get_adapter

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
    html = a.sprite_html(25)
    assert 'class="mon-sprite"' in html
    assert 'data-species="25"' in html


def test_the_encounter_icon_swap_is_no_longer_a_noop(a):
    """server.py:1659 does exactly this replace to get a 20px icon."""
    swapped = a.sprite_html(25).replace('class="mon-sprite"', 'class="enc-sprite"')
    assert 'class="enc-sprite"' in swapped, (
        "the enc-sprite swap silently did nothing, so encounter icons rendered at 40px "
        "in a list sized for 20")


def test_sprite_html_is_empty_for_no_species(a):
    assert a.sprite_html(0) == ""


def test_sprite_src_is_period_correct(a):
    """The JSON payload and the HTML must not disagree about which era they render.

    Inheriting the base default served modern artwork here while sprite_html served
    8-bit Red/Blue sprites -- on the same stream layout.
    """
    assert "generation-i/red-blue" in a.sprite_src(25)
    assert "generation-i/red-blue" in a.sprite_html(25)
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
    """The dashboard renders the player's own party through html_render.status_icon_html
    and the PARTNER column through adapter.status_token. If the two disagree, one mon
    shows PSN and its linked half shows nothing."""
    from server.html_render import status_icon_html
    for value in (0x01, 0x07, 0x08, 0x10, 0x20, 0x40):
        tok = a.status_token(value)
        icon = status_icon_html(value)
        assert tok and tok in icon, f"0x{value:02X}: token={tok!r} icon={icon!r}"


# ── badges + box index (client-side conventions) ─────────────────────────

def _client_src():
    """Source with Lua comments stripped.

    Required, not tidiness: the fixes below are documented in comments that name
    the OLD call, so a raw substring search matches the explanation of the bug and
    reports the bug as still present.
    """
    with open(os.path.join(REPO, "lua", "clients", "gen1_rby_client.lua"),
              encoding="utf-8") as f:
        src = f.read()
    src = re.sub(r"--\[\[.*?\]\]", "", src, flags=re.S)
    return re.sub(r"--[^\n]*", "", src)


def test_badges_are_sent_as_a_mask():
    """A count here lit the wrong badges: 3 badges lit Boulder+Cascade, 8 lit Rainbow."""
    src = _client_src()
    assert "readBadgeCount" not in src, "badges must be the raw bitmask, not a popcount"
    assert src.count("readBadgeMask()") >= 2, "expected hello and tick to send the mask"


def test_box_snapshot_reports_the_active_box():
    """`box = 0` labelled every boxed mon "Box 1", and made Box 12's contents report as
    box 0 here AND box 11 from the memorial read -- so the server saw dead keys in a
    regular box and re-queued memorialize every tick."""
    src = _client_src()
    assert not re.search(r"box\s*=\s*0\s*,\s*--\s*active box", src), (
        "the active-box index is still hardcoded to 0")
    assert "getCurrentBoxNum" in src
