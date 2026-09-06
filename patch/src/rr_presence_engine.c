#include "rr_presence_engine.h"
#define R8(a)  (*(volatile u8 *)(a))
#define R16(a) (*(volatile u16 *)(a))
#define R32(a) (*(volatile u32 *)(a))
#define OBJECTS 0x02036E38u
#define SPRITES 0x0202063Cu
#define PAL_REFS 0x0203B7D4u
#define DUMMY_TEMPLATE 0x08231D00u
#define NO_SPRITE 64u

typedef u8 (*SpawnTemplateFn)(const RRObjectTemplate *);
typedef u32 (*GraphicsFn)(u16);
typedef u8 (*AddPalFn)(u8, u16);
typedef u8 (*PalCountFn)(u8);
typedef void (*ReleasePalFn)(u8);
typedef void (*RemoveFn)(void *);
#define SpawnTemplate ((SpawnTemplateFn)0x0805E7F5u)
#define GetGraphics ((GraphicsFn)0x0805F2C9u)
#define AddPalRef ((AddPalFn)0x0908FA09u)
#define IncPalRef ((PalCountFn)0x0908F969u)
#define DecPalRef ((ReleasePalFn)0x0908FB3Du)
#define RemoveObject ((RemoveFn)0x0805E4B5u)
#define DestroySprite ((RemoveFn)0x08007281u)

static u8 rom_range(u32 address, u32 size)
{
    return address >= 0x08000000u && address < 0x0A000000u && size <= 0x0A000000u - address;
}

u32 rr_presence_graphics(u16 gfx)
{
    /* The pinned switcher has 255 entries. A table pointer must stay in ROM;
     * GetGraphics handles the native dynamic aliases and bank-zero fallback. */
    u8 bank = (u8)(gfx >> 8);
    if (bank != 0xFF) {
        u32 table = R32(0x091468CCu + (u32)bank * 4);
        if (table && !rom_range(table, 1024)) return 0;
    }
    u32 info = GetGraphics(gfx);
    if (!rom_range(info, 36) || (info & 3)) return 0;
    u16 size = R16(info + 6), width = R16(info + 8), height = R16(info + 10);
    if (!size || size > 2048 || (size & 31) || !width || width > 64 || !height || height > 64) return 0;
    if (!rom_range(R32(info + 0x10), 8) || !rom_range(R32(info + 0x18), 4)
        || !rom_range(R32(info + 0x1C), 8)) return 0;
    return info;
}

static u8 field_palettes_consistent(void)
{
    /* Do not allocate into a palette reset that has not yet rebound the active
     * field objects; their colors may still occupy slots marked free. */
    for (u8 i = 0; i < 16; i++) {
        u32 oe = OBJECTS + (u32)i * 0x24;
        if (!(R8(oe) & 1)) continue;
        u8 sid = rr_object_sprite(i, R8(oe + 8));
        if (sid >= NO_SPRITE) return 0;
        u8 pal = (u8)(R16(SPRITES + (u32)sid * 0x44 + 4) >> 12);
        u32 ref = PAL_REFS + (u32)pal * 4;
        if (!R8(ref) || !R8(ref + 1)) return 0;
    }
    return 1;
}

u8 rr_spawn_presence(u16 gfx, u8 movement, u8 local_id, s16 x, s16 y, u8 elevation)
{
    if (!field_palettes_consistent() || !rr_presence_graphics(gfx) || elevation > 15 || movement > 2) return 16;
    RRObjectTemplate t;
    volatile u8 *zero = (volatile u8 *)&t;
    for (u32 i = 0; i < sizeof(t); i++) zero[i] = 0; /* no freestanding memset dependency */
    t.local_id = local_id;
    t.graphics_lo = (u8)gfx; t.graphics_hi = (u8)(gfx >> 8);
    t.x = x - 7; t.y = y - 7; /* parameterized helper's map-border conversion */
    t.elevation = elevation; t.movement = movement;
    t.range = movement ? 0x11 : 0;
    return SpawnTemplate(&t);
}

u8 rr_object_sprite(u8 oe_id, u8 local_id)
{
    if (oe_id >= 16) return NO_SPRITE;
    u32 oe = OBJECTS + (u32)oe_id * 0x24;
    if (!(R8(oe) & 1) || R8(oe + 8) != local_id) return NO_SPRITE;
    u8 sid = R8(oe + 4);
    if (sid >= NO_SPRITE) return NO_SPRITE;
    u32 sprite = SPRITES + (u32)sid * 0x44;
    if (!(R8(sprite + 0x3E) & 1) || R16(sprite + 0x2E) != oe_id) return NO_SPRITE;
    return sid;
}

