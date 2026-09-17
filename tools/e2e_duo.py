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
import re
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
                 "target": "battle", "no_setup": True, "frames": 2000000,
                 "oracle": "assert_link_new_saved"},
    "deadzone_new": {"flags": [], "timeout": 900, "games": ("gen1_new",),
                     "target": "battle", "no_setup": True, "frames": 2000000,
                     "oracle": "assert_dead_zone_new_saved"},
    "linked_faint_bench_new": {"flags": [], "timeout": 1500, "games": ("gen1_new",),
                               "target": "battle", "no_setup": True, "frames": 2500000,
                               "oracle": "assert_linked_faint_saved",
                               "oracle_kwargs": {"active": False}},
    "linked_faint_active_new": {"flags": [], "timeout": 1500, "games": ("gen1_new",),
                                "target": "battle", "no_setup": True, "frames": 2500000,
                                "oracle": "assert_linked_faint_saved",
                                "oracle_kwargs": {"active": True}},
    "reconnect_new": {"flags": [], "timeout": 900, "games": ("gen1_new",),
                      "target": "battle", "no_setup": True, "frames": 2000000,
                      "oracle": "assert_reconnect_saved"},
    # D-2: the starters form a gift pair; the pre-ball rival faints do not kill that pair.
    # Both cartridges start cold and play lab/parcel/save with sequential rival turns.
    "ball_gate_new": {"flags": [], "timeout": 1800, "games": ("gen1_new",),
                      "cold_boot": True, "no_setup": True, "frames": 400000,
                      "oracle": "assert_ball_gate_saved"},
    # T-3/T-4 needs the companion trade bank, unlike the encounter-only new-client lanes.
    "trade_new": {"flags": [], "timeout": 1500, "games": ("gen1_new",),
                  "target": "battle", "no_setup": True, "frames": 2500000,
                  "rom": {"a": "patch/gen1/build/slink_red.gb",
                          "b": "patch/gen1/build/slink_blue.gb"},
                  "patched_saves": {"a": "red_patched", "b": "blue_patched"},
                  "oracle": "assert_trade_new"},
    # W-6/R-4: A holds A+B+Select+Start for 16 polls, the WRAM clear lands, the client withholds
    # its hello and pauses writes, CONTINUE reloads the SAME save, and the re-hello carries the
    # same trainer ID. Marker ranges and the reset timing come from the body's header comment
    # (duo_gen1_main.lua:1240-1265): the clear lands ~48 frames into a 24-frame chord.
    "soft_reset_new": {"flags": [], "timeout": 900, "games": ("gen1_new",),
                       "target": "battle", "no_setup": True, "frames": 2000000,
                       "oracle": "assert_soft_reset_saved"},
    # T-3/T-4's NO path: the same receptionist route, but the partner answers NO at the native
    # confirm, so no blob is ever staged and no party moves.
    "trade_decline_new": {"flags": [], "timeout": 1500, "games": ("gen1_new",),
                          "target": "battle", "no_setup": True, "frames": 2500000,
                          "rom": {"a": "patch/gen1/build/slink_red.gb",
                                  "b": "patch/gen1/build/slink_blue.gb"},
                          "patched_saves": {"a": "red_patched", "b": "blue_patched"},
                          "oracle": "assert_trade_decline_saved"},
    # W-3 / D-11: linked_faint_active_new's A half against a server started with --explode-mode
    # (server/server.py:4755 spells it exactly that; the help text still says "RR only" although
    # the Gen 1 client consumes force_explode too). Runs the trade-carrying ROMs because B's
    # in-battle VBlank probe reads the companion patch's mailbox counter, and it saves under the
    # filename-derived patched save name.
    "explode_new": {"flags": ["--explode-mode"], "timeout": 1800, "games": ("gen1_new",),
                    "target": "battle", "no_setup": True, "frames": 2500000,
                    "rom": {"a": "patch/gen1/build/slink_red.gb",
                            "b": "patch/gen1/build/slink_blue.gb"},
                    "patched_saves": {"a": "red_patched", "b": "blue_patched"},
                    "oracle": "assert_explode_saved"},
    # S-6 / W-5 (Bill's PC listing): the link_new body, then A drives DEPOSIT -> WITHDRAW ->
    # DEPOSIT -> RELEASE through the native PC menus. The release is the documented
    # shared-protocol gap: the client logs RELEASE_SEEN and sends nothing, so the pair stays
    # ALIVE with a phantom boxed half.
    "pc_ops_new": {"flags": [], "timeout": 1800, "games": ("gen1_new",),
                   "target": "battle", "no_setup": True, "frames": 2500000,
                   "oracle": "assert_pc_ops_new_saved"},
    # W-5's box-change half: the deadzone body, then B CHANGEs BOX to 12 (the memorial is
    # listed) and back to 1, with the saved current-box index and the flag read afterwards.
    "changebox_new": {"flags": [], "timeout": 1800, "games": ("gen1_new",),
                      "target": "battle", "no_setup": True, "frames": 2500000,
                      "oracle": "assert_changebox_new_saved"},
    # S-4's blackout half + W-3 (the auto-rebuild): both halves deposit their linked catch,
    # A loses its starter to a wild foe and blacks out, and the server rebuilds the pair out
    # of the two PCs. The runner gates the blackout on BOTH_BOXED (server field, not the
    # client's word) because the rebuild only picks pairs whose halves are absent from
    # `state.party_keys` (server/state.py:2359-2360).
    "whiteout_new": {"flags": [], "timeout": 1800, "games": ("gen1_new",),
                     "target": "battle", "no_setup": True, "frames": 2500000,
                     "oracle": "assert_whiteout_new_saved"},
    # F-4: one randomized Red hello admitted, clean Blue rejected against its randomized
    # Blue contract. The second UPR output is required by prepare_pair but is not launched.
    "admit_randomized_new": {"flags": [], "timeout": 1800, "games": ("gen1_new",),
                             "target": "town", "no_setup": True, "frames": 100000,
                             "oracle": "assert_admit_randomized_saved"},
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


# Titles that share a family for `games` matching. `gen1_new` runs the same hardware as the
# `gen1` entries but is a DIFFERENT client: lua/tests/duo/duo_gen1_main.lua refuses every
# scenario the old drivers own. The old prefix rule therefore handed it six scenarios it cannot
# run, and `--scenario all --game gen1_new` died on the first of them.
FAMILIES = {"gen1": ("gen1", "gen1_yellow")}

# Titles that never inherit a scenario implicitly. An entry with no `games` key means "every
# title", which is right for savestate-less shared scenarios like faint/boxsync — but not for
# `gen1_new`, whose driver runs only the scenarios that name it, so opt-in is the whole rule.
OPT_IN_GAMES = ("gen1_new",)


def scenario_applies(name, game):
    """Does `name` apply to `game`? Absent `games` means every title but the opt-in ones."""
    allowed = SCENARIOS[name].get("games")
    if allowed is None:
        return game not in OPT_IN_GAMES
    return any(game in FAMILIES.get(entry, (entry,)) for entry in allowed)


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


JITTER_MARKER_RE = re.compile(r"JITTER requested=(\d+) applied=(\d+) attempt=(\d+)")
JITTER_PER_ATTEMPT = 37


def jitter_for_attempt(base, attempt):
    """The idle-frame count for one attempt: the harness's own value, moved per attempt.

    Two attempts of a scenario differ only through network-timing jitter, so a retry that asks
    for the same idle count is the same run twice — the harness print, the value written into
    the stubs and this file's own check must all use this one expression.
    """
    return base + (attempt - 1) * JITTER_PER_ATTEMPT


def jitter_problems(text, expected_requested):
    """The driver's echo of the harness's own `--idle-jitter` value, from its result file.

    The harness writes `idle_jitter` into each stub; the driver logs what it requested, what it
    applied and which attempt it was. A missing marker means the check could not run — a harness
    finding, not a pass — and a count the harness did not ask for means this attempt did not
    vary the timing the retry rule claims to have varied.
    """
    matches = JITTER_MARKER_RE.findall(text or "")
    if not matches:
        return ["JITTER marker missing"]
    requested, applied, _attempt = (int(value) for value in matches[0])
    if applied != requested or requested != expected_requested:
        return ["JITTER applied != requested"]
    return []


# Scenarios whose verdict needs a LIVE leg to have finished, not just two client RESULT lines:
# the flag is set only inside the live assert (assert_reconnect_new / assert_admit_randomized_new),
# and the post-result oracle refuses to describe a save that leg never produced.
LIVE_LEG_SCENARIOS = ("reconnect_new", "admit_randomized_new")

RECONNECT_GAMEPLAY_EVENTS = ("capture", "linked", "no_catch", "dead_zone")


def _event_counts(rows):
    return {name: sum(row.get("type") == name for row in rows) for name in RECONNECT_GAMEPLAY_EVENTS}


def _new_events(problems, events_before, events_after):
    """The rows `events_after` gained over `events_before`, in the file's own order.

    events.json is NEWEST-FIRST: the server appends with `appendleft` (server/server.py:1488)
    and persists `list(self._recent_events)` (:1481), so a reconnect's new rows are the FRONT of
    the list and a tail slice is the OLDEST history instead. The ring is capped at 200 rows
    (:79), so at the cap every new row also drops the oldest one and the surviving history is a
    PREFIX of the previous list; it is matched here against the tail of the new one. Anything
    else — a row spliced into the middle of the history, a shorter or reordered list — is a
    rewrite, and reading the new hellos out of a rewritten log would be guessing.
    """
    if not events_before:
        return events_after
    kept = min(len(events_after), len(events_before))
    while kept > 0 and events_after[len(events_after) - kept:] != events_before[:kept]:
        kept -= 1
    if kept == 0:
        problems.append("events log shrank or was rewritten")
        return []
    return events_after[:len(events_after) - kept]


