# M2 implementation brief — shared Lua client (gen1_rby + gen1_purergb)

Scope: `W/lua/gen1/{entry,run,client,signals,reads,rom,writes,boxes,panel,trade_overlay}.lua`,
`W/lua/gen1_write_safety.lua`, `W/lua/slink.lua`. All line numbers below were read directly
from the tree at `E:/Google Drive/SLink/.claude/worktrees/gen1-master-release-plan-6b4279`
(2026-09-17) — they will drift as the Gen 1 RC lands more commits before this plan starts;
re-grep by the quoted string, not by line number alone, when you pick this up. pureRGB-side
facts (addresses, byte patterns, ASM lines) that I could not verify from a local checkout are
cited from the plan (`C:\Users\howar\.claude\plans\moonlit-napping-nautilus.md`, `P:` = pureRGB
GitHub HEAD `7e7a4653`) and marked **[PLAN]**; anything I could not confirm at all is marked
**UNVERIFIED**.

**Shared-runtime rule (do not violate):** every file below stays one code path for both
foundations. A foundation difference is *always* a new field read from `profile`/`sites`/
`write_checkpoint`/the new `trade` block — never `if profile.foundation == "purergb" then`.
The only place foundation identity is ever branched on is `entry.lua`'s admission/candidate
selection (title string, kind string) — everything downstream sees only data.

---

## 0. New profile fields (proposed)

All are additive to the existing `gen1-profile-v1` shape (`W/data/games/gen1_rby/profile.json`,
per-title `{derived, ram, repo, rom, rom_sha1, sram_bank, sym, variant}` — confirmed by reading
the file: `derived` today = `{battle_struct_size, box_capacity, box_struct_size, name_length,
party_capacity, party_struct_size, sram_box_banks, sram_box_stride, sram_boxes_per_bank}`).

| Block | Field | Type | Vanilla value | pureRGB value | Replaces (current hardcode) |
|---|---|---|---|---|---|
| `derived` | `ball_items` | `int[]` | `[1,2,3,4]` | `[1,2,3,4,5,8]` **[PLAN §4 row 7, §3.4]** | `client.lua:87 BALL_ITEMS`, `signals.lua:38 item>=1 and item<=4` |
| `derived` | `opp_id_offset` | `int` | `200` | `197` **[PLAN §4 row 11, §3.5]** | `reads.lua:244-250`, `client.lua:628` |
| `derived` | `bag_capacity` | `int` | `20` (from the live formula) | `30` **[PLAN §4 row 6]** | `reads.lua:194 (a.wPlayerMoney-a.wBagItems-1)/2` |
| `derived` | `base_stats_stride` | `int` | `28` | `35` **[PLAN §4 row 8, §3.3]** | `rom.lua:10 Rom.RECORD = 28` |
| `derived` | `dex_count` | `int` | `151` | `151` | `rom.lua:37 dex<1 or dex>151` (data, not a behaviour change, but must stop being a literal) |
| `derived` | `species_count` | `int` | `190` | `190` | `rom.lua:18 internal<1 or internal>190` |
| `derived` | `nondex_species` | `int[]` | `[]` | the 13 form/spirit/MISSINGNO internal ids (`$1F,$32,$34,$38,$56,$5E,$73,$86,$92,$AC,$AE,$AF,$B5`) **[PLAN §3.3]** | new — `rom.lua` has no NonDex path today |
| `admission` | `<sha1 lowercase>` → `{title, kind, profile_id}` | `object` | one row per clean R/B/Y sha1 | one row per {clean,overlay}×{PureRed,PureBlue,PureGreen} **[PLAN A3, §5.2]** | new — today admission is the single scalar `profile.rom_sha1` per title, never cross-title-collision-safe |
| `sites.<kind>` | `target_symbol` | `string?` | absent | e.g. `"wUsedItemOnWhichPokemon"` for `apex_preflight`/`apex_commit`, whose point-of-interest is `HL`, not `wWhichPokemon` **[PLAN §6 M1 site list]** | new — `signals.lua`'s `point` functions today assume `wWhichPokemon`/`wCurPartySpecies` name the mon; a site whose payload lives elsewhere needs to say so in data |
| `trade` | `mailbox` | `int` (WRAM addr) | `0xDEE2` | the linker-placed bank-1-tail address **[PLAN A4]** | `panel.lua:14 local MAILBOX = 0xDEE2` |
| `trade` | `service` | `{bank:int, addr:int}` | `{bank:0x3F, addr:0x4500}` | overlay build's own address **[PLAN M3]** | `trade_overlay.lua:27-30 T.service_address()`, `client.lua:1137` fallback |
| `trade` | `receptionist_hook` | `int` (ROM flat) or `{bank,addr}` | `0x29C3` | overlay build's own hook site **[PLAN M3]** | `client.lua:960 TRADE_DISPATCH`, `client.lua:996 io.read_u8(0x29C3+...)` |
| `checkpoint.write_safe` | `delay_frame_bytes` | hex string | 8-byte vanilla pattern (see below) | pureRGB's differing prologue bytes **[PLAN §4 row 12, §3.1]** | `gen1_write_safety.lua:39-40` hardcoded `{0x3E,1,0xE0,...}` |
| `checkpoint.write_safe` | `resume_offset` | `int` | `5` | `24` **[PLAN §3.1 Live]** | `gen1_write_safety.lua:62 p.delay_frame + 5` |
| `checkpoint.write_safe` | `caller_offsets` | `int[]` | `[3,3]` | `[1,1]` (same address for both loop symbols) **[PLAN §3.1 Live]** | `gen1_write_safety.lua:63 overworld_loop+3 / overworld_loop_less_delay+3` |
| `checkpoint.write_safe` | `delay_frame_bank_addr` | `int` (`wDelayFrameBank`) | n/a (no such check today) | required, value must read `0` **[PLAN §4 row 12]** | new — no such check exists in `gen1_write_safety.lua` |
| `checkpoint.write_safe` | `wram_bank_register_allowed` | `int[]` | not checked today | `[0,1]` **[PLAN §4 row 12/13]** | new — `gen1_write_safety.lua` never reads `io.register("WRAM BANK")` |

Vanilla's `delay_frame_bytes` (for the migration to be a pure data move, not a behaviour
change) is the 8 bytes `gen1_write_safety.lua:39-40` builds today:
`3E 01 E0 <vblank_flag&0xFF> 76 F0 <vblank_flag&0xFF> A7`.

---

## 1. `lua/slink.lua`

**Current (lines 58-73):** the universal launcher special-cases Gen 1 before the generic
`game_detect` registry:

```lua
local Entry = dofile(_dir .. "gen1/entry.lua")
if Entry.detect_title(function(addr) return memory.read_u8(addr, "ROM") end) then
    dofile(_dir .. "gen1/run.lua")
    return
end
```

`Entry.detect_title` is a **header-substring** check (see §2). For pureRGB this is wrong twice
over: PureRed/PureBlue's headers are byte-identical to vanilla `POKEMON RED`/`POKEMON BLUE`
(`W/lua/gen1/entry.lua:99-101` matches on `"RED"`/`"BLUE"`/`"YELLOW"` substrings), so a PureRed
cartridge is silently misdetected as vanilla Red; PureGreen's header (`POKEMON GREEN`) matches
none of the three and is refused entirely (**[PLAN §4 row 1]**).

**New behaviour:** no change to `slink.lua` itself — it stays "ask `entry.lua` whether this is
a Gen 1 cartridge, and if so hand off to `gen1/run.lua`". The fix is entirely inside
`Entry.detect_title`/`Entry.build` (§2): once those do hash-first admission over *all*
foundations' `admission` tables, this gate becomes correct for pureRGB automatically, no
`if pure then` needed here.

**Unit test to extend:** `W/tests/unit/test_gen1_launcher_route.py` (exercises this exact
routing decision — confirmed present in `ls tests/unit`). Add pureRGB sha1/header fixtures
alongside the vanilla ones it already carries.

---

## 2. `lua/gen1/entry.lua` — composition root + foundation admission

### 2.1 `Entry.detect_title(read_rom_u8)` (lines 90-103)

**Current:**
```lua
function Entry.detect_title(read_rom_u8)
    ...
    if name:find("RED", 1, true) then return "red" end
    if name:find("BLUE", 1, true) then return "blue" end
    if name:find("YELLOW", 1, true) then return "yellow" end
    return nil, name
end
```
Header-substring only (**[PLAN §4 row 1]** — collides on PureRed/PureBlue, refuses PureGreen).

**New behaviour — hash-first, header for candidate narrowing only:**
1. Compute `rom_sha1 = deps.rom_sha1` (already plumbed in from `run.lua`'s
   `gameinfo.getromhash():lower()`, `run.lua:26`) and compare it **case-insensitively** (BizHawk
   returns uppercase SHA-1 for an unrecognised ROM — confirmed live: `Live` §11.2 measured
   `gameinfo.getromhash()` = `2E94D09C1E16A57EB079404C030F26FDEEAC949D` uppercase,
   `indatabase=false`) against the union of every foundation pack's `admission` table
   (`data/games/gen1_rby/admission.json` ∪ `data/games/gen1_purergb/admission.json`, both new
   per **[PLAN M1]** — `gen1_rby`'s admission table does not exist yet; today's only admission
   surface is the scalar `profile.titles[title].rom_sha1` compared nowhere in the Lua client).
2. A hit gives `{title, kind, profile_id}` directly — this is the *only* admission proof, never
   the header.
3. If `gameinfo.indatabase()` is true, BizHawk substituted its own database hash instead of
   hashing the loaded bytes; **[PLAN A3]** requires falling back to hashing the flat `ROM`
   domain in Lua (sha1 in pure Lua — no library dependency exists in the current client, so this
   is new code; a ~30-line pure-Lua SHA-1 over `io.read_range(0, romsize, "ROM")` is the
   cheapest correct option, run once at boot, not per frame).
