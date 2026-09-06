-- RBY admission/response boundary. All APIs are read-only with respect to the ROM.
-- This is session-local sequencing; a durable semantic outbox is still required.
local profiles = require("gen1_admission_profiles").profiles
local M = {PROTOCOL="slink-gen1-session-v1"}
local fields = {"variant", "final_rom_sha1", "content_profile_schema", "content_profile_hash",
                "patch_version", "party_codec"}
local function same_metadata(a,b)
    for _,key in ipairs(fields) do if a[key]~=b[key] then return false end end
    if type(a.capabilities)~="table" then return false end
    local count=0
    for key,value in pairs(a.capabilities) do
        if type(value)~="boolean" or b.capabilities[key]~=value then return false end
        count=count+1
    end
    return count==3
end

M.new_nonce = require("platform_identity").new_nonce

function M.metadata(variant)
    local ok,hash=pcall(function() return gameinfo.getromhash():lower() end)
    local profile=profiles[variant]
    if not ok or type(hash)~="string" or #hash~=40 or not hash:match("^[0-9a-f]+$") then
        return nil,"complete ROM SHA-1 unavailable"
    end
    if not profile or profile.final_rom_sha1~=hash then
        return nil,"ROM requires a verified full semantic scan"
    end
    return {variant=variant,final_rom_sha1=hash,content_profile_schema=profile.schema,
        content_profile_hash=profile.content_profile_hash,patch_version=profile.patch_version,
        party_codec=profile.party_codec,capabilities={panel=false,sfx=false,pc_trade=false}}
end

function M.new(variant,player)
    return require("client_session").new({variant=variant,player=player,protocol=M.PROTOCOL,
        read_metadata=function() return M.metadata(variant) end,
        new_nonce=function() return M.new_nonce() end,metadata_matches=same_metadata})
end
return M
