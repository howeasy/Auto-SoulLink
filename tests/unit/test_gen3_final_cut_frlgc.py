"""--title frlgc: the PATCHED (companion) FR/LG/Emerald final-cut plan (owner decision: re-run the cut on the companion ROMs,
adding the clause / ball-gate / shiny rows, as ONE cut). Opt-in beside frlg/rr/emerald/exp; their plans are not touched.
Pure Python: no emulator, no real subprocess (git against the repo only)."""
import hashlib
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import e2e_duo  # noqa: E402
import gen3_final_cut as fc  # noqa: E402
import gen3_probe_receipt as receipts  # noqa: E402

LANE, MASTER, CUT = "L:/lane", "L:/master", "c" * 40
C = fc.companion_row_id

SOURCE = [C("source_firered"), C("source_leafgreen"), C("source_emerald")]
BOOT = [C(f"bootcheck_{t}_party_{s}") for t in ("firered", "leafgreen") for s in ("town", "town_b", "battle", "battle_b")] + \
    [C(f"bootcheck_emerald_{s}") for s in ("town", "town_b", "battle", "battle_b")]
DUO_FRLG = [C(x) for x in (
    "faint_cmd_gen3_fr_as_a", "link_gen3_fr_as_a", "boxsync_gen3_fr_as_a", "reconnect_gen3_fr_as_a", "deadzone_gen3_fr_as_a",
    "whiteout_gen3_fr_as_a", "whiteout_gen3_lg_as_a", "center_controls_gen3_fr_as_a", "center_controls_gen3_lg_as_a",
    "linked_faint_active_gen3_fr_as_a", "linked_faint_active_gen3_lg_as_a", "active_end_gen3_fr_as_a", "active_end_gen3_lg_as_a",
    "linked_faint_active_whiteout_gen3_fr_as_a", "linked_faint_active_whiteout_gen3_lg_as_a",
    "linked_faint_active_trainer_gen3_fr_as_a", "linked_faint_active_trainer_gen3_lg_as_a",
    "save_then_write_gen3_fr_as_a", "save_then_write_gen3_lg_as_a")]
DUO_EM = [C(f"{s}_gen3_em_as_a") for s in ("faint_cmd", "reconnect", "deadzone", "link", "boxsync", "linked_faint_active", "whiteout")]
RULES = [C(f"{s}_gen3_{o}_as_a") for s in ("species_clause", "gender_clause", "type_clause", "ball_gate", "shiny_bonus", "species_family")
         for o in ("fr", "lg", "em")]
ZIP = [C("zip_build"), C("zip_check"), C("zip_boot_firered"), C("zip_boot_leafgreen"), C("zip_boot_emerald")]
FRLGC_EXPECTED_ROWS = SOURCE + BOOT + DUO_FRLG + DUO_EM + RULES + ZIP + [C("release_gate_quick")]


def _git(*args):
    return subprocess.run(["git", "-C", fc.REPO, *args], check=True, capture_output=True, text=True).stdout.strip()


def test_the_frlgc_plan_is_exactly_the_expected_rows():
    ids = [r.id for r in fc.build_plan_frlgc(CUT, LANE, MASTER)]
    assert ids == FRLGC_EXPECTED_ROWS and len(ids) == 65 and len(set(ids)) == 65


def test_frlgc_rows_never_share_an_id_with_another_plan_and_always_run():
    rows = fc.build_plan_frlgc(CUT, LANE, MASTER)
    other = {r.id for plan in (fc.build_plan, fc.build_plan_rr, fc.build_plan_emerald, fc.build_plan_exp)
             for r in plan(CUT, LANE, MASTER)}
    assert not {r.id for r in rows} & other
    for r in rows:
        assert fc.is_companion_row(r.id) and r.deps is None and fc.row_deps(r) is None, r.id
        assert r.cwd == LANE, r.id                       # even the helpers run the frozen lane's own code
        assert fc.row_inputs(r, LANE), r.id               # every receipt names the companion hash it ran


