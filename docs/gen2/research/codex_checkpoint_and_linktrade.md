# Gen 2 checkpoint and link-trade source receipt

Card `gen2-C3`, task `cx-02b0f4b5`. Codex worker; Claude coordinator. Exclusive write: this file. Read-only primary-source research, no implementation or emulator. Tickets 10 and 13 were read, not edited. Independent review and ledger updates belong to the coordinator.

## Pins and verdict

- **C** throughout means **pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651** (`pokecrystal@7a7881d`).
- **G** throughout means **pokegold@656583c939d30f920a316177311a502dd222b57c** (`pokegold@656583c`).
- Both supplied `scratchpad/pret_head` clone HEADs were reverified. All C/G file:line citations below refer to those exact pins. SLink comparison inputs were read at worktree HEAD `4bf0f3bb1cf7659e76d890d02c185a530e30f7e9`.

**Ticket 10: source-supported candidate, live qualification remains OPEN.** Prefer a synchronous, caller-bound execution checkpoint in the ordinary overworld input path; a frame-boundary IRQ checkpoint is also derivable but has a different stack from Gen 1. No isolated WRAM byte proves all requested ownership conditions. The execution path plus conservative predicates is the proposed proof shape, not a release-qualified predicate.

**Ticket 13: received-party writer and post-trade save LOCATED.** Both link modes converge on `LinkTrade` → `AddTempmonToParty` → `EvolvePokemon` → `SaveAfterLinkTrade`. The Time Capsule first converts received Gen 1 data into Gen 2 opponent-party staging. A receptionist/confirmation/animation analogue exists; bypassing one receptionist wait is not a complete serial takeover (C `engine/link/link.asm:35-41,125-188,1937-2044`; G `engine/link/link.asm:37,186,1780-1874`).

## A. Overworld checkpoint

### Control flow, and why a single byte is insufficient

`OverworldLoop` dispatches `wMapStatus` through a jump table: StartMap, EnterMap, HandleMap, done (C/G `engine/overworld/events.asm:3-21`). There is no `DoOverworldFunction` symbol in either supplied checkout: full source search returned no matches; the current equivalent dispatch is the `rst JumpTable` at `OverworldLoop.loop`. Do not invent a site under the old name.

`HandleMap` updates time/input, runs the command queue and map events, verifies map status, updates objects, waits, then updates background/player state (C `engine/overworld/events.asm:140-155`; G `:138-153`). `MapEvents` runs PlayerEvents and then ScriptEvents (C `:157-175`; G corresponding block following HandleMap). `PlayerEvents` first rejects nonzero `wScriptRunning`, then checks trainer, tile, memory, scene and time events before `OWPlayerInput` (C `:241-278`; G `:238-275`). Thus an input-path site after these checks is narrower than a generic HandleMap/DelayFrame entry.

The script VM has distinct OFF/READ/WAIT_MOVEMENT/WAIT modes, and its SCRIPT_RUNNING bit is a **per-dispatch loop flag**. WaitScript and WaitScriptMovement call StopScript while a logical script still exists; zero SCRIPT_RUNNING alone therefore does not prove no script (C `engine/overworld/scripting.asm:3-55,239-252`; G `:3-55,231-244`). Script_end's final return clears `wScriptRunning` and sets mode OFF (C `:2252-2265`; G `:2142` onward). `wMapEventStatus` controls whether map events/input processing occurs and also depends on player stepping; it is not a menu-open flag (C `engine/overworld/events.asm:193-200,215-232`; G `:191-198` and subsequent CheckPlayerState).

The requested timer symbol is **`wGameTimerPaused`**, not `wGameTimerPause`. Bit 0 set means **timer counting**, despite the variable name; the timer also rejects `wGameLogicPaused != 0` (C/G `home/game_time.asm:25-37`, `constants/ram_constants.asm:30`; declarations C `ram/wram.asm:127,1832`, G `:117,2613`). Neither timer condition proves UI ownership.

### Recommended anchor 1: synchronous main-thread input boundary

