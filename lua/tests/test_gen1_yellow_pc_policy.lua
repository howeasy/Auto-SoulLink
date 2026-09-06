-- Execute Yellow's untouched BillsPCDeposit permission branch in the cartridge.
-- The party picker and later deposit confirmation are outside this narrow oracle.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local G=dofile(ROOT.."/lua/tests/gen1_gatelib.lua")
local t=G.start("test_gen1_yellow_pc_policy")
local M=t.M
assert(t.variant=="yellow","Yellow-only canonical PC policy gate")
local symbols={}
local f=assert(io.open(ROOT.."/.cache/pret/pokeyellow/pokeyellow.sym","r"))
for line in f:lines() do
    local bank,a,name=line:match("^(%x+):(%x+) (%S+)$")
    if bank then symbols[name]={bank=tonumber(bank,16),addr=tonumber(a,16)} end
end
f:close()
local function s(name) return assert(symbols[name],"missing symbol "..name) end
local function a(name) return s(name).addr end
local function r(addr) return memory.read_u8(addr,"System Bus") end
local function w(addr,v) memory.write_u8(addr,v,"System Bus") end
local function put(addr,data) for i,v in ipairs(data) do w(addr+i-1,v) end end
local function rombytes(label,n)
    local entry=s(label)
    local flat=entry.bank*0x4000+entry.addr%0x4000
    local bytes={}
    for i=0,n-1 do bytes[i+1]=memory.read_u8(flat+i,"ROM") end
    return bytes
end
local branch=rombytes("BillsPCDeposit.boxNotFull",33)
local identity=s("IsThisPartyMonStarterPikachu")
local check=s("CheckPikachuFollowingPlayer")
local switch=s("Bankswitch")
-- Skip only the party-picker call and cancellation branch (9 bytes). All bytes
-- after it execute in their original ROM location, including both real predicates.
local expected={0x21,identity.addr%256,math.floor(identity.addr/256),0x06,identity.bank,
    0xCD,switch.addr%256,math.floor(switch.addr/256),0x30,0x0E,
    0xCD,check.addr%256,math.floor(check.addr/256),0x28,0x09}
for i,v in ipairs(expected) do assert(branch[i+9]==v,"Yellow PC permission anchor drift at "..i) end
local entry=a("BillsPCDeposit.boxNotFull")+9
local allowed=a("BillsPCDeposit.asm_215ad")
local denied=entry+#expected
local boot=memorysavestate.savecorestate()
local hooks={}
local outcome
local function mark(label)
    return function() if not outcome then outcome=label end end
end
hooks[1]=event.on_bus_exec(mark("allowed"),allowed,"yellow-deposit-allowed","System Bus")
hooks[2]=event.on_bus_exec(mark("rejected"),denied,"yellow-deposit-denied","System Bus")
local function run_case(label,disabled,change,expected_result)
    memorysavestate.loadcorestate(boot)
    w(a("wWhichPokemon"),0)
    -- pret constants/pokemon_constants.asm: PIKACHU=$54; STARTER_PIKACHU=PIKACHU.
    w(a("wPartyMon1"),0x54)
    w(a("wCurPartySpecies"),0x54)
    w(a("wPartyMon1OTID"),r(a("wPlayerID")))
    w(a("wPartyMon1OTID")+1,r(a("wPlayerID")+1))
    for i=0,10 do w(a("wPartyMonOT")+i,r(a("wPlayerName")+i)) end
    local flag=a("wPikachuOverworldStateFlags")
    w(flag,disabled and 2 or 0)
    if change then change() end
    outcome=nil
    put(0xC800,{0xF3,0x06,s("BillsPCDeposit").bank,0x21,entry%256,math.floor(entry/256),
         0xCD,switch.addr%256,math.floor(switch.addr/256),0x18,0xFE})
    emu.setregister("SP",0xDFFE);emu.setregister("PC",0xC800)
    for _=1,10 do t.step();if outcome then break end end
    t.check(label,outcome==expected_result,"cartridge="..tostring(outcome)..", expected="..expected_result)
end
local ok,err=pcall(function()
    run_case("following starter (bit1 clear) reaches deposit confirmation",false,nil,"allowed")
    run_case("disabled/sleeping starter (bit1 set) is refused",true,nil,"rejected")
    run_case("different OTID is not the starter despite species",true,function()
        w(a("wPartyMon1OTID"),(r(a("wPlayerID"))+1)%256)
    end,"allowed")
    run_case("different fifth OT-name byte is not the starter",true,function()
        w(a("wPartyMonOT")+4,(r(a("wPlayerName")+4)+1)%256)
    end,"allowed")
    run_case("sixth OT-name byte does not change starter identity",true,function()
        w(a("wPartyMonOT")+5,(r(a("wPlayerName")+5)+1)%256)
    end,"rejected")
end)
for _,id in ipairs(hooks) do event.unregisterbyid(id) end
memorysavestate.loadcorestate(boot);memorysavestate.removestate(boot)
t.check("Yellow PC permission harness completed",ok,tostring(err))
t.finish("canonical Yellow PC permission branch")
