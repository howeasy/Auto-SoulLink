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

## 10. The trainer send-out copy site — proven from ROM bytes

Every offset below was read from `polishedcrystal-3.2.3.gbc`. Flat =
`bank*0x4000 + addr - 0x4000`. No WRAM address is dumped — WRAM is not in the ROM.

### 10.1 The routine

**`SendInUserPkmn`**, `sym:10477`, `0f:4748`, flat `0x3C748`. It is **side-neutral**:
one routine copies *either* side's party mon into the battle struct, selected by
`hBattleTurn`. `engine/battle/core.asm:1144` opens it; the enemy branch is selected
at `core.asm:1240-1244`.

Source `core.asm:1225-1298` is three `rst CopyBytes` calls with a
`wOTPartyMon1Species` / `wPartyMon1Species` switch.

### 10.2 The bytes, decoded

**The commit — `wCurOTMon` written, at `0f:47cc`, flat `0x3C7CC`:**

```
21 dd c4 1a 3d 77 ea 0c d1
ld hl, $c4dd   ; wCurOTMon
ld a, [de]     ; wEnemySwitchTarget ($c525)
dec a
ld [hl], a     ; <-- wCurOTMon leaves $FF HERE
ld [$d10c], a  ; wCurPartyMon
```

**Source selection and pointer resolution, at `0f:47dd`, flat `0x3C7DD`:**

```
0f:47dd  21 8b d2      ld hl, wOTPartyMon1Species ($d28b)   ; enemy branch
0f:47e0  fa 0c d1      ld a, [wCurPartyMon]
0f:47e3  cd c9 33      call GetPartyLocation                  ; hl = &wOTPartyMons[wCurOTMon]
0f:47e6  e5            push hl
0f:47e7  11 a5 c4      ld de, $c4a5                          ; wBattleMonSpecies
0f:47ea  cd 32 49      call $4932
0f:47ed  d5            push de
0f:47ee  01 06 00      ld bc, $0006                           ; Species, Item, Moves
0f:47f1  e7            rst CopyBytes
0f:47f2  01 0b 00      ld bc, $000b                           ; DVs, Personality, PP, Happiness
0f:47f5  09            add hl, bc
0f:47f6  11 ab c4      ld de, $c4ab
0f:47f9  cd 32 49      call $4932
0f:47fc  01 0a 00      ld bc, $000a
0f:47ff  e7            rst CopyBytes
0f:4800  01 04 00      ld bc, $0004
0f:4803  09            add hl, bc
0f:4804  11 b5 c4      ld de, $c4b5
0f:4807  cd 32 49      call $4932
0f:480a  01 11 00      ld bc, $0011 = 17 = PARTYMON_STRUCT_LENGTH - MON_LEVEL
0f:480d  e7            rst CopyBytes                           ; <-- LAST CONSUMPTION
```

Full 80-byte window read from `0f:47dd` flat `0x3C7DD`:
`21 8b d2 fa 0c d1 cd c9 33 e5 11 a5 c4 cd 32 49 d5 01 06 00 e7 01 0b 00 09 11 ab c4
cd 32 49 01 0a 00 e7 01 04 00 09 11 b5 c4 cd 32 49 01 11 00 e7 d1 f0 d1 a7 21 2c d2
28 03 21 2e d2 1a ea a6 ce ea 0b d1 77 e1 01 15 00 09 f0 d1 a7 7e ea aa`

### 10.3 The ordering, and what it inverts

**The commit (`0f:47cc`) runs 65 bytes BEFORE the final copy (`0f:480d`).**

So `wCurOTMon != $FF` does **not** mean the window is closed. My §7.2 / §9.2 gate —
"write only while `wCurOTMon == $FF`" — is **wrong**: it refuses during a window that
is still open. Corrected here.

| Window | Condition | Write result |
|---|---|---|
| before `0f:47cc` | `wCurOTMon == $FF` | **consumed** |
| `0f:47cc` .. `0f:480c` | `wCurOTMon != $FF`, copy not finished | **still consumed** |
| after `0f:480d` | copy done | **lost** |