def test_every_clean_duo_row_of_the_frlg_and_emerald_plans_has_a_companion_twin():
    clean = [r.id for r in fc.build_plan(CUT, LANE, MASTER) + fc.build_plan_emerald(CUT, LANE, MASTER)
             if r.id.endswith(("_fr_as_a", "_lg_as_a", "_em_as_a"))]
    assert len(clean) == 19 + 7
    assert [fc.companion_row_id(i) for i in clean] == DUO_FRLG + DUO_EM


def test_companion_duo_rows_run_the_same_scenario_and_game_with_the_flag():
    rows = {r.id: r for r in fc.build_plan_frlgc(CUT, LANE, MASTER)}
    game = {"fr": "gen3_frlg", "lg": "gen3_lgfr", "em": "gen3_emerald"}
    for rid in DUO_FRLG + DUO_EM + RULES:
        scenario, orient = rid[len("frlgc_"):].rsplit("_as_a_companion")[0].rsplit("_", 1)[0], rid.split("_as_a_companion")[0][-2:]
        argv = rows[rid].argv
        assert argv[1:] == ["tools/e2e_duo.py", "--game", game[orient], "--scenario", scenario, "--gen3-companion"], rid
        assert e2e_duo.scenario_applies(scenario, game[orient]) and e2e_duo.skip_reason(scenario, game[orient]) is None, rid
        assert rows[rid].budget >= e2e_duo.SCENARIOS[scenario]["timeout"], rid


def test_the_new_rule_rows_boot_fixtures_that_exist():
    game = {"fr": "gen3_frlg", "lg": "gen3_lgfr", "em": "gen3_emerald"}
    for rid in RULES:
        scenario = rid[len("frlgc_"):].split("_as_a_companion")[0][:-3]
        g = game[rid.split("_as_a_companion")[0][-2:]]
        target = e2e_duo.scenario_target(e2e_duo.SCENARIOS[scenario], g)
        for inst in ("a", "b"):
            stem = e2e_duo.GAMES[g]["sides"][inst][1].format(target=target[inst] if isinstance(target, dict) else target)
            assert os.path.isfile(os.path.join(e2e_duo.GEN3_FIXTURES, stem + ".sav")), (rid, stem)


def test_bootcheck_rows_boot_the_companion_rom_with_the_right_battery_name():
    rows = {r.id: r for r in fc.build_plan_frlgc(CUT, LANE, MASTER)}
    fr = rows[C("bootcheck_firered_party_town")].argv
    assert fr[fr.index("--rom") + 1] == "patch/build/slink_FireRed.gba" and "--saveram-name" not in fr   # stage_rom derives it
    lg = rows[C("bootcheck_leafgreen_party_battle_b")].argv
    assert lg[lg.index("--rom") + 1] == "patch/build/slink_LeafGreen.gba"
    em = rows[C("bootcheck_emerald_battle")].argv
    assert em[em.index("--rom") + 1] == "patch/build/slink_Emerald.gba"
    assert em[em.index("--saveram-name") + 1] == "gen3 slink Emerald.SaveRAM"          # emerald's override defaults to the clean name
    assert em[em.index("--title") + 1] == "emerald" and lg[lg.index("--title") + 1] == "leafgreen"


def test_source_rows_check_the_staged_companion_and_need_no_emulator():
    for t in ("firered", "leafgreen", "emerald"):
        row = next(r for r in fc.build_plan_frlgc(CUT, LANE, MASTER) if r.id == C(f"source_{t}"))
        assert row.argv[1:] == ["tools/gen3_final_cut.py", "companion-check", "--lane", LANE, "--title", t]
        assert not row.emulator and row.cwd == LANE


