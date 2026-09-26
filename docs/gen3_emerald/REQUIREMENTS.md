# Gen 3 Emerald + expansion release requirements

This is the release contract for Pokémon Emerald (BPEE, US/EU rev 0) on pack `gen3_emerald`, and for
the pokeemerald-expansion reference build on pack `gen3_exp`. It uses the same rules as
`docs/gen3_requirements.md`. A row is **done** only when it has both:

- a SOURCE proof: a pret/expansion citation, or data generated from a pinned `.sym/.map`;
- a PHYSICAL proof: the real cartridge in BizHawk, judged by an oracle that is not the code under
  test.

MODEL evidence is recorded but never closes a row on its own. The runner is
`python tools/verify_gen3_release.py`; a lane that did not run did not pass. Nothing in the
archived old client (`archive/gen3-old-client`) or in the stale `emerald` stub
(`data/games/gen3_frlg/profile.json:12-48`) counts as evidence. That stub is not a source;
The stub's addresses are correct but it is incomplete and unprovenanced: see `research/facts_2026-09-25.md` §A2.

Rows stay `·` until their phase in `PLAN.md` §3 lands a receipt.

## Pins

| What | Value |
|---|---|
| Emerald ROM | `Pokemon - Emerald Version (USA, Europe).gba` (project root), header `POKEMON EMER`/`BPEE`, version byte 0, 16 MiB, sha1 `f3ae088181bf583e55daf962a92bb46f4f1d07b7` (= pret `rom.sha1`), md5 `605b89b67018abcea91e693a4dd25be3` (coordinator hash 2026-09-25) — **SIGNED EG0 2026-09-25** |
| pret/pokeemerald source | master `5eff78649e7170a877b961ef0b3da13b81a16038` (2026-09-01); the `symbols` branch is `dba968c67d85caf9595abe12a51ff739d4dc5937` (2026-08-26): its published `pokeemerald.sym` IS the pinned symbol source (EG0 decision 2; no `.map`, the player-controller span is derived from the `.sym`) — **SIGNED EG0: `c65e93f2`** |
| agbcc | pret/agbcc `da598c1d918402c42c0c0d7128ba14567f3175e9` (the FRLG pin, `data/gen3_sources.lock.json`); reuse for pokeemerald is to be proven by the E1-SYM build sha1 |
| BizHawk | 2.11.1 + installed hashes as `docs/gen3_requirements.md` Pins (unchanged) |
| pokeemerald-expansion | tag `expansion/1.17.0` (published 2026-08-31T18:12:55Z); commit sha to record at XG0 |
| Expansion compiler | modern `arm-none-eabi-gcc` only (agbcc removed at 1.9). Choose at XG0: vendored xPack 15.2.1 (`patch/vendor/armgcc/xpack-arm-none-eabi-gcc-15.2.1-1.1`) or CI apt `gcc-arm-none-eabi`; double-build sha1 receipt |
| Wire contract | `docs/protocol.md` (unchanged) |

## Oracles

As in `docs/gen3_requirements.md` (ENGINE, PYDEC, GAME, SERVER, CONTROL), plus:

- **HEADER**: the ROM's own GF header (`0x08000100`, vanilla and expansion) and RHH header (expansion,
  magic `RHHEXP` after the GF header) are read independently of the pack. Their save offsets and
  sizes (flags, vars, SaveBlock1/2 size, party offsets) and table pointers must equal the generated
  profile.

## Status legend

`S` SOURCE, `M` MODEL, `P` PHYSICAL. `·` = not yet, `✓` = done with receipt path, `◐` = partial,
`†UNVERIFIED` = asserted but not pinned.

---

## F: Facts (E1 / X1)

