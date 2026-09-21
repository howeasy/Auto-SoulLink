-- P3 stand-in overhead ONLY: no real client/transport, hence no wire timing verdict.
-- SLINK_ROOT, SLINK_GEN3_CHECKPOINT/TITLE, optional SLINK_STATE.
-- SLINK_OVERHEAD_THROTTLE=1 adds realtime A/E/B/C/D after the fast A..H diagnostics.
-- F/H discard pending inserts (real hooks, no frame poll); G closes all exec hooks.
-- shadow_run.start/poll/teardown: lua/gen3/shadow_run.lua:184,296,321.
-- Registered onframeend order mirrors duo_main.lua:102-120; we verify actual order too.
local P = {FRAMES=600, WINDOWS=5}
-- Hooks-only must not trip signals.MAX_PENDING=64: retain the real callback/byte
-- checks and signal construction, but discard queue inserts synchronously.
function P.discard_queue(signals, counter)
    signals.pending=setmetatable({}, {__newindex=function(_,_,signal)
        counter[signal.kind]=(counter[signal.kind] or 0)+1
    end})
end
function P.fps(ms) return ms>0 and 600000/ms or 0 end
function P.realtime_ok(base, measured)
    return P.fps(P.median(base))>=59.5 and P.fps(P.median(measured))>=59.5
        and P.within(base,measured)
