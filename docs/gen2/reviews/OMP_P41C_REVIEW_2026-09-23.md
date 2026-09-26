# OMP adversarial review — P4.1c companion ABI + DelayFrame service (card gen2-O-p41c), 2026-09-23

Peer review for task `cx-5a69aa66` (peer omp, orchestrator claude). READ-ONLY: this file is the only
thing written; not committed. Mode: ADVERSARIAL — the proposal was assumed wrong and attacked; what
survives is stated with the conditions under which it would fail.

Reviewed at `f0ac3a8e` (patch/gb/slink_abi.inc, patch/gen2/src/slink.asm,
tests/unit/test_gen2_companion_abi.py) with the build glue at `3c519370`/`15686f2e`; all three are
ancestors of HEAD `01ceb190`. Pins: pokecrystal `7a7881d`, pokegold `656583c`. No build or test was
run (live lanes); the ROM-level claims below were re-derived by applying the *published* UPS to the
clean dumps in memory.

---

## SUMMARY

The core of the proposal survives an aggressive pass: the bridge preserves every register and flag it
must, restores `hROMBank` + the MBC, the ISR is bank-agnostic (each handler saves the interrupted bank
to `hROMBankBackup` before switching), banks `$75`/`$13` are genuinely empty in the pinned maps with no
literal or table-driven switch into them, and my independent UPS round-trip confirms the claimed
patched sha1s, the 25-byte bridge, the 73-byte service, and **zero moved/removed symbols**. Two
claims are nevertheless not exactly true — "no added frame of latency" (the flag is armed *after* the
service, so a VBlank landing in that window costs a frame) and "not a new interrupt hook" (the
test that asserts it is vacuous) — and three risks are unquantified: +10 bytes of stack on every
`DelayFrame`, a sampled clock that stalls in five of seven VBlank modes (including serial/link) and is
rewritten by one minigame, and the battle-animation wait loop not being a `DelayFrame` site at all.

## FINDINGS

### F1 — MEDIUM: the displaced flag write is replayed *after* the service → a rare extra frame

The bridge's emitted bytes put the service call before the flag store
(`f5 c5 d5 e5 f0 9d f5 3e 75 d7 cd 00 40 f1 d7 e1 d1 c1 f1 3e 01 ea b3 cf c9` at ROM0 `$0063`; the
`call $4000` precedes `ld a,1 / ld [wVBlankOccurred],a`). `DelayFrame` arms that flag and then
`halt`-loops until a VBlank handler clears it (`home/delay.asm:1-13`; handlers clear it, e.g.
`home/vblank.asm:121`). If the VBlank interrupt fires *inside* the service window (≈150 cycles, my
estimate from the instruction mix — 0.2 % of a frame), the clear is a no-op, the bridge then arms the
flag, and the caller waits for the *next* VBlank: one extra frame on ~0.2 % of calls. The card's "no
added frame of latency" is therefore inexact. Timing-sensitive callers exist: `engine/link/link.asm`
calls `DelayFrame`/`DelayFrames` at `:4,12,51,59,77,218,226,244,539,1523` (timeout and pacing loops).
Fix is one line of ordering: replay the five displaced bytes *before* `rst Bankswitch`, then run the
service — with the flag already armed, a VBlank inside the service gives the original behaviour
exactly. Confidence: high on the mechanism and the byte order; the cycle estimate is mine.

### F2 — MEDIUM: +10 bytes of stack on every `DelayFrame`, with no measurement

The bridge pushes five register pairs (`f5 c5 d5 e5` … `f5`) = 10 bytes, live for the whole service
call, and interrupts are enabled (no `di`), so a VBlank handler nests *inside* that frame. The stack is
256 bytes (Crystal `wStackTop = 00:c0ff`, `data/gen2/pokecrystal.sym:52495`; the P4 plan §1.3 puts the
G/S stack at `$DF03-$DFFF`). The pret code was sized for the *original* worst case; the bridge adds 10
bytes below the ISR frame on that path, and nothing here measures the margin — the test harness models
no stack (`Machine.sp = 0xDFFE`, no depth assertion; `tests/unit/test_gen2_companion_abi.py` docstring
"No timing, interrupts or hardware emulation"). `de` need not be saved at all: the service clobbers
only `a/b/c/h/l/f` (patch/gen2/src/slink.asm:53-81), so dropping that push saves 2 bytes and 8 cycles
per call. Confidence: high on the +10; the overflow probability is unquantified.

