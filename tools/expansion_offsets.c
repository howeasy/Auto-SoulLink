/* X1 compiler-data probe. Compile with the ROM's own preprocessing/CC1/AS
 * pipeline; never execute. gen_expansion_facts.py reads the ELF32 object.
 * No numeric struct offsets, enum widths, or bitfield masks appear here.
 * All declarations are static USED data, not runtime prints or DWARF.
 */
#include "global.h"
#include "pokemon.h"
#include "pokemon_storage_system.h"
#include "main.h"
#include "move.h"
#include "item.h"
#include "load_save.h"
#include "task.h"
#include "script.h"
#include "palette.h"
#include "battle.h"
#include "gba/m4a_internal.h"
#include "constants/flags.h"
#include "constants/songs.h"
#include "x1_source_enums.h" /* generated verbatim from the pinned .c enums */

#define SZ(t) static const u32 x1_size__##t USED = sizeof(struct t); \
    static const struct t x1_zero__##t USED = {0}
#define F_AS(t, label, f) static const u32 x1_field__##t##__##label[] USED = \
    {offsetof(struct t, f), sizeof(((struct t *)0)->f)}
#define F(t, f) F_AS(t, f, f)
#define A(t, f) static const u32 x1_array__##t##__##f[] USED = \
    {offsetof(struct t, f), sizeof(((struct t *)0)->f), sizeof(((struct t *)0)->f[0])}
#define K(k) static const u32 x1_const__##k USED = (k)
#define E(t) static const u32 x1_const__SIZEOF_ENUM_##t USED = sizeof(enum t)
/* Deliberate all-ones assignment is truncated by the compiler to the actual
 * bitfield width. Suppress only its overflow diagnostic, not any ABI option.
 * The emitted zero baseline must contain no bits, and each mask must be one
 * contiguous run; the parser rejects overlaps within each probed struct.
 */
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Woverflow"
#define B(t, f) static const struct t x1_mask__##t##__##f USED = {.f = -1}

SZ(SaveBlock1);
F(SaveBlock1, location);
F_AS(SaveBlock1, location_mapGroup, location.mapGroup);
F_AS(SaveBlock1, location_mapNum, location.mapNum);
F(SaveBlock1, playerPartyCount); A(SaveBlock1, playerParty);
F(SaveBlock1, bag); F(SaveBlock1, pokeblocks);
F(SaveBlock1, flags); F(SaveBlock1, vars);
SZ(Bag); A(Bag, items); A(Bag, keyItems); A(Bag, pokeBalls);
A(Bag, TMsHMs); A(Bag, berries);
SZ(ItemSlot); F(ItemSlot, itemId); F(ItemSlot, quantity);
SZ(SaveBlock2);
A(SaveBlock2, playerName); A(SaveBlock2, playerTrainerId);
F(SaveBlock2, encryptionKey);

SZ(BoxPokemon);
F(BoxPokemon, personality); F(BoxPokemon, otId);
A(BoxPokemon, nickname); A(BoxPokemon, otName);
F(BoxPokemon, checksum); F(BoxPokemon, secure);
B(BoxPokemon, language); B(BoxPokemon, hiddenNatureModifier);
B(BoxPokemon, isBadEgg); B(BoxPokemon, hasSpecies); B(BoxPokemon, isEgg);
B(BoxPokemon, markings); B(BoxPokemon, compressedStatus); B(BoxPokemon, hpLost);
B(BoxPokemon, shinyModifier);
SZ(Pokemon);
F(Pokemon, box); F(Pokemon, status); F(Pokemon, level);
F(Pokemon, hp); F(Pokemon, maxHP); F(Pokemon, mail);
F(Pokemon, attack); F(Pokemon, defense); F(Pokemon, speed);
F(Pokemon, spAttack); F(Pokemon, spDefense);

