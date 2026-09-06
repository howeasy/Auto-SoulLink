"""Every `<use href="#i-…">` must resolve to a `<symbol>` the page actually includes.

An unresolved `<use>` renders as *nothing* — no error, no console warning, no layout shift. The
stream overlays referenced `#i-x` (dead pair), `#i-sparkle` (shiny) and `#i-cross` (memorial)
while their base template never included the sprite, so those markers were silently missing from
every OBS scene.

This walks the template tree rather than asserting on the three known cases, so the whole class
is caught: a new icon reference in a template whose base lacks the sprite fails here.
"""
import os
import re

import pytest

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                   "server", "templates")

USE_RE = re.compile(r'href="#(i-[a-z0-9-]+)"')
SYMBOL_RE = re.compile(r'<symbol[^>]*\bid="(i-[a-z0-9-]+)"')
EXTENDS_RE = re.compile(r'''{%-?\s*extends\s+["']([^"']+)["']''')
INCLUDE_RE = re.compile(r'''{%-?\s*include\s+["']([^"']+)["']''')
IMPORT_RE = re.compile(r'''{%-?\s*(?:from|import)\s+["']([^"']+)["']''')


def _templates():
    for root, _dirs, files in os.walk(TPL):
        for fn in files:
            if fn.endswith(".html"):
                yield os.path.relpath(os.path.join(root, fn), TPL).replace("\\", "/")


def _read(rel):
    with open(os.path.join(TPL, rel), encoding="utf-8") as f:
        return f.read()


def _symbols_reachable_from(rel, _seen=None):
    """Symbol ids available to `rel`, following its extends chain and includes."""
    _seen = _seen if _seen is not None else set()
    if rel in _seen or not os.path.exists(os.path.join(TPL, rel)):
        return set()
    _seen.add(rel)
    src = _read(rel)
    out = set(SYMBOL_RE.findall(src))
    for parent in EXTENDS_RE.findall(src) + INCLUDE_RE.findall(src):
        out |= _symbols_reachable_from(parent, _seen)
    return out


def _dependencies(rel, seen=None):
    seen = seen if seen is not None else set()
    if rel in seen:
        return seen
    seen.add(rel)
    source = _read(rel)
    for child in EXTENDS_RE.findall(source) + INCLUDE_RE.findall(source) + IMPORT_RE.findall(source):
        _dependencies(child, seen)
    return seen


ALL_SYMBOLS = set(SYMBOL_RE.findall(_read("_svg_icons.html")))


@pytest.mark.parametrize("rel", sorted(t for t in _templates() if USE_RE.search(_read(t))))
def test_icon_references_resolve(rel):
    used = set(USE_RE.findall(_read(rel)))
    # A partial rendered INTO another page inherits that page's sprite; only templates that are a
    # page in their own right (they extend a base) can be checked in isolation.
    src = _read(rel)
    hosts = [rel] if EXTENDS_RE.search(src) else [
        page for page in _templates() if EXTENDS_RE.search(_read(page)) and rel in _dependencies(page)]
    assert hosts, f"{rel} has no tested page composition"
    for page in hosts:
        missing = sorted(used - _symbols_reachable_from(page))
        assert not missing, (
            f"{rel} in {page} uses {missing} but its page does not include their symbols")


def test_every_referenced_icon_exists_somewhere():
    """Catches a typo'd id even in a partial, which the per-template check has to skip."""
    used = set()
    for rel in _templates():
        used |= set(USE_RE.findall(_read(rel)))
    unknown = sorted(used - ALL_SYMBOLS)
    assert not unknown, f"referenced icons that no <symbol> defines: {unknown}"


@pytest.mark.parametrize("page,icon", [
    ("stream/links.html", "i-x"),              # dead pair
    ("stream/encounters.html", "i-sparkle"),   # shiny
    ("stream/stream_memorial.html", "i-cross"),  # actual memorial route template
])
def test_the_stream_overlays_can_reach_their_markers(page, icon):
    """The specific regression, checked through the real composition.

    A `_*_root.html` partial is included by a page that extends stream/_base.html; the partial on
    its own reaches nothing, which is correct and is why the per-template test skips partials.
    What matters is that the PAGE the route renders can resolve the icon.
    """
    assert os.path.exists(os.path.join(TPL, page)), f"required overlay {page} is missing"
    assert icon in ALL_SYMBOLS
    assert icon in _symbols_reachable_from(page), (
        f"{page} cannot reach {icon} — it renders as empty space in OBS"
    )
