# Gen 3 fixtures

Built and checked by `tools/gen3_fixtures.py` (worker cards gen3-P2-C2-6,
C2-6b). `import`/`qualify`/`derive-b` need no ROM and no emulator: pure byte
transformations over `server/adapters/gen3_codec.py`, the independent
Python codec described in `docs/gen3/PLAN.md` §5.5 and derived per
`docs/gen3/research/flash_save.md`.

## Naming

`<pack>_<scene>[_b].sav`, e.g. `rr_town.sav`. `<pack>` is `rr` (Radical Red
companion) or `fr`/`lg` (vanilla FireRed/LeafGreen; `make-fr`
builds `firered_town.sav`, see below). `_b` marks a distinct-OT
derivation of the `a`-side fixture (`derive-b`), used for the harness's B
player. Every committed file is exactly 131072 bytes (0x20000, the flash
body with any optional 16-byte mGBA RTC suffix already stripped by
`import`).

## Provenance

| Fixture | Source | Date | sha256 |
|---|---|---|---|
| `rr_town.sav` | `E:/Howard/Bizhawk/GBA/SaveRAM/slink RR.SaveRAM` (source sha256 `bb0c514ba045d2710529b7e03b31d56d62e5aca8eaa29f89005b628166150edc`), built from `patch/build/slink_RR.gba` (the existing companion-patched RR battery save `tools/mkstates.py` also drives, `tools/mkstates.py:100-150`) | 2026-09-21 | `b4b991f623c969eeb5c3d06ef54ef2da73cda62b4759a2c730aece7c18def9a3` |

`rr_town_b.sav` was **attempted and refused**: `derive-b --rr` always
refuses (see `tools/gen3_fixtures.py:RR_DERIVE_REFUSAL`) because the
codec's `party_from_save`/`boxes_from_save` refuse `rr=True` -- RR's chunk
table, CFRU's parasite payload appended after the section checksum in ids
0/4/13, and the 25-box disk mapping are not pinned against the admitted RR
4.1 binary (`docs/gen3/research/flash_save.md` §3, §5.7, §7). Rewriting
sectors without that mapping risks destroying the parasite bytes. A B-side
RR fixture needs its own SOURCE card that extracts the admitted binary's
tables first.

`rr_town.sav`'s decoded party (`qualify --rr`) is printed **UNVERIFIED**
for the same reason: `SB1_PARTY_BASE_OFFSET` (`data/games/gen3_rr/profile.json`
`titles.radical_red.derived`) is a real RAM/profile offset, but its
disk-chunk validity for RR 4.1 specifically is not established. Boxes are
not read for RR at all (`qualify --rr` prints a note instead).

## `boot-check` — the usability signature (emulator lane)

Per `docs/gen3/PLAN.md` §5.5, model qualification (`qualify`) is necessary but
not sufficient: **usability is signed only by a real cold boot → CONTINUE →
re-save → reload**. That is `boot-check`, and it is the one place this tool
launches EmuHawk.

```
python tools/gen3_fixtures.py boot-check --rom patch/build/slink_RR.gba --fixture tests/fixtures/gen3/rr_town.sav --rr
```

1. The fixture is seeded into a **per-run** SaveRAM directory
   (`patch/build/gen3_fixture_runs/bootcheck_<stem>/`) as `<romname>.SaveRAM`
   — nothing stripped, nothing appended; BizHawk writes the optional 16-byte
   RTC suffix itself and `import` normalizes it back out. A per-run copy of
   BizHawk's `config.ini` points the **GBA** Save RAM path there, so no
   developer battery save is ever read or overwritten.
2. `lua/tests/gen3_boot_check.lua` cold-boots the ROM, takes CONTINUE, and
   detects the field with the profile's own `callback2` predicate
   (`gMain.callback2 == CB2_Overworld`, from
   `data/games/gen3_{frlg,rr}/write_checkpoint.json`) — **not** a populated
   party, because RR loads the save into RAM during the intro so the main menu
   can show CONTINUE stats (`lua/tests/mkstate.lua:38-46`).
3. It opens the START menu and finds the SAVE row by **asking the engine**
   (`sSaveDialogCB` becomes non-zero), walking one row per attempt and backing
   out of a wrong row with B. FR's and RR's menus differ in row order and RR's
   row count moves with the companion patch, so no row index is hardcoded and
   no input sequence here is a guess.
