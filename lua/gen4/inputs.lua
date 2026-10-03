-- lua/gen4/inputs.lua -- producers for the rewritten Gen 4 client's four OPTIONAL inputs
-- (lua/gen4/client.lua p.area_of / p.charmap / p.has_pokeballs / p.gift_area).
--
-- Rule: a producer exists only where the PACK carries the fact. This file names no game address,
-- no struct offset, no item id and no char code. A fact the pack does not ship yields
-- (nil, named reason) so the client's seam stays UNWIRED rather than guessing -- the client
-- already treats every one of the four as optional (client.lua area_now/trainer_fields/hello_fields,
-- and the reducer's gift_area seam).
--   Inputs.area_of(deps)       -> function(map_id, loc) -> area_id, loc_name | nil, reason
--   Inputs.charmap(deps)       -> { [code] = text }              | nil, reason
--   Inputs.has_pokeballs(deps) -> function() -> bool | nil       | nil, reason
--   Inputs.gift_area(deps)     -> function(area_id) -> bool      | nil, reason
--   Inputs.build(deps)         -> { area_of = ..., charmap = ..., has_pokeballs = ...,
--                                   gift_area = ... }, gaps[]
--
-- deps = { root, json, pack_profile (repo-relative profile.json path, from Entry.PACKS), log,
--          title      the admitted title name (Entry.admit's `title`), which picks the row out of
--                    profile.json `titles`;
--          save_array function(array_id) -> function(off, len) -> value | nil, reason
--                                    | nil, reason }
--
-- Facts, and where each one comes from:
--   area_of   data/games/<pack>/area_map.json  `.maps[map_id]`  -> area_id or JSON null
--             (tools/gen_gen4_area_map.py, pret/pokeheartgold@ad7a3afa; null = not a Soul Link
--             place, the file's `unmapped_maps` explains each), and
--             data/games/<pack>/locations.json `.locations[map_id].name` -> loc_name.
--             SHIPPED for gen4_hgss. gen4_hge ships no area map, so its producer refuses.
--   gift_area   data/games/<pack>/area_map.json `.gift_areas.ids` -> the areas a scripted
--             starter/gift/egg/loan reaches and no wild-encounter map backs (tools/
--             gen_gen4_area_map.py over acquisition.json; the rule is that file's rules.gift_areas).
--             SHIPPED for gen4_hgss, inside the SAME area_map.json area_of already needs. A pack with
--             no gift_areas block refuses, so no area is exempt -- never the reverse.
--   charmap   data/games/<pack>/charmap.json `.glyphs[dec_code]` -> text (tools/gen_gen4_names.py;
--             the pack-directory convention data/games/gen1_purergb/charmap.json already uses).
--             The table is keyed by NUMBER here, because R.decode_name (reads.lua) looks a u16 up
--             as a number -- the file's decimal-string keys are converted once, at load.
--   has_pokeballs  data/games/<pack>/profile.json `titles.<t>.profile.bag` (tools/gen_gen4_pack.py):
--             the bag save array's balls pocket -- { array_id, balls_pocket_off, ball_slot_size,
--             ball_slot_count, slot_fields{id,quantity}.{off,size}, ball_ids }. Every offset is
--             relative to that ARRAY's base (`base: bag_array`), never to the general block. A pack
--             that cannot source the fact emits `null` with the reason in `titles.<t>.open.bag`.
--
-- `deps.save_array` is this file's ONLY route to the save, so it names no address and no struct
-- offset: it resolves save data + array by id the way the client does (reads.lua R.save_data ->
-- R.array) and hands back a bounds-checked reader over that array's base, where `off` is
-- ARRAY-relative. run.lua owns it because run.lua owns the BizHawk io adapters.
local Inputs = {}


-- Read a pack data file. Absence is a normal outcome (a fact this pack does not ship), never an
-- error: the caller turns it into a named gap.
local function load_optional(json, path)
    local f = io.open(path, "rb")
    if not f then return nil, "missing " .. path end
    local text = f:read("*a")
    f:close()
    local ok, doc = pcall(json.decode, text)
    if not ok or type(doc) ~= "table" then return nil, "unreadable " .. path end
    return doc
end

-- The pack directory, taken from the profile path Entry.PACKS already owns, so there is one
-- convention for "a pack's files" and not two.
local function pack_dir(deps)
    local rel = deps.pack_profile
    if type(rel) ~= "string" or rel == "" then return nil, "pack_gap:deps.pack_profile" end
    -- anchored on the directory separator: "not_a_profile.json" is not a profile.json path
    local dir = rel:match("^(.*[/\\])profile%.json$")
    if not dir then return nil, "pack_gap:deps.pack_profile (not a profile.json path)" end
    return dir
end

-- map_id (number, from reads.R.location) -> area_id + the name the game shows for that map.
-- An unmapped map is (nil, name): the Soul Link area stays empty, the HUD label does not.
function Inputs.area_of(deps)
    local dir, why = pack_dir(deps)
    if not dir then return nil, why end
    local base = deps.root .. "/" .. dir
    local doc
    doc, why = load_optional(deps.json, base .. "area_map.json")
    if not doc then return nil, why end
    local maps = doc.maps
    if type(maps) ~= "table" then return nil, "pack_gap:" .. dir .. "area_map.json .maps" end
    local locs_doc
    locs_doc, why = load_optional(deps.json, base .. "locations.json")
    if not locs_doc then return nil, why end
    local locs = locs_doc.locations
    if type(locs) ~= "table" then return nil, "pack_gap:" .. dir .. "locations.json .locations" end
    return function(map_id, _loc)
        local key = tostring(map_id)
        -- JSON null decodes to a table, so only a real string is an area id.
        local area = maps[key]
        if type(area) ~= "string" then area = nil end
        local row = locs[key]
        local name = type(row) == "table" and row.name or nil
        if type(name) ~= "string" then name = nil end
        return area, name
    end
end

-- area_id -> true iff the pack lists it a gift area: an area no map of which owns a wild-encounter
-- bank, so the only way a mon enters it is the starter / a gift / an egg / a loan. Read from
-- data/games/<pack>/area_map.json `gift_areas.ids`, derived by tools/gen_gen4_area_map.py over the
-- pack's acquisition.json (that file's rules.gift_areas states the rule; the split fails closed if
-- an area in `ids` ever owns a wild-encounter map).
--
-- The answer is ALWAYS a boolean, never nil: an area the pack does not name is not a gift area, and
-- false is the safe direction. The client drops no_catch for a gift area
-- (lua/gen4/poll_events.lua:415-418), so a wrong true swallows a real failed encounter while a wrong
-- false only lets the ordinary rule run -- the opposite of has_pokeballs below, where false was the
-- dangerous answer.
--
-- A pack with no valid gift_areas REFUSES (nil, named gap), and Inputs.build then leaves the seam
-- ABSENT, so the client treats NO area as a gift area. That deliberately differs from Gen 3, where a
-- missing list means "every area is a gift" (D10/E3-GIFTLINK): Gen 4 has no NEW ENCOUNTER banner,
-- so an every-area-gift fallback would silently switch no_catch off for a whole run.
function Inputs.gift_area(deps)
    local dir, why = pack_dir(deps)
    if not dir then return nil, why end
    local doc
    doc, why = load_optional(deps.json, deps.root .. "/" .. dir .. "area_map.json")
    if not doc then return nil, why end
    local block = doc.gift_areas
    if type(block) ~= "table" then return nil, "pack_gap:" .. dir .. "area_map.json .gift_areas" end
    local list = block.ids
    if type(list) ~= "table" then return nil, "pack_gap:" .. dir .. "area_map.json .gift_areas.ids" end
    local ids = {}
    for _, area_id in ipairs(list) do
        -- A JSON null decodes to a table, so shape is what tells a real area id from an absent one.
        if type(area_id) ~= "string" or area_id == "" then
            return nil, "pack_gap:" .. dir .. "area_map.json .gift_areas.ids -- not a non-empty string"
        end
        ids[area_id] = true
    end
    if next(ids) == nil then return nil, "pack_gap:" .. dir .. "area_map.json .gift_areas.ids is empty" end
    return function(area_id)
        return type(area_id) == "string" and ids[area_id] == true
    end
end

-- u16 charcode -> display text, from the pack's charmap.json.
function Inputs.charmap(deps)
    local dir, why = pack_dir(deps)
    if not dir then return nil, why end
    local doc
    doc, why = load_optional(deps.json, deps.root .. "/" .. dir .. "charmap.json")
    if not doc then return nil, why end
    local glyphs = doc.glyphs
    if type(glyphs) ~= "table" then return nil, "pack_gap:" .. dir .. "charmap.json .glyphs" end
    local out = {}
    for key, text in pairs(glyphs) do
        local code = tonumber(key)
        if type(code) == "number" and type(text) == "string" then out[code] = text end
    end
    if next(out) == nil then return nil, "pack_gap:" .. dir .. "charmap.json .glyphs is empty" end
    return out
end

-- true iff some balls-pocket slot holds an id the pack calls a ball with a quantity above zero.
-- The pack decides WHICH ids are balls; this file adds only the pack's own offsets. A read that
-- refuses at call time answers nil (unknown), never false: the client's own seam treats a nil
-- answer as "not yet": client.lua's has_pokeballs latch seeds from the first valid boolean,
-- then stays true for the run (including an empty/unreadable bag). The reducer also latches
-- upward. Returning false for a refusal would claim a measured empty bag the save never supplied.
function Inputs.has_pokeballs(deps)
    local dir, why = pack_dir(deps)
    if not dir then return nil, why end
    if type(deps.save_array) ~= "function" then
        return nil, "pack_gap:deps.save_array -- function(array_id) -> function(off, len) -> value | nil, reason"
    end
    if type(deps.title) ~= "string" then return nil, "pack_gap:deps.title -- the admitted title name" end
    local doc
    doc, why = load_optional(deps.json, deps.root .. "/" .. dir .. "profile.json")
    if not doc then return nil, why end
    local titles = doc.titles
    if type(titles) ~= "table" then return nil, "pack_gap:" .. dir .. "profile.json .titles" end
    local title = titles[deps.title]
    if type(title) ~= "table" then
        return nil, "pack_gap:" .. dir .. "profile.json titles." .. deps.title
    end
    -- The reason is the pack's, read from where it records it; nothing here is invented.
    local function no_bag()
        local open = title.open
        local reason = (type(open) == "table" and type(open.bag) == "string")
            and open.bag or "the pack ships no bag fact and no reason for it"
        return nil, "pack_gap:" .. dir .. "profile.json titles." .. deps.title
            .. ".profile.bag -- open.bag: " .. reason
    end
    local prof = title.profile
    local bag = type(prof) == "table" and prof.bag or nil
    local sf = type(bag) == "table" and bag.slot_fields or nil
    local idf = type(sf) == "table" and sf.id or nil
    local qtf = type(sf) == "table" and sf.quantity or nil
    -- A JSON null decodes to a table, so shape is what tells a real fact from an absent one.
    if type(bag) ~= "table" or type(bag.ball_ids) ~= "table"
       or type(bag.array_id) ~= "number" or type(bag.balls_pocket_off) ~= "number"
       or type(bag.ball_slot_size) ~= "number" or type(bag.ball_slot_count) ~= "number"
       or type(idf) ~= "table" or type(idf.off) ~= "number" or type(idf.size) ~= "number"
       or type(qtf) ~= "table" or type(qtf.off) ~= "number" or type(qtf.size) ~= "number"
       or bag.ball_slot_count < 1 or bag.ball_slot_size < idf.size + qtf.size then
        return no_bag()
    end
    local balls = {}
    for _, id in ipairs(bag.ball_ids) do
        if type(id) == "number" then balls[id] = true end
    end
    if next(balls) == nil then return no_bag() end
    return function()
        -- The array is resolved ONCE per answer: a fresh save read per field would re-validate the
        -- whole array-header table for every slot, and a cached base would outlive a save rewrite.
        local at, rwhy = deps.save_array(bag.array_id)
        if not at then return nil, "bag array " .. tostring(bag.array_id) .. ": " .. tostring(rwhy) end
        for i = 0, bag.ball_slot_count - 1 do
            local slot = bag.balls_pocket_off + i * bag.ball_slot_size
            local id = at(slot + idf.off, idf.size)
            if id == nil then return nil, "bag slot " .. i .. " id unreadable" end
            if balls[id] then
                local qty = at(slot + qtf.off, qtf.size)
                if qty == nil then return nil, "bag slot " .. i .. " quantity unreadable" end
                if qty > 0 then return true end
            end
        end
        return false
    end
end

-- Only the producers that exist are put in the returned table, so a nil seam is ABSENT from the
-- client input rather than present-and-nil.
function Inputs.build(deps)
    local out, gaps = {}, {}
    for _, name in ipairs({ "area_of", "charmap", "has_pokeballs", "gift_area" }) do
        local value, why = Inputs[name](deps)
        if value ~= nil then
            out[name] = value
        else
            gaps[#gaps + 1] = { name = name, why = tostring(why or "pack_gap") }
            if deps.log then deps.log("[SLink-gen4] input " .. name .. " unavailable: " .. tostring(why)) end
        end
    end
    return out, gaps
end

return Inputs
