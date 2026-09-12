-- In-battle exec-callback probe (harness frameadvance only): which battle-core PCs fire during one real FIGHT turn?
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
package.path=ROOT.."/lua/?.lua;"..ROOT.."/lua/tests/?.lua;"..package.path
local G=dofile(ROOT.."/lua/tests/gen1_gatelib.lua")
local t=G.start("probe_battle_exec")
local JSON=require("json_codec")
local Driver=dofile(ROOT.."/lua/tests/gen1_battle_driver.lua")
local f=assert(io.open(assert(os.getenv("SLINK_PROBE_INPUT")),"r"));local cfg=assert(JSON.decode(f:read("*a")));f:close()
local u8=function(a)return memory.read_u8(a,"System Bus")end
local counts={}
for name,pc in pairs(cfg.pcs)do counts[name]={pc=pc,count=0,banks={},frames={}}
    event.on_bus_exec(function()local c=counts[name];c.count=c.count+1;local b=u8(0xFFB8);c.banks[tostring(b)]=(c.banks[tostring(b)]or 0)+1;if #c.frames<8 then c.frames[#c.frames+1]=emu.framecount()end end,pc,"probe-"..name,"System Bus")
end
local flags=u8(cfg.status_flags4);if math.floor(flags/16)%2==1 then memory.write_u8(cfg.status_flags4,flags-16,"System Bus")end
local function step(b)if b then joypad.set(b)end;emu.frameadvance()end
local drv=Driver.new({step=step,u8=u8,sites=cfg.driver.sites,addresses=cfg.driver.addresses})
local dirs={"Up","Down"};local entered=false
for _,side in ipairs({"Left","Right","Left","Right"})do
    for _=1,20 do step({[side]=true})end
    for i=1,150 do local d=dirs[(i%2)+1];for _=1,20 do step({[d]=true});if u8(cfg.in_battle)~=0 then entered=true;break end end;if entered then break end end
    if entered then break end
end
t.check("entered a wild battle",entered,"")
local menu;for _=1,200 do menu=drv.wait_menu(1);if menu.ok then break end;if drv.hits().display_battle_menu.count==0 then for _=1,3 do step({A=true})end end;for _=1,8 do step(nil)end end
t.check("battle menu up",menu.ok,JSON.encode(menu))
local ch=drv.choose("FIGHT");t.log("choose FIGHT: "..JSON.encode(ch))
local tr=drv.commit_move(1,900);t.log("commit_move: "..JSON.encode(tr))
for _=1,300 do step(nil)end
local out={counts=counts,menu=menu,choose=ch,commit=tr,hits=drv.hits(),in_battle=u8(cfg.in_battle)}
local o=assert(io.open(cfg.output,"w"));o:write(JSON.encode(out));o:close()
for name,c in pairs(counts)do t.log(string.format("%-28s %5d banks=%s frames=%s",name,c.count,JSON.encode(c.banks),JSON.encode(c.frames)))end
t.check("probe done",true);t.finish()
