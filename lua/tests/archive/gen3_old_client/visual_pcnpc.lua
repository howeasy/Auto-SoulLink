-- visual_pcnpc.lua — INTERACTIVE check of the Pokémon-Center trade NPC. Unlike test_live_pcnpc.lua
-- this does NOT exit BizHawk: it just enables the patch's PC-NPC driver and lets you play. Load the
-- PATCHED ROM, walk into any Pokémon Center 1F, and eyeball the NPC's sprite (PCNPC_GFX) + tile
-- (PCNPC_TILE_X/Y in patch/src/handlers.c). Press A on it — the console logs each talk detection.
-- Stop the script (or close BizHawk) when done; it disables the driver on exit.

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local MB = dofile(WT .. "/lua/mailbox.lua")
pcall(memory.usememorydomain, "System Bus")

local OE, OST = 0x02036E38, 0x24
local function find_npc()
  for i = 0, 15 do
    local f = memory.read_u8(OE + i*OST)
    if (f & 1) == 1 and memory.read_u8(OE + i*OST + 0x08) == 0xF1 then return i end
  end
  return 16
end

console.log("[visual-pcnpc] waiting for the patch beacon...")
while not MB.present() do emu.frameadvance() end
MB.set_pc_npc(true)
console.log("[visual-pcnpc] PC-NPC driver ENABLED. Walk into a Pokémon Center 1F and look around.")

local last_oe, last_cnt = 16, MB.peer_interact_count()
local ok, err = pcall(function()
  while true do
    local npc = find_npc()
    if npc ~= last_oe then
      if npc < 16 then
        console.log(string.format("[visual-pcnpc] NPC spawned: oe=%d gfx=%d tile=(%d,%d)",
          npc, memory.read_u8(OE + npc*OST + 0x05),
          memory.read_s16_le(OE + npc*OST + 0x10), memory.read_s16_le(OE + npc*OST + 0x12)))
      else
        console.log("[visual-pcnpc] NPC despawned (left the center / map change)")
      end
      last_oe = npc
    end
    local cnt = MB.peer_interact_count()
    if cnt ~= last_cnt then
      console.log("[visual-pcnpc] TALK detected (pi_count " .. last_cnt .. " -> " .. cnt .. ")")
      last_cnt = cnt
    end
    emu.frameadvance()
  end
end)
MB.set_pc_npc(false)
if not ok then console.log("[visual-pcnpc] stopped: " .. tostring(err)) end