**Primary candidate:** the `call CheckAPressOW` instruction within `OWPlayerInput`, C `engine/overworld/events.asm:495` / G `:483`. At this instruction, `PlayerMovement` has returned without carry and with A=0, and `CheckStandingOnIce` did not report ice (C `:485-495`; G `:473-483`). A/menu actions have not yet been dispatched. `OWPlayerInput` is called from PlayerEvents only after its higher-priority events fail (C `:250-265`; G `:247-262`). Source search found one call site in each events implementation; the generator should preserve that assertion.

Recommended capture/hold contract (design inference from those instructions):

1. Admit the exact cartridge/build. Resolve the instruction from the title's full symbols and pin surrounding source assertions and canonical ROM bytes. On **every** attempt recheck admitted ROM hash, flat-ROM bytes, mapped-System-Bus bytes, exact PC, actual ROM bank and WRAM bank. Use `hROMBank` (C `ram/hram.asm:29`; G `:26`), not Gen 1's `hLoadedROMBank` name; verify it agrees with the emulator's mapped bank. Require the bank containing Events, and bank 1 for `$Dxxx` data on GBC. No numeric bank/address is claimed until built.
2. At that exact instruction, before it executes, verify the WRAM/HRAM predicate table below and the immediate caller return word: the instruction after `call OWPlayerInput` in PlayerEvents (C `engine/overworld/events.asm:265-266`; G `:262-263`). Require the actual stack allocation bounds, not a guessed common stack range (C `ram/wram.asm:1-5`; G `:2923-2925`). Read fixed expected words; do not search the stack for a plausible return address.
3. Commit only while this exact synchronous checkpoint is held, or use it to establish a separately verified held CPU state. A boolean remembered until the next frame is **not** this grant: the next instruction can initiate text, menu or another event. No CPU register/stack corruption, no executing arbitrary game code in an IRQ callback. Sound execution needs its own calling convention and return witness.

This site is preferable to the entry of `GetJoypad`: input polling is earlier than event decisions and is also used outside normal overworld input (C `engine/overworld/events.asm:193-200,250-265`; `home/text.asm:891,968`). This is a restrictive idle-input checkpoint, not a promise of availability on every movement frame.

### Recommended anchor 2: Gen 1-shaped halted-frame checkpoint, conditional

For a writer that can only operate at an emulator frame boundary, the source-derived candidate is the **specific** chain:

`HandleMap` → `NextOverworldFrame` → `DelayFrames` → `DelayFrame.halt` → VBlank IRQ.

C calls are at `engine/overworld/events.asm:152,185-191`; G `:150,183-189`; both `home/delay.asm:1-20` contain the same DelayFrames loop. `NextOverworldFrame` returns immediately if `wOverworldDelay == 0`, so this candidate need not exist every loop. This is a source-derived stack recipe, **not measured frame-boundary behavior**:

| Fixed stack word at pre-handler IRQ entry | Required return location |
| --- | --- |
| `[SP]` | instruction immediately after `DelayFrame.halt`'s HALT, i.e. its NOP (C/G `home/delay.asm:8-9`) |
| `[SP+2]` | instruction after `call DelayFrame` in DelayFrames (C/G `home/delay.asm:17-18`) |
| `[SP+4]` | instruction after `call DelayFrames` in NextOverworldFrame (C `engine/overworld/events.asm:190-191`; G `:188-189`) |
| `[SP+6]` | instruction after `call NextOverworldFrame` in HandleMap (C `:152-153`; G `:150-151`) |

Require PC exactly `$0040` **before** the vector jump/handler pushes, `wVBlankOccurred == 1`, all eight bytes within the title's stack bounds, Events mapped as the caller's ROM bank, correct WRAM bank, plus the predicate table. The vector is `jp VBlank` (C `home/header.asm:43-44`); VBlank immediately pushes AF/BC/DE/HL (C/G `home/vblank.asm:9-13`), so checking after that prologue changes the stack and must fail this shape. DelayFrame sets a **WRAM** flag via `ld [wVBlankOccurred],a`, then HALT/NOP, unlike Gen 1's HRAM load/store shape (C/G `home/delay.asm:3-12`). Never copy Gen 1's `DelayFrame+5` or two-word expectation. Exact resume bytes/addresses, PC-at-frame behavior, IRQ conditions and stack presence must be measured for each admitted core/title before enabling this alternative.

