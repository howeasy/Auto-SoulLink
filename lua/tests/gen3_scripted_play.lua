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
local profile_file = assert(io.open(WT .. "/data/games/gen3_frlg/profile.json", "rb"))
local profile = assert(JSON.decode(profile_file:read("a"))).titles.firered
profile_file:close()
assert(profile.admitted and not profile.derived.CFRU_NO_ENCRYPT
       and profile.derived.BOX_DATA_OFFSET == 4 and profile.derived.BOXES_PER_STORE == 14,
       "FR uncompressed box layout is not admitted")
local function read_bytes(addr, count)
    local bytes = {}
    for i = 1, count do bytes[i] = memory.read_u8(addr + i - 1) end
    return bytes
end
-- Defer host reads so loading the leg table needs no emulator globals.
local reader = Reads.new(profile, {
    read_u8 = function(a) return memory.read_u8(a) end,
    read_u32 = function(a) return memory.read_u32_le(a) end,
    read_bytes = read_bytes,
})

-- Plaintext (no decrypt needed) RAM observables pinned in lua/games/gen3_frlge.lua's `vanilla`
-- profile table, cited per use below.
local PARTY_COUNT_ADDR    = 0x02024029  -- gPlayerPartyCount (vanilla.PARTY_COUNT_ADDR)
local BATTLE_OUTCOME_ADDR = 0x02023E8A  -- vanilla.BATTLE_OUTCOME_ADDR; B_OUTCOME_CAUGHT == 7
                                         -- (pret include/constants/battle.h:82)
local BATTLE_RESULTS_ADDR = 0x03004F90  -- vanilla.BATTLE_RESULTS_ADDR; playerFaintCounter @ +0
local B_OUTCOME_CAUGHT = 7
local PARTY_BASE          = 0x02024284  -- gPlayerParty (vanilla.PARTY_BASE)
local MON_SIZE            = 100
local OFF_HP, OFF_MAXHP   = 0x56, 0x58  -- lua/tests/duo/duo_main.lua:26-27
local OFF_PID, OFF_OTID   = 0x00, 0x04  -- lua/tests/duo/duo_main.lua:23-24

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
local BATTLER_CTRL_ADDR = 0x03004FE0
local HANDLE_INPUT_CHOOSE_ACTION = 0x0802E439  -- 0x0802E438 | 1 (Thumb bit)
local ACTION_CURSOR_ADDR = 0x02023FF8
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
local OBJ_EVENTS_ADDR = 0x02036E38

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
-- 5.4 (7,4). Freeze this projection before advancing the battle/whiteout sequence.
local SB1_LAST_HEAL_OFFSET = 0x1C
local function whiteout_destination(cp)
    local sb1 = sb1_ptr(cp)
    if not sb1 then G.finish(false, "whiteout_heal_pointer: unreadable SaveBlock1"); return end
    local p = sb1 + SB1_LAST_HEAL_OFFSET
    local group, num = memory.read_u8(p), memory.read_u8(p + 1)
    local warp = memory.read_u8(p + 2)
    local x, y = memory.read_s16_le(p + 4), memory.read_s16_le(p + 6)
    if group == 3 and num == 0 and warp == 255 and x == 6 and y == 8 then
        return {group = 4, num = 0, x = 8, y = 5}
    elseif group == 3 and num == 1 and warp == 255 and x == 26 and y == 27 then
        return {group = 5, num = 4, x = 7, y = 4}
    end
    G.finish(false, string.format("whiteout_heal_unsupported: lastHealLocation %d.%d "
             .. "warp=%d (%d,%d)", group, num, warp, x, y))
end

