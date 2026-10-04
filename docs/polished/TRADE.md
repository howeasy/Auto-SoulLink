# Polished Crystal 3.2.3 — porting SLink's native trade

**Design card. Nothing here is implemented.** It maps SLink's existing Pokecenter Cable Club
receptionist trade (built for vanilla pokecrystal/GSC) onto Polished Crystal v3.2.3, names what is
identical, what changed, and what needs new design.

Sources: `patch/gen2/src/trade_*.asm`, `patch/gen2/src/slink.asm`, `patch/gb/slink_abi.inc`,
`lua/gen2/trade.lua`, `docs/polished/HOOKS.md` §2 row 12/13/18 and §3.5, and the pinned Polished
source at `F:/slink-work/cache/polished/src`. `docs/polished/HOOKS.md` §3.5 already carries most of
the symbol-level delta; this card adds the **flow order**, the **lease payload question**, the
**party-replacement model**, and the **edit list**.

**Convention.** Vanilla addresses are pokecrystal (`data/gen2/pokecrystal.sym`, bank `$64` etc.);
Polished addresses are `24:7601` style, rgblink **hex** banks. `flat` is the ROM file offset,
`bank * 0x4000 + addr - 0x4000`. **WRAM and HRAM are not in the ROM**: a WRAM symbol such as
`wSlinkMailbox` or `wPlayerTrademonCaughtData` has a `bank:addr` but **no flat offset and no ROM
bytes**. Every ROM byte quoted below is read from the release ROM and is marked as such; where I did
not read bytes, the cell says UNVERIFIED rather than guessing.

---

## 1. The vanilla flow, step by step, and Polished's equivalent

The vanilla overlay does not reimplement the trade; it **branches out of the receptionist script
into its own service, keeps a mailbox lease with the host (the Python server), and rejoins the
engine only to do the atomic party replace**. That shape is what has to survive the port.

### Step 1 — the receptionist script is intercepted

| | vanilla | Polished | verdict |
|---|---|---|---|
| script | `LinkReceptionistScript_Trade` `64:689d`, flat `0x10689d` | `LinkReceptionistScript_Trade` **`24:7601`**, flat `0x97601` | **moved** |
| the edit | `object_event … PAL_NPC_GREEN, OBJECTTYPE_SCRIPT` → pointer rewritten to `SlinkTradeReceptionistScript` | `maps/PokeCenter2F.asm:21` — **Polished dropped the colour field**: vanilla `0, 0, -1, -1, PAL_NPC_GREEN, OBJECTTYPE_SCRIPT` vs Polished `0, 0, -1, 0, OBJECTTYPE_SCRIPT` | **different literal, same shape** — still exactly one occurrence, still a 2-byte pointer rewrite (`HOOKS.md` §2 row 12) |
| quick save | `special TryQuickSave` `0a:5e66` | `Special_TryQuickSave` **`0a:4e46`**, called at `Pokecenter2F.asm:99` | **renamed** |
| mobile branch | present (`mobile/mobile_41.asm`, `BackupGSBallFlag` `41:6187`) | **ABSENT** — no Mobile in Polished | **drop** the `farcall` and its `EXPORT` (`HOOKS.md` §2 row 13) |
| branch point | vanilla's own script tail | **`maps/PokeCenter2F.asm:101`**, after the second `writetext Text_PleaseWait` | **CHANGED** — the whole body is the rewritten dialect (`iffalsefwd` / `iftruefwd` / `iffalse_endtext` / `warpcheck` / `readmem` / `scall`), plus a link-cable/version/room gauntlet at `:90`-`:119` |
| new guard | vanilla had none | `CheckPartyForMail` `0a:5274`, `callasm` at `Pokecenter2F.asm:88` | **NEW** — `SlinkTradeCheckIncoming` / `SlinkTradeItemAllowed` partially duplicate it (`HOOKS.md` §3.5); align rather than ship two mail policies |

**Design call:** `callasm` exists in Polished with identical encoding and the forced quick-save at
`:99` still precedes it, so option (a) — *branch after `:101` into `SlinkTradeEntry`* — still works and
is far smaller than option (b), a reimplementation. **Prefer (a)** (`HOOKS.md` §3.5).

### Step 2 — select the party mon

