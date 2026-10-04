"""C1-8 row o: the active in-battle faint probe (lua/tests/probe_gen4_battle_faint.lua).

Offline (always): python -m pytest tests/live/test_gen4_battle_faint.py -m 'not live' -q
  receipt grammar, config/command shape (own-PID kill needle), Lua scenario table, and the FILE
  proof of every seam pin against the pinned ROM bytes (absent ROM skips by name, wrong bytes fail).

  launch() binds the staged state to the staged save before it stages anything: a diagnostic state
  through SLINK_GEN4_STATE_MANIFEST_<TITLE>, a route-CLI state through the operator-recorded
  SLINK_GEN4_SOURCE_SAVE_SHA256_<TITLE>. A state carries its own SRAM, so a state/save pairing that
  nothing produced is a named refusal, not a run.
Live (the coordinator's ONE emulator lane, granted separately):
  SLINK_LIVE=1 python -m pytest tests/live/test_gen4_battle_faint.py -m live -q -rs
  Input: the C1-9 state <LANE_ROOT>/route/route_leg2_battle_settled.State (copied into the lane,
  never written in route/). hge: route_hge leg5 state + hge_a_OOO_630 save, lane faint_hge (env overrides).
No offline test launches an emulator. A scenario that cannot reach its oracle is a NAMED SKIP (OPEN),
never a pass. Never kill by image name: only this Popen's PID and this lane's own EmuHawk."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import shutil
import struct
import subprocess
import time
from pathlib import Path

import pytest

from tests.unit.test_gen4_evidence import model_surface  # noqa: F401
from tools import gen4_diag, gen4_evidence, gen4_fixtures as g4, gen4_pins

pytestmark = pytest.mark.usefixtures("model_surface")

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "lua/tests/probe_gen4_battle_faint.lua"
LANE_ROOT = g4.lane_root() / "faint2"  # card C1-8D lane (earlier cards used faint / faint_hge)
LANES = {"heartgold": LANE_ROOT, "heartgold_hge": LANE_ROOT, "soulsilver": LANE_ROOT}
# SYNTH 2-mon setup (owner ruling 2026-10-01): python tools/gen4_synth_save.py party2 --profile {hgss|hge} ...
P2_SAVES = {"heartgold": g4.lane_root() / "saves" / "hg_base_26310_party2.SaveRAM",
            "heartgold_hge": g4.lane_root() / "saves" / "hge_a_OOO_630_party2.SaveRAM",
            "soulsilver": g4.lane_root() / "g1inputs-c935-1015/ss_p2.SaveRAM"}
P2_PROFILE = {"heartgold": "hgss", "heartgold_hge": "hge", "soulsilver": "hgss"}
# the C1-9 route tool (`tools/gen4_routes.py run --save <party2> [--game hge --errand pokegear] --lane faint2 --tag p2hg|p2hge`)
# leaves <tag>_leg<N>_battle_settled.State + <tag>_leg<N>.log in the lane
P2_TAG = {"heartgold": "p2hg", "heartgold_hge": "p2hge", "soulsilver": "p2ss"}
P2_SCENARIOS = ("seam_turnend_p2", "seam_ufce_bit_p2")
HGE_STATE = g4.lane_root() / "route_hge" / "route_hge_leg5_battle_settled.State"
HGE_SAVE = g4.lane_root() / "saves" / "hge_a_OOO_630.SaveRAM"
# the route log of each state must name the settled FIGHT-menu battle (title -> (RESULT regex, settled regex))
STATE_LOGS = {
    "heartgold": (r"RESULT BATTLE .*species=(?:16|PIDGEY\(16\)) level=2\b", r"settled after \d+ frames; chain .* hp=13/13 player=155"),
    "heartgold_hge": (r"RESULT BATTLE .*species=PIDGEY\(16\) level=3\b",
                      r"settled after \d+ frames; chain .* enemy=16 L3 hp=16/16 player=155"),
    "soulsilver": (r"RESULT BATTLE\b", r"settled after \d+ frames; chain .*hp=\d+/\d+.*player=\d+"),
}
ROUTE_STATE = g4.lane_root() / "route" / "route_leg2_battle_settled.State"
ROUTE_LOG = ROUTE_STATE.with_name("route_leg2.log")
EMUHAWK = Path(os.environ.get("SLINK_EMUHAWK", "E:/Howard/Bizhawk/EmuHawk.exe"))
DEFAULT_SAVE = Path("E:/Howard/Bizhawk/NDS/SaveRAM/Pokemon - HeartGold Version (USA).SaveRAM")
PACK = {"heartgold": "gen4_hgss", "heartgold_hge": "gen4_hge", "soulsilver": "gen4_hgss"}
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

# --- state/save provenance ------------------------------------------------------------------
# A BizHawk state carries its own SRAM: loading one over a DIFFERENT battery runs the state's world
# while the staged save -- and every receipt naming it -- describes another one. Nothing here decodes
# the state's SRAM. Exactly two honest sources bind the two files, and nothing else passes:
#   (a) a diagnostic-produced state: tools/gen4_diag.check_state_manifest reviews the manifest that
#       recorded the save_sha256 that diagnostic ran from; it must equal sha256(the staged save);
#   (b) a route-CLI-produced state (the route lane leaves no manifest): the operator records the
#       producer save sha256 from the route lane; it must equal sha256(the staged save).
# Quoting a hash does not pair anything by itself: the recorded value is compared against the save
# staged for THIS run, so a retained state cannot be re-labelled as another scenario's input.
# sha256(this save) IS sha256(the staged copy): g4.stage_save copies the battery verbatim and verifies the
# copy's sha1 against the source (tools/gen4_fixtures.py:204-206), so hashing the source binds the bytes
# BizHawk will load.
MANIFEST_ENV = "SLINK_GEN4_STATE_MANIFEST_{}"
SOURCE_SAVE_ENV = "SLINK_GEN4_SOURCE_SAVE_SHA256_{}"


class StateSaveProvenanceError(AssertionError):
    """Named refusal: the state was not bound to the save this run stages."""


def _sha256(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def state_save_binding(state: Path, save: Path, *, title: str, manifest=None,
                       source_save_sha256=None) -> dict:
    """Require the state to have been produced FROM `save`; return the record the config discloses.

    Both sources are producer records, neither a decode of the state: a diagnostic manifest reviewed
    by gen4_diag.check_state_manifest (its save_sha256 must be this save), or a route-lane sha256 the
    operator recorded. A manifest wins when both are offered. Raises StateSaveProvenanceError naming
    which of the two failed; an absent state/save is a named OPEN skip, as everywhere here.
    """
    state = need(Path(state), "state/save provenance state")
    save = need(Path(save), "state/save provenance save")
    asked = manifest if manifest is not None else os.environ.get(MANIFEST_ENV.format(title.upper()))
    recorded = source_save_sha256 or os.environ.get(SOURCE_SAVE_ENV.format(title.upper())) or None
    if asked:
        origin = "diagnostic manifest"
        try:
            gen4_diag.check_state_manifest(state, Path(asked), digest(state))
            recorded = json.loads(Path(asked).read_text(encoding="utf-8")).get("save_sha256")
        except (AssertionError, KeyError, TypeError, ValueError, OSError) as exc:
            raise StateSaveProvenanceError(f"unbound state: {asked} does not review {state.name} ({exc})") from exc
    elif recorded:
        origin = "recorded route save sha256"
    else:
        raise StateSaveProvenanceError(
            f"no state/save provenance: pass manifest= or set {MANIFEST_ENV.format(title.upper())} for a "
            f"diagnostic state, or source_save_sha256= / {SOURCE_SAVE_ENV.format(title.upper())} for a route state")
    if not _sha256(recorded):
        raise StateSaveProvenanceError(f"no state/save provenance: {origin} records no producer save sha256")
    staged = digest(save)
    if recorded != staged:
        raise StateSaveProvenanceError(
            f"state/save provenance mismatch: {origin} save_sha256 {recorded} != staged save {staged} ({save.name})")
    return {"state_sha256": digest(state), "state_save_sha256": staged,
            "state_binding": f"{origin} (not a state decode)"}


def state_save_record(state_save: dict | None) -> dict:
    """The provenance keys the run's config discloses (tools/gen4_diag.py records the same three)."""
    binding = state_save or {}
    return {"state_sha256": binding.get("state_sha256"), "state_save_sha256": binding.get("state_save_sha256"),
            "state_binding": binding.get("state_binding")}


