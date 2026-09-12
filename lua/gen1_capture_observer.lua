-- Read-only delivery hooks. The owner persists peek() before acknowledge().
local JSON=require("json_codec")
local Data=require("gen1_capture_sites")
local M={MAX_PENDING=32}
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
local function hex(address,count,domain)
    local parts={};for i=0,count-1 do parts[#parts+1]=string.format("%02X",memory.read_u8(address+i,domain or "System Bus"))end
    return table.concat(parts)
end
function M.new(options)
    assert(type(options.owned)=="function" and type(options.held)=="function","owned capture observer required")
    local profile=assert(Data.titles[options.variant]);local a=profile.addresses
    local owner=copy(options.owned());local hooks={};local pending=JSON.array();local failure,closed=nil,false
    local function check()
        assert(not closed and not failure,failure or "capture observer closed")
        assert(gameinfo.getromhash():lower()==options.final_sha1 and JSON.encode(owner)==JSON.encode(options.owned()),"capture observer context changed")
    end
    local function point()
        local p={party_hex=hex(a.wPartyDataStart,404),box_hex=hex(a.wBoxDataStart,1122),enemy_hex=hex(a.wEnemyMon,29),
            trainer_hex=hex(a.wPlayerName,11),player_id_hex=hex(a.wPlayerID,2)}
        for key,name in pairs({map_id='wCurMap',battle_flag='wIsInBattle',battle_type='wBattleType',cur_species='wCurPartySpecies',
            captured_species='wCapturedMonSpecies',cur_level='wCurEnemyLevel',mon_location='wMonDataLocation',current_box='wCurrentBoxNum'})do
            p[key]=memory.read_u8(a[name],"System Bus")
        end
        return p
    end
    local function close_hooks()for _,id in ipairs(hooks)do event.unregisterbyid(id)end;hooks={}end
    local ok,why=pcall(function()
        check()
        for _,site in pairs(profile.sites)do
            assert(hex(site.rom_offset,#site.expected_hex/2,"ROM")==site.expected_hex,"capture ROM anchor differs")
        end
        for kind,site in pairs(profile.sites)do
            hooks[#hooks+1]=assert(event.on_bus_exec(function()
                if closed or failure or memory.read_u8(a.hLoadedROMBank,"System Bus")~=site.bank then return end
                local success,reason=pcall(function()
                    check();assert(#pending<M.MAX_PENDING,"capture signal buffer full")
                    assert(emu.getregister("PC")==site.address,"capture execution site differs")
                    assert(hex(site.address,#site.expected_hex/2)==site.expected_hex,"capture instruction bytes changed")
                    pending[#pending+1]={kind=kind,frame=emu.framecount(),pc=site.address,bank=site.bank,sp=emu.getregister("SP"),point=point()}
                end)
                if not success then failure=tostring(reason)end
            end,site.address,"slink-capture-"..kind,"System Bus"))
        end
    end)
    if not ok then close_hooks();error(why,0)end
    return {
        peek=function()check();assert(options.held(),"capture publication requires held frame");return copy(pending)end,
        acknowledge=function(records)
            check();assert(options.held() and JSON.encode(records)==JSON.encode(pending),"capture publication cursor differs")
            pending=JSON.array();return true
        end,
        status=function()return {pending=#pending,failed=failure,closed=closed}end,
        close=function()closed=true;close_hooks()end}
end
return M
