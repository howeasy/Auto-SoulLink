-- Read-only native fishing state decides the next ordinary button.
local function fishing_button(step)
    -- SOURCE fishing.c enum and callbacks; facts() refuses enum drift.
    if step==8 or step==9 or (step>=11 and step<=17) then return "A" end
    return nil -- INIT/dots/check: early A cancels a native cast.
end

local function fish_native(ctx, f)
    local function fishing_step()
        for i=0,f.task_count-1 do
            local at=f.tasks+i*f.task_size
            local fn=memory.read_u32_le(at,"System Bus")
            if memory.read_u8(at+f.task_active_off,"System Bus")~=0
               and (fn & 0x01FFFFFF)==((f.fishing_task|1) & 0x01FFFFFF) then
                return memory.read_s16_le(at+f.task_data_off,"System Bus"),i
            end
        end
    end
    local CAST_LIMIT=30
    for cast=1,CAST_LIMIT do
        ctx.G.tap("Select",3,1)
        local saw,last=false,nil
        for frame=1,1800 do
            if ctx.in_battle() then return true end
            local step,id=fishing_step()
            if step then
                saw=true
                if cast==1 or step~=last then
                    ctx.jlog("FISHING_STEP",{cast=cast,frame=emu.framecount(),task=id,step=step,
                        press=fishing_button(step) or "none"})
                end
                last=step
                local press=fishing_button(step)
                if press then ctx.G.tap(press,1,1) else ctx.G.advance() end
            else
                if saw and last and last>=13 and ctx.on_field() and ctx.player_idle() then break end
                if not saw and frame>120 then return false,"registered OLD_ROD did not start native Task_Fishing" end
                ctx.G.advance()
            end
        end

    end
    return false,"native Old Rod CAST_LIMIT=30 exhausted (no encounter forced)"
end

local function native_enemy_ready(ctx)
    local entry=ctx.reader.read_battle()
    local early=entry and entry.enemy_party and entry.enemy_party[1]
    ctx.jlog("STATIC_ENEMY_ENTRY",{species=early and early.species or -1,
        level=early and early.level or -1,hp=early and early.hp or -1})
    -- Reuse the carrier's native intro/menu witness before trusting an enemy record.
    -- Slot membership remains strict after this wait; a mismatch is never retried.
    local decision=ctx.await_turn(30,"A")
    if decision~="action" then return nil,"native enemy never reached action menu: "..tostring(decision) end
    local snapshot=ctx.reader.read_battle()
    local foe=snapshot and snapshot.enemy_party and snapshot.enemy_party[1]
    if not foe or foe.species==0 then return nil,"native enemy record unreadable" end
    ctx.jlog("STATIC_ENEMY_READY",{species=foe.species,level=foe.level,hp=foe.hp,moves=foe.moves})
    return foe
end

local function live_selector(f)
    local sb1=memory.read_u32_le(f.sb1_pointer,"System Bus")
    local at=sb1+f.vars_off+2*(f.selector_var-0x4000)
    if sb1<0x02000000 or at+2>0x02040000 then return nil,"selector pointer unreadable" end
    return memory.read_u16_le(at,"System Bus"),sb1
end

local function rock_probe_object_present(ctx, f, obj)
    for i=1,obj.object_count-1 do
        local at=obj.object_events+i*obj.object_stride
        if (memory.read_u8(at,"System Bus") & obj.active_mask)~=0
           and memory.read_u16_le(at+obj.graphics_off,"System Bus")==obj.graphics_id
           and memory.read_u8(at+obj.map_num_off,"System Bus")==f.num
           and memory.read_u8(at+obj.map_group_off,"System Bus")==f.group
           and memory.read_s16_le(at+obj.coords_off,"System Bus")-obj.map_offset==obj.npc_x
           and memory.read_s16_le(at+obj.coords_off+2,"System Bus")-obj.map_offset==obj.npc_y then
            ctx.jlog("ROCK_PLAYER_OBJECT",{slot=i,address=at,x=obj.npc_x,y=obj.npc_y,
                graphics_id=memory.read_u16_le(at+obj.graphics_off,"System Bus"),script=obj.script})
            return true
        end
    end
    return false
