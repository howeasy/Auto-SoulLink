# P4.5 plan: Soul Link phone calls (Gen 2 easter egg), 2026-09-23

Planning worker P4.5a → coordinator. Docs only: nothing under `patch/**`, `lua/**` or `server/**`
was edited. Scope: owner ruling **O-29** (2026-09-23). On SLink-patched Gen 2 ROMs the Pokégear
rings with 2-3 fixed-text Soul Link calls, carried by the native special-call mechanism.

Pins: pokecrystal `7a7881d` (**C**), pokegold `656583c` (**G**; Silver builds from the same tree).
Every game fact below comes from those checkouts (`.cache/gen2-build/{pokecrystal,pokegold}`)
and from the committed `data/gen2/{pokecrystal,pokegold,pokesilver}.{sym,map}`. Paths are
repo-relative to the decomp unless they start with `docs/`, `patch/`, `lua/`, `server/`,
`tools/` or `data/gen2/`. Nothing here was taken from a screenshot.

---

## 0. Summary

| Question | Answer |
|---|---|
| Native path | `wSpecialPhoneCallID` (a saved WRAMX byte) → `CountStep` → `CheckSpecialPhoneCall` → `SpecialPhoneCallList` row (condition, contact, `dba` script) → `Script_ReceivePhoneCall` rings and `memcall`s the row's script. The script runs in its OWN bank, so a script and texts in the SLink bank are legal (§1.4) |
| When it fires | Only on a counted overworld step with no script running: never in battle, never mid-script, never in a link room. Surf and bike steps count. Indoor and no-signal maps are allowed with the `SpecialCallWhereverYouAre` condition. The native path never checks the Pokégear (§1.3) |
| Table change | **Zero moved symbols.** A 9-row copy of the table goes in a new `BANK[$24]` section in bank $24's slack, and the two `ld hl, SpecialPhoneCallList` in `phone.asm` are repointed (a same-size edit). Appending a row in place would move 661 (C) / 761 (G/S) symbols, including `FishGroups`/`TimeFishGroups`, which the profile and `gen2_rom_scan.py` consume (§1.5) |
| Caller shown | Contact `PHONE_00`, so the box reads **`----------`** (a mystery caller). No new name data (§1.4) |
| Mailbox | **+32 `PHONE_REQUEST`** (host writes 1..3; the ROM zeroes it = ack) and **+33 `PHONE_ARMED`** (ROM-owned; the accepted id, zeroed by the call script = delivered). C `$CFF8/$CFF9`, G/S `$C1F9/$C1FA` (§2) |
| Save safety | The service arms `wSpecialPhoneCallID` only while `wScriptRunning == 0` and withdraws its own id while any script runs. Every save runs under a script, so SPECIALCALL_SLINK never reaches SRAM, and native `checkphonecall` (the Pokérus nurse) never sees it (§2.3) **AMENDED 2026-09-23 (Codex, P4.5b save census): "every save runs under a script" is not a safe premise -- the P4.3a responder trade saves outside a script. That save (SaveAfterLinkTrade) copies PokemonData only, not the PlayerData block holding wSpecialPhoneCallID, so it cannot persist the id; the real sinks are SavePlayerData/SaveBackupPlayerData. P4.5b keeps a wLinkMode != 0 withdraw as defence and ships a table of every caller of those sinks (incl. Crystal mobile, CONTINUE) with the guard that covers each.** |
| Server | No new command. An optional `"phone"` key goes on three existing commands: `force_faint` from `_propagate_faint` (battle cause) → `fallen`; the dead-zone `msgbox` → `dead_zone`; the link `msgbox` for the run's first two-sided link → `first_link`. Clients that don't know the key ignore it (§3) |
| Rate limit | In the Lua binder: at most one call in flight, a 3-minute emulated-frame gap between rings, priority fallen > dead_zone > first_link, and dropped (not retried) across a reset (§3.3) |
| Caps | **Yes, a new bit:** `SLINK_CAP_PHONE = 1 << 3`. A clean ROM has no beacon, and a P4.1/P4.2 build doesn't set the bit, so neither ever gets a request (§6) |

---

## 1. The native special-call path, end to end (C and G/S)

