"""C1-8 row o: the active in-battle faint probe (lua/tests/probe_gen4_battle_faint.lua).

Offline (always): python -m pytest tests/live/test_gen4_battle_faint.py -m 'not live' -q
  receipt grammar, config/command shape (own-PID kill needle), Lua scenario table, and the FILE
  proof of every seam pin against the pinned ROM bytes (absent ROM skips by name, wrong bytes fail).
Live (the coordinator's ONE emulator lane, granted separately):
  SLINK_LIVE=1 python -m pytest tests/live/test_gen4_battle_faint.py -m live -q -rs
  Input: the C1-9 state C:/slink/g4/route/route_leg2_battle_settled.State (copied into the lane,
  never written in route/). hge: route_hge leg5 state + hge_a_OOO_630 save, lane faint_hge (env overrides).
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
LANE_ROOT = Path("C:/slink/g4/faint2")  # card C1-8D lane (earlier cards used faint / faint_hge)
LANES = {"heartgold": LANE_ROOT, "heartgold_hge": LANE_ROOT}
# SYNTH 2-mon setup (owner ruling 2026-10-01): python tools/gen4_synth_save.py party2 --profile {hgss|hge} ...
P2_SAVES = {"heartgold": Path("C:/slink/g4/saves/hg_base_26310_party2.SaveRAM"),
            "heartgold_hge": Path("C:/slink/g4/saves/hge_a_OOO_630_party2.SaveRAM")}
P2_PROFILE = {"heartgold": "hgss", "heartgold_hge": "hge"}
# the C1-9 route tool (`tools/gen4_routes.py run --save <party2> [--game hge --errand pokegear] --lane faint2 --tag p2hg|p2hge`)
# leaves <tag>_leg<N>_battle_settled.State + <tag>_leg<N>.log in the lane
P2_TAG = {"heartgold": "p2hg", "heartgold_hge": "p2hge"}
P2_SCENARIOS = ("seam_turnend_p2", "seam_ufce_bit_p2")
HGE_STATE = Path("C:/slink/g4/route_hge/route_hge_leg5_battle_settled.State")
HGE_SAVE = Path("C:/slink/g4/saves/hge_a_OOO_630.SaveRAM")
# the route log of each state must name the settled FIGHT-menu battle (title -> (RESULT regex, settled regex))
STATE_LOGS = {
    "heartgold": (r"RESULT BATTLE .*species=(?:16|PIDGEY\(16\)) level=2\b", r"settled after \d+ frames; chain .* hp=13/13 player=155"),
    "heartgold_hge": (r"RESULT BATTLE .*species=PIDGEY\(16\) level=3\b",
                      r"settled after \d+ frames; chain .* enemy=16 L3 hp=16/16 player=155"),
}
ROUTE_STATE = Path("C:/slink/g4/route/route_leg2_battle_settled.State")
ROUTE_LOG = ROUTE_STATE.with_name("route_leg2.log")
EMUHAWK = Path(os.environ.get("SLINK_EMUHAWK", "E:/Howard/Bizhawk/EmuHawk.exe"))
DEFAULT_SAVE = Path("E:/Howard/Bizhawk/NDS/SaveRAM/Pokemon - HeartGold Version (USA).SaveRAM")
PACK = {"heartgold": "gen4_hgss", "heartgold_hge": "gen4_hge"}
RECEIPT_RE = re.compile(r"^PROBE o (PASS|FAIL|OPEN) (\{.*\})$")
INITIAL_TIME = "2010-01-01T12:00:00"
# name -> kind; must equal the Lua table (test_scenario_table_matches_lua)
SCENARIOS = {"seam_turnend_p2": "primary", "seam_ufce_bit_p2": "primary",  # 2-mon replacement path (production)
             "seam_turnend": "secondary", "seam_ufce_bit": "secondary",  # one-mon whiteout
             "battle_only": "control", "party_only": "control", "poll_fightmenu": "exploratory"}
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


def check_state(state: Path, log: Path, title: str = "heartgold") -> Path:
    """The route state must be the settled FIGHT menu of the wild Pidgey battle (player's Cyndaquil).
    Absent skips by name; a present state that is not a BizHawk state or whose route log does not
    name that battle fails."""
    need(state, "C1-9 battle state")
    head = state.read_bytes()[:4]
    assert head == b"PK\x03\x04" and state.stat().st_size > 1 << 20, f"{state} is not a BizHawk state"
    text = need(log, "C1-9 route log").read_text(encoding="utf-8", errors="replace")
    result_re, settled_re = STATE_LOGS[title]
    assert re.search(result_re, text), "route log does not name the Pidgey L2 battle"
    assert re.search(settled_re, text), "route log does not show the settled FIGHT menu (Pidgey, Cyndaquil)"
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


# The end-of-turn command whose entry the S2 seam hooks. HG: command 11 (UpdateFieldConditionExtra). hge replaces
# command 9 (ServerFieldConditionCheck, `hooks:376`) with C that runs ALL end-of-turn effects, calls
# CheckIfAnyoneShouldFaint at its loop top (ServerFieldConditionCheck.c:127) and ends in TURN_END (:1944), so hge never
# dispatches commands 10/11 (live: trace 9 -> 12). The address and pin are read from the ROM's own dispatch table.
UFCE_CMD = {"heartgold": 11, "heartgold_hge": 9}
UFCE_NAME = {11: "BattleControllerPlayer_UpdateFieldConditionExtra", 9: "hge_ServerFieldConditionCheck_entry"}
CMD_TABLE = 0x0226CA90  # sPlayerBattleCommands (xMAP / hge rom.ld:710)


def seam_overrides(title: str, rom: Path) -> dict:
    """{"ufce": {addr, pin, cmd, name}} derived from the ROM table entry, never typed in."""
    cmd = UFCE_CMD[title]
    ov12, _ = rom_images(rom)
    entry = struct.unpack_from("<I", ov12.data, CMD_TABLE + 4 * cmd - ov12.ramAddress)[0]
    addr = entry & ~1
    pin = struct.unpack_from("<I", ov12.data, addr - ov12.ramAddress)[0]
    return {"ufce": {"addr": addr, "pin": pin, "cmd": cmd, "name": UFCE_NAME[cmd]}}


def check_synth(save: Path, title: str) -> dict:
    """The party2 save must carry its sidecar and match it: absent skips by name, a sidecar that does not describe
    THIS file (hash, kind, profile) fails. Returns the receipt's `synth` record (incl. the sidecar sha256)."""
    need(save, f"{title} SYNTH party2 save")
    sidecar = save.with_name(save.name + ".synth.json")
    need(sidecar, f"{title} SYNTH sidecar")
    row = json.loads(sidecar.read_text(encoding="utf-8"))
    assert row.get("schema") == "gen4-synth-v1" and row.get("kind") == "party2", f"{sidecar}: not a party2 sidecar"
    assert row.get("profile") == P2_PROFILE[title], f"{sidecar}: profile {row.get('profile')} != {P2_PROFILE[title]}"
    assert row.get("out_sha1") == g4.sha1_of(save), f"{sidecar} does not describe {save} (out_sha1 differs)"
    return {"sidecar": sidecar.as_posix(), "sidecar_sha256": digest(sidecar), "src_sha1": row.get("src_sha1"),
            "out_sha1": row["out_sha1"], "new_pid": row.get("new_pid")}


def p2_state(title: str) -> Path:
    """Newest `<tag>_leg*_battle_settled.State` the route tool left in the lane for the party2 save (env override)."""
    env = os.environ.get("SLINK_GEN4_P2_STATE_" + title.upper())
    if env:
        return Path(env)
    hits = sorted(LANE_ROOT.glob(f"{P2_TAG[title]}_leg*_battle_settled.State"), key=lambda q: q.stat().st_mtime)
    if not hits:
        pytest.skip(f"OPEN {title} party2 battle state: no {P2_TAG[title]}_leg*_battle_settled.State in {LANE_ROOT}")
    return hits[-1]


def build_config(*, title: str, rom_sha1: str, scenario: str, lane: Path, state: Path, source_head: str,
                 profile: Path, fault: str | None = None, max_frames: int = 5400,
                 seams: dict | None = None, synth: dict | None = None) -> dict:
    prof = json.loads(profile.read_text(encoding="utf-8"))["titles"][title]["profile"]
    # offsets come from the pack, never hard-coded: save header table, battle layout, gSystem (liveness counters)
    pack = {"save": prof["save"], "battle": prof["battle"], "system": prof["system"]}
    return {"pack": pack, "seams": seams or {}, "setup": "SYNTH" if synth else "NATIVE", "synth": synth, "run_id": f"{lane.parent.name}/{lane.name}", "title": title, "rom_sha1": rom_sha1,
            "scenario": scenario, "state_path": state.as_posix(), "shot_dir": lane.as_posix(),
            "requested_rate": 300, "fault": fault, "max_frames": max_frames, "move_right": True,
            "script_sha256": digest(SCRIPT), "profile_sha256": digest(profile), "source_head": source_head}


def emuhawk_command(lane: Path, rom: Path) -> list[str]:
    """ABSOLUTE lane paths: kill_our_emuhawk() matches this lane by its command line."""
    return [str(EMUHAWK), f"--config={(lane / 'bizhawk.ini').as_posix()}", f"--lua={SCRIPT.as_posix()}",
            rom.as_posix()]


def terminal(out: Path) -> bool:
    return out.is_file() and any(ln.startswith("RESULT:") for ln in out.read_text(encoding="utf-8").splitlines())


def launch(title: str, scenario: str, state: Path, rom_src: Path, save: Path, fault: str | None = None,
           synth: dict | None = None):
    assert title in PACK, title
    need(EMUHAWK, "EmuHawk")
    profile = REPO / "data/games" / PACK[title] / "profile.json"
    lane = LANES[title] / f"{title}_{scenario}{'_' + fault if fault else ''}_{time.strftime('%H%M%S')}"
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
                       source_head=head, profile=profile, fault=fault, seams=seam_overrides(title, rom), synth=synth)
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
            if terminal(out):
                break
            time.sleep(0.5)
        assert out.is_file(), f"no terminal receipt in {lane}; exit={proc.poll()}"
        status, payload = parse_receipt(out.read_text(encoding="utf-8"), title=title, rom_sha1=rom_sha1,
                                        run_id=cfg["run_id"])
        assert payload["script_sha256"] == cfg["script_sha256"], "receipt from a different script"
        assert payload["callback_errors"] == 0, f"callback faults in {lane}: {payload.get('callback_error')}"
        assert payload.get("setup") == ("SYNTH" if synth else "NATIVE"), "receipt does not disclose the setup kind"
        if synth:
            assert payload["synth"]["sidecar_sha256"] == synth["sidecar_sha256"], "receipt carries another sidecar"
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
    assert cfg["setup"] == "NATIVE" and cfg["synth"] is None
    assert {"save", "battle", "system"} <= set(cfg["pack"]) and cfg["pack"]["system"]["vblank_counter_off"] == 44
    synth = {"sidecar_sha256": "ab" * 32}
    cfg = build_config(title="heartgold", rom_sha1="ab" * 20, scenario="seam_turnend_p2", lane=tmp_path / "lane",
                       state=tmp_path / "start.State", source_head="cut", profile=profile, synth=synth)
    assert cfg["setup"] == "SYNTH" and cfg["synth"] == synth


