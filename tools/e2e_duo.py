#!/usr/bin/env python3
"""e2e_duo.py — TWO-INSTANCE headless E2E harness for the SLink companion patch.

Runs a throwaway SLink server + two concurrent EmuHawk instances (players a/b), both
loading savestates from the SAME save (instance B mutates its party OTIDs pre-hello so
mon keys don't collide in the server's flat key index), then orchestrates a scenario
via the server's debug HTTP API and waits for both instances' result files.

    python tools/e2e_duo.py --scenario faint
    python tools/e2e_duo.py --scenario all --keep-alive

Per instance: a generated stub (patch/build/duo_{a,b}.lua) bakes SLINK_HOST/PORT/PLAYER
plus the SLINK_DUO table and dofiles lua/tests/duo/duo_main.lua, which runs the REAL
production client and the scenario coroutine (lua/tests/duo/scenario_<name>.lua).
Result protocol: patch/build/e2e_<scenario>_{a,b}_result.txt — incremental log lines,
"MYKEY <slot> <key>" markers, final "RESULT: PASS|FAIL".

Launch rules (hard-won): CWD = repo root with RELATIVE EmuHawk arg paths (absolute paths
containing the "Google Drive" space break BizHawk's CLI parser); absolute paths are fine
INSIDE Lua. Per-instance --config copies avoid the shared config.ini write race.
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMUHAWK = "E:/Howard/Bizhawk/EmuHawk.exe"
BIZHAWK_CONFIG = "E:/Howard/Bizhawk/config.ini"
SAVESTATE_DIR = "E:/Howard/Bizhawk/GBA/State"
ROM_REL = "patch/build/slink_RR.gba"
BUILD = os.path.join(REPO, "patch", "build")
WT_FWD = REPO.replace("\\", "/")

# Per-scenario knobs: extra server flags, savestate (str, or {"a":…,"b":…}), per-side timeout,
# and `games` — which titles a scenario applies to (default: gen3_rr only, since that is
# what this harness was built for). Gen 1-only scenarios have no savestate at all, so
# tests/e2e/test_duo.py must not try to run them.
# (seconds), fillers (default True; or {"a":…,"b":…} — explode keeps B at ONE mon so the
# Explosion self-faint whites out instead of opening the switch menu).
SCENARIOS = {
    "faint":   {"flags": [], "savestate": "slink_overworld.State", "timeout": 420},
    "boxsync": {"flags": [], "savestate": "slink_overworld.State", "timeout": 420},
    # Gen 1 only for now: both halves die, then the pair is buried in Box 12.
    "memorialize": {"flags": [], "timeout": 300, "games": ("gen1",)},
    # Gen 1 does the rival swap from pure RAM — no companion patch, unlike Gen 3.
    "rivalswap": {"flags": ["--rival-team-swap"], "timeout": 300, "games": ("gen1",)},
    # Gen 1 explode: RAM-only, no companion patch. Distinct from the Gen 3 "explode" entry
    # below, which loads savestates and keeps B at a single mon.
    "explode_g1": {"flags": ["--explode-mode"], "timeout": 300, "games": ("gen1",)},
    # The only scenario that PLAYS. Both instances walk Route 1's grass, meet a real wild
    # Pokemon and throw a real ball; the link is formed by the server from the resulting
    # `capture` events. Nothing is injected and the Nuzlocke gate comes from the real bag,
    # so this is the only coverage of encounter linking, area_enter and the ball gate.
    "playthrough": {"flags": [], "timeout": 1500, "games": ("gen1",),
                    "target": "battle", "no_setup": True, "frames": 200000},
    "trade":   {"flags": [], "savestate": "slink_overworld.State", "timeout": 420},
    "ghost":   {"flags": ["--overworld-presence"], "savestate": "slink_overworld.State",
                "timeout": 420},
    # The native panel needs the RR patch present and a formed pair; no extra server flags.
    "infopanel": {"flags": [], "savestate": "slink_overworld.State", "timeout": 420},
    "explode": {"flags": ["--explode-mode"],
                "savestate": {"a": "slink_overworld.State", "b": "slink_prebattle.State"},
                "fillers": {"a": True, "b": False}, "timeout": 600},
}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def api(http_port, method, path, body=None, timeout=10):
    url = f"http://127.0.0.1:{http_port}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def read_result(scenario, inst):
    path = os.path.join(BUILD, f"e2e_{scenario}_{inst}_result.txt")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def wait_for(desc, pred, timeout, interval=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = pred()
        if v:
            return v
        time.sleep(interval)
    raise TimeoutError(f"timed out after {timeout}s waiting for {desc}")


def extract_keys(text):
    """MYKEY <slot> <key> lines -> {slot: key}."""
    keys = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "MYKEY":
            keys[int(parts[1])] = parts[2]
    return keys


def extract_marks(text, tag):
    """'<tag> <value>' lines -> [values]."""
    out = []
    for line in (text or "").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0] == tag:
            out.append(parts[1])
    return out


# ── Games ────────────────────────────────────────────────────────────────────
# The duo harness was written for Radical Red and hardcoded to it. Gen 1 differs in three
# ways that matter, so the per-game bits live here rather than being threaded through:
#
#   * NO SAVESTATE. Gen 1 boots from a battery save (tests/fixtures/gen1/*.SaveRAM), which
#     is not BizHawk-version-locked the way a .State is — nothing to rebuild after an
#     emulator upgrade.
#   * DIFFERENT CARTRIDGES per instance: A is Red, B is Blue. Closer to how the feature is
#     actually played, and the two cannot collide over BizHawk's SaveRAM because it names
#     saves from its own gamedb entry.
#   * Its own duo wrapper, since the boot and the HP endianness differ.
#
# gen3_rr keeps exactly the previous behaviour and stays the default.
GAMES = {
    "gen3_rr": {
        "main": "lua/tests/duo/duo_main.lua",
        "rom": {"a": ROM_REL, "b": ROM_REL},
        "uses_savestate": True,
        "scenario_prefix": "",
    },
    "gen1": {
        "main": "lua/tests/duo/duo_gen1_main.lua",
        "rom": {"a": "patch/build/gen1_red.gb", "b": "patch/build/gen1_blue.gb"},
        "uses_savestate": False,
        "fixture": {"a": "red", "b": "blue"},
        "scenario_prefix": "gen1_",
    },
    # Yellow paired against Red. Yellow shifts nearly every WRAM address by -1, and until now
    # it only ever ran SINGLE-instance gates — no duo, so no Yellow address had ever been
    # exercised through the server, and none of its WRITE paths had run alongside a partner.
    # Pairing it with Red rather than another Yellow means a shift bug shows up as an
    # asymmetry between the two halves instead of cancelling out.
    "gen1_yellow": {
        "main": "lua/tests/duo/duo_gen1_main.lua",
        "rom": {"a": "patch/build/gen1_yellow.gbc", "b": "patch/build/gen1_red.gb"},
        "uses_savestate": False,
        "fixture": {"a": "yellow", "b": "red"},
        "scenario_prefix": "gen1_",
    },
}


class DuoRun:
    def __init__(self, scenario, args):
        self.scenario = scenario
        self.cfg = SCENARIOS[scenario]
        self.args = args
        self.game = getattr(args, "game", "gen3_rr")
        # Family, not id. Gen 1 has more than one duo configuration (red/blue, yellow/red)
        # and every `== "gen1"` check silently sent the others down the Gen 3 path.
        self.is_gen1 = self.game.startswith("gen1")
        self.gcfg = GAMES[self.game]
        self.tcp_port = free_port()
        self.http_port = free_port()
        self.data_dir = tempfile.mkdtemp(prefix=f"slink_duo_{scenario}_")
        self.server = None
        self.emus = []
        self.go_files = {inst: os.path.join(BUILD, f"duo_go_{scenario}_{inst}.txt")
                         for inst in ("a", "b")}

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start_server(self):
        cmd = [sys.executable, "-m", "server.server",
               "--host", "127.0.0.1",
               "--port", str(self.tcp_port),
               "--http-port", str(self.http_port),
               "--data-dir", self.data_dir] + self.cfg["flags"] + self.args.server_flags
        self.server = subprocess.Popen(
            cmd, cwd=REPO,
            stdout=open(os.path.join(self.data_dir, "server.log"), "w"),
            stderr=subprocess.STDOUT)
        wait_for("server HTTP up", lambda: self._status() is not None, 30)
        print(f"[duo] server up: tcp={self.tcp_port} http={self.http_port} data={self.data_dir}")

    def _status(self):
        try:
            return api(self.http_port, "GET", "/api/status", timeout=3)
        except Exception:
            return None

    def start_instances(self):
        if self.is_gen1:
            from gen1_playthrough import staged_rom
            for key in self.gcfg["fixture"].values():
                staged_rom(key)     # space-free copy; BizHawk's CLI splits on spaces
        for inst in ("a", "b"):
            for f in (self._result_path(inst), self.go_files[inst]):
                if os.path.exists(f):
                    os.remove(f)
        for inst in ("a", "b"):
            cfg_ini = os.path.join(BUILD, f"duo_cfg_{inst}.ini")
            if self.is_gen1:
                # Muted, on the second monitor: two emulators for several minutes each.
                from gen1_playthrough import write_run_config
                write_run_config(BIZHAWK_CONFIG, cfg_ini)
            else:
                shutil.copyfile(BIZHAWK_CONFIG, cfg_ini)
            stub = os.path.join(BUILD, f"duo_{inst}.lua")
            fillers = self.cfg.get("fillers", True)
            duo = {
                "wt": WT_FWD, "player": inst, "scenario": self.scenario,
                "fillers": fillers[inst] if isinstance(fillers, dict) else fillers,
                "mutate_otid": inst == "b",
                "result": f"{WT_FWD}/patch/build/e2e_{self.scenario}_{inst}_result.txt",
                # So an instance can wait for its partner to finish before exiting —
                # client.exit() kills the emulator, and a side that leaves early stops
                # sending the very events the other side is waiting on.
                "partner_result": (f"{WT_FWD}/patch/build/e2e_{self.scenario}_"
                                   f"{'b' if inst == 'a' else 'a'}_result.txt"),
                "go_file": self.go_files[inst].replace("\\", "/"),
                # Scenarios that PLAY the game need a frame budget set by how long the game
                # takes, not by the wall-clock timeout: at 400x, timeout*60 runs out mid-hunt.
                "timeout_frames": self.cfg.get("frames", self.cfg["timeout"] * 60),
            }
            if self.gcfg["uses_savestate"]:
                ss = self.cfg["savestate"]
                duo["savestate"] = f"{SAVESTATE_DIR}/{ss[inst] if isinstance(ss, dict) else ss}"
            else:
                # Seed this instance's battery save. Red and Blue get different filenames
                # from BizHawk's gamedb, so the two instances never fight over one file.
                from run_gen1_gate import seed_saveram
                seed_saveram(self.gcfg["fixture"][inst], self.cfg.get("target", "town"))
            with open(stub, "w") as f:
                f.write('SLINK_HOST = "127.0.0.1"\n')
                f.write(f"SLINK_PORT = {self.tcp_port}\n")
                f.write(f'SLINK_PLAYER = "{inst}"\n')
                f.write("SLINK_DUO = {\n")
                for k, v in duo.items():
                    if isinstance(v, str):
                        f.write(f'  {k} = "{v}",\n')
                    elif isinstance(v, bool):
                        f.write(f"  {k} = {str(v).lower()},\n")
                    else:
                        f.write(f"  {k} = {v},\n")
                f.write("}\n")
                f.write(f'dofile("{WT_FWD}/{self.gcfg["main"]}")\n')
            p = subprocess.Popen(
                [EMUHAWK, f"--config=patch/build/duo_cfg_{inst}.ini",
                 f"--lua=patch/build/duo_{inst}.lua", self.gcfg["rom"][inst]],
                cwd=REPO)
            self.emus.append(p)
        print("[duo] two EmuHawk instances launched")

    def wait_keys(self):
        """Both wrappers log MYKEY lines right after savestate+mutation."""
        def both():
            ka = extract_keys(read_result(self.scenario, "a"))
            kb = extract_keys(read_result(self.scenario, "b"))
            return (ka, kb) if ka and kb else None
        ka, kb = wait_for("MYKEY lines from both instances", both, 120)
        if set(ka.values()) & set(kb.values()):
            raise RuntimeError(f"key collision between instances: {ka} vs {kb}")
        print(f"[duo] keys: a={ka.get(0)} b={kb.get(0)}")
        return ka, kb

    def wait_connected(self):
        def both():
            st = self._status()
            if not st:
                return None
            players = st.get("players", {})
            return (players.get("a", {}).get("connected")
                    and players.get("b", {}).get("connected")) or None
        wait_for("both players hello'd", both, 120)
        print("[duo] both players connected")

    def inject_link(self, a_key, b_key, area_id="duo"):
        def linked():
            try:
                r = api(self.http_port, "POST", "/api/inject_link",
                        {"a_key": a_key, "b_key": b_key, "area_id": area_id, "force": True})
                return r if r.get("ok") else None
            except Exception:
                return None
        wait_for("inject_link", linked, 60)
        print(f"[duo] linked {a_key} <-> {b_key}")

    def assert_real_link_formed(self):
        """The whole point of the playthrough scenario.

        Both instances catch a wild mon through actual play; the server must pair those two
        captures BY AREA on its own. Nothing here injects anything — if encounter linking is
        broken, no link appears and this raises. This is the only assertion in the suite that
        covers the rule SLink exists for.
        """
        def caught(inst):
            txt = read_result(self.scenario, inst) or ""
            for line in txt.splitlines():
                if "CAUGHT " in line:
                    return line.split("CAUGHT ", 1)[1].split()[0]
            return None

        def both_caught():
            a, b = caught("a"), caught("b")
            return (a, b) if a and b else None

        a_key, b_key = wait_for("both instances to catch a wild mon", both_caught,
                                self.cfg["timeout"])
        print(f"[duo] real captures: a={a_key} b={b_key}")

        def linked():
            st = self._status() or {}
            for link in (st.get("links") or []):
                keys = {link.get("a_key"), link.get("b_key")}
                if keys == {a_key, b_key}:
                    return link
            return None

        link = wait_for("the SERVER to pair the two real captures", linked, 180)
        area = link.get("area_id")
        print(f"[duo] ENCOUNTER LINK FORMED FROM REAL PLAY: "
              f"{a_key} <-> {b_key} in area={area}")
        if area in (None, "", "duo"):
            raise RuntimeError(f"link formed but area_id is {area!r} — expected a real "
                               f"encounter area resolved from the map, not a harness value")

    def go(self, lines_by_inst=None):
        """Write the per-instance go-files; lines_by_inst = {"a": [...], "b": [...]} or None."""
        for inst in ("a", "b"):
            with open(self.go_files[inst], "w") as f:
                for l in (lines_by_inst or {}).get(inst, []):
                    f.write(l + "\n")
                f.write("GO\n")
        print("[duo] go-files written")

    def set_pokeballs(self):
        """Faints are suppressed server-side until the nuzlocke is active (pokéballs obtained)."""
        for p in ("a", "b"):
            r = api(self.http_port, "POST", "/api/debug/set_pokeballs",
                    {"player": p, "value": True})
            if not r.get("ok"):
                raise RuntimeError(f"set_pokeballs failed: {r}")
        print("[duo] pokeballs_obtained set for both players")

    def queue_command(self, player, cmd):
        body = dict(cmd)
        body["player"] = player
        r = api(self.http_port, "POST", "/api/debug/queue_command", body)
        if not r.get("ok"):
            raise RuntimeError(f"queue_command failed: {r}")
        print(f"[duo] queued for {player}: {cmd}")

    def wait_results(self):
        def both():
            ra = read_result(self.scenario, "a")
            rb = read_result(self.scenario, "b")
            if ra and "RESULT:" in ra and rb and "RESULT:" in rb:
                return ra, rb
            return None
        return wait_for("both RESULT lines", both, self.cfg["timeout"])

    def _result_path(self, inst):
        return os.path.join(BUILD, f"e2e_{self.scenario}_{inst}_result.txt")

    def cleanup(self, passed):
        for p in self.emus:
            if p.poll() is None:
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                               capture_output=True)
        if self.server and self.server.poll() is None:
            self.server.terminate()
            try:
                self.server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.server.kill()
        for gf in self.go_files.values():
            if os.path.exists(gf):
                os.remove(gf)
        if passed and not self.args.keep_data:
            shutil.rmtree(self.data_dir, ignore_errors=True)
        else:
            print(f"[duo] data dir kept: {self.data_dir}")

    # ── per-scenario orchestration ───────────────────────────────────────────
    def orchestrate(self):
        ka, kb = self.wait_keys()
        self.wait_connected()
        if self.cfg.get("no_setup"):
            # Deliberately does NOT call set_pokeballs() or inject_link(): this scenario
            # exists to prove the paths those shortcuts bypass. The fixture carries real
            # Poke Balls, so the gate flips from the client's own bag read.
            self.go()
            self.assert_real_link_formed()
            return
        self.set_pokeballs()
        if self.scenario == "infopanel":
            # THREE pairs, not one: 3 pairs (6 rows) + 3 summary rows = 9 rows = 2 pages, which is
            # what makes the pagination half of the scenario meaningful. One pair fits on a single
            # page and would never exercise it.
            for i in range(min(3, len(ka), len(kb))):
                self.inject_link(ka[i], kb[i], area_id=f"duo{i}")
            self.go()
        elif self.scenario in ("faint", "memorialize", "explode_g1"):
            self.inject_link(ka[0], kb[0])
            self.go()
        elif self.scenario == "rivalswap":
            # No link needed: the swap is gated on the rival id and the partner having
            # cached blobs, not on a formed pair. Go straight away and let A drive.
            self.go()
        elif self.scenario == "explode":
            self.inject_link(ka[0], kb[0])
            # B must be inside a LIVE battle before A's faint fires the force_explode (a
            # frozen battle savestate can't execute the coerced turn — foe never commits).
            wait_for("B inside a live battle",
                     lambda: "IN_BATTLE" in (read_result(self.scenario, "b") or ""), 240)
            self.go()
        elif self.scenario == "boxsync" and self.is_gen1:
            # Gen 1 exercises the RULE, not the storage opcodes: link the pair, then let A
            # deposit its own half. The server's _handle_party_to_box is what must send
            # box_mon to B — nothing is injected here, so a broken rule cannot be masked by
            # the harness doing the work itself.
            self.inject_link(ka[0], kb[0])
            self.go()
        elif self.scenario == "boxsync":
            # Symmetric: BOTH sides deposit their slot-1 filler, then withdraw it statless
            # (native OP_DEPOSIT_MON / OP_WITHDRAW_MON; the Lua asserts live in the scenario).
            self.go()
            self.queue_command("a", {"cmd": "box_mon", "key": ka[1]})
            self.queue_command("b", {"cmd": "box_mon", "key": kb[1]})
            for inst, key in (("a", ka[1]), ("b", kb[1])):
                wait_for(f"{inst} deposit done",
                         lambda i=inst: "DEPOSIT_DONE" in (read_result(self.scenario, i) or ""),
                         180)
                self.queue_command(inst, {"cmd": "party_mon", "key": key})
        elif self.scenario == "trade":
            # MVP scripted trade: no inject_link (the server menu flow is pytest-covered, and a
            # link whose halves swap owners behind the server's back would just feed the
            # reconciler). Cross-inject apply_trade with each side's slot-0 blob.
            def blobs():
                ba = extract_marks(read_result(self.scenario, "a"), "MYBLOB")
                bb = extract_marks(read_result(self.scenario, "b"), "MYBLOB")
                return (ba[0], bb[0]) if ba and bb else None
            blob_a, blob_b = wait_for("MYBLOB from both", blobs, 120)
            self.queue_command("a", {"cmd": "apply_trade", "slot": 0, "blob_hex": blob_b,
                                     "token": "duo"})
            self.queue_command("b", {"cmd": "apply_trade", "slot": 0, "blob_hex": blob_a,
                                     "token": "duo"})
            # The partner's pre-trade key rides in each go-file (blob bytes 0-3 PID, 4-7 OTID).
            def key_of(blob):
                pid = int.from_bytes(bytes.fromhex(blob[:8]), "little")
                otid = int.from_bytes(bytes.fromhex(blob[8:16]), "little")
                return f"{pid:08X}:{otid:08X}"
            self.go({"a": [f"PARTNER {key_of(blob_b)}"],
                     "b": [f"PARTNER {key_of(blob_a)}"]})
        elif self.scenario == "ghost":
            self.go()
        else:
            raise ValueError(self.scenario)

    def run(self):
        passed = False
        try:
            self.start_server()
            self.start_instances()
            self.orchestrate()
            ra, rb = self.wait_results()
            pa = "RESULT: PASS" in ra
            pb = "RESULT: PASS" in rb
            passed = pa and pb
            print(f"[duo] {self.scenario}: a={'PASS' if pa else 'FAIL'} "
                  f"b={'PASS' if pb else 'FAIL'}")
            if not passed:
                for inst, text in (("a", ra), ("b", rb)):
                    print(f"--- {self.scenario} {inst} result ---")
                    print("\n".join(text.splitlines()[-25:]))
            if self.args.keep_alive:
                input("[duo] --keep-alive: press Enter to tear down…")
        finally:
            self.cleanup(passed)
        return passed


def main():
    # The client logs contain Unicode arrows; don't let a cp1252 console kill the runner.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game", default="gen3_rr", choices=sorted(GAMES),
                    help="gen3_rr (Radical Red, default) or gen1 (Red as A, Blue as B)")
    ap.add_argument("--scenario", default="faint",
                    choices=list(SCENARIOS) + ["all"])
    ap.add_argument("--keep-alive", action="store_true",
                    help="pause before teardown for manual inspection")
    ap.add_argument("--keep-data", action="store_true",
                    help="never delete the temp server data dir")
    ap.add_argument("--server-flags", nargs="*", default=[],
                    help="extra flags for server.server")
    args = ap.parse_args()

    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    results = {}
    for name in names:
        print(f"\n========== scenario: {name} ==========")
        results[name] = DuoRun(name, args).run()
    print("\n========== summary ==========")
    for name, ok in results.items():
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