SZ(PokemonSubstruct0);
B(PokemonSubstruct0, species); B(PokemonSubstruct0, teraType);
B(PokemonSubstruct0, heldItem); B(PokemonSubstruct0, unused_02);
B(PokemonSubstruct0, experience); B(PokemonSubstruct0, nickname11);
B(PokemonSubstruct0, unused_04);
F(PokemonSubstruct0, ppBonuses); F(PokemonSubstruct0, friendship);
B(PokemonSubstruct0, pokeball); B(PokemonSubstruct0, nickname12);
B(PokemonSubstruct0, unused_0A);
SZ(PokemonSubstruct1);
B(PokemonSubstruct1, move1); B(PokemonSubstruct1, evolutionTracker1);
B(PokemonSubstruct1, move2); B(PokemonSubstruct1, evolutionTracker2);
B(PokemonSubstruct1, move3); B(PokemonSubstruct1, unused_04);
B(PokemonSubstruct1, move4); B(PokemonSubstruct1, unused_06);
B(PokemonSubstruct1, hyperTrainedHP); B(PokemonSubstruct1, hyperTrainedAttack);
B(PokemonSubstruct1, pp1); B(PokemonSubstruct1, hyperTrainedDefense);
B(PokemonSubstruct1, pp2); B(PokemonSubstruct1, hyperTrainedSpeed);
B(PokemonSubstruct1, pp3); B(PokemonSubstruct1, hyperTrainedSpAttack);
B(PokemonSubstruct1, pp4); B(PokemonSubstruct1, hyperTrainedSpDefense);
SZ(PokemonSubstruct2);
SZ(PokemonSubstruct3);
F(PokemonSubstruct3, pokerus); F(PokemonSubstruct3, metLocation);
B(PokemonSubstruct3, metLevel); B(PokemonSubstruct3, metGame);
B(PokemonSubstruct3, dynamaxLevel); B(PokemonSubstruct3, otGender);
B(PokemonSubstruct3, hpIV); B(PokemonSubstruct3, attackIV);
B(PokemonSubstruct3, defenseIV); B(PokemonSubstruct3, speedIV);
B(PokemonSubstruct3, spAttackIV); B(PokemonSubstruct3, spDefenseIV);
B(PokemonSubstruct3, isEgg); B(PokemonSubstruct3, gigantamaxFactor);
B(PokemonSubstruct3, coolRibbon); B(PokemonSubstruct3, beautyRibbon);
B(PokemonSubstruct3, cuteRibbon); B(PokemonSubstruct3, smartRibbon);
B(PokemonSubstruct3, toughRibbon); B(PokemonSubstruct3, championRibbon);
B(PokemonSubstruct3, winningRibbon); B(PokemonSubstruct3, victoryRibbon);
B(PokemonSubstruct3, artistRibbon); B(PokemonSubstruct3, effortRibbon);
B(PokemonSubstruct3, marineRibbon); B(PokemonSubstruct3, landRibbon);
B(PokemonSubstruct3, skyRibbon); B(PokemonSubstruct3, countryRibbon);
B(PokemonSubstruct3, nationalRibbon); B(PokemonSubstruct3, earthRibbon);
B(PokemonSubstruct3, worldRibbon); B(PokemonSubstruct3, isShadow);
B(PokemonSubstruct3, unused_0B); B(PokemonSubstruct3, abilityNum);
B(PokemonSubstruct3, modernFatefulEncounter);

SZ(BattlePokemon);
F(BattlePokemon, species); F(BattlePokemon, attack); F(BattlePokemon, defense);
F(BattlePokemon, speed); F(BattlePokemon, spAttack); F(BattlePokemon, spDefense);
A(BattlePokemon, moves);
B(BattlePokemon, hpIV); B(BattlePokemon, attackIV); B(BattlePokemon, defenseIV);
B(BattlePokemon, speedIV); B(BattlePokemon, spAttackIV); B(BattlePokemon, spDefenseIV);
B(BattlePokemon, abilityNum);
A(BattlePokemon, statStages); F(BattlePokemon, ability); A(BattlePokemon, types);
A(BattlePokemon, pp); F(BattlePokemon, hp); F(BattlePokemon, level);
F(BattlePokemon, friendship); F(BattlePokemon, maxHP); F(BattlePokemon, item);
A(BattlePokemon, nickname); F(BattlePokemon, ppBonuses); A(BattlePokemon, otName);
F(BattlePokemon, experience); F(BattlePokemon, personality); F(BattlePokemon, status1);
F(BattlePokemon, volatiles); F(BattlePokemon, otId);
B(BattlePokemon, metLevel); B(BattlePokemon, isShiny); F(BattlePokemon, affectionHearts);
SZ(Volatiles); B(Volatiles, perishSongTimer);

