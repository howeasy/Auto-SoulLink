# Sections removed from docs/REFERENCE.md (2026-10-03)

> Historical record, written 2026-10-03. These sections were cut from `docs/REFERENCE.md`
> during an accuracy sweep. They are kept for their reasoning, not as current facts:
>
> 1. "What is proven, per generation" and "Why unit tests pass is not the bar": the
>    per-generation verification bookkeeping as of late September 2026. Current status lives
>    in `docs/gen1_gen2_runtime_checks.md` and the release lanes (`tools/verify_gen*_release.py`).
> 2. The Gen 1 local HUD/sound cue notes: describes `lua/gen1/client.lua` as of this date. The
>    code is the authority; line numbers cited below have drifted.
> 3. "Pokemon ability display", "Radical Red (CFRU) support", "ROM profiles" and "Sync timing
>    architecture": these described the old single-file Gen 3 client
>    (`lua/clients/gen3_frlge_client.lua` and `lua/memory_gba.lua`), deleted from the tree and
>    kept at tag `archive/gen3-old-client`. The current Gen 3 client is `lua/gen3/`, reading
>    `data/games/gen3_{frlg,rr,emerald}/` and `data/games/gen3_exp/`.
>
> Bodies below are verbatim.

---

## What is proven, per generation

- **Gen 3 FireRed / LeafGreen / Radical Red** — 🟡 Release candidate on the rewritten client under
  `lua/gen3/`: the frozen-cut gate passes FR/LG **43/43** and RR **19/19** on real cartridges
  (`docs/gen3/G4_request_draft.md`, `docs/gen3/G5_request_draft.md`); the owner's G4/G5 sign-off is
  pending. Only pinned cartridges are admitted, by ROM hash (`lua/slink.lua`); randomized and other
  unpinned builds are refused by name. Radical Red is companion-patched; a clean cartridge is refused.
- **Gen 3 Emerald** — 🟡 Release candidate on its own `gen3_emerald` pack under `lua/gen3/`, admitted
  by ROM hash or by its engine-site anchors (header-only builds refused). It pairs only with itself,
  never with FRLG/RR. The owner's EG4 sign-off is pending (`docs/gen3_emerald/PLAN.md` §10,
  `docs/gen3_emerald/`).