| id | Requirement | SOURCE | Oracle | S | M | P |
|---|---|---|---|---|---|---|
| EF-1 | `pokeemerald.{sym,map}` built from the pinned commit; the build ROM sha1 == the owner's BPEE | `tools/build_pret_gba_syms.py --lock data/gen3_emerald_sources.lock.json` | CONTROL (sha1) | · | — | — |
| EF-2 | FRLG and RR generator outputs are byte-identical after every shared-tool edit (Gen 3 grant condition) | `--check` on each generator | CONTROL | · | · | — |
| EF-3 | Every `gen3_emerald` profile address names a `pokeemerald.sym` symbol; generated-vs-sym diff 0; generated profile agrees with every stub address (cross-check) | `tools/gen_gen3_profile.py` Emerald row | HEADER | · | · | — |
| EF-4 | Each engine site's `expected_hex` is at its `rom_offset` in BPEE (21 kinds; `CopyMonToPC` rename; re-derived `battle_begin`/`faint`/`capture_wild`/`whiteout`/`map_load`/evolution) | `tools/pin_gen3_site.py` + `gen_gen3_engine_signals.py` | ENGINE (at E2) | · | · | · |
| EF-5 | Writer inventory + `allowed_overworld_tasks` (FR set minus `Task_RunPokemonLeagueLightingEffect`) + Emerald forbidden-task census (contests, secret bases, record mixing, blender/crush, Frontier/Pyramid/Trainer Hill, multi-partner battle, Union Room battle) | `tools/gen_gen3_write_checkpoint.py` | frame-end census | · | · | · |
| EF-6 | Save layout: SB2 0xF2C, SB1 0x3D88, party SB1+0x234/+0x238, 14 sections/slot chunk table, sectors 30/31 Trainer Hill/Recorded Battle | `server/adapters/gen3_codec.py` Emerald constants | HEADER + CONTROL | · | · | — |
| EF-7 | Area map: every `wild_encounters.json` map keyed `mapGroup:mapNum`, merged per the §0 defaults; Hoenn names; never a Kanto name on BPEE | `tools/gen_area_map.py` Emerald mode | CONTROL | · | · | · |
| EF-8 | Statics/gifts/daycare: starters, Castform per form, Beldum, Lavaridge Wynaut egg vs Route 117 daycare, fossils, legendaries, scripted Voltorb/Electrode/Kecleon/Unown | `data/games/gen3_emerald/statics.json` from pret scripts/flags | SERVER | · | · | · |
| EF-9 | Items: common 0–374 table (Gen 3 `5f050857`) + Emerald overlay {375 Magma Emblem, 376 Old Sea Map}; move stats FR == E (two-source assertion) | generator + tests | CONTROL | · | · | — |
| EF-10 | Fixtures `emerald_{town,battle,trainer}{,_b}.sav` pass `--qualify` and `--boot-check` | `tools/gen3_fixtures.py` | GAME + PYDEC | — | ✓ | ✓ |
| XF-1 | Reference build reproducible (two builds, same sha1); `.elf/.map/.sym` kept, ROM never published | `tools/build_expansion.py` | CONTROL | · | — | — |
| XF-2 | Struct offsets (BattlePokemon, SaveBlock1/2, SpeciesInfo, MoveInfo, ItemInfo) from the offsetof probe; consistent with `.map` sizes | `tools/gen_expansion_facts.py` | CONTROL | · | · | — |
| XF-3 | Per-build data pack: species count == RHH `numSpecies`; names/types/abilities/natDex/evolution families; moves; items. The extractor run on vanilla Emerald reproduces pret | `tools/extract_expansion_data.py` | HEADER + CONTROL | · | · | — |

## R: Reads

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| ER-1 | Party/box decode on BPEE == PYDEC (vanilla crypto path, no code change) | PYDEC | ✓ | ✓ | ✓ |
| ER-2 | SaveBlock pointer deref + map location (`SB1+4/+5`) on BPEE | PYDEC + GAME | ✓ | ✓ | ✓ |
| ER-3 | Bag/badges/battle/trainer reads correct on BPEE | PYDEC | ✓ | ✓ | ◐ |
| XR-1 | Profile-driven masks (species 11, item 10, move 11 bits) and 12-char nicknames (Substruct0 extra bytes); FR/LG/RR/E suites unchanged | PYDEC + CONTROL | · | · | · |

## S: Signals

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| ES-1 | Probe matrix rows a–g on BPEE (exec at `CallCallbacks`, write hooks, host-write silence, unregister, negative control, flash domain) | ENGINE | ✓ | ✓ | ✓ |
| ES-2 | One positive + one negative receipt per exercised site kind (observer, scripted play) | ENGINE | ✓ | ✓ | ◐ |

## W: Writes / checkpoint

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| EW-1 | Checkpoint true in Littleroot/Oldale overworld; false with an empty write log in every reachable forbidden state; unreachable states recorded as SOURCE-only limits | ENGINE + CONTROL | ✓ | ✓ | ◐ |
| EW-2 | P+H active in-battle faint on Emerald singles (re-pinned list in `PLAN.md` §3 E4); doubles/Steven multi hold | GAME | ✓ | ✓ | ◐ |
| EW-3 | Writes inside Emerald Pokémon Centers (Union Room tasks allowed, as FRLG ruling) | GAME | · | · | · |

### E2 evidence (2026-09-26, `claude/gen3-emerald`; see `docs/gen3_emerald/EG2_request.md`)

`◐` = PHYSICAL in part, with the uncovered part named here.

- **EF-10:** the fixtures now also include the SYNTH kinds pc, lowhp, badges, catch, evolve,
  poison and gift. Every one was built by `make-emerald` on the lane (boot-check PASS) and
  sha-pinned in `tests/fixtures/gen3/README.md`.
- **ER-1, ER-2:** `probes/reads_pydec_emerald_2026-09-26.txt` shows two states: 0 party/box
  differences, planted-offender control 2, location, and balls.
- **ER-3:** badges at 0 and at 4 (`probes/reads_pydec_emerald_badges_2026-09-26.txt`, straddle
  0x10C/0x10D) and balls are PHYSICAL. Badges 5-8, battle reads and trainer reads are
  SOURCE/MODEL only.
- **ES-1:** `probes/hooks_emerald_2026-09-26.txt`, tracked-clean at `c891455d`. Rows a-return, b-interior and f are OPEN, as on FR.
- **ES-2:** there are eight observer receipts (`probes/shadow_emerald_*_2026-09-26.*`) and the
  negatives manifest (`negatives_manifest.json`, 75/75, the complete matrix). 11 of the 12 coverage kinds are
  PHYSICAL; `trade_done` needs a link partner (E5).
