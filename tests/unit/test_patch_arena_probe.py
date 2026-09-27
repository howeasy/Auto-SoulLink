"""Opt-in T2 heap diagnostic runner. Never launched by pytest collection.

python tests/unit/test_patch_arena_probe.py positive|negative
This proves only the native allocator boundary and a boot canary, NOT trade,
panel, save, battle, or complete EWRAM ownership. All output stays in patch/build.
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_probe(mode):
    base = ROOT / "patch/build" / f"arena-firered-{mode}"
    assert base.resolve().is_relative_to(ROOT.resolve())
    emulator = Path(os.environ.get("SLINK_EMUHAWK", "E:/Howard/Bizhawk/EmuHawk.exe"))
    config_source = Path(os.environ.get("SLINK_BIZHAWK_CONFIG", "E:/Howard/Bizhawk/config.ini"))
    config = json.loads(config_source.read_text(encoding="utf-8-sig"))
    frontend = base / "frontend"
    frontend.mkdir(parents=True, exist_ok=True)
    for entry in config["PathEntries"]["Paths"]:
        if entry["Type"] == "Firmware":
            entry["Path"] = str(config_source.parent / "Firmware")
        else:
            entry["Path"] = str(frontend / entry["System"] / entry["Type"].replace("/", "_"))
    config["RewindEnabled"] = False
    config["AutoLoadLastSaveSlot"] = False
    config["AutoSaveLastSaveSlot"] = False
    config_path = base / "config.ini"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    result = base / "result.txt"
    result.unlink(missing_ok=True)
    script = base / "probe.lua"
    script.write_text('''local out = assert(io.open("''' + result.as_posix() + '''", "w"))
local function log(s) out:write(s .. "\\n"); out:flush() end
local function rd(a) return memory.read_u32_le(a, "System Bus") end
client.speedmode(1000)
local ok, why = pcall(function()
  local found = false
  for frame = 1, 1800 do
    emu.frameadvance()
    if rd(0x0201B000) == 0x32505241 then
      local mode, requested, actual = rd(0x0201B004), rd(0x0201B008), rd(0x0201B00C)
      local allocated, intact = rd(0x0201B010), rd(0x0201B014)
      log(string.format("NATIVE_ALLOCATOR frame=%d mode=%d requested=%X actual=%X allocated=%d canary=%d", frame, mode, requested, actual, allocated, intact))
      assert(requested == 0x1C000, "wrong original heap size")
      if mode == 1 then
        assert(actual == 0x1B000 and allocated == 1 and intact == 1, "reservation failed")
        assert(rd(0x0201B018) + rd(0x0201B01C) <= 0x0201B000, "allocation reached reservation")
        for tick = 1, 600 do
          emu.frameadvance()
          for i = 0, 15 do assert(rd(0x0201BF00 + 4*i) == 0xC0DEC0DE, "boot canary clobbered") end
        end
        log("BOOT_CANARY frames=600 words=16 unchanged")
      else
        assert(mode == 2 and actual == 0x1C000 and allocated == 1 and intact == 0, "negative control did not detect allocator overwrite")
      end
      found = true
      break
    end
  end
  if not found then
    log(string.format("DEBUG marker=%X hook=%X heap=%X size=%X", rd(0x0201B000), rd(0x08002B80), rd(0x03000A38), rd(0x03000A3C)))
    client.screenshot("''' + (base / "failure.png").as_posix() + '''")
  end
  assert(found, "native probe never completed")
end)
log("SCOPE: native allocation + boot only; title lifecycle unqualified")
log("RESULT: " .. (ok and "PASS" or "FAIL") .. " " .. tostring(why or ""))
out:close()
client.exit()
''', encoding="utf-8")
    cmd = [str(emulator), f"--config={config_path.relative_to(ROOT).as_posix()}",
           f"--lua={script.relative_to(ROOT).as_posix()}", (base / "probe.gba").relative_to(ROOT).as_posix()]
    started = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=ROOT, env={**os.environ, "SLINK_ROOT": ROOT.as_posix()},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"owned EmuHawk PID={proc.pid}, mode={mode}", flush=True)
    try:
        while proc.poll() is None and time.monotonic() - started < 120:
            if result.exists() and "RESULT:" in result.read_text():
                break
            time.sleep(1)
    finally:
        if proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=15)
            proc.wait(timeout=15)
    text = result.read_text() if result.exists() else "FAIL: no result"
    print(text)
    return 0 if "RESULT: PASS" in text else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("positive", "negative"))
    raise SystemExit(run_probe(parser.parse_args().mode))
