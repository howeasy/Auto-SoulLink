# Independent review: Gen 2 P4 companion overlay asm (2026-09-24)

Reviewer: Claude Opus (non-author). Read-only review. No emulator was run and no vision was used.
Every finding comes from source (SOURCE) and is **not live-verified** unless it says otherwise.

**Subject.** `patch/gen2/src/*.asm` plus the source edits made by `tools/build_gen2_companion.py`:
DelayFrame bridge, Reset latch, START row, receptionist pointer and the two phone `ld hl` loads.
Published overlays at d09e76c1: C 651dc6bf, G d563669e, S 76c6c112, caps 31. The working-tree
`trade_service.asm` edit that the brief mentions landed during the review as **67143736**
(C 265401fa / G 4a3d1977 / S 942060ee). Section 4 covers it.

**Vanilla references.** `.cache/gen2-build/pokecrystal` @7a7881d (cited as `C`) and
`.cache/gen2-build/pokegold` @656583c (cited as `G`). Symbols come from the clean `.sym`/`.map`
files and from the overlay `data/gen2/{crystal,gold}_slink.{sym,map}`.

---

## 1. Findings

### BLOCKER-1: A responder trade during the Bug-Catching Contest corrupts the party and saves it

- **Where:** `trade_dispatch.asm:30-54`. The pickup gates check SVBK, script mode, battle, link,
  paused, hInMenu, hVBlank and mapstatus. They have **no contest gate**. `trade_commit.asm:88`
  (RemoveMon), `:123` (AddTempmon) and `:157` (SaveAfterLinkTrade) complete the chain.
- **Vanilla facts:** `ContestDropOffMons` hides party members 2-6. It sets `wPartyCount = 1` and
  overwrites `wPartySpecies[1]` with `$FF`, keeping the real byte in
  `wBugContestSecondPartySpecies` (C/G `engine/events/bug_contest/contest_2.asm:75-92`).
  `ContestReturnMons` puts that byte back into slot 1 and recounts up to the first `$FF`
  (`:99-116`). `RemoveMonFromPartyOrBox` does not stop at `wPartyCount`. It shifts the struct, OT
  and nickname arrays up to the end of each array (C/G `engine/pokemon/move_mon.asm:1222-1329`,
  `CopyDataUntil` to `wPartyMonOTs` / `wPartyMonNicknames` / `wPartyMonNicknamesEnd`).
- **Failure scenario:** The responder is in the National Park contest, idle on the overworld. The
  host PROMPTs slot 0, which is the only slot that passes `SlinkTradeCheckOwnSlot` while the count
  is 1, and the player answers YES.
  1. RemoveMon shifts mon 2's struct into index 0, mon 3's into index 1, and so on. The species
     list becomes `[FF, FF, sp3, ...]` and the count becomes 0.
  2. AddTempmon writes the incoming mon over index 0, which destroys mon 2's shifted struct.
  3. SaveAfterLinkTrade saves `count = 1` to SRAM.
  4. At contest end, `ContestReturnMons` restores `sp2` into slot 1 and recounts. The species list
     now names mon 2 while slots 1 and up hold mon 3, mon 4 and so on. The list and the structs no
     longer match.
  5. If the player resets before the contest ends, the durable save holds a one-mon party and mons
     2-6 are lost.

  Both outcomes are durable and pass the checksum.
- **Fix:** In the dispatcher (and, defensively, in `SlinkTradeCheckOwnSlot`), refuse pickup while
  `wStatusFlags2` bit `STATUSFLAGS2_BUG_CONTEST_TIMER_F` is set (C/G `constants/ram_constants.asm`).
  Also add a structural guard: require `wPartySpecies[wPartyCount] == $FF` and a non-`$FF` entry at
  every index below the count. Add a MODEL control built from a masked contest party.

### BLOCKER-2: The commit writes a Pokémon-only save without the native pre-trade full save