4. The header substring (`Entry.detect_title`'s current body) is kept, demoted to *narrowing the
   candidate list for logging/HUD only* — e.g. "header says RED, but the matched admission row
   says PureRed (overlay)" is a legitimate log line, never a decision input.
5. `Entry.ROM_TYPE` (line 26, today `{red="Red", blue="Blue", yellow="Yellow"}`) gains
   `PureRed`/`PureBlue`/`PureGreen` → `game_id gen1_purergb` on the server side (**[PLAN §4 row
   2]**, server-side, out of this brief's scope but the Lua string constants must match
   `server/adapters/__init__.py`'s routing table once that lands).

**`Entry.build(deps)` (lines 28-88):** currently hardcodes the pack path twice —
```lua
local profile = assert(load_json(json, root .. "/data/games/gen1_rby/profile.json").titles[title], ...)
local sites = assert(load_json(json, root .. "/data/games/gen1_rby/engine_signals.json").titles[title]).sites
local write_checkpoint = assert(load_json(json, root .. "/data/games/gen1_rby/write_checkpoint.json")[title])
local area_map = load_json(json, root .. "/data/games/gen1_rby/area_map.json")
local statics = load_json(json, root .. "/data/games/gen1_rby/static_encounters.json").statics
```
(lines 39-44). **New:** `deps.pack` (a new required dep, e.g. `"data/games/gen1_purergb"`)
replaces the literal `"data/games/gen1_rby"` prefix on all five lines; `run.lua` supplies it
from the admission match in step 2 above, not from a hardcoded string.

**Unit tests to extend/mirror:** `W/tests/unit/test_gen1_entry.py` — confirmed function names
`test_the_three_titles_are_recognised` (line 69), `test_an_unrelated_title_returns_nil_and_the_
header_text` (line 73), `test_the_real_dumps_report_their_own_title` (line 84),
`test_rom_type_strings_are_the_ones_the_server_routes_on` (line 91). Add: a PureRed-header ROM
whose sha1 is *not* in any admission table (must return the pure-reason refusal, never fall
back to the vanilla profile "because the header matched"); a PureRed-header ROM whose sha1
*is* in the pure admission table (must select `gen1_purergb`/PureRed even though the header
would also match vanilla's `"RED"` substring); the `indatabase()==true` fallback path
(UNVERIFIED that BizHawk's Lua exposes `gameinfo.indatabase()` from lupa's harness — this is a
BizHawk-only global today, so the lupa mirror of this test needs a stub).

---

## 3. `lua/gen1/run.lua`

**Current (lines 19-33):** builds `deps` from `Entry.bizhawk_deps()`, detects title via header
only, then calls `Entry.build` with a fixed pack implicitly (through `entry.lua`'s hardcoded
path, §2). No admission-table lookup happens here at all.

**New behaviour:** after §2's `Entry.detect_title`/admission work lands, `run.lua`'s only
change is passing through whatever `deps.pack`/`deps.title`/`deps.rom_sha1` the new detection
step decided, plus surfacing the admission `kind` (`clean`/`overlay`) in the startup log line
(`run.lua:39` already logs `title`/`player`/`rom_sha1`; add `kind`). No structural change to
the frame loop (`event.onframeend`, lines 44-48) or `event.onexit` (line 49).

**Unit test:** none exists specifically for `run.lua` (it is thin glue over `entry.lua`); the
`test_gen1_launcher_route.py` extension in §1 covers it end-to-end.

---

## 4. `lua/gen1/reads.lua`

### 4.1 Row 6 — bag capacity (`r.read_bag`, lines 190-206)

**Current:**
```lua
function r.read_bag()
    local count = io.read_u8(a.wNumBagItems)
    local capacity = math.floor((a.wPlayerMoney - a.wBagItems - 1) / 2)
    ...
```
Line 194 derives capacity from the *distance between two WRAM symbols*. pureRGB moves
`wPlayerMoney` to `01:D34F`, which now **precedes** `wBagItems` (`01:D543`) instead of following
it (**[PLAN §4 row 6, A9]**), so the subtraction goes negative.

**New:** `local capacity = d.bag_capacity` (the new `derived.bag_capacity` field, §0). Delete the
symbol-arithmetic line entirely — it was never a real invariant, just an accident of vanilla's
memory layout, and the generator can compute the true capacity from
`(wPocketAbraNick - wBagItems - 1)/2` **[PLAN §4 row 6]** once at pack-build time instead of at
every read.

**Unit test:** `W/tests/unit/test_gen1_reads.py`, function
`test_ancillary_reads_and_all_addresses_follow_shifted_profile` (line 264) — it seeds
`wNumBagItems`/`wBagItems`/`wPlayerMoney` (lines 229-232) and asserts the decoded bag at line
272. Extend: add a pureRGB-shaped fixture where `wPlayerMoney` sits *before* `wBagItems` in the
synthetic memory image and assert `read_bag()` still uses `d.bag_capacity`, not the address
subtraction.

### 4.2 Row 11 — trainer threshold (`r.read_battle`, lines 242-256)

**Current:**
```lua
function r.read_battle()
    -- constants/trainer_constants.asm:1: trainer class = opponent - 200.
    local opponent = io.read_u8(a.wCurOpponent)
    ...
    return {..., is_trainer = opponent >= 200,
            trainer_class = opponent >= 200 and opponent - 200 or R.NULL, ...}
```
(lines 244, 249-250). Literal `200` twice; pureRGB's `OPP_ID_OFFSET = 197` (**[PLAN §4 row 11,
§3.5]**).

**New:** `is_trainer = opponent >= d.opp_id_offset`, `trainer_class = opponent >= d.opp_id_offset
and opponent - d.opp_id_offset or R.NULL`.

**Unit test:** same `test_ancillary_reads_and_all_addresses_follow_shifted_profile`
(`test_gen1_reads.py:264`) — it seeds `wCurOpponent: (202,)` and asserts
`original["battle"]["is_trainer"]` and `trainer_class == 2` (lines 234, 275-276). Extend with a
pureRGB profile fixture (`opp_id_offset=197`) and `wCurOpponent = 199` → `trainer_class == 2`.

### 4.3 Row 18 — charmap (`EXTRA` table lines 9-28, `glyph()` lines 30-35, `r.decode_name` lines
52-60)

**Current:** `EXTRA` is a Lua-literal table transcribed from vanilla's
`constants/charmap.asm:92-117,126-151,187-196` (comment at lines 6-8); `glyph()` maps the three
contiguous A-Z/a-z/0-9 runs by arithmetic and falls back to `EXTRA`. pureRGB changes several
glyph codes (`$9e/$9f` → quotes, `$e9-$eb` → arrow/plus/percent per **[PLAN §3.3]**) and adds
text-shortcut bytes `$33-$4D` (**[PLAN §4 row 28]**).

**New:** `EXTRA` becomes a parameter — `R.new(profile, io)` gains a third argument (or reads it
off `profile.charmap`, a new per-title table `{code(0-255) -> glyph string}` generated by
`tools/gen_gen1_charmap.py` from the foundation's own `constants/charmap.asm`, replacing the
Lua-literal `EXTRA`/`glyph()` pair). `r.decode_name`'s terminator byte `0x50` (line 56, `"@"` in
vanilla's charmap) must also come from the generated table rather than being hardcoded, since a
foundation could in principle move it (**UNVERIFIED for pureRGB — [PLAN] does not show the `@`
terminator byte moving, only glyphs in the `$9x`/`$ex` ranges; keep the literal only if the
generator confirms it via a source assert on `constants/charmap.asm`**).

**Unit test:** `W/tests/unit/test_gen1_reads.py` (the file that already exercises
`decode_name`/`decode_party_mon`; grep confirms it seeds `wPlayerName` via
`oracle.encode_name("RED")` at line 231) and `W/tests/unit/test_gen1_boxes.py:553
test_nickname_override_uses_english_charmap_not_cached_stats` (exercises the *reverse* map,
`boxes.lua`'s `encode_nickname`, §7 below — the two must be generated from the same table).

### 4.4 Row 24 — daycare source (not currently a distinct read path)

**Current:** `reads.lua` has no `read_daycare`/`wDayCareMon` accessor at all — daycare
withdrawal today rides the generic `move_mon`/box-snapshot path in `client.lua` (§13.6).

**New:** add `function r.read_daycare_mon()` mirroring `r.decode_party_mon`, reading
`profile.ram.wDayCareMon` (**[PLAN §4 row 24]** — `wDayCareMon`/`wDayCareInUse` symbols; per
**[PLAN A7]** these are shared vanilla symbols too, so this is a genuine vanilla bug fix that
also happens to be required for pureRGB, not a pureRGB-only addition). Struct shape is the same
`party_struct_size`-byte record (daycare stores one full party-mon blob), so this is a thin
wrapper over the existing `r.decode_party_mon`, not new decode logic.

**Unit test:** new — no `test_gen1_daycare*.py` exists today. Mirror the shape of
`test_gen1_reads.py`'s party/box round-trip tests (`_write_collection`/`_block` helpers already
present in that file) against a single-slot daycare fixture.

---

## 5. `lua/gen1/rom.lua`

### 5.1 Row 8 — species/dex bounds and base-stats stride (`Rom.RECORD`, `self.natdex`,
`self.base_stats`, lines 10, 17-25, 27-46)

