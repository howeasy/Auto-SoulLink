--[[
  lua/gen2/artifact.lua -- the executed-ROM view of one admitted Gen 2 artifact
  (docs/gen2/OVERLAY_ADMISSION.md D2/D3).

  A clean cartridge executes the pack's own facts. An overlay cartridge shares the pack's RAM
  facts but executes different bytes, so its sites, checkpoint anchors and ROM-valued profile
  coordinates come from the generated sidecar data/games/gen2_<t>/overlay/binding.json,
  pinned by the catalog row's binding_sha256. There is no fallback from overlay to clean.

  view = {kind, rom_sha1, base_sha1, binding_sha256, sites, checkpoint, anchors, profile_rom, substitutions}
]]
local Artifact = {}

local module_dir = assert(debug.getinfo(1, "S").source:match("^@(.+[/\\])[^/\\]+$"))
local Admission = dofile(module_dir .. "../admission.lua")
local function digest(value, n)
    return type(value) == "string" and #value == n and value:match("^%x+$") ~= nil
end

-- Artifact.view(root, json, data, title, row) -> view | nil, why
-- data: the loaded pack (entry.lua load_pack); row: the admitted catalog row.
function Artifact.view(root, json, data, title, row)
    if type(row) ~= "table" then return nil, "artifact row required" end
    if row.kind == "clean" then
        local sites = data.sites.titles[title] and data.sites.titles[title].sites
        local checkpoint = data.checkpoint.titles[title]
        if not sites or not checkpoint then return nil, "clean pack facts missing for " .. tostring(title) end
        local anchors, ids = {}, {}
        for id in pairs(data.area_map or {}) do ids[#ids + 1] = id end
        table.sort(ids)
        for _, id in ipairs(ids) do
            local source = data.area_map[id].source
            if not source then return nil, "clean map header source missing" end
            anchors[#anchors + 1] = {offset=source.header_flat, hex=source.header_hex}
        end
        return {kind="clean", rom_sha1=row.sha1, base_sha1=row.sha1, binding_sha256=nil,
                sites=sites, checkpoint=checkpoint, anchors=anchors, profile_rom=nil}
    end
    if row.kind == "overlay" then
        local ok, result = pcall(function()
            assert(digest(row.binding_sha256, 64), "overlay binding_sha256 required")
            assert(digest(row.sha1, 40) and digest(row.base_sha1, 40), "overlay ROM/base sha1 required")
            assert(({crystal=true, gold=true, silver=true})[title], "unsupported binding title")
            local path = root .. "/data/games/gen2_" .. title .. "/overlay/binding.json"
            local file = assert(io.open(path, "rb"), "overlay binding sidecar missing: " .. path)
            local raw = file:read("a")
            file:close()
            assert(type(raw) == "string", "overlay binding sidecar unreadable")
            -- Committed generated text is LF; autocrlf is not a different binding.
            raw = raw:gsub("\r\n", "\n")
            assert(Admission.sha256(function(i) return raw:byte(i + 1) end, #raw) == row.binding_sha256,
                   "overlay binding sha256 differs")
            local binding = assert(json.decode(raw, {items=1000000}), "overlay binding JSON malformed")
            assert(binding.schema == "gen2-overlay-binding-v1" and binding.kind == "overlay"
                   and binding.title == title, "overlay binding schema/title/kind differs")
            assert(binding.rom_sha1 == row.sha1 and binding.base_sha1 == row.base_sha1,
                   "overlay binding ROM/base sha1 differs")
            local base = data.profile and data.profile.titles and data.profile.titles[title]
            assert(base and base.rom_sha1 == binding.base_sha1, "overlay binding base differs from clean facts")
            assert(type(binding.sites) == "table" and type(binding.checkpoint) == "table"
                   and type(binding.header_anchors) == "table" and type(binding.profile_rom) == "table",
                   "overlay binding execution facts missing")
            return {kind="overlay", rom_sha1=binding.rom_sha1, base_sha1=binding.base_sha1,
                    binding_sha256=row.binding_sha256, sites=binding.sites, checkpoint=binding.checkpoint,
                    anchors=binding.header_anchors, profile_rom=binding.profile_rom,
                    -- the companion's own same-size code edits (entry.lua companion_anchors, rand_overlay)
                    substitutions=binding.builder_substitutions}
        end)
        if not ok then return nil, tostring(result) end
        return result
    end
    return nil, "unsupported Gen 2 artifact kind " .. tostring(row.kind)
end

return Artifact
