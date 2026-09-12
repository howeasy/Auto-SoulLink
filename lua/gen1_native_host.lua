-- The native runtime's host inside the composed free-service client: one hold_mux owner vote
-- ("native") over the entry's single exclusive actuator, with a SHORT-LIVED bounded stepper
-- layered on it only while a native command is being serviced. Ordinary gameplay stays free
-- between commands; a bounded step releases only the native vote, so any other owner still
-- holding keeps the frame from advancing and the stepper fails closed.
--
-- gen1_native_runtime (embedded) reads host.status()/step_one/yield_held/set_held on this
-- object for its whole life; arm() and disarm() swap the stepper underneath it.
local M={SCHEMA="slink-native-host-v1"}
-- Pinned Gambatte video clock (platform_bounded_execution asserts the same numbers).
local FRAME_RATE={numerator=262144,denominator=4389}
function M.new(options)
    assert(type(options)=="table" and type(options.adapter)=="table" and type(options.adapter.set_held)=="function"
        and type(options.adapter.status)=="function","hold_mux owner adapter required")
    assert(type(options.owner_id)=="string" and type(options.authorize)=="function","owner identity and per-step authority required")
    assert(type(options.expected_host)=="table","exact expected host evidence required")
    local Bounded=options.bounded or require("platform_bounded_execution")
    local adapter=options.adapter
    local self={}
    local stepper=nil
    function self.armed()return stepper~=nil end
    -- Take the native vote and layer a fresh bounded owner on the (now held) actuator.
    function self.arm(reason)
        assert(stepper==nil,"native host is already armed")
        assert(adapter.set_held(true,reason or "native command service"))
        local ok,result=pcall(Bounded.new,{profile="gambatte",owner_id=options.owner_id,expected_host=options.expected_host,
            host=adapter,authorize=options.authorize})
        if not ok then adapter.set_held(false,"native arm failed");error(result,0)end
        stepper=result
        return true
    end
    -- Close the stepper and release only the native vote. Never called mid-step.
    function self.disarm(reason)
        if stepper then stepper.close(reason or "native command service complete");stepper=nil end
        return adapter.set_held(false,reason or "native command service complete")
    end
    function self.step_one(scope)
        if not stepper then return false,"native host is not armed for bounded stepping"end
        return stepper.step_one(scope)
    end
    function self.set_held(value,reason)
        if stepper then return stepper.set_held(value,reason)end
        return adapter.set_held(value,reason)
    end
    function self.yield_held()
        if stepper then return stepper.yield_held()end
        assert(type(adapter.yield_held)=="function","held yield unavailable")
        return adapter.yield_held()
    end
    function self.status()
        if stepper then return stepper.status()end
        -- Unarmed: the actuator's readback under the same status shape, truthfully NOT bounded
        -- (window evidence built from it reports bounded=false and the server refuses it).
        return {schema="slink-bounded-execution-status-v1",failed=nil,steps=0,host=adapter.status(),
            expected_frame=emu.framecount(),load_state_invalidation=false,owner_exit_invalidation=false,
            frame_rate=FRAME_RATE,single_frame_only=false,frame_callbacks_suppressed=false,
            ordinary_execution=false,native_recovery_execution=false,armed=false}
    end
    return self
end
return M
