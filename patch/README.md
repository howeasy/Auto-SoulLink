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
(Flips, NUPS, RomPatcher.js, …). Result md5 should be `ee307b6dea03f49d025d9a272b36579c`.
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
  unchanged). This is the one feature you'll see during normal play.

## Validated but NOT yet wired into the server-driven client

These opcodes are built and live-validated (see `lua/tests/test_live_*.lua`) but the
production client doesn't invoke them yet — each needs its own server/client integration
(the message box above is the template):

- Battle: `FORCE_FAINT`, `FORCE_MOVE_SLOT`, `APPLY_DAMAGE` (linked HP/chip), `CURE_STATUS`
- Mon: `CREATE_MON`, `GIVE_MON`, `SET_ENEMY_PARTY` (rival-team-swap with correct stats)
- Overworld: `SPAWN/DESPAWN_PEER_NPC` (+ `lua/peer_ghost_npc.lua` receiver), `ARM_PEER_INTERACT`
- Rules/UI: `SET_RULES` (nuzlocke battle-style), `PLAY_FANFARE`

Opcode/address reference: `patch/src/ADDRESSES.md`. Build pipeline: `patch/tools/build.py`
(gcc → ld → objcopy → inject → UPS/IPS, all round-trip self-checked).
