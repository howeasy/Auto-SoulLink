-- Explicit Nintendo DS (ARM9 system bus) bus-exec binding; the NDS sibling of
-- lua/gb_hook_binding.lua with the same API. No title facts, addresses, domain, register
-- or pipeline-offset defaults: all of it comes from `config` (the pack + platform probe).
--
-- Site (pack row + id): {id, image="arm9"|"ov<N>", overlay_id (overlay sites), address,
--   mode="thumb"|"arm", extent, register_hex (full pin, `extent` bytes), fire_hex (8 hex digits
--   = LE u32 of register_hex[1..4]), phase}.
-- Config: bus_domain, pc_register, pc_offset={thumb=,arm=} (PC reads ahead of the fetched
--   instruction), overlay_table (pack: address,regions,per_region,entry_size,id_off,active_off),
--   overlays (pack: [tostring(id)]={ram,size}).
--
-- Fire-time order (PLAN 4.2), the registry capture calls context(site, accept):
--   1. the site's OWN overlay must be active, else return nil (another overlay shares the RAM);
--   2. accept (optional binder filter, a drop never latches);
--   3. shared residency contract re-reads the full pin (one range read per accepted fire);
--   4. callback address and ARM9 PC must match the site;
--   5. the callback's unsigned `val` word must equal fire_hex. A mismatch while the owning
--      overlay is active asserts, which the registry latches: never a silent drop.
-- The callback's (addr,val,flags) are captured by register()'s wrapper for the duration of
-- that one callback, so context keeps the GB `context(site, accept)` signature.
-- Calling context outside a callback asserts.
local here=assert(debug.getinfo(1,"S").source:match("^@(.*[/\\])"),"NDS binding file path required")
local RC=dofile(here.."residency_contract.lua")
local NDS = {}
local NULL_GUID = "00000000-0000-0000-0000-000000000000"
local function integer(v,low,high) return type(v)=="number" and v==math.floor(v) and v>=low and v<=high end
local function callable(v) return type(v)=="function" or type(v)=="userdata" end
local function copy(t)
    if type(t)~="table" then return t end
    assert(getmetatable(t)==nil,"plain site required")
    local out={};for k,v in pairs(t) do out[k]=copy(v) end;return out
end
-- Callback words arrive signed or unsigned; normalise to the unsigned u32.
local function u32(v)
    assert(integer(v,-2147483648,4294967295),"u32 value required")
    return v & 0xFFFFFFFF
end

-- The one residency reader: is overlay `ovy` active in sOverlayRegions[MAIN][0..per_region-1]?
-- `domain` is passed through to io.read_u32 (explicit per binding; the 3-argument form is the
-- PLAN signature for callers whose io already defaults it).
function NDS.resident(io,tbl,ovy,domain)
    assert(type(tbl)=="table" and tbl.regions==3 and tbl.per_region==8 and tbl.entry_size==8,"overlay table geometry")
    assert(integer(tbl.address,0,0xFFFFFFFF) and integer(tbl.id_off,0,4) and integer(tbl.active_off,0,4),"overlay table fields")
    assert(integer(ovy,0,0xFFFF),"overlay id")
    for i=0,tbl.per_region-1 do
        local p=tbl.address+i*tbl.entry_size
        local active=io.read_u32(p+tbl.active_off,domain)
        assert(integer(active,-2147483648,4294967295),"overlay table unreadable")
        if u32(active)~=0 and u32(io.read_u32(p+tbl.id_off,domain))==ovy then return true end
    end
    return false
end

