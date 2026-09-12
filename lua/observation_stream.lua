-- One durable observation in flight. The binding owns sampling and semantics.
-- Publication couples event and baseline; ACK couples cursor advancement.
local JSON=require("json_codec")
local M={}
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
local function same(a,b)return JSON.encode(a)==JSON.encode(b)end
function M.acknowledge(key,event,payload,operation_id,baseline)
    local entry=baseline[key]
    if payload.event==event and entry and entry.phase=="queued" and same(entry.payload,payload)then
        baseline[key]={phase="acknowledged",context=entry.context,sequence=payload.payload.sequence,
            operation_id=operation_id,observation=copy(payload.payload.observation)}
        return baseline
    end
end
function M.new(options)
    assert(options.journal and type(options.key)=="string" and options.key~=""
        and type(options.event)=="string" and type(options.seed)=="function"
        and type(options.sample)=="function" and type(options.verify)=="function" and type(options.owned)=="function",
        "owned observation stream callbacks required")
    local journal,key,event,seed,sample,verify,owned=options.journal,options.key,options.event,options.seed,options.sample,options.verify,options.owned
    local self={}
    function self:step()
        local context=copy(owned())
        local state,revision=journal.store:read();assert(state,revision)
        local baseline=state.observation
        local entry=baseline[key]
        if entry then
            assert(same(entry.context,context),"observation stream context changed")
            if entry.phase=="queued"then return false end
            assert(entry.phase=="acknowledged","invalid observation stream phase")
        else
            entry=seed(copy(baseline))
            if not entry then return false end
            entry=copy(entry)
        end
        assert(type(entry.sequence)=="number" and entry.sequence%1==0 and entry.sequence>=0
            and entry.sequence<9007199254740991 and type(entry.operation_id)=="string"
            and #entry.operation_id==32 and entry.operation_id:match("^[0-9a-f]+$"),"invalid observation cursor")
        local observed=sample(copy(entry.observation))
        assert(same(context,owned()),"observation owner changed while sampling")
        if observed==nil then return false end
        observed=copy(observed)
        assert(verify(copy(observed))==true and same(context,owned()),"observation changed before publication")
        local current,current_revision=journal.store:read();assert(current,current_revision)
        assert(current_revision==revision,"observation callbacks changed the journal baseline")
        local payload={event=event,payload={sequence=entry.sequence+1,previous_operation_id=entry.operation_id,
            observation=copy(observed)}}
        baseline[key]={phase="queued",context=context,payload=payload}
        assert(journal:append(payload,baseline))
        assert(verify(copy(observed))==true and same(context,owned()),"observation owner changed during publication")
        return true
    end
    function self.acknowledge_event(payload,operation_id,baseline)
        return M.acknowledge(key,event,payload,operation_id,baseline)
    end
    return self
end
return M
