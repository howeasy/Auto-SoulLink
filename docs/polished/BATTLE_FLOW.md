# Polished Crystal 3.2.3 — battle faint flow, hold oracles, write windows

Resolves the three blockers left open by `docs/polished/ENGINE_SITES.md` §9:
the `battle_faint` site, the two `battle_hold` oracles, and the two vanilla client
write windows (`force_explode`, `replace_rival_team`).

**Sources.** Polished v3.2.3 (commit `3fa43192379df5c3e7b09a08e4d5d79af4f02f42`)
from `F:/slink-work/cache/polished/src`; symbols from
`F:/slink-work/wt/polished/data/polished/polishedcrystal.sym` (cited as `sym:<line>`);
vanilla from the pokecrystal pin at `E:/Google Drive/SLink/.cache/pret/pokecrystal`
(commit `7a7881d0d62e0ddbd82dcf10e7116807487ac651`); client behaviour from
`lua/gen2/writes.lua` and `lua/gen2/client.lua`.

**Two corrections to `ENGINE_SITES.md` land in this document** (§1.2 and §3.2). Both
were mine, both were found by reading source instead of pattern-matching labels.

## 1. `battle_faint` — the `before_party_copyback` boundary

### 1.1 The flow

```
ResolveFaints                      core.asm:708   sym:10438  0f:44af
  push hBattleTurn                                        :712
  if wWhichMonFaintedFirst != 0                          :715-717
     call FaintUserPokemon                               :720   sym:10558  0f:4cd2
     call SwitchTurn                                     :721   sym:1078   00:3432
     call FaintUserPokemon                               :722
     call SwitchTurn                                     :723
.no_fainted_mons                   core.asm:725   sym:10439  0f:44c7
  pop af                                                :726
  ldh [hBattleTurn], a                                   :727   <-- THE BOUNDARY
  call UpdateBattleMonInParty                            :729   sym:1099   00:34b0
  call UpdateEnemyMonInParty                             :730   sym:1100   00:34c3
  ... victory music / GiveExperience / .check_battle_over :732+
```

### 1.2 The boundary, precisely

**The vanilla equivalent of `before_party_copyback` is the instruction at
`engine/battle/core.asm:727`, `ldh [hBattleTurn], a`** — the last instruction before
`call UpdateBattleMonInParty` at `:729`.

Vanilla's site was `UpdateFaintedPlayerMon`, `phase=before_party_copyback`. In
Polished the faint *animation* happens in `FaintUserPokemon` (`:720`, `:722`), and
the actual data movement out of the battle struct happens 6-9 instructions later, in
the two `Update*InParty` calls. So the Polished boundary is **not** the faint
routine — it is the `ldh` immediately preceding the copy-back. This is the direct
answer to the `battle_faint` blocker.

Address: `.no_fainted_mons` is `0f:44c7` (`sym:10439`). The next two instructions
are `pop af` (1 byte, `$F1`) and `ldh [nn], a` (2 bytes, `$E0 nn`), so the
instruction at `core.asm:727` begins at **`0f:44ca`**.
> **UNVERIFIED:** that byte arithmetic is derived from the SM83 encoding, not read
> out of a ROM. `0f:44ca` must be confirmed against a built `.gbc` before it is
> armed. The *symbol* `0f:44c7` and the *ordering* are source-certain.

### 1.3 Which RAM is authoritative at that instant

| | Address | Status at `:727` |
|---|---|---|
| `wBattleMonHP` | `00:c4b8` (`sym:63880`) | **authoritative** — holds the live battle HP |
| `wCurBattleMon` | `01:d0da` (`sym:65728`) | **authoritative** — selects which party slot is being copied |
| `wBattleMonStatus` / party `MON_STATUS` | party slot via `wPartyMon1` (`01:dcd6`, `sym:67524`) | **stale** — not yet updated |

`UpdateBattleMonInParty` (`sym:1099`, `00:34b0`) is what writes the battle struct
into the party record. Therefore:

- **A client write to the battle struct is the correct act at this boundary.**
  Write `wBattleMonHP` and it is flushed into the party by the two instructions that
  follow, atomically from the game's point of view.
- **A client write to the party mon's HP here is lost.** The copy-back overwrites it
  microseconds later. This is the precise failure mode `before_party_copyback` was
  named for, and it is the reason the vanilla site exists at all.
- Because the boundary is *before* the copy-back, the receipt the client takes must
  be keyed on the **battle struct**, and the party snapshot it emits must be
  reconciled on the next non-battle read — not assumed at this instant.

## 2. The `battle_hold` oracles

`write_checkpoint.json`'s `battle_hold` names two oracles. One resolves cleanly;
the other resolves by role rather than by name.

### 2.1 `LostBattle` — present, unchanged name

