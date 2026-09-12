-- Harness-only timing. Delegates every original call/return; no game or protocol
-- state is changed. Persist only at the terminal gate boundary to avoid adding
-- file writes to the response path being measured.
local M={}
function M.install(root,JSON)
    local trace={schema='rby-cold-timing-v1',wire=JSON.array(),costs={},slow_steps=JSON.array(),truncated=false}
    local function append(rows,row)
        if #rows<20000 then rows[#rows+1]=row else trace.truncated=true end
    end
    local function cost(label,seconds)
        local row=trace.costs[label]or {calls=0,seconds=0,maximum=0}
        row.calls=row.calls+1;row.seconds=row.seconds+seconds;row.maximum=math.max(row.maximum,seconds)
        trace.costs[label]=row
    end
    local function timed(label,fn,clock)
        return function(...)
            local began=clock();local result=table.pack(fn(...));cost(label,clock()-began)
            return table.unpack(result,1,result.n)
        end
    end
    package.preload.gen1_runtime=function()
        local runtime=assert(loadfile(root..'/lua/gen1_runtime.lua'))()
        local original=runtime.new
        runtime.new=function(options)
            local codec=require('json_codec');local clock=options.clock;local transport=options.transport
            options.read_context=timed('read_context',options.read_context,clock)
            local send,receive=transport.send,transport.receive
            transport.send=function(raw)
                local began=clock();local packet=assert(codec.decode(raw));local request=packet.operation_execution
                local scope=request and request.window and request.window.scope
                append(trace.wire,{direction='send',at=began,event=packet.event,operation=packet.operation_id,
                    seq=packet.seq,bytes=#raw,grant_operation=scope and scope.operation_id,phase=scope and scope.phase})
                cost('send_instrumentation',clock()-began)
                return send(raw)
            end
            transport.receive=function(...)
                local result=table.pack(receive(...))
                if result[1]then
                    local began=clock();local packet=assert(codec.decode(result[1]))
                    append(trace.wire,{direction='receive',at=began,event=packet.event,operation=packet.operation_id,
                        seq=packet.seq,bytes=#result[1]})
                    cost('receive_instrumentation',clock()-began)
                end
                return table.unpack(result,1,result.n)
            end
            transport.pump=timed('transport_pump',transport.pump,clock)
            local service=original(options)
            service.step=timed('runtime_step',service.step,clock)
            return service
        end
        return runtime
    end
    package.preload.gen1_client_entry=function()
        local entry=assert(loadfile(root..'/lua/gen1_client_entry.lua'))()
        local original=entry.start
        entry.start=function(...)
            local owner=original(...);local step=owner.step;local installed=false
            owner.step=function(self,...)
                local before=emu.framecount();local began=self.clock and self.clock()
                local result=table.pack(step(self,...))
                if began then
                    local seconds=self.clock()-began;cost('entry_step',seconds)
                    if seconds>=0.1 then append(trace.slow_steps,{before=before,after=emu.framecount(),at=began,seconds=seconds})end
                end
                if self.clock and not installed then
                    installed=true
                    self.status=timed('entry_status',self.status,self.clock)
                    self.host.yield_held=timed('held_yield_with_harness',self.host.yield_held,self.clock)
                end
                return table.unpack(result,1,result.n)
            end
            return owner
        end
        return entry
    end
    return {report=function()return trace end}
end
return M
