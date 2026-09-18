-- Probe: on pureRGB, cancelling the MOVE menu re-enters MainInBattleLoop.loopNoMoveSelected (below
-- the HP check), so a force-faint written there never faints. Test whether zeroing HP at that hook
-- and moving PC back to the loop head (+6 = call ReadPlayerMonCurHPAndStatus) faints the battler.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gate.lua")
local t = G.start("probe_gen1_loop_reentry")
local fmt = string.format
local ram, F = t.parts.profile.ram, t.facts
local sym = {}
for line in io.lines(t.ROOT .. "/data/purergb/pokered.sym") do
    local bank, address, name = line:match("^(%x+):(%x+) (%S+)$")
    if address then sym[name] = tonumber(address, 16) end
end
local rom = t.parts.profile.rom
local Driver = dofile(t.ROOT .. "/lua/tests/gen1_battle_driver.lua"); Driver.with_facts(F)
local function rd(a) return memory.read_u8(a, "System Bus") end
local function step_buttons(b) t.step(b); t.client:frame_end() end
local driver = Driver.new({
    step = function(b) step_buttons(b) end, u8 = rd, facts = F,
    sites = { display_battle_menu = rom.DisplayBattleMenu.addr, move_selection_menu = rom.MoveSelectionMenu.addr,
              select_enemy_move = rom.SelectEnemyMove.addr, execute_player_move = rom.ExecutePlayerMove.addr,
              execute_enemy_move = rom.ExecuteEnemyMove.addr },
    addresses = { wTopMenuItemX = sym.wTopMenuItemX, wTopMenuItemY = sym.wTopMenuItemY,
                  wCurrentMenuItem = sym.wCurrentMenuItem, wMaxMenuItem = sym.wMaxMenuItem,
                  wMenuWatchedKeys = sym.wMenuWatchedKeys, wIsInBattle = sym.wIsInBattle,
                  wPlayerSelectedMove = sym.wPlayerSelectedMove,
                  wActionResultOrTookBattleTurn = sym.wActionResultOrTookBattleTurn,
                  hLoadedROMBank = sym.hLoadedROMBank, wListScrollOffset = sym.wListScrollOffset,
                  wPlayerMonNumber = sym.wPlayerMonNumber, wPartyCount = sym.wPartyCount,
                  wBattleMonMoves = sym.wBattleMonMoves, wBattleMonPP = sym.wBattleMonPP,
                  wBattleMonHP = sym.wBattleMonHP, wEnemyMonHP = sym.wEnemyMonHP,
                  wEnemySelectedMove = sym.wEnemySelectedMove, wCurItem = sym.wCurItem,
                  wNumRunAttempts = sym.wNumRunAttempts, hJoyPressed = sym.hJoyPressed },
})
t.online = true
t.client:start()
local got = false
for i = 1, 6000 do
    local dir = (math.floor(i / 24) % 2 == 0) and "Left" or "Right"
    step_buttons({ [dir] = true })
    if rd(ram.wIsInBattle) == 1 then got = true break end
end
t.check("wild battle started", got, fmt("frame %d", t.frame))
local B = F.MENU.BATTLE
local at_menu = false
for i = 1, 1200 do
    local s = driver.state()
    if s.y == B.menu_y and (s.x == B.left_x or s.x == B.right_x) then at_menu = true break end
    step_buttons((i % 16 < 2) and { A = true } or nil)
end
t.check("battle menu shown", at_menu, fmt("frame %d", t.frame))
-- hook the no-move re-entry and the faint handler
local reentry = sym["MainInBattleLoop.loopNoMoveSelected"]; local head6 = sym.MainInBattleLoop + 6
local fainted_hits, reentry_hits, wrote = 0, 0, false
t.log(fmt("reentry=%04X head6=%04X fainted=%04X", reentry, head6, sym.HandlePlayerMonFainted))
event.on_bus_exec(function()
    if rd(sym.hLoadedROMBank) ~= 0x0F then return end
    reentry_hits = reentry_hits + 1
    if not wrote then
        memory.write_u8(sym.wBattleMonHP, 0, "System Bus"); memory.write_u8(sym.wBattleMonHP + 1, 0, "System Bus")
        memory.write_u8(sym.wPlayerSelectedMove, 0xFF, "System Bus")
        emu.setregister("PC", head6)
        wrote = true
    end
end, reentry, "probe-reentry", "System Bus")
event.on_bus_exec(function() if rd(sym.hLoadedROMBank) == 0x0F then fainted_hits = fainted_hits + 1 end end,
                  sym.HandlePlayerMonFainted, "probe-fainted", "System Bus")
t.check("FIGHT chosen", driver.choose("FIGHT").ok)
local Mv = F.MENU.MOVE
local opened = false
for _ = 1, 600 do
    if rd(sym.wTopMenuItemX) == Mv.menu_x and rd(sym.wTopMenuItemY) == Mv.menu_y then opened = true break end
    step_buttons(nil)
end
t.check("move menu open", opened)
for i = 1, 600 do
    step_buttons((i % 16 < 2) and { B = true } or nil)
    if fainted_hits > 0 then break end
end
t.check("reentry hook fired", reentry_hits > 0, tostring(reentry_hits))
t.check("write + PC move performed", wrote)
t.check("HandlePlayerMonFainted reached", fainted_hits > 0, fmt("hits=%d hp=%02X%02X", fainted_hits, rd(sym.wBattleMonHP), rd(sym.wBattleMonHP + 1)))
for _ = 1, 300 do step_buttons(nil) end
local s = driver.state()
t.log(fmt("after: x=%d y=%d cur=%d max=%d watched=%02X inb=%d partyHP1=%02X%02X", s.x, s.y, s.cur, s.max, s.watched, s.in_battle, rd(ram.wPartyMon1HP), rd(ram.wPartyMon1HP + 1)))
t.finish()
