# Randomized Gen 3 (UPR ZX FR/LG): design and card plan

2026-09-26, owner ruling 29: UPR-randomized FR/LG ships in the RC, and Emerald binds this same
design later. This is a read-only design card. Citations are to this worktree
(`claude/gen3-migration-planning-5d8e45`) unless they are marked `emerald:` (branch
`claude/gen3-emerald`) or `upr:` (the SLink fork source, `.cache/slink-upr/src/com/dabomstew/pkrandom/`,
version `4.6.1-slink3`, `upr:Version.java:32`). **Every "land" step below means: commit on the
branch. Master only on owner approval.**

## 0. Answer first

**A UPR-randomized FR/LG is admitted today, silently, as `clean`.** This was measured, not
inferred. The fork jar randomized FR and LG with two settings files, one allowlisted and one
"widest" (types, evolutions, movesets, base stats and abilities all random, plus all 13 misc
tweaks SLink models). The real `lua/gen3/entry.lua` `Entry.admit` then ran under lupa over each
output (scratch `admit_rand.py`). All 4 outputs returned `(gen3_frlg, firered|leafgreen, clean,
anchors)`, with 18-31 K bytes changed, 690-730 of them below 0x1E0000 (code).
- **The 21 engine sites and the 5 write-checkpoint anchors are untouched.** Every UPR code
  write for FR/LG was checked against them: the 8 FR/LG IPS patches (instant text, roamers,
  Marowak, musicfix), 12 locator patches (obedience at 0x1D3EC, Kanto-dex evo checks at
  0xCE91A/0x126C4A, nat-dex scripts, running shoes at 0x5BA42, perfect odds at 0x2D6BC,
  friendship at 0x43002) and the fixed-offset writes (RunIndoors 0xBD494, catching tutorial
  0x7F88C, intro 0x12FB38/0x130F4C/0x130FA0, starters 0x169BB5, PC potion 0x402220, type
  chart 0x24F050). None overlaps a site (0x51A..0xDA3AC,
  `data/games/gen3_frlg/engine_signals.json`) or an anchor
  (`data/games/gen3_frlg/write_checkpoint.json`). The sources are `upr:config/gen3_offsets.ini`
  `[Fire Red (U) 1.0]` and `upr:romhandlers/Gen3RomHandler.java:2922-3056,4141-4300,4378-4392`.
- **So write safety holds, but rules and information do not.** The anchor pass
  (`lua/gen3/entry.lua:148-160`) is exactly as blind as it was designed to be (it only checks
  engine sites). Admission returns the artifact's own kind (`entry.lua:196-201`), so the client
  says `artifact_kind = "clean"` (`lua/gen3/client.lua:947`), and the server enforces vanilla
  pret evolutions and types (`server/adapters/gen3_frlge.py:362-369`) against a cartridge that
  may have randomized both. It also shows retail trainer parties in the ruling-28 panel and calc
  Prep (`gen3_frlge.py:509-519` says so in its own `ponytail:` note). The existing unit test pins
  this behaviour: `tests/unit/test_gen3_entry.py:173-179` asserts kind `clean`.
- **Decision: randomized needs its own `rand` kind** (Gen 1 precedent below). The first
  falsifier of the whole effort is that same scratch run expecting `rand`.

**Key design decision: mirror Gen 1's rule-table policy exactly.** Types, evolutions,
movesets, base stats and abilities stay forbidden, so `evo_family`/`species_types`
(species/dupes/type clause) keep reading the vanilla pret tables. `adapter_for` already rests on
this: `server/server.py:913-918` says rule semantics "retain the run adapter" because
"supported randomizer settings share those semantics". Only DISPLAY and PANEL data is read per
ROM: wild encounters and trainer parties. The client ships raw table bytes, as Gen 1 does, and
the server decodes them with `server/adapters/gen3_rom_tables.py` (Codex is building it). The
server also decodes evolutions and species info to REFUSE a cartridge whose rule tables
differ from vanilla. That turns the policy into a check, even for a ROM built outside the Manager.

## 1. The accepted framework (Gen 1 / pureRGB), to mirror

