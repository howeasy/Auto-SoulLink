# Fixture strategy and the New Bark lock

Type: grilling
Status: resolved
Blocked by: none

## Question

Gen 1 F-6 needs a town fixture on encounter-free ground and a battle fixture in grass, both from scripted play. Gen 2 today has one staged town fixture (a Totodile written into slot 0, lua/tests/gen2_playthrough.lua:283-298) and the New Bark west exit is script-locked until Elm's starter (SOURCE: pokecrystal@7a7881d maps/NewBarkTown.asm:292-293, maps/ElmsLab.asm:277; Codex cx-3569f8d9 finding 1). Rebuild both from play, town only, or owner-supplied saves?

## Answer

Rebuild **eight fixtures** from scripted play, mirroring Gen 1 F-6:

- `crystal_town.SaveRAM`, `crystal_battle.SaveRAM`
- `gold_town.SaveRAM`, `gold_battle.SaveRAM`
- `silver_town.SaveRAM`, `silver_battle.SaveRAM`
- `crystal_town_ot2.SaveRAM`, `crystal_battle_ot2.SaveRAM`

All live under `tests/fixtures/gen2/`. `town` is inside Elm's lab after the starter,
on encounter-free ground; `battle` is in Route 29 grass. The played Crystal `_ot2` pair
has a different player OT for C↔C A/B identities and the wrong-save control. Distinct player
OTs are a fixture invariant; the identical-full-mon-key refusal is a separate identity test.

O-10 permits Poké Balls injected into the Ball pocket for tests/validation; the starter and
walk remain played, and the Mr. Pokémon errand is not driven. The closed decision "Gen 2
playthrough deliberately not bought" stays closed: `playthrough`, `deadzone` and `dupes`
scenarios remain excluded. See [PLAN §5.7/§8](../../PLAN.md),
[REVIEW_RECORD round 2 Q3, O-10 and Codex CR1/CR2](../../REVIEW_RECORD.md), and
[the fixture ball-source ticket](22-fixture-frame-budget.md).

Resolved means the fixture strategy is decided, not that the saves exist or qualify.
The eight fixtures still require P3b build/qualification evidence; all gates remain unsigned.

## Comments

2026-09-21 history: round 2 Q3 adopted "town + battle for all three titles" (six fixtures).
Codex CR1 added the played Crystal `_ot2` controls; PLAN §5.7/§8 now require eight.
