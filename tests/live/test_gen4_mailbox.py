"""Gen 4 companion C1 mailbox canary watch: offline model tests + opt-in serial PHYSICAL collection.

Offline: python -m pytest tests/live/test_gen4_mailbox.py -m 'not live' -q
Live (the coordinator's one Gen 4 emulator lane, never run by a worker):
    SLINK_LIVE=1 SLINK_GEN4_HEARTGOLD_SAVE=<town save> SLINK_GEN4_SOULSILVER_SAVE=... SLINK_GEN4_HEARTGOLD_HGE_SAVE=...
    SLINK_GEN4_PROBE_SCENARIO=<gen4-probe-scenario-v1 json> python -m pytest tests/live/test_gen4_mailbox.py -m live -q -rs
Absent ROM/save/EmuHawk/census inputs are named skips; malformed or mismatched present inputs fail.
Two runs per title (canary A, then canary B, different seeds). A run whose known-positive or host-rewrite
control is not detected is INVALID (rows d-i FAIL). The output is ONE accepted span per artifact or no address.
"""
from __future__ import annotations

import copy
import datetime
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from tools import gen4_evidence, gen4_fixtures, gen4_mailbox_census

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "lua/tests/probe_gen4_mailbox.lua"
ROWS = tuple("abcdefghi")
ROW_RE = re.compile(r"^PROBE ([a-i]) (PASS|FAIL|OPEN) (\{.*\})$")
TITLES = ("heartgold", "soulsilver", "heartgold_hge")
GAME = {"heartgold": "HG", "soulsilver": "SS", "heartgold_hge": "hge"}
KINDS = ("A", "B")


def register_mailbox_kind():
    """Make tools/gen4_evidence.py know this producer without editing it (a permanent entry is the coordinator's)."""
    gen4_evidence.SCRIPTS.setdefault("mailbox", "lua/tests/probe_gen4_mailbox.lua")
    gen4_evidence.PYTHON.setdefault("mailbox", (
        "tests/live/test_gen4_mailbox.py", "tools/gen4_mailbox_census.py", "lua/tests/probe_gen4_hooks.lua",
        "lua/tests/gen4_route_play.lua", "tools/gen4_routes.py", "tools/gen4_fixtures.py", "tools/gen4_pins.py"))


register_mailbox_kind()


def digest(path: Path, algorithm="sha256") -> str:
    h = hashlib.new(algorithm)
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def input_file(path: Path, name: str) -> Path:
    if not Path(path).is_file():
        pytest.skip(f"OPEN {name}: absent input {path}")
    return Path(path)


# ---------------------------------------------------------------------------------------------- pure python half
def parse_receipt(text, *, title, rom_sha1, run_id, cut, canary):
    """No stale neighbour, duplicate row, wrong artifact, wrong canary, MODEL-as-PHYSICAL or tail accepted."""
    lines = text.splitlines()
    assert lines and lines[-1] in {"RESULT: PASS", "RESULT: FAIL", "RESULT: OPEN"}, "missing terminal RESULT"
    assert sum(line.startswith("RESULT:") for line in lines) == 1, "multiple RESULT lines"
    rows = {}
    for line in lines[:-1]:
        m = ROW_RE.fullmatch(line)
        assert m, f"malformed receipt line: {line[:160]}"
        row, status, raw = m.groups()
        assert row not in rows, f"duplicate row {row}"
        payload = json.loads(raw)
        gen4_evidence.bind(payload, cut, title=title, rom_sha1=rom_sha1)
        assert payload["title"] == title and payload["level"] == "PHYSICAL", "wrong artifact binding / MODEL evidence"
        assert payload["run_id"] == run_id, "stale/wrong-run receipt"
        assert payload["canary"] == canary, "wrong canary pattern for this run"
        rows[row] = (status, payload)
    statuses = [s for s, _ in rows.values()]
    expected = "FAIL" if "FAIL" in statuses else "OPEN" if "OPEN" in statuses or set(rows) != set(ROWS) else "PASS"
    assert lines[-1] == f"RESULT: {expected}", "terminal status contradicts row statuses"
    return rows


