--[[
  lua/tests/test_gen1_evolution_gate.lua — headless: does a REAL Gen 1 evolution produce the
  key_change the server needs, and nothing else?

  WHAT IS UNTESTED WITHOUT THIS. A Gen 1 mon key is DVs:OTID:SPECIES (memory_gb.monKey), so
  every evolution rewrites the key. The client is supposed to notice, keep the pair, and emit
  `key_change` (gen1_rby_client.lua:808 on_evolution) — but ONLY when the first 9 chars
  "DDDD:TTTT" are unchanged (gen1_rby_client.lua:865). If a single frame of the evolution
  shows a different invariant, diff_party falls through to the capture branch four lines
  later and reports a brand-new mon: the pair silently unlinks and a phantom capture appears.
  diff_party() runs EVERY frame (gen1_rby_client.lua:1227 — there is no isInOverworld gate),
  so "no intermediate key, ever" is a real requirement and only a cartridge can prove it.

  WHY A STONE, NOT A LEVEL-UP. Levelling needs EXP, which needs battles, which need
  encounter RNG. A stone is deterministic, needs no battle at all, and — decisively —
  CANNOT BE CANCELLED: Evolution_CheckForCancel (pokered engine/movie/evolution.asm:142)
  honours B only when wForceEvolution is clear, and ItemUseEvoStone sets it TRUE
  (pokered engine/items/item_effects.asm:777). A stray B press cannot abort this gate.

  WHY CLEFAIRY + MOON STONE specifically:
    * pokered data/pokemon/evos_moves.asm:243  `db EVOLVE_ITEM, MOON_STONE, 1, CLEFABLE`
      — level requirement 1, so the fixture's level-5 mon always qualifies.
    * pokered data/pokemon/evos_moves.asm:1649 ClefableEvosMoves has an EMPTY learnset
      (`db 0`), so LearnMoveFromLevelUp (evos_moves.asm:211) finds nothing and no
      "learn a move?" prompt interrupts the sequence.
    * All three evolution texts end with `done`, not `prompt` (pokered
      data/text/text_3.asm:35/40/54) — the whole animation runs UNATTENDED. No button
      mashing, so nothing this gate presses can perturb what it is measuring.
    * Identical in Yellow: same item id, same species ids, same evo entry, same empty
      learnset (pokeyellow data/pokemon/evos_moves.asm:243 and :1673). Yellow's extra
      IsThisPartyMonStarterPikachu refusal (pokeyellow engine/items/item_effects.asm:812)
      is why PIKACHU + THUNDER_STONE would have been the wrong choice — Yellow's starter
      Pikachu REFUSES to evolve, and the gate would pass on Red and fail on Yellow.

  IDS (pokered/pokeyellow constants, identical in both):
    MOON_STONE $0A (item_constants.asm:19)
    CLEFAIRY   $04 / CLEFABLE $8E (pokemon_constants.asm:13 / :151) — INTERNAL indices,
    which is what the key carries; NatDex 35 -> 36 is what the server stores.

  ADDRESSES. Everything read here is either a profile field, an address red and yellow
  agree on (the 0xCCxx menu block), or an offset from M.MAP_ID_ADDR — which is wCurMap, and
  all four of the evolution-related bytes below live in the same block Yellow shifts by the
  same -1, so one anchor covers both variants. From data/pret_syms.json:
                              pokered   pokeyellow   delta from wCurMap
    wCurMap                   0xD35E    0xD35D       (anchor)
    wEventFlags               0xD747    0xD746       +0x3E9
    wEvolutionOccurred        0xD121    0xD120       -0x23D
    wPartyMenuTypeOrMessageID 0xD07D    0xD07C       -0x2E1
    wEvoStoneItemID           0xD156    0xD155       -0x208
  Unshifted (red == yellow, same file): wCurrentMenuItem 0xCC26, wMaxMenuItem 0xCC28,
  wTopMenuItemY 0xCC24, wTopMenuItemX 0xCC25, wPartyAndBillsPCSavedMenuItem 0xCC2B,
  wBagSavedMenuItem 0xCC2C, wListScrollOffset 0xCC36, wForceEvolution 0xCCD4.

  Runs on tests/fixtures/gen1/<rom>_town.SaveRAM (one level-5 Squirtle, 20/20 HP, 5 balls).
  Result file: patch/build/test_gen1_evolution_gate_result.txt
--]]

