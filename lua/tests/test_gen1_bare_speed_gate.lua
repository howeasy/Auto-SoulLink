-- Bare dual-Gambatte throughput probe.  This deliberately loads no SLink runtime,
-- journal, connector, observer, memory profile or gameplay helper: the measured
-- loop contains only BizHawk frame advancement and boundary timing.
local ROOT=assert(SLINK_ROOT or os.getenv("SLINK_ROOT"),"SLINK_ROOT required")
local JSON=dofile(ROOT.."/lua/json_codec.lua")
local clock=assert(dofile(ROOT.."/lua/platform_clock.lua").new())
local output=assert(os.getenv("SLINK_BARE_SPEED_OUTPUT"),"bare speed output required")
local player=assert(os.getenv("SLINK_BARE_SPEED_PLAYER"),"bare speed player required")

local TARGET=59.727500569606
local WINDOW=120
local WARMUP=120

local function measure(name,speed,frameskip,frames)
    assert(type(speed)=="number"and speed>=100 and type(frameskip)=="number"and frameskip>=0,
        "valid speed and frame skip required")
    assert(type(frames)=="number"and frames%WINDOW==0,"whole timing windows required")
    client.speedmode(speed)
    client.frameskip(frameskip)
    emu.minimizeframeskip(false)
    for _=1,WARMUP do emu.frameadvance()end
    local phase_start_frame,phase_start=emu.framecount(),clock()
    local windows=JSON.array()
    for index=1,frames/WINDOW do
        local first,started=emu.framecount(),clock()
        for _=1,WINDOW do emu.frameadvance()end
        local last,finished=emu.framecount(),clock()
        assert(last-first==WINDOW and finished>started,"bare timing window did not advance exactly")
        windows[#windows+1]={index=index,first_frame=first,last_frame=last,frames=last-first,
            seconds=finished-started,fps=(last-first)/(finished-started)}
    end
    local phase_end_frame,phase_end=emu.framecount(),clock()
    assert(phase_end_frame-phase_start_frame==frames and phase_end>phase_start,"bare phase did not advance exactly")
    local target=TARGET*speed/100
    return {name=name,speed=speed,frameskip=frameskip,first_frame=phase_start_frame,last_frame=phase_end_frame,
        frames=phase_end_frame-phase_start_frame,seconds=phase_end-phase_start,
        fps=(phase_end_frame-phase_start_frame)/(phase_end-phase_start),target_fps=target,windows=windows}
end

local function publish(value)
    local temporary=output..".tmp"
    local file=assert(io.open(temporary,"w"));file:write(assert(JSON.encode(value)));file:close()
    assert(os.rename(temporary,output))
end

local ok,result=xpcall(function()
    -- 1x renders every frame.  At 3x we measure the same setting first, then the
    -- minimum useful skip (render one, skip two) so the harness can report
    -- whether production actually needs a render concession.
    return {schema="rby-bare-gambatte-speed-v1",player=player,rom_hash=gameinfo.getromhash():lower(),
        phases=JSON.array({
            measure("one_x",100,0,600),
            measure("three_x_no_skip",300,0,1800),
            measure("three_x_skip_two",300,2,1800),
        })}
end,debug.traceback)
if ok then publish(result)else publish({schema="rby-bare-gambatte-speed-v1",player=player,error=tostring(result)})end
pcall(function()client.exitCode(ok and 0 or 1)end)
client.exit()
error("slink-bare-speed-finished",0)