end

local function rock_probe_bare(raw)
    local function named(value,name)
        if type(value)~="table" then return false end
        for _,n in ipairs(value.names or {}) do if n==name then return true end end
        return false
    end
    local pal=raw and raw.gPaletteFade
    return type(raw)=="table" and named(raw.callback1,"CB1_Overworld") and named(raw.callback2,"CB2_Overworld")
        and type(raw.sLockFieldControls)=="table" and raw.sLockFieldControls.raw==0
        and type(raw.field_message_box_mode)=="table" and raw.field_message_box_mode.raw==0
        and type(pal)=="table" and type(pal.active_word)=="number" and tonumber(pal.active_mask)~=nil
        and (pal.active_word & tonumber(pal.active_mask))==0
end

-- Driver-only native script trigger. The signed checkpoint still requires SHUTDOWN.
local function rock_native_recover(ctx, read, f)
    local start=ctx.emulator.framecount()
    local function status(raw)
        return type(raw.sGlobalScriptContextStatus)=="table" and raw.sGlobalScriptContextStatus.raw or nil
    end
    local function sample(stage)
        local raw=read();local x,y=ctx.G.pos(ctx.cp);local age=ctx.emulator.framecount()-start
        ctx.jlog("ROCK_WAIT_RECOVERY",{stage=stage,frame=ctx.emulator.framecount(),stall_frames=age,
            stall_seconds_60fps=age/60,status=status(raw),x=x,y=y,raw=raw})
        return raw
    end
    local raw=sample("before")
    for _=1,600 do
        if rock_probe_bare(raw) then break end
        ctx.G.idle(1);raw=read()
    end
    if not rock_probe_bare(raw) then sample("no-bare-field");return "no-bare-field" end
    if status(raw)==2 then sample("already-shutdown");return "already-shutdown" end
    if status(raw)~=1 then sample("unknown-context");return "unknown-context" end
    local obj=f.rock_player_probe;local x,y=ctx.G.pos(ctx.cp)
    if not obj or obj.npc_x~=f.x+1 or obj.npc_y~=f.y-1
       or ctx.game_flag(obj.hidden_flag)~=false or not ctx.rock_probe_object_present(obj) then
        sample("no-proven-object");return "no-proven-object"
    end
    if x==f.x and y==f.y then
        ctx.G.tap("Up",3,13)
        for _=1,100 do
            if ctx.player_idle() then break end
            ctx.G.idle(1)
        end
        raw=sample("one-step");x,y=ctx.G.pos(ctx.cp)
        if not ctx.player_idle() or not rock_probe_bare(raw) then return "step-not-settled" end
    end
    if x~=f.x or y~=f.y-1 then sample("wrong-tile");return "wrong-tile" end
    ctx.G.tap("Right",2,20);sample("object-facing")
    x,y=ctx.G.pos(ctx.cp)
    if x~=f.x or y~=f.y-1 then return "object-absent-or-player-moved" end
    ctx.G.tap("A",3,30);raw=sample("object-interact")
    for _=1,40 do
        if status(raw)==2 and rock_probe_bare(raw) then sample("context-overwritten-by-npc-script");return "context-overwritten-by-npc-script" end
        -- Own source MSGBOX_DEFAULT has no battle, item, choice or warp branch.
        ctx.G.tap("A",1,15);raw=read()
    end
    if status(raw)==2 and rock_probe_bare(raw) then sample("context-overwritten-by-npc-script");return "context-overwritten-by-npc-script" end
    sample("dialogue-not-shutdown")
    return "dialogue-not-shutdown"
end

