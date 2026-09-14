"""Colour must come from the theme token layer, not from hex literals baked into Python.

The dashboard's HTML is built by f-strings in `server.py`. Where those hardcoded colours, the
theme system could not reach them — most visibly `color:#ff0` on trainer names, which is 1.04:1
on the light theme, i.e. the player's own name was invisible.

These tests are deliberately literal. They pin the specific regressions rather than trying to
express "looks nice", because the failure mode is someone adding one more hex literal.
"""
import glob
import os
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


_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _dashboard_sources() -> dict[str, str]:
    """Everything that renders the dashboard, wherever it lives right now.

    The dashboard is moving from `SLinkServer._build_status_html` (f-strings) into
    `server/templates/`. A test pinned to the method alone would raise AttributeError at
    collection the day the method goes -- or worse, a grep of all of `server.py` would keep
    passing vacuously while the literals lived on in a template. So: the builder while it
    exists, plus every template, keyed by name so a failure says where.

    Scoping matters: the debug page, the launcher and the manager carry hex literals too, but
    they are separate surfaces with their own single-theme designs; the debug and OBS pages
    join this set when Phase 7 templates them.
    """
    import inspect

    from server.server import SLinkServer

    out = {}
    builder = getattr(SLinkServer, "_build_status_html", None)
    if builder is not None:
        out["SLinkServer._build_status_html"] = inspect.getsource(builder)
    for path in sorted(glob.glob(os.path.join(_ROOT, "server", "templates", "**", "*.html"),
                                 recursive=True)):
        with open(path, encoding="utf-8") as f:
            out[os.path.relpath(path, _ROOT)] = f.read()
    assert out, "no dashboard source found -- the test is pointed at nothing"
    return out


@pytest.mark.parametrize("literal", [
    "color:#ff0",                 # trainer names — 1.04:1 on light, literally invisible
    "background:#222",            # Recent Events sticky headers — a black band in a cream page
    "border:1px solid #333",
    "background:#b00",            # GAME OVER banner
    "background:#600",            # identity-mismatch banner
])
def test_dashboard_builders_do_not_reintroduce_hardcoded_colours(literal):
    hits = [name for name, src in _dashboard_sources().items() if literal in src]
    assert not hits, (
        f"{literal!r} in {hits} bypasses the theme token layer — use a var(--c-*) token so the "
        f"light theme (and every other) can reach it"
    )


_HEX_PROPERTY = re.compile(r"(?:color|background|border(?:-color)?)\s*:\s*#[0-9a-fA-F]{3,8}")


def test_no_bare_hex_colour_properties_left_in_the_dashboard():
    """A backstop for the whole class, not just the five known instances above.

    `background:#` and `border:#` are in the pattern because a `color:#` regex is what let
    the gym-badge palette through for a year."""
    leftovers = {}
    for name, src in _dashboard_sources().items():
        found = [x for x in _HEX_PROPERTY.findall(src)
                 if x.lower().replace(" ", "") not in ("color:#fff", "color:#ffffff")]
        if found:
            leftovers[name] = sorted(set(found))
    assert leftovers == {}, f"hardcoded colours remain: {leftovers}"


@pytest.mark.xfail(strict=True, reason="GYM_BADGES hardcodes eight hex colours inside "
                   "_build_status_html; Phase 4 replaces it with adapter.gym_badge_slugs")
def test_no_quoted_hex_literals_in_the_dashboard_builder():
    """Colour tables written as Python data (`("#a0a0a0", "Boulder Badge")`) never sit next
    to a CSS property name, so the property regex above cannot see them."""
    src = _dashboard_sources().get("SLinkServer._build_status_html", "")
    quoted = re.findall(r"""["']#[0-9a-fA-F]{6}["']""", src)
    assert quoted == [], f"colour data baked into the builder: {sorted(set(quoted))}"


def test_no_stylesheet_suppresses_focus_rings():
    """Exactly two rules removed keyboard focus indicators. The audit's "72 elements" figure was
    a probe artifact — programmatic .focus() does not set keyboard modality, so Chrome's UA ring
    is suppressed by the measurement itself. The static proof is that there should be no
    `outline: 0` / `outline: none` declarations at all."""
    offenders = []
    for path in glob.glob(os.path.join(_ROOT, "server", "static", "**", "*.css"), recursive=True):
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if line.strip().startswith(("/*", "*")):
                    continue
                if re.search(r"outline:\s*(0|none)\b", line):
                    offenders.append(f"{os.path.basename(path)}:{n}")
    assert not offenders, f"focus rings suppressed at: {offenders}"
