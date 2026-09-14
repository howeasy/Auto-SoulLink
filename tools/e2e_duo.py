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
import importlib
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

# Per-scenario knobs: extra server flags, savestate (str, or {"a":…,"b":…}), per-side timeout
# (seconds), fillers (default True; or {"a":…,"b":…} — explode keeps B at ONE mon so the
# Explosion self-faint whites out instead of opening the switch menu), and `games`.
#
# `games` is which titles a scenario applies to. ABSENT MEANS EVERY TITLE — read it through
# scenarios_for(), never inline.
#
# An entry matches the FAMILY as well as the exact id: ("gen1",) covers gen1_yellow, the same
# way the `is_gen1` check does. Without that, adding a second Gen 1 pairing would mean editing
# the tuple on every scenario it inherits, and forgetting one silently drops coverage.
#
# This key was declared and documented here for a long time while nothing but
# tests/e2e/test_duo.py read it, so `--scenario all` expanded to the whole table regardless of
# --game: Gen 3-only scenarios were run against a Game Boy, where they died on the savestate
# they declare and no GB fixture has.
SCENARIOS = {
    "faint":   {"flags": [], "savestate": "slink_overworld.State", "timeout": 420},
    "boxsync": {"flags": [], "savestate": "slink_overworld.State", "timeout": 420},
    # Both halves die, then the pair is buried in the generation's graveyard box — Box 12 on
    # Gen 1, Box 14 on Gen 2. Gen 3 has its own memorial path and is not covered here.
    "memorialize": {"flags": [], "timeout": 300, "games": ("gen1", "gen2")},
    # Gen 1 does the rival swap from pure RAM — no companion patch, unlike Gen 3.
    "rivalswap": {"flags": ["--rival-team-swap"], "timeout": 300, "games": ("gen1",)},
    # Gen 1 explode: RAM-only, no companion patch. Distinct from the Gen 3 "explode" entry
    # below, which loads savestates and keeps B at a single mon.
    "explode_g1": {"flags": ["--explode-mode"], "timeout": 300, "games": ("gen1",)},
    # A poisons its last mon to death and takes pokered's real HandleBlackOut. Longer than
    # `faint` because it walks for the poison tick, mashes through two text boxes and then
    # waits out the auto-rebuild round trip.
    "whiteout": {"flags": [], "timeout": 600, "games": ("gen1",)},
    # The only scenario that PLAYS. Both instances walk Route 1's grass, meet a real wild
    # Pokemon and throw a real ball; the link is formed by the server from the resulting
    # `capture` events. Nothing is injected and the Nuzlocke gate comes from the real bag,
    # so this is the only coverage of encounter linking, area_enter and the ball gate.
    "playthrough": {"flags": [], "timeout": 1500, "games": ("gen1",),
                    "target": "battle", "no_setup": True, "frames": 200000},
    # A meets a real wild Pokemon and KILLS it — a genuine failed encounter, no ball spent —
    # which must lock the area for BOTH players. B is released only once the SERVER reports
    # the lock, then catches there and must have the catch taken away.
    "deadzone": {"flags": [], "timeout": 1500, "games": ("gen1",),
                 "target": "battle", "no_setup": True, "frames": 200000},
    # Species clause. Both cartridges point their wild table at ONE species, both catch it in
    # the same area, and the later capture must be rejected as a same-family duplicate.
    "dupes": {"flags": ["--species-clause"], "timeout": 1500, "games": ("gen1",),
              "target": "battle", "no_setup": True, "frames": 200000},
    # NEW Gen 1 client (lua/gen1/*, game "gen1_new"): docs/gen1_requirements.md D-1 and D-3
    # from real play through lua/tests/duo/duo_gen1_main.lua. Both battle fixtures carry
    # exactly ONE Poke Ball, so each side gets one throw; the hunt fights one Tackle first
    # when the foe is at full HP (lua/tests/gen1_rb_hunt_inputs.lua).
    # `frames` is only a runaway guard: the main runs at 16x, so 150000 frames (~156 s) expired
    # inside a wall-clock wait; the real bound is `timeout`, enforced by this runner's cleanup.
    "link_new": {"flags": [], "timeout": 900, "games": ("gen1_new",),
                 "target": "battle", "no_setup": True, "frames": 2000000},
    "deadzone_new": {"flags": [], "timeout": 900, "games": ("gen1_new",),
                     "target": "battle", "no_setup": True, "frames": 2000000},
    "linked_faint_bench_new": {"flags": [], "timeout": 1500, "games": ("gen1_new",),
                               "target": "battle", "no_setup": True, "frames": 2500000},
    "linked_faint_active_new": {"flags": [], "timeout": 1500, "games": ("gen1_new",),
                                "target": "battle", "no_setup": True, "frames": 2500000},
    "reconnect_new": {"flags": [], "timeout": 900, "games": ("gen1_new",),
                      "target": "battle", "no_setup": True, "frames": 2000000},
    # T-3/T-4 needs the companion trade bank, unlike the encounter-only new-client lanes.
    "trade_new": {"flags": [], "timeout": 1500, "games": ("gen1_new",),
                  "target": "battle", "no_setup": True, "frames": 2500000,
                  "rom": {"a": "patch/gen1/build/slink_red.gb",
                          "b": "patch/gen1/build/slink_blue.gb"},
                  "patched_saves": {"a": "red_patched", "b": "blue_patched"}},
    # F-4: one randomized Red hello admitted, clean Blue rejected against its randomized
    # Blue contract. The second UPR output is required by prepare_pair but is not launched.
    "admit_randomized_new": {"flags": [], "timeout": 1800, "games": ("gen1_new",),
                             "target": "town", "no_setup": True, "frames": 100000},
    # The four below are Gen 3-only and say so explicitly. They load Radical Red savestates
    # and two of them need the RR companion patch, so there is nothing for a Game Boy to run.
    "trade":   {"flags": [], "savestate": "slink_overworld.State", "timeout": 420,
                "games": ("gen3_rr",)},
    "ghost":   {"flags": ["--overworld-presence"], "savestate": "slink_overworld.State",
                "timeout": 420, "games": ("gen3_rr",)},
    # The native panel needs the RR patch present and a formed pair; no extra server flags.
    "infopanel": {"flags": [], "savestate": "slink_overworld.State", "timeout": 420,
                  "games": ("gen3_rr",)},
    "explode": {"flags": ["--explode-mode"],
                "savestate": {"a": "slink_overworld.State", "b": "slink_prebattle.State"},
                "fillers": {"a": True, "b": False}, "timeout": 600,
                "games": ("gen3_rr",)},
}


def scenario_applies(name, game):
    """Does `name` apply to `game`? Absent `games` means every title; entries match families."""
    allowed = SCENARIOS[name].get("games")
    return allowed is None or any(game == a or game.startswith(a + "_") for a in allowed)


def scenarios_for(game):
    """The scenarios that apply to `game`, in table order.

    The single source of truth for that question — tests/e2e/test_duo.py used to hand-roll
    its own copy with a different default, which is how the two answers drifted apart.
    """
    return [n for n in SCENARIOS if scenario_applies(n, game)]


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


RNG_OUT_OF_BALLS = "RESULT: FAIL (hunt ended out-of-balls)"
# Classification table for RESULT reasons in duo_gen1_main.lua:286-758:
#   CAUSE_RNG   bare/nested `hunt ended out-of-balls` (the game's only missed ball)
#   CONSEQUENCE exact linked-capture-not-returned phrases when the other side has CAUSE_RNG
#   FINAL       every other return-false template: no-go/boot/save, other hunt phase,
#               trade menu/prompt/apply, faint window/force_faint/battle/text/Box 12,
#               and admission hello/party/map errors. A nested link prerequisite with
#               any cause OTHER than out-of-balls is FINAL, too.
GEN1_RNG_REASON_CLASS = {
    "hunt ended out-of-balls": "CAUSE_RNG",  # link_new/deadzone_new direct
    "link_new prerequisite failed: hunt ended out-of-balls": "CAUSE_RNG",  # nested trade/faint
    "linked capture was not returned": "CONSEQUENCE",  # linked_faint_* without pair
    "linked capture was not returned to party": "CONSEQUENCE",  # trade_new without pair
    "B could not hold its linked mon active: out-of-balls": "FINAL",  # switch-turn death, not catch RNG
}


class GameRngMiss(Exception):
    """The only early orchestration exit eligible for a whole-run Gen 1 retry."""


def classify_gen1_result(text):
    """PASS, CAUSE_RNG, CONSEQUENCE, FINAL, or None for missing/ambiguous RESULT."""
    lines = [line.strip() for line in (text or "").splitlines() if line.startswith("RESULT:")]
    if len(lines) != 1:
        return None
    line = lines[0]
    if line.startswith("RESULT: PASS"):
        return "PASS"
    if not line.startswith("RESULT: FAIL (") or not line.endswith(")"):
        return "FINAL"
    return GEN1_RNG_REASON_CLASS.get(line[len("RESULT: FAIL ("):-1], "FINAL")


