-- Pure ABI-2/ABI-3 trade witness reader. No emulator APIs, writes or retained transaction state.
-- Offsets/constants below were emitted by the host-C offsetof/sizeof probe in
-- tests/unit/test_nds_native_witness.py against the committed NDS-2 abi.h.
-- That test recompiles the probe and compares EVERY entry; ABI-2 layout is also cross-checked.
-- A coherent witness is not proof of physical flash durability or server authorization.
local M = {}
local L = {
    mailbox_size=80, witness_size=80, witness_offset=80,
    mailbox_signature=0, mailbox_abi_version=4, mailbox_session_epoch=68, mailbox_producer_phase=72,
    witness_session_epoch=0, witness_visit_id=4, witness_token=8, witness_revision=24,
    witness_visit_flags=26, witness_milestones=28, witness_milestone_seq=32,
    witness_final_result=42, witness_save_status=43, witness_milestone_frame=44,
    witness_old_pid=64, witness_old_otid=68, witness_received_pid=72, witness_received_otid=76,
    token_size=16, milestone_count=5, signature=1263422547, abi_nds=3,
    pre_save_ok=1, commit_entered=2, scene_evolution_done=4, post_save_ok=8, final_result=16,
    success_milestones=31, save_ok=1, save_pending=2, save_failed=255,
    phase_done=4, phase_uncertain=5, result_committed=1, result_unchanged=2,
    result_uncertain=3, visit_flags=3,
}

local function uint(v, maximum)
    return type(v)=="number" and v%1==0 and v>=0 and v<=maximum
end
local function plain(t) return type(t)=="table" and getmetatable(t)==nil end
local function callable(f) return type(f)=="function" or type(f)=="userdata" end
local function copy(t)
    local out={};for k,v in pairs(t) do out[k]=v end;return out
end
function M.layout() return copy(L) end

local function bytes(raw,n)
    local out={}
    if type(raw)=="string" then
        if #raw~=n then return nil end
        for i=1,n do out[i]=raw:byte(i) end
    elseif plain(raw) then
        local count=0
        for k,v in pairs(raw) do
            if not uint(k,n) or k==0 or not uint(v,255) then return nil end
            count=count+1;out[k]=v
        end
        if count~=n then return nil end
    else return nil end
    return out
end
local function word(raw,offset,width)
    local value=0
    for i=width,1,-1 do value=value*256+raw[offset+i] end
    return value
end

-- Structural predicate from slink_trade_success_is_durable, not an admission/flash oracle.
function M.success(w,prepare_seq,scene_seq,expected_pid,expected_otid)
    if not plain(w) or not plain(w.milestone_seq) or not uint(w.bits,0xFFFFFFFF)
        or not uint(w.flags,0xFFFF) or not uint(prepare_seq,0xFFFF) or not uint(scene_seq,0xFFFF)
        or not uint(expected_pid,0xFFFFFFFF) or not uint(expected_otid,0xFFFFFFFF) then
        return false,"success:arguments"
    end
    if w.milestone_seq[1]~=prepare_seq then return false,"success:prepare_sequence" end
    for i=2,L.milestone_count do
        if w.milestone_seq[i]~=scene_seq then return false,"success:scene_sequence" end
    end
    if w.result~=L.result_committed then return false,"success:result" end
    if (w.flags & L.visit_flags)~=L.visit_flags then return false,"success:consent" end
    if (w.bits & L.success_milestones)~=L.success_milestones then return false,"success:milestones" end
    if w.saved~=L.save_ok then return false,"success:save" end
    if w.received_pid~=expected_pid or w.received_otid~=expected_otid then return false,"success:identity" end
    return true,nil
end

-- Reconciliation classification, NOT the native producer phase. Valid post-commit PENDING
-- remains pending=true in the snapshot, but its durability is UNCERTAIN until success.
-- On a rejected read use classify(nil, context.seen): never downgrade a known commit.
function M.classify(w,seen)
    seen=seen or 0
    if not uint(seen,L.success_milestones) then return nil,"context:seen" end
    if w~=nil and (not plain(w) or not uint(w.bits,L.success_milestones)
        or not uint(w.result,L.result_uncertain)) then return nil,"snapshot:shape" end
    if w and w.result==L.result_committed and w.durable_success==true then return "COMMITTED",nil end
    if (seen & L.commit_entered)~=0 or (w and ((w.bits & L.commit_entered)~=0
        or w.result==L.result_uncertain)) then return "UNCERTAIN",nil end
    if not w then return "UNKNOWN",nil end
    if w.result==L.result_unchanged then return "UNCHANGED",nil end
    return "PENDING",nil
end