def _new_a_hellos(problems, events_before, events_after):
    """A's hellos among the rows this reconnect actually added, not among all of history."""
    return [row for row in _new_events(problems, events_before, events_after)
            if row.get("type") == "hello" and row.get("player") == "a"]


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
        problems.append("a " + "/".join(RECONNECT_GAMEPLAY_EVENTS) + " count changed")
    new_hellos = _new_a_hellos(problems, events_before, events_after)
    if len(new_hellos) != 1 or not new_hellos[0].get("text", "").startswith("Connected (Red, "):
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
        problems.append("a rejected save changed a " + "/".join(RECONNECT_GAMEPLAY_EVENTS)
                        + " count")
    new_hellos = _new_a_hellos(problems, events_before, events_after)
    if len(new_hellos) != 1 or new_hellos[0].get("text") != "REJECTED — wrong save/slot":
        problems.append("A did not add exactly one WRONG SAVE rejection hello")
    return problems


BALL_GATE_FORBIDDEN_EVENTS = {"no_catch", "dead_zone", "force_faint", "force_explode",
                              "memorialize"}


def ball_gate_fact(receipt, label):
    """Read one named, structured cartridge milestone; duplicate/missing facts fail closed."""
    matches = [line[len(label) + 1:] for line in (receipt or "").splitlines()
               if line.startswith(label + " ")]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {label} receipt, got {len(matches)}")
    return json.loads(matches[0])


def ball_gate_pre_problems(status, links, events, hellos):
    """D-2: independent New Game identities, with both server gates still closed."""
    problems = []
    ids = []
    for inst in ("a", "b"):
        hello = hellos[inst]
        ot_id = hello.get("ot_id")
        ids.append(ot_id)
        if not isinstance(ot_id, int) or ot_id <= 0 or ot_id > 0xFFFF:
            problems.append(f"{inst} cold hello has no real trainer ID")
        if (hello.get("map") != 0x26 or hello.get("party_count") != 0
                or hello.get("has_pokeballs") is not False or hello.get("ball_count") != 0):
            problems.append(f"{inst} first hello was not the empty-party, zero-ball bedroom")
        player = (status.get("players") or {}).get(inst) or {}
        if (not player.get("connected") or player.get("nuzlocke_active") is not False
                or player.get("ball_count") != 0):
            problems.append(f"{inst} server ball gate opened before the first ball")
    if ids[0] == ids[1]:
        problems.append("cold New Game trainer IDs are not distinct")
    if links:
        problems.append("a pair linked before the first Poké Ball")
    if any(row.get("type") in BALL_GATE_FORBIDDEN_EVENTS | {"linked"} for row in events):
        problems.append("server emitted a link/death event before either starter arrived")
    return problems


def ball_gate_starters_problems(status, links, events, pre_rival):
    """Gifts link before balls, while both independent nuzlocke gates stay closed."""
    problems = []
    if len(links) != 1 or links[0].get("area_id") != "gift_map_40" or links[0].get("status") != "alive":
        problems.append("starter gifts did not form one alive gift_map_40 pair")
    else:
        link = links[0]
        for inst in ("a", "b"):
            if (link.get(inst) or {}).get("key") != pre_rival[inst].get("key"):
                problems.append(f"{inst} starter key differs from the gift link")
    for inst in ("a", "b"):
        fact = pre_rival[inst]
        player = (status.get("players") or {}).get(inst) or {}
        if (not fact.get("key") or fact.get("capture_count", 0) < 1
                or fact.get("gift") is not True or fact.get("ball_count") != 0):
            problems.append(f"{inst} starter was not captured as a zero-ball gift")
        if player.get("nuzlocke_active") is not False or player.get("ball_count") != 0:
            problems.append(f"{inst} server ball gate opened on the starter gift")
        if not any(row.get("type") == "linked" and row.get("player") == inst for row in events):
            problems.append(f"{inst} gift-link event missing from events.json")
    if any(row.get("type") in BALL_GATE_FORBIDDEN_EVENTS for row in events):
        problems.append("starter gifts resolved a wild encounter or caused a death")
    return problems


def ball_gate_lab_problems(status, links, expected_link, events, labs, pre_rival, released, server_log):
    """Both real Rival1 losses must emit faint but leave the partner untouched."""
    problems = []
    for inst in ("a", "b"):
        lab = labs[inst]
        if (lab.get("result") != 1 or lab.get("hp", 0) <= 0 or lab.get("faint_count", 0) < 1
                or lab.get("ball_count") != 0 or lab.get("has_pokeballs") is not False):
            problems.append(f"{inst} lab loss lacked the real pre-ball faint/heal receipt")
        if lab.get("force_faint") != 0 or lab.get("memorialize") != 0:
            problems.append(f"{inst} received a partner death command before balls")
        player = (status.get("players") or {}).get(inst) or {}
        if player.get("nuzlocke_active") is not False or player.get("ball_count") != 0:
            problems.append(f"{inst} server gate was open during the lab loss")
        if f"[{inst}] faint key=" not in server_log:
            problems.append(f"{inst} lab faint was absent from slink.log")
    if pre_rival["b"].get("hp", 0) <= 0 or pre_rival["b"].get("hp") != released["b"].get("hp"):
        problems.append("B's parked starter HP changed when A fainted")
    if released["b"].get("force_faint") != 0 or released["b"].get("memorialize") != 0:
        problems.append("B received a death command while parked outside battle")
    if links != [expected_link] or any(row.get("type") in BALL_GATE_FORBIDDEN_EVENTS for row in events):
        problems.append("starter pair changed or a wild encounter/death resolved before balls")
    return problems


def ball_gate_flip_problems(status, flips):
    """Both activations must follow the filtered bag_received engine site and the bag read."""
    problems = []
    for inst in ("a", "b"):
        fact = flips[inst]
        player = (status.get("players") or {}).get(inst) or {}
        if (fact.get("signal_count", 0) < 1 or fact.get("ball_count", 0) < 1
                or fact.get("has_pokeballs") is not True):
            problems.append(f"{inst} client did not activate from bag_received")
        if player.get("nuzlocke_active") is not True or player.get("ball_count", 0) < 1:
            problems.append(f"{inst} server did not activate after the bag tick")
    return problems


def ball_gate_after_labs_problems(labs, after):
    """A and B each remain healthy while the other side's rival faint is delivered."""
    problems = []
    for inst in ("a", "b"):
        if after[inst].get("hp") != labs[inst].get("hp"):
            problems.append(f"{inst} starter HP changed after the partner's lab faint")
        if after[inst].get("force_faint") != 0 or after[inst].get("memorialize") != 0:
            problems.append(f"{inst} received a late pre-ball death command")
    return problems


