# Emerald in-battle bag: driving a Poké Ball throw from RAM (SOURCE research)

Source: headless OMP cx-6e4bea59 (read-only, pret pokeemerald @ c65e93f2). The coordinator spot-checked these
against pret and `data/gen3/pret/pokeemerald.sym`:
- `BALLS_POCKET 1` and `POCKET_POKE_BALLS 2` (`include/constants/item.h:7,13`);
- the pocket-switch wrap (`src/item_menu.c:1303-1310`);
- the syms `gBagPosition 0x0203CE58` (0x1C), `gBagMenu 0x0203CE54` (pointer), `gBagPockets 0x02039DD8` (0x28),
  `CB2_BagMenuRun 0x081AAD5C`, `Task_BagMenu_HandleInput 0x081ABD28`, `Task_ItemContext_SingleRow 0x081ACC04`,
  `BattleMainCB2 0x08038420`, `gActionSelectionCursor 0x020244AC`.

None of this is PHYSICAL yet. The E2 capture leg proves it or corrects it.

## Differences from FR that break a port
- There is no static `gBagMenuState`. The bag is `CB2_Bag` → `CB2_BagMenuRun`, driven by one input task whose `func` is the
  state. `gBagMenu` is a heap pointer.
- The balls pocket index is `BALLS_POCKET = 1`. Pocket order: ITEMS 0, BALLS 1, TMHM 2, BERRIES 3, KEYITEMS 4.
  `gBagPockets` is 1-based (`POCKET_POKE_BALLS = 2`).
- The pocket switch WRAPS, and the bag reopens on the last pocket. Steer by reading `gBagPosition.pocket`
  (+0x05) until it equals 1. Never count presses.
- `struct BagPocket` holds an `itemSlots` POINTER, not an inline array. Only `quantity` is XOR-masked with the SB2
  `encryptionKey`.
- SELECT swaps items in battle. Never send it.

## Predicate sequence (function pointers carry the Thumb bit: compare against sym|1)
| # | Step | Wait predicate | pret |
|---|---|---|---|
| 0 | action menu | `gMain.callback2 == BattleMainCB2|1`; `gActionSelectionCursor[battler] == 1` before A | battle_controller_player.c:230-256 |
| 2 | bag input-ready | `callback2 == CB2_BagMenuRun|1`, `!gPaletteFade.active`, and a task with `func == Task_BagMenu_HandleInput|1` | item_menu.c:746-747,774-779,1217 |
| 3 | pocket | `u8[gBagPosition+0x05]` read until it is 1. Press one RIGHT at a time, and between presses wait for the task func to return from `Task_SwitchBagPocket` | item_menu.c:1284-1310,1352-1393 |
| 4 | row 0 | `u16[gBagPosition+0x12+2p] + u16[gBagPosition+0x08+2p] == 0` (the value is live every frame) | item_menu.c:1213-1214,1245 |
| 6 | context menu | task `func == Task_ItemContext_SingleRow|1` and `u8[*gBagMenu+0x828] == 2` ({USE, CANCEL}, cursor on USE) | item_menu.c:312-314,1679-1688 |
| 7 | USE | balls-pocket quantity decrements | item_use.c:938-947 |
| 8 | throw committed | `callback2 == BattleMainCB2|1`, no bag task left, `gLastUsedItem == ITEM_POKE_BALL` | battle_main.c:4413; battle_util.c:318-322 |
| 9 | caught | `gBattleOutcome == B_OUTCOME_CAUGHT (7)` | constants/battle.h:106 |

Open: the byte offset of `gPaletteFade.active` (read it from `include/palette.h`, which the checkpoint uses as +7 mask 0x80);
whether `itemId` is plaintext (inferred).