local function context(t,final_seq)
    if not plain(t) or not uint(t.epoch,0xFFFFFFFF) or t.epoch==0
        or not uint(t.visit,0xFFFFFFFF) or t.visit==0 or not uint(t.pid,0xFFFFFFFF)
        or not uint(t.otid,0xFFFFFFFF) then return nil,"context:identity" end
    local opaque=bytes(t.opaque,L.token_size)
    if not opaque then return nil,"context:token" end
    local nonzero=false;for _,v in ipairs(opaque) do if v~=0 then nonzero=true end end
    if not nonzero then return nil,"context:token" end
    for _,key in ipairs({"prepare_seq","scene_seq"}) do
        if t[key]~=nil and (not uint(t[key],0xFFFF) or t[key]==0) then return nil,"context:sequence" end
    end
    if final_seq~=nil and (not uint(final_seq,0xFFFF) or final_seq==0) then return nil,"context:sequence" end
    if t.seen~=nil and not uint(t.seen,L.success_milestones) then return nil,"context:seen" end
    if t.incoming~=nil and (not plain(t.incoming) or not uint(t.incoming.pid,0xFFFFFFFF)
        or not uint(t.incoming.otid,0xFFFFFFFF)) then return nil,"context:incoming" end
    local c=copy(t);c.opaque=opaque;c.seen=t.seen or 0
    c.incoming=t.incoming and copy(t.incoming) or nil
    return c,nil
end

