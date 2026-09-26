# OMP P4.1a/P4.1b independent review (card gen2-O-p41ab), 2026-09-23

> **Historical record — F1-F4 were fixed.** Commit `bcb7a184` ("feat(gen2): widen mailbox census
> to the full WRAM-helper family (OMP P4.1a/b review F1-F4)") extends `_bulk_write_sites` to the
> full helper family and records `out_of_scope_by_callee` in the report (see
> `tools/gen2_mailbox_census.py:13-28`). F5-F8 were informational (no action needed).

Peer review for task `cx-a7d45607` (peer omp, orchestrator claude). READ-ONLY: this file is the only
thing written; not committed.

Frozen revisions reviewed (both ancestors of HEAD `e61ee9e1`):

| commit | content |
|---|---|
| `87836c99` | P4.1a build pipeline: tools/build_gen2_companion.py, patch/gen2/src/slink_mailbox_{crystal,goldsilver}.asm, tests/unit/test_build_gen2_companion.py, data/gen2/*_slink.{sym,map}, patch/dist/SLink-*.ups, data/gen2/overlay_provenance.json |
| `686c2a76` | P4.1b census: tools/gen2_mailbox_census.py, data/gen2/mailbox_census.json, tests/unit/test_gen2_mailbox_census.py |

The working tree carries an uncommitted follow-up (ABI copy + DelayFrame hook; tools/build_gen2_companion.py
and its test are modified, patch/gen2/src/slink.asm untracked) — noted in F8 as context, not reviewed as
frozen. Pins: pokecrystal `7a7881d`, pokegold `656583c`. No build/test was run (machine-load rule; live
lanes); all evidence below is source reading plus re-derivation of the census's own classifiers.

---

## SUMMARY

The census's PROVEN verdict holds: I re-ran its own resolvers over an extended corpus — the whole
WRAM-writing helper family it does not scan (FarCopyBytes, FarCopyWRAM, SwapBytes, InitString/InitName,
CopyDataUntil, CopyData, FarCopyBytesDouble) and **every** `ld [hli], a` occurrence (1,496 raw sites in
Crystal, 736 in Gold/Silver) — and found **zero** writers reaching `$CFD8-$CFFF` / `$C1D9-$C1FF` on all
three titles; no WRAM0 clear other than Init exists (New Game's fill stops at `$CFCB` in Crystal and
starts at `$C300` in Gold/Silver, and `ClearWRAM` is WRAMX-only). The census's *method* is narrower than
its docstring claims (helper set, loop idiom, and a silent drop of unresolvable destinations), so the
verdict should be read as bounded; the build's guard rails and sha1 chain are sound end-to-end
(lock = built = profile = admitted), and `--check` covers all ten published artifacts.

## FINDINGS

### F1 — MEDIUM: the census scans two helpers plus one exact loop idiom, not "every bulk write"

`_bulk_write_sites` matches only `call ByteFill|CopyBytes` and the exact 6-instruction inline idiom
(`tools/gen2_mailbox_census.py:163-177`, idiom at `:117-125`). The pinned corpus also writes WRAM through:

| helper | body | Crystal call sites (my probe) |
|---|---|---|
| `FarCopyBytes` | `home/gfx.asm:137` (copy de→hl from bank a) | 52 (28 dest-unresolved, 24 non-WRAM0) |
| `FarCopyWRAM` | `home/copy.asm:94` (copy hl→de in bank a) | 65 (24 unresolved, 34 non-WRAM0, 7 WRAM0) |
| `SwapBytes` | `home/copy.asm:17` (writes hl **and** de) | 1 (`mobile/mobile_40.asm:6308`, unresolved) |
| `InitString`/`InitName` | `home/string.asm:1-30` (dest = caller's hl) | 9 (1 non-WRAM0, 8 unresolved) |
| `CopyDataUntil` | `home/print_text.asm:83` | 3 (unresolved) |
| `CopyData` | `engine/gfx/color.asm:1114` | 7 (6 unresolved, 1 non-WRAM0) |
| `FarCopyBytesDouble_DoubleBankSwitch` | `home/gfx.asm:22` | 1 (unresolved) |

I classified every one of those sites (plus every `ld [hli], a` site) with the census's own
`_resolve_address`/`_resolve_length`/`_next_wram0_symbol_gap`: **0 reach either span** on C/G/S. So the
verdict is right for these pins, but the docstring's "every symbol-anchored bulk write" (`:14-17`)
overclaims: a future overlay-era writer using `farcall FarCopyBytes` would be invisible. Confidence: high
on the counts and the zero-hit result (probe output in this session); the helper/dest mapping is read
from the bodies above.

### F2 — MEDIUM: unresolvable destinations are dropped silently, not reported

`_classify` returns `None` (no record at all) when the destination operand is missing or unresolvable
(`tools/gen2_mailbox_census.py:190-196`), while the docstring only promises UNPROVEN for unresolvable
*lengths* (`:14-17`, `:224-229`). Crystal: 207/347 `ByteFill` and 205/613 `CopyBytes` sites are dropped
this way — ~75% of the helper sites are out of scope, and the committed report carries no count of them
(`data/gen2/mailbox_census.json`: crystal `w4_symbol_writers` = 197, `unproven_writers` = 0). The plan
deliberately assigns computed-pointer writes to W6, so the scope is defensible — but the artifact should
say so (an `out_of_scope` count per callee) instead of reading as "all writes checked". Confidence: high.

### F3 — LOW: the "gap to the next symbol" bound is not an upper bound for sibling fields

`_next_wram0_symbol_gap` (`:179-185`) returns the gap to the next-higher WRAM0 symbol, which the docstring
equates with the write's declared allocation (`:206-211`). For a field whose sibling is the next symbol,
the gap under-counts: `wPlaceBallsX`/`wPlaceBallsY` (`ram/wram.asm:1854-1855`) are written as a 2-byte
unit (`engine/battle/trainer_huds.asm:24-26`: `ld [hli], a` then `ld [hl], a`) while the gap X→Y is 1.
At the spans this cannot bite: the boundary symbol's gap is the whole remaining bank (C `$CFD7`→`$D000`
= 41 B, G `$C1D8`→`$C200` = 40 B), so an unresolved-length write there is UNPROVEN, not SAFE. Recommend
either wording the bound as "declared allocation, exclusive of sibling fields" or marking such records
UNPROVEN. Confidence: high on the under-count (source-cited); no impact found at the spans.

### F4 — LOW: W5 checks one symbol per title; I verified the rest by hand

`neighbours()` returns only the highest WRAM0 symbol below the span (`:258-265`): Crystal `wDaysSince`
`$CFD7`, Gold/Silver `wPCItemsScrollPosition` `$C1D8`. That is exactly the right set for the
`ld [sym], sp` case (a 2-byte store there is the only symbol-anchored store that can touch the span;
`sixteen_bit_store_hits` `:267-274` — 0 hits in the committed report, and my grep found no such store).
The *other* neighbours are covered only indirectly through W4; I checked them: all single-byte stores
(C `engine/overworld/time.asm:375,386,397,407`; G `engine/events/pokecenter_pc.asm:242-243,582-590`,
`engine/link/link.asm:466,472`, `engine/menus/main_menu.asm:27`, `engine/overworld/map_setup.asm:65`) and
no `ld hl, <neighbour>` base use anywhere in either repo (grep: 0). Confidence: high.

### F5 — Q2, no action: no WRAM0 routine other than Init clears or overwrites the spans

- New Game `_ResetWRAM`: Crystal `engine/menus/intro_menu.asm:103-106` fills `[wShadowOAM, wOptions)` —
  `$C400..$CFCB`, below `$CFD8`; Gold `engine/menus/intro_menu.asm:29-32` fills from `wShadowOAM`
  (`$C300`, `data/gen2/pokegold.sym:38843`) upward, away from `$C1D9-$C1FF`. The WRAMX fills
  (`:108-111`, `:113-116`) are outside WRAM0.
- `ClearWRAM` clears WRAMX bank 1 only (`home/init.asm:186-198`, the documented bug) — not WRAM0.
- The corpus contains exactly one region-anchored WRAM0 fill: `home/init.asm:66-75`
  (`STARTOF(WRAM0)`/`SIZEOF(WRAM0)`), which the census accepts as the lifecycle clear
  (`:187`, `:216-222`) — correct.
- Link and Crystal mobile code: my extended probe covered every helper and `ld [hli], a` site in
  `engine/link/*.asm` and `mobile/*.asm` — 0 reach the spans.
Confidence: high.

### F6 — Q3, no action: the build's guard rails and sha1 chain check out

- Wrong/dirty source is refused: `_source_check` requires a repo root, HEAD == the lock commit, and a
  clean tree including untracked files (`tools/build_gen2_syms.py:95-106`), and `fresh_copy` re-copies
  the pinned checkout for every build (`tools/build_gen2_companion.py:148-156`).
- Double-apply cannot be silent: `apply_overlay` requires the per-repo anchor exactly once and raises
  otherwise (`:126-132`); the replacement destroys the anchor, so a second pass on the same checkout
  finds 0 and raises. Covered by `tests/unit/test_build_gen2_companion.py`
  (`refuses_a_checkout_missing_the_anchor`, `..._with_the_anchor_twice`).
- `--check` compares all ten published artifacts: 3 UPS + 6 `*_slink.{sym,map}` (`:247-249`) + the
  provenance dict minus `generated` (`:250-257`); the ROMs are covered by the UPS round-trip
  (`:212-214`) and the provenance's sha1/md5/crc32.
- The sha1 it reproduces is the admitted sha1: the clean ROM must match the lock (`:205-208`), the
  committed provenance records `identical_to_clean=true` with sha1 == the lock for all three titles
  (`data/gen2/overlay_provenance.json`), and the client admits by `profile.rom_sha1`
  (`lua/gen2/entry.lua:267`) which equals the lock sha1 in `data/games/gen2_*/profile.json`.
- The overlay really linked: the committed maps/syms carry `SECTION "SLink Mailbox"` at `$cfd8-$cfff`
  (C) / `$c1d9-$c1ff` (G/S) with `wSlinkMailbox` (`data/gen2/crystal_slink.map:56254`, `gold_slink.map:39520`,
  `crystal_slink.sym:55488`) — not a stale copy of the clean map.
Confidence: high (source/artifact reading; no rebuild run).

### F7 — LOW: the equality gate is manual, and the provenance's own claim is untested

`tests/unit/test_build_gen2_companion.py` never invokes make (by design, header comment), so nothing
automated asserts `identical_to_clean == true` for the mailbox-only overlay — the exact claim the card
rests on. `--check` would catch a regression at run time (a ROM byte change shifts the UPS and the
provenance), but it is not a unit test and was not run here. Cheap addition: assert on the committed
provenance (sha1 == lock, `identical_to_clean is True` for all three outputs) — no build needed.
Confidence: high.

### F8 — context only (in flight): the DelayFrame follow-up's anchor is sound

The uncommitted follow-up adds `apply_delay_hook` for `home/delay.asm` gated on `slink.asm` being in the
applied set, plus a copy-only `patch/gb/slink_abi.inc`. I verified what can be verified without it being
committed: the anchor `DelayFrame:: / ; Wait for one frame / ld a, 1 / ld [wVBlankOccurred], a` occurs
exactly once in both pins (`pokecrystal/home/delay.asm:1-4`, `pokegold/home/delay.asm:1-4`), and the
replacement is 5 bytes for 5 (`call nn` + 2×`nop` vs `ld a,1` + `ld [a16],a`), so no symbol shifts.
Carry: the ROM0 bridge must set `wVBlankOccurred` exactly as the displaced bytes did, or every
`DelayFrame` call in the game spins forever — that obligation belongs in slink.asm's comment and the
P4.1c falsifier.

## DISAGREEMENTS

1. If the coordinator reads the census's PROVEN as "every write path is proven safe", that is stronger
   than what it establishes: it is "the ~197/176 symbol-anchored ByteFill/CopyBytes/inline-idiom writes
   are clear, and (my extension) so is the rest of the helper family and every `ld [hli], a` site"; the
   residual is computed pointers, assigned to W6.
2. The plan's W4 wording says "`ld [hli]` loop"; the implementation matches only the exact 6-instruction
   ByteFill idiom (`:117-125`). If that wording was taken as the scope, the census is narrower than the
   plan reads — the report/docstring should say "the inline ByteFill idiom".

## UNKNOWN / UNVERIFIED

- No build, `--check`, or test run in this session (machine-load rule; live lanes). The real-title
  census evidence is the committed report plus my re-derivation; the reproducibility claim rests on the
  committed provenance and the UPS round-trip, not on a rerun here.
- The dest-unresolved sites (Crystal: 449 helper sites + 966 `ld [hli], a` sites) are out of scope by
  construction; a computed pointer landing in a span cannot be excluded from source (W6's job).
- The follow-up's bridge body (`patch/gen2/src/slink.asm`, untracked) is not reviewed.
- Whether Silver's `.map`/`.sym` differ from Gold's only where the lock says (the census reports
  identical Gold/Silver numbers; I did not diff the two maps myself).

## RECOMMENDATION

1. Extend `_bulk_write_sites` to the full WRAM-writing helper family with per-helper dest/len registers
   (the mapping is in F1's table) and add a generic `ld [hli], a` matcher; keep the exact idiom matcher
   for length semantics.
2. Record the out-of-scope counts per callee in the census report so PROVEN is bounded in the artifact.
3. Fix F3's wording (or mark sibling-field destinations UNPROVEN) and add two planted controls to the
   test file: a `farcall FarCopyBytes` write and a non-idiomatic `ld [hli], a` loop.
4. Add the no-build provenance assertions (F7) to the build test, and put the mailbox-only == clean
   equality gate on a lane row instead of "by hand".
5. Keep the DelayFrame follow-up's gate and write the `wVBlankOccurred` obligation into slink.asm and
   the P4.1c falsifier (F8).

## TESTS / VERIFICATION

- `pytest tests/unit/test_gen2_mailbox_census.py tests/unit/test_build_gen2_companion.py -q` — the
  census's own planted controls and the build's pure parts (not run here).
- `python tools/gen2_mailbox_census.py --check` — the committed report is current (not run here).
- `python tools/build_gen2_companion.py --check` — the only automated check of the equality claim;
  schedule it in a lane when no emulator is running.
- The two probe scripts used in this review (extended helper/hli classification; near-span `ld hl,`
  back-scan) are the evidence for F1/F5 and can be folded into the census tool as extra matchers plus
  the two planted-control tests in recommendation 3.
