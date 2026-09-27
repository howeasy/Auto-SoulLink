-- FR/LG native carrier driver. Normal joypad input only; no protocol answers or RAM writes.
-- Routes: gen3_scripted_play, pinned pret maps. NPC/engine addresses: title-bound manifest.
local M = {}
local ADJ = {["0,-1"]="Up",["0,1"]="Down",["-1,0"]="Left",["1,0"]="Right"}
local FACING = {Down=1,Up=2,Left=3,Right=4}
local function u8(a) return memory.read_u8(a,"System Bus") end
local function u16(a) return memory.read_u16_le(a,"System Bus") end
local function u32(a) return memory.read_u32_le(a,"System Bus") end

function M.select(ctx, h)
    local c = assert(h.manifest.carrier,"missing native carrier bindings")
    local function object(slot) return c.objects+slot*c.stride end
    local function player() return u8(c.avatar+5) end
    local function pos(slot) return u16(object(slot)+0x10)-7,u16(object(slot)+0x12)-7 end
    local function field()
        return u32(c.callback)==c.field_callback and u8(c.field_lock)==0
            and u8(c.script_status)==c.script_idle
    end
    local function npc()
        for slot=0,15 do
            local p=object(slot)
            if (u8(p)&1)~=0 and u8(p+8)==c.local_id then return slot end
        end
    end
    local function owned(op) return u8(c.state+8)==1 and u16(c.state+6)==op end
    local function press_until(done, gate, button, seconds, label)
        local n=0
        local result=ctx.wait_until(function()
            if done() then joypad.set({});return true end
            n=n+1;joypad.set(gate() and n%16<2 and {[button]=true} or {})
        end,seconds,label)
        joypad.set({})
        assert(result,label)
    end
    if ctx.player=="a" then
        local before=ctx.sent("trade_request")
        ctx.play.follow(ctx.cp,"route1_edge_to_pokecenter_door","native trade")
        ctx.SP.warp_to(ctx.cp,"Up",30,ctx.SP.DEST.center,"native trade Center door")
        ctx.play.follow(ctx.cp,"pokecenter_entrance_to_nurse","native trade")
        assert(ctx.wait_until(function() return npc() and field() end,60,"native NPC spawn"),"native NPC absent")
        local deadline=emu.framecount()+3000
        while emu.framecount()<deadline do
            local x,y=ctx.G.pos(ctx.cp)
            if x==3 and y==4 then break end
            assert(y==4 and x>=3,"native NPC approach left the pinned row")
            ctx.G.tap("Left",12,20)
        end
        local x,y=ctx.G.pos(ctx.cp)
        assert(x==3 and y==4,"native NPC approach timed out")
        local count=u32(c.control+4)
        assert(ctx.wait_until(function()
            if u32(c.control+4)~=count then return true end
            local slot=npc()
            if not slot or player()>=16 or not field() then return false end
            local nx,ny=pos(slot);local px,py=ctx.G.pos(ctx.cp)
            local dir=ADJ[(nx-px)..","..(ny-py)]
            if dir then
                if (u8(object(player())+0x18)&15)~=FACING[dir] then ctx.G.tap(dir,3,20) end
                nx,ny=pos(slot);px,py=ctx.G.pos(ctx.cp)
                if ADJ[(nx-px)..","..(ny-py)]==dir and field()
                   and (u8(object(player()))&0x80)~=0
                   and (u8(object(player())+0x18)&15)==FACING[dir] then ctx.G.tap("A",1,20) end
            elseif px==3 and py==4 then ctx.G.tap("Up",12,20) end
            return u32(c.control+4)~=count
        end,180,"normal A facing native trade NPC"),"native NPC counter did not advance")
        assert(ctx.wait_until(function() return ctx.sent("trade_request")==before+1 end,60,"NPC trade_request"))
        local choices=ctx.sent("menu_result")
        assert(ctx.wait_received("show_choices",nil,120),"server choices absent")
        press_until(function() return ctx.sent("menu_result")>choices end,
                    function() return owned(22) end,"A",120,"native Trade choice")
        assert(ctx.last_sent("menu_result").choice==0,"native choice was not Trade")
        assert(ctx.wait_received("choose_mon",nil,120),"server chooser absent")
        assert(ctx.wait_until(function()
            return ctx.party_menu_up() and ctx.task_live("Task_HandleChooseMonInput") and owned(20)
        end,120,"native party chooser"),"native chooser never took input")
        ctx.frames(60)
        -- pret party_menu.c single layout: Right moves from slot 0 to the right column.
        for _=1,12 do
            local slot=u8(c.party_cursor)
            if slot==1 then break end
            ctx.G.tap(slot==0 and "Right" or "Up",3,20)
        end
        assert(u8(c.party_cursor)==1,"native cursor never selected linked slot 1")
        local chosen=ctx.sent("mon_chosen")
        press_until(function() return ctx.sent("mon_chosen")>chosen end,
                    function() return owned(20) and u32(c.callback)~=c.field_callback end,
                    "A",120,"native mon_chosen")
        assert(ctx.last_sent("mon_chosen").slot==1,"native chooser returned another slot")
    else
        local answers=ctx.sent("menu_result")
        assert(ctx.wait_received("show_menu",nil,900),"server offer absent")
        press_until(function() return ctx.sent("menu_result")>answers end,
                    function() return owned(17) end,ctx.D.native_decline and "B" or "A",120,"native offer answer")
        assert(ctx.last_sent("menu_result").choice==(ctx.D.native_decline and 0 or 1),"wrong native offer answer")
    end
    assert(h.carrier_complete(),"native carrier ownership/counter evidence missing")
    ctx.log("NATIVE_CARRIER_INPUTS_COMPLETE")
    return true
end
return M
