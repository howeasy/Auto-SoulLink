# Exhaustive ROM change accounting

`server/rom_change_audit.py` is a small read-only primitive with no generation
knowledge, offsets, source selection or admission decision. It complements the
checked `patch_plan` writer without authorizing mutations.

Construct `RomChangeAudit(original, candidate)` from two immutable, nonempty,
equal-size byte strings. `read(offset, size, original=False)` enforces exact
bounds. `expect(offset, bytes, label)` requires exact serialized bytes.
`value(offset, allowed, label)` validates a single byte against the caller's
allowed set. Claims may repeat identically; overlapping different domains refuse.
There is no unchecked-range exemption.

`finish()` compares every byte in the complete images and refuses any changed
byte without a validated claim. Its result contains both image hashes, size and
changed-byte counts by domain. This is change accounting only. A generation
scanner must pin the canonical source, validate each logical record, constrain
pointer roots/aliases/terminators, and derive exact expected serialization before
making claims. The result supplies no runtime or patching authority.

Qualification: eight portable tests in `tests/unit/test_rom_change_audit.py` cover
unexplained writes, wrong expected/allowed values, identical vs conflicting claims,
negative/out-of-bounds/noninteger reads, mutable input and resizing. Gen1 separately
uses it for a full 1MiB UPR audit; that binding and its cartridge tests are not part
of this shared cut.