**Current:**
```lua
local Rom = { RECORD = 28, GROWTH = 19 }
...
function self.natdex(internal)
    if type(internal) ~= "number" or internal < 1 or internal > 190 then return nil end
    ...
function self.base_stats(dex)
    if type(dex) ~= "number" or dex < 1 or dex > 151 then return nil, "dex out of range" end
    if stats_cache[dex] then return stats_cache[dex] end
    local flat
    if dex == 151 and rom.MewBaseStats then flat = rom.MewBaseStats.flat
    else flat = rom.BaseStats.flat + (dex - 1) * Rom.RECORD end
    local rec = record_at(flat)
    if rec.dex ~= dex then return nil, "base stats record dex byte differs" end
```
Three hardcodes: `RECORD = 28` (module-level constant, not per-profile), the `internal>190`
bound, and the `dex>151`/`dex==151→MewBaseStats` special case. pureRGB: `NUM_POKEMON=152`
internal with `DEX_MISSINGNO=0` (dex space is `0..151`, not `1..151`), 35-byte records
(`BaseStats` for the 151 numbered species + a separate `NonDexMonsBaseStats` table for 13
forms/spirits/MISSINGNO whose `PokedexOrder` entry is 0) (**[PLAN §4 row 8, §3.3]**).

**New:**
- `Rom.RECORD` stops being a shared module constant; `record_at`/`base_stats`/`base_stats_for`
  read `d.base_stats_stride` (new field, §0) from the injected profile instead.
- `self.natdex(internal)` bounds against `d.species_count` (190 for both foundations today, but
  no longer a literal).
