# P5: `replace_rival_team` executor (Gen 1 R/B/Y)

Status: design only, for the handoff item 4 row `replace_rival_team`.

## 1. Detection: an observation-loop read, not an engine signal

`InitBattleEnemyParameters` writes `wCurOpponent` at engagement
(`.cache/pret/pokered/home/trainers.asm:233-235`), before the intro text; a trainer is class +
`OPP_ID_OFFSET` 200 (`engine/battle/read_trainer_party.asm:18-19`), rivals are 225/242/243
(`server/adapters/gen1_rby.py:360-365`), and the byte is
zeroed when the battle ends (`lua/clients/gen1_rby_client.lua:1597`). Address R/B `0xD059`
(`lua/games/gen1_rby.lua:193`), Yellow `0xD058` (`:371`). Row `trainer_battle_start {trainer_id}`
once per non-zero run of `wCurOpponent > 200` held three consecutive ticks (`TRAINER_STABLE_GATE`,
`gen1_rby_client.lua:496-499,1959-1972`), published on that tick next to signals
(`lua/gen1_observation_loop.lua:53-54`), not on the heartbeat. Server: `trainer_battle_start_event`
(`server/gen1_semantic_events.py:70-71`) reaches `_handle_trainer_battle_start`
(`server/state.py:2957-2990`), which queues `{cmd, trainer_id, n, blobs_hex, source}`
(`:2944-2949`) from `partner_blobs`, already filled from inventories with 66-byte `mon.raw`
(`server/gen1_rule_inventory.py:16-35`; `server/party_observation_cache.py:39-40`). Queued at
engagement, only the permit round trip sits inside the write window.

## 2. When the write is safe

Earliest safe instruction: `DoBattleTransitionAndInitBattleVariables` entered from
`InitBattleCommon` (`engine/battle/core.asm:6680`; Yellow `engine/battle/init_battle.asm:39`;
`.sym` R/B `0F:6C32`, Y `0F:6DB8`). `ReadTrainer` has just filled the party (`core.asm:6679`;
`read_trainer_party.asm:11-15,53-63`) and nothing reads it until the `StartBattle` scan
(`core.asm:139-150`) and `EnemySendOutFirstMon` via `LoadEnemyMonFromParty` (`:154`,
`:1670-1722`), the first write of `wEnemyMonPartyPos` (`:1720`). A per-instruction pin would
need a 64-frame hold-stepped window (`lua/instruction_executor.lua:9-12`) across a player-paced
intro.

**Recommendation: the held permit at a frame boundary, with a battle-init predicate.**
`InitBattleCommon` sets `wEnemyMonPartyPos = $FF` and `wIsInBattle = 2` after `ReadTrainer`
(`core.asm:6689-6692`; Yellow `init_battle.asm:48-51`), `$FF` survives until `:1720`, and
`StartBattle` scans and sends out with no `DelayFrame` between (`:139-156`). So every VBlank
boundary with `wIsInBattle == 2 and wEnemyMonPartyPos == $FF` lies inside the window: the
silhouette slide and `Delay3` of `_InitBattleCommon` (`:6735-6763`), measured by the probe and
used by the legacy client with a three-frame gate (`README.md:103-106`).

Profile `battle_init`, new block per title in `data/games/gen1_rby/write_checkpoint.json`:
`wIsInBattle == 2` (`0xD057`/`0xD056`), `wEnemyMonPartyPos == 0xFF` (`0xCFE8`/`0xCFE7`),
`wEnemyPartyCount` in 1..6 (`0xD89C`/`0xD89B`), `wCurOpponent == body.trainer_id`,
`wLinkState == 0` (`0xD12B`/`0xD12A`), `wBattleType == 0` (`0xD05A`/`0xD059`); CPU
`pc == irq_vector`, `sp` in the stack window and `resume == delay_frame + 5` (halted in
`DelayFrame`, the first stack word of `server/gen1_held_faint.py:38-39`); the caller word is not
pinned (the intro has many); ROM anchors reused (`:22-28`; `lua/gen1_write_safety.lua:38-44`);
addresses from `data/pret_syms.json`.

## 3. Footprint (from `M.writeEnemyParty`, `lua/memory_gb.lua:795-807`)

Per blob `i` of `n` (66 bytes = 44 struct + 11 OT + 11 nick, `:874-879`): struct at
`wEnemyMons + 44(i-1)`, OT at `wEnemyMonOT + 11(i-1)`, nick at `wEnemyMonNicks + 11(i-1)`,
species at `wEnemyPartySpecies + (i-1)`; then `wEnemyPartySpecies + n = $FF` and
`wEnemyPartyCount = n`: `67n + 2` bytes, at most 404.

| Symbol | R/B | Yellow | Source |
| --- | --- | --- | --- |
| `wEnemyPartyCount` | `D89C` | `D89B` | `gen1_rby.lua:67,275` |
| `wEnemyPartySpecies` | `D89D` | `D89C` | `:133,332` |
| `wEnemyMons` | `D8A4` | `D8A3` | `:68,276` |
| `wEnemyMonOT` | `D9AC` | `D9AB` | `:196,372` |
| `wEnemyMonNicks` | `D9EE` | `D9ED` | `:197,373` |

