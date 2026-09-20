-- Manager-selected canonical companion, blank SaveRAM, normal New Game inputs.
-- The native entry claims its owner BEFORE the first frame after launcher load;
-- the observed/go handshake and intro frames precede that load. Unlike the
-- non-native free-service gate, menu inputs must be supplied on clean boot frames.
-- No CPU/register/cartridge writes; the only WRAM edit is a restored byte probe.
-- With input.progression the SAME processes continue after the 1x/3x windows through the
-- original game (joypad only, RAM/source observation) to the Viridian Cable Club receptionist.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local JSON=dofile(ROOT.."/lua/json_codec.lua")
local function read(path)
    local file=io.open(path,"r");if not file then return nil end
    local value=assert(JSON.decode(file:read("*a")));file:close();return value
end
local input=assert(read(assert(os.getenv("SLINK_LAUNCHER_TEST_INPUT"))))
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_native_selected_fresh_gate",{no_boot=true})
package.path=ROOT.."/lua/?.lua;"..ROOT.."/data/games/gen1_rby/?.lua;"..package.path
local clock=assert(dofile(ROOT.."/lua/platform_clock.lua").new())
local function publish(name,value)
    local path=input.directory.."/"..name.."-"..input.player..".json"
    local file=assert(io.open(path..".tmp","w"));file:write(assert(JSON.encode(value)));file:close()
    assert(os.rename(path..".tmp",path))
end
local function shot(name)client.screenshot(input.directory.."/"..input.player.."-"..name..".png")end
local symbols={}
do
    local source=t.variant=="yellow"and"pokeyellow"or"pokered"
    local target=t.variant=="blue"and"pokeblue"or source
    for line in io.lines(ROOT.."/.cache/pret/"..source.."/"..target..".sym")do
        local _,address,name=line:match("^(%x+):(%x+) (%S+)$")
        if address then symbols[name]=tonumber(address,16)end
    end
end
local function sym(name)return memory.read_u8(assert(symbols[name]),"System Bus")end
local idle={A=false,B=false,Start=false,Select=false,Up=false,Down=false,Left=false,Right=false}
local beat=0
local function menu_inputs()
    beat=beat+1;local moment=beat%16
    local buttons={A=moment<2,Start=moment==8}
    if sym("wMaxMenuItem")==3 and sym("wTopMenuItemY")==2 and sym("wTopMenuItemX")==1 then
        buttons={Down=sym("wCurrentMenuItem")==0,A=sym("wCurrentMenuItem")>0 and moment<2}
    end
    local pressed={};for key,value in pairs(idle)do pressed[key]=buttons[key]or value end
    joypad.set(pressed)
