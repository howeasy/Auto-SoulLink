"""R5b-3 / R5b-3b Manager side: checkpoint proxy, confirmed-checkpoint recovery, and the save
download.

The recovery is the one place a Manager action can discard progress, so these tests pin the
refusals first (running run, no confirmed checkpoint, unknown id), then the exact resume contract
it hands `create_runtime` — with `audit_predecessor` proven NOT to run, because the checkpoint's
own state is the authority and auditing the predecessor would re-import the very progress being
discarded. The archived bytes are real: one captured checkpoint in a real PairedCheckpointStore.

R5b-3b then hardens five findings from the adversarial review of the first cut:
  F5 - a pretrade witness (any witness_kind other than the legacy save_witness) is refused before
       anything else is loaded.
  F2 - the archive a recovery trusts must be bound to THIS run: its manifest hash must equal the
       journal's own confirmed hash, its provenance must name this run/registry id, and its
       source_fingerprint must equal the CURRENT server/client source digest.
  F1/F8 - the predecessor's stopped journal is still read read-only (never through
       audit_predecessor, which audits the LATER state recovery discards) for two checks a
       rollback must not skip: no open trade, nothing left unacknowledged; the journal's final
       revision is recorded alongside the checkpoint's own.
  F3 - the predecessor is reserved (`recovering`) before any slow work, so a concurrent
       start/resume/second recovery is refused, and the reservation is released on any failure.
  F4 - a native predecessor's prepared pair is rebuilt from scratch (fastest_text via
       gen1_upr_pipeline.prepare_pair with the stored settings/seeds, canonical via
       stage_canonical_pair) rather than copied from the predecessor's directory, and the result
       must reproduce the predecessor's own contract.
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
    gen1_prepared_cartridges,
    gen1_run_config,
    gen1_run_resume,
    gen1_upr_pipeline,
    manager,
)
from server.gen1_run_config import create_runtime, open_runtime
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


def pretrade_witness(**changes):
    """F5: the tagged native-pretrade witness shape (server/paired_save_checkpoints.py's
    NATIVE_PRETRADE_WITNESS_KEYS) — never recoverable, but must be a VALID witness of its own
    kind so the checkpoint captures cleanly and the refusal is about witness_kind, not shape."""
    value = {"witness_kind": "native_pretrade", "digest": "a" * 64, "projection": PROJECTION,
              "transaction_id": secrets.token_hex(8), "command_id": secrets.token_hex(8),
              "command_sequence": 1, "context_generation": secrets.token_hex(8),
              "ready_operation_id": secrets.token_hex(16), "checkpoint_digest": "b" * 64,
              "save_receipt_digest": "c" * 64}
    value.update(changes)
    return value


def _registry_entry(run_id, **more):
    entry = {'run_id': run_id, 'name': 'Pred', 'tcp_port': 5001, 'http_port': 8081, 'status': 'stopped',
             'pid': None, 'native_trade': False, 'fastest_text': False, 'cartridges': {}}
    entry.update(dict.fromkeys(_RULE_KEYS, False))
    entry.update(more)
    return entry


def _inject_pending_command(directory):
    """A real, unacknowledged command in the outbox — the F1/F8 'pending native commands' shape —
    via the same raw `journal.commit` call gen1_checkpoint_runtime.start uses for its own
    checkpoint_upload commands, so the fixture never fabricates the sqlite row by hand."""
    runtime = open_runtime(directory)
    try:
        stage = runtime.state()
        op = secrets.token_hex(16)
        runtime.journal.commit("a", op, {"event": "test_pending_command"},
            expected_revision=stage.journal_revision, state=stage.document(),
            commands={"a": [{"cmd": "test_command"}], "b": []}, result={"ack": "ACK"})
    finally:
        runtime.close()


def _inject_open_trade(directory):
    """A real `active_trade` marker committed through the raw journal (F1/F8's other refusal)."""
    runtime = open_runtime(directory)
    try:
        stage = runtime.state()
        document = {**stage.document(), "active_trade": {"fake": "trade"}}
        op = secrets.token_hex(16)
        runtime.journal.commit("a", op, {"event": "test_open_trade"},
            expected_revision=stage.journal_revision, state=document,
            commands={"a": [], "b": []}, result={"ack": "ACK"})
    finally:
        runtime.close()


def _inject_non_terminal_trade_phase(directory):
    """A real gen1-trade recovery component, phase 'offered' (non-terminal) — the R5b
    joint-protocol §3 'pending-native-trade policy' shape, distinct from `active_trade`."""
    runtime = open_runtime(directory)
    try:
        stage = runtime.state()
        identifier = secrets.token_hex(16)
        component = {"schema": "slink-gen1-trade-recovery-v1", "transactions": {
            identifier: {"phase": "offered", "record_digest": "d" * 64,
                         "pending": {"a": [], "b": []}}}}
        document = {**stage.document(), "active_trade": identifier}
        document["components"] = {**document["components"], "gen1-trade": component}
        op = secrets.token_hex(16)
        runtime.journal.commit("a", op, {"event": "test_pending_trade_phase"},
            expected_revision=stage.journal_revision, state=document,
            commands={"a": [], "b": []}, result={"ack": "ACK"})
    finally:
        runtime.close()


def _fixture(tmp_path, monkeypatch, *, component='confirmed', witness_factory=witness,
             after_capture=None, corrupt_manifest_sha=False, provenance_overrides=None,
             registry_more=None):
    """A stopped registry run with one REAL captured checkpoint and a journal confirmation.

    `component` selects what the (monkeypatched) R5b-1 reader reports: a confirmed entry, None,
    or a component whose status is something else. Provenance and source_fingerprint are REAL
    (the actual runtime's journal run_id, and the actual current source digest) so the F2 binding
    checks pass by construction unless a test deliberately corrupts one of them.
    """
    run_id = 'run_pred'
    directory = tmp_path / run_id
    directory.mkdir(parents=True)
    spec = contract('red', 'blue')
    gen1_admission.write_contract(directory / 'rom_contract.json', spec)
    runtime = create_runtime(directory, spec)
    real_run_id = runtime.journal.run_id
    try:
        document, rules = runtime.state().document(), runtime.state().rules.document()
        rules_bytes = json.dumps(rules).encode('utf-8')
        identity_bytes = json.dumps(known_keys(document, rules)).encode('utf-8')
        # gen1_checkpoint_runtime.server_source_manifest needs a runtime-shaped object only for
        # its native_trade/free_service flags — this fixture's runtime is plain, so both False.
        source_fingerprint = digest(gen1_checkpoint_runtime.server_source_manifest(runtime))
    finally:
        runtime.close()
    request_id = secrets.token_hex(16)
    saves = {player: bytes([1 if player == 'a' else 2]) * 0x8000 for player in ('a', 'b')}
    provenance = {"run_id": real_run_id, "registry_run_id": run_id, "journal_revision": 7,
                  "request_id": request_id}
    if provenance_overrides:
        provenance.update(provenance_overrides)
    witnesses = {player: witness_factory() for player in ('a', 'b')}
    manifest = PairedCheckpointStore(directory).capture(
        players={player: {"save": saves[player], "witness": witnesses[player]} for player in ('a', 'b')},
        rules=rules_bytes, identity=identity_bytes, contract_fingerprint=digest(spec),
        source_fingerprint=source_fingerprint, provenance=provenance, allow_same_batch=True)
    if after_capture is not None:
        after_capture(directory)
    manifest_sha = gen1_checkpoint_runtime._manifest_sha256(manifest)
    if corrupt_manifest_sha:
        manifest_sha = ('1' if manifest_sha[0] == '0' else '0') + manifest_sha[1:]
    confirmed = {"checkpoint_id": manifest["checkpoint_id"], "manifest_sha256": manifest_sha,
                 "request_id": request_id}
    reported = None
    if component == 'confirmed':
        reported = {"schema": gen1_checkpoint_runtime.SCHEMA, "request_id": request_id,
                    "registry_run_id": run_id, "status": "confirmed",
                    "witnesses": witnesses, "uploads": {"a": None, "b": None},
                    "confirmed": confirmed, "intent": None}
    elif component == 'collecting':
        reported = {"schema": gen1_checkpoint_runtime.SCHEMA, "request_id": request_id,
                    "registry_run_id": run_id, "status": "collecting",
                    "witnesses": witnesses, "uploads": {"a": None, "b": None},
                    "confirmed": None, "intent": None}
    elif component in ('abandoned_after_confirmed', 'collecting_with_prior_confirmed'):
        # R5b-joint-protocol.md §3: a LATER request (a different request_id) is abandoned or
        # still collecting, but an EARLIER request's `confirmed` entry must remain authority.
        status = 'abandoned' if component == 'abandoned_after_confirmed' else 'collecting'
        reported = {"schema": gen1_checkpoint_runtime.SCHEMA, "request_id": 'later_' + request_id,
                    "registry_run_id": run_id, "status": status,
                    "witnesses": witnesses, "uploads": {"a": None, "b": None},
                    "confirmed": confirmed, "intent": None}
    monkeypatch.setattr(gen1_checkpoint_runtime, 'confirmed_checkpoints', lambda directory_: reported)
    runs = [_registry_entry(run_id, **(registry_more or {}))]
    monkeypatch.setattr(manager, 'MANAGER_DIR', str(tmp_path))
    monkeypatch.setattr(manager, '_load_registry', lambda: runs.copy())
    monkeypatch.setattr(manager, '_save_registry', lambda value: runs.__setitem__(slice(None), value))
    return {"run_id": run_id, "directory": directory, "manifest": manifest, "confirmed": confirmed,
            "saves": saves, "runs": runs, "real_run_id": real_run_id, "source_fingerprint": source_fingerprint,
            "request_id": request_id}


@pytest.mark.asyncio
async def test_recover_refuses_a_running_run(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch)
    ctx['runs'][0]['status'] = 'running'
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(match={'run_id': ctx['run_id']}))
    assert response.status == 409 and 'stop the run' in _text(response)
    assert ctx['runs'][0].get('recovered_by') is None and len(ctx['runs']) == 1


