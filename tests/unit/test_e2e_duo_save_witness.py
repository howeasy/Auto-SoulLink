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
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import e2e_duo as duo  # noqa: E402

from server.adapters import gen1_codec as codec  # noqa: E402

SITE = duo.SAVE_WITNESS_START
_ROM_BYTES = {"a": b"companion-red", "b": b"companion-blue"}


def _client_line(inst):
    digest = hashlib.sha1(_ROM_BYTES[inst]).hexdigest()
    return (f"client built: title=red pack=gen1_rby kind=named player={inst} "
            f"rom={digest[:8]} -> 127.0.0.1:54321")


def _rom_note(inst, prefix=None):
    digest = hashlib.sha1(_ROM_BYTES[inst]).hexdigest()
    return (f"GEN1_ROM_SHA1 inst={inst} rom=roms/{inst}.gb sha1={digest} "
            f"receipt={prefix or digest[:8]} computed={digest[:8]} match=true")


def _image(seed=0x11):
    """A synthetic 32 KiB SaveRAM: the slice's bytes are a function of their address."""
    return bytes(((address * 7 + seed) & 0xFF) for address in range(codec.SRAM_SIZE))


def _dump_line(blob, saves=1, frame=100, rel=None):
    return (f"SAVE_WITNESS_DUMP path={rel} bytes={len(blob)} saves={saves} frame={frame}")