4. The save is proven by the **flash sector counter advancing** in the
   SaveRAM-backed memory domain (bound at run time from
   `memory.getmemorydomainlist()`), never by assuming a button press worked.
   Then `client.saveram()` flushes.
5. Python re-imports the flushed battery and requires: it still qualifies
   (which is where "sector set complete" lives — `codec.qualify_flash` refuses
   a missing/duplicate/torn sector), the counter advanced by **exactly 1**, and
   the party is unchanged. Prints `BOOT-CHECK PASS|FAIL`.

A cartridge BizHawk's **gamedb knows** (a clean FR/LG dump) is filed under the
gamedb name, not the ROM filename, so the seed lands where the emulator will
not look. The run then fails loudly (erased battery at boot); pass
`--saveram-name "Pokemon - FireRed Version (USA).SaveRAM"` to seed it
correctly. The failure message names the file BizHawk actually wrote.

## `make-fr` — the scripted FireRed/LeafGreen NEW GAME (card C4-LGF2)

```
python tools/gen3_fixtures.py make-fr --rom "<FireRed.gba>" --out tests/fixtures/gen3/firered_town.sav
python tools/gen3_fixtures.py make-fr --title leafgreen --rom "<LeafGreen.gba>" --out tests/fixtures/gen3/leafgreen_town.sav
```

Cold-boots an **erased** per-run SaveRAM directory (so the title offers NEW
GAME), drives `lua/tests/gen3_fr_newgame_inputs.lua` through the intro, walks
out of the house into Pallet Town, saves in-game, flushes, then `import`s and
qualifies the result as vanilla. Replaces steps 1-4 of the old hand recipe
below. Step 5 (`derive-b`) and the `boot-check` above are still run by hand.

**Owner ruling 2026-09-23 (card C4-LGF2): "the intro is the same as
FireRed, why not just copy it?"** FireRed and LeafGreen are the same pret
pokefirered engine built twice, so this ONE driver plays the intro on
either title (`--title leafgreen`); there is no separate LG intro script.

**WITNESS-DRIVEN, not timed.** The intro legs used to be placed by fixed
elapsed-frame counts (`SLINK_GEN3_FR_INTRO` / `SLINK_GEN3_FR_NAME_GAP`,
tuned once on FR US 1.0, 2026-09-21). That broke on LeafGreen: the SCREENS
and CHOICES are identical (physically confirmed) but the ELAPSED FRAMES to
reach each one are not, so an FR-tuned budget landed an input a beat early
or late. `data/gen3/pret/pokefirered.sym` and `pokeleafgreen.sym` DO ship
in this tree (`lua/tests/gen3_title_syms.lua` already reads both), so the
driver now waits on the engine's own state instead of a frame guess, the
same "wait for the task/callback2, never a frame count" shape
`gen3_boot_check.lua`'s SAVE-row search (`c1507b7d`) already uses:
`Task_OakSpeech_HandleGenderInput` gates the gender press, `CB2_NamingScreen`
gates both naming screens (title-checked in `test_gen3_title_syms.py`), and
the starter-nickname Yes/No decline in `gen3_scripted_play.lua`'s own
`starter` leg is gated by `Task_YesNoMenu_HandleInput` the same way. Only
the CHOICE at each screen is still a citation-backed pin, never the timing:
†1 A on the gender prompt takes BOY; †2 the player-name screen is a preset
list, so Down+A accepts a preset instead of opening the keyboard; †3 the
rival-name screen has the same shape.
Everything after the intro is signalled, not timed: the walk out is keyed to
the SaveBlock1 map id (`lua/memory_gba.lua:1109-1114`) and the save to the
flash sector counter, so a mistuned intro fails on a budget with a
screenshot rather than writing a fixture from the wrong game state.

## FR/LG production recipe, by hand

The fallback if the scripted intro above will not run on a given ROM/title:

1. Boot a clean FR or LG US 1.0 ROM in BizHawk from a fresh (erased) save.
2. Play a NEW GAME through the intro to the first Pokémon Center town (an
   encounter-free walk to a save point, matching the "town" kind
   `tools/mkstates.py` uses for Gen 1/RR: no wild-encounter ground under
   foot when the save is made).
3. Save **in-game** (the in-game save menu, not a BizHawk savestate) and
   close the emulator so the `.SaveRAM` flushes.
