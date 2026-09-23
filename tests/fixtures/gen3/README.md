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

## `make-fr` — the vanilla FireRed fixture

```
python tools/gen3_fixtures.py make-fr --rom "<FireRed.gba>" --out tests/fixtures/gen3/firered_town.sav
```

Cold-boots an **erased** per-run SaveRAM directory (so the title offers NEW
GAME), drives `lua/tests/gen3_fr_newgame_inputs.lua` through the intro, walks
out of the house into Pallet Town, saves in-game, flushes, then `import`s and
qualifies the result as vanilla. Replaces steps 1-4 of the old hand recipe
below. Step 5 (`derive-b`) and the `boot-check` above are still run by hand.

> **†UNVERIFIED — every input in the FireRed intro is a guess.**
> `pret/pokefirered` is not in the local pret cache
> (`E:/Google Drive/SLink/.cache/pret/` holds pokered, pokeyellow, pokecrystal,
> pokegold, pokeheartgold, pokeplatinum) and this tree ships no
> `pokefirered.sym`, so the naming screen's callback and menu geometry cannot
> be pinned. Named in the driver's header banner:
> †1 A on the gender prompt takes BOY; †2 the player-name screen is a preset
> list, so Down+A accepts a preset instead of opening the keyboard; †3 the
> rival-name screen has the same shape; †4 the **frame counts** that place †2
> and †3, since no engine signal marks those screens — retune with
> `SLINK_GEN3_FR_INTRO` / `SLINK_GEN3_FR_NAME_GAP`.
> Everything after the intro is signalled, not timed: the walk out is keyed to
> the SaveBlock1 map id (`lua/memory_gba.lua:1109-1114`) and the save to the
> flash sector counter, so a mistuned intro fails on a budget with a
> screenshot rather than writing a fixture from the wrong game state.

## FR/LG production recipe, by hand

The fallback when `make-fr`'s †UNVERIFIED intro legs will not tune, or for
LeafGreen (which has no scripted driver):

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

## LeafGreen (planned, card C4-LGF)

**Nothing LG is built yet.** What this card changed is that the lane is now
*drivable* on LG: `make-party` (`make-fr-party` is the old alias, same
handler) takes `--title leafgreen`, the Lua party driver
(`lua/tests/gen3_fixture_from_state.lua`) resolves its title from
`SLINK_GEN3_TITLE` and picks that title's own profile entry instead of
hardcoding `firered`, and the shared scripted runtime it dofiles
(`gen3_scripted_play.lua`) was already title-aware from card C4-LG/LG2.

Why LG is cheap in principle: FireRed and LeafGreen are one
`pret/pokefirered` decomp built twice. Every DATA symbol the walk / heal /
flee / save legs read sits at the identical address in both `.sym` files
(checked symbol by symbol by `tests/unit/test_gen3_title_syms.py`), and
`DEST`/`PATHS` describe maps the two titles share (Pallet Town, Route 1,
Viridian City). So the driver needs no LG-specific address and no LG-specific
map table. What it does need is a **source battery with a party**, and that
is the one part still unwitnessed.

### The LG source save (the decision this card had to make)

`lua/tests/gen3_fr_newgame_inputs.lua` — the scripted NEW GAME that produced
`firered_town.sav` — is **FR-only by nature** and now refuses LG by name
(`python tools/gen3_fixtures.py make-fr --title leafgreen …` exits 1 with the
reason). Its intro legs (copyright, Oak, gender, two naming screens) are
placed by *elapsed frames*, not by a signal, and were verified physically on
FR US 1.0 only; LG's screens have never been calibrated, and the driver will
not guess a mistimed intro (a mistuned one fails loudly, but nobody has
tuned it). No frame count is proposed here: that is an emulator-lane job.

Two admissible ways to get LG's party-bearing battery, both using **normal
inputs only** — no memory pokes, no game-data staging, no Computer Use, the
same contract the FR pair was built under:

