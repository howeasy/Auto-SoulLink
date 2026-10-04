#!/usr/bin/env python3
"""First live bring-up of the Polished Crystal client (owner-authorised 2026-10-04).

    python tools/polished_live/harness.py setup   # cold boot -> native intro -> SYNTH party/bag/position -> native SAVE
    python tools/polished_live/harness.py live    # real SLinkServer + lua/slink.lua + stage driver (stages 1-4)

Everything runs under F:/slink-work/lanes/pol-live (short, non-Drive: BizHawk SaveRAM fails near MAX_PATH).
Only the EmuHawk PID this script starts is ever killed (taskkill /T /F /PID); never an image-name kill.
The ROM is the overlay the Manager hands out: the cached companion build, refused unless its sha1 equals
data/polished/overlay_provenance.json. Facts come from data/polished/polished_slink.sym and the pinned
source (data/polished_sources.lock.json); nothing is derived from screenshots.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO))

from gen1_playthrough import BIZHAWK_CONFIG, EMUHAWK, write_run_config  # noqa: E402

from server.adapters import polished_codec as pc  # noqa: E402

LANE = Path(os.environ.get("POL_LANE", "F:/slink-work/lanes/pol-live"))
# POL_KIND: overlay (the SLink companion build, the subject) | clean (the release, a CONTROL only: no client runs on it)
KIND = os.environ.get("POL_KIND", "overlay")
# POL_POSMODE: warp (Script_warp-equivalent WRAM writes + MAPSETUP_WARP, the engine reloads the map) | poke (bare
# wMapGroup/wMapNumber/wXCoord/wYCoord write, kept only as the corruption CONTROL)
MODE = os.environ.get("POL_POSMODE", "warp")
CACHE = Path("F:/slink-work/cache/polished")
ROM_SRC = CACHE / ("companion-overlay" if KIND == "overlay" else "release") / "polishedcrystal-3.2.3.gbc"
ROM = LANE / "rom" / f"pol_{KIND}.gbc"               # unknown hash -> BizHawk names the save from the filename
SAVE_NAME = f"pol {KIND}.SaveRAM"
SRAM = LANE / f"sram_{KIND}"
FIXTURE = Path(os.environ.get("POL_FIXTURE") or LANE / "fixture" / f"polished_{KIND}_{MODE}.SaveRAM")
SYM = REPO / "data" / "polished" / "polished_slink.sym"
SYMBOLS = (
    "wPartyCount", "wPartyMons", "wPartyMonOTs", "wPartyMonNicknames", "wPlayerID", "wPlayerName",
    "wNumBalls", "wBalls", "wMapGroup", "wMapNumber", "wXCoord", "wYCoord", "wBattleMode", "wBattleType",
    "wScriptRunning", "wMenuItemsList", "wMenuCursorY", "wGameLogicPaused", "wCurBox", "hROMBank", "hJoyPressed",
    "wEnemyMonSpecies", "wEnemyMonHP", "wBattleResult", "wSlinkMailbox", "wSavedAtLeastOnce", "wSaveFileExists",
    "OWPlayerInput", "SetInitialOptions.joypad_loop", "StartMenu", "SaveMenu", "SaveGameData", "LoadBattleMenu",
    "BattleMenu_Run", "PokeBallEffect", "PokeBallEffect.caught", "PokeBallEffect.SendToPC",
    "PokeBallEffect.SkipPartyMonFriendBall", "BlinkCursor", "YesNoBox", "NamingScreen", "TitleScreenMain",
    "MainMenu", "SlinkDelayFrameBridge", "DelayFrame", "DelayFrames", "NextOverworldFrame", "HandleMapTimeAndJoypad",
    "ExitBattle", "StartBattle", "WildFled_EnemyFled_LinkBattleCanceled", "GiveANickname_YesNo",
    "sSaveVersion", "sChecksum", "wDefaultSpawnpoint", "hMapEntryMethod", "wMapStatus", "wMapTileset", "wMapWidth",
    "wMapHeight", "wMapBlocksPointer", "wCurPocket", "BattlePack", "sGameData", "sGameDataEnd", "sWritingBackup", "sNewBox1", "sBackupNewBox1",
    # run 2 (Stage A gate log, Stage B receptionist, Stage C Pokegear)
    "wLinkMode", "wScriptMode", "wEventFlags", "wPokegearFlags", "wTilemap", "wAttrmap", "wPokegearCard",
    "wJumptableIndex", "wSpriteAnim1", "wShadowOAM", "PokeGear", "InitPokegearTilemap", "PokegearClock_Joypad",
    "PokegearMap_JohtoMap", "PokegearPhone_Joypad", "PokegearRadio_Joypad", "LinkReceptionistScript_Trade",
    "Script_TradeCenterClosed", "Special_WaitForLinkedFriend", "Special_WaitForLinkedFriend.done", "CheckPartyForMail",
    "FixPlayerEVsAndStats", "Special_TryQuickSave",
)
# SYNTH party (O-33, disclosed in docs/polished/LIVE_RESULTS.md): five level-50 mons, base stats from the pinned
# source data/pokemon/base_stats/*.asm (non-FAITHFUL rows), the modern formula Polished uses, DV 15 / IV 31, 0 EV,
# Hardy. OT ID and OT name are patched in Lua from the save's own wPlayerID / wPlayerName (obedience).
SPECIES = (  # (id, name, base hp/atk/def/spe/sat/sdf, exp at L50, gender)
    (169, "CROBAT", (85, 90, 80, 130, 70, 80), 125000, "male"),     # lead: base speed 130 -> every run succeeds
    (135, "JOLTEON", (65, 65, 60, 130, 110, 95), 125000, "male"),
    (55, "GOLDUCK", (80, 82, 78, 85, 95, 80), 125000, "female"),
    (34, "NIDOKING", (81, 102, 77, 85, 85, 75), 117360, "male"),
    (85, "DODRIO", (60, 110, 70, 110, 60, 60), 125000, "female"),
)
TACKLE = 0x21          # constants/move_constants.asm
POKE_BALL = 0x01       # constants/item_constants.asm
GRASS = (24, 3, 48, 12)  # ROUTE_29 (map_constants group 24 #3); step (48,12) is COLL_LONG_GRASS in Route29.ablk


def sym_table() -> dict:
    rows = {}
    for line in SYM.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and ":" in parts[0]:
            bank, addr = parts[0].split(":")
            rows.setdefault(parts[1], [int(bank, 16), int(addr, 16)])
    missing = [s for s in SYMBOLS if s not in rows]
    if missing:
        raise SystemExit(f"symbols missing from {SYM.name}: {missing}")
    return {s: rows[s] for s in SYMBOLS}


def synth_party() -> list:
    out = []
    for i, (species, name, base, exp, gender) in enumerate(SPECIES):
        level, iv = 50, 31
        hp = (2 * base[0] + iv) * level // 100 + level + 10
        stat = [((2 * b + iv) * level // 100) + 5 for b in base[1:]]
        mon = {"species_id": species, "form": 1, "gender": gender, "is_egg": False, "shiny": False,
               "ability_slot": 0, "nature": 0, "held_item": 0, "moves": [TACKLE, 0, 0, 0], "ot_id": 0,
               "exp": exp, "evs": dict.fromkeys(pc.STAT_NAMES, 0),
               "dvs": {n: (15 if n != "hp" else 14 - i) for n in pc.STAT_NAMES},  # distinct DVs per slot
               "pp": [35, 0, 0, 0], "pp_ups": [0, 0, 0, 0], "happiness": 70, "pokerus": 0, "caught_data": 0,
               "caught_level": level, "caught_location": 0, "level": level, "status": 0, "unused": 0,
               "hp": hp, "max_hp": hp,
               # base tuple is hp/atk/def/spe/sat/sdf, so stat[] = atk, def, spe, sat, sdf
               "stats": {"attack": stat[0], "defense": stat[1], "speed": stat[2], "special_attack": stat[3],
                         "special_defense": stat[4]}}
        out.append({"name": name, "struct_hex": pc.encode_party_mon(mon).hex(),
                    "nick_hex": pc.encode_text(name, 11).hex()})
    return out


def stage_rom() -> str:
    prov = json.loads((REPO / "data/polished/overlay_provenance.json").read_text(encoding="utf-8"))
    want = prov["output"]["sha1"] if KIND == "overlay" else prov["base_sha1"]
    data = ROM_SRC.read_bytes()
    sha1 = hashlib.sha1(data).hexdigest()
    if sha1 != want:
        raise SystemExit(f"{KIND} ROM sha1 {sha1} != provenance {want}")
    ROM.parent.mkdir(parents=True, exist_ok=True)
    if not ROM.exists() or hashlib.sha1(ROM.read_bytes()).hexdigest() != sha1:
        ROM.write_bytes(data)
    return sha1


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def kill_own(proc: subprocess.Popen, label: str) -> None:
    if proc.poll() is None:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        proc.wait(timeout=20)
    print(f"[pol-live] {label} pid {proc.pid} ended rc={proc.returncode}", flush=True)


def launch(lua: str, run_dir: Path, env_extra: dict, timeout: int, poll=None) -> tuple[str, int]:
    """One EmuHawk on the staged ROM; returns (result text, pid). Kills only the PID it started."""
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "result.txt"
    out.unlink(missing_ok=True)
    cfg = run_dir / "config.ini"
    write_run_config(BIZHAWK_CONFIG, str(cfg), saveram_dir=str(SRAM), purergb=True)
    longest = max(len(str(SRAM / SAVE_NAME)), len(str(out)))
    if longest >= 200:
        raise SystemExit(f"lane path too long ({longest})")
    syms = run_dir / "syms.json"
    syms.write_text(json.dumps(sym_table()), encoding="utf-8")
    env = dict(os.environ, SLINK_ROOT=str(REPO).replace("\\", "/"), POL_OUT=str(out).replace("\\", "/"),
               POL_SYMS=str(syms).replace("\\", "/"), POL_RUN=str(run_dir).replace("\\", "/"), POL_KIND=KIND, POL_POSMODE=MODE, **env_extra)
    cmd = [EMUHAWK, f"--lua={(REPO / lua).as_posix()}", f"--config={cfg.as_posix()}", ROM.as_posix()]
    proc = subprocess.Popen(cmd, cwd=str(REPO), env=env)
    print(f"[pol-live] EmuHawk pid {proc.pid}: {lua}", flush=True)
    (run_dir / "emuhawk.pid").write_text(str(proc.pid))
    deadline = time.monotonic() + timeout
    text = ""
    try:
        while time.monotonic() < deadline and proc.poll() is None:
            time.sleep(2)
            if poll:
                poll()
            text = out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""
            if any(line.startswith("RESULT:") for line in text.splitlines()):
                time.sleep(3)  # let client.saveram()/exit flush
                break
    finally:
        kill_own(proc, "EmuHawk")
    text = out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""
    return text, proc.pid


def cmd_setup() -> int:
    sha1 = stage_rom()
    sram = SRAM
    sram.mkdir(parents=True, exist_ok=True)
    (sram / SAVE_NAME).unlink(missing_ok=True)   # cold boot: NEW GAME
    synth = LANE / f"setup_{KIND}_{MODE}" / "synth.json"
    synth.parent.mkdir(parents=True, exist_ok=True)
    synth.write_text(json.dumps({"party": synth_party(), "balls": [[POKE_BALL, 99]], "position": GRASS}), encoding="utf-8")
    text, pid = launch("tools/polished_live/setup.lua", synth.parent, {"POL_SYNTH": synth.as_posix()}, 1500)
    print(text[-3000:])
    save = sram / SAVE_NAME
    if save.exists():
        fixture = FIXTURE
        fixture.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(save, fixture)
        print(f"[pol-live] fixture {fixture} sha256 {hashlib.sha256(fixture.read_bytes()).hexdigest()} rom {sha1}")
    return 0 if "RESULT: PASS" in text else 1


def cmd_live() -> int:
    sha1 = stage_rom()
    if KIND != "overlay":
        raise SystemExit("the client only runs on the overlay")
    fixture = FIXTURE
    if not fixture.exists():
        raise SystemExit("run `setup` first")
    sram = SRAM
    sram.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixture, sram / SAVE_NAME)
    run = LANE / "live"
    srv_dir = run / "srv"
    if srv_dir.exists():
        shutil.rmtree(srv_dir)
    srv_dir.mkdir(parents=True)
    # the sha1-bound contract (server/adapters/gen2_polished.py rom_contract_by_sha1): player a = this overlay
    (srv_dir / "rom_contract.json").write_text(json.dumps(
        {"upr_version": "none (overlay, not randomized)", "categories": [], "players": {"a": {"rom_sha1": sha1}}}),
        encoding="utf-8")
    port, http = free_port(), free_port()
    srv_log = open(run / "server.log", "w", encoding="utf-8")  # noqa: SIM115 - outlives the with-less try below
    srv = subprocess.Popen([sys.executable, "-m", "server.server", "--host", "127.0.0.1", "--port", str(port),
                            "--http-port", str(http), "--data-dir", str(srv_dir), "--verbose",
                            "--wire-log", str(run / "wire")],
                           cwd=str(REPO), stdout=srv_log, stderr=subprocess.STDOUT)
    print(f"[pol-live] server pid {srv.pid} tcp {port} http {http}", flush=True)
    snaps = run / "status.jsonl"
    snaps.unlink(missing_ok=True)
    last = {"t": 0.0}

    def poll():
        if time.monotonic() - last["t"] < 5:
            return
        last["t"] = time.monotonic()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{http}/api/status", timeout=3) as r:
                doc = json.loads(r.read())
            with open(snaps, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.time(), "status": doc}) + "\n")
        except Exception as exc:  # noqa: BLE001 - a missed poll is logged, never fatal
            with open(snaps, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.time(), "error": str(exc)}) + "\n")

    time.sleep(3)
    try:
        text, pid = launch("tools/polished_live/live.lua", run,
                           {"SLINK_HOST": "127.0.0.1", "SLINK_PORT": str(port), "SLINK_PLAYER": "a",
                            "POL_STAGES": os.environ.get("POL_STAGES", "1234")}, 2400, poll)
        last["t"] = 0
        poll()
    finally:
        kill_own(srv, "server")
        srv_log.close()
    print(text[-4000:])
    return 0 if "RESULT: PASS" in text else 1


def cmd_control() -> int:
    """No client: CONTINUE from the fixture, read the loaded map header, screenshot, try for an encounter."""
    stage_rom()
    if not FIXTURE.exists():
        raise SystemExit("run `setup` first")
    SRAM.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE, SRAM / SAVE_NAME)
    text, _ = launch("tools/polished_live/control.lua", LANE / f"control_{KIND}_{MODE}", {}, 900)
    print(text[-3000:])
    return 0 if "RESULT: PASS" in text else 1


def cmd_explore() -> int:
    """Run-2 read-only explorations without the client: POL_EXPLORE=B (receptionist stack) | C (Pokegear)."""
    stage_rom()
    which = os.environ.get("POL_EXPLORE", "B")
    if not FIXTURE.exists():
        raise SystemExit("no fixture: copy run 1's polished_overlay_warp.SaveRAM into <lane>/fixture")
    SRAM.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURE, SRAM / SAVE_NAME)
    run = LANE / f"explore_{which}"
    text, _ = launch("tools/polished_live/explore.lua", run, {"POL_EXPLORE": which}, 1500)
    print(text[-5000:])
    if (run / "stacks.json").exists():
        resolve(run / "stacks.json")
    return 0 if "RESULT: PASS" in text else 1


def resolve(path: Path) -> None:
    """Name every stack word: nearest sym at or below it; ROMX words try the sampled bank, then any bank whose bytes
    before the word are a call (cd/c4/cc/d4/dc) or an rst. `call` = the return address really follows a call."""
    rom = ROM.read_bytes()
    syms: dict = {}
    for line in SYM.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and ":" in parts[0]:
            b, a = (int(x, 16) for x in parts[0].split(":"))
            syms.setdefault(b, []).append((a, parts[1]))
    for rows in syms.values():
        rows.sort()

    def name(bank, addr):
        best = None
        for a, n in syms.get(bank, []):
            if a <= addr and (a >= (0x4000 if addr >= 0x4000 else 0)):
                best = (a, n)
            elif a > addr:
                break
        return f"{best[1]}+{addr - best[0]:#x}" if best else "?"

    def flat(bank, addr):
        return addr if addr < 0x4000 else bank * 0x4000 + addr - 0x4000

    def after_call(bank, addr):
        f = flat(bank, addr)
        if f >= 3 and rom[f - 3] in (0xCD, 0xC4, 0xCC, 0xD4, 0xDC):
            return f"call {rom[f - 3]:02x}{rom[f - 2]:02x}{rom[f - 1]:02x}"
        if f >= 1 and rom[f - 1] & 0xC7 == 0xC7:
            return f"rst {rom[f - 1]:02x}"
        return ""

    stacks = json.loads(path.read_text(encoding="utf-8"))
    # which stack bytes vary, per phase and SP (the fingerprint can only use the constant ones)
    groups: dict = {}
    for st in stacks:
        groups.setdefault((st["phase"], st["sp"]), []).append(st)
    for (phase, sp), rows in groups.items():
        datas = [bytes.fromhex(r["bytes"]) for r in rows]
        vary = [i for i in range(32) if len({d[i] for d in datas}) > 1]
        print(f"[vary] {phase} SP={sp}: {len(rows)} distinct / {sum(r['count'] for r in rows)} samples; varying sp+ {vary}")
    for st in stacks:
        data = bytes.fromhex(st["bytes"])
        bank = int(st["rombank"], 16)
        print()
        print(f"[{st['phase']}] x{st['count']} SP={st['sp']} hROMBank={st['rombank']} SVBK={st['svbk']}")
        for off in range(0, 32, 2):
            w = data[off] | data[off + 1] << 8
            if w < 0x4000:
                tag = f"00:{w:04X} {name(0, w)} {after_call(0, w)}"
            elif w < 0x8000:
                # call-shaped banks first (sampled bank, then the overworld/script bank $25, then the rest)
                order = list(dict.fromkeys([bank, 0x25, *range(len(rom) // 0x4000)]))
                banks = [b for b in order if after_call(b, w)] or [bank]
                tag = "; ".join(f"{b:02X}:{w:04X} {name(b, w)} {after_call(b, w)}" for b in banks[:2])
                if len(banks) > 2:
                    tag += f" (+{len(banks) - 2} more call-shaped banks)"
            else:
                tag = "(RAM/data)"
            print(f"  sp+{off:<2} {w:04X}  {tag}")


def cmd_clean() -> int:
    for sub in ("setup", "live", "sram"):
        p = LANE / sub
        if p.exists():
            shutil.rmtree(p)
    return 0


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else ""
    raise SystemExit({"setup": cmd_setup, "live": cmd_live, "control": cmd_control, "explore": cmd_explore, "clean": cmd_clean}.get(which, lambda: print(__doc__) or 2)())