local function verify_destination(cp, label, dest)
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
    end
    if not flag_set(cp, 0x258) or lab_scene_var(cp) ~= 4 then
        G.finish(false, "rival_terminal: FLAG_BEAT_RIVAL_IN_OAKS_LAB and lab scene 4 required")
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
local GMAIN_CALLBACK2_ADDR = 0x030030F4  -- gMain.callback2
local CB2_BAG_MENU_RUN = 0x08107EE1      -- CB2_BagMenuRun | 1 (Thumb bit)
local BAG_MENU_STATE_ADDR = 0x0203ACFC   -- gBagMenuState
local BAG_POCKET_OFF, BAG_ITEMS_ABOVE_OFF, BAG_CURSOR_POS_OFF = 0x06, 0x08, 0x0E
local BAG_POCKET_POKEBALLS = 2           -- OPEN_BAG_POKEBALLS
local SPECIAL_VAR_ITEM_ID_ADDR = 0x0203AD30  -- gSpecialVar_ItemId (pokefirered.sym:449)

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
local function bag_pocket() return memory.read_u16_le(BAG_MENU_STATE_ADDR + BAG_POCKET_OFF) end
--- The bag slot actually highlighted: itemsAbove[pocket] (scroll offset) + cursorPos[pocket]
--- (on-screen row) — item_menu.c:470 initializes the list with exactly this pair.
local function bag_cursor_slot(pocket)
    local above = memory.read_u16_le(BAG_MENU_STATE_ADDR + BAG_ITEMS_ABOVE_OFF + pocket * 2)
    local cursor = memory.read_u16_le(BAG_MENU_STATE_ADDR + BAG_CURSOR_POS_OFF + pocket * 2)
    return above + cursor
