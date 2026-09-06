-- RR read-only metadata provider for shared client_session; no binding activation.
-- Caller supplies already decoded native descriptor and already verified
-- load-time bundle hashes. Loader attestation is not implemented here.
-- IO contract: read_u8(address), read_u32_le(address), getromhash(). No writes.
-- SB2 +0x0A is the save's own four-byte trainer ID, never the lead party OT.
local A={PROTOCOL="slink-rr-durable-v1",SCHEMA="slink-rr-metadata-v1"}
local SB2_PTR=0x0300500C -- canonical global, not an IRQ-code initial-base literal
local flags={
    minimal_grinding={address=0x0203B25A,mask=0x04},
    easy={address=0x0203B25A,mask=0x08},
    hardcore={address=0x0203B25A,mask=0x10},
    restricted={address=0x0203B25B,mask=0x10},
    species_randomizer={address=0x0203B17C,mask=0x01},
    learnset_randomizer={address=0x0203B17C,mask=0x02},
    ability_randomizer={address=0x0203B17C,mask=0x04},
    hard_mode_randomizer={address=0x0203B17B,mask=0x04},
}
local capability_bits={receipts_v2=1,payload_leases=2,storage_guard_v2=4,
    descriptor_v1=8,reservation_echo_v2=16}
local function uint(value,max,label)
    if type(value)~="number" or value~=value or value%1~=0 or value<0 or value>max then
        error("RR "..label.." is not an unsigned integer")
    end
    return value
end
local function is_hash(value,length)
    return type(value)=="string" and #value==length and value:match("^[0-9a-f]+$")~=nil
        and value~=string.rep("0",length)
end
local function hash(value,length,label)
    if not is_hash(value,length) then error("RR missing or invalid "..label) end
    return value
end
local function object_keys(value,keys,label)
    if type(value)~="table" then error("RR missing "..label) end
    for key,_ in pairs(keys) do if value[key]==nil then error("RR missing "..label.."."..key) end end
    for key,_ in pairs(value) do if not keys[key] then error("RR unexpected "..label.."."..tostring(key)) end end
end
local function descriptor(d)
    object_keys(d,{magic=true,descriptor_version=true,abi=true,build_id=true,layout_sha256=true,
        capability_mask=true,mailbox_address=true,mailbox_size=true,storage_guard=true,capabilities=true},"native_descriptor")
    if d.magic~="SLD2" or uint(d.descriptor_version,65535,"descriptor_version")~=1
        or uint(d.abi,65535,"ABI")~=2 or uint(d.capability_mask,4294967295,"capability_mask")~=31
        or uint(d.mailbox_size,65535,"mailbox_size")~=64
        or uint(d.storage_guard,65535,"storage_guard")~=0xA2 then error("RR missing/stale companion contract") end
    local address=uint(d.mailbox_address,4294967295,"mailbox_address")
    if address%4~=0 or address<0x02000000 or address+64>0x02040000 then error("RR invalid mailbox range") end
    object_keys(d.capabilities,capability_bits,"native capabilities")
    local caps={}
    for key,bit in pairs(capability_bits) do
        if type(d.capabilities[key])~="boolean" or d.capabilities[key]~=((d.capability_mask & bit)~=0) then
            error("RR capability differs from mask: "..key)
        end
        caps[key]=d.capabilities[key]
    end
    return {magic="SLD2",descriptor_version=1,abi=2,capability_mask=31,
        mailbox_address=address,mailbox_size=64,storage_guard=0xA2,capabilities=caps,
        build_id=hash(d.build_id,64,"native build ID"),layout_sha256=hash(d.layout_sha256,64,"native layout hash")}