| | vanilla | Polished | verdict |
|---|---|---|---|
| menu | `SelectTradeOrDayCareMon` `14:401d`, `PARTYMENUACTION_GIVE_MON` | `SelectTradeOrDayCareMon` **`14:4002`** | **same shape, moved** |
| remove the sent mon | `RemoveMonFromPartyOrBox` `03:6039` | **`RemoveMonFromParty` `03:5d10`** (`engine/pokemon/move_mon.asm:894`) | **renamed, semantics narrowed** — "or Box" is gone. **UNVERIFIED** whether Polished still withdraws from a box mid-trade. |
| species list | `wOTPartySpecies` `01:d281` (1 byte/mon) | **ABSENT** | `trade_commit.asm` reads it 3×, `trade_service.asm` 1×. **UNVERIFIED** that Polished reads species from `wOTPartyMon1`'s first byte — must be read off the new OT-staging definition. |
| party species list | `wPartySpecies` `01:dcd8` | **ABSENT** (one commented reference, `engine/overworld/events.asm:1164`) | `SlinkTradeCheckParty`'s "species list whose `$FF` terminator is not at `wPartyCount`" bug-contest discriminator **loses its input**; a replacement is needed (**UNVERIFIED**). |

### Step 3 — the mailbox lease handshake

This is SLink's own, not the engine's. Vanilla service labels (`patch/gen2/src/trade_service.asm`):

`SlinkTradeEntry` → `SlinkTradeZeroContext` → `SlinkTradeCheckSaved` → `SlinkTradeCheckParty` →
`SlinkTradeWriteHeader` → publish `SLINK_TRADE_CMD_QUERY` → `SlinkTradeWaitAck` →
`SlinkTradeCheckHeader` → `SLINK_TRADE_CMD_OFFER` → `SLINK_TRADE_CMD_PROMPT` →
`SlinkTradeWaitApply` → `SlinkTradeApplyPickup` → `SlinkTradeCommit` →
`SlinkTradeReleaseSnapshot` → `SlinkTradeExit`, with `SlinkTradeDispatch` entered from the service
hook (`patch/gen2/src/slink.asm:118`).

Guards in between: `SlinkTradeCheckToken`, `SlinkTradeCheckHeldFrame`, `SlinkTradeCheckOwnSlot`,
`SlinkTradeCheckIncoming`, `SlinkTradeCheckName`, `SlinkTradeItemAllowed` /
`SlinkTradeAllowedItems(End)`, `SlinkTradeValidateSnapshot` / `SlinkTradeSnapshot` /
`SlinkTradeReleaseSnapshot`, `SlinkTradeCaptureContext`, `SlinkTradeNextGeneration`,
`SlinkTradePublishDone`, `SlinkTradeClose`, `SlinkTradeResponderSave`, `SlinkTradePromptEntry`.

**None of these is engine code, so none of them is affected by Polished's engine rewrite.** They are
`SECTION "Slink Trade Service", ROMX, BANK[SLINK_SERVICE_BANK]`, which is overlay-owned free space.
The two engine-facing pieces are the **receptionist anchor** (step 1) and the **party replace**
(step 5).

### Step 4 — the trade animation

| | vanilla | Polished | verdict |
|---|---|---|---|
| animation | `TradeAnimation` `0a:4f24` / `TradeAnimationPlayer2` `0a:4f63` | **`0a:5290` / `0a:52de`** | **same, moved** |
| SGB layout call | `GetSGBLayout` `00:3340` | **ABSENT** — Polished has `GetCGBLayout` `00:004c` / `GetMemCGBLayout` `00:004b` | **CHANGED** — `ld b, SCGB_DIPLOMA / call GetSGBLayout` in `panel.asm` **and** `trade_commit.asm` needs replacing. **UNVERIFIED** which call is right (`HOOKS.md` §3 row for `GetSGBLayout`). |
| vblank compare | `cp VBLANK_NORMAL` | Polished's `hVBlank` `00:ff8d` is a **0-8 vblank mode selector** indexing a dispatch table | **different** — `sfx.asm` and `trade_dispatch.asm` must re-derive |
| player-name copy | `wPlayerName -> wPlayerTrademonSenderName`, `wOTPlayerName -> wOTTrademonSenderName`, `bc NAME_LENGTH` (11) | `PLAYER_NAME_LENGTH` is **8** (`constants/text_constants.asm:3`) | **different — a latent overrun.** Polished's player name is 7 glyphs + terminator, so an 11-byte copy **runs 2 bytes past the field**. Must become `bc PLAYER_NAME_LENGTH`. |
| snapshot preimage | "70 bytes must not change" (48 struct + 11 OT + 11 nickname) | still 70 bytes and structurally right, but the byte *meaning* differs: Polished packs 6 EVs, packs 4 IVs into 2 bytes, folds gender/ability/nature/form/is-egg into the personality word, and stores level + a 3-byte caught-data block | **re-derive the refusal check, do not reuse it** — Polished legitimately mutates bytes vanilla never touched (`HOOKS.md` §3.5) |

