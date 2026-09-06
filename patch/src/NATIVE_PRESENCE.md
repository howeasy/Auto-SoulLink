# RR presence resource slice — live acceptance still required

This change fixes the verified graphics-template and palette-reference defects without growing
the existing 44-byte GhostState or allocating from the disputed adjacent EWRAM gaps. It does not
establish arena ownership, complete surf/effect presentation, motion quality, or general release
readiness. The isolated probe candidate is described by its generated native manifest.

## Pinned engine evidence

All addresses below were checked against clean RR MD5 `8529f3a45d32bce4da637976fcf269d4`.
Local CFRU/pret source supplies names and struct interpretations; it is not RR source.

| Interface | RR binary evidence |
|---|---|
| Template-taking spawn | `0x0805E7F4`: saves its template pointer from r0, obtains camera offsets, calls `0x0805E72C`; returns u8 OE ID |
| Full graphics ID | `0x0805E752..0x0805E75A`: loads template bytes 1 and 3, combines them before graphics lookup; hook at `0x0805E150` copies high byte to OE `+0x23` |
| Graphics lookup | `0x0805F2C8` redirects to `0x0907E500`; switcher literal is `0x091468CC`, bank zero `0x08EB1000` |
| Palette acquire | `AddPalRef(u8 type,u16 tag)` at `0x0908FA08`; selects a free type-zero entry and writes type/tag |
| Reference increment | `0x0908F968`: increments the slot's count byte at `+1`, returns its slot |
| Reference release | `0x0908FB3C`: decrements nonzero count; clears type/tag when count reaches zero |
| Palette table | Both count helpers reference `0x0203B7D4`; 16 entries of `{u8 type,u8 count,u16 tag}` |
| Sprite destruction | `0x08007280` redirects to `0x09042594`; `0x090425A0..A4` reads CURRENT paletteNum then decrements that reference |
| Dummy destructor branch | The same hook skips palette decrement when sprite.template is `0x08231D00`; the remaining destructor still frees tiles using sprite.images->size |
| Object removal | `0x0805E4B4` **does clear OE.active**, then its internal routine derives allocation size from graphics info and destroys the sprite. Earlier comments claiming it never cleared active were inaccurate |
| Tint classifier | `0x0909001A..1E` bounds the type switch to 1..4; other values use default zero. Built-in palette types are 0..5 |

The old parameterized helper at `0x0805E830` leaves template byte 3 uninitialized. The new
wrapper initializes all 24 bytes, including script/flags, writes both graphics bytes, applies
the same map-border offset conversion, and calls the template-taking entry directly. Its local
zeroing uses volatile byte stores so the freestanding compiler does not introduce `memset`.

## Ownership and lifetime

`rr_presence_engine.h/.c` own the verified engine wrappers and resource checks. A ghost obtains
a private reference through RR's allocator, then transfers paletteNum and releases exactly the
engine-acquired original reference. Private type **6** separates partner-painted colors from
built-in NPC/generic lookup. The private slot retains the engine's **real palette tag**, allowing
reflection lookup to resolve a valid ROM palette instead of a fabricated tag. The existing C
tint pass handles the private palette; complete tint/visual behavior remains a live gate.

The old hardcoded slot 15 writes are gone. Active field objects must have registered palette
references before a new presence allocation proceeds, so a palette-only reset cannot make the
ghost borrow a slot still displayed by an unregistered field object. No-capacity or inconsistent
allocator state defers the ghost instead of repurposing another object's reference.

Only existing storage is repurposed:

- GhostState bytes 18/19: desired/current graphics high byte.
- GhostState bytes 41/42/43: cached palette slot, sprite ID, lifecycle.
- An owned ghost sprite's `data[6]`: original tile-allocation byte count.
- Its `data[7]`: owner marker `0x534C`; `data[0]` remains the engine OE ID.

