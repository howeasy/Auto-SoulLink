"""Read-only source-hook identity qualification using actual generated ROM sites."""
import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaError

from tests.unit.test_client_state_store import runtime as runtime
from tests.unit.test_gen1_native_runtime_injection import lua as lua

ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((ROOT / 'data/games/gen1_rby/identity_sites.json').read_text())


def setup(lua, variant='yellow', tutorial='4'):
    lua.globals().profile_json = json.dumps(DATA)
    lua.globals().variant = variant
    lua.globals().tutorial_type = tutorial
    lua.execute('''
        package.loaded.gen1_identity_sites=assert(JSON.decode(profile_json))
        profile=package.loaded.gen1_identity_sites.titles[variant];r=profile.ram
        ram={};rom={};hooks={};regs={PC=0,SP=0xD000};writes_before=writes
        function put(address,text,target)
            target=target or ram
            for i=1,#text,2 do target[address+(i-1)/2]=tonumber(text:sub(i,i+1),16)end
        end
        function get(address,n)
            local out={};for i=0,n-1 do out[#out+1]=string.format('%02X',ram[address+i]or 0)end
            return table.concat(out)
        end
        function regpair(a,b,value)regs[a]=math.floor(value/256);regs[b]=value%256 end
        function stack(address,value)ram[address]=value%256;ram[address+1]=math.floor(value/256)end
        original='808182838450D1D2D3D4D5';put(r.wPlayerName,original);put(r.wPlayerID,'1234')
        name=profile.names[tutorial_type]
        ram[r.wBattleType]=tonumber(tutorial_type);ram[r.wIsInBattle]=1;ram[r.wCurMap]=name.map
        ram[r.wPartyCount]=0;ram[r.wPalletTownCurScript]=name.pallet_script or 0
        put(profile.copy.rom_offset,profile.copy.expected_hex,rom)
        for _,site in pairs(profile.sites)do put(site.rom_offset,site.expected_hex,rom)end
        for _,literal in pairs(profile.names)do
            put(profile.sites.borrow_begin.bank*0x4000+literal.address-0x4000,literal.hex,rom)
        end
        memory={read_u8=function(a,d)return (d=='ROM'and rom or ram)[a]or 0 end}
        context={context_generation=string.rep('1',32),physical_instance=string.rep('2',32)}
        romhash=string.rep('a',40);gameinfo={getromhash=function()return romhash end}
        emu={getregister=function(k)return assert(regs[k],k)end}
        event={on_bus_exec=function(fn,address,label)hooks[label]=fn;return label end,
            onloadstate=function(fn,label)hooks[label]=fn;return label end,
            onexit=function(fn,label)hooks[label]=fn;return label end,
            unregisterbyid=function(id)hooks[id]=nil end}
        guard=require('gen1_identity_guard').new{variant=variant,final_sha1=romhash,context=function()return context end}
        function hit(kind,source,destination)
            local site=profile.sites[kind];regs.PC=site.address;ram[r.hLoadedROMBank]=site.bank
            put(site.address,site.expected_hex)
            if source then regpair('H','L',source);regpair('D','E',destination);regpair('B','C',11)end
            hooks['slink-identity-'..kind]()
            guard.check()
        end
        function begin_borrow()
            hit('backup_begin',r.wPlayerName,r.wLinkEnemyTrainerName)
            put(r.wLinkEnemyTrainerName,original);hit('backup_done')
            hit('borrow_begin',name.address,r.wPlayerName)
        end
        function finish_borrow()
            put(r.wPlayerName,name.hex);hit('borrow_done')
        end
        function begin_restore()
            hit('restore_begin',r.wLinkEnemyTrainerName,r.wPlayerName)
        end
        function in_copy(kind,n,before,after)
            put(r.wPlayerName,after:sub(1,n*2)..before:sub(n*2+1))
            regs.PC=profile.copy.address;regs.SP=0xCFFE;stack(regs.SP,profile.sites[kind..'_done'].address)
        end
    ''')


@pytest.mark.parametrize('variant,tutorial', [('red', '1'), ('blue', '1'), ('yellow', '1'), ('yellow', '4')],
                         ids=['red-oldman', 'blue-oldman', 'yellow-oldman', 'yellow-oak'])
def test_original_borrow_restore_is_read_only(runtime, variant, tutorial):
    setup(runtime, variant, tutorial)
    runtime.execute('''
        assert(guard.check());begin_borrow();finish_borrow();assert(guard.check());begin_restore()
        put(r.wPlayerName,original);hit('restore_done');assert(guard.status().phase==nil)
        assert(writes==writes_before);guard.close();assert(next(hooks)==nil)
    ''')


