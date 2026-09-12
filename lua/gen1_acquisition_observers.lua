-- Durable-boundary assembly of capture witnesses, completed scripted grants, static-battle
-- origins/ends, NPC in-game exchanges, wild-encounter boundaries and ordinary evolutions into one frame-ordered
-- {kind, receipt} list. Wild rows are transport only: no catch policy lives here.
-- prepare is read-only. The frame owner MUST persist state and receipts before
-- drain, and must call ready before allowing another physical frame.
local JSON=require("json_codec")
local CaptureData=require("gen1_capture_sites")
local M={SCHEMA="rby-acquisition-observer-state-v1",MAX_RECEIPTS=16}
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
local function same(a,b)return assert(JSON.encode(a))==assert(JSON.encode(b))end
local function integer(n)return type(n)=="number"and n%1==0 and n>=0 and n<=9007199254740991 end
function M.new(options)
    assert(type(options.owned)=="function"and type(options.held)=="function","owned acquisition observers required")
    local owner=copy(options.owned())
    assert(type(owner.context_generation)=="string"and type(owner.physical_instance)=="string","physical acquisition scope required")
    local nonce=assert((options.new_nonce or require("platform_identity").new_nonce)())
    local common={variant=options.variant,final_sha1=options.final_sha1,owned=options.owned,held=options.held}
    local capture,grants,static,exchange,wild,evolution=options.capture,options.grants,options.static,options.npc_exchange,options.wild,options.evolution
    local opened,reason=pcall(function()
        capture=capture or require("gen1_capture_observer").new(common)
        grants=grants or require("gen1_grant_observer").new(common)
        static=static or require("gen1_static_observer").new(common)
        exchange=exchange or require("gen1_npc_exchange_observer").new(common)
        wild=wild or require("gen1_wild_encounter_observer").new(common)
        evolution=evolution or require("gen1_evolution_observer").new(common)
    end)
    if not opened then
        for _,pair in ipairs({{capture,options.capture},{grants,options.grants},{static,options.static},
                {exchange,options.npc_exchange},{wild,options.wild},{evolution,options.evolution}})do
            if pair[1]and not pair[2]then pair[1].close()end
        end
        error(reason,0)
    end
    local self={};local failed=nil
    local function check()
        assert(not failed,failed)
        assert(options.held()==true and same(owner,options.owned()),"acquisition boundary lost held ownership")
        assert(gameinfo.getromhash():lower()==options.final_sha1,"acquisition cartridge changed")
        local c,g,s,x,w,e=capture.status(),grants.status(),static.status(),exchange.status(),wild.status(),evolution.status()
        for _,st in ipairs({c,g,s,x,w,e})do assert(not st.failed and not st.closed,"acquisition hook failed or closed")end
        return c,g,s,x,w,e
    end
    -- The witness whose hook completed a row: its frame orders the merged list.
    local function completion(row)
        local r=row.receipt
        if row.kind=="capture"then return r.receipt["end"]end
        if row.kind=="grant"then return r.paid or r["return"]end
        if row.kind=="evolution"then return r.after end
        if row.kind=="wild_begin"or row.kind=="wild_end"then return r.witness end
        return r.began or r["end"]or r["return"]
    end
    local function validate(state)
        assert(type(state)=="table"and state.schema==M.SCHEMA,"persisted acquisition observer state required")
        local keys={schema=true,variant=true,final_sha1=true,context_generation=true,physical_instance=true,
            frame=true,capture_open=true,grant_open=true,grant_incarnation=true,native_handoff_operation_id=true,evolution_open=true}
        local count=0;for key in pairs(state)do assert(keys[key],"unknown acquisition observer state field");count=count+1 end
        assert(count==9+(state.native_handoff_operation_id~=nil and 1 or 0)+(state.evolution_open~=nil and 1 or 0)
            and (state.native_handoff_operation_id==nil or type(state.native_handoff_operation_id)=="string"
            and #state.native_handoff_operation_id==32 and state.native_handoff_operation_id:match("^[0-9a-f]+$"))
            and state.variant==options.variant and state.final_sha1==options.final_sha1
            and state.context_generation==owner.context_generation and state.physical_instance==owner.physical_instance,
            "acquisition observer state belongs to another physical context")
        assert(integer(state.frame)and integer(state.grant_open)and state.grant_open<=32,"bounded acquisition source progress required")
        assert(type(state.grant_incarnation)=="string","grant observer incarnation required")
        assert(state.evolution_open==nil or integer(state.evolution_open)and state.evolution_open<=1,"bounded evolution source progress required")
        local open=state.capture_open
        assert(open==JSON.null or type(open)=="table"and(open.kind=="party_begin"or open.kind=="box_begin")
            and integer(open.frame)and open.frame<=state.frame,"invalid persisted capture call")
        if state.grant_open>0 then
            assert(state.grant_incarnation==nonce,"open grant call was lost; reconnect requires source reconciliation")
        end
        if (state.evolution_open or 0)>0 then
            assert(state.grant_incarnation==nonce,"open evolution call was lost; reconnect requires source reconciliation")
        end
    end
    function self:initial(frame)
        local c,g,s,x,w,e=check()
        assert(integer(frame)and frame==emu.framecount()and c.pending==0 and g.pending==0 and g.in_flight==0
            and s.pending==0 and s.in_flight==0 and x.pending==0 and not x.removing and w.pending==0 and e.pending==0 and e.in_flight==0,
            "acquisition observers cannot adopt unrecorded source history")
        return {schema=M.SCHEMA,variant=options.variant,final_sha1=options.final_sha1,
            context_generation=owner.context_generation,physical_instance=owner.physical_instance,
            frame=frame,capture_open=JSON.null,grant_open=0,grant_incarnation=nonce,evolution_open=0}
    end
    function self:ready(state)
        local c,g,s,x,w,e=check();validate(state)
        assert(state.frame==emu.framecount(),"acquisition source state differs from held frame")
        assert(c.pending==0 and g.pending==0 and s.pending==0 and x.pending==0 and w.pending==0 and e.pending==0
            and g.in_flight==state.grant_open and e.in_flight==(state.evolution_open or 0),
            "previous acquisition witnesses were not durably drained")
        return true
    end
    function self:prepare(state)
        local _,g,s,x,w,e=check();validate(state)
        local frame=emu.framecount()
        assert(frame==state.frame+1,"acquisition assembly requires exactly one returned frame")
        local captured,granted,statics,exchanged,wilds,evolved=capture.peek(),grants.peek(),static.peek(),exchange.peek(),wild.peek(),evolution.peek()
        local next_state=copy(state);local receipts=JSON.array()
        for _,witness in ipairs(captured)do
            assert(integer(witness.frame)and witness.frame>state.frame and witness.frame<=frame,
                "capture witness lies outside the returned physical step")
            if witness.kind=="party_begin"or witness.kind=="box_begin"then
                assert(next_state.capture_open==JSON.null,"overlapping capture delivery calls")
                next_state.capture_open=copy(witness)
            elseif witness.kind=="party_end"or witness.kind=="box_end"then
                local before=next_state.capture_open
                local destination=witness.kind=="party_end"and"party"or"box"
                assert(before~=JSON.null and before.kind==destination.."_begin"and before.sp==witness.sp,
                    "capture return lost or changed its persisted call")
                receipts[#receipts+1]={kind="capture",receipt={schema="rby-capture-receipt-v1",
                    source_sha256=CaptureData.sha256,variant=options.variant,
                    context_generation=owner.context_generation,final_sha1=options.final_sha1,
                    receipt={destination=destination,begin=copy(before),["end"]=copy(witness)}}}
                next_state.capture_open=JSON.null
            else error("unknown capture delivery witness",0)end
        end
        for _,receipt in ipairs(granted)do receipts[#receipts+1]={kind="grant",receipt=copy(receipt)}end
        for _,receipt in ipairs(statics)do
            receipts[#receipts+1]={kind=receipt.began and"static_origin"or"static_battle_end",receipt=copy(receipt)}
        end
        for _,receipt in ipairs(exchanged)do receipts[#receipts+1]={kind="npc_exchange",receipt=copy(receipt)}end
        for _,receipt in ipairs(wilds)do
            assert(receipt.kind=="begin"or receipt.kind=="end","unknown wild encounter boundary")
            receipts[#receipts+1]={kind="wild_"..receipt.kind,receipt=copy(receipt)}
        end
        for _,receipt in ipairs(evolved)do receipts[#receipts+1]={kind="evolution",receipt=copy(receipt)}end
        -- Preserve order inside each producer and choose chronological order
        -- across producers. Ties retain collection order (capture, grant, static,
        -- exchange, wild, evolution); each producer's rows stay in its ordered callback sequence.
        -- No producer stamps a per-hook sequence, so same-frame rows of different
        -- producers cannot be interleaved; in Gen 1 every completion is separated
        -- from another producer's by text-box frames, so this equals hook order.
        local ordered={};for index,row in ipairs(receipts)do
            local last=completion(row)
            assert(type(last)=="table"and integer(last.frame)and last.frame>state.frame and last.frame<=frame,
                row.kind.." completion lies outside returned physical step")
            ordered[#ordered+1]={index=index,frame=last.frame,row=row}
        end
        table.sort(ordered,function(a,b)return a.frame==b.frame and a.index<b.index or a.frame<b.frame end)
        receipts=JSON.array();for _,row in ipairs(ordered)do receipts[#receipts+1]=row.row end
        assert(#receipts<=M.MAX_RECEIPTS,"acquisition frame receipt capacity exceeded")
        next_state.frame=frame;next_state.grant_open=g.in_flight;next_state.grant_incarnation=nonce;next_state.evolution_open=e.in_flight
        validate(next_state)
        return {state=next_state,receipts=receipts,capture=captured,grants=granted,static=statics,npc_exchange=exchanged,wild=wilds,evolution=evolved}
    end
    function self:drain(prepared)
        check();validate(prepared.state)
        assert(prepared.state.frame==emu.framecount(),"acquisition drain frame changed")
        assert(capture.acknowledge(prepared.capture))
        assert(grants.acknowledge(prepared.grants))
        assert(static.acknowledge(prepared.static))
        assert(exchange.acknowledge(prepared.npc_exchange))
        assert(wild.acknowledge(prepared.wild))
        assert(evolution.acknowledge(prepared.evolution))
        return true
    end
    function self:adopt_native_handoff(state,marker)
        local c,g,s,x,w,e=check();validate(state)
        assert(marker and marker.schema=="rby-client-native-frame-accounting-v1"and marker.phase=="handed_back"
            and marker.context_generation==owner.context_generation,"acknowledged native source handoff required")
        local handoff=assert(marker.handoff);local event=assert(handoff.payload);local payload=assert(event.payload)
        assert(handoff.phase=="acknowledged"and type(handoff.operation_id)=="string"and #handoff.operation_id==32
            and handoff.operation_id:match("^[0-9a-f]+$")and event.event=="native_frame_handoff"
            and payload.schema=="rby-native-frame-return-v1"and payload.ledger_sequence==marker.sequence,
            "native source handoff lacks exact acknowledged sequence")
        local frame=emu.framecount()
        assert(payload.host.frame==frame and payload.host.owner_id==owner.physical_instance and payload.host.held==true
            and payload.inventory.frame==frame and payload.inventory.context_generation==owner.context_generation
            and payload.inventory.final_sha1==options.final_sha1,"native source handoff changed physical scope or frame")
        assert(state.capture_open==JSON.null and state.grant_open==0 and c.pending==0 and g.pending==0 and g.in_flight==0
            and s.pending==0 and s.in_flight==0 and x.pending==0 and not x.removing and w.pending==0
            and e.pending==0 and e.in_flight==0 and (state.evolution_open or 0)==0,
            "native period contains acquisition witnesses; source reconciliation required")
        if state.native_handoff_operation_id==handoff.operation_id then
            assert(state.frame==frame,"native source handoff cannot replay over later frames")
            return copy(state)
        end
        local baseline=assert(marker.baseline)
        assert(baseline.phase=="idle"and baseline.frame==state.frame and same(baseline.acquisition_source,state),
            "native source handoff replaced the recorded loan baseline")
        local result=copy(state);result.frame=frame;result.native_handoff_operation_id=handoff.operation_id
        result.grant_incarnation=nonce
        return result
    end
    function self:status()
        return {failed=failed,capture=capture.status(),grants=grants.status(),static=static.status(),
            npc_exchange=exchange.status(),wild=wild.status(),evolution=evolution.status(),incarnation=nonce}
    end
    function self:close()
        capture.close();grants.close();static.close();exchange.close();wild.close();evolution.close();failed="acquisition observers closed"
    end
    return self
end
return M
