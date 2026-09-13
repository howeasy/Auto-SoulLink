-- Test-only wrapper for the unchanged Manager launcher. Normal New Game keys
-- occur only on the already owned native boot-frame call; no extra frame is
-- advanced by this wrapper after the launcher starts.
local ROOT=assert(SLINK_ROOT or os.getenv("SLINK_ROOT"))
local JSON=dofile(ROOT.."/lua/json_codec.lua")
local function read(path)
    local file=assert(io.open(path,"r"));local value=assert(JSON.decode(file:read("*a")))
    file:close();return value
end
local input=read(assert(os.getenv("SLINK_SCRIPTED_INPUT")))
assert(input.schema=="gen1-scripted-normal-buttons-v1" and (input.player=="a" or input.player=="b")
    and (input.variant=="red" or input.variant=="blue" or input.variant=="yellow"))
assert(gameinfo.getromhash():lower()==input.rom_sha1,"scripted host booted a different cartridge")
local function publish(path,value)
    local file=assert(io.open(path..".tmp","w"))
    file:write(assert(JSON.encode(value)));file:close()
    os.remove(path)
    assert(os.rename(path..".tmp",path))
end
local idle={A=false,B=false,Start=false,Select=false,Up=false,Down=false,Left=false,Right=false}
local original_advance,original_yield=emu.frameadvance,emu.yield
local deadline=os.time()+input.deadline_seconds
local frames,beat,stopped=0,0,false
local function status_now()return SLINK_RUNTIME_STATUS and SLINK_RUNTIME_STATUS()end
local symbols={}
do
    local variant=input.variant
    local source=variant=="yellow"and"pokeyellow"or"pokered"
    local target=variant=="yellow"and"pokeyellow"or"pokeblue"
    if variant=="red"then target="pokered"end
    for line in io.lines(ROOT.."/.cache/pret/"..source.."/"..target..".sym")do
        local _,address,name=line:match("^(%x+):(%x+) (%S+)$")
        if address then symbols[name]=tonumber(address,16)end
    end
end
local function sym(name)return memory.read_u8(assert(symbols[name]),"System Bus")end
local function menu_inputs()
    beat=beat+1;local moment=beat%16
    local buttons={A=moment<2,Start=moment==8}
    if sym("wMaxMenuItem")==3 and sym("wTopMenuItemY")==2 and sym("wTopMenuItemX")==1 then
        buttons={Down=sym("wCurrentMenuItem")==0,A=sym("wCurrentMenuItem")>0 and moment<2}
    end
    local pressed={};for key,value in pairs(idle)do pressed[key]=buttons[key]or value end
    joypad.set(pressed)
end

publish(input.progress,{stage="wrapper-ready",player=input.player,frame=emu.framecount(),boot_frames=0})
local function wrapped_yield()
    local status=status_now()
    if status and (status.host and status.host.held or status.native_reattach)then joypad.set(idle)end
    return original_yield()
end
local function wrapped_advance()
    local status=assert(status_now(),"selected runtime status missing")
    if status.observation_loop then
        joypad.set(idle)
        if not stopped then
            stopped=true
            publish(input.progress,{stage="input-stopped",player=input.player,frame=emu.framecount(),boot_frames=frames})
        end
        if emu.frameadvance==wrapped_advance then emu.frameadvance=original_advance end
        if emu.yield==wrapped_yield then emu.yield=original_yield end
    else
        assert(os.time()<deadline and frames<input.max_boot_frames,"scripted New Game made no bounded progress")
        assert(status.phase=="waiting_for_overworld" and not status.native_reattach,
            "scripted input refused outside clean boot")
        assert(status.host and status.host.lease_owned and status.host.owner_id
            and (not status.context or status.host.owner_id==status.context.physical_instance)
            and not status.host.held,"scripted input requires the clean native owner")
        menu_inputs();frames=frames+1
        if frames%120==0 then
            publish(input.progress,{stage="normal-buttons",player=input.player,
                frame=emu.framecount(),boot_frames=frames})
        end
    end
    return original_advance()
end
emu.yield,emu.frameadvance=wrapped_yield,wrapped_advance
local ok,why=xpcall(function()dofile(input.launcher)end,debug.traceback)
if emu.frameadvance==wrapped_advance then emu.frameadvance=original_advance end
if emu.yield==wrapped_yield then emu.yield=original_yield end
if not ok then
    joypad.set(idle)
    publish(input.failure,{stage="failure",player=input.player,error=tostring(why),
        frame=emu.framecount(),boot_frames=frames})
    error(why)
end