Reverify ROM anchors for the vector, DelayFrame body, DelayFrames call, NextOverworldFrame call and HandleMap call every time. Also verify the complete scope/byte lengths of the mapped ROMX anchors. SLink's comparison implementation is `lua/gen1_write_safety.lua:54-70` (per-attempt anchors), `:71-78` (ownership), `:79-105` (PC/stack); `data/games/gen1_rby/write_checkpoint.json:1-25` is a shape reference only. For Gen 2 the source does not prove that a post-events frame wait excludes every staged command/movement; retain this candidate as OPEN until the negative matrix passes. Anchor 1 is the stronger source-local recommendation.

### Conservative predicate set

These values are a **proposed conjunction at an exact anchor**, not free-running polling authorization. Unknown/unreadable bytes, changed ROM, unexpected PC/bank/caller, or a stale epoch refuse the write. The stronger optional rejections can reduce availability; relax only after source and live evidence.

| Field | Proposed required value | Source meaning / limitation |
| --- | --- | --- |
| `wMapStatus` | `MAPSTATUS_HANDLE = 2` | C `constants/ram_constants.asm:180-184`, `engine/overworld/events.asm:129-132,146-149`; G constants `:170-174`, events `:138-147`. Excludes startup/entry/done. |
| `wMapEventStatus` | `MAPEVENTS_ON = 0` | C constants `:186-189`, events `:193-196,215-232`; G constants `:176-179`. Not independently a no-menu predicate. |
| `wScriptRunning` | `0` | C events `:241-246`, declaration `ram/wram.asm:2924`; G events `:238-243`, declaration `:2311`. |
| `wScriptMode` | `SCRIPT_OFF = 0` | C constants `:207-212`, scripting `:2257-2264`; G constants `:197-202`, scripting `:2142` onward. Reject WAIT even if dispatch bit clear. |
| `wScriptFlags` | `(flags & $04) == 0`; conservatively also reject `$08` pending/deferred marker | C constants `:191-196`, scripting `:239-252`, events `:426-441`; G constants `:181-186`, scripting `:231-244`. Deferred bit can outlive a momentary dispatch; its rejection needs a liveness check, not an assertion that all ordinary play has flags==0. |
| `wScriptStackSize` | `0` | C declaration `ram/wram.asm:2928`, scripting `:2276-2303`; final endall clears it at `:2306-2314`. Reject nested script context. |
| `wJoypadDisable` | `0` (strict) | C/G `home/joypad.asm:29-32` actually masks faint/SGB/bit4 to disable input. Rejecting all nonzero bits is conservative; zero is not sufficient to prove player ownership. Declarations C `ram/wram.asm:1839`, G `:2619`. |
| `wGameLogicPaused` | `0` | C/G `home/joypad.asm:35` onward and `home/game_time.asm:29-32`; declarations C `ram/wram.asm:127`, G `:117`. |
| `wInputType` | `0` for the strict profile; never `AUTO_INPUT=$FF` | C/G `home/joypad.asm:127-131`, `constants/ram_constants.asm:1-2`; `GetJoypad` can use an automated stream. C `home/joypad.asm:253-262` StopAutoInput restores zero for normal input. Only treating all non-$FF values as safe would broaden the contract unnecessarily. |
| `wBattleMode` | `0` | C `ram/wram.asm:2720`, `engine/battle/core.asm:8294-8299`; G declaration `:2186`, cleanup after `engine/battle/core.asm:7965`. Wild/trainer values are 1/2 (C `constants/battle_constants.asm:84-87`). Do not use a nonexistent Gen 1 `wIsInBattle` field. |
| `wStateFlags` | scripted-movement bit 7 clear | C constants `ram_constants.asm:109`, scripting `:44-49`; G constants `:103`. Anchor 1 additionally passes the movement/ice branches. |
| `hMapEntryMethod` | `0` | C `engine/overworld/events.asm:129-130`, declaration `ram/hram.asm:31`; G HRAM `:28`. Reject warp/entry lifecycle. |
| `wLinkMode`, serial status | `LINK_NULL=0`, `hSerialConnectionStatus=$FF`, no active serial transfer | C `constants/serial_constants.asm:3,23-26`; C `engine/link/link.asm:2303-2365,2579-2595`; G `:2158` and `:2405-2421`. These supplement the caller proof; require neither pending trade transaction nor serial-owner lease. Hardware transfer state must be rechecked by the admitted emulator binding. |
| `wGameTimerPaused` | bit 0 set may be an additional strict rejection gate; **not** the ownership oracle | C/G constants `ram_constants.asm:30`, `home/game_time.asm:34-37`. Other bits/full-byte value are not inferred; normal timer activity can occur in menus. |

