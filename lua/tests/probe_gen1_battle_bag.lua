-- Probe (not a gate): on a pure battle fixture, walk into an encounter, choose ITEM and log the
-- list-menu state every 4 frames so the bag geometry can be pinned as a lane fact.
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gate.lua")
local t = G.start("probe_gen1_battle_bag")
local fmt = string.format
local ram, F = t.parts.profile.ram, t.facts
local sym = {}
for line in io.lines(t.ROOT .. "/data/purergb/pokered.sym") do
    local _, address, name = line:match("^(%x+):(%x+) (%S+)$")
    if address then sym[name] = tonumber(address, 16) end
end
local rom = t.parts.profile.rom
local Driver = dofile(t.ROOT .. "/lua/tests/gen1_battle_driver.lua"); Driver.with_facts(F)
local function rd(a) return memory.read_u8(a, "System Bus") end
local pending = nil
local function step_buttons(btns) t.step(btns); t.client:frame_end() end
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
-- pace the grass until a wild battle starts
local got = false
for i = 1, 6000 do
    local dir = (math.floor(i / 24) % 2 == 0) and "Left" or "Right"
    step_buttons({ [dir] = true })
    if rd(ram.wIsInBattle) == 1 then got = true break end
end
t.check("wild battle started", got, fmt("frame %d", t.frame))
-- wait for the battle menu (pressing A through the intro text), like the hunt does
local B = F.MENU.BATTLE
local at_menu = false
for i = 1, 1200 do
    local s = driver.state()
    if s.y == B.menu_y and (s.x == B.left_x or s.x == B.right_x) then at_menu = true break end
    step_buttons((i % 16 < 2) and { A = true } or nil)
end
t.check("battle menu shown", at_menu, fmt("frame %d", t.frame))
local st = driver.state()
t.log(fmt("battle menu state x=%d y=%d cur=%d max=%d watched=%02X", st.x, st.y, st.cur, st.max, st.watched))
t.log(fmt("M.BAG = x=%d y=%d watched=%02X", Driver.BAG.x, Driver.BAG.y, Driver.BAG.watched))
local u = driver.use_item(0, 600)
t.log(fmt("use_item why=%s ok=%s stages=%s", tostring(u.why), tostring(u.ok), t.parts.json.encode(u.stages or {})))
if u.state then t.log(fmt("state x=%d y=%d cur=%d max=%d watched=%02X inb=%d", u.state.x, u.state.y, u.state.cur, u.state.max, u.state.watched, u.state.in_battle)) end
t.finish()
