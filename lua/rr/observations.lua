-- RR temporal observations. Input tables are read-only snapshots; returned events
-- are facts for the caller to publish. No RAM, mailbox, network, HUD or persistence
-- side effects occur here. Durable frame publication remains a coordinator concern.
local Observations = {}
local JSON = require("json_codec")
local function clone(value)
    if type(value)~="table" then return value end
    local kind=JSON.kind(value)
    local result=kind=="array" and JSON.array() or (kind=="object" and JSON.object() or {})
    for key,item in pairs(value) do result[key]=clone(item) end
    return result
end
local function ledger(previous,counter)
    local state={last_hp={},pending={},engine_pending={},suppression={},reported={},ignored={},claimed=0,evidence=0,
        counter_base=counter or 0,last_counter=counter or 0,had_alive=false,whiteout=false,natural=0}
    for key,mon in pairs(previous or {}) do
        if not mon.is_egg then
            state.last_hp[key]=mon.hp
            if mon.hp>0 then state.had_alive=true end
        end
    end
    return state
end
local function integer(value,maximum)
    return type(value)=="number" and value%1==0 and value>=0 and value<=(maximum or 9007199254740991)
end
local function valid_ledger(state)
    if type(state)~="table" then return false end
    for _,field in ipairs({"claimed","evidence","natural"}) do if not integer(state[field]) then return false end end
    for _,field in ipairs({"last_counter","counter_base"}) do if not integer(state[field],255) then return false end end
    for _,field in ipairs({"had_alive","whiteout"}) do if type(state[field])~="boolean" then return false end end
    for _,field in ipairs({"counter_untrusted","ended","loss","suspended"}) do
        if state[field]~=nil and type(state[field])~="boolean" then return false end
    end
    for _,field in ipairs({"last_hp","pending","engine_pending","suppression","reported","ignored"}) do
        if type(state[field])~="table" then return false end
        for key,value in pairs(state[field]) do
            if type(key)~="string" then return false end
            if field=="last_hp" and not integer(value,65535) then return false end
            if (field=="reported" or field=="ignored") and type(value)~="boolean" then return false end
            if (field=="pending" or field=="engine_pending") and (type(value)~="table" or not integer(value.frames)) then return false end
            if field=="pending" or field=="engine_pending" then
                for _,flag in ipairs({"outside","outside_origin","prior_battle"}) do
                    if value[flag]~=nil and type(value[flag])~="boolean" then return false end
                end
                if value.area_id~=nil and type(value.area_id)~="string" then return false end
            end
            if field=="suppression" and value~="engine" and value~="external" then return false end
        end
    end
    return true
end
local function valid_record(record,next_id,ended)
    if type(record)~="table" or not integer(record.id,next_id) or record.id==0
        or type(record.origin)~="table" or type(record.origin.area_id)~="string"
        or type(record.origin.wild)~="boolean" or type(record.captured)~="boolean" then return false end
    if ended then
        return integer(record.outcome,255) and integer(record.deadline) and type(record.foe)=="table"
    end
    return type(record.borrowed)=="boolean"
end
local function carry_pending(previous,current)
    if not previous then return end
    for key,pending in pairs(previous.pending) do
        current.pending[key]=clone(pending)
        current.pending[key].prior_battle=true
        current.last_hp[key]=previous.last_hp[key]
    end
    for key,pending in pairs(previous.engine_pending) do
        current.engine_pending[key]=clone(pending);current.engine_pending[key].prior_battle=true
        current.suppression[key]="engine";current.last_hp[key]=previous.last_hp[key]
    end
end

