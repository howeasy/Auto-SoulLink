-- Isolated original SaveGameData differential. Debug CPU injection and held
-- authority are explicit test fixtures, never production invocation mechanisms.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_full_save_gate")
package.path=ROOT.."/lua/?.lua;"..ROOT.."/data/games/gen1_rby/?.lua;"..package.path
local JSON=require("json_codec")
local Full=require("gen1_full_save")
local Layout=require("gen1_full_save_layout")[t.variant]
local Canonical=require("journal_document")
assert(require("platform_clock").new())
local storage=assert(require("platform_storage").new(os.getenv("SLINK_FULLSAVE_RESULT")..".store"))
local source=t.variant=="yellow" and "pokeyellow" or "pokered"
local target=t.variant=="blue" and "pokeblue" or source
local oracle=dofile(ROOT.."/lua/tests/gb_routine_oracle.lua").new({
    symbols_path=ROOT.."/.cache/pret/"..source.."/"..target..".sym",step=function()t.step({})end,
    scratch=0xCB00,marker=0xCBF0,stack=0xDFFE,bankswitch="Bankswitch"})
local boot=memorysavestate.savecorestate()
local rows=JSON.array()
local mem=setmetatable({isPartyWriteSafe=function()return true end},{__index=t.M})
local body={cmd="native_trade_prepare",player="a"}
local identity={command_id=string.rep("a",32),command_sequence=1}
local adapter=Full.new({memory=mem,manifest={variant=t.variant,final_sha1=gameinfo.getromhash():lower()},
    player="a",authorize=function()return true end,context_generation=function()return "fixture-context"end,
    sha256=storage.sha256,preparation={prepare=function()error("explicit prepared-intent fixture only")end},
    persist_save=function()error("kernel differential must not flush a file")end})
local ok,why=xpcall(function()
    for seed=0,7 do
        memorysavestate.loadcorestate(boot)
        -- Every authoritative byte varies. Disable IRQs in the isolated oracle
        -- so both transformations operate on the same held source snapshot.
        memory.write_u8(0xFFFF,0,"System Bus")
        for p=0,0x7FFF do memory.write_u8(p,(p*17+seed*31)%256,"CartRAM")end
        for _,region in pairs(Layout.regions)do
            for i=0,region.length-1 do memory.write_u8(region.address+i,(i*29+region.address+seed*37)%256,"System Bus")end
        end
        memory.write_u8(Layout.status,seed,"System Bus")
        local before=Full.capture(mem,t.variant)
        local clone=memorysavestate.savecorestate()
        oracle.invoke("SaveGameData")
        local expected=Full.capture(mem,t.variant)
        memorysavestate.loadcorestate(clone)
        local intent={schema=Full.INTENT,command_id=identity.command_id,command_sequence=1,
            body_digest=storage.sha256(assert(Canonical.encode(body))),context_generation="fixture-context",
            point=before,image_hex=Full.image(mem,before),checkpoint={}}
        local frame=emu.framecount();adapter.apply(body,intent,identity)
        local after=Full.capture(mem,t.variant)
        assert(emu.framecount()==frame,"copy kernel advanced a frame")
        assert(after.cart_hex==expected.cart_hex,"full CartRAM differs from original SaveGameData")
        assert(after.save_status==expected.save_status and after.save_status==2,"save status differs")
        assert(Canonical.encode(after.fields)==Canonical.encode(before.fields),"save kernel changed source WRAM")
        rows[#rows+1]={seed=seed,before=before,after_hex=after.cart_hex,oracle_hex=expected.cart_hex}
        memorysavestate.removestate(clone)
    end
end,debug.traceback)
memorysavestate.loadcorestate(boot);memorysavestate.removestate(boot);storage.close()
local file=assert(io.open(os.getenv("SLINK_FULLSAVE_RESULT"),"w"))
file:write(assert(JSON.encode({variant=t.variant,cases=rows,passed=ok,reason=ok and "passed" or tostring(why)})));file:close()
t.check("complete held save matches original SaveGameData",ok,tostring(why));t.finish()
