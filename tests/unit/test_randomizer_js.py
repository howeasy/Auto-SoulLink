"""server/static/randomizer.js — the two client-side fixes on top of the manager.py ones.

Runs the actual file under node (loaded with `new Function`, the same trick the syntax
gate uses, then asked to return `randomizerFields` so the object under test is the real
one): no DOM, no Alpine, just the plain methods `cartsWhy()` and `preflight()` exercise
against a stubbed `fetch`.

1. cartsWhy() must block Prepare on an untrusted jar (preflight()'s `jar_trusted: false`),
   surfacing the server's own `jar_error` when it has one instead of routing an untrusted
   jar into a 600-second randomize() call that refuses it anyway.
2. preflight() fires on every watched jar/rom change with no ordering: a slow response to
   an older pick must not land after, and overwrite, a newer pick's answer.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

_JS_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "server", "static", "randomizer.js"))

_PRELUDE = (
    "const fs = require('fs');\n"
    "const src = fs.readFileSync(" + json.dumps(_JS_PATH) + ", 'utf8');\n"
    "const mod = new Function(src + '\\nreturn { randomizerFields };')();\n"
    "const form = { options: [], jar: '', cartridges: null, current: null, "
    "roms: [], presets: [], family: null };\n"
)


def _run_node(tmp_path, body: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not found on PATH")
    script = tmp_path / "harness.js"
    script.write_text(_PRELUDE + body, encoding="utf-8")
    result = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_emerald_family_keeps_its_picks_and_requires_the_fork_without_a_companion(tmp_path):
    from server import upr_settings as U

    out = _run_node(tmp_path, "form.options = " + json.dumps(U.option_form(every_family=True)) + ";\n" + """
const rf = mod.randomizerFields(form);
rf.family = 'gen3_emerald';
rf.roms = [{ path: 'e.gba', clean: true, family: 'gen3_emerald', variant: 'Emerald', title: 'Emerald' },
           { path: 'fr.gba', clean: true, family: 'gen3_frlg', variant: 'FireRed', title: 'FireRed' }];
rf.rdraft.rom_a = rf.rdraft.rom_b = 'e.gba';
rf.rdraft.randomize = true;
rf.pre = { jar_found: true, jar_trusted: true, jar_fork: false, java_found: true };
const noFork = rf.cartsWhy(), companion = rf.companionOk();
rf.pre.jar_fork = true;
console.log(JSON.stringify({ label: rf.familyLabel(rf.family), good: rf.usable(rf.roms[0]),
  wrong: rf.usable(rf.roms[1]), noFork, ready: rf.cartsReady(), companion,
  tutor: rf.optWhy(form.options.find(o => o.key === 'tutors')),
  fossil: rf.optWhy(form.options.find(o => o.key === 'balance_static_levels')),
  group: rf.romGroups()[0].label }));
""")
    assert out["label"] == "Emerald" and out["good"] and not out["wrong"]
    assert "Emerald" in out["noFork"] and "fork jar" in out["noFork"]
    assert out["ready"] and out["tutor"] == "" and out["fossil"] == "not available for Emerald"
    assert not out["companion"]["ok"] and "No Emerald companion build" in out["companion"]["why"]
    assert out["group"].startswith("Emerald")


def test_the_companion_goes_in_wherever_one_exists_with_no_opt_out(tmp_path):
    """Patch-first (owner 2026-10-01): no draft field turns the companion off."""
    from server import cartridges

    out = _run_node(tmp_path, """
form.companion_titles = """ + json.dumps(list(cartridges.COMPANION_TITLES)) + """;
const rf = mod.randomizerFields(form);
rf.roms = [{ path: 'r.gb', variant: 'Red' }, { path: 'b.gb', variant: 'Blue' }, { path: 'y.gbc', variant: 'Yellow' },
           { path: 'c.gbc', variant: 'Crystal', family: 'gen2_gsc' }];