| | vanilla | Polished |
|---|---|---|
| symbol | `LostBattle` | `LostBattle` |
| bank:addr | `$0F:5396` | `0f:4ff6` (`sym:10612`) |
| source | `engine/battle/core.asm` | `engine/battle/core.asm:2589` |
| verdict | — | **`same`** (renamed address only) |

`ENGINE_SITES.md` §9 risk 2 said this oracle was absent from the Polished sym. **That
was wrong** — my earlier lookup searched a narrow pattern set and missed it. The
label exists. It is reached from `core.asm:62`, `core.asm:4890`, and from the
`ResolveFaints` `.lost` path at `core.asm:773-781`, where `wBattleResult` is
incremented and then `call LostBattle` fires at `:779`. That third call site is the
whiteout decision point: it is inside `ResolveFaints`, after
`CheckPlayerPartyForFitPkmn`, and it is the first moment the engine knows the player
has lost. **This is the oracle to arm.**

### 2.2 `HandlePlayerMonFaint` — absent by name, replaced by role

`HandlePlayerMonFaint` does not exist in Polished (pokecrystal defines it at
`engine/battle/core.asm:2607` and calls it at `:302`, `:335`, `:885`, `:903`, `:906`).
No `HandlePlayerMonFaint`, `HandleEnemyMonFaint`, `HandleFaintedMon` or
`FaintedMonActions` appears anywhere in the Polished sym.

Its role — "does the player have a fainted mon, and if so which side just lost a
turn" — is played by **`HasPlayerFainted`** (`sym:1159`, `00:3684`), called from:

- `engine/battle/core.asm:4726`
- `engine/battle/endturn.asm:88` — "If player is fainted in wild battle, maybe try flee"
- `engine/battle/endturn.asm:100` — builds the two-bit side mask in `e`

The dispatch that consumes it is `engine/battle/endturn.asm:97-110`, the
`.player_not_fleeing` block: `call HasPlayerFainted` sets bit 0 of `e`,
`call HasEnemyFainted` sets bit 1, and `ld a, e / and a / ret z` exits when neither.

**Oracle verdict: `renamed` by role.** Arm `HasPlayerFainted` at `00:3684` together
with the `.player_not_fleeing` dispatch in `endturn.asm`, not a single label. The
write checkpoint's acceptance test should be "the held write is not consumed by the
faint-resolution path", which is observable at `ResolveFaints` (§1), so the oracle
set becomes: `HasPlayerFainted` (side decision) + `LostBattle` (run-over decision).

> **UNVERIFIED:** `endturn.asm`'s sub-labels are not in the `.sym` under the names
> used in the source comments; the dispatch boundary has to be derived from source
> and confirmed on hardware.

## 3. Vanilla write windows in Polished

### 3.1 `force_explode` — safe equivalent exists

The vanilla client holds writes at the instruction before
`call DetermineMoveOrder`: `lua/gen2/client.lua:18-19` names `battle_hold` as "the
in-battle death site (before `call DetermineMoveOrder`)", and
`lua/gen2/writes.lua:19` notes that `DetermineMoveOrder` reads the priority from
`wCurPlayerMove`.

Polished has the same shape. `call DetermineMoveOrder` is at
`engine/battle/core.asm:190`, inside `BattleTurn` (`sym:10379`, `0f:4109`), and
`DetermineMoveOrder` is `sym:10394`, `0f:4235`. Immediately after the call,
`core.asm:194` does `ldh [hBattleTurn], a` and `:195` `ld [wEnemyGoesFirst], a` —
so the call site is exactly the turn-ordering commit point, same as vanilla.

**Hold point: immediately before `call DetermineMoveOrder` at `core.asm:190`.**

Write order is unchanged and the last-write rule still applies:
`lua/gen2/writes.lua:245-246` — "wCurPlayerMove goes LAST: until it lands, the turn
still runs the move the player chose." `lua/gen2/writes.lua:246-261` composes the
explode span and asserts `gate.armed == "battle_hold"`.

Polished target RAM: `wCurPlayerMove`, at `.sym:64052` per `docs/polished/RAM.md:48`
— which also records that it moved relative to vanilla and is *not* a constant
delta from `wCurOTMon` because Polished inserts fields inside the block.

**Verdict: `safe equivalent exists`.** Two conditions:

1. The hold must precede `core.asm:190`, not vanilla's `core.asm:205`.
2. **`wCurPlayerMove` must be written last**, after the battle-struct and
   party-mirror writes, exactly as `writes.lua:245` already encodes.

> **UNVERIFIED:** Polished's `DetermineMoveOrder` (`core.asm:314-327`) branches on
> `CheckMoveSpeed` and `.equal_priority`; I did not confirm it still reads
> `wCurPlayerMove` for move priority the way vanilla's `CompareMovePriority`
> (`pokecrystal core.asm:815-819`) does. If Polised derived priority elsewhere, the
> explode write would land but not take effect.