def _has_exact_rng_miss(text):
    return classify_gen1_result(text) == "CAUSE_RNG"


def retryable_gen1_rng(game, results, attempt):
    """Only a game's missed sole ball may restart one whole gen1_new run."""
    if game != "gen1_new" or attempt != 1:
        return False
    classes = [classify_gen1_result(text) for text in results.values()]
    return "CAUSE_RNG" in classes and all(c in ("CAUSE_RNG", "CONSEQUENCE", "PASS") for c in classes)


RECONNECT_GAMEPLAY_EVENTS = ("capture", "linked", "no_catch", "dead_zone")


def _event_counts(rows):
    return {name: sum(row.get("type") == name for row in rows) for name in RECONNECT_GAMEPLAY_EVENTS}


def reconnect_same_problems(before, after, events_before, events_after, linked_key, ot_id):
    """Public/persisted C-2 facts; empty means a safe same-save reconnect."""
    problems = []
    a = (after.get("status", {}).get("players") or {}).get("a") or {}
    b = (after.get("status", {}).get("players") or {}).get("b") or {}
    if not a.get("connected") or a.get("identity_error"):
        problems.append("A did not reconnect with accepted identity")
    if not b.get("connected"):
        problems.append("B stopped being connected during A relaunch")
    if linked_key not in (a.get("party_keys") or []):
        problems.append("A's resumed party lacks the linked key")
    if before.get("links") != after.get("links"):
        problems.append("the link changed across the same-save relaunch")
    if str((after.get("player_identity", {}).get("a") or {}).get("ot_id")) != str(ot_id):
        problems.append("A's locked OT ID changed")
    if _event_counts(events_before) != _event_counts(events_after):
        problems.append("a capture/link/no_catch/dead_zone event duplicated")
    new_hellos = [row for row in events_after if row.get("type") == "hello" and row.get("player") == "a"]
    old_hellos = [row for row in events_before if row.get("type") == "hello" and row.get("player") == "a"]
    if len(new_hellos) != len(old_hellos) + 1 or not any(
            row.get("text", "").startswith("Connected (Red, ") for row in new_hellos):
        problems.append("A did not add exactly one accepted reconnect hello")
    return problems


def reconnect_wrong_problems(before_bytes, after_bytes, status, events_before, events_after):
    """C-1: only the rejected hello event is allowed; the link file is byte-identical."""
    problems = []
    a = (status.get("players") or {}).get("a") or {}
    if "Identity mismatch for slot A" not in (a.get("identity_error") or ""):
        problems.append("A's different-OT save was not rejected")
    if not ((status.get("players") or {}).get("b") or {}).get("connected"):
        problems.append("B disconnected during A's wrong-save rejection")
    if before_bytes != after_bytes:
        problems.append("links.json bytes changed after the rejected hello")
    if _event_counts(events_before) != _event_counts(events_after):
        problems.append("a rejected save added a gameplay event")
    new_hellos = [row for row in events_after if row.get("type") == "hello" and row.get("player") == "a"]
    old_hellos = [row for row in events_before if row.get("type") == "hello" and row.get("player") == "a"]
    if len(new_hellos) != len(old_hellos) + 1 or not any(
            row.get("text") == "REJECTED — wrong save/slot" for row in new_hellos):
        problems.append("A did not add exactly one WRONG SAVE rejection hello")
    return problems


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
#   * The shared GB duo wrapper (duo_gb_main.lua), since the boot and the HP endianness
#     differ from Gen 3. Gen 2 uses the same one.
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
        "main": "lua/tests/duo/duo_gb_main.lua",
        "game": "gen1_rby",
        "play": "gen1_playthrough",
        "rom": {"a": "patch/build/gen1_red.gb", "b": "patch/build/gen1_blue.gb"},
        "uses_savestate": False,
        "fixture": {"a": "red", "b": "blue"},
        "scenario_prefix": "gen1_",
    },
    # The NEW Gen 1 client (lua/gen1/entry.lua composition root), Red as A and Blue as B, on
    # the battle fixtures rebuilt from scripted play (tools/gen1_fixtures.py). Only link_new
    # and deadzone_new run here; duo_gen1_main refuses every other scenario name. NOTE the
    # family rule in scenario_applies: `("gen1",)` entries also match "gen1_new", so
    # `--scenario all --game gen1_new` would pull the old scenarios in -- run these two by name.
    "gen1_new": {
        "main": "lua/tests/duo/duo_gen1_main.lua",
        "game": "gen1_new",
        "play": "gen1_playthrough",
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
        "main": "lua/tests/duo/duo_gb_main.lua",
        "game": "gen1_rby",
        "play": "gen1_playthrough",
        "rom": {"a": "patch/build/gen1_yellow.gbc", "b": "patch/build/gen1_red.gb"},
        "uses_savestate": False,
        "fixture": {"a": "yellow", "b": "red"},
        "scenario_prefix": "gen1_",
    },
    # THE SAME CARTRIDGE ON BOTH SIDES. There is one Crystal dump, so this pairing only
    # works because write_run_config gives each instance its own SaveRAM directory: BizHawk
    # names a save from its gamedb entry, keyed on ROM hash rather than the path launched,
    # so two instances would otherwise share one file and stamp on each other.
    #
    # duo_gb_main resolves scenarios as scenario_<prefix><name> then scenario_gb_<name>, so
    # faint/boxsync/memorialize come from the shared files — they are written entirely
    # against ctx and are identical for both generations.
    "gen2": {
        "main": "lua/tests/duo/duo_gb_main.lua",
        "game": "gen2_crystal",
        "play": "gen2_playthrough",
        "rom": {"a": "patch/build/gen2_crystal.gbc", "b": "patch/build/gen2_crystal.gbc"},
        "uses_savestate": False,
        "fixture": {"a": "crystal", "b": "crystal"},
        "scenario_prefix": "gen2_",
    },
}


