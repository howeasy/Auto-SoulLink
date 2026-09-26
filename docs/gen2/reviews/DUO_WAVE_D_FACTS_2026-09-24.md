# DUO-WAVE-D feasibility and source facts (2026-09-24)

Card DUO-WAVE-D: the Gen 2 duo scenarios the release lanes need that nobody has built yet:
`gen2_ball_gate`, `gen2_boxed_capture`, `gen2_gift`, `gen2_npc_trade`, `gen2_egg_hatch`
(`gen2_evolution` is out of scope: it waits on the game clock and has its own worker).

Game facts come from the pinned decomps only: `.cache/gen2-build/pokecrystal` 7a7881d (C) and
`.cache/gen2-build/pokegold` 656583c (G/S share the tree). `C x.asm:n` / `G x.asm:n` are file:line in those
trees. Repo facts are cited by path. No screenshot was used.

## Inputs every verdict is measured against

| input | state (PYDEC read with `tools/gen2_fixtures.inspect_candidate`) |
|---|---|
| `crystal_town`, `crystal_town_ot2`, `gold_town`, `silver_town` | Elm's lab (map 24:5) tile (5,3); party = Totodile L5; **Ball pocket empty** (no O-10, `gen2_fixtures.fixture_manifest` `ball_exception` is O-10 only for `battle`). All four have a qualification receipt (`tests/fixtures/gen2/receipts/*_town*.qualification.json`). |
| `<title>_battle[_ot2]` | Route 29 (24:3) grass, Totodile L5, Poké Ball x10 (O-10) |
| `<title>_battle[_ot2]_errand` | Route 29 (53,12), Totodile L5, **Poké Ball x15** = O-10's 10 + the aide's natural 5 (C `maps/ElmsLab.asm:504`, G `:461` `giveitem POKE_BALL, 5`); `EVENT_GAVE_MYSTERY_EGG_TO_ELM` set |
| proven engine sites (production binder registers only these) | `crystal/gold/silver.engine_sites.json` `proven`: battle_end, battle_faint, capture_party, capture_party_finalized, change_box_*, pc_deposit_*, pc_release_*, pc_withdraw_*, poison_faint, save_completed, whiteout_before_heal, wild_ready. **`capture_box` is the U1 gate's ABSENT negative** (`absent: ["capture_box"]`, `lua/tests/gen2_frame_align.lua:29,99`: it must NOT fire with party < 6), so it is not proven. `capture_box_finalized`, `gift_*`, `npc_trade_*`, `hatch_*`, `bag_ball_received` are not proven. |
| binder policy | `lua/gen2/signals.lua:99-104` `OPEN.gift_static` = "Qualified scripted-gift/static caller and final destination context is OPEN": the binder refuses every gift_static site whatever the receipt says (`:745-746`). |
| client publication | `lua/gen2/client.lua:963-983` `publish_capture`: `gift = ev.acquisition == "egg_hatch"`; a direct gift has no publication path. `:1079-1084` `key_change` is sent for the binder's `npc_trade` / `evolution` events. `:1001,1019` no NEW ENCOUNTER / `no_catch` while `has_pokeballs` is false; `:1121-1122,1208-1210` `has_pokeballs` also flips from the Ball-pocket read on hello/tick. |
| clock | host clock + per-fixture hour offset (+11 C/S, +14 Gold). |

## Verdicts

| scenario | verdict | why (short) |
|---|---|---|
| `gen2_ball_gate` | **BUILDABLE NOW** (no new fixture; in-duo errand leg over the town fixtures) | zero-ball town fixtures + the errand the fixture chain already plays + the aide's natural 5 Balls |
| `gen2_boxed_capture` | **BLOCKED** (site receipt) + needs a party-full fixture | `capture_box` is an ABSENT negative, `capture_box_finalized` unproven; no 6-mon save |
| `gen2_gift` | **BLOCKED** (binder policy + site receipt) | `gift_static` is OPEN in the binder; client has no direct-gift publication; the only reachable gift (starter) predates every fixture |
| `gen2_npc_trade` | **BLOCKED** (site receipt); then needs route facts + scripted play (no new save required) | `npc_trade_begin/_finalized` unproven; Violet City is reachable from the errand fixtures |
| `gen2_egg_hatch` | **BLOCKED** (story progress + ~2.4k steps + site receipt) | the first egg needs Falkner's badge; hatch sites unproven |

### 1. `gen2_ball_gate` (D-2) - BUILDABLE NOW