### F3 — MEDIUM: the sampled clock is not a clock (stalls in 5/7 VBlank modes, jumps in a minigame)

`hVBlankCounter` is incremented only by `VBlank_Normal` (`home/vblank.asm:65`) and
`VBlank_DMATransfer` (`:405`); `VBlank_SoundOnly` (`:150`), `VBlank_Cutscene` (`:167`),
`VBlank_CutsceneCGB` (`:251`), `VBlank_Serial` (`:316`) and `VBlank_Credits` (`:347`) do not. And
`engine/games/card_flip.asm:249` *writes* it (`ldh [hVBlankCounter], a`). Consequences for the plan's
next cards: any hold/deadline logic built on the mailbox counter (P4.2a's "240-frame stamped hold
against the mailbox counter") freezes during cutscenes, credits and the *serial/link* mode and jumps
forward after Card Flip — a held SFX would never release across a link trade. The card's known-limits
note ("only advances in some handlers") is correct but understates it: the stall includes the link
mode, and the rewrite makes the counter non-monotonic. Confidence: high (source-cited).

### F4 — LOW-MEDIUM: the service is absent from animation waits, so the battle context is incomplete

`BattleAnimDelayFrame` (`engine/battle_anims/anim_commands.asm:196-205`) re-implements the
arm-and-wait loop *without* calling `DelayFrame`, and the animation commands call it repeatedly
(`:19,25,47,48,49`). A request arriving during a long animation is not serviced until the animation
ends and some other code calls the real `DelayFrame` (the battle does elsewhere:
`engine/battle/anim_hp_bar.asm:290-324`, `engine/battle_anims/bg_effects.asm:2294`). P4.2c's battle
deadline falsifier must therefore include an animation-wait stretch, or P4.2d's `GetJoypad` site must be
armed — otherwise the "battle" context can pass while the worst case fails. Confidence: high.

### F5 — LOW: the A5 cookie is sound; the real stale window is Reset's 32 `DelayFrames`

The cookie (`SLINK_SAMPLE_VALID`, +31) does its job: it stops the first service call after a WRAM0
clear from taking a bogus delta from `LAST_SAMPLE = 0` (patch/gen2/src/slink.asm:64-79; exercised by
`test_emitted_counter_wrap_repeat_and_native_reset`). Staleness assessment: `Init` clears WRAM0 on every
boot and soft reset (`home/init.asm:66-75`), so "New Game doesn't clear the span" is not reachable
without an intervening `Init`; the plan's note is properly about the service treating panel state as
transient, not a live staleness bug. The one real window is `Reset` itself: `Reset` re-enables
interrupts and runs `ld c, 32 / call DelayFrames` *before* `jr Init` (`home/init.asm:1-19`), so the
bridge keeps the beacon valid and the counter advancing for 32 frames with the pre-reset contents — a
host cannot distinguish "resetting" from "running" there. Harmless while `caps = 0` (this skeleton
grants nothing); it becomes a request-loss window when P4.2a/P4.3a grant capabilities, exactly as the
plan's known limit says. Confidence: high.

### F6 — LOW: the "shared" ABI is Gen 2-only today, and the host side is unmirrored

`patch/gen1/src/slink.asm` does not include `patch/gb/slink_abi.inc` (grep: no `slink_abi` under
`patch/gen1/`); it carries its own `SLINK_ABI_VERSION EQU 3` (`:39`) and caps (`:63-65`) with matching
values, but the offsets/beacon are documented in comments (`:42`). So the "one definition" property is
aspirational until P4.1d, and nothing enforces equality meanwhile. Likewise no Lua file mirrors the
offsets yet (grep for the mailbox offsets under `lua/`: none) — expected, since the binder is P4.1f,
but it means the ABI's host contract has no test today. Confidence: high.

### F7 — LOW: the tests bind to a *linked* image, but with a synthetic linkage and two vacuous assertions

Q5 answer: yes, the tests bind to linked ROM bytes — `assemble()` runs rgbasm *and* rgblink
(`tests/unit/test_gen2_companion_abi.py:31-46`), `test_real_assembly_locations` checks the symbol
addresses (`SlinkDelayFrameBridge (0,$63)`, `SlinkService (0x75|0x13, $4000)`), the `Machine` fetches
opcodes from that image, and the mutation tests patch the linked bytes and re-run it. Caveats that
weaken the binding: (a) the probe defines its own `hROMBank`/`hVBlankCounter`/`wVBlankOccurred` and its
own `Bankswitch` stub (`:26-35`), so slink.asm's `ASSERT hVBlankCounter == $ff9b` (patch/gen2/src/slink.asm:11)
is a tautology *in the probe* — only the real build's ASSERT is meaningful (the real addresses are
`00:ff9b`/`00:ff9d` Crystal, `00:ff9d`/`00:ff9f` Gold, `data/gen2/*.sym`, so the probe's constants are
at least correct); (b) `assert rom[0x40:0x43] == bytes(3)` asserts the probe's *empty* vector table and
proves nothing about "not a new interrupt hook"; (c) no timing/interrupt/stack model, so F1/F2/F3 are
invisible to these tests. Test counts: 5 test functions; the `compiled` fixture parametrises 4 of them
over 3 titles, mutations are 5 × 3 = 15, total 25 cases — the card's "22 compiled-byte tests and 12
mutants" does not match what I count (cosmetic). Confidence: high.

