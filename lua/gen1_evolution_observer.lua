-- Original party evolution only. No mutation or acquisition authority.
-- Native cable and NPC trade evolutions have their own owning receipts.
local JSON=require('json_codec')
local Data=require('gen1_evolution_sites')
local M={MAX_PENDING=16}
local function copy(v)return assert(JSON.decode(assert(JSON.encode(v))))end
local function hex(address,count,domain)
    local out={};for i=0,count-1 do out[#out+1]=string.format('%02X',memory.read_u8(address+i,domain or 'System Bus'))end
    return table.concat(out)
end
function M.new(options)
    local profile=assert(Data.titles[options.variant]);local a=profile.addresses
    assert(type(options.owned)=='function'and type(options.held)=='function','owned evolution observer required')
    local owner=copy(options.owned());local hooks={};local pending=JSON.array();local active;local failed,closed
    local function check()
        assert(not closed and not failed,failed or 'evolution observer closed')
        assert(gameinfo.getromhash():lower()==options.final_sha1 and JSON.encode(options.owned())==JSON.encode(owner),'evolution context changed')
    end
    local function point()
        local p={party_hex=hex(a.wPartyDataStart,404),box_hex=hex(a.wBoxDataStart,1122),
            trainer_hex=hex(a.wPlayerName,11),player_id_hex=hex(a.wPlayerID,2),dex_hex=hex(a.wPokedexOwned,38)}
        for key,name in pairs({map_id='wCurMap',battle_flag='wIsInBattle',link_state='wLinkState',slot='wWhichPokemon',
            table_species='wEvoOldSpecies',current_item='wCurItem',force='wForceEvolution',current_box='wCurrentBoxNum',
            mon_location='wMonDataLocation'})do p[key]=memory.read_u8(a[name],'System Bus')end
        return p
    end
    local function remove()for _,id in ipairs(hooks)do event.unregisterbyid(id)end;hooks={}end
    local ok,why=pcall(function()
        check()
        for kind,site in pairs(profile.sites)do
            assert(hex(site.rom_offset,#site.expected_hex/2,'ROM')==site.expected_hex,'evolution ROM anchor differs')
            hooks[#hooks+1]=assert(event.on_bus_exec(function()
                if closed or failed or memory.read_u8(a.hLoadedROMBank,'System Bus')~=site.bank then return end
                if memory.read_u8(a.wLinkState,'System Bus')==profile.link_state_trading then return end
                local valid,reason=pcall(function()
                    check();assert(emu.getregister('PC')==site.address and hex(site.address,#site.expected_hex/2)==site.expected_hex,'evolution instruction changed')
                    local witness={frame=emu.framecount(),pc=site.address,bank=site.bank,sp=emu.getregister('SP'),point=point()}
                    if kind=='begin'then
                        assert(not active,'overlapping evolution attempts')
                        witness.selection={pointer=emu.getregister('H')*256+emu.getregister('L'),level=emu.getregister('A')}
                        active=witness
                    else
                        assert(active and #pending<M.MAX_PENDING,'evolution completion lacks bounded before witness')
                        pending[#pending+1]={schema='rby-evolution-receipt-v1',source_sha256=Data.sha256,variant=options.variant,
                            context_generation=owner.context_generation,physical_instance=owner.physical_instance,final_sha1=options.final_sha1,
                            outcome=kind,before=active,after=witness}
                        active=nil
                    end
                end)
                if not valid then failed=tostring(reason)end
            end,site.address,'slink-evolution-'..kind,'System Bus'))
        end
    end)
    if not ok then remove();error(why,0)end
    return {peek=function()check();assert(options.held(),'evolution publication requires held boundary');return copy(pending)end,
        acknowledge=function(expected)check();assert(options.held()and JSON.encode(expected)==JSON.encode(pending),'evolution receipt changed before durable ACK');pending=JSON.array();return true end,
        status=function()return {pending=#pending,in_flight=active and 1 or 0,failed=failed,closed=closed==true}end,
        close=function()closed=true;remove()end}
end
return M
