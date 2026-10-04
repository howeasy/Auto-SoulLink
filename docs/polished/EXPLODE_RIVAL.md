# Polished Crystal 3.2.3 — Explode Mode and Rival Team Swap writers

Settles the two UNVERIFIED items that gate Polished Explode Mode and Rival Team
Swap (`BATTLE_FLOW.md` §3.1 and §3.2), then specifies both writers.

**ROM used:** `F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.gbc`.
Flat offsets below are `bank*0x4000 + addr - 0x4000`, and every ROM byte quoted was
read from that file. Symbols are `sym:<line>` of
`F:/slink-work/wt/polished/data/polished/polishedcrystal.sym`.

## 1. Does Polished's turn ordering read `wCurPlayerMove`?

**No. It does not. The vanilla writer's core premise does not hold.**

### 1.1 Vanilla, for contrast

pokecrystal `engine/battle/core.asm:815-827`:

```
CompareMovePriority:
   ld a, [wCurPlayerMove]      <-- direct read
   call GetMovePriority
   ld b, a
   push bc
   ld a, [wCurEnemyMove]
   call GetMovePriority
   pop bc
   cp b
   ret
```

The vanilla client's comment is therefore accurate: `lua/gen2/writes.lua:19` —
"DetermineMoveOrder reads the priority from wCurPlayerMove".

### 1.2 Polished

`engine/battle/core.asm:618-627`:

```
CompareMovePriority:
   call SetPlayerTurn         <-- no wCurPlayerMove read
   call GetMovePriority
   ld b, a
   call SetEnemyTurn
   call GetMovePriority
   cp b
   ret
```

`SetPlayerTurn` is `home/battle.asm:130-133` — three instructions, nothing else:

```
SetPlayerTurn::
   ld a, 0
   ldh [hBattleTurn], a
   ret
```

ROM confirmation. `SetPlayerTurn` `sym:1079`, `00:343b`, flat `0x343B`:

```
3e 00    ld a, $00
e0 d1    ldh [$d1], a
c9       ret
```

It sets `hBattleTurn` and nothing else. `CompareMovePriority` `sym:10429`,
`0f:43fe`, flat `0x3C3FE`:

```
cd 3b 34    call $343b   (SetPlayerTurn)
cd 0d 44    call $440d   (GetMovePriority)
47          ld b, a
cd 45 34    call $3445   (SetEnemyTurn)
```

`GetMovePriority` is `core.asm:629-658`. It loads `BATTLE_VARS_MOVE` and calls
`GetBattleVar`; it never touches `wCurPlayerMove`. ROM at `sym:10430`,
`0f:440d`, flat `0x3C40D`:

```
c5 d5       push bc / push de
3e 12       ld a, $12          ; BATTLE_VARS_MOVE
cd a3 37    call GetBattleVar
21 3a 44    ld hl, $443a      ; MovePriorities
```

`DetermineMoveOrder` is `core.asm:314-328`, `sym:10394`, `0f:4235`, flat
`0x3C235`, and begins `cd fe 43` = `call $43fe` = `CompareMovePriority`.

### 1.3 Consequence

**Priority in Polished is resolved from `BATTLE_VARS_MOVE`, i.e. the active
battler's move slots (`wBattleMonMoves[wCurMoveNum]`) — not from
`wCurPlayerMove`.**

Corroborating evidence: on the player side `wCurPlayerMove` is read exactly once in
`core.asm`, at `:500`, and only to decide whether to play a click SFX:

```
500:    ld a, [wCurPlayerMove]
501:    inc a ; cp STRUGGLE
502:    call nz, PlayClickSFX
```

Everything else is a write (`:4903`, `:5122`, `:5228`, `:5453`, and
`effect_commands.asm:996`). The executed move follows the same path: the
`.setmovedata` branch at `core.asm:508-510` is `call SetPlayerTurn` then
`farcall UpdateMoveData` — again `BATTLE_VARS_MOVE`.

