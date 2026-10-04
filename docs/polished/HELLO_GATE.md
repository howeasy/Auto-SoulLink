# HELLO-GATE — a reliable "the overworld is running" predicate for the first hello

**Design doc for a live finding.** Polished's client sent its first hello at **frame 286**, from the
CONTINUE / main-menu screen, before the overworld went idle (first idle frame 336-396;
`TitleScreenMain` last ran at frame 208, `MainMenu` last at 220). The cause is
`lua/gen2/client.lua`'s `hello_unheld` path, whose `game_is_live()` treats **"party readable"** as
"game live". At frame 286 the WRAM area/party/map can be stale or mid-load.

This document proposes a predicate built **only from WRAM/HRAM bytes the client already reads**. Every
candidate is traced to an asm line that **writes** it; anything not traced is **UNVERIFIED**.

Addresses are from `F:/slink-work/wt/polished/data/polished/polishedcrystal.sym`.

---

## 1. The strongest single byte: `wMapStatus`

**`wMapStatus` `01:D431`.** Constants `constants/ram_constants.asm:207-210`:
`MAPSTATUS_START ; 0`, `ENTER ; 1`, `HANDLE ; 2`, `DONE ; 3`.

The only loop that writes it is `engine/overworld/events.asm:3-15`:

```
OverworldLoop::
	xor a ; MAPSTATUS_START
	ld [wMapStatus], a
.loop
	ld a, [wMapStatus]
	ld hl, .jumps
	call JumpTable
	ld a, [wMapStatus]
	cp MAPSTATUS_DONE
	jr nz, .loop
	ret
.jumps
	dw StartMap
	dw EnterMap
	dw HandleMap
	dw DoNothing
```

**`OverworldLoop` has exactly one caller: `engine/menus/intro_menu.asm:452` `farcall OverworldLoop`**,
immediately after `intro_menu.asm:446-451` sets `wLinkMode = 0`, `wGameTimerPaused = TRUE`,
`wEnteredMapFromContinue` bit 1. So `wMapStatus` walks 0→1→2→3 exactly once per map entry and
**lingers at `MAPSTATUS_DONE`** afterwards.

| state | `wMapStatus` |
|---|---|
| (a) title / main menu after Continue | `START` (0) — the loop has not run yet |
| (b) map load / transition | `ENTER`/`HANDLE` (1/2), changing every frame |
| (c) steady overworld | **`DONE` (3)** |
| (d)-(f) menus, battle, scripts | **`DONE` (3)** — it does *not* discriminate these |

**This is the load-bearing byte**: it is the only candidate that separates (a) from (c), which is
precisely the failure observed at frame 286. It is **not** in the save block (no writer in
`engine/overworld/save.asm` or `home/*.asm`), so a Continue cannot pre-load it as `DONE`.

**Failure mode:** if a future path calls `OverworldLoop` outside `intro_menu`, the byte stops meaning
"the player is in the overworld". **UNVERIFIED** — I found one caller by grep and did not prove it is
the only one in every build configuration.

## 2. The supporting bytes

| byte | sym | written at | clears when | discriminating power |
|---|---|---|---|---|
| `wScriptRunning` | `01:D437` | `engine/overworld/events.asm:60`, `:240`; `engine/overworld/scripting.asm:2340` | script finishes | **(f)** cutscene/script — **not** (d) textbox |
| `wGameLogicPaused` | `00:CEB9` | `engine/events/halloffame.asm:7`,`:32`; `engine/menus/save.asm:49`,`:64` | pause screen exits | (d) menus that pause |
| `wGameTimerPaused` | `00:CE91` | `engine/menus/intro_menu.asm:449` | — | set by Continue; **UNVERIFIED** who clears it |
| `wLinkMode` | `00:CEC1` | `intro_menu.asm:447` (cleared) | link ends | link battle — client already has it |
| `wBattleMode` | `01:D233` | engine battle code (**UNVERIFIED** — writer not traced this pass) | battle ends | (e) battle — the client already reads it as `battle.mode` |
| `wPlayerStepFlags` | `01:D122` | `engine/overworld/events.asm:178`,`:190` | player steps freely | bits `PLAYERSTEP_MIDAIR_F ; 4`, `CONTINUE_F ; 5`, `STOP_F ; 6`, `START_F ; 7` (`constants/ram_constants.asm:172-175`) all mean "not idle" |
| `wMapGroup` / `wMapNumber` | `01:DCAC` / `01:DCAD` | map entry (`StartMap`, reached from `OverworldLoop`) | next map | **map identity** — use with the save to prove *the loaded map matches the save* |
| `hMapEntryMethod` | `00:FF90` | — | — | **UNVERIFIED** — I did not trace a writer |
| `wEnabledPlayerEvents` | `01:D435` | `engine/overworld/events.asm:21-31` (`DisableEvents`/`EnableEvents`) | — | weak; set to `$FF` wholesale |
| `wEnteredMapFromContinue` | `01:D7D8` | `intro_menu.asm:451` | — | **UNVERIFIED** — a one-shot marker, not a steady-state predicate |