local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("test_gen1_evolution_gate")
local M = t.M
local fmt = string.format

local CLEFAIRY, CLEFABLE, MOON_STONE = 0x04, 0x8E, 0x0A
local TERMINATOR = 0xFF

-- red_ap relocates this block by its own amounts; the fixtures are vanilla anyway.
if t.variant ~= "red" and t.variant ~= "blue" and t.variant ~= "yellow" then
    t.check("gate runs on a vanilla cartridge", false, "variant=" .. tostring(t.variant))
    t.finish("wrong variant")
end

local ANCHOR              = M.MAP_ID_ADDR
local EVENT_FLAGS         = ANCHOR + 0x3E9
local EVOLUTION_OCCURRED  = ANCHOR - 0x23D
local PARTY_MENU_TYPE     = ANCHOR - 0x2E1
local EVO_STONE_ITEM_ID   = ANCHOR - 0x208
local CUR_MENU, MAX_MENU  = 0xCC26, 0xCC28
local TOP_MENU_Y          = 0xCC24
local TOP_MENU_X          = 0xCC25
local PARTY_SAVED_MENU    = 0xCC2B
local BAG_SAVED_MENU      = 0xCC2C
local LIST_SCROLL         = 0xCC36
local FORCE_EVOLUTION     = 0xCCD4

local r8, w8 = M.read_u8, M.write_u8
local function struct_species() return r8(M.PARTY_BASE_ADDR + M.SPECIES_OFFSET) end
local function list_species()   return r8(M.PARTY_SPECIES_ADDR) end
local function menu_open()      return r8(M.FONT_LOADED_ADDR) % 2 == 1 end

