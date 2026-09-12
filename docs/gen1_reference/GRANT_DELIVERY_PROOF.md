# Scripted grant delivery proof and acquisition settlement

`server/gen1_grant_receipt.validate` turns three read-only witnesses around one
pinned `call GivePokemon` into a source-qualified fact. `server/gen1_acquisition_runtime`
holds capture and grant facts PENDING until a stable inventory checkpoint proves the
delivery, then acquires logical identity, assigns a per-source ordinal and stages the
shared rule. Neither settles frames, commands or memorial policy. The starter is
excluded (settled by the engine-signal pair); NPC exchanges are excluded (they never
call `GivePokemon`).

## Census

Every non-starter scripted grant reaches the player through `GivePokemon`
(`home/give.asm`) → `_GivePokemon` (`engine/events/give_pokemon.asm`), which calls
`AddPartyMon` (party has room), `SendNewMonToBox` (party full, box not) or fails at
`.boxFull`. `tools/gen_gen1_grant_sites.py` reads the acquisition census, asserts the
exact source text every predicate relies on (`GUARDS`), then the clean ROM bytes at each
call site, prelude, helper exit, prize table, level dictionary and coin-subtraction
site, and writes `grant_sites.json` (+ Lua mirror) and `grant_fresh_content.json`
(+ Lua mirror). `--check` fails on any drift.

| Title | Sites | Groups |
|---|---|---|
| Red, Blue | 7 | eevee, lapras, magikarp_salesman, fossil_revival, dojo_choice ×2, game_corner_purchase |
| Yellow | 10 | the above plus yellow_bulbasaur, yellow_charmander, yellow_squirtle |

The regeneration test re-counts `call GivePokemon` in the pinned `scripts/*.asm` and
`prize_menu.asm` and requires it to equal the site count per title. Yellow's
`.addToParty` prints `UnknownTerminator_f6794` before `AddPartyMon` (pinned as
`add_party_mon_offset` 9, vs 3 for Red/Blue).

## Fresh content (`grant_fresh_content.json`)

Per internal species: `catch_rate` (base-stats record +8), `base_moves` (record
+15..18), `learnset` ((level, move) pairs from `EvosMovesPointerTable` via
`gen1_rom_scan.scan_evos_moves`) and `sorted`. `catch_rate_overrides` carries the
title's script override (Yellow Kadabra → `TWISTEDSPOON_GSC` $60 on both paths:
`add_mon.asm:173-178`, `item_effects.asm:3107-3111`). Kept apart from the party
codec so its schema does not churn.

`fresh_moves` emulates `WriteMonMoves` (`evos_moves.asm`): start from the header
moves; for each learnset entry in table order stop at the first level above the mon's,
skip a known move, fill the first empty slot, else drop slot 0 and append. Some pinned
learnsets are not sorted — Yellow internal 117 (Primeape, dex 57) lists level 46 before
45 — so the engine never teaches the level-45 move to a level-45 mon; the emulation
reproduces that, and a test pins it. Under approved UPR the audit refuses any change
to base-stat headers ("unapproved ROM writes") and any logical learnset change
("level-up learnset changed"), so the clean tables are the admitted content; `codec`
and `content` parameters exist for a future policy that admits changed content, and
absent them the decoder fails closed.

## Receipt (`rby-grant-receipt-v1`)

`source_sha256`, `variant`, `context_generation`, `physical_instance`, `final_sha1`,
`source_id`, and witnesses:

- `call` — PC at the pinned `call GivePokemon`, registers `b` (species) and `c`
  (level). The wrapper (`home/give.asm:18-26`) writes the GivePokemon globals only
  after this PC; they are stale here and never read.
- `return` — PC at `call+3`, same SP, `flags` = F (carry = delivered), `wAddedToParty`
  party (1) / box (0); globals must equal the call registers, `wMonDataLocation` 0.
- `paid` — Game Corner only: `HandlePrizeChoice.subtractCoins+16`, the
  `jp PrintPrizePrice` reached only after `SubBCD`.

Each witness carries: party (404), current box (1122), trainer, player id, map,
battle flag, the three globals, `wAddedToParty`, `wCurrentBoxNum`, coins (BCD),
`wWhichPrize`, `wWhichPrizeWindow`, three prize species, six BCD prices.
`lua/gen1_grant_observer.lua` produces exactly this from bus-exec hooks on the pinned
PCs; a carry-clear return or an unpaid prize yields no receipt.

## What the decoder proves

- Call site names the source; map corroborates. `b` is a pinned operand (or the
  admitted `rom_bytes` override of one), `c` the pinned level for it — Game Corner by
  the FIRST dictionary match (`prize_menu.asm:283-295`), so a randomized duplicate
  species takes the first slot's level whichever slot was bought; the bought slot
  itself comes from RAM `wWhichPrize`, whose table entry must be the species and
  whose price table must be the pinned clean costs.