SZ(SpeciesInfo);
F(SpeciesInfo, baseHP); F(SpeciesInfo, baseAttack); F(SpeciesInfo, baseDefense);
F(SpeciesInfo, baseSpeed); F(SpeciesInfo, baseSpAttack); F(SpeciesInfo, baseSpDefense);
A(SpeciesInfo, types); F(SpeciesInfo, growthRate); F(SpeciesInfo, expYield);
F(SpeciesInfo, itemCommon); F(SpeciesInfo, itemRare); F(SpeciesInfo, genderRatio);
A(SpeciesInfo, abilities); A(SpeciesInfo, speciesName); B(SpeciesInfo, natDexNum);
F(SpeciesInfo, evolutions);
SZ(Evolution); F(Evolution, method); F(Evolution, param);
F(Evolution, targetSpecies); F(Evolution, params);
SZ(MoveInfo);
F(MoveInfo, name); F(MoveInfo, pp); B(MoveInfo, power); B(MoveInfo, type);
B(MoveInfo, accuracy); B(MoveInfo, effect); B(MoveInfo, category);
B(MoveInfo, target); B(MoveInfo, priority); F(MoveInfo, argument);
SZ(ItemInfo);
F(ItemInfo, name); F(ItemInfo, price); F(ItemInfo, secondaryId);
F(ItemInfo, holdEffect); F(ItemInfo, holdEffectParam);
F(ItemInfo, effect); F(ItemInfo, battleUsage); B(ItemInfo, pocket);
SZ(AbilityInfo); A(AbilityInfo, name);
SZ(PokemonStorage);
F(PokemonStorage, currentBox); A(PokemonStorage, boxes); A(PokemonStorage, boxNames);
A(PokemonStorage, boxWallpapers); A(PokemonStorage, fusions);
SZ(PokemonStorageASLR); F(PokemonStorageASLR, block); A(PokemonStorageASLR, aslr);
SZ(SaveBlock1ASLR); F(SaveBlock1ASLR, block); A(SaveBlock1ASLR, aslr);
SZ(SaveBlock2ASLR); F(SaveBlock2ASLR, block); A(SaveBlock2ASLR, aslr);
SZ(Main); F(Main, callback2); F(Main, state); B(Main, inBattle);
F(Main, callback1);
SZ(Task); F(Task, func); F(Task, isActive); A(Task, data);
SZ(ScriptContext); F(ScriptContext, mode); F(ScriptContext, nativePtr);
F(ScriptContext, scriptPtr); A(ScriptContext, stack);
SZ(PaletteFadeControl); B(PaletteFadeControl, active);
SZ(BattleResults); F(BattleResults, playerFaintCounter); F(BattleResults, opponentFaintCounter);
SZ(SoundInfo); F(SoundInfo, ident); F(SoundInfo, musicPlayerHead);
SZ(MusicPlayerInfo); F(MusicPlayerInfo, songHeader); F(MusicPlayerInfo, status);
F(MusicPlayerInfo, trackCount); F(MusicPlayerInfo, priority); F(MusicPlayerInfo, clock);
F(MusicPlayerInfo, tracks); F(MusicPlayerInfo, ident); F(MusicPlayerInfo, musicPlayerNext);
SZ(MusicPlayerTrack); F(MusicPlayerTrack, flags); F(MusicPlayerTrack, wait);
F(MusicPlayerTrack, patternLevel); F(MusicPlayerTrack, repN); F(MusicPlayerTrack, gateTime);
F(MusicPlayerTrack, bendRange); F(MusicPlayerTrack, volX); F(MusicPlayerTrack, lfoSpeed);
F(MusicPlayerTrack, chan); F(MusicPlayerTrack, cmdPtr);
#pragma GCC diagnostic pop

K(NUM_SUBSTRUCT_BYTES); K(NUM_SPECIES); K(MOVES_COUNT); K(MOVES_COUNT_ALL);
K(ABILITIES_COUNT); K(ITEMS_COUNT); K(ITEM_NAME_LENGTH); K(MOVE_NAME_LENGTH);
K(ABILITY_NAME_LENGTH); K(POKEMON_NAME_LENGTH);
K(BAG_ITEMS_COUNT); K(BAG_KEYITEMS_COUNT); K(BAG_POKEBALLS_COUNT);
K(BAG_TMHM_COUNT); K(BAG_BERRIES_COUNT); K(PC_ITEMS_COUNT);
K(PARTY_SIZE); K(MAX_BATTLE_TRAINERS); K(MAX_BATTLERS_COUNT);
K(B_TRAINER_PLAYER); K(B_TRAINER_OPPONENT_A);
K(TOTAL_BOXES_COUNT); K(IN_BOX_COUNT); K(MAX_FUSION_STORAGE);
K(EVOLUTIONS_END); K(EVO_NONE);
K(SAVEBLOCK_MOVE_RANGE);
K(SPECIES_EGG);
K(NUM_TASKS); K(CONTEXT_SHUTDOWN); K(STATE_WAIT_ACTION_CHOSEN);
K(STATE_WAIT_ACTION_CONFIRMED_STANDBY); K(B_ACTION_NOTHING_FAINTED);
K(BATTLE_TYPE_LINK); K(BATTLE_TYPE_TRAINER); K(BATTLE_TYPE_DOUBLE);
K(B_OUTCOME_WON); K(B_OUTCOME_LOST); K(B_OUTCOME_DREW); K(B_OUTCOME_RAN); K(B_OUTCOME_CAUGHT);
K(STAT_ATK); K(FLAG_BADGE01_GET); K(SPECIES_SHEDINJA); K(MAX_LEVEL);
K(ID_NUMBER); K(IWRAM_START); K(IWRAM_END);
K(SE_FAINT); K(SE_FLEE); K(SE_BOO); K(SE_SUCCESS); K(SE_FAILURE); K(SE_SHINY);
E(Item); E(ItemSortType); E(Species); E(Move); E(Ability); E(Type); E(EggGroup);
E(NationalDexOrder); E(BattleMoveEffects); E(DamageCategory); E(Pocket); E(BattlerId); E(BattleTrainer);
K(MON_DATA_SPECIES); K(SAVE_NORMAL); K(SAVE_STATUS_OK);