1. **Hand-play the minimum path, then script the rest** (recommended first
   pass). The minimum path to a starter plus one catch is: NEW GAME → the
   intro (gender + two names) → out of the house → Oak's lab → pick a starter
   → fight the rival → walk Route 1 north to Viridian → the Mart, take Oak's
   Parcel → back to Pallet, deliver it to Oak → receive Poké Balls → Route 1
   grass, throw a ball at the first encounter and catch it. (The Parcel
   errand is what gates Poké Balls in FRLG; there is no earlier ball.) Then
   save in-game standing in Route 1's grass at (12,37) and close BizHawk so
   the `.SaveRAM` flushes. Import it as the seed, then run the two party
   kinds below — everything after this point is scripted.
2. **A calibrated scripted new game.** If the FR new-game legs turn out to
   match LG's intro (same engine, same screens), the cheapest fix is to give
   LG its own `SLINK_GEN3_FR_INTRO` / `SLINK_GEN3_FR_NAME_GAP` values from a
   physical run and then relax the refusal. Not attempted here; the refusal
   names it.

A third option exists for the *story* legs specifically — the shared runtime's
own `route1_catch` leg is title-aware, so `SLINK_GEN3_TITLE=leafgreen` on that
gate can drive starter + catch from an LG pre-starter save — but it is the
same emulator lane and it still needs that pre-starter save first.

### The LG commands, in order

```bash
# 0. once: the imported party-bearing seed (see "The LG source save" above),
#    saved in Route 1 grass at (12,37) with a healed two-mon party
python tools/gen3_fixtures.py import --src "<BizHawk GBA/SaveRAM path>"     --out /tmp/lg_seed.sav

# 1. town -- heals at the Viridian Center, saves on Viridian's south tile (24,39)
python tools/gen3_fixtures.py make-party --title leafgreen --kind town     --seed /tmp/lg_seed.sav --out tests/fixtures/gen3/leafgreen_party_town.sav

# 2. battle -- seeds from town's own healed output, saves in Route 1 grass (12,37)
python tools/gen3_fixtures.py make-party --title leafgreen --kind battle     --seed tests/fixtures/gen3/leafgreen_party_town.sav     --out tests/fixtures/gen3/leafgreen_party_battle.sav

# 3. B sides (vanilla derive-b: OT identity only, position untouched)
python tools/gen3_fixtures.py derive-b tests/fixtures/gen3/leafgreen_party_town.sav     tests/fixtures/gen3/leafgreen_party_town_b.sav
python tools/gen3_fixtures.py derive-b tests/fixtures/gen3/leafgreen_party_battle.sav     tests/fixtures/gen3/leafgreen_party_battle_b.sav

# 4. usability: cold boot -> CONTINUE -> re-save -> reload, one per fixture
python tools/gen3_fixtures.py boot-check --title leafgreen     --rom "E:/Google Drive/SLink/Pokemon - LeafGreen Version (USA).gba"     --fixture tests/fixtures/gen3/leafgreen_party_battle.sav
```

`--rom` is optional: without it the builder uses the title's own dump from
`tools/gen3_fixtures.py:PARTY_TITLES`, searched upward from the repo root
(the dumps live at the main checkout root). The battery is seeded under the
gamedb name `Pokemon - LeafGreen Version (USA).SaveRAM`; if BizHawk files it
under something else the run says so and tells you which `--saveram-name` to
pass next time. The LG pair is asserted by
`tests/unit/test_gen3_fixture_qualify.py::test_lg_party_fixtures_match_the_fr_contract`
(two fully healed mons, the kind's own tile, A/B OTs distinct and positions
identical), which skips until the files exist.

### LG-specific unknowns

- **The intro (only if option 2 is taken)**: LG's naming screens are
  frame-timed and uncalibrated; FR's values are not reused.
- **The shared tiles are INFER for LG.** `DEST`/`PATHS` come from
  `gen3_scripted_play.lua`, whose coordinates are FR-sourced. The maps are the
  same map data in both titles, so the tiles should be identical — but no LG
  run has confirmed (12,37)/(24,39) yet. The first `make-party --title
  leafgreen` pass is what turns this into a receipt; its driver verifies the
  destination tile and refuses on mismatch rather than saving somewhere else.
- **The gamedb battery name** for an LG dump is assumed to mirror FR's; the
  tool prints the name it seeded and the name BizHawk actually wrote.
- **The flee machinery** is shared and level-agnostic; an LG party of two
  early-route mons is expected to escape Route 1 wildlife on the same terms
  FR does (first-attempt success is not assumed — the loop retries).