### 1.1 State

| Fact | C | G/S |
|---|---|---|
| `wSpecialPhoneCallID:: db` (+`ds 3`; the script command writes a word) | `ram/wram.asm:3332`, `01:dc31` | `ram/wram.asm:2689`, `01:d97b` |
| It sits inside `wPlayerData` (so **it is saved**): C `wPlayerData 01:d47b` .. `wCurMapData 01:dca5`; G `01:d1a1` .. `01:d9ee` | `ram/wram.asm:2993,3378` | `data/gen2/pokegold.sym` |
| `wScriptRunning:: db` | `ram/wram.asm:2924`, `01:d438` | `ram/wram.asm:2311`, `01:d15f` |
| `wPokegearFlags::` (`POKEGEAR_PHONE_CARD_F` = bit 2) | `:3123`, `01:d957`; `constants/ram_constants.asm:290` | `:2521`, `01:d67c`; `:279` |
| WRAMX banking: C switches `rWBK` (battle animations select bank 5, e.g. `engine/battle_anims/anim_commands.asm:1413`; 30 files write it). G/S never write `rWBK` (grep: 0 files) | CGB-only | always bank 1 |

### 1.2 Constants, table and dispatch

| Step | C | G/S |
|---|---|---|
| `SPECIALCALL_NONE..MASTERBALL` (1..8), `NUM_SPECIALCALLS`, `SPECIALCALL_SIZE EQU 6` | `constants/phone_constants.asm:44-55` | `:43-54` |
| `SpecialPhoneCallList`: `specialcall` = `dw condition` / `db contact` / `dba script`, 8 rows, `assert_table_length NUM_SPECIALCALLS` | `data/phone/special_calls.asm:1-19`, `24:4627` | same lines, `24:45f6` |
| Setter: `Script_specialphonecall` writes id and id+1 | `engine/overworld/scripting.asm:1904-1909` | `:1788-1793` |
| Reader: `Script_checkphonecall` (TRUE if any id pending) | `:1911-1920` | `:1795-` |
| Other writer: `DoBikeStep` queues `SPECIALCALL_BIKESHOP` **only if the id is 0** ("don't overwrite that call") | `engine/overworld/events.asm:1318-1339` | `:1306-1327` |
| `CountStep`: returns early in link mode, then `farcall CheckSpecialPhoneCall`, `jr c, .doscript` | `engine/overworld/events.asm:866-874` | `:854-862` |
| `CheckSpecialPhoneCall`: id 0 → no call. Else row = `(id-1)*6` (**no bounds check**); `call _hl_` the condition (the same bank, $24); on carry → `LoadCallerScript(e = contact)` then overwrite `wCallerContact+SCRIPT2_BANK/ADDR` with the row's `dba`; `CallScript` `.script` = `pause 30` / `sjump Script_ReceivePhoneCall` | `engine/phone/phone.asm:242-287` (the table is read at `:250` and `:294`) | `:249-294` (`:257`, `:301`) |
| Conditions: `SpecialCallOnlyWhenOutside` (`wEnvironment` TOWN or ROUTE) / `SpecialCallWhereverYouAre` (`scf`) | `phone.asm:299-314` | `:306-321` |
| `LoadCallerScript`: `wCurCaller = e`; e = 0 copies `WrongNumber` (`TRAINER_NONE, PHONE_00`) | `:391-422` | `:398-429` |
| `Script_ReceivePhoneCall`: `reanchormap` / `callasm RingTwice_StartCall` / **`memcall wCallerContact + PHONE_CONTACT_SCRIPT2_BANK`** / `waitbutton` / `callasm HangUp` / `closetext` / `callasm InitCallReceiveDelay` | `:424-432` | `:431-439` |
| `RingTwice_StartCall` → `Phone_TextboxWithName(wCurCaller)` → `GetCallerName`; a `TRAINER_NONE` contact prints `NonTrainerCallerNames[number]` | `:451-471`, `:581-592`, `:634-665` | `:458-`, `:582-`, `:635-` |
| `PhoneContacts` row 0 = `TRAINER_NONE, PHONE_00` → `NonTrainerCallerNames .none = "----------@"` | `data/phone/phone_contacts.asm:14`; `data/phone/non_trainer_names.asm:4,12` | `:14`; `:11` |
| Native caller scripts clear the id themselves: `specialphonecall SPECIALCALL_NONE` (e.g. Elm) | `engine/phone/scripts/elm.asm:64-100` | same file |
| Story example: `specialphonecall SPECIALCALL_ROBBED` | `maps/MrPokemonsHouse.asm:129` | — |

