# RR storage menu: title-case strings, retained flow, and a gated input recipe

Research card gen3-P3-R8, 2026-09-21. Only this file created. No emulator, RAM writes, Python or commits. ROM evidence below is from `patch/build/slink_RR.gba` read with PowerShell. `pret:` means the local pokefirered c75f352 source at `E:/Google Drive/SLink/.cache/pret/pokefirered`; symbol citations are `data/gen3/pret/pokefirered.sym`.

## The missing strings are a case-search false negative

RR contains **Withdraw**, **Deposit**, and **Move** at precisely ROM offsets **0x001B5859**, **0x001B586C**, **0x001B587E**. Uppercase WITHDRAW/DEPOSIT searches returned no hits; the mixed-case encoding succeeds. Character bases: `server/adapters/gen3_codec.py:80-87` (uppercase BB, lowercase D5). Read bytes:

```text
001B5859 D1DDE8DCD8E6D5EBB2FF
001B586C BED9E4E3E7DDE8B2FF
001B587E C7E3EAD9B2FF
```

These are abbreviated UI strings, with special glyph B2 before FF. More importantly, the actual five storage-menu labels are referenced by the **unchanged table at ROM0x003CDA20** (symbol sMainMenuTexts :33456). Pointer/description pairs:

| Index | Label pointer / ROM offset | Label prefix in RR | Description pointer |
|---|---|---|---|
| 0 | 0841856C / 0041856C | Withdraw Pokémon (`D1DDE8DCD8E6D5EB00CAE3DF1BE1E3E2FF`) | 084185AD |
| 1 | 0841857D / 0041857D | Deposit Pokémon (`BED9E4E3E7DDE800CAE3DF1BE1E3E2FF`) | 084185E2 |
| 2 | 0841858D / 0041858D | Move Pokémon | 08418611 |
| 3 | 0841859A / 0041859A | Move Items | 08418642 |
| 4 | 084185A5 / 004185A5 | See Ya! | 08418681 |

Source table: `pret:src/pokemon_storage_system_menu.c:37-42`. The exact accented glyph is represented by the ROM's extended text encoding; this conclusion does not depend on searching a guessed plain-ASCII Pokémon spelling. The simpler title-case prefixes are sufficient known-positive search controls.

## Retained UI, with local modifications rather than wholesale replacement

RR retains the following entire vanilla function bodies byte-for-byte in direct comparisons against FireRed: ShowPokemonStorageSystemPC (ROM0008C6A8 length30), EnterPokeStorage (0008CDE4 length7C), Task_DepositMenu (0008DD88 length144). Task_PCMainMenu (0008C39C length30C) differs only in two eight-byte instruction windows:

* ROM **0008C3E0**: `004800479D470409` -> inline Thumb trampoline **0904479C**. Its replacement calls a helper and branches back through continuation literals 0808C3ED/0808C3FD (body sample ROM0104479C).
* ROM **0008C53C**: `00490847CD470409` -> inline trampoline **090447CC**. It reads byte **0203B7AC**, modifies the party-count decision, and resumes through 0808C545/0808C565 (body sample ROM010447CC). The semantic name of that RR byte is **UNVERIFIED**; do not bypass these restrictions in a driver.

Thus “no uppercase labels” does not establish compressed text or a different PC frontend. It is the retained five-option UI with two local patches and CFRU storage backend changes. Full runtime cursor behavior still requires a lane receipt. Pinned CFRU `src/pokemon_storage_system.c` was inspected via the revision in `docs/gen3/research/pins.md:124-146`; binary comparisons above, not upstream naming alone, establish which vanilla menu bodies survive. Backend compression/in-place changes are documented in `docs/gen3_engine_sites.md:360-438`.

ShowPokemonStorageSystemPC creates **Task_PCMainMenu=0808C39C**, sets task state0 and selected option0, then locks field controls (`pret:src/pokemon_storage_system_menu.c:354-359`). Its RR literal at ROM **0008C6D0** is **0808C39D** and following word is gTasks **03005090** (ROM0008C6A8..C6D7). State2 accepts input; selected option is task data[1]; state4 enters storage after fade (`:235-239,263-308,343-348`). This is a useful RAM terminal, better than menu screenshots alone.

## Input sequence: state-gated candidate, not a blind macro

Interpret **party slot2 as zero-based** (third mon), matching the project's slot APIs. If the coordinator means the second visible mon, substitute slot1 and one Down press. Preconditions: at PC-facing approach tile(11,2), field idle; party count at least3 with target allowed to deposit; box0 slot0 empty and box0 selected; no carried/multi-move selection. Preserve target PID:OTID and the identities/bytes of all survivors. Do not promise a fixed-frame or fixed-cursor sequence without these preconditions.

