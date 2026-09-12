"""Detach plain JSON values without domain-object deepcopy machinery.

This is a container-copy utility, not a journal validator or authority cache.
Every occurrence of a list/dict gets a fresh container, including shared inputs.
"""

import math


def copy_json(value):
    """Copy built-in JSON types; reject cycles, deep nesting and domain objects."""
    return _copy(value, 0)


def _copy(value, depth):
    if depth > 32:
        raise ValueError('JSON copy exceeds nesting limit or contains a cycle')
    kind = type(value)
    if kind is dict:
        if any(type(key) is not str for key in value):
            raise TypeError('JSON copy requires plain string object keys')
        return {key: _copy(item, depth + 1) for key, item in value.items()}
    if kind is list:
        return [_copy(item, depth + 1) for item in value]
    if value is None or kind in (str, int, bool):
        return value
    if kind is float and math.isfinite(value):
        return value
    raise TypeError('JSON copy requires plain JSON values and finite numbers')