@pytest.mark.asyncio
async def test_recover_refuses_without_a_journal_confirmed_checkpoint(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch, component=None)
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(match={'run_id': ctx['run_id']}))
    assert response.status == 409 and 'no journal-confirmed checkpoint' in _text(response)
    assert len(ctx['runs']) == 1
    assert 'recovering' not in ctx['runs'][0]   # F3: released on this failure


@pytest.mark.asyncio
async def test_recover_refuses_a_checkpoint_the_journal_never_confirmed(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch)
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(
        {'checkpoint_id': 'b' * 32}, match={'run_id': ctx['run_id']}))
    assert response.status == 409 and 'not the one this journal confirmed' in _text(response)
    assert ctx['confirmed']['checkpoint_id'] != 'b' * 32 and len(ctx['runs']) == 1


@pytest.mark.asyncio
async def test_recover_builds_the_exact_resume_record_and_registers_a_successor(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch)
    calls = []
    runtime_calls = []

    def create_runtime_(directory_, contract_, **options):
        calls.append((Path(directory_), contract_, options))
        runtime_calls.append(options)
        return _Runtime()

    monkeypatch.setattr(gen1_run_config, 'create_runtime', create_runtime_)
    monkeypatch.setattr(gen1_run_resume, 'audit_predecessor',
                        lambda *args, **kwargs: pytest.fail('recovery must not audit the predecessor'))
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(match={'run_id': ctx['run_id']}))
    payload = json.loads(response.text)
    assert response.status == 200 and payload['ok'] is True
    assert payload['checkpoint_id'] == ctx['confirmed']['checkpoint_id']
    assert payload['downloads'] == {'a': f"/api/runs/{payload['run']['run_id']}/recovery-save/a",
                                    'b': f"/api/runs/{payload['run']['run_id']}/recovery-save/b"}
    assert len(calls) == 1
    _directory_, contract_, options = calls[0]
    record = options['resume']
    assert set(record) == {'from_run', 'required', 'rules', 'contract_hash', 'identities'}
    assert record['from_run'] == ctx['run_id'] and record['contract_hash'] == ctx['manifest']['contract_fingerprint']
    for player in ('a', 'b'):
        witness_ = ctx['manifest']['players'][player]['witness']
        assert record['required'][player] == {'digest': witness_['digest'], 'projection': witness_['projection'],
                                              'witness_index': witness_['index'],
                                              'operation_id': witness_['operation_id']}
    assert json.loads(json.dumps(record['rules'])) == json.loads(Path(
        ctx['directory'] / 'checkpoints' / ctx['confirmed']['checkpoint_id'] / 'rules.json').read_text())
    successor = payload['run']
    assert options['native_trade'] is False and _directory_ == tmp_path / successor['run_id']
    assert successor['resume'] == {'from_run': ctx['run_id'], 'contract_hash': record['contract_hash'],
                                   'required': record['required']}
    recovered_from = successor['recovered_from']
    assert recovered_from['run_id'] == ctx['run_id'] and recovered_from['checkpoint_id'] == ctx['confirmed']['checkpoint_id']
    assert recovered_from['manifest_sha256'] == ctx['confirmed']['manifest_sha256']
    assert recovered_from['discarded_after_revision'] == 7   # F1/F8: renamed from discarded_through_revision
    assert isinstance(recovered_from['discarded_through_revision'], int) and recovered_from['discarded_through_revision'] >= 0
    assert ctx['runs'][0]['recovered_by'] == successor['run_id'] and len(ctx['runs']) == 2
    assert 'recovering' not in ctx['runs'][0]   # F3: released on success (folded into recovered_by)


