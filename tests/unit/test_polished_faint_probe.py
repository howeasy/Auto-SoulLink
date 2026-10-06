"""F3 authoring evidence: synthetic oracle/runner tests and Lua 5.5 compile ONLY."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "faint_probe", ROOT / "tools/polished_live/faint_probe.py"
)
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


@pytest.fixture
def inputs():
    # Synthetic ROM, but symbol relationships identical to the real contract.
    syms = {
        "ResolveFaints": (15, 0x44AF),
        "ResolveFaints.no_fainted_mons": (15, 0x44C7),
        "FaintUserPokemon": (15, 0x4CD2),
        "LostBattle": (15, 0x4FF6),
        "UpdateBattleMonInParty": (0, 0x34B0),
        "UpdateEnemyMonInParty": (0, 0x34C3),
        "HasUserFainted": (0, 0x3673),
        "hBattleTurn": (0, 0xFFD1),
        "hROMBank": (0, 0xFF87),
        "wPartyMon1": (1, 0xDCD6),
        "wPartyMon2": (1, 0xDD06),
    }
    for i, label in enumerate(P.FIELDS.values()):
        syms.setdefault(label, (1, 0xD100 + i * 3))
    rom = bytearray(0x40000)
    codes = {
        0x44AF: "f0d1f5",
        0x44C8: "e0d1",
        0x44CA: "cdb034",
        0x44CD: "cdc334",
        0x4CD2: "cd7336c0",
        0x4FF6: "3e01ea",
    }
    for address, hexed in codes.items():
        at = 15 * 0x4000 + address - 0x4000
        rom[at : at + len(bytes.fromhex(hexed))] = bytes.fromhex(hexed)
    return syms, bytes(rom)


@pytest.fixture
def config(inputs):
    syms, rom = inputs
    return {
        "run_id": "test-run",
        "contract": P.derive_contract(syms, rom),
        "provenance": {"rom_sha1": P.digest(rom, "sha1"), "fixture_sha256": "b" * 64},
        "frames": 100,
        "trace_cap": 1000,
        "steps": [],
    }


def hit(config, kind, **over):
    site = config["contract"]["sites"][kind]
    row = {
        "kind": kind,
        "frame": 20,
        "hook_addr": site["addr"],
        "hook_bytes": site["bytes"],
        "pc": site["addr"],
        "sp": 0xC0D0,
        "bank": site["bank"],
        "matched": True,
        "qualified": True,
        "battle_hp_bytes": [0, 10],
        "battle_hp": 10,
        "battle_status": 0,
        "party_hp_bytes": [0, 10],
        "party_hp": 10,
        "party_status": 0,
        "slot": 0,
        "count": 2,
        "party_slot_valid": True,
        "order": 0,
        "substatus2": 0,
        "turn": 0,
        "mode": 1,
    }
    row.update(over)
    return row


def envelope(config, rows):
    trace = [
        {
            "kind": "begin",
            "frame": 0,
            "run_id": config["run_id"],
            "provenance": copy.deepcopy(config["provenance"]),
        }
    ] + copy.deepcopy(rows)
    counts = Counter(r["kind"] for r in rows if r["kind"] in P.SITES)
    trace.append(
        {
            "kind": "final",
            "frame": config["frames"],
            "completed": True,
            "elapsed": config["frames"],
            "hook_hits": sum(counts.values()),
            "counts": {k: counts[k] for k in P.SITES},
            "guest_writes": 0,
            "cpu_changes": 0,
            "overflows": 0,
            "driver_errors": 0,
        }
    )
    for i, row in enumerate(trace, 1):
        row["ord"] = i
    return trace


def passes(config, *, faint=False, unnotified=False):
    rows = [hit(config, "resolve")]
    if faint:
        rows += [hit(config, "faint", turn=0, order=1), hit(config, "faint", turn=1, order=1)]
    for kind in ("pre_copy", "copy_call", "copy_return"):
        row = hit(config, kind)
        if faint or unnotified:
            row.update(
                battle_hp_bytes=[0, 0], battle_hp=0, order=int(faint), substatus2=4 if faint else 0
            )
            if kind == "copy_return":
                row.update(party_hp_bytes=[0, 0], party_hp=0)
        rows.append(row)
    return rows


@pytest.mark.parametrize(
    "case,expected",
    [
        ("healthy", "PASS"),
        ("native-faint", "PASS"),
        ("none", "NO_HIT"),
        ("wrong-pc", "WRONG_PC"),
        ("wrong-order", "ORDER_VIOLATION"),
        ("unnotified", "FAINT_NOT_OBSERVED_AT_44CD"),
        ("truncated", "FAIL"),
    ],
    ids=["healthy", "native-faint", "no-hit", "wrong-pc", "order", "unnotified", "truncated"],
)
def test_each_named_verdict(config, case, expected):
    rows = (
        []
        if case == "none"
        else passes(config, faint=case == "native-faint", unnotified=case == "unnotified")
    )
    if case == "wrong-pc":
        rows[1].update(pc=rows[1]["pc"] + 2, qualified=False)
    if case == "wrong-order":
        rows[1], rows[2] = rows[2], rows[1]
    trace = envelope(config, rows)
    if case == "truncated":
        trace.pop()
    verdict, reasons = P.evaluate(trace, config)
    assert verdict == expected, reasons


@pytest.mark.parametrize("kind", list(P.SITES), ids=list(P.SITES))
def test_wrong_bank_is_retained_but_never_counts(config, kind):
    row = hit(config, kind, bank=0x25, matched=False, qualified=False)
    assert P.evaluate(envelope(config, [row]), config)[0] == "NO_HIT"
    assert P.evaluate(envelope(config, [row] + passes(config)), config)[0] == "PASS"


@pytest.mark.parametrize("kind", ["pre_copy", "copy_return"], ids=["44c8", "44cd"])
def test_wrong_pc_records_observed_address(config, kind):
    rows = passes(config)
    row = next(r for r in rows if r["kind"] == kind)
    row.update(pc=row["pc"] + 3, qualified=False)
    verdict, reasons = P.evaluate(envelope(config, rows), config)
    assert verdict == "WRONG_PC"
    assert any(f"observed={row['pc']:#06x}" in r for r in reasons)


@pytest.mark.parametrize(
    "kinds",
    [
        ["resolve", "copy_call", "pre_copy", "copy_return"],
        ["resolve", "pre_copy", "faint", "copy_call", "copy_return"],
        ["resolve", "pre_copy", "copy_call"],
        ["resolve", "resolve", "pre_copy", "copy_call", "copy_return"],
        ["resolve", "lost", "pre_copy", "copy_call", "copy_return"],
    ],
    ids=["swapped", "late-faint", "missing-return", "nested-entry", "early-loss"],
)
def test_order_violation_is_not_erased_by_final(config, kinds):
    assert (
        P.evaluate(envelope(config, [hit(config, k) for k in kinds]), config)[0]
        == "ORDER_VIOLATION"
    )


def test_multiple_passes_and_loss_after_copy_return(config):
    rows = passes(config, faint=True) + [hit(config, "lost")] + passes(config)
    assert P.evaluate(envelope(config, rows), config)[0] == "PASS"


@pytest.mark.parametrize(
    "case",
    [
        "ordinal",
        "frame",
        "bank-flag",
        "pc-flag",
        "bytes",
        "hook",
        "hp",
        "slot",
        "bool-count",
        "count-census",
        "final-budget",
        "frame-budget",
        "duplicate-final",
        "provenance",
        "unknown",
        "final-mutation",
        "overflow",
        "missing-status",
    ],
    ids=[
        "ordinal",
        "rewind",
        "forged-bank",
        "forged-pc",
        "rom-bytes",
        "hook-address",
        "hp-total",
        "slot-validity",
        "bool-counter",
        "censored",
        "early-final",
        "short-frames",
        "two-finals",
        "provenance",
        "unknown",
        "mutated",
        "overflow",
        "missing-field",
    ],
)
def test_forged_or_incomplete_evidence_fails(config, case):
    trace = envelope(config, passes(config))
    if case == "ordinal":
        trace[2]["ord"] = 1
    elif case == "frame":
        trace[2]["frame"] = 1
    elif case == "bank-flag":
        trace[2]["bank"] = 0x25
    elif case == "pc-flag":
        trace[2]["pc"] += 1
    elif case == "bytes":
        trace[2]["hook_bytes"] = "0000"
    elif case == "hook":
        trace[2]["hook_addr"] += 1
    elif case == "hp":
        trace[2]["battle_hp"] = 999
    elif case == "slot":
        trace[2]["slot"] = 255
    elif case == "bool-count":
        trace[-1]["counts"]["resolve"] = True
    elif case == "count-census":
        trace[-1]["hook_hits"] -= 1
    elif case == "final-budget":
        trace[-1]["elapsed"] -= 1
    elif case == "frame-budget":
        trace[-1]["frame"] -= 1
    elif case == "duplicate-final":
        trace.insert(-1, copy.deepcopy(trace[-1]))
    elif case == "provenance":
        trace[0]["provenance"]["rom_sha1"] = "0" * 40
    elif case == "unknown":
        trace[2]["kind"] = "filtered-hit"
    elif case == "final-mutation":
        trace[-1]["guest_writes"] = 1
    elif case == "overflow":
        trace[2]["kind"] = "overflow"
    else:
        del trace[2]["battle_status"]
    assert P.evaluate(trace, config)[0] == "FAIL"


@pytest.mark.parametrize(
    "trace",
    [None, {}, [], [1], [{"kind": "final"}]],
    ids=["null", "object", "empty", "scalar-row", "final-only"],
)
def test_malformed_trace(config, trace):
    assert P.evaluate(trace, config)[0] == "FAIL"


def test_nonscalar_kind_is_malformed_not_an_oracle_crash(config):
    trace = envelope(config, passes(config))
    trace[1]["kind"] = []
    assert P.evaluate(trace, config)[0] == "FAIL"


def test_capacity_boundary_fails_even_without_later_callback(config):
    trace = envelope(config, passes(config))
    config["trace_cap"] = 4
    assert P.evaluate(trace, config)[0] == "FAIL"


@pytest.mark.parametrize(
    "kind", ["guest_write", "cpu_change", "driver_error"], ids=["write", "register", "exception"]
)
def test_failure_marker_overrides_otherwise_correct_trace(config, kind):
    trace = envelope(config, passes(config) + [{"kind": kind, "frame": 20}])
    assert P.evaluate(trace, config)[0] == "FAIL"


@pytest.mark.parametrize(
    "case",
    ["symbol", "bank", "stride", "call", "pre", "return", "faint", "short"],
    ids=[
        "symbol",
        "bank",
        "stride",
        "call-bytes",
        "pre-bytes",
        "return-bytes",
        "faint-bytes",
        "short-rom",
    ],
)
def test_contract_rejects_drift(inputs, case):
    syms, rom = inputs
    if case == "symbol":
        syms["ResolveFaints"] = (15, 0x44AE)
    elif case == "bank":
        syms["LostBattle"] = (14, 0x4FF6)
    elif case == "stride":
        syms["wPartyMon2"] = (1, 0xDD07)
    elif case == "short":
        rom = rom[:50]
    else:
        address = {"call": 0x44CA, "pre": 0x44C8, "return": 0x44CD, "faint": 0x4CD2}[case]
        raw = bytearray(rom)
        raw[15 * 0x4000 + address - 0x4000] ^= 1
        rom = bytes(raw)
    with pytest.raises(ValueError):
        P.derive_contract(syms, rom)


@pytest.mark.parametrize(
    "route",
    [{"steps": [{"frames": 2, "buttons": ["A"]}]}, {"steps": [{"frames": 1, "buttons": []}]}],
    ids=["press", "idle"],
)
def test_native_route_allowed(tmp_path, route):
    fixture, path = tmp_path / "save", tmp_path / "route.json"
    fixture.write_bytes(bytes(32768))
    path.write_text(json.dumps(route))
    args = P.parse_args(
        ["--setup", "played", "--fixture", str(fixture), "--route", str(path), "--frames", "10"]
    )
    assert args.steps == route["steps"]


@pytest.mark.parametrize(
    "route",
    [
        {"steps": [], "warp": 1},
        {"steps": [{"frames": True, "buttons": []}]},
        {"steps": [{"frames": 1, "buttons": ["A", "A"]}]},
        {"steps": [{"frames": 1, "buttons": ["poke"]}]},
        {"steps": [{"frames": 11, "buttons": []}]},
        {"steps": [{"frames": 1, "buttons": [], "write": 1}]},
    ],
    ids=[
        "setup-field",
        "bool-frames",
        "duplicate-button",
        "invalid-button",
        "budget",
        "write-field",
    ],
)
def test_route_rejects_hidden_setup(tmp_path, route):
    fixture, path = tmp_path / "save", tmp_path / "route.json"
    fixture.write_bytes(bytes(32768))
    path.write_text(json.dumps(route))
    with pytest.raises(SystemExit):
        P.parse_args(
            ["--setup", "played", "--fixture", str(fixture), "--route", str(path), "--frames", "10"]
        )


def test_dry_run_has_no_staging_environment_or_process_side_effect(
    tmp_path, monkeypatch, inputs, config
):
    fixture = tmp_path / "played.SaveRAM"
    fixture.write_bytes(bytes(32768))
    monkeypatch.setattr(P, "WORK", tmp_path / "must-not-exist")
    monkeypatch.setattr(
        P, "prepare", lambda: (inputs[1], config["contract"], copy.deepcopy(config["provenance"]))
    )

    def forbidden(*_a, **_k):
        pytest.fail("dry-run attempted staging/process work")

    monkeypatch.setattr(P.tempfile, "mkdtemp", forbidden)
    before_env, before_files, before_modules = (
        dict(os.environ),
        list(tmp_path.iterdir()),
        set(sys.modules),
    )
    assert P.main(["--setup", "played", "--fixture", str(fixture), "--dry-run"]) == 0
    assert dict(os.environ) == before_env and list(tmp_path.iterdir()) == before_files
    assert "harness" not in set(sys.modules) - before_modules


@pytest.mark.parametrize(
    "case,ok",
    [("complete", True), ("truncated", False), ("launch-error", False)],
    ids=["runner-complete", "runner-truncated", "runner-exception"],
)
def test_runner_with_synthetic_launcher_only(tmp_path, monkeypatch, inputs, config, case, ok):
    fixture = tmp_path / "played.SaveRAM"
    fixture.write_bytes(bytes(32768))
    monkeypatch.setattr(P, "WORK", tmp_path / "lane")
    monkeypatch.setattr(
        P, "prepare", lambda: (inputs[1], config["contract"], copy.deepcopy(config["provenance"]))
    )
    for name in ("POL_LANE", "POL_KIND", "POL_FIXTURE"):
        monkeypatch.setenv(
            name, "original"
        )  # restore environment after main's explicit live-path staging
    seen = []

    def launch(lua_path, run, env, timeout):
        seen.append(lua_path)
        cfg = json.loads(Path(env["POL_PROBE_CONFIG"]).read_text())
        assert cfg["provenance"]["fixture_sha256"] == P.digest(fixture.read_bytes())
        if case == "launch-error":
            raise RuntimeError("synthetic launcher failure")
        trace = envelope(cfg, passes(cfg, faint=True))
        if case == "truncated":
            trace.pop()
        (run / "trace.json").write_text(json.dumps(trace))
        return "RESULT: PASS faint-probe recording (0 checks failed)", 12345

    harness = SimpleNamespace(launch=launch)
    monkeypatch.setitem(sys.modules, "harness", harness)
    assert (P.main(["--setup", "played", "--fixture", str(fixture)]) == 0) == ok
    assert seen == ["tools/polished_live/faint_probe.lua"]
    assert (harness.SRAM / harness.SAVE_NAME).read_bytes() == fixture.read_bytes()
    (verdict,) = list(P.WORK.glob("*/probe/verdict.json"))
    assert json.loads(verdict.read_text())["verdict"] == ("PASS" if ok else "FAIL")


@pytest.mark.parametrize(
    "bad", ["symbols", "base", "overlay"], ids=["symbols-pin", "base-pin", "overlay-pin"]
)
def test_prepare_rejects_provenance_drift(tmp_path, monkeypatch, inputs, bad):
    syms, rom = inputs
    root = tmp_path / "repo"
    (root / "data/polished").mkdir(parents=True)
    (root / "patch/dist").mkdir(parents=True)
    (root / "tools/polished_live").mkdir(parents=True)
    sym = "".join(f"{bank:02x}:{addr:04x} {name}\n" for name, (bank, addr) in syms.items()).encode()
    (root / "data/polished/polished_slink.sym").write_bytes(sym)
    (root / "patch/dist/SLink-Polished.ups").write_bytes(b"synthetic-ups")
    (root / "tools/polished_live/faint_probe.lua").write_text("-- synthetic driver")
    release = tmp_path / "release.gbc"
    release.write_bytes(rom)
    prov = {
        "symbols": {"polished_slink.sym": P.digest(sym)},
        "base_sha1": P.digest(rom, "sha1"),
        "output": {"sha1": P.digest(rom, "sha1")},
    }
    if bad == "symbols":
        prov["symbols"]["polished_slink.sym"] = "0" * 64
    elif bad == "base":
        prov["base_sha1"] = "0" * 40
    else:
        prov["output"]["sha1"] = "0" * 40
    (root / "data/polished/overlay_provenance.json").write_text(json.dumps(prov))
    monkeypatch.setattr(P, "REPO", root)
    monkeypatch.setattr(P, "RELEASE", release)
    from patch.tools import make_ups

    monkeypatch.setattr(make_ups, "ups_apply", lambda clean, ups: clean)
    with pytest.raises(ValueError, match="provenance"):
        P.prepare()


@pytest.mark.parametrize(
    "text,elapsed,timeout,ok",
    [
        ("RESULT: PASS faint-probe recording (0 checks failed)", 1, 10, True),
        ("", 1, 10, False),
        ("RESULT: PASS wrong", 1, 10, False),
        (
            "RESULT: PASS faint-probe recording x\nRESULT: PASS faint-probe recording y",
            1,
            10,
            False,
        ),
        ("RESULT: PASS faint-probe recording x", 10, 10, False),
    ],
    ids=["complete", "absent", "wrong-tag", "duplicate", "deadline"],
)
def test_recording_result_and_deadline(text, elapsed, timeout, ok):
    assert (not P.recording_reasons(text, elapsed, timeout)) == ok


def test_lua55_compile_only_and_no_literal_guest_addresses():
    lua55 = pytest.importorskip("lupa.lua55")
    lua = lua55.LuaRuntime(unpack_returned_tuples=True)
    source = (ROOT / "tools/polished_live/faint_probe.lua").read_text()
    assert lua.eval("function(s) return assert(load(s)) ~= nil end")(
        source
    )  # NEVER call the loaded chunk
    assert "0x44" not in source and "0xFF" not in source and "memory.write" not in source
    assert 'name:match("^write")' in source and 'name == "setregister"' in source
    assert 'append("overflow"' in source and 'append("final"' in source
    assert "pcall(record, kind, site)" in source