### Step 5 — party replace and save

| | vanilla | Polished | verdict |
|---|---|---|---|
| add received mon | `AddTempmonToParty` `03:5a96` | **`AddTempMonToParty` `03:5980`** (`engine/pokemon/move_mon.asm:448`) | **renamed** |
| save | `Link_SaveGame` `05:4ab2`; overlay also calls `farcall BackupGSBallFlag` after | `Link_SaveGame` `05:46ea`; `SaveAfterLinkTrade` `05:46cc` — **Polished's own `LinkTrade` calls `SaveAfterLinkTrade` and nothing after it** | **same, minus the backup** |
| force-evolve | `EvolvePokemon` `10:61d8`, `wForceEvolution` `01:d1e9` | **`06:4000`**, `wForceEvolution` `01:d1ef` | **same, moved** (Pokedex bank `$10` → `$06`) |
| caught-data gender | `farcall GetCaughtGender` | **ABSENT** — gender is `MON_GENDER`, an alias of `personality + 1` | **must reconstruct the caught-data byte from the personality word** |
| frame wait | `trade_dispatch.asm` stack fingerprint `BANK(NextOverworldFrame)` at `sp+5` … | all four symbols exist (`NextOverworldFrame` **`25:5185`**, `DelayFrame` `00:0da8`, `DelayFrames` `00:0da1`) but every address and every `sp+` offset differs; Polished's caller chain runs through `farjp AnimateTitleCrystal` and a scene jumptable | **UNVERIFIED — the most fragile thing in the overlay, and it has no static proof** (`HOOKS.md` §2 row 18) |

---
## 2. The Polished `trademon` struct, and can the 16-byte lease carry a Polished mon?

### 2.1 The struct

`F:/slink-work/cache/polished/src/macros/ram.asm:252-272`, the `trademon` macro:

| offset | field | bytes |
|---|---|---|
| +0 | `Species` (`db`) | 1 |
| +1 | `SpeciesName` (`ds MON_NAME_LENGTH`) | 11 |
| +12 | `Nickname` (`ds MON_NAME_LENGTH`) | 11 |
| +23 | `SenderName` (`ds NAME_LENGTH`) | 11 |
| +34 | `OTName` (`ds NAME_LENGTH`) | 11 |
| +45 | `DVs` — `HPAtkDV`, `DefSpeDV`, `SatSdfDV` (3 × `db`) | 3 |
| +48 | `Personality` — aliases `Shiny`, `Ability`, `Nature`, `Gender`, `IsEgg`, `ExtSpecies`, `Form` (**one** `db`) | 1 |
| +49 | `ID` (`dw`) | 2 |
| +51 | `CaughtData` (`db`) | 1 |
| | **total** | **52** |

Vanilla's `trademon_struct` is the same shape **without** the personality word — **51 bytes**. So
Polished's trademon is exactly **one byte longer**, and that one byte is the one that carries
species-extension, form, ability, nature, gender and shiny.

### 2.2 Does the 16-byte lease hold a Polished identity?

`patch/gb/slink_abi.inc:39-53` and `patch/gen2/src/trade_frame.asm:15`:

```
DEF SLINK_OFS_TRADE_LEASE   EQU SLINK_CORE_SIZE
DEF SLINK_TRADE_LEASE_SIZE  EQU 16
DEF SLINK_TRADE_FRAME       EQU wSlinkMailbox + SLINK_OFS_TRADE_LEASE
```

