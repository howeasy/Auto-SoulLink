-- probe_gen3_rr_bag.lua — drive an input script inside a Radical Red battle and screenshot
-- after each step, to PIN the CFRU battle BAG navigation to a POKe BALL (the FR driver's
-- Right -> B_ACTION_USE_ITEM toggle does not carry over: CFRU replaces the bag UI). Once the
-- sequence that ends in a thrown ball is known (gBattleOutcome == 7, B_OUTCOME_CAUGHT), the RR
-- natural-play driver's wild_catch leg gets it.
--
-- Environment: SLINK_ROOT, SLINK_GEN3_CHECKPOINT/TITLE; SLINK_STATE (default slink_prebattle.State);
--   SLINK_BAG_SCRIPT   comma list of steps: a button name (A B Up Down Left Right Start Select),
--                      "waitN" (N frames), "shot" (screenshot patch/build/gen3_bag_<n>.png),
--                      "menu" (wait until the action menu is up: gBattlerControllerFuncs[0] ==
--                      the duo-precedent ACTION_MENU value, scenario_explode.lua:27-28).
-- Prints a phase per step with the battle outcome byte, party count and frame.

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")
G.open("gen3_rr_bag")
pcall(client.speedmode, 6399)
local cp, title = G.checkpoint()
G.phase("start", "title=" .. tostring(title))

local STATE = os.getenv("SLINK_STATE") or "E:/Howard/Bizhawk/GBA/State/slink_prebattle.State"
local ok = pcall(savestate.load, STATE)
if not ok then G.finish(false, "savestate load failed: " .. STATE) end
G.idle(30)

local OUTCOME = 0x02023E8A        -- radical_red BATTLE_OUTCOME_ADDR (data/games/gen3_rr/profile.json)
local PARTY_COUNT = 0x02024029
local CTRL, ACTION_MENU = 0x03004FE0, 0x0802E439   -- duo-precedent constants (scenario_explode.lua)
local function at_menu() return memory.read_u32_le(CTRL) == ACTION_MENU end
local function status(tag)
    G.phase(tag, string.format("frame=%d outcome=%d party=%d menu=%s", emu.framecount(),
        memory.read_u8(OUTCOME), memory.read_u8(PARTY_COUNT), tostring(at_menu())))
end

local script = os.getenv("SLINK_BAG_SCRIPT") or "menu,shot,Right,wait16,A,wait90,shot"
local n = 0
for raw in script:gmatch("[^,]+") do
    local step = raw:match("^%s*(.-)%s*$")
    if step == "shot" then
        n = n + 1
        pcall(client.screenshot, WT .. string.format("/patch/build/gen3_bag_%02d.png", n))
        status("shot" .. n)
    elseif step == "menu" then
        local up = false
        for _ = 1, 3000 do
            if at_menu() then up = true; break end
            if emu.framecount() % 2 == 0 then joypad.set({ A = true }) else joypad.set({}) end
            G.advance()
        end
        joypad.set({})
        status(up and "menu-up" or "menu-timeout")
    elseif step:match("^wait(%d+)$") then
        G.idle(tonumber(step:match("^wait(%d+)$")))
    else
        for _ = 1, 3 do joypad.set({ [step] = true }); G.advance() end
        G.idle(13)
        status("press-" .. step)
    end
end
G.finish(true, string.format("script done; outcome=%d", memory.read_u8(OUTCOME)))
