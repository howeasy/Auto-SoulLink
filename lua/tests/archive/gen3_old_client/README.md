# Archived Gen 3 gates (old client driver)

These gates exercise the old client's own Lua (`lua/peer_ghost_npc.lua`, or the `msgbox` routing in `lua/clients/gen3_frlge_client.lua` via `memory_gba`/`game_detect`), which P5 card C5-6 deletes. They are never run: `tests/live/test_lua_gates.py` scans only `lua/tests/`, not this folder. They are kept for reference only (card C5-4c).

- `test_live_ghostdoor.lua`: tests the old `peer_ghost_npc` receiver's avatar re-assert across a door warp. Replacement: a `lua/gen3/ghost.lua` door/warp gate, when the peer ghost returns post-RC.
- `test_live_ghostorphan.lua`: tests the old receiver's connect/reconnect for orphan localId-0xF0 object events. Replacement: a `ghost.lua` orphan gate (post-RC); the patch-side orphan check is still live in `test_live_ghostwarp.lua`.
- `test_live_ghostreceiver.lua`: tests that the old receiver (`on_ghost_pos` + `on_frame`) spawns and walks the ghost. Replacement: `ghost.lua` unit tests plus a receiver gate (post-RC).
- `test_live_ghoststutter.lua`: measures the old receiver's walk-cadence stutter. Replacement: the ghost stutter metric on `ghost.lua` (PLAN P5), when the ghost returns post-RC.
- `test_live_ghostscript.lua`: checks for invisible ghost collision after a sign dialogue, driven through the old receiver plus `OP_SHOW_MESSAGE`. Replacement: a `ghost.lua` gate with native text (both post-RC).
- `test_live_msgbox_route.lua`: tests the old client's `msgbox` routing (native box vs HUD) through `memory_gba.isInOverworld` and `game_detect`. Replacement: the new client's native-text capability branch plus a `lua/gen3/client.lua` unit, when native text returns post-RC; box behaviour stays covered by `test_live_message.lua` and `test_live_msgboxdismiss.lua`.
