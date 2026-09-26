# Archipelago "Pokémon Crystal" — repo, RAM contract, layout divergence

Retrieved 2026-09-21 unless noted otherwise. Primary evidence is the installed apworld at
`C:\ProgramData\Archipelago\custom_worlds\pokemon_crystal.apworld` (a zip; extracted read-only
to the scratchpad for this research, nothing under that path was modified) cross-checked
against `gerbiljames/Archipelago-Crystal` on GitHub and this worktree's
`data/pret_syms.json` (pret pokecrystal HEAD `3438c70`, 2026-07-20, read-only cache at
`E:\Google Drive\SLink\.cache\pret\pokecrystal`).

## Pins

- Installed apworld: `pokemon_crystal.apworld`, `APWORLD_VERSION = "4.0.5"`
  (`extracted/pokemon_crystal/data.py:11`, read from the local zip 2026-09-21).
- Upstream repo: https://github.com/gerbiljames/Archipelago-Crystal — confirmed to exist and
  be actively maintained (`pushed_at: 2026-09-19T22:44:39Z`, `gh api
  repos/gerbiljames/Archipelago-Crystal`, retrieved 2026-09-21). This is a **full fork of
  ArchipelagoMW/Archipelago** (it carries branches/worlds for many unrelated games — dredge,
  emerald, tevi, dmc3, kdl3, etc.), not a small standalone repo.
- Tag `4.0.5` exists on that repo, `target_commitish: "pokecrystal"`, published
  `2025-06-21T16:01:13Z` (`gh api repos/gerbiljames/Archipelago-Crystal/releases/tags/4.0.5`).
  Its `worlds/pokemon_crystal/` file list (`gh api
  repos/gerbiljames/Archipelago-Crystal/git/trees/4.0.5?recursive=1`) matches the installed
  apworld's file list exactly (`client.py`, `data.py`, `rom.py`, `data/data.json`,
  `data/basepatch.bsdiff4`, `data/basepatch11.bsdiff4`, etc.) — the installed copy is this tag.
- Current upstream is well ahead of the installed copy: latest release `6.0.0-rc.1`, published
  `2026-09-16T13:45:04Z`; default branch is now `pokecrystal-develop`
  (`gh api repos/gerbiljames/Archipelago-Crystal`, `.../releases`, retrieved 2026-09-21).
- LICENSE in the apworld: `Copyright (c) 2024 AliceMousie`, `Copyright (c) 2025 gerbiljames`,
  MIT (`extracted/pokemon_crystal/LICENSE`).
- `docs/setup_en.md` tutorial credits: `["AliceMousie", "gerbiljames"]`
  (`extracted/pokemon_crystal/__init__.py:48-55`).
- pret pokecrystal HEAD used for the vanilla comparison: `3438c7003a57fa2987fcb223d14b660761b33c64`,
  2026-07-20 21:34:43 -0400 (`git log -1` in `E:\Google Drive\SLink\.cache\pret\pokecrystal`).

## Repo and version

**Q1 answer: the "no public repo" claim in `docs/gen1_gen2_runtime_checks.md:176-177`
("the AP fork has no public repo, so only five of its addresses are provable") is no longer
true on 2026-09-21.** `gerbiljames/Archipelago-Crystal` is public, has 30+ open feature
branches, and ships version history back through 4.0.x. †Note the nuance below under "Layout
divergence": the repo is public for the **Python apworld** (client, options, data tables) —
it does *not* appear to include the **assembly/disassembly source** of the ROM-side patch
(see below), so the original claim's narrower reading ("we can't derive a full symbol table
from source") still holds, just for a different reason than "the repo doesn't exist."

