# lua/tests — manifest

BizHawk Lua test scripts. Three families:

- **`duo/`** — the TWO-INSTANCE headless E2E harness: `duo_main.lua` (shared wrapper that runs
  the REAL production client; instance B mutates party OTIDs pre-hello so keys don't collide)
  plus `scenario_{faint,boxsync,trade,ghost,explode}.lua`. Driven by `tools/e2e_duo.py`, which boots a
  throwaway server + two concurrent EmuHawk instances (per-instance `--config` copies) and
  orchestrates via the debug HTTP API. Run: `python tools/e2e_duo.py --scenario all`
  (or `SLINK_E2E=1 pytest tests/e2e/`). This automates the old "two-instance E2E (USER gate)".

- **`test_live_*` / `test_mailbox_*`** — headless gates for the RR companion patch
  (`patch/src/handlers.c`). Run on the PATCHED build from the worktree root:
  `EmuHawk.exe --lua=lua/tests/<test>.lua patch/build/slink_RR.gba`
  Each loads a savestate from `E:/Howard/Bizhawk/GBA/State/`, writes
  `patch/build/<name>_result.txt` ending `RESULT: PASS|FAIL`, and exits.
- **`test_gen*_*` / discovery scripts** — per-generation client/profile validation and
  address-discovery one-shots (interactive; load in the Lua console).

One-off discovery probes are DELETED once their findings land in
`patch/src/ADDRESSES.md` — that file records the provenance. Don't resurrect them; write a
fresh probe per the patterns below if new discovery is needed.

## Companion-patch regression gates (run these after every `build.py`)

| Test | Gates |
|---|---|
| `test_mailbox_ping.lua` | beacon + ABI + mailbox seq/ack round-trip (opcode 1) |
| `test_mailbox_absent.lua` | clean fallback on an UNPATCHED ROM (no beacon → MB.present()=false) |
| `test_mailbox_battle.lua` | mailbox liveness inside battle |
| `test_live_boxsync.lua` | OP_DEPOSIT_MON/OP_WITHDRAW_MON (24/25) round-trip faithfulness |
| `test_live_memorialize.lua` | OP_MEMORIALIZE (26): compress + zero + swap-with-last + bounds rejects |
| `test_live_events.lua` | EvRing producers/drain: faint-counter deltas, outcome edge, overflow |
| `test_live_calctoggle.lua` | SLINK_CALC_OFF shim paths (calc on/off/flip-churn in battle) |
| `test_live_battlemsg.lua` | OP_SHOW_BATTLE_MESSAGE (23) native in-battle notification |
| `e2e_battlemsg_inject.lua` | end-to-end battle-notif injection (themed colors) |
| `test_live_message.lua`, `test_live_msgbox_route.lua`, `test_live_msgboxdismiss.lua` | OP_SHOW_MESSAGE (8) field box + routing + dismissal |
| `test_live_menu.lua`, `test_live_choices.lua` | OP_SHOW_MENU (17) / OP_SHOW_CHOICES (22) |
| `test_live_choosepartymon.lua` | OP_CHOOSE_PARTY_MON (20) |
| `test_live_tradescene.lua` | OP_TRADE_SCENE (21) native trade animation |
| `test_live_setpartymon.lua` | OP_SET_PARTY_MON (19) silent trade fallback |
| `test_live_createmon.lua`, `test_live_givemon.lua` | OP_CREATE_MON (4) / OP_GIVE_MON |
| `test_live_enemyparty.lua`, `test_live_enemyparty_route.lua` | OP_SET_ENEMY_PARTY (16) rival swap |
| `test_live_forcemove.lua`, `test_force_explosion.lua`, `test_live_explode_route.lua` | OP_FORCE_MOVE_SLOT (5) / explode plumbing (native path currently disabled — ROADMAP §2) |
| `test_live_playse.lua` | OP_PLAY_SE (native sound) |
| `test_live_spawnnpc.lua`, `test_live_pcnpc.lua`, `visual_pcnpc.lua` | OP_SPAWN/DESPAWN_PEER_NPC + the Pokémon-Center trade NPC driver |
| `test_live_peerinteract.lua` | talk-to-ghost/NPC interact counter |
| `test_live_ghost*.lua` (receiver, avatar, layer, stutter, warp, door, battle, orphan, script, show) | peer-ghost lifecycle: spawn/drive/LERP motion, avatar re-assert, depth sort, warp/door/battle suspend-resume, orphan GC |
| `test_pid_freeze_validate.lua` | SwapState borrowed-party ("Party Freeze") begin/end |
| `input_sanity.lua` | joypad input plumbing sanity for driven tests |
| `sprite_gallery.lua` | interactive graphicsId browser (used to pick PCNPC_GFX) |
| `probe_colorphase.lua`, `probe_palettes.lua`, `probe_fit.lua` | color/palette probes kept for the native_messages A/B theming work |

## Discovery provenance (findings live in ADDRESSES.md)

`test_rr_discovery.lua`, `test_rr_validate.lua`, `test_*_discovery.lua` (bag/item/trainer/sound/
battle_main_func/battle_facility_flag/post_eob_settle), `test_se_audit.lua`, `test_bgm_audit.lua`,
`test_faint_counter_gate.lua`, `test_memorialize_gate.lua`, `test_ability_diag.lua`,
`test_map_names.lua` — address/behaviour discovery and audits for the RR profile. Interactive.

## Per-generation client tests

`test_1_memory/2_force_faint/3_server.lua` (Gen 3 FRLG/E), `test_gen1_*`, `test_gen2_*`,
`test_gen4_*`, `test_gen5_*` — memory profiles, faint detection, server protocol per generation.
