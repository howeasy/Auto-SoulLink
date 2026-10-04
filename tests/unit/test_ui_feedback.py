"""Failures the UI used to swallow, and the phone-width board.

- conn-watch.js: a poll that stops getting answers says so (board strip, dimmed overlay)
  and clears on the next good poll. Run in node against a stand-in document.
- The overlay gallery's Copy button works off a secure origin (the LAN Manager).
- At <=600px the board hides ability/item and the bond state visually, not from readers.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "server" / "static"
TEMPLATES = ROOT / "server" / "templates"


def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ── connection lost ────────────────────────────────────────────────────────────────────

_CONN_HARNESS = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const handlers = {};
const classes = new Set();
const strip = { textContent: '' };
global.document = {
  addEventListener: (n, f) => { (handlers[n] = handlers[n] || []).push(f); },
  body: { classList: { toggle: (c, on) => { on ? classes.add(c) : classes.delete(c); } } },
  querySelectorAll: () => [strip],
};
eval(src);
const poll = { getAttribute: k => (k === 'hx-trigger' ? 'every 2s' : null) };
const form = { getAttribute: () => 'submit' };
const fire = (n, detail) => (handlers[n] || []).forEach(f => f({ detail }));
const snap = () => ({ lost: classes.has('conn-lost'), text: strip.textContent });
const out = {};
fire('htmx:sendError', { elt: form });                 out.other = snap();
fire('htmx:afterRequest', { elt: poll, successful: false });
fire('htmx:sendError', { elt: poll });                 out.down = snap();
fire('htmx:afterRequest', { elt: poll, successful: true }); out.back = snap();
fire('htmx:responseError', { elt: poll });             out.err500 = snap();
console.log(JSON.stringify(out));
"""