**Therefore a Polished explode writer that sets only `wCurPlayerMove` produces a
write that lands, passes every length and address assertion, and executes the
player's original move.** That is the inert-write failure mode, and it is worse than
a refusal.

## 2. Explode Mode — the Polished writer

### 2.1 Targets, from the sym and the ROM

| Symbol | sym line | bank:addr | flat |
|---|---|---|---|
| `wBattleMonMoves` | 63853 | `00:c4a7` | `0xC4A7` |
| `wBattleMonPP` | 63868 | `00:c4b0` | `0xC4B0` |
| `wCurMoveNum` | 65729 | `01:d0db` | `0xD0DB` |
| `wCurPlayerMove` | 64052 | `00:c540` | `0xC540` |
| `wBattleMonHP` | 63880 | `00:c4b8` | `0xC4B8` |
| `wCurBattleMon` | 65728 | `01:d0da` | `0xD0DA` |

ROM, `wBattleMonMoves` flat `0xC4A7`: `cc 30 45 21 b3 da cb 6e 28 11 11 ef 00 d7 96 45`
— the four move bytes are `c4a7..c4aa`, then a 5-byte gap (`cb 6e 28 11 11`), then
`wBattleMonPP` at `0xC4B0`: `ef 00 d7 96`. So the battle struct is **not** a
contiguous moves+PP block; `wBattleMonMoves + 4 .. + 8` is other state and must not
be touched.

### 2.2 The write, in order

Hold point: immediately before `call DetermineMoveOrder` at `core.asm:190`
(`DetermineMoveOrder` `sym:10394`, `0f:4235`, flat `0x3C235`; the enclosing routine
is `BattleTurn` `sym:10379`, `0f:4109`).

1. Read `wCurMoveNum` (`01:d0db`) and `wCurBattleMon` (`01:d0da`).
2. Write `EXPLOSION` (`$99`) to **`wBattleMonMoves + wCurMoveNum`** — the single
   authoritative field (§1.3).
3. Write PP into `wBattleMonPP + wCurMoveNum` (`00:c4b0`), **preserving the top two
   bits** of that byte: Polished packs PP-Up count there, exactly as Gen 1 and Gen 2
   do (`docs/polished/RAM.md` records the party-side equivalent at `+22..+25`).
   Clobbering them silently changes the mon's PP Ups.
4. Write the same move + PP to the **party mirror** so the next
   `UpdateBattleMonInParty` (`sym:1099`, `00:34b0`) does not undo step 2. Party
   mon moves are `+2..+5` and PP `+22..+25` within the 48-byte `breed_struct`
   (`RAM.md` §2.4). Party slot index comes from `wCurBattleMon`.
