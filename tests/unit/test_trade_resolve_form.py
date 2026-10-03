"""The trade-conflict banner's form (_board.html + trade-resolve.js) in place of the hand-written
POST hint. It must post exactly what POST /api/debug/resolve_trade accepts, through the run's
own path on the Manager, ask before it changes rule state, and show the answer inline."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit.test_dashboard_contract import parse

pytest_plugins = ["tests.unit.populated_server"]

STATIC = Path(__file__).resolve().parents[2] / "server" / "static"

# A form stub shaped like the rendered one: radios name="action", selects name="side_a|b".
_HARNESS = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const cfg = JSON.parse(process.argv[2]);
const handlers = {};
global.window = global;
global.location = { pathname: cfg.path };
global.document = { addEventListener: (n, f) => { handlers[n] = f; } };
const out = { textContent: '' }, btn = { disabled: false };
const form = {
  getAttribute: k => (k === 'data-token' ? cfg.token : null),
  closest: () => form,
  querySelector: sel => {
    if (sel === 'input[name="action"]:checked') return cfg.action ? { value: cfg.action } : null;
    const m = /select\[name="side_(.)"\]/.exec(sel);
    if (m) return { value: (cfg.sides || {})[m[1]] || '' };
    if (sel === '.trade-resolve-out') return out;
    if (sel === 'button[type="submit"]') return btn;
    return null;
  },
};
const sent = [];
let asked = '';
window.confirm = q => { asked = q; return cfg.confirm; };
global.fetch = (url, opts) => { sent.push({ url, method: opts.method, body: JSON.parse(opts.body) });
  return Promise.resolve({ ok: cfg.reply.status < 400, status: cfg.reply.status,
                           json: () => Promise.resolve(cfg.reply.body) }); };
eval(src);
handlers.submit({ target: form, preventDefault() {} });
setTimeout(() => console.log(JSON.stringify({ sent, asked, shown: out.textContent })), 50);
"""


def _submit(**cfg) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    cfg = {"path": "/", "token": "t7", "confirm": True,
           "reply": {"status": 200, "body": {"ok": True}}, **cfg}
    res = subprocess.run([node, "-e", _HARNESS, str(STATIC / "trade-resolve.js"), json.dumps(cfg)],
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def _conflict(srv, token="t7"):
    link = next(e for e in srv.state.links if e.a and e.b)
    a_key, b_key = link.a.key, link.b.key
    srv.state.pending_trade = {"token": token, "phase": "conflict", "a_key": a_key, "b_key": b_key,
                               "verdict": {"a": "await", "b": "holds NEITHER"},
                               "problem": "B holds NEITHER mon"}


@pytest.mark.asyncio
async def test_the_banner_renders_a_form_not_a_hand_written_post(populated):
    srv, client = populated
    _conflict(srv)
    html = await (await client.get("/")).text()
    assert "POST /api/debug/resolve_trade {" not in html
    form = parse(html).find("form", id="trade-resolve-t7")
    assert form is not None and form.get("data-token") == "t7" and "data-morph-keep" in form.attrs
    actions = [i.get("value") for i in form.find_all("input", name="action")]
    assert actions == ["adopt", "commit", "rollback"]          # resolve_trade's whole vocabulary
    for pid in ("a", "b"):
        sel = form.find("select", name=f"side_{pid}")
        assert [o.get("value") for o in sel.find_all("option")] == ["", "traded", "none"]
    assert form.find("output", role="status") is not None


@pytest.mark.parametrize("path, url", [("/", "/api/debug/resolve_trade"),
                                       ("/runs/r1", "/runs/r1/api/debug/resolve_trade")])
def test_it_posts_the_exact_body_to_the_runs_own_path(path, url):
    r = _submit(path=path, action="commit", sides={"b": "none"})
    assert r["sent"] == [{"url": url, "method": "POST",
                          "body": {"token": "t7", "action": "commit", "sides": {"b": "none"}}}]
    assert "commit" in r["asked"] and "B none" in r["asked"]
    assert r["shown"].startswith("Resolved")
    # no override: no "sides" key at all
    assert _submit(action="adopt")["sent"][0]["body"] == {"token": "t7", "action": "adopt"}


def test_cancelling_the_confirm_or_picking_nothing_sends_nothing():
    assert _submit(action="rollback", confirm=False)["sent"] == []
    r = _submit()
    assert r["sent"] == [] and r["shown"] == "Pick an action first."


@pytest.mark.asyncio
async def test_the_endpoints_refusal_is_shown_inline(populated):
    """End to end: the body the form builds goes to the real endpoint, and what it answers is
    what the form shows. B's evidence contradicts itself, so commit alone is refused."""
    srv, client = populated
    _conflict(srv)
    body = _submit(action="commit")["sent"][0]["body"]
    resp = await client.post("/api/debug/resolve_trade", json=body)
    reply = {"status": resp.status, "body": await resp.json()}
    assert reply["status"] == 400 and "contradictory evidence" in reply["body"]["error"]
    shown = _submit(action="commit", reply=reply)["shown"]
    assert shown == "Refused: " + reply["body"]["error"]


def test_the_board_refresh_leaves_the_form_alone():
    assert "data-morph-keep" in (STATIC / "dashboard.js").read_text(encoding="utf-8")
