"""Explicit linked/source fixture for testing authority against real enrolled peers."""
import copy
import secrets

from server.gen1_starter_settlement import context, mon_info, cache_party
from server.identity_registry import IdentityWitness
from server.party_grant_rules import record_exempt_party_grant
from server.gen1_party_codec import PartyCodec
from server.gen1_engine_signals import DATA
from server.gen1_engine_signal_runtime import record
from tests.unit.test_gen1_engine_signals import signal
from tests.unit.test_gen1_faint_runtime import bag


def publish_death(runtime):
    stage=runtime.state();doc=stage.document();initials=doc['components']['gen1-initial-observations']
    members=[];mons={};peer=None
    for player in ('a','b'):
        initial=initials[player];variant=initial['observation']['source']['variant']
        mon=PartyCodec(variant).validate_blob(bytes.fromhex(initial['inventory']['members'][0]['blob_hex']));mons[player]=mon
        identifier=secrets.token_hex(16)
        members.append(stage.identities.acquire(identifier,identifier,IdentityWitness(context(initial,player),mon.key,mon.sha256,1))['member_id'])
        record_exempt_party_grant(stage.rules,player,'fixture_link',mon_info(mon),peer=peer);cache_party(stage.rules,player,mon)
        peer=mon_info(mon)
    stage.identities.create_link('b',secrets.token_hex(16),members)
    stage.barrier.set_history(stage.history_digest())
    runtime.journal.commit('a',secrets.token_hex(16),{'event':'explicit-linked-authority-fixture'},
        expected_revision=stage.journal_revision,state=stage.document(),commands={'a':[],'b':[]},result={'ack':'ACK'})
    initial=initials['a'];variant=initial['observation']['source']['variant']
    activation=bag(variant);faint=signal(variant)
    for item in (activation,faint):
        item['frame']=initial['observation']['frame']
        item['point']['trainer_hex']=initial['observation']['source']['fields']['name']
        item['point']['player_id_hex']=initial['metadata']['save_identity']['ot_id']
    party=bytearray.fromhex(initial['observation']['source']['fields']['party']);party[9:11]=b'\0\0'
    faint['point']['party_hex']=party.hex().upper();faint['point']['battle_species']=mons['a'].species_index
    payload={'schema':'rby-engine-signals-v1','source_sha256':DATA['sha256'],'variant':variant,
        'context_generation':initial['binding']['context_generation'],'final_sha1':initial['observation']['final_sha1'],
        'sequence':1,'signals':[activation,faint]}
    record(runtime,'a',secrets.token_hex(16),{'event':'engine_signals','payload':copy.deepcopy(payload)})
    return runtime.journal.command('b',runtime.journal.pending_ids('b')[0])
