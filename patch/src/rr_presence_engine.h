#ifndef SLINK_RR_PRESENCE_ENGINE_H
#define SLINK_RR_PRESENCE_ENGINE_H
#include "native_mailbox.h"

/* Pinned RR4.1 interfaces; binary evidence and lifetime constraints are documented
 * in NATIVE_PRESENCE.md. These are engine resources, not new SLink RAM allocations. */
typedef struct {
    u8 local_id, graphics_lo, in_connection, graphics_hi;
    s16 x, y;
    u8 elevation, movement, range, reserved;
    u16 trainer_type, trainer_range;
    u32 script;
    u16 flag_id, flag_id2;
} RRObjectTemplate;
_Static_assert(sizeof(RRObjectTemplate) == 24, "RR template ABI changed");
_Static_assert(offsetof(RRObjectTemplate, graphics_hi) == 3, "RR graphics high byte moved");
_Static_assert(offsetof(RRObjectTemplate, script) == 16, "RR script pointer moved");

#define RR_PRIVATE_PAL_TYPE 6u
#define RR_GHOST_SPRITE_MAGIC 0x534Cu
#define RR_GHOST_ALLOCATION_OFFSET 0x3Au /* Sprite.data[6], only under our inert callback */
#define RR_GHOST_MAGIC_OFFSET 0x3Cu      /* Sprite.data[7] */

u8 rr_spawn_presence(u16 gfx, u8 movement, u8 local_id, s16 x, s16 y, u8 elevation);
u32 rr_presence_graphics(u16 gfx);
u8 rr_object_sprite(u8 oe_id, u8 local_id);
u8 rr_palette_private_owned(u8 slot);
u8 rr_private_palette_acquire(u8 original_slot);
void rr_palette_release(u8 slot);
u8 rr_remove_presence(u8 oe_id, u8 local_id, u32 owned_callback, u8 *released_private);
void rr_release_private_orphan(u8 slot);
u8 rr_adopt_ghost_sprite(u8 oe_id, u8 local_id, u32 owned_callback, u8 *palette_slot);
u8 rr_ghost_sprite_owned(u8 oe_id, u8 local_id, u32 owned_callback);
u8 rr_place_ghost(u8 oe_id, u8 local_id, u32 owned_callback,
                  s16 x, s16 y, u8 elevation, u8 visible);
u8 rr_avatar_fits(u32 images, u32 anims, u8 animation, u16 allocated_size);
#endif