Server refusal to add: at least one blob with HP above zero, since the `StartBattle` scan has
no exit (`core.asm:139-150`). Blobs pass `PartyCodec.validate_party` (`server/gen1_party_codec.py:200`)
before queueing, as `writeEnemyParty` does (`:771`).

## 4. Receipt

`gen1-rival-team-receipt-v1 {trainer_id, before: {count, species_list}, after: {count,
species_list, image_hex}}`: `image_hex` is the readback of exactly the `67n + 2` written bytes in
write order; the server rebuilds it from `body.blobs_hex` and compares, `species_list` must be
`[blob[0] ...] + [255]`. `Gen1ReceiptPolicy` accepts the command and returns `[]`
(`server/gen1_command_receipts.py:112-125`); the engine effect is informational
(`_handle_rival_team_replaced`, `state.py:2992-3020`).

## 5. `lua/gen1_held_rival_team.lua`

Sub-executor in the `gen1_held_storage` shape (`lua/gen1_held_storage.lua:1-40`), composed by
`selected()` (`lua/gen1_held_faint.lua:65-70`); permit, evidence and phases stay there.

```lua
local Codec=require("gen1_party_codec")
local M={INTENT="rby-rival-team-intent-v1",RECEIPT="gen1-rival-team-receipt-v1"}
local BAD="invalid complete rival payload; nothing written"
local function blobs_of(mem,body) -- gen1_rby_client.lua:340-355 moved verbatim: 1..6 dense entries,
    -- each 132 hex chars decoding to 66 bytes via mem.hexToBytes, else nil,BAD and nothing written
    ...
end
function M.new(o) -- o.memory, o.variant; o.safe is the battle_init predicate for this body
    local mem=o.memory
    local function image(n) -- count, species n+1, the three arrays for n mons as one hex string
        return {count=mem.read_u8(mem.ENEMY_COUNT_ADDR),species_list=mem.readEnemySpeciesList(n),
            image_hex=mem.readEnemyImageHex(n)}
    end
    local function expected(body) return Codec.enemyImageHex(assert(blobs_of(mem,body))) end
    return {
        prepare=function(body)
            local blobs,why=blobs_of(mem,body);if not blobs then return nil,why end
            local party,err=Codec.validateParty(blobs,o.variant);if not party then return nil,err end
            return {schema=M.INTENT,trainer_id=body.trainer_id,n=#blobs,before=image(#blobs)}
        end,
        classify=function(body,intent)
            local now=image(intent.n)
            if now.image_hex==expected(body) then return "after",now end
            if now.image_hex==intent.before.image_hex then return "before",now end
            return "diverged","enemy party changed before the swap"
        end,
        apply=function(body,intent) assert(mem.writeEnemyParty(assert(blobs_of(mem,body)))) end,
        receipt=function(body,intent,observed)
            if observed.image_hex~=expected(body) then return nil,"rival readback differs" end
            return {schema=M.RECEIPT,trainer_id=body.trainer_id,before=intent.before,after=observed}
        end}
end
return M
```

## 6. What Codex must edit

* `lua/gen1_held_faint.lua`: `handles :7-11`; `safe :38-40` becomes `safe(body)`, the
  `battle_init` predicate for this command (callers `:41-44,94,104,128,135,167`); `selected
  :65-70`; evidence schema `rby-held-rival-evidence-v1`, `current = image` (`:137-142`).
* `lua/gen1_write_safety.lua`, `lua/gen1_write_checkpoint.lua`: a `kind` argument (`overworld`,
  `battle_init`); `data/games/gen1_rby/write_checkpoint.json` blocks.
* `lua/memory_gb.lua`: `readEnemySpeciesList`, `readEnemyImageHex` (reads only).
* New `server/gen1_rival_runtime.py`: `verify_operation` = `verify_owned_host`
  (`server/gen1_held_faint.py:78-102`) + `verify_battle_init_checkpoint` + intent/receipt checks,
  returning a `VerifiedHeldWrite` with phase `replace_rival_team`; dispatched from `verify :43-56`.
* `server/gen1_command_receipts.py:119-120`; `server/state.py:2941` HP-above-zero refusal.
* `lua/gen1_observation_loop.lua:49-54` and the observation consumer: the trainer row.

## 7. Tests to add

* Server: `verify_battle_init_checkpoint` accept plus one refusal per byte (`PartyPos` not `$FF`,
  count 0, wrong trainer, link state 4, wild flag); tampered species byte in the receipt; no-HP
  refusal; translator row to queued command with inventory-sourced blobs.
* Lua (lupa): the sub-executor on the simulated address space of
  `tests/unit/test_gen1_rival_swap_explode.py`; composition as `tests/unit/test_gen1_held_faint_client.py`.
* Live: a rival gate from the trainer fixtures (`tests/live/test_gen1_battle_force.py:36`), first
  enemy sent out is blob 1; duo `rivalswap` through the production loop.
