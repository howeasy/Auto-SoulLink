import copy

import pytest

from server.admission_context import same_admitted_context


def metadata():
    return {'player': 'a', 'save_identity': {'ot_id': '1234', 'trainer_name': 'SAME'},
            'physical': {'instance': 'one', 'cartridge': 'source'},
            'control_binding': {'session_id': 'old', 'admission_epoch': 1,
                                'binding_digest': 'old', 'context_generation': 'a' * 32}}


def test_only_transport_fields_may_change_and_inputs_are_unchanged():
    before = metadata(); after = copy.deepcopy(before)
    after['control_binding'].update(session_id='new', admission_epoch=2, binding_digest='new')
    saved = copy.deepcopy((before, after))
    assert same_admitted_context(before, after)
    assert (before, after) == saved


@pytest.mark.parametrize('fault', ['missing', 'context', 'physical', 'save', 'player', 'unknown', 'binding_extra'])
def test_changed_physical_context_or_unknown_fields_are_not_ignored(fault):
    before = metadata(); after = copy.deepcopy(before)
    if fault == 'missing': del after['control_binding']
    elif fault == 'context': after['control_binding']['context_generation'] = 'b' * 32
    elif fault == 'physical': after['physical']['instance'] = 'two'
    elif fault == 'save': after['save_identity']['trainer_name'] = 'OTHER'
    elif fault == 'player': after['player'] = 'b'
    elif fault == 'unknown': after['new_context_dimension'] = 'different'
    else: after['control_binding']['new_context_dimension'] = 'different'
    assert not same_admitted_context(before, after)


@pytest.mark.parametrize('value', [None, {}, {'control_binding': {}}, {'control_binding': {'context_generation': ''}}])
def test_missing_or_malformed_metadata_never_matches(value):
    assert not same_admitted_context(value, value)
