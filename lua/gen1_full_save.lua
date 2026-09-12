-- Source-defined SaveGameData copies from one owned, held WRAM snapshot.
-- No emulated frame may occur during these writes. The caller supplies durable
-- intent storage, exact operation authority and the qualified save-file provider.
local JSON=require("json_codec")
local Canonical=require("journal_document")
local Layout=require("gen1_full_save_layout")
local Preparation=require("gen1_trade_preparation")
local M={POINT="rby-full-save-point-v1",INTENT="rby-full-save-intent-v1"}
local function same(a,b)return assert(Canonical.encode(a))==assert(Canonical.encode(b))end
local function read(mem,address,count,domain)
    local result={};for i=0,count-1 do result[#result+1]=memory.read_u8(address+i,domain or "System Bus")end
    return mem.bytesToHex(result)
end
function M.capture(mem,variant)
    local info=assert(Layout[variant]);local fields={}
    for name,region in pairs(info.regions)do fields[name]=read(mem,region.address,region.length)end
    return {schema=M.POINT,variant=variant,cart_hex=read(mem,0,0x8000,"CartRAM"),fields=fields,
        save_status=memory.read_u8(info.status,"System Bus")}
end
function M.image(mem,point)
    assert(point.schema==M.POINT,"full-save point required")
    local info=assert(Layout[point.variant]);local values=assert(mem.hexToBytes(point.cart_hex))
    assert(#values==0x8000,"complete CartRAM image required")
    local count=0
    for name in pairs(point.fields)do assert(info.regions[name],"unexpected save field");count=count+1 end
    assert(count==6,"complete source-defined save fields required")
    for name,region in pairs(info.regions)do
        local raw=assert(mem.hexToBytes(point.fields[name]));assert(#raw==region.length,"save field length differs")
        for i,value in ipairs(raw)do values[region.target+i]=value end
    end
    local sum=0;for p=info.start,info["end"]-1 do sum=(sum+values[p+1])%256 end
    values[info.checksum+1]=255-sum
    return mem.bytesToHex(values)
end
function M.new(options)
    local mem,manifest=options.memory,options.manifest
    local info=assert(Layout[manifest.variant]);local self={}
    local function sha(value)return options.sha256(assert(Canonical.encode(value)))end
    local function guard(action,body,identity,intent)
        assert(options.authorize(action,body,identity)==true,"owned full-save authority required")
        assert(gameinfo.getromhash():lower()==manifest.final_sha1 and mem.isPartyWriteSafe(),"full save requires its held overworld")
        assert(body.cmd=="native_trade_prepare" and body.player==options.player,"paired full-save preparation required")
        if intent then
            assert(intent.schema==M.INTENT and intent.command_id==identity.command_id
                and intent.command_sequence==identity.command_sequence and intent.body_digest==sha(body)
                and intent.context_generation==options.context_generation() and intent.image_hex==M.image(mem,intent.point),
                "full-save intent/context changed")
        end
    end
    local function observe(body,intent,identity)
        guard("observe_full_save",body,identity,intent)
        local point=M.capture(mem,manifest.variant)
        assert(same(point.fields,intent.point.fields),"full-save WRAM changed after preparation")
        local before=point.cart_hex==intent.point.cart_hex and point.save_status==intent.point.save_status
        local after=point.cart_hex==intent.image_hex and point.save_status==2
        assert(before or after,"partial or foreign full-save state requires recovery")
        return point,before,after
    end
    function self.prepare(body,identity)
        guard("observe_full_save",body,identity)
        -- Use the existing complete party/box/context validator before proposing
        -- any full-save mutation. Its returned intent is read-only.
        options.preparation.prepare(body,identity)
        local point=M.capture(mem,manifest.variant)
        return {schema=M.INTENT,command_id=identity.command_id,command_sequence=identity.command_sequence,
            body_digest=sha(body),context_generation=options.context_generation(),point=point,
            checkpoint=Preparation.capture(mem,manifest),image_hex=M.image(mem,point)}
    end
    function self.classify(body,intent,identity)
        local point,_,after=observe(body,intent,identity)
        -- Even an already identical image needs an independently verified save
        -- window before its file receipt can advance paired preparation.
        if after then
            if options.authorize("full_save_ready",body,identity)==true then return "after",point end
            return "armed",{schema="rby-full-save-awaiting-proof-v1",command_id=identity.command_id}
        end
        return "before",point
    end
    function self.apply(body,intent,identity)
        guard("arm_full_save",body,identity,intent)
        local _,before=observe(body,intent,identity);assert(before,"full-save preimage differs")
        local frame=emu.framecount();local values=assert(mem.hexToBytes(intent.image_hex))
        memory.write_u8(info.status,2,"System Bus")
        for p=info.start,info["end"]-1 do
            if (p-info.start)%128==0 then guard("arm_full_save",body,identity);assert(emu.framecount()==frame)end
            memory.write_u8(p,values[p+1],"CartRAM")
        end
        -- The cartridge also publishes the checksum after the complete data.
        memory.write_u8(info.checksum,values[info.checksum+1],"CartRAM")
        assert(emu.framecount()==frame,"frame advanced during full save")
    end
    function self.receipt(body,intent,observed,identity)
        local phase,point=self.classify(body,intent,identity)
        assert(phase=="after" and same(point,observed),"full-save readback differs")
        local file=options.persist_save(intent.image_hex,identity,intent)
        observe(body,intent,identity)
        return {schema="rby-full-save-receipt-v1",command_id=identity.command_id,command_sequence=identity.command_sequence,
            context_generation=intent.context_generation,final_sha1=manifest.final_sha1,
            point=intent.point,image_hex=intent.image_hex,file=file}
    end
    function self.window_evidence(body,intent,identity)
        local point,before,after=observe(body,intent,identity)
        return {phase="full_save",intent=intent,current=point,before=before,after=after}
    end
    function self.verify(receipt)
        local point=M.capture(mem,manifest.variant)
        return receipt.context_generation==options.context_generation() and receipt.final_sha1==manifest.final_sha1
            and point.cart_hex==receipt.image_hex and point.save_status==2 and same(point.fields,receipt.point.fields)
    end
    return self
end
return M
