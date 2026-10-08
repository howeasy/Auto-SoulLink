#!/usr/bin/env python3
"""Card C8: two-instance Polished Crystal SMOKE (hello + party census + 20-box census + one reconnect, ZERO writes).

    python tools/polished_live/duo.py          # ends `RESULT: PASS polished-duo-smoke` or `RESULT: FAIL ...`
    python tools/polished_live/duo.py --fixture-a A.SaveRAM --fixture-b B.SaveRAM --distinct-identities

Two EmuHawk (players a and b) boot the integrated overlay (patch/dist/SLink-Polished.ups on the pinned release,
sha1 97628616... was integrated at that time; the executable pin is INTEGRATED_SHA1 below) under private dirs F:/slink-work/lanes/pol-duo/run/{a,b}/ (own ROM copy, SaveRAM copy, config,
result, log) and talk to ONE real SLink server whose rom_contract.json pins BOTH players to the overlay sha1.
Evidence is read from the SERVER (the wire transcript `--wire-log`, /api/status, /api/debug/raw_state, slink.log);
the Lua driver (duo.lua) only supplies the client's own hello line and a zero-write tap. Then b's own EmuHawk PID is
killed and relaunched on the same private SaveRAM: a must stay connected, b must be re-admitted with an identical census.

DISCLOSURE: by default both sides boot copies of ONE saved identity (the SYNTH warp fixture), so this proves hello +
census only. With --distinct-identities each side boots ITS OWN fixture (--fixture-a / --fixture-b, env POL_FIXTURE_A /
POL_FIXTURE_B, falling back to POL_FIXTURE), the run refuses to start unless the two saves are two different trainers
(different bytes, player ID, name and disjoint party mon keys, read from the SaveRAM bytes), and the evaluator requires
each side's server-reported party keys / trainer / OT id to equal what ITS fixture's bytes decode to, no identity_error,
and both identities unchanged across b's reconnect. The second save is a SYNTH identity derivative (O-33, derive_save.py),
not independently played. Identity is read from the wire hello (ot_id, trainer_name, party) and /api/status
(players.<p>.trainer_name, .party_keys, .identity_error).
Only PIDs this script starts are ever killed (taskkill /T /F /PID); never an image-name kill.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LANE = Path(os.environ.get("POL_DUO_LANE", "F:/slink-work/lanes/pol-duo"))
RELEASE = Path("F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.gbc")
UPS = REPO / "patch/dist/SLink-Polished.ups"
DEFAULT_FIXTURE = "F:/slink-work/lanes/g2int-live/pol/fixture/polished_overlay_warp.SaveRAM"
HERE = Path(__file__).resolve().parent
INTEGRATED_SHA1 = "688945795e2656019247f5aaceb7b1d8791e900a"
ROM_NAME = "pol_overlay.gbc"            # BizHawk names the save from the file stem, '_' -> ' '
SAVE_NAME = "pol overlay.SaveRAM"
ADAPTER, KIND = "gen2_polished", "overlay"
# every command that can write a box/party/trade/faint (docs: server/state.py + server.py cmd names)
FORBIDDEN_CMDS = frozenset({
    "box_mon", "party_mon", "force_faint", "force_explode", "memorialize", "replace_rival_team", "apply_trade",
    "apply_prepare", "trade_final", "trade_mask", "withdraw_trade", "rebuild_start", "rebuild_done", "key_change_ack",
    "choose_mon", "game_over"})
ISOLATED = ("rom", "saveram", "config")  # per-side paths that must differ between the two sides


# ── pure parts (unit-tested: tests/unit/test_polished_duo_driver.py) ───────────────────────────────
def contract_for(sha1: str) -> dict:
    """rom_contract.json (server/adapters/gen2_polished.py rom_contract_by_sha1): BOTH players pinned to the overlay."""
    return {"upr_version": "none (overlay, not randomized)", "categories": [],
            "players": {"a": {"rom_sha1": sha1}, "b": {"rom_sha1": sha1}}}


def side_paths(run: Path, role: str, generation: int = 1) -> dict:
    """One side's private files. rom/saveram/config are per SIDE; `run` (result, sent log, stop file) per launch."""
    base = Path(run) / role
    return {"rom": (base / "rom" / ROM_NAME).as_posix(), "saveram": (base / "sram" / SAVE_NAME).as_posix(),
            "sram_dir": (base / "sram").as_posix(), "config": (base / "config.ini").as_posix(),
            "run": (base / f"g{generation}").as_posix(), "result": (base / f"g{generation}" / "result.txt").as_posix()}