### F8 — VERIFIED (no action): layout, banks, and the isolated link PASS

- ABI offsets match the card exactly (patch/gb/slink_abi.inc:4-24: `$53/$4c/$4e/$4b`, version 3,
  counter 5-6, SFX 7, caps 8, panel 9-11, hold 12-13, lease 14-29; `SLINK_PUBLIC_SIZE = 30`; private
  `LAST_SAMPLE` 30, cookie 31; 32 ≤ 39/40 asserted at slink.asm:19).
- Bridge `$0063-$007B` (25 bytes) and service `$4000-$4048` (73 bytes) in bank `$75` (C) / `$13`
  (G/S) — read from `data/gen2/*_slink.sym` and the map (`SECTION: $4000-$4048 ($0049 bytes)
  ["SLink Service"]`, `data/gen2/crystal_slink.map:43290`).
- Banks free: `ROMX bank #117: EMPTY` (Crystal `$75`) and `ROMX bank #19: EMPTY` (Gold `$13`) in the
  pinned maps; no `ld a, $75` anywhere in pokecrystal and no `ld a, $13` in pokegold (the `$13`
  literal switches are Crystal's own mobile/mystery-gift code — `engine/link/mystery_gift.asm:1793`,
  `mobile/*.asm` — which is why Crystal must keep `$75`, not `$13`); the Stadium 2 checksums are in
  bank `$7F` (`main.asm:686` / pokegold `main.asm:385`).
- Isolated link, independently re-derived: applying `patch/dist/SLink-{Crystal,Gold,Silver}.ups` to the
  clean dumps gives `DelayFrame` = `cd 63 00 00 00` (5 bytes for 5, no shift) and the bridge/service
  bytes above; the clean↔patched `.sym` diff is **7 added symbols, 0 removed, 0 moved** per title; the
  only non-SLink byte diffs are the header checksum (`$14E-$14F`, recomputed) and the Stadium-2
  checksum block in bank `$7F` (by design). Provenance sha1s equal the claimed ones
  (`data/gen2/overlay_provenance.json`: C `20bb8fe5…`, G `04c2e97d…`, S `1a931f75…`).
