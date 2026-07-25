# Cross-validated addresses — Radical Red (md5 8529f3a45d32bce4da637976fcf269d4)

Every entry is derived **two ways** (plan §5): a named **symbol source** and the
**RR binary** itself (capstone via `patch/tools/disasm.py`). Both must agree.

Key validated finding: **RR preserves base FireRed engine addresses** — vanilla-FR /
CFRU `BPRE.ld` symbols resolve to correct, sane prologues in this RR build. So BPRE.ld
is a valid map for the base engine here.

| Symbol | Address | Symbol source | Binary confirmation (RR) |
|---|---|---|---|
| `gMain` | `0x030030F0` | BPRE.ld `gMain = 0x30030F0` | `SetMainCallback2` does `str r0,[r1,#4]` ⇒ callback2 @ gMain+4 = `0x030030F4` (also matches peer-ghost memory) |
| `SetMainCallback2` | `0x08000544` | BPRE.ld | `ldr r1,[pc]; str r0,[r1,#4]` ✓ |
| `CallCallbacks` callback2 dispatch | see hook below | pokefirered `main.c` CallCallbacks | disasm 0x8000510-0x800053E ✓ |
| `RunTasks` | `0x08077578` | BPRE.ld | `push {r4,r5,lr}` clean prologue, **not** CFRU-hooked ✓ |
| `AnimateSprites` | `0x08006B5C` | BPRE.ld | `push {r4,r5,r6,r7,lr}` ✓ |
| `CreateMon` | `0x0803DA54` | BPRE.ld `0x803DA54\|1` | `push {r4-r7,lr}; mov r7,r8; push{r7}; sub sp,#0x1c` ✓ (Phase 2) |
| `CreateMonWithNature` | `0x0803DD98` | BPRE.ld | (Phase 2) |

## Phase-0 injection sites (all binary-confirmed)

- **Hook site `0x0800051A`** — a **5× `mov r8,r8` (Thumb NOP) sled** (10 bytes) inside
  `CallCallbacks`, which runs **every frame, all contexts, main-thread**. RR/CFRU left
  it as NOPs (no existing hook). `lr` is already saved on the stack at the function
  prologue (`push {r4,lr}` @0x8000510), so a `bl` here may clobber `lr` safely. We
  overwrite the first **4 bytes** with `bl slink_hook`; the remaining 6 bytes stay NOP,
  so control falls through to the callback dispatch at `0x08000524`.
  - Binary: `0x0800051A..0x08000523 = C0 46 ×5` (confirmed via disasm).

- **Code region `0x08378F70`** (file `0x378F70`, `CODE_BASE`) — the `0xFF` free run that
  resumes right after the bundled RR4.1_Custom **Battle Calc** block (which owns
  `0x08378CA8..0x08378F6F`); `0x14638` ≈ 81 KB free. Distance from the hook `0x0800051A`
  is `0x378A52` ≈ 3.62 MB, **within Thumb BL ±4 MB range**. Holds the trampoline +
  dispatcher + per-opcode handlers. `build.py` asserts this region is all-`0xFF` (after the
  Battle Calc is applied) before injecting, so it can never clobber the Battle Calc or engine.
  - On a plain base RR (no Battle Calc) `0x08378CA8` itself is free; `CODE_BASE` was moved to
    `0x08378F70` purely to coexist with the bundled Battle Calc — see "Bundled RR4.1_Custom
    Battle Calc" below.

- **Mailbox `0x0203F800`** (EWRAM) — above CFRU's highest known EWRAM symbol
  (`0x0203F3AE`), below EWRAM end `0x0203FFFF`.
  **Runtime-validated**: watched for stray writes across gameplay before trusting
  (Phase-0 gate). Mailbox is ≤256 bytes.
  > **The gap below the mailbox is NOT free space.** An earlier revision of this file described
  > "~0x450 bytes margin" between `0x0203F3AE` and `0x0203F800`; that reads as headroom and it
  > isn't. `0x0203F3AE` is the ceiling of an *incomplete* symbol list, and a scan of the ROM finds
  > that window densely referenced from engine/libc code. Do not allocate below `0x0203F800`.

## EWRAM allocation map (the single source of truth)

Every address here is a `#define` in `handlers.c`; the sizes were confirmed by compiling
`_Static_assert(base + sizeof(T) == end)` for each struct with the vendored toolchain. Keep this
table in step with `handlers.c` — four blocks (`ArmedMove`, `GHOST_PAL_BUF`, `UiState`,
`SLINK_MENU_BUF`, 164 B in total) once existed only in the source, so anyone allocating from this
document alone would have clobbered live state.

| start | size | what |
|---|---|---|
| `0x0203F800` | 64 | Mailbox (ABI v1) |
| `0x0203F840` | 8 | `SwapState` — borrowed-party / Party Freeze |
| `0x0203F848` | *8* | — gap |
| `0x0203F850` | 44 | `GhostState` |
| `0x0203F87C` | *68* | — gap (largest interior block) |
| `0x0203F8C0` | 8 | `ArmedMove` |
| `0x0203F8C8` | *8* | — gap |
| `0x0203F8D0` | 4 | `SlinkState` (`pi_*` peer-interact) |
| `0x0203F8D4` | 4 | `TradeNpcState` |
| `0x0203F8D8` | 1 | `SLINK_CALC_OFF` — Battle-Calc kill switch |
| `0x0203F8D9` | *7* | — gap |
| `0x0203F8E0` | 32 | `SLINK_SCRIPT_BUF` (18 B max used) |
| `0x0203F900` | 256 | `SLINK_TEXT_BUF` — FR text staging |
| `0x0203FA00` | 600 | `SLINK_BLOB_BUF` — party/enemy mon blobs |
| `0x0203FC58` | *8* | — gap |
| `0x0203FC60` | 32 | `GHOST_PAL_BUF` |
| `0x0203FC80` | 12 | `UiState` |
| `0x0203FC8C` | *4* | — gap |
| `0x0203FC90` | 112 | `SLINK_MENU_BUF` — multichoice options |
| `0x0203FD00` | 8 | `BattleNotif` |
| `0x0203FD08` | *8* | — gap |
| `0x0203FD10` | 52 | `EvRing` |
| `0x0203FD44` | 264 | `SlinkInfo` — §6 SOULLINK menu/info (see below) |
| `0x0203FE4C` | *436* | — **free tail, the last contiguous run to `0x0203FFFF`** |

**436 contiguous bytes remain**, plus 111 across seven interior gaps (largest 68 B). When the tail
is gone the next feature must reuse a buffer or fragment; say so here rather than letting it be
discovered the expensive way.

**The tail is runtime-proven free, not inferred.** `lua/tests/test_live_ewramtail.lua` paints all
700 bytes of `0x0203FD44..0x0203FFFF` with a per-address pattern and watches them across seven
savestates and 5,100 frames of mashed input (overworld, Pokécenter, a door warp, battle, the
action/move menus), with a detector self-check each scene — it clobbers the mailbox beacon and
requires the frame hook to restore it, so the watch cannot silently pass while blind. Zero bytes
changed. This matters because the *static* argument for the region was wrong twice: "above CFRU's
highest known symbol" is an incomplete list, and a ROM literal-pool scan offered as backup turned
out to be measuring coincidental word matches inside PCM and graphics data, not literal pools.