**Admission.** Gen 1 hashes the whole ROM and admits a pinned sha1. An unknown hash can still
be admitted by anchors plus the header, and then the kind becomes `rand` (or `rand_overlay` for
the pure overlay): `lua/gen1/entry.lua:245-266`, with `kind()` at `:262-265` and
`allow_unknown_hash=true` at `:247`. The wire already knows the kinds
(`server/server.py:486`). The pairing check refuses mixed kinds (`server.py:779-787`), and
`GameRulesAdapter.pairing_kind` maps only `named` to `clean` (`server/adapters/base.py:314-328`),
so `rand` never pairs with `clean`. The duo scenario is `admit_randomized_new`
(`tools/e2e_duo.py:274,2896,6053`).

**The randomizer.** SLink's fork of UPR ZX 4.6.1 is a patch series (`patch/upr/0001-0010`)
built by `tools/build_upr_fork.py`. Only SHA-256-pinned jars run (`data/upr_jars.json`,
`server/upr_pipeline.py:132-190`). The pipeline works like this:
- `prepare_pair` (`upr_pipeline.py:601-681`) gives both players the same `.rnqs` and admits it
  first (`admit_settings` `:572-598`: version, `forbidden_enabled`, then an allowlist envelope,
  `server/upr_settings.py:694-826`).
- It runs the CLI per player (`:421-470`) and reads the seed and the effective settings back
  from the log (docstring `:7-20`).
- It requires different seeds, the same effective spec, different bytes and the same UPR
  version (`:646-679`).
- `_check_content` (`:499-549`) refuses changed base stats and types, and changed evolutions
  (compared as a graph, because UPR repoints them). The pure family also gets the T6
  write-domain audit (`:552-569`).
- The Manager picks the family from the game (`server/manager.py:84` `GAME_FAMILY`,
  `:1447-1474`). `server/cartridges.py:55-160` provisions the pair and writes
  `rom_contract.json` (`:146`), which holds each player's fingerprint and rom_sha1.
- `.rnqs` import and export: `manager.py:1528-1600`. Presets: `upr_settings.OPTIONS` and
  `default_spec`.

**Per-ROM facts.** Three adapter hooks exist:
`rom_content_fingerprint` and `ingest_rom_content` in `server/adapters/base.py:426-456` (both
MUST raise on malformed input), and `use_rom_encounters`. Gen 1 implements them at
`server/adapters/gen1_rby.py:544-559` (and pure at `gen1_purergb.py:359-370`) through
`gen1_rom_scan.parse_client_content`/`build_encounter_tables`/`content_fingerprint`.
`encounter_table` prefers `_rom_encounters` (`gen1_rby.py:528`).

On the server:
- `_decide_admission` (`server.py:790-836`) compares the hello fingerprint and then the sha1
  with the contract. A `None` fingerprint admits (`:819`), and no contract admits too.
- `_ingest_rom_content` (`server.py:645-690`) adopts tables into a **per-player** adapter,
  using three states: absent, `{}`=unreadable, or populated. It never falls back to the retail
  tables.

**The client** builds `rom_content` from its own ROM (`lua/gen1/rom.lua:121-160`: walk the wild
pointer table, hex-encode each record) and sends it in every hello (`lua/gen1/client.lua:1850-1872`).

**Families and trainers on a randomized Gen 1 cartridge.** `evo_family` stays vanilla, because
randomized evolutions are refused at build time (`upr_pipeline.py:535-548`, and
`forbidden_enabled` adds changeImpossible/easier evolutions, `upr_settings.py:723-758`). Gen 1
has no trainer-party panel (only `trainer_info` names, `gen1_rby.py:418`), so nothing about
trainers is read per ROM. Gen 3 is new ground there (ruling 28).

**Gen 2 refuses randomized.** `data/games/gen2_*/admission.json:14-19` has
`unknown_hash_policy: REFUSE` and `refused_kinds: [archipelago, randomized, unknown]`
(emitted by `tools/gen_gen2_admission.py:231`). Owner ruling O-25 is recorded at
`docs/gen1_gen2_runtime_checks.md:196-201`: a matrix entry that silently skips reads looks
exactly like one that passes, so refusal is stated. Gen 2 admits by exact whole-ROM sha1
(`lua/gen2/entry.lua:286`), and its hooks raise "not qualified" (`server/adapters/gen2_gsc.py:576-580`).

