# Gen 3 — post-RC TODO

Work the owner moved out of the Gen 3 RC. None of it is an RC requirement or a gate item. Each
entry returns as its own card on the new client after the RC ships.

## Native text (RR companion)

Owner ruling 2026-09-23. Notifications drawn in the ROM's own text boxes instead of the Lua HUD:
- `OP_SHOW_MESSAGE` (8): the overworld field message box, text pre-written through `MB.write_message` (`archive/gen3-old-client:lua/mailbox.lua:91`).
- `OP_SHOW_BATTLE_MESSAGE` (23): themed text in the battle move-info window (`archive/gen3-old-client:lua/mailbox.lua:204`).

In the old client this path is `try_native_box` and `native_messages` (`archive/gen3-old-client:lua/clients/gen3_frlge_client.lua:435-476, 550, 719-1014`; the old client was deleted in `addc9225`). The server default is already messages OFF (Lua HUD).

- **Disabled, code kept (owner 2026-09-23):** `server/state.py` forces `native_messages` False in `__init__` and `load()`. The CLI flag, saved rule and hello payload are accepted and ignored. The Manager greys the option out for every game (`server/manager.py`). To re-enable, delete those two overrides and restore the `gen3_frlge_rr` availability entry. Test: `tests/unit/test_manager_option_labels.py::test_native_messages_is_disabled_for_every_game`.
- **RC behaviour:** every Gen 3 notification and prompt goes through `lua/hud.lua`, as on FRLG vanilla. `native.lua` (P5) ports the mailbox ABI, trade, info panel, explode and rival swap. It does not port the message opcodes.
- **Post-RC card:**
  - Port the message opcodes into `native.lua` behind the same capability branch.
  - Charset: the native box uses the FR charset, not `hud.sanitize`.
  - Keep the Lua HUD as the fallback when the box can't open (script running, not overworld).
  - Confirm the shown/refused result byte (old client `:550`).
  - Add a GAME oracle that reads the text back from the box.

## Peer ghost (RR)

Owner ruling 2026-09-22 (PLAN §0/§10). No `ghost.lua` and no `ghost` duo scenario in the RC, and N-2 is out; the RR duo set is eight. The ROM opcodes are still in `patch/src/handlers.c`; `lua/gen3/client.lua`'s `ghost_pos` handler is a no-op.
- **Known gap while deferred:** the Manager still offers Overworld Presence for RR (`server/manager.py`). Turning it on disables the Pokémon Center trade NPC (`lua/gen3/native.lua` `config`: `npc_enabled = overworld_presence ~= true and pc_trade_npc ~= false`), so there is no trade entry point. Fix: mark the toggle unavailable for Gen 3 until the ghost returns (a `server/**` change, so batch it with Gen 2).

Design notes are in memory: `project_peer_ghost_feature`, `reference_peer_ghost_clone_techniques`.

## Archipelago FRLG

Owner ruling 2026-09-23 (PLAN §0/§10). `firered_ap` stays unadmitted. The old client's " AP" ROM name-suffix check (8e125fe/897fefc3) has never been checked against a real AP-patched dump. That check comes back together with the AP pack, kind and gates.
