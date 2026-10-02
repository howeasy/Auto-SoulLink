"""PHYSICAL lane for card P4.5d: the Soul Link phone on the patched Gen 2 ROMs (the <title>_overlay cartridge).

    SLINK_LIVE=1 pytest tests/live/test_gen2_phone_gate.py -q -p no:randomly -k crystal   (or gold, silver)

Boots the qualified <title>_battle fixture warm on the overlay (tools/run_gb_gate.py `<title>_overlay`) and runs
lua/tests/gen2_phone_gate.lua: a request posted in battle, standing in town, with START open, before a native save
and behind a pending native story call must ring only on the next counted step, with the SLink call screen
(PHONE_00 "----------" and the id's first text row), clear ARMED/the id afterwards, never overwrite the native id,
and never reach SRAM. v2 (PHONE-NAMES) adds named_map_change (max-length names survive a map change between arming
and ringing: ClearUnusedMapBuffer is hooked, the binder re-stages, the header names the trainer) and named_fallback
(a trainer without mons: named header, fixed body). This file re-checks the printed facts and, on PASS, writes

    tests/fixtures/gen2/receipts/<title>_overlay.phone_gate.json

Skipped without EmuHawk, the pinned build, the fixture or its qualification receipt.
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

from tests.live import test_gen2_new_gates as live  # noqa: E402
from tests.live.test_gen2_new_gates import emuhawk  # noqa: E402,F401 - pytest fixture
from tests.live.test_gen2_panel_gate import panel_facts  # noqa: E402
from tools import gen2_fixtures, gen2_source_data  # noqa: E402

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                       reason="live Gen 2 gates only run with SLINK_LIVE=1 (spawns EmuHawk)"),
]

GATE = "lua/tests/gen2_phone_gate.lua"
TITLES = ("crystal", "gold", "silver")
PHONE_ASM = REPO / "patch/gen2/src/phone.asm"
SITES = ("RingTwice_StartCall", "ClearUnusedMapBuffer")
RAM = ("wSpecialPhoneCallID", "wCurCaller", "wPokegearFlags")
CASES = ("battle", "town", "start_menu", "save", "native", "named_map_change", "named_fallback")
# docs/gen2/reviews/P45_PHONE_SAVE_CENSUS_2026-09-23.md "Exact sinks": CartRAM offsets of the saved phone byte.
SRAM = {"crystal": {"primary": 0x27BF, "backup": 0x19BF},
        "gold": {"primary": 0x27E3, "backup": 0x1075}, "silver": {"primary": 0x27E3, "backup": 0x1075}}
TEXT_LABELS = {1: "SlinkPhoneFallenText", 2: "SlinkPhoneDeadZoneText", 3: "SlinkPhoneFirstLinkText"}


def text_needles(source: str) -> dict[str, str]:
    """Call id -> the longest plain run of its first `text` row (no <PLAYER>, no ellipsis): what the tilemap shows."""
    out = {}
    for call_id, label in TEXT_LABELS.items():
        first = re.search(rf"^{label}::\s*\n\s*text \"([^\"]+)\"", source, re.M).group(1)
        out[str(call_id)] = max((p.strip() for p in re.split(r"<[A-Z]+>|…", first)), key=len)
    return out


def phone_facts(title: str, *, repo: Path = REPO) -> dict:
    facts = panel_facts(title, repo=repo, sites=SITES, ram=RAM)
    ctx = gen2_source_data.load_context(title, root=repo)
    consts = re.findall(r"^\s*const (SPECIALCALL_\w+)", ctx.read_source("constants/phone_constants.asm"), re.M)
    facts["robbed"] = consts.index("SPECIALCALL_ROBBED")
    facts["texts"] = text_needles(PHONE_ASM.read_text(encoding="utf-8"))
    sram, ram = SRAM[title], facts["ram"]
    # The census's primary offset re-derived from the pinned .sym: sPlayerData + (id - wPlayerData).
    sym = (repo / "data/gen2" / f"{title}_slink.sym").read_text(encoding="utf-8")
    addr = {n: (int(b, 16), int(a, 16)) for b, a, n in re.findall(r"^([0-9a-f]{2}):([0-9a-f]{4}) (\S+)$", sym, re.M)}
    (sb, sa), (_, wp) = addr["sPlayerData"], addr["wPlayerData"]
    assert sb * 0x2000 + sa - 0xA000 + ram["wSpecialPhoneCallID"]["addr"] - wp == sram["primary"], "census offset moved"
    facts["sram"] = sram
    # Save completion: the pinned engine site (data/games/gen2_<title>/engine_signals.json save_completed,
    # _SaveGameData.ok+3's RET), checked against the overlay .sym (the overlay does not move it).
    save = json.loads((repo / f"data/games/gen2_{title}/engine_signals.json").read_text(encoding="utf-8"))
    save = save["titles"][title]["sites"]["save_completed"]
    ok_bank, ok_addr = addr[save["symbol"]]
    assert (ok_bank, ok_addr + save["symbol_offset"]) == (save["bank"], save["addr"]), "save_completed moved"
    facts["sites"]["save_completed"] = {"symbol": save["symbol"], "bank": save["bank"], "addr": save["addr"],
                                        "flat": save["rom_offset"], "hex": save["expected_hex"]}
    return facts


def verify(text: str, facts: dict, title: str, staged: bytes) -> dict:
    """Independent re-check of the gate output; returns the receipt the gate printed."""
    cases = {c["case"]: c for c in (json.loads(line) for line in live.tagged_lines(text).get("CASE", []))}
    assert set(cases) == set(CASES), sorted(cases)
    for c in cases.values():
        assert c["result"] == "PASS" and c["problem"] is None, c
        assert c["acked"] >= c["posted"] and c["armed_id"] == c["id"], c
        assert c["early_ring"] is None and c["id_visible"] is None, c
        ring = c["slink_ring"]
        assert ring["caller"] == 0 and c["step_at"] <= ring["frame"], c
        assert c["screen_caller"] and c["screen_text"] and c["after_armed"] == 0 and c["after_id"] == 0, c
    assert cases["town"]["via"] == "binder" and cases["town"]["pending_id"] == 9, cases["town"]
    assert cases["battle"]["extra"]["rings_in_battle"] == 0, cases["battle"]
    assert cases["start_menu"]["extra"]["id_in_menu"] == 0, cases["start_menu"]
    save = cases["save"]["extra"]
    assert save["armed_at_save"] and save["sram_primary"] == 0 and save["sram_backup"] == 0, save
    assert save["save_site_frame"] is not None and save["sram_changed_bytes"] > 0, save   # the save really ran
    native = cases["native"]["extra"]["native_ring"]
    assert native["caller"] != 0 and native["frame"] < cases["native"]["slink_ring"]["frame"], cases["native"]
    moved = cases["named_map_change"]["extra"]
    assert moved["staged_before_crossing"] and moved["wipes"] > 0 and moved["restaged"], moved
    assert cases["named_fallback"]["extra"]["species"] == [0, 0], cases["named_fallback"]
    receipt = live.tag_json(text, "RECEIPT")
    assert receipt["schema"] == "gen2-phone-gate-v2", receipt
    assert receipt["title"] == title and receipt["fixture"] == f"{title}_battle", receipt
    assert receipt["overlay_sha1"] == facts["overlay_sha1"] and receipt["evidence_level"] == "PHYSICAL", receipt
    assert receipt["fixture_sha256"] == hashlib.sha256(staged).hexdigest(), "receipt names other fixture bytes"
    (seed,) = receipt["harness_write_scopes"]
    assert seed["value"] == facts["robbed"], seed
    return receipt


@pytest.mark.parametrize("title", TITLES)
def test_phone_on_the_patched_rom(emuhawk, title):  # noqa: F811
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
    facts = phone_facts(title)
    env = live.inspect_env(spec, staged, kind="overlay")
    env["SLINK_GEN2_PHONE_FACTS"] = json.dumps(facts)
    env["SLINK_GEN2_QUALIFICATION_ATTEMPT"] = qualification["attempt_id"]
    passed, path, text = run_gate(GATE, rom_key=f"{title}_overlay", target=spec.target, timeout=2400,
                                  saveram_dir=str(REPO / ".cache/gen2-fixtures/p45d-phone" / spec.name),
                                  fixture_path=str(fixture), speed_percent=300, env_overrides=env)
    assert passed, f"gate FAILED; result {path}: {text[-4000:]}"
    assert fixture.read_bytes() == staged, "fixture changed while the gate ran"
    receipt = verify(text, facts, title, staged)
    assert receipt["qualification_attempt_id"] == qualification["attempt_id"]
    (REPO / live.RECEIPTS / f"{title}_overlay.phone_gate.json").write_text(
        json.dumps(live.stamped(receipt), indent=1, sort_keys=True) + "\n", encoding="utf-8")