> Suspected, unproven, and unrelated to §6: six 4-aligned words at `SLINK_BLOB_BUF+0x174..0x188`
> (`0x0203FB74`–`0x0203FB88`) are referenced from code at `0x081E82DC`–`0x081E89F0` that
> disassembles as a heap free-list allocator. If it ever runs while a 4+ mon rival-team-swap stage
> is live, the stage would be corrupted. The live gates pass, so it may never execute — but a
> future reuse of `SLINK_BLOB_BUF` should stop at `+0x174` until someone watches it.

## §6 SOULLINK start-menu entry

`SlinkInfo @ 0x0203FD44` (264 B, ends `0x0203FE4C`): `{u8 enable, opened, drawn, lines, page,
pages, gen, _pad; u8 line[8][32]}`. Every byte's zero value reproduces pre-feature behaviour —
`enable=0` splices no row *and* makes the callback tail-call the row it displaced, `opened==drawn`
means the frame hook never draws, `lines=0` makes the screen refuse to open.

RR reads the start menu's description and action arrays through **one** base literal `0x09148FB4`
with hardcoded offsets — `desc[i] = *(base+8+4i)` (13 entries, ending `0x09148FEF`) and
`action[i] = base+0x3C+8i` (13 entries). Those ranges **abut**: `desc[13]` *is* `act[0].text`. So a
14th action id cannot own a description without re-encoding compiled CFRU `ldr` immediates. We take
over **id 8** instead — a second PLAYER row that only `SetUpStartMenu_Link` appends, and which
`lua/tests/test_live_startmenu.lua` proves absent from the menu a real player opens.

`build.py` rewrites four words, each verified against its expected current value first:

| ROM word | was | becomes |
|---|---|---|
| `0x09148FDC` (`desc[8]`) | `0x0841A049` | `sSoulLinkDesc` |
| `0x09149030` (`act[8].text`) | `0x0841628E` | `sSoulLinkLabel` |
| `0x09149034` (`act[8].func`) | `0x0806F56D` | `slink_startmenu_cb\|1` |
| `0x0806ED58` (`SetUpStartMenu` literal) | `0x090BE179` | `slink_setup_start_menu\|1` |

Menu globals, both located live: **`sNumStartMenuActions = 0x020370F5`**, **`sStartMenuOrder =
0x020370F6`**. A normal field menu is exactly `[1 2 3 4 5 6]` with EXIT (id 6) last, so the wrapper
splices SOULLINK at index 5 and pushes EXIT to 6 — and it splices *only* into that exact shape, so
the link menu and any future RR revision are left alone rather than guessed at.

### The info screen (opcode 27)

`show_info_entry` is a **sibling** of `show_choices_entry`, not an extension — that one rejects
`count > 8` and its shape (measure the widest option, size the window to it, wrap the cursor) is
option-list logic. Both share `run_ui_script()` for the `lockall ; callnative ; waitstate ;
releaseall ; end` bracket.

It hands input to the engine's multichoice task with **count = 1**. A *or* B then closes the
window, tears it down and resumes the script for free, and `drive_ui` kind 1 publishes which was
pressed — `result[0]` = `0` (A) or `0x7F` (B). That difference **is** the pagination protocol; there
is no separate "next page" opcode.

> **A `callnative` target inside a `lockall` script must never fail to create its input task.**
> `waitstate` is resolved only by that task, so an early `return` leaves the player in a locked
> overworld with no window and no way out. The staged panel is validated *before* the script is set
> up (`info_lines_ok()` → `ack(ST_FAIL, 2)`), and `show_info_entry` clamps and repairs rather than
> bailing. The first run of `test_live_infoscreen` caught exactly this — a malformed stage came back
> with no status at all because the script never resolved. `show_choices_entry` still has the
> original bailing shape and the same latent softlock.

#### Window tile budget — a hard ceiling that is easy to blow

`CreateWindowFromRect` hardcodes **baseBlock `0x38`**, and the field message-box window's template
(`0x0841F42C`) has baseBlock **`0x198`**. The usable range is therefore `0x038..0x197` = **352
tiles**, and `width * height` must fit inside it.

At width 27 the **maximum height is 13** (351 tiles, ending `0x196`). The first shipped version of
this screen used `27 x 14` = 378 tiles and overran the message-box window by 26 — fixed to
`CreateWindowFromRect(1, 2, 27, 13)`.

> **`show_choices_entry` has the same latent overrun.** It calls `CreateWindowFromRect(left, 1,
> width, sMcHeight[count])`; with `count == 8` (`sMcHeight[8] = 14`) and a `width` near its 27
> clamp it spends up to 378 tiles. For `run_choices(with_text=1)` the message box it would corrupt
> is a **live** one. It needs a combined `width * height <= 352` guard, not just the width clamp.

#### Looking native

Derived from RR's own screens (captured by `lua/tests/_ref_screens.lua`): the trainer card, the
Pokémon Info page, OPTIONS and the party menu. The closest engine analogue is the start-menu
**save-stats box** (`PrintSaveStats`, alive in RR at `0x0806FCF4`) — one framed window, coloured
header, hairline rule, small-font rows at fixed x with explicit colour triples.

| element | how |
|---|---|
| frame | `SetStandardWindowBorderStyle(win, 0)` — draws the **player's OPTIONS frame choice**, so the panel matches whatever they picked |
| colour | `AddTextPrinterParameterized4` @ `0x0812E5A5`, taking an explicit `{bg, fg, shadow}` triple. Canonical: body `{1,2,3}`, accent/blue `{1,8,9}`, alert/red `{1,4,5}` |
| title | ROM const, `FONT_NORMAL`, blue, top-left |
| page hint | right-aligned at `216 - GetStringWidth(...)`, with the menu cursor parked beside it — the `▲Page ✕Cancel` convention off the Pokémon Info page. `GetStringWidth` is pixel-exact for English (renderer and measurer both skip `letterSpacing` outside Japanese mode), so right-align needs no fudge |
| rule / HP bars | `FillWindowPixelRect` @ `0x08004379` (clips internally) |
| `Lv` | the engine's own glyph, FR bytes `F9 05` |
| fonts | `FONT_SMALL` (0) is 8x13, `FONT_NORMAL` (2) is 10x14. Rows use SMALL at a 13px pitch: 6 rows in the 104px content area |

**Row kind is derived from the field count**, not stored — slots are split on `0xFE`, which
`MB.fr_encode` already emits for `"
"`. 5 fields = a party-menu-style mon row (area, name, `Lv`,
HP text, bar px), 2 = label/value, 1 = full-width text. So the `SlinkInfo` contract is unchanged and
Lua can mix row kinds on a page without the patch knowing anything about the content. The split
copies to a stack buffer rather than editing in place, so redrawing the same stage is idempotent.

