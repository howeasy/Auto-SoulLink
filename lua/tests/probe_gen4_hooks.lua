-- G1 instrumentation, not a production NDS binding. Addresses/pins come from C1-2.
-- No console traffic in callbacks or frame loops. One terminal io.open receipt.
-- Offline consumers set SLINK_GEN4_PROBE_TEST=true and receive the test API.
local M = {}
local ROWS = "abcdefghijklmn"
local BUS = "ARM9 System Bus"
local function need(value, name)
    if value == nil then error({open=name}, 0) end
    return value
end
local function check(value, name) assert(value, name) end
local function u32(value) return value & 0xFFFFFFFF end
local function count(t) local n=0; for _ in pairs(t) do n=n+1 end; return n end
function M.same_distribution(a,b)
    local na,nb=0,0
    for _,v in pairs(a) do na=na+v end; for _,v in pairs(b) do nb=nb+v end
    if na==0 or nb==0 then return nil end
    for k,v in pairs(a) do if v*nb~=(b[k] or 0)*na then return false end end
    for k,v in pairs(b) do if v*na~=(a[k] or 0)*nb then return false end end
    return true
end
local function clone(t)
    if type(t)~="table" then return t end
    local result={}; for k,v in pairs(t) do result[k]=clone(v) end; return result
end
local function word(hex)
    check(type(hex)=="string" and #hex==8 and hex:match("^%x+$"), "fire_hex must be four bytes")
    -- C1-2 fire_hex() formats the decoded LE u32, not its on-ROM byte spelling.
    return tonumber(hex,16)
end
local function byte_word(hex)
    local n=0; for i=0,3 do n=n | (tonumber(hex:sub(2*i+1,2*i+2),16) << (8*i)) end
    return n
end
function M.read_register(names,reader,name)
    check(names[name]~=nil,"unknown register name: "..name)
    return u32(reader(name))
end
function M.host_write_control(read_byte,write_byte,address)
    local original=read_byte(address)
    local complement=(~original)&255
    local ok,why=pcall(function()
        write_byte(address,complement)
        check(read_byte(address)==complement,"host write intermediate readback")
    end)
    local restored,restore_error=pcall(write_byte,address,original)
    check(restored,"host write restore failed: "..tostring(restore_error))
    check(read_byte(address)==original,"host write restore readback")
    check(ok,"host write control failed: "..tostring(why))
end
function M.record_boot_input(audit,buttons)
    for button,pressed in pairs(buttons) do if pressed then audit[button]=(audit[button] or 0)+1 end end
end
function M.other_boot_buttons(audit)
    local n=0; for button,hits in pairs(audit) do if button~="A" and button~="Start" then n=n+hits end end
    return n
end
function M.boot(mode,limit,idle,field_live,step,frame)
    local stable,audit,first_live=0,{},nil
    for i=1,limit do
        local live=field_live()
        if live and first_live==nil then first_live=frame() end
        if idle() then stable=stable+1 else stable=0 end
        if stable>=60 then return {overworld=true,boot_inputs=audit,other_boot_buttons=M.other_boot_buttons(audit),boot_frame=frame(),first_field_live_frame=first_live} end
        local buttons={}
        if mode~="no-buttons" and not live then
            local p=i%40; if p<3 then buttons.A=true elseif p>=20 and p<23 then buttons.Start=true end
        end
        M.record_boot_input(audit,buttons); step(buttons)
    end
    return {overworld=false,boot_inputs=audit,other_boot_buttons=M.other_boot_buttons(audit),boot_frame=frame(),first_field_live_frame=first_live}
end
function M.rtc_slice(title)
    local rtc=need(title.profile.rtc,"k:pack profile.rtc (symbol, date/time offsets and sizes, source)")
    local sym=need(title.symbols[need(rtc.symbol,"k:pack RTC symbol")],"k:RTC symbol descriptor")
    local source=need(rtc.source,"k:pack RTC source")
    check(type(source)=="string" and source~="","RTC source empty")
    local result={}
    for _,name in ipairs({"date","time"}) do
        local offset,size=need(rtc[name.."_off"],"k:pack RTC "..name.." offset"),need(rtc[name.."_size"],"k:pack RTC "..name.." size")
        check(type(offset)=="number" and offset%1==0 and offset>=0 and type(size)=="number" and size%1==0
            and size>0 and offset+size<=sym.size,"RTC slice outside packed symbol")
        result[name.."_address"]=sym.address+offset; result[name.."_size"]=size
    end
    return result
end
function M.sample_rtc(title,target,step,frame,bytes)
    local rtc=M.rtc_slice(title)
    target=need(target,"k:fixed RTC sample frame config")
    check(type(target)=="number" and target%1==0 and target>0 and target<=12000,"invalid RTC sample frame")
    local now=frame()
    check(type(now)=="number" and now%1==0 and now>=0,"invalid emulator frame count")
    if now>target then error({open="k:fixed RTC sample frame "..target.." already passed at "..now},0) end
    -- Boot completion is a predicate, not a fixed time (hge observed 977 vs 979).
    -- Advance only empty inputs, then report the REAL counter; never relabel a sample.
    for _=1,target-now do step({}) end
    local sampled=frame()
    check(sampled==target,"RTC sample frame advance did not reach the fixed frame")
    return {first=bytes(rtc.date_address,rtc.date_size)..bytes(rtc.time_address,rtc.time_size),
        frame_first=sampled,sample_frame=target}
end
function M.save_driver_witness(title,read,read_byte,frame)
    local p=need(title.profile.probe_field,"save:pack probe_field")
    local fs=read(need(title.symbols.sFieldSysPtr,"save:FieldSystem symbol").address)
    if fs==0 then return nil end
    local driver=read(fs+need(p.save_driver,"save:driver offset")); if driver==0 then return nil end
    local data=read(driver+need(p.save_driver_data_off,"save:driver data offset")); if data==0 then return nil end
    return {driver=driver,data=data,state=read_byte(data+need(p.save_state,"save:state offset")),frame=frame}
end
function M.save_completed(trace)
    if type(trace)~="table" or #trace<3 then return false end
    local first=trace[1]; local active=false; local last_frame=-1
    if first.state~=1 or type(first.driver)~="number" or first.driver<=0 or type(first.data)~="number" or first.data<=0 then return false end
    for _,v in ipairs(trace) do
        if v.driver~=first.driver or v.data~=first.data or type(v.frame)~="number" or v.frame%1~=0 or v.frame<0 or v.frame<last_frame
            or type(v.state)~="number" or v.state%1~=0 or v.state<1 or v.state>7 then return false end
        last_frame=v.frame
        if v.state>=2 and v.state<=7 then active=true end
    end
    return active and trace[#trace].state==1 and trace[#trace].frame>first.frame
end
function M.predicate(title,read,p)
    local sym=need(title.symbols[p.symbol],"predicate symbol:"..tostring(p.symbol))
    local base=read(sym.address)
    -- The pinned reset leg explicitly tests the root pointer variable itself.
    if p.zero and #(p.deref or {})==0 and p.offset==0 then return base==0 end
    for _,offset in ipairs(p.deref or {}) do
        if base==0 then return false end
        base=read(base+offset)
    end
    if base==0 then return false end -- A null chain is not a valid target field.
    local value=read(base+p.offset)
    if p.nonzero then return value~=0 end
    if p.zero then return value==0 end
    return value==p.value
end
function M.internal_load_id(entry,read_register)
    local id=entry.id
    if entry.id_register then
        id=read_register(entry.id_register)
        if entry.id and id~=entry.id then return nil end
    end
    need(id,"c:internal loader ID argument/constant")
    if entry.ids then
        local allowed=false
        check(type(entry.ids)=="table" and #entry.ids>0,"internal loader ID set")
        for _,value in ipairs(entry.ids) do if id==value then allowed=true end end
        if not allowed then return nil end
    end
    return id
end
function M.play_recipe(leg,step,until_matches)
    local used=0
    local function advance(buttons)
        if used>=leg.max_frames then return false end
        step(buttons); used=used+1
        return until_matches(leg["until"])
    end
    if until_matches(leg["until"]) then return 0 end
    while used<leg.max_frames do
        local before=used
        for _,s in ipairs(leg.steps) do
            local buttons={}; for _,button in ipairs(s.press) do buttons[button]=true end
            for _=1,s.hold_frames do if advance(buttons) then return used end end
            for _=1,s.then_wait_frames do if advance({}) then return used end end
        end
        if used==before and advance({}) then return used end -- wait-only recipe
    end
    check(until_matches(leg["until"]),"route until predicate not reached: "..leg.name)
    return used
end
function M.valid_handle(h)
    return type(h)=="string" and h~="" and h:gsub("[%-%{%}]", ""):match("^0+$")==nil
end
function M.resident(title, read, id)
    local t=need(title.overlay_table,"overlay_table")
    check(t.regions==3 and t.per_region==8 and t.entry_size==8, "overlay table geometry")
    -- MAIN only: the other two regions are still included in the transition census.
    for i=0,t.per_region-1 do
        local p=t.address+i*t.entry_size
        if read(p+t.active_off)~=0 and read(p+t.id_off)==id then return true end
    end
    return false
end
function M.validate_site(title, site, bytes, resident)
    local sym=need(title.symbols[site.symbol],"symbol:"..tostring(site.symbol))
    if site.hge_status=="REPLACED" then
        local replacement=need(title.hge_replacements and title.hge_replacements[site.symbol],"hge replacement export:"..site.symbol)
        check(replacement.address==site.address and replacement.image==site.image and type(site.mode_evidence)=="string",
            "hge replacement export provenance")
        sym={address=replacement.address,image=replacement.image,mode=site.mode}
    end
    check(site.address%2==0 and site.address==sym.address, "site must use even symbol address")
    check(site.image==sym.image and site.mode==sym.mode, "site symbol provenance")
    check(site.mode=="thumb" or site.mode=="arm", "site instruction mode")
    word(site.fire_hex)
    check(type(site.register_hex)=="string" and site.register_hex:match("^%x+$")
        and #site.register_hex==site.extent*2 and site.extent>=4, "full registration extent")
    check(byte_word(site.register_hex:sub(1,8))==word(site.fire_hex), "fire/registration pin disagreement")
    if site.image~="arm9" then
        check(site.image=="ov"..tostring(site.overlay_id), "declared overlay identity")
        local ov=need(title.overlays[tostring(site.overlay_id)],"overlay:"..site.overlay_id)
        check(site.address>=ov.ram and site.address+site.extent<=ov.ram+ov.size, "overlay extent")
    end
    if site.image=="arm9" or resident(site.overlay_id) then
        local actual=bytes(site.address,site.extent):lower()
        check(actual==site.register_hex:lower(), "full registration pin mismatch: "..tostring(site.id or site.symbol)
            .." image="..site.image.." address="..string.format("%08x",site.address)
            .." expected="..site.register_hex:lower().." actual="..actual)
    end
    return clone(site)
end
function M.save_witness_ok(title, pointer, field_save, signature, identity, expected)
    local symbol=title.symbols.sSaveDataPtr
    local declared=title.profile.save_ptr
    return pointer>0 and pointer%4==0 and pointer==field_save
        and declared.symbol=="sSaveDataPtr" and declared.address==symbol.address
        and symbol.section==".bss" and symbol.image=="arm9"
        and signature==expected.signature_hex and identity==expected.identity_hex
end
function M.capture(site, addr, val, flags, pc, resident)
    -- Collision rejection MUST precede the fire-word check.
    if site.image~="arm9" and not resident(site.overlay_id) then return nil end
    check(u32(addr)==site.address, "callback address mismatch")
    check(u32(pc)==site.address+(site.mode=="thumb" and 4 or 8), "callback PC mismatch")
    check(u32(val)==word(site.fire_hex), "active owner fire pin mismatch")
    return {id=site.id,address=u32(addr),word=u32(val),pc=u32(pc),flags=u32(flags)}
end
function M.phase_sites_ready(sites,bytes,resident,frame,state,policy,image_pins,want_arm)
    if want_arm==nil then want_arm=true end
    local ready=true
    for _,site in ipairs(sites) do
        local active=site.image=="arm9" or resident(site.overlay_id)
        if not active then
            state.current[site.id]=nil; ready=false
        else
            local sample=state.current[site.id]
            if not sample then
                sample={site=site.id,image=site.image,table_active_frame=frame}
                state.current[site.id]=sample; state.samples[#state.samples+1]=sample
            end
            local actual=bytes(site.address,site.extent):lower()
            local expected=site.register_hex:lower()
            local detail=site.id.." image="..site.image.." address="..string.format("%08x",site.address)
                .." expected="..expected.." actual="..actual
            if actual==expected then
                if not sample.pin_ready_frame then
                    sample.pin_ready_frame=frame; sample.settle_frames=frame-sample.table_active_frame
                end
            else
                sample.initial_bytes=sample.initial_bytes or actual
                local elapsed=frame-sample.table_active_frame
                sample.waited_frames=elapsed
                if want_arm then
                    check(not sample.pin_ready_frame,"confirmed site changed: "..detail)
                    check(site.image~="arm9","static pin mismatch: "..detail)
                    for image,pin in pairs(need(image_pins[site.id],"n:other-image FILE pins: "..site.id)) do
                        check(actual~=pin:lower(),"wrong-image match: "..image.." "..detail)
                    end
                    check(elapsed<policy.max_frames,"settle deadline ("..policy.max_frames.." frames): "..detail)
                end
                ready=false
            end
        end
    end
    return ready
end
function M.observe_overlay(b,site,addr,val,flags,pc,bytes,resident)
    if not resident(site.overlay_id) then b.dropped=b.dropped+1; return end
    if bytes(site.address,site.extent)~=site.register_hex then b.callback_corrupt=b.callback_corrupt+1; return end
    local ok,err=pcall(M.capture,site,addr,val,flags,pc,resident)
    if ok then b.accepted=b.accepted+1 else b.callback_corrupt=b.callback_corrupt+1; b.error=tostring(err) end
end

-- Probe-only composition over the REAL shared registry. Track external handles, not
-- cumulative status().registered. A failed close retains its owner and freezes re-arm.
function M.composite(Registry, binding)
    local s={phases={},handles={},ready_events={},failure=nil,peak=0,costs={}}
    function s:live_handles() return count(self.handles) end
    function s:enter(phase, sites)
        if self.failure then return nil,self.failure end
        if self.phases[phase] then return nil,"phase already armed" end
        if #sites==0 then return true end
        if self:live_handles()+#sites>4 then self.failure="phase hook budget exceeded"; return nil,self.failure end
        local before=os.clock()
        local reg,err,partial=Registry.new({owner="g4probe."..phase,sites=sites,max_pending=4096,
            validate=binding.validate,valid_handle=M.valid_handle,capture=binding.capture,
            register=function(site,callback,name)
                local h=binding.register(site,callback,name)
                if M.valid_handle(h) then self.handles[h]=phase end
                self.peak=math.max(self.peak,self:live_handles())
                return h
            end,
            unregister=function(h)
                local result=binding.unregister(h)
                if result~=false then self.handles[h]=nil end
                return result
            end})
        self.costs[#self.costs+1]=os.clock()-before
        if not reg then
            self.failure=err; if partial then self.phases[phase]=partial end
            return nil,err
        end
        self.phases[phase]=reg; return true
    end
    function s:drain()
        local out=self.ready_events; self.ready_events={}
        for _,reg in pairs(self.phases) do
            for _,e in ipairs(reg:drain()) do out[#out+1]=e end
            local status=reg:status()
            if status.failed or status.handler_error then self.failure=status.failed or status.handler_error end
        end
        return out
    end
    function s:leave(phase)
        local reg=self.phases[phase]; if not reg then return true end
        -- Last queued event remains observable exactly once, even after close fails.
        for _,e in ipairs(reg:drain()) do self.ready_events[#self.ready_events+1]=e end
        local before=os.clock()
        local ok,result=pcall(reg.close,reg)
        self.costs[#self.costs+1]=os.clock()-before
        if not ok or result~=true then self.failure="phase cleanup failed: "..phase; return false end
        local status=reg:status()
        if status.failed or status.handler_error then self.failure=status.failed or status.handler_error end
        self.phases[phase]=nil; return true
    end
    function s:close()
        local keys={}; for phase in pairs(self.phases) do keys[#keys+1]=phase end
        local ok=true; for _,phase in ipairs(keys) do if not self:leave(phase) then ok=false end end
        return ok and self:live_handles()==0
    end
    return s
end

function M.phase_controls(Registry)
    local result={level="MODEL"}
    local callbacks,active,serial={}, {},0
    local fail_remove,fail_register=false,false
    local binding={validate=function(site) return site end,capture=function(site) return {id=site.id} end}
    binding.register=function(site,cb)
        if fail_register and site.id=="second" then return "00000000-0000-0000-0000-000000000000" end
        serial=serial+1; local h="control-"..serial; active[h]=true; callbacks[site.id]=cb; return h
    end
    binding.unregister=function(h) if fail_remove then return false end; active[h]=nil; return true end
    local s=M.composite(Registry,binding)
    check(s:enter("empty",{}),"zero-site phase")
    check(s:enter("pc",{{id="last"}}),"static PC construct")
    callbacks.last(); s:leave("pc")
    result.last_event=#s:drain(); result.second_drain=#s:drain(); result.after_close=s:live_handles()
    check(s:enter("reset",{{id="reset"}}),"reset construct")
    callbacks.reset(); s:close(); result.reset_event=#s:drain()
    check(s:enter("failedclose",{{id="last"}}),"failed-close construct")
    callbacks.last(); fail_remove=true
    result.close_ok=s:leave("failedclose"); result.retained=s:live_handles()
    result.fault=s.failure~=nil; result.rearm=s:enter("failedclose",{{id="last"}})==true
    result.failed_last=#s:drain(); result.failed_second=#s:drain()
    fail_remove=false; check(s:close(),"control cleanup must release owner")
    -- Partial construction plus failed cleanup must retain the first handle.
    local p=M.composite(Registry,binding); fail_register=true; fail_remove=true
    p:enter("partial",{{id="first"},{id="second"}})
    result.partial_fault=p.failure~=nil; result.partial_retained=p:live_handles()
    fail_register=false; fail_remove=false; check(p:close(),"partial control cleanup")
    local budget=M.composite(Registry,binding)
    check(budget:enter("budget",{{id="one"},{id="two"},{id="three"},{id="four"}}),"four-hook budget")
    result.fifth=budget:enter("fifth",{{id="five"}})==true
    result.peak=budget.peak; check(budget:close(),"budget cleanup")
    return result
end

local validators={}
validators.a=function(x)
    for _,mode in ipairs({"arm","thumb"}) do
        local v=need(x[mode],"a:"..mode)
        check(v.frames>0 and v.hits==v.frames and v.badpc==0 and v.badword==0,"per-frame "..mode.." hook")
    end
    check(need(x.negative_hits,"a:never-executed control")==0,"never-executed hook fired")
end
validators.b=function(x)
    check(need(x.accepted,"b:faint command")>0,"no owning-overlay faint hit")
    if need(x.dropped,"b:wrong-overlay physical collision")==0 then error({open="b:wrong-overlay physical collision unobserved"},0) end
    check(x.inactive_drop==true and x.active_fault==true and x.full_pin_reject==true,
        "residency / active fault / full registration controls")
    check(x.callback_corrupt==0,"active callback address/PC/word corruption")
end
function M.census_measure(x)
    local used,lags={},{}
    for _,change in ipairs(x.changes) do
        local found,candidate=nil,nil
        for i,cause in ipairs(x.causes) do
            if not used[i] and cause.id==change.id and cause.region==change.region
                and cause.kind==change.kind and change.frame>=cause.frame
                and type(cause.source)=="string" and cause.source~="" then
                candidate=candidate or i
                if change.frame-cause.frame<=2 then found=i; break end
            end
        end
        local cause=x.causes[found or candidate]
        lags[#lags+1]={id=change.id,region=change.region,kind=change.kind,frame=change.frame,
            cause_frame=cause and cause.frame,lag=cause and change.frame-cause.frame,matched=found~=nil}
        if found then used[found]=true end
    end
    return lags
end
function M.census_ok(x)
    for _,lag in ipairs(M.census_measure(x)) do if not lag.matched then return false end end
    return true
end
validators.c=function(x)
    check(x.jit==false and x.use_real_time==false,"unpinned core settings")
    check(#need(x.changes,"c:table transitions")>0,"empty transition census")
    check(#need(x.table_transitions,"c:full 24-entry table transition trace")>0,"empty raw table trace")
    need(x.causes,"c:load/unload/internal causes")
    x.measured_lags=M.census_measure(x)
    check(M.census_ok(x),"unexplained table transition: pinned cause within 0..2 frames required")
    check(need(x.quiet_changes,"c:load-free window")==0,"load-free window changed")
    local red=clone(x); table.remove(red.causes,1)
    check(not M.census_ok(red),"omitted cause did not make census red")
end
validators.d=function(x)
    check(need(x.hits,"d:game stores")>0,"game store callback absent")
    check(x.timing=="before" or x.timing=="after","write timing ambiguous")
    check(x.host_hits==0 and x.wrong_hits==0,"host/wrong-address callback fired")
end
validators.e=function(x)
    check(need(x.before,"e:liveness")>0 and x.kept>0,"liveness control dead")
    check(x.removed==0 and need(x.reloaded,"e:private savestate reload")==0,"hook survived removal/reload")
end
validators.f=function(x)
    -- Owner superseded the cap-three ruling: averages and unthrottled curves
    -- characterize cost but cannot qualify sustained full-client 1x delivery.
    local sustained=need(x.sustained,"f:gen4-PERF sustained full-client timing records (0 hooks and 1 on-demand)")
    for _,name in ipairs({"zero","one","overworld_zero"}) do
        local sample=need(sustained[name],"f:sustained "..name.."-hook load sample")
        check(sample.requested_execution_mode=="paced_production_frameadvance","sustained sample must request paced frameadvance")
        local throttle=need(sample.throttle_config,"f:requested throttle settings")
        check(throttle.Unthrottled==false and throttle.ClockThrottle==true and throttle.SpeedPercent==100
            and throttle.FrameSkip==0 and throttle.AutoMinimizeSkipping==false and throttle.VSyncThrottle==false
            and throttle.SuperHawkThrottle==false,"unpaced performance config")
        check(sample.requested_rate==100 and sample.frames>=3000,"sustained measurement needs >=3000 frames at 1x")
        check(sample.registered_hooks==(name=="one" and 1 or 0),"incorrect sustained hook count")
        check(sample.timing_kind=="wall_frame_interval" and type(sample.clock_source)=="string" and sample.clock_source~="",
            "sustained measurement requires a declared wall-clock frame-interval source")
        check(need(sample.clock,"f:clock descriptor").monotonic_guaranteed==true,"performance clock lacks monotonic guarantee")
        local times=need(sample.frame_times,"f:raw per-frame timings")
        check(#times==sample.frames,"incomplete sustained timing sequence")
        local sorted,total={},0
        for i,t in ipairs(times) do check(type(t)=="number" and t>0 and t<math.huge,"invalid frame time"); sorted[i]=t; total=total+t end
        table.sort(sorted)
        local p99=sorted[math.ceil(#sorted*0.99)]
        local maximum=sorted[#sorted]
        local native_fps=33513982/560190 -- BizHawk MelonDS.cs DefaultFpsNumerator/Denominator
        check(math.abs((#times/total)/native_fps-1)<=0.001,"mean FPS outside native-cadence 0.1% tolerance")
        local floor=need(sample.floor,"f:same-session bare-floor sample")
        check(need(floor.clock,"f:floor clock descriptor").monotonic_guaranteed==true,"floor clock lacks monotonic guarantee")
        check(floor.session_id==sample.session_id and floor.phase==sample.phase and floor.clock_source==sample.clock_source,
            "floor belongs to a different session/phase/clock")
        check(floor.requested_rate==100 and floor.registered_hooks==0 and floor.instrumentation_floor==true,"floor not bare paced zero-hook")
        local baseline=need(floor.frame_times,"f:raw floor timing sequence")
        check(#baseline>=3000,"floor window too short")
        local fs={}; for i,t in ipairs(baseline) do check(type(t)=="number" and t>0 and t<math.huge,"invalid floor interval"); fs[i]=t end
        table.sort(fs)
        check(p99<=fs[math.ceil(#fs*0.99)]+0.001,"p99 exceeds same-session floor plus 1ms")
        check(maximum<=0.03343,"frame interval exceeds 33.43ms owner limit")
        local load=need(sample.load_counts,"f:full-client workload counts")
        for _,work in ipairs({"pointer_chain","party_diff","json_encode"}) do
            check(type(load[work])=="number" and load[work]>=sample.frames,"missing per-frame client load: "..work)
        end
        if name=="overworld_zero" then
            check(sample.phase=="overworld" and load.battle_attempts>=sample.frames and load.battle_mons_hp==0,"overworld battle-chain/load accounting")
        else check(load.battle_mons_hp>=sample.frames,"battle HP workload missing") end
        check(sample.ending_registered==0,"hook retained in steady state after measurement")
        if name=="one" then check(sample.on_demand==true and sample.removed_after_fire==true,"one-hook sample must prove on-demand removal") end
    end
end
validators.g=function(x)
    for name,size in pairs({["Main RAM"]=4194304,["Shared WRAM"]=32768,["ARM7 WRAM"]=65536,
        SRAM=524288,["Instruction TCM"]=32768,["Data TCM"]=16384,[BUS]=0}) do check(x.domains[name]==size,"domain:"..name) end
    for i=0,15 do check(x.registers["ARM9 r"..i]~=nil,"register ARM9 r"..i) end
    check(x.bogus_refused==true,"bogus register silently accepted")
    check(need(x.raw_core_bogus_accepted,"g:raw core bogus-name result")==true,"raw core bogus-name platform behavior changed")
end
validators.h=function(x)
    check(need(x.pointer,"h:SaveData pointer")>0 and x.pointer==x.field_save,"SaveData / FieldSystem disagreement")
    check(need(x.signature,"h:independent page signature")==x.expected_signature,"page signature mismatch")
    check(need(x.identity,"h:loaded-save identity")==x.expected_identity,"loaded-save identity mismatch")
    check(x.invalid_rejected and x.signature_rejected and x.provenance_rejected,"SaveData negative controls")
end
validators.i=function(x)
    -- These values must be filled by independent Python decode of the *same* run's
    -- SaveRAM and a cold reload. Lua receipt claims never provide their own oracle.
    check(need(x.written,"i:PYDEC native-save party field")==x.target and x.target~=x.original,"party write did not persist")
    check(x.no_write==x.original,"no-write control changed")
    check(need(x.box_dirty,"i:PYDEC occupied-box write")==x.box_target and x.box_target~=x.box_original,"box write did not persist")
    check(need(x.box_cold_reload,"i:cold RAM occupied-box write")==x.box_target,"box write lost at cold reload")
    check(need(x.box_without_dirty,"i:PYDEC occupied-box write without flag")==x.box_target
        and need(x.box_without_dirty_cold_reload,"i:cold RAM occupied-box write without flag")==x.box_target,
        "box write without flag lost across SAVE/cold reload")
    local cases=need(x.save_driver_cases,"i:save-driver state traces")
    for _,name in ipairs({"party-write","no-write","box-write","box-no-dirty"}) do
        check(M.save_completed(need(cases[name],"i:save-driver trace "..name)),"native save-driver completion absent: "..name)
    end
    check(x.cold_reload==x.target and x.save_completed==true,"cold reload/save boundary absent")
end
validators.j=function(x)
    local h=need(x.hash,"j:gameinfo ROM hash"):lower()
    check(h==x.sha1:lower() or h==x.md5:lower(),"loaded ROM hash differs from pinned file")
    local patched=need(x.patched_hash,"j:one-byte patched ROM boot"):lower()
    check(patched~=x.sha1:lower() and patched~=x.md5:lower(),"one-byte ROM control unchanged")
end
validators.k=function(x)
    check(need(x.first,"k:first pinned boot")==need(x.second,"k:second pinned boot"),"pinned RTC differs")
    check(need(x.unpinned,"k:unpinned RTC control")~=x.first,"unpinned RTC identical")
    check(x.frame_first==x.frame_second,"RTC compared at different frame counts")
end
validators.l=function(x)
    check(need(x.overworld,"l:CONTINUE with A/Start")==true,"buttons-only CONTINUE failed")
    check(need(x.no_buttons_overworld,"l:no-button boot")==false,"no-button boot reached overworld")
    local other=M.other_boot_buttons(need(x.boot_inputs,"l:measured boot input counts"))
    check(x.other_boot_buttons==other and other==0,"CONTINUE used non A/Start input or input accounting mismatch")
end
validators.m=function(x)
    for _,p in ipairs({"overworld","menu","battle","save"}) do
        local hist=need(x.histograms[p],"m:verified phase "..p)
        check(count(hist)>0,"empty CPU histogram")
    end
    check(need(x.halt,"m:OS_Halt symbol")>0 and x.idle_hits>0,"idle-thread PC not observed")
    check(x.save_same_as_idle==false,"save/script PC distribution matches idle")
end
validators.n=function(x)
    local m=need(x.model,"n:real registry controls")
    check(m.last_event==1 and m.second_drain==0 and m.after_close==0 and m.reset_event==1,"last-event/reset drain")
    check(m.close_ok==false and m.retained==1 and m.fault and not m.rearm,"failed-close fault/accounting")
    check(m.failed_last==1 and m.failed_second==0 and m.partial_fault and m.partial_retained==1,
        "failed-construction retention")
    check(not m.fifth and m.peak==4,"hook budget control")
    local p=need(x.physical,"n:pack phase predicates + earliest/last producer oracle")
    local cases=need(p.cases,"n:per-phase case measurements")
    check(#cases>0,"no measured phase cases")
    for _,case in ipairs(cases) do
        check(case.first_expected>0 and case.first_seen==case.first_expected and case.last_expected>0
            and case.last_seen==case.last_expected,"first/last producer lost in phase case: "..tostring(case.phase))
    end
    check(p.first_expected>0 and p.first_seen==p.first_expected and p.last_seen==p.last_expected and p.last_expected>0,
        "first/last producer lost")
    check(p.static_pc and p.reset and p.peak<=4 and p.live_after_close==0,"phase coverage/accounting")
    check(need(p.pending_at_close,"n:physical queued-last-event close")>0 and p.second_drain==0,"physical last-event close not exercised")
    check(p.max_cost<1/60 and p.restored_fps>=p.baseline_fps*0.9,"phase timing/cleanup performance")
end
function M.evaluate(row, observation)
    local ok,why=pcall(function() validators[row](need(observation,row..":observation")) end)
    if ok then return "PASS" end
    if type(why)=="table" and why.open then return "OPEN",why.open end
    return "FAIL",tostring(why)
end

local function run()
    local root=assert(SLINK_ROOT or os.getenv("SLINK_ROOT"),"SLINK_ROOT required")
    local json=dofile(root.."/lua/json_codec.lua")
    local function read_json(path)
        local f=assert(io.open(path,"rb"),"cannot read "..path); local raw=f:read("a"); f:close()
        local parsed=assert(json.decode(raw))
        local function strip_null(t)
            for key,v in pairs(t) do
                if v==json.null then t[key]=nil elseif type(v)=="table" then strip_null(v) end
            end
        end
        strip_null(parsed); return parsed
    end
    local cfg=read_json(assert(os.getenv("SLINK_GEN4_PROBE_CONFIG"),"SLINK_GEN4_PROBE_CONFIG required"))
    local out=assert(os.getenv("SLINK_GEN4_PROBE_OUT"),"SLINK_GEN4_PROBE_OUT required")
    local observations,errors,owned={},{},{}
    local callback_errors,callback_error_detail=0,nil
    local started,advanced=os.clock(),0
    local title,pack
    local function guarded(row,fn)
        local ok,result=pcall(fn)
        if ok then observations[row]=result else errors[row]=type(result)=="table" and result or tostring(result) end
    end
    local function bytes(a,n)
        local b=memory.read_bytes_as_array(a,n,BUS); local t={}
        for i=1,n do t[i]=string.format("%02x",b[i]) end; return table.concat(t)
    end
    local function read(a) return u32(memory.read_u32_le(a,BUS)) end
    local function symbol(name) return need(title.symbols[name],"symbol:"..name).address end
    local function site(name)
        for id,s in pairs(title.sites) do if s.symbol==name then local t=clone(s); t.id=id; return t end end
        error({open="site:"..name},0)
    end
    local function resident(id) return M.resident(title,read,id) end
    local function register(s,cb,name,validate)
        if validate~=false then M.validate_site(title,s,bytes,resident) end
        local h=event.on_bus_exec(function(...)
            local good,why=pcall(cb,...)
            if not good then callback_errors=callback_errors+1; callback_error_detail=tostring(why) end
        end,s.address,name,BUS)
        check(M.valid_handle(h),"exec registration returned zero GUID: "..name); owned[h]=true; return h
    end
    local function remove(h)
        local ok,v=pcall(event.unregisterbyid,h)
        check(ok and v~=false,"unregister failed: "..tostring(h)); owned[h]=nil
    end
    local histogram,phase={},"boot"
    local phase_monitor
    local changes,causes,prior={}, {},{}
    local table_transitions,prior_raw={},nil
    local census_enabled=false
    local function snapshot()
        local t=title.overlay_table; local now,raw={},{}
        for r=0,t.regions-1 do for i=0,t.per_region-1 do
            local p=t.address+(r*t.per_region+i)*t.entry_size
            local id,active=read(p+t.id_off),read(p+t.active_off)
            raw[#raw+1]=string.format("%08x%08x",id,active)
            if active~=0 then now[r..":"..id]={region=r,id=id} end
        end end
        local current=table.concat(raw)
        if current~=prior_raw then table_transitions[#table_transitions+1]={frame=emu.framecount(),before=prior_raw,after=current} end
        prior_raw=current
        for key,v in pairs(now) do if not prior[key] then
            changes[#changes+1]={frame=emu.framecount(),region=v.region,id=v.id,kind="load"}
        end end
        for key,v in pairs(prior) do if not now[key] then
            changes[#changes+1]={frame=emu.framecount(),region=v.region,id=v.id,kind="unload"}
        end end
        prior=now
    end
    local phase_valid,save_driver_trace
    local function step(buttons)
        if phase_monitor then phase_monitor.before() end
        joypad.set(buttons or {}); emu.frameadvance()
        advanced=advanced+1
        if save_driver_trace then
            local witness=M.save_driver_witness(title,read,function(a) return memory.read_u8(a,BUS) end,emu.framecount())
            if witness then save_driver_trace[#save_driver_trace+1]=witness end
        end
        if phase_monitor then phase_monitor.after() end
        if census_enabled then snapshot() end
        local observed=phase
        if phase=="route-unverified" and phase_valid then
            for _,label in ipairs({"battle","save","menu","overworld"}) do
                if phase_valid(label) then observed=label; break end
            end
        end
        if phase~="route-unverified" and phase_valid and not phase_valid(phase) then observed="unverified" end
        local pc=u32(emu.getregister("ARM9 r15")); local h=histogram[observed] or {}; histogram[observed]=h
        local key=string.format("%08x",pc); h[key]=(h[key] or 0)+1
    end
    local function idle(n,fast)
        for _=1,n do
            if fast then joypad.set({}); emu.frameadvance(); advanced=advanced+1 else step() end
        end
    end
    local function idle_field()
        local fs,sp=read(symbol("sFieldSysPtr")),read(symbol("sSaveDataPtr"))
        if fs==0 or sp==0 then return false end
        local p=need(title.profile.probe_field,"profile.probe_field offsets")
        for _,key in ipairs({"sub","save","task","live","launched_app","field_app","paused","save_driver","save_driver_data_off","save_state"}) do
            need(p[key],"profile.probe_field."..key)
        end
        local sub=read(fs+p.sub)
        if not (sub~=0 and read(fs+p.save)==sp and read(fs+p.task)==0 and read(fs+p.live)~=0
            and read(sub+p.launched_app)==0 and read(sub+p.field_app)~=0 and read(sub+p.paused)==0) then return false end
        local driver=read(fs+p.save_driver); if driver==0 then return false end
        local data=read(driver+p.save_driver_data_off)
        return data~=0 and memory.read_u8(data+p.save_state,BUS)==1
    end
    phase_valid=function(label)
        if label=="boot" or label=="route-unverified" then return true end
        if label=="overworld" then return idle_field() end
        local p=title.profile.probe_field
        local fs=read(symbol("sFieldSysPtr")); if fs==0 then return false end
        local sub=read(fs+need(p.sub,"profile.probe_field.sub")); if sub==0 then return false end
        local battle=site("BtlCmd_TryFaintMon")
        if label=="battle" then return resident(battle.overlay_id) end
        if label=="menu" then return not resident(battle.overlay_id) and
            (read(fs+p.task)~=0 or read(sub+p.launched_app)~=0) end
        if label=="save" or label=="script" then
            if read(sub+p.launched_app)~=0 then return false end
            local driver=read(fs+need(p.save_driver,"profile.probe_field.save_driver"))
            if driver==0 then return false end
            local data=read(driver+p.save_driver_data_off); if data==0 then return false end
            local state=memory.read_u8(data+p.save_state,BUS)
            if label=="save" then return state>=2 and state<=7 end
            return state==1 and read(fs+p.task)~=0
        end
        return false
    end
    local function array_addr(id)
        local save=read(symbol("sSaveDataPtr")); local g=title.profile.save
        check(save~=0 and id>=0 and id<g.array_header_count,"invalid SaveArray pointer/id")
        local h=save+g.array_headers_off+id*g.array_header_size
        check(read(h+g.array_header_fields.id)==id,"runtime SaveArray header ID mismatch")
        local offset,size=read(h+g.array_header_fields.offset),read(h+g.array_header_fields.size)
        check(size>0 and offset+size<=g.dynamic_region_size,"runtime SaveArray extent")
        return save+g.dynamic_region_off+offset,size
    end
    local bridge_driver,bridge_sequence,pc_cycle_done=nil,0,false
    local bridge_gaps={}
    local function bridge_play(name)
        if name=="boot_continue_to_overworld" then
            local x=M.boot("bridge",cfg.boot_frames,idle_field,function()
                local fs=read(symbol("sFieldSysPtr")); return fs~=0 and read(fs+title.profile.probe_field.live)~=0
            end,step,emu.framecount)
            check(x.overworld,"bridge CONTINUE did not reach idle field"); return
        end
        if name=="pc_withdraw_box_mon" then
            bridge_gaps[#bridge_gaps+1]="PC withdrawal has no verified route-engine leg"; return
        end
        if name:match("^pc_") then
            check(pc_cycle_done,"PC subleg requested before a completed deposit cycle"); return
        end
        if not bridge_driver then
            SLINK_GEN4_ROUTE_LIBRARY=true
            local ok,driver=pcall(dofile,root.."/lua/tests/gen4_route_play.lua")
            SLINK_GEN4_ROUTE_LIBRARY=nil
            check(ok,"route library load failed: "..tostring(driver)); bridge_driver=driver
        end
        for attempt=1,12 do
            bridge_sequence=bridge_sequence+1
            local request={id=bridge_sequence,leg=name,position=bridge_driver.position(title)}
            local f=assert(io.open(need(cfg.bridge_request,"bridge:request path"),"w"))
            f:write(assert(json.encode(request))); f:close()
            local reply
            for _=1,12000 do
                local input=io.open(need(cfg.bridge_response,"bridge:response path"),"rb")
                if input then local value=json.decode(input:read("a")); input:close()
                    if value and value.id==request.id then reply=value; break end
                end
                step({})
            end
            need(reply,"bridge:host planner response timeout")
            if reply.open then error({open=reply.open},0) end
            check(not reply.error,"bridge planner failed: "..tostring(reply.error))
            local context={route=reply.route,title=title,step=step,env={G4_REPO=root,G4_LANE=cfg.bridge_lane,G4_TAG="bridge-"..bridge_sequence}}
            local ok,result=pcall(bridge_driver.run,context)
            check(not ok and type(result)=="table" and result.route_result,"route library failed: "..tostring(result))
            result=result.route_result
            observations.bridge=observations.bridge or {}; observations.bridge[#observations.bridge+1]=result
            if result.status=="BATTLE" and name=="gen4_routes:battle_settled" then return end
            if result.status=="PC_DEPOSIT" then
                result.covered_legs={"gen4_pc:reach_pc_terminal","pc_open_storage","pc_deposit_first_party_mon","pc_exit_app"}
                pc_cycle_done=true; return
            end
            check(result.status=="RESYNC","route bridge status "..result.status..": "..result.detail)
        end
        error({open="bridge:route resync limit reached for "..name},0)
    end
    local function play_route(route)
        for _,leg in ipairs(route or {}) do
            if leg.bridge then
                phase="route-unverified"; bridge_play(leg.bridge)
            elseif leg.steps then
                phase="route-unverified"
                M.play_recipe(leg,step,function(p) return M.predicate(title,read,p) end)
            else
            local buttons={}; for _,button in ipairs(leg.buttons or {}) do
                check(({A=true,B=true,X=true,Y=true,Start=true,Select=true,Up=true,Down=true,Left=true,Right=true,L=true,R=true})[button],"non-button route input")
                buttons[button]=true
            end
            phase="route-unverified"
            if leg.phase then phase=leg.phase end -- verified each frame against pack field/overlay predicates
            check(type(leg.frames)=="number" and leg.frames%1==0 and leg.frames>0 and leg.frames<=12000,"route frame bound")
            for _=1,leg.frames do step(buttons) end
            end
        end
    end
    local ok,fatal=pcall(function()
        pack=read_json(cfg.profile)
        check(pack.schema=="gen4-profile-v1","profile schema")
        title=need(pack.titles[cfg.title],"profile title:"..cfg.title)
        check(title.rom.sha1:lower()==cfg.rom_sha1:lower() and title.rom.md5:lower()==cfg.rom_md5:lower(),"profile/file hash mismatch")
        emu.limitframerate(true); client.speedmode(cfg.requested_rate)
        guarded("g",function()
            local domains={}; for _,name in pairs(memory.getmemorydomainlist()) do domains[name]=memory.getmemorydomainsize(name) end
            local registers=emu.getregisters()
            local accepted,v=pcall(emu.getregister,"ARM9 no_such_register")
            local safe=pcall(M.read_register,registers,emu.getregister,"ARM9 no_such_register")
            return {domains=domains,registers=registers,bogus_refused=not safe,
                raw_core_bogus_accepted=accepted,raw_core_bogus_value=accepted and v or nil,
                refusal_owner="probe register-name guard (production NDS binding must retain this guard)"}
        end)
        guarded("j",function() return {hash=gameinfo.getromhash(),sha1=cfg.rom_sha1,md5=cfg.rom_md5} end)
        if cfg.mode=="patched-rom" then return end -- hash control needs no CONTINUE/new-game route
        -- Boot census has its own bounded hook set; never overlaps the bench set.
        local census_handles={}
        guarded("c",function()
            for _,entry in ipairs({{"HandleLoadOverlay","load"},{"UnloadOverlayByID","unload"}}) do
                local s=site(entry[1]); local kind=entry[2]
                -- Boot instrumentation precedes ARM9 decompression. Pin the declared
                -- image independently from the ROM before registration, then require
                -- the full RAM pin on every execution. This is not the production
                -- warm registration path exercised by a/b/n.
                local file_pin=need(cfg.census_image_bytes and cfg.census_image_bytes[entry[1]],"c:declared-image FILE pin before bootstrap")
                M.validate_site(title,s,function(a,n)
                    check(a==s.address and n==s.extent,"declared-image FILE read extent"); return file_pin
                end,function() return true end)
                census_handles[#census_handles+1]=register(s,function(a,v,flags)
                    if not M.capture(s,a,v,flags,emu.getregister("ARM9 r15"),resident) then return end
                    M.validate_site(title,s,bytes,resident)
                    causes[#causes+1]={frame=emu.framecount(),id=u32(emu.getregister("ARM9 r0")),region=0,kind=kind,
                        source=entry[1]..":"..s.id}
                end,"g4c."..kind,false)
            end
            -- hge needs explicit pinned internal entry sites; no numeric allowance.
            for _,entry in ipairs(cfg.internal_loads or {}) do
                local s=site(entry.symbol)
                check(type(entry.source)=="string" and entry.source~="","internal loader source required")
                local pin=need(cfg.census_image_bytes[entry.symbol],"c:internal loader declared-image FILE pin")
                M.validate_site(title,s,function() return pin end,function() return true end)
                census_handles[#census_handles+1]=register(s,function(a,v,flags)
                    if not M.capture(s,a,v,flags,emu.getregister("ARM9 r15"),resident) then return end
                    M.validate_site(title,s,bytes,resident)
                    local id=M.internal_load_id(entry,function(name)
                        return M.read_register(emu.getregisters(),emu.getregister,name)
                    end)
                    if id==nil then return end
                    causes[#causes+1]={frame=emu.framecount(),id=id,region=entry.region,kind="load",source=entry.source}
                end,"g4c.internal."..entry.symbol,false)
            end
            check(#census_handles<=4,"census hook budget")
            census_enabled=true
            return {jit=cfg.jit,use_real_time=cfg.use_real_time,changes=changes,causes=causes,table_transitions=table_transitions,
                pin_timing="declared-image FILE before boot registration; full RAM pin at every callback"}
        end)
        local boot_ok=false
        guarded("l",function()
            local x=M.boot(cfg.mode,cfg.boot_frames,idle_field,function()
                local fs=read(symbol("sFieldSysPtr")); if fs==0 then return false end
                local p=need(title.profile.probe_field,"l:pack field offsets")
                return read(fs+need(p.live,"l:pack live field offset"))~=0
            end,step,emu.framecount)
            boot_ok=x.overworld; return x
        end)
        guarded("k",function()
            return M.sample_rtc(title,cfg.rtc_sample_frame,step,emu.framecount,bytes)
        end)
        if cfg.mode=="cold-reload" then
            check(boot_ok and idle_field(),"cold readback not at idle overworld")
            guarded("i",function()
                local p=need(cfg.cold_readback,"i:cold readback descriptor")
                local addr,size=array_addr(p.array_id)
                check(p.record_offset+#p.before_hex/2<=size,"cold record extent")
                return {runtime_hex=bytes(addr+p.record_offset,#p.before_hex/2),operation="cold-reload"}
            end)
            return
        end
        if cfg.mode=="persistence" then
            check(boot_ok,"persistence CONTINUE did not reach verified overworld")
            guarded("i",function()
                local p=need(cfg.persistence,"i:independently encoded mutation")
                local addr,size=array_addr(p.array_id); addr=addr+p.record_offset
                check(p.record_offset>=0 and p.record_offset+#p.before_hex/2<=size,"record outside runtime SaveArray")
                check(bytes(addr,#p.before_hex/2)==p.before_hex,"runtime record differs from independently decoded save preimage")
                check(memory.read_u16_le(addr+p.flags_offset,BUS)&3==0,"locked representation refused")
                local modified
                if p.box then
                    local base=array_addr(p.array_id)
                    local off=title.profile.pc.box_modified_flag_off
                    modified=off and base+off or nil
                end
                local modified_before=modified and read(modified)
                if p.write then
                    check(idle_field(),"persistence mutation outside idle overworld")
                    for _,change in ipairs(p.changes) do
                        check(change.offset>=0 and change.offset<#p.before_hex/2,"mutation byte outside record")
                        memory.write_u8(addr+change.offset,change.value,BUS)
                    end
                    if modified and p.dirty then memory.write_u32_le(modified,read(modified)|(1<<p.box),BUS) end
                    check(bytes(addr,#p.after_hex/2)==p.after_hex,"record mutation readback mismatch")
                end
                local finished=0; local s=site("Save_WriteManFinish")
                local h=register(s,function(a,v,flags)
                    if M.capture(s,a,v,flags,emu.getregister("ARM9 r15"),resident) then finished=finished+1 end
                end,"g4i.native-save")
                save_driver_trace={need(M.save_driver_witness(title,read,function(a) return memory.read_u8(a,BUS) end,emu.framecount()),"i:save-driver initial state")}
                play_route(need(cfg.persistence_route,"i:native SAVE normal-button route")); idle(120); remove(h)
                check(finished>0,"no native save-finish execution")
                local trace=save_driver_trace; save_driver_trace=nil
                check(M.save_completed(trace),"native save-driver did not transition active to idle")
                return {runtime_hex=bytes(addr,#p.before_hex/2),save_finish_hits=finished,operation=p.operation,
                    save_driver_trace=trace,modified_before=modified_before,modified=modified and read(modified),level="INSTRUMENTATION"}
            end)
            return
        end
        if cfg.mode~="baseline" then return end
        if errors.l then error(errors.l,0) end
        check(boot_ok,"CONTINUE did not reach verified overworld")
        phase="overworld"; local quiet_before=#changes; idle(cfg.sample_frames)
        if observations.c then observations.c.quiet_changes=#changes-quiet_before end
        if observations.c then
            local stats={loads=0,unloads=0,newly_active_ids=0,residency_changes=#changes,table_transitions=#table_transitions}
            for _,v in ipairs(causes) do if v.kind=="load" then stats.loads=stats.loads+1 else stats.unloads=stats.unloads+1 end end
            for _,v in ipairs(changes) do if v.kind=="load" then stats.newly_active_ids=stats.newly_active_ids+1 end end
            observations.c.counts=stats
        end
        for _,h in ipairs(census_handles) do remove(h) end; census_enabled=false
        guarded("h",function()
            local p=read(symbol("sSaveDataPtr")); local fs=read(symbol("sFieldSysPtr"))
            local witness=need(cfg.save_witness,"h:independent source-save witness offsets")
            local geom=title.profile.save
            local spec=p+geom.slot_specs_off
            local footer=p+geom.dynamic_region_off+read(spec+geom.slot_spec_fields.offset)
                +read(spec+geom.slot_spec_fields.size)-geom.chunk_footer.size
            local signature=bytes(footer+witness.signature_footer_offset,#witness.signature_hex/2)
            local trainer=need(title.profile.trainer,"profile.trainer verified identity offsets")
            local header=p+geom.array_headers_off+trainer.array_id*geom.array_header_size
            local trainer_addr=p+geom.dynamic_region_off+read(header+geom.array_header_fields.offset)+trainer.profile_off_in_array
            local identity=bytes(trainer_addr,#witness.identity_hex/2)
            local field_save=read(fs+title.profile.probe_field.save)
            check(M.save_witness_ok(title,p,field_save,signature,identity,witness),"SaveData page/identity/provenance refusal")
            local bogus=clone(title); bogus.profile.save_ptr.symbol="gSystem"
            local bad_sig=signature:sub(1,-3)..(signature:sub(-2)=="00" and "01" or "00")
            return {pointer=p,field_save=read(fs+title.profile.probe_field.save),signature=signature,
                expected_signature=witness.signature_hex,identity=identity,expected_identity=witness.identity_hex,
                invalid_rejected=not M.save_witness_ok(title,0,field_save,signature,identity,witness),
                signature_rejected=not M.save_witness_ok(title,p,field_save,bad_sig,identity,witness),
                provenance_rejected=not M.save_witness_ok(bogus,p,field_save,signature,identity,witness)}
        end)
        guarded("a",function()
            local x={negative_hits=0}; local handles={}
            for _,entry in ipairs({{"OS_WaitIrq","arm"},{"VBlankCB_DmaTasksFramecounter","thumb"}}) do
                local s=site(entry[1]); local v={frames=cfg.sample_frames,hits=0,badpc=0,badword=0}; x[entry[2]]=v
                handles[#handles+1]=register(s,function(a,val)
                    v.hits=v.hits+1
                    if u32(a)~=s.address or u32(emu.getregister("ARM9 r15"))~=s.address+(s.mode=="thumb" and 4 or 8) then v.badpc=v.badpc+1 end
                    if u32(val)~=word(s.fire_hex) then v.badword=v.badword+1 end
                end,"g4a."..entry[2])
            end
            handles[#handles+1]=register(site("DoSoftReset"),function() x.negative_hits=x.negative_hits+1 end,"g4a.negative")
            idle(cfg.sample_frames); for _,h in ipairs(handles) do remove(h) end; return x
        end)
        guarded("d",function()
            need(event.on_bus_write,"API:event.on_bus_write")
            local offset=need(title.profile.system.vblank_counter_off,"profile.system.vblank_counter_off")
            local addr=symbol("gSystem")+offset
            local hits,wrong,timing=0,0,{}
            local h=event.on_bus_write(function(_,v)
                hits=hits+1; local current=memory.read_u8(addr,BUS)
                timing[current==(u32(v)&255) and "after" or "before"]=true
            end,addr,"g4d.store",BUS)
            check(M.valid_handle(h),"write hook zero GUID"); owned[h]=true
            local wrong_addr=need(title.profile.probe_wrong_write_offset,"profile.probe_wrong_write_offset")+symbol("gSystem")
            local w=event.on_bus_write(function() wrong=wrong+1 end,wrong_addr,"g4d.wrong",BUS)
            check(M.valid_handle(w),"negative write hook zero GUID"); owned[w]=true
            M.host_write_control(function(a) return memory.read_u8(a,BUS) end,
                function(a,v) memory.write_u8(a,v,BUS) end,addr)
            local host=hits
            idle(cfg.sample_frames); remove(h); remove(w)
            return {hits=hits,timing=count(timing)==1 and next(timing) or "ambiguous",host_hits=host,wrong_hits=wrong}
        end)
        guarded("e",function()
            local n,kept=0,0; local s=site("OS_WaitIrq")
            local h=register(s,function() n=n+1 end,"g4e.remove")
            local live=register(s,function() kept=kept+1 end,"g4e.keep")
            idle(60); local before=n; remove(h); n=0; idle(60); local removed=n
            need(savestate and savestate.save,"API:savestate.save")
            local path=need(cfg.state_path,"e:private savestate path")
            savestate.save(path); savestate.load(path); idle(60)
            local live_before=kept; idle(60)
            remove(live); return {before=before,removed=removed,reloaded=n,kept=kept-live_before}
        end)
        guarded("f",function()
            if cfg.skip_perf_reason then error({open="f:performance not rerun: "..cfg.skip_perf_reason},0) end
            local request=need(cfg.perf_request,"f:coordinator process inventory handshake")
            local marker=assert(io.open(request,"w")); marker:write("ready\n"); marker:close()
            local deadline=os.time()+20
            local inventory
            repeat
                local response=io.open(cfg.perf_response,"rb")
                if response then local raw=response:read("a"); response:close(); inventory=assert(json.decode(raw))
                else idle(1,true) end
            until inventory or os.time()>=deadline
            need(inventory,"f:process inventory response absent")
            if #inventory.foreign_pids>0 then error({open="f:concurrent load; foreign EmuHawk PIDs "..table.concat(inventory.foreign_pids,",")},0) end
            local candidates={"OS_WaitIrq","VBlankCB_DmaTasksFramecounter","DoSoftReset","Task_Blackout","Main_RunOverlayManager"}
            local fps={}
            emu.limitframerate(false); client.speedmode(cfg.requested_rate)
            local handles={}
            for hooks=0,5 do
                if hooks>0 then handles[hooks]=register(site(candidates[hooks]),function() end,"g4f."..hooks) end
                local start=os.clock(); idle(cfg.sample_frames,true); fps[hooks+1]=cfg.sample_frames/(os.clock()-start)
            end
            remove(handles[5]); handles[5]=nil
            local start=os.clock(); idle(cfg.sample_frames,true); local restored_four=cfg.sample_frames/(os.clock()-start)
            check(cfg.phase_max>=1 and cfg.phase_max<=3,"production hook cap exceeds D6")
            for i=4,cfg.phase_max+1,-1 do remove(handles[i]); handles[i]=nil end
            start=os.clock(); idle(cfg.sample_frames,true); local restored_production=cfg.sample_frames/(os.clock()-start)
            for _,h in ipairs(handles) do remove(h) end
            start=os.clock(); idle(cfg.sample_frames,true); local restored=cfg.sample_frames/(os.clock()-start)
            -- gen4-PERF will produce actual per-frame full-client samples. Neither
            -- a config-supplied array nor the withdrawn average-only 3-hook test
            -- is PHYSICAL sustained evidence.
            return {fps=fps,restored=restored,restored_four=restored_four,restored_production=restored_production,
                legacy_cap_fps=fps[cfg.phase_max+1],legacy_above_cap_hooks=cfg.phase_max+1,legacy_above_cap_fps=fps[cfg.phase_max+2],
                criterion="OWNER: sustained full-client 1x at 0 hooks and 1 on-demand; curve is characterization only",
                curve_evidence="CHARACTERIZATION",production_steady_hooks=0,production_on_demand_max=1,
                phase_max=cfg.phase_max,
                requested_rate=cfg.requested_rate,process_inventory=inventory}
        end)
        guarded("n",function() return {model=M.phase_controls(dofile(root.."/lua/hook_registry.lua"))} end)
        -- Battle and save routes are coordinator-supplied normal inputs. Labels alone
        -- are never phase proof: verify the pack's predicate before including a census.
        local b={accepted=0,dropped=0,callback_corrupt=0}
        guarded("b",function()
            if cfg.phase_case then error({open="b:separate phase-budget run; faint observer not armed"},0) end
            need(cfg.route and #cfg.route>0 and true or nil,"b:normal-input battle/faint/collision route")
            local s=site("BtlCmd_TryFaintMon")
            local inactive=function() return false end
            b.inactive_drop=M.capture(s,s.address,0,0,s.address,inactive)==nil
            b.active_fault=not pcall(M.capture,s,s.address,word(s.fire_hex)~1,0,s.address+(s.mode=="thumb" and 4 or 8),function() return true end)
            local corrupt=clone(s); corrupt.register_hex=corrupt.register_hex:sub(1,-3)..(corrupt.register_hex:sub(-2)=="00" and "01" or "00")
            b.full_pin_reject=not pcall(M.validate_site,title,corrupt,function() return s.register_hex end,function() return true end)
            register(s,function(a,val,flags)
                M.observe_overlay(b,s,a,val,flags,emu.getregister("ARM9 r15"),bytes,resident)
            end,"g4b.faint")
            return b
        end)
        -- One phase case per fresh boot keeps the independent always-on producer
        -- observer + phase registry within four external handles. It falsifies a
        -- late activation predicate rather than excusing the one-frame table lag.
        guarded("n",function()
            local result=observations.n or {model=M.phase_controls(dofile(root.."/lua/hook_registry.lua"))}
            local case=need(cfg.phase_case,"n:normal-input phase case (static PC and reset cases required)")
            local predicate=need(case.predicate,"n:executable pack phase predicate")
            check(case.source and case.source~="","phase predicate source required")
            local settle_policy=need(cfg.phase_settle,"n:measured overlay settle policy for this title")
            check(settle_policy.max_frames==settle_policy.measured_max+settle_policy.margin
                and settle_policy.max_frames>0,"invalid settle policy")
            local image_pins=need(cfg.phase_image_pins,"n:other-image FILE pins")
            local settle={current={},samples={}}
            local producer=clone(need(title.sites[case.producer_site],"n:independent producer site")); producer.id=case.producer_site
            local sites={}; for _,id in ipairs(case.sites) do local s=clone(need(title.sites[id],"n:phase site:"..id)); s.id=id; sites[#sites+1]=s end
            check(#sites>0 and #sites+1<=4,"producer observer + phase handle budget")
            local baseline_start=os.clock(); idle(cfg.sample_frames,true); local baseline=cfg.sample_frames/(os.clock()-baseline_start)
            local oracle,seen={},{}
            local active
            local h=register(producer,function(a,v,flags)
                -- The oracle does not reuse the composition's residency gate. It
                -- sees a producer inside its caller predicate even if the overlay
                -- table lags. Reusing M.capture here would hide the same first hit
                -- from both sides and falsely pass a late arm.
                if active() and bytes(producer.address,producer.extent)==producer.register_hex then
                    check(u32(a)==producer.address and u32(v)==word(producer.fire_hex),"independent producer address/word")
                    check(u32(emu.getregister("ARM9 r15"))==producer.address+(producer.mode=="thumb" and 4 or 8),"independent producer PC")
                    oracle[#oracle+1]=emu.framecount()
                end
            end,"g4n.oracle")
            local binding={validate=function(s) return M.validate_site(title,s,bytes,resident) end,
                register=function(s,cb,name) return register(s,cb,name,false) end,
                unregister=function(handle) remove(handle); return true end,
                capture=function(s,a,v,flags)
                    local e=M.capture(s,a,v,flags,emu.getregister("ARM9 r15"),resident)
                    if e then M.validate_site(title,s,bytes,resident); e.frame=emu.framecount() end; return e
                end}
            local composite=M.composite(dofile(root.."/lua/hook_registry.lua"),binding)
            local armed=false
            active=function()
                return M.predicate(title,read,predicate)
            end
            local pending_at_close=0
            phase_monitor={before=function()
                -- Poll the table even before the caller predicate turns true so
                -- the bounded wait starts at the observed residency transition.
                local wanted=active()
                local ready=M.phase_sites_ready(sites,bytes,resident,emu.framecount(),settle,settle_policy,image_pins,wanted)
                local enabled=wanted and ready
                if enabled and not armed then composite:enter(case.name,sites); armed=true
                elseif not enabled and armed then
                    pending_at_close=pending_at_close+composite.phases[case.name]:status().pending
                    composite:leave(case.name); armed=false
                end
            end,after=function()
                -- Deliberately retain the event at a phase-exit boundary until leave
                -- exercises the physical drain-before-close path in the next pre-pump.
                if active() or not armed then
                    for _,e in ipairs(composite:drain()) do if e.id==case.producer_site then seen[#seen+1]=e.frame end end
                end
                check(not composite.failure,"phase composite fault: "..tostring(composite.failure))
                check(composite:live_handles()+1<=4,"physical observer + phase budget")
            end,finish=function()
                for _,reg in pairs(composite.phases) do pending_at_close=pending_at_close+reg:status().pending end
                composite:close()
                for _,e in ipairs(composite:drain()) do if e.id==case.producer_site then seen[#seen+1]=e.frame end end
                local second_drain=#composite:drain()
                remove(h)
                local before=os.clock(); idle(cfg.sample_frames,true); local restored=cfg.sample_frames/(os.clock()-before)
                local maxcost=0; for _,cost in ipairs(composite.costs) do maxcost=math.max(maxcost,cost) end
                local matched=#oracle==#seen
                for i,f in ipairs(oracle) do if seen[i]~=f then matched=false end end
                result.physical={first_expected=#oracle,first_seen=matched and #seen or 0,last_expected=#oracle,last_seen=matched and #seen or 0,
                    static_pc=case.name=="pc" and producer.image=="arm9",reset=case.name=="reset",peak=composite.peak+1,
                    live_after_close=composite:live_handles(),max_cost=maxcost,restored_fps=restored,baseline_fps=baseline,
                    pending_at_close=pending_at_close,second_drain=second_drain,
                    oracle_frames=oracle,seen_frames=seen,phase=case.name,predicate_source=case.source}
                result.physical.cases={clone(result.physical)}
                result.physical.bridge_gaps=clone(bridge_gaps)
                result.physical.settle={policy=clone(settle_policy),samples=clone(settle.samples)}
            end}
            return result
        end)
        play_route(cfg.route)
        if phase_monitor then local monitor=phase_monitor; phase_monitor=nil; monitor.finish() end
        guarded("m",function()
            local halt=symbol("OS_Halt"); local idlehist=histogram.overworld or {}
            local pc=string.format("%08x",halt+0xC) -- measured idle-thread instruction is base+4, PC pipeline +8
            local saved=histogram.save
            return {histograms=histogram,halt=halt,idle_hits=idlehist[pc] or 0,
                save_same_as_idle=saved and M.same_distribution(saved,idlehist)}
        end)
    end)
    if not ok then
        if type(fatal)~="table" or not fatal.open then
            -- An active phase/route fault must not be softened to OPEN merely
            -- because its partially collected observation already exists.
            errors[phase_monitor and "n" or "m"]=tostring(fatal)
        end
        for row in ROWS:gmatch(".") do if not observations[row] and not errors[row] then errors[row]=fatal end end
    end
    local cleanup_error
    for h in pairs(owned) do local good,why=pcall(remove,h); if not good then cleanup_error=tostring(why) end end
    local lines,overall={},"PASS"
    for row in ROWS:gmatch(".") do
        local status,why=M.evaluate(row,observations[row])
        if errors[row] then
            status=type(errors[row])=="table" and errors[row].open and "OPEN" or "FAIL"
            why=type(errors[row])=="table" and errors[row].open or tostring(errors[row])
        end
        if cleanup_error then status="FAIL"; why="retained handles: "..cleanup_error end
        if callback_errors>0 then status="FAIL"; why="callback fault: "..tostring(callback_error_detail) end
        if status=="FAIL" then overall="FAIL" elseif status=="OPEN" and overall=="PASS" then overall="OPEN" end
        local payload={schema="gen4-probe-row-v1",run_id=cfg.run_id,title=cfg.title,rom_sha1=cfg.rom_sha1,
            level="PHYSICAL",mode=cfg.mode,reason=why,observation=observations[row],requested_rate=cfg.requested_rate,
            source_head=cfg.source_head,script_sha256=cfg.code_sha256,profile_sha256=cfg.profile_sha256,callback_errors=callback_errors}
        payload.module_sha256=cfg.module_sha256; payload.surface_sha256=cfg.surface_sha256; payload.receipt_kind=cfg.receipt_kind
        payload.setup=cfg.setup or "NATIVE"; payload.sidecar_sha256=cfg.sidecar_sha256
        payload.setup_src_sha1=cfg.src_sha1; payload.setup_out_sha1=cfg.out_sha1
        payload.setup_new_pid=cfg.new_pid
        payload.advanced_frames=advanced; payload.elapsed_clock_seconds=os.clock()-started
        payload.achieved_fps=advanced/math.max(0.001,payload.elapsed_clock_seconds)
        lines[#lines+1]="PROBE "..row.." "..status.." "..assert(json.encode(payload))
    end
    lines[#lines+1]="RESULT: "..overall
    local f=assert(io.open(out,"w"),"cannot publish probe receipt: "..out)
    f:write(table.concat(lines,"\n"),"\n"); f:close(); pcall(client.exit)
end
if SLINK_GEN4_PROBE_TEST then return M end
run()
return M
