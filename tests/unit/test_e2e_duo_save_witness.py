"""S-7's save witness: the hook-time dump hashed against the flushed SaveRAM.

The check runs from `_run_oracle` for every gen1_new scenario, so its failure modes are the
scenario's failure modes: a stale dump, a name the body and the harness disagree about, a short
or missing file, or bytes that differ. Each is pinned here against a synthetic 0x8000 image and
a synthetic dump, and each check removed has to fail its own case.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import e2e_duo as duo  # noqa: E402

from server.adapters import gen1_codec as codec  # noqa: E402

SITE = duo.SAVE_WITNESS_START


def _image(seed=0x11):
    """A synthetic 32 KiB SaveRAM: the slice's bytes are a function of their address."""
    return bytes(((address * 7 + seed) & 0xFF) for address in range(codec.SRAM_SIZE))


def _dump_line(blob, saves=1, frame=100, rel=None):
    return (f"SAVE_WITNESS_DUMP path={rel} bytes={len(blob)} saves={saves} frame={frame}")


def _stub(tmp_path, monkeypatch, *, blob=None, flushed=None, a_extra="", b_extra="",
          patched=False):
    """A DuoRun whose flush is `flushed` and whose witness file holds `blob`."""
    build = tmp_path / "build"
    build.mkdir(exist_ok=True)
    flushed = flushed if flushed is not None else _image()
    blob = blob if blob is not None else flushed[SITE:duo.SAVE_WITNESS_END]

    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario = "link_new"
    run.attempt = 1
    run.game = "gen1_new"
    run.emus = []
    run.cfg = dict(duo.SCENARIOS["link_new"])
    if patched:
        run.cfg["patched_saves"] = {"a": "red_patched", "b": "blue_patched"}
    run.gcfg = dict(duo.GAMES["gen1_new"])
    run.data_dir = str(tmp_path)
    notes = []
    run._pydec_note = notes.append
    monkeypatch.setattr(duo, "BUILD", str(build))
    # The body logs a path relative to the repo root (duo_gen1_main.lua:81-84), which the check
    # joins back on — pin that form by making the stub's repo root this tmp dir.
    monkeypatch.setattr(duo, "REPO", str(tmp_path))
    monkeypatch.setattr(run, "_saved_gen1_party",
                        lambda inst, **kw: (flushed, [], [], codec))
    monkeypatch.setattr(run, "_patched_saved_state",
                        lambda inst: (b"\x00" * codec.SRAM_SIZE, [], [], codec))

    lines = {}
    for inst in ("a", "b"):
        rel = os.path.relpath(os.path.join(str(build), f"e2e_link_new_{inst}_1_witness.bin"),
                              tmp_path)
        lines[inst] = "\n".join([
            "SAVE_WITNESS link_new frames=900",
            _dump_line(blob, saves=1, frame=100, rel=rel),
            _dump_line(blob, saves=2, frame=900, rel=rel),
        ])
    results = {"a": lines["a"] + a_extra, "b": lines["b"] + b_extra}
    for inst in ("a", "b"):
        if blob is not None:
            (build / f"e2e_link_new_{inst}_1_witness.bin").write_bytes(blob)
    return run, results, notes, build


def test_matching_witness_emits_the_exact_line(tmp_path, monkeypatch):
    run, results, notes, _build = _stub(tmp_path, monkeypatch)
    run.check_save_witness(results)
    expected = hashlib.sha256(_image()[SITE:duo.SAVE_WITNESS_END]).hexdigest()
    assert notes == [
        f"SAVE_WITNESS_SHA256 inst={inst} site={expected} file={expected} match=true saves=2"
        for inst in ("a", "b")]