No proven universal textbox-open/menu-open WRAM bit is claimed here. The proposed absence-of-UI proof comes from the narrow execution/caller path, supported by the predicates, then challenged by live controls. `wWindowStackSize` exists (C `ram/wram.asm:1743`, G `:1373`) but existence does not establish a reliable zero/no-menu invariant; do not add it unqualified. A lingering rendered textbox or asynchronous command is explicitly an unresolved negative-control case for a parked-frame implementation.

### DelayFrame, Joypad and native sound

`Joypad` itself is an interrupt placeholder containing `reti`; `UpdateJoypad` runs from VBlank, while `GetJoypad` copies/automates the input consumed by game logic (C/G `home/joypad.asm:1-17,106-131`). Therefore a hook at `Joypad` is not a main-thread input hook. Main-thread `GetJoypad` under `HandleMapTimeAndJoypad` is a possible sound-service observation, but only with its verified caller and an appropriate reentrancy/return contract; it is not the write checkpoint above (C events `:193-201`; G `:191-199`).

Do **not** import “menus never reach DelayFrame”: Crystal's party-menu route within StartMenu explicitly calls it (C `engine/menus/start_menu.asm:501-519`), and text waits call GetJoypad/DelayFrames (C `home/text.asm:891-896,968-973`). Generic DelayFrame/UpdateJoypad hits can occur while UI or interrupts own execution. Native sound must retain main-thread provenance and a separate reviewed ABI, rather than treating a generic wait as an arbitrary cartridge-code execution grant.

### False positives and required live gate

A false positive can write while PC/naming/menu buffers retain older copies, race a save/box load, or alter party records while battle/evolution/trade routines are staging them. Source examples of competing owners: post-trade AddTempmonToParty copies records/names (C/G `engine/pokemon/move_mon.asm:396-444`), ChangeBoxSaveGame saves then loads active storage (C `engine/menus/save.asm:39-54`; G `:40` onward), and scripts/menu input use paths above. The result could be lost writes, duplicate/deleted records, or a faint/link applied to the wrong identity. These are risk deductions, not reproduced failures.

Minimum live matrix, for each admitted title/core, with all writes disabled during predicate measurement:

- Positive idle overworld before/after input; return from a text box/START menu; verify bounded reacquisition. Record PC/SP, fixed stack words, ROM/WRAM banks and all predicate bytes on every candidate acceptance.
- **Inside textbox:** opening, scrolling, waiting A/B, closing; include a script `waitbutton` and a standalone text wait. No grant at generic DelayFrame/GetJoypad hits.
- **Inside START menu:** list, party, bag, Pokémon stats, save confirmation, options, nested naming/PC screens. No grant until ownership returns.
- **Inside battle:** intro, selection, animation, faint, end/evolution, can-lose and whiteout. No overworld grant.
- **Warp fade:** before fade, map-byte writes, map setup, spawn/Continue, connection scroll. No grant until completed ownership boundary.
- **Elm scene:** approach/forced movement, dialogue, starter choice/naming, aide/potion, final scene return; test paused movement and script wait where SCRIPT_RUNNING bit can be clear but mode remains WAIT.
- Automated input/ice/ledge/scripted movement, pending phone/deferred scene, Cable Club receptionist and in-room trade, save/reset/state load. Corrupt one anchor/caller/bank/byte read and require refusal; prove a cached prior acceptance cannot survive reset/ROM change.

These are unrun qualification controls. The first falsifier is any acceptance while one of the requested negative contexts owns execution; do not run an unchanged failed live scenario repeatedly.

## B. Received Pokémon and native trade

### Receptionist, confirmation and serial boundaries

