# Gen 2 source-qualified engine-site candidates

This P2 cut provides **43 typed CPU candidates per selected title**, representing
all 25 inventory families. Representation is not completion: event-source joins,
guard/latch implementations, several story classifications, physical firing and
liveness remain open. It does **not** complete F3, arm hooks, grant runtime
admission, demonstrate firing, or establish persistent writes. Every site remains
SOURCE_CANDIDATE with physical_firing OPEN and runtime_enabled false.

The selected artifacts are Crystal 1.0, Gold, and Silver. Crystal 1.1 remains
build-only. All inputs pass `tools/gen2_source_data.py` admission: exact source
HEAD and clean source, P1 lock/provenance, all four SYM/MAP artifact hashes and
the selected actual ROM hash. No legacy profile or `pret_syms.json` is consumed.

## Source and byte derivation

- Crystal: `pret/pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651`.
- Gold and Silver: `pret/pokegold@656583c939d30f920a316177311a502dd222b57c`.
- The curated specification is `data/gen2/engine_site_specs.json`; its source
  prefixes and caller/semantic excerpts come from those exact clones. The
  earlier `research/codex_engine_site_audit.md` was navigation only.

The generator resolves each anchor through the selected built SYM. It then
locates the same scoped source label, checks the source file's SHA-256, and
requires the exact normalized instruction prefix. A bounded SM83 opcode/length
walker derives the byte offset by walking those instructions from the label;
it never scans the ROM for a coincidentally matching byte sequence. Known
symbol operands, relative branches, predef indices and farcall expansions are
checked against the actual ROM. Predef/farcall expansion source is checked.
Unimplemented instructions and script commands are refused.

This is deliberately not a general assembler. Named immediate constant
expressions are not independently re-evaluated: their operand bytes come from
the already hash-verified ROM; instruction opcodes, lengths, source text, and
symbol operands constrain the boundary. A new instruction or source shape
needs an explicit implementation/review, never a guessed size. `expected_hex`
contains the exact resulting ROM slice. Full ROM admission remains mandatory,
especially for one-byte return anchors.

Source hashes describe UTF-8 source text after newline normalization by the
verified source reader; ROM/SYM/MAP hashes describe actual artifact bytes. Each
site records exact repo, commit, path, first/last line and source hash. The pack
also records every source file read, the canonical specification hash, lock
hash, build-provenance hash and selected ROM/SYM/MAP hashes. There is no date or
machine path in generated output.

## Candidate table

All addresses below are CPU `bank:address` in hexadecimal. These are SOURCE
candidates only. The generated packs are authoritative for bytes and citations.

| Candidate | Crystal 1.0 | Gold | Silver | Source point / limitation |
| --- | --- | --- | --- | --- |
| `battle_faint` | `0f:51aa` | `0f:50f4` | `0f:50f4` | `UpdateFaintedPlayerMon` entry; active index is `wCurBattleMon`, before battle-to-party copyback |
| `battle_end` | `0f:769e` | `0f:7456` | `0f:7456` | `ExitBattle` entry; result/evolution/cleanup remain ahead, mask result bits |
| `wild_ready` | `0f:7648` | `0f:7400` | `0f:7400` | `InitEnemyWildmon.skip_unown`; enemy/move/PP staging preceded graphics work |
| `trainer_ready` | `0f:7606` | `0f:73c4` | `0f:73c4` | `InitEnemyTrainer.done` return after trainer load and mode assignment |
| `capture_party` | `03:6adb` | `03:6b50` | `03:6b4e` | immediately after `predef TryAddMonToParty`; metadata/name work remains |
| `capture_box` | `03:6b44` | `03:6bb3` | `03:6bb1` | immediately after `predef SendMonIntoBox`; before conditional BOX_FULL flag |
| `poison_faint` | `14:4649` | `14:467f` | `14:467f` | `DoPoisonStep.DamageMonIfPoisoned` zero-after-damage branch, before status reset |
| `whiteout_before_heal` | `03:401b` | `03:422b` | `03:422b` | CPU `Special` entry with **all** script/register/stack guards below |
| `hatch_species` | `05:6fc5` | `05:736d` | `05:736d` | after replacing parallel EGG marker; OT/HP/name finalization remains |
| `save_completed` | `05:4c6a` | `05:4d0d` | `05:4d0d` | terminal `_SaveGameData` RET, after its internal calls return |
| `new_game` | `01:5b6b` | `01:5c1e` | `01:5c1e` | `NewGame` entry before ResetWRAM; final campaign identity unavailable |
| `soft_reset` | `00:0150` | `00:05b0` | `00:05b0` | `Reset` entry; subsequent shared Init also has cold-start callers |

