-- Compose the existing native executor with durable applied evidence and SaveRAM.
-- The supplied save provider must perform the owned, complete file flush/readback.
local JSON=require("json_codec")
local Canonical=require("journal_document")
local M={}
local function copy(v)return assert(JSON.decode(assert(JSON.encode(v))))end
function M.new(options)
    local native,journal=options.native,options.journal
    assert(type(options.persist_save)=="function","owned native save-file provider required")
    assert(options.save_image==nil or type(options.save_image)=="function","save image reader must be callable")
    local adapter={prepare=native.prepare,classify=native.classify,apply=native.apply}
    function adapter.receipt(body,intent,observed,identity)
        local receipt=native.receipt(body,intent,observed,identity)
        local payload={event="trade_applied",transaction_id=body.transaction_id,command_id=identity.command_id,
            command_sequence=identity.command_sequence,receipt=receipt}
        local digest=journal.store.backend.sha256(assert(Canonical.encode(payload)))
        local state=assert(journal.store:read())
        local prior=state.observation.gen1_native_applied
        if prior and prior.command_id==identity.command_id then
            assert(prior.digest==digest,"native applied evidence changed")
        else
            local baseline=copy(state.observation)
            baseline.gen1_native_applied={command_id=identity.command_id,digest=digest}
            assert(journal:append(payload,baseline))
        end
        -- Failure leaves the intent/native lease and applied event recoverable;
        -- it cannot produce a terminal command outcome or repeat native apply.
        local file=options.persist_save(copy(receipt),copy(intent),copy(identity))
        assert(type(file)=="table" and file.schema=="slink-saveram-file-v1"
            and file.flushed==true and file.readback==true,"verified native save-file receipt required")
        local result={schema="rby-file-backed-v1",native=copy(receipt),file=copy(file)}
        if options.save_image then
            local raw=options.save_image(copy(file),copy(identity))
            assert(type(raw)=="string" and #raw==file.byte_length*2 and raw:match("^[0-9A-F]+$"),
                "complete verified file image required")
            result.save_image_hex=raw
        end
        return result
    end
    return adapter
end
return M
