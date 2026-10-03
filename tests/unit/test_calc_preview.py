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


_PREVIEW_HARNESS = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const c = JSON.parse(process.argv[2]);
const log = { order: [], dex: [], defender: null };
const div = { style: {}, innerHTML: '',
  getAttribute: k => ({ 'data-in-battle': '1', 'data-calc': JSON.stringify(c) })[k] || null };
let installed = false;
global.document = {
  querySelector: () => div,
  getElementById: id => (id === 'calc-preview-a' ? div : null),
  createElement: () => ({}),
  head: { appendChild(s) { if (!installed) { installed = true; install(); } setImmediate(() => s.onload()); } },
};
global.window = global;
global.location = { pathname: process.argv[3] || '/' };
function install() {  // a recording stand-in for the compiled engine
  const e = window.calc;
  e.useDex = d => { log.order.push('useDex'); log.dex.push(d); };
  e.Generations = { get: n => { log.order.push('gen'); return { num: n }; } };
  e.Pokemon = function (gen, name, opts) {
    if (!log.defender) log.defender = { name, item: opts.item, ability: opts.ability, nature: opts.nature };
    Object.assign(this, { name, species: { baseStats: {} }, rawStats: { hp: 100 },
      maxHP: () => 100, curHP: () => 100 });
  };
  e.Move = function () {}; e.Field = function () {};
  e.calculate = () => ({ damage: [10, 20] });
  window.SETDEX_SV = { Onix: { 'Leader Brock': { level: 12, item: 'Set Item', ability: 'Sturdy' } } };
}
eval(src);
setTimeout(() => console.log(JSON.stringify(log)), 200);
"""


def _run_preview(calc: dict) -> dict:
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    res = subprocess.run([node, "-e", _PREVIEW_HARNESS,
                          os.path.join(_REPO, "server", "static", "calc-preview.js"), json.dumps(calc)],
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


_BASE = {"player_species": "Pikachu", "player_level": 12, "player_moves": ["Thunder"],
         "enemy_species": "Onix", "enemy_level": 12}


def test_preview_runs_purergb_on_its_own_dex_and_vanilla_gen1_on_vanilla():
    """Review cx-66e7600f F1, behaviourally: the dex is picked before any Gen 1 data is read."""
    log = _run_preview({**_BASE, "gen": 1, "dex": "purergb"})
    assert log["dex"] == ["purergb"] and log["order"][:2] == ["useDex", "gen"]
    assert _run_preview({**_BASE, "gen": 1, "dex": "vanilla"})["dex"] == ["vanilla"]
    assert _run_preview({**_BASE, "gen": 3, "dex": "vanilla"})["dex"] == []


def test_preview_defender_uses_the_live_foe_and_an_rr_set_still_wins():
    """Review cx-66e7600f F2: outside a matched RR set the defender carries the live item and
    ability; a matched RR trainer set keeps precedence."""
    live = {"enemy_item": "Leftovers", "enemy_ability": "Rock Head", "enemy_nature": None}
    d = _run_preview({**_BASE, **live, "gen": 3, "dex": "vanilla"})["defender"]
    assert (d["item"], d["ability"]) == ("Leftovers", "Rock Head")
    rr = {**_BASE, **live, "gen": 9, "dex": "rr", "is_trainer": True, "trainer_key": "Leader Brock"}
    d = _run_preview(rr)["defender"]
    assert (d["item"], d["ability"]) == ("Set Item", "Sturdy")


def test_a_repeat_render_neither_hides_nor_rewrites_the_box():
    """The battle flash: every 2 s poll re-rendered the preview by hiding it and rebuilding its
    HTML. An unchanged matchup must leave the box visible and its DOM untouched."""
    harness = _PREVIEW_HARNESS.replace(
        "setTimeout(() => console.log(JSON.stringify(log)), 200);",
        """setTimeout(() => {
  const writes = { display: [], html: 0 };
  let d = div.style.display, h = div.innerHTML;
  Object.defineProperty(div.style, 'display', { get: () => d, set: v => { writes.display.push(v); d = v; } });
  Object.defineProperty(div, 'innerHTML', { get: () => h, set: v => { writes.html++; h = v; } });
  window._slinkCalcRender(); window._slinkCalcRender();
  console.log(JSON.stringify(writes));
}, 200);""")
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    res = subprocess.run([node, "-e", harness, os.path.join(_REPO, "server", "static", "calc-preview.js"),
                          json.dumps({**_BASE, "gen": 3, "dex": "vanilla"})],
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    writes = json.loads(res.stdout)
    assert "none" not in writes["display"], writes
    assert writes["html"] == 0, writes


def test_an_unbuilt_calc_says_so_in_the_now_card_instead_of_hiding():
    """calc/dist missing: every engine script 404s. The preview used to stay hidden with no
    word; it now shows the calc page's own build advice, once, in the battling card."""
    harness = _PREVIEW_HARNESS.replace(
        "setImmediate(() => s.onload());", "setImmediate(() => s.onerror());").replace(
        "setTimeout(() => console.log(JSON.stringify(log)), 200);",
        "setTimeout(() => console.log(JSON.stringify({ html: div.innerHTML, display: div.style.display })), 200);")
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    res = subprocess.run([node, "-e", harness, os.path.join(_REPO, "server", "static", "calc-preview.js"),
                          json.dumps({**_BASE, "gen": 3, "dex": "vanilla"})],
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert out["display"] != "none"
    assert "Damage preview unavailable" in out["html"] and "npm run build" in out["html"]


@pytest.mark.parametrize("path, href", [("/runs/r7", "/runs/r7/calc/normal.html"), ("/", "/calc/normal.html")])
def test_open_in_calc_targets_the_run_being_viewed(path, href):
    """On the Manager an origin-relative /calc/ opened the PINNED run's calc; the link is
    run-scoped like dashboard.js's trainer buttons."""
    harness = _PREVIEW_HARNESS.replace(
        "setTimeout(() => console.log(JSON.stringify(log)), 200);",
        "setTimeout(() => console.log(JSON.stringify({ html: div.innerHTML })), 200);")
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    res = subprocess.run([node, "-e", harness, os.path.join(_REPO, "server", "static", "calc-preview.js"),
                          json.dumps({**_BASE, "gen": 3, "dex": "vanilla"}), path],
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    assert f'href="{href}"' in json.loads(res.stdout)["html"]