Bar colour uses FRLG's own >50% / >20% thresholds as two compares on the pixel width — **no
division anywhere**, because this blob has no libgcc (`/` on a runtime value emits an undefined
`__aeabi_uidiv`). Lua does the HP→pixels division and stages the result. `barpx == 0` renders the
name and HP text in red and leaves the bar empty: that is the fainted signal.

LIVE (`test_live_infoscreen`): rejects an empty panel and an unterminated line without locking the
field, draws (BG VRAM changes), renders all three row kinds, asserts the panel's own tiles actually
contain blue/red/green (a flat-black screen would otherwise pass), A→`0` and B→`0x7F` both close and
release, and it reopens cleanly.

The callback deliberately **does not draw**: it bumps `opened` and tail-calls `StartMenu_Exit`
(`0x0806F541`, which is already `act[6].func` and therefore proven safe in this slot). That is what
makes the hook gateable on its own. LIVE (`test_live_soullinkmenu`): stock 6-row menu when
disabled, `[1 2 3 4 5 8 6]` when enabled, and the callback fires on row 5 **and no other row**.

- **SwapState `0x0203F840`** (EWRAM, 8 B) — authoritative borrowed-party ("Party Freeze")
  signal, published struct (read-only mirror for Lua), in the free gap between the mailbox
  (ends `0x0203F840`) and GhostState (`0x0203F850`). Fields: `u8 active` (1 while a borrowed/
  preset party is installed), `u8 seq` (++ on each begin edge — Lua triggers the freeze on the
  edge), `u8 diverged` (internal latch), `u8 _pad`, `u32 real_pid` (`gPlayerParty[0]` PID at
  begin). **Begin** is hooked authoritatively: build.py redirects CFRU BackupParty's two
  party→backup memcpy `BL` sites (`0x0804C10C`, `0x0804C212`, both `BL 0x081E5E78`) to
  `slink_backup_wrap`, which does the real copy then flags begin once (guarded on dst ==
  `REAL_PARTY_BACKUP 0x02025564`). **End** is per-frame in `drive_swap_state`: clear `active`
  once `gPlayerParty` matches the backup buffer again after diverging (RestoreParty memcpy
  `0x0804C254` is left unhooked). Hook sites discovered live via
  `lua/tests/probe_party_backup_writer.lua`.

- **SLINK_CALC_OFF `0x0203F8D8`** (EWRAM, 1 B) — Battle-Calc display kill switch, right after
  TradeNpcState (`0x0203F8D4`, 4 B) in the gap before `SLINK_SCRIPT_BUF 0x0203F8E0`. **INVERTED**:
  `0` (EWRAM boot default — no Lua/config) = calc SHOWN as today; `1` = `slink_battletext_hook`
  skips the calc trampoline, replays the two displaced halfwords (clean RR `0x080D87BE`:
  `mov r7,r8` ; `push {r7}`) and resumes the function body at `0x080D87C3` — as if the calc patch
  weren't installed. Driven by the per-run `battle_calc` toggle (`MB.set_battle_calc`). LIVE
  (`test_live_calctoggle`: A-mash battles + flip churn, both paths).

- **EvRing `0x0203FD10`** (EWRAM, 52 B, ends `0x0203FD44`) — native→Lua event-push ring, after
  BattleNotif (ends `0x0203FD08`).
  `{u8 wr, u8 rd, u8 overflow, u8 inb, u8 pfc, u8 ofc, u8 prim, u8 pcnt, u32 ev[8], u16 spc[6]}`;
  events packed `type | a<<8 | b<<16`. Producers (`drive_events`, every frame):
  - **EV_PLAYER_FAINT=1 / EV_FOE_FAINT=2** on `gBattleResults` (`0x03004F90`, player@+0 foe@+1)
    counter deltas — they bump only AFTER Sturdy/Sash/Endure resolve (the authoritative settle
    signal). `a` = the counter value after the bump.
  - **EV_OUTCOME=3** with `gBattleOutcome` on the end-of-battle edge.
  - **EV_PARTY_ADD=4** when `gPlayerPartyCount` grows (catch / gift / withdraw / trade-in);
    `a` = new count, `b` = species of the slot that appeared.
  - **EV_EVOLVE=5** when a party slot's species changes IN PLACE (both sides nonzero — a slot
    filling or emptying is not an evolution); `a` = slot, `b` = the new species. CFRU is
    NO_ENCRYPT with fixed substruct order, so species is a raw u16 at `mon + 0x20`.

  Frame-granular polling was chosen over BL hooks (`Cmd_tryfaintmon`, `EvolutionScene`) deliberately:
  same settle semantics, zero new detours, zero battle/script reentrancy — and 7 reads a frame is
  cheaper than the per-frame party DECRYPTION it replaces on the Lua side.

  The producer's prev-state latches live IN the struct (our ROM blob has no .data/.bss — mutable
  statics are impossible). `prim` (+6) is the party-latch primed flag: **0 makes the next frame latch
  only**, which is what keeps the all-zero EWRAM boot default reproducing pre-producer behaviour
  instead of replaying the existing party as events. The party producers are suppressed entirely
  while `SwapState.active` (a borrowed Battle-Tower/Poke-Dude party replaces `gPlayerParty` wholesale
  — every slot would read as evolved) and `prim` is cleared so they re-prime against the real party.

  Lua: `MB.events_init/events_drain`, `MB.EV_*`, `MB.EVR_PRIM`. LIVE: `test_live_events` (single
  bump, multi-bump delta, overflow drop+flag+recover), `test_live_partyevents` (prime-emits-nothing,
  in-place evolve, fill-is-not-evolve, stone/trade evolution with key+level unchanged, count growth,
  shrink emits nothing).

  Consumers: EV_PLAYER_FAINT and EV_OUTCOME drive behaviour (faint fast-path, whiteout
  acceleration). EV_PARTY_ADD and EV_EVOLVE are a cross-check that asserts the ring agrees with the
  Lua diff and counts disagreements — the soak instrument the §3 authority swap is waiting on. See
  `ev_xcheck` in `lua/clients/gen3_frlge_client.lua`.

## Bundled RR4.1_Custom Battle Calc (in-battle damage calculator)

The emitted patch folds in the **Battle Calc**, extracted as a base-RR → RR4.1_Custom UPS
delta (`rr41_battle_calc.ups`, regenerate via `tools/make_battle_calc_patch.py`) and applied
before SLink injection. It is the same RR build as ours run through a customizer: **3,412
bytes in 13 regions** (base RR `8529f3a4…` → custom `b50b3a51…`; integrated-output md5
`7f3be72b…`). All engine/controller addresses above are **unchanged** by it — verified
byte-identical.

**Battle Calc = an in-battle damage / type-effectiveness calculator.** All addresses resolved
against `BPRE.ld` and disassembled (capstone):

