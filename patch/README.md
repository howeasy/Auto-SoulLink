# SLink Companion Patch (Radical Red) — testing guide

An **optional** native code-injection layer for Radical Red. When applied, the SLink Lua
client detects it and uses native in-game features; without it, everything falls back to
the existing behaviour. **Unpatched players are unaffected.**

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
(Flips, NUPS, RomPatcher.js, …). Result md5 should be `d45485d4da2c60cf3062c7c5527270a7`.
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
| `native_battle_control` | OFF | `--native-battle-control` | Variant-3 RAM explode + deferred faint. NOT a user toggle (no manager checkbox): it selects the IMPLEMENTATION PATH under Explode Mode — CLI-only dev switch for the native controller-swap soak (which softlocked in real play; thunk addrs re-validated by `probe_movecursor_thunks.lua`) |

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
- **Peer ghost** — your partner (another real player playing their own game) appears as a real
  engine object-event (NPC) walking your overworld in real time, rendered as **their own trainer
  avatar + colours**, moving and animating **exactly as they move**. The client broadcasts its
  player's sub-pixel WORLD-PIXEL position + facing + live animNum + avatar (live sprite
  images/anims ROM ptrs + true 16-colour palette) ~20 Hz (server relays it ephemeral+coalesced);
  the partner's patch spawns a real NPC, neutralizes its callback, and drives `pos1` by LERPing
  toward that position (continuous + speed-agnostic — no tile-quantized "walk-stop" stutter),
  plays their animNum, and paints their avatar onto a dedicated OBJ palette slot (15) so the
  player's own slot 0 is never touched. Talk to the ghost (face it + A) for a dismissable message.
  RR + patch only; both players must be patched.
  - **Deferred (on-foot works now):** bike/surf/fishing avatar variants (need size-matched
    re-spawn + larger VRAM tile handling); day/night tint on the avatar palette (v1 shows the
    partner's true colours, un-tinted at night). The two-instance visual run is the final gate.
- **Talk to your partner → action menu (Trade / Say hey).** Face the partner ghost + press A to open a
  native **multichoice list** (`Trade` / `Say hey`, extensible). **Say hey** pings the partner
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

- Battle: `FORCE_FAINT`, `FORCE_MOVE_SLOT` ARE wired, but ship **disabled by default** behind
  the `--native-battle-control` server flag after a live softlock — the Lua Variant-3 RAM path
  remains the production default (see `patch/ROADMAP.md`)
- Mon: `CREATE_MON`, `GIVE_MON` (`SET_ENEMY_PARTY` rival-team-swap and `SET_PARTY_MON` trade ARE wired)
- Overworld: `ARM_PEER_INTERACT` (talk-to-ghost; `SPAWN/DESPAWN_PEER_NPC` is now wired — see above)
- Rules/UI: `PLAY_FANFARE` (`SHOW_MENU`, `PLAY_SE` ARE wired)

Removed (opcode numbers 10–12 reserved): `APPLY_DAMAGE`, `CURE_STATUS` (linked chip/status — dropped),
`SET_RULES` (nuzlocke battle-style — redundant on RR). See `ADDRESSES.md` › "Removed opcodes".

Opcode/address reference: `patch/src/ADDRESSES.md`. Build pipeline: `patch/tools/build.py`
(gcc → ld → objcopy → inject → UPS/IPS, all round-trip self-checked).
