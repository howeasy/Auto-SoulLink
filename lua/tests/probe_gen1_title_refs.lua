client.speedmode(tonumber(os.getenv("SLINK_SPEED") or "100"))   -- SLINK_SPEED=800 reaches a slow title (Gen 2) in seconds
-- Which BG tile ids does a title EVER reference, over the whole boot-to-idle sequence? Samples both BG maps
-- (all 32x32 cells, so off-screen scroll columns count) every 4 frames. A tile id that never appears is safe to
-- reuse; one that appears once is not. SLINK_FORCE_PURE=<addr> keeps pureRGB's Pure title flag set (see
-- probe_gen1_title_vram.lua). Output: <SLINK_SHOT_DIR>/title_refs.json {"frames": N, "referenced": [ids]}.
local force = tonumber(os.getenv("SLINK_FORCE_PURE") or "")
local last = tonumber(os.getenv("SLINK_PROBE_FRAME") or "3600")
local from = tonumber(os.getenv("SLINK_REFS_FROM") or "1")   -- start after the intro (the copyright screen reuses these ids)
local seen = {}
local function scan(base)
  for y = 0, 17 do for x = 0, 19 do seen[memory.read_u8(base + y * 32 + x, "VRAM")] = true end end
end
for f = 1, last do
  if force and f >= 12 then memory.write_u8(force, bit.bor(memory.read_u8(force, "System Bus"), 0x40), "System Bus") end
  emu.frameadvance()
  if f >= from and f % 4 == 0 then scan(0x1800); scan(0x1C00) end
end
local ids = {}
for i = 0, 255 do if seen[i] then ids[#ids + 1] = tostring(i) end end
local out = io.open(os.getenv("SLINK_SHOT_DIR") .. "/title_refs.json", "w")
out:write('{"frames": ', last, ', "referenced": [', table.concat(ids, ","), ']}\n')
out:close(); client.exit()
