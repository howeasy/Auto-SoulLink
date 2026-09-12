-- Generation-independent one-instruction executor (PROTOTYPE, not wired into the client).
-- The bounded owner arms one server-issued authority immediately before ONE step_one and calls
-- finish() immediately after it returns. A binding supplies the pinned sites, the snapshot and
-- the decision; this module owns the lifecycle: the hold must be verified at arm and at finish,
-- exactly one frame must have run between them, steps are monotonic, a challenge is used once,
-- and inside the released frame a bus-exec hook on a pinned PC snapshots, decides, writes
-- exactly the decided footprint, reads back and disarms. Nothing here claims the hold while
-- writing: the hook records held=false and latches if the host reports a hold.
-- Window: an authority carrying frames={first,count} (count<=MAX_WINDOW_FRAMES) is armed once per
-- frame of the window with the SAME table: the first arm at frames.first, each next one at the frame
-- the previous finish() ended on (contiguous), steps step, step+1, ...; the first site reached
-- consumes it and any later arm is refused. No frames field = count 1 = exactly the old behaviour.
local JSON=require("json_codec")
local M={SCHEMA="slink-instruction-authority-v1",EVIDENCE="slink-instruction-evidence-v1",MAX_WINDOW_FRAMES=64}
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
function M.window(authority)
    local f=authority.frames
    if f==nil then return authority.frame,1 end
    assert(type(f)=="table" and f.first==authority.frame and type(f.count)=="number" and f.count%1==0
        and f.count>=1 and f.count<=M.MAX_WINDOW_FRAMES,"instruction authority window is malformed")
    return f.first,f.count
