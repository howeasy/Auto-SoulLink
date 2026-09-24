-- test_live_choices_guards.lua — the OP_SHOW_CHOICES patch-side GUARDS (malformed MENU_BUF stages).
--
-- MALFORMED STAGES MUST BE REJECTED AT THE OPCODE, NOT INSIDE THE CALLNATIVE. show_choices_entry runs
-- from a lockall'd field script whose `waitstate` is resolved ONLY by the input task it creates, so
-- any early return from it strands the player in a locked overworld with no window and no way out —
-- a reset-only softlock. The guards therefore live in OP_SHOW_CHOICES (handlers.c choices_ok), before
-- lockall, and the entry clamps and repairs instead of bailing. Each case asserts BOTH halves: a clean
-- ST_FAIL, and the field left unlocked. A well-formed list must still open afterwards, so the guards
-- cannot have been "fixed" by rejecting everything.
--
-- native:show_choices validates in Lua and never posts a malformed list, so these stages go through
-- lua/tests/gen3_gatelib.lua's test-only raw poster (card C5-4b). The valid path through native.lua is
-- test_live_choices.lua. Overworld savestate, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local SC2 = 0x03000F9C   -- sScriptContext2Enabled
local t = G.open("choices_guards")

local function boot() t.boot({ state = "slink_overworld.State", native = false, beacon = 240 }) end
local MENU_BUF = t.P.MENU_BUF

-- Each case re-loads so it starts from a known-good, unlocked overworld.
local function reject_case(name, stage)
    boot()
    local r = t.raw_wait("OP_SHOW_CHOICES", { 0 }, { { MENU_BUF, stage } }, 180)
    t.check(name .. ": ST_FAIL", r ~= nil and r.why == "native refused", t.receipt_str(r))
    t.check(name .. ": field not locked", memory.read_u8(SC2) == 0)
end

local over = { 9 }
for i = 1, 40 do over[#over + 1] = 0xFF end
local unterminated = { 1 }
-- fill the whole buffer with a printable glyph so no 0xFF appears anywhere after the count
for i = 1, 111 do unterminated[#unterminated + 1] = 0xBB end

reject_case("count 0", { 0 })
reject_case("count 9 (over the 8 the window can hold)", over)
reject_case("option with no terminator", unterminated)

-- ...and a well-formed stage must still work after all that.
local good = { 2 }
for _, opt in ipairs({ "TRADE", "WAVE" }) do
    for _, b in ipairs(t.encode(opt, 113)) do good[#good + 1] = b end
end
local r = t.raw_wait("OP_SHOW_CHOICES", { 0 }, { { MENU_BUF, good } }, 300,
                     function(i) return (i > 30 and i % 2 == 0) and { A = true } or nil end)
t.check("a valid list still opens and acks after the rejections", t.acked_ok(r), t.receipt_str(r))
t.check("chose index 0 (TRADE, default cursor + A)", r ~= nil and r.result == 0, t.receipt_str(r))
t.check("field released again", memory.read_u8(SC2) == 0)
t.finish()