Magic `SLT1` = `$53 $4C $54 $31` (`slink_abi.inc:42-45`), version 1 (`:46`). Frame offsets actually
written or read across `trade_*.asm`: `+0,+1,+2,+3` (magic), `+5` (cmd), `+6`, `+7`, `+8`, `+9`,
`+10`, `+11`, `+12`. **Bytes +4, +13, +14, +15 are unused** — three genuinely spare payload bytes
plus the version slot.

**Answer: yes, but only as a *reference*, not as a payload — and the lease must not grow for this.**

A Polished SLink identity is `DDDDDD:OOOO:SSS:TT` (`server/adapters/polished_codec.py:207`): 3 DV
bytes, 2 OT-ID bytes, a 9-bit species and a traits byte. That is 3 + 2 + 2 + 1 = **8 bytes** minimum,
or 7 if the traits byte is packed into the species word's high bits. A Polished mon's full
*appearance* for the trade animation needs more: nickname (11), sender name (8 with
`PLAYER_NAME_LENGTH`), OT name (8/11), the ability/nature/gender/form/shiny bits, and the ball.

Those already have a home: **the 52-byte `trademon` struct**. The lease's job is to say *which* slot
and *which generation*, not to carry the mon — which is exactly how the vanilla lease is used
(`+8`/`+9` = own slot, `+10`/`+11` = token, `+12` = result; the 4-byte token and the 10-byte
`SLINK_TRADE_CONTEXT` on the stack carry identity, `trade_service.asm:1-6`).

**Therefore: keep `SLINK_TRADE_LEASE_SIZE = 16`.** Two changes are needed, not a size change:

1. **`+6`/`+7` must carry a Polished-shaped identity, not a vanilla one.** Whatever vanilla packs
   there (a species byte plus a form byte, or an OT id) must be re-derived against Polished's
   `Species` + `Personality` encoding. **UNVERIFIED** what vanilla puts in `+6`/`+7` — I counted the
   offsets used but did not read the semantics.
2. **The snapshot preimage must change** (§1 step 4): the "70 bytes must not change" check is
   structurally still 48 + 11 + 11, but Polished's party struct has a different *meaning* per byte.

## 3. The party-replacement path in Polished

`engine/events/npc_trade.asm` `DoNPCTrade:` (`:90`) is the model, and it is only ~20 instructions:

```
	ld hl, wPartyMon1Level          ; the SENT mon's level
	ld bc, PARTYMON_STRUCT_LENGTH
	call Trade_GetAttributeOfCurrentPartymon
	ld a, [hl]
	ld [wCurPartyLevel], a          ; :153-156
	ld a, [wOTTrademonSpecies]      ; the RECEIVED species
	ld [wCurPartySpecies], a        ; :157-159
	xor a
	ld [wMonType], a                ; :160-161
	ld [wPokemonWithdrawDepositParameter], a
	predef RemoveMonFromParty       ; :163
	predef TryAddMonToParty         ; :164
```

So Polished replaces a party mon by **four writes plus two predefs**: set `wCurPartyLevel`,
`wCurPartySpecies`, `wMonType = 0`, `wPokemonWithdrawDepositParameter = 0`, then `RemoveMonFromParty`
and `TryAddMonToParty`. The received mon's bytes are staged in `wOTTrademon*` before this.

**This is the safe write window, and it is the same shape as vanilla's** — the overlay's
`trade_commit.asm` already sequences exactly this, so the port is a re-anchor, not a redesign. The
four things that must change:

| what | why |
|---|---|
| `bc NAME_LENGTH` → `bc PLAYER_NAME_LENGTH` on the two sender-name copies | 11-byte copy overruns Polished's 8-byte field by 2 (`HOOKS.md` §3.5) |
| `farcall GetCaughtGender` → reconstruct from `personality + 1` | `GetCaughtGender` is ABSENT; gender is a personality alias |
| drop `farcall BackupGSBallFlag` | ABSENT in Polished; its own `LinkTrade` calls `SaveAfterLinkTrade` and nothing after |
| `RemoveMonFromPartyOrBox` → `RemoveMonFromParty` | renamed, and the box half is gone (**UNVERIFIED** whether a box withdrawal is still legal mid-trade) |

**Dex flags.** `TryAddMonToParty` is the same call vanilla uses and handles the dex entry itself, so
there is no separate dex write to port — **UNVERIFIED** that Polished's `TryAddMonToParty` marks the
dex on a trade-received mon; read `engine/pokemon/move_mon.asm` around `03:5980`.

