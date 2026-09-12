"""Pure proof caches preserve fresh data/receipt refusal boundaries."""

import copy

import pytest

from server import (
    gen1_bootstrap_receipt as bootstrap,
    gen1_initial_save as initial_save,
    gen1_party_codec as codec,
)
from server.gen1_run_config import create_runtime
from server.protocol_journal import JournalError
from tests.unit.test_gen1_bootstrap_receipt import fixture
from tests.unit.test_gen1_initial_observation import source
from tests.unit.test_gen1_initial_save import IDENTITY, prepared
from tests.unit.test_gen1_initial_save_runtime import acknowledgement, setup
from tests.unit.test_gen1_sessions import contract


def test_exact_bootstrap_and_initial_transforms_hit_without_shared_results():
    bootstrap.validate.cache_clear()
    initial_save.expected.cache_clear()
    initial_save.wire_payload.cache_clear()
    receipt, arguments = fixture()
    result = bootstrap.validate(receipt, **arguments)
    assert bootstrap.validate(receipt, **arguments) == result
    assert bootstrap.validate.cache_info()['hits'] == 1
    before = source('yellow')
    after = initial_save.expected(before, identity=IDENTITY)
    after['fields']['name'] = 'mutated'
    assert initial_save.expected(before, identity=IDENTITY)['fields']['name'] == before['fields']['name']
    payload = prepared('yellow')
    result = initial_save.wire_payload(payload)
    original = copy.deepcopy(result)
    result['changes'] = {}
    assert initial_save.wire_payload(payload) == original


def test_bootstrap_source_table_change_invalidates_warm_proof(monkeypatch):
    receipt, arguments = fixture()
    bootstrap.validate(receipt, **arguments)
    site = bootstrap.DATA['titles']['yellow']['sites']['begin']
    monkeypatch.setitem(site, 'address', site['address'] + 1)
    with pytest.raises(JournalError, match='site differs'):
        bootstrap.validate(receipt, **arguments)


def test_codec_file_change_invalidates_warm_proofs(tmp_path, monkeypatch):
    receipt, arguments = fixture()
    before = source('yellow')
    bootstrap.validate(receipt, **arguments)
    initial_save.expected(before, identity=IDENTITY)
    path = tmp_path / 'codec.json'
    path.write_text('{"schema":"invalid"}')
    monkeypatch.setattr(codec, 'DATA_PATH', path)
    with pytest.raises(JournalError, match='codec'):
        bootstrap.validate(receipt, **arguments)
    with pytest.raises(JournalError, match='codec'):
        initial_save.expected(before, identity=IDENTITY)


def test_changed_preimage_and_prepared_postimage_do_not_reuse_old_result():
    payload = prepared('yellow')
    initial_save.wire_payload(payload)
    corrupted = copy.deepcopy(payload)
    corrupted['after']['cart_hex'] = '00' + corrupted['after']['cart_hex'][2:]
    with pytest.raises(JournalError):
        initial_save.wire_payload(corrupted)
    receipt, arguments = fixture()
    bootstrap.validate(receipt, **arguments)
    changed = copy.deepcopy(arguments)
    changed['identity']['ot_id'] = 'ffff'
    with pytest.raises(JournalError):
        bootstrap.validate(receipt, **changed)


def test_warm_transform_cache_does_not_hide_atomic_record_corruption(tmp_path):
    runtime = create_runtime(tmp_path, contract('yellow', 'yellow'))
    try:
        setup(runtime)
        runtime.state()
        runtime.state()
        runtime.journal._db.execute("UPDATE records SET digest=? WHERE namespace='gen1-initial-save'", ('f' * 64,))
        with pytest.raises(JournalError):
            runtime.state()
    finally:
        runtime.close()


def test_file_receipt_is_rechecked_even_when_all_image_transforms_hit(tmp_path):
    from server.gen1_initial_save_runtime import COMPONENT, arguments, original_command, prepared

    runtime = create_runtime(tmp_path, contract('yellow', 'yellow'))
    try:
        setup(runtime)
        message = acknowledgement(runtime, 'a')
        document = runtime.state().document()
        command = original_command(runtime.journal, 'a', document['components'][COMPONENT]['a'])
        before = prepared(document, 'a')['before']
        initial_save.verify_receipt(command, message['receipt'], before, **arguments(document, 'a'))
        message['receipt']['file']['flushed'] = False
        with pytest.raises(JournalError, match='file proof'):
            initial_save.verify_receipt(command, message['receipt'], before, **arguments(document, 'a'))
    finally:
        runtime.close()