- **Detour** `0x080D87BE` = `BL 0x08378CA8` over `BattlePutTextOnWindow`'s prologue.
- **Trampoline `0x08378CA8` (712 B)**: masks the window id (`r1 & 0x3F`), reads
  `gMoveSelectionCursor` (`0x02023FFC`), formats a colored decimal number (FR control codes
  `0xFC 01 04/06` + digit charmap `0xA1`=‘0’) into CFRU scratch `0x0203F200`, calls
  `BattlePutTextOnWindow`.
- **New funcs `0x09360000`–`0x09360F17` (~2.7 KB)**: `0x9360C00` reads `gBattleMons` type
  `+0x20` / ability `+0x1B` / item `+0x4C` / move `+0x2E` and applies `×3`/shift multipliers
  (type-effectiveness); `0x9360400` is a PID^OTID checksum guard caching into
  `gNewBS`/`0x0203F000`; `0x9360000` builds the string over `gDisplayedStringBattle`,
  installed via a redirected pointer at `0x08069C54` (`0x090B1C58 → 0x09360341`).
- **Trivial extras**: one move name edited (`gMoveNames+0x1304`, 4 B) + an 8-byte config
  tweak at `0x083FEC02`.

**Disjoint from SLink** (so they coexist): SLink hook `0x0800051A` ≠ mod hooks
(`0x080D87BE`, `0x08069C54`); SLink EWRAM `0x0203F800+` vs mod EWRAM `≤0x0203F200` /
`gNewBS 0x0203E038`; SLink code relocated to `0x08378F70`, just above the mod's
`0x08378CA8` block. IPS cannot ship this (Battle Calc code at file `~0x1360000` > 16 MB) — UPS only.

### The 13 changed regions
| ROM | bytes | what |
|---|---|---|
| `0x08069C54` | 4 | redirected fn-pointer → new code `0x09360341` |
| `0x080D87BE` | 4 | `BL` hook over `BattlePutTextOnWindow` |
| `0x08248398` | 4 | move-name string edit (`gMoveNames+0x1304`) |
| `0x08378CA8`–`0x08378F6F` | 712 | trampoline (SLink moved above it) |
| `0x083FEC02` | 8 | config/data tweak |
| `0x09360000`/`0400`/`0C00` | ~2.7 K | new damage-calc + string functions |
| 5× `0x0904D…0x090AC…` | ~30 | small table records |

## Mailbox ABI v1 (little-endian)

| off | type | field | meaning |
|---|---|---|---|
| 0 | u32 | signature | `'SLNK'` = bytes `53 4C 4E 4B` (u32 LE `0x4B4E4C53`). Written every frame ⇒ Lua presence beacon. |
| 4 | u16 | abi_version | `1` |
| 6 | u16 | opcode | Lua writes; dispatcher clears to 0 when consumed. `0`=idle, `1`=PING |
| 8 | u16 | seq | Lua increments per command |
| 10 | u16 | status | `0`=idle `1`=busy `2`=ok `3`=fail |
| 12 | u16 | ack_seq | dispatcher echoes `seq` when done |
| 14 | u16 | reason | fail reason code |
| 16 | u8[32] | args | opcode arguments |
| 48 | u8[?] | result | opcode result bytes |