end
local saveram=assert(os.getenv("SLINK_GATE_SAVERAM"))
local save_directory=assert(os.getenv("SLINK_SAVERAM_DIRECTORY"))
assert(saveram:sub(1,#save_directory)==save_directory and saveram:match("candidate%.SaveRAM$"),
    "the gate must use its isolated candidate SaveRAM")
local save=assert(io.open(saveram,"rb"));local blank=save:read("*a");save:close()
assert(blank==string.rep(string.char(255),0x8000),"native fresh gate requires blank SaveRAM")
assert(gameinfo.getromhash():lower()==input.rom_sha1,"gate did not boot the exact Manager artifact")
publish("observed",{variant=t.variant,rom_sha1=gameinfo.getromhash():lower(),
    saveram_path=saveram,saveram_directory=save_directory})
local deadline=os.time()+45
while not read(input.directory.."/go.json")do
    if read(input.directory.."/abort.json")then
        t.check("Manager-selected native launch reached the paired go signal",false,"aborted before go")
        t.finish();return
    end
    assert(os.time()<deadline,"Manager launch timed out");t.step({})
end
for _=1,120 do t.step({})end;shot("intro")

local original_yield,original_advance=emu.yield,emu.frameadvance
local early_claim_frame,held_frame,loop_started,first_client_frame,frames_driven=nil,nil,nil,nil,0
local phases=JSON.array();local planned=assert(input.phases)
local index,current,reported,finished=0,nil,false,false
local function status_now()return SLINK_RUNTIME_STATUS and SLINK_RUNTIME_STATUS()end
local function begin_phase(status)
    index=index+1;local spec=planned[index]
    if not spec then current=nil;return false end
    assert(spec.frames%600==0 and type(spec.active)=="boolean","bounded 600-frame windows required")
    client.speedmode(spec.speed);client.frameskip(0);emu.minimizeframeskip(false)
    current={name=spec.name,speed=spec.speed,active=spec.active,planned_frames=spec.frames,
        began={frame=emu.framecount(),clock=clock()},window={frame=emu.framecount(),clock=clock()},
        windows=JSON.array(),probes=JSON.array()}
    if spec.active then
        for _=1,spec.frames/600 do current.probes[#current.probes+1]={address=assert(symbols.wPartyDataStart)+403}end
    end
    if index==1 then assert(status.runtime.pending_events==0,"free loop begins with a backlog")end
    return true
end
local function finish_phase()
    local now=clock();local frame=emu.framecount()
    phases[#phases+1]={name=current.name,speed=current.speed,active=current.active,planned_frames=current.planned_frames,
        frames=frame-current.began.frame,seconds=now-current.began.clock,
        fps=(frame-current.began.frame)/(now-current.began.clock),windows=current.windows,probes=current.probes}
end
local function finish_if_requested()
    if reported and read(input.directory.."/finish.json")then
        shot("free-end");finished=true
        t.check("Manager-selected native free service ran the fresh bedroom",true);t.finish()
    end
end
-- ---------------------------------------------------------------------------------------
-- Original-game progression (research receipt cx-fa4fad12). Yellow only in this experiment:
-- no starter choice, Yellow/Yellow starter clause exempt. Every stage is RAM-reactive with a
-- finite frame cap; inputs are ordinary joypad presses; nothing is written to WRAM/CPU/SRAM.
-- pret pokeyellow: bedroom REDS_HOUSE_2F $26 stairs (7,1); REDS_HOUSE_1F $25 door (2,7)/(3,7);
-- PALLET_TOWN $00 north edge trips Oak at wYCoord==1 (scripts/PalletTown.asm) -> OAKS_LAB $28;
-- EVENT_GOT_STARTER bit 34, EVENT_BATTLED_RIVAL_IN_OAKS_LAB bit 35 (constants/event_constants.asm,
-- identical in pokered; re-derived offline by tests/unit/test_gen1_native_selected_progression.py);
-- lab exit (4,11)/(5,11); ROUTE_1 $0C; VIRIDIAN_CITY $01 Pokemon Center door (23,25) ->
-- VIRIDIAN_POKECENTER $29 with the LINK_RECEPTIONIST object at (11,2) facing DOWN.
-- The receptionist dispatch is the companion patch's SlinkReceptionist (host query), so no
-- Pokedex/Parcel gate applies; the experiment ends at the receptionist_entered ACK.
local prog=input.progression
local MAP={HOUSE_2F=0x26,HOUSE_1F=0x25,PALLET=0x00,LAB=0x28,ROUTE_1=0x0C,VIRIDIAN=0x01,POKECENTER=0x29}
local EVENT={GOT_STARTER=34,BATTLED_RIVAL=35}
local PIKACHU=0x54
local function r16(name)local a=assert(symbols[name]);return memory.read_u8(a,"System Bus")*256+memory.read_u8(a+1,"System Bus")end
local function event_flag(bit)
    local a=assert(symbols.wEventFlags)+math.floor(bit/8)
    return memory.read_u8(a,"System Bus")&(1<<(bit%8))~=0
end
local function party()
    local count=sym("wPartyCount")
    return {count=count,species=count>0 and sym("wPartySpecies") or nil,
        level=count>0 and sym("wPartyMon1Level") or nil,hp=count>0 and r16("wPartyMon1HP") or nil}
end
local function journal_entry_phase(status)
    local file=status and status.journal_path and io.open(status.journal_path,"r");if not file then return nil end
    local ok,doc=pcall(function()local text=file:read("*a");return JSON.decode(text)end);file:close()
    if not ok or type(doc)~="table" then return nil end
    local payload=doc.document and doc.document.payload
    local entry=payload and payload.observation and payload.observation.receptionist_entry
    return entry and entry.phase or nil
end
local P={index=0,stage=nil,stages=JSON.array(),done=false,outcome=nil,last=nil,still=0,axis="y",side=1,sidestep=0,
    battles={wild=0,trainer=0},in_battle=false,trace=JSON.array(),samples=0,turned=0}
local STAGES={
    {name="bedroom",cap=1800,goal=function(m)return m~=MAP.HOUSE_2F end,target={7,1}},
    {name="house",cap=1800,goal=function(m)return m==MAP.PALLET end,target={3,7}},
    {name="oak",cap=9000,goal=function(m)return m==MAP.LAB end,target={10,1}},
    {name="starter",cap=9000,goal=function()return event_flag(EVENT.GOT_STARTER) and sym("wPartyCount")>=1 end,wait=true},
    {name="rival",cap=9000,goal=function()return event_flag(EVENT.BATTLED_RIVAL)end,target={4,11}},
    {name="exit_lab",cap=3600,goal=function(m)return m==MAP.PALLET end,target={4,11}},
    {name="route1",cap=6000,goal=function(m)return m==MAP.ROUTE_1 end,target={10,0}},
    {name="viridian",cap=12000,goal=function(m)return m==MAP.VIRIDIAN end,target={10,0}},
    {name="pokecenter",cap=9000,goal=function(m)return m==MAP.POKECENTER end,target={23,25}},
    {name="receptionist",cap=6000,goal=function(_,status)return journal_entry_phase(status)=="acknowledged" end,target={11,3},talk=true},
}
-- Root may retarget a stage's waypoint or cap from the input receipt after a traced run
-- (input.progression.targets[name] = {x,y}, .caps[name] = frames) without editing this gate.
for _,spec in ipairs(STAGES)do
    local over=prog and prog.targets and prog.targets[spec.name]
    if over then spec.target={over[1],over[2]} end
    local cap=prog and prog.caps and prog.caps[spec.name]
    if cap then spec.cap=cap end
end
local function stage_begin(frame)
    P.index=P.index+1;local spec=STAGES[P.index]
    if not spec then P.stage=nil;return end
    P.stage={spec=spec,began=frame,began_clock=clock(),moves=0,nudges=0,battles=0}
    P.last=nil;P.still=0;P.sidestep=0;P.turned=0
end
local function stage_end(frame,how)
    local s=P.stage
    P.stages[#P.stages+1]={name=s.spec.name,frames=frame-s.began,seconds=clock()-s.began_clock,moves=s.moves,nudges=s.nudges,
        battles=s.battles,how=how,map=sym("wCurMap"),x=sym("wXCoord"),y=sym("wYCoord")}
end
local function refuse(frame,reason)
    stage_end(frame,"refused")
    P.done=true;P.outcome="refused"
    shot("refused");local ok,status=pcall(status_now)
    publish("refused",{reason=reason,stage=P.stage.spec.name,frame=frame,stages=P.stages,party=party(),
        battles=P.battles,trace=P.trace,map=sym("wCurMap"),x=sym("wXCoord"),y=sym("wYCoord"),
        events={got_starter=event_flag(EVENT.GOT_STARTER),battled_rival=event_flag(EVENT.BATTLED_RIVAL)},
        status=ok and status or tostring(status)})
end
local function press(keys)
    local pressed={};for key,value in pairs(idle)do pressed[key]=keys[key]or value end
    joypad.set(pressed)
end
local function walk(frame,target)
    -- Goal-directed servo: hold the direction of the larger delta on the preferred axis; when the
    -- position stops changing, alternate axes, then sidestep alternately left/right. Ledges and
    -- walls are never modelled; the stage cap bounds any oscillation.
    local x,y=sym("wXCoord"),sym("wYCoord")
    local key=x..","..y
    if key~=P.last then P.last=key;P.still=0;P.stage.moves=P.stage.moves+1 else P.still=P.still+1 end
    local dx,dy=target[1]-x,target[2]-y
    if P.sidestep>0 then
        P.sidestep=P.sidestep-1;press({Left=P.side<0,Right=P.side>0});return
    end
    if P.still>0 and P.still%40==0 then
        P.axis=P.axis=="y" and "x" or "y"
        if P.still%80==0 then P.side=-P.side;P.sidestep=32 end
    end
    local axis=P.axis
    if axis=="y" and dy==0 then axis="x" elseif axis=="x" and dx==0 then axis="y" end
    if axis=="y" then press({Up=dy<0,Down=dy>0}) else press({Left=dx<0,Right=dx>0}) end
end
local function progress(frame,status)
    if P.done then joypad.set(idle);return end
    if not P.stage then
        if P.index==0 then client.speedmode(prog.speed or 300);stage_begin(frame) else P.done=true;return end
    end
    local spec=P.stage.spec
    local map=sym("wCurMap")
    local mon=party()
    -- Refusals: the starter must never faint (a Soul Link death), the party must stay ours.
    if mon.count>=1 and mon.hp==0 then return refuse(frame,"starter fainted (HP 0)") end
    if mon.count>=1 and mon.species~=PIKACHU then return refuse(frame,"party lead is not the Yellow starter") end
    if frame-P.stage.began>=spec.cap then return refuse(frame,"stage cap exceeded: "..spec.name) end
    if status and (status.phase~="free_service" or status.runtime.failed or not status.runtime.connected) then
        return refuse(frame,"service lost during "..spec.name)
    end
    P.samples=P.samples+1
    if P.samples%120==0 and #P.trace<400 then P.trace[#P.trace+1]={f=frame,m=map,x=sym("wXCoord"),y=sym("wYCoord"),s=spec.name}end
    -- Battles (wild 1 / trainer 2): FIGHT with the first move by mashing A; nothing else is selected.
    local battle=sym("wIsInBattle")
    if battle~=0 then
        if not P.in_battle then
            P.in_battle=true;P.stage.battles=P.stage.battles+1
            if battle==1 then P.battles.wild=P.battles.wild+1 else P.battles.trainer=P.battles.trainer+1 end
        end
        beat=beat+1;press({A=beat%16<2});return
    end
    P.in_battle=false
    if spec.goal(map,status) then
        stage_end(frame,"reached");stage_begin(frame)
        if not P.stage then
            P.done=true;P.outcome="arrived";shot("receptionist")
            publish("arrived",{stages=P.stages,battles=P.battles,party=mon,frame=frame,trace=P.trace,
                events={got_starter=event_flag(EVENT.GOT_STARTER),battled_rival=event_flag(EVENT.BATTLED_RIVAL)},
                map=sym("wCurMap"),x=sym("wXCoord"),y=sym("wYCoord"),status=status_now()})
        end
        return
    end
    beat=beat+1
    local held=sym("wJoyIgnore")~=0
    if spec.wait or held then
        -- Scripted dialogue: B advances text and answers NO (the Pikachu nickname prompt); it never
        -- selects a menu item, so nothing but the story's own path can be taken here.
        P.stage.nudges=P.stage.nudges+1;press({B=beat%16<2});return
    end
    local target=spec.target
    local x,y=sym("wXCoord"),sym("wYCoord")
    if spec.talk and x==target[1] and y==target[2] then
        -- Face the receptionist (blocked tile: a short Up tap only turns), then talk with A.
        if P.turned<12 then P.turned=P.turned+1;press({Up=true});return end
        P.stage.nudges=P.stage.nudges+1;press({A=beat%16<2});return
    end
    if P.still>=48 and P.still%48<16 then P.stage.nudges=P.stage.nudges+1;press({B=beat%16<2});return end
    walk(frame,target)
end
if prog then assert(t.variant=="yellow","the first progression experiment is Yellow only") end

emu.yield=function()
    original_yield()
    assert(not read(input.directory.."/abort.json"),"paired native selected gate aborted")
    finish_if_requested()
    local status=status_now()
    if not status or status.observation_loop then return end
    local reattach=status.native_reattach
    if status.host and status.host.physical_stop_verified and not early_claim_frame then
        early_claim_frame=emu.framecount()
    end
    if reattach and not held_frame then
        held_frame=emu.framecount()
        assert(status.host.physical_stop_verified and reattach.read.frame>=held_frame,
            "native reattach was not first read under the held owner")
        shot("held-reattach")
    end
    if reattach then assert(held_frame and reattach.read.frame>=held_frame,
        "the native read preceded the held reattach checkpoint")end
    if held_frame then
        assert(emu.framecount()==held_frame and status.host.physical_stop_verified,
            "native startup advanced before the server released its read")
    end
end
emu.frameadvance=function()
    local frame=emu.framecount()
    -- Do not call the full status/JSON encoder on each active frame: the
    -- existing strict gate samples every 120 frames for the same reason.
    local status=(not loop_started or (frame-loop_started.frame)%120==0)and status_now()or nil
    if not loop_started then
        if status and status.observation_loop then
            assert(held_frame and status.native_reattach and status.native_reattach.server
                and status.native_reattach.server.verdict=="released", "loop began without released native read")
            loop_started={frame=frame,clock=clock()};shot("free-start");joypad.set(idle)
            assert(begin_phase(status))
        else
            -- Native start owns and releases one *clean* boot frame at a time. The
            -- gate supplies ordinary menu buttons on those frames, never while held.
            assert(status and status.phase=="waiting_for_overworld" and not status.native_reattach,
                "unexpected pre-loop free frame")
            assert(status.host and status.host.lease_owned and status.host.owner_id
                and (not status.context or status.host.owner_id==status.context.physical_instance)
                and not status.host.held,"clean New Game frame lost its exclusive native owner")
            early_claim_frame=early_claim_frame or frame
            first_client_frame=first_client_frame or frame
            menu_inputs();frames_driven=frames_driven+1
            assert(frames_driven<20000,"normal New Game did not reach the held checkpoint")
        end
    elseif prog and reported and not P.done then
        progress(frame,status)
    else
        local buttons={};for key,value in pairs(idle)do buttons[key]=value end
        buttons.Right=frame-loop_started.frame<16;joypad.set(buttons)
        if current and current.active then
            local offset=frame-current.began.frame
            local probe=current.probes[math.floor(offset/600)+1]
            if probe then
                local inside=offset%600
                if not probe.injected and inside>=90 then
                    probe.original=memory.read_u8(probe.address,"System Bus")
                    probe.replacement=(probe.original+1)%256
                    probe.injected_frame=frame
                    memory.write_u8(probe.address,probe.replacement,"System Bus");probe.injected=true
                elseif probe.injected and not probe.restored and inside>=180 then
                    memory.write_u8(probe.address,probe.original,"System Bus")
                    probe.restored_frame=frame;probe.restored=true
                end
            end
        end
        if status and (frame-loop_started.frame)%120==0 then
            -- A parent-side assertion happens only after both ready receipts.
            -- Exit on its abort without adding filesystem polling to FPS windows.
            if reported and read(input.directory.."/abort.json")then error("paired native selected gate aborted")end
            assert(status.phase=="free_service" and status.runtime.connected
                and status.runtime.session_state=="admitted" and not status.runtime.failed,
                "native-selected free client lost its admitted service")
            assert(not status.engine_signals or not status.engine_signals.failed,"source observer failed")
            if current and frame-current.window.frame>=600 then
                local now=clock();local elapsed=now-current.window.clock
                current.windows[#current.windows+1]={first_frame=current.window.frame,last_frame=frame,
                    frames=frame-current.window.frame,seconds=elapsed,fps=(frame-current.window.frame)/elapsed,
                    pending_events=status.runtime.pending_events}
                current.window={frame=frame,clock=now}
            end
            if current and frame-current.began.frame>=current.planned_frames then
                finish_phase();begin_phase(status)
            elseif not current and not reported and status.runtime.pending_events==0 then
                publish("ready",{status=status,held_frame=held_frame,loop_started=loop_started,
                    early_claim_frame=early_claim_frame,first_client_frame=first_client_frame,
                    frame_after=frame,frames_driven=frames_driven,phases=phases,
                    final_source=require("gen1_full_save").capture(require("memory_gb"),t.variant)})
                reported=true
            end
            finish_if_requested()
        end
    end
    original_advance()
end
local ok,why=xpcall(function()dofile(input.launcher)end,debug.traceback)
emu.yield=original_yield;emu.frameadvance=original_advance
if not finished then
    pcall(function()shot("failed-frame")end)
    local status_ok,status=pcall(status_now)
    publish("failure",{error=tostring(why),status=status_ok and status or tostring(status)})
    t.check("Manager-selected native free-service launcher completed",false,tostring(why));t.finish()
end
