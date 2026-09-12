"""Bounded memoization of successful deterministic JSON validation.

This stores results, never authority. Callers must include every external data
dependency and continue reading current journal records and their provenance.
"""

from collections import OrderedDict
from functools import wraps
from threading import RLock

from server.protocol_journal import JournalError, _decode, _encode


class VerifiedContentCache:
    def __init__(self, validator, *, dependencies=None, max_entries=32, max_bytes=2 * 1024 * 1024):
        if not callable(validator) or dependencies is not None and not callable(dependencies):
            raise ValueError('deterministic validator and optional dependency reader required')
        if type(max_entries) is not int or not 1 <= max_entries <= 4096:
            raise ValueError('bounded cache entry count required')
        if type(max_bytes) is not int or not 1 <= max_bytes <= 64 * 1024 * 1024:
            raise ValueError('bounded cache byte count required')
        self.validator = validator
        self.dependencies = dependencies
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self._entries = OrderedDict()
        self._bytes = self._hits = self._misses = 0
        self._lock = RLock()

    def _key(self, args, kwargs):
        return _encode({'args': list(args), 'kwargs': kwargs,
                        'dependencies': self.dependencies() if self.dependencies else None})

    def __call__(self, *args, **kwargs):
        source, fingerprint = self._key(args, kwargs)
        with self._lock:
            cached = self._entries.get(fingerprint)
            if cached is not None and cached[0] == source:
                value = _decode(cached[1], cached[2])['value']
                self._entries.move_to_end(fingerprint)
                self._hits += 1
                return value
            self._misses += 1
        value = self.validator(*args, **kwargs)
        if self._key(args, kwargs) != (source, fingerprint):
            raise JournalError('deterministic validator inputs or dependencies changed')
        body, checksum = _encode({'value': value})
        size = len(source) + len(body)
        with self._lock:
            if size <= self.max_bytes:
                old = self._entries.pop(fingerprint, None)
                if old is not None:
                    self._bytes -= old[3]
                while self._entries and (len(self._entries) >= self.max_entries or self._bytes + size > self.max_bytes):
                    _, removed = self._entries.popitem(last=False)
                    self._bytes -= removed[3]
                self._entries[fingerprint] = (source, body, checksum, size)
                self._bytes += size
        return _decode(body, checksum)['value']

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._bytes = self._hits = self._misses = 0

    def info(self):
        with self._lock:
            return {'entries': len(self._entries), 'bytes': self._bytes, 'hits': self._hits, 'misses': self._misses}


def verified_content_cache(**options):
    def decorate(validator):
        cache = VerifiedContentCache(validator, **options)

        @wraps(validator)
        def wrapped(*args, **kwargs):
            return cache(*args, **kwargs)

        wrapped.cache_clear = cache.clear
        wrapped.cache_info = cache.info
        return wrapped

    return decorate
