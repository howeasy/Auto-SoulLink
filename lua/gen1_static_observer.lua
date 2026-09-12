-- Read-only static-battle origin hooks. The owner persists peek() before acknowledge().
-- Witnesses: `arm` right after a static's opponent species/level were written (a Snorlax
-- script's own write block, or InitBattleEnemyParameters.noTrainer's ret for object statics,
-- named there by wCurMap + wSpriteIndex), the shared `began` at InitWildBattle+5, and `end`
-- at EndOfBattle's entry, published only while a began receipt is live (every battle passes
-- it; wBattleResult is final there). Same peek/acknowledge/status/close surface as gen1_grant_observer.
local JSON=require("json_codec")
local Data=require("gen1_static_sites")
local M={MAX_PENDING=32,SCHEMA="rby-static-origin-receipt-v1"}
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
local function hex(address,count,domain)
    local parts={};for i=0,count-1 do parts[#parts+1]=string.format("%02X",memory.read_u8(address+i,domain or "System Bus"))end
    return table.concat(parts)
end
function M.new(options)
    assert(type(options.owned)=="function" and type(options.held)=="function","owned static observer required")
    local profile=assert(Data.titles[options.variant]);local a=profile.addresses
    local owner=copy(options.owned())
    assert(type(owner.context_generation)=="string" and type(owner.physical_instance)=="string","pre-admission physical identity required")
    local hooks={};local pending=JSON.array();local open=nil;local live=false;local failure,closed=nil,false
    local function check()
        assert(not closed and not failure,failure or "static observer closed")
        assert(gameinfo.getromhash():lower()==options.final_sha1 and JSON.encode(owner)==JSON.encode(options.owned()),"static observer context changed")
    end
    local function point()
        local p={trainer_hex=hex(a.wPlayerName,11),player_id_hex=hex(a.wPlayerID,2)}
        for key,name in pairs({map_id="wCurMap",cur_opponent="wCurOpponent",cur_level="wCurEnemyLevel",enemy_species2="wEnemyMonSpecies2",
            battle_flag="wIsInBattle",battle_type="wBattleType",sprite_index="wSpriteIndex",engaged_class="wEngagedTrainerClass",
            engaged_set="wEngagedTrainerSet",battle_result="wBattleResult"})do
            p[key]=memory.read_u8(a[name],"System Bus")
        end
        return p
    end
    local function witness(site)
        assert(emu.getregister("PC")==site.address and hex(site.address,#site.expected_hex/2)==site.expected_hex,"static instruction site changed")
        return {frame=emu.framecount(),pc=site.address,bank=site.bank,sp=emu.getregister("SP"),point=point()}
    end
    local function close_hooks()for _,id in ipairs(hooks)do event.unregisterbyid(id)end;hooks={}end
    local function install(site,name,fn)
        hooks[#hooks+1]=assert(event.on_bus_exec(function()
            -- Home (bank 0) code runs whatever bank is switched in; only banked sites filter on it.
            if closed or failure or (site.bank~=0 and memory.read_u8(a.hLoadedROMBank,"System Bus")~=site.bank) then return end
            local success,reason=pcall(function()check();fn(witness(site))end)
            if not success then failure=tostring(reason)end
        end,site.address,"slink-static-"..name,"System Bus"))
    end
    local function header()
        return {schema=M.SCHEMA,source_sha256=Data.sha256,variant=options.variant,context_generation=owner.context_generation,
            physical_instance=owner.physical_instance,final_sha1=options.final_sha1}
    end
    local function publish(receipt)
        assert(#pending<M.MAX_PENDING,"static receipt buffer full; recovery required")
        pending[#pending+1]=receipt
    end
    local function arm(source_id,w)
        assert(not open,"overlapping static arm for "..source_id..": "..(open and open.source_id or "?").." never began")
        open=header();open.source_id=source_id;open.arm=w
    end
    local ok,why=pcall(function()
        check()
        local objects={}
        for source_id,site in pairs(profile.sites)do
            for _,anchor in ipairs({site.arm,site.writes,site.arm.routine})do
                assert(hex(anchor.rom_offset,#anchor.expected_hex/2,"ROM")==anchor.expected_hex,"static ROM anchor differs")
            end
            if site.kind=="object" then objects[site.map_id..":"..site.object_index]=source_id
            else install(site.arm,"arm-"..source_id,function(w)arm(source_id,w)end)end
        end
        for _,anchor in ipairs({profile.began,profile.began.prelude,profile.battle_end,profile.battle_end.reset,profile.battle_end.call})do
            assert(hex(anchor.rom_offset,#anchor.expected_hex/2,"ROM")==anchor.expected_hex,"static ROM anchor differs")
        end
        install(profile.object_arm,"arm-object",function(w)
            local key=w.point.map_id..":"..w.point.sprite_index
            arm(assert(objects[key],"unknown static object "..key.."; census incomplete, recovery required"),w)
        end)
        install(profile.began,"began",function(w)
            if not open then return end -- random or fishing encounters: nothing was armed, nothing to attribute
            local receipt=open;open=nil;receipt.began=w
            publish(receipt);live=true
        end)
        install(profile.battle_end,"battle-end",function(w)
            -- Only the end of a battle that began while an origin was live matters; the server joins it by order.
            if not live then return end
            live=false;local receipt=header();receipt["end"]=w;publish(receipt)
        end)
    end)
    if not ok then close_hooks();error(why,0)end
    return {
        peek=function()check();assert(options.held(),"static publication requires held frame");return copy(pending)end,
        acknowledge=function(records)
            check();assert(options.held() and JSON.encode(records)==JSON.encode(pending),"static publication cursor differs")
            pending=JSON.array();return true
        end,
        status=function()return {pending=#pending,in_flight=open and 1 or 0,live=live,failed=failure,closed=closed}end,
        close=function()closed=true;close_hooks()end}
end
return M
