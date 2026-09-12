-- Exact server-prepared images under an existing command-scoped held permit.
-- Shared within Gen 1: schema/phase policy is supplied by a narrow wrapper.
-- The caller owns durable intents and fresh command/write/save authorization.
local Full=require("gen1_full_save")
local Layout=require("gen1_full_save_layout")
local Canonical=require("journal_document")
local M={}
local function same(a,b)return Canonical.encode(a)==Canonical.encode(b)end
function M.new(options,tags)
    assert(type(tags)=="table","generation-owned image schema tags required")
    local mem,variant=options.memory,options.variant
    local info=assert(Layout[variant]);local self={}
    local function point()assert(options.safe(),"owned held memorial checkpoint required");return Full.capture(mem,variant)end
    local function validate(body,intent)
        assert(intent.schema==tags.intent and intent.body_digest==options.sha(body),"memorial intent differs from command")
        assert(body.cmd==tags.command and type(body.payload)=="table","prepared memorial command required")
        local p=body.payload
        assert(p.schema==tags.delta and type(p.changes)=="table","compact prepared memorial delta required")
        if tags.unchanged_fields then for name in pairs(p.changes)do assert(name=="cart","initial save cannot change WRAM fields")end end
        assert(p.context_generation==options.owned().context_generation and p.final_sha1==gameinfo.getromhash():lower(),"memorial context differs")
        return p
    end
    local function transformed(before,p)
        local after={schema=before.schema,variant=variant,save_status=2,fields={},cart_hex=before.cart_hex}
        for name,value in pairs(before.fields)do after.fields[name]=value end
        for name,delta in pairs(p.changes)do
            assert(not tags.unchanged_fields or name=="cart","initial save cannot change WRAM fields")
            if name=="cart" then after.cart_hex=require("hex_delta").apply(before.cart_hex,delta)
            else assert(info.regions[name],"unknown memorial memory region");after.fields[name]=require("hex_delta").apply(before.fields[name],delta)end
        end
        assert(options.sha(after)==p.after_digest and after.cart_hex==Full.image(mem,after),"prepared memorial delta differs from exact saved poststate")
        if tags.unchanged_fields then assert(after.cart_hex==Full.image(mem,before),"initial save delta changes bytes outside source-defined copies")end
        return after
    end
    local function recover(current,p)
        assert(current.save_status==p.before_status or current.save_status==2,"foreign partial save status")
        local before={schema=current.schema,variant=current.variant,save_status=p.before_status,fields={},cart_hex=current.cart_hex}
        for name,value in pairs(current.fields)do before.fields[name]=value end
        for name,delta in pairs(p.changes)do
            if name=="cart"then before.cart_hex=require("hex_delta").recover_before(current.cart_hex,delta)
            else assert(info.regions[name],"unknown recovery memory region");before.fields[name]=require("hex_delta").recover_before(current.fields[name],delta)end
        end
        assert(options.sha(before)==p.before_digest,"partial memorial contains foreign data")
        return before
    end
    function self.phase(current,p)
        local fingerprint=options.sha(current)
        -- An unchanged prepared image still needs a file flush/readback permit.
        -- Match classify(), which treats equal pre/post digests as already applied.
        if fingerprint==p.after_digest then return tags.save_phase end
        if fingerprint==p.before_digest then return tags.command end
        recover(current,p);return tags.repair_phase
    end
    function self.prepare_host()
        if not self.provider then
            -- Host/path qualification is read-only and precedes any write grant.
            -- The retained provider requires a consumed permit for every flush.
            local constructing=true
            local ok,provider=pcall(require("platform_saveram").new,{profile="gambatte",path=options.saveram_path,directory=options.saveram_directory,
                authorize=function()return options.safe() and (constructing or options.permitted())end})
            constructing=false;assert(ok,provider);self.provider=provider
        end
    end
    function self.prepare(body,identity)
        if tags.observe and body.cmd==tags.observe then
            return {schema="rby-memorial-observe-intent-v1",body_digest=options.sha(body),point=point()}
        end
        local intent={schema=tags.intent,body_digest=options.sha(body)}
        local p=validate(body,intent);local current=point()
        local fingerprint=options.sha(current)
        if fingerprint~=p.before_digest and fingerprint~=p.after_digest then recover(current,p)end
        if fingerprint==p.before_digest then transformed(current,p)end
        self.prepare_host()
        return intent
    end
    function self.classify(body,intent)
        if tags.observe and body.cmd==tags.observe then
            assert(intent.schema=="rby-memorial-observe-intent-v1" and intent.body_digest==options.sha(body),"memorial observation intent differs")
            local current=point();assert(same(current,intent.point),"memorial observation changed")
            return "after",current
        end
        local p=validate(body,intent);local current=point()
        local fingerprint=options.sha(current)
        if fingerprint==p.after_digest then return "after",current end
        if fingerprint==p.before_digest then return "before",current end
        local ok=pcall(recover,current,p)
        if ok then return "before",current end
        return "diverged","partial memorial contains foreign data"
    end
    function self.apply(body,intent)
        local p=validate(body,intent);local before=point()
        local original=recover(before,p)
        local after=transformed(original,p)
        local frame=emu.framecount();local total_written=0
        local function guard()
            local safe,permitted=options.safe(),options.permitted()
            assert(safe and permitted and emu.framecount()==frame,"memorial authority changed during apply; bytes="..total_written.." safe="..tostring(safe).." permit="..tostring(permitted))
        end
        local function write(address,before,after,domain)
            local old,new=assert(mem.hexToBytes(before)),assert(mem.hexToBytes(after))
            assert(#old==#new,"prepared memory image size differs")
            local written=0
            for i,value in ipairs(new)do
                if old[i]~=value then
                    if written%64==0 then guard()end
                    memory.write_u8(address+i-1,value,domain);written=written+1;total_written=total_written+1
                end
            end
            guard()
        end
        self.retry_reason=nil
        local ok,why=pcall(function()
        guard()
        for _,name in ipairs({"name","main","sprites","box","party","tiles"})do
            local region=info.regions[name]
            assert(#before.fields[name]==region.length*2 and #after.fields[name]==region.length*2,"memorial region length differs")
            write(region.address,before.fields[name],after.fields[name],"System Bus")
        end
        write(0,before.cart_hex,after.cart_hex,"CartRAM")
        guard();memory.write_u8(info.status,2,"System Bus");guard()
        end)
        if not ok then
            -- Only an explainable prefix under the same physical hold may be
            -- retried. A fresh server permit is required before another byte.
            local current=point();assert(emu.framecount()==frame,"frame changed during partial memorial")
            recover(current,p);self.retry_reason=tostring(why);return false
        end
        return true
    end
    function self.receipt(body,intent,observed,identity)
        assert(same(point(),observed),"memorial readback changed")
        if tags.observe and body.cmd==tags.observe then
            local host=options.host.status();local owned=options.owned()
            return {schema="rby-memorial-observation-v1",command_id=identity.command_id,command_sequence=identity.command_sequence,
                context_generation=owned.context_generation,final_sha1=gameinfo.getromhash():lower(),point=observed,
                checkpoint=require("gen1_write_checkpoint").capture(mem.profile),
                host={owner_id=host.owner_id,capability_id=host.capability_id,process_id=host.process_id,
                      frame=emu.framecount(),held=host.physical_stop_verified==true}}
        end
        local p=validate(body,intent);assert(options.sha(observed)==p.after_digest,"complete memorial poststate required")
        local provider=assert(self.provider,"prepared save-file provider required")
        local file=provider:flush(observed.cart_hex)
        assert(same(point(),observed) and options.permitted(),"memorial changed during file flush")
        return {schema=tags.receipt,command_id=identity.command_id,command_sequence=identity.command_sequence,
            body_digest=options.sha(body),context_generation=p.context_generation,final_sha1=p.final_sha1,
            before_digest=p.before_digest,after=observed,file=file}
    end
    return self
end
return M
