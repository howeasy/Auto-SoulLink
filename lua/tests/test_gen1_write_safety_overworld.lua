-- Live main-loop checkpoint matrix. UI entry is independently observed in ROM;
-- the predicate under test is the production M.isPartyWriteSafe implementation.
-- This gate does not establish admission or durable transaction ownership.
local ROOT=SLINK_ROOT or os.getenv('SLINK_ROOT')
local G=dofile(ROOT..'/lua/tests/gatelib.lua')
local t=G.start("test_gen1_write_safety_overworld")
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
local function enum(file, wanted)
    local index
    for line in io.lines(ROOT..'/.cache/pret/'..source..'/constants/'..file) do
        local skip=line:match('^%s*const_skip%s+(%d+)')
        if not skip and line:match('^%s*const_skip%s*$') then skip='1' end
        local name=line:match('^%s*const%s+([%w_]+)')
        if line:match('^%s*const_def%s*$') then index=0
        elseif skip and index then index=index+tonumber(skip)
        elseif name and index then
            if name==wanted then return index end
            index=index+1
        end
    end
    error('unresolved source enum '..wanted)
end
local context='world'
local hooks, entered={},{}
local function hook(name,kind)
    local sym=s(name)
    hooks[#hooks+1]=event.on_bus_exec(function()
        if sym.bank==0 or r(a('hLoadedROMBank'))==sym.bank then
            context=kind
            entered[name]=(entered[name] or 0)+1
        end
    end,sym.addr,'matrix-'..name,'System Bus')
end
hook('OverworldLoop','world');hook('OverworldLoopLessDelay','world')
hook('DisplayTextID','text');hook('DisplayStartMenu','start')
hook('RedisplayStartMenu','start');hook('CloseTextDisplay','closing')
hook('EnterMap','transition');hook('HandleBlackOut','blackout')
hook('DisplayNamingScreen','naming')
hook('TextScript_PokemonCenterPC','PC');hook('BillsPCMenu','BillsPC')
hook('DisplayMonListMenu','PC-selector');hook('DisplayDepositWithdrawMenu','PC-choice')
hook('StatusScreen','stats');hook('DisplayChangeBoxMenu','box-selector')
hook('CableClubNPC','cable-club');hook('CableClubNPC.establishConnectionLoop','cable-handshake')
if t.variant=='yellow' then hook('BillsPCPrintBox','printer');hook('PrintPCBoxPage','printer-transmission') end
for _,label in ipairs({'Deposit','Withdraw','Release','ChangeBox'}) do hook('BillsPC'..label,'PC-'..label) end
for _,label in ipairs({'Pokedex','Pokemon','Item','TrainerInfo','SaveReset','Option'}) do
    hook('StartMenu_'..label,label)
end
local rows={}
local function stack_candidate() return (M.isPartyWriteSafe()) end

local current
local function step(buttons)
    t.step(buttons)
    if not current then return end
    local row=rows[current]
    local stack=stack_candidate()
    local old=M.isInOverworld()
    row.frames=row.frames+1
    row.old=row.old+(old and 1 or 0)
    row.stack=row.stack+(stack and 1 or 0)
    row.candidate=row.candidate+(stack and old and 1 or 0)
    row.contexts[context]=(row.contexts[context] or 0)+1
    if stack and old and context~='world' then
        row.bad=row.bad+1
        t.log('CANDIDATE IN '..context..' at frame '..t.frame)
    end
end
local function frames(n,buttons) for _=1,n do step(buttons) end end
local function press(button,n)
    frames(n or 8,{[button]=true});frames(18)
end
local function begin(label)
    current=label
    rows[label]={frames=0,stack=0,old=0,candidate=0,bad=0,contexts={}}
end
local boot=memorysavestate.savecorestate()
local function restore()
    current=nil;memorysavestate.loadcorestate(boot);context='world';entered={}
    frames(30)
end
local function walk(x,y)
    for _=1,80 do
        local xx,yy=r(a('wXCoord')),r(a('wYCoord'))
        if xx==x and yy==y then frames(24);return true end
        local btn=xx<x and 'Right' or xx>x and 'Left' or yy<y and 'Down' or 'Up'
        for _=1,20 do
            step({[btn]=true})
            if r(a('wXCoord'))==x and r(a('wYCoord'))==y then break end
        end
    end
    t.log(string.format('walk wanted %d,%d got %d,%d map=%d',x,y,r(a('wXCoord')),r(a('wYCoord')),M.getCurrentMap()))
    client.screenshot(ROOT..'/patch/build/probe-gen1-path-'..t.variant..'.png')
    return false