4. `python tools/gen3_fixtures.py import --src "<BizHawk GBA/SaveRAM path>" --out tests/fixtures/gen3/fr_town.sav`
   (drop `--rr`; vanilla `qualify_flash` applies the strict slot/checksum
   witness).
5. `python tools/gen3_fixtures.py derive-b tests/fixtures/gen3/fr_town.sav tests/fixtures/gen3/fr_town_b.sav`
   for the B-side fixture -- vanilla `derive-b` is fully implemented (OTID
   + OT-name re-key, secure-data re-encrypt/re-checksum, sector checksums
   recomputed; see the manifest it prints).
6. Both fixtures still need `boot-check` above before they are trusted as
   more than model-qualified bytes.

## firered_town.sav (2026-09-21)

Vanilla FireRed US 1.0 (sha1 `41cb23d8…`), produced by `tools/gen3_fixtures.py make-fr` (`lua/tests/gen3_fr_newgame_inputs.lua`): cold boot → NEW GAME → intro → the pinned walk 2F (6,6) → stairs (10,2) → 1F → door (4,8) → Pallet Town (map 768) → START/SAVE. sha256 `dde9360296ea69d0373f993f7cab35cee49d2803ed78d410145bc478182a3ae5`, slot 1, counter 1, trainer `JONN` #99DE0D8A, **party empty (pre-starter)**. Boot-checked (`docs/gen3/probes/bootcheck_firered_town_2026-09-21.txt`, counter 1→2, 14/14 sectors). BizHawk files its battery under the gamedb name `Pokemon - FireRed Version (USA).SaveRAM`, so seed with `--saveram-name` accordingly. Scenarios that need a party (faint, boxsync) need an extended script through the starter choice; queued.

## rr_town_b.sav (2026-09-21)