### 1.3 When it can fire, and when it can't

`CountStep` is reached only through `HandleMap → MapEvents.events → PlayerEvents →
CheckTileEvent` (C `events.asm:140-172, 241-341`; G `:138-170, 238-`). So a pending id is
delivered on the first step that satisfies all of these:

| Context | Fires? | Source |
|---|---|---|
| Overworld, player finished a step, no script | **yes** | `CheckPlayerState` re-enables events on step stop (C `:215-232`, G `:212-`); `CheckTileEvent` step-count branch (C `:325-329`, G `:315`) |
| Any script running (NPC, sign, START/SELECT menu, heal, cutscene) | **no**: `PlayerEvents` returns while `wScriptRunning != 0` | C `:244-246`; `CallScript` sets it (`home/map.asm:925-936`, G `:1340-`); `Script_end`/`endall` clear it (C `scripting.asm:2252-2262, 2306-2310`, G `:2142-, 2196-`) |
| START menu / save | **no** (it's a script: `CheckMenuOW → CallScript StartMenuScript`) | C `events.asm:814-846`, G `:802-834` |
| Battle (wild or trainer) | **no**: reached as a player event script; the overworld loop isn't stepping | `PlayerEvents .ok` sets `wScriptRunning` (C `:271-289`) |
| Warp tile, connection, coord event, trainer sight | **no** on that step (those branches return first); the next plain step delivers | C `:291-323` |
| Just after a warp | **no** until the first completed step (`EnterMap` → `DisableEvents`, C `:114`, G `:112`) | — |
| Link rooms (`wLinkMode != 0`) | **no** | `CountStep` C `:867-870`, G `:855-858` |
| Surf / bike | **yes**: every counted step, whatever the movement type. Native precedent: the bike-shop call is queued from bike steps | `DoBikeStep` C `:1318-1339` |
| Indoors | only with `SpecialCallWhereverYouAre` (BIKESHOP/MOM/WEIRDBROADCAST use it) | `special_calls.asm:15-17` |
| No-signal maps | **yes, not checked.** `GetMapPhoneService` is consulted only by random calls and outgoing calls | `CheckPhoneCall` C `phone.asm:126`; `MakePhoneCallFromPokegear` `:316-324` (also refuses in link mode); `GetMapPhoneService` `home/map.asm:2247` (G `:2598`) |
| Pokégear not obtained | **the native path doesn't care**: nothing in `CheckSpecialPhoneCall`/`Script_ReceivePhoneCall` reads `wPokegearFlags` (the only readers are `engine/menus/start_menu.asm:317` and `engine/pokegear/pokegear.asm`). Native calls are all set after Mom's `setflag ENGINE_POKEGEAR` / `ENGINE_PHONE_CARD` (`maps/PlayersHouse1F.asm:41-42`, G `:32-33`). **SLink must add the gate itself** (§2.2) | — |

Pending ids persist: a failed condition returns `nc` and the step counts normally, and the id waits.

### 1.4 Adding an SLink call (legality)

- **Script in the SLink bank:** the row's `dba` is copied into `wCallerContact+SCRIPT2_*` and
  run by `memcall` (`Script_memcall` → `ScriptCall` with `b` = bank; C `scripting.asm:1230-1242`,
  G `:1136-`). The call script executes with `wScriptBank = $75` (C) / `$13` (G/S).
- **Texts in the SLink bank:** `Script_writetext` passes `wScriptBank` as the text bank
  (C `:329-337`, G `:310-318`), and `MapTextbox` bank-switches to it (`home/map.asm:1015-1035`).
  Local `text`/`line`/`para`/`done` in bank $75/$13 is legal, and no `text_far` is needed.
- **Mailbox access from the script:** `readmem`/`loadmem` exist in both macro sets
  (`macros/scripts/events.asm:158-175`; `Script_loadmem` C `:1468-1475`, G `:1374-1381`).
  So the script needs no `callasm`.
- **The condition must live in bank $24** (`call _hl_` without a bank switch). Reuse the native
  `SpecialCallWhereverYouAre`. No new condition code.
- **Caller = `PHONE_00`:** `LoadCallerScript(e=0)` loads `WrongNumber` whose script pointer is then
  overwritten. The name box prints `----------`. Nothing new in bank $24 besides the table.

### 1.5 Where the new row goes: repoint, don't append (zero moved symbols)

Appending a 9th row in `data/phone/special_calls.asm` moves every later `bank24` symbol by +6:
**661 in C, 761 in G/S** (from `PhoneOutOfAreaScript` to `Slots3LZ`). These include `FishGroups` and
`TimeFishGroups`, which `data/games/gen2_*/profile.json`, `lua/gen2/rom.lua`,
`server/adapters/gen2_rom_scan.py` and `tools/gen_gen2_encounters.py` consume, and the
`SetDayOfWeek`/`InitClock` fixtures (`tools/gen2_fixtures.py`, `lua/tests/*`). Appending also
changes `NUM_SPECIALCALLS`.

**Recommended (T2):**

1. A new `SECTION "SLink Special Calls", ROMX, BANK[$24]` (floating inside bank $24's slack: C
   `EMPTY $7a3d-$7fff` = 1475 B, G/S `EMPTY $7f92-$7fff` = 110 B;
   `data/gen2/pokecrystal.map:18662`, `pokegold.map:13009`, `pokesilver.map:13009`) holds
   `SlinkSpecialPhoneCallList`, the 8 native rows verbatim plus
   `specialcall SpecialCallWhereverYouAre, PHONE_00, SlinkPhoneCallScript`. That's 54 B, and
   `layout.link` pins only `"bank24"` at `ROMX $24`, so the new section fills the gap after it.
2. `DEF SPECIALCALL_SLINK EQU NUM_SPECIALCALLS + 1` (9) in the SLink source. The native enum
   and its `assert_table_length` stay untouched.
3. Anchor-replace (the `START_MENU_EDITS` pattern, `tools/build_gen2_companion.py:111-130`) the two
   `ld hl, SpecialPhoneCallList` in `CheckSpecialPhoneCall` and `.DoSpecialPhoneCall`
   (C `phone.asm:250,294`, G `:257,301`) with `ld hl, SlinkSpecialPhoneCallList`. It's the same
   3-byte opcode, so no symbol moves. The old table stays as dead data.
4. Unit pin: the first 48 bytes of the new table equal the old table's bytes in the built ROM. If
   they don't, a native call would misroute.

---

## 2. Mailbox handshake

### 2.1 Bytes

The public ABI is 0..29 (`patch/gb/slink_abi.inc`: core 0..13, trade lease 14..29). The private
bytes are 30..31 (`LAST_SAMPLE`, the `$A5` cookie, `patch/gen2/src/slink.asm:21-26`). The span is
40 B (C) / 39 B (G/S).

| Off | Name | Writer | Meaning | C | G/S |
|---|---|---|---|---|---|
| **+32** | `SLINK_OFS_PHONE_REQUEST` | host | 0 idle; 1..3 a call id. The ROM zeroes it on accept (**ack**) or on an invalid id (dropped) | `$CFF8` | `$C1F9` |
| **+33** | `SLINK_OFS_PHONE_ARMED` | ROM | the accepted id while it's pending; the call script zeroes it after reading it (**delivered**) | `$CFF9` | `$C1FA` |

Free after this: C +34..39 (6 B), G/S +34..38 (5 B). The offsets are Gen 2-only, so they go in
the Gen 2 source with `ASSERT SLINK_OFS_PHONE_ARMED < SLINK_MAILBOX_SIZE`. The **caps bit** goes in
the shared `patch/gb/slink_abi.inc`, so Gen 1 never reuses bit 3.

Call ids: `1 = FALLEN`, `2 = DEAD_ZONE`, `3 = FIRST_LINK`.

### 2.2 Service rules (appended to `SlinkService`, one pass per `DelayFrame`)

Run it as a **tail `jp`** from `SlinkService`, so the bridge's stack depth doesn't grow
(OMP F2 is still unmeasured).

```
phone:
  IF CRYSTAL: ldh a,[rWBK] / and 7 / cp 2 / ret nc   ; WRAMX must be bank 1 (0 reads as 1)
  armed = [+33]
  if armed == 0:
      req = [+32]; if req == 0 -> goto scrub
      [+32] = 0                                       ; ack (also for an invalid id)
      if req > 3 -> goto scrub                        ; dropped
      [+33] = armed = req
  ; armed != 0 from here
  if [wScriptRunning] != 0 -> goto withdraw           ; never visible to a script or a save
  if !(bit POKEGEAR_PHONE_CARD_F, [wPokegearFlags]) -> goto withdraw   ; hold: no phone yet
  if [wSpecialPhoneCallID] != 0 -> ret                ; native (or ours) already pending: never clobber
  [wSpecialPhoneCallID] = SPECIALCALL_SLINK ; [+1] = 0
  ret
withdraw / scrub:
  if [wSpecialPhoneCallID] == SPECIALCALL_SLINK -> [wSpecialPhoneCallID] = 0
  ret
```

The call script (SLink bank):

```
SlinkPhoneCallScript:
	specialphonecall SPECIALCALL_NONE            ; native convention (elm.asm)
	readmem wSlinkMailbox + SLINK_OFS_PHONE_ARMED
	loadmem wSlinkMailbox + SLINK_OFS_PHONE_ARMED, 0   ; delivered
	ifequal SLINK_CALL_FALLEN, .fallen
	ifequal SLINK_CALL_DEAD_ZONE, .dead_zone
	ifequal SLINK_CALL_FIRST_LINK, .first_link
	writetext SlinkPhoneStaticText               ; armed 0: orphan, still a valid call
	end
.fallen
	writetext SlinkPhoneFallenText
	end
; ... (one writetext + end per id)
```

### 2.3 Properties

| Property | How |
|---|---|
| **Never clobbers a native story call** | the service writes the id only when it reads 0. `Script_specialphonecall` *can* overwrite a pending SLink id. `ARMED` survives that, and once the native call clears the id, the next frame re-arms SLink, so it rings on a later step |
| **Bike-shop call** | `DoBikeStep` already refuses a nonzero id (C `events.asm:1325-1329`), so it waits one call |
| **Idempotent** | Lua writes +32 only when +32 == 0 **and** +33 == 0. The ROM accepts only when +33 == 0. One id can't be armed twice, and a duplicate post can't double-ring |
| **Invisible to scripts** | withdrawal while `wScriptRunning != 0`. The Pokérus nurse's `checkphonecall` (C `engine/events/std_scripts.asm:127`, G `:97`) runs after the heal animation's `DelayFrame`s, so it reads 0 and native behaviour is unchanged |
| **Never saved** | every save path runs under a script: START→SAVE (`start_menu.asm:435`, from `StartMenuScript`), `SaveGameData` from the Hall of Fame (`engine/events/halloffame.asm:25`) and Bill's PC (`engine/pokemon/bills_pc.asm:2001`), and `SaveAfterLinkTrade` (`engine/link/link.asm:2044`, a link-room script). So `SPECIALCALL_SLINK` never reaches SRAM. That matters because `CheckSpecialPhoneCall` has no bounds check: a save carrying id 9 loaded on a **clean** ROM would call a garbage condition pointer read from the bytes after the 8-row table |
| **Crystal WRAMX** | the `rWBK` gate skips any frame whose `DelayFrame` runs with bank 5 selected (the `c7c3fe08` hello-flap root cause) |
| **Reset / F5 stale window** | during `Reset`'s 32 `DelayFrames` before `Init` (C `home/init.asm:1-19`, G `:1-14`), the service may still accept a request and even write the id. Then `Init` zeroes WRAM0 (C `:66-75`, G `:58-67`, which also covers WRAMX) and Crystal's `ClearWRAM` (`:93`, `:186-203`) wipes WRAMX bank 1. New Game's `_ResetWRAM` clears `wGameData` (C `engine/menus/intro_menu.asm:102-114`, G `:28-37`), and Continue overwrites `wPlayerData` from the save. Nothing stale survives. An in-flight request is **lost, not replayed**. The scrub rule covers any stale id left in WRAMX anyway |
| **Clock (OMP F3)** | the handshake uses no timer. The Lua rate limit counts BizHawk frames, never the mailbox counter (which stalls in serial/cutscene modes and jumps after Card Flip) |

---

## 3. Lua and server trigger design

### 3.1 Mapping

| Id | Event | Server site | Tag carried on | Recipient |
|---|---|---|---|---|
| 1 `fallen` | partner's linked mon died, yours goes with it | `_propagate_faint`, the `force_faint`/`force_explode` to the partner (`server/state.py:3010-3011`), **only when `cause == "battle"`** (`identity_lost` is not a death) | that command: `"phone": "fallen"` | the partner (the one losing a mon) |
| 2 `dead_zone` | an area became a dead zone | the no-catch path (`server/state.py:2036-2050`, `dz_text` msgboxes) | both msgboxes: `"phone": "dead_zone"` | both |
| 3 `first_link` | the run's first link formed | the both-captured link (`server/state.py:1727-1750`), only when, after the append at `:1728`, exactly one `LinkEntry` has two keyed halves (`e.a and e.a.key and e.b and e.b.key`; dead-zone entries have a missing or `key=""` side) | both "linked!" msgboxes: `"phone": "first_link"` | both |

Not tagged: self-retirements (a capture in a dead zone or already-linked area, clause violations:
`:1517-1580`) and the shiny bonus pair (`:1493-1505`). The HUD already covers those, and a bonus
pair can't reasonably be the run's first link. `ponytail:` add the bonus path if the owner wants it.

### 3.2 Why a tag, not a new command

- **Smallest:** three dict keys in `server/state.py`, no protocol row, no ordering. The call rides
  the event it narrates, so it can't arrive without it.
- **Adapter-neutral:** no `game_id` branch. Gen 1/3 clients read only known fields, so the key is
  inert there (run `slink-adapter-guard`). A new `phone_call` command would work too, but every
  other client would log it as unknown.
- **Inferring from existing traffic doesn't work:** a `force_faint` from `_propagate_faint` and one
  from a self-retirement look the same, and matching msgbox text (`"is a dead zone!"`,
  `" linked!"`) is brittle.

### 3.3 Lua binder (`lua/gen2/phone.lua`, about 60 lines, Gen 2-only)

- `lua/gen2/client.lua` `handle_command`: after the existing `force_faint`/`msgbox` handling,
  `if cmd.phone then phone:request(cmd.phone) end`.
- `phone:request(name)` → id 1..3. It's dropped unless `panel:fresh()` (the P4.1f freshness gate:
  beacon + ABI 3 + cookie `$A5` + moving counter, `lua/gen2/panel.lua:109-128`) and caps has
  `CAP_PHONE`. **A clean ROM never passes** (no beacon), and neither does a P4.1/P4.2 build (no bit).
