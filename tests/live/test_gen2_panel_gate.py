"""PHYSICAL lane for card P4.1g: the SLink panel on the patched Gen 2 ROMs (the <title>_overlay cartridge).

    SLINK_LIVE=1 pytest tests/live/test_gen2_panel_gate.py -q -p no:randomly -k crystal   (or gold, silver)

Boots the qualified <title>_battle fixture warm on the overlay (clean build + patch/dist UPS, staged and
sha1-checked by tools/run_gb_gate.py `<title>_overlay`) and runs lua/tests/gen2_panel_gate.lua: the O-28
START row, the client panel (CLOSED -> AWAIT -> STAGED, paging, A/B/START close), the no-client fallback,
CGB fade stress with palette/attr restoration and the minimum-SP witness (OMP P4.1c F2). This file re-checks
the printed facts independently and, on PASS, writes

    tests/fixtures/gen2/receipts/<title>_overlay.panel_gate.json

Sites and RAM come from data/gen2/<title>_slink.sym (sha256-bound by data/gen2/overlay_provenance.json);
the expected site bytes are read from the UPS-applied image whose sha1 the provenance names. Skipped
without EmuHawk, the pinned build, the fixture or its qualification receipt.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "patch/tools"))

from make_ups import ups_apply  # noqa: E402

from tests.live import test_gen2_new_gates as live  # noqa: E402
from tests.live.test_gen2_new_gates import emuhawk  # noqa: E402,F401 - pytest fixture
from tools import gen2_fixtures, gen2_source_data  # noqa: E402

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                       reason="live Gen 2 gates only run with SLINK_LIVE=1 (spawns EmuHawk)"),
]

GATE = "lua/tests/gen2_panel_gate.lua"
TITLES = ("crystal", "gold", "silver")
PROVENANCE = "data/gen2/overlay_provenance.json"
SITES = ("SlinkPanel", "SlinkPanel.close", "SlinkStartMenuEntry", "FadeOutToWhite", "FadeInFromWhite",
         "EnableSpriteUpdates", "DisableSpriteUpdates")
RAM = ("wStackBottom", "wStackTop", "wBGPals1", "wBGPals2", "wOBPals1", "wOBPals2")
CLOSE_BOUND = 240   # lua P.CLOSE_BOUND


def panel_facts(title: str, *, repo: Path = REPO, sites=SITES, ram=RAM) -> dict:
    """Overlay sites/RAM from the pinned overlay .sym; site bytes from the provenance-bound image."""
    ctx = gen2_source_data.load_context(title, root=repo)
    provenance = json.loads((repo / PROVENANCE).read_text(encoding="utf-8"))
    out = provenance["outputs"][ctx.artifact]
    sym_name = f"{title}_slink.sym"
    sym = (repo / "data/gen2" / sym_name).read_bytes()
    assert hashlib.sha256(sym).hexdigest() == provenance["symbols"][sym_name], "overlay .sym differs from provenance"
    image = ups_apply(ctx.rom, (repo / out["ups"]["file"]).read_bytes())
    assert hashlib.sha1(image).hexdigest() == out["sha1"] and out["base_sha1"] == hashlib.sha1(ctx.rom).hexdigest()
    symbols = {}
    for bank, addr, name in re.findall(r"^([0-9a-f]{2}):([0-9a-f]{4}) (\S+)$", sym.decode("utf-8"), re.M):
        symbols[name] = (int(bank, 16), int(addr, 16))
    bound = {}
    for name in sites:
        bank, addr = symbols[name]
        flat = addr if bank == 0 else bank * 0x4000 + addr - 0x4000
        bound[name] = {"symbol": name, "bank": bank, "addr": addr, "flat": flat, "hex": image[flat:flat + 3].hex()}
    wram = {name: {"bank": symbols[name][0], "addr": symbols[name][1]} for name in ram}
    return {"overlay_sha1": out["sha1"], "sites": bound, "ram": wram}


def verify(text: str, facts: dict, title: str, staged: bytes) -> dict:
    """Independent re-check of the gate output; returns the receipt the gate printed."""
    menu = live.tag_json(text, "MENU")
    items = menu["items"]
    assert items and items[-1] == "SLINK" and items.count("SLINK") == 1 and "EXIT" not in items, menu
    assert menu["bottom"] <= 17 and menu["bottom"] == menu["top"] + 2 * len(items) + 1, menu
    panel = live.tag_json(text, "PANEL")
    trace = [e["state"] for e in panel["trace"]]
    assert panel["pre_state"] == 0 and trace[:4] == [1, 2, 1, 2], trace   # CLOSED -> AWAIT -> STAGED, page turn
    fallback = live.tag_json(text, "FALLBACK")
    assert [f["button"] for f in fallback] == ["A", "B", "Start"], fallback
    assert all(f["stayed_closed"] and f["close_frames"] <= CLOSE_BOUND and 0 < f["timeout"] <= 100 for f in fallback)
    assert live.tag_json(text, "CONTROL")["native_option"] == "restored"
    stress = live.tag_json(text, "STRESS")
    assert stress["all_restored"] is True and stress["in_fade_out"] > 0 and stress["in_fade_in"] > 0, stress
    assert all(c["opened"] and c["closed"] and c["restored"] is True for c in stress["cycles"]), stress
    stack = live.tag_json(text, "STACK")
    bottom = facts["ram"]["wStackBottom"]["addr"]
    assert stack["bottom"] == bottom and stack["top"] == facts["ram"]["wStackTop"]["addr"], stack
    assert stack["early_hits"] >= 8 and stack["margin_bytes"] == stack["low_water_addr"] - bottom > 0, stack
    receipt = live.tag_json(text, "RECEIPT")
    assert receipt["title"] == title and receipt["fixture"] == f"{title}_battle", receipt
    assert receipt["overlay_sha1"] == facts["overlay_sha1"] and receipt["evidence_level"] == "PHYSICAL", receipt
    # B2: the executed identity, OBSERVED in the emulator (real.romhash) and cross-checked here against the
    # independently hashed staged bytes. The receipt then carries its own artifact identity (stamped below).
    identity = live.identity(title, "overlay")
    assert receipt["observed_rom_sha1"] == identity["rom_sha1"], "the gate ran other bytes than the staged overlay"
    assert receipt["fixture_sha256"] == hashlib.sha256(staged).hexdigest(), "receipt names other fixture bytes"
    assert receipt["minimum_sp"] == stack and receipt["harness_write_scopes"] == []
    return receipt


@pytest.mark.parametrize("title", TITLES)
def test_panel_on_the_patched_rom(emuhawk, title):  # noqa: F811
    spec = gen2_fixtures.BY_NAME[f"{title}_battle"]
    reason = (live.rom_missing_reason(spec.title) or live.fixture_missing_reason(spec.name)
              or live.receipt_missing_reason(spec.name, kind="overlay"))
    if reason:
        pytest.skip(reason)
    from run_gb_gate import run_gate

    fixture = REPO / "tests/fixtures/gen2" / f"{spec.name}.SaveRAM"
    staged = fixture.read_bytes()
    live.qualified_identity(spec.name, staged, kind="overlay")
    qualification = json.loads(live.receipt_file(f"{spec.name}.qualification.json", "overlay").read_text(encoding="utf-8"))
    facts = panel_facts(title)
    env = live.inspect_env(spec, staged, kind="overlay")
    env["SLINK_GEN2_PANEL_FACTS"] = json.dumps(facts)
    env["SLINK_GEN2_QUALIFICATION_ATTEMPT"] = qualification["attempt_id"]
    passed, path, text = run_gate(GATE, rom_key=f"{title}_overlay", target=spec.target, timeout=1800,
                                  saveram_dir=str(REPO / ".cache/gen2-fixtures/p41g-panel" / spec.name),
                                  fixture_path=str(fixture), speed_percent=300, env_overrides=env)
    assert passed, f"gate FAILED; result {path}: {text[-3000:]}"
    assert fixture.read_bytes() == staged, "fixture changed while the gate ran"
    receipt = verify(text, facts, title, staged)
    assert receipt["qualification_attempt_id"] == qualification["attempt_id"]
    # B1: overlay evidence lands in the overlay namespace, never beside the clean receipts.
    identity = live.identity(title, "overlay")
    receipt.update(artifact_kind=identity["kind"], rom_sha1=identity["rom_sha1"],
                   base_sha1=identity["base_sha1"], binding_sha256=identity["binding_sha256"])
    live.receipt_file(f"{title}.panel_gate.json", "overlay").write_text(
        json.dumps(live.stamped(receipt), indent=1, sort_keys=True) + "\n", encoding="utf-8")
