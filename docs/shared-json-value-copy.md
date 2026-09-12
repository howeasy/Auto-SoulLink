# Detached JSON value copying

`server.json_value_copy.copy_json(value)` creates fresh built-in dictionaries and
lists recursively. Shared input containers become independent output containers.
It preserves immutable scalar values, including negative floating-point zero.
It rejects domain objects and built-in subclasses, non-string keys, nonfinite
numbers, cycles and nesting beyond 32 levels.

This helper copies data; it does not validate journal schemas, checksums,
permissions or physical observations. Callers must retain those checks.
`Gen1RuntimeState` uses it only for its stored document and detached exports;
rule, identity and recovery projections are still obtained freshly. No returned
object is cached or shared between callers.

The cold-run document took approximately 0.53 ms per `deepcopy` versus 0.19 ms
for the initial JSON-specific copying prototype. With explicit type/depth checks
and fresh projections included, total document-export work per production audit
fell from 30–33 ms to roughly 19 ms. Unit controls cover nested detachment,
repeated aliases, scalar types, unsupported values and cyclic structures.
