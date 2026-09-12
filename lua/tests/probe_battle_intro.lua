-- Does pressing A during the wild-battle intro delay DisplayBattleMenu? Two battles: idle vs A-mash. Harness only.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
package.path=ROOT.."/lua/?.lua;"..ROOT.."/lua/tests/?.lua;"..package.path
local G=dofile(ROOT.."/lua/tests/gen1_gatelib.lua")
local t=G.start("probe_battle_intro")
local JSON=require("json_codec")
local f=assert(io.open(assert(os.getenv("SLINK_PROBE_INPUT")),"r"));local cfg=assert(JSON.decode(f:read("*a")));f:close()
local u8=function(a)return memory.read_u8(a,"System Bus")end
local menu_frames={}
event.on_bus_exec(function()if u8(0xFFB8)==0x0F then menu_frames[#menu_frames+1]=emu.framecount()end end,cfg.menu_pc,"probe-menu","System Bus")
local flags=u8(cfg.status_flags4);if math.floor(flags/16)%2==1 then memory.write_u8(cfg.status_flags4,flags-16,"System Bus")end
local function step(b)if b then joypad.set(b)end;emu.frameadvance()end
local function enter()
    local dirs={"Up","Down"}
    for _,side in ipairs({"Left","Right","Left","Right"})do
        for _=1,20 do step({[side]=true})end
        for i=1,150 do local d=dirs[(i%2)+1];for _=1,20 do step({[d]=true});if u8(cfg.in_battle)~=0 then return true end end end
    end
    return false
end
local out={}
for _,mode in ipairs({"idle","mash_a"})do
    local ok=enter();local start=emu.framecount();local base=#menu_frames
    for _=1,2400 do
        if #menu_frames>base then break end
        if mode=="mash_a" then for _=1,3 do step({A=true})end;for _=1,10 do step(nil)end else step(nil)end
    end
    local delay=(#menu_frames>base) and (menu_frames[base+1]-start) or -1
    out[mode]={entered=ok,start=start,menu_delay_frames=delay,joy_ignore=u8(cfg.joy_ignore)}
    t.log(mode..": "..JSON.encode(out[mode]))
    client.screenshot(cfg.out_dir.."/intro_"..mode..".png")
    -- end the battle: RUN = Right, Down, A from the menu (menu is up now); retry a few times
    for _=1,10 do
        if u8(cfg.in_battle)==0 then break end
        for _=1,6 do step({Right=true})end;for _=1,6 do step(nil)end;for _=1,6 do step({Down=true})end;for _=1,6 do step(nil)end;for _=1,3 do step({A=true})end
        for _=1,240 do step(nil);if u8(cfg.in_battle)==0 then break end end
        for _=1,3 do step({B=true})end;for _=1,10 do step(nil)end
    end
    for _=1,60 do step(nil)end
end
local o=assert(io.open(cfg.output,"w"));o:write(JSON.encode(out));o:close()
t.check("probe done",true);t.finish()
