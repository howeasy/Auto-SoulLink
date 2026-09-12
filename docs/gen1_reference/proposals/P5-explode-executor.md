# P5: `force_explode` executor (Gen 1 R/B/Y)

Status: design only. Pairs with P7 (`server/gen1_faint_runtime.py:126-127`) and handoff item 5.

## 1. The question: writing move slots inside a battle

Explode writes the active battler in battle: `wBattleMonMoves`/`wBattleMonPP` and
`wPlayerSelectedMove` (`lua/memory_gb.lua:836-868`). The held overworld checkpoint refuses that:
`verify_checkpoint` fixes `BATTLE_FLAG_ADDR` to 0 (`server/gen1_held_faint.py:29-37`), `verify`
demands `intent.before.battle_flag == 0` (`:71`), `lua/gen1_write_safety.lua:45-48` likewise. A
held profile at a battle-menu PC is not possible: the platform hold stops at the VBlank vector
(`verify_checkpoint :19`, `pc == irq_vector`), never at an instruction, and the menu re-derives
`wPlayerSelectedMove` from `wBattleMonMoves[wCurrentMenuItem]` on every confirm
(`.cache/pret/pokered/engine/battle/core.asm:2660-2668`).

**Recommendation: the existing instruction authority, one new binding name, no new pins.**
`instruction_executor.lua` hooks the two sites the coercion needs (`lua/instruction_executor.lua:90-93`),
writes exactly the decided footprint inside one released frame (`:56-62`), the server verifies it
byte by byte (`server/instruction_authority.py:162-179`), and the hook frame convention is
measured on all three titles (`server/battle_force_authority.py:51-55`):

* `loop_head` = `MainInBattleLoop+0` (R/B `0F:4233`, Y `0F:4249`, `battle_force_authority.py:59,74`)
  runs before `DisplayBattleMenu` and `MoveSelectionMenu` (`core.asm:280-333`). Moves written
  here are what the menu offers this turn.
* `player_action` = `ExecutePlayerMove+0` (R/B `0F:565E`, Y `0F:57D0`, `:60,75`) reads
  `wPlayerSelectedMove` (`core.asm:3073-3078`) and `GetCurrentMove` loads that id with no
  membership check (`:3097`); `DecrementPP` indexes PP by `wPlayerMoveListIndex` only
  (`engine/battle/decrement_pp.asm:36-43`).

## 2. Addresses and footprint

| Symbol | R/B | Yellow | Source |
| --- | --- | --- | --- |
| `wBattleMonMoves` | `D01C` | `D01B` | `lua/games/gen1_rby.lua:205,378`; `data/pret_syms.json` |
| `wBattleMonPP` | `D02D` | `D02C` | `:206,379` |
| `wPlayerSelectedMove` | `CCDC` | `CCDC` | `:201,375` |
| `wPlayerMoveListIndex` | `CC2E` | `CC2E` | `:202,376` (read only, never written) |
| `wPlayerMonNumber` | `CC2F` | `CC2F` | `:204,377`; `data/games/gen1_rby/engine_signals.json:20` |

Writes the server verifies, by site, active linked mon only:

* `loop_head`: `wBattleMonMoves[0..3] = 0x99` (153, `memory_gb.lua:826`) and
  `wBattleMonPP[0..3] = 0x05`: 8 bytes. All four slots, since the confirm re-derives the move
  from the chosen slot (`core.asm:2660-2668`; `tests/unit/test_gen1_withdraw_and_explode.py`);
  PP 5 so the menu neither refuses the slot nor forces Struggle (`:2640-2646`). No
  `wPlayerSelectedMove` (the menu overwrites it), no party mirror (legacy `:858-864`): a
  switch-out makes the mon benched and the next window applies the benched write.
* `player_action`: `wPlayerSelectedMove = 0x99`: 1 byte, coerces the turn already chosen;
  refused when `action_result != 0` (item, switch or run took the turn, `core.asm:3087-3089`
  skips the move).
* Benched, either site: `benched_writes` unchanged (party HP `0000`, status `00`,
  `battle_force_authority.py:122-125`), the legacy fallback (`faint_party_key`,
  `lua/clients/gen1_rby_client.lua:324-333`) as evidence.

The self-KO is the original engine: `ExplodeEffect` zeroes the user HP and status even on a miss
(`engine/battle/effects.asm:175-189`; `core.asm:3223`); the next `MainInBattleLoop` reaches
`RemoveFaintedPlayerMon`, so the ordinary `battle_faint` signal fires for that key, and `settle`
skips it because the link is already DEAD (`gen1_faint_runtime.py:133-134`;
`server/state.py:1717-1720`).

