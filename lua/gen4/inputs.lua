-- lua/gen4/inputs.lua -- producers for the rewritten Gen 4 client's three OPTIONAL inputs
-- (lua/gen4/client.lua p.area_of / p.charmap / p.has_pokeballs).
--
-- Rule: a producer exists only where the PACK carries the fact. This file names no game address,
-- no struct offset, no item id and no char code. A fact the pack does not ship yields
-- (nil, named reason) so the client's seam stays UNWIRED rather than guessing -- the client
-- already treats every one of the three as optional (client.lua area_now/trainer_fields/hello_fields).
--
--   Inputs.area_of(deps)       -> function(map_id, loc) -> area_id, loc_name | nil, reason
--   Inputs.charmap(deps)       -> { [code] = text }              | nil, reason
--   Inputs.has_pokeballs(deps) -> function() -> bool             | nil, reason
--   Inputs.build(deps)         -> { area_of = ..., charmap = ..., has_pokeballs = ... }, gaps[]
--
-- deps = { root, json, pack_profile (repo-relative profile.json path, from Entry.PACKS), log }
--
-- Facts, and where each one comes from:
--   area_of   data/games/<pack>/area_map.json  `.maps[map_id]`  -> area_id or JSON null
--             (tools/gen_gen4_area_map.py, pret/pokeheartgold@ad7a3afa; null = not a Soul Link
--             place, the file's `unmapped_maps` explains each), and
--             data/games/<pack>/locations.json `.locations[map_id].name` -> loc_name.
--             SHIPPED for gen4_hgss. gen4_hge ships no area map, so its producer refuses.
--   charmap   data/games/<pack>/charmap.json `.glyphs[dec_code]` -> text; the pack-directory
--             convention data/games/gen1_purergb/charmap.json already uses. NOT YET GENERATED
--             for Gen 4 (tools/gen_gen4_names.py parses charmap.txt but emits only names), so the
--             producer refuses today rather than borrowing the Python oracle's table.
--   has_pokeballs  REFUSED: needs a bag fact the pack does not carry (see Inputs.GAPS).
local Inputs = {}

-- The exact pack fact each refusal is waiting on. Names the key, not a value: nothing here is a
-- guessed address, and Inputs.build reports every entry as a startup gap so the omission is
-- visible on the console instead of silent.
Inputs.GAPS = {
    charmap = "pack_gap:data/games/<pack>/charmap.json .glyphs -- the u16 code->text table "
        .. "(tools/gen_gen4_names.py reads charmap.txt but emits only names)",
    has_pokeballs = "pack_gap:profile.bag -- { balls_pocket_off, ball_slot_size, ball_slot_count, "
        .. "ball_ids } for the save-array bag, array_id already named by save.array_ids.bag "
        .. "(pret/pokeheartgold@ad7a3afa src/bag.c; kwsch PlayerBag4HGSS.cs)",
}

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

-- u16 charcode -> display text. Refuses until the pack ships charmap.json.
function Inputs.charmap(deps)
    local dir, why = pack_dir(deps)
    if not dir then return nil, why end
    local doc
    doc, why = load_optional(deps.json, deps.root .. "/" .. dir .. "charmap.json")
    if not doc then return nil, why .. " (" .. Inputs.GAPS.charmap .. ")" end
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

-- Refuses: the save-array bag has no pocket geometry in either Gen 4 pack (only the array id).
-- Not a stub -- naming the fact is the whole contract, and Inputs.build reports it as a gap.
function Inputs.has_pokeballs(_deps)
    return nil, Inputs.GAPS.has_pokeballs
end

-- Only the producers that exist are put in the returned table, so a nil seam is ABSENT from the
-- client input rather than present-and-nil.
function Inputs.build(deps)
    local out, gaps = {}, {}
    for _, name in ipairs({ "area_of", "charmap", "has_pokeballs" }) do
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
