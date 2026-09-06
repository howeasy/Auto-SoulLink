-- RBY policy for the shared prepared-command executor. Not a production binding.
-- can_write MUST recheck admission, ROM/save ownership and an appropriate verified
-- execution checkpoint; a structurally valid party is not a safe-state predicate.
local JSON=require("json_codec")
local Receipts=require("gen1_command_receipts")
local M={SCHEMA="gen1-force-faint-intent-v1"}
local function same(a,b)return assert(JSON.encode(a))==assert(JSON.encode(b))end

function M.new(memory,variant,identity,can_write)
    assert(type(can_write)=="function","live admission/checkpoint callback required")
    assert(type(identity)=="table" and type(identity.ot_id)=="string" and type(identity.trainer_name)=="string",
        "admitted save identity required")
    local save_id,save_name=identity.ot_id,identity.trainer_name
    local function snapshot()
        local allowed,reason=can_write()
        if not allowed then return nil,reason or "write admission/checkpoint unavailable" end
        local observed,why=Receipts.party_snapshot(memory,variant)
        if not observed then return nil,why end
        if observed.save_id~=save_id or observed.save_name~=save_name then return nil,"save identity changed" end
        return observed
    end
    local function validate(body,intent)
        if type(intent)~="table" or intent.schema~=M.SCHEMA then return nil,"force-faint intent schema mismatch" end
        local expected,slot=Receipts.force_faint_expected(body,intent.before)
        if not expected then return nil,slot end
        if intent.before.variant~=variant or intent.before.save_id~=save_id or intent.before.save_name~=save_name
            or not same(expected,intent.after) or intent.slot~=slot then return nil,"force-faint intent changed" end
        return slot
    end
    return {
        prepare=function(body)
            local before,reason=snapshot()
            if not before then return nil,reason end
            local after,slot=Receipts.force_faint_expected(body,before)
            if not after then return nil,slot end
            return {schema=M.SCHEMA,before=before,after=after,slot=slot}
        end,
        classify=function(body,intent)
            local slot,reason=validate(body,intent)
            if slot==nil then return "diverged",reason end
            local observed,why=snapshot()
            if not observed then return "diverged",why end
            -- Already-zero HP is a proven no-op; do not execute a redundant write.
            if same(observed,intent.after) then return "after",observed end
            if same(observed,intent.before) then return "before",observed end
            return "diverged","party or battle state differs from both prepared states"
        end,
        apply=function(body,intent)
            local slot,reason=validate(body,intent)
            if slot==nil then error(reason,0) end
            local observed,why=snapshot()
            if not observed then error(why,0) end
            if not same(observed,intent.before) then error("prestate changed before force-faint",0) end
            -- forceFaint returns whether the battle mirror was written, not success.
            -- Only fresh exact readback can prove completion.
            memory.forceFaint(slot)
        end,
        receipt=function(body,intent,observed)
            local slot,reason=validate(body,intent)
            if slot==nil then return nil,reason end
            if not same(observed,intent.after) then return nil,"force-faint poststate differs" end
            return {schema=Receipts.RECEIPT_SCHEMA,before=intent.before,after=observed}
        end,
    }
end
return M