**Not present:** `wJoypadDisable` has **no symbol** in the pinned sym, so I cannot offer it as a
candidate. **UNVERIFIED** whether Polished uses a differently-named equivalent.

## 3. The recommended predicate

A **conjunction**, evaluated fresh each frame, required to hold **simultaneously** for **3
consecutive frames**:

```
wMapStatus      == MAPSTATUS_DONE (3)        -- 01:D431  the map entry loop completed
wScriptRunning  == 0                        -- 01:D437  no script
wGameLogicPaused== 0                        -- 00:CEB9  no pause
wLinkMode       == 0                        -- 00:CEC1
wBattleMode     == 0                        -- 01:D233
wPlayerStepFlags & 0xF0 == 0                -- 01:D122  no MIDAIR/CONTINUE/STOP/START
wMapGroup/wMapNumber in range and equal to the save's map
```

**Why 3 and not 8.** The live finding used 8 polls and still fired early, because the predicate it
polled (`game_is_live`) was wrong, not the window. The window's job is only to catch the *transition*
frames, and the transition into the overworld is a few frames long. **3 simultaneous** frames is the
minimum that distinguishes a settled overworld from a mid-transition one without adding latency;
8 would be equally correct but slower.

**Why "simultaneously" matters.** During a map load the bytes do not settle together — `wMapStatus`
reaches `DONE` before the player can act. Requiring all of them true in the *same* frame is what makes
the conjunction safe; polling each independently and combining the results would admit the window
where `wMapStatus` is already `DONE` but `wPlayerStepFlags` has not settled.

**Failure modes of this predicate:**
1. **A script that owns the overworld long-term** (a cutscene) → the gate waits, which is correct but
   delays the hello by the cutscene's length. Acceptable: a wrong hello is worse.
2. **A menu open over the overworld** (bag, party) → `wGameLogicPaused` is not set for every menu, so
   the hello may fire while a menu is open. The party is still correct, so this is cosmetic; if the
   coordinator wants strictness, add `hInMenu == 0` — **UNVERIFIED** whether that covers all menus.
3. **`wGameTimerPaused` left set by Continue** would block forever if included. **I deliberately left
   it OUT of the conjunction** until its clearing site is traced.
4. **Map identity**: requiring `wMapGroup`/`wMapNumber` to equal the save's map makes the gate fail on
   a legitimate map change the player already made — acceptable for a *first* hello, which is the only
   use here.

## 4. Can the 8-poll stability window alone ever be enough?

**No — and the live run is the proof.** Stability measures *change*, not *correctness*: stale WRAM from
the save is perfectly stable, which is exactly why frame 286 passed eight stable polls. A poll window
can only ever answer "is this value quiet?", never "is this value right?".

What the window is good for is the **transition** half of the problem: it is what stops a single-frame
glitch during `ENTERMAP`. So keep a window, but make it a *conjunction* window over bytes that are
individually meaningful, not a stability window over a single weak signal.

## 5. What the coordinator should do

1. Implement §3 as `client.lua`'s `hello_unheld` readiness predicate, replacing `game_is_live`'s
   "party readable" test — keep `game_is_live` as the cheap pre-filter it already is.
2. Trace `wGameTimerPaused`'s clearing site; add it to the conjunction only if it is reliably cleared.
3. Prove `OverworldLoop` has exactly one caller in the shipped build (the §1 caveat).
4. Live-verify: boot to Continue and confirm the first hello lands **after** the first idle frame
   (the 336-396 window from the live finding), not at 286.

