> **Status: DRAFT** (OMP cx-52e45b38, 2026-10-02). The coordinator's review decisions are below; they WIN over the draft.
>
> - **Q1 (MUTATES_INPUT on the PK4 binding): no owner call needed.** My ruling summary was imprecise. The flag stays set (a harmless scratch copy for the party raw copy); DECISIONS is corrected. No shared edit.
> - **D1:** PLAN.md's stale box-delivery lines are fixed (C5 row + open question 3 closed by the party-only ruling).
> - **F5:** the hge fork is at `E:/Howard/HGEngine_ROMHack/hg-engine` (not under hgss_archipelago-master). The hge citations go through FEATURE_BAR until C6 re-reads them there.
> - The shared trade producer leaves foreign opcodes alone (Gen 4 commit `6c76265c`,
>   `claude/gen4-tp-gate`): its state machine still runs every visit for the save watchdog, and
>   only `{29, 21, 30, 31}` reach dispatch. The C2 dispatcher calls every producer every visit and
>   each producer ignores foreign opcodes. (corrected 2026-10-03: "The C2 dispatcher routes by
>   opcode before `tp_service`" is retired.)
>
> **Status: DRAFT** (OMP cx-52e45b38, 2026-10-02). Peer spec draft for coordinator review and owner
> sign-off. Nothing here is built.
>
> - Reads the coordinator decision blocks of `docs/gen4/companion/C2_BEACON_SPEC.md:1-19` and
>   `docs/gen4/companion/C3_SOUND_SPEC.md:1-24`; those decisions WIN over anything below.
> - **`DECISIONS_2026-10-02_companion.md:12` — "It should not. In party only."** The box arm is
>   dropped. No `PCStorage_PlaceMonInFirstEmptySlotInAnyBox`, no `CountPCEmptySpace` gate, no
>   writable 0x88 scratch. This closes `FEATURE_BAR.md:201`.
> - The shared ABI is used **UNMODIFIED** (`C2_BEACON_SPEC.md:47-49`). Every static assert at
>   `patch/src/nds/common/abi.h:261-286` still holds.
> - **Producer isolation is per producer, not in the dispatcher** (Gen 4 `6c76265c`,
>   `claude/gen4-tp-gate`): the C2 service SysTask calls **every** producer on **every** visit, and
>   each producer ignores opcodes it does not own. The trade producer's old catch-all
>   `} else { tp_ack(m,seq,0,2); }` (`trade_producer.h:300-302`) is gated on the trade-owned set;
>   the sound producer already returned without acking anything that was not
>   `SLINK_OP_PLAY_SE`/`PLAY_FANFARE` (`sound_producer.h:17`). C5 is the second producer in that
>   SysTask and inherits nothing but the call order.
>   (corrected 2026-10-03: the draft's "must never hand `SLINK_OP_PLAY_SE` to `tp_service`" is
>   obsolete; the dispatcher routing requirement is void.)
> - The trade's hold/state lives in the **service SysTask's own heap data block**
>   (`C2_BEACON_SPEC.md:5`), NOT in the 0xE00 title window (`C2_BEACON_SPEC.md:6-12`) and not in
>   the ABI.
> - **Correction to `FEATURE_BAR.md:110`:** the opcode is `u16` and `gScriptCmdTable` index 1 is
>   `ScrCmd_Dummy` — `src/data/fieldmap/script_cmd_table.h:857-858` (index 0 = `ScrCmd_Nop` at
>   `:857`, index 1 = `ScrCmd_Dummy` at `:858`). Confirmed below.
> - **Citation drift fixed here:** `FEATURE_BAR.md:158` cites `asm/macros/script.inc:22-24` for
>   `Dummy`; the macro body is `asm/macros/script.inc:23-25` (`:22` is the comment).
>
> **Pinned sources.** HG/SS: `E:/Howard/hgss_archipelago-master/.tooling/pokeheartgold` @ `ad7a3afa`
> (`data/gen4_sources.lock.json`). hge: `E:/Howard/HGEngine_ROMHack/hg-engine` (pin `cb2dc435`,
> `FEATURE_BAR.md:120`).

# Gen 4 companion C5: receptionist trade, PARTY-ONLY (spec draft, 2026-10-02)

**Card:** C5 (`PLAN.md:66`), bar item 4 (`FEATURE_BAR.md:14`).

**Evidence classes.** S = SOURCE (a file:line at the pinned pin), M = MODEL (lupa host world),
P = PHYSICAL (a running patched cartridge).

---

## 1. Scope

**IN.** One in-game trade at the Pokémon Center nurse. The player is offered the SLINK trade,
consents, picks a party slot, and the host's **encrypted** 0xEC record overwrites that slot.

**OUT** (all settled, cited):

| Excluded | Why |
|---|---|
| Box delivery / `PCStorage_PlaceMonInFirstEmptySlotInAnyBox` | owner ruling, `DECISIONS_2026-10-02_companion.md:12`; `FEATURE_BAR.md:197-201` |
| Any ROM-side cipher or checksum **implementation** | the host stages at-rest bytes; the ROM only *calls* the engine's own primitives for the identity gate (§3.2) |
| A third menu option in the nurse message | the nurse menu is message data — `NonNPCMsgVar` + `GetMenuChoice` (`FEATURE_BAR.md:96`; `scr_seq_0003.s:101-103`). A named third option is a message-bank edit. C5 uses a `ScrCmd_YesNo` gate instead (`FEATURE_BAR.md:97`) |
| `SLINK_RB_COMMIT_MUTATES_INPUT` behaviour | irrelevant to the party arm — see §3.1 |
| Any new ABI field, offset, opcode or capability | `C2_BEACON_SPEC.md:47-49`. Trade uses the shared `SLINK_CAP_DURABLE_TRADE` (`abi.h:89`) via `slink_trade_advertise` (`trade_producer.h:28-33`) |

**The two-arm table in `FEATURE_BAR.md:100-108` collapses to one row for Gen 4:**

| Destination | Call | Input | Mutates input? |
|---|---|---|---|
| **Party only** | `Party_SafeCopyMonToSlot_ResetAprijuiceModifiers` (`src/party.c:97-105`) | 0xEC `Pokemon` | **no** (§3.1) |

---

## 2. Script flow, per artifact

### 2.1 The one patch site

`std_nurse_joy` is `2002` (`include/constants/std_script.h:17`) and resolves through
`sScriptBankMapping` to common-script member 3 entry **002**
(`FEATURE_BAR.md:94`; `files/fielddata/script/scr_seq/scr_seq_0003.s:83`). One script serves all 25
Pokémon Centers.

Vanilla shape, read at the pin:

```
scr_seq_0003_002:                    scr_seq_0003.s:83
    PlaySE SEQ_SE_DP_SELECT          :84
    LockAll                          :85        <- the field is already locked
    FacePlayer                       :86
    ... GetTrcardStars / menu setup  :87-100
_0175:
    NonNPCMsgVar VAR_SPECIAL_x8004   :101
    TouchscreenMenuHide              :102
    GetMenuChoice VAR_SPECIAL_RESULT :103
    Compare VAR_SPECIAL_RESULT, 0    :104
    GoToIfEq _01AA                   :105       <- heal path
    Compare VAR_SPECIAL_RESULT, 1    :106
    GoToIfEq _019B                   :107       <- decline path
    End                              :108       <- anything else: script ends
```

The epilogue the SLINK branch must return through is the heal path's tail, `_02B2`
(`scr_seq_0003.s:190-199`): restore the nurse's movement, `NPCMsg msg_0040_00003`, `WaitButton`,
`CloseMsg`, `TouchscreenMenuShow`, `ReleaseAll`, `RestartCurrentScript`.

### 2.2 HG/SS (`scr_seq_0003.s`)

The SLINK branch is **entered from the nurse menu choice**, not added to the message. After
`Compare VAR_SPECIAL_RESULT, 1 / GoToIfEq _019B` (`:106-107`) and before the bare `End` (`:108`),
insert a third dispatch that costs no message edit:

```
    Compare VAR_SPECIAL_RESULT, 2
    GoToIfEq _SLINK          ; a fourth menu row is not needed; see §2.2 note
```

**INFERRED, and the cheaper shape is preferred:** instead of a new menu row, gate on the *visit*.
`LockAll` is already held (`:85`) and `FacePlayer` has run (`:86`), so the script is at a safe,
input-quiet point in **every** Pokémon Center visit. Insert, immediately before `End` (`:108`):

```
_SLINK_GATE:
    SetVar VAR_SPECIAL_x8004, 0          ; pre-seed: YesNo leaves it UNTOUCHED on B
    YesNo VAR_SPECIAL_x8004
    Compare VAR_SPECIAL_x8004, 0
    GoToIfNe _SLINK_DECLINED
    ...
```

**Why the pre-seed is mandatory.** `ScrCmd_YesNo` (`src/scrcmd_c.c:947-956`) hands off to
`sub_020416E4` (`:958-973`), which on `LIST_NOTHING_CHOSEN` (B) returns FALSE **without writing the
variable** (`:963-964`). Without the pre-seed, B leaves the previous value and the branch falls
through into the trade. This is falsifier **F3b**.

`YesNo` writes **0 = yes, 1 = no** (`src/scrcmd_c.c:966-970`). It is a native opcode 63 macro
(`asm/macros/script.inc:424-427`); the compiled table entry is `gScriptCmdTable[63]` =
`ScrCmd_YesNo` (`src/data/fieldmap/script_cmd_table.h:920`, index 0 at `:857`).

Then the party selection, copied verbatim from the native trade
(`files/fielddata/script/scr_seq/scr_seq_0753_T03PC0101.s:31-40`):

```
    CloseMsg
    FadeScreen 6, 1, 0, RGB_BLACK
    WaitFade
    ScrCmd_566
    GetPartySelection VAR_SPECIAL_RESULT
    RestoreOverworld
    FadeScreen 6, 1, 1, RGB_BLACK
    WaitFade
    Compare VAR_SPECIAL_RESULT, 255
    GoToIfEq _SLINK_DECLINED
```

- `GetPartySelection` is opcode 351 (`asm/macros/script.inc:1998-2001`;
  `src/data/fieldmap/script_cmd_table.h:1208`). It reads the app's selection and maps slot **7 to
  255** (`src/scrcmd_c.c:1620-1631`, `:1625-1627`), then frees `PartyMenuArgs`.
- **`ScrCmd_566` / `RestoreOverworld` bracket the party app** (`:34-38`). That pair is not
  decoration: the selection is an application launched out of the field context, and the field is
  re-entered after. Any C5 branch that drops it is a new bug, not a simplification.
- The slot-overwrite epilogue is the native one (`scr_seq_0753_T03PC0101.s:64-69`): decline message,
  `WaitButton`, `CloseMsg`, `ReleaseAll`, `End`.

**No new UX.** Every glyph, menu and animation in this sequence is the vanilla nurse + native NPC
trade. The only thing C5 adds is one opcode-1 `ScrCmd` in the middle and a Yes/No prompt.

### 2.3 hge (`armips/scr_seq/scr_seq_00003_commonscript.s`)

Same edit, in the fork's armips spelling. The nurse entry is `scr_seq_0003_002` at
`armips/scr_seq/scr_seq_00003_commonscript.s:93`; the menu dispatch is `:113-118` and the epilogue
is `:152-…` with `releaseall` at `:125`. The hge nurse is a **fork source edit**, not a bytecode
patch (`FEATURE_BAR.md:166`).

Every macro C5 needs already exists in hge's `armips/include/scriptmacros.s`:

| Macro | Line | Opcode | pret twin |
|---|---|---|---|
| `dummy` | `:17-19` | **1** | `Dummy`, `script.inc:23-25` |
| `yesno` | `:480-483` | 63 | `YesNo`, `script.inc:424-427` |
| `get_party_selection` | `:2340-2343` | 351 | `GetPartySelection`, `script.inc:1998-2001` |
| `lockall` / `releaseall` | `:789-791` / `:793-795` | 96 / 97 | — |

(`GetSelectedPartySlot` at `:7506-7509` is a **duplicate alias for the same opcode 351**; use
`get_party_selection`.)

### 2.4 The opcode slot

`gScriptCmdTable[1]` is `ScrCmd_Dummy` at `src/data/fieldmap/script_cmd_table.h:858` (index 0 =
`ScrCmd_Nop` at `:857`). Repoint that one pointer and C5 owns a ScrCmd with **no table growth**,
which is what makes the hge arm viable (hge inherits the script NARCs from the base ROM,
`FEATURE_BAR.md:111`).

**Opcode-1 gate: PASSED by composition** (`FEATURE_BAR.md:158-165`) — zero `Dummy` macro uses in
`files/fielddata/script`, zero `dummy` uses in hge's `armips/scr_seq`, and HG/SS's `a/0/1/2` NARC is
byte-identical to the assembled `scr_seq/*.s` because C0 rebuilds the ROMs byte-for-byte.
**Re-run that check (C0 sha1 + NARC member diff) on any new pin** (`FEATURE_BAR.md:165`).

---

## 3. ROM side

### 3.1 `SLINK_RB_COMMIT_MUTATES_INPUT` is irrelevant to the party arm

`slink_binding_gen4_pk4` sets the flag (`record_binding.h:165-171`, bit at `:39`), so
`tp_service` hands `s->scratch` instead of `s->incoming`
(`trade_producer.h:292-297`). For the party arm that flag is **carried by analogy, not by
evidence**: `Party_SafeCopyMonToSlot_ResetAprijuiceModifiers` writes only the *destination*
(`src/party.c:101-102`) and reads `src` for one boolean (`:100`). It cannot scribble on `src`.

Handing the scratch copy anyway is **free and correct** — it costs one 0xEC memcpy and removes a
class of future hazard. C5 does **not** edit `record_binding.h`. The flag's real justification
remains the box path (`record_binding.h:36-39`, `README.md:92-96`), which Gen 4 does not build.

### 3.2 The identity gate: the engine's decrypt, on a scratch, never on `s->incoming`

`tp_accept_stage` runs `validate` and `identity` **on `s->incoming`**
(`trade_producer.h:151-155`), and `tp_service` then hands `s->incoming` to `start_scene`
(`:292`). For PK4 both callbacks need a `SlinkDecoder` — without one they **fail closed**
(`record_binding.h:33-40, 119-140`; `README.md:76-77`).

The engine supplies everything the decoder needs, with no new cipher:

| Decoder op | Engine primitive | Evidence |
|---|---|---|
| LCG segment decrypt (in place) | `MonDecryptSegment(void*, u32, u32 seed)` — XOR with the LCG stream; `_MonDecryptSegment == _MonEncryptSegment` | `src/math_util.c:143-152`; declared `include/math_util.h:26` |
| seed for the data blocks | the record's own `checksum` word at +0x06 — i.e. `ENCRY_ARGS_BOX` | `src/pokemon.c:62,66` |
| seed for the party tail | `box.personality` — i.e. `ENCRY_ARGS_PTY` | `src/pokemon.c:61,65` |
| `read_u32` at logical `0x00` | `scratch->box.personality` (plaintext) | `include/pokemon_types_def.h:156` |
| `read_u32` at logical `0x0C` | `GetBoxMonData(&scratch->box, MON_DATA_OT_ID)` → `blockA->otID` | `src/pokemon.c:539-541`; block resolved by `GetSubstruct` (`:3951-3990`) |
| `verify` | `CalcMonChecksum((u16*)dataBlocks, sizeof(dataBlocks)) == box.checksum` — the `CHECKSUM` macro | `src/pokemon.c:67`, body `:3941-3949` |

**Byte-for-byte agreement with the host oracle** (`server/adapters/gen4_codec.py:245-248, 258`):
the oracle LCG-decrypts `raw[8:]` with the stored checksum as the seed, then requires
`checksum(stored) == stored_sum`. The engine's `DECRYPT_BOX` + `CHECKSUM` is the same rule with
the same seed. `GetSubstruct` (`:3951-3990`) and the oracle's `_unshuffle` are the same permutation,
and the oracle's logical `otID` at +0x0C (`:289, 302`) is `box.personality`'s sibling `otID` in the
decrypted logical view (`include/pokemon_types_def.h:226`). **The OT offset in the shipped binding
(`record_binding.h:168`, `0x0C`) is correct and is a LOGICAL, post-decrypt offset.**

**The invariant that must not be got wrong:** `MonDecryptSegment` **mutates in place**, and
`GetBoxMonData` does not decrypt (`src/pokemon.c:539-541` reads `blockA->otID` directly). So the
adapter must:

1. copy `stage_len` bytes out of `s->incoming` into a **separate 4-aligned 0xEC scratch**
   (`trade_producer.h:58-59` already provides one aligned buffer, but it is `s->scratch`, which is
   what gets handed to `start_scene` — the decoder needs a *third* buffer, or must re-encrypt);
2. `DECRYPT_PTY`/`DECRYPT_BOX` the copy, read OT, run `CHECKSUM`;
3. **discard it, leaving `s->incoming` byte-identical to the host stage.**

If the decoder decrypts `s->incoming` in place, `start_scene` receives a **plaintext** record,
`Party_SafeCopyMonToSlot_ResetAprijuiceModifiers` writes plaintext into a party the game believes is
encrypted, and every later `GetMonData` on that slot returns garbage. That is falsifier **F1**.

### 3.3 The commit site

The ScrCmd's single job, in order:

| # | Action | Contract |
|---|---|---|
| 1 | `slot == Slink_Gen4_ChosenSlot(ctx)` — the slot the **script variable** carries | the one and only slot the player may be shown. **The chosen slot travels in a script variable, never in static ROM storage**: `GetPartySelection VAR_SPECIAL_RESULT` (§2.2) leaves the slot in `VAR_SPECIAL_RESULT`, and the ScrCmd reads it out of the `ScrCmdContext` it is handed. (The exact context field is a C5 SOURCE detail; I have not read the struct.) There is **no `Slink_Gen4_SelectedSlot` symbol**. (corrected 2026-10-03: the draft named a `Slink_Gen4_SelectedSlot()` accessor as if it were storage. Two reasons that shape is forbidden: **static `.bss` is forbidden on HG/SS** — it moves `SDK_STATIC_BSS_END = 0x021E5900` and every pinned address above it (`C2_BEACON_SPEC.md:629`, `FEATURE_BAR.md:145`) — and **hge writes `bsssize = 0` for every generic overlay** (`make.py:454`), so a static there is uninitialised (`C6_HGE_BUILD_SPEC.md:482-486`). The script variable is the only carrier that works on all three artifacts.) |
| 2 | `slot < Party_GetCount(saveData)` **and** `slot < 6` | **mandatory** — see below |
| 3 | `slink_trade_commit_entered(producer, witness, slot, engine)` | `trade_producer.h:121-132`; marks `SLINK_COMMIT_ENTERED` (`:130`) |
| 4 | `Party_SafeCopyMonToSlot_ResetAprijuiceModifiers(SaveArray_Party_Get(fs->saveData), slot, (Pokemon *)record)` | `src/party.c:97`; the same call the native trade makes (`src/npc_trade.c:153-156`) |
| 5 | `UpdatePokedexWithReceivedSpecies(fs->saveData, (Pokemon *)record)` | mirrors `src/npc_trade.c:155`; **INFERRED** that C5 wants this — see §7 Q4 |

**Step 2 is not optional. `PARTY_ASSERT_SLOT` asserts, and asserts are LIVE in this build:**

```
src/party.c:9-12     GF_ASSERT(slot >= 0); GF_ASSERT(slot < curCount); GF_ASSERT(slot < maxCount);
include/assert.h:12-16   GF_ASSERT -> GF_AssertFail() when PM_KEEP_ASSERTS
config.mk:36-37      GF_DEFINES += -DPM_KEEP_ASSERTS     (unless NO_GF_ASSERT)
```

A stale or out-of-range slot is therefore a **cartridge halt**, not a graceful refusal. The
producer's `locate()` gate (`trade_producer.h:287-288`) already bounds `slot<0 || slot>5`, but it
does **not** know `curCount`. C5's own `slot < Party_GetCount` check is what makes the commit
fail-closed instead of aborting. Falsifier **F4** pins this.

**Why a full party cannot arise — the arithmetic, not a slogan.** `src/party.c:100-103`:
`valid = destHasSpecies - srcHasSpecies; curCount += valid;`. Overwriting an **occupied** slot with
an **existing** species gives `valid = 1 - 1 = 0`, so `curCount` is unchanged and the party never
grows. `GetPartySelection` can only return slots the menu listed, i.e. slots `< curCount`. The
owner ruling (`DECISIONS_2026-10-02_companion.md:13`) is therefore structurally guaranteed.

**`slink_trade_commit_entered` on a companion-owned copy.** Its doc comment is written for a
*native* trade whose original mutation must be skipped on refusal (`trade_producer.h:118-120`).
C5 has no original to skip — the copy *is* the commit. What the function still usefully provides is
the `locate()`-vs-`actual_slot`-vs-`s->slot` triple check (`:126`) and the `SLINK_COMMIT_ENTERED`
milestone (`:130`) that `tp_service` requires before it will believe the scene
(`:215-220`). Calling it is therefore **required**; treating its refusal path as meaningful for
C5 is **INFERRED-unused** and must be tested (F4).

### 3.4 Witness publication

- PREPARE publishes epoch/visit/token/old identity and `SLINK_VISIT_ACCEPTED`, plus
  `SLINK_PRE_SAVE_CONSENT` on a yes (`trade_producer.h:263-270`, `:197-203`).
- SCENE drives the rest (`trade_producer.h:212-248`): `COMMIT_ENTERED` (§3.3 step 3) →
  `received_key` readback → `same_identity` → `SCENE_EVOLUTION_DONE` → post-save.
- `received_key` **must read the game's party slot**, not the staging decoder
  (`README.md:138-141`; `record_binding.h:161-164`). Implementation: read
  `party->mons[slot].box.personality` (plaintext, `+0`) and `GetBoxMonData(&party->mons[slot].box,
  MON_DATA_OT_ID)` after a scratch decrypt — i.e. the *same* primitives as §3.2, applied to
  `gSaveBlock2Ptr`'s party. **INFERRED**: this is the independent chain the ABI demands.
- Final result: `SLINK_TRADE_COMMITTED` only with all five milestone bits and
  `save_status == 1` (`abi.h:129-137`, `trade_producer.h:174-188`). Anything that fails **after**
  `COMMIT_ENTERED` is `SLINK_TRADE_UNCERTAIN` and is retained until reset/reconciliation
  (`trade_producer.h:216-220`; `abi.h:130-131`).
- Host read: `lua/nds/native_witness.lua` `M.success(w, prepare_seq, scene_seq, expected_pid,
  expected_otid)` (`lua/nds/native_witness.lua:53`), under the ABI-3 reader rule
  (`README.md:32-35`).

### 3.5 Save interaction — who saves, and when the commit is durable

**The ROM saves, not the player and not the host.** Mapping onto the shared producer:

| Producer hook | Gen 4 implementation | Evidence |
|---|---|---|
| `start_pre_save` / `poll_pre_save` | the **YesNo gate**: accepted = `SLINK_VISIT_ACCEPTED`, yes = `SLINK_PRE_SAVE_CONSENT`, no = `SLINK_TRADE_UNCHANGED` before any mutation | `trade_producer.h:194-208, 263-273`; gate §2.2 |
| `post_save_begin` | **initiate only**: `Save_PrepareForAsyncWrite(fs->saveData, mode)` → `Save_WriteManInit` | `src/save.c:264-266`, `:613-619` |
| `post_save_poll` | one `Save_WriteFileAsync(fs->saveData)` per service visit, mapped to OK / PENDING / FAIL | `src/save.c:206`, statuses `WRITE_STATUS_CONTINUE/NEXT/SUCCESS` (`:207`) |
| `save_timeout_frames` | REQUIRED nonzero or PREPARE is refused with BAD_ARGS; PENDING past it is FAIL | `trade_producer.h:260, 163-171` |

**Do not use `Save_NowWriteFile_AfterMGInit`** (`src/save.c:198-209`): it is a **blocking**
`do { } while` loop that burns the frame, and it carries two LIVE asserts
(`isNewGame == FALSE`, `saveFileExists == TRUE`, `src/save.c:202-203`, subject to
`config.mk:36-37`). The vanilla async path is driven from overlay 44
(`src/overlay_44_0222CDAC.c:1802-1806`), which is precedent for a per-frame poll.

**Durability.** The commit is durable at the **first polled OK**, and only there:
`POST_SAVE_OK` is published from the poll, never from `begin` (`trade_producer.h:233-243`,
`:174-188`; `README.md:78-84`). Before that the witness reads `SAVE_PENDING (2)`
(`abi.h:136`, `:239`), which the ABI-3 reader treats as **not success**
(`README.md:32-35`). `SAVE_PENDING` past `save_timeout_frames` is FAIL, so `UNCERTAIN` stays
reachable after `COMMIT_ENTERED` (`trade_producer.h:160-171`).

**Ordering matches the accepted Gen 1 flow**: consent → save → commit
(`patch/gen1/src/trade_receptionist.asm:54-57`, `patch/gen1/src/trade_ui.asm:114-135`). The
Gen 4 pre-save maps to that same point; **INFERRED**, because the Gen 1 pre-save is a game-context
save and the Gen 4 pre-save here is a script-context save. See §7 Q3.

---

## 4. Host side

### 4.1 Staging and the lease

Two mailbox commands, both already defined, neither new (`abi.h:84-85`):

| Step | Host writes | Producer rule |
|---|---|---|
| PREPARE | `opcode = SLINK_OP_TRADE_PREPARE (29)`, then `args`: `slot[0]`, `role[1]`, `old PID[4:8]`, `old OT[8:12]`, `visit_id[12:16]`, `token[16:32]` | `trade_producer.h:253-273`; arg layout `abi.h:165-168` |
| — | host waits for `ack_seq`/`status`, phase `READY` | `trade_producer.h:198-205` |
| SCENE | `SlinkRecordStageV1` at `BLOB_OFFSET 0x100` (`abi.h:47`), **then** `opcode = SLINK_OP_TRADE_SCENE (21)` + `seq` + `args[0] = slot` | publish opcode **LAST** (`C3_SOUND_SPEC.md:96`) |
| WITHDRAW (optional) | `SLINK_OP_TRADE_WITHDRAW (30)` | legal only in `READY`; too late in `SCENE` → `SLINK_REASON_WITHDRAW_TOO_LATE` (`trade_producer.h:278-280`) |
| STATUS | `SLINK_OP_TRADE_STATUS (31)` | read-only ack (`trade_producer.h:276-277`) |

**Stage contents** (`SlinkRecordStageV1`, `abi.h:192-201`):

| Field | Value | Why |
|---|---|---|
| `layout_version` | `SLINK_NDS_STAGE_LAYOUT (1)` | `abi.h:39` |
| `binding_id` | `SLINK_BIND_GEN4_PK4 (4)` | `record_binding.h:24` |
| `stage_len` | **exactly `0xEC`** | `trade_stage_len` is 0 in the binding (`record_binding.h:168`), so `slink_binding_stage_len` returns `party_len` (`record_binding.h:87-91`) |
| `generation` | 4 | `record_binding.h:166` |
| `flags` | `SLINK_STAGE_RAW_ENCRYPTED (1)`, and **no other bit** | `abi.h:191`; unknown bits are a refusal (`trade_producer.h:148`) |
| `claimed_pid`, `claimed_otid` | from the **plaintext** record: `pid` at +0, `otid` at +0x0C | `gen4_codec.py:288-289, 302`; cross-checked against the binding (`record_binding.h:141-145`) |
| `record` | `Pk4.encrypt_party(plain)` | `lua/gen4/pk4.lua:80`, `PARTY_MON_SIZE = 0xEC` (`:14`) |

Every one of those is checked before any engine call (`trade_producer.h:146-150`), and the claim is
cross-checked against the binding's own extraction (`:154-155`, `abi.h:186-189`).

### 4.2 The identity checks, fail closed

1. **Host-side, before encrypting.** `Pk4.decode_party_mon` round-trips the record
   (`lua/gen4/pk4.lua:153-157`); `Pk4.mon_key(pid, otid)` gives `PID:OTID`
   (`lua/gen4/pk4.lua:82`). The host refuses to stage if `claimed_*` disagrees with the decoded
   plaintext.
2. **Producer-side.** `tp_accept_stage` compares the host claim to
   `b->identity(decoder, ...)` (`trade_producer.h:154-155`). A missing decoder or a missing
   `verify` callback returns 0 — **FAIL CLOSED**, not a permissive default
   (`record_binding.h:94-102, 130-140`; `README.md:76-77`).
3. **After the commit.** `received_key` is re-read from the game and compared with
   `s->incoming_id` (`trade_producer.h:224-230`); a mismatch is `UNCERTAIN`, never a success.
4. **Slot.** `locate(ctx, old_pid, old_otid)` must return the same slot the script chose
   (`trade_producer.h:287-288`, `:126`). PREPARE refuses a slot argument that disagrees with
   `locate` (`:261-262`).

### 4.3 Cancel and timeout

| Case | Result | Evidence |
|---|---|---|
| B at the YesNo gate (var untouched) | script goes to the decline epilogue; **no mailbox command is ever issued**, so nothing is armed | `src/scrcmd_c.c:963-964`; pre-seed §2.2 |
| 255 from `GetPartySelection` | script declines; if a PREPARE was already outstanding the host issues `WITHDRAW`, which is legal in `READY` | `src/scrcmd_c.c:1625-1627`; `trade_producer.h:278-280` |
| No at the gate | `SLINK_TRADE_UNCHANGED` before any mutation | `trade_producer.h:206-208, 273` |
| Host goes silent in `PRE_SAVE` | the producer polls `poll_pre_save` every visit; there is no ROM-side timeout for a waiting host. **INFERRED: the host must own the deadline** | `trade_producer.h:194-208` |
| Host never sends SCENE | phase stays `READY` indefinitely. **INFERRED: same** — but note `SLINK_TRADE_WITHDRAW` is the designed exit | `:194-208, 278-280` |
| `safe_field` false at SCENE | `SLINK_TRADE_UNCHANGED`, engine untouched | `trade_producer.h:286` |
| Save PENDING past `save_timeout_frames` | FAIL → `UNCERTAIN`, never released raw | `trade_producer.h:160-171` |

**The cancel path is genuinely inert:** falsifier **F2** asserts the party is byte-identical after a
cancel, which is only true because nothing is published before consent.

---

## 5. Falsifiers

| # | Claim | Class | Method | Pass |
|---|---|---|---|---|
| **F1** | The received record lands **byte-exact (encrypted)** in the chosen slot | S+M+P | S: static — the decoder writes only to a third buffer (§3.2), and `start_scene` is handed `s->incoming` unmodified (`trade_producer.h:292`). M: a fake engine captures the pointer; assert it equals the staged bytes. P: on a patched cartridge, after commit, read the party slot and byte-compare against the host's `encrypt_party` output — **no decrypt on the ROM side** | Byte-identical, all three |
| **F2** | Cancel leaves the party unchanged | M+P | B at the YesNo gate; 255 at `GetPartySelection`; `no` at PREPARE. Snapshot all 6 slots before and after | Byte-identical; no milestone above `SLINK_VISIT_ACCEPTED` |
| **F3** | A stale or mismatched stage is refused | S+M | (a) `stage_len != 0xEC`; (b) `binding_id != 4`; (c) `generation != 4`; (d) an unknown `flags` bit; (e) `RAW_ENCRYPTED` cleared; (f) `layout_version != 1`; (g) `claimed_pid/otid` altered; (h) a record whose `CHECKSUM` disagrees. Each must be `SLINK_TRADE_UNCHANGED` with the party untouched (`trade_producer.h:146-155`) | Every case refused, no mutation, no ack-with-OK |
| **F4** | An out-of-range or stale slot is refused, **never asserted** | S+M+P | Force `slot >= Party_GetCount` (a party of 3, slot chosen as 5 by a synthetic script path) and a `locate()` that disagrees with the chosen slot | No `GF_AssertFail`; `SLINK_TRADE_UNCHANGED`; party byte-identical. Pins `src/party.c:9-12` + `config.mk:36-37` |
| **F5** | SAVE + cold reload keep it | P | Commit, let the save poll reach OK, power-cycle (no soft reset), reload | The slot still holds the record; `POST_SAVE_OK` was set only after the polled OK, never at begin (`trade_producer.h:233-243`) |
| **F6** | **Opcode 1 is executed by no vanilla script** | S | Re-run `FEATURE_BAR.md:158-165`: zero `Dummy` uses in `files/fielddata/script`; zero `dummy` uses in hge `armips/scr_seq`; C0 sha1 + `a/0/1/2` member diff (965 members, `filesystem.mk:406`) | Zero uses on HG, SS and hge; re-run on every pin (`FEATURE_BAR.md:165`) |
| **F7** | Two producers do not steal each other's acks | S+M | C3's **F6** (`C3_SOUND_SPEC.md:487`) with C5 present: hold a `SLINK_OP_PLAY_SE` across ≥1 visit; post a `TRADE_PREPARE`; assert each producer acks only its own opcodes (`trade_producer.h:300-302`, gated). Then, with no trade request outstanding, assert the trade producer's save watchdog still advances — its state machine runs **every** visit and only `{29,21,30,31}` reach dispatch. | Exactly one producer acks each request, and the watchdog does not stall. **This is what the shared else-arm fix buys** (`6c76265c`); it failed against the unrouted dispatcher the draft proposed. |
| **F8** | The committed identity is observed, not assumed | S+M | Mutant: `received_key` decodes the staging buffer instead of the party slot. It must stay **RED** | `README.md:138-141` |

**What no falsifier here can prove:** flash durability (the ABI says so itself,
`abi.h:243-245`, `README.md:153-154`); that the SE/prompt reads well; that a full 6-mon party
behaves — a full party is unreachable by §3.3's arithmetic, so that case has no test.

---

## 6. Single-writer table

One owner per field, per artifact. "ROM" = the C5 companion module; "engine" = vanilla HGSS/hge.

| Cell | Owner | Evidence |
|---|---|---|
| mailbox `signature`, `abi_version` (0x00/0x04) | **ROM** (C2, per tick) | `abi.h:149-150`; `C2_BEACON_SPEC.md:242-243` |
| `opcode`, `seq`, `args[]` (0x06/0x08/0x10) | **host**, published last | `abi.h:150-153`; `FEATURE_BAR.md:258` |
| `status`, `ack_seq`, `reason` | **ROM** (C5, via `tp_ack`) | `abi.h:151-152`; `trade_producer.h:93-104` |
| `result[16]` (0x30) | untouched by C5 | `abi.h:154` |
| `capabilities` (0x40) | **ROM** (C5 sets `SLINK_CAP_DURABLE_TRADE`; C2 stamps it per tick) | `abi.h:155`; `trade_producer.h:28-33` |
| `session_epoch` (0x44) | **host**; ROM only checks | `abi.h:156`; `C2_BEACON_SPEC.md:246` |
| `producer_phase` (0x48) | **ROM** (C5 only; 0 until C5 lands) | `abi.h:157`; `C3_SOUND_SPEC.md:519` |
| `reserved` = boot generation (0x4C) | **ROM** (C2) | `C2_BEACON_SPEC.md:248` |
| witness (0x50, 0x50 B) | **ROM** (C5 producer only) | `abi.h:169-182`; `trade_producer.h:66-83` |
| `SlinkRecordStageV1` at 0x100 | **host** writes; **ROM** reads and snapshots | `abi.h:192-201`; `trade_producer.h:139-158` |
| title window 0xE00..0xE40 | **ROM** published / **host** read; **neither** trade state | `C2_BEACON_SPEC.md:6-12` |
| producer hold/lease state | **SysTask heap data block**, C2-allocated, reset-freed | `C2_BEACON_SPEC.md:5`; `C3_SOUND_SPEC.md:99` |
| `gScriptCmdTable[1]` pointer | **ROM** (C5, once at build) | `script_cmd_table.h:858` |
| `party->mons[slot]` bytes | **engine** record; written once by C5's copy, read by everyone | `src/party.c:97-105` |
| `party->extra.aprijuiceModifiers[slot]` | **engine**, reset by the copy | `src/party.c:102` |
| flash save chunks | **engine** (`Save_WriteFileAsync`), initiated by C5 | `src/save.c:204-208` |
| dialogue / party menu / animation | **engine** — C5 adds none | §2.2 |

**One rule that follows:** the ROM never writes a host-owned field, and the host never writes a
ROM-owned field. The stage buffer is the single crossing, and it is host-written then
snapshot-copied (`trade_producer.h:151`), never aliased.

---

## 7. Open questions

Every item below is either marked **UNVERIFIED** (I could not read it) or **INFERRED** (I reasoned
to it and it must be proven at the cited class).

1. **Who calls `Save_PrepareForAsyncWrite` with which `mode`, and is it legal from a
   `mainTaskQueue` SysTask while a script is running?** The overlay-44 precedent
   (`src/overlay_44_0222CDAC.c:1802-1806`) is a different context. **UNVERIFIED**; the engine's
   `asyncWriteMan` ownership and the flash lock (`OS_Lock`/`CARD_UnlockBackup`) need reading.
   C5 SOURCE.
2. **The exact `WRITE_STATUS_*` → `SLINK_SAVEPOLL` mapping.** `src/save.c:207` shows
   `CONTINUE`/`NEXT`/`SUCCESS`; `SlinkSavePoll` is PENDING/OK/FAIL
   (`trade_producer.h:144-146`). **INFERRED**: `SUCCESS` → OK, `CONTINUE`/`NEXT` → PENDING,
   anything else → FAIL. Must be pinned at C5 MODEL.
3. **Pre-save semantics.** §3.5 maps the YesNo gate onto `start_pre_save`. That gives consent, not
   a save. Gen 1's pre-save is a real game-context save before the commit
   (`patch/gen1/src/trade_receptionist.asm:55-57`). **INFERRED**: Gen 4 needs no pre-commit save,
   because the party write is in RAM and durability is the post-save's job. **Owner call.**
4. **`UpdatePokedexWithReceivedSpecies`** (`src/npc_trade.c:155`). The native trade calls it so the
   received species is registered. Soul Link pairs usually arrive already registered. **INFERRED**:
   call it. Cheap and faithful to the native shape; **owner call** if the coordinator wants the
   minimum.
5. **Trade evolution.** The shared model has a `SCENE_EVOLUTION_DONE` milestone
   (`abi.h:118`) and the producer stamps it on scene completion
   (`trade_producer.h:232`). The owner ruling is a **raw slot overwrite** with no animation and no
   evolution. **INFERRED**: the milestone is stamped by `tp_service` without any evolution code, so
   nothing is owed — but this should be stated once, in the ABI-aware sense, and never
   reinterpreted as "evolution ran". Confirm with the ABI owner.
6. **`safe_field`.** `tp_service` requires it true at PREPARE (`:258`) and SCENE (`:286`).
   **UNVERIFIED** what the Gen 4 predicate is. It must be true while a nurse script holds
   `LockAll`; it must be false inside the party-menu app. C5 SOURCE + MODEL.
7. **`poll_scene`.** It must return 1 once "the field returned" (`trade_producer.h:44`), i.e. after
   the fade-in and the epilogue message are done. **INFERRED**: return 0 until the script reaches
   `ReleaseAll`. The bound is `save_timeout_frames`, and the host's own SCENE budget is 6000
   frames (`README.md:85-88`) — the adapter bound must not exceed it.
8. **Is the nurse branch safe under `LockAll`?** `LockAll` is at `scr_seq_0003.s:85`, and
   `ScrCmd_YesNo` builds a `ListMenu2D` over the field BG (`src/scrcmd_c.c:949-952`). **UNVERIFIED**
   that a list menu opens with the lock held. The vanilla `scr_seq_0753_T03PC0101.s` does not call
   `LockAll` before its own menus. **P at C5**: this is a live-run question no static check answers,
   and it is falsifier-adjacent to F2.
9. **hge's `gScriptCmdTable[1]` target.** `FEATURE_BAR.md:127-128` shows `#486` is the same function
   as `#1` in both HG and hge, so one repoint serves both — but that was read from the pinned xMAP,
   not from the fork's source. **UNVERIFIED** for the hge build C6 produces.
10. **`README.md:134-137`** asks for an "UNVERIFIED independent-implementation" comment on the PK4
    binding and notes its raw staging / 0x0C / `MUTATES_INPUT` are unchecked. §3.1-3.2 now check
    0x0C and raw staging against the pinned pret; `MUTATES_INPUT` stays **unproven for the party
    arm** and is retained by analogy. That comment belongs to the ABI owner, not to C5.