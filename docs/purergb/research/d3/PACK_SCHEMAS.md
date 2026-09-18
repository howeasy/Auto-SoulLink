# M1 data-pack schemas — `data/games/gen1_purergb/`

Field shapes below were read directly from the *current* `data/games/gen1_rby/*.json` files at
`E:/Google Drive/SLink/.claude/worktrees/gen1-master-release-plan-6b4279` (2026-09-17) — every
sample under "Example (measured from the current vanilla pack)" is a real value pulled with
`python -c "json.load(...)"` against that tree, not invented. pureRGB-specific values (byte
patterns, addresses, constants) are cited from the plan
(`C:\Users\howar\.claude\plans\moonlit-napping-nautilus.md`) and marked **[PLAN]**; I have no
local pureRGB ROM/source checkout, so nothing pureRGB-side here is independently re-verified —
treat every pureRGB number as **UNVERIFIED against the built ROM** until M1's generators run and
their own asserts pass.

Generator/consumer citations for the *existing* vanilla files are taken from direct reads of
`server/adapters/gen1_rby.py` (lines 21-38 confirmed by reading the file) and the plan's B3 census
(`docs/gen1_reference` card `cx-112d5c7a`, folded into the plan at §11.2 "B3"); I mark which of
each pair I confirmed myself vs. which I'm carrying from B3's census as **[B3]**.

---

## 1. `profile.json` (extends `gen1-profile-v1`)

**Producer:** `tools/gen_gen1_profile.py` (exists today for R/B/Y; **[PLAN M1]** "edit: `TITLES`/
lock per foundation... derived `ball_items`, `opp_id_offset`, `bag_capacity`, `base_stats_stride`,
`dex_count`"). **Consumers:** `lua/gen1/entry.lua:39` (`load_json(...).titles[title]`, confirmed
by direct read), `server/adapters/gen1_rom_scan.py`, `server/adapters/gen1_rby.py` (module-level
lookups per **[B3]**), every `lua/gen1/*.lua` module via the `profile` table `entry.lua` builds
and threads through (confirmed: `reads.lua:44-51`, `rom.lua:12-14`, `writes.lua:48-49`,
`boxes.lua:44-53`, `signals.lua:184-186` all `assert(profile.ram)`/`assert(profile.derived)`).

Top-level shape (confirmed from the live file): `{generator, schema, source, titles}`. Per-title
shape (confirmed): `{derived, ram, repo, rom, rom_sha1, sram_bank, sym, variant}`.

### 1.1 `titles.<title>.derived` — extended fields

| Field | Type | Vanilla example (measured) | pureRGB value | Notes |
|---|---|---|---|---|
| `party_capacity` | int | `6` | `6` | unchanged struct geometry (§3.2 "sizes unchanged") |
| `party_struct_size` | int | `44` | `44` | unchanged |
| `box_capacity` | int | `20` | `20` | unchanged |
| `box_struct_size` | int | `33` | `33` | unchanged |
| `battle_struct_size` | int | `44` | `44` | unchanged |
| `name_length` | int | `11` | `11` | unchanged |
| `sram_box_stride` | int | `1122` | `1122` | unchanged |
| `sram_boxes_per_bank` | int | `6` | `6` | unchanged |
| `sram_box_banks` | int[] | `[2, 3]` | `[2, 3]` | unchanged (bank *numbers*, not addresses) |
| `ball_items` **(new)** | int[] | `[1, 2, 3, 4]` | `[1, 2, 3, 4, 5, 8]` **[PLAN §3.4]** | MASTER/ULTRA/GREAT/POKE ids 1-4; pure adds HYPER_BALL `$05` and Safari Ball-class `$08` |
| `opp_id_offset` **(new)** | int | `200` | `197` **[PLAN §3.5]** | `wCurOpponent - offset = trainer class`; `OPP_ID_OFFSET` constant |
| `bag_capacity` **(new)** | int | `20` (computed today as `(wPlayerMoney-wBagItems-1)/2`, not stored) | `30` **[PLAN §4 row 6]** | generator computes from `(wPocketAbraNick - wBagItems - 1)/2` on pure |
| `base_stats_stride` **(new)** | int | `28` | `35` **[PLAN §3.3]** | 27 vanilla fields (minus one pad byte) + 8 sprite-bank/alt-pic bytes on pure |
| `dex_count` **(new)** | int | `151` | `151` **[PLAN §3.3]** | national dex ceiling; dex `0` = MISSINGNO/hole on both |
| `species_count` **(new)** | int | `190` | `190` **[PLAN §3.3]** | internal-index ceiling (`PokedexOrder` table size) |
| `nondex_species` **(new)** | int[] | `[]` | `[31,50,52,56,86,94,115,134,146,172,174,175,181]` (decimal forms of `$1F,$32,$34,$38,$56,$5E,$73,$86,$92,$AC,$AE,$AF,$B5` **[PLAN §3.3]**) | internal indices whose stats live in `NonDexMonsBaseStats`, not `BaseStats` |
| `dex_missingno` **(new)** | int | absent (n/a on vanilla) | `181` (`$B5`) **[PLAN §3.3]** | the one `nondex_species` entry that is also a *playable species*, not a form/spirit |

**Generator obligation (M1 exit gate):** every `nondex_species` entry must be a source-assert
against `constants/pokemon_constants.asm`'s named constants (`SPIRIT_TORCHED`, `MISSINGNO`, …),
never a bare hex literal in the generator — this is the same "(b) needs a pureRGB source-text
assert" discipline the plan's assumption matrix applies to every (b)-class row.

### 1.2 `titles.<title>.admission` **(new block)**

Replaces the single scalar `rom_sha1` (still kept for backward compat / display) with a full
admission table so hash-first detection (client brief §2) has one place to look per foundation
pack, and so overlay/randomized artifacts can be admitted without a second file format.

```json
"admission": {
  "2e94d09c1e16a57eb079404c030f26fdeeac949d": {
    "title": "PureRed", "kind": "clean", "profile_id": "gen1_purergb_purered_v2.7.6"
  },
  "d419fe244fa17196f7df46ddab47c840e7573652": {
    "title": "PureBlue", "kind": "clean", "profile_id": "gen1_purergb_pureblue_v2.7.6"
  },
  "fe4c63a67c8b28770916cc7b1788f9eeb04ccf02": {
    "title": "PureGreen", "kind": "clean", "profile_id": "gen1_purergb_puregreen_v2.7.6"
  }
}
```