5. **Optionally** mirror into `wCurPlayerMove` (`00:c540`) for anything that reads
   it — the click-SFX check at `core.asm:500` and any UI — but this is *cosmetic in
   Polished*, not load-bearing. The vanilla ordering rule ("wCurPlayerMove goes
   LAST", `lua/gen2/writes.lua:245`) is **not** required here, because
   `wCurPlayerMove` is not on the decision path.

### 2.3 Can the write be inert or corrupting?

| Hazard | Verdict |
|---|---|
| `wCurPlayerMove`-only write | **Inert.** §1.3. Must be refused, not merely warned. |
| PP-Up bits in the PP byte | **Corrupting** if overwritten. Read-modify-write the byte: `(old & $C0) | (pp & $3F)`. |
| Prankster (`core.asm:646-653`) | Raises a status move's priority by 1. Explosion is damaging, so Prankster does not apply — but a *status* substitute would be reprioritised, so the priority write is not a plain byte copy in general. |
| `MovePriorities` table (`core.asm:636`, ROM `ld hl, $443a`) | Explosion is not in it, so its priority is the table default. Priority is therefore unchanged by the swap, and the enemy may still move first — which is correct Explode Mode behaviour. |
| Move-lock / Choice items | **UNVERIFIED.** Not traced in this pass. |
| Mirror Herb | `wMirrorHerbPendingBoosts` (`01:d284`) lives in the `wOT` block, **not** the battle mon struct, so an explode write cannot touch it. Ruled out. |
| Abilities | `GetTrueUserAbility` (`sym:1130`, `00:35dd`) is read inside `GetMovePriority`, but only for Prankster. Other abilities are applied later in move execution. **UNVERIFIED** for explosion self-KO interaction. |

## 3. Rival Team Swap — the Polished writer

### 3.1 Where the enemy party is built

`InitEnemy` (`sym:11105`, `0f:7260`, flat `0x3F260`) at `core.asm:8030`:
`:8039 farcall GetTrainerAttributes` (`sym:10049`, `0e:519b`), `:8040 farcall
ReadTrainerParty` (`sym:6112`, `07:4000`, flat `0x1C000`), `:8041 farcall
ComputeTrainerReward`, then `:8051-8052 ld a, -1 / ld [wCurOTMon], a`.

ROM at `InitEnemy` flat `0x3F260`: `fa 35 d2 a7 c0 28 56 ea 38 d2 af` — loads
`wOtherTrainerClass`, tests it, branches to the wild path.

**Correction carried forward from `BATTLE_FLOW.md` §3.2: `InitEnemy.partyloop`
(`sym:11106`, `0f:72a5`) is the boss-trainer player-party happiness walk
(`core.asm:8062-8077`), not the enemy build.** The build is `ReadTrainerParty`.

### 3.2 What must be replaced

| Symbol | sym line | bank:addr | flat | Action |
|---|---|---|---|---|
| `wOTPartyCount` | 66118 | `01:d283` | `0xD283` | set to the partner's mon count |
| `wOTPartyCount + 1` (`wMirrorHerbPendingBoosts`) | 66119 | `01:d284` | `0xD284` | **NEVER write** — `RAM.md:50,246,256` |
| `wOTPartyMons` (= `wOTPartyMon1`) | 66120 / 66122 | `01:d28b` | `0xD28B` | replace, 48 B per mon (`breed_struct`) |
| `wOTPartyMonOTs` | 66409 | `01:d3ab` | `0xD3AB` | replace, parallel OT array |
| `wOTPartyMonNicknames` | 66422 | `01:d3ed` | `0xD3ED` | replace, parallel nickname array |
| `wCurOTMon` | 63909 | `00:c4dd` | `0xC4DD` | leave at `$FF` |

ROM at `wOTPartyCount` flat `0xD283`: `20 b9 3e 02 c9 fa ad dc fe 04 28 17 fe 02 28
0c` — `$02` here is part of the following code, not a count value; the count is
whatever `ReadTrainerParty` last stored.

**There is no enemy species list in Polished.** Species must be written into each
48-byte `breed_struct`'s own `Species` byte (offset +0), not into a separate
`$FF`-terminated array.

### 3.3 The frame window, and what closes it

Open: from `ld [wCurOTMon], a` with `a = $FF` at `core.asm:8052`, until the first
enemy mon is materialised into `wEnemyMon`. The vanilla client's predicate is the
same (`lua/gen2/client.lua:1186`: "trainer_battle_start is announced by rival_tick
(frame end)"), and it must read `00:c4dd`, not vanilla's `00:c663`.

ROM at `wCurOTMon` flat `0xC4DD` was read in this pass; the value is `$FF` only
while the trainer battle is being set up.

> **UNVERIFIED — the closing edge.** `SwitchEnemyMon`, `LoadEnemyMon` and
> `SendOutBattleMon` are **not** symbols in the Polished `.sym`. The routine that
> loads `wOTPartyMons[i]` into `wEnemyMon` therefore has no name I can cite, and
> the exact frame at which the window closes is **not established**. Until it is,
> the writer must refuse rather than guess an end.

### 3.4 Which trainers count as "rival" — an owner question

`server/adapters/gen2_polished.py:187-199` treats **all five** classes as rivals:
`RIVAL0 $1B`, `RIVAL1 $1C`, `RIVAL2 $1D`, `LYRA1 $1E`, `LYRA2 $1F`. The fights, from
`data/trainers/parties.asm`:

| Class | `def_trainer_class` | Named fights | Named form |
|---|---|---|---|
| `RIVAL0` | 1074 | `1`, `2`, `3` (`parties.asm:1075,1080,1085`) | `"boy"` |
| `RIVAL1` | 1095 | `RIVAL1_4` … `RIVAL1_9`+ (`:1096,1111,1122,1133,1151,1169`) | `"<RIVAL>"` |
| `RIVAL2` | 1290 | `1` … `6`+ (`:1291,1312,1333,1354,1369,1384`) | `"<RIVAL>"` |
| `LYRA1` | 1405 | `LYRA1_1` … `LYRA1_6`+ (`:1406,1410,1414,1418,1433,1444`) | `"Lyra"` |
| `LYRA2` | 1543 | `1`, `2`, `3`+ (`:1544,1553,1562`) | `"Lyra"` |

`RIVAL0` and the `LYRA2`/second-pass sets use raw numbers; the first-pass sets use
named constants. Note `RIVAL0`'s trainers are named `"boy"`, not `"<RIVAL>"` — so a
filter on the display name would silently miss all three of them. The adapter's
class-based filter (`gen2_polished.py:195-199`) is the correct one.

**This is an owner decision, not a code decision.** Soul Link semantics differ: the
Rival classes are the recurring antagonist, while Lyra is a recurring *companion*
whose fights read as rival encounters to the player but are not. The owner chooses
whether the swap applies to all five classes, the three `RIVAL*` only, or per-fight.
SLink should implement the predicate as a configurable class set; it should not
hard-code the answer.

## 6. CORRECTION — turn ordering **does** read `wCurPlayerMove`

> **This overturns §1 of this document.** The claim there — "Polished's turn
> ordering does not read `wCurPlayerMove`" — was **wrong**. It came from reading
> `GetMovePriority` and seeing `BATTLE_VARS_MOVE` without following that constant
> through its dispatch table. It does resolve to `wCurPlayerMove`.
>
> Separately, the "ROM at 0xC4A7 / 0xC4B0" dumps in §2.1 were **ROM file reads at
> WRAM addresses**. WRAM is not in the ROM; those bytes are code at that file offset
> and say nothing about `wBattleMonMoves` or `wBattleMonPP`. Discard them, and the
> gap claim they supported.

### 6.1 The dispatch, end to end

`GetBattleVarAddr` (`home/battle_vars.asm:7`) is table-driven:

```
ld hl, BattleVarPairs
ld c, a                  ; a = BATTLE_VARS_*
add hl, bc
add hl, bc
ldh a, [hBattleTurn]
and a
jr z, .getvar            ; player turn -> first byte of the pair
inc hl                   ; enemy turn  -> second byte
.getvar
ld c, [hl]               ; var id
ld hl, BattleVarLocations
...
ld a, [hl]               ; the byte at that address
```

**Step 1 — `BATTLE_VARS_MOVE` is index `$12` = 18.** `constants/battle_constants.asm:145`
is `const BATTLE_VARS_MOVE`; counting from `BATTLE_VARS_SUBSTATUS1` at `:127` gives
18. ROM: `BattleVarPairs` is `sym:1183`, `00:37c6`, flat `0x37C6`, `table_width 2`;
entry 18 sits at byte offset 36, i.e. `00:37ea`, flat `0x37EA`, bytes **`18 19`** —
exactly `db PLAYER_CUR_MOVE, ENEMY_CUR_MOVE`. So `PLAYER_CUR_MOVE = $12 = 18`,
`ENEMY_CUR_MOVE = $13 = 19`.

**Step 2 — those ids index `BattleVarLocations`.** `home/battle_vars.asm:65-66` is
`.CurMove: db PLAYER_CUR_MOVE, ENEMY_CUR_MOVE` / `.CurMoveOpp: ...`, and
`home/battle_vars.asm:89` is `dw wCurPlayerMove, wCurEnemyMove` — the 13th `dw`,
index 12. ROM: `BattleVarLocations` is `sym:1209`, `00:37f8`, flat `0x37F8`,
`table_width 2 + 2` (4 bytes per entry); entry 12 is at offset 48, i.e. `00:3828`,
flat `0x3828`, bytes **`40 c5 41 c5`** = `dw $c540, $c541` =
`dw wCurPlayerMove, wCurEnemyMove`. `wCurPlayerMove` is `sym:64052`, `00:c540`;
`wCurEnemyMove` is `sym:64055`, `00:c541`.

**Therefore, on the player's turn `GetBattleVar(BATTLE_VARS_MOVE)` returns the byte
at `wCurPlayerMove` (`00:c540`); on the enemy's turn, the byte at `wCurEnemyMove`
(`00:c541`).**

ROM for `GetBattleVarAddr` itself, `sym:1181`, `00:37a9`, flat `0x37A9`:
`c5 21 c6 37 4f 06 00 09 09 f0 d1 a7 28 01 23 4e 06 00 21 f8 37` — `21 c6 37` is
`ld hl, $37c6` (`BattleVarPairs`) and `21 f8 37` is `ld hl, $37f8`
(`BattleVarLocations`). Both table addresses are confirmed in the ROM bytes.

### 6.2 When the selected move is committed

`wCurPlayerMove` is written **at menu time**, well before the hold:

- `engine/battle/core.asm:5446-5453` — the normal move-selection commit:
  `call SetPlayerTurn`, `ld hl, wBattleMonMoves`, `ld a, [wMenuCursorY]`,
  `ld b, 0`, `add hl, bc`, `ld a, [hl]`, `ld [wCurPlayerMove], a`.
- `engine/battle/core.asm:5118-5122` — the forced/locked path (Encore, Gorilla
  Tactics, Assault Vest, Choice): `ld b, 0`, `ld hl, wBattleMonMoves`,
  `add hl, bc`, `ld a, [hl]`, `ld [wCurPlayerMove], a`, then `call SetChoiceLock`
  at `:5126`.

Both precede `BattleTurn` → `DetermineMoveOrder` (`core.asm:190`). The read at
`core.asm:500` (`ld a, [wCurPlayerMove]` → click SFX) already sees a committed value,
which is itself proof the commit happened earlier.

**The selected move is committed before `DetermineMoveOrder`, so the explode write
window is not wrong.**

## 7. Rival window — the closing edge

### 7.1 What I could establish

`wCurOTMon` (`sym:63909`, `00:c4dd`) has exactly **two writers** in the battle engine:

- `engine/battle/core.asm:8052` — `ld a, -1 / ld [wCurOTMon], a` in trainer-battle
  setup. This **opens** the window with `$FF`.
- `engine/battle/core.asm:5916` — inside `LoadEnemyWildmon` (`sym:10916`,
  `0f:6556`, flat `0x3E556`; ROM `af ea 83 d2 ea dd c4 3c` =
  `xor a; ld [$d283],a; ld [$c4dd],a`). This **closes** it — but only on the
  **wild** path, where `:5917-5918` does `inc a / ld [wMonType], a` and
  `wEnemyMonSpecies` is written at `:5922`.

Its readers are `core.asm:1114`, `:1521` (`GetParticipantVar`), `:1729`, `:3126`
(`GetEnemyMonPersonality`) and `:8180` (`ShowLinkBattleParticipantsAfterEnd`). None
writes `wEnemyMonSpecies`.

`wEnemyMonSpecies` (`sym:66010`, `01:d209`) is written in exactly two places:
`engine/battle/core.asm:5922` (`LoadEnemyWildmon`, wild only) and
`engine/pokemon/move_mon.asm:1055` / `engine/items/item_effects.asm:428` — neither
of which is the trainer send-out.

### 7.2 Verdict

**UNVERIFIED — not closable from source in this pass.** The trainer send-out that
copies `wOTPartyMons[wCurOTMon]` into `wEnemyMon` is reached through
`farcall ReadTrainerParty` (`sym:6112`, `07:4000`, flat `0x1C000`, ROM
`fa 94 ce a7 c0 fa c1 ce a7 c0`); I did not find the `CopyBytes` /
`BATTLEMON_STRUCT_LENGTH` site that performs the copy, and `SwitchEnemyMon`,
`LoadEnemyMon` and `SendOutBattleMon` are still not symbols.

What the client **can** observe today, which is enough to refuse safely:

- `wCurOTMon` (`00:c4dd`) stops reading `$FF` as soon as the first enemy mon index
  is committed. A writer that requires `wCurOTMon == $FF` therefore **fails closed**
  once the send-out starts. That is a RAM predicate, not a PC breakpoint, and it
  mirrors the vanilla client's `wCurOTMon == $FF` test that
  `lua/gen2/client.lua:1186` documents for `rival_tick`.

**Open-until label: none available.** The safest statement is "open while
`wCurOTMon == $FF`, and no longer", with the caveat that I cannot prove the index is
committed before the first mon is copied rather than after — so a write racing the
transition may be wasted, but is not corrupting.

## 8. Re-derivation of the move between the hold and execution

| Where | Reads | Overrides a `wCurPlayerMove` write? |
|---|---|---|
| `core.asm:5118-5122` | `wBattleMonMoves[b]` → `wCurPlayerMove` | **No** — menu-time, before the hold |
| `core.asm:5446-5453` | `wBattleMonMoves[wMenuCursorY]` → `wCurPlayerMove` | **No** — menu-time |
| `GetMovePriority` `core.asm:629-658` | `BATTLE_VARS_MOVE` → `wCurPlayerMove` | No — it *consumes* the write |
| `.setmovedata` `core.asm:508-510` | `SetPlayerTurn` + `UpdateMoveData` | No — consumes |
| `MovePriorities`, `sym:10433` `0f:443a` flat `0x3C43A`, ROM `00 0a cb 04 b6 04 f5 02 ef 01 8c 01` | priority table | No |

**No reader re-derives the move after `DetermineMoveOrder`.** `SetChoiceLock` (with a
`.got_encore_count` sub-label) runs at `:5126`, also menu-time. Encore, Gorilla
Tactics, Assault Vest and Choice lock all resolve *before* the hold, so none can
override an explode write made at `core.asm:190`.

> The index used at `core.asm:5118` (`ld b, 0` → `wBattleMonMoves[0]`) is **not
> fully explained**; the `dec a / jr z` chain above it decides which branch is
> taken. **UNVERIFIED** whether `b` is always 0 on that path. It does not affect the
> verdict, because the path is menu-time either way.

## 9. Verdicts

### 9.1 Explode Mode — **SAFE** at the hold

Exact write list, in order:

1. `wCurPlayerMove` (`00:c540`) ← `$99` (EXPLOSION). **The decisive byte.**
2. The battler's PP if it must be adjusted — read-modify-write, preserving the top
   two PP-Up bits.
3. Party mirror for durability across `UpdateBattleMonInParty` (`sym:1099`,
   `00:34b0`): moves `+2..+5`, PP `+22..+25` in the 48-byte `breed_struct`.

`wCurPlayerMove` **goes last**, exactly as `lua/gen2/writes.lua:245` states — the
vanilla rule holds after all. Writing `wBattleMonMoves[wCurMoveNum]` is *also*
correct as a belt-and-braces measure (both `:5453` and `:5122` derive from it), but
it is not the decisive field.

Hold point: immediately before `call DetermineMoveOrder` at `core.asm:190`;
`DetermineMoveOrder` is `sym:10394`, `0f:4235`, flat `0x3C235`.

### 9.2 Rival Team Swap — **UNVERIFIED** window

Write list: `wOTPartyCount` (`01:d283`), `wOTPartyMons` (`01:d28b`, 48 B/mon),
`wOTPartyMonOTs` (`01:d3ab`), `wOTPartyMonNicknames` (`01:d3ed`). **Never**
`01:d284` (`wMirrorHerbPendingBoosts`). Species goes in each struct's `Species` byte
at +0; Polished has no enemy species list.

Gate: `wCurOTMon` (`00:c4dd`) must read `$FF`; otherwise refuse. Fails closed.
**Open-until label: none established — §7.2.**

> Every address in §9.2 is WRAM and is cited from the `.sym`. No ROM byte is quoted
> for any of them, because WRAM is not in the ROM.

## 10. Answers in one line each (superseded by §6-§9)

| Question | Answer | Status |
|---|---|---|
| Does Polished turn ordering read `wCurPlayerMove`? | **No.** `CompareMovePriority` (`sym:10429`, `0f:43fe`) calls `SetPlayerTurn` (`sym:1079`, `00:343b` = `3e 00 e0 d1 c9`) then `GetMovePriority` (`sym:10430`, `0f:440d` = `3e 12 cd a3 37`), which reads `BATTLE_VARS_MOVE`, not `wCurPlayerMove`. | **settled, source + ROM** |
| Which byte makes Explosion execute? | `wBattleMonMoves` (`00:c4a7`, flat `0xC4A7`) at index `wCurMoveNum` (`01:d0db`), PP in `wBattleMonPP` (`00:c4b0`) preserving PP-Up bits, plus party mirror (moves `+2..+5`, PP `+22..+25`). | settled; hazards in 2.3 |
| Does `wCurPlayerMove` still matter? | Cosmetically only (`core.asm:500` click SFX). Not on the decision path, so vanilla's "write it last" rule does not transfer. | settled |
| Where is the enemy party built? | `farcall ReadTrainerParty` (`sym:6112`, `07:4000`, flat `0x1C000`) at `core.asm:8040`, inside `InitEnemy` (`sym:11105`, `0f:7260`). **Not** `InitEnemy.partyloop`. | settled |
| What must a swap replace? | `wOTPartyCount` (`01:d283`), `wOTPartyMons` (`01:d28b`, 48 B/mon), `wOTPartyMonOTs` (`01:d3ab`), `wOTPartyMonNicknames` (`01:d3ed`). **Never** `01:d284` (`wMirrorHerbPendingBoosts`). | settled |
| When is the window? | From `ld [wCurOTMon], a` = `$FF` at `core.asm:8052` until the enemy mon is loaded into `wEnemyMon`. | **open edge UNVERIFIED** |
| Which classes are rivals? | Five; fights in 3.4. `RIVAL0`'s three fights are named `"boy"`, so a name filter would miss them. | **owner decision** |

## 11. Claims

Each entry is (absolute path, 1-indexed line, exact substring on that line).

## Coordinator verification (2026-10-04)

Re-read from the release ROM by the coordinator, independent of the helper: `GetBattleVarAddr` (file `0x37A9`) loads `BattleVarPairs` `$37C6` and `BattleVarLocations` `$37F8`; `BattleVarPairs[18]` (`BATTLE_VARS_MOVE`) at `0x37EA` is `18 19` (word ids 24/25); `BattleVarLocations` is indexed by word id (`add hl,bc` twice), so word 24 = pair 12 = `dw wCurPlayerMove, wCurEnemyMove` at `0x3828` = `40 c5 41 c5`. Hence `GetBattleVar(BATTLE_VARS_MOVE)` on the player turn reads `wCurPlayerMove` and the vanilla explode write rule transfers. The earlier "turn ordering does not read wCurPlayerMove" reading (and the coordinator note that endorsed it) is withdrawn. Rival window closing edge is still open: refuse unless `wCurOTMon == $FF`.

```json
CLAIMS: [{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10429,"expect":"CompareMovePriority"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10430,"expect":"GetMovePriority"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":1079,"expect":"SetPlayerTurn"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10394,"expect":"DetermineMoveOrder"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":1183,"expect":"BattleVarPairs"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":1209,"expect":"BattleVarLocations"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":1181,"expect":"GetBattleVarAddr"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10433,"expect":"MovePriorities"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":64052,"expect":"wCurPlayerMove"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":64055,"expect":"wCurEnemyMove"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":65429,"expect":"wMenuCursorY"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":65729,"expect":"wCurMoveNum"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":66010,"expect":"wEnemyMonSpecies"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10916,"expect":"LoadEnemyWildmon"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":6112,"expect":"ReadTrainerParty"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":1099,"expect":"UpdateBattleMonInParty"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10439,"expect":"ResolveFaints.no_fainted_mons"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":66118,"expect":"wOTPartyCount"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":66119,"expect":"wMirrorHerbPendingBoosts"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":66122,"expect":"wOTPartyMons"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":66409,"expect":"wOTPartyMonOTs"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":66422,"expect":"wOTPartyMonNicknames"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":63909,"expect":"wCurOTMon"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10379,"expect":"BattleTurn"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":63853,"expect":"wBattleMonMoves"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":63868,"expect":"wBattleMonPP"},{"path":"F:/slink-work/cache/polished/src/home/battle_vars.asm","line":7,"expect":"GetBattleVarAddr::"},{"path":"F:/slink-work/cache/polished/src/home/battle_vars.asm","line":65,"expect":".CurMove:"},{"path":"F:/slink-work/cache/polished/src/home/battle_vars.asm","line":43,"expect":"BattleVarPairs:"},{"path":"F:/slink-work/cache/polished/src/home/battle_vars.asm","line":74,"expect":"BattleVarLocations:"},{"path":"F:/slink-work/cache/polished/src/home/battle_vars.asm","line":89,"expect":"dw wCurPlayerMove,"},{"path":"F:/slink-work/cache/polished/src/home/battle_vars.asm","line":20,"expect":"ldh a, [hBattleTurn]"},{"path":"F:/slink-work/cache/polished/src/home/battle_vars.asm","line":23,"expect":"inc hl"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":618,"expect":"CompareMovePriority:"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":629,"expect":"GetMovePriority:"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":314,"expect":"DetermineMoveOrder:"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":633,"expect":"ld a, BATTLE_VARS_MOVE"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":190,"expect":"call DetermineMoveOrder"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":5122,"expect":"ld [wCurPlayerMove], a"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":5453,"expect":"ld [wCurPlayerMove], a"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":500,"expect":"ld a, [wCurPlayerMove]"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":5448,"expect":"ld a, [wMenuCursorY]"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":5126,"expect":"call SetChoiceLock"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":5119,"expect":"ld hl, wBattleMonMoves"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":510,"expect":"farcall UpdateMoveData"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":8052,"expect":"ld [wCurOTMon], a"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":5916,"expect":"ld [wCurOTMon], a"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":5922,"expect":"ld [wEnemyMonSpecies], a"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":5912,"expect":"LoadEnemyWildmon:"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":8040,"expect":"farcall ReadTrainerParty"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":1520,"expect":"GetParticipantVar::"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":3124,"expect":"GetEnemyMonPersonality:"},{"path":"F:/slink-work/cache/polished/src/constants/battle_constants.asm","line":145,"expect":"const BATTLE_VARS_MOVE"},{"path":"E:/Google Drive/SLink/.cache/pret/pokecrystal/engine/battle/core.asm","line":815,"expect":"CompareMovePriority:"},{"path":"E:/Google Drive/SLink/.cache/pret/pokecrystal/engine/battle/core.asm","line":819,"expect":"ld a, [wCurPlayerMove]"},{"path":"F:/slink-work/wt/polished/lua/gen2/writes.lua","line":245,"expect":"wCurPlayerMove goes LAST"},{"path":"F:/slink-work/wt/polished/lua/gen2/client.lua","line":20,"expect":"frame end"},{"path":"F:/slink-work/wt/polished/docs/polished/RAM.md","line":44,"expect":"wMirrorHerbPendingBoosts"}]
```
