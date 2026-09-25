"""Accessibility of the Manager's cartridge and randomizer forms, as rendered (WCAG 2.2):
one label per control, pickers named for what they pick, radio chips with a single Tab stop
and arrow keys, and live regions for progress and failures."""

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

import server.manager as manager

pytest_plugins = ["tests.unit.manager_harness"]

RANDOMIZER_JS = Path(__file__).resolve().parents[2] / "server" / "static" / "randomizer.js"


async def _pages(client):
    manager._save_registry([{"run_id": "r1", "name": "Duo", "tcp_port": 1, "http_port": 2,
                             "status": "stopped", "pid": None, "game": "gen1"}])
    new = await (await client.get("/new")).text()
    carts = await client.get("/runs/r1/cartridges")
    assert carts.status == 200
    return new, await carts.text()


class _LabelDepth(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = self.deepest = 0

    def handle_starttag(self, tag, attrs):
        if tag == "label":
            self.depth += 1
            self.deepest = max(self.deepest, self.depth)

    def handle_endtag(self, tag):
        if tag == "label":
            self.depth -= 1


@pytest.mark.asyncio
async def test_no_label_is_nested_and_each_control_has_its_own(manager_client):
    for page in await _pages(manager_client):
        parser = _LabelDepth()
        parser.feed(page)
        assert parser.deepest == 1, "a <label> inside a <label> names two controls at once"
        for pair in ((":for=\"'rom-select-' + pid\"", ":id=\"'rom-select-' + pid\""),
                     (":for=\"'rom-file-' + pid\"", ":id=\"'rom-file-' + pid\""),
                     ('for="upr-jar"', 'id="upr-jar"'), ('for="upr-jar-file"', 'id="upr-jar-file"')):
            assert all(p in page for p in pair), pair


@pytest.mark.asyncio
async def test_pickers_are_named_for_what_they_pick(manager_client):
    for page in await _pages(manager_client):
        assert "'Add file…') + ' for the Player ' + pid.toUpperCase() + ' cartridge'" in page
        assert "'Choose randomizer jar…'" in page and "'Pick…'" not in page


@pytest.mark.asyncio
async def test_randomizer_chips_rove_and_take_arrow_keys(manager_client):
    for page in await _pages(manager_client):
        chips = page[page.index('class="mk-rchips"'):]
        assert 'role="radiogroup" :aria-label="o.label" @keydown="radioKeys($event)"' in chips
        assert ':tabindex="chipTab(o, c)"' in chips


@pytest.mark.asyncio
async def test_progress_and_failures_are_announced(manager_client):
    new, carts = await _pages(manager_client)
    live = 'role="status" aria-live="polite"'
    # the create flow: status outside the aria-busy form, the error a persistent alert
    status = new.index(live + ' style=')
    assert "x-text=\"busy ? (stage || 'Creating…') : (uploading ? 'Adding the file…' : uploadNote)\"" in new
    assert status < new.index('<div class="mk-form" :aria-busy="busy || !!uploading">')
    assert 'role="alert" x-text="error"' in new
    # the rebuild flow
    assert carts.count(':aria-busy="busy || !!uploading"') == 2
    assert '<span role="alert" style=' in carts and "(uploadNote || note)" in carts
    # shared by both: the preset note and the preflight result
    for page in (new, carts):
        assert re.search(r'<span role="status" aria-live="polite" style="[^"]*" x-text="presetNote"></span>', page)
        assert "x-text=\"rdraft.randomize && pre ? jarWords() + ', ' + javaWords() : ''\"" in page


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_radio_keys_skip_disabled_chips_and_chip_tab_roves():
    script = RANDOMIZER_JS.read_text(encoding="utf-8") + r"""
function chip(name, disabled) {
  return { name: name, disabled: disabled, focus: function () { document.activeElement = this; },
           click: function () { clicked.push(this.name); } };
}
var clicked = [], document = { activeElement: null };
var radios = [chip('a', false), chip('b', true), chip('c', false), chip('d', false)];
var group = { querySelectorAll: function () { return radios; } };
function press(key, from) {
  document.activeElement = radios[from];
  radioKeys({ key: key, currentTarget: group, preventDefault: function () {} });
  return document.activeElement.name;
}
var o = { key: 'k', choices: [{ value: 1 }, { value: 2, off: true }, { value: 3 }] };
var ctx = { rdraft: { spec: { k: 2 } }, choiceOk: function (o, c) { return !c.off; } };
var tab = randomizerFields({ options: [] }).chipTab;
console.log(JSON.stringify({
  right_from_a: press('ArrowRight', 0), left_from_a: press('ArrowLeft', 0),
  home: press('Home', 3), end: press('End', 0), other: press('x', 2),
  tabs_checked_disabled: o.choices.map(function (c) { return tab.call(ctx, o, c); }),
  tabs_checked_enabled: o.choices.map(function (c) { return tab.call({ rdraft: { spec: { k: 3 } }, choiceOk: ctx.choiceOk }, o, c); }),
  clicked: clicked,
}));
"""
    out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
    assert out["right_from_a"] == "c", "ArrowRight skips the disabled chip"
    assert out["left_from_a"] == "d" and out["home"] == "a" and out["end"] == "d"
    assert out["other"] == "c", "other keys leave focus alone"
    assert out["clicked"] == ["c", "d", "a", "d"], "moving selects"
    assert out["tabs_checked_disabled"] == [0, -1, -1], "a disabled checked chip hands the Tab stop to the first enabled"
    assert out["tabs_checked_enabled"] == [-1, -1, 0]
