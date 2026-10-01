-- Ordinary RR School inputs. No staged party, flags, HP, fixture, or emulator writes.
return function(ctx)
    if not ctx.wait_go() then return false,"no GO" end
    local facts,key=ctx.go_value("BORROW"),ctx.go_value("TARGET")
    if not facts or not key then return false,"missing own-ROM borrow facts/target" end
    local mode=facts.case
    if mode~="menu" and mode~="battle" and mode~="opponent" then return false,"invalid borrowed case" end
    if ctx.player=="b" then
        if not ctx.wait_until(ctx.partner_done,2400,"borrow subject finished") then return false,"subject absent" end
        local result=ctx.partner_result() or ""
        return result:find("RESULT: PASS",1,true)~=nil,"idle peer; no save"
    end
    local function field()
        return ctx.play.on_field(ctx.cp) and ctx.G.pred_ok(ctx.cp,"script_context_status")
            and ctx.G.pred_ok(ctx.cp,"field_controls_locked")
    end
    local function borrowed() return ctx.session.game.party_borrowed() end
    local function u8(a) return memory.read_u8(a,"System Bus") end
    local function raw(slot)
        local at=assert(ctx.party_base())+slot*100;local bytes={}
        for i=0,99 do bytes[#bytes+1]=u8(at+i) end
        return string.char(table.unpack(bytes))
    end
    local function hex(s) return (s:gsub(".",function(c) return string.format("%02X",c:byte()) end)) end
    local function cursor() return ctx.peek("gPartyMenu",1,9) end
    local function picker() return ctx.party_menu_up() and ctx.task_live("Task_HandleChooseMonInput") end
    local function party_writes(start)
        local n=0;local base=assert(ctx.party_base())
        for i=start+1,#ctx.write_lines() do
            local w=ctx.write_lines()[i]
            if w.address<base+600 and w.address+w.len>base then n=n+1 end
        end
        return n
    end
    local signals,drain=ctx.session.signals,ctx.session.signals.drain
    signals.drain=function(self)
        local out=drain(self)
        for _,sig in ipairs(out) do
            if sig.kind=="borrowed_party_begin" or sig.kind=="borrowed_party_opponent_begin" or sig.kind=="borrowed_party_end" then
                ctx.jlog("BORROW_SIGNAL",{kind=sig.kind,point=sig.point,frame=ctx.emulator.framecount()})
            end
        end
        return out
    end
    local Routes=dofile(ctx.D.wt.."/lua/tests/gen3_routes.lua")
    local function route_trace(stage)
        local group,num=ctx.G.map(ctx.cp);local x,y=ctx.G.pos(ctx.cp);local tasks={}
        if ctx.sym and ctx.sym.gTasks then
            for i=0,15 do
                local at=ctx.sym.gTasks+i*40 -- same Task layout as duo main's task reader
                if u8(at+4)~=0 then tasks[#tasks+1]=memory.read_u32_le(at,"System Bus") end
            end
        end
        ctx.jlog("BORROW_ROUTE_STAGE",{stage=stage,map={group,num},pos={x,y},tasks=tasks,
            callback2=ctx.sym and ctx.sym.gMain and memory.read_u32_le(ctx.sym.gMain+4,"System Bus"),
            field=ctx.play.on_field(ctx.cp),controls=ctx.G.pred_ok(ctx.cp,"field_controls_locked"),
            script=ctx.G.pred_ok(ctx.cp,"script_context_status")})
    end
    route_trace("grass_to_pc")
    local ok,why=Routes.with_incidental_escape(ctx,"borrowed school",function()
        ctx.walk_to_pc("borrowed school")
    end)
    if not ok then route_trace("grass_to_pc_failed");return false,"borrow transit: "..tostring(why) end
    -- RR's Center exit can start a message scene. Restore the ordinary step first:
    -- Routes.wait_walk's idle gate would raise before traced_follow can press A.
    ok,why=pcall(function()
        route_trace("pc_to_center_exit")
        ctx.play.follow(ctx.cp,"pc_to_pokecenter_entrance","borrowed school")
        route_trace("center_exit_warp")
        ctx.SP.warp_to(ctx.cp,"Down",30,ctx.SP.DEST.center_exit,"borrowed Center exit")
        route_trace("city_path")
        ctx.SP.PATHS.borrow_city={from={26,27},to={25,19},dirs=facts.paths.city,battles=false}
        ctx.SP.traced_follow(ctx.cp,"borrow_city","borrowed school door")
        route_trace("school_door_warp")
        ctx.SP.warp_to(ctx.cp,"Up",30,{group=5,num=2,x=facts.arrival[1],y=facts.arrival[2]},"School door")
        route_trace("school_counter_path")
        ctx.follow_path("borrow_school",facts.paths.school,facts.arrival,facts.approach,"School NPC approach")
    end)
    if not ok then route_trace("route_failed");return false,"borrow transit: "..tostring(why) end
    local own=ctx.party() or {};local pre={}
    if #own<2 or own[2].key~=key or own[2].hp<=0 then return false,"own healthy targetslot1 absent" end
    for _,m in ipairs(own) do pre[#pre+1]=hex(raw(m.slot)) end
    ctx.jlog("BORROW_BASELINE",{key=key,raw_party_hex=pre,rom_sha1=facts.rom_sha1})
    if not ctx.face("Up") then return false,"School counter facing" end
    ctx.G.tap("A",3,20)
    if not ctx.mash_until(function() return ctx.task_live("Task_MultichoiceMenu_HandleInput") end,120,"A") then
        return false,"School native multichoice absent"
    end
    ctx.frames(60)
    for _=1,facts.menu_option do ctx.G.tap("Down",3,20) end
    ctx.G.tap("A",3,20)
    if not ctx.mash_until(picker,120,"A") or not borrowed() then return false,"native loan picker/lifecycle absent" end
    if mode~="battle" then
        local loan={};for _,m in ipairs(ctx.party() or {}) do loan[#loan+1]=hex(raw(m.slot)) end
        local start=#ctx.write_lines();local ready_frame=ctx.emulator.framecount()
        ctx.jlog("BORROW_MENU_READY",{key=key,frame=ctx.emulator.framecount()})
        if not ctx.wait_received("force_faint",key,120) then return false,"command absent" end
        local ticks=ctx.sent("tick")
        for _=1,120 do
            ctx.frames(1)
            if not borrowed() or not picker() or party_writes(start)~=0 then return false,"loan changed before cancel" end
        end
        for i,m in ipairs(ctx.party() or {}) do if hex(raw(m.slot))~=loan[i] then return false,"loan record mutated" end end
        local tick=ctx.last_sent("tick")
        if not tick or tick.party_hidden~=true or not ctx.queued("force_faint",key) then return false,"hidden tick/held command missing" end
        ctx.jlog("BORROW_HELD",{key=key,frames=120,party_write_count=party_writes(start),hidden_ticks=ctx.sent("tick")-ticks,
                               start_frame=ready_frame,end_frame=ctx.emulator.framecount()})
        if not ctx.wait_go("RESTORE") then return false,"restore permission absent" end
        ctx.G.tap("B",3,20)
        -- CHOOSE_MULTIPLE_MONS asks its own cancel confirmation before returning
        -- to the script. Native input defaults to YES (cursor0); confirm without writes.
        if not ctx.wait_until(function() return ctx.task_address_live(facts.party_cancel_task) end,
                              120,"party cancel confirmation") then return false,"party cancel confirmation absent" end
        ctx.frames(60);ctx.G.tap("A",3,20)
        -- F5's confirmed cancellation returns to School's main menu, not the field. Quit that
        -- menu with B, then confirm YES to restore and end the conversation.
        if not ctx.wait_until(function() return ctx.task_live("Task_MultichoiceMenu_HandleInput") end,
                              120,"School main menu after picker cancel") then return false,"School main menu absent after cancel" end
        ctx.frames(60);ctx.G.tap("B",3,20)
        if not ctx.wait_until(function() return ctx.task_live("Task_YesNoMenu_HandleInput") end,
                              120,"School quit confirmation") then return false,"School quit confirmation absent" end
        ctx.frames(60);ctx.G.tap("A",3,20)
    else
        -- Primary party_menu.c CursorCB_Enter: selected order stores slot+1;
        -- the third entry moves to SLOT_CONFIRM=PARTY_SIZE (6), then A closes.
        for slot=0,2 do
            for _=1,12 do
                if cursor()==slot then break end
                local at=cursor();ctx.G.tap(at==0 and "Right" or (at<slot and "Down" or "Up"),3,20)
            end
            if cursor()~=slot then return false,"loan selection cursor stalled" end
            ctx.G.tap("A",3,20)
            if not ctx.wait_until(function() return ctx.task_live("Task_HandleSelectionMenuInput") end,10,"ENTER popup") then return false,"ENTER popup absent" end
            ctx.G.tap("A",3,20)
            if not ctx.wait_until(function() return u8(facts.selected_order_address+slot)==slot+1 end,10,"selected loan") then return false,"native selected order absent" end
        end
        if cursor()~=facts.confirm_slot then return false,"native confirm cursor absent" end
        ctx.G.tap("A",3,20)
        if not ctx.mash_until(ctx.in_battle,180,"A") then return false,"ordinary School battle absent" end
        for _=1,200 do
            if not ctx.in_battle() then break end
            if ctx.action_menu_up() then
                local move=ctx.status_move_slot()
                if move==nil then
                    local active=ctx.battler_slot()
                    for _,m in ipairs(ctx.party() or {}) do
                        if m.slot==active then for i=1,4 do if m.moves[i]~=0 and m.pp[i]>0 then move=i-1;break end end end
                    end
                end
                if move==nil then return false,"all loan moves exhausted" end
                local used,msg=ctx.use_move(move);if not used then return false,"normal loan move: "..tostring(msg) end
                ctx.frames(60)
            elseif ctx.party_menu_up() then
                local target
                for _,m in ipairs(ctx.party() or {}) do if m.hp>0 and m.slot~=ctx.battler_slot() then target=m.slot;break end end
                if target then local sent,msg=ctx.send_out(target);if not sent then return false,"loan send out: "..tostring(msg) end
                else ctx.G.tap("A",3,20) end
            else ctx.G.tap("A",3,20) end
        end
        if ctx.in_battle() then return false,"School battle turn budget exhausted" end
        local outcome=ctx.battle_outcome()
        if outcome~=1 and outcome~=2 then return false,"School battle did not win/lose" end
        ctx.jlog("BORROW_BATTLE",{outcome=outcome})
    end
    if not ctx.mash_until(function() return field() and not borrowed() and ctx.find(key) end,180,"A") then
        return false,"own party restore/site missing"
    end
    if mode~="battle" and not ctx.wait_until(function() local m=ctx.find(key);return m and m.hp==0 end,120,"own queuedHP0") then
        return false,"held command did not land on restored own target"
    end
    ctx.jlog("BORROW_RESTORED",{key=key,borrowed=borrowed(),hp=ctx.find(key).hp})
    if not ctx.wait_go("SAVE") then return false,"save permission absent" end
    return ctx.save("borrowed")
end
