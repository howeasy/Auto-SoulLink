-- SYNTH fixture/link setup is disclosed by Python. Native buttons only here;
-- every guest write is through the real composed client's trade binder.
local L=dofile(assert(os.getenv("POL_DRIVER_ROOT")).."/tools/polished_live/pol_lib.lua")
local J=L.json
local role=os.getenv("SLINK_PLAYER")
local cold=os.getenv("POL_COLD")=="1"
-- run.lua/entry refuse by console diagnostic; preserve it before the generic graph assertion.
local original_console_log=console.log
console.log=function(...)
    local words={}
    for i=1,select('#',...) do words[#words+1]=tostring(select(i,...)) end
    local f=io.open(L.RUN.."/console.log","ab")
    if f then f:write(table.concat(words," ").."\n") f:close() end
    return original_console_log(...)
end
local function dump(name,value)
    local f=assert(io.open(L.RUN.."/"..name,"wb"))
    assert(f:write(J.encode(value))) f:close()
end
local function exists(name)
    local f=io.open(L.RUN.."/"..name,"rb")
    if f then f:close() return true end
    return false
end
local ok,why=pcall(function()
console.log("[trade-duo] global print type="..type(print))
client.speedmode(300)
for _,name in ipairs({"OWPlayerInput","SetInitialOptions.joypad_loop","YesNoBox","NoYesBox"}) do L.hook(name) end
-- Explicit dev option, through the existing Entry.build seam. Private root
-- contains the enabled build's provenance/profile, not changed shipped pins.
local original_dofile=dofile
dofile=function(path)
    local value=original_dofile(path)
    if path==L.ROOT.."/lua/gen2/entry.lua" then
        local build=value.build
        value.build=function(deps) deps.polished_trade_dev=true return build(deps) end
    end
    return value
end
SLINK_HOST,SLINK_PORT,SLINK_PLAYER=os.getenv("SLINK_HOST"),tonumber(os.getenv("SLINK_PORT")),role
dofile(L.ROOT.."/lua/gen2/run.lua")
dofile=original_dofile
assert(SLINK_GEN2_CLIENT and SLINK_GEN2_PARTS.dev_polished_trade,"enabled test graph failed to compose dev binder")
local C=assert(package.loaded.connector)
local hello,done,prompt=nil,nil,false
local send,receive=C.send,C.receive
C.send=function(line,...)
    local msg=J.decode(line)
    if msg.event=="hello" then hello=msg end
    if msg.event=="trade_done" then
        done=msg
        L.log("TRADE_DONE "..line)
        dump("done.json",msg)
        if client.saveram then client.saveram() end
    end
    return send(line,...)
end
C.receive=function(...)
    local line=receive(...)
    if line then
        local msg=J.decode(line)
        for _,cmd in ipairs(msg.commands or {}) do
            if cmd.cmd=="show_menu" then prompt=true L.log("NATIVE_RESPONDER_PROMPT") end
        end
    end
    return line
end
    assert(L.to_overworld(20,1,60,10000,"cold Continue to retained receptionist fixture"),"CONTINUE did not reach POKECENTER_2F")
    local t=emu.framecount()
    while not hello and emu.framecount()-t<1800 do L.frame() end
    assert(hello,"hello absent")
    L.idle(180) -- let normal party ticks and any setup-link retrieval acknowledgment settle on both sides
    dump("ready.json",hello)
    L.log("READY "..role.." cold="..tostring(cold).." pos="..L.rw("wXCoord")..","..L.rw("wYCoord"))
    t=emu.framecount()
    while not exists("go") and not exists("stop") and emu.framecount()-t<90000 do L.frame() end
    if cold or exists("stop") then return end
    if role=="a" then
        assert(L.rw("wXCoord")==5 and L.rw("wYCoord")==3,"fixture is not in front of trade receptionist")
        for _=1,6 do L.frame({Up=true}) end
    end
    local noyes=L.hits.NoYesBox or 0 -- ignore any boot/CONTINUE prompt already passed
    t=emu.framecount()
    while not done and not exists("stop") and emu.framecount()-t<18000 do
        if (L.hits.NoYesBox or 0)>noyes then
            noyes=L.hits.NoYesBox
            L.idle(24)
            for _=1,3 do L.frame({Down=true}) end
            L.idle(8)
            for _=1,3 do L.frame({A=true}) end
        elseif role=="a" or prompt then L.pulse("A") else L.frame() end
    end
    assert(done and not done.uncertain and done.new_key,"trade did not complete: "..tostring(done and done.uncertain))
    for _=1,180 do L.frame() end -- flush wire and native exit; no extra save or fabricated acknowledgment
    if client.saveram then client.saveram() end
    while not exists("stop") and emu.framecount()-t<90000 do L.frame() end
end)
if not ok then dump("failure.json",{reason=tostring(why)}) end
L.check("native trade / cold CONTINUE",ok,why)
L.finish("trade-duo-"..role)
