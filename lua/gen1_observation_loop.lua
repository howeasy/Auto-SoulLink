-- Free-running Gen 1 observation loop: observe free, hold to write
-- (docs/gen1_reference/EXECUTION_MODEL_PROPOSAL.md sections 3-5). One tick per
-- emulated frame: peek the read-only sources, publish ONE "observation" event when
-- a signal or receipt exists or the heartbeat is due, and only then drain the
-- sources: persist-before-drain, the invariant the retired frame-credit client kept.
-- A capture call that opened without returning yet persists the cursor alone
-- (ctx.persist) before its witness is acknowledged. No RAM address, no write and
-- no hold live here; writes are ctx.writer:service(), which takes its own hold.
-- Polled battle state comes from ctx.engine:probe() (wIsInBattle, wCurOpponent): every
-- event carries the battle byte, and a TRAINER battle start (opponent = class + 200 while
-- wIsInBattle == 2, stable for TRAINER_STABLE_TICKS ticks, once per battle: the debounce
-- the legacy client used, gen1_rby_client.lua TRAINER_STABLE_GATE) publishes at once.
-- ctx.instruction (optional, {finish, arm}) is the in-battle instruction window of
-- gen1_client_entry.lua: finish() settles the frame that just ran before anything else in
-- the tick, arm() is the last thing before the next frame, so an armed executor never
-- overlaps a writer hold and its rows ride the command receipt, not this event.
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
local M={SCHEMA="rby-observation-v1",MAX_SIGNALS=32,MAX_RECEIPTS=16,HEARTBEAT=30,TRAINER_OFFSET=200,TRAINER_STABLE_TICKS=3}
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
local function integer(n)return type(n)=="number" and n%1==0 and n>=0 and n<=9007199254740991 end
local function witnessed(rows) -- every raw witness ends as a receipt or a cursor change
    return #rows.capture+#rows.grants+#rows.static+#rows.npc_exchange+#rows.wild+#rows.evolution>0
