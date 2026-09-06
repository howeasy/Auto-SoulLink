-- Shared session sequencing, pending-event bounds and response/command envelopes.
-- Cartridge evidence and capability policy are supplied by the game adapter.
local Identity=require("platform_identity")
local Wire=require("wire_protocol")
local M={}
local function token(value)
    return type(value)=="string" and #value==32 and value:match("^[0-9a-f]+$")~=nil
end
function M.new(options)
    assert(type(options)=="table" and type(options.protocol)=="string", "session protocol required")
    assert(type(options.read_metadata)=="function" and type(options.metadata_matches)=="function", "admission callbacks required")
    local variant,player=options.variant,options.player
    local self={variant=variant,player=player,state="contract_pending",sequence=0,
                pending={},pending_count=0,last_response=0}
    function self:revoke(reason)
        self.state="contract_pending"; self.reason=reason
        self.epoch=nil; self.session_id=nil; self.nonce=nil; self.report=nil
        self.save_id=nil; self.save_name=nil
        self.pending={}; self.pending_count=0; self.sequence=0; self.last_response=0
    end
    function self:begin()
        self:revoke("waiting for cartridge admission")
        local report,reason=options.read_metadata()
        if not report then self.reason=reason; return false,reason end
        local nonce,error=(options.new_nonce or Identity.new_nonce)()
        if not nonce then self.reason=error; return false,error end
        self.report=report; self.nonce=nonce
        return true
    end
    function self:decorate(evt)
        if evt.event=="hello" then
            if not self.nonce or self.state~="contract_pending" then return false,"HELLO is not pending" end
            for key,value in pairs(self.report) do evt[key]=value end
            evt.client_nonce=self.nonce; evt.seq=0
            evt.operation_id=options.durable_ids and self.nonce or self.nonce..":hello"
        else
            if self.state~="admitted" then return false,"cartridge is not admitted" end
            if self.pending_count>=128 or self.sequence>=9007199254740991 then return false,"session pending-event limit" end
            evt.seq=self.sequence+1
            if options.durable_ids then
                if not token(evt.operation_id) then return false,"persisted operation identifier required" end
            else evt.operation_id=self.nonce..":"..string.format("%.0f",evt.seq) end
            evt.admission_epoch=self.epoch; evt.session_id=self.session_id
        end
        evt.protocol=options.protocol; evt.player=self.player
        return true
    end
    function self:queued(evt)
        if evt.event=="hello" then self.state="hello_sent"; return end
        self.sequence=evt.seq; self.pending[evt.seq]=evt.operation_id
        self.pending_count=self.pending_count+1
    end
    function self:receive(packet)
        local _,shape_error=Wire.validate_response(packet)
        if shape_error then return nil,shape_error end
        if type(packet)~="table" or packet.protocol~=options.protocol or packet.player~=self.player then
            return nil,"response is not for this protocol/player"
        end
        local hello=self.state=="hello_sent"
        if hello then
            local hello_id=options.durable_ids and self.nonce or self.nonce..":hello"
            if packet.seq~=0 or packet.operation_id~=hello_id
                or type(packet.admission)~="table" or packet.admission.client_nonce~=self.nonce then
                return nil,"response is not for this HELLO"
            end
        else
            if self.state~="admitted" then return nil,"no admitted session" end
            if packet.admission_epoch~=self.epoch or packet.session_id~=self.session_id then
                return nil,"stale response epoch/session"
            end
            if type(packet.seq)~="number" or packet.seq%1~=0 or packet.seq<1 then return nil,"invalid response sequence" end
            if packet.seq<=self.last_response then return {},nil end
            if packet.seq~=self.last_response+1 or self.pending[packet.seq]~=packet.operation_id then
                return nil,"unsolicited or out-of-order response"
            end
        end
        if packet.ack~="ACK" then
            self:revoke(type(packet.admission)=="table" and packet.admission.reason or "server rejected operation")
            return nil,self.reason
        end
        if hello and (packet.admission.state~="admitted" or not options.metadata_matches(packet.admission,self.report)
            or not token(packet.admission_epoch) or not token(packet.session_id)) then
            return nil,"admission response metadata mismatch"
        end
        if type(packet.commands)~="table" or #packet.commands>128 then return nil,"invalid command batch" end
        local previous_command=0
        for index,command in ipairs(packet.commands) do
            if type(command)~="table" or command.command_index~=index then return nil,"invalid command index" end
            for _,key in ipairs({"protocol","player","admission_epoch","session_id","seq","operation_id"}) do
                if command[key]~=packet[key] then return nil,"command envelope differs from response" end
            end
            if options.durable_ids then
                if not token(command.command_id) or type(command.command_sequence)~="number"
                    or command.command_sequence%1~=0 or command.command_sequence<=previous_command then
                    return nil,"invalid durable command identity/order"
                end
                previous_command=command.command_sequence
            end
        end
        if hello then
            self.epoch=packet.admission_epoch; self.session_id=packet.session_id; self.state="admitted"
        else
            self.pending[packet.seq]=nil; self.pending_count=self.pending_count-1
            self.last_response=packet.seq
        end
        return packet.commands
    end
    return self
end
return M
