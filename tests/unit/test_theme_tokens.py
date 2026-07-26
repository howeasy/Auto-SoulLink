"""Colour must come from the theme token layer, not from hex literals baked into Python.

The dashboard's HTML is built by f-strings in `server.py`. Where those hardcoded colours, the
theme system could not reach them — most visibly `color:#ff0` on trainer names, which is 1.04:1
on the light theme, i.e. the player's own name was invisible.

These tests are deliberately literal. They pin the specific regressions rather than trying to
express "looks nice", because the failure mode is someone adding one more hex literal.
"""
import re

import pytest

from server.html_render import TYPE_COLOR, _relative_luminance, readable_on


def _contrast(fg: str, bg: str) -> float:
    a, b = _relative_luminance(fg), _relative_luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("type_name,bg", sorted(TYPE_COLOR.items()))
def test_every_type_badge_meets_wcag_aa(type_name, bg):
    """Type is the primary matchup signal in the party, box, encounter list and every overlay.

    A hand-maintained whitelist of five "light" types left nine badges below AA — Steel at
    1.94:1, Grass 2.06, Bug 2.20. Deriving the text colour fixes all of them and cannot drift
    when a new type colour is added.
    """
    assert _contrast(bg, readable_on(bg)) >= 4.5


def test_readable_on_picks_the_higher_contrast_option():
    assert readable_on("#ffffff") == "#000"
    assert readable_on("#000000") == "#fff"


def _server_source() -> str:
    import server.server as m
    with open(m.__file__, encoding="utf-8") as f:
        return f.read()


@pytest.mark.parametrize("literal", [
    "color:#ff0",                 # trainer names — 1.04:1 on light, literally invisible
    "background:#222",            # Recent Events sticky headers — a black band in a cream page
    "border:1px solid #333",
    "background:#b00",            # GAME OVER banner
    "background:#600",            # identity-mismatch banner
])
def test_dashboard_builders_do_not_reintroduce_hardcoded_colours(literal):
    assert literal not in _server_source(), (
        f"{literal!r} bypasses the theme token layer — use a var(--c-*) token so the "
        f"light theme (and every other) can reach it"
    )


def _status_builder_source() -> str:
    """Just `_build_status_html` — the dashboard. Scoping matters: the debug page, the launcher
    and the manager also carry hex literals, but they are separate surfaces with their own
    (single-theme) designs, and lumping them in would make this test claim more than it checks.
    """
    import inspect

    from server.server import SLinkServer
    return inspect.getsource(SLinkServer._build_status_html)


def test_no_bare_hex_text_colours_left_in_the_dashboard_builder():
    """A backstop for the whole class, not just the five known instances above."""
    leftovers = re.findall(r"color:#[0-9a-fA-F]{3,6}", _status_builder_source())
    # #fff over an explicitly token-coloured banner background is deliberate.
    leftovers = [x for x in leftovers if x.lower() not in ("color:#fff", "color:#ffffff")]
    assert leftovers == [], f"hardcoded text colours remain: {sorted(set(leftovers))}"
