-- Live production checkpoint proof through the real CONTINUE, battle, capture and naming paths.
local ROOT=SLINK_ROOT or os.getenv('SLINK_ROOT')
local G=dofile(ROOT..'/lua/tests/gatelib.lua')
local t=G.start("test_gen1_write_safety_battle",{no_boot=true})
local M=t.M
t.log('rom_sha1='..gameinfo.getromhash():lower())
local source=t.variant=='yellow' and 'pokeyellow' or 'pokered'
local target=t.variant=='blue' and 'pokeblue' or source
local symbols={}
for line in io.lines(ROOT..'/.cache/pret/'..source..'/'..target..'.sym') do
    local bank,addr,name=line:match('^(%x+):(%x+) (%S+)$')
    if bank then symbols[name]={bank=tonumber(bank,16),addr=tonumber(addr,16)} end
end
local function s(name)return assert(symbols[name],name)end
local function a(name)return s(name).addr end
local function r(address)return memory.read_u8(address,'System Bus')end
local function w(address,value)memory.write_u8(address,value,'System Bus')end
local context='boot'
local hooks,entered,observed={},{},{}
local function hook(name,kind)
    local sym=s(name)
    hooks[#hooks+1]=event.on_bus_exec(function()
        if sym.bank==0 or r(a('hLoadedROMBank'))==sym.bank then
            context=kind
            entered[name]=(entered[name] or 0)+1
        end
    end,sym.addr,'battle-safety-'..name,'System Bus')
end
hook('OverworldLoop','world');hook('OverworldLoopLessDelay','world')
hook('DisplayNamingScreen','naming');hook('EnterMap','transition')
local function candidate() return (M.isPartyWriteSafe()) end

local function step(buttons)
    t.step(buttons)
    local label=M.isInBattle() and context~='naming' and 'battle' or context
    local row=observed[label] or {frames=0,safe=0,old=0}
    observed[label]=row
    row.frames=row.frames+1
    row.safe=row.safe+(candidate() and 1 or 0)
    row.old=row.old+(M.isInOverworld() and 1 or 0)
end
local function frames(n,buttons)for _=1,n do step(buttons)end end
local function hold(btn,n,stop)
    for _=1,n do
        if stop and stop() then return true end
        step({[btn]=true})
    end
    step();return stop and stop() or false
end
local function press(btn,n)hold(btn,n or 8);frames(18)end
local ok,err=pcall(function()
    t.check('pinned battle fixture boots through CONTINUE',G.prove_booted(M,'gen1_rby',step,hold))
    t.log(string.format('boot map=%d coords=%d,%d battle=%d',M.getCurrentMap(),r(a('wXCoord')),r(a('wYCoord')),r(M.BATTLE_FLAG_ADDR)))
    local H=dofile(ROOT..'/lua/tests/duo/gen1_hunt.lua')({M=M,G=t.G,log=t.log,frames=frames,hold=hold,party_count=M.getPartyCount})
    M.setNoBattles(false) -- the pinned fixture was saved during its boot suppression window
    if not M.isInBattle() then
        local found,why=H.find_battle(M.getCurrentMap())
        assert(found,why)
    end
    assert(M.isInBattle() and r(M.BATTLE_FLAG_ADDR)==1,'actual wild battle did not start')
    assert(H.wait_for_menu(),'no real battle menu');assert(H.left_column(1),'no real ITEM choice')
    w(M.BAG_ITEMS_ADDR,1);w(M.BAG_ITEMS_ADDR+1,10) -- canonical Master Ball, deterministic capture
    press('A',10);frames(45);press('A',10);frames(45)
    for _=1,150 do
        if (entered.DisplayNamingScreen or 0)>0 then break end
        press('A',4);frames(12)
    end
    t.check('actual capture opens NamingScreen',(entered.DisplayNamingScreen or 0)>0)
    frames(120)
    press('A');press('Start');press('A')
    for _=1,80 do
        if context=='world' and not M.isInBattle() then break end
        press('B',4);frames(12)
    end
    t.check('actual capture and naming resume overworld',context=='world' and not M.isInBattle() and M.getPartyCount()==2)
    frames(60)
    for _,label in ipairs({'boot','battle','naming'}) do
        local row=observed[label]
        t.check(label..' was sampled and never qualifies',row and row.frames>0 and row.safe==0)
    end
    t.check('positive world control qualifies',observed.world and observed.world.safe>0)
end)
for label,row in pairs(observed)do
    t.log(string.format('%s: frames=%d old=%d candidate=%d',label,row.frames,row.old,row.safe))
end
for _,id in ipairs(hooks)do event.unregisterbyid(id)end
t.check('live battle/naming checkpoint gate completed',ok,tostring(err))
t.finish()