## 4. The overlay edit list

Same as vanilla where the anchor survives; new design where it does not. `SERVICE_BANK = $7E`, and
the mailbox is `wSlinkMailbox` at `$C60B` — **WRAM, no ROM bytes**.

| # | edit | vanilla | Polished | design |
|---|---|---|---|---|
| E1 | receptionist anchor: `object_event … OBJECTTYPE_SCRIPT`, rewrite the last field `LinkReceptionistScript_Trade` → `SlinkTradeReceptionistScript` | `maps/Pokecenter2F.asm` | `maps/PokeCenter2F.asm:21`, **colour field dropped** | **same edit, new literal**; still exactly one occurrence, still a 2-byte pointer rewrite |
| E2 | branch into `SlinkTradeEntry` | vanilla script tail | **`maps/PokeCenter2F.asm:101`**, after the second `writetext Text_PleaseWait` | **new anchor, same shape**; `callasm` encoding is identical and the `:99` quick-save still precedes it |
| E3 | `trade_receptionist.asm`'s `ASSERT BANK(LinkReceptionistScript_Trade) == SLINK_TRADE_MAP_BANK` | bank `$64` / `$5c` | bank **`$24`** | **update the constant** — the assert is the right shape and will fail loudly at link time (`HOOKS.md` §4) |
| E4 | `verify_trade_hook`'s hard-coded `(bank, address, original)` triple | `(0x64, 0x73b1, 0x689d)` | must be **re-derived** | **must change** — it asserts the reception pointer is untouched except its two bytes, and the address moved (`HOOKS.md` §2 row 12, §7) |
| E5 | drop `BackupGSBallFlag` export + `farcall` | present | ABSENT | **delete** |
| E6 | `GetCaughtGender` call | present | ABSENT | **replace** with a personality-word reconstruction |
| E7 | sender-name copies `bc NAME_LENGTH` → `bc PLAYER_NAME_LENGTH` | n/a | 8 vs 11 | **must change** or it overruns |
| E8 | `cp VBLANK_NORMAL` compares | `hVBlank` is a byte | 0-8 **mode selector** | **re-derive** (`sfx.asm`, `trade_dispatch.asm`) |
| E9 | `GetSGBLayout` | `00:3340` | ABSENT | **replace** with `GetCGBLayout 00:004c` / `GetMemCGBLayout 00:004b` — **UNVERIFIED which** |
| E10 | `trade_dispatch.asm` stack fingerprint | `sp+5`/`sp+12` | every offset differs | **re-measure** — highest-risk item, no static proof |
| E11 | snapshot preimage | "70 bytes must not change" | still 70 bytes, different meaning | **re-derive the check** |
| E12 | `SlinkTradeCheckIncoming` / `SlinkTradeItemAllowed` vs Polished's own `CheckPartyForMail 0a:5274` (`Pokecenter2F.asm:88`) | vanilla had no such guard | Polished has one | **new design**: align, do not ship two mail policies |
| E13 | mailbox: 40 bytes at `$C60B`; core 14 + trade lease 16 + 2 private sample | as vanilla | **same budget** | **same** — nothing in the lease needs to grow |
| E14 | service code in bank `$7E` ROMX | bank `$7E`, must be empty in the clean ROM | same constraint, plus the R6 overlay beacon now pins every overlay byte | **same**, and the beacon gives a free integrity check |

## 5. Risks

1. **The stack fingerprint (E10) has no static proof and every address moved.** If it is wrong the
   service is reachable from an unintended caller. Instrument or disassemble a Polished build first.
2. **`PLAYER_NAME_LENGTH` overrun (E7) is silent.** An 11-byte copy into an 8-byte field corrupts the
   next field and will not fault.
3. **The snapshot check (E11) is the same size but not the same contract.** Reusing vanilla's
   refusal logic would either accept a corrupted snapshot or refuse a legitimate one.
4. **Two mail policies (E12)** if the overlay's checks and `CheckPartyForMail` disagree — a player
   could be offered a trade the engine will refuse, or the reverse.
