# FireRed PC flow and storage completion sites

Research card `gen3-P3-R9`, task `cx-444537b2`; SOURCE only. SLink source cut examined: `690409d17423e66fde87489bde12c2f9e77aaaef`. Exclusive output: this file. No Python, emulator, game-state changes, or other file edits.

Citation convention: **P/** means `E:/Google Drive/SLink/.cache/pret/pokefirered/`; other paths are relative to this worktree. That clone's `git rev-parse HEAD` returned `c75f352304d529f6ba92d4f74b9cf8b5c3810788`, matching `data/gen3_sources.lock.json:3-5`; `git status --short` returned no changes (only warnings about an inaccessible user ignore file). The symbol file's computed SHA-256 is `6f9d2929b78d0b723180653082c9a115b4b876657af8ab1c0493b4d14151f7b0`, matching `data/gen3/pret/provenance.json:173`. The receipt binds the source/agbcc commits at `:10-16` and FireRed ROM SHA-1 at `:168-170`. This investigation did not rebuild or rehash a ROM.

## A. PC input recipe

**Five separate A presses reach the storage main menu**, counting the initial interaction. This is a source-derived recipe with each message allowed to finish and each menu allowed to accept fresh input; it is not a fixed-frame timing guarantee. The three default message boxes each wait for a button; the PC selector itself contributes one selection, in addition to the initial interaction (`P/data/scripts/pc.inc:1-11,20-35,46-64`; `P/asm/macros/event.inc:1777-1781`; `P/data/scripts/std_msgbox.inc:18-22`; `P/src/scrcmd.c:1401-1408`).

Assumptions for this route: ordinary field interaction with a PC metatile, no quest-log playback, storage not disabled, Pokédex obtained, Bill's PC naming flag unset, game not cleared. The PC metatile selects `EventScript_PC`; that script separately handles quest-log and disabled-PC exceptions (`P/src/field_control_avatar.c:515-519`; `P/data/scripts/pc.inc:1-18`).

| Input / state | Vanilla FireRed result | Source |
|---|---|---|
| A #1: interact while facing PC | `{PLAYER} booted up the PC.` | `P/src/field_control_avatar.c:515-519`; `P/data/scripts/pc.inc:1-10`; `P/data/text/pc.inc:1-2` |
| A #2: dismiss boot message | `Which PC should be accessed?` with row 0 **SOMEONE'S PC**, row 1 **{PLAYER}'s PC**, row 2 **PROF. OAK's PC**, row 3 **LOG OFF**; cursor starts at row 0. The question uses `message`/`waitmessage`, not an additional button-wait message box. | `P/data/scripts/pc.inc:20-25`; `P/data/text/pc.inc:4-5`; `P/src/script_menu.c:1015-1034`; `P/src/strings.c:473-478` |
| A #3: choose row 0 | `Accessed Someone's PC.` | `P/data/scripts/pc.inc:28-30,46-49,58-60`; `P/data/text/pc.inc:7-8` |
| A #4: dismiss access message | `POKéMON Storage System opened.` | `P/data/scripts/pc.inc:48-50`; `P/data/text/pc.inc:10-11` |
| A #5: dismiss opened message | `ShowPokemonStorageSystemPC` creates `Task_PCMainMenu`; selection initially row 0. Wait for menu input readiness. | `P/data/scripts/pc.inc:50-52`; `P/src/pokemon_storage_system_menu.c:247-264,354-359` |
| Storage menu order | 0 **WITHDRAW POKéMON**; 1 **DEPOSIT POKéMON**; 2 **MOVE POKéMON**; 3 **MOVE ITEMS**; 4 **SEE YA!**. This is a separate menu from the PC-owner selector. | `P/include/pokemon_storage_system_internal.h:17-24`; `P/src/pokemon_storage_system_menu.c:37-43`; `P/src/strings.c:672-676` |

### Exact conditions changing the PC-owner list

| Condition | Effect / ordered list | Source |
|---|---|---|
| `FLAG_SYS_GAME_CLEAR` unset, `FLAG_SYS_POKEDEX_GET` unset | Three rows: storage owner's PC / player's PC / LOG OFF. The script's result-2 branch refuses Oak access without the Pokédex and turns the PC off. | `P/src/script_menu.c:1015-1034`; `P/data/scripts/pc.inc:28-35,86-87` |
| Game-clear unset, Pokédex set | Four rows: storage owner's PC / player's PC / PROF. OAK's PC / LOG OFF. This is the requested pre-Bill, Pokédex-obtained case when the naming flag is unset. | `P/src/script_menu.c:1015-1034`; `P/src/strings.c:473-478` |
| `FLAG_SYS_GAME_CLEAR` set | Five rows: storage owner's PC / player's PC / PROF. OAK's PC / HALL OF FAME / LOG OFF. This rendering branch takes precedence over the Pokédex-dependent item count. | `P/src/script_menu.c:1006-1034`; `P/src/strings.c:473-478` |
| `FLAG_SYS_NOT_SOMEONES_PC` unset versus set | Row 0 changes from SOMEONE'S PC to BILL'S PC; the accessed-PC message changes too. This flag does not add/remove menu entries. | `P/src/script_menu.c:1027-1030`; `P/data/scripts/pc.inc:48-49,58-64`; `P/data/text/pc.inc:7-8,16-17` |
| When vanilla sets Bill naming flag | The successful SS Ticket award path sets `FLAG_SYS_NOT_SOMEONES_PC`, after the item-space check and award. “Met Bill” is shorthand, not the exact test used by the PC. | `P/data/maps/Route25_SeaCottage/scripts.inc:94-106`; `P/include/constants/flags.h:1386` |

### Deposit and withdrawal sub-flows

These recipes use a fresh storage session's normal cursor mode, not the alternate quick/multi-move input path (`P/src/pokemon_storage_system_data.c:68-84,1252-1264,1513-1523`).

| Operation / input | Result and important qualifications | Source |
|---|---|---|
| Deposit: from fresh main menu, Down then A | Select DEPOSIT POKéMON. The main menu refuses when `CountPartyMons() == 1`. Otherwise it enters storage; deposit mode starts in party area at slot 0. | `P/src/pokemon_storage_system_menu.c:263-278,289-308,343-358`; `P/src/pokemon_storage_system_data.c:68-83` |
| Choose occupied party slot, A | Up/Down changes party slot; Down once from slot 0 selects slot 1. Normal A selection opens the selected-mon popup: **STORE / SUMMARY / MARK / RELEASE / CANCEL**. Empty slots do not produce this popup. | `P/src/pokemon_storage_system_data.c:1465-1478,1504-1516,1755-1772,1794-1806`; `P/src/pokemon_storage_system_tasks.c:935-951`; `P/src/strings.c:634-642` |
| A on popup row 0 STORE | Opens **Deposit in which BOX?** and a box chooser. This is NOT the actual deposit yet. Last usable non-egg protection and held-mail rejection precede the chooser. | `P/src/pokemon_storage_system_data.c:941-946,2110-2132`; `P/src/pokemon_storage_system_tasks.c:996-1005,1189-1199`; `P/src/strings.c:610` |
| Choose destination box with Left/Right if needed, A | Calls `TryStorePartyMonInBox(boxId)`. The chooser starts at box 0 on fresh entry and remembers successful choices during that session. B cancels. A full box gives an error and returns to box selection; success proceeds to party compaction and returns to storage selection. | `P/src/pokemon_storage_system_tasks.c:480-481,1201-1249`; `P/src/pokemon_storage_system_menu.c:463-485`; `P/src/pokemon_storage_system_data.c:658-681` |
| Withdraw: from fresh main menu, A on row 0 | Select WITHDRAW POKéMON. Full party is refused; non-deposit entry starts in the box area at slot 0. Choose an occupied box slot and press A. | `P/src/pokemon_storage_system_menu.c:289-296,343-358`; `P/src/pokemon_storage_system_data.c:68-83,1252-1255,1767-1771` |
| A on withdrawal popup row 0 | Popup order **WITHDRAW / SUMMARY / MARK / RELEASE / CANCEL**. WITHDRAW runs `Task_WithdrawMon`: checks capacity, grabs the boxed record, shows party, places the record, then hides party. There is no deposit-style destination-box confirmation in this path. | `P/src/pokemon_storage_system_data.c:1767-1771,1794-1805,2110-2132`; `P/src/pokemon_storage_system_tasks.c:991-995,1136-1186` |
| Completion assertion | A copied/zeroed record is observable before the whole UI settles. Deposit compacts party slots later; storage exit recomputes `gPlayerPartyCount`. Do not require the count byte to update at the transfer hook. | `P/src/pokemon_storage_system_tasks.c:1231-1242,1976-1982,2035-2041`; `docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt:63-65` |

### Cross-check against the existing RR PHYSICAL receipt

| Receipt fact | Comparison / boundary | Evidence |
|---|---|---|
| Five A inputs before storage menu | Consistent with the vanilla source recipe. RR log records A inputs ending at frames 2013, 2149, 2285, 2421, 2557. `ShowPokemonStorageSystemPC` and `Task_PCMainMenu` first fire at 2542 during the fifth input interval. No vanilla PHYSICAL run was performed here. | `docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt:18-27,48-49,60-61`; vanilla `P/data/scripts/pc.inc:10,20-24,46-64` |
| RR menu: Someone's PC / B's PC / Log Off | Vanilla with Pokédex obtained additionally has PROF. OAK's PC before LOG OFF. The three-row RR menu alone does not establish a hack change: vanilla without the Pokédex also has three rows. RR flag values/menu implementation are **UNVERIFIED** by this receipt. | `docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt:60`; `P/src/script_menu.c:1015-1034` |
| RR deposit input timeline | The note abbreviates the sub-flow. Raw log has A ending 3125 (selected mon), A ending 3261 (STORE/chooser), and A ending 3397 (commit box selection). `Task_DepositMenu` first fires at 3246, not on the initial storage-menu DEPOSIT choice; `TryStorePartyMonInBox` fires at 3381. This agrees with the extra box-chooser confirmation in vanilla. Exact intermediate RR screen text is **UNVERIFIED** by the text-only log. | `docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt:35-44,53-54,62-63`; `P/src/pokemon_storage_system_tasks.c:996-1005,1195-1214` |
| FR-offset functions execute on RR companion | The receipt observes `Task_PCMainMenu` at `0x0808C39C` (294 hits), `Task_DepositMenu` at `0x0808DD88` (135), and `TryStorePartyMonInBox` at `0x080930E4` (1). This establishes execution at unchanged entry addresses; it does not prove every body/callee is byte-identical to FR. | `docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt:49,53-54,58`; RR modifications at `data/games/gen3_rr/engine_signals.json:243-279,402-433` |

## B. Record-completion sites and the current pc_move row

**The current `pc_move` site is acquisition-to-storage, not a deposit/withdraw/release classifier.** Vanilla `GiveMonToPlayer` falls back to `SendMonToPC` when party is full; the latter copies the incoming boxed record into a free box slot. It does not implement the user storage-menu withdrawal or release path (`P/src/pokemon.c:3686-3740`; `data/games/gen3_frlg/engine_signals.json:300-329`). Both RR artifact rows explicitly retain that acquisition meaning (`data/games/gen3_rr/engine_signals.json:309-346,873-910`).

The current JSON already supplies **pc_deposit, pc_withdraw, pc_box_place, pc_release_begin, pc_release**; reuse those contracts rather than proposing duplicate new addresses. JSON `address` is the byte-anchor start; the registered hook is `address + capture_offset` (`lua/gen3/signals.lua:7,94,132`). Expected hex below is quoted from the current JSON at the anchor, not claimed as a fresh ROM dump. These remain SOURCE_BYTE_PIN contracts (`data/games/gen3_frlg/engine_signals.json:1-4`; `data/games/gen3_rr/engine_signals.json:1-4`).

### FR US 1.0 symbols, quoted verbatim

The following lines are copied from `data/gen3/pret/pokefirered.sym:2348,2364,2396,6103,6106-6107,6125,6163-6165,6318,6320-6322,6324,6328,6336` respectively (file identity verified above):

```text
0803d994 g 0000007e ZeroMonData
0803e774 g 00000050 BoxMonToMon
08040b90 l 000000aa SendMonToPC
0808bbb4 g 00000040 SetBoxMonAt
0808bcb4 g 0000003c ZeroBoxMonAt
0808bcf0 g 00000040 BoxMonAtToMon
0808c39c l 0000030c Task_PCMainMenu
0808dc9c l 000000ec Task_WithdrawMon
0808dd88 l 00000144 Task_DepositMenu
0808decc l 000001f0 Task_ReleaseMon
08092ef4 l 00000060 PlaceMon
08092f60 l 00000074 SetMovedMonData
08092fd4 l 0000005c SetPlacedMonData
08093030 l 00000028 PurgeMonOrBoxMon
080930e4 g 00000090 TryStorePartyMonInBox
08093218 g 0000004c ReleaseMon
080937dc g 0000009c CompactPartySlots
```

| Kind / data flow | Completion hook and capture conditions | Exact existing FR byte pin / evidence |
|---|---|---|
| Party → box deposit: `TryStorePartyMonInBox` finds a free slot. Selected-party branch calls `SetMovedMonData` (party → moving buffer, then zero origin), then `SetPlacedMonData` (restore PP, call `SetBoxMonAt`; actual boxed assignment). Carried-mon branch places the already carried record. | **0x08093164 = TryStorePartyMonInBox +0x80**, common return after writes, before register restoration. Require **R0 == 1**; R6 = box, R4 carries slot in high byte. Keep origin identity/context: the carried-mon branch alone does not prove party origin. | `pc_deposit`: anchor **0x0809315C**, offset **8**, hex `012175F715F9012070BC02BC08470000`. `data/games/gen3_frlg/engine_signals.json:271-299`; `P/src/pokemon_storage_system_data.c:613-642,658-681`; `P/src/pokemon_storage_system.c:73-76` |
| Box → party withdraw: `Task_WithdrawMon` runs CHANGE_GRAB then CHANGE_PLACE. `SetMovedMonData` converts box → moving buffer through `BoxMonAtToMon`/`BoxMonToMon`, purges the source box, and saves origin. `PlaceMon` calls the party branch of `SetPlacedMonData`. | **0x08092FF8 = SetPlacedMonData +0x24**, after the 100-byte party copy. Require FR **R6 == 14**, R7 valid party slot, and box-origin/caller correlation. Party placement is shared with party rearrangement/shift; the primitive alone is not a withdrawal classifier. The moving flag is cleared later by `PlaceMon`. | `pc_withdraw`: anchor **0x08092FF2**, offset **6**, hex `642252F140FF12E0`. `data/games/gen3_frlg/engine_signals.json:385-411`; `P/src/pokemon_storage_system_tasks.c:1136-1186`; `P/src/pokemon_storage_system_data.c:586-642,644-655`; `P/src/pokemon_storage_system.c:104-107` |
| Confirmed release: `Task_ReleaseMon` calls `ReleaseMon` after permission/confirmation. It purges a party/box record, or clears the moving flag when the record was already picked up. | Snapshot identity at **0x08093218** entry (`pc_release_begin`); completion **0x08093256 = ReleaseMon +0x3E**, after purge/flag clear and before display refresh. Pair the two: the zeroed record cannot identify the released mon. Release is not party → box. | Begin anchor/hook **0x08093218**, offset **0**, hex `00B5FDF757FF03490878002804D00020`; completion anchor **0x08093250**, offset **6**, hex `101CFFF7EDFE00F0DBFB01BC0047`. `data/games/gen3_frlg/engine_signals.json:330-384`; `P/src/pokemon_storage_system_tasks.c:1255-1305`; `P/src/pokemon_storage_system_data.c:636-642,716-733` |
| MOVE POKéMON box placement: `PlaceMon` and `SetShiftedMonData` also call `SetPlacedMonData`. This covers manual placement beyond the STORE dialog. | **0x08093020 = SetPlacedMonData +0x4C**, after `SetBoxMonAt`. Require **R6 < 14**, R7 < 30, and saved origin. Classify cross-boundary transfer versus box rearrangement/shift; deduplicate against `pc_deposit`. Common epilogue also receives the party branch. | `pc_box_place`: anchor **0x08093018**, offset **8**, hex `301C391CF8F7CAFDF0BC01BC0047`. `data/games/gen3_frlg/engine_signals.json:243-270`; `P/src/pokemon_storage_system_data.c:586-605,625-655` |
| Existing acquisition-to-PC `pc_move` | FR **0x08040C30 = SendMonToPC +0xA0**, common return; discriminate success from failure with the return contract. This does not distinguish or substitute for the three user PC operations above. | Anchor **0x08040C2C**, offset **4**, hex `BFD1022008BC9846F0BC02BC0847`. `data/games/gen3_frlg/engine_signals.json:300-329`; `P/src/pokemon.c:3686-3740`; symbol `data/gen3/pret/pokefirered.sym:2396` |

### RR clean and companion comparison

These comparisons read `titles.radical_red.artifacts.clean.sites` **and** `titles.radical_red.artifacts.companion.sites`; FR rows above read `titles.firered.artifacts.clean.sites`. No inference from only a top-level site name was used (JSON locations cited in every row).

| Kind | RR clean and companion current contract | Evidence / limitation |
|---|---|---|
| `pc_move` | Anchor **0x090B6E9A**, offset **6**, hook **0x090B6EA0**; hex `00F0EDF90120F8BD01351E2DD7D10134`. This is the compressed acquisition-to-PC return, **R0=1 success / 2 failure**, with box/slot meaningful on success. | `data/games/gen3_rr/engine_signals.json:309-346,873-910`; this is not the vanilla SendMonToPC body. |
| `pc_deposit` | Same anchor **0x0809315C**, offset **8**, hook **0x08093164**, and anchor hex `012175F715F9012070BC02BC08470000` as FR; require successful return and origin correlation. | `data/games/gen3_rr/engine_signals.json:280-308,844-872`; entry execution only is in `docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt:54`. |
| `pc_withdraw` | Same anchor **0x08092FF2**, offset **6**, hook **0x08092FF8**, hex `642252F140FF12E0`, but **R6 == 25**, not FR's 14. `SetPlacedMonData` is modified in place. | `data/games/gen3_rr/engine_signals.json:402-433,966-997`; withdraw task was silent in the supplied receipt (`docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt:55`). |
| `pc_box_place` | Same anchor **0x08093018**, offset **8**, hook **0x08093020**, hex `301C391CF8F7CAFDF0BC01BC0047`; require **R6 < 25**, R7 < 30. Its `SetBoxMonAt` callee detours to **0x090B6CA4**, compresses, and writes a 58-byte record before the wrapper completes. | `data/games/gen3_rr/engine_signals.json:243-279,807-843`; matching wrapper bytes do not imply a vanilla storage representation. |
| `pc_release_begin` / `pc_release` | Same entry **0x08093218** and completion **0x08093256** as FR, with the same two anchor byte strings from the FR table. Preserve identity before purge and correlate completion. | `data/games/gen3_rr/engine_signals.json:347-401,911-965`; release is not in the receipt's observed function list (`docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt:47-55`). |

### Completion boundary, unknowns, and recommendation

| Issue | Conclusion / what settles it | Evidence |
|---|---|---|
| Record completion versus final party layout | The proposed existing sites are after copy/zero, but deposit compacts later and release compacts after its messages. `CompactPartySlots` copies survivors and zeros trailing slots; count refresh is on exit. Use the transfer snapshot immediately, then a separate settled observation for final slots/count. | `P/src/pokemon_storage_system_tasks.c:1231-1242,1307-1322,1976-1982,2035-2041`; `P/src/pokemon_storage_system_data.c:904-924`; RR receipt `docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt:63-65` |
| “Unchanged RR functions” | **Confirmed only at the cited entry addresses**, not whole bodies/callees. The existing pin explicitly describes modified sentinel and compressed callee. Full equivalence is **UNVERIFIED** and should not be claimed from an entry-hit census. | RR receipt `docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt:49,53-54`; `data/games/gen3_rr/engine_signals.json:243-279,402-433` |
| Exact runtime completion observations | **UNVERIFIED in this research.** No new ROM disassembly, live callback capture, or emulator test. Owner-lane deposit/withdraw/release runs must check byte guards, success/failure/cancel controls, origin identity, and post-copy/zero snapshots separately from final count. | Existing JSON declares `live_verified: false` (`data/games/gen3_frlg/engine_signals.json:1-4`; `data/games/gen3_rr/engine_signals.json:1-4`); supplied receipt's bounded coverage is `docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt:47-56`. |
| Reuse decision | Reuse the existing per-kind pins and capture-offset registration; do not reinterpret acquisition `pc_move` as generic user PC movement. Retain per-game sentinel/record facts in packs; shared observer machinery should consume these facts and operation context. | Current contracts `data/games/gen3_frlg/engine_signals.json:243-411`; `data/games/gen3_rr/engine_signals.json:243-433,807-997`; registration `lua/gen3/signals.lua:94,132`. |

Verification performed: read-only source-pin/status checks, PowerShell JSON traversal of both packs (including both RR artifacts), symbol SHA-256 comparison, 102 explicit citation-range checks, and verbatim comparison of all 17 quoted symbol lines. A separate read-only worker (`/root/storage_sites`, inline receipt under task `cx-444537b2`) corroborated section B, then reviewed this completed note without authoring it: **ACCEPT, no material corrections**; specifically checked five-A sequencing, extra box confirmation, completion arithmetic/guards, and RR evidence limits. First falsifiers were the actual PC script/menu ordering and whether `pc_move` called the user storage copy/zero paths; the evidence above rejects a generic `pc_move` interpretation and a STORE-without-box-confirmation recipe. Next action: coordinator reviews this note and routes any input-recipe or observer qualification work; no ledger, signal JSON, or runtime edits are part of this card.