local function pin_matches(io,address,hex,domain)
    local want={}
    for i=1,#hex,2 do want[#want+1]=tonumber(hex:sub(i,i+1),16) end
    local got=io.read_range(address,#want,domain)
    assert(type(got)=="table" and getmetatable(got)==nil,"registration bytes unreadable")
    for i=1,#want do
        local v=got[i]
        if not integer(v,0,255) or v~=want[i] then return false end
    end
    return true
end

function NDS.new(io,config)
    assert(type(io)=="table" and type(config)=="table","explicit NDS io/config required")
    for _,name in ipairs({"read_u32","read_range","register","framecount","on_bus_exec","unregister"}) do
        assert(callable(io[name]),"NDS io."..name.." required")
    end
    local c=copy(config)
    for _,name in ipairs({"bus_domain","pc_register"}) do
        assert(type(c[name])=="string" and c[name]~="","explicit NDS "..name.." required")
    end
    assert(type(c.pc_offset)=="table" and integer(c.pc_offset.thumb,0,16) and integer(c.pc_offset.arm,0,16),"explicit NDS pc_offset {thumb,arm} required")
    assert(type(c.overlay_table)=="table" and type(c.overlays)=="table","explicit NDS overlay_table/overlays required")
    local tbl=c.overlay_table
    local strategy={}
    function strategy.entries(read)
        local rows={}
        for region=0,tbl.regions-1 do
            for slot=0,tbl.per_region-1 do
                local p=tbl.address+(region*tbl.per_region+slot)*tbl.entry_size
                rows[#rows+1]={id=u32(read(p+tbl.id_off,c.bus_domain)),
                    active=u32(read(p+tbl.active_off,c.bus_domain))~=0,region=region}
            end
        end
        return rows
    end
    function strategy.resident(id)
        if not integer(id,0,0xFFFF) then return false end
        return NDS.resident(io,tbl,id,c.bus_domain)
    end
    function strategy.epoch()
        -- ponytail: this private token is decided and consumed inside ONE validate call,
        -- with no frameadvance/yield in between. It is never cached across polls/boots.
        -- A bounded 16-word MAIN fold detects a changed arming view; inactive-id changes
        -- may over-report. It is NOT a persistent boot/save-generation identity. Every
        -- decision still rechecks residency and the full pin through may_arm below.
        local value=0x811C9DC5
        for slot=0,tbl.per_region-1 do
            local p=tbl.address+slot*tbl.entry_size
            value=((value ~ u32(io.read_u32(p+tbl.id_off,c.bus_domain)))*0x01000193)&0xFFFFFFFF
            value=((value ~ u32(io.read_u32(p+tbl.active_off,c.bus_domain)))*0x01000193)&0xFFFFFFFF
        end
        return value
    end
    -- Geometry validation stays at this HGSS-configured strategy boundary.
    NDS.resident(io,tbl,0,c.bus_domain)
    RC.assert_strategy(strategy,io.read_u32)
    local function site_confirmed(site)
        return pin_matches(io,site.address,site.register_hex,c.bus_domain)==true
    end
    local function call_view(epoch,id,resident)
        -- ponytail: call-local view only, never retained over a yield/poll. ARM
        -- decisions fold once, then recheck the target residency and full pin.
        -- FIRE checks reuse the residency scan taken before the read-only accept
        -- filter; may_fire still owns the full-pin check after accept succeeds.
        return {entries=strategy.entries,
            epoch=epoch~=nil and function() return epoch end or strategy.epoch,
            resident=function(overlay)
                if id~=nil and overlay==id then return resident end
                return strategy.resident(overlay)
            end}
    end
    local self={}
    local accept_errors,accept_error=0,nil
    local hit=nil
    -- Binder filter faults are dropped hits, recorded here; never a latch.
    function self:status() return {accept_errors=accept_errors,accept_error=accept_error} end
    function self:resident(ovy)
        assert(integer(ovy,0,0xFFFF),"overlay id")
        return strategy.resident(ovy)
    end
    function self:validate(site)
        local out=copy(site)
        assert(type(out.id)=="string" and out.id~="","site id required")
        assert(out.mode=="thumb" or out.mode=="arm","NDS site mode")
        assert(integer(out.address,0,0xFFFFFFFF) and out.address%2==0 and (out.mode~="arm" or out.address%4==0),"invalid NDS address/alignment")
        assert(type(out.phase)=="string" and out.phase~="","site phase required")
        local pin,fire=out.register_hex,out.fire_hex
        assert(integer(out.extent,4,4096) and type(pin)=="string" and #pin==out.extent*2 and pin:match("^[0-9a-fA-F]+$"),"full registration extent")
        assert(type(fire)=="string" and #fire==8 and fire:match("^[0-9a-fA-F]+$"),"fire_hex must be four bytes")
        out.fire=tonumber(fire,16)
        local lead=0
        for i=0,3 do lead=lead | (tonumber(pin:sub(2*i+1,2*i+2),16) << (8*i)) end
        assert(lead==out.fire,"fire/registration pin disagreement: "..out.id)
        out.pc=out.address+c.pc_offset[out.mode]
        if out.image=="arm9" then
            assert(out.overlay_id==nil,"static ARM9 site carries no overlay id")
        else
            assert(integer(out.overlay_id,0,0xFFFF) and out.image=="ov"..out.overlay_id,"declared overlay identity: "..out.id)
            local ov=c.overlays[tostring(out.overlay_id)]
            assert(type(ov)=="table" and integer(ov.ram,0,0xFFFFFFFF) and integer(ov.size,1,0xFFFFFFFF),"unknown overlay: "..out.id)
            assert(out.address>=ov.ram and out.address+out.extent<=ov.ram+ov.size,"site extent outside its overlay: "..out.id)
        end
        if out.image=="arm9" then
            assert(site_confirmed(out),"full registration pin mismatch: "..out.id)
        else
            local epoch=strategy.epoch()
            local allowed,reason=RC.may_arm(call_view(epoch),out,site_confirmed,epoch)
            if not allowed then
                if reason=="pin_mismatch" or reason=="not_resident" or reason=="stale_epoch" then
                    error("nds-refused:"..reason..":"..out.id,0)
                end
                error("NDS arm fault: "..tostring(reason)..":"..out.id,0)
            end
        end
        return out
    end
    function self:context(site,accept)
        assert(hit,"NDS context outside a bus-exec callback: "..tostring(site.id))
        local resident=site.overlay_id and self:resident(site.overlay_id)
        if site.overlay_id and not resident then return nil end
        if accept then
            local ok,accepted=pcall(accept)
            if not ok then
                accept_errors,accept_error=accept_errors+1,tostring(site.id)..": "..tostring(accepted)
                return nil
            end
            if not accepted then return nil end
        end
        local allowed,reason=RC.may_fire(call_view(nil,site.overlay_id,resident),site,site_confirmed)
        if not allowed then
            if reason=="not_resident" then return nil end
            error("NDS fire fault: "..tostring(reason)..":"..tostring(site.id),0)
        end
        assert(u32(hit.addr)==site.address,tostring(site.id)..": callback address differs")
        assert(u32(io.register(c.pc_register))==site.pc,tostring(site.id)..": callback PC differs")
        assert(u32(hit.val)==site.fire,tostring(site.id)..": fire word differs while owning overlay active")
        return {pc=site.pc,address=site.address,word=site.fire,overlay_id=site.overlay_id,flags=u32(hit.flags or 0),frame=io.framecount()}
    end
    function self:register(site,callback,name)
        return io.on_bus_exec(function(addr,val,flags)
            hit={addr=addr,val=val,flags=flags}
            local ok,err=pcall(callback,addr,val,flags)
            hit=nil
            if not ok then error(err,0) end
        end,site.address,name,c.bus_domain)
    end
    function self:unregister(handle) return io.unregister(handle) end
    function self:valid_handle(handle)
        if integer(handle,1,9007199254740991) then return true end
        return type(handle)=="string" and handle~="" and handle:gsub("[{}]",""):lower()~=NULL_GUID
    end
    return self
end

return NDS