- **Where:** `trade_commit.asm:9-10` declares the precondition "a current save already
  established". Nothing establishes it:
  - `trade_receptionist.asm:11-30` goes straight from `yesorno` to `callasm SlinkTradeEntry`.
  - `SlinkTradePromptEntry` (`trade_service.asm:124-176`) runs anywhere on the idle overworld.
  - `trade_commit.asm:157` then calls `SaveAfterLinkTrade`.
- **Vanilla facts:**
  - `SaveAfterLinkTrade` writes only `wPokemonData`. It then **recomputes the checksum over all of
    `sGameData`**, which still includes the old `sPlayerData` (C `engine/menus/save.asm:26-37`,
    G `:27-38`; `SaveChecksum` C `:526-537`).
  - It skips `AskOverwriteSaveFile`.
  - Vanilla always forces a full save before a trade: `Text_MustSaveGame` / `special TryQuickSave`
    (C `maps/Pokecenter2F.asm:87-90`, G `:70-73`).
- **Failure scenarios:** The resulting saves are durable and pass the checksum.
  - **(a)** The responder caught a legendary or received a gift mon since their last save, then
    trades. The party and dex are saved, but the event flags, items and location (`wPlayerData`)
    are not. After a power-off without a later full save, the legendary or gift is available again,
    which duplicates it. Items consumed from the bag since the last save come back.
  - **(b)** A new run on a cartridge or emulator save that holds an older file. The first trade
    happens before the first save. The new run's party is written into the **old file**, whose check
    values are valid, and the checksum is recomputed. The old save is silently overwritten with a
    mix of two files.
  - **(c)** No save exists at all. The primary and backup check values are absent, so the traded mon
    exists only in RAM, but DONE(0) was already published.

  Host oracles take a following scenario save in the duo harness. Real play has no such save.
- **Fix:**
  - **Proposer:** add the native `Text_MustSaveGame / yesorno / special TryQuickSave` steps (EXPORT
    them like `Text_TradeReceptionistIntro`) before `callasm SlinkTradeEntry`. Cancel if the player
    declines.
  - **Responder:** after YES, call the same native save (`TryQuickSave` → `Link_SaveGame`, which
    includes the overwrite prompt) before `SlinkTradeSnapshot`. Treat a declined save as a decline,
    PublishDone(1).
  - At minimum, refuse PROMPT and QUERY unless `wSavedAtLeastOnce` is set (C `ram/wram.asm:3002`,
    G `:2407`). That closes (b) and (c) but not (a).

### MAJOR-1: PROMPT pickup can open native text in the middle of a step, leaving the background out of alignment

- **Where:** `trade_dispatch.asm:4-54` has no player-step gate. `trade_service.asm:151` calls
  `OpenText` from the idle-frame bridge.
- **Vanilla facts:**
  - In `HandleMap`, `HandleMapObjects` (which advances `_HandlePlayerStep`) runs **before**
    `NextOverworldFrame` (C `engine/overworld/events.asm:151-153`, G `:149-151`). Pickup therefore
    runs on frames in the middle of a step.
  - `_HandlePlayerStep` moves the map anchor at step **start** (`UpdateOverworldMap`,
    C/G `engine/overworld/player_step.asm:1-16`). `ScrollScreen` then adds the step vector to `hSCX`
    and `hSCY` each frame (`:37-48`).
  - `OpenText` → `ReanchorBGMap_NoOAMUpdate` rebuilds the BG from the (already-destination) anchor
    and sets `hSCX = hSCY = 0` (C `engine/overworld/init_map.asm:49`, G `:45`; `home/window.asm:46-53`).
  - Vanilla opens text only on frames where `CheckPlayerState` enables events (C
    `events.asm:215-232`). `PlayerEvents` (START menu, NPC text) and the phone's `CountStep` path
    run only then.
