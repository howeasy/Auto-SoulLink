-- Install before New Game. No frame, cartridge write, admission, or release authority.
local JSON=require('json_codec')
local Data=require('gen1_bootstrap_sites')
local M={}
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
local function hex(address,count,domain)
    local out={};for i=0,count-1 do out[#out+1]=string.format('%02X',memory.read_u8(address+i,domain or 'System Bus'))end
    return table.concat(out)
end
function M.new(options)
    assert(type(options.owned)=='function' and type(options.held)=='function','owned bootstrap observer required')
    local profile=assert(Data.titles[options.variant]);local owner=copy(options.owned())
    assert(type(owner.context_generation)=='string' and type(owner.physical_instance)=='string','pre-admission physical identity required')
    local hooks={};local begin,finished,failure;local closed=false
    local function check()
        assert(not closed and not failure,failure or 'bootstrap observer closed')
        assert(gameinfo.getromhash():lower()==options.final_sha1 and JSON.encode(owner)==JSON.encode(options.owned()),'bootstrap physical context changed')
    end
    local function close_hooks()for _,id in ipairs(hooks)do event.unregisterbyid(id)end;hooks={}end
    local ok,why=pcall(function()
        check()
        for kind,site in pairs(profile.sites)do
            assert(hex(site.rom_offset,#site.expected_hex/2,'ROM')==site.expected_hex,'bootstrap ROM anchor differs')
            hooks[#hooks+1]=assert(event.on_bus_exec(function()
                if closed or failure or memory.read_u8(profile.bank_address,'System Bus')~=site.bank then return end
                local success,reason=pcall(function()
                    check();assert(not finished,'new game restarted after bootstrap completion')
                    assert(emu.getregister('PC')==site.address and hex(site.address,#site.expected_hex/2)==site.expected_hex,'bootstrap instruction site changed')
                    local witness={frame=emu.framecount(),pc=site.address,bank=site.bank,sp=emu.getregister('SP')}
                    if kind=='begin' then
                        assert(not begin,'overlapping new-game bootstrap');begin=witness
                    else
                        assert(begin and witness.sp==begin.sp and witness.frame>begin.frame,'bootstrap return lacks normal entry')
                        witness.point={}
                        for name,field in pairs(profile.fields)do witness.point[name]=hex(field.address,field.length)end
                        finished={schema='rby-bootstrap-receipt-v1',source_sha256=Data.sha256,variant=options.variant,
                            context_generation=owner.context_generation,physical_instance=owner.physical_instance,
                            final_sha1=options.final_sha1,begin=begin,['end']=witness}
                    end
                end)
                if not success then failure=tostring(reason)end
            end,site.address,'slink-bootstrap-'..kind,'System Bus'))
        end
    end)
    if not ok then close_hooks();error(why,0)end
    return {peek=function()check();assert(options.held(),'bootstrap publication requires held frame');return finished and copy(finished)end,
        status=function()return {started=begin~=nil,complete=finished~=nil,failed=failure,closed=closed}end,
        close=function()closed=true;close_hooks()end}
end
return M
