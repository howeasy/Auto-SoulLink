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

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _dashboard_sources() -> dict[str, str]:
    """Everything that renders the dashboard, wherever it lives right now.

    The dashboard was `SLinkServer._build_status_html` (f-strings) and is now
    `server/templates/dashboard.html`. This reads the builder while one exists, plus every
    template, keyed by name so a failure says where; a grep of all of `server.py` would pass
    vacuously while the literals lived on in a template.

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
        # templates/pages/ are the raw debug / Twitch / OBS pages, single-theme by design and
        # substituted with str.replace, not rendered by Jinja. They join this set when they
        # are re-themed on the tokens, not before.
        if os.sep + "pages" + os.sep in path:
            continue
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