- WebSearch (query "Archipelago Pokemon Crystal apworld github AliceMousie gerbiljames base
  rom disassembly", retrieved 2026-09-21) †SECONDARY corroborates the project history: AliceMousie
  released a source-only version 2023-11-10, first `.apworld` (v0.1) 2024-02-25; she left the
  Archipelago Discord/community 2025-02-27; gerbiljames picked it back up 2025-03-13 going from
  2.1.2 to 3.0.0. Not independently verified beyond the search snippet.
- History note (†SECONDARY, from the same search result, Archipelago Miraheze wiki was not
  directly fetched): treat dates before 2026 in that summary as unverified specifics, only the
  repo's own existence and current activity are pinned above via `gh api`.

**Base pokecrystal fork used to build the ROM-side patch: NOT publicly located.** The repo's
`worlds/pokemon_crystal/` directory (both tag `4.0.5` and the current `pokecrystal-develop`
branch, where the dev copy lives at `worlds/pokemon_crystal_prerelease/`) contains only
**compiled** patch artifacts — `data/basepatch.bsdiff4` and `data/basepatch11.bsdiff4` — and
Python. A full recursive tree listing of `pokecrystal-develop`
(`gh api repos/gerbiljames/Archipelago-Crystal/git/trees/pokecrystal-develop?recursive=1`,
1046 entries, `truncated: false`) has **no** `.asm` file, `wram.asm`, or disassembly directory
under any `pokemon_crystal*` path — contrast with e.g. `worlds/earthbound/src/eb.asm`,
`worlds/mm2/src/mm2_basepatch.asm`, `worlds/lufia2ac/basepatch/basepatch.asm`, which are
present for other AP worlds that do ship their ASM source in-repo. So: the branch/commit of
the pokecrystal disassembly fork used to hand-patch the ROM is **not identifiable from this
repo** — only the resulting binary diff is checked in. Open question.

## Client RAM contract

All addresses below are as declared by the apworld itself: `data.ram_addresses` and
`data.rom_addresses`, loaded from `extracted/pokemon_crystal/data/data.json` via
`load_json_data("data.json")` (`extracted/pokemon_crystal/data.py:410-411, 429-432`). Values in
`ram_addresses` are **System-Bus-relative WRAM offsets from 0xC000** (confirmed by the
existing repo test's convention, `tests/unit/test_gen2_ap_addresses.py:34` `WRAM_BASE = 0xC000`,
and independently by every delta matching the lua profile comments below).

`extracted/pokemon_crystal/client.py` reads/writes exclusively via `worlds._bizhawk.bizhawk`
(`bizhawk.read`, `bizhawk.guarded_read`, `bizhawk.write`) against two BizHawk memory domains,
`"WRAM"` and `"ROM"`. No `"SRAM"` domain access appears anywhere in `client.py` or `rom.py`.

Full symbol/offset table declared in the installed `data.json` (16 `ram_addresses` entries,
all resolved by name from JSON, none hard-coded in `client.py` itself):

| symbol | offset (from 0xC000) | System Bus addr | used in client.py |
|---|---|---|---|
| `wArchipelagoOptions` | 0x0FCC | 0xDFCC | `client.py:130` (`DEATH_LINK_SETTING_ADDR = ...+4`) |
| `wMapEventStatus` | 0x1437 | 0xD437 | not read in `client.py`; used elsewhere in the world (rules/regions) |
| `wArchipelagoDeathLink` | 0x16E4 | 0xD6E4 | `client.py:460,467,472` |
| `wArchipelagoNextItem` | 0x16E5 | 0xD6E5 | not referenced in `client.py` (used by `rom.py`/other modules) |
| `wStatusFlags` | 0x1827 | 0xD827 | not read in `client.py` |
| `wEventFlags` | 0x1A8F | 0xDA8F | `client.py:270` (`0x104` = 260 bytes read) |
| `wArchipelagoItemReceived` | 0x1CA7 | 0xDCA7 | `client.py:238-249` |
| `wArchipelagoItemIndex` | 0x1CA8 | 0xDCA8 | not referenced by name in `client.py` (adjacent to ItemReceived, read as part of the 5-byte block at `client.py:238`) |
| `wArchipelagoSafeWrite` | 0x1CAA | 0xDCAA | `client.py:236` (`overworld_guard`) |
| `wArchipelagoPhoneTrapReadIndex` | 0x1CAB | 0xDCAB | not referenced by name (adjacent, part of the 5-byte read) |
| `wArchipelagoPhoneTrapIndex` | 0x1CAC | 0xDCAC | not referenced by name in this file |
| `wArchipelagoBonkCount` | 0x1CAD | 0xDCAD | not referenced in `client.py` |
| `wMapGroup` | 0x1CC0 | 0xDCC0 | `client.py:473` |
| `wMapNumber` | 0x1CC1 | 0xDCC1 | `client.py:473` (read together with `wMapGroup`, 2 bytes) |
| `wArchipelagoPokedexCaught` | 0x1EA4 | 0xDEA4 | `client.py:271` |
| `wArchipelagoPokedexSeen` | 0x1EC4 | 0xDEC4 | `client.py:272` |

Relevant `rom_addresses` (ROM-domain, byte offsets into the 2MB patched ROM, also from
`data.json`), used by `validate_rom`/`set_auth` in `client.py:180-220`:

| symbol | ROM offset | purpose |
|---|---|---|
| `AP_ROM_Header` | 0x134 | 11-byte ASCII title check (`"AP_CRYSTAL"` vs vanilla `"PM_CRYSTAL"`) |
| `AP_ROM_Version` | 0x14E | 2-byte checksum compared against `data.rom_version`/`rom_version11` |
| `AP_ROM_Revision` | 0x14C | 1 byte: 0 = v1.0 base, else v1.1 |
| `AP_Setting_RemoteItems` | 0x1FB934 | 1 byte, gates `ctx.items_handling` |
| `AP_Version` | 0x4010 | 32-byte ASCII, the generator's apworld version string, for the mismatch error message |
| `AP_Seed_Auth` | 0x4000 | 16 bytes, base64-encoded into `ctx.auth` (`set_auth`, `client.py:222-225`) |
| `AP_Setting_Phone_Trap_Locations` | 0x1FB8B4 | 0x20 bytes, 16 little-endian u16 location ids |

No party base, box base, or player-ID address is read anywhere in `client.py`. Location
checks (event flags aside) are resolved from the flag-bit scan over `wEventFlags` plus two
Pokédex bitfields, not from party/box memory — the client does not need those addresses for
its own operation, so their fork-relocated values (if any) are simply absent from
`ram_addresses` and unprovable from this source.

## Layout divergence from pret

Deltas computed directly from `data/pret_syms.json`'s `pokecrystal` table (vanilla, WRAM
absolute addresses) vs. the apworld's `ram_addresses` (offset + 0xC000), both read in this
session:

