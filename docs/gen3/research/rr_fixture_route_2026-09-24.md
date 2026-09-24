# RR fixture route to 2+ Poké Balls and a second party mon (card G5-RR-FIXTURE-ROUTE)

Static research only: no emulator/EmuHawk runs, no code changes. Every fact below is tagged
**PROVEN** (read directly from admitted bytes/source, with offset or path) or **INFERRED**
(reasoned from adjacent proven facts, not independently confirmed against RR's own compiled
bytecode).

## Sources used

- ROM: `E:/Google Drive/SLink/Pokemon - Radical Red.gba`, the clean 4.1 dump, md5
  `8529f3a45d32bce4da637976fcf269d4`, sha1 `964f951a0fdaf209e4ea1344883ef0d557bb3a80` (matches
  the card's stated hash). Used for all map/geometry parsing via `tools/gba_map.py`.
- Fixtures: `tests/fixtures/gen3/rr_town.sav` (sha256 `b4b991f6...def9a3`) and
  `tests/fixtures/gen3/rr_battle.sav` (sha256 `d9fe5eb6...319c4b`), read with
  `server/adapters/gen3_codec.py`'s existing RR primitives (`split_rtc`, `_rr_regions`,
  `_rr_read`, `rr_party_from_save`) plus `tools/e2e_duo.py::gen3_ball_count`.
- pret decomp: `E:/Google Drive/SLink/.cache/pret/pokefirered` @ `c75f35230` (vanilla FireRed
  reference only, per repo rule: never a source of RR fact, only of the vanilla script/struct
  shapes RR is checked against).
- `data/games/gen3_rr/profile.json` (`titles.radical_red.derived`/`.ram`): pre-existing,
  in-repo constants, several of them printed by `lua/tests/test_rr_discovery.lua` — a one-off
  manual live-RAM discovery script whose header says it must be run "with a save loaded that
  has ... some Pokeballs in the bag ... at least 1 badge" against real RR 4.1 in BizHawk. That
  makes these specific constants **PROVEN against real RR RAM by a prior live session**, not
  vanilla-FR guesses, even though I did not re-run BizHawk this session.

## Starting state (both fixtures)

| Fact | Value | Status | Source |
|---|---|---|---|
| Map | 3.19 (Route 1) | PROVEN | fixture build receipts; `tools/gba_map.py --map 3.19` byte-parse |
| Position | `rr_town.sav` (7,33); `rr_battle.sav` (12,37), the `GRASS_ORIGIN` tile | PROVEN | `docs/gen3/probes/fixture_rr_battle_2026-09-24.txt` RESULT lines |
| Tile terrain | both tiles are `MB_TALL_GRASS` (0x02) | PROVEN | `tests/fixtures/gen3/README.md` §rr_battle.sav, cross-checked this session (`gba_map.py --find-behaviour 0x02` includes (7,33) and (12,37)) |
| Party | 1 mon: Treecko (species 277) Lv.6, hp 22/22, key `EBEF11DA:2BDDC8BF` | PROVEN | fixture RESULT line + boot-check (party read back unchanged after a real cold-boot save/reload) |
| Poké Ball pocket | **0** balls, 50-slot EWRAM pocket, all slots empty | PROVEN | `tools/e2e_duo.py::gen3_ball_count(rr_battle_body, "radical_red")` re-run this session → `0`; matches `tests/fixtures/gen3/README.md`'s prior claim |
| `FLAG_SYS_POKEDEX_GET` (vanilla flag id 0x829) | **0** (not set) | PROVEN (bit read this session) — INFERRED that the RR flag numbering matches vanilla (see below) | `_rr_read(SaveBlock1+3808, 288)`, bit 0x829 |
| `FLAG_BADGE01_GET` (0x820) | 0 | same caveat | same read |
| `VAR_MAP_SCENE_VIRIDIAN_CITY_MART` (vanilla var 0x4057) | **0** | PROVEN (word read this session) — INFERRED var-numbering match | `_rr_read(SaveBlock1+4096, 512)`, index 0x57 |
| `VAR_MAP_SCENE_PALLET_TOWN_PROFESSOR_OAKS_LAB` (vanilla var 0x4055) | **4** | same | same read, index 0x55 |
| Money (SaveBlock1+0x290, right after the 600-byte party array) | raw `3120`, decrypted with `SaveBlock2+0xF20` XOR key `0` → **3120** | INFERRED offset (not in `profile.json`, never pinned by any tool in this repo; read this session as a byte-offset analogy, not independently proven) | ad-hoc read this session |

