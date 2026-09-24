"""PHYSICAL lane for card P4.2c: native sound on the patched Gen 2 ROMs (the <title>_overlay cartridge).

    SLINK_LIVE=1 pytest tests/live/test_gen2_sfx_gate.py -q -p no:randomly -k crystal   (or gold, silver)

Boots the qualified <title>_battle fixture warm on the overlay (tools/run_gb_gate.py `<title>_overlay`) and runs
lua/tests/gen2_sfx_gate.lua: the shipped lua/gen2/panel.lua binding posts each request; the exact native id must
reach ch5-8 (wChannel5..8 MusicID + SOUND_CHANNEL_ON) within the deadline in the idle, movement, transition (held
through the music fade), START menu, text, battle-animation and battle-menu contexts, and a request pending at
Reset is dropped with nothing played after the reboot. This file re-checks the printed facts against ids it
derives itself (patch/gen2/src/sfx.asm `.sounds` order x the decomp's constants/sfx_constants.asm) and, on PASS,
writes

    tests/fixtures/gen2/receipts/<title>_overlay.sfx_gate.json

A red context is card P4.2d's input (a GetJoypad second site); this lane never builds one. Skipped without
EmuHawk, the pinned build, the fixture or its qualification receipt.
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

GATE = "lua/tests/gen2_sfx_gate.lua"
TITLES = ("crystal", "gold", "silver")
SFX_ASM = REPO / "patch/gen2/src/sfx.asm"
SITES = ("BattleAnimDelayFrame", "PlaySFX", "Reset", "SlinkSfxService")
RAM = ("wChannel5", "wChannel6", "wChannel7", "wChannel8", "wCurSFX", "wMusicFade", "wWalkingDirection")
CONTEXTS = ("idle_1", "idle_2", "idle_3", "idle_4", "movement", "transition", "start_menu", "text",
            "battle_anim", "battle_menu")
DEADLINE = 300   # lua P.DEADLINE


def native_ids(title: str, *, repo: Path = REPO) -> dict[int, int]:
    """Semantic code -> native SFX id: sfx.asm's `.sounds` order over the pinned decomp's const list."""
    names = [n.strip() for n in re.search(r"^\.sounds\s*\n\s*db\s+(.+)$", SFX_ASM.read_text(), re.M).group(1).split(",")]
    ctx = gen2_source_data.load_context(title, root=repo)
    consts = re.findall(r"^\s*const (SFX_\w+)", ctx.read_source("constants/sfx_constants.asm"), re.M)
    return {code: consts.index(name) for code, name in enumerate(names, 1)}


def sfx_facts(title: str, *, repo: Path = REPO) -> dict:
    facts = panel_facts(title, repo=repo, sites=SITES, ram=RAM)
    facts["sounds"] = {str(code): nid for code, nid in native_ids(title, repo=repo).items()}
    return facts


def verify(text: str, facts: dict, title: str, staged: bytes) -> dict:
    """Independent re-check of the gate output; returns the receipt the gate printed."""
    ids = {int(k): v for k, v in facts["sounds"].items()}
    cases = {c["context"]: c for c in (json.loads(line) for line in live.tagged_lines(text).get("CASE", []))}
    assert set(cases) == set(CONTEXTS), sorted(cases)
    for name, c in cases.items():
        assert c["result"] == "PASS" and c["id"] == ids[c["code"]], c
        assert c["consumed"] is not None and c["played"] >= c["consumed"] >= c["posted"], c
        assert 5 <= c["channel"] <= 8, c
        if name == "transition":
            assert c["fade_at_post"] and not c["dropped_in_fade"] and c["fade_frames"] > 0, c
            assert c["fade_end"] <= c["played"] <= c["fade_end"] + DEADLINE, c
        else:
            assert c["played"] - c["posted"] <= DEADLINE, c
    assert [cases[f"idle_{k}"]["id"] for k in (1, 2, 3, 4)] == [ids[k] for k in (1, 2, 3, 4)]
    assert cases["battle_anim"]["anim_frames"] is not None, cases["battle_anim"]
    receipt_contexts = live.tag_json(text, "RECEIPT")["contexts"]
    gap = receipt_contexts["battle_anim"]["battle_service_gap"]
    assert isinstance(gap, int) and 0 < gap <= DEADLINE, receipt_contexts["battle_anim"]   # OMP P41C F4 worst case
    reset = live.tag_json(text, "RESET")
    assert reset["result"] == "PASS" and reset["pending_at_entry"] and reset["latched"] and reset["dropped"], reset
    assert reset["played_id"] is None and reset["on_channel"] is None and reset["id"] == ids[reset["code"]], reset
    assert reset["id"] not in reset["playsfx_ids_after"], reset
    receipt = live.tag_json(text, "RECEIPT")
    assert receipt["title"] == title and receipt["fixture"] == f"{title}_battle", receipt
    assert receipt["overlay_sha1"] == facts["overlay_sha1"] and receipt["evidence_level"] == "PHYSICAL", receipt
    assert receipt["fixture_sha256"] == hashlib.sha256(staged).hexdigest(), "receipt names other fixture bytes"
    assert receipt["harness_write_scopes"] == [] and receipt["reset"] == reset
    assert {int(k): v for k, v in receipt["sounds"].items()} == ids
    return receipt


@pytest.mark.parametrize("title", TITLES)
def test_native_sound_on_the_patched_rom(emuhawk, title):  # noqa: F811
    spec = gen2_fixtures.BY_NAME[f"{title}_battle"]
    reason = (live.rom_missing_reason(spec.title) or live.fixture_missing_reason(spec.name)
              or live.receipt_missing_reason(spec.name))
    if reason:
        pytest.skip(reason)
    from run_gb_gate import run_gate

    fixture = REPO / "tests/fixtures/gen2" / f"{spec.name}.SaveRAM"
    staged = fixture.read_bytes()
    live.qualified_identity(spec.name, staged)
    qualification = json.loads((REPO / live.RECEIPTS / f"{spec.name}.qualification.json").read_text(encoding="utf-8"))
    facts = sfx_facts(title)
    env = live.inspect_env(spec, staged)
    env["SLINK_GEN2_SFX_FACTS"] = json.dumps(facts)
    env["SLINK_GEN2_QUALIFICATION_ATTEMPT"] = qualification["attempt_id"]
    passed, path, text = run_gate(GATE, rom_key=f"{title}_overlay", target=spec.target, timeout=1800,
                                  saveram_dir=str(REPO / ".cache/gen2-fixtures/p42c-sfx" / spec.name),
                                  fixture_path=str(fixture), speed_percent=300, env_overrides=env)
    assert passed, f"gate FAILED; result {path}: {text[-4000:]}"
    assert fixture.read_bytes() == staged, "fixture changed while the gate ran"
    receipt = verify(text, facts, title, staged)
    assert receipt["qualification_attempt_id"] == qualification["attempt_id"]
    (REPO / live.RECEIPTS / f"{title}_overlay.sfx_gate.json").write_text(
        json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def test_native_ids_are_the_asserted_ones():
    """Static: the derived table equals sfx.asm's own ASSERT (SFX_ITEM $01, WRONG $19, BUMP $24, READ_TEXT_2 $08)."""
    for title in ("crystal", "gold"):
        try:
            ids = native_ids(title)
        except Exception as exc:  # noqa: BLE001 - the pinned decomp is a local build input
            pytest.skip(f"pinned decomp unavailable: {exc}")
        assert ids == {1: 0x01, 2: 0x19, 3: 0x24, 4: 0x08}
