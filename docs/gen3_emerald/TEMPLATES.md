# Gen 3 Emerald / expansion templates

Copy these when you execute `PLAN.md`. Each template follows a shape the Gen 3 lane already shipped;
the source is named in each heading. Fill the `<…>` slots; do not add sections.

## T1 Pack skeleton (source: `data/games/gen3_frlg/*`, `lua/gen3/entry.lua:61-93`)

Files per pack (`data/games/gen3_emerald/`; the expansion pack goes in `data/games/gen3_exp/<build>/`):

```
profile.json            generated: tools/gen_gen3_profile.py
engine_signals.json     generated: tools/pin_gen3_site.py + tools/gen_gen3_engine_signals.py
write_checkpoint.json   generated: tools/gen_gen3_write_checkpoint.py
area_map.json           generated: tools/gen_area_map.py (Emerald mode)
gen3_emerald_areas.lua, gen3_emerald_locations.lua   generated with area_map.json
statics.json            generated from pret scripts/flags (EF-8)
README.md               provenance: pins, generator commands, what is hand-pinned and why
```

`profile.json` (the `gen3_frlg` shape; title key `emerald`):

```json
{"generator": "tools/gen_gen3_profile.py", "pack": "gen3_emerald", "schema": "<same as gen3_frlg>",
 "source": {"file": "data/gen3/pret/pokeemerald.sym", "git_head": "<cut>", "sha256": "<sym sha256>"},
 "titles": {"emerald": {
   "_src": {"<FIELD>": "pokeemerald.sym:<symbol> | <pret file:line>"},
   "admitted": true, "variant": "emerald", "rom_sha1": "f3ae088181bf583e55daf962a92bb46f4f1d07b7",
   "ram":  {"PARTY_BASE": "gPlayerParty 0x020244EC", "PARTY_COUNT_ADDR": "gPlayerPartyCount 0x020244E9",
            "ENEMY_BASE": "gEnemyParty 0x02024744", "ENEMY_COUNT_ADDR": "gEnemyPartyCount 0x020244EA",
            "BATTLE_MONS_ADDR": "gBattleMons 0x02024084", "BATTLE_TYPE_ADDR": "gBattleTypeFlags 0x02022FEC",
            "BATTLE_OUTCOME_ADDR": "gBattleOutcome 0x0202433A", "BATTLE_COMM_ADDR": "gBattleCommunication 0x02024332",
            "BATTLE_RESULTS_ADDR": "gBattleResults 0x03005D10", "CHOSEN_ACTION_ADDR": "gChosenActionByBattler 0x0202421C",
            "DISABLE_STRUCTS_ADDR": "gDisableStructs 0x020242BC", "STATUS3_ADDR": "gStatuses3 0x020242AC",
            "GMAIN_ADDR": "gMain 0x030022C0", "TASKS_BASE_ADDR": "gTasks 0x03005E00",
            "SB1_PTR_ADDR": "gSaveBlock1Ptr 0x03005D8C", "SB2_PTR_ADDR": "gSaveBlock2Ptr 0x03005D90",
            "PSP_PTR_ADDR": "gPokemonStoragePtr 0x03005D94", "TRAINER_OPPONENT_ADDR": "gTrainerBattleOpponent_A 0x02038BCA",
            "BATTLERS_COUNT_ADDR": "<sym>", "BATTLER_PARTY_INDEXES_ADDR": "<sym>", "BATTLE_MAIN_FUNC_ADDR": "<sym>",
            "LOCKED_MOVES_ADDR": "<sym>", "POKEMON_STORAGE_BASE": "<sym>", "SPECIAL_VAR_BOX_ID_ADDR": "<sym>",
            "SPECIAL_VAR_BOX_POS_ADDR": "<sym>"},
   "rom":  {"BASESTATS_ADDR": "gSpeciesInfo 0x083203CC", "BATTLE_MOVES_ADDR": "gBattleMoves 0x0831C898",
            "EXPERIENCE_TABLES_ADDR": "<sym>", "RETURN_FROM_BATTLE_ADDR": "ReturnFromBattleToOverworld 0x0803DF70",
            "BEGIN_BATTLE_INTRO_ADDR": "<sym>", "BEGIN_BATTLE_INTRO_DUMMY_ADDR": "<sym>",
            "BATTLE_INTRO_GET_MONS_DATA_ADDR": "<sym>", "CB2_EVOLUTION_BEGIN_ADDR": "<sym>",
            "CB2_EVOLUTION_LOAD_ADDR": "<sym>", "CB2_EVOLUTION_UPDATE_ADDR": "<sym>",
            "CB2_TRADE_EVOLUTION_UPDATE_ADDR": "<sym>", "PP_UP_GET_MASK_ADDR": "<sym>",
            "POST_BATTLE_WRITER_TASKS": ["<task syms>"], "SE_SONG_HEADERS": ["<syms>"]},
   "derived": {"SB2_ENC_KEY_OFFSET": 172, "SB1_FLAGS_OFFSET": 4720, "SB1_VARS_OFFSET": 5020,
               "SB1_BALL_POCKET_OFFSET": 1616, "SB1_BALL_POCKET_COUNT": 16,
               "SB1_LOCATION_MAP_GROUP_OFFSET": 4, "SB1_LOCATION_MAP_NUM_OFFSET": 5,
               "GMAIN_INBATTLE_OFFSET": 1081, "GMAIN_INBATTLE_MASK": 2, "BASESTATS_ENTRY_SIZE": 28,
               "<remaining 45 derived keys>": "same key set as gen3_frlg; each value re-derived from pret pokeemerald, never copied"},
   "rom_thumb": ["<same key list as gen3_frlg>"]}}}
```