rf.rdraft.rom_a = 'r.gb'; rf.rdraft.rom_b = 'b.gb';
rf.rdraft.companion = false;   // a stale draft field must not opt out
const red = rf.cartridgesBody();
rf.rdraft.rom_b = 'y.gbc';
const yellow = rf.cartridgesBody(), why = rf.companionOk().why;
rf.rdraft.rom_a = rf.rdraft.rom_b = 'c.gbc';
const crystal = rf.cartridgesBody(), gen2why = rf.companionOk().why;
console.log(JSON.stringify({ red: red.companion, yellow: yellow.companion, why, crystal: crystal.companion, gen2why }));
""")
    # The browser always sends patch-first intent; server/cartridges.py decides per player.
    assert out["red"] is True and out["yellow"] is True and out["crystal"] is True
    # It only explains the per-pick exceptions.
    assert "handed out as picked" in out["why"]
    assert "does not admit it yet" in out["gen2why"]


def test_carts_why_blocks_an_untrusted_jar_with_the_servers_own_message(tmp_path):
    out = _run_node(tmp_path, """
const rf = mod.randomizerFields(form);
rf.rdraft.rom_a = 'a.gb';
rf.rdraft.rom_b = 'b.gb';
rf.rdraft.randomize = true;

rf.pre = { jar_found: true, jar_trusted: false, jar_error: 'SERVER MESSAGE HERE', java_found: true };
const withServerMsg = rf.cartsWhy();

rf.pre = { jar_found: true, jar_trusted: false, java_found: true };
const withoutServerMsg = rf.cartsWhy();

rf.pre = { jar_found: true, jar_trusted: true, java_found: true };
const whenTrusted = rf.cartsWhy();

console.log(JSON.stringify({ withServerMsg, withoutServerMsg, whenTrusted }));
""")
    assert out["withServerMsg"] == "SERVER MESSAGE HERE"
    assert "not a known build" in out["withoutServerMsg"]
    assert out["whenTrusted"] == ""


def test_preflight_drops_a_stale_response_that_resolves_after_a_newer_one(tmp_path):
    out = _run_node(tmp_path, """
const rf = mod.randomizerFields(form);

var pendingFirstResolve;
var callIndex = 0;
global.fetch = function (url) {
  var idx = callIndex++;
  if (idx === 0) {
    return new Promise(function (resolve) { pendingFirstResolve = resolve; }); // never settles on its own
  }
  return Promise.resolve({ ok: true, json: function () { return Promise.resolve({ tag: 'second-response' }); } });
};

(async function () {
  var p1 = rf.preflight();   // the slow call for an OLDER pick, still pending
  var p2 = rf.preflight();   // the fast call for the CURRENT pick, resolves immediately
  await p2;
  var afterSecond = JSON.parse(JSON.stringify(rf.pre));
  // now let the slow, older call finish -- late, and with a different answer
  pendingFirstResolve({ ok: true, json: function () { return Promise.resolve({ tag: 'first-response-late' }); } });
  await p1;
  var afterFirst = JSON.parse(JSON.stringify(rf.pre));
  console.log(JSON.stringify({ afterSecond: afterSecond, afterFirst: afterFirst }));
})();
""")
    assert out["afterSecond"] == {"tag": "second-response"}
    # The stale first response must be DROPPED, not overwrite the newer one.
    assert out["afterFirst"] == {"tag": "second-response"}


def test_save_preset_recovers_from_a_conflict_the_page_did_not_know_about(tmp_path):
    """Another tab saved the name: the server's 409 arms the confirm, the next click replaces."""
    out = _run_node(tmp_path, """
const sent = [];
globalThis.fetch = async (url, opts) => {
  const body = JSON.parse(opts.body); sent.push(body.overwrite);
  if (!body.overwrite) return { ok: false, status: 409, json: async () => ({ ok: false, error: 'exists' }) };
  return { ok: true, status: 200, json: async () => ({ ok: true, preset: { name: body.name, spec: {} } }) };
};
(async () => {
  const rf = mod.randomizerFields(form);
  rf.rdraft.spec = {};
  rf.presetName = 'Hard';
  await rf.savePreset();
  const first = rf.presetNote;
  await rf.savePreset();
  console.log(JSON.stringify({ sent, first, second: rf.presetNote }));
})();
""")
    assert out["sent"] == [False, True]
    assert "already exists" in out["first"]
    assert out["second"] == 'Saved "Hard"'