def combine(title, runs, census_status, span):
    """runs: {"A": rows, "B": rows}. ONE accepted span only when both canaries PASS every row and the census is PASS."""
    status, why = "PASS", []
    if set(runs) != set(KINDS):
        status, why = "OPEN", [f"runs present: {sorted(runs)}; both canary patterns are required"]
    seeds = {k: next(iter(r.values()))[1].get("seed") for k, r in runs.items() if r}
    if len(set(seeds.values())) != len(seeds) or None in seeds.values():
        status, why = "FAIL", why + [f"canary runs must use different seeds: {seeds}"]
    for kind, rows in sorted(runs.items()):
        for row in ROWS:
            got, payload = rows.get(row, ("OPEN", {"reason": "row absent"}))
            if got == "FAIL":
                status, why = "FAIL", why + [f"{kind}/{row}: {payload.get('reason')}"]
            elif got == "OPEN" and status != "FAIL":
                status, why = "OPEN", why + [f"{kind}/{row}: {payload.get('reason')}"]
    if status == "PASS" and census_status != "PASS":
        status, why = "OPEN", [f"source/artifact census is {census_status}, not PASS"]
    return {"title": title, "status": status, "reasons": why,
            "accepted": {"span": [f"{span[0]:#010x}", f"{span[1]:#010x}"], "domain": "Instruction TCM", "offset": f"{span[0] & 0x7FFF:#06x}"}
            if status == "PASS" else None}


def seed_for(run_id: str, kind: str) -> int:
    return int(hashlib.sha256(f"{run_id}/{kind}".encode()).hexdigest()[:6], 16) % 100000 + (1 if kind == "A" else 2)


# ---------------------------------------------------------------------------------------------- Lua model (lupa)
@pytest.fixture
def lua():
    from lupa import LuaRuntime
    runtime = LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().SLINK_GEN4_MAILBOX_TEST = True
    model = runtime.execute(SCRIPT.read_text(encoding="utf-8"))
    runtime.execute("""
        -- a fake byte-addressable memory window; `game` is called once per fake frame
        function make_io(n, opts)
            opts = opts or {}
            local mem = {}
            for i = 0, n - 1 do mem[i] = 0 end
            local io = {mem = mem}
            function io.write(off, t) if opts.drop_writes then return end for i, b in ipairs(t) do mem[off + i - 1] = b end end
            function io.read(off, k) local r = {} for i = 1, k do r[i] = (opts.stale and opts.stale[off + i - 1]) or mem[off + i - 1] end return r end
            return io
        end
    """)
    return runtime, model