## 2. Gen 3 today

`Entry.admit` (`lua/gen3/entry.lua:188-217`) tries the hash, then anchors, then the header. On
this branch, `lua/slink.lua:139-160` routes anything admitted by something other than the header.
On `emerald:` that policy is ONE function, `Entry.admit_routed`
(`emerald:lua/gen3/entry.lua:243-254`; header-only refused, unrouted pack refused), and both
`slink.lua` and `run.lua` call it (test `emerald:tests/unit/test_gen3_run_lua_admission.py`).
A randomized FR arrives with `admitted_by = "anchors"`, so it is routed. `run.lua:205-206`
passes `kind` and `rom_sha1 = admitted.rom_hash` into the client, and the hello carries
`artifact_kind`/`rom_sha1` but no `rom_content` (`client.lua:947-950`). The Gen 3 adapter has
no ROM hooks (the base returns `None`), so any contract would admit it (`server.py:819`).

## 3. Per-ROM data: what UPR changes and where each piece is consumed

Addresses are from pret `data/gen3/pret/pokefirered.sym` (FR 1.0; LG from its own sym). UPR
offsets are from `upr:config/gen3_offsets.ini`. "In place" means UPR rewrites at the vanilla
address, so the table base stays at its pret address and only what it points to can move.

| Data | pret symbol (FR ROM off, size) | UPR writes | Consumer in SLink | Policy |
|---|---|---|---|---|
| Wild encounters | `gWildMonHeaders` 0x3C9CB8, 0xA64; 20-byte `struct WildPokemonHeader` (group, num, 4 info ptrs; pret `include/wild_encounter.h:26-34`) | In place (the handler locates it by pointer prefix, `Gen3RomHandler.java:464`); the slot arrays are pointed to | Encounter panel/banner. Today FR/LG has NONE: `encounter_table` is RR-only (`gen3_frlge.py:473-480`). Dupes uses the live battle species plus `evo_family` (`server/state.py:2552-2575`), not tables | **Ingest** (R2) |
| Trainer parties | `gTrainers` 0x23EAC8, 0x7418 (743x40, `TrainerData`/`TrainerEntrySize=40`) | Entries in place; **parties repointed** into free space from 0x800000 when they grow (`Gen3RomHandler.java:1959-1987`) | Ruling-28 panel `trainers_for_area`/`trainer_brief` (`server.py:957-975`, per-player `adapter_for`), calc label (`server.py:235-246,3086`), and the `_frlg_trainer_table` seam (`gen3_frlge.py:509-519`) | **Ingest** (R2) |
| Starters | Oak's lab script at 0x169BB5 (`StarterPokemon`, +5/+461/+515, `Gen3Constants.java:94-95`), plus the rival's teams through trainer data. `sStarterSpecies` 0x3F5D2C (pret `field_specials.c:1519`) is NOT written | In place | None. The client reads the party | Nothing to read |
| Evolutions | `gEvolutionTable` 0x259754, 0x4060 (412x5x8) | In place; the Kanto-dex evo code is patched (0xCE91A/0x126C4A) | `evo_family` (species/dupes clause), `gen3_frlge.py:362` | **Forbidden**; decoded only to verify it matches vanilla |
| Types / abilities / base stats | `gSpeciesInfo` 0x254784, 0x2D10 (28-byte rows) | In place | `species_types` (type clause) `:368`, `ability_name` `:501`, `calc_stats` `:682` | **Forbidden**; verified to match vanilla |
| Level-up movesets | `gLevelUpLearnsets` 0x25D7B4 (pointer table) | **Repointed** (`Gen3RomHandler.java:2149-2190`) | None server-side | Forbidden (Gen 1 parity) |
| TMs / compat / tutors | TmMoves 0x45A5A4, `sTMHMLearnsets` 0x252BC8, `sTutorLearnsets` 0x459B7E | In place | None | TMs/compat allowed (as Gen 1); tutors = Q2 |
| Field items / shops / pickup | Scripts, ShopItemOffsets, pickup locator | In place | None | Field items allowed; shops/pickup = Q2 |
| Type chart | `gTypeEffectiveness` 0x24F050 | `UPDATE_TYPE_EFFECTIVENESS` tweak | Calc (FRLG.js is the Gen 3 chart) | Forbidden tweak |

