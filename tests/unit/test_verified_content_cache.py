"""Only exact successful validations may be reused, within explicit bounds."""

import pytest

from server.protocol_journal import JournalError
from server.verified_content_cache import VerifiedContentCache


def test_exact_inputs_hit_and_results_are_detached():
    calls = []

    def validate(value, *, option):
        calls.append(value['id'])
        return {'proof': [value['id'], option]}

    cache = VerifiedContentCache(validate)
    original = {'id': 1}
    first = cache(original, option=True)
    first['proof'][0] = 999
    assert cache({'id': 1}, option=True) == {'proof': [1, True]}
    assert original == {'id': 1} and calls == [1]
    assert cache({'id': 1}, option=False) == {'proof': [1, False]}
    assert len(calls) == 2 and cache.info()['hits'] == 1


def test_dependencies_are_reread_and_changed_content_misses():
    policy = {'version': 1}
    calls = []

    def validate(value):
        calls.append(value)
        return {'proof': policy['version']}

    cache = VerifiedContentCache(validate, dependencies=lambda: policy)
    assert cache(1)['proof'] == 1
    policy['version'] = 2
    assert cache(1)['proof'] == 2 and calls == [1, 1]


def test_failures_and_dependencies_changed_during_validation_never_cache():
    calls = []

    def refuse(value):
        calls.append(value)
        raise JournalError('refused')

    cache = VerifiedContentCache(refuse)
    for _ in range(2):
        with pytest.raises(JournalError, match='refused'):
            cache(1)
    assert calls == [1, 1] and cache.info()['entries'] == 0
    policy = {'version': 1}

    def change():
        policy['version'] += 1
        return {'proof': True}

    cache = VerifiedContentCache(change, dependencies=lambda: policy)
    with pytest.raises(JournalError, match='dependencies changed'):
        cache()
    assert cache.info()['entries'] == 0


def test_entry_and_byte_limits_evict_without_rejecting_valid_result():
    cache = VerifiedContentCache(lambda value: {'proof': value}, max_entries=2, max_bytes=300)
    for value in range(3):
        assert cache(value) == {'proof': value}
    assert cache.info()['entries'] == 2 and cache.info()['bytes'] <= 300
    assert cache(0) == {'proof': 0} and cache.info()['misses'] == 4
    assert cache('x' * 1000) == {'proof': 'x' * 1000}
    assert cache.info()['entries'] == 2 and cache.info()['bytes'] <= 300
    cache.clear()
    assert cache.info() == {'entries': 0, 'bytes': 0, 'hits': 0, 'misses': 0}


@pytest.mark.parametrize('field,value', [('max_entries', True), ('max_entries', 0), ('max_bytes', False), ('max_bytes', 0)])
def test_invalid_bounds_refuse(field, value):
    with pytest.raises(ValueError):
        VerifiedContentCache(lambda: {}, **{field: value})


def test_non_json_arguments_and_corrupt_cached_result_refuse():
    cache = VerifiedContentCache(lambda value: {'proof': value})
    with pytest.raises(JournalError):
        cache(object())
    cache(1)
    key, row = next(iter(cache._entries.items()))
    cache._entries[key] = (row[0], '{}', row[2], row[3])
    with pytest.raises(JournalError, match='checksum'):
        cache(1)
