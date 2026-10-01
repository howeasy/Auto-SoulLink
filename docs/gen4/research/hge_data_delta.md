# hge vs vanilla HG: G2 data delta

Card `gen4-G2-hge-delta`. Question: for each G2 dataset (commit c6698595, generated from pokeheartgold @ad7a3afa), does the hge build differ from vanilla HG, and how must an hge generator source its data?

- **hge ROM:** `.cache/gen4/hge/build-fc5175764983/test.nds`, sha1 `cb2dc435196d09c8c9209bf037240ed834f4cea1`. Built from fork `fc517576498305ecb5f5e1de44681c6e3822361b` (clean).
- **Vanilla ROM:** `E:/Howard/Bizhawk/Pokemon - HeartGold Version (USA).nds`, sha1 `4fcded0e2713dc03929845de631d0932ea2b5a37`.
- **Tags:** FILE = measured on the two ROMs with ndspy (scratch `C:/Users/howar/AppData/Local/Temp/claude/gen4-hge-delta/`: `cmp.py enc.py tr.py mh.py msg.py names.py`). SOURCE = read in the fork or pokeheartgold, not measured on the ROM.
- **Hashes** are the first 12 hex of sha1 over the whole NARC file.

## Summary

| Dataset | Verdict | hge generator source |
|---|---|---|
| 1. Wild encounters | IDENTICAL (bytes) | ROM NARC `a/0/3/7`; the committed `encounters.json` (heartgold side) already holds this data |
| 2. Trainers | IDENTICAL in content (34 `trpoke` members differ by trailing pad only); format is a superset but unused by this build | ROM `a/0/5/5` + `a/0/5/6` + msg 729 |
| 3. Map headers / mapsec / areas | IDENTICAL | ROM arm9 `sMapHeaders` + msg 279, or reuse `area_map.json`/`locations.json` |
| 4. Acquisition | IDENTICAL data; CHANGED code (helpers replaced) | reuse the vanilla script sites; hge adds no new sites |
| 5. Id spaces / names | CHANGED-FORMAT (id spaces) | ROM msg members 237 / 750 / 222 plus the fork's constant headers |

Nothing in G2 needs a new hge extraction format. The one real hge change is the id spaces (§5): species above 493 are not national-dex numbers.

## 1. Wild encounters: IDENTICAL

**Where the data lives (SOURCE).** pokeheartgold `files/fielddata/encountdata/gs_enc_data.json` becomes NARC `a/0/3/7` (142 banks, 196 bytes each). Bank index = `ENCDATA_*` from `include/encounter_tables_narc.h`. hge builds the same path from `data/Encounters.c` (`narcs.mk:520-531`, `Makefile:444-445`), including the 142 `[ENCDATA_...]` entries.

**FILE: NARC bytes.**

| NARC | vanilla | hge | verdict |
|---|---|---|---|
| `a/0/3/7` wild encounters | `1475986b752a`, 29020 B, 142 members | `1475986b752a`, 29020 B, 142 members | SAME, 0 changed banks |
| `a/2/5/2` headbutt | `8a2d55cbb5c5`, 540 members | `8a2d55cbb5c5` | SAME |
| `a/2/3/0` Safari | `92e0b4252f75`, 12 members | `92e0b4252f75` | SAME |

The fork compiles `Encounters.c` into the ROM (`cp $(ENCOUNTER_NARC) $(ENCOUNTER_TARGET)`), so the copy was run. It simply reproduces vanilla.

**Format: CHANGED-FORMAT-SAME.**
- FILE: all 142 banks are 196 bytes in both ROMs.
- SOURCE: the 196-byte layout is `include/encounter.h` `EncounterData`: 8 header bytes, then land `levels[12]` and `species{Morning,Day,Night}[12]` as u16, 2+2 sound species, surf 5, rock 2, old/good/super rod 5 each as `{min,max,u16 species}`, then 4 swarm u16 (total 196).
- Slot counts are unchanged: 12 land, 5 surf, 2 rock smash, 5 per rod, 4 swarm.
- SOURCE: hge reads each wild species word as `species = word & 0x7FF`, `form = (word & 0xF800) >> 11` (`asm/other_hook.s:206-263`). Vanilla data stores no form bits.
- FILE: both ROMs hold 6210 non-zero species words, max species id 455, **0 words with form bits set**, **0 above 493**. The widened decode is a no-op on this build's data.
- FILE cross-check: the 426 land time-of-day lists (142 banks x morn/day/nite) from the hge ROM equal `data/games/gen4_hgss/encounters.json` `versions.heartgold.banks.*.land` (0 mismatches). So the committed heartgold encounters match the hge build for land.
- SOURCE (`hg_engine.md` §5): the fork's own overlay-2 slot-roll hooks are misfiled and dead. That is a fork matter, not a data one.