Gold and Silver acquisition addresses differ despite shared source/RAM layout.
The source prefix for `ExitBattle` also differs between Crystal and Gold/Silver;
there is no reused repo-wide offset. Banked candidates carry `hROMBank` guards,
and point-symbol records preserve their own WRAM/SRAM bank metadata. The pack
does not implement a memory-domain reader or qualify CGB frame timing.

## Whiteout is guarded CPU dispatch

`Script_Whiteout` contains script bytecode, including `special HealParty`.
It is never an execution hook. Its exact script prefix is checked only to derive
the interpreter position after the HealParty special operand has been consumed.

The actual hook is CPU `Special` before it looks up and calls the special.
`Script_special` fetched the two operand bytes into DE. `GetScriptByte` advanced
`wScriptPos`; the farcall path preserves DE. The generated guard is the
conjunction of:

1. `hROMBank` equals the CPU site's bank.
2. DE equals `(HealPartySpecial - SpecialsPointers) / 3`, verified as 27.
3. `wScriptBank` equals the bank of `Script_Whiteout` and little-endian
   `wScriptPos` equals the address immediately after its HealParty operand.
4. The word at SP equals the return after `FarCall_hl`'s call of
   `FarCall_JumpToHL`; the word at SP+4 equals `Script_special`'s farcall return.
   The intervening word is the saved AF from `FarCall_hl`.

The generator derives these return addresses from separately checked CPU
instruction prefixes and verifies the special pointer targets actual
`HealParty`. Script command indices differ across repositories: Crystal's
wait/pause bytes are `$54/$8b`, Gold/Silver's are `$53/$8a`. They are derived
from each pinned macro enumeration, not copied across titles.

These predicates are SOURCE-backed candidates, not a measured live hook ABI.
The future binder must qualify stack access, CGB banking, ordinary-heal negative
controls, battle/poison positive paths, and pre-heal identity/HP capture. Missing
any guard must refuse the hook; presence of a candidate pack grants no writes.

## Additional completion and intermediate sites

All are SOURCE candidates. Requires-prior is a mandatory same-operation
success/identity dependency, not evidence that a runtime latch already exists.

