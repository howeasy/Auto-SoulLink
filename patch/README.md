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
(Flips, NUPS, RomPatcher.js, …). Result md5 should be `67493210fc378a9349b93cc890e41897`.
(`SLink-RR.ips` is also provided.) Then load the patched ROM in BizHawk as usual.

## Verify the patch loaded

Start the patched ROM; within a second or two the patch writes a `'SLNK'` beacon to EWRAM
`0x0203F800`. The SLink client logs `companion patch: present` when it detects it (and
falls back silently when it doesn't). A dev smoke check: load `lua/tests/test_mailbox_ping.lua`
in EmuHawk → it reports `RESULT: PASS`.

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
- **Talk to your partner → action menu (Trade / Wave).** Face the partner ghost + press A to open a
  native **multichoice list** (`Trade` / `Wave`, extensible). **Wave** notifies the partner (with
  your badge count — the in-game nuzlocke status helper). **Trade** opens the native **"Choose a
  POKéMON" party menu**; only a *linked* mon is accepted (anything else re-prompts). Your **partner**
  then gets a single confirm (showing your badge count); on accept, the **real in-game trade animation
  plays on both sides** (`DoInGameTradeScene` against the partner's matching half staged in
  `gEnemyParty[0]`) — including **trade-evolution** (Kadabra→Alakazam, etc.) — and the link reconciles
  to the post-trade species. The two mons are always the **matching halves of one link** (the server
  auto-selects the partner's counterpart; you can never trade for an unlinked or different-link mon).
  (Falls back to a faithful silent swap if the native scene is unavailable.)
- **Native sound.** Server `play_sound` cues (link formed, KO, shiny, …) play through the patch
  (`PlaySE`) when present, instead of the Lua m4a RAM-poke — fallback keeps unpatched ROMs working.

## Validated but NOT yet wired into the server-driven client

These opcodes are built and live-validated (see `lua/tests/test_live_*.lua`) but the
production client doesn't invoke them yet — each needs its own server/client integration
(the message box above is the template):

- Battle: `FORCE_FAINT`, `FORCE_MOVE_SLOT`, `APPLY_DAMAGE` (linked HP/chip), `CURE_STATUS`
- Mon: `CREATE_MON`, `GIVE_MON` (`SET_ENEMY_PARTY` rival-team-swap and `SET_PARTY_MON` trade ARE wired)
- Overworld: `ARM_PEER_INTERACT` (talk-to-ghost; `SPAWN/DESPAWN_PEER_NPC` is now wired — see above)
- Rules/UI: `SET_RULES` (nuzlocke battle-style), `PLAY_FANFARE` (`SHOW_MENU`, `PLAY_SE` ARE wired)

Opcode/address reference: `patch/src/ADDRESSES.md`. Build pipeline: `patch/tools/build.py`
(gcc → ld → objcopy → inject → UPS/IPS, all round-trip self-checked).
