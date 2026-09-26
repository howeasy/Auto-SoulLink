# Fixture bootstrapper frame budget and the Poke Ball source

Type: research
Status: resolved
Blocked by: none

## Question

The Gen 2 `battle` fixture must sit in Route 29 tall grass with one Poke Ball (Gen 1 F-6 precedent: Route 1 + one ball). Establish from pokecrystal@7a7881d / pokegold@656583c: (1) the earliest scripted point at which the player can hold a Poke Ball (Elm's aide after the Mr. Pokemon errand? Cherrygrove Mart stock before/after which event flag? `data/items/marts.asm`, `maps/CherrygroveMart.asm`, `maps/ElmsLab.asm` aide script), (2) the input-scripted path New Game -> naming -> Mom -> Elm's lab -> starter -> (ball source) -> Route 29 grass, as a frame-count estimate per segment using the existing driver conventions in `lua/tests/gen1_scripted_new_game.lua` and `lua/tests/gen2_playthrough.lua` (which today stages the starter instead of playing Elm's lab: lines 283-298), (3) which segments differ between Crystal and Gold/Silver. Output: a bounded frame budget and the ball source with citations, so the owner can confirm the fixture build or choose owner-played saves (fallback c in `docs/gen2/PLAN.md` section 8).

## Answer

Resolved by research lane R4 (§B), coordinator-verified against the HEAD clone, then RULED by the owner. Fact: there is NO Poké Ball source before the Mr. Pokémon errand. The starter comes with a Berry (`maps/ElmsLab.asm:182,212,240`), Cherrygrove Mart sells Potion/Antidote-class items only (`data/items/marts.asm:40-44`), Route 29/30 item balls are not Poké Balls, and the aide's `giveitem POKE_BALL, 5` (`maps/ElmsLab.asm:498-508`) fires only after `EVENT_GAVE_MYSTERY_EGG_TO_ELM` (`:139-141`), which requires the Route 30 round trip and the Cherrygrove rival battle (`maps/MrPokemonsHouse.asm:127` sets `SCENE_CHERRYGROVECITY_MEET_RIVAL`; `maps/CherrygroveCity.asm:557-559`). No fixture-build frame receipt exists anywhere in the repo, so the 10-segment errand budget is unmeasured. OWNER RULING (chat, 2026-09-21): "We can inject balls for tests and validation." Therefore the fixture chain is New Game -> naming -> Mom -> Elm's lab -> starter (all PLAYED) -> exit New Bark west -> Route 29 grass -> SAVE, with Poké Balls INJECTED into the Ball pocket (`wNumBalls`/`wBalls`) as the single, recorded staging exception (gen2_requirements.md F-6, limits list). The Mr. Pokémon errand is not driven. Crystal vs Gold/Silver: `ElmsLab.asm` dialogue/callback wiring differs but scene/event gating is the same, so a RAM-reactive driver ports unchanged.
