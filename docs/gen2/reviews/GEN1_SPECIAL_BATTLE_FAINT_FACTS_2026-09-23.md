# Gen 1 special-battle faints: SOURCE facts (O-30, card gen1-inbattle-faint-all)

Companion to `INBATTLE_FAINT_FACTS_2026-09-23.md` §4. The sources are pret/pokered `405b624`
(R/B), pret/pokeyellow (Y) and pureRGB `7e7a4653`, under `.cache/pret/*` and `.cache/purergb-src`.

## Battle types (`constants/battle_constants.asm:42-46`)

| wBattleType | Where | Player mon on the field? |
|---|---|---|
| 0 NORMAL | every other battle, including pureRGB's non-Classic Safari types (pureRGB `init_battle_variables.asm:53-58` sets SAFARI only when `wSafariType == 0`) | yes |
| 1 OLD_MAN | Viridian catch tutorial (`scripts/ViridianCity.asm:62+` R) | no |
| 2 SAFARI | Classic Safari maps (`init_battle_variables.asm:29-36` R) | no |
| 3 RUN (Y only) | nothing writes it (`.handleUnusedBattle`, Y `core.asm:2221`) | n/a |
| 4 PIKACHU (Y only) | Oak's Pikachu demo (`scripts/PalletTown.asm:143` Y). The player has no party yet. | no |

## The engine path for type != 0

- `StartBattle` sends a mon out only when `wBattleType == 0` (`jp z, .playerSendOutFirstMon`,
  R `core.asm:164-166`, Y `:173-175`, pureRGB `:195-197`).
- Otherwise it runs `.displaySafariZoneBattleMenu`, which loops back to `.checkAnyPartyAlive`
  (R `:206`, Y `:215`, pureRGB `:238`) or ends the battle (`ret c`, R `:170`).
- It never reaches `MainInBattleLoop` (R `:280`). The other `jp MainInBattleLoop` sites are all
  downstream of `.playerSendOutFirstMon`.
- `wBattleMon` is never loaded, because `LoadBattleMonFromParty` runs only in
  `.playerSendOutFirstMon`.
- `wPlayerMonNumber` is `InitBattleVariables`' zero (R `init_battle_variables.asm:16`,
  pureRGB `:17`).

## Verdicts

- **Active-battler write:** there is no active battler, and the loop-head hook never fires.
  `W.active_faint_guard` refusing type != 0 is correct. It is not an exclusion.
- **Bench write:** safe for every party slot, slot 0 included.
  - Nothing in these battles reads the party structs except `AnyPartyAlive` at
    `.checkAnyPartyAlive` (R `:158-162`), and there is no party menu (Safari:
    BALL/BAIT/ROCK/RUN; old man: scripted ITEM, R `core.asm:2019-2046`).
  - No EXP, so no level-up and no evolution HP-delta trap.
  - Killing the last live mon mid-Safari makes the next `.checkAnyPartyAlive` take
    `HandlePlayerBlackOut` (R `:162`). This is the native blackout, the same end the checkpoint
    path reached after the battle.
  - The old man battle checks `AnyPartyAlive` only before its menu, so a death there blacks out
    at the overworld afterwards, as before.
  - Receipt is the only in-battle landing point, since there is no loop head.
- **Link (`wLinkState == 4`):** held to the checkpoint (O-30 exception).
- **pureRGB:** same three types, same dispatch.
- **Yellow PIKACHU:** the player has no party, so there is nothing to faint.

## Change

`lua/gen1/client.lua` on-receipt bench write: `battle.type == 0 and slot ~= player_mon_number`
became `(battle.type ~= 0 or slot ~= player_mon_number)`, and `link_state ~= 4` is kept. The
loop-head paths are unchanged, since type != 0 never reaches them natively.

Known ceiling: if a receipt write is refused (for example the pureRGB WRAM-bank gate), a special
battle has no loop head to retry at. The `battle_end` flush then lands it at the checkpoint.
