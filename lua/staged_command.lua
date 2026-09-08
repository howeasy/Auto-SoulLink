-- Durable ordered composition of command adapters. No authority or host effects
-- are supplied here: each child owns its evidence, effects and receipt policy.
local JSON=require("json_codec")
local Canonical=require("journal_document")
local M={SCHEMA="slink-staged-command-v1",INTENT="slink-staged-command-intent-v1"}
local function copy(v)return assert(JSON.decode(assert(JSON.encode(v))))end
function M.initial()return {schema=M.SCHEMA,phase="idle"}end
function M.new(options)
    local store,stages=assert(options.store),assert(options.stages)
    assert(type(stages)=="table" and stages~=JSON.null and getmetatable(stages)==nil
        and JSON.kind(stages)~="object","dense ordered stage list required")
    local count,largest=0,0
    for key in pairs(stages)do
        assert(type(key)=="number" and key%1==0 and key>=1 and key<=16,"dense ordered stage list required")
        count=count+1;largest=math.max(largest,key)
    end
    assert(count>0 and count==largest and type(options.context)=="function"
        and type(options.verify_completed)=="function","bounded stages, owned context and final readback required")
    assert(options.receipt==nil or type(options.receipt)=="function","receipt converter must be callable")
    local read_context,verify_completed,convert=options.context,options.verify_completed,options.receipt
    local names,adapters={},{}
    for i,stage in ipairs(stages)do
        assert(type(stage.name)=="string" and stage.name:match("^[a-z][a-z0-9_]*$")
            and #stage.name<=32 and not adapters[stage.name],"unique bounded stage name required")
        local methods={}
        for _,method in ipairs({"prepare","classify","apply","receipt"})do
            assert(type(stage.adapter[method])=="function","complete child command adapter required")
            methods[method]=stage.adapter[method]
        end
        names[i]=stage.name;adapters[stage.name]=methods
    end
    local function sha(v)return store.backend.sha256(assert(Canonical.encode(v)))end
    local function context()
        local value=read_context()
        assert(type(value)=="string" and #value>=1 and #value<=256,"explicit bounded physical context required")
        return value
    end
    local function state()
        local value=assert(store:read())
        assert(value.schema==M.SCHEMA and ({idle=true,active=true,complete=true})[value.phase],"invalid staged command state")
        return value
    end
    local function pending(identity)
        return "armed",{schema="slink-command-stage-pending-v1",command_id=identity.command_id}
    end
    local self={}
    local function retain(value)
        assert(value.context==context(),"staged command context changed during callback")
    end
    local function commit(value)
        retain(value)
        assert(store:commit(value))
        retain(value)
    end
    local function completed(value,body,identity)
        retain(value)
        local valid=verify_completed(copy(value.results),copy(body),copy(identity))
        retain(value)
        assert(valid==true,
            "completed stage effects no longer match physical readback")
        return "after",copy(value.results)
    end
    local function check(body,intent,identity)
        assert(intent.schema==M.INTENT and intent.command_id==identity.command_id
            and intent.command_sequence==identity.command_sequence and intent.body_digest==sha(body)
            and intent.context==context() and sha(intent.stages)==sha(names),"staged command/context changed")
        local value=state()
        if value.phase=="idle" or value.command_id~=identity.command_id then
            assert(value.phase=="idle" or value.phase=="complete","unfinished previous command requires recovery")
            value={schema=M.SCHEMA,phase="active",command_id=identity.command_id,
                intent_digest=sha(intent),context=intent.context,index=1,results=JSON.object()}
            commit(value)
        end
        assert(value.intent_digest==sha(intent) and value.context==context(),"staged lease belongs to another intent/context")
        return value
    end
    function self.prepare(body,identity)
        local value=state()
        assert(value.phase=="idle" or value.phase=="complete","unfinished staged command requires recovery")
        return {schema=M.INTENT,command_id=identity.command_id,command_sequence=identity.command_sequence,
            body_digest=sha(body),context=context(),stages=JSON.array(copy(names))}
    end
    function self.classify(body,intent,identity)
        local value=check(body,intent,identity)
        if value.phase=="complete"then return completed(value,body,identity)end
        local name=assert(names[value.index]);local adapter=adapters[name]
        if not value.child_intent then
            value.child_intent=assert(adapter.prepare(copy(body),copy(identity)))
            retain(value)
            commit(value) -- durable before a child can have an effect
        end
        retain(value)
        local phase,observed=adapter.classify(copy(body),copy(value.child_intent),copy(identity))
        retain(value)
        if phase=="before"then return "before",observed end
        if phase=="armed"then return pending(identity)end
        assert(phase=="after","child poststate is not proven")
        value.results[name]=assert(adapter.receipt(copy(body),copy(value.child_intent),copy(observed),copy(identity)))
        retain(value)
        value.index=value.index+1;value.child_intent=nil
        if value.index>#names then value.phase="complete"end
        commit(value) -- completed child is never applied again
        if value.phase=="complete"then return completed(value,body,identity)end
        return pending(identity)
    end
    function self.apply(body,intent,identity)
        local value=check(body,intent,identity)
        assert(value.phase=="active" and value.child_intent,"prepared child intent required")
        local adapter=adapters[assert(names[value.index])]
        local phase=adapter.classify(copy(body),copy(value.child_intent),copy(identity))
        retain(value)
        assert(phase=="before","child is not in its exact prestate")
        local result=adapter.apply(copy(body),copy(value.child_intent),copy(identity))
        retain(value)
        return result
    end
    function self.receipt(body,intent,observed,identity)
        local value=check(body,intent,identity)
        assert(value.phase=="complete" and sha(value.results)==sha(observed),"completed stage receipts differ")
        completed(value,body,identity)
        if convert then
            local result=convert(copy(value.results),copy(body),copy(identity))
            retain(value)
            assert(type(result)=="table" and result~=JSON.null,"configured receipt converter returned no object")
            result=copy(result)
            assert(JSON.kind(result)=="object" and next(result)~=nil,"configured receipt converter returned no receipt")
            return result
        end
        retain(value)
        return copy(value.results)
    end
    function self.current(command_id)
        local value=state()
        if value.phase~="active" or value.command_id~=command_id or not value.child_intent then return nil end
        retain(value)
        return names[value.index],copy(value.child_intent)
    end
    function self.stage(command_id)
        local value=state()
        if value.phase~="active" or value.command_id~=command_id or not value.child_intent then return nil end
        retain(value)
        return names[value.index],value.child_intent.schema
    end
    function self.completed(command_id,name)
        local value=state()
        if value.command_id~=command_id or value.results==nil or value.results[name]==nil then return false end
        retain(value)
        return true
    end
    return self
end
return M
