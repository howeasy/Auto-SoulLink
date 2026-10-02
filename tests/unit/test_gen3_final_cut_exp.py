"""Expansion final-cut planning and fail-closed evidence, without launching an emulator."""
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import e2e_duo  # noqa: E402
import gen3_final_cut as fc  # noqa: E402
import gen3_probe_receipt as receipts  # noqa: E402

CUT = "c" * 40
TITLE = "emerald_expansion_28877d73"


def test_exp_cli_lists_the_registry_and_zip_closure_without_a_lane(monkeypatch, capsys):
    monkeypatch.setattr(fc, "main_checkout", lambda: fc.REPO)
    assert fc.main(["--cut", "HEAD", "--title", "exp", "--lane", "unused-exp-lane", "--list"]) == 0
    listed = [line.split()[0] for line in capsys.readouterr().out.splitlines()]
    expected = [name + "_exp_as_a" for name in e2e_duo.SCENARIOS
                if e2e_duo.scenario_applies(name, "gen3_exp")]
    assert set(expected) <= set(listed)
    assert listed[-3:] == ["exp_zip_build", "exp_zip_check", "zip_boot_exp"]
    assert len(listed) == len(set(listed))


def test_exp_plan_includes_future_explicit_rows_and_refuses_unruled_limits(monkeypatch):
    monkeypatch.setitem(e2e_duo.SCENARIOS, "future_exp", {
        "games": ("gen3_exp",), "explicit_only": True, "timeout": 1})
    rows = fc.build_plan_exp(CUT, "L:/lane", "unused")
    assert "future_exp_exp_as_a" in {r.id for r in rows}
    monkeypatch.setitem(e2e_duo.SCENARIOS["future_exp"], "signed_limit", "unreviewed")
    with pytest.raises(RuntimeError, match="expansion signed limit"):
        fc.build_plan_exp(CUT, "L:/lane", "unused")


def test_exp_boot_and_input_names_bind_the_existing_duo_contract():
    assert fc.STAGED["exp"] == "patch/build/gen3_pokeemerald.gba"
    assert fc.ROOT_DUMPS["exp"] == ".cache/expansion-output/reference/pokeemerald.gba"
    rom, launched, seed, battery, _client, hello = fc.ZIP_BOOT["exp"]
    assert rom == fc.STAGED["exp"] and launched == "gen3_pokeemerald.gba"
    assert seed == "exp_pc.sav"
    assert battery == e2e_duo.GEN3_TITLES[TITLE]["saveram"]
    assert hello == f"hello rom={TITLE} "
    assert fc.EXPANSION_PINNED_INPUTS[rom][0] == "exp"
    pins = fc.rom_pins(fc.REPO, include_expansion=True)
    profile = json.loads((Path(fc.REPO) / "data/games/gen3_exp/28877d73/profile.json").read_text())
    assert pins["exp"] == profile["source"]["rom_sha1"]


def test_exp_zip_pack_closure_is_in_existing_release_manifest():
    from tools import make_release
    assert set(fc.EXPANSION_ZIP_PACK_FILES) == {
        "profile.json", "engine_signals.json", "write_checkpoint.json",
        "area_map.json", "gen3_exp_locations.lua"}
    assert set(fc.EXPANSION_ZIP_PACK_FILES) <= set(make_release._DATA_GAME_LUA["gen3_exp/28877d73"])


SERVER_ROUTE = (f"TEST-ONLY route of {TITLE} -> gen3_exp enabled "
                "(production refuses it by name; production:false)")
CLIENT_ROUTE = ("TEST-ONLY route of gen3_exp (pre-XG; production Entry.ROUTED lacks it)\n"
                f"TEST-ONLY admission of gen3_exp/{TITLE} (pre-XG; production refuses)\n")


def output(cut=CUT, route=True, client=False):
    return (f"EXPANSION_CUT requested={cut} before={cut}\n" +
            (SERVER_ROUTE + "\n" if route else "") + (CLIENT_ROUTE if client else "") +
            f"EXPANSION_CUT after={cut}\n")