function Observations.new(options)
    options=options or {}
    local grace=options.result_grace or 90
    local next_id,active,death,recent_id=0,nil,nil,nil
    local results={}
    local self={}

    function self.begin_battle(origin,previous,counter,frame,borrowed)
        -- A subsequent battle establishes that the previous engine transaction
        -- ended. Resolve its known failure before a later capture in the same area.
        for _,record in ipairs(results) do
            if record.outcome~=0 and record.outcome~=7 then record.deadline=frame end
        end
        next_id=next_id+1
        active={id=next_id,origin=clone(origin),borrowed=borrowed==true,captured=false}
        if borrowed then
            if death then death.suspended=true end
        else
            local next_death=ledger(previous,counter)
            carry_pending(death,next_death)
            death=next_death;death.area_id=origin.area_id
        end
        return self.drain_results(frame)
    end

    function self.set_box_origin(box_index,occupied)
        if not active then return end
        -- Do not retain the mutable client box-snapshot table.
        active.origin.box_index=box_index
        active.origin.box_occupied={}
        for slot=0,29 do active.origin.box_occupied[slot+1]=occupied and occupied[slot] or false end
    end

    function self.end_battle(outcome,foe,frame)
        if not active then return end
        if not active.borrowed then
            results[#results+1]={id=active.id,origin=clone(active.origin),outcome=outcome or 0,
                foe=clone(foe or {}),captured=active.captured,deadline=frame+grace}
            if death then death.ended=true;death.loss=outcome==2 end
        end
        recent_id=not active.borrowed and active.id or nil
        active=nil
        -- Pending death/living edges intentionally survive end-of-battle cleanup.
    end

    function self.current_battle_id() return active and not active.borrowed and active.id or recent_id end
    function self.capture(area_id,key,battle_id)
        if type(key)~="string" or key=="" then return false,"capture identity required" end
        local candidate,count=nil,0
        local function consider(record)
            if not record.borrowed and record.origin.area_id==area_id and not record.captured
                and (battle_id==nil or record.id==battle_id) then candidate=record;count=count+1 end
        end
        if active then consider(active) end
        for _,record in ipairs(results) do consider(record) end
        if count~=1 then return false,"capture context is missing or ambiguous" end
        candidate.captured=true;candidate.capture_key=key
        return true
    end

    function self.drain_results(frame)
        local events,keep={},{}
        for _,record in ipairs(results) do
            if record.captured then
                -- Physical acquisition was observed; the caller's rules layer owns
                -- whether it is legal. Never convert it into an encounter failure.
            elseif frame>=record.deadline and record.outcome~=0 and record.outcome~=7 then
                if record.origin.wild and not record.borrowed then
                    events[#events+1]={event="no_catch",area_id=record.origin.area_id,
                        species_id=record.foe.species_id or 0,level=record.foe.level or 0}
                end
            elseif not record.origin.wild then
                -- A trainer outcome has no wild-acquisition obligation.
            else
                -- CAUGHT without a matching acquisition, or an unknown outcome,
                -- retains its original evidence. A timer cannot invent its result.
                keep[#keep+1]=record
            end
        end
        results=keep
        return events
    end

    function self.pending_results() return clone(results) end

    function self.checkpoint()
        return {schema="rr-temporal-observations-v1",next_id=next_id,recent_id=recent_id,
            policy={death_evidence="counter-or-settled-state-v1",result_grace=grace},active=clone(active),death=clone(death),
            results=JSON.array(clone(results))}
    end
    function self.restore(document)
        -- The caller must first validate the journal's cartridge/save/context
        -- binding. Restoring detector data is not authorization to rewind a game.
        if type(document)~="table" or document.schema~="rr-temporal-observations-v1"
            or not integer(document.next_id) or type(document.policy)~="table"
            or document.policy.death_evidence~="counter-or-settled-state-v1" or document.policy.result_grace~=grace
            or JSON.kind(document.results)~="array" then return false,"invalid RR detector checkpoint" end
        if document.recent_id~=nil and (not integer(document.recent_id,document.next_id) or document.recent_id==0) then
            return false,"invalid recent battle checkpoint"
        end
        if document.active~=nil and not valid_record(document.active,document.next_id,false) then
            return false,"invalid active battle checkpoint"
        end
        if document.death~=nil and not valid_ledger(document.death) then return false,"invalid death checkpoint" end
        local seen={}
        if document.active then seen[document.active.id]=true end
        local count=0
        for index,record in pairs(document.results) do
            if not integer(index,#document.results) or index==0 then return false,"invalid result sequence" end
            if not valid_record(record,document.next_id,true) then return false,"invalid result checkpoint" end
            if seen[record.id] then return false,"duplicate battle checkpoint" end
            seen[record.id]=true;count=count+1
        end
        if count~=#document.results then return false,"incomplete result sequence" end
        next_id,active,death,recent_id,results=document.next_id,clone(document.active),clone(document.death),document.recent_id,clone(document.results)
        return true
    end

    function self.migrate(old_key,new_key)
        if not death then return end
        for _,field in ipairs({"last_hp","pending","engine_pending","suppression","reported","ignored"}) do
            if death[field][old_key]~=nil then
                death[field][new_key]=death[field][old_key];death[field][old_key]=nil
            end
        end
    end

    function self.observe(input)
        if not input.observable or input.borrowed then return {} end
        if not death then death=ledger(input.previous or input.party,input.counter) end
        if death.suspended then
            local resumed=ledger(input.previous or input.party,input.counter)
            carry_pending(death,resumed);death=resumed
        end
        local events={}
        local counter=input.counter
        if counter~=nil then
            if input.counter_reliable==false and counter-death.counter_base>death.claimed then
                death.counter_untrusted=true
                death.counter_reason="settled counter has an unattributed player-battler zero"
            end
            if counter<death.last_counter then
                -- A late engine baseline reset must not wrap into 255 faint credits.
                death.counter_base=counter;death.evidence=death.claimed
                death.counter_untrusted=death.claimed>0
            end
            death.last_counter=counter
            if not death.counter_untrusted then
                death.evidence=math.max(death.evidence,counter-death.counter_base)
                for _,event in ipairs(input.native_events or {}) do
                    -- EvRing.a is the same cumulative counter, not another faint.
                    -- A value beyond current RAM belongs to delayed/stale evidence.
                    if event.type==1 and event.a>=death.counter_base and event.a<=counter then
                        death.evidence=math.max(death.evidence,event.a-death.counter_base)
                    end
                end
            end
        end
        if input.outcome==2 and input.battle_just_ended then death.loss=true end
        local zero_keys,engine_keys,eligible,all_zero={},{},0,true
        for key,mon in pairs(input.party) do
            if not mon.is_egg then
                local cause=input.suppressed and input.suppressed[key]
                if cause=="engine" then death.suppression[key]="engine"
                elseif cause=="external_override" then
                    death.suppression[key]="external";death.engine_pending[key]=nil
                elseif cause and not death.suppression[key] then
                    -- A natural zero already pending before a partner command is
                    -- still an engine-counter candidate; do not erase its cause.
                    death.suppression[key]=death.pending[key] and not death.pending[key].outside_origin and "engine" or "external"
                end
                eligible=eligible+1
                if mon.hp>0 then
                    death.had_alive=true;all_zero=false;death.pending[key]=nil
                    death.engine_pending[key]=nil
                else
                    if death.suppression[key] then
                        local candidate=death.pending[key] or death.engine_pending[key]
                        death.pending[key]=nil
                        if not death.reported[key] and not death.ignored[key] then
                            if death.suppression[key]=="engine" then
                                death.engine_pending[key]=candidate or {frames=0}
                                death.engine_pending[key].frames=death.engine_pending[key].frames+1
                                engine_keys[#engine_keys+1]=key
                            else
                                -- A direct external HP write need not increment
                                -- gBattleResults. It consumes no native ordinal.
                                death.ignored[key]=true
                            end
                        end
                    elseif not death.reported[key] and not death.ignored[key] then
                        if (death.last_hp[key] or 0)>0 and not death.pending[key] then
                            local outside=not input.in_battle and not input.battle_just_ended
                            death.pending[key]={frames=0,outside_origin=outside,
                                outside=outside and input.outside_authoritative==true,
                                area_id=input.battle_just_ended and death.area_id or input.area_id}
                        end
                        if death.pending[key] then
                            death.pending[key].frames=death.pending[key].frames+1
                            zero_keys[#zero_keys+1]=key
                        end
                    end
                end
                death.last_hp[key]=mon.hp
            end
        end
        table.sort(zero_keys) -- deterministic simultaneous-KO output order
        local current_candidates=0
        for _,key in ipairs(zero_keys) do
            if not death.pending[key].prior_battle and not death.pending[key].outside_origin then
                current_candidates=current_candidates+1
            end
        end
        for _,key in ipairs(engine_keys) do
            if not death.engine_pending[key].prior_battle then current_candidates=current_candidates+1 end
        end
        local available=death.evidence-death.claimed
        local settled=available>=current_candidates and current_candidates>0
        local settled_loss=death.loss and not input.in_battle and all_zero
        for _,key in ipairs(engine_keys) do
            local pending=death.engine_pending[key]
            local native_proof=settled and not pending.prior_battle
            if native_proof or settled_loss or (input.settled_zero and input.settled_zero[key]) then
                death.engine_pending[key]=nil;death.ignored[key]=true
                if native_proof then death.claimed=death.claimed+1 end
            end
        end
        for _,key in ipairs(zero_keys) do
            local pending=death.pending[key]
            local native_proof=settled and not pending.prior_battle and not pending.outside_origin
            -- Elapsed zero-HP frames are diagnostic only. Protection, scripts and
            -- engine writeback can outlast any timer; time cannot prove a death.
            local field_proof=pending.outside_origin and input.outside_authoritative==true
            if native_proof or pending.outside or field_proof or settled_loss or (input.settled_zero and input.settled_zero[key]) then
                death.pending[key]=nil;death.reported[key]=true
                if native_proof then death.claimed=death.claimed+1 end
                death.natural=death.natural+1
                events[#events+1]={event="faint",key=key,area_id=pending.area_id or input.area_id}
            end
        end
        local pending_visible=false
        for _,key in ipairs(zero_keys) do if death.pending[key] then pending_visible=true end end
        for _,key in ipairs(engine_keys) do if death.engine_pending[key] then pending_visible=true end end
        if eligible>0 and all_zero and death.had_alive and not pending_visible and not death.whiteout
            and (death.natural>0 or death.loss) then
            death.whiteout=true;events[#events+1]={event="whiteout"}
        end
        return events
    end
    return self
end
return Observations
