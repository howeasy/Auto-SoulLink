-- Actual assembled foreground engine: remove, append, native movie, evolution,
-- map restoration and canonical save. Test injection is not a runtime scheduler.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_native_trade_engine")
local M=t.M
package.path=ROOT.."/lua/?.lua;"..package.path
local JSON=require("json_codec")
local Codec=require("gen1_party_codec")
local function read_json(path)
    local f=assert(io.open(path,"r"));local text=f:read("*a");f:close();return assert(JSON.decode(text))
end
local manifest=read_json(ROOT.."/patch/gen1/build/native_"..t.variant.."/manifest.json")
assert(gameinfo.getromhash():lower()==manifest.final_sha1,"wrong current native artifact")
assert(type(manifest.test_probe)=="table" and manifest.test_probe.NativeTradeTestEntry,"test entry required")
local cases=read_json(ROOT.."/.cache/native-trade-cases-"..t.variant..".json")
local source=t.variant=="yellow" and "pokeyellow" or "pokered"
local target=t.variant=="blue" and "pokeblue" or source
local frame,active,cancel_pressed=0,false,false
local current_case,learning_active,learning_menu,learning_questions,forget_menus
local function step()
    frame=frame+1
    local buttons={A=active and frame%20<8,B=active and cancel_pressed,Down=false}
    if learning_menu then
        learning_menu.clock=learning_menu.clock+1
        local row=learning_menu.row
        buttons.A=learning_menu.clock>=70 and learning_menu.clock<76
        buttons.B=false
        for i=1,row do
            local start=10+(i-1)*12
            if learning_menu.clock>=start and learning_menu.clock<start+5 then buttons.Down=true end
        end
    end
    t.step(buttons)
end
local oracle=dofile(ROOT.."/lua/tests/gb_routine_oracle.lua").new({
    symbols_path=ROOT.."/.cache/pret/"..source.."/"..target..".sym",step=step,
    scratch=0xCB00,marker=0xCBF0,stack=0xDFFE,bankswitch="Bankswitch",
    enable_interrupts=true,timeout_frames=12000})
