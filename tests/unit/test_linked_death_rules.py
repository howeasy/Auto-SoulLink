import pytest

from server.linked_death_rules import record_linked_death, update_run_over
from server.party_grant_rules import record_exempt_party_grant
from server.protocol_journal import JournalError
from server.state import MonInfo, LinkStatus
from tests.unit.test_party_grant_rules import staged


@pytest.mark.parametrize('command',['force_faint','force_explode'])
def test_verified_death_only_queues_the_selected_physical_effect_and_retains_memorial_work(tmp_path,command):
    state=staged(tmp_path);a=MonInfo(key='same',level=5,species=25);b=MonInfo(key='same',level=5,species=25)
    record_exempt_party_grant(state,'a','gift',a);record_exempt_party_grant(state,'b','gift',b,peer=a)
    before=state.document()
    assert record_linked_death(state,'a','same',cause='battle',level=6,at='2026-09-08T00:00:00+00:00',partner_command=command) is None
    assert state.document()==before
    state.pokeballs_obtained['a']=True
    effect=record_linked_death(state,'a','same',cause='poison',level=6,at='2026-09-08T00:00:00+00:00',partner_command=command)
    assert effect['player']=='b' and effect['command']['cmd']==command
    assert state.links[0].status==LinkStatus.DEAD and state.links[0].cause=='poison'
    assert not any(state.queued_commands.values()) and all(state.pending_memorials.values())
    assert not state.run_over
    state.pokeballs_obtained['b']=True;update_run_over(state);assert state.run_over
    assert record_linked_death(state,'b','same',cause='battle',level=5,at='2026-09-08T00:00:00+00:00',partner_command=command) is None


def test_unlinked_active_death_refuses_before_mutation(tmp_path):
    state=staged(tmp_path);state.pokeballs_obtained['a']=True;before=state.document()
    with pytest.raises(JournalError):
        record_linked_death(state,'a','unknown',cause='battle',level=5,at='2026-09-08T00:00:00+00:00',partner_command='force_faint')
    assert state.document()==before


def test_ambiguous_same_player_key_refuses_without_selecting_a_pair(tmp_path):
    from server.state import LinkEntry
    state=staged(tmp_path);state.pokeballs_obtained['a']=True
    for area in ('first','second'):
        state.links.append(LinkEntry(area_id=area,a=MonInfo(key='same',species=25,level=5),
            b=MonInfo(key=area,species=25,level=5),status=LinkStatus.ALIVE))
    before=state.document()
    with pytest.raises(JournalError,match='ambiguous'):
        record_linked_death(state,'a','same',cause='battle',level=5,at='2026-09-08T00:00:00+00:00',partner_command='force_faint')
    assert state.document()==before