Sprite data is used only after replacing the movement callback with the inert native ghost
callback. Animation processing does not consume these general-purpose data words. Other engine
movement callbacks do use them, so ownership requires the exact callback, marker, valid allocation
size, active sprite and matching OE ID. Data from an engine-reconstructed sprite is not trusted.

Normal cleanup uses the recorded original allocation size rather than a peer-repointed image
table. The destructor reports which private reference it consumed, preventing a second decrement
when a child still shares that palette. If the palette was already freed/reused, the verified
dummy-template branch prevents touching its new owner. Cached private references discarded by
bulk sprite reset are retired separately; a private orphan slot is drained only when no live
sprite refers to it. Slots reassigned to built-in palette types are never decremented as ghosts.

When the engine reconstructs a ghost sprite on field return, SLink tears that fresh native object
down and waits an engine tick before spawning its own replacement. The same gap applies to
graphics changes and orphan collection, allowing attached engine effects to observe an inactive
parent. Non-field frames update only SLink lifecycle metadata. They never hide or rewrite a
retained sprite slot. The PC trade NPC uses initialized templates and checked ordinary engine
cleanup; presence-OFF PC mode retires the partner ghost before claiming interaction ownership.

## Lua and wire boundary

Lua publishes desired position/avatar state only. `peer_ghost_npc.lua` no longer writes sprite
images, animation state, OAM palette number, subpriority or live palettes. Palette-only and
animation-pointer changes are forwarded. Spawn does not erase the avatar staged in the same
frame. Failed mailbox requests are not latched as successfully requested ghosts.

`ghost_pos.gfx` is an integer 0..65535, read from OE low byte `+5` and high byte `+0x23`.
The sender broadcasts only under the verified field callback, even though the broader client
continues polling native menus/trades outside it. The receiver rejects malformed coordinates,
graphics IDs and avatar palette/pointers instead of converting them into a default player.
`PG.set_enabled(false)` clears cached presence and rejects stale incoming positions while disabled.

`MB.ghost_spawn(gfx16)` sends opcode 14 args `{low,0xF0,high}`. The opcode only updates desired
state; the field driver owns actual teardown/spawn. Existing palette-buffer staging remains in
its previous location. The C owner checks avatar pointers against the pinned graphics record and
bounds the ordinary animation's frame transfers to the original tile allocation. Unsupported
forward-jump/oversized animation programs are deferred for explicit validation, not guessed safe.

## Required isolated runtime cases

These are acceptance requirements, not results of the host-side tests:

1. Poisoned stack patterns and gfx IDs sharing low bytes; inspect all template fields, OAM
   dimensions, tile reservations and image-frame sizes.
2. Repeated normal spawn/despawn and graphics changes; palette type/tag/count and tile bitmap
   return to their expected baseline, including private slots other than 15.
3. Existing ghost into wild/trainer battle, party/bag, trade/evolution, door/map changes and
   whiteout; no non-field sprite writes and a clean reconstructed owner on return.
4. Bulk sprite reset with palette refs retained; palette reset with sprites retained; both
   reset; formerly owned slots reused by another object. No leak, double-decrement or repaint
   of another owner. Confirm the field allocator consistency guard recovers after rebinding.
5. Reflections and other attached effects across parent removal and reconstruction. Preserve
   live child references, free discarded ones, and verify the inactive-parent tick actually
   reaches their callbacks. Full surf/fishing effect support is separate remaining work.
6. Palette/OE/sprite/tile exhaustion and recovery; no fallback theft, invisible collision,
   repeated leaked allocations or interaction with an undrawn invalid avatar.
7. Different avatars, palette-only changes, running, and PC-NPC/presence toggles through the
   real two-player transport. Use video/screenshots plus resource assertions.

The binary/host tests validate contracts and Lua staging, not actual game resource lifetimes.
Live failures remain release blockers. The legacy A-key interaction interception still requires
its timing cases; initializing a template does not by itself prove map-template script lookup safe.
