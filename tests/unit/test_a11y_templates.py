"""Accessibility contracts in the shared templates (WCAG 2.2): skip link, landmarks,
aria-current, the board's glyph text, and the theme picker's radio semantics."""
from __future__ import annotations

import re
from pathlib import Path

import jinja2
import pytest

from server import board

TEMPLATES = Path(__file__).resolve().parents[2] / "server" / "templates"


@pytest.fixture(scope="module")
def env():
    # ChainableUndefined: the board's top level reads a whole payload; a macro test only
    # needs the macros, and the rest renders as empty.
    e = jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATES), autoescape=True,
                           undefined=jinja2.ChainableUndefined)
    e.globals.update(hp_pct=board.hp_pct, hp_class=board.hp_class,
                     bond_glyph=board.bond_glyph, rom_label=str)
    return e


def _src(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


# ── skip link + one main per page ──────────────────────────────────────────────────────

def test_skip_link_is_the_first_thing_in_the_body(env):
    html = env.get_template("base.html").render(theme="default")
    after_body = html.split("<body", 1)[1].split(">", 1)[1].lstrip()
    assert after_body.startswith('<a class="skip-link" href="#main-content">Skip to main content</a>')


# memorial.html is another lane's file this round: it still owes id="main-content".
# _smoke.html is a macro harness with no main.
_NO_TARGET_YET = {"base.html", "_smoke.html", "memorial.html"}


@pytest.mark.parametrize("name", sorted(
    p.name for p in TEMPLATES.glob("*.html")
    if '{% extends "base.html" %}' in p.read_text(encoding="utf-8") and p.name not in _NO_TARGET_YET))
def test_every_page_has_exactly_one_main_and_it_is_the_skip_target(name):
    mains = re.findall(r"<main\b[^>]*>", _src(name))
    assert len(mains) == 1, mains
    assert 'id="main-content"' in mains[0] and 'tabindex="-1"' in mains[0]


# ── rail + tabs ─────────────────────────────────────────────────────────────────────────

def test_rail_is_primary_nav_with_the_runs_as_a_group_and_marks_the_current_page(env):
    runs = [{"run_id": "r1", "name": "Kanto", "status": "running"},
            {"run_id": "r2", "name": "Johto", "status": "stopped"}]
    html = env.get_template("_rail.html").render(runs=runs, run=runs[0], page="run", base="/runs/r1")
    assert '<nav class="mk-rail" aria-label="Primary">' in html
    assert '<div class="mk-rail-runs" role="group" aria-label="Runs">' in html
    current = re.findall(r'<a [^>]*aria-current="page"[^>]*>', html)
    assert len(current) == 1 and 'href="/runs/r1"' in current[0]
    # every active link says so, and only those
    for a in re.findall(r"<a [^>]*>", html):
        assert ("active" in a.split('href')[0]) == ('aria-current="page"' in a), a


def test_panel_tabs_mark_the_current_one(env):
    html = env.get_template("panel_page.html").render(
        tabs=[("Board", "/runs/r1", False), ("Calc", "/runs/r1/calc/normal.html", True)],
        runs=[], panel="calc", available=False, theme="default", api_base="/runs/r1")
    tabs = re.findall(r'<a class="mk-tab[^>]*>', html)
    assert ['aria-current="page"' in t for t in tabs] == [False, True]


def test_stream_index_has_one_main():
    src = _src("stream_index.html")
    assert len(re.findall(r"<main\b", src)) == 1
    assert '<section class="pane" aria-label="Overlay settings">' in src


# ── the board ───────────────────────────────────────────────────────────────────────────

def _half(env, **mon):
    h = {"species_name": "Pikachu", "level": 5, "hp": 10, "maxHP": 20, **mon}
    row = {"a": h, "section": "party", "status": "alive"}
    return env.get_template("_board.html").module.half(row, "a", {}, "b")


def test_active_and_shiny_glyphs_are_hidden_behind_words(env):
    html = str(_half(env, active=True, shiny=True))
    assert '<span aria-hidden="true">⚔</span><span class="sr-only">Out in battle</span>' in html
    assert '<span aria-hidden="true">✦</span><span class="sr-only">Shiny</span>' in html


def test_hp_fraction_is_announced_as_hp(env):
    assert '<span class="sr-only">HP </span>10/20' in str(_half(env))


def test_hp_without_a_max_is_a_number_not_a_full_bar(env):
    """The Gen 1 client reads a foe's HP but no max: no bar to fake, no dangling '/'."""
    html = str(env.get_template("_board.html").module.hp({"hp": 17, "maxHP": None}))
    assert "mk-hp-fill" not in html
    assert re.sub(r"<[^>]+>", "", html).strip() == "HP 17"


def test_a_connected_player_with_no_name_yet_is_not_called_not_connected(env):
    players = {pid: {"connected": True, "admission": "admitted", "trainer_name": ""} for pid in "ab"}
    html = env.get_template("_board.html").render(status={"players": players})
    assert "not connected" not in html
    assert "<b>Player A</b>" in html and "<b>Player B</b>" in html


def _battle_card(env, **bs):
    players = {pid: {"connected": True, "admission": "admitted", "trainer_name": "RED"} for pid in "ab"}
    players["a"]["battle_state"] = {"in_battle": True, **bs}
    players["a"]["party_details"] = {}
    brd = {"has_data": {"a": True, "b": False}, "active": {}, "sections": None,
           "badges": {pid: {"slots": 8, "count": 0} for pid in "ab"}}
    return env.get_template("_board.html").render(status={"players": players}, board=brd, live=True)


def test_a_client_sending_null_collections_does_not_break_the_board(env):
    html = _battle_card(env, is_trainer_battle=False, enemy_party=None)
    assert "wild encounter" in html


def test_a_trainer_with_no_class_is_just_vs_the_name(env):
    html = _battle_card(env, is_trainer_battle=True, opponent_class=None, opponent_name="GARY", enemy_party=[])
    assert "vs GARY" in html and "None" not in html


# ── theme picker ────────────────────────────────────────────────────────────────────────

def test_theme_pills_are_radios_with_roving_focus_and_escape(env):
    src = _src("_theme_switcher.html")
    pills = re.findall(r'<button[^>]*class="theme-pill"[^>]*>', src, re.S)
    assert pills
    for p in pills:
        assert 'role="radio"' in p and ':aria-checked=' in p and ':tabindex=' in p
    assert "@keydown.escape" in src
    assert "@keydown.down.prevent=\"move(1)\"" in src and "@keydown.up.prevent=\"move(-1)\"" in src