5. **No ROM bytes were read for any of this.** Every address in §1-§2 comes from HOOKS.md §3.5, which
   cites the sym; I re-derived only the `trademon` macro and `DoNPCTrade` from the Polished source.
   The two verifiers holding hard-coded addresses (E4, and the OVERLAY-ASM hash noted in FACT_CHECK)
   both need re-pinning.

## 6. Ordered cards, with the first falsifier for each

| # | card | first falsifier (what would kill it) |
|---|---|---|
| **T1** | Re-measure the frame-wait stack fingerprint against a Polished build | Disassemble `25:5185`'s overworld caller chain; if `BANK(NextOverworldFrame)` is not at `sp+5`, the fingerprint is unwinnable and E10 needs a new mechanism |
| **T2** | `verify_trade_hook` re-derivation + the `ASSERT BANK(...) == $24` | Link with the old triple; if the receptionist pointer is not the only mutable 2 bytes, the guard is unsound |
| **T3** | `PLAYER_NAME_LENGTH` / `GetCaughtGender` / `BackupGSBallFlag` removals | Assemble `trade_commit.asm` and `trade_snapshot.asm` for Polished; any unresolved symbol fails the build |
| **T4** | `trademon` snapshot contract: re-derive the preimage | Write two Polished snapshots differing only in bytes Polished legitimately rewrites; if the check accepts both, it is not a check |
| **T5** | lease semantics: what `+6`/`+7` mean under Polished | Write a lease with a Polished-form mon and read it back; if form/ExtSpecies is lost, the lease must carry the personality word |
| **T6** | `VBLANK_NORMAL` and `GetSGBLayout` replacements | Run `sfx.asm` and `trade_commit.asm` in a Polished build and compare frames |
| **T7** | align the overlay's mail checks with `CheckPartyForMail 0a:5274` | Offer a trade with a mail-holding mon; if the two disagree the player sees one answer and the engine does another |
| **T8** | party-replace window (E-set §3) on a real cartridge | Run one native trade end to end; the received mon must appear with its dex entry and the sender's slot must be freed |

**Sequencing:** T1 and T2 first — both are cheap, both are UNVERIFIED, and a wrong answer to either
invalidates the anchor design the rest depends on.

## 7. Machine-checkable citations

## Coordinator correction (2026-10-04) to F-1: the Polished `trademon` is 53 bytes, three more than vanilla (not one)

Measured from the symbols: Polished `wPlayerTrademon` `00:c51c` .. `wPlayerTrademonEnd` `00:c551` = 0x35 = **53 bytes** (`data/polished/polishedcrystal.sym:63956,64099`); vanilla Crystal `wPlayerTrademon` `00:c6d0` with OTName at `c6f2`, 11-byte OT name, 2 DV bytes, 2-byte ID and CaughtData = **50 bytes**. The macro (`macros/ram.asm:252-272`) shows the three extra bytes: a THIRD DV byte (`SatSdfDV`), `Personality` (Shiny/Ability/Nature, `00:c54c`) and a separate `ExtSpecies/Form/Gender/IsEgg` byte (`00:c54d`). The F-2 conclusion that the 16-byte lease need not grow is therefore still UNPROVEN (the lease names a slot and a generation; whether form/personality must also travel depends on `trade_frame.asm`/`trade_service.asm` semantics for lease bytes +6/+7, which were never read). Treat the lease as 16 bytes until a card proves otherwise.

