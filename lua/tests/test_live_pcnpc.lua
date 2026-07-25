-- test_live_pcnpc.lua — LIVE Pokémon-Center trade NPC (presence-OFF path). The companion patch's
-- drive_trade_npc spawns a real engine NPC (localId 0xF1) on every Pokémon Center 1F when
-- MB.set_pc_npc(true), auto-arms talk on it (SS->pi_oe / pi_armed), and despawns it when disabled.
-- We enable it, confirm the NPC spawned + talk is armed, position the player one tile south facing it,
-- press A, and assert pi_count bumps with NO local box (the SERVER drives the Trade/Say hey menu). Then we
-- disable and confirm clean removal.
--
-- REQUIRES: the PATCHED RR ROM + a savestate STANDING IN A POKÉMON CENTER 1F (front room). Create one
-- and point STATE at it. The test also prints the spawned NPC's tile + the player's map id so you can
-- confirm/tune PCNPC_GFX / PCNPC_TILE_X/Y and the kPokecenter1F map list in patch/src/handlers.c.

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT   = WT .. "/patch/build/pcnpc_result.txt"
local STATE = "E:/Howard/Bizhawk/GBA/State/slink_pokecenter.State"   -- <-- savestate inside a PC 1F
local MB    = dofile(WT .. "/lua/mailbox.lua")

local OE, OST  = 0x02036E38, 0x24      -- gObjectEvents
local GS, GST  = 0x0202063C, 0x44      -- gSprites
local PI_ARMED = 0x0203F8D1            -- SlinkState.pi_armed
local PI_OE    = 0x0203F8D2            -- SlinkState.pi_oe
local TN_LOCALID = 0xF1

local function oe_active(i) return (memory.read_u8(OE + i*OST + 0x00) & 1) == 1 end
local function oe_local(i)  return memory.read_u8 (OE + i*OST + 0x08) end
local function oe_sprite(i) return memory.read_u8 (OE + i*OST + 0x04) end
local function oe_cx(i)     return memory.read_s16_le(OE + i*OST + 0x10) end
local function oe_cy(i)     return memory.read_s16_le(OE + i*OST + 0x12) end
local function spr_inuse(s) return (memory.read_u8(GS + s*GST + 0x3E) & 1) end
local function find_npc()   for i=0,15 do if oe_active(i) and oe_local(i) == TN_LOCALID then return i end end return 16 end

local lines={}; local fails=0
local function log(s) lines[#lines+1]=s; console.log(s) end
local function check(n,c,e) if not c then fails=fails+1 end; log(string.format("  [%s] %s%s",c and "PASS" or "FAIL",n,e and "  "..e or "")) end
local function finish() log(fails==0 and "RESULT: PASS" or ("RESULT: FAIL ("..fails..")"))
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, STATE); emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
if not MB.present() then log("FAIL: beacon absent (need the patched ROM)"); finish(); return end

local poe = MB.player_oe()
local pmg, pmn = memory.read_u8(poe + 0x0A), memory.read_u8(poe + 0x09)
log(string.format("player map = (%d,%d)  [confirm this is a Pokémon Center 1F in kPokecenter1F]", pmg, pmn))

-- 1) Enable the patch's PC-NPC driver; it should spawn + arm within a few frames.
MB.set_pc_npc(true)
local npc = 16
for _=1,120 do emu.frameadvance(); npc = find_npc(); if npc < 16 then break end end
check("trade NPC spawned (active OE, localId 0xF1)", npc < 16, "oe=" .. npc)
if npc >= 16 then
  log("  (no NPC — is the savestate inside a PC 1F? is this map in kPokecenter1F? is PCNPC_TILE valid?)")
  finish(); return
end
local nx, ny, sid = oe_cx(npc), oe_cy(npc), oe_sprite(npc)
log(string.format("  NPC oe=%d gfx=%d tile=(%d,%d) sprite=%d", npc, memory.read_u8(OE+npc*OST+0x05), nx, ny, sid))
check("NPC sprite allocated + in use", sid < 64 and spr_inuse(sid) == 1, "sprite=" .. sid)
check("talk armed on the NPC (SS->pi_oe + pi_armed)",
      memory.read_u8(PI_OE) == npc and memory.read_u8(PI_ARMED) == 1,
      string.format("pi_oe=%d pi_armed=%d", memory.read_u8(PI_OE), memory.read_u8(PI_ARMED)))

-- 2) Talk: put the player one tile SOUTH of the NPC, idle + facing NORTH, then press A.
--    check_peer_interact reads only the player's currentCoords/facing/idle + the armed OE's tile, so
--    repositioning the player struct is sufficient to simulate standing in front of the NPC.
memory.write_s16_le(poe + 0x10, nx)        -- player currentCoords X = NPC X
memory.write_s16_le(poe + 0x12, ny + 1)    -- player currentCoords Y = NPC Y + 1 (one tile south)
local face = memory.read_u8(poe + 0x18)
memory.write_u8(poe + 0x18, (face & 0xF0) | 2)        -- facing NORTH (toward the NPC)
memory.write_u8(poe + 0x00, memory.read_u8(poe) | 0x80)  -- heldMovementFinished (idle)

local c0 = MB.peer_interact_count()
joypad.set({}); emu.frameadvance()
joypad.set({A=true}); emu.frameadvance()              -- A newly pressed, facing the NPC
joypad.set({}); for _=1,20 do emu.frameadvance() end

check("peer-interact counter incremented", MB.peer_interact_count() > c0,
      string.format("%d -> %d", c0, MB.peer_interact_count()))
check("no local box auto-opened (server drives the menu)", memory.read_u8(0x03000F9C) == 0,
      "sScriptContext2Enabled=" .. memory.read_u8(0x03000F9C))

-- 3) Disable: the patch must remove the NPC cleanly + disarm talk.
MB.set_pc_npc(false)
for _=1,60 do emu.frameadvance(); if find_npc() >= 16 then break end end
check("NPC removed when disabled", find_npc() >= 16)
check("sprite freed", sid >= 64 or spr_inuse(sid) == 0, "sprite=" .. sid)
check("talk disarmed", memory.read_u8(PI_ARMED) == 0, "pi_armed=" .. memory.read_u8(PI_ARMED))
check("game still running (no softlock)", MB.present())

finish()