**Earliest instruction after which a write is lost: `0f:480d`, flat `0x3C80D`
(`rst CopyBytes`, the 17-byte tail).**

### 10.4 What the client can poll

**Exact gate — PC breakpoint at `0f:47dd` flat `0x3C7DD`** (`ld hl, wOTPartyMon1Species`).
At that instant the party pointer has not been resolved and the copy has not run,
so a write to `wOTPartyMons[0]` is guaranteed consumed. This is the only gate that is
both open and precise.

**Conservative RAM fallback:** `wCurOTMon == $FF`. Always safe, occasionally refuses
while the window is in fact open. That is the right failure direction, but it is
strictly weaker than the PC gate and should not be described as "the window".

**Vanilla comparison.** pokecrystal `engine/battle/core.asm:3956-3968` has the same
shape — `ld hl, wOTPartyMon1Species`, `call GetPartyLocation`,
ld de, wEnemyMonSpecies`, then three `call CopyBytes` — so the *routine* is
descended from vanilla, but vanilla has a separate `LoadEnemyMon` entry whereas
Polished folded both sides into `SendInUserPkmn`. `lua/gen2/client.lua:1186` uses
`rival_tick` at a frame end; **that is not transferable to Polished**, because the
copy happens inside a single routine, mid-frame, not at a frame boundary.

### 10.5 Final verdict — Rival Team Swap: **SAFE** with the PC gate

Write list, in order, all WRAM (cited from the `.sym`, no ROM bytes exist for them):

1. `wOTPartyCount` (`01:d283`) ← partner's mon count.
2. `wOTPartyMons` (`01:d28b`) ← `48 * i` per mon: `breed_struct`, `Species` at +0,
   moves +2..+5, PP +22..+25, level +30 (read-modify-write the PP-Up bits).
3. `wOTPartyMonOTs` (`01:d3ab`) ← parallel OT array.
4. `wOTPartyMonNicknames` (`01:d3ed`) ← parallel nickname array.
5. **Never** `01:d284` (`wMirrorHerbPendingBoosts`).

Gate: **PC == `0f:47dd` (flat `0x3C7DD`)**. Refuse on any other PC. If a PC gate is
unavailable, fall back to `wCurOTMon == $FF` and accept the narrower coverage.

Species goes in each struct's `Species` byte at +0; Polished has no enemy species
list, so the vanilla `wOTPartySpecies1` write has no counterpart and must be omitted.

## 11. Answers in one line each (superseded by §6-§10)

| Question | Answer | Status |
|---|---|---|
| Does Polished turn ordering read `wCurPlayerMove`? | **No.** `CompareMovePriority` (`sym:10429`, `0f:43fe`) calls `SetPlayerTurn` (`sym:1079`, `00:343b` = `3e 00 e0 d1 c9`) then `GetMovePriority` (`sym:10430`, `0f:440d` = `3e 12 cd a3 37`), which reads `BATTLE_VARS_MOVE`, not `wCurPlayerMove`. | **settled, source + ROM** |
| Which byte makes Explosion execute? | `wBattleMonMoves` (`00:c4a7`, flat `0xC4A7`) at index `wCurMoveNum` (`01:d0db`), PP in `wBattleMonPP` (`00:c4b0`) preserving PP-Up bits, plus party mirror (moves `+2..+5`, PP `+22..+25`). | settled; hazards in 2.3 |
| Does `wCurPlayerMove` still matter? | Cosmetically only (`core.asm:500` click SFX). Not on the decision path, so vanilla's "write it last" rule does not transfer. | settled |
| Where is the enemy party built? | `farcall ReadTrainerParty` (`sym:6112`, `07:4000`, flat `0x1C000`) at `core.asm:8040`, inside `InitEnemy` (`sym:11105`, `0f:7260`). **Not** `InitEnemy.partyloop`. | settled |
| What must a swap replace? | `wOTPartyCount` (`01:d283`), `wOTPartyMons` (`01:d28b`, 48 B/mon), `wOTPartyMonOTs` (`01:d3ab`), `wOTPartyMonNicknames` (`01:d3ed`). **Never** `01:d284` (`wMirrorHerbPendingBoosts`). | settled |
| When is the window? | From `ld [wCurOTMon], a` = `$FF` at `core.asm:8052` until the enemy mon is loaded into `wEnemyMon`. | **open edge UNVERIFIED** |
| Which classes are rivals? | Five; fights in 3.4. `RIVAL0`'s three fights are named `"boy"`, so a name filter would miss them. | **owner decision** |

## 12. Claims

Each entry is (absolute path, 1-indexed line, exact substring on that line).

## Coordinator verification (2026-10-04)

Re-read from the release ROM by the coordinator, independent of the helper: `GetBattleVarAddr` (file `0x37A9`) loads `BattleVarPairs` `$37C6` and `BattleVarLocations` `$37F8`; `BattleVarPairs[18]` (`BATTLE_VARS_MOVE`) at `0x37EA` is `18 19` (word ids 24/25); `BattleVarLocations` is indexed by word id (`add hl,bc` twice), so word 24 = pair 12 = `dw wCurPlayerMove, wCurEnemyMove` at `0x3828` = `40 c5 41 c5`. Hence `GetBattleVar(BATTLE_VARS_MOVE)` on the player turn reads `wCurPlayerMove` and the vanilla explode write rule transfers. The earlier "turn ordering does not read wCurPlayerMove" reading (and the coordinator note that endorsed it) is withdrawn. ~~Rival window closing edge is still open: refuse unless `wCurOTMon == $FF`.~~ SUPERSEDED (coordinator, same day): §10 proves `wCurOTMon` is committed at 0f:47cc BEFORE the copy, so `== $FF` would refuse while the window is open; the gate is the PC at 0f:47dd and the write is lost after 0f:480d.

```json
CLAIMS: [{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10477,"expect":"SendInUserPkmn"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":63909,"expect":"wCurOTMon"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":66118,"expect":"wOTPartyCount"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":66122,"expect":"wOTPartyMons"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":66409,"expect":"wOTPartyMonOTs"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":66422,"expect":"wOTPartyMonNicknames"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":66119,"expect":"wMirrorHerbPendingBoosts"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":65782,"expect":"wCurPartyMon"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":65728,"expect":"wCurBattleMon"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":63850,"expect":"wBattleMonSpecies"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":66010,"expect":"wEnemyMonSpecies"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":1065,"expect":"GetPartyLocation"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":63988,"expect":"wEnemySwitchTarget"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":63985,"expect":"wPlayerSwitchTarget"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10429,"expect":"CompareMovePriority"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10430,"expect":"GetMovePriority"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":1183,"expect":"BattleVarPairs"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":1209,"expect":"BattleVarLocations"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":1181,"expect":"GetBattleVarAddr"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10394,"expect":"DetermineMoveOrder"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":64052,"expect":"wCurPlayerMove"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":64055,"expect":"wCurEnemyMove"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":6112,"expect":"ReadTrainerParty"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":1099,"expect":"UpdateBattleMonInParty"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10916,"expect":"LoadEnemyWildmon"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10433,"expect":"MovePriorities"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":65429,"expect":"wMenuCursorY"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10379,"expect":"BattleTurn"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":1144,"expect":"SendInUserPkmn:"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":1233,"expect":"ld hl, wCurOTMon"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":1237,"expect":"ld [hl], a"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":1238,"expect":"ld [wCurPartyMon], a"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":1244,"expect":"ld hl, wOTPartyMon1Species"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":1247,"expect":"call GetPartyLocation"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":1249,"expect":"ld de, wBattleMonSpecies"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":1253,"expect":"rst CopyBytes ; copy Species, Item, Moves"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":1264,"expect":"ld bc, PARTYMON_STRUCT_LENGTH - MON_LEVEL"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":1265,"expect":"rst CopyBytes ; copy Level, Status, Unused, HP, MaxHP, Stats"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":8052,"expect":"ld [wCurOTMon], a"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":8040,"expect":"farcall ReadTrainerParty"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":618,"expect":"CompareMovePriority:"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":629,"expect":"GetMovePriority:"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":314,"expect":"DetermineMoveOrder:"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":190,"expect":"call DetermineMoveOrder"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":5122,"expect":"ld [wCurPlayerMove], a"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":5453,"expect":"ld [wCurPlayerMove], a"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":5448,"expect":"ld a, [wMenuCursorY]"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":5126,"expect":"call SetChoiceLock"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":510,"expect":"farcall UpdateMoveData"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":500,"expect":"ld a, [wCurPlayerMove]"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":5922,"expect":"ld [wEnemyMonSpecies], a"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":5916,"expect":"ld [wCurOTMon], a"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":3124,"expect":"GetEnemyMonPersonality:"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":1520,"expect":"GetParticipantVar::"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":2935,"expect":"Function_SetEnemyPkmnAndSendOutAnimation:"},{"path":"F:/slink-work/cache/polished/src/home/battle_vars.asm","line":7,"expect":"GetBattleVarAddr::"},{"path":"F:/slink-work/cache/polished/src/home/battle_vars.asm","line":43,"expect":"BattleVarPairs:"},{"path":"F:/slink-work/cache/polished/src/home/battle_vars.asm","line":74,"expect":"BattleVarLocations:"},{"path":"F:/slink-work/cache/polished/src/home/battle_vars.asm","line":89,"expect":"dw wCurPlayerMove,"},{"path":"F:/slink-work/cache/polished/src/home/battle_vars.asm","line":65,"expect":".CurMove:"},{"path":"F:/slink-work/cache/polished/src/home/battle_vars.asm","line":20,"expect":"ldh a, [hBattleTurn]"},{"path":"F:/slink-work/cache/polished/src/constants/battle_constants.asm","line":145,"expect":"const BATTLE_VARS_MOVE"},{"path":"E:/Google Drive/SLink/.cache/pret/pokecrystal/engine/battle/core.asm","line":3956,"expect":"ld hl, wOTPartyMon1Species"},{"path":"E:/Google Drive/SLink/.cache/pret/pokecrystal/engine/battle/core.asm","line":3960,"expect":"call CopyBytes"},{"path":"E:/Google Drive/SLink/.cache/pret/pokecrystal/engine/battle/core.asm","line":815,"expect":"CompareMovePriority:"},{"path":"E:/Google Drive/SLink/.cache/pret/pokecrystal/engine/battle/core.asm","line":819,"expect":"ld a, [wCurPlayerMove]"},{"path":"F:/slink-work/wt/polished/lua/gen2/writes.lua","line":245,"expect":"wCurPlayerMove goes LAST"},{"path":"F:/slink-work/wt/polished/lua/gen2/client.lua","line":20,"expect":"frame end"},{"path":"F:/slink-work/wt/polished/docs/polished/RAM.md","line":44,"expect":"wMirrorHerbPendingBoosts"}]
```

## Implemented (2026-10-06): the Rival Team Swap writer, composed and refusing by default

`lua/gen2/polished_rival.lua`, composed by `compose_polished` (`lua/gen2/entry.lua`), tests
`tests/unit/test_polished_rival_path.py`. `server/**`, `client.lua`, `polished_explode.lua`,
`polished_writes.lua` and every `supports_*` flag are untouched.

**What it writes** (WRAMX bank 1, all through its own `Permit`, in this order, every byte read back):
`wOTPartyMons` (`count x 48`), `wOTPartyMonOTs` (`count x 11`), `wOTPartyMonNicknames` (`count x 11`), then
`wOTPartyCount` LAST. `01:D284` (`wMirrorHerbPendingBoosts`) is excluded by the permit bounds. The `allow` predicate is
narrowed to exactly the four ranges the count needs. A read-back mismatch restores the saved originals (count
untouched when an array failed). The records are the partner's complete 70-byte blobs (the server's
`replace_rival_team` payload); nothing is rebuilt, so `polished_stats.lua` (the box-withdraw twin) is not used.
The blob constants the client reads (`PARTYMON_STRUCT_LENGTH` 48, `MON_HP` 34, `MON_SPECIES` 0) are derived from the
profile's `structs.party`, the `.sym`-backed geometry; the generated `profile.json` still does not carry them.

**What it refuses, before writing a byte:** an empty rival-class set (the default), a trainer class outside the set, a
stale trainer or `wCurOTMon`/`wCurPartyMon`, a battle that is not `TRAINER_BATTLE`, link / native save / backup save
(the `rival` battle-hold kind, which also re-reads the `0f:47DD` site bytes from the executed ROM), a CPU that is not at
`0f:47DD` (`hROMBank == 0x0F` and `io.register("PC") == 0x47DD`), count 0 or above 6, an index outside the new party or a
mon with no HP being sent out, an unknown species, an egg, a level outside 1..100, an incomplete record/OT/nickname.

**Production gate amendment (2026-10-08, g2p-rival-prod):** the writer now also
requires `io.read_u8(profile.hram.hBattleTurn, "System Bus") == 1` and a non-nil
`ctx.trainer_id` equal to the current `class * 256 + id`, before constructing the
write plan (`lua/gen2/polished_rival.lua:140-145`). The existing generated HRAM
field supplies `$FFD1` (`data/games/polished_crystal/profile.json:400`, generated
from `hBattleTurn`); no generator/profile change and no literal address fallback.
The class set remains caller-configurable; fixture class `$1B`/ID3 is not policy.
Player side, wild mode at the exact site, missing identity and stale identity
all refuse with zero writes; a configured `$1E`/ID7 enemy send-in is accepted by
the model. Source-copy mutants removing side and restoring optional identity
make the refusal assertion red through actual 141-byte wrong acceptance.

The probe-level LIVE result is separate (`RIVAL_STAGING.md`, operation-predicate
card): wild enemy initialization reaches this site too (`core.asm:8079-8086`),
so bank/PC alone is insufficient. This amendment ran no emulator and does not
prove swap consumption. `signals.lua` needs no change for the writer's fail-closed
safety: it dispatches the window, and this writer plans before any write. A later
signal-level filter could avoid non-rival dispatch, but must use the same live
side/mode/class/bound identity and may not replace these writer checks. Client,
entry, overworld and signal composition are unchanged. The existing legacy poll
(`client.lua:2630`) does not pass trainer_id: it now refuses explicitly even if
its PC is forged. The future caller must propagate the identity bound to the
pending command, not derive a fresh identity from current RAM. Gen 2 CODE_DIGEST is
staled by the production Lua edit and must be refreshed at the coordinated cut.

Verification on this card: rival-path **42 passed**, explode-path **44 passed**,
release-manifest **3 passed** (combined 89, no skips), including both in-process
guard mutants and a Lua 5.5 compile-only check; Ruff and diff checks clean.
The player-side and missing-ID cases failed red-first before the two assertions.

**Source-tested (model only):** the exact bytes and write order, the narrowed ranges, every refusal above with zero
writes, the read-back and restore, and eight mutant tests of the real module, each shown red (count first, a count
write reaching `D284`, no PC gate, no array read-back, no count read-back, widened ranges, a drifted write that only the
narrowed `allow` stops, a vanilla species-list write). The suite caught one real defect during the work: `proxy:arm`
shadowed the narrowed `allow` with the caller's `nil`.

**NOT proven, and the swap cannot land on a running game today:**
- **The live hold at `0f:47DD`.** No client hook is registered there (`client.lua` hooks only `0f:416A`, and only polls
  for the rival at a frame end). Through the client every attempt is refused by the PC gate (frame end) or by
  `wCurOTMon == 0xFF` being outside the new party. Landing the swap needs a client change (park the reply, run it from a
  `0f:47DD` exec hook) that this card was not allowed to make.
- That BizHawk's `emu.getregister("PC")` reads the instruction's own address inside an exec callback (UNVERIFIED live).
- The window's closing edge (`0f:480d`, §10.3) and that a write at `0f:47DD` is consumed by the copy: still ROM-byte
  reasoning only, no emulator run.
- **Which trainer classes count as rival is an OWNER DECISION (§3.4) and is not made here.** The writer takes
  `deps.rival_classes` (wOtherTrainerClass values) or `:set_classes()`; nothing in the production composition supplies
  it, so it refuses. The server separately gates `replace_rival_team` on the adapter's `rival_trainer_ids()` and the
  per-run `rival_team_swap` flag; `supports_explode_mode`/rival capability flags stay as they were.

### Review corrections (2026-10-06, headless Codex cx-c01c159e, coordinator-verified)
* The write list in section 10.5 above says level `+30` and implies the count first: both are SUPERSEDED. The party struct has Level at **+31** (profile
  `structs.party.Level`) and the implemented order is arrays, read-back, then `wOTPartyCount` LAST.
* The species check takes a RAW species id (the species table, 1..$123 with holes); variant BaseData record indices (292..337) are not species. Fixed.
* A failed rollback is no longer hidden: if the saved originals do not read back, the error is `TORN ENEMY PARTY: <original>; rollback FAILED: <why>`; a
  server treats every non-empty error as a failed swap, so a torn party is only distinguishable by this text. UNVERIFIED live.

### Landing the swap: the client hook plan (Polished peer cx-cfd8df54, coordinator-verified 2026-10-06)
The writer is composed and refuses because `client.lua` only polls at a frame end (`rival_tick`, `wCurOTMon == $FF`), drains the parked command there, and the writer requires the CPU at `0f:47DD` with a real selected enemy index (`wCurOTMon`/`wCurPartyMon` equal and inside the new party). The gate is already declared (`write_checkpoint.json` `battle_hold.rival_swap_gate` pc 18397 = $47DD, bank 15; `engine_signals.json` `SendInUserPkmn+149`, bytes `21 8B D2`, last consumption `0f:480D` still SOURCE_CANDIDATE).
**Minimal client change (optional, Polished-only; vanilla frame-end flow unchanged):** register one `io.on_bus_exec` hook at the gate (bank checked FIRST, a wrong-bank hit consumes nothing); keep the frame-end announcement and blob parsing but do NOT drain or clear `pending` there; at the FIRST qualified initial send-out consume the pending command once (a late reply never applies at a later send-out), read the live index in the callback, call the proxy `arm("rival_swap")` / `write_enemy_party` / `disarm` inside `pcall`, report from the next frame end; no logging, network or UI in the callback; do not borrow the explode hook token. The write is 71..421 bytes plus read-back (n = 1..6): timing inside an exec callback is UNMEASURED.
**Cards:** P0 a read-only probe (exec hook at 0f:47DD recording the callback-observed PC register, bank, frame, class/id, selected index; zero writes) falsifies the 'PC reads the instruction address' assumption; P1 the optional client callback state machine + tests (first falsifier: drained at frame end, FF required, double write, wrong-bank hit closes the window, late reply applies at a later send-out); P2 only if P0 needs a hook witness instead of raw PC equality; P3 the class policy wiring after your ruling; P4 the live consumed-write proof (the post-480D enemy battle record equals the staged record; n=1 and n=6 timing; rollback).
**Owner decisions:** (1) which classes count as rival: the five class values are RIVAL0 $1B, RIVAL1 $1C, RIVAL2 $1D, LYRA1 $1E, LYRA2 $1F; the server adapter ALREADY treats all five as rivals (`gen2_polished.py` `_rival_ids`) while the writer's set is empty by default, so the policy is currently inconsistent; (2) whether a SYNTH-forced trainer battle (a script/engine setup, as the special-entry probe used for the receptionist) is authorised for P0, or a played route to a trainer is required: writing `wOtherTrainerClass/ID` alone does not construct a battle; candidates near the Route 29 fixture are the Cherrygrove rival trigger (33,6)/(33,7) and Route 30 trainers, reachability from the fixture UNVERIFIED.