@pytest.mark.asyncio
async def test_recovery_save_streams_the_archived_bytes_with_their_hash(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch)

    def create_runtime_(directory_, contract_, **options):
        return _Runtime()

    monkeypatch.setattr(gen1_run_config, 'create_runtime', create_runtime_)
    recovered = json.loads((await manager.RunManager('127.0.0.1').handle_recover(
        Request(match={'run_id': ctx['run_id']}))).text)['run']
    handler = manager.RunManager('127.0.0.1')
    response = await handler.handle_recovery_save(Request(match={'run_id': recovered['run_id'], 'player': 'b'}))
    assert response.status == 200 and response.body == ctx['saves']['b']
    assert response.headers['X-SLink-Save-SHA256'] == hashlib.sha256(ctx['saves']['b']).hexdigest()
    assert response.headers['Content-Disposition'] == 'attachment; filename="b.SaveRAM"'
    assert (await handler.handle_recovery_save(Request(match={'run_id': ctx['run_id'], 'player': 'b'}))).status == 404
    assert (await handler.handle_recovery_save(
        Request(match={'run_id': recovered['run_id'], 'player': 'c'}))).status == 404
    assert ctx['confirmed']['checkpoint_id'] in ctx['runs'][1]['recovered_from']['checkpoint_id']