Server rule to prove (coverage map `gen2.requirement.D-2`, `docs/gen2/gen2_coverage_map.md:1482-1491`): the
catch rule opens only when the Ball-pocket witness shows Balls; O-10 injection is a fixture exception, not a
natural acquisition.

Facts:
- **Zero-ball start exists.** All four town fixtures decode an empty Ball pocket (table above).
- **Natural first Balls.** After the errand hand-off Elm sets `SCENE_ELMSLAB_AIDE_GIVES_POKE_BALLS`
  (C `ElmsLab.asm:349`, G `:306`); the aide's coord events (4,8)/(5,8) (C `:1385-1386`, G `:1232-1233`) run
  `AideScript_GiveYouBalls` (C `:498`, G `:455`) -> `giveitem POKE_BALL, 5` (C `:504`, G `:461`). The walk from
  Elm to the lab warp passes that aisle: all four errand fixtures carry the aide's 5 on top of O-10's 10
  (PYDEC above). No earlier Ball source: the Cherrygrove Mart stocks Balls only after
  `EVENT_GAVE_MYSTERY_EGG_TO_ELM` (C/G `maps/CherrygroveMart.asm:11-21`, `MART_CHERRYGROVE_DEX`).
- **The errand is already played by `lua/tests/gen2_scripted_play.lua`** (`self.errand`, the four errand
  fixtures). Route/scene facts: `docs/gen2/reviews/OMP_GOLD_ERRAND_FACTS_2026-09-23.md` (Mystery Egg is a bag
  item, party stays one mon; Elm's ROBBED call; the Cherrygrove rival is unavoidable eastbound and
  `BATTLETYPE_CANLOSE`, C `maps/CherrygroveCity.asm:123,134,145`: no whiteout, no flag; the Route 29 catching
  tutorial is answered NO).
- **A pre-Ball wild encounter is reachable.** Route 29 grass, 10% per step all times
  (C `data/wild/johto_grass.asm:1237-1238`); any species works; RUN from a L2-4 foe (`gen2_route29_inputs.lua`
  `R.flee`, up to 8 RUNs).
- **A pre-Ball faint happens naturally**: the errand's rival fight is lost on purpose (the scripted play
  LEERs until the lead faints). `battle_faint` is proven, so the client sends `faint`; the server's FAINT GATE
  must suppress it while `pokeballs_obtained` is false (`server/state.py:2154-2158`).
- **Clock:** no time-of-day dependency on the path (tables differ by hour, any species is accepted).

Server events the scenario must prove (both sides, C<->C and G<->S):
1. hello with `has_pokeballs=false`, `ball_count=0` (client `send_hello`, `client.lua:1121-1133`);
2. the pre-Ball Route 29 encounter sends neither `no_catch` nor `capture` (client `:1019`), so `route_29` stays
   unresolved on the server;
3. the pre-Ball rival loss reaches the server as `faint` (`server/server.py:1923` logs `[x] faint key=`) and
   produces no `force_faint`/`memorialize` for either side and no DEAD link (`state.py:2156` FAINT GATE);
4. after the aide's Balls, the tick carries `has_pokeballs=true` (`state.py:463-464`), and the persisted
   `links.json` `pokeballs_obtained` is true for both (`state.py:3759`);
5. the first post-Ball Route 29 catch on each side forms one ALIVE `route_29` pair (the pre-Ball encounter
   did not consume the area); the final Ball pocket is the natural stack only (POKe BALL, 1..4 left: 5 minus
   the thrown), never O-10's.

Limits recorded up front: `bag_ball_received` is not a proven site, so the flip is the client's Ball-pocket
read, not the ENGINE bag site (the D-2 oracle is SERVER + PYDEC, the ball_received ENGINE family stays with
the U1 gate); the starters are not a gift pair in Gen 2 (no gift publication), so unlike Gen 1
`ball_gate_new` there is no pre-Ball link whose partner could be killed: item 3 proves the suppression on an
unlinked key only. Five natural Balls miss a full-HP catch about 13% of the time (catch value 85/256 per ball,
C `engine/items/item_effects.asm` PokeBallEffect): the lane retries once on "no Poke Ball left" only
(the one-ball fixture rule).

Needed plumbing (no new fixture, no staging): the scripted play gains `case.resume` (start mid-chain) and
`case.natural_balls` (no O-10, errand first); the shared gate accepts a town case with errand facts for this
scenario only; the duo harness accepts a town fixture for it. Runner lane: A/B = `crystal_town` /
`crystal_town_ot2` (C<->C) and `gold_town` / `silver_town` (G<->S), route facts `route_facts(title, errand=True)`
with its ledges, qualify facts over the same fingerprint.

