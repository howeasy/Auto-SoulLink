-- Read-only gen4-PERF instrumentation. No game-data writes and no per-frame log IO.
-- Every trial uses one private copied state/config; f remains qualification authority.
local P={BUS="ARM9 System Bus"}
local function need(x,name) if x==nil then error({open=name},0) end; return x end
local function check(x,why) assert(x,why) end
function P.stats(times)
    check(#times>0,"empty timing sequence")
    local sorted,total,slow={},0,0
    for i,t in ipairs(times) do
        check(type(t)=="number" and t>0 and t<math.huge,"invalid wall-frame interval")
        sorted[i]=t; total=total+t; if t>1/60 then slow=slow+1 end
    end
    table.sort(sorted)
    return {frames=#times,p50=sorted[math.ceil(#times*.5)],p99=sorted[math.ceil(#times*.99)],
        max=sorted[#times],over_budget=slow,elapsed_seconds=total,fps=#times/total}
end
function P.clock()
    -- NLua may expose CLR types. Read-only Stopwatch is preferred, but availability
    -- is established at runtime; do not enable CLR packages or change host trust.
    if luanet and luanet.import_type then
        local ok,sw=pcall(luanet.import_type,"System.Diagnostics.Stopwatch")
        if ok and sw then
            local good,freq=pcall(function() return tonumber(sw.Frequency) end)
            if good and freq and freq>0 then
                local clock=function() return tonumber(sw.GetTimestamp())/freq end
                local valid=pcall(clock)
                if valid then return clock,{source="System.Diagnostics.Stopwatch.GetTimestamp/Frequency",frequency=freq,kind="monotonic_wall",monotonic_guaranteed=true} end
            end
        end
    end
    -- CLR is not imported into this Lua global environment on some NLua builds.
    -- The documented read-only config object can expose its loaded assemblies;
    -- inspect them for Stopwatch without loading packages or changing trust.
    local reflected,clock=pcall(function()
        local object=client.getconfig():GetType().BaseType
        local domain_type=object.Assembly:GetType("System.AppDomain")
        local domain=domain_type:GetProperty("CurrentDomain"):GetValue(nil,nil)
        local assemblies=domain:GetAssemblies()
        for i=0,assemblies.Length-1 do
            local sw=assemblies[i]:GetType("System.Diagnostics.Stopwatch")
            if sw then
                local frequency=tonumber(sw:GetField("Frequency"):GetValue(nil))
                local method=sw:GetMethod("GetTimestamp")
                return function() return tonumber(method:Invoke(nil,nil))/frequency end
            end
        end
    end)
    if reflected and clock then
        local ok=pcall(clock)
        if ok then return clock,{source="System.Diagnostics.Stopwatch via loaded-assembly reflection",kind="monotonic_wall",monotonic_guaranteed=true} end
    end
    local ok,s=pcall(require,"socket")
    if ok and s and s.socket and type(s.socket.gettime)=="function" then
        return s.socket.gettime,{source="LuaSocket.socket.gettime",kind="wall_utc",monotonic_guaranteed=false,
            reflection_failure=not reflected and tostring(clock) or "Stopwatch not found in loaded assemblies"}
    end
    error({open="high-resolution wall clock unavailable: Stopwatch / existing LuaSocket.gettime"},0)
end
function P.calibrate(clock)
    local previous=clock(); local minimum,backward=math.huge,0
    for _=1,20000 do
        local current=clock(); local dt=current-previous
        if dt<0 then backward=backward+1 elseif dt>0 then minimum=math.min(minimum,dt) end
        previous=current
    end
    check(backward==0,"clock moved backward")
    if minimum==math.huge or minimum>0.0001 then error({open="wall clock resolution not sufficient for 1/60-second deadlines"},0) end
    return {minimum_positive_increment=minimum,backward_steps=backward,reads=20001}
end
function P.sample(clock,advance,work,frames)
    local out,work_times={},{}
    local previous=clock()
    for i=1,frames do
        local begin=clock(); if work then work() end; local complete=clock()
        work_times[i]=complete-begin
        advance()
        local current=clock(); out[i]=current-previous; previous=current
    end
    return out,work_times
end
function P.workload(reads,pk4,safety,json,title,mem,phase)
    reads.pk4=pk4
    local counts={pointer_chain=0,battle_mons_hp=0,battle_attempts=0,party_diff=0,json_encode=0,save_data=0,safety=0}
    local prior,battle,last_hello=nil,nil,nil
    local gate=safety.new(title,mem,{reads=reads,encounter_active=function() return battle~=nil end})
    local function work()
        local sd,why=reads.save_data(mem,title)
        check(sd~=nil,"save_data: "..tostring(why)); counts.save_data=counts.save_data+1
        local party; party,why=reads.party(mem,title,sd)
        check(party~=nil,"party: "..tostring(why))
        local found; found,why=reads.battle(mem,title)
        counts.pointer_chain=counts.pointer_chain+1; counts.battle_attempts=counts.battle_attempts+1
        if phase=="battle" then check(found~=nil,"battle workload unavailable: "..tostring(why))
        else check(found==nil and (why=="no_app" or why=="not_battle"),"overworld workload not in overworld: "..tostring(why)) end
        battle=found
        if battle then
            check(#battle.mons>0,"battle HP sample empty")
            counts.battle_mons_hp=counts.battle_mons_hp+#battle.mons
        end
        local changes=0
        for i,m in ipairs(party) do
            local old=prior and prior[i]
            if not old or old.key~=m.key or old.hp~=m.hp or old.level~=m.level then changes=changes+1 end
            for j=1,4 do if not old or old.moves[j]~=m.moves[j] then changes=changes+1 end end
        end
        if prior and #prior~=#party then changes=changes+1 end
        prior=party; counts.party_diff=counts.party_diff+1
        local safe,reason=gate:checkpoint(); counts.safety=counts.safety+1
        if phase=="overworld" then check(safe or reason=="no_new_frame","overworld checkpoint: "..tostring(reason)) end
        -- A hello-sized projection: real decoded records, 4 move slots, identity,
        -- profile/admission fields and one snapshot, not a constant tiny object.
        last_hello=assert(json.encode({event="hello",player="perf",game=title.perf_title,rom_hash=title.rom.sha1,
            party=party,boxes={},protocol_version=1,capabilities={"poll_events","checkpoint"},
            battle=battle,checkpoint=safe,checkpoint_reason=reason,party_changes=changes}))
        counts.json_encode=counts.json_encode+1
    end
    return work,counts,function() return {hello_bytes=last_hello and #last_hello or 0,party_count=prior and #prior or 0} end
end

local function run()
    local root=assert(SLINK_ROOT or os.getenv("SLINK_ROOT"),"SLINK_ROOT required")
    package.path=root.."/lua/?.lua;"..package.path
    local json=dofile(root.."/lua/json_codec.lua")
    local function load_json(path)
        local f=assert(io.open(path,"rb")); local raw=f:read("a"); f:close()
        local parsed=assert(json.decode(raw))
        local function strip(t) for k,v in pairs(t) do if v==json.null then t[k]=nil elseif type(v)=="table" then strip(v) end end end
        strip(parsed); return parsed
    end
    local cfg=load_json(assert(os.getenv("SLINK_GEN4_PERF_CONFIG")))
    local out=assert(os.getenv("SLINK_GEN4_PERF_OUT"))
    local record={schema="gen4-perf-v1",level="PHYSICAL",producer="gen4-PERF",run_id=cfg.run_id,title=cfg.title,
        rom_sha1=cfg.rom_sha1,phase=cfg.phase,scenario=cfg.scenario,source_head=cfg.source_head,
        script_sha256=cfg.script_sha256,profile_sha256=cfg.profile_sha256,module_sha256=cfg.module_sha256,surface_sha256=cfg.surface_sha256,receipt_kind=cfg.receipt_kind,
        config_sha256=cfg.config_sha256,state_sha256=cfg.state_sha256,requested_rate=cfg.rate,
        jit_requested=cfg.jit_requested,effective_jit="UNVERIFIABLE",jit_visibility="config request only",
        callback_hits=0,callback_errors=0,hook_handles={},setup="NATIVE"}
    record.frames_requested=cfg.frames
    record.throttle_config=cfg.throttle_config
    local owned,handles={},{}
    local clock,descriptor
    local function remove(h)
        local ok,result=pcall(event.unregisterbyid,h)
        check(ok and result~=false,"failed unregister retained handle: "..tostring(h)); owned[h]=nil
    end
    local ok,why=pcall(function()
        local profile=load_json(cfg.profile)
        check(profile.schema=="gen4-profile-v1","profile schema")
        local title=need(profile.titles[cfg.title],"profile title"); title.perf_title=cfg.title
        check(title.rom.sha1==cfg.rom_sha1,"profile ROM binding")
        local romhash=gameinfo.getromhash():lower()
        check(romhash==title.rom.sha1 or romhash==title.rom.md5,"loaded ROM binding")
        if not cfg.cold_boot then check(savestate.load(cfg.state_path)~=false,"copied state load failed") end
        joypad.set({})
        for _=1,30 do emu.frameadvance() end
        clock,descriptor=P.clock(); record.clock_source=descriptor.source; record.clock=descriptor
        record.clock_calibration=P.calibrate(clock)
        local reads=dofile(root.."/lua/gen4/reads.lua")
        local mem={}
        local memory_counts={u8=0,u16=0,u32=0}
        for key,api in pairs({u8="read_u8",u16="read_u16_le",u32="read_u32_le"}) do
            mem[key]=function(a) memory_counts[key]=memory_counts[key]+1; return memory[api](a,P.BUS)&0xFFFFFFFF end
        end
        local pk4=dofile(root.."/lua/gen4/pk4.lua")
        local safety=dofile(root.."/lua/gen4/safety.lua")
        if cfg.cold_boot then
            local boot_gate=safety.new(title,mem,{reads=reads,encounter_active=function() return false end})
            local stable=0
            for i=1,6000 do
                local ready=boot_gate:checkpoint(); stable=ready and stable+1 or 0
                if stable>=60 then break end
                local buttons={}; local cycle=i%40
                if cycle<3 then buttons.A=true elseif cycle>=20 and cycle<23 then buttons.Start=true end
                joypad.set(buttons); emu.frameadvance()
            end
            check(stable>=60,"cold JIT boot did not reach checkpoint")
        end
        local workload,counts,audit=P.workload(reads,pk4,safety,json,title,mem,cfg.phase)
        -- Validate state/representation before every case, including the no-workload floor.
        workload(); local matched_state=reads.battle(mem,title)
        check((cfg.phase=="battle")== (matched_state~=nil),"wrong input state phase")
        local work=cfg.workload and workload or nil
        local probe=dofile(root.."/lua/tests/probe_gen4_hooks.lua") -- loaded as test API by global below
        local resident=function(id) return probe.resident(title,mem.u32,id) end
        local function bytes(a,n)
            local b=memory.read_bytes_as_array(a,n,P.BUS); local t={}
            for i=1,n do t[i]=string.format("%02x",b[i]) end; return table.concat(t)
        end
        local function register(spec)
            local addr
            if spec.kind=="exec" then
                local site=need(cfg.sites[spec.site],"packed exec site:"..spec.site)
                if cfg.seam_symbol and site.symbol==cfg.seam_symbol.name then
                    title.symbols[site.symbol]=cfg.seam_symbol.descriptor
                end
                probe.validate_site(title,site,bytes,resident); addr=site.address
            else
                addr=title.symbols.gSystem.address+title.profile.system.vblank_counter_off
            end
            local api=need(event["on_bus_"..spec.kind],"API:on_bus_"..spec.kind)
            local called,h=pcall(api,function() record.callback_hits=record.callback_hits+1 end,addr,
                "g4perf."..cfg.scenario.."."..(#handles+1),P.BUS)
            if not called or not probe.valid_handle(h) then
                record.registration={supported=false,reason=tostring(h),kind=spec.kind,address=addr}
                error({open="callback registration unsupported under requested JIT/config: "..tostring(h)},0)
            end
            owned[h]=true; handles[#handles+1]=h
        end
        for _,spec in ipairs(cfg.hooks) do register(spec) end
        record.registered_hooks=#handles
        record.distinct_addresses=cfg.distinct_addresses
        record.on_demand=cfg.on_demand or false
        local advance=function() joypad.set({}); emu.frameadvance() end
        client.speedmode(cfg.rate); emu.limitframerate(cfg.rate==100)
        for _=1,cfg.warmup_frames do if work then work() end; advance() end
        local start_counts={}; for k,v in pairs(counts) do start_counts[k]=v end
        local start_mem={}; for k,v in pairs(memory_counts) do start_mem[k]=v end
        local hits=record.callback_hits
        local times,work_times
        times,work_times=P.sample(clock,advance,work,cfg.frames)
        -- Request/config echo only; f independently checks measured native cadence.
        record.requested_execution_mode=cfg.rate==100 and "paced_production_frameadvance" or "script_frameadvance_capacity"
        record.frame_times=times; record.work_times=work_times; record.stats=P.stats(times)
        record.load_counts={}; for k,v in pairs(counts) do record.load_counts[k]=v-start_counts[k] end
        record.memory_counts={}; for k,v in pairs(memory_counts) do record.memory_counts[k]=v-start_mem[k] end
        record.callback_hits_sample=record.callback_hits-hits
        record.workload_audit=audit(); record.timing_kind="wall_frame_interval"
        record.instrumentation_floor=not cfg.workload
        record.instrumentation_note="Timing callbacks/clock remain; floor excludes client workload, not literal no-Lua"
        record.removed_after_fire=false
        if cfg.on_demand then
            -- Keep one no-op seam callback armed for the sample window. Then normal
            -- inputs advance a turn solely to witness firing/removal; no HP/flag writes.
            local prior=record.callback_hits
            for i=1,1800 do
                if record.callback_hits>prior then record.removed_after_fire=true; break end
                joypad.set(i%30<2 and {A=true} or {}); emu.frameadvance()
            end
            if not record.removed_after_fire then error({open="on-demand seam did not fire through normal input after timing window"},0) end
        end
        for _,h in ipairs(handles) do remove(h) end
        record.ending_registered=0
        record.clock_crosscheck={os_time=os.time(),note="clock source is declared/calibrated; os.clock is not substituted"}
    end)
    local cleanup_error
    for h in pairs(owned) do local clean,err=pcall(remove,h); if not clean then cleanup_error=tostring(err) end end
    local status="PASS"
    if not ok then status=type(why)=="table" and why.open and "OPEN" or "FAIL"; record.reason=type(why)=="table" and why.open or tostring(why) end
    if cleanup_error then status="FAIL"; record.reason=cleanup_error end
    record.result=status
    local f=assert(io.open(out,"w")); f:write("PERF "..status.." "..assert(json.encode(record)),"\nRESULT: "..status,"\n"); f:close()
    pcall(client.exit)
end
if SLINK_GEN4_PERF_TEST then return P end
SLINK_GEN4_PROBE_TEST=true
run()
return P