**Where to read it.** The Gen 1 precedent decides: the client reads its own cartridge and ships
raw bytes, and the server decodes them. This is the only path that works on a reconnect, that
the contract fingerprint can verify, and that covers a ROM the Manager never saw. A
server-side parse of the Manager's output file would cover Manager-built runs only.
Approximate size of the payload: wild ~10 KB, gTrainers plus parties ~45 KB, gEvolutionTable
16.5 KB and gSpeciesInfo 11.5 KB, so ~85 KB raw and ~170 KB hex. It is built **once at boot and
cached**. It lives in a new module, because the gen3 client is at the Lua 200-local limit.

## 4. Manager / UX

- **Family.** Add `gen3: gen3_frlg` to `GAME_FAMILY` (`manager.py:84`) and
  `FAMILY_FRLG = "gen3_frlg"` to `upr_settings.FAMILIES` (`:462-464`). A run names one family,
  and an FR/LG pair is refused on a Gen 1 run and vice versa (`manager.py:1447-1460`).
- **Paired seeds.** These are unchanged from Gen 1, for every family:
  - one `.rnqs`, two CLI runs, seeds read back and required to differ;
  - the same effective spec, different output bytes, the same UPR version (`upr_pipeline.py:646-679`);
  - an FR+LG pair is allowed, as Red+Blue is (`:604-606`).
- **Gen 1-only code the pipeline must branch on.**
  - `describe_rom`: the size gate `GEN1_ROM_SIZE` and `identify` (`:337-370`).
  - `family_of` (`:259-276`).
  - The output name `{player}_randomized.gbc` (`:623`). Use `.gba`, since the handler picks
    the extension.
  - `_check_content`, `fingerprint_rom` and `profile_hash` are all `gen1_rom_scan`.
  - The Gen 3 branch:
    - identifies the source by the clean sha1 pins in `engine_signals.json`;
    - verifies the rule tables are unchanged, via `gen3_rom_tables`;
    - **asserts every engine site and checkpoint anchor on the OUTPUT** (the Gen 3 analogue of
      T6, and exactly the property measured in §0);
    - fingerprints with the same function the server uses.
- **Presets.** Use `default_spec` for the family (wild, starters and trainers random). The
  allowlist envelope keeps every Gen 3-only option at "unchanged"; which of those the owner
  opens is Q2.

## 5. Risks

1. **Engine sites and checkpoint after UPR:** measured intact (§0). New UPR code writes would
   come from a new tweak or a fork patch, so R3's output-anchor assertion re-proves it on every
   build.
2. **Hash digest:** a contract compares the hello `rom_sha1` with the contract's
   (`server.py:827-833`). The comment at `entry.lua:116-118` notes that BizHawk's
   `getromhash` is not the same digest on every core. R1 must prove that the GBA core reports
   the file's sha1 (otherwise every randomized hello is rejected as "wrong ROM").
3. **pret tables in `gen3_frlge.py`:** species names are safe. The `LOWER_CASE_POKEMON_NAMES`
   tweak re-cases ROM names only, and the server keeps its own. Evolutions and types are
   correct only because they are forbidden. The ROM-side verification in R2 is what makes a
   GUI-made ROM with random evolutions a named refusal instead of a silent mis-rule.
4. **Calc:** the FRLG.js setdex is vanilla. For `rand`, `trainer_brief` must omit `calc_label`,
   so `_calc_trainer_label` returns "" and the bridge falls back to species plus level
   (`server.py:235-246`). The per-ROM party still feeds the Prep panel (Q6).