Values shown are research findings (`research/facts_2026-09-25.md` §A2), **not pins**. The generator
recomputes every one from the pinned build. The HEADER oracle cross-checks `SB1_FLAGS_OFFSET` (0x1270),
`SB1_VARS_OFFSET` (0x139C) and the SaveBlock sizes against the ROM's GF header.

`engine_signals.json`: `titles.emerald.artifacts.clean.sites[]` = `{kind, address, capture_offset,
expected_hex, rom_offset, point, mode}`, plus `artifacts.named` (BPEE header fallback, refused on byte
mismatch). `evidence`/`live_verified` stay false until E2.

`write_checkpoint.json`: `emerald.{anchors{cb1_overworld,cb2_overworld,frame_control,run_tasks,try_saving_data},
battle{clauses,commit_guard,handoff,version}, cpu, pointers{gPokemonStoragePtr,gSaveBlock1Ptr,gSaveBlock2Ptr},
predicates{…same 10…}, sound, tasks{allowed_overworld_tasks,…}, witnesses{save_dialog_cb}}`.

Entry wiring (`lua/gen3/entry.lua`): `PACKS.gen3_emerald = {rom_type = {emerald = "emerald"},
header_code = {BPEE = "emerald"}}` (code -> title, matching `gen3_frlg`'s `{BPRE = "firered", ...}`),
`PACK_FILES.gen3_emerald = {profile=…, sites=…, checkpoint=…,
area_map=…, locations=…}`. Add `ROUTED.gen3_emerald = true` only at EG4 (ruling 24).

## T2 Worker card brief (source: `docs/agents/worker_card.md`)

```
Card <id> — <one-line goal>
Worktree: E:/Google Drive/SLink/.claude/worktrees/gen3-emerald (branch claude/gen3-emerald)
Contract: docs/agents/worker_card.md (read it; this brief only adds card specifics)
Model: <haiku|sonnet|opus> (explicit)
Source cut: <sha>          Prerequisite gate: <EGn signed | none>
Lease (exclusive): <exact files>
Read-only context: <files, pret paths, research §>
Build: <what, one paragraph>
First falsifier: <the red test and its expected failure message>
Grant conditions: additive title rows only; FRLG and RR --check byte-identical;
  gen3_codec.py edits coordinated with the calc lane
Exit evidence: <tests named, commands, receipts>
Reuse decision: <which existing module/helper it binds, and why nothing new is shared>
Report: worker_card.md "The report" (4 parts)
```

OMP headless card (reviews, tests, small code; short, contained):

```
mode=<REVIEW|FACT_CHECK|DELEGATE> delivery=headless workingDirectory=<worktree>
timeoutMs<=1200000. The task text states: "Hard kill limit N min; reply within M min with what
you have." Read-only unless DELEGATE+allowWrites for a small named file set. Cite file:line.
```

Record the outcome with `kind=outcome` (accepted/rejected/open) once each finding has been checked.

## T3 Gate request (source: `docs/gen3/G4_request_draft.md`)

```
# EG<n> request — <title> (draft, <date>)
## 1 What EG<n> signs          <the exact claim; what it does NOT sign>
## 1a Status at checkpoint <k>  <frozen cut sha, lanes run, open items>
## 2 Per-item status           <REQUIREMENTS.md rows with S/M/P and receipt paths>
## 3 Defects found and fixed   <red→green, commit shas>
## 4 MODEL evidence            <suites + counts>
## 5 Limits carried forward    <not signed by this gate>
## 6 Owner decisions           <numbered rulings, verbatim, dated>
## 7 How to verify this draft  <exact commands>
```

## T4 Requirements row + receipt line (source: `docs/gen3_requirements.md`)

```
| <ID> | <Requirement, one sentence> | <SOURCE: tool or pret file:line> | <ORACLE> | <S> | <M> | <P> |
- <date> <ID> <S|M|P> <PASS|FAIL> <cut sha> — <receipt path> — <one-line what it proves>
```

## T5 Resume checkpoint (source: `docs/gen3_resume.md`)

```
## CHECKPOINT <k> (<date>, <block length>): resume here
Owner rules this block: <worker models/limits, OMP policy>
- FROZEN CUT <sha>: <what is frozen, lanes/commands to finish>
- Done since last: <commit shas with one-line why>
- Open failures: <receipt → diagnosis → fix plan, red first>
- Owner decisions pending: <numbered>
- NEXT: <1..n, exact commands>
```

## T6 Expansion-hack onboarding recipe (X4; open-source hacks only)

1. **Pin**: record the hack's repo, commit sha, expansion version (from `include/constants/expansion.h`
   or the RHH header of a built ROM), and compiler, in `data/gen3_exp_sources.lock.json` (one entry per build).
