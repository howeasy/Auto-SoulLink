#!/usr/bin/env python3
"""Card C8: two-instance Polished Crystal SMOKE (hello + party census + 20-box census + one reconnect, ZERO writes).

    python tools/polished_live/duo.py          # ends `RESULT: PASS polished-duo-smoke` or `RESULT: FAIL ...`

Two EmuHawk (players a and b) boot the integrated overlay (patch/dist/SLink-Polished.ups on the pinned release,
sha1 97628616...) under private dirs F:/slink-work/lanes/pol-duo/run/{a,b}/ (own ROM copy, SaveRAM copy, config,
result, log) and talk to ONE real SLink server whose rom_contract.json pins BOTH players to the overlay sha1.
Evidence is read from the SERVER (the wire transcript `--wire-log`, /api/status, /api/debug/raw_state, slink.log);
the Lua driver (duo.lua) only supplies the client's own hello line and a zero-write tap. Then b's own EmuHawk PID is
killed and relaunched on the same private SaveRAM: a must stay connected, b must be re-admitted with an identical census.

DISCLOSURE: both sides boot copies of ONE saved identity (the SYNTH warp fixture), so this proves hello + census
only; a trade needs two distinct played identities, which do not exist yet.
Only PIDs this script starts are ever killed (taskkill /T /F /PID); never an image-name kill.
"""
from __future__ import annotations

import hashlib
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
FIXTURE = Path(os.environ.get("POL_FIXTURE", "F:/slink-work/lanes/g2int-live/pol/fixture/polished_overlay_warp.SaveRAM"))
FIXTURE_SHA256_PREFIX = "75c7a5dc"
INTEGRATED_SHA1 = "97628616e36b2bd0c241699aa00e5abcfe0d45db"
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
            "ot_id": msg.get("ot_id"), "trainer_name": msg.get("trainer_name")}


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


def main() -> int:
    sys.path[:0] = [str(REPO / "tools"), str(REPO)]
    import harness  # sym_table, free_port (reused unchanged)
    from gen1_playthrough import BIZHAWK_CONFIG, EMUHAWK, write_run_config

    from patch.tools.make_ups import ups_apply

    deadline = time.monotonic() + float(os.environ.get("POL_DUO_DEADLINE", "1200"))
    rom = ups_apply(RELEASE.read_bytes(), UPS.read_bytes())
    sha1 = hashlib.sha1(rom).hexdigest()
    if sha1 != INTEGRATED_SHA1:
        raise SystemExit(f"staged overlay sha1 {sha1} != integrated overlay {INTEGRATED_SHA1}")
    fixture_sha = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    if not fixture_sha.startswith(FIXTURE_SHA256_PREFIX):
        raise SystemExit(f"fixture sha256 {fixture_sha} does not start {FIXTURE_SHA256_PREFIX}: {FIXTURE}")

    run = LANE / "run"
    if run.exists():
        shutil.rmtree(run)
    srv_dir, wire_dir = run / "srv", run / "wire"
    srv_dir.mkdir(parents=True)
    (srv_dir / "rom_contract.json").write_text(json.dumps(contract_for(sha1)), encoding="utf-8")
    syms = json.dumps(harness.sym_table())
    base_paths = {r: side_paths(run, r) for r in ("a", "b")}
    for p in base_paths.values():     # own ROM copy + own SaveRAM copy + own config per side
        for k in ("rom", "saveram"):
            Path(p[k]).parent.mkdir(parents=True, exist_ok=True)
        Path(p["rom"]).write_bytes(rom)
        shutil.copyfile(FIXTURE, p["saveram"])
        write_run_config(BIZHAWK_CONFIG, p["config"], saveram_dir=p["sram_dir"], purergb=True)
        if max(len(p["saveram"]), len(p["result"])) >= 200:
            raise SystemExit("lane path too long for BizHawk SaveRAM")
    print(f"[duo] staged overlay sha1 {sha1}; fixture sha256 {fixture_sha}; lane {run}", flush=True)

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
                      f"stored {h.get('server_pc_boxes_n')} ot {h.get('ot_id')} name {h.get('trainer_name')}", flush=True)
        print(f"[duo]   continuous={s['continuous']} client_writes={s['client_writes']} server_commands={s['commands']} "
              f"exit_marker={s['exit_marker']}", flush=True)
    for n in notes:
        print(f"[duo] {n}", flush=True)
    print(f"[duo] server data dir {srv_dir}; wire {wire_dir}; staged ROM sha1 {sha1}; both sides share ONE saved identity "
          f"(fixture {fixture_sha[:8]}): hello + census smoke only, no trade possible", flush=True)
    (run / "evidence.json").write_text(json.dumps({"ok": ok, "reasons": reasons, "sides": sides, "notes": notes}, indent=1,
                                                  default=str), encoding="utf-8")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} polished-duo-smoke" + ("" if ok else f" -- {reasons}"), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