| Candidate | Crystal | Gold | Silver | Phase |
| --- | --- | --- | --- | --- |
| `pc_deposit_begin` | `38:7094` | `38:7873` | `38:7873` | `before_transfer_attempt` |
| `pc_deposit_complete` | `38:70a5` | `38:7884` | `38:7884` | `after_successful_copy_and_compaction` |
| `pc_withdraw_begin` | `38:7119` | `38:78f8` | `38:78f8` | `before_transfer_attempt` |
| `pc_withdraw_complete` | `38:712b` | `38:790a` | `38:790a` | `after_successful_copy_and_compaction` |
| `pc_release_party_begin` | `38:6515` | `38:6d22` | `38:6d22` | `confirmed_before_removal` |
| `pc_release_party_complete` | `38:651b` | `38:6d28` | `38:6d28` | `after_confirmed_removal` |
| `pc_release_box_begin` | `38:6709` | `38:6ef7` | `38:6ef7` | `confirmed_before_removal` |
| `pc_release_box_complete` | `38:670f` | `38:6efd` | `38:6efd` | `after_confirmed_removal` |
| `change_box_begin` | `05:4a83` | `05:4b2a` | `05:4b2a` | `before_confirmation` |
| `change_box_loaded` | `05:4aa8` | `05:4b4c` | `05:4b4c` | `after_old_box_save_and_new_box_load` |
| `evolution_species_published` | `10:63f2` | `10:63ee` | `10:63ee` | `after_party_species_list_publish` |
| `npc_trade_begin` | `3f:4c63` | `3f:4a69` | `3f:4a69` | `before_npc_trade_replacement` |
| `npc_trade_finalized` | `3f:4dc1` | `3f:4b8d` | `3f:4b8d` | `after_npc_trade_identity_and_stats` |
| `map_entry_complete` | `25:676c` | `25:66b1` | `25:66b1` | `after_map_setup_status_publish` |
| `continue_confirmed` | `01:5d96` | `01:5e04` | `01:5e04` | `loaded_confirmed_before_map_entry` |
| `capture_party_finalized` | `03:6be2` | `03:6c4b` | `03:6c49` | `after_nickname_requires_acquisition_latch` |
| `capture_box_finalized` | `03:6be2` | `03:6c4b` | `03:6c49` | `after_nickname_requires_acquisition_latch` |
| `hatch_finalized` | `05:707d` | `05:7425` | `05:7425` | `after_hatch_metadata_and_name_requires_slot_latch` |
| `link_trade_received` | `0a:4de9` | `0a:4c97` | `0a:4c97` | `after_animation_before_received_party_copy` |
| `link_trade_saved` | `0a:4e69` | `0a:4d14` | `0a:4d14` | `after_received_copy_evolution_and_trade_save` |
| `bag_ball_received` | `03:52fe` | `03:530b` | `03:5309` | `after_successful_ball_pocket_write` |
| `gift_begin` | `03:6277` | `03:6290` | `03:628e` | `before_gift_insert_attempt` |
| `gift_party_finalized` | `03:63b6` | `03:6391` | `03:638f` | `after_party_gift_identity_and_name` |
| `gift_box_finalized` | `03:63d3` | `03:63ae` | `03:63ac` | `after_box_gift_identity_and_name` |
| `contest_selected` | `03:66ed` | `03:6771` | `03:676f` | `contest_buffer_selected_before_party_or_box_acquisition` |
| `contest_party_finalized` | `13:5aa2` | `31:7c5a` | `31:7c5a` | `after_contest_party_name_and_metadata` |
| `contest_box_inserted` | `13:5ad5` | `31:7c8d` | `31:7c8d` | `after_successful_contest_box_insert_before_name` |
| `contest_box_finalized` | `13:5b34` | `31:7cc9` | `31:7cc9` | `after_contest_box_name_requires_insert_latch` |
| `script_wild_staged` | `25:7423` | `25:7295` | `25:7295` | `after_script_wild_species_and_level_staging` |
| `roamer_party_finalized` | `03:6be2` | `03:6c4b` | `03:6c49` | `after_roamer_name_requires_success_and_type_guards` |
| `roamer_box_finalized` | `03:6be2` | `03:6c4b` | `03:6c49` | `after_roamer_name_requires_success_and_type_guards` |

## Mandatory success and identity guards

Register/flag and prior-event guards are part of the generated contract.
Requires-prior mode ANY selects one of its listed prior sites in the same
operation. It must be consumed once and invalidated on failure, cancellation,
reset, reload or source change. Listed match_symbols must agree between events.
The future binder must preserve captured record identity and destination across
compaction; a pending site ID alone is not identity proof. The generator
validates declarations and missing predecessors; it does not implement these
runtime state machines.

- **Ordinary captures:** insertion and final naming are separate sites.
  PokeBallEffect.return_from_capture also handles failed, debug and tutorial
  throws. Each final row requires its successful party/box insertion latch.
- **Hatch:** HatchEggs.next is shared with non-egg/unhatched skips. Final
  publication requires hatch_species for the same wCurPartyMon. On that path,
  HP, OT ID/name and nickname work are complete. Runtime gift_daycare handling
  and the slot latch remain unqualified.
- **PC operations:** deposit/withdraw failure carry branches bypass the
  post-compaction site. Release start occurs after confirmation/refusal checks
  The binder therefore lets a new deposit/withdraw/release/NPC-trade/ChangeBox
  start supersede an unconsumed start of the same kind (counted in `drops`):
  `.BoxFull` (pokecrystal `engine/pokemon/bills_pc.asm:1779,1809`, pokegold
  `:1757,1787`), `.PartyFull` (`:1834,1864` / `:1812,1842`) and
  `ChangeBoxSaveGame.refused` (`engine/menus/save.asm:45-59` / `:46-59`)
  never reach the completion site. Capture/hatch/contest starts keep the
  duplicate refusal.
  and before removal. Completion consumes retained outgoing identity.
  ChangeBox has distinct attempt and post-save/load candidates.