# The two producer records state_save_binding accepts, and the wire kind each discloses. The receipt
# echo in lua/tests/probe_gen4_battle_faint.lua classifies the same two origins from cfg.state_binding
# (M.binding_kind); an unrecognised origin has no kind, so it never passes as a route record.
BINDING_KINDS = {"diagnostic manifest": "diag_manifest", "recorded route save sha256": "route_recorded"}


def binding_kind(state_binding: str | None) -> str | None:
    for origin, kind in BINDING_KINDS.items():
        if isinstance(state_binding, str) and state_binding.startswith(origin):
            return kind
    return None


def check_receipt_binding(payload: dict, cfg: dict) -> None:
    """A receipt must disclose the state/save provenance ITS OWN run bound: the staged battery's sha256,
    the binding record, and which producer record paired them. Nothing inside the state file carries that
    pairing, so a receipt that omits or misreports it is not evidence for the run that produced it --
    refused here, beside the setup/sidecar disclosures."""
    assert payload.get("state_save_sha256") == cfg["state_save_sha256"], \
        "receipt does not disclose this run's bound state_save_sha256"
    assert payload.get("state_binding") == cfg["state_binding"], "receipt carries another state binding"
    assert payload.get("state_binding_kind") == binding_kind(cfg["state_binding"]), \
        "receipt misreports the state/save binding kind"


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


StaleReceiptError = gen4_evidence.StaleEvidenceError


def head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()


# Every file the probe `dofile`s (test_every_probe_dofile_is_bound greps the script and fails on an unbound one).
MODULES = ("lua/json_codec.lua",)


def module_digests(title="heartgold") -> dict[str, str]:
    return gen4_evidence.snapshot("faint", title, repo=REPO)["module_sha256"]


def current_cut(title: str) -> dict:
    """The cut a receipt must carry to be consumed: this HEAD, this probe script file, this title's pack profile, the
    sha256 of every module the probe dofiles, and the pinned ROM sha1 for the title."""
    return {**gen4_evidence.snapshot("faint", title, repo=REPO), "rom_sha1": gen4_pins.ROM_SPECS[title][0]}


def bind_cut(payload: dict, expected_cut: dict) -> None:
    gen4_evidence.bind(payload, expected_cut, title=expected_cut["title"], rom_sha1=expected_cut["rom_sha1"])


def consume_receipt(text: str, *, title: str, rom_sha1: str, run_id: str | None = None,
                    expected_cut: dict | None = None) -> tuple[str, dict]:
    """The ONE way this wrapper (and anything that reads a row o file such as SLINK_GEN4_ROW_O) consumes a receipt:
    refuse source_head != HEAD or script/profile sha256 != the current files BEFORE anything else (STALE outranks
    PASS), then the grammar checks. Mirrors gates.perf_f in test_gen4_probe_gates.py."""
    expected_cut = expected_cut or current_cut(title)
    lines = text.splitlines()
    assert lines, "empty receipt"
    match = RECEIPT_RE.fullmatch(lines[0])
    assert match, f"malformed receipt line: {lines[0][:160]}"
    bind_cut(json.loads(match.group(2)), expected_cut)
    return parse_receipt(text, title=title, rom_sha1=rom_sha1, run_id=run_id)


def receipt_verdict(path: Path, *, title: str, rom_sha1: str, expected_cut: dict | None = None) -> tuple[str, str]:
    """A file's verdict as a consumer sees it: ("STALE", why) for another cut, else (PASS|FAIL|OPEN, reason)."""
    try:
        status, payload = consume_receipt(path.read_text(encoding="utf-8"), title=title, rom_sha1=rom_sha1,
                                          expected_cut=expected_cut)
    except StaleReceiptError as exc:
        return "STALE", str(exc)
    return status, payload.get("reason", "")


