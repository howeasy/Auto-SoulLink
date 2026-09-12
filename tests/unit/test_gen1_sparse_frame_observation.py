"""Sparse frame returns attest physical boundaries without inventing inventory."""

import copy
import secrets

import pytest

from server import gen1_engine_signal_runtime as engine
from server.event_reference import make
from server.gen1_frame_runtime import (
    COMPONENT,
    boundary_from_inventory,
    bundle_boundary,
    complete,
    reserve,
    validate_boundary,
    validate_state,
)
from server.gen1_observation_provenance import semantic_receipt, stage_origin
from server.protocol import digest
from server.protocol_journal import JournalError
from tests.unit import test_gen1_frame_runtime as frame_fixtures
from tests.unit.test_gen1_frame_runtime import proof, returned

frame_setup = frame_fixtures.setup


@pytest.fixture
def sparse(frame_setup):
    runtime, document = frame_setup
    reserve(document, 'a', proof(document))
    receipt, bundle = returned(runtime, document)
    bundle['boundary'] = boundary_from_inventory(bundle['inventory'])
    bundle['inventory'] = None
    receipt['observations_digest'] = digest(bundle)
    return runtime, document, receipt, bundle


@pytest.mark.parametrize('with_signals', [False, True])
def test_sparse_return_preserves_rules_and_inventory_absence(sparse, with_signals):
    runtime, document, receipt, bundle = sparse
    if not with_signals:
        bundle['engine_signals'] = None
        receipt['observations_digest'] = digest(bundle)
    before = copy.deepcopy(document)
    disk = runtime.journal.snapshot()
    closed = complete(document, 'a', receipt, bundle)
    validate_state(document)
    assert closed['receipt']['after'] == bundle['boundary']['frame']
    assert document['components'][COMPONENT]['a']['pending_observation'] is not None
    assert document['rules'] == before['rules']
    assert document['identities'] == before['identities']
    assert document['components']['gen1-runtime'] == before['components']['gen1-runtime']
    assert 'gen1-inventory-observations' not in document['components']
    assert runtime.journal.snapshot() == disk


@pytest.mark.parametrize('fault', [
    'owner', 'process', 'bool-process', 'capability', 'unheld', 'context', 'hash', 'uppercase-hash',
    'frame', 'bool-frame', 'extra-boundary', 'missing-boundary-field', 'extra-host', 'extra-bundle',
    'missing-boundary', 'digest',
])
def test_invalid_sparse_boundary_leaves_grant_unconsumed(sparse, fault):
    _, document, receipt, bundle = sparse
    boundary = bundle['boundary']
    if fault == 'owner':
        boundary['host']['owner_id'] = 'f' * 32
    elif fault == 'process':
        boundary['host']['process_id'] += 1
    elif fault == 'bool-process':
        boundary['host']['process_id'] = True
    elif fault == 'capability':
        boundary['host']['capability_id'] = 'other'
    elif fault == 'unheld':
        boundary['host']['held'] = False
    elif fault == 'context':
        boundary['context_generation'] = 'f' * 32
    elif fault == 'hash':
        boundary['final_sha1'] = 'f' * 40
    elif fault == 'uppercase-hash':
        boundary['final_sha1'] = 'F' * 40
    elif fault == 'frame':
        boundary['frame'] += 1
    elif fault == 'bool-frame':
        boundary['frame'] = True
    elif fault == 'extra-boundary':
        boundary['permission'] = True
    elif fault == 'missing-boundary-field':
        del boundary['host']
    elif fault == 'extra-host':
        boundary['host']['trusted'] = True
    elif fault == 'extra-bundle':
        bundle['capture'] = None
    elif fault == 'missing-boundary':
        del bundle['boundary']
    if fault != 'digest':
        receipt['observations_digest'] = digest(bundle)
    else:
        receipt['observations_digest'] = 'f' * 64
    before = copy.deepcopy(document)
    with pytest.raises(JournalError):
        complete(document, 'a', receipt, bundle)
    assert document == before


