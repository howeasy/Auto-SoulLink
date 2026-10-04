# SITES-MIN — the minimum engine-site set for one wild capture (Polished)

Milestone B, `docs/polished/CLIENT.md` C-SITES. This is a **design doc only**; it
writes nothing outside itself.

**Rule followed: no PC is guessed.** Every PC is either read from
`data/polished/polishedcrystal.sym` with a `sym:<line>` cite, or is a *source line*
inside a named routine and is flagged for the coordinator's byte re-derivation.

## 1. The minimum set is ONE site, not three

The vanilla design carries three capture rows (`docs/gen2/gen2_engine_sites.md:58,59,125,126`):

| vanilla row | vanilla PC | when |
|---|---|---|
| `capture_party` | `03:6adb` | immediately after `predef TryAddMonToParty` |
| `capture_box` | `03:6b44` | immediately after `predef SendMonIntoBox` |
| `capture_party_finalized` | `03:6be2` | after the nickname prompt |
| `capture_box_finalized` | `03:6be2` | same PC, disambiguated by `prior` |

`lua/gen2/signals.lua:68-69` binds `capture_party={collection="party",selector="last"}`
and `capture_box={collection="box",selector="first"}`; `:79-80` then make the two
`*_finalized` rows carry `acquisition="wild"` against their `prior`.

**For milestone B only one is needed.** The party-insert point below fires only when
the mon went to the **party**, and a full party is routed to the box by the game itself
(`engine/items/item_effects.asm:500-502`, `ld a,[wPartyCount] / cp PARTY_LENGTH /
jmp z,.SendToPC`). So a client that wants "one wild capture acquisition" in the common
case needs exactly **one** PC, and the box case is a follow-on, not a prerequisite.

## 2. The PC

### 2.1 Where the party insert completes

`engine/items/item_effects.asm`, inside `PokeBallEffect` (`03:63a0`, `sym:3373`):

```
500:    ld a, [wPartyCount]
501:    cp PARTY_LENGTH
502:    jmp z, .SendToPC          ; full party -> box instead
504:    xor a                    ; PARTYMON
505:    ld [wMonType], a
509:    ld hl, wPartyCount
510:    ld a, [hl]
511:    inc [hl]                 ; count bumped BEFORE the record copy
512:    ld hl, wPartyMon1
513:    push af
514:    call GetPartyLocation
517:    ld hl, wOTPartyMon1
518:    ld bc, PARTYMON_STRUCT_LENGTH
519:    rst CopyBytes             ; the mon itself
522:    ld hl, wPartyMonOTs ... 528: rst CopyBytes    ; OT
530:    ld hl, wPartyMonNicknames ... 536: rst CopyBytes ; nickname
538:    farcall SetCaughtData    ; <-- PROPOSED MINIMUM PC
```

**The earliest point where a successful wild catch is certain and the mon is fully in
`wPartyMon*` is the instruction at `engine/items/item_effects.asm:538`.** Three
`rst CopyBytes` have completed: the 48-byte `PARTYMON_STRUCT_LENGTH` record (`:519`),
`NAME_LENGTH` OT (`:528`) and `MON_NAME_LENGTH` nickname (`:536`).

**UNVERIFIED — the byte offset.** I did not resolve `:538`'s address before the kill
limit. Re-derive it from the `.sym`: it lies inside `PokeBallEffect` `03:63a0`
(`sym:3373`), i.e. at `03:63a0 + N` for the line offset *N*. **Do not accept this card
until the coordinator reads the ROM bytes there** — `farcall` in Polished is not
`3e bank / ea lo hi`, so my earlier guess was wrong and I am not offering one.

### 2.2 Why the PC differs from vanilla's

Vanilla's `capture_party` (`03:6adb`) sits *immediately after* `predef TryAddMonToParty`
— one routine call earlier in the flow. Polished **inlines the party insert** inside
`PokeBallEffect` (`:509-536`, three explicit `rst CopyBytes`) instead of calling a
predef, so there is no single post-call PC to use. The equivalent boundary is the
first instruction after the last of those copies. Polished *does* still use
`predef TryAddMonToParty` elsewhere (`engine/battle/core.asm:5929`,
`engine/events/npc_trade.asm:164`, `engine/events/wonder_trade.asm:209,446`) — the catch
path is the one that does not.

Consequence for a Polished port: the site's identity is *"the mon record, its OT and
its nickname are all in the party arrays"*, expressed as a PC, rather than
*"TryAddMonToParty returned"*. That is a slightly weaker invariant to state but the
same observable moment.

## 3. What the handler must read at that PC

Vanilla's binder expects a *named observation*, not raw bytes: `lua/gen2/signals.lua:13`
documents each site's `authority` / `owner` / `max_pending`, and `:144-145`
(`EFFECT_CONTRACT`) records which RAM each signal mutates — `capture_party="wPartyCount"`,
`capture_party_finalized="wPartyCount"`.

