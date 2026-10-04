# In-battle active faint (D7/D12): research (plan card C1-7)

**Source:** pokeheartgold @ad7a3afa (asm counts as source).
**OMP card:** G4-R10 `cx-0cff1364`.
**Coordinator re-checks:**
- `CopyBattleMonToPartyMon` (`src/battle/overlay_12_0224E4FC.c:1557-1564`)
- `BattleControllerPlayer_TurnEnd` (`src/battle/battle_controller_player.c:1655-1669`)
- the party-HP read in `ov12_0224D540` (`:3430-3437`)
- the party-tail encryption macros (`src/pokemon.c:60-66`)

## Findings

1. **Two HP copies with different widths.** A battle has `battleMons[i].hp`, a signed 32-bit field at `BattleMon+0x4C` (`include/battle/battle.h:248`), **and** a party Pokémon record with unsigned 16-bit HP at `PartyPokemon+0x8E` (`include/pokemon_types_def.h:199-204`) in `BattleSystem.trainerParty[b]` (`BattleSystem+0x68`, copied from `BattleSetup.party`). Hge retains the signed 32-bit battle field (`include/battle.h:905`).
2. **Sync is one-way and event-driven.** HP goes battleMon → party only, at each damage or heal event: `CopyBattleMonToPartyMon` → `BattleController_EmitBattleMonToPartyMonCopy`, called from `BtlCmd_UpdateHealthbarValue` (`battle_command.c:965`) and about ten other damage/heal sites. There is no per-turn, switch-out or battle-end sync.
3. **The save is built from the party copy.** At battle end, `Party_Copy(trainerParty[0], setup->party[0])` (`asm/overlay_12_022378C0.s:895`), and the field then copies that over the save party (`src/battle/battle_setup.c:433`).
   - **A write to `battleMons[i].hp` alone never reaches the save.** It is also harmful: the replacement and win/lose logic read the **party copy's** HP through `GetMonData(MON_DATA_HP)` (`battle_controller_player.c:3436-3458, 3517-3541`; `CanSwitchMon`, `overlay_12_0224E4FC.c:2704`). The mon could be offered as a replacement, or the battle could fail to end.
4. **HP sweeps are distinct from the normal faint script.** `BattleControllerPlayer_TurnEnd` (`battle_controller_player.c:1658-1669`) calls `ov12_0224D7EC` (win/lose) and `ov12_0224D540` (faint → replacement). Both inspect zero HP, including after status-only turns. But `BtlCmd_TryFaintMon` (`battle_command.c:978-990`) is script-driven and sets the FAINTED bit; the controller's `TryFaintMon` (`battle_controller_player.c:3658-3682`) consumes that bit to launch the faint subscript. A raw HP write does not itself set the bit or prove normal faint animation.
5. **Timing and safe point remain OPEN.** Controller command 11 is a candidate before `TURN_END`, not an established write gate: `BattleControllerPlayer_UpdateFieldConditionExtra` can still run Future Sight, Perish Song and Trick Room scripts (`battle_controller_player.c:1571-1655`). `ov12_02238358` can call `BattleContext_Main` twice in one battle update (`asm/overlay_12_022378C0.s:743-786`), and each call dispatches the current command (`battle_controller_player.c:159-170`); a frame-end poll has no proven coverage of every command-11 interval. The selection screen (command 5) can wait for input, so no finite command-to-effect latency follows from the turn-end sweep. Derive a pinned post-effect/pre-sweep execution seam, or prove poll coverage and latency PHYSICALLY. D7's immediate in-battle effect and D12's no-fallback rule remain unproved.
6. **Loss path.**
   - If the side's party HP sum is 0, the result is `BATTLE_RESULT_LOSE` (`battle_controller_player.c:3504-3619`), leading to `BATTLE_SUBSCRIPT_BATTLE_LOST`.
   - `winFlag` = 2 at battle end (`asm/overlay_12_022378C0.s:962-968`).
   - A wild loss leads to `Task_Blackout` (`src/encounter.c:373-376`); a trainer loss also takes money (`battle_command.c:2243`).
   - The save copy-back happens **before** the loss handling (`src/encounter.c:136` → `sub_0205239C`).
   - In the generic encounter task, `HealParty` runs on `BATTLE_TYPE_11` losses (`encounter.c:145-148`) and when the NPC-follower flag is set, including after a win (`:154-156`). The wild-loss task jumps to `Task_Blackout` (`:369-375`), which heals the saved party (`blackout.c:189-205`). Do not equate the NPC-follower flag with the ordinary walking Pokémon; `scrcmd_battle.c:109-110` reads a follower trainer number. A post-heal save cannot witness zero HP at copy-back.