- **At most one queued call.** A higher-priority request (fallen > dead_zone > first_link)
  replaces a lower queued one, never the reverse.
- `phone:service()` runs once a frame. It posts the queued id when +32 == 0, +33 == 0, and at
  least `MIN_GAP = 10800` BizHawk frames (about 3 min) have passed since the last observed
  delivery. The write goes through the WRAM0 permit (`lua/gen2/panel.lua` `P.writes`,
  extended to allow `reason == "phone"` for exactly `mailbox+32`, 1 byte), so the receipt log shows it.
- **Delivered** = +33 observed == id, then observed 0 while fresh. If freshness drops (a reset),
  the in-flight call is forgotten: no retry, and the gap timer doesn't start.
- `first_link` rings at most once per session in the binder, as well as once per run from the server.
- Log one line per post and per delivery. No HUD fallback: a clean ROM simply gets no call.

---

## 4. Texts (draft, both charmaps)

Constraints: `TEXTBOX_INNERW = 18` tiles per line (`constants/text_constants.asm:26`, both).
`<PLAYER>` is at most 7 tiles (`PLAYER_NAME_LENGTH EQU 8` including the terminator, `:3`). Both
charmaps have `<PLAYER>` (C `constants/charmap.asm:24`, G `:22`), `#` = POKé (C `:26`, G `:24`),
`…` (C `:62`, G `:60`), `'`, `'s`/`'t`/`'m` ligatures, `-`, `?`, `!` and `.`. `<PLAY_G>` is
Crystal-only (C `:6`; G has none), so it's not used. The caller box already reads `----------`.

