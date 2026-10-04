# Battle pointer + party-slot → battler mapping (plan card C1-8, research half)

- **Source:** pokeheartgold @ad7a3afa; `sFieldSysPtr` address from the pinned xMAP.
- **OMP card:** G4-R11 `cx-0ed2adc9`.
- **Coordinator re-checks:** the `OverlayManager` struct (`include/overlay_manager.h:20-28`); the battle allocation `OverlayManager_CreateAndGetData(man, 0x2490, 5)` (`asm/overlay_12_022378C0.s:4264-4273`); `gOverlayTemplate_Battle` (`src/launch_application.c:178-182`); `ov12_02238A68` (`asm/overlay_12_022378C0.s:1514-1521`).

## Zero-hook pointer chain (recommended)

```
fs   = u32[0x021D4158]          -- sFieldSysPtr (xMAP)
sub0 = u32[fs + 0x00]           -- FieldSystem.unk0
man  = u32[sub0 + 0x04]         -- unk4 = the launched app's OverlayManager (src/field_system.c:127-133)
bs   = u32[man + 0x1C]          -- OverlayManager.data = BattleSystem* (0x2490 block, HEAP_ID_BATTLE)
ctx  = u32[bs + 0x30]           -- BattleContext* (asm/overlay_12_022378C0.s:720, 1800-1802)
```

**Validation.** `unk4` is shared by every launched app (bag, party, summary). Accept the chain only if all of these hold:
- `u32[man + 0x0C] == FS_OVERLAY_ID(OVY_12)` (the template's 4th field; `gOverlayTemplate_Battle`)
- `bs != 0` and `ctx != 0` (ctx is allocated after bs)
- the `battleMons` species match the selected party species (structure check only). Species equality does not identify a Pokémon: before any write, resolve the selected party record's PID:OTID against the linked key and save-party slot, and recheck the pointer chain in the same write window.

**Two traps:**
- **`man + 0x18` is `args` = the `BattleSetup*`, not the `BattleSystem`.** Mixing them up mis-parses the struct.
- **The link path briefly puts a 0x1028 staging block in `data`.** Link battles are out of scope; the invariants reject it anyway.

**Cost.** Four loads per frame, re-acquired each frame (no caching across battles). **Zero hooks** for a battle-local read; this does not provide a persistent outcome pointer after the application exits. An encounter-scoped outcome latch must outlive the chain for loss/whiteout observation without retaining a stale writable pointer. A controller execution hook may still be required for the D7 timing seam; frame-poll coverage is OPEN ([battle_faint.md](battle_faint.md)).

**One-hook alternative, as a wake-up only:** `ov12_02238A68` @ 0x02238A68 (ov12) runs once per battle with r0 = `BattleSystem*` and r1 = `BattleSetup*`. Keep reading through the chain regardless.

## Useful offsets (asm-literal-derived)

| Field | Offset |
|---|---|
| `bs->battleType` | +0x2C |
| `bs->ctx` | +0x30 |
| `bs->opponentData[4]` | +0x34; `battlerType` at `+0x195` of each (side = `& 1`) |
| `bs->trainerParty[4]` | +0x68 (header-derived only; neighbours are asm-confirmed) |
| `ctx->selectedMonIndex[4]` | +0x219C (u8) |
| `ctx->battleMons[b]` | +0x2D40 + 0xC0·b (**not** 0x2D4C, which is `moves[0]`) |

BattleMon fields: species +0x00, moves +0x0C, level +0x34, **hp +0x4C (s32; read/write all four bytes)**, maxHp +0x50, exp +0x64, gender +0x7E (low nibble). The selected party record's HP is a separate u16 at `PartyPokemon+0x8E` (`include/battle/battle.h:248`; `include/pokemon_types_def.h:203`); a partial battle-HP read or write can leave a stale signed high half.

## Party slot → battler

The save party is struct-copied, index-preserving, into `BattleSetup.party[0]` (`src/battle/battle_setup.c:174-177, 227`; `Party_Copy` = `*dst = *src`, `src/party.c:125-127`). So `ctx->selectedMonIndex[b] == N` ⟺ `battleMons[b]` is save-party slot N.

The party owner per battler follows `BattleSystem_GetPartyMon` (`src/battle/battle_system.c:92-100`):

| Format | `owner(b)` | Battlers holding the local save party |
|---|---|---|
| Singles | `b` | {0} |
| Doubles | `b & 1` | {0, 2}, distinct slots |
| Multi | `b` | {0} (battler 2 is the partner's own party) |
| Tag (two enemy trainers, no follower) | `b` if side(b)==1, else `b & 1` | {0, 2} on the player side, distinct slots |

- Player battlers are 0 and 2 (`include/constants/battle.h:6-9`). The two-enemy TAG format is created at `src/encounter.c:701-721`; its player-side party lookup uses `trainerParty[b & 1]` (`src/battle/battle_system.c:92-99`). The partner comparison in the replacement sweep is `b ^ 2` (`battle_controller_player.c:3423-3438`); the participant side and battle type must be checked, not inferred from index alone.
- **`selectedMonIndex[b] == 6` is a real sentinel for "no mon on field"** (`battle_command.c:1417-1418`, `battle_controller_player.c:3445, 3468`). Skip it.

Resolution loop (for `lua/gen4/storage.battle_faint`): for `b` in 0..3, keep `b` only if all of these hold:
- `owner(b) == 0`
- `idx = selectedMonIndex[b]` is not 6
- species ≠ 0
- the selected party record's PID:OTID matches the pending linked key and the save-party slot after battle setup copying; reject duplicates or ambiguity

Then `b` is a candidate holding save slot `idx`. Require exactly one verified owner for a write; same-species party members and reused heap addresses must not create a false match. A live TAG 0/2 case and multi/follower cases remain to be checked independently.

## Open (live, G1 row o / C1-8 probe)

- Confirm the chain live in a wild and a trainer battle, singles and doubles (HG and hge).
- hge: `HandleLoadOverlay` is replaced, but `FieldSystem_LaunchApplication`/`OverlayManager` are vanilla. Confirm the template overlay id at `man+0x0C` is still OVY_12, and whether hge's `ServerInit` (which allocates its own `BattleStruct`) leaves `bs->ctx` at +0x30. Research R9 says it does.
- `maxBattlers` for multi/tag is inferred (no asm for the store).
- A battle pointer can be recycled across battles. Prove an encounter epoch/identity and decline a command held across battle end, reset, disconnect or a different save; the chain alone does not bind the command to its originating encounter.