- `self.base_stats(dex)`: the special case widens from "`dex==151` → `MewBaseStats`" to "internal
  species is in `d.nondex_species` → read `NonDexMonsBaseStats[index_of(internal, nondex_species)]`
  instead of `BaseStats[dex-1]`" — this changes the function's primary key from *dex number* to
  *internal species index* for the non-dex case, because MISSINGNO and the 12 pureRGB
  forms/spirits all have `dex == 0`, so `self.base_stats(dex)` can no longer even be asked for
  them by dex; callers that need a non-dex mon's stats must go through `self.base_stats_for
  (internal)` (line 49-53, already internal-index-keyed) with `self.base_stats` becoming an
  internal helper for the dex-keyed table only. `boxes.lua`'s `self.party_mon`
  (§7, calls `self.rom.base_stats_for(species)` via `client.lua:543`) already uses the
  internal-index entry point, so this is contained to `rom.lua`.
- Vanilla's `MewBaseStats` special case (dex 151) becomes the degenerate one-entry case of the
  same `nondex_species` mechanism (`derived.nondex_species = []` for vanilla, since Mew's dex
  *is* 151 there — **UNVERIFIED whether vanilla should instead keep its own `MewBaseStats`
  branch as today, since Mew is dex 151 in BOTH foundations and pureRGB keeps `MewStatsOffset`
  as its own symbol per [PLAN S2] `MewStatsOffset 0xB38C7 = BaseStats + 150×35`; the cleanest
  unification is to fold Mew into `nondex_species` treatment only if its record truly is NOT
  contiguous with `BaseStats[149]` in pureRGB — confirm against the built `.sym` before
  refactoring `self.base_stats(151)`**).

### 5.2 `self.rom_content()` fishing walkers (lines 77-140)

**Current:** three format assumptions hardcoded inline: old rod reads a fixed `+6` displacement
and 2 bytes (`local old = ...ItemUseOldRod.flat + 6; assert(byte(old)==1, ...)`, lines 110-112);
good rod reads exactly 4 bytes / one table (`rom.GoodRodMons`, line 114); super rod branches
only on `rom.SuperRodFishingSlots` presence (Yellow) vs `rom.SuperRodData` (R/B) (lines 116-138).
pureRGB: two `lb bc` old-rod sites (Magikarp *and* Goldeen, **[PLAN S2]**
`OldRodOffset 0xDEDD`), `GoodRodMons` **plus** a second table `GoodRodMonsOcean` selected by
`IsMapOceanMap` (**[PLAN §3.5, §4 row 16]**), and `SuperRodData`'s per-group format is unchanged
in shape but the map-id domain differs.

**New:** `self.rom_content()` gains a foundation-aware old-rod/good-rod walk driven by presence
of `rom.GoodRodMonsOcean` (mirroring the existing `rom.SuperRodFishingSlots` presence-branch
pattern at line 116) rather than hardcoded byte counts; the payload gains a `good_rod_ocean`
key alongside today's `good_rod`. This is squarely **[PLAN §4 row 16]** ("(b)+(c)
foundation-specific walkers/fingerprint") and **[PLAN M1]** ("add the fishing formats: two `lb
bc` old-rod sites, `GoodRodMons`+`GoodRodMonsOcean` 4 pairs, `SuperRodData` groups").

**Unit tests:** `W/tests/unit/test_gen1_rom_scan.py` and `W/tests/unit/test_gen1_rom_content.py`
(both confirmed present) — these already differential-test `rom.lua` against
`server/adapters/gen1_rom_scan.py` on clean vanilla ROMs (per **[PLAN B3]**:
`test_gen1_rom_content.py`/`test_gen1_rom_tables.py` "Lua/Python agreement on clean ROMs").
Mirror both against a pureRGB fixture ROM once M0's build lands; the same tests must keep
passing unmodified on vanilla (the walkers must stay foundation-parametrised, not
foundation-forked).

---

## 6. `lua/gen1/signals.lua`

### 6.1 Row 9 / M2-b — new site kinds and `target_symbol`

**Current:** `S.KINDS` (lines 29-179) is a fixed table of 17 kinds, each a `{filter?, point?}`
pair keyed by a symbol name it assumes exists in `ram` (e.g. `S.KINDS.npc_trade`'s `point`
reads `ram.wInGameTradeGiveMonSpecies`/`wWhichPokemon`, lines 172-179).

**New kinds to add** (**[PLAN M1 site list, M2-b]**):
- `S.KINDS.transform` — point reads `wWhichPokemon`, `wCurPartySpecies`, and the pre-write HP
  (old_hp) at `ChangePartyPokemonSpecies+0` (site offsets `+$4A`/`+$4C` are the HP store, handled
  by `writes.lua` §8, not here).
- `S.KINDS.apex_preflight` / `S.KINDS.apex_commit` — point reads the target slot from `HL`
  (register, not a WRAM symbol — this is what the new `target_symbol` site field documents) via
  `io.register("H")*256 + io.register("L")`, mirroring the existing `bag_received` filter's use
  of `H`/`L` registers (lines 35-36) as the precedent for "read a register, not a fixed symbol,
  to find the point of interest."
- `S.KINDS.npc_trade_remove` / `S.KINDS.npc_trade_done` — replace the single `S.KINDS.npc_trade`
  (lines 172-179); `npc_trade_remove`'s point is today's `npc_trade` point (`wWhichPokemon` +
  give/receive species), `npc_trade_done`'s point is a party snapshot read *after* the append so
  the client can look at `wPartyCount-1` (**[PLAN §4 row 25]**).
- `S.KINDS.daycare_withdraw` — point reads the daycare snapshot (§4.4's new `r.read_daycare_mon`
  is called from `client.lua`'s `on_signal`, not from here; this site's `point` only needs
  `wWhichPokemon`/`wPartyCount` to know where the appended mon landed, same shape as
  `storage_point` lines 140-147).
- `S.KINDS.cable_trade_remove` / `cable_trade_add` / `cable_partial_save` — **[PLAN M1]**, needed
  for the vanilla NPC-trade-slot-instability fix (**[PLAN §4 row 25]** notes "the same fix
  applies to vanilla" — this is a shared bug fix, not pureRGB-only).
- `S.KINDS.starter` — **[PLAN M1]** already partially covered by existing `starter_begin`/
  `starter_end` (lines 67-68); confirm at generator time whether pureRGB's
  `OaksLabMonChoiceMenu.continue+$23` needs a distinct site or reuses the existing pair
  (**UNVERIFIED** — the plan lists it as a new site name but the existing client already has
  `starter_begin`/`_end` wired to `battle_point`; reconcile during M1, not M2).

None of the above require a change to `S.new`'s hook-registration loop (lines 228-233) or
`fire`'s bank/PC/byte-reverification (lines 202-226) — the mechanism is already fully
data-driven per site; only `S.KINDS` (the *interpretation* table) grows.

### 6.2 M2-b — all-zero-GUID registration rejection

**Current (lines 228-233):**
```lua
for kind, site in pairs(sites) do
    local pc = site.address + (site.capture_offset or 0)
    local id = io.on_bus_exec(function() fire(kind, site) end, pc, "SLink-gen1-" .. kind, "System Bus")
    assert(id, "engine signal registration failed: " .. kind)
    self.hooks[#self.hooks + 1] = id
end
```
`assert(id, ...)` at line 231 is a **truthy** check — a string is always truthy in Lua, so a
BizHawk registration that "succeeds" by returning the well-known all-zero GUID string (the
sentinel it returns for an unsupported registration, per **[PLAN M2-b]**, sourced from live
research card A15) passes this assert and the client believes the hook is armed when it is not.

**New:** compare `id` against a known all-zero-GUID literal (`"00000000-0000-0000-0000-000000000000"`
— **UNVERIFIED exact format BizHawk returns; confirm against a live A15-style probe before
hardcoding the literal, since GUID casing/braces vary by BizHawk version**) and treat a match as
a registration failure equivalent to `id == nil`. Also track a registration *count* separate
from `#self.hooks` (the plan's "and counts registrations") so `S.new` can assert
`registered_count == expected_count` once at the end of the loop, catching a partial-failure
mid-loop rather than only a single bad id.

**Unit test:** `W/tests/unit/test_gen1_signals.py:107
test_registers_one_hook_per_site_at_its_pc` — extend with an `io.on_bus_exec` stub that returns
the all-zero-GUID string for one site and assert `S.new` raises (today it would silently accept
that site as armed).

### 6.3 M2-b — flat WRAM-domain reads for `$D000+`

**Current:** every `point`/`filter` function in this file reads via `io.read_u8(addr, "System
Bus")` (e.g. line 37, line 41-43, throughout). `entry.lua`'s `reads_io` (lines 48-51) is
similarly pinned to `"System Bus"` for the higher-level `reads.lua` module. Per **[PLAN §4 row
13, Live]**, a `$D000-$DFFF` read through `"System Bus"` during pureRGB's transient `SVBK=2`
palette-fade window returns bank-2 bytes instead of the intended bank-1 WRAM, because System Bus
follows the live hardware mapping.

**New:** for any read at `addr >= 0xD000 and addr < 0xE000`, route through the flat `WRAM`
domain at `0x1000 + (addr - 0xD000)` instead of `System Bus`. This is confirmed safe by the
coordinator's live probe (**[PLAN §3.1/§11.2 Live]**: "a write through the `WRAM` domain to the
free tail byte `$DEFF` was visible on the bus and restored... the client can read pure `$Dxxx`
state through the flat domain without bank checks"). The cheapest correct place to do this is a
single helper in `signals.lua`'s injected `io` (or a new `io.read_u8_wram_safe`) used by every
`point`/`filter` closure that reads a `$Dxxx` symbol — **do not** special-case per-site; every
site that touches `wCurOpponent`/`wPartyCount`/etc. (nearly all of them) needs the same fix, so
this is a change to the shared read helper the sites call, not seventeen individual edits. The
production `S.bizhawk_io()` (lines 257-271) is where the domain routing actually happens today
(`memory.read_u8(addr, domain)` with `domain` passed in verbatim by every call site) — the fix
is a wrapper there, or in `entry.lua`'s `reads_io`/`box_io` construction (lines 46-70), not
inside every `S.KINDS` entry.

**Write-side gate (also M2-b):** `writes.lua`'s `write_bytes` (§8) must refuse any write to
`$D000+` unless `io.register("WRAM BANK") ∈ {0,1}` — this is the write-side half of the same
finding and belongs to `writes.lua`, not `signals.lua`.

**Unit test:** no existing test exercises domain routing directly (the lupa harness's fake `io`
doesn't model bank-2 aliasing); this needs a new differential test once the pureRGB fixture ROM
exists, comparing a `System Bus` read during a synthetic bank-2 window against the flat `WRAM`
read.

---

## 7. `lua/gen1/writes.lua`

### 7.1 New armed windows: `apex_commit`, `transform`

**Current pattern to mirror (`self:faint_active_battler`, lines 87-92):**
```lua
function self:faint_active_battler(slot)
    assert(self.armed == "battle_loop_head", "active-battler faint only at the battle loop head")
    self:write_bytes(ram.wBattleMonHP, { 0, 0 })
    self:write_bytes(ram.wPlayerSelectedMove, { W.CANNOT_MOVE })
    self:faint_party_slot(slot)
end
```
Every write method in this file (`faint_party_slot` 78-83, `faint_active_battler` 87-92,
`explode_active_battler` 96-103, `write_enemy_party` 109-133) follows the same shape: assert the
caller armed the specific reason this method requires, then call `self:write_bytes`, which
itself asserts `self.armed` and (if the caller supplied an `allow` predicate via `self:arm`)
checks the byte range (lines 57-73).

**New methods, same shape:**
```lua
-- W-8 (new): restore the two DV bytes ItemUseMedicine.useApexChip was about to commit, when the
-- resulting FFFF:OTID:species key would collide with a live key. Armed only inside the
-- apex_commit hook, synchronously (on_fire), before .recalculateStats runs.
function self:restore_apex_dvs(dv_hi, dv_lo)
    assert(self.armed == "apex_commit", "APEX DV restore only inside the apex_commit hook")
    self:write_bytes(ram.wUsedItemOnWhichPokemon_dv_offset, { dv_hi, dv_lo }) -- exact offset: M1 site data
end

-- W-9 (new): force a transformed mon's HP back to 0 when the pre-transform key was DEAD/
-- MEMORIAL, so ChangePartyPokemonSpecies's "current HP := new max HP" store never revives a
-- canonically-dead mon (P:engine/pokemon/change_mon_species.asm#L34-L49, PLAN A2).
function self:restore_transform_hp_zero(slot)
    assert(self.armed == "transform", "transform HP zero only inside the transform hook")
    self:faint_party_slot(slot) -- same HP/status zero as W-1; struct offsets are foundation-agnostic
end
```
Both are **GATE** per **[PLAN §5.2 A1/A2]** — they are unproven until the live commit-site
window is confirmed to fire before `.recalculateStats`/the HP store lands, exactly the same
proof standard `MainInBattleLoop+0` already met (pinned site, bytes re-verified at fire time,
model replay, live gate). Until that gate passes, the fallback per **[PLAN U6/U7]** is:
APEX collisions are refused rules-side via the acknowledged `key_change` rejection (server-side,
§13.9 below), never silently allowed to collide.

**Where they're called from:** `client.lua:start()`'s `on_fire` handler table (§13.13, currently
only wires `battle_loop_head` and, conditionally, `trade_service`) gains `apex_commit` and
`transform` entries that arm the window and call these methods synchronously inside the hook —
this is the same "on_fire runs inside the bus-exec callback" mechanism `signals.lua:220-223`
already provides for `battle_loop_head`.

**Unit tests to mirror:** `W/tests/unit/test_gen1_writes.py` — `test_active_battler_faint_needs_
the_loop_head_and_hits_both_structs` (line 106) and `test_active_faint_guard_rules` (line 122)
are the direct template: assert the new methods refuse outside their named `armed` reason, and
(for `restore_apex_dvs`) assert a full byte-validation-before-any-write discipline the same way
`test_enemy_party_is_validated_completely_before_any_byte_lands` (line 149) does for
`write_enemy_party`.

### 7.2 M2-b — WRAM BANK write gate

**Current:** `self:write_bytes` (lines 63-73) has no address-range check at all; it writes
whatever `arm`/`allow` permitted, unconditionally.

**New:** before the byte loop, when `addr >= 0xD000 and addr < 0xE000`:
`assert(({[0]=true,[1]=true})[io.register("WRAM BANK")], "write refused: WRAM BANK outside {0,1}
(W-10)")`. This is the write-side complement to §6.3's read-side flat-domain fix, and is a
foundation-agnostic hardware-correctness fix (it protects vanilla too, since nothing today stops
a write racing a transient bank-2 window on GBC hardware — **UNVERIFIED whether vanilla ever
actually enters `SVBK=2`**; **[PLAN §3.1]** documents the bank-2 fade buffer as pureRGB-observed
but the mechanism (`GBCSetCPU2xSpeed`/palette fade) is pret-shared code, so treat this as
"needed for pureRGB, harmless and probably correct for vanilla too").

**Unit test:** extend `test_gen1_writes.py`'s `test_nothing_is_written_without_an_armed_window`
(line 75) sibling area with a `WRAM BANK == 2` fixture and assert every `$Dxxx` write raises.

---

## 8. `lua/gen1/boxes.lua`

### 8.1 Row 8 — base-stats-stride-dependent rebuild (`rebuild`, lines 362-382)

**Current:** `rebuild(entry, base)` (called from `self.party_mon`, line 440) takes `base` from
the caller (`client.lua:543 self.rom.base_stats_for(species)`) and only reads
`base.growth_rate/hp/attack/defense/speed/special` — it never touches the record's byte length
directly, so this function is **already stride-agnostic** as written; the stride dependency
lives entirely in `rom.lua` (§5.1), which is the correct layering. No change needed here beyond
confirming `rom.lua`'s `base_stats_for` keeps returning the same five-field shape for
`nondex_species` entries (i.e., `NonDexMonsBaseStats` records must expose the same
`{hp,attack,defense,speed,special,growth_rate}` fields `record_at` already produces at
`rom.lua:30-31`, since `growth_rate` sits at record offset 19 in both the 28-byte and 35-byte
layouts per **[PLAN §3.3]**'s "27 (vanilla minus the padding byte) + 8 sprite-bank/alt-pic
bytes" — the extra 8 bytes are appended, so the first 27+1 bytes' offsets, including
`growth_rate@19`, are unchanged. **UNVERIFIED — confirm against the built `.sym`/`base_stats.asm`
before relying on this**).

### 8.2 Row 28 — nickname round-trip (`encode_nickname`, lines 383-406)

**Current:**
```lua
local function encode_nickname(name)
    ...
    for b = 0, 255 do
        local glyph = reads.decode_name({b})
        if glyph and glyph ~= "" then tokens[#tokens + 1], values[glyph] = glyph, b end
    end
    ...
```
This *already* derives its reverse-map from the injected `reads` instance (line 389,
`reads.decode_name`), not from a second hardcoded table — so once `reads.lua`'s charmap becomes
profile-driven (§4.3), `encode_nickname` inherits the fix automatically with **no code change
in this file**. This is worth calling out explicitly because it means row 28's `boxes.lua` risk
is fully absorbed by row 18's `reads.lua` fix, provided nobody "helpfully" re-inlines a second
charmap table here later.

**Remaining row-28 risk:** `boxes.lua` never round-trips a *stored* nickname through
`encode_nickname` unless the server supplies a new one (`self.party_mon(key, base_stats,
nickname, stats)`, line 408, only calls `encode_nickname` `if nickname ~= nil` at line 444) —
the default path keeps `nick = original.nick` (raw bytes, line 442), which is exactly the
"raw name bytes authoritative for withdraw/rebuild" rule **[PLAN §4 row 28]** asks for. No
change needed on the default path; only the player-supplied-nickname path depends on §4.3's
charmap fix.

**Unit test:** `W/tests/unit/test_gen1_boxes.py:553
test_nickname_override_uses_english_charmap_not_cached_stats` already exercises exactly this
seam. Mirror it with a pureRGB charmap fixture whose token set includes the `$33-$4D`
text-shortcut bytes and assert `encode_nickname` either round-trips them or fails closed with a
clear reason (never silently drops a shortcut byte) — this needs an explicit product decision
during M1 (**UNVERIFIED**: does the pure client ever need to *write* a shortcut-compressed
nickname, or only decode one the game already wrote? If write is never needed, `encode_nickname`
can refuse any name containing a shortcut token, which is simpler and safer than round-tripping
compression).

---

## 9. `lua/gen1/panel.lua`

**Current:** `local MAILBOX = 0xDEE2` (line 14) and every derived offset (`ABI`, `CAPS`,
`STATE`, `PAGE`, `PAGES`, lines 16-20) are computed from that literal. Per **[PLAN A4]**, the
overlay build's mailbox lives at a linker-placed address in the bank-1 tail, not `$DEE2` (which
collides with pureRGB's box data even before the overlay is considered, per **[PLAN A9]**:
`wBoxDataEnd` moved to `01:DEEA`, so `$DEE2` is now *inside* pureRGB's box struct, not free
WRAM at all).

**New:** `P.new(profile, io, writes, sanitize)` reads `profile.trade.mailbox` (new field, §0)
instead of the module-level `MAILBOX` constant; `ABI`/`CAPS`/`STATE`/`PAGE`/`PAGES` become
computed at `P.new` time from that value rather than at module-load time from a literal. The
`BEACON` bytes (`'SLNK'`, line 15) stay numeric and foundation-agnostic — the panel never sends
them through pureRGB's charmap (unlike the companion patch's own `'S'` character-literal bug
**[PLAN S3]**, which is an overlay-source concern, not a Lua-side one). `TILES`/`ROWS`/`COLS`/
`MAX_PAGES`/`DEADLINE`/`CAP_PANEL` stay module constants — they describe the *shared* panel
protocol (18×20 tiles, capability bit layout), which per **[PLAN A4]** does not change between
the two foundations' overlay builds (same mailbox ABI version 3, same `SLT1` lease v1).

