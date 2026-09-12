-- Durable Gen 1 HUD notices: the no-write command service behind command_service_router.
-- A hud_notice at the FIFO head persists its intent, is drawn by one actual gui call (or
-- expires against the server TTL on the client wall clock) and settles with the exact
-- slink-gen1-hud-receipt-v1 the server verifies (server/gen1_hud_feedback.py). It needs
-- no memory module, RAM write, write permit, physical hold, native patch or sound, so it
-- may settle while lifecycle-held and can never block service continuity.
-- Drawn-once is remembered in this VM only: a crash after the draw and before the local
-- receipt may redraw the same notice once on restart, bounded by the notice TTL.
local JSON=require("json_codec")
local Canonical=require("journal_document")
local M={COMMAND_SCHEMA="slink-gen1-hud-notice-v1",RECEIPT_SCHEMA="slink-gen1-hud-receipt-v1",
    STATE_SCHEMA="slink-gen1-hud-state-v1",STATE_RECEIPT="slink-gen1-hud-state-receipt-v1",
    INTENT_SCHEMA="rby-hud-notice-intent-v1",STATE_INTENT="rby-hud-state-intent-v1",STATUS_SCHEMA="rby-hud-service-status-v1",
    MAX_TEXT=30,MAX_FRAMES=600,MAX_TTL_SECONDS=120,MAX_INT=9007199254740991}
local KINDS={link_pending=true,link_formed=true,violation=true,clause_retry=true}
local SURFACES={hud=true,prompt=true}
local FIELDS={cmd=true,schema=true,kind=true,surface=true,text=true,r=true,g=true,b=true,
    frames=true,issued_at=true,expires_at=true}
local STATE_FIELDS={cmd=true,schema=true,mode=true,text=true}
local MODES={game_over=true}
local function integer(value,low,high)
    return type(value)=="number" and value%1==0 and value>=low and value<=high
end
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end

function M.handles(body)return type(body)=="table" and (body.cmd=="hud_notice" or body.cmd=="hud_state") end

-- Mirrors server validate_body exactly: same field set, kinds, surfaces and bounds.
function M.validate(body)
    if type(body)=="table" and body.cmd=="hud_state" then
        assert(body.schema==M.STATE_SCHEMA and MODES[body.mode],"complete versioned Gen 1 HUD state required")
        for key in pairs(body)do assert(STATE_FIELDS[key],"unknown Gen 1 HUD state field: "..tostring(key))end
        for key in pairs(STATE_FIELDS)do assert(body[key]~=nil,"missing Gen 1 HUD state field: "..key)end
        assert(body.text=="","terminal Gen 1 HUD state has no text parameter")
        return body
    end
    assert(type(body)=="table" and body.cmd=="hud_notice" and body.schema==M.COMMAND_SCHEMA,
        "complete versioned Gen 1 HUD notice required")
    for key in pairs(body)do assert(FIELDS[key],"unknown Gen 1 HUD notice field: "..tostring(key))end
    for key in pairs(FIELDS)do assert(body[key]~=nil,"missing Gen 1 HUD notice field: "..key)end
    assert(KINDS[body.kind] and SURFACES[body.surface],"unsupported Gen 1 HUD notice kind or surface")
    assert(type(body.text)=="string" and #body.text>=1 and #body.text<=M.MAX_TEXT and not body.text:find("[^ -~]"),
        "Gen 1 HUD text must be 1..30 printable ASCII characters")
    for _,channel in ipairs({"r","g","b"})do assert(integer(body[channel],0,255),"invalid Gen 1 HUD "..channel.." channel")end
    assert(integer(body.frames,1,M.MAX_FRAMES),"invalid Gen 1 HUD frame duration")
    assert(integer(body.issued_at,0,M.MAX_INT) and integer(body.expires_at,0,M.MAX_INT)
        and body.issued_at<=body.expires_at and body.expires_at<=body.issued_at+M.MAX_TTL_SECONDS,
        "Gen 1 HUD expiry must be within 120 seconds of issue")
    return body
end