end
local function await_checkpoint()
    for _=1,90 do
        step()
        if M.isPartyWriteSafe() then return true end
    end
    return false
end
local function seed_pc_inventory()
    -- A controlled, complete fixture with enough party and box occupants to reach
    -- the actual selectors. Storage transformations have separate cartridge oracles.
    local mon=assert(M.readPartySlot(0))
    local facts=assert(t.G.readBaseStats(t.variant,t.G.toNatDex(mon.species_index)))
    local xp=assert(t.G.experienceForLevel(facts.growth_rate,mon.level))
    w(a('wPartyMon1Exp'),math.floor(xp/65536));w(a('wPartyMon1Exp')+1,math.floor(xp/256)%256)
    w(a('wPartyMon1Exp')+2,xp%256)
    for slot=1,2 do
        for i=0,43 do w(M.PARTY_BASE_ADDR+slot*44+i,r(M.PARTY_BASE_ADDR+i)) end
        for i=0,10 do
            w(M.PARTY_OT_NAMES_ADDR+slot*11+i,r(M.PARTY_OT_NAMES_ADDR+i))
            w(M.PARTY_NICKS_ADDR+slot*11+i,r(M.PARTY_NICKS_ADDR+i))
        end
        w(M.PARTY_BASE_ADDR+slot*44+27,0x31+slot)
        w(M.PARTY_SPECIES_ADDR+slot,r(M.PARTY_SPECIES_ADDR))
    end
    w(M.PARTY_SPECIES_ADDR+3,255);w(M.PARTY_COUNT_ADDR,3)
    local codec=require('gen1_party_codec')
    for slot=0,2 do assert(codec.validateBlob(M.readPartyBlob(slot),t.variant)) end
    local deposited,reason=M.depositPartyMon(2)
    assert(deposited,reason)
    t.check('PC fixture contains two party and one boxed Pokemon',M.getPartyCount()==2 and M.getBoxCount()==1)
