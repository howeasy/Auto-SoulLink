-- mkstates_gen3_tutorials.lua — the FRLG tutorial-battle savestates (card 2B-TUTORIAL-STATES,
-- plan docs/gen3/research/g4_2b_matrix_plan_2026-09-23.md §3 R-T/R-O/P), ONE normal-input
-- session per title from tests/fixtures/gen3/<title>_party_town.sav. Launched by
-- tools/mkstates_gen3_tutorials.py; result file patch/build/mkstates_gen3_tutorials_result.txt.
--
--   cold boot -> CONTINUE, Viridian 3.1 (24,39), var 0x4051 == 1, no TEACHY TV
--   walk U8 L2 U22 to (22,9) (map/tile verified per segment), U1 onto (22,8)
--   slink_oldman.State    the naturally entered old-man demo: gMain.inBattle, gBattleTypeFlags
--                         has OLD_MAN_TUTORIAL (bit 9) and NOT POKEDUDE, and
--                         gBattlerControllerFuncs[0] lies in battle_controller_oak_old_man.o
--   the scene finishes:   var 0x4051 == 2 AND item 366 in the key pocket, field quiet
--   START -> BAG -> KEY ITEMS -> TEACHY TV -> USE -> first list row (TTVSCR_BATTLE)
--   slink_pokedude.State  gBattleTypeFlags has POKEDUDE (bit 16) and NOT OLD_MAN, and
--                         gBattlerControllerFuncs[0] lies in battle_controller_pokedude.o
--
-- INPUT POLICY. Only A, Start and the d-pad are ever pressed. NEVER B: BattleMainCB2 quits a
-- Pokedude battle on JOY_HELD(B_BUTTON) (pret battle_main.c:1455-1461) and the Teachy TV host
-- text aborts on JOY_NEW(B_BUTTON) (teachy_tv.c:811-822). No memory write, no savestate load,
-- no game-data staging: every state is reached by the game's own scripts.
--
-- pret pokefirered c75f3523 facts (re-derived for this card):
--   data/maps/ViridianCity/map.json  coord_events (22,8) TutorialTriggerRight and (20,8) ...Left
--       when VAR_MAP_SCENE_VIRIDIAN_CITY_OLD_MAN == 1; (22,11) RoadBlocked only when it is 0.
--       Water-only wild table (src/data/wild_encounters.json), so a land walk never battles.
--   ViridianCity/scripts.inc:17-21   scene 1 parks LOCALID_TUTORIAL_MAN at (21,8), LOOK_AROUND
--   ViridianCity/scripts.inc:213-237 TriggerRight -> DoTutorialBattle: msgbox, special
--       StartOldManTutorialBattle, waitstate, msgbox, setvar 0x4051 2, giveitem ITEM_TEACHY_TV
--   include/constants/vars.h:133 (0x4051), items.h:438 (ITEM_TEACHY_TV 366),
--   battle.h:56 (OLD_MAN_TUTORIAL 1<<9), :64 (POKEDUDE 1<<16)
--   battle_setup.c:301-307 gBattleTypeFlags = BATTLE_TYPE_OLD_MAN_TUTORIAL
--   battle_controllers.c:84-107 OLD_MAN -> SetControllerToOakOrOldMan, POKEDUDE -> ...Pokedude
--   battle_controller_pokedude.c:2675-2683 InitPokedudePartyAndOpponent: flags = POKEDUDE only
--   start_menu.c:40-50 STARTMENU_BAG == 2; item_menu.c:345-348 the field bag is OPEN_BAG_LAST
--       (pocket remembered: steer it), :1124-1145 Left/Right switch pockets,
--       :1070-1095 A sets gSpecialVar_ItemId from the pocket slot under the cursor,
--       :1392-1406 key-pocket context menu {USE, REGISTER|DESELECT, CANCEL}, cursor 0 (:1431)
--   item_use.c:518-545 FieldUseFunc_TeachyTv (from the bag) -> InitTeachyTvController(0, ...)
--   teachy_tv.c:420-429 mode 0 zeroes scrollOffset/selectedRow; :168-223 TTVSCR_BATTLE is row 0
--       of both lists; :713-751 the list reads input only while the fade is idle and on A moves
--       the task to TeachyTvRenderMsgAndSwitchClusterFuncs with whichScript = row index;
--       :1172-1201 TeachyTvPrepBattle -> InitPokedudePartyAndOpponent -> CB2_InitBattle
-- Addresses: data/gen3/pret/poke{firered,leafgreen}.{sym,map}; tests/unit/test_gen3_tutorial_states.py
-- checks every one below against both titles.

