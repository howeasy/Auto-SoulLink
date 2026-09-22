-- Pure Gen 2 wire projection: turns a decoded party/box/battle-mon record
-- (lua/gen2/reads.lua stable output shape) into the JSON-shaped snapshot
-- entry docs/protocol.md expects (party entry S4.1, foe entry S4.3, box entry
-- S4.4). Game facts and projection only: no transport, no admission, no
-- emulator globals, no writes, no `require`. This module never decodes a
-- name itself (no hard-coded charmap) -- it only forwards `mon.nickname`,
-- a plain string that reads.lua already produced from its own injected
-- name-decoder input (R.new's `decode_name` parameter). A caller whose
-- reads.lua instance was built without a decoder simply gets no `nickname`
-- field, which docs/protocol.md S4.1/S4.4 mark optional (SHOULD, not MUST).
--
-- Pins: pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651;
--       pokegold@656583c939d30f920a316177311a502dd222b57c.
--
-- Gen 2 differences from lua/gen1/client.lua inline wire-building, each with
-- its reason, are cited at the point they apply below; summary:
--   1. Factored into its own pure module (this file) instead of building
--      wire tables inline inside client.lua, so it is independently testable
--      without HelloSession/net/io mocks -- it mirrors reads.lua existing
--      split between pure decode and live IO (lua/gen2/reads.lua:44-573).
--   2. `held_item_id` is populated (client.lua:202-210 party_entry never
--      sets it): Gen 1 cartridges have no held-item mechanic at all, Gen 2
--      introduced it, and docs/protocol.md S4.1/S4.4 both list the field.
--   3. Stat-stage neutral-offset conversion is NOT redone here: unlike Gen 1
--      (client.lua:129-133 wire_stages, which also blanks the SDEF slot to
--      neutral because Gen 1 tracks only one combined "Special" stage),
--      Gen 2 tracks Attack/Defense/Speed/SpAtk/SpDef/Accuracy/Evasion as
--      seven independent stages and reads.lua read_stat_stages(...).wire
--      already applies the docs/protocol.md S4.1 6-neutral offset in the
--      exact ATK,DEF,SPD,SATK,SDEF,ACC,EVA wire order (reads.lua:529-560).
--      This module only validates and passes it through unchanged.
--   4. `key` is never emitted on a foe entry: Gen 2 battle_mon struct
--      (macros/ram.asm battle_struct, read by reads.read_battle_mon) carries
--      no OT id field -- only the party/box structs do -- so there is no
--      source fact to build DVs:OTID:species from for an active battler.
--      docs/protocol.md S4.3 lists `key` as optional ("as S4.1"); Gen 1
--      enemy_party (client.lua:252-259) omits it for the same underlying
--      reason (no OT id in its battle-view read either).
--   5. `ability_id`/`form` are never emitted anywhere: Gen 2 has no ability
--      system (server/adapters/gen2_gsc.py supports_abilities -> False) and
--      no dex form beyond cosmetic Unown, which
--      server/adapters/gen2_gsc.py form_sprite_id documents as "presentation
--      only, never identity" -- so this module never fabricates a wire value
--      for either.
--   6. A record whose `is_egg` is true is refused outright by party_entry
--      and box_entry (see refuse_egg below): open item, see the module
--      footer comment.

local M = {}

local function is_integer(value, low, high)
    return type(value) == "number" and value == math.floor(value) and value >= low and value <= high
end

local function hex_field(mon, field, byte_length)
    local value = mon[field]
    if type(value) ~= "string" or #value ~= byte_length * 2 or value:match("^%x*$") == nil then
        return nil, "missing/invalid " .. field
    end
    return value
end

local function four(list)
    if type(list) ~= "table" or #list ~= 4 then return nil end
    for i = 1, 4 do if not is_integer(list[i], 0, 255) then return nil end end
    return { list[1], list[2], list[3], list[4] }
end

-- docs/protocol.md S3.1: three-segment key, DDDD:OOOO:SS, DVs/OT uppercase
-- hex, internal species hex -- matches server/adapters/gen2_codec.py key and
-- Gen2GSCAdapter.is_valid_mon_key ([0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}:[0-9A-Fa-f]{2},
-- species 1..251) exactly, field for field.
function M.mon_key(mon)
    if type(mon) ~= "table" then return nil, "mon record required" end
    if not is_integer(mon.dv_word, 0, 65535) then return nil, "invalid or missing dv_word" end
    if not is_integer(mon.ot_id, 0, 65535) then return nil, "invalid or missing ot_id" end
    if not is_integer(mon.species_id, 1, 251) then return nil, "invalid or missing species_id" end
    return string.format("%04X:%04X:%02X", mon.dv_word, mon.ot_id, mon.species_id)
end

-- The 70-byte transfer blob docs/protocol.md S4.1 requires (`blob_hex`,
-- exactly party_blob_size()*2 = 140 hex chars), in gen2_codec.decode_party_blob
-- /encode_party_blob exact field order: 48-byte party struct, then the
-- 11-byte OT name, then the 11-byte nickname. Assembled only from the
-- record own raw hex fields (reads.lua decode_record/decode_transfer_blob
-- already produced them from the live bytes) -- never re-serialized
-- field-by-field here, so this module cannot itself introduce a field-order
-- bug in the blob; it can only fail to find the three hex strings.
local function party_blob_hex(mon)
    local record, why = hex_field(mon, "raw_hex", 48)
    if not record then return nil, why end
    local ot, why_ot = hex_field(mon, "ot_raw_hex", 11)
    if not ot then return nil, why_ot end
    local nickname, why_nick = hex_field(mon, "nickname_raw_hex", 11)
    if not nickname then return nil, why_nick end
    return record .. ot .. nickname
end

-- An egg species-list marker (253) is the ONLY honest witness that a record
-- is an egg; reads.lua already carries that as `mon.is_egg`, decoded from the
-- separately observed marker, never inferred from record bytes (reads.lua:107-110,
-- 120). docs/protocol.md defines no wire shape for an egg on a party or box
-- entry -- only the `capture` event carries `is_egg` (S3.2) -- and an egg
-- record own `species_id` field holds its real (post-hatch) species, so
-- projecting it through party_entry/box_entry unchanged would silently
-- present an unhatched egg as an ordinary caught mon of that species. Refuse
-- rather than guess at an undefined shape.
local function refuse_egg(mon)
    if mon.is_egg then return "egg record: no defined Gen 2 party/box wire shape (docs/protocol.md has none)" end
    return nil
end

local function stat_stages_of(stages)
    if stages == nil then return nil end
    if type(stages) ~= "table" or #stages ~= 7 then return nil, "invalid stat_stages" end
    local out = {}
    for i = 1, 7 do
        if not is_integer(stages[i], 0, 12) then return nil, "invalid stat_stages" end
        out[i] = stages[i]
    end
    return out
end

-- docs/protocol.md S4.1 (element of `party` in hello/tick/safe).
-- `active_slot` and `stages` are supplied by the caller: this module never
-- reads battle state itself (no emulator globals). `stages` is expected to
-- already be reads.read_stat_stages(...).wire (see the module header, point 3).
function M.party_entry(mon, active_slot, stages)
    if type(mon) ~= "table" then return nil, "mon record required" end
    local egg_reason = refuse_egg(mon)
    if egg_reason then return nil, egg_reason end
    local key, key_why = M.mon_key(mon)
    if not key then return nil, key_why end
    local blob, blob_why = party_blob_hex(mon)
    if not blob then return nil, blob_why end
    if not is_integer(mon.slot, 0, 5) then return nil, "invalid or missing slot" end
    if not is_integer(mon.level, 1, 100) then return nil, "invalid or missing level" end
    if not is_integer(mon.hp, 0, 65535) or not is_integer(mon.max_hp, 0, 65535) then
        return nil, "invalid or missing hp/max_hp"
    end
    if not is_integer(mon.status, 0, 255) then return nil, "invalid or missing status" end
    local moves = four(mon.moves)
    if not moves then return nil, "invalid or missing moves" end
    local pp = four(mon.pp)
    if not pp then return nil, "invalid or missing pp" end
    local pp_ups = four(mon.pp_ups)
    if not pp_ups then return nil, "invalid or missing pp_ups" end
    if not is_integer(mon.held_item, 0, 255) then return nil, "invalid or missing held_item" end
    if mon.nickname ~= nil and type(mon.nickname) ~= "string" then
        return nil, "nickname must be a decoded string, not raw bytes"
    end
    local active = active_slot ~= nil and mon.slot == active_slot
    local entry = {
        key = key, slot = mon.slot, species_id = mon.species_id, level = mon.level,
        hp = mon.hp, maxHP = mon.max_hp, status_cond = mon.status,
        moves = moves, pp = pp, pp_ups = pp_ups,
        held_item_id = mon.held_item, -- gen1 has no held items; see module header point 2
        active = active, blob_hex = blob,
    }
    if mon.nickname ~= nil then entry.nickname = mon.nickname end
    if active and stages ~= nil then
        local wire_stages, stages_why = stat_stages_of(stages)
        if not wire_stages then return nil, stages_why end
        entry.stat_stages = wire_stages
    end
    return entry
end

-- docs/protocol.md S4.3 (element of `enemy_party`). `stages` follows the
-- same contract as party_entry. See module header point 4 for why `key`
-- is never emitted.
function M.foe_entry(mon, stages)
    if type(mon) ~= "table" then return nil, "mon record required" end
    if not is_integer(mon.species_id, 1, 251) then return nil, "invalid or missing species_id" end
    if not is_integer(mon.level, 1, 100) then return nil, "invalid or missing level" end
    if not is_integer(mon.hp, 0, 65535) or not is_integer(mon.max_hp, 0, 65535) then
        return nil, "invalid or missing hp/max_hp"
    end
    if not is_integer(mon.status, 0, 255) then return nil, "invalid or missing status" end
    local moves = four(mon.moves)
    if not moves then return nil, "invalid or missing moves" end
    local pp = four(mon.pp)
    if not pp then return nil, "invalid or missing pp" end
    local pp_ups = four(mon.pp_ups)
    if not pp_ups then return nil, "invalid or missing pp_ups" end
    if not is_integer(mon.held_item, 0, 255) then return nil, "invalid or missing held_item" end
    local entry = {
        species_id = mon.species_id, level = mon.level, hp = mon.hp, maxHP = mon.max_hp,
        status_cond = mon.status, held_item_id = mon.held_item, active = true,
        moves = moves, pp = pp, pp_ups = pp_ups,
    }
    local wire_stages, stages_why = stat_stages_of(stages)
    if stages ~= nil and not wire_stages then return nil, stages_why end
    if wire_stages then entry.stat_stages = wire_stages end
    return entry
end

-- docs/protocol.md S4.4 (element of `pc_boxes`). `box_index` is supplied by
-- the caller (which box a record came from is scan bookkeeping this module
-- never performs). Unlike lua/gen1/client.lua pc_boxes_wire (client.lua:279-286,
-- no held_item_id: Gen 1 has none), this includes `held_item_id` -- see
-- module header point 2.
function M.box_entry(mon, box_index)
    if type(mon) ~= "table" then return nil, "mon record required" end
    local egg_reason = refuse_egg(mon)
    if egg_reason then return nil, egg_reason end
    local key, key_why = M.mon_key(mon)
    if not key then return nil, key_why end
    if not is_integer(box_index, 0, 13) then return nil, "invalid or missing box_index" end
    if not is_integer(mon.slot, 0, 19) then return nil, "invalid or missing slot" end
    if not is_integer(mon.level, 1, 100) then return nil, "invalid or missing level" end
    local moves = four(mon.moves)
    if not moves then return nil, "invalid or missing moves" end
    if not is_integer(mon.held_item, 0, 255) then return nil, "invalid or missing held_item" end
    if mon.nickname ~= nil and type(mon.nickname) ~= "string" then
        return nil, "nickname must be a decoded string, not raw bytes"
    end
    local entry = {
        box = box_index, slot = mon.slot, key = key, species_id = mon.species_id,
        level = mon.level, held_item_id = mon.held_item, moves = moves,
    }
    if mon.nickname ~= nil then entry.nickname = mon.nickname end
    return entry
end

-- OPEN (not defined by docs/protocol.md, so not modeled here): a wire shape
-- for a boxed/partied Gen 2 egg. The shared protocol only is_egg carrier is
-- the `capture` event (S3.2); no generation has ever needed a party/box-entry
-- egg shape before (Gen 1 has no eggs; Gen 3 client never boxes/parties one
-- through this path either). refuse_egg above fails closed until that shape
-- exists upstream, rather than silently mislabeling an egg as its post-hatch
-- species.

return M