Widths assume `<PLAYER>` = 7.

```
SlinkPhoneFallenText:                     ; id 1
	text "…Hello? <PLAYER>?"        ; 16
	line "It's your partner."       ; 18
	para "Our link snapped."        ; 17
	line "Mine didn't make"         ; 16
	cont "it through…"              ; 11
	para "…and yours went"          ; 15
	line "with it. Sorry."          ; 15
	done

SlinkPhoneDeadZoneText:                   ; id 2
	text "<PLAYER>? Can you"         ; 16
	line "hear me? …kssh…"          ; 15
	para "The catch here got"       ; 18
	line "away. This place"         ; 16
	cont "is a DEAD ZONE."          ; 15
	para "Don't look back!"         ; 16
	done

SlinkPhoneFirstLinkText:                  ; id 3
	text "Hey, <PLAYER>!"            ; 13
	line "It's your partner!"       ; 18
	para "Our first #MON"          ; 17 (#MON = POKéMON)
	line "are linked. Their"        ; 17
	cont "souls are one now."       ; 18
	para "Keep 'em alive,"          ; 15
	line "OK? Bye-bye!"             ; 12
	done

SlinkPhoneStaticText:                     ; orphan/unknown id
	text "…kssh… …kssh…"                ; 13
	line "Nobody's there."          ; 15
	done
```

