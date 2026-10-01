-- Ordinary-input RR Nature Changer. Observe production registered points; never stage a PID.
return function(ctx)
    if not ctx.wait_go() then return false, "no GO" end
    local key, facts = ctx.linked(), ctx.go_value("NATURE")
    if not facts or not key or not ctx.find(key) or ctx.find(key).slot ~= 1 then
        return false, "nature requires linked physical slot1 and own-ROM facts"
    end
    if ctx.player == "b" then
        if not ctx.wait_go("SAVE") then return false, "no partner save permission" end
        return ctx.save("nature")
    end
    local function u8(a) return memory.read_u8(a,"System Bus") end
    local function raw()
        local base=assert(ctx.party_base())+100
        local bytes={}
        for i=0,99 do bytes[#bytes+1]=u8(base+i) end
        return string.char(table.unpack(bytes))
    end
    local function hex(s) return (s:gsub(".",function(c) return string.format("%02X",c:byte()) end)) end
    local function multi() return ctx.task_live("Task_MultichoiceMenu_HandleInput") end
    local function list() return ctx.task_address_live(assert(facts.list_input_task)) end
    local function service() return multi() or list() end
    local function yesno() return ctx.task_live("Task_YesNoMenu_HandleInput") end
    local function picker() return ctx.party_menu_up() and ctx.task_live("Task_HandleChooseMonInput") end
    local function field() return ctx.play.on_field(ctx.cp)
        and ctx.G.pred_ok(ctx.cp,"script_context_status")
        and ctx.G.pred_ok(ctx.cp,"field_controls_locked") end
    local mutations=0
    local signals, drain=ctx.session.signals,ctx.session.signals.drain
    signals.drain=function(self)
        local out=drain(self)
        for _,sig in ipairs(out) do
            if sig.kind=="nature_change_begin" or sig.kind=="nature_change" then
                if sig.kind=="nature_change" then mutations=mutations+1 end
                ctx.jlog("NATURE_SIGNAL",{kind=sig.kind,point=sig.point})
            end
        end
        return out
    end
    local walked,why=ctx.flee_incidentals("nature",function()
        ctx.walk_to_pc("nature")
        ctx.follow_path("nature_pc_to_counter",facts.path,{11,2},{8,4},"nature counter")
    end)
    if not walked then return false,"nature transit: "..tostring(why) end
    ctx.SP.verify_destination(ctx.cp,"nature counter",{group=facts.map[1],num=facts.map[2],x=8,y=4})
    ctx.jlog("NATURE_BASELINE",{key=key})
    local function open_picker()
        if not ctx.face("Up") then return false,"nature facing" end
        ctx.G.tap("A",3,20)
        if not ctx.mash_until(service,120,"A") then return false,"service list absent" end
        ctx.frames(60); ctx.G.tap("A",3,20) -- service option0: Nature
        if not ctx.mash_until(yesno,120,"A") then return false,"native YES absent" end
        ctx.frames(60); ctx.G.tap("A",3,20) -- YES default
        if not ctx.wait_until(picker,120,"native nature party picker") then return false,"picker absent" end
        ctx.frames(60)
        return true
    end
    local before=raw()
    local ok,msg=open_picker(); if not ok then return false,msg end
    ctx.G.tap("B",3,20)
    if not ctx.mash_until(field,120,"A") then return false,"cancel did not return to field" end
    ctx.frames(60)
    if raw()~=before or ctx.sent("key_change")~=0 then return false,"cancel mutated identity" end
    ctx.jlog("NATURE_CANCEL",{key=key,unchanged=true})
    ok,msg=open_picker(); if not ok then return false,msg end
    local cursor=function() return ctx.peek("gPartyMenu",1,9) end
    for _=1,12 do
        if cursor()==1 then break end
        ctx.G.tap(cursor()==0 and "Right" or "Up",3,20)
    end
    if cursor()~=1 then return false,"native picker wrong slot" end
    local pre=raw()
    local pid,ot=string.unpack("<I4I4",pre)
    if string.format("%08X:%08X",pid,ot)~=key then return false,"pre-action raw identity differs" end
    local Admission=dofile(ctx.D.wt.."/lua/admission.lua")
    ctx.jlog("NATURE_PREIMAGE",{slot=1,key=key,raw_hex=hex(pre),
        raw_sha1=Admission.sha1(function(i) return pre:byte(i+1) end,#pre),
        rom_sha1=gameinfo.getromhash():lower()})
    ctx.G.tap("A",3,20)
    if not ctx.mash_until(list,120,"A") then return false,"native ListMenu nature list absent" end
    ctx.frames(60);ctx.G.tap("A",3,20) -- first native nature option, ROM-derived target
    joypad.set({})
    if not ctx.wait_until(function() return mutations>=1 end,180,"first registered nature mutation") then
        return false,"registered nature mutation absent"
    end
    -- The native mutation is autonomous after selecting the list row. A is now
    -- permitted only to dismiss its still-active script; never on an idle field.
    local pulse=0
    if not ctx.wait_until(function()
        joypad.set({})
        if field() then return true end
        if mutations~=1 then error("extra native nature mutation") end
        pulse=pulse+1
        if pulse%16==0 and (not ctx.G.pred_ok(ctx.cp,"script_context_status")
                           or not ctx.G.pred_ok(ctx.cp,"field_controls_locked")) then
            joypad.set({A=true})
        end
    end,120,"nature script dismissal without reopening") then return false,"nature script did not finish" end
    joypad.set({})
    if not ctx.wait_until(function() return ctx.sent("key_change")>=1 end,120,"nature migration publication") then
        return false,"registered nature migration absent"
    end
    local change=ctx.last_sent("key_change")
    if not change or change.reason~="nature_change" or change.old_key~=key then return false,"wrong migration" end
    local ack=ctx.wait_until(function()
        return ctx.rx_after(0,function(m) return m.cmd=="key_change_ack" and m.old_key==key
                                               and m.new_key==change.new_key and m.migrated==true end)
    end,120,"nature migration ACK")
    if not ack then return false,"no nature ACK" end
    ctx.jlog("NATURE_ACK",ack)
    if mutations~=1 then return false,"extra native nature mutation" end
    joypad.set({})
    ctx.log("NATURE_CHANGED "..change.new_key)
    if not ctx.wait_go("SAVE") then return false,"no save permission" end
    return ctx.save("nature")
end
