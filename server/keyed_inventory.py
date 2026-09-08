"""Compare unique physical observations; matching keys do not prove logical identity."""
import copy

from server.protocol_journal import JournalError, _encode


def compare(before, after, *, limit):
    """Return deterministic additions, removals and paired rows without guessing rekeys.

    The generation validates records and supplies a capacity. Keys are scoped to
    the caller's already verified physical context. No acquisition, storage,
    evolution, death or command policy lives here.
    """
    if type(limit) is not int or not 1 <= limit <= 4096:
        raise JournalError('bounded inventory capacity required')

    def index(rows):
        if not isinstance(rows, list) or len(rows) > limit:
            raise JournalError('bounded inventory rows required')
        result = {}
        for row in rows:
            if not isinstance(row, dict):
                raise JournalError('inventory object required')
            key = row.get('key')
            if not isinstance(key, str) or not 1 <= len(key) <= 256 or not key.isprintable():
                raise JournalError('inventory key required')
            if key in result:
                raise JournalError('duplicate physical inventory key')
            _encode(row)
            result[key] = copy.deepcopy(row)
        return result

    old, new = index(before), index(after)
    return {
        'added': [new[key] for key in sorted(new.keys() - old.keys())],
        'removed': [old[key] for key in sorted(old.keys() - new.keys())],
        'matched': [{'key': key, 'before': old[key], 'after': new[key]}
                    for key in sorted(old.keys() & new.keys())],
    }