```json CLAIMS
[
 {
  "path": "F:/slink-work/cache/polished/src/macros/ram.asm",
  "line": 252,
  "expect": "MACRO trademon"
 },
 {
  "path": "F:/slink-work/cache/polished/src/macros/ram.asm",
  "line": 201,
  "expect": "\\1Species::     db"
 },
 {
  "path": "F:/slink-work/cache/polished/src/macros/ram.asm",
  "line": 22,
  "expect": "\\1Personality::"
 },
 {
  "path": "F:/slink-work/cache/polished/src/macros/ram.asm",
  "line": 23,
  "expect": "\\1Shiny::"
 },
 {
  "path": "F:/slink-work/cache/polished/src/macros/ram.asm",
  "line": 28,
  "expect": "\\1ExtSpecies::"
 },
 {
  "path": "F:/slink-work/cache/polished/src/macros/ram.asm",
  "line": 223,
  "expect": "\\1Form::        db"
 },
 {
  "path": "F:/slink-work/cache/polished/src/macros/ram.asm",
  "line": 271,
  "expect": "\\1CaughtData::  db"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/npc_trade.asm",
  "line": 90,
  "expect": "DoNPCTrade:"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/npc_trade.asm",
  "line": 163,
  "expect": "predef RemoveMonFromParty"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/npc_trade.asm",
  "line": 164,
  "expect": "predef TryAddMonToParty"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/npc_trade.asm",
  "line": 159,
  "expect": "ld [wCurPartySpecies], a"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/npc_trade.asm",
  "line": 157,
  "expect": "ld [wCurPartyLevel], a"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/npc_trade.asm",
  "line": 104,
  "expect": "ld [wOTTrademonSpecies], a"
 },
 {
  "path": "F:/slink-work/cache/polished/src/maps/PokeCenter2F.asm",
  "line": 21,
  "expect": "LinkReceptionistScript_Trade"
 },
 {
  "path": "F:/slink-work/cache/polished/src/maps/PokeCenter2F.asm",
  "line": 88,
  "expect": "CheckPartyForMail"
 },
 {
  "path": "F:/slink-work/cache/polished/src/maps/PokeCenter2F.asm",
  "line": 99,
  "expect": "Special_TryQuickSave"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gb/slink_abi.inc",
  "line": 41,
  "expect": "DEF SLINK_TRADE_LEASE_SIZE EQU 16"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gb/slink_abi.inc",
  "line": 40,
  "expect": "DEF SLINK_OFS_TRADE_LEASE EQU SLINK_CORE_SIZE"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gb/slink_abi.inc",
  "line": 42,
  "expect": "DEF SLINK_TRADE_MAGIC_0 EQU $53"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gb/slink_abi.inc",
  "line": 46,
  "expect": "DEF SLINK_TRADE_VERSION EQU 1"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gb/slink_abi.inc",
  "line": 53,
  "expect": "DEF SLINK_PUBLIC_SIZE EQU SLINK_OFS_TRADE_LEASE + SLINK_TRADE_LEASE_SIZE"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_frame.asm",
  "line": 15,
  "expect": "DEF SLINK_TRADE_FRAME EQU wSlinkMailbox + SLINK_OFS_TRADE_LEASE"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_service.asm",
  "line": 6,
  "expect": "DEF SLINK_TRADE_CONTEXT_SIZE EQU 10"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_service.asm",
  "line": 12,
  "expect": "DEF SLINK_TRADE_QUERY_FRAMES EQU 600"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_service.asm",
  "line": 18,
  "expect": "DEF SLINK_TRADE_APPLY_FRAMES EQU 3600"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_service.asm",
  "line": 20,
  "expect": "SECTION \"SLink Trade Service\", ROMX, BANK[SLINK_SERVICE_BANK]"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_service.asm",
  "line": 22,
  "expect": "SlinkTradeEntry::"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_service.asm",
  "line": 31,
  "expect": "SlinkTradeWriteHeader"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/slink.asm",
  "line": 118,
  "expect": "call SlinkTradeDispatch"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_receptionist.asm",
  "line": 4,
  "expect": "SLINK_TRADE_MAP_BANK"
 },
 {
  "path": "F:/slink-work/wt/polished/server/adapters/gen2_gsc.py",
  "line": 646,
  "expect": "def native_trade_ui(self):"
 },
 {
  "path": "F:/slink-work/wt/polished/server/adapters/polished_codec.py",
  "line": 207,
  "expect": "def key(mon) -> str:"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 66,
  "expect": "| 12 | `_trade_receptionist_text()`"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 138,
  "expect": "### 3.5 `trade_*.asm`"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 66,
  "expect": "Polished dropped the colour field"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 67,
  "expect": "`BackupGSBallFlag` absent"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 147,
  "expect": "A real latent bug the port introduces if missed."
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 111,
  "expect": "`GetSGBLayout`"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 72,
  "expect": "The most fragile thing in the overlay, and it has no static proof"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 172,
  "expect": "`RemoveMonFromParty 03:5d10`"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 173,
  "expect": "`AddTempMonToParty 03:5980`"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 177,
  "expect": "`wOTPartySpecies`"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 158,
  "expect": "must be re-derived, not reused"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 66,
  "expect": "verify_trade_hook"
 }
]
```