| symbol | vanilla (pret `3438c70`) | AP declared | delta |
|---|---|---|---|
| `wMapGroup` | 0xDCB5 | 0xDCC0 | +11 |
| `wMapNumber` | 0xDCB6 | 0xDCC1 | +11 |
| `wMapEventStatus` | 0xD433 | 0xD437 | +4 |
| `wEventFlags` | 0xDA72 | 0xDA8F | +29 |
| `wStatusFlags` | 0xD84C | 0xD827 | −37 |

These five exactly match the values already recorded in `lua/games/gen2_crystal.lua:479-482`
(the `-- wMapEventStatus 0xD433 -> 0xD437 +4` comment block) and pinned by
`tests/unit/test_gen2_ap_addresses.py`. This research **independently re-derives the same
five deltas from the two primary sources** (apworld `data.json` + pret `pokecrystal` syms)
rather than trusting the lua/test comment — they agree.

`wOptions` (vanilla 0xCFCC): **not present** in the apworld's `ram_addresses` table at all.
The fork does not appear to relocate `wOptions`; it instead adds a wholly new
`wArchipelagoOptions` block at 0xDFCC that is unrelated to vanilla's options byte. No evidence
either way on whether the fork's own `wOptions` moved internally — only that AP's client
doesn't reference it.

`wPartyCount`/`wPartyMon1`/`wBoxCount`/`wPlayerID`: **not present** in `ram_addresses`.
Cannot verify whether the fork relocates party/box/player-ID memory — the client simply
doesn't touch it (see Client RAM contract above), so there is no primary-source evidence
either way. Open question.

New WRAM blocks confirmed (all `wArchipelago*` names, none of which exist in vanilla
`pret_syms.json`): `wArchipelagoOptions`, `wArchipelagoDeathLink`, `wArchipelagoNextItem`,
`wArchipelagoItemReceived`, `wArchipelagoItemIndex`, `wArchipelagoSafeWrite`,
`wArchipelagoPhoneTrapReadIndex`, `wArchipelagoPhoneTrapIndex`, `wArchipelagoBonkCount`,
`wArchipelagoPokedexCaught`, `wArchipelagoPokedexSeen`. These sit interleaved with relocated
vanilla symbols (e.g. `wArchipelagoItemReceived` at 0xDCA7 is 25 bytes before the relocated
`wMapGroup` at 0xDCC0), consistent with insertions into the middle of vanilla's WRAM layout
that push everything after them forward — exactly the mechanism the lua comment already
described.

The fork does **not** ship a `.sym` file or a `ram/wram.asm` anywhere findable in the public
repo (see Repo and version, above) — `data/data.json` inside the apworld *is* the closest
thing to a symbol file, and it is JSON, not an assembler symbol table. `tools/build_pret_syms.py`
in this worktree could not be pointed at a wram.asm for this fork because none was found.

## Save layout

