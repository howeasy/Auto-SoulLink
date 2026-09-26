# Radical Red bag runtime and save layout

Research card gen3-P3-R6, 2026-09-21. Only this note created; no ROM/save mutation, emulator, Python or commits. Binary: `patch/build/slink_RR.gba`, MD5 verified bf8e94a01c0aee0aa7eb37c7333329af. ROM offsets below were read with PowerShell ReadAllBytes/BitConverter/ToHexString. Upstream references use CFRU b637a27898b14e25dd24d0f69a3e302f0069deb8, fetched read-only in memory.

## Answer and fixture recipe

**Poké Balls live at fixed EWRAM 0x0203C354, 50 ItemSlots of four bytes each: little-endian u16 itemId, then raw little-endian u16 quantity. Poké Ball is item 4.** This is already the shipping RR profile (`lua/games/gen3_frlge.lua:311-314`: BAG_IN_EWRAM=true, BALL_POCKET_ADDR=0x0203C354, BALL_POCKET_ENC=false, count=50), not the vanilla SB1 pocket. The old client selects this absolute base in `lua/memory_gba.lua:1121-1132,1140-1155`.

One-line Lua **fixture-only** recipe, before opening/reopening the BAG, with slot 0 known empty:

```lua
assert(memory.read_u16_le(0x0203C354, "System Bus") == 0); memory.write_u16_le(0x0203C354, 4, "System Bus"); memory.write_u16_le(0x0203C356, 5, "System Bus") -- bytes 04 00 05 00
```

If nonempty, preserve it: locate an existing item-4 slot or an empty slot among the 50, rather than replacing arbitrary inventory. For an empty-pocket fixture, the next slot remains zero. Do this while the UI is closed: the UI has cached counts/list buffers, so an already-open list is not a reliable immediate readback (pinned `src/item.c:1233` onward, :1429-1442). Reopen, verify displayed quantity and use one ball, then perform an in-game save and reload. **Not physically tested by this card.**

## Runtime pointer table: binary confirmation