def receipt(row="faint_cmd_gen3_exp_as_a", body=None, **updates):
    attempt = {"load": "cpu=1%", "start_utc": "2026-10-01T12:00:00Z",
               "end_utc": "2026-10-01T12:01:00Z", "rc": 0, "tracked_before": True,
               "tracked_after": True, "classification": "pass",
               "output": output(client=True) if body is None else body}
    attempt.update(updates)
    return receipts.run_receipt_text(row=row, item="XG3", cut=CUT, lane="lane",
                                     command="model", cwd="lane", env={},
                                     attempts=[attempt], verdict="PASS")


@pytest.mark.parametrize("row", ["unit_exp", "profile_generated_check_exp", "exp_zip_build",
                                "exp_zip_check", "faint_cmd_gen3_exp_as_a", "zip_boot_exp"])
def test_exp_receipt_accepts_bound_source_or_logged_runtime(row, tmp_path):
    assert fc.fc_check(f"fc_{row}_{CUT[:8]}.txt", receipt(row), str(tmp_path))[1]


@pytest.mark.parametrize("change,why", [
    (lambda s: s.replace(SERVER_ROUTE, "route was requested"), "logged test-only"),
    (lambda s: s.replace("before=" + CUT, "before=" + "d" * 40), "full SHA"),
    (lambda s: s.replace("after=" + CUT, "after=" + CUT[:8]), "full SHA"),
    (lambda s: s.replace("after=" + CUT, "after=" + CUT + "0"), "full SHA"),
    (lambda s: s.replace("tracked_clean_before=True", "tracked_clean_before=False"), "clean before"),
    (lambda s: s.replace("tracked_clean_after=True", "tracked_clean_after=False"), "last attempt"),
])
def test_exp_receipt_rejects_each_missing_or_changed_fact(change, why, tmp_path):
    row = "faint_cmd_gen3_exp_as_a"
    _hdr, ok, problem = fc.fc_check(f"fc_{row}_{CUT[:8]}.txt", change(receipt(row)), str(tmp_path))
    assert not ok and why in problem


def test_zip_boot_requires_client_seam_as_well_as_server_route(tmp_path):
    row = "zip_boot_exp"
    text = receipt(row, output(client=False))
    assert not fc.fc_check(f"fc_{row}_{CUT[:8]}.txt", text, str(tmp_path))[1]


def test_exp_receipt_cannot_borrow_a_route_from_an_earlier_attempt(tmp_path):
    row = "faint_cmd_gen3_exp_as_a"
    text = receipt(row).replace("--- attempt 1 of 1 ---", "--- attempt 1 of 2 ---")
    tail = receipt(row, output(route=False)).split("--- attempt 1 of 1 ---")[1]
    text += "--- attempt 2 of 2 ---" + tail
    assert not fc.fc_check(f"fc_{row}_{CUT[:8]}.txt", text, str(tmp_path))[1]


def test_exp_header_short_or_wrong_cut_cannot_resume(tmp_path):
    row = "faint_cmd_gen3_exp_as_a"
    for changed in (CUT[:8], "d" * 40):
        text = receipt(row).replace("cut=" + CUT, "cut=" + changed, 1)
        assert not fc.fc_check(f"fc_{row}_{CUT[:8]}.txt", text, str(tmp_path))[1]


def test_exp_rows_and_zip_chain_never_carry_prior_evidence():
    rows = fc.build_plan_exp(CUT, "lane", "unused")
    assert all(r.deps is None for r in rows)
    assert {fc.chain_of(r.id) for r in rows[-3:]} == {"zip"}
    source = rows[:7]
    assert all(not r.emulator and not r.own_verdict for r in source)
    assert all(Path(fc.REPO, f).is_file() for f in fc.EXPANSION_UNIT_FILES)
    area = next(r for r in rows if r.id == "area_map_generated_check_exp")
    assert area.argv[-7:-2] == ["--game", "emerald", "--expansion", "28877d73", "--check"]
    assert area.argv[-2:] == ["--source", fc.expansion_env("lane")["SLINK_EXPANSION_SRC"]]
    gift = next(r for r in rows if r.id == "gift_census_check_exp")
    assert gift.argv[-2:] == ["--src", fc.expansion_env("lane")["SLINK_EXPANSION_SRC"]]
    assert all(r.env == fc.expansion_env("lane") for r in rows)
    assert all(r.cwd == "lane" for r in rows)


