# P4.5b phone-byte save census

SOURCE evidence only; physical ringing/save readback belongs to P4.5d. Pins:
Crystal (`C`) `pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651`;
Gold/Silver (`G`) `pokegold@656583c939d30f920a316177311a502dd222b57c`.
References below are in `.cache/gen2-build/{pokecrystal,pokegold}`, never `.cache/pret`.

The service accepts into WRAM0 `PHONE_ARMED`, arms native ID 9 only with the
phone card and no script/link activity, and withdraws its own ID on those
blocked paths. It never erases native story IDs 0-8. Physical WRAM bank 1 is required.
The native setter writes a word although readers inspect its low byte. Before
accepting a request, the overlay scrubs reserved IDs >=9 unless the word is
exactly `9/0` with valid live `PHONE_ARMED` ownership. Invalid ARMED values are
also cleared. It arms only `0/0`; foreign high padding for native IDs 0-8 stays intact.

## Exact sinks

| Title | WRAM byte | Primary SRAM | Backup SRAM | Byte-bearing copies |
|---|---|---|---|---|
| C | `01:DC31` | `01:A7BF` (CartRAM `27BF`) | `00:B9BF` (CartRAM `19BF`) | `SavePlayerData`, `SaveBackupPlayerData`: `engine/menus/save.asm:498-509,559-571` |
| G/S | `01:D97B` | `01:A7E3` (CartRAM `27E3`) | `00:B075` (CartRAM `1075`) | `SavePlayerData`, first `SaveBackupPlayerData` span: `engine/menus/save.asm:396-407,457-463` |

C derives the offset `$7B6` from `wPlayerData=$D47B`, copied to `$A009/$B209`.
G/S primary derives `$7DA` from `wPlayerData=$D1A1`; its split backup uses
`wPlayerData3=$D571`, not the first backup span's address arithmetic.
Mappings are from the corresponding committed `data/gen2/*.sym` and
`ram/sram.asm` (C:64-68,93-97; G:68,93-100).

The complete native call-path partition for those two sinks follows. A guard
is insufficient without a pre-copy `DelayFrame`; the table records the barrier.

| Entry/path | Guard and barrier before the byte copy | C source | G source |
|---|---|---|---|
| START SAVE / `SaveMenu` | `CallScript` retains `wScriptRunning`; saving text waits **16 frames** before `_SaveGameData` | `engine/overworld/events.asm:826-845`; `home/map.asm:925-935`; `engine/menus/save.asm:239-242,336-357` | `engine/overworld/events.asm:814-833`; `home/map.asm:1340-1350`; `engine/menus/save.asm:227-249` |
| PC Change Box / `ChangeBoxSaveGame` | `PCScript`; same **16-frame** saving barrier | `engine/events/std_scripts.asm:226-230`; `engine/menus/save.asm:39-55,336-357` | `engine/events/std_scripts.asm:184-188`; `engine/pokemon/bills_pc.asm:2403-2410`; `engine/menus/save.asm:40-55,227-249` |
| PC Move without Mail initial save | PC script; same **16-frame** barrier | `engine/menus/save.asm:117-126` | `engine/pokemon/bills_pc_top.asm:109-120`; `engine/menus/save.asm:116-125` |
| PC move insertion, final direct copies | PC script; **20 frames before transfer-branch dispatch**, then the direct save leaves | `engine/pokemon/bills_pc.asm:1925-1970`; `engine/menus/save.asm:98,103` | `engine/pokemon/bills_pc.asm:1903-1948`; `engine/menus/save.asm:98,103` |
| PC Party-to-Box direct `SaveGameData` | Same PC script and **20-frame pre-dispatch** barrier | `engine/pokemon/bills_pc.asm:1997-2001` | `engine/pokemon/bills_pc.asm:1975-1979` |
| Hall of Fame direct `SaveGameData` | Script remains active through native call; fade ends in **100 frames before save** | `engine/overworld/scripting.asm:2317-2333`; `engine/events/halloffame.asm:3-25,59-72` | `maps/HallOfFame.asm:45`; `engine/overworld/scripting.asm:2207-2221`; `engine/events/halloffame.asm:3-25,55-68` |
| Receptionist quick saves, including Battle Tower/mobile variants in C | Map-script special; `TryQuickSave`/`Link_SaveGame` use the **16-frame** barrier; no reliance on link mode already being set | `maps/Pokecenter2F.asm:90,151,192,319`; `maps/BattleTower1F.asm:84,172,211`; `engine/link/link.asm:2536-2539`; `engine/menus/save.asm:63-68,336-357` | `maps/Pokecenter2F.asm:73,134,210`; `engine/link/link.asm:2362-2377`; `engine/menus/save.asm:63-67` |
| C mobile battle `Function103780` | Map-script special reaches the same `Link_SaveGame` barrier | `maps/Pokecenter2F.asm:255`; `mobile/mobile_40.asm:7527-7546` | Not present |
| C mobile news interpreter `_SaveGameData` command | Command has no own delay; sole outer entry is registered special `Function17d2ce`, whose `FadeToMenu` yields before interpreter. No native map invokes this unused special in the pin | `mobile/mobile_5f.asm:510-531,1919-1958,2950-2967`; `data/events/special_pointers.asm:154`; `home/map.asm:1910-1917`; `engine/tilesets/timeofday_pals.asm:122-128,277-287` | Not present |
| CONTINUE primary-to-backup / backup-to-primary repair | **No clearing frame.** PlayerData is loaded from disk before copying it to the other save, without intervening DelayFrame. Requires the clean-input invariant below | `engine/menus/save.asm:596-624,734-754,789-800` | `engine/menus/save.asm:538-566,699-712,762-770,825-849,926-987`; `engine/pokemon/mail.asm:252-263`; `engine/link/mystery_gift.asm:1232-1245` |

