# pureRGB integration — changelog

Branch `claude/purergb-soul-link-integration-ff5e13`, 78 commits on local master `bbcd037`
(the Gen 1 Red/Blue release candidate), 2026-09-17 → 2026-09-19. Owner gates G0–G5 signed;
G6 (tag + release) is the owner's. The version number comes from the git tag at publication,
never from this file.

Everything below cites the commit that landed it. `PLAN.md` §13.1 holds the gate ledger and
§11.2 the research facts each change rests on; `docs/release_notes.md` carries the short form.

---

## 1. Summary

[pureRGB](https://github.com/Vortyne/pureRGB) **v2.7.6** (commit `7e7a46535ca332ad24ecb02e326ea2f75e79ebb9`)
is a second Gen 1 *foundation* on the Soul Link platform: `game_id gen1_purergb`, titles
**PureRed / PureBlue / PureGreen**, on the same rewritten Lua client, codec, server and harness
as vanilla Red/Blue/Yellow. Every game fact is generated from the pinned source and verified
against a byte-reproducible build; nothing is hand-typed and nothing vanilla was weakened —
`data/games/gen1_rby/*` regenerates byte-identical apart from two deliberate additions to
`profile.json` (§4.3), and every vanilla release lane re-ran green.

Three deliverables sit on top of the rules:

| Deliverable | What it is | Where |
|---|---|---|
| Rules on pureRGB | encounter linking, dead zones, faint propagation, party/PC sync, memorials, whiteout, evolution/transform/APEX identity, Explode Mode, rival swap | `lua/gen1/*`, `server/adapters/gen1_purergb.py`, `data/games/gen1_purergb/` |
| Companion overlay | native Cable Club trade, START-menu SLINK panel, ROM-level APEX collision guard — as **source sections** linked into the pureRGB build | `patch/gen1/purergb/`, `patch/dist/SLink-Pure{Red,Blue,Green}.ups` |
| Randomized pairs | a lossless fork of Universal Pokémon Randomizer ZX 4.6.1 with pure INI entries, wired into the Manager | `patch/upr/*.patch`, `.cache/slink-upr/PokeRandoZX.jar` (`4.6.1-slink1`) |

---

## 2. What ships (artifacts)

- **Cartridges.** The pinned pureRGB build is reproduced from source (`tools/build_purergb_syms.py`)
  or by applying the upstream v2.7.6 `.bps` to a clean Red/Blue dump (`tools/apply_bps.py`);
  either way the sha1 must be `2e94d09c…` (PureRed), `d419fe24…` (PureBlue), `fe4c63a6…`
  (PureGreen) or the client refuses it. Built ROMs are never committed.
- **Overlay patches.** `patch/dist/SLink-PureRed.ups`, `SLink-PureBlue.ups`, `SLink-PureGreen.ups`
  over the corresponding pinned ROM (overlay sha1s `09ddffda…`, `5528ac1f…`, `87e11687…`); shipped in
  the `--with-patch` release bundle (`tools/make_release.py`, `e933380`).
- **Data pack.** `data/games/gen1_purergb/` — 23 files: `profile.json`, `engine_signals.json`
  (41 sites × 3 titles), `write_checkpoint.json`, `admission.json`, `area_map.json` (248 map ids →
  areas), `area_map_notes.json`, `floor_labels.json`, `encounter_tables.json`, `static_encounters.json`,
  `gifts.json`, `species_index.json` (190 internal ids, 13 non-dex records, 9 transform edges),
  `types.json`, `evolutions.json`, `moves.json`, `items.json`, `trainers.json` (56 classes, 492
  parties), `charmap.json` + `charmap.lua`, the overlay twins `profile_overlay.json`,
  `engine_signals_overlay.json`, `write_checkpoint_overlay.json`, `admission_overlay.json`, and
  `README.md`.
- **Symbols and provenance.** `data/purergb/{pokered,pokeblue,pokegreen}.sym|.map` (clean) and
  `*_slink.sym|.map` (overlay), `build_provenance.json`, `overlay_provenance.json`,
  `upr_pure_entries.ini`; `data/purergb_sources.lock.json` (source commit, RGBDS/w64devkit pins,
  expected ROM hashes).
- **Fork patches.** `patch/upr/0001-slink-lossless-pureRGB-support-4.6.1-slink1.patch`,
  `0002-slink-ignore-the-built-jar.patch`; `tools/build_upr_fork.py --bootstrap` clones UPR ZX at
  `7f00eb86` (v4.6.1), applies them and builds with a sha256-pinned Temurin JDK 17.
- **Fixtures.** `tests/fixtures/gen1/pure{red,blue,green}_{town,battle}.SaveRAM` and
  `purered_town_ot2.SaveRAM` (second-OT save for the reconnect wrong-save leg), produced by scripted
  play and qualified by the codec like the vanilla ones.

---

## 3. Changes by area

### 3.1 Build recipe (M0 / P1) — `8349f26`

- `data/purergb_sources.lock.json`: pureRGB commit, tag, RGBDS **1.0.3** (`rgbds-win64.zip`
  sha256 `b66c23cb…`), w64devkit **2.10.0** (sha256 `18d0a4c7…`), the three expected output sha1s.
- `tools/build_purergb_syms.py`: clones/verifies the checkout at the lock, builds all three titles
  with `make`, refuses to publish unless every sha1 matches, then copies `.sym`/`.map` into
  `data/purergb/` and writes `build_provenance.json` (sha256 of every published file).
- `tools/_build_tools_bootstrap.py`: a second pinned RGBDS version beside the vanilla 1.0.1 pin.
- `tools/apply_bps.py`: a BPS v1 applier (target CRC verified) for the harness and for users who
  apply the upstream patch instead of building.
- `.github/workflows/purergb-syms.yml`: the same gate on Ubuntu — builds, checks sha1s, diffs the
  committed symbols.
- Tests: `tests/unit/test_purergb_build.py`, `test_apply_bps.py`.

### 3.2 Data pack and generators (M1 / P2) — `aab51ee`, `96a17eb`, `d4a9ce4`, `6dcad63`, fixes `8821643`, `96e8a7d`, `4d748be`

- `tools/gen1_foundation.py` (new): the one place that knows a foundation's source checkout,
  ROM directory, lock file, sym directory and output directory (`pret` vs `purergb`, and the
  overlay kind). Environment overrides: `SLINK_PURERGB_SRC`, `SLINK_PURERGB_ROMS`,
  `SLINK_PURERGB_OVERLAY_SRC`, `SLINK_PURERGB_OVERLAY_ROMS`; defaults `.cache/purergb` and
  `.cache/purergb-overlay`.
- Every existing Gen 1 generator gained `--foundation purergb` and resolves paths through it:
  `gen_gen1_profile.py` (a per-foundation `derived` block with **source-text asserts** on every
  constant: `ball_items [1,2,3,4,5,8]`, `opp_id_offset 197`, `bag_capacity 30`,
  `base_stats_stride 35`, `dex_count 152`, `species_count 190`, `rival_trainer_ids [221,237,238]`,
  `wram_bank_gate`, `hardware cgb`, later `explode_low_hp_fraction 3`), `gen_gen1_evos.py`
  (pointer-table walk; 76 entries → 72 edges / 79 families), `gen_gen1_encounters.py` (adds the
  pure fishing formats: two `lb bc` Old Rod sites, `GoodRodMons` + `GoodRodMonsOcean`, Super Rod
  groups; dex-0 rows kept), `gen_gen1_statics.py`, `gen_gen1_items.py`, `gen_moves_data.py`.
- New generators, all with the RC standard (source-text assert + symbol-derived operand check +
  `expected_hex` sliced from the built ROM): `gen_gen1_engine_signals.py` (41 sites per title,
  incl. the new kinds `transform`, `apex_preflight`, `apex_commit`, `apex_recalc_call`,
  `npc_trade_remove/add/done`, `daycare_withdraw`, `cable_remove/add/partial_save`, `starter`,
  `battle_loop_no_move`, every `SaveGameData` caller), `gen_gen1_write_checkpoint.py` (the pure
  overworld checkpoint `PC == $0040`, `[SP] == DelayFrame+24`, `[SP+2] == OverworldLoop+1`,
  `wDelayFrameBank == 0`, WRAM bank ∈ {0,1}), `gen_gen1_admission_profiles.py` (whole-ROM sha1 /
  md5 / crc32 / header CRC per artifact), `gen_gen1_species.py` (internal-id-keyed species index,
  13 non-dex records classified `form | spirit | missingno`, `base_species` for forms, default
  typings incl. the new type ids, transform edges from the 10 `ChangePartyPokemonSpecies` call
  sites), `gen_gen1_area_map.py` (248 map ids; U10 dungeon collapse; every interior inherits its
  parent; `area_map_notes.json` records each judgement), `gen_gen1_trainers.py` (grammar-aware:
  fixed / `$FF` / `$FE` / `$FD` records, 56 classes, rival ids 221/237/238, ROM-walked 492/492),
  `gen_gen1_charmap.py` (JSON + Lua twin: glyphs, text shortcuts `$33–$4D`, terminator),
  `gen_gen1_gifts.py` (both foundations).
- Three research-phase offsets the generator corrected on the way (the point of the standard):
  `InitBattleCommon+$48`, `ChangeBox.yes+$35`, `TradeCenter_Trade.doTrade+$9D`.
- Vanilla `data/games/gen1_rby/*` regenerates byte-identical (pinned by `test_gen1_profile.py`
  and the `profile-generated` release lane); the pure pack gets mirrored contract tests
  (`tests/unit/test_gen1_purergb_{profile,engine_sites,species,evos,areas,encounters,
  statics_trainers,moves_items_charmap,rom_content,rom_scan,codec,adapter,client}.py`).

### 3.3 Shared server (P3a) — `355f047`, `7be4a39`, `c674b29`

The one change to shared `server/` code, reviewed with `slink-adapter-guard` plus one independent
round; the Gen 3 unit suite ran first. Documented in `docs/protocol.md` (§3.2 `key_change`,
§5 `key_change_ack` / `key_change_rejected`, rule 38a, appendix A18).

- **Acknowledged `key_change`.** `_handle_key_change` is now validate → accept | reject → mutate.
  Accept migrates every keyed structure (the O2 census: `_key_index`, MonInfo incl.
  `encounter_a/b`, pending captures, `party_keys`, `mon_stats`, `bonus_keys`, `pending_memorials`,
  queued commands and in-flight ids, `pending_bonus`, `partner_blobs`, `rebuild_pending`,
  `pending_trade`, then the presentation caches) and replies `key_change_ack{migrated:true}`.
  A replay or an unknown `old_key` acks with `migrated:false`. A **load-bearing** collision
  (a different ALIVE link or a live structure of either player already holding `new_key`) replies
  `key_change_rejected{reason}` with nothing migrated, and the old key's pair is retired
  `cause="identity_lost"` (partner `force_faint`, both memorialized). A DEAD/MEMORIAL index hit
  is accepted (buried keys are reusable, as before). `mon_stats` / `_mon_cache` are deliberately
  not part of the collision census — they never prune, so counting them would make a buried key
  permanently unreusable (`7be4a39` pins that).
- **`_propagate_faint(cause=...)`** replaces the hard-coded `"battle"`; `templates/_macros.html`
  renders the new `identity_lost` tombstone.
- **Dead-key re-queue.** A `key_change` whose old key is DEAD/MEMORIAL re-queues `force_faint` +
  `memorialize` under the new key (dedup by `_has_pending_command`; never `force_explode`).
- **`[x] MIXED GAMES`.** Once a run has committed a `rom_type`, a hello routing to a different
  `game_id` — or, once committed, a different `artifact_kind` (clean vs overlay) — is refused
  with a HUD message and `identity_error`; variants of one game still pair.
- **Contract sha1.** `_decide_admission` compares the hello's `rom_sha1` to the preparation
  contract's, **after** the table fingerprint, so vanilla's wrong-cartridge wording is unchanged
  (`c674b29`).
- **Presentation migration** (`party_details`, `_mon_cache`, `pc_boxes`) now runs after state
  acceptance instead of 110 lines before it.
- `tests/unit/protocol_schema.py`: the two new commands and the `reason` vocabulary
  (`nature_change`, `evolution`, `npc_trade`, `trade_undo`, `transform`, `apex_chip`).

### 3.4 Lua client (P3b) — `a6bfaf0`, `dca0af1`, `35e05cf`, `e25e8a8`, `5ab4c01`, `cc125f3`, `071bff6`, `afb4063`, `0640660`

One client for both foundations; every vanilla literal it used to carry is now a profile field.

- **Admission is hash-first** (`lua/gen1/entry.lua`): `Entry.admit` looks the cartridge's full
  sha1 up in every pack's `admission.json` / `admission_overlay.json` (PureRed/PureBlue keep the
  `POKEMON RED/BLUE` header, PureGreen has no vanilla family at all); an unknown sha1 is tried
  **by anchors** — every engine-site byte string, its prelude and the checkpoint slices of exactly
  one pack/title/kind must match (~400 bytes) — which admits UPR-randomized artifacts as kind
  `rand` / `rand_overlay` (`cc125f3`); a red/blue/yellow header that no table admits boots the
  vanilla pack as kind `named` — the companion-patched vanilla cartridges (`5ab4c01`; `071bff6`
  fixed `Entry.build`, which had no pack-file mapping for that kind and crashed every patched
  vanilla launch). `Entry.BASE_KIND` maps `rand→clean`, `rand_overlay→overlay`, `named→clean`;
  `Entry.pack_file` is the single rule and the harness shares it.
