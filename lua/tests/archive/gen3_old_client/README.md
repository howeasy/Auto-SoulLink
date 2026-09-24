# Archived Gen 3 gates (old client driver)

These gates exercise the old client's own Lua (`lua/peer_ghost_npc.lua`, or the `msgbox` routing in `lua/clients/gen3_frlge_client.lua` via `memory_gba`/`game_detect`), which P5 card C5-6 deletes. They are never run: `tests/live/test_lua_gates.py` scans only `lua/tests/`, not this folder. They are kept for reference only (card C5-4c).

- `test_live_ghostdoor.lua`: tests the old `peer_ghost_npc` receiver's avatar re-assert across a door warp. Replacement: a `lua/gen3/ghost.lua` door/warp gate, when the peer ghost returns post-RC.
- `test_live_ghostorphan.lua`: tests the old receiver's connect/reconnect for orphan localId-0xF0 object events. Replacement: a `ghost.lua` orphan gate (post-RC); the patch-side orphan check is still live in `test_live_ghostwarp.lua`.
- `test_live_ghostreceiver.lua`: tests that the old receiver (`on_ghost_pos` + `on_frame`) spawns and walks the ghost. Replacement: `ghost.lua` unit tests plus a receiver gate (post-RC).
- `test_live_ghoststutter.lua`: measures the old receiver's walk-cadence stutter. Replacement: the ghost stutter metric on `ghost.lua` (PLAN P5), when the ghost returns post-RC.
- `test_live_ghostscript.lua`: checks for invisible ghost collision after a sign dialogue, driven through the old receiver plus `OP_SHOW_MESSAGE`. Replacement: a `ghost.lua` gate with native text (both post-RC).
- `test_live_msgbox_route.lua`: tests the old client's `msgbox` routing (native box vs HUD) through `memory_gba.isInOverworld` and `game_detect`. Replacement: the new client's native-text capability branch plus a `lua/gen3/client.lua` unit, when native text returns post-RC; box behaviour stays covered by `test_live_message.lua` and `test_live_msgboxdismiss.lua`.

## Non-gate diagnostics (card C5-6-EXEC-1)

These manual BizHawk scripts `require("memory_gba")` or `dofile` `lua/mailbox.lua` / `lua/clients/gen3_frlge_client.lua`, all deleted by C5-6 (the whole old client is at tag `archive/gen3-old-client`). None was in a gate manifest; they cannot run from here.

- `test_battle_facility_flag_discovery.lua`: one-shot discovery of the RR battle-facility flag the old client gated on; the finding lives with that client in the tag.
- `test_bgm_audit.lua`: interactive BGM audition through the old `memory_gba` m4a helpers; sound ids now live in the new client's profile.
- `test_se_audit.lua`: interactive SE audition through `memory_gba`; same as above.
- `test_sound_discovery.lua`: scanned for gSongTable/SE headers to paste into `memory_gba` profiles; superseded by the generated `write_checkpoint.json` sound block.
- `test_rr_discovery.lua`: one-shot RR address discovery whose output was pasted into `memory_gba` profiles; the RR facts are now in `data/games/gen3_rr/profile.json`.
- `test_post_eob_settle_discovery.lua`: measured the old client's post-end-of-battle settle window; one-shot.
- `test_faint_counter_gate.lua`: manual regression for the old client's faint counter; covered by `test_live_events.lua`.
- `test_force_explosion.lua`: single-instance explode harness over `memory_gba`; covered by `test_live_forcemove.lua` / `test_live_explode_route.lua`.
- `test_pid_freeze_validate.lua`: old-client "Party Freeze" validation over `memory_gba`; one-shot.
- `test_sound_playback.lua`: plays SEs through `memory_gba.playSE`; covered by `test_live_playse.lua`.
- `test_memorialize_gate.lua`: ran alongside the old client to time memorialize; covered by `test_live_memorialize.lua`.
- `probe_colorphase.lua`: native-message colour-phase probe over the old `mailbox.lua`; port to `lua/tests/gen3_gatelib.lua` if native text returns post-RC.
- `probe_fit.lua`: native-message text-fit probe over the old `mailbox.lua`; port to `lua/tests/gen3_gatelib.lua` if native text returns post-RC.
- `probe_infostyle.lua`: native-message info-box style probe over the old `mailbox.lua`; port to `lua/tests/gen3_gatelib.lua` if native text returns post-RC.
- `probe_uibudget.lua`: native-message UI frame-budget probe over the old `mailbox.lua`; port to `lua/tests/gen3_gatelib.lua` if native text returns post-RC.
- `probe_uibudget3.lua`: native-message UI frame-budget (third pass) probe over the old `mailbox.lua`; port to `lua/tests/gen3_gatelib.lua` if native text returns post-RC.
- `probe_winmap.lua`: native-message window-map probe over the old `mailbox.lua`; port to `lua/tests/gen3_gatelib.lua` if native text returns post-RC.
- `sprite_gallery.lua`: graphicsId browser over `mailbox.lua` (picked PCNPC_GFX); port to `gen3_gatelib.lua` if needed again.
- `visual_pcnpc.lua`: visual check of the PC trade NPC over `mailbox.lua`; covered by `test_live_pcnpc.lua`.
- `_ref_screens.lua`: reference-screenshot capture over `mailbox.lua`; one-shot.
- `e2e_battlemsg_inject.lua`: dofiled the old production client to inject battle notifications; superseded by `test_live_battlemsg.lua`.
- `probe_gen3_frameend_pc.lua`: frozen P1 probe (G1 signed) over `memory_gba`/`games.gen3_frlge`; historical evidence only. Its unit test was deleted with it.

Deleted outright (in the tag): `test_1_memory.lua`, `test_2_force_faint.lua`, `test_3_server.lua` (the old client's manual smoke scripts, superseded by the `test_live_*` gates), and the unit tests `tests/unit/test_gen3_lua_vs_codec.py`, `tests/unit/test_gen3_old_client_outcomes.py` (both read `memory_gba.lua` source).
