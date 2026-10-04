# Gen 4 companion C4 — FACTS (card C4a, 2026-10-04)

**Card:** C4a of the C4 panel card (`PLAN.md:65`), part 1 only: the open points in
`docs/gen4/companion/C4_PANEL_SPEC.md` §8, answered from SOURCE.

**Provenance.** Every row is read from the pinned pret `pokeheartgold` at `ad7a3afa`
(`E:/Howard/hgss_archipelago-master/.tooling/pokeheartgold`) or from this repository, and
carries `file:line`. **VERIFIED** = read at the cited line. **VERIFIED-BY-PRECEDENT** = read,
but the value is a convention several call sites share rather than a declared constant.
**UNVERIFIED** = not settled here, with what would settle it. No value is guessed.

**Status legend for the corrections this file makes to other documents:**

| Mark | Meaning |
|---|---|
| **[CORRECTS]** | the cited document says something this file read contradicts |
| **[CONFIRMS]** | the cited document is right and this file closes its stated doubt |

---

## 1. The facts table

| # | Fact | Value | Evidence | Status |
|---|---|---|---|---|
| Q7a | `SlinkTextSpec.charset` is **not** an HGSS font id. It is the shared `SlinkCharset` class enum, and the validator never reads it | `charset = SLINK_CHARSET_GEN4` = **2**, width 2, terminator `0xFFFF` — exactly the PK4 binding's own `text` member | `patch/src/nds/common/record_binding.h:27-32` (enum), `:165-171` (`slink_binding_gen4_pk4.text = { 2, SLINK_CHARSET_GEN4, 0xFFFFu }`), `:185-195` (`slink_text_terminator_index` reads **only** `width` and `terminator`; a NULL spec returns −1) | VERIFIED |
| Q7b | **The spec's premise is wrong**: a wrong *charset* cannot refuse a payload, so "the spec is wrong ⇒ the whole payload is refused" is not the rule | refusal comes from `width ∉ {1,2}`, a NULL spec, or no terminator unit in a validated row | `record_binding.h:188` (`!t || (t->width != 1 && t->width != 2)`), `:189-194`; `panel_producer.h:22-32` | **[CORRECTS]** `C4_PANEL_SPEC.md:634` |
| Q7c | The panel must pass the **binding's own** spec through the seam, not a hand-written copy | `&slink_binding_gen4_pk4.text` | `record_binding.h:169`; an 8-bit Gen 3 spec (`{1, GEN3, 0xFF}`) is *accepted* on a Gen 4 row, because the low byte of `0xFFFF` is `0xFF` — pinned by `tests/unit/test_gen4_panel_policy.py` scenario 8 | VERIFIED |
| Q7d | A Gen 4 row is 16 UTF-16LE units: **15 characters + the terminator** | 32 bytes / width 2 = 16 units | `record_binding.h:169`, `:189-193`; `abi.h:55` (`SLINK_INFO_LINE_WIDTH 32`) | **[CONFIRMS]** `C4_PANEL_SPEC.md:263-269` |
| Q7e | HGSS's own font id for window text. There is **no named constant** at the pinned tree; the value every START-menu-launched app uses is the literal `4` | `FontID` is a bare `u8`; `FONT_NUM` is 6; boot allocates 0, 1, 3; font 2 is the naming screen; **4 is what every message-window app allocates** | `include/font_types_def.h:7` (`typedef u8 FontID; // TODO: This should be an enum`), `include/font.h:6` (`FONT_NUM 6`), `src/main.c:60-62` (0, 1, 3), `src/naming_screen.c:501` and `src/overlay_44_0222CDAC.c:4748` (2), and 4 at `src/application/pokedex/ov18_021E8BF4.c:269`, `src/application/pokegear/map/overlay_101_021EDCE0.c:524`, `src/party_menu.c:285`, `src/view_rankings.c:395`, `src/voltorb_flip/voltorb_flip.c:2090`, `src/battle/battle_022378C0.c:217`, `src/oaks_speech.c:562`, `src/berry_pots_app.c:1130`, `src/alph_puzzle.c:1160`, `src/overlay_mic_test.c:410`, `src/view_photo.c:349` | VERIFIED-BY-PRECEDENT. The **symbolic** name is UNVERIFIED; what would settle it: an hg-engine `enum FontID`, or reading `sFontArcParam` in `src/font.c:52-55`. Consequence for `panel.c`: use the literal `4` with this citation, or define a named macro citing this row |
| Q8a | The START menu launches an app only after **(a)** `ov01_021E636C(0)` and **(b)** `IsPaletteFadeFinished()` | the trainer-card path, verbatim | `src/start_menu.c:1093-1100` (selection: fade, `exitTaskFunc`, `state = START_MENU_STATE_WAIT_FADE`), `:366-368` (state dispatch), `:705-715` (`Task_StartMenu_WaitFade`: `if (IsPaletteFadeFinished()) { …; exitTaskFunc(taskManager); state = WAIT_APP; }`), `:721-723` (`WAIT_APP` then polls `FieldSystem_ApplicationIsRunning`) | VERIFIED |
| Q8b | What the fade helper actually does | `ov01_021E636C(0)` = `BeginNormalPaletteFade(0, 0, 0, 0, 6, 1, 4)`; `ov01_021E636C(1)` = `BeginNormalPaletteFade(0, 1, 1, 0, 6, 1, 4)`. Any other argument hits `GF_AssertFail` | `asm/overlay_01_021E5900.s:1237-1276` (the two argument tuples and the assert at `:1271-1272`), declared `include/overlay_01.h:35`; `BeginNormalPaletteFade`/`IsPaletteFadeFinished` at `include/unk_0200FA24.h:6,11` | VERIFIED |
| Q8c | The engine-side launch precondition, which the panel inherits | `GF_ASSERT(fieldSystem->unk0->unk4 == NULL)`; the return path asserts `unk4 == NULL` **and** `unk0 == NULL` | `src/field_system.c:127-133`, `:89-98` | VERIFIED |
| Q8d | Returning to the menu also waits a fade | `START_MENU_STATE_RETURN_WAIT_FADE` → `IsPaletteFadeFinished()` → `HANDLE_INPUT`; `state 10/11` runs `ov01_021E636C(1)` then polls | `src/start_menu.c:435-438`, `:393-403` | VERIFIED |
| Q8e | **There is no "text window active" predicate in this chain.** `MenuInputStateMgr_GetState` is a BUTTONS/TOUCH selector, not a window check — so the spec's INFERRED second half has no engine counterpart | `MENU_INPUT_STATE_BUTTONS` / `MENU_INPUT_STATE_TOUCH` | `include/menu_input_state.h:6-16`; used as a touch test at `src/start_menu.c:723` | **[CORRECTS]** `C4_PANEL_SPEC.md:635` |
| Q8f | ⇒ the predicate the policy implements is **fade finished AND the menu is the launching context AND no child app resident** — and the middle term has no single engine flag | the seam carries all three; `menu_open` is a seam member, not a fact | `patch/src/nds/gen4/panel_policy.h`, `SlinkGen4PanelEngine` | the fade term VERIFIED; `menu_open` and `app_running` are **UNVERIFIED as single predicates** — what would settle them: a start-menu hook that sets a flag while `state ∈ {HANDLE_INPUT, WAIT_APP}`, and a read of `fieldSystem->unk0->unk4` from the service SysTask |
| Q5 | `OverlayManager_New` **tolerates `parentWork == NULL`** | it stores `args` verbatim and never dereferences it | `src/overlay_manager.c:5-18` (`ret->args = args;` at `:12`), `:41-43` (`GetArgs` returns it), `:45-75` (`OverlayManager_Run` calls `init(man, &proc_state)` at `:54` with no args access). `FieldSystem_LaunchApplication` passes `parentWork` straight through | VERIFIED. **The only precondition is that the app's own `Init` must not call `OverlayManager_GetArgs`**: the trainer card's does (`src/overlay_trainer_card.c:38`, storing it at `:45-46`), and the panel's must not. **[CONFIRMS]** `C4_PANEL_SPEC.md:481-485` |
| H1 | A new `enum HeapID` value is **not** needed. The pattern is a cast alias into the existing enum's numeric range | `HEAP_ID_TRAINER_CARD` is `#define … ((enum HeapID)94)`, not an enumerator; it is the **only** app-private heap alias in the whole tree (the sole other numeric cast is an `AllocMonZeroed((enum HeapID)4)` in `src/field_roamer.c:208`) | `include/overlay_trainer_card.h:8`; the enum itself, `include/constants/heap.h:4-167` | VERIFIED |
| H2 | The numeric range and how heaps are allocated | ids 0..159 (`HEAP_ID_VOLTORB_FLIP` = 159, `HEAP_ID_MAX` = 160); `totalNumHeaps = HEAP_ID_MAX`; slots 0..3 are the four boot templates, every other id is created on demand; **every** alloc/free path is bounds-checked against `totalNumHeaps` | `include/constants/heap.h:160-166`; `src/system.c:86-91` + `:110` (`Heap_InitSystem(sDefaultHeapSpec, 4, HEAP_ID_MAX, …)`); `src/heap.c:31-38`, `:66-79`, `:207`, `:224`, `:242`, `:268`, `:287` | VERIFIED |
| H3 | **`Heap_Create` on an id that already exists is a hard assert** — so the panel's heap id must never be concurrently live | `CreateHeapInternal`'s `else` arm is `GF_ASSERT(FALSE)` | `src/heap.c:119-154`, specifically `:150-152` | VERIFIED |
| H4 | Which number to take | ~40 distinct child ids are ever `Heap_Create`d in the pinned tree; outside the named app ids the numeric ones are {26, 53, 94, 103, 104, 128} plus `HEAPID_OV36` / `HEAPID_OV55`. 94 is the trainer card's and cannot be live at the same time as the panel (`unk4 == NULL` is asserted), but a slot no app creates is the boring choice | the scan above; ids 0..3 are boot templates (`src/heap.c:66-79`) and are **not** reusable | UNVERIFIED as a *choice*. What would settle it: the owner's pick, plus one `Heap_Create`/`Heap_Destroy` cycle check at runtime. **`panel.c` decides, this card does not** |
| Q9a | **`SDK_STATIC_BSS_END` and the arena start, on HG** | `0x021E5900` and `0x0226EC40` | `heartgoldus.xMAP:50389` (`SDK_STATIC_BSS_END`), `:206726` (`SDK_SECTION_ARENA_START`) | VERIFIED |
| Q9b | **ov1 (`field`) on HG starts at `0x021E5900`** | `SDK_OVERLAY.field.ID = 1`, `START = 0x021E5900` | `heartgoldus.xMAP:53317-53318`; the source agrees: `main.lsf:486-491` puts `asm/overlay_01_021E5900.o` first in the `field` group | VERIFIED |
| Q9c | **The 0x021E5900 sharing is real on HG, not only on hge.** `trainer_card` (id `0x32`) starts there too, and 46 HG overlay groups share that START | `SDK_OVERLAY.trainer_card.ID = 00000032`, `START = 021E5900` | `heartgoldus.xMAP:130860-130861`; the shared-START list also contains `pokegear`, `options_app`, `OVY_0`, `voltorb_flip`, … (`main.lsf:1143-1146` names `overlay_100_021E5900.o` for pokegear) | **[CORRECTS]** `C4_PANEL_SPEC.md:415` — the caveat "measured on hge only" is itself out of date. **[CONFIRMS]** `FEATURE_BAR.md:223` |
| Q9d | The largest HG overlay ends exactly at the arena start | `OVY_12.END = 0x0226EC40` (largest of 129 overlay groups) | `heartgoldus.xMAP:206726`; `main.lsf` for the group list | **[CONFIRMS]** `FEATURE_BAR.md:227` |
| Q9e | **"ov1 is `0x60280`" is ov1's own footprint, not the free window** | `field.BSS_END − field.START = 0x02245B80 − 0x021E5900 = 0x60280` exactly; the free window from that base to the arena is `0x0226EC40 − 0x021E5900 = 0x89340`, i.e. `0x28EC0` of headroom above ov1 | `heartgoldus.xMAP:63113` (`END = 0x02209B60`), `:63123` (`BSS_END = 0x02245B80`), `:53318` (`START`) | **[CORRECTS]** the arithmetic in `FEATURE_BAR.md:227` / `C4_PANEL_SPEC.md:418-423`. The *constraint* stands and is now stated correctly: **the group's END must be ≤ `SDK_SECTION_ARENA_START` = 0x0226EC40**, and a panel far smaller than ov1 cannot move it |
| Q9f | Where a **newly appended** group lands | UNVERIFIED — the map above describes vanilla groups only; a new `After main` group must be read out of the linked ELF | — | UNVERIFIED. **This is falsifier F10** (`C4_PANEL_SPEC.md:578`) and stays open until the first HG/SS link |
| Q9g | Other HG slots exist, so `0x021E5900` is not the only candidate | `0x021E7740` (pokegear_app, OVY_102), `0x0221BA00`, `0x0221BE20`, `0x022378C0` (OVY_12/57/58/70/72), `0x02260C20` (OVY_124-128), … | the shared-START scan of `heartgoldus.xMAP` | VERIFIED |
| Q9h | **Soul Silver** | nothing in this worktree: only a heartgoldus map exists | the pinned xMAP path | UNVERIFIED. What would settle it: an SS link + map from the same C0 build. **The HG numbers above must not be quoted as SS numbers** |
| Q9i | hge | unchanged; C6 owns it | `FEATURE_BAR.md:229-244` (settled decision: the vanilla-style `0x021E5900` slot) | out of scope for this card |
| SEQ | **`SEQ_SE_GS_GEARCANCEL` = 2368** | `#define SEQ_SE_GS_GEARCANCEL 2368`, between `SEQ_SE_GS_GEARCURSOR 2367` and `SEQ_SE_GS_GEARDECIDE 2369` | `include/constants/sndseq.h:1366` | VERIFIED. **[CONFIRMS]** the decision block (`C4_PANEL_SPEC.md:4`). **§3.4's "INFERRED … must not be guessed" (`:328-330`) is stale** — the value is read, not inferred |
| KEYS | `gSystem + 0x48` is `newKeys` | `heldKeys` +0x44, `newKeys` +0x48, `newAndRepeatedKeys` +0x4C | `include/system.h:39-41` | **[CONFIRMS]** the 2026-10-03 correction in `C4_PANEL_SPEC.md:315-318` |
| RES | The result words | `0` = A/more, `0x7F` = B/close, valid at `closed_seq`; the Q1 ruling widens `0x7F` to "closed, for any reason" | `patch/src/nds/common/abi.h:213-214`; ruling `C4_PANEL_SPEC.md:7-11` | VERIFIED |
| OWN | Single-writer table for the info region | host: `session_epoch`, `request_seq`, `lines`, `page`, `pages`, `enable`, `text`; ROM: `drawn_seq`, `closed_seq`, `state`, `result` | `abi.h:203-228`; `C4_PANEL_SPEC.md:591-608` | VERIFIED |