@pytest.mark.asyncio
async def test_start_refuses_a_predecessor_that_was_recovered(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch)
    ctx['runs'][0]['recovered_by'] = 'run_successor'
    response = await manager.RunManager('127.0.0.1').handle_start(Request(match={'run_id': ctx['run_id']}))
    assert response.status == 409 and 'recovered' in _text(response)


# ---------------------------------------------------------------------------------------------
# F5: refuse a pretrade checkpoint before loading anything else.
# ---------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recover_refuses_a_pretrade_checkpoint(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch, witness_factory=pretrade_witness)
    monkeypatch.setattr(gen1_run_config, 'create_runtime',
        lambda *a, **k: pytest.fail('a pretrade checkpoint must never reach create_runtime'))
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(match={'run_id': ctx['run_id']}))
    assert response.status == 409 and 'pretrade checkpoint is not enabled yet' in _text(response)
    assert 'recovering' not in ctx['runs'][0] and len(ctx['runs']) == 1


def test_pretrade_checkpoint_error_flags_any_non_save_witness_kind():
    """F5's own guard, isolated: exercised directly so a defense-in-depth removal of the OTHER
    layer (resume_record_from_checkpoint's own raise) cannot mask this one going missing."""
    mixed = {"players": {"a": {"witness": witness()}, "b": {"witness": pretrade_witness()}}}
    assert manager._pretrade_checkpoint_error(mixed) == 'recovery from a pretrade checkpoint is not enabled yet'
    clean = {"players": {"a": {"witness": witness()}, "b": {"witness": witness()}}}
    assert manager._pretrade_checkpoint_error(clean) is None


def test_resume_record_from_checkpoint_has_no_native_pretrade_mapping():
    """F5: the mapping function itself refuses a pretrade witness rather than translating it —
    there is deliberately no fallback shape for it to produce."""
    manifest = {"players": {"a": pretrade_witness(), "b": witness()}, "contract_fingerprint": "x" * 64}
    manifest = {"players": {"a": {"witness": manifest["players"]["a"]}, "b": {"witness": manifest["players"]["b"]}},
                "contract_fingerprint": "x" * 64}
    checkpoint = SimpleNamespace(rules_bytes=lambda: b'{}', identity_bytes=lambda: b'{}')
    with pytest.raises(ValueError, match='pretrade checkpoint is not enabled yet'):
        manager.resume_record_from_checkpoint('run_pred', manifest, checkpoint)


# ---------------------------------------------------------------------------------------------
# F2: the archive must be bound to THIS run — manifest hash, provenance identity, source pin.
# ---------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recover_refuses_a_manifest_hash_that_does_not_match_the_journal(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch, corrupt_manifest_sha=True)
    monkeypatch.setattr(gen1_run_config, 'create_runtime',
        lambda *a, **k: pytest.fail('an unbound checkpoint must never reach create_runtime'))
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(match={'run_id': ctx['run_id']}))
    assert response.status == 409 and 'does not match the journal-confirmed hash' in _text(response)
    assert 'recovering' not in ctx['runs'][0]


