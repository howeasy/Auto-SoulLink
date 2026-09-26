# BizHawk gamedb/mode (wayfinder 18) and Gen 2 encounter/area sources (wayfinder 21)

Retrieved 2026-09-21 unless noted. Resolves `docs/gen2/wayfinder/issues/18-cgb-mode-and-gamedb.md`
and `21-encounter-tables.md` (read, not edited).

## Pins

- BizHawk `2.11.1` tag = commit `bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5` (per
  `docs/gen2/research/bizhawk_gambatte_gbc.md` Pins, this worktree). All BizHawk URLs below are
  `raw.githubusercontent.com/TASEmulators/BizHawk/2.11.1/...`, retrieved 2026-09-21.
- pret HEAD clones (read-only, this session's scratchpad): `pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651`,
  `pokegold@656583c939d30f920a316177311a502dd222b57c` — both confirmed identical `HEAD` via
  `git rev-parse` in this pass, and both `roms.sha1` files byte-identical to the cached
  `.cache/pret` checkouts (`docs/gen2/research/rom_hashes.md` Pins).
- The four sha1s (from `rom_hashes.md`): Gold `d8b8a3600a465308c9953dfa04f0081c05bdcb94`, Silver
  `49b163f7e57702bc939d642a18f591de55d92dae`, Crystal 1.0 `f4cd194bdee0d04ca4eac29e09b8e4e9d818c133`,
  Crystal 1.1 `f2f52230b536214ef7c9924f483392993e226cfb`.

## A. BizHawk gamedb and mode

### A.1 gamedb file and per-title lines

Two GB-family gamedb files exist under `Assets/gamedb/` at `2.11.1`: `gamedb_gb.txt` (DMG-only
titles) and `gamedb_gbc.txt` (GBC titles) — confirmed via the tag's recursive tree listing
(`api.github.com/repos/TASEmulators/BizHawk/git/trees/2.11.1?recursive=1`, retrieved 2026-09-21).
None of the four sha1s appear in `gamedb_gb.txt` (searched full file); all four appear in
`gamedb_gbc.txt` (`https://raw.githubusercontent.com/TASEmulators/BizHawk/2.11.1/Assets/gamedb/gamedb_gbc.txt`,
retrieved 2026-09-21), verbatim (tab-separated, columns per A.2):

```
D8B8A3600A465308C9953DFA04F0081C05BDCB94	G	Pokemon - Gold Version (USA, Europe)	GBC
49B163F7E57702BC939D642A18F591DE55D92DAE	G	Pokemon - Silver Version (USA, Europe)	GBC
F4CD194BDEE0D04CA4EAC29E09B8E4E9D818C133	G	Pokemon - Crystal Version (USA, Europe)	GBC
F2F52230B536214EF7C9924F483392993E226CFB	G	Pokemon - Crystal Version (USA, Europe) (Rev A)	GBC
```

Status `G` = "Good dump" per the `Database.cs` status-char table (A.3). All four are `System = GBC`
— no `GB` entries for these hashes anywhere, i.e. BizHawk's gamedb makes Gold/Silver GBC-system
titles despite the cartridge itself being dual-mode (CGB-compatible, not CGB-only). No `metadata`
(5th), `region` (6th) or `forcedcore` (7th) column is populated on any of these four lines — the
line ends after the `System` field. **No MBC3/RTC-bearing flag anywhere in the gamedb line for
any of the four titles** — the gamedb format carries name/system/status only for these entries,
never a cart-type or RTC hint (open question: is this columnar absence, or does the format simply
never carry cart-type at all — not resolved from these 4 lines alone, see Open questions).

### A.2 Line format (`Database.cs`)

`ParseCGIRecord` in `src/BizHawk.Emulation.Common/Database/Database.cs`
(`https://raw.githubusercontent.com/TASEmulators/BizHawk/2.11.1/src/BizHawk.Emulation.Common/Database/Database.cs`,
retrieved 2026-09-21) splits each line on tab into, in order: (1) hash (optionally prefixed
`sha1:`/`md5:`), (2) status char, (3) name, (4) system id string, (5) metadata, (6) region,
(7) forced-core — trailing fields optional. Status chars include `G`=GoodDump, `B`/`V`=BadDump,
`T`=Translated, `O`=Overdump, `I`=Bios, `D`=Homebrew, `H`=Hack, `U`=Unknown.

### A.3 Hash lookup and fallback (`Database.GetGameInfo`)

`GetGameInfo(romData, fileName)` SHA-1-hashes the ROM bytes and looks the hash up in the
in-memory gamedb dictionary; on a miss it retries MD5, then CRC32; only if all three miss does
it fall back to a `NotInDatabase = true` `GameInfo` built from the file extension and file name
(`Database.cs:270-307`, cited already in `bizhawk_gambatte_gbc.md` §5 in this directory, same
retrieval pass). For all four sha1s here the SHA-1 hit is exact (A.1), so this fallback path
never triggers for a clean dump of Gold/Silver/Crystal.

### A.4 SaveRAM file names (per `bizhawk_gambatte_gbc.md` §5, restated per-title)

The `.SaveRAM` filename is `{game.FilesystemSafeName()}.SaveRAM`, and `game.Name` comes straight
from the gamedb `Name` field on a hash hit (§A.3). So, for a clean dump of each title:

| Title | SHA-1 | gamedb `Name` | `.SaveRAM` filename |
|---|---|---|---|
| Gold | `d8b8a360...` | `Pokemon - Gold Version (USA, Europe)` | `Pokemon - Gold Version (USA, Europe).SaveRAM` |
| Silver | `49b163f7...` | `Pokemon - Silver Version (USA, Europe)` | `Pokemon - Silver Version (USA, Europe).SaveRAM` |
| Crystal 1.0 | `f4cd194b...` | `Pokemon - Crystal Version (USA, Europe)` | `Pokemon - Crystal Version (USA, Europe).SaveRAM` |
| Crystal 1.1 | `f2f52230...` | `Pokemon - Crystal Version (USA, Europe) (Rev A)` | `Pokemon - Crystal Version (USA, Europe) (Rev A).SaveRAM` |

`FilesystemSafeName()` itself was not independently re-derived in this pass (assumed to be a
straight illegal-character strip, per its use already confirmed in `bizhawk_gambatte_gbc.md`
§5) — flagged in Open questions. Each of the four titles gets a DISTINCT gamedb `Name` (no
collision among these four, unlike the `crystal` vs `Pokemon - Crystal Version (USA, Europe)`
mismatch `tools/gen2_playthrough.py:56-64` already records for a differently-named local dump).

### A.5 `ConsoleMode.Auto` outcome per title

Per `bizhawk_gambatte_gbc.md` §4 (`Gambatte.cs` constructor, same retrieval pass): `Auto` sets
`CGB_MODE` purely from `game.System == VSystemID.Raw.GBC`, not from re-reading the cartridge's
own header CGB-compatibility byte at 0x143. Since gamedb classifies **all four** titles as
`System = GBC` (A.1), **`ConsoleMode.Auto` boots all four — Gold, Silver, Crystal 1.0, Crystal
1.1 — in CGB mode.** This holds even though Gold/Silver's cartridge header byte is `0x80`
(CGB-compatible, dual-mode — works on DMG too) and Crystal's is `0xC0` (CGB-only) — the gamedb
`System` string is the only input to `Auto`'s branch, so the dual-mode compatibility of
Gold/Silver's own header is irrelevant to what `Auto` actually does; running Gold/Silver in DMG
mode requires the sync setting explicitly set to `ConsoleMode.GB`.

**Consequence for fixtures/duos:** because `Auto` already lands on CGB for all four titles, a
fixture or duo does not need to pin `ConsoleMode` explicitly to get CGB behavior for Gen 2 — the
default already does. Pinning becomes necessary only if a scenario deliberately wants Gold/Silver
run in DMG-compatibility mode (a scenario this research did not find named anywhere in the
worktree) — recommend leaving `ConsoleMode = Auto` as the default and only setting it explicitly
if/when a DMG-mode Gold/Silver scenario is scoped.

### A.6 `.gbc` extension vs header byte vs gamedb — who decides `game.System`

Searched `src/BizHawk.Client.Common/RomLoader.cs`
(`https://raw.githubusercontent.com/TASEmulators/BizHawk/2.11.1/src/BizHawk.Client.Common/RomLoader.cs`)
for `VSystemID.Raw.GB`/`GBC` and any `0x143`/CGB header read: the loader's `case VSystemID.Raw.GB:
case VSystemID.Raw.GBC:` block (LoadOther, ~line 385) treats `.gb`/`.gbc` identically except for
`.gbs` (a music-file special case) and an opt-in `_config.GbAsSgb` override to `VSystemID.Raw.SGB`
— **no code path in `RomLoader.cs` inspects the ROM header's CGB-compatibility byte (0x143) at
all.** The one `GetGameInfo` call site actually feeding `game.System` is in `LoadXML`
(`Game = Database.GetGameInfo(pfd.FileData, Path.GetFileName(pfd.Filename))`, ~line 495) — i.e.
`game.System` is set from the gamedb hash lookup (§A.3), and the file extension only ever
narrows behavior (SGB opt-in, `.gbs` routing to the Sameboy core), never overrides or refines the
gamedb's system classification. So: **the gamedb entry is authoritative for `game.System`; the
`.gb`/`.gbc` extension and the cartridge's own header byte play no role in the DMG-vs-GBC
decision at load time** — a `.gbc`-extension dump of a byte-identical ROM to a `.gb`-extension
one would still classify identically, driven by the hash, not the filename. (This file's `.gbs`
branch and the `CGBNotSupportedException` message near line 700 were the only other CGB-adjacent
code found; neither reads the header byte either.)

### A.7 RTC tail on `.SaveRAM` — Gambatte source

`src/BizHawk.Emulation.Cores/Consoles/Nintendo/Gameboy/Gambatte.ISaveRam.cs`
(`https://raw.githubusercontent.com/TASEmulators/BizHawk/2.11.1/src/BizHawk.Emulation.Cores/Consoles/Nintendo/Gameboy/Gambatte.ISaveRam.cs`,
full file reproduced in this pass) shows `CloneSaveRam`/`StoreSaveRam` delegate entirely to the
native library: `CloneSaveRam` allocates `length = LibGambatte.gambatte_getsavedatalength(...)`
bytes and calls `gambatte_savesavedata(GambatteState, ret)` — **no C# code appends an RTC tail;
whatever length the native `gambatte_getsavedatalength` reports IS the `.SaveRAM` size**, and
that native call lives in the vendored `gambatte-core` C++ library (not fetched in this pass —
its length/serialization logic for an MBC3+RTC cart is †UNVERIFIED against BizHawk C# source
alone). This is consistent with, but does not itself independently re-derive, the project's own
measured fact at `tools/gen2_playthrough.py:67-71`: "A Crystal `.SaveRAM` is 32790 bytes, not
32768: BizHawk appends the cartridge's 22-byte RTC block after the four 8KB SRAM banks" — that
32790 = 32768 + 22 figure is a MEASURED fixture fact from a live BizHawk run, not something this
gamedb/C#-source pass can confirm independently (the 22-byte layout itself lives in native
gambatte, out of scope here). `StoreSaveRam` separately calls `gambatte_settime` under
`DeterministicEmulation`, confirming the native core treats RTC state as bundled with save data
(consistent with a length that includes an RTC tail) without pinning the tail's exact byte
layout from C# alone.