- **Gen 1 Red / Blue / Yellow** — 🟡 Partially verified. The Soul Link *mechanisms* are proven against
  running cartridges; a *playthrough* is not.
  - **Proven live** — **encounter linking from actual play**: both cartridges walk Route 1's grass,
    meet real wild Pokémon, throw real Poké Balls, and the server pairs the two captures by area on its
    own (`area=route_1`, nothing injected, Nuzlocke gate flipped by the client's own bag read). Plus
    faint propagation and party→box sync across two real cartridges; memorialize into Box 12; Explode
    Mode arming Explosion; the enemy-party write; `force_faint`; box level at `box+0x03`; Yellow's −1
    WRAM shift (reads); the companion patch's VBlank hook, its START-menu row, and the in-game panel
    (a page turn and a close) on both a clean and a randomized+injected cartridge. The rewritten
    client's duo harness (`tools/e2e_duo.py`, game `gen1_new`) runs **twenty** scenarios, all paired
    **Red (player A) against Blue (player B)** — there is no Yellow duo pairing in this harness.
    Yellow's −1 shift is instead exercised by the non-duo inspect/scripted live gates
    (`tests/live/test_gen1_new_gates.py`), which run on all three cartridges individually.
  - **Proven live, without injection** — encounter linking, the ball gate, the dead zone and the
    species clause: `link_new`, `ball_gate_new`, `deadzone_new` and `species_clause_new` walk Route 1's
    grass on both cartridges, meet real wild Pokémon and throw real Poké Balls, and the server pairs
    the captures by area (`docs/gen1_requirements.md` D-1..D-4).
  - **NOT proven live** — whiteout and the gender/type clauses; any map *transition* (every playing
    scenario stays on Route 1, so 1 of 39 encounter areas is exercised); evolution `key_change`; and
    the Archipelago variants, never launched. The scripted warp that would reach the other 38 is
    undrivable from Lua — `hWarpDestinationMap` at `$FF81` is shared HRAM the renderer overwrites
    within the frame (measured three ways before the probe was retired) — and the fly warp reaches
    thirteen destinations of which two carry encounters.
  - Rival swap and Explode Mode need **no ROM patch** on Gen 1 (no encryption, no checksums). The
    Red/Blue companion patch (required; Yellow is exempt and has none) adds the
    in-game SLINK panel and native sound. The VBlank `PlaySound` path ABI 2 used was swallowed during
    music fades and re-entered a non-reentrant audio routine, so sound now runs on the main thread:
    `SlinkSfxService` (`patch/gen1/src/slink.asm`, `SLINK_CAP_SFX`) plays the semantic code the client
    posts at mailbox `+7` (`request_sfx_local` in `lua/gen1/client.lua`, gated on `panel:sfx_present()`
    and `native_sounds`).
- **Gen 1 · pureRGB** — PureRed, PureBlue, PureGreen (v2.7.6 `7e7a4653`, one pinned release) — 🟡
  **Same bar as Red/Blue.** A second Gen 1 *foundation* (`game_id gen1_purergb`, adapter
  `server/adapters/gen1_purergb.py`, pack `data/games/gen1_purergb/`) on the same client, codec and
  server machinery; every game fact is generated from the pinned source and byte-verified in the built
  ROMs (`docs/purergb/PLAN.md`, §13.1 gate ledger).
  - **Admission by full ROM sha1** (`admission.json`, `admission_overlay.json`; the pure headers
    collide with vanilla's) — any other pureRGB version is refused. Randomized pure cartridges are
    admitted by every engine-site anchor + the overworld checkpoint bytes (kind `rand` /
    `rand_overlay`), then by the preparation contract's fingerprint **and** sha1.
  - **Reads through the flat `WRAM` domain** for `$D000-$DFFF`, writes gated on `WRAM BANK ∈ {0,1}`:
    pureRGB runs the overworld at GBC 2× and selects WRAM bank 2 inside its palette-buffer loop with
    interrupts enabled. BizHawk **Console Mode GBC**, not SGB.
  - **Overworld checkpoint** `PC == $0040`, `[SP] == DelayFrame+24`, `[SP+2] == OverworldLoop+1`,
    `wDelayFrameBank == 0` (`write_checkpoint.json`, generated with source asserts).
  - **Species by internal index**, never dex: 151 + 13 non-dex records (7 transformation forms, 5
    uncatchable spirits, MissingNo `$B5`) with pureRGB's default typings (the per-save Type Guy toggles
    are ignored by design) and `PokedexOrder` for the species clause.
  - **Identity:** script transformations (`ChangePartyPokemonSpecies`, 10 sites) and the APEX CHIP
    (DVs → `$FFFF`) are `key_change{reason: transform | apex_chip}`, **acknowledged** by the server
    (`key_change_ack` / `key_change_rejected`); a predicted collision (same species + OT already at
    `$FFFF`) restores the DV bytes at the commit site and sends nothing; a server-side rejection retires
    the pair (`identity_lost`). A transformed DEAD mon is re-fainted (the engine heals it to full HP).
  - **Explode Mode:** pureRGB's EXPLOSION only faints its user below ⅓ HP, so `force_explode` first
    drops the active battler under `max/3` (profile `derived.explode_low_hp_fraction`).
  - **Pairing:** pureRGB pairs only with pureRGB, same artifact kind (clean↔overlay is refused); Cable
    Club trades between a vanilla and a pure cartridge are not supportable.
  - **Companion overlay** (`patch/gen1/purergb/`, `patch/dist/SLink-Pure*.ups`): the vanilla binary
    patch cannot apply (ROM0 is full, RST vectors are live code, the vanilla mailbox address is inside
    pureRGB's box data), so the native trade, the START-menu SLINK row + panel and an APEX collision
    guard are **source sections** linked into the pureRGB build: bank `$3F`, 15 bytes of ROM0, a 12-byte
    mailbox at `$DEEA` (the bank-1 WRAM tail), ABI 3 / lease `SLT1` unchanged. RAM/SRAM placement is
    proven equal to the clean build, and a clean save loads on the overlay unchanged (A4 gate,
    `tests/unit/test_gen1_purergb_overlay.py`).
  - **Randomizer:** the SLink fork of UPR ZX 4.6.1 (`patch/upr/*.patch`, `tools/build_upr_fork.py`, jar
    `4.6.1-slink3`, fork revision 3 required) with lossless load→save for pure entries, generated INI rows
    (`tools/gen_upr_gen1_ini.py`), a write-domain audit (`tools/upr_write_domain_diff.py`) and every
    code-patching tweak refused (`server/upr_settings.py` pure family); one tweak allowed, lower-case
    names (a data write over the species-name table, re-cased byte-for-byte in place).
  - **Evidence:** unit pins mirror the vanilla contract (`tests/unit/test_gen1_purergb_*.py`); live:
    inspect on all six pure cartridges (clean + overlay), APEX restore and APEX refusal gates,
    receptionist/menu-row/panel on the overlay, GBC FADE stress; duo: the vanilla scenario set on
    PureRed↔PureBlue, PureRed↔PureGreen and the overlay pairing (`tests/e2e/test_duo_gen1_pure.py`,
    lane `duo-pairs-purergb`), including `admit_randomized_new` on the fork jar.
- **Gen 2** — Gold, Silver, Crystal (GBC) — 🟡 **Partially verified.** Same shape as Gen 1: the
  *mechanisms* are proven against real cartridges, a *playthrough* is not.
  - One adapter serves all three titles: `server/adapters/gen2_gsc.py`, with `gen2_codec.py` (save and
    party structs) and `gen2_rom_scan.py`, over the per-title packs `data/games/gen2_{crystal,gold,silver}/`,
    all generated from the pinned pret decomps (`data/gen2_sources.lock.json`). The legacy Crystal-only
    adapter was removed at the P3b.8 cutover.
  - **Proven live** on real dumps of all three titles, in **98** PHYSICAL duo and gate cells (pairings
    C↔C, G↔S, C↔G) judged from committed receipts by `tools/verify_gen2_release.py`. Duos: encounter
    linking, the species/gender/type clauses, the ball gate, faint and active-battler faint (wild and
    trainer), whiteout and whiteout-rebuild, overworld poison, PC deposit/withdraw/release and box
    changes, NPC trade, evolution, gift, egg hatch, boxed capture, reconnect, soft reset, wrong-ROM
    admission, and the native SLINK TRADE (commit, decline, refuse-item, trade-evolve, timeout,
    reset). Gates: read, engine sites (all three titles) and write windows (Crystal, Gold; Silver
    shares Gold's, O-23); on the companion overlay the START-menu panel, native sound, phone calls,
    the W6 write guard and the battle-text stack low-water gate. The memorial box is the last box
    (`gen2_gsc.memorial_box_index`).
  - **Not proven:** a full playthrough. The Gen 2 dead zone rides on the generation-independent server
    rule that Gen 1's `deadzone_new` proves live; there is no Gen 2 dead-zone duo.
  - **Companion overlay** (`patch/dist/SLink-{Crystal,Gold,Silver}.ups`): **admitted and required**.
    The overlay rows are SELECTED/ADMITTED under the G4 runtime gate, so a clean Crystal/Gold/Silver
    cartridge is refused exactly like any other companion title.

### Why "unit tests pass" is not the bar

That distinction is not academic, and Gen 2 proved it twice. Bringing Gen 1 up found defects no static
check could reach — a deferred-command queue that bound to a nil global and crashed the client on the
first box or memorialize command; a `party_to_box` debounce that could never complete, so party/box
sync was silently dead; a box level read from an offset past the end of the box struct; Archipelago
detection reading HRAM instead of ROM. Gen 2 went in with a larger unit suite than Gen 1 ever had and
everything the static suite could not see was wrong: Gold, Silver and AP Crystal routed to the **Gen 3**
adapter, `party_blob_size()` inherited 0 so every Gen 2 party blob was discarded, no profile declared
`stats_offset` so every box deposit dropped the stat block, and the Apricorn ball IDs pointed at
SUN_STONE, leaving the Nuzlocke gate shut for anyone carrying balls Kurt made. All of it passed the
unit suite and the Lua syntax gate. Treat "unit tests pass" as necessary, not sufficient.

---

## Gen 1 local HUD and sound cues

Gen 1's HUD/sound is not purely a server-pushed overlay: `lua/gen1/client.lua` also raises its own
local moments, mirroring the old Gen 3 client's client-only cues (`archive/gen3-old-client:lua/clients/gen3_frlge_client.lua`) rather than
waiting on a command. A Nuzlocke-start banner fires once, on the first Poke Ball landing in the bag
*during play* (the `bag_received` hook or a `send_tick` ball-count edge) — never at a hello that
already finds one there, which only logs; the latch (`self.nuzlocke_announced`) is a client-session
concept, not a save-file one, so it survives a WRAM-clearing soft reset and a CONTINUE reload rather
than resetting with the other identity latches. A `** NEW ENCOUNTER **` banner fires on
`area_enter`/`wild_begin` once the run has seeded `resolved_areas`, the area is unresolved, and the
encounter is the player's own: a scripted/static encounter, a demonstration battle (Y-0) and a Tower
ghost battle fought without the Silph Scope are excluded on `wild_begin` (the demo and ghost
predicates are `battle_end`'s own; the static exclusion is the banner's alone — an uncaught static
still resolves its own `static_<map>_<dex>` slot through `no_catch`). On plain map entry the "no gift area" half of that gate
cannot be `area_id`-based — the server's gift-area list (`server/adapters/gen1_rby.py`'s
`_GIFT_AREAS`) is not on the wire, and a gift area like Oak's Lab is a real, non-`gift_map_*`-prefixed
`area_id` — so it instead requires the entered map to appear in `self.wild_maps`, the cartridge's own
wild-data table read at hello (`rom.rom_content()`), and requires being outside battle (a map
transition mid-trainer-battle must not banner). That table holds grass/surf records only: a
fishing-only map (Pallet Town, Cerulean Gym, Vermilion Dock — both rates zero) gets no entry banner
and is announced when the rod battle actually starts; the entry banner is a hint, not an oracle. A KO'd banner is always text-only, but not for one
uniform reason: the server's `play_sound 26` rides alongside a terminal/linked-battle-faint
`force_faint` (`server/state.py:2884`), so a local cue there would double it, while the
whiteout-driven retire loop (`:2073`) and the dead-key requeue after a buried `key_change` (`:2708`)
carry no sound of their own either — the whiteout case gets its own local cue from the client's own
whiteout detection instead. `game_over` requests that same local cue, because neither of the server
paths that queue it (`:2103`, `:3202`) pairs it with a `play_sound`; `request_sfx_local` keeps a per-frame
set of the semantic codes already posted, so an identical code requested again in the same frame
(that terminal-faint `play_sound 26` landing beside `game_over`'s own local 26, or a 26/25/26
interleave) posts once while distinct codes stay distinct; the same code one frame later is a new
cue. The deposit/withdraw/memorialize banners (boxed/unboxed/
buried, and the box/memorial failure variants) land where the deferred queue observes the result —
`lua/gen1/boxes.lua`'s return value — not where the command was received; the one exception is a
retired-alias command the checkpoint itself refuses (a lost/ambiguous record), which answers the
server with `..._failed` but shows no HUD banner, matching how that refusal already differs from an
ordinary box-module failure. Every local cue shares the same native-SFX gate as a server `play_sound`
command (`self:request_sfx_local`, `lua/gen1/panel.lua`'s `sfx_code_for`/`sfx_present`/
`config.native_sounds`); an id with no Gen 1 mapping returns early rather than tripping the
one-time "unavailable" log, and on an unpatched cartridge the banners still render while the sound is
silently absent.

---

## Pokémon Ability Display

> **Archived (C5-6, owner ruling 24):** this section describes the old Gen 3 client (`lua/clients/gen3_frlge_client.lua` + `lua/memory_gba.lua`), deleted from the tree and kept at tag `archive/gen3-old-client`. The rewritten client under `lua/gen3/` reads through `data/games/gen3_{frlg,rr}/profile.json`; this section awaits that rewrite.

The status page displays ability names for party mons, PC box mons, and enemy/wild mons during battle. Abilities are resolved from `gBaseStats` in the ROM using the mon's species ID and ability bit (from the encrypted substruct data).

**How abilities are read:**
1. **Primary method:** `memory_gba.lua` decrypts the species ID and ability bit from the party/box mon's substruct, then looks up `gBaseStats[species].ability1` or `ability2` based on the bit
2. **Fallback (gBattleMons cache):** During battle, ability IDs are read directly from `gBattleMons[battler].ability` (offset `+0x20`). These are cached in `_ability_cache` keyed by monKey and used as a fallback when substruct decryption fails or returns 0
3. **Server-side:** `pokemon_data.py` provides `ability_name(ability_id, is_rr)` and `ability_description(ability_id, is_rr)`. For RR/CFRU (`is_rr=True`), uses a 255-entry table with RR-specific ability names and descriptions (sourced from funnotbun's RR Dex). For vanilla/Gen 4 (`is_rr=False`), uses a complete 165-entry vanilla table (Gen III–V, IDs 1-165) with correct standard ability names and descriptions. Hovering ability names on the status page shows a tooltip with the description.

**Per-species ability name overrides (RR/CFRU).** Some abilities have species-specific renames in Radical Red (e.g. Mightyena's "Intimidate" displays as "Strong Jaws"). `pokemon_data.CFRU_ABILITY_NAME_OVERRIDES` is a merge of two layers:

- `CFRU_ABILITY_NAME_OVERRIDES_GENERATED` — auto-built from funnotbun's `data/abilities/duplicate_abilities.h` by `tools/gen_ability_name_overrides_rr.py`. Output is written to `server/rr_ability_overrides.py` (regenerate by running the script; ~87 entries covering Shell Armor on Slowbro-Mega, Vital Spirit on Mankey/Primeape, Air Lock on Rayquaza, etc.).
- `CFRU_ABILITY_NAME_OVERRIDES_MANUAL` — hand-curated entries for species not yet in funnotbun's upstream file. Shadows GENERATED on key conflict, so locally-observed renames always win.

Override keys are `(ability_id, natdex_base_form)`. Form collisions (e.g. Kyurem-Black "Teravolt" and Kyurem-White "Turboblaze" both mapping to NatDex 646 with `ABILITY_MOLDBREAKER`) are detected by the generator and emit a warning; both entries are dropped so neither shadows the wrong form.

**Profile-specific gBaseStats addresses:**
| Profile | gBaseStats address | Source |
|---|---|---|
| Vanilla | `0x08254784` | Hardcoded from pret/pokefirered |
| AP | `0x0825634C` | Shifted from vanilla (AP recompiles from source) |
| RR/CFRU | Pointer at `0x080001BC` → actual address | Dynamic via CFRU function pointer |

---

## Radical Red (CFRU) Support

> **Archived (C5-6, owner ruling 24):** this section describes the old Gen 3 client (`lua/clients/gen3_frlge_client.lua` + `lua/memory_gba.lua`), deleted from the tree and kept at tag `archive/gen3-old-client`. The rewritten client under `lua/gen3/` reads through `data/games/gen3_{frlg,rr}/profile.json`; this section awaits that rewrite.

SLink supports **Pokémon Radical Red 4.1** ([CFRU](https://github.com/Skeli789/Complete-Fire-Red-Upgrade)) through the `gen3_rr` pack (`data/games/gen3_rr/`: `profile.json`, `engine_signals.json`, `write_checkpoint.json`), companion-patched only. All core features — encounter linking, faint propagation, party/box sync, memorial box, species/gender/type clause — work identically to vanilla.

**Admission:** There is no CFRU signature scan any more. `lua/gen3/entry.lua` `Entry.admit` matches the cartridge hash against the pinned `rom_sha1`/`rom_md5` rows in `engine_signals.json`; a hash in no table is admitted by anchors (every engine site of exactly one pack/title/kind still reads as pinned in ROM), and a header-only match is refused (`admit_routed`). A clean or randomized-clean RR is refused too: the `gen3_rr` pack sets `companion_required`, and the server refuses it at the hello (`companion_refusal` in `server/adapters/gen3_frlge.py`).

### Key architectural differences from vanilla/AP

| Feature | Vanilla / AP | Radical Red (CFRU) |
|---|---|---|
| **Substruct encryption** | XOR-encrypted with `personality ^ otId`; permuted order based on `personality % 24` | **Unencrypted**; fixed order: Growth / Attacks / EVs / Misc |
| **PC box storage** | 80-byte `BoxPokemon` × 30 slots × 14 boxes (contiguous after `PokemonStorage+0x01`) | **58-byte `CompressedPokemon`** × 30 slots × **25 boxes** in **4 non-contiguous EWRAM regions** |
| **Party struct in battle** | Live — HP/level updated in real-time in `gPlayerParty` | **Stale during battle** — live HP/level only in `gBattleMons`; battle HP cache handles writeback to party struct on battle end |
| **Bag location** | Inside `SaveBlock1` (SB1 pointer + offset); AP encrypts quantities | **EWRAM at fixed address** (`0x0203C354` for ball pocket); not inside SB1; **not encrypted** |
| **Battle outcome (caught)** | `B_OUTCOME_CAUGHT = 6` | `B_OUTCOME_CAUGHT = 7` (`B_OUTCOME_MON_FLED = 6` inserted before it) |
| **Battle detection** | Vanilla: `gMain+0x439` inBattle bit. AP: `gMain+0x038` overworld + three-condition check | **`gBattleOutcome`-based** ("battle_outcome" detection mode) — `gMain` is unreliable in CFRU |
| **Species IDs** | National Pokédex (1–386) | Extended to ~1293 (Gen 1–8 + forms); IDs diverge from NatDex after Gen 2 |
| **Ball pocket slots** | 13 (vanilla) / 16 (AP) | **50 slots**; 27 ball item types (IDs up to 631) |

### Confirmed Radical Red addresses

| Symbol | Address | Notes |
|---|---|---|
| `gPlayerParty` | `0x02024284` | Same as vanilla EWRAM — **live** copy (stale during battle) |
| `gPlayerPartyCount` | `0x02024029` | EWRAM global |
| `SB1_PTR_ADDR` | `0x03003840` | IWRAM |
| `SB2_PTR_ADDR` | `0x03003838` | IWRAM |
| `PokemonStorage` base | `0x02029314` | EWRAM — first of 4 non-contiguous box regions |
| `gBattleMons` | `0x02023BE4` | EWRAM — live HP/level/status during battle |
| `gBattleOutcome` | `0x02023E8A` | EWRAM — same address as vanilla |
| Ball pocket | `0x0203C354` | EWRAM, 50 slots × 4 bytes, not encrypted |

### Battle HP cache (CFRU writeback)

In CFRU, `gPlayerParty` is **not updated during battle** — the game engine copies party data to `gBattleMons` at battle start and only writes back on battle end. This means faint detection during battle must read from `gBattleMons`, not `gPlayerParty`. The Lua client maintains a **battle HP cache** keyed by **monKey** (not slot index) that:

1. Reads HP from `gBattleMons` every frame during battle (mapping battler personality → monKey)
2. Detects faints (HP 0) in real-time from the battle struct — guards against re-reporting server-initiated force_faints via `force_fainted_keys` set
3. Writes back final HP values to `gPlayerParty` when battle ends — scans party by monKey to find the correct slot, ensuring writeback targets survive mon switches mid-battle

**Frame execution order (critical for CFRU):** CFRU can set `gBattleOutcome` on the **same frame** as the last mon's HP→0. The Lua client executes in this strict order each frame:

1. Battle start detection (clears cache)
2. Battle HP cache update from `gBattleMons` — gated on `in_battle OR battle_just_ended` to capture the final frame
3. Battle end writeback (writes cache to party struct, then clears cache)
4. `index_party()` — reads party struct with cache overlay if in battle
5. Party diff (faint/whiteout detection)

**Double-buffer party diff:** `index_party()` uses two independent entry pools (one per buffer frame) to compare previous and current party state. Each buffer owns its own pre-allocated entry tables so that writing current-frame HP never overwrites previous-frame data — this is essential for detecting HP transitions (alive → fainted).

### Doubles battle detection (Gen 3)

`is_doubles` is set on the battle state when `gBattlersCount >= 4` (`M.isDoubleBattle()` in `lua/memory_gba.lua`, `BATTLE_TYPE_DOUBLE_MASK` constant; works on all profiles including RR). Active battlers are read from `gBattlerPartyIndexes`: players are battlers 0+2, enemies are battlers 1+3. The status page renders a DOUBLES chip in the battle panel header; the `enemy-focus` overlay renders both active foes side-by-side via `.focus-mons.doubles`; the player `focus` overlay does the same when two party mons are active.

Singles also use `gBattlerPartyIndexes[0]`/`[1]` as the primary active-detection path, with species+level match against `gBattleMons` as a fallback when the index read is stale (`idx >= 6`, e.g. CFRU address drift). Gen 4/5 clients emit `evt.is_doubles=false` stubs for now.

### Enemy moves and live PP (Gen 3)

Each foe row in the status battle panel has a collapsible "Moves (N)" table. For active enemy battlers, moves and PP come from `gBattleMons[1]` (and `gBattleMons[3]` in doubles) at the following offsets:

- `+0x0C` — moves (4 × `uint16`)
- `+0x24` — current PP (4 × `uint8`)
- `+0x3A` — PP-Up bonuses (packed in one `uint8`)

The Lua client overlays these onto the matching enemy party entry so post-use PP shows immediately. CFRU's `battle_seen_enemies` accumulator and the player party snapshot also forward `pp_bonuses`. For full party slots (not just active battlers), `M.decryptMoves` and `M.decryptPpBonuses` in `memory_gba.lua` decode moves/PP/ppBonuses from substructs (CFRU unencrypted layout and vanilla/AP encrypted substruct both supported).

Server enrichment (`_enrich_party` / `_enrich_battle_state` in `server/server.py`) resolves raw move IDs via `adapter.move_data()`, attaches `current_pp` from `raw_pp[]`, and applies the PP-Up multiplier:

```
max_pp = base_pp + (base_pp * pp_ups) // 5
```

Without this multiplier, RR trainer mons with PP-Ups would show e.g. `56/35` instead of `56/56`. The formula is guarded by `if base_pp:` so unknown moves (base_pp = 0) don't divide-by-zero. The status page row uses a `data-key` so idiomorph's `beforeAttributeUpdated` hook preserves the user-toggled `<details open>` state across HTMX morph swaps.

---

## ROM Profiles

> **Archived (C5-6, owner ruling 24):** this section describes the old Gen 3 client (`lua/clients/gen3_frlge_client.lua` + `lua/memory_gba.lua`), deleted from the tree and kept at tag `archive/gen3-old-client`. The rewritten client under `lua/gen3/` reads through `data/games/gen3_{frlg,rr}/profile.json`; this section awaits that rewrite.

SLink supports two ROM profiles, auto-detected at startup by `memory_gba.lua`. All profile-dependent addresses are stored in the `PROFILES` table and applied via `M.initProfile()`.

| Profile | ROM type | Detection method | Battle detection | Box format | Substructs |
|---|---|---|---|---|---|
| **`vanilla`** | Standard FRLG US 1.0 + data-only randomizers (UPR, etc.) | Default — no CFRU signature found | `gMain+0x439` inBattle bit (bit 1, mask `0x02`) | 80-byte `BoxPokemon` × 30 × 14 boxes | Encrypted (XOR `personality ^ otId`); permuted order (`personality % 24`) |
| **`radical_red`** | Radical Red 4.1 / CFRU-based hacks | CFRU signature bytes in ROM binary | `gBattleOutcome`-based ("battle_outcome" mode) — `gMain` unreliable in CFRU | 58-byte `CompressedPokemon` × 30 × 25 boxes (4 EWRAM regions) | **Unencrypted**; fixed order: Growth / Attacks / EVs / Misc |

For full address tables, see the [RR Support](#radical-red-cfru-support) section above. All vanilla addresses in the FRLG Memory Map section below apply only to the `vanilla` profile — RR uses different addresses as documented in their respective profiles in `lua/memory_gba.lua`.

---

## Sync Timing Architecture

Sync commands (`box_mon`, `party_mon`, `memorialize`) are **deferred to safe state** to avoid corrupting party/box data during battle or transition animations.

**Safe state requirements (all must be true):**
1. **Overworld** — player is in the overworld (not in battle, menu, script, or animation)
2. **Sync cooldown expired** — a per-command cooldown prevents rapid-fire writes
3. **Not `battle_just_ended`** — the battle-end transition must fully complete
4. **`post_battle_frames == 0`** — a 30-frame cooldown after battle ends, plus a 90-frame post-battle grace period (~2 seconds total at 60fps)

**Execution model:**
- Commands execute **one per frame** to avoid party corruption from concurrent slot compaction (e.g., two `memorialize` commands zeroing adjacent slots simultaneously would corrupt the shift-down logic)
- The ~2-second post-battle buffer ensures the game engine has fully written back battle results to the party struct before SLink modifies it
- During the grace period, the Lua client suppresses party diff detection to avoid false `box_to_party` / `party_to_box` events from engine writeback

**PP preservation (CFRU):** The 58-byte compressed box format does not store PP. On deposit, the client caches PP values (read from party struct `+0x34..+0x37`) in `mon_stats_cache`. On retrieval via `retrieveBoxMon`, PP is restored from the cache (or defaults to 35 for non-zero moves as a fallback for legacy entries).

**Item integrity protection (CFRU):** CFRU's game engine may react to party modifications between frames and inadvertently swap held items. The client implements a defensive snapshot/verify system:
1. Before any sync operation (`box_mon`, `party_mon`, `memorialize`), `snapshot_party_items()` records every party mon's held item keyed by monKey
2. Immediately after the operation completes, `verify_party_items()` checks each mon's item against the snapshot and writes back any that changed unexpectedly
3. Verification continues for 5 frames after sync to catch between-frame engine interference
4. The snapshot stays current during normal gameplay (updated each `build_party_snapshot` call) so legitimate item changes (e.g., player equipping items) are never falsely reverted

---