def test_conn_watch_marks_a_failed_poll_and_clears_on_the_next_good_one():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    res = subprocess.run([node, "-e", _CONN_HARNESS, str(STATIC / "conn-watch.js")],
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert out["other"] == {"lost": False, "text": ""}      # a non-poll request is not the link
    assert out["down"]["lost"] and out["down"]["text"].startswith("Connection lost")
    assert out["back"] == {"lost": False, "text": ""}
    assert out["err500"]["lost"]


@pytest.mark.parametrize("page", ["dashboard.html", "manager.html", "stream/_base.html"])
def test_every_polling_page_loads_conn_watch(page):
    assert '<script src="/static/conn-watch.js" defer></script>' in _src(TEMPLATES / page)


def test_board_has_the_strip_outside_the_polled_fragment_and_overlays_dim():
    board = _src(TEMPLATES / "_board.html")
    strip = board.index('<div class="mk-connlost" role="status"></div>')
    assert strip < board.index('<div id="content"')
    css = _src(STATIC / "board.css")
    assert ".mk-connlost:empty { display: none; }" in css
    assert "body.stream.conn-lost #root" in _src(STATIC / "slink.css")


# ── copy button ────────────────────────────────────────────────────────────────────────

def test_copy_feature_tests_the_clipboard_and_falls_back():
    src = _src(TEMPLATES / "stream_index.html")
    body = re.search(r"    copy\(\) \{(.*?)\n    \},", src, re.S).group(1)
    assert "navigator.clipboard && window.isSecureContext" in body
    assert "document.execCommand('copy')" in body
    assert "'Copied'" in body and "'Press Ctrl+C'" in body
    assert 'x-text="copyMsg"' in src and 'role="status"' in src


# ── phone width ────────────────────────────────────────────────────────────────────────

def _media_600(css: str) -> str:
    start = css.index("@media (max-width: 600px)")
    depth, i = 0, css.index("{", start)
    for j in range(i, len(css)):
        depth += {"{": 1, "}": -1}.get(css[j], 0)
        if depth == 0:
            return css[i:j]
    raise AssertionError("unclosed @media")


def test_phone_width_hides_visually_not_from_screen_readers():
    css = _src(STATIC / "board.css")
    block = _media_600(css)
    for sel in (".mk-pair .mk-sub.faint", ".mk-bond-state"):
        rule = re.search(re.escape(sel) + r"\s*\{([^}]*)\}", block).group(1)
        assert "display: none" not in rule and "clip: rect(0, 0, 0, 0)" in rule, sel
    compact = re.search(r"\.mk-pairs\.compact \.mk-sub\.faint\s*\{([^}]*)\}", css).group(1)
    assert "display: none" not in compact
    area = re.search(r"\.mk-bond-area\s*\{([^}]*)\}", block).group(1)
    assert "white-space: normal" in area and "line-clamp: 2" in area
    # an auto spine column would just widen to fit the route on one line
    assert "fit-content(" in re.search(r"\.mk-pair\s*\{([^}]*)\}", block).group(1)


# ── the overlay gallery's Alpine component, run in node ────────────────────────────────

_LAUNCHER_HARNESS = r"""
const html = require('fs').readFileSync(process.argv[1], 'utf8');
const src = /<script>\s*(function overlayLauncher\(\)[\s\S]*?)<\/script>/.exec(html)[1];
global.window = global;
window.SLINK_LAYOUT_LABELS = {}; window.SLINK_ALL_FILTERS = []; window.SLINK_DEFAULT_FILTERS_ON = [];
global.localStorage = { getItem: () => null };
window.location = { origin: 'http://192.168.1.5:8090' };
window.isSecureContext = false;                       // the LAN Manager: no navigator.clipboard
global.document = {
  body: { appendChild() {} },
  createElement: () => ({ style: {}, setAttribute() {}, select() {}, remove() {} }),
  execCommand: () => process.argv[2] === 'exec-ok',
};
window.getSelection = () => ({ selectAllChildren() {} });
eval(src);
const reply = JSON.parse(process.argv[3]);
global.fetch = () => reply.network ? Promise.reject(new Error('Failed to fetch'))
  : Promise.resolve({ ok: reply.status < 400, status: reply.status, json: () => Promise.resolve(reply.body) });
const o = overlayLauncher();
o.$refs = { urlBox: {} };
o.catalog = { x: { slug: 'x', layouts: [''] } }; o.active = 'x';
o.copy();
o.attemptsValue = 4;
o.setAttempts();
setTimeout(() => console.log(JSON.stringify({ copy: o.copyMsg, attempts: o.attemptsMsg })), 50);
"""


def _launcher(exec_ok: bool, reply: dict) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    res = subprocess.run([node, "-e", _LAUNCHER_HARNESS, str(TEMPLATES / "stream_index.html"),
                          "exec-ok" if exec_ok else "exec-refused", json.dumps(reply)],
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_copy_off_a_secure_origin_copies_or_asks_for_ctrl_c():
    ok = {"status": 200, "body": {"ok": True, "attempts_count": 4}}
    assert _launcher(True, ok)["copy"] == "Copied"
    assert _launcher(False, ok)["copy"] == "Press Ctrl+C"


@pytest.mark.parametrize("reply, said", [
    ({"status": 200, "body": {"ok": True, "attempts_count": 4}}, "Saved: attempt #4"),
    ({"status": 400, "body": {"ok": False, "error": "count must be a non-negative integer"}},
     "Not saved: count must be a non-negative integer"),
    ({"status": 503, "body": {"ok": False, "error": "proxy_failed"}}, "Not saved: the run did not answer"),
    ({"network": True}, "Not saved: Failed to fetch"),
])
def test_set_attempts_reports_what_the_server_said(reply, said):
    assert _launcher(True, reply)["attempts"] == said


# ── rail game chip, product name ───────────────────────────────────────────────────────

def test_rail_shows_each_runs_game_as_plain_text():
    import jinja2
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATES), autoescape=True,
                             undefined=jinja2.ChainableUndefined)
    runs = [{"run_id": "r1", "name": "Kanto", "status": "running", "game_label": "Radical Red"},
            {"run_id": "r2", "name": "Johto", "status": "stopped", "game_label": ""}]
    html = env.get_template("_rail.html").render(runs=runs, run=runs[0], page="run", base="/runs/r1")
    assert '<span class="mk-rail-game">Radical Red</span>' in html
    assert html.count("mk-rail-game") == 1          # nothing for an undetected game
    assert ".mk-rail-game {" in _src(STATIC / "board.css")


def test_templates_use_the_products_own_name():
    for p in TEMPLATES.rglob("*.html"):
        src = _src(p)
        assert "Auto-SoulLink" not in src, p
        assert "Pokemon Yellow" not in src, p