# The end-of-turn command whose entry the S2 seam hooks. HG: command 11 (UpdateFieldConditionExtra). hge replaces
# command 9 (ServerFieldConditionCheck, `hooks:376`) with C that runs ALL end-of-turn effects, calls
# CheckIfAnyoneShouldFaint at its loop top (ServerFieldConditionCheck.c:127) and ends in TURN_END (:1944), so hge never
# dispatches commands 10/11 (live: trace 9 -> 12). The address and pin are read from the ROM's own dispatch table.
UFCE_CMD = {"heartgold": 11, "heartgold_hge": 9, "soulsilver": 11}
UFCE_NAME = {11: "BattleControllerPlayer_UpdateFieldConditionExtra", 9: "hge_ServerFieldConditionCheck_entry"}
CMD_TABLE = 0x0226CA90  # sPlayerBattleCommands (xMAP / hge rom.ld:710)


def seam_overrides(title: str, rom: Path) -> dict:
    """{"ufce": {addr, pin, cmd, name}} derived from the ROM table entry, never typed in."""
    if title == "soulsilver":
        return {"ufce": ss_file_proof(rom)["seams"]["ufce"]}
    cmd = UFCE_CMD[title]
    ov12, _ = rom_images(rom)
    entry = struct.unpack_from("<I", ov12.data, CMD_TABLE + 4 * cmd - ov12.ramAddress)[0]
    addr = entry & ~1
    pin = struct.unpack_from("<I", ov12.data, addr - ov12.ramAddress)[0]
    return {"ufce": {"addr": addr, "pin": pin, "cmd": cmd, "name": UFCE_NAME[cmd]}}


def ss_file_proof(rom: Path) -> dict:
    """SS-only FILE derivation. Reject any disagreement with the unchanged Lua floor.

    HG/hge take their existing paths. SS's xMAP names the dispatch table and
    observers; its ROM verifies their bytes. The Lua floor needs no change only
    because these independent SS facts match it (test_ss_title_support_and_file_floor).
    """
    from tools import gen_gen4_pack as generator
    assert g4.sha1_of(rom) == gen4_pins.ROM_SPECS["soulsilver"][0], "wrong SS ROM"
    xm_path = gen4_pins.default_locations().assets["soulsilver_xmap"]
    need(xm_path, "SS xMAP")
    lock = json.loads(g4.LOCK.read_text())
    assert digest(xm_path) == lock["assets"]["soulsilver_xmap"]["sha256"], "wrong SS xMAP"
    xm, images = generator.load_xmap(xm_path), generator.load_images(rom)
    t = json.loads((REPO / "data/games/gen4_hgss/profile.json").read_text())["titles"]["soulsilver"]
    def site(name):
        sym = xm.lookup(name)
        return {"addr": sym.address, "pin": int.from_bytes(images.read(sym.image, sym.address, 4), "little"),
                "name": name, "image": sym.image, "source": "soulsilverus.xMAP:"+name}
    table = xm.lookup("sPlayerBattleCommands")
    turnend, ufce = site("BattleControllerPlayer_TurnEnd"), site("BattleControllerPlayer_UpdateFieldConditionExtra")
    assert table.image == "ov12" and table.address == CMD_TABLE, "SS command table differs from floor"
    for command, row in ((12, turnend), (UFCE_CMD["soulsilver"], ufce)):
        entry = int.from_bytes(images.read(table.image, table.address + 4 * command, 4), "little")
        assert entry == row["addr"] | 1, "SS dispatch target differs"
        row["cmd"] = command
    seam = t["profile"]["battle"]["d7"]["seam"]
    assert (seam["addr"], seam["cmd"], int.from_bytes(bytes.fromhex(seam["pin_hex"]), "little")) == (ufce["addr"], ufce["cmd"], ufce["pin"]), "SS pack seam differs"
    heal, blackout = site("HealParty"), site("Task_Blackout")
    floor = ((turnend, TURNEND_ADDR, 0x1C0CB538), (ufce, seam["addr"], 0xB082B5F8),
             (heal, 0x02090C1C, 0xB083B5F0), (blackout, t["sites"]["blackout"]["address"], 0xB086B5F8))
    for row, address, pin in floor:
        assert (row["addr"], row["pin"]) == (address, pin), f"SS Lua floor mismatch: {row['name']}"
    chain = {"FS": t["symbols"]["sFieldSysPtr"]["address"], "SAVEPTR": t["symbols"]["sSaveDataPtr"]["address"]}
    assert chain == {"FS": xm.lookup("sFieldSysPtr").address, "SAVEPTR": xm.lookup("sSaveDataPtr").address}
    assert chain == {"FS": 0x021D4158, "SAVEPTR": 0x021D2228}, "SS chain differs from Lua floor"
    return {"rom_sha1": g4.sha1_of(rom), "xmap_sha256": digest(xm_path), "chain": chain,
            "seams": {"turnend": turnend, "ufce": ufce}, "observers": {"heal": heal, "blackout": blackout}}


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


OV12_WINDOW = (0x022378C0, 0x022378C0 + 226176)  # ov12 load address and size (ndspy, both pinned ROMs)
TURNEND_ADDR = 0x0224A958


def check_seam_first(obs: dict, expected: dict[str, int]) -> list[str]:
    """Receipt-shape check on the hook's FIRST raw registers (F5): for every seam that dispatched (and always for the
    armed one) `first` exists, r0/r1 equal the chain-derived bs/ctx, and r15 is addr+4 (the Thumb pipeline PC: it reads
    EVEN, Thumb state lives in CPSR) inside the ov12 window. Returns one line per checked seam."""
    seams = obs.get("seams")
    assert seams, "receipt has no observation.seams"
    armed = obs["seam"]["armed_mode"]
    lines = []
    for key, st in seams.items():
        if st.get("hits", 0) == 0 and key != armed:
            continue
        first = st.get("first")
        assert first, f"seam {key}: no first-hit registers recorded"
        assert first["r0"] == first["bs"] and first["r1"] == first["ctx"], f"seam {key}: r0/r1 != chain pointers"
        r15 = first["r15"]
        assert OV12_WINDOW[0] <= r15 < OV12_WINDOW[1], f"seam {key}: r15 {r15:#x} outside ov12"
        assert r15 % 2 == 0 and r15 == expected[key] + 4, f"seam {key}: r15 {r15:#x} != {expected[key]:#x}+4"
        lines.append(f"{key}: r15={r15:#x} addr={expected[key]:#x} r0={first['r0']:#x} r1={first['r1']:#x}")
    return lines


