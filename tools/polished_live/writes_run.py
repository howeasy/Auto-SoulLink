#!/usr/bin/env python3
"""Run card POL-LIVE-WRITES on the INTEGRATED Polished overlay (tools/polished_live/writes.lua).

    python tools/polished_live/writes_run.py

Nothing is rebuilt. The staged ROM is the pinned release with the committed
patch/dist/SLink-Polished.ups applied, and it is refused unless its sha1 is the integrated
overlay `deebb100…` (the same figure lanes/g2int-ov/drv/mkrom.py produces). The save fixture is
copied into this lane and its sha256 printed, so another card rewriting its own lane cannot move
this run's inputs.

No SLink server is started: the card drives the CLIENT, through `Client:handle_command`
(lua/gen2/client.lua:535), which is the same public entry the real reply path uses.

One EmuHawk at a time, engine warp only, short non-Drive lane. Only the PID this script starts is
ever killed (harness.kill_own) — never an image-name kill.
"""
from __future__ import annotations

import hashlib
import os
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO))

os.environ.setdefault("POL_LANE", "F:/slink-work/lanes/pol-livew")
os.environ.setdefault("POL_FIXTURE", "F:/slink-work/lanes/g2int-ov/live/sram_overlay/pol overlay.SaveRAM")

import harness  # noqa: E402
from patch.tools.make_ups import ups_apply  # noqa: E402

LANE = harness.LANE
RELEASE = Path("F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.gbc")
UPS = REPO / "patch/dist/SLink-Polished.ups"
STAGED = LANE / "rom" / "pol_writes.gbc"
# the integrated overlay sha1, as staged by lanes/g2int-ov/drv/mkrom.py
INTEGRATED_SHA1 = "deebb1004d4f6123667d5d9e061ad0bf867ac021"


def stage() -> str:
    clean = RELEASE.read_bytes()
    data = ups_apply(clean, UPS.read_bytes())
    sha1 = hashlib.sha1(data).hexdigest()
    if sha1 != INTEGRATED_SHA1:
        raise SystemExit(f"staged overlay sha1 {sha1} != integrated overlay {INTEGRATED_SHA1}")
    STAGED.parent.mkdir(parents=True, exist_ok=True)
    STAGED.write_bytes(data)
    return sha1


def main() -> int:
    sha1 = stage()
    print(f"[writes] staged {STAGED} sha1 {sha1}", flush=True)
    harness.ROM_SRC = STAGED
    harness.ROM = STAGED                 # harness.ROM is what EmuHawk is handed

    source = harness.FIXTURE
    if not source.is_file():
        raise SystemExit(f"no save fixture at {source}")
    fixture = LANE / "fixture" / "pol_writes.SaveRAM"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, fixture)
    print(f"[writes] fixture sha256 {hashlib.sha256(fixture.read_bytes()).hexdigest()}", flush=True)

    # BizHawk names the SaveRAM from the ROM FILE STEM, not from the game database: the fixture
    # copy must share the staged ROM's stem or the boot is a fresh new game (the coordinator's
    # screenshot: the Options screen looping).
    sram = harness.SRAM
    sram.mkdir(parents=True, exist_ok=True)
    save_name = STAGED.stem + ".SaveRAM"
    shutil.copyfile(fixture, sram / save_name)
    print(f"[writes] save as {sram / save_name} (rom stem {STAGED.stem!r})", flush=True)

    # The real client dials a TCP peer on start. There is no SLink server here (the card drives
    # the client), so start the harness's own server exactly as harness.cmd_live does -- otherwise
    # the connector retries forever and the boot never settles.
    run = LANE / "writes"
    srv_dir = run / "srv"
    if srv_dir.exists():
        shutil.rmtree(srv_dir)
    srv_dir.mkdir(parents=True)
    (srv_dir / "rom_contract.json").write_text(
        json.dumps({"upr_version": "none (overlay, not randomized)", "categories": [],
                    "players": {"a": {"rom_sha1": sha1}}}), encoding="utf-8")
    port, http = harness.free_port(), harness.free_port()
    srv_log = open(run / "server.log", "w", encoding="utf-8")
    srv = subprocess.Popen([sys.executable, "-m", "server.server", "--host", "127.0.0.1",
                            "--port", str(port), "--http-port", str(http),
                            "--data-dir", str(srv_dir), "--wire-log", str(run / "wire")],
                           cwd=str(REPO), stdout=srv_log, stderr=subprocess.STDOUT)
    print(f"[writes] server pid {srv.pid} tcp {port}", flush=True)
    time.sleep(1.5)
    try:
        text, pid = harness.launch("tools/polished_live/writes.lua", run,
                                   {"SLINK_HOST": "127.0.0.1", "SLINK_PORT": str(port)}, 300)
    finally:
        # only our own PIDs: the emulator harness.kill_own handles, this is the server
        if srv.poll() is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(srv.pid)], capture_output=True)
        srv.wait(timeout=20)
    print(text[-4000:])
    result = run / "result.txt"
    if result.is_file():
        print(f"[writes] result.txt sha256 {hashlib.sha256(result.read_bytes()).hexdigest()}", flush=True)
    ok = "RESULT: PASS" in text
    print(f"[writes] {'PASS' if ok else 'FAIL'} (EmuHawk pid {pid})", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())