- **Failure scenario:** The partner's PROMPT arrives while the responder is walking. Pickup lands
  mid-step on most walking frames. The screen jumps to the destination view. After `CloseText`, the
  rest of the step's scroll is added on top, so `hSCX` ends up to 15 px past where the engine
  expects. The background stays misaligned with the sprites and the edge-column streaming until the
  next reanchor (the next text box or menu). Ledge hops (MIDAIR) and the bike are affected the same
  way. This is visual only, not save corruption, and it is reasoned from source, not reproduced.
- **Fix:** Pick up only on the frames where vanilla would enable events. Mirror `CheckPlayerState`:
  require `wPlayerStepFlags` bit `PLAYERSTEP_CONTINUE_F` clear, or `STOP` set with `MIDAIR` clear.
  Add a unit control with the flags mid-step. The live duo responder should also be shown walking.

### MINOR-1: RemoveMon shifts party mail in SRAM before the durable save

- **Where:** `trade_commit.asm:80-88` clears `wLinkMode` before the RemoveMon farcall.
- **Vanilla facts:** With `wLinkMode == 0`, `RemoveMonFromPartyOrBox` immediately opens SRAM and
  shifts `sPartyMail` (C/G `move_mon.asm:1330-1360`). `SaveAfterLinkTrade` runs about 10 s later,
  after the animation and evolution.
- **Failure scenario:** The traded mon sits before a party member that holds mail. A reset between
  RemoveMon and SaveAfterLinkTrade leaves the saved party as it was before the trade, but the mail is
  shifted by one slot, so the wrong message appears. The host reconciles "rolled back" from the save
  and cannot see this.
- **Fix:** Keep `wLinkMode = LINK_TRADECENTER` during RemoveMon, as vanilla `LinkTrade` does, and do
  the one-slot `sPartyMail` compaction immediately before `SaveAfterLinkTrade`. The outgoing mon
  never carries mail (D3), so only the other members' mail moves.

### MINOR-2: The post-commit and UNCERTAIN holds are silent, permanent soft-locks

- **Where:** `trade_service.asm:277-314`. With result 2, `.check` jumps straight back to `.wait`
  (`:296-299`), so the loop never exits, not even on RELEASE. With result 0 there is no timeout and
  no B, only RELEASE.
- **Failure scenario:** The host or server dies after a commit, or any uncertain path runs. The game
  freezes on an empty speech box forever. A reset is the intended recovery, and it is data-safe
  because the save happens before DONE, but nothing on screen tells the player to reset.
- **Fix:** Before entering either hold, print a native line such as "Trade saved. Waiting for
  partner… Reset if stuck." (result 0) or "Trade error. Please reset." (result 2).

### MINOR-3: The responder's consent and wait UX

- **Where:** `trade_service.asm:151-158, 182-190` and `:544-546`.
- **Problem:** The responder's YES/NO says only "SLINK TRADE?". It does not name which of their mons
  leaves (host-chosen `FRAME+9`) or what arrives. After YES, `CloseText` runs and the map stays
  frozen with no text for up to `SLINK_TRADE_APPLY_FRAMES` (60 s after 67143736). A player who
  presses B, thinking the game has hung, cancels silently. Also, `YesNoBox` itself has no bound, so a
  slow human can answer after the proposer's wait has already expired.
- **Fix:** Name the outgoing and incoming species in the prompt (`GetPokemonName` into the string
  buffer). Keep a "Waiting for partner… (B: cancel)" box open through WaitApply.

### MINOR-4: No vanilla trade-sanity parity on the ROM side

- **Where:** `trade_service.asm:489-523` (`SlinkTradeCheckIncoming`).
- **Vanilla facts:** Vanilla refuses a trade that would leave no living mon
  (`CheckAnyOtherAliveMonsForTrade`) and refuses abnormal incoming mons (`ValidateOTTrademon`)
  (C `engine/link/link.asm:1524-1527`, G `:1399-1401`). The overlay checks shape, item and names
  only, and leaves semantics to the host (acknowledged at `:490-491`).
- **Failure scenario:** A bad or malicious host payload (a fainted mon, or eggs only) leaves the
  responder unable to battle.
