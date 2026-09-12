-- Read-only wild boundaries. The owner persists peek before acknowledge.
-- Capture delivery is a separate source; no absence inference or grace timer here.
local JSON=require('json_codec')
local Data=require('gen1_wild_encounter_sites')
local M={MAX_PENDING=32}
local function copy(v)return assert(JSON.decode(assert(JSON.encode(v))))end
local function hex(address,count)
    local out={};for i=0,count-1 do out[#out+1]=string.format('%02X',memory.read_u8(address+i,'System Bus'))end
    return table.concat(out)
end
function M.new(options)
    local profile=assert(Data.titles[options.variant]);local a=profile.addresses
    assert(type(options.owned)=='function'and type(options.held)=='function','owned wild encounter observer required')
    local owner=copy(options.owned());local pending=JSON.array();local hooks={};local closed,failed=false,nil
    local function check()
        assert(not closed and not failed,failed or 'wild encounter observer closed')
        assert(gameinfo.getromhash():lower()==options.final_sha1 and JSON.encode(options.owned())==JSON.encode(owner),
            'wild encounter physical context changed')
    end
    local function point()
        local value={trainer_hex=hex(a.wPlayerName,11),player_id_hex=hex(a.wPlayerID,2),bag_hex=hex(a.wNumBagItems,42)}
        for key,name in pairs({map_id='wCurMap',cur_opponent='wCurOpponent',species_index='wEnemyMonSpecies2',
            level='wCurEnemyLevel',battle_flag='wIsInBattle',battle_type='wBattleType',battle_result='wBattleResult',link_state='wLinkState'})do
            value[key]=memory.read_u8(a[name],'System Bus')
        end
        return value
    end
    local function remove()for _,id in ipairs(hooks)do event.unregisterbyid(id)end;hooks={}end
    local ok,why=pcall(function()
        check()
        for kind,site in pairs(profile.sites)do
            local actual={};for i=0,#site.expected_hex/2-1 do actual[#actual+1]=string.format('%02X',memory.read_u8(site.rom_offset+i,'ROM'))end
            assert(table.concat(actual)==site.expected_hex,'wild encounter ROM anchor differs')
            hooks[#hooks+1]=assert(event.on_bus_exec(function()
                if closed or failed or memory.read_u8(a.hLoadedROMBank,'System Bus')~=site.bank
                    or memory.read_u8(a.wIsInBattle,'System Bus')~=1 then return end
                -- Tutorial names are temporarily overwritten by cartridge code.
                -- They never enter the delivering encounter stream on either title.
                local bt=memory.read_u8(a.wBattleType,'System Bus')
                if bt~=profile.battle_types.BATTLE_TYPE_NORMAL and bt~=profile.battle_types.BATTLE_TYPE_SAFARI then return end
                local valid,reason=pcall(function()
                    check();assert(#pending<M.MAX_PENDING,'wild encounter buffer full')
                    assert(emu.getregister('PC')==site.address and hex(site.address,#site.expected_hex/2)==site.expected_hex,
                        'wild encounter instruction changed')
                    pending[#pending+1]={schema='rby-wild-encounter-receipt-v1',source_sha256=Data.sha256,
                        variant=options.variant,context_generation=owner.context_generation,physical_instance=owner.physical_instance,
                        final_sha1=options.final_sha1,kind=kind,witness={frame=emu.framecount(),pc=site.address,bank=site.bank,
                            sp=emu.getregister('SP'),point=point()}}
                end)
                if not valid then failed=tostring(reason)end
            end,site.address,'slink-wild-encounter-'..kind,'System Bus'))
        end
    end)
    if not ok then remove();error(why,0)end
    return {peek=function()check();assert(options.held(),'wild publication requires hold');return copy(pending)end,
        acknowledge=function(expected)
            check();assert(options.held()and JSON.encode(expected)==JSON.encode(pending),'wild receipts changed before durable acknowledgement')
            pending=JSON.array();return true
        end,
        status=function()return {pending=#pending,closed=closed,failed=failed}end,
        close=function()closed=true;remove()end}
end
return M