5. **Per-player content:** A and B hold different seeds, so every trainer or encounter read must
   go through `adapter_for(pid)`. The panel already does (`server.py:957-965`). The trainer
   table must ride the existing adopt path. `ingest_rom_content` returns the area tables as a
   dict carrying a `.trainers` attribute, and `use_rom_encounters` adopts both, so there is
   no `server.py` change (`ponytail:` a `use_rom_content` hook if a third table ever arrives).
6. **Shared-file blast radius:** `server/**/*.py` and `lua/*.lua` stale the Gen 2 digest (~2 h
   re-sweep). R1, R2 and R3's server edits land as ONE batch, and Gen 2 is pinged first.
   `lua/gen3/**` does not stale Gen 2.
7. **Limits on this pass's re-proof (owner review, 2026-09-26), queued rather than blocking R3:**
   - (a) The FR/LG output re-proof covers the 21 engine sites + their context windows and the
     5 write-checkpoint anchors, not a full write-domain audit like pureRGB's T6
     (`_audit_write_domain`). The FASTEST_TEXT tweak (default on) is an unchecked CODE write;
     a full write-domain audit for FR/LG is queued.
   - (b) The rule-table checks (`_gen3_species_rules`, `gen3_rom_tables.decode_rom_tables`)
     read the .sym table HEADS, not live pointers. This is safe only for as long as UPR
     never repoints `gSpeciesInfo` / `gEvolutionTable`'s heads -- which is exactly what the
     evolution and base-stat bans imply, but is not itself checked. Pointer-aware checks
     (following the actual runtime pointer rather than the linked address) are queued.
   - (c) Opening an in-game trade means a `key_change` (`state.py _handle_key_change`) can
     move a link onto a UPR-chosen species with no species-clause re-check at that moment --
     the clause is enforced when the pair is built, not on every later mutation. A rules
     card for this is queued.
   - (d) Admission needs the GBA hello's `rom_sha1` to equal the FILE's sha1
     (`gameinfo.getromhash` on the mGBA/GBA core) the way risk 2 above already flags for the
     hash digest generally; this is unproven for the GBA core specifically and needs a live
     check before R3 ships to players.

## 6. Cards

Every card: commit on the branch; master only on owner approval.

**R1: admission kind `rand`.**
- *Change request to Emerald T3* (entry.lua is leased to them): in `Entry.admit`, the anchors
  branch returns `kind = "rand"` when the matched artifact is `clean` on a pack with
  `randomizable = true` (`gen3_frlg` now, `gen3_emerald` at E-bind). Add
  `Entry.BASE_KIND.rand = "clean"`, so build reads the clean sites (`emerald:entry.lua:414-415`).
  RR's anchors behaviour and `admit_routed` stay unchanged. The test flip is
  `test_gen3_entry.py:173-179` → `rand`, plus RR anchors → unchanged.
- *This lane:* `server/adapters/gen3_frlge.py`:
  - `set_artifact_kind` stores the kind;
  - `rand` gates calc_label omission;
  - `pairing_kind` leaves `rand` distinct;
  - new `tests/unit/test_gen3_rand_kind.py`.
- `lua/slink.lua`: no residue after the Emerald merge (anchors routes through `admit_routed`).
- *First falsifier:* the scratch fork run (4 outputs) through `Entry.admit` expects `rand`.
  Today it is `clean`, i.e. red.
- *Exit:*
  - the 4 outputs report `rand`;
  - the clean pins stay `hash/clean`;
  - a `rand` hello next to a `clean` one is refused as mixed kinds;
  - the GBA hello `rom_sha1` equals the file sha1 (risk 2).

**R2: per-ROM ingest.**
- *Files:*
  - new `lua/gen3/rom_content.lua` (walk gWildMonHeaders, gTrainers plus party pointers,
    gEvolutionTable and gSpeciesInfo; hex blobs; bases from the pack profile);
  - a hello hook in `lua/gen3/client.lua` (only when `kind == "rand"`, cached);
  - profile syms in `data/games/gen3_frlg/profile.json` via `tools/gen_gen3_profile.py`
    (lease check with Emerald);
  - `server/adapters/gen3_frlge.py`: `ingest_rom_content`, `rom_content_fingerprint`,
    `use_rom_encounters`, and `_frlg_trainer_table` returning the adopted table;
  - it consumes Codex's `server/adapters/gen3_rom_tables.py`;
  - new `tests/unit/test_gen3_rom_content.py`.
