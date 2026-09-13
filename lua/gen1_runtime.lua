-- RBY metadata and exact durable-body binding for the shared client pump.
-- The launcher supplies the opened journal, qualified hold/context owner and
-- cartridge executor. This module does not auto-select a production runtime.
local JSON=require("json_codec")
local Runtime=require("durable_runtime")
local Session=require("gen1_runtime_profiles")
local PROTOCOL,HOLD_EVENT="slink-gen1-durable-v1","gen1_hold"
local M={PROTOCOL=PROTOCOL,HOLD_EVENT=HOLD_EVENT}
local function token(value)
    return type(value)=="string" and #value==32 and value:match("^[0-9a-f]+$")~=nil
end
local function equal(a,b)return assert(JSON.encode(a))==assert(JSON.encode(b))end

function M.metadata(variant,context,run_id,prepared_cartridge)
    if not token(run_id) then return nil,"durable RBY run identity required"end
    if type(context)~="table" or not token(context.context_generation) or not token(context.physical_instance) then
        return nil,"owned RBY physical context is unavailable"
    end
    local save=context.save_identity
    if type(save)~="table" or type(save.ot_id)~="string" or not save.ot_id:match("^[0-9A-F][0-9A-F][0-9A-F][0-9A-F]$")
        or type(save.trainer_name)~="string" or #save.trainer_name==0 or save.trainer_name:find("[%c]") then
        return nil,"owned RBY save identity is unavailable"
    end
    local cartridge,why=Session.metadata(variant,prepared_cartridge)
    if not cartridge then return nil,why end
    return {run_id=run_id,context_generation=context.context_generation,gen1_metadata={schema="slink-gen1-runtime-metadata-v1",
        cartridge=cartridge,save_identity={ot_id=save.ot_id,trainer_name=save.trainer_name},physical_instance=context.physical_instance}}
end

function M.metadata_matches(admission,report)
    return admission.game_id=="gen1_rby" and admission.scope=="metadata_only_no_physical_readiness"
        and admission.run_id==report.run_id
        and admission.rom_type==report.gen1_metadata.cartridge.variant
        and equal(admission.gen1_metadata,report.gen1_metadata)
        and equal(admission.save_identity,report.gen1_metadata.save_identity)
end

function M.unwrap(command,player)
    assert(type(command)=="table" and type(command.cmd)=="string" and type(command.body)=="table",
        "exact nested durable command body required")
    for key in pairs(command)do assert(key=="cmd" or key=="body","unexpected durable body wrapper field")end
    assert(command.cmd==command.body.cmd,"outer and stored command types differ")
    assert(command.body.player==nil or command.body.player==player,"native command belongs to the other player")
    return assert(JSON.decode(assert(JSON.encode(command.body))))
end

function M.new(options)
    assert(type(options)=="table" and type(options.read_context)=="function","owned RBY context reader required")
    assert(options.variant=="red" or options.variant=="blue" or options.variant=="yellow","RBY variant required")
    assert(token(options.run_id),"durable RBY run identity required")
    assert(type(options.operation_ready)=="function" and type(options.executor_adapter)=="table",
        "RBY readiness and cartridge executor required")
    local player,variant,run_id=options.player,options.variant,options.run_id
    local prepared=options.prepared_cartridge and assert(JSON.decode(assert(JSON.encode(options.prepared_cartridge))))or nil
    local adapter={}
    for _,name in ipairs({"prepare","classify","apply","receipt"})do
        assert(type(options.executor_adapter[name])=="function","RBY executor callback required: "..name)
        adapter[name]=function(body,...)return options.executor_adapter[name](M.unwrap(body,player),...)end
    end
    local fixed={protocol=PROTOCOL,hold_event=HOLD_EVENT,variant=variant,executor_adapter=adapter,
        pending_delivery_hint=true,
        semantic_settlement=options.semantic_settlement,
        metadata_matches=M.metadata_matches,
        read_hello=function()
            local context,why=options.read_context()
            if not context then return nil,why end
            return M.metadata(variant,context,run_id,prepared)
        end,
        operation_ready=function(body,intent,control)
            return options.operation_ready(M.unwrap(body,player),intent,control)
        end}
    if options.operation_execution~=nil then
        assert(type(options.operation_execution)=="table","RBY operation execution binding must be a table")
        local original=options.operation_execution
        assert(type(original.authorize_apply)=="function","RBY operation apply authority callback required")
        fixed.operation_execution=setmetatable({authorize_apply=function(body,...)
            return original.authorize_apply(M.unwrap(body,player),...)
        end},{__index=original})
    end
    return Runtime.new(setmetatable(fixed,{__index=function(_,key)
        if key~="reserved_events" then return options[key]end
        local supplied=options.reserved_events
        if supplied~=nil and type(supplied)~="table" then return supplied end
        local reserved={ghost_pos=true,trade_request=true,mon_chosen=true,menu_result=true,trade_done=true}
        for name,enabled in pairs(supplied or {})do reserved[name]=enabled end
        return reserved
    end}))
end
return M
