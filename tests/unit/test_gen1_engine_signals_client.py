import json
from pathlib import Path

import pytest

from tests.unit.test_client_state_store import runtime  # noqa: F401
from tests.unit.test_client_journal import start
from tests.unit.test_gen1_engine_signals import signal
from server.gen1_engine_signals import DATA, validate_signal


@pytest.fixture
def probe(runtime):  # noqa: F811
    lua=runtime;start(lua)
    lua.globals().data_json=json.dumps(DATA)
    lua.globals().layout_path=str(Path(__file__).resolve().parents[2]/'data/games/gen1_rby')
    lua.execute('''
        package.path=layout_path..'/?.lua;'..package.path
        package.loaded.gen1_engine_signal_data=assert(JSON.decode(data_json))
        Signals=require('gen1_engine_signals');profile=JSON.decode(data_json).titles.yellow
        bus={};rom={};hooks={};removed=0;frame=100;pc=0;sp=0xDFFE;held=true
        context={context_generation=string.rep('a',32)};hash=string.rep('f',40)
        registers={}
        emu={framecount=function()return frame end,getregister=function(name)return registers[name] or (name=='PC' and pc or sp) end}
        gameinfo={getromhash=function()return hash end}
        memory={read_u8=function(address,domain)return (domain=='ROM' and rom[address] or bus[address])or 0 end,
            read_u16_be=function(address)return (bus[address]or 0)*256+(bus[address+1]or 0)end}
        function put(address,hex,domain)
            for i=1,#hex,2 do (domain=='ROM' and rom or bus)[address+(i-1)/2]=tonumber(hex:sub(i,i+1),16)end
        end
        for _,site in pairs(profile.sites)do put(site.rom_offset,site.expected_hex,'ROM');put(site.address,site.expected_hex)end
        event={on_bus_exec=function(fn,address,name)hooks[name]={fn=fn,address=address};return name end,
            unregisterbyid=function(name)hooks[name]=nil;removed=removed+1 end}
        function create()return Signals.new({journal=journal,variant='yellow',final_sha1=hash,
            owned=function()return context end,held=function()return held end})end
        probe=create()
        function fire(kind)
            local site=profile.sites[kind];pc=site.address+(site.capture_offset or 0);bus[profile.addresses.hLoadedROMBank]=site.bank
            hooks['SLink-engine-'..kind].fn()
        end
        function flush()return pcall(function()return probe:flush()end)end
    ''')
    return lua


def load_point(lua,kind='battle_faint'):
    point=signal('yellow',kind)['point'];addresses=DATA['titles']['yellow']['addresses']
    for field,name in [('party_hex','wPartyDataStart'),('trainer_hex','wPlayerName'),('player_id_hex','wPlayerID')]:
        lua.globals().put(addresses[name],point[field],None)
    for field,name in [('map_id','wCurMap'),('battle_flag','wIsInBattle'),('active_slot','wPlayerMonNumber'),
        ('battle_species','wBattleMonSpecies'),('which','wWhichPokemon'),('mon_location','wMonDataLocation'),
        ('cur_species','wCurPartySpecies'),('cur_level','wCurEnemyLevel')]:lua.globals().bus[addresses[name]]=point[field]


def saved(lua):return json.loads(lua.globals().disk)['document']['payload']


def test_hook_is_read_only_and_survives_healing_before_durable_flush(probe):
    load_point(probe);before=probe.globals().disk
    probe.globals().fire('battle_faint');assert probe.globals().disk==before
    address=DATA['titles']['yellow']['addresses']['wPartyDataStart']
    probe.globals().bus[address+10]=20 # later healing cannot rewrite the captured witness
    assert probe.globals().flush()==(True,True)
    entry=saved(probe)['outbox'][0]['payload']['payload'];assert entry['sequence']==1
    assert validate_signal(entry['signals'][0],'yellow',{'ot_id':'1234','trainer_name':'SAME'})['kind']=='faint'
    assert probe.globals().flush()==(True,False)


def test_other_bank_does_not_generate_a_signal(probe):
    probe.execute("bus[profile.addresses.hLoadedROMBank]=255;hooks['SLink-engine-battle_faint'].fn()")
    assert probe.globals().probe.status(probe.globals().probe)['pending']==0