Derived from `rr_town.sav` by `tools/gen3_fixtures.py derive-b --rr` (Codex card C2-8, pinned RR layout): player OTID XOR 0xFFFFFFFF, name `B` → `BB`, every owned record's OTID/OT-name re-keyed in place (fixed-order unencrypted RR records, no vanilla XOR/checksum), only the two changed chunks' sector checksums recomputed, parasite/extension bytes byte-identical. sha256 `13da0f15400894b78077a236514a54c01e4085d53a02821f411e428c9f51f1d3`. Boot-checked (`docs/gen3/probes/bootcheck_rr_town_b_2026-09-21.txt`, counter 2→3, 14/14 sectors, trainer `BB` #3559012160 after the boot). Seeded under the default battery name (`gen3 slink RR.SaveRAM`).

## firered_party_battle.sav / firered_party_town.sav (+ `_b`, 2026-09-23)

Party fixtures (card gen3-P4-C4-F). **Only scripted normal inputs — no
memory pokes, no Computer Use, no byte-patched position.** Built entirely
by cold-booting a battery through CONTINUE and walking/healing/fleeing
with `lua/tests/gen3_fixture_from_state.lua`
(`tools/gen3_fixtures.py make-fr-party`); `derive-b` (PLAN §11, OT identity
only) is the one byte-level derivation used anywhere in this pair.
`savestate.load()` mid-script is never used — every session is a real cold
boot.

Build order matters and is split into two separate cold-boot sessions at
the natural midpoint (Viridian City), not one long session:

1. **`town`** — cold-boots the accepted, unhealed
   `firered_party_battle.sav` (below) → CONTINUE, flees every incidental
   Route 1 encounter (never fights), walks to the Viridian Pokemon Center,
   heals the whole party, walks back out to Viridian's own south tile
   (24,39, non-grass town ground), saves in-game via the START menu.
2. **`battle`** — cold-boots `town`'s own healed output → CONTINUE, walks
   the short leg back to Route 1's grass origin (12,37), saves there.

A single cold-boot session covering the whole heal-and-return round trip
(~9500-12000 frames) reproducibly left EmuHawk exiting with no RESULT line
partway through; splitting at Viridian (each session roughly half the
length) never reproduced it — recorded as an instrument limit, not a game
bug.

**Root cause of an earlier false "silent crash" diagnosis**: `returncode=1`
with no RESULT line in the driver's own result file looked like a host
crash, but was our own `finish(false, ...)` firing through
`gen3_scripted_play.lua`'s *separate* `dofile`'d module instance — `dofile`
re-executes a file fresh on every call, so that instance's own `G` was
never `G.open()`'d and wrote its FAIL line nowhere the driver read. Fixed
by routing every finish-capable call in `gen3_fixture_from_state.lua`
(`my_verify_destination`, `my_return_to_grass_origin`, `follow_running`,
`reach_target`) through the driver's own `G` exclusively; no code here
calls into `gen3_scripted_play.lua`'s finish-capable helpers anymore.

**The real bug that diagnosis then surfaced**: `save_via_menu`'s SAVE-row
search (shared, `lua/tests/gen3_boot_check.lua`, read-only here) presses
only Start/A/B/Down while hunting for the right row. A stray Down can leak
past the menu onto the bare field mid-search, and — since the search can
take many attempts — that stray press can walk the player across the
Route1↔Viridian↔Pallet map connections *during* the save transaction, so a
`sok=true` verdict from `save_via_menu` is not proof the saved data is at
the intended tile. Both directions were observed: Route 1's grass square
drifting into Pallet Town while saving "battle", and Viridian drifting back
onto Route 1 while saving "town". Fixed in `gen3_fixture_from_state.lua`,
not in the shared save driver: `save_at` now re-verifies position *after*
every save (not just before) and retries — recover position via
`reach_target`, save again — up to 8 attempts, since one drift can chain
into a longer, drift-prone row search on the very next attempt.

- `firered_party_battle.sav`: saved standing in Route 1 tall grass (map
  3.19, tile (12,37)). sha256
  `95f047f0bd9c54014d81720858869f7c46a484362d5751df27fe6cc54287024e`, slot
  1, counter 7, trainer `JONN` #99DE0D8A, party `[Squirtle Lv.9 hp=27/27,
  species 16 (Pidgey) Lv.4 hp=17/17]` — both mons fully healed (`hp ==
  max_hp`), not merely non-fainted. Boot-checked (cold boot → CONTINUE →
  re-save → reload, counter 7→8, 14/14 sectors, party unchanged).
- `firered_party_town.sav`: saved standing on Viridian City's own south
  tile (map 3.1, tile (24,39)), non-grass town ground. sha256
  `db60478826f16ff02c04ff5dc7df67579cf3e32ef99ca4dfbb36cd976047e213`, slot
  0, counter 4, trainer `JONN` #99DE0D8A, same fully-healed party as the
  battle fixture. Boot-checked (counter 4→5, 14/14 sectors, party
  unchanged).
- `firered_party_battle_b.sav` / `firered_party_town_b.sav`: `derive-b`
  over the two fixtures above (vanilla path — OTID/OT-name re-keyed on
  both party mons, secure data re-encrypted/re-checksummed, sector
  checksums recomputed; position bytes untouched, so each `_b` fixture
  sits on the exact same tile as its `a` side). sha256
  `d90e464960551dc953d475b40a3f386c1729c5bafab6ac845db649fe2819daab` and
  `3fcb2975cadec0caa1a750a12a90c1a0d47cb5d3938627bc8dbe5a14ba18bd9e`,
  trainer `JONNB` #6621F275, same party (species/level/HP) as the `a`
  side. Both boot-checked (counter 7→8 and 4→5, 14/14 sectors, party
  unchanged).

The `retarget-position` subcommand this section previously described (a
pure SaveBlock1 pos/map byte patch, used to build an earlier
`firered_party_town.sav`) has been **removed**: it is game-data staging,
not a scripted normal input, and is out of scope under this card's
contract. `derive-b`'s OT-identity rewrite is the only PLAN-sanctioned
byte-level derivation (PLAN §11); it never touches position.

## LeafGreen fixtures (card C4-LGF2, 2026-09-23)

**Built.** Owner ruling: *"the intro is the same as FireRed, why not just
copy it?"* FireRed and LeafGreen are one `pret/pokefirered` decomp built
twice, so `make-fr`/`make-party` drive LG through the exact same scripted
runtime as FR (`--title leafgreen`), no LG-only script. Every DATA symbol
the walk/heal/flee/save legs read sits at the identical address in both
`.sym` files (checked symbol by symbol by `tests/unit/test_gen3_title_syms.py`),
and `DEST`/`PATHS` describe maps the two titles share (Pallet Town, Route 1,
Viridian City) — confirmed, not just inferred, by the physical LG runs below.

### The chain that produced these fixtures

1. `make-fr --title leafgreen` → `leafgreen_town.sav` (pre-starter, cold
   boot → NEW GAME → intro → Pallet Town → save). The intro is
   **witness-driven** (`Task_OakSpeech_HandleGenderInput` /
   `CB2_NamingScreen`, `lua/tests/gen3_title_syms.lua`), not frame-timed —
   see the `make-fr` section above.
2. `gen3_scripted_play.lua` with `SLINK_GEN3_TITLE=leafgreen` and
   `SLINK_GEN3_PLAY_STOP_AFTER=route1_catch` (an env knob added for this
   card): runs the Pallet Town story — starter, rival battle, the Parcel
   errand (which gates Poké Balls in FRLG), Route 1 catch — then walks back
   to the grass origin (12,37) and saves in-game, producing a source
   battery with an unhealed two-mon party standing exactly where
   `make-party --kind town` expects its seed. Every per-step oracle in this
   file (`verify_starter`, `verify_rival`, the parcel-delivery witnesses,
   the catch outcome) ran unmodified against LG and would have failed by
   name on a wrong outcome; none did.
3. `import` the flushed battery, then `make-party --title leafgreen --kind
   town` (heals at the Viridian Center, saves at (24,39)) and `--kind
   battle` (seeded from town's own output, saves at Route 1 grass (12,37)).
4. `derive-b` both (vanilla path: OTID/OT-name re-key, position untouched).
5. `boot-check --title leafgreen` all four, `--saveram-name "Pokemon -
   LeafGreen Version (USA).SaveRAM"` (LG is gamedb-known, like FR).

