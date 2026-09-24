# RR fixture route to 2+ Poké Balls and a second party mon (card G5-RR-FIXTURE-ROUTE)

Static research only: no emulator/EmuHawk runs, no code changes. Every fact below is tagged
**PROVEN** (read directly from admitted bytes/source, with offset or path) or **INFERRED**
(reasoned from adjacent proven facts, not independently confirmed against RR's own compiled
bytecode).

**Update (card G5-RR-FIXTURE-DRIVER, same date):** the one INFERRED link this doc originally
left open — whether RR's *compiled* map/NPC scripts still branch on the same flag/var **id
numbers** as vanilla FireRed's decomp source, rather than merely keeping the same SaveBlock1
*storage layout* — is now closed. §"RR bytecode disassembly" below decodes RR's own Viridian
Mart and Oak's Lab scripts, byte for byte, out of the admitted clean ROM, against pret's own
opcode table (`asm/macros/event.inc`). Every fact that section states is PROVEN from those
bytes, not inferred from vanilla. It also corrects one number the first pass got wrong by
extrapolating from vanilla instead of reading RR's own bytes: RR's Lab scene gives **10** free
Poké Balls, not vanilla's 5.

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
| `FLAG_SYS_POKEDEX_GET` (vanilla flag id 0x829) | **0** (not set) | PROVEN — the save-byte read AND the id numbering (RR's own compiled Mart `OnLoad` script checks this exact id, §"RR bytecode disassembly") | `_rr_read(SaveBlock1+3808, 288)`, bit 0x829 |
| `FLAG_BADGE01_GET` (0x820) | 0 | PROVEN (byte read; id numbering corroborated by RR's own Mart clerk script checking flags 0x820-0x827 for its badge-count flavor text, §"RR bytecode disassembly") | same read |
| `VAR_MAP_SCENE_VIRIDIAN_CITY_MART` (vanilla var 0x4057) | **0** | PROVEN — the save-byte read AND the id numbering (RR's own compiled Mart `ON_FRAME_TABLE` entry and clerk script both use this exact id, §"RR bytecode disassembly") | `_rr_read(SaveBlock1+4096, 512)`, index 0x57 |
| `VAR_MAP_SCENE_PALLET_TOWN_PROFESSOR_OAKS_LAB` (vanilla var 0x4055) | **4** | PROVEN (save-byte read; id numbering corroborated by RR's own Oak script using this id, §"RR bytecode disassembly") | same read, index 0x55 |
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
consistent with flags/vars sitting at their unmodified vanilla offsets. That storage-layout
argument was, on its own, strong but not watertight: it proved the *storage layout* lines up,
not that RR's *compiled map scripts* still branch on the same flag/var **id numbers** the way
vanilla FR's decomp source does. §"RR bytecode disassembly" below settles that directly, by
decoding RR's own script bytes rather than reasoning about them.

## RR bytecode disassembly (PROVEN, card G5-RR-FIXTURE-DRIVER)

Map event scripts are ROM bytecode interpreted by the game's own script engine — not ARM/THUMB
CPU instructions — so they can be decoded the same way the map/collision data already was:
parse the pointer, read the opcode table pret ships as an assembler macro file
(`asm/macros/event.inc`, in the same cached pokefirered checkout), and confirm RR's bytes
produce a well-formed, sensible script under that table (a wrong opcode table could not by
accident decode into a coherent, source-matching command sequence).

**Method.** `struct MapHeader.mapScripts` sits at header offset `0x08`
(`include/global.fieldmap.h:195`, not `0x0C`/connections as an earlier pass without decomp
access had assumed for a *different* field — connections are confirmed separately at `0x0C` and
still correct). A `MAP_SCRIPT_ON_FRAME_TABLE` entry (type byte `2`) points to a
`{u16 var; u16 compare; u32 script}` table (`asm/macros/map.inc:16-20`, the `map_script_2`
macro), terminated by a `var == 0` entry. `struct ObjectEventTemplate` is 24 bytes
(`asm/macros/map.inc:23-38`, the `object_event` macro) with its `script` pointer at byte offset
`0x10` and `event_flag` at `0x14` — `tools/gba_map.py`'s own `ObjectEvent` dataclass does not
parse these two fields, so they were read directly off the same `Rom` object with one extra
`_ptr(base + 0x10)` call, not a change to the tool. The opcode table itself is the `.byte 0xNN`
literal in each macro in `asm/macros/event.inc` (cited by mnemonic and address below).

**Object-event cross-check (PROVEN, establishes local_id correspondence).** RR's map 5.3
(ViridianCity_Mart) and 4.3 (OaksLab) object lists were compared field-by-field against vanilla
FR's `data/maps/.../map.json` for the same maps: every position, elevation and
`movement_type` numeric value (`MOVEMENT_TYPE_FACE_RIGHT=0xA`, `_WANDER_AROUND=0x2`,
`_WANDER_UP_AND_DOWN=0x3`, `_FACE_DOWN=0x8`, `include/constants/event_object_movement.h`)
matches exactly, for all 3 Mart objects and Oak specifically (`x=6,y=3,elevation=3,
movement_type=8`, matching `LOCALID_OAKS_LAB_PROF_OAK`). Only the Mart clerk's cosmetic
`graphics_id` differs (RR `25` vs. vanilla `OBJ_EVENT_GFX_CLERK=68`; the other two Mart NPCs'
graphics ids, `18`/`23`, match `OBJ_EVENT_GFX_YOUNGSTER`/`OBJ_EVENT_GFX_WOMAN_1` exactly, and
Oak's own graphics id `71` matches `OBJ_EVENT_GFX_PROF_OAK` exactly) — a sprite reskin, not a
structural change. This is what makes "RR object index 0 in map 5.3 is the clerk" and "index 3
in map 4.3 is Oak" PROVEN rather than assumed.

**Viridian Mart `OnFrame` table (PROVEN).** Decoded at RR map 5.3's `mapScripts` pointer
(ROM `0x0816a1d3`):
```
map_script table: type=1 (ON_LOAD) -> 0x0816a1de ; type=2 (ON_FRAME_TABLE) -> 0x0816a1fb ; end
ON_FRAME_TABLE:  var=0x4057  compare=0  script=0x0816a205 ; end
```
`var=0x4057` is `VAR_MAP_SCENE_VIRIDIAN_CITY_MART`'s exact vanilla id — read directly out of
RR's compiled table, not assumed. The `OnLoad` script at `0x0816a1de` decodes as
`checkflag 0x829; goto_if 0(FALSE), 0x0816a1e8; end` — byte-identical in shape and id to
vanilla's `goto_if_unset FLAG_SYS_POKEDEX_GET, ...HideQuestionnaire` (`FLAG_SYS_POKEDEX_GET =
0x800+0x29 = 0x829`).

**Mart `ParcelScene` (target of the table entry above, PROVEN, full decode):**
```
0x0816a205 lockall
0x0816a206 textcolor 0
0x0816a208 applymovement npc=1 movements=0x081a75ed   ; clerk: WalkInPlaceFasterDown
0x0816a20f waitmovement
0x0816a212 msgbox "YouCameFromPallet"                  ; loadword 0,text ; callstd 4
0x0816a21a closemessage
0x0816a21b applymovement npc=1   movements=0x0816a262   ; clerk: FacePlayer
0x0816a222 applymovement npc=255 movements=0x0816a25c   ; player: ApproachCounter
0x0816a229 waitmovement
0x0816a22c msgbox "TakeThisToProfOak"
0x0816a234 setvar 0x4057, 1                             -- VAR_MAP_SCENE_VIRIDIAN_CITY_MART = 1
0x0816a239 additem item=0x15d(349=ITEM_OAKS_PARCEL), qty=1
0x0816a23e msgbox "ReceivedOaksParcelFromClerk" (giveitem_msg's own message)
0x0816a253 callstd 9 (STD_RECEIVED_ITEM)
0x0816a255 setvar 0x4055, 5                             -- VAR_MAP_SCENE_..._OAKS_LAB = 5
0x0816a25a releaseall
0x0816a25b end
```
`item=0x15d` is exactly `349` decimal, `ITEM_OAKS_PARCEL`'s vanilla id
(`include/constants/items.h:421`) — proven from RR's own bytes, not carried over from vanilla.
This closes Candidate 1's rejection with certainty: the automatic scene really does fire on the
first Mart visit, really does set `VAR_MAP_SCENE_VIRIDIAN_CITY_MART = 1`, and grants the parcel,
never a purchase prompt.

**Mart clerk's talk script (PROVEN, confirms the shop gate).** RR object index 0 in map 5.3,
script at ROM `0x0871c6c0`:
```
lock; faceplayer
compare_var_to_value 0x4057, 1
goto_if 1(EQUAL), 0x0871c7a0            -- -> "say hi to Oak for me", NO shopping
special 0x187
compare_var_to_value 0x800d, 2 ; goto_if 4(>=), 0x0871c72f   -- RR-added badge-count branches
checkflag 0x827 ; goto_if 1, ...   (and 0x826, 0x825, 0x824, 0x823, 0x822, 0x821, 0x820, in
                                     order -- FLAG_BADGE08_GET down to FLAG_BADGE01_GET, RR's
                                     own added "greeting varies by badge count" flavor text,
                                     using the SAME vanilla badge-flag ids)
goto 0x0871c78a                        -- the actual `pokemart` shop open, reached only if
                                           VAR_MAP_SCENE_VIRIDIAN_CITY_MART is NOT 1
```
`goto_if 1(EQUAL)` on `compare_var_to_value 0x4057, 1` is checked **first**, before any of RR's
own added badge-flavor branches — byte-identical in shape and id to vanilla's
`goto_if_eq VAR_MAP_SCENE_VIRIDIAN_CITY_MART, 1, ...SayHiToOakForMe`. RR's own badge-count
flavor text (new content, not in vanilla) uses `FLAG_BADGE01_GET`-`FLAG_BADGE08_GET` at their
exact vanilla ids (0x820-0x827) too, which is further, independent corroboration that RR did
not renumber the flags/vars namespace.

**Oak's talk script (PROVEN, confirms the gate and the reward).** RR object index 3 in map 4.3
("OaksLab"), script at ROM `0x09050959`:
```
lock; faceplayer
checkitem 0x10b(=267), 1 ; compare_var_to_value 0x800d, 1 ; goto_if 4(>=), 0x090509cb  -- RR-added
checkflag 0x2 ; goto_if 1, 0x08169600
compare_var_to_value 0x4055, 9 ; goto_if 1, ...
compare_var_to_value 0x4055, 8 ; goto_if 1, ...
compare_var_to_value 0x4052, 1 ; goto_if 1, ...            -- RR-added
compare_var_to_value 0x4055, 6 ; goto_if 1, ...
compare_var_to_value 0x4057, 1 ; goto_if 4(>=), 0x0816961e  -- -> ReceiveDexScene
compare_var_to_value 0x4055, 4 ; goto_if 1, ...
compare_var_to_value 0x4055, 3 ; goto_if 1, ...
msgbox "OakWhichOneWillYouChoose" (fallback)
```
`compare_var_to_value 0x4057, 1; goto_if 4(GREATER-THAN-OR-EQUAL), 0x0816961e` is
byte-identical in shape and id to vanilla's `goto_if_ge VAR_MAP_SCENE_VIRIDIAN_CITY_MART, 1,
...EventScript_ReceiveDexScene` (the RR ladder has extra branches spliced in around it, all
RR-added var/flag content at ids vanilla never used for this ladder, e.g. `0x800d`/`0x10b`/
`0x4052` — new content, not renumbering).

**RR's `ReceiveDexScene` (target of the branch above, PROVEN, full decode) — the reward, and
the one number the first pass got wrong:**
```
0x0816961e msgbox "..." ; textcolor 3 ; playfanfare 0x105 ; message "..." ; waitmessage
           waitfanfare ; call 0x081a6675
0x08169637 removeitem item=0x15d(349=ITEM_OAKS_PARCEL), qty=1
0x0816963c msgbox "..."                                    -- parcel-delivered text
           ... (badge-count-branched flavor text, RR-added, elided) ...
0x0816976d setflag 0x829                                    -- FLAG_SYS_POKEDEX_GET
0x08169770 special 0x181
0x08169773 setvar 0x407c, 1                                 -- RR-added
0x08169780 additem item=0x4(ITEM_POKE_BALL), qty=10          -- **10 Poke Balls, not vanilla's 5**
0x08169785 msgbox "..." (giveitem_msg's own message) ; callstd 9
0x081697a4 setvar 0x8004,0 ; setvar 0x8005,1 ; special 0x173 (famechecker-equivalent)
           ... (more badge-branched flavor text) ...
0x0816982a setvar 0x4055, 6
0x0816982f setvar 0x4057, 2                                  -- shop now unlocked too
0x08169834 setvar 0x4051, 1 ; setvar 0x4058, 1 ; setvar 0x4054, 1   -- RR-added
0x08169843 release ; end
```
`item=0x4` is exactly `4`, `ITEM_POKE_BALL`'s vanilla id (`include/constants/items.h:8`) —
proven from RR's own bytes. **The quantity is `10`, not vanilla's `5`**: the first pass of this
doc extrapolated the vanilla figure (5) instead of reading RR's own `additem` operand; this is
the one correction this update makes to the original recommendation, and it only strengthens
it (more balls, same free mechanism, same gate).

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
Lab (deliver the parcel to Oak, receive Pokédex flag + **10 free Poké Balls**, PROVEN by
decoding RR's own `ReceiveDexScene` bytecode, §"RR bytecode disassembly") → back to Route 1
grass → catch a wild mon. Satisfies (a) with balls to spare (10, not just 2) and sets up (b) via
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
| 2 | — | Lab door (16,13) | 1 | press Up; talk to Oak (a `faceplayer`+`lock` NPC, needs one A/interact press, then a long **forced, automatic** cutscene: dex/rival scene, no further choices, ends with 10 Poké Balls, PROVEN by decoding `ReceiveDexScene`) |
| **Leg 2 total** | | | **116** | mart → parcel delivered, 10 balls in bag |
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
Once Candidate 3 grants 10 Poké Balls, catching mon #2 is an ordinary Route-1 grass encounter at
the grass origin — no new route needed.

### Not evaluated
"An RR-specific NPC gift" near this location: none of the nine nearby indoor maps' object lists
(dumped this session) show an obviously mon-granting layout beyond the already-used starter/
Lab/rival objects; confirming would need script disassembly of RR's compiled Lab/House
scripts, out of scope for this static pass.

## Recommendation

Build the driver as **Candidate 3**. It is the only route that reaches (a) at all (the Mart is
gated shut and there are no ground items), and it reaches (b) for free as a side effect (10
Poké Balls, not just the required 2, PROVEN by decoding RR's own compiled scripts) without
touching the unverified money offset. The one INFERRED link the first pass of this doc left
open — whether RR's compiled scripts branch on the same flag/var ids as vanilla FR — is now
CLOSED (§"RR bytecode disassembly"): it does, byte for byte, confirmed from RR's own ROM. A
live BizHawk run is still the only thing that can confirm the *runtime* mechanics this static
pass cannot see (exact button timing, dialogue-box frame counts, the walk BFS holding up
against real collision/step behavior), but the *scripted logic* this route depends on is no
longer a live-only question.

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
- A witness for `ReceiveDexScene` completing at the Lab: now that the scene is fully decoded
  (§"RR bytecode disassembly"), its own terminal writes are the witness — poll
  `VAR_MAP_SCENE_VIRIDIAN_CITY_MART == 2`, `FLAG_SYS_POKEDEX_GET == 1`, and the ball pocket
  reading `ITEM_POKE_BALL x10`, the same "wait for the engine's own terminal state, never a
  frame count" pattern `verify_parcel_delivered` already uses for FR/LG
  (`lua/tests/gen3_scripted_play.lua:2150-2158`). RR has no equivalent key-items-pocket read
  pinned yet (its bag moved to a custom EWRAM structure — see the flags/vars section above), so
  a driver cannot witness "the parcel left the bag" mid-scene the way the FR/LG leg does; it can
  only witness the scene's *completed* terminal state, which is sufficient here since nothing
  else in this route can produce that same combination of writes.
- Because `gen3_scripted_play.lua` explicitly refuses `radical_red` by name today (its own
  comment: "this file's story legs already refuse RR by name"), this route needs a **new** RR
  leg, not a title-branch inside the existing FR/LG parcel legs — the maps are byte-identical
  but the witnessing primitives (`key_items_has_parcel`, badge/flag reads) already differ by
  title (`SB1_KEYITEMS_POCKET_OFFSET` for FR/LG vs. RR's EWRAM-based bag) and should stay
  title-branched the way `gen3_ball_count` already is.

## Open questions for whoever builds the driver

1. ~~Does RR's compiled Mart/Lab script still branch on `VAR_MAP_SCENE_VIRIDIAN_CITY_MART`/
   `..._PALLET_TOWN_PROFESSOR_OAKS_LAB` at the same numeric ids, and still call
   `giveitem ITEM_POKE_BALL, N`?~~ **CLOSED** (§"RR bytecode disassembly", card
   G5-RR-FIXTURE-DRIVER): yes, at the same ids, and RR gives 10, not vanilla's 5.
2. ~~Is `ITEM_POKE_BALL`'s item id unchanged in RR?~~ **CLOSED**: yes, `4`, read directly out of
   RR's own `additem` operand in `ReceiveDexScene` (§"RR bytecode disassembly").
3. Is `SB1_MONEY_OFFSET` (`0x0290`, used ad hoc this session, not in `profile.json`) worth
   pinning properly if a future scenario needs money — not needed for this route.
4. RR's `ReceiveDexScene` writes several vars this doc did not decode the purpose of
   (`0x407c=1`, `0x4051=1`, `0x4058=1`, `0x4054=1`) and reads a badge-count special var
   (`0x800d`) repeatedly for its own added flavor-text branches — none of these gate this
   route's outcome (traced: they sit after the `additem`/`setflag`/`setvar 0x4057,2` calls this
   route depends on, or are read-only badge-count branches), but their meaning is otherwise
   unresearched. Not needed for this route; flagged for whoever next touches RR's early-game
   scripts.
## Driver (card G5-RR-FIXTURE-DRIVER)

Implemented as a second entry point in `lua/tests/gen3_rr_battle_fixture.lua` (W3's file for
`rr_battle.sav`, extended rather than forked, gated by `SLINK_GEN3_RR_FIXTURE_LEG=route2` so the
unset default is byte-for-byte the original `run()`): `run_route2()`, seeded from
`rr_battle.sav` itself, walks grass origin → Mart → Oak's Lab → grass origin (the exact PATHS
above, computed the same session against the same clean ROM), verifies every gate via the RAM
reads this doc proves (`VAR_MAP_SCENE_VIRIDIAN_CITY_MART`, `FLAG_SYS_POKEDEX_GET`, the ball
pocket), throws a Poké Ball at a wild encounter with the pinned sequence
`lua/tests/gen3_rr_scripted_play.lua`'s `wild_catch` leg already proved live
(2026-09-21), and saves in-game. It produces `rr_battle2.sav` (never touching `rr_battle*`)
via the same `tools/gen3_fixtures.py` cold-boot/import pipeline the existing fixtures use. This
driver has **not** been run live (no emulator in this card either); it is built entirely from
this doc's PROVEN facts plus the one already-live-proven ball-throw sequence it cites.

5. RR's Mart clerk and Oak scripts both branch on a "RR-added" var `0x800d` and (Oak only)
   `checkitem 0x10b`/`compare 0x800d,1` at their very start — these run BEFORE this route's
   relevant branch and were not followed to their targets (out of scope: they gate content this
   route never reaches, confirmed by tracing the `goto_if` targets that matter and finding this
   route's branch is unconditional relative to them). If a future scenario needs Mart/Lab
   dialogue *content* (not just the shop/parcel mechanics), those targets need decoding too.
