# Canonical integer journal documents

lua/journal_document.lua exposes encode(document), returning canonical ASCII JSON
or nil, reason. It matches server.protocol_journal._encode's representation for
objects/arrays, strings, Booleans, null and exact integer JSON numbers. Callers hash
the returned bytes through their existing SHA256 backend.

This helper exists because the transport/local-store JSON encoder deliberately
uses UTF-8 while the Python journal uses ensure_ascii=True. Hashing those different
representations rejected valid Unicode trade metadata. Neither frozen encoder
was changed; only proof hashing opts into this helper.

The shared json_codec first validates JSON types, UTF-8, depth, size and cycles.
journal_document keeps sorted object keys and explicit empty-object/array kinds,
emits lower-case Unicode escapes and supplementary surrogate pairs, and matches
Python's short control-character escapes. Literal backslashes remain literal.
The resulting representation is bounded to4MiB.

Floating-point JSON numbers, including1.0 and negative floating zero, are outside
the contract and are refused on the qualified Lua5.4 runtime. Callers must use
integer ticks/milliseconds or opaque strings for proof fields that would otherwise
be floats. This is not a replacement for general JSON canonicalization, journal
validation, command/body validation or admission.

Gen1's native executor uses this encoding for proposal, prepared-command and
intent hashes. Existing ASCII integer document hashes are unchanged. Native
effects, durable receipt semantics, local-state encoding and transport encoding
are unchanged.

Qualification:13 actual Lua/Python differential cases cover Unicode keys/values,
gender/currency symbols, supplementary characters, DEL/control characters,
literal escape text, Windows paths, null, Boolean, empty containers, exact integer
boundaries and float refusal. The current Gen1 native integration rerun passed
all nine ordered actual RBY pairs with the complete production rule document.
That run still uses explicit offer/control fixtures and does not select a
production runtime. Reproduce the portable differential test with:

    python -m pytest tests/unit/test_journal_document.py -q