def test_synth_party2_sidecar_absent_skips_wrong_fails_ok_binds_the_hash(tmp_path):
    save = tmp_path / "x_party2.SaveRAM"
    with pytest.raises(pytest.skip.Exception, match="OPEN heartgold SYNTH party2 save"):
        check_synth(save, "heartgold")
    save.write_bytes(b"" * 64)
    with pytest.raises(pytest.skip.Exception, match="OPEN heartgold SYNTH sidecar"):
        check_synth(save, "heartgold")
    side = save.with_name(save.name + ".synth.json")
    row = {"schema": "gen4-synth-v1", "kind": "party2", "profile": "hgss", "out_sha1": g4.sha1_of(save),
           "src_sha1": "s", "new_pid": 5}
    side.write_text(json.dumps(row), encoding="utf-8")
    got = check_synth(save, "heartgold")
    assert got["sidecar_sha256"] == digest(side) and got["out_sha1"] == row["out_sha1"]
    for patch, why in [({"out_sha1": "0" * 40}, "does not describe"), ({"profile": "hge"}, "profile"),
                       ({"kind": "other"}, "not a party2 sidecar")]:
        side.write_text(json.dumps({**row, **patch}), encoding="utf-8")
        with pytest.raises(AssertionError, match=why):
            check_synth(save, "heartgold")