def test_exp_unit_collection_includes_new_matching_module(tmp_path):
    unit = tmp_path / "tests/unit"
    write(unit / "test_gen3_exp_future.py", "def test_future(): pass\n")
    assert "tests/unit/test_gen3_exp_future.py" in fc.expansion_unit_files(tmp_path)


def test_exp_unit_collection_rejects_adjacent_generations(tmp_path):
    unit = tmp_path / "tests/unit"
    for name in ("test_gen1_rival_swap_explode.py", "test_gen2_explode_rival.py",
                 "test_gen3_explode_bind.py", "test_gen3_export_future.py",
                 "test_gen4_future_exp.py", "test_purergb_exp.py", "test_crystal_exp.py"):
        write(unit / name, "def test_adjacent(): pass\n")
        assert f"tests/unit/{name}" not in fc.expansion_unit_files(tmp_path)
    assert not hasattr(fc, "EXPANSION_UNIT_EXCLUSIONS")


def test_exp_unit_collection_covers_current_expansion_modules():
    collected = set(fc.EXPANSION_UNIT_FILES)
    for name in ("test_gen3_exp_sites.py", "test_gen3_fixture_exp.py",
                 "test_gen3_title_syms_exp.py", "test_gen3_expansion_towns.py",
                 "test_gen3_expansion_trainer_panel.py", "test_gen3_expansion_gift_policy.py",
                 "test_gen3_exp_release_row.py", "test_gen3_exp_player_gender.py",
                 "test_gen3_exp_faint_pin.py", "test_gen3_exp_signal_mirror.py",
                 "test_gen3_exp_acquisition_rows.py", "test_gen3_exp_static_wild_rows.py"):
        assert f"tests/unit/{name}" in collected
    for name in ("test_e2e_duo_gen3_exp.py", "test_gen3_codec_expansion.py",
                 "test_gen3_fixture_exp.py", "test_gen3_title_syms_exp.py"):
        assert f"tests/unit/{name}" in collected


@pytest.mark.parametrize("dirty,actual", [(False, "d" * 40), (True, CUT)])
def test_exp_row_never_executes_on_wrong_cut_or_dirty_lane(monkeypatch, tmp_path, dirty, actual):
    monkeypatch.setattr(fc, "PROBES", str(tmp_path))
    monkeypatch.setattr(fc, "head", lambda _lane: actual)
    monkeypatch.setattr(fc, "tracked_clean", lambda _lane: not dirty)
    monkeypatch.setattr(fc, "load_snapshot", lambda: "model")
    monkeypatch.setattr(fc, "rewind_violations", lambda *_: [])
    def forbidden(*_):
        raise AssertionError("wrong/dirty lane must not run")
    monkeypatch.setattr(fc, "run_once", forbidden)
    row = fc.Row("unit_exp", "MODEL", [], str(tmp_path), 0, emulator=False)
    assert fc.run_row(row, CUT, str(tmp_path), None)[0].startswith("FAIL")


def test_exp_row_zero_exit_without_logged_route_is_a_real_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(fc, "PROBES", str(tmp_path))
    monkeypatch.setattr(fc, "head", lambda _: CUT)
    monkeypatch.setattr(fc, "tracked_clean", lambda _: True)
    monkeypatch.setattr(fc, "load_snapshot", lambda: "model")
    monkeypatch.setattr(fc, "rewind_violations", lambda *_: [])
    calls = []
    def run(*_):
        calls.append(1)
        return 0, "PYDEC: PASS", False, False
    monkeypatch.setattr(fc, "run_once", run)
    row = fc._duo("faint_cmd_gen3", "gen3_exp", "XG3", str(tmp_path))
    verdict, attempts, _clean = fc.run_row(row, CUT, str(tmp_path), None)
    assert verdict.startswith("FAIL") and attempts == 1 and calls == [1]


