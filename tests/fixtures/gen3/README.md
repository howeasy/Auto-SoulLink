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