-- ── Frame-by-frame key sampler ───────────────────────────────────────────────
-- THE point of the gate. Every distinct key slot 0 ever shows is recorded with the frame it
-- first appeared, because "old then new, nothing between" is exactly what the client's
-- evolution branch requires and exactly what a torn read would break.
local seen, order = {}, {}
local function sample()
    local mon = M.readPartySlot(0)
    local k = mon and mon.key or "<nil>"
    if not seen[k] then seen[k] = t.frame; order[#order + 1] = k end
    return mon
end

local function run(frames, btn, stop)
    local b = btn and {[btn] = true} or nil
    for _ = 1, frames do
        sample()
        if stop and stop() then return true end
        t.step(b)
    end
    sample()
    return stop and stop() or false
end

local function fail_here(what, detail)
    client.screenshot(t.ROOT .. "/patch/build/test_gen1_evolution_gate_" .. what .. ".png")
    t.check(what, false, detail)
    t.finish("staging failed at " .. what)
end

-- ── Stage the preconditions ──────────────────────────────────────────────────
-- The MECHANISM under test is the cartridge's own evolution routine, so the ROM code is
-- driven for real through the real menus. Only the two preconditions the town fixture
-- happens not to have — a stone-evolving mon and a stone — are written directly. That is
-- the same latitude tools/gen1_playthrough.py already takes to put Poké Balls in the bag.
t.check("fixture starts with exactly one party mon", M.getPartyCount() == 1,
        fmt("got %d", M.getPartyCount()))

w8(M.PARTY_BASE_ADDR + M.SPECIES_OFFSET, CLEFAIRY)
w8(M.PARTY_SPECIES_ADDR, CLEFAIRY)
w8(M.PARTY_SPECIES_ADDR + 1, TERMINATOR)
t.check("staged slot 0 as CLEFAIRY in BOTH the struct and the species list",
        struct_species() == CLEFAIRY and list_species() == CLEFAIRY,
        fmt("struct=0x%02X list=0x%02X", struct_species(), list_species()))

-- One item, so the bag list cursor cannot land on the wrong row.
w8(M.BAG_COUNT_ADDR, 1)
w8(M.BAG_ITEMS_ADDR + 0, MOON_STONE)
w8(M.BAG_ITEMS_ADDR + 1, 1)
w8(M.BAG_ITEMS_ADDR + 2, TERMINATOR)
-- Saved cursors persist across menu visits (StartMenu_Item restores wBagSavedMenuItem;
-- PartyMenuInit restores wPartyAndBillsPCSavedMenuItem). Zero them so "press A" means
-- "the first row" on every ROM and every fixture rebuild.
w8(BAG_SAVED_MENU, 0)
w8(PARTY_SAVED_MENU, 0)
w8(LIST_SCROLL, 0)

local before = M.readPartySlot(0)
if not before then fail_here("slot 0 decodes before the evolution", "readPartySlot returned nil") end
local before_key = before.key
local invariant  = before_key:sub(1, 9)
local nick_before = M.readPartyNickname(0)
t.log(fmt("[evo] before: key=%s level=%d hp=%d/%d nick=%q",
          before_key, before.level, before.hp, before.maxHP, nick_before))
t.check("the staged key ends in the CLEFAIRY index", before_key:sub(11, 12) == "04",
        fmt("key=%s", before_key))

-- ── ITEM's index in the START menu ───────────────────────────────────────────
-- pokered home/start_menu.asm:62-72 dispatches on wCurrentMenuItem, adding 1 first when
-- EVENT_GOT_POKEDEX is clear: ITEM is dispatch id 2, so the CURSOR index is 2 with the dex
-- and 1 without. tools/gen1_playthrough.py:416 deliberately leaves that flag clear, which
-- is why the fixture's menu is POKeMON(0) ITEM(1) <NAME>(2) SAVE(3) OPTION(4) EXIT(5).
-- Read it rather than trusting the comment — a fixture rebuild that set the flag would
-- otherwise silently open the Pokemon menu and this gate would time out looking like a
-- client bug. Bit 37 of wEventFlags = byte 4, mask 0x20 (pret constants/event_constants.asm).
local has_dex = (r8(EVENT_FLAGS + 4) // 0x20) % 2 == 1
local ITEM_INDEX = has_dex and 2 or 1
t.log(fmt("[evo] EVENT_GOT_POKEDEX=%s -> ITEM is cursor index %d",
          tostring(has_dex), ITEM_INDEX))

-- ── Drive the real menus ─────────────────────────────────────────────────────
-- Every press is HELD; a 1-frame tap does not register (gatelib's boot loop and
-- gen1_playthrough.lua:456 both learned this the hard way). One Start press is not reliably
-- picked up either, so retry until the game confirms a menu is up.
for _ = 1, 12 do
    if menu_open() then break end
    t.hold("Start", 10, menu_open)
    run(24, nil, menu_open)
end
if not menu_open() then fail_here("START menu opened", fmt("frame %d", t.frame)) end

for _ = 1, 12 do
    if r8(CUR_MENU) == ITEM_INDEX then break end
    -- Re-check INSIDE the loop: if a press closed the menu, the remaining Down holds stop
    -- being menu navigation and become overworld movement, which walks the player off the
    -- fixture's tile and makes every later check fail for the wrong reason.
    if not menu_open() then break end
    t.hold("Down", 6, nil)
    run(10, nil, function() return r8(CUR_MENU) == ITEM_INDEX end)
end
if r8(CUR_MENU) ~= ITEM_INDEX then
    fail_here("ITEM selected in the START menu",
              fmt("cur=%d want=%d max=%d", r8(CUR_MENU), ITEM_INDEX, r8(MAX_MENU)))
end

-- A opens the bag list. The single staged item sits on row 0 with the cursor already there.
t.hold("A", 6, nil)
run(60, nil, nil)

-- A on the item raises the USE/TOSS box. Its cursor block is set to an unmistakable
-- position (pokered engine/menus/start_sub_menus.asm:355-363: topY 11, topX 14, cur 0,
-- max 1), which is a far better "am I there yet" signal than counting frames.
local function on_use_toss()
    return r8(TOP_MENU_Y) == 11 and r8(TOP_MENU_X) == 14 and r8(MAX_MENU) == 1
end
for _ = 1, 8 do
    if on_use_toss() then break end
    t.hold("A", 6, nil)
    run(30, nil, on_use_toss)
end
if not on_use_toss() then
    fail_here("USE/TOSS box appeared",
              fmt("topY=%d topX=%d max=%d cur=%d", r8(TOP_MENU_Y), r8(TOP_MENU_X),
                  r8(MAX_MENU), r8(CUR_MENU)))
end
t.check("USE is preselected (cursor 0)", r8(CUR_MENU) == 0, fmt("cur=%d", r8(CUR_MENU)))

-- A picks USE. MOON_STONE is in UsableItems_PartyMenu (pokered data/items/use_party.asm:3),
-- so control reaches ItemUseEvoStone, which stashes the item and opens the party menu
-- itself (engine/items/item_effects.asm:759-772).
t.hold("A", 6, nil)
local function on_party_menu()
    return r8(PARTY_MENU_TYPE) == 5 and r8(TOP_MENU_Y) == 1 and r8(TOP_MENU_X) == 0
end
run(240, nil, on_party_menu)
if not on_party_menu() then
    fail_here("EVO_STONE party menu appeared",
              fmt("type=%d topY=%d topX=%d", r8(PARTY_MENU_TYPE), r8(TOP_MENU_Y), r8(TOP_MENU_X)))
end
t.check("the stone reached wEvoStoneItemID", r8(EVO_STONE_ITEM_ID) == MOON_STONE,
        fmt("got 0x%02X want 0x%02X", r8(EVO_STONE_ITEM_ID), MOON_STONE))
-- PartyMenuInit caps wMaxMenuItem at wPartyCount-1, so with one mon the cursor cannot be
-- anywhere but slot 0 (pokered home/pokemon.asm:216-224).
t.check("party menu cursor is pinned to slot 0",
        r8(CUR_MENU) == 0 and r8(MAX_MENU) == 0,
        fmt("cur=%d max=%d", r8(CUR_MENU), r8(MAX_MENU)))

-- ── Confirm the mon, and make sure the press actually LANDS ──────────────────
-- DisplayPartyMenu returns CARRY on cancel, and wForceEvolution is only set when carry is
-- clear (item_effects.asm:774-778). So a press that does not register as a fresh edge is
-- indistinguishable from the player backing out: the item use is dropped silently and
-- ItemUseNoEffect runs. That is exactly what this gate hit — every earlier step passed,
-- wEvoStoneItemID was set, and then nothing evolved.
--
-- pokered's JoypadLowSensitivity wants a fresh press EDGE, and two t.hold calls back to back
-- give it barely one release frame. So: release for a clear gap, press, and RETRY until the
-- flag latches, rather than pressing once and hoping.
local confirmed = false
for attempt = 1, 12 do
    run(20, nil, nil)                      -- neutral frames guarantee a release edge
    t.hold("A", 4, nil)
    run(20, nil, function() return r8(FORCE_EVOLUTION) ~= 0 end)
    if r8(FORCE_EVOLUTION) ~= 0 then
        confirmed = true
        t.log(fmt("[evo] party-menu confirm landed on attempt %d", attempt))
        break
    end
    if not on_party_menu() then break end  -- menu gone: either cancelled or already moving on
end
t.check("the party-menu confirmation registered as a press, not a cancel", confirmed,
        confirmed and fmt("wForceEvolution=%d", r8(FORCE_EVOLUTION))
                  or "DisplayPartyMenu returned carry — the item use was dropped as a cancel")

-- ── The evolution ────────────────────────────────────────────────────────────
-- From here on: SAMPLE EVERY FRAME AND PRESS NOTHING. The texts end with `done`, so the
-- sequence is self-advancing, and a neutral pad means nothing this gate does can influence
-- what it observes.
local evolved = run(3000, nil, function() return list_species() == CLEFABLE end)

local struct_frame = seen[invariant .. ":8E"]
t.check("wForceEvolution was set by the stone path", r8(FORCE_EVOLUTION) ~= 0,
        fmt("got %d — without this, B could have cancelled", r8(FORCE_EVOLUTION)))
t.check("wEvolutionOccurred is set (the game really evolved it)",
        r8(EVOLUTION_OCCURRED) == 1,
        fmt("got %d — 0 means ItemUseNoEffect ran instead", r8(EVOLUTION_OCCURRED)))
t.check("the species LIST reached CLEFABLE", evolved,
        fmt("list=0x%02X struct=0x%02X after %d frames",
            list_species(), struct_species(), t.frame))
t.check("the stone was consumed from the bag", r8(M.BAG_COUNT_ADDR) == 0,
        fmt("bag count %d — a leftover stone means RemoveItemFromInventory never ran",
            r8(M.BAG_COUNT_ADDR)))

local after = M.readPartySlot(0)
if not after then fail_here("slot 0 decodes after the evolution", "readPartySlot returned nil") end
local after_key = after.key
t.log(fmt("[evo] after:  key=%s level=%d hp=%d/%d nick=%q  (struct changed at frame %s)",
          after_key, after.level, after.hp, after.maxHP, M.readPartyNickname(0),
          tostring(struct_frame)))

-- ── What the server is owed ──────────────────────────────────────────────────
t.check("the key changed", after_key ~= before_key, fmt("%s -> %s", before_key, after_key))
t.check("the new key carries the CLEFABLE index", after_key:sub(11, 12) == "8E",
        fmt("key=%s", after_key))

-- THE assertion. This is verbatim the predicate gen1_rby_client.lua:865 uses to choose
-- key_change over capture. If it is false, the pair unlinks and a phantom mon appears.
t.check("DVs+OTID survived the evolution (client sends key_change, not capture)",
        before_key:sub(1, 9) == after_key:sub(1, 9),
        fmt("%s -> %s", before_key:sub(1, 9), after_key:sub(1, 9)))

-- The other half of that predicate: the client only migrates when the key differs in a
-- slot it already knows. Two keys, in order, is the whole contract.
t.check("exactly two keys were ever visible in slot 0",
        #order == 2 and order[1] == before_key and order[2] == after_key,
        fmt("saw %d: %s", #order, table.concat(order, " ")))

t.check("the species the server records maps to NatDex 35 -> 36",
        t.G.toNatDex(CLEFAIRY) == 35 and t.G.toNatDex(after.species_index) == 36,
        fmt("%s -> %s", tostring(t.G.toNatDex(CLEFAIRY)),
            tostring(t.G.toNatDex(after.species_index))))

t.check("the mon is still alive and in the party", M.getPartyCount() == 1
        and after.hp > 0 and after.maxHP > 0,
        fmt("count=%d hp=%d/%d", M.getPartyCount(), after.hp, after.maxHP))

-- The struct's species byte (what readPartySlot keys on) is written by the CopyData at
-- pokered engine/pokemon/evos_moves.asm:207; the species LIST is written ~20 instructions
-- and several routines later, at :228. Anything that reads the list — depositPartyMon,
-- readPartyBlob for the Rival Team Swap — sees the pre-evolution species inside that
-- window. Bound it, so a future ROM or a Yellow-only difference that opens it wide (a move
-- prompt, a tileset reload that waits) is caught here instead of by a partner receiving a
-- Clefairy blob for a Clefable.
local gap = struct_frame and (t.frame - struct_frame) or -1
t.check("struct and species list agree once the dust settles",
        struct_species() == CLEFABLE and list_species() == CLEFABLE,
        fmt("struct=0x%02X list=0x%02X", struct_species(), list_species()))
t.log(fmt("[evo] struct->list catch-up window: %d frames (upper bound only; both agree now)", gap))

t.finish(fmt("variant=%s frames=%d", t.variant, t.frame))