No evidence of SRAM/save-layout changes was found. `client.py` and `rom.py` (the two files
that would touch persistent save data) reference only the `"WRAM"` and `"ROM"` BizHawk memory
domains — grep for `SRAM`/`sram`/`SaveRAM`/`checksum` across every `.py` file in the extracted
apworld returns zero hits outside two log-message strings in `client.py:207-208` that say
"checksum" but refer to the **ROM patch version checksum** (`AP_ROM_Version`,
`data.rom_version`), not a save-file checksum. All of AP's own bookkeeping
(`wArchipelagoItemReceived`, `wArchipelagoPokedexCaught`, etc.) lives in WRAM (0xC000–0xDFFF
range), the same volatile region vanilla pokecrystal already uses for event flags before they
are flushed to SRAM on save — consistent with the fork not needing a new SRAM bank or a save
schema change for its own tracking, since it rides along on the existing WRAM→SRAM save path
rather than adding one. Whether the underlying disassembly relocates `sBox` or any other SRAM
struct is **CANNOT VERIFY** — that would require the (not public, see above) ASM source.

## Patch and base ROM

- Patch container: `.apcrystal` (`PokemonCrystalProcedurePatch.patch_file_ending`,
  `extracted/pokemon_crystal/rom.py`, class `PokemonCrystalProcedurePatch(APProcedurePatch,
  APTokenMixin)`), producing a `.gbc` (`result_file_ending`).
- Procedure: `[("apply_bsdiff4", ["basepatch.bsdiff4"]), ("apply_tokens", ["token_data.bin"])]`
  — a `bsdiff4` binary diff over the base ROM, followed by AP's generic token-based byte
  patches for the per-seed randomization.
- `PokemonCrystalAPPatchExtension.apply_bsdiff4` special-cases revision: if
  `rom_bytes[data.rom_addresses["AP_ROM_Revision"]] == 1` it uses `basepatch11.bsdiff4`
  instead of `basepatch.bsdiff4`, requiring that file to be present in the patch container —
  i.e. **the same `.apcrystal` file supports both V1.0 and V1.1 base ROMs** by carrying two
  base diffs.
- Expected base-ROM hashes (MD5, `extracted/pokemon_crystal/rom.py`):
  `CRYSTAL_1_0_HASH = "9f2922b235a5eeb78d65594e82ef5dde"`,
  `CRYSTAL_1_1_HASH = "301899b8087289a6436b0a241fbbb474"`. Both are declared on
  `PokemonCrystalSettings.RomFile.md5s = PokemonCrystalProcedurePatch.hash` in
  `extracted/pokemon_crystal/__init__.py:41-46` (`class RomFile(settings.UserFilePath)`), which
  is what the AP launcher checks when the player supplies their own ROM file.
- `data.rom_version` / `data.rom_version11` (from `data.json`, read at `data.py:761-762`):
  `9392` (0x24B0) for V1.0, `47792` (0xBAB0) for V1.1 — the 2-byte values the client compares
  against `AP_ROM_Version` in `validate_rom` (`client.py:198-199`).

## ROM identification

`validate_rom` (`extracted/pokemon_crystal/client.py:180-220`):
1. Requires the loaded ROM's `"ROM"` memory-size to be exactly 2097152 bytes (2 MB) — the
   patched-ROM size, not the vanilla 1 MB Crystal ROM.
2. Reads 11 bytes at `AP_ROM_Header` (0x134, the GB/GBC cartridge title field) and decodes
   ASCII. Unpatched vanilla Crystal reads `"PM_CRYSTAL"` there and gets a specific "you need to
   patch this" log message; anything else that isn't exactly `"AP_CRYSTAL"` fails validation
   silently (`return False`).
3. Reads `AP_ROM_Version` (2 bytes) + `AP_ROM_Revision` (1 byte) + `AP_Setting_RemoteItems`
   (1 byte) + `AP_Version` (32 bytes) in the same batched `bizhawk.read` call and compares the
   version word against `data.rom_version`/`rom_version11` depending on the revision byte, to
   catch a client/generator apworld-version mismatch.
4. On success sets `ctx.game`, `ctx.items_handling` (bit 1 gated by `remote_items`),
   `ctx.want_slot_data = True`, `ctx.watcher_timeout = 0.125`.

No separate SRAM "slot" identification exists — identification is entirely via the ROM title
string plus the two-byte version checksum embedded in the ROM by the generator.

## Local assumptions audit

Source files read read-only; nothing in this worktree was edited by this note.