**Decoded hge examples.** No decoded example differs from vanilla, because the NARC is byte-identical. Sanity: bank `R29` morning slot 0 is species 16 (Pidgey), in both ROMs and in `encounters.json`.

**Recommended hge generator source.** The ROM NARC `a/0/3/7`:
- Decode `species & 0x7FF` and `species >> 11` as the form.
- Name through hge msg 237 (see §5).
- Names are Title Case in hge ("Pidgey") and ALL CAPS in vanilla ("PIDGEY"); fold case before comparing.
- The fork's `data/Encounters.c` is a C initializer using `SPECIES_*` macros. It needs a preprocessor or a regex over `species.h`, so it is a worse source than the ROM.
- If the owner later edits `Encounters.c`, the ROM and `encounters.json` will diverge. The generator must then read the ROM NARC, never the pret JSON.

## 2. Trainers: IDENTICAL content, format superset

**Where the data lives (SOURCE).** pokeheartgold `trdata.narc` is `a/0/5/5` (738 x 20 B) and `trpoke.narc` is `a/0/5/6`. The fork builds both from `data/Trainers.c` through `tools/source/trainerdatagen/trainer_data_gen.c` (`narcs.mk:225-253`). Names are msg 729, classes msg 730.

**FILE: NARC bytes.**

| NARC | vanilla | hge | verdict |
|---|---|---|---|
| `a/0/5/5` trdata | `4a1b58ce53e5`, 738 x 20 B | `4a1b58ce53e5` | SAME |
| `a/0/5/6` trpoke | `4a7cb39119d6` | `5d6cf9766693` | 34 members differ, **padding only** (below) |
| `a/0/5/7` trainer text map | `2e831eeb3984` | `2e831eeb3984` | SAME |
| `a/1/3/1` trainer text offsets | `8354914c6a35` | `8354914c6a35` | SAME |

**The 34 `trpoke` differences are padding.**
- Vanilla pads every member to a multiple of 4 bytes. The hge writer does not (e.g. member 21: 56 vs 54 B; member 160: 20 vs 18 B).
- FILE: for all 34, vanilla length = round-up-4 of the hge length, and the vanilla tail is zeros.
- I parsed every party in both ROMs as {iv, ability byte, level, species, [item], [4 moves], capsule}. Result: **0 of 738 parties differ** in iv, ability, level, species, item, moves or capsule, and the party sizes match for all 738.
- FILE: trainer-type histogram is identical, {0: 487, 1: 177, 2: 7, 3: 67}.
- FILE: the highest species used by any trainer mon is 478 in both ROMs.

**Is the party format extended? CHANGED-FORMAT-SAME on this build.** SOURCE (`include/trainer_data.h:23-31`, `trainer_data_gen.c:178-309`): the hge writer supports a bitfield on the trainer-type byte.

| Bit | Meaning |
|---|---|
| 0x01 | moves |
| 0x02 | item |
| 0x04 | ability |
| 0x08 | ball |
| 0x10 | IV/EV set |
| 0x20 | nature |
| 0x40 | shiny lock |
| 0x80 | additional flags |

Per-mon layout is `{u8 ivs, u8 abilitySlot, u16 level, u16 species}`, then the optional fields in the order above. For the `0x80` flag, a u32 of extras follows (status, hp/atk/def/spd/spa/spd, pp counts, nickname). Every mon ends with a u16 `ballSeal`. With only bits 0x01/0x02 set, this is byte-identical to the vanilla record. FILE: this build's data sets only bits 0x01 and 0x02 (`Trainers.c` has 487 + 177 + 67 + 7 = 738 type lines, matching the ROM histogram). So no ROM party uses the extended bits.

Other layout notes (SOURCE):
- Trainer header +1 is a **u16** class in hge (`WriteLe16(&data[0x01])`); vanilla has u8 class plus u8 `unk_2`. The bytes match here because every class id is below 256.
- Vanilla's species field is 10-bit species plus 6-bit form (`pokeheartgold include/trainer_data.h`). hge writes the full u16 species. Both agree for ids at or below 493.

**Names (FILE).** Msg 729 decodes to the same 738 trainer names in both ROMs. Entry 0 is the dummy (`" -"` vs `"-"`). Entries 667-671 and 707-711 are plain text in vanilla and 9-bit-compressed `{TRNAME}` strings in hge, but decode to the same names (decoder: `MessagesDecoder::DecodeTrainerNameMessage`). Msg 730 (class names) is identical after decoding.