@pytest.mark.parametrize('fault',['context','rom','bytes','overflow'])
def test_observer_fault_latches_and_refuses_publication(probe,fault):
    load_point(probe)
    if fault=='context':probe.execute("context.context_generation=string.rep('b',32)")
    elif fault=='rom':probe.globals().hash='e'*40
    elif fault=='bytes':probe.execute("bus[profile.sites.battle_faint.address]=0")
    else:
        for _ in range(32):probe.globals().fire('battle_faint')
    probe.globals().fire('battle_faint')
    assert probe.globals().flush()[0] is False
    assert not saved(probe)['outbox']


@pytest.mark.parametrize('mode',['before','after'])
def test_uncertain_storage_cannot_clear_or_duplicate_signals(probe,mode):
    load_point(probe);probe.globals().fire('battle_faint');probe.globals().mode=mode
    assert probe.globals().flush()[0] is False
    assert probe.globals().flush()[0] is False
    assert len(saved(probe)['outbox'])==(1 if mode=='after' else 0)


def test_close_unregisters_every_hook(probe):
    probe.globals().probe.close(probe.globals().probe)
    assert probe.globals().removed==6
    assert probe.globals().flush()[0] is False


def test_probe_reads_the_battle_flag_and_opponent_between_frames_only(probe):
    addresses = DATA['titles']['yellow']['addresses']
    assert addresses['wCurOpponent'] == 0xD058
    assert DATA['titles']['red']['addresses']['wCurOpponent'] == 0xD059 == DATA['titles']['blue']['addresses']['wCurOpponent']
    probe.globals().bus[addresses['wIsInBattle']] = 2
    probe.globals().bus[addresses['wCurOpponent']] = 225
    assert json.loads(probe.eval("JSON.encode(probe:probe())")) == {'battle': 2, 'opponent': 225}
    probe.globals().held = False
    assert probe.eval("(pcall(function()return probe:probe()end))") is False
    probe.globals().held = True
    probe.globals().hash = 'e' * 40
    assert probe.eval("(pcall(function()return probe:probe()end))") is False  # the context check runs on every read


@pytest.mark.parametrize('fault',[None,'pc_destination','failed','nonball'])
def test_ball_hook_uses_actual_h_and_l_registers_and_success_carry(probe,fault):
    load_point(probe)
    addresses=DATA['titles']['yellow']['addresses'];destination=addresses['wNumBagItems']
    probe.globals().put(destination,'010405FF'+'00'*38,None)
    probe.globals().bus[addresses['wCurItem']]=20 if fault=='nonball' else 4
    probe.globals().bus[addresses['wItemQuantity']]=5
    if fault=='pc_destination':destination+=100
    probe.globals().registers['H']=destination>>8;probe.globals().registers['L']=destination&255
    probe.globals().registers['F']=0 if fault=='failed' else 16
    probe.globals().fire('bag_received')
    assert probe.globals().flush()==(True,fault is None)
    if fault is None:
        value=saved(probe)['outbox'][0]['payload']['payload']['signals'][0]
        assert validate_signal(value,'yellow',{'ot_id':'1234','trainer_name':'SAME'})['kind']=='pokeballs_obtained'


def test_save_witness_digests_the_persistent_cartram_projection(probe):
    site=DATA['titles']['yellow']['sites']['save_witness']
    probe.globals().bus[0xD087]=2  # wSaveFileStatus (yellow)
    probe.execute("cart={};memory.read_u8=function(address,domain)local d=domain=='ROM' and rom or domain=='CartRAM' and cart or bus;return d[address] or 0 end")
    probe.globals().cart[0x497]=0xEE  # sprite work buffer: outside the projection
    probe.globals().cart[0x498]=0x12;probe.globals().cart[0x7FFF]=0x34
    probe.globals().fire('save_witness')
    assert probe.globals().flush()==(True,True)
    value=saved(probe)['outbox'][0]['payload']['payload']['signals'][0]
    import hashlib
    expected=hashlib.sha256(('12'+'00'*(0x8000-0x498-2)+'34').encode()).hexdigest()
    assert value['pc']==site['address']+3 and value['point']=={'digest':expected,'projection':'cartram-0498-8000-v1','save_file_status':2}
    assert validate_signal(value,'yellow',{'ot_id':'1234','trainer_name':'SAME'})['kind']=='save_witness'


def test_save_witness_ignores_the_shared_ret_reached_from_other_banks(probe):
    probe.execute("bus[profile.addresses.hLoadedROMBank]=3;hooks['SLink-engine-save_witness'].fn()")
    assert probe.globals().probe.status(probe.globals().probe)['pending']==0
