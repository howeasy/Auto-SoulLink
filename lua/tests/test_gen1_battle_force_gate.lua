--[[
  lua/tests/test_gen1_battle_force_gate.lua — LIVE qualification of the battle instruction
  authority prototype (lua/battle_force_authority.lua on lua/instruction_executor.lua).

  Original engine, battery save = the DISCLOSED two-mon fixture built by tools/gen1_battle_fixture.py
  (Route 1, Squirtle L5 + Ditto L5 with Transform; see its manifest), normal battle entry by walking
  into grass, every menu driven with joypad input through lua/tests/gen1_battle_driver.lua whose
  read-only hooks report each engine stage. After two harness-only measurements every frame is ONE
  platform_bounded_execution.step_one under a real bounded owner; each frame arms ONE fresh
  authority (carrying the measured hook-frame convention) and finishes right after; every evidence
  row is recorded exactly as the executor produced it and verified by tests/live/test_gen1_battle_force.py.

  Scenarios, all in ONE wild battle so the single white-out comes last:
    convention / controls / bounded_convention   as before
    benched      PKMN -> switch Ditto in with Squirtle linked: ExecutePlayerMove is reached with the
                 linked mon BENCHED -> party-only HP/status zeros; then the engine refuses to send it back out
    transform    Ditto (not linked) uses TRANSFORM: wPlayerBattleStatus3 TRANSFORMED set, battle struct = enemy
    player_action  Ditto linked while transformed: menu -> not_reached only; FIGHT commit ->
                 ExecutePlayerMove+0 write (HP 0000 + CANNOT_MOVE) -> faint -> black-out (both mons down)
    explode_first  (scenarios=["explode_first"] only, P11) the EXPLODE binding armed for the linked Squirtle from the
                 walk on: the wild battle's first MainInBattleLoop+0 rewrites its four move slots to EXPLOSION (PP 5)
                 before the first menu; FIGHT + slot 1 reaches ExecutePlayerMove+0 with $99 already selected (one-byte
                 no-op write) and the ORIGINAL engine's ExplodeEffect faints the mon itself and hits the wild mon
    free_window  (scenarios=["free_window"] only, handoff item 5) fight_first in the FREE-LOOP form: no bounded owner
                 (emu.frameadvance, held() = the frame boundary), one 64-frame window authority per issue entered late,
                 the SAME table armed every frame until a site is reached or the window runs out, then the next window;
                 tests/live/test_gen1_battle_force.py settles every window with battle_force_authority.verify_window
  Assertions and screenshots anchor on the CURRENT member's non-refused row, never an earlier callback.
--]]
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
package.path=ROOT.."/lua/?.lua;"..ROOT.."/lua/tests/?.lua;"..package.path
local G=dofile(ROOT.."/lua/tests/gen1_gatelib.lua")
local t=G.start("test_gen1_battle_force_gate")
local JSON=require("json_codec")
local Battle=require("battle_force_authority")
local Executor=require("instruction_executor")
local Driver=dofile(ROOT.."/lua/tests/gen1_battle_driver.lua")
local fmt=string.format
local f=assert(io.open(assert(os.getenv("SLINK_BATTLE_FORCE_INPUT")),"r"));local config=assert(JSON.decode(f:read("*a")));f:close()
local A=config.addresses;local SITES=config.sites;local OUT=config.out_dir;local D=config.driver
-- config.scenarios (optional list) selects scenarios; nil = the full benched -> transform -> player_action battle.
local function want(name)
    local sc=config.scenarios;if sc==nil or sc==JSON.null then return name~="fight_first" and name~="explode_first" and name~="free_window" end
    for _,n in ipairs(sc)do if n==name then return true end end;return false
end
local u8=function(a)return memory.read_u8(a,"System Bus")end
local result={schema="battle-force-live-v2",variant=t.variant,owner_id=string.rep("b",32),scenarios=JSON.array(),passed=false,
    screenshots=JSON.array(),notes=JSON.array(),fixture=config.fixture}