Pinned source [src/item.c:1161-1227](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/src/item.c#L1161-L1227) defines expansion directly: regular=450, key=75, balls=50. There is no EXPANDED_BAG conditional around this block. `config.h` has bag hide/disable and other item options, not a requirement to enable this runtime layout. Source constants give `sBagRegularItems=0x0203BB20`, key items immediately after 450 slots, and balls after another 75 slots: **0x0203BB20 + (450+75)*4 = 0x0203C354**. [include/global.h:485-489](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/include/global.h#L485-L489) defines the two-u16 ItemSlot.

RR's vanilla SetBagPocketsPointers entry at CPU **0x08099E44** / ROM **0x00099E44** is replaced by bytes **00480047355F0A09**: ldr/bx to **0x090A5F35**, even body **0x090A5F34**. This body copies the arrangement into **gBagPockets=0x0203988C** (pool word in ROM **0x010A5F50**); its source pointer is **0x09147E00**, advanced by 8 before copying (body bytes at ROM010A5F34: `06490A0010B5064B083313CB13C213CB13C213CB13C21B68136010BD`). Table payload at **ROM0x01147E08**:

| Runtime pocket | pointer | capacity | ROM pointer/count offset |
|---|---|---:|---|
| Items | 0x0203BB20 | 450 | 0x01147E08 / +4 |
| Key Items | 0x0203C228 | 75 | 0x01147E10 / +4 |
| Poké Balls | **0x0203C354** | **50** | **0x01147E18 / +4** |
| TM/HM | 0x0203C41C | 128 | 0x01147E20 / +4 |
| Berries | 0x0203C61C | 75 | 0x01147E28 / +4 |

Thus the dynamic alternative is `read_u32_le(0x0203989C)` (gBagPockets+0x10), with u32 capacity at +0x14 = 0x020398A0, after the engine has initialized the table. Do not treat an uninitialized table as a different bag layout. Symbol corroboration: `data/gen3/pret/pokefirered.sym:330,6586`; source struct field ordering `src/item.c:1196-1207`. The pocket byte range is **[0x0203C354,0x0203C41C)**.

Quantity is not merely raw because the currently observed encryption key happens to be zero. RR's GetBagItemQuantity at ROM **0x00099DA0** begins **00887047**, decoding `ldrh r0,[r0]; bx lr`, bypassing the vanilla XOR body. Its argument is a pointer to quantity (pret `E:/Google Drive/SLink/.cache/pret/pokefirered/src/item.c:21-28`). The RR profile independently sets BALL_POCKET_ENC=false (`lua/games/gen3_frlge.lua:313`). Do not apply SaveBlock2-key XOR to these fixture bytes.

## Poké Ball ID: table evidence, not only vanilla inheritance

Pinned [include/constants/items.h:7](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/include/constants/items.h#L7) defines ITEM_POKE_BALL=4; the separately named key item ITEM_POKE_BALL_KEY_ITEM is not this consumable (:880).

RR ItemId_GetPocket at CPU **0x0809A9D8** uses record stride **0x2C** and table pointer **0x093C0000**, read from ROM **0x0009A9F8** (body includes `2C21 4843 0019 807E`, multiply id by44 and load pocket byte+0x1A). Item4's record at **ROM0x013C00B0** is:

```text
CAE3DF1B00BCD5E0E0FF000000000400C8000000D04F3D080000030300000000020000001D1E0A0803000000
```

Its pocket byte+0x1A is **03**. The selected table plus pinned item-id definition corroborates item4 in the ball pocket; there is no evidence for renumbering it in this RR artifact. Full item-name character decoding was not required for the recipe.

## Save mapping: ball pocket is extension sector 30

The parasite occupies **0x0203B174..0x0203C038** (exclusive end), length0xEC4, split over spare tails of logical sections 0/4/13. Balls at0x0203C354 are **beyond that block**. Sources: `docs/gen3/research/rr_save_layout.md:117-142`, and pinned [src/save.c:19-24,119-146](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/src/save.c#L119-L146).

The next **0xFF0 bytes from RAM0x0203C038** are copied to physical flash sector **30**; the following block from0x0203D028 goes to sector31. Read/write code: [src/save.c:79-115](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/src/save.c#L79-L115); binary pool values for those bases were reread at ROM0x010B8C98 and0x010B8DEC (documented in rr_save_layout.md:119-128). Existing save evidence: rr_save_layout.md:144-155.

Therefore, by exact address subtraction:

```text
pocket offset in sector30 = 0x0203C354 - 0x0203C038 = 0x031C
raw .sav file start       = 30*0x1000 + 0x031C      = 0x1E31C
50-slot range            = [0x1E31C, 0x1E3E4)
first-slot bytes          = 04 00 05 00
```

This is physical sector30, not logical rotating section id30 and not one of the two 14-sector slots. The extension copies are shared, with no section signature/checksum metadata; do not invent or recompute a normal logical-section checksum for this edit (`rr_save_layout.md:146-155`; save.c:103-115 zeroes the buffer then copies0xFF0 data). In contrast, modifying SB1+0x430 edits the normal SaveBlock1 image and would involve its ordinary chunk checksum. Prefer runtime fixture injection plus the engine's save/reload witness; editing an arbitrary stale disk copy does not prove runtime usability.

The expanded bag as a whole straddles parasite and extension storage: regular-items start0x0203BB20 is before0x0203C038; key/ball/TM/berry pockets follow. Only the balls mapping is needed here. Do not place the whole expanded bag in logical sections0/4/13 based on the word “parasite.”

## What is SB1+0x430 now?

It is **not the live ball pocket**: RR's initialized pointer table explicitly chooses0x0203C354, and its profile bypasses SB1 for bag reads (evidence above). Upstream CFRU [include/global.h:766-769](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/include/global.h#L766-L769) places0x430 inside **filler_40A[0x4E]**, after expanded dex flags and before safeBackupParty at0x458. It no longer defines a ball ItemSlot array there.

**RR-specific non-bag use is UNVERIFIED:** RR can repurpose upstream filler. The pointer-table proof establishes that this is not the selected runtime inventory, not that arbitrary writes there are harmless. Do not reuse SB1+0x430 as scratch or keep the failed injection in a committed fixture without accounting for those bytes.

## NOT VERIFIED / coordinator checks

* Runtime readback of gBagPockets+0x10 / capacity+0x14 on the exact loaded state, displayed five-ball stack, successful throw/decrement, and persistence through save/reload remain coordinator PHYSICAL work.
* UI count/list refresh when already open is not guaranteed; inject before opening and reopen if needed. Preserve occupied slots and unrelated bytes.
* No claim that every upstream compile-time config matches RR, or that unused SB1 filler is unused by RR. Binary table and getter evidence above are specific to the admitted companion hash.
* Save offset derivation rests on the previously pinned extension mapping plus reread base literals; no new boot receipt was generated. No changes to ROM, fixtures or source code.
