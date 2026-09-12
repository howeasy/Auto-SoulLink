-- Controlled memorial kernel plus ORIGINAL SaveGameData; no production permit,
-- file flush, actor faint, or paired runtime closure is inferred from this gate.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_memorial_receipt_gate")
package.path=ROOT.."/lua/?.lua;"..ROOT.."/data/games/gen1_rby/?.lua;"..package.path
local JSON=require("json_codec")
local Full=require("gen1_full_save")
local Layout=require("gen1_full_save_layout")[t.variant]
local source=t.variant=="yellow" and "pokeyellow" or "pokered"
local target=t.variant=="blue" and "pokeblue" or source
local oracle=dofile(ROOT.."/lua/tests/gb_routine_oracle.lua").new({
    symbols_path=ROOT.."/.cache/pret/"..source.."/"..target..".sym",step=function()t.step({})end,
    scratch=0xCB00,marker=0xCBF0,stack=0xDFFE,bankswitch="Bankswitch"})
local function read_json(path)
    local file=assert(io.open(path,"r"));local raw=file:read("*a");file:close()
    return assert(JSON.decode(raw))
end
local function put(address,hex,domain)
    for i,value in ipairs(assert(t.M.hexToBytes(hex)))do memory.write_u8(address+i-1,value,domain)end
end
local boot=memorysavestate.savecorestate()
local rows=JSON.array()
local ok,why=xpcall(function()
    for _,case in ipairs(read_json(os.getenv("SLINK_MEMORIAL_INPUT")))do
        memorysavestate.loadcorestate(boot)
        memory.write_u8(0xFFFF,0,"System Bus")
        local before=case.before
        for name,region in pairs(Layout.regions)do put(region.address,before.fields[name],"System Bus")end
        put(0,before.cart_hex,"CartRAM")
        memory.write_u8(Layout.status,before.save_status,"System Bus")
        t.M._memorial_reservations=nil
        local emotion
        if t.variant=="yellow" then
            -- Execute the original deposit happiness routine with the same
            -- selected member and d=PIKAHAPPY_DEPOSITED (source constant 7).
            local clone=memorysavestate.savecorestate()
            oracle.write(oracle.address("wWhichPokemon"),case.slot)
            emu.setregister("D",7)
            oracle.invoke("ModifyPikachuHappiness")
            emotion={happiness=oracle.read(oracle.address("wPikachuHappiness")),
                     mood=oracle.read(oracle.address("wPikachuMood"))}
            memorysavestate.loadcorestate(clone);memorysavestate.removestate(clone)
        end
        local frame=emu.framecount()
        local accepted,reason=t.M.depositMemorialMon(case.slot)
        assert(accepted,tostring(reason))
        assert(emu.framecount()==frame,"memorial primitive advanced a frame")
        local after=Full.capture(t.M,t.variant)
        oracle.invoke("SaveGameData")
        local saved=Full.capture(t.M,t.variant)
        after.cart_hex=saved.cart_hex;after.save_status=saved.save_status
        if emotion then
            assert(oracle.read(oracle.address("wPikachuHappiness"))==emotion.happiness,"deposit happiness differs from cartridge")
            assert(oracle.read(oracle.address("wPikachuMood"))==emotion.mood,"deposit mood differs from cartridge")
        end
        rows[#rows+1]={before=before,after=after,key=case.key,identity=case.identity,emotion=emotion}
    end
end,debug.traceback)
memorysavestate.loadcorestate(boot);memorysavestate.removestate(boot)
local file=assert(io.open(os.getenv("SLINK_MEMORIAL_RESULT"),"w"))
file:write(assert(JSON.encode({passed=ok,cases=rows,reason=ok and "passed" or tostring(why)})));file:close()
t.check("memorial source witnesses captured with original full save",ok,tostring(why));t.finish()