def test_real_party2_saves_and_sidecars_if_present():
    for title, save in P2_SAVES.items():
        if not save.is_file():
            pytest.skip(f"OPEN {title} party2 save absent: {save}")
        assert check_synth(save, title)["out_sha1"] == g4.sha1_of(save)


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
    # TurnEnd's prologue bytes 38 b5 are the halfword 0xB538 = PUSH {r3,r4,r5,lr} (r3-r5 from the low byte 0x38)
    hw = struct.unpack_from("<H", ov12.data, off)[0]
    assert hw >> 8 == 0xB5 and [r for r in range(8) if hw >> r & 1] == [3, 4, 5]
    # ov12_0224D540 clears/sets the "replacement needed" flag at ctx+0x13C: movs r1,#0x4f ; ... ; lsls r1,r1,#2
    d540 = 0x0224D540 - ov12.ramAddress
    assert struct.unpack_from("<H", ov12.data, d540 + 0x4A)[0] == 0x214F
    assert struct.unpack_from("<H", ov12.data, d540 + 0x4E)[0] == 0x0089 and m.L.ctx_repl == 0x4F << 2
    table = 0x0226CA90
    assert word(table + 4 * 11) == m.SEAMS.ufce.addr | 1 and word(table + 4 * 12) == turn_end | 1
    assert word(table + 4 * 5) == 0x02248848 | 1  # SelectionScreenInput: the idle-at-menu command
    assert word(table + 4 * 10) == 0x02249CC4 | 1


