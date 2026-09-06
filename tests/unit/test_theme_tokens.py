"""Colour must come from the theme token layer, not from hex literals baked into Python.

The dashboard's HTML is built by f-strings in `server.py`. Where those hardcoded colours, the
theme system could not reach them — most visibly `color:#ff0` on trainer names, which is 1.04:1
on the light theme, i.e. the player's own name was invisible.

These tests are deliberately literal. They pin the specific regressions rather than trying to
express "looks nice", because the failure mode is someone adding one more hex literal.
"""
import re
from pathlib import Path

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
    return _status_builder_source()


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
    """Scan templates and remaining Python widgets through and after extraction."""
    import inspect

    from server.server import SLinkServer
    templates = sorted((Path(__file__).resolve().parents[2] / "server/templates").rglob("*.html"))
    assert templates and any(path.name == "dashboard.html" for path in templates)
    sources = [path.read_text(encoding="utf-8") for path in templates]
    sources.append((Path(__file__).resolve().parents[2] / "server/dashboard.py").read_text(encoding="utf-8"))
    for name in ("_build_status_html", "_build_dashboard_context", "_encounter_html", "_trainer_panel_html"):
        method = getattr(SLinkServer, name, None)
        if method is not None:
            sources.append(inspect.getsource(method))
    return "\n".join(sources)


def test_no_bare_hex_text_colours_left_in_the_dashboard_builder():
    """A backstop for the whole class, not just the five known instances above."""
    leftovers = re.findall(r"(?:color|background(?:-color)?)\s*:\s*#[0-9a-fA-F]{3,8}\b", _status_builder_source(), re.I)
    # #fff over an explicitly token-coloured banner background is deliberate.
    leftovers = [x for x in leftovers if re.sub(r"\s+", "", x.lower()) not in ("color:#fff", "color:#ffffff")]
    assert leftovers == [], f"hardcoded text colours remain: {sorted(set(leftovers))}"


def test_no_stylesheet_suppresses_focus_rings():
    """Exactly two rules removed keyboard focus indicators. The audit's "72 elements" figure was
    a probe artifact — programmatic .focus() does not set keyboard modality, so Chrome's UA ring
    is suppressed by the measurement itself. The static proof is that there should be no
    `outline: 0` / `outline: none` declarations at all."""
    import glob
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    offenders = []
    for path in glob.glob(os.path.join(root, "server", "static", "**", "*.css"), recursive=True):
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if line.strip().startswith(("/*", "*")):
                    continue
                if re.search(r"outline:\s*(0|none)\b", line):
                    offenders.append(f"{os.path.basename(path)}:{n}")
    assert not offenders, f"focus rings suppressed at: {offenders}"
