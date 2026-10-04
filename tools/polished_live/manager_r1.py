#!/usr/bin/env python3
"""Stage R1 (live randomization run, owner-authorised 2026-10-04): the REAL Manager over HTTP.

    python tools/polished_live/manager_r1.py            # jar installed ($SLINK_UPR_JAR = the pinned forms jar)
    python tools/polished_live/manager_r1.py nojar      # the same Manager with no jar findable (status + refusal)
    python tools/polished_live/manager_r1.py oldjar     # an older trusted fork jar (no polished_offsets.ini)

Starts `python -m server.manager` on a private port with a private --data-dir under F:/slink-work/lanes/pol-rand,
drives it ONLY through its HTTP API (no internals), and records every call + response in <lane>/r1_<mode>/calls.jsonl.
The jar mode creates a gen2_polished run, provisions a randomized PAIR from the picker's Polished release with the
companion on, downloads both ROMs through /api/runs/{id}/rom/{p} and copies the run's rom_contract.json.
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
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LANE = Path(os.environ.get("POL_LANE", "F:/slink-work/lanes/pol-rand"))
JAR = Path(os.environ.get("POL_JAR", "F:/slink-work/cache/polished/jar/PokeRandoZX.jar"))
OLD_JAR = Path("E:/Google Drive/SLink/.cache/slink-upr/PokeRandoZX.jar")
RELEASE = Path("F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.gbc")
# widest sensible Polished spec: every category the handler writes (forms are always in the pool, no setting)
SPEC = {"wild": "random", "wild_restriction": "none", "wild_block_legendaries": True, "wild_min_catch_rate": 0,
        "wild_levels": 0, "starters": "random", "statics": "random", "static_levels": 0, "trainers": "random",
        "trainers_similar_strength": False, "trainers_rival_starter": True, "trainers_block_legendaries": True,
        "trainers_match_typing": False, "trades": "given_and_requested"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Api:
    def __init__(self, port: int, log: Path):
        self.base, self.log = f"http://127.0.0.1:{port}", log

    def call(self, method: str, path: str, body=None, raw=False, timeout=900):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status, payload = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, payload = e.code, e.read()
        row = {"t": t0, "secs": round(time.time() - t0, 2), "method": method, "path": path, "body": body,
               "status": status}
        if raw:
            row["bytes"], row["sha1"] = len(payload), hashlib.sha1(payload).hexdigest()
        else:
            try:
                row["response"] = json.loads(payload)
            except ValueError:
                row["response_text"] = payload.decode("utf-8", "replace")
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        print(f"[r1] {method} {path} -> {status} ({row['secs']}s)", flush=True)
        return status, (payload if raw else row.get("response", row.get("response_text")))


def main(mode: str) -> int:
    out = LANE / f"r1_{mode}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    env = dict(os.environ)
    env.pop("SLINK_UPR_JAR", None)
    if mode == "jar":
        env["SLINK_UPR_JAR"] = str(JAR)
    elif mode == "oldjar":
        env["SLINK_UPR_JAR"] = str(OLD_JAR)
    port = free_port()
    log = open(out / "manager.log", "w", encoding="utf-8")  # noqa: SIM115
    mgr = subprocess.Popen([sys.executable, "-m", "server.manager", "--host", "127.0.0.1", "--port", str(port),
                            "--data-dir", str(out / "mgr")], cwd=str(REPO), env=env, stdout=log,
                           stderr=subprocess.STDOUT)
    (out / "manager.pid").write_text(str(mgr.pid))
    print(f"[r1] manager pid {mgr.pid} port {port} mode {mode}", flush=True)
    api = Api(port, out / "calls.jsonl")
    summary: dict = {"mode": mode, "manager_pid": mgr.pid, "port": port, "jar_env": env.get("SLINK_UPR_JAR")}
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(api.base + "/api/runs", timeout=2).read()
                break
            except OSError:
                time.sleep(0.5)
        _, roms = api.call("GET", "/api/roms")
        pol = [r for r in roms["roms"] if r.get("family") == "gen2_polished"]
        summary["picker_polished"] = pol
        release = next((r["path"] for r in pol if r.get("kind") == "clean"), str(RELEASE))
        q = urllib.parse.urlencode({"rom_a": release, "rom_b": release})
        _, summary["status"] = api.call("GET", f"/api/randomizer/status?{q}")
        _, new = api.call("POST", "/api/runs/new", {"name": f"pol-rand {mode}", "game": "gen2_polished"})
        run_id = new.get("run_id") or new.get("run", {}).get("run_id")
        summary["run_id"] = run_id
        status, page = api.call("GET", f"/runs/{run_id}/randomizer")
        (out / "randomizer_page.html").write_text(page if isinstance(page, str) else json.dumps(page), encoding="utf-8")
        status, cart = api.call("POST", f"/api/runs/{run_id}/cartridges",
                                {"rom_a": release, "rom_b": release, "companion": True, "randomize": True,
                                 "spec": SPEC})
        summary["cartridges_status"], summary["cartridges"] = status, cart
        if status == 200 and cart.get("ok"):
            for p in "ab":
                _, blob = api.call("GET", f"/api/runs/{run_id}/rom/{p}", raw=True)
                (out / f"rom_{p}.gbc").write_bytes(blob)
                summary[f"rom_{p}_sha1"] = hashlib.sha1(blob).hexdigest()
            run_dir = out / "mgr" / run_id
            shutil.copyfile(run_dir / "rom_contract.json", out / "rom_contract.json")
            contract = json.loads((out / "rom_contract.json").read_text(encoding="utf-8"))
            summary["contract"] = contract
            summary["contract_matches_downloads"] = all(
                contract["players"][p]["rom_sha1"] == summary[f"rom_{p}_sha1"] for p in "ab")
            _, summary["runs"] = api.call("GET", "/api/runs")
    finally:
        if mgr.poll() is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(mgr.pid)], capture_output=True)
            mgr.wait(timeout=20)
        log.close()
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("runs", "cartridges")}, indent=1)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "jar"))
