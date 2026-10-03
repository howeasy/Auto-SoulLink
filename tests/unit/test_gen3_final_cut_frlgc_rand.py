"""--title frlgc-rand: the small opt-in plan that runs the randomized-COMPANION rows (admission with its pair / wrong_rom /
rules_changed / equivalent_pair / mixed_kind / clean_refused legs, link, nearby-trainer panel) on FR+LG and Emerald, plus the clean
zip-boot REFUSAL proofs. frlgc keeps its owner-agreed 65 rows. Pure Python: no emulator, no real subprocess."""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import e2e_duo  # noqa: E402
import gen3_final_cut as fc  # noqa: E402
import gen3_probe_receipt as receipts  # noqa: E402

LANE, MASTER, CUT = "L:/lane", "L:/master", "c" * 40
P = fc.RAND_ROW_PREFIX

EXPECTED = [P + x for x in (
    "source_firered", "source_leafgreen", "source_emerald",
    "admit_randomized_frlg", "admit_randomized_emerald",
    "link_gen3_rand_frlg", "link_gen3_rand_emerald",
    "trainer_panel_gen3_rand_frlg", "trainer_panel_gen3_rand_emerald",
    "zip_build", "zip_check", "zip_boot_firered_refused", "zip_boot_emerald_refused")]
DUO = EXPECTED[3:9]
ALLOWED = {"FireRed_allowed.gba", "LeafGreen_allowed.gba", "FireRed_widest.gba",
           "Emerald_allowed.gba", "Emerald_allowed_b.gba", "Emerald_widest.gba"}


ZIP = f"{LANE}/dist/SLink-player-g4-{CUT[:8]}.zip"


