import json

import pytest

from tests.unit.test_client_state_store import runtime  # noqa: F401
from tests.unit.test_client_journal import start
from tests.unit.test_gen1_initial_observation import admit, source
from tests.unit.test_gen1_inventory_observation import deliver, faint
from tests.unit.test_gen1_sessions import contract
from server.gen1_run_config import create_runtime
from server.gen1_inventory_observation import COMPONENT


@pytest.mark.parametrize('variant', ['red', 'blue', 'yellow'])
def test_lua_checkpoint_stream_reaches_real_server_decoding_and_durable_ack(runtime, tmp_path, variant):  # noqa: F811
    lua = runtime; start(lua)
    server = create_runtime(tmp_path, contract(variant, variant))
    try:
        owner = admit(server, 'a')
        lua.globals().physical_json = json.dumps(source(variant, occupied=True))
        lua.globals().rom_hash = server.contract['players']['a']['final_rom_sha1']
        lua.globals().variant = variant
        lua.execute('''
            frame=100;context={context_generation=string.rep('a',32)}
            emu={framecount=function()return frame end};gameinfo={getromhash=function()return rom_hash end}
            package.loaded.gen1_full_save={capture=function()return assert(JSON.decode(physical_json))end}
            Observe=require('gen1_initial_observation')
            journal=assert(Journal.open(store,new_id,Observe))
            observer=Observe.new({journal=journal,memory={isPartyWriteSafe=function()return true end},variant=variant,
                owned=function()return context end,host={status=function()return {physical_stop_verified=true,
                    owner_id=string.rep('1',32),capability_id='bizhawk-2.11.1-gambatte-exclusive-hold-v1',process_id=123}end}})
            function observe()return observer:step(true)end
        ''')
        def pending():
            return json.loads(lua.globals().disk)['document']['payload']['outbox'][0]
        from tests.unit.test_gen1_initial_observation import send
        assert lua.globals().observe() is True
        initial = pending()
        send(server, 'a', owner, initial['payload']['payload'], initial['operation_id'])
        assert lua.globals().accept(initial['operation_id'], '[]')[0] is True
        assert lua.globals().observe() is False
        lua.globals().frame = 101
        lua.globals().physical_json = json.dumps(faint(source(variant, occupied=True)))
        assert lua.globals().observe() is True
        event = pending()
        assert event['payload']['event'] == 'inventory_observation'
        deliver(server, 'a', owner, event['payload']['payload'], event['operation_id'])
        assert len(server.state().document()['components'][COMPONENT]['a']['transition']['party_hp_zero']) == 1
        assert lua.globals().accept(event['operation_id'], '[]')[0] is True
        assert lua.globals().observe() is False
        lua.globals().frame = 102
        assert lua.globals().observe() is True
        event = pending(); deliver(server, 'a', owner, event['payload']['payload'], event['operation_id'])
        assert not server.state().document()['components'][COMPONENT]['a']['transition']['party_hp_zero']
        assert not server.journal.pending_ids('b')
    finally:
        server.close()
