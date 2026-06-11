-- sprite_gallery.lua — INTERACTIVE object-event graphicsId browser, for picking PCNPC_GFX.
-- Spawns an engine NPC one tile EAST of the player and lets you cycle its graphicsId with the
-- keyboard, rendering each candidate exactly as the engine would (sprite, palette, OAM size).
-- Load the PATCHED ROM, stand somewhere open (a Pokémon Center works), run this, and browse.
--
--   N = next gfx     P = previous gfx     K = +10     J = -10
--
-- The current id is shown on screen and logged. When you've picked one, set PCNPC_GFX in
-- patch/src/handlers.c to that id and rebuild (python patch/tools/build.py).
--
-- SAFETY: make a savestate first. graphicsIds are an index into RR's graphics-info table; ids past
-- the table's end read garbage pointers and can glitch or crash. We cap at 0xEF (vanilla FR ends
-- ~0x96; CFRU/RR extends it, so mid-range ids are usually fine — back off if a range looks corrupt).

local WT = "E:/Google Drive/SLink/.claude/worktrees/condescending-bassi-9175e6"
local MB = dofile(WT .. "/lua/mailbox.lua")
pcall(memory.usememorydomain, "System Bus")

local LOCALID = 0xF2          -- distinct from the ghost (0xF0) and the PC trade NPC (0xF1)
local MAXGFX  = 0xEF
local OE, OST = 0x02036E38, 0x24
local gfx, oe = 1, 16

console.log("[gallery] waiting for the patch beacon...")
while not MB.present() do emu.frameadvance() end

local function slot_is_ours()
  if oe >= 16 then return false end
  local base = OE + oe*OST
  return (memory.read_u8(base) & 1) == 1 and memory.read_u8(base + 0x08) == LOCALID
end

local function despawn()
  if slot_is_ours() then
    local st = MB.send(MB.OP_DESPAWN_PEER_NPC, {oe})
    for _ = 1, 10 do emu.frameadvance(); if MB.poll(st) then break end end
  end
  oe = 16
end

local function spawn()
  local poe = MB.player_oe()
  local px = memory.read_s16_le(poe + 0x10)
  local py = memory.read_s16_le(poe + 0x12)
  local st = MB.send(MB.OP_SPAWN_PEER_NPC, MB.spawn_npc_args(gfx, LOCALID, px + 1, py, 0))
  for _ = 1, 10 do emu.frameadvance(); if MB.poll(st) then break end end
  oe = MB.read_result_u8(0)
  if oe >= 16 then
    console.log(string.format("[gallery] spawn FAILED for gfx=%d (no free OE slot here?)", gfx))
  else
    console.log(string.format("[gallery] gfx = %d (0x%02X)  -> oe=%d", gfx, gfx, oe))
  end
end

local function reskin(delta)
  gfx = (gfx + delta) % (MAXGFX + 1)
  if gfx < 0 then gfx = gfx + MAXGFX + 1 end
  despawn(); spawn()
end

console.log("[gallery] N=next  P=prev  K=+10  J=-10.  NPC spawns 1 tile EAST of you.")
spawn()

local prev = {}
while true do
  local cur = input.get()
  if cur["N"] and not prev["N"] then reskin(1)   end
  if cur["P"] and not prev["P"] then reskin(-1)  end
  if cur["K"] and not prev["K"] then reskin(10)  end
  if cur["J"] and not prev["J"] then reskin(-10) end
  prev = cur
  -- Map change / scripted reload freed our slot -> respawn at the player's new spot.
  if oe < 16 and not slot_is_ours() then oe = 16; spawn() end
  gui.text(8, 8, string.format("gfx = %d (0x%02X)    N/P = +/-1    K/J = +/-10", gfx, gfx))
  emu.frameadvance()
end
