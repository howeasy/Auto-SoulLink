-- _ref_screens.lua — capture RR's OWN menu screens as visual reference for the §6 redesign.
-- Scratch tool, not a gate: it asserts nothing, it just drives the start menu and screenshots.
--   python tools/run_gate.py lua/tests/_ref_screens.lua --timeout 240
local SDIR = "E:/Howard/Bizhawk/GBA/State"
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
local MB = dofile(WT .. "/lua/mailbox.lua")
pcall(memory.usememorydomain, "System Bus")
pcall(function() client.speedmode(400) end)

local function boot()
    pcall(savestate.load, SDIR .. "/slink_overworld.State"); emu.frameadvance()
    for _ = 1, 240 do emu.frameadvance(); if MB.present() then break end end
end
local function tap(btn, frames)
    for f = 1, (frames or 30) do
        joypad.set(f <= 3 and { [btn] = true } or {}); emu.frameadvance()
    end
end
local function shot(name)
    for _ = 1, 40 do emu.frameadvance() end
    pcall(function() client.screenshot(WT .. "/patch/build/ref_" .. name .. ".png") end)
end

-- row order on this save: 0 Pokemon, 1 Bag, 2 <player> (trainer card), 3 Save, 4 Option, 5 Exit
local function menu(down)
    boot(); tap("Start", 60)
    for _ = 1, down do tap("Down", 12) end
    tap("A", 60)
end

menu(0); shot("party")                     -- the party menu: the densest real list screen
tap("A", 50); shot("party_actions")        -- its action submenu (SUMMARY / SWITCH / ITEM / CANCEL)
tap("A", 90); shot("summary")              -- the POKEMON summary page
tap("Right", 60); shot("summary2")         -- its second page

menu(2); shot("trainercard")               -- the trainer card: a real full-screen info panel

menu(1); shot("bag")                       -- the bag: header + list + description

menu(4); shot("options")                   -- OPTIONS: label/value rows, and the frame picker

local f = io.open(WT .. "/patch/build/ref_result.txt", "w")
f:write("RESULT: PASS\n"); f:close()
client.exit()
