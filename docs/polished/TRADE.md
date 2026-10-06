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

> **SUPERSEDED (2026-10-06):** E1-E3 (a replaced or edited receptionist script in bank $24) are replaced by the two bank-$7E special gates (s11-s15); no map script byte changes. The rows below are the original proposal.

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
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_frame.asm",
  "line": 5,
  "expect": "SLINK_TRADE_OFS_MAGIC"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_frame.asm",
  "line": 6,
  "expect": "SLINK_TRADE_OFS_VERSION"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_frame.asm",
  "line": 8,
  "expect": "SLINK_TRADE_OFS_GENERATION"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_frame.asm",
  "line": 11,
  "expect": "SLINK_TRADE_OFS_SLOT"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_frame.asm",
  "line": 12,
  "expect": "SLINK_TRADE_OFS_AVAILABLE"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_frame.asm",
  "line": 13,
  "expect": "SLINK_TRADE_OFS_MASK"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_frame.asm",
  "line": 14,
  "expect": "SLINK_TRADE_OFS_TOKEN"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_frame.asm",
  "line": 16,
  "expect": "ASSERT SLINK_TRADE_OFS_TOKEN + 4 == SLINK_TRADE_LEASE_SIZE"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_frame.asm",
  "line": 45,
  "expect": "SlinkTradeCheckToken::"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_frame.asm",
  "line": 77,
  "expect": "SlinkTradeClose::"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_dispatch.asm",
  "line": 7,
  "expect": "ld hl, sp + 5"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_dispatch.asm",
  "line": 9,
  "expect": "cp BANK(NextOverworldFrame)"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_dispatch.asm",
  "line": 13,
  "expect": "cp LOW(DelayFrame + 3)"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_dispatch.asm",
  "line": 19,
  "expect": "cp LOW(DelayFrames + 3)"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_dispatch.asm",
  "line": 25,
  "expect": "cp LOW(NextOverworldFrame + 9)"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_service.asm",
  "line": 568,
  "expect": "SlinkTradeCheckIncoming::"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_service.asm",
  "line": 280,
  "expect": "call SlinkTradeValidateSnapshot"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_items.asm",
  "line": 16,
  "expect": "SlinkTradeItemAllowed::"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_items.asm",
  "line": 1,
  "expect": "refuse mail, key items, non-tossable items and placeholder IDs"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/trade_items.asm",
  "line": 33,
  "expect": "184 allowed IDs including NONE"
 },
 {
  "path": "F:/slink-work/wt/polished/lua/gb_trade_lease.lua",
  "line": 16,
  "expect": "OFF_LEASE, L.LEASE_SIZE = 14, 16"
 },
 {
  "path": "F:/slink-work/wt/polished/lua/gb_trade_lease.lua",
  "line": 71,
  "expect": "bytes[9] <= 3"
 },
 {
  "path": "F:/slink-work/wt/polished/tools/build_gen2_companion.py",
  "line": 514,
  "expect": "def verify_trade_hook("
 },
 {
  "path": "F:/slink-work/wt/polished/tools/build_gen2_companion.py",
  "line": 516,
  "expect": "0x64, 0x73b1, 0x689d"
 },
 {
  "path": "F:/slink-work/wt/polished/tools/build_gen2_companion.py",
  "line": 527,
  "expect": "changed outside its two-byte script pointer"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 63956,
  "expect": "00:c51c wPlayerTrademon"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 64080,
  "expect": "00:c54c wPlayerTrademonPersonality"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 64085,
  "expect": "00:c54d wPlayerTrademonForm"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 64095,
  "expect": "00:c550 wPlayerTrademonCaughtData"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 64099,
  "expect": "00:c551 wPlayerTrademonEnd"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 287,
  "expect": "00:0da8 DelayFrame"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 285,
  "expect": "00:0da1 DelayFrames"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 22894,
  "expect": "25:5185 NextOverworldFrame"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/events/npc_trade.asm",
  "line": 161,
  "expect": "ld [wMonType], a"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/link/link.asm",
  "line": 2820,
  "expect": "CheckPartyForMail:"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/link/link.asm",
  "line": 2827,
  "expect": "call ItemIsMail_a"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/link/link.asm",
  "line": 2823,
  "expect": "ld hl, wPartyMon1Item"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/pokemon/move_mon.asm",
  "line": 1,
  "expect": "TryAddMonToParty:"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/pokemon/move_mon.asm",
  "line": 8,
  "expect": "ld de, wOTPartyCount"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/pokemon/move_mon.asm",
  "line": 448,
  "expect": "AddTempMonToParty:"
 }
]
```

---

# 8. Open items settled (2026-10-04)

Coordinator correction carried through: **Polished's `trademon` is 53 bytes, vanilla's 50**, so §2.1's
"+1 byte" framing and the 52-byte arithmetic in §2.1/§2.2 were wrong. The 16-byte lease conclusion is
**withdrawn and re-derived below**.

> **Method note, because it bit me once:** `00:c51c` is a **WRAM** address. Reading the ROM file at
> that offset yields bytes (`3e 32 ea bd df …`) that are *not* the trademon's contents. Every ROM
> byte quoted in this section is a real code address (bank ≠ WRAM, or ROM0 code), and none is quoted
> for a RAM symbol.

## 8.1 The 16-byte lease, byte by byte — SETTLED

`patch/gen2/src/trade_frame.asm:6-14` defines every field, and the last line settles the size:

```
DEF SLINK_TRADE_OFS_MAGIC      EQU 0
DEF SLINK_TRADE_OFS_VERSION    EQU 4
DEF SLINK_TRADE_OFS_COMMAND    EQU 5
DEF SLINK_TRADE_OFS_GENERATION EQU 6
DEF SLINK_TRADE_OFS_ACK        EQU 7
DEF SLINK_TRADE_OFS_RESULT     EQU 8
DEF SLINK_TRADE_OFS_SLOT       EQU 9
DEF SLINK_TRADE_OFS_AVAILABLE  EQU 10
DEF SLINK_TRADE_OFS_MASK       EQU 11
DEF SLINK_TRADE_OFS_TOKEN      EQU 12
ASSERT SLINK_TRADE_OFS_TOKEN + 4 == SLINK_TRADE_LEASE_SIZE
```

| + | field | meaning | written by | read by |
|---|---|---|---|---|
| 0-3 | `MAGIC` | `SLT1` = `$53 $4C $54 $31` (`slink_abi.inc:42-45`) | Lua host | ROM: `SlinkTradeCheckHeader` compares all four, refuses otherwise |
| 4 | `VERSION` | 1 (`slink_abi.inc:46`) | Lua host | ROM: same |
| 5 | `COMMAND` | `QUERY 1 / OFFER 2 / PROMPT 3 / APPLY 5 / DONE 7 / RELEASE 8` (`slink_abi.inc:47-52`) | **both** | **both** |
| 6 | `GENERATION` | visit counter; bumps each entry so a stale reply cannot be taken | Lua host | ROM |
| 7 | `ACK` | host acknowledges the generation | Lua host | ROM |
| 8 | `RESULT` | outcome code | Lua host | ROM |
| 9 | `SLOT` | **own party slot** (0..5) | Lua host | ROM (`SlinkTradeCheckOwnSlot`); Lua validates `bytes[9] <= 3` (`lua/gb_trade_lease.lua:71`) |
| 10 | `AVAILABLE` | item bitmask — items this mon may carry | Lua host | ROM; `SlinkTradeClose` zeroes it |
| 11 | `MASK` | item bitmask — items the mon actually carries | Lua host | ROM; `SlinkTradeClose` zeroes it |
| 12-15 | `TOKEN` | 4-byte per-visit token | Lua host | ROM: `SlinkTradeCheckToken` compares it against the same 4 bytes on the private stack, and refuses a **zero** token (all-zero) |

**Correction to my own previous card:** I claimed `+4` and `+13..+15` were spare. **They are not** —
`TOKEN` is a 4-byte value at `+12..+15`, and the `ASSERT` proves the 16 bytes are exactly full. All
16 bytes are allocated.

**What the lease carries today: protocol metadata and a party slot — no Pokémon data whatsoever.**
No species, no DVs, no OT id, no form, no name.

**Therefore the Polished question answers itself: the lease stays 16 bytes.** A Polished identity
needs 3 DV bytes + Personality + the ExtSpecies/Form byte + a 9-bit species + a 2-byte OT id, and
**none of it belongs in the lease** — it belongs in the staged trademon struct, exactly as vanilla
does it. Growing the lease would add capacity nothing uses and break `SLINK_PUBLIC_SIZE`
(`slink_abi.inc:53`).

**But one field does change meaning.** `+9 SLOT` is a party slot, and `PARTY_LENGTH` is 6 in both
games, so `SLOT` is fine. The `AVAILABLE`/`MASK` item bitmasks are item-domain, and Polished's item
table differs — **UNVERIFIED** how wide those masks are and whether 16 bits suffice.

## 8.2 The trademon struct, corrected to 53 bytes — SETTLED from the sym

`data/polished/polishedcrystal.sym`: `wPlayerTrademon` **`00:c51c`**, `wPlayerTrademonEnd`
**`00:c551`** → **53 bytes**. Every field, from the sym:

| off | address | aliases |
|---|---|---|
| +0 | `00:c51c` | `Species` |
| +1 | `00:c51d` | `SpeciesName` (11) |
| +12 | `00:c528` | `Nickname` (11) |
| +23 | `00:c533` | `SenderName` (11) |
| +34 | `00:c53e` | `OTName` (11) |
| +45 | `00:c549` | `DVs` / `HPAtkDV`, `+46` `DefSpeDV`, `+47` `SatSdfDV` |
| +48 | `00:c54c` | `Personality` / `Shiny` / `Ability` / `Nature` |
| +49 | `00:c54d` | `ExtSpecies` / `Form` / `Gender` / `IsEgg` |
| +50 | `00:c54e` | `ID` (dw) |
| +52 | `00:c550` | `CaughtData` |
| +53 | `00:c551` | `End` |

So Polished folds **two** attribute bytes where vanilla had none: `+48` (shiny/ability/nature) and
`+49` (ext-species/form/gender/is-egg). The macro source lists them as separate labels but they
**alias two addresses** — the sym is authoritative.

**Consequence for the port:** the snapshot preimage is **53 + 11 + 11 = 75 bytes**, not 70. Any
"70 bytes must not change" check carried over from vanilla is wrong by five. This is T4, and it is
now a *number*, not a re-derivation.

## 8.3 The frame-wait stack fingerprint — SETTLED NEGATIVE, needs a live observation

First, a correction about what the card asks. **`verify_trade_hook` says nothing about the
frame-wait call chain.** `tools/build_gen2_companion.py:514-527` asserts only that the 13-byte
object event changes **only** its two-byte script pointer, and that the receptionist stays in its
original map bank. The fingerprint is a **separate runtime check** in
`patch/gen2/src/trade_dispatch.asm:8-29`, reached from `SlinkTradeDispatch`, which inspects the
stack on entry:

```
sp+5  == BANK(NextOverworldFrame)          ; bank byte of the frame-wait caller
sp+12..13 == LOW/HIGH(DelayFrame + 3)      ; return address into DelayFrame
sp+14..15 == LOW/HIGH(DelayFrames + 3)     ; return address into DelayFrames
sp+16..17 == LOW/HIGH(NextOverworldFrame + 9)
```
followed by live guards: `rSVBK & 7 < 2`, `wScriptMode == 0`, `wBattleMode == 0`, and more below.

So it asserts a specific call chain: **NextOverworldFrame → DelayFrames → DelayFrame**, and nothing
else may reach the service.

**Polished, read from the release ROM** (bank ≠ WRAM, so these bytes are real):

| symbol | bank:addr | flat | bytes at the symbol |
|---|---|---|---|
| `DelayFrame` | `00:0da8` | `0x000da8` | `f0 44 e0 d7 af e0 8f 76` |
| `DelayFrames` | `00:0da1` | `0x000da1` | `cd a8 0d d2 0f ac 9f` |
| `NextOverworldFrame` | `25:5185` | `0x095185` | `fa 93 ce a7 20 08 f0 d7` |

`DelayFrames` is literally `call DelayFrame` (`cd a8 0d`) then `ret` (`d2`) — the chain is intact at
*that* link. **But `NextOverworldFrame` does not call `DelayFrames`.** Scanning its first 64 bytes
for `cd a1 0d` returns **nothing**; the bytes at `NextOverworldFrame+9` are
`20 0d af e0 d7 fa 93 ce a7 c8 3d ea` — `jr nc`, `ldh`, `ld a,[…]`, `rst`, no `call`.

**Settled negative: the vanilla fingerprint cannot be re-derived by substitution.** The chain
Polished uses does not run overworld-frame → `DelayFrames` → `DelayFrame`. `HOOKS.md` §2 row 18's
note that the caller path goes through `farjp AnimateTitleCrystal` and a scene jumptable is
consistent with what the bytes show.

**The exact live observation that would settle it:** break in the overlay's Polished build at the
moment the trade service is entered from the frame wait, and read `sp+0 .. sp+24`. Whatever
`sp+5` and the three return addresses are *in that build* is the new fingerprint; the overlay
constants then become `BANK(...)`/`LOW(...)`/`HIGH(...)` over whatever symbols those addresses land
in. No static method can produce this, because the chain is a property of the linked binary, not of
any source file. **Until then T1 is unclosable and no Polished overlay should ship a trade service.**

## 8.4 Does the received mon get Pokedex-marked? — PARTLY SETTLED

`TryAddMonToParty` (`engine/pokemon/move_mon.asm`) selects the destination by `wMonType & $f`:
clear → `wPartyCount`, set → `wOTPartyCount` (`DoNPCTrade` sets `wMonType = 0`, so the **player
party**), bounds-checks `PARTY_LENGTH`, increments the count and copies the temp mon. The
entry points I read (`AddTempMonToParty` at `:448`, `TryAddMonToParty`'s head) contain **no dex
write**.

**UNVERIFIED** whether the dex is marked later in `TryAddMonToParty`'s OT branch, by
`SetSeen`/`LoadTempMon` or by the caller. Settled by grepping the rest of the function for
`SetSeen`/`Pokedex`/`SeenMon`, and by one live trade whose received mon is checked against the dex.

## 8.5 Is a box withdrawal possible mid-trade? — SETTLED

Two independent answers, and they differ:

* **The overlay never offers one.** `SlinkTradeCheckIncoming` (`trade_service.asm:568-571`) reads
  the staged OT party and refuses a mismatch; `SlinkTradeValidateSnapshot` and the party-count
  comparison at `:271-273` (`wPartyCount` before vs after) are the same-instant guards. The
  receptionist path selects from the **party**, via `SelectTradeOrDayCareMon`
  (`PARTYMENUACTION_GIVE_MON`). A box is never a source.
* **The engine's removal is narrower anyway.** `RemoveMonFromPartyOrBox` → **`RemoveMonFromParty`**
  (`engine/pokemon/move_mon.asm:894`), so the box half is gone. **UNVERIFIED** whether that is a
  rename or a behaviour change — `HOOKS.md` §3.5 flags the same open item.

**What freezes the game** during the receptionist flow is not a single flag: the service dispatch
checks `rSVBK & 7 < 2`, `wScriptMode == 0`, `wBattleMode == 0` and (below the fold) `wLinkMode`,
and the overlay's own hold is `wGameLogicPaused`. The frame-wait fingerprint exists precisely because
"we are in the idle overworld's own frame wait" is a **stack shape**, not a flag — which is why
losing it is fatal.

## 8.6 One mail policy for both — PROPOSAL

Two policies exist and they answer different questions:

| | what it asks | scope |
|---|---|---|
| Polished's `CheckPartyForMail` (`engine/link/link.asm:2820`) | does **any** party slot hold mail? Walks `wPartyMon1Item` with stride `PARTYMON_STRUCT_LENGTH`, `call ItemIsMail_a`, sets `hScriptVar` TRUE on the first hit | whole party, one bit |
| overlay's `SlinkTradeItemAllowed` (`trade_items.asm:19-33`) + `SlinkTradeCheckIncoming` | is **this** item ID tradeable at all? 256-entry table, **184 allowed IDs including `$00`**, `$FF` always refused; refuses mail, key items, non-tossable and placeholder IDs | one item |

They are **complementary, not divergent** — `CheckPartyForMail` is a party precondition, and
`SlinkTradeItemAllowed` already refuses mail among other classes. The risk is only that they are
maintained separately and drift.

**Proposed single policy — one source of truth, two call sites:**

1. Keep `SlinkTradeItemAllowed`'s table as the **only** mail truth, and add Polished's condition to
   it rather than shipping a second predicate: the trade is offered only if
   `CheckPartyForMail`-equivalent is clear **and** every candidate item passes the table.
2. Make the entry point **one** `SlinkTradeMailPolicyClear` that runs both, so a future item class
   added to the table cannot be forgotten by the party check.
3. Reuse Polished's own `ItemIsMail_a` rather than the overlay's own mail test, so an item Polished
   newly classifies as mail is refused without an overlay change.
4. Add the invariant as a **build-time `ASSERT`**: the number of mail IDs refused by the table equals
   the count `data/items/mail_items.asm` declares. This is the check that fails loudly if the two
   ever drift, and it is a one-line test.

**UNVERIFIED:** the exact mail-item set in Polished's `data/items/mail_items.asm` and whether
`ItemIsMail_a` and the overlay's table agree today.

## 8.7 Card status after this pass

| card | before | after |
|---|---|---|
| T1 frame-wait fingerprint | UNVERIFIED | **settled negative** — not substitutable; needs a live `sp` read in a linked build |
| T2 `verify_trade_hook` re-derivation | open | open; its `(0x64, 0x73b1, 0x689d)` triple must be re-derived for `24:…` |
| T3 symbol removals | open | open; unchanged (`BackupGSBallFlag`, `GetCaughtGender`, `PLAYER_NAME_LENGTH`) |
| T4 snapshot contract | "re-derive" | **now a number: 75 bytes**, not 70 |
| T5 lease payload | open | **closed** — the lease carries no mon data; 16 bytes stands |
| T6 vblank / SGB | open | open |
| T7 mail policy | open | **now has a proposal** (§8.6) with a build-time `ASSERT` as the drift guard |
| T8 party replace | open | open; window shape unchanged, `TryAddMonToParty` confirmed |

**The one that must move first is unchanged: T1.** A Polished overlay must not ship a trade service
until the stack fingerprint is measured in a linked build.

## 9. Open items settled

### 9.1 Dex marking: the native trade path already marks it — the overlay does not need to

`engine/events/npc_trade.asm:164` — inside `DoNPCTrade`, after
`predef RemoveMonFromParty` at `:163` — calls `predef TryAddMonToParty`. That is the
receival branch: the wanted mon is handed in and the given mon arrives.

`engine/pokemon/move_mon.asm:1278` calls `SetSeenAndCaughtMon` with
`wCurPartySpecies` in `c` (`:1276-1277`) and the form in `b` (`:1274-1275`), guarded by
`.done` at `:1273` when `MON_IS_EGG_F` is set (`:1271-1272`) — so **eggs are not dex-marked**,
which is correct.

**So the NPC-trade path marks the dex natively and the overlay's commit path does not
need to call `SetSeenAndCaughtMon` itself.** Confidence: high for the NPC path.

**The link-trade path — UNVERIFIED.** I traced the NPC path to the call site but did not
walk `engine/link/link.asm`'s trade-completion path to its own `SetSeenAndCaughtMon`
call within the budget. A tree-wide grep shows `SetSeenAndCaughtMon` is called from
`engine/items/item_effects.asm:474`, `engine/pokemon/breeding.asm:330`,
`evolve.asm:496`, `learn.asm:132`, `mon_menu.asm:522`, `move_mon.asm:167,503,880,1278`,
`engine/events/specials.asm:26`, `move_deleter.asm:172`, `shiny_ditto.asm:76` — but
**`engine/link/link.asm` does not appear in that list**. If the link path adds the
received mon by a route that bypasses all of those, the SLink overlay's commit path
**must** call `SetSeenAndCaughtMon` itself. This is the one unresolved piece of item 1
and it is falsifiable by reading `LinkTrade`'s completion branch.

### 9.2 `RemoveMonFromPartyOrBox` does not exist; the removal is a null-write + shift

A tree-wide grep for `RemoveMonFromPartyOrBox` in Polished returns **zero hits**. The
routine that exists is:

```
894: RemoveMonFromParty:
895: ; Done by writing a null entry to the party slot.
896:    ld b, 0
897:    ld a, [wCurPartyMon]
898:    inc a
899:    ld c, a
900:    ld e, 0
901:    farjp SetStorageBoxPointer
```

**Answer: no box-or-party variant exists, and for a party mon the behaviour is
identical in effect** — the predef writes a null entry at `wCurPartyMon` and shifts the
tail down through `SetStorageBoxPointer`, which is exactly the "shift of
species/mons/OTs/nicknames + count decrement" behaviour. It is **implemented, not
inlined**, so an overlay does not have to replicate the shift.

`predef RemoveMonFromParty` is the call site used by `DoNPCTrade` (`:163`), and by
`engine/link/link.asm:1584`, `engine/pokemon/mail.asm:175`,
`engine/events/wonder_trade.asm:203,445` and `shuckle.asm:48`.

**Consequence for the overlay:** a "box withdrawal mid-trade" path (a TRADE.md open item)
must go through the predef or through `SetStorageBoxPointer`, **not** through a
hand-rolled parallel-array shift — the parallel arrays are the storage's business and
the exact shift order is not spelled out at the call site.

### 9.3 The lease bytes are **one byte each**, and they are flags, not an item-class bitmask

`patch/gen2/src/trade_frame.asm:12-13`:

```
DEF SLINK_TRADE_OFS_AVAILABLE EQU 10
DEF SLINK_TRADE_OFS_MASK EQU 11
```

One byte apiece. `SlinkTradeClose::` (`:77`) clears **both** to zero with the same `xor a`
that clears COMMAND, preserving "generation/ack/result/slot/token evidence" per its own
comment at `:76`. They are published by `SlinkTradePublishDone:` (`trade_service.asm:419`,
called from `:202`, `:207`, `:301`).

**What they encode is UNVERIFIED** — I established the width, the offsets, the clear
semantics and the publisher, but **not what value is stored**. They are certainly not a
2-byte class bitmask: a 2-byte bitmask cannot express 8 item classes at 2 bits each
without overflow into 256 items, and a single byte cannot either.

**The item-classification data that does exist** is `data/items/attributes.asm`:
`MACRO item_attribute` with `price, held effect, parameter, pocket, field menu, battle
menu`, and `ItemAttributes` keyed by the complete item id. **The `pocket` field is the
item class** — `BALL` for every ball (`:9` onward). So the Polished class axis is
**pocket**, from `constants/item_constants.asm`.

### 9.4 Polished item space, and a proposed allowed-item rule

Polished's item list is far larger than vanilla's: `constants/item_constants.asm` runs
past the 16 vanilla balls (`PARK_BALL` at `:12`, `POKE_BALL 01` … `DIVE_BALL 11`,
`LUXURY_BALL 12`, `HEAL_BALL 13` at `:35`, and on), and the task's note of **254 ids +
key items** matches a table far past vanilla's `$FF`-terminated set.

**A `trade_items.asm`-style per-id refusal table does not port unchanged.** Vanilla's
table is 16 rows of 16 bytes (`trade_items.asm:36-51`), indexed by the *complete* item
byte with `$ff` always refused (`:34`). Polished needs a longer table, and the refusal
rule should be expressed as a **rule over `pocket`**, not as 256 hand-listed bytes.

Proposed rule, consistent with `SlinkTradeMailPolicyClear` and vanilla's three refusals
(mail, key items, non-tossable):

| refuse | why | source |
|---|---|---|
| any pocket `MAIL` | a mail item carries the story hook; trading it breaks the trade mail policy | vanilla refuses mail (`trade_items.asm:1-3`) |
| any item flagged key | key items are not transferable in either game | vanilla `CANT_TOSS` |
| `MASTER_BALL` | price 0, the one ball vanilla singles out | `attributes.asm:16` price 0 |
| **new in Polished: apricorn balls** (Level/Lure/Moon/Friend/Fast/Heavy/Love) | Polished's Kurt items; the vanilla gate does not know them | `constants/item_constants.asm:21-27` |
| **new in Polished: Wonder Trade / mail-adjacent ids** | must not be transferable | **UNVERIFIED** — I did not enumerate them |

**Allow**: `BALL` pocket except `MASTER_BALL`, and `HELD` pocket items that are neither
mail nor key.

**UNVERIFIED:** I did not read `SlinkTradeMailPolicyClear` itself, and I did not
enumerate Polished's full pocket set — so "which class does not exist / newly exists" is
answered only for apricorn balls, which I read directly at
`constants/item_constants.asm:21-27`.

## Coordinator correction (2026-10-04) to §9.1: dex marking is native on BOTH trade paths

Locating each `SetSeenAndCaughtMon` call by its enclosing routine in `engine/pokemon/move_mon.asm`: `:167` is inside `TryAddMonToParty` (declared at `:1`; used by `DoNPCTrade`, `npc_trade.asm:164`), `:503` is inside `AddTempMonToParty` (`:448`; the LINK trade adds the received mon with `farcall AddTempMonToParty` at `engine/link/link.asm:1622`, after `predef RemoveMonFromParty` at `:1584`), `:880` is `SentPkmnIntoBox` and `:1278` is `GivePoke::` (the §9.1 citation of `:1278` for the NPC path is wrong). So both the NPC-trade and the link-trade path mark the Pokedex natively (eggs excluded by the `MON_IS_EGG_F` guard at `:502`), and the overlay's commit path must NOT call `SetSeenAndCaughtMon` again if it keeps these routines; §9.1's 'unresolved link half' is resolved. `RemoveMonFromPartyOrBox` absence (no hits) and the single-byte AVAILABLE/MASK lease fields were re-checked in source and stand.

```json
CLAIMS: [{"path":"F:/slink-work/cache/polished/src/engine/events/npc_trade.asm","line":90,"expect":"DoNPCTrade:"},{"path":"F:/slink-work/cache/polished/src/engine/events/npc_trade.asm","line":163,"expect":"predef RemoveMonFromParty"},{"path":"F:/slink-work/cache/polished/src/engine/events/npc_trade.asm","line":164,"expect":"predef TryAddMonToParty"},{"path":"F:/slink-work/cache/polished/src/engine/pokemon/move_mon.asm","line":894,"expect":"RemoveMonFromParty:"},{"path":"F:/slink-work/cache/polished/src/engine/pokemon/move_mon.asm","line":895,"expect":"Done by writing a null entry to the party slot."},{"path":"F:/slink-work/cache/polished/src/engine/pokemon/move_mon.asm","line":1272,"expect":"bit MON_IS_EGG_F, a"},{"path":"F:/slink-work/cache/polished/src/engine/pokemon/move_mon.asm","line":1274,"expect":"and SPECIESFORM_MASK"},{"path":"F:/slink-work/cache/polished/src/engine/pokemon/move_mon.asm","line":1276,"expect":"ld a, [wCurPartySpecies]"},{"path":"F:/slink-work/cache/polished/src/engine/pokemon/move_mon.asm","line":1278,"expect":"call SetSeenAndCaughtMon"},{"path":"F:/slink-work/cache/polished/src/engine/items/item_effects.asm","line":474,"expect":"call SetSeenAndCaughtMon"},{"path":"F:/slink-work/cache/polished/src/engine/pokemon/breeding.asm","line":330,"expect":"call SetSeenAndCaughtMon"},{"path":"F:/slink-work/cache/polished/src/engine/pokemon/evolve.asm","line":496,"expect":"call SetSeenAndCaughtMon"},{"path":"F:/slink-work/cache/polished/src/engine/pokemon/learn.asm","line":132,"expect":"call SetSeenAndCaughtMon"},{"path":"F:/slink-work/cache/polished/src/engine/events/specials.asm","line":26,"expect":"call SetSeenAndCaughtMon"},{"path":"F:/slink-work/cache/polished/src/engine/events/shiny_ditto.asm","line":76,"expect":"call SetSeenAndCaughtMon"},{"path":"F:/slink-work/cache/polished/src/engine/link/link.asm","line":1584,"expect":"predef RemoveMonFromParty"},{"path":"F:/slink-work/cache/polished/src/engine/pokemon/mail.asm","line":175,"expect":"predef RemoveMonFromParty"},{"path":"F:/slink-work/cache/polished/src/engine/events/wonder_trade.asm","line":203,"expect":"predef RemoveMonFromParty"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/trade_frame.asm","line":12,"expect":"DEF SLINK_TRADE_OFS_AVAILABLE EQU 10"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/trade_frame.asm","line":13,"expect":"DEF SLINK_TRADE_OFS_MASK EQU 11"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/trade_frame.asm","line":77,"expect":"SlinkTradeClose::"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/trade_frame.asm","line":76,"expect":"End publication without erasing generation/ack/result/slot/token evidence."},{"path":"F:/slink-work/wt/polished/patch/gen2/src/trade_frame.asm","line":80,"expect":"ld [SLINK_TRADE_FRAME + SLINK_TRADE_OFS_AVAILABLE], a"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/trade_frame.asm","line":81,"expect":"ld [SLINK_TRADE_FRAME + SLINK_TRADE_OFS_MASK], a"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/trade_service.asm","line":419,"expect":"SlinkTradePublishDone::"},{"path":"F:/slink-work/wt/polished/patch/gen2/src/trade_items.asm","line":1,"expect":"refuse mail, key items, non-tossable items and placeholder IDs."},{"path":"F:/slink-work/wt/polished/patch/gen2/src/trade_items.asm","line":34,"expect":"Indexed by the complete byte (not item-1); $ff is always refused."},{"path":"F:/slink-work/wt/polished/patch/gen2/src/trade_items.asm","line":36,"expect":"db 1,1,1,1,1,1,0,0,1,1,1,1,1,1,1,1 ; $00"},{"path":"F:/slink-work/cache/polished/src/data/items/attributes.asm","line":1,"expect":"MACRO item_attribute"},{"path":"F:/slink-work/cache/polished/src/data/items/attributes.asm","line":2,"expect":"price, held effect, parameter, pocket, field menu, battle menu"},{"path":"F:/slink-work/cache/polished/src/data/items/attributes.asm","line":8,"expect":"ItemAttributes:"},{"path":"F:/slink-work/cache/polished/src/data/items/attributes.asm","line":11,"expect":"item_attribute 200, 0, 0, BALL, ITEMMENU_PARTY, ITEMMENU_CLOSE"},{"path":"F:/slink-work/cache/polished/src/data/items/attributes.asm","line":17,"expect":"item_attribute 0, 0, 0, BALL, ITEMMENU_PARTY, ITEMMENU_CLOSE"},{"path":"F:/slink-work/cache/polished/src/constants/item_constants.asm","line":12,"expect":"DEF PARK_BALL EQU NO_ITEM"},{"path":"F:/slink-work/cache/polished/src/constants/item_constants.asm","line":14,"expect":"const POKE_BALL    ; 01"},{"path":"F:/slink-work/cache/polished/src/constants/item_constants.asm","line":34,"expect":"const LUXURY_BALL  ; 12"},{"path":"F:/slink-work/cache/polished/src/constants/item_constants.asm","line":35,"expect":"const HEAL_BALL    ; 13"},{"path":"F:/slink-work/cache/polished/src/constants/item_constants.asm","line":21,"expect":"const LEVEL_BALL   ; 06"},{"path":"F:/slink-work/cache/polished/src/constants/item_constants.asm","line":27,"expect":"const LOVE_BALL    ; 0c"}]
```


---

## Coordinator note: live stack measurement (2026-10-04)

`docs/polished/LIVE_RESULTS.md` Stage 4 (read-only, 300 samples at `SlinkDelayFrameBridge` entry, idle Route 29
overworld on the overlay ROM): the stack is `0DAB (DelayFrame+3)`, `25:51C2` (return from `call z, DelayFrame`,
`cc a8 0d` at `25:51BF`), pushed registers (sp+4 and sp+8..9 vary: not fingerprintable), `25:516B (HandleMap+0x15)`,
`25:50E2 (OverworldLoop.loop+9)`, `0014 (FarCall+4)`. So the overworld chain is OverworldLoop -> HandleMap ->
NextOverworldFrame -> **DelayFrame directly**; section 8.3 only searched for calls to `DelayFrames` and missed this
call to `DelayFrame`. Not yet measured: the same stack at the Pokemon Center receptionist / trade entry (that screen
was not cheaply reachable from the synthetic save), which is what the trade hook design actually needs.


### Live stack measurement at the receptionist (coordinator, 2026-10-04, LIVE_RESULTS.md Run 2 Stage B)

Pokemon Center 2F is map group 20 #1; receptionist at (5,2), talk from (5,3). The warp used the engine's Script_warp bytes
plus one SYNTH event flag (EVENT_GAVE_MYSTERY_EGG_TO_ELM, `wEventFlags+4` $00 -> $02). Inside the link wait
(`Special_WaitForLinkedFriend`, frames 1039-1552, 300 samples, SP $C0DC, bank $0A) the stack is
`DelayFrame+3`, `WaitForLinkedFriend.not_done+0xf`, `_ReturnFarCall`, FarCall-saved registers (carry caller bank $25),
`25:62B5 ScriptEvents.loop+9`, `25:515F HandleMap+9`, `25:50E2 OverworldLoop.loop+9`, `FarCall+4`; only sp+2 varies. The
YES/NO prompt and talk-start stacks share the same bank-$25 tail; text printing gives 167 distinct stacks over 249 samples
(not fingerprintable). The idle-overworld constant (`$516B` at sp+12) does not hold inside the script; inside it the
stable tail is `$62B5/$515F/$50E2`.


---

## Coordinator note (2026-10-05): the snapshot preimage is 70 bytes, NOT 75

Withdraws the "53 + 11 + 11 = 75" statement in section 8.2 and the earlier coordinator note. The snapshot is built from PARTY structs
(`patch/gen2/src/trade_snapshot.asm:19` copies `PARTYMON_STRUCT_LENGTH`; the asm asserts it is 48 at `:4`), and Polished's party struct is
48 bytes (`wPartyMon1 01:dcd6` .. `wPartyMon1End 01:dd06`), so the preimage is 48 + 11 + 11 = 70 bytes; the 53-byte trademon is the STAGED struct
(`wPlayerTrademon 00:c51c`..`00:c551`), a different thing. What does differ is which bytes Polished legitimately rewrites on a trade (personality
word +20, form word +21): T4 stays open as a re-derivation of that mutation list, not a size change. Verified by the coordinator against the sym.

---

## 10. Design note (peer round 2, 2026-10-04): what the Polished dispatcher must actually check

**Nothing here was measured live in this pass** — the session had no shell, so no build, no
pytest and no EmuHawk run was possible. Everything below is derived from committed source and
from `data/polished/polished_slink.sym` (the linked overlay symbols), and every claim names its
source. The live confirmation is still owed; §10.6 is the exact probe that would settle it.

### 10.1 The dispatcher is not the service's own wait gate — it is the responder's pickup gate

The card asked for a probe "at the point where `callasm SlinkTradeEntry` would run … sample
`sp+0..31` on the frame waits the service would park in". Those are the wrong frames.

`SlinkTradeDispatch` is called from inside `SlinkService`
(`patch/gen2/src/slink.asm:117-119`), and `SlinkService` runs on **every** patched `DelayFrame`
(`patch/polished/src/slink.asm:29-48` replaces DelayFrame's 7-byte lead-in with
`call SlinkDelayFrameBridge`, which arms the wait, pushes, bankswitches and calls the service).
Its own header says so: `patch/gen2/src/trade_dispatch.asm:1-2` — "Only pick up a partner prompt
at the idle overworld's own frame wait" — and `trade_service.asm:135-136` — "Dispatcher has
already checked safe overworld context".

So the two frame populations are opposites:

| population | what it is | what the dispatcher must do |
|---|---|---|
| `SlinkTradeWaitFrame`'s own `call DelayFrame` (`trade_service.asm:463-480`) | the service parking for a host reply | **refuse** — it is inside the overlay's own bank |
| the ordinary idle-overworld frame wait | a player standing in the overworld with a partner `PROMPT` sitting in the lease | **accept**, and open the native prompt (`SlinkTradePromptEntry`, `trade_service.asm:135`) |

Run 2 Stage B already measured the accept population (item 1, 300 samples on the overlay ROM,
idle Pokemon Center 2F): `SP $C0DE`, `hROMBank $25`, "byte-for-byte run 1's Route 29 chain".
So **T1's live measurement is largely already in hand**; what is missing is §10.6's confirmation
that the *dispatch entry* offsets derived below match those bytes, on a build that actually
contains the dispatcher.

### 10.2 The vanilla `sp+5` check is `hROMBank`, not a return address

Vanilla bridge (`patch/gen2/src/slink.asm:32-41`): `ld a,1 / ld [wVBlankOccurred],a`, then
`push af`, `push bc`, `push hl`, `ldh a,[hROMBank] / push af`, then `call SlinkService`. Then
`SlinkService` does `call SlinkTradeDispatch` (`:118`).

Unwinding that from `SlinkTradeDispatch`'s first instruction:

| sp+ | frame | value in the idle overworld |
|---|---|---|
| 0-1 | return into `SlinkService` | — |
| 2-3 | return into the bridge | — |
| 4-5 | saved `AF` from `ldh a,[hROMBank] / push af` | **`[sp+5]` = `hROMBank` = `$25`** |
| 6-7 | saved HL | varies |
| 8-9 | saved BC | varies |
| 10-11 | saved `AF` from `ld a,1 … push af` | — |
| 12-13 | bridge-entry `sp+0` | `$0DAB` = `DelayFrame + 3` |
| 14-15 | bridge-entry `sp+2` | `$51C2` |
| 16-17 | bridge-entry `sp+4` | `$FE00`/`$FE20` — a **register**, not an address |
| 24-25 | bridge-entry `sp+12` | `$516B` = `HandleMap + $15` |

This matches `trade_dispatch.asm:5-6`'s own comment ("service return, bridge return, saved bank
AF, HL, BC, AF, patched DelayFrame return, DelayFrames return, NextOverworldFrame return" —
two-byte items, so the three return addresses are at sp+12/14/16) and makes `cp BANK(NextOver-
worldFrame)` at `:9` a **bank** test, which is what `[sp+5]` actually holds. Worth stating
plainly because §8.3 and HOOKS.md row 18 both describe `sp+5` as "the bank byte of the frame-wait
caller", which is right in effect and wrong about the byte's provenance.

**The Polished bridge pushes the identical 8 bytes in the identical order**
(`patch/polished/src/slink.asm:41-48`: `push af`, `push bc`, `push hl`, `ldh a,[hROMBank] /
push af`), and `SlinkService` is a single `call` away from where `call SlinkTradeDispatch` will
go. **So the offset arithmetic carries over unchanged**: dispatch-entry `sp+12+k` == bridge-entry
`sp+k`. The only bridge difference is `xor a` (`slink.asm:39`) where vanilla has `ld a,1`
(`gen2/slink.asm:32`), i.e. `sp+10` is `$00` in Polished, `$01` in vanilla. It carries no weight.

### 10.3 The Polished fingerprint, with the constants that express it

`sp+12..17` cannot be used as one window: Polished has no `DelayFrames` link in this chain
(§8.3, settled negative), and `sp+16..23` are **pushed registers**, two of which Stage B and
Stage 4 both record as varying (`sp+4`, `sp+8..9` at bridge-entry depth). The third link has to be
taken from further up, where the measurement is stable.

Derived from the pinned source and the linked overlay sym
(`data/polished/polished_slink.sym:22904-22907,22902,22890`, `F:/slink-work/cache/polished/src/
engine/overworld/events.asm:157-160`):

```asm
; engine/overworld/events.asm:157-160
.gfx_done
	ldh a, [hDelayFrameLY]
	and a
	call z, DelayFrame
