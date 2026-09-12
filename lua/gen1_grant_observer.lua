-- Read-only scripted-grant delivery hooks. The owner persists peek() before acknowledge().
-- Witnesses: the script's `call GivePokemon` (operands still in B/C), its return (F carry =
-- delivered, wAddedToParty = party/box) and, for a Game Corner prize, the jp after SubBCD.
-- Same peek/acknowledge/status/close surface as gen1_capture_observer.
local JSON=require("json_codec")
local Data=require("gen1_grant_sites")
local M={MAX_PENDING=32,SCHEMA="rby-grant-receipt-v1"}
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
local function hex(address,count,domain)
    local parts={};for i=0,count-1 do parts[#parts+1]=string.format("%02X",memory.read_u8(address+i,domain or "System Bus"))end
    return table.concat(parts)
end
function M.new(options)
    assert(type(options.owned)=="function" and type(options.held)=="function","owned grant observer required")
    local profile=assert(Data.titles[options.variant]);local a=profile.addresses
    local owner=copy(options.owned())
    assert(type(owner.context_generation)=="string" and type(owner.physical_instance)=="string","pre-admission physical identity required")
    local hooks={};local pending=JSON.array();local open={};local failure,closed=nil,false
    local function check()
        assert(not closed and not failure,failure or "grant observer closed")
        assert(gameinfo.getromhash():lower()==options.final_sha1 and JSON.encode(owner)==JSON.encode(options.owned()),"grant observer context changed")
    end
    local function point()
        local p={party_hex=hex(a.wPartyDataStart,404),box_hex=hex(a.wBoxDataStart,1122),trainer_hex=hex(a.wPlayerName,11),
            player_id_hex=hex(a.wPlayerID,2),coins_hex=hex(a.wPlayerCoins,2),prizes_hex=hex(a.wPrize1,3),prices_hex=hex(a.wPrize1Price,6)}
        for key,name in pairs({map_id="wCurMap",battle_flag="wIsInBattle",cur_species="wCurPartySpecies",cur_level="wCurEnemyLevel",
            mon_location="wMonDataLocation",added_to_party="wAddedToParty",current_box="wCurrentBoxNum",which_prize="wWhichPrize",
            prize_window="wWhichPrizeWindow"})do
            p[key]=memory.read_u8(a[name],"System Bus")
        end
        return p
    end
    local function finish(source_id)
        local receipt=open[source_id];open[source_id]=nil
        assert(#pending<M.MAX_PENDING,"grant receipt buffer full; recovery required")
        pending[#pending+1]=receipt
    end
    local function witness(site)
        assert(emu.getregister("PC")==site.address and hex(site.address,#site.expected_hex/2)==site.expected_hex,"grant instruction site changed")
        return {frame=emu.framecount(),pc=site.address,bank=site.bank,sp=emu.getregister("SP"),point=point()}
    end
    local function close_hooks()for _,id in ipairs(hooks)do event.unregisterbyid(id)end;hooks={}end
    local function install(source_id,site,kind,fn)
        hooks[#hooks+1]=assert(event.on_bus_exec(function()
            if closed or failure or memory.read_u8(a.hLoadedROMBank,"System Bus")~=site.bank then return end
            local success,reason=pcall(function()check();fn(witness(site))end)
            if not success then failure=tostring(reason)end
        end,site.address,"slink-grant-"..kind.."-"..source_id,"System Bus"))
    end
    local ok,why=pcall(function()
        check()
        for _,site in pairs(profile.sites)do
            for _,anchor in ipairs({site.call,site["return"],site.purchase and site.purchase.paid})do
                assert(hex(anchor.rom_offset,#anchor.expected_hex/2,"ROM")==anchor.expected_hex,"grant ROM anchor differs")
            end
        end
        for source_id,site in pairs(profile.sites)do
            install(source_id,site.call,"call",function(w)
                assert(not open[source_id],"overlapping grant call for "..source_id)
                w.b=emu.getregister("B");w.c=emu.getregister("C")
                open[source_id]={schema=M.SCHEMA,source_sha256=Data.sha256,variant=options.variant,context_generation=owner.context_generation,
                    physical_instance=owner.physical_instance,final_sha1=options.final_sha1,source_id=source_id,call=w}
            end)
            install(source_id,site["return"],"return",function(w)
                local receipt=assert(open[source_id],"grant return without its call")
                w.flags=emu.getregister("F");receipt["return"]=w
                -- Carry clear: party and box were full, nothing was given; no receipt, no ordinal.
                if w.flags%32<16 then open[source_id]=nil;return end
                if not site.purchase then finish(source_id)end
            end)
            if site.purchase then
                install(source_id,site.purchase.paid,"paid",function(w)
                    local receipt=assert(open[source_id],"prize payment without its delivery")
                    assert(receipt["return"],"prize payment before delivery returned")
                    receipt.paid=w;finish(source_id)
                end)
            end
        end
    end)
    if not ok then close_hooks();error(why,0)end
    return {
        peek=function()check();assert(options.held(),"grant publication requires held frame");return copy(pending)end,
        acknowledge=function(records)
            check();assert(options.held() and JSON.encode(records)==JSON.encode(pending),"grant publication cursor differs")
            pending=JSON.array();return true
        end,
        status=function()
            local in_flight=0;for _ in pairs(open)do in_flight=in_flight+1 end
            return {pending=#pending,in_flight=in_flight,failed=failure,closed=closed}
        end,
        close=function()closed=true;close_hooks()end}
end
return M
