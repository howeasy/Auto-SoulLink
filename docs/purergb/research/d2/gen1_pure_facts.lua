-- gen1_pure_facts.lua — per-foundation constants for the pureRGB ROM hack, derived from the
-- pureRGB source tree (P/ = C:/Users/howar/AppData/Local/Temp/claude/E--Google-Drive-SLink--
-- claude-worktrees-recursing-hopper-86c382/27f97123-cfa0-473c-aed8-f288963eedeb/scratchpad/
-- purergb/, commit 7e7a4653) so the shared W/lua/tests/*.lua drivers could load this instead of
-- their vanilla R/B literals. Every field is commented with its citation. Method and full
-- reasoning: see FACTS.md in this same directory.
--
-- STATUS SUMMARY (see FACTS.md for the complete literal-by-literal table):
--   * Map ids, event-flag ordinals (as raw numbers), item ids, Mart stock, OaksLab/PalletTown/
--     ViridianMart script-index TABLES, starter level-1/level-5 movesets, and most menu geometry
--     (battle menu, PC, YES/NO, Mart list) are SAME as vanilla pokered.
--   * TWO real, verified MECHANISM differences explain the two reported live failures:
--       1. EVENT_OAK_GOT_PARCEL no longer exists in pureRGB (event_constants.asm:50: "used to be
--          EVENT_OAK_GOT_PARCEL but it's no different from EVENT_GOT_POKEDEX"). Nothing in
--          scripts/OaksLab.asm or scripts/ViridianMart.asm ever sets or checks that bit anymore;
--          EVENT_GOT_POKEDEX (bit 37, unchanged ordinal) is SetEvent'd instead, inside
--          OaksLabOakGivesPokedexScript (script 16), before the script advances to 17 then to
--          NOOP (18). A driver that reads bit 56 for "oak_got_parcel" always reads 0/false in
--          pureRGB, so it falls off scripts 15-17 into NOOP(18) still believing the delivery
--          isn't done -> "parcel removed outside Oak delivery script".
--       2. DrawStartMenu's wMaxMenuItem is ONE LESS than vanilla's convention: pureRGB stores the
--          menu's last 0-based row index (5 without Pokedex / 6 with), not the row COUNT (6 / 7)
--          vanilla stores. The SAVE row's own 0-based index is UNCHANGED (3 without Pokedex, 4
--          with), so the driver's working formula becomes a single constant either way:
--          menu_max == save_index + 2 (pureRGB) vs. save_index + 3 (vanilla assumption).
--   * The already-fixed rival opponent id (225 -> 221) is explained exactly: OPP_ID_OFFSET
--     dropped from vanilla's 200 to pureRGB's 197, AND RIVAL1's trainer-class ordinal dropped one
--     slot ($19 -> $18); 197 + 24 = 221.

local F = {}

-- ── Map ids: pureRGB/constants/map_constants.asm — every id checked is SAME as vanilla ────────
-- (map_const emits the numeric id as a trailing comment in this file; verified by reading it).
F.MAP = {
    PALLET_TOWN               = 0x00, -- map_constants.asm:19  "map_const PALLET_TOWN, 10, 9 ; $00"
    VIRIDIAN_CITY             = 0x01, -- map_constants.asm:20  "; $01"
    ROUTE_22                  = 0x21, -- map_constants.asm:54  "; $21"
    OAKS_LAB                  = 0x28, -- map_constants.asm:62  "; $28"
    VIRIDIAN_POKECENTER       = 0x29, -- map_constants.asm:63  "; $29"
    VIRIDIAN_MART             = 0x2A, -- map_constants.asm:64  "; $2A"
    VIRIDIAN_FOREST_SOUTH_GATE= 0x32, -- map_constants.asm:72  "; $32"
    VIRIDIAN_FOREST           = 0x33, -- map_constants.asm:73  "; $33"
    -- ROUTE_1 / ROUTE_2 were not visible in the header block this pass grepped; the drivers'
    -- own map=0x0C / 0x0D literals were never contradicted by anything read in P/, so treat as
    -- SAME pending a direct grep of map_constants.asm's ROUTE_1/ROUTE_2 lines. UNVERIFIED (low
    -- risk: settle with `grep -n "ROUTE_1 \|ROUTE_2 " constants/map_constants.asm`).
    ROUTE_1                   = 0x0C, -- UNVERIFIED (see note above); vanilla value, uncontradicted
    ROUTE_2                   = 0x0D, -- UNVERIFIED (see note above); vanilla value, uncontradicted
}

-- ── Item ids: pureRGB/constants/item_constants.asm — SAME as vanilla ──────────────────────────
F.ITEM = {
    POKE_BALL   = 0x04, -- item_constants.asm:13 "const POKE_BALL     ; $04"
    ANTIDOTE    = 0x0B, -- item_constants.asm:20 "const ANTIDOTE      ; $0B"
    BURN_HEAL   = 0x0C, -- item_constants.asm:21 "const BURN_HEAL     ; $0C"
    PARLYZ_HEAL = 0x0F, -- item_constants.asm:24 "const PARLYZ_HEAL   ; $0F"
    OAKS_PARCEL = 0x46, -- item_constants.asm:79 "const OAKS_PARCEL   ; $46"
}

-- ── Event-flag ordinals (bit index from const_def's anchor at EVENT_FOLLOWED_OAK_INTO_LAB=0) ──
-- Simulated the const_def/const/const_skip/const_next macro chain in
-- pureRGB/constants/event_constants.asm exactly (macros/const.asm:1-40) rather than counting
-- lines; const_skip/const_next entries are NOT separately named constants and must not be
-- counted as one.
F.EVENT = {
    GOT_POKEDEX     = 37, -- event_constants.asm:37 "const EVENT_GOT_POKEDEX" -- SAME ordinal as vanilla
    GOT_OAKS_PARCEL = 57, -- event_constants.asm:51 "const EVENT_GOT_OAKS_PARCEL" -- SAME ordinal as vanilla
    -- MECHANISM CHANGE, not a value change: vanilla's EVENT_OAK_GOT_PARCEL (bit 56, the "Oak has
    -- received the parcel" flag the parcel driver polls as `oak_got_parcel`) DOES NOT EXIST in
    -- pureRGB. Its old bit slot is now a bare `const_skip` (event_constants.asm:50: "used to be
    -- EVENT_OAK_GOT_PARCEL but it's no different from EVENT_GOT_POKEDEX") and is never SetEvent'd
    -- or CheckEvent'd anywhere in scripts/OaksLab.asm or scripts/ViridianMart.asm (grep for
    -- EVENT_OAK_GOT_PARCEL across scripts/ and data/ returns nothing). Reading that bit will
    -- always read 0. The correct substitute is EVENT_GOT_POKEDEX: it is SetEvent'd inside
    -- OaksLabOakGivesPokedexScript (scripts/OaksLab.asm, the "SetEvent EVENT_GOT_POKEDEX" line
    -- immediately before `ld a, SCRIPT_OAKSLAB_RIVAL_LEAVES_WITH_POKEDEX`), i.e. partway through
    -- script 16, strictly BEFORE the script counter reaches 17 then NOOP (18). So a driver must
    -- read `oak_got_parcel` as EVENT_GOT_POKEDEX (bit 37) on pureRGB, not a phantom bit 56.
    OAK_GOT_PARCEL_EXISTS = false,       -- mechanism flag for callers: no such event on pureRGB
    OAK_GOT_PARCEL_SUBSTITUTE = "GOT_POKEDEX", -- read F.EVENT.GOT_POKEDEX (bit 37) instead
}

-- ── OaksLab / PalletTown / ViridianMart script-index TABLES: SAME as vanilla ──────────────────
-- The dw_const macro (macros/const.asm:47-50, identical to pret's) auto-numbers each script
-- pointer 0,1,2,... in table order, exactly like pret pokered. Read scripts/OaksLab.asm:6-26,
-- scripts/PalletTown.asm:9-15 and scripts/ViridianMart.asm:5-10 directly: same script NAMES in
-- the same ORDER as vanilla pokered, so the numeric indices are identical.
F.SCRIPT_OAKSLAB = {
    DEFAULT = 0, OAK_ENTERS_LAB = 1, TOGGLE_OAKS = 2, PLAYER_ENTERS_LAB = 3, FOLLOWED_OAK = 4,
    OAK_CHOOSE_MON_SPEECH = 5, PLAYER_DONT_GO_AWAY = 6, PLAYER_FORCED_TO_WALK_BACK = 7,
    CHOSE_STARTER = 8, RIVAL_CHOOSES_STARTER = 9, RIVAL_CHALLENGES_PLAYER = 10,
    RIVAL_START_BATTLE = 11, RIVAL_END_BATTLE = 12, RIVAL_STARTS_EXIT = 13,
    PLAYER_WATCH_RIVAL_EXIT = 14,
    RIVAL_ARRIVES_AT_OAKS_REQUEST = 15, -- delivery[1]; scripts/OaksLab.asm:23, entered at :921-923
    OAK_GIVES_POKEDEX             = 16, -- delivery[2]; scripts/OaksLab.asm:24 (SetEvent GOT_POKEDEX fires here, see F.EVENT)
    RIVAL_LEAVES_WITH_POKEDEX     = 17, -- delivery[3]; scripts/OaksLab.asm:25
    NOOP                          = 18, -- scripts/OaksLab.asm:26 "dw_const DoRet, SCRIPT_OAKSLAB_NOOP"
}
F.SCRIPT_PALLETTOWN = {
    DEFAULT = 0, OAK_HEY_WAIT = 1, OAK_WALKS_TO_PLAYER = 2, OAK_NOT_SAFE_COME_WITH_ME = 3,
    PLAYER_FOLLOWS_OAK = 4, DAISY = 5, NOOP = 6,
} -- scripts/PalletTown.asm:9-15, same names/order as vanilla; driver only reads 0-4.
F.SCRIPT_VIRIDIANMART = {
    DEFAULT = 0, OAKS_PARCEL = 1, NOOP = 2,
} -- scripts/ViridianMart.asm:6-10; the parcel driver's `mart_script==2` check is SAME.

-- Oak-delivery script index mapping the parcel driver needs (delivery[] + noop), same shape as
-- W/lua/tests/gen1_rb_parcel_inputs.lua:13-17's LAB table. IDENTICAL to vanilla in pureRGB.
F.LAB_DELIVERY = { delivery = {15, 16, 17}, noop = 18 }

-- ── Viridian Mart stock: pureRGB/data/items/marts/viridian.asm — SAME as vanilla ─────────────
-- "script_mart POKE_BALL, ANTIDOTE, PARLYZ_HEAL, BURN_HEAL" (viridian.asm:1-5), same order.
-- The parcel route passed live through the whole purchase flow, consistent with this.
F.MART_VIRIDIAN = { F.ITEM.POKE_BALL, F.ITEM.ANTIDOTE, F.ITEM.PARLYZ_HEAL, F.ITEM.BURN_HEAL }

-- ── Rival: already-fixed opponent id, explained exactly ───────────────────────────────────────
-- constants/trainer_constants.asm:1 "DEF OPP_ID_OFFSET EQU 197" (vanilla: 200)
-- constants/trainer_constants.asm:40 "trainer_const RIVAL1  ; $18" (vanilla: $19 = 25)
-- OPP_RIVAL1 = OPP_ID_OFFSET + RIVAL1 = 197 + 24 = 221 (vanilla: 200 + 25 = 225). Matches the
-- constant the harness already patched (225 -> 221) exactly, from two independent shifts: one
-- fewer trainer-class id before RIVAL1 in the class list, and OPP_ID_OFFSET itself 3 lower.
F.OPP_RIVAL1 = 221

-- ── Starter movesets: level 1 == level 5 (first new move is level 7+ for all three) ──────────
-- data/pokemon/base_stats/{bulbasaur,charmander,squirtle}.asm:13 (level-1 learnset) and
-- data/pokemon/evos_moves.asm ({Bulbasaur,Charmander,Squirtle}EvosMoves: first learned move is
-- level 7 Leech Seed / level 7 Leer / level 8 Bubble respectively), so nothing changes moves
-- between level 1 and level 5 -- IDENTICAL to vanilla in content and order.
F.STARTER_MOVES_LV5 = {
    BULBASAUR  = {"TACKLE", "GROWL"},      -- base_stats/bulbasaur.asm:13
    CHARMANDER = {"SCRATCH", "GROWL"},     -- base_stats/charmander.asm:13 (GROWL in slot 2, as the lab driver assumes)
    SQUIRTLE   = {"TACKLE", "TAIL_WHIP"},  -- base_stats/squirtle.asm:13 (no Growl for Squirtle, SAME as vanilla)
}
F.GROWL = 0x2D -- constants/move_constants.asm (simulated const chain) -- SAME as vanilla

-- ── START menu geometry: THE row-count mechanism difference ──────────────────────────────────
-- engine/menus/draw_start_menu.asm:9-10 wTopMenuItemY=2, wTopMenuItemX=11 -- SAME as vanilla.
-- Row text (draw_start_menu.asm:64-76): StartMenuWithPokedexText "#DEX" falls through into
-- StartMenuWithoutPokedexText's "#MON"/"ITEM"/(blank name row)/"SAVE"/"OPTION"/"EXIT@": SAME 6
-- rows without Pokedex (indices 0..5: POKEMON,ITEM,NAME,SAVE,OPTION,EXIT) / 7 with (0..6, Pokedex
-- prepended) as vanilla, and the SAVE row is at the SAME 0-based index either way:
F.START_MENU_SAVE_INDEX = { without_pokedex = 3, with_pokedex = 4 } -- unchanged from vanilla
-- BUT draw_start_menu.asm:26-34 stores the LAST 0-based row index into wMaxMenuItem, not the row
-- COUNT vanilla stores (vanilla: home/start_menu.asm-cited 6/7 = count; pureRGB: 5/6 = count-1):
--   ld a, 5                          ; :26  (5 = last index of 6 rows, NOT 6)
--   ...jr z, .storeMenuItemCount     ; branch on EVENT_GOT_POKEDEX
--   inc a                            ; :?   (5 -> 6 when Pokedex is owned; still count-1, not +1)
--   ld [wMaxMenuItem], a             ; :34
-- home/start_menu.asm:21 confirms the SAME "Pokedex is a prepended row" indexing convention
-- ("inc a ; adjust position to account for missing pokedex menu item").
-- Net effect for the SAVE driver: wMaxMenuItem - start_menu_save_index is a CONSTANT, but a
-- DIFFERENT constant than vanilla assumed:
F.START_MENU_MAX_MINUS_SAVE = 2 -- pureRGB: menu_max == save_index + 2 (BOTH with and without Pokedex)
-- (vanilla/W-driver assumption was save_index + 3, or +4 with the SLink companion-cartridge
-- SLINK row appended -- that companion row does not exist on a standalone pureRGB ROM, so only
-- the +2 case applies here.) This is the exact, complete explanation of the live failure at
-- W/lua/tests/gen1_rb_save_inputs.lua:62 ("START menu row count disagrees with the SAVE row"):
-- the assertion demands menu_max==save+3, pureRGB actually presents menu_max==save+2.

-- ── SAVE prompt / YES-NO geometry: SAME as vanilla, plus a real timing change ────────────────
-- engine/menus/save.asm:178 "ld a, TWO_OPTION_MENU" ($14, constants/menu_constants.asm:25 "; $14")
-- -- SAME as vanilla. save.asm:150-153 "hlcoord 0, 7 / lb bc, 8, 1" -> wTopMenuItemY=8,
-- wTopMenuItemX=1, wMaxMenuItem=1, same as the vanilla-derived driver expectation.
-- home/yes_no.asm:6 "hlcoord 14, 7" -- SAME as vanilla's YES/NO box position.
F.SAVE_PROMPT = { text_box = 0x14, menu_y = 8, menu_x = 1, menu_max = 1, yes_index = 0 }
-- MECHANISM CHANGE (does not affect correctness, only timing): pureRGB removed the "Now saving..."
-- message and cut the artificial save delay to 1/3 of vanilla's (engine/menus/save.asm, comments
-- "PureRGBnote: CHANGED: remove 'now saving' text because saving is near-instant now." and
-- "PureRGBnote: CHANGED: reduce artificial save delay to 1/3 of original." before `ld c, 10 / jp
-- DelayFrames`). The save driver's 1800-frame `self.closing` bound comfortably covers this either
-- way; flagged only because it changes what a frame-by-frame trace around SAVE looks like.
F.SAVE_DELAY_FRAMES = 10 -- engine/menus/save.asm SaveMenu:.save "ld c, 10 ; ... jp DelayFrames"

-- ── Battle menu geometry: SAME as vanilla ─────────────────────────────────────────────────────
-- constants/menu_constants.asm:16 "const BATTLE_MENU_TEMPLATE ; $0b" -- SAME.
-- data/text_boxes.asm "text_box_text BATTLE_MENU_TEMPLATE, 8, 12, 19, 17, BattleMenuText, 10, 14"
-- -- box position/size and cursor Y=14 identical to what gen1_battle_driver.lua's own header
-- cites for vanilla core.asm (wTopMenuItemY=$e=14); the FIGHT/PKMN column X (9 or 15) is set by
-- BattleMenuText's own logic, not visible in this static table, but the lab route's rival battle
-- (FIGHT -> Growl) already ran this exact menu successfully live, which is a live positive
-- control for the whole M.BATTLE_MENU / M.MOVE_MENU geometry in gen1_battle_driver.lua.
F.BATTLE_MENU_TEMPLATE = 0x0B

-- ── PC (Bill's PC) menu geometry: SAME as vanilla, same line numbers even ────────────────────
-- engine/pokemon/bills_pc.asm:77,79 set wTopMenuItemY/X directly -- SAME two line numbers the
-- vanilla-derived gen1_rb_pc_inputs.lua header already cites (bills_pc.asm:77-80). Row hlcoord
-- values 2,2 / 2,4 / 2,6 / 2,8 / 2,10 (bills_pc.asm:32,36,40,49(main list continuing),57,60,64)
-- decode to tilemap offsets 42/82/122/162/202 -- IDENTICAL to gen1_rb_pc_inputs.lua's M.OFF table.
-- Deposit/withdraw sub-box hlcoord 11,12 (bills_pc.asm:474) -> offset 251, SAME as vanilla.
F.PC_OFFSETS = { main = 42, withdraw = 42, deposit = 82, release = 122, changebox = 162, seeya = 202,
                 sub_action = 251 }
-- Note: pureRGB moved "change box" out of save.asm into its own engine/menus/change_box_menu.asm
-- (a refactor to support the new "hold SELECT on SAVE to change box from the START menu"
-- feature, engine/menus/draw_start_menu.asm:8 comment + home/start_menu.asm's `.selectPressed`
-- handler). The geometry itself was not independently re-verified against the moved file this
-- pass -- UNVERIFIED (mechanism location changed; settle with one live frame of the CHANGE BOX
-- screen's wTopMenuItemY/X/wMaxMenuItem, or a source read of change_box_menu.asm).

return F
