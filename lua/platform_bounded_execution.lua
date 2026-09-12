-- Source-pinned one-frame owner layered on the unchanged exclusive hold actuator.
-- Generation policy must authorize each step. No ordinary or recovery ticket is inferred.
local Execution=require("platform_execution")
local M={SCHEMA="slink-bounded-frame-v1"}
function M.new(options)
    assert(type(options)=="table" and options.profile=="gambatte","bounded stepping is qualified for Gambatte only")
    assert(type(options.authorize)=="function","private per-step execution validator required")
    luanet.load_assembly("System");luanet.load_assembly("System.Windows.Forms")
    local App=luanet.import_type("System.Windows.Forms.Application")
    local Object=luanet.import_type("System.Object")
    local Array=luanet.import_type("System.Array")
    local Enum=luanet.import_type("System.Enum")
    local Flags=luanet.import_type("System.Reflection.BindingFlags")
    local flags=Enum.Parse(luanet.ctype(Flags),"Instance, Public, NonPublic")
    local main,console_form
    local forms=App.OpenForms:GetEnumerator()
    while forms:MoveNext()do
        local form=forms.Current
        local kind=tostring(form:GetType().FullName)
        if kind=="BizHawk.Client.EmuHawk.MainForm"then assert(not main);main=form
        elseif kind=="BizHawk.Client.EmuHawk.LuaConsole"then assert(not console_form);console_form=form end
    end
    assert(main and console_form,"owned MainForm/LuaConsole required")
    local function field_reader(object,name)
        local find=luanet.get_method_bysig(object:GetType(),"GetField","System.String","System.Reflection.BindingFlags")
        local field=assert(find(name,flags),"pinned host field is absent: "..name)
        local get=luanet.get_method_bysig(field,"GetValue","System.Object")
        return function()return get(object)end
    end
    local read_libraries=field_reader(console_form,"LuaImp")
    local libraries=assert(read_libraries())
    local read_advance=field_reader(main,"_runloopFrameAdvance")
    local read_capture=field_reader(main,"_currAviWriter")
    local read_inputs=field_reader(main,"InputManager")
    local inputs=assert(read_inputs())
    local core=main.Emulator
    local frame_numerator,frame_denominator=tonumber(core.VsyncNumerator),tonumber(core.VsyncDenominator)
    assert(frame_numerator==262144 and frame_denominator==4389,"pinned Gambatte video clock differs")
    local find=luanet.get_method_bysig(main:GetType(),"GetMethod","System.String","System.Reflection.BindingFlags")
    local method=assert(find("StepRunLoop_Core",flags))
    local invoke=luanet.get_method_bysig(method,"Invoke","System.Object","System.Object[]")
    local arguments=Array.CreateInstance(luanet.ctype(Object),1);arguments:SetValue(true,0)
    local function scripts_valid()
        local enabled=0
        local scripts=libraries.ScriptList:GetEnumerator()
        while scripts:MoveNext()do
            local script=scripts.Current
            if script.Enabled then enabled=enabled+1
            elseif script.Functions.Count~=0 then return false end
        end
        return enabled==1
    end
    local reset_controls={}
    for _,name in ipairs({"ActiveController","AutoFireController","StickyController","ClickyVirtualPadController","ControllerOutput"})do
        local controller=assert(inputs[name])
        reset_controls[#reset_controls+1]={name=name,controller=controller,
            pressed=luanet.get_method_bysig(controller,"IsPressed","System.String")}
    end
    local function valid()
        local reset=false
        for _,control in ipairs(reset_controls)do
            if not Object.ReferenceEquals(control.controller,inputs[control.name])then return false,"controller changed"end
            if control.pressed("Power")or control.pressed("Reset")then reset=true end
        end
        local checks={core=Object.ReferenceEquals(core,main.Emulator),libraries=Object.ReferenceEquals(libraries,read_libraries()),
            inputs=Object.ReferenceEquals(inputs,read_inputs()),updates=not libraries.IsUpdateSupressed,
            scripts=scripts_valid(),future=main.PreFutureFrameCallback==nil,movie=main.MovieSession.Movie==nil,
            capture=read_capture()==nil,cheats=not main.CheatList.AnyActive,
            advance=not main.PressFrameAdvance,hold_advance=not main.HoldFrameAdvance,inch=not main.FrameInch,
            runloop=read_advance()==false,input=not inputs.ClientControls["Frame Advance"],reset=not reset,seeking=not main.IsSeeking}
        for name,ok in pairs(checks)do if not ok then return false,name end end
        return true
    end
    local valid_initial,conflict=valid()
    assert(valid_initial,"bounded host conflict: "..tostring(conflict))
    local host=assert(Execution.new({profile=options.profile,owner_id=options.owner_id,
        exclusive_ownership="emulator_process",control_context="between_frames",expected_host=options.expected_host}))
    assert(host.set_held(true,"bounded execution owner waiting for authority"))
    local self={}
    local failed,busy,steps=nil,false,0
    local expected_frame=emu.framecount()
    local function stop(reason)
        failed=failed or tostring(reason)
        local ok,why=host.set_held(true,"bounded execution failed")
        return false,failed,ok,why
    end
    assert(event.onloadstate and event.onexit,"host lifecycle callbacks required")
    local load_hook=assert(event.onloadstate(function()stop("savestate load invalidated bounded execution context")end,
        "slink-bounded-load-"..options.owner_id))
    local exit_hook=assert(event.onexit(function()stop("Lua owner stopped")end,"slink-bounded-exit-"..options.owner_id))
    function self.step_one(authority)
        if failed then return false,failed end
        if busy then return false,"bounded frame is already running"end
        busy=true
        local ok,result=pcall(function()
            assert(valid() and host.status().physical_stop_verified and emu.framecount()==expected_frame,
                "bounded frame requires its unchanged held context")
            local before=emu.framecount()
            local paused=main.EmulatorPaused
            assert(options.authorize(authority,{frame=before,owner_id=options.owner_id,steps=steps})==true,
                "per-step authority is absent or expired")
            assert(not failed and valid() and host.status().physical_stop_verified and emu.framecount()==before,"context changed during authorization")
            -- Nested main-loop stepping must not resume the currently running
            -- Lua coroutine. Memory bus hooks remain active; frame event callbacks
            -- are suppressed for this call and observations run in the owned loop.
            libraries.IsUpdateSupressed=true
            assert(libraries.IsUpdateSupressed,"Lua update suppression was not established")
            local released,release_error=host.set_held(false,"one authorized synchronous frame")
            local advanced,advance_error=false,release_error
            if released then advanced,advance_error=pcall(function()invoke(main,arguments)end)end
            local held,hold_error=host.set_held(true,"authorized frame completed")
            libraries.IsUpdateSupressed=false
            assert(held,hold_error)
            assert(advanced,advance_error)
            assert(not failed and valid() and main.EmulatorPaused==paused and emu.framecount()==before+1,
                "bounded frame changed context/pause or advanced an unexpected number of frames")
            assert(host.status().physical_stop_verified,"bounded frame did not restore the physical hold")
            steps=steps+1
            expected_frame=before+1
            return {schema=M.SCHEMA,before=before,after=before+1,owner_id=options.owner_id,step=steps,user_paused=paused}
        end)
        busy=false
        if not ok then
            -- Only restore suppression on the same still-owned library object.
            pcall(function()if Object.ReferenceEquals(libraries,read_libraries())then libraries.IsUpdateSupressed=false end end)
            return stop(result)
        end
        return true,result
    end
    function self.set_held(value,reason)
        if value~=true then return false,"bounded owner exposes no unbounded release"end
        return host.set_held(true,reason)
    end
    function self.yield_held()
        if failed then return false,failed end
        if not valid()or emu.framecount()~=expected_frame then return stop("bounded context changed before held yield")end
        local ok,why=host.yield_held()
        if not ok then return stop(why)end
        if failed or not valid()or emu.framecount()~=expected_frame then return stop("bounded context changed during held yield")end
        return true
    end
    function self.status()
        return {schema="slink-bounded-execution-status-v1",failed=failed,steps=steps,host=host.status(),
            expected_frame=expected_frame,load_state_invalidation=load_hook~=nil,owner_exit_invalidation=exit_hook~=nil,
            frame_rate={numerator=frame_numerator,denominator=frame_denominator},
            single_frame_only=true,frame_callbacks_suppressed=true,ordinary_execution=false,native_recovery_execution=false}
    end
    return self
end
return M
