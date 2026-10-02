-- NDS phase -> registry composite: the session's single `signals` object.
--
-- lua/hook_registry.lua is constructor-only (one registry per armed phase, no dynamic site
-- API), so this module owns the phase lifecycle on top of it. It holds no title facts: the
-- Gen 4 layer supplies per-phase armed sites (from the pack), phase predicates (callables)
-- and the capture callback (which adapts binding:context to the registry's capture).
--
-- FRAME ORDER CONTRACT (session:frame_end, lua/core/session.lua):
--   emu.frameadvance  hook callbacks queue events inside the owning registry
--   frame_end:  game.pre_pump -> signals:poll()    evaluate predicates; disarm, THEN arm
--               ...net.pump...
--               signals:drain()                    events -> game.on_signal; then reads
--                                                  signals.handler_error / signals.failure
--               game.frame_hooks                   (do NOT call poll here)
--   session:stop -> signals:close()
-- poll() belongs in `pre_pump`: a disarm drains the dying registry into a held buffer
-- BEFORE closing it, and the same frame_end's drain() then returns it, exactly once. A poll
-- run after drain() is still lossless (held until the next drain) but one frame later.
-- Predicates therefore see state after frame N and a newly armed hook is live for frame
-- N+1; first-entry coverage is the C1-2/C1-1 predicate's job, not this module's.
-- Callbacks only run during emulation, never inside poll/drain/close, so no hit can land
-- between a registry's drain and its close.
--
-- Budget overrun is NOT a fault (F3): arm() refuses it ("busy: ...", counted in status().refused /
-- last_refusal) and nothing latches, so a poll()-driven overrun can never lock out the D7 on-demand hook.
--
-- Faults (any of: failed construction, failed close, a registry's capture/queue failure, a
-- throwing predicate) are LATCHED: `failure` holds the first fault, status().faults
-- every one by phase, and no phase is armed again until recover() proves the cleanup faults
-- clear (capture/queue faults need a new session). Unremoved handles are kept
-- counted (status().owned/retained) and their registry is retained until closed.
local PS = {}
local function integer(v,low,high) return type(v)=="number" and v==math.floor(v) and v>=low and v<=high end
local function callable(v) return type(v)=="function" or type(v)=="userdata" end

function PS.new(cfg)
    assert(type(cfg)=="table","phase signals config required")
    local Registry,binding=cfg.Registry,cfg.binding
    assert(type(Registry)=="table" and callable(Registry.new),"shared hook registry required")
    assert(type(binding)=="table" and callable(binding.validate) and callable(binding.register)
        and callable(binding.unregister) and callable(binding.valid_handle),"NDS binding required")
    assert(type(cfg.owner)=="string" and cfg.owner:match("^[%w_.%-]+$"),"explicit owner namespace required")
    assert(integer(cfg.max_pending,1,1e9),"explicit positive queue bound required")
    assert(callable(cfg.capture),"capture callback required")
    assert(cfg.on_event==nil or callable(cfg.on_event),"on_event must be callable")
    -- Owner ruling 2026-10-01: 60 fps at 1x holds with at most 1 hook (3 hooks = 66 fps, 4 = 58),
    -- so production default is ONE concurrent hook. A higher cap (<=3) is an explicit cfg
    -- decision; the one extra handle is a probe observer only.
    local cap=cfg.cap==nil and 1 or cfg.cap
    local allowance=cfg.observer_allowance or 0
    assert(integer(cap,0,3) and integer(allowance,0,1),"hook cap 0..3 plus observer allowance 0..1")
    local budget=cap+allowance
    assert(type(cfg.phases)=="table","phase table required")
    local names={}
    for name,phase in pairs(cfg.phases) do
        assert(type(name)=="string" and name:match("^[%w_.%-]+$") and type(phase)=="table","phase entry")
        assert(type(phase.sites)=="table" and (phase.active==nil or callable(phase.active)),"phase sites/active")
        names[#names+1]=name
    end
    table.sort(names)

    local self={failure=nil,handler_error=nil}
    local live={}        -- phase -> registry, armed and healthy
    local oneshot={}     -- phase -> true: armed on demand, removed after its first drained event
    local retained={}    -- phase -> registry whose close failed or whose construction left handles
    local owned={}       -- handle -> phase: ACTUAL external handles (cumulative status() is not)
    local held={}        -- events drained from a registry that is going away
    local faults={}      -- phase -> {kind=,message=}; first one is `failure`
    local fault_order={}
    local registered_closed=0
    local refused,last_refusal=0,nil        -- budget refusals: counted, never latched (F3)
    local reported_handler={}

    local function count_owned() local n=0; for _ in pairs(owned) do n=n+1 end; return n end
    local function owned_by(phase) local n=0; for _,p in pairs(owned) do if p==phase then n=n+1 end end; return n end
    local function latch(phase,kind,message)
        message=phase..": "..tostring(message)
        if not faults[phase] then fault_order[#fault_order+1]=phase; faults[phase]={kind=kind,message=message} end
        if not self.failure then self.failure=message end
    end
    local function take(reg)
        for _,event in ipairs(reg:drain()) do held[#held+1]=event end
    end
    local function watch(phase,reg)
        local status=reg:status()
        if status.failed then latch(phase,"registry",status.failed) end
        if status.handler_error and reported_handler[reg]~=status.handler_error then
            reported_handler[reg]=status.handler_error
            self.handler_error=status.handler_error
        end
    end
    local function wrap_register(phase)
        return function(site,callback,name)
            local handle=binding:register(site,callback,name)
            if binding:valid_handle(handle)==true then owned[handle]=phase end
            return handle
        end
    end
    local function unregister(handle)
        local result=binding:unregister(handle)         -- a throw leaves the handle owned
        if result~=false then owned[handle]=nil end
        return result
    end
    -- Drain first so the last queued event survives, then close; always exactly once.
    local function remove(phase,reg)
        take(reg)
        watch(phase,reg)
        local ok,closed=pcall(reg.close,reg)
        if ok and closed==true and owned_by(phase)==0 then
            registered_closed=registered_closed+reg:status().registered
            reported_handler[reg]=nil
            return true
        end
        retained[phase]=reg
        latch(phase,"close",ok and "registry close failed: "..table.concat(reg:status().cleanup_errors,"; ") or closed)
        return false
    end

    function self:arm(phase)
        local def=assert(cfg.phases[phase],"unknown phase: "..tostring(phase))
        if live[phase] then return true end
        if self.failure then return nil,self.failure end
        local sites=def.sites
        if #sites==0 then return true end                    -- zero-site phase: no registry
        if count_owned()+#sites>budget then
            refused=refused+1
            last_refusal=phase..": busy: hook budget "..budget.." exceeded: "..count_owned().." owned + "..#sites
            return nil,last_refusal
        end
        local ok,reg,err,failed=pcall(Registry.new,{owner=cfg.owner.."."..phase,sites=sites,max_pending=cfg.max_pending,
            validate=function(site) return binding:validate(site) end,register=wrap_register(phase),unregister=unregister,
            valid_handle=function(handle) return binding:valid_handle(handle) end,capture=cfg.capture,on_event=cfg.on_event})
        if not ok then reg,err,failed=nil,reg,nil end         -- Registry.new threw: no registry object
        if not reg then
            -- Constructor already unwound; a failed unwind leaves handles in `owned` + its registry.
            if failed then take(failed); registered_closed=registered_closed+failed:status().registered end
            if owned_by(phase)>0 then retained[phase]=failed end
            latch(phase,"construct",err)
            return nil,faults[phase].message
        end
        live[phase]=reg
        return true
    end
    function self:disarm(phase)
        local reg=live[phase]
        if not reg then return true end
        live[phase],oneshot[phase]=nil,nil
        return remove(phase,reg)
    end
    -- On-demand one-shot (the production use: the D7 write seam). Arms `phase`'s sites, the first
    -- drain that returns an event removes them again. A request while the budget is taken or the
    -- phase is armed is REFUSED (nil,"busy: ..."), never queued: the seam is time-critical, a
    -- queued request would fire against state the caller no longer validated, so the caller
    -- re-decides on its own next poll. Busy is a normal refusal, not a latched fault.
    function self:request(phase)
        local def=assert(cfg.phases[phase],"unknown phase: "..tostring(phase))
        if self.failure then return nil,self.failure end
        if live[phase] then return nil,"busy: "..phase.." already armed" end
        if count_owned()+#def.sites>budget then return nil,"busy: hook budget "..budget.." in use" end
        local ok,why=self:arm(phase)
        if not ok then return nil,why end
        if live[phase] then oneshot[phase]=true end
        return true
    end
    -- Drive arm/disarm from the phase predicates (see ORDER above). Disarms run first so a
    -- hand-over between phases frees its handles before the next phase counts against the cap.
    function self:poll()
        local want={}
        for _,name in ipairs(names) do
            local active=cfg.phases[name].active
            if active then
                local ok,result=pcall(active)
                -- a throwing predicate fails CLOSED (F4): latch it and disarm the phase, never leave its hook costing fps
                if ok then want[name]=not not result else latch(name,"predicate",result); want[name]=false end
            end
        end
        for _,name in ipairs(names) do if want[name]==false then self:disarm(name) end end
        for _,name in ipairs(names) do if want[name] then self:arm(name) end end
    end
    function self:drain()
        local out=held
        held={}
        for _,name in ipairs(names) do
            local reg=live[name] or retained[name]
            if reg then
                local before=#held
                take(reg); watch(name,reg)
                local dead=live[name] and reg:status().failed
                if live[name] and (dead or (oneshot[name] and #held>before)) then self:disarm(name) end
            end
        end
        for _,event in ipairs(held) do out[#out+1]=event end
        held={}
        return out
    end
    -- Close everything. False (never a throw) when any handle stayed behind: counted, latched.
    function self:close()
        for _,name in ipairs(names) do
            local reg=live[name]
            if reg then live[name]=nil; remove(name,reg) end
        end
        for _,name in ipairs(names) do                       -- retained registries retry once
            local reg=retained[name]
            if reg then
                take(reg)
                local ok,closed=pcall(reg.close,reg)
                if ok and closed==true and owned_by(name)==0 then retained[name]=nil end
            end
        end
        return count_owned()==0
    end
    -- Explicit recovery: retry closing retained registries; only cleanup faults can clear.
    function self:recover()
        if not self:close() then return false end
        for _,name in ipairs(fault_order) do
            local kind=faults[name].kind
            if kind~="close" and kind~="construct" then return false end
        end
        faults,fault_order,self.failure={},{},nil
        return true
    end
    function self:status()
        local armed,retained_out,pending,registered={}, {},0,registered_closed
        local fault_out={}
        for name,reg in pairs(live) do
            armed[name]=oneshot[name] and "on_demand" or true
            local s=reg:status(); pending=pending+s.pending; registered=registered+s.registered
        end
        for name,reg in pairs(retained) do
            local s=reg and reg:status() or {pending=0,registered=0}
            pending=pending+s.pending; registered=registered+s.registered
            retained_out[name]={handles=owned_by(name),owner=cfg.owner.."."..name}
        end
        for name,fault in pairs(faults) do fault_out[name]=fault.message end
        return {armed=armed,owned=count_owned(),budget=budget,retained=retained_out,faults=fault_out,failure=self.failure,
                handler_error=self.handler_error,pending=pending,held=#held,registered=registered,
                refused=refused,last_refusal=last_refusal}
    end
    return self
end

return PS