- **Profile-driven facts** (`reads.lua`, `rom.lua`, `client.lua`, `signals.lua`, `writes.lua`,
  `boxes.lua`): bag capacity (`wPocketAbraNick − wBagItems`, 30 on pure), the Poké Ball set,
  the trainer threshold (`opp_id_offset`), the 35-byte base-stat stride with the `NonDexMonsBaseStats`
  table, the per-foundation charmap (raw name bytes stay authoritative for withdraw/rebuild),
  species by internal index, the WRAM-bank gate.
- **Banked WRAM.** On a foundation whose profile says `wram_bank_gate`, every `$D000–$DFFF`
  read goes through BizHawk's flat `WRAM` domain (bank 1 at `0x1000`) and every write is refused
  unless `emu.getregister("WRAM BANK") ∈ {0,1}` — pureRGB selects bank 2 inside its palette-buffer
  loop with interrupts enabled.
- **Battle classifier.** `battle_begin` with `wCurOpponent == 0` is ignored (a non-battle caller
  fires the site after the starter pick); a wild encounter has `wCurOpponent == 0` on both
  foundations (species in `wEnemyMonSpecies2`); a fled wild battle is a failed encounter (dead-zone
  rule kept; the RUN bit is a log witness only, `e25e8a8`); an unsettled in-battle acquisition
  counts as the capture (`3ad62de`).
