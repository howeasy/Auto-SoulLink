# Archipelago (AP) FireRed/LeafGreen: archived reference

> **Historical record, moved 2026-10-03** from `docs/REFERENCE.md`. Archipelago builds are not supported and are not offered anywhere in SLink. This describes the old Gen 3 client (tag `archive/gen3-old-client`); current Gen 3 facts live in `docs/REFERENCE.md` and `data/games/gen3_*`.


> **Archived (C5-6, owner ruling 24):** this section describes the old Gen 3 client (`lua/clients/gen3_frlge_client.lua` + `lua/memory_gba.lua`), deleted from the tree and kept at tag `archive/gen3-old-client`. The rewritten client under `lua/gen3/` reads through `data/games/gen3_{frlg,rr}/profile.json`; this section awaits that rewrite. Archipelago FireRed/LeafGreen is not supported until then.

SLink auto-detects AP-patched ROMs and adjusts all memory addresses automatically. No manual configuration needed.

**How it works:**
- AP recompiles the FRLG binary, shifting all EWRAM globals (+0x14) and IWRAM pointers (−0xB0)
- `memory_gba.lua` reads a signature string at ROM offset 0x108 to detect AP ROMs ("pokemon red version" / "pokemon green version")
- All profile-dependent addresses are stored in a `PROFILES` table and applied at startup via `M.initProfile()`
- The status page shows "FireRed (AP)" or "LeafGreen (AP)" for AP clients

**AP address profile (complete):**

| Symbol | Vanilla | AP | Shift |
|---|---|---|---|
| `gMain` | `0x030030F0` | `0x03003040` | −0xB0 (IWRAM) |
| `gSaveBlock1Ptr` | `0x03005008` | `0x03004F58` | −0xB0 |
| `gSaveBlock2Ptr` | `0x0300500C` | `0x03004F5C` | −0xB0 |
| `gPokemonStoragePtr` | `0x03005010` | `0x03004F60` | −0xB0 |
| `gPlayerParty` | `0x02024284` | `0x02024298` | +0x14 (EWRAM) |
| `gBattleTypeFlags` | `0x02022B4C` | `0x02022B60` | +0x14 |
| `gBattleOutcome` | `0x02023E8A` | `0x02023E9E` | +0x14 |
| SB1 Pokéball pocket | `+0x0430` | `+0x0680` | +0x250 (struct) |
| SB2 `encryptionKey` | `+0x0F20` | `+0x0F2C` | +0x0C (struct) |
| `gBaseStats` | `0x08254784` | `0x0825634C` | +0xEBC8 (ROM) |

**AP-specific behavior:**

- **Overworld detection**: AP uses a custom `gMain+0x038` field (1 = overworld, anything else = not overworld) instead of the vanilla `gMain+0x439` inBattle bit
- **Battle detection**: Three-condition check prevents false triggers from menus: `gMain+0x038 != 1` AND `gBattleTypeFlags != 0` AND `gBattleOutcome == 0`. The `gBattleOutcome` check is necessary because `gBattleTypeFlags` stays stale (non-zero) after battles end in AP.
- **Item tracking**: AP expands bag pocket structs by 592 bytes (0x250). Item IDs are not encrypted; quantities are XOR'd with `encryptionKey & 0xFFFF` from `SB2+0x0F2C`. The AP encryption key is at a +0x0C shift from vanilla. `M.hasPokeballs()` and `M.countPokeballs()` use profile-dependent offsets automatically.
- **Battle redirect**: `forceImmediateWhiteout()` cannot redirect to `ReturnFromBattleToOverworld` in AP mode (ROM function address unknown); it zeros party HP only
- **Sound effects**: In-game SE playback works on AP ROMs. Song header addresses are discovered per-ROM via `lua/test_sound_discovery.lua` and stored in the AP profile's `SE_SONG_HEADERS` table.
- **Starter/gift linking**: AP supports randomized starting locations. If a gift/static Pokémon appears before `nuzlocke_active` is set, the client uses `"intro"` as the area_id so both players' starters link regardless of randomized start location. Post-nuzlocke gifts (Eevee, Lapras, fossils) use their real area_id. The server treats `"intro"` and `"gift"` as gift areas (no `pokeballs_obtained` activation, pre-nuzlocke faint immunity).
- **Menu/script state protection**: AP's `isInOverworld()` returns false during menus (bag, PC, Repel use). The `party_diff_ok` gate freezes all party change detection during non-overworld/non-battle states, preventing false `box_to_party`/`party_to_box` events from memory read glitches during BizHawk window resize or in-game menus.
- **Coexistence**: SLink runs alongside the AP BizHawk client — both use different memory write targets (AP writes item flags; SLink writes HP/party data)
- **Gym badge bitmask**: Badges are read from `SaveBlock1.flags[0x104]` as a raw bitmask (each bit = one badge). AP can grant badges out of order, so the status page renders each badge independently via `badge_mask & (1 << i)` — no assumption of sequential acquisition
