"""Contracts for the phone shell + live announcements layered onto the pair board.

`test_dashboard_contract.py` proves the board's DOM; this proves the two things added on
top of it in this branch:

  * the announcer/toggle/toast-host markup sits OUTSIDE `#content`, the htmx morph target
    -- inside it, the 2s poll would rebuild (and read aloud) the whole board every tick,
    exactly the mistake `docs/public_ui/mobile-a11y.md` #4 calls out.
  * dashboard.js's board-announcer diff: a pair's section-class transition (pending ->
    party = a new link, anything -> fallen = a death) drives one sr-only announcement and
    one toast per event -- never for a dead zone, where both halves stay `.empty` -- and
    both are suppressed while paused with no replay flood on unpause.

The phone drawer and the slim side-by-side pair layout are CSS media queries with no
Python- or Node-testable behaviour; those were checked by hand in a browser at 320/360/900px
(see the task report), which is the harness the repo already uses for that (mobile-a11y.md
"Unverified and open").
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio

from tests.unit.test_dashboard_contract import parse

pytest_plugins = ["tests.unit.populated_server"]

JS = Path(__file__).resolve().parents[2] / "server" / "static" / "dashboard.js"


# ── template contract: the announcer lives outside the morph target ────────────────────

@pytest_asyncio.fixture
async def dashboard(populated):
    srv, client = populated
    resp = await client.get("/")
    assert resp.status == 200
    return srv, parse(await resp.text())


@pytest.mark.asyncio
async def test_announcer_and_toasts_sit_outside_the_polled_content(dashboard):
    _, dom = dashboard
    content = dom.find(id="content")
    assert content, "no #content"
    inside_ids = {n.get("id") for n in content.walk() if n.get("id")}
    for wanted in ("mk-announcer", "mk-announce-toggle", "mk-toast-host"):
        assert wanted not in inside_ids, (
            f"#{wanted} is inside the polled #content -- it would be rebuilt (and, for the "
            "announcer, read aloud) on every 2s swap"
        )
    announcer = dom.find(id="mk-announcer")
    assert announcer is not None
    assert announcer.get("role") == "status"
    assert announcer.get("aria-live") == "polite"
    assert announcer.get("aria-atomic") == "true"
    toggle = dom.find(id="mk-announce-toggle")
    assert toggle is not None and toggle.get("aria-pressed") == "false"
    assert dom.find(id="mk-toast-host") is not None


# ── dashboard.js: the pair-transition diff that drives the announcer + toasts ──────────
# Node runs the file against a hand-rolled DOM stub, same approach as test_dashboard_js.py
# (the repo has no JS test runner). The stub is just enough of #content, .mk-pair articles
# and .mk-half halves for sectionOf()/isRealPair()/nickOf()/areaOf() to walk.

STUB = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');

function classSet(s) { return new Set((s || '').split(/\s+/).filter(Boolean)); }
function classList(el) {
  return {
    contains: c => el._cls.has(c),
    add: c => el._cls.add(c),
    remove: c => el._cls.delete(c),
    toggle(c, on) { if (on === undefined) on = !el._cls.has(c); el._cls[on ? 'add' : 'delete'](c); return on; },
  };
}
function makeEl(cls) {
  const el = {
    _cls: classSet(cls), _ls: {}, className: cls || '', textContent: '', children: [], hidden: false,
    appendChild(c) { this.children.push(c); return c; },
    remove() {}, focus() {},
    setAttribute() {}, getAttribute: () => null, removeAttribute() {},
    addEventListener(t, f) { (this._ls[t] = this._ls[t] || []).push(f); },
    querySelector: () => null, querySelectorAll: () => [],
  };
  el.classList = classList(el);
  return el;
}
function fakeNick(text) {
  return { textContent: text, cloneNode: () => ({ textContent: text, querySelectorAll: () => [] }) };
}
function fakeHalf(side, empty) { return makeEl('mk-half ' + side + (empty ? ' empty' : '')); }
function fakePair(id, section, opts) {
  opts = opts || {};
  const el = makeEl('mk-pair ' + section);
  el.id = id;
  const a = fakeHalf('a', opts.aEmpty), b = fakeHalf('b', opts.bEmpty);
  el.querySelector = function(sel) {
    if (sel === '.mk-half.a') return a;
    if (sel === '.mk-half.b') return b;
    if (sel === '.mk-half.a .mk-half-nick') return fakeNick(opts.aNick || 'A-mon');
    if (sel === '.mk-half.b .mk-half-nick') return fakeNick(opts.bNick || 'B-mon');
    if (sel === '.mk-bond-area') return { textContent: opts.area || id };
    return null;
  };
  return el;
}
function fireOn(el, type, ev) {
  ev = ev || {}; ev.type = type;
  for (const f of ((el._ls && el._ls[type]) || [])) f(ev);
  return ev;
}

const store = {};
global.localStorage = { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); },
  removeItem: k => { delete store[k]; } };

// The board on first paint: route1 half-caught (pending), route2 already linked. This is
// what dashboard.js's own `var prev = snapshot()` sees at load -- it must never announce
// either as new just because the script only just started watching.
const pairsArr = [
  fakePair('pair-route1', 'pending', { aEmpty: false, bEmpty: true, area: 'Route 1' }),
  fakePair('pair-route2', 'party', { area: 'Route 2', aNick: 'Squirtle', bNick: 'Bulbasaur' }),
];
const banner = makeEl('phase-banner phase-running');
const contentEl = {
  querySelectorAll(sel) { return sel === '.mk-pair[id]' ? pairsArr : []; },
  querySelector(sel) { return sel === '.phase-banner' ? banner : null; },
};
const announcer = makeEl('sr-only');
const toastHost = makeEl('');
const toggle = makeEl('');

function bus() {
  const ls = {};
  return { ls, addEventListener(t, f) { (ls[t] = ls[t] || []).push(f); } };
}
const body = Object.assign(bus(), { className: '', classList: { contains: () => false } });
const doc = Object.assign(bus(), { readyState: 'complete', hidden: false, body,
  querySelector: () => null, querySelectorAll: () => [],
  getElementById: id => ({ 'mk-announcer': announcer, 'mk-toast-host': toastHost,
                            'mk-announce-toggle': toggle, content: contentEl }[id] || null),
  createElement: () => makeEl('') });
const win = bus();
global.window = win; global.document = doc; global.location = { pathname: '/', href: 'http://x/' };
win.localStorage = global.localStorage;
global.requestAnimationFrame = f => f();
global.setTimeout = f => { f(); return 1; };   // run the announce/fade timers synchronously
global.clearTimeout = () => {};
win.setTimeout = global.setTimeout; win.clearTimeout = global.clearTimeout;   // dashboard.js calls window.setTimeout

function fire(type, ev) {
  ev = ev || {}; ev.type = type;
  for (const f of (body.ls[type] || [])) f(ev);
  return ev;
}

new Function(src)();   // captures `prev` from pairsArr above, wires up #mk-announce-toggle

function poll(nextPairs, runOver) {
  pairsArr.length = 0;
  nextPairs.forEach(p => pairsArr.push(p));
  banner.classList[runOver ? 'add' : 'remove']('phase-game_over');
  toastHost.children.length = 0;
  announcer.textContent = '';
  fire('htmx:afterSettle', {});
  return { toasts: toastHost.children.map(c => c.className), announced: announcer.textContent };
}

const out = {};

// route1 completes (pending -> party): the one new link. route2 is unchanged.
out.newLink = poll([
  fakePair('pair-route1', 'party', { area: 'Route 1', aNick: 'Pikachu', bNick: 'Eevee' }),
  fakePair('pair-route2', 'party', { area: 'Route 2' }),
], false);

// route2's pair dies. route1 is unchanged (no duplicate).
out.death = poll([
  fakePair('pair-route1', 'party', { area: 'Route 1' }),
  fakePair('pair-route2', 'fallen', { area: 'Route 2', aNick: 'Squirtle', bNick: 'Bulbasaur' }),
], false);

// A dead zone appears (fallen, but both halves stay .empty -- nobody caught anything) and
// a fresh pending capture starts. Neither is a link or a death: silence.
out.silentDeadZoneAndPending = poll([
  fakePair('pair-route1', 'party', { area: 'Route 1' }),
  fakePair('pair-route2', 'fallen', { area: 'Route 2' }),
  fakePair('pair-route3', 'fallen', { aEmpty: true, bEmpty: true, area: 'Route 3' }),
  fakePair('pair-route4', 'pending', { aEmpty: false, bEmpty: true, area: 'Route 4' }),
], false);

// Pause, then route4 completes while paused: no sr-only text, no toast.
fireOn(toggle, 'click', {});
out.pauseFlagAfterClick = store['slink-announce-paused'];
out.whilePaused = poll([
  fakePair('pair-route1', 'party', { area: 'Route 1' }),
  fakePair('pair-route2', 'fallen', { area: 'Route 2' }),
  fakePair('pair-route3', 'fallen', { aEmpty: true, bEmpty: true, area: 'Route 3' }),
  fakePair('pair-route4', 'party', { area: 'Route 4', aNick: 'Charmander', bNick: 'Totodile' }),
], false);

// Unpause with nothing further changed: the missed link must not replay.
fireOn(toggle, 'click', {});
out.pauseFlagAfterSecondClick = store['slink-announce-paused'];
out.afterUnpauseNoReplay = poll([
  fakePair('pair-route1', 'party', { area: 'Route 1' }),
  fakePair('pair-route2', 'fallen', { area: 'Route 2' }),
  fakePair('pair-route3', 'fallen', { aEmpty: true, bEmpty: true, area: 'Route 3' }),
  fakePair('pair-route4', 'party', { area: 'Route 4' }),
], false);

// The run ends.
out.runOver = poll([
  fakePair('pair-route1', 'party', { area: 'Route 1' }),
  fakePair('pair-route2', 'fallen', { area: 'Route 2' }),
  fakePair('pair-route3', 'fallen', { aEmpty: true, bEmpty: true, area: 'Route 3' }),
  fakePair('pair-route4', 'party', { area: 'Route 4' }),
], true);

console.log(JSON.stringify(out));
"""


