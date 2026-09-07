# Validated local-state snapshot copies

`state_store.read()` returns a detached copy of its private validated document.
It preserves JSON array/object tags, empty containers, nested values and the
shared null sentinel. The already validated strings and numbers are immutable;
copying them does not serialize and parse the whole journal again.

Initial and replacement payloads still take the full JSON validation path. Open
still verifies binding, revision, exact envelope fields and checksum. Commit still
checks the disk preimage, atomically replaces it, verifies full readback and latches
ambiguous failures until close/reopen. Neither the disk schema nor those checks
changed. The document and wire cache are now private closure values; assigning
undocumented `store.document` or `store.wire` fields cannot replace them.

The first measured caller is the RBY native TCP service, where repeated copies of
prepared command/save evidence delayed cartridge frames. The mechanism contains
no cartridge data or execution authority. RR and Gen2 checked their consumers and
found no dependency on the old undocumented cache fields.

Validation includes nested Unicode, exact integers, null/false, empty arrays and
objects, detached mutation, private-cache isolation, publication/readback failures
and the existing journal/client regressions. Every generation still owns its
physical operation and release qualification.