- **`battle_loop_no_move`** (`dca0af1`): pureRGB's MOVE-menu cancel re-enters
  `MainInBattleLoop.loopNoMoveSelected` below the HP check, so a pending in-battle write
  (`force_faint` / `force_explode`) that missed the loop head lands there and the client moves
  `PC` back to `MainInBattleLoop+6` with `emu.setregister`.
- **Identity events.** `transform` (`ChangePartyPokemonSpecies+0`: old key, old HP; a DEAD mon
  is re-zeroed at the HP store), `apex_preflight` / `apex_commit` (`ItemUseMedicine.useApexChip
  +$0F/+$11`: a predicted collision — same species + OT already at `$FFFF` in the party or the
  scanned boxes — writes the two original DV bytes back before `.recalculateStats`; otherwise
  `key_change{reason:"apex_chip"}` with an old→new alias held until `key_change_ack`), NPC trade
  identity from the removal site with the appended-slot readback, daycare withdrawal from
  `wDayCareMon`. Key reconciliation is suppressed while `wLinkState ≠ 0`.
- **Explode Mode on pureRGB** (`afb4063`, `0640660`): pureRGB's EXPLOSION/SELFDESTRUCT only faint
  their user below ⅓ HP (heavy recoil otherwise, `remap_move_data.asm
  ExplosionSelfdestructModifier`). With `derived.explode_low_hp_fraction` present the client first
  drops `wBattleMonHP` under `max/3` and sets the battle-struct speed to 999 so the battler acts
  before the foe can KO it; the party mirror is untouched (the engine writes it back at the
  faint). Vanilla has no such field and is unchanged.
