-- Canonical CalcExperience and CalcStats versus SLink from cloned core states.
-- Runs unchanged cartridge code with bank-qualified symbols. No fixture/save edits.
local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
local G = dofile(ROOT .. "/lua/tests/gen1_gatelib.lua")
local t = G.start("test_gen1_stats_differential")
local game = t.M._game
local source = t.variant == "yellow" and "pokeyellow" or "pokered"
local target = t.variant == "blue" and "pokeblue" or source
local symbols = {}
local f = assert(io.open(ROOT .. "/.cache/pret/" .. source .. "/" .. target .. ".sym", "r"))
for line in f:lines() do
    local bank, addr, name = line:match("^(%x+):(%x+) (%S+)$")
    if bank then symbols[name] = {bank=tonumber(bank,16),addr=tonumber(addr,16)} end
end
f:close()
local function sym(name) return assert(symbols[name],"missing canonical symbol "..name) end
local function addr(name) return sym(name).addr end
local function read(a) return memory.read_u8(a,"System Bus") end
local function write(a,v) memory.write_u8(a,v,"System Bus") end
local function word(a,v) write(a,math.floor(v/256));write(a+1,v%256) end
local function emit(code,...) for _,v in ipairs({...}) do code[#code+1]=v end end
local function call(code,name)
    local s=sym(name)
    if s.bank==0 then
        emit(code,0xCD,s.addr%256,math.floor(s.addr/256))
    else
        local switch=addr("Bankswitch")
        emit(code,0x06,s.bank,0x21,s.addr%256,math.floor(s.addr/256),
            0xCD,switch%256,math.floor(switch/256))
    end
end
local function execute(code)
    local all={0xF3}
    for _,byte in ipairs(code) do all[#all+1]=byte end
    emit(all,0x3E,0xA5,0xEA,0xFF,0xC7,0x18,0xFE)
    assert(#all<256,"oracle trampoline overflow")
    write(0xC7FF,0)
    for i,byte in ipairs(all) do write(0xC800+i-1,byte) end
    emu.setregister("SP",0xDFFE);emu.setregister("PC",0xC800)
    for _=1,180 do t.step();if read(0xC7FF)==0xA5 then return end end
    error(string.format("canonical stat/experience routine did not return: PC=$%04X SP=$%04X", emu.getregister("PC"), emu.getregister("SP")))
end
local boot=memorysavestate.savecorestate()
local xp_cases,stat_cases,failures=0,0,0
local function mismatch(label,want,got)
    if want==got then return end
    failures=failures+1
    if failures<=16 then t.check(label,false,"canonical="..tostring(want).." SLink="..tostring(got)) end
end
local ok,err=pcall(function()
    for growth=0,5 do
        for level=1,100 do
            memorysavestate.loadcorestate(boot)
            write(addr("wMonHGrowthRate"),growth)
            local clone=memorysavestate.savecorestate()
            local code={0x16,level} -- ld d,level
            call(code,"CalcExperience")
            execute(code)
            local exp=addr("hExperience")
            local expected=read(exp)*65536+read(exp+1)*256+read(exp+2)
            memorysavestate.loadcorestate(clone);memorysavestate.removestate(clone)
            mismatch("experience curve="..growth.." level="..level,expected,game.experienceForLevel(growth,level))
            xp_cases=xp_cases+1
        end
    end
    t.check("600 canonical experience computations, all six growth curves",xp_cases==600 and failures==0,
        "cases="..xp_cases.." mismatches="..failures)

    local species={}
    for internal,dex in pairs(game.INDEX_TO_NATDEX) do species[#species+1]={internal=internal,dex=dex} end
    table.sort(species,function(a,b) return a.dex<b.dex end)
    t.check("all 151 canonical species represented",#species==151)
    local fields={"hp","attack","defense","speed","special"}
    local exp_fields={"HPExp","AttackExp","DefenseExp","SpeedExp","SpecialExp"}
    local boundaries={0,1,65024,65025,65535}
    for _,mon in ipairs(species) do
        for _,level in ipairs({1,5,50,100}) do
            for index,dv in ipairs({0x0000,0xFFFF,0x1234,0xFEDC}) do
                memorysavestate.loadcorestate(boot)
                write(addr("wCurSpecies"),mon.internal)
                write(addr("wCurEnemyLevel"),level)
                word(addr("wPartyMon1DVs"),dv)
                local stat_exp={}
                for i,name in ipairs(fields) do
                    local value=boundaries[(i+index-2)%#boundaries+1]
                    stat_exp[name]=value
                    word(addr("wPartyMon1"..exp_fields[i]),value)
                end
                local clone=memorysavestate.savecorestate()
                local code={}
                call(code,"GetMonHeader")
                -- CalcStats: HL is one byte before stat experience; DE destination;
                -- B=1 includes stat experience. Both pointers are outside trampoline.
                local hp_exp=addr("wPartyMon1HPExp")-1
                emit(code,0x21,hp_exp%256,math.floor(hp_exp/256),0x11,0x00,0xC7,0x06,0x01)
                assert(sym("CalcStats").bank==0,"CalcStats bank changed; oracle calling convention needs review")
                call(code,"CalcStats")
                execute(code)
                local expected={}
                for i,name in ipairs(fields) do expected[name]=read(0xC700+(i-1)*2)*256+read(0xC701+(i-1)*2) end
                memorysavestate.loadcorestate(clone);memorysavestate.removestate(clone)
                local actual=game.calcStats(game.readBaseStats(t.variant,mon.dex),level,dv,stat_exp)
                for _,name in ipairs(fields) do
                    mismatch("stats dex="..mon.dex.." level="..level.." dv="..dv.." "..name,
                        expected[name],actual and actual[name])
                end
                stat_cases=stat_cases+1
            end
        end
    end
    t.check("2416 canonical stat computations over all species/levels/DV/stat-exp boundaries",
        stat_cases==2416 and failures==0,"cases="..stat_cases.." mismatches="..failures)
end)
memorysavestate.loadcorestate(boot);memorysavestate.removestate(boot)
t.check("stat differential harness completed",ok,tostring(err))
t.check("all 3016 expected computations executed",xp_cases==600 and stat_cases==2416,
    "experience="..xp_cases.." stats="..stat_cases)
t.finish("stat differential")
