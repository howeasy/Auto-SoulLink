"""The UI says what the policy is: the SLink companion patch is REQUIRED (except Yellow,
Archipelago and the Emerald Expansion), and nothing the UI advertises is a feature this
release greys out in manager.py."""
import json
import os
import re
import shutil
import subprocess

import pytest

import server.manager as manager

pytest_plugins = ["tests.unit.manager_harness"]

_JS = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "server", "static", "randomizer.js"))


def _text(page):
    """Visible-ish text: drop <script>/<style> and tags, keep attribute-free prose."""
    page = re.sub(r"<(script|style)\b.*?</\1>", "", page, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))


@pytest.mark.asyncio
async def test_patcher_page_states_the_requirement_and_advertises_no_deferred_feature(manager_client):
    for url in ("/patcher", "/patcher?game=rr"):
        resp = await manager_client.get(url)
        assert resp.status == 200
        text = _text(await resp.text())
        assert "optional" not in text.lower(), "the patch is required"
        assert "unpatched players are unaffected" not in text
        assert "required" in text.lower() and "Yellow" in text and "Archipelago" in text
        assert "refused" in text
        # manager.py greys these two for this release (OPTION_SUPPORT)
        low = text.lower()
        for greyed in ("peer ghost", "talk to your partner", "native message box", "native messages"):
            assert greyed not in low, greyed
        assert "need no patch on any game boy" not in low
        assert "Requires ROM patch" not in text
        for group in ("Battle", "Native UI"):
            assert group in text


@pytest.mark.asyncio
async def test_cartridges_form_calls_the_companion_required(manager_client):
    manager._save_registry([{"run_id": "r1", "name": "Duo", "tcp_port": 1, "http_port": 2,
                             "status": "stopped", "pid": None, "game": "gen1"}])
    pages = [await (await manager_client.get("/new")).text(),
             await (await manager_client.get("/runs/r1/cartridges")).text()]
    for page in pages:
        text = _text(page)
        assert "Optional: without it" not in page and "silently" not in page
        assert "Required" in text
        assert "Yellow" in text and "Archipelago" in text


def test_tools_page_does_not_advertise_greyed_features():
    src = open(os.path.join(os.path.dirname(_JS), "..", "templates", "tools.html"), encoding="utf-8").read()
    assert "native messages" not in src.lower() and "peer ghost" not in src.lower()


@pytest.mark.asyncio
async def test_home_getting_started_has_the_exemptions_and_links_the_patcher(manager_client):
    body = await (await manager_client.get("/")).text()
    step = body[body.index("Prepare your cartridge"):]
    step = step[:step.index("</li>")]
    assert 'href="/patcher"' in step
    for name in ("Yellow", "Archipelago", "Emerald Expansion"):
        assert name in step


def test_board_step_has_the_exemptions():
    src = open(os.path.join(os.path.dirname(_JS), "..", "templates", "_board.html"), encoding="utf-8").read()
    step = src[src.index("prepares their cartridge"):]
    step = step[:step.index("</li>")]
    assert 'href="/patcher"' in step and "Yellow" in step and "Archipelago" in step and "Emerald Expansion" in step


def test_onboarding_tells_players_to_prepare_the_cartridge_first():
    tdir = os.path.join(os.path.dirname(_JS), "..", "templates")
    for name in ("_board.html", "manager.html"):
        src = open(os.path.join(tdir, name), encoding="utf-8").read()
        assert "/patcher" in src, name


_PRELUDE = ("const src = require('fs').readFileSync(" + json.dumps(_JS) + ", 'utf8');\n"
            "const mod = new Function(src + '\\nreturn { randomizerFields };')();\n")


def _node(body, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not found on PATH")
    script = tmp_path / "harness.js"
    script.write_text(_PRELUDE + body, encoding="utf-8")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_cartridge_form_requires_the_companion_where_one_exists(tmp_path):
    out = _node("""
const form = { options: [], jar: '', cartridges: { companion: false }, current: null, presets: [], family: null,
  companion_titles: ['Red', 'Blue'],
  roms: [{ path: 'r.gb', clean: true, family: 'gen1_rby', variant: 'Red', title: 'Red' },
         { path: 'b.gb', clean: true, family: 'gen1_rby', variant: 'Blue', title: 'Blue' },
         { path: 'y.gb', clean: true, family: 'gen1_rby', variant: 'Yellow', title: 'Yellow' }] };
const rf = mod.randomizerFields(form);
const start = rf.rdraft.companion;
rf.rdraft.rom_a = 'r.gb'; rf.rdraft.rom_b = 'b.gb';
const on = rf.cartsWhy();
rf.rdraft.companion = false;
const off = rf.cartsWhy(), offReady = rf.cartsReady(), body = rf.cartridgesBody();
const offBody = body.companion;
rf.rdraft.rom_b = 'y.gb';
const exempt = rf.cartsWhy(), exemptOk = rf.companionOk();
rf.syncCompanion();
const exemptDraft = rf.rdraft.companion, exemptBody = rf.cartridgesBody().companion, exemptReq = rf.companionRequired();
rf.rdraft.rom_b = 'b.gb'; rf.syncCompanion();
const capDraft = rf.rdraft.companion, capBody = rf.cartridgesBody().companion, capReq = rf.companionRequired();
console.log(JSON.stringify({ start, on, off, offReady, offBody, exempt, exemptOk, exemptDraft, exemptBody, exemptReq,
  capDraft, capBody, capReq }));
""", tmp_path)
    assert out["start"] is True, "a previous run's companion=false must not carry over"
    assert out["on"] == ""
    assert out["off"] and "companion" in out["off"].lower() and not out["offReady"]
    assert out["offBody"] is False, "posts what the draft says; cartsWhy is what stops it"
    assert out["exempt"] == "" and not out["exemptOk"]["ok"]
    # exempt pick: not required, draft unchecked, posted false. capable pick: required, checked, posted true
    assert (out["exemptReq"], out["exemptDraft"], out["exemptBody"]) == (False, False, False)
    assert (out["capReq"], out["capDraft"], out["capBody"]) == (True, True, True)


@pytest.mark.asyncio
async def test_checkbox_markup_separates_unavailable_from_required(manager_client):
    page = await (await manager_client.get("/new")).text()
    box = page[page.index('x-model="rdraft.companion"') - 40:]
    box = box[:box.index("</label>")]
    assert ':disabled="!companionOk().ok"' in box, "disabled only when unavailable"
    assert "companionRequired() ? 'true'" in box and "preventDefault" in box, "required = aria-disabled + click cancelled"
    assert 'aria-describedby="companion-why"' in box and 'id="companion-why"' in box