-- Explicit diagnostic only: ordinary native player actions, never a policy/record write.
local function rock_player_inputs(ctx, read, f)
    local start=ctx.emulator.framecount()
    local function status(raw) return raw.sGlobalScriptContextStatus and raw.sGlobalScriptContextStatus.raw end
    local bare=rock_probe_bare
    local function sample(stage)
        local raw=read();local x,y=ctx.G.pos(ctx.cp)
        ctx.jlog("ROCK_PLAYER_PROBE",{stage=stage,frame=ctx.emulator.framecount(),age=ctx.emulator.framecount()-start,
            x=x,y=y,status=status(raw),raw=raw})
        return raw
    end
    local raw=sample("capture-return")
    for _=1,600 do
        if bare(raw) then break end
        ctx.G.idle(1);raw=read()
    end
    if not bare(raw) then sample("no-bare-field");return "no-bare-field" end
    if status(raw)==2 then sample("already-shutdown");return "already-shutdown" end
    if status(raw)~=1 then sample("unknown-context");return "unknown-context" end
    sample("idle-before")
    ctx.G.idle(300)
    raw=sample("idle-after")
    if status(raw)==2 then return "idle" end
    if not bare(raw) then return "field-not-bare-after-idle" end
    ctx.G.tap("Start",3,30)
    for _=1,300 do
        if ctx.SP.EMH.menu_ready() then break end
        ctx.G.idle(1)
    end
    sample("menu-open")
    if not ctx.SP.EMH.menu_ready() then return "start-menu-not-opened" end
    ctx.G.tap("B",3,30)
    ctx.G.idle(60);raw=sample("menu-close")
    if status(raw)==2 then return "menu-close" end
    if not bare(raw) then return "field-not-bare-after-menu" end
    ctx.G.tap("B",3,30);raw=sample("empty-B")
    if status(raw)==2 then return "empty-B" end
    if not bare(raw) then return "field-not-bare-after-B" end
    ctx.G.tap("A",3,30);raw=sample("empty-A")
    if status(raw)==2 then return "empty-A" end
    if not bare(raw) then return "field-not-bare-after-A" end
    local x,y=ctx.G.pos(ctx.cp)
    if x~=f.x or y~=f.y then return "displaced-before-step" end
    ctx.G.tap("Up",3,13)
    for _=1,100 do
        if ctx.player_idle() then break end
        ctx.G.idle(1)
    end
    raw=sample("one-step")
    if not ctx.player_idle() then return "step-still-in-flight" end
    if status(raw)==2 then return "one-step" end
    x,y=ctx.G.pos(ctx.cp)
    if not bare(raw) or x~=f.x or y~=f.y-1 then return "step-did-not-reach-cleared-rock-tile" end
    return rock_native_recover(ctx,read,f)
end