7. **Other "fainted" state.** The FAINTED `battleStatus` bit, `totalTimesFainted`, `battlerIdFainted` and the EXP flag are set by the script command and are **not** read by the replacement or loss sweeps. Leaving them untouched can preserve the HP result while missing the normal faint subscript/animation. Its actual presentation remains a PHYSICAL question.

## Candidate two-copy write contract (C1-8 / probe row o; not yet qualified)

1. Get `BattleSystem*` (C1-8), then `ctx = [bs+0x30]`.
2. Resolve the linked mon's save-party slot through `ctx.selectedMonIndex[b]` (`ctx+0x219C`) and `BattleSystem_GetPartyMon` ownership semantics (`trainerParty[b]` or `[b&1]` by battle type). Revalidate slot, battler, PID:OTID, party-copy key, and pointer epoch immediately before writing; species equality alone is insufficient when two slots share a species.
3. At a *proved* post-effect/pre-sweep seam, prevalidate both spans and write in the same guarded operation:
   - `battleMons[b].hp = 0` (`ctx+0x2D40+0xC0*b+0x4C`), a **signed 32-bit/full four-byte** write; a two-byte write leaves the high half stale.
   - the party mon's **unsigned 16-bit** HP (`party+0x8+0xEC*p+0x8E`). Inspect `partyDecrypted`/`boxDecrypted` first. When unlocked, the party tail is PID-stream encrypted (`ENCRY_ARGS_PTY`, `pokemon.c:60-66`); HP uses keystream word 3. `AcquireMonLock` leaves it plaintext until `ReleaseMonLock` (`pokemon.c:122-143`), so unconditional XOR is unsafe. Refuse a locked record or establish a separately checked plaintext path. A tail-only HP edit is outside the box-data checksum.
4. A prevalidated batch is not atomic rollback: if one span writes and the other fails, report partial mutation, revoke further writes, and do not emit success. The candidate does not itself establish the FAINTED bit or animation; obtain an independent, encounter-bound game observation before treating D7 as met.
5. **Receipt proposal:** encounter/command identity, source cut, frame, battler, slot, PID:OTID, pointer epoch, encryption state, and full-width before/after HP in both copies; report partial/error distinctly. Model prevalidation must refuse a battle HP outside `0..maxHp` (including negative signed values), a party HP outside `0..partyMaxHp`, or a mismatched identity. Model readback must inspect all four battle-HP bytes and both party-HP bytes: both resulting values must be exactly zero, with no stale high half. A client receipt plus a later save witness cannot by itself prove the game faint occurred in battle.

**D12 open questions for the live probe (row o):**
- does the game's faint subscript/animation occur at all without a script-driven faint command, and does the HP bar agree?
- does the replacement prompt appear?
- does a last-mon faint produce normal loss/whiteout once, with pre-heal evidence distinct from post-heal save state?
- **doubles:** both player battlers (0 and 2), and the `battlerId ^ 2` partner check at `:3437`
- **hge:** ov130 replaces the battle script command handler. Confirm hge still runs the vanilla `TurnEnd` sweep, or find its equivalent from the build symbols.
- does an execution hook observe every legal write seam across Future Sight/Perish Song, switch, run, idle selection, and command 11 → 12 transitions? Measure command-to-game-effect latency without assuming a bound.

## Unverified

- The positions of `tryfaintmon` inside the battle-script data (ROM NARC; not needed for the recipe).
- The absence of `STATIC_ASSERT`s for 0x2D40/0x4C (corroborated by asm literal pools).
