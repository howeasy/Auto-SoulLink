# In-battle active faint (D7/D12): research (plan card C1-7)

**Source:** pokeheartgold @ad7a3afa (asm counts as source).
**OMP card:** G4-R10 `cx-0cff1364`.
**Coordinator re-checks:**
- `CopyBattleMonToPartyMon` (`src/battle/overlay_12_0224E4FC.c:1557-1564`)
- `BattleControllerPlayer_TurnEnd` (`src/battle/battle_controller_player.c:1655-1669`)
- the party-HP read in `ov12_0224D540` (`:3430-3437`)
- the party-tail encryption macros (`src/pokemon.c:60-66`)

## Findings

1. **Two HP copies.** A battle has `battleMons[i]` (the `ctx+0x2D40` array) **and** a party Pokémon record in `BattleSystem.trainerParty[b]` (`BattleSystem+0x68`, copied from `BattleSetup.party`).
2. **Sync is one-way and event-driven.** HP goes battleMon → party only, at each damage or heal event: `CopyBattleMonToPartyMon` → `BattleController_EmitBattleMonToPartyMonCopy`, called from `BtlCmd_UpdateHealthbarValue` (`battle_command.c:965`) and about ten other damage/heal sites. There is no per-turn, switch-out or battle-end sync.
3. **The save is built from the party copy.** At battle end, `Party_Copy(trainerParty[0], setup->party[0])` (`asm/overlay_12_022378C0.s:895`), and the field then copies that over the save party (`src/battle/battle_setup.c:433`).
   - **A write to `battleMons[i].hp` alone never reaches the save.** It is also harmful: the replacement and win/lose logic read the **party copy's** HP through `GetMonData(MON_DATA_HP)` (`battle_controller_player.c:3436-3458, 3517-3541`; `CanSwitchMon`, `overlay_12_0224E4FC.c:2704`). The mon could be offered as a replacement, or the battle could fail to end.
4. **The faint sweep runs every turn.** `BattleControllerPlayer_TurnEnd` (`battle_controller_player.c:1658-1669`) calls `ov12_0224D7EC` (win/lose) and `ov12_0224D540` (faint → replacement). Both test hp == 0 on **every** turn, including status moves, switches, items and run attempts; the controller pipeline 8 → 12 is unconditional.
   - `BtlCmd_TryFaintMon` is **script-driven** (battle-script data), so a raw RAM write never triggers it. **Do not rely on hooking it.**
5. **Latency and safe point.** The worst-case delay is the end of the current turn.
   - The selection screen (controller command 5) has no HP gate. `Battler_CanSelectAction` checks `status2` only.
   - The safest write point is **controller command 11 `UPDATE_FIELD_CONDITION_EXTRA`**, the last state before `TURN_END`. No input or move execution follows it.
6. **Loss path.**
   - If the side's party HP sum is 0, the result is `BATTLE_RESULT_LOSE` (`battle_controller_player.c:3504-3619`), leading to `BATTLE_SUBSCRIPT_BATTLE_LOST`.
   - `winFlag` = 2 at battle end (`asm/overlay_12_022378C0.s:962-968`).
   - A wild loss leads to `Task_Blackout` (`src/encounter.c:373-376`); a trainer loss also takes money (`battle_command.c:2243`).
   - The save copy-back happens **before** the loss handling (`src/encounter.c:136` → `sub_0205239C`).
   - `HealParty` runs only on `BATTLE_TYPE_11` losses (`:145-148`) and when a follower exists (`:154-156`).
7. **Other "fainted" state.** The FAINTED `battleStatus` bit, `totalTimesFainted`, `battlerIdFainted` and the EXP flag are set only by the script command and are **not** read by the replacement or loss sweeps. Skipping `UpdateFriendshipFainted` is fine (no friendship penalty).

## Write recipe (for C1-8 / probe row o to confirm live)

1. Get `BattleSystem*` (C1-8), then `ctx = [bs+0x30]`.
2. Find the partner-linked mon's battler `b` via the slot mapping (C1-8) and its party index `p = ctx.selectedMonIndex[b]` (`ctx+0x219C`). Find the party via `BattleSystem_GetPartyMon` semantics (`trainerParty[b]` or `[b&1]` by battle type).
3. When `ctx->command == 11` (a battle-phase exec hook or a per-frame poll of the controller command), write in one frame:
   - `battleMons[b].hp = 0` (`ctx+0x2D40+0xC0*b+0x4C`, u16)
   - the party mon's HP (`party+0x8+0xEC*p+0x8E`), **encrypted**. The party tail (0x88-0xEB) is XOR-encrypted with the PID-seeded LCG (`ENCRY_ARGS_PTY`, `src/pokemon.c:60-66`), so XOR the new value with keystream word 3 of that stream, as `lua/gen4/reads` already computes it. It isn't covered by the box checksum.
4. Leave the FAINTED bit and counters alone; the turn-end sweep handles replacement and loss.
5. **Receipt:** frame, `b`, `p`, hp before/after in both copies.

**D12 open questions for the live probe (row o):**
- does the HP bar/animation look acceptable without a damage event?
- does the replacement prompt appear?
- does a last-mon faint produce a normal whiteout?
- **doubles:** both player battlers (0 and 2), and the `battlerId ^ 2` partner check at `:3437`
- **hge:** ov130 replaces the battle script command handler. Confirm hge still runs the vanilla `TurnEnd` sweep, or find its equivalent from the build symbols.

## Unverified

- The positions of `tryfaintmon` inside the battle-script data (ROM NARC; not needed for the recipe).
- The absence of `STATIC_ASSERT`s for 0x2D40/0x4C (corroborated by asm literal pools).