@pytest.mark.parametrize('fault', ['before-range', 'past-consumed', 'context'])
def test_sparse_sources_still_require_admission_and_consumed_frame_coverage(sparse, fault):
    _, document, receipt, bundle = sparse
    if fault == 'before-range':
        bundle['engine_signals']['signals'][0]['frame'] = receipt['before']
    elif fault == 'past-consumed':
        bundle['engine_signals']['signals'][0]['frame'] = receipt['after'] + 1
    else:
        bundle['engine_signals']['context_generation'] = 'f' * 32
    receipt['observations_digest'] = digest(bundle)
    before = copy.deepcopy(document)
    with pytest.raises(JournalError):
        complete(document, 'a', receipt, bundle)
    assert document == before


def test_explicit_boundary_and_full_inventory_must_agree(frame_setup):
    runtime, document = frame_setup
    reserve(document, 'a', proof(document))
    receipt, bundle = returned(runtime, document)
    boundary = boundary_from_inventory(bundle['inventory'])
    bundle['boundary'] = boundary
    assert bundle_boundary(bundle) == boundary
    bundle['inventory']['frame'] += 1
    receipt['observations_digest'] = digest(bundle)
    before = copy.deepcopy(document)
    with pytest.raises(JournalError, match='explicit held boundary'):
        complete(document, 'a', receipt, bundle)
    assert document == before


def test_boundary_helpers_return_detached_fields_and_bind_enrollment(sparse):
    _, document, receipt, bundle = sparse
    initial = document['components']['gen1-initial-observations']['a']
    boundary = validate_boundary(bundle['boundary'], initial=initial, frame=receipt['after'])
    boundary['host']['process_id'] += 1
    assert bundle['boundary']['host'] == initial['observation']['host']


@pytest.mark.parametrize('extra_inventory_digest', [False, True])
def test_sparse_source_event_has_exact_engine_only_semantic_result(sparse, extra_inventory_digest):
    runtime, document, receipt, bundle = sparse
    stage = runtime.state()
    closed = complete(document, 'a', receipt, bundle)
    request = {'event': 'frame_complete', 'receipt': receipt, 'bundle': bundle}
    operation = secrets.token_hex(16)
    origin = make('a', operation, request)
    staged = engine.stage_observation(
        runtime, stage, document, 'a', operation, {'event': 'engine_signals', 'payload': bundle['engine_signals']},
        frame_origin=origin, frame_request=request,
    )
    result = {'ack': 'ACK', 'ordinary_execution': False, 'observations_settled': True,
              'closed_frame_digest': digest(closed), 'engine_evidence_digest': digest(staged['entry'])}
    if extra_inventory_digest:
        result['inventory_transition_digest'] = 'f' * 64
    runtime.journal.commit('a', operation, request, expected_revision=stage.journal_revision, state=document,
                           commands=staged['commands'], records=staged['records'], result=result)
    if extra_inventory_digest:
        with pytest.raises(JournalError, match='settled its observations'):
            semantic_receipt(runtime.journal, 'a', staged['entry'], 'engine_signals')
    else:
        assert semantic_receipt(runtime.journal, 'a', staged['entry'], 'engine_signals').result == staged['result']
    assert 'gen1-inventory-observations' not in document['components']


def test_sparse_frame_cannot_claim_an_unobserved_inventory_or_different_source(sparse):
    _, document, receipt, bundle = sparse
    complete(document, 'a', receipt, bundle)
    request = {'event': 'frame_complete', 'receipt': receipt, 'bundle': bundle}
    operation = secrets.token_hex(16)
    origin = make('a', operation, request)
    payload = {'observation': document['components']['gen1-initial-observations']['a']['observation']}
    with pytest.raises(JournalError, match='differs from its compound frame bundle'):
        stage_origin(document, 'a', operation, {'event': 'inventory_observation', 'payload': payload},
                     frame_origin=origin, frame_request=request)
    source = copy.deepcopy(bundle['engine_signals'])
    source['sequence'] += 1
    with pytest.raises(JournalError, match='differs from its compound frame bundle'):
        stage_origin(document, 'a', operation, {'event': 'engine_signals', 'payload': source},
                     frame_origin=origin, frame_request=request)
