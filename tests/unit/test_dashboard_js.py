"""dashboard.js behaviour, run under node against a hand-rolled DOM stub.

The repo has no JS test runner; node alone is enough to load the file, fire the events
the handlers listen for, and read what they did. Bubbling is modelled as body listeners,
then document listeners, honouring stopPropagation: the order a real click takes.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[2] / "server" / "static" / "dashboard.js"

STUB = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const pathname = process.argv[2];
function bus() {
  const ls = {};
  return { ls, addEventListener(t, f) { (ls[t] = ls[t] || []).push(f); } };
}
const body = Object.assign(bus(), { className: '', classList: { contains: () => false } });
const doc = Object.assign(bus(), { body, readyState: 'complete', hidden: false,
  querySelector: () => null, querySelectorAll: () => [], getElementById: () => null });
const win = bus();
const store = {};
const timers = [];
const opened = [];
global.window = win; global.document = doc; global.location = { pathname, href: 'http://x' + pathname };
global.localStorage = { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); },
  removeItem: k => { delete store[k]; } };
win.localStorage = global.localStorage;
win.open = (url, name) => { opened.push([url, name]); return null; };
global.setTimeout = (f) => { timers.push(f); return timers.length; };
global.clearTimeout = (id) => { if (id) timers[id - 1] = null; };
function fire(type, ev) {
  ev.type = type; ev.stopped = false; ev.defaultPrevented = false;
  ev.stopPropagation = () => { ev.stopped = true; };
  ev.preventDefault = () => { ev.defaultPrevented = true; };
  for (const t of [body, doc]) {
    for (const f of (t.ls[type] || [])) f(ev);
    if (ev.stopped) break;
  }
  return ev;
}
new Function(src)();
const out = {};

// A Calc button inside a keyed trainer-row summary.
const details = { tagName: 'DETAILS', open: false, getAttribute: () => 'tr:a:route1:7' };
const summary = { parentElement: details };
const btn = { dataset: { calcLabel: 'Lt. Surge' },
  closest: sel => (sel === '.tr-calc-btn' ? btn : sel === 'summary' ? summary : null) };
fire('click', { target: btn });
out.opened = opened;
out.detailsKey = store['slink-details-open:tr:a:route1:7'] || null;

// Mouse-interaction pause: a stale mouseup timer must not end a newer press.
fire('mousedown', {}); fire('mouseup', {}); fire('mousedown', {});
for (const f of timers.splice(0)) if (f) f();
const swap = fire('htmx:beforeSwap', {});
out.swapVetoedWhilePressed = swap.defaultPrevented;
fire('mouseup', {});
for (const f of timers.splice(0)) if (f) f();
out.swapVetoedAfterRelease = fire('htmx:beforeSwap', {}).defaultPrevented;
console.log(JSON.stringify(out));
"""


def _run(pathname: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    res = subprocess.run([node, "-e", STUB, str(JS), pathname],
                         capture_output=True, text=True, timeout=30, check=True)
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_calc_button_opens_the_run_servers_calc_with_the_trainer_in_the_url():
    out = _run("/")
    assert out["opened"] == [["/calc/normal.html?prep=Lt.%20Surge", "rrCalc"]]


def test_calc_button_on_a_manager_run_page_opens_that_runs_calc():
    out = _run("/runs/r-42")
    assert out["opened"] == [["/runs/r-42/calc/normal.html?prep=Lt.%20Surge", "rrCalc"]]


def test_calc_button_click_leaves_the_rows_saved_open_state_alone():
    assert _run("/")["detailsKey"] is None


def test_a_stale_mouseup_timer_does_not_end_a_newer_press():
    out = _run("/")
    assert out["swapVetoedWhilePressed"] is True
    assert out["swapVetoedAfterRelease"] is False


def test_the_calc_bridge_reads_the_prep_param_the_button_sends():
    """Source-level only: the bridge is one IIFE over the calc page's DOM. A fresh calc tab
    never hears the storage event, so ?prep= is what lands it on the Prep tab."""
    src = (JS.parents[2] / "calc" / "src" / "js" / "slink_bridge.js").read_text(encoding="utf-8")
    assert "URLSearchParams(window.location.search).get('prep')" in src
    assert "_activeTab = 'prep'; }" in src


_SETS_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const fn = /(  function _maybeLoadGameSets[\s\S]*?\r?\n  \}\r?\n)/.exec(src)[1];
const pending = [];
const window = { CUSTOMSETDEX_C: { Onix: { 'Leader Falkner': {} } } };
const document = { createElement: () => ({}), head: { appendChild: s => pending.push(s) } };
let _gameSetdex = null, _gameIndex = {}, _gameSetsLoadStarted = false, _gameSetsFile = null,
    _gameSetsLoad = 0, _setdexReady = false;
const _isRR = () => false, _buildTrainerIndex = d => d, _enrichEnemyMons = () => {},
      refreshPanel = () => {};
eval(fn);
const crystal = { sets: { file: 'Crystal.js', var: 'CUSTOMSETDEX_C' } };
_maybeLoadGameSets(crystal); pending.shift().onload();
const loaded = !!_gameSetdex;
_maybeLoadGameSets({ gen: 2 });                       // Gold joins: set-less profile
const cleared = _gameSetdex === null && Object.keys(_gameIndex).length === 0;
_maybeLoadGameSets(crystal); const late = pending.shift();
_maybeLoadGameSets({ gen: 2 }); late.onload();        // Crystal.js lands after the switch
const lateIgnored = _gameSetdex === null;
_maybeLoadGameSets(crystal); const first = pending.shift();   // back to Crystal, twice:
_maybeLoadGameSets({ gen: 2 });
_maybeLoadGameSets(crystal); pending.shift().onload();
first.onerror();                                      // the older attempt fails late
console.log(JSON.stringify({ loaded, cleared, lateIgnored, staleErrorIgnored: !!_gameSetdex }));
"""


def test_the_bridge_drops_trainer_sets_when_the_profile_loses_them():
    """Review cx-283a3992: Crystal + Gold now shares a set-less Gen 2 profile. The bridge
    used to keep whatever sets an earlier payload loaded, so Crystal's trainers matched the
    Gold player's fights."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    bridge = JS.parents[2] / "calc" / "src" / "js" / "slink_bridge.js"
    res = subprocess.run([node, "-e", _SETS_HARNESS, str(bridge)],
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout) == {"loaded": True, "cleared": True, "lateIgnored": True,
                                       "staleErrorIgnored": True}
