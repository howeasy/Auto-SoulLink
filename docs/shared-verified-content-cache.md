# Successful content validation cache

`VerifiedContentCache(validator, dependencies=None, max_entries=32,
max_bytes=2097152)` memoizes a deterministic JSON validator. The decorator
`@verified_content_cache(...)` exposes the same behavior with `cache_clear()` and
`cache_info()` diagnostics.

Every call validates and canonically hashes all positional and keyword arguments
and the current dependency reader's result. A hit requires the same complete
canonical input, including dependencies. Successful results are stored as checked
JSON text and decoded into detached values on return. Exceptions are never
cached. Input or dependency changes during a computation refuse publication.
Entry and byte limits evict old values; an oversized valid result is returned
without retention.

The cache grants no execution or write authority. It must not replace fresh
journal reads, stored request/result checksums, event provenance, current owners,
or current permission checks. External validator resources must appear in the
dependency reader; a filename or modification time alone is insufficient.

RBY adopts this only for bootstrap validation, the initial-save image transform,
and its compact wire delta. Dependencies include current codec file bytes and
the actual source tables/layouts used by those functions. Initial-save receipt
fields and journal provenance remain independently checked on every call.

Tests cover detached results, changed arguments/dependencies, failed validation,
mid-validation changes, memory limits, corrupted cache content, changed RBY data
files/source tables, and corrupted journal/file receipt evidence after warming.