def build_config(*, title: str, rom_sha1: str, scenario: str, lane: Path, state: Path, source_head: str,
                 profile: Path, fault: str | None = None, max_frames: int = 5400,
                 seams: dict | None = None, synth: dict | None = None,
                 state_save: dict | None = None) -> dict:
    prof = json.loads(profile.read_text(encoding="utf-8"))["titles"][title]["profile"]
    # offsets come from the pack, never hard-coded: save header table, battle layout, gSystem (liveness counters)
    pack = {"save": prof["save"], "battle": prof["battle"], "system": prof["system"]}
    return {"pack": pack, "seams": seams or {}, "setup": "SYNTH" if synth else "NATIVE", "synth": synth, "run_id": f"{lane.parent.name}/{lane.name}", "title": title, "rom_sha1": rom_sha1,
            "scenario": scenario, "state_path": state.as_posix(), "shot_dir": lane.as_posix(),
            "requested_rate": 300, "fault": fault, "max_frames": max_frames, "move_right": True,
            "script_sha256": digest(SCRIPT), "profile_sha256": digest(profile), "source_head": source_head,
            "modules": module_digests(title), **state_save_record(state_save)}


def emuhawk_command(lane: Path, rom: Path) -> list[str]:
    """ABSOLUTE lane paths: kill_our_emuhawk() matches this lane by its command line."""
    return [str(EMUHAWK), f"--config={(lane / 'bizhawk.ini').as_posix()}", f"--lua={SCRIPT.as_posix()}",
            rom.as_posix()]


def terminal(out: Path) -> bool:
    return out.is_file() and any(ln.startswith("RESULT:") for ln in out.read_text(encoding="utf-8").splitlines())


def launch(title: str, scenario: str, state: Path, rom_src: Path, save: Path, fault: str | None = None,
           synth: dict | None = None, *, manifest=None, source_save_sha256=None):
    assert title in PACK, title
    # FIRST, before any staging and before the emulator: the state and the save are one pair, or this
    # is not a run of anything. Loading a state over an unrelated battery would let the receipt
    # describe a world the staged save never held.
    binding = state_save_binding(state, save, title=title, manifest=manifest, source_save_sha256=source_save_sha256)
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
                        source_head=head, profile=profile, fault=fault, seams=seam_overrides(title, rom), synth=synth,
                        state_save=binding)
    if title == "soulsilver":
        cfg["ss_file_proof"] = ss_file_proof(rom)
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
        status, payload = consume_receipt(out.read_text(encoding="utf-8"), title=title, rom_sha1=rom_sha1,
                                          run_id=cfg["run_id"])
        assert payload["script_sha256"] == cfg["script_sha256"], "receipt from a different script"
        assert payload["callback_errors"] == 0, f"callback faults in {lane}: {payload.get('callback_error')}"
        if payload["observation"].get("write"):  # a run that wrote has hooks that fired: check their raw registers
            check_seam_first(payload["observation"], {"turnend": TURNEND_ADDR, "ufce": cfg["seams"]["ufce"]["addr"]})
        assert payload.get("setup") == ("SYNTH" if synth else "NATIVE"), "receipt does not disclose the setup kind"
        if synth:
            assert payload["synth"]["sidecar_sha256"] == synth["sidecar_sha256"], "receipt carries another sidecar"
        # the binding this run staged and paired is only in probe.json until the probe echoes it back
        check_receipt_binding(payload, cfg)
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


def _no_env(monkeypatch):
    """Hermetic: the operator's own binding channels must not decide a model refusal."""
    for template in (MANIFEST_ENV, SOURCE_SAVE_ENV):
        for name in PACK:
            monkeypatch.delenv(template.format(name.upper()), raising=False)


def _state_and_save(tmp_path: Path) -> tuple[Path, Path]:
    lane = tmp_path / "diag"
    lane.mkdir()
    state = lane / "leg1_battle_settled.State"
    state.write_bytes(b"PK\x03\x04" + b"state" * 64)
    save = tmp_path / "battery.SaveRAM"
    save.write_bytes(b"\x00" * 512)
    return state, save


def _diagnostic_manifest(lane: Path, state: Path, save: Path) -> Path:
    """The document tools/gen4_diag.collect publishes (tools/gen4_diag.py:130,198-210): the config it
    ran with (which carries the run's save_sha256) plus its DIAGNOSTIC_PRODUCED output states."""
    doc = {"schema": "gen4-diagnostic-v1", "producer": "tools/gen4_diag.py", "qualified": False,
           "status": "OBSERVED", "command": "settle", "save_sha256": digest(save),
           "state_path": state.as_posix(),
           "outputs": {state.relative_to(lane).as_posix():
                       {"producer": "tools/gen4_diag.py", "qualified": False, "sha256": digest(state),
                        "setup": "DIAGNOSTIC_PRODUCED", "command": "settle", "source_head": "0" * 40}}}
    path = lane / "diagnostic.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_diagnostic_state_from_another_save_refuses(tmp_path):
    """A lead12-produced state carries a level-12 party; over the level-3 native battery the receipt would
    describe the wrong world. The manifest knows the save it ran from, and that is not this one."""
    state, save = _state_and_save(tmp_path)
    lead12 = tmp_path / "lead12.SaveRAM"
    lead12.write_bytes(b"\xff" * 512)
    manifest = _diagnostic_manifest(state.parent, state, lead12)
    with pytest.raises(StateSaveProvenanceError, match="state/save provenance mismatch"):
        state_save_binding(state, save, title="heartgold", manifest=manifest)
    # the state itself is still reviewed -- only the save pairing is refused
    assert gen4_diag.check_state_manifest(state, manifest, digest(state))["sha256"] == digest(state)