## B. Encounter and area sources

### B.1 Wild data files and format

`data/wild/*.asm` in both `pokecrystal@7a7881d` and `pokegold@656583c` (directory listing, this
pass): `johto_grass.asm`, `johto_water.asm`, `kanto_grass.asm`, `kanto_water.asm`, `fish.asm`,
`flee_mons.asm`, `treemons.asm` (headbutt), `treemon_maps.asm`, `roammon_maps.asm`,
`swarm_grass.asm`, `swarm_water.asm`, `bug_contest_mons.asm`, `probabilities.asm`,
`unlocked_unowns.asm`. **Crystal-only file: `treemons_asleep.asm`** — present in pokecrystal's
`data/wild/` listing, absent from pokegold's (directory diff, this pass) — the sleeping-Sudowoodo
headbutt variant.

`def_grass_wildmons`/`end_grass_wildmons` macros (`pokegold@656583c macros/asserts.asm:60-72`,
identical text confirmed to exist in pokecrystal by grep in this pass):
```
MACRO? def_grass_wildmons
;\1: map id
	REDEF CURRENT_GRASS_WILDMONS_MAP EQUS "\1"
	REDEF CURRENT_GRASS_WILDMONS_LABEL EQUS "._def_grass_wildmons_\1"
{CURRENT_GRASS_WILDMONS_LABEL}:
	map_id \1
ENDM
MACRO? end_grass_wildmons
	DEF x = @ - {CURRENT_GRASS_WILDMONS_LABEL}
	assert GRASS_WILDDATA_LENGTH == x, ...
ENDM
```
`map_id` (`pokegold@656583c macros/scripts/maps.asm:1-6`): `db GROUP_\1, MAP_\1` — i.e. each
table entry is keyed by a **2-byte (map group, map number) pair**, sourced from
`constants/map_constants.asm`'s `map_const`/`newgroup` macros, the same group/number pair
`gen_gen2_area_map.py`'s composite id (`mapGroup*256+mapNumber`, see B.3) already encodes.
`GRASS_WILDDATA_LENGTH EQU 2 + 3 + NUM_GRASSMON * 2 * 3` (`pokegold@656583c
constants/pokemon_data_constants.asm:163`) — 2 bytes map id + 3 encounter-rate bytes
(morn/day/nite) + 7 grass slots × (level, species) × 3 times of day, confirmed against the raw
data (`data/wild/johto_grass.asm:1-30`, this pass): a `db 2 percent, 2 percent, 2 percent`
rate triple followed by three 7-entry `db level, SPECIES` blocks labeled `; morn`/`; day`/`; nite`
in source comments.

