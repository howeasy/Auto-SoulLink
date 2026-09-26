# P3 Gen 2 binders: independent adversarial review (gen2-R2, 2026-09-22)

Lease: reviewer gen2-R2, read-only on `codex/gen2-foundation` @ `17aeb62`; this file is the only write.
No repo code edited, nothing committed, no emulator. Evidence level of everything reviewed: SOURCE/MODEL.
Pins: pokecrystal `7a7881d0`, pokegold `656583c9` (clones in `.cache/gen2-build`, symbols in `data/gen2/*.sym`,
built ROMs `.cache/gen2-build/*/*.gbc`). Scratch reproductions lived outside the repo
(`<scratchpad>/r2tests/test_r2_findings.py`, both tests fail at HEAD as expected).

## Findings (ranked)

### F1 HIGH, CONFIRMED: two of the ten mail items pass the held-item gate (O-14)
- HEAD: `server/adapters/gen2_gsc.py:221`: `... and not row["constant"].endswith("_MAIL")`.
- Source (both repos): `data/items/mail_items.asm:1-12` lists `LITEBLUEMAIL` and `PORTRAITMAIL`
  (ids `0xB6`, `0xB7`; `constants/item_constants.asm:190-191`). Neither name ends in `_MAIL`. The engine
  decides mail with `ItemIsMail`, which looks the item up in `MailItems` (C `engine/pokemon/mail_2.asm:941-947`).
  Their attributes are `CANT_SELECT` only (C `data/items/attributes.asm:374-377`), so the `CANT_TOSS`
  bit does not catch them.
- Reproduced: `Gen2GSCAdapter(t).is_valid_held_item(0xB6)` and `(0xB7)` return True for
  crystal, gold and silver. The other eight mail ids return False.
- Failure: a 70-byte blob whose holder carries Lite Blue Mail or Portrait Mail passes
  `validate_party_blob`. The mon is carried without its mail struct (the party mail lives
  separately in `sPartyMail`), which breaks O-14 ("mail a recorded limit"). The receiver ends up with a
  mail item paired with whatever stale mail entry sits at that party index. No Lua-side barrier exists:
  `git grep -i mail HEAD -- lua/gen2 lua/gen2_write_safety.lua` finds nothing.
- Fix: take the mail set from the source `MailItems` list (or add an explicit `mail` flag to the
  generated item pack). Add one test that walks the whole `MailItems` list.

### F2 MEDIUM, CONFIRMED: phantom Headbutt tables in five Gold/Silver towns, the same wrong decode in three implementations
- HEAD: `tools/gen_gen2_encounters.py:198` skips only `TREEMON_SET_NONE`. `server/adapters/gen2_rom_scan.py:221`
  and `lua/gen2/rom.lua:200` decode every set from 1 to `NUM_TREEMON_SETS-1`. `gen2_gsc.py:353` presents
  every set except 0.
- Source, pokegold `engine/events/treemons.asm:98-102`:
  `assert TREEMON_SET_CITY == NUM_TREEMON_SETS - 1` then `cp NUM_TREEMON_SETS - 2` / `jr nc, .quit`.
  G/S `TREEMON_SET_UNUSED` (4) and `TREEMON_SET_CITY` (5) never yield an encounter, and in
  `data/wild/treemons.asm` they alias `TreeMonSet_None`. pokecrystal's `GetTreeMons` (`:100-105`)
  refuses only set 0, so Crystal is correct.
- Reproduced: in the gold and silver packs, `tree.sets` is `[1,2,3,4,5]`, and
  `encounter_table("new_bark_town")` contains `Headbutt Common` and `Headbutt Rare` (set 5). The towns affected are
  New Bark, Violet, Ecruteak, Mahogany and Blackthorn (`pokegold data/wild/treemon_maps.asm:28,30,35,36,38`).
- Why it survived: the generator, the Python scanner and the Lua reader all agree, so the
  differential tests (`test_gen2_rom_reader`, `test_gen2_rom_tables`) cannot see it. The fix belongs in all three:
  the disabled-set predicate is a per-title source fact and should be generated, not hard-coded as `== 0`.