def test_matching_diagnostic_manifest_binds_the_state_to_that_save(tmp_path):
    state, save = _state_and_save(tmp_path)
    manifest = _diagnostic_manifest(state.parent, state, save)
    bound = state_save_binding(state, save, title="heartgold", manifest=manifest)
    assert bound["state_save_sha256"] == digest(save) and bound["state_sha256"] == digest(state)
    assert "diagnostic manifest" in bound["state_binding"] and "not a state decode" in bound["state_binding"]


def test_route_state_without_a_recorded_save_hash_refuses(monkeypatch, tmp_path):
    _no_env(monkeypatch)
    state, save = _state_and_save(tmp_path)
    with pytest.raises(StateSaveProvenanceError, match="no state/save provenance"):
        state_save_binding(state, save, title="heartgold")
    with pytest.raises(StateSaveProvenanceError, match="records no producer save sha256"):
        state_save_binding(state, save, title="heartgold", source_save_sha256="not-a-sha256")
    with pytest.raises(StateSaveProvenanceError, match="does not review"):
        state_save_binding(state, save, title="heartgold", manifest=tmp_path / "diag" / "absent.json")
    # a manifest that reviews some other state does not review this one
    other = tmp_path / "diag" / "leg0_battle_settled.State"
    other.write_bytes(b"PK\x03\x04" + b"other" * 64)
    with pytest.raises(StateSaveProvenanceError, match="does not review"):
        state_save_binding(state, save, title="heartgold", manifest=_diagnostic_manifest(tmp_path / "diag", other, save))


def test_route_state_wrong_recorded_hash_refuses_and_the_right_hash_passes(monkeypatch, tmp_path):
    _no_env(monkeypatch)
    state, save = _state_and_save(tmp_path)
    with pytest.raises(StateSaveProvenanceError, match="state/save provenance mismatch"):
        state_save_binding(state, save, title="heartgold", source_save_sha256="0" * 64)
    bound = state_save_binding(state, save, title="heartgold", source_save_sha256=digest(save))
    assert bound["state_save_sha256"] == digest(save) and "route save sha256" in bound["state_binding"]


def test_the_route_binding_can_come_from_the_operator_env(monkeypatch, tmp_path):
    """The live lane has no manifest, so the channel the coordinator actually uses is the env pair."""
    _no_env(monkeypatch)
    state, save = _state_and_save(tmp_path)
    key = SOURCE_SAVE_ENV.format("HEARTGOLD")
    with pytest.raises(StateSaveProvenanceError, match="no state/save provenance"):
        state_save_binding(state, save, title="heartgold")
    monkeypatch.setenv(key, "0" * 64)
    with pytest.raises(StateSaveProvenanceError, match="state/save provenance mismatch"):
        state_save_binding(state, save, title="heartgold")
    monkeypatch.setenv(key, digest(save))
    assert state_save_binding(state, save, title="heartgold")["state_save_sha256"] == digest(save)
    # a binding offered for another title never binds this one
    monkeypatch.setenv(SOURCE_SAVE_ENV.format("SOULSILVER"), digest(save))
    assert state_save_binding(state, save, title="heartgold")["state_save_sha256"] == digest(save)


def test_launch_refuses_an_unbound_pair_before_it_stages_anything(monkeypatch, tmp_path):
    """The refusal is the first thing launch() does: no EmuHawk needed, no ROM, no run directory."""
    _no_env(monkeypatch)
    state, save = _state_and_save(tmp_path)
    lead12 = tmp_path / "lead12.SaveRAM"
    lead12.write_bytes(b"\xff" * 512)
    manifest = _diagnostic_manifest(state.parent, state, lead12)
    monkeypatch.setitem(LANES, "heartgold", tmp_path / "lanes")
    with pytest.raises(StateSaveProvenanceError, match="state/save provenance mismatch"):
        launch("heartgold", "seam_turnend", state, tmp_path / "absent.nds", save, manifest=manifest)
    assert not (tmp_path / "lanes").exists(), "launch staged a run before refusing the pairing"


def test_the_hash_comparison_is_what_refuses_red_revert(tmp_path):
    """Revert-check: with that one comparison neutralised, the same mismatched pairing is ACCEPTED, so
    the refusals above are that guard and not an accident of some other check."""
    source = inspect.getsource(state_save_binding)
    guard = "recorded != staged"
    assert source.count(guard) == 1
    namespace = {"Path": Path, "os": os, "re": re, "json": json, "digest": digest, "need": need,
                 "gen4_diag": gen4_diag, "MANIFEST_ENV": MANIFEST_ENV, "SOURCE_SAVE_ENV": SOURCE_SAVE_ENV,
                 "StateSaveProvenanceError": StateSaveProvenanceError, "_sha256": _sha256}
    exec(source.replace(guard, "False"), namespace)
    state, save = _state_and_save(tmp_path)
    lead12 = tmp_path / "lead12.SaveRAM"
    lead12.write_bytes(b"\xff" * 512)
    manifest = _diagnostic_manifest(state.parent, state, lead12)
    bound = namespace["state_save_binding"](state, save, title="heartgold", manifest=manifest)
    assert bound["state_save_sha256"] == digest(save), "the comparison was not the thing that refused"


def test_config_carries_the_bound_state_save_provenance(tmp_path):
    profile = REPO / "data/games/gen4_hgss/profile.json"
    bound = {"state_sha256": "1" * 64, "state_save_sha256": "2" * 64,
             "state_binding": "recorded route save sha256 (not a state decode)"}
    common = {"title": "heartgold", "rom_sha1": "ab" * 20, "scenario": "seam_turnend",
              "lane": tmp_path / "lane", "state": tmp_path / "start.State", "source_head": "cut",
              "profile": profile}
    cfg = build_config(**common, state_save=bound)
    assert (cfg["state_sha256"], cfg["state_save_sha256"], cfg["state_binding"]) == \
        (bound["state_sha256"], bound["state_save_sha256"], bound["state_binding"])
    assert build_config(**common)["state_save_sha256"] is None, "an unbound config must disclose nothing"