**Recommended hge generator source.** The ROM (`a/0/5/5`, `a/0/5/6`, msg 729/730), with a parser that follows the type-byte bitfield so a future hge edit that turns on abilities, balls or IV/EV does not silently misparse. `Trainers.c` is a faithful C source (738 entries) but needs a C parser.

## 3. Map headers / mapsec / area names: IDENTICAL

**Where the data lives (SOURCE).** `sMapHeaders` at **0x020F6BE0**, size 0x32A0 = 540 x 24 B, in the main ARM9 (`.cache/gen4/xmap/heartgoldus.xMAP:49070`). Each header carries `wildEncounterBank`, `areaDataBank`, `mapsec` (u8), `regionNo`, `mapType` (`pokeheartgold include/map_header.h`). Area names are msg 279 indexed by mapsec.

**FILE.**

| Item | vanilla | hge | verdict |
|---|---|---|---|
| `sMapHeaders` 12960 B | `4c0f77d192eb` | `4c0f77d192eb` | SAME, 0 of 540 headers changed |
| msg 279 (`a/0/2/7` member 279) | 235 strings | 235 strings | SAME, identical bytes |

Vanilla ARM9 is compressed and loads at 0x02000000 (1120352 B decompressed). hge's ARM9 is raw and expanded (2389960 B), but the table sits at the same RAM address. The fork has no `MapHeader` data source or hook (`hooks`, `armips/`, `data/`, `narcs.mk` grep: none), so headers come from the base ROM.

**Recommended hge generator source.** Reuse the committed `area_map.json` and `locations.json` unchanged. If a ROM-derived check is wanted: read 540 x 24 B at 0x020F6BE0 from the loaded ARM9 (decompress vanilla; take hge raw) and msg 279. The pret-derived G2 data is valid for hge as is.

## 4. Acquisition: IDENTICAL data, CHANGED engine code

**Script NARC `a/0/1/2` (SOURCE: built by `narcs.mk:661-672` from `armips/scr_seq/*`).**

| Item | vanilla | hge |
|---|---|---|
| NARC | `0b911f52fda9`, 965 members | `cf9a277a258d`, 965 members |
| members changed | | **1 of 965: member 3** (`scr_seq_0003`, common scripts), 5996 to 6081 B |

- The 61 vanilla sites live in 47 script members (`scr_seq_0005` ... `scr_seq_0947`, listed in `acquisition.json` `script_sites[].file`). **None is member 3**, so all 47 are byte-identical in hge. FILE.
- The fork's only scr_seq sources are `armips/scr_seq/scr_seq_00003_commonscript.s` and `scr_seq_00953_trainerscript.s`. Member 953 is unchanged (FILE: same bytes).
- SOURCE: the hge commonscript contains no `give_mon`, `give_egg`, `wild_battle`, `create_roamer`, `load_npc_trade`, `choose_starter` or `give_loan` command. Its diff is a larger header table (73 scripts) plus added common scripts (repels, autobattle testing).
- NPC trade records `a/1/1/2` (13 x 0x54 B, 13 records): `045caf08d8ce` in both, SAME. So the 10 exchanges, 2 loans and 1 dormant record carry over. SOURCE: `include/npc_trade.h` keeps the 0x54-byte `NPCTrade`.

**Replaced code (SOURCE; `hooks:192-198, 528-529`).** These change behaviour, not the sites:

| Replaced | hge behaviour |
|---|---|
| `GiveMon` helper 0x020541DC (`src/pokemon.c:1357`) | adds `forme`, `ability`, `ball`, `encounterType` args; sets form; reinits moves if form != 0 |
| `ScrCmd_GiveEgg` 0x0204D248 (`src/field/script_commands.c:28`) | decodes the species arg as `species & 0x7FF` and `form = (>>11)`; sets form; honours the hidden-ability script flag |
| `ScrCmd_GiveTogepiEgg` 0x022020CC (ov1) | replaced. **Not listed in `hg_engine.md` §4**; add it to the replaced table |
| `_CreateTradeMon` 0x02259C40 | replaced |
| `SetFixedWildEncounter`, `AddWildPartyPokemon` | replaced |
| `ScrCmd_GiveMon` 0x0204D088 | **kept** (FILE-verified earlier) |

Because the scripts are unchanged, species args in the 61 sites stay at or below 493, so the wider decode is a no-op on today's data.