**Not terminal.** Sleep, freeze, paralysis, confusion (`CheckPlayerStatusConditions`,
`core.asm:3092`) or a RUN/ITEM choice can stop the move that turn, so `explode_armed` records
enforcement without stopping issuance: the server re-issues while the death is `pending_faint`
and no faint signal names the key; a re-arm is idempotent (before equals after). Only
`benched` is terminal, as in item 5.

## 3. Decide, Lua

```lua
-- lua/battle_force_authority.lua; snapshot() gains
--   moves_hex=Executor.hex(a.wBattleMonMoves,4), pp_hex=Executor.hex(a.wBattleMonPP,4)
function M.decide(state,member,site,authority)
    local explode=authority.binding=="rby-battle-force-explode"
    -- refusals :22-27, benched branch :29-33, identity/HP checks :34-39 unchanged
    if explode and site=="player_action" and state.action_result~=0 then return refuse("turn already taken") end
    return {writes=authority.sites[site].writes,outcome=explode and "explode_armed" or "fainted"}
end
function M.new(options) -- name selects the binding the server issued
    return Executor.new({owner_id=options.owner_id,held=options.held,
        binding={name=options.name or M.NAME,snapshot=M.snapshot,decide=M.decide}})
end
```

## 4. Decide, server mirror

```python
# server/battle_force_authority.py
EXPLODE = "rby-battle-force-explode"
BINDINGS = {"force_faint": BINDING, "force_explode": EXPLODE}

def explode_writes(variant, site):
    a = ANCHORS[variant]["addresses"]  # plus wBattleMonMoves, wBattleMonPP
    if site == "player_action":
        return [{"address": a["wPlayerSelectedMove"], "value": 0x99}]
    return ([{"address": a["wBattleMonMoves"] + i, "value": 0x99} for i in range(4)]
            + [{"address": a["wBattleMonPP"] + i, "value": 5} for i in range(4)])

def decide(state, member, variant, site, binding=BINDING):
    ...  # :133-151 unchanged
    if binding == EXPLODE and site == "player_action" and state["action_result"] != 0:
        return refuse("turn already taken")
    explode = binding == EXPLODE
    return {"writes": explode_writes(variant, site) if explode else active_writes(variant, site),
            "refusal": None, "outcome": "explode_armed" if explode else "fainted"}
```
`sites(variant, binding)` fills `site["writes"]` the same way; `prepare` maps `body["cmd"]`
through `BINDINGS` (`:160`); `STATE_FIELDS` gains `moves_hex`, `pp_hex` (8 hex chars);
`verify_evidence` adds those 8 bytes to the before-map (`:205-209`).

## 5. Fallback and closure

Benched or out of battle, `force_explode` is `force_faint`: the benched write above, or the
overworld held executor for the same command. Closure never changes: `gen1_held_faint` takes
`force_explode` like `force_faint`, ACKs the proven no-op when HP is already `0000`
(`lua/gen1_force_faint_executor.lua:43-44`; `server/gen1_command_receipts.py:75-80`) or writes
HP when the battle ended by RUN or capture. The outbox command stays the one the death tracks.

## 6. What Codex must edit

* `server/battle_force_authority.py`: `BINDINGS`, `explode_writes`, `sites`, `decide`,
  `prepare :160`, `STATE_FIELDS :86-91`, `verify_evidence :205-209`, `ANCHORS` addresses.
* `lua/battle_force_authority.lua`: `snapshot :10-19`, `decide :20-41`, `new :42-44`.
* `lua/gen1_held_faint.lua`: `handles :7-11` and `selected :66` accept `force_explode`.
* `server/gen1_held_faint.py:57`, `server/gen1_command_receipts.py:60-61,119-120`: same receipt
  for `force_explode`.
* Writer battle branch (item 5): binding by `body.cmd`; `explode_armed` re-issuable.
* `server/gen1_faint_runtime.py:126-127`: delete (P7).

## 7. Tests to add

* `tests/unit/test_battle_force_authority.py`: decide parity Lua/Python at both sites, refusal on
  `action_result`, benched fall-through, footprint mismatch on a 9th byte.
* `tests/unit/test_gen1_held_faint.py`: `force_explode` overworld no-op receipt and real write.
* `tests/unit/test_gen1_faint_runtime.py`: re-issue after `explode_armed`, stop after the faint
  signal; P7 case.
* Live: `tests/live/test_gen1_battle_force.py` explode variant on the fixtures; duo `explode`
  through the production loop (item 4 gate).