class DuoRun:
    def __init__(self, scenario, args, attempt=1):
        self.scenario = scenario
        self.attempt = attempt
        self.cfg = SCENARIOS[scenario]
        self.args = args
        self.game = getattr(args, "game", "gen3_rr")
        self.gcfg = GAMES[self.game]
        # What the launch path actually branches on is "does this game boot from a battery
        # save", not which generation it is — Gen 2 needs the identical treatment. Kept as
        # `is_gen1` only where a SCENARIO is genuinely Gen 1-specific.
        self.battery_boot = not self.gcfg["uses_savestate"]
        self.is_gen1 = self.game.startswith("gen1")
        self.tcp_port = free_port()
        self.http_port = free_port()
        self.data_dir = tempfile.mkdtemp(prefix=f"slink_duo_{scenario}_")
        self._pydec_path = (os.path.join(BUILD, f"e2e_{scenario}_pydec_result.txt")
                            if self.game == "gen1_new" else None)
        self.server = None
        self.emus = []
        self.emu_by_inst = {}
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
            # The handle is the server subprocess's stdout and must outlive this call —
            # a `with` would close it out from under the still-running server.
            stdout=open(os.path.join(self.data_dir, "server.log"), "w"),  # noqa: SIM115
            stderr=subprocess.STDOUT)
        wait_for("server HTTP up", lambda: self._status() is not None, 30)
        print(f"[duo] server up: tcp={self.tcp_port} http={self.http_port} data={self.data_dir}")

    def _saveram_dir(self, inst: str) -> str:
        """A SaveRAM directory unique to this SCENARIO and this instance.

        Per-instance is the load-bearing half: two instances of one cartridge (Gen 2 runs
        Crystal on both sides) resolve to the same gamedb SaveRAM filename and would otherwise
        share one file and stamp on each other.

        Per-scenario, NOT per-run — the path is reused across invocations and nothing cleans
        it. That is safe only because `seed_saveram` overwrites the file before every launch,
        which is what actually prevents a crashed run's save leaking into the next one. Do not
        weaken that copy on the assumption this directory is fresh; it isn't.
        """
        return os.path.join(BUILD, f"saveram_{self.scenario}_{inst}")

    def _pydec_note(self, fact):
        """Keep Python oracle facts beside both Lua receipts for the release ledger."""
        line = str(fact).replace("\n", " ")
        print(f"[duo] {line}")
        path = getattr(self, "_pydec_path", None)
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def _status(self):
        try:
            return api(self.http_port, "GET", "/api/status", timeout=3)
        except Exception:
            return None

    def prepare_admit_randomized_new(self):
        """Build the real two-seed contract before the server or either cartridge starts."""
        import hashlib

        if REPO not in sys.path:
            sys.path.insert(0, REPO)  # python tools/e2e_duo.py otherwise has tools/ at sys.path[0]
        from server.adapters.gen1_rom_scan import fingerprint_rom
        from server.upr_pipeline import find_upr_jar, prepare_pair
        from server.upr_settings import build_categories

        jar = find_upr_jar()  # upr_pipeline.py:101-123 searches the main checkout's .cache/upr
        if not jar:
            raise RuntimeError("PokeRandoZX.jar missing; randomized admission cannot be skipped")
        sources = {p: os.path.join(REPO, self.gcfg["rom"][p]) for p in ("a", "b")}
        for player, source in sources.items():
            if not os.path.isfile(source):
                raise FileNotFoundError(f"clean {player} ROM missing: {source}")
        settings = os.path.join(self.data_dir, "settings.rnqs")
        with open(settings, "wb") as handle:
            handle.write(build_categories({"wild"}))  # upr_settings.py:483-491
        # prepare_pair requires BOTH players, writes .gbc outputs and verifies distinct seeds
        # and rule-bearing data (upr_pipeline.py:254-335). One invocation, no retry.
        result = prepare_pair(jar, settings, sources, os.path.join(self.data_dir, "roms"))
        players = result["players"]
        contract = {
            "upr_version": result["upr_version"],
            "settings_sha256": result["settings_sha256"],
            "categories": result["categories"],
            "players": {p: {"fingerprint": players[p]["fingerprint"], "seed": str(players[p]["seed"]),
                            "rom_sha1": players[p]["sha1"]} for p in ("a", "b")},
        }  # Manager-shaped: manager.py:954-964; spec belongs to the registry, not this file.
        # BizHawk opens a .gbc as a Color title and misses the DMG battery save
        # (tools/make_randomized_patched.py:30-34). Stage unchanged bytes under a known
        # space-free .gb basename; never apply UPS or the structural injector in this gate.
        stage_dir = os.path.join(BUILD, "e2e_admit_randomized_new")
        os.makedirs(stage_dir, exist_ok=True)
        stage = os.path.join(stage_dir, "slink_red_randomized.gb")
        shutil.copyfile(players["a"]["output"], stage)
        with open(stage, "rb") as handle:
            staged = handle.read()
        if hashlib.sha1(staged).hexdigest() != contract["players"]["a"]["rom_sha1"]:
            raise RuntimeError("staged randomized Red SHA-1 differs from the contract")
        if fingerprint_rom(staged) != contract["players"]["a"]["fingerprint"]:
            raise RuntimeError("staged randomized Red fingerprint differs from the contract")
        with open(sources["b"], "rb") as handle:
            clean_blue_fingerprint = fingerprint_rom(handle.read())
        if clean_blue_fingerprint == contract["players"]["b"]["fingerprint"]:
            raise RuntimeError("clean Blue equals randomized Blue fingerprint; negative control is invalid")
        self._admit_roms = {"a": os.path.relpath(stage, REPO).replace("\\", "/"),
                            "b": self.gcfg["rom"]["b"]}
        # run_gb_gate.py:47-80: patched/unknown-hash ROMs use the filename-derived SaveRAM
        # name. Seed both that fallback and the clean gamedb name into the same isolated dir.
        from run_gb_gate import GENS

        self._admit_extra_saves = {
            "a": GENS["gen1"]["patched"]["red_rand_patched"][2],
        }
        self._admit_fingerprints = {"expected_b": contract["players"]["b"]["fingerprint"],
                                    "reported_b": clean_blue_fingerprint}
        # server.py:468-505 reads this exact path from --data-dir, including on hello refresh.
        with open(os.path.join(self.data_dir, "rom_contract.json"), "w", encoding="utf-8") as handle:
            json.dump(contract, handle, indent=2)
        print(f"[duo] admission contract staged: A={contract['players']['a']['fingerprint'][:12]} "
              f"B expected={contract['players']['b']['fingerprint'][:12]} "
              f"B clean={clean_blue_fingerprint[:12]}")
        return contract

    def _seed_instance_save(self, inst):
        from run_gb_gate import GENS, seed_saveram

        seeded = seed_saveram(self.gcfg["fixture"][inst], self.cfg.get("target", "town"),
                              dest_dir=self._saveram_dir(inst))
        if self.cfg.get("patched_saves"):
            patch_key = self.cfg["patched_saves"][inst]
            save_name = GENS["gen1"]["patched"][patch_key][2]
            shutil.copyfile(seeded, os.path.join(self._saveram_dir(inst), save_name))
        extra_name = getattr(self, "_admit_extra_saves", {}).get(inst)
        if extra_name:
            shutil.copyfile(seeded, os.path.join(self._saveram_dir(inst), extra_name))
        return seeded

    def _phase_result_path(self, inst, phase="initial"):
        if phase == "initial":
            return self._result_path(inst)
        return os.path.join(BUILD, f"e2e_{self.scenario}_{inst}_{phase}_result.txt")

    def launch_instance(self, inst, *, phase="initial", seed=True, expected_key=""):
        """Launch one cartridge; reconnect phases keep the existing per-instance SaveRAM."""
        cfg_ini = os.path.join(BUILD, f"duo_cfg_{inst}.ini")
        if self.battery_boot:
            from gen1_playthrough import write_run_config

            write_run_config(BIZHAWK_CONFIG, cfg_ini, saveram_dir=self._saveram_dir(inst))
        else:
            shutil.copyfile(BIZHAWK_CONFIG, cfg_ini)
        result = self._phase_result_path(inst, phase)
        if os.path.exists(result):
            os.remove(result)  # stale phase receipts cannot satisfy a new relaunch
        stub = os.path.join(BUILD, f"duo_{inst}.lua")
        fillers = self.cfg.get("fillers", True)
        duo = {
            "wt": WT_FWD, "player": inst, "scenario": self.scenario,
            "phase": phase, "expected_key": expected_key, "attempt": self.attempt,
            "game": self.gcfg.get("game", ""),
            "fillers": fillers[inst] if isinstance(fillers, dict) else fillers,
            "mutate_otid": inst == "b", "result": result.replace("\\", "/"),
            "partner_result": self._result_path("b" if inst == "a" else "a").replace("\\", "/"),
            "go_file": self.go_files[inst].replace("\\", "/"),
            "timeout_frames": self.cfg.get("frames", self.cfg["timeout"] * 60),
        }
        if self.gcfg["uses_savestate"]:
            ss = self.cfg["savestate"]
            duo["savestate"] = f"{SAVESTATE_DIR}/{ss[inst] if isinstance(ss, dict) else ss}"
        elif seed:
            self._seed_instance_save(inst)
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
             f"--lua=patch/build/duo_{inst}.lua",
             getattr(self, "_admit_roms", self.cfg.get("rom", self.gcfg["rom"]))[inst]],
            cwd=REPO)
        self.emus.append(p)
        self.emu_by_inst[inst] = p
        print(f"[duo] launched {inst} phase={phase} seed={seed}")
        return p

    def terminate_instance(self, inst):
        """Harness-only crash; keep the server and the other emulator running."""
        p = self.emu_by_inst[inst]
        if p.poll() is None:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
            p.wait(timeout=15)
        print(f"[duo] terminated {inst} pid={p.pid}; server retained")

    def start_instances(self):
        if self.battery_boot:
            play = importlib.import_module(self.gcfg["play"])
            for key in self.gcfg["fixture"].values():
                play.staged_rom(key)  # space-free relative ROM paths for BizHawk
        for inst in ("a", "b"):
            for f in (self._result_path(inst), self.go_files[inst]):
                if os.path.exists(f):
                    os.remove(f)
        for inst in ("a", "b"):
            self.launch_instance(inst)
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
            self._go_one(inst, (lines_by_inst or {}).get(inst, []))

    def _go_one(self, inst, lines=()):
        """Release ONE instance. Scenarios where B must provably act after A do this rather
        than starting both and hoping the ordering holds."""
        with open(self.go_files[inst], "w") as f:
            for line in lines:
                f.write(line + "\n")
            f.write("GO\n")
        print(f"[duo] go-file written for {inst}")

    # ── result-file readers ──────────────────────────────────────────────────
    def _marks(self, inst, tag):
        return extract_marks(read_result(self.scenario, inst) or "", tag)

    def _caught(self, inst):
        """The key of a mon this instance caught, if it managed to name one.

        TWO SOURCES, BECAUSE THE FIRST IS A RACE THE SCENARIO ALREADY GAVE UP ON.
        `CAUGHT` is printed by the hunt only if it can still read the mon in the party --
        and inside a dead zone the server force-faints and memorialises the capture so
        quickly that it very often cannot. scenario_gen1_deadzone.lua says so in as many
        words ("The return value is a bonus, not a requirement") and asserts on the ball
        count and the memorial instead. This poller was left demanding the line the Lua
        had stopped promising, so a run where the server won the race timed out after
        1500s with both halves of the scenario reporting PASS.

        `REFUSED <key> (<how>)` is the line the scenario does promise, and it carries the
        full key whenever one was recovered at all.
        """
        text = read_result(self.scenario, inst) or ""
        for line in text.splitlines():
            if "CAUGHT " in line:
                return line.split("CAUGHT ", 1)[1].split()[0]
        for line in text.splitlines():
            if "REFUSED " in line:
                key = line.split("REFUSED ", 1)[1].split()[0]
                # "<retired before we could read it>" means no key was ever recovered.
                if key.startswith("<"):
                    return None
                return key
        return None

    def _area(self, inst):
        marks = self._marks(inst, "AREA")
        return marks[0] if marks else None

    def _dead_zone_area(self):
        for area, st in ((self._status() or {}).get("area_states") or {}).items():
            if st == "dead_zone":
                return area
        return None

    def _shared_area(self):
        """The one encounter area both cartridges are standing on."""
        a, b = self._area("a"), self._area("b")
        if not (a and b):
            return None
        if a != b:
            raise RuntimeError(
                f"A is on {a} and B is on {b}. Soul Link pairs and locks BY AREA, so these "
                f"scenarios need both fixtures on one encounter map. All six committed "
                f"battery saves stand on Route 1 at (10,35) — Red, Blue AND Yellow, decoded "
                f"in tests/unit/test_gen1_fixtures.py — so if these disagree the fixtures "
                f"have been rebuilt somewhere else, not inherited from a title difference.")
        return a

    # ── assertions ───────────────────────────────────────────────────────────
    def assert_dead_zone_refusal(self):
        """(a) A real failed encounter locks the area, and the PARTNER is refused there.

        Nothing is injected: A's no_catch comes from the client noticing its own wild battle
        ended with no new party member, and the area lock is read back off the live server
        before B is allowed to move. Withholding B's go-file until then is what makes "B
        caught INSIDE a dead zone" a fact instead of a race.
        """
        self._go_one("a")
        area = wait_for("A's failed encounter to lock an area",
                        self._dead_zone_area, self.cfg["timeout"])
        print(f"[duo] DEAD ZONE FROM REAL PLAY: {area}")
        a_area = self._area("a")
        if a_area and a_area != area:
            raise RuntimeError(f"A played on {a_area} but {area} is what got locked")

        self._go_one("b")
        wait_for("B to report its area", lambda: self._area("b"), 900)
        self._shared_area()      # raises with a readable message if the fixtures disagree

        # Wait on the RETIREMENT, not on B naming the mon. A ball leaving the bag plus the
        # memorial growing is the rule under test; whether B could still read the mon it
        # threw at is a race it does not need to win (see _caught).
        wait_for("B to throw a ball inside the dead zone",
                 lambda: "THREW " in (read_result(self.scenario, "b") or ""),
                 self.cfg["timeout"])
        wait_for("B's client to retire the refused capture",
                 lambda: "REFUSED " in (read_result(self.scenario, "b") or ""), 900)
        b_key = self._caught("b")
        print(f"[duo] B threw in the dead area and the client retired "
              f"{b_key or 'a capture it could not read back'}")

        st = self._status() or {}
        got = (st.get("area_states") or {}).get(area)
        if got != "dead_zone":
            raise RuntimeError(f"{area} is {got!r} after B's capture, not dead_zone — the "
                               f"lock did not survive a capture attempt")
        # Key-specific check, only when B managed to name the mon. Every assertion around
        # it is key-independent on purpose, so losing the race weakens the test by exactly
        # one check instead of failing it.
        if b_key:
            for link in st.get("links") or []:
                if b_key in (link.get("a_key"), link.get("b_key"))                         and link.get("status") == "alive":
                    raise RuntimeError(f"B's dead-zone catch {b_key} formed a LIVE link")
        if ((st.get("pending_captures") or {}).get(area) or {}).get("b"):
            raise RuntimeError(f"B's dead-zone catch is pending in {area} — it was accepted")
        if not [lnk for lnk in (st.get("links") or [])
                if lnk.get("area_id") == area and lnk.get("status") == "dead"]:
            raise RuntimeError(f"no DEAD link entry recorded for {area}")

    def assert_species_clause_rejection(self):
        """(b) The species clause rejects a partner catch from the same evolution family.

        Both cartridges are pointed at one species through wGrassMons, so both meet it for
        real; the server rejects whichever capture arrives second. Neither side knows in
        advance which it will be, so the verdicts are cross-checked here.
        """
        self.go()
        wait_for("both instances to report their area",
                 lambda: self._area("a") and self._area("b"), 900)
        area = self._shared_area()
        keys = wait_for("both instances to catch the forced species",
                        lambda: (self._caught("a"), self._caught("b"))
                        if self._caught("a") and self._caught("b") else None,
                        self.cfg["timeout"])
        print(f"[duo] both caught in {area}: a={keys[0]} b={keys[1]}")

        def verdicts():
            out = {}
            for inst in ("a", "b"):
                text = read_result(self.scenario, inst) or ""
                for tag in ("REJECTED", "KEPT"):
                    if any(ln.startswith(tag + " ") for ln in text.splitlines()):
                        out[inst] = tag
            return out if len(out) == 2 else None

        v = wait_for("both instances to report a verdict", verdicts, 900)
        if sorted(v.values()) != ["KEPT", "REJECTED"]:
            raise RuntimeError(f"expected exactly one rejection, got {v} — with both sides "
                               f"holding the same species the clause must fire exactly once")

        st = self._status() or {}
        if [lnk for lnk in (st.get("links") or []) if lnk.get("area_id") == area]:
            raise RuntimeError(f"a link was recorded in {area} — the clause did not reject")
        pend = ((st.get("pending_captures") or {}).get(area) or {})
        if len(pend) != 1:
            raise RuntimeError(f"expected one surviving pending capture in {area}, got {pend}")
        rejected = next(i for i, tag in v.items() if tag == "REJECTED")
        if rejected in pend:
            raise RuntimeError(f"{rejected} reported REJECTED but its capture is still pending")
        got = (st.get("area_states") or {}).get(area)
        if got not in ("pending_a", "pending_b"):
            raise RuntimeError(f"{area} is {got!r} — a clause rejection must reopen the area "
                               f"for a retry, not lock or link it")
        print(f"[duo] SPECIES CLAUSE: {rejected}'s catch rejected, {area} reopened ({got})")

    # ── NEW Gen 1 client (game gen1_new) ─────────────────────────────────────
    def _links_json(self):
        """The server's persisted link table (carries `cause`, which /api/status does not)."""
        path = os.path.join(self.data_dir, "links.json")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("links") or []

    def _reconnect_document(self):
        with open(os.path.join(self.data_dir, "links.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def _reconnect_events(self):
        path = os.path.join(self.data_dir, "events.json")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def _append_reconnect_marker(self, inst, marker):
        with open(self.go_files[inst], "a", encoding="utf-8") as handle:
            handle.write(marker + "\n")

    def _wrong_red_save_ot(self, path, expected_ot):
        """Require a real, independently played Red save with a different saved trainer ID."""
        from pathlib import Path

        if REPO not in sys.path:
            sys.path.insert(0, REPO)
        from gen1_fixtures import qualify

        from server.adapters import gen1_codec as codec

        source = Path(path)
        name = source.name.lower()
        if (not source.is_file() or source.suffix != ".SaveRAM"
                or not (name.startswith("red") or "red version" in name)):
            raise RuntimeError("--wrong-save must name an existing second-OT Red SaveRAM")
        sram = source.read_bytes()
        rom = (Path(REPO) / self.gcfg["rom"]["a"]).read_bytes()
        problems = qualify(sram, rom)  # gen1_fixtures.py:57-83, game's checksum/stat oracle
        if problems:
            raise RuntimeError(f"--wrong-save is not a game-loadable Red save: {problems}")
        profile = json.loads((Path(REPO) / "data/games/gen1_rby/profile.json").read_text(
            encoding="utf-8"))["titles"]["red"]["ram"]
        # save.asm:208-220 copies wMainDataStart..End to sMainData; never subtract
        # wPlayerName here (gen1_codec.py:74-77 uses the same compacted offset rule).
        offset = codec.SRAM_LAYOUT["sMainData"] + profile["wPlayerID"] - profile["wMainDataStart"]
        other_ot = int.from_bytes(sram[offset:offset + 2], "big")
        if str(other_ot) == str(expected_ot):
            raise RuntimeError(f"--wrong-save has the original OT {other_ot}; need a second-OT Red save")
        return other_ot

    def _wrong_save_missing(self):
        self._pydec_note("WRONG_SAVE_LEG NOT RUN — supply --wrong-save <second-OT red*.SaveRAM>")
        self._reconnect_complete = False

    def assert_reconnect_new(self):
        """C-2 crash/reload while B stays online, then optional fail-closed C-1 wrong save."""
        from pathlib import Path

        from run_gb_gate import GENS

        self.go()
        self.assert_link_new()
        for inst in ("a", "b"):
            wait_for(f"{inst} link_new SAVE and reconnect hold",
                     lambda i=inst: "RECONNECT_READY " + i in (read_result(self.scenario, i) or ""), 300)
        _sram, party, _current, codec = self._saved_gen1_party("a")
        if [codec.key(mon) for mon in party] != [self._boot_keys["a"], self._link_keys["a"]]:
            raise RuntimeError("A's flushed Red save does not hold the linked pair before the crash")
        correct_save = Path(self._saveram_dir("a")) / GENS["gen1"]["saveram_names"]["red"]
        shutil.copyfile(correct_save, os.path.join(self.data_dir, "a_original_before_reconnect.SaveRAM"))
        baseline = {"links": self._reconnect_document(), "events": self._reconnect_events()}
        shutil.copyfile(self._result_path("a"), os.path.join(self.data_dir, "a_initial_result.txt"))

        self.terminate_instance("a")
        wait_for("A disconnected while B stays online", lambda: (
            (s := self._status()) and not s["players"]["a"]["connected"]
            and s["players"]["b"]["connected"]), 45)
        if self._reconnect_document().get("links") != baseline["links"].get("links"):
            raise RuntimeError("the live link changed when A's EmuHawk was killed")
        self._pydec_note("C-2 A EmuHawk terminated; server/B live, link unchanged while A disconnected")
        self.launch_instance("a", phase="same_save", seed=False, expected_key=self._link_keys["a"])
        same_path = self._phase_result_path("a", "same_save")
        wait_for("same-save A hello", lambda: "RECONNECT_HELLO same_save count=1" in (
            Path(same_path).read_text(encoding="utf-8") if os.path.exists(same_path) else ""), 180)
        wait_for("server accepts A's same-save party", lambda: (
            (s := self._status()) and (a := s["players"]["a"]).get("connected")
            and not a.get("identity_error") and self._link_keys["a"] in (a.get("party_keys") or [])), 60)
        old_a_hellos = sum(row.get("type") == "hello" and row.get("player") == "a"
                           for row in baseline["events"])
        wait_for("durable accepted reconnect hello", lambda: sum(
            row.get("type") == "hello" and row.get("player") == "a"
            for row in self._reconnect_events()) == old_a_hellos + 1, 30)
        same_after = {"links": self._reconnect_document(), "events": self._reconnect_events(),
                      "status": self._status() or {}}
        problems = reconnect_same_problems(baseline["links"], same_after, baseline["events"],
                                           same_after["events"], self._link_keys["a"],
                                           baseline["links"]["player_identity"]["a"]["ot_id"])
        same_receipt = Path(same_path).read_text(encoding="utf-8")
        if "RX force_faint" in same_receipt or "RX box_mon" in same_receipt:
            problems.append("A relaunch received force_faint/box_mon")
        if problems:
            raise RuntimeError("C-2 same-save reconnect failed: " + "; ".join(problems))
        self._pydec_note(f"C-2 same OT accepted; alive link {self._link_keys['a']} / "
                         f"{self._link_keys['b']}; party re-synced, zero duplicate gameplay events")
        self._append_reconnect_marker("a", "A_DONE_SAME")
        wait_for("same-save A phase PASS", lambda: "RESULT: PASS" in (
            Path(same_path).read_text(encoding="utf-8") if os.path.exists(same_path) else ""), 60)
        final_same_receipt = Path(same_path).read_text(encoding="utf-8")
        if "RX force_faint" in final_same_receipt or "RX box_mon" in final_same_receipt:
            raise RuntimeError("A received a late force_faint/box_mon after reconnect validation")
        self.emu_by_inst["a"].wait(timeout=30)
        self.terminate_instance("a")
        wait_for("same-save A socket closed before the wrong-save relaunch", lambda: (
            (s := self._status()) and not s["players"]["a"]["connected"]), 45)

        wrong = getattr(self.args, "wrong_save", None)
        if not wrong:
            self._wrong_save_missing()
            final_a = same_path
        else:
            other_ot = self._wrong_red_save_ot(wrong, baseline["links"]["player_identity"]["a"]["ot_id"])
            before_wrong_bytes = Path(self.data_dir, "links.json").read_bytes()
            before_wrong_events = self._reconnect_events()
            shutil.copyfile(wrong, correct_save)
            self.launch_instance("a", phase="wrong_save", seed=False)
            wrong_path = self._phase_result_path("a", "wrong_save")
            wait_for("A wrong-save HUD", lambda: "WRONG_SAVE_HUD [x] WRONG SAVE: slot A" in (
                Path(wrong_path).read_text(encoding="utf-8") if os.path.exists(wrong_path) else ""), 180)
            after_wrong = self._status() or {}
            problems = reconnect_wrong_problems(before_wrong_bytes, Path(self.data_dir, "links.json").read_bytes(),
                                                after_wrong, before_wrong_events, self._reconnect_events())
            if problems:
                raise RuntimeError("C-1 wrong-save refusal failed: " + "; ".join(problems))
            self._pydec_note(f"C-1 wrong OT {other_ot} rejected; links.json byte-identical, no gameplay events")
            self._append_reconnect_marker("a", "A_DONE_WRONG")
            wait_for("wrong-save A phase PASS", lambda: "RESULT: PASS" in (
                Path(wrong_path).read_text(encoding="utf-8") if os.path.exists(wrong_path) else ""), 60)
            self.emu_by_inst["a"].wait(timeout=30)
            self._reconnect_complete = True
            final_a = wrong_path
        shutil.copyfile(final_a, self._result_path("a"))
        self._append_reconnect_marker("b", "B_DONE")
        wait_for("B stayed online through reconnect legs", lambda: "RESULT: PASS" in (
            read_result(self.scenario, "b") or ""), 120)
        return self._reconnect_complete

    def assert_link_new(self):
        """D-1: ONE alive link on route_1 whose halves are the two keys the cartridges caught."""
        def both_caught():
            a, b = self._caught("a"), self._caught("b")
            if a and b:
                return a, b
            if any(_has_exact_rng_miss(read_result(self.scenario, inst)) for inst in ("a", "b")):
                raise GameRngMiss("a cartridge missed its sole ball before the pair formed")
            return None
        a_key, b_key = wait_for("both instances to catch a wild mon", both_caught,
                                self.cfg["timeout"])
        print(f"[duo] real captures: a={a_key} b={b_key}")

        def linked():
            for link in (self._status() or {}).get("links") or []:
                if {link.get("a_key"), link.get("b_key")} == {a_key, b_key}:
                    return link
            return None
        link = wait_for("the SERVER to pair the two real captures", linked, 180)
        st = self._status() or {}
        links = st.get("links") or []
        area_state = (st.get("area_states") or {}).get("route_1")
        problems = []
        if len(links) != 1:
            problems.append(f"expected exactly one link, got {len(links)}: {links}")
        if link.get("status") != "alive":
            problems.append(f"link status is {link.get('status')!r}, not alive")
        if link.get("area_id") != "route_1":
            problems.append(f"link area is {link.get('area_id')!r}, not route_1")
        if area_state != "linked":
            problems.append(f"area_states.route_1 is {area_state!r}, not linked")
        if problems:
            raise RuntimeError("; ".join(problems))
        print(f"[duo] ENCOUNTER LINK FROM REAL PLAY (new client): {a_key} <-> {b_key} "
              f"on route_1, alive")
        self._link_keys = {"a": a_key, "b": b_key}
        return a_key, b_key

    def _saved_gen1_party(self, inst):
        """PYDEC + the fixture qualifier on the cartridge's flushed 32 KiB SaveRAM."""
        from pathlib import Path

        if REPO not in sys.path:
            sys.path.insert(0, REPO)
        from gen1_fixtures import qualify
        from run_gb_gate import GENS

        from server.adapters import gen1_codec as codec

        title = self.gcfg["fixture"][inst]
        name = GENS["gen1"]["saveram_names"][title]
        sram = (Path(self._saveram_dir(inst)) / name).read_bytes()
        rom = (Path(REPO) / self.gcfg["rom"][inst]).read_bytes()
        # tools/gen1_fixtures.py:57-83 uses codec.verify_bank1 (the game's CalcCheckSum),
        # decode_party, level_from_exp and recompute_stats against this exact ROM.
        problems = qualify(sram, rom)
        if problems:
            raise RuntimeError(f"{inst} saved game would not qualify: {problems}")
        start = codec.SRAM_LAYOUT["sPartyData"]  # gen1_codec.py:66-72,587-595
        party = codec.decode_party(sram[start:start + codec.PARTY_LAYOUT["size"]])
        current = codec.SRAM_LAYOUT["sCurBoxData"]  # the WRAM mirror is copied here on SAVE
        current_box = codec.decode_box(sram[current:current + codec.BOX_SIZE])
        self._pydec_note(f"{inst} main checksum/exp/recomputed stats valid; saved party/current box decode valid")
        return sram, party, current_box, codec

    def assert_link_new_saved(self):
        """The caught halves are saved in slot 1, with PYDEC-rebuilt stored stats."""
        for process in self.emus:
            process.wait(timeout=30)  # BizHawk flushes CartRAM when client.exit completes
        for inst in ("a", "b"):
            _sram, party, current_box, codec = self._saved_gen1_party(inst)
            keys = [codec.key(mon) for mon in party]  # gen1_codec.py:602-610
            expected = [self._boot_keys[inst], self._link_keys[inst]]
            if keys != expected:
                raise RuntimeError(f"{inst} saved link party {keys}, expected starter/withdrawn {expected}")
            if any(codec.key(mon) == self._link_keys[inst] for mon in current_box):
                raise RuntimeError(f"{inst} saved current box still holds its withdrawn linked mon")
            # qualify() above independently invokes codec.recompute_stats on both mons
            # (tools/gen1_fixtures.py:70-82; gen1_codec.py:738-751).
            self._pydec_note(f"{inst} saved slot 0 starter {keys[0]}")
            self._pydec_note(f"{inst} saved slot 1 linked {keys[1]}, no current-box duplicate")

    def assert_dead_zone_new_saved(self):
        """B's retired key is absent from party and durably present, fainted, in Box 12."""
        for process in self.emus:
            process.wait(timeout=30)
        _a_sram, a_party, _a_current, codec = self._saved_gen1_party("a")
        b_sram, b_party, b_current, _codec = self._saved_gen1_party("b")
        if [codec.key(mon) for mon in a_party] != [self._boot_keys["a"]]:
            raise RuntimeError("A's failed encounter changed its saved starter party")
        b_keys = [codec.key(mon) for mon in b_party]
        if b_keys != [self._boot_keys["b"]] or self._deadzone_b_key in b_keys:
            raise RuntimeError(f"B's retired key remained in saved party: {b_keys}")
        if any(codec.key(mon) == self._deadzone_b_key for mon in b_current):
            raise RuntimeError("B's saved current box still holds the Box 12 memorial")
        # gen1_codec.py:636-668: raw individual and bank checksums, box count, saved
        # initialized flag and offsets. decode_box validates every count/FF terminator.
        verdict = codec.verify_boxes(b_sram)
        if (not verdict["initialized"] or not all(v["valid"] for v in verdict["banks"].values())
                or not all(v["valid"] for v in verdict["boxes"].values())):
            raise RuntimeError(f"B's saved box banks/checksums/initialized flag invalid: {verdict}")
        boxes = {}
        for number, info in verdict["boxes"].items():
            start = info["offset"]
            boxes[number] = codec.decode_box(b_sram[start:start + codec.BOX_SIZE])
        memorial = boxes[12]  # 1-based report key = Box 12; command index is 11
        if len(memorial) != 1 or codec.key(memorial[0]) != self._deadzone_b_key or memorial[0]["hp"] != 0:
            raise RuntimeError(f"B Box 12 did not save the zero-HP retired key {self._deadzone_b_key}: "
                               f"{[(codec.key(mon), mon['hp']) for mon in memorial]}")
        self._pydec_note(f"B saved party/current box excludes {self._deadzone_b_key}")
        self._pydec_note("B initialized box banks and all 12 counts/terminators/checksums valid")
        self._pydec_note(f"B Box 12 holds {self._deadzone_b_key} at HP 0")

    def assert_linked_faint_saved(self, results, *, active):
        """D-6/W-1/W-2: server cause + both game-loadable memorials and engine receipts."""
        for process in self.emus:
            process.wait(timeout=30)
        matches = [entry for entry in self._links_json() if entry.get("area_id") == "route_1"]
        if len(matches) != 1:
            raise RuntimeError(f"expected one durable Route 1 link, got {matches}")
        link = matches[0]
        # state.py:2661-2704 sets DEAD/cause=battle; :2745-2768 advances to MEMORIAL
        # after BOTH physical memorialize_done events.
        if link.get("status") != "memorial" or link.get("cause") != "battle":
            raise RuntimeError(f"linked faint did not become a battle-caused memorial: {link}")
        with open(os.path.join(self.data_dir, "slink.log"), encoding="utf-8") as handle:
            log_text = handle.read()
        dead_transition = log_text.find(f"[a] faint → force_faint b:{self._link_keys['b']}")
        memorial_transition = log_text.find("pair in route_1 fully memorialized")
        if dead_transition < 0 or memorial_transition <= dead_transition:
            raise RuntimeError("server lacked ordered DEAD propagation then full memorial receipt")
        self._pydec_note("server DEAD propagation precedes final MEMORIAL, cause=battle")
        for inst in ("a", "b"):
            key = self._link_keys[inst]
            if link[inst]["key"] != key:
                raise RuntimeError(f"{inst} persisted link key differs from captured {key}")
            sram, party, current_box, codec = self._saved_gen1_party(inst)
            if len(party) != 1 or codec.key(party[0]) != self._boot_keys[inst] or party[0]["hp"] == 0:
                raise RuntimeError(f"{inst} saved party is not its living starter: "
                                   f"{[(codec.key(m), m['hp']) for m in party]}")
            if any(codec.key(mon) == key for mon in current_box):
                raise RuntimeError(f"{inst} saved current box still holds the linked corpse")
            verdict = codec.verify_boxes(sram)  # gen1_codec.py:636-668
            if (not verdict["initialized"] or not all(v["valid"] for v in verdict["banks"].values())
                    or not all(v["valid"] for v in verdict["boxes"].values())):
                raise RuntimeError(f"{inst} memorial banks/checksums invalid: {verdict}")
            for number, info in verdict["boxes"].items():
                offset = info["offset"]
                boxed = codec.decode_box(sram[offset:offset + codec.BOX_SIZE])  # validates count/FF
                if number == 12:
                    memorial = boxed
            if len(memorial) != 1 or codec.key(memorial[0]) != key or (
                    memorial[0]["hp"], memorial[0]["status"]) != (0, 0):
                raise RuntimeError(f"{inst} Box 12 lacks the HP0000/status00 linked key {key}: "
                                   f"{[(codec.key(m), m['hp'], m['status']) for m in memorial]}")
            self._pydec_note(f"{inst} saved living starter; linked key {key} absent from party/current box")
            self._pydec_note(f"{inst} Box 12 {key} HP0000/status00; initialized checksums/terminators valid")
        a_text, b_text = results["a"], results["b"]
        for inst, text in (("a", a_text), ("b", b_text)):
            key = self._link_keys[inst]
            if f"RX memorialize key={key}" not in text or '"event":"memorialize_done"' not in text:
                raise RuntimeError(f"{inst} lacked memorialize command/ack for {key}")
        if f"BATTLE_FAINT_SITE {self._link_keys['a']}" not in a_text:
            raise RuntimeError("A's linked faint lacked the engine battle_faint site witness")
        if f'"event":"faint","key":"{self._link_keys["a"]}"' not in a_text:
            raise RuntimeError("A's engine battle_faint did not emit its linked key")
        if f"RX force_faint key={self._link_keys['b']}" not in b_text:
            raise RuntimeError("B never received the server force_faint for its linked key")
        if "GAME_OVER RX game_over" not in b_text:
            raise RuntimeError("B never received the last-link game_over command")
        if active:
            first = b_text.find("LOOP_HEAD_WRITE key=" + self._link_keys["b"])
            second = b_text.find("BATTLE_FAINT_SITE " + self._link_keys["b"])
            tile_witness = ("TILEMAP_FAINTED offset=" in b_text or
                            "TILEMAP_FAINTED unavailable: native faint text advanced before probe" in b_text)
            if (first < 0 or second <= first or not tile_witness
                    or f'"event":"faint","key":"{self._link_keys["b"]}"' not in b_text
                    or "BATTLE_RESULT b " not in b_text):
                raise RuntimeError("B active write was not followed by engine battle_faint/text")
        elif ("READY_BENCH map=12 x=8 y=31" not in b_text or "BENCH_HP_STATUS 0000 00" not in b_text
              or ("TILEMAP_FNT row=2" not in b_text and
                  "TILEMAP_FNT unavailable: memorialised within " not in b_text)):
            raise RuntimeError("B bench write lacked HP/status and party-menu FNT tile evidence")
        self._pydec_note(f"D-6/W-{2 if active else 1} server battle cause and ordered engine receipts valid")

    def assert_trade_new(self, results):
        """T-3/T-4: durable swapped halves plus each cartridge's actual saved party."""
        from pathlib import Path

        if REPO not in sys.path:
            sys.path.insert(0, REPO)  # python tools/e2e_duo.py otherwise has tools/ at sys.path[0]
        from run_gb_gate import GENS

        from server.adapters import gen1_codec as codec
        from tests.unit import protocol_schema

        for process in self.emus:
            process.wait(timeout=30)  # client.exit flushes CartRAM to its per-instance SaveRAM
        with open(os.path.join(self.data_dir, "links.json"), encoding="utf-8") as handle:
            document = json.load(handle)
        matches = [entry for entry in document.get("links", [])
                   if entry.get("area_id") == "route_1" and entry.get("status") == "alive"]
        if len(matches) != 1:
            raise RuntimeError(f"expected one durable alive route_1 link, got {matches}")
        before_a, before_b = self._trade_before
        link = matches[0]
        if link["a"]["key"] != before_b or link["b"]["key"] != before_a:
            raise RuntimeError(f"links.json halves were not swapped: {link['a']['key']} / {link['b']['key']}")

        for inst, incoming, partner in (("a", before_b, "b"), ("b", before_a, "a")):
            save_name = GENS["gen1"]["patched"][self.cfg["patched_saves"][inst]][2]
            save = Path(self._saveram_dir(inst)) / save_name
            sram = save.read_bytes()
            if len(sram) != codec.SRAM_SIZE:
                raise RuntimeError(f"{inst} SaveRAM is {len(sram)} bytes, expected {codec.SRAM_SIZE}")
            start = codec.SRAM_LAYOUT["sPartyData"]
            party = codec.decode_party(sram[start:start + codec.PARTY_LAYOUT["size"]])
            if len(party) != 2 or codec.key(party[-1]) != incoming:
                raise RuntimeError(f"{inst} saved party lacks partner's mon in LAST slot: "
                                   f"{[codec.key(mon) for mon in party]}")
            dv, ot, species = incoming.split(":")
            received = party[-1]
            if (received["dvs"]["raw"] != int(dv, 16)
                    or received["ot_id"] != int(ot, 16)
                    or received["species"] != int(species, 16)):
                raise RuntimeError(f"{inst} received mon identity fields differ from {incoming}")
            # Hello locks this name in player_identity; trainer_names is an older field
            # that Gen 1 never populates (server/state.py:953-989,3071-3073).
            original_ot = document.get("player_identity", {}).get(partner, {}).get("trainer_name")
            if not original_ot or received["ot_name"] != original_ot:
                raise RuntimeError(f"{inst} received OT name {received['ot_name']!r}, "
                                   f"expected partner's original {original_ot!r}")
            trade_lines = [json.loads(line[3:]) for line in results[inst].splitlines()
                           if line.startswith("TX {") and '"event":"trade_done"' in line]
            if len(trade_lines) != 1:
                raise RuntimeError(f"{inst} sent {len(trade_lines)} trade_done lines, expected one")
            report = trade_lines[0]
            errors = protocol_schema.validate_event(report)
            if errors or report.get("new_key") != incoming or report.get("slot") != len(party) - 1:
                raise RuntimeError(f"{inst} trade_done disagrees with saved party: {report}, {errors}")
            self._pydec_note(f"{inst} saved LAST slot {incoming}, OT {original_ot}, trade_done valid")
        self._pydec_note(f"T-3/T-4 durable swapped halves: a={before_b}, b={before_a}")

    def assert_admit_randomized_new(self):
        """The server verdict and durable hello events, not the TCP connected bit, decide F-4."""
        def both_verdicts():
            status = self._status() or {}
            players = status.get("players") or {}
            a, b = players.get("a") or {}, players.get("b") or {}
            return status if a.get("admission") == "admitted" and b.get("admission") == "rejected" else None

        status = wait_for("randomized A admitted and clean B rejected", both_verdicts, 180)
        a, b = status["players"]["a"], status["players"]["b"]
        if a.get("admission_reason") != "cartridge matches the contract":
            raise RuntimeError(f"A admission reason differs: {a.get('admission_reason')!r}")
        got, want = self._admit_fingerprints["reported_b"], self._admit_fingerprints["expected_b"]
        reason = b.get("admission_reason", "")
        if ("not the cartridge built for player b" not in reason
                or got[:12] not in reason or want[:12] not in reason):
            raise RuntimeError(f"B wrong-cartridge reason lacks the fingerprint prefixes: {reason!r}")
        # server.py:1574-1591 returns only noop on a rejected hello. Status is the public
        # evidence that no B party snapshot or trainer identity was adopted.
        if b.get("party_keys") or b.get("trainer_name") or b.get("current_area_id"):
            raise RuntimeError(f"rejected B adopted party/identity/area: {b}")

        def receipts():
            a_text = read_result(self.scenario, "a") or ""
            b_text = read_result(self.scenario, "b") or ""
            if all(tag in text for text in (a_text, b_text)
                   for tag in ("ADMIT_MAP 40 5 6", "ADMIT_PARTY ", "HELLO_RECEIPT ")):
                return a_text, b_text
            return None

        a_text, b_text = wait_for("live town save and hello receipts", receipts, 120)
        for player, text in (("a", a_text), ("b", b_text)):
            party_line = next((line for line in text.splitlines() if line.startswith("ADMIT_PARTY ")), "")
            if not party_line or int(party_line.split()[1]) < 1:
                raise RuntimeError(f"{player} booted without a live party: {party_line!r}")

        def durable_events():
            path = os.path.join(self.data_dir, "events.json")
            if not os.path.isfile(path):
                return None
            with open(path, encoding="utf-8") as handle:
                rows = json.load(handle)
            hellos = [row for row in rows if row.get("type") == "hello"]
            return hellos if len(hellos) >= 2 else None

        hellos = wait_for("durable admitted/rejected hello events", durable_events, 30)
        a_events = [row for row in hellos if row.get("player") == "a"]
        b_events = [row for row in hellos if row.get("player") == "b"]
        if (len(a_events) != 1 or not a_events[0].get("text", "").startswith("Connected (Red, ")
                or len(b_events) != 1 or not b_events[0].get("text", "").startswith("REJECTED — ")):
            raise RuntimeError(f"unexpected durable hello events: {hellos}")
        with open(os.path.join(self.data_dir, "slink.log"), encoding="utf-8") as handle:
            log_text = handle.read()
        if ("[a] admission: admitted — cartridge matches the contract" not in log_text
                or "[b] admission: rejected — " + reason not in log_text):
            raise RuntimeError("slink.log omitted an admission transition")
        self._pydec_note(f"F-4 public verdicts: A admitted, clean B rejected; "
                         f"expected={want[:12]} reported={got[:12]} (admission-only, no save mutation)")

    def assert_dead_zone_new(self):
        """D-3: A's RUN sends no_catch and locks route_1; B's later catch there is retired.

        B is released only once the SERVER reports the lock, so "B caught inside a dead zone"
        is a fact. Retirement is read two ways: the server's links.json carries the DEAD entry
        with cause dead_zone, and B's result file shows the caught key at HP 0 in the party
        (FAINTED, written by the client's force_faint) before memorialize moves it out.
        """
        self._go_one("a")
        area = wait_for("A's failed encounter to lock an area", self._dead_zone_area,
                        self.cfg["timeout"])
        if area != "route_1":
            raise RuntimeError(f"A locked {area!r}, expected route_1")
        wait_for("A to report its no_catch",
                 lambda: "NO_CATCH" in (read_result(self.scenario, "a") or ""), 60)
        print(f"[duo] DEAD ZONE FROM REAL PLAY (new client): {area}")

        self._go_one("b")
        def b_caught():
            key = self._caught("b")
            if not key and _has_exact_rng_miss(read_result(self.scenario, "b")):
                raise GameRngMiss("B missed its sole ball inside the dead zone")
            return key

        b_key = wait_for("B to catch inside the dead zone", b_caught, self.cfg["timeout"])
        self._deadzone_b_key = b_key
        wait_for("B's client to force-faint the refused capture",
                 lambda: "FAINTED " in (read_result(self.scenario, "b") or ""), 300)
        retired = "RETIRED " in (read_result(self.scenario, "b") or "")
        print(f"[duo] B caught {b_key} in the dead zone; force-fainted"
              f"{', memorialized' if retired else ' (memorialize not observed)'}")

        st = self._status() or {}
        area_state = (st.get("area_states") or {}).get(area)
        problems = []
        if area_state != "dead_zone":
            problems.append(f"{area} is {area_state!r} after B's catch, not dead_zone")
        for link in st.get("links") or []:
            if b_key in (link.get("a_key"), link.get("b_key")) and link.get("status") == "alive":
                problems.append(f"B's dead-zone catch {b_key} formed a LIVE link")
        if ((st.get("pending_captures") or {}).get(area) or {}).get("b"):
            problems.append(f"B's dead-zone catch is pending in {area}")
        dead = [lnk for lnk in self._links_json()
                if lnk.get("area_id") == area and lnk.get("status") == "dead"
                and lnk.get("cause") == "dead_zone"]
        if not dead:
            problems.append(f"links.json has no DEAD/dead_zone entry for {area}: "
                            f"{self._links_json()}")
        if problems:
            raise RuntimeError("; ".join(problems))
        print(f"[duo] links.json: {len(dead)} dead_zone entry for {area}; B's {b_key} retired")

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
        if self.scenario == "admit_randomized_new":
            self.assert_admit_randomized_new()
            self.go()  # passive clients hold for ~600 frames before RESULT: PASS
            return
        ka, kb = self.wait_keys()
        self._boot_keys = {"a": ka[0], "b": kb[0]}
        self.wait_connected()
        if self.scenario == "reconnect_new":
            self.assert_reconnect_new()
            return
        if self.cfg.get("no_setup"):
            # Deliberately does NOT call set_pokeballs() or inject_link(): these scenarios
            # exist to prove the paths those shortcuts bypass. The fixture carries real
            # Poke Balls, so the gate flips from the client's own bag read.
            if self.scenario == "deadzone":
                self.assert_dead_zone_refusal()
            elif self.scenario == "dupes":
                self.assert_species_clause_rejection()
            elif self.scenario in ("link_new", "linked_faint_bench_new", "linked_faint_active_new"):
                self.go()
                self.assert_link_new()
            elif self.scenario == "trade_new":
                self.go()
                self.assert_link_new()
                before = [entry for entry in self._links_json()
                          if entry.get("area_id") == "route_1" and entry.get("status") == "alive"]
                if len(before) != 1:
                    raise RuntimeError("trade_new has no durable post-link_new pair")
                self._trade_before = (before[0]["a"]["key"], before[0]["b"]["key"])
            elif self.scenario == "deadzone_new":
                self.assert_dead_zone_new()
            else:
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
        elif self.scenario == "whiteout":
            # TWO pairs, and the second one is not padding. Measured against the real
            # server: on a cartridge every `faint` beats the `whiteout` to the server, so
            # _handle_whiteout finds nothing left to retire and its only observable effect
            # is the auto-rebuild — which needs an alive, fully-boxed pair to pull back. A
            # boxes its slot-1 half during the scenario; link it here or there is no pair.
            self.inject_link(ka[0], kb[0], area_id="duo0")
            self.inject_link(ka[1], kb[1], area_id="duo1")
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
        elif self.scenario == "boxsync" and self.battery_boot:
            # The GB gens exercise the RULE, not the storage opcodes: link the pair, then let A
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
        if getattr(self, "_pydec_path", None):
            os.makedirs(os.path.dirname(self._pydec_path), exist_ok=True)
            with open(self._pydec_path, "w", encoding="utf-8") as handle:
                handle.write(f"attempt {self.attempt} of 2\n")
        try:
            if self.scenario == "admit_randomized_new":
                self.prepare_admit_randomized_new()
            self.start_server()
            self.start_instances()
            try:
                self.orchestrate()
            except GameRngMiss:
                ra, rb = self.wait_results()
                if not retryable_gen1_rng(self.game, {"a": ra, "b": rb}, 1):
                    raise  # an unrelated failed half is never a game-RNG retry
            else:
                ra, rb = self.wait_results()
            pa = "RESULT: PASS" in ra
            pb = "RESULT: PASS" in rb
            if pa and pb and self.scenario == "trade_new":
                self.assert_trade_new({"a": ra, "b": rb})
            if pa and pb and self.scenario == "link_new":
                self.assert_link_new_saved()
            if pa and pb and self.scenario == "deadzone_new":
                self.assert_dead_zone_new_saved()
            if pa and pb and self.scenario in ("linked_faint_bench_new", "linked_faint_active_new"):
                self.assert_linked_faint_saved({"a": ra, "b": rb},
                                               active=self.scenario == "linked_faint_active_new")
            passed = pa and pb and (self.scenario != "reconnect_new" or self._reconnect_complete)
            if getattr(self, "_pydec_path", None):
                reason = ("asserted scenario facts" if passed else
                          "wrong-save leg not run" if pa and pb and self.scenario == "reconnect_new" else
                          "client RESULT before saved-state oracle")
                self._pydec_note(f"PYDEC: {'PASS' if passed else 'FAIL'} {reason}")
            print(f"[duo] {self.scenario}: a={'PASS' if pa else 'FAIL'} "
                  f"b={'PASS' if pb else 'FAIL'}")
            if not passed:
                for inst, text in (("a", ra), ("b", rb)):
                    print(f"--- {self.scenario} {inst} result ---")
                    print("\n".join(text.splitlines()[-25:]))
            if self.args.keep_alive:
                input("[duo] --keep-alive: press Enter to tear down…")
        except Exception as exc:
            if getattr(self, "_pydec_path", None):
                self._pydec_note(f"PYDEC: FAIL {exc}")
            raise
        finally:
            self.cleanup(passed)
        return passed


def run_scenario_with_rng_retry(name, args):
    """A new DuoRun for each attempt means a new server/data dir and reseeded battery saves."""
    limit = 2 if args.game == "gen1_new" else 1
    for attempt in range(1, limit + 1):
        print(f"[duo] {name}: attempt {attempt} of {limit}")
        ok = DuoRun(name, args, attempt=attempt).run()
        receipts = {inst: read_result(name, inst) for inst in ("a", "b")}
        # The next run deletes the normal result files; keep each attempt's receipts.
        for inst in ("a", "b"):
            if receipts[inst] is not None:
                    with open(os.path.join(BUILD, f"e2e_{name}_{inst}_attempt{attempt}_result.txt"),
                          "w", encoding="utf-8") as handle:
                        handle.write(receipts[inst])
        pydec = os.path.join(BUILD, f"e2e_{name}_pydec_result.txt")
        if os.path.exists(pydec):
            shutil.copyfile(pydec, os.path.join(BUILD, f"e2e_{name}_pydec_attempt{attempt}_result.txt"))
        if ok or not retryable_gen1_rng(args.game, receipts, attempt):
            return ok, attempt
        print(f"[duo] {name}: the cartridge's only ball missed; restarting attempt 2 of 2 "
              "with a fresh server, run directory and SaveRAM seeds")
    return False, 2


def main():
    # The client logs contain Unicode arrows; don't let a cp1252 console kill the runner.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game", default="gen3_rr", choices=sorted(GAMES),
                    help="gen3_rr (Radical Red, default), gen1 (Red as A, Blue as B), "
                         "gen1_yellow (Yellow as A, Red as B) or gen2 (Crystal both sides)")
    ap.add_argument("--scenario", default="faint",
                    choices=list(SCENARIOS) + ["all"])
    ap.add_argument("--keep-alive", action="store_true",
                    help="pause before teardown for manual inspection")
    ap.add_argument("--keep-data", action="store_true",
                    help="never delete the temp server data dir")
    ap.add_argument("--wrong-save", default=None,
                    help="second-OT Red SaveRAM for reconnect_new's fail-closed C-1 leg")
    ap.add_argument("--server-flags", nargs="*", default=[],
                    help="extra flags for server.server")
    ap.add_argument("--list", action="store_true",
                    help="print the scenarios --scenario all would run for --game, then exit")
    args = ap.parse_args()

    if args.list:
        for name in scenarios_for(args.game):
            print(name)
        sys.exit(0)

    if args.scenario == "all":
        names = scenarios_for(args.game)
        # NAME what was dropped. A silent filter and a table that genuinely has nothing for
        # this title look identical from the summary, and "all passed" over a silently empty
        # selection is the worst possible way to report no coverage.
        skipped = [n for n in SCENARIOS if n not in names]
        if skipped:
            print(f"[duo] {args.game}: skipping {len(skipped)} scenario(s) that do not apply "
                  f"— {', '.join(skipped)}")
        if not names:
            sys.exit(f"[duo] no scenarios apply to {args.game}")
    else:
        # Fail NOW rather than after two emulators boot and time out on a missing savestate.
        # If the pairing really should work, the fix is the scenario's `games` tuple.
        if not scenario_applies(args.scenario, args.game):
            allowed = ", ".join(SCENARIOS[args.scenario]["games"])
            sys.exit(f"[duo] scenario '{args.scenario}' does not apply to --game {args.game} "
                     f"(it declares games: {allowed}). Add {args.game} to its `games` tuple "
                     f"in SCENARIOS if it should.")
        names = [args.scenario]
    results = {}
    limit = 2 if args.game == "gen1_new" else 1
    for name in names:
        print(f"\n========== scenario: {name} ==========")
        results[name] = run_scenario_with_rng_retry(name, args)
    print("\n========== summary ==========")
    for name, (ok, attempt) in results.items():
        print(f"  {name}: {'PASS' if ok else 'FAIL'} (attempt {attempt} of {limit})")
    sys.exit(0 if all(ok for ok, _ in results.values()) else 1)


if __name__ == "__main__":
    main()
