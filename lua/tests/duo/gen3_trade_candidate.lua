-- T5 only. This module is never imported by a production bootstrap.
-- The runner owns the nonce/environment and the private admission projection.
-- No native witness, party byte, or save byte is written by this carrier.
local M = {}
M.ENV = "SLINK_DUO_FR_TRADE_CANDIDATE"
M.DISCLOSURE = "native NPC/party-chooser/offer carrier: UNTESTED (HARNESS_ONLY selection)"
local cases = {native_trade_firered=true, native_trade_decline_firered=true}
local sources = {
    "tools/gen3_trade_duo.py", "tools/e2e_duo.py",
    "lua/gen3/run.lua", "lua/gen3/entry.lua", "lua/gen3/signals.lua",
    "lua/gen3/native.lua", "lua/gen3/safety.lua", "lua/gen3/trade.lua", "lua/gen3/rom_content.lua",
    "lua/tests/duo/gen3_trade_candidate.lua", "lua/tests/duo/duo_gen3_main.lua",
    "lua/tests/duo/scenario_gen3_native_trade.lua",
    "data/games/gen3_frlg/profile.json", "data/games/gen3_frlg/engine_signals.json",
    "data/games/gen3_frlg/write_checkpoint.json", "patch/src/trade_targets/abi.h",
}
local function relative(path)
    return type(path) == "string" and path:match("^patch/build/[%w_/%-.]+$") and not path:find("..",1,true)