local function note(s)t.log(s);result.notes[#result.notes+1]=s end
local function shot(name)local path=OUT.."/"..name..".png";client.screenshot(path);result.screenshots[#result.screenshots+1]=name..".png";return path end
local function hexrange(base,count)local parts={};for i=0,count-1 do parts[#parts+1]=fmt("%02x",u8(base+i))end;return table.concat(parts)end
local function party_slot(slot)
    local base=A.wPartyMon1+44*slot
    return {species=u8(base),hp_hex=hexrange(A.wPartyMon1HP+44*slot,2),status=u8(A.wPartyMon1Status+44*slot),dvs_hex=hexrange(A.wPartyMon1DVs+44*slot,2),
        ot_id_hex=hexrange(A.wPartyMon1OTID+44*slot,2),level=u8(base+33)}
end
local function party_count()return u8(A.wPartyMon1-8)end
local function member_for(slot)local p=party_slot(slot);return {slot=slot,species=p.species,dvs_hex=p.dvs_hex,ot_id_hex=p.ot_id_hex,variant=t.variant}end
local function world()return {map=u8(config.coord_addr.map),x=u8(config.coord_addr.x),y=u8(config.coord_addr.y),in_battle=u8(A.wIsInBattle),
    active=u8(A.wPlayerMonNumber),status3=u8(A.wPlayerBattleStatus3),battle_species=u8(A.wBattleMonSpecies),battle_hp=hexrange(A.wBattleMonHP,2),
    party0=party_slot(0).hp_hex,party1=party_count()>=2 and party_slot(1).hp_hex or JSON.null,frame=emu.framecount()}end
local challenge_n=0
local owner=nil;local in_frame=false
-- current.binding selects the authority a step arms (faint by default); the explode binding carries its own site writes
local current={member=nil,scenario=nil,exec=nil,binding=Battle.NAME}
local function authority(member,frame,step)
    challenge_n=challenge_n+1
    local explode=current.binding==Battle.EXPLODE
    return {schema=Executor.SCHEMA,challenge=fmt("%032x",challenge_n),scope={operation_id=string.rep("0",32),operation_digest=string.rep("0",64),
        context_generation=string.rep("0",32),binding_digest=string.rep("0",64),phase="battle_force_faint"},proof_digest=string.rep("0",64),
        owner_id=result.owner_id,frame=frame,step=step,uses=1,held=false,binding=current.binding,member=member,sites=explode and config.explode_sites or SITES,addresses=A,
        hook_frame_offset=(owner and result.hook_frame_offset_bounded) or result.hook_frame_offset_harness or 0}
end
local function scenario(name)local s={name=name,reached=JSON.array(),not_reached=0,checks=JSON.array()};result.scenarios[#result.scenarios+1]=s;return s end
local function check(s,what,ok,detail)s.checks[#s.checks+1]={what=what,ok=ok and true or false,detail=detail};t.check(s.name..": "..what,ok,detail)end

-- ── frame primitive: harness (emu.frameadvance) until the owner exists, then step_one ──────────
local function held()if owner then return owner.status().host.physical_stop_verified end;return not in_frame end
local X=Battle.new({owner_id=result.owner_id,held=held})
local XE=Battle.new({owner_id=result.owner_id,held=held,name=Battle.EXPLODE}) -- same two sites, its own hooks and challenge ledger
current.exec=X
local step_n=0
-- Measured live (lua/tests/probe_input_latency.lua): under step_one joypad.set is STICKY — a button stays
-- held until another joypad.set replaces it (frameadvance auto-releases). Every frame therefore sets all
-- eight buttons explicitly, so a "press" is exactly the frames it is asked for and releases are real.
local BUTTONS={"A","B","Up","Down","Left","Right","Start","Select"}
local function frame(buttons)
    local pad={};for _,b in ipairs(BUTTONS)do pad[b]=false end
    if buttons then for b,v in pairs(buttons)do pad[b]=v and true or false end end
    joypad.set(pad)
    if owner then local ok,r=owner.step_one({});assert(ok,r)else in_frame=true;emu.frameadvance();in_frame=false end
    t.frame=t.frame+1
end
local function step(buttons)
    local member,s,ex=current.member,current.scenario,current.exec
    step_n=step_n+1
    local before=emu.framecount()
    local auth
    local w=current.window
    if w then -- free-loop form: one WINDOW-frame authority entered `late` frames in, the SAME table armed every frame until consumed or exhausted
        local a=w.authority
        if not a or w.consumed or before>a.frames.first+a.frames.count-1 then
            a=authority(member,before-w.late,step_n-w.late);a.frames={first=before-w.late,count=Executor.MAX_WINDOW_FRAMES}
            w.authority=a;w.consumed=false;w.windows[#w.windows+1]={authority=a,rows=JSON.array()}
        end
        auth=a
    else auth=authority(member,before,step_n) end
    assert(ex.arm(auth))
    frame(buttons)
    local ev=ex.finish()
    if w then local rows=w.windows[#w.windows].rows;rows[#rows+1]=ev;if ev.site~=JSON.null and ev.site~=nil then w.consumed=true end end
    if ev.site~=JSON.null and ev.site~=nil then
        s.reached[#s.reached+1]={authority=auth,evidence=ev,world_at_finish=world(),bounded=owner~=nil}
        note(fmt("[%s] REACHED %s frame=%d hook_frame=%s member=%02X refusal=%s writes=%d",s.name,ev.site,before,tostring(ev.hook_frame),member.species,
            ev.refusal==JSON.null and "-" or tostring(ev.refusal),#ev.writes))
    else s.not_reached=s.not_reached+1 end
    return ev
end
local function use(member,s,exec,binding)current.member=member;current.scenario=s;current.exec=exec or X;current.binding=binding or Battle.NAME end
local function wait(frames,stop)for _=1,frames do if stop and stop()then return true end;step(nil)end;return stop and stop()or false end
local function landed(s,base,member)
    local r=s.reached[#s.reached]
    return #s.reached>base and r.authority.member.species==member.species and r.authority.member.slot==member.slot and (r.evidence.refusal==JSON.null or r.evidence.refusal==nil)
end
local function watch_after(s,row,label)
    local timeline=JSON.array()
    for i=1,20 do wait(25);timeline[#timeline+1]=world();if i==1 then shot(label.."_after_write")end;if i==6 then shot(label.."_later")end end
    row.timeline=timeline
end
local drv=Driver.new({step=step,u8=u8,sites=D.sites,addresses=D.addresses,framecount=function()return emu.framecount()end})
local function to_menu(limit,button)
    -- press `button` only while DisplayBattleMenu has NOT been entered yet (text still scrolling); once the
    -- menu routine has started, a press would select an entry, so only idle until the cursor state is consistent
    local m;local base=drv.hits().display_battle_menu and drv.hits().display_battle_menu.count or 0
    for _=1,limit do
        m=drv.wait_menu(1);if m.ok or u8(A.wIsInBattle)==0 then break end
        local entries=drv.hits().display_battle_menu and drv.hits().display_battle_menu.count or 0
        if button and entries==base then for _=1,3 do step({[button]=true})end end
        for _=1,10 do step(nil)end
    end
    return m
end
local function enter_battle(s)
    local dirs={"Up","Down"}
    for _,side in ipairs({"Left","Right","Left","Right","Left","Right"})do
        for _=1,20 do step({[side]=true})end;for _=1,6 do step(nil)end
        for i=1,120 do
            local d=dirs[(i%2)+1]
            for _=1,20 do step({[d]=true});if u8(A.wIsInBattle)~=0 then break end end
            if u8(A.wIsInBattle)~=0 then break end
        end
        if u8(A.wIsInBattle)~=0 then break end
    end
    if u8(A.wIsInBattle)==0 then return false end
    s.menu=to_menu(240,"A")
    return u8(A.wIsInBattle)~=0 and s.menu.ok
end

local ok,why=xpcall(function()
    local squirtle,ditto=member_for(0),member_for(1)
    local stranger={slot=0,species=(squirtle.species%255)+1,dvs_hex=squirtle.dvs_hex,ot_id_hex=squirtle.ot_id_hex,variant=t.variant}
    note(fmt("fixture party: count=%d slot0=%s slot1=%s world=%s",party_count(),JSON.encode(party_slot(0)),JSON.encode(party_slot(1)),JSON.encode(world())))
    do -- disclosed harness precondition: the shipped fixtures carry BIT_NO_BATTLES
        local flags=u8(config.encounter.status_flags4);local pacer=u8(config.encounter.pacer)
        if math.floor(flags/16)%2==1 then memory.write_u8(config.encounter.status_flags4,flags-16,"System Bus")end
        if pacer~=0 then memory.write_u8(config.encounter.pacer,0,"System Bus")end
        result.encounter_switches={before={flags=flags,pacer=pacer},after={flags=u8(config.encounter.status_flags4),pacer=u8(config.encounter.pacer)}}
        note("encounter switches: "..JSON.encode(result.encounter_switches))
    end
    local sram_before=memory.read_bytes_as_array(0,0x2000,"SRAM")
    do
        local s=scenario("convention");use(stranger,s)
        local seen=JSON.array()
        local probe=event.on_bus_exec(function()seen[#seen+1]=emu.framecount()end,0x40,"battle-force-vblank-probe","System Bus")
        local before=emu.framecount();step(nil)
        result.hook_frame_offset_harness=#seen>0 and (seen[1]-before) or JSON.null
        check(s,"harness: vblank hook fired inside the one frame",#seen>=1,fmt("seen=%s before=%d",JSON.encode(seen),before))
        event.unregisterbyid(probe)
    end
    do
        local s=scenario("controls");use(stranger,s)
        local Y=Battle.new({owner_id=result.owner_id,held=held})
        local a1=authority(squirtle,emu.framecount(),1)
        assert(Y.arm(a1));frame(nil);Y.finish()
        check(s,"replaying a finished challenge is refused",not pcall(Y.arm,a1),"arm(same authority) after finish")
        check(s,"a non-advancing step is refused",not pcall(Y.arm,authority(squirtle,emu.framecount(),1)),"step 1 after step 1")
        check(s,"an authority for another frame is refused",not pcall(Y.arm,authority(squirtle,emu.framecount()+5,2)),"frame+5")
        in_frame=true;local held_arm_ok=pcall(Y.arm,authority(squirtle,emu.framecount(),3));in_frame=false
        check(s,"arming while unheld is refused",not held_arm_ok,"held()==false at arm")
        local noconv=authority(squirtle,emu.framecount(),3);noconv.hook_frame_offset=nil
        check(s,"an authority without the measured convention is refused",not pcall(Y.arm,noconv),"hook_frame_offset=nil")
        Y.close()
        local Z=Battle.new({owner_id=result.owner_id,held=held})
        local shifted={};for name,site in pairs(SITES)do shifted[name]={pc=site.pc+3,bank=site.bank,expected_hex=site.expected_hex,writes=site.writes,return_sites=site.return_sites}end
        local a4=authority(squirtle,emu.framecount(),1);a4.sites=shifted
        assert(Z.arm(a4))
        local hp_before=party_slot(0).hp_hex
        for i=1,120 do frame(i%2==0 and {Down=true} or {Up=true});if Z.status().failed or u8(A.wIsInBattle)~=0 then break end end
        check(s,"a shifted PC never writes",party_slot(0).hp_hex==hp_before,fmt("failed=%s in_battle=%d",tostring(Z.status().failed),u8(A.wIsInBattle)))
        Z.close()
        if u8(A.wIsInBattle)~=0 then -- stray battle from the walk: end it with the non-linked member (zero writes)
            local c=scenario("controls_cleanup");use(stranger,c)
            to_menu(80,"A")
            for _=1,8 do if u8(A.wIsInBattle)==0 then break end;local r=drv.run();c.run=r;if not r.ok then to_menu(80,nil)end end
            check(c,"stray battle ended by RUN",u8(A.wIsInBattle)==0,JSON.encode(world()))
        end
    end
    if not want("free_window") then -- the free loop has no bounded owner: every frame stays emu.frameadvance
        local s=scenario("bounded_convention");use(stranger,s)
        owner=require("platform_bounded_execution").new({profile="gambatte",owner_id=assert(require("platform_identity").new_nonce()),
            expected_host=require("platform_execution").supported_profile("gambatte"),authorize=function(value)return value~=nil end})
        local seen=JSON.array()
        local probe=event.on_bus_exec(function()seen[#seen+1]=emu.framecount()end,0x40,"battle-force-bounded-probe","System Bus")
        local before=emu.framecount();step(nil)
        result.hook_frame_offset_bounded=#seen>0 and (seen[1]-before) or JSON.null
        check(s,"step_one: vblank hook fired inside the one frame",#seen>=1,fmt("seen=%s before=%d steps=%d",JSON.encode(seen),before,owner.status().steps))
        check(s,"bounded convention equals the harness convention the authorities carry",result.hook_frame_offset_bounded==result.hook_frame_offset_harness,
            fmt("%s vs %s",tostring(result.hook_frame_offset_bounded),tostring(result.hook_frame_offset_harness)))
        event.unregisterbyid(probe)
        local w0=world();local moved=false
        for _,d in ipairs({"Down","Up","Left","Right"})do
            for _=1,40 do step({[d]=true});if u8(A.wIsInBattle)~=0 then break end end
            local w=world();if w.x~=w0.x or w.y~=w0.y or w.in_battle~=0 then moved=true;break end
        end
        result.bounded_input=moved
        check(s,"joypad input reaches the core inside step_one",moved,fmt("%s -> %s",JSON.encode(w0),JSON.encode(world())))
    end
    -- ── the one battle ─────────────────────────────────────────────────────────────────────────
    local battle=scenario("battle_entry")
    -- explode_first arms the EXPLODE binding for the linked Squirtle from the walk on, so the wild battle's very first
    -- MainInBattleLoop+0 (before its first menu) is the loop_head site: the eight-byte moveset write lands before any menu.
    -- A stray battle from the probe walk has already passed its first loop head: end it with the non-linked member first.
    local explode=want("explode_first") and scenario("explode_first") or nil
    if explode and u8(A.wIsInBattle)~=0 then
        local c=scenario("explode_cleanup");use(stranger,c)
        to_menu(120,"A")
        for _=1,8 do if u8(A.wIsInBattle)==0 then break end;local r=drv.run();c.run=r;if not r.ok then to_menu(120,nil)end end
        check(c,"stray battle ended by RUN before the explode entry",u8(A.wIsInBattle)==0,JSON.encode(world()))
    end
    if explode then use(squirtle,explode,XE,Battle.EXPLODE) else use(stranger,battle) end
    if u8(A.wIsInBattle)==0 then check(battle,"entered a wild battle by walking (step_one)",enter_battle(battle),JSON.encode(world()))
    else battle.menu=to_menu(240,"A");check(battle,"battle from the probe reached its menu",battle.menu and battle.menu.ok,JSON.encode(battle.menu))end
    shot("battle_menu");battle.world=world()
    -- fight_first: the linked Squirtle is STILL ACTIVE (no switch, no Transform yet); FIGHT commit must reach
    -- ExecutePlayerMove+0 with the ACTIVE decision (wBattleMonHP 0000 + CANNOT_MOVE) and the engine must faint it
    if want("fight_first") then
        local s=scenario("fight_first");use(squirtle,s)
        local menu_rows=s.not_reached;wait(30)
        check(s,"menu state with the active linked member yields not_reached only",s.not_reached==menu_rows+30,fmt("%d->%d reached=%d",menu_rows,s.not_reached,#s.reached))
        s.world_before=world()
        check(s,"the linked mon is the active battle mon",u8(A.wPlayerMonNumber)==0 and s.world_before.battle_species==squirtle.species,JSON.encode(s.world_before))
        local base=#s.reached
        if drv.state().x~=5 then s.choose=drv.choose("FIGHT") else s.choose={skipped="move menu already open"} end
        local trace=drv.commit_move(1,900);s.commit_trace=trace
        wait(600,function()return landed(s,base,squirtle) end)
        local row=landed(s,base,squirtle) and s.reached[#s.reached] or nil
        check(s,"a site was reached and written for the ACTIVE linked member after FIGHT",row~=nil,fmt("rows after commit=%d stages=%s",#s.reached-base,JSON.encode(trace.stages or {})))
        if row then
            s.write_row={site=row.evidence.site,frame=row.evidence.frame,hook_frame=row.evidence.hook_frame,challenge=row.authority.challenge,writes=row.evidence.writes,
                state=row.evidence.state,world=row.world_at_finish}
            check(s,"the site was ExecutePlayerMove+0 with the ACTIVE footprint (wBattleMonHP 0000 + wPlayerSelectedMove $FF)",
                row.evidence.site=="player_action" and #row.evidence.writes==3 and row.evidence.writes[1].address==A.wBattleMonHP and row.evidence.writes[3].address==A.wPlayerSelectedMove
                and row.evidence.writes[3].after_hex=="ff",JSON.encode(row.evidence.writes))
            check(s,"the snapshot shows the active linked mon (slot 0, species/DVs/OT match, not transformed)",
                row.evidence.state.player_mon_number==0 and row.evidence.state.battle_species==squirtle.species and row.evidence.state.status3%16<8,JSON.encode(row.evidence.state))
            watch_after(s,row,"fight_first")
        end
        s.world_after=world();s.slot0=party_slot(0)
        check(s,"the linked mon fainted in the original engine (party HP 0000) with the active battle struct at 0000",
            s.slot0.hp_hex=="0000" and (s.world_after.battle_hp=="0000" or u8(A.wPlayerMonNumber)~=0 or u8(A.wIsInBattle)==0),JSON.encode(s.world_after))
        shot("fight_first_fainted")
        -- "Use next POKeMON?" -> yes -> Ditto; then end the battle by RUN attempts (Ditto is not linked: zero writes)
        use(stranger,s)
        for _=1,30 do if u8(A.wPlayerMonNumber)==1 or u8(A.wIsInBattle)==0 then break end;for _=1,3 do step({A=true})end;for _=1,20 do step(nil)end end
        to_menu(120,"A")
        for _=1,8 do if u8(A.wIsInBattle)==0 then break end;local r=drv.run();s.run=r;if not r.ok then to_menu(120,nil)end end
        s.world_final=world();shot("fight_first_after")
        note("fight_first final: "..JSON.encode(s.world_final))
    end
    -- free_window: fight_first in the free-loop form (handoff item 5). No bounded owner; ONE 64-frame window authority per
    -- issue, as the server issues it from a batch, entered `late` frames after its first frame and armed with the SAME
    -- table every frame until a site is reached or the window runs out, then the next window (the re-issue the server
    -- makes from the window receipt). tests/live/test_gen1_battle_force.py settles every window with verify_window.
    if want("free_window") then
        local s=scenario("free_window");use(squirtle,s)
        current.window={late=8,windows=JSON.array(),consumed=false}
        local menu_rows=s.not_reached;wait(30)
        check(s,"menu state with the active linked member yields not_reached only",s.not_reached==menu_rows+30,fmt("%d->%d reached=%d",menu_rows,s.not_reached,#s.reached))
        s.world_before=world()
        check(s,"the linked mon is the active battle mon",u8(A.wPlayerMonNumber)==0 and s.world_before.battle_species==squirtle.species,JSON.encode(s.world_before))
        check(s,"frames advance with emu.frameadvance, not a bounded owner",owner==nil,"owner="..tostring(owner))
        local base=#s.reached
        if drv.state().x~=5 then s.choose=drv.choose("FIGHT") else s.choose={skipped="move menu already open"} end
        local trace=drv.commit_move(1,900);s.commit_trace=trace
        wait(600,function()return landed(s,base,squirtle) end)
        local row=landed(s,base,squirtle) and s.reached[#s.reached] or nil
        check(s,"a site was reached and written for the ACTIVE linked member after FIGHT inside a late-entered window",row~=nil,
            fmt("rows after commit=%d windows=%d stages=%s",#s.reached-base,#current.window.windows,JSON.encode(trace.stages or {})))
        if row then
            -- the window the reached row closed (the driver may have stepped on and opened the next one already)
            local w;for _,candidate in ipairs(current.window.windows)do if candidate.authority.challenge==row.authority.challenge then w=candidate end end
            s.write_row={site=row.evidence.site,frame=row.evidence.frame,hook_frame=row.evidence.hook_frame,challenge=row.authority.challenge,writes=row.evidence.writes,
                state=row.evidence.state,world=row.world_at_finish}
            check(s,"the site was ExecutePlayerMove+0 with the ACTIVE footprint (wBattleMonHP 0000 + wPlayerSelectedMove $FF)",
                row.evidence.site=="player_action" and #row.evidence.writes==3 and row.evidence.writes[1].address==A.wBattleMonHP and row.evidence.writes[3].address==A.wPlayerSelectedMove
                and row.evidence.writes[3].after_hex=="ff",JSON.encode(row.evidence.writes))
            check(s,"the reached row closed its window: entered late, contiguous rows, the reached row last",
                w.authority.challenge==row.authority.challenge and w.rows[1].frame==w.authority.frames.first+current.window.late and w.rows[#w.rows].site=="player_action"
                and #w.rows==w.rows[#w.rows].frame-w.rows[1].frame+1,fmt("first=%d entry=%d rows=%d",w.authority.frames.first,w.rows[1].frame,#w.rows))
            watch_after(s,row,"free_window")
        end
        s.windows=current.window.windows;current.window=nil
        s.world_after=world();s.slot0=party_slot(0)
        check(s,"the linked mon fainted in the original engine (party HP 0000) with the active battle struct at 0000",
            s.slot0.hp_hex=="0000" and (s.world_after.battle_hp=="0000" or u8(A.wPlayerMonNumber)~=0 or u8(A.wIsInBattle)==0),JSON.encode(s.world_after))
        shot("free_window_fainted")
        use(stranger,s)
        for _=1,30 do if u8(A.wPlayerMonNumber)==1 or u8(A.wIsInBattle)==0 then break end;for _=1,3 do step({A=true})end;for _=1,20 do step(nil)end end
        to_menu(120,"A")
        for _=1,8 do if u8(A.wIsInBattle)==0 then break end;local r=drv.run();s.run=r;if not r.ok then to_menu(120,nil)end end
        s.world_final=world();shot("free_window_after")
        note("free_window final: "..JSON.encode(s.world_final))
    end
    -- explode_first: the EXPLODE binding on the ACTIVE linked Squirtle (armed since the walk: see the battle entry above)
    if explode then
        local s=explode
        s.world_before=world()
        check(s,"the linked mon is the active battle mon",u8(A.wPlayerMonNumber)==0 and s.world_before.battle_species==squirtle.species,JSON.encode(s.world_before))
        local head=landed(s,0,squirtle) and s.reached[#s.reached] or nil
        local moves,pp=hexrange(A.wBattleMonMoves,4),hexrange(A.wBattleMonPP,4)
        check(s,"MainInBattleLoop+0 was reached before the first menu with the EXPLODE footprint (4 x $99 moves + 4 x PP 5)",
            head~=nil and head.evidence.site=="loop_head" and #head.evidence.writes==8 and head.evidence.writes[1].address==A.wBattleMonMoves
            and head.evidence.writes[5].address==A.wBattleMonPP and moves=="99999999" and pp=="05050505",
            JSON.encode({rows=#s.reached,site=head and head.evidence.site or JSON.null,writes=head and head.evidence.writes or JSON.null,moves=moves,pp=pp}))
        if head then s.loop_head_row={site=head.evidence.site,frame=head.evidence.frame,hook_frame=head.evidence.hook_frame,challenge=head.authority.challenge,
            writes=head.evidence.writes,state=head.evidence.state,world=head.world_at_finish} end
        local menu_rows=s.not_reached;wait(30)
        check(s,"menu state with the active linked member yields not_reached only",s.not_reached==menu_rows+30,fmt("%d->%d reached=%d",menu_rows,s.not_reached,#s.reached))
        local base=#s.reached
        local enemy_before=u8(A.wEnemyMonHP)*256+u8(A.wEnemyMonHP+1)
        if drv.state().x~=5 then s.choose=drv.choose("FIGHT") else s.choose={skipped="move menu already open"} end
        wait(30);shot("explode_first_after_write") -- the move menu: EXPLOSION in every slot
        local trace=drv.commit_move(1,900);s.commit_trace=trace
        wait(600,function()return landed(s,base,squirtle) end)
        local row=landed(s,base,squirtle) and s.reached[#s.reached] or nil
        check(s,"ExecutePlayerMove+0 was reached and written for the ACTIVE linked member after FIGHT",row~=nil and row.evidence.site=="player_action",
            fmt("rows after commit=%d stages=%s",#s.reached-base,JSON.encode(trace.stages or {})))
        if row then
            s.write_row={site=row.evidence.site,frame=row.evidence.frame,hook_frame=row.evidence.hook_frame,challenge=row.authority.challenge,writes=row.evidence.writes,
                state=row.evidence.state,world=row.world_at_finish}
            check(s,"the action-site write is wPlayerSelectedMove=$99 alone, already $99 from the menu (the slot re-derivation): a one-byte no-op",
                #row.evidence.writes==1 and row.evidence.writes[1].address==A.wPlayerSelectedMove and row.evidence.writes[1].before_hex=="99"
                and row.evidence.writes[1].after_hex=="99" and row.evidence.state.selected_move==0x99,JSON.encode(row.evidence))
        end
        -- the engine's own turn: ExplodeEffect zeroes the user's HP and status, the wild mon takes the hit
        wait(900,function()return hexrange(A.wBattleMonHP,2)=="0000" or party_slot(0).hp_hex=="0000" or u8(A.wPlayerMonNumber)~=0 or u8(A.wIsInBattle)==0 end)
        wait(60)
        local enemy_after=u8(A.wEnemyMonHP)*256+u8(A.wEnemyMonHP+1)
        s.engine={selected_move_at_execute=row and row.evidence.state.selected_move or JSON.null,selected_move_after_a=trace.selected_move,
            enemy_hp_before=enemy_before,enemy_hp_after=enemy_after,slot0_hp=party_slot(0).hp_hex,battle_hp=hexrange(A.wBattleMonHP,2),
            active=u8(A.wPlayerMonNumber),in_battle=u8(A.wIsInBattle),frame=emu.framecount()}
        shot("explode_first_fainted")
        check(s,"the linked mon exploded itself in the original engine (party HP 0000)",party_slot(0).hp_hex=="0000",JSON.encode(s.engine))
        check(s,"the wild mon took the Explosion (enemy HP dropped)",enemy_after<enemy_before,JSON.encode(s.engine))
        -- "Use next POKeMON?" -> Ditto (not linked: zero writes); then end the battle by RUN attempts, or it is already over
        use(stranger,s)
        for _=1,30 do if u8(A.wPlayerMonNumber)==1 or u8(A.wIsInBattle)==0 then break end;for _=1,3 do step({A=true})end;for _=1,20 do step(nil)end end
        if u8(A.wIsInBattle)~=0 then to_menu(120,"A") end
        for _=1,8 do if u8(A.wIsInBattle)==0 then break end;local r=drv.run();s.run=r;if not r.ok then to_menu(120,nil)end end
        s.world_final=world();shot("explode_first_after")
        note("explode_first final: "..JSON.encode(s.world_final))
    end
    -- benched: PKMN -> Ditto in while Squirtle is the linked member
    if want("benched") then
        local s=scenario("benched");use(squirtle,s)
        local menu_rows=s.not_reached;wait(30)
        check(s,"menu state with the linked member yields not_reached only",s.not_reached==menu_rows+30,fmt("%d->%d reached=%d",menu_rows,s.not_reached,#s.reached))
        local base=#s.reached
        local trace=drv.switch_to(1);s.switch_trace=trace
        wait(600,function()return landed(s,base,squirtle) or u8(A.wIsInBattle)==0 end)
        local row=landed(s,base,squirtle) and s.reached[#s.reached] or nil
        check(s,"switch completed (Ditto active)",trace.ok and u8(A.wPlayerMonNumber)==1,JSON.encode({trace=trace,active=u8(A.wPlayerMonNumber)}))
        check(s,"a site was reached and written for the BENCHED linked member",row~=nil and row.evidence.site=="player_action",fmt("rows after switch=%d",#s.reached-base))
        if row then
            s.write_row={site=row.evidence.site,frame=row.evidence.frame,hook_frame=row.evidence.hook_frame,challenge=row.authority.challenge,writes=row.evidence.writes,
                state=row.evidence.state,world=row.world_at_finish}
            check(s,"the write is party-only (3 bytes: HP hi, HP lo, status) and the battle struct is untouched",
                #row.evidence.writes==3 and row.world_at_finish.battle_hp~="0000",JSON.encode(row.evidence.writes))
            watch_after(s,row,"benched")
        end
        s.slot0=party_slot(0)
        check(s,"benched linked slot reads HP 0000 status 00",s.slot0.hp_hex=="0000" and s.slot0.status==0,JSON.encode(s.slot0))
        -- HasMonFainted must refuse sending Squirtle back out
        use(stranger,s)
        to_menu(120,"B")
        local back=drv.switch_to(0);s.switch_back=back
        shot("benched_switch_back_refused")
        check(s,"the engine refuses to send the benched mon back out",u8(A.wPlayerMonNumber)==1 and u8(A.wIsInBattle)~=0,JSON.encode({back=back,active=u8(A.wPlayerMonNumber)}))
        to_menu(120,"B")
    end
    -- transform: Ditto (not linked) uses TRANSFORM
    if want("transform") then
        local s=scenario("transform");use(stranger,s)
        local w0=world()
        if drv.state().x~=5 then s.choose=drv.choose("FIGHT") else s.choose={skipped="move menu already open"} end
        local trace=drv.commit_move(1,900);s.commit_trace=trace
        to_menu(120,nil)
        local w1=world();s.world_before=w0;s.world_after=w1
        check(s,"TRANSFORM was committed and executed",trace.ok and trace.stages.execute_player_move~=nil,JSON.encode(trace))
        check(s,"TRANSFORMED bit set and the battle struct now carries the enemy species",math.floor(w1.status3/8)%2==1 and w1.battle_species~=ditto.species,JSON.encode(w1))
        shot("transformed")
    end
    -- player_action: Ditto linked while transformed -> FIGHT commit -> skip + faint -> black-out
    if want("player_action") then
        local s=scenario("player_action");use(ditto,s)
        local menu_rows=s.not_reached;wait(30)
        check(s,"menu state with the transformed linked member yields not_reached only",s.not_reached==menu_rows+30,fmt("%d->%d reached=%d",menu_rows,s.not_reached,#s.reached))
        s.world_before=world()
        local base=#s.reached
        if drv.state().x~=5 then s.choose=drv.choose("FIGHT") else s.choose={skipped="move menu already open"} end
        local trace=drv.commit_move(1,900);s.commit_trace=trace
        wait(900,function()return landed(s,base,ditto) end)
        local row=landed(s,base,ditto) and s.reached[#s.reached] or nil
        check(s,"a site was reached and written for the transformed linked member after FIGHT",row~=nil,fmt("rows after commit=%d trace=%s",#s.reached-base,JSON.encode(trace.stages or {})))
        if row then
            s.write_row={site=row.evidence.site,frame=row.evidence.frame,hook_frame=row.evidence.hook_frame,challenge=row.authority.challenge,writes=row.evidence.writes,
                state=row.evidence.state,world=row.world_at_finish}
            check(s,"the site was ExecutePlayerMove+0 with the CANNOT_MOVE skip written",row.evidence.site=="player_action" and #row.evidence.writes==3,JSON.encode(row.evidence.writes))
            check(s,"the snapshot shows TRANSFORMED with a foreign battle species",math.floor(row.evidence.state.status3/8)%2==1 and row.evidence.state.battle_species~=ditto.species,JSON.encode(row.evidence.state))
            watch_after(s,row,"player_action")
        end
        s.world_after=world()
        check(s,"the linked mon fainted (party HP 0000) or the black-out already healed it outside the battle",
            party_slot(1).hp_hex=="0000" or (u8(A.wIsInBattle)==0 and s.world_after.map~=s.world_before.map),JSON.encode(s.world_after))
        for _=1,60 do if u8(A.wIsInBattle)==0 then break end;for _=1,3 do step({A=true})end;for _=1,20 do step(nil)end end
        wait(120)
        shot("after_battle");s.world_final=world()
        check(s,"the battle ended (black-out: both party mons were down)",u8(A.wIsInBattle)==0,JSON.encode(s.world_final))
    end
    do
        local sram_after=memory.read_bytes_as_array(0,0x2000,"SRAM")
        local diff=0;for i=1,#sram_before do if sram_before[i]~=sram_after[i] then diff=diff+1 end end
        result.sram_diff_bytes=diff
        t.check("SRAM unchanged across the whole gate",diff==0,fmt("%d bytes differ",diff))
    end
    result.driver_hits=drv.hits();result.owner_final=owner and owner.status() or JSON.null
end,debug.traceback)
result.passed=ok and t.failures==0;result.error=not ok and tostring(why)or nil
if not ok then note("ERROR: "..tostring(why)) end
if owner then pcall(function()owner.set_held(true,"battle force live gate complete")end)end
local out=assert(io.open(config.output,"w"));out:write(assert(JSON.encode(result)));out:close()
t.check("battle force live gate completed",ok,tostring(why));t.finish()
