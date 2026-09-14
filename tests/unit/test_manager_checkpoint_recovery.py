"""R5b Manager side: checkpoint proxy, confirmed-checkpoint recovery, and the save download.

The recovery is the one place a Manager action can discard progress, so these tests pin the
refusals first (running run, no confirmed checkpoint, unknown id), then the exact resume contract
it hands `create_runtime` — with `audit_predecessor` proven NOT to run, because the checkpoint's
own state is the authority and auditing the predecessor would re-import the very progress being
discarded. The archived bytes are real: one captured checkpoint in a real PairedCheckpointStore.
"""
import asyncio
import hashlib
import json
import secrets
from pathlib import Path
from types import SimpleNamespace

import pytest

from server import (
    gen1_admission,
    gen1_checkpoint_runtime,
    gen1_run_config,
    gen1_run_resume,
    manager,
)
from server.gen1_run_config import create_runtime
from server.gen1_run_resume import PROJECTION, known_keys
from server.paired_save_checkpoints import PairedCheckpointStore
from server.protocol import digest
from tests.unit.test_gen1_sessions import contract

_RULE_KEYS = ('species_lock', 'gender_lock', 'type_lock', 'explode_mode', 'rival_team_swap',
              'overworld_presence', 'native_messages', 'native_sounds', 'battle_calc', 'pc_trade_npc')


class Request:
    def __init__(self, body=None, *, match=None, query=None):
        self.body = body or {}
        self.match_info = match or {}
        self.query = query or {}

    async def json(self):
        return self.body


class _Runtime:
    def __init__(self):
        self.closed = False

    def state(self):
        return SimpleNamespace(rules=SimpleNamespace(**dict.fromkeys(_RULE_KEYS, False)))

    def close(self):
        self.closed = True


def witness(**changes):
    value = {"frame": 100, "digest": "a" * 64, "projection": PROJECTION, "index": 3,
             "operation_id": secrets.token_hex(16)}
    value.update(changes)
    return value


def _registry_entry(run_id, **more):
    entry = {'run_id': run_id, 'name': 'Pred', 'tcp_port': 5001, 'http_port': 8081, 'status': 'stopped',
             'pid': None, 'native_trade': False, 'fastest_text': False, 'cartridges': {}}
    entry.update(dict.fromkeys(_RULE_KEYS, False))
    entry.update(more)
    return entry


def _fixture(tmp_path, monkeypatch, *, component='confirmed'):
    """A stopped registry run with one REAL captured checkpoint and a journal confirmation.

    `component` selects what the (monkeypatched) R5b-1 reader reports: a confirmed entry, None,
    or a component whose status is something else.
    """
    run_id = 'run_pred'
    directory = tmp_path / run_id
    directory.mkdir(parents=True)
    spec = contract('red', 'blue')
    gen1_admission.write_contract(directory / 'rom_contract.json', spec)
    runtime = create_runtime(directory, spec)
    try:
        document, rules = runtime.state().document(), runtime.state().rules.document()
        rules_bytes = json.dumps(rules).encode('utf-8')
        identity_bytes = json.dumps(known_keys(document, rules)).encode('utf-8')
    finally:
        runtime.close()
    request_id = secrets.token_hex(16)
    saves = {player: bytes([1 if player == 'a' else 2]) * 0x8000 for player in ('a', 'b')}
    manifest = PairedCheckpointStore(directory).capture(
        players={player: {"save": saves[player], "witness": witness()} for player in ('a', 'b')},
        rules=rules_bytes, identity=identity_bytes, contract_fingerprint=digest(spec),
        source_fingerprint="f" * 64, provenance={"journal_revision": 7, "request_id": request_id},
        allow_same_batch=True)
    confirmed = {"checkpoint_id": manifest["checkpoint_id"],
                 "manifest_sha256": gen1_checkpoint_runtime._manifest_sha256(manifest),
                 "request_id": request_id}
    reported = None
    if component == 'confirmed':
        reported = {"schema": gen1_checkpoint_runtime.SCHEMA, "request_id": request_id,
                    "registry_run_id": run_id, "status": "confirmed",
                    "witnesses": {"a": witness(), "b": witness()}, "uploads": {"a": None, "b": None},
                    "confirmed": confirmed, "intent": None}
    elif component == 'collecting':
        reported = {"schema": gen1_checkpoint_runtime.SCHEMA, "request_id": request_id,
                    "registry_run_id": run_id, "status": "collecting",
                    "witnesses": {"a": witness(), "b": witness()}, "uploads": {"a": None, "b": None},
                    "confirmed": None, "intent": None}
    monkeypatch.setattr(gen1_checkpoint_runtime, 'confirmed_checkpoints', lambda directory_: reported)
    runs = [_registry_entry(run_id)]
    monkeypatch.setattr(manager, 'MANAGER_DIR', str(tmp_path))
    monkeypatch.setattr(manager, '_load_registry', lambda: runs.copy())
    monkeypatch.setattr(manager, '_save_registry', lambda value: runs.__setitem__(slice(None), value))
    return run_id, directory, manifest, confirmed, saves, runs


def _recover(request, run_id, tmp_path):
    return asyncio.run(manager.RunManager('127.0.0.1').handle_recover(
        Request(match={'run_id': run_id})))