**Why the flag/var numbering is trusted to carry over from vanilla FR, not just assumed:**
`data/games/gen3_rr/profile.json`'s `derived` block already carries `SB1_FLAGS_OFFSET: 3808`
(`0x0EE0`), `SB1_VARS_OFFSET: 4096` (`0x1000`), and `SB1_BADGE_BYTE_OFFSET: 260` — these are the
*exact* byte offsets of pokefirered's `struct SaveBlock1.flags`/`.vars` fields
(`include/global.h:790-791`, cached checkout) and `260 = (SYS_FLAGS+0x20)/8` is exactly where
vanilla `FLAG_BADGE01_GET` would sit in that same flags array. Those constants were not
invented for this card; they were already in the repo, sourced from the real-RAM discovery
tool, and `SB1_PARTY_BASE_OFFSET: 56` (`0x38`) from the same block is independently proven
correct for RR by the `rr_battle.sav` boot-check (party read back byte-identical after a real
cold boot/save/reload). Since RR's item bag was moved **out of SaveBlock1 entirely** into a
separate EWRAM/extension region (`"BAG_IN_EWRAM": true`, `ram.BALL_POCKET_ADDR` =
`0x0203C354`, inside the sectors-30/31 extension `gen3_codec._rr_regions` already reads) rather
than resized in place, nothing downstream of the old bag fields needed to shift — which is
consistent with flags/vars sitting at their unmodified vanilla offsets. This is strong but not
watertight: it proves the *storage layout* lines up, not that RR's *compiled map scripts* still
branch on the same flag/var **id numbers** the way vanilla FR's decomp source does. I did not
disassemble RR's Mart/Lab script bytecode to confirm the numbering directly (out of scope for a
static, no-emulator card); that is the one live check the recommendation below should get
before being trusted as fact rather than a strong inference.

## What the vars actually mean (from vanilla FR source, cross-referenced against the read above)

`E:/Google Drive/SLink/.cache/pret/pokefirered/data/maps/ViridianCity_Mart/scripts.inc`:
- `ViridianCity_Mart_OnFrame` fires `ParcelScene` automatically via
  `map_script_2 VAR_MAP_SCENE_VIRIDIAN_CITY_MART, 0, ...` — i.e. **the first time the player
  ever steps into the Mart**, before any button is needed: it gives `ITEM_OAKS_PARCEL` and sets
  `VAR_MAP_SCENE_VIRIDIAN_CITY_MART = 1` and `VAR_MAP_SCENE_PALLET_TOWN_PROFESSOR_OAKS_LAB = 5`.
- The clerk's own talk script (`ViridianCity_Mart_EventScript_Clerk`) only opens `pokemart`
  (lets you buy) when `VAR_MAP_SCENE_VIRIDIAN_CITY_MART != 1`; while it is `1` (parcel taken,
  not yet delivered) it just says "say hi to Oak for me" — **no shopping**.

`.../PalletTown_ProfessorOaksLab/scripts.inc`, `EventScript_ProfOak`:
- `goto_if_ge VAR_MAP_SCENE_VIRIDIAN_CITY_MART, 1, ...EventScript_ReceiveDexScene` is checked
  **before** the `var==4` branch, so once the Mart has been visited once (var >= 1), talking to
  Oak runs `ReceiveDexScene` regardless of the Lab-scene var's own value.
- `ReceiveDexScene` (scripts.inc:606-679): `removeitem ITEM_OAKS_PARCEL` (line 606),
  `setflag FLAG_SYS_POKEDEX_GET` (656), then
  `giveitem_msg ..._ReceivedFivePokeBalls, ITEM_POKE_BALL, 5` (line 660) — **delivering the
  parcel grants 5 free Poké Balls**, not just shop access — then
  `setvar VAR_MAP_SCENE_VIRIDIAN_CITY_MART, 2` (679, now shop access is open too, unused by the
  route below).

Given the read state above (`VAR_MAP_SCENE_VIRIDIAN_CITY_MART == 0`, `FLAG_SYS_POKEDEX_GET ==
0`, `VAR_MAP_SCENE_PALLET_TOWN_PROFESSOR_OAKS_LAB == 4`, one already-caught starter, empty ball
pocket): this fixture's playthrough has **never entered the Viridian Mart**. That is
self-consistent with the developer having gone straight from the Lab (reaching lab-scene state
4, i.e. done with the starter/rival scene) onto Route 1 without detouring through Viridian —
exactly the state this quest gate predicts for "no balls yet, one starter caught."

## Map geometry (PROVEN, parsed from the ROM this session with `tools/gba_map.py`)

