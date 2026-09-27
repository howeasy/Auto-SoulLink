/* X3 harness compiler-data probe (the X1 probe's method, tools/expansion_offsets.c): the struct
 * offsets/constants the live harness and the make-exp fixture seed use on the expansion
 * reference build, compiled with the ROM's own pipeline and never executed.
 * tools/gen_expansion_harness_facts.py reads the ELF32 object (x1_ symbols, same parser).
 * No numeric struct offset appears here.
 */
#include "global.h"
#include "item_menu.h"
#include "constants/item.h"
#include "constants/items.h"
#include "constants/pokeball.h"
#include "x1_source_enums.h" /* the facts pipeline always generates it */
#include "x3_pc_options.h"   /* the PC main-menu enum, copied verbatim from the pinned .c by the generator */

#define SZ(t) static const u32 x1_size__##t USED = sizeof(struct t); \
    static const struct t x1_zero__##t USED = {0}
#define F_AS(t, label, f) static const u32 x1_field__##t##__##label[] USED = \
    {offsetof(struct t, f), sizeof(((struct t *)0)->f)}
#define F(t, f) F_AS(t, f, f)
#define A(t, f) static const u32 x1_array__##t##__##f[] USED = \
    {offsetof(struct t, f), sizeof(((struct t *)0)->f), sizeof(((struct t *)0)->f[0])}
#define K(k) static const u32 x1_const__##k USED = (k)

/* the battle-bag ball throw (gen3_scripted_play.lua emerald_throw_ball) */
SZ(BagPosition);
F(BagPosition, pocket); A(BagPosition, cursorPosition); A(BagPosition, scrollPosition);
SZ(BagMenu);
F(BagMenu, contextMenuNumItems);
K(POCKET_POKE_BALLS); K(POCKETS_COUNT); K(ITEM_POKE_BALL); K(BALL_POKE);

/* the make-exp SYNTH seed's SaveBlock1/2 fields (tools/gen3_fixtures.py build_exp_seed) */
SZ(SaveBlock1);
F(SaveBlock1, pos); F(SaveBlock1, location); F(SaveBlock1, continueGameWarp);
F(SaveBlock1, lastHealLocation); F(SaveBlock1, mapLayoutId); F(SaveBlock1, money);
F(SaveBlock1, bag); F(SaveBlock1, flags);
SZ(SaveBlock2);
F(SaveBlock2, playerGender); F(SaveBlock2, specialSaveWarpFlags);
A(SaveBlock2, playerTrainerId); F(SaveBlock2, encryptionKey);

/* the PC main-menu rows (src/pokemon_storage_system.c; their order follows OW_PC_MOVE_ORDER) */
K(OPTION_WITHDRAW); K(OPTION_DEPOSIT); K(OPTION_MOVE_MONS); K(OPTION_MOVE_ITEMS); K(OPTION_EXIT);