end
function M.hex(address,count)
    local parts={};for i=0,count-1 do parts[#parts+1]=string.format("%02x",memory.read_u8(address+i,"System Bus"))end
    return table.concat(parts)
end
function M.new(options)
    assert(type(options)=="table" and type(options.held)=="function" and type(options.owner_id)=="string","bounded owner context required")
    local binding=assert(options.binding,"instruction binding required")
    assert(type(binding.name)=="string" and type(binding.snapshot)=="function" and type(binding.decide)=="function","complete binding required")
    local armed,result,failure,hooks=nil,nil,nil,{}
    local last_step,used,window=0,{},nil
    local function fire(name)
        if failure or not armed then return end
        local authority=armed;local site=authority.sites[name]
        local frame=emu.framecount()
        -- the server conveys the measured host convention; any other hook frame is not this step's instruction: no write
        if frame~=authority.frame+authority.hook_frame_offset then return end
        if memory.read_u8(authority.addresses.hLoadedROMBank,"System Bus")~=site.bank then return end
        local ok,err=pcall(function()
            local pc=emu.getregister("PC")
            assert(pc==site.pc and M.hex(site.pc,#site.expected_hex/2)==site.expected_hex,"pinned instruction changed")
            assert(options.held()==false,"bus-exec hook fired while the host reports a hold")
            local sp=emu.getregister("SP")
            if site.return_sites then -- the caller is part of the pin: refuse BEFORE any byte is written
                local ret=memory.read_u8(sp,"System Bus")+256*memory.read_u8(sp+1,"System Bus")
                local known=false;for _,r in ipairs(site.return_sites)do if r==ret then known=true end end
                assert(known,string.format("instruction was not entered from its pinned caller (ret=%04x)",ret))
            end
            local evidence={schema=M.EVIDENCE,challenge=authority.challenge,owner_id=options.owner_id,frame=authority.frame,step=authority.step,
                held=false,site=name,pc=pc,bank=site.bank,sp=sp,stack_hex=M.hex(sp,4),hook_frame=frame,
                state=binding.snapshot(authority.addresses,authority.member),writes=JSON.array(),refusal=JSON.null}
            armed=nil -- one use: whichever site fires first consumes the authority
            local decision=binding.decide(evidence.state,authority.member,name,authority)
            if decision.refusal then evidence.refusal=decision.refusal;result=evidence;return end
            for _,w in ipairs(decision.writes)do
                local before=memory.read_u8(w.address,"System Bus")
                memory.write_u8(w.address,w.value,"System Bus")
                local after=memory.read_u8(w.address,"System Bus")
                assert(after==w.value,"authorized write did not land")
                evidence.writes[#evidence.writes+1]={address=w.address,before_hex=string.format("%02x",before),after_hex=string.format("%02x",after)}
            end
            result=evidence
        end)
        if not ok then failure=tostring(err);armed=nil end
    end
    local self={}
    function self.arm(authority)
        assert(not failure,failure)
        assert(not armed and not result,"an authority is already armed or unfinished")
        assert(type(authority)=="table" and authority.schema==M.SCHEMA and authority.uses==1 and authority.held==false
            and authority.owner_id==options.owner_id and authority.binding==binding.name,"exact instruction authority for this owner and binding required")
        assert(type(authority.challenge)=="string" and not used[authority.challenge],"instruction authority was already used")
        assert(type(authority.hook_frame_offset)=="number","authority must carry the measured hook frame convention")
        local first,count=M.window(authority)
        local now=emu.framecount()
        local w=window
        if w and w.challenge==authority.challenge then -- the next frame of an open window
            assert(now==w.next_frame,"instruction authority window is not contiguous")
        else
            assert(first==now,"authority names a frame other than the one about to run")
            w={challenge=authority.challenge,last=first+count-1,next_frame=first,consumed=false}
        end
        local step=type(authority.step)=="number" and authority.step+(now-first)
        assert(step and step>last_step,"instruction authority step is not after the last finished step")
        assert(options.held()==true,"arming requires the verified hold")
        if window and window~=w then used[window.challenge]=true end -- an abandoned window is spent, whatever it covered
        window=w
        armed=copy(authority);armed.frame=now;armed.step=step -- the copy names THIS frame and step of the window
        if #hooks==0 then
            for name,site in pairs(armed.sites)do
                hooks[#hooks+1]=assert(event.on_bus_exec(function()fire(name)end,site.pc,"slink-instruction-"..binding.name.."-"..name,"System Bus"))
            end
        end
        return true
    end
    function self.finish()
        assert(not failure,failure)
        local authority=result or armed
        assert(authority,"nothing armed")
        local ok,err=pcall(function()
            assert(options.held()==true,"finish requires the re-acquired hold")
            assert(emu.framecount()==authority.frame+1,"exactly one frame must have run since arm")
        end)
        if not ok then failure=tostring(err);armed=nil;result=nil;error(failure,0)end
        local evidence=result
        if evidence==nil then
            evidence={schema=M.EVIDENCE,challenge=armed.challenge,owner_id=options.owner_id,frame=armed.frame,step=armed.step,held=false,
                site=JSON.null,pc=JSON.null,bank=JSON.null,sp=JSON.null,stack_hex=JSON.null,hook_frame=JSON.null,state=JSON.null,
                writes=JSON.array(),refusal=JSON.null}
        end
        local w=window
        w.covered_from=w.covered_from or authority.frame;w.covered_to=authority.frame;w.next_frame=authority.frame+1;w.consumed=result~=nil
        if w.consumed or w.next_frame>w.last then used[authority.challenge]=true end -- one use: fired, or the window ran out
        last_step=authority.step
        armed=nil;result=nil
        return evidence
    end
    function self.status()return {armed=armed~=nil,pending=result~=nil,failed=failure,hooks=#hooks,last_step=last_step}end
    function self.window_status(challenge)
        if not window or window.challenge~=challenge then return nil end
        return {covered_from=window.covered_from,covered_to=window.covered_to,consumed=window.consumed}
    end
    function self.close()for _,id in ipairs(hooks)do event.unregisterbyid(id)end;hooks={};armed=nil;result=nil end
    return self
end
return M