@pytest.mark.asyncio
async def test_recover_refuses_provenance_minted_for_a_different_run(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch, provenance_overrides={"registry_run_id": "run_other"})
    monkeypatch.setattr(gen1_run_config, 'create_runtime',
        lambda *a, **k: pytest.fail('a checkpoint minted for another run must never reach create_runtime'))
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(match={'run_id': ctx['run_id']}))
    assert response.status == 409 and 'provenance does not match this run' in _text(response)


@pytest.mark.asyncio
async def test_recover_refuses_a_checkpoint_whose_source_fingerprint_has_drifted(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(gen1_checkpoint_runtime, 'server_source_manifest', lambda runtime_: {"drifted": True})
    monkeypatch.setattr(gen1_run_config, 'create_runtime',
        lambda *a, **k: pytest.fail('a source-drifted checkpoint must never reach create_runtime'))
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(match={'run_id': ctx['run_id']}))
    assert response.status == 409 and 'source fingerprint does not match' in _text(response)


@pytest.mark.asyncio
async def test_run_checkpoints_drops_an_unbound_checkpoint_for_a_stopped_run(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch, corrupt_manifest_sha=True)
    response = await manager.RunManager('127.0.0.1').handle_run_checkpoints(Request(match={'run_id': ctx['run_id']}))
    payload = json.loads(response.text)
    assert response.status == 200 and payload == {"ok": True, "current": None, "dropped": 1}


@pytest.mark.asyncio
async def test_recovery_save_404s_for_an_unbound_checkpoint(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch)

    def create_runtime_(directory_, contract_, **options):
        return _Runtime()
    monkeypatch.setattr(gen1_run_config, 'create_runtime', create_runtime_)
    recovered = json.loads((await manager.RunManager('127.0.0.1').handle_recover(
        Request(match={'run_id': ctx['run_id']}))).text)['run']
    # Drift the source AFTER the successor is already recorded, so the save download's own F2
    # binding check (not the recover endpoint's) is what refuses it.
    monkeypatch.setattr(gen1_checkpoint_runtime, 'server_source_manifest', lambda runtime_: {"drifted": True})
    handler = manager.RunManager('127.0.0.1')
    response = await handler.handle_recovery_save(Request(match={'run_id': recovered['run_id'], 'player': 'a'}))
    assert response.status == 404


@pytest.mark.asyncio
async def test_recover_refuses_a_checkpoint_contract_mismatch_explicitly(tmp_path, monkeypatch):
    """F2's fourth check, fail-fast: `create_runtime` would refuse the same mismatch later via
    `resume['contract_hash']`, but a checkpoint whose own contract_fingerprint disagrees with
    this run's contract is refused before any cartridge staging."""
    ctx = _fixture(tmp_path, monkeypatch)
    real_facts = manager._stopped_journal_facts

    def fake_facts(directory_):
        facts = real_facts(directory_)
        facts['spec'] = {**facts['spec'], 'contract': contract('yellow', 'yellow')}
        return facts
    monkeypatch.setattr(manager, '_stopped_journal_facts', fake_facts)
    monkeypatch.setattr(gen1_run_config, 'create_runtime',
        lambda *a, **k: pytest.fail('a contract mismatch must never reach create_runtime'))
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(match={'run_id': ctx['run_id']}))
    assert response.status == 409 and 'contract fingerprint does not match' in _text(response)


# ---------------------------------------------------------------------------------------------
# R5b-joint-protocol.md §3/§4 test 5: an earlier confirmed checkpoint survives a later
# collecting/abandoned request, and Recover racing Start over that reservation still yields
# exactly one successor.
# ---------------------------------------------------------------------------------------------

def test_confirmed_entry_returns_the_confirmed_field_regardless_of_latest_status():
    confirmed = {"checkpoint_id": "c1", "manifest_sha256": "a" * 64, "request_id": "r1"}
    for status in ("collecting", "preparing", "abandoned", "confirmed"):
        component = {"status": status, "confirmed": confirmed}
        assert manager._confirmed_entry(component) == confirmed
    # A "preparing" intent with no confirmation yet is never authority.
    assert manager._confirmed_entry({"status": "preparing", "confirmed": None}) is None
    assert manager._confirmed_entry(None) is None


@pytest.mark.asyncio
async def test_recover_uses_an_earlier_confirmed_checkpoint_after_the_latest_request_was_abandoned(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch, component='abandoned_after_confirmed')
    monkeypatch.setattr(gen1_run_config, 'create_runtime', lambda *a, **k: _Runtime())
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(match={'run_id': ctx['run_id']}))
    payload = json.loads(response.text)
    assert response.status == 200 and payload['checkpoint_id'] == ctx['confirmed']['checkpoint_id']
    assert len(ctx['runs']) == 2