The cartridge has the requested analogue: trade receptionist YES/NO, save YES/NO, native room entry, selected-mon trade/cancel choice and player-specific animations. C `maps/PokeCenter2F.asm:69-104` performs unlock check, YES/NO, cable/mobile selection, SetBitsForLinkTradeRequest, WaitForLinkedFriend, save confirmation/TryQuickSave, timeout and room compatibility checks. G `maps/PokeCenter2F.asm:59-88` is the cable analogue without Crystal mobile selection. Time Capsule uses compatibility checks before its wait/save/entry (C `maps/PokeCenter2F.asm:298-334`; G `:189` onward). Room scripts call `special TradeCenter` / `special TimeCapsule` (both C/G `maps/TradeCenter.asm:38`, `maps/TimeCapsule.asm:38`).

TradeCenter sets LINK_TRADECENTER and TimeCapsule sets LINK_TIMECAPSULE before calling LinkCommunications (C `engine/link/link.asm:2579-2599`; G `:2405-2425`). LinkCommunications branches to Gen2ToGen1LinkComms for Time Capsule, otherwise Gen2ToGen2LinkComms (C `:35-41`; G `:35-39`).

**Takeover feasibility: source analogue CONFIRMED; complete takeover UNVERIFIED.** A session-owned bridge would have to intercept before the receptionist serial wait initiates the physical handshake: SetBitsFor…/WaitForLinkedFriend and CheckLinkTimeout_Receptionist/room mode checks, with confirmed ownership and refusal/cancel behavior preserved. WaitForLinkedFriend drives rSB/rSC and tests internal/external clock states in a loop (C `engine/link/link.asm:2303-2369`; G `:2158` onward). Crystal's VC hook comment at C `:2339-2347` explicitly describes faking connection status at that point; that is evidence of one interception boundary, **not** proof that setting a status byte implements a trade.

Further interception is mandatory for payload exchange (C `:83-103,258-279`), patched-data reconstruction, selections/trade-cancel exchange (C `:1761-1800`), and post-animation synchronization (C `:2025-2044`; G `:1855-1874`). A bridge that bypasses only the first wait can hang, select the wrong peer mon, or commit divergent records. Any proposed companion takeover must supply validated staging data and acknowledgments consistently on both participants; source reachability alone does not qualify dual animations, serial emulation or recovery. No patches were designed/applied by this card.

### Staging and conversion are not local-party commit

| Path | Source flow |
| --- | --- |
| Trade Center, Gen 2 peer | Serial exchange writes `wLinkReceivedPartyData`, exchanges patch lists and (for Trade Center) mail, reconstructs `wLinkPlayerPartyData`, then copies into opponent staging `wOTPlayerName`, `wOTPartyCount`, `wOTPlayerID`, `wOTPartyMons`. C `engine/link/link.asm:258-295,448-463`; G `:257,289-294,429-431`. The misleading-sounding `wLinkPlayerPartyData` is a buffer name, not a local party commit. |
| Time Capsule, Gen 1 peer | Receives into `wLinkReceivedPartyData`, checks received count, copies `wLinkTimeCapsulePartyData`, restores serial patch bytes, translates species using ConvertMon_1to2, then calls Link_ConvertPartyStruct1to2 to fill opponent-party structures. C `engine/link/link.asm:91-103,112-188,1032` onward; G `:90,111,186,936` onward. This is a conversion boundary, not bitwise Gen 2 record transport. |

Both then reach the same selection/LinkTrade mutation path (C `engine/link/link.asm:1702` and subsequent mutation; G `:1555`). Names changed at HEAD, so hook generation should use the actual HEAD symbols, not infer the local writer from an older union name.

### Exact local write sequence

