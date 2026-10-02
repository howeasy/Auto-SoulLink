-- Dump the settled vanilla title: which BG tile ids hold data, and both BG maps. Output is committed as a test fixture.
local out = io.open(os.getenv("SLINK_SHOT_DIR") .. "/title_vram.json", "w")
for f = 1, tonumber(os.getenv("SLINK_PROBE_FRAME") or "1900") do emu.frameadvance() end
local function nonzero(base)           -- 128 tiles, "1" when any of the 16 bytes is non-zero
  local s = {}
  for i = 0, 127 do
    local nz = "0"
    for b = 0, 15 do if memory.read_u8(base + i * 16 + b, "VRAM") ~= 0 then nz = "1" break end end
    s[#s + 1] = nz
  end
  return table.concat(s)
end
local function map(base)
  local rows = {}
  for y = 0, 17 do
    local r = {}
    for x = 0, 19 do r[#r + 1] = tostring(memory.read_u8(base + y * 32 + x, "VRAM")) end
    rows[#rows + 1] = '[' .. table.concat(r, ",") .. ']'
  end
  return '[' .. table.concat(rows, ",") .. ']'
end
out:write('{"frame": ', os.getenv("SLINK_PROBE_FRAME") or "1900",
  ', "ids_00_7f_nonzero": "', nonzero(0x1000), '", "ids_80_ff_nonzero": "', nonzero(0x0800),
  '", "map0": ', map(0x1800), ', "map1": ', map(0x1C00), '}\n')
out:close(); client.exit()