def test_exp_row_refuses_source_checkout_dirtied_by_check_generator(monkeypatch, tmp_path):
    lane, source = tmp_path / "lane", tmp_path / "source"
    source.mkdir()
    write(lane / "data/gen3_exp_sources.lock.json", json.dumps({"source": {"commit": "e" * 40}}))
    monkeypatch.setattr(fc, "PROBES", str(tmp_path))
    monkeypatch.setattr(fc, "head", lambda path: CUT if str(path) == str(lane) else "e" * 40)
    dirty = [False]
    monkeypatch.setattr(fc, "tracked_clean", lambda path: not dirty[0] if str(path) == str(source)
                        else True)
    monkeypatch.setattr(fc, "load_snapshot", lambda: "model")
    monkeypatch.setattr(fc, "rewind_violations", lambda *_: [])
    def run(*_):
        dirty[0] = True
        return 0, "generator --check passed", False, False
    monkeypatch.setattr(fc, "run_once", run)
    row = fc.Row("area_map_generated_check_exp", "SOURCE", [], str(lane), 0,
                 emulator=False, env={"SLINK_EXPANSION_SRC": str(source)})
    verdict, attempts, _clean = fc.run_row(row, CUT, str(lane), None)
    assert verdict.startswith("FAIL") and attempts == 1
    assert "source checkout" in Path(fc.receipt_path(row.id, CUT)).read_text()


def write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(body, bytes):
        path.write_bytes(body)
    else:
        path.write_text(body, encoding="utf-8")