@pytest.mark.asyncio
async def test_recover_races_start_while_collecting_and_yields_exactly_one_successor(tmp_path, monkeypatch):
    """§4 test 5: the LATEST checkpoint request is still collecting (the predecessor stopped
    mid-request) but an earlier confirmed checkpoint remains recoverable; a Start racing the
    reservation window is refused; and the whole race produces exactly one successor."""
    ctx = _fixture(tmp_path, monkeypatch, component='collecting_with_prior_confirmed')
    handler = manager.RunManager('127.0.0.1')
    seen = []
    real_facts = manager._stopped_journal_facts

    def spy(directory_):
        seen.append(json.loads(asyncio.run(handler.handle_start(Request(match={'run_id': ctx['run_id']}))).text))
        return real_facts(directory_)
    monkeypatch.setattr(manager, '_stopped_journal_facts', spy)
    monkeypatch.setattr(gen1_run_config, 'create_runtime', lambda *a, **k: _Runtime())
    response = await handler.handle_recover(Request(match={'run_id': ctx['run_id']}))
    assert response.status == 200
    assert len(seen) == 1 and seen[0]['ok'] is False and 'being recovered' in seen[0]['error']
    assert len(ctx['runs']) == 2   # predecessor + exactly one successor, never two
    assert sum(1 for run in ctx['runs'] if run['run_id'] != ctx['run_id']) == 1


# ---------------------------------------------------------------------------------------------
# F1/F8: the predecessor's stopped journal — open trade, pending commands, the final revision.
# ---------------------------------------------------------------------------------------------

def test_stopped_journal_facts_refuses_an_open_trade(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch, after_capture=_inject_open_trade)
    with pytest.raises(ValueError, match='predecessor has an open trade'):
        manager._stopped_journal_facts(ctx['directory'])


def test_stopped_journal_facts_refuses_a_pending_command(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch, after_capture=_inject_pending_command)
    with pytest.raises(ValueError, match='predecessor has pending native commands'):
        manager._stopped_journal_facts(ctx['directory'])


def test_stopped_journal_facts_refuses_a_non_terminal_trade_phase_as_an_open_trade(tmp_path, monkeypatch):
    """R5b-joint-protocol.md §3: 'the pending-native-trade policy forbids rollback'. There is no
    separate check for this: `gen1_trade_recovery.transactions()` enforces that a non-terminal
    phase entry requires `active_trade == identifier` (server/gen1_trade_recovery.py:49-50), so
    the existing `active_trade is not None` refusal already covers it — proven here by injecting
    a real non-terminal transaction and confirming the SAME 'open trade' message fires."""
    ctx = _fixture(tmp_path, monkeypatch, after_capture=_inject_non_terminal_trade_phase)
    with pytest.raises(ValueError, match='predecessor has an open trade'):
        manager._stopped_journal_facts(ctx['directory'])


def test_stopped_journal_facts_reports_the_final_revision(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch)
    facts = manager._stopped_journal_facts(ctx['directory'])
    assert isinstance(facts['final_revision'], int) and facts['final_revision'] >= 0
    assert facts['spec']['run_id'] == ctx['real_run_id']


@pytest.mark.asyncio
async def test_recover_refuses_a_predecessor_with_an_open_trade(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch, after_capture=_inject_open_trade)
    monkeypatch.setattr(gen1_run_config, 'create_runtime',
        lambda *a, **k: pytest.fail('an open trade must never reach create_runtime'))
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(match={'run_id': ctx['run_id']}))
    assert response.status == 409 and 'predecessor has an open trade' in _text(response)
    assert 'recovering' not in ctx['runs'][0]


@pytest.mark.asyncio
async def test_recover_refuses_a_predecessor_with_pending_native_commands(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch, after_capture=_inject_pending_command)
    monkeypatch.setattr(gen1_run_config, 'create_runtime',
        lambda *a, **k: pytest.fail('pending commands must never reach create_runtime'))
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(match={'run_id': ctx['run_id']}))
    assert response.status == 409 and 'predecessor has pending native commands' in _text(response)


