-- What does the core see (hJoyInput/hJoyHeld) frame by frame for a 3-on/10-off A press, harness vs bounded step_one?
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
package.path=ROOT.."/lua/?.lua;"..package.path
local G=dofile(ROOT.."/lua/tests/gen1_gatelib.lua")
local t=G.start("probe_input_latency")
local JSON=require("json_codec")
local f=assert(io.open(assert(os.getenv("SLINK_PROBE_INPUT")),"r"));local cfg=assert(JSON.decode(f:read("*a")));f:close()
local u8=function(a)return memory.read_u8(a,"System Bus")end
local out={}
local function pattern(step,label)
    local rows={}
    for cycle=1,3 do
        for i=1,3 do step({A=true});rows[#rows+1]={f=emu.framecount(),set="A",input=u8(0xFFF8),held=u8(0xFFB4),pressed=u8(0xFFB3)}end
        for i=1,10 do step(nil);rows[#rows+1]={f=emu.framecount(),set="-",input=u8(0xFFF8),held=u8(0xFFB4),pressed=u8(0xFFB3)}end
    end
    for i=1,6 do step({Down=true});rows[#rows+1]={f=emu.framecount(),set="D",input=u8(0xFFF8),held=u8(0xFFB4),pressed=u8(0xFFB3)}end
    for i=1,6 do step(nil);rows[#rows+1]={f=emu.framecount(),set="-",input=u8(0xFFF8),held=u8(0xFFB4),pressed=u8(0xFFB3)}end
    out[label]=rows
    local s={};for _,r in ipairs(rows)do s[#s+1]=r.set..":"..string.format("%02x",r.input)end;t.log(label.." "..table.concat(s," "))
end
pattern(function(b)if b then joypad.set(b)end;emu.frameadvance()end,"harness")
local owner=require("platform_bounded_execution").new({profile="gambatte",owner_id=assert(require("platform_identity").new_nonce()),
    expected_host=require("platform_execution").supported_profile("gambatte"),authorize=function(v)return v~=nil end})
pattern(function(b)if b then joypad.set(b)end;local ok,r=owner.step_one({});assert(ok,r)end,"bounded")
owner.set_held(true,"probe done")
local o=assert(io.open(cfg.output,"w"));o:write(JSON.encode(out));o:close()
t.check("probe done",true);t.finish()