def test_zip_rows_boot_each_companion_title():
    rows = {r.id: r for r in fc.build_plan_frlgc(CUT, LANE, MASTER)}
    assert rows[C("zip_build")].argv[1] == "tools/make_release.py" and rows[C("zip_check")].argv[1] == "tools/check_release_zip.py"
    for t in ("firered", "leafgreen", "emerald"):
        argv = rows[C(f"zip_boot_{t}")].argv
        assert argv[argv.index("--title") + 1] == f"{t}_companion"
        assert argv[argv.index("--zip") + 1] == f"{LANE}/dist/SLink-player-g4-{CUT[:8]}.zip"
    assert len({r.item for r in rows.values() if "ZIP" in r.item}) == 1 and "FRLGC" in rows[C("zip_build")].item


def test_zip_boot_companion_entries_demand_the_companion_by_hash_line():
    for t, pack, saveram, fixture in (("firered", "gen3_frlg", "slink FireRed.SaveRAM", "firered_party_town.sav"),
                                      ("leafgreen", "gen3_frlg", "slink LeafGreen.SaveRAM", "leafgreen_party_town.sav"),
                                      ("emerald", "gen3_emerald", "slink Emerald.SaveRAM", "emerald_town.sav")):
        rom, launched, seed, battery, client, hello = fc.ZIP_BOOT[f"{t}_companion"]
        assert rom == fc.COMPANION_ROMS[t] and launched == os.path.basename(rom) and seed == fixture and battery == saveram
        assert rf"{pack}/{t} \(companion by hash\) player a " in client and hello == f"hello rom={t} "
        assert os.path.isfile(os.path.join(fc.REPO, "tests", "fixtures", "gen3", seed))
    assert "needs the SLink companion patch" in fc.ZIP_BOOT["firered"][4]       # the clean entries prove the refusal
    with pytest.raises(SystemExit):
        fc.main(["zip-boot", "--zip", "z", "--lane", LANE, "--title", "nope"])