**Edit (docs sweep, 2026-09-26): the "no such reader exists yet" claim below (B.3/B.5) is now
stale.** Both a Python ROM-byte decoder and a Lua ROM reader exist: `server/adapters/gen2_rom_scan.py`
(reads `data/wild/*.asm`-derived tables straight from ROM bytes via a per-title profile, including
`wild()`/grass/water tables) and `lua/gen2/rom.lua` (`self.wild()`, same table names/shapes). Both
post-date this research pass; treat the "future work" framing in B.3/B.5 as historical.

`fish.asm` uses a separate `FishGroups`/`fishgroup` table (rate + 3 rod-tier sub-pointers per
group, keyed by `FISHGROUP_*` constant, not by map — a map's fishing spot points at a
`FISHGROUP_*` via a per-map fish-encounter table elsewhere in the same file) with `time_group`
supplying at most a "use the nth `TimeFishGroups` entry" indirection — species pool does not
itself split by time of day in the way grass/water does (`data/wild/fish.asm:1-30`, this pass).

`roammon_maps.asm`'s `roam_map` macro (`data/wild/roammon_maps.asm:1-25`, this pass) stores a
start map plus a variable list of adjacent jump maps, each a `map_id` pair — i.e. roamers are
NOT keyed to one map's wild table at all; they are a graph of maps a legendary can currently be
standing on (Route 29 -> {30,46}, etc., for Entei/Raikou in G/S; Suicune's table is separate
elsewhere per the file's own per-species handling, not fully walked in this pass).

### B.2 Gold/Silver differences within the SAME files

`data/wild/johto_grass.asm` (`pokegold@656583c`) is **one shared file with inline `IF DEF(_GOLD)
... ELIF DEF(_SILVER) ... ENDC` conditionals per map** — confirmed by grep in this pass: 9
distinct `IF DEF(_GOLD)`/`ELIF DEF(_SILVER)` blocks inside `johto_grass.asm` alone (lines 343,
360, 446, 471, 501, 526, 640, 657, 800, 825, 855, 880, 910, 935, 965, 990, 1020, 1045, plus a
Silver Cave block at 1297-1398 with per-version rows), each swapping which species occupies which
slot for a given map (e.g. Sprout Tower has no such block — its `db RATTATA`/`db GASTLY` rows are
unconditional and thus identical between Gold and Silver; other maps like the ones with the
`IF DEF` blocks differ). **`fish.asm`, `roammon_maps.asm`, `bug_contest_mons.asm`, `treemons.asm`,
`swarm_grass.asm`/`swarm_water.asm` were not individually re-checked for `_GOLD`/`_SILVER`
conditionals in this pass** (only `johto_grass.asm` was grepped) — flagged in Open questions
rather than assumed identical. `pokegold`'s single repo builds BOTH `pokegold.gbc` and
`pokesilver.gbc` from these `_GOLD`/`_SILVER`-conditional shared sources (consistent with
`rom_hashes.md`'s Makefile citations for both ROM targets living in one `pokegold` repo).

**Crystal-only:** `treemons_asleep.asm` (file-level difference, B.1); Crystal's `data/wild/`
otherwise matches Gold/Silver's file set. Crystal-specific `IF DEF`/version splits were not
searched in this pass (Crystal has no `_GOLD`/`_SILVER` split of its own — it is one ROM, not a
dual-version repo) — its wild files may still differ in per-map CONTENT from Gold/Silver's
(different route Pokémon between generations is a known Crystal-vs-G/S design fact) but that
content diff was not tabulated map-by-map here.

### B.3 ROM-side table for a Lua reader / `gen2_rom_scan.py`

Label names to scan: `JohtoGrassWildMons`, `JohtoWaterWildMons` (inferred naming parallel, not
independently grepped for existence — the file itself opens with `JohtoGrassWildMons:` per
`data/wild/johto_grass.asm:3`, this pass), `KantoGrassWildMons`/`KantoWaterWildMons` (by the
analogous `kanto_grass.asm`/`kanto_water.asm` files, not individually opened this pass),
`FishGroups` (confirmed, B.1), `RoamMaps` (confirmed, B.1), `TreeMons`/similar (inferred from
`treemons.asm`, not opened), `BugContestMons`/similar (inferred from `bug_contest_mons.asm`, not
opened). Each grass/water record's first 2 bytes are the `(GROUP_x, MAP_x)` pair the `map_id`
macro emits (B.1) — **the map group/number key is encoded exactly as `gen_gen2_area_map.py`'s
composite id already does** (`tools/gen_gen2_area_map.py:11`: "Composite ID = mapGroup * 256 +
mapNumber (Crystal uses 2-byte map addressing)"), so a Lua reader walking the ROM table and a
Python `gen2_rom_scan.py` walking the same table can key results identically to the existing
`area_map.json`, mirroring Gen 1's F-4 two-path-equality precedent
(`server/adapters/gen1_rom_scan.py:1-19`: "NO HARDCODED ROM OFFSETS... a symbol's value is `bank
<< 16 | address`"; `docs/gen1_requirements.md:49` F-4: "Lua ROM reader == Python
`gen1_rom_scan.py`, byte-equal, all 59 tables"). **No such `gen2_rom_scan.py` or Lua-side ROM
reader exists yet in this worktree** (only `tools/gen_gen2_encounters.py`/`gen_gen2_area_map.py`
exist, and both read pret ASCII source under `.cache/pret/pokecrystal`, not ROM bytes — B.5) —
building the byte-offset table (via `data/pret_syms.json`/`pret_rom_syms.json`, per
`rom_hashes.md`'s finding that Gen 2 pret symbol data currently has NO `rom_sha1` keys — a
blocker noted there, not re-solved here) is future work, not something this pass produced.

### B.4 Map list and landmark/region names

`constants/map_constants.asm` (`pokegold@656583c constants/map_constants.asm:1-19`, this pass):
`newgroup`/`map_const`/`endgroup` macros assign `GROUP_<name>`/`MAP_<name>` constants plus a
per-map `<name>_WIDTH`/`<name>_HEIGHT` in blocks — this is the authoritative map-id source
`map_id` (B.1) asserts against ("Missing 'map_const \1' in constants/map_constants.asm"). A
`data/maps/maps.asm` and `data/maps/landmarks.asm` both exist in `pokegold@656583c` (directory
listing, this pass: `constants/pokemon_data_constants.asm`'s sibling directory `data/maps/`
lists `attributes.asm, blocks.asm, environment_colors.asm, flypoints.asm, landmarks.asm` —
`maps.asm` itself was not directly confirmed present in this listing and needs a follow-up
`ls`/read before a generator depends on it — Open questions) — `landmarks.asm` supplies the
Town Map / region display names (analogous to Gen 1's already-shipped
`data/games/gen1_rby/area_map.json` `"name"` field), while `map_constants.asm` supplies the
raw group/number -> internal-name mapping a generator walks.

### B.5 What exists today vs. hypothesis

`data/games/gen2_crystal/area_map.json` (this worktree, read in this pass) already has ~hundreds
of composite-id -> `{area_id, name}` entries, including multi-floor collapse (`"769"`/`"770"`/
`"771"` all map to `area_id: "sprout_tower"` with distinct display `name`s per floor — Sprout
Tower 2F/3F — mirroring Gen 1's Mt. Moon/Rock Tunnel/etc. collapse pattern cited in
`tools/gen_gen1_area_map.py:9-14`). `tools/gen_gen2_area_map.py` (84 lines) reads that JSON and
emits `lua/gen2_crystal_areas.lua`/`gen2_crystal_locations.lua` keyed by the same composite id
(`mapGroup*256+mapNumber`) — it does NOT itself derive `area_map.json` from pret source; that
JSON's own provenance (hand-authored vs. pret-derived) was not traced further in this pass.
`tools/gen_gen2_encounters.py` (396 lines, header read this pass) DOES read pret directly —
`.cache/pret/pokecrystal/data/wild/{johto,kanto}_{grass,water}.asm` — but **only Crystal's grass
and water tables**: no Gold/Silver, no `fish.asm`, `treemons.asm`, `roammon_maps.asm`,
`swarm_grass.asm`/`swarm_water.asm`, `bug_contest_mons.asm`. It hardcodes `GRASS_RATES = [30, 30,
20, 10, 5, 4, 1]` / `WATER_RATES = [60, 30, 10]` as Python constants rather than reading them
from each map's own 3 rate bytes (`data/wild/johto_grass.asm`'s `db 2 percent, 2 percent, 2
percent` line, B.1) — i.e. the existing generator currently ASSUMES every map uses the same
slot-percentage layout, which is Crystal's normal case but not independently re-verified against
every map's own rate bytes in this pass (potential silent bug if any map deviates — Open
questions). "Multi-floor dungeons ... collapse to the same canonical area_id ... First-wins"
(`tools/gen_gen2_encounters.py:20-22`) is the SAME first-wins convention already used for Gen 1
statics per `docs/gen1_requirements.md` (not independently re-derived, cited from the same file's
own comment).

### B.6 Static encounters

Ten `loadwildmon` call sites exist across `maps/*.asm` in `pokegold@656583c` (grep count, this
pass), including legendary/gift-style sites (`BurnedTowerB1F.asm:74 loadwildmon ENTEI, 40`,
`LakeOfRage.asm:87 loadwildmon GYARADOS, 30`) alongside ordinary scripted-encounter sites
(`Route29.asm:53/78/118 loadwildmon RATTATA, 5` — the "rustling grass" beginner-area tutorial
encounter, not a legendary). **`loadwildmon` alone does not distinguish a true static/legendary
from a scripted low-level tutorial wild battle** — a `gen_gen2_statics.py` needs an additional
filter (e.g. cross-referencing against known one-time/legendary map names, or a `givepoke`-style
distinct command) rather than grepping every `loadwildmon` site as-is; `givepoke` sites (gift
Pokémon, not wild statics) were not separately enumerated in this pass — Open questions.

## Recommended generator inputs (per title)

| Title | Grass/water | Fish | Headbutt | Roamers | Swarm | Bug Contest | Statics |
|---|---|---|---|---|---|---|---|
| Gold | `johto_grass.asm`+`kanto_grass.asm`+`johto_water.asm`+`kanto_water.asm` under `IF DEF(_GOLD)` branches | `fish.asm` (shared, not yet confirmed version-split, B.2) | `treemons.asm`/`treemon_maps.asm` | `roammon_maps.asm` (shared) | `swarm_grass.asm`/`swarm_water.asm` (shared, not yet confirmed version-split) | `bug_contest_mons.asm` (shared) | `maps/*.asm` `loadwildmon`/`givepoke` sites under `_GOLD` |
| Silver | same files, `ELIF DEF(_SILVER)` branches | same | same | same | same | same | same, `_SILVER` |
| Crystal | same 4 files, no version conditional (single ROM) + Crystal-only `treemons_asleep.asm` | same | `treemons.asm` + `treemons_asleep.asm` | same | same | same | `maps/*.asm` in pokecrystal |

Area-id policy recommendation (per Gen 1 precedent, `docs/gen1_requirements.md` F-4/S-8 and
`tools/gen_gen1_area_map.py`'s "area granularity follows vanilla's dungeon collapse"): **time of
day does NOT split an area** — Morn/Day/Nite are three encounter-table views of ONE area, exactly
as `data/games/gen2_crystal/encounter_tables.json` already models it (`"sprout_tower": {"Morn":
[...], "Day": [...], "Nite": [...]}`, read this pass). Headbutt and rock smash are the map they
occur on (no separate area), matching the S-8 fishing-maps-not-a-separate-area rule already
approved for Gen 1 ("fishing maps mapped" onto the map's own area, `docs/gen1_requirements.md:73`).
Roamers and the Bug-Catching Contest are recommended as special cases, NOT folded into per-map
area encounter tables: a roamer's current map is dynamic (it moves between `RoamMaps` entries at
runtime, B.1) so a static per-map table can only list it as "possible, not guaranteed," and the
Contest is a scripted minigame with its own separate mon pool (`bug_contest_mons.asm`) tied to a
specific NPC interaction rather than ambient grass — **marked as an owner question below rather
than decided here.**

## Open questions

- Whether the gamedb format has ANY field, anywhere in `gamedb_gbc.txt`, that ever carries an
  MBC3/RTC cart-type flag (the 5th/6th/7th optional columns exist in `ParseCGIRecord`'s format
  but were empty for these four lines specifically) — not resolved from these 4 lines alone.
- `FilesystemSafeName()`'s exact character-stripping rule was not independently re-derived from
  BizHawk source in this pass (only its existence/call site was, per `bizhawk_gambatte_gbc.md` §5).
- The native `gambatte_getsavedatalength`/RTC-tail byte layout for an MBC3+TIMER+RAM+BATTERY cart
  lives in the vendored C++ `gambatte-core` library, not fetched in this pass — the 22-byte figure
  is taken as a MEASURED project fact (`tools/gen2_playthrough.py:67-71`), not re-derived from
  gambatte source here.
- `fish.asm`, `roammon_maps.asm`, `bug_contest_mons.asm`, `treemons.asm`, `swarm_grass.asm`,
  `swarm_water.asm` were not individually grepped for `_GOLD`/`_SILVER` conditionals — only
  `johto_grass.asm` was checked map-by-map; whether these other tables differ by version (beyond
  the species-swap pattern already confirmed in grass tables) is unconfirmed.
- `data/maps/maps.asm`'s existence/content in `pokegold@656583c` was inferred from the directory
  listing showing `data/maps/` with `attributes.asm`/`blocks.asm`/etc. but `maps.asm` itself was
  not directly opened or confirmed present — needs a follow-up read before a generator depends on
  a `data/maps/maps.asm` path specifically.
- `JohtoGrassWildMons`/`JohtoWaterWildMons`/`KantoGrassWildMons`/`KantoWaterWildMons`/`TreeMons`/
  `BugContestMons` label names beyond the one confirmed (`JohtoGrassWildMons:` at
  `johto_grass.asm:3`) are inferred by naming-convention parallel, not individually grepped for
  existence in this pass.
- `tools/gen_gen2_encounters.py`'s hardcoded `GRASS_RATES`/`WATER_RATES` constants were not
  cross-checked against every map's own 3-byte rate row in `johto_grass.asm`/`kanto_grass.asm` —
  if any map deviates from the assumed 30/30/20/10/5/4/1 (grass) or 60/30/10 (water) split, the
  existing generator would silently mis-tag that map's rates.
- `loadwildmon` sites need a stronger filter than "every call site" to separate true
  static/legendary encounters (Entei, Gyarados-at-Lake-of-Rage) from ordinary low-level scripted
  wild battles (Route 29's tutorial rustling grass) before a `gen_gen2_statics.py` can trust the
  list; `givepoke` (gift Pokémon) sites were not separately enumerated at all.
- Owner question: should roaming legendaries and the Bug-Catching Contest get their own
  `roamer_<species>`/`bug_contest_<map>`-style synthetic area/event ids (mirroring Gen 1's
  `static_<map>_<dex>`/`gift_map_<id>` convention, `docs/gen1_requirements.md:73`), or should they
  be left out of the area/encounter generator entirely as a v1 scope cut? Not decided here.
- Whether Crystal's per-map wild SPECIES content (not just the shared file set) differs from
  Gold/Silver's beyond the known generational species-availability differences was not tabulated
  map-by-map in this pass.
