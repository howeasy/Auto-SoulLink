--[[
  lua/tests/test_gen1_apex_gate.lua — PHYSICAL (pureRGB only): the APEX CHIP identity contract.

  On a booted pure town fixture (one starter, empty bag) the gate injects an APEX CHIP and uses it
  on slot 1 twice, from the START menu with blind taps on the lane's cadence:
    1. with the would-be key FFFF:OTID:SS seeded as a server pending capture -> the client must
       restore the two DV bytes inside the apex_commit hook (PLAN A1, Live 4): DVs unchanged,
       no key_change sent, the chip consumed (U6), the refusal HUD line logged;
    2. with the seed cleared -> DVs become FFFF, stats recalculated, a key_change{apex_chip}
       is sent with the alias held until the server's key_change_ack clears it.
  Result file: patch/build/test_gen1_apex_gate_result.txt
--]]
local G = dofile((SLINK_ROOT or os.getenv("SLINK_ROOT")) .. "/lua/tests/gen1_gate.lua")
local t = G.start("test_gen1_apex_gate")
local fmt = string.format
local ram, F = t.parts.profile.ram, t.facts
local reads, json = t.parts.reads, t.parts.json
if t.parts.foundation ~= "purergb" and not ram.wUsedItemOnWhichPokemon then
    t.check("gate runs on a pureRGB title", false, "vanilla has no APEX CHIP"); t.finish()
end

local APEX_CHIP = 0x32
local function bag_count() return memory.read_u8(ram.wNumBagItems, "System Bus") end
local function inject_chip()
    memory.write_u8(ram.wNumBagItems, 1, "System Bus")
    memory.write_u8(ram.wBagItems, APEX_CHIP, "System Bus")
    memory.write_u8(ram.wBagItems + 1, 1, "System Bus")
    memory.write_u8(ram.wBagItems + 2, 0xFF, "System Bus")
end
local function dvs()
    local p = reads.read_party()
    return p and p[1] and p[1].dvs.raw or -1, p and p[1] or nil