# ---------------------------------------------------------------------------------------------
# F3: reserve the predecessor before any slow work; release on any failure.
# ---------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_start_attempted_while_recovering_is_refused(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch)
    handler = manager.RunManager('127.0.0.1')
    seen = []
    real_facts = manager._stopped_journal_facts

    def spy(directory_):
        # Runs inside handle_recover's own asyncio.to_thread call, while the reservation is held.
        seen.append(json.loads(asyncio.run(handler.handle_start(Request(match={'run_id': ctx['run_id']}))).text))
        return real_facts(directory_)
    monkeypatch.setattr(manager, '_stopped_journal_facts', spy)
    monkeypatch.setattr(gen1_run_config, 'create_runtime', lambda *a, **k: _Runtime())
    response = await handler.handle_recover(Request(match={'run_id': ctx['run_id']}))
    assert response.status == 200
    assert len(seen) == 1 and seen[0]['ok'] is False and 'being recovered' in seen[0]['error']


@pytest.mark.asyncio
async def test_a_second_recovery_is_refused_while_one_is_in_flight(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch)
    handler = manager.RunManager('127.0.0.1')
    seen = []
    real_facts = manager._stopped_journal_facts

    def spy(directory_):
        seen.append(asyncio.run(handler.handle_recover(Request(match={'run_id': ctx['run_id']}))).status)
        return real_facts(directory_)
    monkeypatch.setattr(manager, '_stopped_journal_facts', spy)
    monkeypatch.setattr(gen1_run_config, 'create_runtime', lambda *a, **k: _Runtime())
    response = await handler.handle_recover(Request(match={'run_id': ctx['run_id']}))
    assert response.status == 200
    assert seen == [409]


@pytest.mark.asyncio
async def test_recover_releases_its_reservation_on_failure_so_a_later_start_succeeds(tmp_path, monkeypatch):
    ctx = _fixture(tmp_path, monkeypatch, component=None)   # refused: no confirmed checkpoint
    handler = manager.RunManager('127.0.0.1')
    response = await handler.handle_recover(Request(match={'run_id': ctx['run_id']}))
    assert response.status == 409
    assert 'recovering' not in ctx['runs'][0]

    async def spawn(*args, **kwargs):
        return 12345
    monkeypatch.setattr(manager, '_spawn_run', spawn)
    start_response = await handler.handle_start(Request(match={'run_id': ctx['run_id']}))
    assert start_response.status == 200   # not blocked by a stale reservation


# ---------------------------------------------------------------------------------------------
# F4: rebuild the successor's prepared pair from scratch; never copytree the predecessor's.
# ---------------------------------------------------------------------------------------------

class _FakeCartridges:
    """A fake PreparedCartridges whose .contract() is fixed at construction — enough to drive
    the F4 contract-match / contract-mismatch branches without a real cartridge image."""

    def __init__(self, directory, *, contract_value):
        self.directory = Path(directory)
        self._contract = contract_value

    def contract(self):
        return self._contract


def _native_ctx(tmp_path, monkeypatch, *, fastest_text, contract_value=None, mismatched=False):
    """A confirmed-checkpoint fixture whose (fabricated) run spec claims native_trade — F4's
    cartridge staging is exercised by faking `_stopped_journal_facts`'s spec directly, since a
    REAL native predecessor needs a real cartridge image to pass `create_runtime`'s own native
    binding (see test_manager_prepared_gen1.py's boundary test) — orthogonal to what F4 covers.
    """
    ctx = _fixture(tmp_path, monkeypatch, registry_more={'native_trade': True, 'fastest_text': fastest_text})
    native_contract = contract_value or contract('red', 'blue')
    real_facts = manager._stopped_journal_facts
    real_source_manifest = gen1_checkpoint_runtime.server_source_manifest

    def fake_facts(directory_):
        facts = real_facts(directory_)
        facts['spec'] = {**facts['spec'], 'native_trade': True, 'contract': native_contract}
        return facts
    monkeypatch.setattr(manager, '_stopped_journal_facts', fake_facts)
    # The checkpoint was captured against the fixture's plain (non-native) runtime; pin the
    # source manifest to that same shape so faking native_trade above (for F4 staging) does not
    # also — as an unrelated side effect — trip the F2 source_fingerprint check.
    monkeypatch.setattr(gen1_checkpoint_runtime, 'server_source_manifest',
        lambda runtime_: real_source_manifest(SimpleNamespace(native_trade=False, free_service=False)))
    monkeypatch.setattr(gen1_admission, 'clean_contract', lambda paths: contract('red', 'blue'))
    result_contract = contract('yellow', 'yellow') if mismatched else native_contract
    monkeypatch.setattr(gen1_prepared_cartridges, 'PreparedCartridges',
        lambda directory_: _FakeCartridges(directory_, contract_value=result_contract))
    monkeypatch.setattr(gen1_run_config, 'create_runtime', lambda *a, **k: _Runtime())
    if fastest_text:
        (ctx['directory'] / 'fastest-text.rnqs').write_bytes(b'fastest-text-settings')
    return ctx