def wait_for(desc, pred, timeout, interval=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = pred()
        if v:
            return v
        time.sleep(interval)
    raise TimeoutError(f"timed out after {timeout}s waiting for {desc}")


def marker(text, pattern, label):
    """The named driver marker's regex match, or a failure that names it.

    A marker is the driver's own log line; one that is absent is absent evidence, so an oracle
    refuses rather than reading a default. The oracle re-derives the ranges from the matched
    values instead of trusting the driver's pass/fail, so a driver that logged a bad number
    without failing still fails here.
    """
    match = re.search(pattern, text or "")
    if not match:
        raise RuntimeError(f"{label}: marker /{pattern}/ not found in the receipt")
    return match


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
    # the battle fixtures rebuilt from scripted play (tools/gen1_fixtures.py). The scenarios it
    # runs are the ones that NAME it: `gen1_new` is opt-in (OPT_IN_GAMES), so the `("gen1",)`
    # family entries and the savestate-less shared ones do not leak in, and every scenario here
    # carries an `oracle` -- a Gen 1 verdict always reads the saved state (A0-H2). duo_gen1_main
    # refuses any name it does not implement, so `--scenario all --game gen1_new` must select
    # exactly this set (pinned in tests/unit/test_e2e_duo_scenario_selection.py).
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
        # When this attempt started, and when each instance was launched: artifact freshness is
        # measured against these, because a leftover file from an earlier run would otherwise
        # read as this run's evidence.
        self._started = time.time()
        self._launch_times = {}
        # Live legs that finished, by scenario name. Set ONLY by the live assert, never by the
        # post-result oracle: a client RESULT must not stand in for a leg that never ran.
        self._live_complete = {}
        self._same_save_artifact = None

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
        if self.cfg.get("cold_boot"):
            # A fresh per-run path makes a cold cartridge independent of any older attempt.
            return os.path.join(self.data_dir, f"saveram_{inst}")
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

    def _raw_state(self):
        """The server's own state dump (`/api/debug/raw_state`).

        `_live.party_keys` here is `SoulLinkState.party_keys` — the field
        `_handle_party_to_box` discards from (server/state.py:2086) — unlike the `party_keys`
        `/api/status` publishes, which `_get_party_ordered` rebuilds from the cartridges'
        party snapshots every tick (server/server.py:2209, :4335-4343). The BOTH_BOXED gate
        reads this one.
        """
        try:
            return api(self.http_port, "GET", "/api/debug/raw_state", timeout=3)
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

    def expected_idle_jitter(self) -> int:
        """The idle-frame count both stubs are told to apply, and the driver must echo back.

        Each attempt varies it so that a retried scenario is not the same run twice under a
        different label (see `jitter_for_attempt`).
        """
        return jitter_for_attempt(self.args.idle_jitter, self.attempt)

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
            "idle_jitter": self.expected_idle_jitter(),
            "cold_boot": bool(self.cfg.get("cold_boot")),
            "max_attempts": 1 if self.cfg.get("cold_boot") else 2,
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
        elif seed and not self.cfg.get("cold_boot"):
            self._seed_instance_save(inst)
        elif self.cfg.get("cold_boot"):
            os.makedirs(self._saveram_dir(inst), exist_ok=True)
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
        self._launch_times[inst] = time.time()
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
            self.launch_instance(inst, seed=not self.cfg.get("cold_boot"))
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

    def _links_bytes(self):
        """The persisted link document's raw bytes, or None before the server writes one.

        Byte identity is the strongest server-side claim a scenario like the soft reset can
        make: it is checked against a baseline taken before either client acted.
        """
        path = os.path.join(self.data_dir, "links.json")
        if not os.path.exists(path):
            return None
        with open(path, "rb") as handle:
            return handle.read()

    def _reconnect_events(self):
        path = os.path.join(self.data_dir, "events.json")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def _wait_ball_fact(self, inst, label, timeout=300):
        def fact():
            receipt = read_result(self.scenario, inst) or ""
            if label + " " not in receipt:
                return None
            return ball_gate_fact(receipt, label)

        return wait_for(f"{inst} {label}", fact, timeout)

    def assert_ball_gate_new(self):
        """Stage the lab rivals separately; take every verdict from the server and receipts."""
        hellos = {inst: self._wait_ball_fact(inst, "BALL_HELLO", 180) for inst in ("a", "b")}
        self.wait_connected()
        self._ball_hellos = hellos
        def check_pre():
            return ball_gate_pre_problems(self._status() or {}, self._links_json(),
                                          self._reconnect_events(), hellos)

        problems = check_pre()
        if problems:
            raise RuntimeError("; ".join(problems))
        self._pydec_note("cold bedroom: two distinct OTs, zero balls, both gates closed")
        self.go()
        pre = {inst: self._wait_ball_fact(inst, "BALL_PRE_RIVAL", 300) for inst in ("a", "b")}
        def starter_link():
            links = self._links_json()
            return links if len(links) == 1 else None

        links = wait_for("starter gift pair", starter_link, 60)
        problems = ball_gate_starters_problems(self._status() or {}, links,
                                               self._reconnect_events(), pre)
        if problems:
            raise RuntimeError("; ".join(problems))
        self._ball_starter_link = links[0]
        self._pydec_note("starter gift_map_40 pair linked with both zero-ball gates closed")
        self._append_reconnect_marker("a", "ALLOW_A_RIVAL")
        a_lab = self._wait_ball_fact("a", "BALL_LAB", 300)
        self._append_reconnect_marker("b", "ALLOW_B_RIVAL")
        b_release = self._wait_ball_fact("b", "BALL_RELEASE_RIVAL", 30)
        b_lab = self._wait_ball_fact("b", "BALL_LAB", 300)
        log_path = os.path.join(self.data_dir, "slink.log")
        with open(log_path, encoding="utf-8", errors="replace") as handle:
            server_log = handle.read()
        problems = ball_gate_lab_problems(self._status() or {}, self._links_json(),
                                          self._ball_starter_link,
                                          self._reconnect_events(), {"a": a_lab, "b": b_lab},
                                          pre, {"b": b_release}, server_log)
        if problems:
            raise RuntimeError("; ".join(problems))
        self._pydec_note("both real Rival1 faints suppressed; gift pair alive; parked B HP unchanged")
        for inst in ("a", "b"):
            self._append_reconnect_marker(inst, "ALLOW_PARCEL")
        after = {inst: self._wait_ball_fact(inst, "BALL_AFTER_LABS", 30) for inst in ("a", "b")}
        problems = ball_gate_after_labs_problems({"a": a_lab, "b": b_lab}, after)
        if problems:
            raise RuntimeError("; ".join(problems))
        flips = {inst: self._wait_ball_fact(inst, "BALL_FLIP", 360) for inst in ("a", "b")}
        wait_for("both server ball gates active", lambda: all(
            ((self._status() or {}).get("players") or {}).get(inst, {}).get("nuzlocke_active")
            for inst in ("a", "b")), 60)
        problems = ball_gate_flip_problems(self._status() or {}, flips)
        if problems:
            raise RuntimeError("; ".join(problems))
        self._pydec_note("both filtered bag_received signals followed by client and server activation")
        for inst in ("a", "b"):
            self._append_reconnect_marker(inst, "ALLOW_SAVE")

    def assert_ball_gate_saved(self, results):
        """Post-result oracle; `results` is the dispatcher contract, consumed by the live leg."""
        if self._links_json() != [self._ball_starter_link]:
            raise RuntimeError("starter gift pair changed before the first wild encounter")
        for process in self.emus:
            process.wait(timeout=30)  # BizHawk flushes the normal SAVE on client.exit.
        for inst, species in (("a", 0x99), ("b", 0xB0)):
            receipt = read_result(self.scenario, inst) or ""
            if "SAVE_WITNESS ball_gate_new" not in receipt or "BALL_SAVED " not in receipt:
                raise RuntimeError(f"{inst} has no ordinary-button save witness")
            _sram, party, _box, _codec = self._saved_gen1_party(inst)
            if (len(party) != 1 or party[0]["species"] != species or party[0]["hp"] <= 0
                    or party[0]["ot_id"] != self._ball_hellos[inst]["ot_id"]):
                raise RuntimeError(f"{inst} qualified save lacks its living original starter")
        self._pydec_note("both flushed SaveRAMs qualify; one living original starter per cartridge")

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
        self._live_complete["reconnect_new"] = False

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
        same_after = {**self._reconnect_document(), "events": self._reconnect_events(),
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
        # The wrong-OT relaunch overwrites this file IN PLACE (shutil.copyfile(wrong,
        # correct_save), further down), so the same-save leg's flush is copied out here, while
        # it is still the same-save leg's bytes, and read back by assert_reconnect_saved.
        self._same_save_artifact = os.path.join(BUILD, "e2e_reconnect_new_a_same.SaveRAM")
        shutil.copyfile(correct_save, self._same_save_artifact)
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
            self._live_complete["reconnect_new"] = True
            final_a = wrong_path
        shutil.copyfile(final_a, self._result_path("a"))
        self._append_reconnect_marker("b", "B_DONE")
        wait_for("B stayed online through reconnect legs", lambda: "RESULT: PASS" in (
            read_result(self.scenario, "b") or ""), 120)
        return self._live_complete.get("reconnect_new", False)

    def assert_reconnect_saved(self, results):
        """C-2/C-1 saved states: each leg's flushed SaveRAM, read as the cartridge that wrote it.

        The wrong-OT relaunch overwrites A's SaveRAM in place, so the same-save leg has to be
        read from the artifact the live assert copied out before that (`_same_save_artifact`);
        the instance's own file then describes the wrong-save phase. Both reads name their file
        and phase in the PYDEC receipt: the OT expectation is what tells the two apart, so a
        wrong-path or stale read cannot pass as the other leg.
        """
        if not self._live_complete.get("reconnect_new"):
            raise RuntimeError("reconnect_new's live legs did not complete — the final A save "
                               "belongs to the wrong-save phase and the same-save flush was "
                               "never copied out")
        from gen1_fixtures import DEFAULT_OT, saved_ot

        for process in self.emus:
            process.wait(timeout=30)  # client.exit flushes CartRAM
        same = self._artifact(self._same_save_artifact, "C-2 same-save SaveRAM")
        same_sram, same_party, _same_box, codec = self._saved_gen1_party("a", save_name=str(same))
        same_keys = [codec.key(mon) for mon in same_party]
        same_ot = saved_ot(same_sram, "red")
        if self._link_keys["a"] not in same_keys:
            raise RuntimeError(f"same-save artifact lacks A's linked key {self._link_keys['a']}: "
                               f"{same_keys}")
        if same_ot != DEFAULT_OT:
            raise RuntimeError(f"same-save artifact carries OT 0x{same_ot:04X}, not the clean "
                               f"Red OT 0x{DEFAULT_OT:04X} — it is not the same-save flush")
        self._pydec_note(f"phase same_save: {os.path.relpath(same, REPO)} OT 0x{same_ot:04X}, "
                         f"linked key present, party {same_keys}")

        final_sram, final_party, _final_box, _codec = self._saved_gen1_party("a")
        final_keys = [codec.key(mon) for mon in final_party]
        final_ot = saved_ot(final_sram, "red")
        if final_ot == DEFAULT_OT:
            raise RuntimeError(f"final A save still carries the clean Red OT 0x{final_ot:04X}; "
                               f"the wrong-OT relaunch did not replace the same-save file")
        if self._link_keys["a"] in final_keys:
            raise RuntimeError(f"the wrong-OT save still holds A's linked key "
                               f"{self._link_keys['a']}: {final_keys}")
        self._pydec_note(f"phase wrong_save: OT 0x{final_ot:04X} != 0x{DEFAULT_OT:04X}, "
                         f"linked key absent, party {final_keys}")

    def assert_soft_reset_saved(self, results):
        """W-6/R-4: A's same-save soft reset, from the driver's markers and the server's refusal
        to see anything but a reconnect.

        The reset zero-fills $C000-$DFFF while the client is mid-flight, so the load-bearing
        claims are about what did NOT happen: no WRAM and no cart write landed on the cleared
        window, the durable pair is byte-identical to the pre-reset baseline, and the re-hello
        carried the SAME trainer ID. Every marker read here is named in the PYDEC receipt.
        """
        from pathlib import Path

        from gen1_fixtures import saved_ot

        from server.adapters import gen1_codec as codec

        for process in self.emus:
            process.wait(timeout=30)  # client.exit flushes CartRAM
        a_text, b_text = results["a"], results["b"]

        ot = marker(a_text, r"HELLO_AT_CHECKPOINT ot=([0-9A-Fa-f]{4}) hellos=1",
                    "A checkpoint hello")
        reset = marker(a_text, r"RESET_SEEN frame=(\d+)", "A soft reset")
        if not 40 <= int(reset.group(1)) <= 60:
            raise RuntimeError(f"A's WRAM clear landed {reset.group(1)} frames after the chord "
                               f"started, outside 40..60 (16 polls + 32 DelayFrames)")
        cleared = marker(a_text, r"HELLO_CLEARED frame=\d+ delta=(\d+)", "A hello withhold")
        if int(cleared.group(1)) > 120:
            raise RuntimeError(f"A's hello_sent survived {cleared.group(1)} frames of cleared "
                               f"WRAM (one validation is 60)")
        paused = marker(a_text, r"WRITES_PAUSED frame=\d+ delta=(\d+)", "A writes pause")
        if not 240 <= int(paused.group(1)) <= 360:
            raise RuntimeError(f"A paused writes {paused.group(1)} frames after the reset, "
                               f"outside 240..360 (5 x 60-frame validations)")
        started, resumed = a_text.find("WRITES_PAUSED"), a_text.find("WRITES_RESUMED")
        if resumed < 0 or resumed < started:
            raise RuntimeError("A never logged WRITES_RESUMED after WRITES_PAUSED")
        marker(a_text, r"CONTINUED frame=", "A CONTINUE")
        rehello = marker(a_text, r"REHELLO ot=([0-9A-Fa-f]{4}) hellos=2", "A re-hello")
        if rehello.group(1).upper() != ot.group(1).upper():
            raise RuntimeError(f"A re-helloed as OT {rehello.group(1)}, not the pre-reset "
                               f"OT {ot.group(1)}")
        marker(a_text, r"NO_WRITES_IN_WINDOW writes=0 cart_writes=0", "A cleared-window witness")
        marker(a_text, r"SAVE_WITNESS soft_reset_new_a", "A save witness")
        marker(a_text, r"\[SLink-gen1\] writes PAUSED", "A client pause line")
        marker(a_text, r"writes re-enabled after a live validation", "A client resume line")
        for absent in ("BOX_WRITE ", "RX force_faint", "RX box_mon"):
            if absent in a_text:
                raise RuntimeError(f"A's reset receipt carries {absent!r}; nothing may write to "
                                   f"the cleared window")
        marker(b_text, r"IDLE_PARTNER hellos=1", "B idle partner")
        marker(b_text, r"SAVE_WITNESS soft_reset_new_b", "B save witness")
        self._pydec_note(f"W-6 markers: RESET_SEEN={reset.group(1)} HELLO_CLEARED="
                         f"{cleared.group(1)} WRITES_PAUSED={paused.group(1)} "
                         f"OT={ot.group(1)} re-hello={rehello.group(1)}; "
                         f"NO_WRITES_IN_WINDOW 0/0; no BOX_WRITE/force_faint/box_mon")

        baseline = self._reset_baseline
        rows = self._reconnect_events()
        a_hellos = [row for row in rows if row.get("type") == "hello" and row.get("player") == "a"]
        b_hellos = [row for row in rows if row.get("type") == "hello" and row.get("player") == "b"]
        # The baseline is taken after `wait_connected`, and a client's ticks are gated on its
        # hello (lua/gen1/client.lua:908-912,920), so both players had exactly one hello row
        # when it was taken. If that ever stops being true this fails loudly instead of quietly
        # checking "one more than whatever the baseline happened to be".
        if baseline["a_hellos"] != 1:
            raise RuntimeError(f"the pre-reset baseline saw {baseline['a_hellos']} A hellos, not "
                               f"the one the checkpoint hello produces")
        if (len(a_hellos) != baseline["a_hellos"] + 1
                or not all(row.get("text", "").startswith("Connected (") for row in a_hellos)):
            raise RuntimeError(f"A's durable hellos are not baseline+1 accepted rows: {a_hellos}")
        if len(b_hellos) != 1 or not b_hellos[0].get("text", "").startswith("Connected ("):
            raise RuntimeError(f"B's durable hello is not one accepted row: {b_hellos}")
        if any("REJECTED" in row.get("text", "") for row in rows):
            raise RuntimeError("a REJECTED hello appeared during a same-save reset")
        if _event_counts(baseline["events"]) != _event_counts(rows):
            raise RuntimeError("gameplay event counts changed across the soft reset")
        if self._links_bytes() != baseline["links_bytes"]:
            raise RuntimeError("links.json changed across the soft reset")
        self._pydec_note(f"server: A hellos {len(a_hellos)} = baseline {baseline['a_hellos']}+1, "
                         f"B {len(b_hellos)}, 0 REJECTED, gameplay counts unchanged, "
                         f"links.json byte-identical")

        for inst, title in (("a", "red"), ("b", "blue")):
            fixture = Path(self._fixture_save_path(inst)).read_bytes()
            start = codec.SRAM_LAYOUT["sPartyData"]
            want = [codec.key(mon) for mon in codec.decode_party(
                fixture[start:start + codec.PARTY_LAYOUT["size"]])]
            sram, party, _box, _codec = self._saved_gen1_party(inst)
            got = [codec.key(mon) for mon in party]
            if got != want:
                raise RuntimeError(f"{inst}'s saved party {got} is not the fixture's {want}: the "
                                   f"reset did not reload the same save")
            if saved_ot(sram, title) != saved_ot(fixture, title):
                raise RuntimeError(f"{inst}'s saved trainer ID changed across the reset")
            self._pydec_note(f"{inst} saved party {got} == fixture "
                             f"{self.gcfg['fixture'][inst]}_{self.cfg.get('target', 'town')}; "
                             f"OT 0x{saved_ot(sram, title):04X} unchanged")

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

    def _artifact(self, path, label):
        """A file this run wrote, with its provenance checked.

        Existence alone is not provenance: a leftover from an earlier run would read as this
        run's evidence, so the mtime has to be later than the attempt's start.
        """
        from pathlib import Path

        if not path:
            raise RuntimeError(f"{label} artifact was never produced by this run")
        file = Path(path)
        if not file.is_file():
            raise RuntimeError(f"{label} artifact missing: {file}")
        age = self._started - file.stat().st_mtime
        if age > 0:
            raise RuntimeError(f"{label} artifact is stale: {file} predates this run's start "
                               f"by {age:.0f}s")
        return file

    def _fixture_save_path(self, inst):
        """The committed fixture this instance was seeded from — the bag baseline's source.

        `run_gb_gate.seed_saveram` copies `<rom>_<target>.SaveRAM` from this directory into the
        instance's SaveRAM dir, so reading it here compares the flushed bag with the bytes the
        cartridge actually booted from.
        """
        import gen1_playthrough as play

        return os.path.join(play.FIXTURES,
                            f"{self.gcfg['fixture'][inst]}_{self.cfg.get('target', 'town')}.SaveRAM")

    def _saved_gen1_party(self, inst, rom=None, save_name=None):
        """PYDEC + the fixture qualifier on the cartridge's flushed 32 KiB SaveRAM.

        `rom` (repo-relative, the path the instance launched) and `save_name` override the
        clean-title defaults, which name the wrong file for two scenarios: admit_randomized_new
        launches the staged randomized Red, whose SaveRAM carries the filename-derived name a
        hash BizHawk does not know resolves to, and reconnect_new's same-save leg is overwritten
        in place by the wrong-OT copy before the run ends. An absolute `save_name` is read as
        given; a relative one resolves inside the instance's own SaveRAM directory.
        """
        from pathlib import Path

        if REPO not in sys.path:
            sys.path.insert(0, REPO)
        from gen1_fixtures import qualify
        from run_gb_gate import GENS

        from server.adapters import gen1_codec as codec

        title = self.gcfg["fixture"][inst]
        name = save_name or GENS["gen1"]["saveram_names"][title]
        path = Path(name) if os.path.isabs(str(name)) else Path(self._saveram_dir(inst)) / name
        sram = path.read_bytes()
        rom_bytes = (Path(REPO) / (rom or self.gcfg["rom"][inst])).read_bytes()
        # tools/gen1_fixtures.py:57-83 uses codec.verify_bank1 (the game's CalcCheckSum),
        # decode_party, level_from_exp and recompute_stats against this exact ROM.
        problems = qualify(sram, rom_bytes)
        if problems:
            raise RuntimeError(f"{inst} saved game would not qualify: {problems}")
        start = codec.SRAM_LAYOUT["sPartyData"]  # gen1_codec.py:66-72,587-595
        party = codec.decode_party(sram[start:start + codec.PARTY_LAYOUT["size"]])
        current = codec.SRAM_LAYOUT["sCurBoxData"]  # the WRAM mirror is copied here on SAVE
        current_box = codec.decode_box(sram[current:current + codec.BOX_SIZE])
        self._pydec_note(f"{inst} main checksum/exp/recomputed stats valid; saved party/current box decode valid")
        return sram, party, current_box, codec

    def assert_link_new_saved(self, results):
        """The caught halves are saved in slot 1, with PYDEC-rebuilt stored stats, and each
        half's bag is exactly one Poke Ball lighter than the fixture it booted from."""
        from pathlib import Path

        for process in self.emus:
            process.wait(timeout=30)  # BizHawk flushes CartRAM when client.exit completes
        for inst in ("a", "b"):
            sram, party, current_box, codec = self._saved_gen1_party(inst)
            keys = [codec.key(mon) for mon in party]  # gen1_codec.py:602-610
            expected = [self._boot_keys[inst], self._link_keys[inst]]
            if keys != expected:
                raise RuntimeError(f"{inst} saved link party {keys}, expected starter/withdrawn {expected}")
            if any(codec.key(mon) == self._link_keys[inst] for mon in current_box):
                raise RuntimeError(f"{inst} saved current box still holds its withdrawn linked mon")
            # qualify() above independently invokes codec.recompute_stats on both mons
            # (tools/gen1_fixtures.py:70-82; gen1_codec.py:738-751).
            fixture = Path(self._fixture_save_path(inst)).read_bytes()
            baseline = codec.bag_quantity(fixture, codec.POKE_BALL)  # gen1_codec.py:642-645
            final = codec.bag_quantity(sram, codec.POKE_BALL)
            self._pydec_note(f"BAG_BALLS baseline={baseline} final={final} inst={inst}")
            if final != baseline - 1:
                raise RuntimeError(
                    f"{inst} saved bag holds {final} Poke Balls; the fixture it booted from "
                    f"carried {baseline}, and this route throws exactly one")
            self._pydec_note(f"{inst} saved slot 0 starter {keys[0]}")
            self._pydec_note(f"{inst} saved slot 1 linked {keys[1]}, no current-box duplicate")

    def assert_dead_zone_new_saved(self, results):
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

    def _patched_saved_state(self, inst):
        """The flushed SaveRAM of a trade-carrying cartridge (companion patch in the ROM).

        Those scenarios launch `patch/gen1/build/slink_{red,blue}.gb`, whose SaveRAM name is the
        filename-derived patched one, so the clean-title default would read the wrong file. One
        resolver, shared by every oracle that runs those ROMs.
        """
        if REPO not in sys.path:
            sys.path.insert(0, REPO)  # python tools/e2e_duo.py otherwise has tools/ at sys.path[0]
        from run_gb_gate import GENS

        save_name = GENS["gen1"]["patched"][self.cfg["patched_saves"][inst]][2]
        return self._saved_gen1_party(inst, rom=self.cfg["rom"][inst], save_name=save_name)

    def assert_linked_faint_saved(self, results, *, active, saved_state=None):
        """D-6/W-1/W-2: server cause + both game-loadable memorials and engine receipts.

        `saved_state(inst)` defaults to the clean-title read; explode_new passes the patched
        resolver because it runs the trade-carrying ROMs, whose SaveRAM name and ROM differ.
        """
        read = saved_state or self._saved_gen1_party
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
            sram, party, current_box, codec = read(inst)
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

    def assert_explode_saved(self, results):
        """W-3/D-11: the shared faint half plus the markers only a companion-patched cartridge
        with `--explode-mode` can produce.

        The saved-state half is `assert_linked_faint_saved(active=True)` run through the
        patched-save resolver, because explode_new launches the trade-carrying ROMs: the pair
        must be dead with cause battle and both Box 12s must hold the linked key at HP 0. B's
        markers then prove the path was Explode Mode's: the in-battle VBlank counter advanced
        (the patch's hook still runs), the server sent only `force_explode`, the move menu
        showed the catch's own moves BEFORE the write and four EXPLOSIONs after it, and the
        commit was the coerced turn rather than a queued one.
        """
        self.assert_linked_faint_saved(results, active=True,
                                       saved_state=self._patched_saved_state)
        a_text, b_text = results["a"], results["b"]

        marker(a_text, r"A_ENGINE_FAINT", "A engine faint")
        marker(a_text, r"BATTLE_FAINT_SITE ", "A battle faint site")
        marker(a_text, r"SAVE_WITNESS explode_new", "A save witness")
        marker(b_text, r"READY_ACTIVE linked_slot=0", "B active hold")
        counters = marker(b_text, r"PANEL_COUNTER_IN_BATTLE a=(\d+) b=(\d+)", "B VBlank probe")
        if counters.group(1) == counters.group(2):
            raise RuntimeError(f"B's in-battle VBlank counter did not advance across a frame "
                               f"({counters.group(1)} == {counters.group(2)}); the patch's hook "
                               f"is not running inside the battle")
        marker(b_text, r"RX force_explode key=", "B explode command")
        cmds = marker(b_text, r"EXPLODE_CMDS force_explode=(\d+) force_faint=(\d+)",
                      "B command split")
        if cmds.group(1) != "1" or cmds.group(2) != "0":
            raise RuntimeError(f"Explode Mode sent force_explode={cmds.group(1)} "
                               f"force_faint={cmds.group(2)}, expected 1 / 0")
        before = marker(b_text, r"MOVE_MENU_BEFORE (.*)", "B pre-write move menu")
        if "EXPLOSION" in before.group(1):
            raise RuntimeError(f"the move menu already showed EXPLOSION before the write landed: "
                               f"{before.group(1)!r}")
        loop = marker(b_text, r"LOOP_HEAD_EXPLODE moves=(\S+) pp=(\S+)", "B loop-head write")
        if loop.group(1) != "99999999" or loop.group(2) != "01010101":
            raise RuntimeError(f"B's battle struct after the write reads moves={loop.group(1)} "
                               f"pp={loop.group(2)}, expected 99999999 / 01010101")
        marker(b_text, r"MOVE_MENU_AFTER EXPLOSION \| EXPLOSION \| EXPLOSION \| EXPLOSION",
               "B post-write move menu")
        marker(b_text, r"MOVE_MENU_EXPLOSION rows=4", "B four EXPLOSION rows")
        marker(b_text, r"B_ACTIVE_COMMIT player_move", "B commit")
        marker(b_text, r"BATTLE_FAINT_SITE .* battle_hp=0", "B battle faint site")
        marker(b_text, r"BATTLE_RESULT b", "B battle result")
        marker(b_text, r"SAVE_WITNESS explode_new", "B save witness")
        for absent in ("RX force_faint", "LOOP_HEAD_WRITE", "PANEL_COUNTER_IN_BATTLE absent"):
            if absent in b_text:
                raise RuntimeError(f"B's explode receipt carries {absent!r}")
        self._pydec_note(f"W-3/D-11 markers: VBlank counter {counters.group(1)}->"
                         f"{counters.group(2)}, force_explode={cmds.group(1)} "
                         f"force_faint={cmds.group(2)}, menu before={before.group(1).strip()!r}, "
                         f"loop head moves={loop.group(1)} pp={loop.group(2)}, rows=4, "
                         f"player_move commit; absent RX force_faint/LOOP_HEAD_WRITE/absent-probe")

        # Routing only: this row says the SERVER asked for an explode, not that the game ran one
        # (state.py:2678-2680 picks the command name; server.py:1918-1922 logs the verb). The
        # engine markers above are the execution proof, so the row is recorded, never asserted.
        exploded = [row.get("text", "") for row in self._reconnect_events()
                    if row.get("type") == "force_explode"]
        self._pydec_note(f"events.json force_explode rows: {exploded} (routing only)")

    def assert_pc_ops_new_saved(self, results):
        """S-6 (Bill's PC by play) and the documented release gap.

        A deposits its linked half, withdraws it, deposits it again and RELEASES it from the box.
        The first three operations are on the wire; the release is NOT — the client logs
        `RELEASE_SEEN key=… box=…` and sends nothing (lua/gen1/client.lua:571-592) — so the
        server keeps the pair ALIVE with a phantom boxed half. That is the shared-protocol gap
        this scenario pins, not a defect of the run, and the status/links assertions below say so
        explicitly rather than treating it as a failure.

        The box checksum claim is scoped to the box this run wrote: pc_ops_new never changes
        boxes, so the untouched banks stay at $FF and only Box 1's own checksum and its bank's
        whole-bank checksum are meaningful. The all-twelve form belongs to the scenarios that
        run a ChangeBox (deadzone/changebox), where the game initialises every box.
        """
        for process in self.emus:
            process.wait(timeout=30)  # client.exit flushes CartRAM
        a_text, b_text = results["a"], results["b"]
        key, partner_key = self._link_keys["a"], self._link_keys["b"]

        before = marker(a_text, r"PC_BOX_BEFORE box=(\d+) count=(\d+)", "A pre-deposit box")
        if before.group(1) != "1" or before.group(2) != "0":
            raise RuntimeError(f"A's Box {before.group(1)} held {before.group(2)} mon(s) before "
                               f"the deposit; the scenario needs Box 1 empty")
        counts = {name: len(re.findall(pattern, a_text)) for name, pattern in (
            ("deposit start", r"PC_OP deposit start"), ("deposit done", r"PC_OP deposit done"),
            ("withdraw done", r"PC_OP withdraw done"),
            ("release_box done", r"PC_OP release_box done"))}
        if (counts["deposit start"], counts["deposit done"]) != (2, 2):
            raise RuntimeError(f"A ran {counts['deposit start']}/{counts['deposit done']} deposit "
                               f"start/done ops, expected 2/2")
        if counts["withdraw done"] != 1 or counts["release_box done"] != 1:
            raise RuntimeError(f"A ran {counts['withdraw done']} withdraw and "
                               f"{counts['release_box done']} release ops, expected 1 each")

        tx_box = re.findall(r'^TX .*"event":"party_to_box".*' + re.escape(key), a_text, re.M)
        tx_party = re.findall(r'^TX .*"event":"box_to_party".*' + re.escape(key), a_text, re.M)
        if len(tx_box) != 2 or len(tx_party) != 1:
            raise RuntimeError(f"A sent {len(tx_box)} party_to_box and {len(tx_party)} "
                               f"box_to_party for {key}, expected 2 and 1")
        marker(a_text, re.escape("PC_DEPOSIT_KEY " + key), "A deposit key")
        marker(a_text, re.escape("PC_WITHDRAW_KEY " + key), "A withdraw key")
        marker(a_text, re.escape("PC_RELEASE_SEEN " + key), "A release receipt")
        marker(a_text, r"PC_MID party=2 box=1 count=0", "A mid state")

        releases = re.findall(r"RELEASE_SEEN key=(\S+) box=(\d+)", a_text)
        if len(releases) != 1:
            raise RuntimeError(f"A logged {len(releases)} RELEASE_SEEN line(s), expected exactly one")
        if releases[0][0] != key or releases[0][1] != "0":
            raise RuntimeError(f"RELEASE_SEEN named {releases[0][0]} box={releases[0][1]}, "
                               f"expected {key} box=0")
        offsets = [m.start() for m in re.finditer(
            r'^TX .*"event":"(?:party_to_box|box_to_party)"', a_text, re.M)]
        release_at = a_text.find("RELEASE_SEEN key=")
        # The Lua stamps each RELEASE_SEEN with the number of storage sends before it and
        # refuses anything but "after all three" (duo_gen1_main.lua:1566-1571): deposit,
        # withdraw, second deposit. The release itself sends nothing.
        if len(offsets) != 3 or release_at < offsets[-1]:
            raise RuntimeError(f"RELEASE_SEEN is not after the third storage send "
                               f"({len(offsets)} sends, release at {release_at}, last at "
                               f"{offsets[-1] if offsets else -1})")

        marker(a_text, r"PC_FINAL party=1 box=1 count=0 init=true", "A final state")
        marker(a_text, r"SAVE_WITNESS pc_ops_new_a", "A save witness")
        rx1 = marker(b_text, r"PC_PARTNER_RX 1 box_mon (\S+)", "B partner box_mon")
        rx2 = marker(b_text, r"PC_PARTNER_RX 2 party_mon (\S+)", "B partner party_mon")
        if rx1.group(1) != partner_key or rx2.group(1) != partner_key:
            raise RuntimeError(f"B's partner sync named {rx1.group(1)} / {rx2.group(1)}, expected "
                               f"{partner_key} for both")
        if b_text.find("PC_PARTNER_RX 1") > b_text.find("PC_PARTNER_RX 2"):
            raise RuntimeError("B's partner sync arrived party_mon before box_mon")
        if b_text.find("PC_PARTNER_RX 3") >= 0:
            raise RuntimeError("B received a third storage command; the second deposit's sync "
                               "was supposed to land before B finished")
        marker(b_text, r"SAVE_WITNESS pc_ops_new_b", "B save witness")
        self._pydec_note("S-6 markers: Box 1 empty->deposit->withdraw->deposit->release; "
                         "2/1 storage sends, one RELEASE_SEEN after the third send, no wire event")

        a_sram, a_party, _a_box, codec = self._saved_gen1_party("a")
        a_keys = [codec.key(mon) for mon in a_party]
        if a_keys != [self._boot_keys["a"]]:
            raise RuntimeError(f"A's saved party is {a_keys}, expected the starter alone after "
                               f"the release")
        verdict = codec.verify_boxes(a_sram)
        box1 = verdict["boxes"][1]
        if not box1["valid"]:
            raise RuntimeError(f"A's saved Box 1 checksum does not match (stored "
                               f"{box1['stored']:02X}, calculated {box1['calculated']:02X})")
        boxed = codec.decode_box(a_sram[box1["offset"]:box1["offset"] + codec.BOX_SIZE])
        if any(codec.key(mon) == key for mon in boxed):
            raise RuntimeError(f"A's saved Box 1 still holds the released key {key}")
        if not verdict["banks"][2]["valid"]:
            raise RuntimeError("A's saved Box 1-6 bank checksum does not match")
        b_sram, b_party, _b_box, _codec = self._saved_gen1_party("b")
        b_keys = [codec.key(mon) for mon in b_party]
        if b_keys != [self._boot_keys["b"], partner_key]:
            raise RuntimeError(f"B's saved party is {b_keys}, expected starter + {partner_key}")
        self._pydec_note(f"{key} released: A's saved party is the starter alone, Box 1 checksum "
                         f"valid and empty; B still holds {partner_key}")

        # The documented gap, asserted as such: the release never reached the server, so the
        # pair is still ALIVE with A's key on the status surface and in links.json. This is the
        # OBSERVED limit, not a defect -- the receipt says so.
        live = [entry for entry in (self._status() or {}).get("links", [])
                if entry.get("area_id") == "route_1"]
        if len(live) != 1 or live[0].get("a_key") != key:
            raise RuntimeError(f"/api/status no longer lists A's linked key {key} after the "
                               f"release: {live}")
        durable = [entry for entry in self._links_json() if entry.get("area_id") == "route_1"]
        if (len(durable) != 1 or durable[0].get("status") != "alive"
                or durable[0].get("a", {}).get("key") != key):
            raise RuntimeError(f"the durable pair did not stay ALIVE with {key}: {durable}")
        self._pydec_note(f"server bookkeeping UNCHANGED by the release (documented limit): "
                         f"alive route_1 pair still lists a={key}; the release is invisible")

    def assert_changebox_new_saved(self, results):
        """W-5's box-change half: the deadzone body, then B CHANGEs BOX to 12 and back to 1.

        The shared half is `assert_dead_zone_new_saved` (A untouched, B's dead-zone catch is in
        Box 12 at HP 0 with every box bank initialised). B's own receipt then proves the change:
        Box 12 listed the memorial, the current box went back to 1, and the run sent no storage
        event of its own — a box change is a local PC action, not a party/box transfer.
        """
        self.assert_dead_zone_new_saved(results)
        b_text = results["b"]
        at12 = marker(b_text, r"CHANGEBOX_TO 12 initialised=true count=(\d+)", "B change to Box 12")
        if int(at12.group(1)) < 1:
            raise RuntimeError(f"Box 12 listed {at12.group(1)} mon(s) after the change; the "
                               f"memorial has to still be there")
        marker(b_text, r"CHANGEBOX_BACK 1", "B change back to Box 1")
        marker(b_text, r"SAVE_WITNESS changebox_new_b", "B save witness")
        for pattern, label in ((r'"event":"party_to_box"', "party_to_box"),
                               (r'"event":"box_to_party"', "box_to_party"),
                               (r"RELEASE_SEEN", "RELEASE_SEEN")):
            if re.search(pattern, b_text):
                raise RuntimeError(f"B's changebox receipt carries {label}; a box change is not "
                                   f"a storage transfer")

        b_sram, _b_party, _b_box, codec = self._saved_gen1_party("b")
        flag = b_sram[codec._CURRENT_BOX]
        index = flag & ~codec._BOX_INITIALIZED
        if not flag & codec._BOX_INITIALIZED:
            raise RuntimeError("B's saved has-changed-boxes bit is clear after CHANGE BOX")
        if index != 0:
            raise RuntimeError(f"B's saved current box is {index}, expected Box 1 (index 0)")
        verdict = codec.verify_boxes(b_sram)
        box12 = verdict["boxes"][12]
        memorial = codec.decode_box(b_sram[box12["offset"]:box12["offset"] + codec.BOX_SIZE])
        if (len(memorial) != 1 or codec.key(memorial[0]) != self._deadzone_b_key
                or memorial[0]["hp"] != 0):
            raise RuntimeError(f"Box 12 no longer holds {self._deadzone_b_key} at HP 0: "
                               f"{[(codec.key(mon), mon['hp']) for mon in memorial]}")
        self._pydec_note(f"W-5 box change: Box 12 listed {at12.group(1)} memorial(s), back to "
                         f"Box 1; saved flag set, index {index}, {self._deadzone_b_key} still "
                         f"HP 0 in Box 12; no storage event on the wire")

    def assert_whiteout_both_boxed(self):
        """The runner's half of the BOTH_BOXED handshake, before either cartridge may leave
        the PC.

        The Lua polls its go-file for the literal BOTH_BOXED (duo_gen1_main.lua:1849-1853,
        900 s budget) instead of trusting the mirrored box_mon, and this is the process that
        has to write it. Both halves deposit by hand, and a deposit is mirrored to the partner
        the moment the server sees `party_to_box` -- so the partner's key leaves `party_keys`
        there, before that cartridge has moved anything (server/state.py:2066-2113). A
        mirrored box_mon arriving at an already-deposited mon is a no-op, not a failure
        (lua/gen1/boxes.lua:296-318). Bookkeeping is therefore not evidence; this gate is the
        runner reading the server for itself:

          1. both driver receipts carry DEPOSITED_FOR_REBUILD <their own linked key> (the
             physical read: party = starter only, the catch listed in the active box);
          2. the SERVER's `state.party_keys` no longer lists either key -- the field
             `_handle_party_to_box` discards from (server/state.py:2086 own half, :2108
             mirrored half), and exactly the co-location predicate `_alive_pc_mons` uses to
             pick rebuild candidates (server/state.py:2359-2360). If this passes, the blackout
             that follows has a pair to rebuild from. The `party_keys` `/api/status` publishes
             is NOT this field: `_get_party_ordered` rebuilds it from the cartridges' own
             party snapshots (server/server.py:2209, :4335-4343);
          3. only then BOTH_BOXED into both go-files, through the same writer `go()` uses.
        """
        keys = self._link_keys
        missing = {}

        def deposited():
            missing.clear()
            for inst in ("a", "b"):
                text = read_result(self.scenario, inst) or ""
                if not re.search(re.escape("DEPOSITED_FOR_REBUILD " + keys[inst]), text):
                    missing[inst] = f"no DEPOSITED_FOR_REBUILD {keys[inst]} yet"
            return True if not missing else None

        try:
            wait_for("both halves to deposit their linked catch for the rebuild", deposited,
                     self.cfg["timeout"])
        except TimeoutError as exc:
            raise RuntimeError("the deposit never landed — "
                               + "; ".join(f"{inst}: {why}" for inst, why in missing.items())) from exc

        problems = {}

        def server_agrees():
            live = (self._raw_state() or {}).get("_live") or {}
            party_keys = live.get("party_keys") or {}
            problems.clear()
            for inst in ("a", "b"):
                field = party_keys.get(inst)
                if field is None:
                    problems[inst] = "party_keys: the server published no such field"
                elif keys[inst] in field:
                    problems[inst] = f"party_keys still lists {keys[inst]}: {field}"
            return True if not problems else None

        try:
            wait_for("the SERVER to see both linked keys boxed", server_agrees, 300)
        except TimeoutError as exc:
            raise RuntimeError(
                "the server never saw both halves boxed — "
                + "; ".join(f"{inst}: {why}" for inst, why in problems.items())) from exc
        for inst in ("a", "b"):
            self._go_one(inst, ["BOTH_BOXED"])
        print(f"[duo] BOTH_BOXED appended for both halves; the server's party_keys dropped "
              f"{keys['a']} and {keys['b']}")

    def assert_whiteout_new_saved(self, results):
        """S-4 (blackout) + W-3 (auto-rebuild): one whiteout, one rebuild, no deaths.

        Both halves deposit their linked catch, A loses its starter to a wild foe and blacks
        out to Pallet Town. `_handle_whiteout` retires only links whose half is still in the
        WHITED-OUT player's `party_keys` (server/state.py:2024-2026) — both halves are boxed —
        and plans the rebuild from alive pairs with both halves boxed (`_alive_pc_mons`
        :2359-2360, `_plan_rebuild` :2365-2392). One `party_mon` is queued to each half and
        `rebuild_start` to A alone (`_queue_rebuild_commands` :2418-2443); `rebuild_done`
        follows once A's own `sync_retrieve_done` lands (:2448-2462). Both are COMMANDS, so
        they are evidenced by the RX lines the driver tees, never by events.json, which is the
        server's ring buffer of INBOUND events (`_log_event`, server/server.py:1505-1516).
        `game_over` is a command too; the "no game over" claim is asserted as its durable
        cause: the pair is still ALIVE, `run_over` is false, and neither client was told.

        The saved state is read through the same PYDEC path as `assert_pc_ops_new_saved`
        (`_saved_gen1_party`, whose `qualify()` checks the game's own checksum and recomputed
        stats). This scenario runs the clean fixtures, so the patched-ROM resolver
        (`_patched_saved_state`) does not apply.
        """
        for process in self.emus:
            process.wait(timeout=30)  # BizHawk flushes CartRAM when client.exit completes
        self._artifact(self._result_path("a"), "A result receipt")
        self._artifact(self._result_path("b"), "B result receipt")
        a_text, b_text = results["a"], results["b"]
        key_a, key_b = self._link_keys["a"], self._link_keys["b"]

        # The blackout, re-derived from the driver's numbers rather than its MONEY_HALVED
        # verdict: the game halves the BCD total, so after == before // 2 or the run is wrong.
        before = marker(a_text, r"MONEY_BEFORE (\d+)", "A money before the blackout")
        after = marker(a_text, r"MONEY_AFTER (\d+)", "A money after the blackout")
        expected = int(before.group(1)) // 2
        if int(after.group(1)) != expected:
            raise RuntimeError(f"A's money went {before.group(1)} -> {after.group(1)}; the "
                               f"blackout halves it to {expected}")
        marker(a_text, r"MONEY_HALVED before=\d+ after=\d+", "A money-halving receipt")
        site = marker(a_text, r"BLACKOUT_SITE map=(\d+) x=(\d+) y=(\d+)", "A blackout site")
        if site.groups() != ("0", "5", "6"):
            raise RuntimeError(f"A blacked out to map={site.group(1)} "
                               f"({site.group(2)},{site.group(3)}), not Pallet Town (0, 5, 6)")
        ko = marker(a_text, r"STARTER_KO frame=\d+ key=(\S+)", "A starter KO")
        if ko.group(1) != self._boot_keys["a"]:
            raise RuntimeError(f"A's KO'd key is {ko.group(1)}, not the boot starter "
                               f"{self._boot_keys['a']}; the linked half was supposed to be "
                               f"boxed and out of the battle")
        tx = re.findall(r'^TX .*"event":"whiteout"', a_text, re.M)
        if len(tx) != 1:
            raise RuntimeError(f"A sent {len(tx)} whiteout event(s), expected exactly one")
        if re.search(r'"event":"whiteout"', b_text):
            raise RuntimeError("B sent a whiteout; only the blacked-out half may")

        for inst, key in (("a", key_a), ("b", key_b)):
            text = results[inst]
            marker(text, re.escape("DEPOSITED_FOR_REBUILD " + key), f"{inst} deposit-for-rebuild")
            marker(text, re.escape("BOTH_BOXED status=true"), f"{inst} BOTH_BOXED ack")
            marker(text, re.escape("REBUILD_PARTY_MON " + key), f"{inst} rebuild party_mon")
            marker(text, re.escape("SYNC_RETRIEVE_DONE " + key), f"{inst} rebuild withdraw")
            marker(text, r"REBUILT party=2 box_count=0", f"{inst} rebuilt party")
            marker(text, re.escape("SAVE_WITNESS whiteout_new_" + inst), f"{inst} save witness")
            if re.search(r"GAME_OVER RX game_over", text):
                raise RuntimeError(f"{inst} was told the run is over; a boxed pair was there "
                                   f"to rebuild")

        starts = len(re.findall(r"^RX rebuild_start\b", a_text, re.M))
        dones = len(re.findall(r"^RX rebuild_done\b", a_text, re.M))
        if starts != 1 or dones != 1:
            raise RuntimeError(f"A was told rebuild_start x{starts} and rebuild_done x{dones}, "
                               f"expected 1 each")
        if a_text.find("RX rebuild_start") > a_text.find("RX rebuild_done"):
            raise RuntimeError("A's rebuild_done arrived before its rebuild_start")
        if re.search(r"^RX rebuild_(?:start|done)\b", b_text, re.M):
            raise RuntimeError("B received a rebuild command; rebuild_start/rebuild_done "
                               "belong to the whited-out half alone")

        events = self._reconnect_events()  # newest-first: server.py:1508 appendleft
        whiteouts = [row for row in events if row.get("type") == "whiteout"]
        if len(whiteouts) != 1 or whiteouts[0].get("player") != "a":
            raise RuntimeError(f"events.json carries {len(whiteouts)} whiteout row(s) "
                               f"{[(row.get('player'), row.get('text')) for row in whiteouts]}, "
                               f"expected exactly one from a")
        document = self._reconnect_document()  # the whole links.json, for run_over
        if document.get("run_over"):
            raise RuntimeError("links.json says the run is over; the whiteout had a boxed pair "
                               "to rebuild")
        live = [entry for entry in (document.get("links") or [])
                if entry.get("area_id") == "route_1"]
        if (len(live) != 1 or live[0].get("status") != "alive"
                or live[0].get("a", {}).get("key") != key_a
                or live[0].get("b", {}).get("key") != key_b):
            raise RuntimeError(f"the route_1 pair did not survive the whiteout: {live}")
        self._pydec_note(f"S-4/W-3 one whiteout from a, run_over false, route_1 pair still "
                         f"ALIVE {key_a} <-> {key_b}")

        for inst, key in (("a", key_a), ("b", key_b)):
            sram, party, current_box, codec = self._saved_gen1_party(inst)
            if not re.fullmatch(r"[0-9A-F]{4}:[0-9A-F]{4}:[0-9A-F]{2}", key):
                raise RuntimeError(f"{inst}'s linked key {key!r} is not in DDDD:OOOO:SS form")
            keys = [codec.key(mon) for mon in party]
            if keys != [self._boot_keys[inst], key]:
                raise RuntimeError(f"{inst}'s saved party is {keys}, expected the starter plus "
                                   f"the rebuilt {key}")
            if current_box:
                raise RuntimeError(f"{inst}'s saved current box still holds "
                                   f"{[codec.key(mon) for mon in current_box]}; the rebuild "
                                   f"withdrew it and box_count must be 0")
            self._pydec_note(f"{inst} saved party {len(party)} mon(s) = starter + rebuilt {key}, "
                             f"active box empty, decode valid")

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

    def assert_trade_decline_saved(self, results):
        """T-3/T-4's NO path: the partner declined, so no blob was staged and no party moved.

        The server exposes no pending-trade field on /api/status (recorded finding), so the
        decline is evidenced by what is ABSENT on the wire — no RX apply_trade, no TRADE_DONE,
        no PARTNER_ACCEPTED — by the durable route_1 pair keeping both pre-trade keys, and by
        both saved parties still holding [starter, linked] with the linked half on the side
        that caught it.
        """
        for process in self.emus:
            process.wait(timeout=30)  # client.exit flushes CartRAM to its per-instance SaveRAM
        for inst, text in results.items():
            marker(text, r"DECLINE_OVERWORLD", f"{inst} decline return")
            marker(text, r"SAVE_WITNESS trade_decline_new", f"{inst} save witness")
            for absent in ("RX apply_trade", "TRADE_DONE ", "PARTNER_ACCEPTED"):
                if absent in text:
                    raise RuntimeError(f"{inst}'s declined trade receipt carries {absent!r}")
        marker(results["b"], r"TRADE_DECLINED", "B decline answer")
        self._pydec_note("both receipts: DECLINE_OVERWORLD + SAVE_WITNESS trade_decline_new; "
                         "absent: RX apply_trade / TRADE_DONE / PARTNER_ACCEPTED")

        before_a, before_b = self._trade_before
        matches = [entry for entry in self._links_json()
                   if entry.get("area_id") == "route_1" and entry.get("status") == "alive"]
        if len(matches) != 1:
            raise RuntimeError(f"expected one durable alive route_1 link, got {matches}")
        link = matches[0]
        if link["a"]["key"] != before_a or link["b"]["key"] != before_b:
            raise RuntimeError(f"the declined trade moved the durable pair: {link['a']['key']} / "
                               f"{link['b']['key']} != {before_a} / {before_b}")
        self._pydec_note(f"durable route_1 pair unchanged: a={before_a} b={before_b}")

        for inst in ("a", "b"):
            _sram, party, _box, codec = self._patched_saved_state(inst)
            keys = [codec.key(mon) for mon in party]
            want = [self._boot_keys[inst], self._link_keys[inst]]
            if keys != want:
                raise RuntimeError(f"{inst}'s saved party {keys} is not the pre-trade pair "
                                   f"{want}: the declined trade staged a blob")
            own = before_a if inst == "a" else before_b
            self._pydec_note(f"{inst} saved party {keys}; linked half {own} on {inst}, no swap")

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
        self._live_complete["admit_randomized_new"] = True

    def assert_admit_randomized_saved(self, results):
        """F-4's saved half, with explicit provenance for both cartridges.

        A runs the STAGED randomized Red, whose SaveRAM carries the filename-derived name
        BizHawk resolves for a hash it does not know — so the default read would qualify the
        untouched clean-name seed against the clean ROM and prove nothing. B's readback shows
        the rejected cartridge's save was not touched by the server: party and current box
        unchanged from the seed it booted with, its rejection the only durable record, and none
        of its keys anywhere in links.json.
        """
        if not self._live_complete.get("admit_randomized_new"):
            raise RuntimeError("admit_randomized_new's live verdict did not complete")
        from pathlib import Path

        for process in self.emus:
            process.wait(timeout=30)  # client.exit flushes CartRAM

        a_rom = self._admit_roms["a"]
        a_save = self._admit_extra_saves["a"]
        a_path = Path(self._saveram_dir("a")) / a_save
        launched = self._launch_times.get("a")
        if not launched or a_path.stat().st_mtime < launched:
            raise RuntimeError(f"A's randomized SaveRAM was not written after its launch: {a_path}")
        a_sram, a_party, _a_box, codec = self._saved_gen1_party("a", rom=a_rom, save_name=a_save)
        if not a_party:
            raise RuntimeError("A's admitted save holds no party")
        self._pydec_note(f"phase initial: {os.path.relpath(a_path, REPO)} written after launch, "
                         f"qualifies against {a_rom}, party {[codec.key(m) for m in a_party]}")

        b_sram, b_party, b_box, _codec = self._saved_gen1_party("b", rom=self._admit_roms["b"])
        seed = Path(self._fixture_save_path("b")).read_bytes()
        party_start = codec.SRAM_LAYOUT["sPartyData"]
        box_start = codec.SRAM_LAYOUT["sCurBoxData"]
        seed_party = codec.decode_party(seed[party_start:party_start + codec.PARTY_LAYOUT["size"]])
        seed_box = codec.decode_box(seed[box_start:box_start + codec.BOX_SIZE])
        for what, got, want in (("party", b_party, seed_party), ("current box", b_box, seed_box)):
            if [codec.key(mon) for mon in got] != [codec.key(mon) for mon in want]:
                raise RuntimeError(
                    f"rejected B's saved {what} changed vs the seed it booted with: "
                    f"{[codec.key(m) for m in got]} != {[codec.key(m) for m in want]}")

        hellos = [row for row in self._reconnect_events()
                  if row.get("type") == "hello" and row.get("player") == "b"]
        if len(hellos) != 1 or not hellos[0].get("text", "").startswith("REJECTED — "):
            raise RuntimeError(f"B's rejection is not the durable record: {hellos}")
        document = Path(self.data_dir, "links.json").read_text(encoding="utf-8")
        leaked = sorted(key for key in {codec.key(mon) for mon in b_party + b_box}
                        if key in document)
        if leaked:
            raise RuntimeError(f"links.json carries rejected B's keys: {leaked}")
        self._pydec_note("B's saved party/current box identical to the seed; one durable "
                         "REJECTED hello; no B key in links.json")

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
        if self.scenario == "ball_gate_new":
            self.assert_ball_gate_new()
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
            elif self.scenario in ("link_new", "linked_faint_bench_new", "linked_faint_active_new",
                                   "explode_new", "pc_ops_new"):
                self.go()
                self.assert_link_new()
            elif self.scenario == "whiteout_new":
                # The extra gate is this scenario's own: both halves must be BOXED as far as
                # the server is concerned before either may leave the PC, because the blackout
                # that follows rebuilds only from pairs whose halves are absent from
                # `party_keys` (_alive_pc_mons, server/state.py:2336-2363).
                self.go()
                self.assert_link_new()
                self.assert_whiteout_both_boxed()
            elif self.scenario in ("trade_new", "trade_decline_new"):
                self.go()
                self.assert_link_new()
                before = [entry for entry in self._links_json()
                          if entry.get("area_id") == "route_1" and entry.get("status") == "alive"]
                if len(before) != 1:
                    raise RuntimeError(f"{self.scenario} has no durable post-link_new pair")
                self._trade_before = (before[0]["a"]["key"], before[0]["b"]["key"])
            elif self.scenario == "soft_reset_new":
                # The reset's evidence is that NOTHING changed, so the baseline is taken before
                # either client acts: the end state is compared against it, which is what stops
                # a duplicated or rewritten log from passing as "the same save reconnected".
                events = self._reconnect_events()
                self._reset_baseline = {
                    "status": self._status() or {},
                    "links": self._links_json(),
                    "links_bytes": self._links_bytes(),
                    "events": events,
                    "a_hellos": sum(row.get("type") == "hello" and row.get("player") == "a"
                                    for row in events),
                }
                self.go()
            elif self.scenario in ("deadzone_new", "changebox_new"):
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

    def _run_oracle(self, results):
        """The scenario's post-result oracle, from the SCENARIOS registry.

        A gen1_new scenario with no `oracle` entry FAILS: the saved-state readback is the
        independent half of every Gen 1 verdict, and a scenario that silently skipped it would
        print PYDEC: PASS on the client's own word. Gen 2/Gen 3 entries carry no `oracle` field
        and keep the legacy path, where a client RESULT is the whole verdict.
        """
        method = self.cfg.get("oracle")
        if not method:
            if getattr(self, "game", "") == "gen1_new":
                raise RuntimeError(f"{self.scenario} declares no post-result oracle in SCENARIOS; "
                                   f"a Gen 1 verdict needs a saved-state readback")
            return
        getattr(self, method)(results, **self.cfg.get("oracle_kwargs", {}))

    def _live_ok(self) -> bool:
        """True when every live leg this scenario needs ran to completion."""
        if self.scenario not in LIVE_LEG_SCENARIOS:
            return True
        return bool(self._live_complete.get(self.scenario))

    def run(self):
        passed = False
        if getattr(self, "_pydec_path", None):
            os.makedirs(os.path.dirname(self._pydec_path), exist_ok=True)
            with open(self._pydec_path, "w", encoding="utf-8") as handle:
                handle.write(f"attempt {self.attempt} of {1 if self.cfg.get('cold_boot') else 2}\n")
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
            if pa and pb:
                self._run_oracle({"a": ra, "b": rb})
            if pa and pb and getattr(self, "game", "") == "gen1_new":
                # Harness finding, not a scenario verdict: the harness wrote the expected count
                # into the stub, so the driver's echo is checkable without the game. Checked
                # only on a double PASS so a real failure keeps its own error, not this one.
                expected_jitter = self.expected_idle_jitter()
                jitter_findings = [f"{inst}: {problem}" for inst, text in (("a", ra), ("b", rb))
                                   for problem in jitter_problems(text, expected_jitter)]
                if jitter_findings:
                    raise RuntimeError("idle-jitter contract violated — "
                                       + "; ".join(jitter_findings))
            passed = pa and pb and self._live_ok()
            if getattr(self, "_pydec_path", None):
                reason = ("asserted scenario facts" if passed else
                          "live leg did not complete" if pa and pb and not self._live_ok() else
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
    limit = 2 if args.game == "gen1_new" and name != "ball_gate_new" else 1
    for attempt in range(1, limit + 1):
        print(f"[duo] {name}: attempt {attempt} of {limit}")
        print(f"[duo] JITTER requested={jitter_for_attempt(args.idle_jitter, attempt)} "
              f"attempt={attempt}")
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
        if ok or attempt >= limit or not retryable_gen1_rng(args.game, receipts, attempt):
            return ok, attempt
        print(f"[duo] {name}: the cartridge's only ball missed; restarting attempt 2 of 2 "
              "with a fresh server, run directory and SaveRAM seeds")
    return False, limit


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
    ap.add_argument("--idle-jitter", type=int, default=0,
                    help="extra idle frames before the first hunt; each RNG retry adds 37 per "
                         "attempt")
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
