# SLink Companion Patch (Radical Red) — testing guide

FireRed, LeafGreen and Emerald companions are published as
`patch/dist/SLink-{FireRed,LeafGreen,Emerald}.ups`. Apply each to its matching
English revision-0 ROM through `/patcher`; `gen3_companions.json` pins the base,
result and UPS hashes. These builds use ABI2 at `0201B000` and reserve the last
4 KiB of the native heap. FR/LG publish capabilities23; Emerald publishes87,
including Match Call. RR keeps the separate ABI1 build described below.

Build or verify a vanilla companion with
`python patch/tools/build.py --target firered --rom <clean.gba>` (substitute
`leafgreen` or `emerald`), adding `--check` to compare the UPS and manifest without
publishing changes. `--trade-candidate` remains a private test build. The release
builder's `--with-patch` option includes all three UPS files and their manifest.

The Manager can compose a companion after an allowed randomizer run: it refuses
any randomizer change inside the companion's protected code/data spans. The
final ROM hash belongs to the run contract. Native capability and randomized
pairing remain separate; the hello uses the existing `rand` wire kind.

**Title screen and main menu.** Every Gen 3 companion (FireRed, LeafGreen, Emerald, and Radical Red's ABI1 build) puts a
SoulLink wordmark in the Pokémon logo's style on the title and prints the patch version (`SoulLink vX.Y.Z`, or `SoulLink
dev`) on the main menu, the New Game / Continue screen. The version lives there and nowhere else (owner, 2026-10-02: like
the Game Boy menus).

*Title:* a static asset patch with no code (`patch/tools/gen3_title.py`, art from `tools/gen_gen1_title.py`): the title's own
LZ77 graphics are relocated into the ROM's free tail with the wordmark added and the two literal-pool words that name them are
repointed, so the game's loader draws it and the fade-in, flash and restarts treat it as part of the title. FR / LG / RR use
the Charizard / Venusaur layer on its empty rows under the flames, the wordmark's ink centred on PRESS START, in the logo
palette's unused bank; Emerald uses the affine Pokémon-logo layer (the clouds and Rayquaza scroll and blend) under the
"Emerald Version" banner, in the logo's own palette indices, centred on the screen, so it slides in with the logo. The
title spans join the manifest's protected spans.

*Main menu:* neither menu has a static BG asset (the whole BG0 map is built by windows at run time), so the payload's frame
hook owns one window (`patch/src/trade_targets/native_menu.h`, shared by the FR / LG / Emerald companions and Radical Red's
`handlers.c`). While `gMain.callback2` is the menu and its task (always `gTasks[0]`) idles in its input or cursor function,
it draws the line once in the game's own font, right-aligned on tile rows 17-18, and frees the window the moment the menu is
left. That is the free band under the boxes, or, with a Mystery Gift box there, the right half of that box (the layout is
read from `gTasks[0].data[0]`). FR / LG have no menu at all on a cartridge without a save (the game goes straight to the
intro); Emerald shows New Game / Option with the line below. `build.py --version vX.Y.Z[-dev]` (default `dev`, at most ten
characters) encodes the line in the charmap and passes it to the compiler as `-DSLINK_MENU_TEXT=...`; the receipt and the
manifest row record it as `menu_version`. Per-game addresses are the `SLINK_TARGET_MENU_*` defines in the target headers
(RR's `SLM_*` literals in `handlers.c`; RR's menu is FireRed's, byte for byte). The state byte is arena offset `0x920` on the
native companions and `0x0203FF61` on RR.

Measured facts: `tests/fixtures/gen3/title_*.json` (`lua/tests/probe_gen3_title_vram.lua`, `tools/analyze_gen3_title.py`) and
`tests/fixtures/gen3/menu_*.json` (`lua/tests/probe_gen3_menu_plan.lua`, vanilla menus in every layout); tests:
`tests/unit/test_gen3_title_screen.py`, `tests/unit/test_gen3_menu_version.py` (the ROM checks need `SLINK_GEN3_ROMS`, the
compile checks a toolchain).
**Not promoted:** the published UPS files and `gen3_companions.json` are still the build without the title wordmark or the
menu line, so `build.py --check` differs until the owner regenerates them (every companion ROM hash, and the pins built on
it, moves); `tools/make_release.py` does not yet re-stamp the version.

> The Game Boy companion builds live beside this one: `patch/gen1/` (the Red/Blue binary patch,
> `patch/dist/SLink-RB-{Red,Blue}.ups`) and `patch/gen1/purergb/` (the pureRGB **source overlay**,
> `patch/dist/SLink-Pure{Red,Blue,Green}.ups`). `tools/make_release.py --with-patch` bundles all
> six patches; `/patcher` applies any of them in the browser.

A native code-injection layer for Radical Red. When applied, the SLink Lua client detects
it and uses native in-game features. The Soul Link rules themselves run in Lua on every
cartridge, patched or not.

## Patch-first (owner, 2026-10-01; companion REQUIRED 2026-10-02)

The companion is **required** for every title that has one: Red/Blue, pureRGB, Gold/Silver/Crystal,
FireRed/LeafGreen/Emerald and Radical Red. The Manager patches it into every cartridge it prepares,
with no opt-out (`server/cartridges.py` `COMPANION_TITLES`), and it **refuses** a pick it cannot
patch instead of handing out a clean one. A clean (unpatched) cartridge of those titles is refused
twice more, so it cannot be used by bypassing the Manager: by the launcher (`lua/gen1/entry.lua`
`admit_routed`, `lua/gen3/entry.lua` `admit_routed`; Gen 2's launcher and adapter refusal land with its
overlay re-admission) and by the server at the hello (`GameRulesAdapter.companion_refusal`, overridden
per adapter). A randomized
cartridge is randomized and then patched; a randomized-clean one is refused like any clean one. The
player-facing reason: this cartridge needs the SLink companion patch, so prepare it through the Manager
or `/patcher`.

**Exempt, still admitted clean:** Yellow (zero free WRAM, so no companion exists), the Archipelago
builds (permitted by policy, but the Manager lists no Archipelago game until a client supports one),
the Emerald Expansion (`gen3_exp`, its companion does not exist yet) and Gen 4/5 (never run against a
real game). Those keep sharing the Lua rule paths, which is why those paths stay.

**New ROM-side features are companion-only.** They get no Lua/HUD fallback, so a cartridge
without the companion simply lacks them, the way Rival Swap answers `patch_required` on Gen 3.

## Prerequisites — the patch is per-RR-build

The patch is built against **one specific Radical Red build**:

| | |
|---|---|
| Base ROM | `Pokemon - Radical Red.gba` |
| md5 | `8529f3a45d32bce4da637976fcf269d4` |

If your RR's md5 differs, the patch will not match (the engine/controller addresses are
build-specific). Re-pin and rebuild for a different build: `python patch/tools/build.py`.

## Apply the patch

Apply `patch/dist/SLink-RR.ups` to your clean RR ROM with any UPS patcher
(Flips, NUPS, RomPatcher.js, …). Result md5 should be `70e7e746e573a2d00df5d3ef41d19d61`.
Then load the patched ROM in BizHawk as usual.

UPS only — no IPS is provided. The patch now bundles the **Battle Calc** (the in-battle
damage calculator, below), whose code lives above 16 MB; IPS's 24-bit offsets can't reach it.

## Verify the patch loaded

Start the patched ROM; within a second or two the patch writes a `'SLNK'` beacon to EWRAM
`0x0203F800`. The SLink client logs `companion patch: present` when it detects it (and
falls back silently when it doesn't). A dev smoke check: load `lua/tests/test_mailbox_ping.lua`
in EmuHawk → it reports `RESULT: PASS`.

## Bundled Battle Calc (in-battle damage calculator)

The emitted patch folds in the **Battle Calc** — an in-battle **damage / type-effectiveness
calculator** extracted from a custom RR4.1 build. In the move-selection menu it shows a
computed value for the highlighted move. It detours `BattlePutTextOnWindow`, reads
`gMoveSelectionCursor`, and renders from new functions at ROM `0x09360000` (full delta map
in `src/ADDRESSES.md`).

It is captured as a base-RR → RR4.1_Custom UPS delta in `src/rr41_battle_calc.ups`
(regenerate with `tools/make_battle_calc_patch.py`) and applied before SLink injection;
SLink's own code was moved to `CODE_BASE 0x08378F70` to sit just above the Battle Calc's
`0x08378CA8` block. Build without it via `python patch/tools/build.py --no-battle-calc`.

It can also be hidden **per run at runtime** (no rebuild): the run's `battle_calc` toggle
(run-manager checkbox / `--no-battle-calc` server flag) drives an EWRAM kill-switch byte
(`SLINK_CALC_OFF 0x0203F8D8`, inverted: boot-default 0 = shown) that makes the battletext
shim skip the calc trampoline entirely.

## Per-run feature toggles

Every patch feature the run can configure rides the server's `config` command (sent on hello;
set per run in the run manager's **New run** form or via server CLI flags):

| Toggle | Default | CLI | Off behaviour |
|---|---|---|---|
| `native_messages` | OFF | `--native-messages` | Lua HUD overlay (field + in-battle) |
| `native_sounds` | OFF | `--native-sounds` | Lua m4a `playSE` poke |
| `battle_calc` | ON | `--no-battle-calc` | damage display hidden (kill-switch byte) |
| `pc_trade_npc` | ON | `--no-pc-trade-npc` | no Pokémon-Center trade NPC (only effective while overworld presence is OFF) |
| `phone_calls` | ON | `--no-phone-calls` | Gen 2 only: no Pokégear call for first link / dead zone / fallen (the HUD pop-up still shows) |

Run RULES that happen to need the patch (`--explode-mode`, `--rival-team-swap`,
`--overworld-presence`) stay opt-in per run as before. **Not toggleable by design**: native PC
box⇄party storage (24/25), the native trade scene (21), memorialize (26), party freeze and the
peer-interact plumbing — they're correctness paths, not preferences (the Lua fallbacks remain
for unpatched ROMs only).

## What's wired into a real run TODAY

- **Native message box** for momentous *overworld* events — a link forms, a shiny is found,
  a bonus pair links, an area becomes a dead zone. The client routes these to the native box
  when patched + in the overworld, else to the HUD/center-prompt (so unpatched/in-battle is
  unchanged).
- **Peer ghost (Overworld Presence) — deferred post-RC, not currently driven.** The native opcodes
  below (`OP_SPAWN_PEER_NPC` / `OP_DESPAWN_PEER_NPC` / `OP_ARM_PEER_INTERACT`) are built into the
  patch and were live-validated against the old, now-archived Gen 3 client (`archive/gen3-old-client`,
  its `peer_ghost_npc.lua`). The rewritten Gen 3 client (`lua/gen3/`) never sends the opcodes that
  arm it — `lua/gen3/client.lua`'s `ghost_pos` handler is a no-op — so no NPC spawns yet (owner
  ruling 2026-09-22, deferred post-RC). What the ROM side does when driven: spawns a real engine
  object-event rendered as the partner's own trainer avatar + colours, LERPs it toward broadcast
  sub-pixel positions (continuous, speed-agnostic), matches bike/surf/fishing graphics via the
  partner's own `graphicsId`, and applies native day/night tint measured from the player's own
  palette slot.
- **Talk to your partner → action menu (Trade / Say hey).** Face the Pokémon Center's trade NPC
  (`pc_trade_npc`, on by default while Overworld Presence is off — the peer-ghost interact path
  above is deferred) and press A to open a native **multichoice list** (`Trade` / `Say hey`, extensible). **Say hey** pings the partner
  (the in-game nuzlocke status helper). **Trade** opens the native **"Choose a
  POKéMON" party menu**; only a *linked* mon is accepted (anything else re-prompts). Your **partner**
  then gets a single confirm (showing your badge count); on accept, the **real in-game trade animation
  plays on both sides** (`DoInGameTradeScene` against the partner's matching half staged in
  `gEnemyParty[0]`) — including **trade-evolution** (Kadabra→Alakazam, etc.) — and the link reconciles
  to the post-trade species. The two mons are always the **matching halves of one link** (the server
  auto-selects the partner's counterpart; you can never trade for an unlinked or different-link mon).
  (Falls back to a faithful silent swap if the native scene is unavailable.)
- **Native sound.** Server `play_sound` cues (link formed, KO, shiny, …) play through the patch
  (`PlaySE`) when present **and the `native_sounds` toggle is ON**, instead of the Lua m4a
  RAM-poke — fallback keeps unpatched ROMs (and toggled-off runs) working.
- **Native PC box ⇄ party storage** (`DEPOSIT_MON` 24 / `WITHDRAW_MON` 25) — server-driven
  box/party sync runs through CFRU's own compressed-box conversion (async, settled in the
  client's storage poll; Lua RAM-poke path remains the unpatched fallback).
- **Native memorialize** (`MEMORIALIZE` 26) — dead linked mons move to the memorial box in one
  frame-hook pass (compress + zero + swap-with-last, survivors keep their slot indices). Async
  like storage; on any failure the client reverts to the Lua path for the rest of the session.
- **Event-push ring** (`EvRing 0x0203FD10`) — the patch pushes faint-settled (gBattleResults
  counter deltas) and battle-outcome edges; the client drains them each frame
  (`MB.events_drain`). Foundation: today they're logged alongside the proven Lua detection;
  consumers migrate per `patch/ROADMAP.md`.

## Validated but NOT yet wired into the server-driven client

These opcodes are built and live-validated (see `lua/tests/test_live_*.lua`) but the
production client doesn't invoke them yet — each needs its own server/client integration
(the message box above is the template):

- Battle: `FORCE_FAINT`, `FORCE_MOVE_SLOT` — validated headlessly
  (`lua/tests/test_live_forcemove.lua`) but **deliberately never sent by the client**: the
  controller swap softlocked in real play, so the Lua Variant-3 RAM path is the single
  production mechanism.  Reserved in the ABI; see `patch/ROADMAP.md` §2.
- Mon: `CREATE_MON`, `GIVE_MON` (`SET_ENEMY_PARTY` rival-team-swap and `SET_PARTY_MON` trade ARE wired)
- Overworld: `ARM_PEER_INTERACT` (talk-to-ghost; `SPAWN/DESPAWN_PEER_NPC` is now wired — see above)
- Rules/UI: `PLAY_FANFARE` (`SHOW_MENU`, `PLAY_SE` ARE wired)

Removed (opcode numbers 10–12 reserved): `APPLY_DAMAGE`, `CURE_STATUS` (linked chip/status — dropped),
`SET_RULES` (nuzlocke battle-style — redundant on RR). See `ADDRESSES.md` › "Removed opcodes".

Opcode/address reference: `patch/src/ADDRESSES.md`. Build pipeline: `patch/tools/build.py`
(gcc → ld → objcopy → inject → UPS/IPS, all round-trip self-checked).

## Gen 1 Red/Blue companion patches

The trade-carrying Red/Blue patches are separate UPS files for their exact clean dumps:

| Patch | Clean ROM md5 | Patched ROM md5 |
|---|---|---|
| `SLink-RB-Red.ups` | `3d45c1ee9abd5738df46d2bdda8b57dc` | `a9a70f99008559734ba01a9a80d78d5c` |
| `SLink-RB-Blue.ups` | `50927e843568814f7ed45ec4f944bd8b` | `fa47b8ba0c10e82f2545791abd157ad3` |

Rebuild them from the clean dumps and the current Gen 1 build:

```bash
python patch/gen1/tools/build.py
python patch/tools/make_ups.py create patch/build/gen1_red.gb patch/gen1/build/slink_red.gb patch/dist/SLink-RB-Red
python patch/tools/make_ups.py create patch/build/gen1_blue.gb patch/gen1/build/slink_blue.gb patch/dist/SLink-RB-Blue
```