```
route1(3.19) --up(offset -12)--> viridian(3.1, 48x40) --down(offset 12)--> route1(3.19)
route1(3.19) --down(offset 0)---> pallet(3.0, 24x20)   --up(offset 0)----> route1(3.19)
```
- Viridian warps resolve (via `data/maps/map_groups.json`'s `gMapGroup_IndoorViridian`) to:
  Mart = map 5.3, door tile (36,19) [collision-blocked; approach from (36,20) and press Up].
  Gym=5.1, School=5.2, House=5.0, PokeCenter=5.4/5.5.
- Pallet warps resolve (`gMapGroup_IndoorPallet`) to: Oak's Lab = map 4.3, door tile (16,13)
  [approach from (16,14) and press Up]; player's house = 4.0/4.1, rival's house = 4.2.
- **No hidden items** (`BG_EVENT_HIDDEN_ITEM`/kind=7) anywhere on Route 1, Viridian City,
  Pallet Town, or any of their nine indoor maps (Mart, both PC floors, Gym, School, both
  houses, rival's house, Oak's Lab) — checked this session, all empty. So "an item ball on the
  ground" is not a candidate at all near this fixture's position.
- 2 patrolling NPCs on Route 1 (graphics_id 25/19, movement_type 3/5) are a wild-battle/trainer-
  sightline risk the BFS below does not model (it only avoids their exact standing tile, not
  their vision cone); Route 1's own north/south map-connection edges are tall grass, so
  incidental wild encounters are also possible mid-walk. Both are the same class of risk
  `lua/tests/gen3_scripted_play.lua`'s `warp_to` already resolves for FR/LG (flee/fight-through
  before retrying), not a new problem.

## Candidate routes

### Candidate 1 — buy at the Mart (rejected)
Walk grass origin → Mart, buy 2+ Poké Balls with the 3120 money read above. **Blocked**: per
the read state, `VAR_MAP_SCENE_VIRIDIAN_CITY_MART == 0`, i.e. the Mart has never been entered,
so first entry triggers the automatic Parcel pickup, not a shop prompt; the shop does not open
until the parcel is delivered (see above). Money is not the constraint here.

### Candidate 2 — item balls on the ground (rejected)
No hidden items exist within Route 1 / Viridian / Pallet or their nine indoor maps (checked
this session, PROVEN empty).

### Candidate 3 — parcel errand (RECOMMENDED)
Walk grass origin → Mart (auto-receive `ITEM_OAKS_PARCEL`, no shopping) → Pallet Town → Oak's
Lab (deliver the parcel to Oak, receive Pokédex flag + **5 free Poké Balls**) → back to Route 1
grass → catch a wild mon. Satisfies (a) with balls to spare (5, not just 2) and sets up (b) via
an ordinary wild catch — no purchase, no reliance on the unverified money offset.

**Step list** (button-equivalent movement presses; BFS avoids collision/blocked-NPC tiles,
4-directional, computed against the clean RR ROM this session):

| Leg | From | To | Steps | Notes |
|---|---|---|---|---|
| 1 | Route1 (12,37) grass origin | Route1 (12,0) | 57 | `route1.bfs((12,37),(12,0))` |
| 1 | — | cross into Viridian (24,39) | 1 | press Up off the map edge |
| 1 | Viridian (24,39) | Viridian (36,20), just south of the Mart door | 35 | `viridian.bfs((24,39),(36,20))` |
| 1 | — | Mart door (36,19) | 1 | press Up; **auto-cutscene fires**, dismiss ~2-3 text boxes, no input choices |
| **Leg 1 total** | | | **94** | grass → parcel in hand |
| 2 | Viridian (36,20) | Viridian (24,39) | 35 | back south |
| 2 | — | cross into Route1 (12,0) | 1 | |
| 2 | Route1 (12,0) | Route1 (12,39) | 59 | full north-south crossing (Viridian and Pallet do not connect directly; every leg between them re-crosses Route 1) |
| 2 | — | cross into Pallet (12,0) | 1 | |
| 2 | Pallet (12,0) | Pallet (16,14), just south of the Lab door | 18 | |
| 2 | — | Lab door (16,13) | 1 | press Up; talk to Oak (a `faceplayer`+`lock` NPC, needs one A/interact press, then a long **forced, automatic** cutscene: dex/rival scene, no further choices, ends with the 5 Poké Balls) |
| **Leg 2 total** | | | **116** | mart → parcel delivered, 5 balls in bag |
| 3 | Pallet (16,14) | Pallet (12,0) | 18 | |
| 3 | — | cross into Route1 (12,39) | 1 | |
| 3 | Route1 (12,39) | Route1 (12,37) grass origin | 2 | |
| **Leg 3 total** | | | **21** | lab → back at the grass origin, ready to catch |
| **Grand total** | | | **231** movement presses | plus dismiss-text A presses (a handful at the Mart, a long fixed sequence at the Lab with no branching) and the catch sequence itself (walk into grass, wait for/trigger a wild encounter, throw a Poké Ball) |

