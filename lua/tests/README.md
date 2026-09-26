# lua/tests — manifest

BizHawk Lua test scripts. Three families:

- **`duo/`** — the TWO-INSTANCE headless E2E harness. The active wrappers run the real
  production client (instance B mutates party OTIDs pre-hello so keys don't collide):
  `duo_gen3_main.lua` for Gen 3 (battery boot), `duo_gen1_main.lua` for the rewritten
  Gen 1 client (Game Boy, boots a committed battery save; Red as player A, Blue as B — no
  Yellow pairing), and `duo_gen2_main.lua` for Gen 2 (Game Boy, boots a committed battery
  save per title; same-title pairings share one cartridge dump). The retired `duo_main.lua`
  is archived at `archive/gen3_old_client/duo_main.lua`. Driven by `tools/e2e_duo.py`, which
  boots a throwaway server + two concurrent EmuHawk instances (per-instance `--config` copies,
  and per-instance SaveRAM dirs) and orchestrates via the debug HTTP API. This automates the old "two-instance
  E2E (USER gate)".

  `duo_gen1_main.lua` does **not** use prefix-based scenario lookup: its eighteen
  `gen1_new` scenarios (`link_new`, `ball_gate_new`, `deadzone_new`, `species_clause_new`,
  `type_clause_new`, `reconnect_new`, `trade_new`, `trade_decline_new`,
  `linked_faint_bench_new`, `linked_faint_active_new`, `explode_new`, `soft_reset_new`,
  `pc_ops_new`, `changebox_new`, `whiteout_new`, `poison_new`, `rival_swap_new`,
  `admit_randomized_new`) are `scenarios.<name>()` functions implemented directly in that
  file. `duo_gen2_main.lua` resolves a scenario as `scenario_gen2_<name>.lua`:

  | File(s) | Games |
  |---|---|
  | `scenario_gen3_*.lua` | Gen 3 battery rows (`gen3_frlg`, `gen3_lgfr`, `gen3_rr`) |
  | `scenario_gen2_{link,faint}.lua` | Gen 2 (Crystal/Gold/Silver, same-title and cross-title pairings) |

  The old `scenario_gen1_{whiteout,playthrough,deadzone,dupes,rivalswap,explode_g1}.lua`
  prefix files and the `gen1`/`gen1_yellow` duo titles they drove no longer exist — deleted
  in the same harness sweep above. The legacy Gen 2 duo chain (`duo_gb_main.lua`,
  `scenario_gb_{faint,boxsync,memorialize}.lua`, `gatelib.lua`) is likewise retired, replaced
  by the files above.

  `--game` picks the title: `gen3_rr` (default), `gen1_new` (the rewritten Gen 1 client,
  Red as A / Blue as B) or `gen2_new` (Crystal/Gold/Silver pairings).

  ```bash
  SLINK_E2E=1 pytest tests/e2e/test_duo.py -q               # Gen 3
  SLINK_E2E=1 pytest tests/e2e/test_duo_gen1_new.py -q      # Gen 1 (rewritten client, 18 scenarios)
  SLINK_E2E=1 pytest tests/e2e/test_duo_gen2_new.py -q      # Gen 2
  python tools/e2e_duo.py --game gen2_new --scenario link    # one scenario, directly
  python tools/e2e_duo.py --game gen2_new --list             # what --scenario all would run
  python tools/e2e_duo.py --game gen1_new --list             # the 18 gen1_new scenarios
  ```

  `--scenario all` runs only the scenarios whose `games` tuple covers `--game` (absent means
  every title), naming the ones it drops rather than skipping them silently; `--list` prints
  that selection without booting anything, and asking for a scenario a game cannot run fails
  immediately instead of timing out on a missing fixture.

  Gen 2 does not run `playthrough`, `deadzone` or `dupes`: those need tall grass, and
  Crystal's fixture parks indoors because New Bark Town's west exit is script-locked until
  Elm hands over a starter. The rules they cover are server-side and generation-independent,
  and Gen 1's own `gen1_new` scenarios cover the same ground (`link_new`, `deadzone_new`,
  `species_clause_new`) with real play.