local a,r,w=oracle.address,oracle.read,oracle.write
local function bytes(address,count,domain)
    local result={}
    for i=0,count-1 do result[#result+1]=memory.read_u8(address+i,domain or "System Bus") end
    return result
end
local function put(address,data)
    for i,byte in ipairs(data)do w(address+i-1,byte)end
end
local function party()
    local blobs={}
    for slot=0,M.getPartyCount()-1 do blobs[#blobs+1]=M.bytesToHex(assert(M.readPartyBlob(slot))) end
    return JSON.array(blobs)
end
local function cart_offset(name)
    local symbol=oracle.symbol(name);return symbol.bank*0x2000+symbol.address-0xA000
end
local counts,min_sp={},0xFFFF
local observations={}
local hooks={}
local learning_returns={}
local returned,returning,original_registers,callback_error,active_refusal
hooks[#hooks+1]=event.on_bus_exec(function()
    if active and r(a("hLoadedROMBank"))==manifest.test_probe.bank then
        observations.returned=M.getPartyCount();returning=emu.getregister("A")
    end
end,manifest.test_probe.NativeTradeTestReturned,"native-trade-test-return","System Bus")
hooks[#hooks+1]=event.on_bus_exec(function()
    if returning~=nil then
        for _,change in ipairs(active_refusal or {})do w(change.address,change.before)end
        if emu.getregister("SP")~=original_registers.SP then callback_error="native call did not balance original stack" end
        for _,name in ipairs({"A","F","B","C","D","E","H","L"})do
            local set,why=pcall(emu.setregister,name,original_registers[name])
            if not set then callback_error="restore "..name..": "..tostring(why) end
        end
        returned=returning;returning=nil;active=false;joypad.set({A=false})
    end
end,0x40,"native-trade-test-resume","System Bus")
for _,name in ipairs({"_RemovePokemon","_AddEnemyMonToPlayerParty","InternalClockTradeAnim","TryEvolvingMon","SavePartyAndDexData","InGameTrade_RestoreScreen","RedrawMapView","LearnMove"})do
    local symbol=oracle.symbol(name)
    hooks[#hooks+1]=event.on_bus_exec(function()
        if active and (symbol.bank==0 or r(a("hLoadedROMBank"))==symbol.bank) then
            counts[name]=(counts[name] or 0)+1
            if name=="LearnMove"then learning_active=true end
            observations[name]=M.getPartyCount()
            if name=="InternalClockTradeAnim" then
                observations.trade_music=r(a("wLastMusicSoundID"))
                observations.trade_music_bank=r(a("wAudioROMBank"))
            end
            min_sp=math.min(min_sp,emu.getregister("SP"))
        end
    end,symbol.address,"trade-engine-"..name,"System Bus")
end
hooks[#hooks+1]=event.on_bus_exec(function()
    if not active or not learning_active or not current_case.learning_action then return end
    local x,y=r(a("wTopMenuItemX")),r(a("wTopMenuItemY"))
    local row
    if x==5 and y==8 then
        forget_menus=forget_menus+1
        row=current_case.forget_choices and current_case.forget_choices[math.min(forget_menus,#current_case.forget_choices)]
            or current_case.forget_slot or 0
    elseif x==15 and y==8 then
        learning_questions=learning_questions+1
        row=(current_case.learning_action=="decline" and learning_questions==1)and 1 or 0
    else return end
    local sp=emu.getregister("SP")
    local return_address=r(sp)+256*r(sp+1)
    local bank=r(a("hLoadedROMBank"))
    local key=bank..":"..return_address
    learning_menu={clock=0,row=row,key=key}
    if not learning_returns[key]then
        learning_returns[key]=true
        hooks[#hooks+1]=event.on_bus_exec(function()
            if learning_menu and learning_menu.key==key and r(a("hLoadedROMBank"))==bank then learning_menu=nil end
        end,return_address,"native-learning-return-"..key,"System Bus")
    end
end,a("HandleMenuInput"),"native-learning-menu","System Bus")
local boot=memorysavestate.savecorestate()
local evidence=JSON.array()
local ok,reason=xpcall(function()
    for _,case in ipairs(cases)do
        current_case=case;learning_active=false;learning_menu=nil;learning_questions=0;forget_menus=0
        memorysavestate.loadcorestate(boot)
        cancel_pressed=case.press_cancel==true
        counts={};observations={};min_sp=0xFFFF
        local prepared={}
        for i,hex in ipairs(case.party)do prepared[i]=assert(M.hexToBytes(hex))end
        local incoming=assert(M.hexToBytes(case.incoming))
        if case.pikachu_happiness then
            local blob=prepared[case.slot+1]
            assert(t.variant=="yellow" and blob[1]==0x54,"starter fixture must be Yellow Pikachu")
            blob[13]=r(M.PLAYER_ID_ADDR);blob[14]=r(M.PLAYER_ID_ADDR+1)
            for i=0,10 do blob[45+i]=r(M.PLAYER_NAME_ADDR+i)end
            case.party[case.slot+1]=M.bytesToHex(blob)
            w(a("wPikachuHappiness"),case.pikachu_happiness)
            w(a("wPikachuMood"),0x80)
            w(a("wPikachuOverworldStateFlags"),case.following_disabled and 2 or 0)
        end
        assert(Codec.validateParty(prepared,t.variant,nil,{}))
        local received=assert(Codec.validateBlob(incoming,t.variant))
        local selected=assert(Codec.validateBlob(prepared[case.slot+1],t.variant))
        assert(Codec.prepareExchange(prepared,t.variant,case.slot,incoming,selected.key,received.key,
            case.evolved_species or received.species_index,{}))
        w(M.PARTY_COUNT_ADDR,#prepared)
        for slot,blob in ipairs(prepared)do
            put(M.PARTY_BASE_ADDR+(slot-1)*44,{table.unpack(blob,1,44)})
            put(M.PARTY_OT_NAMES_ADDR+(slot-1)*11,{table.unpack(blob,45,55)})
            put(M.PARTY_NICKS_ADDR+(slot-1)*11,{table.unpack(blob,56,66)})
            w(M.PARTY_SPECIES_ADDR+slot-1,blob[1])
        end
        w(M.PARTY_SPECIES_ADDR+#prepared,255)
        w(a("wEnemyPartyCount"),1);w(a("wEnemyPartySpecies"),incoming[1]);w(a("wEnemyPartySpecies")+1,255)
        put(a("wEnemyMons"),{table.unpack(incoming,1,44)})
        put(a("wEnemyMonOT"),{table.unpack(incoming,45,55)})
        put(a("wEnemyMonNicks"),{table.unpack(incoming,56,66)})
        put(a("wLinkEnemyTrainerName"),{0x8F,0x84,0x84,0x91,0x50,0x50,0x50,0x50,0x50,0x50,0x50})
        w(a("wTradingWhichPlayerMon"),case.slot)
        for _=1,300 do if M.isPartyWriteSafe()then break end;step()end
        assert(M.isPartyWriteSafe(),"verified pre-call checkpoint absent")
        local map,x,y=M.getCurrentMap(),r(a("wXCoord")),r(a("wYCoord"))
        local options=r(a("wOptions"))
        local map_music=r(a("wMapMusicSoundID"))
        local controls=bytes(a("wSpriteStateData1"),0x200)
        local tilemap=bytes(a("wTileMap"),360)
        local party_before=M.bytesToHex(bytes(a("wPartyDataStart"),a("wPartyDataEnd")-a("wPartyDataStart")))
        local before_dex=M.bytesToHex(bytes(a("wPokedexOwned"),38))
        local save_length=a("sMainDataCheckSum")-a("sGameData")+1
        local before_save_region=M.bytesToHex(bytes(cart_offset("sGameData"),save_length,"CartRAM"))
        local before_pikachu=t.variant=="yellow" and M.bytesToHex(bytes(a("wPikachuHappiness"),2)) or nil
        local save_id=string.format("%04X",M.readPlayerId())
        local save_name=M.bytesToHex(bytes(M.PLAYER_NAME_ADDR,11))
        local cart_before=case.refusal and M.bytesToHex(bytes(0,0x8000,"CartRAM"))
        local scratch_before=M.bytesToHex(bytes(a("wTradedPlayerMonSpecies"),32))
        local which_before=r(a("wWhichPokemon"))
        local canary_address=t.variant=="yellow" and 0xDF15 or 0xDF00
        local canary={0x91,0x27,0xE4,0xB6,0x3A,0xCD,0x58,0x0F}
        put(canary_address,canary)
        client.screenshot(ROOT.."/.cache/native-trade-before-"..t.variant..".png")
        local start=frame
        returned=nil;returning=nil;callback_error=nil;active=true;original_registers={}
        active_refusal={}
        for _,change in ipairs(case.refusal or {})do
            local address=a(change.field)+(change.offset or 0)
            active_refusal[#active_refusal+1]={address=address,before=r(address)}
            w(address,change.value)
        end
        assert(emu.getregister("PC")==0x40,"test entry requires VBlank boundary")
        for _,name in ipairs({"A","F","B","C","D","E","H","L","SP"})do original_registers[name]=emu.getregister(name)end
        local sp=original_registers.SP-2
        w(sp,0x40);w(sp+1,0)
        emu.setregister("SP",sp);emu.setregister("B",manifest.test_probe.bank)
        emu.setregister("H",math.floor(manifest.test_probe.NativeTradeTestEntry/256))
        emu.setregister("L",manifest.test_probe.NativeTradeTestEntry%256);emu.setregister("PC",a("Bankswitch"))
        for _=1,12000 do step();if returned~=nil then break end end
        active=false
        if returned==nil then
            t.log(string.format("timeout pc=%04X sp=%04X bank=%02X calls=%s",emu.getregister("PC"),emu.getregister("SP"),r(a("hLoadedROMBank")),JSON.encode(JSON.object(counts))))
            client.screenshot(ROOT.."/.cache/native-trade-engine-failure-"..t.variant..".png")
        end
        assert(returned~=nil,"native trade did not return")
        assert(callback_error==nil,callback_error)
        -- Equal-Length-Frames may stop inside DMA immediately after the return.
        -- Cartridge readback must wait for the independently proved checkpoint.
        for _=1,300 do if M.isPartyWriteSafe()then break end;step()end
        assert(M.isPartyWriteSafe(),"post-trade readback checkpoint absent")
        if case.refusal then
            assert(returned==1,"invalid native request did not refuse")
            assert(next(counts)==nil,"refused command entered physical/animation/save routines")
            assert(M.bytesToHex(bytes(a("wPartyDataStart"),a("wPartyDataEnd")-a("wPartyDataStart")))==party_before,"refused request changed party")
            assert(M.bytesToHex(bytes(0,0x8000,"CartRAM"))==cart_before,"refused request changed SRAM")
            assert(M.bytesToHex(bytes(a("wTradedPlayerMonSpecies"),32))==scratch_before and r(a("wWhichPokemon"))==which_before,"refused request changed transaction scratch")
            t.check(case.id.." refuses with zero party/save/transaction mutation",true)
            evidence[#evidence+1]={id=case.id,refused=true,frames=frame-start}
        else
        t.check(case.id.." native sequence returned success",returned==0,tostring(returned))
        for _,name in ipairs({"_RemovePokemon","_AddEnemyMonToPlayerParty","InternalClockTradeAnim","TryEvolvingMon","SavePartyAndDexData","InGameTrade_RestoreScreen","RedrawMapView"})do
            t.check(case.id.." invokes "..name,counts[name]==1,tostring(counts[name]))
        end
        t.check(case.id.." original animation advances frames",frame-start>2000,tostring(frame-start))
        assert(observations.trade_music==manifest.trade_music.id and observations.trade_music_bank==manifest.trade_music.bank,"native trade music did not start")
        local after=party()
        t.check(case.id.." party count preserved",#after==#case.party,tostring(#after))
        if #after~=#case.party then t.log("party-count-trace="..JSON.encode(JSON.object(observations)).." after="..JSON.encode(after))end
        local expected={}
        for i,hex in ipairs(case.party)do if i~=case.slot+1 then expected[#expected+1]=hex end end
        expected[#expected+1]=case.incoming
        for i=1,#expected-1 do assert(after[i]==expected[i],"unrelated mon/order changed")end
        if not case.evolution then assert(after[#after]==case.incoming,"incoming66-byte fidelity failed")end
        local actual=assert(Codec.validateBlob(M.hexToBytes(after[#after]),t.variant))
        assert(actual.species_index==(case.evolved_species or received.species_index),"recipient evolution outcome differs")
        if case.evolution then
            local ev={hp=received.stat_experience[1],attack=received.stat_experience[2],defense=received.stat_experience[3],
                speed=received.stat_experience[4],special=received.stat_experience[5]}
            local stats=assert(t.G.rebuildBoxStats(t.variant,actual.species_index,received.level,received.dv_word,ev))
            for i,field in ipairs({"hp","attack","defense","speed","special"})do
                assert(actual.computed_stats[i]==stats[field],"evolved stat differs from canonical formula")
            end
            assert(actual.hp==received.hp+actual.maxHP-received.maxHP,"evolution did not preserve HP damage")
            local allowed={[1]=true,[2]=true,[3]=true,[6]=true,[7]=true}
            for i=35,44 do allowed[i]=true end
            if case.expected_nickname then
                local nickname=assert(M.hexToBytes(case.expected_nickname))
                assert(#nickname==11,"expected nickname must include every cartridge byte")
                for i=1,11 do
                    assert(actual.blob[55+i]==nickname[i],"native evolution nickname differs from MonsterNames")
                    allowed[55+i]=true
                end
            end
            if case.expected_moves then
                for i=1,4 do
                    assert(actual.blob[8+i]==case.expected_moves[i],"native learned move differs")
                    assert(actual.blob[29+i]==case.expected_packed_pp[i],"native learned PP differs")
                    allowed[8+i]=true;allowed[29+i]=true
                end
            end
            for i,byte in ipairs(incoming)do if not allowed[i] then assert(actual.blob[i]==byte,"evolution changed unrelated blob field "..i)end end
        end
        if case.expected_learn_calls then assert((counts.LearnMove or 0)==case.expected_learn_calls,"native learning path differs")end
        if case.expected_forget_menus then assert(forget_menus==case.expected_forget_menus,"native HM refusal path differs")end
        local live_party=bytes(a("wPartyDataStart"),a("wPartyDataEnd")-a("wPartyDataStart"))
        local saved_party=bytes(cart_offset("sPartyData"),#live_party,"CartRAM")
        assert(M.bytesToHex(live_party)==M.bytesToHex(saved_party),"party did not reach canonical SRAM")
        assert(M.bytesToHex(bytes(a("wPokedexOwned"),38))==M.bytesToHex(bytes(cart_offset("sMainData"),38,"CartRAM")),"dex did not reach SRAM")
        local sum=0
        for _,byte in ipairs(bytes(cart_offset("sGameData"),a("sGameDataEnd")-a("sGameData"),"CartRAM"))do sum=(sum+byte)%256 end
        assert(memory.read_u8(cart_offset("sMainDataCheckSum"),"CartRAM")==255-sum,"canonical save checksum differs")
        if case.pikachu_happiness then
            local expected_happiness=case.pikachu_happiness-(case.pikachu_happiness>=200 and 20 or 10)
            assert(r(a("wPikachuHappiness"))==expected_happiness,"starter trade happiness not applied")
            local saved_happiness=cart_offset("sMainData")+a("wPikachuHappiness")-a("wMainDataStart")
            assert(memory.read_u8(saved_happiness,"CartRAM")==expected_happiness,"starter happiness not saved")
            assert(r(a("wPikachuMood"))==0 and memory.read_u8(saved_happiness+1,"CartRAM")==0,"starter trade mood not saved")
        end
        t.check(case.id.." returns to same map/coordinates",M.getCurrentMap()==map and r(a("wXCoord"))==x and r(a("wYCoord"))==y)
        t.check(case.id.." restores original tilemap",M.bytesToHex(bytes(a("wTileMap"),360))==M.bytesToHex(tilemap))
        t.check(case.id.." restores options",r(a("wOptions"))==options)
        t.check(case.id.." native stack remains in its reserved range",min_sp>=(t.variant=="yellow" and 0xDF15 or 0xDF00),string.format("%04X",min_sp))
        assert(M.bytesToHex(bytes(canary_address,#canary))==M.bytesToHex(canary),"native stack crossed lower canary")
        for _=1,120 do if M.isPartyWriteSafe()then break end;step()end
        t.check(case.id.." returns to real overworld checkpoint",M.isPartyWriteSafe())
        for _=1,16 do step()end
        assert(r(a("wLastMusicSoundID"))==map_music,"map music was not restored")
        client.screenshot(ROOT.."/.cache/native-trade-return-"..t.variant..".png")
        evidence[#evidence+1]={id=case.id,before=case.party,incoming=case.incoming,slot=case.slot,party=after,frames=frame-start,native_calls=JSON.object(counts),
            min_sp=min_sp,saved_party_hex=M.bytesToHex(saved_party),live_party_hex=M.bytesToHex(live_party),
            before_dex_hex=before_dex,before_save_region_hex=before_save_region,before_pikachu_hex=before_pikachu,
            saved_region_hex=M.bytesToHex(bytes(cart_offset("sGameData"),save_length,"CartRAM")),
            save_id=save_id,save_name_hex=save_name,sprite_state_before=M.bytesToHex(controls)}
        if case.reset then
            assert(case==cases[#cases],"reset proof must be the final case")
            memorysavestate.removestate(boot);boot=nil
            client.reboot_core()
            M._party_tail_cache=nil;M._memorial_reservations=nil
            local first_mood,mood_steps,mood_hook=nil,0,nil
            if case.pikachu_happiness then
                local symbol=oracle.symbol("UpdatePikachuHappinessAndMood")
                mood_hook=event.on_bus_exec(function()
                    if r(a("hLoadedROMBank"))==symbol.bank then
                        if first_mood==nil then first_mood=r(a("wPikachuMood"))end
                        mood_steps=mood_steps+1
                    end
                end,symbol.address,"native-trade-reset-mood","System Bus")
            end
            assert(G.prove_booted(M,"gen1_rby",t.step,t.hold),"real reset did not reach playable CONTINUE")
            if mood_hook then event.unregisterbyid(mood_hook)end
            assert(JSON.encode(party())==JSON.encode(after),"reset did not preserve traded/evolved party")
            if case.pikachu_happiness then
                -- Vanilla poison.asm moves mood one unit toward128 on EVERY
                -- walking step, even with no starter present. Prove the saved0
                -- was loaded and then let the real boot/walk change it normally.
                assert(first_mood==0 and mood_steps>0,"saved trade mood was not loaded before walking")
                assert(r(a("wPikachuHappiness"))==case.pikachu_happiness-20,"reset lost trade happiness")
                assert(r(a("wPikachuMood"))==math.min(128,mood_steps),"post-load mood differs from native walking updates")
                evidence[#evidence].reset_mood_steps=mood_steps
            end
            evidence[#evidence].reset_verified=true
            t.check(case.id.." real reset/CONTINUE preserves completed trade",true)
        end
        end
    end
    local f=assert(io.open(ROOT.."/.cache/native-trade-engine-"..t.variant..".json","w"))
    f:write(assert(JSON.encode({variant=t.variant,final_sha1=manifest.final_sha1,cases=evidence})));f:close()
end,debug.traceback)
for _,id in ipairs(hooks)do event.unregisterbyid(id)end
if boot then memorysavestate.loadcorestate(boot);memorysavestate.removestate(boot)end
t.check("assembled native trade engine completed",ok,tostring(reason))
t.finish()