function M.new(options)
    assert(type(options)=="table" and type(options.journal)=="table" and type(options.overlay)=="table"
        and type(options.overlay.present)=="function" and type(options.overlay.apply_state)=="function",
        "client journal and HUD overlay required")
    local journal,overlay,player=options.journal,options.overlay,options.player
    local frame=options.frame or function()return emu.framecount()end
    local wall=options.wall or os.time
    local unwrap=options.unwrap or function(body)return require("gen1_runtime").unwrap(body,player)end
    local self={drawn={},counts={drawn=0,expired=0}}
    local persisted,read_error=journal:hud_state()
    assert(read_error==nil,read_error)
    if persisted then assert(overlay.apply_state(persisted.mode,persisted.text)==true,
        "persisted HUD state could not be restored visibly")end
    local function sha(value)return journal.store.backend.sha256(assert(Canonical.encode(value)))end
    local function head()
        local entry=assert(journal:pending_commands())[1]
        if not entry then return nil end
        entry=copy(entry);entry.body=unwrap(entry.body)
        return entry
    end
    local function matches(body)
        local entry=head()
        -- json_codec sorts keys, so equality is exact; canonical encoding is reserved for
        -- digests of validated bodies (it refuses non-integer numbers).
        if not entry or not M.handles(entry.body) or assert(JSON.encode(entry.body))~=assert(JSON.encode(body)) then
            return false,"waiting for the owned HUD notice at the command head"
        end
        return true,entry
    end
    local function owned(body,identity)
        M.validate(body)
        local ok,entry=matches(body)
        assert(ok,"owned Gen 1 HUD notice at the command head required")
        assert(entry.command_id==identity.command_id and entry.command_sequence==identity.command_sequence,
            "HUD notice identity differs from the command head")
        return entry
    end
    local function bound(body,intent,identity)
        owned(body,identity)
        assert(type(intent)=="table" and intent.schema==(body.cmd=="hud_state" and M.STATE_INTENT or M.INTENT_SCHEMA)
            and intent.command_id==identity.command_id
            and intent.body_digest==sha(body),"exact persisted HUD notice intent required")
    end
    local function expired(body)
        local now=wall()
        assert(integer(now,0,M.MAX_INT),"Gen 1 HUD wall clock failed")
        return now>body.expires_at
    end
    local function forget_settled()
        -- ponytail: one small record per drawn notice; drop the ones the journal no longer holds.
        for command_id in pairs(self.drawn)do
            if journal:get_command(command_id)==nil then self.drawn[command_id]=nil end
        end
    end
    self.handles=M.handles
    self.adapter={}
    function self.adapter.prepare(body,identity)
        owned(body,identity)
        if body.cmd=="hud_state" then
            return {schema=M.STATE_INTENT,command_id=identity.command_id,body_digest=sha(body),
                mode=body.mode,text=body.text}
        end
        return {schema=M.INTENT_SCHEMA,command_id=identity.command_id,body_digest=sha(body),
            surface=body.surface,frames=body.frames}
    end
    function self.adapter.classify(body,intent,identity)
        bound(body,intent,identity)
        if body.cmd=="hud_state"then
            local state,why=journal:hud_state()
            assert(why==nil,why)
            if state and state.command_id==identity.command_id then
                assert(state.body_digest==intent.body_digest and state.command_sequence==identity.command_sequence
                    and state.mode==body.mode and state.text==body.text,"persisted HUD state differs from command")
                return "after",{disposition="applied",frame=state.frame}
            end
            if state then
                assert(state.command_sequence<identity.command_sequence and state.body_digest==intent.body_digest
                    and state.mode=="game_over" and body.mode=="game_over",
                    "terminal HUD state replay differs from the persisted run state")
                -- The previous command's ACK may be retired. An accidental re-issue is
                -- a harmless no-write replay, not another overlay draw every reconnect.
                return "after",{disposition="applied",frame=state.frame}
            end
            return "before"
        end
        local drawn=self.drawn[identity.command_id]
        if drawn then return "after",{disposition="drawn",frame=drawn.frame}end
        if expired(body)then return "after",{disposition="expired",frame=-1}end
        return "before"
    end
    function self.adapter.apply(body,intent,identity)
        bound(body,intent,identity)
        if body.cmd=="hud_state"then
            local at=frame()
            assert(integer(at,0,M.MAX_INT),"emulated frame counter required")
            assert(overlay.apply_state(body.mode,body.text)==true,"HUD state was not visibly applied")
            local saved,why=journal:record_hud_state(identity.command_id,
                {schema="slink-gen1-hud-client-state-v1",mode=body.mode,text=body.text,
                    command_id=identity.command_id,command_sequence=identity.command_sequence,
                    body_digest=intent.body_digest,frame=at})
            assert(saved,why or "HUD state was not persisted")
            self.counts.drawn=self.counts.drawn+1
            return
        end
        assert(self.drawn[identity.command_id]==nil,"HUD notice was already drawn")
        if expired(body)then return end -- readback settles it as expired; nothing was drawn
        local at=frame()
        assert(integer(at,0,M.MAX_INT),"emulated frame counter required")
        assert(overlay.present({surface=body.surface,text=body.text,r=body.r,g=body.g,b=body.b,frames=body.frames})==true,
            "HUD overlay did not draw the notice")
        forget_settled()
        self.drawn[identity.command_id]={frame=at}
        self.counts.drawn=self.counts.drawn+1
    end
    function self.adapter.receipt(body,intent,observation,identity)
        bound(body,intent,identity)
        if body.cmd=="hud_state"then
            assert(type(observation)=="table" and observation.disposition=="applied"
                and integer(observation.frame,0,M.MAX_INT),"persisted HUD state disposition required")
            return {schema=M.STATE_RECEIPT,command_id=identity.command_id,command_sequence=identity.command_sequence,
                body_digest=intent.body_digest,disposition="applied",frame=observation.frame}
        end
        assert(type(observation)=="table" and (observation.disposition=="drawn" and integer(observation.frame,0,M.MAX_INT)
            or observation.disposition=="expired" and observation.frame==-1),"exact HUD notice disposition required")
        if observation.disposition=="expired" then self.counts.expired=self.counts.expired+1 end
        return {schema=M.RECEIPT_SCHEMA,command_id=identity.command_id,command_sequence=identity.command_sequence,
            body_digest=intent.body_digest,disposition=observation.disposition,frame=observation.frame}
    end
    -- No hold, permit, memory or sound is involved, so a notice is ready whenever it is the
    -- owned head: it settles while lifecycle-held and under a free-running core alike.
    local function owned_head(body)
        local ok,why=matches(body)
        if not ok then return false,why end
        return true
    end
    self.ready=owned_head
    self.operations={
        request=function()return nil end, -- never asks for a permit window
        accept=function(packet)assert(packet==nil,"HUD notices take no operation grant");return true end,
        authorize_apply=owned_head,
        revoke=function()end,
        status=function()return self.status()end}
    function self.status()
        local pending=0
        for _,entry in ipairs(assert(journal:pending_commands()))do
            local ok,body=pcall(unwrap,entry.body)
            if ok and M.handles(body)then pending=pending+1 end
        end
        local retained=type(overlay.retained)=="function" and overlay.retained() or {hud=0,prompt=0}
        return {schema=M.STATUS_SCHEMA,pending=pending,retained=retained.hud+retained.prompt,
            drawn=self.counts.drawn,expired=self.counts.expired}
    end
    return self
end
return M