## 2. Shared-producer behaviour the policy had to be written around

Read, and each row is now **pinned by a test** in `tests/unit/test_gen4_panel_policy.py`:

| # | Behaviour | Evidence | Consequence for `panel.c` / the host |
|---|---|---|---|
| S1 | The un-posted open needs `menu_open` **and** a valid payload **and** `m->opcode == 0` | `panel_producer.h:46-47` | `SLINK_OP_SHOW_INFO` is only needed to *force* an open |
| S2 | A posted request is refused with `FAIL` + `SLINK_REASON_BAD_ARGS` whenever the gate or the payload fails — including while a panel is live | `panel_producer.h:49-52` | there is no "busy" reason; the host sees `BAD_ARGS` |
| S3 | The app is handed a **copy**; a mid-panel rewrite of `request_seq` or `session_epoch` is ignored, and the close is **consumed but not published** | `panel_producer.h:39-44, :54-57` | a torn payload is *unvalidated*, never half-drawn |
| S4 | **A close and the next open land in the same visit.** The drain clears `active` at `:44` and control then falls through to the take-a-request branch | `panel_producer.h:36-62` | the host must clear `enable` or bump `request_seq` after a close. This is why the ROM keeps no private page cursor — and it is the concrete form of `C4_PANEL_SPEC.md:360-364` |
| S5 | The un-posted open and the drain both need the mailbox epoch **armed** (`!epoch` refuses) | `panel_producer.h:25-26` | a zero-epoch mailbox is "unarmed", not "empty" |
| S6 | Refusal reasons are the shared vocabulary's only (`BAD_ARGS`). C4 therefore adds **no** epoch gate of its own | `panel_producer.h:51`; contrast C3's `CLIENT_TOO_OLD`/`IDENTITY` in `sound_policy.h` | deliberate non-decision; F8 pins reason 2 |