def to_lua(rt, value):
    if isinstance(value, dict):
        return rt.table_from({k: to_lua(rt, v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return rt.table_from([to_lua(rt, v) for v in value])
    return value


def lua_list(t):
    return [t[i] for i in range(1, len(t) + 1)]


def test_canary_patterns_never_collide_and_never_look_like_init_bytes(lua):
    _, m = lua
    for seed in (1, 77, 99999):
        a, b = lua_list(m.canary("A", seed, 1024)), lua_list(m.canary("B", seed, 1024))
        assert len(a) == len(b) == 1024
        assert all(x != y for x, y in zip(a, b, strict=True)), "A and B must differ at every offset"
        assert all(1 <= x <= 253 for x in a + b), "no 0x00 (cleared) or 0xFF (erased) bytes"
    assert lua_list(m.canary("A", 1, 64)) != lua_list(m.canary("A", 2, 64)), "pattern must be run-specific"
    with pytest.raises(Exception, match="canary kind"):
        m.canary("C", 1, 4)


def test_watch_clean_then_single_write_detected_with_exact_offset_and_rearmed(lua):
    rt, m = lua
    io = rt.eval("make_io(0x400)")
    w = m.new_watch(io, "span", 0x01FFF800, 0x400, m.canary("A", 5, 0x400))
    assert w.arm(w) is True
    assert len(w.check(w, "boot", 1)) == 0
    io.mem[0x123] = (io.mem[0x123] + 1) % 256  # a foreign write
    found = w.check(w, "battle", 2)
    assert len(found) == 1 and found[1].off == 0x123 and found[1].got != found[1].want
    assert w.foreign_checks == 1 and w.events[1].phase == "battle"
    assert len(w.check(w, "battle", 3)) == 0, "canary is re-armed after a report, so a later write is a separate event"
    io.mem[0x10] = 0
    assert len(w.check(w, "save", 4)) == 1 and w.foreign_checks == 2


def test_same_value_write_hides_in_one_run_but_the_two_patterns_catch_it(lua):
    """A game that happens to store byte X where run A put X is invisible to A; run B's pattern differs there."""
    rt, m = lua
    caught = {}
    for kind, other in (("A", "B"), ("B", "A")):
        io = rt.eval("make_io(0x40)")
        w = m.new_watch(io, "span", 0, 0x40, m.canary(kind, 9, 0x40))
        assert w.arm(w)
        io.mem[7] = m.canary(other, 9, 0x40)[8]  # the game writes the OTHER run's pattern byte at +7
        caught[kind] = len(w.check(w, "boot", 1))
        io.write(0, m.canary(kind, 9, 0x40))
        io.mem[7] = m.canary(kind, 9, 0x40)[8]  # ...or this run's own byte: undetectable by construction
        caught[kind + "-own"] = len(w.check(w, "boot", 2))
    assert caught["A"] == 1 and caught["B"] == 1, "a write of the other pattern's value is always seen"
    assert caught["A-own"] == 0 and caught["B-own"] == 0, "documents the blind spot the second pattern closes"


def test_arm_refuses_a_write_that_does_not_stick(lua):
    rt, m = lua
    for drop, want in ((False, True), (True, False)):
        io = rt.eval(f"make_io(16, {{drop_writes={'true' if drop else 'false'}}})")
        w = m.new_watch(io, "span", 0, 16, m.canary("A", 3, 16))
        assert w.arm(w) is want
        assert (w.arm_error is not None) is (not want)


def test_known_positive_control_detects_a_counting_byte_and_a_dead_instrument_is_red(lua):
    rt, m = lua
    io = rt.eval("make_io(1)")
    count = {"n": 0}

    def alive():
        io.mem[0] = (io.mem[0] + 1) % 256  # the game increments gSystem.vblankCounter every frame

    def dead():
        count["n"] += 1  # the game never touches the byte, e.g. the wrong address

    good = m.control_known_positive(io, alive, 30, 11)
    assert good.detected is True and good.frames == 1
    io2 = rt.eval("make_io(1)")
    bad = m.control_known_positive(io2, dead, 30, 11)
    assert bad.detected is False and count["n"] == 30
    good_again = m.control_known_positive(rt.eval("make_io(1)"), lambda: None, 3, 11)
    assert good_again.detected is False  # revert-check: detection depends on a real write, not on the harness


def test_host_rewrite_control_names_exactly_the_flipped_offset_and_stale_reads_are_red(lua):
    rt, m = lua
    io = rt.eval("make_io(0x100)")
    w = m.new_watch(io, "span", 0, 0x100, m.canary("B", 4, 0x100))
    assert w.arm(w)
    ok = m.control_host_rewrite(w, 10)
    assert ok.ok is True and ok.offset == 0x80 and ok.found == 1 and ok.clean_after_restore is True
    # a stale-read instrument (reads never reflect the flip) must turn the control red
    snapshot = {i: m.canary("B", 4, 0x100)[i + 1] for i in range(0x100)}
    stale = rt.eval("make_io(0x100)")
    w2 = m.new_watch(stale, "span", 0, 0x100, m.canary("B", 4, 0x100))
    assert w2.arm(w2)
    stale.read = rt.eval("function(off, k) local r = {} for i = 1, k do r[i] = STALE[off + i - 1] end return r end")
    rt.globals().STALE = to_lua(rt, snapshot)
    assert m.control_host_rewrite(w2, 10).ok is False
    # and a clean pass after the stale instrument is replaced (revert)
    assert m.control_host_rewrite(w, 11).ok is True


def good_obs():
    return {"arm": {"itcm_size_ok": True, "armed": True, "bus_agree": True}, "known_positive": {"detected": True},
            "host_rewrite": {"ok": True}, "checks": 50, "span_foreign_total": 0,
            "phases": {p: {"verified": 100000} for p in ("boot", "overworld", "menu", "battle", "save")}, "foreign": {}}


def status_of(lua, obs):
    rt, m = lua
    rows = m.evaluate(to_lua(rt, obs))
    return {r: rows[r].status for r in "abcdefghi"}, {r: rows[r].reason for r in "abcdefghi"}


def test_evaluate_green_baseline(lua):
    statuses, _ = status_of(lua, good_obs())
    assert set(statuses.values()) == {"PASS"}


@pytest.mark.parametrize("name,edit,row,want", [
    ("foreign write during battle", lambda o: o["foreign"].update(battle=1) or o.update(span_foreign_total=1), "g", "FAIL"),
    ("foreign write during save", lambda o: o["foreign"].update(save=2) or o.update(span_foreign_total=2), "h", "FAIL"),
    ("foreign write anywhere", lambda o: o.update(span_foreign_total=1), "i", "FAIL"),
    ("battle never reached", lambda o: o["phases"]["battle"].update(verified=0), "g", "OPEN"),
    ("save never reached", lambda o: o["phases"].pop("save"), "h", "OPEN"),
    ("known-positive NOT detected", lambda o: o["known_positive"].update(detected=False), "b", "FAIL"),
    ("host rewrite control wrong", lambda o: o["host_rewrite"].update(ok=False), "c", "FAIL"),
    ("ITCM write does not stick", lambda o: o["arm"].update(arm_error="write does not stick"), "a", "FAIL"),
    ("domains disagree", lambda o: o["arm"].update(bus_agree=False), "a", "FAIL"),
    ("ITCM domain wrong size", lambda o: o["arm"].update(itcm_size_ok=False), "a", "FAIL"),
])
def test_evaluate_red_on_mutation_green_on_revert(lua, name, edit, row, want):
    obs = good_obs()
    edit(obs)
    statuses, _ = status_of(lua, obs)
    assert statuses[row] == want, (name, statuses)
    assert status_of(lua, good_obs())[0][row] == "PASS"


def test_a_missed_control_invalidates_every_phase_row_never_pass(lua):
    obs = good_obs()
    obs["known_positive"]["detected"] = False
    statuses, reasons = status_of(lua, obs)
    assert all(statuses[r] == "FAIL" for r in "bdefghi"), statuses
    assert "INVALID" in reasons["g"] and "silence proves nothing" in reasons["g"]


def test_lua_probe_compiles_under_lupa(lua):
    rt, _ = lua
    compile_chunk = rt.eval("function(s) local f, e = load(s, 'probe_gen4_mailbox'); return f ~= nil, e end")
    compiled, error = compile_chunk(SCRIPT.read_text(encoding="utf-8"))
    assert compiled, error


# ---------------------------------------------------------------------------------------------- receipt + combination
def row(status="PASS", reason=None, **extra):
    return (status, {"reason": reason, "seed": 1, "canary": "A", **extra})


def good_runs():
    a = {r: row(seed=11, canary="A") for r in ROWS}
    b = {r: row(seed=22, canary="B") for r in ROWS}
    return {"A": a, "B": b}


SPAN = gen4_mailbox_census.DEFAULT_SPAN


@pytest.mark.parametrize("name,edit,want", [
    ("one canary only", lambda r: r.pop("B"), "OPEN"),
    ("a foreign write in one run", lambda r: r["B"].update(g=row("FAIL", "foreign", seed=22)), "FAIL"),
    ("an unreached phase", lambda r: r["A"].update(h=row("OPEN", "save not reached", seed=11)), "OPEN"),
    ("same seed in both runs", lambda r: r["B"].update({k: row(seed=11, canary="B") for k in ROWS}), "FAIL"),
    ("row absent", lambda r: r["A"].pop("i"), "OPEN"),
])
def test_combine_red_on_mutation_green_on_revert(name, edit, want):
    assert combine("heartgold", good_runs(), "PASS", SPAN)["status"] == "PASS"
    runs = good_runs()
    edit(runs)
    out = combine("heartgold", runs, "PASS", SPAN)
    assert out["status"] == want and out["accepted"] is None, (name, out)
    assert combine("heartgold", good_runs(), "PASS", SPAN)["accepted"]["domain"] == "Instruction TCM"


def test_combine_never_accepts_an_address_without_a_passing_census():
    for census in ("UNPROVEN", "FAIL"):
        assert combine("heartgold", good_runs(), census, SPAN)["accepted"] is None


def test_seeds_differ_per_kind_and_run():
    assert seed_for("r1", "A") != seed_for("r1", "B") and seed_for("r1", "A") != seed_for("r2", "A")


def model_cut(title="heartgold"):
    files = {"lua/tests/probe_gen4_mailbox.lua": digest(SCRIPT)}
    cut = {"script_sha256": "1" * 64, "profile_sha256": "2" * 64, "source_head": "cut", "receipt_kind": "mailbox",
           "script": "model.lua", "module_sha256": files, "title": title, "rom_sha1": "a" * 40}
    cut["surface_sha256"] = gen4_evidence.surface_hash("mailbox", files)
    return cut


def receipt_text(cut, run_id="r", canary="A", **over):
    lines = []
    for r in ROWS:
        payload = {k: cut[k] for k in ("script_sha256", "profile_sha256", "module_sha256", "surface_sha256", "receipt_kind")}
        payload.update(title="heartgold", rom_sha1=cut["rom_sha1"], level="PHYSICAL", run_id=run_id, canary=canary, **over)
        lines.append(f"PROBE {r} PASS {json.dumps(payload)}")
    return "\n".join([*lines, "RESULT: PASS"]) + "\n"


@pytest.mark.parametrize("mutation", ["stale_module", "wrong_run", "wrong_canary", "model_level", "duplicate", "tail", "wrong_rom"])
def test_receipt_rejection_controls_red_on_mutation_green_on_revert(mutation):
    cut = model_cut()
    kw = {"title": "heartgold", "rom_sha1": cut["rom_sha1"], "run_id": "r", "cut": cut, "canary": "A"}
    assert len(parse_receipt(receipt_text(cut), **kw)) == 9
    text = receipt_text(cut)
    if mutation == "stale_module":
        text = receipt_text({**cut, "module_sha256": {"lua/tests/probe_gen4_mailbox.lua": "0" * 64}})
    elif mutation == "wrong_run":
        text = receipt_text(cut, run_id="other")
    elif mutation == "wrong_canary":
        text = receipt_text(cut, canary="B")
    elif mutation == "model_level":
        text = text.replace('"level": "PHYSICAL"', '"level": "MODEL"')
    elif mutation == "duplicate":
        text = text.replace("PROBE b ", "PROBE a ", 1)
    elif mutation == "tail":
        text = text.replace("RESULT: PASS", "RESULT: PASS\nPROBE a PASS {}")
    elif mutation == "wrong_rom":
        kw["rom_sha1"] = "b" * 40
    with pytest.raises((AssertionError, gen4_evidence.StaleEvidenceError)):
        parse_receipt(text, **kw)
    assert len(parse_receipt(receipt_text(cut), **{**kw, "rom_sha1": cut["rom_sha1"]})) == 9


# ---------------------------------------------------------------------------------------------- live collection
def emulator_pids():
    command = "Get-CimInstance Win32_Process -Filter \"Name='EmuHawk.exe'\" | Select-Object -ExpandProperty ProcessId | ConvertTo-Json -Compress"
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True, timeout=15, check=True)
    values = json.loads(result.stdout) if result.stdout.strip() else []
    return values if isinstance(values, list) else [values]


def launch_mailbox(pg, module, title, source, save, profile, base, kind, lane, cfg):
    """One fresh private lane; only this Popen's PID is ever stopped. Same host bridge as the G1 probe."""
    assert not lane.exists(), f"refusing stale run directory {lane}"
    lane.mkdir(parents=True)
    staged = module.stage_rom(source, lane)
    rom = staged.parent / "probe.nds"
    staged.rename(rom)
    battery = module.stage_save(save, lane, cfg["rom_sha1"], rom_basename=rom.name)
    module.write_nds_run_config(base, lane / "config.ini", initial_time=cfg["initial_time"], lane_saveram_dir=battery.parent, saveram_name_hint=battery.name)
    run_id = lane.parent.name + "/" + lane.name
    cfg = dict(cfg, canary=kind, seed=seed_for(run_id, kind), run_id=run_id, bridge_lane=lane.as_posix(),
               bridge_request=(lane / "bridge-request.json").as_posix(), bridge_response=(lane / "bridge-response.json").as_posix())
    from tools import gen4_routes as routes
    synth = routes.synth_setup(save) if pg.save_setup(save)["setup"] == "SYNTH" else None
    planner = routes.BridgePlanner(source, GAME[title], synth)
    cfg_path, out = lane / "mailbox.json", lane / "receipt.txt"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    shutil.copyfile(SCRIPT, lane / "probe.lua")
    env = dict(os.environ, SLINK_ROOT=str(REPO).replace("\\", "/"), SLINK_GEN4_MAILBOX_CONFIG=str(cfg_path), SLINK_GEN4_MAILBOX_OUT=str(out))
    emulator = input_file(Path(os.environ.get("SLINK_EMUHAWK", "E:/Howard/Bizhawk/EmuHawk.exe")), "EmuHawk")
    if emulator_pids():
        pytest.skip("OPEN another EmuHawk is running: the Gen 4 lane is single-owner")
    proc = subprocess.Popen([str(emulator), "--config=config.ini", "--lua=probe.lua", "rom/probe.nds"], cwd=lane, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    deadline = time.monotonic() + int(os.environ.get("SLINK_GEN4_MAILBOX_TIMEOUT", "1800"))
    seen = None
    try:
        while proc.poll() is None and time.monotonic() < deadline:
            request = Path(cfg["bridge_request"])
            if request.is_file():
                try:
                    pending = json.loads(request.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pending = None
                if pending and pending["id"] != seen:
                    seen = pending["id"]
                    try:
                        answer = {"id": seen, "route": planner.plan(pending)}
                    except (routes.RomAbsent, FileNotFoundError) as exc:
                        answer = {"id": seen, "open": str(exc)}
                    except routes.RouteError as exc:
                        answer = {"id": seen, "error": str(exc)}
                    temp = Path(cfg["bridge_response"]).with_suffix(".tmp")
                    temp.write_text(json.dumps(answer), encoding="utf-8")
                    temp.replace(cfg["bridge_response"])
            if out.is_file() and out.read_text(encoding="utf-8").splitlines()[-1:] and out.read_text(encoding="utf-8").splitlines()[-1] in {"RESULT: PASS", "RESULT: FAIL", "RESULT: OPEN"}:
                break
            time.sleep(0.25)
        assert out.is_file(), f"no terminal mailbox receipt in {lane}; exit={proc.poll()}"
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pytest.fail(f"EmuHawk did not exit gracefully after the terminal receipt: {lane}")
        return out.read_text(encoding="utf-8"), run_id
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1", reason="OPEN C1 physical mailbox watch requires SLINK_LIVE=1; one owned emulator lane")
@pytest.mark.parametrize("title", TITLES)
def test_gen4_mailbox_canary_watch(title):
    pg = importlib.import_module("tests.live.test_gen4_probe_gates")
    module = pg.fixture_module()
    pins = importlib.import_module("tools.gen4_pins")
    source = input_file(Path(os.environ.get("SLINK_GEN4_" + title.upper(), pins.default_locations().roms[title])), f"{title} ROM")
    profile = input_file(REPO / "data/games" / pg.TITLE_PACK[title] / "profile.json", f"{title} profile")
    save_env = "SLINK_GEN4_" + title.upper() + "_SAVE"
    if not os.environ.get(save_env):
        pytest.skip(f"OPEN populated played save: {save_env} unset")
    save = input_file(Path(os.environ[save_env]), f"{title} played save")
    base = input_file(Path(os.environ.get("SLINK_BIZHAWK_CONFIG", "E:/Howard/Bizhawk/config.ini")), "BizHawk base config")
    pack = json.loads(profile.read_text(encoding="utf-8"))
    artifact = pack["titles"][title]
    rom_sha1, rom_md5 = digest(source, "sha1"), digest(source, "md5")
    assert artifact["rom"]["sha1"] == rom_sha1 and artifact["rom"]["md5"] == rom_md5, "present ROM/profile mismatch"
    census = gen4_mailbox_census.census(SPAN, titles=(title,))
    census_status = census["artifacts"][title]["status"]
    assert census_status != "FAIL", f"census FAIL: {json.dumps(census['artifacts'][title]['rows'])[:600]}"
    register_mailbox_kind()
    cut = gen4_evidence.snapshot("mailbox", title, repo=REPO)
    cut["rom_sha1"] = rom_sha1
    root = Path(os.environ.get("SLINK_GEN4_MAILBOX_RUNS") or gen4_fixtures.lane_root() / "mailbox")
    assert " " not in str(root.resolve()) and "google drive" not in str(root.resolve()).lower(), "short non-Drive lane root required"
    batch = root / (title + "-" + uuid.uuid4().hex[:12])
    batch.mkdir(parents=True, exist_ok=False)
    recipes = artifact.get("route_legs", {})
    route, why = [], []
    for key in ("route", "persistence_route"):
        legs, reasons = pg.resolve_pack_route(artifact.get(key, []), recipes)
        route += legs
        why += reasons
    if why:
        pytest.skip(f"OPEN route legs unresolved: {'; '.join(why)}")
    cfg = {"title": title, "rom_sha1": rom_sha1, "rom_md5": rom_md5, "profile": str(profile).replace("\\", "/"), "requested_rate": 300,
           "initial_time": "2010-01-01T12:00:00", "boot_frames": 6000, "arm_after": 120, "check_every": int(os.environ.get("SLINK_GEN4_MAILBOX_EVERY", "30")),
           "idle_frames": 300, "span": list(SPAN), "arena": list(gen4_mailbox_census.ARENA),
           "fill": os.environ.get("SLINK_GEN4_MAILBOX_FILL", "arena"), "route": route,
           "code_sha256": cut["script_sha256"], "profile_sha256": cut["profile_sha256"], "source_head": cut["source_head"],
           "module_sha256": cut["module_sha256"], "surface_sha256": cut["surface_sha256"], "receipt_kind": cut["receipt_kind"],
           **pg.save_setup(save), **pg.scenario_input(title)}
    before = digest(save)
    runs = {}
    try:
        for kind in KINDS:
            text, run_id = launch_mailbox(pg, module, title, source, save, profile, base, kind, batch / f"canary{kind}", cfg)
            runs[kind] = parse_receipt(text, title=title, rom_sha1=rom_sha1, run_id=run_id, cut=cut, canary=kind)
        verdict = combine(title, runs, census_status, SPAN)
        verdict["census"] = {k: v["status"] for k, v in census["artifacts"][title]["rows"].items()}
        verdict["recorded_at_utc"] = datetime.datetime.now(datetime.UTC).isoformat()
        (batch / "mailbox-receipt.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")
        assert verdict["status"] != "FAIL", f"C1 FAIL {title}: {verdict['reasons']}; receipt {batch / 'mailbox-receipt.json'}"
        if verdict["status"] == "OPEN":
            pytest.skip(f"OPEN C1 {title}: {'; '.join(verdict['reasons'])}; receipt {batch / 'mailbox-receipt.json'}")
    finally:
        assert digest(save) == before, "original save was modified"


def test_live_test_skips_cleanly_without_the_environment(monkeypatch):
    monkeypatch.delenv("SLINK_LIVE", raising=False)
    mark = test_gen4_mailbox_canary_watch.pytestmark
    assert any(m.name == "skipif" and m.args and m.args[0] is True for m in mark), "live test must be skipped without SLINK_LIVE=1"
    assert copy.deepcopy(ROWS) == tuple("abcdefghi") and sys.version_info >= (3, 11)