u8 rr_palette_private_owned(u8 slot)
{
    if (slot >= 16) return 0;
    u32 ref = PAL_REFS + (u32)slot * 4;
    return R8(ref) == RR_PRIVATE_PAL_TYPE && R8(ref + 1) > 0;
}

u8 rr_private_palette_acquire(u8 original_slot)
{
    if (original_slot >= 16) return 0xFF;
    u32 original = PAL_REFS + (u32)original_slot * 4;
    if (!R8(original) || !R8(original + 1)) return 0xFF;
    for (u32 i = 0; i < 16; i++) {
        u32 candidate = PAL_REFS + i * 4;
        if (R8(candidate) == 0) {
            if (R8(candidate + 1) != 0) return 0xFF; /* inconsistent engine allocator state */
            break;
        }
    }
    /* Keep a real ROM palette tag for engine reflection lookup, but isolate the
     * type namespace so NPC/generic lookups cannot share partner-painted colors. */
    u8 slot = AddPalRef(RR_PRIVATE_PAL_TYPE, R16(original + 2));
    if (slot >= 16) return 0xFF;
    IncPalRef(slot);
    if (!rr_palette_private_owned(slot)) { DecPalRef(slot); return 0xFF; }
    return slot;
}

void rr_palette_release(u8 slot)
{
    if (slot < 16) DecPalRef(slot);
}

u8 rr_ghost_sprite_owned(u8 oe_id, u8 local_id, u32 callback)
{
    u8 sid = rr_object_sprite(oe_id, local_id);
    if (sid >= NO_SPRITE) return NO_SPRITE;
    u32 sprite = SPRITES + (u32)sid * 0x44;
    u16 size = R16(sprite + RR_GHOST_ALLOCATION_OFFSET);
    if (R32(sprite + 0x1C) != (callback | 1) || R16(sprite + RR_GHOST_MAGIC_OFFSET) != RR_GHOST_SPRITE_MAGIC
        || !size || size > 2048 || (size & 31)) return NO_SPRITE;
    return sid;
}

u8 rr_place_ghost(u8 oe_id, u8 local_id, u32 callback,
                  s16 x, s16 y, u8 elevation, u8 visible)
{
    /* RR checks previousCoords even when an object is not moving. Updating
     * currentCoords alone leaves collision at the old spawn/placement tile. */
    if (R32(0x030030F4u) != 0x080565B5u || elevation > 15 || visible > 1) return 0;
    u8 sid = rr_ghost_sprite_owned(oe_id, local_id, callback);
    if (sid >= NO_SPRITE) return 0;
    u32 oe = OBJECTS + (u32)oe_id * 0x24;
    u32 sprite = SPRITES + (u32)sid * 0x44;
    R16(oe + 0x10) = (u16)x; R16(oe + 0x12) = (u16)y;
    R16(oe + 0x14) = (u16)x; R16(oe + 0x16) = (u16)y;
    R8(oe + 0x0B) = (u8)(elevation | (elevation << 4));
    if (visible) R8(sprite + 0x3E) &= (u8)~0x04u;
    else R8(sprite + 0x3E) |= 0x04u;
    return 1;
}

