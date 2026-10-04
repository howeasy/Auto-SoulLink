# Plan citations vs master after the ea9c8a07 merge (2026-10-01)

Read-only Sonnet review (card gen4-REV-merge-drift). It checked PLAN.md rev 5, plus wire_contract.md, checkpoint.md and prior_art.md, against HEAD c6698595. The docs were written against master 1d02702f.

## Verdict

The planned reuse of `hook_registry.lua` (still constructor-only, `:126-135`), `write_permit.lua` (API unchanged) and `lua/core/{session,deferred,identity}.lua` is still possible. About 40 line citations have **MOVED**, by +10 to +280 lines. Nothing was deleted except `gen_gen4_area_map.py:1367`, which went in this branch's own rewrite. Cards must locate code by symbol, not by the cited line numbers.

## Drifts that change Gen 4 work

1. **The hello field set grew.**
   - Gen 3 now sends `rom_type, foundation, artifact_kind, rom_sha1, party, pc_boxes, pc_boxes_generation, area_id, loc_name, has_pokeballs, in_battle, badges, ball_count`.
   - It also sends conditional fields, including `ot_id`, `trainer_name`, `player_gender`, `party_hidden` and the trade members. The session injects `writes_enabled` (`session.lua:349`).
   - Gen 4 drops the trade members, because `supports_trade_recovery()` is False.
   - For HG/SS, `getromhash()` is MD5, so `rom_sha1` must not carry that value as if it were a SHA1.
   - Omit `foundation` until the G3a rows land.
2. **KEY-SCOPE-5 changes to `key_change` (D11 npc_trade).**
   - The driver must set `pending.msg` after `Identity:begin_alias`, as Gen 3 does at `client.lua:569-573`.
   - Retryable refusals need the driver to provide `box_generation()` and `rescan_boxes()`, or the alias stays pending forever (`session.lua:303-309`).
   - The Gen 4 adapter must keep `reports_box_census()` False, or it must ship `pc_boxes_generation`.
   - Ruling 35 (`state.py:3944-3955`): an `npc_trade` that violates a clause retires the pair and force-faints the received mon. D11 does not say this yet.
3. **There is no shared reducer.** PLAN:154's "shared reducer if available" does not exist. Gen 4 needs its own signal-to-event reducer card.
4. **`lua/gen3/run.lua` is not a copy-and-strip target.** Besides the nonce, it carries the baton/session-counter block (~`:80-259`) and the GBA trade-journal adapter (`:262-385`). Only the bootstrap tail (`:386-445`) is generic.
5. **Admission follows `Entry.admit_routed`** (`gen3/entry.lua:281`), which folds in the launcher's ROUTED policy. PLAN:149's plain `admit{}` would let a `dofile`'d run.lua bypass the launcher gate.
6. **The shared test needs a Gen 4 row.** `tests/unit/protocol_schema.py:101` `HELLO_DECLARES` needs one; it is not in the plan's file list.
7. **Existing mechanisms the plan does not use:**
   - `_REFUSED_ROM_TYPES` + `_route` (`__init__.py:204-218`) refuse a rom_type while keeping its row. This is the alternative to deleting the `platinum` rows (PLAN:191).
   - Adapter-declared `per_player_key` / `per_player_bound_key` (`server.py:915-945`) give HG and SS their own per-title data.
8. **The driver's mon record** needs snake-case `max_hp` and `level`, because `deferred.lua:64` reads `default_stats`. WIRE:85 wrongly attributes nickname_bytes/moves to `deferred.lua:64`; they are identity evidence (`identity.lua:34`).
9. **Gen 4 is the first client to compose `lua/core` with registry+permit.** Gen 3 uses core with its own signals/writes. Gen 1/2 use registry+permit without core. `write_permit` also requires `mapped` and `provenance` domains, which the plan does not mention.

## Selected moved citations

| Citation (doc) | Now |
|---|---|
| session `eligible()` `:109-110` | `session.lua:121-123` |
| session flush `:168-189` | `session.lua:173-204` |
| command dispatch `:265-311` | `session.lua:270-330` (new `key_change_rejected` branch `:298-309`) |
| `_ROM_TYPE_TO_FOUNDATION :165-178` | `server/adapters/__init__.py:280-296` |
| `register_adapter("gen4_hgsspt")` `:215-217` | `__init__.py:339-341` |
| refusal order `server.py:1597-1640` | route `:1664-1676`, `_mixed_games_error` `:747-815`, `_decide_admission` `:818-880` |
| WRONG SAVE `state.py:1681-1700` | `state.py:1961-2012` |
| accepted hello `state.py:1885-1958` | `state.py:2229-2262` |
| `_party_snapshot` `server.py:1969-1989` | `server.py:2035-2058` |
| `slink.lua:198` legacy client row | `slink.lua:189` |
| `make_release.py :52/:64/:337` | `:55/:67/:373` |
| `test_slink_route.py:203-207` | `:216-222` |
| `capabilities.json` Gen 4 rows | heartgold `:564`, hgss `:601`, platinum `:696`, renegade_platinum `:986`, soulsilver `:1060` |
| `docs/gen3_requirements.md` X `:141-148` | `:181-188` |
| e2e_duo `FAMILY_EVIDENCE` / `GAMES` | `:2783` / `:2972` (`OPT_IN_GAMES :685`) |

Files untouched since the plan: `hook_registry.lua`, `write_permit.lua`, `gb_hook_binding.lua`, `hud.lua`, `token_scanner.lua`, `admission.lua`, `memory_nds.lua`, `games/gen4_hgsspt.lua`, `test_gen4_adapter.py`.

**Coordinator disposition:** items 2–5 and 8 are inputs to the G2 client cards, and each card brief must cite them. Item 2's ruling-35 behaviour goes to the owner with the D11 refresh at G2. No plan edit now, because the PLAN hash is bound in `tests/gen4_requirements.json`; these findings are recorded here instead.