| Step | Inputs, separated by release and awaited terminal | RAM / engine terminal and evidence |
|---|---|---|
| Open PC | A; advance boot/login text with individual A taps until PC-choice menu is ready | Field locks and CreatePCMenu executes. Vanilla script selects storage on result0 (`pret:data/scripts/pc.inc:1-11,20-35`). Exact RR initial-script routing is not fully binary-traced here; census below must confirm |
| Select storage | First PC entry (Someone's/Bill's); A, then advance login text | ShowPokemonStorageSystemPC -> task0808C39C, task state2 and selected0. `pc.inc:46-55`; retained constructor bytes above |
| Choose deposit | Down once from selected0, verify selected1, A | Storage callback2 **0808CDC5** (even body0808CDC4); EnterPokeStorage argument1. Main-menu source :263-308,343-348; symbol :6145-6146 |
| Choose target | From party cursor0, Down twice with cursor feedback to2; A opens context menu; A chooses first action Store | Do NOT sweep arbitrary rows: deposit context's first action is Store (`pret:src/pokemon_storage_system_data.c:1465-1478,1504-1523,1755-1770`). RR cursor-global binding/initial cursor must be validated, see below |
| Choose box | In box chooser, select box0; A confirms | Task_DepositMenu calls TryStorePartyMonInBox(boxId), then compacts party (`pret:src/pokemon_storage_system_tasks.c:1189-1242`). There is a BOX chooser, not a generic yes/no confirmation. Default sDepositBoxId must not be assumed zero after prior use |
| Deposit proof | Wait for animation/task settle without more A | party count drops exactly1; target absent from party; exact target key appears in box0 slot0; other survivors preserved. Count alone cannot distinguish release |
| Return to storage mode menu | B; if the close-box confirmation appears, choose Yes with A, await Task_PCMainMenu state2 | Exact B/confirm count is **LIVE OPEN**. Stop at the task terminal; do not blindly keep A pressed. Returning menu can retain the old selected option (`pret:src/pokemon_storage_system_menu.c:362` onward) |
| Choose withdraw | Move cursor to selected0 (usually Up once from deposit1), verify, A | EnterPokeStorage argument0; storage callback2. Party must have free capacity; source menu :290-301 |
| Select box0 slot0 | Verify current box0 and box cursor0; A opens context menu, A chooses first action Withdraw | `pret:src/pokemon_storage_system_data.c:1767-1770`; Task_WithdrawMon :1136-1185 handles grab/party insertion, not an additional guessed yes/no dialog |
| Withdraw proof | Await completed transfer | exact target key back in party, box0 slot0 empty, party count restored, other records unchanged. Do not require target to return to original slot2: withdrawal can append |
| Exit | B/Yes only as needed to task/menu terminals, then B to leave menus | task removal, callback2=CB2_Overworld, inBattle clear, script context shutdown and controls unlocked (`write_checkpoint.json` predicates). Source menu :281-287; actual exit press count must be calibrated |

**This is the exact logical choice sequence, with unverified cursor/initial-script/exit timing explicitly marked.** No live input receipt was produced. It would be dishonest to present a universal fixed button-count macro while RR's initial menu state and persisted cursor/box choice remain unmeasured.

## RAM observables and evidence strength

* Party count **u8 02024029**, party records **02024284 + slot*100**, key **u32 PID+0/u32 OTID+4**: `lua/games/gen3_frlge.lua:199-200`, `lua/gen3/reads.lua:228-244,267-269`.
* RR box0 slot0 at **02029318**, compressed stride **58**, capacity30; profile derived.CFRU_BOX_BASES[1] and COMPRESSED_MON_SIZE (`data/games/gen3_rr/profile.json:144-173`; `docs/gen3/research/rr_save_layout.md:88-102`). Header PID/OTID survives compression; full byte equality with a100-byte party record is invalid. Compare key and decoded stable metadata, accounting for engine PP/stat reconstruction.
* gTasks **03005090**,16 entries, stride40, function u32+0, active u8+4; data[] starts+8. For active Task_PCMainMenu pointer0808C39D: state u16+8, selected option u16+10, accepted input u16+12 (`data/gen3/pret/pokefirered.sym:829`; RR checkpoint tasks; `pret:include/task.h` Task layout; storage_menu.c:235-243). Constructor/body literals corroborate this RR task array. Never identify a task merely by slot number.
* gMain.callback2 **u32 030030F4**; expected overworld **080565B5** from RR checkpoint callback2 row. Storage callback expected **0808CDC5**, .sym:6145. Inspect this in the census rather than interpreting an unresponsive menu as field idle.
* Field lock **u8 03000F9C ==0** and script status **u8 03000EA8 ==2** are RR checkpoint predicates (`data/games/gen3_rr/write_checkpoint.json:94-100,142-149`). Treat fade/menu states as held, not opportunities to blindly restart the menu.
* FR symbols sCursorArea **02039820**, sCursorPosition **02039821**, sDepositBoxId **020397B6**, gStorage pointer variable **020397B0** are at .sym:307,310,315-316. They are **candidate RR instrumentation, not fully rebound by this note**. Selected RR task bodies contain gStorage literals at the FR location (Task_WithdrawMon sample ROM0008DCB4 = B0970302); pin actual cursor reads/writes or log them alongside the census before trusting Down-tap arithmetic. Do not guess a gStorage structure offset for mode/current box.

## Coordinator census (10 function starts)

Names/starts from .sym:6125-6126,6145-6147,6153,6163-6164,6324,6726. All even.

```text
CreatePCMenu=0x0809D040
ShowPokemonStorageSystemPC=0x0808C6A8
Task_PCMainMenu=0x0808C39C
EnterPokeStorage=0x0808CDE4
CB2_PokeStorage=0x0808CDC4
CB2_ReturnToPokeStorage=0x0808CE60
Task_InitPokeStorage=0x0808D020
Task_DepositMenu=0x0808DD88
Task_WithdrawMon=0x0808DC9C
TryStorePartyMonInBox=0x080930E4
```

At EnterPokeStorage entry log R0 option; at Task_PCMainMenu log matching gTasks row/state/selection; at deposit/withdraw log key/count/box witnesses. If initial PC choice never reaches ShowPokemonStorageSystemPC, inspect actual special dispatch before changing the storage option order. If it does, the title-case string finding and retained option table remove the need for an arbitrary Down/A sweep.

## NOT VERIFIED

No claim of an RR-wide PC replacement, compression of these labels, live confirmation of the full input sequence, or safe use of unbound cursor globals. Unresolved: initial PC script/special table selection, mode cursor initialization, remembered current box, exit confirmation timing, and meaning of inline-hook flag0203B7AC. These require the bounded census and keyed before/after lane receipt. The failed uppercase string search is definitively corrected by the explicit ROM samples above.