- **Panel / trade overlay** (`lua/gen1/panel.lua`, `trade_overlay.lua`): mailbox, service bank/
  address, receptionist hook and ABI windows come from the profile's `trade` block on an overlay
  cartridge (vanilla keeps the module constants); the panel exposes its `mailbox` for the harness.
- **Launcher route** (`lua/slink.lua`, `lua/gen1/run.lua`): the universal launcher detects a
  GB/GBC cartridge, admits it (sha1 → anchors → named family), reports `foundation` and
  `artifact_kind` in the hello.

### 3.5 Adapter, codec, ROM scan, Manager (P3b) — `b2c21bd`, `36eb101`, `cc125f3`

- `server/adapters/gen1_purergb.py`: `Gen1PureRGBAdapter`, `game_id gen1_purergb`, rom types
  `PureRed | PureBlue | PureGreen`, **class-level tables** loaded from the pure pack (the vanilla
  adapter's data is module-bound); `species_name` for forms and spirits, `evo_family` via
  `base_species` + transform edges, `species_types` from pureRGB's default typings, data-driven
  statics and gift areas, `rival_trainer_ids` from `trainers.json`, `trainer_info` for 56 classes,
  `native_trade_ui()` true only for an overlay artifact (`set_artifact_kind`), an unknown variant
  raises instead of defaulting to Red.
- `server/adapters/gen1_codec.py`: per-foundation layout (`codec.for_foundation("gen1_purergb")`
  — bag SRAM offset `$27E6` vs vanilla `$25C9`, 35-byte stride, non-dex table, charmap with
  shortcut expansion); the SRAM bank-1 map, checksums and party layout are identical to vanilla
  and stay shared.
- `server/adapters/gen1_rom_scan.py`: `identify()` by header title + pinned sha1 set (clean and
  overlay), pure fishing walkers, the 35-byte stride, the `rom_content` wire contract used by
  admission fingerprints.
- `server/adapters/__init__.py`: routing and labels for the three rom types.
- `server/manager.py`: `GAMES` family `("gen1_purergb", "PureRed · PureBlue · PureGreen", …)`,
  `OPTION_SUPPORT` rows (gender clause unsupported with the pureRGB reason, Explode + rival swap
  supported), `gen1_games` extended, the randomizer page names the jar it found ("SLink fork jar
  (vanilla + pureRGB)"), the run config pins Console Mode GBC and `GbAsSgb=false` for pure lanes.
  `tests/fixtures/ui/capabilities.json` regenerated.
- `server/patcher.py` targets `pure-red / pure-blue / pure-green`.

### 3.6 Companion source overlay (M3 / P4) — `3b893be`, `c15d1bb`, `2f258e7`

The vanilla binary patch cannot apply to pureRGB (ROM0 is full, the RST vectors are live code,
the vanilla mailbox address `$DEE2` is inside pureRGB's box data), so the companion is a set of
**source sections linked into the pureRGB build**:

- `patch/gen1/purergb/overlay/`: `slink.asm` (VBlank hook replacing `farcall TrackPlayTime`,
  saves/selects/restores `rWBK` around the 12-byte mailbox at `$DEEA`, beacon `SLNK` as numeric
  bytes because the preincluded charmap would remap `'S'`; the overworld foreground hook after
  `rst _DelayFrame`), `slink_home.asm` (`SlinkStartMenuEntry`, 9 bytes of ROM0 in a `"SLink Home"`
  section), `trade_service.asm`, `native_trade.asm`, `trade_receptionist.asm` (no second
  `WaitForTextScrollButtonPress`), `trade_ui.asm`, `trade_prompt.asm`, `species_table.inc`, and
  `apex_guard.asm` (`SlinkApexGuard`: refuses a colliding APEX CHIP use **before** the chip is
  consumed, using pureRGB's own `.alreadyUsedApex` text). Bank `$3F`; mailbox ABI 3 and the
  `SLT1` lease v1 are unchanged, so `lua/gen1/panel.lua` / `trade_overlay.lua` drive both builds.
- `tools/apply_purergb_overlay.py`: 14 verify-then-replace edits to the pinned checkout
  (`main.asm`, `layout.link`, `home/vblank.asm`, `home/overworld.asm`, `home/map_objects.asm`,
  `home/start_menu.asm`, `engine/menus/draw_start_menu.asm`, `custom_list_menu.asm`,
  `ItemUseMedicine`, `TryEvolvingMon` export).
- `tools/build_purergb_overlay.py`: applies, builds, verifies byte-reproducibility, re-runs the
  generators for the overlay kind (`profile_overlay.json`, `engine_signals_overlay.json`,
  `write_checkpoint_overlay.json`, `admission_overlay.json`, `*_slink.sym|map`) and emits the
  UPS files + `overlay_provenance.json`.
- A4 save-ABI gate (`tests/unit/test_gen1_purergb_overlay.py`, 39 tests): every symbol inside
  the saved WRAM regions and every SRAM symbol equal between clean and overlay `.sym`; every
  RAM/SRAM section placement equal in the `.map`; ROM sections may relocate.
- `.gitattributes`: `patch/gen1/purergb/**` and `patch/upr/*.patch` are LF (provenance hashes).

### 3.7 UPR ZX fork (M5 / P5) — `2e863f7`, `48995bd`, `4ff28fe`

- `patch/upr/0001-…`: a lossless handler for pure entries — no unconditional name/stat/move/
  evo-learnset repack, no intro-Pokémon write, no trainer collateral, 35-byte base-stat stride
  incl. the literal `0x1C`, the 13 non-dex records preserved, MissingNo excluded from the
  randomizable pool, map-name stride 5, four hidden-item entry points, 56 trainer classes,
  `$FE`/`$FD` trainer records round-tripped; `0002-…` ignores the built jar.
- `tools/build_upr_fork.py --bootstrap`: clone at `7f00eb86`, `git am`, build with a pinned
  Temurin JDK 17 → `.cache/slink-upr/PokeRandoZX.jar` reporting `4.6.1-slink1`.
- `tools/gen_upr_gen1_ini.py` → `data/purergb/upr_pure_entries.ini`: `[PureRed (U)]`,
  `[PureBlue (U)]`, `[PureGreen (U)]` from the pinned symbols (the fact-check corrections are all
  in: `WildPokemonTableOffset`/`TradeTableOffset` key names, `MapBanks`/`MapAddresses`,
  `PokemonMovesetsDataSize 0x9F4`, per-title raw immediates, one `StaticPokemon{}` record per
  double-encoded static, `OldRodOffset` at the first immediate pair, class counts from the
  ROM-walked pack).
- `tools/upr_lossless_check.py` (3/3 byte-identical `load→save`) and
  `tools/upr_write_domain_diff.py` (T6: 0 bytes outside the allowlist for the enabled settings).
- `server/upr_pipeline.py`: `SUPPORTED_UPR_VERSION = "4.6.1-slink1"`, `jar_is_fork`,
  `family_of` (a pure pair must both be clean pinned builds), the stock jar still serves vanilla;
  `server/upr_settings.py`: the pure family turns **every** tweak off (fastest text is a code
  write and pureRGB has instant text natively).
- `tools/e2e_duo.py`: the randomized pair for a pure pairing is prepared with fastest text off
  (`48995bd`); `admit_randomized_new` runs on the pure pairings.

### 3.8 Harness (P3b-e / P4c) — `2fc6e93`, `884c257`, `36eb101`, `2d41f91`, `385cd66`, `a2f75ad`, `3e9ccca`, `589a4b3`, `79a4e1f`, `0c923ee`, `ba1ea83`, `3ad62de`, `69a416a`, `249f863`, `30f48d6`, `aefc668`, `20b2a60`, `f2898d1`, `b9fff35`, `c15d1bb`, `139c77b`, `13fdbdc`

- **Per-foundation driver facts.** `lua/tests/gen1_rb_facts.lua` (vanilla twin, reproduces every
  former literal) and `lua/tests/gen1_pure_facts.lua` (223 facts with per-key provenance —
  SAME / DELTA / UNVERIFIED notes); identical key sets pinned by
  `tests/unit/test_gen1_facts_tables.py` with an `EXPECTED_DELTA` list. Every route/battle/PC/
  Center driver takes the lane's facts table (`with_facts`, `Driver.new({facts=…})`); a module
  that is not handed one falls back to vanilla, which is why the duo main passes it everywhere.
  Notable deltas measured live: list-menu watched keys `$2F`, `wMaxMenuItem` = last index (not a
  count), the PC release / change-box / box-list geometry, the whiteout destination (Viridian City
  after a Center visit), the Oak-parcel flag (`EVENT_GOT_POKEDEX`), rival id 221, ball ids, and the
  deliberate lab loss (§3.8 last bullet).
- **Pure cartridges in the harness.** `tools/gen1_playthrough.py`: lock-pinned staging of the
  pure builds (`patch/build/gen1_pure*.gbc`), overlay staging by applying the UPS to the
  sha1-verified clean build (`purergb_overlay_dump`), filename-derived SaveRAM names
  (`gen1 purered.SaveRAM`, `gen1 purered overlay.SaveRAM`), GBC console-mode run configs;
  `tools/run_gb_gate.py`: ROM keys `purered | pureblue | puregreen`, `*_cold`, `*_overlay`;
  `tools/gen1_fixtures.py`: chains for the three titles.
- **Duo pairings** (`tools/e2e_duo.py`): `gen1_pure` (PureRed↔PureBlue, clean), `gen1_pure_green`
  (PureRed↔PureGreen), `gen1_pure_overlay` (the three trade/explode scenarios on the overlay
  artifacts via `patched_saves_override`); a row's scenario family selects its scenarios; per-lane
  isolation (`--lane`: stub, config, SaveRAM dir, window keyed by lane); pairing-aware oracles
  (bag through the pure codec layout, rival id from `trainers.json`, reconnect save/OT from the
  pairing fixture, blackout destination per pairing, `admit_randomized_new` waits for a real verdict
  — `3df8a70`).
- **Harness reads banked WRAM through the flat domain** (`Entry.harness_bus_u8`, `afb4063`):
  the duo main, the gate harness and the scripted-play module no longer read `$D000–$DFFF`
  through the System Bus (a frame-end read once landed inside pureRGB's bank-2 palette loop and
  saw `wPartyCount == 0`).
- **Gates.** `lua/tests/test_gen1_apex_gate.lua` (client-side APEX contract: collision → DVs
  restored, chip consumed, no `key_change`; clean use → `FFFF`, `key_change{apex_chip}`, alias
  cleared by the ack), `lua/tests/test_gen1_apex_refusal_gate.lua` (the overlay's ROM-level guard:
  chip kept, DVs unchanged, pureRGB's own refusal text, normal use afterwards works), the
  receptionist / menu-row / companion-patch gates read the mailbox and ABI windows from the profile
  and the `COMPANION` facts, `tests/live/test_gen1_new_gates.py` parametrised over the pure titles
  (`SLINK_GEN1_ROMS`) plus the overlay round-trip (`SLINK_GEN1_OVERLAY_ROMS`),
  `tests/live/test_gen1_trade_gates.py` and `test_gen1_gates.py` run `purered_overlay`.
- **Release lanes** (`tools/verify_gen1_release.py`, 19 lanes): `profile-generated-purergb`,
  `inspect-purergb` (16), `apex-purergb`, `inspect-purergb-overlay` (6), `live-trade-gates-purergb`,
  `apex-refusal-purergb`, `duo-pairs-purergb` (`tests/e2e/test_duo_gen1_pure.py`, 33 cases).
  Skips count as failures in every lane.
- **The pure deliberate lab loss** (`69a416a` → `139c77b` → `13fdbdc`): vanilla loses the Oak's-lab
  rival battle by Growl-stacking; on pureRGB the rival Growls the starter to −6 within its first
  turns (its AI stops only when maxed) and a Growl-stacked rival at −6 deals 0–1 until its 35
  Scratches are gone, so the Growl-only loss stalled at 2 HP with every PP spent. The pure loss is
  now HP-driven from per-turn receipts (`hp/atk/ehp/eatk`): one Growl (the rival stays at −1),
  Tackle while the rival has more than 6 HP (a 5–6 crit cannot KO it), Growl below — the battle
  ends in ~8 turns. Facts `LAB_LOSS.tackle_max_enemy_hp`, `LAB_LOSS.growl_min_enemy_attack_mod`;
  the pending-Tackle loop walks the restored cursor up instead of cancelling the move menu.
  Vanilla keeps its Growl-only loss (facts 0/0/0).

### 3.9 Tests

- Unit: 3601 passed / 14 explained skips at `13fdbdc` (from 3475 at the Gen 1 RC). 20 new
  pure/fork files: `test_gen1_pure_lanes.py`, `test_gen1_purergb_{adapter,areas,client,codec,
  encounters,engine_sites,evos,moves_items_charmap,overlay,profile,rom_content,rom_scan,species,
  statics_trainers}.py`, `test_purergb_build.py`, `test_upr_{gen1_ini,pipeline,pure_pipeline,
  settings}.py`; extended `test_state.py`, `test_gen1_identity_and_collisions.py`,
  `test_gen1_facts_tables.py`, `test_e2e_duo_lane_isolation.py`, `test_make_release_manifest.py`,
  `test_verify_gen1_release_lanes.py`, `test_protocol_schema.py`.
- The pure unit tests resolve the pinned checkout at `gen1_foundation`'s default and skip only when
  it is absent (`f89d7fa`) — the release runner exports no environment.
- Live: inspect ×6 clean + ×6 overlay, engine-sequence ×3 pure titles, APEX ×2, receptionist,
  menu row, companion patch on the overlay; GBC FADE ON stress (243 warps, mailbox intact every
  frame, 0 bank-2 VBlanks).
- Duo: 15 scenarios on PureRed↔PureBlue (incl. `admit_randomized_new` on the fork jar), 15 on
  PureRed↔PureGreen, 3 on the overlay pairing.

### 3.10 Documentation — `3e9e69d`, `0ea9164`, `bbe7105`, `5e48fe5`, `81c7b88`, this sweep

`README.md` (Supported Games row, a pureRGB section, randomizer note), `docs/REFERENCE.md`
(Gen 1 pureRGB bullet, prerequisites), `docs/release_notes.md` (pureRGB section),
`docs/protocol.md` (acknowledged `key_change`), `docs/gen1_requirements.md` (pureRGB section),
`docs/gen1_engine_sites.md` and `docs/shared_runtime.md` (second-foundation notes),
`patch/README.md`, `patch/gen1/README.md`, `patch/gen1/purergb/README.md`,
`data/games/gen1_purergb/README.md`, `docs/purergb/{README,PLAN,CHANGELOG}.md`.

---

## 4. Behaviour changes visible outside pureRGB

Read this section if you only play vanilla.

### 4.1 Wire protocol (all games)
- Every `key_change` is now answered by `key_change_ack` or `key_change_rejected` in the same
  reply. Gen 3 ignores unknown commands; its local migration is unconditional, so a rejection
  (only reachable with colliding Gen 1 keys) leaves client and server disagreeing until the pair
  is retired — recorded in `docs/protocol.md` A18.
- A hello whose `rom_type` routes to a different `game_id` than the run's committed one, or a
  different artifact kind, is refused with `[x] MIXED GAMES` (previously logged and ignored).
- A randomized run's preparation contract binds the full ROM sha1 and the server compares it
  after the table fingerprint; a rand→clean swap is now refused with "tables match; sha1 …".

### 4.2 Vanilla Gen 1 client
- `Entry.build` accepts kind `named` — a companion-patched vanilla cartridge, which the production
  launcher had been crashing on (`071bff6`; the bug was introduced by `cc125f3` on this branch,
  so no shipped version was affected).
- `wild_begin` no longer stages a trainer id; `battle_begin` with no opponent is ignored;
  a fled wild battle is a failed encounter; an unsettled in-battle acquisition counts as the
  capture — all with vanilla duo receipts (18/18 on the `gen1_new` lane).

### 4.3 Vanilla data and packaging
- `data/games/gen1_rby/profile.json` gained, per title, a `derived` block (`ball_items`,
  `opp_id_offset`, `bag_capacity`, `base_stats_stride`, `dex_count`, `species_count`,
  `rival_trainer_ids` — the vanilla literals the client used to carry, now extracted from pret with
  source asserts, `6dcad63`) and one RAM symbol, `wBattleMonSpeed` (`0640660`). Every value equals
  the literal it replaced (`test_gen1_facts_tables.py`, `test_gen1_profile.py`). The vanilla pack
  also gained `gifts.json` (the Red prize table, emitted by `gen_gen1_gifts.py` for both
  foundations; read by the pure adapter and the area-map generator only — `gen1_rby/area_map.json`
  is unchanged). Nothing else in the vanilla pack changed.
- `tools/make_release.py --with-patch` bundles the three pure UPS files beside the vanilla
  Red/Blue ones.
- `tools/verify_gen1_release.py` has 19 lanes (7 new); a release verdict needs all of them.

### 4.4 Harness
- Every harness read of `$D000–$DFFF` goes through the flat `WRAM` domain on both foundations.
- `lua/tests/gen1_rb_*_inputs.lua` read their game facts from a table; vanilla behaviour is
  reproduced literal for literal (`test_gen1_facts_tables.py`).

---

## 5. Defects found by the live gates (all fixed)

| # | Found by | Defect | Fix |
|---|---|---|---|
| 1 | vanilla menu-row gate | any companion-patched vanilla cartridge asserted in `Entry.build` (`profile_named`) | `Entry.BASE_KIND.named = "clean"`, `Entry.pack_file` shared with the harness (`071bff6`) |
| 2 | overlay explode duo | harness read `wPartyCount == 0` for one frame (System Bus inside pureRGB's bank-2 palette loop) | `Entry.harness_bus_u8`, all harness reads through the flat domain (`afb4063`) |
| 3 | overlay explode duo | pureRGB's EXPLOSION only self-KOs below ⅓ HP | drop the battler under `max/3` (`afb4063`), then make it move first — the foe KO'd it before the explosion (`0640660`) |
| 4 | overlay menu-row gate | `wMaxMenuItem` on pureRGB is the last index, not a count | lane fact `MENU.START.max_minus_save` (`071bff6`) |
| 5 | APEX refusal gate | the refusal text was probed after the message box had closed; the overlay's SLINK row shifts the START-menu index | probe while the item routine runs; index from `profile.trade` (`2f258e7`) |
| 6 | pure `admit_randomized_new` | the oracle read a no-verdict player as admitted with an empty reason (B's rejection landed first) | require a real verdict (`3df8a70`) |
| 7 | release runner | 28 pure unit tests skipped without `SLINK_PURERGB_SRC`; unexplained skips fail the lane | resolve the checkout at the foundation default (`f89d7fa`) |
| 8 | release runner, cold lab routes | the pure deliberate lab loss stalled at −6 (0–1 damage a turn) | HP-driven loss with a Growl cap (`139c77b`, `13fdbdc`) |
| 9 | duo bag oracle | the link oracle read the bag at vanilla's SRAM offset on a pure pairing | `codec.for_foundation` (`ac8a30d`) |
| 10 | pure duos | drivers constructed without the lane facts silently used vanilla's (menus, whiteout map, reconnect OT) | facts handed to every constructor; oracles pairing-aware (`589a4b3`, `79a4e1f`, `20b2a60`, `35e05cf`) |
| 11 | documentation sweep | `/patcher`'s pure rows carried `patched_md5` literals from an earlier overlay build, so the page would have refused its own output | md5s sourced from the admission tables; pinned by `test_patcher_routes.py` (`91bbea6`) |
| 12 | final review (Codex, cx-6aacc4f1) | after `key_change_rejected` the server retires the pair under the OLD key while the cartridge already holds the NEW one, so the retirement `memorialize` found no mon ("key not in party") and the changed mon stayed alive | client `retired_alias`: retirement commands resolve to the physical key, replies keep the server's key; regression in `test_gen1_purergb_client.py` |
| 13 | final review (Codex) | the dead-key re-queue guarded `force_faint` and `memorialize` with one combined pending check, so a queued memorial suppressed the faint (and vice versa) | the two obligations are deduplicated separately (`server/state.py`); regression in `test_state.py` |
| 14 | final review (Codex) | `identify()` reported a modified pure ROM matching NEITHER anchor set as `rand` against the clean base, so the pipeline could contract a ROM the Lua gate refuses | neither anchor set → `RomScanError`; regression in `test_gen1_purergb_rom_scan.py` |
| 15 | final review (Codex) | changelog/release notes said the vanilla profile changed by one symbol only; it also gained the `derived` block (`6dcad63`) | wording corrected (§1, §4.3, release notes) |
| 16 | final review (Fable, limited context) | a clean Red beside a companion-patched Blue (kind `named`) was refused as MIXED artifact kinds — a vanilla regression for the optional patch | `named` counts as `clean` in the mixed-kind check (the patch is per cartridge, announced per player); regression in `test_state_key_change_ack.py` |
| 17 | final review (Codex, round 2) | the retirement alias resolved only in the deferred path and by key alone: `force_faint` dispatch/battle writes never saw it, and a duplicate of the new key in the party made the memorial ambiguous; a WRAM clear left a stale alias | one alias-aware `find_party_slot` (dispatch, battle, deferred) with a validated slot locator; the box module takes the slot hint; the alias map is cleared on WRAM clear |
| 18 | final review (Fable) | comments claimed a non-pinned pureRGB build "cannot take" the vanilla-header path; it can, and is then refused by the vanilla site verification | `run.lua`, `gen1_rom_scan.py` docstring, CHANGELOG §7 corrected |
| 19 | final review (Codex, round 3) | the retirement locator was a party slot: after a swap the duplicate of the new key sat at the recorded slot and would have been retired instead; the pending `key_alias` survived a WRAM clear, so a late rejection could re-create a retirement from the previous session | the locator is record evidence (nickname bytes + move set) that a swap cannot forge, refused when none or several records match; WRAM clear drops the pending alias and pending change too; the committed run kind is the base kind |

---

## 6. Evidence (gate receipts)

- G1 build: local + CI builds reproduce the three release ROMs byte for byte.
- G2 pack: 41 sites × 3 titles byte-verified; generator fact-check 120/120; vanilla pack
  byte-identical.
- G3a shared server: `slink-adapter-guard` clean, one independent review, Gen 3 suite then full
  suite green.
- G3 rules: pure duo 14/14 (PureRed↔PureBlue incl. the reconnect wrong-save leg), vanilla
  `gen1_new` 18/18 after the shared client changes, PureRed↔PureGreen, release lanes
  `profile-generated-purergb` / `inspect-purergb` / `apex-purergb`.
- G4 overlay: inspect ×6 on the overlay artifacts, receptionist (ABI windows at 2×), START-menu
  row + panel at the overlay mailbox, companion patch, APEX refusal, `trade_new` /
  `trade_decline_new` / `explode_new` on `gen1_pure_overlay`, GBC FADE stress.
- G5 randomizer: fork `load→save` 3/3 identical, T6 diff 0 stray, `admit_randomized_new` on the
  pure pairing, and the Manager UI leg (create a pure run → Randomizer finds the fork jar →
  preflight names both clean pure builds → pair built with fastest text off → the run's own
  launcher boots the randomized PureRed → `admission: admitted — cartridge matches the contract`).
- G6 full runner (`tools/verify_gen1_release.py`, no `--quick`, 19 lanes, three runs on
  2026-09-19): 15/19 → 18/19 → 17/19 lanes, every failure either fixed above or an RNG-class
  scenario retry (one-ball fixtures, rival AI move choice) that re-ran green on the same cut;
  union on `13fdbdc` green for all 19 lanes and all 51 duo cases. Independent read-only review of
  the release-facing diff: no confirmed defects.

---

## 7. Known limitations and what is not claimed

- Same bar as vanilla Gen 1: mechanisms proven on real cartridges on Route 1, **no full
  playthrough**; the four mid-game duo scenarios named in the plan (`transform_new`, `apex_new`,
  `npc_trade_new`, `daycare_new`) need routes past Route 1 and rest on the APEX live gates and
  model replays.
- One pinned pureRGB version (v2.7.6); any other version — older or newer — is refused: its sha1
  and anchors admit nothing, the vanilla-header fallback then fails the vanilla pack's engine-site
  verification, so it is never booted against the wrong addresses.
- CGB console mode only (DMG/SGB unsupported); pureRGB pairs only with pureRGB of the same
  artifact kind (clean↔overlay and vanilla↔pure are refused); Cable Club trades between a
  vanilla and a pure cartridge are not supportable.
- Explode Mode on pureRGB follows pureRGB's own rule (self-KO below ⅓ HP); the client stages
  the battler so the outcome is identical, the animation differs from vanilla's.
- The harness's RNG classes remain: one-ball fixtures miss ~10–15 % of throws, the rival AI's
  move choice varies; the runner retries within budgets, and `ball_gate_new` (cold boot) has one
  attempt by design.
- `SoulLinkState.load` rebuilds the adapter without `artifact_kind` (compensated in `server.py`);
  a rand↔clean pure pair is refused as MIXED GAMES (same-kind rule); receipts are scenario-keyed,
  so the same scenario must not run on two lanes at once.
- OMP (DeepSeek) was unavailable for the second half (OpenRouter credits); reviews ran on Sonnet.

---

## 8. Operating notes

```bash
# canonical build (RGBDS 1.0.3 + w64devkit, pinned; publishes .sym/.map only on sha1 match)
python tools/build_purergb_syms.py

# companion overlay → UPS + overlay pack files (needs the build above)
python tools/build_purergb_overlay.py

# UPR fork jar (clone + git am + JDK 17)
python tools/build_upr_fork.py --bootstrap

# regenerate the pure pack (any generator; --check exits 1 when stale)
python tools/gen_gen1_profile.py --foundation purergb
python tools/gen_gen1_profile.py --foundation purergb --kind overlay

# release gate (all 19 lanes; --quick stops before the emulator lanes)
python tools/verify_gen1_release.py

# one pure duo
python tools/e2e_duo.py --game gen1_pure --scenario link_new --lane R1
```

Environment: `SLINK_PURERGB_SRC` / `SLINK_PURERGB_ROMS` (default `.cache/purergb`),
`SLINK_PURERGB_OVERLAY_SRC` / `_ROMS` (default `.cache/purergb-overlay`), `SLINK_UPR_JAR`
(default search: repo, `.cache/slink-upr`, `.cache/upr`), `SLINK_GEN1_ROMS` /
`SLINK_GEN1_OVERLAY_ROMS` (live-gate title selection), `SLINK_PURE_WRONG_SAVE` (reconnect leg).