end
function P.median(values)
    assert(#values > 0, "empty sample")
    local copy = {}
    for i,v in ipairs(values) do
        assert(type(v)=="number" and v==v and v>0 and v<math.huge, "invalid duration")
        copy[i]=v
    end
    table.sort(copy)
    local n=#copy
    if n%2==1 then return copy[(n+1)//2] end
    return (copy[n//2]+copy[n//2+1])/2
end
function P.delta(base, measured) return (P.median(measured)/P.median(base)-1)*100 end
-- No console or file output by this measurement loop. Observer file I/O remains real;
-- its console STATUS output is buffered via its injected console until after timing.
function P.window(advance, clock, wall, frames)
    local w0,c0=wall(),clock()
    for _=1,frames do advance() end
    local cpu,elapsed=clock()-c0,wall()-w0
    assert(cpu>0 and elapsed>=0, "timer did not advance monotonically")
    return cpu*1000,elapsed*1000
end
function P.within(base, measured) return P.median(measured)<=P.median(base)*1.05 end

function P.run()
    local wt=assert(SLINK_ROOT or os.getenv("SLINK_ROOT"),"SLINK_ROOT required")
    local G=dofile(wt.."/lua/tests/gen3_boot_check.lua")
    local Shadow=dofile(wt.."/lua/gen3/shadow_run.lua")
    local json=dofile(wt.."/lua/json_codec.lua")
    G.open("probe_gen3_overhead")
    G.budget=65000
    local throttle=os.getenv("SLINK_OVERHEAD_THROTTLE")=="1"
    memory.usememorydomain("System Bus")
    local cp,title=G.checkpoint()
    local pack=title=="radical_red" and "gen3_rr" or "gen3_frlg"
    local f=assert(io.open(wt.."/data/games/"..pack.."/profile.json","rb"))
    local profile=assert(json.decode(f:read("a"))).titles[title]; f:close()
    local ram=assert(profile.ram)
    local state_path=os.getenv("SLINK_STATE")
    local results,active_ids,observer={}, {},nil
    local function register(fn,name)
        local id=event.onframeend(fn,"SLink-overhead-"..name)
        assert(id and tostring(id):gsub("[{}]", "")~="00000000-0000-0000-0000-000000000000",
            "frame callback registration failed")
        active_ids[#active_ids+1]=id
    end
    local function cleanup()
        for _,id in ipairs(active_ids) do event.unregisterbyid(id) end
        active_ids={}
        if observer then observer.teardown(); observer=nil end
    end
    local ok,err=pcall(function()
        -- A/E provide separate no-observer counterparts. No code from the old client
        -- is loaded; its socket/HUD cost cannot be inferred from these measurements.
        local canonical
        -- Fast diagnostics always run; throttled qualification is an additional pass.
        local schedule={}
        for _,label in ipairs({"A","E","B","C","D","F","G","H"}) do
            schedule[#schedule+1]={label=label,speed=6399}
        end
        if throttle then
            for _,label in ipairs({"A","E","B","C","D"}) do
                schedule[#schedule+1]={label=label,speed=100}
            end
        end
        for _,config in ipairs(schedule) do
            local label,speed=config.label,config.speed
            client.speedmode(speed)
            if state_path and state_path~="" then savestate.load(state_path)
            elseif label=="A" then assert(G.boot_to_field(cp,9000),"boot never reached field") end
            joypad.set({}); G.idle(30)
            local callback_error,order_error,last_frame,phase=nil,nil,nil,0
            local standin_calls,poll_calls,checksum=0,0,0
            local buffered,hook_counts={},{}
            local hooks_only=label=="F" or label=="H"
            local function ordered(which)
                local frame=emu.framecount()
                if frame~=last_frame then last_frame,phase=frame,0 end
                phase=phase+1
                local first=label=="C" and "standin" or "observer"
                if (label=="C" or label=="D") and which~=(phase==1 and first or
                    (first=="standin" and "observer" or "standin")) then order_error="callback order mismatch" end
            end
            local function guarded(fn)
                return function()
                    local good,why=pcall(fn)
                    if not good then callback_error=tostring(why) end
                end
            end
            local function standin()
                ordered("standin"); standin_calls=standin_calls+1
                local p=cp.predicates.callback2
                checksum=memory.read_u32_le(p.address+p.offset,"System Bus")
                    +memory.read_u8(assert(ram.PARTY_COUNT_ADDR),"System Bus")
                for i=0,99 do checksum=checksum+memory.read_u8(assert(ram.PARTY_BASE)+i,"System Bus") end
            end
            if label=="E" or label=="C" then register(guarded(standin),label.."-standin") end
            if label~="A" and label~="E" then
                observer=assert(Shadow.start({shadow=true,
                    console={log=function(line) buffered[#buffered+1]=tostring(line) end},
                    duo={player="a",result=wt.."/patch/build/overhead_"..speed.."_"..label..".txt"}}),"observer missing")
                assert(observer.admitted_by~="default","observer admission fell back")
                local bindings={}
                for name,site in pairs(observer.parts.sites) do
                    bindings[#bindings+1]=name..":"..tostring(site.address)..":"..tostring(site.capture_offset)
                end
                table.sort(bindings)
                local signature=table.concat(bindings,",")
                canonical=canonical or signature
                assert(signature==canonical,"observer site set differs from baseline observer")
                assert(observer.parts.signals:status().registered==#bindings,"incomplete duo site set")
                if label=="G" or label=="H" then observer.parts.signals:close() end
                if label=="H" then
                    local Signals=dofile(wt.."/lua/gen3/signals.lua")
                    observer.parts.signals=Signals.new(observer.parts.profile,
                        {frame_control=assert(observer.parts.sites.frame_control)},observer.deps.io,observer.deps.ev)
                end
                if hooks_only then P.discard_queue(observer.parts.signals,hook_counts)
                else
                    register(guarded(function()
                        ordered("observer"); poll_calls=poll_calls+1; observer.poll()
                    end),label.."-observer")
                end
            end
            if label=="D" then register(guarded(standin),label.."-standin") end
            G.idle(60) -- warm-up excluded; all timed windows use the same frame count
            local start_standin,start_poll=standin_calls,poll_calls
            local function live_count()
                return hooks_only and (hook_counts.frame_control or 0)
                    or (observer and (observer.liveness_counts.frame_control or 0) or 0)
            end
            local start_live=live_count()
            local cpu,wall,approx={},{},{}
            for i=1,P.WINDOWS do
                local prior=live_count()
                cpu[i],wall[i]=P.window(G.advance,os.clock,os.time,P.FRAMES)
                if observer and label~="G" then
                    assert(live_count()>prior,"no liveness in measurement window")
                end
                local available,value=pcall(function() return client.get_approx_framerate() end)
                approx[i]=available and type(value)=="number" and tostring(value) or "unavailable"
            end
            local st=observer and observer.parts.signals:status() or nil
            local live=live_count()-start_live
            local expected=0
            if observer then for _ in pairs(observer.parts.sites) do expected=expected+1 end end
            assert(not callback_error,callback_error)
            assert(not order_error,order_error)
            if label=="C" or label=="D" or label=="E" then assert(standin_calls-start_standin==3000,"stand-in missed frames") end
            if st then
                if label=="H" then expected=1 end
                assert(st.registered==expected and expected>0 and st.rejected==0 and st.dropped==0
                    and not st.failed and not st.handler_error,"observer not healthy")
                assert(poll_calls-start_poll==(hooks_only and 0 or 3000),"poll count differs")
                if label=="G" then assert(st.closed and #observer.parts.signals.hooks==0 and live==0,"poll-only has live hooks")
                else assert(not st.closed and live>0,"observer not live") end
            end
            -- os.clock is a CPU/process timer on some hosts, NOT universally wall time.
            -- Cross-check totals against os.time (1-second resolution); fail unreliable clocks.
            local total_cpu,total_wall=0,0
            for i=1,P.WINDOWS do total_cpu=total_cpu+cpu[i]; total_wall=total_wall+wall[i] end
            local clock_ok=math.abs(total_cpu-total_wall)<=2000
            results[speed]=results[speed] or {}
            results[speed][label]={cpu=cpu,wall=wall,clock_ok=clock_ok}
            cleanup()
            G.log("CONFIG speed="..speed.." label="..label.." hooks_only_discard_sink="..tostring(hooks_only))
            G.log(string.format("OVERHEAD %s median_ms_per_600=%.3f fps=%.2f wall_total_ms=%d clock_total_ms=%.3f clock_crosscheck=%s registered=%d rejected=%d liveness=%d standin_reads=%d checksum=%s",
                label,P.median(cpu),600000/P.median(cpu),total_wall,total_cpu,tostring(clock_ok),
                st and st.registered or 0,st and st.rejected or 0,live,standin_calls-start_standin,tostring(checksum)))
            G.log("WINDOWS "..label.." clock_ms="..table.concat(cpu,",").." wall_ms="..table.concat(wall,","))
            local cf,wf={},{}
            for i=1,P.WINDOWS do cf[i]=P.fps(cpu[i]); wf[i]=P.fps(wall[i]) end
            G.log("FPS "..label.." clock="..table.concat(cf,",").." wall="..table.concat(wf,",")
                .." approx="..table.concat(approx,",").." wall_resolution_s=1")
            for _,line in ipairs(buffered) do G.log(line) end -- AFTER all five timed windows
        end
    end)
    local clean,clean_err=pcall(cleanup)
    local passed=ok and clean
    if passed then
        for _,pair in ipairs({{"B","A"},{"C","E"},{"D","E"},{"F","A"},{"G","A"},{"H","A"}}) do
            local measured,base=results[6399][pair[1]],results[6399][pair[2]]
            local delta=P.delta(base.cpu,measured.cpu)
            G.log(string.format("INFORMATIONAL speed=6399 %s/%s clock_delta_percent=%.3f",
                pair[1],pair[2],delta))
        end
        if throttle then
            for _,label in ipairs({"A","E","B","C","D"}) do
                local fps=P.fps(P.median(results[100][label].wall))
                passed=passed and fps>=59.5
                G.log(string.format("REALTIME %s median_wall_fps=%.3f minimum=59.5 verdict=%s",
                    label,fps,fps>=59.5 and "PASS" or "FAIL"))
            end
            for _,pair in ipairs({{"B","A"},{"C","E"},{"D","E"}}) do
                local measured,base=results[100][pair[1]],results[100][pair[2]]
                local good=P.realtime_ok(base.wall,measured.wall)
                passed=passed and good
                G.log(string.format("BUDGET speed=100 %s/%s wall_delta_percent=%.3f clock_delta_percent=%.3f verdict=%s",
                    pair[1],pair[2],P.delta(base.wall,measured.wall),P.delta(base.cpu,measured.cpu),good and "PASS" or "FAIL"))
            end
        end
    end
    G.log("SCOPE standin_only console_status_deferred=true wire_timings=UNVERIFIED wire_deltas=UNVERIFIED wall_resolution_s=1")
    G.finish(passed,not ok and tostring(err) or not clean and tostring(clean_err)
        or (throttle and "throttled stand-in budget (coarse wall clock)" or "diagnostics only; no realtime budget verdict"))
end
if (debug.getinfo(1,"S").source or "") == "main" then P.run() end
return P