- **Evolution:** the evolved struct and level-up move work precede .skip_unown.
  The hook follows the parallel species-list write. wCurPartyMon names the slot;
  the old species comes from the generated `identity_migration` table, **not**
  wEvolutionOldSpecies (see "Evolution identity migration" below).
- **NPC trade:** nickname, OT name/ID, DVs, held item and stats are complete at
  terminal return. Receiver is **PartyCount minus one**. wCurPartyMon was
  restored to the outgoing selection and must not select the received record.
- **Link trade:** the after-animation marker precedes incoming copy and forced
  evolution. The later candidate follows SaveAfterLinkTrade. Protocol/readback,
  host scenario save and cold reload still qualify transaction/persistence.
  Both rows require wLinkMode == LINK_TRADECENTER (2), derived from each
  repository's serial constants. They do not admit Time Capsule or mobile paths.
- **Ball receipt:** PutItemInPocket.done is success-only SCF/RET. Require carry
  and **DE equals wNumBalls**. Other pockets and capacity-refusal returns are
  excluded. Read quantity back; no one-item increment is presumed.
- **Gift:** GivePoke.skip_nickname returns party success with **Z=1, B=0** and
  box success with **B=1** after final nickname copy. Failure returns B=2.
  Both success rows require retained gift intent.
- **Contest:** accepted replacement/first catch yields a provisional buffer.
  Final party/box acquisition is separate. Box final requires a success-only
  InsertPokemonIntoBox latch because .BoxFull also runs on capacity refusal
  and still publishes the boxed result in both repositories. Crystal also
  touches first-box-mon caught metadata on refusal. Neither return nor script
  result alone proves insertion.
- **Roamers:** final rows require a successful insertion latch and
  wBattleType == BATTLETYPE_ROAMING (5), derived separately from both enums.
  Ordinary/failed catches and Crystal fixed Suicune are excluded.
  A roaming result alone does not distinguish capture from defeat.
- **Map/CONTINUE:** map entry completion follows setup/status publication.
  CONTINUE follows save/RTC confirmation but precedes clock/roamer/mobile/map
  work; it grants no live-session admission.

## Evolution identity migration

`evolution_species_published` is the `push hl` after `ld [hl], a` in
`EvolveAfterBattle_MasterLoop.skip_unown` (pokecrystal `engine/pokemon/evolve.asm:312-317`,
pokegold `:313-318`). By then the evolved struct has been copied into the party slot
(`:291-293` / `:292-294`), A holds the new species and HL points at
`wPartySpecies + wCurPartyMon`. The binder emits one `key_change` (reason
`evolution`) with `old_key` = the record's DVs/OT with the old species and
`new_key` = the record's key, and refuses (a value, not a failure) unless A equals
the slot's struct species, HL names wCurPartyMon's list entry, `wLinkMode` is 0,
the species has a pre-evolution, and neither key names a second party record.

- **Old species source.** `wEvolutionOldSpecies` is written once (`evolve.asm:32`,
  both repos) but shares a WRAM UNION byte with `wListMovesLineSpacing`
  (Crystal `01:d1ea`, Gold/Silver `01:d0d3`; `ram/wram.asm:2582/2694`,
  pokegold `:2062/2160`). `LearnLevelMoves` (`evolve.asm:299` / `:300`) reaches
  `predef LearnMove` (`:468` / `:469`) -> `call ForgetMove` (`learn.asm:33`) ->
  `ld a, SCREEN_WIDTH * 2` / `ld [wListMovesLineSpacing], a` (`learn.asm:144-145`,
  both repos) whenever the evolved mon must forget a move, i.e. before the hook.
  It is therefore not a witness. Instead the generator walks the built ROM's
  `EvosAttacksPointers` table the way `evolve.asm:44-53` and its `.loop` read it
  (same bank, STAT entries 4 bytes, others 3, 0 ends a list), refuses unless every
  species has at most one pre-evolution, and emits `identity_migration.old_species_by_new`
  (122 entries per title; equal to the independently generated `evolutions.json`).
- **Cancel control.** A B-press makes `EvolutionAnimation` return carry and
  `jp c, CancelEvolution` (`evolve.asm:228`, both repos); `CancelEvolution`
  (`:379-384` / `:380-385`) jumps back to the master loop without executing
  `.skip_unown`, so a cancelled evolution emits nothing.