def test_one_byte_different_fails_and_names_the_address(tmp_path, monkeypatch):
    run, results, notes, _build = _stub(tmp_path, monkeypatch)
    # 0x3523 is sMainDataCheckSum: written ~120 frames AFTER the hook (save.asm:170-172), which
    # is why the message names the address rather than just "different".
    address = duo.SAVE_WITNESS_POST_HOOK[0]
    blob = bytearray(_image()[SITE:duo.SAVE_WITNESS_END])
    blob[address - SITE] ^= 0xFF
    (Path(duo.BUILD) / "e2e_link_new_a_1_witness.bin").write_bytes(bytes(blob))
    with pytest.raises(RuntimeError) as excinfo:
        run.check_save_witness(results)
    message = str(excinfo.value)
    assert "a: the save witness does not match the flushed SaveRAM" in message
    assert "0x3523" in message and "sMainDataCheckSum" in message, message
    assert notes[-1].endswith("match=false saves=2"), notes[-1]


def test_short_witness_fails(tmp_path, monkeypatch):
    run, results, _notes, _build = _stub(tmp_path, monkeypatch)
    (Path(duo.BUILD) / "e2e_link_new_b_1_witness.bin").write_bytes(b"\x00" * 100)
    with pytest.raises(RuntimeError, match=r"b: the save witness is short — 100 bytes"):
        run.check_save_witness(results)


def test_missing_witness_with_a_save_marker_fails(tmp_path, monkeypatch):
    run, results, _notes, build = _stub(tmp_path, monkeypatch)
    (build / "e2e_link_new_a_1_witness.bin").unlink()
    with pytest.raises(RuntimeError, match="a: the save witness is missing at"):
        run.check_save_witness(results)


def test_missing_witness_quotes_a_failed_dump(tmp_path, monkeypatch):
    run, results, _notes, build = _stub(tmp_path, monkeypatch,
                                        a_extra="\nSAVE_WITNESS_DUMP_FAIL cannot open "
                                                "patch/build/x_witness.bin")
    (build / "e2e_link_new_a_1_witness.bin").unlink()
    with pytest.raises(RuntimeError, match="SAVE_WITNESS_DUMP_FAIL: cannot open"):
        run.check_save_witness(results)


def test_a_half_that_never_saves_is_skipped(tmp_path, monkeypatch):
    """reconnect_new's relaunch phases log no save marker at all: the line says so and the
    check does not invent a dump to compare."""
    run, results, notes, _build = _stub(tmp_path, monkeypatch)
    results["b"] = "RECONNECT_READY b linked_key=AAAA:1111:01\n"
    run.check_save_witness(results)
    assert notes[0].endswith("match=true saves=2")
    assert notes[1] == "SAVE_WITNESS_SHA256 inst=b site=- file=- match=- saves=0 skipped"


def test_a_logged_path_the_harness_did_not_expect_fails(tmp_path, monkeypatch):
    run, results, _notes, _build = _stub(tmp_path, monkeypatch)
    results["a"] = results["a"].replace("e2e_link_new_a_1_witness.bin",
                                        "e2e_link_new_a_2_witness.bin")
    with pytest.raises(RuntimeError, match="disagree about the name"):
        run.check_save_witness(results)


def test_the_flush_comes_from_the_scenarios_own_resolver(tmp_path, monkeypatch):
    """A trade-carrying ROM saves under its patched name; comparing the witness against the
    gamedb-named fixture would fail for a reason that is not the cartridge's."""
    run, results, _notes, _build = _stub(tmp_path, monkeypatch, patched=True)
    with pytest.raises(RuntimeError, match="does not match the flushed SaveRAM"):
        run.check_save_witness(results)  # _patched_saved_state returns zeros


def test_stale_witnesses_are_cleared_at_attempt_start(tmp_path, monkeypatch):
    run, _results, _notes, build = _stub(tmp_path, monkeypatch, blob=None)
    (build / "e2e_link_new_a_1_witness.bin").write_bytes(b"old")
    (build / "e2e_link_new_a_7_witness.bin").write_bytes(b"older")
    (build / "e2e_deadzone_new_a_1_witness.bin").write_bytes(b"another scenario")
    (build / "e2e_link_new_a_result.txt").write_text("stale", encoding="utf-8")
    run._result_path = lambda inst: str(build / f"e2e_link_new_{inst}_result.txt")
    run.go_files = {inst: str(build / f"duo_go_link_new_{inst}.txt") for inst in ("a", "b")}
    for inst in ("a", "b"):
        Path(run.go_files[inst]).write_text("GO\n", encoding="utf-8")
    run._clear_attempt_artifacts()
    assert sorted(p.name for p in build.iterdir()) == ["e2e_deadzone_new_a_1_witness.bin"]