### 3.2 `replace_rival_team` — condition survives, layout does not

**Correction.** `ENGINE_SITES.md` §2 mapped the vanilla `trainer_ready` site to
`InitEnemy.partyloop`. That is wrong. Reading `core.asm:8062-8077`, `.partyloop` is
the **boss-trainer player-party happiness walk** (`ChangeHappiness` per party mon),
reached only for `IsBossTrainer`. It has nothing to do with the enemy party.

The real trainer-party construction is earlier, at `core.asm:8039-8041`:

```
InitEnemy                        core.asm:8030   sym:11105  0f:7260
  farcall GetTrainerAttributes          :8039   sym:10049  0e:519b
  farcall ReadTrainerParty              :8040   sym:6112   07:4000
  farcall ComputeTrainerReward          :8041
  ld a, -1 / ld [wCurOTMon], a          :8051-8052
  ld a, TRAINER_BATTLE / ld [wBattleMode], a  :8053-8054
```

**The `wCurOTMon == $FF` condition survives.** `core.asm:8051-8052` sets
`wCurOTMon` to `$FF` for every trainer battle, exactly as vanilla does. Vanilla's
address is `00:c663`; Polished's is **`00:c4dd`** (`sym:63909`, moved `-0x186` per
`RAM.md:44`). The vanilla client's frame-end trigger
(`lua/gen2/client.lua:1186`: "trainer_battle_start is announced by rival_tick (frame
end)") therefore still has a valid predicate — but it must read `00:c4dd`, not
`00:c663`.

**The enemy-party layout does not survive, and this is the blocker.** Vanilla's
7 bytes after `wOTPartyCount` are `wOTPartySpecies1`, a real `$FF`-terminated
species list. In Polished those same 7 bytes are **`wMirrorHerbPendingBoosts`**
(`wOTPartyCount` `sym:66118` `01:d283`, `wOTPartyCount+1` = `sym:66119`). Per
`RAM.md:50` and `RAM.md:246`: writing an enemy species list there **clobbers Mirror
Herb state**, and Polished has **no enemy species list at all**.

Consequently, for `replace_rival_team`:

- **Do not** write a species list at `ot_block + 1`. Refuse, per `RAM.md:256`.
- Species must be written into each enemy's own `party_struct` `Species` byte, after
  `ReadTrainerParty` (`sym:6112`, `07:4000`) has built the party.
- **Every other field of the swap (level, held item, moves, DVs, EVs) keeps its
  vanilla offset inside the struct** — but the struct layout itself is *not*
  identical. `RAM.md:394` is explicit: "Same length, same head/tail, different
  middle", so a `PARTYMON_STRUCT_LENGTH == 48` assertion passes while every
  EV/DV/PP/field write lands 1-2 bytes off. PP moved `+23` -> `+22`
  (`RAM.md:182`), PP-ups occupy `+0x16` as one byte (`RAM.md:282`).

**Verdict: condition `same`, layout `changed-semantics`.** A safe Polished equivalent
exists, but only against the Polished struct layout, and the enemy-species-list half
of the vanilla write **has no equivalent at all**.

> **UNVERIFIED:** whether `ReadTrainerParty` leaves the party fully built and idle
> long enough for a frame-end write between it and the first `SendOutBattleMon` —
> i.e. whether the frame-end window is actually open. Needs a source read of
> `engine/battle/start_battle.asm` and a hardware trace.

## 4. Answers in one line each

| Blocker | Answer | Status |
|---|---|---|
| (1) `battle_faint` / `before_party_copyback` | `ldh [hBattleTurn], a` at `engine/battle/core.asm:727`, i.e. `0f:44ca` (2 bytes past `.no_fainted_mons` `0f:44c7`, `sym:10439`). Battle struct (`wBattleMonHP` `00:c4b8`) is authoritative; the party record is stale until `UpdateBattleMonInParty` (`sym:1099`) fires. | resolved; address `UNVERIFIED` |
| (2a) oracle `LostBattle` | `LostBattle` **exists** in Polished at `0f:4ff6` (`sym:10612`), `core.asm:2589`. `ENGINE_SITES.md` was wrong to call it absent. | resolved |
| (2b) oracle `HandlePlayerMonFaint` | absent by name; the role is `HasPlayerFainted` (`sym:1159`, `00:3684`) plus the `.player_not_fleeing` dispatch in `engine/battle/endturn.asm:97-110`. | resolved by role |
| (3a) `force_explode` hold | hold immediately before `call DetermineMoveOrder` at `core.asm:190` (inside `BattleTurn` `0f:4109`). `wCurPlayerMove` still written LAST. | safe equivalent exists |
| (3b) `replace_rival_team` | `wCurOTMon == $FF` condition survives (`core.asm:8051-8052`, `wCurOTMon` `00:c4dd`). Enemy-party **species list does not exist** — those bytes are `wMirrorHerbPendingBoosts`. | condition same, layout changed-semantics |