- **Fix:** Either farcall the two native predicates before `SlinkTradeValidateSnapshot`, or record
  this as a host-owned invariant with a server-side test.

### MINOR-5: The stack evidence does not cover the deepest commit path

- **Where:** `trade_service.asm:426-428`; `tests/unit/test_gen2_trade_service.py:428-470`.
- **Problem:** The static budget test explicitly excludes commit, animation and evolution. The live
  continuous witness (`tools/gen2_trade_oracles.py:281-302`, margin ≥32) covers the scenarios that
  were run (`evolve` has the responder evolving). The deepest native tail is not known to be
  covered: the responder base (bridge 8 + returns + 10-byte context + commit's 20), then
  EvolvePokemon, then `LearnLevelMoves` with a full move set (the forget-a-move menu), then a nested
  DelayFrame with a SFX `PlaySFX`, then a Normal IRQ.
- **Consequence:** On G/S the stack is `$DF03-$DFFF` (G `pokegold.sym`) with `wOTPartyMonNicknames`
  just below it. On Crystal it is `$C000-$C0FF`, with cart RAM below, and that RAM is open during
  `SaveAfterLinkTrade`.
- **Fix:** Add one live witness in which the responder receives a trade-evolver whose evolution
  offers a move with four moves already known, with a host SFX request posted during the evolution.

### NIT-1: `SlinkTradeInit` is dead code

`trade_service.asm:9-17` is never called; `grep` finds no caller in `patch/gen2/src` or `lua`.
Delete it.

### NIT-2: The Crystal commit omits `BackupGSBallFlag`

Vanilla calls `farcall BackupGSBallFlag` after `SaveAfterLinkTrade` (C `link.asm:2044-2046`;
`mobile/mobile_41.asm:515`). The overlay commit skips it, so `sGSBallFlagBackup` can drift from
`sGSBallFlag` until the next full save (`save.asm:107,284`). This matters only when the backup save
is restored. Add the farcall under `IF !DEF(_GOLD) && !DEF(_SILVER)`.

### NIT-3: Phone and trade pickup are silently disabled on G/S in DMG or SGB mode

`phone.asm:15-18` and `trade_dispatch.asm:30-33` read `rSVBK`, which reads `$FF` on DMG, so both
refuse. This is harmless under the recorded CGB-mode pin (`docs/gen2/GEN2_STANDARD_COMPARISON.md:69`).
If DMG mode is ever admitted, gate the check on `hCGB`.

### NIT-4: No "please wait" text during the proposer's QUERY and OFFER waits

The receptionist box keeps showing the intro text for up to 10 s (after 67143736). Vanilla prints
`Text_PleaseWait` here (C `Pokecenter2F.asm:84`).

---

## 2. The DelayFrame, Reset and START hooks (brief item 1)

**DelayFrame (`slink.asm:28-47`).**
- The bridge returns with the entry flags and `A = 1`, which is exactly the state vanilla has after
  `ld a,1 / ld [wVBlankOccurred],a` (C `home/delay.asm:1-13`; the G anchor is identical).
- BC and HL are pushed and popped. DE is preserved, as the source says:
  - trade dispatch: `push de` around PromptEntry (`trade_dispatch.asm:65-67`);
  - phone: no DE use;
  - SFX: `push de` around `PlaySFX` (`sfx.asm:52-65`).
- The bank is saved from `hROMBank` and restored through `rst Bankswitch` on the only exit.
- No overlay routine switches banks by itself. The only `Bankswitch` uses are in `slink.asm:37-43`.
  Every direct `call` from bank `$75`/`$13` targets ROM0 (checked against the overlay `.sym`); banked
  targets use `farcall` or `predef`.
- Arming `wVBlankOccurred` before the service is sound: a VBlank during the service satisfies this
  DelayFrame.

**Reset (`sfx.asm:13-25`).**
- Same-size replacement of `call DelayFrames` in Reset, verified by the builder anchor.
- AF is preserved and C stays 32.
- It latches BLOCKED before the first service visit. That also protects the soft-reset path, which
  enters Reset from interrupt context while the main thread may be inside `PlaySFX`.

**Receptionist, phone and START edits.** The receptionist pointer, the phone `ld hl` loads and the
START edits are all same-shape. `verify_trade_hook` and `verify_phone_hook` pin the bytes.

**Interrupt safety.** Nothing an ISR touches is written from the bridge, apart from vanilla-legal
main-thread `PlaySFX`. The dispatcher and phone service read WRAMX only after the SVBK check. The
mailbox, the Crystal stack and the audio state are all in WRAM0.

## 3. Verified OK

1. **Free space.**
   - Mailbox `$CFD8-$CFFF` (C) and `$C1D9-$C1FF` (G/S) are `EMPTY` in the clean maps.
   - Native `_ResetWRAM` excludes both: C clears `$C400..$CFCB`; G clears `$C300..$D198` plus game
     data.
   - ROM0 `$0063-$00FF` is `EMPTY` and all zero in both clean ROMs. The bridge takes `$0063-$0079`
     and the Reset latch takes `$0080+`, both ASSERTed.
   - Service banks `$75` (C) and `$13` (G/S) are `EMPTY` in the clean maps.
   - Bank `$24` has `$006E` free bytes on G/S; the 54-byte table uses `$7F92-$7FC7`.
   - Bank `$24` is `CheckSpecialPhoneCall`'s own bank in all three syms, as the same-bank
     `ld hl, table` requires.
2. **Mailbox layout.** Core `+0..13`, lease `+14..29`, private sample `+30/31`, phone `+32/33`. There
   is no overlap. `+33 < 39` on G/S. The ROM-private and host-owned bytes are disjoint.
3. **Dispatcher stack check.** The pattern (`sp+5` = `BANK(NextOverworldFrame)` = `$25`;
   `DelayFrame+3`, `DelayFrames+3`, `NextOverworldFrame+9`) matches the instruction sizes (C
   `events.asm:185-191`, G `:183-189`). Nested DelayFrames inside PromptEntry, the Reset path and
   every non-overworld caller fail it. `gen != ack` blocks redispatch.
4. **Trade lease state machine.**
   - Context offsets are consistent across callers and callees (`+2` inside callees).
   - `add sp`/`ret` are balanced on every Entry, PromptEntry and Exit path.
   - The generation and ack rules hold: QUERY g1, OFFER g2, APPLY g2+1 with ACK == g2.
   - The slot cannot be redirected.
   - Every refusal between the APPLY pickup (`SlinkTradeApplyPickup`) and the `SlinkTradeCommit`
     entry happens **before any mutation**. The host rule "a close after pickup is a pre-commit
     refusal; after the commit latch it is UNCERTAIN" (`lua/gen2/trade_overlay.lua:166-179`)
     therefore matches the asm.
   - A reset between the APPLY pickup and the commit leaves SRAM untouched and zeroes the lease.
   - A reset inside the commit resolves by the save the player loads. `SaveAfterLinkTrade` writes
     primary then backup, so a torn save still loads either before or after the trade. The
     exceptions are MINOR-1 (mail) and BLOCKER-2 (what the save contains).
5. **OT slot 1 preimage.** It is deliberately **not restored** on any path
   (`trade_snapshot.asm:71-75`). That is safe:
   - The native engine treats `wOTParty*` as scratch, reloaded at every battle or link.
   - The host stages only OT slot 0, the species list, the count and the OT player name.
   - The snapshot is compared, never copied back.
   - On G/S the scratch lies inside `wPokemonData` (`$DD55 < $DF01`), so saves carry a stale copy of
     the player's own mon, as vanilla carries stale trainer parties. This is harmless.
6. **Commit register discipline.**
   - The five saved control pairs plus the role/count word are popped in the correct reverse order on
     every path (`.bad_entry`, three `.uncertain` sites, success).
   - The Z status survives the loads and pops.
   - `wCurPartyMon = count-1`, `wForceEvolution = TRUE` and `wLinkMode = LINK_TRADECENTER` are set
     around EvolvePokemon, which vanilla trade evolution requires (C `engine/pokemon/evolve.asm:68-75,
     145-168`).
   - `AddTempmonToParty` returns carry only when the party is full (C `move_mon.asm`).
7. **Phone (brief item 3).**
   - It never overwrites a nonzero native id. It arms only when the full word is `0000`
     (`phone.asm:68-76`).
   - It withdraws only its own exact `09 00`.
   - Every native writer overwrites unconditionally (`Script_specialphonecall`, C
     `scripting.asm:1904-1909`) or waits politely (bike shop `events.asm:1325-1330` defers while 9 is
     queued).
   - Delivery goes only through `CountStep` → `CheckSpecialPhoneCall` (C `events.asm:873`), which
     runs inside `PlayerEvents` with no script running, at a step boundary, never with `wLinkMode`
     set. That rules out cutscenes, link rooms and the trade hold.
   - `checkphonecall` in the nurse script runs after several `pause`s, so id 9 has been withdrawn by
     then.
   - The 30-frame `pause` in `CheckSpecialPhoneCall.script` withdraws the id before
     `SlinkPhoneCallScript` runs, and ARMED is consumed exactly once.
   - Elm's and the bike shop's story calls are deferred, never lost. Bill's box-full call does not use
     the id.
   - A contaminated saved id is scrubbed on the first service visit.
   - `SaveAfterLinkTrade` cannot persist id 9 because the id lives in `wPlayerData`.
8. **START row (brief item 5).**
   - EXIT is replaced in the append list only, so the item count is unchanged: at most 8 normally,
     7 in the contest, and 4 early game with no dex and no mon.
   - Index 9 addresses the tenth `.Items` row.
   - B and START still return `PAD_B` through `ContinueGettingMenuJoypad` (C `home/menu.asm:649-655`)
     because the menu keeps `STATICMENU_ENABLE_START`.
   - `SlinkStartMenuEntry` mirrors `StartMenu_Option` (FadeToMenu, farcall, return 6 →
     `.ReturnRedraw`, which redraws the contest status box too).
   - `SlinkPanel` restores `hInMenu` on its single exit.
   - G/S have the identical constant and append layout (G `engine/menus/start_menu.asm:3-11,295-340`).
9. **Reset.** It clears the whole mailbox via native Init (C `home/init.asm`). The SFX latch
   discards host posts made during the 32-frame wait.

## 4. The trade_service.asm wait edit (brief's "working-tree diff", now commit 67143736)

**Only three immediates change.**
- QUERY 30 → 600 and OFFER 180 → 600, via `SlinkTradeWaitAck`, B-cancellable through
  `SlinkTradeWaitFrame`.
- APPLY 1800 → 3600, via `SlinkTradeWaitApply`, B-cancellable, **shared by both roles**.
- 16-bit counters are fine.
- **SOURCE:** each immediate is the same `ld bc, n16` size as before. **Reported by the author, not
  re-run here:** the `.sym`/`.map` files are byte-identical.

**Verdict: correct, and it fixes a real bug.** In the committed d09e76c1 build the 30-frame QUERY
bound was shorter than the client's 30-frame tick plus one round trip, so it could drop a healthy
host.

**Comments on the edit:**
- **(a)** The comment's "~29 s for the partner's YES/NO" is a budget, not a bound. The responder's
  `YesNoBox` is unbounded (MINOR-3), so the host must still settle a late YES, and 4d6524e5 does.
- **(b)** The APPLY constant also governs the **responder's** frozen, text-less map wait, now 60 s
  (MINOR-3).
- **(c)** A longer B-cancellable proposer wait widens the time in which the host may have delivered
  APPLY to the partner while the proposer cancels. That is a one-sided commit, handled by the
  server's uncertain/conflict path (`server/state.py` `_tick_pending_trade` / `_settle_trade`). No
  asm change is needed.
- **(d)** NIT-4 ("please wait" text) applies.