def source_inputs(tmp_path, monkeypatch):
    """Real source git identity; tiny fake ROM/probe to exercise copying without copyrighted bytes."""
    repo, lane = tmp_path / "repo", tmp_path / "lane"
    source = repo / ".cache/expansion-src"
    write(source / "include/config/example.h", "pinned header")
    def git(*args):
        return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()
    git("init", "-q")
    git("add", "include")
    git("-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "source")
    sha = git("rev-parse", "HEAD")
    rom = b"fake ROM input"
    rom_sha = hashlib.sha1(rom).hexdigest()
    probe = repo / ".cache/x1-probe/probe.o"
    write(probe, b"fake offline object")
    write(probe.with_name("compile.json"), "{}")
    facts = {"provenance": {"compile": {"object_sha256": hashlib.sha256(probe.read_bytes()).hexdigest()}}}
    write(lane / fc.EXPANSION_PACK / "facts.json", json.dumps(facts))
    write(lane / "data/gen3_exp_sources.lock.json", json.dumps({
        "source": {"commit": sha}, "config_headers": {
            "include/config/example.h": hashlib.sha256(b"pinned header").hexdigest()}}))
    for kind in ("pc", "catch"):
        for side in ("", "_b"):
            write(lane / f"tests/fixtures/gen3/exp_{kind}{side}.sav", b"fake tracked seed")
    for rel in (".cache/pret/pokeemerald/README", ".cache/expansion-output/reference/pokeemerald.sym",
                ".cache/expansion-output/reference/pokeemerald.map",
                ".cache/expansion-output/reference/pokeemerald.elf",
                ".cache/expansion-output/reference/receipt.json"):
        write(repo / rel, "artifact")
    write(repo / fc.ROOT_DUMPS["exp"], rom)
    monkeypatch.setattr(fc, "expansion_rom_pin", lambda _: rom_sha)
    monkeypatch.setenv("SLINK_EXPANSION_SRC", str(source))
    monkeypatch.setenv("SLINK_EXPANSION_PROBE_OBJECT", str(probe))
    return lane, repo, source, probe


def test_exp_input_copy_preserves_full_artifacts_and_binds_private_probe(tmp_path, monkeypatch):
    lane, repo, source, probe = source_inputs(tmp_path, monkeypatch)
    fc.copy_expansion_inputs(str(lane), str(repo), str(repo))
    assert (lane / fc.STAGED["exp"]).read_bytes() == (repo / fc.ROOT_DUMPS["exp"]).read_bytes()
    for name in ("pokeemerald.sym", "pokeemerald.map", "pokeemerald.elf", "receipt.json"):
        assert (lane / ".cache/expansion-output/reference" / name).is_file()
    linked = lane / ".cache/expansion-src"
    assert os.path.realpath(linked) == os.path.realpath(source)
    private_probe = Path(fc.expansion_env(str(lane))["SLINK_EXPANSION_PROBE_OBJECT"])
    assert private_probe.read_bytes() == probe.read_bytes()
    assert private_probe.with_name("compile.json").is_file()
    assert not (lane / fc.STAGED["firered"]).exists()  # no unrelated input obligation


@pytest.mark.parametrize("bad", ["dirty_source", "wrong_source", "header", "probe", "missing_probe",
                                 "fixture", "rom"])
def test_exp_input_drift_fails_closed(tmp_path, monkeypatch, bad):
    lane, repo, source, probe = source_inputs(tmp_path, monkeypatch)
    if bad == "dirty_source":
        write(source / "include/config/example.h", "tracked edit")
    elif bad == "wrong_source":
        monkeypatch.setenv("SLINK_EXPANSION_SRC", str(tmp_path / "missing_source"))
    elif bad == "header":
        lock = lane / "data/gen3_exp_sources.lock.json"
        value = json.loads(lock.read_text())
        value["config_headers"]["include/config/example.h"] = "0" * 64
        write(lock, json.dumps(value))
    elif bad == "probe":
        write(probe, b"wrong object")
    elif bad == "missing_probe":
        probe.unlink()
    elif bad == "fixture":
        (lane / "tests/fixtures/gen3/exp_catch_b.sav").unlink()
    else:
        write(repo / fc.ROOT_DUMPS["exp"], b"wrong ROM")
    with pytest.raises(fc.LaneError):
        fc.copy_expansion_inputs(str(lane), str(repo), str(repo))


def test_offline_probe_without_original_compile_manifest_does_not_invent_one(tmp_path, monkeypatch):
    lane, repo, _source, probe = source_inputs(tmp_path, monkeypatch)
    probe.with_name("compile.json").unlink()
    fc.copy_expansion_inputs(str(lane), str(repo), str(repo))
    target = Path(fc.expansion_env(str(lane))["SLINK_EXPANSION_PROBE_OBJECT"])
    assert target.read_bytes() == probe.read_bytes()
    assert not target.with_name("compile.json").exists()


def extracted_pack(tmp_path):
    root = tmp_path / "extract"
    for name in fc.EXPANSION_ZIP_PACK_FILES:
        write(root / fc.EXPANSION_PACK / name, (Path(fc.REPO) / fc.EXPANSION_PACK / name).read_bytes())
    write(root / "lua/gen3/entry.lua", "Entry.ROUTED = {gen3_frlg = true}\n")
    write(root / "lua/slink.lua", "-- model launcher")
    return root


@pytest.mark.parametrize("missing", [None, *fc.EXPANSION_ZIP_PACK_FILES])
def test_extracted_zip_pack_closure_is_checked_before_boot(tmp_path, missing):
    root = extracted_pack(tmp_path)
    if missing:
        (root / fc.EXPANSION_PACK / missing).unlink()
    reason = fc.expansion_zip_blocker(str(root / "lua"))
    assert (reason is None) == (missing is None)
    if missing:
        assert missing in reason


@pytest.mark.parametrize("bad", ["profile", "entry"])
def test_exp_zip_production_refusal_cannot_be_flipped(tmp_path, bad):
    root = extracted_pack(tmp_path)
    if bad == "entry":
        write(root / "lua/gen3/entry.lua", "Entry.ROUTED = {gen3_exp = true}\n")
    else:
        path = root / fc.EXPANSION_PACK / "profile.json"
        profile = json.loads(path.read_text())
        profile["titles"][TITLE]["admitted"] = True
        write(path, json.dumps(profile))
    assert fc.expansion_zip_blocker(str(root / "lua")) is not None


@pytest.mark.parametrize("route,blocked", [
    ('Entry.ROUTED = {gen3_frlg = { nested = true }, gen3_exp = true}', True),
    ('Entry.ROUTED = {label = "gen3_exp = true", gen3_frlg = true}', False),
    ('Entry.ROUTED = {-- gen3_exp = true\n gen3_frlg = true}', False),
    ('Entry.ROUTED = {gen3_frlg = {nested = "}"}, ["gen3_exp"] = true}', True),
])
def test_exp_zip_route_scanner_handles_nested_tables_strings_and_comments(tmp_path, route, blocked):
    root = extracted_pack(tmp_path)
    write(root / "lua/gen3/entry.lua", route)
    assert (fc.expansion_zip_blocker(str(root / "lua")) is not None) is blocked


def test_exp_zip_route_scanner_rejects_second_admitting_assignment(tmp_path):
    root = extracted_pack(tmp_path)
    write(root / "lua/gen3/entry.lua", "Entry.ROUTED = {gen3_frlg = true}\n"
          "Entry.ROUTED = {gen3_exp = true}\n")
    assert fc.expansion_zip_blocker(str(root / "lua")) is not None


def test_real_duo_admission_seam_composes_with_zip_launcher_without_editing_json():
    from lupa import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(r'''
    transcript = ""
    os = {getenv=function(k) if k == "SLINK_ZIPBOOT_ENTRY" then return "/extract/lua/slink.lua" end
                            return "route-log" end}
    io = {open=function() return {write=function(_, ...) for _,s in ipairs({...}) do
                      transcript=transcript..s end end, close=function() end} end}
    joypad = {set=function() end}; emu = {frameadvance=function() end}
    docs = {titles={emerald_expansion_28877d73={admitted=false}, other={admitted=false}}}
    original_json = {decode=function() return docs end}
    dofile = function(path)
        if path == "/extract/lua/json_codec.lua" then return original_json end
        if path == "/extract/lua/gen3/entry.lua" then return {ROUTED={gen3_frlg=true}} end
        if path == "/extract/lua/slink.lua" then
            local entry = dofile("/extract/lua/gen3/entry.lua")
            local json = dofile("/extract/lua/json_codec.lua")
            assert(entry.ROUTED.gen3_exp)
            assert(json.decode().titles.emerald_expansion_28877d73.admitted)
            assert(json.decode().titles.other.admitted == false)
            assert(original_json.decode ~= json.decode)
            booted = true
        end
    end
    ''')
    lua.execute(fc.zip_bootstrap(fc.REPO, "exp"))
    assert lua.globals().booted is True
    assert "TEST-ONLY route of gen3_exp" in lua.globals().transcript
    assert f"TEST-ONLY admission of gen3_exp/{TITLE}" in lua.globals().transcript
    # Other titles continue to use the unchanged shipped launcher path.
    assert fc.zip_bootstrap(fc.REPO, "emerald") == fc._BOOT_LUA


@pytest.mark.parametrize("logged", [True, False])
def test_exp_zip_launch_uses_flag_and_requires_actual_server_and_client_logs(tmp_path, monkeypatch, logged):
    import gen3_fixtures
    root = extracted_pack(tmp_path)
    zip_path = tmp_path / "model.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(path, str(Path("SLink") / path.relative_to(root)))
    lane = tmp_path / "lane"
    write(lane / fc.STAGED["exp"], b"fake ROM")
    write(lane / "tests/fixtures/gen3/exp_pc.sav", b"fake save")
    tmp = tmp_path / "boot"
    tmp.mkdir()
    monkeypatch.setattr(fc.tempfile, "mkdtemp", lambda **_: str(tmp))
    monkeypatch.setattr(fc, "zip_bootstrap", lambda *_: "-- model")
    monkeypatch.setattr(gen3_fixtures.codec, "split_rtc", lambda body: (body, None))
    monkeypatch.setattr(gen3_fixtures, "write_gba_run_config",
                        lambda _base, cfg, _save: write(Path(cfg), '{"Rewind":{"Enabled":false}}'))
    monkeypatch.setattr(fc.time, "sleep", lambda _: None)
    ticks = iter([0, 1, 3])
    monkeypatch.setattr(fc.time, "time", lambda: next(ticks))
    calls = []
    class Process:
        def poll(self):
            return 0
    def launch(argv, **kwargs):
        calls.append((argv, kwargs))
        if "server.server" in argv:
            assert argv[-2:] == ["--test-only-route", TITLE]
            kwargs["stdout"].write((SERVER_ROUTE if logged else "") + f"\nhello rom={TITLE} \n")
            kwargs["stdout"].flush()
        else:
            env = kwargs["env"]
            entry = Path(env["SLINK_ZIPBOOT_ENTRY"])
            write(entry.parent.parent / "slink_lua.log",
                  f"[SLink-gen3] gen3_exp/{TITLE} (clean by hash) player a TCP connected\n")
            write(Path(env["SLINK_ZIPBOOT_ROUTE_LOG"]), CLIENT_ROUTE)
            assert Path(env["SLINK_STATE_DIR"]).parent == tmp
        return Process()
    monkeypatch.setattr(fc.subprocess, "Popen", launch)
    assert fc.zip_boot(str(zip_path), str(lane), timeout=2, title="exp") == (0 if logged else 1)
    assert len(calls) == 2


def test_exp_plan_requires_cited_shadow_negatives_before_duos_and_zip():
    plan=fc.build_plan_exp(CUT,"L:/lane","unused")
    row=next((r for r in plan if r.id=="shadow_negatives_exp"),None)
    assert row is not None,"expansion PC observer controls absent from final-cut plan"
    assert row.emulator is False and row.budget==120
    assert row.argv[1:]==["tools/gen3_shadow_negatives.py","docs/gen3_exp/negatives_manifest.json"]
    assert row.deps is None
    names=[r.id for r in plan]
    assert names.index(row.id)<names.index("unit_exp")
    duo_count=sum(e2e_duo.scenario_applies(n,"gen3_exp")for n in e2e_duo.SCENARIOS)
    assert len(plan)==duo_count+11


def test_exp_pc_negative_manifest_binds_real_windows_and_positive_siblings():
    from tests.unit.test_gen3_exp_pc_negative_legs import (
        check_absent_over_window,
        check_bypass_window,
        check_fired_outside_window,
        statuses,
    )
    root=Path(fc.REPO)
    manifest=json.loads((root/"docs/gen3_exp/negatives_manifest.json").read_text())
    assert {r['artifact']for r in manifest['receipts']}=={'pc_release_bypass','pc_release_cancel','pc_full_box'}
    for row in manifest['receipts']:
        proof=row['pc_window']
        raw=(root/row['file']).read_text(encoding='utf-8')
        source=(root/proof['full_shadow']).read_text(encoding='utf-8')
        assert raw==source and hashlib.sha256(source.encode()).hexdigest()==proof['shadow_text_sha256']
        assert len(proof['source_head'])==40
        result=(root/proof['result']).read_text(encoding='utf-8')
        assert hashlib.sha256(result.encode()).hexdigest()==proof['result_text_sha256']
        assert 'RESULT: PASS' in result
        shadow=raw
        assert all(s['rejected']=='0' and s['dropped']=='0' and s['failed']=='nil'
                   and s['handler_error']=='nil' for s in statuses(shadow))
        lo,hi=proof['frames']
        markers={'pc_release_bypass':('leg-start', 'bypassed', 'emerald_pc_move_release_bypass'),
                 'pc_release_cancel':('leg-start','release-cancelled','emerald_pc_release_cancel'),
                 'pc_full_box':('box-refusal-start','box-full',None)}
        start,end,leg=markers[row['artifact']]
        suffix=' '+re.escape(leg)+'$'if leg else r'(?:\s|$)'
        actual_lo=re.findall(rf'(?m)^phase {start} frame=(\d+)'+suffix,result)
        actual_hi=re.findall(rf'(?m)^phase {end} frame=(\d+)(?:\s|$)',result)
        assert actual_lo==[str(lo)] and actual_hi==[str(hi)]
        if row['artifact']=='pc_release_bypass':
            check_bypass_window(shadow,lo,hi)
        else:
            kind='pc_release'if row['artifact']=='pc_release_cancel'else'pc_deposit'
            check_absent_over_window(shadow,kind,lo,hi)
            check_fired_outside_window(shadow,kind,lo,hi)
        assert proof['claim']=='raw observer window only; client reporting remains unqualified'
        assert 'pc_move'not in {r['kind']for r in row['must_not']}
