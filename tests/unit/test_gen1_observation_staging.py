"""Detached observation composition never publishes partial rules or commands."""

import copy
import secrets

import pytest

from server import gen1_engine_signal_runtime as engine, gen1_inventory_observation as inventory
from server.gen1_hud_feedback import PRESENTATION_COMMANDS, validate_body as validate_hud_body
from server.gen1_run_config import create_runtime
from server.protocol_journal import JournalError
from server.state import LinkStatus
from tests.unit.test_gen1_engine_signal_runtime import payload
from tests.unit.test_gen1_faint_runtime import paired, signal_batch
from tests.unit.test_gen1_initial_observation import admit, observation, send
from tests.unit.test_gen1_inventory_observation import advance
from tests.unit.test_gen1_sessions import contract
from tests.unit.test_gen1_starter_settlement import enroll, source_and_checkpoint


def durable_evidence(runtime):
    return (
        tuple(runtime.journal._db.iterdump()),
        runtime.journal._db.total_changes,
        {player: {**vars(session), 'metadata': copy.deepcopy(session.metadata)}
         for player, session in runtime.gate.sessions.items()},
    )


def forbid_publication(monkeypatch, runtime):
    def forbidden(*args, **kwargs):
        raise AssertionError('staging must use caller state and cannot publish')

    monkeypatch.setattr(runtime, 'state', forbidden)
    monkeypatch.setattr(runtime.journal, 'commit', forbidden)
    monkeypatch.setattr(runtime.journal, 'event', forbidden)
    monkeypatch.setattr(runtime.journal, 'register_session', forbidden)


def physical_commands(commands):
    """Allow checked presentation feedback after, never in place of, a write."""
    assert set(commands) == {'a', 'b'}
    physical = {}
    for player, bodies in commands.items():
        seen_presentation = False
        physical[player] = []
        for body in bodies:
            if body['cmd'] in PRESENTATION_COMMANDS:
                validate_hud_body(body)
                seen_presentation = True
            else:
                assert not seen_presentation, 'physical command followed presentation feedback'
                physical[player].append(body)
    return physical


@pytest.mark.parametrize('variant', ['red', 'blue', 'yellow'])
def test_sources_and_checkpoints_compose_on_one_detached_stage(tmp_path, monkeypatch, variant):
    runtime = create_runtime(tmp_path, contract(variant, variant))
    try:
        _, initials, operations = enroll(runtime)
        values = {player: source_and_checkpoint(runtime, player, initials[player], operations[player])
                  for player in ('a', 'b')}
        stage = runtime.state()
        document = stage.document()
        before = durable_evidence(runtime)
        original_request = copy.deepcopy(values)
        forbid_publication(monkeypatch, runtime)
        records = []
        for player in ('a', 'b'):
            source, checkpoint = values[player]
            for module, event, value in (
                (engine, 'engine_signals', source),
                (inventory, 'inventory_observation', checkpoint),
            ):
                staged = module.stage_observation(
                    runtime, stage, document, player, secrets.token_hex(16),
                    {'event': event, 'payload': value},
                )
                assert set(staged) == {'entry', 'result', 'commands', 'records'}
                assert document['components'][module.COMPONENT][player] == staged['entry']
                assert physical_commands(staged['commands']) == {'a': [], 'b': []}
                assert staged['result']['ack'] == 'ACK'
                records.extend(staged['records'])
        assert len(stage.rules.links) == len(document['identities']['links']) == 1
        assert stage.rules.links[0].status == LinkStatus.ALIVE
        assert len(document['identities']['members']) == 2
        assert len(records) == 4
        assert durable_evidence(runtime) == before
        assert values == original_request
    finally:
        runtime.close()


@pytest.mark.parametrize('kind', ['engine', 'inventory'])
def test_invalid_staging_leaves_committed_state_and_sessions_untouched(tmp_path, monkeypatch, kind):
    runtime = create_runtime(tmp_path, contract('yellow', 'yellow'))
    try:
        _, initials, operations = enroll(runtime)
        source, checkpoint = source_and_checkpoint(runtime, 'a', initials['a'], operations['a'])
        if kind == 'engine':
            module = engine
            source['signals'] = [source['signals'][0]] * 2
            request = {'event': 'engine_signals', 'payload': source}
        else:
            module = inventory
            checkpoint['sequence'] = 2
            request = {'event': 'inventory_observation', 'payload': checkpoint}
        stage = runtime.state()
        document = stage.document()
        before = durable_evidence(runtime)
        forbid_publication(monkeypatch, runtime)
        with pytest.raises(JournalError):
            module.stage_observation(runtime, stage, document, 'a', secrets.token_hex(16), request)
        assert durable_evidence(runtime) == before
    finally:
        runtime.close()


def test_linked_death_stages_command_without_publishing_it(tmp_path, monkeypatch):
    runtime = create_runtime(tmp_path, contract('yellow', 'yellow'))
    try:
        paired(runtime)
        value = signal_batch(runtime, 'a')
        stage = runtime.state()
        document = stage.document()
        before = durable_evidence(runtime)
        forbid_publication(monkeypatch, runtime)
        staged = engine.stage_observation(
            runtime, stage, document, 'a', secrets.token_hex(16),
            {'event': 'engine_signals', 'payload': value},
        )
        assert stage.rules.links[0].status == LinkStatus.DEAD
        physical = physical_commands(staged['commands'])
        assert [row['cmd'] for row in physical['b']] == ['force_faint']
        assert physical['a'] == []
        assert not runtime.journal.pending_ids('a') and not runtime.journal.pending_ids('b')
        assert durable_evidence(runtime) == before
    finally:
        runtime.close()


@pytest.mark.parametrize('kind', ['engine', 'inventory'])
def test_record_wrapper_commits_once_and_replay_commits_nothing(tmp_path, monkeypatch, kind):
    runtime = create_runtime(tmp_path, contract('yellow', 'yellow'))
    try:
        owner = admit(runtime, 'a')
        initial = observation(runtime, 'a', occupied=True)
        first = secrets.token_hex(16)
        send(runtime, 'a', owner, initial, first)
        if kind == 'engine':
            module = engine
            request = {'event': 'engine_signals', 'payload': payload(runtime, 'a', ['battle_faint'])}
        else:
            module = inventory
            request = {'event': 'inventory_observation', 'payload': advance(initial, first)}
        commits = []
        original = runtime.journal.commit

        def counted(*args, **kwargs):
            commits.append((args, kwargs))
            return original(*args, **kwargs)

        monkeypatch.setattr(runtime.journal, 'commit', counted)
        operation = secrets.token_hex(16)
        result = module.record(runtime, 'a', operation, request)
        assert len(commits) == 1
        assert module.record(runtime, 'a', operation, request) == result
        assert len(commits) == 1
        runtime.state()
    finally:
        runtime.close()