1. **Before removing anything**, capture outgoing slot `wCurTradePartyMon` and incoming selected index `wCurOTTradePartyMon`. LinkTrade copies animation identity fields, then moves outgoing selection into `wCurPartyMon` and calls RemoveMonFromPartyOrBox with REMOVE_PARTY. The original selected slot is compacted away; the received mon is later appended, not written back into that same slot (C `engine/link/link.asm:1900-1955`; G removal at `:1780`; writer append below).
2. The native code selects TradeAnimation or TradeAnimationPlayer2 based on serial clock role (C `:1969-1976`; G `:1802-1806`). At `.done_animation`, it restores the incoming opponent slot, sets wCurPartySpecies from opponent species list, copies the 48-byte opponent record to wTempMonSpecies, then calls **`AddTempmonToParty`** (C `:1978-1994`; G `:1808-1824`).
3. **Actual writer:** C/G `engine/pokemon/move_mon.asm:396-444` checks capacity, increments party count, appends species/terminator, copies `PARTYMON_STRUCT_LENGTH` from wTempMonSpecies to final party slot, then copies selected opponent OT name and nickname into the corresponding name arrays. `:446-478` updates caught/seen, sets non-egg BASE_HAPPINESS, handles Unown and returns success with carry clear. The record copy alone at `:420` is too early for a complete received-record witness. Pin the successful return or call-return after AddTempmonToParty, preserving caller context and observing its result.
4. LinkTrade sets `wCurPartyMon = wPartyCount-1` and calls **EvolvePokemon** (C `engine/link/link.asm:1995-1998`; G `:1825-1828`). Therefore acquisition receipt and final post-evolution identity are separate observations. Capture after the successful add, then after successful/canceled evolution completion; do not attribute every species change to the trade without the session latch.
5. It synchronizes the post-trade check byte, then calls **SaveAfterLinkTrade** for both modes. Time Capsule skips part of the special-species comparison, but still reaches `.save` (C `:2025-2044`; G `:1855-1874`). A “Trade completed!” display follows the save (C `:2047-2055`; G `:1875-1882`). The persistent receipt should be after successful save return, not merely after the animation or AddTempmonToParty.

High confidence in these source boundaries. Dual-machine temporal ordering, disconnect/timeout atomicity, actual SRAM persistence to the host, and all Time Capsule conversion edge cases remain untested.

### SaveAfterLinkTrade: exactly what is saved

C `engine/menus/save.asm:26-37` and G `:27-38` do: PauseGameLogic; StageRTCTimeForSave; BackupMysteryGift; SavePokemonData; SaveChecksum; SaveBackupPokemonData; SaveBackupChecksum; BackupPartyMonMail; SaveRTC; ResumeGameLogic. There is **no SaveBox, SavePlayerData or SaveBackupPlayerData call in this routine**. This is a specialized post-trade save, distinct from receptionist TryQuickSave → Link_SaveGame (C `engine/link/link.asm:2536-2551`, `engine/menus/save.asm:63-72`; G TryQuickSave at `engine/link/link.asm:2362`).

The exact source-defined SRAM intervals below are half-open. Symbolic lengths avoid pretending that an unbuilt HEAD has verified numeric addresses. SRAM placement is C `layout.link:362-378`, G `layout.link:286-304`; definitions C `ram/sram.asm:8-55,58-103`, G `:14-70,87-104,137-173`.

| Operation | SRAM writes / checksum reads | Source |
| --- | --- | --- |
| Primary Pokémon data | bank 1 `[sPokemonData, sPokemonData + (wPokemonDataEnd-wPokemonData))` | C `engine/menus/save.asm:511-519`; G `:409-417`. Includes the entire Pokémon-data block, not just the traded slot. |
| Backup Pokémon data | bank 0 `[sBackupPokemonData, sBackupPokemonData + (wPokemonDataEnd-wPokemonData))` | C `:573-581`; G `:485-493`. |
| Primary checksum | Recompute 16-bit sum of bank 1 `[sGameData,sGameDataEnd)`; write two bytes `[sChecksum,sChecksum+2)` | C `:526-537,1087-1100`; G `:424-435,1038` onward. Both games recompute; they do not incrementally patch only the mon bytes. |
| Crystal backup checksum | Recompute bank 0 `[sBackupGameData,sBackupGameDataEnd)`; write `[sBackupChecksum,sBackupChecksum+2)` in bank 0 | C `:583-594`, `ram/sram.asm:58-74`. |
| Gold/Silver backup checksum | Sum bank 0 ranges starting `sBackupPlayerData3` length `wPlayerData3End-wPlayerData3`, `sBackupPokemonData` length `wPokemonDataEnd-wPokemonData`, `sBackupPlayerData1` length `wPlayerData1End-wPlayerData1`; bank 1 `sBackupPlayerData2` length `wPlayerData2End-wPlayerData2`; bank 3 `sBackupCurMapData` length `wCurMapDataEnd-wCurMapData`. Write two bytes at bank 3 `sBackupChecksum`. | G `engine/menus/save.asm:495-536`; `ram/sram.asm:66-70,137-139,167-173`. Do not substitute Crystal's contiguous backup span. |
| Mystery Gift backup | bank 0 `sBackupMysteryGiftItem` and `sNumDailyMysteryGiftPartnerIDs`, sourced from sMysteryGiftItem and sMysteryGiftUnlocked | C `engine/link/mystery_gift.asm:1374-1387`; G same routine at `:1217`; SRAM labels in the bank-0 declaration. |
| Mail backup | bank 0 `[sPartyMailBackup,+PARTY_LENGTH*MAIL_STRUCT_LENGTH)` and `[sMailboxCountBackup,+1+MAILBOX_CAPACITY*MAIL_STRUCT_LENGTH)` | C/G `engine/pokemon/mail.asm:239-250`. Sources are live SRAM mail/mailbox records; actual trade also modifies live mail before append (C `engine/link/link.asm:1802` onward). |
| RTC | Clears the RTC day-high carry bit through mapped RTC registers and writes bank-0 `sRTCStatusFlags=0` | C/G `engine/rtc/rtc.asm:76-89`. StageRTCTimeForSave first updates WRAM wRTC (`:63-74`); do not call that alone a full saved-player-data commit, since this specialized routine does not call SavePlayerData. C wRTC is declared at `ram/wram.asm:3011`, outside wPokemonData `:3411-3499`. |

