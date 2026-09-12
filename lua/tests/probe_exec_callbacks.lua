-- Which addresses does BizHawk's Gambatte bus-exec callback actually deliver? Overworld only, 240 frames.
-- Candidates (bank 0, all executed every frame): interrupt vector, jp target, call target, linear bytes.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
package.path=ROOT.."/lua/?.lua;"..package.path
local G=dofile(ROOT.."/lua/tests/gen1_gatelib.lua")
local t=G.start("probe_exec_callbacks")
local JSON=require("json_codec")
local P={vector_0040=0x0040,VBlank_jp_target_2024=0x2024,VBlank_plus3_linear_2027=0x2027,DelayFrame_call_target_20af=0x20af,DelayFrame_plus2_linear_20b1=0x20b1,
    OverworldLoop_jp_target_03ff=0x03ff,OverworldLoopLessDelay_0402=0x0402,Joypad_call_target_019a=0x019a,Bankswitch_call_target_35d6=0x35d6,CopyData_call_target_00b5=0x00b5,
    UpdateSprites_call_target_2429=0x2429,JoypadLowSens_call_target_3831=0x3831}
local counts={}
for name,pc in pairs(P)do counts[name]=0;event.on_bus_exec(function()counts[name]=counts[name]+1 end,pc,"probe-"..name,"System Bus")end
for _=1,240 do emu.frameadvance()end
local out=assert(io.open(assert(os.getenv("SLINK_PROBE_OUT")),"w"));out:write(JSON.encode(counts));out:close()
for name,c in pairs(counts)do t.log(string.format("%-36s %d",name,c))end
t.check("probe done",true);t.finish()