### Opcodes
| op | name | args | effect |
|---|---|---|---|
| 1 | PING | — | ack ok (presence/round-trip check) |
| 2 | FORCE_FAINT | `[0]`=battler | `gBattleMons[battler].hp = 0` |
| 3 | FORCE_MOVE | `[0]`=battler `[1]`=target `[2]`=move_pos `[4..5]`=move_id(u16) | commits a forced move (see below) |
| 4 | CREATE_MON | `[0]`=slot `[1]`=party(0=player,1=enemy) `[2..3]`=species(u16) `[4]`=level `[5]`=bump_count | engine `CreateMon` into party[slot]; `bump`=GIVE_MON (sets party count → usable member) |
| 5 | FORCE_MOVE_SLOT | `[0]`=battler `[1]`=target `[2]`=move_pos | **live** forced move via controller-swap (see below) |
| 6 | SPAWN_PEER_NPC | `[0]`=gfxId `[1]`=localId `[2..3]`=x `[4..5]`=y `[6]`=movement → `result[0]`=objEventId | spawn a real engine object-event NPC |
| 7 | DESPAWN_PEER_NPC | `[0]`=objEventId | DestroySprite + clear object-event (clean removal) |
| 8 | SHOW_MESSAGE | text pre-written (FR-encoded) to `0x0203F900` → `result[0]`=shown | native field message box (`ShowFieldMessage`) |
| 9 | PLAY_FANFARE | `[0..1]`=songId | `PlayFanfare(songId)` |
| 10–12 | _(reserved)_ | — | **REMOVED** — were APPLY_DAMAGE / CURE_STATUS / SET_RULES (linked chip / status / nuzlocke battle-style). Dropped: chip+status as features, set-mode/level-cap is native to RR. Numbers kept reserved (no dispatch case → ack ST_FAIL); see "Removed opcodes" below |
| 13 | ARM_PEER_INTERACT | `[0]`=ghost oeId `[1]`=armed | talk-to-ghost detection (legacy; ghost auto-arms now) |
| 14 | GHOST_SPAWN | `[0]`=gfxId `[1]`=localId | engine-driven peer ghost: hook spawns+walks it via held movements (GhostState@0x0203F850) |
| 15 | GHOST_CLEAR | — | hook cleanly removes the ghost (RemoveEventObject) |
| 16 | SET_ENEMY_PARTY | `[0]`=count; blobs staged in `0x0203FA00` | faithful byte-copy of count×100 party-mon bytes into `gEnemyParty` + set count (rival-team-swap) |
| 17 | SHOW_MENU | text (FR-encoded) in `0x0203F900` → `result[0]`=choice (1=YES 0=NO) | native YES/NO field menu (`yesnobox`); **async** — ack ST_BUSY, `drive_menu` publishes `gSpecialVar_Result`@`0x020370D0` when the script ends. Talk-to-partner menuing foundation. |
| 18 | SET_PARTY_MON | `[0]`=slot `[1]`=bump; one blob staged in `0x0203FA00` | faithful 100-byte blob copy into `gPlayerParty[slot]` (trade — mirror of SET_ENEMY_PARTY) |
| 19 | PLAY_SE | `[0..1]`=songId | `PlaySE(songId)` @`0x080722CC` — native sound effect (retires the Lua m4a SE1 RAM-poke) |
| 20 | CHOOSE_PARTY_MON | — → `result[0]`=slot(0-5)/7=cancel | native "Choose a POKéMON" menu via `callnative InitPartyMenu` (FR `special` idx is reordered on RR); ASYNC, `drive_ui` publishes Var8004 |
| 21 | TRADE_SCENE | `[0]`=slot | native in-game trade animation+evolution via `callnative DoInGameTradeScene` @`0x08054440` (RE'd); trades `gPlayerParty[slot]` ↔ `gEnemyParty[0]`; ASYNC |
| 22 | SHOW_CHOICES | options FR-encoded in `SLINK_MENU_BUF` (`[u8 count][str 0xFF]...`) → `result[0]`=index/0x7F=cancel | native multichoice list (custom labels); replicates `DrawVerticalMultichoiceMenu` in C (`CreateWindowFromRect 0x809D654`, `SetStandardWindowBorderStyle 0x80F7750`, `AddTextPrinterParameterized 0x8002C48`, `CopyWindowToVram 0x8003F20`, `Menu_InitCursor 0x810F7D8`, `CreateTask 0x807741C` → `Task_MultichoiceMenu_HandleInput 0x809CC98`, `GetStringWidth 0x8005ED4`, `ScheduleBgCopyTilemapToVram 0x80F67A4`); FONT_NORMAL=2, gTasks=0x3005090. ASYNC (lockall-bracketed, drive_ui kind 1) |
| 24 | DEPOSIT_MON | `[0]`=partySlot `[1]`=boxId `[2]`=boxPos | party→PC box (CFRU `CreateCompressedMonFromBoxMon` + shift-compact party). LIVE (`test_live_boxsync`). See "PC storage / box migration reference" |
| 25 | WITHDRAW_MON | `[0]`=boxId `[1]`=boxPos `[2]`=partySlot | PC box→party (CFRU `CompressedMonToMon`; engine recomputes level/stats/PP). LIVE (`test_live_boxsync`) |
| 26 | MEMORIALIZE | `[0]`=partySlot `[1]`=boxId `[2]`=boxPos | party→memorial box. Same compress as DEPOSIT_MON but removal is **zero + SWAP-WITH-LAST** (not shift) so survivors keep their slot indices — CFRU's deferred battle writes target slots (mirrors Lua `M.memorializeMon`). Lua picks the free memorial slot + renames boxes. LIVE (`test_live_memorialize`) |
| 23 | SHOW_BATTLE_MESSAGE | `[0..1]`=duration frames, `[2]`=window id (0→`0xD`). FR text in `SLINK_TEXT_BUF` | **native IN-BATTLE text** (the BizHawk-HUD-in-battle replacement), drawn into the Battle Calc's move-info window (`0xD`, top-left). `BattleNotif`@`0x0203FD00` {active,win,task,phase,frames}. **Two parts:** (1) build.py RE-POINTS the calc's `BattlePutTextOnWindow` detour @`0x080D87BE` (was `BL 0x08378CA8`) to naked shim `slink_battletext_hook` → `slink_battle_inject` swaps the text ptr for window `BN->win` IN-CONTEXT (inside the engine's draw), then `bx 0x08378CA9` (calc trampoline). REAL callable entry = `0x080D87BD` (prologue @`0x080D87BC`), NOT the detour @`0x080D87BE`. (2) `drive_battle_notif` `CreateTask`s `slink_notif_task` which draws every frame via **RunTasks** (the in-context point — calling `BattlePutTextOnWindow` from the slink_hook frame hook WHITE-OUTS the BG); on teardown draws an empty FR string then `DestroyTask 0x08077508` (poking the task struct @+0 corrupts the FUNC ptr → RunTasks crash; isActive@+4). SYNC ack |

**RR `gSpecials` is REORDERED** — the FireRed `special` indices (e.g. ChoosePartyMon 170, DoInGameTradeScene
265) DO NOT work on RR (live-proven no-ops). The native menus/scene are invoked **by address** via CFRU's
`callnative` (script-cmd `0x23` + 4-byte fn ptr). `InitPartyMenu = 0x0811EA44`, `Task_HandleChooseMonInput
= 0x0811FB28`, `CB2_ReturnToField = 0x080567DC` (BPRE.ld). **`DoInGameTradeScene = 0x08054440`** was RE'd
(`patch/tools/find_trade_scene.py`): the tiny fn LockPlayerFieldControls→CreateTask(Task_InGameTrade,10)→
BeginNormalPaletteFade(-1,0,0,16,0)→HelpSystem_Disable whose task installs CB2 `0x080505CC` (references
gSelectedTradeMonPositions + Var8005 + gEnemyParty = the in-game NPC trade). `gSpecialVar_0x8004=0x020370C0`,
`0x8005=0x020370C2`. Script-cmd bytes: setvar 0x16, callnative 0x23, special 0x25, waitstate 0x27.

**Trade/party-write globals used by opcodes 17–22** (CFRU `event_data.h` ↔ live RR profile):
`gSpecialVar_Result = 0x020370D0` (yes/no + multichoice chosen index), `gPlayerPartyCount = 0x02024029`,
`gEnemyPartyCount = 0x0202402A` (u8 member counts, bumped by SET_PARTY_MON/SET_ENEMY_PARTY). The trade
scene's "X sent over Y" text is overridden each frame from the staged `gEnemyParty[0]` plaintext
(NO_ENCRYPT: nickname @+0x08 (11 b), otName @+0x14 (8 b)) into `gStringVar3 = 0x02021D04` (received
nickname) and `gStringVar1 = 0x02021CD0` (received OT); `gStringVar2`/`gStringVar4 = 0x02021D18`.

> **Function-pointer convention:** the address tables above list **bare** ROM addresses; `handlers.c`
> ORs the Thumb bit (`addr | 1`) on every function pointer it calls (e.g. table `0x809D654` →
> code `0x0809D655`). A `+1` between this doc and the code is that Thumb bit, not a mismatch.

**SHOW_MESSAGE (8) is now DISMISSABLE** — it routes through the same `run_sign_msgbox()` script path
as talk-to-ghost (ScriptContext1_SetupScript + MSGBOX_SIGN), not bare ShowFieldMessage, so the
"partner waved at you" box closes on A.

## Phase-5 (peer interaction) — validated
EWRAM state `SlinkState @ 0x0203F8D0` {_rsvd0, pi_armed, pi_oe, pi_count} (`_rsvd0` = the removed
`enforce_rules` byte, kept to pin the `pi_*` offsets). The frame hook runs `check_peer_interact()`
every frame (no-op until armed).
- **ARM_PEER_INTERACT** (talk-to-ghost): each frame, if A is newly pressed (`gMain`(0x030030F0)+0x2E &
  0x0001) and the tile in front of the player (object-event facing@0x18: 1=down/2=up/3=left/4=right)
  equals the ghost object-event's tile, bump `pi_count` (the client polls it to notify the server/
  partner) and run a NAVIGABLE dialogue. Live: A-press facing the ghost -> counter++, native box
  shown, **no softlock** (a real engine-spawned NPC handles A-press cleanly, unlike the old hand-clone).
- **Dismissable dialogue (not bare ShowFieldMessage).** `ShowFieldMessage` only draws a box; the
  close (wait-for-A -> hide -> unlock) is script-driven, so on its own it sticks open. Instead the
  handler builds a 9-byte field script in EWRAM `SLINK_SCRIPT_BUF=0x0203F8E0`:
  `loadword 0, 0x0203F900` (`0F 00 00 F9 03 02`) ; `callstd MSGBOX_SIGN` (`09 03`) ; `end` (`02`),
  and runs it via `ScriptContext1_SetupScript = 0x08069AE4` (Thumb). `gStdScripts = 0x8160450` (10
  entries; **MSGBOX_SIGN = callstd index 3** = lockall/message/waitmessage/waitbuttonpress/releaseall
  — a real A-to-advance/dismiss conversation). Guard: skip if `sScriptContext2Enabled`(`0x03000F9C`)
  != 0 (a dialogue is already up) so mashing A mid-conversation doesn't re-trigger. Live-validated
  (`test_live_peerinteract` on rebuilt ROM: counter++, message shown, no softlock).

## Removed opcodes (10 APPLY_DAMAGE, 11 CURE_STATUS, 12 SET_RULES)
These were built + live-validated but never wired, and are removed to reclaim ROM/EWRAM:
- **APPLY_DAMAGE / CURE_STATUS** (linked chip / link-cured status, `gBattleMons` hp@0x28, status1@0x4C):
  the shared-fate linked-battle mechanics were **dropped as features** for RR.
- **SET_RULES** (ROM-enforced battle-style SET / nuzlocke): **redundant on RR** — the base hack already
  enforces set mode + level caps and ships a toggleable infinite repel.

Opcode **numbers 10–12 stay reserved** (no dispatch case → `default: ack(ST_FAIL, 1)`, same as an
older patch) so 13+ keep their ABI slot; `SlinkState._rsvd0` pins the `pi_*` offsets. For a future,
less-featured base game these are easy to re-add: chip = `hp -= amount` clamp 0 (engine refreshes the
health box, CFRU copies gBattleMons.hp→party at battle end so it persists); status = zero status1;
set-rules = OR `optionsBattleStyle` SET (bit 9 / 0x0200 of options u16 at `*gSaveBlock2Ptr`+0x14).

## Phase-4 (native UI) — validated
`ShowFieldMessage = 0x0806943C` `(const u8 *str)` — copies `str` (FR-charmap, 0xFF-terminated) into
`gStringVar4` (0x02021D18), starts the text printer, and creates a task the overworld's RunTasks
drives → a transient native message box. Returns FALSE if a box is already up. Lua writes the
FR-encoded text to `0x0203F900` (via `MB.write_message`/`MB.fr_encode`: space=0x00, 0-9=0xA1, A-Z=0xBB,
a-z=0xD5, EOS=0xFF) then sends SHOW_MESSAGE. `PlayFanfare = 0x08071C60`. **Live-validated**
(`test_live_message.lua`): SHOW returns shown→busy, gStringVar4 holds the text, no crash; fanfare acks.
**Deferred:** a *persistent* shared status bar (badge/area/HP) — high-effort persistent-UI that fights
the field window system and duplicates the existing dashboard/OBS overlays; the message box is the
high-value native-UI win.

## Phase-3 (peer NPC) — validated
Spawn a **real engine object-event** so the engine owns its sprite/palette/VRAM/callback —
retiring the 24-round Lua peer-ghost saga (whose corruption was all about a hand-cloned sprite's
engine-managed resources). `SpawnSpecialObjectEventParameterized = 0x0805E830` (vanilla-FR fn, RR
preserves it) `(gfxId, movementBehavior, localId, s16 x, s16 y, u8 elevation)` — **takes
camera-offset coords and subtracts MAP_OFFSET (7)**, so pass `gObjectEvents` `currentCoords`-style
coordinates. Returns the object-event id (≥16 = failed). `DestroySprite = 0x08007280`.
`gObjectEvents = 0x02036E38` (stride 0x24: flags@0, spriteId@4, gfx@5, movementType@6, localId@8,
currentCoords x@0x10/y@0x12, facing@0x18); `gSprites = 0x0202063C` (stride 0x44; inUse = byte@0x3E bit0).

**Live-validated** (`test_live_spawnnpc.lua`): SPAWN creates an active object-event + allocated
sprite at the target tile; DESPAWN clears it and frees the sprite. **Per-frame position/facing
driving stays in Lua** (the existing `peer_ghost.lua` smooth-tracking logic, now driving the
engine-spawned sprite — no clone, so no callback/palette/VRAM corruption). The NPC is spawned with
`movementType=NONE` so its engine callback won't fight the Lua-driven position.

## Phase-2 (CREATE_MON) — validated
`gPlayerParty = 0x02024284` (BPRE.ld ↔ SLink RR profile), MON_SIZE 100; party struct
level@0x54, hp@0x56, maxHP@0x58 (plaintext, outside the encrypted substruct). `CreateMon`
@ `0x0803DA54` called via fixed-address function pointer from injected C. **Live-validated**
(`test_live_createmon.lua`, overworld save): Bulbasaur L50 → maxHP 105 (exact base-45 calc),
Snorlax L50 → maxHP 220; Snorlax ≫ Bulbasaur proves species-specific base stats → fixes the
"Mewtwo with Pidgey stats" bug. **The handlers are now compiled C (`handlers.c` + `slink.ld`,
linked at CODE_BASE); `build.py` uses arm-none-eabi-gcc. The earlier hand-asm dispatcher
(slink_patch.asm) is retired — the C build passes the same PING + battle-logic tests.**

## Phase-1 battle globals (triple-validated: SLink RR profile ↔ BPRE.ld ↔ binary)
| symbol | address | notes |
|---|---|---|
| `gBattleMons` | `0x02023BE4` | stride `0x58`, hp(u16) @+0x28, maxHP @+0x2C |
| `gChosenActionByBank` | `0x02023D7C` | u8[4]; USE_MOVE=0 |
| `gChosenMovesByBanks` | `0x02023DC4` | u16[4]; move id |
| `gBattleCommunication` | `0x02023E82` | u8[8]; 3 = confirmed-standby (skips menu) |
| `gBattleStruct` | `0x02023FE8` | pointer; `chosenMovePositions[]` @+0x80, `moveTarget[]` @+0x0C |

> **Cross-validation caught an error:** an RE pass claimed `chosenMovePositions @ +0x90`; the
> battle-tested SLink profile (`gen3_frlge.lua`) and shipping Explode-mode prove it is **+0x80**.
>
> FORCE_MOVE replicates SLink's production "Variant-3" commit natively. The dispatcher's
> writes are runtime-validated via `lua/tests/test_mailbox_battle.lua` (fake battle state,
> every global confirmed) and FORCE_FAINT zeroes the live battler HP correctly.

### FORCE_MOVE live-execution finding (source-confirmed — pokefirered `battle_main.c`)
Live testing on a real in-battle savestate proved the Variant-3 RAM commit **does not, by
itself, execute a move** from the action menu. `HandleTurnActionSelectionState` at
`STATE_WAIT_ACTION_CHOSEN`:
1. gates on a **multi-nibble** exec mask — `bit | bit<<4 | bit<<8 | bit<<12 | 0xF0000000`,
   not just `1<<battler` (`gBattleControllerExecFlags`/`gBattleExecBuffer` = `0x02023BC8`);
2. reads the action from **`gBattleBufferB[battler][1]`** (`gBattleBufferB = 0x20233C4`,
   stride 0x200), **not** `gChosenActionByBank`;
3. on USE_MOVE it **re-emits ChooseMove** (the move submenu) — so committing the action
   only loops back to move-select.
**Both pure-RAM paths are now ruled out (source + empirical):**
- *Variant-3 action commit* (gChosenAction/comm/bs) — insufficient: state-2 reads
  `gBattleBufferB[battler][1]`, not `gChosenActionByBank`, and re-emits ChooseMove.
- *MULTIPLETURNS rampage lock* — SLink already tried `LOCK_STATUS2_VALUE = 0x1000 / 0x1800`
  (the correct CFRU bit) and it failed/softlocked (see `gen3_frlge.lua` RR profile comment,
  `LOCK_STATUS2_VALUE = nil`). Dead end.

**The action→move protocol (pokefirered `battle_main.c` HandleTurnActionSelectionState):**
at `STATE_WAIT_ACTION_CHOSEN`, when the multi-nibble exec mask clears, the engine reads
`gBattleBufferB[battler][1]`; `B_ACTION_USE_MOVE` (0) → `BtlController_EmitChooseMove` +
`MarkBattlerForControllerExec` (the move submenu), staying in WAIT_ACTION_CHOSEN. So it's a
**two-stage** controller handshake (choose action, then choose move), each gated by the exec
mask and read from `gBattleBufferB`.

**Full 3-state protocol RE'd** (`battle_main.c`, comm enum confirmed by live probe):
BEFORE_ACTION_CHOSEN=1 → WAIT_ACTION_CHOSEN=2 → WAIT_ACTION_CASE_CHOSEN=3 → CONFIRMED_STANDBY=4.
- comm 2: engine reads `gBattleBufferB[b][1]` (action); USE_MOVE(0) → emits ChooseMove, comm→3.
- comm 3: reads `gBattleBufferB[b][1]==10` + `[2]`=move_pos + `[3]`=target → sets
  `chosenMovePositions=[2]`, `gChosenMoveByBattler=moves[[2]]`, `moveTarget=[3]`, comm→4 (executes).
Move emit (`battle_controller_player.c:342`): `EmitTwoReturnValues(1, 10, cursor | (target<<8))`.

### SOLVED — FORCE_MOVE_SLOT (opcode 5), live-validated
A pre-callback2 hook can't win the buffer race (the controller/DMA overwrites it during
callback2). The fix is a **controller-pointer swap**: when armed and the player's menu is up,
the frame hook repoints `gBattlerControllerFuncs[battler]` (0x3004FE0) to our own routine, which
therefore runs *as* the controller (authoritative). That routine sets `gChosenActionByBank=USE_MOVE`,
`gChosenMovesByBanks[b]=gBattleMons[b].moves[move_pos]`, `gBattleStruct->chosenMovePositions[b]`/
`moveTarget[b]`, and **jumps comm straight to STATE_WAIT_ACTION_CONFIRMED_STANDBY (4)** + clears the
exec mask, then disarms (fires once via an `armed` guard; the engine reassigns the controller at the
next menu). Jumping to CONFIRMED sidesteps both the buffer-transfer round-trip *and* CFRU's Z-move
byte (a stale value made Scratch fire as "Breakneck Blitz").