- **`test_live_*` / `test_mailbox_*`** — headless gates for the RR companion patch
  (`patch/src/handlers.c`). Run on the PATCHED build from the worktree root:
  `EmuHawk.exe --lua=lua/tests/<test>.lua patch/build/slink_RR.gba`
  Each loads a savestate from `E:/Howard/Bizhawk/GBA/State/`, writes
  `patch/build/<name>_result.txt` ending `RESULT: PASS|FAIL`, and exits.
- **`test_gen*_*` / discovery scripts** — per-generation client/profile validation and
  address-discovery one-shots (interactive; load in the Lua console). The exception is the
  `*_gate.lua` files, which run HEADLESS off a committed battery save:
  Gen 1's `test_gen1_patch_gate.lua` / `test_gen1_menu_row_gate.lua` / a randomized-panel run
  via `tests/live/test_gen1_gates.py` (companion patch only), `test_gen1_inspect_gate.lua` /
  `test_gen1_scripted_gate.lua` via `tests/live/test_gen1_new_gates.py` (the rewritten
  client, all three cartridges), `test_gen1_receptionist_gate.lua` via
  `tests/live/test_gen1_trade_gates.py` (SLINK TRADE), and Gen 2's
  `gen2_inspect_gate.lua` / `gen2_frame_align.lua` / `gen2_write_windows.lua` via
  `tests/live/test_gen2_new_gates.py` / `test_gen2_frame_align.py` / `test_gen2_write_windows.py`
  (`SLINK_LIVE=1 pytest tests/live/ -q` runs all of the above).

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
| `test_live_message.lua`, `test_live_msgboxdismiss.lua` | OP_SHOW_MESSAGE (8) field box + dismissal |
| `test_live_menu.lua`, `test_live_choices.lua` | OP_SHOW_MENU (17) / OP_SHOW_CHOICES (22) |
| `test_live_choosepartymon.lua` | OP_CHOOSE_PARTY_MON (20) |
| `test_live_tradescene.lua` | OP_TRADE_SCENE (21) native trade animation |
| `test_live_setpartymon.lua` | OP_SET_PARTY_MON (19) silent trade fallback |
| `test_live_createmon.lua`, `test_live_givemon.lua` | OP_CREATE_MON (4) / OP_GIVE_MON |
| `test_live_enemyparty.lua`, `test_live_enemyparty_route.lua` | OP_SET_ENEMY_PARTY (16) rival swap |
| `test_live_forcemove.lua`, `test_live_explode_route.lua` | OP_FORCE_MOVE_SLOT (5) / explode plumbing (native path currently disabled — ROADMAP §2) |
| `test_live_playse.lua` | OP_PLAY_SE (native sound) |
| `test_live_spawnnpc.lua`, `test_live_pcnpc.lua` | OP_SPAWN/DESPAWN_PEER_NPC + the Pokémon-Center trade NPC driver |
| `test_live_peerinteract.lua` | talk-to-ghost/NPC interact counter |
| `test_live_ghost*.lua` (receiver, avatar, layer, stutter, warp, door, battle, orphan, script, show) | peer-ghost lifecycle: spawn/drive/LERP motion, avatar re-assert, depth sort, warp/door/battle suspend-resume, orphan GC |
| `input_sanity.lua` | joypad input plumbing sanity for driven tests |
| `probe_palettes.lua` | color/palette probes kept for the native_messages A/B theming work |

## Discovery provenance (findings live in ADDRESSES.md)

`test_rr_validate.lua`, `test_*_discovery.lua` (bag/item/trainer/battle_main_func),
`test_ability_diag.lua`, `test_map_names.lua` — address/behaviour discovery and audits for the RR
profile. Interactive. The discovery/audit scripts that loaded the old Gen 3 client's modules
(sound, RR, battle_facility_flag, post_eob_settle, SE/BGM audits, faint-counter and memorialize
gates) are archived in `archive/gen3_old_client/` (card C5-6).

## Per-generation client tests

`test_gen1_*`, `test_gen2_*`,
`test_gen4_*`, `test_gen5_*` — memory profiles, faint detection, server protocol per generation.
