-- Exact installed artifact selection for durable RBY metadata. No effect authority.
local Clean=require("gen1_session")
local Catalog=require("gen1_companion_profiles")
local JSON=require("json_codec")
local M={}
function M.metadata(variant,prepared)
    if variant~="red"and variant~="blue"and variant~="yellow"then return nil,"RBY variant required"end
    local clean=Clean.metadata(variant)
    if clean then return clean end
    local ok,hash=pcall(function()return gameinfo.getromhash():lower()end)
    if not ok or type(hash)~="string" or #hash~=40 or not hash:match("^[0-9a-f]+$")then
        return nil,"complete ROM SHA-1 unavailable"
    end
    if type(prepared)=="table"and prepared.content_profile_schema=="gen1-rby-scanned-companion-content-v1"then
        local fields={variant=true,final_rom_sha1=true,content_profile_schema=true,content_profile_hash=true,
            patch_version=true,party_codec=true,capabilities=true}
        for key in pairs(prepared)do if not fields[key]then return nil,"unexpected prepared cartridge field"end end
        local caps=prepared.capabilities
        if prepared.variant~=variant or prepared.final_rom_sha1~=hash or prepared.patch_version~=3
            or prepared.party_codec~="gen1-rby-party-v1"or type(prepared.content_profile_hash)~="string"
            or #prepared.content_profile_hash~=64 or not prepared.content_profile_hash:match("^[0-9a-f]+$")
            or type(caps)~="table"or caps.panel~=(variant~="yellow")or caps.sfx~=false or caps.pc_trade~=true then
            return nil,"loaded cartridge differs from the prepared artifact"
        end
        for key in pairs(caps)do if key~="panel"and key~="sfx"and key~="pc_trade"then return nil,"unexpected prepared capability"end end
        return assert(JSON.decode(assert(JSON.encode(prepared))))
    end
    local profile=Catalog.profiles and Catalog.profiles[variant]
    if Catalog.schema~="gen1-rby-canonical-companion-catalog-v1" or not profile
        or profile.schema~="gen1-rby-canonical-companion-content-v1" or profile.variant~=variant
        or profile.final_rom_sha1~=hash or profile.patch_version~=3
        or profile.capabilities.panel~=(variant~="yellow") or profile.capabilities.sfx~=false
        or profile.capabilities.pc_trade~=true or profile.manifest.runtime_ready~=false then
        return nil,"ROM requires a verified complete artifact profile"
    end
    return {variant=variant,final_rom_sha1=hash,content_profile_schema=profile.schema,
        content_profile_hash=profile.content_profile_hash,patch_version=profile.patch_version,
        party_codec=profile.party_codec,capabilities={panel=variant~="yellow",sfx=false,pc_trade=true}}
end
return M