u8 rr_adopt_ghost_sprite(u8 oe_id, u8 local_id, u32 callback, u8 *palette_slot)
{
    u8 sid = rr_object_sprite(oe_id, local_id);
    if (sid >= NO_SPRITE) return 0;
    u32 sprite = SPRITES + (u32)sid * 0x44;
    u8 old = (u8)(R16(sprite + 4) >> 12);
    if (rr_ghost_sprite_owned(oe_id, local_id, callback) < NO_SPRITE) {
        if (!rr_palette_private_owned(old)) return 0;
        *palette_slot = old; return 1;
    }
    u32 oe = OBJECTS + (u32)oe_id * 0x24;
    u16 gfx = (u16)(R8(oe + 5) | ((u16)R8(oe + 0x23) << 8));
    u32 info = rr_presence_graphics(gfx);
    if (!info) return 0;
    u8 fresh = rr_private_palette_acquire(old);
    if (fresh >= 16) return 0;
    /* Initialize the private colors before exposing the slot. Partner colors may
     * not have arrived yet; the engine's valid native avatar remains a safe stand-in. */
    for (u32 i = 0; i < 32; i++) {
        R8(0x020373F8u + (u32)fresh * 32 + i) = R8(0x020373F8u + (u32)old * 32 + i);
        R8(0x020377F8u + (u32)fresh * 32 + i) = R8(0x020377F8u + (u32)old * 32 + i);
        R8(0x05000200u + (u32)fresh * 32 + i) = R8(0x05000200u + (u32)old * 32 + i);
    }
    /* Commit the new ownership before releasing the engine-acquired reference. */
    R16(sprite + 4) = (u16)((R16(sprite + 4) & 0x0FFF) | ((u16)fresh << 12));
    R16(sprite + RR_GHOST_ALLOCATION_OFFSET) = R16(info + 6);
    R16(sprite + RR_GHOST_MAGIC_OFFSET) = RR_GHOST_SPRITE_MAGIC;
    R32(sprite + 0x1C) = callback | 1;
    rr_palette_release(old);
    *palette_slot = fresh;
    return 1;
}

u8 rr_remove_presence(u8 oe_id, u8 local_id, u32 callback, u8 *released_private)
{
    if (released_private) *released_private = 0xFF;
    u8 sid = rr_object_sprite(oe_id, local_id);
    if (sid >= NO_SPRITE) return 0; /* a real NPC/reused sprite is never ours to free */
    u32 oe = OBJECTS + (u32)oe_id * 0x24, sprite = SPRITES + (u32)sid * 0x44;
    if (rr_ghost_sprite_owned(oe_id, local_id, callback) < NO_SPRITE) {
        struct { u32 data; u16 size, pad; } frame = {0, R16(sprite + RR_GHOST_ALLOCATION_OFFSET), 0};
        u8 pal = (u8)(R16(sprite + 4) >> 12);
        /* RR's destructor decrements CURRENT paletteNum. If that reference was
         * externally cleared/reused, its verified dummy-template branch skips the
         * decrement; tiles still free using our original allocation size. */
        if (!rr_palette_private_owned(pal)) R32(sprite + 0x14) = DUMMY_TEMPLATE;
        else if (released_private) *released_private = pal;
        R32(sprite + 0x0C) = (u32)&frame;
        R8(oe) &= (u8)~1u;
        DestroySprite((void *)sprite);
    } else {
        /* Fresh engine sprite after field reconstruction: its ordinary palette
         * and graphics allocation have not been overridden by this owner. */
        u8 pal = (u8)(R16(sprite + 4) >> 12);
        if (rr_palette_private_owned(pal) && released_private) *released_private = pal;
        RemoveObject((void *)oe);
    }
    return 1;
}

void rr_release_private_orphan(u8 slot)
{
    if (!rr_palette_private_owned(slot)) return;
    for (u8 i = 0; i < 64; i++) {
        u32 sprite = SPRITES + (u32)i * 0x44;
        if ((R8(sprite + 0x3E) & 1) && (R16(sprite + 4) >> 12) == slot) return;
    }
    /* Bulk sprite resets can discard all references without individual destructors.
     * Only the private namespace with no live sprite references can be drained. */
    for (u32 i = 0; i < 255 && rr_palette_private_owned(slot); i++) DecPalRef(slot);
}

u8 rr_avatar_fits(u32 images, u32 anims, u8 animation, u16 allocated_size)
{
    if ((images & 3) || (anims & 3) || !rom_range(images, 8) || !rom_range(anims, 4 * ((u32)animation + 1))) return 0;
    u32 script = R32(anims + (u32)animation * 4);
    if ((script & 1) || !rom_range(script, 4)) return 0;
    /* Bound every frame in the ordinary linear/looping animation, not just
     * frame zero. Forward-jump/oversized programs are deferred for explicit RE. */
    for (u32 i = 0; i < 64; i++) {
        if (!rom_range(script + i * 4, 4)) return 0;
        s16 command = (s16)R16(script + i * 4);
        if (command == -1) return 1;
        if (command == -2) return R16(script + i * 4 + 2) <= i;
        if (command == -3) { if (i == 0) return 0; continue; }
        if (command < 0) return 0;
        u32 frame = images + (u32)command * 8;
        if (!rom_range(frame, 8)) return 0;
        u16 size = R16(frame + 4);
        if (!size || size > allocated_size || !rom_range(R32(frame), size)) return 0;
    }
    return 0;
}
