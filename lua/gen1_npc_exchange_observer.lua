-- Read-only NPC in-game exchange hooks. The owner persists peek() before acknowledge().
-- Witnesses: the map script's `ld [wWhichTrade], a` (A = trade index; the store's PC names the
-- source), the engine's `call RemovePokemon` (party intact, wWhichPokemon = outgoing slot) and
-- the `call ClearScreen` reached only after AddPartyMon, InGameTrade_CopyDataToReceivedMon and
-- the trade-evolution hook returned. Same peek/acknowledge/status/close surface as
-- gen1_grant_observer.
local JSON=require("json_codec")
local Data=require("gen1_npc_exchange_sites")
local M={MAX_PENDING=32,SCHEMA="rby-npc-exchange-receipt-v1"}
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
local function hex(address,count,domain)
    local parts={};for i=0,count-1 do parts[#parts+1]=string.format("%02X",memory.read_u8(address+i,domain or "System Bus"))end
    return table.concat(parts)
end
function M.new(options)
    assert(type(options.owned)=="function" and type(options.held)=="function","owned exchange observer required")
    local profile=assert(Data.titles[options.variant]);local a=profile.addresses;local engine=profile.engine
    local owner=copy(options.owned())
    assert(type(owner.context_generation)=="string" and type(owner.physical_instance)=="string","pre-admission physical identity required")
    local hooks={};local pending=JSON.array();local current=nil;local failure,closed=nil,false
    local function check()
        assert(not closed and not failure,failure or "exchange observer closed")
        assert(gameinfo.getromhash():lower()==options.final_sha1 and JSON.encode(owner)==JSON.encode(options.owned()),"exchange observer context changed")
    end
    local function point()
        local p={party_hex=hex(a.wPartyDataStart,404),box_hex=hex(a.wBoxDataStart,1122),trainer_hex=hex(a.wPlayerName,11),
            player_id_hex=hex(a.wPlayerID,2),traded_ot_id_hex=hex(a.wTradedEnemyMonOTID,2),trade_nick_hex=hex(a.wInGameTradeMonNick,11)}
        for key,name in pairs({map_id="wCurMap",battle_flag="wIsInBattle",which_trade="wWhichTrade",which_pokemon="wWhichPokemon",
            cur_species="wCurPartySpecies",cur_level="wCurEnemyLevel",mon_location="wMonDataLocation",remove_from_box="wRemoveMonFromBox",
            give_species="wInGameTradeGiveMonSpecies",receive_species="wInGameTradeReceiveMonSpecies",current_box="wCurrentBoxNum"})do
            p[key]=memory.read_u8(a[name],"System Bus")
        end
        return p
    end
    local function witness(site)
        assert(emu.getregister("PC")==site.address and hex(site.address,#site.expected_hex/2)==site.expected_hex,"exchange instruction site changed")
        return {frame=emu.framecount(),pc=site.address,bank=site.bank,sp=emu.getregister("SP"),point=point()}
    end
    local function close_hooks()for _,id in ipairs(hooks)do event.unregisterbyid(id)end;hooks={}end
    local function install(name,site,fn)
        hooks[#hooks+1]=assert(event.on_bus_exec(function()
            if closed or failure or memory.read_u8(a.hLoadedROMBank,"System Bus")~=site.bank then return end
            local success,reason=pcall(function()check();fn(witness(site))end)
            if not success then failure=tostring(reason)end
        end,site.address,"slink-exchange-"..name,"System Bus"))
    end
    local ok,why=pcall(function()
        check()
        local anchors={engine.remove,engine["return"],engine.block,engine.trainer_string,engine.species_level_check,engine.copy_received,engine.ot_id_source}
        for _,site in pairs(profile.sites)do
            anchors[#anchors+1]=site.call;anchors[#anchors+1]=site.dispatch
            anchors[#anchors+1]={rom_offset=site.record_rom_offset,expected_hex=site.record_hex}
        end
        for _,anchor in ipairs(anchors)do
            assert(hex(anchor.rom_offset,#anchor.expected_hex/2,"ROM")==anchor.expected_hex,"exchange ROM anchor differs")
        end
        for source_id,site in pairs(profile.sites)do
            install("call-"..source_id,site.call,function(w)
                -- A declined or wrong-species dialogue leaves its selector open; the next selector supersedes it.
                -- The dialogue is synchronous, so a selector can never interleave a removal and its delivery.
                assert(not(current and current.remove),"exchange selector during a delivery")
                w.a=emu.getregister("A")
                current={schema=M.SCHEMA,source_sha256=Data.sha256,variant=options.variant,context_generation=owner.context_generation,
                    physical_instance=owner.physical_instance,final_sha1=options.final_sha1,source_id=source_id,call=w}
            end)
        end
        install("remove",engine.remove,function(w)
            assert(current and not current.remove,"exchange removal without its selector")
            current.remove=w
        end)
        install("return",engine["return"],function(w)
            assert(current and current.remove,"exchange delivery without its removal")
            current["return"]=w
            assert(#pending<M.MAX_PENDING,"exchange receipt buffer full; recovery required")
            pending[#pending+1]=current;current=nil
        end)
    end)
    if not ok then close_hooks();error(why,0)end
    return {
        peek=function()check();assert(options.held(),"exchange publication requires held frame");return copy(pending)end,
        acknowledge=function(records)
            check();assert(options.held() and JSON.encode(records)==JSON.encode(pending),"exchange publication cursor differs")
            pending=JSON.array();return true
        end,
        status=function()
            return {pending=#pending,in_flight=current and 1 or 0,selected=current and current.source_id or nil,
                removing=(current and current.remove) and true or false,failed=failure,closed=closed}
        end,
        close=function()closed=true;close_hooks()end}
end
return M