end
function M.authorize(manifest, d, env, hash, read, digest)
    assert(d.game == "gen3_fr_trade" and d.title == "firered" and cases[d.scenario], "not a T5 duo row")
    assert(manifest.schema == "slink-fr-trade-duo-v2", "stale T5 manifest: regenerate private packs")
    assert(manifest.production == false and manifest.ready == 0, "not a private READY0 candidate manifest")
    assert(type(manifest.nonce) == "string" and #manifest.nonce == 32
           and manifest.nonce:match("^%x+$") and env == manifest.nonce, "T5 runner override absent or mismatched")
    hash = tostring(hash or ""):lower()
    assert(hash == manifest.rom_sha1 or hash == manifest.rom_md5, "T5 cartridge differs from candidate manifest")
    for _, name in ipairs({"profile","sites","checkpoint"}) do
        assert(relative(manifest.pack_files[name]), "T5 private pack escaped patch/build")
        assert(read and digest and manifest.pack_sha1 and
               digest(read(manifest.pack_files[name])) == manifest.pack_sha1[name], "stale T5 private pack digest: " .. name)
    end
    local seen = 0
    for _ in pairs(manifest.source_sha1 or {}) do seen = seen + 1 end
    assert(seen == #sources,"stale T5 manifest: missing source digests")
    for _, path in ipairs(sources) do
        assert(digest(read(path)) == manifest.source_sha1[path], "stale T5 source digest: " .. path)
    end
    return true
end
function M.new(d, json, manifest, log, manifest_raw)
    local digest = assert(dofile(d.wt .. "/lua/gen3/rom_content.lua").sha1,"raw byte digest unavailable")
    assert(type(manifest_raw)=="string" and digest(manifest_raw)==d.native_manifest_sha1,"stale T5 manifest digest")
    local function read(path)
        local file = assert(io.open(d.wt .. "/" .. path,"rb"),"T5 bound file unavailable: " .. path)
        local bytes=file:read("a");file:close();return bytes
    end
    M.authorize(manifest,d,os.getenv(M.ENV),gameinfo.getromhash(),read,digest)
    local self = {manifest=manifest, ready=false, finals={}, save_entries=0}
    local base = manifest.native.BASE
    local prefix = "patch/build/t5_" .. manifest.nonce .. "_" .. d.player .. "_" .. (d.phase or "initial")
    local ordinal, io_, session, parts, g = 0, nil, nil, nil, nil
    local function emit(kind, fields)
        fields = fields or {}
        fields.kind, fields.side, fields.phase, fields.frame = kind,d.player,d.phase or "initial",emu.framecount()
        log("T5 " .. json.encode(fields))
    end
    local function raw(address,n,domain)
        local out = {}
        for i=0,n-1 do out[#out+1] = string.char(memory.read_u8(address+i,domain or "System Bus")) end
        return table.concat(out)
    end
    local function dump(label, data)
        ordinal = ordinal + 1
        local path = prefix .. "_" .. label .. "_" .. ordinal .. ".bin"
        local f = assert(io.open(d.wt .. "/" .. path,"wb"), "T5 evidence file unavailable")
        assert(f:write(data)); assert(f:close())
        return path
    end
    local function counter() return g and g.save_counter(assert(g.flash_domain())) or -1 end
    local function disk(path)
        local file = io.open(path,"rb")
        if not file then return nil end
        local data = file:read("a");file:close();return data
    end
    local function journal_snapshot()
        local until_ = os.clock()+1
        repeat
            local guard1 = disk(d.wt.."/slink_gen3_trade.guard")
            local body = disk(d.wt.."/slink_gen3_trade.log")
            local guard2 = disk(d.wt.."/slink_gen3_trade.guard")
            if guard1 and body and guard1 == guard2 then
                local hash = 2166136261
                for i=1,#body do hash=((hash ~ body:byte(i))*16777619)&0xFFFFFFFF end
                if guard1 == string.format("SLINK-TRADE-JOURNAL-1\n%d:%08x\n",#body,hash) then
                    emit("journal_intent",{path=dump("journal",body),guard=dump("guard",guard1)})
                    return
                end
            end
        until os.clock() >= until_
        error("T5 could not capture a coherent persisted write-ahead journal")
    end
    function self.snapshot(kind, extra)
        local before = memory.read_u16_le(base+0x68,"System Bus")
        local data = raw(base,0xA0)
        assert(memory.read_u16_le(base+0x68,"System Bus") == before, "T5 torn native snapshot")
        local fields = extra or {}
        fields.path, fields.counter = dump(kind,data),counter()
        emit(kind,fields)
    end
    function self.bind_entry(entry)
        -- Only this validated harness module selects these private files. The
        -- ordinary Entry ignores both the nonce env and the files. Their
        -- production:true row is an explicit test projection of a false receipt.
        entry.PACK_FILES.gen3_frlg = manifest.pack_files
        return entry
    end
    function self.before_build(deps)
        io_ = deps.io
        local write = io_.write_u8
        io_.write_u8 = function(address,value,...)
            local result = write(address,value,...)
            if address == base+7 then
                local op = io_.read_u16(base+6)
                if op == 29 then self.snapshot("prepare")
                elseif op == 21 then self.snapshot("scene");journal_snapshot()
                elseif op == 30 then self.snapshot("withdraw") end
            end
            return result
        end
        local flush = io_.saveram
        io_.saveram = function(...)
            emit("flash",{path=dump("flash",raw(0,0x20000,assert(g.flash_domain()))),counter=counter()})
            local result = flush(...)
            assert(result ~= false,"T5 host flush returned false")
            self.snapshot("flush_native")
            local file = assert(io.open(d.native_battery,"rb"), "T5 no battery file at host-flush return")
            local disk = file:read("a");file:close()
            emit("flush",{path=dump("flushed",disk),counter=counter(),status="returned"})
            return result
        end
    end
    function self.attach(the_session,the_parts)
        session,parts = the_session,the_parts
    end
    function self.tx(message)
        if message.event == "hello" then
            self.advertised = message.trade_prepare == true
            emit("hello",{trade_prepare=message.trade_prepare == true,rom_sha1=message.rom_sha1})
        elseif message.event == "apply_ready" or message.event == "trade_done" or message.event == "menu_result"
            or message.event == "mon_chosen" or message.event == "trade_request" then
            emit("tx",{message=message,counter=counter()})
        end
    end
    function self.command(cmd, handle)
        emit("rx",{message=cmd})
        if cmd.cmd == "show_choices" then
            assert(d.player == "a" and self.selection and type(cmd.token)=="string","T5 unexpected action menu")
            session.send("menu_result",{token=cmd.token,choice=0})
            return true
        elseif cmd.cmd == "choose_mon" then
            assert(d.player == "a" and self.selection and type(cmd.token)=="string","T5 unexpected chooser")
            session.send("mon_chosen",{token=cmd.token,slot=1})
            return true
        elseif cmd.cmd == "show_menu" then
            assert(d.player == "b" and self.selection and type(cmd.token)=="string","T5 unexpected offer")
            session.send("menu_result",{token=cmd.token,choice=d.native_decline and 0 or 1})
            return true
        elseif cmd.cmd == "msgbox" or cmd.cmd == "link_panel" then
            emit("omitted_ui",{command=cmd.cmd,text=cmd.text})
            if cmd.cmd == "msgbox" and type(cmd.text)=="string" and cmd.text:find("declined",1,true) then
                self.declined = true
            end
            return true
        end
        local result = handle(cmd)
        if cmd.cmd == "trade_final" then self.finals[cmd.token] = cmd.verdict end
        if cmd.cmd == "config" and self.advertised and parts.native:trade_capable() then
            self.ready = true
            emit("ready",{production=false})
        end
        return result
    end
    function self.start_selection()
        self.selection = true
        if d.player == "a" then session.send("trade_request",{}) end
    end
    function self.start(ctx)
        g = ctx.G
        local function hook(symbol, fn)
            local address = assert(manifest.hooks[symbol],"T5 missing engine hook "..symbol)
            assert(event.on_bus_exec(fn,address,"T5-"..symbol),"T5 engine hook failed "..symbol)
            emit("hook",{symbol=symbol,address=address})
        end
        hook("TradeMons_body",function() self.snapshot("commit") end)
        hook("DoInGameTradeScene",function() self.snapshot("scene_enter") end)
        hook("TradeEvolutionScene",function() self.snapshot("evolution") end)
        hook("TrySavingData",function()
            self.save_entries = self.save_entries + 1
            self.snapshot("save_entry",{ordinal=self.save_entries})
        end)
        self.capture_party("boot_party",ctx)
        emit("boot",{counter=counter(),production=false,rom_sha1=manifest.rom_sha1})
    end
    function self.capture_party(kind,ctx)
        local count = memory.read_u8(ctx.reader.PARTY_COUNT_ADDR or manifest.party_count,"System Bus")
        assert(count > 0 and count <= 6,"T5 unreadable party count")
        emit(kind,{path=dump(kind,raw(assert(ctx.reader.party_base()),count*100)),count=count,counter=counter()})
    end
    function self.flush_decline() return io_.saveram() end
    function self.capture_final(ctx)
        self.snapshot("final")
        self.capture_party("before_reload",ctx)
        emit("ready_for_reload",{counter=counter()})
    end
    function self.reloaded(ctx)
        self.capture_party("reloaded",ctx)
        emit("reload",{counter=counter(),production=false})
    end
    function self.final_seen()
        local journal = io_ and io_.trade_journal
        for token,verdict in pairs(self.finals) do
            if verdict=="committed" and journal and journal:ready() and not journal:hidden() and not journal:has_entries() then
                if not self.journal_recorded then
                    self.journal_recorded = true
                    emit("journal",{token=token,ready=true,hidden=false,empty=true})
                end
                return true
            end
        end
        return false
    end
    emit("override",{environment=M.ENV,value=manifest.nonce,production=false,ready=0,rom_sha1=manifest.rom_sha1,
        source_commit=manifest.source_commit,manifest_sha1=d.native_manifest_sha1,
        run_lua_sha1=manifest.source_sha1["lua/gen3/run.lua"],sites_sha1=manifest.pack_sha1.sites})
    log("HARNESS_ONLY " .. M.DISCLOSURE)
    return self
end
return M
