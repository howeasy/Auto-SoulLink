--[[
  lua/tests/test_gen1_apex_refusal_gate.lua — PHYSICAL (pureRGB OVERLAY only): the ROM-level
  APEX CHIP collision guard the M3 overlay adds (patch/gen1/purergb/overlay/apex_guard.asm,
  `SlinkApexGuard`, retargeted onto `ItemUseMedicine.setDVs` by tools/apply_purergb_overlay.py).

  This is a DIFFERENT check from lua/tests/test_gen1_apex_gate.lua, which proves the CLIENT's own
  post-hoc restore (`apex_preflight`/`apex_commit`, PLAN A1) on a build with no ROM guard at all.
  Here the guard runs INSIDE the item routine, before the DV store: on a hit it branches to
  pureRGB's own `.alreadyUsedApex` label (the same text/flow the base engine already uses when a
  mon's OWN DVs are already $FFFF, engine/items/item_effects.asm:1673) with the chip still in the
  bag. Because slot 1's own DVs are NOT maxed here, landing there can only be the NEW cross-mon
  check firing.

  Setup: on a booted pure town fixture (one starter, empty bag), clone slot 1's whole 44-byte
  party struct + 11-byte OT name + 11-byte nickname into slot 2 (wPartyMon2/wPartyMonOT/
  wPartyMonNicks — PARTY_MON_SIZE/NAME_SIZE, server/adapters/gen1_codec.py; these are Gen 1 ABI
  constants, identical on vanilla and pureRGB, not a per-foundation fact), bump wPartyCount to 2
  and its species-list terminator, then set slot 2's clone DVs to $FFFF (offset 27, MON_DVS —
  apex_guard.asm's `.match` compares species @0, MON_OTID @12, DVS @27-28 only; OT name and
  nickname are copied for a realistic party record but are not what the guard reads).

  What has to be true:
    1. the chip is USED on slot 1 (same species+OT, DVs still normal) while slot 2 carries the
       $FFFF clone -> the guard's `.scanList` finds slot 2 and refuses before the DV store;
    2. slot 1's DVs are UNCHANGED and the chip is NOT consumed (bag count stays 1);
    3. pureRGB's own `.alreadyUsedApex` text reaches the message box (probed as "already", the
       one word in "There's already an APEX CHIP installed on..." that the tile decoder's
       letters-only whitelist can spell — data/text/text_6.asm:121-128);
    4. the client sent no key_change: nothing was written for `apex_preflight`/`apex_commit` to
       restore, because the ROM never reached the store;
    5. with the clone removed, the SAME chip used on the SAME slot 1 now goes through normally:
       chip consumed, DVs become $FFFF.

  Run against an overlay-admitted pure cartridge:
      python tools/run_gb_gate.py lua/tests/test_gen1_apex_refusal_gate.lua --rom purered_overlay --target town
  Result file: patch/build/test_gen1_apex_refusal_gate_result.txt
--]]
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gate.lua")
local t = G.start("test_gen1_apex_refusal_gate")
local fmt = string.format
local ram, F = t.parts.profile.ram, t.facts
local reads, json = t.parts.reads, t.parts.json
local Center = dofile(t.ROOT .. "/lua/tests/gen1_rb_center_inputs.lua")

if t.kind ~= "overlay" then
    t.check("gate runs on an overlay-admitted pureRGB cartridge", false,
            fmt("title=%s kind=%s — SlinkApexGuard only exists in the M3 overlay", t.title, tostring(t.kind)))
    t.finish()
end

-- Gen 1 party-record ABI (server/adapters/gen1_codec.py: PARTY_MON_SIZE/NAME_SIZE/_FIELDS/_DVS;
-- identical on vanilla and pureRGB — a struct-layout fact, not a per-foundation one).
local PARTY_MON_SIZE, NAME_SIZE = 44, 11
local OT_ID_OFFSET, DVS_OFFSET = 12, 27
local APEX_CHIP = 0x32