- **EW-1 ◐:** `probes/checkpoint_emerald_battle_2026-09-26.txt` (21/21, tracked-clean) covers
  every probed row. NOT run on Emerald: `pc_menu` (the PC write window), `battle_faint_prompt`,
  `battle_link` and the companion/RR rows. The probe constructs no writer, so an empty write
  log is not evidence here. The Emerald-only forbidden states are SOURCE-only
  (`write_checkpoint.md` §8).


## C: Client / server / pairing

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| EC-1 | Foundation `gen3_emerald`; FR↔E and RR↔E refused before adapter reselection, `links.json` bytes unchanged | SERVER | ✓ | ✓ | — |
| EC-2 | `Gen3Adapter` keeps `rom_type`; title data (statics, items overlay, sprites `generation-iii/emerald`, label "Emerald", title-aware area catalog) | SERVER | ✓ | ✓ | ◐ |
| EC-3 | By-name refusal (`lua/slink.lua`) and `UNADMITTED_GAMES` flip only with EG4 (ruling 24) | CONTROL | · | · | · |
| EC-4 | Conformance World rows + capabilities fixture regenerated | MODEL | ✓ | ✓ | — |

### E4 / E4b evidence (2026-09-26; receipts `docs/gen3_emerald/probes/duo_e4_*`)

- **ED-1 ◐:** six of seven scenarios PASS E↔E at cut `cd93382b` with save witness + oracle +
  PYDEC: faint_cmd, reconnect, deadzone, link (RNG retry 2/3), boxsync, linked_faint_active (twice:
  once with an A-side whiteout to Oldale 0.10 (6,17)). whiteout_gen3 is not yet an Emerald row:
  Emerald respawns outdoors (pokeemerald `src/overworld.c:357-366`), so FR's Center receipt has
  nothing to check; card E4c designs the Emerald receipt. Pre-EG4 the duo driver admits Emerald
  through a TEST-ONLY seam logged in every receipt (production refusals unchanged).
- **EW-2 ◐:** P+H PHYSICAL on Emerald singles (`duo_e4_linked_faint_active_cd93382b_PASS_*`: five
  `battle_commit` writes on one frame, HANDOFF, `ACTIVE_KO battle_hp=0 inputs=0 hp_writes=0`,
  ENGINE_FAINT_SITE). Doubles / Steven multi hold: not exercised.
- **ED-2 ◐:** wrong-save refusal PASS inside reconnect_gen3 (C-1). Zip boot and the Emerald
  final-cut summary wait for EG4 (the final-cut plan `tools/gen3_final_cut.py --title emerald`
  exists; its zip_boot_emerald reports BLOCKED-EG4 until the cut carries the admission flip).
- Regression at `cd93382b`: FR faint_cmd and RR deadzone PASS.

### E3 evidence (2026-09-26; see `docs/gen3_emerald/EG3_request.md`)

- **EC-1:** `test_mixed_foundations.py` covers the FR/RR↔E refusal in 4 arrival orders, with the `links.json` bytes unchanged, and E↔E admission.
- **EC-2 ◐:** the title data plus restart/rollback are in `test_gen3_emerald_server.py`. PHYSICAL only on FR/LG/RR (regression duos); the Emerald client runs only in tests until EG4.
- **EC-4:** `test_protocol_conformance.py::test_world_rows_on_emerald` (test-only admitted pack copy) and `test_mockup_fixtures.py`.
| XC-1 | `gen3_expansion.py` adapter contract (full `base.py` surface; empty trainer/encounter = recorded limit); `pokemon_data.py` untouched | SERVER | · | · | · |

## D: Duos (E4 / X3)

| id | Requirement | Oracle | S | M | P |
|---|---|---|---|---|---|
| ED-1 | faint_cmd, linked_faint_active, boxsync, whiteout, link, deadzone, reconnect on E↔E with witness + oracle | GAME + SERVER | — | ✓ | ◐ |
| ED-2 | Wrong-save refusal; zip boot `emerald`; `fc_SUMMARY_<cut>_emerald.txt` all PASS | GAME | — | ✓ | ◐ |
| ED-3 | Vanilla trade duo FR↔FR and E↔E (E5, shared Gen 3) | GAME | · | · | · |
| XD-1 | Seven duos on the expansion reference build | GAME + SERVER | — | · | · |

## Not in this release

Battle Frontier / Battle Pyramid / Trainer Hill / Contests / Secret Bases rule support (writes are
refused there; negative controls only). Expansion battle calc. Binary-only expansion hacks.
Emerald companion/native patch. Non-US Emerald (BPEF/D/S/I/J). Peer ghost on Emerald.
Archipelago Emerald. Rival Team Swap on Emerald (RR-companion only).

## Recorded limits

Carried from the shipped Gen 3 contract (`docs/gen3_requirements.md`), plus: expansion reference build
serves no trainer/encounter-table panels (adapter returns empty).

## Receipts

(none yet)