end
local ok,err=pcall(function()
    begin('idle');frames(90)
    t.check('positive idle stack candidate exists',rows.idle.candidate>0)
    local dex=enum('event_constants.asm','EVENT_GOT_POKEDEX')
    local dexaddr,mask=a('wEventFlags')+math.floor(dex/8),2^(dex%8)
    for _,has_dex in ipairs({false,true}) do
        for index,label in ipairs({'Pokedex','Pokemon','Item','TrainerInfo','SaveReset','Option'}) do
            if has_dex or label~='Pokedex' then
                restore()
                local value=r(dexaddr)
                local present=math.floor(value/mask)%2==1
                if has_dex~=present then w(dexaddr,value+(has_dex and mask or -mask)) end
                begin((has_dex and 'dex-' or 'no-dex-')..label)
                press('Start');frames(60)
                local wanted=index-1-(has_dex and 0 or 1)
                for _=1,12 do
                    if r(a('wCurrentMenuItem'))==wanted then break end
                    press('Down')
                end
                t.check(current..' selector is exact',r(a('wCurrentMenuItem'))==wanted)
                press('A');frames(120)
                t.check(current..' native entry reached',(entered['StartMenu_'..label] or 0)>0)
                if label=='Pokemon' or label=='Item' or label=='Pokedex' then
                    press('A');frames(90)
                    press('A');frames(90)
                end
                for _=1,12 do
                    if context=='world' then break end
                    press('B');frames(30)
                end
                t.check(current..' resumes overworld',context=='world')
                t.check(current..' regains a writable checkpoint',await_checkpoint())
            end
        end
    end
    restore();begin('fly-and-pokecenter')
    seed_pc_inventory()
    w(a('wDestinationMap'),1) -- Source: VIRIDIAN_CITY, FlyWarpDataPtr at (23,26).
    local mask=2^enum('ram_constants.asm','BIT_FLY_WARP')
    local flags=r(a('wStatusFlags6'))
    if math.floor(flags/mask)%2==0 then w(a('wStatusFlags6'),flags+mask) end
    frames(360)
    t.check('real Fly map chain reaches Viridian',M.getCurrentMap()==1)
    for _=1,100 do
        step({Up=true})
        if M.getCurrentMap()~=1 then break end
    end
    frames(120)
    t.check('walked through real Pokecenter warp',M.getCurrentMap()==0x29)
    t.log(string.format('Pokecenter landing %d,%d',r(a('wXCoord')),r(a('wYCoord'))))
    -- Row 6 has the benches; the pinned blockset/collision table leaves row 5 open.
    assert(walk(3,5));assert(walk(13,5));assert(walk(13,4))
    press('Up',4);press('A');frames(90)
    for _=1,8 do
        if (entered.TextScript_PokemonCenterPC or 0)>0 then break end
        press('A');frames(60)
    end
    t.check('real Pokemon Center PC opened',(entered.TextScript_PokemonCenterPC or 0)>0)
    for _=1,14 do
        if (entered.BillsPCMenu or 0)>0 then break end
        press('A');frames(40)
    end
    t.check('real BillsPC menu reached',(entered.BillsPCMenu or 0)>0)
    client.screenshot(ROOT..'/patch/build/probe-gen1-pc-'..t.variant..'.png')
    local pc_state=memorysavestate.savecorestate()
    local actions={'Withdraw','Deposit','Release','ChangeBox'}
    if t.variant=='yellow' then actions[#actions+1]='PrintBox' end
    for index,label in ipairs(actions) do
        current=nil;memorysavestate.loadcorestate(pc_state);context='BillsPC';entered={}
        begin('PC-'..label)
        for _=1,12 do
            if r(a('wCurrentMenuItem'))==index-1 then break end
            press('Down')
        end
        press('A');frames(120)
        t.check('native PC '..label..' reached',(entered['BillsPC'..label] or 0)>0)
        if label=='Withdraw' or label=='Deposit' or label=='Release' then
            t.check(label..' actual mon selector reached',(entered.DisplayMonListMenu or 0)>0)
            press('A');frames(90)
            if label~='Release' then
                t.check(label..' native action/stats choice reached',(entered.DisplayDepositWithdrawMenu or 0)>0)
                press('Down');press('A');frames(120)
                t.check(label..' actual stats screen reached',(entered.StatusScreen or 0)>0)
            end
        elseif label=='ChangeBox' then
            for _=1,20 do
                if (entered.DisplayChangeBoxMenu or 0)>0 then break end
                press('A');frames(30)
            end
            t.check('actual twelve-box selector reached',(entered.DisplayChangeBoxMenu or 0)>0)
        elseif label=='PrintBox' then
            t.check('actual printer transmission loop reached',(entered.PrintPCBoxPage or 0)>0)
        end
        for _=1,8 do press('B');frames(30) end
        t.check(label..' closes and regains a writable checkpoint',await_checkpoint())
    end
    memorysavestate.removestate(pc_state)
    -- The original receptionist runs its real serial handshake and times out
    -- without a cable peer. This does not simulate a successful link session.
    begin('cable-receptionist')
    local value=r(dexaddr)
    if math.floor(value/(2^(dex%8)))%2==0 then w(dexaddr,value+2^(dex%8)) end
    assert(walk(11,4));assert(walk(11,3));press('Up',4);press('A')
    for _=1,24 do
        if (entered['CableClubNPC.establishConnectionLoop'] or 0)>0 then break end
        press('A');frames(30)
    end
    t.check('original receptionist and real serial handshake execute',(entered.CableClubNPC or 0)>0
        and (entered['CableClubNPC.establishConnectionLoop'] or 0)>0)
    for _=1,24 do
        press('B');frames(30)
        if context=='world' then break end
    end
    t.check('serial timeout returns to a writable checkpoint',await_checkpoint())
    restore();begin('poison-blackout')
    w(a('wPartyMon1Status'),8);w(a('wPartyMon1HP'),0);w(a('wPartyMon1HP')+1,1)
    for i=1,40 do
        frames(24,{[i%2==0 and 'Left' or 'Right']=true})
        if M.read_u16_be(a('wPartyMon1HP'))==0 then break end
    end
    for _=1,180 do
        press('A',6)
        if (entered.HandleBlackOut or 0)>0 and context=='world' then break end
    end
    t.check('actual cartridge HandleBlackOut executed',(entered.HandleBlackOut or 0)>0)
    t.check('blackout returns to healed overworld',context=='world' and M.read_u16_be(a('wPartyMon1HP'))>0)
    t.check('blackout recovery regains a writable checkpoint',await_checkpoint())
    restore();begin('reset-title')
    client.reboot_core();context='reset';frames(900)
    t.check('reset/title never qualifies',rows[current].candidate==0)

end)
current=nil
for label,row in pairs(rows) do
    local parts={}
    for ctx,count in pairs(row.contexts) do parts[#parts+1]=ctx..'='..count end
    table.sort(parts)
    t.log(string.format('%s: frames=%d old=%d stack=%d candidate=%d nonworld=%d; %s',
        label,row.frames,row.old,row.stack,row.candidate,row.bad,table.concat(parts,',')))
    t.check(label..' no non-world candidate',row.bad==0)
end
for _,id in ipairs(hooks) do event.unregisterbyid(id) end
memorysavestate.removestate(boot)
t.check('live overworld checkpoint matrix completed',ok,tostring(err))
t.finish()
