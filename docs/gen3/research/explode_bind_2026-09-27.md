# EXPLODE-BIND — FR, LG and Emerald

SOURCE / MODEL implementation on `codex/gen3-explode-bind`, based on integration
`b828c656171e565816597456a7c75bc8f7dddee9`. No emulator was launched for this card.
The coordinator owns the three live rows below. Unit success is not a physical receipt.

## Source bindings

The profile generator reads each title's committed pret symbols. FR/LG use
pokefirered `c75f352304d529f6ba92d4f74b9cf8b5c3810788`; Emerald uses pokeemerald
`c65e93f20a5275ab03b07d6f6411096a82a60ffd`.

| Fact | FR / LG | Emerald |
| --- | --- | --- |
| `gChosenMoveByBattler` (four u16s) | `0x02023DC4` | `0x02024274` |
| `gBattleStruct` (pointer) | `0x02023FE8` | `0x0202449C` |
| `gBattlerControllerFuncs` | `0x03004FE0` | `0x03005D60` |
| `PlayerBufferExecCompleted` (Thumb pointer) | `0x0802E33D` | `0x0805748D` |
| `STATE_WAIT_ACTION_CONFIRMED_STANDBY` | `3` | `4` |
| `BattleStruct.moveTarget` / `chosenMovePositions` | `0x0C` / `0x80` | `0x0C` / `0x80` |

Symbol receipts are `data/gen3/pret/poke{firered,leafgreen}.sym:117,142,802,1987`
and `pokeemerald.sym:156,181,953,3367`. Struct fields are FR `include/battle.h:373-412`
and Emerald `include/battle.h:354-392`; the test compiles their actual pointer-free
prefixes and constants and measures both offsets with C `offsetof`. Emerald's
`MAX_BATTLERS_COUNT` is an enum, and its action-state enum adds `STATE_TURN_START_RECORD`;
neither fact is copied from FR or RR.

The engine path is FR `src/battle_main.c:3086-3095,3350-3371,3981-4027` and Emerald's
corresponding `HandleTurnActionSelectionState` / `HandleAction_UseMove` (standby at
`:4458`). FR `src/battle_controller_player.c:186-200` and Emerald `:200-214` prove
that the hand-off installs `PlayerBufferRunCommand` and clears the execution bit
outside link battles. Existing generator checks verify its ROM prefix and pool.

The checkpoint generator additionally reads each title's own `gBattleMoves[153]`:
effect must be `EFFECT_EXPLOSION` (7), PP must be 5. Missing or changed hand-off,
effect or PP proof stops generation. Only `battle.handoff.explode` changes in the
vanilla checkpoint files; the CPU, ordinary battle and Perish clauses are preserved.
RR's generated profile and checkpoint are unchanged.

## Runtime and surface

The existing executor writes battle moves/PP, chosen action/move, move position,
target, standby state, then the controller pointer last. It never writes HP for
the active Explosion commit. The existing plan validator checks the complete
shape before the atomic write. Missing hand-off proof and doubles/multi-controller
states stay held; the proved path is singles, controller 0. This also makes the
unqualified RR doubles path a hold; RR's qualified singles path is retained.

The server adapter opts FR/LG/E into Explode. Manager uses exact ROM-type overrides
so the change does not enable Archipelago or expansion by their shared game ID.
Explode's existing label, description and HUD text are retained. The generated UI
capability fixture changes only the three vanilla Explode booleans.

No companion is required. No file under `patch/src` is changed, and native trade
readiness is not changed by this card.

## Live rows for the coordinator

Run from the integrated source cut with the established Gen 3 environment:

```text
python tools/e2e_duo.py --game gen3_frlg --scenario explode_gen3
python tools/e2e_duo.py --game gen3_lgfr --scenario explode_gen3
python tools/e2e_duo.py --game gen3_emerald --scenario explode_gen3
```

The subject is B: these exercise LG, FR and Emerald respectively. The row reuses
the existing active-faint carrier and saved-state oracle. It requires a keyed
command, the hand-off, no player press through the KO, move 153, the attacker's
faint site/counter increment, zero SLink HP writes, and the existing independent
saved-party/box/server readback.

The new measured `EXPLOSION_PP` marker must show committed `5/5/5/5` and a later
valid PP vector with a decrease in at least one slot. The Lua observer rejects a
KO without that decrease; the Python oracle rejects missing, unchanged or invalid
PP vectors. Normal input to advance battle text after the KO remains allowed, as
in the existing carrier; it is not input to initiate the Explosion.

Before final physical qualification, every required row must PASS without a
control/skip substitution. The old RR receipts predate this stronger PP marker;
they are not receipts from the new oracle.

## Verification

The first production-client MODEL control failed on FR, LG and Emerald: the
chosen move remained zero. It passes after binding, with no companion and no HP
write. Separate red controls caught missing capability opt-ins, writes in doubles
or without a hand-off, missing vanilla carrier registration, and a false-positive
Explosion KO with no PP consumption. Final unit counts and receipt pins follow
in the verification receipt committed with this card.
