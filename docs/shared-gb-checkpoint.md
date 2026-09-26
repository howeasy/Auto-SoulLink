# Shared GB checkpoint evaluator

`lua/gb_checkpoint.lua` extracts PLAN §5.15c's read-only mechanics. Gen 1 and
Gen 2 supply their own facts and state/ownership policies. It grants neither
ROM admission nor a write permit and never calls a write or execution interface.

## Interface

`GB.check(spec, io, predicate)` returns `true, reason` or `false, reason`.
Missing, malformed or unavailable evidence and callback errors are refusals.
The predicate must explicitly return boolean `true`; truthy numbers are refused.

Required inputs:

- `spec.domains`: explicit named ranges `{first, limit}` with exclusive limits.
- `spec.anchors`: nonempty dense array of `{domain, address, expected_hex}`.
  Hex must be nonempty, even-length and valid. Every byte is read anew on every
  attempt; flat ROM offsets may exceed 64 KiB. No cached positive is retained.
- `spec.pc`: exact 16-bit PC; the platform register names are `PC` and `SP`.
- `spec.stack`: `{domain, minimum_sp, exclusive_end, read_bytes, words}`.
  Each word is `{offset, values={...}}`, with a distinct even offset and
  nonempty explicit 16-bit alternatives. The entire bounded read fits before
  any stack byte is read. Only declared little-endian words are read; no search.
- `io.domains()`, `io.read_u8(address, domain)`, `io.register(name)`.
- `predicate(read_u8, register)`: the game-owned state and ownership policy.
  The provided readers validate available byte/register values and domain bounds.

The caller owns synchronous execution/hold stability, admission, reset epochs,
effective banking, exclusion of concurrent owners and all game predicates.
Sharing these checks does not establish that a particular engine site is live-safe.

## Gen 1 rebind

`gen1_write_safety.new(GB).check(profile, io)` preserves the existing vanilla and
pureRGB checkpoint shapes and policy. DelayFrame/resume offsets, ROM0 anchors,
font/joypad/battle checks, serial/Cable Club/printer state, pureRGB restoration
bank and WRAM-bank choices remain inside the Gen 1 binder.

Existing standalone harness callers retain `gen1_write_safety.check(profile, io)`;
that compatibility entry loads the exact sibling `gb_checkpoint.lua`. Production
Entry explicitly injects the same evaluator. Neither path contains a second
implementation. Missing shared dependency refuses rather than reverting to old code.

The same source cut must ship `gb_checkpoint.lua`, rebind production Entry and
retain Gen 1/pureRGB independent regressions. MODEL controls do not qualify the
physical rebind. Required later lanes remain live-new-gates, duo-pairs,
inspect-purergb-overlay and duo-pairs-purergb, with liveness and refusal controls.
Rollback restores the previous binder and Entry/bundle composition together.

## Gen 2 source candidate

`gen2_write_safety.new(pack, title, io, GB, ownership, receipt)` consumes the
generated `gen2-write-checkpoint-v1` pack (`lua/gen2_write_safety.lua:627,709`).
`io.domain_size("ROM")` is additionally required. The host supplies `capture()`,
`valid(token)`, `admitted(title, rom_sha1)`, `no_conflicting_owner()`,
`mapped_rom_bank()` and `effective_wram_bank()`. No-conflicting-owner covers
save, box-load/staged writes, trade and serial leases; validity covers the
same synchronous hold, session/reset epoch and source identity. `receipt` is
optional (`:637`): omitted, the binder stays an unqualified SOURCE_CANDIDATE.

`inspect_candidate()` returns a report containing `candidate_match`,
`runtime_authorized=false`, `evidence_level="SOURCE_MODEL"` and
`physical_status="OPEN"`. It checks ROM and mapped-bus anchor bytes, the exact
pre-CheckAPressOW PC, the pack's bounded caller word, actual mapped banks and
shadow, serial control, and all fifteen proposed game predicates. Ownership is
rechecked after observations. No Gen 1 IRQ, DelayFrame or two-word stack is inherited.

**This has shipped past the source-candidate stage.** With no `receipt`,
`check(kind)` still always refuses (`:648`, `unqualified` reason). But a caller
may now pass a PHYSICAL `gen2-write-window-receipt-v2` (`M.RECEIPT_SCHEMA`,
`:16`), assembled by `tests/live/test_gen2_write_windows.py` from
`lua/tests/gen2_write_windows.lua`'s run records; `M.qualified` (`:444-490`)
recomputes every control from those raw records rather than trusting a stored
verdict, and binds title, ROM, pack commit, fixture bytes, attempt ids, CGB
mode and the harness write scopes before it trusts the receipt. `check(kind)`
then authorizes writes for exactly the kinds that receipt proved
(`M.WRITE_KINDS`: `party_hp`, `box_deposit`; `:22`, `:647-658`) — Crystal and
Gold carry their own receipts, and Silver's identical pack rows may reuse
Gold's (`:19-21`). Runtime enablement is therefore a receipt the binder
verifies field-by-field, not a stored flag or a passed MODEL test; every
other write kind, and every title/kind the receipt doesn't cover, still refuses.

## Evidence and limitations

Neutral tests exercise fresh/mutated anchors, bounded reads, wrong caller/resume,
missing domains/registers/bytes, malformed arrays/hex and predicate refusal.
Both game binders have source-shaped MODEL controls. Gen 2 checks all selected
titles and every proposed state predicate, including first-save and serial state.
No emulator is launched and no physical liveness, host hold or bank observation is
qualified by these tests. Applicable SOURCE and PHYSICAL evidence remain distinct.