```bash
python tools/gen3_fixtures.py make-fr --title leafgreen --rom "<LeafGreen.gba>" --out tests/fixtures/gen3/leafgreen_town.sav
# (the SLINK_GEN3_PLAY_STOP_AFTER story-seed run is a coordinator/emulator-lane step, not a CLI subcommand yet)
python tools/gen3_fixtures.py import --src "<BizHawk GBA/SaveRAM path>" --out /tmp/lg_seed.sav
python tools/gen3_fixtures.py make-party --title leafgreen --kind town   --seed /tmp/lg_seed.sav --out tests/fixtures/gen3/leafgreen_party_town.sav
python tools/gen3_fixtures.py make-party --title leafgreen --kind battle --seed tests/fixtures/gen3/leafgreen_party_town.sav --out tests/fixtures/gen3/leafgreen_party_battle.sav
python tools/gen3_fixtures.py derive-b tests/fixtures/gen3/leafgreen_party_town.sav   tests/fixtures/gen3/leafgreen_party_town_b.sav
python tools/gen3_fixtures.py derive-b tests/fixtures/gen3/leafgreen_party_battle.sav tests/fixtures/gen3/leafgreen_party_battle_b.sav
python tools/gen3_fixtures.py boot-check --title leafgreen --rom "E:/Google Drive/SLink/Pokemon - LeafGreen Version (USA).gba" --saveram-name "Pokemon - LeafGreen Version (USA).SaveRAM" --fixture tests/fixtures/gen3/leafgreen_party_town.sav
```

### What differed from the FR precedent, and how the oracles caught it

- **The gender/naming-screen intro was frame-timed, tuned once on FR.**
  Same screens and choices on LG, different elapsed frames — an FR-tuned
  budget could land an input a beat early/late. Fixed by waiting on the
  engine's own task/callback2 (`Task_OakSpeech_HandleGenderInput`,
  `CB2_NamingScreen`) instead of a frame count; re-verified on FR too (same
  landing tile/map, `RESULT: PASS map=768 counter -1 -> 1`).
