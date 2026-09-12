-- RBY preparation may first need to close an acknowledged native partner prompt.
-- The shared executor persists that closure intent before its only physical effect.
local M={}
function M.new(prompt,preparation)
    local closure=prompt.closure_adapter()
    local function closing(intent)return intent.schema=="rby-prompt-close-intent-v1"end
    local adapter={}
    function adapter.prepare(body,identity)
        if prompt.needs_closure(body)then return closure.prepare(body,identity)end
        return preparation.prepare(body,identity)
    end
    function adapter.classify(body,intent,identity)
        if closing(intent)then
            local phase,observed=closure.classify(body,intent,identity)
            if phase~="after"then return phase,observed end
            -- This remaining stage is read-only. A failure cannot repeat closure.
            local ready=preparation.prepare(body,identity)
            local result,checkpoint=preparation.classify(body,ready,identity)
            assert(result=="after","read-only preparation did not prove its checkpoint")
            return "after",{ready=ready,checkpoint=checkpoint}
        end
        return preparation.classify(body,intent,identity)
    end
    function adapter.apply(body,intent,identity)
        assert(closing(intent),"read-only preparation cannot apply")
        return closure.apply(body,intent,identity)
    end
    function adapter.receipt(body,intent,observed,identity)
        if closing(intent)then return preparation.receipt(body,observed.ready,observed.checkpoint,identity)end
        return preparation.receipt(body,intent,observed,identity)
    end
    return adapter
end
return M
