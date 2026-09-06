-- Read-only cartridge snapshots used by durable command preparation/readback.
local JSON=require("json_codec")
local Codec=require("gen1_party_codec")
local M={SCHEMA="gen1-party-readback-v1",RECEIPT_SCHEMA="gen1-force-faint-receipt-v1"}
local fields={schema=true,variant=true,save_id=true,save_name=true,party_count=true,party=true,
    species_list=true,battle_flag=true,active_slot=true,battle_hp=true}
local function integer(value,low,high)
    return type(value)=="number" and value%1==0 and value>=low and value<=high
end
local function raw_hex(hex)
    if type(hex)~="string" or #hex~=132 or not hex:match("^[0-9A-F]+$") then
        return nil,"readback needs canonical full party hex"
    end
    local raw={}
    for i=1,132,2 do raw[#raw+1]=tonumber(hex:sub(i,i+1),16) end
    return raw
end

function M.validate_snapshot(snapshot,variant)
    if (variant~="red" and variant~="blue" and variant~="yellow") or type(snapshot)~="table"
        or snapshot.schema~=M.SCHEMA or snapshot.variant~=variant then return nil,"readback schema/variant mismatch" end
    for name in pairs(snapshot) do if not fields[name] then return nil,"unknown readback field" end end
    for name in pairs(fields) do if snapshot[name]==nil then return nil,"missing readback field" end end
    if type(snapshot.save_id)~="string" or #snapshot.save_id~=4 or not snapshot.save_id:match("^[0-9A-F]+$") then
        return nil,"readback needs the save player ID"
    end
    if type(snapshot.save_name)~="string" or #snapshot.save_name<1 or #snapshot.save_name>40
        or snapshot.save_name:find("[%z\1-\31]") then return nil,"readback needs the save name" end
    local count=snapshot.party_count
    if not integer(count,1,6) or JSON.kind(snapshot.party)~="array" or #snapshot.party~=count
        or JSON.kind(snapshot.species_list)~="array" or #snapshot.species_list~=count+1 then
        return nil,"readback needs exact party count, blobs and species list"
    end
    local blobs={}
    for _,hex in ipairs(snapshot.party) do
        local raw,reason=raw_hex(hex)
        if not raw then return nil,reason end
        blobs[#blobs+1]=raw
    end
    local party,reason=Codec.validateParty(blobs,variant,snapshot.species_list,{})
    if not party then return nil,reason end
    if not integer(snapshot.battle_flag,0,2) then return nil,"invalid battle flag" end
    if snapshot.battle_flag~=0 then
        if not integer(snapshot.active_slot,0,count-1) or not integer(snapshot.battle_hp,0,999) then
            return nil,"invalid active battler"
        end
    elseif snapshot.active_slot~=JSON.null or snapshot.battle_hp~=JSON.null then
        return nil,"overworld readback must not assert an active battler"
    end
    return party
end

function M.party_snapshot(memory,variant)
    local count=memory.getPartyCount()
    if type(count)~="number" or count%1~=0 or count<1 or count>6 then return nil,"invalid party count" end
    local blobs,encoded,list={},{},{}
    for slot=0,count-1 do
        local blob=memory.readPartyBlob(slot)
        if not blob then return nil,"party blob unavailable" end
        blobs[#blobs+1]=blob
        encoded[#encoded+1]=memory.bytesToHex(blob)
        list[#list+1]=memory.read_u8(memory.PARTY_SPECIES_ADDR+slot)
    end
    list[#list+1]=memory.read_u8(memory.PARTY_SPECIES_ADDR+count)
    local valid,reason=Codec.validateParty(blobs,variant,list,{})
    if not valid then return nil,reason end
    local battle=memory.read_u8(memory.BATTLE_FLAG_ADDR)
    if battle~=0 and battle~=1 and battle~=2 then return nil,"invalid battle context" end
    local active,hp=JSON.null,JSON.null
    if battle~=0 then
        active=memory.getActivePartySlot()
        if type(active)~="number" or active%1~=0 or active<0 or active>=count then return nil,"invalid active slot" end
        hp=memory.read_u16_be(memory.BATTLE_MON_HP_ADDR)
        if hp<0 or hp>999 then return nil,"invalid battle HP" end
    end
    local snapshot={schema=M.SCHEMA,variant=variant,save_id=string.format("%04X",memory.readPlayerId()),
        save_name=memory.readPlayerName(),party_count=count,party=JSON.array(encoded),
        species_list=JSON.array(list),battle_flag=battle,active_slot=active,battle_hp=hp}
    local party,why=M.validate_snapshot(snapshot,variant)
    if not party then return nil,why end
    return snapshot
end

function M.force_faint_expected(command,before)
    if type(command)~="table" or command.cmd~="force_faint" or type(before)~="table" then
        return nil,"force-faint command and snapshot required"
    end
    local party,reason=M.validate_snapshot(before,before.variant)
    if not party then return nil,reason end
    local after=assert(JSON.decode(assert(JSON.encode(before))))
    local target
    for index,mon in ipairs(party) do
        if mon.key==command.key then
            if target then return nil,"duplicate force-faint key" end
            target=index
            local hex=before.party[index]
            after.party[index]=hex:sub(1,2).."0000"..hex:sub(7)
        end
    end
    if not target then return nil,"force-faint key is not in the party" end
    if before.battle_flag~=0 and before.active_slot==target-1 then after.battle_hp=0 end
    return after,target-1
end
return M