end
function M.new(ctx)
    assert(type(ctx)=="table" and ctx.engine and type(ctx.engine.probe)=="function" and ctx.journal and ctx.session and ctx.baseline
        and type(ctx.owned)=="function" and type(ctx.rom_hash)=="function","observation loop dependencies required")
    assert(ctx.verify==nil or type(ctx.verify)=="function","observation boundary verifier must be callable")
    assert(ctx.pending_inventory_retry==nil or type(ctx.pending_inventory_retry)=="function",
        "durable inventory retry reader must be callable")
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
    local self={trainer={id=nil,ticks=0,published=false},diagnostics={ticks=0,observer_quiet=0,
        observer_active=0,publications=0,inventory_checks=0,inventory_publications=0,
        signal_publications=0,acquisition_publications=0}}
    if ctx.checkpoint then
        local _,fingerprint=ctx.checkpoint(false)
        assert(fingerprint,"initial inventory fingerprint required")
        self.fingerprint=fingerprint
    end
    local function trainer(probe,frame) -- one trainer_battle_start row per stable trainer engagement
        local id=probe.battle==2 and probe.opponent>=M.TRAINER_OFFSET and probe.opponent or nil
        local t=self.trainer
        if id~=t.id then t={id=id,ticks=0,published=false};self.trainer=t end
        if id==nil then return JSON.null end
        t.ticks=t.ticks+1
        if t.published or t.ticks<M.TRAINER_STABLE_TICKS then return JSON.null end
        t.published=true
        return {trainer_id=id,frame=frame}
    end
    -- Acquisition cursor: persisted with every publication, advanced in memory between them.
    if ctx.observers then
        self.source=guarded(function()return baseline().acquisition_source or ctx.observers:initial(frame_of())end)
    end
    local function observe(self)
        local frame=frame_of()
        local signals=ctx.engine:peek()
        local rows=ctx.observers and ctx.observers:prepare(self.source) or nil
        if ctx.observers then
            local key=rows and"observer_active"or"observer_quiet"
            self.diagnostics[key]=self.diagnostics[key]+1
        end
        assert(#signals<=M.MAX_SIGNALS,"frame signal batch exceeds source bounds")
        assert(not rows or #rows.receipts<=M.MAX_RECEIPTS,"frame acquisition batch exceeds source bounds")
        local probe=ctx.engine:probe()
        assert(integer(probe.battle) and probe.battle<=255 and integer(probe.opponent) and probe.opponent<=255,"engine probe bytes required")
        local engaged=trainer(probe,frame)
        local heartbeat=frame%period==0
        local inventory=JSON.null
        if heartbeat and ctx.checkpoint then
            self.diagnostics.inventory_checks=self.diagnostics.inventory_checks+1
            local retry=ctx.pending_inventory_retry and ctx.pending_inventory_retry() or nil
            local point,fingerprint=ctx.checkpoint(self.fingerprint,retry~=nil)
            if fingerprint then self.fingerprint=fingerprint end
            if point then inventory=point end
        elseif heartbeat and ctx.inventory then
            inventory=ctx.inventory()or JSON.null
        end
        local publish=#signals>0 or inventory~=JSON.null or (heartbeat and (not ctx.checkpoint or probe.battle~=0))
            or engaged~=JSON.null or rows~=nil and #rows.receipts>0
        local event
        if publish or rows and witnessed(rows) then
            if ctx.verify then assert(ctx.verify())end
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
                    inventory=inventory,
                    battle=probe.battle,trainer=engaged}
                self.diagnostics.publications=self.diagnostics.publications+1
                if inventory~=JSON.null then self.diagnostics.inventory_publications=self.diagnostics.inventory_publications+1 end
                if #signals>0 then self.diagnostics.signal_publications=self.diagnostics.signal_publications+1 end
                if rows and #rows.receipts>0 then self.diagnostics.acquisition_publications=self.diagnostics.acquisition_publications+1 end
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
        self.diagnostics.ticks=self.diagnostics.ticks+1
        if ctx.instruction then ctx.instruction:finish()end -- the frame that just ran, before anything can hold or yield
        local event=observe(self)
        if ctx.writer and ctx.writer:pending() then ctx.writer:service()end
        ctx.session:pump()
        if ctx.observers then assert(ctx.observers:ready(self.source))end
        if ctx.instruction then ctx.instruction:arm()end -- for the frame about to run; nothing else follows in this tick
        return event
    end
    function self:observe()return guarded(observe,self)end -- for a writer that steps frames itself
    function self:tick()return guarded(service,self)end
    function self:status()return copy(self.diagnostics)end
    function self:continuity()
        local ok,result=pcall(function()return guarded(function()
            local current=baseline();local source=assert(self.source,"persisted acquisition cursor required")
            local cursor=current.observation_cursor
            if cursor then
                assert(type(cursor)=="table"and cursor.sequence==current.observation_sequence,
                    "last observation is not durably acknowledged")
            else
                assert(current.observation_sequence==nil or current.observation_sequence==0,
                    "last observation is not durably acknowledged")
                local initial=assert(current.initial_inventory,"initial observation cursor required")
                local payload=initial.payload and initial.payload.payload or nil
                assert(initial.phase=="acknowledged"and type(initial.operation_id)=="string"
                    and (payload and type(payload.frame)=="number"or initial.schema=="rby-initial-observation-cursor-v1"
                    and type(initial.frame)=="number"),"initial observation is not durably acknowledged")
                cursor={sequence=0,operation_id=initial.operation_id,frame=payload and payload.frame or initial.frame}
            end
            assert(source.capture_open==JSON.null and source.grant_open==0
                and (source.evolution_open or 0)==0 and source.native_handoff_operation_id==nil,
                "open acquisition cursor prohibits service continuity")
            if ctx.observers then
                assert(type(ctx.observers.idle)=="function","idle acquisition verifier required")
                assert(ctx.observers:idle(source))
            end
            local engine=ctx.engine:peek();assert(#engine==0,"engine hook buffer prohibits service continuity")
            local probe=ctx.engine:probe();assert(probe.battle==0,"battle state prohibits service continuity")
            local instruction=ctx.instruction and ctx.instruction:status()or {open=false,armed=false}
            assert(not instruction.open and not instruction.armed,"battle instruction prohibits service continuity")
            assert(not ctx.writer or not ctx.writer:pending(),"physical write obligation prohibits service continuity")
            return {cursor=copy(cursor),idle={acquisition_open=false,acquisition_pending=0,
                engine_pending=0,instruction_open=false,instruction_armed=false,battle=0,source_frame=source.frame}}
        end)end)
        if not ok then
            local why=tostring(result or "service continuity is not idle"):gsub("[%c]"," "):sub(1,240)
            return nil,why~=""and why or "service continuity is not idle"
        end
        return result
    end
    function self:run()while true do emu.frameadvance();self:tick()end end
    return self
end
return M