Crystal's caller additionally calls trainer-ranking stub and BackupGSBallFlag immediately after SaveAfterLinkTrade (C `engine/link/link.asm:2044-2046`; BackupGSBallFlag is `mobile/mobile_41.asm:515`). Those are caller-side effects, not silently part of the specialized save routine. No claim here equates SRAM mutation with a flushed host save file.

## Verification, reuse and handoff

Read both ticket bodies and the Gen 1 checkpoint JSON/Lua shape; verified both pret HEADs with per-command read-only safe-directory overrides; inspected source and compared named C/G entry points. No code, ticket, source checkout or emulator state changed. No executable tests were requested or appropriate for this single-document research cut. The proposed negative matrix above remains unrun.

Documentation checks: `git diff --check -- docs/gen2/research/codex_checkpoint_and_linktrade.md` produced no findings; because the file is untracked, its contents were also scanned independently and had zero trailing-whitespace lines. Lease-restricted status: `?? docs/gen2/research/codex_checkpoint_and_linktrade.md`.

Reuse decision: reuse shared admission/anchor validation, bounded event capture, epoch retirement, transaction ownership and transport where compatible. Game adapters own Gen 2 call chains, script-state meanings, serial formats, conversion rules and save spans. The Gen 1 PC/stack constants and Joypad assumption are **not reusable facts**. Independent review: pending coordinator's separate reviewer. Next action: reconcile source findings into tickets 10/13, choose execution versus parked-frame checkpoint, then generate canonical anchors and run the bounded gate before any write authorization.

## Open questions

- Can the chosen emulator safely hold/commit at the synchronous input instruction, or must the writer use a frame-boundary IRQ checkpoint? Measure both; source alone cannot prove the emulator's exposed PC/stack boundary.
- Does the strict predicate regain liveness after deferred scenes, menus, phone events and auto-input? In particular, deferred flag rejection may conservatively stall; do not weaken it by guesswork.
- Which exact byte slice/CPU bank/register assumptions at each anchor survive the admitted patch set? Need canonical ROM and symbol artifacts at these HEADs, per-title build outputs and per-call rejection controls.
- Can every textbox/menu/warp/Elm-scene negative be excluded while allowing ordinary idle play, including asynchronous command queue ownership? No universal UI flag was established in this audit.
- Native-trade takeover still needs a reviewed two-sided protocol: receptionist handshake, room/session identity, payload/patch/mail conversion, selected indices, cancel/timeout/replay, both animations, post-evolution identity and save acknowledgment. Existing source analogy does not prove a one-byte handshake bypass is safe.
- What host save-RAM flush and crash/reconnect receipt follows cartridge SaveAfterLinkTrade? A source call returning is not physical disk durability or proof both peers committed.