- **Link trade.** `engine/link/link.asm:1998` (pokegold `:1828`) calls
  `EvolvePokemon` with `wLinkMode` set; that evolution belongs to the OPEN
  link_trade transaction and is refused.

## Binder delivery and refusal contract

`lua/gen2/signals.lua` (MODEL only) keeps these rules for every site above:

- A boundary (battle_end/soft_reset/new_game/continue_confirmed sites, or an explicit
  `boundary()`) retires latches but never discards queued events: batches finalized
  before it are delivered by the next `drain()` in engine order. The only drop is a
  latch-creating observation (`observation`, `faint`) stamped with an operation that
  is no longer held; it is counted in `status().drops` with its reason.
- A refusal is a value: no event, the reason in `status().refusals[site]`, open latches
  retired, later signals keep flowing (the client logs each site/reason once). Only
  invariant breaks (corrupt site metadata, broken io, impossible latch state, a
  mapped ROM bank that disagrees with the verified shadow) stop the shared registry.
- `battle_faint` and `poison_faint` carry the fainting record's same-frame identity:
  the party struct at `wCurBattleMon` (`UpdateFaintedPlayerMon` entry) or
  `wCurPartyMon` (`DoPoisonStep.DamageMonIfPoisoned`). Battle copy-back has not run,
  but DVs/OT/species never change in battle, so the key is final.

## Open source and physical obligations

Every family now has at least one typed SOURCE candidate, but **F3 remains
false**. No physical firing, causal latch, bank/frame behavior, queue ordering,
positive/refusal scenario or independent persistence oracle is closed.

CPU Script_loadwildmon provides scripted-wild origin staging, distinct from a
catch. Per-story static eligibility and association with later capture events
still require the story/encounter policy. Crystal Tin Tower Suicune uses
BATTLETYPE_SUICUNE in maps/TinTower1F.asm:119-121; it is **not** roaming mode.
Its separate legendary/static classification remains SOURCE OPEN instead of
silently inheriting the roaming predicate. Gold/Silver roaming Suicune follows
roaming mode. Natural legend_<species> extra-catch and national_park_contest zone
behavior remain unqualified.

Shared CPU addresses require their distinct guards, predecessor identity and
cancellation/reset invalidation. A future registry can bind one address and
dispatch only matching typed events; emitting every row at that address would
be incorrect.

Roamer rows have event_role CLASSIFICATION_ONLY: they decorate the same generic
acquisition and must never emit a second capture or consume the latch twice.
The future binder must evaluate applicable observations/classifiers together,
then consume the operation once. That composition is not implemented here.

The save candidate is a success-path CPU return, not CartRAM durability.
All save callers/variants, raw CartRAM witness and cold-boot primary/backup
recovery remain open. A transient battle-loss value is not whiteout proof.

## Interface and verification

`generate_pack(context, specs)` returns the `gen2-engine-signals-v1` wrapper,
with exactly one selected title. `verify_pack(context, pack, specs)` regenerates
the complete expected structure from verified inputs and refuses any mismatch,
including bytes, bank/address, source provenance, mandatory guards, maturity,
or omitted inventory/site rows. Both CLI entry points expose `main(argv)`.

```text
python -B tools/gen_gen2_engine_signals.py
python -B tools/gen_gen2_engine_signals.py --check
python -B tools/verify_gen2_rom_layout.py
python -B -m pytest tests/unit/test_gen2_engine_sites.py -q -p no:cacheprovider
```

Generation validates all three outputs before publishing any pack. `--check`
does not write. `--root` permits an explicitly selected workspace. The layout
verifier supports `--title crystal|gold|silver`; the default verifies all three.
It does not launch an emulator, rebuild inputs, repin hashes, or modify sources.

The refusal tests cover wrong expected byte, site bank/address/offset, script
labels even with plausible CPU bytes, source-shape/hash drift, symbol-operand
drift, maturity/provenance changes invalid register/flag guards, missing lifecycle predecessors, removal of required
success latches, and missing sites/inventory. The real-input
test requires all three current locked ROM/source contexts with no missing-input
skip. Unit results are MODEL; pinned source and byte comparisons are SOURCE;
all physical firing, liveness, lifecycle and release gates remain OPEN.