### F3 LOW, CONFIRMED: fishing tables emitted for indoor maps, including a fish group the area cannot reach
- HEAD: `gen2_gsc.py:366-381` emits rod tables for every `area_map` row with a non-zero `fishing_group`.
- Source: map headers give indoor maps a fish group. For example `data/maps/maps.asm` (C :495-496, G :476-477) gives
  `ElmsLab`/`PlayersHouse1F` `FISHGROUP_SHORE`, while `NewBarkTown` (C :494) is `FISHGROUP_OCEAN`.
  `gen2_rom_scan.OPEN_OBLIGATIONS` itself lists `fishing_map_association` as OPEN.
- Reproduced: Crystal `new_bark_town` has 37 labels, including 6 map copies of each rod/time row. The
  `(ElmsLab)`/`(PlayersHouse*)` rows are SHORE fish, which cannot be caught anywhere in the area.
- Failure: the presentation (and any consumer that treats `encounter_table` as the catchable set) shows
  species that cannot be caught. Gate rod tables on a map having water, or keep them out of the table while the obligation is OPEN.

### F4 LOW, CONFIRMED (source quote): active-box plans lose their edit on reset-before-save, with no stated obligation
- HEAD: `lua/gen2/boxes.lua:144-146` records `copyback.mode="ENGINE_SAVEBOX_DEFERRED"`. The obligations at
  `:138-141` set `reassert_after_full_save` for memorial only.
- Source: Continue runs `TryLoadSaveFile` then `LoadBox` (C `engine/menus/save.asm:596-601`, G `:538-543`),
  which copies the current box's backing `sBoxN` over `sBox`. `_SaveGameData` then `SaveBox` (C `:275`, G `:282`)
  is the only place that syncs the other way.
- Failure: a deposit or withdraw planned against the current box writes `sBox` (bank 1). If the player
  resets before the next SAVE, the game silently reverts it, while the server believes the mon moved.
  Backing-box (inactive) plans do not have this problem. Suggest naming an explicit obligation for active plans
  (a full save before a reset, or re-assert on Continue), the way memorial already does.

### F5 MEDIUM (out of scope, CONFIRMED): HEAD unit suite red for the legacy Crystal adapter
- `pytest -k gen2` at HEAD: 17 failed, 1239 passed, all in `tests/unit/test_gen2_adapter.py::test_encounter_table_*`
  (legacy `Gen2CrystalAdapter`).
- Cause: `data/games/gen2_crystal/encounter_tables.json` was replaced by the new `gen2-encounter-tables-v1`
  pack (515c522/3769c4d). The legacy adapter still reads it (`server/adapters/gen2_crystal.py:202-205`,
  `_GEN2_ENCOUNTERS`), so `encounter_table()` now returns None. The live legacy Crystal route loses its
  encounter tables until the cutover. Either keep the legacy file under its own name or retire the tests now.

### F6 INFO: the earlier "status validated before HP policy" finding is RESOLVED; small residuals remain
- `lua/gen2/writes.lua:126-129` now submits status and HP as one `write_batch`. `lua/write_permit.lua:118-134`
  snapshots every span and runs `current()` (lifetime, bounds, allow, mapped, pointer_stable) over all of them twice
  before the first emission. A later-span policy refusal therefore cannot follow a status write
  (`test_second_faint_span_policy_refusal_never_emits_status`).
- Residual 1 (documented, tested): an I/O error after the status byte leaves status=0 with HP intact. That is the
  harmless direction (cured, not fainted), with no rollback claim. It does not matter.
- Residual 2 (PLAUSIBLE, design note): the battle `snapshot` (`mode`, `active_slot`, `battle_type`, `link_mode`)
  is caller-supplied and not re-read under the permit's hold (`writes.lua:113-121`), and the slot is not checked
  against `wPartyCount`. The active-battler refusal is only as good as `policy.authorize`. The
  future qualified policy must bind the snapshot to the held observation.