def side_env(paths: dict, role: str, host: str, port: int) -> dict:
    """The environment duo.lua / pol_lib.lua read (pol_lib: SLINK_ROOT POL_OUT POL_RUN POL_SYMS)."""
    return {"SLINK_ROOT": str(REPO).replace("\\", "/"), "POL_OUT": paths["result"], "POL_RUN": paths["run"],
            "POL_SYMS": paths["run"] + "/syms.json", "SLINK_HOST": host, "SLINK_PORT": str(port),
            "SLINK_PLAYER": role, "DUO_ROLE": role}


# ── per-side fixtures + identity (pure; the identity layout is derive_save.py's, never duplicated) ──────
class FixtureError(ValueError):
    """A fixture is not a SaveRAM this driver can read an identity from."""


def _derive_save():
    mod = sys.modules.get("polished_derive_save")
    if mod is None:
        spec = importlib.util.spec_from_file_location("polished_derive_save", HERE / "derive_save.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["polished_derive_save"] = mod
        spec.loader.exec_module(mod)
    return mod


def resolve_fixtures(fixture_a=None, fixture_b=None, env=None) -> tuple[Path, Path]:
    """CLI flag > POL_FIXTURE_A / POL_FIXTURE_B > POL_FIXTURE (the default for BOTH sides) > the default fixture."""
    env = os.environ if env is None else env
    common = env.get("POL_FIXTURE") or DEFAULT_FIXTURE
    return (Path(fixture_a or env.get("POL_FIXTURE_A") or common), Path(fixture_b or env.get("POL_FIXTURE_B") or common))


def fixture_identity(data: bytes) -> dict:
    """The trainer a SaveRAM image belongs to, decoded from its bytes with derive_save's layout + the repo codec:
    sha256 (and its recorded 8-char prefix), player id, player name, and the party mon keys in slot order. Main and
    backup copy must agree; a wrong-size/marker/checksum image raises FixtureError (never guesses)."""
    ds = _derive_save()
    problems = ds._layout_problems(data) + (ds._checksum_problems(data) if len(data) == ds.SAVE_SIZE else [])
    if problems:
        raise FixtureError("; ".join(problems))
    per_copy = {}
    for c in ds.ALL_COPIES:
        ident = ds._identity(data, c)
        keys = [ds.pc.key(ds._mon(data, c, s)) for s in range(ds.party_count(data, c))]
        per_copy[c.name] = (ident["id"], ident["name"], keys)
    if per_copy["main"] != per_copy["backup"]:
        raise FixtureError(f"main and backup copies disagree on identity/party: {per_copy}")
    player_id, name, keys = per_copy["main"]
    sha = hashlib.sha256(bytes(data)).hexdigest()
    return {"sha256": sha, "prefix": sha[:8], "player_id": player_id, "name": name, "keys": keys}


def distinct_refusals(a: dict, b: dict) -> list[str]:
    """Why --distinct-identities must refuse to start (empty = two different trainers). a/b = fixture_identity()."""
    out = []
    if a["sha256"] == b["sha256"]:
        out.append("fixtures_byte_identical")
    if a["player_id"] == b["player_id"]:
        out.append("player_id_shared")
    if a["name"] == b["name"]:
        out.append("player_name_shared")
    if set(a["keys"]) & set(b["keys"]):
        out.append("party_keys_overlap")
    return out


def stage_side(paths: dict, rom: bytes, fixture: Path) -> str:
    """Give ONE side its own ROM copy and its own SaveRAM copy of ITS fixture; returns the copy's sha256 (must equal the
    fixture's: the side boots exactly the bytes whose identity the evaluator will expect)."""
    for k in ("rom", "saveram"):
        Path(paths[k]).parent.mkdir(parents=True, exist_ok=True)
    Path(paths["rom"]).write_bytes(rom)
    shutil.copyfile(fixture, paths["saveram"])
    return hashlib.sha256(Path(paths["saveram"]).read_bytes()).hexdigest()


def parse_wire(records: list) -> dict:
    """One player's wire_<p>.jsonl: its hellos (with connection id), connect/disconnect counts, server->client commands."""
    out = {"hellos": [], "connects": 0, "disconnects": 0, "commands": {}}
    for rec in records:
        msg = rec.get("msg") if isinstance(rec, dict) else None
        if not isinstance(msg, dict):
            continue
        if rec.get("dir") == "meta":
            key = {"_connect": "connects", "_disconnect": "disconnects"}.get(msg.get("event"))
            if key:
                out[key] += 1
        elif rec.get("dir") == "c2s" and msg.get("event") == "hello":
            out["hellos"].append({"conn": rec.get("conn"), "msg": msg})
        elif rec.get("dir") == "s2c":
            for cmd in msg.get("commands") or []:
                name = cmd.get("cmd") if isinstance(cmd, dict) else None
                out["commands"][str(name)] = out["commands"].get(str(name), 0) + 1
    return out


def parse_log(text: str) -> dict:
    """slink.log: per-player admission verdicts (on change) and adapter routes in hello order, and the TCP client source ports in
    accept order (the wire tap numbers connections in the same order, so conn N = ports[N-1])."""
    out = {"admission": {"a": [], "b": []}, "routes": {"a": [], "b": []}, "ports": []}
    for line in text.splitlines():
        if m := re.search(r"\[(a|b)\] admission: (\w+)", line):
            out["admission"][m[1]].append(m[2])
        elif m := re.search(r"\[(a|b)\] route \S+ -> (\S+)", line):
            out["routes"][m[1]].append(m[2])
        elif m := re.search(r"Client connected: \('[\d.]+', (\d+)\)", line):
            out["ports"].append(int(m[1]))
    return out


def hello_view(rec: dict | None, k: int, role: str, log: dict, status_player: dict) -> dict:
    """What the SERVER saw for this player's k-th hello (rec = parse_wire hello), joined with its own log verdicts."""
    if not rec:
        return {"seen": False}
    msg, routes = rec["msg"], log["routes"][role]
    boxes = msg.get("pc_boxes")
    # /api/status admission = the verdict of the NEWEST hello (re-decided on every hello; slink.log only logs a change,
    # so a clean reconnect leaves no line there). A live identity_error is a refusal too.
    verdict = "identity_error" if status_player.get("identity_error") else status_player.get("admission", "none")
    return {"seen": True, "conn": rec.get("conn"), "admission": verdict,
            "adapter": (routes[min(k, len(routes) - 1)] if routes else ""),
            "artifact_kind": msg.get("artifact_kind"), "rom_type": msg.get("rom_type"), "rom_sha1": msg.get("rom_sha1"),
            "party_keys": [e.get("key", "") for e in msg.get("party") or []], "party_count": len(msg.get("party") or []),
            "pc_boxes_generation": msg.get("pc_boxes_generation"),
            "pc_boxes": None if boxes is None else sorted(f"{e.get('box')}:{e.get('key')}" for e in boxes),
            "server_party_keys": list(status_player.get("party_keys") or []),
            "server_pc_boxes_n": len(status_player.get("pc_boxes") or []),
            "ot_id": msg.get("ot_id"), "trainer_name": msg.get("trainer_name"),
            "server_trainer_name": status_player.get("trainer_name"),
            "identity_error": status_player.get("identity_error") or ""}


def _hello_reasons(tag: str, h: dict | None, staged: str) -> list[str]:
    if not h or not h.get("seen"):
        return [f"{tag}:hello_missing"]
    out = []
    if h.get("admission") != "admitted":
        out.append(f"{tag}:hello_rejected")
    if h.get("adapter") != ADAPTER:
        out.append(f"{tag}:adapter_mismatch")
    if h.get("artifact_kind") != KIND:
        out.append(f"{tag}:artifact_kind_mismatch")
    if str(h.get("rom_sha1") or "").lower() != staged.lower():
        out.append(f"{tag}:rom_sha1_mismatch")
    keys = h.get("party_keys") or []
    if not keys:
        out.append(f"{tag}:party_empty")
    elif (h.get("party_count") != len(keys) or len(set(keys)) != len(keys) or "" in keys
          or sorted(keys) != sorted(h.get("server_party_keys") or [])):
        out.append(f"{tag}:party_incomplete")
    gen = h.get("pc_boxes_generation")
    if type(gen) is not int or gen < 0 or h.get("pc_boxes") is None:
        out.append(f"{tag}:box_census_incomplete")
    elif h.get("server_pc_boxes_n") != len(h["pc_boxes"]):
        out.append(f"{tag}:box_census_refused")
    return out


def evaluate(sides: dict, staged_sha1: str) -> tuple[bool, list[str]]:
    """sides = {"a": side, "b": side}; each side: player, paths{rom,saveram,config}, client_port, hello, reconnect (hello or
    None), continuous (never disconnected before the stop), client_writes, commands{name: n} (server->client, all
    connections), exit_marker. Returns (ok, reasons); every defect has its own reason code, fail closed."""
    reasons: list[str] = []
    if sorted(sides) != ["a", "b"]:
        return False, ["sides_missing"]
    reconnecting = [r for r in sides if sides[r].get("reconnect") is not None]
    if not reconnecting:
        reasons.append("reconnect_missing")
    for role, s in sorted(sides.items()):
        reasons += _hello_reasons(role, s.get("hello"), staged_sha1)
        if role in reconnecting:
            reasons += _hello_reasons(f"{role}/reconnect", s["reconnect"], staged_sha1)
            h1, h2 = s.get("hello") or {}, s["reconnect"]
            if h1.get("seen") and h2.get("seen") and (
                    h1.get("party_keys") != h2.get("party_keys") or h1.get("pc_boxes") != h2.get("pc_boxes")):
                reasons.append(f"{role}:census_changed_after_reconnect")
        elif not s.get("continuous"):
            reasons.append(f"{role}:disconnected_unexpectedly")
        if s.get("client_writes") != 0:
            reasons.append(f"{role}:write_observed")
        bad = sorted(set(s.get("commands") or {}) & FORBIDDEN_CMDS)
        if bad:
            reasons.append(f"{role}:command_observed:{','.join(bad)}")
        if not s.get("exit_marker"):
            reasons.append(f"{role}:exit_marker_missing")
    a, b = sides["a"], sides["b"]
    for field in ISOLATED:
        if a["paths"].get(field) == b["paths"].get(field):
            reasons.append(f"isolation:{field}_shared")
    if a.get("client_port") is None or a.get("client_port") == b.get("client_port"):
        reasons.append("isolation:client_port_shared_or_unknown")
    return not reasons, reasons


def _identity_reasons(tag: str, h: dict, own: dict, other: dict) -> list[str]:
    """One hello's identity against the fixture ITS side booted (own) and the other side's (other)."""
    out = []
    if h.get("identity_error"):
        out.append(f"{tag}:identity_error_present")
    keys = sorted(h.get("party_keys") or [])
    if keys and keys == sorted(other["keys"]) and keys != sorted(own["keys"]):
        out.append(f"{tag}:booted_other_fixture")
    else:
        if keys != sorted(own["keys"]):
            out.append(f"{tag}:party_keys_not_from_fixture")
        if h.get("ot_id") != own["player_id"]:
            out.append(f"{tag}:ot_id_not_from_fixture")
        if h.get("trainer_name") != own["name"]:
            out.append(f"{tag}:trainer_name_not_from_fixture")
    if h.get("server_trainer_name") != h.get("trainer_name"):
        out.append(f"{tag}:server_trainer_name_differs")
    return out


def evaluate_identities(sides: dict, expected: dict) -> list[str]:
    """The distinct-identities requirements on top of `evaluate`. expected = {"a": fixture_identity, "b": ...}. A side whose
    hello is missing is left to `evaluate` (hello_missing); everything else has its own reason code, fail closed."""
    if sorted(expected) != ["a", "b"] or sorted(sides) != ["a", "b"]:
        return ["identity:expected_missing"]
    out: list[str] = []
    if set(expected["a"]["keys"]) & set(expected["b"]["keys"]) or expected["a"]["player_id"] == expected["b"]["player_id"]:
        out.append("identity:expected_fixtures_not_distinct")
    seen = {}
    for role, other in (("a", "b"), ("b", "a")):
        s = sides[role]
        h = s.get("hello")
        if not h or not h.get("seen"):
            continue
        seen[role] = h
        out += _identity_reasons(role, h, expected[role], expected[other])
        rc = s.get("reconnect")
        if rc is not None and rc.get("seen"):
            out += _identity_reasons(f"{role}/reconnect", rc, expected[role], expected[other])
            if (h.get("ot_id"), h.get("trainer_name")) != (rc.get("ot_id"), rc.get("trainer_name")):
                out.append(f"{role}:identity_changed_after_reconnect")
        elif rc is None:                      # the side that stayed up: its identity must be untouched by the peer's reconnect
            fin = s.get("final")
            if not fin:
                out.append(f"{role}:final_identity_missing")
            else:
                if fin.get("identity_error"):
                    out.append(f"{role}:final_identity_error_present")
                if sorted(fin.get("party_keys") or []) != sorted(h.get("party_keys") or []) or \
                        fin.get("trainer_name") != h.get("trainer_name"):
                    out.append(f"{role}:identity_changed_while_peer_reconnected")
    if len(seen) == 2:
        ka, kb = set(seen["a"].get("party_keys") or []), set(seen["b"].get("party_keys") or [])
        if ka and ka == kb:
            out.append("identity:party_keys_identical")
        elif ka & kb:
            out.append("identity:party_keys_overlap")
        if seen["a"].get("trainer_name") and seen["a"].get("trainer_name") == seen["b"].get("trainer_name"):
            out.append("identity:trainer_name_shared")
        if seen["a"].get("ot_id") is not None and seen["a"].get("ot_id") == seen["b"].get("ot_id"):
            out.append("identity:ot_id_shared")
    return out


def evaluate_distinct(sides: dict, staged_sha1: str, expected: dict) -> tuple[bool, list[str]]:
    """`evaluate` (hello/census/reconnect/zero-writes/isolation) plus the two-identity requirements."""
    _, reasons = evaluate(sides, staged_sha1)
    reasons = reasons + evaluate_identities(sides, expected)
    return not reasons, reasons


# ── live runner ────────────────────────────────────────────────────────────────────────────────────
def kill_pid(proc: subprocess.Popen, label: str) -> None:
    if proc.poll() is None:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            print(f"[duo] {label} pid {proc.pid} did not exit after taskkill", flush=True)
    print(f"[duo] {label} pid {proc.pid} ended rc={proc.returncode}", flush=True)


def http_json(port: int, path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return json.loads(r.read())


def read_jsonl(path: Path) -> list:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()]


def client_line(result: Path, tag: str) -> dict | None:
    if result.is_file():
        for line in result.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(tag + " "):
                return json.loads(line[len(tag) + 1:])
    return None


def exit_marker(result: Path, role: str) -> bool:
    return result.is_file() and f"RESULT: PASS duo-side-{role}" in result.read_text(encoding="utf-8", errors="replace")


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Two-instance Polished Crystal smoke (hello + census + reconnect, zero writes)")
    ap.add_argument("--fixture-a", help="SaveRAM for side a (env POL_FIXTURE_A; default POL_FIXTURE, then the warp fixture)")
    ap.add_argument("--fixture-b", help="SaveRAM for side b (env POL_FIXTURE_B; default POL_FIXTURE, then the warp fixture)")
    ap.add_argument("--distinct-identities", action="store_true",
                    help="require two genuinely distinct trainers: refuse identical fixtures, check each side against ITS fixture")
    return ap.parse_args(argv)


def plan_fixtures(args, env=None) -> tuple[dict, dict]:
    """Per-side fixture paths and their identities, decoded from the files themselves. In --distinct-identities mode this
    REFUSES (SystemExit) unless the two saves are two different trainers: nothing is staged or launched before it."""
    fixtures = dict(zip(("a", "b"), resolve_fixtures(args.fixture_a, args.fixture_b, env), strict=True))
    try:
        ident = {r: fixture_identity(fixtures[r].read_bytes()) for r in ("a", "b")}
    except (OSError, FixtureError) as exc:
        raise SystemExit(f"fixture unreadable as a Polished SaveRAM: {exc}") from exc
    if args.distinct_identities:
        refused = distinct_refusals(ident["a"], ident["b"])
        if refused:
            raise SystemExit(f"--distinct-identities refused: {refused} (a {fixtures['a']} {ident['a']['prefix']}, "
                             f"b {fixtures['b']} {ident['b']['prefix']})")
    return fixtures, ident


def main(argv=None) -> int:
    args = parse_args(argv)
    fixtures, ident = plan_fixtures(args)
    sys.path[:0] = [str(REPO / "tools"), str(REPO)]
    import harness  # sym_table, free_port (reused unchanged)
    from gen1_playthrough import BIZHAWK_CONFIG, EMUHAWK, write_run_config

    from patch.tools.make_ups import ups_apply

    deadline = time.monotonic() + float(os.environ.get("POL_DUO_DEADLINE", "1200"))
    rom = ups_apply(RELEASE.read_bytes(), UPS.read_bytes())
    sha1 = hashlib.sha1(rom).hexdigest()
    if sha1 != INTEGRATED_SHA1:
        raise SystemExit(f"staged overlay sha1 {sha1} != integrated overlay {INTEGRATED_SHA1}")
    run = LANE / "run"
    if run.exists():
        shutil.rmtree(run)
    srv_dir, wire_dir = run / "srv", run / "wire"
    srv_dir.mkdir(parents=True)
    (srv_dir / "rom_contract.json").write_text(json.dumps(contract_for(sha1)), encoding="utf-8")
    syms = json.dumps(harness.sym_table())
    base_paths = {r: side_paths(run, r) for r in ("a", "b")}
    for r, p in base_paths.items():     # own ROM copy + own SaveRAM copy of ITS fixture + own config per side
        if stage_side(p, rom, fixtures[r]) != ident[r]["sha256"]:
            raise SystemExit(f"side {r}: private SaveRAM copy differs from its fixture {fixtures[r]}")
        write_run_config(BIZHAWK_CONFIG, p["config"], saveram_dir=p["sram_dir"], purergb=True)
        if max(len(p["saveram"]), len(p["result"])) >= 200:
            raise SystemExit("lane path too long for BizHawk SaveRAM")
    print(f"[duo] staged overlay sha1 {sha1}; mode {'distinct-identities' if args.distinct_identities else 'single-fixture smoke'}; "
          f"lane {run}", flush=True)
    for r in ("a", "b"):
        print(f"[duo] fixture {r}: {fixtures[r]} sha256 {ident[r]['sha256']} (prefix {ident[r]['prefix']}) player "
              f"{ident[r]['name']!r} id {ident[r]['player_id']} expected party keys {ident[r]['keys']}", flush=True)

    port, http = harness.free_port(), harness.free_port()
    srv_log = open(run / "server.log", "w", encoding="utf-8")  # noqa: SIM115 - closed in finally
    srv = subprocess.Popen([sys.executable, "-m", "server.server", "--host", "127.0.0.1", "--port", str(port),
                            "--http-port", str(http), "--data-dir", str(srv_dir), "--verbose", "--wire-log", str(wire_dir)],
                           cwd=str(REPO), stdout=srv_log, stderr=subprocess.STDOUT)
    procs: dict[str, subprocess.Popen] = {}
    pids: dict[str, list] = {"a": [], "b": []}
    gen = {"a": 0, "b": 0}

    def launch(role: str) -> dict:
        gen[role] += 1
        p = side_paths(run, role, gen[role])
        Path(p["run"]).mkdir(parents=True, exist_ok=True)
        Path(p["run"], "syms.json").write_text(syms, encoding="utf-8")
        env = dict(os.environ, **side_env(p, role, "127.0.0.1", port))
        cmd = [EMUHAWK, f"--lua={(REPO / 'tools/polished_live/duo.lua').as_posix()}", f"--config={p['config']}", p["rom"]]
        procs[role] = subprocess.Popen(cmd, cwd=str(REPO), env=env)
        pids[role].append(procs[role].pid)
        print(f"[duo] EmuHawk {role} generation {gen[role]} pid {procs[role].pid}", flush=True)
        return p

    def wait(what: str, pred, timeout: float) -> None:
        end = min(time.monotonic() + timeout, deadline)
        while time.monotonic() < end:
            if pred():
                return
            for role, pr in procs.items():
                if pr.poll() is not None and what != "exit":
                    raise RuntimeError(f"{what}: EmuHawk {role} pid {pr.pid} exited early rc={pr.returncode}")
            time.sleep(1.5)
        raise RuntimeError(f"timeout waiting for {what}")

    def server_view() -> dict:
        wire = {r: parse_wire(read_jsonl(wire_dir / f"wire_{r}.jsonl")) for r in ("a", "b")}
        log_path = srv_dir / "slink.log"
        log = parse_log(log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else "")
        return {"status": http_json(http, "/api/status"), "raw": http_json(http, "/api/debug/raw_state"), "wire": wire, "log": log}

    sides: dict = {}
    notes: list[str] = []
    ok, reasons = False, ["driver_error"]
    try:
        wait("server http", lambda: bool(http_json(http, "/api/status")), 40)
        print(f"[duo] server pid {srv.pid} tcp {port} http {http} data {srv_dir}", flush=True)
        pa, pb = launch("a"), launch("b")
        wait("both clients hello", lambda: client_line(Path(pa["result"]), "DUO_CLIENT") and client_line(Path(pb["result"]), "DUO_CLIENT"), 600)
        view1 = server_view()
        print(f"[duo] phase 1: a {client_line(Path(pa['result']), 'DUO_CLIENT')}\n[duo] phase 1: b {client_line(Path(pb['result']), 'DUO_CLIENT')}", flush=True)
        b_before = hashlib.sha256(Path(base_paths["b"]["saveram"]).read_bytes()).hexdigest()
        kill_pid(procs["b"], "EmuHawk b (reconnect test)")
        wait("exit", lambda: server_view()["wire"]["b"]["disconnects"] >= 1, 60)
        mid = server_view()
        notes.append(f"b killed: server saw b disconnect; a disconnects so far {mid['wire']['a']['disconnects']}, "
                     f"a connected {mid['status']['players']['a']['connected']}, b connected {mid['status']['players']['b']['connected']}")
        b_after = hashlib.sha256(Path(base_paths["b"]["saveram"]).read_bytes()).hexdigest()
        pb2 = launch("b")
        wait("b reconnect hello", lambda: client_line(Path(pb2["result"]), "DUO_CLIENT"), 600)
        view2 = server_view()
        a_continuous = view2["wire"]["a"]["connects"] == 1 and view2["wire"]["a"]["disconnects"] == 0
        for p in (pa, pb2):    # stop file -> L.finish -> client.exit (the exit marker)
            Path(p["run"], "stop").write_text("stop", encoding="utf-8")
        wait("exit", lambda: all(pr.poll() is not None for pr in procs.values()), 90)
        fin = server_view()
        for role in ("a", "b"):
            if procs[role].poll() is None:
                kill_pid(procs[role], f"EmuHawk {role}")

        for role, final_p in (("a", pa), ("b", pb2)):
            w, st, log = fin["wire"][role], view2["status"]["players"][role], fin["log"]
            hellos = w["hellos"]
            h1 = hello_view(hellos[0] if hellos else None, 0, role, log, view1["status"]["players"][role])
            h2 = hello_view(hellos[1] if len(hellos) > 1 else None, 1, role, log, st) if role == "b" else None
            side_ports = [log["ports"][r["conn"] - 1] for r in hellos if r.get("conn") and r["conn"] - 1 < len(log["ports"])]
            sides[role] = {"player": role, "paths": {k: base_paths[role][k] for k in ISOLATED},
                           "client_port": side_ports[0] if side_ports else None, "client_ports": side_ports,
                           "pids": pids[role], "hello": h1, "reconnect": h2,
                           "continuous": a_continuous if role == "a" else None,
                           "client_writes": (client_line(Path(final_p["result"]), "DUO_FINAL") or {}).get("lua_writes", -1)
                           + (client_line(Path(final_p["result"]), "DUO_FINAL") or {}).get("panel_writes", 0),
                           "commands": w["commands"], "exit_marker": exit_marker(Path(final_p["result"]), role),
                           "client_hello_line": client_line(Path(final_p["result"]), "DUO_CLIENT")}
            if role == "a":      # the side that stayed up: its server-side identity AFTER b's reconnect
                fa = view2["status"]["players"]["a"]
                sides["a"]["final"] = {"trainer_name": fa.get("trainer_name"), "party_keys": list(fa.get("party_keys") or []),
                                       "identity_error": fa.get("identity_error") or ""}
        if args.distinct_identities:
            ok, reasons = evaluate_distinct(sides, sha1, ident)
        else:
            ok, reasons = evaluate(sides, sha1)
        notes.append(f"b SaveRAM sha256 before kill {b_before[:16]} after kill {b_after[:16]} (unchanged: {b_before == b_after})")
    except Exception as exc:  # noqa: BLE001 - any harness failure is a FAIL with the reason, never a silent pass
        reasons = [f"driver_error: {exc}"]
        ok = False
    finally:
        for role, pr in procs.items():
            kill_pid(pr, f"EmuHawk {role}")
        kill_pid(srv, "server")
        srv_log.close()
    print("[duo] ---- evidence ----", flush=True)
    for role, s in sorted(sides.items()):
        print(f"[duo] side {role}: EmuHawk pids {s['pids']} client ports {s['client_ports']}", flush=True)
        for tag, h in (("hello", s["hello"]), ("reconnect", s["reconnect"])):
            if h:
                print(f"[duo]   {tag}: seen={h.get('seen')} admission={h.get('admission')} adapter={h.get('adapter')} "
                      f"kind={h.get('artifact_kind')} rom_sha1={h.get('rom_sha1')}\n[duo]     party {h.get('party_count')} "
                      f"keys {h.get('party_keys')} (server party_keys {h.get('server_party_keys')})\n[duo]     box census "
                      f"generation {h.get('pc_boxes_generation')} client entries {len(h.get('pc_boxes') or [])} server "
                      f"stored {h.get('server_pc_boxes_n')}\n[duo]     identity: ot {h.get('ot_id')} "
                      f"name {h.get('trainer_name')} server status trainer_name {h.get('server_trainer_name')} identity_error {h.get('identity_error')!r}", flush=True)
        if s.get("final"):
            print(f"[duo]   status after b reconnected: {s['final']}", flush=True)
        print(f"[duo]   continuous={s['continuous']} client_writes={s['client_writes']} server_commands={s['commands']} "
              f"exit_marker={s['exit_marker']}", flush=True)
    for n in notes:
        print(f"[duo] {n}", flush=True)
    if args.distinct_identities:
        disclosure = (f"fixtures a {ident['a']['prefix']} ({ident['a']['name']}, id {ident['a']['player_id']}) and b "
                      f"{ident['b']['prefix']} ({ident['b']['name']}, id {ident['b']['player_id']}): SYNTH identity derivative "
                      f"(O-33), not independently played; two distinct identities admitted, hello + census + reconnect only, "
                      f"no trade exercised")
    else:
        disclosure = (f"both sides share ONE saved identity (fixture {ident['a']['prefix']}): hello + census smoke only, "
                      f"no trade possible")
    print(f"[duo] server data dir {srv_dir}; wire {wire_dir}; staged ROM sha1 {sha1}; {disclosure}", flush=True)
    (run / "evidence.json").write_text(json.dumps(
        {"ok": ok, "reasons": reasons, "mode": "distinct-identities" if args.distinct_identities else "single-fixture",
         "fixtures": {r: {"path": str(fixtures[r]), **ident[r]} for r in ("a", "b")}, "disclosure": disclosure,
         "sides": sides, "notes": notes}, indent=1, default=str), encoding="utf-8")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} polished-duo-smoke" + ("" if ok else f" -- {reasons}"), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