**Live-validated** (`test_live_forcemove.lua`): forcing slot 1 (Growl) on the lead → slot-1 PP drops,
fires once, no corruption, no Z-move. Comm enum confirmed: 1 BEFORE → 2 WAIT_ACTION → 3 CASE_CHOSEN
→ 4 CONFIRMED_STANDBY. The exec mask is `bit|bit<<4|bit<<8|bit<<12|0xF0000000` on `gBattleExecBuffer
=0x02023BC8`.

**RR-build-specific addresses (runtime-discovered — re-discover per RR version):**
action-menu controllers `0x0802E439`/`0x0802E3B5`, move-menu controller thunk `0x0802EA11`
(→ real `HandleInputChooseMove` 0x090AB8B8). **RE-VALIDATED 2026-06-11 on the current build**
(`lua/tests/probe_movecursor_thunks.lua`): live `gBattlerControllerFuncs[0]` reads exactly
`0x0802E439` at the action menu and `0x0802EA11` at the move menu — the constants are correct,
so the 2026-06 real-play softlock was NOT stale addresses; re-enable work (config flag
`--native-battle-control`, default OFF) must focus on the swap's runtime behavior under a live
two-instance soak. Also found (used by the abandoned emit approach,
kept for reference): `EmitTwoReturnValues=0x0800E848`, `EmitMoveChosen=0x090AA73C`,
`PlayerBufferExecCompleted=0x0802E33C`, `gBattleBufferB=0x20233C4` (stride 0x200, CFRU format
`[0]=0x21 [1]=10/action [2]=move_pos [3]=target [4]=mega [5]=ultra [6]=zMove [7]=dynamax`).