**Recommended hge generator source.** Reuse `acquisition.json` `script_sites`, `npc_trade_records` and `runtime_branches` verbatim, with this extra check: `a/0/1/2` member N (N from the `scr_seq_NNNN` file name) must hash-equal vanilla for the 47 members. The `c_producers` section is a pokeheartgold src inventory and does **not** apply to hge. An hge producer inventory must be authored from the fork's `src/` (hg_engine.md §4 hook table; add `ScrCmd_GiveTogepiEgg`). An hge generator would only add per-build symbols for the replaced C producers, not new script sites. A fork edit to any script member beyond 3 and 953 would have to be re-scanned.

## 5. Species / move / item id spaces and name tables: CHANGED-FORMAT

**Where the names live (FILE).** Message NARC `a/0/2/7` (vanilla 829 members, `dda4290205ea`; hge 854 members, `07d3b7f1f21d`). 35 members differ, and members 829-853 are new. Decode: 4-byte header {u16 count, u16 seed}, per-entry key `seed*0x2FD*(i+1)`, per-string key `(i+1)*0x91BD3`, +0x493D, charmap from the fork's `charmap.txt`.

| Space | Msg member | vanilla | hge | Source of hge names (SOURCE) |
|---|---|---|---|---|
| Species | 237 | 496 strings | **1476** | generated from `data/Species.c` `.textData.name` by `speciesdatagen` (`narcs.mk:117-134`) |
| Moves | 750 | 468 | **923** | generated from `data/Moves.c` (`narcs.mk:62-83`) |
| Items | 222 | 537 | **2685** | plain text `data/text/222.txt`, one name per line, line N = item id N |
| Trainer classes | 730 | 129 | 129 | `data/text/730.txt`; identical after decode |
| Trainer names | 729 | 738 | 738 | generated from `Trainers.c` `.name`; 737 same |

**FILE: low ids are the same entities.**
- Species 1-493 names: all 493 match vanilla after case folding. hge is Title Case, vanilla is ALL CAPS.
- Moves 1-467: 4 spelling fixes only ("ViceGrip" to "Vise Grip", "Hi Jump Kick" to "High Jump Kick", "Faint Attack" to "Feint Attack", "SmellingSalt" to "Smelling Salts"). The raw change count is 21 because of punctuation/spacing normalization.
- Items 1-536: ids are unchanged, but 127 names differ after normalization. These are spelling fixes ("Parlyz Heal" to "Paralyze Heal") plus **vanilla `???` placeholder slots that hge fills with real items** (e.g. 113 Tea, 119 Chill Drive). A vanilla-era item id name map will mislabel those slots on hge.

**FILE + SOURCE: ids above vanilla are not national-dex numbers.**
- Species 494/495 stay Egg/Bad Egg. 496-543 are `-----` filler. **National dex #494 Victini is id 544** (`species.h:553`). The hge msg 237 confirms: `[544]=Victini`, `[545]=Snivy`, `[649]=Klink` (dex 599), `[1075]=Pecharunt` (dex 1025). The shift is **+50 for dex 494 and up**.
- Ids 1076-1475 are form entries with `-----` names in msg 237. Forms are an index above the canonical range or the 5-bit form field (0xF800 on encounter words); see `include/constants/species.h` (`MAX_SPECIES_INCLUDING_FORMS` 1476, `SPECIES_MISC_FORM_START` 1175).
- Moves above 467: **a 3-id gap** (canonical id + 3). `MOVE_HONE_CLAWS` is 471, `MOVE_ECHOED_VOICE` 500 and the last, `MOVE_MALIGNANT_CHAIN`, 922. Msg 750 index 468 is the placeholder string `MOVE_468`.
- Items above 536 are new ids (`ITEM_PRISM_SCALE` 537 ... `ITEM_CANARI_BREAD` 2684).

**Recommended hge generator source.**
- Names: read the hge ROM msg 237 / 750 / 222 (decoder above). This is the only source that includes generated names without compiling C.
- Constants and ids (`SPECIES_*`, `MOVE_*`, `ITEM_*`): the fork's `include/constants/{species,moves,item}.h`. A generator must **never assume national-dex ids above 493**.
- Admission: the hge profile must carry its own species, move and item tables rather than borrowing vanilla's, so ids above 493 resolve to names.

## Open (not measured)

- The fork's `data/Species.c` was not parsed to confirm that every species name in msg 237 matches its source.
- Soul Link needs `GiveMon` / `ScrCmd_GiveEgg` / `ScrCmd_GiveTogepiEgg` hook behaviour confirmed on the hge ROM in a runtime acquisition receipt. This card measured data only.
- SoulSilver is not supported by hge (`Makefile` IPKE only), so the SS side of `encounters.json` has no hge counterpart.