**Unit tests to extend:** `W/tests/unit/test_gen1_panel.py` (11 test functions found, e.g.
`test_present_abi_and_awaiting_read_the_mailbox` line 279, `test_every_write_lands_inside_the_
allow_set` line 246) and `W/tests/unit/test_gen1_panel_capability.py` /
`test_gen1_panel_tiles.py` (both present per `ls`). None currently parametrise over a mailbox
address other than `0xDEE2`; add a pureRGB-overlay fixture profile with a different
`trade.mailbox` value and re-run the same assertions.

---

## 10. `lua/gen1/trade_overlay.lua`

**Current:** `T.service_address()` (module function, lines 27-30) hardcodes
`{bank = 0x3F, addr = 0x4500}`; `local MAGIC = {0x53, 0x4C, 0x54, 0x31}` (`'SLT1'`, line 5) and
the lease offsets (`overlay+5` RELEASE, `overlay+6` generation, `overlay+7` ack, `overlay+8`
result, `overlay+10..` mask/token — used throughout `answer_query`/`answer_offer`/`arm`/
`poll_done`/`release`) are all relative to `ram.wSerialPartyMonsPatchList` (already
profile-driven, line 40: `local overlay = assert(ram.wSerialPartyMonsPatchList)`), so the
16-byte lease *contents* protocol is foundation-agnostic by construction — only the fixed
service-routine address is hardcoded.

