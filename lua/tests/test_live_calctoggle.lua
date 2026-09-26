-- test_live_calctoggle.lua — LIVE smoke for the Battle-Calc kill switch (SLINK_CALC_OFF, profile
-- native.CALC_OFF), set through lua/gen3/native.lua's config({battle_calc}) the way the server's
-- config command sets it. The battletext shim branches: byte 0 -> the calc trampoline; byte 1 ->
-- replay the two displaced halfwords (mov r7,r8 ; push {r7}) and continue BattlePutTextOnWindow's
-- body as if the calc weren't installed. A wrong replay crashes/hangs EVERY in-battle text draw, so
-- this drives a battle with the byte flipped both ways and asserts the game keeps running.
-- Battle savestate, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("calctoggle")
t.boot({ state = "slink_battle.State" })
local CALC_OFF = t.P.CALC_OFF
local function mash(i) return i % 20 < 10 and { A = true } or nil end
-- config is a stage-only native job (no opcode, no receipt): it lands at the next frame end.
local function set_calc(on) t.native:config({ battle_calc = on }) end

-- Mash A through battle text with the calc DISABLED: every battle message draw exercises the
-- byte-1 shim path. If the displaced-instruction replay were wrong this hangs/crashes immediately.
set_calc(false)
t.step(nil)
t.check("calc-off byte set", memory.read_u8(CALC_OFF) == 1, "byte=" .. memory.read_u8(CALC_OFF))
for i = 1, 600 do t.step(mash(i)) end
t.check("600 frames calc-OFF survived (beacon alive)", t.present())

-- Flip back ON mid-battle and keep going — both directions must be safe at runtime.
set_calc(true)
t.step(nil)
t.check("calc-on byte cleared", memory.read_u8(CALC_OFF) == 0, "byte=" .. memory.read_u8(CALC_OFF))
for i = 1, 600 do t.step(mash(i)) end
t.check("600 frames calc-ON survived (beacon alive)", t.present())

-- Rapid flip churn (worst case: byte changes between draws within a message). Every frame queues a
-- flip and the previous one lands, so the byte alternates frame by frame.
local flips, last = 0, memory.read_u8(CALC_OFF)
for i = 1, 240 do
    set_calc(i % 2 == 0)
    t.step(mash(i))
    local now = memory.read_u8(CALC_OFF)
    if now ~= last then flips = flips + 1 end
    last = now
end
set_calc(true)
t.step(nil)
t.check("the byte really churned (native config landed every frame)", flips >= 200, "flips=" .. flips)
t.check("240 frames flip-churn survived (beacon alive)", t.present())
t.check("calc restored ON", memory.read_u8(CALC_OFF) == 0)
t.finish()