end
local function reply(command) t.replies[#t.replies + 1] = assert(json.encode({ commands = { command } })) end
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
-- Wait for the write checkpoint (menus closed, overworld idle) so the client can settle.
local function settle(frames)
    for _ = 1, frames do t.step(nil); t.client:frame_end() end
end
local function menu_state()
    return fmt("menu max=%d cur=%d y=%d joy=%d font=%d bag=%d dvs=%04X pc=%s",
               memory.read_u8(ram.wMaxMenuItem, "System Bus"), memory.read_u8(ram.wCurrentMenuItem, "System Bus"),
               0, memory.read_u8(ram.wJoyIgnore, "System Bus"),
               memory.read_u8(ram.wFontLoaded, "System Bus"), bag_count(), (dvs()),
               tostring(t.client.pending_change and t.client.pending_change.kind))
end
local function menu_max() return memory.read_u8(ram.wMaxMenuItem, "System Bus") end
local function menu_cur() return memory.read_u8(ram.wCurrentMenuItem, "System Bus") end
-- Wait until the live menu reports `max` (pureRGB stores the LAST row index), pressing nothing.
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
-- Reuse the scripted host's title-specific symbols and the shared event-bit decoder.
local play = dofile(t.ROOT .. "/lua/tests/gen1_scripted_play.lua").new(t.ROOT, t.title, t.client.player)
local fields = dofile(t.ROOT .. "/lua/tests/gen1_rb_point_fields.lua")
local read_bus = dofile(t.ROOT .. "/lua/gen1/entry.lua").harness_bus_u8()
local function start_shape()
    local dex = fields.event_bit(read_bus, assert(play.symbols.wEventFlags), F.EVENT.GOT_POKEDEX)
    local companion = t.client.trade_enabled == true
    local menu = F.MENU.START
    local save = dex and menu.save_index_with_pokedex or menu.save_index_without_pokedex
    -- Pokédex prepends a row; SLINK appends one without moving ITEM.
    return save + menu.max_minus_save + (companion and 1 or 0), dex and 2 or 1, dex, companion
end
local function use_chip_on_slot1(tag)
    local bag0 = bag_count()
    local start_max, item_row, dex, companion = start_shape()
    tap("Start", 30)
    local opened = wait_menu(start_max, 120)
    t.log(fmt("START_SHAPE %s pokedex=%s companion=%s expected_max=%d observed_max=%d item_row=%d",
              tag, tostring(dex), tostring(companion), start_max, menu_max(), item_row))
    t.check(tag .. ": START menu open", opened, menu_state())
    move_to(item_row); tap("A", 30)                       -- ITEM
    t.check(tag .. ": item list open", wait_menu(1, 120), menu_state())  -- APEX CHIP + CANCEL
    move_to(0); tap("A", 30)                              -- select the chip -> USE/TOSS
    t.check(tag .. ": USE/TOSS submenu", wait_menu(1, 120) and menu_cur() == 0, menu_state())
    tap("A", 30)                                          -- USE -> party menu (one mon: max 0)
    t.check(tag .. ": party menu open", wait_menu(0, 120), menu_state())
    tap("A", 60)                                          -- mon 1: the item routine runs now
    -- dismiss the result text and back out until the overworld checkpoint is reachable
    for _ = 1, 40 do
        if bag_count() < bag0 and t.overworld_ok() then break end
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

local dv0, mon0 = dvs()
t.check("slot 1 readable with non-maxed DVs", mon0 ~= nil and dv0 ~= 0xFFFF, fmt("dvs=%04X", dv0))
local key0 = mon0 and reads.key(mon0) or "?"
local new_key = mon0 and fmt("%04X:%04X:%02X", 0xFFFF, mon0.ot_id, mon0.species) or "?"
t.log(fmt("SLOT1 key=%s would-be=%s", key0, new_key))

-- 1. collision seeded by the server: the use must be refused at the commit hook
reply({ cmd = "pending_keys", keys = { new_key } })
settle(10)
inject_chip()
t.check("chip injected", bag_count() == 1, fmt("bag=%d", bag_count()))
local sent_before = #t.sent
use_chip_on_slot1("USE1")
local dv1 = dvs()
t.check("collision: DVs restored (unchanged)", dv1 == dv0, fmt("before=%04X after=%04X", dv0, dv1))
t.check("collision: chip consumed", bag_count() == 0, fmt("bag=%d", bag_count()))
t.check("collision: no key_change sent", #sent_events("key_change") == 0, fmt("%d sent", #sent_events("key_change")))
t.log(fmt("SENT_AFTER_COLLISION %d lines", #t.sent - sent_before))

-- 2. seed cleared: the use goes through and re-keys the mon
reply({ cmd = "pending_keys", keys = {} })
settle(10)
inject_chip()
t.check("second chip injected", bag_count() == 1, fmt("bag=%d", bag_count()))
use_chip_on_slot1("USE2")
local dv2, mon2 = dvs()
t.check("apex: DVs are FFFF", dv2 == 0xFFFF, fmt("dvs=%04X", dv2))
t.check("apex: chip consumed", bag_count() == 0, fmt("bag=%d", bag_count()))
local kc = sent_events("key_change")
t.check("apex: one key_change sent", #kc == 1, fmt("%d sent", #kc))
if kc[1] then
    t.check("apex: key_change reason is apex_chip", kc[1].reason == "apex_chip", tostring(kc[1].reason))
    t.check("apex: old/new keys as predicted", kc[1].old_key == key0 and kc[1].new_key == new_key,
            fmt("%s -> %s", tostring(kc[1].old_key), tostring(kc[1].new_key)))
    t.check("apex: alias held until ack", t.client.key_alias ~= nil and t.client.key_alias.new_key == new_key,
            tostring(t.client.key_alias and t.client.key_alias.new_key))
    reply({ cmd = "key_change_ack", old_key = kc[1].old_key, new_key = kc[1].new_key, migrated = true })
    settle(30)
    t.check("apex: alias cleared by key_change_ack", t.client.key_alias == nil, tostring(t.client.key_alias))
end
t.log(fmt("STATS after: %s", json.encode(mon2 and { hp = mon2.hp, max_hp = mon2.max_hp, level = mon2.level } or {})))
end, debug.traceback)
if not ok then t.check("apex gate sequence", false, tostring(err)) end
t.finish()