- `lua/games/gen2_crystal.lua:479-483` (comment block) claims the five deltas
  `wMapEventStatus +4`, `wMapGroup +11`, `wMapNumber +11`, `wEventFlags +29`,
  `wStatusFlags −37`. **CONFIRMED** — independently re-derived above from `data.json` + pret
  `pokecrystal` syms; all five match exactly.
- `lua/games/gen2_crystal.lua:502-503` — `MAP_GROUP_ADDR = 0xDCC0` and
  `MAP_NUMBER_ADDR = 0xDCC1` in the `crystal_ap` profile. **CONFIRMED** against
  `data.ram_addresses["wMapGroup"] = 0x1CC0` and `["wMapNumber"] = 0x1CC1` (+ 0xC000 base).
- `lua/games/gen2_crystal.lua:506-510` — `ap_known_addresses` table:
  `wMapEventStatus = 0xD437`, `wStatusFlags = 0xD827`, `wEventFlags = 0xDA8F`. **CONFIRMED**,
  all three match `data.ram_addresses` + 0xC000 exactly.
- `lua/games/gen2_crystal.lua:488-495` (comment) — "there is no public fork repo... the URL
  the docs used to name is gone" and "`tools/build_pret_syms.py` cannot do for AP Crystal what
  it does for `alchav_pokered`". **CONTRADICTED** on the repo-existence half: a public repo
  exists at `github.com/gerbiljames/Archipelago-Crystal` and is actively maintained (see
  Repo and version). **Still true** on the `build_pret_syms.py` half: no `.asm`/`wram.asm`
  disassembly source was found in that repo for `pokemon_crystal` at any ref checked (tag
  `4.0.5`, branch `pokecrystal-develop`) — only compiled `bsdiff4` patch blobs — so
  `build_pret_syms.py` still has no ASM source to run against for this fork.
- `lua/games/gen2_crystal.lua:513-515` — `ap_addresses_unverified = true` flag and the
  "everything else is inherited from vanilla Crystal and NOT verified" comment. **Still
  accurate as a caution**, but this research shows the inherited set is larger than "unknown
  either way" for two symbols: `wOptions` and party/box addresses are **not represented at
  all** in AP's own `ram_addresses` table (the client never reads them), so there is no way to
  confirm or contradict a relocation for those specifically — CANNOT VERIFY, not merely
  unverified-but-plausible.
- `tests/unit/test_gen2_ap_addresses.py:34` — `WRAM_BASE = 0xC000` used to convert the
  apworld's declared offsets into System Bus addresses. **CONFIRMED**: every value in
  `data.ram_addresses` is well below 0x2000 (16-bit WRAM bank + mirror offset), and adding
  0xC000 reproduces the exact addresses independently computed above from pret deltas.
- `tests/unit/test_gen2_ap_addresses.py:31` — `APWORLD = r"C:\ProgramData\Archipelago\
  custom_worlds\pokemon_crystal.apworld"`. **CONFIRMED present** at that exact path on this
  machine as of 2026-09-21 (used directly as the primary source for this whole note).
- `tests/unit/test_gen2_ap_addresses.py` asserts only the 5 map/status/event addresses and
  the "still flagged unverified" premise; it makes no claim about party, box, SRAM, or the
  repo's existence, so there was nothing further in that file to confirm or contradict.

## Delta from what the project had

**Pin ruling (owner, 2026-09-21): pin to `6.0.0-rc.1`, not upstream HEAD.** Repo
`gerbiljames/Archipelago-Crystal`, release
https://github.com/gerbiljames/Archipelago-Crystal/releases/tag/6.0.0-rc.1, resolved tag
commit `0b11931c69134786369c0cd1ca7394104335aef5`, published 2026-09-16T13:45:04Z,
`target_commitish: "pokecrystal-develop"`, `prerelease: true` (all via `gh api
repos/gerbiljames/Archipelago-Crystal/releases/tags/6.0.0-rc.1`, retrieved 2026-09-21). Release
assets: `Pokemon.Crystal.Prerelease.yaml` (player options template) and
`pokemon_crystal_prerelease.apworld` — note the **world folder and patch suffix change name**
at this tag: `worlds/pokemon_crystal_prerelease/` and `.apcrystalpre`
(`Archipelago-Crystal@0b11931c:worlds/pokemon_crystal_prerelease/rom.py:251`), not the
`pokemon_crystal` / `.apcrystal` of the stable line this project's docs and tests reference.
Base-fork/build-source check repeated at this exact commit: a full recursive tree
(`gh api repos/gerbiljames/Archipelago-Crystal/git/trees/0b11931c69134786369c0cd1ca7394104335aef5?recursive=1`,
1060 entries) shows `worlds/pokemon_crystal_prerelease/{data,docs,test}` only — no `.asm`,
`wram.asm`, or disassembly directory — same conclusion as the stable tag: **only compiled
`data/basepatch.bsdiff4` + `data/basepatch11.bsdiff4` are checked in; the ASM source of the
base patch is not identifiable from this repo at this or any other ref checked.**