local M = {}

-- WRAM (identical in both .sym files)
M.BATTLE_TYPE_FLAGS_ADDR = 0x02022B4C    -- gBattleTypeFlags
M.BATTLER_CTRL_ADDR      = 0x03004FE0    -- gBattlerControllerFuncs[0]
M.TTV_STATIC_ADDR        = 0x0203F444    -- teachy_tv.c sStaticResources: whichScript +5,
M.TTV_WHICH_OFF, M.TTV_SCROLL_OFF, M.TTV_ROW_OFF = 5, 6, 8   -- scrollOffset +6, selectedRow +8
M.CONTEXT_ITEMS_PTR_ADDR = 0x0203AD24    -- item_menu.c sContextMenuItemsPtr
M.START_MENU_CURSOR_ADDR = 0x020370F4    -- sStartMenuCursorPos
M.START_MENU_COUNT_ADDR  = 0x020370F5    -- sNumStartMenuItems
M.START_MENU_ORDER_ADDR  = 0x020370F6    -- sStartMenuOrder
M.START_MENU_WINDOW_ADDR = 0x0203ABE0    -- sStartMenuWindowId (0xFF = closed)

M.SB1_VARS_OFF = 0x1000                  -- global.h:791
M.VAR_OLD_MAN = 0x4051
M.ITEM_TEACHY_TV = 366
M.OLD_MAN = 0x200
M.POKEDUDE = 0x10000
M.STARTMENU_BAG = 2
M.POCKET_KEY_ITEMS = 1                   -- OPEN_BAG_KEYITEMS == gBagMenuState.pocket index
M.ITEMMENUACTION_USE = 0                 -- include/constants/item_menu.h:22
M.TTVSCR_BATTLE = 0                      -- include/teachy_tv.h:6
M.HOLD = 30                              -- witness frames before a save

-- per-title .text: controller object spans [lo, hi) from the linker maps, and Thumb (|1)
-- function pointers as gTasks[].func / gMain.callback2 store them
M.TITLES = {
    firered = {
        oak_old_man = { 0x080E75AC, 0x080EB658 }, pokedude = { 0x081560A0, 0x0815A008 },
        TASK_FIELD_ITEM_CONTEXT = 0x08109BE5,   -- Task_FieldItemContextMenuHandleInput
        CB2_TEACHY_TV = 0x0815AC2D,             -- TeachyTvMainCallback
        TASK_TTV_LIST = 0x0815B2C1,             -- TeachyTvOptionListController
        TASK_TTV_MSG = 0x0815B4ED,              -- TeachyTvRenderMsgAndSwitchClusterFuncs
    },
    leafgreen = {
        oak_old_man = { 0x080E7584, 0x080EB630 }, pokedude = { 0x0815607C, 0x08159FE4 },
        TASK_FIELD_ITEM_CONTEXT = 0x08109BBD,
        CB2_TEACHY_TV = 0x0815AC09,
        TASK_TTV_LIST = 0x0815B29D,
        TASK_TTV_MSG = 0x0815B4C9,
    },
}

-- R-T first segment (tools/gba_map.py over both ROMs: every tile collision 0, behaviour 0)
M.START = { 24, 39 }
M.SEGMENTS = { { "Up", 8, { 24, 31 } }, { "Left", 2, { 22, 31 } }, { "Up", 22, { 22, 9 } } }
M.TRIGGER = { 22, 8 }

-- ── pure witnesses (reads only; the unit test drives these over fake RAM) ─────────────────────

local function key_slot(sb1, item, off, count)
    for slot = 0, count - 1 do
        if memory.read_u16_le(sb1 + off + slot * 4) == item then return slot end
    end
    return nil
end

--- (var 0x4051, key-pocket slot of TEACHY TV or nil). `pocket` = { off, count } from
--- gen3_scripted_play's SB1_KEYITEMS_POCKET_OFFSET / BAG_KEYITEMS_COUNT.
function M.scene(sb1, pocket)
    return memory.read_u16_le(sb1 + M.SB1_VARS_OFF + (M.VAR_OLD_MAN - 0x4000) * 2),
           key_slot(sb1, M.ITEM_TEACHY_TV, pocket[1], pocket[2])
