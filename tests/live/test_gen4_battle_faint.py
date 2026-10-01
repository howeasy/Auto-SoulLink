"""C1-8 row o: the active in-battle faint probe (lua/tests/probe_gen4_battle_faint.lua).

Offline (always): python -m pytest tests/live/test_gen4_battle_faint.py -m 'not live' -q
  receipt grammar, config/command shape (own-PID kill needle), Lua scenario table, and the FILE
  proof of every seam pin against the pinned ROM bytes (absent ROM skips by name, wrong bytes fail).
Live (the coordinator's ONE emulator lane, granted separately):
  SLINK_LIVE=1 python -m pytest tests/live/test_gen4_battle_faint.py -m live -q -rs
  Input: the C1-9 state C:/slink/g4/route/route_leg2_battle_settled.State (copied into the lane,
  never written in route/). hge needs SLINK_GEN4_HGE_FAINT_STATE + SLINK_GEN4_HEARTGOLD_HGE_SAVE.
No offline test launches an emulator. A scenario that cannot reach its oracle is a NAMED SKIP (OPEN),
never a pass. Never kill by image name: only this Popen's PID and this lane's own EmuHawk."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import time
from pathlib import Path

import pytest

from tools import gen4_fixtures as g4, gen4_pins

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "lua/tests/probe_gen4_battle_faint.lua"
LANE_ROOT = Path("C:/slink/g4/faint")
ROUTE_STATE = Path("C:/slink/g4/route/route_leg2_battle_settled.State")
ROUTE_LOG = ROUTE_STATE.with_name("route_leg2.log")
EMUHAWK = Path(os.environ.get("SLINK_EMUHAWK", "E:/Howard/Bizhawk/EmuHawk.exe"))
DEFAULT_SAVE = Path("E:/Howard/Bizhawk/NDS/SaveRAM/Pokemon - HeartGold Version (USA).SaveRAM")
PACK = {"heartgold": "gen4_hgss", "heartgold_hge": "gen4_hge"}
RECEIPT_RE = re.compile(r"^PROBE o (PASS|FAIL|OPEN) (\{.*\})$")
INITIAL_TIME = "2010-01-01T12:00:00"
# name -> kind; must equal the Lua table (test_scenario_table_matches_lua)
SCENARIOS = {"seam_turnend": "primary", "battle_only": "control", "party_only": "control",
             "seam_ufce_bit": "primary", "poll_fightmenu": "exploratory"}
FAULTS = {"identity": "wrong_pid_accepted", "verify_party": "battle_only_not_detected",
          "verify_high": "two_byte_stale_high_not_detected", "locked": "locked_accepted",
          "slot": "wrong_slot_accepted"}


def digest(path: Path, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def need(path: Path, name: str) -> Path:
    if not path.is_file():
        pytest.skip(f"OPEN {name}: absent input {path}")
    return path


def check_state(state: Path, log: Path) -> Path:
    """The C1-9 state must be the FIGHT menu of the wild Pidgey L2 battle (player's Cyndaquil).
    Absent skips by name; a present state that is not a BizHawk state or whose route log does not
    name that battle fails."""
    need(state, "C1-9 battle state")
    head = state.read_bytes()[:4]
    assert head == b"PK\x03\x04" and state.stat().st_size > 1 << 20, f"{state} is not a BizHawk state"
    text = need(log, "C1-9 route log").read_text(encoding="utf-8", errors="replace")
    assert re.search(r"RESULT BATTLE species=16 level=2\b", text), "route log does not name the Pidgey L2 battle"
    assert re.search(r"settled after \d+ frames; chain .* hp=13/13 player=155", text), \
        "route log does not show the settled FIGHT menu (Pidgey 13/13, Cyndaquil)"
    return state


def parse_receipt(text: str, *, title: str, rom_sha1: str, run_id: str | None = None) -> tuple[str, dict]:
    """Same grammar as test_gen4_probe_gates.row_o(): one PROBE o row + one terminal RESULT."""
    lines = text.splitlines()
    assert len(lines) == 2, f"expected one PROBE row and one RESULT line, got {len(lines)}"
    match = RECEIPT_RE.fullmatch(lines[0])
    assert match, f"malformed receipt line: {lines[0][:160]}"
    status, payload = match.group(1), json.loads(match.group(2))
    assert lines[1] == f"RESULT: {status}", "terminal status contradicts the row"
    assert payload["level"] == "PHYSICAL" and payload["producer"] == "C1-8", "wrong level/producer"
    assert payload["title"] == title and payload["rom_sha1"].lower() == rom_sha1.lower(), "wrong artifact"
    if run_id is not None:
        assert payload["run_id"] == run_id, "stale/wrong-run receipt"
    if status == "PASS":
        assert payload.get("oracle") and payload.get("negative_control"), "PASS lacks oracle/red controls"
    return status, payload


def build_config(*, title: str, rom_sha1: str, scenario: str, lane: Path, state: Path, source_head: str,
                 profile: Path, fault: str | None = None, max_frames: int = 5400) -> dict:
    return {"run_id": f"{lane.parent.name}/{lane.name}", "title": title, "rom_sha1": rom_sha1,
            "scenario": scenario, "state_path": state.as_posix(), "shot_dir": lane.as_posix(),
            "requested_rate": 300, "fault": fault, "max_frames": max_frames, "move_right": True,
            "script_sha256": digest(SCRIPT), "profile_sha256": digest(profile), "source_head": source_head}


def emuhawk_command(lane: Path, rom: Path) -> list[str]:
    """ABSOLUTE lane paths: kill_our_emuhawk() matches this lane by its command line."""
    return [str(EMUHAWK), f"--config={(lane / 'bizhawk.ini').as_posix()}", f"--lua={SCRIPT.as_posix()}",
            rom.as_posix()]


def terminal(out: Path) -> bool:
    return out.is_file() and any(ln.startswith("RESULT:") for ln in out.read_text(encoding="utf-8").splitlines())


def launch(title: str, scenario: str, state: Path, rom_src: Path, save: Path, fault: str | None = None):
    assert title in PACK, title
    need(EMUHAWK, "EmuHawk")
    profile = REPO / "data/games" / PACK[title] / "profile.json"
    lane = LANE_ROOT / f"{title}_{scenario}{'_' + fault if fault else ''}_{time.strftime('%H%M%S')}"
    assert not lane.exists(), f"refusing stale run directory {lane}"
    lane.mkdir(parents=True)
    rom = g4.stage_rom(rom_src, lane)
    rom_sha1 = g4.sha1_of(rom)
    assert rom_sha1 == gen4_pins.ROM_SPECS[title][0], "ROM is not the pinned build for this title"
    g4.stage_save(save, lane, rom_sha1, rom_basename=rom.name)
    g4.write_nds_run_config(g4.BIZHAWK_CONFIG, lane / "bizhawk.ini", initial_time=INITIAL_TIME,
                            lane_saveram_dir=lane / "SaveRAM")
    lane_state = lane / "start.State"
    shutil.copyfile(state, lane_state)  # route/ is never written, nor read by the emulator
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    cfg = build_config(title=title, rom_sha1=rom_sha1, scenario=scenario, lane=lane, state=lane_state,
                       source_head=head, profile=profile, fault=fault)
    (lane / "probe.json").write_text(json.dumps(cfg), encoding="utf-8")
    out = lane / "receipt.txt"
    env = dict(os.environ, SLINK_ROOT=REPO.as_posix(), SLINK_GEN4_FAINT_CONFIG=(lane / "probe.json").as_posix(),
               SLINK_GEN4_FAINT_OUT=out.as_posix())
    proc = subprocess.Popen(emuhawk_command(lane, rom), cwd=lane, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    deadline = time.monotonic() + int(os.environ.get("SLINK_GEN4_FAINT_TIMEOUT", "900"))
    try:
        while proc.poll() is None and time.monotonic() < deadline:
            if out.is_file() and out.read_text(encoding="utf-8").rstrip().splitlines()[-1:][0:1] and \
                    out.read_text(encoding="utf-8").splitlines()[-1].startswith("RESULT:"):
                break
            time.sleep(0.5)
        assert out.is_file(), f"no terminal receipt in {lane}; exit={proc.poll()}"
        status, payload = parse_receipt(out.read_text(encoding="utf-8"), title=title, rom_sha1=rom_sha1,
                                        run_id=cfg["run_id"])
        assert payload["script_sha256"] == cfg["script_sha256"], "receipt from a different script"
        assert payload["callback_errors"] == 0, f"callback faults in {lane}: {payload.get('callback_error')}"
        return status, payload, lane, out
    finally:
        if proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        g4.kill_our_emuhawk(lane)  # this lane's own PIDs only


# ---------------------------------------------------------------- offline
def good_payload(**kw):
    p = {"level": "PHYSICAL", "producer": "C1-8", "title": "heartgold", "rom_sha1": "ab" * 20,
         "run_id": "faint/x", "oracle": "game result byte", "negative_control": {"battle_only": {}}}
    p.update(kw)
    return p


def test_receipt_grammar_accepts_row_o_and_rejects_neighbours():
    row = "PROBE o PASS " + json.dumps(good_payload())
    assert parse_receipt(row + "\nRESULT: PASS\n", title="heartgold", rom_sha1="ab" * 20)[0] == "PASS"
    for text, why in [
        (row + "\nRESULT: OPEN\n", "contradicts"),
        (row.replace("PROBE o", "PROBE n") + "\nRESULT: PASS\n", "malformed"),
        (row + "\n" + row + "\nRESULT: PASS\n", "expected one"),
        ("PROBE o PASS " + json.dumps(good_payload(producer="other")) + "\nRESULT: PASS\n", "producer"),
        ("PROBE o PASS " + json.dumps(good_payload(negative_control=None)) + "\nRESULT: PASS\n", "controls"),
        ("PROBE o PASS " + json.dumps(good_payload(level="MODEL")) + "\nRESULT: PASS\n", "level"),
    ]:
        with pytest.raises(AssertionError, match=why):
            parse_receipt(text, title="heartgold", rom_sha1="ab" * 20)
    with pytest.raises(AssertionError, match="wrong-run"):
        parse_receipt(row + "\nRESULT: PASS\n", title="heartgold", rom_sha1="ab" * 20, run_id="other")


def test_state_input_absent_skips_present_wrong_fails(tmp_path):
    state, log = tmp_path / "s.State", tmp_path / "route.log"
    with pytest.raises(pytest.skip.Exception, match="OPEN C1-9 battle state"):
        check_state(state, log)
    state.write_bytes(b"not a zip" * 1000)
    with pytest.raises(AssertionError, match="not a BizHawk state"):
        check_state(state, log)
    state.write_bytes(b"PK\x03\x04" + b"\0" * (1 << 20))
    with pytest.raises(pytest.skip.Exception, match="OPEN C1-9 route log"):
        check_state(state, log)
    log.write_text("RESULT BATTLE species=19 level=3 map=33", encoding="utf-8")
    with pytest.raises(AssertionError, match="Pidgey L2"):
        check_state(state, log)
    log.write_text("settled after 900 frames; chain fs=1 ovy=12 enemy=16 L2 hp=13/13 player=155\n"
                   "RESULT BATTLE species=16 level=2 map=33 x=664 y=404", encoding="utf-8")
    assert check_state(state, log) == state


def test_command_names_the_lane_so_only_our_emuhawk_matches(tmp_path):
    lane, other = tmp_path / "lane_a", tmp_path / "lane_b"
    rom = lane / "rom" / "hg.nds"
    cmd = emuhawk_command(lane, rom)
    assert all(not a.startswith("--config=bizhawk.ini") for a in cmd)
    procs = [{"ProcessId": 1, "CommandLine": " ".join(cmd)},
             {"ProcessId": 2, "CommandLine": " ".join(emuhawk_command(other, other / "rom" / "hg.nds"))},
             {"ProcessId": 3, "CommandLine": None}]
    assert g4.our_emuhawk_pids(procs, lane) == [1]


def test_config_binds_run_identity_and_scripts(tmp_path):
    profile = REPO / "data/games/gen4_hgss/profile.json"
    cfg = build_config(title="heartgold", rom_sha1="ab" * 20, scenario="seam_turnend", lane=tmp_path / "lane",
                       state=tmp_path / "start.State", source_head="cut", profile=profile, fault="identity")
    assert cfg["scenario"] == "seam_turnend" and cfg["fault"] == "identity" and cfg["requested_rate"] == 300
    assert cfg["script_sha256"] == digest(SCRIPT) and cfg["profile_sha256"] == digest(profile)
    assert cfg["run_id"] == f"{tmp_path.name}/lane"


def lua_api():
    lupa = pytest.importorskip("lupa")
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.globals().SLINK_GEN4_FAINT_TEST = True
    return rt.execute(SCRIPT.read_text(encoding="utf-8"))


def test_scenario_table_matches_lua():
    m = lua_api()
    assert {k: v.kind for k, v in m.SCENARIOS.items()} == SCENARIOS
    assert set(FAULTS) >= {"identity", "verify_party", "verify_high", "locked", "slot"}


def thumb_bl_target(data: bytes, off: int, addr: int) -> int:
    hi, lo = struct.unpack_from("<HH", data, off)
    assert hi >> 11 == 0b11110 and lo >> 11 == 0b11111, "not a Thumb BL pair"
    rel = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
    if rel & 0x400000:
        rel -= 0x800000
    return addr + 4 + rel


def rom_images(path: Path):
    ndspy_rom = pytest.importorskip("ndspy.rom")
    rom = ndspy_rom.NintendoDSRom.fromFile(str(path))
    ov12 = rom.loadArm9Overlays()[12]
    try:
        arm9 = (rom.loadArm9().sections[0].ramAddress, rom.loadArm9().sections[0].data)
    except ValueError:  # hge: ndspy mis-detects compression on the expanded arm9
        arm9 = (rom.arm9RamAddress, bytes(rom.arm9))
    return ov12, arm9


@pytest.mark.parametrize("title", ["heartgold", "heartgold_hge"])
def test_seam_pins_and_flow_hold_in_the_pinned_rom_bytes(title):
    """FILE: the pins in the Lua are the ROM's own bytes; the seam sits before the sweeps; the
    controller dispatch table sends commands 11 and 12 to the pinned functions (both builds)."""
    locations = gen4_pins.default_locations()
    rom = locations.roms[title]
    if not rom.is_file():
        pytest.skip(f"OPEN {title} ROM absent: {rom}")
    assert g4.sha1_of(rom) == gen4_pins.ROM_SPECS[title][0], f"{title} ROM is not the pinned build"
    m = lua_api()
    ov12, (arm9_base, arm9) = rom_images(rom)
    assert ov12.ramAddress == 0x022378C0

    def word(addr):
        if addr >= ov12.ramAddress and addr + 4 <= ov12.ramAddress + len(ov12.data):
            return struct.unpack_from("<I", ov12.data, addr - ov12.ramAddress)[0]
        return struct.unpack_from("<I", arm9, addr - arm9_base)[0]

    for spec in list(m.SEAMS.values()) + list(m.OBS.values()):
        assert word(spec.addr) == spec.pin, f"{spec.name} @{spec.addr:#x} pin differs from the ROM"
    turn_end = m.SEAMS.turnend.addr
    off = turn_end - ov12.ramAddress
    # TurnEnd = DD18 (EXP) -> D7EC (win/lose) -> D540 (replacement): the seam is BEFORE all three
    targets = [thumb_bl_target(ov12.data, off + o, turn_end + o) for o in (0x0C, 0x18, 0x24)]
    assert targets == [0x0224DD18, 0x0224D7EC, 0x0224D540]
    table = 0x0226CA90
    assert word(table + 4 * 11) == m.SEAMS.ufce.addr | 1 and word(table + 4 * 12) == turn_end | 1
    assert word(table + 4 * 5) == 0x02248848 | 1  # SelectionScreenInput: the idle-at-menu command
    assert word(table + 4 * 10) == 0x02249CC4 | 1


# ---------------------------------------------------------------- live (one owned emulator lane)
def _live_inputs(title: str):
    if title == "heartgold":
        state = check_state(ROUTE_STATE, ROUTE_LOG)
        save = need(Path(os.environ.get("SLINK_GEN4_HEARTGOLD_SAVE", DEFAULT_SAVE)), "heartgold played save")
    else:
        if not os.environ.get("SLINK_GEN4_HGE_FAINT_STATE"):
            pytest.skip("OPEN hge: no hge FIGHT-menu state (SLINK_GEN4_HGE_FAINT_STATE unset); "
                        "the hge seam is proven by FILE bytes only")
        state = need(Path(os.environ["SLINK_GEN4_HGE_FAINT_STATE"]), "hge battle state")
        save_env = os.environ.get("SLINK_GEN4_HEARTGOLD_HGE_SAVE")
        if not save_env:
            pytest.skip("OPEN hge: SLINK_GEN4_HEARTGOLD_HGE_SAVE unset")
        save = need(Path(save_env), "hge played save")
    rom = gen4_pins.default_locations().roms[title]
    return state, need(rom, f"{title} ROM"), save


live = pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                          reason="OPEN physical probe: SLINK_LIVE=1 and the coordinator's emulator lane")


@pytest.mark.live
@live
@pytest.mark.parametrize("title", PACK)
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_live_row_o_scenario(title, scenario):
    state, rom, save = _live_inputs(title)
    status, payload, lane, out = launch(title, scenario, state, rom, save)
    kind = SCENARIOS[scenario]
    assert status != "FAIL", f"{scenario} FAIL: {payload.get('reason')} ({lane})"
    if kind == "control":
        assert status == "PASS", f"control {scenario} did not go red as required: {payload.get('reason')}"
    if status == "OPEN":
        pytest.skip(f"OPEN {scenario}: {payload.get('reason')} ({out})")
    if kind == "primary":  # the only receipt row_o() will accept as the physical row
        shutil.copyfile(out, LANE_ROOT / f"row_o_{title}_{scenario}.txt")


@pytest.mark.live
@live
@pytest.mark.parametrize("fault", FAULTS)
def test_live_instrument_controls_go_red_when_a_check_is_disabled(fault):
    """Revert-test on the real memory: disabling ONE guard/readback check must turn the run FAIL
    with that control named, before any game memory is written."""
    state, rom, save = _live_inputs("heartgold")
    status, payload, lane, _ = launch("heartgold", "seam_turnend", state, rom, save, fault=fault)
    assert status == "FAIL" and FAULTS[fault] in payload["reason"], (status, payload.get("reason"))
    assert payload["observation"].get("write") is None, "a write happened despite red instrument controls"
