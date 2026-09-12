"""Only exact source/save decoding is reusable; authority remains fresh."""

import copy
import hashlib
import json

import pytest

from server import gen1_party_codec
from server.gen1_initial_observation import SYMBOLS, inventory, validate
from server.protocol_journal import JournalError
from tests.unit.test_gen1_initial_observation import source

SAVE = {'ot_id': '0000', 'trainer_name': 'SAME'}


@pytest.fixture(autouse=True)
def clear_cache():
    inventory.cache_clear()
    yield
    inventory.cache_clear()


@pytest.mark.parametrize('variant', ['red', 'blue', 'yellow'])
def test_exact_source_decode_is_reused_without_mutable_aliases(variant):
    point = source(variant, occupied=True)
    expected = inventory(point, SAVE)
    result = inventory(copy.deepcopy(point), dict(SAVE))
    assert result == expected and inventory.cache_info()['hits'] == 1
    result['members'][0]['key'] = 'changed'
    result['boxes'][0]['count'] = 20
    assert inventory(point, SAVE) == expected


@pytest.mark.parametrize('change', ['save', 'name', 'party', 'source-field'])
def test_changed_source_or_save_cannot_reuse_success(change):
    point = source('yellow', occupied=True)
    inventory(point, SAVE)
    save = dict(SAVE)
    if change == 'save':
        save['ot_id'] = '1234'
    elif change == 'name':
        point['fields']['name'] = '9184835000000000000000'
    elif change == 'party':
        point['fields']['party'] = '07' + '00' * 403
    else:
        del point['fields']['sprites']
    with pytest.raises(JournalError):
        inventory(point, save)
    assert inventory.cache_info()['hits'] == 0


def test_fresh_codec_bytes_invalidate_cached_decoding(tmp_path, monkeypatch):
    data = json.loads(gen1_party_codec.DATA_PATH.read_text())
    path = tmp_path / 'codec.json'
    path.write_text(json.dumps(data))
    monkeypatch.setattr(gen1_party_codec, 'DATA_PATH', path)
    point = source('yellow')
    inventory(point, SAVE)
    data['name_bytes'].remove(0x92)  # S in SAME is no longer a valid name byte.
    content = {key: value for key, value in data.items() if key != 'content_sha256'}
    data['content_sha256'] = hashlib.sha256(json.dumps(content, sort_keys=True,
        separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    path.write_text(json.dumps(data))
    with pytest.raises(gen1_party_codec.PartyCodecError, match='invalid name glyph'):
        inventory(point, SAVE)
    assert inventory.cache_info()['hits'] == 0


def test_fresh_identity_offsets_invalidate_cached_decoding(monkeypatch):
    point = source('yellow')
    inventory(point, SAVE)
    # The source name at offset zero in main is zero, so select the original
    # party-count bound via an invalid identity offset rather than invent data.
    monkeypatch.setitem(SYMBOLS['pokeyellow'], 'wPlayerID', SYMBOLS['pokeyellow']['wMainDataStart'] + 1928)
    with pytest.raises(JournalError, match='save identity differs'):
        inventory(point, SAVE)
    assert inventory.cache_info()['hits'] == 0


def test_fresh_save_layout_invalidate_cached_decoding(monkeypatch):
    point = source('yellow')
    inventory(point, SAVE)
    monkeypatch.setitem(SYMBOLS['pokeyellow'], 'wSaveFileStatus', SYMBOLS['pokeyellow']['wSaveFileStatus'] + 1)
    assert inventory(point, SAVE)['party_count'] == 0
    assert inventory.cache_info()['hits'] == 0 and inventory.cache_info()['misses'] == 2


@pytest.mark.parametrize('change', ['held', 'owner', 'frame', 'context', 'rom'])
def test_cached_inventory_does_not_cache_observation_authority(change):
    point = source('yellow')
    payload = {'schema': 'rby-initial-observation-v1', 'context_generation': 'a' * 32,
        'final_sha1': 'b' * 40, 'frame': 100, 'source': point,
        'host': {'owner_id': 'c' * 32, 'capability_id': 'bizhawk-2.11.1-gambatte-exclusive-hold-v1',
                 'process_id': 123, 'held': True}}
    metadata = {'save_identity': SAVE, 'gen1_metadata': {'physical_instance': 'c' * 32,
        'cartridge': {'variant': 'yellow', 'final_rom_sha1': 'b' * 40}}}
    binding = {'context_generation': 'a' * 32}
    validate(payload, metadata, binding)
    if change == 'held':
        payload['host']['held'] = False
    elif change == 'owner':
        payload['host']['owner_id'] = 'd' * 32
    elif change == 'frame':
        payload['frame'] = -1
    elif change == 'context':
        payload['context_generation'] = 'd' * 32
    else:
        payload['final_sha1'] = 'd' * 40
    with pytest.raises(JournalError):
        validate(payload, metadata, binding)


def test_warm_inventory_cache_does_not_skip_current_journal_record_checks(tmp_path):
    from server.gen1_run_config import create_runtime
    from tests.unit.observation_fixture import starters
    from tests.unit.test_gen1_sessions import contract

    runtime = create_runtime(tmp_path, contract('yellow', 'yellow'), free_service=True)
    try:
        starters(runtime)
        runtime.state()
        assert inventory.cache_info()['hits'] > 0
        changed = runtime.journal._db.execute("UPDATE records SET body='{}' WHERE namespace=?",
                                             ('gen1-inventory-observations',)).rowcount
        assert changed > 0
        with pytest.raises(JournalError, match='checksum mismatch'):
            runtime.state()
    finally:
        runtime.close()