@pytest.mark.parametrize('count', range(12), ids=lambda n: f'prefix-{n}')
@pytest.mark.parametrize('kind', ['borrow', 'restore'])
def test_every_copy_prefix_requires_exact_call_stack(runtime, count, kind):
    setup(runtime)
    runtime.globals().count = count
    runtime.globals().kind = kind
    runtime.execute('''
        begin_borrow()
        if kind=='restore'then finish_borrow();begin_restore()end
        in_copy(kind,count,kind=='borrow'and original or name.hex,kind=='borrow'and name.hex or original)
        assert(guard.check());regs.PC=0x1234
    ''')
    with pytest.raises(LuaError, match='qualified interval'):
        runtime.execute('guard.check()')


@pytest.mark.parametrize('mode', ['copy-irq', 'return-irq', 'forged-irq'])
def test_interrupt_boundary_proves_its_saved_copy_return(runtime, mode):
    setup(runtime)
    runtime.globals().mode = mode
    runtime.execute('''
        begin_borrow();in_copy('borrow',5,original,name.hex);regs.PC=0x40
        if mode=='return-irq'then
            put(r.wPlayerName,name.hex);regs.SP=0xCFFE;stack(regs.SP,profile.sites.borrow_done.address)
        else
            regs.SP=0xCFFC;stack(regs.SP,profile.copy.address+1)
            stack(regs.SP+2,mode=='forged-irq'and 0x1234 or profile.sites.borrow_done.address)
        end
    ''')
    if mode == 'forged-irq':
        with pytest.raises(LuaError, match='qualified interval'):
            runtime.execute('guard.check()')
    else:
        assert runtime.eval('guard.check()')


@pytest.mark.parametrize('mutation,reason', [
    ("put(r.wPlayerName,name.hex)", 'outside source-qualified'),
    ("romhash=string.rep('b',40)", 'physical context'),
    ("put(r.wPlayerID,'5678')", 'physical context'),
    ("context.context_generation=string.rep('3',32)", 'physical context'),
    ("context.physical_instance=string.rep('3',32)", 'physical context'),
    ("hooks['slink-identity-load']()", 'savestate load'),
    ("hooks['slink-identity-exit']()", 'Lua exit'),
], ids=['unobserved-name', 'rom', 'player-id', 'generation', 'instance', 'load', 'exit'])
def test_unqualified_identity_changes_latch_refusal(runtime, mutation, reason):
    setup(runtime)
    runtime.execute(mutation)
    with pytest.raises(LuaError, match=reason):
        runtime.execute('guard.check()')
    assert runtime.eval('guard.status().failed~=nil')


@pytest.mark.parametrize('mutation,reason', [
    ("put(r.wLinkEnemyTrainerName,'0000000000000000000000')", 'backup changed'),
    ("ram[r.wPartyCount]=1", 'Oak tutorial'),
    ("ram[r.wPalletTownCurScript]=4", 'Oak tutorial'),
    ("ram[r.wCurMap]=1", 'tutorial identity'),
    ("ram[r.wIsInBattle]=0", 'tutorial identity'),
    ("ram[r.wBattleType]=0", 'unqualified tutorial'),
    ("put(r.wPlayerName,original)", 'borrowed name changed'),
], ids=['backup', 'party', 'script', 'map', 'battle-end', 'type', 'early-restore'])
def test_borrow_cannot_outlive_its_source_context(runtime, mutation, reason):
    setup(runtime)
    runtime.execute('begin_borrow();finish_borrow();' + mutation)
    with pytest.raises(LuaError, match=reason):
        runtime.execute('guard.check()')


def test_missing_source_begin_and_altered_operands_are_refused(runtime):
    setup(runtime)
    with pytest.raises(LuaError, match='lacks verified backup'):
        runtime.execute("hit('borrow_begin',name.address,r.wPlayerName)")


def test_backup_instruction_operands_are_checked(runtime):
    setup(runtime)
    with pytest.raises(LuaError, match='backup operands'):
        runtime.execute("hit('backup_begin',r.wPlayerName+1,r.wLinkEnemyTrainerName)")


def test_generated_source_is_reproducible():
    from tools.gen_gen1_identity_sites import build
    assert build() == DATA


def test_native_default_identity_remains_strict(lua):
    lua.execute("mem.readPlayerName=function()return 'PROF.OAK'end")
    with pytest.raises(LuaError, match='ROM/save changed'):
        lua.execute('construct()')


@pytest.mark.parametrize('change', ['none', 'false', 'player-id', 'rom'])
def test_native_explicit_identity_witness_never_replaces_rom_or_id(lua, change):
    lua.execute("mem.readPlayerName=function()return 'PROF.OAK'end;options.identity_check=function()return true end")
    if change == 'false':
        lua.execute('options.identity_check=function()return false end')
    elif change == 'player-id':
        lua.execute('mem.readPlayerId=function()return 0x5678 end')
    elif change == 'rom':
        lua.execute("gameinfo.getromhash=function()return string.rep('0',40)end")
    if change == 'none':
        lua.execute('construct()')
    else:
        with pytest.raises(LuaError, match='ROM/save changed|cartridge differs'):
            lua.execute('construct()')

