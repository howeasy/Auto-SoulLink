-- probe_movecursor_thunks.lua — re-derive the battle-menu controller thunk addresses for THIS
-- ROM build (ROADMAP §2 explode re-enable prep). The native FORCE_MOVE_SLOT controller-swap
-- depends on RR-version-specific values hardcoded in handlers.c:
--   ACTION_CTRL_A 0x0802E439 / ACTION_CTRL_B 0x0802E3B5 (action-select controllers)
--   MOVE_CTRL_THUNK 0x0802EA11 (move-select / HandleInputChooseMove thunk)
-- Method: load the action-menu and move-menu savestates and read gBattlerControllerFuncs[0..3]
-- (0x03004FE0) live — the engine itself installed the controller, so whatever is in slot 0 IS
-- the address the swap must match. PASS = the live pointers equal the handlers.c constants
-- (Thumb bit included). A FAIL means re-discovery is needed before re-enabling
-- native_battle_control (see the NATIVE EXPLODE/FAINT DISABLED postmortem).
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/movecursor_thunks_result.txt"
local CTRL = 0x03004FE0

local EXPECT = {
    actionmenu = { name = "slink_actionmenu.State", want = { [0x0802E439] = "ACTION_CTRL_A",
                                                            [0x0802E3B5] = "ACTION_CTRL_B" } },
    movemenu   = { name = "slink_movemenu.State",   want = { [0x0802EA11] = "MOVE_CTRL_THUNK" } },
}

local lines, fails = {}, 0
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function check(n, c, e) if not c then fails = fails + 1 end
    log(string.format("  [%s] %s%s", c and "PASS" or "FAIL", n, e and "  " .. e or "")) end
local function finish() log(fails == 0 and "RESULT: PASS" or ("RESULT: FAIL (" .. fails .. ")"))
    local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit() end

pcall(function() client.speedmode(400) end)
pcall(memory.usememorydomain, "System Bus")

for _, key in ipairs({"actionmenu", "movemenu"}) do
    local spec = EXPECT[key]
    local ok = pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/" .. spec.name)
    if not ok then
        check(key .. ": savestate loads", false, spec.name)
    else
        for _ = 1, 10 do emu.frameadvance() end
        local slot0 = memory.read_u32_le(CTRL)
        local all = {}
        for b = 0, 3 do all[#all + 1] = string.format("%08X", memory.read_u32_le(CTRL + b * 4)) end
        log(string.format("%s: gBattlerControllerFuncs = %s", key, table.concat(all, " ")))
        local label = spec.want[slot0]
        check(key .. ": slot-0 controller matches a handlers.c constant", label ~= nil,
              string.format("live=0x%08X%s", slot0,
                  label and (" == " .. label) or "  (NO MATCH — re-discover before re-enable)"))
    end
end
finish()
