"""Launch EmuHawk on a built pureRGB ROM with the probe script; SaveRAM redirected to scratch."""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SP = os.path.dirname(HERE)
W = r"E:\Google Drive\SLink\.claude\worktrees\gen1-master-release-plan-6b4279"
sys.path.insert(0, os.path.join(W, "tools"))
os.environ.setdefault("SLINK_EMU_WINDOW", "primary")
import gen1_playthrough as gp  # noqa: E402  (read-only reuse of the config writer)

rom = sys.argv[1] if len(sys.argv) > 1 else os.path.join(SP, "build", "pokered.gbc")
script = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "probe.lua")
out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(HERE, "probe_out.txt")
frames = sys.argv[4] if len(sys.argv) > 4 else "9000"
timeout = int(sys.argv[5]) if len(sys.argv) > 5 else 420

cfg = os.path.join(HERE, "config_probe.ini")
gp.write_run_config(gp.BIZHAWK_CONFIG, cfg, saveram_dir=os.path.join(HERE, "saveram"))
if os.path.exists(out):
    os.remove(out)
env = dict(os.environ, SLINK_PROBE_OUT=out, SLINK_PROBE_FRAMES=frames)
cmd = [gp.EMUHAWK, f"--lua={script}", f"--config={cfg}", rom]
print("[probe]", " ".join(cmd), file=sys.stderr)
proc = subprocess.Popen(cmd, cwd=HERE, env=env)
deadline = time.time() + timeout
while time.time() < deadline and proc.poll() is None:
    time.sleep(1)
if proc.poll() is None:
    proc.kill()
    print("[probe] timed out; killed", file=sys.stderr)
print(open(out, encoding="utf-8", errors="replace").read() if os.path.exists(out) else "[probe] no output")