def test_a_receipt_must_disclose_the_bound_state_save_and_red_revert():
    cfg = {"state_save_sha256": "2" * 64, "state_binding": "diagnostic manifest (not a state decode)"}
    good = {"state_save_sha256": "2" * 64, "state_binding": cfg["state_binding"], "state_binding_kind": "diag_manifest"}
    wrong_sha = [{k: v for k, v in good.items() if k != "state_save_sha256"}, {**good, "state_save_sha256": "3" * 64}]
    wrong_kind = [{**good, "state_binding_kind": "route_recorded"}, {**good, "state_binding_kind": None}]
    wrong_record = [{**good, "state_binding": "recorded route save sha256 (not a state decode)"}]
    check_receipt_binding(good, cfg)
    for payload, why in [(p, "bound state_save_sha256") for p in wrong_sha] + \
                         [(p, "binding kind") for p in wrong_kind] + \
                         [(p, "another state binding") for p in wrong_record]:
        with pytest.raises(AssertionError, match=why):
            check_receipt_binding(payload, cfg)
    # RED: with the sha256 disclosure neutralised the same receipts are accepted -- the refusals above
    # are that comparison and not an accident of some other check. REVERT: the real one refuses again.
    source = inspect.getsource(check_receipt_binding)
    guard = 'payload.get("state_save_sha256") == cfg["state_save_sha256"]'
    assert source.count(guard) == 1
    namespace = {"binding_kind": binding_kind}
    exec(source.replace(guard, "True"), namespace)
    for payload in wrong_sha:
        namespace["check_receipt_binding"](payload, cfg)
    for payload in wrong_sha:
        with pytest.raises(AssertionError, match="bound state_save_sha256"):
            check_receipt_binding(payload, cfg)


def test_the_lua_receipt_echo_classifies_exactly_the_same_bindings():
    lupa = pytest.importorskip("lupa")
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.globals().SLINK_GEN4_FAINT_TEST = True
    m = rt.execute(SCRIPT.read_text(encoding="utf-8"))
    for origin, kind in BINDING_KINDS.items():
        record = f"{origin} (not a state decode)"
        assert binding_kind(record) == kind == m.binding_kind(record)
    # an absent, explicitly nil or unrecognised binding classifies as nil on both sides, never a default kind
    for expr, cfg in (("return {}", {}), ("return {state_binding=nil}", {"state_binding": None}),
                      ("return {state_binding='some other origin'}", {"state_binding": "some other origin"})):
        assert binding_kind(cfg.get("state_binding")) is None
        assert m.binding_kind(rt.execute(expr)) is None


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


@pytest.mark.parametrize("title", ["heartgold", "heartgold_hge", "soulsilver"])
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


def test_ss_title_support_and_file_floor():
    """FILE: SS is derived from its own locked xMAP/ROM, not a title alias."""
    assert PACK["soulsilver"] == "gen4_hgss"
    assert LANES["soulsilver"] == LANE_ROOT and P2_PROFILE["soulsilver"] == "hgss"
    rom = need(gen4_pins.default_locations().roms["soulsilver"], "SS ROM")
    proof = ss_file_proof(rom)
    m = lua_api()
    for key in ("FS", "SAVEPTR"):
        assert proof["chain"][key] == m.L[key], key
    for kind, group in (("seams", m.SEAMS), ("observers", m.OBS)):
        for key, spec in group.items():
            row = proof[kind][key]
            assert row["addr"] == spec.addr and row["pin"] == spec.pin, key
    prof = json.loads((REPO / "data/games/gen4_hgss/profile.json").read_text())["titles"]["soulsilver"]["profile"]
    assert UFCE_CMD["soulsilver"] == prof["battle"]["d7"]["seam"]["cmd"] == proof["seams"]["ufce"]["cmd"]
    b = prof["battle"]
    for lua_key, value in {"bs_type": b["type_off"], "bs_outcome": b["outcome_off"],
                           "bs_party": b["d7"]["bs_party_off"], "ctx_cmd": b["d7"]["ctx_cmd_off"],
                           "ctx_status": b["fainted_flag_off"], "mon_maxhp": b["max_hp_off"],
                           "mon_pid": b["personality_off"], "mon_otid": b["otid_off"],
                           "ctx_repl": b["d7"]["repl_flag_off"], "rec_hp": b["d7"]["party_hp_off"]}.items():
        assert m.L[lua_key] == value, lua_key


def test_ss_model_controls_red_and_revert():
    import lupa

    from tests.unit.test_gen4_battle_faint_model import World, lt, want
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.globals().SLINK_GEN4_FAINT_TEST = True
    m = rt.execute(SCRIPT.read_text())
    assert "soulsilver" in PACK
    prof = json.loads((REPO / "data/games/gen4_hgss/profile.json").read_text())["titles"]["soulsilver"]["profile"]
    def lua(v):
        return rt.table_from({k: lua(x) if isinstance(x, dict) else x for k, x in v.items()})
    m.configure(lua(prof))
    world = World(save_hdr=prof["save"]["array_headers_off"])
    original = bytes(world.m)
    assert m.judge_controls(m.controls(world.mem(rt), want(rt)))[0]
    for fault, reason in FAULTS.items():
        ok, why = m.judge_controls(m.controls(world.mem(rt), want(rt), lt(rt, fault=fault)))
        assert not ok and why == reason
        assert m.judge_controls(m.controls(world.mem(rt), want(rt)))[0]
    assert bytes(world.m) == original


