"""PHYSICAL lane for card gen2-p4-w6: the live mailbox write-watch tripwire on the patched Gen 2 overlays.

    SLINK_LIVE=1 pytest tests/live/test_gen2_w6_gate.py -q -p no:randomly -k crystal   (or gold, silver)

O-27 D1: the SLink mailbox span (tools/gen2_mailbox_census.MAILBOX_SPANS) is protected by writer exclusion,
proven from source by the census; this is the live tripwire over the scripted corpus, never a proof. Per title
it runs the existing scripted gates on the <title>_overlay cartridge (tools/run_gb_gate.py stages the published
UPS over the clean build and checks the provenance sha1), each wrapped by lua/tests/gen2_w6_gate.lua:

    panel   lua/tests/gen2_panel_gate.lua     menus, the client panel, fallback, fade stress, a wild battle
    sfx     lua/tests/gen2_sfx_gate.lua       every sound context, a battle, a soft reset
    u1      lua/tests/gen2_frame_align.lua    Route 29 play, wild battle + Poke Ball capture + native save,
                                              the overworld poison leg and the in-battle faint

Every inner gate must still PASS its own independent verify() (the corpus really ran), and every CPU write
into the span must come from a SLink code range of the pinned overlay .sym (w6_facts), Init's WRAM0 clear at
boot/reset, or the shipped Lua client. Both known-positive controls (a native writer on wVBlankOccurred, a
non-client Lua store into the span) must be caught in every leg. On PASS writes

    tests/fixtures/gen2/receipts/<title>_overlay.w6_gate.json

Skipped without EmuHawk, the pinned build, a fixture or its qualification receipt.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "patch/tools"))

from tests.live import (  # noqa: E402
    test_gen2_new_gates as live,
    test_gen2_panel_gate as panel,
    test_gen2_sfx_gate as sfx,
)
from tests.live.test_gen2_new_gates import emuhawk  # noqa: E402,F401 - pytest fixture
from tools import gen2_fixtures, gen2_source_data  # noqa: E402
from tools.gen2_mailbox_census import MAILBOX_SPANS  # noqa: E402

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                       reason="live Gen 2 gates only run with SLINK_LIVE=1 (spawns EmuHawk)"),
]

GATE = "lua/tests/gen2_w6_gate.lua"
SCHEMA = "gen2-w6-gate-v1"
TITLES = ("crystal", "gold", "silver")
LEGS = ("panel", "sfx", "u1")
STAGGER = 60          # seconds between this lane's EmuHawk launches (other lanes share the machine)
# main 2026-09-23: the U1 leg runs the FROZEN U1e chain (catch, save, poison, battle faint, whiteout) at a7bf1773,
# not U1f's in-development PC leg, which joins the corpus once it passes and is receipted (one more W6 re-run
# then). The faint driver is taken at c60c45c3: its 0-PP fix (live: the frozen driver loops on TAIL WHIP at 0 PP).
U1_REF = "a7bf1773"
U1_FROZEN = {"lua/tests/gen2_frame_align.lua": U1_REF, "lua/tests/gen2_poison_inputs.lua": U1_REF,
             "lua/tests/duo/gen2_faint_inputs.lua": "c60c45c3", "tests/live/test_gen2_frame_align.py": U1_REF}
IN_PLACE_CODE = ("SlinkStartMenuEntry",)   # patch/gen2/src/panel_start.asm, bank 4
INIT_LOOP = bytes.fromhex("3600230b78b120f8")   # Init.ByteFill: ld [hl],0 / inc hl / dec bc / ld a,b / or c / jr nz


def _symbols(title: str, repo: Path = REPO) -> tuple[dict, list]:
    """The pinned overlay .sym (sha256-bound by the provenance, via panel.panel_facts): name -> (bank, addr)."""
    text = (repo / "data/gen2" / f"{title}_slink.sym").read_text(encoding="utf-8")
    rows = [(int(b, 16), int(a, 16), n) for b, a, n in re.findall(r"^([0-9a-f]{2}):([0-9a-f]{4}) (\S+)$", text, re.M)]
    return {n: (b, a) for b, a, n in rows}, rows


def w6_facts(title: str, *, repo: Path = REPO) -> dict:
    """Span, allowlist, Init clear and the control byte, all from the pinned overlay .sym."""
    base = panel.panel_facts(title, repo=repo, sites=("Init.ByteFill",), ram=("hROMBank", "wVBlankOccurred"))
    assert base["sites"]["Init.ByteFill"]["hex"] == INIT_LOOP[:3].hex(), "Init's WRAM0 clear moved"
    symbols, rows = _symbols(title, repo)
    service_bank = symbols["SlinkService"][0]
    allow = [{"name": "SLink service bank", "bank": service_bank, "lo": 0x4000, "hi": 0x8000}]
    # Outside the service bank: the ROM0 Slink* bridges and the in-place CODE hunks named in IN_PLACE_CODE, each
    # running to the next symbol in its bank. In-place data/script labels (SlinkMenuString,
    # SlinkSpecialPhoneCallList, SlinkTradeReceptionistScript) are never CPU code: a writer PC there is a fault.
    # A new in-place code hunk fails closed until it is named here.
    for bank, addr, name in rows:
        if (not name.startswith("Slink") or "." in name or name.endswith("End") or addr >= 0x8000
                or not (bank == 0 or name in IN_PLACE_CODE)):
            continue
        nxt = min((a for b, a, _ in rows if b == bank and a > addr), default=0x4000 if bank == 0 else 0x8000)
        allow.append({"name": name, "bank": bank, "lo": addr, "hi": nxt})
    init_bank, init_lo = symbols["Init.ByteFill"]
    assert init_bank == 0
    lo, hi = MAILBOX_SPANS[title]
    # SLink-owned native regions (main 2026-09-23): the P4.5b phone service writes the WORD wSpecialPhoneCallID
    # (+0, +1) from the service bank only; any other SLink range writing it is a violation.
    phone_bank, phone = symbols["wSpecialPhoneCallID"]
    assert phone_bank == 1 and 0xD000 <= phone < 0xE000, "wSpecialPhoneCallID left WRAMX bank 1"
    regions = [{"name": "wSpecialPhoneCallID", "lo": phone, "hi": phone + 2, "wram_bank": 1,
                "slink_allow": ["SLink service bank"]}]
    return {"overlay_sha1": base["overlay_sha1"], "span": [lo, hi], "allow": allow, "regions": regions,
            "init": {"name": "Init WRAM0 clear", "entry": symbols["Init"][1], "lo": init_lo, "hi": init_lo + len(INIT_LOOP)},
            "hrombank": symbols["hROMBank"][1], "control": symbols["wVBlankOccurred"][1]}


def symbolize(title: str, key: str, repo: Path = REPO) -> str:
    """'75:4012' -> '75:4012 SlinkService.sample+0x3' (nearest symbol at or below, same bank)."""
    bank, addr = (int(x, 16) for x in key.split(":"))
    _, rows = _symbols(title, repo)
    # An `...End` label shares its address with the next routine (SlinkServiceEnd == SlinkPanel): skip it.
    best = max(((a, n) for b, a, n in rows if b == bank and a <= addr and a < 0x8000 and not n.endswith("End")),
               default=None)
    return f"{key} {best[1]}+0x{addr - best[0]:x}" if best else key


def frozen_u1():
    """Each U1_FROZEN file at its ref under .cache/gen2-w6-frozen/<U1_REF> (the Lua wrapper serves them in place of
    the worktree files), {path: {ref, sha256}}, and the frozen test module (u1_facts, verify, U1_FIXTURE, GATE)."""
    base = REPO / ".cache/gen2-w6-frozen" / U1_REF
    files = {}
    for rel, ref in U1_FROZEN.items():
        data = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=REPO, capture_output=True, check=True).stdout
        (base / rel).parent.mkdir(parents=True, exist_ok=True)
        (base / rel).write_bytes(data)
        files[rel] = {"ref": ref, "sha256": hashlib.sha256(data).hexdigest()}
    spec = importlib.util.spec_from_file_location("w6_frozen_u1", base / "tests/live/test_gen2_frame_align.py")
    module = importlib.util.module_from_spec(spec)
    path = list(sys.path)
    spec.loader.exec_module(module)
    sys.path[:] = path          # its REPO-relative sys.path inserts point into the cache
    module.REPO = REPO
    return base, files, module


def _legs(title: str, u1) -> dict:
    """leg -> (inner gate, its result file, fixture name, env builder, verify, timeout); u1 = the frozen U1 module."""
    def panel_env(spec, qual):
        return {"SLINK_GEN2_PANEL_FACTS": json.dumps(panel.panel_facts(title))}

    def sfx_env(spec, qual):
        return {"SLINK_GEN2_SFX_FACTS": json.dumps(sfx.sfx_facts(title))}

    def u1_env(spec, qual):
        ctx = gen2_source_data.load_context(spec.title, root=REPO)
        return {"SLINK_GEN2_U1_FACTS": json.dumps(u1.u1_facts(ctx, gen2_fixtures.spec_route_facts(spec, REPO), qual))}

    pack = json.loads((REPO / f"data/games/gen2_{title}/engine_signals.json").read_text(encoding="utf-8"))
    return {
        "panel": (panel.GATE, "patch/build/gen2_panel_gate_result.txt", f"{title}_battle", panel_env,
                  lambda text, staged: panel.verify(text, panel.panel_facts(title), title, staged), 1800),
        "sfx": (sfx.GATE, "patch/build/gen2_sfx_gate_result.txt", f"{title}_battle", sfx_env,
                lambda text, staged: sfx.verify(text, sfx.sfx_facts(title), title, staged), 1800),
        "u1": (u1.GATE, "patch/build/gen2_frame_align_result.txt", u1.U1_FIXTURE[title], u1_env,
               lambda text, staged: u1.verify(text, pack, title), 2400),
    }


def verify_leg(record: dict, leg: str, facts: dict) -> None:
    """The W6 record of one leg: completed, writers only allowed, both controls caught."""
    assert record["schema"] == "gen2-w6-leg-v1" and record["leg"] == leg and record["evidence_level"] == "PHYSICAL"
    assert record["overlay_sha1"] == facts["overlay_sha1"] and record["span"] == facts["span"], record
    assert record["inner_completed"] is True and record["corpus_frames"] > 0, record
    assert record["violation_count"] == 0 and record["violations"] == [], record["violations"]
    assert record["allowed_writes"] == sum(record["writers"].values()) > 0, record["writers"]
    assert not record["lua_writes"]["harness"], record["lua_writes"]
    control = record["control"]
    assert control["native_caught"] is True and control["native_flagged"] > 0, control
    assert control["lua_caught"] is True and control["lua_kind"] == "harness", control
    assert set(record["regions"]) == {r["name"] for r in facts["regions"]}, record["regions"]


@pytest.mark.parametrize("title", TITLES)
def test_mailbox_write_watch_on_the_overlay(emuhawk, title):  # noqa: F811
    from run_gb_gate import run_gate

    facts = w6_facts(title)
    frozen_dir, frozen_files, u1 = frozen_u1()
    legs, launched = {}, False
    for leg, (gate, inner_result, fixture_name, extra_env, check, timeout) in _legs(title, u1).items():
        spec = gen2_fixtures.BY_NAME[fixture_name]
        reason = (live.rom_missing_reason(spec.title) or live.fixture_missing_reason(spec.name)
                  or live.receipt_missing_reason(spec.name))
        if reason:
            pytest.skip(reason)
        fixture = REPO / "tests/fixtures/gen2" / f"{spec.name}.SaveRAM"
        staged = fixture.read_bytes()
        live.qualified_identity(spec.name, staged)
        qual = json.loads((REPO / live.RECEIPTS / f"{spec.name}.qualification.json").read_text(encoding="utf-8"))
        env = live.inspect_env(spec, staged)
        env.update(extra_env(spec, qual["attempt_id"]))
        env["SLINK_GEN2_QUALIFICATION_ATTEMPT"] = qual["attempt_id"]
        source = gen2_source_data.load_context(title, root=REPO).source_record()
        env["SLINK_GEN2_W6"] = json.dumps({"leg": leg, "gate": gate, "inner_result": inner_result, "facts": facts,
                                           "overlay_sha1": facts["overlay_sha1"], "base_sha1": source["rom_sha1"],
                                           "clean_view": leg == "u1", "lua_control_offset": 20,
                                           "frozen": {rel: str(frozen_dir / rel) for rel in U1_FROZEN
                                                      if rel.endswith(".lua")} if leg == "u1" else None})
        if launched:
            time.sleep(STAGGER)
        launched = True
        passed, path, text = run_gate(GATE, rom_key=f"{title}_overlay", target=spec.target, timeout=timeout,
                                      saveram_dir=str(REPO / ".cache/gen2-fixtures/w6" / f"{title}-{leg}"),
                                      fixture_path=str(fixture), speed_percent=300, env_overrides=env)
        inner_text = (REPO / inner_result).read_text(encoding="utf-8", errors="replace") \
            if (REPO / inner_result).is_file() else ""
        assert passed, f"{leg}: W6 gate FAILED; {path}: {text[-3000:]}\ninner: {inner_text[-2000:]}"
        assert fixture.read_bytes() == staged, "fixture changed while the gate ran"
        check(inner_text, staged)   # the corpus leg really ran and passed its own independent re-check
        record = live.tag_json(text, "W6")
        verify_leg(record, leg, facts)
        legs[leg] = {**record, "fixture": spec.name, "fixture_sha256": hashlib.sha256(staged).hexdigest(),
                     "qualification_attempt_id": qual["attempt_id"],
                     "driver": {"ref": U1_REF, "files": frozen_files} if leg == "u1" else None,
                     "writers": {symbolize(title, k): v for k, v in sorted(record["writers"].items())},
                     "boot_clear": {symbolize(title, k): v for k, v in sorted(record["boot_clear"].items())},
                     "regions": {name: {**r, "native": {symbolize(title, k): v for k, v in sorted(r["native"].items())},
                                        "slink": {symbolize(title, k): v for k, v in sorted(r["slink"].items())}}
                                 for name, r in record["regions"].items()},
                     "control": {**record["control"], "native_writers": {
                         symbolize(title, k): v for k, v in sorted(record["control"]["native_writers"].items())}}}

    writers: dict[str, int] = {}
    for record in legs.values():
        for key, count in record["writers"].items():
            writers[key] = writers.get(key, 0) + count
    first = legs["panel"]
    receipt = {"schema": SCHEMA, "title": title, "evidence_level": "PHYSICAL", "result": "PASS",
               "overlay_sha1": facts["overlay_sha1"], "fixture": first["fixture"], "fixture_sha256": first["fixture_sha256"],
               "facts": facts, "legs": legs, "corpus_frames": sum(r["corpus_frames"] for r in legs.values()),
               "writers": dict(sorted(writers.items())), "violation_count": 0,
               "input_mode": "normal_buttons", "harness_write_scopes": []}
    (REPO / live.RECEIPTS / f"{title}_overlay.w6_gate.json").write_text(
        json.dumps(receipt, indent=1, sort_keys=True) + "\n", encoding="utf-8")