@pytest.mark.asyncio
async def test_recover_refuses_a_running_run(tmp_path, monkeypatch):
    run_id, _directory, _manifest, _confirmed, _saves, runs = _fixture(tmp_path, monkeypatch)
    runs[0]['status'] = 'running'
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(match={'run_id': run_id}))
    assert response.status == 409 and 'stop the run' in _text(response)
    assert runs[0].get('recovered_by') is None and len(runs) == 1


@pytest.mark.asyncio
async def test_recover_refuses_without_a_journal_confirmed_checkpoint(tmp_path, monkeypatch):
    run_id, _directory, _manifest, _confirmed, _saves, runs = _fixture(tmp_path, monkeypatch, component=None)
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(match={'run_id': run_id}))
    assert response.status == 409 and 'no journal-confirmed checkpoint' in _text(response)
    assert len(runs) == 1


@pytest.mark.asyncio
async def test_recover_refuses_a_checkpoint_the_journal_never_confirmed(tmp_path, monkeypatch):
    run_id, _directory, _manifest, confirmed, _saves, runs = _fixture(tmp_path, monkeypatch)
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(
        {'checkpoint_id': 'b' * 32}, match={'run_id': run_id}))
    assert response.status == 409 and 'not the one this journal confirmed' in _text(response)
    assert confirmed['checkpoint_id'] != 'b' * 32 and len(runs) == 1


@pytest.mark.asyncio
async def test_recover_builds_the_exact_resume_record_and_registers_a_successor(tmp_path, monkeypatch):
    run_id, directory, manifest, confirmed, _saves, runs = _fixture(tmp_path, monkeypatch)
    calls = []
    runtime_calls = []

    def create_runtime_(directory_, contract_, **options):
        calls.append((Path(directory_), contract_, options))
        runtime_calls.append(options)
        return _Runtime()

    monkeypatch.setattr(gen1_run_config, 'create_runtime', create_runtime_)
    monkeypatch.setattr(gen1_run_resume, 'audit_predecessor',
                        lambda *args, **kwargs: pytest.fail('recovery must not audit the predecessor'))
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(match={'run_id': run_id}))
    payload = json.loads(response.text)
    assert response.status == 200 and payload['ok'] is True
    assert payload['checkpoint_id'] == confirmed['checkpoint_id']
    assert payload['downloads'] == {'a': f"/api/runs/{payload['run']['run_id']}/recovery-save/a",
                                    'b': f"/api/runs/{payload['run']['run_id']}/recovery-save/b"}
    assert len(calls) == 1
    _directory_, contract_, options = calls[0]
    record = options['resume']
    assert set(record) == {'from_run', 'required', 'rules', 'contract_hash', 'identities'}
    assert record['from_run'] == run_id and record['contract_hash'] == manifest['contract_fingerprint']
    for player in ('a', 'b'):
        witness_ = manifest['players'][player]['witness']
        assert record['required'][player] == {'digest': witness_['digest'], 'projection': witness_['projection'],
                                              'witness_index': witness_['index'],
                                              'operation_id': witness_['operation_id']}
    assert json.loads(json.dumps(record['rules'])) == json.loads(Path(
        directory / 'checkpoints' / confirmed['checkpoint_id'] / 'rules.json').read_text())
    successor = payload['run']
    assert options['native_trade'] is False and _directory_ == tmp_path / successor['run_id']
    assert successor['resume'] == {'from_run': run_id, 'contract_hash': record['contract_hash'],
                                   'required': record['required']}
    assert successor['recovered_from'] == {'run_id': run_id, 'checkpoint_id': confirmed['checkpoint_id'],
                                           'manifest_sha256': confirmed['manifest_sha256'],
                                           'discarded_through_revision': 7}
    assert runs[0]['recovered_by'] == successor['run_id'] and len(runs) == 2


@pytest.mark.asyncio
async def test_recovery_save_streams_the_archived_bytes_with_their_hash(tmp_path, monkeypatch):
    run_id, _directory, _manifest, confirmed, saves, runs = _fixture(tmp_path, monkeypatch)

    def create_runtime_(directory_, contract_, **options):
        return _Runtime()

    monkeypatch.setattr(gen1_run_config, 'create_runtime', create_runtime_)
    recovered = json.loads((await manager.RunManager('127.0.0.1').handle_recover(
        Request(match={'run_id': run_id}))).text)['run']
    handler = manager.RunManager('127.0.0.1')
    response = await handler.handle_recovery_save(Request(match={'run_id': recovered['run_id'], 'player': 'b'}))
    assert response.status == 200 and response.body == saves['b']
    assert response.headers['X-SLink-Save-SHA256'] == hashlib.sha256(saves['b']).hexdigest()
    assert response.headers['Content-Disposition'] == 'attachment; filename="b.SaveRAM"'
    assert (await handler.handle_recovery_save(Request(match={'run_id': run_id, 'player': 'b'}))).status == 404
    assert (await handler.handle_recovery_save(
        Request(match={'run_id': recovered['run_id'], 'player': 'c'}))).status == 404
    assert confirmed['checkpoint_id'] in runs[1]['recovered_from']['checkpoint_id']


@pytest.mark.asyncio
async def test_start_refuses_a_predecessor_that_was_recovered(tmp_path, monkeypatch):
    run_id, _directory, _manifest, _confirmed, _saves, runs = _fixture(tmp_path, monkeypatch)
    runs[0]['recovered_by'] = 'run_successor'
    response = await manager.RunManager('127.0.0.1').handle_start(Request(match={'run_id': run_id}))
    assert response.status == 409 and 'recovered' in _text(response)


def _text(response):
    return json.loads(response.text)['error']