P4.5b's unit check: every line's rendered width is ≤ 18 with `<PLAYER>` = 7, measured from the
built ROM's bytes, not from the source.

Deferred (optional, O-29): the partner mon's name needs 11 B (`NAME_LENGTH EQU 11`), but only 6 B
(C) / 5 B (G/S) are left in the mailbox. It needs a lease-sharing rule for +14..29 or a staging
buffer, so it's a separate card.

---

## 5. Cards

| Card | Files (exclusive) | Prereq | Owner | First falsifier | Exit evidence | ∥ |
|---|---|---|---|---|---|---|
| **P4.5a** plan | this doc | O-29 | Claude (Opus) | — | the coordinator accepts §1-§6 | — |
| **P4.5b** asm service + table + script + texts | `patch/gen2/src/phone.asm` (new: the service tail, the `BANK[$24]` table, the script, the texts, `SPECIALCALL_SLINK`), `patch/gen2/src/phone_flags.asm`, `patch/gen2/src/slink.asm` (caps OR, tail `jp`), `patch/gb/slink_abi.inc` (`SLINK_CAP_PHONE`), `tools/build_gen2_companion.py` (the 2 `ld hl` anchors, INCLUDEs), `tests/unit/test_gen2_companion_abi.py` (phone rows), rebuilt `data/gen2/*_slink.{sym,map}`, `patch/dist/*.ups`, provenance | **P4.1g passes**, P4.5a | **Codex** | Machine test: preset `wSpecialPhoneCallID = SPECIALCALL_ROBBED` and post REQ=1. The id must stay ROBBED while REQ→0/ARMED=1. Reverting the `ret nz` guard → red. Also: with `wScriptRunning != 0` and id = SLINK, one service pass → id 0 | `--check` byte-identical ×3; clean↔patched sym diff **0 moved / 0 removed** (only `Slink*` added); the table-copy pin (48 B equal); `rWBK=5` pass → no write; invalid REQ=7 → REQ 0, ARMED 0; text widths ≤ 18; caps = PANEL\|PHONE | ∥ 5c |
| **P4.5c** Lua binder + server tags | `lua/gen2/phone.lua` (new), `lua/gen2/client.lua` (the one-line hook + a `service()` call), `lua/gen2/panel.lua` (`P.writes` accepts reason `phone` for +32 only), `server/state.py` (the 3 tags), `tests/unit/test_gen2_phone.py`, `tests/unit/test_state_phone_tags.py` | P4.1f committed; the offsets from this doc (pinned to the asm once 5b lands) | **Opus** (+ `slink-adapter-guard`) | lupa: a `phone` tag on a cartridge without `CAP_PHONE` → **zero** writes to +32 (empty receipt log); server: `_propagate_faint(cause="identity_lost")` carries no tag | units green; a posting with ARMED≠0 is refused; a second post inside `MIN_GAP` is refused; priority replacement works; freshness loss forgets the in-flight call; `first_link` tagged only on the first two-sided link; guard clean; Gen 1/Gen 3 regression units unchanged | ∥ 5b |
| **P4.5d** live gate | `lua/tests/gen2_phone_gate.lua`, phone rows in `tests/live/test_gen2_*_gates.py`, `tools/run_gb_gate.py` rows | 5b, 5c | Coord (C, G and S lanes in parallel) | the host posts REQ=1 in the town state and the ring must be seen **only after** one completed step: `wCurCaller == 0`, `----------` and the first text row in `wTilemap`, ARMED→0, id→0. Ringing before the step, or in battle → red | per title: (1) a town step rings; (2) posted mid-battle → no ring until after the battle **and** a step; (3) START open → the id reads 0 while the menu is up, then rings after close + step; (4) native precedence: fixture id = ROBBED → Elm rings first, SLink on a later step; (5) save with ARMED≠0 → the saved `wSpecialPhoneCallID` in SRAM == 0; (6) optional C↔C duo: a partner battle death → the other side rings `fallen` | — |

