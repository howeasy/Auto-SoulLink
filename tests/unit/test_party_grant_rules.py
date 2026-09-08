import copy

import pytest

from server.adapters import get_adapter
from server.party_grant_rules import record_exempt_party_grant
from server.protocol_journal import JournalError
from server.staged_state import StagedSoulLinkState
from server.state import SoulLinkState, MonInfo, AreaStatus


def staged(tmp_path):
    state=SoulLinkState(data_dir=str(tmp_path),adapter=get_adapter('gen1_rby',rom_type='yellow'),
        species_lock=True,gender_lock=True,type_lock=True)
    state.rom_type='yellow'
    return StagedSoulLinkState.from_live(state,{'retired_pairs':[]})


def test_exempt_party_grants_link_without_retrieval_sound_or_clause_side_effects(tmp_path):
    state=staged(tmp_path);mon=MonInfo(key='1234:5678:54',species=25,level=5,nickname='PIKACHU')
    assert record_exempt_party_grant(state,'a','gift:first',mon) is None
    assert state.area_states['gift:first']==AreaStatus.PENDING_B
    assert not any(state.queued_commands.values())
    link=record_exempt_party_grant(state,'b','gift:first',mon,peer=mon)
    assert link.a==link.b==mon and link.a is not link.b
    assert not state.pending_captures and state.area_states['gift:first']==AreaStatus.LINKED
    assert state.party_keys=={'a':{mon.key},'b':{mon.key}}
    assert not any(state.queued_commands.values()) and not any(state.pokeballs_obtained.values())
    assert not list(tmp_path.glob('*.json'))


@pytest.mark.parametrize('fault',['peer_missing','peer_mismatch','peer_boxed','duplicate','ended','unpublished'])
def test_unproved_or_conflicting_grants_leave_the_detached_state_unchanged(tmp_path,fault):
    state=staged(tmp_path);first=MonInfo(key='1234:5678:54',species=25,level=5)
    record_exempt_party_grant(state,'a','gift:first',first)
    peer=copy.deepcopy(first);player='b';area='gift:first';mon=MonInfo(key='5678:5678:54',species=25,level=5)
    if fault=='peer_missing':peer=None
    elif fault=='peer_mismatch':peer.key='different'
    elif fault=='peer_boxed':state.party_keys['a'].clear()
    elif fault=='duplicate':player='a';area='gift:second';mon=first;peer=None
    elif fault=='ended':state.run_over=True
    else:state.queued_commands['a'].append({'cmd':'force_faint','key':first.key})
    before=state.document()
    with pytest.raises(JournalError):record_exempt_party_grant(state,player,area,mon,peer=peer)
    assert state.document()==before


def test_shared_rule_helper_refuses_a_live_file_backed_state(tmp_path):
    state=SoulLinkState(data_dir=str(tmp_path))
    with pytest.raises(JournalError):record_exempt_party_grant(state,'a','gift:first',MonInfo(key='key',species=25,level=5))
    assert not list(tmp_path.glob('*.json'))
