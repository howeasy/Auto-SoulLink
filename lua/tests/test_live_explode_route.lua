-- test_live_explode_route.lua — LIVE validation of the PRODUCTION Explode-Mode routing
-- on a patched ROM.  Mirrors exactly what gen3_frlge_client.lua now does when it receives
-- a `force_explode` command for an active battler with the companion patch present:
--   1. write MOVE_EXPLOSION into gBattleMons[battler].moves[0] (+ pp[0]=5, PP>0 required),
--   2. MB.send(OP_FORCE_MOVE_SLOT, {battler, target=1, move_pos=0}) to arm the controller swap,
--   3. the patch's driver reads moves[0] at fire time and executes Explosion natively.
-- PASS = slot-0 holds Explosion AND its PP drops (the engine committed + fired the forced
-- move), with the mailbox still alive.  This is the same bar as test_live_forcemove.lua:
-- in a frozen savestate only battler 0 is forced, so the foe never commits and the turn's
-- damage script never resolves — the self-faint (hp→0) is a real-two-sided-play consequence,
-- logged here as informational, not a pass gate.
-- Battle save + PATCHED ROM.  Replaces the fragile Variant-3 menu-skip RAM hack.

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT   = WT .. "/patch/build/exploderoute_result.txt"
local STATE = "E:/Howard/Bizhawk/GBA/State/slink_battle.State"
local MB    = dofile(WT .. "/lua/mailbox.lua")

local MOVE_EXPLOSION = 153
local gBM, gComm, gExec = 0x02023BE4, 0x02023E82, 0x02023BC8
local function move(b,i) return memory.read_u16_le(gBM + b*0x58 + 0x0C + i*2) end
local function pp(b,i)   return memory.read_u8   (gBM + b*0x58 + 0x24 + i)     end
local function hp(b)     return memory.read_u16_le(gBM + b*0x58 + 0x28)        end
local function comm(b)   return memory.read_u8   (gComm + b)                   end
local function clear_exec(b)
    local m=(1<<b)|(1<<(b+4))|(1<<(b+8))|(1<<(b+12))|0xF0000000
    memory.write_u32_le(gExec, memory.read_u32_le(gExec)&(~m&0xFFFFFFFF))
end

local lines={}; local function log(s) lines[#lines+1]=s; console.log(s) end
local function finish(ok) log(ok and "RESULT: PASS" or "RESULT: FAIL")
  local f=io.open(OUT,"w"); if f then f:write(table.concat(lines,"\n").."\n"); f:close() end; client.exit() end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, STATE); emu.frameadvance(); pcall(memory.usememorydomain,"System Bus")
if not MB.present() then log("FAIL: beacon absent"); finish(); return end

local B, POS, TARGET = 0, 0, 1
log(string.format("before: moves[0]=%d pp[0]=%d hp=%d", move(B,POS), pp(B,POS), hp(B)))

-- Production routing step 1+2: stamp Explosion into slot 0 (+PP), then arm the driver.
memory.write_u16_le(gBM + B*0x58 + 0x0C + POS*2, MOVE_EXPLOSION)
memory.write_u8   (gBM + B*0x58 + 0x24 + POS,    5)
local pp0 = pp(B,POS)
MB.send(MB.OP_FORCE_MOVE_SLOT, MB.force_move_slot_args(B, TARGET, POS))
log(string.format("armed: moves[0]=%d (expect %d) pp[0]=%d", move(B,POS), MOVE_EXPLOSION, pp0))

-- Phase 1: nudge the (savestate-frozen) battle to the action menu and let the patch fire.
local committed = false
for _ = 1, 600 do
    local c = comm(B)
    if c < 2 or c >= 4 then clear_exec(B) end
    emu.frameadvance()
    if pp(B,POS) < pp0 then committed = true; break end
end

-- Phase 2 (informational only): advance a while in case the turn happens to resolve the
-- self-faint.  In a one-sided frozen savestate it won't (the foe never commits), so this is
-- logged but NOT a pass gate — see the header.
local self_fainted = (hp(B) == 0)
if committed then
    for _ = 1, 600 do
        emu.frameadvance()
        if hp(B) == 0 then self_fainted = true; break end
    end
end

local explosion_selected = (move(B,POS) == MOVE_EXPLOSION)
log(string.format("after: moves[0]=%d pp[0]=%d (was %d) hp=%d committed=%s self_fainted=%s(info) present=%s",
    move(B,POS), pp(B,POS), pp0, hp(B), tostring(committed), tostring(self_fainted), tostring(MB.present())))
finish(committed and explosion_selected and MB.present())