| Field | Type | Notes |
|---|---|---|
| key | lowercase 40-hex-char string | full-ROM SHA-1; **[PLAN §1]** gives PureRed `2e94d09c…`, PureBlue `d419fe24…`, PureGreen `fe4c63a6…` (measured twice by the plan's coordinator: BPS-applied release ROMs and a byte-identical local canonical build — both stated to match) |
| `.title` | string | one of `PureRed`/`PureBlue`/`PureGreen` — feeds `Entry.ROM_TYPE` (client brief §2) |
| `.kind` | enum `clean\|overlay\|rand\|rand_overlay` | **[PLAN A3]**; only `clean` rows exist from M1, `overlay` added by M3, `rand`/`rand_overlay` by M5 |
| `.profile_id` | string | opaque generator-stamped id, used for the ledger and for `rom_contract.json` provenance binding (**[PLAN A3]**: "for randomized artifacts the preparation contract must bind the final output sha1 plus provenance... UPR fork version, settings hash") |

**Producer:** new `tools/gen_gen1_admission_profiles.py` (**[PLAN M1]**: "whole-ROM sha1/sha256
catalog = the A3 admission table"). **Consumer:** `lua/gen1/entry.lua` (client brief §2, new
hash-first `Entry.detect_title`/`Entry.build` logic) and, server-side, `server/server.py`'s
admission check (**[PLAN B2]**: "admission: contract fingerprint only, `rom_sha1` recorded by
the Manager but never compared" — today's gap this table is meant to close, out of this brief's
Lua scope but the schema must serve both consumers identically).

### 1.3 `titles.<title>.checkpoint` — **not added here**

The overworld write-checkpoint predicate stays in the separate `write_checkpoint.json` file
(§3 below), matching today's layout (confirmed: `profile.json` has no `write_safe`/checkpoint
keys at all; `write_checkpoint.json` is a sibling file `entry.lua:41` loads independently). Do
not fold it into `profile.json` — keeping it separate lets the M1 exit gate ("any generated site
whose `expected_hex` is not found... is a reviewed change") diff the checkpoint file on its own
without profile churn.

### 1.4 `sites`/`trade` blocks — **live in other files, not `profile.json`**

`sites` lives in `engine_signals.json` (§2); a new top-level `trade` block (mailbox/service/
receptionist_hook, per the client brief §0) belongs in the **overlay** artifact's own generated
profile, produced by re-running M1's generators against the M3 overlay build (**[PLAN M3]**:
"a step 're-run the M1 generators on the overlay build' producing the overlay profile block,
sites, checkpoint and admission rows") — it does not exist in the base `gen1_purergb` pack this
document otherwise describes, only in a second `gen1_purergb` *overlay*-kind profile entry keyed
by its own admission row.

---

## 2. `engine_signals.json`

**Producer:** ported `tools/gen_gen1_engine_signals.py` (**[PLAN M1]**: "port from `R/`, two
assert sets" — the vanilla lane currently has no such generator; sites are hand-pinned via
`tools/pin_gen1_site.py`, confirmed present in `ls tools/`). **Consumer:** `lua/gen1/signals.lua:190-233`
(`S.new`'s load-time anchor check and per-site `on_bus_exec` registration, confirmed by direct
read) via `lua/gen1/entry.lua:40` (`load_json(...).titles[title].sites`).

Top-level shape (confirmed): `{schema, sha256, titles}`. Per-title: `{sites: {<kind>: {...}}}`.

### 2.1 Per-site fields (confirmed shape, `titles.red.sites.wild_begin`)

```json
"wild_begin": {
  "address": 28555, "bank": 15, "capture_offset": 5,
  "expected_hex": "3E01EA57D0CD016B", "rom_offset": 257931, "symbol": "InitWildBattle"
}
```

| Field | Type | Notes |
|---|---|---|
| `symbol` | string | pret/pureRGB label name, source-asserted by the generator |
| `bank` | int | ROM bank the hook must be executing in (`signals.lua:204`: `io.read_u8(ram.hLoadedROMBank) ~= site.bank` is a load-bearing false-hit guard — confirmed live-necessary at **[PLAN §11.2 Live 2]**, "`RemoveFaintedPlayerMon`'s address also fired... in ROMX bank `$01`") |
| `address` | int | flat-bank-relative address (bank-local, e.g. `$0000-$3FFF` window math) where `capture_offset` is added to form the PC the hook fires at |
| `capture_offset` | int | offset from `address` to the exact instruction whose PC identifies the event (`signals.lua:207`: `local pc = site.address + (site.capture_offset or 0)`) |
| `rom_offset` | int | flat ROM-file byte offset (bank×0x4000 + address-0x4000-style math already resolved) used for the load-time `expected_hex` check against the `"ROM"` domain |
| `expected_hex` | uppercase hex string, even length | the exact bytes at `rom_offset`; re-checked both at load (`signals.lua:192-193`) and at every fire (`signals.lua:210-212`) |
| `target_symbol` **(new, client brief §0)** | string, optional | names the WRAM symbol (or `"HL"`/`"registers"` sentinel) the site's `point` function should read as its primary subject, for sites whose point-of-interest is a CPU register rather than a fixed symbol (`apex_preflight`/`apex_commit`) |

### 2.2 Full pure site list (M1 bullet; **[PLAN]**, all UNVERIFIED against the built ROM until
M1's own generator + S1-style byte verification runs — S1 already caught 3/40 predicted offsets
wrong on a first pass, so treat every offset below as a *research-phase estimate*, not a fact)

Kept sites (existing kind, pureRGB-specific `symbol`/offsets):