Confidence: high (byte-level, reproduced locally from the published artifacts).

### F9 — LOW: `de` is pushed needlessly; the per-call service cost is real but negligible

The service touches only `a/b/c/h/l/f` (slink.asm:53-81), so the bridge's `push de`/`pop de` is dead
weight (2 bytes of stack, 8 cycles per call). The service itself runs on *every* `DelayFrame` call
(≈150 cycles, my estimate) — ~0.2 % CPU, and 32 extra runs inside `Reset`'s delay loop (F5). Acceptable
for a skeleton; worth remembering when the SFX service grows. Confidence: medium (estimate).

## DISAGREEMENTS

1. "No added frame of latency" (Q3) — not exact: the arm is delayed by the service, so a VBlank in that
   window costs a frame (F1). If the coordinator accepted the claim as stated, the fix is a one-line
   reorder.
2. "Existing RST Bankswitch convention is used, not a new interrupt hook" — the *code* does that, but
   the test offered as evidence (`rom[0x40:0x43] == bytes(3)`) asserts the probe's empty vectors and
   proves nothing (F7b).
3. The gate's "symbols unchanged outside the SLink bank(s) and the declared hook spans" should be read
   as *symbols*, not bytes: the header checksum and the Stadium-2 checksum block legitimately change
   (F8); a byte-equality gate that forgot them would fail on every overlay.

## UNKNOWN / UNVERIFIED

- No emulator run: the stack margin (F2), the real VBlank-phase probability (F1) and link-timing impact
  are unmeasured. A `minimum_sp` trace on a DelayFrame-heavy path (link trade, battle) would settle F2.
- The service's cycle count is my estimate, not a measurement (F1/F9).
- The card's "22 tests / 12 mutants" count: my static count is 25 cases / 15 mutation cases (F7c).
- The host (Lua) side of the ABI does not exist yet, so no claim about the host's read of offsets 5-6
  (little-endian) can be tested today.

## RECOMMENDATION

1. Reorder the bridge: replay the displaced five bytes *first*, then switch banks and call the service
   (F1) — this restores exact `DelayFrame` semantics and costs nothing.
2. Drop the `de` push (F2/F9) and, before P4.1c is admitted, measure the worst-case SP at a
   `DelayFrame` call site under a nested VBlank (or state the margin as a recorded limit).
3. In P4.2a, do not use the mailbox counter as a wall clock: it freezes in serial/cutscene/credits
   modes and jumps after Card Flip (F3). Either sample `rDIV`/a VBlank-owned counter, or define the
   stall policy explicitly and test it.
4. Add an animation-wait stretch to the P4.2c battle context (F4), or arm P4.2d for it.
5. Have the P4.4 equality gate allow exactly three diff classes — SLink spans, header checksum,
   Stadium-2 checksums — and assert nothing else differs (F8).
6. When P4.1d lands, make Gen 1 include the shared `.inc` and add the Lua-constants equality test (F6).

## TESTS / VERIFICATION

- Cheap and decisive for F1: a byte-order assertion on the linked bridge (the flag store must precede
  the `call`), plus a Machine check that `wVBlankOccurred` is armed before the service's first mailbox
  write.
- For F2: a `minimum_sp` witness (the U2/W6 detector pattern) over a scripted link trade and a battle.
- For F3: a source-derived matrix test that only `VBlank_Normal`/`VBlank_DMATransfer` increment
  `hVBlankCounter`, feeding the hold-policy tests; plus a Card Flip case for the rewrite.
- For F4: extend the battle falsifier with an animation wait and assert the request's deadline.
- Existing: `pytest tests/unit/test_gen2_companion_abi.py tests/unit/test_build_gen2_companion.py -q`
  and `python tools/build_gen2_companion.py --check` (not run here); re-run the isolated-link lane after
  the F1 reorder, since it changes the ROM bytes and therefore every published sha1.
