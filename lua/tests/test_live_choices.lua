-- test_live_choices.lua — OP_SHOW_CHOICES (the PROPER multichoice list menu) through
-- lua/gen3/native.lua. native:show_choices stages {"TRADE","WAVE"} in MENU_BUF and opens the native
-- vertical multichoice (replicated DrawVerticalMultichoiceMenu in C + the engine's input task).
-- Confirms the menu opens and the chosen index round-trips from the mailbox result into native's
-- menu_result event. The patch-side guards against malformed stages are test_live_choices_guards.lua
-- (a GAP: native.lua never posts a malformed list). Overworld savestate, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local SC2 = 0x03000F9C
local t = G.open("choices")
t.boot({ state = "slink_overworld.State" })

local function pick(token)
    local job = t.watch(t.native:show_choices({ token = token, options = { "TRADE", "WAVE" } }))
    t.check("native:show_choices queued the op (token " .. token .. ")", job ~= nil)
    if not job then t.finish() end
    t.check("op posted to the mailbox (dispatch receipt)", t.wait_posted(job))
    -- Drive: let the menu open, then press A (cursor defaults to index 0 = TRADE).
    local saw_menu = false
    local r = t.wait(job, 300, function(i)
        if memory.read_u8(SC2) ~= 0 then saw_menu = true end
        return (i > 30 and i % 2 == 0) and { A = true } or nil
    end)
    return r, saw_menu
end

local r, saw_menu = pick(3)
t.check("native multichoice opened (field script locked)", saw_menu)
t.check("choices acked", r ~= nil, t.receipt_str(r))
t.check("ack is ST_OK", r ~= nil and r.why == nil, t.receipt_str(r))
t.check("chose index 0 (TRADE, default cursor + A)", r ~= nil and r.result == 0, t.receipt_str(r))
local sent = t.sent_of("menu_result")
t.check("native sent menu_result{token=3, choice=0}",
        #sent == 1 and sent[1].token == 3 and sent[1].choice == 0,
        #sent == 1 and ("choice=" .. tostring(sent[1].choice)) or (#sent .. " menu_result events"))
t.check("dialogue closed (no stuck menu)", memory.read_u8(SC2) == 0)

-- The mailbox must be reusable: a second list opens and acks after the first one closed.
local r2 = pick(4)
t.check("a second list opens and acks", r2 ~= nil and r2.why == nil, t.receipt_str(r2))
t.check("field released again", memory.read_u8(SC2) == 0)
t.check("beacon still present (no crash)", t.present())
t.finish()
