# U2 write-window source facts (OMP Gen2-Base card gen2-O7, cx-e8d7d743, 2026-09-23)

READ-ONLY source card; recorded by the coordinator as input for card U2
(`docs/gen2/reviews/P3B7_PLAN_CODEX_2026-09-23.md`). Pinned clones `.cache/gen2-build/pokecrystal` (7a7881d)
and `.cache/gen2-build/pokegold` (656583c). C = Crystal, G = Gold/Silver.

| Question | Answer | Cites |
|---|---|---|
| Idle overworld site | `OverworldLoop` (driven by `wMapStatus`) calls `OWPlayerInput`; the player path returns while `wScriptRunning != 0` | C `engine/overworld/events.asm:3-10,241-246,265,485`; G `events.asm:241` |
| Predicate coverage | `lua/gen2_write_safety.lua:4-9` names 15 symbols: `wBattleMode`, `wScriptRunning`/`wScriptMode`/`wScriptFlags`/`wScriptStackSize`, `wMapStatus`/`wMapEventStatus`/`hMapEntryMethod`, `wJoypadDisable`, `wGameLogicPaused`, `wLinkMode`/`hSerialConnectionStatus`, `wInputType`, `wStateFlags`, `wSavedAtLeastOnce`; all present in the three `.sym` files. Mask/value pairs are pack data (`primary.state_predicates`), NOT checked by this card | repo |
| Gaps | START menu / non-script text box: **no flag**; refusal is proved by the anchor (`OWPlayerInput`) not firing. Bug-Catching Contest: **no flag in the set** (state it out of scope or add `wStatusFlags2` bit 2, see N14b facts) | as above |
| Authoritative copies | party = WRAM; **current box = SRAM** (`sBoxCount`/`sBoxMons`, `ram/sram.asm`). `SaveBox` (C `engine/menus/save.asm:521`, callers `:50,77,88,275`) copies over the SRAM box, so an out-of-window box write can be reverted by the next save; `SavePlayerData` `:498` | C/G |
| SRAM latch | `OpenSRAM` / `CloseSRAM` (`home/sram.asm:1,37`). BizHawk CartRAM visibility of an external write while SRAM is closed: **UNVERIFIED** (emulator fact; U2 must witness it) | C |
| In-battle KO | active mon lives in the battle struct; copy-back `UpdateBattleMonInParty` (C `engine/battle/core.asm:176,294,1521,2105,2670`) and `UpdateFaintedPlayerMon` (`:2656`); paired store `:1181-1185`. A live KO of the active mon must target the battle struct or the copy-back overwrites it | C |
| Save/PC/HoF windows | `wGameLogicPaused` set by save (`save.asm:137,142`), Hall of Fame (`halloffame.asm:8,30`), PC (`bills_pc.asm:2000,2003`); read by `GetJoypad` (`home/joypad.asm:35`) | C |

Negative controls for U2: START menu open (anchor-not-firing, documented as such), script text box
(`wScriptRunning`), in-battle party-only write (`wBattleMode`), mid-warp (`wMapStatus`), link/serial (`wLinkMode` +
`hSerialConnectionStatus`), save/PC window (`wGameLogicPaused`). UNVERIFIED: predicate mask/values, the CartRAM
visibility above, the `ChangeBoxSaveGame`/`LoadBox` label forms, whole-pack G/S parity.