def _stub(tmp_path, monkeypatch, *, blob=None, flushed=None, a_extra="", b_extra=""):
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

    (tmp_path / "roms").mkdir()
    for inst, raw in _ROM_BYTES.items():
        (tmp_path / "roms" / f"{inst}.gb").write_bytes(raw)
    monkeypatch.setattr(run, "_rom_for", lambda inst: f"roms/{inst}.gb")

    lines = {}
    for inst in ("a", "b"):
        rel = os.path.relpath(os.path.join(str(build), f"e2e_link_new_{inst}_1_witness.bin"),
                              tmp_path)
        lines[inst] = "\n".join([
            _client_line(inst),
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
        note for inst in ("a", "b") for note in (
            _rom_note(inst),
            f"SAVE_WITNESS_SHA256 inst={inst} site={expected} file={expected} match=true saves=2",
        )]


def test_one_byte_different_fails_and_names_the_address(tmp_path, monkeypatch):
    run, results, notes, _build = _stub(tmp_path, monkeypatch)
    # Any byte will do; the message names the SRAM address rather than just "different", which
    # is what a reader can look up (the live lane confirmed the hook-time dump is byte-identical
    # to the flushed slice, so there is no expected-difference byte to exclude).
    address = SITE + 0x100
    blob = bytearray(_image()[SITE:duo.SAVE_WITNESS_END])
    blob[address - SITE] ^= 0xFF
    (Path(duo.BUILD) / "e2e_link_new_a_1_witness.bin").write_bytes(bytes(blob))
    with pytest.raises(RuntimeError) as excinfo:
        run.check_save_witness(results)
    message = str(excinfo.value)
    assert "a: the save witness does not match the flushed SaveRAM" in message
    assert hex(address) in message, message
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
    run, results, _notes, build = _stub(tmp_path, monkeypatch)
    # A save that never produced a dump: the plain marker is there, the FAIL is the only dump
    # outcome, and the file is absent.
    results["a"] = "\n".join(
        line for line in results["a"].splitlines() if not line.startswith("SAVE_WITNESS_DUMP "))
    results["a"] += "\nSAVE_WITNESS_DUMP_FAIL cannot open patch/build/x_witness.bin"
    (build / "e2e_link_new_a_1_witness.bin").unlink()
    with pytest.raises(RuntimeError, match="SAVE_WITNESS_DUMP_FAIL: cannot open"):
        run.check_save_witness(results)


def test_a_failed_dump_after_a_successful_one_is_not_masked(tmp_path, monkeypatch):
    """The file on disk is then the EARLIER save's, which can be byte-identical to what the
    final save would have written — so the outcomes are read in order."""
    run, results, _notes, _build = _stub(tmp_path, monkeypatch)
    results["a"] += "\nSAVE_WITNESS_DUMP_FAIL cannot open patch/build/x_witness.bin"
    with pytest.raises(RuntimeError, match="the last dump attempt was"):
        run.check_save_witness(results)


def test_a_gapped_dump_ordinal_is_rejected(tmp_path, monkeypatch):
    run, results, _notes, _build = _stub(tmp_path, monkeypatch)
    results["a"] = results["a"].replace("saves=2 frame=900", "saves=3 frame=900")
    with pytest.raises(RuntimeError, match=r"ordinals are \[1, 3\]"):
        run.check_save_witness(results)


def test_a_half_that_never_saves_is_skipped(tmp_path, monkeypatch):
    """reconnect_new's relaunch phases log no save marker at all: the line says so and the
    check does not invent a dump to compare."""
    run, results, notes, _build = _stub(tmp_path, monkeypatch)
    results["b"] = _client_line("b") + "\nRECONNECT_READY b linked_key=AAAA:1111:01\n"
    run.check_save_witness(results)
    assert notes[0] == _rom_note("a")
    assert notes[1].endswith("match=true saves=2")
    assert notes[2] == _rom_note("b")
    assert notes[3] == "SAVE_WITNESS_SHA256 inst=b site=- file=- match=- saves=0 skipped"


def test_a_logged_path_the_harness_did_not_expect_fails(tmp_path, monkeypatch):
    run, results, _notes, _build = _stub(tmp_path, monkeypatch)
    results["a"] = results["a"].replace("e2e_link_new_a_1_witness.bin",
                                        "e2e_link_new_a_2_witness.bin")
    with pytest.raises(RuntimeError, match="disagree about the name"):
        run.check_save_witness(results)


def test_the_flush_comes_from_the_oracles_own_default_read(tmp_path, monkeypatch):
    """The witness is compared with exactly what `_saved_gen1_party` reads by default (the
    launched cartridge's save, see test_e2e_duo_lane_isolation), never a hardcoded name: no
    save_name is passed at all -- a scenario-staged cartridge is resolved by that default too."""
    run, results, _notes, _build = _stub(tmp_path, monkeypatch)
    seen = []
    flushed = _image()
    monkeypatch.setattr(run, "_saved_gen1_party",
                        lambda inst, **kw: seen.append(kw) or (flushed, [], [], codec))
    run.check_save_witness(results)
    assert seen and all(kw == {} for kw in seen), seen


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
    run.game = "legacy"             # gen3_rr is the new battery row since ac448144
    order = []
    monkeypatch.setattr(run, "check_save_witness", lambda res: order.append("witness"))
    run.assert_stub_oracle = lambda res, **kw: order.append("oracle")
    run.cfg["oracle"] = "assert_stub_oracle"
    run._run_oracle(results)
    assert order == ["oracle"]


def test_new_family_cannot_pass_on_client_results_alone(tmp_path, monkeypatch):
    run, _results, _notes, _build = _stub(tmp_path, monkeypatch)
    run.game = "unregistered_duo_family"
    run.cfg = {}
    with pytest.raises(RuntimeError, match="evidence contract"):
        run._run_oracle({"a": "RESULT: PASS", "b": "RESULT: PASS"})


def test_missing_oracle_is_rejected_before_launch(tmp_path, monkeypatch):
    run, _results, _notes, _build = _stub(tmp_path, monkeypatch)
    run.cfg.pop("oracle")
    launched = []
    run.start_server = lambda: launched.append("server")
    run.start_instances = lambda: launched.append("instances")
    run.orchestrate = lambda: None
    run.wait_results = lambda: ("RESULT: PASS", "RESULT: PASS")
    run.cleanup = lambda passed: None
    with pytest.raises(RuntimeError, match="post-result oracle"):
        run.run()
    assert launched == []


def _required_family(run, monkeypatch):
    run.game = "model_duo_family"
    run.args = SimpleNamespace(keep_alive=False)
    monkeypatch.setitem(duo.FAMILY_EVIDENCE, "model_duo_family",
                        duo.EvidenceContract("assert_stub_witness", require_oracle=True))
    run.cfg = {"oracle": "assert_stub_oracle", "oracle_kwargs": {"expected": 7}}
    run.assert_stub_witness = lambda results: None
    run.assert_stub_oracle = lambda results, expected: None


@pytest.mark.parametrize("missing", ["witness", "oracle", "binding", "kwargs"])
def test_required_family_validates_all_stages_before_callbacks(tmp_path, monkeypatch, missing):
    run, results, _notes, _build = _stub(tmp_path, monkeypatch)
    _required_family(run, monkeypatch)
    calls = []
    run.assert_stub_witness = lambda res: calls.append("witness")
    if missing == "witness":
        run.assert_stub_witness = None
    elif missing == "oracle":
        run.cfg.pop("oracle")
    elif missing == "binding":
        run.assert_stub_oracle = None
    else:
        run.cfg["oracle_kwargs"] = []
    with pytest.raises(RuntimeError):
        run._run_oracle(results)
    assert calls == []


def test_required_family_transports_original_receipts_and_kwargs(tmp_path, monkeypatch):
    run, results, _notes, _build = _stub(tmp_path, monkeypatch)
    _required_family(run, monkeypatch)
    calls = []
    run.assert_stub_witness = lambda res: calls.append(("witness", res))
    run.assert_stub_oracle = lambda res, expected: calls.append((expected, res))
    run._run_oracle(results)
    assert [call[0] for call in calls] == ["witness", 7]
    assert all(call[1] is results for call in calls)


@pytest.mark.parametrize("stage", ["witness", "oracle"])
def test_required_family_explicit_false_fails(tmp_path, monkeypatch, stage):
    run, results, _notes, _build = _stub(tmp_path, monkeypatch)
    _required_family(run, monkeypatch)
    calls = []
    run.assert_stub_witness = lambda res: False if stage == "witness" else None
    run.assert_stub_oracle = lambda res, expected: calls.append("oracle") or False
    with pytest.raises(RuntimeError, match="rejected evidence"):
        run._run_oracle(results)
    assert calls == ([] if stage == "witness" else ["oracle"])


@pytest.mark.parametrize("missing_side", ["a", "b"])
def test_gen2_stub_missing_save_marker_cannot_skip(tmp_path, monkeypatch, missing_side):
    run, _results, notes, build = _stub(tmp_path, monkeypatch)
    _required_family(run, monkeypatch)
    results = dict.fromkeys(("a", "b"), "MODEL_SAVE_MARKER\nRESULT: PASS")
    results[missing_side] = "RESULT: PASS"
    calls = []

    def witness(receipts):
        # H2 supplies the real marker and save facts; this tests the injection boundary.
        for side in ("a", "b"):
            if "MODEL_SAVE_MARKER" not in receipts[side]:
                raise RuntimeError(f"{side}: missing save marker")

    run.assert_stub_witness = witness
    run.assert_stub_oracle = lambda res, expected: calls.append("oracle")
    run.start_server = lambda: None
    run.start_instances = lambda: None
    run.orchestrate = lambda: None
    run.wait_results = lambda: (results["a"], results["b"])
    run.cleanup = lambda passed: calls.append(passed)
    run._pydec_path = str(build / "pydec.txt")
    with pytest.raises(RuntimeError, match=f"{missing_side}: missing save marker"):
        run.run()
    assert calls == [False]
    assert notes == [f"PYDEC: FAIL {missing_side}: missing save marker"]


def test_required_binding_is_rechecked_after_launch(tmp_path, monkeypatch):
    run, _results, _notes, _build = _stub(tmp_path, monkeypatch)
    _required_family(run, monkeypatch)
    run.start_server = lambda: None
    run.start_instances = lambda: None
    run.orchestrate = lambda: setattr(run, "assert_stub_witness", None)
    run.wait_results = lambda: ("RESULT: PASS", "RESULT: PASS")
    run.cleanup = lambda passed: None
    with pytest.raises(RuntimeError, match="witness validator"):
        run.run()


def test_required_family_complete_run_emits_verdict_after_both_stages(tmp_path, monkeypatch):
    run, _results, notes, build = _stub(tmp_path, monkeypatch)
    _required_family(run, monkeypatch)
    calls = []
    run.args = SimpleNamespace(keep_alive=False)
    run.assert_stub_witness = lambda res: calls.append("witness")
    run.assert_stub_oracle = lambda res, expected: calls.append("oracle")
    run.start_server = lambda: calls.append("server")
    run.start_instances = lambda: calls.append("instances")
    run.orchestrate = lambda: None
    run.wait_results = lambda: ("RESULT: PASS", "RESULT: PASS")
    run.cleanup = lambda passed: calls.append(passed)
    run._pydec_path = str(build / "pydec.txt")
    assert run.run() is True
    assert calls == ["server", "instances", "witness", "oracle", True]
    assert notes == ["PYDEC: PASS asserted scenario facts"]


@pytest.mark.parametrize("contract", [None, duo.EvidenceContract(require_oracle=True),
                                     duo.EvidenceContract("assert_stub_witness"),
                                     duo.EvidenceContract("assert_stub_witness", "yes")])
def test_incomplete_contract_is_not_a_legacy_opt_out(tmp_path, monkeypatch, contract):
    run, results, _notes, _build = _stub(tmp_path, monkeypatch)
    _required_family(run, monkeypatch)
    monkeypatch.setitem(duo.FAMILY_EVIDENCE, "model_duo_family", contract)
    with pytest.raises(RuntimeError):
        run._run_oracle(results)


@pytest.mark.parametrize("bad", ["missing_kwarg", "extra_kwarg", "witness_args"])
def test_stage_signature_mismatch_is_rejected_before_launch(tmp_path, monkeypatch, bad):
    run, _results, _notes, _build = _stub(tmp_path, monkeypatch)
    _required_family(run, monkeypatch)
    if bad == "missing_kwarg":
        run.cfg["oracle_kwargs"] = {}
    elif bad == "extra_kwarg":
        run.cfg["oracle_kwargs"]["unexpected"] = True
    else:
        run.assert_stub_witness = lambda: None
    launched = []
    run.start_server = lambda: launched.append("server")
    run.start_instances = lambda: launched.append("instances")
    run.orchestrate = lambda: None
    run.wait_results = lambda: ("RESULT: PASS", "RESULT: PASS")
    run.cleanup = lambda passed: None
    with pytest.raises(RuntimeError, match="arguments"):
        run.run()
    assert launched == []


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


@pytest.mark.parametrize("inst", ["a", "b"])
@pytest.mark.parametrize("has_save", [True, False])
@pytest.mark.parametrize("fault", ["missing", "wrong_hash", "malformed", "wrong_player", "conflicting"])
def test_gen1_rom_receipt_must_bind_each_instance_even_without_saves(tmp_path, monkeypatch,
                                                                 inst, has_save, fault):
    run, results, _notes, _build = _stub(tmp_path, monkeypatch)
    good = _client_line(inst)
    if not has_save:
        results[inst] = good + "\nRESULT: PASS"
    digest = hashlib.sha1(_ROM_BYTES[inst]).hexdigest()[:8]
    bad = {
        "missing": "",
        "wrong_hash": good.replace(digest, "00000000"),
        "malformed": good.replace(digest, digest + "f"),
        "wrong_player": good.replace(f"player={inst}", "player=other"),
        "conflicting": good + "\n" + good.replace(digest, "00000000"),
    }[fault]
    results[inst] = results[inst].replace(good, bad)
    with pytest.raises(RuntimeError, match=f"{inst}: client built ROM"):
        run.check_save_witness(results)


def test_gen1_rom_receipt_rejects_cartridge_bytes_changed_since_the_client_booted(tmp_path, monkeypatch):
    run, results, _notes, _build = _stub(tmp_path, monkeypatch)
    (tmp_path / "roms" / "a.gb").write_bytes(b"different cartridge")
    with pytest.raises(RuntimeError, match="a: client built ROM"):
        run.check_save_witness(results)


def test_gen1_rom_receipt_accepts_repeated_matching_builds_and_uppercase_hashes(tmp_path, monkeypatch):
    run, results, notes, _build = _stub(tmp_path, monkeypatch)
    for inst in ("a", "b"):
        prefix = hashlib.sha1(_ROM_BYTES[inst]).hexdigest()[:8]
        results[inst] = results[inst].replace(prefix, prefix.upper()) + "\n" + _client_line(inst)
    run.check_save_witness(results)
    assert [note for note in notes if note.startswith("GEN1_ROM_SHA1 ")] == [
        _rom_note(inst, hashlib.sha1(_ROM_BYTES[inst]).hexdigest()[:8].upper())
        for inst in ("a", "b")
    ]


@pytest.mark.parametrize("game", ["gen1_new", "gen1_pure", "gen1_pure_green"])
@pytest.mark.parametrize("inst", ["a", "b"])
@pytest.mark.parametrize("bad_kind", ["clean", "rand", "unknown"])
def test_matching_hash_cannot_admit_an_unpatched_receipt_kind(tmp_path, monkeypatch, game, inst, bad_kind):
    run, results, _notes, _build = _stub(tmp_path, monkeypatch)
    run.game, run.gcfg = game, dict(duo.GAMES[game])
    if game != "gen1_new":
        for side in ("a", "b"):
            results[side] = results[side].replace("pack=gen1_rby kind=named",
                                                "pack=gen1_purergb kind=overlay")
    allowed = "named" if game == "gen1_new" else "overlay"
    results[inst] = results[inst].replace(f"kind={allowed}", f"kind={bad_kind}")
    with pytest.raises(RuntimeError, match="companion|kind"):
        run.check_save_witness(results)


@pytest.mark.parametrize("game", ["gen1_pure", "gen1_pure_green"])
@pytest.mark.parametrize("kind", ["overlay", "rand_overlay"])
def test_pure_companion_kinds_bind_successfully(tmp_path, monkeypatch, game, kind):
    run, results, _notes, _build = _stub(tmp_path, monkeypatch)
    run.game, run.gcfg = game, dict(duo.GAMES[game])
    for inst in ("a", "b"):
        results[inst] = results[inst].replace("pack=gen1_rby kind=named",
                                            f"pack=gen1_purergb kind={kind}")
    run.check_save_witness(results)
