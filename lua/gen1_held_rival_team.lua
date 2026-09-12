-- replace_rival_team: the partner party over the trainer party, at trainer-battle init.
-- Sub-executor of gen1_held_faint.lua (composed like storage/memorial); the permit, evidence
-- and phases stay there. Window and footprint: proposals/P5-rival-team-executor.md sections 2-4.
local JSON=require("json_codec")
local Codec=require("gen1_party_codec")
local ok,Data=pcall(require,"gen1_rival_team_checkpoint")
if not ok then
    local root=rawget(_G,"SLINK_ROOT") or os.getenv("SLINK_ROOT")
    Data=dofile((root and (root.."/") or "").."data/games/gen1_rby/gen1_rival_team_checkpoint.lua")
end
assert(Data.schema=="rby-battle-init-checkpoint-v1","unsupported battle-init checkpoint data schema")
local M={INTENT="rby-rival-team-intent-v1",RECEIPT="gen1-rival-team-receipt-v1",EVIDENCE="rby-held-rival-evidence-v1",
    MISSED_INTENT="rby-rival-team-missed-intent-v1",MISSED_RECEIPT="gen1-rival-team-missed-receipt-v1"}
local BAD="invalid complete rival payload; nothing written"

function M.handles(body)
    return type(body)=="table" and body.cmd=="replace_rival_team" and type(body.trainer_id)=="number"
        and type(body.blobs_hex)=="table"
end

local function hex_of(bytes)
    local out={}
    for i=1,#bytes do out[i]=string.format("%02X",bytes[i]) end
    return table.concat(out)
end

local function blobs_of(mem,body) -- lua/clients/gen1_rby_client.lua:340-355, unchanged
    local hexes=body.blobs_hex
    if type(hexes)~="table" or #hexes<1 or #hexes>6 then return nil,BAD end
    local blobs,count={},0
    for index,hex in pairs(hexes) do
        if type(index)~="number" or index%1~=0 or index<1 or index>#hexes
            or type(hex)~="string" or #hex~=132 or not hex:match("^%x+$") then return nil,BAD end
        count=count+1;blobs[index]=mem.hexToBytes(hex)
        if not blobs[index] or #blobs[index]~=66 then return nil,BAD end
    end
    if count~=#hexes then return nil,BAD end
    return blobs
end