For Polished, at the `:538` PC the handler reads **system-bus WRAM only**:

| what | bank:addr | sym line | why |
|---|---|---|---|
| `wPartyCount` | `01:dcce` | `:67522` | which slot is new; already incremented at `:511` |
| `wCurPartyMon` | `01:d10c` | `:65782` | selects the record |
| `wPartyMon1` + `PARTYMON_STRUCT_LENGTH` | `01:dcd6` | `:67524` | the mon itself (48 B, Polished layout) |
| `wCurSpecies` / `wCurForm` | — | **UNVERIFIED** | I did not resolve these; the species the copy just wrote is the authoritative one |
| `wBattleType` | `01:d216` | `:53814` | guards wild vs contest vs roamer |

**Shape:** mirror `signals.lua:68`'s `{collection="party", selector="last"}` — the new
mon is `wPartyMon(wPartyCount-1)`, i.e. **the last party slot**, because `inc [hl]` at
`:511` precedes the copy. A `selector="last"` binder therefore ports unchanged.

**The species decode is not vanilla's.** Polished's `breed_struct` carries a 2-byte
species: `Species` at +0 is `LOW(species)` and the form/ExtSpecies byte carries
`HIGH(species)<<5 | form` (`macros/data.asm:89-91`; `constants/pokemon_data_constants.asm:244-253`).
The handler must combine both bytes. **UNVERIFIED:** the exact byte offsets of the two
species bytes inside the 48-byte struct — I did not re-derive `MON_SPECIES`/`MON_FORM`
offsets this pass.

## 4. The overworld frame gate

**`NextOverworldFrame` exists in Polished** — `engine/overworld/events.asm:114`,
`sym:12671`-adjacent entry `25:51a5` (sym line recorded by the generator, symbol
`NextOverworldFrame`), called from `engine/overworld/events.asm:99`.

So the vanilla per-frame hook has a counterpart and **no new gate needs inventing**.
`OvwFrameCounter` is **absent from the sym** (I looked) — if the vanilla client keys off
a frame counter, Polished's equivalent counter name is **UNVERIFIED**.

## 5. What `engine_signals.json` already has vs what is missing

Already RESOLVED in `data/games/polished_crystal/engine_signals.json` (40 of 52 resolved):

| row | status | symbol | bank:addr | flat | `expected_hex` |
|---|---|---|---|---|---|
| `capture_party` | RESOLVED | `PokeBallEffect` | `03:63a0` | `0xE3A0` | `FA33D2A7CAB3` |
| `capture_box` | RESOLVED | `PokeBallEffect.SendToPC` | `03:6590` | `0xE590` | `CD9F2ACDC05C` |
| `capture_party_finalized` | RESOLVED | `PokeBallEffect.return_from_capture` | `03:666d` | `0xE66D` | `FA36D2FE0628` |
| `capture_box_finalized` | RESOLVED | `PokeBallEffect.return_from_capture` | `03:666d` | `0xE66D` | `FA36D2FE0628` |

**The gap, and it is the whole point of this card:** `capture_party` is currently pinned
to **`PokeBallEffect`'s routine head**, i.e. *before* the catch has been decided. At
`03:63a0` the ball has not yet been shaken, `wBattleResult` has not been set
(`:497-498`), and the party insert has not happened. **A client armed at the generated
PC would fire on every ball use, including escapes.**

What is missing is therefore one row — a **post-insert** `capture_party` at the `:538`
boundary — plus the box equivalent at `:600`'s `farcall SetBoxMonCaughtData`. Everything
else the vanilla three-row flow needs is already resolved.

## 6. Red control and the one live measurement owed

**Red control (synthetic, no hardware).** Reuse the shape already proven for the
ROM-table reader: a synthetic image with `PokeBallEffect` entered at `03:63a0`, a
`wPartyCount` of 0 and a scripted `wOTPartyMon1`, then replay the instruction stream
from `:509` to `:538`. Fire the hook at each candidate PC in turn and assert exactly one
fires, with the party slot populated. **Mutate the image** by setting `wBattleResult`
without running the copy (a failed shake) and assert zero fires — that is the falsifier
for a site placed too early.

**The single live measurement still owed:** one non-synthetic run carrying the frame
alignment for this PC, exactly as `lua/gen2/signals.lua:289` already demands for the
vanilla capture RAM-effect. `:307-315` shows the existing mechanism: `live_capture`
stays false until a real run supplies `run.frame_alignment.battle_party`, and the
capture RAM-effect check refuses to be validated on synthetic data alone. The Polished
site inherits that debt.