# ---------------------------------------------------------------- live (one owned emulator lane)
def _live_inputs(title: str, p2: bool = False):
    if p2:
        save = P2_SAVES[title]
        synth = check_synth(save, title)
        state = p2_state(title)
        log = state.with_name(state.name.replace("_battle_settled.State", ".log"))
        need(state, f"{title} party2 battle state")
        text = need(log, f"{title} party2 route log").read_text(encoding="utf-8", errors="replace")
        assert re.search(r"RESULT BATTLE\b", text) and re.search(r"settled after \d+ frames", text), \
            f"{log} does not show a settled battle"
        rom = gen4_pins.default_locations().roms[title]
        return state, need(rom, f"{title} ROM"), save, synth
    if title == "heartgold":
        state = check_state(ROUTE_STATE, ROUTE_LOG)
        save = need(Path(os.environ.get("SLINK_GEN4_HEARTGOLD_SAVE", DEFAULT_SAVE)), "heartgold played save")
    else:
        state_path = Path(os.environ.get("SLINK_GEN4_HGE_FAINT_STATE", HGE_STATE))
        log = state_path.with_name(state_path.name.replace("_battle_settled.State", ".log"))
        state = check_state(state_path, log, title)
        save = need(Path(os.environ.get("SLINK_GEN4_HEARTGOLD_HGE_SAVE", HGE_SAVE)), "hge played save")
    rom = gen4_pins.default_locations().roms[title]
    return state, need(rom, f"{title} ROM"), save, None


live = pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                          reason="OPEN physical probe: SLINK_LIVE=1 and the coordinator's emulator lane")


@pytest.mark.live
@live
@pytest.mark.parametrize("title", PACK)
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_live_row_o_scenario(title, scenario):
    state, rom, save, synth = _live_inputs(title, p2=scenario in P2_SCENARIOS)
    status, payload, lane, out = launch(title, scenario, state, rom, save, synth=synth)
    kind = SCENARIOS[scenario]
    assert status != "FAIL", f"{scenario} FAIL: {payload.get('reason')} ({lane})"
    if kind == "control":
        assert status == "PASS", f"control {scenario} did not go red as required: {payload.get('reason')}"
    if status == "OPEN":
        pytest.skip(f"OPEN {scenario}: {payload.get('reason')} ({out})")
    if kind in ("primary", "secondary"):  # the receipts row_o() may accept as the physical row
        shutil.copyfile(out, LANES[title] / f"row_o_{title}_{scenario}.txt")


@pytest.mark.live
@live
@pytest.mark.parametrize("fault", FAULTS)
def test_live_instrument_controls_go_red_when_a_check_is_disabled(fault):
    """Revert-test on the real memory: disabling ONE guard/readback check must turn the run FAIL
    with that control named, before any game memory is written."""
    state, rom, save, _ = _live_inputs("heartgold")
    status, payload, lane, _ = launch("heartgold", "seam_turnend", state, rom, save, fault=fault)
    assert status == "FAIL" and FAULTS[fault] in payload["reason"], (status, payload.get("reason"))
    assert payload["observation"].get("write") is None, "a write happened despite red instrument controls"


@pytest.mark.parametrize("title", ["heartgold", "heartgold_hge"])
def test_s2_seam_is_derived_from_the_rom_dispatch_table(title):
    """FILE: HG derives the Lua default (command 11); hge derives its command-9 entry, the vanilla address
    patched by hooks:376 (a trampoline, so its pin differs from the vanilla UFCE bytes)."""
    rom = gen4_pins.default_locations().roms[title]
    if not rom.is_file():
        pytest.skip(f"OPEN {title} ROM absent: {rom}")
    seam = seam_overrides(title, rom)["ufce"]
    m = lua_api()
    if title == "heartgold":
        assert (seam["addr"], seam["pin"], seam["cmd"]) == (m.SEAMS.ufce.addr, m.SEAMS.ufce.pin, m.SEAMS.ufce.cmd)
    else:
        assert (seam["addr"], seam["cmd"]) == (0x022494DC, 9)
        assert seam["pin"] != m.SEAMS.ufce.pin  # replaced entry bytes, not the vanilla function
