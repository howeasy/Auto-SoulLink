"""Fresh JSON containers without copied domain state or hidden aliases."""

import math

import pytest

from server.json_value_copy import copy_json


def test_nested_and_repeated_containers_are_independently_detached():
    shared = {'items': [1, {'value': False}]}
    source = {'a': shared, 'b': shared, 'empty': []}
    result = copy_json(source)
    assert result == source
    result['a']['items'][1]['value'] = True
    result['empty'].append(2)
    assert source['a']['items'][1]['value'] is False
    assert result['b']['items'][1]['value'] is False
    assert source['empty'] == []


@pytest.mark.parametrize('value', [None, True, False, 0, 2**60, '', '☀', 1.5, -0.0],
                         ids=['null', 'true', 'false', 'zero', 'integer', 'empty', 'unicode', 'float', 'negative-zero'])
def test_plain_scalar_values_preserve_type_and_value(value):
    actual = copy_json(value)
    assert type(actual) is type(value) and actual == value
    if type(value) is float:
        assert math.copysign(1, actual) == math.copysign(1, value)


@pytest.mark.parametrize('value', [(), set(), b'', object(), float('nan'), float('inf'), {1: 'value'}],
                         ids=['tuple', 'set', 'bytes', 'domain-object', 'nan', 'infinity', 'integer-key'])
def test_unsupported_values_refuse(value):
    with pytest.raises(TypeError, match='JSON copy requires'):
        copy_json({'nested': [value]})


def test_builtin_subclass_cannot_smuggle_mutable_domain_state():
    class DomainName(str):
        pass

    value = DomainName('name')
    value.mutable = []
    with pytest.raises(TypeError, match='plain JSON values'):
        copy_json({'name': value})


@pytest.mark.parametrize('kind', ['list', 'dict'])
def test_cycles_refuse_with_a_bounded_error(kind):
    value = [] if kind == 'list' else {}
    if kind == 'list':
        value.append(value)
    else:
        value['cycle'] = value
    with pytest.raises(ValueError, match='nesting limit or contains a cycle'):
        copy_json(value)