- The server REFUSES (raises) when the decoded evolutions or types/abilities/base stats differ
  from pret.
- *First falsifier:* decode `FireRed_allowed.gba`. At least one trainer party differs from
  `frlg_trainers.json`, and the per-ROM `trainer_brief` must show the ROM's species. Also,
  `FireRed_widest.gba` must be refused by name.
- *Exit:*
  - the Lua payload and a Python read of the same file give identical decodes (lupa harness);
  - a malformed payload gives `{}` and "unavailable", never retail data.

**R3: Manager randomizer.**
- *Files:*
  - `server/upr_settings.py` (FAMILY_FRLG, the allowed FR/LG tweaks);
  - `server/upr_pipeline.py` (the Gen 3 branch of describe/family/check/fingerprint, `.gba`,
    and the output site/anchor assertion);
  - `server/cartridges.py` (the Gen 3 provision path, no companion);
  - `server/manager.py` (GAME_FAMILY);
  - the family chip and cartridge picker in `server/static`/`templates`;
  - tests `tests/unit/test_upr_pipeline_gen3.py`.
- *First falsifier:* `prepare_pair` on clean FR+LG with a widest `.rnqs` is refused by name,
  and with the default spec it yields a contract whose fingerprints equal R2's
  server fingerprint of the same files.
- *Exit:*
  - one Manager-made FR/LG pair;
  - `rom_contract.json` is complete;
  - an import/export `.rnqs` round-trips.

**R4: duos.**
- *Files:*
  - `tools/e2e_duo.py` gen3 rows (`admit_randomized_frlg`, plus link/faint/trainer-panel on
    the pair);
  - new `lua/tests/duo/scenario_gen3_rand_*.lua`.
- *First falsifier:* a player loading the OTHER player's randomized ROM is rejected ("not the
  cartridge built for player").
- *Exit (x2, as the RR duos):*
  - randomized FR↔LG link, faint and trainer panel are green;
  - the panel shows each player's own ROM party;
  - the calc falls back to species plus level.

## 7. Owner questions: ANSWERED 2026-09-26 as ruling 31 (`docs/gen3/G4_request_draft.md` §6)

All seven defaults are accepted, **except Q2: the Gen 3-only options (wild/trainer held items, move tutors, in-game trades, shops, pickup) are OPEN**. Each consumer of those tables must read them from the cartridge, never from pret. That means the in-game trade species wherever the server tracks NPC trades or gifts, the trainer held items in trainer_brief, and the wild held items only if displayed. The original questions follow:

- **Q1.** Keep Gen 1's forbidden set for Gen 3 (types, evolutions, movesets, base stats,
  **abilities**, `UPDATE_TYPE_EFFECTIVENESS`)? The alternative is per-ROM rule tables, which
  changes the `adapter_for` contract (`server.py:913-918`) and the calc.
- **Q2.** The Gen 3-only UPR options are wild held items, trainer held items, move tutors,
  in-game trades, shops and pickup. Should any be opened? The default is unchanged: they are
  outside the envelope and refused.
- **Q3.** Which FR/LG misc tweaks should be allowed? All of these were verified off-site:
  - fastest text, running shoes indoors, run without shoes, national dex at start;
  - PC potion, catching tutorial, ban lucky egg, lower-case names, balance static levels.
- **Q4.** For a randomized ROM made outside the Manager (UPR GUI, no contract): admit it as
  `rand` with the ROM-read tables and the rule-table verification (Gen 1 admits it: no contract
  ⇒ admitted), or require a Manager contract for Gen 3?
- **Q5.** Allow a randomized FR↔LG pair (as Red↔Blue)? Proposed default: yes.
- **Q6.** Is calc Prep for a randomized trainer acceptable as the per-ROM party plus the
  species/level bridge fallback, with no setdex sets?
- **Q7.** Should Emerald bind the same R1-R4 once its lane is free?