### Minor (no action required)
- Map-number bound differs: Python `_map` allows 1..255 (`gen2_rom_scan.py:120`), Lua `map_at` allows 1..254
  (`rom.lua:78`). No pinned map uses 255.
- `validate_party_blob` (`gen2_gsc.py:262`) accepts four zero moves and duplicate moves.
- Title branches exist only inside binders (`reads.lua:447` BATTLERESULT mask, `gen2_rom_scan.py:215-216,268`
  counts), and each is cross-checked against a generated constant. There is no `game_id` branch and no shared-module leak.

## Coverage (checked and found correct)
- **Codec** (`gen2_codec.py`): `DDDD:OOOO:SS` key; DV/HP-DV decode; the species-list marker is mandatory, and EGG is
  accepted only as the marker, never inferred; the 70-byte blob order is record, OT, nickname, matching `reads.lua`; box/party
  terminators; G/S backup checksum = the 16-bit sum of five spans, matching pokegold `SaveBackupChecksum`
  (`save.asm:495-536`); checksums stored little-endian; primary-then-backup recovery projection. Gender/shiny/CalcMonStat
  were spot-checked only (a previous review covered them).
- **Adapter**: `legend_<species>` is gated to the selected title's `InitRoamMons` species (C Raikou/Entei only,
  `wildmons.asm:493-524`; G adds Suicune `:488-529`), so Crystal `legend_245` is refused;
  `egg_hatch` maps to `gift_daycare`; `contest` maps to `national_park_contest`; egg pickup is never a capture; Johto badge order is
  bit-indexed (Mineral bit 4 maps to PokeAPI id 14, correct).
- **ROM readers**: base-stat layout (growth +22, egg groups +23, TM/HM +24); grass 47 / water 9 byte rows,
  level before species; probability tables; fish groups (1-based via `GetFishGroupIndex` `dec d`), `<=` threshold
  selection, time groups split at `NITE_F`; roamer initializer and RoamMaps graph; bank-local cursors. F2 is the only defect.
- **reads.lua**: exact field partition including the 2 aux bytes; egg marker; WRAM bank-window and injected
  bank-validity checks before and after each read; active box 1102 vs backing 1104 (padding untouched); pockets, TM/HM,
  badges, battle context (the BITMASK is the removal mask), battle_struct via generated symbols, and stat stages with min=1.
- **boxes.lua**: withdraw compaction byte-matches `RemoveMonFromPartyOrBox` (`move_mon.asm:1222+`, both repos),
  including the slot-19 `ld [hl], -1` special case and the stale tail; deposit appends; memorial refused only when
  `current_box == 13`; pre-first-save refusal; sealed plans (a weak-key registry, deep compare, retired before the gate,
  preflight may not mutate); untouched spans complete.
- **Checkpoint pack + gen2_write_safety**: every anchor byte-exact against the built ROMs (C `0x96974`/`0x9681f`,
  G/S `0x968a7`/`0x9675e`); the PC is the `call CheckAPressOW` inside `OWPlayerInput` (C `0x6983` calls `0x6999`, G/S
  `0x68b6` calls `0x68cc`); the stack word is the return address after `call OWPlayerInput` in `PlayerEvents` (C `0x6844`, G `0x6783`);
  all 15 predicate symbols and banks match `.sym`; `irq_anchor` is UNAVAILABLE (no DelayFrame inheritance);
  `runtime_authorized=false`; `check()` always returns false.
- **signals.lua**: script-label sites are refused and mnemonics must be CPU instructions; capture latches are set only after
  `TryAddMonToParty`/`SendMonIntoBox` (C `item_effects.asm`). `.return_from_capture` is also reached by
  break-free, tutorial and contest paths, which are all latchless and therefore refused. The roamer is classified via the capture latch plus
  `wBattleType == 5` at the PokeBallEffect return, never from the roamer cleanup. Crystal Suicune (type 12, scripted
  `loadwildmon`, `TinTower1F.asm:120`) is refused by both the type allow-list and the `BATTLESCRIPT_SCRIPTED_F` bit 7
  (`ram_constants.asm:166-167`; `randomwildmon` clears it for grass, fish, headbutt and rock smash). On the contest `.BoxFull` path
  (no insert, but caught data is still written to box slot 1) the latch is absent, so it is refused. The hatch `.next` visits every
  party slot, and the latch plus `wCurPartyMon` scope it. Reset, continue, new-game and battle-end clear latches. `S.new` refuses.
  Liveness depends on the documented contract that operation ids distinguish native attempts.