- **The town-save door-exit tile.** `firered_town.sav` (built 2026-09-21,
  before the SAVE-row search's stray-Down bug was fixed at the root,
  `c1507b7d`) sits at (6,9); a battery built with the fixed helper rests at
  the engine's true post-door-exit tile, (6,8), one short. The `starter`
  leg's own `town_start_to_oak_trigger` path is pinned to (6,9); a one-step
  bridge (a no-op for FR's own already-committed fixture) covers the gap.
- **The starter-nickname Yes/No decline.** Alternating blind A/B taps (the
  FR-only design) let an A land on the nickname prompt's own default YES
  one iteration before B could decline it — opening the naming keyboard,
  caught by name (`patch/build/gen3_stuck.png`) rather than silently
  mis-saving. Fixed by witnessing `Task_YesNoMenu_HandleInput` and pressing
  B only while it is the active task.
- **An incidental battle at the Route 1 / Pallet Town connection.**
  `parcel_deliver`'s `warp_to(..., DEST.pallet_north, ...)` failed with
  `map never changed from 787`: Route 1's own south/north edges are tall
  grass, so a wild encounter can start while pressing *into* the
  connection, and `playlib`'s `enter_warp` has no battle policy of its own.
  `warp_to` now resolves an incidental battle (`play.in_battle` /
  `play.fight_through`, the same pattern `route1_faint` already used) before
  retrying the press — deterministic regardless of where the encounter
  rolls, verified by re-running the identical seed (cold-boot emulation is
  deterministic: the same encounter fired at the same frame both times).

None of this needed a single LG-specific address, map, or literal beyond
the three witnesses above (all title-checked by `test_gen3_title_syms.py`).

### leafgreen_town.sav / leafgreen_party_{town,battle}[_b].sav

- `leafgreen_town.sav`: pre-starter, Pallet Town (map 768). sha256
  `98f562460399ec45c55182dcf44986163f96826ea16ed51677f7216ef245c2b0`, slot
  1, counter 1, trainer `MAX` #1C600D89, party empty. Not independently
  boot-checked (it is consumed immediately by the story-seed run; the four
  party fixtures below carry the boot-check receipts).
- `leafgreen_party_town.sav`: saved on Viridian City's own south tile (map
  3.1, tile (24,39)). sha256
  `b2f4e5476a179973f3016bb0391baed5c91df72b818973bbb500024569a21db2`, slot
  1, counter 3, trainer `MAX` #1C600D89, party `[Squirtle Lv.6 hp=23/23,
  Rattata Lv.3 hp=15/15]`, both fully healed. Boot-checked (counter 3→4,
  14/14 sectors, party unchanged).
- `leafgreen_party_battle.sav`: saved standing in Route 1 tall grass (map
  3.19, tile (12,37)). sha256
  `3922d561ff671b86f3f82e84be6068a2ce1f6a4a60df942831dadd9ebe6a01ae`, slot
  0, counter 4, same trainer and healed party as the town fixture.
  Boot-checked (counter 4→5, 14/14 sectors, party unchanged).
- `leafgreen_party_town_b.sav` / `leafgreen_party_battle_b.sav`: `derive-b`
  over the two fixtures above (OTID/OT-name re-keyed, position untouched).
  sha256 `710898c92d7b01832a502ebba33c49dc14e751b2b9f1c9469ac862ddd9586497`
  and `934184df33c5de0f8eeac56d1647ab465664ad2fd047fda8dd1475ce35af7b11`,
  trainer `MAXB` #E39FF276, same party (species/level/HP) as the `a` side.
  Both boot-checked (counter 3→4 and 4→5, 14/14 sectors, party unchanged).

`tests/unit/test_gen3_fixture_qualify.py::test_lg_party_fixtures_match_the_fr_contract`
and `::test_lg_party_b_variant_has_a_distinct_trainer_at_the_same_place` now
run (no longer skip) and pass against these five committed files.

## rr_battle.sav / rr_battle_b.sav (card G4-LANE-1, 2026-09-24)

The Radical Red analogue of `firered_party_battle{,_b}.sav`: the party standing on Route 1's
grass origin (map 3.19, tile (12,37)), the tile every Gen 3 duo grass hunt starts from
(`lua/tests/gen3_scripted_play.lua` `GRASS_ORIGIN`/`GRASS_LOOP`). **Only scripted normal
inputs**: no memory pokes, no savestate, no save editing; `derive-b --rr` (PLAN §11, OT identity
only) is the one byte-level derivation, exactly as for `rr_town_b.sav`.

**Geometry from the RR ROM, never a screenshot.** Parsed out of `patch/build/slink_RR.gba`
(sha1 `b7d1e0756fcc66575878affc8f7b95c45386bb1c`) with `tools/gba_map.py`. RR's code still loads
`gMapGroups` 0x083526A8 from its single literal-pool word at 0x0805524C (the same word FR US 1.0
has), and RR's map 3.19 parses byte-identical to FR US 1.0's (collision, metatile behaviours,
connections), so the FR grass square exists unchanged on RR:

```
python tools/gba_map.py patch/build/slink_RR.gba --map 3.19 --bfs 7,33 12,37 --find-behaviour 0x02
# bfs (7,33) -> (12,37): Down Down Right Right Right Right Right Down Down
# MB_TALL_GRASS (0x02) includes (7,33) (12,37) (13,37) (12,38) (13,38)
```

Note: `rr_town.sav`'s own tile, (7,33) on map 3.19, is also MB_TALL_GRASS by the same parse
(it is the battery `tools/mkstates.py` captured `slink_prebattle.State` from), so despite its
name it is not encounter-free town ground.

Built by `lua/tests/gen3_rr_battle_fixture.lua` (new, this card) in the clean lane checkout at
`f6d503f4`: seed `rr_town.sav` into a per-run SaveRAM dir → cold boot → CONTINUE → verify the
start tile (7,33) → `playlib.follow` the pinned BFS path (any wild battle is fled with RUN,
never fought; none fired on this run) → START/SAVE via `gen3_boot_check.lua` `save_via_menu` →
re-verify the tile. Launched through `tools/gen3_fixtures.py`'s own `_prepare_run`/`_launch`
(`rr=True`, title `radical_red`, rewind off via `write_gba_run_config`), then `import_savedata(rr=True)`:

```python
# from the repo root
import sys; sys.path[:0] = ["tools", "."]
import gen3_fixtures as fx
from server.adapters import gen3_codec as codec
seed = codec.split_rtc(open("tests/fixtures/gen3/rr_town.sav", "rb").read())[0]
rom_rel, run_dir, battery = fx._prepare_run("rr_battle_fixture", "patch/build/slink_RR.gba",
                                             seed=seed, saveram_name_override=None)