| kind | symbol | offset | bank (built `.sym`) |
|---|---|---|---|
| `wild_begin` | `InitWildBattle` | `+$13` (after `MissingNoInit`/`PreventInvalidEncounters`) | `0F` (`InitWildBattle 0F:6F37`) |
| `battle_loop_head` | `MainInBattleLoop` | `+6` (3 extra opening bytes vs. vanilla's `+0`) | `0F` |
| `battle_begin` (trainer staging) | `InitBattleCommon`/`_InitBattleCommon` | `+$48` (`3E 02`) staging / `+$4D` (S1-corrected: bytes at `+$48` were actually `CD C1 00 5D 54 E5`, not `3E 02` — **[PLAN §11.2 Live 2, S1]**, "the offset is wrong and must come from the generator, not from source-counted arithmetic") | `0F` |
| `save_witness` | `SaveMenu.save` | `+3` (now `call ClearTextBox`, S1-corrected from a different +3 assumption) | `1C` |
| `bag_received` | `AddItemToInventory_.done` | `+8` | `03` |
| `poison_faint` | `ApplyOutOfBattlePoisonDamage.noBorrow` | `+4` | `03` |
| capture `party_begin`/`party_end` | `ItemUseBall.skipShowingPokedexData` | `+34`/`+37` | `03` |
| capture `box_begin`/`box_end` | `ItemUseBall.sendToBox` | `+3`/`+6` | `03` |
| PC `deposit` | `BillsPCDeposit` | `+$4B` (`call WaitForSoundToFinish`) | `33` |
| PC `withdraw` | `BillsPCWithdraw` | `+$67` | `33` |
| PC `release` | `BillsPCRelease` | `+$70` | `33` |
| PC `changebox` | `ChangeBox.yes` | `+$35` (`call SaveGameData`; S1-corrected — a prior `+$38` guess was one instruction too late) | `1C` |
| `evolve` | `Evolution_PartyMonLoop.skipfix_end` | `+$3C` (bytes `77 E5 6B 62 18 01`) | `2C` |

New kinds (M1/M2-b, no vanilla equivalent):

| kind | symbol | offset | point-of-interest | bank |
|---|---|---|---|---|
| `transform` | `ChangePartyPokemonSpecies` | `+0` | `wWhichPokemon`, `wCurPartySpecies`, old HP (store site `+$4A`/`+$4C`) | `35` (`ChangePartyPokemonSpecies 35:65B2`) |
| `apex_preflight` | `ItemUseMedicine.useApexChip` | `+$0F` (= `.setDVs`, `03:5B43`) | `HL` / `wUsedItemOnWhichPokemon` — **not** `wWhichPokemon` (restored to its pre-menu value earlier, `item_effects.asm:1026-1028`) | `03` |
| `apex_commit` | same routine | `+$11` (both DV bytes written, before `call .recalculateStats` at `+$13`) | same target as preflight | `03` |
| `npc_trade_remove` | `InGameTrade_DoTrade` | `+$7B` | `wWhichPokemon` (pre-removal slot) | `1C` (`InGameTrade_DoTrade 1C:54CC`) |
| `npc_trade_done` | same routine | `+$89` (`ClearScreen` call) | readback at `wPartyCount-1` | `1C` |
| `daycare_withdraw` | `DaycareGentlemanText.enoughMoney` | `+$27` (`call MoveMon` after `ld a, DAYCARE_TO_PARTY`) | `wDayCareMon`, readback at `wPartyCount-1` | `15` |
| `cable_trade_remove`/`cable_trade_add` | `TradeCenter_Trade.doTrade` | `+$77`/`+$9D` (S1-corrected: an earlier `+$A0` guess was the instruction *after* the call) | party slots | `01` |
| `cable_partial_save` | `TradeCenter_Trade.tradeCompleted` | `+$2C` (`callfar SavePartyAndDexData`, bytes `21 80 78 06 1C C7`) | — | `01` |
| `starter` | `OaksLabMonChoiceMenu.continue` | `+$23` (`call AddPartyMon`) | party append | `07` |

All 7 `SaveGameData` callers (in-game SAVE, Change Box, OPTIONS full save, Cable Club
receptionist, Hall of Fame, updater ×2 — **[PLAN M1]**) must be individually enumerated in the
generated `engine_signals.json` (or a sibling `save_flush_sites` list) so the SaveRAM flush the
client already performs at `save_witness` (`client.lua:795-796`) runs after every one, not just
the in-game SAVE path.

**Generator obligation (exit gate, unchanged from vanilla's own rule):** "any generated site
whose `expected_hex` is not found at `rom_offset` in the built title ROM, or any source-text
assert failing... → the row is a reviewed change, not a warning" (**[PLAN §6 exit gates]**).

---

## 3. `write_checkpoint.json`

**Producer:** new `tools/gen_gen1_write_checkpoint.py` (**[PLAN M1]** — the RC's tool of the same
name only re-exports hand-written Lua profiles and is explicitly *not* this generator; today's
vanilla `write_checkpoint.json` is hand-pinned, not generated, per **[B2]**/`profile.json`'s
`generator` field convention not applying here). **Consumer:** `lua/gen1_write_safety.lua`
`M.check` (confirmed by direct read, lines 6-71) via `lua/gen1/entry.lua:41`.

Top-level shape (confirmed): `{blue, red, yellow}` (no wrapper object, unlike the other files —
keep this shape for `{purered, pureblue, puregreen}` to match, or normalize during M1; either is
a one-line change to `entry.lua:41`'s lookup).

### 3.1 Per-title shape, extended (`write_checkpoint.red`, confirmed content + new fields)

```json
{
  "BATTLE_FLAG_ADDR": 53335, "FONT_LOADED_ADDR": 53188, "JOY_IGNORE_ADDR": 52587,
  "write_safe": {
    "version": "gen1-main-loop-v1",
    "irq_vector": 64, "vblank_entry": 8228, "vblank_flag": 65494,
    "delay_frame": 8367, "overworld_loop": 1023, "overworld_loop_less_delay": 1026,
    "link_state": 53547, "link_none": 0,
    "serial_status": 65450, "disconnected_serial": 255,
    "entering_cable_club": 52295, "stack_min": 57088, "stack_end": 57343,

    "delay_frame_bytes": "3E01E0D6763EFDE0D6", "_comment_delay_frame_bytes": "NEW — hex bytes at delay_frame; vanilla's equivalent today is the Lua-hardcoded {0x3E,1,0xE0,vblank_flag,0x76,0xF0,vblank_flag,0xA7} in gen1_write_safety.lua:39-40",
    "overworld_loop_call_bytes": "CD2F20", "_comment_overworld_loop_call_bytes": "NEW — vanilla is a 3-byte 0xCD (call) instruction; pureRGB is a 1-byte 0xD7 rst _DelayFrame ($10) per constants/rst_vectors.asm and macros/farcall.asm#L8-31 [PLAN]",
    "resume_offset": 5, "_comment_resume_offset": "NEW — offset from delay_frame where [SP] must point; vanilla 5, pureRGB 24 (measured live, PLAN Live)",
    "caller_offsets": [3, 3], "_comment_caller_offsets": "NEW — offsets from overworld_loop / overworld_loop_less_delay for [SP+2]; vanilla [3,3], pureRGB [1,1] (same target address, since rst is 1 byte)",
    "delay_frame_bank_addr": 0, "_comment_delay_frame_bank_addr": "NEW — wDelayFrameBank symbol; 0 (falsy) on vanilla means 'no such check', must become a real address once the generator adds it even for vanilla",
    "delay_frame_bank_expected": 0, "_comment_delay_frame_bank_expected": "NEW — required value at delay_frame_bank_addr",
    "wram_bank_register_allowed": [1], "_comment_wram_bank_register_allowed": "NEW — allowed io.register(\"WRAM BANK\") values at the checkpoint; vanilla measured as 1 in practice (UNVERIFIED — confirm via the existing vanilla live gate before shipping), pureRGB measured live as {0,1} (PLAN Live: \"WRAM BANK == 1 on all 11,947 VBlanks\" for pure; the {0,1} allowance in the plan's row-12 text covers pureRGB's own broader observed set)"
  }
}
```

The `_comment_*` keys above are illustrative only — the real generator should not emit
free-text comments inline; they're included here so a reader can see which fields are additions
without cross-referencing this document against a diff. `M.VERSION` in
`lua/gen1_write_safety.lua:4` (`"gen1-main-loop-v1"`) gates on `write_safe.version` (confirmed:
`M.check` line 9, `p.version ~= M.VERSION`) — bump to `"gen1-main-loop-v2"` once these new
required fields land, so an old cached profile fails closed instead of reading `nil`.

### 3.2 pureRGB values for the new fields (**[PLAN §3.1, §11.2 Live]**, UNVERIFIED against the
built ROM's exact byte sequence — the plan gives the *structure* of `DelayFrame`'s body but not
its literal opcode bytes)

| Field | pureRGB value | Source |
|---|---|---|
| `resume_offset` | `24` | measured live: `[SP] == DelayFrame+24` (the `nop` after `halt`), 9316/~9500 overworld VBlank samples |
| `caller_offsets` | `[1, 1]` | measured live: `[SP+2] == OverworldLoop+1 == OverworldLoopLessDelay` (same address, since `rst _DelayFrame` is a 1-byte call site and `OverworldLoopLessDelay` is literally the next byte) |
| `delay_frame_bank_expected` | `0` | measured live: `wDelayFrameBank == 0` at the checkpoint |
| `wram_bank_register_allowed` | `[0, 1]` | measured live: `WRAM BANK ∈ {0,1}` (plan text; the live probe log itself only reports observing `1`, "WRAM bank at VBlank entry was 1 on all 11,947 VBlanks" — the `{0,1}` allowance in row 12's prose is broader than what was directly observed and should be re-confirmed, not copied blind) |
| `overworld_loop_call_bytes` | 1-byte `rst _DelayFrame` opcode, **not** a 3-byte `call` | `OverworldLoop:: rst _DelayFrame` (`P:home/overworld.asm#L28-L33`) |
| `delay_frame_bytes` | 31-byte body, `halt` at `+23`, includes `ld a,[hLoadedROMBank]`/`ld [wDelayFrameBank]`/`call home_PrepareOAMData` before the halt | `P:home/vblank.asm#L89-L118` (full body quoted in the plan's §3.1) |

Also required (shared with `checkpoint{...}` field for the write-safety WRAM predicate the task
brief names): `[SP]==DelayFrame+24`, `[SP+2]==OverworldLoop+1`, `wDelayFrameBank==0`, `wram_bank
in {0,1}` — these four are exactly `resume_offset`, `caller_offsets`, `delay_frame_bank_expected`,
`wram_bank_register_allowed` above; there is no separate `checkpoint` top-level block beyond
`write_checkpoint.json` itself (see §1.3 — do not create a duplicate schema).

**Generator obligation (exit gate):** "the inspect gate on a pure battery-save fixture... Lua
decode ≠ PYDEC, or the checkpoint never reached → the profile/checkpoint derivation is wrong"
(**[PLAN §6 M2 exit gate]**).

---

## 4. `area_map.json`

**Producer:** new `tools/gen_gen1_area_map.py` (**[PLAN M1]**: "the old JSON→Lua converter of
that name was deleted in `21ff0d7`; this one derives `area_map.json` from
`constants/map_constants.asm` + `data/wild/`, applying vanilla's dungeon-collapse rules per
U10"). **Consumer:** `lua/gen1/client.lua:170-174` (`area_of(map)`, confirmed by direct read:
`local a = area_map[tostring(map)]; if a then return a.area_id, a.name end`) via
`entry.lua:42`; server-side `server/adapters/gen1_rby.py:26-29` (confirmed: `_AREAS =
_json("area_map.json"); _AREA_BY_MAP = {int(map_id): row["area_id"] ...}`).

Shape (confirmed, keyed by decimal map-id string): `{"<map_id>": {"area_id": str, "name": str}}`.
Example (measured): `"0": {"area_id": "pallet_town", "name": "Pallet Town"}`.

| Field | Type | Notes |
|---|---|---|
| key | decimal string | `wCurMap` byte value, as a string (Lua's `tostring(map)` / Python's `int(map_id)`) |
| `.area_id` | string, snake_case | stable identity used everywhere else (server dead-zone/resolved-area keys, `no_catch`/`capture` payloads) |
| `.name` | string | display name |

**pureRGB rule (U10, confirmed **[PLAN §0 owner decisions]**):** area granularity follows
vanilla's dungeon-collapse convention — Mt. Moon, Rock Tunnel, Seafoam, Victory Road, Pokémon
Tower, Safari quadrants stay one area each; every other map with a wild/fishing table is its own
area. pureRGB's 18 new maps (**[PLAN §3.5]**: `POWER_PLANT_ROOF $45`, `VERMILION_FITNESS_CLUB
$4B`, `CELADON_BACK_ALLEY $4E`, `CERULEAN_*_HOUSE $69-$6B`, `VIRIDIAN_SCHOOL_HOUSE_B1F $6D`,
`BILLS_GARDEN $6E`, `SECRET_LAB $6F`, `POKEMON_TOWER_B1F $70`, `CHAMP_ARENA $72`,
`DIAMOND_MINE $73`, `CINNABAR_VOLCANO $74/$75`, `TYPE_GUYS_HOUSE $AD`,
`FUCHSIA_TREE_DELETER_HOUSE $CC`/`FOSSIL_GUYS_HOUSE $CD`, `CERULEAN_BALL_DESIGNER $E7`) each get
an entry only if they carry a wild/fishing table per decision 4 ("every map with a wild/fishing
table is an area"); `POKEMON_TOWER_B1F $70` explicitly collapses into the existing
`pokemon_tower` area per U10, not a new `pokemon_tower_b1f` id.

**Example row this pack needs that vanilla's schema has never had to represent:** a
renumbered-but-same-name city (`SAFFRON_CITY` moves to `$07` per **[PLAN §3.5]**) — the schema
itself needs no new field for this (the key is already the numeric id, which simply differs),
but the *generator* must never assume vanilla's map-id numbering when deriving `area_id` strings
from `constants/map_constants.asm`.

---

## 5. `static_encounters.json`

**Producer:** `tools/gen_gen1_statics.py` (exists today per `ls tools/`; **[PLAN M1]**: "existing
source parser; add foundation paths and pureRGB's static-animation entry
`engine/battle/volcano_battle_init.asm`"). **Consumer:** `lua/gen1/client.lua:638-648`
(confirmed: `local ids = self.statics and self.statics[tostring(map_id)]` inside the
`wild_begin`/`battle_begin` branch, used to reclassify a wild encounter as `static_<map>_<dex>`)
via `entry.lua:44` (`.statics`); **[PLAN B3]** notes the server keeps a *separate*
`_STATIC_SITES` table (`gen1_rby.py`) rather than reading this file — "loaded by the client
only."

Shape (confirmed): `{schema, source, statics, cites}`, with `statics` keyed by decimal map-id
string → array of internal species ids. Example (measured): `"23": [132]`, `"27": [132]` (both
Cinnabar Mansion floors' Ditto, internal id 132 — a plausible read given the vanilla static
roster, **UNVERIFIED which specific static this id maps to without cross-checking
`species_index.json`**).

| Field | Type | Notes |
|---|---|---|
| key | decimal string | `wCurMap` value |
| value | int[] | internal species ids that are static (fixed) encounters on that map |

**pureRGB additions (**[PLAN S2, §3.3]**, all species ids by *internal index*, not dex):**
Snorlax ×2 (L40), MissingNo (L120), Restless Soul (L30), Viridian tutorial Weedle (L5) as
plain `ld a,SPECIES`/`ld [wCurOpponent]` pairs; Mewtwo/Moltres/Zapdos/Articuno/Cloyster as
script-structured statics (offsets not yet derived — **UNVERIFIED**); Voltorb/Electrode
(Power Plant) are **now trainer battles**, not statics, in pureRGB (`PowerPlant.asm:268-282`)
— the generator must *drop* them from this table rather than port them, which is itself a
useful M1 regression check (a static that disappears between foundations should fail loudly if
the generator's map/species list is copy-pasted from vanilla instead of re-derived from
pureRGB's own scripts). Ghost Marowak (Pokémon Tower B1F rewrite) and the Cinnabar Volcano
statics (Volcanic Magmar transform site) also need entries once their exact
`ld a,SPECIES`/script offsets are located — flagged in the plan as "script-structured (offsets
not derived)"; mark these `UNVERIFIED` in the generated file's own `cites` array rather than
guessing an offset.

---

## 6. `species_index.json` (extended)

**Producer:** new `tools/gen_gen1_species.py` (**[PLAN M1]**: "keyed by internal index —
`PokedexOrder` dex, name, base-stat types from `BaseStats`/`NonDexMonsBaseStats` with the
35-byte stride and the NonDex index for withdraw rebuilds, `base_species` for forms, transform
edges from `ChangePartyPokemonSpecies` callers, new type ids/names"; today's vanilla file is
"curated," per **[B3]**, not generated at all — this is a genuine new generator, not a port).
**Consumer:** `lua/gen1/rom.lua:17-25` (`self.natdex`, reads the ROM's `PokedexOrder` table
directly at runtime rather than this JSON — confirmed by direct read); server-side
`server/adapters/gen1_rby.py:31-32` (confirmed: `_INDEX_JSON = {int(key): int(value) for key,
value in _json("species_index.json")["index_to_national"].items()}`).

Current vanilla shape (confirmed): `{_comment, index_to_national, national_to_index}`, both
maps of decimal-string-key → int. Example (measured): `index_to_national["1"] == 112`
(internal index 1 → national dex 112, i.e. Rhydon is internal slot 1 in R/B/Y's internal
ordering — a well-known pret fact, consistent with the measured value).

### 6.1 Extended per-entry shape for pureRGB

The plan's brief for this deliverable asks for a richer per-species record than the current
flat int→int maps support (`classification`, `base_species`, `types`, `stats_source`). Proposed
schema — keep `index_to_national`/`national_to_index` as-is for backward compatibility with the
existing consumers above, and add a new keyed object:

```json
"species": {
  "31": {
    "dex": 0, "name": "Spirit (Torched)", "classification": "form",
    "base_species": 12, "types": ["Fire", "Ghost"], "stats_source": "NonDex:0"
  },
  "1": {
    "dex": 112, "name": "Rhydon", "classification": "ordinary",
    "base_species": 1, "types": ["Ground", "Rock"], "stats_source": "BaseStats:111"
  }
}
```

| Field | Type | Example | Notes |
|---|---|---|---|
| key | decimal string | `"31"` | internal species index |
| `.dex` | int | `0` | national dex (`0` for MISSINGNO/forms/spirits/unused, per **[PLAN §3.3]** "`MISSINGNO` is a species only at internal `$B5`; every other `PokedexOrder` zero is an unused slot") |
| `.name` | string | `"Spirit (Torched)"` | display name; forms/spirits get pureRGB's own names, base species keep vanilla names |
| `.classification` | enum `ordinary\|form\|missingno\|spirit\|unused` | `"form"` | **new concept**, not present in any current file; `unused` = a `PokedexOrder` zero-dex slot that is genuinely nothing playable (not MISSINGNO, not a form) |
| `.base_species` | int (internal index) | `12` (Butterfree, say) | the species this form/spirit's identity/evolution-family membership rolls up to for rules purposes (species-clause, evolution family); **UNVERIFIED exact base-species mapping per form — must come from the `ChangePartyPokemonSpecies` caller census, `P:engine/pokemon/change_mon_species.asm` per-script transform table, cross-referenced against §3.3's per-form list** |
| `.types` | `[string, string]` | `["Fire", "Ghost"]` | the form/spirit's **own** default types, per **[PLAN §3.3]**: "Forms carry their own default types (Floating Magneton `ELECTRIC, FLOATING`... Volcanic Magmar `FIRE, MAGMA`)" — types come from the new type-id space (`TYPELESS $06`, `CRYSTAL $09`, `BONEMERANG_TYPE $0A`, `TRI $11`, `FLOATING $12`, `MAGMA $13`), not vanilla's 15-type table |
| `.stats_source` | string `"BaseStats:<i>"` or `"NonDex:<i>"` | `"NonDex:0"` | which 35-byte-stride table + zero-based record index holds this species' stats — this is the field `lua/gen1/rom.lua`'s extended `self.base_stats`/`self.base_stats_for` (client brief §5.1) needs to stop special-casing Mew as the only "apart" record |

**Consequence for the client brief's §5.1 refactor:** `rom.lua`'s `self.base_stats(dex)` can key
purely off `stats_source` once this table exists, rather than the current
`dex==151→MewBaseStats/else BaseStats` two-way branch — but that refactor should read
`species_index.json`'s `stats_source` at *generator* time (baking the resolved flat ROM offset
into `profile.json`'s `rom` table, the same way `profile.json.titles.red.rom.BaseStats` already
gives a `{addr,bank,flat}` triple) rather than having the Lua client parse `stats_source` strings
at runtime — keep the runtime path dumb (a flat address lookup) and the cleverness in the
generator, consistent with how `rom.lua` already treats every other ROM symbol as a pre-resolved
`{bank,addr,flat}` record.

---

## 7. `evolutions.json` (+ transform edges)

**Producer:** `tools/gen_gen1_evos.py` (exists today; **[PLAN M1]**: "pointer-table walk over
`EvosMovesPointerTable`; asserts 76 entries / 72 edges / 79 families with Eevee's four in one
family"). **Consumer:** `server/adapters/gen1_rby.py:33` (confirmed:
`_FAMILY = {int(key): int(value) for key, value in _json("evolutions.json")["family"].items()}`);
`lua/gen1/client.lua` does not read this file directly (evolution is detected by the `evolve`
engine signal, not by consulting the evolution table — confirmed, no reference to
`evolutions.json` anywhere in `lua/gen1/`).

Shape (confirmed): `{_source, evolutions, family}`; `evolutions` maps internal-species-string →
`int[]` (possible evolved forms); `family` maps internal-species-string → int (family id).
Example (measured): `evolutions["1"] == [2]`, `evolutions["2"] == [3]`, `family["1"] == family["2"]
== family["3"] == 1`.

### 7.1 pureRGB additions

- **Trade-evolution level-37 entries** (**[PLAN §3.3]**): pureRGB's
  `data/pokemon/evos_moves.asm` gains four new level-37 evolution rows for the classic
  trade-evolution species (Kadabra/Machoke/Graveler/Haunter-equivalents by internal index) —
  these are ordinary `evolutions`/`family` entries, no schema change, just more rows and a
  changed evolution *method* the generator must also capture (see next bullet).
- **`method` field (new, needed regardless of pureRGB since the current schema has no evolution
  *method* at all — UNVERIFIED whether the vanilla generator already drops this on the floor
  deliberately because the client signal-detects evolution rather than predicting it; add it
  for completeness and cross-checking):**
  ```json
  "evolutions": { "1": [{"to": 2, "method": "level", "at": 16}] }
  ```
  This is a schema *widening* (array of objects instead of array of ints) — **flag as a breaking
  change to `gen1_rby.py:33`'s consumer if adopted; the lazier, fully backward-compatible
  alternative is a parallel `evolution_methods` map and leave `evolutions`'s int-array shape
  alone.** Recommend the parallel-map approach unless a concrete M2 consumer needs inline
  method data.
- **Transform edges (new top-level key, required by this deliverable's spec):**
  ```json
  "transforms": [
    { "from": 12, "to": 31, "site": "CinnabarVolcanoWest", "trigger": "script" },
    { "from": 95, "to": 172, "site": "DiamondMine", "trigger": "script" }
  ]
  ```
  One row per **[PLAN §3.3]**'s 10 `ChangePartyPokemonSpecies` call sites across 8 scripts
  (`CinnabarVolcanoWest#L152` Magmar→Volcanic, `DiamondMine#L390,L448` Onix→Hardened,
  `PowerPlant#L602` Magneton→Floating, `SilphCo1F#L225` Weezing→Floating,
  `SeafoamIslands1F#L526` Dragonair→Winter, `SecretLab#L922` Mewtwo→Armored,
  `PokemonTowerB1F#L401,L1128` Gengar→Powered Haunter and Ghost Marowak→Cubone,
  `LavenderCuboneHouse#L120` Cubone→Gengar). `.from`/`.to` are internal species indices;
  `.site` is the pureRGB script/map name (informational, for the ledger); `.trigger` is always
  `"script"` today (reserved enum in case a future foundation has an item-triggered transform).
  **Consumer:** none in `lua/` today (the client's `transform` signal, client brief §12.13,
  detects the *event* live and doesn't need to predict which species pairs are possible) — this
  table's primary consumer is the server-side species/evolution-family clause logic (does a
  transform count as the same identity for species-clause purposes?) and the ledger, both out of
  this brief's scope; document it here because the task's schema spec explicitly asks for it.

---

## 8. `encounter_tables.json`

**Producer:** `tools/gen_gen1_encounters.py` (exists today; **[PLAN M1]**: "add the fishing
formats: two `lb bc` old-rod sites, `GoodRodMons`+`GoodRodMonsOcean` 4 pairs, `SuperRodData`
groups; keep dex-0 rows"). **Consumer:** `server/adapters/gen1_rby.py:34`
(confirmed: `_ENCOUNTERS = _json("encounter_tables.json")`) — **[B3]** notes species are stored
as **National Dex** in this file and converted to internal species only at the adapter boundary
(`gen1_rby.py:437-465`, cited by the plan, not independently re-verified by me).
`lua/gen1/rom.lua`'s `self.rom_content()` (client brief §5.2) reads the *ROM itself* at runtime
for the live wild/fishing walk and does not consult this JSON — this file is a **curated/
display** table (area names, level ranges by encounter method), separate from the ROM-derived
`rom_content` payload the client sends in `hello` (`client.lua:913-921`).

Current shape (confirmed, keyed by title then by area name — **not** by map id):
```json
"red": {
  "route_1": {
    "Grass": [
      {"species_id": 16, "name": "Pidgey", "rate": 50, "min_level": 2, "max_level": 5},
      {"species_id": 19, "name": "Rattata", "rate": 50, "min_level": 2, "max_level": 4}
    ]
  }
}
```

| Field | Type | Notes |
|---|---|---|
| top key | title (`red`/`blue`/`yellow`) | pureRGB adds `purered`/`pureblue`/`puregreen` siblings — **[PLAN §3.1]** confirms per-title code differences are data-only (immediates), so three separate tables are still correct, not a single shared one |
| 2nd key | area name (snake_case) | matches `area_map.json`'s `.area_id`, not a raw map id — **generator must cross-reference the pureRGB `area_map.json` this same M1 pass produces**, since pureRGB's map-id renumbering (§4) means area names can't be assumed stable even where the city itself is unchanged |
| 3rd key | method: `"Grass"`\|`"Water"` today; pureRGB needs `"OldRod"`\|`"GoodRod"`\|`"GoodRodOcean"`\|`"SuperRod"` added | `.method` enum widening — **new methods, not present in vanilla's file at all today** (confirmed: only `Grass`/`Water` appear at the sampled key) |
| array entry `.species_id` | int | **NatDex id** per **[B3]**; dex `0` (MISSINGNO) rows are kept per the task spec ("dex 0 kept") — e.g. `P:data/wild/maps/SeaRoutes.asm#L3 db 120, MISSINGNO` must survive as a `species_id: 0` row, not be dropped as "invalid" |
| `.name` | string | display name (English) |
| `.rate` | int, 0-100 | vanilla's per-slot chance table is `{51,51,39,25,25,25,13,13,11,3}/256` (**[PLAN §3.5]**, unchanged on pureRGB — "slot chances unchanged"); this curated file appears to pre-aggregate per-species rather than per-slot (measured: two Route 1 grass entries sum to 100, i.e. already merged across slots) — **UNVERIFIED exact aggregation rule; confirm against `gen_gen1_encounters.py`'s own logic before assuming a simple sum** |
| `.min_level`/`.max_level` | int | level range across all slots that species occupies |

**pureRGB-specific rows:**
- `GoodRodOcean` method needed wherever `IsMapOceanMap` selects `GoodRodMonsOcean` over
  `GoodRodMons` (**[PLAN §3.5]**) — the generator needs the same ocean-map predicate pureRGB's
  own ASM uses, not a guess.
- Fishing entries generally: vanilla's file (confirmed) has **no fishing rows at all** at the
  sampled title/area (only `Grass`/`Water` appeared) — this is a genuine schema *addition* for
  both foundations if the vanilla lane doesn't already emit them elsewhere; if vanilla's
  `gen_gen1_encounters.py` truly never emits Old/Good/Super Rod rows today, note that as a
  vanilla gap the pureRGB work incidentally would need to fix too (**UNVERIFIED — grep
  `gen_gen1_encounters.py`'s own output keys before assuming fishing is entirely absent; the
  sampled area (`route_1`) may simply have no fishing spots**).

---

## 9. `trainers.json`

**Producer:** new `tools/gen_gen1_trainers.py` (**[PLAN M1]**: "new, grammar-aware;
`OPP_ID_OFFSET`, `$FE/$FD` records" — today's vanilla file is hand-curated, per **[B3]**, not
generated). **Consumer:** `server/adapters/gen1_rby.py:35` (confirmed:
`_TRAINERS = _json("trainers.json")`).

Current shape (confirmed): `{classes, named_trainers}`. `classes` keyed by decimal trainer-id
string → display name (or a small per-trainer-instance name map for rivals). Example (measured):
`classes["200"] == "Nobody"`; `classes["225"] == {"1": "Blue", "2": "Blue", "3": "Blue"}` (id 225
= `RIVAL1`, three separate named instances keyed by encounter number).

| Field | Type | Vanilla example | pureRGB |
|---|---|---|---|
| `classes` key | decimal string, `wCurOpponent - 0` domain (200-247 today) | `"200"` | pureRGB's domain is **198-253** per this deliverable's spec (56 classes at offset 197, `wCurOpponent` range `197+1..197+56`) — **[PLAN §3.5]**: `OPP_ID_OFFSET=197`, `NUM_TRAINERS=56`; renumbered `RIVAL1 $18→221`, `RIVAL2 $28→237`, `RIVAL3 $29→238` |
| `classes` value | string, or `{"<instance>": name}` for multi-named classes | `"Nobody"` / rival map | pureRGB keeps rivals as multi-named (still "Blue" per **[PLAN §0]** decision — Green's rival name **UNVERIFIED**, not stated in the plan; confirm at generator time against pureRGB's own trainer name table, bank `$33` "Pokémon Names" section houses trainer class names too per `layout.link`) |
| `named_trainers` | object/array of individual trainer instances (party contents) | not sampled in detail | pureRGB records add `$FE` (level\|alt-palette bit) and `$FD` (custom moveset id) party-record variants (**[PLAN §3.5]**) — schema must gain a `record_kind` enum (`fixed\|FE\|FD`) per party-member entry so the UPR-fork handler (out of scope here, **[PLAN M5]**) and any Gen-1-lane consumer can round-trip losslessly instead of only handling the fixed-level case |

**11 new trainer classes** and **56 total** vs. vanilla's 47 (confirmed count from vanilla's
sampled file's schema, not from an exhaustive count — **UNVERIFIED exact vanilla count without
loading the whole file; the plan states 48 classes 200-247 per B3's census of the file**).
Class-count source assert: `P:data/trainers/parties.asm` per-class party-size list
(**[PLAN S2]**: `12,15,19,7,11,24,10,10,15,15,9,5,11,15,9,9,15,6,6,10,9,17,9,9,3,14,4,41,10,6,
3,3,3,3,3,3,3,3,7,12,9,3,24,3,3,4,7,3,2,7,6,1,2,7,7,7` — 56 values, `RookieData` aliased by
four classes).

---

## 10. `items.json` / `moves.json` / `charmap.json`

### 10.1 `moves.json`

**Producer:** `tools/gen_moves_data.py` (exists today, per **[B3]** "literal", i.e. not
source-derived — a hardcoded table today, which the plan implies stays foundation-agnostic
since move data/ids are stable between vanilla and pureRGB per **[PLAN §3.1]**'s unchanged-file
list: `data/trainers/parties.asm` 1 commit and — more directly — `TypeEffects`/move mechanics
are not called out as changed in §3-§4 beyond the type-id additions already covered by
`species_index.json`'s `.types`). **Consumer:** `server/adapters/gen1_rby.py:36` (confirmed:
`_MOVES = {int(row["id"]): row for row in _json("moves.json")["moves"]}`).

Shape (confirmed): `{moves: [{...}]}`, array of per-move row objects keyed by `id` inside each
row (not by top-level key). **No pureRGB-specific schema change identified** — moves themselves
are not reported as renumbered or restructured anywhere in the plan's §3/§4 (only the type-id
space changed, which lives in a move's `type` field value domain, not the move schema itself:
new type ids `TYPELESS $06`, `CRYSTAL $09`, `BONEMERANG_TYPE $0A`, `TRI $11`, `FLOATING $12`,
`MAGMA $13` must be valid values wherever a `.type`/`.type1`/`.type2` field appears across every
schema in this document, including this one if any move's type changed — **UNVERIFIED whether
any move actually changes type on pureRGB; not stated in the plan**).

### 10.2 `items.json` (lives outside the per-title pack today)

**[B3]** confirms items are **not** in `data/games/gen1_rby/` at all currently — "Items live
outside the pack (`server/data/items/gen1.py` from `gen_gen1_items.py`)" — confirmed consistent
with `server/adapters/gen1_rby.py:16` (`from server.data.items.gen1 import ITEM_NAMES`, a Python
module import, not a JSON load). **Producer:** `tools/gen_gen1_items.py` (exists per `ls
tools/`). For pureRGB, the task's schema ask ("items.json") should therefore either (a) follow
the same pattern — a `server/data/items/gen1_purergb.py` module, keeping the two foundations
symmetric with vanilla's own layout — or (b) migrate to a real `data/games/gen1_purergb/
items.json` file if M1 decides to fix the vanilla lane's inconsistency at the same time.
**Recommend (a)** (mirror vanilla exactly) to minimize shared-code churn per the shared-runtime
rule; note the inconsistency for the Gen 1 lane rather than silently fixing it under this plan.

Required content regardless of file location: `HYPER_BALL = $05` (replaces TOWN MAP slot),
`APEX_CHIP = $32` (**[PLAN §3.4]**), ball-gate set `{1,2,3,4,5,8}` (same as `derived.ball_items`,
§1.1 — these two should be generated from one source of truth, not duplicated).

### 10.3 `charmap.json` (new file; does not exist for vanilla today)

**[B3]** confirms vanilla's charmap is "hand-transcribed (Lua + Python)" — `lua/gen1/reads.lua:9-28`
(the `EXTRA` table, confirmed by direct read) and `server/adapters/gen1_codec.py` (cited by
**[B3]**, not independently re-read by me for this document) each carry their **own** copy of
the same 256-entry glyph table, with no JSON intermediate. This is a real inconsistency the
pureRGB work is well-positioned to fix (client brief §4.3 already proposes generating this table
rather than hand-transcribing it a third time for a second foundation).

**Producer (new):** `tools/gen_gen1_charmap.py` (**[PLAN M1]**: "new; emits Lua + JSON").
**Consumers (new):** `lua/gen1/reads.lua` (replaces the `EXTRA` table + `glyph()` arithmetic,
client brief §4.3), `server/adapters/gen1_codec.py` (replaces its own hardcoded charmap, per
**[B3]**'s "charmap, dex order, stride, species domain differ" line item for row 26).

Proposed shape:
```json
{
  "schema": "gen1-charmap-v1",
  "terminator": 80,
  "glyphs": { "0": "<NULL>", "128": "A", "160": "a", "246": "0", "80": "@" },
  "shortcuts": { "51": "you", "52": "is" }
}
```

| Field | Type | Notes |
|---|---|---|
| `terminator` | int | the name-terminator byte (`0x50`/80 on vanilla; **UNVERIFIED whether pureRGB moves it** — not stated in the plan, keep as a generated field rather than a shared literal regardless) |
| `glyphs` | object, decimal-string byte → display string | every one of the 256 possible bytes should have an entry (even if `"<$XX>"` fallback) so `lua/gen1/reads.lua`'s `glyph()` function (client brief §4.3) can become a single table lookup with no arithmetic fallback branches, simplifying that function as a side effect |
| `shortcuts` | object, decimal-string byte → expansion text | **[PLAN §4 row 18, §3.3]**: pureRGB's `$33-$4D` text-shortcut bytes (`"you"`, `"is"`, … per **[PLAN S3]**) — kept **separate** from `glyphs` per this deliverable's explicit ask ("shortcut expansions kept separate"), because a shortcut is a multi-character *expansion for display*, not a literal glyph, and per client brief §8.2 the raw bytes must remain the round-trip-authoritative representation (a shortcut byte is never silently expanded into the stored name bytes) |

**Raw-byte round-trip rule (explicit, per this deliverable's spec):** whatever `glyphs`/
`shortcuts` say about *display*, the stored SRAM/WRAM name bytes are always the source of truth
for identity and for write-back (`boxes.lua`'s `nick = original.nick` default path, client
brief §8.2) — this JSON file's job is exclusively "how do I print these bytes to a human,"
never "how do I re-encode this text back to bytes" for anything other than a genuinely
player-supplied new nickname (`boxes.lua:encode_nickname`, which must refuse — not guess — any
name string containing characters this table cannot map back to a unique byte, per client brief
§8.2's open question about shortcut-byte writes).

---

## 11. Cross-file consistency obligations (M1 exit gate additions this pack introduces)

1. `derived.ball_items` (profile.json) and `items.json`'s ball-gate set (§10.2) must be the same
   list, generated once and shared, not independently hand-maintained twice.
2. `species_index.json`'s `.types` per form/spirit and `moves.json`'s type-id domain (§10.1) must
   both recognise the same six new type ids (`TYPELESS,CRYSTAL,BONEMERANG_TYPE,TRI,FLOATING,
   MAGMA`) — a generator that adds one without the other will silently produce an unresolvable
   type id somewhere downstream.
3. `area_map.json`'s `.area_id` values and `encounter_tables.json`'s second-level keys (§8) must
   be drawn from the same generated list, in the same generator run, so a renamed/renumbered
   pureRGB map can never desync between the two files.
4. `admission.json`'s (§1.2) sha1 keys must match `data/purergb_build_provenance.json`'s
   (**[PLAN M0]**) measured build output exactly — the M0 exit gate ("built `pokered.gbc` sha1 ≠
   `2e94d09c…` → stop; nothing published") is what makes every sha1 cited in this document
   trustworthy in the first place; if M0's build ever drifts, every admission row here is stale
   and must be regenerated, not hand-patched.
