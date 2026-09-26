-- test_live_msgboxdismiss.lua — OP_SHOW_MESSAGE must be a DISMISSABLE dialogue (the waved-at
-- player's "Your partner waved at you!" box used to stick open). The patch routes it through the std
-- sign-msgbox script (lockall/message/waitbuttonpress/releaseall). Assert: showing the message enables
-- a field script (sScriptContext2Enabled != 0), and an A-press dismisses it (returns to 0).
-- DEFERRED (native text is off for the RC): opt-in via SLINK_GATES_DEFERRED=1. Posted through
-- lua/tests/gen3_gatelib.lua's test-only raw poster (C5-4c). Overworld savestate, PATCHED ROM.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("msgboxdismiss")
local SCRIPT_ACTIVE = 0x03000F9C   -- sScriptContext2Enabled (u8 != 0 while a field script is up)
local function script_up() return memory.read_u8(SCRIPT_ACTIVE) ~= 0 end
t.boot({ state = "slink_overworld.State", native = false })
t.check("no script up initially", not script_up())

-- Show a message via the opcode (text staged with the post).
local job = t.raw("OP_SHOW_MESSAGE", {}, { t.message_stage("Your partner waved at you!") })
t.check("SHOW_MESSAGE posted", t.wait_posted(job), t.last_service)
local up = false
for _ = 1, 30 do t.step(nil); if script_up() then up = true; break end end
t.check("OP_SHOW_MESSAGE opened a dismissable dialogue (script active)", up)

-- Press A to advance/dismiss; the box should close and release the player.
t.step({})
t.step({ A = true })
t.idle(40)
-- a single A may just print; mash A a couple more times to close any wait-button-press
for _ = 1, 3 do t.step({ A = true }); t.idle(15) end
t.check("dialogue dismissed by A (script no longer active)", not script_up())
t.finish()