Risks: the two Route-1 crossings (leg 2 crosses the whole map three times total across the
route) each pass the same two NPC tiles and the same grass-edge encounter risk noted above —
any incidental battle must be fled or fought through, matching the existing `warp_to` pattern.
The Lab cutscene is long (see the full script quoted above) but has **no player choices** once
started (all `applymovement`/`msgbox`/`waitmessage`, no `multichoice`), so it is safe to drive
by waiting on `waitmessage`/task completion the same way `gen3_scripted_play.lua`'s witnessed
legs already do for FR/LG, rather than a frame budget.

### Candidate 4 — catch after balls (not separate; folded into Candidate 3's tail)
Once Candidate 3 grants 5 Poké Balls, catching mon #2 is an ordinary Route-1 grass encounter at
the grass origin — no new route needed.

### Not evaluated
"An RR-specific NPC gift" near this location: none of the nine nearby indoor maps' object lists
(dumped this session) show an obviously mon-granting layout beyond the already-used starter/
Lab/rival objects; confirming would need script disassembly of RR's compiled Lab/House
scripts, out of scope for this static pass.

## Recommendation

Build the driver as **Candidate 3**. It is the only route that reaches (a) at all (the Mart is
gated shut and there are no ground items), and it reaches (b) for free as a side effect (5
Poké Balls, not just the required 2) without touching the unverified money offset. Before
committing driver work, get one **live** confirmation (a single BizHawk session, not part of
this static card): step into the Mart from `rr_battle.sav` and confirm the parcel auto-fires
exactly as the vanilla script predicts, then walk to Oak's Lab and confirm the 5-ball grant.
That settles the one INFERRED link in the chain (RR's compiled scripts still branching on the
same flag/var ids as vanilla FR) before code is written against it.

## What a `lua/tests/gen3_routes.lua`-style driver needs

- The three `PATHS` legs above (grass→mart, mart→lab, lab→grass), expressed the way
  `gen3_scripted_play.lua`'s existing `PATHS`/`DEST` tables already are (`map`, `from`, `to`,
  direction list) — the BFS direction lists this session printed can seed them directly.
- `warp_to`-style handling at every map-connection crossing (3 crossings in leg 1, 3 in leg 2, 2
  in leg 3) to resolve an incidental wild encounter before retrying the press, exactly as
  `gen3_scripted_play.lua`'s `warp_to` already does for FR/LG.
- A witness for the Mart auto-cutscene: since it fires on `OnFrame` the instant the map loads,
  the driver should wait for control to return (a `waitmessage`/menu-idle witness) rather than
  a frame budget, then dismiss text.
- A witness for `ReceiveDexScene` completing at the Lab: the same "wait for the task/callback2,
  never a frame count" rule already used elsewhere in this file. Since this session could not
  read RR's compiled script for the exact witness signal (no live RAM access), the driver
  should reuse `key_items_has_parcel`/ball-count-style **polling on save-state facts** (the
  parcel leaving the bag, `gen3_ball_count` going from 0 to 5) as the completion oracle, the
  same pattern `verify_parcel_delivered` already uses for FR/LG
  (`lua/tests/gen3_scripted_play.lua:2150-2158`), rather than inventing a new RR-specific task
  name blind.
- Because `gen3_scripted_play.lua` explicitly refuses `radical_red` by name today (its own
  comment: "this file's story legs already refuse RR by name"), this route needs a **new** RR
  leg, not a title-branch inside the existing FR/LG parcel legs — the maps are byte-identical
  but the witnessing primitives (`key_items_has_parcel`, badge/flag reads) already differ by
  title (`SB1_KEYITEMS_POCKET_OFFSET` for FR/LG vs. RR's EWRAM-based bag) and should stay
  title-branched the way `gen3_ball_count` already is.

## Open questions for whoever builds the driver

1. Does RR's compiled Mart/Lab script still branch on `VAR_MAP_SCENE_VIRIDIAN_CITY_MART`/
   `..._PALLET_TOWN_PROFESSOR_OAKS_LAB` at the same numeric ids, and still call
   `giveitem ITEM_POKE_BALL, 5`? (This doc's one INFERRED link; settle live before trusting it.)
2. Is `ITEM_POKE_BALL`'s item id unchanged in RR (needed if the driver wants to assert the
   bag's *contents*, not just the ball-count total)? Not checked this session.
3. Is `SB1_MONEY_OFFSET` (`0x0290`, used ad hoc this session, not in `profile.json`) worth
   pinning properly if a future scenario needs money — not needed for this route.