**New:** `T.service_address()` is replaced by reading `profile.trade.service` (new field, §0);
the module function form is kept as a fallback default equal to today's vanilla value, or
dropped entirely once every caller passes the profile through (`client.lua:1137` currently
calls `self.trade.service_address()` with a hardcoded fallback `{bank=0x3F, addr=0x4500}` — that
fallback must also become `profile.trade.service`, not a second hardcoded literal; see §13.13).
`MAGIC`/`VERSION`/`QUERY`/`OFFER`/`PROMPT`/`APPLY`/`DONE`/`RELEASE` (lines 5-6) stay module
constants — **[PLAN M3]** confirms the `SLT1` lease v1 and ABI version are unchanged for the
overlay build ("the `SLT1` magic and the species/name tables are numeric `db`s and
charmap-immune").

**Unit test:** `W/tests/unit/test_gen1_trade_overlay.py` (5 functions, e.g.
`test_arm_stages_enemy_preimage_and_publishes_generation_last` line 133,
`test_query_mask_token_and_ack_order` line 88) — add a pureRGB-overlay fixture with a different
`{bank,addr}` for `service_address` and re-run unchanged; the lease-protocol tests themselves
need no logic change since they never touch bank/addr directly.

---

## 11. `lua/gen1_write_safety.lua`

**Current — the whole `M.check` function (lines 6-71) is one hardcoded vanilla predicate:**
```lua
if not rom_matches(p.irq_vector, instruction(0xC3, p.vblank_entry))
    or not rom_matches(p.delay_frame, {0x3E, 1, 0xE0, p.vblank_flag % 256,
        0x76, 0xF0, p.vblank_flag % 256, 0xA7})
    or not rom_matches(p.overworld_loop, instruction(0xCD, p.delay_frame))
    or not rom_matches(p.overworld_loop_less_delay, instruction(0xCD, p.delay_frame)) then
    return false, "cartridge checkpoint instructions differ"
end
...
local resume = byte(sp) + 256 * byte(sp + 1)
local caller = byte(sp + 2) + 256 * byte(sp + 3)
if resume ~= p.delay_frame + 5
    or (caller ~= p.overworld_loop + 3 and caller ~= p.overworld_loop_less_delay + 3)
    or byte(p.vblank_flag) ~= 1 then
    return false, "main thread is not waiting in the overworld loop"
end
```
This is **[PLAN §4 row 12]**'s exact failure mode: pureRGB's `OverworldLoop` calls `DelayFrame`
via a 1-byte `rst _DelayFrame`, not the 3-byte `call DelayFrame` the `instruction(0xCD, ...)`
helper checks (lines 41-42); `DelayFrame`'s body is 31 bytes with `halt` at `+23` and additional
instructions the 8-byte literal at lines 39-40 does not account for
(`ld a,[hLoadedROMBank]/ld [wDelayFrameBank]/call home_PrepareOAMData` inserted before the
`halt`, per **[PLAN §3.1]**); the resume offset is `+24` not `+5`; the caller offset is `+1` not
`+3`; and **there is no `wDelayFrameBank`/`WRAM BANK` check anywhere in this file**, which the
pureRGB checkpoint predicate requires (`wDelayFrameBank==0`, `WRAM BANK ∈ {0,1}` — confirmed
live, **[PLAN §11.2 Live]**: "the pure checkpoint predicate is exactly A5's: `PC == $0040`,
`[SP] == DelayFrame+24`, `[SP+2] == OverworldLoop+1`, `wDelayFrameBank == 0`, `WRAM BANK ∈
{0,1}`, plus the vanilla WRAM predicates").

**New:** every hardcoded number/byte-array above moves into `checkpoint.write_safe` (§0's new
fields):
1. `rom_matches(p.delay_frame, bytes_of(p.delay_frame_bytes))` replaces the literal 8-byte array
   — `delay_frame_bytes` is a hex string the generator slices straight from the built ROM (same
   "expected_hex" pattern `signals.lua`/`engine_signals.json` already use for engine sites, so
   this brings `write_checkpoint.json` up to the same evidentiary standard the plan's B6
   "RC generator standard" already applies elsewhere).
2. `rom_matches(p.overworld_loop, ...)`/`rom_matches(p.overworld_loop_less_delay, ...)`: the
   `instruction(0xCD, p.delay_frame)` helper (3-byte `call`) becomes a second
   `checkpoint.write_safe` byte-pattern field (e.g. `overworld_loop_call_bytes`), since pureRGB's
   is a 1-byte `rst` opcode, not a `call` — the *shape* of the check (fixed bytes at a fixed
   offset) survives; only the byte count and value are data now.
3. `resume ~= p.delay_frame + 5` → `resume ~= p.delay_frame + p.resume_offset`.
4. `caller ~= p.overworld_loop + 3 and caller ~= p.overworld_loop_less_delay + 3` →
   `caller ~= p.overworld_loop + p.caller_offsets[1] and caller ~= p.overworld_loop_less_delay +
   p.caller_offsets[2]`.
5. New final check appended to the function: read `wDelayFrameBank` via `byte(p.delay_frame_
   bank_addr)` and assert it equals `p.delay_frame_bank_expected` (0); read
   `io.register("WRAM BANK")` and assert membership in `p.wram_bank_register_allowed`. Both are
   **additive** — vanilla's `write_checkpoint.json` gets `delay_frame_bank_expected = 0` and
   `wram_bank_register_allowed = [1]` (vanilla's own checkpoint was measured as `WRAM BANK == 1`
   in practice, but confirm against the existing vanilla live gate before narrowing it —
   **UNVERIFIED, do not tighten vanilla's accepted set without re-running its own live gate**),
   so the function's shape is identical for both foundations; only the JSON differs.

**Unit tests to extend:** `W/tests/unit/test_gen1_safe_state.py` — every one of its 11 functions
pins some slice of this exact logic: `test_every_title_has_a_verified_checkpoint` (line 90,
parametrised over `title` already — extend the parametrisation to include a pureRGB profile
fixture), `test_the_cpu_must_be_parked_in_the_verified_loop` (line 134, the resume/caller-offset
check), `test_a_changed_cartridge_is_never_trusted_from_cache` (line 147, the ROM-byte
re-verification-on-every-call discipline — must keep passing unchanged since `M.check` still
verifies from scratch every call), `test_a_profile_without_the_verified_version_refuses` (line
159, `M.VERSION = "gen1-main-loop-v1"` gate at line 9 — **decide whether pureRGB bumps this
version string; if the *shape* of `write_safe` gains fields, old cached profiles without them
must fail this check rather than silently reading `nil` fields, so bumping to
`"gen1-main-loop-v2"` once the new fields are mandatory is the safer default**).

---

## 12. `lua/gen1/client.lua`

This is the largest file (1210 lines) and touches the most rows. Organized by row/bullet, not
strictly by line order.

### 12.1 Row 1 (routing) — no direct change

`client.lua` never inspects the ROM header or title string beyond storing
`self.rom_type`/`self.rom_sha1` (constructor, line 128) for the `hello` payload (line 923). No
change needed here; §2 covers the whole detection path.

### 12.2 Row 7 — ball items (`local BALL_ITEMS`, line 87; `ball_count`, lines 202-207)

**Current:**
```lua
local BALL_ITEMS = { [1] = true, [2] = true, [3] = true, [4] = true } -- MASTER..POKE
...
local function ball_count()
    local bag = reads.read_bag()
    local n = 0
    if bag then for _, it in ipairs(bag.items) do if BALL_ITEMS[it.id] then n = n + it.qty end end end
    return n
end
```
**New:** `BALL_ITEMS` moves from a module-level literal to a table built once in `Client.new`
from `d.ball_items` (§0's new `derived.ball_items` array): `local BALL_ITEMS = {}; for _, id in
ipairs(d.ball_items) do BALL_ITEMS[id] = true end`. `ball_count`'s body is unchanged; it already
only consults the (now-parametrised) table.

**Unit test:** no dedicated `ball_count` test found by name; it's exercised indirectly through
`test_gen1_client.py`'s hello/tick tests (`has_pokeballs`/`ball_count` fields appear in
`send_hello`/`send_tick`, lines 924-925, 947). Extend whichever hello/tick test asserts
`ball_count` with a pureRGB profile whose bag contains an item id `5` or `8` (HYPER_BALL/Safari
Ball-equivalent) and confirm it counts.

### 12.3 Row 10 — NPC-trade/Bill's-Garden `$80` discriminator (`on_signal`, lines 684-697)

**Current:**
```lua
elseif k == "add_party_mon" or k == "capture_box" then
    local loc = pt.mon_location or 0
    if k == "add_party_mon" and loc % 16 ~= 0 then
        -- ReadTrainer building the ENEMY party through the same routine: not ours
    elseif k == "add_party_mon" and loc == 0x80 then
        -- NPC in-game trade appending the incoming mon: the npc_trade signal owns it
    elseif self.pending_change and self.pending_change.kind == "npc_trade" then
        -- already tracking the trade; the key_change settles it
    else
        self.pending_change = { kind = "acquire", ... }
    end
```
Line 688's `loc == 0x80` branch assumes *every* `wMonDataLocation == $80` acquisition is the NPC
trade's own append and silently drops it as "the npc_trade signal owns it." Per **[PLAN §4 row
10]**, pureRGB's Bill's Garden capture (a reachable wild encounter, alt-palette Pikachu) uses
*exactly* `$80` too (**[PLAN §3.4]**: "Bill's Garden Pikachu is added with
`wMonDataLocation=$80` (no naming)"), so this branch would silently swallow a legitimate wild
capture as if it were an in-flight NPC trade.

**New:** replace the `loc == 0x80` special case with the row's own prescribed fix — discriminate
by `pt.in_battle == 1` (the wild-capture test the client already uses elsewhere, e.g.
`acquisition_point`'s `in_battle` field, `signals.lua:119`) combined with
`self.pending_change.kind == "npc_trade"` (the branch immediately below, line 690, already the
*correct* discriminator for an actual in-flight trade). Concretely: drop the `loc == 0x80`
elseif entirely; let `$80` acquisitions fall through to the existing
`self.pending_change.kind == "npc_trade"` check (which correctly suppresses them **only** when a
trade is actually pending) and otherwise treat them as an ordinary `acquire` (Bill's Garden is
`pt.in_battle == 1`, `pc.to_box == false`, gift-or-not exactly like any other wild capture).

**Unit test:** `W/tests/unit/test_gen1_client.py:434
test_enemy_party_build_and_npc_trade_do_not_look_like_captures` is the exact test this row must
not regress (it presumably asserts the `loc % 16 ~= 0` and `loc == 0x80` suppressions both still
work for the *actual* NPC-trade case). Add a new case in the same test (or a sibling) with
`pending_change == nil`, `loc == 0x80`, `in_battle == 1` and assert it **is** reported as a
capture (the Bill's-Garden scenario) — today's code would drop it.

### 12.4 Row 11 / M2-b trainer-staging gate (`on_signal`, line 628, 633)

**Current:**
```lua
self.battle = { frame = sig.frame, wild = pt.cur_opponent < 200, species = pt.species, ... }
...
if not self.battle.wild then send("trainer_battle_start", { trainer_id = pt.cur_opponent }) end
```
Two problems, both **[PLAN §4 row 11]** / **[PLAN M2-b]**: the literal `200` (fixed by §0's
`derived.opp_id_offset` the same way as `reads.lua`, §4.2), and — per the live research finding
(**[PLAN §11.2 Live 2]**) — `_InitBattleCommon+$48` fires once with `wCurOpponent == 0` right
after the starter pick (a non-battle caller sharing the same address/offset), which today would
be misclassified as `wild = true` (`0 < 200`) and, worse, could reach the
`send("trainer_battle_start", ...)` branch if the offset ever lands on a "trainer-looking" spurious value.

**New:** guard `trainer_battle_start` on `pt.cur_opponent >= d.opp_id_offset` explicitly (not
merely `not wild`), so a spurious `cur_opponent == 0` fire is inert regardless of how `wild` is
computed: `if pt.cur_opponent >= d.opp_id_offset then send("trainer_battle_start", { trainer_id
= pt.cur_opponent }) end`. This also fixes a latent vanilla-adjacent bug: today's `not
self.battle.wild` is `true` whenever `cur_opponent >= 200`, which is equivalent *only* if
`opp_id_offset` is always `200` — once it's data, the two conditions must be written as the same
expression, not as complementary ones, to avoid them drifting apart under a future
foundation-specific edit.

**Unit test:** `W/tests/unit/test_gen1_client.py:407
test_trainer_battle_start_is_sent_once_with_the_200_form_id` is the exact test to extend: add a
`cur_opponent == 0` fixture (mirroring the Live-2 finding) and assert no
`trainer_battle_start` is sent; add a pureRGB-profile case with `opp_id_offset=197` and
`cur_opponent=200` (a valid pure trainer id) asserting it *is* sent.

### 12.5 Row 12 checkpoint — no direct `client.lua` change

`client.lua` calls `safety.check(ws_profile, io)` opaquely (`run_deferred` line 515,
`frame_end` line 1169) and never inspects the checkpoint's internals — §11's fix is fully
contained in `gen1_write_safety.lua` and the `write_checkpoint.json` it's handed. No change
needed here.

### 12.6 Row 19 / M2-b — `key_change` reasons and alias-until-ack (`settle_pending_change`,
lines 848-860; `handle_command`, lines 312-392)

**Current:**
```lua
elseif pc.kind == "evolution" or pc.kind == "npc_trade" then
    local key, mon = key_at(party, pc.slot)
    if not key then self.pending_change = nil return end
    if key ~= pc.old_key then
        self.known_keys[pc.old_key] = nil
        self.known_keys[key] = true
        send("key_change", { old_key = pc.old_key, new_key = key, new_species = mon.species,
                             reason = pc.kind == "evolution" and "evolution" or "npc_trade",
                             new_nickname = mon.nickname })
        self.pending_change = nil
    elseif self.frame - pc.frame > 300 then
        self.pending_change = nil -- trade declined / evolution cancelled
    end
```
Two gaps relative to **[PLAN §5.2 A1]**'s acknowledged contract: (1) `reason` is a ternary over
exactly two literal strings — adding `"transform"`/`"apex_chip"` means widening `pc.kind`'s
domain and this ternary into a lookup, not adding a third branch by hand; (2) there is **no
ack/rollback at all** — `self.known_keys` is mutated and `self.pending_change` is cleared
*immediately* on send, before any server acknowledgement. `handle_command`'s dispatch (lines
312-392) has no case for `key_change_ack`/`key_change_rejected` — an unrecognised command falls
through to the generic `else log("unknown command")` at line 390, so today a server that sent
those commands would just be logged as noise, with no protocol effect.

**New:**
1. `settle_pending_change`'s evolution/npc_trade/transform/apex_chip branches unify on a
   `reason` looked up from `pc.kind` (a small table `{evolution="evolution", npc_trade=
   "npc_trade", transform="transform", apex_chip="apex_chip"}` rather than a growing ternary
   chain).
2. On send, **do not** clear `self.known_keys[pc.old_key]` or `self.pending_change` yet. Instead
   set `self.pending_change = { kind = "awaiting_key_change_ack", old_key = pc.old_key, new_key
   = key, since = self.frame }` and keep **both** `old_key` and `new_key` in `known_keys` (an
   "alias") until the ack arrives — this is what "alias-until-ack" means concretely: any inbound
   command naming `pc.old_key` in the meantime (e.g. a `force_faint` the server sent before it
   learned about the rename) must still resolve via `find_party_slot`, which already keys off
   the *live* cartridge bytes (`mon_key(m)`, unaffected by this bookkeeping) — so the alias is
   really about not prematurely forgetting `old_key` in `self.known_keys` for the "is this a
   brand-new mon" acquisition heuristic (`settle_pending_change`'s `acquire` branch, line 816),
   not about routing commands.
3. `handle_command` gains two new cases: `"key_change_ack"` clears the
   `awaiting_key_change_ack` pending state and finally drops `old_key` from `known_keys`;
   `"key_change_rejected"` per **[PLAN U5]** ("the pair dies: the old key's link → DEAD
   `cause=identity_lost`") is a **server-side** state transition — the client's only
   responsibility on rejection is to log it and drop the stale `pending_change`/alias
   bookkeeping; it does not itself force-faint anything (the server will send an explicit
   `force_faint` command for that, through the existing `force_faint` path, §13.6-equivalent).
4. A collision timeout: if no ack/rejection arrives within a bound (mirror the existing 300-frame
   cancel timeout at line 858, reused rather than reinvented) treat it as an implicit ack
   (idempotent — matches **[PLAN §5.2 A1]**'s server-side idempotent-replay rule) rather than
   re-sending, since `key_change` has no defined retry semantics today.

**Unit test:** `W/tests/unit/test_gen1_client.py:528 test_evolution_emits_key_change_with_
reason` is the direct template — extend it to (a) assert `known_keys` still contains `old_key`
immediately after the send (today it would already be gone — this is the behaviour change to
verify), (b) feed a `key_change_ack` command through `handle_command` and assert `old_key` is
now gone, (c) feed a `key_change_rejected` command and assert the client logs it and does not
crash on the unknown-command path it previously fell into.

### 12.7 Row 24 — daycare withdrawal (`on_signal`'s `move_mon` branch, lines 698-719)

**Current:**
```lua
if pt.move_type == MOVE_PARTY_TO_BOX or pt.move_type == MOVE_PARTY_TO_DAYCARE then
    ...
elseif pt.move_type == MOVE_BOX_TO_PARTY or pt.move_type == MOVE_DAYCARE_TO_PARTY then
    local box = reads.box_from_snapshot(pt.box or {})
    local key = box and key_at(box, pt.which)
    if key then send("box_to_party", { key = key, area_id = area_id }) end
end
```
`MOVE_DAYCARE_TO_PARTY` (constant `= 2`, line 96) is folded into the exact same branch as
`MOVE_BOX_TO_PARTY`, reading the mon out of `pt.box` — the *box* snapshot's shape
(`storage_point`, `signals.lua:140-147`, which reads `wBoxCount`/`wBoxData`), not the daycare's
own `wDayCareMon`. Per **[PLAN §4 row 24]**, a daycare withdrawal never touches the box at all
(`MoveMon(DAYCARE_TO_PARTY)` reads `wDayCareMon` directly and appends at `wPartyCount-1`), so
this branch is decoding the wrong memory for that case — it happens to not crash today only
because `reads.box_from_snapshot` tolerates whatever bytes are there, but the *box* it decodes
is unrelated to the mon that actually moved.

**New:** split the branch on `pt.move_type`:
```lua
elseif pt.move_type == MOVE_BOX_TO_PARTY then
    local box = reads.box_from_snapshot(pt.box or {})
    local key = box and key_at(box, pt.which)
    if key then send("box_to_party", { key = key, area_id = area_id }) end
elseif pt.move_type == MOVE_DAYCARE_TO_PARTY then
    -- new daycare_withdraw site (signals.lua §6.1) fires alongside/instead of this move_mon
    -- hook; its point carries the daycare snapshot directly (reads.lua §4.4's read_daycare_mon
    -- shape), and the key comes from the READBACK at wPartyCount-1 after settle, per the row's
    -- prescribed mechanism, not from pt.which against a box.
    self.pending_change = { kind = "daycare_withdraw", frame = sig.frame }
end
```
The actual key/species readback happens in `settle_pending_change` (mirroring the existing
`acquire` branch's "read after the engine is done, not from the signal's own snapshot" pattern,
lines 810-847) rather than trying to decode it synchronously inside `on_signal` — this keeps the
"which slot does `wPartyCount-1` name" question answered by a live read at settle time, the same
discipline row 25's NPC-trade readback needs (§12.8).

**Unit test:** `W/tests/unit/test_gen1_client.py:516
test_pc_moves_come_from_the_movemon_signal_direction` is the existing test for this whole
branch; extend it with a `MOVE_DAYCARE_TO_PARTY` case whose `pt.box` snapshot is *empty/garbage*
(simulating "the daycare doesn't touch the box at all") and assert the client does **not** try
`box_from_snapshot` on it, instead following the new `daycare_withdraw` path.

### 12.8 Row 25 — NPC-trade identity from removal + readback (`on_signal`'s `npc_trade` branch,
lines 791-794; `remove_pokemon` branch, lines 720-785)

**Current:** a single `npc_trade` signal (`S.KINDS.npc_trade`, `signals.lua:172-179`) fires once
at `InGameTrade_DoTrade+0` and captures `pt.which` as the pre-trade slot; `on_signal` stashes
`{kind="npc_trade", slot=pt.which, old_key=key}` (line 794) and later, when the party changes
(via the generic `remove_pokemon`/`add_party_mon` signals), `settle_pending_change`'s
`evolution`-shared branch (§12.6) reads `key_at(party, pc.slot)` — i.e., it re-reads the **same
slot index** `pc.slot` and expects the new mon to be there. Per **[PLAN §4 row 25]**, the actual
engine order is: selection happens *inside* the routine (not at `+0`), `RemovePokemon` **compacts
the party** (shifting every later slot down), and the received mon is *appended* — so `pc.slot`
may no longer even exist, or may now hold a different, shifted-down mon, by the time
`RemovePokemon` finishes.

**New:** replace the single `npc_trade` site with the two sites `npc_trade_remove` (at `+$7B`,
after selection but at the removal call) and `npc_trade_done` (at `+$89`, after the append)
per §6.1. `on_signal`'s new branches:
```lua
elseif k == "npc_trade_remove" then
    local party = party_from_snapshot(pt.party or {})
    local key = party and key_at(party, pt.which)
    if key then self.pending_change = { kind = "npc_trade", frame = sig.frame, old_key = key } end
elseif k == "npc_trade_done" then
    -- readback: the received mon is always the LAST slot, never pc.slot
    self.pending_change = self.pending_change or {}
    self.pending_change.kind, self.pending_change.frame = "npc_trade", sig.frame
    self.pending_change.readback_last_slot = true
```
`settle_pending_change`'s `npc_trade` case switches from `key_at(party, pc.slot)` to "the last
party entry" (`party[#party]`) when `pc.readback_last_slot` is set — mirroring the pattern
`client.lua:1092-1093` already uses for the *native cable trade* apply path
(`local received = party and party[#party]`), which is the same "appended at the end" shape.
This unifies two already-similar-but-separately-written readback idioms in the file (native
trade apply vs. NPC trade) onto one helper, which is also a reasonable place to name a small
`last_party_entry(party)` function shared by both call sites.

**Unit test:** `W/tests/unit/test_gen1_client.py:1756
test_a_removal_inside_an_npc_trade_keeps_the_pending_key_change` already exercises the
"`remove_pokemon` fires mid-NPC-trade and must not be misread as a standalone release" half of
this; extend it (or add a sibling) asserting the *new key* comes from the last party slot after
`npc_trade_done`, not from `pc.slot`, using a fixture where the removed mon was NOT the last
slot pre-trade (forcing a compaction shift) so a `pc.slot`-based readback would provably name
the wrong mon.

### 12.9 M2-b — witness-based battle-outcome classifier (`on_signal`'s `battle_end`, lines
651-672)

**Current:**
```lua
elseif k == "battle_end" then
    local b = self.battle
    if b and b.demo then
        ...
    elseif b and b.wild and not b.captured and not self.resolved_areas[b.area_id] and b.area_id ~= "" then
        if TOWER_MAPS[b.map] and reads.has_item(SILPH_SCOPE) ~= true then
            ...
        elseif not self.has_pokeballs then
            ...
        else
            send("no_catch", { area_id = b.area_id, species_id = b.species, level = b.level })
            self.resolved_areas[b.area_id] = true
        end
    end
```
Confirmed by direct read: this branch **never inspects `pt.result` / `wBattleResult`** at all,
even though `signals.lua`'s `S.KINDS.battle_end` point (lines 105-111) already captures it
(`p.result = io.read_u8(ram.wBattleResult, "System Bus")  -- 0 won, 1 lost, 2 ran`) and
`reads.lua:255` also reads it. This is exactly the inherited gap **[PLAN §2.3]** documents:
"the client never inspects `wBattleResult`... an acquisition counts as a capture for any
nonzero `wIsInBattle`." A `no_catch` is sent purely from "wild battle ended, nothing was
captured, area unresolved" — it cannot currently distinguish a loss/blackout, a RUN, or a
TELEPORT/ROAR/WHIRLWIND-forced end from a genuine "the player fought and neither caught nor
fled" outcome, which per **[PLAN M2-b]** must be classified by the correct signals
(`wBattleFunctionalFlags` bit 1 for RUN success; TELEPORT/ROAR/WHIRLWIND end the battle;
SCREECH does not).

**New:** add a witness-based classification step at the top of the `battle_end` branch, before
the existing `no_catch` logic:
1. Read `pt.result` (already in the point, just unused) and `wBattleFunctionalFlags` bit 1 (new
   read — `reads.lua` needs a `read_battle_functional_flags()` accessor, or fold the bit into
   `read_battle()`'s existing return table).
2. If the battle ended via RUN success, TELEPORT, ROAR, or WHIRLWIND, treat it as "the player
   did not get a fair shot at this encounter" and suppress `no_catch` entirely (do not mark the
   area resolved) — this is a **new** suppression, not present today at all (today *any*
   non-captured wild `battle_end` sends `no_catch` regardless of how the battle ended, other
   than the Tower-ghost and no-Poke-Balls-yet exceptions already coded).
3. SCREECH does **not** end the battle (it's a stat-stage move), so it never reaches
   `battle_end` in the first place — no code change needed for it; it's called out in the plan
   only to say "don't add a suppression for it by mistake."

**Unit test:** `W/tests/unit/test_gen1_client.py:312
test_wild_battle_without_capture_emits_no_catch_with_species` is the exact test whose current
"no_catch" trigger conditions this row narrows — extend with a RUN-success fixture
(`wBattleFunctionalFlags` bit 1 set) and assert `no_catch` is **not** sent, versus today where
(per the current code path) it would be.

### 12.10 M2-b — `wLinkState != 0` key-reconciliation suppression

**Current:** confirmed by direct read — **no code in `client.lua` reads `wLinkState` during
`settle_pending_change`, `on_signal`'s evolution/npc_trade branches, or anywhere in the
key-change path.** `reads.lua:255` reads `wLinkState` only as part of the generic
`read_battle()` payload (used for the `hello`/`tick` wire shape, `client.lua:927`), and
`signals.lua`'s `battle_loop_head`/`opponent_point` points also capture it (lines 86, 101) but
`client.lua` never inspects those fields for this purpose.

**New:** `settle_pending_change`'s evolution/npc_trade/transform/apex_chip branches must check
`reads.read_battle().link_state ~= 0` and, if true, **defer** the settle (leave
`self.pending_change` untouched, retry next frame) rather than resolving a key change while
Cable Club link code is actively rewriting party bytes (`$FE→$FF`), per **[PLAN M2-b]**. This is
a guard added at the top of the relevant `settle_pending_change` branches, not a new signal.

**Unit test:** none exists today (confirmed — no test file matched `wLinkState`/link-state
key-change interaction). New test needed in `test_gen1_client.py`, mirroring the shape of the
existing `evolution`/`npc_trade` tests but with `wLinkState` nonzero during the settle window,
asserting the `key_change` send is delayed until it clears.

### 12.11 M2-b — `wGameInternalVersion` gate

**Current:** `send_hello`/`frame_end` (lines 905-933, 1150-1201) have **no version check of any
kind** — confirmed by direct read of the whole file; there is no `wGameInternalVersion` symbol
reference anywhere in `client.lua`, `reads.lua`, or `signals.lua`.

**New:** `frame_end`'s hello-gating condition (line 1168-1171,
`if connected and not self.hello_sent and game_is_live() and (reads.read_battle().in_battle ~= 0
or safety.check(ws_profile, io)) then self:send_hello() end`) gains a version check: read
`wGameInternalVersion` (new `reads.lua` accessor, mirroring `read_save_file_status`'s one-liner
shape, line 268) and refuse to hello (log + hold, do not `pcall`-crash) when it differs from
`profile.derived.pinned_game_internal_version` (new field — **not listed in §0's table above
because it is pureRGB-specific plumbing for the save-file updater, not a foundation-selection
concern; add it under `derived` alongside the others**). Per **[PLAN §4 row title "pureRGB
status"]**: "the updater saves before stamping the version," so this must be a hard refusal, not
a soft warning — a mid-update save could otherwise be treated as live.

**Unit test:** new — no existing test touches `wGameInternalVersion`. Add to
`test_gen1_client.py` alongside the other hello-gating tests (`test_hello_waits_for_the_
overworld_checkpoint_not_the_main_menu`, line 583, is the closest existing template for
"hello is gated on a WRAM predicate, not just connectivity").

### 12.12 M2-b — `safari_type` in the battle payload

**Current:** `enemy_party`/`send_tick` (lines 193-200, 935-954) build the battle payload from
`reads.read_battle()`'s fields (`in_battle`, `cur_opponent`, `is_trainer`, `enemy_species`,
`enemy_level`, `enemy_hp`, `battle_mon_hp`, `player_mon_number`, `result`, `link_state` — the
full set returned by `reads.lua:248-255`); none of these is `safari_type`. `wSafariType` is not
referenced anywhere in `reads.lua`/`client.lua` today.

**New:** `reads.read_battle()` gains a `safari_type` field (new WRAM read,
`io.read_u8(a.wSafariType)`); `send_tick`'s payload (lines 946-953) carries it through as
`safari_type = battle.safari_type`. Per **[PLAN §3.5]**, only `SAFARI_TYPE_CLASSIC` sets
`BATTLE_TYPE_SAFARI` — FREE ROAM/RANGER HUNT battles in Safari maps are otherwise ordinary
battles, so the server needs this field to apply Safari-specific rules (ball consumption,
capture semantics) correctly only for the classic sub-mode.

**Unit test:** extend `test_gen1_reads.py`'s `_seed_ancillary`/`_snapshot` fixtures (§4.1's
template) with `wSafariType` and assert it appears in `read_battle()`'s return table; extend
whichever `test_gen1_client.py` tick test asserts the wire payload shape.

### 12.13 M2-b — `trade_service` on_fire wiring extended for `apex_commit`/`transform`
(`self:start`, lines 1131-1148)

**Current:**
```lua
function self:start()
    local handlers = { battle_loop_head = function(sig) self:on_battle_loop_head(sig) end }
    local all_sites = sites
    if self.trade and self:trade_patch_present() then
        ...
        handlers.trade_service = function() self.trade:picked_up() end
        self.trade_enabled = true
    end
    self.signals = signals_mod.new(profile, all_sites, io, handlers)
end
```
Confirmed: `handlers` (the `on_fire` table `signals.lua:184-223` invokes synchronously inside
the bus-exec callback) has exactly two possible entries today. Per §7.1/§6.1, two more kinds
need synchronous on-fire handlers.

**New:**
```lua
handlers.apex_commit = function(sig) self:on_apex_commit(sig) end
handlers.transform = function(sig) self:on_transform(sig) end
```
with `self:on_apex_commit`/`self:on_transform` new methods (mirroring `self:on_battle_loop_head`,
lines 870-902, in structure: read the signal's `point`, decide whether the write applies, `arm`
the matching `writes.lua` window from §7.1, write, `disarm`). The `apex_commit` handler also
owns the "collision set" computation **[PLAN §5.2 A1]** describes (scan `known_keys` plus a
fresh box scan, refreshed on every PC/`move_mon`/`remove_pokemon` site) — this is new,
non-trivial logic that belongs in `client.lua` (it needs `self.box_cache`/`self:rescan_boxes`,
already present, lines 219-239) rather than in `writes.lua` (which only knows how to write, not
which keys are live).

**Unit test:** new — mirror `W/tests/unit/test_gen1_client.py`'s `on_battle_loop_head`-adjacent
tests (`test_active_force_faint_waits_for_the_battle_loop_head`, line 567, and
`test_a_battle_write_queued_before_a_pause_still_lands_at_the_loop_head`, line 645, are the
closest existing templates for "a synchronous on-fire handler applies a write and the rest of
the frame loop observes the result correctly").

### 12.14 `trade_overlay`/`panel` field wiring (`self:trade_patch_present`, lines 994-999;
`self:start`, line 1137)

**Current:**
```lua
function self:trade_patch_present()
    for i, b in ipairs(TRADE_DISPATCH) do
        if io.read_u8(0x29C3 + i - 1, "ROM") ~= b then return false end
    end
    return true
end
```
and (line 1137) `local svc = self.trade.service_address and self.trade.service_address() or
{ bank = 0x3F, addr = 0x4500 }`. Both hardcode the vanilla receptionist/service addresses
directly in `client.lua`, duplicating what `trade_overlay.lua` already (partially) encapsulates.

**New:** `TRADE_DISPATCH`'s check address (`0x29C3`) and the `{bank=0x3F,addr=0x4500}` fallback
both move to reading `profile.trade.receptionist_hook`/`profile.trade.service` (§0) — passed
into `Client.new` alongside the rest of `profile`, so no new constructor parameter is needed,
just no more module-level literals shadowing profile data.

**Unit test:** `W/tests/unit/test_gen1_trade_patch.py` (confirmed present) is the direct
template for `trade_patch_present`'s detection logic; extend with an overlay-profile fixture
whose `receptionist_hook` differs from `0x29C3`.

---

## 13. Summary — files touched vs. rows/bullets covered

| File | Rows | M2-b bullets |
|---|---|---|
| `slink.lua` | 1 (no direct change; downstream of entry.lua) | — |
| `entry.lua` | 1, 2 (routing) | hash-first admission, header-as-candidate-only |
| `run.lua` | 1 (glue only) | — |
| `reads.lua` | 6, 11, 18, 24 | safari_type, wGameInternalVersion accessor |
| `rom.lua` | 8, 16 | — |
| `signals.lua` | 9 (site list) | new site kinds, all-zero GUID, flat-WRAM reads |
| `writes.lua` | — | apex_commit/transform windows, WRAM BANK write gate |
| `boxes.lua` | 8 (delegates), 28 (delegates) | — |
| `panel.lua` | 20/A4 (mailbox address) | — |
| `trade_overlay.lua` | 20/A4 (service address) | — |
| `gen1_write_safety.lua` | 12 | wDelayFrameBank/WRAM BANK checkpoint predicate |
| `client.lua` | 1, 7, 10, 11, 12, 19, 24, 25 | battle-outcome classifier, trainer-staging gate, wLinkState suppression, wGameInternalVersion gate, safari_type, apex/transform on_fire wiring, key_change alias-until-ack |

Rows **13** (flat WRAM reads) and **28** (charmap round-trip, delegated from `boxes.lua` to
`reads.lua`) are cross-cutting and listed under their owning file (`signals.lua`+`entry.lua` for
13, `reads.lua` for 18/28).

Not in this brief's scope (server-side, cited for context only): `key_change_ack`/
`key_change_rejected` as new server reply commands and their `state.py` migration-ordering fix
(**[PLAN §5.2 A1, M2-c]**) — the client-side handling of those two commands (§12.6) depends on
the server actually sending them, which is a separate `server/state.py`/`server/server.py`
change outside `lua/`.