def test_title_frlgc_dry_run_prints_the_plan_launches_nothing_and_names_its_own_summary(monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("a dry run launched something")
    monkeypatch.setattr(fc, "run_row", boom)
    monkeypatch.setattr(fc, "run_once", boom)
    real_popen = subprocess.Popen

    def only_git(argv, *a, **k):
        if argv[0] != "git":
            raise AssertionError(f"a dry run launched {argv}")
        return real_popen(argv, *a, **k)
    monkeypatch.setattr(subprocess, "Popen", only_git)
    cut = _git("rev-parse", "HEAD")
    assert fc.main(["--cut", cut, "--title", "frlgc", "--dry-run", "--lane", LANE, "--master", MASTER]) == 0
    out = capsys.readouterr().out
    assert [ln.split()[1] for ln in out.splitlines() if ln.startswith("[")] == FRLGC_EXPECTED_ROWS
    assert "$ python tools/e2e_duo.py --game gen3_lgfr --scenario ball_gate_gen3 --gen3-companion" in out
    assert "--title leafgreen_companion" in out
    assert out.rstrip().splitlines()[-1].endswith(f"fc_SUMMARY_{cut[:8]}_frlgc.txt")
    assert "slink_FireRed.gba" in out                                                # the provisioning lines name the pinned inputs


def test_frlgc_provisioning_pins_the_three_companion_roms():
    plan = "\n".join(fc.provision_plan(LANE, CUT, {**fc.EMERALD_PINNED_INPUTS, **fc.COMPANION_PINNED_INPUTS}))
    for rel in fc.COMPANION_ROMS.values():
        assert rel in plan
    assert fc.COMPANION_PINNED_INPUTS["patch/build/slink_Emerald.gba"] == ("emerald_companion", ["patch/build/slink_Emerald.gba"])
    for t in fc.GEN3_COMPANION_TITLES:
        assert fc.rom_pins(fc.REPO, require_companions=True)[f"{t}_companion"]


def test_title_frlgc_does_not_change_the_other_titles_default():
    assert [r.id for r in fc.build_plan("c" * 40, LANE, MASTER)][0] == "states_firered_town"
    with pytest.raises(SystemExit):
        fc.main(["--cut", "HEAD", "--title", "frlgcx", "--dry-run", "--lane", LANE, "--master", MASTER])


@pytest.mark.parametrize("n", [1, 2, 3, 5])
def test_shards_partition_the_frlgc_plan_exactly_and_keep_the_zip_chain_whole(n):
    rows = fc.build_plan_frlgc(CUT, LANE, MASTER)
    est = {r.id: r.budget for r in rows}
    shards = fc.shard_rows(rows, n, est)
    ids = [r.id for s in shards for r in s]
    assert sorted(ids) == sorted(r.id for r in rows) and len(ids) == len(set(ids)) == 65
    zipped = [k for k, s in enumerate(shards) if any(r.id in ZIP for r in s)]
    assert len(zipped) == 1 and {r.id for r in shards[zipped[0]]} >= set(ZIP)       # build -> check -> boots, together, in order
    order = [r.id for r in shards[zipped[0]] if r.id in ZIP]
    assert order == ZIP
    assert shards == fc.shard_rows(rows, n, est)                                    # deterministic


def test_a_cli_shard_runs_only_its_rows(monkeypatch, capsys):
    cut = _git("rev-parse", "HEAD")
    assert fc.main(["--cut", cut, "--title", "frlgc", "--dry-run", "--lane", LANE, "--master", MASTER, "--shard", "2/3"]) == 0
    out = capsys.readouterr().out
    live = [ln for ln in out.splitlines() if ln.startswith("[") and "[other shard]" not in ln]
    other = [ln for ln in out.splitlines() if ln.startswith("[") and "[other shard]" in ln]
    assert len(live) + len(other) == 65 and live and other


def test_companion_rows_borrow_their_clean_twins_retained_durations():
    assert fc.estimate_twin(C("whiteout_gen3_fr_as_a")) == "whiteout_gen3_fr_as_a"
    assert fc.estimate_twin(C("bootcheck_firered_party_town")) == "bootcheck_firered_party_town"
    assert fc.estimate_twin(C("zip_boot_firered")) == "zip_boot_firered"
    assert fc.estimate_twin(C("zip_build")) == "zip_build"
    assert fc.estimate_twin("whiteout_gen3_fr_as_a") == "whiteout_gen3_fr_as_a"        # a clean row is its own twin


# ---- the companion evidence a green receipt must carry ----

PINS = {f"{t}_companion": hashlib.sha1(t.encode()).hexdigest() for t in ("firered", "leafgreen", "emerald")}


def _adm(side, title, pack="gen3_frlg", kind="companion", rom=None):
    return (f"[duo] COMPANION_ADMISSION {side}: [client] [SLink-gen3] {pack}/{title} ({kind} by hash) player {side} -> "
            f"127.0.0.1:60673 (rom {rom or PINS[title + '_companion'][:8]})")


def _duo_out(a="firered", b="leafgreen", pack="gen3_frlg", **kw):
    return "\n".join([_adm("a", a, pack, **kw), _adm("b", b, pack), "RESULT: PASS"])


def test_a_companion_duo_row_needs_both_admission_proofs():
    p = fc.companion_attempt_problem
    assert p(C("link_gen3_fr_as_a"), _duo_out(), PINS) is None
    assert p(C("link_gen3_lg_as_a"), _duo_out("leafgreen", "firered"), PINS) is None
    assert p(C("link_gen3_em_as_a"), _duo_out("emerald", "emerald", "gen3_emerald"), PINS) is None
    assert p(C("link_gen3_lg_as_a"), _duo_out("firered", "leafgreen"), PINS)           # orientation swapped: A must be LG
    assert p(C("link_gen3_fr_as_a"), "RESULT: PASS", PINS)                              # no proof at all
    assert p(C("link_gen3_fr_as_a"), _duo_out(kind="clean"), PINS)                      # a clean cartridge
    assert p(C("link_gen3_fr_as_a"), _duo_out(rom="00000000"), PINS)                    # a hash that is not the pin
    assert p(C("link_gen3_fr_as_a"), _duo_out().replace("player b", "player a"), PINS)  # one side twice
    assert p(C("link_gen3_fr_as_a"), _duo_out(), {})                                    # no pins to compare with: fail closed


def test_a_companion_zip_boot_row_needs_its_clients_companion_line():
    p = fc.companion_attempt_problem
    ok = ("--- lua log ---\n[SLink-gen3] gen3_frlg/leafgreen (companion by hash) player a -> 127.0.0.1:1 (rom "
          f"{PINS['leafgreen_companion'][:8]})\nTCP connected\nRESULT: PASS")
    assert p(C("zip_boot_leafgreen"), ok, PINS) is None
    assert p(C("zip_boot_firered"), ok, PINS)                                           # another title's line
    assert p(C("zip_boot_leafgreen"), ok.replace("companion", "clean"), PINS)
    assert p(C("zip_boot_leafgreen"), "RESULT: PASS", PINS)
    assert p(C("source_firered"), "RESULT: PASS", PINS) is None                         # rows with no client owe no admission


def _receipt(row, body, verdict="PASS"):
    attempt = {"load": "cpu=1%", "start_utc": "2026-10-02T12:00:00Z", "end_utc": "2026-10-02T12:01:00Z", "rc": 0,
               "tracked_before": True, "tracked_after": True, "classification": "pass", "output": body}
    return receipts.run_receipt_text(row=row, item="FRLGC-DUO", cut=CUT, lane="lane", command="c", cwd=".", env={},
                                     attempts=[attempt], verdict=verdict, note="")


def test_fc_check_requires_the_admission_evidence_for_a_companion_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(fc, "gen3_companion_pins", lambda tree, strict=False: PINS)
    monkeypatch.setattr(fc, "gen3_companion_pins_at", lambda cut: PINS)
    row = C("link_gen3_fr_as_a")
    name = f"fc_{row}_{CUT[:8]}.txt"
    assert fc.fc_check(name, _receipt(row, _duo_out()), str(tmp_path))[1]
    hdr, ok, why = fc.fc_check(name, _receipt(row, "RESULT: PASS"), str(tmp_path))
    assert not ok and "companion" in why
    assert not fc.fc_check(name, _receipt(row, _duo_out(kind="clean")), str(tmp_path))[1]
    clean_row = "link_gen3_fr_as_a"                                                      # a clean row owes nothing new
    assert fc.fc_check(f"fc_{clean_row}_{CUT[:8]}.txt", _receipt(clean_row, "RESULT: PASS"), str(tmp_path))[1]


def test_run_row_fails_a_companion_row_whose_output_lacks_the_proof(monkeypatch, tmp_path):
    monkeypatch.setattr(fc, "PROBES", str(tmp_path))
    monkeypatch.setattr(fc, "gen3_companion_pins", lambda tree, strict=False: PINS)
    monkeypatch.setattr(fc, "tracked_clean", lambda tree: True)
    monkeypatch.setattr(fc, "rewind_violations", lambda *a: [])
    monkeypatch.setattr(fc, "head", lambda tree: CUT)
    for body, want in ((_duo_out(), "PASS"), ("RESULT: PASS", "FAIL")):
        monkeypatch.setattr(fc, "run_once", lambda row, deadline, body=body: (0, body, False, False))
        row = fc.Row(C("link_gen3_fr_as_a"), "FRLGC-DUO", ["x"], str(tmp_path), 10)
        verdict, _n, _clean = fc.run_row(row, CUT, str(tmp_path), None)
        assert verdict.startswith(want), (body, verdict)


# ---- companion-check: the staged cartridge is the pinned composition of the clean dump and the shipped UPS ----

def _synthetic_lane(tmp_path, monkeypatch, tamper=None):
    sys.path.insert(0, fc.REPO)
    from patch.tools import make_ups
    clean = bytes(range(256)) * 8
    patched = bytearray(clean)
    patched[100:104] = b"SLNK"
    patched = bytes(patched)
    ups = make_ups.ups_create(clean, patched)
    lane = tmp_path / "lane"
    (lane / "patch/dist").mkdir(parents=True)
    (lane / "patch/build").mkdir(parents=True)
    (lane / "patch/dist/SLink-FireRed.ups").write_bytes(ups)
    (lane / fc.ROOT_DUMPS["firered"]).write_bytes(clean)
    (lane / fc.COMPANION_ROMS["firered"]).write_bytes(tamper or patched)
    pins = {"firered": hashlib.sha1(clean).hexdigest(), "firered_companion": hashlib.sha1(patched).hexdigest(),
            "firered_companion:md5": hashlib.md5(patched).hexdigest()}
    (lane / "patch/dist/gen3_companions.json").write_text(json.dumps({"titles": {"firered": {
        "patch": "SLink-FireRed.ups", "base_sha1": pins["firered"], "rom_sha1": pins["firered_companion"],
        "rom_md5": pins["firered_companion:md5"], "production": True}}}))
    monkeypatch.setattr(fc, "rom_pins", lambda tree, **kw: pins)
    return str(lane)


def test_companion_check_passes_a_correct_composition_and_fails_closed_otherwise(tmp_path, monkeypatch, capsys):
    lane = _synthetic_lane(tmp_path, monkeypatch)
    assert fc.companion_check(lane, "firered") == 0
    assert "RESULT: PASS" in capsys.readouterr().out
    bad = _synthetic_lane(tmp_path / "t", monkeypatch, tamper=b"not the companion" * 100)
    assert fc.companion_check(bad, "firered") == 1                                      # staged bytes differ from the pin
    assert "RESULT: FAIL" in capsys.readouterr().out
    os.remove(os.path.join(lane, fc.COMPANION_ROMS["firered"]))
    assert fc.companion_check(lane, "firered") == 1                                     # missing staged file
    capsys.readouterr()
    (tmp_path / "t2").mkdir()
    no_dump = _synthetic_lane(tmp_path / "t2", monkeypatch)
    os.remove(os.path.join(no_dump, fc.ROOT_DUMPS["firered"]))
    assert fc.companion_check(no_dump, "firered") == 1                                  # cannot recompose: fail, never skip
    assert "RESULT: FAIL" in capsys.readouterr().out


def test_companion_check_composes_the_real_staged_roms_when_the_dumps_are_reachable(capsys):
    """Known positive on the real bytes (skipped where the owner's dumps are not on disk; the lane run never skips)."""
    for t in ("firered", "leafgreen", "emerald"):
        dump = next((os.path.join(b, fc.ROOT_DUMPS[t]) for b in (fc.REPO, fc.main_checkout())
                     if os.path.isfile(os.path.join(b, fc.ROOT_DUMPS[t]))), None)
        if not dump or not os.path.isfile(os.path.join(fc.REPO, fc.COMPANION_ROMS[t])):
            pytest.skip("clean dumps or staged companions are not on this machine")
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as lane:
            for rel in (fc.COMPANION_ROMS[t], "patch/dist/gen3_companions.json", "patch/dist/companion_pins.json",
                        "tools/gen_gen3_write_checkpoint.py", f"patch/dist/SLink-{os.path.basename(fc.COMPANION_ROMS[t])[6:-4]}.ups"):
                os.makedirs(os.path.dirname(os.path.join(lane, rel)), exist_ok=True)
                shutil.copyfile(os.path.join(fc.REPO, rel), os.path.join(lane, rel))
            shutil.copyfile(dump, os.path.join(lane, fc.ROOT_DUMPS[t]))
            assert fc.companion_check(lane, t) == 0, capsys.readouterr().out


def test_zip_boot_refuses_a_companion_title_whose_staged_rom_is_not_the_pin(tmp_path, monkeypatch, capsys):
    import zipfile
    zpath = tmp_path / "z.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("SLink/lua/slink.lua", "-- entry")
    lane = tmp_path / "lane"
    (lane / "patch/build").mkdir(parents=True)
    (lane / fc.COMPANION_ROMS["firered"]).write_bytes(b"not the pinned companion")
    monkeypatch.setattr(fc, "rom_pins", lambda tree, **kw: dict(PINS))
    boom = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: boom.append(a))
    assert fc.zip_boot(str(zpath), str(lane), 5, "firered_companion") == 1
    out = capsys.readouterr().out
    assert "RESULT: FAIL" in out and "not the firered companion pin" in out and not boom       # nothing was launched