def _run() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    res = subprocess.run([node, "-e", STUB, str(JS)],
                          capture_output=True, text=True, timeout=30, check=True)
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_a_pending_capture_becoming_linked_announces_once():
    out = _run()
    assert len(out["newLink"]["toasts"]) == 1, out["newLink"]
    assert out["newLink"]["toasts"][0] == "mk-toast mk-toast-link"
    assert out["newLink"]["announced"] == "New link at Route 1: Pikachu & Eevee."


def test_a_pair_falling_announces_once_and_not_the_unrelated_pair():
    out = _run()
    assert len(out["death"]["toasts"]) == 1, out["death"]
    assert out["death"]["toasts"][0] == "mk-toast mk-toast-death"
    assert out["death"]["announced"] == "Route 2 pair has fallen: Squirtle & Bulbasaur."


def test_a_dead_zone_and_a_fresh_pending_capture_stay_silent():
    """A dead zone lands in the same `fallen` section as a real pair death (both halves
    stay `.empty`); a pending capture is deliberately not announced until it links.
    Neither may reach the live region or a toast."""
    out = _run()
    assert out["silentDeadZoneAndPending"]["toasts"] == []
    assert out["silentDeadZoneAndPending"]["announced"] == ""


def test_pausing_suppresses_and_unpausing_does_not_replay_the_missed_event():
    out = _run()
    assert out["pauseFlagAfterClick"] == "1"
    assert out["whilePaused"]["toasts"] == [], "announced while paused"
    assert out["whilePaused"]["announced"] == ""
    assert out["pauseFlagAfterSecondClick"] == "0"
    assert out["afterUnpauseNoReplay"]["toasts"] == [], "replayed the link it missed while paused"
    assert out["afterUnpauseNoReplay"]["announced"] == ""


def test_the_run_ending_announces_once():
    out = _run()
    assert out["runOver"]["toasts"] == ["mk-toast mk-toast-over"]
    assert out["runOver"]["announced"] == "The run is over."