end
local function snapshot(M,io)
    local pointer=uint(io.read_u32_le(SB2_PTR),4294967295,"SaveBlock2 pointer")
    if pointer%4~=0 or pointer<0x02000000 or pointer+14>0x02040000 then error("RR SaveBlock2 is not ready") end
    local bytes,chars,ended={}, {},false
    for i=0,7 do
        local byte=uint(io.read_u8(pointer+i),255,"trainer name byte")
        bytes[#bytes+1]=byte
        if not ended then
            if byte==255 then ended=true
            elseif i==7 then error("RR trainer name has no terminator")
            else
                local char=M.CHARSET[byte]
                if type(char)~="string" or char=="" then error("RR trainer name has an unknown character") end
                chars[#chars+1]=char
            end
        end
    end
    if not ended then error("RR trainer name is incomplete") end
    local name=table.concat(chars):gsub("%s+$","")
    if name=="" or not name:match("%S") or name:find("[%z\1-\31\127]") then error("RR trainer name is blank or invalid") end
    local trainer_id=0
    for i=0,3 do trainer_id=trainer_id+uint(io.read_u8(pointer+0xA+i),255,"trainer ID byte")*2^(8*i) end
    local mode_bytes={}
    for _,flag in pairs(flags) do
        if mode_bytes[flag.address]==nil then mode_bytes[flag.address]=uint(io.read_u8(flag.address),255,"mode byte") end
    end
    return {pointer=pointer,name=name,trainer_id=trainer_id,name_bytes=bytes,mode_bytes=mode_bytes}
end
local function same(a,b)
    if type(a)~=type(b) then return false end
    if type(a)~="table" then return a==b end
    for k,v in pairs(a) do if not same(v,b[k]) then return false end end
    for k,_ in pairs(b) do if a[k]==nil then return false end end
    return true
end
function A.read_metadata(M,io,decoded_descriptor,bundle_evidence)
    local function callable_candidate(value)
        local kind=type(value)
        -- Pinned BizHawk exposes registered Lua APIs as callable NLua userdata.
        -- This shape is not proof: the protected read below must execute them
        -- successfully and validate every returned byte/hash before publication.
        return kind=="function" or kind=="userdata"
    end
    local function read()
        if type(M)~="table" or M.profile_name~="radical_red" or M.CFRU_NO_ENCRYPT~=true
            or M.SB2_PTR_ADDR~=SB2_PTR or type(M.CHARSET)~="table" then error("RR memory profile is not ready") end
        if type(io)~="table" or not callable_candidate(io.read_u8) or not callable_candidate(io.read_u32_le)
            or not callable_candidate(io.getromhash) then error("RR read-only IO provider is incomplete") end
        local native=descriptor(decoded_descriptor)
        object_keys(bundle_evidence,{client_bundle_sha256=true,data_bundle_sha256=true},"load-time bundle evidence")
        local bundles={client_bundle_sha256=hash(bundle_evidence.client_bundle_sha256,64,"client bundle hash"),
            data_bundle_sha256=hash(bundle_evidence.data_bundle_sha256,64,"data bundle hash")}
        local raw_hash=io.getromhash()
        if type(raw_hash)~="string" then error("RR loaded ROM hash is missing") end
        local loaded_hash=hash(raw_hash:lower():gsub("^sha1:",""),40,"loaded ROM SHA-1")
        local first=snapshot(M,io)
        local second=snapshot(M,io)
        if not same(first,second) then error("RR save or mode changed while reading admission metadata") end
        local final_hash=io.getromhash()
        if type(final_hash)~="string" or final_hash:lower():gsub("^sha1:","")~=loaded_hash then
            error("RR loaded ROM changed while reading admission metadata")
        end
        local actual_flags={}
        for name,flag in pairs(flags) do actual_flags[name]=(first.mode_bytes[flag.address] & flag.mask)~=0 end
        return {rr_metadata={schema=A.SCHEMA,loaded_rom_sha1=loaded_hash,
            trainer_id=first.trainer_id,trainer_name=first.name,native_descriptor=native,
            bundle_hashes=bundles,mode_flags=actual_flags}}
    end
    local ok,report=pcall(read)
    if not ok then return nil,tostring(report) end
    return report,nil
end
function A.metadata_matches(admission,report)
    if type(admission)~="table" or type(report)~="table" or type(report.rr_metadata)~="table" then return false end
    local m=report.rr_metadata
    return admission.game_id=="gen3_frlge" and admission.rom_type=="firered_rr"
        and admission.scope=="metadata_only_no_physical_readiness"
        and is_hash(admission.rom_sha256,64) and is_hash(admission.contract_digest,64)
        and same(admission.rr_metadata,m)
        and type(admission.save_identity)=="table"
        and admission.save_identity.ot_id==string.format("%08X",m.trainer_id)
        and admission.save_identity.trainer_name==m.trainer_name
        and admission.mode==(m.mode_flags.minimal_grinding and "default_mgm_on" or "default_mgm_off")
end
return A
