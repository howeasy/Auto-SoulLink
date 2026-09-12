-- Test-only buttons and explicit file transport; production adapters own all UI RAM writes.
local JSON=require("json_codec")
local M={}
local function exchange(path,packet)
    local file=assert(io.open(path..".tmp","w"));file:write(assert(JSON.encode(packet)));file:close()
    assert(os.rename(path..".tmp",path))
    -- Intentionally no emulated frames during test-transport latency. This is
    -- not paired host-control/network qualification or a production scheduler.
    local deadline=os.time()+10
    while os.time()<deadline do
        local reply=io.open(path..".ack","r")
        if reply then
            local value=assert(JSON.decode(reply:read("*a")));reply:close()
            assert(value.ack=="ACK" and value.operation_id==packet.operation_id,"test transport ACK differs")
            return value
        end
    end
    error("native UI test transport timed out",0)
end
function M.receptionist(t,manifest,journal,context,directory)
    local mem=t.M
    local ui=manifest.receptionist
    local entered,menus,clock,notice,result=0,0,0,false,nil
    local hooks={}
    local function hook(address,fn)
        hooks[#hooks+1]=event.on_bus_exec(function()
            if memory.read_u8(manifest.ram.hLoadedROMBank,"System Bus")==ui.entry.bank then fn()end
        end,address,"ui-client-test-"..#hooks,"System Bus")
    end
    hook(ui.entry.address,function()entered=entered+1 end)
    hook(ui.menu_input,function()menus=menus+1;clock=0 end)
    hook(ui.notice,function()notice=true;clock=0 end)
    hook(ui.notice_done,function()notice=false end)
    hook(ui.offer_result,function()result=emu.getregister("B")end)
    local adapter=require("gen1_receptionist_client").new({memory=mem,manifest=manifest,journal=journal,
        context_generation=function()return context end,authorize=function()return true end,
        eligible_slots=function()return 1 end}) -- explicit linked-pair fixture; slot0 only
    local returned=false;local sent=false
    for frame=1,3000 do
        adapter.step()
        local packet=journal:pending_events()[1]
        if packet and packet.payload.event=="trade_offer" and not sent then
            exchange(directory.."/offer.json",packet)
            assert(journal:accept_response(packet.operation_id,JSON.array()))
            sent=true;adapter.step()
        end
        clock=clock+1
        local buttons={}
        if frame<=8 then buttons.Up=true
        elseif entered==0 then buttons.A=frame%30<6
        elseif notice then buttons.A=clock>=12 and clock%30<6
        elseif menus>0 then buttons.A=clock>=90 and clock<96 end
        t.step(buttons)
        if entered>0 and mem.isPartyWriteSafe()then returned=true;break end
    end
    adapter.close();for _,id in ipairs(hooks)do event.unregisterbyid(id)end
    assert(returned and entered==1 and menus==2 and result==0 and sent,"native receptionist offer did not complete")
    assert(journal.store:read().observation.gen1_receptionist.phase=="acknowledged","native sent notice lacks durable server ACK")
    return {entries=entered,menus=menus,result=result,server_acknowledged=true}
end
function M.partner(t,manifest,journal,lease_store,context,player,command,directory)
    local mem=t.M
    local poll=assert(journal:append({event="sync"}))
    assert(journal:accept_response(poll,JSON.array({command})))
    local native=require("gen1_partner_prompt_executor").new({memory=mem,manifest=manifest,journal=journal,store=lease_store,
        player=player,context_generation=function()return context end,authorize=function()return true end})
    local executor=require("command_executor").new(journal,native)
    local seen,clock=false,0
    local prompt=manifest.receptionist.partner_prompt
    local hook=event.on_bus_exec(function()
        if memory.read_u8(manifest.ram.hLoadedROMBank,"System Bus")==prompt.bank then seen=true;clock=0 end
    end,prompt.choice,"ui-client-native-choice","System Bus")
    local done,result=executor:step(command.command_id)
    assert(not done and result.pending,"native prompt was not durably armed")
    for _=1,3000 do
        if seen then clock=clock+1 end
        t.step({A=seen and clock>=35 and clock<41})
        done,result=executor:step(command.command_id)
        if done then break end
        assert(result.pending,JSON.encode(result))
    end
    event.unregisterbyid(hook)
    assert(done and result.outcome=="ACK" and result.receipt.result==0,"native partner did not accept")
    local before=memory.read_u8(manifest.foreground.overlay+5,"System Bus")
    assert(not pcall(native.release) and memory.read_u8(manifest.foreground.overlay+5,"System Bus")==before,
        "prompt released before its exact durable server ACK")
    local packet=journal:pending_events()[1];assert(packet.payload.event=="trade_decision","typed native decision was not queued")
    exchange(directory.."/decision.json",packet)
    assert(journal:accept_response(packet.operation_id,JSON.array()))
    native.release()
    for _=1,180 do t.step({});if mem.isPartyWriteSafe()then break end end
    local closure=native.finish_release();native.close()
    return {decision=result.receipt,closure=closure,server_acknowledged=true}
end
M.exchange=exchange
return M