local function rock_rng_prep(f)
    assert(f.rock_rng_size==16,"own SFC32 state size drift")
    assert(f.rock_rng_address>=0x03000000 and f.rock_rng_address+16<=0x03008000,"RNG symbol outside IWRAM")
    local before={}
    for i=0,15 do
        before[#before+1]=memory.read_u8(f.rock_rng_address+i,"System Bus")
        memory.write_u8(f.rock_rng_address+i,tonumber(f.rock_rng_state_hex:sub(i*2+1,i*2+2),16),"System Bus")
    end
    return before
end

-- Pending SYNTH prerequisites only; every battle/throw/RUN is driven through native inputs.
return function(ctx)
    local f = ctx.D.static_wild_facts
    if not f or not ctx.wait_go() then return false, "unproven static/wild setup or no GO" end
    local seen = {}
    local rng_prepared,rng_armed=false,false
    local rng_draw,rng_pending=0,false
    if f.case=="rock" then
        for _,delta in ipairs({0,0x02000000}) do
            assert(event.on_bus_exec(function(callback)
                if rng_armed and rng_draw<2 then
                    assert(not rng_pending,"unexpected nested SYNTH RNG draw")
                    rng_pending=true
                    local counter=memory.read_u32_le(f.rock_rng_address+12,"System Bus")
                    assert(counter==17+rng_draw,"leaked draw before native Rock odds")
                    ctx.jlog("SYNTH_ROCK_RNG_DRAW",{phase="before",draw=rng_draw+1,counter=counter,
                        callback_address=callback,frame=emu.framecount()})
                end
            end,f.rock_rng_function+delta,"exp-rock-rng-before-"..delta,"System Bus"),"SYNTH RNG entry hook refused")
            assert(event.on_bus_exec(function(callback)
                if rng_armed and rng_pending then
                    rng_pending=false;rng_draw=rng_draw+1
                    local counter=memory.read_u32_le(f.rock_rng_address+12,"System Bus")
                    assert(counter==17+rng_draw,"leaked draw during native Rock RNG")
                    ctx.jlog("SYNTH_ROCK_RNG_DRAW",{phase="after",draw=rng_draw,counter=counter,
                        result=emu.getregister("R0"),modulus=f.rock_rng_modulus,
                        callback_address=callback,frame=emu.framecount()})
                    if rng_draw==2 then rng_armed=false end
                end
            end,f.rock_rng_return+delta,"exp-rock-rng-after-"..delta,"System Bus"),"SYNTH RNG return hook refused")
        end
    end
    for name, address in pairs(f.method_probes) do
        for _, delta in ipairs({0,0x02000000}) do
            local id = event.on_bus_exec(function(callback)
                if f.case=="rock" and name=="RockSmashWildEncounter" and not rng_prepared then
                    rng_prepared,rng_armed=true,true
                    ctx.jlog("SYNTH_ROCK_RNG_PREP",{frame=emu.framecount(),callback_address=callback,
                        address=f.rock_rng_address,before=rock_rng_prep(f),state_hex=f.rock_rng_state_hex,
                        counter=memory.read_u32_le(f.rock_rng_address+12,"System Bus"),scope=f.rock_rng_scope})
                end
                seen[name] = true
                ctx.jlog("STATIC_METHOD_PROBE",{name=name,address=callback,frame=emu.framecount(),r0=emu.getregister("R0")})
            end,address+delta,"exp-method-"..name.."-"..delta,"System Bus")
            assert(id,"native method probe refused")
        end
    end
    for name,address in pairs(f.post_capture_probes or {}) do
        local logged=false
        for _,delta in ipairs({0,0x02000000}) do
            assert(event.on_bus_exec(function(callback)
                if not logged and ctx.sent("capture")>0 then
                    logged=true
                    ctx.jlog("POST_CAPTURE_FLOW",{name=name,address=callback,frame=emu.framecount(),
                        captures=ctx.sent("capture")})
                end
            end,address+delta,"exp-post-capture-"..name.."-"..delta,"System Bus"),"post-capture diagnostic refused")
        end
    end
    local unexpected_faint = false
    for _, delta in ipairs({0,0x02000000}) do
        assert(event.on_bus_exec(function(callback)
            local battler = emu.getregister("R0")
            local move = memory.read_u16_le(f.current_move,"System Bus")
            ctx.jlog("STATIC_FAINT_MOVE",{address=callback,frame=emu.framecount(),battler=battler,move=move})
            if f.damp_slot and battler==1 then
                local self_ko=false
                for _,m in ipairs(f.self_ko_moves) do if move==m then self_ko=true end end
                if not self_ko then unexpected_faint=true end
            end
        end,f.faint_probe+delta,"exp-faint-move-"..delta,"System Bus"),"faint diagnostic hook refused")
        assert(event.on_bus_exec(function(callback)
            local move=memory.read_u16_le(f.current_move,"System Bus")
            for _,m in ipairs(f.self_ko_moves) do
                if move==m then ctx.jlog("STATIC_DAMP_GATE",{address=callback,frame=emu.framecount(),move=move,
                    last_used_ability=memory.read_u16_le(f.last_used_ability,"System Bus")}) end
            end
        end,f.damp_probe+delta,"exp-damp-gate-"..delta,"System Bus"),"Damp diagnostic hook refused")
    end
    local where = ctx.reader.read_location()
    local x,y = ctx.G.pos(ctx.cp)
    if not where or where.map_group~=f.group or where.map_num~=f.num or x~=f.x or y~=f.y then
        return false,"wrong pending static/wild seed tile"
    end
    local selector,sb1=live_selector(f)
    if not selector then return false,sb1 end
    if selector~=f.selector then return false,"native selector differs from pending fixture" end
    ctx.jlog("STATIC_SELECTOR_BEFORE",{selector=selector,pointer=sb1})
    local before = ctx.balls()
    ctx.jlog("STATIC_WILD_BEFORE",{balls=before,captures=ctx.sent("capture"),no_catch=ctx.sent("no_catch")})
    if not ctx.face(f.face) then return false,"cannot face native trigger" end
    local function battle() return ctx.in_battle() end
    local enter
    if f.case=="static" or f.case=="static_run" or f.case=="rock" then
        enter = ctx.mash_until(battle,120,"A")
    elseif f.case=="fish" then
        local why
        enter,why=fish_native(ctx,f)
        if not enter then return false,why end
    elseif f.case=="surf" then
        local surfing = ctx.mash_until(function()
            return (memory.read_u8(f.avatar,"System Bus") & 8)~=0
        end,60,"A")
        if not surfing then return false,"native Surf did not activate" end
        enter = ctx.wait_until(function()
            if battle() then return true end
            if ctx.on_field() and ctx.player_idle() then
                ctx.G.tap(f.swim_direction,8,20)
                if not battle() then ctx.G.tap(f.swim_back,8,20) end
            end
        end,120,"native water encounter")
    else
        enter = ctx.wait_until(function()
            if battle() then return true end
            if ctx.on_field() and ctx.player_idle() then
                local px=ctx.G.pos(ctx.cp)
                ctx.G.tap(px==f.x and "Right" or "Left",8,20)
            end
        end,120,"native land encounter")
    end
    if not enter then return false,"native encounter did not start (no encounter forced)" end
    local foe,enemy_why=native_enemy_ready(ctx)
    if not foe then return false,enemy_why end
    local in_slots=false
    for _,slot in ipairs(f.slots) do
        if foe.species==slot[3] and foe.level>=slot[1] and foe.level<=slot[2] then in_slots=true end
    end
    if not in_slots then return false,"native enemy differs from selected compiled slots" end
    local battle_selector,battle_pointer=live_selector(f)
    if not battle_selector then return false,battle_pointer end
    ctx.jlog("STATIC_WILD_BATTLE",{selector_pointer=battle_pointer,method=f.method,species=foe.species,level=foe.level,selector=battle_selector,
        scope=f.projection_scope,field_probe=seen[f.expected_probe] or false,moves=foe.moves})
    if f.case=="static_run" then
        if not ctx.run_away("static negative") then return false,"native RUN failed" end
        if not ctx.wait_until(function()return ctx.sent("no_catch")==1 end,30,"native no_catch") then
            return false,"static RUN did not publish no_catch"
        end
        ctx.jlog("STATIC_WILD_AFTER",{balls=ctx.balls(),captures=ctx.sent("capture"),no_catch=ctx.sent("no_catch")})
        ctx.jlog("STATIC_WILD_READY",{negative=true})
    else
        local player_probe
        if f.case=="rock" then
            ctx.rock_probe_object_present=function(obj)return rock_probe_object_present(ctx,f,obj)end
            player_probe=function(read)
                local diagnostic=os.getenv("SLINK_ROCK_PLAYER_PROBE")=="1"
                local outcome=diagnostic and rock_player_inputs(ctx,read,f) or rock_native_recover(ctx,read,f)
                ctx.jlog("ROCK_WAIT_RECOVERY_RESULT",{outcome=outcome,diagnostic=diagnostic,frame=emu.framecount()})
            end
        end
        local key,why=ctx.catch("static/wild",true,f.ball_item,player_probe)
        if unexpected_faint then return false,"static foe KO by a non-explosion move; stop for diagnosis" end
        if not key then return false,"native catch failed: "..tostring(why) end
        if not ctx.wait_until(function()return ctx.sent("capture",key)==1 end,60,"ordinary capture TX") then
            return false,"ordinary capture missing"
        end
        ctx.jlog("STATIC_WILD_AFTER",{balls=ctx.balls(),captures=ctx.sent("capture"),no_catch=ctx.sent("no_catch")})
        ctx.jlog("STATIC_WILD_READY",ctx.last_sent("capture"))
    end
    if not ctx.wait_go("SAVE") then return false,"native settlement never released SAVE" end
    if f.case~="static_run" then
        local cap=ctx.last_sent("capture")
        if not ctx.wait_until(function()return ctx.find(cap.key)~=nil end,120,"linked mon back in party") then
            return false,"linked mon remains boxed or absent"
        end
    end
    return ctx.save("static/wild "..f.case)
end
