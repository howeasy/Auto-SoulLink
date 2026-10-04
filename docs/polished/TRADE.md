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