`P4.5b` starts only after P4.1g passes (coordinator rule), because it edits `slink.asm`/the
builder, which P4.1 owns until then.

---

## 6. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | The service writes a **native, saved** variable, the first time it touches game state outside the mailbox. The P4.1b writer census and the W6 write-watch allowlist assume mailbox-only | P4.5b adds `wSpecialPhoneCallID` to the census as a new writer class. Native writers are `Script_specialphonecall` and `DoBikeStep`, both main-thread with no `DelayFrame` between read and write, and the service is main-thread, so there's no race. W6 then allowlists the service PC for that one byte |
| R2 | A saved id 9 on a clean ROM → an out-of-table condition call (no bounds check, `phone.asm:242-257`) | withdraw-while-script (§2.3); gate step (5) reads the SRAM copy |
| R3 | Crystal WRAMX bank ≠ 1 during `DelayFrame` | the `rWBK` gate; gate row (2) exercises a battle |
| R4 | Bank $24 growth moves symbols (661/761), including `FishGroups` consumers | T2 repoint: 0 moved; asserted by the sym diff |
| R5 | A native story `specialphonecall` displaces a pending SLink call | by design: ARMED survives and re-arms after the native call. Gate row (4) |
| R6 | It rings in no-signal maps and indoors (`SpecialCallWhereverYouAre`) | accepted; native Elm/Mom/bike-shop calls do the same. `ponytail:` a 7-byte bank-$24 condition calling `GetMapPhoneService`, if the owner wants realism |
| R7 | A request before the Pokégear | held (the `PHONE_CARD_F` gate) until Mom's `setflag`; the ring comes on the first step after |
| R8 | The OMP F5 reset window loses a request | accepted (easter egg); the binder drops on freshness loss and never retries |
| R9 | Stack (OMP F2) | tail `jp`, no extra frame; F2's measurement is still owed by P4.1 |
| R10 | Spam | one in flight, a 3-min gap, priority; `first_link` once per run (server) and once per session (Lua) |
| R11 | Text overflow with long player names | worst case `<PLAYER>` = 7 is budgeted; P4.5b measures the built bytes |
| R12 | The server tag leaks to other gens | an inert dict key; `slink-adapter-guard` on P4.5c |

**Caps bit: yes.** `SLINK_CAP_PHONE EQU 1 << 3` in `patch/gb/slink_abi.inc`, and
`CAP_PHONE = 0x08` beside the other caps in `lua/gb_panel.lua`, pinned by the existing
constants-equality test. No ABI version bump: +32/+33 were unassigned and the capability
advertises them. Clean ROMs have no beacon; P4.1/P4.2 builds leave bit 3 clear, so Lua never
writes +32 there.
