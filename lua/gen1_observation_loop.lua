-- Free-running Gen 1 observation loop: observe free, hold to write
-- (docs/gen1_reference/EXECUTION_MODEL_PROPOSAL.md sections 3-5). One tick per
-- emulated frame: peek the read-only sources, publish ONE "observation" event when
-- a signal or receipt exists or the heartbeat is due, and only then drain the
-- sources: persist-before-drain, the invariant the retired frame-credit client kept.
-- A capture call that opened without returning yet persists the cursor alone
-- (ctx.persist) before its witness is acknowledged. No RAM address, no write and
-- no hold live here; writes are ctx.writer:service(), which takes its own hold.
--
-- Boundary predicate. gen1_engine_signals.lua (:74 peek, :78 drain, :82 batch),
-- gen1_acquisition_observers.lua (:37 check, reached by every method) and, through
-- its common table (:17), all six gen1_*_observer.lua peek/acknowledge pairs assert
-- options.held()==true, which a free-running core never satisfies. This loop sets
-- ctx.at_boundary=true for the whole of tick()/observe() and around observers:initial.
-- The relaxation is therefore one line at each construction site, not in the sources:
-- gen1_initial_observation.lua:52 and gen1_client_entry.lua:130 pass
-- held=function()return ctx.at_boundary==true end, so "held" reads "between frames,
-- inside the loop". The hooks fire inside emulation and never check it. The owned()
-- given to both modules must not assert the hold either (gen1_client_entry.lua:109-113
-- does; source_owned at :103-108 does not).
local JSON=require("json_codec")
local M={SCHEMA="rby-observation-v1",MAX_SIGNALS=32,MAX_RECEIPTS=16,HEARTBEAT=30}
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
local function integer(n)return type(n)=="number" and n%1==0 and n>=0 and n<=9007199254740991 end
local function witnessed(rows) -- every raw witness ends as a receipt or a cursor change
    return #rows.capture+#rows.grants+#rows.static+#rows.npc_exchange+#rows.wild+#rows.evolution>0
end
function M.new(ctx)
    assert(type(ctx)=="table" and ctx.engine and ctx.journal and ctx.session and ctx.baseline
        and type(ctx.owned)=="function" and type(ctx.rom_hash)=="function","observation loop dependencies required")
    local period=ctx.heartbeat or M.HEARTBEAT
    assert(integer(period) and period>=1,"heartbeat period in frames required")
    local frame_of=ctx.frame or function()return emu.framecount()end
    local persist=ctx.persist or function(baseline)return ctx.journal:append_many(JSON.array(),baseline)end
    local function baseline()return type(ctx.baseline)=="function" and ctx.baseline() or ctx.baseline end
    local function guarded(fn,self)
        local outer=ctx.at_boundary;ctx.at_boundary=true
        local ok,result=pcall(fn,self)
        ctx.at_boundary=outer or false
        if not ok then error(result,0)end
        return result
    end
    local self={}
    -- Acquisition cursor: persisted with every publication, advanced in memory between them.
    if ctx.observers then
        self.source=guarded(function()return baseline().acquisition_source or ctx.observers:initial(frame_of())end)
    end
    local function observe(self)
        local frame=frame_of()
        local signals=ctx.engine:peek()
        local rows=ctx.observers and ctx.observers:prepare(self.source) or nil
        assert(#signals<=M.MAX_SIGNALS,"frame signal batch exceeds source bounds")
        assert(not rows or #rows.receipts<=M.MAX_RECEIPTS,"frame acquisition batch exceeds source bounds")
        local heartbeat=frame%period==0
        local publish=#signals>0 or heartbeat or rows~=nil and #rows.receipts>0
        local event
        if publish or rows and witnessed(rows) then
            local current=baseline()
            if rows then current.acquisition_source=copy(rows.state)end
            if publish then
                local seq=(current.observation_sequence or 0)+1
                assert(integer(seq) and seq>=1,"observation sequence exhausted")
                local batch=JSON.null
                if #signals>0 then -- engine batches keep their own contiguous counter (server rule)
                    local previous=current.engine_signals
                    local signal_seq=(previous and previous.sequence or 0)+1
                    batch=ctx.engine:batch(signals,signal_seq)
                    current.engine_signals={context=copy(ctx.owned()),sequence=signal_seq}
                end
                event={schema=M.SCHEMA,event="observation",frame=frame,sequence=seq,context=copy(ctx.owned()),
                    rom=ctx.rom_hash(),signals=batch,acquisitions=rows and copy(rows.receipts) or JSON.array(),
                    inventory=heartbeat and ctx.inventory and ctx.inventory() or JSON.null}
                current.observation_sequence=seq
                assert(ctx.journal:append(event,current)) -- durable before any source forgets
            else
                assert(persist(current))
            end
            if #signals>0 then assert(ctx.engine:drain(signals))end
            if rows then assert(ctx.observers:drain(rows))end
        end
        if rows then self.source=rows.state end
        return event
    end
    local function service(self)
        local event=observe(self)
        if ctx.writer and ctx.writer:pending() then ctx.writer:service()end
        ctx.session:pump()
        if ctx.observers then assert(ctx.observers:ready(self.source))end
        return event
    end
    function self:observe()return guarded(observe,self)end -- for a writer that steps frames itself
    function self:tick()return guarded(service,self)end
    function self:run()while true do emu.frameadvance();self:tick()end end
    return self
end
return M