`StopScript` is not script termination: it clears the dispatch flag, not
`wScriptRunning`. G `engine/overworld/scripting.asm:241-244,2142-2149,2196-2204`
distinguishes them. Native calls above return before termination.

## Other save/SRAM paths

| Path | Why it is not a phone-byte sink |
|---|---|
| `SaveAfterLinkTrade`, including the new scriptless SLink responder | Copies PokemonData, not PlayerData: C `save.asm:26-37`, G `:27-38`. C PokemonData starts `$DCD7`, G `$DA22`, after the respective phone byte. This disproves the old “every save is scripted” premise but does **not** itself persist the phone ID. The link-mode guard is additional defense. |
| Center/Elm healing | Healing/animation scripts, not PlayerData saves. G `std_scripts.asm:54-125`, `maps/ElmsLab.asm:252-276`; nurse `checkphonecall` follows pause/healing frames (G `std_scripts.asm:85-97`, C `:127`). |
| Ordinary Mystery Gift and its backup/restore | Dedicated SRAM fields. G `engine/link/mystery_gift.asm:1217-1245`; C `:1374-1387`. Identity/name reads from PlayerData do not copy the phone field back. |
| Boxes, Hall-of-Fame records, mail, RTC/GS Ball flags, Battle Tower/rankings, debug identity/dex/event/item writes | Separate intended SRAM destinations; no additional transport of the phone byte was found. Checksum routines read the enclosing span but write checksum fields, not the phone byte. |
| Crystal `_SaveData` | Not `_SaveGameData`: seven bytes at `01:BE3D` and the two-byte `$A60E` alias, outside `$A7BF`; C `engine/menus/save.asm:829-853`. |
| Delete save / `EmptyAllSRAMBanks` | Covers these addresses but writes **zero**, not transient WRAM 9; C `engine/menus/empty_sram.asm:1-15`, G `:1-19`. |

## Boundary

This is a preventive, inductive argument starting with a native/untainted save
(native special IDs are 0-8). No such input gains a saved ID 9 through this
build's phone feature. Contaminated inputs could instead come from external
RAM/SRAM edits, deliberately modified test saves, or a defective third-party
or experimental overlay; no previously released SLink build is asserted to
have produced them.

A checksum-valid preexisting disk ID 9 is faithfully copied by CONTINUE before
withdrawal can run. Thus this build can **propagate existing disk contamination**
during repair even though it does not manufacture it from clean inputs. The
first bank-1 phone-service pass scrubs an unowned reserved ID in WRAM, protecting
subsequent patched-game dispatch. It does not rewrite existing SRAM copies;
those become clean only after a normal full save. This is runtime defense,
not an imported-save migration guarantee.

Clean native code has **no upper-bound check** before `(id-1)*6` lookup and
indirect condition call (C `engine/phone/phone.asm:242-256`, G `:249-263`). An
out-of-range saved ID therefore treats non-table bytes as a function pointer;
clean-ROM portability is unsafe for such a contaminated file. Do not describe
it as repaired merely because the patched game's WRAM was scrubbed.
Arbitrary external mobile bytecode and unrelated pointer corruption are also
outside the native call-path census.

P4.5d must still read SRAM after a real save with `PHONE_ARMED != 0`, check native
call precedence, and exercise battle/menu/reset transitions on each title.
