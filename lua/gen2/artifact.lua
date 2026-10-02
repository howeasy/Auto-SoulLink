--[[
  lua/gen2/artifact.lua -- the executed-ROM view of one admitted Gen 2 artifact
  (docs/gen2/OVERLAY_ADMISSION.md D2/D3).

  A clean cartridge executes the pack's own facts. An overlay cartridge shares the pack's RAM
  facts but executes different bytes, so its sites, checkpoint anchors and ROM-valued profile
  coordinates come from the generated sidecar data/games/gen2_<t>/overlay/binding.json,
  pinned by the catalog row's binding_sha256. There is no fallback from overlay to clean.

  view = {kind, rom_sha1, base_sha1, binding_sha256, sites, checkpoint, anchors, profile_rom}
]]
local Artifact = {}

-- Artifact.view(root, json, data, title, row) -> view | nil, why
-- data: the loaded pack (entry.lua load_pack); row: the admitted catalog row.
function Artifact.view(root, json, data, title, row)
    if type(row) ~= "table" then return nil, "artifact row required" end
    if row.kind == "clean" then
        local sites = data.sites.titles[title] and data.sites.titles[title].sites
        local checkpoint = data.checkpoint.titles[title]
        if not sites or not checkpoint then return nil, "clean pack facts missing for " .. tostring(title) end
        return {kind="clean", rom_sha1=row.sha1, base_sha1=row.sha1, binding_sha256=nil,
                sites=sites, checkpoint=checkpoint, anchors=nil, profile_rom=nil}
    end
    if row.kind == "overlay" then
        -- Stream R fills this in: load overlay/binding.json, check sha256 == row.binding_sha256,
        -- check rom_sha1/base_sha1 against the row, return the overlay execution view.
        return nil, "overlay execution binding not implemented"
    end
    return nil, "unsupported Gen 2 artifact kind " .. tostring(row.kind)
end

return Artifact
