"""ISOLATED enabled trade + cold CONTINUE, never publishes shipped ROM pins.

SYNTH: retained receptionist fixture, derived second identity, exactly one link
seeded through State hello/capture events. Receptionist onward uses native input,
real clients/server and native commit/save. Only owned process PIDs are stopped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from server.adapters import polished_codec as pc  # noqa: E402
from tools.polished_live import duo, reload_probe  # noqa: E402

LANE = Path("F:/slink-work/lanes/pol-tradeduo")
SHIPPED = "688945795e2656019247f5aaceb7b1d8791e900a"
FIXTURE = Path("F:/slink-work/lanes/pol-svclive/apply-done1/attempt-0003/sram_overlay/pol overlay.SaveRAM")
DISCLOSURE = "SYNTH: retained receptionist fixture, second identity derivative, one ALIVE link seeded via server events; trade menus/commit/trade_done native"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def probe_symbols(syms):
    from tools.polished_live import harness
    # The full ~70k-label SYM exceeds json_codec's 100k-value bound (each row is an array).
    return {name: syms[name] for name in (*harness.SYMBOLS, "NoYesBox", "SlinkTradeCommit", "SlinkTradeApplyCommit",
                                         "SlinkTradePublishDone", "SlinkTradeExit", "SlinkTradeResponderExit")}


def party(data):
    ds = duo._derive_save()
    duo.fixture_identity(data)
    rows = []
    for i in range(ds.party_count(data, ds.MAIN)):
        c = ds.MAIN
        blob = data[c.mon_at(i):c.mon_at(i)+48]+data[c.ot_at(i):c.ot_at(i)+11]+data[c.nick_at(i):c.nick_at(i)+11]
        m = pc.decode_party_blob(blob)
        rows.append({"slot": i, "key": pc.key(m), "species_id": pc.effective_species(m["species_id"], m["form"]),
                     "nickname": m["nickname"], "level": m["level"], "hp": m["hp"], "blob_hex": blob.hex()})
    return rows


def seed_server(path, saves, rom_sha=SHIPPED):
    from server.adapters.gen2_polished import _companion_abi
    from server.server import SLinkServer
    from server.state import LinkStatus
    (path/"rom_contract.json").write_text(json.dumps(duo.contract_for(rom_sha)))
    server = SLinkServer(data_dir=str(path), phone_calls=False)
    state = server.state
    events = []
    for role in ("a", "b"):
        ident, mons = duo.fixture_identity(saves[role]), party(saves[role])
        hello = {"event": "hello", "party": mons, "ot_id": ident["player_id"], "trainer_name": ident["name"], "has_pokeballs": True,
                 "rom_type": "polished_crystal", "foundation": "gen2_polished", "artifact_kind": "overlay",
                 "rom_sha1": rom_sha, "companion_abi": _companion_abi()}
        capture = dict(mons[0], event="capture", area_id="route_29")
        for event in (hello, capture):
            server._dispatch(role, event)  # admission also commits rom_type/artifact_kind needed by journal reload
            events.append({"player": role, "msg": event})
    assert len(state.links) == 1 and state.links[0].status == LinkStatus.ALIVE, "SYNTH link setup failed"
    state._save()
    return events


def judge(wire, before, cold, state):
    reasons = []
    original = {r: party(before[r]) for r in ("a", "b")}
    tokens = []
    for r, other in (("a", "b"), ("b", "a")):
        events = [row["msg"] for row in wire[r] if row.get("dir") == "c2s"]
        done = [m for m in events if m.get("event") == "trade_done"]
        hellos = [m for m in events if m.get("event") == "hello"]
        applies = [c for row in wire[r] if row.get("dir") == "s2c" for c in row.get("msg", {}).get("commands", [])
                   if c.get("cmd") == "apply_trade"]
        if not hellos or [m["key"] for m in hellos[0].get("party", [])] != [m["key"] for m in original[r]]:
            reasons.append(r+": setup keys not witnessed by client hello")
        if len(applies) != 1 or not applies[0].get("token") or len(done) != 1 or done[0].get("token") != applies[0]["token"]:
            reasons.append(r+": APPLY/token not bound")
        else:
            tokens.append(applies[0]["token"])
        if len(done) != 1 or done[0].get("uncertain") or done[0].get("new_key") != original[other][0]["key"]:
            reasons.append(r+": trade_done not one exact received key")
        if any(m.get("event") in ("faint", "whiteout") for m in events):
            reasons.append(r+": false death")
        if not cold.get(r):
            reasons.append(r+": cold CONTINUE missing")
            continue
        expected = [m["key"] for m in original[r][1:]]+[original[other][0]["key"]]
        if [m["key"] for m in cold[r].get("party", [])] != expected:
            reasons.append(r+": cold party differs")
        if cold[r].get("trainer_name") != duo.fixture_identity(before[r])["name"]:
            reasons.append(r+": cold identity differs")
    if len(tokens) != 2 or tokens[0] != tokens[1]:
        reasons.append("two sides did not complete the same transaction")
    links = state.get("links", [])
    if len(links) != 1 or links[0].get("status") != "alive":
        reasons.append("server link not ALIVE")
    else:
        for r, other in (("a", "b"), ("b", "a")):
            if links[0].get(r, {}).get("key") != original[other][0]["key"]:
                reasons.append("server "+r+" not re-keyed")
    if state.get("pending_trade") is not None:
        reasons.append("server trade still pending")
    return ("FAIL" if reasons else "PASS"), reasons


def stage_root(enabled):
    root = LANE/"client"
    shutil.copytree(ROOT/"lua", root/"lua", dirs_exist_ok=True)
    shutil.copytree(ROOT/"data/games/polished_crystal", root/"data/games/polished_crystal", dirs_exist_ok=True)
    shutil.copytree(ROOT/"data/polished", root/"data/polished", dirs_exist_ok=True)
    provenance = enabled/"data/polished/overlay_provenance.json"
    shutil.copyfile(provenance, root/"data/polished/overlay_provenance.json")
    prov = json.loads(provenance.read_text())
    path = root/"data/games/polished_crystal/profile.json"
    profile = json.loads(path.read_text())
    profile["titles"]["polished"]["overlay"]["rom_sha1"] = prov["output"]["sha1"]
    profile["source"]["overlay_sha1"] = prov["output"]["sha1"]
    profile["source"]["overlay_provenance_sha256"] = sha(provenance.read_bytes())
    # The isolated profile follows the enabled build's relocated service labels.
    from tools.build_gen2_companion import _symbols
    syms = _symbols(enabled/"data/polished/polished_slink.sym")
    def relocate(obj):
        if isinstance(obj, dict):
            if obj.get("symbol") in syms and "addr" in obj and "bank" in obj:
                obj["bank"], obj["addr"] = syms[obj["symbol"]]
            for value in obj.values():
                relocate(value)
        elif isinstance(obj, list):
            for value in obj:
                relocate(value)
    relocate(profile["titles"]["polished"]["overlay"]["trade"])
    path.write_text(json.dumps(profile, indent=2)+"\n")
    return root, syms, prov["output"]["sha1"]


def run(args):
    from tools.gen1_playthrough import BIZHAWK_CONFIG, EMUHAWK, write_run_config
    from tools.polished_live import harness
    disabled = (LANE/"disabled/cache/polished/companion-overlay/polishedcrystal-3.2.3.gbc").read_bytes()
    assert hashlib.sha1(disabled).hexdigest() == SHIPPED, "disabled build failed reproduction"
    enabled = LANE/"enabled"
    rom = (enabled/"cache/polished/companion-overlay/polishedcrystal-3.2.3.gbc").read_bytes()
    root, syms, rom_sha = stage_root(enabled)
    gate = 0x7E*0x4000+0x573B-0x4000
    assert disabled[gate] == 0 and rom[gate] == 1
    diff = [i for i, (a, b) in enumerate(zip(disabled, rom, strict=True)) if a != b]
    run_dir = LANE/args.name
    run_dir.mkdir(exist_ok=False)
    a = args.fixture.read_bytes()
    b, derivation = duo._derive_save().derive_identity(a, name="TradeB", player_id=53699)
    saves = {"a": a, "b": b}
    for r in saves:
        (run_dir/f"before-{r}.SaveRAM").write_bytes(saves[r])
    srvdir = run_dir/"server"
    srvdir.mkdir()
    events = seed_server(srvdir, saves, rom_sha)
    (srvdir/"rom_contract.json").write_text(json.dumps(duo.contract_for(rom_sha)))
    manifest = {"disclosure": DISCLOSURE, "derivation": derivation, "seed_events": events,
                "test_rom_sha1": rom_sha, "disabled_sha1": SHIPPED, "changed_offsets": diff,
                "gate": {"bank": 126, "addr": 0x573B, "old": 0, "new": 1}, "source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()}
    (run_dir/"manifest.json").write_text(json.dumps(manifest, indent=2))
    port, http = harness.free_port(), harness.free_port()
    processes = {}
    paths = {}
    def launch(role, cold=False):
        paths[role] = p = duo.side_paths(run_dir, role, 2 if cold else 1)
        Path(p["run"]).mkdir(parents=True)
        if not cold:
            duo.stage_side(p, rom, run_dir/f"before-{role}.SaveRAM")
        write_run_config(BIZHAWK_CONFIG, p["config"], saveram_dir=p["sram_dir"], purergb=True)
        Path(p["run"], "syms.json").write_text(json.dumps(probe_symbols(syms)))
        env = dict(os.environ, **duo.side_env(p, role, "127.0.0.1", port))
        env.update(SLINK_ROOT=root.as_posix(), POL_DRIVER_ROOT=ROOT.as_posix(), POL_COLD="1" if cold else "0")
        proc = subprocess.Popen([EMUHAWK, "--lua="+(ROOT/"tools/polished_live/trade_duo_live.lua").as_posix(),
                                 "--config="+p["config"], p["rom"]], cwd=ROOT, env=env)
        processes[role] = proc
        Path(p["run"], "pid.txt").write_text(str(proc.pid))
    with (run_dir/"server.log").open("w") as log:
        srv = subprocess.Popen([sys.executable, "-m", "server.server", "--host", "127.0.0.1", "--port", str(port),
                                "--http-port", str(http), "--data-dir", str(srvdir), "--wire-log", str(run_dir/"wire"),
                                "--no-phone-calls", "--verbose"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+40
            while time.monotonic() < deadline:
                try:
                    duo.http_json(http, "/api/status")
                    break
                except Exception:
                    time.sleep(.2)
            launch("a")
            launch("b")
            deadline = time.monotonic()+args.timeout
            while time.monotonic() < deadline:
                duo.http_json(http, "/api/status")
                ready = all(Path(paths[r]["run"], "ready.json").exists() for r in ("a", "b"))
                if ready:
                    Path(paths["a"]["run"], "go").touch()
                    Path(paths["b"]["run"], "go").touch()
                if all(Path(paths[r]["run"], "done.json").exists() for r in ("a", "b")):
                    break
                if any(Path(paths[r]["run"], "failure.json").exists() for r in ("a", "b")):
                    break
                if any(p.poll() is not None for p in processes.values()):
                    break
                time.sleep(1)
            for r in processes:
                Path(paths[r]["run"], "stop").touch()
            time.sleep(3)
            for proc in processes.values():
                harness.kill_own(proc, "trade side")
            wire = {r: duo.read_jsonl(run_dir/f"wire/wire_{r}.jsonl") for r in ("a", "b")}
            state = json.loads((srvdir/"links.json").read_text())
            (run_dir/"state-after-trade.json").write_text(json.dumps(state, indent=2))
            traded = all(Path(paths[r]["run"], "done.json").exists() for r in ("a", "b"))
            cold = {}
            durable_failures = []
            if traded:
                for r in ("a", "b"):
                    data = Path(paths[r]["saveram"]).read_bytes()
                    proof = reload_probe.extract_save(data)
                    (run_dir/f"durable-{r}.json").write_text(json.dumps(proof, indent=2))
                    expected = [m["key"] for m in party(saves[r])[1:]]+[party(saves["b" if r == "a" else "a"])[0]["key"]]
                    for copy, snapshot in proof["copies"].items():
                        if (not proof["integrity"][copy]["valid"] or not proof["integrity"][copy]["markers_valid"]
                                or [m["key"] for m in reload_probe.decode_snapshot(snapshot)["party"]] != expected):
                            durable_failures.append(r+": durable "+copy+" differs or is corrupt")
                    launch(r, cold=True)
                deadline = time.monotonic()+120
                while time.monotonic() < deadline and not all(Path(paths[r]["run"], "ready.json").exists() for r in ("a", "b")):
                    time.sleep(1)
                for r in ("a", "b"):
                    path = Path(paths[r]["run"], "ready.json")
                    if path.exists():
                        cold[r] = json.loads(path.read_text())
            verdict, reasons = judge(wire, saves, cold, state)
            if durable_failures:
                verdict, reasons = "FAIL", reasons+durable_failures
            for role in ("a", "b"):
                for failure in (run_dir/role).glob("g*/failure.json"):
                    verdict = "FAIL"
                    reasons.append(role+": "+json.loads(failure.read_text())["reason"])
            (run_dir/"verdict.json").write_text(json.dumps({"verdict": verdict, "reasons": reasons, "cold": cold,
                                                          "disclosure": DISCLOSURE}, indent=2))
            print(run_dir, verdict, reasons)
            return 0 if verdict == "PASS" else 1
        finally:
            for proc in processes.values():
                harness.kill_own(proc, "owned trade/cold side")
            harness.kill_own(srv, "owned trade server")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fixture", type=Path, default=FIXTURE)
    p.add_argument("--name", required=True, help="new private attempt name; never overwrite a receipt")
    p.add_argument("--timeout", type=int, default=600)
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