end

function M.before_scene(sb1, pocket)
    local var, tv = M.scene(sb1, pocket)
    if var ~= 1 then return false, "var 0x4051 is " .. var .. ", the tutorial needs 1" end
    if tv then return false, "TEACHY TV is already in key slot " .. tv end
    return true
end

--- Scene 2 needs BOTH the var and the item: var 2 without the TV is not a finished scene.
function M.after_scene(sb1, pocket)
    local var, tv = M.scene(sb1, pocket)
    if var ~= 2 then return false, "var 0x4051 is " .. var .. ", not 2" end
    if not tv then return false, "var 0x4051 == 2 but no TEACHY TV(366) in the key pocket" end
    return true, tv
end

--- kind "oak_old_man" | "pokedude": in battle, the kind's type bit set, the other kind's bit
--- clear, and battler 0's controller inside that kind's controller object.
function M.battle_witness(kind, T, in_battle)
    local flags = memory.read_u32_le(M.BATTLE_TYPE_FLAGS_ADDR)
    local ctrl = memory.read_u32_le(M.BATTLER_CTRL_ADDR)
    local want, other = M.OLD_MAN, M.POKEDUDE
    if kind == "pokedude" then want, other = M.POKEDUDE, M.OLD_MAN end
    local span = T[kind]
    local detail = string.format("in_battle=%s flags=%08X ctrl0=%08X", tostring(in_battle), flags, ctrl)
    if not in_battle then return false, detail .. " (not in battle)" end
    if flags & want == 0 or flags & other ~= 0 then return false, detail .. " (wrong type flags)" end
    if ctrl < span[1] or ctrl >= span[2] then
        return false, string.format("%s (controller outside %s [%08X,%08X))", detail, kind, span[1], span[2])
    end
    return true, detail
end

-- ── the run (BizHawk only) ───────────────────────────────────────────────────────────────────

local G   -- gen3_boot_check, bound by run()

