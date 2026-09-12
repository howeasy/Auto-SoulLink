-- Retire a pre-COMMIT trade, closing an acknowledged prompt if this player has one.
-- An idle participant has a read-only receipt; an armed native trade is never undone.
local JSON=require("json_codec")
local Canonical=require("journal_document")
local Capture=require("gen1_trade_preparation")
local M={}
function M.new(options)
    local prompt,closure=options.prompt,options.prompt.closure_adapter()
    local function sha(value)return options.sha256(assert(Canonical.encode(value)))end
    local function read(body,identity,intent)
        assert(options.authorize("observe_abort",body,identity)==true,"owned abort context required")
        assert(body.cmd=="native_trade_abort" and body.player==options.player and body.payload.schema=="trade-abort-v1"
            and ({cancelled=true,declined=true,expired=true})[body.payload.terminal_phase],"pre-COMMIT abort required")
        local phase=options.native_store:read().phase
        assert(phase=="idle" or phase=="released","native trade cannot be discarded by abort")
        assert(not prompt.needs_closure(body),"native prompt needs verified closure")
        if intent then
            assert(intent.schema=="rby-trade-abort-intent-v1" and intent.command_id==identity.command_id
                and intent.command_sequence==identity.command_sequence and intent.body_digest==sha(body)
                and intent.context_generation==options.context_generation(),"abort intent/context changed")
        end
        local point=Capture.capture(options.memory,options.manifest)
        if intent then assert(sha(point)==sha(intent.checkpoint),"abort checkpoint changed")end
        return point
    end
    local self={}
    function self.prepare(body,identity)
        if prompt.needs_closure(body)then return closure.prepare(body,identity)end
        return {schema="rby-trade-abort-intent-v1",command_id=identity.command_id,
            command_sequence=identity.command_sequence,body_digest=sha(body),context_generation=options.context_generation(),
            checkpoint=read(body,identity)}
    end
    function self.classify(body,intent,identity)
        if intent.schema=="rby-prompt-close-intent-v1"then return closure.classify(body,intent,identity)end
        return "after",read(body,identity,intent)
    end
    function self.apply(body,intent,identity)
        assert(intent.schema=="rby-prompt-close-intent-v1","idle abort has no physical apply")
        return closure.apply(body,intent,identity)
    end
    function self.receipt(body,intent,observed,identity)
        if intent.schema=="rby-prompt-close-intent-v1"then return closure.receipt(body,intent,observed,identity)end
        assert(sha(read(body,identity,intent))==sha(observed),"abort receipt changed")
        return {schema="rby-trade-abort-v1",command_id=identity.command_id,command_sequence=identity.command_sequence,
            transaction_id=body.transaction_id,proposal_digest=body.proposal_digest,
            context_generation=options.context_generation(),final_sha1=options.manifest.final_sha1,checkpoint=observed}
    end
    return self
end
return M