end
local function bag_pokeballs_item_id(cp, slot)
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
    -- (global.h:358 +0xF20; pokefirered.sym:810 gSaveBlock2Ptr=0300500C).
    local sb2 = memory.read_u32_le(0x0300500C)
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
local BAG_POKEBALLS_COUNT = 13
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
}

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
    -- HIGH nibble at +0x18 (pret include/global.fieldmap.h struct ObjectEvent). Introduced on
    -- run 8 to cross-check the live object against SaveBlock1.pos when the two disagreed.
    obj_pos = function(i)
        local base = OBJ_EVENTS_ADDR + (i or 0) * 0x24
        return memory.read_s16_le(base + 0x10) - 7, memory.read_s16_le(base + 0x12) - 7
    end,
    obj_facing = function(i)
        return memory.read_u8(OBJ_EVENTS_ADDR + (i or 0) * 0x24 + 0x18) >> 4
    end,
    party_count = function() return memory.read_u8(PARTY_COUNT_ADDR) end,
    -- Party IDENTITY, for playlib's keyed snapshot. PID:OTID is the same handle the duo
    -- harness follows a mon by (lua/tests/duo/duo_main.lua:86-98); it is plaintext (both sit
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

local play, check_whiteout
play = PL.bind(H, {
    paths          = PATHS,
    -- where the per-leg savestates below land
    state_dir      = os.getenv("SLINK_GEN3_PLAY_STATES_DIR") or "E:/Howard/Bizhawk/GBA/State",
    max_recoveries = 2,
    -- HOW THIS GAME FIGHTS a battle it did not choose. gActionSelectionCursor resets to 0
    -- (USE_MOVE) each battle (src/battle_controller_player.c), so A, A is a pinned
    -- FIGHT -> move-slot-1 selection; A keeps advancing the text afterwards. That is a Gen 3
    -- fact, so playlib refuses to assume it and takes it from here.
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
        local dest = whiteout_destination(cp)
        if not play.mash_a(budget or 1200, function() return not H.in_battle(cp) end) then
            return false
        end
        if not play.wait_scene_settled(cp, 1800) then return false end
        -- Raise the shared recovery signal here: playlib's static heal_map cannot
        -- express FR's lastHealLocation-dependent respawn projection.
        check_whiteout(cp, before_map, before_x, before_y, dest)
        return true
    end,
})

local function warp_to(cp, dir, budget, dest, label)
    local ok, why = play.enter_warp(cp, dir, budget)
    if not ok then G.finish(false, label .. ": warp_failed: " .. tostring(why)); return end
    -- enter_warp returns once the new map is on the field, which for an exterior door is
    -- BEFORE the scripted step off the door tile (field_fadetransition.c:357): FR run 25b read
    -- the Viridian mart door (36,19), not (36,20). Let the player come to rest on the
    -- destination first; a wrong landing still fails below, just after the budget.
    play.wait_at(cp, dest.x, dest.y, 120)
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
            end
        end
    end
    for key in pairs(after) do
        if key ~= except and not before[key] then
            G.finish(false, label .. ": unexpected_box_addition: " .. key)
        end
    end
end

local function verify_pc_transfer(label, op, before, after, target)
    local a, b = before.party, after.party
    if op == "withdraw" then
        if b.n ~= a.n + 1 or a.keys[target] or not b.keys[target]
           or not before.boxes[target] or after.boxes[target] then
            G.finish(false, label .. ": withdraw_target: selected PID must move box->party")
        end
        if after.mons[target].species ~= before.boxes[target].species then
            G.finish(false, label .. ": withdraw_species: selected record changed species")
        end
    else
        local gone = play.departed_key(a, b)
        if b.n ~= a.n - 1 or gone ~= target then
            G.finish(false, label .. ": pc_target: party slot 1 PID was not the single departure")
        end
        if op == "deposit" then
            local boxed = after.boxes[target]
            if not boxed or boxed.box ~= 0 or boxed.slot ~= 0
               or boxed.species ~= before.mons[target].species then
                G.finish(false, label .. ": deposit_readback: selected PID not in box 0 slot 0")
            end
        elseif op == "release" then
            if after.boxes[target] then
                G.finish(false, label .. ": release_deposited: selected PID is still boxed")
            end
        else
            G.finish(false, label .. ": unknown PC operation")
        end
    end
    local ok, why = play.survivors_intact(a, b, target)
    if not ok then G.finish(false, label .. ": " .. why) end
    boxes_unchanged(label, before.boxes, after.boxes, op ~= "release" and target or nil)
end

local function pc_deposit_target(before)
    if before.party.n < 2 then G.finish(false, "pc_target: deposit needs at least two mons") end
    -- This input route chooses box 0, then withdraws slot 0; bind that cursor to
    -- the selected identity BEFORE pressing buttons, including on resumed runs.
    if before.current_box ~= 0 then G.finish(false, "pc_box_cursor: current box must be 0") end
    for _, mon in pairs(before.boxes) do
        if mon.box == 0 and mon.slot == 0 then
            G.finish(false, "pc_box_slot: box 0 slot 0 must be empty before deposit")
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

--- Route either admitted respawn interior to Pallet Town (6,9), the shared resume origin.
--- The house's actual door landing is (6,8); the following verified step reaches (6,9).
local function recover_to_pallet_town(cp)
    local dest = whiteout_destination(cp)
    verify_destination(cp, "whiteout_recovery", dest)
    if dest.group == 4 and dest.num == 0 then
        play.follow(cp, "heal_house_to_door", "whiteout-recovery")
        warp_to(cp, "Down", 30, DEST.house_exit, "whiteout house exit")
        play.follow(cp, "house_exit_to_town_start", "whiteout-recovery")
    elseif dest.group == 5 and dest.num == 4 then
        play.follow(cp, "heal_center_to_door", "whiteout-recovery")
        warp_to(cp, "Down", 30, DEST.center_exit, "whiteout Center exit")
        play.follow(cp, "pokecenter_door_to_route1_edge", "whiteout-recovery")
        warp_to(cp, "Down", 30, DEST.route1_north, "whiteout Viridian->Route1")
        play.follow(cp, "route1_north_to_south_edge", "whiteout-recovery")
        warp_to(cp, "Down", 30, DEST.pallet_north, "whiteout Route1->Pallet")
        play.follow(cp, "pallet_north_to_town_start", "whiteout-recovery")
    else
        G.finish(false, "whiteout_recovery_unsupported: no route for this respawn map")
    end
    G.phase("recovered", "back outside at " .. play.at(cp))
end

--- route1_catch and route1_faint own their own battle (hunt_encounter calls play.step with
--- enc=false precisely so THIS file, not playlib, decides how to fight/throw) -- which means
--- playlib's own whiteout detector (P.handle_encounter's `error({whiteout=true,...},0)`,
--- playlib.lua:288-297) never sees the displacement, and P.run_leg's recover()/resume()
--- machinery only ever fires on that exact signal shape. A leg that opts out of playlib fighting
--- its battles must raise the same signal itself, or a whiteout here just runs off the end of
--- the leg looking like a plain loss. `before_map/x/y` is the position the caller captured right
--- as the battle started (same convention as handle_encounter's own `before`).
check_whiteout = function(cp, before_map, before_x, before_y, dest)
    local nmap = play.map(cp)
    local x, y = G.pos(cp)
    if nmap ~= before_map or x ~= before_x or y ~= before_y then
        dest = dest or whiteout_destination(cp)
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
        if action_menu_up() then return true end
        if not play.in_battle(cp) then return false end
        if i % 2 == 0 then joypad.set({ A = true }) else joypad.set({}) end
        G.advance()
    end
    joypad.set({})
    return false
end

--- Wait for the menu witness and require the cursor to be sitting on FIGHT(0) -- the default
--- every battle starts on (gActionSelectionCursor resets per battle,
--- src/battle_controller_player.c). route1_catch is about to toggle it to BAG(1) and
--- route1_faint is about to mash A on it; both need to know the press is landing on the menu
--- they think it is, not on the still-open "Wild X appeared!" intro text (FR run 19's bug).
--- A battle that ends before the menu ever comes up is not a failure -- there is nothing here
--- for either leg to press.
local function verify_fight_cursor(cp, label)
    if not play.in_battle(cp) then return end
    if not wait_for_action_menu(cp, 1200) then
        if play.in_battle(cp) then
            G.shot("stuck")
            G.finish(false, string.format(
                "%s: the action menu never came up (gBattlerControllerFuncs[0] never read "
                .. "HandleInputChooseAction) at %s", label, play.at(cp)))
        end
        return
    end
    -- The cursor is REMEMBERED across battles (PHYSICAL FR run 20: the menu opened on BAG(1)),
    -- so steer it to FIGHT with the pinned bit toggles of HandleInputChooseAction (pret
    -- src/battle_controller_player.c): Left clears bit0, Up clears bit1. Bounded, verified.
    for _ = 1, 4 do
        local c = action_cursor()
        if c == ACTION_FIGHT then return end
        if c % 2 == 1 then G.tap("Left", 3, 20) elseif c >= 2 then G.tap("Up", 3, 20) end
    end
    if action_cursor() ~= ACTION_FIGHT then
        G.shot("stuck")
        G.finish(false, string.format(
            "%s: could not steer the action cursor to FIGHT(0) (reads %d)", label, action_cursor()))
    end
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
    local dest = whiteout_destination(cp)
    local resolved = play.mash_a(mash_budget or 160, function() return not play.in_battle(cp) end)
    if resolved and not play.wait_scene_settled(cp, 1800) then
        G.finish(false, "whiteout_settle: post-battle scene never settled"); return false
    end
    check_whiteout(cp, before_map, before_x, before_y, dest)
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

-- ── the vanilla PC flow, from source ────────────────────────────────────────────────────────
-- docs/gen3/research/fr_pc_flow_and_pc_move_sites.md (Codex R9, cited to pret c75f352). The
-- shape is the same one the RR census proved PHYSICALLY
-- (docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt), and the spacing below is that
-- receipt's: ~120 frames between message presses, ~180 before a menu accepts input, ~240 for a
-- commit to settle. Presses are DATA, not a sweep.
--
--   A #1 interact            "{PLAYER} booted up the PC."
--   A #2 dismiss             "Which PC should be accessed?"  rows: 0 SOMEONE'S PC,
--                            1 {PLAYER}'s PC, 2 PROF. OAK's PC, 3 LOG OFF  (four rows once the
--                            Pokedex is obtained, which parcel_deliver did; cursor starts at 0)
--   A #3 choose row 0        "Accessed Someone's PC."
--   A #4 dismiss             "POKeMON Storage System opened."
--   A #5 dismiss             Task_PCMainMenu, selection row 0
--
-- Storage menu: 0 WITHDRAW, 1 DEPOSIT, 2 MOVE, 3 MOVE ITEMS, 4 SEE YA!
local PC_WAIT = { press = 120, menu = 180, commit = 240, cursor = 20 }

local function pc_press(btn, wait)
    G.tap(btn, 3, 13)
    G.idle(wait or PC_WAIT.press)
end

--- Five A presses from the field to the storage main menu.
local function open_storage_menu()
    for _ = 1, 5 do pc_press("A", PC_WAIT.press) end
    G.idle(PC_WAIT.menu - PC_WAIT.press)
end

--- THE PARTY COUNT IS A LIE WHILE THE PC IS OPEN. gPlayerPartyCount is recomputed on storage
--- exit, not at the transfer (the R9 note's completion row; PHYSICAL on RR, where the census
--- read party=3 throughout even after TryStorePartyMonInBox fired). So leaving the PC is part
--- of the operation, and every assertion in these legs is made on the field afterwards.
---
--- The leaving itself is playlib's leave_menu: on_field goes true while the PC's "See you
--- later!" textbox is still up, and stopping there shifts every press of the NEXT open by one
--- (PHYSICAL, RR r5b/r5c -- it turned a withdraw into a second deposit).
local function leave_storage(cp, label)
    play.leave_menu(cp, label, { flush = 5, flush_gap = 27, settle = 60 })
end

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
            local ox = memory.read_s16_le(0x02036E38 + 0x10) - 7
            local oy = memory.read_s16_le(0x02036E38 + 0x12) - 7
            local sx, sy = G.pos(cp)
            G.phase("pre-walk", string.format("obj0=(%d,%d) sb1=(%d,%d)", ox, oy, sx, sy))
            G.shot("prewalk")
        end
        play.follow(cp, "lab_oak_scene_end_to_ball", "starter")   -- asserts the real (6,4), not assumed
        do
            local ox = memory.read_s16_le(0x02036E38 + 0x10) - 7
            local oy = memory.read_s16_le(0x02036E38 + 0x12) - 7
            local sx, sy = G.pos(cp)
            G.phase("post-walk", string.format("obj0=(%d,%d) sb1=(%d,%d)", ox, oy, sx, sy))
            G.shot("postwalk")
        end
        do
            -- Face the ball and PROVE the facing: ObjectEvent.facingDirection is the low nibble
            -- at +0x18 (include/global.fieldmap.h: u8 movementDirection:4 / facingDirection:4);
            -- 1=down 2=up 3=left 4=right. Hold Up until it reads 2 (the ball object is solid,
            -- so Up can only turn, never step).
            local function facing() return memory.read_u8(0x02036E38 + 0x18) >> 4 end
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
        -- (scripts.inc:1140-1180) all run before script_context_status goes idle. A alone would
        -- risk landing on the nickname box's default YES and opening the naming screen this
        -- driver doesn't handle; B alone risks not dismissing a plain message (only A does).
        -- Alternating A then B on every tap is safe both ways: a plain `message`/`waitmessage`
        -- box only closes on A (B is a no-op there); the one Yes/No box left (nickname) treats
        -- B identically to NO (src/script_menu.c:901-905, MENU_B_PRESSED -> FALSE) without
        -- opening the keyboard -- so the exact frame the box appears doesn't need to be known.
        local idle = false
        for _ = 1, 40 do
            if G.pred_ok(cp, "script_context_status") then idle = true; break end
            G.tap("A", 3, 16)
            G.tap("B", 3, 16)
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
    recover = function(cp) recover_to_pallet_town(cp) end,
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
    recover = function(cp) recover_to_route1_grass(cp) end,
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
        "src/overworld.c SetWarpDestinationToLastHealLocation (a single-mon party can only white "
        .. "out BY fainting, so the whiteout itself is proof of the site this leg exercises)",
    },
    -- Same recovery as route1_catch: back to Pallet Town, then to the grass origin, grass_step
    -- reset. Needed here even though resume() below does no hunting of its own -- the NEXT leg
    -- (viridian_pc_deposit_withdraw) still expects to start from the grass, not the heal house.
    recover = function(cp) recover_to_route1_grass(cp) end,
    run = function(cp)
        local before = player_faints()
        local fainted = false
        for encounter = 1, 20 do
            if not hunt_encounter(cp, "route1_faint", 40) then
                G.shot("stuck")
                G.finish(false, string.format(
                    "route1_faint: 40 cycles of the pinned grass loop produced no wild "
                    .. "encounter (attempt %d, at %s)", encounter, play.at(cp)))
            end
            -- The same menu witness route1_catch uses (card gen3-P3-C3-21), so this leg's FIGHT
            -- choice is as deterministic as that one's BAG choice: confirm the cursor really is
            -- FIGHT(0) before mashing A on it, rather than assuming the intro text is gone.
            verify_fight_cursor(cp, "route1_faint")
            -- Keep attacking (RISK, see header) until this battle ends, then check the faint
            -- counter — a strong starter may just keep winning; bounded at 20 encounters.
            -- resolve_battle_and_check_whiteout settles the post-battle scene BEFORE reading the
            -- map (ROOT CAUSE, see that function's comment) -- without it, a faint's whiteout
            -- warp can land after this check has already passed, and the displacement then
            -- surfaces unnoticed inside the NEXT hunt_encounter's walk instead of here. A faint
            -- that also empties the party IS a whiteout: check_whiteout raises the same signal
            -- playlib's handle_encounter would have, so run_leg's recover()/resume() engages
            -- instead of this leg reporting a plain "never advanced" failure for a faint that in
            -- fact just happened.
            resolve_battle_and_check_whiteout(cp, 160)
            if player_faints() > before then fainted = true; break end
        end
        if not fainted then
            G.shot("stuck")
            G.finish(false, "route1_faint: playerFaintCounter never advanced after 20 encounters "
                         .. "(RISK: the starter may simply keep winning — see header)")
        end
        G.phase("fainted", "playerFaintCounter=" .. player_faints())
    end,
    -- run_leg only calls resume() after check_whiteout() raised above, so reaching here already
    -- proves the faint: a single-mon party whites out BY fainting, and there is no other way to
    -- land in resume(). gBattleResults (BATTLE_RESULTS_ADDR) is a scratch struct the engine
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
    run = function(cp)
        play.follow(cp, "route1_grass_to_north_edge", "viridian_pc_deposit_withdraw")
        warp_to(cp, "Up", 30, DEST.viridian_south, "viridian_pc Route1->Viridian")
        play.follow(cp, "route1_edge_to_pokecenter_door", "viridian_pc_deposit_withdraw")
        warp_to(cp, "Up", 30, DEST.center, "viridian_pc Center door")
        play.follow(cp, "pokecenter_entrance_to_pc", "viridian_pc_deposit_withdraw")
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
        open_storage_menu()
        pc_press("Down", PC_WAIT.cursor); pc_press("A", PC_WAIT.menu)    -- DEPOSIT
        pc_press("Down", PC_WAIT.cursor); pc_press("A", PC_WAIT.press)   -- party slot 1 -> popup
        pc_press("A", PC_WAIT.press)                                     -- STORE -> box chooser
        pc_press("A", PC_WAIT.commit)                                    -- box 0 -> TryStore...
        leave_storage(cp, "viridian_pc")

        local mid_world = owned_snapshot("viridian_pc deposited")
        local mid = mid_world.party
        verify_pc_transfer("viridian_pc deposit", "deposit", before_world, mid_world, target)
        if mid.n ~= before.n - 1 then
            G.shot("stuck")
            G.finish(false, string.format(
                "viridian_pc: after the deposit and leaving the PC the party count is %d, not "
                .. "%d. The pinned route is 5x A, Down+A, Down+A, A (STORE), A (box) -- the "
                .. "last A is the destination-box confirmation, without which nothing is stored",
                mid.n, before.n - 1))
        end
        local gone, why = play.departed_key(before, mid)
        if not gone then G.finish(false, "viridian_pc: deposit: " .. why) end
        G.phase("deposited", string.format("party %d -> %d, key %s left", before.n, mid.n, gone))

        -- WITHDRAW. Row 0 is already selected on a fresh menu, so A takes WITHDRAW; entry is in
        -- the BOX area at slot 0, A opens that record's popup, and A takes WITHDRAW (row 0).
        -- There is no destination confirmation on this path (R9 note).
        G.tap("Up", 2, 13)
        open_storage_menu()
        -- NO Up HERE. A re-opened PC starts the storage menu on ROW 0 (Withdraw), and an Up
        -- would WRAP the cursor to See Ya and close it (PHYSICAL, RR lane r5d,
        -- docs/gen3/probes/shadow_rr_play_r5d_pc_ops_2026-09-21.txt). The r5b/r5c
        -- "double deposit" that looked like a remembered cursor was really leave_storage
        -- returning early through the exit textbox; that is fixed above, not here.
        pc_press("A", PC_WAIT.menu)                                      -- WITHDRAW (row 0)
        pc_press("A", PC_WAIT.press)                                     -- box 0 slot 0 -> popup
        pc_press("A", PC_WAIT.commit)                                    -- WITHDRAW
        leave_storage(cp, "viridian_pc")

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

        open_storage_menu()
        pc_press("Down", PC_WAIT.cursor); pc_press("A", PC_WAIT.menu)    -- DEPOSIT (party area)
        pc_press("Down", PC_WAIT.cursor); pc_press("A", PC_WAIT.press)   -- party slot 1 -> popup
        for _ = 1, 3 do pc_press("Down", PC_WAIT.cursor) end             -- STORE -> ... -> RELEASE
        pc_press("A", PC_WAIT.press)                                     -- RELEASE -> Yes/No confirm
        -- THE CONFIRMATION IS PINNED. ShowYesNoWindow(1) starts the cursor on NO and does not
        -- wrap (pokemon_storage_system_tasks.c:2595-2599), so a bare A here declines silently --
        -- Up moves the cursor to YES first. Two more A's clear the trailing MSG_WAS_RELEASED and
        -- MSG_BYE_BYE messages (pokemon_storage_system_tasks.c:1307-1339).
        pc_press("Up", PC_WAIT.cursor)
        pc_press("A", PC_WAIT.press)                                     -- YES
        pc_press("A", PC_WAIT.press)                                     -- MSG_WAS_RELEASED
        pc_press("A", PC_WAIT.commit)                                    -- MSG_BYE_BYE
        leave_storage(cp, "pc_release")

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

-- ── run ──────────────────────────────────────────────────────────────────────────────────────

local function run()
    play.main(LEGS, {
        name   = "gen3_scripted_play",      -- patch/build/gen3_scripted_play_result.txt
        budget = 900000,
        -- A savestate per FINISHED leg (slink_fr_<leg>.State). The FR checkpoint negatives
        -- (lua/tests/probe_gen3_checkpoint.lua) need an in-battle-reachable state and a door
        -- state, and tests/fixtures/gen3/firered_town.sav has party=0 -- no wild battle is
        -- reachable from it, so this run is the only route there: the state at starter's
        -- leg-done is one A press from the rival battle, and leave_lab_for_parcel's is the
        -- lab door. A leg that FAILED saves nothing; a state written mid-failure is a trap.
        save_states = "slink_fr_",
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
    GRASS_LOOP = GRASS_LOOP, GRASS_ORIGIN = GRASS_ORIGIN,
    -- test hooks (Codex review cx-378ce251): the in_battle polarity wrapper and the lab scene
    -- var address arithmetic, both independently checkable without an emulator.
    follow = play.follow,
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
    owned_snapshot = owned_snapshot, verify_pc_transfer = verify_pc_transfer,
    pc_deposit_target = pc_deposit_target,
}