## 5. Claims

Each entry is (absolute path, 1-indexed line, exact substring on that line).
All were verified against the files at the time of writing.

```json
CLAIMS: [{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10438,"expect":"ResolveFaints"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10439,"expect":"ResolveFaints.no_fainted_mons"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10558,"expect":"FaintUserPokemon"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":1078,"expect":"SwitchTurn"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":1099,"expect":"UpdateBattleMonInParty"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":1100,"expect":"UpdateEnemyMonInParty"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":1159,"expect":"HasPlayerFainted"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":1157,"expect":"HasEnemyFainted"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10612,"expect":"LostBattle"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10394,"expect":"DetermineMoveOrder"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10398,"expect":"GetSpeed"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":11105,"expect":"InitEnemy"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":11106,"expect":"InitEnemy.partyloop"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":11108,"expect":"InitEnemy.wildmon"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10379,"expect":"BattleTurn"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10383,"expect":"BattleTurn.loop1"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10655,"expect":"CheckPlayerPartyForFitPkmn"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":6112,"expect":"ReadTrainerParty"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10049,"expect":"GetTrainerAttributes"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":10916,"expect":"LoadEnemyWildmon"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":63856,"expect":"wBattleMonHP"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":65728,"expect":"wCurBattleMon"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":67524,"expect":"wPartyMon1"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":65756,"expect":"wBattleResult"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":66054,"expect":"wBattleType"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":63909,"expect":"wCurOTMon"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":66118,"expect":"wOTPartyCount"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":66119,"expect":"wMirrorHerbPendingBoosts"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":64127,"expect":"wEnemyGoesFirst"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":64093,"expect":"wWhichMonFaintedFirst"},{"path":"F:/slink-work/wt/polished/data/polished/polishedcrystal.sym","line":70128,"expect":"hBattleTurn"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":708,"expect":"ResolveFaints:"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":314,"expect":"DetermineMoveOrder:"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":2589,"expect":"LostBattle:"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":8062,"expect":".partyloop"},{"path":"F:/slink-work/cache/polished/src/engine/battle/endturn.asm","line":89,"expect":".player_not_fleeing"},{"path":"F:/slink-work/wt/polished/lua/gen2/writes.lua","line":245,"expect":"wCurPlayerMove goes LAST"},{"path":"F:/slink-work/wt/polished/lua/gen2/writes.lua","line":249,"expect":"assert(gate.armed == \"battle_hold\", \"explode only inside the battle hold\")"},{"path":"F:/slink-work/wt/polished/lua/gen2/client.lua","line":18,"expect":"before"},{"path":"F:/slink-work/wt/polished/docs/polished/RAM.md","line":44,"expect":"wMirrorHerbPendingBoosts"},{"path":"F:/slink-work/wt/polished/docs/polished/RAM.md","line":83,"expect":"PP"},{"path":"E:/Google Drive/SLink/.cache/pret/pokecrystal/engine/battle/core.asm","line":205,"expect":"call DetermineMoveOrder"},{"path":"E:/Google Drive/SLink/.cache/pret/pokecrystal/engine/battle/core.asm","line":2607,"expect":"HandlePlayerMonFaint:"},{"path":"F:/slink-work/wt/polished/data/games/gen2_crystal/write_checkpoint.json","line":98,"expect":"\"battle-turn-before-determine-move-order\""},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":727,"expect":"ldh [hBattleTurn], a"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":729,"expect":"call UpdateBattleMonInParty"},{"path":"F:/slink-work/cache/polished/src/engine/battle/core.asm","line":8052,"expect":"ld [wCurOTMon], a"}]
```

## Coordinator note (2026-10-04): the boundary is ROM-verified

Release ROM bytes at `0f:44c7` (`ResolveFaints.no_fainted_mons`): `f1` (`pop af`), `e0 d1` (`ldh [hBattleTurn], a`), then at `0f:44ca` `cd b0 34` = `call UpdateBattleMonInParty` (sym `00:34b0`), followed by `cd c3 34` = `call UpdateEnemyMonInParty` (sym `00:34c3`). So `0f:44ca` is the first instruction of the copy-back, i.e. the last point at which the battle struct is authoritative. `LostBattle` is `0f:4ff6`. Still UNVERIFIED: whether Polished's `DetermineMoveOrder` reads `wCurPlayerMove` for priority (decides whether `force_explode` does anything), and the enemy-party write window.