### 2. `gen2_boxed_capture` (S-2, S-3, D-3 box half) - BLOCKED

- A box catch happens only with a full party: `PokeBallEffect` `.SendToPC` (C `engine/items/item_effects.asm:609-618`,
  G `:607-610`, requirements S-3). Every fixture has one mon; five more catches are needed.
- **Site receipt:** `capture_box` is the U1 gate's ABSENT negative today and `capture_box_finalized` (same PC as
  `capture_party_finalized`, C `03:6be2`) is unproven, so the binder emits no box capture and the client sends
  nothing (`client.lua:976` `in_box` is never reached). Needs a U1 receipt on a party-full fixture (owner: U1
  gate).
- **Fixture:** a party-full save via scripted play. With 15 errand Balls and ~33% per full-HP throw, five
  catches need ~15 Balls on average; buying more needs the Cherrygrove Mart after the errand
  (`CherrygroveMart.asm:19-20`). The S-3 twentieth-slot control (19 in the box) is out of reach by play.
- Verdict: blocked on the U1 receipt; then a new `*_party_full` fixture through `gen2_fixtures.run_play`.

### 3. `gen2_gift` (S-8 gifts) - BLOCKED

- **Binder policy:** `gift_static` is OPEN (`signals.lua:100`); the client publishes only `egg_hatch` as a gift
  (`client.lua:975`). No receipt can open it without that code change.
- **Reachable gifts:** the starter (`givepoke TOTODILE, 5, BERRY`, C `maps/ElmsLab.asm:212`, G `:172`) is
  already in every fixture, so only a cold-boot New Game lane would replay it (`new_game` site unproven). The
  next gifts are the Togepi egg (see 5), Kenya the Spearow (C `maps/Route35GoldenrodGate.asm:31`, G `:30`,
  past Goldenrod) and later ones (Eevee, Tyrogue, Dratini). None is reachable from the fixtures.
- Verdict: blocked on the gift binder context (owner/Codex ruling) + `gift_begin/_party_finalized` receipts.

### 4. `gen2_npc_trade` (S-5 NPC trade, D-1 key_change) - BLOCKED (site receipt)

- **First trader:** Kyle, Violet City (`trade NPC_TRADE_KYLE`, C/G `maps/VioletKylesHouse.asm:16`; house warp
  C/G `maps/VioletCity.asm:288`): requests BELLSPROUT, offers ONIX "ROCKY", OT KYLE 48926
  (C `data/events/npc_trades.asm:15`, G `:15`). Same row on all three titles.
- **Reachability from the errand fixtures:** Route 30 north -> Route 31 (C/G `data/maps/attributes.asm:183`)
  -> Violet City west (`:188`); the Route 30 scene objects are hidden once `EVENT_ROUTE_30_BATTLE` is set by the
  hand-off (OMP Gold errand facts F1). No badge gate.
- **Species:** Bellsprout is Route 31 grass slot 3 (20%, C `data/wild/probabilities.asm:10`) at morn/day/nite
  on every title (C `johto_grass.asm:1298,1306,1314`; G/S `:1662,1670,1678`), so the clock does not matter.
  In a Soul Link duo it must be the linked mon: the lane catches the first Route 31 encounter and retries
  when it is not Bellsprout (80% of runs).
- **Blocker:** `npc_trade_begin` (C `3f:4c63`, G `3f:4a69`) and `npc_trade_finalized` are not in any receipt's
  `proven`, so the binder emits no `key_change` for the trade. Also missing: route facts for Route 31, Violet
  City and Kyle's house (not in `gen2_fixtures.ERRAND_MAPS`) and the trade UI origins.
- Server event to prove once unblocked: `key_change {old_key=<Bellsprout>, new_key=<Onix>, reason "npc_trade"}`
  acked, the `route_31` link migrated to the Onix key (`state.py:3022-3049`), partner untouched.

### 5. `gen2_egg_hatch` (S-8 hatch as `gift_daycare`, O-15) - BLOCKED