What's newer than RC1 upstream, and why RC1 is still the right pin: **nothing has been
released since.** `6.0.0-rc.1` is the newest entry in
`gh api repos/gerbiljames/Archipelago-Crystal/releases` (retrieved 2026-09-21) — there is no
`6.0.0` final yet. Curiously, the repo's nominal default branch tip (`pokecrystal-develop`,
commit `95ab8477c62919d1b35dcde1dbec7c1cd61fa476`, 2026-06-10) is **572 commits behind** the
RC1 tag commit (`gh api repos/.../compare/0b11931c...pokecrystal-develop` →
`"ahead_by": 0, "behind_by": 572`) — the RC1 build was cut from further-along, unmerged work,
so the branch name is not a reliable "latest" pointer for this repo; the release tag is. RC1
is therefore both the newest published release and, in practice, the most advanced commit
reachable through GitHub's release mechanism — there's no more-current point to prefer it
over.

What the project previously assumed (all read-only, nothing here edited):
- `lua/games/gen2_crystal.lua:479-483,502-515` (`crystal_ap` profile + its comment block) and
  `tests/unit/test_gen2_ap_addresses.py` pin exactly **five** addresses
  (`wMapGroup`, `wMapNumber`, `wMapEventStatus`, `wEventFlags`, `wStatusFlags`) sourced from
  whatever `.apworld` happened to be installed at `C:\ProgramData\Archipelago\custom_worlds\
  pokemon_crystal.apworld` — this turned out to be tag `4.0.5` (2025-06-21, commit resolved via
  `gh api repos/gerbiljames/Archipelago-Crystal/releases/tags/4.0.5`), the **stable**
  `pokemon_crystal` world, over a year behind RC1.
- `tools/build_pret_syms.py` has no `REPOS` entry for any Archipelago/AP Gen 2 checkout — it
  only clones `pret/pokered`, `pret/pokeyellow`, `pret/pokecrystal` (vanilla disassemblies),
  confirmed by reading the tool's docstring/`REPOS` table in this worktree; there is no AP Gen 2
  entry to update.
- No `.cache/pret/*` AP checkout exists — `ls "E:\Google Drive\SLink\.cache\pret\"` lists only
  `alchav_pokered, pokecrystal, pokefirered, pokegold, pokeheartgold, pokeplatinum, pokered,
  pokeyellow`, all vanilla/pret disassemblies, no Archipelago fork.
- The project's pret base pin for pokecrystal was `3438c7003a57fa2987fcb223d14b660761b33c64`
  (2026-07-20) in `.cache/pret/pokecrystal` (read-only, unmodified by this note). **The owner
  has since moved that pin to `7a7881d0d62e0ddbd82dcf10e7116807487ac651`** (2026-08-13),
  cloned read-only at
  `...\17c55ba3-97ae-4ed8-ba47-396926dd84c9\scratchpad\pret_head\pokecrystal`. A structural
  check (`diff` of `grep -n "^wMapGroup:\|^wMapNumber:\|^wEventFlags:\|^wStatusFlags:\|
  ^wMapEventStatus:\|^wOptions:\|^wPlayerID:\|^wPlayerGender:\|^wPrevWarp:\|^wVisitedSpawns:\|
  ^wUnownDex:\|^wUnlockedUnowns:" ram/wram.asm` between the two checkouts) shows every one of
  those labels shifted by exactly **+86 lines** between the old and new sha, with their
  relative order unchanged — i.e. the new pret sha inserted ~86 lines of unrelated content
  somewhere before `wOptions` and did not reorder the symbols this project cares about. This is
  a structural signal only, **not** byte-accurate addresses: deriving the actual new addresses
  requires an RGBDS assemble (`tools/build_pret_syms.py`), which would write to
  `data/pret_syms.json` (outside this note's lease) and clone into `.cache/pret` (explicitly
  off-limits for this task) — left as an implementation-phase step, not done here.

