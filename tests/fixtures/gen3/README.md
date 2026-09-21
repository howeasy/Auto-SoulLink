# Gen 3 fixtures

Built and checked by `tools/gen3_fixtures.py` (worker card gen3-P2-C2-6). No
ROM, no emulator: `import`/`qualify`/`derive-b` are all pure byte
transformations over `server/adapters/gen3_codec.py`, the independent
Python codec described in `docs/gen3/PLAN.md` §5.5 and derived per
`docs/gen3/research/flash_save.md`.

## Naming

`<pack>_<scene>[_b].sav`, e.g. `rr_town.sav`. `<pack>` is `rr` (Radical Red
companion) or `fr`/`lg` (vanilla FireRed/LeafGreen, not produced by this
card -- see "FR/LG production recipe" below). `_b` marks a distinct-OT
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

## What `--boot-check` will do (coordinator lane, not this tool)

`tools/gen3_fixtures.py` never launches EmuHawk. Per `docs/gen3/PLAN.md`
§5.5, model qualification (`qualify`, this tool) is necessary but not
sufficient: usability is signed only by a real cold boot -> CONTINUE ->
re-save -> reload of each fixture, run by the coordinator's emulator lane
(`python tools/gen3_fixtures.py --boot-check`, not yet implemented here --
lease scope stops at model qualification). That run loads the fixture as
the ROM's battery save, confirms the title screen offers CONTINUE (proving
the save the loader itself accepts, not just this tool's stricter
`qualify_flash`), advances into the game, saves again in the emulator, and
reloads -- the same three-step proof `tools/mkstates.py`'s town/battle
states use for Gen 1/RR savestates, but for a battery save instead of a
`.State`.

## FR/LG production recipe (not produced by this card)

No vanilla FireRed/LeafGreen save exists yet in this tree. To produce one:

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
6. Both fixtures still need the emulator `--boot-check` above before they
   are trusted as more than model-qualified bytes.