@pytest.mark.asyncio
async def test_recover_reruns_upr_with_the_stored_fastest_text_settings_and_pinned_seeds(tmp_path, monkeypatch):
    ctx = _native_ctx(tmp_path, monkeypatch, fastest_text=True)
    calls = []

    def prepare_pair(jar, settings, sources, directory, *, seeds, java='java', custom_names=None):
        calls.append((jar, settings, sources, Path(directory), seeds))
        Path(directory).mkdir(parents=True)
    monkeypatch.setattr(gen1_upr_pipeline, 'prepare_pair', prepare_pair)
    monkeypatch.setattr(gen1_prepared_cartridges, 'stage_canonical_pair',
        lambda *a, **k: pytest.fail('the canonical pair must not be staged for fastest text'))
    monkeypatch.setenv('SLINK_UPR_JAR', 'C:/dummy/upr.jar')
    rom_a, rom_b = str(tmp_path / 'a.gb'), str(tmp_path / 'b.gb')
    (tmp_path / 'a.gb').write_bytes(b'\x00' * 16)
    (tmp_path / 'b.gb').write_bytes(b'\x00' * 16)
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(
        {'rom_a': rom_a, 'rom_b': rom_b}, match={'run_id': ctx['run_id']}))
    assert response.status == 200, _text_if_error(response)
    assert len(calls) == 1
    jar, settings, sources, _directory, seeds = calls[0]
    assert jar == 'C:/dummy/upr.jar' and settings == b'fastest-text-settings'
    assert sources == {'a': rom_a, 'b': rom_b} and seeds == {'a': '123456789', 'b': '987654321'}


@pytest.mark.asyncio
async def test_recover_stages_the_canonical_pair_without_fastest_text(tmp_path, monkeypatch):
    ctx = _native_ctx(tmp_path, monkeypatch, fastest_text=False)
    staged = []

    def stage_canonical_pair(directory, clean_paths):
        staged.append((Path(directory), clean_paths))
        Path(directory).mkdir(parents=True)
    monkeypatch.setattr(gen1_prepared_cartridges, 'stage_canonical_pair', stage_canonical_pair)
    monkeypatch.setattr(gen1_upr_pipeline, 'prepare_pair',
        lambda *a, **k: pytest.fail('UPR must not run without fastest text'))
    rom_a, rom_b = str(tmp_path / 'a.gb'), str(tmp_path / 'b.gb')
    (tmp_path / 'a.gb').write_bytes(b'\x00' * 16)
    (tmp_path / 'b.gb').write_bytes(b'\x00' * 16)
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(
        {'rom_a': rom_a, 'rom_b': rom_b}, match={'run_id': ctx['run_id']}))
    assert response.status == 200, _text_if_error(response)
    assert len(staged) == 1 and staged[0][1] == {'a': rom_a, 'b': rom_b}


@pytest.mark.asyncio
async def test_recover_refuses_a_recovered_cartridge_pair_that_does_not_match_the_predecessor_contract(tmp_path, monkeypatch):
    ctx = _native_ctx(tmp_path, monkeypatch, fastest_text=False, mismatched=True)
    monkeypatch.setattr(gen1_prepared_cartridges, 'stage_canonical_pair',
        lambda directory, clean_paths: Path(directory).mkdir(parents=True))
    rom_a, rom_b = str(tmp_path / 'a.gb'), str(tmp_path / 'b.gb')
    (tmp_path / 'a.gb').write_bytes(b'\x00' * 16)
    (tmp_path / 'b.gb').write_bytes(b'\x00' * 16)
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(
        {'rom_a': rom_a, 'rom_b': rom_b}, match={'run_id': ctx['run_id']}))
    assert response.status == 409 and 'does not match the predecessor contract' in _text(response)
    assert [p.name for p in tmp_path.iterdir() if p.is_dir() and p.name.startswith('run_') and p.name != ctx['run_id']] == []
    assert 'recovering' not in ctx['runs'][0]


@pytest.mark.asyncio
async def test_recover_refuses_a_native_recovery_missing_rom_paths(tmp_path, monkeypatch):
    ctx = _native_ctx(tmp_path, monkeypatch, fastest_text=False)
    response = await manager.RunManager('127.0.0.1').handle_recover(Request(match={'run_id': ctx['run_id']}))
    assert response.status == 409 and 'requires rom_a and rom_b' in _text(response)


def _text_if_error(response):
    if response.status != 200:
        return json.loads(response.text)
    return None


def _text(response):
    return json.loads(response.text)['error']