- Party: exactly one append, prior members byte-identical, box unchanged; the new mon
  is a fresh `AddPartyMon` result — species, level, box level 0, status 0, header
  types, catch rate (with override), `WriteMonMoves` move set, OT id/name, exact
  `CalcExperience`, zero stat experience, max PP without PP Ups, fresh `CalcStats`,
  HP at max. Only the DVs and nickname are read from the record.
- Box (`SendNewMonToBox`, `item_effects.asm:2649-2812`): party full and unchanged;
  new record at slot 0, every prior record/OT/nick shifted intact; species, box level,
  status 0, types, catch rate, moves, OT id/name, exact experience, zero EVs, max PP,
  HP = fresh HP stat.
- Keys unique across party and current box at every witness; delivered key new.
- Carry clear refused; TM window, out-of-range slot, missing/misplaced payment,
  unchanged/over-reduced coins, non-BCD coins refused.

## Acquisition settlement (`server/gen1_acquisition_runtime.py`)

Event `acquisition_observation` (`rby-acquisition-observation-v1`, ≤16 receipts of
`{kind: capture|grant, receipt}`), or the compound-frame bundle field `acquisitions`
(same list). `decode_receipts` decodes each with the admitted context and attaches a
`source_ref = {event: event_reference, index}`. `stage_acquisitions(runtime, stage,
document, player, operation, facts, frame_origin)` returns
`{entry, result, commands, records}` for the caller's atomic commit and mutates only
the detached stage/document.

A fact is pending until the player's latest inventory checkpoint is at or after its
return frame and shows the delivered key at the delivered location with the same
species, level, OT id and OT name. A checkpoint after the return frame that lacks the
key, or shows a different mon under it, refuses settlement. On settlement:
`identity_registry.acquire` with the stable blob's digest; ordinal =
`components['gen1-acquisition-ordinals'][pairing_id][player] += 1`, so refused or
never-stabilized receipts, and purchases that never produced a receipt, consume none;
`pairing_key = pairing_id#ordinal` is the cross-title pairing handle. Rules: fixed-
species gifts in the party → `party_grant_rules.record_exempt_party_grant`; everything
else in the party → `capture_rules.record_clause_checked_acquisition` (pending capture,
area state, `_check_link_violation` unless fixed-species; a violation is recorded, not
enforced); boxed deliveries → `boxed_deferred` (identity and ordinal only; the shared
spec requires a separate boxed binding). Grants never set the Pokéball gate; captures
in non-gift areas do. Areas: adapter map→area with `gift_link_area`; unmapped grant
maps (Yellow Melanie's house, Vermilion City) use the pairing id; Game Corner
purchases pair under their `pairing_key` because the prize room repeats.

`verify_state` re-derives ordinals from settled rows, checks every acquisition and
link id against the identity registry and every pairing key against its ordinal.
`verify_journal` requires the component to equal its atomic record and re-decodes
every pending and settled fact from the raw receipt its `source_ref` names.

## Evidence

- `tests/unit/test_gen1_grant_receipt.py` (168): every site × party/box with stale
  call globals, 18 prize slots with payment, WriteMonMoves incl. the unsorted Yellow
  learnset, Kadabra override on both paths, duplicate-prize first-match level,
  register-vs-global, 30 hostile gifts, 15 fresh-party mutations incl. catch and
  moves, 21 hostile box deliveries, collisions, 15 hostile purchases, UPR overrides,
  regeneration + census.
- `tests/unit/test_gen1_acquisition_runtime.py` (13): pending → stable → identity,
  ordinal, rule, cross-player link and identity link; per-source ordinals across
  repeated prizes with an unstabilized receipt consuming none; boxed deferral; hostile
  observations commit nothing; contradicting checkpoint refuses; replay; restore
  re-checks; clause-checked pairing and recorded violation.
- `tests/unit/test_gen1_grant_observer.py` (12): observer receipts equal the decoder
  fixtures byte for byte and validate; carry-clear and unpaid prizes publish nothing;
  hooks survive an unheld frame while publication needs the hold; latching faults.

All party/box bytes are synthetic fixtures shaped as the engine leaves them. No live
original-engine acquisition evidence is claimed. The observer is not yet wired into
the client (root owns the frame client), the event is not yet in runtime dispatch or
`Gen1RuntimeState` verification (root owns those), and `_contained` does not yet know
the `acquisitions` bundle field.

## Not covered here

- Live mechanism gate: needs a battery save positioned at a grant NPC (Celadon Eevee,
  full party, non-empty box is the smallest) driven through the real script; invoking
  `GivePokemon` out of band reaches `AskName`/`PrintText` mid-frame, the withdrawn
  corruption path. That fixture is the initial-save extraction owner's.
- Clause-violation consequences (force-faint/memorialize/unresolve) — recorded, not
  enforced; the rule coordinator owns writes.
- Quarantine (`box_mon`) and un-quarantine commands — write commands, not staged here.
- Boxed-delivery rule binding — deferred per the shared spec.
- Magikarp salesman pays ¥, not coins; delivery is proved, money payment is not.