What changed upstream between the previously-assumed release and RC1 (`pokemon_crystal` 4.0.5
→ `pokemon_crystal_prerelease` 6.0.0-rc.1, both apworld files fetched directly from GitHub raw
content at their respective tags, 2026-09-21):
- **`ram_addresses` grew from 16 to 43 entries.** New symbols at RC1 include
  `wArchipelagoTrackerSlot`, `wPrevWarp`/`wPrevMapGroup`/`wPrevMapNumber`, `wPlayerGender`,
  `wPlayerID`, `wArchipelagoNextFlagItem`, `wArchipelagoFlagItemId`,
  `wArchipelagoTradeFlags`, `wArchipelagoTrapReceived`, `wArchipelagoFlagItemReceived`,
  `wVisitedSpawns`, `wUnownDex`, `wUnlockedUnowns`, `wArchipelagoData`/`wArchipelagoDataEnd`,
  `wArchipelagoGrassFlags`, `wArchipelagoSignFlags`, `wArchipelagoBattleTowerTrainerFlags`,
  `wArchipelagoBattleTowerCompletedTiers`, `wArchipelagoRematchTrainerFlags`,
  `wArchipelagoEnergyLinkStatus`/`Amount`/`Pool`, `wWarpFlags`/`wWarpFlagsEnd`, `wLastWarpID`
  (`head_6_0/data.json` in the research scratchpad, fetched from
  `raw.githubusercontent.com/gerbiljames/Archipelago-Crystal/6.0.0-rc.1/worlds/
  pokemon_crystal_prerelease/data/data.json`). Notably, **`wPlayerID` and `wPlayerGender` are
  now present** — the 4.0.5 client never read player identity from WRAM at all; RC1 does.
- **`client.py` grew from 498 to 981 lines** and its `game_watcher` now does one large
  `guarded_read` (`Archipelago-Crystal@0b11931c:worlds/pokemon_crystal_prerelease/client.py:372-388`)
  pulling 16 separate WRAM regions in one call (event flags, dex caught/seen, grass/trade/sign
  flags, unown dex, map group, status flags, tracker slot, unlocked unowns, warp flags, visited
  spawns, battle-tower state, rematch-trainer flags, last warp id) where 4.0.5 pulled 3. It also
  gained an Energy Link feature (`wArchipelagoEnergyLinkStatus` etc., `client.py:226`) that did
  not exist in 4.0.5 at all.
- **Base-ROM identification is unchanged**: `CRYSTAL_1_0_HASH`/`CRYSTAL_1_1_HASH` MD5 constants
  in `rom.py` are byte-identical between 4.0.5 and RC1
  (`9f2922b235a5eeb78d65594e82ef5dde` / `301899b8087289a6436b0a241fbbb474`) — RC1 still patches
  the same vanilla V1.0/V1.1 English ROMs, no new base-ROM revision requirement.
- **`rom_version`/`rom_version11` (the ROM-embedded compatibility checksum) changed**, as
  expected for any apworld update: 4.0.5 declared `9392`/`47792` (V1.0/V1.1 differ); RC1's
  `data.json` declares `9006` for **both** fields (`head_6_0/data.json`) — the two revisions
  now report the same checksum value in this data file (whether that reflects an actual
  ROM-checksum equalization or is an artifact of how the two fields are populated for the
  prerelease world could not be confirmed further without generating a ROM; flagged as an open
  question below).
- **Patch container changed for this world**: `.apcrystal` (stable) vs `.apcrystalpre`
  (prerelease, RC1) — the two worlds are not patch-file-compatible with each other, consistent
  with them being parallel, differently-versioned Archipelago worlds in the same repo.
- The five addresses this project already pins (`wMapGroup`, `wMapNumber`, `wMapEventStatus`,
  `wEventFlags`, `wStatusFlags`) **all moved again** between 4.0.5 and RC1 (see next section) —
  confirming the layout is not stable across apworld releases and re-pinning per release is
  necessary, not optional.

**Exact clone URL + sha the implementation phase should pin:**
`https://github.com/gerbiljames/Archipelago-Crystal.git` @
`0b11931c69134786369c0cd1ca7394104335aef5` (tag `6.0.0-rc.1`), world path
`worlds/pokemon_crystal_prerelease/`, `.apcrystalpre` patch suffix, asset
`pokemon_crystal_prerelease.apworld`.

## Layout divergence from pret, at the RC1 pin (`6.0.0-rc.1`, commit `0b11931c`)