def test_every_companion_bootcheck_row_binds_its_rom_to_the_pin():
    """F2: their own verdict carries no pin binding, so the TOOL must refuse any --rom but the pinned build."""
    rows = [r for r in fc.build_plan_frlgc(CUT, LANE, MASTER) if "bootcheck_" in r.id]
    assert len(rows) == 12 and all("--companion" in r.argv for r in rows)
    assert all("--companion" not in r.argv for r in fc.build_plan("c" * 40, LANE, MASTER) if "bootcheck_" in r.id)


def _lane_with_pins(tmp_path, name, pins):
    import json as _json

    dist = tmp_path / name / "patch" / "dist"
    dist.mkdir(parents=True)
    titles = {t: {"rom_sha1": pins[f"{t}_companion"], "rom_md5": "0" * 32, "canonical_sha1": "1" * 40,
                  "production": True} for t in ("firered", "leafgreen", "emerald")}
    (dist / "gen3_companions.json").write_text(_json.dumps({"titles": titles}), encoding="utf-8")
    return str(tmp_path / name)


def test_fc_check_judges_companion_evidence_against_the_lanes_pins_not_the_main_checkouts(tmp_path):
    """F3: the main checkout's gen3_companions.json differs from the cut's -- the cut's pins decide."""
    row = C("link_gen3_fr_as_a")
    name = f"fc_{row}_{CUT[:8]}.txt"
    text = _receipt(row, _duo_out())                               # admissions carry the PINS prefixes
    lane = _lane_with_pins(tmp_path, "lane_ok", PINS)
    other = _lane_with_pins(tmp_path, "lane_other", {k: hashlib.sha1(k.encode() + b"x").hexdigest() for k in PINS})
    assert fc.gen3_companion_pins(fc.REPO) != fc.gen3_companion_pins(lane)           # the lane differs from main
    assert fc.fc_check(name, text, str(tmp_path), lane=lane)[1]
    ok, why = fc.fc_check(name, text, str(tmp_path), lane=other)[1:]
    assert not ok and "companion" in why                                              # the lane's other pins reject it
    # no lane given: the CUT's own pins (git show), and a cut git cannot show fails closed -- never main's pins
    assert fc.gen3_companion_pins_at("0" * 40) == {}
    ok, why = fc.fc_check(name, text, str(tmp_path))[1:]
    assert not ok and "pin to compare" in why
    assert fc.gen3_companion_pins_at("HEAD") == fc.gen3_companion_pins(fc.REPO)      # the cut's pins are readable


def test_prior_verdict_threads_the_lane(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(fc, "PROBES", str(tmp_path))
    row = C("link_gen3_fr_as_a")
    (tmp_path / f"fc_{row}_{CUT[:8]}.txt").write_text(_receipt(row, _duo_out()), encoding="utf-8")
    real = fc.fc_check
    monkeypatch.setattr(fc, "fc_check", lambda *a, **k: seen.append(k.get("lane")) or real(*a, **k))
    lane = _lane_with_pins(tmp_path, "lane_ok", PINS)
    assert fc.prior_verdict(row, CUT, lane) == "PASS" and seen == [lane]
    assert fc.prior_verdict(row, CUT) is None            # default: the cut's pins, absent here -> not adopted