local function u8(addr) return memory.read_u8(addr, "System Bus") end
local function w8(addr, v) memory.write_u8(addr, v, "System Bus") end
local function bag_count() return u8(ram.wNumBagItems) end
local function inject_chip()
    w8(ram.wNumBagItems, 1)
    w8(ram.wBagItems, APEX_CHIP)
    w8(ram.wBagItems + 1, 1)
    w8(ram.wBagItems + 2, 0xFF)
end
local function dvs_slot1()
    local p = reads.read_party()
    return p and p[1] and p[1].dvs.raw or -1
end
local function sent_events(name)
    local out = {}
    for _, line in ipairs(t.sent) do
        local ok, msg = pcall(json.decode, line)
        if ok and type(msg) == "table" and msg.event == name then out[#out + 1] = msg end
    end
    return out
end
local function tap(btn, gap)
    t.step({ [btn] = true }); t.client:frame_end()
    for _ = 1, (gap or 40) do t.step(nil); t.client:frame_end() end
end
local function settle(frames) for _ = 1, frames do t.step(nil); t.client:frame_end() end end
local function menu_max() return u8(ram.wMaxMenuItem) end
local function menu_cur() return u8(ram.wCurrentMenuItem) end
local function wait_menu(max, frames)
    for _ = 1, frames do
        if menu_max() == max then return true end
        t.step(nil); t.client:frame_end()
    end
    return false
end
local function move_to(row)
    for _ = 1, 8 do
        if menu_cur() == row then return true end
        tap(menu_cur() < row and "Down" or "Up", 12)
    end
    return menu_cur() == row
end
local function menu_state()
    return fmt("max=%d cur=%d bag=%d party=%d dvs1=%04X", menu_max(), menu_cur(), bag_count(),
               u8(ram.wPartyCount), dvs_slot1())
end
local START_MAX = F.MENU.START.save_index_without_pokedex + F.MENU.START.max_minus_save

--- Copy slot 1's whole struct + OT name + nickname into slot 2, and mark the CLONE's DVs
--- $FFFF. Only the guard-visible fields (species/OT id/DVs) matter to apex_guard.asm's
--- `.match`; the rest is copied for a realistic party record.
local function clone_slot1_into_slot2_as_apex()
    for i = 0, PARTY_MON_SIZE - 1 do w8(ram.wPartyMon2 + i, u8(ram.wPartyMon1 + i)) end
    for i = 0, NAME_SIZE - 1 do w8(ram.wPartyMonOT + NAME_SIZE + i, u8(ram.wPartyMonOT + i)) end
    for i = 0, NAME_SIZE - 1 do w8(ram.wPartyMonNicks + NAME_SIZE + i, u8(ram.wPartyMonNicks + i)) end
    w8(ram.wPartyMon2 + DVS_OFFSET, 0xFF)
    w8(ram.wPartyMon2 + DVS_OFFSET + 1, 0xFF)
    w8(ram.wPartySpecies + 1, u8(ram.wPartySpecies))  -- clone's species = slot 1's species
    w8(ram.wPartySpecies + 2, 0xFF)                   -- terminator moves out one slot
    w8(ram.wPartyCount, 2)
end

--- Undo the clone: party count back to 1, terminator back where it was. Slot 2's bytes are
--- left as garbage on purpose -- nothing reads past wPartyCount mons.
local function remove_clone()
    w8(ram.wPartyCount, 1)
    w8(ram.wPartySpecies + 1, 0xFF)
end

--- Drive the item menu onto slot 1 exactly like test_gen1_apex_gate.lua's use_chip_on_slot1,
--- generalised to however many party mons are currently seeded (`party_max` = wMaxMenuItem the
--- party-picker screen shows, 0-based: 0 with one mon, 1 with two).
local function use_chip_on_slot1(tag, party_max)
    local bag0 = bag_count()
    tap("Start", 30)
    t.check(tag .. ": START menu open", wait_menu(START_MAX, 120), menu_state())
    move_to(1); tap("A", 30)                              -- ITEM
    t.check(tag .. ": item list open", wait_menu(1, 120), menu_state())  -- APEX CHIP + CANCEL
    move_to(0); tap("A", 30)                              -- select the chip -> USE/TOSS
    t.check(tag .. ": USE/TOSS submenu", wait_menu(1, 120) and menu_cur() == 0, menu_state())
    tap("A", 30)                                          -- USE -> party menu
    t.check(tag .. ": party menu open", wait_menu(party_max, 120), menu_state())
    move_to(0); tap("A", 60)                               -- mon 1 (slot 1): the item routine runs now
    for _ = 1, 40 do
        if t.overworld_ok() then break end
        tap("A", 20); tap("B", 20)
    end
    for _ = 1, 400 do
        if t.overworld_ok() then break end
        tap("B", 15)
    end
    settle(120); t.log(tag .. " settled: " .. menu_state())
end

local ok, err = xpcall(function()
t.online = true
local ok0, err0 = pcall(function() t.client:start() end)
t.check("client armed", ok0, err0)
t.client:send_hello()
settle(120)
t.check("writes enabled on the live save", t.client.writes_enabled == true, tostring(t.client.writes_enabled))

local dv0 = dvs_slot1()
t.check("slot 1 readable with non-maxed DVs", dv0 >= 0 and dv0 ~= 0xFFFF, fmt("dvs=%04X", dv0))
t.check("party starts with one mon", u8(ram.wPartyCount) == 1, fmt("count=%d", u8(ram.wPartyCount)))

-- 1. seed the collision: slot 2 clones slot 1's species+OT, DVs $FFFF
clone_slot1_into_slot2_as_apex()
t.check("clone seeded: party count is 2", u8(ram.wPartyCount) == 2, fmt("count=%d", u8(ram.wPartyCount)))
t.check("clone seeded: species list terminates after 2", u8(ram.wPartySpecies + 2) == 0xFF,
        fmt("byte=%02X", u8(ram.wPartySpecies + 2)))

inject_chip()
t.check("chip injected", bag_count() == 1, fmt("bag=%d", bag_count()))
local sent_before = #t.sent
use_chip_on_slot1("REFUSAL", 1)   -- party menu shows 2 mons -> max index 1

local dv1 = dvs_slot1()
t.check("refusal: slot 1 DVs unchanged", dv1 == dv0, fmt("before=%04X after=%04X", dv0, dv1))
t.check("refusal: chip NOT consumed", bag_count() == 1, fmt("bag=%d", bag_count()))
t.check("refusal: pureRGB's own alreadyUsedApex text reached the message box",
        Center.has_tiles(u8, ram.wTileMap, "already"),
        "no 'already' tile run on screen — the guard did not branch to .alreadyUsedApex")
t.check("refusal: no key_change sent (nothing to restore)",
        #sent_events("key_change") == 0, fmt("%d sent", #sent_events("key_change")))
t.log(fmt("SENT_AFTER_REFUSAL %d lines", #t.sent - sent_before))

-- 2. remove the collision and use the SAME chip on the SAME slot normally
remove_clone()
t.check("clone removed: party count back to 1", u8(ram.wPartyCount) == 1, fmt("count=%d", u8(ram.wPartyCount)))
use_chip_on_slot1("NORMAL", 0)     -- party menu shows 1 mon again -> max index 0

local dv2 = dvs_slot1()
t.check("normal use: chip consumed", bag_count() == 0, fmt("bag=%d", bag_count()))
t.check("normal use: DVs are FFFF", dv2 == 0xFFFF, fmt("dvs=%04X", dv2))
end, debug.traceback)
if not ok then t.check("apex refusal gate sequence", false, tostring(err)) end
t.finish()