## 3. What this file does NOT settle

| Question | Why it is open | What would settle it |
|---|---|---|
| Where a newly appended `slink_panel` group lands on HG/SS (Q9f) | vanilla maps only | one `main.elf` read (falsifier **F10**) |
| Any Soul Silver number (Q9h) | no SS map in this worktree | the SS link from the same C0 build |
| The panel overlay's own `ramSize` (Q4) | no panel code exists yet | the linked section headers after the first link |
| Whether `menu_open` / `app_running` have single engine predicates (Q8f) | none found in the traced chain | a start-menu hook, or reading `fieldSystem->unk0->unk4` from the service SysTask |
| The symbolic HGSS font id (Q7e) | `FontID` is a bare `u8` | an hg-engine font enum, or `sFontArcParam` |
| The panel heap number (H4) | an owner/build choice | the owner's pick + one runtime `Heap_Create`/`Heap_Destroy` cycle |
| F3 / F4 / F5 (drawn glyphs, no leak, field reload) | PHYSICAL | hardware; see `C4_PANEL_SPEC.md:571-573` |

## 4. Corrections this file makes, in one place

1. **`C4_PANEL_SPEC.md:634`** (Q7): the charset member is never consulted; `SLINK_CHARSET_GEN4` is
   simply the value the PK4 binding already carries (`record_binding.h:169`). A refusal comes
   from width, a NULL spec, or a missing terminator unit.