RC1's `ram_addresses` (all values are still WRAM offsets from 0xC000, same convention verified
earlier — every value is well under 0x2000) for the five previously-tracked symbols, from
`head_6_0/data.json` (`worlds/pokemon_crystal_prerelease/data/data.json` @ `0b11931c`):

| symbol | 4.0.5 (offset) | RC1 (offset) | RC1 System Bus addr |
|---|---|---|---|
| `wMapEventStatus` | 0x1437 | 0x143A | 0xD43A |
| `wStatusFlags` | 0x1827 | 0x181E | 0xD81E |
| `wEventFlags` | 0x1A8F | 0x1A90 | 0xDA90 |
| `wMapGroup` | 0x1CC0 | 0x1CBB | 0xDCBB |
| `wMapNumber` | 0x1CC1 | 0x1CBC | 0xDCBC |

All five shifted again relative to 4.0.5, by small amounts (−1 to +3 bytes), consistent with
RC1 inserting a handful of new fields (`wArchipelagoTrackerSlot` at 0xFD5,
`wPrevWarp`/`wPrevMapGroup`/`wPrevMapNumber` at 0x1150-0x1152, `wPlayerGender`/`wPlayerID` at
0x1478/0x1481) ahead of `wMapEventStatus` in the WRAM layout. **Computing these five against
vanilla pret at the owner's new pin (`7a7881d0d62e0ddbd82dcf10e7116807487ac651`) byte-exactly
requires an RGBDS assemble** (`tools/build_pret_syms.py`), which is out of this note's lease
(it writes `data/pret_syms.json` and clones into `.cache/pret`, both off-limits here). The
structural check in the previous section (uniform +86-line shift, order preserved) is the best
available evidence without that build: it says the *relative* layout of these five vanilla
symbols to each other is unchanged at the new pret sha, but says nothing about their absolute
addresses, which is what an implementation profile actually needs.

## Open questions

1. Which branch/commit of a pokecrystal **disassembly** fork (ASM source, not the apworld
   Python) was used to hand-build `basepatch.bsdiff4`/`basepatch11.bsdiff4`? Not found in the
   public `gerbiljames/Archipelago-Crystal` repo at tag `4.0.5` or branch
   `pokecrystal-develop` — only the compiled binary diffs are checked in.
2. Do the fork's party (`wPartyCount`/`wPartyMon1`), box (`wBoxCount`), or player-ID
   (`wPlayerID`) structures move from vanilla? AP's own client never reads them, so there is no
   primary-source way to answer this without the ASM source from question 1, or without
   diffing a patched ROM against vanilla by hand.
3. Does the disassembly relocate `sBox` or any other SRAM structure, or change the save-file
   checksum scheme? No SRAM domain access appears in the client at all, which is suggestive but
   not conclusive (the client may simply not need to touch SRAM directly even if the
   disassembly did move something there).
4. Whether `wOptions` itself (vanilla 0xCFCC) is touched by the fork's own engine changes,
   as opposed to the new, unrelated `wArchipelagoOptions` block AP adds at 0xDFCC.
5. The AliceMousie-era project history (original 2023-11-10 release, 0.1 apworld
   2024-02-25, departure 2025-02-27, gerbiljames pickup 2025-03-13 at 2.1.2→3.0.0) is
   †SECONDARY from a single WebSearch summary and was not independently verified against
   primary commit history in this session.
6. Byte-exact vanilla pret addresses for `wMapGroup`/`wMapNumber`/`wMapEventStatus`/
   `wEventFlags`/`wStatusFlags` at the owner's new pret pin
   (`7a7881d0d62e0ddbd82dcf10e7116807487ac651`) — needs `tools/build_pret_syms.py` (RGBDS
   assemble), which is outside this note's lease (touches `.cache/pret` and
   `data/pret_syms.json`). Only a line-order structural check was done here.
7. Whether `rom_version == rom_version11 == 9006` in RC1's `data.json` reflects a genuine
   convergence of the V1.0/V1.1 ROM-embedded checksums, or is specific to how the
   `pokemon_crystal_prerelease` world populates that field pre-1.0-final. Not confirmed
   without generating and inspecting an actual patched ROM.
8. Whether the `pokemon_crystal` (stable) line will eventually adopt RC1's expanded RAM
   contract verbatim when `6.0.0` ships as non-prerelease, or whether the stable and
   prerelease worlds' address tables will keep diverging independently — no roadmap document
   was found in the repo to confirm either way.
