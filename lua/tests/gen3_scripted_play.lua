-- gen3_scripted_play.lua — scripted natural-play driver for vanilla FireRed (card gen3-P3-C3-5).
--
-- Exercises the engine sites the shadow observer (lua/gen3/shadow_run.lua) must witness, from
-- the committed fixture tests/fixtures/gen3/firered_town.sav (Pallet Town, trainer JONN, EMPTY
-- party — pre-starter; see tests/fixtures/gen3/README.md). Runs an ordered LEGS table; each leg
-- names the site kinds it exercises (docs/gen3_engine_sites.md's 23-kind list) and a pret
-- citation (pokefirered @ c75f352, cloned at .cache/pret/pokefirered).
--
-- WALK PATHS ARE PRECOMPUTED, NOT GUESSED. Every direction list below (the `PATHS` table) was
-- produced OFFLINE by a Python BFS over data/layouts/<Map>/map.bin: each block is a 16-bit LE
-- word, collision = (word >> 10) & 3 (nonzero blocked), object_event tiles blocked, 4-directional
-- BFS from a start tile to a target tile. Door/warp tiles are collision-BLOCKED in the raw data
-- (verified: PalletTown's own house door (6,7) and the lab door (16,13) both read collision=1);
-- the walkable tile is the one just outside/inside it, and the warp fires on a held press INTO
-- the door from that tile — the same "arrow warp" shape gen3_fr_newgame_inputs.lua leg 6 uses.
-- Map-to-map edges without a door (Route1/PalletTown/ViridianCity) are `connections`
-- (data/maps/<Map>/map.json "connections"), crossed by walking off the relevant edge; the
-- landing x on the far side was verified against that map's own collision grid (not assumed).
-- Every PATHS entry below cites the exact start/end tile and the offline BFS command used.
--
-- WHAT REMAINS A REAL RISK (stated, not hidden — see each leg's comment):
--  - The rival battle and any Route 1 wild battle are driven by generic default-cursor mashing
--    (A repeatedly), not a verified move-by-move plan. gActionSelectionCursor resets to 0 each
--    battle (src/battle_controller_player.c) so "press A twice" IS a pinned FIGHT->move-slot-1
--    selection; anything the wild/rival side does in response is not controlled.
--  - Opening the BAG from the action menu is pinned (Right toggles cursor bit0 to
--    B_ACTION_USE_ITEM, src/battle_controller_player.c:248-253); the BAG's own pocket-tab and
--    item-list navigation to POKE BALL is ALSO now pinned (card gen3-P3-C3-23,
--    throw_pokeball_from_bag below): gBagMenuState.pocket is read and steered (never assumed to
--    start at ITEMS(0) — GoToBagMenu's OPEN_BAG_LAST leaves it exactly where it was last left,
--    item_menu.c:307-343), the plaintext bag-slot item id is checked before the selecting A, and
--    gSpecialVar_ItemId is checked after. What remains unverified is only that this sequence
--    actually plays out on real hardware/BizHawk — the coordinator's own lane run, not this file.
--  - The Oak "Pokedex scene" after delivering the parcel is almost entirely NPC `applymovement`
--    (the player only appears to walk when the script itself moves them — the ApproachCounter/
--    dex-scene movements are scripted, not driven by joypad input at all); this driver only
--    mashes A to clear message boxes and waits for the engine to hand control back.
--
-- RESUME: SLINK_GEN3_PLAY_FROM=<leg name> skips every leg before it, assuming the save state
-- those earlier legs would have left is already loaded — the coordinator's job, not this
-- script's.
--
-- Environment: SLINK_ROOT, SLINK_GEN3_CHECKPOINT, SLINK_GEN3_TITLE (see gen3_boot_check.lua),
-- SLINK_GEN3_PLAY_FROM (optional).

local WT = SLINK_ROOT or os.getenv("SLINK_ROOT")
assert(WT, "SLINK_ROOT unset — launch via the gen3 fixture/gate tooling")
local G = dofile(WT .. "/lua/tests/gen3_boot_check.lua")
local PL = dofile(WT .. "/lua/tests/playlib.lua")
local Reads = dofile(WT .. "/lua/gen3/reads.lua")
local JSON = dofile(WT .. "/lua/json_codec.lua")
local Syms = dofile(WT .. "/lua/tests/gen3_title_syms.lua")

-- TITLE (card C4-LG): a SLINK_GEN3_TITLE GLOBAL (the same "global, else env" shape SLINK_ROOT
-- uses two lines up — a duo driver sets globals, not process env, per BizHawk instance) or env
-- var, defaulting to "firered" so every existing caller that never set either keeps the exact
-- byte-for-byte FR behaviour this file always had. Syms.for_title refuses loudly only for an
-- unrecognized title; an entry radical_red has no proof for (card C4-LG2) is simply absent from
-- S, so a helper that needs it fails where it is actually used, never here at load. The
-- story-only half (LEGS/PATHS/DEST/verify_starter/verify_rival) is guarded in run() below.
local TITLE = SLINK_GEN3_TITLE or os.getenv("SLINK_GEN3_TITLE")
if not TITLE or TITLE == "" then TITLE = "firered" end
local S = Syms.for_title(TITLE)

-- PROFILE PACK (card C4-LG2, extended E2-PLAY-PREP): each title's profile.json lives under
-- its own data/games/gen3_<pack> directory (same split duo_gen3_main.lua already makes for its
-- own pack/checkpoint reads). Emerald is a separate pret decomp (data/games/gen3_emerald),
-- neither FR/LG's pokefirered profile nor RR's hand-patched one.
local PROFILE_PACK_BY_TITLE = { firered = "gen3_frlg", leafgreen = "gen3_frlg",
                                 radical_red = "gen3_rr", emerald = "gen3_emerald" }
local PROFILE_PACK = assert(PROFILE_PACK_BY_TITLE[TITLE],
    "gen3_scripted_play: no profile pack for title " .. tostring(TITLE))
local profile_file = assert(io.open(WT .. "/data/games/" .. PROFILE_PACK .. "/profile.json", "rb"))
local profile = assert(JSON.decode(profile_file:read("a"))).titles[TITLE]
profile_file:close()
assert(profile, "gen3_scripted_play: no profile." .. TITLE .. " in data/games/" .. PROFILE_PACK
             .. "/profile.json")
if TITLE == "radical_red" then
    -- RR/CFRU's box layout is compressed (25 boxes, no BOX_DATA_OFFSET) -- the FR/LG
    -- "uncompressed box layout" invariant below does not apply and must not be asserted here.
    assert(profile.admitted, "radical_red profile is not admitted")
elseif TITLE == "emerald" then
    -- Emerald's own profile (data/games/gen3_emerald/profile.json) matches FR/LG's
    -- uncompressed box layout (BOX_DATA_OFFSET==4, BOXES_PER_STORE==14, same pret PC struct)
    -- but is not yet flagged `admitted` pending its own live gate -- this driver is authored
    -- offline ahead of that gate (card E2-PLAY-PREP), so it checks only the two box-layout
    -- invariants this file's PC legs actually need, not the profile-wide admission flag.
    assert(profile.derived.BOX_DATA_OFFSET == 4 and profile.derived.BOXES_PER_STORE == 14,
           "emerald uncompressed box layout is not admitted")
else
    assert(profile.admitted and not profile.derived.CFRU_NO_ENCRYPT
           and profile.derived.BOX_DATA_OFFSET == 4 and profile.derived.BOXES_PER_STORE == 14,
           TITLE .. " uncompressed box layout is not admitted")
end
local function read_bytes(addr, count)
    local bytes = {}
    for i = 1, count do bytes[i] = memory.read_u8(addr + i - 1) end
    return bytes
end
-- Defer host reads so loading the leg table needs no emulator globals.
local reader = Reads.new(profile, {
    read_u8 = function(a) return memory.read_u8(a) end,
    read_u16 = function(a) return memory.read_u16_le(a) end,
    read_u32 = function(a) return memory.read_u32_le(a) end,
    read_bytes = read_bytes,
})

-- Plaintext (no decrypt needed) RAM observables pinned in lua/games/gen3_frlge.lua's `vanilla`
-- profile table, cited per use below. Title-aware (card C4-LG): every address below comes from
-- S = Syms.for_title(TITLE), verified against both .sym files by test_gen3_title_syms.py. FR
-- and LG land on the identical WRAM address for all of these (same decomp, same struct layout);
-- S exists so a future divergence is caught by the pytest, not discovered live.
local PARTY_COUNT_ADDR    = S.PARTY_COUNT_ADDR     -- gPlayerPartyCount
local BATTLE_OUTCOME_ADDR = S.BATTLE_OUTCOME_ADDR  -- B_OUTCOME_CAUGHT == 7
                                                    -- (pret include/constants/battle.h:82)
local BATTLE_RESULTS_ADDR = S.BATTLE_RESULTS_ADDR  -- gBattleResults; playerFaintCounter @ +0
local B_OUTCOME_CAUGHT = 7
local PARTY_BASE          = S.PARTY_BASE  -- gPlayerParty
local MON_SIZE            = 100
local OFF_HP, OFF_MAXHP   = 0x56, 0x58  -- lua/tests/archive/gen3_old_client/duo_main.lua:26-27
local OFF_PID, OFF_OTID   = 0x00, 0x04  -- lua/tests/archive/gen3_old_client/duo_main.lua:23-24

-- THE ACTION-MENU WITNESS (card gen3-P3-C3-21). FR run 19's coordinator replay showed the wild
-- intro ("Wild RATTATA appeared!" -> "Go! SQUIRTLE!") is long enough to outlast a fixed A-tap
-- clear, so a Right press issued on a timer lands on the still-open intro text and does nothing
-- -- the cursor stays at FIGHT for the mash that follows and the starter fights instead of being
-- thrown a ball. gBattlerControllerFuncs[0] (0x03004FE0, u32; pokefirered.sym:802) reads
-- HandleInputChooseAction (0x0802E438, +1 for the Thumb bit; pokefirered.sym line 1990) exactly
-- when the player's own action menu (src/battle_controller_player.c) is waiting for input --
-- the same address+value probe_gen3_rr_bag.lua's CTRL/ACTION_MENU already uses for the RR duo,
-- which is this same FR symbol (RR is a FR ROM hack). gActionSelectionCursor (0x02023FF8, u8[4]
-- per-battler; pokefirered.sym:146) is 0 FIGHT, 1 BAG, 2 POKeMON, 3 RUN
-- (src/battle_controller_player.c); battler 0 is the player.
local BATTLER_CTRL_ADDR = S.BATTLER_CTRL_ADDR
local HANDLE_INPUT_CHOOSE_ACTION = S.HANDLE_INPUT_CHOOSE_ACTION  -- HandleInputChooseAction | 1
local ACTION_CURSOR_ADDR = S.ACTION_CURSOR_ADDR
local ACTION_FIGHT, ACTION_BAG = 0, 1

local function action_menu_up() return memory.read_u32_le(BATTLER_CTRL_ADDR) == HANDLE_INPUT_CHOOSE_ACTION end
local function action_cursor() return memory.read_u8(ACTION_CURSOR_ADDR) end

-- Whiteout destinations are projected from the saved outdoor checkpoint below.
-- Run 14 landed at Mom (4.0, 8,5); run 24 landed at Viridian's nurse (5.4, 7,4).
-- Neither receipt makes that interior the destination of every subsequent whiteout.

local function battle_outcome() return memory.read_u8(BATTLE_OUTCOME_ADDR) end

--- Slot 0's current and maximum HP -- the heal terminal. Plaintext, like every other reader
--- here (the HP fields sit outside the encrypted substructures).
local function slot0_hp()
    return memory.read_u16_le(PARTY_BASE + OFF_HP), memory.read_u16_le(PARTY_BASE + OFF_MAXHP)
end
local function player_faints() return memory.read_u8(BATTLE_RESULTS_ADDR) end

-- gObjectEvents = 0x02036E38 (pokefirered.sym:205); playlib.obj_pos/obj_facing read it
-- (object 0 = player, currentCoords +0x10/+0x12 stored +7, facing nibble at +0x18).
local OBJ_EVENTS_ADDR = S.OBJ_EVENTS_ADDR

local function int(x) return math.floor(x) end

-- VAR_MAP_SCENE_PALLET_TOWN_PROFESSOR_OAKS_LAB (pret include/constants/vars.h:137) = 0x4055.
-- SaveBlock1.vars[] lives at SB1+0x1000 (pret include/global.h:791), each entry a u16, so this
-- var's byte offset from SaveBlock1 is 0x1000 + (0x4055-0x4000)*2.
local SB1_VARS_OFFSET = 0x1000
local VAR_MAP_SCENE_PALLET_TOWN_PROFESSOR_OAKS_LAB = 0x4055
local LAB_SCENE_VAR_OFFSET = SB1_VARS_OFFSET + (VAR_MAP_SCENE_PALLET_TOWN_PROFESSOR_OAKS_LAB - 0x4000) * 2

--- gSaveBlock1Ptr, dereferenced fresh every call: FR relocates SaveBlock1 on every map load, so
--- nothing here may cache the pointed-to address across frames (gen3_boot_check.lua:118-123's
--- own M.map does the same fresh read). nil while the pointer is not yet a sane EWRAM address.
local function sb1_ptr(cp)
    local ptr = assert(cp.pointers and cp.pointers.gSaveBlock1Ptr, "no gSaveBlock1Ptr")
    local sb1 = memory.read_u32_le(int(ptr.address))
    if sb1 < 0x02000000 or sb1 > 0x02040000 - 0x3D68 or sb1 % 4 ~= 0 then return nil end
    return sb1
end

-- C3-29, pret/pokefirered@c75f352: global.h:392-398,765. gSaveBlock1Ptr is
-- 03005008 (data/gen3/pret/pokefirered.sym:809); lastHealLocation at +0x1C is
-- WarpData: s8 group/num/warpId at +0/+1/+2, padding +3, s16 x/y at +4/+6.
-- This is the OUTDOOR checkpoint, not the whiteout interior! heal_location.c:64-118
-- maps it through src/data/heal_locations.json:3-19 to house 4.0 (8,5) or Center
-- 5.4 (7,4). Freeze the raw WarpData before battle; project only on displacement.
local SB1_LAST_HEAL_OFFSET = 0x1C
local function last_heal_checkpoint(cp)
    local sb1 = sb1_ptr(cp)
    if not sb1 then G.finish(false, "whiteout_heal_pointer: unreadable SaveBlock1"); return end
    local p = sb1 + SB1_LAST_HEAL_OFFSET
    return {group=memory.read_u8(p), num=memory.read_u8(p + 1),
            warp=memory.read_u8(p + 2), x=memory.read_s16_le(p + 4),
            y=memory.read_s16_le(p + 6)}
end

local function whiteout_destination(cp, checkpoint)
    local raw = checkpoint or last_heal_checkpoint(cp)
    if not raw then return nil end
    local group, num, warp, x, y = raw.group, raw.num, raw.warp, raw.x, raw.y
    if group == 3 and num == 0 and warp == 255 and x == 6 and y == 8 then
        return {group = 4, num = 0, x = 8, y = 5}
    elseif group == 3 and num == 1 and warp == 255 and x == 26 and y == 27 then
        return {group = 5, num = 4, x = 7, y = 4}
    end
    G.finish(false, string.format("whiteout_heal_unsupported: lastHealLocation %d.%d "
             .. "warp=%d (%d,%d)", group, num, warp, x, y))
    return nil
end

local function verify_destination(cp, label, dest)
    -- A warp reports the new map before the exit step off the door tile
    -- (field_fadetransition.c:317-437, Task_ExitDoor / Task_ExitNonAnimDoor): FR runs 25b/25c
    -- read the mart door (36,19) and the lab door (16,13). Wait, bounded, for the player to
    -- rest on the destination; a wrong landing still fails after the budget.
    local stable = 0
    for _ = 1, 120 do
        local g, n = G.map(cp)
        local px, py = G.pos(cp)
        if g == dest.group and n == dest.num and px == dest.x and py == dest.y then
            stable = stable + 1
            if stable >= 4 then break end
        else
            stable = 0
        end
        G.advance()
    end
    local group, num = G.map(cp)
    local x, y = G.pos(cp)
    if group ~= dest.group or num ~= dest.num or x ~= dest.x or y ~= dest.y then
        G.finish(false, string.format("%s: destination_mismatch: expected %d.%d (%d,%d), "
                 .. "got %s.%s (%s,%s)", label, dest.group, dest.num, dest.x, dest.y,
                 tostring(group), tostring(num), tostring(x), tostring(y)))
        return false
    end
    return true
end

-- Exact destinations from data/maps/{PalletTown,Route1,ViridianCity,...}/map.json
-- warp_events/connections + data/maps/map_groups.json. Exterior door exits take
-- one step south (src/field_fadetransition.c:317-402); connection offsets are
-- Pallet<->Route1=0, Route1<->Viridian=12. These are settled input terminals.
local DEST = {
    house_exit = {group=3, num=0, x=6, y=8},
    lab = {group=4, num=3, x=6, y=12},
    lab_exit = {group=3, num=0, x=16, y=14},
    route1_south = {group=3, num=19, x=12, y=39},
    route1_north = {group=3, num=19, x=12, y=0},
    pallet_north = {group=3, num=0, x=12, y=0},
    viridian_south = {group=3, num=1, x=24, y=39},
    mart = {group=5, num=3, x=4, y=7},
    mart_exit = {group=3, num=1, x=36, y=20},
    center = {group=5, num=4, x=7, y=8},
    center_exit = {group=3, num=1, x=26, y=27},
}

--- The lab scene var, read through gSaveBlock1Ptr the way G.map/G.pos do: -1 while the pointer
--- is not yet a sane EWRAM address.
local function lab_scene_var(cp)
    local sb1 = sb1_ptr(cp)
    if not sb1 then return -1 end
    return memory.read_u16_le(sb1 + LAB_SCENE_VAR_OFFSET)
end

local function verify_starter()
    local mons, why = reader.read_party()
    local mon = mons and mons[1]
    -- scripts.inc:1092-1129 chooses Squirtle (species.h:14: 7), then givemon.
    if not mons or #mons ~= 1 or not mon or mon.species ~= 7 or mon.has_species ~= 1
       or mon.is_egg ~= 0 or mon.is_bad_egg ~= 0 or not mon.checksum_ok then
        G.finish(false, "starter_species: party slot 0 must be a valid Squirtle (7): "
                 .. tostring(why or (mon and mon.species)))
        return false
    end
end

local function flag_set(cp, id)
    local sb1 = sb1_ptr(cp)
    if not sb1 then return false end
    return (memory.read_u8(sb1 + 0xEE0 + id // 8) & (1 << (id % 8))) ~= 0
end

local function verify_rival(cp, outcome)
    -- battle.h:76-77; scripts.inc:467-482 sets scene=4 and flag 0x258 on BOTH
    -- win and loss (flags.h:625). Losing the tutorial is valid; run/catch is not.
    if outcome ~= 1 and outcome ~= 2 then
        G.finish(false, "rival_outcome: expected WON(1) or LOST(2), got " .. tostring(outcome))
        return false
    end
    if not flag_set(cp, 0x258) or lab_scene_var(cp) ~= 4 then
        G.finish(false, "rival_terminal: FLAG_BEAT_RIVAL_IN_OAKS_LAB and lab scene 4 required")
        return false
    end
end

-- THE BAG WITNESS (card gen3-P3-C3-23). CB2_BagMenuFromBattle (src/item_menu.c:350-353) calls
-- GoToBagMenu(ITEMMENULOCATION_BATTLE, OPEN_BAG_LAST, ...); OPEN_BAG_LAST (3) matches none of
-- the three pocket constants GoToBagMenu checks before overwriting gBagMenuState.pocket
-- (item_menu.c:337-338: `if (pocket == OPEN_BAG_ITEMS || ... OPEN_BAG_POKEBALLS) ...`), so the
-- pocket is left exactly where it was last REMEMBERED, not reset — this file must read and
-- steer it, never assume ITEMS(0). gBagMenuState (pokefirered.sym:440, 0x0203acfc, size 0x14)
-- is include/item_menu.h's struct BagStruct { MainCallback bagCallback; u8 location;
-- bool8 bagOpen; u16 pocket; u16 itemsAbove[NUM_BAG_POCKETS_NO_CASES];
-- u16 cursorPos[NUM_BAG_POCKETS_NO_CASES]; } — u32 @ +0x00, u8 @ +0x04, u8 @ +0x05, u16 @ +0x06,
-- u16[3] @ +0x08, u16[3] @ +0x0E, totalling 0x14 (matches the symbol's own size).
-- NUM_BAG_POCKETS_NO_CASES == 3 (include/constants/global.h:56); OPEN_BAG_ITEMS/KEYITEMS/
-- POKEBALLS == 0/1/2 (include/constants/item_menu.h:4-7) index both arrays directly and ARE
-- gBagMenuState.pocket's own values (item_menu.c:1379,1388-1416 switch on them raw).
--
-- LoadBagMenuGraphics' load state machine (src/item_menu.c:384-506) keeps gMain.callback2 ==
-- CB2_OpenBagMenu across many frames and only calls SetMainCallback2(CB2_BagMenuRun)
-- (item_menu.c:502, pokefirered.sym:10170 0x08107ee0) once loading finishes and the input task
-- already exists (case 14, item_menu.c:469: CreateBagInputHandlerTask) — gMain.callback2 ==
-- CB2_BagMenuRun is therefore "the bag is up and reading Left/Right/A", the same callback2-
-- witness shape used throughout this codebase (gMain @ pokefirered.sym:745 0x030030f0,
-- .callback2 @ +0x04 per include/main.h:14-15).
local GMAIN_CALLBACK2_ADDR = S.GMAIN_CALLBACK2_ADDR  -- gMain.callback2
-- pret/pokefirered@c75f352: pokefirered.sym:507,829,10991,11025,11043,11149.
-- include/party_menu.h:8-19: slotId +9, action +0xB; src/party_menu.c:5832-5857
-- opens the mandatory battle menu at slot 0 and :1119-1150 accepts input only
-- while Task_HandleChooseMonInput is active. src/data/party_menu.h:1095 puts
-- SEND OUT at popup row 0 for PARTY_ACTION_SEND_OUT=1.
local CB2_UPDATE_PARTY_MENU = S.CB2_UPDATE_PARTY_MENU
local PARTY_MENU_ADDR = S.PARTY_MENU_ADDR
local PARTY_MENU_SLOT_OFF, PARTY_MENU_ACTION_OFF = 9, 0xB
local PARTY_ACTION_SEND_OUT = 1
local TASKS_BASE, TASK_SIZE = S.TASKS_BASE, 40
local TASK_CHOOSE_MON = S.TASK_CHOOSE_MON
local TASK_RETURN_AFTER_TEXT = S.TASK_RETURN_AFTER_TEXT
local TASK_SELECTION_POPUP = S.TASK_SELECTION_POPUP
local function party_menu_up()
    return memory.read_u32_le(GMAIN_CALLBACK2_ADDR) == CB2_UPDATE_PARTY_MENU
end
local function party_task()
    for slot = 0, 15 do
        local base = TASKS_BASE + slot * TASK_SIZE
        if memory.read_u8(base + 4) ~= 0 then
            local fn = memory.read_u32_le(base)
            if fn == TASK_CHOOSE_MON or fn == TASK_RETURN_AFTER_TEXT
               or fn == TASK_SELECTION_POPUP then return fn end
        end
    end
    return nil
end
--- Generic gTasks[] witness (card C4-LGF2): is the task at `addr` the currently active one?
--- Same func-at-+0/isActive-at-+4 scan party_task() above already uses for its own three
--- addresses, reusable for any single task address -- e.g. TASK_YES_NO_MENU below.
local function task_active(addr)
    if not addr then return false end
    for slot = 0, 15 do
        local base = TASKS_BASE + slot * TASK_SIZE
        if memory.read_u8(base + 4) ~= 0 and memory.read_u32_le(base) == addr then
            return true
        end
    end
    return false
end
-- Task_YesNoMenu_HandleInput (src/script_menu.c): the generic Yes/No confirm task every
-- ScriptMenu_YesNo box uses, including the starter-nickname decline the "starter" leg drives
-- below. No radical_red value: this file's story legs already refuse RR by name.
local TASK_YES_NO_MENU = S.TASK_YES_NO_MENU
local CB2_BAG_MENU_RUN = S.CB2_BAG_MENU_RUN      -- CB2_BagMenuRun | 1 (Thumb bit)
local BAG_MENU_STATE_ADDR = S.BAG_MENU_STATE_ADDR   -- gBagMenuState
local BAG_POCKET_OFF, BAG_ITEMS_ABOVE_OFF, BAG_CURSOR_POS_OFF = 0x06, 0x08, 0x0E
local BAG_POCKET_POKEBALLS = 2           -- OPEN_BAG_POKEBALLS
local SPECIAL_VAR_ITEM_ID_ADDR = S.SPECIAL_VAR_ITEM_ID_ADDR  -- gSpecialVar_ItemId (pokefirered.sym:449)

-- POKe BALL is item 4 (include/constants/items.h:8). Its pocket, SaveBlock1.bagPocket_PokeBalls
-- (include/global.h:781, offset 0x0430 within SaveBlock1: pcItems 0x0298 + bagPocket_Items
-- (42 * 4) + bagPocket_KeyItems (30 * 4) == 0x0430), holds struct ItemSlot { u16 itemId;
-- u16 quantity } entries (include/global.h:400-404, 4 bytes each). Only .quantity is encrypted
-- with gSaveBlock2Ptr->encryptionKey (src/item.c:20-29 GetBagItemQuantity/SetBagItemQuantity,
-- :41-49 ApplyNewEncryptionKeyToBagItems only XORs the quantity fields); the itemId this file
-- reads is plaintext, like every other RAM read here.
local ITEM_POKE_BALL = 4
local SB1_POKEBALLS_POCKET_OFFSET = 0x0430

local function bag_menu_up() return memory.read_u32_le(GMAIN_CALLBACK2_ADDR) == CB2_BAG_MENU_RUN end
--- Can the bag READ a press? CB2_BagMenuRun is installed before the open fade ends (pret
--- src/item_menu.c:501-502), and Task_BagMenu_HandleInput returns without reading input while
--- gPaletteFade.active or Task_AnimateWin0v runs (:1044-1049). Live link_gen3 run 1 (FR, throw
--- 2): the POKEBALLS pocket was remembered, the steer's idle was skipped, and the selecting A
--- landed in the fade -- gSpecialVar_ItemId kept GoToBagMenu's ITEM_NONE (:340).
local TASK_BAG_MENU_HANDLE_INPUT = S.TASK_BAG_MENU_HANDLE_INPUT
local TASK_ANIMATE_WIN0V = S.TASK_ANIMATE_WIN0V
local BAG_INPUT_WAIT_FRAMES = 240
local function bag_pocket() return memory.read_u16_le(BAG_MENU_STATE_ADDR + BAG_POCKET_OFF) end
--- The bag slot actually highlighted: itemsAbove[pocket] (scroll offset) + cursorPos[pocket]
--- (on-screen row) — item_menu.c:470 initializes the list with exactly this pair.
local function bag_cursor_slot(pocket)
    local above = memory.read_u16_le(BAG_MENU_STATE_ADDR + BAG_ITEMS_ABOVE_OFF + pocket * 2)
    local cursor = memory.read_u16_le(BAG_MENU_STATE_ADDR + BAG_CURSOR_POS_OFF + pocket * 2)
    return above + cursor
end
local function bag_pokeballs_item_id(cp, slot)
    -- RR (CFRU) keeps its bag in EWRAM, not SaveBlock1: the pack's derived.BAG_IN_EWRAM +
    -- ram.BALL_POCKET_ADDR, the same pocket lua/gen3/reads.lua read_balls reads (G5-RR-BATTERY-2)
    if profile.derived.BAG_IN_EWRAM then
        return memory.read_u16_le(profile.ram.BALL_POCKET_ADDR + slot * 4)
    end
    local sb1 = sb1_ptr(cp)
    if not sb1 then return -1 end
    return memory.read_u16_le(sb1 + SB1_POKEBALLS_POCKET_OFFSET + slot * 4)
end
local function selected_item_id() return memory.read_u16_le(SPECIAL_VAR_ITEM_ID_ADDR) end

-- THE PARCEL-DELIVERY ORACLE (card gen3-P3-C3-26). FALSE PASS FOUND: the old parcel_deliver leg
-- called play.wait_scene_settled and reported success the instant it returned true, with no RAM
-- check at all -- but PalletTown_ProfessorOaksLab_EventScript_ProfOak (data/maps/
-- PalletTown_ProfessorOaksLab/scripts.inc:567-660) is a TALK-TO script (`lock; faceplayer`),
-- triggered by pressing A while facing the object, not by walking up to or facing it. The old
-- leg never pressed A, so the field was ALREADY idle+unlocked (nothing had started) the instant
-- it finished walking -- exactly what wait_scene_settled's own "quiet" predicate reads as
-- "settled". The PHYSICAL RAM dump that caught this (slink_fr_parcel_deliver.State) showed
-- ITEM_OAKS_PARCEL still sitting in the key-items pocket and every POKe BALLS slot at 0. Three
-- real terminals replace the guess, each one a write the script itself makes:
--   1. ITEM_OAKS_PARCEL leaves the key-items pocket (scripts.inc:601 `removeitem`)
--   2. FLAG_SYS_POKEDEX_GET gets set (scripts.inc:656 `setflag`)
--   3. ITEM_POKE_BALL lands in the POKe BALLS pocket (scripts.inc:660 `giveitem_msg ...,
--      ITEM_POKE_BALL, 5`)
--
-- SaveBlock1.bagPocket_KeyItems (pret include/global.h:779, offset 0x03B8; BAG_KEYITEMS_COUNT=30
-- per include/constants/global.h:37) holds the same struct ItemSlot{itemId,quantity} shape as
-- bagPocket_PokeBalls above -- itemId plaintext, only .quantity XOR-keyed (src/item.c:20-29).
-- ITEM_OAKS_PARCEL=349 (include/constants/items.h:421). Scan every slot, never assume 0: this
-- file's own rule (see the bag-witness comment above), even though the PHYSICAL dump found it
-- there.
local SB1_KEYITEMS_POCKET_OFFSET = 0x03B8
local BAG_KEYITEMS_COUNT = 30
local ITEM_OAKS_PARCEL = 349
local function key_items_has_parcel(cp)
    local sb1 = sb1_ptr(cp)
    if not sb1 then return true end  -- unreadable: never claim "delivered" on a bad read
    for slot = 0, BAG_KEYITEMS_COUNT - 1 do
        if memory.read_u16_le(sb1 + SB1_KEYITEMS_POCKET_OFFSET + slot * 4) == ITEM_OAKS_PARCEL then
            return true
        end
    end
    return false
end

local function verify_parcel_fetched(cp)
    local sb1 = sb1_ptr(cp)
    -- item.c:20-29 XORs quantity with the LOW u16 of SaveBlock2.encryptionKey
    -- (global.h:358 +0xF20; pokefirered.sym:810 gSaveBlock2Ptr).
    local sb2 = memory.read_u32_le(S.SAVEBLOCK2_PTR_ADDR)
    if not sb1 or sb2 < 0x02000000 or sb2 > 0x02040000 - 0xF24 or sb2 % 4 ~= 0 then
        G.finish(false, "parcel_fetch_pointer: unreadable bag or encryption key"); return
    end
    local key = memory.read_u16_le(sb2 + 0xF20)
    for slot = 0, BAG_KEYITEMS_COUNT - 1 do
        local addr = sb1 + SB1_KEYITEMS_POCKET_OFFSET + slot * 4
        if memory.read_u16_le(addr) == ITEM_OAKS_PARCEL
           and (memory.read_u16_le(addr + 2) ~ key) > 0 then return true end
    end
    G.finish(false, "parcel_fetch_missing: mart did not grant ITEM_OAKS_PARCEL(349) "
             .. "with positive quantity in the key pocket")
    return false
end

-- FLAG_SYS_POKEDEX_GET = SYS_FLAGS(0x800) + 0x29 = 0x829 (include/constants/flags.h:1324,1375).
-- SaveBlock1.flags[] at SB1+0x0EE0 (include/global.h:790; NUM_FLAG_BYTES-sized, vanilla profile's
-- own SB1_FLAGS_OFFSET). Flags are bit-packed: byte flags[idx/8], bit (idx&7) — the exact shape
-- GetFlagAddr/FlagGet use (src/event_data.c:279-309).
local SB1_FLAGS_OFFSET = 0x0EE0
local FLAG_SYS_POKEDEX_GET = 0x829
local function pokedex_get_flag(cp)
    local sb1 = sb1_ptr(cp)
    if not sb1 then return false end
    local byte = memory.read_u8(sb1 + SB1_FLAGS_OFFSET + (FLAG_SYS_POKEDEX_GET // 8))
    return (byte & (1 << (FLAG_SYS_POKEDEX_GET % 8))) ~= 0
end

-- POKe BALLS pocket: does any slot hold ITEM_POKE_BALL? Reuses bag_pokeballs_item_id's own
-- reader/offset (SaveBlock1.bagPocket_PokeBalls +0x0430); BAG_POKEBALLS_COUNT=13
-- (include/constants/global.h:38). Scanned, not assumed at slot 0, for the same reason as the
-- key-items scan above.
local BAG_POKEBALLS_COUNT = profile.derived.SB1_BALL_POCKET_COUNT or 13   -- RR: 50
local function pokeballs_pocket_has_poke_ball(cp)
    for slot = 0, BAG_POKEBALLS_COUNT - 1 do
        if bag_pokeballs_item_id(cp, slot) == ITEM_POKE_BALL then return true end
    end
    return false
end

-- ── PATHS: every direction list below, OFFLINE-BFS-computed ────────────────────────────────────
-- Tool: a Python BFS (scratchpad, not checked in) over data/layouts/<map>/map.bin: block u16,
-- collision=(word>>10)&3, blocked if nonzero; object_event tiles from data/maps/<map>/map.json
-- also blocked; 4-directional BFS, shortest path. Every entry names the map, start, end tile.
local PATHS = {
    -- PalletTown/map.json coord_events: OakTriggerLeft @ (12,1), var VAR_MAP_SCENE_PALLET_TOWN_OAK
    -- == 0 (true on a fresh save). Walking onto this TILE fires it (a coord_event, not a warp —
    -- no press-into needed). This is the FIRST entry into the lab, not the door: on a fresh
    -- save Oak is not in the lab and the starter balls are inert (PalletTown_ProfessorOaksLab/
    -- scripts.inc:1219-1223 "Those are Poke Balls") until this trigger's scripted sequence
    -- (data/maps/PalletTown/scripts.inc:181-217) leads the player in and warps them to
    -- (6,12) with VAR_MAP_SCENE_PALLET_TOWN_PROFESSOR_OAKS_LAB=1. Path avoids (13,1)/(13,2)
    -- (OakTriggerRight / SignLadyTrigger) entirely (checked cell-by-cell against the BFS output).
    town_start_to_oak_trigger = {
        map = "PalletTown", from = { 6, 9 }, to = { 12, 1 },
        dirs = { "Right","Right","Right","Right","Right","Up","Up","Up","Up","Up","Up","Up",
                 "Right","Up" },
    },
    -- Re-entry path for every LATER lab visit (parcel_deliver, route1_catch), once
    -- FLAG_HIDE_OAK_IN_PALLET_TOWN is set and the door works normally again.
    -- PalletTown/map.json warp_events[2] = (16,13) MAP_PALLET_TOWN_PROFESSOR_OAKS_LAB warp 0.
    -- Door tile (16,13) reads collision=1; the walkable approach is (16,14), one tile south.
    town_start_to_lab_door = {
        map = "PalletTown", from = { 6, 9 }, to = { 16, 14 },   -- (6,9): FRLG door exit walks one tile south of the door (PHYSICAL 2026-09-21)
        dirs = { "Down", "Right", "Right", "Right", "Right", "Down", "Down", "Down", "Down", "Right", "Right", "Right", "Right", "Right", "Right" },
    },
    -- PalletTown_ProfessorOaksLab/map.json warp_events[0] = (6,12), the lab's own landing tile
    -- (collision=0, walk-through). SquirtleBall object_event at (9,4) (collision=1, solid);
    -- (9,5) one tile south is the interact-facing approach. Used by LATER visits that enter
    -- via the door directly (the first visit's own scripted walk ends at (6,4), not (6,12) —
    -- see lab_oak_scene_end_to_ball below).
    lab_entrance_to_ball = {
        map = "PalletTown_ProfessorOaksLab", from = { 6, 12 }, to = { 9, 5 },
        dirs = { "Up","Up","Up","Up","Up","Up","Up","Right","Right","Right" },
    },
    -- ONE-TIME: the ChooseStarterScene's own scripted player movement
    -- (PalletTown_ProfessorOaksLab_Movement_PlayerEnter, scripts.inc:238-247: walk_up x8 from
    -- the (6,12) landing tile) parks the player at (6,4), not (6,12) — computed from the
    -- movement macro, the same "engine drives this walk" exception as mart_scene_end_to_exit.
    -- Verified at runtime by follow()'s start-tile check like every other path.
    lab_oak_scene_end_to_ball = {
        map = "PalletTown_ProfessorOaksLab", from = { 6, 4 }, to = { 9, 5 },
        dirs = { "Down","Right","Right","Right" },
    },
    -- coord_events RivalBattleTriggerLeft/Mid/Right @ y=8, x in {5,6,7}
    -- (PalletTown_ProfessorOaksLab/map.json). This BFS route from the ball's approach tile
    -- (9,5) reaches x=7 before descending, so it always lands ON (7,8) = RivalBattleTriggerRight
    -- (PHYSICAL run 9: confirmed — the walker stalled trying to step PAST (7,8), because landing
    -- on the trigger tile itself already fires it: `lockall` in
    -- scripts.inc:270-274, RivalBattleTriggerRight). The path therefore ends AT the trigger
    -- tile, not past it -- one shorter than a plain BFS to (6,8) would be.
    ball_to_rival_row = {
        -- battles = false: landing on this path's LAST tile fires the rival trigger, so the
        -- battle that follows belongs to the rival_battle leg's own oracle. The walker's
        -- encounter absorber (playlib step/handle_encounter) would fight it first and leave
        -- that leg with nothing to observe.
        battles = false,
        map = "PalletTown_ProfessorOaksLab", from = { 9, 5 }, to = { 7, 8 },
        dirs = { "Down","Down","Left","Left","Down" },
    },
    -- warp_events[0..2] = (5,12)/(6,12)/(7,12) -> PalletTown warp 2; walk-through, no press-in.
    -- from=(7,8): the rival battle script never moves the PLAYER object coordinate-wise (only
    -- Common_Movement_WalkInPlaceFasterUp -- in place -- and the post-battle
    -- PlayerWatchRivalExitAfterBattle -- also in place, scripts.inc:283-284,540-545), so the
    -- player is still standing on the trigger tile (7,8) once the whole scene releases.
    rival_row_to_lab_exit = {
        map = "PalletTown_ProfessorOaksLab", from = { 7, 8 }, to = { 6, 12 },
        dirs = { "Down","Down","Down","Down","Left" },
    },
    -- PROF_OAK object_event @ (6,3) (collision=1, solid); (6,4) is the approach.
    lab_entrance_to_oak = {
        map = "PalletTown_ProfessorOaksLab", from = { 6, 12 }, to = { 6, 4 },
        dirs = { "Up","Up","Up","Up","Up","Up","Up","Up" },
    },
    oak_to_lab_exit = {
        map = "PalletTown_ProfessorOaksLab", from = { 6, 4 }, to = { 6, 12 },
        dirs = { "Down","Down","Down","Down","Down","Down","Down","Down" },
    },
    -- PalletTown/map.json connections[0]: MAP_ROUTE1 direction=up offset=0 -> Route1's local x
    -- equals PalletTown's. Top rows (y=0,1) open only at x=10..13; the north-open column x=12
    -- lines up with Route1's own south grass gap at x=12,13 (verified against both grids).
    lab_exit_to_route1_edge = {
        map = "PalletTown", from = { 16, 14 }, to = { 12, 1 },
        dirs = { "Left","Left","Left","Left","Up","Up","Up","Up","Up","Up","Up","Up","Up","Up",
                 "Up","Up","Up" },
    },
    -- CONNECTION ARRIVAL ROW, the rule the lane taught us (run 13: "parcel_deliver
    -- (route1_north_to_south_edge): start tile (12,0) is not the path's from (12,1)").
    -- Crossing a map CONNECTION does not land you one tile inside the destination: you arrive
    -- ON its edge row. Walking off map A's BOTTOM edge into A's `down` connection lands at the
    -- destination's y=0; walking off A's TOP edge into its `up` connection lands at the
    -- destination's y=height-1. The x is the destination's own, via the connection offset.
    --
    -- Both directions were always in play; only the y=height-1 one happened to match, because
    -- Route 1 is 40 tall and the old from-tile said 39. The y=0 side was wrong in two entries
    -- and cost a lane run.
    --
    -- tools/gba_map.py does not read the connections list yet (it parses layouts/warps/objects
    -- /coords/bg), so the RULE above is cited from pret data/maps/<Map>/map.json "connections"
    -- (direction + offset per entry) rather than re-derived here; what the tool DID verify is
    -- every tile these paths walk over, against the real ROM:
    --
    --   python tools/gba_map.py "patch/build/gen3_Pokemon_-_FireRed_Version_(USA).gba" \
    --          --map 3.19 --bfs 12,0 12,39        (Route 1     = 3.19, 24x40, 0 warps)
    --   python tools/gba_map.py "patch/build/gen3_Pokemon_-_FireRed_Version_(USA).gba" \
    --          --map 3.0  --bfs 12,0 16,14        (Pallet Town = 3.0,  24x20, 3 warps)
    --
    -- Each returned exactly the old direction list with ONE extra leading Down -- i.e. the
    -- routes were right all along and only their start tile was off by the arrival row.
    route1_edge_to_lab_door = {
        map = "PalletTown", from = { 12, 0 }, to = { 16, 14 },   -- arrives from Route 1's down connection
        dirs = { "Down","Down","Down","Down","Down","Down","Down","Down","Down","Down","Down",
                 "Down","Down","Down","Right","Right","Right","Right" },
    },
    -- Route1/map.json connections: down->PalletTown offset=0 (own x); up->ViridianCity offset=-12
    -- under the "this_x = other_x + offset" convention pret uses (verified empirically: crossing
    -- at Route1 x=12 lands ViridianCity x=24, which is open ground; x=12-12=0 there is a border
    -- wall). South wall (y=38,39) is open ONLY at x=12,13 (both tall-grass metatiles 10-13 in
    -- gTileset_General, data/tilesets/primary/general/metatile_attributes.bin low-byte 0x02 =
    -- MB_TALL_GRASS); grass at the entrance is unavoidable, not a choice.
    -- Ends on (12,37), the top-left corner of GRASS_LOOP's four-tile square (all four read
    -- MB_TALL_GRASS 0x02; see hunt_encounter).
    route1_south_to_grass_spot = {
        map = "Route1", from = { 12, 39 }, to = { 12, 37 }, dirs = { "Up","Up" },
    },
    route1_south_to_north_edge = {
        map = "Route1", from = { 12, 39 }, to = { 12, 1 },
        dirs = { "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Left", "Left", "Left", "Left", "Up", "Up", "Up", "Up", "Up", "Right", "Right", "Right", "Right", "Up", "Up", "Up", "Up", "Up", "Up", "Left", "Left", "Up", "Up", "Up", "Up", "Right", "Right", "Right", "Right", "Right", "Right", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Left", "Left", "Left", "Up", "Left" },
    },
    route1_north_to_south_edge = {
        map = "Route1", from = { 12, 0 }, to = { 12, 39 },   -- arrives from Viridian's down connection
        dirs = { "Down","Down","Down","Down","Right","Right","Right","Right","Down","Down","Down","Down",
                 "Down","Down","Down","Down","Down","Down","Down","Down","Down","Down","Down",
                 "Left","Left","Left","Left","Left","Left","Down","Down","Down","Down","Down",
                 "Right","Right","Down","Down","Down","Down","Down","Down","Left","Left","Left",
                 "Left","Down","Down","Down","Down","Down","Right","Right","Right","Right","Down",
                 "Down","Down","Down" },
    },
    route1_grass_to_north_edge = {
        map = "Route1", from = { 12, 37 }, to = { 12, 1 },
        dirs = { "Up","Up","Up","Up","Up","Left","Left","Left","Left","Up","Up","Up","Up","Up",
                 "Right","Right","Right","Right","Up","Up","Up","Up","Up","Up","Left","Left","Up",
                 "Up","Up","Up","Right","Right","Right","Right","Right","Right","Up","Up","Up",
                 "Up","Up","Up","Up","Up","Up","Up","Up","Up","Up","Up","Up","Left","Left","Left",
                 "Up","Left" },
    },
    -- ViridianCity/map.json connections down->Route1 offset=12 ("this_x = other_x + offset"
    -- i.e. Route1_x = ViridianCity_x - 12); the crossing landing (24,39) was verified open
    -- ground on ViridianCity's own collision grid. Mart door (36,19) collision=1; approach
    -- (36,20) collision=0 (warp_events entries in data/maps/ViridianCity/map.json).
    route1_edge_to_mart_door = {
        map = "ViridianCity", from = { 24, 39 }, to = { 36, 20 },
        dirs = { "Up","Up","Up","Up","Up","Up","Up","Up","Left","Left","Up","Up","Up","Up","Up",
                 "Up","Up","Up","Up","Up","Up","Right","Right","Right","Right","Right","Right",
                 "Right","Right","Right","Right","Right","Right","Right","Right" },
    },
    mart_door_to_route1_edge = {
        map = "ViridianCity", from = { 36, 20 }, to = { 24, 39 },
        dirs = { "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Right", "Right" },
    },
    -- PokeCenter door (26,26) in ViridianCity/map.json; collision=1, approach (26,27)=0.
    route1_edge_to_pokecenter_door = {
        map = "ViridianCity", from = { 24, 39 }, to = { 26, 27 },
        dirs = { "Up","Up","Up","Up","Up","Up","Up","Up","Left","Left","Up","Up","Up","Up",
                 "Right","Right","Right","Right" },
    },
    -- ViridianCity_Mart's own warp_events[1] = (4,7); the parcel scene's scripted player
    -- movement (ViridianCity_Mart_Movement_ApproachCounter: walk_up x4) ends at (4,3) facing
    -- left — computed from the movement macro in data/maps/ViridianCity_Mart/scripts.inc, not
    -- observed; that is the one non-BFS coordinate below (see the leg comment).
    mart_scene_end_to_exit = {
        map = "Mart", from = { 4, 3 }, to = { 4, 7 }, dirs = { "Down","Down","Down","Down" },
    },
    -- WHITEOUT RECOVERY. From where Mom stands you up (8,5) to the house's own front door
    -- row; the door tiles (4,8)/(5,8) are warps, so the exit is a press-into Down from (4,8),
    -- the same shape gen3_fr_newgame_inputs.lua's 1F->town leg uses.
    --   python tools/gba_map.py "<FR>.gba" --map 4.0 --bfs 8,5 4,8
    --   -> ['Down','Down','Down','Left','Left','Left','Left']
    heal_house_to_door = {
        map = "PalletTown_PlayersHouse_1F", from = { 8, 5 }, to = { 4, 8 },
        dirs = { "Down","Down","Down","Left","Left","Left","Left" },
    },
    -- C3-29: BFS over pret data/layouts/PokemonCenter_1F/map.bin, with
    -- ViridianCity_PokemonCenter_1F/map.json object tiles blocked: (7,4)->(7,8).
    heal_center_to_door = {
        map = "PokemonCenter_1F", from = {7,4}, to = {7,8},
        dirs = {"Down","Down","Down","Down"},
    },
    -- pret PalletTown/map.json warp 0=(6,7), Task_ExitDoor walks south to (6,8).
    house_exit_to_town_start = {
        map = "PalletTown", from = {6,8}, to = {6,9}, dirs = {"Down"},
    },
    -- BFS over pret data/layouts/PalletTown/map.bin, objects blocked.
    pallet_north_to_town_start = {
        map = "PalletTown", from = {12,0}, to = {6,9},
        dirs = {"Down","Down","Down","Down","Down","Down","Down","Down","Down",
                "Left","Left","Left","Left","Left","Left"},
    },
    -- VIRIDIAN HEAL DETOUR (prevention, so the southbound Route 1 walk starts at full HP).
    --   python tools/gba_map.py "<FR>.gba" --map 3.1 --bfs 36,20 26,27
    --   python tools/gba_map.py "<FR>.gba" --map 3.1 --bfs 26,27 24,39
    mart_door_to_pokecenter_door = {
        map = "ViridianCity", from = { 36, 20 }, to = { 26, 27 },
        dirs = { "Down","Down","Down","Down","Down","Down","Down","Left","Left","Left","Left",
                 "Left","Left","Left","Left","Left","Left" },
    },
    pokecenter_door_to_route1_edge = {
        map = "ViridianCity", from = { 26, 27 }, to = { 24, 39 },
        dirs = { "Down","Down","Left","Left","Left","Left","Down","Down","Down","Down","Down",
                 "Down","Down","Down","Down","Down","Right","Right" },
    },
    -- The nurse (object 1, graphics 64) stands at (7,2) behind a counter row whose metatiles
    -- read behaviour 0x80 = MB_COUNTER at (5..9,3) (pret include/constants/metatile_behaviors.h;
    -- FRLG's value, not Emerald's 0x6B) -- an interaction passes THROUGH a counter to the
    -- object behind it, so the talking tile is (7,4), one below the counter, facing Up.
    --   python tools/gba_map.py "<FR>.gba" --map 5.4 --bfs 7,8 7,4  -> ['Up','Up','Up','Up']
    pokecenter_entrance_to_nurse = {
        map = "PokemonCenter_1F", from = { 7, 8 }, to = { 7, 4 },
        dirs = { "Up","Up","Up","Up" },
    },
    -- PokemonCenter_1F's own warp_events[1] = (7,8) (used entering from ViridianCity warp 1).
    -- PC counter metatile (MB_PC=0x83, pret include/constants/metatile_behaviors.h:94) found at
    -- gTileset_Building metatile ids 98/99 (data/tilesets/primary/building/metatile_attributes.bin
    -- low byte 0x83), placed at (11,1) in data/layouts/PokemonCenter_1F/map.bin; collision=1,
    -- approach (11,2)=0.
    pokecenter_entrance_to_pc = {
        map = "PokemonCenter_1F", from = { 7, 8 }, to = { 11, 2 },
        dirs = { "Up","Up","Up","Up","Right","Right","Right","Right","Up","Up" },
    },
    -- The tail of pokecenter_entrance_to_pc from its (7,4) waypoint: the whiteout landing
    -- (heal_location.c: Viridian -> Center 5.4 (7,4)). Same BFS-verified tiles, no new geometry.
    center_heal_spot_to_pc = {
        map = "PokemonCenter_1F", from = { 7, 4 }, to = { 11, 2 },
        dirs = { "Right","Right","Right","Right","Up","Up" },
    },
    -- C4-6m, the Center 2F controls: tools/gba_map.py --map 5.4 --bfs 11,2 2,6 (objects
    -- blocked; FR == LG). (1,6) is the MB_UP_ESCALATOR 0x6A the next Left step rides.
    center_pc_to_escalator = {
        map = "PokemonCenter_1F", from = { 11, 2 }, to = { 2, 6 },
        dirs = { "Down","Down","Down","Left","Down","Left","Left","Left","Left","Left","Left",
                 "Left","Left" },
    },
    -- --map 5.5 --bfs 2,6 10,4: the escalator arrival (EscalatorWarpInEffect_7 walks EAST off
    -- (1,6)) to the Direct Corner attendant's counter front; then to the Union Room attendant's.
    center2f_to_direct_corner = {
        map = "PokemonCenter_2F", from = { 2, 6 }, to = { 10, 4 },
        dirs = { "Up","Up","Right","Right","Right","Right","Right","Right","Right","Right" },
    },
    -- --map 5.5 --bfs 2,4 10,4: from where CableClub_EventScript_Tutorial leaves the player
    -- (Movement_PlayerApproachCounter, walk_up x2 from the arrival (2,6)).
    center2f_counter_to_direct_corner = {
        map = "PokemonCenter_2F", from = { 2, 4 }, to = { 10, 4 },
        dirs = { "Right","Right","Right","Right","Right","Right","Right","Right" },
    },
    center2f_direct_corner_to_union_room = {
        map = "PokemonCenter_2F", from = { 10, 4 }, to = { 6, 4 },
        dirs = { "Left","Left","Left","Left" },
    },
}

-- ── per-title paths (G5-RR-LAST) ─────────────────────────────────────────────────────────────
-- Radical Red's Viridian City (map 3.1, read from the RR ROM with tools/gba_map.py): the same
-- 48x40 layout, collision, behaviours and warps as FR along every tile below, but RR adds three
-- object events, four more coord events, moves object 2 off (11,24) and changes object 6's
-- movement type -- dynamic state the static BFS cannot see. Live whiteout_gen3 at 6131930f
-- stalled on the FR way out ((26,28) Down), while the way IN (route1_edge_to_pokecenter_door) is
-- walked live on RR every run. On RR the way out is therefore that proven path reversed tile for
-- tile: Left x4 along y=27, Down x4 at x=22, Right x2, Down x8 at x=24 -- it never touches
-- (26,28)/(26,29), and a unit re-walks it on the RR map's collision.
if TITLE == "radical_red" then
    local INVERT = { Up = "Down", Down = "Up", Left = "Right", Right = "Left" }
    local inbound, out = PATHS.route1_edge_to_pokecenter_door, {}
    for i = #inbound.dirs, 1, -1 do out[#out + 1] = INVERT[inbound.dirs[i]] end
    PATHS.pokecenter_door_to_route1_edge = {
        map = inbound.map, from = { inbound.to[1], inbound.to[2] },
        to = { inbound.from[1], inbound.from[2] }, dirs = out,
    }
end

-- ── the Gen 3 binding ────────────────────────────────────────────────────────────────────────
-- playlib holds no host call and no game fact: no memory, joypad, client, event, savestate or
-- dofile appears in it (Codex review cx-67a6e199). Everything it needs arrives here, which is
-- also what lets a Gen 1 or Gen 2 driver bind its own readers to the same runner.
local H = {
    -- frames, input and reporting: the Gen 3 helper module already is these
    advance = G.advance, idle = G.idle, tap = G.tap, pos = G.pos,
    phase = G.phase, finish = G.finish, shot = G.shot, open = G.open,
    checkpoint = G.checkpoint,
    press      = function(buttons) joypad.set(buttons); G.advance() end,
    speed_max  = function() client.speedmode(6399) end,
    set_budget = function(n) G.budget = n end,

    -- MAP IDENTITY. nil when the SaveBlock1 pointer is not a sane EWRAM address, which is what
    -- G.map's -1,-1 means (gen3_boot_check.lua:118-123). playlib compares map ids and must
    -- never mistake "cannot read" for "changed".
    map = function(cp)
        local g, n = G.map(cp)
        if g < 0 or n < 0 then return nil end
        return g * 256 + n
    end,

    -- PREDICATE POLARITY, in one place. The `in_battle` row is a mask with expect=0 and
    -- pred_ok compares (value & mask) == expect, so G.pred_ok(cp,"in_battle") is TRUE when we
    -- are NOT in a battle (Codex cx-378ce251). The predicate NAMES are Gen 3's, which is why
    -- they live here and not in the library.
    in_battle   = function(cp) return not G.pred_ok(cp, "in_battle") end,
    on_field    = function(cp)
        return G.pred_ok(cp, "in_battle") and G.pred_ok(cp, "callback2")
    end,
    scene_quiet = function(cp)
        return G.pred_ok(cp, "script_context_status") and G.pred_ok(cp, "field_controls_locked")
    end,

    -- gObjectEvents = 0x02036E38 (pokefirered.sym:205), object 0 = the player, stride 0x24.
    -- currentCoords are s16 x/y at +0x10/+0x12 stored +7 (MAP_OFFSET); facingDirection is the
    -- LOW nibble at +0x18 and movementDirection the high one (pret include/global.fieldmap.h:254-255
    -- declares `u8 facingDirection:4; u8 movementDirection:4;`, packed LSB-first). Introduced on
    -- run 8 to cross-check the live object against SaveBlock1.pos when the two disagreed.
    obj_pos = function(i)
        local base = OBJ_EVENTS_ADDR + (i or 0) * 0x24
        return memory.read_s16_le(base + 0x10) - 7, memory.read_s16_le(base + 0x12) - 7
    end,
    obj_facing = function(i)
        return memory.read_u8(OBJ_EVENTS_ADDR + (i or 0) * 0x24 + 0x18) & 0x0F
    end,
    party_count = function() return memory.read_u8(PARTY_COUNT_ADDR) end,
    -- Party IDENTITY, for playlib's keyed snapshot. PID:OTID is the same handle the duo
    -- harness follows a mon by (lua/tests/archive/gen3_old_client/duo_main.lua:86-98); it is plaintext (both sit
    -- outside the encrypted substructures) and it survives a box round trip, which the
    -- record's bytes need not.
    party_key = function(i)
        local base = PARTY_BASE + i * MON_SIZE
        return string.format("%08X:%08X", memory.read_u32_le(base + OFF_PID),
                                          memory.read_u32_le(base + OFF_OTID))
    end,
    party_record = function(i)
        local base = PARTY_BASE + i * MON_SIZE
        local parts = {}
        for w = 0, (MON_SIZE // 4) - 1 do
            parts[#parts + 1] = string.format("%08X", memory.read_u32_le(base + w * 4))
        end
        return table.concat(parts)
    end,

    load_state = function(path) return (pcall(savestate.load, path)) end,
    save_state = function(path) return (pcall(savestate.save, path)) end,
    register_frame_end = function(fn, name)
        -- Return what the host returned, and NOTHING else. `id or name` fabricated a handle
        -- whenever onframeend returned nil, which sailed past playlib's "was it registered?"
        -- check and then handed a NAME to unregisterbyid (Codex cx-bc675fa4). An observer
        -- nobody polls must fail the run, not look registered.
        local ok, id = pcall(event.onframeend, fn, name)
        if not ok then return nil end
        return id
    end,
    unregister_frame_end = function(id) pcall(event.unregisterbyid, id) end,

    -- The shadow observer, as a factory: playlib starts it, polls it and reads its HEALTH, but
    -- never loads it (dofile is a host call too).
    observer = function(result)
        local ok, shd = pcall(dofile, WT .. "/lua/gen3/shadow_run.lua")
        if not ok or not shd then return nil, "dofile lua/gen3/shadow_run.lua: " .. tostring(shd) end
        local ok2, st = pcall(shd.start, { duo = { result = result, player = "a" } })
        if not ok2 or not st then return nil, "shadow_run.start: " .. tostring(st) end
        return {
            poll   = st.poll,
            status = function() return st.parts.signals:status() end,
            detail = "admitted_by=" .. tostring(st.admitted_by),
        }
    end,
}

local play, check_whiteout, verify_fight_cursor, send_out_healthy_mon
play = PL.bind(H, {
    paths          = PATHS,
    -- where the per-leg savestates below land
    state_dir      = os.getenv("SLINK_GEN3_PLAY_STATES_DIR") or "E:/Howard/Bizhawk/GBA/State",
    max_recoveries = 2,
    -- HOW THIS GAME FIGHTS an incidental battle. The action cursor resets on
    -- new-battle setup and switch-in (battle_controllers.c:51-52 and
    -- battle_controller_player.c:2099-2100), but can remain on POKEMON(2)
    -- within one battle. FR run 25e was a mid-battle forced party selection.
    -- Witness and steer to FIGHT whenever the action menu returns.
    -- Input policy, not library policy: which button dismisses a textbox and which advances a
    -- scripted scene are per-game facts, same as opts.battle (Codex cx-bc675fa4).
    clear_dialogue = function() for _ = 1, 4 do G.tap("A", 3, 13) end end,
    advance_scene  = function() G.tap("A", 2, 10) end,
    -- Backing out of a menu, one press. playlib owns the RULE (dismiss until the field
    -- appears, keep dismissing through the exit textbox, settle, re-check); the button and its
    -- spacing are ours.
    menu_back = function(_, gap) G.tap("B", 3, gap or 20) end,
    battle = function(cp, budget)
        local before_map, before_x, before_y = play.map(cp), G.pos(cp)
        local checkpoint = last_heal_checkpoint(cp)
        if not checkpoint then return false end
        local turns, taps_per_turn = 32, math.max(1, math.ceil((budget or 1200) / 32))
        for _ = 1, turns do
            if not play.in_battle(cp) then break end
            local menu = party_menu_up() and "party" or verify_fight_cursor(cp, "incidental_battle")
            if menu == "party" then
                if not send_out_healthy_mon(cp, "incidental_battle") then return false end
            elseif play.in_battle(cp) then
                if not action_menu_up() then
                    G.finish(false, "incidental_battle: action menu disappeared before FIGHT selection")
                    return false
                end
                -- Require the witnessed action menu to close under FIGHT before
                -- the next A selects move slot 1; a dropped press stays bounded.
                for _ = 1, 4 do
                    if not action_menu_up() then break end
                    G.tap("A", 3, 13)
                end
                if action_menu_up() then
                    G.finish(false, "incidental_battle: FIGHT selection did not leave the action menu")
                    return false
                end
                G.tap("A", 3, 13)  -- move slot 1
                -- Stop before an unqualified A can select a remembered cursor
                -- or the forced party menu on the next turn.
                play.mash_a(taps_per_turn, function()
                    return not play.in_battle(cp) or action_menu_up() or party_menu_up()
                end)
            end
        end
        if play.in_battle(cp) then return false end
        if party_menu_up() then
            G.finish(false, "incidental_battle: forced party menu remained open after battle")
            return false
        end
        if not play.wait_scene_settled(cp, 1800) then return false end
        if not play.on_field(cp) then
            G.finish(false, "incidental_battle: field callback never settled after battle")
            return false
        end
        -- Raise the shared recovery signal here: playlib's static heal_map cannot
        -- express FR's lastHealLocation-dependent respawn projection.
        check_whiteout(cp, before_map, before_x, before_y, checkpoint)
        return true
    end,
})

-- WITNESS-DRIVEN battle recovery (card C4-LGF2, coordinator steer 2026-09-23). PHYSICAL LG run:
-- parcel_deliver's "Route1->Pallet" warp failed with "map never changed from 787" -- the phase
-- log showed the walk itself (route1_north_to_south_edge) reached its own `to` tile cleanly, so
-- the stall was in THIS press-into-the-connection step, which sits on tall grass (Route 1's
-- south/north edges are grass at every open column; route1_edge_to_lab_door's own PATHS comment
-- already says so). playlib's enter_warp presses blindly and carries no battle policy of its own
-- (playlib holds no game fact); RE-RUNNING THE SAME PRESS SEQUENCE ON AN UNCHANGED FAILURE WOULD
-- ONLY RE-ROLL THE SAME RNG, so the fix resolves whatever incidental battle is actually open --
-- witnessed by play.in_battle, fought with play.fight_through, the exact pattern route1_faint
-- already uses for a battle mid-walk -- THEN retries the press. Deterministic regardless of which
-- tile the encounter rolls on.
local function warp_to(cp, dir, budget, dest, label)
    local ok, why
    for _ = 1, 3 do
        ok, why = play.enter_warp(cp, dir, budget)
        if ok then break end
        if not play.in_battle(cp) then break end   -- a real failure, not a battle: stop retrying
        if not play.fight_through(cp, 1200) then
            G.finish(false, label .. ": warp_failed: an incidental battle during the warp "
                         .. "press never ended")
            return
        end
    end
    if not ok then G.finish(false, label .. ": warp_failed: " .. tostring(why)); return end
    verify_destination(cp, label, dest)
end

-- FR boxes: pokefirered.sym:811 gPokemonStoragePtr=03005010, relocated on load
-- (src/load_save.c:68-78). pokemon_storage_system.h:44-49 boxes begin at +4, NOT
-- the stale +1 comment: BoxPokemon requires u32 alignment (pokemon.h:105-127).
-- 14 * 30 uncompressed 80-byte records; reads.lua decrypts/permutates and checks
-- the secure checksum. PID/OTID are plaintext; no production write API is used.
local function owned_snapshot(label)
    local party = play.party_snapshot()
    local mons, why = reader.read_party()
    if not mons or #mons ~= party.n then
        G.finish(false, label .. ": unreadable_party: " .. tostring(why)); return
    end
    local owned = {party=party, mons={}, boxes={}}
    for i, mon in ipairs(mons) do
        local key = reader.key(mon)
        if mon.species == 0 or mon.has_species ~= 1 or mon.is_bad_egg ~= 0
           or not mon.checksum_ok or owned.mons[key] or key ~= party.order[i] then
            G.finish(false, label .. ": invalid_party_record: " .. key); return
        end
        owned.mons[key] = mon
    end
    local storage, bad = reader.read_storage()
    if not storage then G.finish(false, label .. ": unreadable_storage: " .. tostring(bad)); return end
    owned.current_box = memory.read_u8(storage)
    for box = 0, 13 do
        local records, err = reader.read_box(box)
        if not records then G.finish(false, label .. ": unreadable_box: " .. tostring(err)); return end
        for slot, mon in ipairs(records) do
            if not mon.checksum_ok or mon.is_bad_egg ~= 0 then
                G.finish(false, label .. ": invalid_box_checksum"); return
            end
            if mon.species ~= 0 then
                local key = reader.key(mon)
                if mon.has_species ~= 1 or owned.mons[key] or owned.boxes[key] then
                    G.finish(false, label .. ": ambiguous_box_record: " .. key); return
                end
                local addr = storage + 4 + (box * 30 + slot - 1) * 80
                owned.boxes[key] = {box=box, slot=slot-1, species=mon.species,
                    raw=string.char(table.unpack(read_bytes(addr, 80)))}
            elseif mon.has_species ~= 0 then
                G.finish(false, label .. ": empty_box_has_species_flag"); return
            end
        end
    end
    return owned
end

local function boxes_unchanged(label, before, after, except)
    for key, old in pairs(before) do
        if key ~= except then
            local new = after[key]
            if not new or old.box ~= new.box or old.slot ~= new.slot or old.raw ~= new.raw then
                G.finish(false, label .. ": unrelated_box_changed: " .. key)
                return false
            end
        end
    end
    for key in pairs(after) do
        if key ~= except and not before[key] then
            G.finish(false, label .. ": unexpected_box_addition: " .. key)
            return false
        end
    end
    return true
end

local function verify_pc_transfer(label, op, before, after, target)
    local a, b = before.party, after.party
    if op == "withdraw" then
        if b.n ~= a.n + 1 or a.keys[target] or not b.keys[target]
           or not before.boxes[target] or not after.mons[target] or after.boxes[target] then
            G.finish(false, label .. ": withdraw_target: selected PID must move box->party")
            return false
        end
        if after.mons[target].species ~= before.boxes[target].species then
            G.finish(false, label .. ": withdraw_species: selected record changed species")
            return false
        end
    else
        local gone = play.departed_key(a, b)
        if b.n ~= a.n - 1 or gone ~= target then
            G.finish(false, label .. ": pc_target: party slot 1 PID was not the single departure")
            return false
        end
        if op == "deposit" then
            local boxed = after.boxes[target]
            if not boxed or boxed.box ~= 0 or boxed.slot ~= 0
               or boxed.species ~= before.mons[target].species then
                G.finish(false, label .. ": deposit_readback: selected PID not in box 0 slot 0")
                return false
            end
        elseif op == "release" then
            if after.boxes[target] then
                G.finish(false, label .. ": release_deposited: selected PID is still boxed")
                return false
            end
        else
            G.finish(false, label .. ": unknown PC operation")
            return false
        end
    end
    local ok, why = play.survivors_intact(a, b, target)
    if not ok then G.finish(false, label .. ": " .. why); return false end
    return boxes_unchanged(label, before.boxes, after.boxes, op ~= "release" and target or nil)
end

local function pc_deposit_target(before)
    if before.party.n < 2 then G.finish(false, "pc_target: deposit needs at least two mons"); return nil end
    -- This input route chooses box 0, then withdraws slot 0; bind that cursor to
    -- the selected identity BEFORE pressing buttons, including on resumed runs.
    if before.current_box ~= 0 then G.finish(false, "pc_box_cursor: current box must be 0"); return nil end
    for _, mon in pairs(before.boxes) do
        if mon.box == 0 and mon.slot == 0 then
            G.finish(false, "pc_box_slot: box 0 slot 0 must be empty before deposit")
            return nil
        end
    end
    return before.party.order[2]
end

--- Hunt a wild encounter by walking a PINNED TALL-GRASS LOOP.
---
--- FR lane run 15: "route1_catch: no wild encounter after 1 grass cycles". The old search
--- oscillated Left/Right from (12,37) with raw joypad holds and no verification -- and (11,37)
--- is not grass, so half of every cycle was spent stepping out of the patch and back, or into
--- a wall. A per-step encounter check only fires on a step ONTO a grass tile, so a search that
--- leaves the grass is not searching.
---
--- All four tiles below read metatile behaviour 0x02 (MB_TALL_GRASS) on Route 1:
---   python tools/gba_map.py "<FR>.gba" --map 3.19 --find-behaviour 0x02
---   -> ... (12,35) (12,36) (12,37) (12,38) (12,39) (13,35) (13,36) (13,37) (13,38) (13,39) ...
--- so the square (12,37) -> (13,37) -> (13,38) -> (12,38) -> back is four grass steps, each
--- one a fresh encounter roll. Bounded by cycles, not frames, and every cycle is a phase line.
local GRASS_LOOP = { "Right", "Down", "Left", "Up" }   -- from (12,37), staying in the band
local GRASS_ORIGIN = { 12, 37 }
-- WHERE THE LOOP IS, ACROSS CALLS. An encounter interrupts the square wherever it fires, and
-- the next hunt used to restart at step 1 from THERE: interrupted at (13,37), the next Right
-- walks to (14,37), which is not grass (Codex cx-bc675fa4). The loop is a cycle, so resuming at
-- the step the player is actually standing on is the whole fix; the origin check below is the
-- belt to that braces.
local grass_step = 1

-- CHECKPOINT BATTLE STATE. probe_gen3_checkpoint.lua's battle row (SLINK_CHECKPOINT_BATTLE_STATE,
-- default slink_prebattle.State) has no source before this driver: the committed fixture
-- (tests/fixtures/gen3/firered_town.sav) has party=0, so no wild battle is reachable from it at
-- all. Route 1's grass loop is the first point in the WHOLE natural-play run that is reliably
-- in-battle, so save it there -- once, the first time either route1_catch or route1_faint (or
-- any future Route 1 leg through hunt_encounter) actually lands in one, not once per leg and not
-- again on a whiteout retry's second encounter.
local battle_state_saved = false

local function save_battle_state_once(cp)
    if battle_state_saved or not H.save_state then return end
    local path = play.state_path("slink_fr_battle.State")
    if path and H.save_state(path) then
        battle_state_saved = true
        G.phase("battle-state-saved", path)
    end
end

--- Walk back to GRASS_ORIGIN from wherever a hunt left the player on the square. FR run 25d:
--- route1_faint ended at (13,38) and viridian_pc's first path starts at (12,37). Left undoes
--- the x, Up the y; each step can still find a battle (play.step fights it).
local function return_to_grass_origin(cp, label)
    for _ = 1, 4 do
        local px, py = G.pos(cp)
        if px == GRASS_ORIGIN[1] and py == GRASS_ORIGIN[2] then return end
        local on_square = (px == 12 or px == 13) and (py == 37 or py == 38)
        if not on_square then
            G.shot("stuck")
            G.finish(false, string.format("%s: expected to be on the grass square (12..13,37..38), "
                     .. "found %s", label, play.at(cp)))
            return
        end
        local ok, why = play.step(cp, px == 13 and "Left" or "Up", play.map(cp), true)
        if not ok then
            G.finish(false, string.format("%s: step back to the grass origin failed (%s) at %s",
                     label, tostring(why), play.at(cp)))
            return
        end
    end
    local px, py = G.pos(cp)
    if px ~= GRASS_ORIGIN[1] or py ~= GRASS_ORIGIN[2] then
        G.finish(false, string.format("%s: never reached the grass origin; at %s", label, play.at(cp)))
    end
end

local function hunt_encounter(cp, label, cycles)
    local start_map = play.map(cp)
    -- Re-anchor if we are not on one of the square's four tiles at all (a whiteout recovery or
    -- a leg that walked here by another route).
    local px, py = G.pos(cp)
    local on_square = (px == 12 or px == 13) and (py == 37 or py == 38)
    if not on_square then
        if not play.wait_at(cp, GRASS_ORIGIN[1], GRASS_ORIGIN[2], 4) then
            G.shot("stuck")
            G.finish(false, string.format(
                "%s: the grass hunt starts at %s, which is not on the pinned square "
                .. "(12..13,37..38)", label, play.at(cp)))
        end
        grass_step = 1
    else
        -- The step is a function of the tile, not of history: a leg resumed from a savestate
        -- (FR run 27: route1_faint from slink_fr_route1_catch.State at (13,38)) starts with
        -- grass_step reset to 1 (Right), which walks off the square. GRASS_LOOP from (12,37).
        grass_step = (px == 12 and py == 37) and 1 or (px == 13 and py == 37) and 2
                     or (px == 13 and py == 38) and 3 or 4
    end
    for cycle = 1, (cycles or 40) do
        for _ = 1, #GRASS_LOOP do
            local dir = GRASS_LOOP[grass_step]
            grass_step = (grass_step % #GRASS_LOOP) + 1
            if play.in_battle(cp) then
                -- Leave grass_step pointing at the step we did NOT take, so the next hunt
                -- resumes the square instead of walking off its edge.
                grass_step = ((grass_step - 2) % #GRASS_LOOP) + 1
                G.phase("encounter-found", string.format("%s: cycle %d at %s",
                                                         label, cycle, play.at(cp)))
                save_battle_state_once(cp)
                return true
            end
            -- enc = false: THIS leg owns the battle it is hunting for, so the walker must not
            -- absorb it. A step that ENDS IN a battle is the answer, not a stall -- the
            -- encounter fires mid-step, before the top-of-loop check above can see it (FR run
            -- 17 reported "the grass loop stalled on Down at (13,37)" while the observer was
            -- logging battle_begin). Anything else that cannot move is a real problem.
            local stepped, why = play.step(cp, dir, start_map, nil, false)
            if not stepped and why == "in_battle" then
                grass_step = ((grass_step - 2) % #GRASS_LOOP) + 1
                G.phase("encounter-found", string.format("%s: cycle %d mid-step %s at %s",
                                                         label, cycle, dir, play.at(cp)))
                save_battle_state_once(cp)
                return true
            end
            if not stepped then
                G.shot("stuck")
                G.finish(false, string.format("%s: the grass loop stalled on %s at %s (%s)",
                                              label, dir, play.at(cp), tostring(why)))
            end
        end
        if cycle % 8 == 0 then
            G.phase("hunting", string.format("%s: %d cycles, still no encounter at %s",
                                             label, cycle, play.at(cp)))
        end
    end
    local landed_in_battle = play.in_battle(cp)
    if landed_in_battle then save_battle_state_once(cp) end
    return landed_in_battle
end

-- RR-WHITEOUT (card G5-RR-WHITEOUT): SLINK_GEN3_RR_TRACE=1 makes traced_follow's RR-only loop
-- (below) log one line per step -- player pos/facing, whether the field is locked (script
-- running), and every OTHER active object event's position -- instead of running quietly. One
-- log per STEP (not per frame -- the inner press/settle loop inside play.step is untouched), so
-- this cannot starve the emulator. Off in every normal run including CI; it only ever adds a
-- console.log, never changes which path is walked or how a stall is judged.
local RR_TRACE = TITLE == "radical_red" and os.getenv("SLINK_GEN3_RR_TRACE") == "1"

-- gen3_title_syms.lua's OBJ_EVENTS_ADDR entry carries no radical_red value ("no RR citation
-- found" -- line ~83 there), so OBJ_EVENTS_ADDR (and H.obj_pos/H.obj_facing, which read it) are
-- nil on RR; a live run confirmed the nil-arithmetic crash. reference_rr_object_events.md
-- independently confirms RR uses the SAME fixed EWRAM gObjectEvents layout as FR/LG
-- (0x02036E38, stride 0x24, 16 slots, proven live via lua/tests/test_overworld_discovery.lua's
-- anchor walk + byte dump) -- diagnostic-only, never gates a pass/fail, only feeds this log line.
local RR_OBJ_EVENTS_ADDR = 0x02036E38

local function rr_trace_log(cp, path_name, step_no, dir)
    local px, py = H.pos(cp)
    local base = OBJ_EVENTS_ADDR or RR_OBJ_EVENTS_ADDR
    local objs = {}
    for i = 1, 15 do
        local flags = memory.read_u8(base + i * 0x24)
        if (flags & 0x01) ~= 0 then
            local lid = memory.read_u8(base + i * 0x24 + 0x08)
            local ox = memory.read_s16_le(base + i * 0x24 + 0x10) - 7
            local oy = memory.read_s16_le(base + i * 0x24 + 0x12) - 7
            objs[#objs + 1] = string.format("obj%d(id=%d@%d,%d)", i, lid, ox, oy)
        end
    end
    local facing = memory.read_u8(base + 0x18) & 0x0F
    console.log(string.format(
        "[rr-trace] %s #%d dir=%s player=(%d,%d) facing=%d locked=%s %s",
        path_name, step_no, tostring(dir), px, py, facing,
        tostring(not H.scene_quiet(cp)), table.concat(objs, " ")))
end

--- FR/LG: byte-identical to play.follow (this function IS play.follow for them). RR only: a
--- live trace (patch/build/e2e_whiteout_gen3_a_result.txt, run 3) caught the whiteout_gen3 stall
--- red-handed -- the path's #2 Left step started with the field unlocked, an RR-only object
--- (local id 20, absent from FR/LG's map.json -- c23a8f46 / reference_rr_object_events.md: "RR
--- adds objects 10-12, four more coord events") walked adjacent to the player and locked the
--- field mid-step (facing forced to 4/Right, toward that object). A PURE idle-wait (run 4, 4
--- rounds x 300 frames) never saw the lock clear: locked=true held through every round, which
--- means it is not a silent script -- it is a message box (or a trainer's "sees you" intro)
--- waiting for A, exactly what playlib's own P.clear_dialogue exists for, and P.step's 6 short
--- attempts (each already calling clear_dialogue once) simply ran out too early against a
--- longer scene. So this re-implements P.follow's loop using only P's PUBLIC calls
--- (play.step/play.clear_dialogue/play.in_battle/play.handle_encounter/play.map/play.wait_at/
--- play.at/play.on_field, same primitives playlib itself uses), and on a stall taps A through
--- the lock (fighting an incidental battle for real, through the SAME P.handle_encounter
--- accounting play.follow uses -- the encounter budget and the whiteout/displacement check both
--- apply, not just the mash), then retries the SAME step -- bounded at 4 rounds.
---
--- WITNESSED, not blind (OMP cx-84088887): after each recovery round this checks the map is
--- still the one the step started on (a change here is a warp the recovery itself caused -- a
--- wrong dialogue choice, a menu selection, a trainer battle's own after-effect -- and FAILS
--- loud rather than letting P.step's own "a map change is a warp, and a warp is success" rule
--- wave it through), and only retries the directional step once the field is actually idle
--- (play.on_field + scene_quiet: no script running, no multichoice or menu still reading the
--- very button this loop is about to press again). A round that ends still locked simply loops
--- again, bounded at 4; a genuinely blocked tile still fails fast the moment neither a battle
--- nor a lock is left to wait out.
---
--- `p.battles == false` (a leg that owns its own battle after this call) is honoured exactly as
--- play.follow honours it: play.step already refuses to absorb the encounter and reports
--- "in_battle", and this loop must not then go fight it anyway -- that would silently override
--- the leg's own policy.
local function traced_follow(cp, path_name, label)
    if TITLE ~= "radical_red" then return play.follow(cp, path_name, label) end
    local p = assert(PATHS[path_name], "no PATHS entry " .. tostring(path_name))
    local start_map = play.map(cp)
    if not play.wait_at(cp, p.from[1], p.from[2], 120) then
        G.finish(false, string.format("%s (%s): start tile never settled at (%d,%d)",
            label, path_name, p.from[1], p.from[2]))
        return
    end
    local enc = { n = 0, max = p.max_encounters or (play.opts and play.opts.max_encounters) or 12 }
    if p.battles == false then enc = false end
    for i, dir in ipairs(p.dirs) do
        if RR_TRACE then rr_trace_log(cp, path_name, i, dir) end
        local ok, why = play.step(cp, dir, start_map, nil, enc)
        local rounds = 0
        while not ok and rounds < 4 and (play.in_battle(cp) or not H.scene_quiet(cp)) do
            rounds = rounds + 1
            if play.in_battle(cp) then
                if enc == false then
                    G.shot("stuck")
                    G.finish(false, string.format(
                        "%s (%s): step %s: an encounter started but this path refuses battles "
                        .. "(battles=false) -- at %s", label, path_name, dir, play.at(cp)))
                    return
                end
                -- Route through the SAME accounting play.follow uses: the encounter budget
                -- (P.handle_encounter counts and caps it) and the displacement/whiteout check
                -- (a battle that moves the player, or lands them anywhere but the heal map, is
                -- fatal, not absorbed) -- a direct play.fight_through call skipped both.
                local bx, by = H.pos(cp)
                play.handle_encounter(cp, enc, dir, { map = play.map(cp), x = bx, y = by })
            else
                for _ = 1, 20 do
                    play.clear_dialogue(cp)
                    if play.in_battle(cp) or H.scene_quiet(cp) then break end
                end
            end
            if RR_TRACE then
                console.log(string.format(
                    "[rr-trace] %s #%d dir=%s waited round %d locked=%s in_battle=%s",
                    path_name, i, tostring(dir), rounds, tostring(not H.scene_quiet(cp)),
                    tostring(play.in_battle(cp))))
            end
            -- Postcondition 1: still the same map. A warp here is not the lock clearing.
            local now_map = play.map(cp)
            if now_map ~= nil and now_map ~= start_map then
                G.shot("stuck")
                G.finish(false, string.format(
                    "%s (%s): step %s: recovery round %d warped from map %s to %s instead of "
                    .. "clearing the lock -- a wrong dialogue choice, menu selection or battle, "
                    .. "not the message box this loop exists to tap through",
                    label, path_name, dir, rounds, tostring(start_map), tostring(now_map)))
                return
            end
            -- Postcondition 2: no multichoice/menu left reading input. Only once the field is
            -- genuinely idle (same predicate the PC-exit wait above uses) is it safe to press
            -- `dir` again -- pressing it into a still-open menu could move its cursor instead of
            -- the player. Postcondition 3 (the step lands on the expected tile) is play.step's
            -- own job, called right here.
            if play.on_field(cp) and H.scene_quiet(cp) then
                ok, why = play.step(cp, dir, start_map, nil, enc)
            end
        end
        if not ok then
            if RR_TRACE then rr_trace_log(cp, path_name, i, tostring(dir) .. "-STALLED") end
            G.shot("stuck")
            local locked = rounds > 0 and string.format(
                " -- the field stayed locked through %d recovery round%s",
                rounds, rounds == 1 and "" or "s") or ""
            G.finish(false, string.format("%s (%s): step %s stalled at %s%s",
                label, path_name, dir, play.at(cp), locked))
            return
        end
        local now = play.map(cp)
        if now ~= nil and now ~= start_map then return end
    end
    if play.map(cp) == nil then
        G.finish(false, string.format(
            "%s (%s): the walk ended with the map id unreadable", label, path_name))
        return
    end
    local ex, ey = H.pos(cp)
    if p.to and (ex ~= p.to[1] or ey ~= p.to[2]) then
        G.finish(false, string.format(
            "%s (%s): walk ended at (%d,%d), not the path's to (%d,%d)",
            label, path_name, ex, ey, p.to[1], p.to[2]))
    end
end

--- Route either admitted respawn interior to Pallet Town (6,9), the shared resume origin.
--- The house's actual door landing is (6,8); the following verified step reaches (6,9).
local function recover_to_pallet_town(cp)
    local dest = whiteout_destination(cp)
    if not dest then return false end
    verify_destination(cp, "whiteout_recovery", dest)
    if dest.group == 4 and dest.num == 0 then
        play.follow(cp, "heal_house_to_door", "whiteout-recovery")
        warp_to(cp, "Down", 30, DEST.house_exit, "whiteout house exit")
        play.follow(cp, "house_exit_to_town_start", "whiteout-recovery")
    elseif dest.group == 5 and dest.num == 4 then
        play.follow(cp, "heal_center_to_door", "whiteout-recovery")
        warp_to(cp, "Down", 30, DEST.center_exit, "whiteout Center exit")
        traced_follow(cp, "pokecenter_door_to_route1_edge", "whiteout-recovery")
        warp_to(cp, "Down", 30, DEST.route1_north, "whiteout Viridian->Route1")
        play.follow(cp, "route1_north_to_south_edge", "whiteout-recovery")
        warp_to(cp, "Down", 30, DEST.pallet_north, "whiteout Route1->Pallet")
        play.follow(cp, "pallet_north_to_town_start", "whiteout-recovery")
    else
        G.finish(false, "whiteout_recovery_unsupported: no route for this respawn map")
        return false
    end
    G.phase("recovered", "back outside at " .. play.at(cp))
end

-- playlib.run_leg calls recover() OUTSIDE its pcall. Convert a second whiteout
-- during the long Viridian return walk to a named terminal here; other errors
-- retain their original failure rather than being recast as whiteouts.
local function guarded_recovery(cp, label, recover)
    local ok, err = pcall(recover, cp)
    if ok then return true end
    if type(err) == "table" and err.whiteout then
        G.shot("stuck")
        G.finish(false, label .. ": whiteout_during_recovery at " .. play.at(cp))
        return false
    end
    error(err, 0)
end

--- route1_catch and route1_faint own their own battle (hunt_encounter calls play.step with
--- enc=false precisely so THIS file, not playlib, decides how to fight/throw) -- which means
--- playlib's own whiteout detector (P.handle_encounter's `error({whiteout=true,...},0)`,
--- playlib.lua:288-297) never sees the displacement, and P.run_leg's recover()/resume()
--- machinery only ever fires on that exact signal shape. A leg that opts out of playlib fighting
--- its battles must raise the same signal itself, or a whiteout here just runs off the end of
--- the leg looking like a plain loss. `before_map/x/y` is the position the caller captured right
--- as the battle started (same convention as handle_encounter's own `before`).
check_whiteout = function(cp, before_map, before_x, before_y, checkpoint)
    local nmap = play.map(cp)
    local x, y = G.pos(cp)
    if nmap ~= before_map or x ~= before_x or y ~= before_y then
        local dest = whiteout_destination(cp, checkpoint)
        if not dest then return end
        if not verify_destination(cp, "whiteout_landing", dest) then return end
        G.phase("whiteout", string.format(
            "battle displaced the player from map %s (%d,%d) to the heal map %s at %s",
            tostring(before_map), before_x, before_y, tostring(nmap), play.at(cp)))
        error({ whiteout = true, map = nmap, from_map = before_map,
                from_x = before_x, from_y = before_y }, 0)
    end
end

--- Bounded wait for the action-menu witness (see the constants above), pressing A every OTHER
--- frame ONLY while the witness is false and the battle is still up -- the same "menu" step
--- shape probe_gen3_rr_bag.lua uses. Returns false either on timeout OR because the battle
--- itself ended before ever reaching the menu (nothing here needs the menu at that point); the
--- caller tells those two apart with play.in_battle(cp).
local function wait_for_action_menu(cp, budget)
    for i = 1, (budget or 1200) do
        if party_menu_up() then joypad.set({}); return "party" end
        if action_menu_up() then joypad.set({}); return true end
        if not play.in_battle(cp) then joypad.set({}); return false end
        if i % 2 == 0 then joypad.set({ A = true }) else joypad.set({}) end
        G.advance()
    end
    joypad.set({})
    return false
end

--- Wait for the menu witness and steer the remembered cursor to FIGHT(0).
--- FR run 20 proved the cursor can start on BAG(1); FR run 25e entered a
--- party menu from POKEMON(2). The incidental battle policy uses this on
--- every action-menu return. route1_catch then toggles to BAG(1), while
--- route1_faint mashes A; both need to know the press is landing on the menu
--- they think it is, not on the still-open "Wild X appeared!" intro text (FR run 19's bug).
--- A battle that ends before the menu ever comes up is not a failure -- there is nothing here
--- for either leg to press.
verify_fight_cursor = function(cp, label)
    if not play.in_battle(cp) then return end
    local ready = wait_for_action_menu(cp, 1200)
    if ready == "party" then
        if label == "incidental_battle" then return "party" end
        G.finish(false, label .. ": unexpected forced party menu before action selection")
        return
    end
    if not ready then
        if play.in_battle(cp) then
            G.shot("stuck")
            G.finish(false, string.format(
                "%s: neither action nor forced party menu came up (possible move-menu/no-PP "
                .. "path) at %s", label, play.at(cp)))
            return
        end
        return
    end
    -- The cursor can remain off FIGHT within one battle (FR run 20 read BAG(1)),
    -- although new battles and switch-in reset it. Steer with the pinned bit
    -- toggles of HandleInputChooseAction: Left clears bit0, Up clears bit1.
    for _ = 1, 4 do
        local c = action_cursor()
        if c == ACTION_FIGHT then return "fight" end
        if c % 2 == 1 then G.tap("Left", 3, 20) elseif c >= 2 then G.tap("Up", 3, 20) end
    end
    if action_cursor() ~= ACTION_FIGHT then
        G.shot("stuck")
        G.finish(false, string.format(
            "%s: could not steer the action cursor to FIGHT(0) (reads %d)", label, action_cursor()))
        return
    end
    return "fight"
end

--- Mandatory faint replacement only: source battle_scripts_1.s:2829-2836 opens
--- BS_FAINTED; battle_script_commands.c openpartyscreen uses SEND_OUT, not the
--- optional trainer shift prompt. In FR, an A on the fainted slot just prints
--- "has no energy" (party_menu.c:5916-5933). Read callback, input task, cursor,
--- and plaintext party HP before each selection. Never infer a slot from pixels.
--- A party record the helper may send in. RR (CFRU) keeps no secure checksum: lua/gen3/reads.lua
--- leaves checksum_ok nil there (the production rule; e2e_duo's gen3_record_problems agrees), so
--- nil passes on radical_red only -- vanilla still demands true. G5-RR-R1R3: rr_battle2's healthy
--- slot-1 catch (18/18) was refused on nil and A failed forced_party_no_healthy_mon.
-- ponytail: only the send-out uses it; the FR-only legs (verify_starter, owned_snapshot) keep `true`
--- One step of the forced send-out's cursor walk: "done", "Up", "Down", or nil, why. slotId is
--- gPartyMenu +9 on RR too (G5-RR-ORACLES-2: 13 CFRU sites load 0x0203B0A0 and ldrb +9, beside
--- FR's 28 identical ones), and 6 / 7 are the menu's CONFIRM / CANCEL rows below every mon (pret
--- party_menu.c, PARTY_SIZE / PARTY_SIZE + 1): R1-R3 at f4ef3f5a read one of those and failed
--- forced_party_cursor_invalid. From there, Up walks back into the mons. Self-contained.
local function cursor_step(slot, target, count)
    if slot == target then return "done" end
    if slot < 0 or slot > 7 then return nil, "slotId " .. slot .. " is no party-menu row" end
    return (slot >= count or slot > target) and "Up" or "Down"
end
local function record_ok(mon, title)
    return mon.checksum_ok == true or (title == "radical_red" and mon.checksum_ok == nil)
end
send_out_healthy_mon = function(cp, label)
    if not party_menu_up() then G.finish(false, label .. ": forced_party_menu_missing"); return false end
    local kind = memory.read_u8(PARTY_MENU_ADDR + 8) & 0x0F
    local action = memory.read_u8(PARTY_MENU_ADDR + PARTY_MENU_ACTION_OFF)
    if kind ~= 1 or action ~= PARTY_ACTION_SEND_OUT then
        G.finish(false, label .. ": forced_party_wrong_action: expected in-battle SEND_OUT")
        return false
    end
    local count = memory.read_u8(PARTY_COUNT_ADDR)
    if count < 2 or count > 6 then
        G.finish(false, label .. ": forced_party_count: need a replacement party")
        return false
    end
    local records, why = reader.read_party()
    if not records or #records ~= count then
        G.finish(false, label .. ": forced_party_unreadable: " .. tostring(why)); return false
    end
    local target
    for slot = 0, count - 1 do
        local base = PARTY_BASE + slot * MON_SIZE
        local mon = records[slot + 1]
        if memory.read_u16_le(base + OFF_HP) > 0
           and memory.read_u16_le(base + OFF_MAXHP) > 0
           and mon.species ~= 0 and mon.has_species == 1 and record_ok(mon, TITLE)
           and mon.is_bad_egg == 0 and mon.is_egg == 0
           and mon.is_egg_flag == 0 then target = slot; break end
    end
    if not target then G.finish(false, label .. ": forced_party_no_healthy_mon"); return false end
    local ready = false
    for _ = 1, 1200 do
        local task = party_task()
        if not party_menu_up() then break end
        if task == TASK_CHOOSE_MON then ready = true; break end
        if task == TASK_RETURN_AFTER_TEXT then G.tap("A", 3, 13)
        elseif task == TASK_SELECTION_POPUP then
            -- A stray earlier press may have opened the fainted slot's popup.
            -- B selects CANCEL1 and returns to Task_HandleChooseMonInput
            -- (party_menu.c:3083-3087,3391-3400).
            G.tap("B", 3, 13)
        else G.advance() end
    end
    if not ready then G.finish(false, label .. ": forced_party_input_not_ready"); return false end
    for _ = 1, 10 do
        local slot = memory.read_u8(PARTY_MENU_ADDR + PARTY_MENU_SLOT_OFF)
        local step, bad = cursor_step(slot, target, count)
        if step == "done" then break end
        if not step then G.finish(false, label .. ": forced_party_cursor_invalid: " .. bad); return false end
        G.tap(step, 3, 20)
        if party_task() ~= TASK_CHOOSE_MON then
            G.finish(false, label .. ": forced_party_cursor_lost_input"); return false
        end
    end
    if memory.read_u8(PARTY_MENU_ADDR + PARTY_MENU_SLOT_OFF) ~= target then
        G.finish(false, label .. ": forced_party_cursor_stalled at slotId "
                 .. memory.read_u8(PARTY_MENU_ADDR + PARTY_MENU_SLOT_OFF) .. " for " .. target); return false
    end
    if memory.read_u16_le(PARTY_BASE + target * MON_SIZE + OFF_HP) == 0 then
        G.finish(false, label .. ": forced_party_target_fainted"); return false
    end
    G.tap("A", 3, 20) -- healthy party slot -> SEND OUT / SUMMARY / CANCEL popup
    local popup = false
    for _ = 1, 180 do
        if not party_menu_up() then break end
        if party_task() == TASK_SELECTION_POPUP then popup = true; break end
        G.advance()
    end
    if not popup then G.finish(false, label .. ": forced_party_sendout_popup_missing"); return false end
    if memory.read_u8(PARTY_MENU_ADDR + PARTY_MENU_SLOT_OFF) ~= target then
        G.finish(false, label .. ": forced_party_popup_target_changed"); return false
    end
    G.tap("A", 3, 20) -- SEND OUT is popup row 0 (src/data/party_menu.h:1095)
    for _ = 1, 900 do
        if not party_menu_up() then return true end
        if party_task() == TASK_RETURN_AFTER_TEXT then
            G.finish(false, label .. ": forced_party_sendout_rejected"); return false
        end
        G.advance()
    end
    G.finish(false, label .. ": forced_party_sendout_never_returned_to_battle")
    return false
end

--- The fight/settle/whiteout-check tail shared by route1_catch_loop and route1_faint: mash A
--- until the battle clears, then let the post-battle scene settle BEFORE reading the map, and
--- only then hand off to check_whiteout.
---
--- ROOT CAUSE (FR run 19): without the settle wait, in_battle can clear a good while before a
--- whiteout's own heal-and-warp sequence actually lands the player on the heal map -- the
--- trailing "no more usable POKeMON... whited out!" message and the walk-home narration both
--- run AFTER the battle callback itself has already handed control back. check_whiteout, called
--- right then, reads the OLD map and sees no whiteout at all; the actual warp fires later,
--- unnoticed, in the MIDDLE of the next hunt_encounter's walk -- and because play.step() counts
--- any readable map change as ordinary progress, that hunt just wanders the house for its whole
--- cycle budget and reports "no wild encounter", which is exactly what FR run 19's receipt
--- showed (two real encounters fought and fainted, no whiteout-recover phase logged, then "40
--- cycles ... at (7,4)" -- the player's own house). wait_scene_settled is the same call
--- opts.battle already makes after every OTHER absorbed battle in this file; this is that same
--- fix, applied where a leg fights its own.
local function resolve_battle_and_check_whiteout(cp, mash_budget)
    local before_map, before_x, before_y = play.map(cp), G.pos(cp)
    local checkpoint = last_heal_checkpoint(cp)
    if not checkpoint then return false end
    local resolved = play.mash_a(mash_budget or 160, function() return not play.in_battle(cp) end)
    if resolved and not play.wait_scene_settled(cp, 1800) then
        G.finish(false, "whiteout_settle: post-battle scene never settled"); return false
    end
    check_whiteout(cp, before_map, before_x, before_y, checkpoint)
    return resolved
end

--- Whiteout recovery for route1_catch/route1_faint: back out to Pallet Town
--- (recover_to_pallet_town), then continue to the Route 1 grass loop's own origin. Reuses the
--- SAME two PATHS entries a normal walk there already uses -- town_start_to_oak_trigger's
--- (6,9)->(12,1) route and route1_south_to_grass_spot's (12,39)->(12,37) -- rather than a new
--- BFS: by this point in the run OakTrigger's gate (var VAR_MAP_SCENE_PALLET_TOWN_OAK==0) has
--- long since gone false for real (the starter leg already fired it), so walking back over
--- (12,1) is a plain tile crossing, not a re-trigger (see that PATHS entry's own comment).
--- Verified with the tool the file's own header requires: `python tools/gba_map.py
--- "patch/build/gen3_Pokemon_-_FireRed_Version_(USA).gba" --map 3.0 --bfs 6,9 12,1` and
--- `--map 3.19 --bfs 12,39 12,37` both returned exactly these two PATHS entries' own dirs.
---
--- grass_step MUST reset to 1: left pointing at whatever step a mid-square whiteout
--- interrupted, the next hunt would walk off the band from the fresh origin (12,37) instead of
--- starting the loop there (same class of bug hunt_encounter's own resume-in-place comment
--- documents for an in-place interruption; this is the equivalent for an interruption that
--- teleports the player away entirely).
local function recover_to_route1_grass(cp)
    recover_to_pallet_town(cp)
    play.follow(cp, "town_start_to_oak_trigger", "whiteout-recovery")
    warp_to(cp, "Up", 30, DEST.route1_south, "whiteout Pallet->Route1")
    play.follow(cp, "route1_south_to_grass_spot", "whiteout-recovery")
    grass_step = 1
    G.phase("recovered", "back in the grass at " .. play.at(cp))
end

--- Heal at a Poke Center counter: walk to the talking tile, face the nurse, A through her
--- dialogue, and require slot 0 to come back at FULL HP. The terminal is the party, never the
--- number of presses (pret src/pokemon_center.c heals via the standard script; the counter
--- metatile behaviour that lets the interaction reach her is cited on the PATHS entry).
local function heal_at_nurse(cp, label)
    play.follow(cp, "pokecenter_entrance_to_nurse", label)
    G.tap("Up", 2, 13)
    local hp0, max0 = slot0_hp()
    G.phase("heal-start", string.format("%s: slot0 %d/%d", label, hp0, max0))
    local healed = false
    for _ = 1, 120 do
        local hp, maxhp = slot0_hp()
        if maxhp > 0 and hp == maxhp then healed = true; break end
        G.tap("A", 3, 20)
    end
    if not healed then
        G.shot("stuck")
        local hp, maxhp = slot0_hp()
        G.finish(false, string.format("%s: the nurse never restored slot 0 (%d/%d)",
                                      label, hp, maxhp))
    end
    -- The "we hope to see you again" bow is scripted; let it finish before walking off.
    play.wait_scene_settled(cp, 1800)
    local hp, maxhp = slot0_hp()
    G.phase("healed", string.format("%s: slot0 %d/%d", label, hp, maxhp))
end

-- ── FR PC stages, read through the symbols of pret/pokefirered@c75f352 ──────────────────────
-- data/scripts/pc.inc:1-55; src/script_menu.c:977-1036; src/menu.c:9-25,337.
-- sMenu is 0203ADE4 (sym:462, size 0x0C); 020399C0 is mon_markings.c's
-- unrelated sMenu pointer. Task_MultichoiceMenu_HandleInput=0809CC98 (sym:6719).
-- src/pokemon_storage_system_menu.c:230-371: Task_PCMainMenu=0808C39C,
-- task.data[0]=state (2 HANDLE_INPUT), data[1]=selected row (0 WITHDRAW,1 DEPOSIT).
-- src/pokemon_storage_system_data.c:16-17,69-76: sCursorArea/sCursorPosition
-- are 02039820/21 (sym:315-316), 0=box, 1=party; popup cursor is sMenu+2.
local PC_TASKS, PC_TASK_SIZE = S.TASKS_BASE, 40 -- sym:829; include/task.h:14-25
local PC_MULTICHOICE = S.PC_MULTICHOICE
local PC_MAIN_MENU = S.PC_MAIN_MENU
local PC_STORAGE_MAIN = S.PC_STORAGE_MAIN
local PC_ON_SELECTED = S.PC_ON_SELECTED
local PC_DEPOSIT_MENU = S.PC_DEPOSIT_MENU
local PC_WITHDRAW_MON = S.PC_WITHDRAW_MON
local PC_RELEASE_MON = S.PC_RELEASE_MON
-- Task_OnBPressed (pokemon_storage_system_tasks.c:1988-2035): B in storage asks "Continue BOX
-- operations?". The cursor starts on NO, not YES: ShowYesNoWindow(cursorPos)
-- (tasks.c:2595-2599) calls CreateYesNoMenu(..., initialCursorPos = 1) -- that 7th argument IS
-- the initial row (include/menu.h:49) -- and then Menu_MoveCursorNoWrapAround(cursorPos), which
-- moves by a DELTA (menu.c:323-334); ShowYesNoWindow(0)'s zero moves nothing, so the cursor
-- stays on row 1 of gText_YesNo "YES\nNO" (strings.c:156).
-- Confirmed PHYSICALLY: FR run 28d's receipt logs `menu_cursor=1` while this task is up
-- (docs/gen3/probes/shadow_fr_play_run28_2026-09-23.txt:73). With the cursor on NO, A selects
-- NO and B is MENU_B_PRESSED: BOTH exit (state 2 case 1 / MENU_B_PRESSED, tasks.c:2016-2031);
-- only Down+A (YES, case 0) stays in the box. B is pressed because its outcome cannot depend
-- on where the cursor happens to be.
local PC_ON_B_PRESSED = S.PC_ON_B_PRESSED
-- S.PC_MENU_BASE is absent for radical_red (card C4-LG2: unproven there); the `and` guards the
-- arithmetic so loading stays nil-safe instead of erroring here at module load. A helper that
-- then reads a nil PC_MENU_CURSOR/PC_MENU_MAX_CURSOR fails where it is actually called, same as
-- every other unproven RR constant.
local PC_MENU_CURSOR = S.PC_MENU_BASE and (S.PC_MENU_BASE + 2)
local PC_MENU_MAX_CURSOR = S.PC_MENU_BASE and (S.PC_MENU_BASE + 4) -- src/menu.c:9-25
local PC_RESULT = S.PC_RESULT -- sym:231 gSpecialVar_Result, VAR_RESULT
local PC_CURSOR_AREA, PC_CURSOR_POS = S.PC_CURSOR_AREA, S.PC_CURSOR_POS
local PC_STORAGE_PTR = S.PC_STORAGE_PTR -- sym:307; gStorage->state +0, boxOption +1
local PC_DEPOSIT_BOX_ID = S.PC_DEPOSIT_BOX_ID -- sym:310; sDepositBoxId
-- gStorage->boxOption is one enum (OPTION_WITHDRAW 0, OPTION_DEPOSIT 1, OPTION_MOVE_MONS 2,
-- include/pokemon_storage_system_internal.h:17-24) and CURSOR_AREA_* is another (IN_BOX 0,
-- IN_PARTY 1, :108-115); they merely happen to share 0/1. A popup offers the option its
-- cursor's own area implies, so map the area instead of comparing the two enums directly
-- (C3-40, finding 5 of cx-006e6f09: a MOVE-MONS popup would have slipped through).
local PC_POPUP_OPTION = { [0] = 0, [1] = 1 } -- CURSOR_AREA_IN_BOX -> OPTION_WITHDRAW,
                                             -- CURSOR_AREA_IN_PARTY -> OPTION_DEPOSIT
local PC = {}

local function pc_task(fn)
    for i = 0, 15 do
        local base = PC_TASKS + i * PC_TASK_SIZE
        if memory.read_u8(base + 4) ~= 0 and memory.read_u32_le(base) == fn then
            return base
        end
    end
end

local function pc_storage()
    local ptr = memory.read_u32_le(PC_STORAGE_PTR)
    if ptr < 0x02000000 or ptr >= 0x02040000 or ptr % 4 ~= 0 then return nil end
    return ptr
end

-- BizHawk's memory.* is userdata: a nil address raises "Argument number 1 is invalid" rather
-- than returning something inert. PC_STORAGE_PTR, PC_RESULT and PC_MENU_BASE (-> PC_MENU_CURSOR)
-- have no radical_red entry in gen3_title_syms.lua, so on RR they ARE nil, and the unguarded
-- reads below raised on the very check meant to explain a PC-stage failure (never printing) — a
-- run 28c-class diagnostic gap, on RR. -1 stands in for "not proven on this title".
local function safe_read(fn, addr)
    if addr == nil then return -1 end
    return fn(addr)
end

--- What owned input when a PC stage failed: every active task's func, gStorage->state and the
--- script context status byte (sGlobalScriptContextStatus 0x03000EA8, 2 = shutdown). A named
--- stage without this left FR run 28c undiagnosable. Wrapped in pcall so an address this hasn't
--- been proven for on some future title still can't turn a diagnostic dump into the crash that
--- masks the timeout it was meant to explain.
local function pc_state_dump()
    local ok, result = pcall(function()
        local tasks = {}
        for i = 0, 15 do
            local base = PC_TASKS + i * PC_TASK_SIZE
            if memory.read_u8(base + 4) ~= 0 then
                tasks[#tasks + 1] = string.format("%08X", memory.read_u32_le(base))
            end
        end
        local sp = safe_read(memory.read_u32_le, PC_STORAGE_PTR)
        local st = (sp >= 0x02000000 and sp < 0x02040000) and memory.read_u8(sp) or -1
        return string.format("tasks=[%s] storage_state=%d script_status=%d result=%d menu_cursor=%d",
            table.concat(tasks, ","), st, safe_read(memory.read_u8, S.SCRIPT_CONTEXT_STATUS_ADDR),
            safe_read(memory.read_u16_le, PC_RESULT), safe_read(memory.read_u8, PC_MENU_CURSOR))
    end)
    if ok then return result end
    return "pc_state_dump failed: " .. tostring(result)
end

local function pc_fail(label, stage)
    G.shot("stuck")
    G.finish(false, label .. ": pc_" .. stage .. " " .. pc_state_dump())
    return false
end

local function pc_poll(predicate, budget)
    for _ = 1, budget or 900 do
        if predicate() then return true end
        G.advance()
    end
    return false
end

local function pc_wait(label, stage, predicate, budget)
    if pc_poll(predicate, budget) then return true end
    return pc_fail(label, stage)
end

function PC.open(cp, label)
    -- Run 27b resumed while this exact multichoice was already up. A stage may
    -- consume a press, but no fixed number of A presses counts as progress.
    if not pc_task(PC_MULTICHOICE) and not pc_task(PC_MAIN_MENU) then
        if G.pred_ok(cp, "script_context_status") then G.tap("A", 3, 13) end
        for _ = 1, 12 do
            if pc_task(PC_MULTICHOICE) or pc_task(PC_MAIN_MENU) then break end
            for _ = 1, 90 do
                if pc_task(PC_MULTICHOICE) or pc_task(PC_MAIN_MENU) then break end
                G.advance()
            end
            if pc_task(PC_MULTICHOICE) or pc_task(PC_MAIN_MENU) then break end
            if G.pred_ok(cp, "script_context_status") then
                return pc_fail(label, "interaction_not_started")
            end
            G.tap("A", 3, 13) -- script text, while the script is witnessed busy
        end
    end
    if not pc_task(PC_MULTICHOICE) and not pc_task(PC_MAIN_MENU) then
        return pc_fail(label, "which_pc_menu_missing")
    end
    if pc_task(PC_MULTICHOICE) then
        -- CreatePCMenuWindow initializes row 0; refuse a resumed wrong row.
        if memory.read_u8(PC_MENU_CURSOR) ~= 0 then return pc_fail(label, "which_pc_wrong_row") end
        local rows = memory.read_u8(PC_MENU_MAX_CURSOR) + 1
        if rows < 3 or rows > 5 then return pc_fail(label, "which_pc_wrong_row_count") end
        for _ = 1, 12 do
            if pc_task(PC_MAIN_MENU) then break end
            if pc_task(PC_MULTICHOICE) then
                -- NO re-read of the row here: the entry read above covers a RESUMED menu with
                -- the cursor parked on another row, and A is this loop's only press -- nothing
                -- inside PC.open can move the cursor (the guard that used to sit here was
                -- undetectable by mutation, cx-006e6f09).
                G.tap("A", 3, 13) -- Someone's/Bill's PC, verified row 0
            elseif not G.pred_ok(cp, "script_context_status") then
                G.tap("A", 3, 13) -- Accessed PC / storage opened script boxes
            else
                for _ = 1, 90 do
                    if pc_task(PC_MAIN_MENU) or pc_task(PC_MULTICHOICE) then break end
                    G.advance()
                end
            end
        end
        if pc_task(PC_MULTICHOICE) then return pc_fail(label, "which_pc_choice_not_consumed") end
        -- VAR_RESULT may already contain a stale zero; only read it after the
        -- Task_MultichoiceMenu_HandleInput witness has disappeared (pc.inc:20-37).
        if not pc_task(PC_MULTICHOICE) and memory.read_u16_le(PC_RESULT) ~= 0 then
            return pc_fail(label, "which_pc_result_not_someones")
        end
    end
    local main = pc_task(PC_MAIN_MENU)
    if not main then return pc_fail(label, "storage_top_menu_missing") end
    if not pc_wait(label, "storage_top_not_ready", function()
        return pc_task(PC_MAIN_MENU) and memory.read_u16_le(main + 8) == 2
    end, 900) then return false end
    if memory.read_u16_le(main + 10) ~= 0 then return pc_fail(label, "storage_top_wrong_row") end
    return true
end

function PC.mode(label, row)
    local main = pc_task(PC_MAIN_MENU)
    if not main or memory.read_u16_le(main + 8) ~= 2 then return pc_fail(label, "storage_top_not_ready") end
    if memory.read_u8(PC_MENU_MAX_CURSOR) ~= 4 then return pc_fail(label, "storage_top_wrong_row_count") end
    for _ = 1, 4 do
        if memory.read_u16_le(main + 10) == row then break end
        G.tap("Down", 3, 20)
        if not pc_wait(label, "storage_top_cursor_stalled", function()
            return memory.read_u16_le(main + 10) == row
        end, 90) then return false end
    end
    if memory.read_u16_le(main + 10) ~= row then return pc_fail(label, "storage_top_wrong_row") end
    for _ = 1, 4 do
        G.tap("A", 3, 13)
        for _ = 1, 900 do
            if pc_task(PC_STORAGE_MAIN) then break end
            G.advance()
        end
        if pc_task(PC_STORAGE_MAIN) then break end
        if not pc_task(PC_MAIN_MENU) or memory.read_u16_le(main + 8) ~= 2
           or memory.read_u16_le(main + 10) ~= row then break end
    end
    if not pc_task(PC_STORAGE_MAIN) then return pc_fail(label, "storage_mode_not_entered") end
    local storage = pc_storage()
    if not storage or memory.read_u8(storage + 1) ~= row then
        return pc_fail(label, "storage_mode_mismatch")
    end
    return pc_wait(label, "storage_cursor_not_ready", function()
        return pc_task(PC_STORAGE_MAIN) and memory.read_u8(storage) == 0
    end, 900)
end

function PC.cursor(label, area, pos)
    local storage = pc_storage()
    if not storage or not pc_task(PC_STORAGE_MAIN) then return pc_fail(label, "storage_cursor_not_ready") end
    if memory.read_u8(PC_CURSOR_AREA) ~= area then return pc_fail(label, "storage_cursor_wrong_area") end
    for _ = 1, 8 do
        local current = memory.read_u8(PC_CURSOR_POS)
        if current == pos then return true end
        if current > 5 then return pc_fail(label, "storage_cursor_invalid") end
        G.tap(current < pos and "Down" or "Up", 3, 20)
        if not pc_wait(label, "storage_cursor_stalled", function()
            return memory.read_u8(PC_CURSOR_POS) ~= current
        end, 90) then return false end
        if memory.read_u8(PC_CURSOR_AREA) ~= area then return pc_fail(label, "storage_cursor_wrong_area") end
    end
    -- Reached only by a cursor that keeps moving but never lands on the row: a +1 march from any
    -- start reaches its position inside this budget (C3-41 finding 2).
    return pc_fail(label, "storage_cursor_stalled")
end

function PC.popup(label, area, pos, row)
    if not PC.cursor(label, area, pos) then return false end
    local storage = pc_storage()
    if memory.read_u8(storage + 1) ~= PC_POPUP_OPTION[area] then
        return pc_fail(label, "storage_popup_wrong_mode")
    end
    for _ = 1, 4 do
        if pc_task(PC_ON_SELECTED) and memory.read_u8(storage) == 2 then break end
        if not pc_task(PC_STORAGE_MAIN) then return pc_fail(label, "storage_popup_unexpected_task") end
        G.tap("A", 3, 13)
        for _ = 1, 120 do
            if pc_task(PC_ON_SELECTED) and memory.read_u8(storage) == 2 then break end
            G.advance()
        end
    end
    if not pc_task(PC_ON_SELECTED) or memory.read_u8(storage) ~= 2 then
        return pc_fail(label, "storage_popup_missing")
    end
    local max_row = memory.read_u8(PC_MENU_MAX_CURSOR)
    if max_row ~= 4 then return pc_fail(label, "storage_popup_wrong_row_count") end
    -- The cursor is tested BEFORE each Down, so a budget of max_row presses reaches the last row
    -- (4, CANCEL) but never tests it: the popup would sit on row 4 and the leg would report
    -- storage_popup_cursor_stalled one press short (C3-41 finding 2). max_row + 1 walks 0..4.
    for _ = 1, max_row + 1 do
        local current = memory.read_u8(PC_MENU_CURSOR)
        if current == row then return true end
        if current > row then return pc_fail(label, "storage_popup_wrong_row") end
        G.tap("Down", 3, 20)
        if not pc_wait(label, "storage_popup_cursor_stalled", function()
            return memory.read_u8(PC_MENU_CURSOR) == current + 1
        end, 90) then return false end
    end
    -- Only a cursor that keeps moving but never lands on the row gets here: a +1 march from any
    -- start reaches its row inside the budget above.
    return pc_fail(label, "storage_popup_cursor_stalled")
end

function PC.select(label, task)
    if not pc_task(PC_ON_SELECTED) then return pc_fail(label, "storage_popup_missing") end
    for _ = 1, 4 do
        G.tap("A", 3, 13)
        if pc_poll(function()
            return pc_task(task) or not pc_task(PC_ON_SELECTED)
        end, 180) then
            if pc_task(task) then return true end
            return pc_fail(label, "storage_choice_wrong_task")
        end
    end
    return pc_fail(label, "storage_choice_not_taken")
end

function PC.box(label)
    local storage = pc_storage()
    if not storage or not pc_task(PC_DEPOSIT_MENU) then return pc_fail(label, "box_chooser_missing") end
    if not pc_wait(label, "box_chooser_not_ready", function()
        return pc_task(PC_DEPOSIT_MENU) and memory.read_u8(storage) == 1
    end, 900) then return false end
    -- CreateChooseBoxMenuSprites(sDepositBoxId) starts at the last confirmed
    -- box (tasks.c:1192-1222); with no directional input, zero means box 0.
    if memory.read_u8(PC_DEPOSIT_BOX_ID) ~= 0 then return pc_fail(label, "box_chooser_wrong_box") end
    for _ = 1, 4 do
        G.tap("A", 3, 13)
        for _ = 1, 2400 do
            if pc_task(PC_STORAGE_MAIN) then return true end
            if not pc_task(PC_DEPOSIT_MENU) then return pc_fail(label, "box_deposit_wrong_task") end
            local state = memory.read_u8(storage)
            if state == 4 then return pc_fail(label, "box_deposit_box_full") end
            if state == 1 and _ > 120 then break end -- only retry a lost press at the chooser
            G.advance()
        end
    end
    return pc_fail(label, "box_deposit_not_committed")
end

function PC.withdraw(label)
    return pc_wait(label, "withdraw_not_completed", function()
        return pc_task(PC_STORAGE_MAIN)
    end, 2400)
end

function PC.release(label)
    local storage = pc_storage()
    if not storage or not pc_task(PC_RELEASE_MON) then return pc_fail(label, "release_confirmation_missing") end
    if not pc_wait(label, "release_confirmation_not_ready", function()
        return pc_task(PC_RELEASE_MON) and memory.read_u8(storage) == 1
    end, 900) then return false end
    if memory.read_u8(PC_MENU_CURSOR) ~= 1 then return pc_fail(label, "release_confirmation_not_no") end
    G.tap("Up", 3, 20)
    if memory.read_u8(PC_MENU_CURSOR) ~= 0 then return pc_fail(label, "release_confirmation_not_yes") end
    G.tap("A", 3, 13)
    if not pc_wait(label, "release_not_confirmed", function()
        return pc_task(PC_RELEASE_MON) and memory.read_u8(storage) == 4
    end, 2400) then return false end
    G.tap("A", 3, 13) -- MSG_WAS_RELEASED -> MSG_BYE_BYE, src/tasks.c:1307-1339
    if not pc_wait(label, "release_bye_message_missing", function()
        return pc_task(PC_RELEASE_MON) and memory.read_u8(storage) == 5
    end, 900) then return false end
    G.tap("A", 3, 13)
    return pc_wait(label, "release_not_completed", function()
        return pc_task(PC_STORAGE_MAIN)
    end, 2400)
end

--- THE PARTY COUNT IS A LIE WHILE THE PC IS OPEN. gPlayerPartyCount is recomputed on storage
--- exit, not at the transfer (the R9 note's completion row; PHYSICAL on RR, where the census
--- read party=3 throughout even after TryStorePartyMonInBox fired). So leaving the PC is part
--- of the operation, and every assertion in these legs is made on the field afterwards.
---
--- The leaving itself is playlib's leave_menu: on_field goes true while the PC's "See you
--- later!" textbox is still up, and stopping there shifts every press of the NEXT open by one
--- (PHYSICAL, RR r5b/r5c -- it turned a withdraw into a second deposit).
--- Has B closed the PC owner list (CreatePCMenu's multichoice) without choosing a row? FR/LG:
--- Task_MultichoiceMenu_HandleInput wrote SCR_MENU_CANCEL (127) into gSpecialVar_Result (pret
--- script_menu.c) -- `cancel_seen` latches it on any frame since the B. radical_red (G5-RR-PC):
--- the whole path is FR's byte for byte -- EventScript_PC/PCMainMenu/ChoosePCMenu/TurnOffPC,
--- CreatePCMenu, the multichoice task, and the TurnOffPC specials' gSpecials entries 0xD7/0x190
--- and bodies -- yet live boxsync/whiteout at e99c3760 closed the list, shut the script down and
--- landed on the field (live tasks: Task_WeatherMain, Task_RunPerStepCallback,
--- Task_RunTimeBasedEvents and the Center's Union Room trio -- field tasks only) with
--- gSpecialVar_Result reading 0 throughout. On RR the witness is therefore "the list closed
--- and no PC task took over"; leave_storage's field-terminal wait after this is what proves the
--- PC turned off (a chosen row would reopen storage or a message and never reach it). Self-
--- contained (no upvalues) so tests run this exact body.
local function owner_list_closed(multichoice_live, cancel_seen, title, pc_task_live)
    if multichoice_live then return false end
    if cancel_seen then return true end
    return title == "radical_red" and not pc_task_live
end
local function leave_storage(cp, label)
    -- pc.inc:50-55 loops back to EventScript_PCMainMenu after storage; the
    -- first B exits storage, the second B cancels the owner list (VAR_RESULT
    -- 127). Only script.c's SHUTDOWN+unlocked pair is a field terminal.
    for step = 1, 24 do
        if pc_task(PC_MULTICHOICE) then break end
        G.phase("pc-exit", string.format("step=%d %s", step, pc_state_dump()))
        local storage = pc_storage()
        if pc_task(PC_STORAGE_MAIN) and storage and memory.read_u8(storage) == 0 then
            G.tap("B", 3, 13)
        elseif pc_task(PC_ON_B_PRESSED) then
            -- the Continue-BOX yes/no: B only. Its cursor starts on NO, so A would exit too --
            -- but A's outcome depends on where the cursor is while B's never does. (FR run 28b
            -- looped on the STORAGE TOP MENU this exits to, not on this prompt: run 28c's dump
            -- shows Task_PCMainMenu live across every stuck step.)
            if storage and memory.read_u8(storage) == 2 then G.tap("B", 3, 13) else G.advance() end
        elseif pc_task(PC_MAIN_MENU) then
            -- Leaving the box lands on the storage MAIN menu (WITHDRAW/DEPOSIT/..., PHYSICAL FR
            -- run 28d), one level above the owner list: B there is MENU_B_PRESSED == SEE YA!
            -- (pokemon_storage_system_menu.c:263-290). Only while it accepts input (state 2).
            local main = pc_task(PC_MAIN_MENU)
            if memory.read_u16_le(main + 8) == 2 then G.tap("B", 3, 13) else G.advance() end
        elseif pc_task(PC_STORAGE_MAIN) or pc_task(PC_ON_SELECTED) or pc_task(PC_DEPOSIT_MENU)
            or pc_task(PC_WITHDRAW_MON) or pc_task(PC_RELEASE_MON) then
            G.advance()      -- ANY storage task owning input: A here would act inside the box
        elseif not G.pred_ok(cp, "script_context_status") then
            G.tap("A", 3, 13) -- PC script's message boxes before the owner list
        else
            G.advance()
        end
        for _ = 1, 90 do
            if pc_task(PC_MULTICHOICE) then break end
            G.advance()
        end
    end
    if not pc_task(PC_MULTICHOICE) then return pc_fail(label, "exit_owner_list_missing") end
    local rows = memory.read_u8(PC_MENU_MAX_CURSOR) + 1
    if rows < 3 or rows > 5 then return pc_fail(label, "exit_owner_row_count") end
    G.tap("B", 3, 13)
    local saw_cancel = false
    if not pc_wait(label, "exit_owner_not_canceled", function()
        saw_cancel = saw_cancel or memory.read_u16_le(PC_RESULT) == 127
        return owner_list_closed(pc_task(PC_MULTICHOICE) ~= nil, saw_cancel, TITLE,
                                 pc_task(PC_MAIN_MENU) ~= nil or pc_task(PC_STORAGE_MAIN) ~= nil)
    end, 180) then return false end
    G.phase("pc-exit", string.format("owner list closed cancel_seen=%s %s", tostring(saw_cancel), pc_state_dump()))
    if not pc_wait(label, "exit_not_field", function()
        return play.on_field(cp) and G.pred_ok(cp, "script_context_status")
           and G.pred_ok(cp, "field_controls_locked")
           and not pc_task(PC_STORAGE_MAIN) and not pc_task(PC_MAIN_MENU)
           and not pc_task(PC_MULTICHOICE)
    end, 900) then return false end
    return true
end
PC.leave = leave_storage
PC.dump = pc_state_dump      -- every active task + PC state, for a caller's timeout line

local LEGS = {}

-- ── leg: starter ─────────────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "starter",
    exercises = { "mon_given", "map_load" },
    source = {
        "data/maps/PalletTown/map.json (coord_events OakTriggerLeft @ 12,1)",
        "data/maps/PalletTown/scripts.inc:169-217 (OakTrigger: lockall, lead player to the lab, warp MAP_PALLET_TOWN_PROFESSOR_OAKS_LAB 6 12)",
        "data/maps/PalletTown_ProfessorOaksLab/scripts.inc:44-48,199-227 (OnFrame ChooseStarterScene: scripted Oak+player movement, ends VAR_MAP_SCENE_PALLET_TOWN_PROFESSOR_OAKS_LAB=2)",
        "data/maps/PalletTown_ProfessorOaksLab/map.json (object_events SquirtleBall @ 9,4; (9,5) one tile south is the only walkable approach — collision=1 at (9,4) itself, confirmed with the same PATHS/collision method as every door in this file)",
        "data/maps/PalletTown_ProfessorOaksLab/scripts.inc:1212-1223 (SquirtleBall: lock; faceplayer — the object turns to face the player, matching facing Up from (9,5) — only ConfirmStarterChoice-reachable once scene==2, else \"Those are Poke Balls\")",
        "data/maps/PalletTown_ProfessorOaksLab/scripts.inc:1092-1096 (ConfirmSquirtle: msgbox ..., MSGBOX_YESNO)",
        "src/script_menu.c:873 (ScriptMenu_YesNo -> DisplayYesNoMenuDefaultYes: every MSGBOX_YESNO in this file, including the nickname prompt, defaults to YES)",
        "data/maps/PalletTown_ProfessorOaksLab/scripts.inc:1115-1134 (ChoseStarter: givemon PLAYER_STARTER_SPECIES,5 at line 1122 fires before the nickname prompt at line 1129 -- Text_GiveNicknameToThisMon, MSGBOX_YESNO)",
        "src/script_menu.c:887-913 (Task_YesNoMenu_HandleInput: MENU_B_PRESSED is handled identically to selecting NO -- gSpecialVar_Result=FALSE -- so B declines the nickname without opening the naming screen)",
        "data/maps/PalletTown_ProfessorOaksLab/scripts.inc:1140-1180 (RivalPicksStarter -> RivalWalksToX -> RivalTakesStarter: trailing rival dialogue, all plain `message`/`msgbox` with no further MSGBOX_YESNO)",
    },
    run = function(cp)
        -- SEED LANDING TILE (card C4-LGF2). town_start_to_oak_trigger's own `from` (6,9) is
        -- pinned against tests/fixtures/gen3/firered_town.sav's committed position -- but that
        -- fixture was built 2026-09-21, before save_via_menu's stray-Down-during-the-SAVE-row-
        -- search bug was fixed at the root (card gen3-P4-C4-F2, commit c1507b7d), and the
        -- README records that bug as capable of nudging the player's position DURING a save. A
        -- battery built with the fixed helper (leafgreen_town.sav) rests at the engine's TRUE
        -- post-door-exit tile instead (DEST.house_exit, "Exterior door exits take one step
        -- south"), one tile short. Bridge that one step here -- a no-op for firered_town.sav,
        -- which is already at (6,9) and never takes this branch.
        do
            local px, py = G.pos(cp)
            if px == DEST.house_exit.x and py == DEST.house_exit.y then
                play.follow(cp, "house_exit_to_town_start", "starter")
            end
        end
        -- Walking onto (12,1) fires the coord_event; from here to landing in the lab at scene=2
        -- is ENTIRELY scripted (lockall): Oak enters, leads the player north through the door,
        -- an internal `warp` command lands them at (6,12) in the lab, and the lab's own
        -- ON_FRAME ChooseStarterScene fires immediately (scene==1) — more scripted dialogue and
        -- an applymovement walk that parks the player at (6,4). No joypad steering happens or
        -- would do anything during this; only A to clear message boxes.
        local town_map = play.map(cp)
        play.follow(cp, "town_start_to_oak_trigger", "starter")
        local reached_lab = false
        for _ = 1, 6000 do
            if play.map(cp) ~= town_map then reached_lab = true; break end
            G.tap("A", 2, 10)
        end
        if not reached_lab then
            G.shot("stuck")
            G.finish(false, "starter: Oak's intercept never warped the player into the lab")
        end
        verify_destination(cp, "starter Oak warp", DEST.lab)
        G.phase("in-lab", play.where(cp))
        -- GROUND TRUTH, not position/idle guessing (PHYSICAL runs 4-7: position (6,4) + script
        -- idle + field controls unlocked was NOT sufficient — Oak was still talking). scripts.inc
        -- (ChooseStarterScene) only reaches `setvar VAR_MAP_SCENE_PALLET_TOWN_PROFESSOR_OAKS_LAB,
        -- 2` at the very end, line 225, right before `releaseall`. A-only: this is entirely a
        -- scripted cutscene (lockall), so Start must never fire here (see the mash_a comment).
        local scene_done = false
        for _ = 1, 6000 do
            if lab_scene_var(cp) == 2 then scene_done = true; break end
            G.tap("A", 2, 10)
        end
        if not scene_done then
            G.shot("stuck")
            G.finish(false, string.format(
                "starter: lab scene var never reached 2 (last=%d) at (%d,%d)",
                lab_scene_var(cp), G.pos(cp)))
        end
        -- The var can read 2 a frame or two before `releaseall` actually restores control
        -- (PHYSICAL risk noted by the coordinator); debounce script idle + field controls
        -- unlocked held for 60 consecutive frames, no further input, before trusting it.
        local stable, settled = 0, false
        for _ = 1, 900 do
            if G.pred_ok(cp, "script_context_status") and G.pred_ok(cp, "field_controls_locked") then
                stable = stable + 1
                if stable >= 60 then settled = true; break end
            else
                stable = 0
            end
            G.advance()
        end
        if not settled then
            G.shot("stuck")
            G.finish(false, "starter: scene var==2 but idle+unlocked never held 60 frames")
        end
        G.phase("scene-done", "var=2, idle+unlocked held 60f")

        -- DIAGNOSTIC (run 8): the live player OBJECT coords vs SaveBlock1.pos, and a screenshot,
        -- because after the scripted scene the screen showed the player beside Oak while
        -- SaveBlock1.pos claimed the walk to (9,5) succeeded. gObjectEvents = 0x02036E38
        -- (pokefirered.sym:205), object 0 = player, currentCoords s16 x/y at +0x10/+0x12
        -- (include/global.fieldmap.h struct ObjectEvent), stored +7 (MAP_OFFSET).
        do
            local ox = memory.read_s16_le(OBJ_EVENTS_ADDR + 0x10) - 7
            local oy = memory.read_s16_le(OBJ_EVENTS_ADDR + 0x12) - 7
            local sx, sy = G.pos(cp)
            G.phase("pre-walk", string.format("obj0=(%d,%d) sb1=(%d,%d)", ox, oy, sx, sy))
            G.shot("prewalk")
        end
        play.follow(cp, "lab_oak_scene_end_to_ball", "starter")   -- asserts the real (6,4), not assumed
        do
            local ox = memory.read_s16_le(OBJ_EVENTS_ADDR + 0x10) - 7
            local oy = memory.read_s16_le(OBJ_EVENTS_ADDR + 0x12) - 7
            local sx, sy = G.pos(cp)
            G.phase("post-walk", string.format("obj0=(%d,%d) sb1=(%d,%d)", ox, oy, sx, sy))
            G.shot("postwalk")
        end
        do
            -- Face the ball and PROVE the facing: ObjectEvent.facingDirection is the low nibble
            -- at +0x18 (include/global.fieldmap.h:254-255: u8 facingDirection:4 / movementDirection:4);
            -- 1=down 2=up 3=left 4=right. Hold Up until it reads 2 (the ball object is solid,
            -- so Up can only turn, never step).
            local function facing() return memory.read_u8(OBJ_EVENTS_ADDR + 0x18) & 0x0F end
            for _ = 1, 4 do
                if facing() == 2 then break end
                for _ = 1, 8 do joypad.set({ Up = true }); G.advance() end
                G.idle(8)
            end
            G.phase("facing", string.format("dir=%d (2=up)", facing()))
            G.shot("facing")
        end

        -- Phase 1: A only, checked each tap, until givemon actually lands (party_count 0->1).
        -- Every MSGBOX_YESNO up to and including "would you like Squirtle?" (ConfirmSquirtle,
        -- scripts.inc:1092-1096) defaults to YES (src/script_menu.c:873), so plain A-mashing is
        -- a pinned accept, not a guess -- and it can only ever accept the STARTER here, because
        -- the nickname prompt (the only OTHER yes/no reachable from this script) cannot appear
        -- before givemon fires (scripts.inc:1122 precedes 1129).
        local got = false
        for _ = 1, 40 do
            G.tap("A", 3, 20)
            if play.party_count() > 0 then got = true; break end
        end
        if not got then
            G.shot("stuck")
            G.finish(false, "starter: gPlayerPartyCount never left 0 after interacting with the ball")
        end
        verify_starter()
        G.phase("starter-got", "party=" .. play.party_count())

        -- Phase 2: the trailing "received {mon} from OAK!" message/fanfare, the nickname
        -- Yes/No (Text_GiveNicknameToThisMon, scripts.inc:1129), and the rival's own dialogue
        -- (scripts.inc:1140-1180) all run before script_context_status goes idle.
        -- WITNESS-DRIVEN (card C4-LGF2, coordinator steer 2026-09-23): a plain message box only
        -- closes on A, so mash A through every one of those; the instant
        -- Task_YesNoMenu_HandleInput is the active task (the SAME task every Yes/No box in the
        -- game uses, gTasks[] witness above), press B ONCE -- MENU_B_PRESSED is handled
        -- identically to NO (src/script_menu.c:901-905) -- and go back to mashing A. This
        -- replaces an earlier blind "alternate A then B every tap" design: on a PHYSICAL LG run
        -- that pattern let an A land on the Yes/No box's own default YES one iteration before
        -- its own B could decline it (one frame-timing tick different from FR's own run),
        -- opening the naming keyboard this driver does not otherwise handle. Witnessing the
        -- task directly removes the coincidence entirely, on either title.
        local idle = false
        for _ = 1, 200 do
            if G.pred_ok(cp, "script_context_status") then idle = true; break end
            if task_active(TASK_YES_NO_MENU) then
                G.tap("B", 3, 20)
            else
                G.tap("A", 3, 16)
            end
        end
        if not idle then
            G.shot("stuck")
            G.finish(false, "starter: trailing text/nickname-decline never went idle "
                         .. "(script_context_status)")
        end
        G.phase("starter-idle", "party=" .. play.party_count())
    end,
}

-- ── leg: rival_battle ────────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "rival_battle",
    exercises = { "battle_begin", "battle_end" },
    source = {
        "data/maps/PalletTown_ProfessorOaksLab/map.json (coord_events RivalBattleTriggerRight @ 7,8)",
        "data/maps/PalletTown_ProfessorOaksLab/scripts.inc:270-333 (RivalBattleTriggerRight -> RivalBattle -> RivalApproachForBattleBulbasaur* -> trainerbattle_earlyrival, VAR_STARTER_MON==1 (Squirtle) branch, scripts.inc:299-301)",
        "data/maps/PalletTown_ProfessorOaksLab/scripts.inc:441-444 (RivalBattleBulbasaur: trainerbattle_earlyrival ..., RIVAL_BATTLE_TUTORIAL, ...)",
        "include/constants/battle.h:73-74 (RIVAL_BATTLE_TUTORIAL=3 includes bit0 RIVAL_BATTLE_HEAL_AFTER)",
        "src/battle_setup.c:905-931 (CB2_EndTrainerBattle, TRAINER_BATTLE_EARLY_RIVAL: RIVAL_BATTLE_HEAL_AFTER set -> a LOSS heals the party and returns via CB2_ReturnToFieldContinueScriptPlayMapMusic, same as a win -- CB2_WhiteOut is only reached when that bit is clear, which it is not here -- so this battle cannot whiteout)",
        "data/maps/PalletTown_ProfessorOaksLab/scripts.inc:467-481 (EndRivalBattle: unconditional HealPlayerParty + scripted rival exit, regardless of outcome)",
    },
    run = function(cp)
        -- Landing ON (7,8) already fired the trigger (PATHS.ball_to_rival_row's own comment);
        -- everything from here through the approach dialogue is scripted (`lockall`). A-only:
        -- this is all still field/dialogue, never a menu that Start should touch.
        play.follow(cp, "ball_to_rival_row", "rival_battle")
        local entered = play.mash_a(250, function() return play.in_battle(cp) end)
        if not entered then
            G.shot("stuck")
            G.finish(false, "rival_battle: never entered battle after the trigger tile")
        end
        G.phase("battle-begin")
        -- gActionSelectionCursor resets to 0 (USE_MOVE) each battle
        -- (src/battle_controller_player.c); A,A is a pinned FIGHT->move-slot-1 selection, not a
        -- guess. What the rival does in response is not controlled — RISK stated in the header.
        -- A-only (mash_a): G.mash's Start pulse must never fire while a battle is up. A loss is
        -- an acceptable outcome here (see source: RIVAL_BATTLE_HEAL_AFTER, no whiteout), so the
        -- terminal allows WON or LOST, followed by the lab script's flag and scene writes.
        local ended = play.mash_a(1200, function() return not play.in_battle(cp) end)   -- PHYSICAL run 10: the fight was WON at ~315 taps but the end-of-battle text still needs presses
        if not ended then
            G.shot("stuck")
            G.finish(false, "rival_battle: in_battle never cleared within budget")
        end
        local outcome = battle_outcome()  -- retain this battle's result before the scene advances
        G.phase("battle-end")
        -- Post-battle is scripted too (EndRivalBattle: HealPlayerParty, "go toughen up your
        -- mon" message, the rival's own applymovement exit): wait_scene_settled (A-only while
        -- busy, then idle+unlocked held 60 frames) -- same PHYSICAL lesson as the starter leg's
        -- scene wait (run 4-7: a single-frame idle read is not enough, it can flicker mid-scene).
        if not play.wait_scene_settled(cp, 6000) then
            G.shot("stuck")
            G.finish(false, "rival_battle: post-battle scene never settled (idle+unlocked 60f)")
        end
        verify_rival(cp, outcome)
        G.phase("rival-gone", string.format("at=(%d,%d)", G.pos(cp)))
    end,
}

-- ── leg: leave_lab_for_parcel ────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "leave_lab_for_parcel",
    exercises = { "map_load" },
    source = {
        "data/maps/PalletTown_ProfessorOaksLab/map.json (warp_events[0..2] @ 5..7,12 -> PalletTown warp 2)",
        "data/tilesets/secondary/lab/metatile_attributes.bin (metatiles 656-658 at 5..7,12: behavior 0x0 = MB_NORMAL, not a metatile-driven warp)",
    },
    run = function(cp)
        local lab_map = play.map(cp)
        play.follow(cp, "rival_row_to_lab_exit", "leave_lab_for_parcel")
        -- DIAGNOSTIC (run 11 stalled here: "map never changed from 1027" after landing on
        -- (6,12), a collision=0/MB_NORMAL tile — no arrow-warp metatile behavior, yet a plain
        -- walk-onto did not fire the warp). Log the live object vs SaveBlock1.pos before trying
        -- the fix, the same cross-check that caught the starter leg's stale-position bug.
        do
            local ox, oy = play.obj_pos(0)
            local sx, sy = G.pos(cp)   -- multi-return: capture first (a bare G.pos(cp) mid-list drops sy)
            G.phase("at-lab-exit", string.format(
                "map=%s sb1=(%d,%d) obj0=(%d,%d) facing=%d", tostring(play.map(cp)), sx, sy, ox, oy, play.obj_facing(0)))
        end
        -- FIX: treat this door the same as every OTHER door in this file — a press INTO it,
        -- not a plain walk-onto. (leave_lab_for_parcel's collision-only investigation showed
        -- MB_NORMAL, not an arrow-warp metatile, but the coordinate-warp check still appears to
        -- require the player's MOVEMENT to be a step onto/through the tile, which `follow()`
        -- landing on it via its last queued direction does not reliably trigger — same shape as
        -- every exterior door (16,13)/(36,19)/(26,26) elsewhere in this file, all driven by
        -- enter_warp, not require_map_change.)
        if not play.enter_warp(cp, "Down", 20) then
            local ox2, oy2 = play.obj_pos(0)
            G.shot("stuck")
            G.finish(false, string.format(
                "leave_lab_for_parcel: the lab exit never fired a warp; obj0=(%d,%d) sb1=(%d,%d)",
                ox2, oy2, G.pos(cp)))
        end
        verify_destination(cp, "leave_lab_for_parcel", DEST.lab_exit)
        G.phase("outside", play.where(cp))
    end,
}

-- ── leg: parcel_fetch ────────────────────────────────────────────────────────────────────────
-- PalletTown -> Route1 -> ViridianCity -> the Mart. ViridianCity_Mart_EventScript_ParcelScene
-- (data/maps/ViridianCity_Mart/scripts.inc:16-32) is a MAP_SCRIPT_ON_FRAME script gated on
-- VAR_MAP_SCENE_VIRIDIAN_CITY_MART==0 — it fires automatically once the map loads, no player
-- action needed to trigger it, and it moves the PLAYER object itself via `applymovement`
-- (ViridianCity_Mart_Movement_ApproachCounter: walk_up x4). Verified by
-- `script_context_status` returning to idle (2) after being busy — a real predicate, not a
-- frame count.
LEGS[#LEGS + 1] = {
    name = "parcel_fetch",
    exercises = { "map_load" },
    source = {
        "data/maps/PalletTown/map.json (connections up -> Route1)",
        "data/maps/Route1/map.json (connections up -> ViridianCity)",
        "data/maps/ViridianCity/map.json (warp_events[4] -> ViridianCity_Mart)",
        "data/maps/ViridianCity_Mart/scripts.inc:16-32 (ParcelScene, ON_FRAME-triggered)",
    },
    run = function(cp)
        play.follow(cp, "lab_exit_to_route1_edge", "parcel_fetch")
        warp_to(cp, "Up", 30, DEST.route1_south, "parcel_fetch Pallet->Route1")
        play.follow(cp, "route1_south_to_north_edge", "parcel_fetch")
        warp_to(cp, "Up", 30, DEST.viridian_south, "parcel_fetch Route1->Viridian")
        play.follow(cp, "route1_edge_to_mart_door", "parcel_fetch")
        warp_to(cp, "Up", 30, DEST.mart, "parcel_fetch mart door")
        G.phase("in-mart", play.where(cp))
        -- Let the ON_FRAME script run and clear its own message boxes with A; the scene owns
        -- player movement. wait_scene_settled: idle+unlocked debounced 60 frames, never a
        -- single read (same lesson as the starter/rival-battle scenes).
        if not play.wait_scene_settled(cp, 3000) then
            G.shot("stuck")
            G.finish(false, "parcel_fetch: the mart's parcel scene never returned control")
        end
        verify_parcel_fetched(cp)
        G.phase("parcel-scene-done", string.format("at=(%d,%d), parcel read back", G.pos(cp)))
    end,
}

-- ── leg: parcel_deliver ──────────────────────────────────────────────────────────────────────
-- Press A until the delivery is actually under way, proven by the FIRST RAM write the script
-- makes (removeitem ITEM_OAKS_PARCEL, scripts.inc:601), never by a frame count or by the field
-- "going quiet" — quiet is also what an interaction that never started looks like, which is the
-- false pass this card fixes (see the oracle comment above key_items_has_parcel). Bounded
-- generously: the removeitem fires after only the first two message boxes
-- (Text_OakHaveSomethingForMe, then the "Delivered Oak's Parcel" fanfare message) clear.
local function start_oak_delivery(cp, label)
    if not sb1_ptr(cp) then
        G.finish(false, label .. ": parcel_fetch_precondition: key pocket unreadable"); return
    end
    if not key_items_has_parcel(cp) then
        G.finish(false, label .. ": parcel_fetch_precondition: mart/parcel_fetch left no "
                 .. "ITEM_OAKS_PARCEL in the key pocket"); return
    end
    for _ = 1, 400 do
        if not key_items_has_parcel(cp) then return end
        G.tap("A", 3, 16)
    end
    G.shot("stuck")
    G.finish(false, string.format(
        "%s: talking to Oak never removed ITEM_OAKS_PARCEL(%d) from the key-items pocket",
        label, ITEM_OAKS_PARCEL))
    -- explicit return: client.exit() is real on hardware but a no-op under test (fake RAM), so
    -- fail-fast never relies only on the host actually exiting.
    return
end

--- THE REAL ORACLE (card gen3-P3-C3-26). A settled scene proves the ENGINE went quiet, not that
--- the delivery happened. Checks every terminal PalletTown_ProfessorOaksLab_EventScript_ProfOak
--- actually writes (scripts.inc:601,656,660): the parcel gone, the dex flag set, a POKe BALL in
--- the pocket.
local function verify_parcel_delivered(cp, label)
    -- Each check `return`s on failure (client.exit() is real on hardware but a no-op under
    -- test), so exactly ONE reason is ever reported -- the first terminal that didn't hold,
    -- not whichever happened to run last.
    if key_items_has_parcel(cp) then
        G.shot("stuck")
        G.finish(false, label .. ": ITEM_OAKS_PARCEL is still in the key-items pocket")
        return
    end
    if not pokedex_get_flag(cp) then
        G.shot("stuck")
        G.finish(false, label .. ": FLAG_SYS_POKEDEX_GET never got set")
        return
    end
    if not pokeballs_pocket_has_poke_ball(cp) then
        G.shot("stuck")
        G.finish(false, label .. ": the POKe BALLS pocket has no ITEM_POKE_BALL")
        return
    end
    -- scripts.inc:678 is AFTER the dex flag and ball gift: this is the scene terminal.
    if lab_scene_var(cp) ~= 6 then
        G.finish(false, label .. ": parcel_delivery_scene: lab scene never reached 6"); return
    end
    G.phase("balls-received", label .. ": parcel gone, dex flag set, POKe BALL in the pocket, scene=6")
end

LEGS[#LEGS + 1] = {
    name = "parcel_deliver",
    exercises = { "map_load" },
    source = {
        "data/maps/PalletTown_ProfessorOaksLab/scripts.inc:567-660 (EventScript_ProfOak, a TALK-TO script: lock/faceplayer -> ReceiveDexScene -> ReceivedFivePokeBalls)",
        "data/maps/PalletTown_ProfessorOaksLab/map.json (LOCALID_OAKS_LAB_PROF_OAK object_event at (6,3), flag FLAG_HIDE_OAK_IN_HIS_LAB, script EventScript_ProfOak)",
        "include/global.h:779,790 (SaveBlock1.bagPocket_KeyItems +0x03B8; SaveBlock1.flags[] +0x0EE0); include/constants/global.h:37-38 (BAG_KEYITEMS_COUNT=30, BAG_POKEBALLS_COUNT=13)",
        "include/constants/items.h:421 (ITEM_OAKS_PARCEL=349); include/constants/flags.h:1324,1375 (FLAG_SYS_POKEDEX_GET = SYS_FLAGS(0x800)+0x29)",
        "src/event_data.c:279-309 (GetFlagAddr/FlagGet: flags[idx/8], bit (idx&7))",
    },
    -- The whole leg from Pallet Town onwards, shared by run() and resume(): after a whiteout
    -- the parcel is still in the bag and Oak is still waiting, so the ONLY thing a restart has
    -- to redo is the walk from the town to the lab.
    deliver_from_town = function(cp)
        play.follow(cp, "town_start_to_lab_door", "parcel_deliver")
        warp_to(cp, "Up", 30, DEST.lab, "parcel_deliver lab door")
        play.follow(cp, "lab_entrance_to_oak", "parcel_deliver")
    end,
    -- playlib calls recover() after a whiteout, then resume() instead of run().
    recover = function(cp) guarded_recovery(cp, "parcel_deliver", recover_to_pallet_town) end,
    run = function(cp)
        -- mart_scene_end_to_exit's start (4,3) is the ApproachCounter movement's computed end
        -- tile (walk_up x4 from the (4,7) entrance), not a BFS/observed tile — the one path
        -- entry in this file that isn't independently source-BFS'd, because the engine (not the
        -- player) drove that walk. Verified at runtime by G.pos same as every other step.
        play.follow(cp, "mart_scene_end_to_exit", "parcel_deliver")
        warp_to(cp, "Down", 30, DEST.mart_exit, "parcel_deliver mart exit")

        -- HEAL FIRST (FR lane run 14: the starter fainted in the Route 1 grass on the way home
        -- and the player whited out). A full party is the cheap prevention; playlib's whiteout
        -- recovery below is the expensive cure, and both now exist.
        play.follow(cp, "mart_door_to_pokecenter_door", "parcel_deliver")
        warp_to(cp, "Up", 30, DEST.center, "parcel_deliver Center door")
        heal_at_nurse(cp, "parcel_deliver")
        play.follow(cp, "heal_center_to_door", "parcel_deliver")
        warp_to(cp, "Down", 30, DEST.center_exit, "parcel_deliver Center exit")
        play.follow(cp, "pokecenter_door_to_route1_edge", "parcel_deliver")

        warp_to(cp, "Down", 30, DEST.route1_north, "parcel_deliver Viridian->Route1")
        play.follow(cp, "route1_north_to_south_edge", "parcel_deliver")
        warp_to(cp, "Down", 30, DEST.pallet_north, "parcel_deliver Route1->Pallet")
        play.follow(cp, "route1_edge_to_lab_door", "parcel_deliver")
        warp_to(cp, "Up", 30, DEST.lab, "parcel_deliver lab door")
        play.follow(cp, "lab_entrance_to_oak", "parcel_deliver")
        G.tap("Up", 2, 13)
        -- Talking to Oak with the parcel triggers the whole delivery + Pokedex + 5-balls
        -- cutscene (scripts.inc:567-660); long, almost entirely message boxes and NPC
        -- applymovement. FACING him is not talking to him — start_oak_delivery presses A until
        -- the scene is actually under way (proven by the parcel leaving the bag), THEN
        -- wait_scene_settled rides the rest of it out (idle+unlocked debounced 60 frames, plus
        -- callback2 back to CB2_Overworld, never a single read), and verify_parcel_delivered
        -- checks the real terminals before this leg is allowed to call it done.
        start_oak_delivery(cp, "parcel_deliver")
        if not play.wait_scene_settled(cp, 12000, function() return G.pred_ok(cp, "callback2") end) then
            G.shot("stuck")
            G.finish(false, "parcel_deliver: Oak's dex-scene never returned control")
        end
        verify_parcel_delivered(cp, "parcel_deliver")
    end,
}
-- resume() reuses the leg's own tail. Written after the table literal because it needs the leg
-- back: a whiteout restart begins at Pallet Town (6,9), not inside the Viridian mart.
LEGS[#LEGS].resume = function(cp)
    local leg = nil
    for _, l in ipairs(LEGS) do if l.name == "parcel_deliver" then leg = l end end
    leg.deliver_from_town(cp)
    G.tap("Up", 2, 13)
    start_oak_delivery(cp, "parcel_deliver (resume)")
    if not play.wait_scene_settled(cp, 12000, function() return G.pred_ok(cp, "callback2") end) then
        G.shot("stuck")
        G.finish(false, "parcel_deliver (resume): Oak's dex-scene never returned control")
    end
    verify_parcel_delivered(cp, "parcel_deliver (resume)")
end

--- Steer the battle bag (already open — the action menu's Right+A already fired
--- CB2_BagMenuFromBattle) to the POKEBALLS pocket, verify the item under the cursor really is
--- ITEM_POKE_BALL from BOTH sides of the selecting A (the plaintext bag slot before, then the
--- engine's own gSpecialVar_ItemId copy after), and confirm the USE/CANCEL popup's default row
--- (USE, item_menu.c:1353-1357 sContextMenuItems_BattleUse; Menu_InitCursor's last arg 0,
--- item_menu.c:1431) to throw it. Replaces the old blind 30x-A mash entirely (card
--- gen3-P3-C3-23): every step below either matches a witness or fails loudly naming it.
local function throw_pokeball_from_bag(cp, label)
    if not play.in_battle(cp) then return end

    -- The bag menu itself: gMain.callback2 == CB2_BagMenuRun (see the constant's own comment).
    local up = false
    for i = 1, 600 do
        if bag_menu_up() then up = true; break end
        if not play.in_battle(cp) then return end
        if i % 2 == 0 then joypad.set({ A = true }) else joypad.set({}) end
        G.advance()
    end
    joypad.set({})
    if not up then
        G.shot("stuck")
        G.finish(false, string.format(
            "%s: the bag menu never came up (gMain.callback2 never read CB2_BagMenuRun) at %s",
            label, play.at(cp)))
        return
    end

    -- Steer the REMEMBERED pocket to POKEBALLS(2). ProcessPocketSwitchInput
    -- (item_menu.c:1124-1145) clamps at POCKET_POKE_BALLS-1 and no-ops past it, so pressing
    -- Right more times than needed is harmless — bounded at 2, the worst case from ITEMS(0).
    -- PHYSICAL FR run 22: back-to-back Rights moved 0 -> 1 only; the pocket-switch animation
    -- swallows input until it finishes. So press, wait (bounded) for the pocket value to change,
    -- let the switch settle, and only then press again.
    for _ = 1, 4 do
        local before = bag_pocket()
        if before == BAG_POCKET_POKEBALLS then break end
        G.tap("Right", 3, 0)
        for _ = 1, 60 do
            if bag_pocket() ~= before then break end
            G.advance()
        end
        G.idle(40)
    end
    if bag_pocket() ~= BAG_POCKET_POKEBALLS then
        G.shot("stuck")
        G.finish(false, string.format(
            "%s: could not steer gBagMenuState.pocket to POKEBALLS(2) (reads %d)",
            label, bag_pocket()))
        return
    end

    -- Verify the PLAINTEXT item id under the cursor BEFORE ever pressing A on it.
    local slot = bag_cursor_slot(BAG_POCKET_POKEBALLS)
    local item = bag_pokeballs_item_id(cp, slot)
    if item ~= ITEM_POKE_BALL then
        G.shot("stuck")
        G.finish(false, string.format(
            "%s: the POKEBALLS pocket's cursor slot %d holds item %d, not ITEM_POKE_BALL(%d)",
            label, slot, item, ITEM_POKE_BALL))
        return
    end

    -- Only press once the bag's input task will read it (see bag_input_ready above).
    if not (TASK_BAG_MENU_HANDLE_INPUT and TASK_ANIMATE_WIN0V) then
        G.finish(false, string.format(
            "%s: no verified Task_BagMenu_HandleInput/Task_AnimateWin0v address for title %s",
            label, tostring(TITLE)))
        return
    end
    local ready = false
    for _ = 1, BAG_INPUT_WAIT_FRAMES do
        if G.pred_ok(cp, "palette_fade_active") and task_active(TASK_BAG_MENU_HANDLE_INPUT)
           and not task_active(TASK_ANIMATE_WIN0V) then ready = true; break end
        G.advance()
    end
    if not ready then
        G.shot("stuck")
        G.finish(false, string.format(
            "%s: the bag never took input in %d frames (palette fade clear, Task_BagMenu_HandleInput "
            .. "active, no Task_AnimateWin0v)", label, BAG_INPUT_WAIT_FRAMES))
        return
    end

    -- Select it, then require the engine's OWN copy of the selection (gSpecialVar_ItemId,
    -- item_menu.c:1097) to agree — proof the A landed on the row this file thinks it did.
    G.tap("A", 3, 20)
    if selected_item_id() ~= ITEM_POKE_BALL then
        G.shot("stuck")
        G.finish(false, string.format(
            "%s: gSpecialVar_ItemId reads %d after selecting the pocket's item, not "
            .. "ITEM_POKE_BALL(%d)", label, selected_item_id(), ITEM_POKE_BALL))
        return
    end

    -- The USE/CANCEL popup's default row (USE) — one A confirms it and starts the throw.
    G.tap("A", 3, 30)
end

-- ── leg: route1_catch (capture_wild) ─────────────────────────────────────────────────────────
-- DESIGN CHOICE (card gen3-P3-C3-18): throw a ball on the FIRST action-menu turn, never fight
-- first. The starter does not need to weaken a full-HP Pidgey/Rattata to catch it, and fighting
-- first only spends more turns taking return hits for nothing this leg needs -- catching is
-- retried across encounters (bounded), not across turns of one losing fight.
--
-- ROOT CAUSE of FR run 18's fainted starter, found by reading what this leg used to send: hunt_
-- encounter() returns the instant the encounter fires, which is still the "Wild PIDGEY
-- appeared!" INTRO text, not the action menu -- the old code's very first press (Right, meant to
-- toggle FIGHT(0) -> BAG(1)) landed on that text and did nothing, so the 30-A mash that followed
-- opened with the cursor still at its battle-start default FIGHT(0) and fought a real move
-- instead. A fixed A-tap count to clear the intro (run 19) was not enough either -- the
-- coordinator's replay showed the intro ("Wild X appeared!" -> "Go! SQUIRTLE!") can outlast it.
-- verify_fight_cursor (above) replaces both: it waits for the actual engine witness
-- (gBattlerControllerFuncs[0] == HandleInputChooseAction) instead of a frame count, and confirms
-- the cursor really is FIGHT(0) before Right is pressed.
local function route1_catch_loop(cp)
    local caught = false
    for encounter = 1, 4 do
        if not hunt_encounter(cp, "route1_catch", 40) then
            G.shot("stuck")
            G.finish(false, string.format(
                "route1_catch: 40 cycles of the pinned grass loop produced no wild "
                .. "encounter (attempt %d, at %s)", encounter, play.at(cp)))
        end
        verify_fight_cursor(cp, "route1_catch")
        -- BAG is pinned (Right, A); reaching and throwing POKE BALL inside it is now pinned too
        -- (card gen3-P3-C3-23, throw_pokeball_from_bag).
        if play.in_battle(cp) then
            G.tap("Right", 3, 20)  -- FIGHT(0) -> BAG/USE_ITEM(1), pinned bit toggle
            if action_cursor() ~= ACTION_BAG then
                G.shot("stuck")
                G.finish(false, string.format(
                    "route1_catch: Right did not move the cursor to BAG (read %d)",
                    action_cursor()))
            end
            G.tap("A", 3, 30)  -- opens the battle bag (CB2_BagMenuFromBattle, item_menu.c:350-353)
            throw_pokeball_from_bag(cp, "route1_catch")
        end
        local resolved = resolve_battle_and_check_whiteout(cp, 160)
        if resolved and battle_outcome() == B_OUTCOME_CAUGHT then
            caught = true
            break
        end
    end
    if not caught then
        G.shot("stuck")
        G.finish(false, string.format(
            "route1_catch: never reached B_OUTCOME_CAUGHT (last outcome=%d) after 4 encounters "
            .. "— the bag-menu mash (RISK, see header) is the likely culprit", battle_outcome()))
    end
    G.phase("caught", "outcome=" .. battle_outcome())
end

LEGS[#LEGS + 1] = {
    name = "route1_catch",
    exercises = { "capture_wild" },
    source = {
        "data/maps/Route1/map.json; data/layouts/Route1/map.bin metatiles 10-13 = MB_TALL_GRASS",
        "src/battle_controller_player.c:248-253 (Right toggles B_ACTION_USE_ITEM/BAG)",
        "src/battle_script_commands.c (BattleScript_SuccessBallThrow); include/constants/battle.h:82 (B_OUTCOME_CAUGHT=7)",
        "src/item_menu.c:307-343,350-353 (GoToBagMenu/CB2_BagMenuFromBattle: OPEN_BAG_LAST leaves gBagMenuState.pocket REMEMBERED, not reset)",
        "src/item_menu.c:384-506 (LoadBagMenuGraphics state machine -> SetMainCallback2(CB2_BagMenuRun) only once loaded)",
        "src/item_menu.c:1124-1145 (ProcessPocketSwitchInput: DPAD_RIGHT increments gBagMenuState.pocket, clamped at POCKET_POKE_BALLS-1, no wrap)",
        "include/constants/global.h:50-56 (POCKET_ITEMS/KEY_ITEMS/POKE_BALLS=1/2/3; NUM_BAG_POCKETS_NO_CASES=3); include/constants/item_menu.h:4-7 (OPEN_BAG_ITEMS/KEYITEMS/POKEBALLS=0/1/2)",
        "include/global.h:400-404,781 (struct ItemSlot; SaveBlock1.bagPocket_PokeBalls offset 0x0430); include/constants/items.h:8 (ITEM_POKE_BALL=4)",
        "src/item.c:20-29,41-49 (only ItemSlot.quantity is XORed with gSaveBlock2Ptr->encryptionKey; itemId is plaintext)",
        "src/item_menu.c:1353-1357,1686-1697 (ITEMMENULOCATION_BATTLE + ItemId_GetBattleUsage -> sContextMenuItems_BattleUse {USE,CANCEL}; Task_ItemMenuAction_BattleUse -> ItemId_GetBattleFunc, the throw)",
        "src/item_menu.c:1420-1431 (Menu_InitCursor(...,0): the USE/CANCEL popup's cursor defaults to row 0 USE)",
        "src/item_menu.c:1097 (gSpecialVar_ItemId set from the same plaintext BagGetItemIdByPocketPosition read on selection)",
        "data/maps/PalletTown_ProfessorOaksLab/scripts.inc:660 (giveitem_msg ..., ITEM_POKE_BALL, 5 — Oak's gift after the Pokedex, parcel_deliver leg)",
    },
    -- playlib calls recover() after our own check_whiteout() raises, then resume() instead of
    -- run(). recover_to_route1_grass leaves the player standing back at the grass origin with
    -- grass_step reset, so resuming is just running the hunt+catch loop again.
    recover = function(cp) guarded_recovery(cp, "route1_catch", recover_to_route1_grass) end,
    run = function(cp)
        play.follow(cp, "oak_to_lab_exit", "route1_catch")
        -- Same door as leave_lab_for_parcel (5..7,12): a press INTO it, not a plain walk-onto.
        if not play.enter_warp(cp, "Down", 20) then
            G.shot("stuck")
            G.finish(false, "route1_catch: the lab exit never fired a warp")
        end
        verify_destination(cp, "route1_catch lab exit", DEST.lab_exit)
        play.follow(cp, "lab_exit_to_route1_edge", "route1_catch")
        warp_to(cp, "Up", 30, DEST.route1_south, "route1_catch Pallet->Route1")
        play.follow(cp, "route1_south_to_grass_spot", "route1_catch")
        route1_catch_loop(cp)
    end,
    resume = route1_catch_loop,
}

-- ── leg: route1_faint ────────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "route1_faint",
    exercises = { "faint" },
    source = {
        "data/maps/Route1/map.json (wild encounter table, same grass patch)",
        "lua/games/gen3_frlge.lua:vanilla.BATTLE_RESULTS_ADDR (gBattleResults.playerFaintCounter @ +0)",
        "src/battle_script_commands.c Cmd_openpartyscreen; data/battle_scripts_1.s:2829-2836 "
        .. "(after a faint with another healthy mon the forced SEND_OUT menu continues the battle)",
    },
    -- Same recovery as route1_catch: back to Pallet Town, then to the grass origin, grass_step
    -- reset. Needed here even though resume() below does no hunting of its own -- the NEXT leg
    -- (viridian_pc_deposit_withdraw) still expects to start from the grass, not the heal house.
    recover = function(cp) guarded_recovery(cp, "route1_faint", recover_to_route1_grass) end,
    run = function(cp)
        local fainted = false
        for encounter = 1, 20 do
            if not hunt_encounter(cp, "route1_faint", 40) then
                G.shot("stuck")
                G.finish(false, string.format(
                    "route1_faint: 40 cycles of the pinned grass loop produced no wild "
                    .. "encounter (attempt %d, at %s)", encounter, play.at(cp)))
            end
            -- A faint with a healthy second mon leaves this battle OPEN on a
            -- mandatory party selection. The FR battle policy handles that
            -- RAM-witnessed send-out and the remaining fight, then checks for
            -- whiteout after the field settles. The faint counter alone is not
            -- a leg terminal (FR run 26 saved a mid-battle state there).
            if not play.fight_through(cp, 1200) or play.in_battle(cp)
               or not play.wait_scene_settled(cp, 1800) or not play.on_field(cp) then
                G.finish(false, "route1_faint: battle_not_settled_after_faint")
                return
            end
            -- BattleStartClearSetData resets this counter for EACH battle
            -- (battle_main.c:2308), so compare with zero after every fight.
            if player_faints() > 0 then fainted = true; break end
        end
        if not fainted then
            G.shot("stuck")
            G.finish(false, "route1_faint: playerFaintCounter never advanced after 20 encounters "
                         .. "(RISK: the starter may simply keep winning — see header)")
        end
        G.phase("fainted", "playerFaintCounter=" .. player_faints())
    end,
    -- run_leg only calls resume() after a whiteout signal raised above, so reaching here already
    -- proves all usable mons fainted. gBattleResults (BATTLE_RESULTS_ADDR) is a scratch struct the engine
    -- clears on returning to the field after a whiteout, so re-reading it here the way run()
    -- does would report 0 and look like nothing happened -- check it FIRST anyway (it is cheap
    -- and free if some other flow left it set), then fall back to the whiteout itself as
    -- evidence rather than grinding for a SECOND faint the recovered party doesn't need.
    resume = function(cp)
        local counter = player_faints()
        if counter > 0 then
            G.phase("fainted", "playerFaintCounter=" .. counter .. " (survived the recovery walk)")
        else
            G.phase("fainted", "accepted the whiteout itself as evidence (playerFaintCounter "
                             .. "was reset to 0 by the engine, as expected)")
        end
    end,
}

-- ── leg: viridian_pc_deposit_withdraw ────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "viridian_pc_deposit_withdraw",
    exercises = { "pc_deposit", "pc_box_place", "pc_withdraw" },
    source = {
        "docs/gen3/research/fr_pc_flow_and_pc_move_sites.md (Codex R9: the five-A PC route, the four-row owner menu once the Pokedex is obtained, the storage menu order, and the STORE -> destination-box confirmation)",
        "src/pokemon_storage_system_menu.c:37-43,263-308,343-358 (sMainMenuTexts order; DEPOSIT is row 1; the main menu refuses DEPOSIT when the party holds one mon)",
        "src/pokemon_storage_system_data.c:1465-1478,1755-1772 (the selected-mon popup: STORE / SUMMARY / MARK / RELEASE / CANCEL)",
        "src/pokemon_storage_system_tasks.c:996-1005,1189-1249 (STORE opens the box chooser; the A there is what calls TryStorePartyMonInBox)",
        "patch/build/gen3_Pokemon_-_FireRed_Version_(USA).gba parsed with tools/gba_map.py: ViridianCity (3.1) warp (26,26) -> map 5.4, whose only MB_PC (0x83) metatile is (11,1); bfs (7,8)->(11,2) = Up x4, Right x4, Up x2 with the four object-event tiles blocked",
        "docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt (the same flow observed hook by hook, and the source of the frame spacing)",
    },
    -- A whiteout on the Route 1 walk (FR run 28: the weak post-faint party lost at (12,25))
    -- lands the player, healed, inside this very Center at (7,4): recover checks that landing,
    -- resume walks the tail of the PC path from there and does the PC work as run() would.
    recover = function(cp)
        guarded_recovery(cp, "viridian_pc_deposit_withdraw", function(c)
            verify_destination(c, "viridian_pc whiteout landing", {group=5, num=4, x=7, y=4})
        end)
    end,
    run = function(cp, from_heal_spot)
        if from_heal_spot then
            play.follow(cp, "center_heal_spot_to_pc", "viridian_pc_deposit_withdraw")
        else
        return_to_grass_origin(cp, "viridian_pc_deposit_withdraw")
        play.follow(cp, "route1_grass_to_north_edge", "viridian_pc_deposit_withdraw")
        warp_to(cp, "Up", 30, DEST.viridian_south, "viridian_pc Route1->Viridian")
        play.follow(cp, "route1_edge_to_pokecenter_door", "viridian_pc_deposit_withdraw")
        warp_to(cp, "Up", 30, DEST.center, "viridian_pc Center door")
        play.follow(cp, "pokecenter_entrance_to_pc", "viridian_pc_deposit_withdraw")
        end
        G.tap("Up", 2, 13)               -- face the (solid) PC metatile at (11,1)

        local before_world = owned_snapshot("viridian_pc before")
        local before = before_world.party
        local target = pc_deposit_target(before_world)
        if before.n < 2 then
            G.finish(false, string.format(
                "viridian_pc: the party holds %d mon. The storage main menu REFUSES DEPOSIT at "
                .. "one (pokemon_storage_system_menu.c:289-308), and the oracle needs a second "
                .. "record to prove the survivors were left alone", before.n))
        end

        -- DEPOSIT. Down, A picks DEPOSIT (row 1); deposit mode opens in the party area at slot
        -- 0, so Down, A picks slot 1 and opens its popup; A takes STORE (row 0), which opens
        -- "Deposit in which BOX?"; the LAST A commits box 0 and is what actually calls
        -- TryStorePartyMonInBox. That final confirmation is the press an earlier RR lane run
        -- was missing, and the reason its party count never moved.
        PC.open(cp, "viridian_pc deposit")
        PC.mode("viridian_pc deposit", 1) -- DEPOSIT
        PC.popup("viridian_pc deposit", 1, 1, 0) -- party slot 1, STORE row 0
        PC.select("viridian_pc deposit", PC_DEPOSIT_MENU)
        PC.box("viridian_pc deposit")
        PC.leave(cp, "viridian_pc deposit")

        local mid_world = owned_snapshot("viridian_pc deposited")
        local mid = mid_world.party
        verify_pc_transfer("viridian_pc deposit", "deposit", before_world, mid_world, target)
        if mid.n ~= before.n - 1 then
            G.shot("stuck")
            G.finish(false, string.format(
                "viridian_pc: after the deposit and leaving the PC the party count is %d, not "
                .. "%d. The witnessed PC stages must reach the party popup and box chooser; "
                .. "the chooser confirmation is what commits the deposit",
                mid.n, before.n - 1))
        end
        local gone, why = play.departed_key(before, mid)
        if not gone then G.finish(false, "viridian_pc: deposit: " .. why) end
        G.phase("deposited", string.format("party %d -> %d, key %s left", before.n, mid.n, gone))

        -- WITHDRAW. Row 0 is already selected on a fresh menu, so A takes WITHDRAW; entry is in
        -- the BOX area at slot 0, A opens that record's popup, and A takes WITHDRAW (row 0).
        -- There is no destination confirmation on this path (R9 note).
        G.tap("Up", 2, 13)
        PC.open(cp, "viridian_pc withdraw")
        -- NO Up HERE. A re-opened PC starts the storage menu on ROW 0 (Withdraw), and an Up
        -- would WRAP the cursor to See Ya and close it (PHYSICAL, RR lane r5d,
        -- docs/gen3/probes/shadow_rr_play_r5d_pc_ops_2026-09-21.txt). The r5b/r5c
        -- "double deposit" that looked like a remembered cursor was really leave_storage
        -- returning early through the exit textbox; that is fixed above, not here.
        PC.mode("viridian_pc withdraw", 0)
        PC.popup("viridian_pc withdraw", 0, 0, 0)
        PC.select("viridian_pc withdraw", PC_WITHDRAW_MON)
        PC.withdraw("viridian_pc withdraw")
        PC.leave(cp, "viridian_pc withdraw")

        local after_world = owned_snapshot("viridian_pc withdrawn")
        local after = after_world.party
        verify_pc_transfer("viridian_pc withdraw", "withdraw", mid_world, after_world, target)
        if after.n ~= mid.n + 1 then
            G.shot("stuck")
            G.finish(false, string.format(
                "viridian_pc: after the withdraw the party count is %d, not %d", after.n, mid.n + 1))
        end
        if after.keys[gone] == nil then
            G.shot("stuck")
            G.finish(false, string.format(
                "viridian_pc: the withdrawn mon is NOT the deposited one. Deposited %s; the "
                .. "party now holds [%s]. A count that merely returned to where it started is "
                .. "not a round trip", gone, play.keylist(after)))
        end
        local ok, bad = play.survivors_intact(before, after, gone)
        if not ok then
            G.shot("stuck")
            G.finish(false, "viridian_pc: " .. bad .. " during the round trip")
        end
        G.phase("withdrawn", string.format("party %d -> %d, key %s is back; %d survivors "
                                           .. "byte-identical", mid.n, after.n, gone, before.n - 1))
    end,
}

-- ── leg: pc_release ──────────────────────────────────────────────────────────────────────────
-- Was OPEN for want of a pinned route; the R9 note supplies one. RELEASE is row 3 of the SAME
-- selected-mon popup the deposit uses (STORE / SUMMARY / MARK / RELEASE / CANCEL), so the walk
-- to it is the deposit's own route with three Downs instead of a STORE.
do local vpc = LEGS[#LEGS]; vpc.resume = function(cp) vpc.run(cp, true) end end

LEGS[#LEGS + 1] = {
    name = "pc_release",
    exercises = { "pc_release_begin", "pc_release" },
    source = {
        "docs/gen3/research/fr_pc_flow_and_pc_move_sites.md (the selected-mon popup order and the release completion pair: pc_release_begin at ReleaseMon entry 0x08093218, pc_release at +0x3E = 0x08093256)",
        "src/pokemon_storage_system_data.c:1761-1805 (popup rows STORE 0, SUMMARY 1, MARK 2, RELEASE 3, CANCEL 4)",
        "src/pokemon_storage_system_tasks.c:1255-1305 (Task_ReleaseMon: RELEASE opens a Yes/No confirmation, ShowYesNoWindow(1))",
        "src/pokemon_storage_system_tasks.c:2595-2599 (ShowYesNoWindow(1) starts the cursor on NO and does not wrap -- a bare A declines silently)",
        "src/pokemon_storage_system_tasks.c:1307-1339 (confirming YES runs ReleaseMon, then two trailing message boxes: MSG_WAS_RELEASED, MSG_BYE_BYE)",
    },
    run = function(cp)
        -- The leg runs straight after the round trip, so the player is already at the PC.
        G.tap("Up", 2, 13)
        local before_world = owned_snapshot("pc_release before")
        local before = before_world.party
        if before.n < 2 then
            G.finish(false, string.format(
                "pc_release: the party holds %d mon; DEPOSIT mode (which is how the party-side "
                .. "popup is reached) is refused at one", before.n))
        end
        local target = before.order[2]  -- Down from slot 0 selects slot 1, before compaction

        PC.open(cp, "pc_release")
        PC.mode("pc_release", 1)
        PC.popup("pc_release", 1, 1, 3) -- party slot 1, RELEASE row 3
        PC.select("pc_release", PC_RELEASE_MON)
        -- THE CONFIRMATION IS PINNED. ShowYesNoWindow(1) starts the cursor on NO and does not
        -- wrap (pokemon_storage_system_tasks.c:2595-2599), so a bare A here declines silently --
        -- Up moves the cursor to YES first. Two more A's clear the trailing MSG_WAS_RELEASED and
        -- MSG_BYE_BYE messages (pokemon_storage_system_tasks.c:1307-1339).
        PC.release("pc_release") -- witness NO->YES, confirm, then both message states
        PC.leave(cp, "pc_release")

        local after_world = owned_snapshot("pc_release after")
        local after = after_world.party
        verify_pc_transfer("pc_release", "release", before_world, after_world, target)
        if after.n ~= before.n - 1 then
            G.shot("stuck")
            G.finish(false, string.format(
                "pc_release: the party count is %d, not %d. The whole route (RELEASE, Up, A, "
                .. "A, A) is pinned to source -- see this leg's citations",
                after.n, before.n - 1))
        end
        local gone, why = play.departed_key(before, after)
        if not gone then G.finish(false, "pc_release: " .. why) end
        local ok, bad = play.survivors_intact(before, after, gone)
        if not ok then G.finish(false, "pc_release: " .. bad) end
        G.phase("released", string.format(
            "party %d -> %d, selected key %s gone from party and all 14 boxes; boxes unchanged",
            before.n, after.n, gone))
    end,
}

-- ── leg: save ────────────────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "save",
    exercises = { "save" },
    source = { "src/save.c:701 (TrySavingData); row search + flash sector counter witness (lua/tests/gen3_boot_check.lua save_via_menu), no guessed menu row" },
    run = function(cp)
        local domain = select(1, G.flash_domain())
        if not domain then G.finish(false, "save: no flash memory domain") end
        -- save_via_menu validates the new slot (unique ids, one slot, checksums) and flushes.
        local ok, before, after, why = G.save_via_menu(cp, domain)
        if not ok then
            G.finish(false, string.format("save: %s (counter %s -> %s)", tostring(why),
                                          tostring(before), tostring(after)))
        end
        G.phase("saved", string.format("counter %d -> %d", before, after))
    end,
}

-- ── leg: pc_move_full_party (OPEN) ───────────────────────────────────────────────────────────
-- pc_move is SendMonToPC, and SendMonToPC is acquisition-to-storage: GiveMonToPlayer falls back
-- to it when the party is full (R9 note section B). It is NOT the storage menu's deposit, which
-- is why viridian_pc_deposit_withdraw no longer claims it -- that leg exercises pc_deposit,
-- pc_box_place and pc_withdraw, and claiming pc_move as well was simply wrong.
LEGS[#LEGS + 1] = {
    name = "pc_move_full_party",
    exercises = { "pc_move" },
    source = {
        "docs/gen3/research/fr_pc_flow_and_pc_move_sites.md section B (SendMonToPC is the full-party fallback of GiveMonToPlayer, not a deposit/withdraw/release classifier)",
        "src/pokemon.c:3686-3740 (GiveMonToPlayer -> SendMonToPC)",
    },
    open = true,
    open_reason = "SendMonToPC only runs on an acquisition that cannot fit in the party, i.e. a "
               .. "catch or gift with six party mons; this route reaches Viridian with far "
               .. "fewer, and nothing here fills a party to six",
}

-- ── leg: gift_mon (OPEN) ─────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "gift_mon",
    exercises = { "mon_given" },
    source = { "data/maps/Route4_PokemonCenter_1F/scripts.inc:49 (givemon SPECIES_MAGIKARP, 5)" },
    open = true,
    open_reason = "earliest non-starter givemon is Route 4's Magikarp, past Mt. Moon",
    run = function(cp) G.phase("gift_mon", "OPEN: earliest is Route 4 PokeCenter, past Mt. Moon") end,
}

-- ── leg: npc_trade (OPEN) ────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "npc_trade",
    exercises = { "trade_done", "trade_begin", "trade_evolve_species_store" },
    source = {
        "data/maps/CeruleanCity_House3/scripts.inc (trade NPC)",
        "src/data/ingame_trades.h (INGAME_TRADE_MR_MIME, requestedSpecies SPECIES_ABRA)",
    },
    open = true,
    open_reason = "earliest trade is Cerulean's Mr. Mime for an Abra, needing Route 24",
    run = function(cp) G.phase("npc_trade", "OPEN: earliest is Cerulean Mr. Mime, needs Route 24 Abra") end,
}

-- ── leg: evolution (OPEN) ────────────────────────────────────────────────────────────────────
LEGS[#LEGS + 1] = {
    name = "evolution",
    exercises = { "evolve_species_store" },
    source = { "src/evolution_scene.c (level-up evolution path)" },
    open = true,
    open_reason = "earliest is the starter's own level-up (Squirtle Lv.16); needs many more battles",
    run = function(cp) G.phase("evolution", "OPEN: earliest is a starter level-up, needs battle grinding") end,
}

-- ══════════════════════════════════════════════════════════════════════════════════════════
-- EMERALD: scripted natural play (card E2-PLAY-PREP)
-- ══════════════════════════════════════════════════════════════════════════════════════════
-- A SEPARATE ordered table, not appended to the FR/LG/RR LEGS above: LEGS is built
-- unconditionally at module load regardless of title (every existing leg literal runs
-- LEGS[#LEGS+1]=... with no title guard), so appending here would hand an Emerald run legs
-- built entirely from Pallet Town/pokefirered facts. EMERALD_LEGS is declared for every title
-- (an empty table when TITLE ~= "emerald") so the module's own export table below never indexes
-- a nil, and populated only inside the guard.
--
-- Three INDEPENDENT SYNTH-seeded fixtures (tests/fixtures/gen3/README.md, "emerald_{town,
-- battle,trainer}[_b].sav"), each already standing where its own group of legs needs it --
-- unlike the FR/LG story above (one save, threaded start to finish), these do not chain:
-- emerald_town.sav sits at Oldale Town's heal tile (0.10, 6,17), emerald_battle.sav in Route
-- 102's tall grass (0.17, 21,16), emerald_trainer.sav one step from Youngster Calvin's sight
-- line (0.17, 32,16). EMERALD_LEGS is still ONE ordered table (so every leg shares playlib's
-- SLINK_GEN3_PLAY_FROM resume mechanism and the "open (skipped)" reporting), but the first leg
-- of each group carries a `check(cp)` that fails loudly if the loaded fixture's tile does not
-- match the group about to run -- no leg here assumes it can walk in from a DIFFERENT group's
-- tile. (Oldale Town's own west connection does lead onto Route 102 in principle, but no BFS
-- path threading all three fixtures together has been computed or verified, so this driver does
-- not attempt it -- see the report for why three independent starts, not one long walk.)
-- ponytail: EMH holds the E2-LEGS round-2 Emerald helpers in one table -- the main chunk sits at
-- Lua's 200-local cap. Empty unless TITLE == "emerald", like EMERALD_LEGS.
local EMERALD_LEGS, EMH = {}, {}
if TITLE == "emerald" then

--- group/num/x/y destination check for a leg's own `check(cp)` -- returns a message (leg
--- precondition failed) or nil (ok), the shape playlib's `leg.check` wants.
local function emerald_at(group, num, x, y, extra)
    return function(cp)
        local g, n = G.map(cp)
        local px, py = G.pos(cp)
        if g ~= group or n ~= num or px ~= x or py ~= y then
            return string.format(
                "expected the %s fixture's own tile %d.%d (%d,%d), read %s.%s (%s,%s) -- wrong "
                .. "fixture loaded for this leg (tests/fixtures/gen3/README.md)",
                "emerald", group, num, x, y, tostring(g), tostring(n), tostring(px), tostring(py))
        end
        return extra and extra(cp) or nil
    end
end

--- Party guards for a group's first leg (card E2-LEGS): the tile alone cannot tell emerald_pc.sav
--- from emerald_town.sav, nor emerald_lowhp.sav from emerald_battle.sav -- they share tiles.
local function em_party_count_is(n)
    return function()
        local got = memory.read_u8(PARTY_COUNT_ADDR)
        if got ~= n then
            return string.format("expected a %d-mon party (gPlayerPartyCount), read %d -- wrong "
                                 .. "fixture loaded for this leg", n, got)
        end
    end
end
local function em_lead_hp_is(n, hp)
    return function()
        local count = memory.read_u8(PARTY_COUNT_ADDR)
        local cur, maxhp = slot0_hp()
        if count ~= n or cur ~= hp or maxhp <= hp then
            return string.format("expected a %d-mon party with the lead at %d HP (below max), read "
                                 .. "party=%d HP %d/%d -- wrong fixture loaded for this leg",
                                 n, hp, count, cur, maxhp)
        end
    end
end

-- Emerald's own START-menu save path. gen3_boot_check.lua's G.save_via_menu (the FR/LG "save"
-- leg above uses it) is FR/LG's task-based START menu (sStartMenuOrder / Task_StartMenuHandleInput
-- -- gen3_title_syms.lua already documents those as `emerald = nil` on purpose, a genuine
-- architecture change, not a rename); Emerald's is the gMenuCallback-driven design
-- lua/tests/gen3_emerald_boot_check.lua's own header explains ("that driver's START-menu
-- witnesses are FR/LG's task-based menu ... Emerald's menu is gMenuCallback-driven"). This is
-- the SAME witness chain that script already proved live (its own boot-check receipts,
-- tests/fixtures/gen3/README.md), re-derived here through `cp`/G because that script is a
-- top-level driver (calls G.finish/G.open itself at module load) and not a reusable library
-- function this file can dofile mid-leg.
local EMERALD_START_SYM_NAMES = {
    "gMenuCallback", "Task_ShowStartMenu", "HandleStartMenuInput", "StartMenuSaveCallback",
    "SaveStartCallback", "SaveCallback", "sStartMenuCursorPos", "sNumStartMenuActions",
    "sCurrentStartMenuActions",
    -- card E2-LEGS: the MOVE POKeMON grab/place tasks and the carried-mon flag
    -- (src/pokemon_storage_system.c:2737-2775, :574), which gen3_title_syms.lua has no entry for.
    "Task_MoveMon", "Task_PlaceMon", "sIsMonBeingMoved",
    -- round 2: the battle script's position, for EMH.battle_dump's failure message
    "gBattlescriptCurrInstr", "gBattleCommunication",
}

local function load_emerald_start_syms()
    local want, out = {}, {}
    for _, n in ipairs(EMERALD_START_SYM_NAMES) do want[n] = true end
    for line in io.lines(WT .. "/data/gen3/pret/pokeemerald.sym") do
        local addr, name = line:match("^(%x+) %a+ %x+ (%S+)$")
        if addr and want[name] then out[name] = tonumber(addr, 16) end
    end
    for _, n in ipairs(EMERALD_START_SYM_NAMES) do
        assert(out[n], "gen3_scripted_play: symbol " .. n .. " missing from pokeemerald.sym")
    end
    return out
end
local ES = load_emerald_start_syms()
local function em_thumb(a) return a | 1 end
local function em_menu_cb() return memory.read_u32_le(ES.gMenuCallback) end
local function em_menu_ready()
    return task_active(em_thumb(ES.Task_ShowStartMenu))
       and em_menu_cb() == em_thumb(ES.HandleStartMenuInput)
end
local function em_save_dialog()
    local c = em_menu_cb()
    return c == em_thumb(ES.StartMenuSaveCallback) or c == em_thumb(ES.SaveStartCallback)
        or c == em_thumb(ES.SaveCallback)
end
local EM_MENU_ACTION_SAVE = 5  -- src/start_menu.c:51-58 (Emerald's own numbering; FR/LG's is 4)
local function emerald_save_via_menu(cp)
    local domain = select(1, G.flash_domain())
    if not domain then G.finish(false, "emerald_save: no flash memory domain"); return end
    local before = G.save_counter(domain)
    G.phase("save-menu", "counter=" .. before)
    local opened = false
    for _ = 1, 5 do
        for _ = 1, 300 do
            if G.pred_ok(cp, "field_controls_locked") then break end  -- pred true == free
            G.advance()
        end
        G.tap("Start", 3, 0)
        for _ = 1, 120 do
            if em_menu_ready() then opened = true; break end
            G.advance()
        end
        if opened then break end
    end
    if not opened then
        G.shot("stuck")
        G.finish(false, "emerald_save: the START menu never took input")
        return
    end
    local n = memory.read_u8(ES.sNumStartMenuActions)
    local row = nil
    for i = 0, n - 1 do
        if memory.read_u8(ES.sCurrentStartMenuActions + i) == EM_MENU_ACTION_SAVE then row = i; break end
    end
    if not row then
        G.finish(false, string.format("emerald_save: no SAVE row among %d START items", n))
        return
    end
    for _ = 1, n + 8 do
        if memory.read_u8(ES.sStartMenuCursorPos) == row then break end
        if not em_menu_ready() then
            G.finish(false, "emerald_save: the START menu closed during the row walk")
            return
        end
        G.tap("Down", 3, 13)
    end
    if memory.read_u8(ES.sStartMenuCursorPos) ~= row then
        G.finish(false, "emerald_save: cursor never reached the SAVE row " .. row)
        return
    end
    G.tap("A", 3, 0)
    local opened_dialog = false
    for _ = 1, 120 do
        if em_save_dialog() then opened_dialog = true; break end
        G.advance()
    end
    if not opened_dialog then
        G.shot("stuck")
        G.finish(false, "emerald_save: the save dialog never opened")
        return
    end
    G.phase("save-dialog", "row=" .. row .. "/" .. n)
    -- YES is the default on the save prompt; the flash counter, not the presses, is the verdict.
    local after, moved = before, false
    for i = 1, 300 do
        G.tap("A", 3, 13)
        after = G.save_counter(domain)
        if after > before then moved = true; break end
    end
    if not moved then
        G.finish(false, "emerald_save: the save counter never advanced")
        return
    end
    G.phase("saved", string.format("counter=%d->%d", before, after))
    -- SaveCallback's own success exit is the only one that frees the field controls again.
    local closed = false
    for _ = 1, 40 do
        G.tap("A", 3, 13)
        if G.pred_ok(cp, "field_controls_locked") then closed = true; break end  -- free again
    end
    if not closed then
        G.finish(false, "emerald_save: the save dialog never closed")
        return
    end
    local ok = pcall(client.saveram)
    if not ok then G.finish(false, "emerald_save: SaveRAM flush failed"); return end
    G.phase("flushed", play.where(cp))
end

-- ── TOWN group (emerald_town.sav, Oldale Town 0.10 (6,17)) ─────────────────────────────────

EMERALD_LEGS[#EMERALD_LEGS + 1] = {
    name = "emerald_enter_pc",
    exercises = { "map_load" },
    check = emerald_at(0, 10, 6, 17, em_party_count_is(2)),  -- emerald_pc.sav, not emerald_town.sav
    source = {
        "data/maps/OldaleTown/map.json (warp_events: (6,16) -> MAP_OLDALE_TOWN_POKEMON_CENTER_1F warp 0)",
        "data/maps/OldaleTown_PokemonCenter_1F/map.json (group 2 num 2, warps[0] = (7,8) -> OldaleTown warp 2)",
        "tools/gba_map.py --game emerald --map 0.10 / --map 2.2 (this card's own additive Emerald "
        .. "support: Tileset.metatileAttributes is u16@0x10 in pokeemerald, not FR/LG's u32@0x14 -- "
        .. "include/global.fieldmap.h in both pret trees)",
    },
    run = function(cp)
        -- One step Up presses INTO the door (6,16) from the fixture's own start tile (6,17) --
        -- the same "press into it, don't just walk onto it" shape every FR/LG door in this file
        -- uses (play.enter_warp). A real-RAM terminal, not a frame count: the pre-press
        -- position and the post-press map/tile (verify_destination below) both read G.pos/G.map.
        local px0, py0 = G.pos(cp)
        G.phase("emerald_enter_pc-start", string.format("at (%d,%d)", px0, py0))
        local ok, why = play.enter_warp(cp, "Up", 20)
        if not ok then
            G.shot("stuck")
            G.finish(false, "emerald_enter_pc: the Oldale PC door never fired a warp: " .. tostring(why))
            return
        end
        verify_destination(cp, "emerald_enter_pc", { group = 2, num = 2, x = 7, y = 8 })
        G.phase("in-pc", play.where(cp))
    end,
}

-- ── PC group (emerald_pc.sav, card E2-LEGS) ─────────────────────────────────────────────────
-- emerald_pc.sav (tests/fixtures/gen3/README.md, built by tools/gen3_fixtures.py kind "pc"):
-- Oldale Town (0.10) (6,17), party [Mudkip Lv5, Poochyena Lv3], box 0 slot 0 Zigzagoon, slot 1
-- Wurmple, currentBox 0. emerald_enter_pc's guard refuses the one-Mudkip emerald_town.sav.
--
-- The storage UI is FR's own state machine under Emerald's names (pret pokeemerald @c65e93f2,
-- src/pokemon_storage_system.c), so the FR PC stages above (PC.open/mode/popup/select/box/
-- withdraw/release/leave) are reused unchanged through the Emerald entries of
-- gen3_title_syms.lua. Checked against the source, not assumed:
--  * the which-PC multichoice (data/scripts/pc.inc:10-23; src/script_menu.c:328-375): 3 rows
--    (SOMEONE'S/LANETTE'S PC, <PLAYER>'s PC, LOG OFF; 4 with FLAG_SYS_GAME_CLEAR), cursor 0,
--    VAR_RESULT 0 = storage, MULTI_B_PRESSED 127 (include/constants/script_menu.h:8);
--  * Task_PCMainMenu (:1538-1648): tState=data[0], 2=HANDLE_INPUT, tSelectedOption=data[1],
--    OPTION_WITHDRAW 0 / DEPOSIT 1 / MOVE_MONS 2 / MOVE_ITEMS 3 / EXIT 4 (:54-60), started at 0 by
--    ShowPokemonStorageSystemPC (:1650-1656); DEPOSIT is refused at one party mon (:1592-1598);
--  * sStorage->state @+0 / boxOption @+1 (:403-406); Task_PokeStorageMain MSTATE_HANDLE_INPUT=0
--    (:2254-2256); InitCursor puts DEPOSIT in the party area, every other mode in the box, pos 0,
--    auto-action off (:5788-5805) -- so A opens the popup (InBoxInput_Normal :7092-7096);
--  * the popup (SetMenuTexts_Mon :7621-7669): DEPOSIT/WITHDRAW = STORE|WITHDRAW, SUMMARY, MARK,
--    RELEASE, CANCEL (5 rows); MOVE_MONS = MOVE|PLACE, SUMMARY, WITHDRAW, MARK, RELEASE, CANCEL
--    (6 rows); Task_OnSelectedMon takes input in state 2 (:2580-2660);
--  * Task_DepositMenu chooser state 1, box-full 4, TryStorePartyMonInBox on A (:2847-2910);
--  * Task_ReleaseMon yes/no state 1 on NO (ShowYesNoWindow(1) = CreateYesNoMenu(...,0) then
--    Menu_MoveCursorNoWrapAround(1), :4315-4319), WAS_RELEASED 4, BYE_BYE 5 (:2912-2975);
--  * Task_OnBPressed yes/no in state 2, B exits (:3670-3700).

-- tools/gba_map.py "<Emerald ROM>" --sym data/gen3/pret/pokeemerald.sym --game emerald --map 2.2
-- --find-behaviour 0x83 -> [(10, 1)] (MB_PC, include/constants/metatile_behaviors.h:136 = 0x83);
-- --bfs 7,8 10,2 -> the dirs below (object tiles blocked: nurse (7,2), gentleman (4,4), boy
-- (10,6), girl (3,7) range 1 -- data/maps/OldaleTown_PokemonCenter_1F/map.json). (7,8) is the
-- door landing emerald_enter_pc verifies; (10,2) faces the PC after the final Up.
PATHS.em_oldale_center_to_pc = {
    map = "OldaleTown_PokemonCenter_1F", from = { 7, 8 }, to = { 10, 2 }, battles = false,
    dirs = { "Up","Up","Up","Up","Right","Right","Right","Up","Up" },
}

local function em_box_key(owned, box, slot)
    for key, mon in pairs(owned.boxes) do
        if mon.box == box and mon.slot == slot then return key end
    end
end

--- Walk the box cursor (CURSOR_AREA_IN_BOX, IN_BOX_COLUMNS 6) along its row to `pos`, one
--- witnessed Right/Left at a time (InBoxInput_Normal :7028-7081). Leaving the row is refused.
local function em_box_cursor(label, pos)
    for _ = 1, 8 do
        if memory.read_u8(PC_CURSOR_AREA) ~= 0 then return pc_fail(label, "box_cursor_wrong_area") end
        local current = memory.read_u8(PC_CURSOR_POS)
        if current == pos then return true end
        if current // 6 ~= pos // 6 then return pc_fail(label, "box_cursor_wrong_row") end
        G.tap(current < pos and "Right" or "Left", 3, 20)
        if not pc_wait(label, "box_cursor_stalled", function()
            local st = pc_storage()
            return st and memory.read_u8(PC_CURSOR_POS) ~= current and pc_task(PC_STORAGE_MAIN)
               and memory.read_u8(st) == 0
        end, 120) then return false end
    end
    return pc_fail(label, "box_cursor_stalled")
end

--- MOVE POKeMON mode's popup row 0 (MOVE on a mon, PLACE on an empty slot while carrying one):
--- AddMenu starts the cursor on row 0 (:8001-8014), so A opens the popup and A takes row 0.
local function em_move_popup_row0(label, task)
    local storage = pc_storage()
    if not storage or memory.read_u8(storage + 1) ~= 2 then return pc_fail(label, "move_mode_not_active") end
    local function up() return pc_task(PC_ON_SELECTED) and memory.read_u8(storage) == 2 end
    for _ = 1, 4 do
        if up() then break end
        if not pc_task(PC_STORAGE_MAIN) then return pc_fail(label, "move_popup_unexpected_task") end
        G.tap("A", 3, 13)
        pc_poll(up, 120)
    end
    if not up() then return pc_fail(label, "move_popup_missing") end
    if memory.read_u8(PC_MENU_MAX_CURSOR) ~= 5 then return pc_fail(label, "move_popup_wrong_row_count") end
    if memory.read_u8(PC_MENU_CURSOR) ~= 0 then return pc_fail(label, "move_popup_not_row0") end
    return PC.select(label, task)
end

--- Back on Task_PokeStorageMain's input state with the carried-mon flag reading `carrying`.
local function em_wait_carry(label, stage, carrying)
    return pc_wait(label, stage, function()
        local st = pc_storage()
        return st and pc_task(PC_STORAGE_MAIN) and memory.read_u8(st) == 0
           and memory.read_u8(ES.sIsMonBeingMoved) == carrying
    end, 900)
end

local function em_fail(label, msg)
    G.shot("stuck")
    G.finish(false, label .. ": " .. msg)
    return false
end

--- Steer the storage top menu (Task_PCMainMenu) to `row` one witnessed Down at a time, THEN hand
--- over to PC.mode. PC.mode's own Down loop waits for tSelectedOption == row after EACH press,
--- which only holds for rows 0/1 (FR never needed more). Live E2-LEGS run 1: PC.mode(L, 2)
--- failed pc_storage_top_cursor_stalled with Task_PCMainMenu (080C7268 = pokeemerald.sym
--- Task_PCMainMenu) live and menu_cursor=1 -- the first Down HAD landed, on row 1, and the
--- wait for row 2 timed out. storage_state=-1 there is expected: sStorage is only allocated
--- once storage opens (EnterPokeStorage), not on the top menu. With the row already selected,
--- PC.mode's loop breaks before pressing anything (tSelectedOption @task+10, :1558-1575).
function EMH.pc_top_row(label, row)
    local main = pc_task(PC_MAIN_MENU)
    if not main or memory.read_u16_le(main + 8) ~= 2 then return pc_fail(label, "storage_top_not_ready") end
    for _ = 1, 5 do
        local current = memory.read_u16_le(main + 10)
        if current == row then return true end
        G.tap("Down", 3, 20)
        if not pc_wait(label, "storage_top_cursor_stalled", function()
            return memory.read_u16_le(main + 10) == (current + 1) % 5
               and memory.read_u8(PC_MENU_CURSOR) == (current + 1) % 5
        end, 90) then return false end
    end
    return pc_fail(label, "storage_top_wrong_row")
end

EMERALD_LEGS[#EMERALD_LEGS + 1] = {
    name = "emerald_pc_deposit",
    exercises = { "pc_deposit" },
    source = {
        "src/pokemon_storage_system.c:1538-1648 (Task_PCMainMenu; DEPOSIT row 1, refused at one party mon :1592-1598)",
        "src/pokemon_storage_system.c:2580-2660,7621-7669 (party popup STORE row 0 -> Task_DepositMenu)",
        "src/pokemon_storage_system.c:2847-2910 (chooser A -> TryStorePartyMonInBox into the box's first empty slot)",
        "data/scripts/pc.inc:1-55; src/script_menu.c:314-375 (which-PC multichoice, row 0 = storage)",
        "tools/gba_map.py --game emerald --map 2.2: MB_PC 0x83 at (10,1), bfs (7,8)->(10,2)",
    },
    run = function(cp)
        local L = "emerald_pc_deposit"
        play.follow(cp, "em_oldale_center_to_pc", L)
        G.tap("Up", 2, 13)                     -- face the (solid) PC metatile at (10,1)
        local before = owned_snapshot(L .. " before")
        if not before then return end
        if before.party.n ~= 2 or before.current_box ~= 0 then
            return em_fail(L, string.format("precondition: party %d (want 2), current box %d "
                           .. "(want 0) -- emerald_pc.sav's own facts", before.party.n, before.current_box))
        end
        local target, slot = before.party.order[2], nil
        for s = 0, 29 do if not em_box_key(before, 0, s) then slot = s; break end end
        if not slot then return em_fail(L, "precondition: box 0 is full") end
        -- DEPOSIT (row 1): Down, A; the party cursor starts on slot 0, Down selects slot 1, A opens
        -- its popup, A takes STORE (row 0); the chooser opens on sDepositBoxId (box 0) and its A
        -- is the press that calls TryStorePartyMonInBox.
        PC.open(cp, L)
        PC.mode(L, 1)
        PC.popup(L, 1, 1, 0)
        PC.select(L, PC_DEPOSIT_MENU)
        PC.box(L)
        PC.leave(cp, L)
        local after = owned_snapshot(L .. " after")
        if not after then return end
        local gone = play.departed_key(before.party, after.party)
        local boxed = after.boxes[target]
        if after.party.n ~= 1 or gone ~= target or not boxed or boxed.box ~= 0 or boxed.slot ~= slot
           or boxed.species ~= before.mons[target].species then
            return em_fail(L, string.format("deposit_readback: party %d -> %d, departed %s (want %s), "
                           .. "box record %s (want box 0 slot %d, species %d)", before.party.n,
                           after.party.n, tostring(gone), target, boxed and
                           string.format("box %d slot %d species %d", boxed.box, boxed.slot,
                                         boxed.species) or "absent", slot, before.mons[target].species))
        end
        local ok, why = play.survivors_intact(before.party, after.party, target)
        if not ok then return em_fail(L, why) end
        if not boxes_unchanged(L, before.boxes, after.boxes, target) then return end
        G.phase("deposited", string.format("party 2 -> 1, %s now box 0 slot %d", target, slot))
    end,
}

EMERALD_LEGS[#EMERALD_LEGS + 1] = {
    name = "emerald_pc_withdraw",
    exercises = { "pc_withdraw" },
    source = {
        "src/pokemon_storage_system.c:5788-5805 (InitCursor: WITHDRAW opens in the box area, position 0)",
        "src/pokemon_storage_system.c:7621-7669 (box popup WITHDRAW row 0) and :2795-2845 (Task_WithdrawMon -> party)",
    },
    run = function(cp)
        local L = "emerald_pc_withdraw"
        G.tap("Up", 2, 13)
        local before = owned_snapshot(L .. " before")
        if not before then return end
        local target = em_box_key(before, 0, 0)  -- emerald_pc.sav's Zigzagoon
        if not target or before.party.n ~= 1 then
            return em_fail(L, "precondition: box 0 slot 0 occupied and a 1-mon party (after emerald_pc_deposit)")
        end
        PC.open(cp, L)
        PC.mode(L, 0)             -- WITHDRAW is row 0 on a fresh menu: no press moves it
        PC.popup(L, 0, 0, 0)      -- box slot 0, WITHDRAW row 0
        PC.select(L, PC_WITHDRAW_MON)
        PC.withdraw(L)
        PC.leave(cp, L)
        local after = owned_snapshot(L .. " after")
        if not after then return end
        if not verify_pc_transfer(L, "withdraw", before, after, target) then return end
        if play.party_count() ~= 2 then return em_fail(L, "gPlayerPartyCount is not 2 on the field") end
        G.phase("withdrawn", string.format("party 1 -> 2, %s left box 0 slot 0", target))
    end,
}

EMERALD_LEGS[#EMERALD_LEGS + 1] = {
    name = "emerald_pc_box_place",
    exercises = { "pc_box_place" },
    source = {
        "src/pokemon_storage_system.c:1538-1648 (MOVE POKeMON = OPTION_MOVE_MONS, row 2, :54-60)",
        "src/pokemon_storage_system.c:7621-7669 (MOVE on a mon, PLACE on an empty slot while carrying, row 0)",
        "src/pokemon_storage_system.c:2737-2775 (Task_MoveMon grab / Task_PlaceMon place -> SetPlacedMonData box path)",
        "src/pokemon_storage_system.c:6304-6346,6353-6370 (MoveMon/PlaceMon raise/clear sIsMonBeingMoved; "
        .. "SetMovingMonData copies via BoxMonAtToMon, SetPlacedMonData writes it back with SetBoxMonAt)",
        "src/pokemon.c:2898-2908 (BoxMonToMon writes only party-only fields -- STATUS/HP/MAX_HP/MAIL/"
        .. "stats -- so the 80-byte BoxPokemon lands byte-identical: the readback below asserts it)",
        "data/games/gen3_emerald/engine_signals.json pc_box_place (SetPlacedMonData box epilogue, R6<14)",
    },
    run = function(cp)
        local L = "emerald_pc_box_place"
        G.tap("Up", 2, 13)
        local before = owned_snapshot(L .. " before")
        if not before then return end
        local target = em_box_key(before, 0, 1)  -- emerald_pc.sav's Wurmple
        if not target or em_box_key(before, 0, 0) then
            return em_fail(L, "precondition: box 0 slot 0 empty and slot 1 occupied (after emerald_pc_withdraw)")
        end
        -- MOVE POKeMON (row 2): the box cursor opens on slot 0; Right to slot 1, A, A = MOVE (grab);
        -- Left to slot 0, A, A = PLACE. The carried flag must rise and fall between the two.
        PC.open(cp, L)
        EMH.pc_top_row(L, 2)
        PC.mode(L, 2)
        em_box_cursor(L, 1)
        em_move_popup_row0(L, em_thumb(ES.Task_MoveMon))
        em_wait_carry(L, "grab_not_done", 1)
        em_box_cursor(L, 0)
        em_move_popup_row0(L, em_thumb(ES.Task_PlaceMon))
        em_wait_carry(L, "place_not_done", 0)
        PC.leave(cp, L)
        local after = owned_snapshot(L .. " after")
        if not after then return end
        local ok, why = play.survivors_intact(before.party, after.party, nil)
        if not ok or after.party.n ~= before.party.n then
            return em_fail(L, "the party changed: " .. tostring(why))
        end
        local moved = after.boxes[target]
        if not moved or moved.box ~= 0 or moved.slot ~= 0 or moved.raw ~= before.boxes[target].raw then
            return em_fail(L, string.format("place_readback: %s is %s, want box 0 slot 0 byte-identical",
                           target, moved and string.format("box %d slot %d", moved.box, moved.slot) or "gone"))
        end
        if not boxes_unchanged(L, before.boxes, after.boxes, target) then return end
        G.phase("placed", string.format("%s box 0 slot 1 -> slot 0, bytes identical", target))
    end,
}

EMERALD_LEGS[#EMERALD_LEGS + 1] = {
    name = "emerald_pc_release",
    exercises = { "pc_release_begin", "pc_release" },
    source = {
        "src/pokemon_storage_system.c:7621-7669 (party popup in DEPOSIT mode: RELEASE row 3)",
        "src/pokemon_storage_system.c:2912-2975 (Task_ReleaseMon: yes/no on NO, YES -> ReleaseMon, WAS_RELEASED 4, BYE_BYE 5)",
        "src/pokemon_storage_system.c:4315-4319 (ShowYesNoWindow(1) leaves the cursor on NO; Up reaches YES)",
    },
    run = function(cp)
        local L = "emerald_pc_release"
        G.tap("Up", 2, 13)
        local before = owned_snapshot(L .. " before")
        if not before then return end
        if before.party.n ~= 2 then
            return em_fail(L, "precondition: a 2-mon party (after emerald_pc_withdraw); DEPOSIT mode is refused at one")
        end
        local target = before.party.order[2]      -- the withdrawn Zigzagoon
        PC.open(cp, L)
        PC.mode(L, 1)
        PC.popup(L, 1, 1, 3)                      -- party slot 1, RELEASE row 3
        PC.select(L, PC_RELEASE_MON)
        PC.release(L)                             -- NO -> Up -> YES, A, then both messages
        PC.leave(cp, L)
        local after = owned_snapshot(L .. " after")
        if not after then return end
        if not verify_pc_transfer(L, "release", before, after, target) then return end
        if play.party_count() ~= 1 then return em_fail(L, "gPlayerPartyCount is not 1 on the field") end
        G.phase("released", string.format("party 2 -> 1, %s gone from party and all 14 boxes", target))
    end,
}

EMERALD_LEGS[#EMERALD_LEGS + 1] = {
    name = "emerald_save_town",
    exercises = { "save" },
    source = {
        "src/start_menu.c:560-633 (gMenuCallback-driven START menu; HandleStartMenuInput -> "
        .. "StartMenuSaveCallback -> SaveCallback), :51-58 (MENU_ACTION_SAVE == 5, Emerald's own "
        .. "numbering -- FR/LG's is 4)",
        "src/save.c:701 (TrySavingData); the flash sector counter witness (lua/tests/gen3_boot_check.lua "
        .. "save_counter), no guessed menu row -- the same shape lua/tests/gen3_emerald_boot_check.lua's "
        .. "own save_via_menu already proved live (its header: 'twin ... every witness below is "
        .. "Emerald's own'); this leg re-derives the same symbols through `cp`/G because that script "
        .. "is a top-level driver (calls G.finish/G.open itself), not a reusable library function.",
    },
    run = function(cp)
        local x, y = G.pos(cp)
        G.phase("emerald_save_town-start", string.format("at (%d,%d)", x, y))
        emerald_save_via_menu(cp)
    end,
}

-- ── BATTLE group (emerald_battle.sav, Route 102 0.17 (21,16), tall grass) ──────────────────

--- Small back-and-forth loop over four confirmed MB_TALL_GRASS(0x02) tiles (verified live by
--- this card: `python tools/gba_map.py <emerald ROM> --game emerald --map 0.17 --find-behaviour
--- 0x02` lists (21,16),(22,16),(22,17),(21,17) among the patch, none an object-event tile),
--- stopping the instant a wild battle starts. Steps with playlib's own P.step (play.step) --
--- the library's real walking primitive (12 held + 4 idle frames, up to 6 retries), never a raw
--- G.tap (that primitive is for menu presses) -- with `enc = false` so a battle that starts
--- mid-step is reported back, not auto-fought by the generic FR-shaped `battle` callback this
--- file's PL.bind wired up (that callback's own check_whiteout goes through whiteout_destination,
--- whose landing table is hardcoded to Pallet Town/Viridian City map ids -- wrong for Emerald,
--- so this leg fights its own battle with emerald_fight_through below instead of letting the
--- generic path do it). The exact "enc == false: the caller's answer" shape playlib's own
--- P.step docstring names.
--- The loop is a CYCLE keyed by tile (card E2-LEGS): every loop tile has exactly one next step,
--- so a hunt resumed wherever the last encounter stopped it stays on the grass. The fixed
--- Right/Down/Left/Up order it replaced walked OFF the loop from any tile but (21,16) -- the same
--- class of bug FR's grass_step comment documents.
local EM_GRASS_ORIGIN = { 21, 16 }
local EM_GRASS_NEXT = { ["21,16"] = "Right", ["22,16"] = "Down", ["22,17"] = "Left", ["21,17"] = "Up" }
local function emerald_hunt_grass(cp, max_cycles)
    local start_map = play.map(cp)
    for _ = 1, max_cycles * 4 do
        if play.in_battle(cp) then return true end
        local px, py = G.pos(cp)
        local d = EM_GRASS_NEXT[px .. "," .. py]
        if not d then
            G.shot("stuck")
            G.finish(false, string.format("emerald_hunt_grass: (%d,%d) is not on the grass loop "
                                          .. "(21..22,16..17)", px, py))
            return false
        end
        play.step(cp, d, start_map, nil, false)
        if play.in_battle(cp) then return true end
    end
    return play.in_battle(cp)
end

--- Fight an already-triggered battle to its end, same pinned shape as this file's own
--- rival_battle leg: gActionSelectionCursor resets to FIGHT(0) on every new battle
--- (src/battle_controller_player.c, identical source across FR/LG/Emerald), so A,A is FIGHT ->
--- move slot 1 -- not a guess. What the wild/trainer mon does in response is not controlled.
local function emerald_fight_through(cp, label)
    local entered = play.mash_a(250, function() return play.in_battle(cp) end)
    if not entered then
        G.shot("stuck")
        G.finish(false, label .. ": never entered battle")
        return false
    end
    G.phase("battle-begin", label)
    local ended = play.mash_a(1200, function() return not play.in_battle(cp) end)
    if not ended then
        G.shot("stuck")
        G.finish(false, label .. ": in_battle never cleared within budget")
        return false
    end
    G.phase("battle-end", label)
    return true
end

--- Back to EM_GRASS_ORIGIN (21,16) at the end of a grass leg, so the next leg's strict tile
--- guard holds. From (22,y) Left, from (x,17) Up -- both land on loop tiles; a battle rolled on
--- the way is fought through first (same shape as FR's return_to_grass_origin).
local function emerald_return_to_grass_origin(cp, label)
    for _ = 1, 6 do
        if play.in_battle(cp) and not emerald_fight_through(cp, label) then return false end
        play.wait_scene_settled(cp, 1800)
        local px, py = G.pos(cp)
        if px == EM_GRASS_ORIGIN[1] and py == EM_GRASS_ORIGIN[2] then return true end
        if not EM_GRASS_NEXT[px .. "," .. py] then
            G.shot("stuck")
            G.finish(false, string.format("%s: expected to be on the grass loop, found %s",
                                          label, play.at(cp)))
            return false
        end
        play.step(cp, px == 22 and "Left" or "Up", play.map(cp), true, false)
    end
    G.shot("stuck")
    G.finish(false, string.format("%s: never got back to the grass origin (21,16); at %s",
                                  label, play.at(cp)))
    return false
end

EMERALD_LEGS[#EMERALD_LEGS + 1] = {
    name = "emerald_route102_wild_battle",
    exercises = { "battle_begin", "battle_end" },
    check = emerald_at(0, 17, 21, 16),
    source = {
        "data/maps/Route102/map.json; data/tilesets/... (behaviour 0x02 confirmed at (21,16) "
        .. "et al by tools/gba_map.py --game emerald --map 0.17 --find-behaviour 0x02)",
        "src/data/wild_encounters.json MAP_ROUTE102 land_mons (Lv3-4 Poochyena/Wurmple/Lotad/"
        .. "Zigzagoon/Ralts/Seedot, encounter_rate 20)",
        "src/battle_controller_player.c (gActionSelectionCursor resets to FIGHT(0) each battle)",
    },
    run = function(cp)
        local x, y = G.pos(cp)
        G.phase("emerald_route102_wild_battle-start", string.format("hunting from (%d,%d)", x, y))
        if not emerald_hunt_grass(cp, 40) then
            G.shot("stuck")
            G.finish(false, "emerald_route102_wild_battle: 40 cycles of the grass loop produced no encounter")
            return
        end
        if not emerald_fight_through(cp, "emerald_route102_wild_battle") then return end
        emerald_return_to_grass_origin(cp, "emerald_route102_wild_battle")
    end,
}

-- ── Emerald's own battle-bag ball throw (card E2-CATCH-LEG) ───────────────────────────────────────────────────
-- Predicate sequence pinned by docs/gen3_emerald/research/battle_bag_ball_throw_2026-09-25.md
-- (a spot-checked research note; every address below was independently re-verified against
-- pokeemerald.sym and pret sources for this card, see gen3_title_syms.lua's own citations).
-- Emerald's bag is architecturally different from FR/LG's throw_pokeball_from_bag above:
-- `struct BagMenu *gBagMenu` is a heap POINTER (include/item_menu.h:61-86), not FR/LG's static
-- `struct BagStruct gBagMenuState`, and the pocket switch WRAPS (src/item_menu.c:1300-1310
-- ChangeBagPocketId) instead of clamping at the last pocket -- so this steers the pocket BY
-- VALUE (gBagPosition.pocket == BALLS_POCKET), bounded, never by counting presses (a fixed
-- press count would be wrong for whatever pocket OPEN_BAG_LAST remembered).
local BAG_POSITION_ADDR = S.BAG_POSITION_ADDR                     -- gBagPosition (Emerald only)
local BAG_MENU_PTR_ADDR = S.BAG_MENU_PTR_ADDR                     -- gBagMenu (heap pointer)
local TASK_ITEM_CONTEXT_SINGLE_ROW = S.TASK_ITEM_CONTEXT_SINGLE_ROW
local BATTLE_MAIN_CB2 = S.BATTLE_MAIN_CB2
local LAST_USED_ITEM_ADDR = S.LAST_USED_ITEM_ADDR
-- struct BagPosition (include/item_menu.h:49-59): MainCallback exitCallback (u32 @0x00);
-- u8 location @0x04; u8 pocket @0x05; u16 pocketSwitchArrowPos @0x06;
-- u16 cursorPosition[POCKETS_COUNT] @0x08; u16 scrollPosition[POCKETS_COUNT] @0x08+2*5=0x12
-- (POCKETS_COUNT=5, include/constants/item.h:17 -- matches gBagPosition's own 0x1C symbol size:
-- 0x08 + 2*5 + 2*5 == 0x1C).
local EM_BAG_POS_POCKET_OFF, EM_BAG_POS_CURSOR_OFF, EM_BAG_POS_SCROLL_OFF = 0x05, 0x08, 0x12
-- struct BagMenu (include/item_menu.h:61-86): contextMenuNumItems lands at +0x828 -- computed
-- field-by-field (newScreenCallback u32 0x00; tilemapBuffer[BG_SCREEN_SIZE=0x800] 0x04..0x804;
-- spriteIds[ITEMMENUSPRITE_COUNT=12] 0x804..0x810; windowIds[ITEMWIN_COUNT=10] 0x810..0x81A;
-- toSwapPos u8 0x81A; the bitfield byte 0x81B; unused1[2] 0x81C..0x81E; pocketScrollArrowsTask
-- 0x81E; pocketSwitchArrowsTask 0x81F; contextMenuItemsPtr u32 (4-aligned) 0x820..0x824;
-- contextMenuItemsBuffer[4] 0x824..0x828; contextMenuNumItems u8 @0x828) -- spot-checked by the
-- research note as the "cursor on USE" predicate's own byte offset.
local EM_BAG_MENU_CTX_NUM_ITEMS_OFF = 0x828
local BALLS_POCKET = 1        -- include/constants/item.h:13 (0-based gBagPosition.pocket index)
local POCKETS_COUNT_EM = 5    -- include/constants/item.h:17

local function em_bag_pocket() return memory.read_u8(BAG_POSITION_ADDR + EM_BAG_POS_POCKET_OFF) end
--- The highlighted slot in the current pocket's own row: scrollPosition[p] + cursorPosition[p]
--- (mirrors FR's bag_cursor_slot above). Only used to confirm the cursor sits on row 0 -- the
--- fixture's only bag item (tests/fixtures/gen3/README.md: "no bag items besides the Poke
--- Balls"), so row 0 IS the Poke Ball slot without needing a plaintext item-id read.
local function em_bag_row0()
    local p = em_bag_pocket()
    local cursor = memory.read_u16_le(BAG_POSITION_ADDR + EM_BAG_POS_CURSOR_OFF + p * 2)
    local scroll = memory.read_u16_le(BAG_POSITION_ADDR + EM_BAG_POS_SCROLL_OFF + p * 2)
    return cursor + scroll
end
local function em_context_menu_num_items()
    local ptr = memory.read_u32_le(BAG_MENU_PTR_ADDR)
    if ptr == 0 then return -1 end
    return memory.read_u8(ptr + EM_BAG_MENU_CTX_NUM_ITEMS_OFF)
end
--- Is the bag reading input right now? (item_menu.c:1044-1049 Task_BagMenu_HandleInput returns
--- without reading a press while the palette fade runs.) Reuses bag_menu_up() (generic
--- gMain.callback2 == CB2_BagMenuRun, S-resolved for every title) and task_active() (generic
--- gTasks[] scan) -- neither is FR-specific, both already resolve for Emerald.
local function em_bag_input_ready(cp)
    return bag_menu_up() and G.pred_ok(cp, "palette_fade_active")
       and task_active(TASK_BAG_MENU_HANDLE_INPUT)
end

--- Throw a Poke Ball from an already-open battle bag (the caller's action-menu Right+A already
--- fired CB2_BagMenuFromBattle). Hard rules (card E2-CATCH-LEG): never SELECT (it swaps items in
--- battle, research note's own warning -- this function never sends it); steer the pocket BY
--- VALUE, never by counting presses; assert the exact task func before every A; pair "bag gone"
--- with "no bag task" on the throw-committed check; every wait below is bounded and a timeout
--- returns a named failure (via G.finish(false, ...), the same fail-loud shape every leg here
--- uses).
local function emerald_throw_ball(cp, label)
    if not play.in_battle(cp) then
        G.finish(false, label .. ": the battle ended before the bag opened")
        return false
    end

    -- step 2 (bag input-ready): item_menu.c:746-747,774-779,1217.
    local ready = false
    for _ = 1, BAG_INPUT_WAIT_FRAMES do
        if em_bag_input_ready(cp) then ready = true; break end
        G.advance()
    end
    if not ready then
        G.shot("stuck")
        G.finish(false, string.format(
            "%s: the bag never took input in %d frames (callback2 CB2_BagMenuRun, palette fade "
            .. "clear, Task_BagMenu_HandleInput active)", label, BAG_INPUT_WAIT_FRAMES))
        return false
    end

    -- step 3 (pocket, BY VALUE): press, wait (bounded) for gBagPosition.pocket to change, wait
    -- for the bag to settle back to input-ready, and only then press again -- back-to-back
    -- presses land mid pocket-switch-animation and are swallowed (item_menu.c:1284-1310 Switch
    -- BagPocket/Task_SwitchBagPocket).
    for _ = 1, POCKETS_COUNT_EM do
        local before = em_bag_pocket()
        if before == BALLS_POCKET then break end
        G.tap("Right", 3, 0)
        for _ = 1, 60 do
            if em_bag_pocket() ~= before then break end
            G.advance()
        end
        local settled = false
        for _ = 1, 240 do
            if em_bag_input_ready(cp) then settled = true; break end
            G.advance()
        end
        if not settled then
            G.shot("stuck")
            G.finish(false, label .. ": the bag never settled back to input after a pocket switch")
            return false
        end
    end
    if em_bag_pocket() ~= BALLS_POCKET then
        G.shot("stuck")
        G.finish(false, string.format(
            "%s: could not steer gBagPosition.pocket to BALLS_POCKET(%d) (reads %d)",
            label, BALLS_POCKET, em_bag_pocket()))
        return false
    end

    -- step 4 (row 0): the value is live every frame (item_menu.c:1213-1214,1245).
    if em_bag_row0() ~= 0 then
        G.shot("stuck")
        G.finish(false, string.format(
            "%s: the BALLS pocket's cursor is not on row 0 (reads %d)", label, em_bag_row0()))
        return false
    end

    -- Select it (item_menu.c:1245-1267 Task_BagMenu_HandleInput -> OpenContextMenu on A). The
    -- task-func assertion for THIS A is em_bag_input_ready's own task_active(TASK_BAG_MENU_
    -- HANDLE_INPUT) check just above (no frame advanced since, on the "already correct pocket"
    -- path; the settle check on the "steered" path).
    local last_used_before = memory.read_u16_le(LAST_USED_ITEM_ADDR)
    local balls_before = EMH.ball_count()
    G.tap("A", 3, 20)

    -- step 6 (context menu): Task_ItemContext_SingleRow (asserted before this A, hard rule)
    -- showing exactly the 2-item {USE, CANCEL} BattleUse set (item_menu.c:312-314,1536-1538,
    -- 1679-1688). Menu_InitCursor defaults the cursor to row 0 (USE) on open (item_menu.c:1420-
    -- 1431's own FR-precedent shape) -- not re-verified by address here, same assumption FR's
    -- throw_pokeball_from_bag makes for its own USE/CANCEL popup.
    local ctx_ready = false
    for _ = 1, 240 do
        if task_active(TASK_ITEM_CONTEXT_SINGLE_ROW) and em_context_menu_num_items() == 2 then
            ctx_ready = true; break
        end
        G.advance()
    end
    if not ctx_ready then
        G.shot("stuck")
        G.finish(false, string.format(
            "%s: the USE/CANCEL context menu never came up (Task_ItemContext_SingleRow active, "
            .. "contextMenuNumItems==2; reads %d)", label, em_context_menu_num_items()))
        return false
    end

    -- The select-A wrote the highlighted slot's item into gSpecialVar_ItemId before opening this
    -- menu (item_menu.c:1266) -- the same check FR's throw_pokeball_from_bag makes.
    if memory.read_u16_le(SPECIAL_VAR_ITEM_ID_ADDR) ~= ITEM_POKE_BALL then
        G.shot("stuck")
        G.finish(false, string.format("%s: the selected bag item is %d, not ITEM_POKE_BALL(%d) "
                 .. "(gSpecialVar_ItemId)", label, memory.read_u16_le(SPECIAL_VAR_ITEM_ID_ADDR),
                 ITEM_POKE_BALL))
        return false
    end

    -- step 7 (USE): only pressed once ctx_ready confirmed the exact task func above (hard rule).
    -- ItemMenu_UseInBattle -> ItemUseInBattle_PokeBall -> RemoveBagItem (item_use.c:938-947)
    -- decrements the pocket's quantity; the throw-committed witnesses below are the verdict.
    G.tap("A", 3, 30)

    -- step 8 (throw committed): pair "bag gone" with "no bag task" (hard rule) -- callback2 back
    -- to BattleMainCB2, no bag input/context task left active, and gLastUsedItem is the ball just
    -- thrown (battle_main.c:4413; battle_util.c:318-322).
    -- The per-press witness is the pocket losing exactly one ball (OMP cx-39602c02 #1:
    -- ItemUseInBattle_PokeBall's RemoveBagItem, item_use.c:938-947), not gLastUsedItem == 4.
    local committed = false
    for _ = 1, 600 do
        if memory.read_u32_le(GMAIN_CALLBACK2_ADDR) == BATTLE_MAIN_CB2
           and not task_active(TASK_BAG_MENU_HANDLE_INPUT)
           and not task_active(TASK_ITEM_CONTEXT_SINGLE_ROW)
           and EMH.ball_count() == balls_before - 1 then
            committed = true; break
        end
        G.advance()
    end
    if not committed then
        G.shot("stuck")
        G.finish(false, string.format(
            "%s: the throw never committed (callback2 BattleMainCB2, no bag task, pocket %d -> "
            .. "%d, want one fewer) within 600 frames", label, balls_before, EMH.ball_count()))
        return false
    end
    G.phase("ball-thrown", string.format("gLastUsedItem %d -> %d, balls %d -> %d", last_used_before,
                                         memory.read_u16_le(LAST_USED_ITEM_ADDR), balls_before,
                                         EMH.ball_count()))
    return true
end

-- ── leg: emerald_route102_catch (capture_wild) ──────────────────────────────────────────────────
-- Same "throw on the first action-menu turn, retry across ENCOUNTERS (bounded), never across
-- turns of one losing fight" design choice as FR's route1_catch above (that leg's own header
-- has the root-cause story for why). verify_fight_cursor (generic, already resolves for Emerald
-- via S) both clears the "Wild X appeared!" intro text and steers the action cursor to FIGHT(0)
-- before this loop toggles it to BAG(1) -- reused as-is, not re-derived.
--- What the battle is doing, for a failure message (card E2-LEGS round 2): callback2, the battle
--- script's current opcode and gBattleCommunication[0..1] (MULTIUSE_STATE / CURSOR_POSITION,
--- include/constants/battle_script_commands.h:287-288), the action-menu witness and the outcome.
function EMH.battle_dump()
    local ok, msg = pcall(function()
        local instr = memory.read_u32_le(ES.gBattlescriptCurrInstr)
        local op = (instr >= 0x08000000 and instr < 0x0A000000) and memory.read_u8(instr) or -1
        return string.format("callback2=%08X instr=%08X op=%02X comm=[%d,%d] action_menu=%s "
            .. "outcome=%d item=%d last_used=%d", memory.read_u32_le(GMAIN_CALLBACK2_ADDR), instr,
            op, memory.read_u8(ES.gBattleCommunication), memory.read_u8(ES.gBattleCommunication + 1),
            tostring(action_menu_up()), battle_outcome(), memory.read_u16_le(SPECIAL_VAR_ITEM_ID_ADDR),
            memory.read_u16_le(LAST_USED_ITEM_ADDR))
    end)
    return ok and msg or ("battle dump failed: " .. tostring(msg))
end

--- After a committed throw, resolve with B, never A (card E2-LEGS round 2). Live run 1 mashed A:
--- a caught mon reaches BattleScript_TryNicknameCaughtMon (data/battle_scripts_2.s:74-86), whose
--- yes/no starts on YES (Cmd_trygivecaughtmonnick case 0, CURSOR_POSITION = 0,
--- battle_script_commands.c:10224-10229); A there opens the naming screen (:10246-10252,
--- :10264-10275), where more A only types letters -- in_battle stays set and givecaughtmon
--- (capture_wild) never runs: exactly the shadow log (battle_begin, no capture_wild, no
--- battle_end). B is safe at every stop on this path: it advances battle text (text.c:875,893
--- TextPrinterWait*), dismisses the caught-mon dex page (pokedex.c:4032), and declines the
--- nickname (MULTIUSE_STATE = 4, :10256-10260). Returns "ended", "missed" (the action menu came
--- back: the ball broke free) or nil after G.finish.
function EMH.resolve_throw(cp, label)
    for _ = 1, 600 do
        if not play.in_battle(cp) then return "ended" end
        if action_menu_up() then return "missed" end
        G.tap("B", 3, 13)
    end
    G.shot("stuck")
    G.finish(false, label .. ": the throw never resolved (battle still up, no action menu) "
             .. EMH.battle_dump())
end

-- EMH.CATCH_BALLS: emerald_catch.sav carries 20 Poke Balls (card E2-LEGS round 3: five misses at
-- full HP on emerald_battle.sav's 5 balls were bad luck, not a mechanics fault -- every throw
-- committed and the action menu came back). One throw per ball, across turns AND encounters
-- (OMP cx-6903a836 #6); the group guard below checks the count.
EMH.CATCH_BALLS = 20
--- The Poke Ball pocket's total, through reads.lua's own decoder (SaveBlock1 +0x650, quantities
--- XOR the low half of SaveBlock2.encryptionKey -- pret include/global.h:532,1008).
function EMH.ball_count()
    local b = reader.read_balls()
    return b and b.ball_count or -1
end
function EMH.balls_are(n)
    return function()
        local got = EMH.ball_count()
        if got ~= n then
            return string.format("expected %d Poke Balls in the pocket, read %d -- wrong fixture "
                                 .. "loaded for this leg", n, got)
        end
    end
end
local function emerald_route102_catch_loop(cp)
    local L = "emerald_route102_catch"
    -- Driven by the pocket (OMP cx-39602c02 #1/#6): read once, loop while a ball is left, the
    -- fixture's count as the hard cap. Each committed throw takes one (emerald_throw_ball).
    local balls = EMH.ball_count()
    G.phase("balls", string.format("pocket holds %d Poke Balls (cap %d)", balls, EMH.CATCH_BALLS))
    for throw = 1, EMH.CATCH_BALLS do
        if EMH.ball_count() <= 0 then break end
        if not play.in_battle(cp) then
            if not emerald_hunt_grass(cp, 40) then
                G.shot("stuck")
                G.finish(false, string.format("%s: 40 cycles of the grass loop produced no wild "
                         .. "encounter (throw %d, at %s)", L, throw, play.at(cp)))
                return
            end
        end
        local menu = verify_fight_cursor(cp, L)
        if menu ~= "fight" then
            if play.in_battle(cp) then
                G.finish(false, L .. ": no action menu to throw from " .. EMH.battle_dump())
                return
            end
        else
            -- Round 3 probe: gLastUsedItem read 0 before every throw of live run 2 although each
            -- throw set it to 4 (battle_util.c:318). No per-turn clear is in pret; the only
            -- unconditional rewrite is BufferStringBattle's copy from the printed message's own
            -- snapshot (battle_message.c:1965, taken at emit time by battle_controllers.c:1149,1181).
            -- Logging it here, on the action menu, localizes the reset on the next live run.
            G.phase("throw-start", string.format("throw %d on the action menu: gLastUsedItem=%d balls=%d",
                    throw, memory.read_u16_le(LAST_USED_ITEM_ADDR), EMH.ball_count()))
            G.tap("Right", 3, 20)  -- FIGHT(0) -> BAG(1), pinned bit toggle
            if action_cursor() ~= ACTION_BAG then
                G.shot("stuck")
                G.finish(false, string.format("%s: Right did not move the cursor to BAG (read %d)",
                                              L, action_cursor()))
                return
            end
            G.tap("A", 3, 30)  -- opens the battle bag (CB2_BagMenuFromBattle)
            -- A false verdict has already finished the run with its named stage (OMP cx-6903a836
            -- #7): stop here, before a single further press can land in a possibly-open bag.
            if not emerald_throw_ball(cp, L) then return end
            local result = EMH.resolve_throw(cp, L)
            if not result then return end
            G.phase("throw-resolved", string.format("throw %d: %s, outcome=%d", throw, result,
                                                    battle_outcome()))
            if result == "ended" then
                if battle_outcome() == B_OUTCOME_CAUGHT then
                    play.wait_scene_settled(cp, 1800)
                    G.phase("caught", "outcome=" .. battle_outcome())
                    return
                end
                play.wait_scene_settled(cp, 1800)   -- fled/other: hunt the next encounter
            end
        end
    end
    G.shot("stuck")
    G.finish(false, string.format("%s: never reached B_OUTCOME_CAUGHT after %d balls (last "
             .. "outcome=%d) %s", L, EMH.CATCH_BALLS, battle_outcome(), EMH.battle_dump()))
end

EMERALD_LEGS[#EMERALD_LEGS + 1] = {
    name = "emerald_route102_catch",
    exercises = { "capture_wild" },
    check = emerald_at(0, 17, 21, 16, EMH.balls_are(EMH.CATCH_BALLS)),  -- emerald_catch.sav
    source = {
        "docs/gen3_emerald/research/battle_bag_ball_throw_2026-09-25.md (spot-checked predicate "
        .. "sequence this leg implements steps 0-9 of)",
        "include/item_menu.h:49-86 (struct BagPosition gBagPosition -- a real redesign from FR/"
        .. "LG's static struct BagStruct gBagMenuState -- and struct BagMenu *gBagMenu, a heap "
        .. "pointer); gen3_title_syms.lua's BAG_POSITION_ADDR/BAG_MENU_PTR_ADDR entries",
        "include/constants/item.h:12-17 (ITEMS_POCKET..KEYITEMS_POCKET 0-4, POCKETS_COUNT=5, "
        .. "BALLS_POCKET=1 -- the 0-based gBagPosition.pocket scale, distinct from gItems' own "
        .. "1-based POCKET_POKE_BALLS=2)",
        "src/item_menu.c:1300-1310 (ChangeBagPocketId: the pocket switch WRAPS, no clamp) and "
        .. ":1284-1400 (SwitchBagPocket/Task_SwitchBagPocket: back-to-back presses are swallowed "
        .. "mid-animation)",
        "src/item_menu.c:312-314,1536-1538,1679-1688 (ITEMMENULOCATION_BATTLE routes to "
        .. "sContextMenuItems_BattleUse {ACTION_BATTLE_USE, ACTION_CANCEL}, always 2 items -> "
        .. "Task_ItemContext_Normal picks Task_ItemContext_SingleRow)",
        "src/item_use.c:938-947 (ItemUseInBattle_PokeBall -> RemoveBagItem, the quantity "
        .. "decrement); src/battle_main.c:4413 (BattleMainCB2); src/battle_util.c:318-322 "
        .. "(HandleAction_UseItem sets gLastUsedItem before gBattlescriptsForBallThrow)",
        "include/constants/battle.h:106 (B_OUTCOME_CAUGHT=7)",
        "data/battle_scripts_2.s:64-86; src/battle_script_commands.c:10220-10290 (caught-mon "
        .. "nickname yes/no starts on YES; B declines) -- the post-throw resolution presses B only",
        "src/text.c:875,893; src/pokedex.c:4032 (B advances battle text and the caught dex page)",
        "src/item_menu.c:1266 (the select-A writes gSpecialVar_ItemId)",
        "tests/fixtures/gen3/README.md (emerald_battle.sav: 5 Poke Balls, no bag items besides "
        .. "the Poke Balls -- the fixture fact em_bag_row0's ==0 check relies on)",
    },
    run = function(cp)
        local x, y = G.pos(cp)
        G.phase("emerald_route102_catch-start", string.format("hunting from (%d,%d)", x, y))
        emerald_route102_catch_loop(cp)
        emerald_return_to_grass_origin(cp, "emerald_route102_catch")
    end,
}

-- ── LOWHP group (emerald_lowhp.sav, Route 102 0.17 (21,16), card E2-LEGS) ───────────────────
-- emerald_lowhp.sav (tests/fixtures/gen3/README.md, tools/gen3_fixtures.py kind "lowhp"): the
-- battle tile, party = [Mudkip Lv5 at 1 HP] (moves[0] TACKLE), lastHealLocation = Oldale Town.
-- A single hit KOs the lead; with no other mon the battle ends in a whiteout. The group guard
-- refuses the full-HP emerald_battle.sav, which shares the tile.
EMERALD_LEGS[#EMERALD_LEGS + 1] = {
    name = "emerald_route102_faint",
    exercises = { "faint" },
    check = emerald_at(0, 17, 21, 16, em_lead_hp_is(1, 1)),  -- emerald_lowhp.sav
    source = {
        "src/data/wild_encounters.json MAP_ROUTE102 land_mons (Lv3-4; every one has a damaging move)",
        "src/battle_script_commands.c Cmd_tryfaintmon (gBattleResults.playerFaintCounter++, "
        .. "engine_signals.json faint: +0x11C after the counter store)",
        "src/battle_controller_player.c (gActionSelectionCursor resets to FIGHT(0) each battle: A,A = move 0, TACKLE)",
    },
    run = function(cp)
        local L = "emerald_route102_faint"
        -- The terminal is RAM: the lead's party HP reading 0 (the battle writes party HP back on
        -- every HP change) or the faint counter rising, witnessed IN battle. A battle the 1-HP
        -- Mudkip wins instead ends normally and the next encounter is hunted.
        for encounter = 1, 10 do
            if not emerald_hunt_grass(cp, 40) then
                G.shot("stuck")
                G.finish(false, string.format("%s: 40 cycles of the grass loop produced no "
                                              .. "encounter (attempt %d)", L, encounter))
                return
            end
            G.phase("battle-begin", string.format("%s #%d", L, encounter))
            play.mash_a(1200, function()
                return slot0_hp() == 0 or player_faints() > 0 or not play.in_battle(cp)
            end)
            if play.in_battle(cp) and (slot0_hp() == 0 or player_faints() > 0) then
                G.phase("fainted", string.format("lead HP %d, playerFaintCounter %d, still in battle",
                                                 (slot0_hp()), player_faints()))
                return
            end
            if play.in_battle(cp) then
                G.shot("stuck")
                G.finish(false, L .. ": the battle neither ended nor fainted the lead within budget")
                return
            end
            play.wait_scene_settled(cp, 1800)
            G.phase("battle-won", string.format("%s #%d: the lead survived at %d HP", L, encounter,
                                                (slot0_hp())))
        end
        G.shot("stuck")
        G.finish(false, L .. ": the lead never fainted in 10 encounters")
    end,
}

EMERALD_LEGS[#EMERALD_LEGS + 1] = {
    name = "emerald_route102_whiteout",
    exercises = { "whiteout" },
    source = {
        "src/overworld.c:358-365 (DoWhiteOut: HealPlayerParty, SetWarpDestinationToLastHealLocation, "
        .. "WarpIntoMap) and :665-668 (the destination IS gSaveBlock1Ptr->lastHealLocation -- no "
        .. "FR-style interior projection) and :1550-1570 (CB2_WhiteOut)",
        "include/global.h:990 (SaveBlock1.lastHealLocation @ +0x1C, struct WarpData :581)",
        "src/data/heal_locations.json:82-85 (HEAL_LOCATION_OLDALE_TOWN = MAP_OLDALE_TOWN (6,17))",
    },
    run = function(cp)
        local L = "emerald_route102_whiteout"
        if not play.in_battle(cp) or slot0_hp() ~= 0 then
            G.finish(false, string.format("%s: precondition: in battle with the lead at 0 HP "
                     .. "(emerald_route102_faint), read in_battle=%s HP %d", L,
                     tostring(play.in_battle(cp)), (slot0_hp())))
            return
        end
        local heal = last_heal_checkpoint(cp)
        if not heal then return end
        -- MAP_OLDALE_TOWN = group 0 num 10 (emerald_enter_pc's own tile), WARP_ID_NONE = 0xFF.
        if heal.group ~= 0 or heal.num ~= 10 or heal.warp ~= 255 or heal.x ~= 6 or heal.y ~= 17 then
            G.finish(false, string.format("%s: lastHealLocation is %d.%d warp %d (%d,%d), not "
                     .. "Oldale Town's heal tile 0.10 (6,17)", L, heal.group, heal.num, heal.warp,
                     heal.x, heal.y))
            return
        end
        if not play.mash_a(400, function() return not play.in_battle(cp) end) then
            G.shot("stuck")
            G.finish(false, L .. ": in_battle never cleared after the faint")
            return
        end
        local arrived = false
        for _ = 1, 3000 do
            local g, n = G.map(cp)
            local px, py = G.pos(cp)
            if g == heal.group and n == heal.num and px == heal.x and py == heal.y then
                arrived = true; break
            end
            G.advance()
        end
        if not arrived then
            G.shot("stuck")
            G.finish(false, string.format("%s: never landed on lastHealLocation 0.10 (6,17); at %s",
                                          L, play.at(cp)))
            return
        end
        play.wait_scene_settled(cp, 1800)
        if not verify_destination(cp, L, { group = heal.group, num = heal.num, x = heal.x, y = heal.y }) then
            return
        end
        local hp, maxhp = slot0_hp()
        if memory.read_u8(PARTY_COUNT_ADDR) ~= 1 or hp ~= maxhp or maxhp <= 1 then
            G.finish(false, string.format("%s: not healed by DoWhiteOut: party %d, HP %d/%d", L,
                                          memory.read_u8(PARTY_COUNT_ADDR), hp, maxhp))
            return
        end
        G.phase("whited-out", string.format("landed 0.10 (6,17), lead healed %d/%d", hp, maxhp))
    end,
}

-- ── TRAINER group (emerald_trainer.sav, Route 102 0.17 (32,16)) ────────────────────────────

EMERALD_LEGS[#EMERALD_LEGS + 1] = {
    name = "emerald_calvin_trainer_battle",
    exercises = { "battle_begin", "battle_end" },
    check = emerald_at(0, 17, 32, 16),
    source = {
        "data/maps/Route102/map.json (object_events: OBJ_EVENT_GFX_YOUNGSTER at (33,14), "
        .. "MOVEMENT_TYPE_FACE_DOWN, trainer_sight_or_berry_tree_id=3, script "
        .. "Route102_EventScript_Calvin -- a facing-down sight line covers his column x=33, "
        .. "y=15..17, so one Right step from (32,16) to (33,16) enters it)",
        "data/maps/Route102/scripts.inc:20-21 (Route102_EventScript_Calvin: "
        .. "trainerbattle_single TRAINER_CALVIN_1, ...)",
    },
    run = function(cp)
        -- One real walking step (play.step, not a raw G.tap) from the fixture's own tile
        -- (32,16) onto (33,16), Calvin's sight column. The sight-triggered approach that
        -- follows (lockall, NPC walk to the player, intro text) is entirely scripted;
        -- emerald_fight_through's own A-mash clears it, same as this file's rival_battle intro.
        local px0, py0 = G.pos(cp)
        G.phase("emerald_calvin_trainer_battle-start", string.format("at (%d,%d)", px0, py0))
        local moved = play.step(cp, "Right", play.map(cp), true)
        if not moved then
            G.shot("stuck")
            G.finish(false, "emerald_calvin_trainer_battle: the step into Calvin's sight line stalled")
            return
        end
        emerald_fight_through(cp, "emerald_calvin_trainer_battle")
    end,
}

-- ── EVOLVE group (emerald_evolve.sav, Route 102 0.17 (21,16), card E2-LEGS round 3) ─────────
-- SYNTH setup, native behaviour: the fixture's Mudkip is Lv15 with EXP one short of Lv16 and
-- fewer than four moves; the level-up, the evolution scene and the species store all run native.
EMH.SPECIES_MUDKIP, EMH.SPECIES_MARSHTOMP = 283, 284   -- include/constants/species.h:289-290
EMH.OFF_STATUS, EMH.OFF_LEVEL = 0x50, 0x54             -- struct Pokemon party tail (include/pokemon.h)

--- Party guard: count, the lead's (decrypted) species, its plaintext level, and an open move
--- slot. With a free slot, MonTryLearningNewMove gives MUD_SHOT (Marshtomp's Lv16 move) without
--- the "delete a move?" yes/no (src/evolution_scene.c:775,791-792: EVOSTATE_TRY_LEARN_MOVE ->
--- REPLACE_MOVE only on MON_HAS_MAX_MOVES), so no move prompt can meet the A-only presses below.
function EMH.lead_is(n, species, level)
    return function()
        local count = memory.read_u8(PARTY_COUNT_ADDR)
        local mons = reader.read_party()
        local mon = mons and mons[1]
        local lvl = memory.read_u8(PARTY_BASE + EMH.OFF_LEVEL)
        local free = 0
        if mon then for i = 1, 4 do if (mon.moves[i] or 0) == 0 then free = free + 1 end end end
        if count ~= n or not mon or mon.species ~= species or lvl ~= level or free == 0 then
            return string.format("expected a %d-mon party led by species %d Lv%d with a free move "
                                 .. "slot, read party=%d species=%s Lv%d free_slots=%d -- wrong "
                                 .. "fixture loaded for this leg", n, species, level, count,
                                 tostring(mon and mon.species), lvl, free)
        end
    end
end

EMERALD_LEGS[#EMERALD_LEGS + 1] = {
    name = "emerald_evolve",
    exercises = { "evolve_species_store" },
    check = emerald_at(0, 17, 21, 16, EMH.lead_is(1, EMH.SPECIES_MUDKIP, 15)),  -- emerald_evolve.sav
    source = {
        "src/evolution_scene.c:637-647 (Task_EvolutionScene: B HELD during "
        .. "EVOSTATE_WAIT_CYCLE_MON_SPRITE cancels the evolution) -- so this leg presses ONLY A",
        "src/evolution_scene.c:757-771 (EVOSTATE_SET_MON_EVOLVED: SetMonData(MON_DATA_SPECIES), the "
        .. "evolve_species_store site, docs/gen3_emerald/engine_sites.md)",
        "src/evolution_scene.c:930-946 (the learn-move yes/no; B == NO) -- unreachable here: the guard "
        .. "requires a free move slot",
        "src/data/pokemon/evolution.h:129 (SPECIES_MUDKIP: EVO_LEVEL 16 -> SPECIES_MARSHTOMP)",
        "src/battle_controller_player.c (gActionSelectionCursor resets to FIGHT(0) each battle: A,A = move 0)",
    },
    run = function(cp)
        local L = "emerald_evolve"
        if not emerald_hunt_grass(cp, 40) then
            G.shot("stuck")
            G.finish(false, L .. ": 40 cycles of the grass loop produced no encounter")
            return
        end
        G.phase("battle-begin", L)
        -- A only, from the battle through the level-up and the whole evolution scene, until the
        -- overworld callback is back. play.mash_a never presses anything but A.
        if not play.mash_a(3000, function() return play.on_field(cp) end) then
            G.shot("stuck")
            G.finish(false, L .. ": the field never came back after the battle/evolution "
                     .. EMH.battle_dump())
            return
        end
        play.wait_scene_settled(cp, 1800)
        local mons = reader.read_party()
        local mon = mons and mons[1]
        local lvl = memory.read_u8(PARTY_BASE + EMH.OFF_LEVEL)
        if not mon or mon.species ~= EMH.SPECIES_MARSHTOMP or lvl ~= 16 then
            G.shot("stuck")
            G.finish(false, string.format("%s: party[0] is species %s Lv%d, want MARSHTOMP(%d) Lv16",
                                          L, tostring(mon and mon.species), lvl, EMH.SPECIES_MARSHTOMP))
            return
        end
        G.phase("evolved", string.format("party[0] species %d Lv%d", mon.species, lvl))
    end,
}

-- ── POISON group (emerald_poison.sav, Oldale Town 0.10 (6,17), card E2-LEGS round 3) ────────
-- party = [Mudkip PSN at 1 HP, Poochyena]. Every 4th step UpdatePoisonStepCounter
-- (field_control_avatar.c:637-660, VAR_POISON_STEP_COUNTER %4) runs DoPoisonFieldEffect
-- (field_poison.c:120-154): 1 HP -> 0, FLDPSN_FNT -> EventScript_FieldPoison
-- (data/scripts/field_poison.inc:1-7) -> TryFieldPoisonWhiteOut: FaintFromFieldPoison clears the
-- status (field_poison.c:42-51), prints the faint message, and with Poochyena standing it is
-- FLDPSN_NO_WHITEOUT (:101-104) -- releaseall, no warp.
-- tools/gba_map.py --game emerald --map 0.10: (6,17) and (7,17) collision 0, behaviour 0x00, no
-- object (objects (16,11) (13,7) (8,9) (11,19)) and no coord event (coords (0,10) (8,19) (9,19)
-- (10,19)). The walk only ever presses Right/Left between them: never Up into the PC door (6,16).
EMH.POISON_TILES = { { 6, 17 }, { 7, 17 } }
EMH.STATUS1_PSN_ANY = 0x88                             -- include/constants/battle.h:117-124
function EMH.poison_party()
    return function()
        local count = memory.read_u8(PARTY_COUNT_ADDR)
        local hp, maxhp = slot0_hp()
        local status = memory.read_u32_le(PARTY_BASE + EMH.OFF_STATUS)
        -- the second mon must be healthy, or a faint would white out (field_poison.c:27-38)
        local status2 = memory.read_u32_le(PARTY_BASE + MON_SIZE + EMH.OFF_STATUS)
        local hp2 = memory.read_u16_le(PARTY_BASE + MON_SIZE + OFF_HP)
        if count ~= 2 or hp ~= 1 or maxhp <= 1 or status & EMH.STATUS1_PSN_ANY == 0
            or status2 ~= 0 or hp2 == 0 then
            return string.format("expected [poisoned lead at 1 HP, healthy second mon], read party=%d "
                                 .. "HP %d/%d status=0x%X second HP %d status=0x%X -- wrong fixture "
                                 .. "loaded for this leg", count, hp, maxhp, status, hp2, status2)
        end
    end
end

EMERALD_LEGS[#EMERALD_LEGS + 1] = {
    name = "emerald_poison_faint",
    exercises = { "poison_hp_before", "poison_faint" },
    check = emerald_at(0, 10, 6, 17, EMH.poison_party()),  -- emerald_poison.sav
    source = {
        "src/field_control_avatar.c:549-552,637-660 (UpdatePoisonStepCounter: every 4th step)",
        "src/field_poison.c:120-154 (DoPoisonFieldEffect: poison_hp_before +0x34, poison_faint +0x4E)",
        "src/field_poison.c:42-51,65-109 (FaintFromFieldPoison clears STATUS; FLDPSN_NO_WHITEOUT while "
        .. "another mon stands); data/scripts/field_poison.inc:1-7",
        "tools/gba_map.py --game emerald --map 0.10 ((6,17)/(7,17) free, no object, no coord event)",
    },
    run = function(cp)
        local L = "emerald_poison_faint"
        local map0 = play.map(cp)
        -- Right/Left between the two tiles; the counter fires within 4 steps, 12 is the bound.
        for _ = 1, 12 do
            if slot0_hp() == 0 then break end
            local px = G.pos(cp)
            local ok, why = play.step(cp, px == EMH.POISON_TILES[1][1] and "Right" or "Left", map0,
                                      true, false)
            if not ok and slot0_hp() ~= 0 then
                G.shot("stuck")
                G.finish(false, string.format("%s: poison walk step failed (%s) at %s", L,
                         tostring(why), play.at(cp)))
                return
            end
        end
        if slot0_hp() ~= 0 then
            G.shot("stuck")
            G.finish(false, L .. ": 12 steps and the lead never reached 0 HP from field poison")
            return
        end
        G.phase("poison-hp-zero", play.at(cp))
        -- A through the faint message. The status word clears when the message is printed
        -- (FaintFromFieldPoison), the script releases after it closes: both are the stop.
        if not play.mash_a(60, function()
            return memory.read_u32_le(PARTY_BASE + EMH.OFF_STATUS) == 0 and play.on_field(cp)
               and G.pred_ok(cp, "script_context_status") and G.pred_ok(cp, "field_controls_locked")
        end) then
            G.shot("stuck")
            G.finish(false, L .. ": the field-poison faint message never closed")
            return
        end
        local g, n = G.map(cp)
        local hp = slot0_hp()
        local status = memory.read_u32_le(PARTY_BASE + EMH.OFF_STATUS)
        local count = memory.read_u8(PARTY_COUNT_ADDR)
        if hp ~= 0 or status ~= 0 or count ~= 2 or play.map(cp) ~= map0 then
            G.shot("stuck")
            G.finish(false, string.format("%s: want HP 0, status 0, party 2, still on 0.10; read HP %d "
                     .. "status 0x%X party %d map %d.%d", L, hp, status, count, g, n))
            return
        end
        G.phase("poison-fainted", string.format("lead HP 0, status cleared, party 2, still at %s",
                                                play.at(cp)))
    end,
}

-- ── GIFT group (emerald_gift.sav, card E2-LEGS round 3) ─────────────────────────────────────
-- The input policy is witness-driven, not counted: A until gPlayerPartyCount rises (talk, the
-- accept yes/no -- every MSGBOX_YESNO defaults to YES, script_menu.c ScriptMenu_YesNo -- and the
-- text before the give), then ONLY B until the script is quiet. After the give, B closes every
-- field message (text.c:875,893 accept A|B) and answers NO to a nickname yes/no (B ==
-- MENU_B_PRESSED == NO in Task_HandleYesNoInput), the round-2 lesson from the caught-mon prompt.
EMH.GIFT = {
    -- emerald_gift.sav (tools/gen3_fixtures.py kind "gift"): LavaridgeTown = group 0 num 12
    -- (data/maps/map_groups.json), the egg woman OBJ_EVENT_GFX_EXPERT_F at (4,7) FACE_DOWN
    -- (data/maps/LavaridgeTown/map.json), the player one tile south at (4,8) (gba_map: collision
    -- 0, MB_MOUNTAIN_TOP 0x0C) turning Up. Fixture state: party [Mudkip], FLAG_RECEIVED_LAVARIDGE_EGG
    -- clear, VAR_LAVARIDGE_TOWN_STATE ~= 1 (1 runs the rival's Go-Goggles ON_FRAME scene,
    -- scripts.inc:40-42).
    group = 0, num = 12, x = 4, y = 8, face = "Up", party_before = 1,
    species = 360, is_egg = 1,          -- SPECIES_WYNAUT, include/constants/species.h:366
    source = {
        "data/maps/LavaridgeTown/scripts.inc:232-247 (EggWoman: MSGBOX_YESNO, giveegg SPECIES_WYNAUT)",
        "src/script_pokemon_util.c:87-97 (ScriptGiveEgg: CreateEgg, MON_DATA_IS_EGG, GiveMonToPlayer)",
        "src/pokemon.c:4425-4445 (GiveMonToPlayer: the mon_given site, docs/gen3_emerald/engine_sites.md)",
        "src/text.c:875,893 (field text closes on A or B); script_menu.c yes/no: B == NO",
    },
}

function EMH.gift_party()
    return function()
        local count = memory.read_u8(PARTY_COUNT_ADDR)
        if count ~= EMH.GIFT.party_before then
            return string.format("expected a %d-mon party before the gift, read %d -- wrong fixture "
                                 .. "loaded for this leg", EMH.GIFT.party_before, count)
        end
    end
end

EMERALD_LEGS[#EMERALD_LEGS + 1] = {
    name = "emerald_mon_given",
    exercises = { "mon_given" },
    check = emerald_at(EMH.GIFT.group, EMH.GIFT.num, EMH.GIFT.x, EMH.GIFT.y, EMH.gift_party()),
    source = EMH.GIFT.source,
    run = function(cp)
        local L = "emerald_mon_given"
        local want = EMH.GIFT.party_before + 1
        G.tap(EMH.GIFT.face, 2, 13)               -- turn toward the NPC (its tile is blocked)
        for _ = 1, 80 do
            if memory.read_u8(PARTY_COUNT_ADDR) == want then break end
            G.tap("A", 3, 13)
        end
        -- giveegg follows `waitfanfare` (LavaridgeTown/scripts.inc:243-245): wait it out, no press
        for _ = 1, 40 do
            if memory.read_u8(PARTY_COUNT_ADDR) == want then break end
            G.idle(15)
        end
        if memory.read_u8(PARTY_COUNT_ADDR) ~= want then
            G.shot("stuck")
            G.finish(false, string.format("%s: the party never grew to %d (read %d)", L, want,
                                          memory.read_u8(PARTY_COUNT_ADDR)))
            return
        end
        G.phase("given", string.format("party %d -> %d", EMH.GIFT.party_before, want))
        local quiet = false
        for _ = 1, 60 do
            if play.on_field(cp) and G.pred_ok(cp, "script_context_status")
               and G.pred_ok(cp, "field_controls_locked") then quiet = true; break end
            G.tap("B", 3, 13)
        end
        if not quiet then
            G.shot("stuck")
            G.finish(false, L .. ": the gift script never went quiet under B")
            return
        end
        local mons = reader.read_party()
        local mon = mons and mons[want]
        if not mon or mon.species ~= EMH.GIFT.species or mon.is_egg ~= EMH.GIFT.is_egg
           or memory.read_u8(PARTY_COUNT_ADDR) ~= want then
            G.shot("stuck")
            G.finish(false, string.format("%s: party[%d] is species %s egg %s, want %d egg %d", L,
                     want - 1, tostring(mon and mon.species), tostring(mon and mon.is_egg),
                     EMH.GIFT.species, EMH.GIFT.is_egg))
            return
        end
        G.phase("gift-verified", string.format("party[%d] species %d egg %d", want - 1, mon.species,
                                               mon.is_egg))
    end,
}

end -- if TITLE == "emerald"

-- ── run ──────────────────────────────────────────────────────────────────────────────────────

--- LEGS/PATHS/DEST/verify_starter/verify_rival/parcel-delivery are the Pallet Town INTRO STORY,
-- pinned against tests/fixtures/gen3/firered_town.sav (card C4-LG: the duo drivers reuse this
-- file's WITNESS CONSTANTS on both sides of a live FR<->LG duo, never this story playthrough).
-- Owner ruling 2026-09-23 (card C4-LGF2): FireRed and LeafGreen are the same pret pokefirered
-- engine built twice -- the intro is the same, so LG reuses this FR story rather than getting
-- its own. Every S.<ADDR> above already resolves per-title via Syms.for_title(TITLE)
-- (test_gen3_title_syms.py), and every oracle below (verify_starter/verify_rival/DEST tiles/
-- flags) reads species/flag ids and map tiles that are identical data in both titles -- so
-- nothing here needs an LG-specific literal. radical_red still refuses: its fixture is an
-- imported real save, not a scripted new game, and the shared runtime says so itself
-- (lua/tests/gen3_fr_newgame_inputs.lua header: "Radical Red is NOT driven by this script").
--- SLINK_GEN3_PLAY_STOP_AFTER=<leg name> (card C4-LGF2): run LEGS[1..that leg], walk back to
-- the Route 1 grass origin (12,37) if the stop leg left the player on the grass square, then
-- save in-game there -- reusing the SAME "save" leg object defined above, never a duplicate of
-- its logic. Built for the LG source-save bootstrap (tests/fixtures/gen3/README.md, "The LG
-- source save" option 3): the card's own chain wants exactly starter/rival/parcel/Poke-Balls/
-- route1_catch, landing where make-party --kind town's own contract expects its seed (an
-- unhealed party standing AT (12,37)) -- not the "save" leg's default (far) position after the
-- PC deposit/withdraw/release legs nobody asked LG to exercise yet. Unset (the default), this
-- changes nothing: `legs` is just `LEGS` and every existing caller keeps byte-for-byte behaviour.
local function stopped_legs(stop_after)
    local idx, save_leg
    for i, leg in ipairs(LEGS) do
        if leg.name == stop_after then idx = i end
        if leg.name == "save" then save_leg = leg end
    end
    if not idx then
        G.finish(false, "gen3_scripted_play: SLINK_GEN3_PLAY_STOP_AFTER names no leg: "
                     .. stop_after)
        return nil
    end
    local legs = {}
    for i = 1, idx do legs[i] = LEGS[i] end
    if stop_after == "route1_catch" then
        legs[#legs + 1] = {
            name = "return_to_grass_origin",
            exercises = { "walk" },
            source = { "return_to_grass_origin (this file): the grass-loop origin walk-back "
                     .. "every later Route 1 leg already reuses" },
            run = function(cp) return_to_grass_origin(cp, "play_stop_after") end,
        }
    end
    legs[#legs + 1] = assert(save_leg, "gen3_scripted_play: no 'save' leg defined")
    return legs
end

--- SLINK_GEN3_PLAY_STOP_AFTER for Emerald (card E2-LEGS): EMERALD_LEGS[1..that leg] and nothing
--- appended -- each fixture group is its own run (PLAY_FROM = its first leg, STOP_AFTER = its
--- last). Pure: returns the legs, or nil and the refusal the caller finishes with.
local function emerald_stopped_legs(stop_after)
    local legs = {}
    for i, leg in ipairs(EMERALD_LEGS) do
        legs[i] = leg
        if leg.name == stop_after then return legs end
    end
    return nil, "gen3_scripted_play: SLINK_GEN3_PLAY_STOP_AFTER names no Emerald leg: " .. stop_after
end

local function run()
    if TITLE == "emerald" then
        local stop_after = os.getenv("SLINK_GEN3_PLAY_STOP_AFTER")
        local em_legs, why = EMERALD_LEGS, nil
        if stop_after then em_legs, why = emerald_stopped_legs(stop_after) end
        if not em_legs then G.finish(false, why); return end
        -- A-only boot (no Start pulse): gen3_emerald_boot_check.lua's own boot_to_field is
        -- A-only too, deliberately not G.boot_to_field's A/Start alternation -- Emerald's own
        -- title/save-select screens are not proven safe against a stray Start the way FR/LG's
        -- are (that shared helper was written and tuned for FR/LG only).
        play.main(em_legs, {
            name   = "gen3_scripted_play_emerald",  -- patch/build/gen3_scripted_play_emerald_result.txt
            budget = 900000,
            save_states = "slink_em_",
            boot = function(cp)
                local held = 0
                for _ = 1, 9000 do
                    if G.pred_ok(cp, "callback2") and G.pred_ok(cp, "field_controls_locked") then  -- pred true == free
                        held = held + 1
                        joypad.set({})
                        if held >= 60 then return end
                        G.advance()
                    else
                        held = 0
                        joypad.set(G.spent % 16 == 8 and { A = true } or {})
                        G.advance()
                    end
                end
                G.shot("stuck")
                G.finish(false, "boot: never reached a free field in 9000 frames")
            end,
            shadow = {
                script = WT .. "/lua/gen3/shadow_run.lua",
                result = WT .. "/patch/build/gen3_scripted_play_emerald_result.txt",
                name   = "SLink-gen3-shadow-poll",
            },
        })
        return
    end
    if TITLE ~= "firered" and TITLE ~= "leafgreen" then
        G.finish(false, "gen3_scripted_play: the Pallet Town story legs (LEGS/PATHS/DEST) are "
                     .. "FireRed/LeafGreen-only; SLINK_GEN3_TITLE=" .. tostring(TITLE))
        return
    end
    local stop_after = os.getenv("SLINK_GEN3_PLAY_STOP_AFTER")
    local legs = stop_after and stopped_legs(stop_after) or LEGS
    if stop_after and not legs then return end   -- stopped_legs already called G.finish(false, ...)
    play.main(legs, {
        name   = "gen3_scripted_play",      -- patch/build/gen3_scripted_play_result.txt
        budget = 900000,
        -- A savestate per FINISHED leg (slink_fr_<leg>.State / slink_lg_<leg>.State). The FR
        -- checkpoint negatives (lua/tests/probe_gen3_checkpoint.lua) need an in-battle-reachable
        -- state and a door state, and tests/fixtures/gen3/firered_town.sav has party=0 -- no
        -- wild battle is reachable from it at all, so this run is the only route there: the
        -- state at starter's leg-done is one A press from the rival battle, and
        -- leave_lab_for_parcel's is the lab door. A leg that FAILED saves nothing; a state
        -- written mid-failure is a trap. Title-prefixed (card C4-LGF2) so an LG run never
        -- clobbers FR's own committed probe states with LG data under the same filename.
        save_states = TITLE == "leafgreen" and "slink_lg_" or "slink_fr_",
        -- The fixture's battery is seeded but the field pointer is not sane at cold boot until
        -- the title screen -> CONTINUE has run (gen3_boot_check.lua run():300-320); a leg cannot
        -- read G.pos/G.map before this. It happens BEFORE the observer starts, deliberately: the
        -- title screen's own map loads are not natural play.
        boot = function(cp)
            if not G.boot_to_field(cp, 9000) then
                G.shot("stuck")
                local cb2 = G.pred(cp, "callback2")
                G.finish(false, string.format("boot: never reached the field (callback2=%08X)", cb2))
            end
        end,
        shadow = {
            script = WT .. "/lua/gen3/shadow_run.lua",
            result = WT .. "/patch/build/gen3_scripted_play_result.txt",
            name   = "SLink-gen3-shadow-poll",
        },
    })
end

if (debug.getinfo(1, "S").source or "") == "main" then run() end

return {
    LEGS = LEGS, PATHS = PATHS, play = play,
    EMERALD_LEGS = EMERALD_LEGS, PROFILE_PACK_BY_TITLE = PROFILE_PACK_BY_TITLE,
    emerald_stopped_legs = emerald_stopped_legs,
    EMH = EMH,
    GRASS_LOOP = GRASS_LOOP, GRASS_ORIGIN = GRASS_ORIGIN,
    return_to_grass_origin = return_to_grass_origin,
    hunt_encounter = hunt_encounter,
    -- test hooks (Codex review cx-378ce251): the in_battle polarity wrapper and the lab scene
    -- var address arithmetic, both independently checkable without an emulator.
    follow = play.follow,
    traced_follow = traced_follow,
    in_battle = play.in_battle,
    LAB_SCENE_VAR_OFFSET = LAB_SCENE_VAR_OFFSET,
    -- Whiteout signal and checkpoint-battle-state guard (C3-18, C3-29).
    check_whiteout = check_whiteout,
    save_battle_state_once = save_battle_state_once,
    -- test hooks (card gen3-P3-C3-21): the action-menu witness address/value pair and cursor
    -- constants, and the fight/settle/whiteout-check tail both route1_catch and route1_faint
    -- share.
    BATTLER_CTRL_ADDR = BATTLER_CTRL_ADDR,
    HANDLE_INPUT_CHOOSE_ACTION = HANDLE_INPUT_CHOOSE_ACTION,
    ACTION_CURSOR_ADDR = ACTION_CURSOR_ADDR,
    ACTION_FIGHT = ACTION_FIGHT, ACTION_BAG = ACTION_BAG,
    verify_fight_cursor = verify_fight_cursor,
    resolve_battle_and_check_whiteout = resolve_battle_and_check_whiteout,
    -- test hooks (card gen3-P3-C3-23): the bag pocket/cursor witness addresses+constants and
    -- the function that drives the bag with them, so a unit test can cross-check every address
    -- against pokefirered.sym and exercise the fail-loud paths without an emulator.
    GMAIN_CALLBACK2_ADDR = GMAIN_CALLBACK2_ADDR,
    CB2_BAG_MENU_RUN = CB2_BAG_MENU_RUN,
    TASK_BAG_MENU_HANDLE_INPUT = TASK_BAG_MENU_HANDLE_INPUT, TASK_ANIMATE_WIN0V = TASK_ANIMATE_WIN0V,
    TASKS_BASE = TASKS_BASE,
    BAG_MENU_STATE_ADDR = BAG_MENU_STATE_ADDR,
    BAG_POCKET_OFF = BAG_POCKET_OFF,
    BAG_ITEMS_ABOVE_OFF = BAG_ITEMS_ABOVE_OFF,
    BAG_CURSOR_POS_OFF = BAG_CURSOR_POS_OFF,
    BAG_POCKET_POKEBALLS = BAG_POCKET_POKEBALLS,
    SPECIAL_VAR_ITEM_ID_ADDR = SPECIAL_VAR_ITEM_ID_ADDR,
    ITEM_POKE_BALL = ITEM_POKE_BALL,
    SB1_POKEBALLS_POCKET_OFFSET = SB1_POKEBALLS_POCKET_OFFSET,
    throw_pokeball_from_bag = throw_pokeball_from_bag,
    -- test hooks (card gen3-P3-C3-26): the parcel-delivery oracle -- the false pass this fixes,
    -- the addresses/constants it reads, and the two functions that drive and check it.
    SB1_KEYITEMS_POCKET_OFFSET = SB1_KEYITEMS_POCKET_OFFSET,
    BAG_KEYITEMS_COUNT = BAG_KEYITEMS_COUNT,
    ITEM_OAKS_PARCEL = ITEM_OAKS_PARCEL,
    SB1_FLAGS_OFFSET = SB1_FLAGS_OFFSET,
    FLAG_SYS_POKEDEX_GET = FLAG_SYS_POKEDEX_GET,
    BAG_POKEBALLS_COUNT = BAG_POKEBALLS_COUNT,
    key_items_has_parcel = key_items_has_parcel,
    pokedex_get_flag = pokedex_get_flag,
    pokeballs_pocket_has_poke_ball = pokeballs_pocket_has_poke_ball,
    start_oak_delivery = start_oak_delivery,
    verify_parcel_delivered = verify_parcel_delivered,
    -- C3-29 fake-RAM falsifiers; these are read-only FR projections.
    SB1_LAST_HEAL_OFFSET = SB1_LAST_HEAL_OFFSET,
    whiteout_destination = whiteout_destination,
    verify_destination = verify_destination, DEST = DEST, warp_to = warp_to,
    recover_to_pallet_town = recover_to_pallet_town,
    recover_to_route1_grass = recover_to_route1_grass,
    verify_starter = verify_starter, verify_rival = verify_rival,
    verify_parcel_fetched = verify_parcel_fetched,
    PC = PC,
    owned_snapshot = owned_snapshot, verify_pc_transfer = verify_pc_transfer,
    pc_deposit_target = pc_deposit_target,
}