```json
[
  {"path": "F:/slink-work/cache/polished/src/engine/overworld/events.asm", "line": 3, "expect": "OverworldLoop::"},
  {"path": "F:/slink-work/cache/polished/src/engine/overworld/events.asm", "line": 5, "expect": "ld [wMapStatus], a"},
  {"path": "F:/slink-work/cache/polished/src/engine/overworld/events.asm", "line": 11, "expect": "cp MAPSTATUS_DONE"},
  {"path": "F:/slink-work/cache/polished/src/engine/overworld/events.asm", "line": 16, "expect": "dw StartMap"},
  {"path": "F:/slink-work/cache/polished/src/engine/overworld/events.asm", "line": 60, "expect": "ld [wScriptRunning], a"},
  {"path": "F:/slink-work/cache/polished/src/engine/overworld/events.asm", "line": 178, "expect": "bit PLAYERSTEP_STOP_F, [hl]"},
  {"path": "F:/slink-work/cache/polished/src/engine/overworld/events.asm", "line": 190, "expect": "bit PLAYERSTEP_CONTINUE_F, a"},
  {"path": "F:/slink-work/cache/polished/src/engine/menus/intro_menu.asm", "line": 447, "expect": "ld [wLinkMode], a"},
  {"path": "F:/slink-work/cache/polished/src/engine/menus/intro_menu.asm", "line": 449, "expect": "ld [wGameTimerPaused], a"},
  {"path": "F:/slink-work/cache/polished/src/engine/menus/intro_menu.asm", "line": 452, "expect": "farcall OverworldLoop"},
  {"path": "F:/slink-work/cache/polished/src/constants/ram_constants.asm", "line": 172, "expect": "const PLAYERSTEP_MIDAIR_F   ; 4"},
  {"path": "F:/slink-work/cache/polished/src/constants/ram_constants.asm", "line": 174, "expect": "const PLAYERSTEP_STOP_F     ; 6"},
  {"path": "F:/slink-work/cache/polished/src/constants/ram_constants.asm", "line": 207, "expect": "const MAPSTATUS_START  ; 0"},
  {"path": "F:/slink-work/cache/polished/src/constants/ram_constants.asm", "line": 210, "expect": "const MAPSTATUS_DONE   ; 3"},
  {"path": "F:/slink-work/cache/polished/src/engine/menus/save.asm", "line": 49, "expect": "ld [wGameLogicPaused], a"},
  {"path": "F:/slink-work/cache/polished/src/engine/events/halloffame.asm", "line": 7, "expect": "ld [wGameLogicPaused], a"},
  {"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 66431, "expect": "01:d431 wMapStatus"},
  {"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 66438, "expect": "01:d437 wScriptRunning"},
  {"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 65805, "expect": "01:d122 wPlayerStepFlags"},
  {"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 65477, "expect": "00:ceb9 wGameLogicPaused"},
  {"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 65439, "expect": "00:ce91 wGameTimerPaused"},
  {"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 65484, "expect": "00:cec1 wLinkMode"},
  {"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 66049, "expect": "01:d233 wBattleMode"},
  {"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 67516, "expect": "01:dcac wMapGroup"},
  {"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 67517, "expect": "01:dcad wMapNumber"},
  {"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 70055, "expect": "00:ff90 hMapEntryMethod"},
  {"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 67234, "expect": "01:d7d8 wEnteredMapFromContinue"},
  {"path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym", "line": 66436, "expect": "01:d435 wEnabledPlayerEvents"}
]
```

---

## Coordinator correction (2026-10-04): the steady-overworld value is HANDLE (2), NOT DONE (3)

`OverworldLoop` (`engine/overworld/events.asm:3-13`) loops `JumpTable` on `wMapStatus` and **returns when the
status is `MAPSTATUS_DONE`** - DONE means the loop has ENDED, not that the overworld is running. `EnterMap` ends
with `ld a, MAPSTATUS_HANDLE / ld [wMapStatus], a` (`:84-85`) and `HandleMap` keeps running while it stays HANDLE
(`:94-96`). So the table in F-1 is wrong: steady overworld = **`wMapStatus == MAPSTATUS_HANDLE` (2)**; 0 = START
(the title/main menu, never set by anything else), 1 = ENTER (map load); 3 = DONE only transiently as the loop exits.
Everything else in the recommendation stands with that value swapped: `wMapStatus == 2` and `hMapEntryMethod == 0`
(EnterMap clears it, `:81-82`, a second independent 'map entry finished' signal) and the rest of the conjunction held
for 3 simultaneous frames. An implementation that waited for `DONE` would never send a hello. The OMP's CLAIMS quotes
verify; the conclusion drawn from them did not.