-- The 67n+2 bytes writeEnemyParty writes, in write order (memory_gb.lua): per mon the 44-byte
-- struct, 11-byte OT, 11-byte nick (that is the blob itself) and the species-list byte; then the
-- 0xFF terminator and wEnemyPartyCount.
function M.expectedImageHex(blobs)
    local parts={}
    for i,blob in ipairs(blobs) do parts[i]=hex_of(blob)..string.format("%02X",blob[1]) end
    return table.concat(parts)..string.format("FF%02X",#blobs)
end

-- Every VBlank boundary with wIsInBattle==2 and wEnemyMonPartyPos==0xFF lies strictly between
-- ReadTrainer and the first send-out: pokered engine/battle/core.asm:6679-6692 sets both right
-- after the party is read, :139-156 scans and sends out with no DelayFrame between, and :1720 is
-- the first write of wEnemyMonPartyPos. The main thread must be halted in DelayFrame at the IRQ
-- vector exactly as the overworld checkpoint proves it (gen1_write_safety.lua); the caller word
-- is not pinned because the battle intro has many.
function M.check(profile,body,io)
    local ok,safe,reason=pcall(function()
        if type(profile)~="table" or profile.version~="gen1-battle-init-v1" then
            return false,"no verified battle-init profile"
        end
        if not M.handles(body) or body.trainer_id%1~=0 or body.trainer_id<=200 or body.trainer_id>255 then
            return false,"trainer opponent id required"
        end
        local domains={}
        for _,domain in pairs(io.domains()) do domains[domain]=true end
        if not domains.ROM or not domains["System Bus"] then return false,"ROM and System Bus domains are required" end
        local function byte(address,domain)
            if type(address)~="number" or address%1~=0 or address<0 or address>65535 then error("invalid checkpoint address") end
            local value=io.read_u8(address,domain or "System Bus")
            if type(value)~="number" or value%1~=0 or value<0 or value>255 then error("unavailable checkpoint byte") end
            return value
        end
        local function rom_matches(address,bytes)
            for i,value in ipairs(bytes) do
                if byte(address+i-1,"ROM")~=value then return false end
            end
            return true
        end
        local p=profile
        if not rom_matches(p.irq_vector,{0xC3,p.vblank_entry%256,math.floor(p.vblank_entry/256)})
            or not rom_matches(p.delay_frame,{0x3E,1,0xE0,p.vblank_flag%256,0x76,0xF0,p.vblank_flag%256,0xA7}) then
            return false,"cartridge checkpoint instructions differ"
        end
        if byte(p.is_in_battle)~=p.trainer_battle or byte(p.enemy_mon_party_pos)~=0xFF then
            return false,"not inside the trainer battle-init window"
        end
        local count=byte(p.enemy_party_count)
        if count<1 or count>6 or byte(p.cur_opponent)~=body.trainer_id then
            return false,"trainer party or opponent differs from the command"
        end
        if byte(p.link_state)~=p.link_none or byte(p.battle_type)~=0 then
            return false,"link or special battle owns the game"
        end
        local pc,sp=io.register("PC"),io.register("SP")
        if pc~=p.irq_vector or type(sp)~="number" or sp%1~=0 or sp<p.stack_min or sp+1>p.stack_end then
            return false,"CPU is outside the verified checkpoint"
        end
        if byte(sp)+256*byte(sp+1)~=p.delay_frame+5 or byte(p.vblank_flag)~=1 then
            return false,"main thread is not waiting in DelayFrame"
        end
        return true,"verified battle-init checkpoint"
    end)
    if not ok then return false,"checkpoint evidence unavailable: "..tostring(safe) end
    return safe,reason
end

-- Capture exactly the reads the predicate makes (the gen1_write_checkpoint.lua shape).
function M.capture(profile,body)
    local point={pc=emu.getregister("PC"),sp=emu.getregister("SP"),rom=JSON.object(),system=JSON.object()}
    local safe,reason=M.check(profile,body,{
        domains=function()return memory.getmemorydomainlist()end,
        register=function(name)return name=="PC" and point.pc or point.sp end,
        read_u8=function(address,domain)
            local value=memory.read_u8(address,domain);local field=domain=="ROM" and "rom" or "system"
            point[field][tostring(address)]=value;return value
        end})
    assert(safe,reason);return point
end

function M.new(o) -- o.memory (initProfile done), o.variant
    local mem=o.memory
    local profile=assert(Data.titles[o.variant],"battle-init checkpoint requires admitted Red, Blue or Yellow")
    local function live_io()
        return {domains=function()return memory.getmemorydomainlist()end,
            register=function(name)return emu.getregister(name)end,
            read_u8=function(address,domain)return memory.read_u8(address,domain)end}
    end
    local function image(n) -- readback of exactly the bytes a write of n mons touches, in write order
        local struct=mem.PARTY_STRUCT_SIZE;local bytes={}
        for i=1,n do
            for j=0,struct-1 do bytes[#bytes+1]=mem.read_u8(mem.ENEMY_BASE_ADDR+(i-1)*struct+j) end
            for j=0,10 do bytes[#bytes+1]=mem.read_u8(mem.ENEMY_OT_NAMES_ADDR+(i-1)*11+j) end
            for j=0,10 do bytes[#bytes+1]=mem.read_u8(mem.ENEMY_NICKS_ADDR+(i-1)*11+j) end
            bytes[#bytes+1]=mem.read_u8(mem.ENEMY_SPECIES_LIST_ADDR+(i-1))
        end
        bytes[#bytes+1]=mem.read_u8(mem.ENEMY_SPECIES_LIST_ADDR+n)
        local count=mem.read_u8(mem.ENEMY_COUNT_ADDR);bytes[#bytes+1]=count
        local species=JSON.array()
        for i=0,math.min(count,6) do species[i+1]=mem.read_u8(mem.ENEMY_SPECIES_LIST_ADDR+i) end
        return {count=count,species_list=species,image_hex=hex_of(bytes)}
    end
    local function validated(body,intent)
        local blobs,why=blobs_of(mem,body)
        if not blobs then return nil,why end
        if type(intent)~="table" or intent.schema~=M.INTENT or intent.trainer_id~=body.trainer_id or intent.n~=#blobs
            or type(intent.before)~="table" or type(intent.before.image_hex)~="string" then return nil,"rival intent changed" end
        return blobs
    end
    local self={}
    local function late(body)
        if not M.handles(body)then return false end
        local ok,point=pcall(function()return {battle=mem.read_u8(profile.is_in_battle),
            opponent=mem.read_u8(profile.cur_opponent),enemy_position=mem.read_u8(profile.enemy_mon_party_pos),
            frame=emu.framecount()}end)
        if not ok or type(point.frame)~="number"or point.frame%1~=0 or point.frame<0 then return false end
        local missed=point.battle~=profile.trainer_battle or point.opponent~=body.trainer_id or point.enemy_position~=0xFF
        return missed,point
    end
    function self.missed(body)return late(body)end
    function self.safe(body)return M.check(profile,body,live_io())end
    function self.checkpoint(body)return M.capture(profile,body)end
    function self.image(body)return image(#body.blobs_hex)end
    function self.prepare(body)
        local blobs,why=blobs_of(mem,body)
        if not blobs then return nil,why end
        local party,err=Codec.validateParty(blobs,o.variant)
        if not party then return nil,err.."; nothing written" end
        local alive=false
        for _,mon in ipairs(party) do if mon.hp>0 then alive=true end end
        -- StartBattle scans for the first living enemy with no exit (core.asm:139-150).
        if not alive then return nil,"rival party needs a living member; nothing written" end
        local missed,observed=late(body)
        if missed then return {schema=M.MISSED_INTENT,trainer_id=body.trainer_id,observed=observed}end
        return {schema=M.INTENT,trainer_id=body.trainer_id,n=#blobs,before=image(#blobs)}
    end
    function self.classify(body,intent)
        if type(intent)=="table"and intent.schema==M.MISSED_INTENT and intent.trainer_id==body.trainer_id
            and type(intent.observed)=="table"then return "after",intent.observed end
        local missed,observed=late(body)
        if missed then return "after",observed end
        local blobs,why=validated(body,intent)
        if not blobs then return "diverged",why end
        local now=image(#blobs)
        if now.image_hex==M.expectedImageHex(blobs) then return "after",now end
        if now.image_hex==intent.before.image_hex then return "before",now end
        return "diverged","enemy party changed before the swap"
    end
    function self.apply(body,intent)
        local blobs,why=validated(body,intent)
        if not blobs then error(why,0) end
        local written,reason=mem.writeEnemyParty(blobs)
        if not written then error(reason,0) end
    end
    function self.receipt(body,intent,observed)
        if type(intent)=="table"and intent.schema==M.MISSED_INTENT and intent.trainer_id==body.trainer_id
            and type(observed)=="table"then
            return {schema=M.MISSED_RECEIPT,trainer_id=body.trainer_id,observed=observed}
        end
        local missed,current=late(body)
        if missed and type(observed)=="table"and observed.battle==current.battle and observed.opponent==current.opponent
            and observed.enemy_position==current.enemy_position and observed.frame==current.frame then
            return {schema=M.MISSED_RECEIPT,trainer_id=body.trainer_id,observed=observed}
        end
        local blobs,why=validated(body,intent)
        if not blobs then return nil,why end
        if type(observed)~="table" or observed.image_hex~=M.expectedImageHex(blobs) or observed.count~=#blobs then
            return nil,"rival readback differs"
        end
        return {schema=M.RECEIPT,trainer_id=body.trainer_id,before=intent.before,after=observed}
    end
    return self
end
return M
