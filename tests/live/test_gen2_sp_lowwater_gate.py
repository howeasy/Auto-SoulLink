"""PHYSICAL lane for SP-LOWWATER (docs/gen2/POST_RC_CARDS.md): the worst-case stack during battle-text service.

    SLINK_LIVE=1 pytest tests/live/test_gen2_sp_lowwater_gate.py -q -p no:randomly -k crystal   (or gold, silver)

Three fresh boots of the qualified <title>_battle fixture on the overlay (tools/run_gb_gate.py `<title>_overlay`), one
per mode (A_held, B_held, released), each running lua/tests/gen2_sp_lowwater_gate.lua: the sibling mode of the sfx gate
(its header has the design). The three per-run RECEIPT lines are re-judged here by the release verifier's own
_sp_lowwater_gate_row_errors and, when all three PASS, combined into

    tests/fixtures/gen2/receipts/<title>_overlay.sp_lowwater_gate.json

Every run's trace is kept as patch/build/gen2_sp_lowwater_gate_<title>_<mode>_result.txt. Skipped without EmuHawk,
the pinned build, the fixture or its qualification receipt.
"""
from __future__ import annotations

import hashlib
import json
import os
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
from tests.live.test_gen2_sfx_gate import (  # noqa: E402
    RAM as SFX_RAM,
    SITES as SFX_SITES,
    native_ids,
)
from tools import gen2_fixtures, verify_gen2_release as gate  # noqa: E402

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                       reason="live Gen 2 gates only run with SLINK_LIVE=1 (spawns EmuHawk)"),
]

GATE = "lua/tests/gen2_sp_lowwater_gate.lua"
RESULT = REPO / "patch/build/gen2_sp_lowwater_gate_result.txt"
TITLES = ("crystal", "gold", "silver")
MODES = tuple(gate.SP_LOWWATER_MODES)
SITES = SFX_SITES + ("SlinkDelayFrameBridge", "SlinkDelayFrameBridgeEnd", "SlinkService", "SlinkPhoneService",
                     "_PlaySFX", "VBlank", "PrintLetterDelay.checkjoypad", "PrintLetterDelay.delay",
                     "PrintLetterDelay.end", "RingTwice_StartCall")
RAM = SFX_RAM + ("wStackBottom", "wStackTop", "wTextDelayFrames", "wVBlankOccurred", "wBattleMode")
# the binding every run shares; `runs` and the verdicts are the per-run parts
BINDING = ("title", "evidence_level", "overlay_sha1", "base_sha1", "fixture", "fixture_sha256",
           "qualification_attempt_id", "core_mode", "input_mode", "harness_write_scopes", "client_write_scope",
           "bounds", "static_bound", "nested_vblank_policy")


def lowwater_facts(title: str, *, repo: Path = REPO) -> dict:
    facts = panel_facts(title, repo=repo, sites=SITES, ram=RAM)
    facts["sounds"] = {str(code): nid for code, nid in native_ids(title, repo=repo).items()}
    return facts


def combine(parts: dict[str, dict], title: str, staged: bytes) -> dict:
    """The per-title receipt from the three per-run RECEIPT lines, which must agree on the binding."""
    first = parts[MODES[0]]
    for mode, part in parts.items():
        assert part["schema"] == "gen2-sp-lowwater-v1" and part["part"] == "run" and part["mode"] == mode, part
        assert {k: part.get(k) for k in BINDING} == {k: first.get(k) for k in BINDING}, (mode, "binding differs")
    receipt = {k: first[k] for k in BINDING}
    runs = {mode: part["run"] for mode, part in parts.items()}
    margins = [r.get("margin_bytes") for r in runs.values()]
    receipt.update(schema="gen2-sp-lowwater-v1", result="PASS", runs=runs,
                   margin_bytes=min(margins) if all(type(m) is int for m in margins) else None)
    assert receipt["title"] == title and receipt["fixture"] == f"{title}_battle", receipt
    assert receipt["fixture_sha256"] == hashlib.sha256(staged).hexdigest(), "receipt names other fixture bytes"
    assert receipt["harness_write_scopes"] == [], receipt
    return receipt


def summary(parts: dict) -> str:
    rows = []
    for mode, part in parts.items():
        run = (part or {}).get("run") or {}
        nested = run.get("nested_vblank") or {}
        rows.append(f"{mode}: {run.get('verdict')} margin {run.get('margin_bytes')} ({run.get('margin_kind')}) "
                    f"composed {(run.get('composition') or {}).get('composed_margin')} "
                    f"nested {nested.get('count')} problems {run.get('problems')}")
    return "; ".join(rows)


@pytest.mark.parametrize("title", TITLES)
def test_sp_lowwater_on_the_patched_rom(emuhawk, title):  # noqa: F811
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
    facts = lowwater_facts(title)
    parts, failed = {}, []
    for mode in MODES:   # one fresh boot per mode: phone ARMED is single-slot
        env = live.inspect_env(spec, staged)
        env["SLINK_GEN2_SFX_FACTS"] = json.dumps(facts)
        env["SLINK_GEN2_QUALIFICATION_ATTEMPT"] = qualification["attempt_id"]
        env["SLINK_GEN2_SP_LOWWATER"] = mode
        passed, path, text = run_gate(GATE, rom_key=f"{title}_overlay", target=spec.target, timeout=1800,
                                      saveram_dir=str(REPO / ".cache/gen2-fixtures/splw" / f"{spec.name}_{mode}"),
                                      fixture_path=str(fixture), speed_percent=300, env_overrides=env)
        RESULT.with_name(f"gen2_sp_lowwater_gate_{title}_{mode}_result.txt").write_text(text, encoding="utf-8")
        parts[mode] = live.tag_json(text, "RECEIPT") if live.tagged_lines(text).get("RECEIPT") else None
        if not passed:
            failed.append(f"{mode} ({path}): {text[-1500:]}")
    assert fixture.read_bytes() == staged, "fixture changed while the gate ran"
    assert not failed, summary(parts) + "\n" + "\n".join(failed)
    receipt = combine(parts, title, staged)
    assert receipt["overlay_sha1"] == facts["overlay_sha1"] and receipt["evidence_level"] == "PHYSICAL", receipt
    assert receipt["qualification_attempt_id"] == qualification["attempt_id"]
    errors = gate._sp_lowwater_gate_row_errors(REPO, title, receipt)
    assert not errors, errors
    (REPO / live.RECEIPTS / f"{title}_overlay.sp_lowwater_gate.json").write_text(
        json.dumps(live.stamped(receipt), indent=1, sort_keys=True) + "\n", encoding="utf-8")