**This empirically validates the report's core thesis:** pure external RAM-poke is
fundamentally limited; robust battle control needs in-ROM (controller-hook) code.

## Peer-ghost re-architecture (engine-driven NPC via held movements)

Cross-validated BPRE.ld(CFRU) ↔ capstone on RR (md5 8529f3a4): each lands on a sane Thumb
prologue (`push {..,lr}`). CFRU uses the "EventObject" naming = pokefirered "ObjectEvent".

| Function | RR addr (Thumb \|1) | prologue | purpose |
|---|---|---|---|
| `EventObjectSetHeldMovement` | 0x8063CA4 | push {r4,r5,lr} | queue a 1-tile held movement on an OE |
| `EventObjectClearHeldMovementIfActive` | 0x8063D1C | push {lr} | stop active held movement |
| `EventObjectClearHeldMovementIfFinished` | 0x8063D7C | push {r4,r5,lr} | poll: 0=finished 16=not-active else=busy; clears if done |
| `GetFaceDirectionMovementAction` | 0x8063EB8 | push {r4,lr} | dir→FACE action (0x0-0x3, idle facing) |
| `GetWalkNormalMovementAction` | 0x8063F2C | push {r4,lr} | dir→WALK_NORMAL action (0x10-0x13) |
| `GetWalkFastMovementAction` | 0x8063FB0 | push {r4,lr} | dir→WALK_FAST/run action (0x1D-0x20) |
| `RemoveEventObject` | 0x805E4B4 | push {lr} | clean remove: destroys sprite + deactivates OE |
| `MoveEventObjectToMapCoords` | 0x805F724 | push {r4-r7,lr} | hard re-place an OE at map coords (snap) |
| `EventObjectTurn` | 0x805F218 | push {r4-r6,lr} | face a direction without moving |
| `PatchObjectPalette` | 0x805F538 | push {r4,lr} | load+tint an OBJ palette into a slot (fallback) |
| `GetEventObjectGraphicsInfoOriginal` | 0x805F2C8 | ldr r1,[pc] | gfxId→graphics info (paletteSlot/Tag) (fallback) |

