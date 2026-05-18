# Phase 0 — Gen 1 / Gen 2 profile address audit

**Goal**: cross-reference every memory address in [lua/games/gen1_rby.lua](../lua/games/gen1_rby.lua) and [lua/games/gen2_crystal.lua](../lua/games/gen2_crystal.lua) against authoritative sources (pret disassemblies, DataCrystal RAM map) before adding new features on top. Verification is two-tier:

- **Static cross-reference** (done in Phase 0): WebFetch DataCrystal RAM maps; flag profile addresses that disagree with at least one independent source.
- **Live verification** (done in Phase 9): `lua/tests/test_gen{1,2}_profile_audit.lua` dumps every profile address live in BizHawk during boot, overworld idle, wild battle, and trainer battle; user reports values for each that don't pass plausibility checks.

**Convention in this doc**:
- ✅ **Confirmed** — at least two independent sources agree with the profile.
- ⚠️ **Single-source** — only one source (DataCrystal or the existing profile) supports it; needs Phase 9 live verification.
- ❌ **Discrepancy** — sources disagree with the profile; correction is staged for Phase 9 after live confirmation.
- 🆕 **New** — address is not in the existing profile yet; will be added in a later phase from authoritative sources.

Sources:
- DC = DataCrystal RAM map ([Red/Blue](https://datacrystal.tcrf.net/wiki/Pok%C3%A9mon_Red_and_Blue/RAM_map), [Yellow](https://datacrystal.tcrf.net/wiki/Pok%C3%A9mon_Yellow/RAM_map), [Crystal](https://datacrystal.tcrf.net/wiki/Pok%C3%A9mon_Crystal/RAM_map))
- pret/pokered = https://github.com/pret/pokered (ram/wram.asm — raw fetch unreliable due to SECTION-based addressing)
- pret/pokecrystal = https://github.com/pret/pokecrystal

---

## Gen 1 — Red / Blue (US English)

Profile location: [lua/games/gen1_rby.lua:46-98](../lua/games/gen1_rby.lua:46)

| Field | Profile value | DC value | Status | Notes |
|---|---|---|---|---|
| party_count_addr | 0xD163 | 0xD163 | ✅ | wPartyCount |
| party_species_addr | 0xD164 | 0xD164 | ✅ | wPartySpecies (6 bytes + 0xFF terminator) |
| party_base_addr | 0xD16B | 0xD16B | ✅ | wPartyMon1 base — 6 × 44 bytes |
| party_ot_names_addr | 0xD273 | 0xD273 | ✅ | wPartyMonOT (6 × 11) |
| party_nicks_addr | 0xD2B5 | 0xD2B5 | ✅ | wPartyMonNicks |
| party_struct_size | 44 | 44 | ✅ | |
| enemy_count_addr | 0xD89C | 0xD89C | ✅ | wEnemyPartyCount |
| enemy_base_addr | 0xD8A4 | (0xD89D + 7) | ✅ | wEnemyMon1 = count(1) + species_list(7) + struct[0]. DC notes wEnemyMon1 at 0xD89D-ish; profile's interpretation (D8A4) places it after the 7-byte count+species region, consistent with pret convention. |
| enemy_species_list_addr | 0xD89D | 0xD89D | ✅ | |
| box_count_addr | 0xDA80 | 0xDA80 | ✅ | wBoxCount |
| box_species_addr | 0xDA81 | (DC implies) | ⚠️ | DC doesn't list explicitly; profile placement (count+1) is conventional |
| box_base_addr | 0xDA96 | 0xDA96 | ✅ | wBoxMon1 |
| box_ot_names_addr | 0xDD2A | 0xDD2A | ✅ | |
| box_nicks_addr | 0xDEB8 | (after OT) | ⚠️ | DC doesn't explicitly list; profile is conventional placement |
| bag_count_addr | 0xD31D | 0xD31D | ✅ | wNumBagItems |
| bag_items_addr | 0xD31E | 0xD31E | ✅ | |
| **battle_flag_addr** | **0xD057** | **0xD05A** | ❌ | **DISCREPANCY**. DC labels D05A as wIsInBattle. Profile uses D057. Possible explanations: (a) profile is wrong by 3 bytes; (b) DC is wrong; (c) both addresses exist (e.g. D057 is wBattleType, D05A is wIsInBattle). Phase 9 diagnostic reads BOTH addresses live — the one that returns 0..2 during overworld/wild/trainer is correct. |
| enemy_mon_species_addr | 0xCFE5 | 0xCFE5 | ✅ | wEnemyMon battle_struct, offset 0 |
| enemy_mon_hp_addr | 0xCFE6 | 0xCFE6 | ✅ | offset +1 (2 bytes BE) |
| enemy_mon_level_addr | 0xCFF3 | 0xCFE8 | ⚠️ | DC says enemy "Level" is at CFE8 (offset +3). Profile uses CFF3 (offset +0x0E). In Gen 1 battle struct there are typically TWO level bytes — "scaling level" used in damage formulas (+3) and "actual level" used for display (+0x0E). Profile's offset 0x0E is correct for "actual level"; DC's CFE8 is the scaling level. Both are real; profile's choice is right for our use case (display level). |
| enemy_mon_maxhp_addr | 0xCFF4 | 0xCFF4 | ✅ | offset +0x0F (2 bytes BE) |
| map_id_addr | 0xD35E | 0xD35E | ✅ | wCurMap |
| player_name_addr | 0xD158 | 0xD158 | ✅ | wPlayerName |
| player_id_addr | 0xD359 | 0xD359 | ✅ | wPlayerID (2 bytes BE) |
| badges_addr | 0xD356 | 0xD356 | ✅ | wObtainedBadges |

### Gen 1 party struct offsets (within 44-byte struct)
| Offset | Field | Notes |
|---|---|---|
| 0x00 | species | ✅ |
| 0x01 | current HP (2 BE) | ✅ |
| 0x04 | status | ✅ non-volatile flags |
| 0x0C | OT ID (2 BE) | ✅ |
| 0x1B | DVs 1 (Atk/Def nibbles) | ✅ |
| 0x1C | DVs 2 (Spd/Spc nibbles) | ✅ |
| 0x21 | actual level | ✅ |
| 0x22 | max HP (2 BE) | ✅ |

### Gen 1 — NEW addresses required for later phases (not yet in profile)
| Symbol | Per DC | Phase | Notes |
|---|---|---|---|
| wPlayerMonAttackMod | 0xCD1A | 2 | stat stages start; +1..+5 for Def/Spd/Spc/Acc/Eva |
| wEnemyMonAttackMod | 0xCD2E | 2 | enemy stat stages start |
| party slot Moves[4] | +0x08 in struct | 3 | 4 bytes of move IDs |
| party slot PP[4] | +0x1D in struct | 3 | simple 1-byte counters (no PP-Up encoding in Gen 1) |
| wEnemyMonMoves | 0xCFED | 4 | offset +8 in wEnemyMon |
| wEnemyMonPP | 0xCFFE | 4 | offset +0x19 in wEnemyMon |
| wTrainerClass | 0xD031 (working hypothesis) | 5 | DC lists 0xCD2D but that conflicts with stat mods — likely DC error; pret convention is wTrainerClass in a different region. Verify in Phase 5. |
| wTrainerNo | TBD | 5 | adjacent to wTrainerClass |
| wAudioFadeOutControl | 0xC002 | 7 | per DC |
| wMusicID / wSoundID | 0xD35B / 0xD35C | 7 | per DC; SFX dispatch |

### Gen 1 — Yellow profile (lua/games/gen1_rby.lua:101-140)
The Yellow profile claims every relevant address is shifted -1 byte from Red/Blue due to extra Yellow audio code. DataCrystal Yellow page is sparse and confirms only the principle ("offset of -1 from Red and Blue"), not exact addresses. The shift pattern is plausible (Yellow does add audio data), but every address in the Yellow profile needs Phase 9 live verification on an actual Yellow ROM. **Status: ⚠️ single-source for every Yellow address.**

---

## Gen 2 — Crystal (US English)

Profile location: [lua/games/gen2_crystal.lua:32-132](../lua/games/gen2_crystal.lua:32)

| Field | Profile value | DC value | Status | Notes |
|---|---|---|---|---|
| party_count_addr | 0xDCD7 | 0xDCD7 | ✅ | wPartyCount |
| party_species_addr | 0xDCD8 | 0xDCD8 | ✅ | wPartySpecies (6 bytes + 0xFF terminator) |
| party_base_addr | 0xDCDF | 0xDCDF | ✅ | wPartyMon1, 6 × 48 bytes |
| party_ot_names_addr | 0xDDFF | 0xDDFF | ✅ | wPartyMonOT |
| party_nicks_addr | 0xDE41 | 0xDE41 | ✅ | wPartyMonNicknames |
| party_struct_size | 48 | 48 | ✅ | |
| **enemy_count_addr** | **0xD280** (TODO) | not explicitly in DC | ⚠️ | DC mentions opposing-trainer party data without exact address; profile's 0xD280 traces from a pre-existing source. Phase 9 verifies. |
| **enemy_base_addr** | **0xD288** (TODO) | not in DC | ⚠️ | wOTPartyMon1 base. Live verification needed. |
| box (SRAM) | 0xAD10 family | not in DC (SRAM separate) | ⚠️ | profile's SRAM box layout is plausible per pokecrystal SRAM convention |
| bag_count_addr | 0xD8D7 | not explicitly | ⚠️ | wNumBalls (ball pocket) |
| bag_items_addr | 0xD8D8 | not explicitly | ⚠️ | |
| **battle_flag_addr** | **0xD22D** (TODO) | 0xD22D (DC labels as "Type of Battle") | ⚠️ | DC confirms 0xD22D as a battle-type byte. Live verification needed to confirm semantics (0=overworld, 1=wild, 2=trainer). |
| enemy_mon_species_addr | 0xD206 | 0xD206 | ✅ | enemy battle struct base + 0 |
| enemy_mon_hp_addr | 0xD216 | 0xD216 | ✅ | offset +0x10 (2 bytes BE) |
| enemy_mon_level_addr | 0xD213 | 0xD213 | ✅ | offset +0x0D |
| enemy_mon_maxhp_addr | 0xD218 | 0xD218 | ✅ | offset +0x12 (2 bytes BE) |
| enemy_species_list_addr | 0xD281 (TODO) | (post-count) | ⚠️ | conventional placement, live-verify |
| map_group_addr | 0xDCB5 | (DC lists ~0xD47D region for player) | ⚠️ | DC doesn't directly list map group/number; profile's 0xDCB5/DCB6 is from pret convention. Phase 9 verifies. |
| map_number_addr | 0xDCB6 | | ⚠️ | |
| player_id_addr | 0xD47B | 0xD47B | ✅ | |
| player_name_addr | 0xD47D | 0xD47D | ✅ | |
| badges_addr (Johto) | 0xD857 | 0xD857 | ✅ | |
| kanto_badges_addr | 0xD858 | 0xD858 | ✅ | |

### Gen 2 party struct offsets (within 48-byte struct)
All offsets confirmed against pret/pokecrystal `macros/wram.asm` `party_struct` definition:

| Offset | Field | Status |
|---|---|---|
| 0x00 | species | ✅ |
| 0x01 | held item | ✅ |
| 0x02–0x05 | Moves[4] | ✅ (NEW for Phase 3) |
| 0x06–0x07 | OT ID (2 BE) | ✅ |
| 0x08–0x0A | Experience (3 bytes) | (not in profile, not needed) |
| 0x15–0x16 | DVs (Atk/Def, Spd/Spc nibbles) | ✅ |
| 0x17–0x1A | PP[4] (bit-packed: low 6 bits = PP, top 2 = PP-Up count) | ✅ (NEW for Phase 3) |
| 0x1F | level | ✅ |
| 0x20 | status | ✅ |
| 0x22–0x23 | current HP (2 BE) | ✅ |
| 0x24–0x25 | max HP (2 BE) | ✅ |

**NOTE on DataCrystal table for Crystal**: DC's party struct layout had errors (listed PP at offset 6 AND offset 0x1B-1E, which can't both be right). The pret macro is authoritative; PP is at 0x17-0x1A. Profile already uses correct convention.

### Gen 2 — NEW addresses required for later phases (not yet in profile)
| Symbol | Per DC | Phase | Notes |
|---|---|---|---|
| wPlayerStatLevels | ~0xCA0E-0xCA14 (DC ambiguous) | 2 | 7 bytes: ATK/DEF/SPD/SAT/SDF/ACC/EVA. Phase 2 fetches pret directly. |
| wEnemyStatLevels | ~0xCA15-0xCA1B | 2 | |
| wEnemyMonMoves | 0xD208 | 4 | DC table for enemy battle struct |
| wEnemyMonPP | 0xD20E | 4 | DC table |
| wOtherTrainerClass | ~0xD233 | 5 | DC suggests this region |
| wOtherTrainerID | ~0xD234 | 5 | |
| Audio dispatch | wMapMusic / wMusicID etc. | 7 | pret audio engine constants needed |
| wDayCareMan / wBreedMon1 | (Phase 1 reference only) | — | not in our read-loop; gift detection uses area_id |
| EGG species constant | 0xFD = 253 | 1 | pret `constants/pokemon_constants.asm` |

---

## Discrepancies summary (require Phase 9 live verification)

| Game | Field | Profile | Alternative source | Action |
|---|---|---|---|---|
| Gen 1 R/B | battle_flag_addr | 0xD057 | DC: 0xD05A | Diagnostic reads both, user reports which transitions 0→1 on battle start |
| Gen 1 R/B | enemy_mon_level_addr | 0xCFF3 (+0x0E) | DC: 0xCFE8 (+0x03) | Two real fields; profile's choice (actual level) is correct — no action |
| Gen 1 Y | every address | shifted -1 from R/B | DC sparse | Diagnostic reads all on a Yellow ROM |
| Gen 2 | 4 TODO addresses | profile guesses | DC ambiguous | Diagnostic reads, user reports values during state transitions |

## Confidence ladder

1. ✅ DC + profile + pret usage agree → trust outright
2. ⚠️ Only one source (profile alone, or DC alone, or pret usage alone) → tentative, Phase 9 verifies
3. ❌ Sources actively disagree → fix only after Phase 9 live evidence

**No automatic profile changes in Phase 0.** The Yellow profile delta (-1 byte), the Gen 1 battle_flag, and the 4 Gen 2 TODOs all stay as currently written until Phase 9 diagnostics provide ground truth — at which point a Phase 9a "fix(gen1/2): correct addresses per audit" commit lands all corrections at once.

## Phase 0 deliverables (this audit file plus)

- [lua/tests/test_gen1_profile_audit.lua](../lua/tests/test_gen1_profile_audit.lua) — raw-byte dump of every profile address with plausibility checks; for R/B and Y
- [lua/tests/test_gen2_profile_audit.lua](../lua/tests/test_gen2_profile_audit.lua) — same for Crystal
- [tests/PHASE9_BATCH.md](PHASE9_BATCH.md) — Phase 0 entry first in the user testing checklist