local function run()
    local WT = assert(SLINK_ROOT or os.getenv("SLINK_ROOT"), "SLINK_ROOT unset — run via tools/mkstates_gen3_tutorials.py")
    local DIR = assert(os.getenv("SLINK_STATE_DIR"), "SLINK_STATE_DIR unset")
    G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")
    local SP = dofile(WT .. "/lua/tests/gen3_scripted_play.lua")
    local play = SP.play
    local POCKET = { SP.SB1_KEYITEMS_POCKET_OFFSET, SP.BAG_KEYITEMS_COUNT }

    G.open("mkstates_gen3_tutorials")   -- patch/build/mkstates_gen3_tutorials_result.txt
    pcall(client.speedmode, 6399)
    G.budget = 60000
    local cp, title = G.checkpoint()
    local T = M.TITLES[title]
    if not T then return G.finish(false, "no tutorial spans for title " .. tostring(title)) end
    local S = dofile(WT .. "/lua/tests/gen3_title_syms.lua").for_title(title)
    G.phase("start", "title=" .. title .. " dir=" .. DIR)

    local function fail(msg) G.shot("stuck"); G.finish(false, msg) end
    local function sb1() return memory.read_u32_le(math.floor(cp.pointers.gSaveBlock1Ptr.address)) end
    local function in_battle() return not G.pred_ok(cp, "in_battle") end
    local function quiet()
        for _, p in ipairs({ "callback2", "in_battle", "field_controls_locked",
                             "script_context_status", "palette_fade_active" }) do
            if not G.pred_ok(cp, p) then return false end
        end
        return true
    end
    local function task_on(fn)
        for i = 0, 15 do
            local base = SP.TASKS_BASE + i * 40
            if memory.read_u8(base + 4) ~= 0 and memory.read_u32_le(base) == fn then return true end
        end
        return false
    end
    local function cb2() return memory.read_u32_le(SP.GMAIN_CALLBACK2_ADDR) end
    --- Wait up to `frames` for pred(); with `a`, pulse A (never B) on the 16-frame cadence.
    local function await(pred, frames, a)
        for i = 1, frames do
            if pred() then joypad.set({}); return true end
            joypad.set((a and i % 16 == 8) and { A = true } or {})
            G.advance()
        end
        joypad.set({})
        return pred()
    end
    --- pred() true for M.HOLD consecutive idle frames within `frames`; returns ok, last detail.
    local function hold(pred, frames)
        local n, ok, why = 0, false, nil
        joypad.set({})
        for _ = 1, frames do
            ok, why = pred()
            n = ok and n + 1 or 0
            if n >= M.HOLD then return true, why end
            G.advance()
        end
        return false, why
    end
    local function save(name, detail)
        local ok, err = pcall(savestate.save, DIR .. "/" .. name)
        if not ok then return fail("savestate.save " .. name .. ": " .. tostring(err)) end
        G.phase("state-saved", name .. " " .. detail)
    end
    local function at(x, y)
        local g, n = G.map(cp)
        local px, py = G.pos(cp)
        return g == 3 and n == 1 and px == x and py == y,
            string.format("at %d.%d (%d,%d), want 3.1 (%d,%d)", g, n, px, py, x, y)
    end

    -- boot, settle (mkstates_gen3.lua's first-run lesson: CONTINUE still locks the field)
    if not G.boot_to_field(cp, 9000) then return fail("never reached the field") end
    if not hold(quiet, 3000) then return fail("field never settled after CONTINUE") end
    local ok, why = at(M.START[1], M.START[2])
    if not ok then return fail("start: " .. why) end
    ok, why = M.before_scene(sb1(), POCKET)
    if not ok then return fail("precondition: " .. why) end

    -- R-T segment: U8 L2 U22, then U1 onto the trigger
    local map0 = play.map(cp)
    for _, seg in ipairs(M.SEGMENTS) do
        for i = 1, seg[2] do
            local moved, stall = play.step(cp, seg[1], map0, true, false)
            if not moved then
                return fail(string.format("%s %d/%d: %s at %s", seg[1], i, seg[2], tostring(stall), play.at(cp)))
            end
        end
        play.wait_at(cp, seg[3][1], seg[3][2], 120)
        ok, why = at(seg[3][1], seg[3][2])
        if not ok then return fail("segment " .. seg[1] .. seg[2] .. ": " .. why) end
        G.phase("segment", why)
    end
    if not play.step(cp, "Up", map0, true, false) then return fail("trigger step: " .. play.at(cp)) end
    ok, why = at(M.TRIGGER[1], M.TRIGGER[2])
    if not ok then return fail("trigger: " .. why) end

    -- the demo battle: A through ShowYouHowToCatchMons until the battle is up, then witness
    if not await(in_battle, 3000, true) then return fail("the old-man battle never started") end
    ok, why = hold(function() return M.battle_witness("oak_old_man", T, in_battle()) end, 600)
    if not ok then return fail("old-man witness: " .. tostring(why)) end
    save("slink_oldman.State", why)

    -- let the scene finish: A (never B) until var 2 + TV + a quiet field, held
    local function done() return quiet() and (M.after_scene(sb1(), POCKET)) end
    local settled = false
    for _ = 1, 3 do
        if await(done, 6000, true) and hold(done, 300) then settled = true; break end
    end
    if not settled then
        local _, reason = M.after_scene(sb1(), POCKET)
        return fail("scene 2: " .. tostring(reason or "field never quiet"))
    end
    local _, tv_slot = M.after_scene(sb1(), POCKET)
    G.phase("teachy-tv", string.format("var 0x4051=2 key slot %d", tv_slot))

    -- START -> BAG (row read from sStartMenuOrder, input gated like gen3_boot_check.save_via_menu)
    local input_ready = G.start_menu_witness(title)
    if not input_ready then return fail("no START menu witness for " .. title) end
    local function menu_open() return memory.read_u8(M.START_MENU_WINDOW_ADDR) ~= 0xFF end
    for _ = 1, 5 do
        if not await(function() return G.pred_ok(cp, "field_controls_locked") end, 300) then
            return fail("field controls never freed before START")
        end
        G.tap("Start", 3, 0)
        if await(menu_open, 120) then break end
    end
    if not await(input_ready, 300) then return fail("START menu never took input") end
    local row
    for i = 0, memory.read_u8(M.START_MENU_COUNT_ADDR) - 1 do
        if memory.read_u8(M.START_MENU_ORDER_ADDR + i) == M.STARTMENU_BAG then row = i end
    end
    if not row then return fail("no BAG row in sStartMenuOrder") end
    for _ = 1, 12 do
        local c = memory.read_u8(M.START_MENU_CURSOR_ADDR)
        if c == row then break end
        G.tap(c < row and "Down" or "Up", 3, 13)
    end
    if memory.read_u8(M.START_MENU_CURSOR_ADDR) ~= row then return fail("START cursor never reached BAG") end
    G.tap("A", 3, 0)

    local BAG = SP.BAG_MENU_STATE_ADDR
    local function pocket() return memory.read_u16_le(BAG + SP.BAG_POCKET_OFF) end
    local function bag_ready()
        return cb2() == SP.CB2_BAG_MENU_RUN and G.pred_ok(cp, "palette_fade_active")
            and task_on(SP.TASK_BAG_MENU_HANDLE_INPUT) and not task_on(SP.TASK_ANIMATE_WIN0V)
    end
    if not await(bag_ready, 900) then return fail("the field bag never took input") end
    for _ = 1, 4 do
        local p = pocket()
        if p == M.POCKET_KEY_ITEMS then break end
        G.tap(p < M.POCKET_KEY_ITEMS and "Right" or "Left", 3, 0)
        await(function() return pocket() ~= p end, 60)
        await(bag_ready, 240)
    end
    if pocket() ~= M.POCKET_KEY_ITEMS then return fail("bag pocket never reached KEY ITEMS: " .. pocket()) end
    local function cursor_slot()
        local k = M.POCKET_KEY_ITEMS * 2
        return memory.read_u16_le(BAG + SP.BAG_ITEMS_ABOVE_OFF + k) + memory.read_u16_le(BAG + SP.BAG_CURSOR_POS_OFF + k)
    end
    for _ = 1, 32 do
        local s = cursor_slot()
        if s == tv_slot then break end
        G.tap(s < tv_slot and "Down" or "Up", 3, 0)
        await(bag_ready, 240)
    end
    local item = memory.read_u16_le(sb1() + POCKET[1] + cursor_slot() * 4)
    if item ~= M.ITEM_TEACHY_TV then return fail("key-pocket cursor slot holds item " .. item) end
    G.tap("A", 3, 0)
    if not await(function()
        return memory.read_u16_le(SP.SPECIAL_VAR_ITEM_ID_ADDR) == M.ITEM_TEACHY_TV and task_on(T.TASK_FIELD_ITEM_CONTEXT)
    end, 120) then return fail("the TEACHY TV context menu never opened") end
    G.idle(13)
    local mc = memory.read_s8(S.PC_MENU_BASE + 2)   -- sMenu.cursorPos (menu.c:9-23)
    local action = memory.read_u8(memory.read_u32_le(M.CONTEXT_ITEMS_PTR_ADDR) + mc)
    if action ~= M.ITEMMENUACTION_USE then
        return fail(string.format("context cursor %d is action %d, not USE", mc, action))
    end
    G.tap("A", 3, 0)

    -- Teachy TV list: row 0 == TTVSCR_BATTLE, read back before and after the A
    local S0 = M.TTV_STATIC_ADDR
    if not await(function()
        return cb2() == T.CB2_TEACHY_TV and task_on(T.TASK_TTV_LIST) and G.pred_ok(cp, "palette_fade_active")
    end, 900) then return fail("the Teachy TV list never took input") end
    G.idle(13)
    local idx = memory.read_u16_le(S0 + M.TTV_SCROLL_OFF) + memory.read_u16_le(S0 + M.TTV_ROW_OFF)
    if idx ~= M.TTVSCR_BATTLE then return fail("Teachy TV list cursor on row " .. idx) end
    G.tap("A", 3, 0)
    if not await(function()
        return task_on(T.TASK_TTV_MSG) and memory.read_u8(S0 + M.TTV_WHICH_OFF) == M.TTVSCR_BATTLE
    end, 120) then return fail("TTVSCR_BATTLE was not chosen") end
    G.phase("ttv-battle", "row 0 chosen")

    -- host text (A only) into the Pokedude demo, then witness with no input at all
    if not await(in_battle, 6000, true) then return fail("the Pokedude battle never started") end
    ok, why = hold(function() return M.battle_witness("pokedude", T, in_battle()) end, 600)
    if not ok then return fail("Pokedude witness: " .. tostring(why)) end
    save("slink_pokedude.State", why)
    G.finish(true, "tutorial states in " .. DIR)
end

M.run = run
if (debug.getinfo(1, "S").source or "") == "main" then
    local ok, err = pcall(run)
    if not ok and G then G.shot("stuck"); G.finish(false, "uncaught Lua error: " .. tostring(err)) end
end
return M