@pytest.mark.parametrize("corruption,reason", [
    ("heal", "SS Lua floor mismatch: HealParty"),
    ("seam", "SS pack seam differs"),
    ("dispatch", "SS dispatch target differs"),
])
def test_ss_file_pin_corruption_refuses_and_reverts(monkeypatch, corruption, reason):
    from tools import gen_gen4_pack as generator
    rom = need(gen4_pins.default_locations().roms["soulsilver"], "SS ROM")
    good = ss_file_proof(rom)
    original = generator.load_images
    images = original(rom)
    corrupt_address = {"heal": good["observers"]["heal"]["addr"], "seam": good["seams"]["ufce"]["addr"],
                       "dispatch": CMD_TABLE + 4 * UFCE_CMD["soulsilver"]}[corruption]
    class Corrupt:
        def read(self, image, address, size):
            raw = images.read(image, address, size)
            if address == corrupt_address:
                return bytes([raw[0] ^ 1]) + raw[1:]
            return raw
    monkeypatch.setattr(generator, "load_images", lambda *a, **k: Corrupt())
    with pytest.raises(AssertionError, match=reason):
        ss_file_proof(rom)
    monkeypatch.setattr(generator, "load_images", original)
    assert ss_file_proof(rom) == good


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
    elif title == "soulsilver":
        state_path = Path(os.environ.get("SLINK_GEN4_SOULSILVER_FAINT_STATE", g4.lane_root() / "route_ss/ss_battle_settled.State"))
        log = state_path.with_name(state_path.name.replace("_battle_settled.State", ".log"))
        state = check_state(state_path, log, title)
        save = need(Path(os.environ.get("SLINK_GEN4_SOULSILVER_SAVE", g4.lane_root() / "saves/ss_DDDD_25944.SaveRAM")), "SS played save")
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
@pytest.mark.parametrize("scenario", ["seam_turnend", "seam_turnend_p2"])
@pytest.mark.parametrize("fault", FAULTS)
def test_live_instrument_controls_go_red_when_a_check_is_disabled(fault, scenario):
    """Revert-test on the real memory: disabling ONE guard/readback check must turn the run FAIL
    with that control named, before any game memory is written (one-mon and the 2-mon SYNTH state)."""
    state, rom, save, synth = _live_inputs("heartgold", p2=scenario in P2_SCENARIOS)
    status, payload, lane, _ = launch("heartgold", scenario, state, rom, save, fault=fault, synth=synth)
    assert status == "FAIL" and FAULTS[fault] in payload["reason"], (status, payload.get("reason"))
    assert payload["observation"].get("write") is None, "a write happened despite red instrument controls"


@pytest.mark.parametrize("title", ["heartgold", "heartgold_hge", "soulsilver"])
def test_s2_seam_is_derived_from_the_rom_dispatch_table(title):
    """FILE: HG derives the Lua default (command 11); hge derives its command-9 entry, the vanilla address
    patched by hooks:376 (a trampoline, so its pin differs from the vanilla UFCE bytes)."""
    rom = gen4_pins.default_locations().roms[title]
    if not rom.is_file():
        pytest.skip(f"OPEN {title} ROM absent: {rom}")
    seam = seam_overrides(title, rom)["ufce"]
    m = lua_api()
    if title in ("heartgold", "soulsilver"):
        assert (seam["addr"], seam["pin"], seam["cmd"]) == (m.SEAMS.ufce.addr, m.SEAMS.ufce.pin, m.SEAMS.ufce.cmd)
    else:
        assert (seam["addr"], seam["cmd"]) == (0x022494DC, 9)
        assert seam["pin"] != m.SEAMS.ufce.pin  # replaced entry bytes, not the vanilla function


def _seam_obs(**over):
    first = {"bs": 0x22C020C, "ctx": 0x22C32D8, "r0": 0x22C020C, "r1": 0x22C32D8, "r15": 0x224A95C}
    obs = {"seam": {"armed_mode": "turnend"},
           "seams": {"turnend": {"hits": 2, "first": first},
                     "ufce": {"hits": 1, "first": {**first, "r15": 0x224A710}}}}
    obs["seams"]["turnend"].update(over)
    return obs


def test_seam_first_registers_receipt_shape_goes_red_on_each_defect():
    expected = {"turnend": TURNEND_ADDR, "ufce": 0x0224A70C}
    assert len(check_seam_first(_seam_obs(), expected)) == 2
    good = _seam_obs()["seams"]["turnend"]["first"]
    for patch, why in [({"first": None}, "no first-hit"), ({"first": {**good, "r15": 0x2000000}}, "outside ov12"),
                       ({"first": {**good, "r15": 0x224A95B}}, "outside|!="),  # odd: not the Thumb pipeline PC
                       ({"first": {**good, "r15": 0x224A960}}, r"!= 0x224a958\+4"),
                       ({"first": {**good, "r0": 5}}, "r0/r1")]:
        with pytest.raises(AssertionError, match=why):
            check_seam_first(_seam_obs(**patch), expected)
    obs = _seam_obs()
    del obs["seams"]
    with pytest.raises(AssertionError, match="no observation.seams"):
        check_seam_first(obs, expected)


def test_seam_first_registers_of_shipped_p2_receipts_if_present():
    """The four shipped 2-mon rows: their raw registers satisfy the shape check (skips by name when absent)."""
    shipped = {"heartgold_seam_ufce_bit_p2_201242": 0x0224A70C, "heartgold_seam_turnend_p2_201327": 0x0224A70C,
               "heartgold_hge_seam_turnend_p2_201400": 0x022494DC, "heartgold_hge_seam_ufce_bit_p2_201513": 0x022494DC}
    for name, ufce in shipped.items():
        path = LANE_ROOT / name / "receipt.txt"
        if not path.is_file():
            pytest.skip(f"OPEN shipped receipt absent: {path}")
        payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0].split(" ", 3)[3])
        check_seam_first(payload["observation"], {"turnend": TURNEND_ADDR, "ufce": ufce})  # shape holds regardless of cut
        title = payload["title"]
        cut = current_cut(title)
        verdict, why = receipt_verdict(path, title=title, rom_sha1=payload["rom_sha1"])
        if any(payload.get(k) != cut[k] for k in cut):  # shipped from an older cut: STALE until re-run at landing
            assert verdict == "STALE", f"{name}: stale cut consumed as {verdict}"
        else:
            assert verdict != "STALE"


