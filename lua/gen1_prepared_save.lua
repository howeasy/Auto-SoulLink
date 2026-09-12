-- RBY binding of the shared ordered command adapter: native prompt return,
-- full save/file proof, then the final read-only paired preparation checkpoint.
local Canonical=require("journal_document")
local Capture=require("gen1_trade_preparation")
local M={}
function M.new(options)
    local prompt,closure=options.prompt,options.prompt.closure_adapter()
    local function same(a,b)return assert(Canonical.encode(a))==assert(Canonical.encode(b))end
    local function noop(identity)
        return {schema="rby-no-prompt-close-v1",command_id=identity.command_id,
            command_sequence=identity.command_sequence,context_generation=options.context_generation()}
    end
    local first={}
    function first.prepare(body,identity)
        if prompt.needs_closure(body)then return closure.prepare(body,identity)end
        return noop(identity)
    end
    function first.classify(body,intent,identity)
        if intent.schema=="rby-prompt-close-intent-v1"then return closure.classify(body,intent,identity)end
        assert(not prompt.needs_closure(body) and same(intent,noop(identity)),"unexpected native prompt obligation")
        return "after",noop(identity)
    end
    function first.apply(body,intent,identity)
        assert(intent.schema=="rby-prompt-close-intent-v1","absent prompt has no physical effect")
        return closure.apply(body,intent,identity)
    end
    function first.receipt(body,intent,observed,identity)
        if intent.schema=="rby-prompt-close-intent-v1"then return closure.receipt(body,intent,observed,identity)end
        local phase,current=first.classify(body,intent,identity)
        assert(phase=="after" and same(current,observed));return current
    end
    return require("staged_command").new({store=options.store,context=options.context_generation,
        stages={{name="prompt",adapter=first},{name="save",adapter=options.save},{name="ready",adapter=options.preparation}},
        verify_completed=function(results)
            return options.save.verify(results.save)
                and same(Capture.capture(options.memory,options.manifest),results.ready.checkpoint)
                and results.ready.context_generation==options.context_generation()
                and (results.prompt.schema=="rby-no-prompt-close-v1" or prompt.execution_phase=="closed")
        end,
        receipt=function(results)return {schema="rby-saved-ready-v1",stages=results}end})
end
return M
