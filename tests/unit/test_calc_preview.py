"""The board's in-battle damage preview (server/static/calc-preview.js).

It never worked: it loaded one CommonJS file without the full calc page's shim, and it was
handed numeric move ids the engine cannot look up. These hold the preview to the full page's
engine files and to the names /api/calc/mons already sends.
"""
from __future__ import annotations

import json
import os
import re

import pytest

from server.server import SLinkServer

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(_REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


def _js_list(src: str, name: str) -> list[str]:
    body = re.search(rf"var {name}\s*=\s*\[(.*?)\];", src, re.S).group(1)
    return re.findall(r"'([^']+)'", body)


@pytest.mark.parametrize("page", ["normal", "hardcore"])
def test_preview_loads_the_full_pages_engine_and_sets(page):
    """Same files, same order as the full calc page: the compiled modules only work in the
    order the template lists them, behind its shim."""
    js = _read("server", "static", "calc-preview.js")
    tpl = _read("calc", "src", f"{page}.template.html")
    srcs = re.findall(r'src="\./([^"?]+)', tpl)
    assert _js_list(js, "ENGINE") == [s for s in srcs if s.startswith("calc/")]
    sets = [s for s in srcs if s.startswith("js/data/sets/")][:2]
    assert _js_list(js, f"{page.upper()}_SETS") == sets == [f"js/data/sets/{page}.js",
                                                              "js/data/sets/slink_priority.js"]
    # the template's shim, as window assignments
    assert "var calc = exports = {};" in tpl and "function require() { return exports };" in tpl
    assert "window.calc = window.exports = {};" in js
    assert "window.require = function () { return window.exports; };" in js


@pytest.mark.parametrize("template", ["dashboard.html", "manager.html"])
def test_preview_script_is_included_unconditionally(template):
    """An HTMX swap never adds a <script>; gating it on the ROM type known at page load left a
    board opened before the hello without a preview for the whole run."""
    src = _read("server", "templates", template)
    assert '<script src="/static/calc-preview.js" defer></script>' in src
    assert "calc_preview" not in src


@pytest.mark.asyncio
async def test_calc_preview_sends_names_and_battle_state(tmp_path):
    from tests.unit.populated_server import populate  # a plugin elsewhere: import late

    srv = SLinkServer(data_dir=str(tmp_path))
    close = await populate(srv, "gen3")  # Radical Red; B is in a wild battle
    try:
        details = srv.party_details["b"]
        key = next(k for k, d in details.items() if d.get("active"))
        details[key].update(status_cond=0x10, stat_stages=[8, 6, 4, 6, 6, 6, 6])
        bs = srv.battle_state["b"]
        bs.update(is_doubles=True, is_trainer_battle=True,
                  opponent_class="Gym Leader", opponent_name="Brock")
        foe = dict(bs["enemy_party"][0], status_cond=0x40, stat_stages=[6, 7, 6, 6, 6, 6, 6])

        c = srv._calc_preview("b", [foe])
    finally:
        await close()

    assert c["player_moves"] == ["Ember", "Scratch", "Leer", "Smokescreen"]
    assert c["player_ability"] == "Blaze" and c["player_item"] == "Focus Band"
    assert c["player_status"] == "brn" and c["enemy_status"] == "par"
    assert c["player_boosts"] == {"atk": 2, "spe": -2}
    assert c["enemy_boosts"] == {"def": 1}
    assert c["player_hp_pct"] == 100 and c["enemy_hp_pct"] == 87
    assert c["is_doubles"] is True
    assert c["is_trainer"] is True and c["trainer_key"] == "Gym Leader Brock"


@pytest.mark.asyncio
async def test_calc_attribute_round_trips_quotes(tmp_path):
    """The preview reads one JSON attribute. tojson leaves `"` unescaped, so without
    forceescape a double-quoted attribute ends at the first string in it."""
    from html.parser import HTMLParser

    from aiohttp.test_utils import TestClient, TestServer

    from server.server import build_app
    from tests.unit.populated_server import populate

    srv = SLinkServer(data_dir=str(tmp_path))
    close = await populate(srv, "gen3")
    tricky = {"player_moves": ["King's Shield", 'Say "hi"', "<b>&amp;"], "enemy_species": "X"}
    srv._calc_preview = lambda pid, party: tricky
    client = TestClient(TestServer(build_app(srv)))
    await client.start_server()
    try:
        body = await (await client.get("/")).text()
    finally:
        await client.close()
        await close()

    found = []

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if (a.get("id") or "").startswith("calc-preview-"):
                found.append(json.loads(a["data-calc"]))

    P().feed(body)
    assert found and all(f == tricky for f in found)
