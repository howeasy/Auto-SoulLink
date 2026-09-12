-- Native partner YES/NO through the foreground service, without CPU redirection.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local JSON=dofile(ROOT.."/lua/json_codec.lua")
local function read_json(path)
    local f=assert(io.open(path,"r"));local raw=f:read("*a");f:close();return assert(JSON.decode(raw))
end
local input=read_json(assert(os.getenv("SLINK_PARTNER_PROMPT_INPUT")))
local manifest=input.manifest
local map_fixture=dofile(ROOT.."/lua/tests/gen1_map_fixture.lua").start(input.fixture,"partner-prompt")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_partner_prompt_gate")
map_fixture:close()
local M=t.M
local a=manifest.ram
local prompt=manifest.receptionist.partner_prompt
local function r(p)return memory.read_u8(p,"System Bus")end
local function w(p,v)memory.write_u8(p,v,"System Bus")end
local function bytes(p,count,domain)
    local out={};for i=0,count-1 do out[#out+1]=memory.read_u8(p+i,domain or "System Bus")end;return out
end
local function hex(p,count,domain)return M.bytesToHex(bytes(p,count,domain))end
local function put(p,raw)for i,v in ipairs(raw)do w(p+i-1,v)end end
local function fields()
    local out={};for name,address in pairs(prompt.saved_fields)do out[name]=r(address)end;return out
end
local routines={service=manifest.foreground.service,prompt=prompt}
for _,name in ipairs({"InternalClockTradeAnim","TryEvolvingMon","SavePartyAndDexData"})do
    routines[name]=manifest.native_calls[name]
end
local observer=dofile(ROOT.."/lua/tests/gb_foreground_observer.lua").new({
    name="partner-prompt",bridge_entry=1,bank_address=a.hLoadedROMBank,
    return_addresses=manifest.foreground.original_callers,routines=routines})
local active,choice_clock,seen_choice,current_case,question_lines,guard_changes
local prompt_hook=event.on_bus_exec(function()
    if active and r(a.hLoadedROMBank)==prompt.bank then
        for _,change in ipairs(current_case.refusal or {})do
            local address=a[change.field]+(change.offset or 0)
            guard_changes[#guard_changes+1]={address=address,before=r(address)}
            w(address,change.value)
        end
    end
end,prompt.address,"partner-last-moment-guard","System Bus")
local choice_hook=event.on_bus_exec(function()
    if active and r(a.hLoadedROMBank)==prompt.bank then
        seen_choice=true;choice_clock=0
        question_lines={hex(a.wTileMap+281,18),hex(a.wTileMap+321,18)}
    end
end,prompt.choice,"partner-native-choice","System Bus")
local observations={}
local ok,why=xpcall(function()
    assert(gameinfo.getromhash():lower()==manifest.final_sha1 and t.variant==input.variant,"wrong prompt artifact")
    if input.fixture then assert(map_fixture.loads==1 and M.getCurrentMap()==input.fixture.map_id,"wrong prepared map")end
    local cart_before=hex(0,0x8000,"CartRAM")
    for index,case in ipairs(input.cases)do
        current_case=case
        for _=1,180 do if M.isPartyWriteSafe()then break end;t.step({})end
        assert(M.isPartyWriteSafe(),"partner did not reach a verified overworld checkpoint")
        for i,raw in ipairs(case.party)do
            local blob=assert(M.hexToBytes(raw))
            put(a.wPartyMons+(i-1)*44,{table.unpack(blob,1,44)})
            put(a.wPartyMonOT+(i-1)*11,{table.unpack(blob,45,55)})
            put(a.wPartyMonNicks+(i-1)*11,{table.unpack(blob,56,66)})
            w(a.wPartySpecies+i-1,blob[1])
        end
        w(a.wPartyCount,#case.party);w(a.wPartySpecies+#case.party,255)
        local incoming=assert(M.hexToBytes(case.incoming))
        put(a.wEnemyMons,{table.unpack(incoming,1,44)})
        put(a.wEnemyMonOT,{table.unpack(incoming,45,55)})
        put(a.wEnemyMonNicks,{table.unpack(incoming,56,66)})
        w(a.wEnemyPartyCount,1);w(a.wEnemyPartySpecies,incoming[1]);w(a.wEnemyPartySpecies+1,255)
        local party_before=hex(a.wPartyCount,a.wPartyMonNicks+66-a.wPartyCount)
        local map_before=M.getCurrentMap()
        local tiles_before=hex(a.wTileMap,360)
        local controls_before=fields()
        local overlay=manifest.foreground.overlay
        put(manifest.foreground.backup,bytes(overlay,16))
        local generation=index%255+1
        put(overlay,{0x53,0x4c,0x54,0x31,1,3,generation-1,generation-1,255,case.slot,1,0,0x12,0x34,0x56,index})
        w(overlay+6,generation)
        observer:start();active=true;seen_choice=false;choice_clock=0;guard_changes={};question_lines=nil
        local complete=false;local frames
        for frame=1,3000 do
            local buttons={}
            if case.hold_open and frame<90 then
                buttons[case.hold_open]=true
                assert(not seen_choice,"held input advanced into partner choice")
            elseif seen_choice then
                choice_clock=choice_clock+1
                if case.answer=="no"then buttons.Down=choice_clock>=10 and choice_clock<16 end
                if case.answer=="cancel"then buttons.B=choice_clock>=35 and choice_clock<41
                else buttons.A=choice_clock>=35 and choice_clock<41 end
            end
            t.step(buttons)
            if case.screenshot and seen_choice and choice_clock==6 then
                client.screenshot(input.output.."-"..case.id..".png")
            end
            if emu.getregister("PC")==0x40 then
                local sp=emu.getregister("SP")
                local caller=r(sp+2)+256*r(sp+3)
                if caller==manifest.foreground.wait_return and r(overlay+5)==7 and r(overlay+7)==generation then
                    complete=true;frames=frame;break
                end
            end
        end
        assert(complete,case.id..": prompt did not finish")
        for _,change in ipairs(guard_changes)do w(change.address,change.before)end
        local result=r(overlay+8)
        assert(result==case.result,case.id..": wrong native choice "..result)
        assert(seen_choice==(case.result~=3) and observer.counts.prompt==1,case.id..": wrong native YES/NO entry")
        if question_lines then
            for line=1,2 do
                local expected=case.question_lines[line]
                assert(question_lines[line]:sub(1,#expected)==expected,case.id..": wrong names in native question")
            end
        end
        assert(hex(a.wPartyCount,a.wPartyMonNicks+66-a.wPartyCount)==party_before,"partner prompt changed party")
        assert(hex(0,0x8000,"CartRAM")==cart_before,"partner prompt changed SRAM")
        for name,value in pairs(controls_before)do assert(r(prompt.saved_fields[name])==value,"prompt changed control "..name)end
        local union_after=hex(manifest.foreground.backup,16)
        -- A stale generation and then a wrong token must keep the completed
        -- foreground lease held until its matching receipt is consumed.
        w(overlay+5,8);w(overlay+6,generation-1)
        for _=1,5 do t.step({});assert(not M.isPartyWriteSafe(),"stale prompt release was accepted")end
        w(overlay+6,generation);w(overlay+15,0)
        for _=1,5 do t.step({});assert(not M.isPartyWriteSafe(),"wrong prompt token released play")end
        w(overlay+15,index);observer:release()
        for _=1,180 do t.step({});if observer.after and M.isPartyWriteSafe()then break end end
        assert(observer.before and observer.after and M.isPartyWriteSafe(),"prompt did not return to original caller")
        for name,value in pairs(observer.before)do
            assert(observer.after[name]==value+(name=="SP"and 2 or 0),"prompt changed caller "..name)
        end
        assert(M.getCurrentMap()==map_before and hex(a.wTileMap,360)==tiles_before,"prompt changed map presentation")
        assert(hex(overlay,16)==union_after,"prompt failed to restore borrowed union")
        for _,name in ipairs({"InternalClockTradeAnim","TryEvolvingMon","SavePartyAndDexData"})do
            assert(not observer.counts[name],"confirmation triggered "..name)
        end
        observations[#observations+1]={id=case.id,result=result,frames=frames,counts=observer.counts,
            party_unchanged=true,save_unchanged=true,controls_restored=true,map_restored=true,
            before=observer.before,after=observer.after,map=map_before,question_lines=question_lines}
        active=false;t.log("[ok] "..case.id)
        for _=1,10 do t.step({})end
    end
end,debug.traceback)
observer:close();event.unregisterbyid(choice_hook);event.unregisterbyid(prompt_hook)
local result={variant=t.variant,final_sha1=manifest.final_sha1,passed=ok,error=not ok and tostring(why)or nil,
    runtime_ready=false,direct_cpu_redirect=false,cases=JSON.array(observations)}
local f=assert(io.open(input.output,"w"));f:write(assert(JSON.encode(result)));f:close()
if not ok then client.screenshot(input.output.."-failure.png")end
t.check("native partner trade confirmation",ok,tostring(why));t.finish()
