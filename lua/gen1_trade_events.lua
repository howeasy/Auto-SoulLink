-- RBY typed receipts and native receptionist acknowledgement projection.
-- The shared journal publishes these callbacks atomically with inbox/outbox state.
local JSON=require("json_codec")
local M={}
local events={native_trade_prompt="trade_decision",native_trade_prepare="trade_ready",
    native_trade_commit="trade_verified",native_trade_release="trade_ack",native_trade_abort="trade_ack"}
function M.completion_event(entry,outcome,receipt)
    local body=entry.body.body or entry.body
    local name=events[body.cmd]
    if not name then return nil end
    assert(outcome=="ACK","uncertain native work cannot publish a terminal NACK")
    assert(type(body.transaction_id)=="string" and #body.transaction_id==32
        and body.transaction_id:match("^[0-9a-f]+$"),"native transaction identity required")
    if body.cmd=="native_trade_commit" then
        assert(receipt.schema=="rby-file-backed-v1" and type(receipt.native)=="table" and type(receipt.file)=="table",
            "native COMMIT needs separately verified file evidence before completion")
    end
    return {event=name,transaction_id=body.transaction_id,command_id=entry.command_id,
        command_sequence=entry.command_sequence,receipt=receipt}
end
function M.acknowledge_event(payload,operation_id,baseline)
    local entry=baseline.receptionist_entry
    if payload.event=="receptionist_entered" and entry and entry.phase=="queued"
        and assert(JSON.encode(payload))==assert(JSON.encode(entry.payload))then
        entry.phase="acknowledged";entry.operation_id=operation_id;return baseline
    end
    local offer=baseline.gen1_receptionist
    if payload.event=="trade_offer" and offer and offer.phase=="queued"
        and assert(JSON.encode(payload))==assert(JSON.encode(offer.payload)) then
        offer.phase="acknowledged";offer.operation_id=operation_id
        return baseline
    end
end
return M