passed, text = fx._launch("lua/tests/gen3_rr_battle_fixture.lua", rom_rel, run_dir, rr=True,
                          timeout=1800, title="radical_red")
body = fx.import_savedata(fx._flushed_saveram(run_dir, battery).read_bytes(), rr=True)
```
```
python tools/gen3_fixtures.py derive-b --rr tests/fixtures/gen3/rr_battle.sav tests/fixtures/gen3/rr_battle_b.sav
python tools/gen3_fixtures.py boot-check --rom patch/build/slink_RR.gba --fixture tests/fixtures/gen3/rr_battle.sav --rr
python tools/gen3_fixtures.py boot-check --rom patch/build/slink_RR.gba --fixture tests/fixtures/gen3/rr_battle_b.sav --rr
```

- `rr_battle.sav`: driver `RESULT: PASS counter 2 -> 3 at map=787 at=(12,37) healed=true
  party=[1] species=277 level=6 hp=22/22`. sha256
  `d9fe5eb6a0b3ea3dc778162584b9d7169fc3bdb38555f709f217113b33319c4b`, slot 1, counter 3, trainer
  `B` #2BDDC8BF, party `[Treecko (277) Lv.6 hp=22/22]` (key `EBEF11DA:2BDDC8BF`), fully healed.
  Boot-checked (counter 3→4, 14/14 sectors, party unchanged).
- `rr_battle_b.sav`: `derive-b --rr` over the above (OTID 0x2BDDC8BF → 0xD4223740, name `B` →
  `BB`; party[0] OTID/OT-name re-keyed; only sectors 17/18 (ids 0/1) checksums recomputed;
  position bytes untouched). sha256
  `140ad05c6325180bdc7fae0bb590157310f250fa65c5b8b43b1fb24d6a3ffe2b`, slot 1, counter 3.
  Boot-checked (counter 3→4, 14/14 sectors, party unchanged).
- Runtime confirmation (scratch probe, not committed): cold boot of `rr_battle.sav`, pace the
  `GRASS_LOOP` square → `wild battle after 11 grass steps at (13,38)`.
- Seeded under the default battery name `gen3 slink RR.SaveRAM`.

**Differences from the FR analogue a scenario author must know.** The party is ONE mon
(`rr_town.sav`'s), and the CFRU ball pocket is EMPTY (`tools/e2e_duo.py` `gen3_ball_count` → 0;
FR's battle fixture has 4). Ball-throwing (`ball_hunt`) and two-mon scenarios cannot run from
these fixtures as they stand; a second mon or balls need an RR scripted-play leg (purchase or
story) that no card has pinned yet.
