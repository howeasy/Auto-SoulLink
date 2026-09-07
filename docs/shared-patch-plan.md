# Checked binary write sets

`server.patch_plan.apply_spans(source, spans, protected=..., bank_size=...)`
composes immutable `PatchSpan(offset, before, after, label)` values. It validates
the entire proposed write set before constructing changed output: exact preimages,
nonempty equal-sized replacement bytes, bounds, exclusive ownership, protected
ranges and optional bank boundaries. Source bytes remain unchanged on failure.

The caller owns source identity, free-space reservations, symbol provenance,
header/checksum policy and semantic qualification. This helper neither discovers
free space nor authorizes an unknown/randomized cartridge. Protection ranges use
exclusive ends. No implicit Game Boy, GBA or other cartridge constants are present.

The RBY companion builder is the first caller. It combines source-declared native
sections with the existing R/B panel prefix, verifies that those sections reproduce
the native artifact exactly, and applies one checked set to the canonical input.
It reuses the existing UPS encoder/decoder for a byte-identical round trip.
Nine portable tests exercise composition and refusal boundaries.
