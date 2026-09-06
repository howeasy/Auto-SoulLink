# Phase 3 presentation projection

The additive `/api/status` projection consumes the accepted `bc880025` runtime
reader. Two subsequently published owner commits were merged independently:
`8f97ea0` rejects unknown legacy cartridges before HELLO adoption; `dbad8d5`
shares the admitted HELLO/tick party snapshot and retains initial stat stages.
Both owner PRs passed their hosted portable checks before this phase was published.
No dirty runtime worktree was imported.

## Public additions

Each player has `capabilities[feature]` with independent `supported`, `ready`,
`effective`, and `reason` values. Configurable features also have `requested`.
Only actual booleans become boolean evidence; absent facts remain null. Intrinsic
abilities and info-panel support omit `requested`. Unknown cartridge identity
does not inherit the fallback Gen 3 adapter's apparent support. Backend admission
rejection text is retained; generic explanations are used when no specific
displayable reason exists.

| Feature | Support evidence | Effective evidence |
|---|---|---|
| abilities | Player adapter `supports_abilities` | Unavailable |
| info_panel | Player adapter `supports_info_panel`, overridden by verified `panel` when supplied | Existing `panel` gate |
| explode_mode | Player adapter `supports_explode_mode` | Existing `explode_mode` gate |
| rival_team_swap | Player adapter `has_rival_trainers` | Existing `rival_team_swap` gate |
| overworld_presence | Unavailable | Only a supplied gate; currently unavailable |
| native_messages | Unavailable | Only a supplied gate; currently unavailable |
| native_sounds | Verified `sfx` when supplied | Existing `native_sounds` gate |
| battle_calc | Unavailable | Only a supplied gate; currently unavailable |
| pc_trade_npc | Verified `pc_trade` when supplied | Existing `pc_trade_npc` gate |

The frozen producer supplies no individual readiness facts, so `ready` remains
null in current runtime output. Synthetic tests prove the dimensions remain
independent when future readiness evidence is supplied. A capability does not
certify operation completion, durable recovery, or randomized-ROM admission.

Party entries add their authoritative dictionary key and held-item name. Box and
enemy entries add held-item names; pending captures add sprite HTML. Species,
items, abilities, moves, links, and memorial killer names resolve through the
owning player's adapter. Existing encounter `sprite_src` fields are retained as
part of status compatibility. Persistent mon keys are not derived from enemy or
effective battle forms.

Move enrichment is shared without changing raw move/PP arrays or boxed PP
behavior. A presentation adapter method gives Gen 1 the same PP Up rule as its
existing `PartyCodec`; all 165 moves and four PP Up counts are checked against
that codec. Other generations retain the existing presentation formula.

Returned nested containers are detached from live party, box, battle, and event
caches. A regression test first demonstrated that modifying projected moves and
stat stages changed the raw cache, then passed after the copy boundary was added.
Observation age is recomputed for every response. Timing on the hydrated fixtures
was 0.94 ms for Gen 3 and 0.70 ms for Gen 1 per projection (median of five batches
of 100 calls on this workstation). This is fixture-scale evidence only; no status
memoization was introduced.

## Rendering and validation

Generated Gen 3 and Gen 1 fixtures come from isolated hydrated state. Nested
contracts cover capabilities, party keys, held items, box/enemy enrichment, and
pending sprites. Archived source captures remain unchanged. Seventeen new UI
test nodes are explicitly classified as portable; the owners' 33 admission and
seven snapshot nodes are preserved. The 308 named input/platform deferrals are
unchanged.

Gen 1 sprite crop geometry is now scoped CSS, preserving the `mon-sprite`,
`enc-sprite`, and `data-species` hooks. Browser inspection covered Gen 3 default
at 1600 px, Gen 1 light at 1100 and 700 px, and the existing Gen 1 focus overlay
at 400 by 600 px. Measured crop/image widths were 40/52 px for ordinary sprites,
20/26 px for encounters, and 60/78 px in focus. This verifies the retained
dashboard and crop change; the new board and full theme/preset matrix still
belong to subsequent phases.

Final combined evidence is recorded in `.cache/phase3-full.{log,xml}` and
`.cache/phase3-portable/report.json`: **3760 passed / 3 skipped** in the full local
unit/integration suite; **3455 passed / 308 named deferrals** in the portable lane,
with zero selected skips or xfails. Required Ruff checks passed and all 216 Lua
files parsed. The three local skips are the unbuilt optional Red companion
component and two Windows file-symlink privilege cases; junction equivalents
run locally and the file-symlink cases run in Linux CI.

Local release inputs remain ignored and are not included in this PR. These unit,
integration, and browser checks do not complete the emulator E2E or verified
randomizer publication gates.