- **entry.lua**: `admit` always refuses (eligible=false), `build` returns nil, `build_candidate` needs `candidate_only`
  and re-hashes the ROM.
- **Extraction rule**: `write_permit.lua`, `gb_checkpoint.lua`, `gb_hook_binding.lua`, `hook_registry.lua` and
  `admission.lua` contain no Gen 2 or title knowledge. Every game fact reaches them as binder input.
- **Suites**: the 13 in-scope gen2 unit files passed 587/587 at HEAD. The full `-k gen2` run had only the F5 failures.

## Closure (gen2-R2, fix commit `bf2d5e1`, checked at HEAD `e0b38b7`)

`git diff bf2d5e1 e0b38b7` shows no changes in the Gen 2 server, Lua, pack or generator paths. The working tree was clean.
Both scratch reproductions (`r2tests/test_r2_findings.py`) now pass. The six affected unit files
(profile, rom_reader, rom_tables, items, encounters, boxes) passed 211/211.

- **F1 CLOSED (adapter).** `tools/gen_gen2_items.py` parses `MailItems` and checks it against the ROM
  (`verify_table(ctx, "MailItems", ...)`). Every title's `items.json` has `mail_ids` = 0x9E and 0xB5..0xBD (10 ids,
  10 `mail: true` rows). `gen2_gsc.py` reads `row["mail"]`, the pack loader requires it to be a bool, and all ten are refused on
  C, G and S.
- **F2 CLOSED.** `treemon_enabled_limit` is pinned independently, not only shared: it is parsed from the `GetTreeMons` `cp`
  operand, it must equal the source-asserted refused tail (fault-injected negatives in
  `test_treemon_enabled_limit_is_the_gettreemons_cp_bound`), and the generator checks the ROM bytes `FE <limit> 30`.
  I re-read those bytes myself: C `fe 08 30 10 a7 28`, G/S `fe 04 30 10 a7 28`. Reader tests also carry literal 8/4
  expectations. Residual (low): the Python and Lua ROM readers trust the profile value within `rock < limit <= count` and do not
  re-read the ROM gate. A tampered profile would pass both differentials, though the profile is covered by provenance.
- **F3 CLOSED as a labelled limitation.** Every rod row on all titles carries `map_association="UNQUALIFIED"`. The unreachable
  indoor rows are still presented (Crystal `new_bark_town` still has 37 labels). The obligation stays OPEN.
- **F4 CLOSED.** Active plans carry `reset_before_save="LOADBOX_REVERTS_ACTIVE_EDIT"` and
  `reassert_after_full_save=true`. Backing plans carry `NOT_APPLICABLE`/`false`, with a control test.
- **Pack regeneration** (structural diff against `92f5445`): items has only `/items/*/mail`, `/sentinels/*/mail` and `/mail_ids` added.
  The encounter packs have only `/tree/enabled_set_limit` added, and on G/S `tree.sets` shrinks from 5 to 3. Profiles have only
  `TREEMON_ENABLED_LIMIT` (constant and derived) plus the `treemons.asm` constant-source receipt added. Nothing else changed.

### New finding
- **N1 MEDIUM, CONFIRMED by grep: the mail gate is not enforced at any transfer boundary.** No shared server code calls
  `validate_party_blob` or `is_valid_held_item` (`git grep` over `server/` outside `adapters/gen*`). On the Lua side the
  flag appears nowhere: `boxes.lua` `mon()` and `writes.lua` `write_party_bytes` accept any held byte, and `wire.lua` only
  projects `held_item` (0..255). This is acceptable while native trade (P4) is unbuilt. The P4 transfer path must call the
  adapter gate, or the insertion binders need the mail set injected, before any held item is carried.