def test_run_oracle_checks_the_witness_before_the_scenario_oracle(tmp_path, monkeypatch):
    run, results, _notes, _build = _stub(tmp_path, monkeypatch)
    order = []
    monkeypatch.setattr(run, "check_save_witness", lambda res: order.append("witness"))
    run.assert_stub_oracle = lambda res, **kw: order.append("oracle")
    run.cfg["oracle"] = "assert_stub_oracle"
    run._run_oracle(results)
    assert order == ["witness", "oracle"]


def test_run_oracle_skips_the_witness_for_other_generations(tmp_path, monkeypatch):
    run, results, _notes, _build = _stub(tmp_path, monkeypatch)
    run.game = "gen3_rr"
    order = []
    monkeypatch.setattr(run, "check_save_witness", lambda res: order.append("witness"))
    run.assert_stub_oracle = lambda res, **kw: order.append("oracle")
    run.cfg["oracle"] = "assert_stub_oracle"
    run._run_oracle(results)
    assert order == ["oracle"]


def test_a_rejected_dump_gate_fails_with_the_lua_reason(tmp_path, monkeypatch):
    """The committed body gates the dump on the signal validating (duo_gen1_main.lua:123-147): a
    rejected fire writes no file and logs why. A save whose dump gate said no is a defect — the
    failure quotes the client's own reason instead of reporting a bare missing file."""
    run, results, _notes, build = _stub(tmp_path, monkeypatch)
    results["a"] = results["a"].replace("SAVE_WITNESS_DUMP path=",
                                        "SAVE_WITNESS_DUMP_SKIPPED why=pending-0-to-0\n"
                                        "SAVE_WITNESS_DUMP path=")
    results["a"] = "\n".join(line for line in results["a"].splitlines()
                             if "SAVE_WITNESS_DUMP path=" not in line)
    (build / "e2e_link_new_a_1_witness.bin").unlink()
    with pytest.raises(RuntimeError, match="dump gate rejected the fire"):
        run.check_save_witness(results)


def test_the_diff_helper_reports_sram_addresses():
    site = bytes([0, 1, 2, 3, 4])
    flushed = bytearray(site)
    flushed[2] = 9
    assert duo.save_witness_diff(site, bytes(flushed)) == [duo.SAVE_WITNESS_START + 2]
    assert duo.save_witness_diff(site, site) == []


def test_the_contract_constants_are_the_bodys_own_slice():
    """0x498:0x8000 is what duo_gen1_main.lua:89 dumps and what docs/gen1_requirements.md pins
    for S-7 — 0x7B68 bytes, past the three sprite buffers (3 * 0x188)."""
    body = (REPO / "lua" / "tests" / "duo" / "duo_gen1_main.lua").read_text(encoding="utf-8")
    assert duo.SAVE_WITNESS_START == 0x498 and duo.SAVE_WITNESS_END == 0x8000
    assert duo.SAVE_WITNESS_BYTES == 0x7B68 == 31592
    assert "local WITNESS_FROM, WITNESS_TO = 0x498, 0x8000" in body
    assert 'fmt("patch/build/e2e_%s_%s_%d_witness.bin", D.scenario, D.player, D.attempt or 1)' \
        in body
    assert "SAVE_WITNESS_DUMP path=%s bytes=%d saves=%d frame=%d" in body
    assert 'log("SAVE_WITNESS_DUMP_FAIL " .. tostring(derr))' in body
    assert 'log("SAVE_WITNESS_DUMP_SKIPPED why=" .. why)' in body


def test_the_poison_and_clause_scenarios_are_covered_by_the_same_check():
    """Every gen1_new registry entry goes through `_run_oracle`, so none can opt out of S-7."""
    for name in duo.scenarios_for("gen1_new"):
        assert duo.SCENARIOS[name].get("oracle"), name