```json
[
 {
  "path": "F:/slink-work/wt/polished/docs/gen2/gen2_engine_sites.md",
  "line": 58,
  "expect": "| `capture_party` |"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/gen2/gen2_engine_sites.md",
  "line": 59,
  "expect": "| `capture_box` |"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/gen2/gen2_engine_sites.md",
  "line": 125,
  "expect": "| `capture_party_finalized` |"
 },
 {
  "path": "F:/slink-work/wt/polished/lua/gen2/signals.lua",
  "line": 68,
  "expect": "capture_party={collection=\"party\",selector=\"last\"}"
 },
 {
  "path": "F:/slink-work/wt/polished/lua/gen2/signals.lua",
  "line": 69,
  "expect": "capture_box={collection=\"box\",selector=\"first\"}"
 },
 {
  "path": "F:/slink-work/wt/polished/lua/gen2/signals.lua",
  "line": 79,
  "expect": "capture_party_finalized={prior=\"capture_party\",acquisition=\"wild\"}"
 },
 {
  "path": "F:/slink-work/wt/polished/lua/gen2/signals.lua",
  "line": 144,
  "expect": "S.EFFECT_CONTRACT = {capture_party=\"wPartyCount\""
 },
 {
  "path": "F:/slink-work/wt/polished/lua/gen2/signals.lua",
  "line": 307,
  "expect": "live_capture"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/items/item_effects.asm",
  "line": 325,
  "expect": "PokeBallEffect:"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/items/item_effects.asm",
  "line": 502,
  "expect": "jmp z, .SendToPC"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/items/item_effects.asm",
  "line": 538,
  "expect": "farcall SetCaughtData"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/items/item_effects.asm",
  "line": 600,
  "expect": "farcall SetBoxMonCaughtData"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/overworld/events.asm",
  "line": 99,
  "expect": "call NextOverworldFrame"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/overworld/events.asm",
  "line": 114,
  "expect": "NextOverworldFrame:"
 },
 {
  "path": "F:/slink-work/cache/polished/src/macros/data.asm",
  "line": 89,
  "expect": "MACRO? dp ; db species, extspecies | form"
 },
 {
  "path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm",
  "line": 244,
  "expect": "DEF EXTSPECIES_MASK  EQU %00100000"
 },
 {
  "path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm",
  "line": 245,
  "expect": "DEF FORM_MASK        EQU %00011111"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/battle/core.asm",
  "line": 5929,
  "expect": "predef TryAddMonToParty"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/npc_trade.asm",
  "line": 164,
  "expect": "predef TryAddMonToParty"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 3373,
  "expect": "03:63a0 PokeBallEffect"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 3381,
  "expect": "03:6590 PokeBallEffect.SendToPC"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 3392,
  "expect": "03:666d PokeBallEffect.return_from_capture"
 }
]
```


---

## Coordinator re-derivation (2026-10-04) - the blocking PC

The OMP left the byte offset of `farcall SetCaughtData` unresolved. Re-derived from the release ROM
(`polishedcrystal-3.2.3.gbc`, sha1 6930b48a) and the `.sym`:

* `farcall` assembles to `rst FarCall` (`D7`) followed by `dw addr / db bank` (`macros/rst.asm:7`).
  `SetCaughtData` is `13:4508`, so the instruction is `D7 08 45 13`.
* The only occurrence in `PokeBallEffect` (`03:63a0`..`03:66a1`) is at **03:652D**, flat **0xE52D**:
  `... 01 0B 00 E7 | D7 08 45 13 | FA 09 D1 ...` = `ld bc, NAME_LENGTH(11)` / `rst CopyBytes` (the OT
  copy completes at 0x652C) / `rst FarCall SetCaughtData` / `ld a,[wCurItem]`.
* The pinned sequence for the site is therefore `expected_hex = D7084513FA09D1`, `symbol_offset` =
  0x652D - 0x63A0 = **+0x18D** from `PokeBallEffect`, bank 3.
* Confirmed wrong: the generated `capture_party` row (`engine_signals.json`) sits at `symbol_offset 0`
  (`03:63A0`, `FA33D2A7CAB3`), the routine head, though it is labelled `post_insert_pre_nickname`.
  A client armed there fires on every ball use. F1 stands; F2's PC is now resolved.
* The OT copy (`ld bc, 11 / rst CopyBytes`) before it is the second copy; the nickname copy is the
  third (`MON_NAME_LENGTH` is also 11), so 0x652C is the nickname `rst CopyBytes` and 0x652D is the first
  instruction after all three. (Three `E7` precede it in the routine; the preceding `0B 00 E7` is the
  nickname copy.)


---

## Coordinator correction to the re-derivation above (2026-10-04)

The PC above is off by two bytes: `rst FarCall` (`D7`) is at **03:652B** (flat 0xE52B, `symbol_offset`
+0x18B), not 03:652D; the `08 45` match I scanned for is the *address operand* (0x652C). Bytes:
`652A=E7 (rst CopyBytes), 652B=D7, 652C=08, 652D=45, 652E=13, 652F=FA`. A hook at 0x652D would sit
mid-instruction and never fire. The SITE-REPIN worker caught it; `engine_signals.json` pins 0x652B.