- **Egg source:** the Mystery Egg is a bag item (`giveitem MYSTERY_EGG`, OMP facts F2), never a party egg.
  The first party egg is Togepi (`giveegg TOGEPI, EGG_LEVEL`, C/G `maps/VioletPokecenter1F.asm:27`) from Elm's
  aide, who appears only after `SPECIALCALL_ASSISTANT` (C/G `maps/VioletGym.asm:38`, after Falkner) clears
  `EVENT_ELMS_AIDE_IN_VIOLET_POKEMON_CENTER` (C/G `engine/phone/scripts/elm.asm:84`). The Day-Care eggs are
  later still (Route 34).
- **Steps:** the egg's cycle counter is its happiness byte, set from `wBaseEggSteps` (C
  `engine/pokemon/move_mon.asm:1204-1208`); Togepi has 10 (C/G `data/pokemon/base_stats/togepi.asm:12`).
  `DoEggStep` decrements it once per 256 steps, at `wStepCount == $80` (C `engine/overworld/events.asm:894-898`,
  G `:886`; C/G `engine/pokemon/breeding.asm:174-190`): about 2,430 steps after the gift.
- **Blocker:** a Falkner win plus ~2.4k scripted steps, and `hatch_species` / `hatch_finalized` unproven.
- Server event to prove once unblocked: `capture {gift=true, area_id "gift_daycare", key=<hatchling>}`
  published at the hatch, never at `GiveEgg` (requirements S-8).

## Owners for the blocked rows

- U1 gate owner: `capture_box` + `capture_box_finalized` (party-full fixture), `npc_trade_*`, `hatch_*`,
  `gift_*`, `bag_ball_received` receipts.
- Owner/Codex ruling: open `OPEN.gift_static` (binder) and a direct-gift publication path in the client.
- Fixtures (`gen2_fixtures.run_play`): party-full; later a Violet-City save and a post-Falkner egg save.

## Addendum (same day): unblocked by O-33 and U1G, all five built and PHYSICAL on C-C and G-S

Owner ruling O-33 (synthetic SETUP fixtures) and U1G (cf4ef58e: `capture_box*`, `gift_*`, `npc_trade_*`, `hatch_*`
PHYSICAL on C/G/S, client gift publish) removed every blocker above. The four blocked scenarios now start from
builder-made setups (`tools/gen2_synth_fixtures.py` `DUO_RECIPES` full/hatch/trade, and the U1G `bill` recipe);
each receipt's `DUO_GEN2.synth` names the setup, and `gen2_duo_oracles.synth_duo_oracle` re-derives those bytes
with the builder and proves only deltas from them. Everything under test runs natively.

| scenario | setup | C-C | G-S |
|---|---|---|---|
| `gen2_ball_gate` | none (town fixtures, errand in the duo) | PASS `2c50b60e` | PASS `0903a4ed` |
| `gen2_egg_hatch` | `hatch`: lab, [Sentret, Pidgey egg on its last cycle], wStepCount $7F | PASS `4db75edf` | PASS `4db75edf` |
| `gen2_gift` | U1G `bill`: poison whiteout to Goldenrod, Bill's `givepoke EEVEE, 20` | PASS `4db75edf` | PASS `c9c37a2f` |
| `gen2_boxed_capture` | `full`: party of 6 on Route 29 grass, Master Balls | PASS `4db75edf` | PASS `c9c37a2f` |
| `gen2_npc_trade` | `trade`: poison whiteout to Violet City, a Bellsprout egg hatching on step 2 | PASS `4db75edf` | PASS `c9c37a2f` |

The npc_trade setup hatches the Bellsprout in the duo so that Kyle trades a mon that is already linked (the
`gift_daycare` pair), so the `key_change` really migrates a live link half.

### Finding: a Gen 2 NPC trade gives both players the SAME key

`npctrade` rows fix the received mon's DVs and OT (C/G `data/events/npc_trades.asm:15`: Kyle's ONIX, DVs $96 $66,
OT ID 48926). The Soul Link key is DV:OT:species, so every cartridge that trades with Kyle publishes the identical
key `9666:BF1E:5F`. Live C-C run 1 (lane tcc at 5495b645): both sides traded their linked Bellsprouts; B's
`key_change` was acked, A's was then rejected as a collision with a key already load-bearing in the pair
(`server/state.py` `_handle_key_change`, the U5 fail-closed rule), so the pair died `identity_lost` and both halves
were memorialized. The duo now trades on A only (cbd053e0). This is a protocol gap, not a harness one: any two
players who both do the same Gen 2 in-game trade collide as soon as one of them already holds that key in a
live link. **Owner ruling needed**
(for example: the key of a fixed-identity NPC-trade mon gets a per-player discriminator, or the second trade is
refused before the swap).
