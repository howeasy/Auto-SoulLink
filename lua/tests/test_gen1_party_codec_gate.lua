-- Verify PP limits using the untouched GetMaxPP routine, then decode a complete
-- party record actually constructed by MoveMon/CalcStats from cloned core state.
local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
local G = dofile(ROOT .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("test_gen1_party_codec_gate")
local M, Codec = t.M, require("gen1_party_codec")
local source = t.variant == "yellow" and "pokeyellow" or "pokered"
local target = t.variant == "blue" and "pokeblue" or source
local oracle=dofile(ROOT.."/lua/tests/gb_routine_oracle.lua").new({
    symbols_path=ROOT.."/.cache/pret/"..source.."/"..target..".sym",step=t.step,
    scratch=0xC800,marker=0xC7FF,stack=0xDFFE,bankswitch="Bankswitch"})
local a,read,write,copy,invoke=oracle.address,oracle.read,oracle.write,oracle.copy,oracle.invoke
local boot = memorysavestate.savecorestate()
local cases, failures = 0, 0
local ok, err = pcall(function()
    for move=1,165 do
        for ups=0,3 do
            memorysavestate.loadcorestate(boot)
            write(a("wPartyMon1Moves"),move)
            write(a("wPartyMon1PP"),ups*64)
            write(a("wWhichPokemon"),0)
            write(a("wMonDataLocation"),0)
            write(a("wCurrentMenuItem"),0)
            invoke("GetMaxPP")
            local expected, actual = read(a("wMaxPP")), Codec.maxPP(t.variant, move, ups)
            cases = cases + 1
            if expected ~= actual then
                failures = failures + 1
                if failures <= 8 then
                    t.check("PP move="..move.." ups="..ups,false,"cartridge="..expected.." codec="..tostring(actual))
                end
            end
        end
    end
    t.check("all660 cartridge GetMaxPP comparisons agree",cases==660 and failures==0,
            "cases="..cases.." mismatches="..failures)
    memorysavestate.loadcorestate(boot)
    copy(a("wBoxMons"),a("wPartyMons"),33)
    copy(a("wBoxMonOT"),a("wPartyMonOT"),11)
    copy(a("wBoxMonNicks"),a("wPartyMonNicks"),11)
    local species = read(a("wPartyMon1Species"))
    write(a("wBoxMon1Exp"),0);write(a("wBoxMon1Exp")+1,3);write(a("wBoxMon1Exp")+2,0xE8)
    write(a("wBoxCount"),1);write(a("wBoxSpecies"),species);write(a("wBoxSpecies")+1,255)
    write(a("wPartyCount"),0);write(a("wPartySpecies"),255)
    write(a("wWhichPokemon"),0);write(a("wCurPartySpecies"),species)
    write(a("wMoveMonType"),0)
    invoke("_MoveMon")
    write(a("wRemoveMonFromBox"),1)
    invoke("_RemovePokemon")
    local blob = assert(M.readPartyBlob(0))
    local decoded, why = Codec.validateBlob(blob,t.variant,M.monKey(M.PARTY_BASE_ADDR))
    t.check("complete cartridge-produced party blob validates",decoded~=nil,tostring(why))
    assert(decoded,"cartridge blob failed codec")
    t.check("codec read canonical 24-bit experience",decoded.experience==1000)
    t.check("codec read canonical level",decoded.level==read(a("wPartyMon1Level")))
    for index=1,66 do assert(decoded.blob[index]==blob[index],"codec changed byte "..index) end
    local encoded={}
    for index=1,66 do encoded[index]=tostring(blob[index]) end
    local output=assert(io.open(ROOT.."/.cache/gen1-codec-"..t.variant..".json","w"))
    output:write('{"variant":"'..t.variant..'","rom_sha1":"'..gameinfo.getromhash()..
        '","pp_cases":'..cases..',"key":"'..decoded.key..'","blob":['..table.concat(encoded,",")..']}\n')
    output:close()
end)
memorysavestate.loadcorestate(boot);memorysavestate.removestate(boot)
t.check("codec cartridge oracle completed",ok,tostring(err))
t.finish()