2. **Build**: `python tools/build_expansion.py --build <name>` twice. Both builds must give the same sha1.
   Keep `.elf/.map/.sym`; never publish the ROM.
3. **Offsets**: `python tools/gen_expansion_facts.py --build <name>` compiles `tools/expansion_offsets.c`
   against the hack tree (the same compiler and flags) to get `BattlePokemon`, `SaveBlock1/2`, `SpeciesInfo`,
   `MoveInfo` and `ItemInfo` offsets (config-exact, honours `FREE_*`/`P_*`).
4. **Data**: `python tools/extract_expansion_data.py --build <name>`: species/moves/items/abilities
   read through the GF/RHH header pointers. Check: species count == RHH `numSpecies`.
5. **Pack**: run the generators with the build's `.sym/.map` (profile, sites, checkpoint). Generate the area
   map and statics from the hack's own `data/maps/map_groups.json` and `src/data/wild_encounters.json`
   using the E1 Emerald area generator.
6. **Fixtures**: town/battle/trainer (+`_b`) via `tools/gen3_fixtures.py` (scripted, or disclosed
   O-33 synthetic setup); `--qualify --boot-check`.
7. **Rows**: add a `gen3_exp` artifact row to probe/observer/duo/final-cut. Generate the
   `gen3_title_syms.lua` entries from the `.sym` file.
8. **Admission**: kind `clean` = exact build sha1. A ROM whose RHH header is present but whose sha1 is
   unknown is refused by name: "pokeemerald-expansion build <maj.min.patch> is not onboarded (sha1 <…>)".
9. **Gates**: the XG1-equivalent facts sign-off, then probe/duo receipts, then owner play.

## T7 Emerald fixture brief (E1-FIX; its OMP scoping card cx-2801b7c2 timed out)

Step 1 (Sonnet or OMP, ≤15 min each, split). First read `tools/gen3_fixtures.py` `cmd_make_fr`/`cmd_make_fr_party`
and its Lua driver: how it waits (RAM predicates vs frames) and how `_b` variants get a distinct OT.
Then choose one:
- **(a) Scripted new game**: Birch intro → gender/name → truck → Mom → bedroom clock → Route 101 Birch
  rescue (starter) → lab → Oldale (town fixture near the PC) / Route 101–102 grass (battle) /
  Route 103 rival or a Route 102 youngster (trainer). Wait on `gSaveBlock1Ptr->location` and on
  `gMain.callback2` (pokeemerald.sym).
- **(b) Disclosed O-33 synthetic setup**: the codec writes a bootable flash save (SB2 0xF2C, SB1 0x3D88,
  14 sections/slot, checksums, signature 0x08012025, location warp). Only the behaviour under test runs natively.

Pick the one with less new code that still passes `--boot-check`. Record the choice in the card report.