def _cut_receipt(cut, **over):
    payload = {"level": "PHYSICAL", "producer": "C1-8", "title": "heartgold", "rom_sha1": "ab" * 20, "run_id": "r",
               "oracle": "o", "negative_control": {"x": 1}, **cut, **over}
    return "PROBE o PASS " + json.dumps(payload) + "\nRESULT: PASS\n"


MODEL_CUT = {"source_head": "cut", "script_sha256": "1" * 64, "profile_sha256": "2" * 64,
             "module_sha256": {"lua/json_codec.lua": "3" * 64}, "rom_sha1": "ab" * 20}
MODEL_CUT.update(receipt_kind="faint", title="heartgold", script="model.lua",
                 surface_sha256=gen4_evidence.surface_hash("faint", MODEL_CUT["module_sha256"]))


def _stale_value(field):
    return {"lua/json_codec.lua": "0" * 64} if field == "module_sha256" else "0" * 7


@pytest.mark.parametrize("field", tuple(k for k in MODEL_CUT if k != "source_head"))
def test_consume_receipt_stale_cut_red_revert(field):
    def consume(text):
        return consume_receipt(text, title="heartgold", rom_sha1="ab" * 20, expected_cut=MODEL_CUT)

    assert consume(_cut_receipt(MODEL_CUT))[0] == "PASS"
    with pytest.raises(StaleReceiptError, match=f"STALE {field}"):
        consume(_cut_receipt(MODEL_CUT, **{field: _stale_value(field)}))
    assert consume(_cut_receipt(MODEL_CUT))[0] == "PASS"  # revert: the fresh receipt is accepted again


def test_stale_outranks_every_other_verdict_and_is_never_pass(tmp_path):
    """A stale receipt is STALE even when it is also malformed in a later check, and a file's verdict is the string
    STALE (never PASS); the same file with the current cut is PASS."""
    path = tmp_path / "row_o.txt"
    path.write_text(_cut_receipt(MODEL_CUT, script_sha256="old", producer="other"), encoding="utf-8")
    verdict, why = receipt_verdict(path, title="heartgold", rom_sha1="ab" * 20, expected_cut=MODEL_CUT)
    assert verdict == "STALE" and "script_sha256" in why
    path.write_text(_cut_receipt(MODEL_CUT), encoding="utf-8")
    assert receipt_verdict(path, title="heartgold", rom_sha1="ab" * 20, expected_cut=MODEL_CUT)[0] == "PASS"


def test_current_cut_is_this_head_and_these_files(monkeypatch):
    cut = current_cut("heartgold")
    assert cut["source_head"] and cut["script_sha256"] == digest(SCRIPT)
    assert cut["profile_sha256"] == digest(REPO / "data/games/gen4_hgss/profile.json")
    assert current_cut("heartgold_hge")["profile_sha256"] == digest(REPO / "data/games/gen4_hge/profile.json")
    # default binding (no injected cut): a receipt from another HEAD or another script file is STALE
    rom = cut["rom_sha1"]
    fresh = _cut_receipt(cut, rom_sha1=rom)
    assert consume_receipt(fresh, title="heartgold", rom_sha1=rom)[0] == "PASS"
    for field in (k for k in cut if k != "source_head"):
        with pytest.raises(StaleReceiptError, match=f"STALE {field}"):
            consume_receipt(_cut_receipt(cut, **{field: _stale_value(field)}), title="heartgold", rom_sha1=rom)
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: "moved\n")  # HEAD moves: the same receipt is now STALE
    assert consume_receipt(fresh, title="heartgold", rom_sha1=rom)[0] == "PASS"


def test_every_probe_dofile_is_bound():
    """B3: a module the probe loads is part of the evidence cut. Grep the script's dofile paths; each must be in MODULES,
    so the cut hashes it and a change to it makes old receipts STALE."""
    text = SCRIPT.read_text(encoding="utf-8")
    paths = set(re.findall(r'dofile\(\s*root\s*\.\.\s*"/?([^"]+)"', text))
    assert paths, "the grep found no dofile (pattern drifted from the probe's `dofile(root .. \"/lua/...\")` form)"
    assert not re.findall(r"\b(?:loadfile|require)\(", text), "a loadfile/require would bypass the dofile grep"
    unbound = paths - set(MODULES)
    assert not unbound, f"probe loads unbound modules {sorted(unbound)}: add them to MODULES"
    assert set(current_cut("heartgold")["module_sha256"]) >= paths


def test_unbound_dofile_is_detected_red_revert(tmp_path, monkeypatch):
    """Revert-test of the grep itself: a probe that loads another module makes the check fail."""
    fake = tmp_path / "probe.lua"
    fake.write_text(SCRIPT.read_text(encoding="utf-8") + '\nlocal extra = dofile(root .. "/lua/hud.lua")\n', encoding="utf-8")
    monkeypatch.setitem(globals(), "SCRIPT", fake)
    with pytest.raises(AssertionError, match="unbound modules"):
        test_every_probe_dofile_is_bound()


def test_module_change_makes_receipts_stale(monkeypatch):
    cut = current_cut("heartgold")
    fresh = _cut_receipt(cut, rom_sha1=cut["rom_sha1"])
    assert consume_receipt(fresh, title="heartgold", rom_sha1=cut["rom_sha1"])[0] == "PASS"
    original = gen4_evidence.snapshot
    def changed(*a, **kw):
        result = original(*a, **kw)
        result["module_sha256"]["lua/json_codec.lua"] = "e" * 64
        result["surface_sha256"] = gen4_evidence.surface_hash("faint", result["module_sha256"])
        return result
    monkeypatch.setattr(gen4_evidence, "snapshot", changed)
    with pytest.raises(StaleReceiptError, match="STALE module_sha256"):
        consume_receipt(fresh, title="heartgold", rom_sha1=cut["rom_sha1"])
    # the receipt itself records the module hashes the run used
    assert "module_sha256" in cut and cut["module_sha256"]["lua/json_codec.lua"] == digest(REPO / "lua/json_codec.lua")