```

`call z` is 3 bytes, so the return address pushed into DelayFrame is `NextOverworldFrame.gfx_done
+ 3 + 3` = **+6**. The sym puts `NextOverworldFrame.gfx_done` at `25:51bc`; `25:51bc + 6 =
25:51C2` — exactly the word Stage B measured at bridge-entry `sp+2`. The chain therefore closes
symbolically, not by pasting constants.

Proposed dispatcher fingerprint (all five values are `LOW`/`HIGH` of an exported Polished label —
Polished assembles with `-E`, `patch/polished/src/slink.asm:23-24`):

| sp+ | expected | symbol form | measured at bridge entry |
|---|---|---|---|
| 5 | `$25` | `BANK(NextOverworldFrame)` | hROMBank `$25` (Stage B #1) |
| 12-13 | `$0DAB` | `LOW/HIGH(DelayFrame + 3)` | sp+0..1 (tautology: every call through the patched lead-in) |
| 14-15 | `$51C2` | `LOW/HIGH(NextOverworldFrame.gfx_done + 6)` | sp+2..3 ✓ |
| 24-25 | `$516B` | `LOW/HIGH(HandleMap + $15)` (`HandleMap` = `25:5156`) | sp+12..13 ✓ |
| 26-27 | `$50E2` | `LOW/HIGH(OverworldLoop.loop + 9)` (`25:50d9`) | sp+14..15 ✓ |

**Refusal cases, from the same Stage B data:**

* **Script frames** (`$62B5` `ScriptEvents.loop+9` at bridge-entry `sp+12`) → dispatch `sp+24 =
  $62B5` ≠ `$516B`. **Refused.** This is the check that keeps the service out of every ordinary
  NPC script, and it is the one vanilla does not need (vanilla's `sp+16..17` already fails there).
* **The service's own wait**: `SlinkTradeWaitFrame` calls DelayFrame from bank `$7E`, so
  `hROMBank = $7E` at `sp+5`, and `sp+14..15` returns into the overlay, not `25:51C2`.
  **Refused twice over.**
* **The idle overworld is the only accept case measured.** Stage B #1 is the known-positive
  control, identical on Route 29 and in the Pokemon Center — the fingerprint is map-independent
  in both games, which is what makes it safe to key on.

### 10.4 The unit test must mask, not pin

The card asks for "a unit test replaying the exact stack bytes (positive and negative: a stack
differing by one byte refused)". **As literally stated that test is wrong**, and it would fail on
the game's own noise: Stage B records `sp+4` and `sp+8..9` varying between runs and between the
poke and warp fixtures, and run 1 vs run 2 saw `sp+8..9` = `3e00` vs `4446`. A test that pins all
32 bytes pins a register.

The window is: **assert the six pinned byte positions (§10.3) match; assert one flipped byte at
any of those positions is refused; assert a flipped byte at any other position changes nothing.**
The second clause is the negative the card wants; the third is the one that would otherwise have
shipped a gate that fails on a different overworld frame.

Positive vector — dispatch-entry `sp+12..31` is Stage B #1 verbatim, with 12 bytes of
overlay/service frame prepended (of which only `sp+5` is pinned):

```
sp+0..11   ?? ?? ?? ?? ?? 25 ?? ?? ?? ?? ?? 00     ; service ret, bridge ret, hROMBank, HL, BC, AF
sp+12..13  ab 0d                                    ; DelayFrame + 3
sp+14..15  c2 51                                    ; NextOverworldFrame.gfx_done + 6
sp+16..23  00 fe 86 d6 44 46 22 d1                  ; registers (masked out)
sp+24..25  6b 51                                    ; HandleMap + $15
sp+26..27  e2 50                                    ; OverworldLoop.loop + 9
sp+28..29  14 00                                    ; FarCall + 4
sp+30..31  01 8a
```

### 10.5 Two blockers S2 hits before it writes a line of asm

> **RESOLVED (2026-10-06):** bank $24 has zero free bytes (s11) and the script growth in (b) is no longer needed (special gates); (a) the verifier span is now a derived six-byte table span. Original text follows.

**(a) `verify_overlay` will reject the E2 source edit.** `tools/build_polished_companion.py:159-166`
enumerates the *only* spans a changed byte may fall in: the DelayFrame lead-in, the ROM0 bridge,
the bank-`$7E` service, the header checksums, the ROM0 phone bridge, and the five bank-`$24`
phone-hook operands. An edit to `maps/PokeCenter2F.asm` changes **other** bank-`$24` bytes (the
script stream shifts) and hits `raise RuntimeError(f"unexpected change at …")` at `:171`. The
span class has to be added deliberately, with the script's own byte range computed from the two
syms — widening the gate with a derived range, not loosening it.

**(b) E2 is not size-neutral, and the size delta is knowable from the source.**
`macros/scripts/events.asm:97-100` gives `callasm` = `db` + `dba` = **4 bytes**; `:103-106` gives
`special` = `db` + `db` = **2 bytes**. There is no 4-byte script command other than `callasm`, so
there is no same-size substitution available: branching into `SlinkTradeEntry` costs **+2 bytes in
bank `$24`'s script stream**. TRADE.md E2 ("branch after `:101`") and E1/E3 (a wholesale
replacement script in a new bank-`$24` section) therefore *both* consume bank-`$24` slack, and
HOOKS.md §10 states only that "No ROMX free space outside bank `$7E` is used" — which describes
overlay placement, not the map bank's headroom. **UNVERIFIED: how many bytes bank `$24` has free.**
That number decides E1 vs E2 and is the first thing to measure.

### 10.6 The probe that closes T1 (for whoever has a shell)

Same shape as Run 2 Stage B: an `event.on_bus_exec` on `SlinkDelayFrameBridge` (ROM0 `$0070`),
sampling `sp+0..31` plus `hROMBank` on the frames where `wMapStatus = 2` and `wScriptRunning = 0`
(the accept population), then the same sample **from inside the receptionist script** after the
YES prompt (the refuse population). The derived table in §10.3 predicts accept = `$25 / $0DAB /
$51C2 / $516B / $50E2` at `sp+5/12/14/24/26`, and refuse (script) = `$25 / $0DAB / <not $51C2> /
$62B5 / $50E2`. A second run with `POL_STAGES` reaching one frame **inside** the service's own
`SlinkTradeWaitFrame` is the third population and must show `hROMBank = $7E`.

### 10.7 One more name change the port must absorb

`trade_dispatch.asm:49-51` and `trade_service.asm:466-468` compare `cp VBLANK_NORMAL`.
Polished's `hVBlank` is a **0-7 mode selector**, not a flag: `engine/link/link.asm:2276-2278`
(`xor a / ldh [hVBlank],a` on the link-success path), `home/decompress.asm:17` (`cp 4`),
`engine/menus/credits.asm:67` (`ld a,5`), `gfx/copy_tilemap_at_once.asm:60-61`
(`ld a, 1 << 7 | 7 ; execute actual VBlank7`). The port is `cp 0`, and unlike vanilla — where
`hVBlank` has a single value and the check is `and a` in disguise — **the Polished check is
load-bearing**. (UNVERIFIED: vanilla's `VBLANK_NORMAL` value; no pokecrystal checkout was
reachable in this session.)

### 10.8 Do not derive struct sizes from `macros/ram.asm` by counting labels

The macro and the linked sym disagree on `party_struct`, and the sym is right.
`macros/ram.asm:42-55` declares `EggCycles db`, `Happiness db` (`:31-32`) and
`CaughtData db`, `CaughtTime db`, `CaughtBall db` (`:34-36`) as **five separate bytes**, which
counts to 51. The linked sym shows them collapsing onto **three** addresses
(`data/polished/polished_slink.sym:67567-67572`): `wPartyMon1EggCycles` = `wPartyMon1Happiness` =
`01:dcf0`, `wPartyMon1PokerusStatus` = `01:dcf1`, `wPartyMon1CaughtBall` =
`wPartyMon1CaughtData` = `wPartyMon1CaughtTime` = `01:dcf2`. So
`wPartyMon1 01:dcd6` .. `wPartyMon1End 01:dd06` = **0x30 = 48 bytes**, and the coordinator's
70-byte preimage (48 + 11 + 11) stands.

The aliasing is the *same* shape the trademon uses for its two attribute bytes
(`macros/ram.asm:262-269`, `Personality`/`Gender`/`IsEgg`/`ExtSpecies`/`Form`), and it is exactly
what produced §2.1's wrong "52" arithmetic: the macro lists seven labels where the layout spends
two bytes. **Measured sizes, for the record** (sym is authoritative in both rows):

| struct | macro label count | sym span | size |
|---|---|---|---|
| `trademon` | 53 bytes (no aliasing) | `wPlayerTrademon 00:c51c` .. `wPlayerTrademonEnd 00:c551` | **53** |
| `party_struct` | 51 bytes (three aliases) | `wPartyMon1 01:dcd6` .. `wPartyMon1End 01:dd06` | **48** |
| `wPartyMonOTs` stride | — | `wPartyMon1OT 01:ddf6` .. `wPartyMon2OT 01:de01` | **11** |
| `wPartyMonNicknames` stride | — | `wPartyMon1Nickname 01:de38` .. `wPartyMon2Nickname 01:de43` | **11** |

`server/adapters/polished_codec.py:39-42,255-258` already encodes exactly these numbers
(`PARTY_SIZE = 48`, `TRADEMON_SIZE = 53`, `NAME_SIZE = NICKNAME_SIZE = 11`) and keeps the two
structs distinct — `decode_party_blob` is the 70-byte wire blob (`:239-242`) and
`trademon_from_party_blob` converts it to the 53-byte staged struct (`:348-353`). Round 1's codec
is correct as it stands; this note only records why the macro must not be used to re-derive it.

The mutation set T4 still has to re-derive is confirmed in the same table:
`wPartyMon1Personality 01:dcea` = struct offset **20** and `wPartyMon1Form 01:dceb` = offset
**21**, i.e. exactly the two words the coordinator named. Nothing else in `wPartyMon1`..`End` is
engine-written during a hand-over — but **UNVERIFIED**: which of the two the trade path rewrites
(the engine regenerates the personality word from DVs on load, and the overlay's snapshot window
closes between the snapshot and the commit, so a rewrite landing in that window is the exact bug
class T4 exists to catch).
## 10.9 Live measurement of the DISPATCH-ENTRY window (S1, 2026-10-04): §10.3 CONFIRMED

**This closes §10.6's first half.** Run 2 Stage B sampled at `SlinkDelayFrameBridge` ENTRY;
`SlinkTradeDispatch` runs three frames further in, so the window the dispatcher reads had never
been observed. Driver: `tools/polished_live/trade_probe.py` (new). Lane
`F:/slink-work/lanes/pol-trade2/`, overlay `34942315BB3E62189A56DABBCB9CEF6DD3E9A9F5` (the CURRENT
`data/polished/overlay_provenance.json`), fixture `polished_overlay_warp.SaveRAM`
sha256 `75c7a5dc…`, EmuHawk PID 258200, killed and checked gone. Evidence
`lanes/pol-trade2/explore_B/result.txt` sha256 `f92cb78ebf91d7aa728bc51ee3195a4fc7e2485c1e0305d6f44cb848fadd3ec6`,
`stacks.json` sha256 `4d55371779278605b8ccaaa26419ffec625345d36f2c656358c3f5c50c48ac66`,
`RESULT: PASS explore-B (0 checks failed) frame 1667`.

**The frame depth is arithmetic, not a paste.** At bridge entry `sp = B`, `$0DAB` is at `B+0`; the
bridge pushes `af`(bank) `hl` `bc` `af`(xor a) — 8 bytes — then `call SlinkService` costs 2 more
(`B-10`); `SlinkService` runs straight-line today, and `call SlinkTradeDispatch` costs 2 more.
**`dispatch sp == bridge sp - 12`**, i.e. `dispatch sp+12+k == bridge sp+k`, exactly §10.2's claim.

Measured at the dispatch entry, from the dominant stack of each phase (hex):

| phase | samples | sp+5 | sp+12-13 | sp+14-15 | sp+24-25 | sp+26-27 | verdict |
|---|---|---|---|---|---|---|---|
| `overworld` | 300 (297 same stack) | `25` | `ab 0d` | `c2 51` | `6b 51` | `e2 50` | **ACCEPT** |
| `overworld_after` | 61 (1 distinct) | `25` | `ab 0d` | `c2 51` | `6b 51` | `e2 50` | **ACCEPT** |
| `script` | 197 (129 distinct) | `24` | `ab 0d` | *varies* | *varies, 11 values* | *varies* | **REFUSE** on sp+5 |
| `wait_friend` | 300 (298 same) | `0A` | `ab 0d` | `5f 4d` | `b5 62` | `5f 51` | **REFUSE** on sp+5 |
| `after_wait` | 52 | `24` | `ab 0d` | *varies* | *varies* | *varies* | **REFUSE** on sp+5 |
| `yesno` | 21 | `25` | `ab 0d` | *varies* | *varies* | *varies* | REFUSE on sp+14 |

And every pinned constant re-derives from `data/polished/polished_slink.sym`, so the match is
symbolic rather than coincidental:

| predicted | derived from the sym | measured |
|---|---|---|
| sp+12-13 `DelayFrame + 3` | `00:0da8` + 3 | `ab 0d` ✓ |
| sp+14-15 `NextOverworldFrame.gfx_done + 6` | `25:51bc` + 6 | `c2 51` ✓ |
| sp+24-25 `HandleMap + $15` | `25:5156` + $15 | `6b 51` ✓ |
| sp+26-27 `OverworldLoop.loop + 9` | `25:50d9` + 9 | `e2 50` ✓ |
| sp+5 `hROMBank` | `BANK(NextOverworldFrame)` = `$25` | `25` ✓ |

### Three corrections to §10.3, from the same data

1. **§10.3's script-frame constant `$62B5` is real but NOT universal.** `ScriptEvents.loop + 9`
   re-derives to `$62B5` (`25:62ac` + 9) and it is exactly what the `wait_friend` phase carries at
   sp+24-25. But the `script` phase's dominant stack has `60` there and sp+24 **varies across 11
   values** in 197 samples. `$62B5` is the *LinkTradeFarCall tail*, not "the" script fingerprint.
   The refusal still holds — it is `sp+5` (`$24` ≠ `$25`) that rejects those frames — but a
   dispatcher may not cite `$62B5` as the script discriminator.
2. **`sp+5` is the load-bearing check, and it is stronger than §10.3 says.** Script frames run in
   bank `$24`, the link wait in `$0A`, and only the idle overworld is in `$25`. Checking sp+5
   first rejects three of the five measured phases on its own.
3. **NEW HAZARD, not in §10.3: the `talk` phase can false-accept.** Its 6 samples (2 distinct) have
   `sp+5 = $25` and, in the dominant 3, `sp+24-25 = $6B $51` — the accept values. That is the frame
   on which the player's A press *starts* the receptionist script, before `wScriptRunning` is set.
   A dispatcher that accepts on the stack alone would open the native prompt on the same frame the
   player begins a talk. The port MUST keep `trade_dispatch.asm:34-54`'s engine-state refusals
   (`wScriptMode`, `wBattleMode`, `wLinkMode`, `wGameLogicPaused`, `hInMenu`, `wMapStatus`,
   `wPlayerStepFlags`, `wMapEventStatus`) — the stack fingerprint is a *pre-filter*, never the
   whole gate. §10.7's `cp 0` for Polished's `hVBlank` mode selector matters for the same reason.

### Noise positions confirmed unpinnable

`sp+4` and `sp+8..9` (bridge-entry depth) vary between runs exactly as §10.4 says: the `overworld`
phase alone shows 9 distinct bytes across the noise positions. `trade_probe.py` reports them and
counts them as deliberately unpinned; the unit test must assert the six pinned positions and a
flipped byte at any of them, never all 32.

**NOT measured here:** the third population §10.6 asks for — a frame inside the service's own
`SlinkTradeWaitFrame`, which needs `hROMBank = $7E`. It is unreachable until S2 lands the service;
until then it is UNVERIFIED, not disproved.

## 11. Trade slice status (coordinator, 2026-10-05)

* **Slice 1 DONE (inert):** `SlinkTradeCheckHeader/Token/Close` frame + the 256-entry item-allow table are in bank `$7E`
  at fixed `$4200`/`$4280` (a floating section made rgblink pack largest-first and shove the version field). Table is
  generated from `FIRST_MAIL` (`$F5`) by `tools/gen_polished_trade_items.py`; policy = refuse mail only (Polished's one
  native held-item refusal, `ItemIsMail_a`), not vanilla's key/non-tossable set: those ids mean other items here and a mon
  cannot hold a key item. Overlay v3 sha1 `1a9094eb...`; nothing calls these routines yet (superseded by slice 2a below).
* **MEASURED: bank `$24` has ZERO free bytes** (release ROM, last symbol `SilphCo3FElevatorText` `24:7ff5`, no padding).
  Closes 10.5(b): E2 cannot grow the script stream by 2. The receptionist hook must be a **same-size in-place
  substitution** inside `LinkReceptionistScript_Trade`/`..._DoTradeOrBattle` (`maps/PokeCenter2F.asm`), e.g. fold
  `writetext Text_PleaseWait` (3 B) + an adjacent 1-byte command into one 4-byte `callasm SlinkTradeEntry`, then re-prove
  the script still reaches `warpcheck`. E1 (pointer to a new script in `$7E`) is impossible: an object-event script
  pointer is 16-bit in the map bank.
* **Next (not started):** pick the substitution site; `verify_overlay` span class for it (computed from the two syms,
  10.5(a)); then dispatch (10.3 fingerprint) and service/commit/snapshot.

## 12. Entry design + ordered port cards (coordinator, 2026-10-06; Polished peer cx-b8624834, headless Codex cx-8419505a, each claim re-derived from source/sym)

**Entry:** repoint two `SpecialsPointers` entries (table 03:402A; entry 2 `Special_WaitForLinkedFriend` 0A:4D03 at ROM 0xC030, entry 3 `Special_CheckLinkTimeout` 0A:4D78 at 0xC033, 6 bytes `0A 03 4D 0A 78 4D`) to bank-$7E gates. Trade vs battle (they share `DoTradeOrBattle`, PokeCenter2F.asm:90-102,201-202) is `wChosenCableClubRoom` (01:D26B) == LINK_TRADECENTER-1 == 1, which survives `Special_TryQuickSave`; NOT `wLinkMode`/`wPlayerLinkAction`. Return TRUE via `hScriptVar` (00:FF85). After the service, set `hScriptBank` (FFEB) = $2D and `hScriptPos` (FFEC/FFED) = $7595 = the bare `endtext` at `DayOfWeekSiblingsHousePokedexScript.End` (ROM 0xB7595 = C0). Allowed by `verify_overlay` since slice 2a as a derived six-byte table span (it was not allowed before; see s11 and s15). Skipping the real wait leaves serial/timeout state untouched; the redirect bypasses `PerformLinkChecks`/room entry, which is fine only if no path falls through.

**The idle-overworld responder still needs an adapted `trade_dispatch`** (vanilla chain DelayFrame -> bridge -> SlinkService -> SlinkTradeDispatch -> SlinkTradePromptEntry); the special gate replaces only the proposer entry. Polished fingerprint: NextOverworldFrame (`25:50D9`/`HandleMap 25:5156`/`.gfx_done 25:51BC`) per s10.3; `hVBlank` is a 0-8 mode, require 0.

**Port differences found (source-verified):** `$53` is the name terminator (not `$50`); `$5F`=<MALE> so the vanilla `$60` glyph threshold is wrong; no `wPartySpecies`/`wOTPartySpecies` (validate record/form-aware, extended species); OT stride 11 = 8 name + 3 extra (keep all 11 in the 70-byte preimage); name buffers are 11 bytes so there is NO PLAYER_NAME_LENGTH overrun; commit: stage `wTempMonOT`/`wTempMonNickname` (`AddTempMonToParty` reads them), drop vanilla `.ShiftMail` (`RemoveMonFromParty` -> `ShiftPartySlotToEnd` already moves mail), evolution mode is `EVOLVE_TRADE` (3) not TRUE, three DV bytes and form/egg for the animation, caught-data = 0 (no `GetCaughtGender`/`BackupGSBallFlag`), `GetCGBLayout` with `CGB_PLAIN`, `farcall AddTempMonToParty`, `ClearTileMap`, `GetSRAMBank`. `polished_trade.lua` has NO lease binder yet and `entry.lua` constructs the Polished client without a trade component.

**Cards (each <=3 files, one acceptance command, a first falsifier):** 1 special entry/return no-mutation probe (slice 2a gates + stub entry + live probe `trade_port_probe.py --case special-entry`); 2 held service + snapshot with Polished guards, commit disabled; 3 native commit helper (staging, mail, EVOLVE_TRADE, cold reload); 4 adapted dispatcher + both entries (`--case entry-matrix`); 5 production lease binder (`polished_trade.lua`/`entry.lua`/profile generator); 6 cold-reload duo receipt on one frozen cut. **Biggest unproven assumption:** a long-lived service entered through the repointed special survives native menus/animation/save/map restore and returns with a valid script continuation and balanced machine state: card 1's probe records SP, banks, script cursor, `hVBlank` on entry and exit.

## 13. Live special-entry probe spec (headless Codex cx-13eb0c35, coordinator-verified 2026-10-06)

Setup (SYNTH, disclosed, as in `tools/polished_live/explore.lua` WHICH=B): fixture `F:/slink-work/lanes/g2int-live/pol/fixture/polished_overlay_warp.SaveRAM` (sha256 `75c7a5dc...`, boots Route 29 `24:3`); set `wEventFlags+4 |= $02` (EVENT_GAVE_MYSTERY_EGG_TO_ELM) and engine-warp to `20:1` (5,3); the trade receptionist is the object at (5,2) (battle one at (9,2)); face Up, pulse A. The clean ROM has `special` bytes `0F 02` at `24:7619` (Wait) and `0F 03` at `24:762A` (Timeout); the redirect target `2D:7595` is script DATA (ROM byte C0), observe it through `GetScriptByte`/`RunScriptCommand`/`Script_endtext`, never a bus-exec hook.
Positive oracle: Wait gate entry once (bank $7E, `wChosenCableClubRoom`=1, cursor `24:761B`) -> returns once with `hScriptVar`=1 -> quick-save returns `hScriptVar`=1 with the room still 1 -> Timeout gate entry once (cursor `24:762C`) -> stub once -> cursor redirected to `2D:7595` -> `Script_endtext` hit once (cursor `2D:7596`) -> `wScriptRunning`=0, `wScriptStackSize`=0, `hVBlank`=0, `wLinkMode`=0, then Down moves the player. Zero original Wait/Timeout/`PerformLinkChecks`/room-entry hits. Note `_ReturnFarCall` pops a bank byte, so SP after return is NOT entry+2: witness the return address at SP_entry+2 and the interpreter continuation at bank $25. `L.hook_at` calls the callback with `false` on a bank mismatch: every recorder must start `if not matched then return end`. `PLAYEREVENT_MAPSCRIPT` is $FF not 1.
Controls (each from a fresh save copy, sequential): battle receptionist (room 2) must reach the ORIGINAL `0A:4D03` and finish within ~900 frames (native wait is finite, ~513 frames measured), no stub/timeout gate; save-decline (B on the must-save prompt) -> `.DidNotSave` `24:7689` -> `WaitForOtherPlayerToExit`, zero TryQuickSave/Timeout/stub entries; clean v3.2.3 ROM with the same driver: original wait runs and the positive oracle REJECTS for missing gate events (a boot failure is not a control). A differing save player ID can show NoYesBox at quick-save: do not assume every A is YES. Mutation checks scope to the gate interval (the scenario saves and `FixPlayerEVsAndStats` rewrites stats). A passing stub probe proves only the bounded entry/return path, not the long-lived service.

## 14. Incoming-trade predicate for the held service (Polished peer cx-26862a8a, coordinator-verified 2026-10-06)

Shape: B = P(48) || O(11) || N(11) = 70 bytes, snapshot ALL of it with no mutation mask. OT text is only O[0:8]; O[8:11] is metadata (Hyper Training mask `$FC` in O[8]); preserve all three byte-for-byte (the 'apply EVs' bit is a temporary register flag, not stored).
Rules (zero-based offsets, big-endian HP/stats): **species** s = P[0] + ((P[21] & $20) << 3), accept 1..$FE or $101..$123 (NOT `NUM_POKEMON+1`; `$FF`=EGG display sentinel and `$100` are holes); **egg** = P[21] & $40, still validate the underlying species, never substitute `$FF` in the party record (EGG only in the 53-byte display trademon); **form** f = P[21] & $1F in {0,1} or an exact (species, form&$3F) pair in the cosmetic (ROM 0x3E0C, 56 pairs) or variant (0x3E7C, 46 pairs) tables (conservative policy, not native); **level** 1..100 (native `ValidateOTTrademon`, link.asm:1206; not MIN_LEVEL 2); **moves** each 0 or 1..255 ($FF is STRUGGLE, not a terminator); **item** P[1] < $F5 (`SlinkTradeAllowedItems`); **DVs** P[17:20], optional nature guard (P[20]&$1F) < 25; **names** find the first `$53` within 11 (nickname) / 8 (OT text), refuse if none, bytes before it must be >= `$5F` (broad literal policy; the keyboard-only alphabet K is [7F-B9][BC-BF][C1-C8]{D2,D3,D8,D9,DA,DC,DD}[E0-EA]{EC}); **HP/status**: no native recompute on append, so only an optional sanity (0 <= HP <= maxHP, maxHP > 0), and full consistency is a card-3 decision. **Snapshot timing:** capture AFTER `FixPlayerEVsAndStats` (PokeCenter2F.asm:83) and the quick-save; allowed own-record drift between capture and commit is the EMPTY set (happiness reset and evolution are post-commit effects). **Defects to fix, not copy:** `lua/gen2/polished_trade.lua:91` copies the underlying species for an egg and `:98` copies P[28] into caught-data, but native staging uses `$FF` for eggs and caught-data 0; an egg with the extension bit set makes `GetPokemonName` index `$1FF` (source-level risk, not reproduced): normalise the DISPLAY species only, in card 3. Native lookups (`GetBaseData`, `GetEvosAttacksPointer`, names) are unbounded, so validate before any native getter runs.

**Slice 2a LANDED (2026-10-06, commit ddf91c0ed, merged bf4b863d3):** the two special gates are in the overlay. Overlay v4 sha1 `97628616e36b2bd0c241699aa00e5abcfe0d45db` (UPS 1030 B, 954 bytes in 21 runs; built with `--version 0.1.0`, byte-identical version field). `SlinkTradeWaitGate` 7e:4400 / `SlinkTradeTimeoutGate` 7e:4410 / stub `SlinkTradeEntry` 7e:4480 (end 7e:4484); the table entries at ROM 0xC030..0xC035 changed `0a 03 4d 0a 78 4d` -> `7e 00 44 7e 10 44` and nothing else in the table moved (the builder derives the 6-byte span and the old bytes from the clean sym; a link-time ASSERT pins `DayOfWeekSiblingsHousePokedexScript.End` = 2D:7595, byte C0). Coordinator disassembled both gates from the patched ROM (room compare with 1, `hScriptVar`=1, bank $2D, FFEC=$95, FFED=$75, native branches `rst FarCall` + jump flag to 0A:4D03 / 0A:4D78). Evidence is a mini SM83 rig on the real bytes plus the writes-card boot smoke; **the live entry/return probe has since run (s15)**; the stub makes every trade request end the script silently until the real service lands.

## 15. LIVE: the special entry/return contract holds for the stub (2026-10-06, probe commit 7b05eede4, merged b77c1acc6)
`python tools/polished_live/trade_port_probe.py --case special-entry|battle|decline|clean` on overlay v4 (sha1 `97628616...`), fixture `75c7a5dc...`, SYNTH setup disclosed (event flag + engine warp to 20:1 (5,3); everything else native input; no cable partner, no SLink client). Coordinator re-ran `special-entry` (EmuHawk pid 43468, result.txt sha256 `27eefc19...`, 57 events) and `clean` (pid 58192): both PASS. Positive trace: wait gate once (bank $7E, room 1, cursor 24:761B) -> returns `hScriptVar`=1, sp unchanged -> TryQuickSave returns var 1, room still 1 -> timeout gate once (24:762C) -> stub once -> hScriptBank:Pos = 2D:7595 -> `GetScriptByte` read at 2D:7595, `Script_endtext` (25:7326) once -> `wScriptRunning`=0, `wScriptStackSize`=0, `hVBlank`=0, `wLinkMode`=0 -> Down moves (5,3) -> (5,4). Zero hits of the original Wait/Timeout, `PerformLinkChecks`, `WaitForOtherPlayerToExit` or the room entry. Controls: battle receptionist (room 2) reaches the ORIGINAL 0a:4D03 for 513 frames and never the timeout gate/stub; save-decline reads `.DidNotSave` (24:7689) once then `WaitForOtherPlayerToExit` once, zero TryQuickSave/timeout-gate/stub; the clean v3.2.3 ROM runs the original wait for 513 frames and the oracle REJECTS it.
Measured correction to s13: at gate entry sp+0..1 is `_ReturnFarCall` (00:2698), sp+2 is the bank byte, so the oracle checks the return sp equals the entry sp and the interpreter continuation in bank $25, not 'SP_entry+2'. **Not proven:** the long-lived service, menus/animation/commit, the NoYesBox quick-save branch (the quick-save never prompted: same player id), a real cable/second client, one fixture and one map position per case. The central assumption of s12 (a special entered this way returns with a valid script continuation and balanced machine state) now holds for the stub path.

## 16. Host-facing half and the ordered cards (Polished peer cx-e0566dcb, coordinator-verified 2026-10-06)
**Lease** (reuse `lua/gb_trade_lease.lua`, do NOT write a second FSM): 16 bytes at `wSlinkMailbox`+14: 0..3 `SLT1`, 4 version, 5 command (QUERY1 / OFFER2 ROM->host, PROMPT3 / APPLY5 host->ROM, DONE7 ROM->host, RELEASE8 host->ROM), 6 generation (publisher increments, written LAST), 7 ack (receiver echoes generation LAST; there is no ACK command and no role byte), 8 result (host answers OFFER 0 accept/1 reject; ROM result 0 success/1 decline/2 UNCERTAIN), 9 slot, 10 available, 11 eligibility mask (party slots, NOT held-item permission), 12..15 a nonzero 4-byte LOCAL visit token (distinct from the server transaction token). Flow: A receptionist -> QUERY -> server mask -> native pick/confirm -> OFFER -> server proposes to B -> A waits for APPLY; B's idle dispatcher consumes PROMPT -> native prompt/save/snapshot -> DONE yes/no -> host RELEASE; server `apply_prepare` to both -> `apply_ready` -> both hosts stage the incoming 70-byte blob into OT slot 0 and publish APPLY with the SAME visit token and generation+1 -> ROM ACKs first, validates, commits -> DONE with result/slot/token, ACK last -> host RELEASEs and reports the received key; result 2 holds with no release and needs after-reset evidence. Native timeouts QUERY 600 / OFFER 600 / APPLY 3600 frames, decline wait 90; a committed/uncertain wait has no B/timeout escape. Server events (state.py ~:564-575,994-1034,1218-1346) and docs/protocol.md assertions 39-43 are unchanged; the key is `DDDDDD:OOOO:SSS:TT` (underlying 9-bit species, never the effective BaseData id).
**Binder deltas (Polished):** no `wOTPartySpecies` span; the 70-byte blob = 48 + OT 11 (8 text + 3 metadata) + nickname 11; the host stages ONLY OT slot 0 (`wOTPartyMon1` D28B / OT D3AB / nick D3ED); OT slot 1 (D2BB / D3B6 / D3F8) belongs to the ROM snapshot and a one-byte host write there must be rejected by the permit; the 53-byte trademon is a native animation structure, never host-written; `PT.encode` is not native animation staging (egg species, caught-data); hooks and ram records come from the built sym, never vanilla constants; `tools/gen_polished_profile.py` emits no `overlay.trade` today and `compose()` returning spans is not a binder; all-or-none family, a stub family must not advertise a production trade.
**Cards (<=3 authored files, one acceptance command):** C1 held service + snapshot (trade_service.asm, trade_snapshot.asm, test_polished_trade_service.py; 2a, the snapshot and validity predicate, is in flight as pol-svc); C2 profile schema (gen_polished_profile.py, profile.json, test_polished_trade_profile.py); C3 binder (polished_trade.lua, test_polished_trade_binder.py); C4 composition/wiring (entry.lua, test_polished_trade_composition.py; fold the slink.asm wiring into C7); C5 commit helper (trade_commit.asm, test_polished_trade_commit.py); C6 dispatcher/responder (trade_dispatch.asm, test_polished_trade_dispatch.py); C7 build integration; C8 two-instance smoke harness (tools/polished_live/duo.py, a lua driver, test_polished_duo_driver.py); C9 trade duo scenario. Parallel pairs: C1+C2, C3+C5, C6+C8; C4 then C7 serial. Production trade stays disabled until both entry paths and the commit exist.
**Duo:** no Polished entry exists in `e2e_duo.GAMES` and `duo_gen2_main.lua` is vanilla-bound; do not relabel `gen2_new`. `tools/polished_live/harness.py` already starts a real server and writes the rom contract but contracts player A only: it needs per-side staging for A and B. First honest duo claim = both production hellos admitted with correct identities + complete party/20-box censuses + reconnect, zero trade writes. Only then a trade: normal receptionist input on A, real idle pickup on B, both native commits and saves, cold reload of both private saves, exchanged keys on both. Two independently played trade-ready fixtures do not exist yet (the SYNTH warp fixture is one identity).

## 17. The second identity, the held service split and the duo plan (2026-10-06; peers cx-c323a2ff, cx-b9531965; coordinator-verified)
**Second identity (SYNTH under O-33, owner 2026-09-24, docs/gen2/REVIEW_RECORD.md:44):** the duo fixture (`polished_overlay_warp.SaveRAM`, 32790 B, sha256 `75c7a5dc...`) holds trainer `Aaaaaaa`, ID `$D1C2` (53698), five mons all with held item 0, empty boxes; main and backup checksums are both `$13E4`. A pure derivation `derive_identity(A, name, id) -> (B, disclosure)` replaces, in BOTH the main and the backup copy, the player ID (flat 0x2008 / 0x1208, big-endian), the first 8 name bytes at 0x200B / 0x120B (7 chars + `$53`), every occupied party mon's OT ID (0x286C+48i / 0x1A6C+48i) and the first 8 bytes of its OT field (0x2986+11i / 0x1B86+11i; the final 3 EXTRA bytes preserved), then re-sums `[2008,2B83)` / `[1208,1D83)` into the little-endian checksum at 0x2D0D / 0x1F0D. Never call `seal_save` on a real fixture (it randomises the game data). Preconditions: valid checksums, empty boxes. It is a disclosed SYNTH derivative, not independently played; a held item for item coverage and the Mystery Egg event for the receptionist are separate disclosed setup. Played alternative: a driver from New Game to a starter exists only as the 3044-frame intro to the bedroom; no starter/errand driver exists (estimate 30k-90k frames to a trade location, UNVERIFIED).
**Held service C1 (proposer only, commit disabled):** context is on the CPU STACK (10 bytes), not mailbox scratch; mailbox bytes are reserved. APPLY validated but commit disabled publishes DONE result 1 ('not performed'), never result 0, then a bounded RELEASE wait; an OFFER reject, B, a timeout or a binding failure closes the lease with no DONE/RELEASE; the party menu is `SelectTradeOrDayCareMon` with B = PARTYMENUACTION_GIVE_MON; no automatic WaitForOtherPlayerToExit; the entry at 7e:4480 has 128 bytes before the snapshot at $4500, so it becomes a `jp` to a service section placed after the final map. The staged incoming mon is SCATTERED (record D28B, OT names D3AB, nicknames D3ED, sender D276; OT slot 1 D2BB/D3B6/D3F8 is the snapshot), so the validator needs a staged wrapper (sent to pol-svc). Cards: C1a FSM source + tests, C1b build wiring (serial with the builder), C1c a serverless Lua host responder + probe (QUERY answered with a test token, OFFER rejected, native endtext).
**Order now:** pol-svc (snapshot + scatter-aware validator) -> C1a/C1c -> C2 profile schema -> C3 binder -> C5 commit -> C6 dispatcher -> a second-identity duo (derive_identity card, then the per-side fixture admission in duo.py) -> trade-reload duo.

## 18. The responder dispatcher: guards, fingerprint and the measurement plan (Polished peer cx-1791219d, coordinator-verified 2026-10-06)
**Placement:** the call does not exist yet (`slink.asm` has no `SlinkTradeDispatch` call and no `SLINK_TRADE_ENABLED`): one conditional `call SlinkTradeDispatch` goes in `SlinkService` after the frame-sample accounting and BEFORE the `jp SlinkSfxService`, never a call+ret rewrite of that jump (it changes depth). Dispatcher stack at entry: +0..1 return to the service, +2..3 to the bridge, +4..5 the bridge's saved-bank AF, +6..7 HL, +8..9 BC, +10..11 AF, +12 the caller chain. `SlinkServiceEnd` is `7e:404c` and the panel runs to `4101`; the other fixed entries are the frame `4200`, items `4280`, gates `4400`, stub `4480`, and `4500`/`4600` for pol-svc: allocate the dispatcher in a verified non-overlapping interval with an explicit end symbol.
**Guards (vanilla -> Polished):** KEEP saved bank at +5 == `BANK(NextOverworldFrame)` ($25, the saved A, not the current bank which is $7E); KEEP +12/13 == `DelayFrame+3`; CHANGE +14/15 to `NextOverworldFrame.gfx_done`+6 (`51C2`, the Polished idle path has no `DelayFrames` link); DROP the vanilla `NextOverworldFrame+9` position (register noise in Polished) and REPLACE with +24/25 == `HandleMap`+15 (`516B`) and +26/27 == `OverworldLoop.loop`+9 (`50E2`). That is NINE pinned bytes; every other stack byte is masked (the 'must mask, not pin' rule). KEEP `rSVBK&7 < 2`, `wScriptMode == 0`, `wBattleMode == 0`, `wLinkMode == 0`, `wGameLogicPaused == 0`, `hInMenu == 0`, `wMapStatus == MAPSTATUS_HANDLE`, no `PLAYERSTEP_CONTINUE`, `wMapEventStatus == MAPEVENTS_ON`, `SlinkTradeCheckHeader`, command == PROMPT, generation != ACK; CHANGE `hVBlank` to exactly 0 (a 0..8 mode selector, no `VBLANK_NORMAL`); preserve DE (`push de` / `call SlinkTradePromptEntry` / `pop de`), no persistent mutation on any refusal.
**Evidence limits:** the earlier s10.9 numbers were reconstructed from BRIDGE-entry samples (`trade_probe.py`), not measured at a real dispatcher entry; the talk-transition frames (the A press before `wScriptRunning` is set) matched parts of the idle fingerprint, so the first falsifier is a forbidden talk frame that satisfies every proposed check. The measurement card hooks BOTH the bridge and the dispatcher entry on a frozen wired ROM and classifies every sample: positives = idle Route 29 and Pokecenter safe tiles; negatives = NPC text, the talk transition, START/party/bag/Pokegear and their transitions, yes/no, wild battle (walk into grass), walking/mid-step, map transitions, and (once C1 exists) the service's own wait loops; zero samples is OPEN/FAIL. M1 inert checker without a PROMPT (accept tested offline by the pure predicate); M2 a lease-only test host PROMPT at an eligible idle frame. The existing mini-SM83 `Machine` has no real SP/stack/flag model (no `ld hl,sp+e`, push/pop, carry, BIT): the dispatcher oracle needs a separate reusable machine, a red control per guard (each guard removed with only its own field invalid) and an adversarial nested-DelayFrame reentry control.
**Dependency:** the proposer-only C1 does NOT implement `SlinkTradePromptEntry`; the responder service (vanilla trade_service.asm :135-209: OpenText, confirm, the full save, snapshot, DONE, RELEASE, APPLY hold) is its own card, and production pickup stays off until it and the binder exist. Cards: D1 dispatcher source + guard model + `tests/unit/polished_sm83.py`; D2 wiring (`slink.asm`, builder, companion tests; serial); D3 the paired-entry measurement probe; D1 and D3 parallel.


**Card 2a LANDED (2026-10-06): the 70-byte snapshot and the incoming predicates (INERT, nothing calls them).** `patch/polished/src/trade_snapshot.asm` (fixed 7e:4500, end `SlinkTradeSnapshotEnd` 7e:45ab, 171 B): `SlinkTradeSnapshot` 7e:4500 / `SlinkTradeValidateSnapshot` 7e:4537 / `SlinkTradeReleaseSnapshot` 7e:4571 (a bare `ret`), a port of the vanilla module minus the species-list/EGG cross-check; A = own slot, carry = refused (count not 1..6, slot >= count, or any of the 70 bytes differs), BC/DE/HL preserved, writes ONLY OT slot 1 (wOTPartyMon2 d2bb, wOTPartyMonOTs+11 d3b6, wOTPartyMonNicknames+11 d3f8) and never slot 0. `patch/polished/src/trade_validate.asm` (fixed 7e:4600, end `SlinkTradeValidateEnd` 7e:4696, 150 B). Native OT staging is SCATTERED (record wOTPartyMon1 d28b, OT wOTPartyMonOTs d3ab, nickname wOTPartyMonNicknames d3ed, sender name wOTPlayerName d276), so the predicate is split: `SlinkTradeValidateRecord` 7e:4600 (HL = 48-byte record: species 1..$FE / $101..$123, level 1..100, item via `SlinkTradeItemAllowed`, nature < 25), `SlinkTradeValidateText` 7e:4636 (HL = buffer, B = 8 or 11: first "@" $53 within B, every byte before it >= $5F, O[8:11] never checked), `SlinkTradeValidateIncomingStaged` 7e:464b (no arguments: record, OT text 8, nickname 11 and the sender name 11, each at its native address, read-only) and the contiguous model form `SlinkTradeValidateIncoming` 7e:4676 (HL = P(48)||O(11)||N(11); the staged wrapper does NOT use it). All carry = refused, BC/DE/HL preserved. Evidence: `tests/unit/test_polished_trade_snapshot.py` runs the REAL assembled bytes on an SM83 interpreter (70 flip cases on each side, bounds, 47-row boundary table, 3000-blob fuzz of the contiguous form AND of the staged wrapper on scattered WRAM images with garbage in the gaps and a valid/invalid OT slot 1, against a Python twin, 21 byte-patch mutants). Overlay v5 sha1 `26ed4a41c5901ae6dcae49ec0929a034d1f40219`, UPS 1355 B, 1275 bytes in 23 runs.

**Cards D1+D2 LANDED (2026-10-06, branch claude/pol-disp): the responder DISPATCHER, INERT.** `patch/polished/src/trade_dispatch.asm`: `SlinkTradeDispatch` 7e:4700 (end of code `SlinkTradeDispatchCodeEnd` 7e:477a, 122 B, slot $4700-$477F) and the bare-`ret` stub `SlinkTradePromptEntry` 7e:4780 (`SlinkTradeDispatchEnd` 7e:4781; the responder service REPLACES it; it never touches the lease, so no ACK and production trade stays off). `SlinkService` makes one plain `call SlinkTradeDispatch` after the frame-sample store and before `jp SlinkSfxService` (nothing pushed before it; the service moved the panel/sound/version +3 B). Guards in order: nine pinned stack bytes (+5 saved bank = BANK(NextOverworldFrame) $25; +12/13 DelayFrame+3 0DAB; +14/15 NextOverworldFrame.gfx_done+6 51C2; +24/25 HandleMap+$15 516B; +26/27 OverworldLoop.loop+9 50E2; every other stack byte is masked and a read-hook test proves only those nine are read), rSVBK&7<2, wScriptMode/wBattleMode/wLinkMode/wGameLogicPaused/hInMenu/hVBlank == 0, wMapStatus == MAPSTATUS_HANDLE, PLAYERSTEP_CONTINUE clear, wMapEventStatus == MAPEVENTS_ON, SlinkTradeCheckHeader ok, command == PROMPT, generation != ACK; then `push de / call SlinkTradePromptEntry / pop de / ret`. Stack budget: early refuse 2 B (the return slot), lease refuse 4 B, accept 6 B (push de + call). Evidence: `tests/unit/test_polished_trade_dispatch.py` runs the BUILT bytes on the real SM83 interpreter: the routine equals an independent byte model from the symbols, 22 mutants (one conditional return NOPed per guard, incl. each of the nine stack bytes) each accept only their own violation, noise/engine/lease/re-entry vectors. NOT measured live: the real dispatcher-entry stack populations (a separate probe card); the live smoke here is the writes boot run only. Overlay v6 sha1 `aecedbb2c6d1fa4c2fceaf67a70f21801e723833`, UPS 1485 B, 1401 bytes in 25 runs.