2. **`C4_PANEL_SPEC.md:635`** (Q8): "no text window active" has no engine counterpart
   (`include/menu_input_state.h:6-16` is a BUTTONS/TOUCH selector). The predicate is fade +
   menu context + no resident child app.
3. **`C4_PANEL_SPEC.md:415`** (Q9): the `0x021E5900` sharing is measured **on HG** too —
   `heartgoldus.xMAP:53318` and `:130861`, with 46 groups sharing that START.
4. **`FEATURE_BAR.md:227`** (Q9): `0x60280` is ov1's own footprint
   (`BSS_END − START`), not the free window (`0x89340`). The constraint is `END ≤ 0x0226EC40`.
5. **`C4_PANEL_SPEC.md:328-330`** (SEQ): the id is read, not inferred —
   `include/constants/sndseq.h:1366` = 2368.

## 5. Seams this card left open, on purpose

Every item below is a `SlinkGen4PanelEngine` member rather than a decision, because the fact
behind it is unproven:

| Seam member | The fact that is missing |
|---|---|
| `menu_open` | no single engine predicate for "the START menu is the launching context" |
| `app_running` | the resident-child-app guard; optional (NULL = no such guard), and no rule yet says the panel needs it |
| `text` | carried from the record binding rather than restated, so Q7 can never drift |

No other Gen 4 fact was left as a seam. In particular the fade term is **not** a guess: it is
`IsPaletteFadeFinished()`, the trainer card's own precondition.