def _git(*args):
    return subprocess.run(["git", "-C", fc.REPO, *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def rand_dir(tmp_path, monkeypatch):
    """A SLINK_GEN3_RAND_ROMS directory holding every ROM file the rows need (placeholder bytes)."""
    for name in ALLOWED:
        (tmp_path / name).write_bytes(name.encode())
    monkeypatch.setenv("SLINK_GEN3_RAND_ROMS", str(tmp_path))
    return tmp_path


def _plan():
    return {r.id: r for r in fc.build_plan_frlgc_rand(CUT, LANE, MASTER)}


# ---- the plan's shape ----

def test_the_plan_is_exactly_these_thirteen_rows(rand_dir):
    ids = [r.id for r in fc.build_plan_frlgc_rand(CUT, LANE, MASTER)]
    assert ids == EXPECTED and len(ids) == 13 and len(set(ids)) == 13


def test_frlgc_keeps_its_owner_agreed_65_rows():
    assert len(fc.build_plan_frlgc(CUT, LANE, MASTER)) == 65


def test_rows_never_share_an_id_with_another_plan_and_always_run(rand_dir):
    rows = fc.build_plan_frlgc_rand(CUT, LANE, MASTER)
    other = {r.id for plan in (fc.build_plan, fc.build_plan_rr, fc.build_plan_emerald, fc.build_plan_exp, fc.build_plan_frlgc)
             for r in plan(CUT, LANE, MASTER)}
    assert not {r.id for r in rows} & other
    for r in rows:
        assert r.id.startswith(P) and fc.is_companion_row(r.id) and fc.is_rand_row(r.id), r.id
        assert r.deps is None and fc.row_deps(r) is None, r.id          # never carried
        assert fc.build_kind(r.id) is None and fc.estimate_twin(r.id) == r.id
        assert r.cwd == LANE and r.est and r.est > 0, r.id               # priced by the plan's own evidence
        assert fc.row_inputs(r, LANE), r.id                              # every receipt names what it used (the zip rows: the zip)


def test_the_duo_rows_are_the_randomized_companion_scenarios(rand_dir):
    rows = _plan()
    seen = set()
    for rid in DUO:
        argv = rows[rid].argv
        scenario, game = argv[argv.index("--scenario") + 1], argv[argv.index("--game") + 1]
        assert e2e_duo.SCENARIOS[scenario]["gen3_rand"] is True and e2e_duo.scenario_applies(scenario, game), rid
        assert "--gen3-companion" not in argv                            # the rand cartridges carry the companion themselves
        assert argv[argv.index("--lane") + 1] == fc.RAND_LANE_ID
        assert rows[rid].env == {"SLINK_GEN3_RAND_ROMS": str(rand_dir)}
        seen.add((scenario, game))
    assert seen == {("admit_randomized_frlg", "gen3_frlg"), ("admit_randomized_emerald", "gen3_emerald"),
                    ("link_gen3_rand", "gen3_frlg"), ("link_gen3_rand", "gen3_emerald"),
                    ("trainer_panel_gen3_rand", "gen3_frlg"), ("trainer_panel_gen3_rand", "gen3_emerald")}
    # no clean / randomized-clean cartridge anywhere: every admission-leg source is a companion, the clean one is the refusal leg
    for rows_by_phase in e2e_duo.GEN3_RAND_PHASES.values():
        assert not any(src.startswith("clean") for src, _kind in rows_by_phase.values())
    legs = {"pair", "wrong_rom", "rules_changed", "equivalent_pair", "mixed_kind"}
    assert legs <= set(e2e_duo.GEN3_RAND_PHASES)


def test_the_zip_boot_rows_are_the_clean_refusal_proofs(rand_dir):
    rows = _plan()
    for title in ("firered", "emerald"):
        row = rows[P + f"zip_boot_{title}_refused"]
        assert row.argv[-2:] == ["--title", "emerald"] if title == "emerald" else "--title" not in row.argv
        assert fc.row_inputs(row, LANE) == {f"rom:{title}": os.path.join(LANE, fc.STAGED[title]),   # the CLEAN dump it refuses
                                            "zip:dist": ZIP}                                       # and the zip it boots
    assert [r.id for r in fc.build_plan_frlgc_rand(CUT, LANE, MASTER) if "zip" in r.id] == EXPECTED[9:]


def test_the_clean_plans_stay_refused_and_this_one_is_not():
    assert fc.clean_plan_refusal("frlgc-rand") is None
    assert set(fc.CLEAN_PLAN_TITLES) == {"frlg", "emerald"}


# ---- the randomized ROMs: BLOCKED, never skipped ----

def test_the_rom_files_each_row_needs_come_from_the_harness_tables(rand_dir):
    assert fc.rand_roms_for("admit_randomized_frlg", "gen3_frlg") == (
        "FireRed_allowed.gba", "LeafGreen_allowed.gba", "FireRed_widest.gba")
    assert fc.rand_roms_for("admit_randomized_emerald", "gen3_emerald") == (
        "Emerald_allowed.gba", "Emerald_allowed_b.gba", "Emerald_widest.gba")
    assert fc.rand_roms_for("link_gen3_rand", "gen3_frlg") == ("FireRed_allowed.gba", "LeafGreen_allowed.gba")
    assert fc.rand_roms_for("trainer_panel_gen3_rand", "gen3_emerald") == ("Emerald_allowed.gba", "Emerald_allowed_b.gba")
    assert set().union(*(r.rand_roms for r in _plan().values())) == ALLOWED


def test_a_complete_rom_directory_blocks_nothing(rand_dir):
    assert fc.rand_blockers(list(_plan().values())) == {}


def test_an_unset_rom_directory_blocks_every_randomized_row_by_name(monkeypatch):
    monkeypatch.delenv("SLINK_GEN3_RAND_ROMS", raising=False)
    rows = list(fc.build_plan_frlgc_rand(CUT, LANE, MASTER))
    blocked = fc.rand_blockers(rows)
    assert set(blocked) == set(DUO)                                      # the source and zip rows need no randomized ROM
    assert all("SLINK_GEN3_RAND_ROMS is not set" in why and why.startswith("BLOCKED") for why in blocked.values())


@pytest.mark.parametrize("gone, rows", [
    ("Emerald_widest.gba", {P + "admit_randomized_emerald"}),                  # only the admission row reads the widest ROM
    ("LeafGreen_allowed.gba", {P + "admit_randomized_frlg", P + "link_gen3_rand_frlg", P + "trainer_panel_gen3_rand_frlg"}),
    ("Emerald_allowed_b.gba", {P + "admit_randomized_emerald", P + "link_gen3_rand_emerald",
                               P + "trainer_panel_gen3_rand_emerald"}),
])
def test_an_absent_rom_blocks_exactly_the_rows_that_read_it(rand_dir, gone, rows):
    (rand_dir / gone).unlink()
    blocked = fc.rand_blockers(list(_plan().values()))
    assert set(blocked) == rows
    assert all(gone in why and "absent" in why for why in blocked.values())


def test_a_real_run_aborts_before_provisioning_when_a_rom_is_absent(rand_dir, monkeypatch, capsys):
    (rand_dir / "FireRed_widest.gba").unlink()

    def boom(*a, **k):
        raise AssertionError("provisioned or launched with a randomized ROM absent")
    for name in ("provision", "copy_inputs", "run_row", "run_once"):
        monkeypatch.setattr(fc, name, boom)
    cut = _git("rev-parse", "HEAD")
    assert fc.main(["--cut", cut, "--title", "frlgc-rand", "--lane", LANE, "--master", MASTER]) == 2
    err = capsys.readouterr().err
    assert f"{P}admit_randomized_frlg" in err and "FireRed_widest.gba" in err and "BLOCKED" in err
    # inspection still works, and shows the block
    assert fc.main(["--cut", cut, "--title", "frlgc-rand", "--lane", LANE, "--master", MASTER, "--dry-run"]) == 0
    assert f"# {P}admit_randomized_frlg: BLOCKED: randomized ROM absent" in capsys.readouterr().out


# ---- inputs binding ----

def test_inputs_name_the_clean_dump_companion_rand_rom_and_overlay_of_every_title_the_row_uses(rand_dir):
    rows = _plan()
    fr = fc.row_inputs(rows[P + "admit_randomized_frlg"], LANE)
    assert {k for k in fr if k.startswith("rom:")} == {"rom:firered", "rom:leafgreen", "rom:firered_companion",
                                                       "rom:leafgreen_companion"}
    assert {k for k in fr if k.startswith("rand:")} == {f"rand:{f}" for f in (
        "FireRed_allowed.gba", "LeafGreen_allowed.gba", "FireRed_widest.gba")}
    # exactly the files the harness stages: A's title for a / equivalent / forbidden, B's title for b
    assert {k for k in fr if k.startswith("overlay:")} == {"overlay:a_firered", "overlay:b_leafgreen",
                                                           "overlay:equivalent_firered", "overlay:forbidden_firered"}
    assert fr["rom:firered_companion"] == os.path.join(LANE, fc.COMPANION_ROMS["firered"])
    assert fr["overlay:a_firered"] == os.path.join(LANE, "patch", "build", f"rand_{fc.RAND_LANE_ID}", "a_firered.gba")
    em = fc.row_inputs(rows[P + "link_gen3_rand_emerald"], LANE)
    assert {k for k in em if k.startswith("rom:")} == {"rom:emerald", "rom:emerald_companion"}
    assert not any("firered" in k or "leafgreen" in k for k in em)
    assert set(fc.row_inputs(rows[P + "source_leafgreen"], LANE)) == {"rom:leafgreen", "rom:leafgreen_companion"}


def test_overlay_inputs_follow_the_scenario_not_the_lane_history(rand_dir):
    """link / trainer-panel rows stage only a and b; the admission rows add the equivalent and rule-changed controls. Six rows share
    one stage dir, so declaring a control a row never stages would make its inputs depend on which rows ran before it."""
    rows = _plan()
    overlays = {rid: {k for k in fc.row_inputs(rows[P + rid], LANE) if k.startswith("overlay:")}
                for rid in ("admit_randomized_frlg", "admit_randomized_emerald", "link_gen3_rand_frlg", "link_gen3_rand_emerald",
                            "trainer_panel_gen3_rand_frlg", "trainer_panel_gen3_rand_emerald")}
    assert overlays["link_gen3_rand_frlg"] == overlays["trainer_panel_gen3_rand_frlg"] == {
        "overlay:a_firered", "overlay:b_leafgreen"}
    assert overlays["link_gen3_rand_emerald"] == overlays["trainer_panel_gen3_rand_emerald"] == {
        "overlay:a_emerald", "overlay:b_emerald"}
    assert overlays["admit_randomized_emerald"] == {"overlay:a_emerald", "overlay:b_emerald", "overlay:equivalent_emerald",
                                                    "overlay:forbidden_emerald"}
    assert overlays["admit_randomized_frlg"] - overlays["link_gen3_rand_frlg"] == {
        "overlay:equivalent_firered", "overlay:forbidden_firered"}
    assert fc.rand_row_overlays("link_gen3_rand", "gen3_frlg") == ("a_firered.gba", "b_leafgreen.gba")


def test_the_zip_rows_record_the_release_zip_and_a_swapped_zip_stops_a_resume(rand_dir, tmp_path):
    lane = tmp_path / "lane"
    rows = {r.id: r for r in fc.build_plan_frlgc_rand(CUT, lane.as_posix(), MASTER)}
    zip_path = lane / "dist" / f"SLink-player-g4-{CUT[:8]}.zip"
    for rid in ("zip_build", "zip_check", "zip_boot_firered_refused", "zip_boot_emerald_refused"):
        assert fc.row_inputs(rows[P + rid], str(lane))["zip:dist"].replace("\\", "/") == zip_path.as_posix(), rid
    zip_path.parent.mkdir(parents=True)
    zip_path.write_bytes(b"the built zip")
    for rid in ("zip_build", "zip_check", "zip_boot_firered_refused", "zip_boot_emerald_refused"):
        row = rows[P + rid]
        for key, path in fc.row_inputs(row, str(lane)).items():
            if key.startswith("rom:"):
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_bytes(key.encode())
        note = "# " + fc.inputs_note(fc.hash_inputs(fc.row_inputs(row, str(lane))))
        assert fc.resume_inputs_problem(row, note, str(lane)) is None, rid
        zip_path.write_bytes(b"a swapped zip, longer")   # a different SIZE: file_digest memoises on (path, size, mtime_ns), and a same-size rewrite within the mtime tick is served the stale digest
        assert "zip:dist" in fc.resume_inputs_problem(row, note, str(lane)), rid
        zip_path.write_bytes(b"the built zip")


def test_a_changed_rand_rom_or_overlay_changes_the_recorded_hash_and_stops_a_resume(rand_dir, tmp_path):
    row = _plan()[P + "link_gen3_rand_emerald"]
    lane = tmp_path / "lane"
    for key, path in fc.row_inputs(row, str(lane)).items():
        if not key.startswith("rand:"):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            Path(path).write_bytes(key.encode())
    note = "# " + fc.inputs_note(fc.hash_inputs(fc.row_inputs(row, str(lane))))
    assert fc.resume_inputs_problem(row, note, str(lane)) is None
    (rand_dir / "Emerald_allowed.gba").write_bytes(b"another seed")                   # a different randomized ROM
    assert "rand:Emerald_allowed.gba" in fc.resume_inputs_problem(row, note, str(lane))
    (rand_dir / "Emerald_allowed.gba").write_bytes(b"Emerald_allowed.gba")
    assert fc.resume_inputs_problem(row, note, str(lane)) is None
    overlay = os.path.join(str(lane), "patch", "build", f"rand_{fc.RAND_LANE_ID}", "a_emerald.gba")
    Path(overlay).write_bytes(b"a different overlay")                                  # a different overlay hash
    assert "overlay:a_emerald" in fc.resume_inputs_problem(row, note, str(lane))


def test_a_missing_rand_rom_is_recorded_as_missing_not_dropped(monkeypatch):
    monkeypatch.delenv("SLINK_GEN3_RAND_ROMS", raising=False)
    row = next(r for r in fc.build_plan_frlgc_rand(CUT, LANE, MASTER) if r.id == P + "trainer_panel_gen3_rand_frlg")
    hashes = fc.hash_inputs(fc.row_inputs(row, LANE))
    assert hashes["rand:FireRed_allowed.gba"] == "MISSING"


# ---- the title wiring ----

def test_the_title_is_selectable_listed_and_suffixed(rand_dir, capsys):
    cut = _git("rev-parse", "HEAD")
    assert fc.main(["--cut", cut, "--title", "frlgc-rand", "--lane", LANE, "--master", MASTER, "--list"]) == 0
    assert [ln.split()[0] for ln in capsys.readouterr().out.splitlines()] == EXPECTED
    assert fc.main(["--cut", cut, "--title", "frlgc-rand", "--lane", LANE, "--master", MASTER, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert f"fc_SUMMARY_{cut[:8]}_frlgc_rand.txt" in out
    for rel in fc.COMPANION_ROMS.values():                                              # the same pinned companion inputs as frlgc
        assert rel in out.split("# provision: pinned inputs")[1].splitlines()[0]
    assert "rows=13" in out
    with pytest.raises(SystemExit):
        fc.main(["--cut", cut, "--title", "frlgc_rand", "--dry-run"])


def test_the_dry_run_prices_every_row_and_totals_serial_and_three_shards(rand_dir, capsys):
    cut = _git("rev-parse", "HEAD")
    assert fc.main(["--cut", cut, "--title", "frlgc-rand", "--lane", LANE, "--master", MASTER, "--dry-run"]) == 0
    out = capsys.readouterr().out
    for rid in EXPECTED:
        assert re.search(rf"(?m)^#\s+{rid}\s+~\d+s$", out), rid
    assert "from retained receipts" in out and "reconnect_gen3" in out                   # the evidence is named
    assert re.search(r"# serial total ~\d+s \(\d+\.\d min\)", out)                          # not a literal: receipts reprice rows
    assert re.search(r"# 3 shards ~\d+s \(\d+\.\d min\) longest", out)
    assert "no history, budget" not in out                                                # no row is unpriced


def test_the_estimates_total_and_shard(rand_dir):
    rows = list(fc.build_plan_frlgc_rand(CUT, LANE, MASTER))
    assert sum(r.est for r in rows) == 475
    lines = fc.rand_estimate_lines(rows, {r.id: None for r in rows})
    assert any(line.startswith("# serial total ~475s (7.9 min)") for line in lines)     # the plan's own estimates, no history
    shards = fc.shard_rows(rows, 3, {r.id: r.est for r in rows})
    assert sum(len(s) for s in shards) == 13
    zips = {k for k, s in enumerate(shards) for r in s if "zip" in r.id}
    assert len(zips) == 1                                                                 # the zip chain is atomic
    assert max(sum(r.est for r in s) for s in shards) < sum(r.est for r in rows) / 2     # sharding really shortens it


# ---- companion evidence ----

PINS = {f"{t}_companion": hashlib.sha1(t.encode()).hexdigest() for t in ("firered", "leafgreen", "emerald")}


def _staged_bytes(side, title):
    return f"{side}-{title}-overlay".encode()


def _input(side, title, pin=None, overlay=True, sha=None):
    sha = sha or hashlib.sha1(_staged_bytes(side, title)).hexdigest()
    return (f"[duo] RAND_INPUT {side} SYNTH=clean-derived-save title={title} "
            f"{'companion=overlay ' if overlay else ''}companion_pin={(pin or PINS[title + '_companion'])[:12]} sha1={sha}")


def _stage_overlays(lane, a="firered", b="leafgreen"):
    stage = Path(lane) / "patch" / "build" / f"rand_{fc.RAND_LANE_ID}"
    stage.mkdir(parents=True, exist_ok=True)
    for side, title in (("a", a), ("b", b)):
        (stage / f"{side}_{title}.gba").write_bytes(_staged_bytes(side, title))


def _out(a="firered", b="leafgreen", admit=True, **kw):
    lines = [_input("a", a, **kw), _input("b", b)]
    if admit:
        lines.append(f"[duo] RAND_REFUSED phase=clean_refused side=b title={b} at=launch")
    return "\n".join(lines + ["RESULT: PASS"])


def test_a_randomized_row_needs_the_overlay_on_the_pinned_companion_for_both_sides():
    p = fc.companion_attempt_problem
    assert p(P + "admit_randomized_frlg", _out(), PINS) is None
    assert p(P + "link_gen3_rand_frlg", _out(admit=False), PINS) is None
    assert p(P + "admit_randomized_emerald", _out("emerald", "emerald"), PINS) is None
    assert p(P + "admit_randomized_frlg", "RESULT: PASS", PINS)                           # no proof at all
    assert p(P + "admit_randomized_frlg", _out(overlay=False), PINS)                       # a randomized-CLEAN cartridge
    assert p(P + "admit_randomized_frlg", _out(pin="0" * 40), PINS)                        # an overlay on another build
    assert p(P + "admit_randomized_frlg", _out("leafgreen", "firered"), PINS)              # wrong orientation / titles
    assert p(P + "admit_randomized_frlg", _out(admit=False), PINS)                         # the clean_refused leg is missing
    assert p(P + "link_gen3_rand_frlg", _out(admit=False), {})                             # no pins: fail closed
    assert p(P + "source_firered", "RESULT: PASS", PINS) is None                           # rows with no client owe none
    assert p(P + "admit_randomized_frlg", _out().replace("sha1=", "sha1=zz"), PINS)        # a malformed sha1 is no attestation


def test_the_note_must_be_the_overlay_rom_actually_staged_in_the_lane(tmp_path):
    """The evidence is the harness's self-attestation (a randomized cartridge cannot print `(companion by hash)`); with a lane the
    attested sha1 must equal the sha1 of the overlay ROM staged there."""
    p = fc.companion_attempt_problem
    _stage_overlays(tmp_path)
    assert p(P + "admit_randomized_frlg", _out(), PINS, str(tmp_path)) is None
    assert "not the overlay ROM staged" in p(P + "admit_randomized_frlg", _out(), PINS, str(tmp_path / "elsewhere"))
    (tmp_path / "patch" / "build" / f"rand_{fc.RAND_LANE_ID}" / "b_leafgreen.gba").write_bytes(b"a different cartridge")
    why = p(P + "admit_randomized_frlg", _out(), PINS, str(tmp_path))
    assert why and "RAND_INPUT b" in why and "RAND_INPUT a" not in why
    assert p(P + "admit_randomized_frlg", _out(sha="0" * 40), PINS, str(tmp_path))      # an attested hash that was never staged


def test_a_clean_zip_boot_row_needs_the_clients_refusal():
    p = fc.companion_attempt_problem
    ok = "RESULT: PASS the extracted zip's client REFUSED the clean firered (needs the SLink companion patch); it never connected"
    assert p(P + "zip_boot_firered_refused", ok, PINS) is None
    assert p(P + "zip_boot_firered_refused", ok.replace("firered", "emerald"), PINS)
    assert p(P + "zip_boot_emerald_refused", ok, PINS)
    assert p(P + "zip_boot_firered_refused", "RESULT: PASS the extracted zip booted firered on the new client", PINS)


def test_fc_check_and_run_row_enforce_the_overlay_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(fc, "gen3_companion_pins", lambda tree, strict=False: PINS)
    monkeypatch.setattr(fc, "gen3_companion_pins_at", lambda cut: PINS)
    row = P + "admit_randomized_frlg"
    name = f"fc_{row}_{CUT[:8]}.txt"

    def receipt(body):
        attempt = {"load": "cpu=1%", "start_utc": "2026-10-03T12:00:00Z", "end_utc": "2026-10-03T12:01:00Z", "rc": 0,
                   "tracked_before": True, "tracked_after": True, "classification": "pass", "output": body}
        return receipts.run_receipt_text(row=row, item="FRLGCR-RAND", cut=CUT, lane="lane", command="c", cwd=".", env={},
                                         attempts=[attempt], verdict="PASS", note="")
    assert fc.fc_check(name, receipt(_out()), str(tmp_path))[1]
    hdr, ok, why = fc.fc_check(name, receipt("RESULT: PASS"), str(tmp_path))
    assert not ok and "companion" in why
    assert not fc.fc_check(name, receipt(_out(overlay=False)), str(tmp_path))[1]
    monkeypatch.setattr(fc, "PROBES", str(tmp_path))
    monkeypatch.setattr(fc, "tracked_clean", lambda tree: True)
    monkeypatch.setattr(fc, "rewind_violations", lambda *a: [])
    monkeypatch.setattr(fc, "head", lambda tree: CUT)
    _stage_overlays(tmp_path)                                                              # run_row checks the staged ROMs too
    for body, want in ((_out(), "PASS"), ("RESULT: PASS", "FAIL"), (_out(sha="1" * 40), "FAIL")):
        monkeypatch.setattr(fc, "run_once", lambda r, deadline, body=body: (0, body, False, False))
        verdict, _n, _clean = fc.run_row(fc.Row(row, "FRLGCR-RAND", ["x"], str(tmp_path), 10), CUT, str(tmp_path), None)
        assert verdict.startswith(want), (body, verdict)


def test_a_companion_rand_row_is_never_carried_or_cached(rand_dir):
    row = _plan()[P + "link_gen3_rand_frlg"]
    hdr_text = receipts.run_receipt_text(row=row.id, item="x", cut=CUT, lane="l", command="c", cwd=".", env={}, attempts=[],
                                         verdict=f"CARRIED from fc_{row.id}_{'d' * 8}.txt @{'d' * 40}", note="")
    hdr, ok, why = fc.fc_check(f"fc_{row.id}_{CUT[:8]}.txt", hdr_text, "x")
    assert not ok and "exact cut" in why


def test_chain_of_keeps_the_zip_rows_together(rand_dir):
    zips = {fc.chain_of(r.id) for r in fc.build_plan_frlgc_rand(CUT, LANE, MASTER) if "zip" in r.id}
    assert zips == {"zip"}


# ---- stage-companions ----

def test_stage_companions_stages_only_the_pinned_composition_and_never_overwrites(tmp_path, monkeypatch, capsys):
    clean = {t: t.encode() * 4 for t in fc.GEN3_COMPANION_TITLES}
    patched = {t: (t + "-patched").encode() for t in fc.GEN3_COMPANION_TITLES}
    pins = {**{t: hashlib.sha1(clean[t]).hexdigest() for t in clean},
            **{f"{t}_companion": hashlib.sha1(patched[t]).hexdigest() for t in clean}}
    monkeypatch.setattr(fc, "rom_pins", lambda tree, **kw: pins)
    import tools.gen3_companions as gc
    monkeypatch.setattr(gc, "published", lambda title, dump, root=None: (patched[title], {}) if dump == clean[title] else None)
    for t in clean:
        (tmp_path / fc.ROOT_DUMPS[t]).write_bytes(clean[t])
    assert fc.stage_companions(str(tmp_path)) == 0
    for t in clean:
        assert (tmp_path / fc.COMPANION_ROMS[t]).read_bytes() == patched[t]
    assert fc.stage_companions(str(tmp_path)) == 0                                       # idempotent
    (tmp_path / fc.COMPANION_ROMS["firered"]).write_bytes(b"something else")
    capsys.readouterr()
    assert fc.stage_companions(str(tmp_path)) == 1 and "exists and differs" in capsys.readouterr().out
    assert (tmp_path / fc.COMPANION_ROMS["firered"]).read_bytes() == b"something else"
    (tmp_path / fc.ROOT_DUMPS["leafgreen"]).write_bytes(b"not the pinned dump")
    assert fc.stage_companions(str(tmp_path), ("leafgreen",)) == 1
    assert "is not the pinned clean dump" in capsys.readouterr().out
    monkeypatch.setattr(gc, "published", lambda title, dump, root=None: (b"wrong build", {}))
    (tmp_path / fc.ROOT_DUMPS["leafgreen"]).write_bytes(clean["leafgreen"])
    assert fc.stage_companions(str(tmp_path), ("leafgreen",)) == 1
    assert "not the leafgreen companion pin" in capsys.readouterr().out
    assert fc.stage_companions(str(tmp_path / "empty"), ("emerald",)) == 1               # no dump to compose from


def test_stage_companions_writes_a_temp_file_and_replaces_atomically(tmp_path, monkeypatch):
    clean, patched = b"clean-dump" * 4, b"patched-build"
    pins = {"firered": hashlib.sha1(clean).hexdigest(), "firered_companion": hashlib.sha1(patched).hexdigest()}
    monkeypatch.setattr(fc, "rom_pins", lambda tree, **kw: pins)
    import tools.gen3_companions as gc
    monkeypatch.setattr(gc, "published", lambda title, dump, root=None: (patched, {}))
    (tmp_path / fc.ROOT_DUMPS["firered"]).write_bytes(clean)
    dst = tmp_path / fc.COMPANION_ROMS["firered"]
    real_replace, seen = os.replace, []

    def failing_replace(src, dest):
        seen.append((src, dest, os.path.exists(src), os.path.exists(dest)))
        raise OSError("replace refused")
    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError, match="replace refused"):
        fc.stage_companions(str(tmp_path), ("firered",))
    (src, dest, src_existed, dest_existed), = seen
    assert os.path.normpath(dest) == os.path.normpath(str(dst)) and os.path.normpath(src) != os.path.normpath(dest)
    assert os.path.dirname(src) == os.path.dirname(dest) and src_existed and not dest_existed   # temp next to it; ROM absent until the swap
    assert not dst.exists() and not any(tmp_path.joinpath("patch", "build").glob("*.tmp*"))     # no partial ROM, no stray temp
    monkeypatch.setattr(os, "replace", real_replace)
    assert fc.stage_companions(str(tmp_path), ("firered",)) == 0 and dst.read_bytes() == patched
    reads = []
    real_read = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: reads.append(str(self)) or real_read(self))
    assert fc.stage_companions(str(tmp_path), ("firered",)) == 0
    assert sum(1 for r in reads if os.path.normpath(r) == os.path.normpath(str(dst))) == 1       # ONE read of the destination


# ---- the harness really emits what the evidence check demands (needs the real, uncommitted inputs: a named skip when absent) ----

@pytest.mark.parametrize("scenario, game, row, titles", [
    ("admit_randomized_frlg", "gen3_frlg", "admit_randomized_frlg", ("firered", "leafgreen")),
    ("admit_randomized_emerald", "gen3_emerald", "admit_randomized_emerald", ("emerald", "emerald"))])
# (link / trainer-panel rows read the fixture profiles through the live REPO, so they cannot run under a scratch REPO; they share
# this exact prepare code and RAND_INPUT note, and were prepared for real in the lane-less feasibility run)
def test_the_prepare_step_emits_the_lines_the_evidence_check_demands(tmp_path, monkeypatch, scenario, game, row, titles):
    from types import SimpleNamespace

    from tools import gen3_final_cut as cut
    from tools.gen3_companions import published

    rand_root = os.environ.get("SLINK_GEN3_RAND_ROMS")
    roms_root = os.environ.get("SLINK_GEN3_ROMS", cut.main_checkout())
    if not rand_root or not all(os.path.isfile(os.path.join(rand_root, f)) for f in fc.rand_roms_for(scenario, game)):
        pytest.skip("SLINK_GEN3_RAND_ROMS does not hold the randomized ROMs this row reads")
    dumps = {t: os.path.join(roms_root, fc.ROOT_DUMPS[t]) for t in set(titles)}
    if not all(os.path.isfile(p) for p in dumps.values()):
        pytest.skip(f"clean dumps absent from {roms_root}")
    pins = cut.rom_pins(fc.REPO, require_companions=True)
    for t, path in dumps.items():
        staged = tmp_path / cut.STAGED[t]
        staged.parent.mkdir(parents=True, exist_ok=True)
        data = open(path, "rb").read()
        assert hashlib.sha1(data).hexdigest() == pins[t], f"present-but-wrong clean {t}"
        staged.write_bytes(data)
        companion = tmp_path / cut.COMPANION_ROMS[t]
        companion.write_bytes(published(t, data)[0])
    monkeypatch.setattr(e2e_duo, "REPO", str(tmp_path))
    monkeypatch.setattr(e2e_duo, "BUILD", str(tmp_path / "patch" / "build"))
    monkeypatch.setattr(cut, "rom_pins", lambda *_a, **_k: pins)
    monkeypatch.delenv("SLINK_STATE_DIR", raising=False)
    run = e2e_duo.DuoRun(scenario, SimpleNamespace(game=game, lane=fc.RAND_LANE_ID))
    notes = []
    run._pydec_note = notes.append
    run._prepare_gen3_rand()
    out = "\n".join(f"[duo] {n}" for n in notes)
    if scenario in e2e_duo.GEN3_RAND_ADMISSION:
        out += f"\n[duo] RAND_REFUSED phase=clean_refused side=b title={titles[1]} at=launch"
    assert fc.rand_attempt_problem(P + row, out, pins) is None, out
    # the cartridges that boot are the randomized ROMs WITH the overlay: the SLNK signature is intact in each
    for side in "ab":
        launched = (tmp_path / run._rand_inputs[side]["rom"]).read_bytes()
        assert b"SLNK" in launched


def test_a_real_run_provisions_with_the_strict_companion_pins_and_the_companion_inputs(rand_dir, monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(fc, "PROBES", str(tmp_path))
    monkeypatch.setattr(fc, "provision", lambda tree, rev, root: rev)
    monkeypatch.setattr(fc, "copy_inputs", lambda tree, root, **kw: seen.update(kw))
    real_pins = fc.rom_pins
    monkeypatch.setattr(fc, "rom_pins", lambda tree, **kw: seen.setdefault("pin_kw", kw) and real_pins(fc.REPO, **kw))
    ran = []
    monkeypatch.setattr(fc, "run_row", lambda row, cut, lane, deadline: (ran.append(row.id), ("PASS", 1, True))[1])
    cut = _git("rev-parse", "HEAD")
    assert fc.main(["--cut", cut, "--title", "frlgc-rand", "--lane", LANE, "--master", MASTER, "--resume"]) == 0
    assert ran == EXPECTED
    assert seen["pin_kw"] == {"require_companions": True}                                  # a missing companion pin aborts loudly
    assert set(fc.COMPANION_PINNED_INPUTS) <= set(seen["extra_pinned"])                    # the staged companions are provisioned
    assert (tmp_path / f"fc_SUMMARY_{cut[:8]}_frlgc_rand.txt").is_file()


# ---- --merge-summary is not a way around the randomized-ROM block ----

def _merge_env(monkeypatch, tmp_path, rand_dir):
    monkeypatch.setattr(fc, "PROBES", str(tmp_path))
    monkeypatch.setattr(fc, "gen3_companion_pins", lambda tree, strict=False: PINS)
    monkeypatch.setattr(fc, "gen3_companion_pins_at", lambda cut: PINS)
    lane = tmp_path / "lane"
    _stage_overlays(lane)
    row = _plan()[P + "link_gen3_rand_frlg"]
    attempt = {"load": "cpu=1%", "start_utc": "2026-10-03T12:00:00Z", "end_utc": "2026-10-03T12:01:00Z", "rc": 0,
               "tracked_before": True, "tracked_after": True, "classification": "pass", "output": _out(admit=False)}
    note = fc.inputs_note(fc.hash_inputs(fc.row_inputs(row, str(lane))))
    text = receipts.run_receipt_text(row=row.id, item="FRLGCR-RAND", cut=CUT, lane=str(lane), command="c", cwd=".", env={},
                                     attempts=[attempt], verdict="PASS", note=note)
    (tmp_path / f"fc_{row.id}_{CUT[:8]}.txt").write_text(text, encoding="utf-8")
    return row


def _merge_verdict(row, capsys):
    rc = fc.merge_summary(CUT, [row], "_frlgc_rand")
    return rc, capsys.readouterr().out


def test_a_merge_passes_while_the_randomized_roms_are_what_the_receipt_recorded(rand_dir, tmp_path, monkeypatch, capsys):
    row = _merge_env(monkeypatch, tmp_path, rand_dir)
    rc, out = _merge_verdict(row, capsys)
    assert rc == 0 and "OVERALL: PASS (1/1 rows)" in out


def test_a_merge_is_not_a_pass_when_the_randomized_roms_are_gone(rand_dir, tmp_path, monkeypatch, capsys):
    row = _merge_env(monkeypatch, tmp_path, rand_dir)
    (rand_dir / "LeafGreen_allowed.gba").unlink()
    rc, out = _merge_verdict(row, capsys)
    assert rc == 1 and "OVERALL: FAIL" in out and "rand:LeafGreen_allowed.gba" in out and "absent or changed" in out


def test_a_merge_is_not_a_pass_when_the_randomized_roms_are_repointed(rand_dir, tmp_path, monkeypatch, capsys):
    row = _merge_env(monkeypatch, tmp_path, rand_dir)
    other = tmp_path / "other_roms"
    other.mkdir()
    for name in ALLOWED:
        (other / name).write_bytes(b"different bytes: " + name.encode())
    monkeypatch.setenv("SLINK_GEN3_RAND_ROMS", str(other))
    rc, out = _merge_verdict(row, capsys)
    assert rc == 1 and "OVERALL: FAIL" in out and "rand:FireRed_allowed.gba" in out


def test_the_merge_check_is_scoped_to_the_randomized_rows(tmp_path, monkeypatch, capsys):
    """Another title's merge is unchanged: no frlgcr_ row, no randomized-ROM comparison."""
    monkeypatch.setattr(fc, "PROBES", str(tmp_path))
    called = []
    monkeypatch.setattr(fc, "rand_rom_inputs_problem", lambda *a: called.append(a))
    row = next(r for r in fc.build_plan_frlgc(CUT, LANE, MASTER) if r.id.startswith(fc.COMPANION_ROW_PREFIX + "source_"))
    attempt = {"load": "cpu=1%", "start_utc": "2026-10-03T12:00:00Z", "end_utc": "2026-10-03T12:01:00Z", "rc": 0,
               "tracked_before": True, "tracked_after": True, "classification": "pass", "output": "RESULT: PASS"}
    monkeypatch.setattr(fc, "gen3_companion_pins", lambda tree, strict=False: PINS)
    monkeypatch.setattr(fc, "gen3_companion_pins_at", lambda cut: PINS)
    text = receipts.run_receipt_text(row=row.id, item="x", cut=CUT, lane="l", command="c", cwd=".", env={}, attempts=[attempt],
                                     verdict="PASS", note="")
    (tmp_path / f"fc_{row.id}_{CUT[:8]}.txt").write_text(text, encoding="utf-8")
    assert fc.merge_summary(CUT, [row], "_frlgc") == 0 and called == []


# ---- the shared ROM-unchanged guard ----

def _guard_run(tmp_path, scenario):
    run = object.__new__(e2e_duo.DuoRun)
    rom = tmp_path / "patch" / "build" / "a_firered.gba"
    rom.parent.mkdir(parents=True, exist_ok=True)
    rom.write_bytes(b"prepared")
    run.scenario = scenario
    run._rand_inputs = {"a": {"rom": "patch/build/a_firered.gba"}}
    run._rand_facts = {"a": {"sha1": hashlib.sha1(b"prepared").hexdigest()}}
    run._live_complete = {scenario: True}
    run._rand_evidence = {"pair": {"status": {}, "hellos": {}}}
    return run, rom


@pytest.mark.parametrize("scenario, orchestrate", [
    ("admit_randomized_frlg", "orchestrate_admit_randomized_frlg"),
    ("link_gen3_rand", "orchestrate_link_gen3_rand"),
    ("trainer_panel_gen3_rand", "orchestrate_trainer_panel_gen3_rand")])
def test_each_randomized_orchestration_stops_on_a_mid_attempt_rom_rewrite(tmp_path, monkeypatch, scenario, orchestrate):
    monkeypatch.setattr(e2e_duo, "REPO", str(tmp_path))
    run, rom = _guard_run(tmp_path, scenario)
    run.game = "gen3_frlg"
    run._gen3_prelude = lambda *a, **k: None
    run.go = lambda *a, **k: None
    run.assert_link_new = lambda *a, **k: None
    run._gen3_title = lambda inst: "firered"
    monkeypatch.setattr(e2e_duo, "gen3_rand_retail", lambda title: {})
    monkeypatch.setattr(e2e_duo, "gen3_rand_panel_problems", lambda *a, **k: [])

    def observe(phase):
        rom.write_bytes(b"rewritten mid attempt")                    # the next row's prepare step reusing the shared stage dir
        return {"status": {}, "hellos": {}}
    run._observe_gen3_rand_admission = observe
    with pytest.raises(RuntimeError, match="a: ROM file changed during the attempt"):
        getattr(run, orchestrate)()
    rom.write_bytes(b"prepared")
    run._observe_gen3_rand_admission = lambda phase: {"status": {}, "hellos": {}}
    getattr(run, orchestrate)()                                      # untouched: the guard is silent


@pytest.mark.parametrize("scenario", ["admit_randomized_frlg", "link_gen3_rand", "trainer_panel_gen3_rand"])
def test_the_shared_verdict_check_also_catches_a_rewrite(tmp_path, monkeypatch, scenario):
    monkeypatch.setattr(e2e_duo, "REPO", str(tmp_path))
    run, rom = _guard_run(tmp_path, scenario)
    monkeypatch.setattr(e2e_duo, "gen3_rand_admission_problems", lambda *a, **k: [])
    run._check_gen3_rand_pair()
    rom.write_bytes(b"rewritten")
    with pytest.raises(RuntimeError, match="ROM file changed during the attempt"):
        run._check_gen3_rand_pair()


def test_the_cross_plan_minute_format_is_untouched():
    assert fc._mins(90) == "2m" and fc._mins(30) == "0m" and fc._mins(3600) == "60m"