-- new(io, {base=<mailbox address>, abi=2|3, layout=<optional compiled layout>}).
-- read_bytes(address,n) -> dense 1-based byte table or binary string; alternatively
-- read_u8/read_u16/read_u32. Missing wider reads are composed from the byte reader.
-- An explicitly supplied layout must match this ABI exactly; it is copied, never retained.
function M.new(io,config)
    if not plain(io) or not plain(config) or not uint(config.base,0xFFFFFFFF)
        or config.base+L.witness_offset+L.witness_size>0x100000000 then return nil,"config:base" end
    if config.abi~=2 and config.abi~=L.abi_nds then return nil,"abi:unsupported" end
    local layout=config.layout or L
    if not plain(layout) then return nil,"config:layout" end
    for k,v in pairs(L) do if layout[k]~=v then return nil,"config:layout" end end
    for k in pairs(layout) do if L[k]==nil then return nil,"config:layout" end end
    layout=copy(layout)
    local input={}
    for _,name in ipairs({"read_bytes","read_u8","read_u16","read_u32"}) do
        if io[name]~=nil and not callable(io[name]) then return nil,"config:reader" end
        input[name]=io[name]
    end
    if not input.read_bytes and not input.read_u8 then return nil,"config:reader" end
    local base,abi=config.base,config.abi
    local function block(address,n)
        if input.read_bytes then
            local raw=bytes(input.read_bytes(address,n),n)
            if not raw then error("invalid byte reader output") end
            return raw
        end
        local raw={}
        for i=1,n do
            local value=input.read_u8(address+i-1)
            if not uint(value,255) then error("invalid byte") end
            raw[i]=value
        end
        return raw
    end
    local function scalar(address,width)
        local fn
        if width==2 then fn=input.read_u16 else fn=input.read_u32 end
        local value
        if fn then value=fn(address) else value=word(block(address,width),0,width) end
        if width==4 and type(value)=="number" and value%1==0 and value>=-0x80000000 and value<0 then
            value=value & 0xFFFFFFFF
        end
        if not uint(value,width==2 and 0xFFFF or 0xFFFFFFFF) then error("invalid scalar") end
        return value
    end
    local function mailbox()
        return {signature=scalar(base+layout.mailbox_signature,4),
            abi=scalar(base+layout.mailbox_abi_version,2),
            epoch=scalar(base+layout.mailbox_session_epoch,4),
            phase=scalar(base+layout.mailbox_producer_phase,4)}
    end
    local function read(c,final_seq)
        local mb_before=mailbox()
        if mb_before.signature~=layout.signature then return nil,"mailbox:signature" end
        if mb_before.abi~=abi then return nil,"abi:mismatch" end
        local address=base+layout.witness_offset
        local before=scalar(address+layout.witness_revision,2)
        local raw=block(address,layout.witness_size)
        local after=scalar(address+layout.witness_revision,2)
        if before==0 or before%2~=0 or before~=after
            or word(raw,layout.witness_revision,2)~=before then return nil,"snapshot:revision" end
        local mb=mailbox()
        for k,v in pairs(mb_before) do if mb[k]~=v then return nil,"mailbox:changed" end end
        if mb.epoch~=c.epoch then return nil,"identity:mailbox_epoch" end
        if not uint(mb.phase,layout.phase_uncertain) then return nil,"mailbox:phase" end
        local w={abi=abi,revision=before,phase=mb.phase,
            epoch=word(raw,layout.witness_session_epoch,4),visit=word(raw,layout.witness_visit_id,4),
            old_pid=word(raw,layout.witness_old_pid,4),old_otid=word(raw,layout.witness_old_otid,4),
            bits=word(raw,layout.witness_milestones,4),flags=word(raw,layout.witness_visit_flags,2),
            result=raw[layout.witness_final_result+1],saved=raw[layout.witness_save_status+1],
            received_pid=word(raw,layout.witness_received_pid,4),received_otid=word(raw,layout.witness_received_otid,4),
            token={},milestone_seq={},milestone_frame={}}
        if w.epoch~=c.epoch or w.visit~=c.visit or w.old_pid~=c.pid or w.old_otid~=c.otid then
            return nil,"identity:witness"
        end
        for i=1,layout.token_size do
            w.token[i]=raw[layout.witness_token+i]
            if w.token[i]~=c.opaque[i] then return nil,"identity:token" end
        end
        local bits,flags,result,saved=w.bits,w.flags,w.result,w.saved
        if bits>layout.success_milestones or flags>layout.visit_flags or result>layout.result_uncertain then
            return nil,"witness:range"
        end
        if (bits & c.seen)~=c.seen then return nil,"milestones:regressed" end
        if (bits & layout.commit_entered)~=0 and (bits & layout.pre_save_ok)==0 then return nil,"milestones:order" end
        if (bits & layout.scene_evolution_done)~=0 and (bits & layout.commit_entered)==0 then return nil,"milestones:order" end
        if (bits & layout.post_save_ok)~=0 and (bits & layout.scene_evolution_done)==0 then return nil,"milestones:order" end
        if ((bits & layout.final_result)==0)~=(result==0) then return nil,"milestones:final_result" end
        -- ABI semantic divergence: PENDING is never a terminal save witness.
        local pending_allowed = abi == 3 and saved == layout.save_pending
        local pending_final = (bits & (layout.post_save_ok | layout.final_result)) ~= 0
        if pending_allowed and pending_final then return nil,"abi:pending_final" end
        if abi==3 and saved~=0 and saved~=layout.save_ok and saved~=layout.save_failed and not pending_allowed then
            return nil,"abi:save_status"
        end
        if (bits & layout.pre_save_ok)~=0 and (flags~=layout.visit_flags
            or (saved~=layout.save_ok and saved~=layout.save_failed and not pending_allowed)) then
            return nil,"abi:pre_save_status"
        end
        for i=0,layout.milestone_count-1 do
            local sequence=word(raw,layout.witness_milestone_seq+2*i,2)
            w.milestone_seq[i+1]=sequence
            w.milestone_frame[i+1]=word(raw,layout.witness_milestone_frame+4*i,4)
            if (bits & (1 << i))~=0 then
                local expected
                if i==0 then expected=c.prepare_seq elseif i==4 then expected=final_seq else expected=c.scene_seq end
                if expected==nil or sequence~=expected then return nil,"sequence:milestone" end
            end
        end
        if (result==layout.result_committed or result==layout.result_unchanged) and mb.phase~=layout.phase_done then
            return nil,"phase:done"
        end
        if result==layout.result_uncertain and mb.phase~=layout.phase_uncertain then return nil,"phase:uncertain" end
        if (bits & layout.post_save_ok)~=0 and (saved~=layout.save_ok or not c.incoming
            or w.received_pid~=c.incoming.pid or w.received_otid~=c.incoming.otid) then
            return nil,"identity:post_save"
        end
        if result==layout.result_committed and (bits~=layout.success_milestones or flags~=layout.visit_flags
            or saved~=layout.save_ok or not c.incoming or w.received_pid~=c.incoming.pid
            or w.received_otid~=c.incoming.otid) then return nil,"success:incomplete" end
        if result==layout.result_unchanged and (bits & 14)~=0 then return nil,"result:unchanged_after_commit" end
        w.pending=result==0
        w.durable_success=false
        if c.incoming then w.durable_success=M.success(w,c.prepare_seq,c.scene_seq,c.incoming.pid,c.incoming.otid) end
        if result==layout.result_committed and not w.durable_success then return nil,"success:sequence" end
        w.classification=M.classify(w,c.seen)
        return w,nil
    end
    local reader={}
    function reader.read(t,final_seq)
        local c,reason=context(t,final_seq)
        if not c then return nil,reason end
        local ok,w,why=pcall(read,c,final_seq)
        if not ok then return nil,"read:error" end
        if not w then return nil,why or "read:invalid" end
        return w,nil
    end
    return reader,nil
end
return M