**`gPlayerAvatar = 0x02037078`** (CFRU; = gObjectEvents + 16*0x24). `objectEventId` @ +0x05 = the
player's gObjectEvents slot — the player is NOT always slot 0 (it lives elsewhere in some maps; the
spawn then grabs the free slot 0 and slot-0 reads point at the wrong thing). Validated: on the
overworld savestate it reads 0 (player IS slot 0), so player_oe() == slot 0 there and the driver tests
pass; the fix is reading this slot instead of a hardcoded 0, both in the patch (player_oe()) and Lua
(MB.player_oe()).

Directions: DIR_SOUTH=1 NORTH=2 WEST=3 EAST=4. Model = CFRU `follow_me.c`: spawn OE with
MOVEMENT_TYPE_NONE, then each step `EventObjectSetHeldMovement(oe, GetWalk*Action(dir))` and poll
`EventObjectClearHeldMovementIfFinished`. The engine animates/positions/palettes/collides natively.
`SpawnSpecialObjectEventParameterized`=0x805E831 and `ScriptContext1_SetupScript`=0x08069AE5 already
validated above.

## PC storage / box migration reference (forward-looking — for OP_DEPOSIT_MON/WITHDRAW/MEMORIALIZE)
Groundwork for retiring the Lua `depositPartyMon`/`retrieveBoxMon`/`memorializeMon` RAM-pokes
(`memory_gba.lua`). **The data layout is already fully mapped by SLink's Lua** (`lua/games/gen3_frlge.lua`):
PC boxes use CFRU's **58-byte (0x3A) `CompressedPokemon`** (NOT the 80-byte BoxPokemon), unencrypted,
fixed substruct order; `POKEMON_STORAGE_BASE = 0x02029314`, **25 boxes**, and the boxes are
**non-contiguous in EWRAM** — see `CFRU_BOX_BASES` (the `sPokemonBoxPtrs[]` table; e.g. box0 @
`0x2029314+4`, box20 @ `0x203CB44`, box23 @ `0x2027434`, box25 @ `0x2024638`).

**Base-engine mon accessors — VALIDATED on the live ROM** (disasm prologue ✓, `patch/build/slink_RR.gba`):
| symbol | addr | prologue | note |
|---|---|---|---|
| `GetMonData` | 0x0803FBE8 | push {r4,lr} | party `struct Pokemon` field read |
| `SetMonData` | 0x0804037C | push {r4,lr} | party field write |
| `BoxMonToMon` | 0x0803E774 | push {r4,lr};sub sp,#4 | expand an 80-byte BoxPokemon → 100-byte Pokemon |
| `CompactPartySlots` | 0x080937DC | push {r4-r7,lr} | close gaps after a party removal |
| `IsPokemonStorageFull` | 0x08040FA0 | push {r4-r6,lr} | box-space guard |
| `Memcpy` | 0x081E5E78 | — | raw copy (the BL the backup-wrap hook & `CopyMon` thunk target) |
| `GetMonDataFromAnyBox` | 0x0808BA18 | ldr r3,[pc];bx r3 | **CFRU trampoline** → real body ~`0x090B6B38` (the compressed-aware box accessor) |
| `SetMonDataFromAnyBox` | 0x0808BA5C | push;ldr r2,[pc];bx r2 | CFRU trampoline (compressed-aware box write) |

NB `CopyMon` (BPRE.ld 0x8040B08) is just a `bl Memcpy` thunk with no size set up — use `Memcpy` directly.

**The conversion primitives live in CFRU `src/pokemon_storage_system.c`** (CFRU-custom, in the
`0x09xxxxxx` added-code region, so NOT in BPRE.ld). **LOCATED 2026-06-08 by scanning the ROM for the
`sPokemonBoxPtrs[]` table** (`SLink-RR.gba`): the 25 box-base pointers (= SLink's `CFRU_BOX_BASES`) sit
as a const u32 table at **ROM `0x09148930`** (all 25 verified; dword after = `0x02031658` box-name base).
13 literal-pool xrefs to it cluster the storage functions in **`0x090B68xx–0x090B6Dxx`**:
| function | addr | confidence | evidence |
|---|---|---|---|
| **`CompressedMonToMon`(comp*, dst*)** — **WITHDRAW** primitive | **0x090B6A24** | ✓✓ LIVE | body = `sub sp,#0x50` (local BoxPokemon) → `CreateBoxMonFromCompressedMon(&box, comp)` → `BoxMonToMon(&box, dst)` — exact source match; **round-trip-proven on hardware** |
| **`CreateCompressedMonFromBoxMon`(box*, comp*)** — **DEPOSIT** primitive | **0x090B6B78** | ✓✓ LIVE | body = `Memset(comp,0,0x3A)` then the exact `0x1C`/substruct0/EV/misc/move copies from source; **round-trip-proven** |
| `CreateBoxMonFromCompressedMon`(box*, comp*) | 0x090B6924 | ✓ HIGH | the 80-byte builder `CompressedMonToMon` tail-calls (don't need it directly) |
| `GetCompressedMonPtr` math (inlined) | 0x090B69F4 | ✓ | computes `*(u32*)(0x09148930 + boxId*4) + boxPos*0x3A`, bounds boxId≤0x18 & pos≤0x1d. **Inlined in the handler** |

**IMPLEMENTED + LIVE-VALIDATED (2026-06-08, opcodes 24/25, build md5 7a8e8ebc):**
`OP_WITHDRAW_MON(box,pos,partySlot)` = `comp = *(u32*)(0x09148930 + box*4) + pos*0x3A`;
`CompressedMonToMon(comp, &gPlayerParty[slot])`; extend `gPlayerPartyCount`; zero the 58-byte box slot.
`OP_DEPOSIT_MON(partySlot,box,pos)` = `CreateCompressedMonFromBoxMon(&gPlayerParty[slot] /*its first 80
bytes ARE a BoxPokemon*/, comp)`; then shift-compact the party + decrement count (mirrors Lua
`depositPartyMon`). Because the engine conversion runs the real `BoxMonToMon`/`CalculatePPWithBonus`/
`CalculateMonStats`, a withdrawn mon comes out fully formed (level/stats/PP) — **the server-cached
`stats` blob is no longer needed**. Proven by `lua/tests/test_live_boxsync.lua` (deposit→withdraw of the
save's real lead mon: personality/OT/species preserved, level recomputed, box slot freed, no corruption).
**Status:** DONE — `exec_box_mon`/`exec_party_mon` run through `MB.deposit_mon`/`MB.withdraw_mon`
(async + patch-detect + Lua fallback), and `OP_MEMORIALIZE` (26) landed as the follow-up. The Lua
RAM-poke path is kept deliberately: it is the fallback for unpatched ROMs.
