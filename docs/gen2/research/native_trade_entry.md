> **Coordinator correction (Codex `cx-51f03e2d`, 2026-09-21, verified on both HEAD clones):** (1) Pokegold routine map: `SetBitsForLinkTradeRequest` G `link.asm:2132`, `WaitForLinkedFriend :2158`, `CheckLinkTimeout_Receptionist :2238`, `CheckBothSelectedSameRoom :2379`, `TradeCenter :2416`, `TimeCapsule :2405`, `TradeAnimationPlayer2` G `trade_animation.asm:67`; Gold's `PokeCenter2F.asm:59-88` runs the cable flow with no Mobile branch. (2) Time Capsule DOES convert held items (`link.asm:821-825`, `:1102-1113`, mapping `:1180` via `TimeCapsule_CatchRateItems`; pokegold `:760-765`, `:1006-1017`, `:1084`): the 'no item conversion' claim is wrong; `CheckTimeCapsuleCompatibility` (`:2114-2192`) is a Gen 1 compatibility gate and must NOT be reused as a Gen 2 item validator (it would reject Johto species/moves). (3) Crystal Mobile (`maps/MobileTradeRoom.asm:20-26`) calls `Function1037c2`/`Function101231`, so 'same LinkTrade path' is NOT established. (4) The patch count ('two' vs 'three' sites) is a design result; the takeover must also cover the room payload exchange and post-trade serial sync (`link.asm:258-279, 2025-2044`; pokegold `:256-277, 1855-1874`). Owner O-14: Time Capsule is out of scope regardless.

# Native trade entry point for Gen 2 (ticket 15)

Card: research, wayfinder ticket 15. Read-only; no code/patch changes. Pins below.

## Pins

- **C** = pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651 (`pokecrystal@7a7881d`).
- **G** = pokegold@656583c939d30f920a316177311a502dd222b57c (`pokegold@656583c`).
- Gen 2's `LinkTrade` write chain (staging is not a commit; `AddTempmonToParty` → `EvolvePokemon` →
  `SaveAfterLinkTrade`, and what `SaveAfterLinkTrade` does/does not save) was already resolved by
  ticket 13 and is cited here, not re-derived: `docs/gen2/wayfinder/issues/13-link-trade-routine.md`
  and its source receipt `docs/gen2/research/codex_checkpoint_and_linktrade.md` §B (worktree paths,
  not re-pinned to a sha since they are local docs).
- Ticket 14 (mailbox address in always-mapped RAM) is currently negative/open. Per the assignment,
  this document assumes **a mailbox exists in always-mapped RAM** and designs against that
  assumption; it does not pick or verify an address.
- Gen 1 precedent cited from the worktree at its current tree state (not sha-pinned, per the task's
  own citation convention for worktree paths): `patch/gen1/README.md`, `patch/gen1/src/*.asm`,
  `lua/gen1/trade_overlay.lua`, `docs/gen1_requirements.md`, `docs/purergb/PLAN.md`.

## Cable Club flow

Gen 2's Cable Club is the Pokémon Center's 2F link room, reached from four receptionist NPCs and
one Colosseum-adjacent room set, not a single script like Gen 1's:

- **Trade Center**: `LinkReceptionistScript_Trade`, C `maps/PokeCenter2F.asm:69-104`; G
  `maps/PokeCenter2F.asm:59-88`.
- **Colosseum (battle)**: `LinkReceptionistScript_Battle`, C `maps/PokeCenter2F.asm:171-199`; G
  `:129-141` region.
- **Time Capsule**: `LinkReceptionistScript_TimeCapsule`, C `maps/PokeCenter2F.asm:298-333`; G
  `:189-217` region.
- Crystal adds a Mobile Adapter branch inline in the same trade/battle scripts (`special
  CheckMobileAdapterStatusSpecial` / `AskMobileOrCable` / `Mobile_SelectThreeMons`, C
  `maps/PokeCenter2F.asm:76-83,178-186,229-259`); G has no mobile branch at all (no
  `CheckMobileAdapterStatusSpecial` call in `pokegold@656583c maps/PokeCenter2F.asm`).

Each receptionist script's cable path is the same shape (C line refs; G refs are the matching
scene at its own line numbers noted above):

1. `checkevent`/`checkflag` gate (mystery egg given, Bill met, `ENGINE_TIME_CAPSULE`), else
   `Script_*Closed` (C `:53,290`).
2. `opentext` / `writetext` intro, `yesorno` — decline falls to `.Cancel` → `closetext`/`end` (C
   `:71-73,171-173,300-302`).
3. Trade Center only: `special CheckMobileAdapterStatusSpecial` / mobile branch (C `:76-82`); Time
   Capsule only: `special CheckTimeCapsuleCompatibility` first, refusing on
   introduced-in-Gen-2/new-move/holding-mail before any wait (C `:304-311`, body at `:2114-2160`).
4. `special SetBitsFor{LinkTrade,BattleRequest,TimeCapsuleRequest}Request` (C `engine/link/link.asm
   :2277,2289`) — sets `wLinkMode`/request bits read by the other side's link scan.
5. `special WaitForLinkedFriend` (C `link.asm:2303-2369`) — the first real serial spin loop; drives
   `rSB`/`rSC`, times out to `.FriendNotReady` → `special WaitForOtherPlayerToExit`.
6. Save prompt: `yesorno` then `special TryQuickSave` (C `link.asm:2536-2551`, calling
   `engine/menus/save.asm` `Link_SaveGame`-shaped save, **not** `SaveAfterLinkTrade`). Declining
   either aborts to `.DidNotSave`/`.AbortLink`.
7. `special CheckLinkTimeout_Receptionist` (C `link.asm:2383-...`) — second serial wait/timeout.
8. `readmem wOtherPlayerLinkMode` — Time-Capsule-vs-Gen-2 branch (`.LinkedToFirstGen` /
   `special FailedLinkToPast`).
9. `special CheckBothSelectedSameRoom` (C `link.asm:2553-...`) — refuses Trade Center vs Colosseum
   vs Time Capsule mismatches, `.IncompatibleRooms` → `special CloseLink`.
10. Success: `writetext Text_PleaseComeIn`, `waitbutton`, gender-check scall, `warpcheck` into
    `maps/TradeCenter.asm` / `maps/Colosseum.asm` / `maps/TimeCapsule.asm`.

The destination room's only job is `special TradeCenter` / `special TimeCapsule` (both C/G
`maps/TradeCenter.asm:38`, `maps/TimeCapsule.asm:38`), which calls `LinkCommunications` (C
`engine/link/link.asm:1`) → branches to `Gen2ToGen1LinkComms` (Time Capsule, C `:39`) or
`Gen2ToGen2LinkComms` (Trade Center/Colosseum, C `:205`). This is the third and largest serial
region: menu UI, per-player selection (`LinkTrade`, C `:1702`, the actual trade-confirmation menu
— see below), and party-data exchange via `Link_PrepPartyData_Gen1`/`_Gen2` (C `:706,877`).

Crystal's Mobile-adapter path (`maps/MobileTradeRoom*.asm`) reuses the same
`LinkReceptionistScript_Trade`/`_Battle` scripts' `.Mobile` branches and a separate
`BattleTradeMobile_WalkIn`/mobile room warp (C `maps/PokeCenter2F.asm:150-169,232-260`); it does not
introduce a different local-write routine — it is a different physical-link transport reaching the
same `LinkCommunications`/`LinkTrade` code, per §Out of scope below.

## Takeover points

### Where a companion patch would intercept (mapped to Gen 1's two windows)

Gen 1's native takeover (`patch/gen1/src/trade_receptionist.asm`) replaces the entire
`TX_SCRIPT_CABLE_CLUB_RECEPTIONIST` dispatch with `SlinkReceptionist` (one hook, one dispatch site,
`docs/gen1_requirements.md` T-1 row: "one text-script opcode... dispatched in the HOME bank...
covers them all"), then runs its own foreground menu/party-picker entirely off native menu code
before ever reaching the real serial routines, publishing a lease (`SLT1`) through the borrowed
`wSerialPartyMonsPatchList`/enemy-slot-1 union that the host (Lua) answers within bounded frame
windows: QUERY 30 frames, OFFER 180 frames (`docs/purergb/PLAN.md:421`, `lua/gen1/trade_overlay.lua
:66-107`).

Gen 2 has no single dispatch opcode analogous to `TX_SCRIPT_CABLE_CLUB_RECEPTIONIST` — the four
receptionist scripts are separate `scripting.asm` bytecode bodies per room (`LinkReceptionistScript_
Trade/_Battle/_TimeCapsule`, `maps/PokeCenter2F.asm` above), each already calling into shared
`special` (native ASM callback) routines. That shared-`special`-call shape is itself the Gen-2-native
equivalent of "one hook covers many call sites": a companion patch that replaces the bodies of
`SetBitsForLinkTradeRequest`/`WaitForLinkedFriend`/`CheckLinkTimeout_Receptionist`/
`CheckBothSelectedSameRoom` (all `special`s, i.e. plain ASM routines already reachable from ROM0,
C `link.asm:2277,2303,2383,2553`) intercepts all four scripts without touching `maps/PokeCenter2F.asm`
itself, mirroring Gen 1's "one hook, many callers" property at the ASM-routine layer instead of the
text-script layer.

**Takeover point 1 — "partner offer arrives" (Gen 1's receptionist query window).** The Gen-2-shaped
analogue is the pair `SetBitsForLinkTradeRequest` (publish local mode/request) →
`WaitForLinkedFriend` (C `link.asm:2303-2369`, spins on `rSB`/`rSC` and internal/external clock
role, times out to `.FriendNotReady`). This is the first serial wait a takeover must intercept
before it drives the physical handshake — Crystal's own VC-hook comment at this exact site
(`vc_hook`-style note, C `link.asm:2339-2347`, cited already in `codex_checkpoint_and_linktrade.md`
§B) is source evidence that faking connection status here is one plausible interception boundary,
not proof it alone suffices. A companion patch would replace `WaitForLinkedFriend`'s body with a
QUERY-shaped lease publish/poll (offer availability + mask, mirroring Gen 1's `answer_query`,
`lua/gen1/trade_overlay.lua:66-79`) bounded to a QUERY-class frame window, then fall through to
`.FriendNotReady` on timeout exactly as vanilla does on a real absent partner.

**Takeover point 2 — "both confirmed" (Gen 1's 180-frame OFFER window / selection).** Gen 2's
confirmation is not at the receptionist at all — it is inside `LinkTrade` itself (C `link.asm
:1702-1789`): a native 2D menu (`ScrollingMenuJoypad`) offering the partner's named mon vs. Cancel,
built from `wCurTradePartyMon`/`wCurOTTradePartyMon` and each side's `wOtherPlayerLinkMode`/
`wPlayerLinkAction` exchanged via `farcall PlaceWaitingTextAndSyncAndExchangeNybble` (C `:1770,1789`
— this farcall is the actual "confirm/cancel" serial exchange, the Gen-2 analogue of Gen 1's `SLT1`
OFFER handshake). A cancel on either side is symmetric: local B-press sets `wPlayerLinkAction=1` and
displays "trade was canceled" (C `:1772-1783`); the partner having canceled is detected after the
sync by `ld a,[wOtherPlayerLinkMode] / dec a / jr nz, .do_trade` (C `:1789-1799`) taking the same
canceled-text path. A takeover must replace this whole selection+sync block (not just
`WaitForLinkedFriend`) because it is where the actual pair-of-slot-indices and go/no-go decision is
made and exchanged; it maps directly to Gen 1's `PROMPT`→`APPLY` lease steps
(`lua/gen1/trade_overlay.lua:107-140`, `MAGIC`/`VERSION`/`PROMPT=3`/`APPLY=5`).

**Both animations.** Selected by `hSerialConnectionStatus == USING_EXTERNAL_CLOCK` at `predef
TradeAnimation` vs `predef TradeAnimationPlayer2` (C `link.asm:1969-1976`; entry points
`engine/movie/trade_animation.asm:21` and `:72`; G `link.asm:1802-1806`). Both predefs run
symmetrically as the two players' local views of one shared transfer moment; a companion takeover
must still drive one of the two paths on each side (mirroring Gen 1's own `TradeAnimation`/
`TradeAnimationPlayer2` split noted in the same `link.asm` clock-role branch), not skip animation
entirely, since `.done_animation` (C `:1978`) is also where the post-animation species/struct
restore happens (see ABI below) — the animation and the data restore are not separable.

**Local commit (already resolved by ticket 13, re-cited).** `.done_animation` restores the
opponent's slot, sets `wCurPartySpecies`, copies the 48-byte `PARTYMON_STRUCT_LENGTH` record from
opponent-party staging into `wTempMonSpecies` (C `:1978-1994`), then `predef AddTempmonToParty`
(actual writer, C/G `engine/pokemon/move_mon.asm:396-444`) → `callfar EvolvePokemon` (C `:1998`) →
mew/celebi anti-cheat checkbyte loop (C `:2001-2038`) → `farcall SaveAfterLinkTrade` (C `:2044`).
G mirrors at `:1808,1824,1828,1874`.

### Why the takeover needs three sites, not one

Gen 1's single receptionist hook works because Gen 1's Cable Club puts availability query, offer,
confirm and both animations all under one script's control flow. Gen 2 spreads the same logical
steps across (a) the receptionist script's `special` calls (`SetBitsForLinkTradeRequest`,
`WaitForLinkedFriend`, `CheckLinkTimeout_Receptionist`, `CheckBothSelectedSameRoom` — all four
receptionist scripts share these, C `link.asm:2277-2599`), and (b) `LinkTrade` itself, called only
after `LinkCommunications`/`Gen2ToGen2LinkComms` in the destination room (C `maps/TradeCenter.asm
:38`, `link.asm:1,205,1702`). A companion patch therefore needs at minimum: one hook covering the
four receptionist `special`s (Takeover point 1), and one hook replacing `LinkTrade`'s selection/sync
block plus its call into the two `TradeAnimation` predefs (Takeover point 2). This is a two-site
takeover, wider than Gen 1's one-site text-script swap, though each site individually still has the
same "one hook, many script callers" property that made Gen 1's swap cheap.

## ABI

Buffers a mailbox-fed takeover must fill in place of the real serial partner, all named at HEAD
(pre-rename union names from `pret_gen2_symbols.md` are explicitly not reused, per ticket 13's
resolution):

| Slot | Buffer(s) | Source |
|---|---|---|
| Received party staging (Trade Center/Colosseum) | `wOTPlayerName` (C `ram/wram.asm:2859`), `wOTPlayerID` (`:2860`), `wOTPartyCount` (`:2862`), `wOTPartyMons` (`:2868`) | Populated from `wLinkReceivedPartyData` (`:2828`) reconstruction, C `link.asm:258-295,448-463` |
| Received party staging (Time Capsule, Gen 1 peer) | `wLinkTimeCapsulePartyData` (`:1079-1108`) → `ConvertMon_1to2`/`Link_ConvertPartyStruct1to2` (C `link.asm:1032` onward) → same `wOTPartyMons`-family opponent staging | C `link.asm:91-103,112-188` |
| Local outgoing selection | `wCurTradePartyMon` (index into `wPartySpecies`), `wCurOTTradePartyMon` (index into `wOTPartySpecies`) | C `link.asm:1711,1804,1858` |
| Per-side confirm/cancel | `wPlayerLinkAction`, `wOtherPlayerLinkMode`, synced via `farcall PlaceWaitingTextAndSyncAndExchangeNybble` | C `link.asm:1770,1789,2035` |
| Traded-mon record (48 bytes, one mon) | `wTempMonSpecies` (staging), consumed by `AddTempmonToParty` | C `link.asm:1988-1994`; struct layout below |
| Nicknames/OT for the appended slot | `wPlayerName`→`wPlayerTrademonSenderName`, `wPartyMonOTs`→`wPlayerTrademonOTName`, and the opponent-side mirrors `wOTPlayerName`→`wOTTrademonSenderName`, `wOTPartyMonOTs`→`wOTTrademonOTName` | C `link.asm:1849-1901` |
| Mail (Trade Center only) | `sPartyMail` (SRAM, per-slot `MAIL_STRUCT_LENGTH=$2f` records) copied/shifted, and `wLinkOTMail` (`ram/wram.asm:1128`) for the incoming side | C `link.asm:1804-1843` |
| Speed check-byte handshake (Mew/Celebi anti-cheat) | `wPlayerLinkAction`/`wOtherPlayerLinkAction` loop | C `link.asm:2001-2039` |

**Traded-mon record layout** (`PARTYMON_STRUCT_LENGTH`, C `constants/pokemon_data_constants.asm
:75-113`): `MON_SPECIES`(1) `MON_ITEM`(1, held item — this is what must convert/validate, not just
copy) `MON_MOVES`(4) `MON_OT_ID`(2) `MON_EXP`(3) `MON_STAT_EXP`(10, 5×u16)
`MON_DVS`(2) `MON_PP`(4) `MON_HAPPINESS`(1) `MON_POKERUS`(1) `MON_CAUGHTDATA`(2: time+gender or
level+location) `MON_LEVEL`(1) — this is `BOXMON_STRUCT_LENGTH` — then `MON_STATUS`(1) + pad,
`MON_HP`(2) `MON_MAXHP`(2) `MON_STATS`(10, 5×u16) = `PARTYMON_STRUCT_LENGTH`. Nickname and OT name
are separate fixed arrays (`NAME_LENGTH`/`MON_NAME_LENGTH`), not part of this struct, appended by
`AddTempmonToParty`'s name-array copy (`engine/pokemon/move_mon.asm:420-444`, cited in ticket 13's
receipt).

**What must be converted, not just copied, for a mailbox-driven takeover:**
- **Held item** (`MON_ITEM`): must be validated against the receiving side's item table (Gen 2 item
  IDs) — the real serial exchange never crosses games with different item sets except through the
  Time Capsule path, which is exactly why Time Capsule checks item-as-mail before allowing entry
  (`CheckTimeCapsuleCompatibility` item loop, C `link.asm:2131-2144`, using `farcall ItemIsMail`)
  rather than converting held items at all.
- **Mail**: only exchanged Trade-Center-side (`sPartyMail`/`wLinkOTMail`, C `link.asm:1802-1843`);
  Time Capsule explicitly refuses entry if any party mon holds mail (`CheckTimeCapsuleCompatibility`
  returns 3, C `link.asm:2132-2144`) — mail is out of scope for any Gen-1-facing conversion path by
  the game's own design, not an omission a takeover needs to fill in.
- **Species/move validity** (Time Capsule only): `CheckTimeCapsuleCompatibility` refuses any
  Gen-2-introduced species (`>= JOHTO_POKEMON`) or Gen-2-introduced move (`> STRUGGLE` for the old
  move table) before the wait even starts (C `link.asm:2118-2166`); a companion takeover reusing
  this path inherits the refusal for free as long as it runs the same check before publishing an
  offer.

**Cartridge-owned YES/NO handshake.** Three separate YES/NO prompts exist and all are native menu
code the takeover does not need to reimplement, only gate on: (1) receptionist intro accept/decline
(`yesorno` after `Text_*ReceptionistIntro`, C `maps/PokeCenter2F.asm:73,173,302`); (2) save-before-
link accept/decline (`yesorno` after `Text_MustSaveGame`, C `:87,190,318`); (3) the in-`LinkTrade`
mon-select-vs-Cancel 2D menu (C `link.asm:1735-1770`), which is the actual per-pair trade
confirmation and is exchanged via the nybble-sync farcall, not a plain `yesorno`. A takeover
supplies data at (1)'s post-accept point and at (3)'s selection, while (2) is a pure local
save-confirmation the cartridge already handles unmodified (feeding into the receptionist's own
`TryQuickSave`, distinct from post-trade `SaveAfterLinkTrade` — ticket 13's finding).

## Out of scope paths

- **Time Capsule** is a plausible *future* extension (it already contains its own from-Gen-1
  conversion machinery, `ConvertMon_1to2`/`Link_ConvertPartyStruct1to2`, C `link.asm:1032` onward)
  but is **out of scope for this takeover design** because: (a) it requires a second, different
  wire format entirely (Gen 1 party struct → Gen 1-to-2 conversion) that a Gen-2-native mailbox ABI
  does not need to support to satisfy the Cable Club trade requirement; (b) its own compatibility
  gate already forbids the two highest-value payloads (held mail entirely, and any Gen-2-native
  species/move) — supporting it would mean designing an ABI around the *more* restrictive of the two
  formats for no functional gain over the direct Gen2↔Gen2 path; (c) ticket 13's receipt already
  flags Time Capsule conversion edge cases as untested/unverified. Recommendation: revisit only if
  a cross-generation companion bridge (Gen 1 ↔ Gen 2 SLink peers) becomes a product goal; the
  takeover points identified above (receptionist `special`s, `LinkTrade` selection/sync) are
  structurally the same call sites Time Capsule would need, so nothing here forecloses it.
- **Crystal Mobile Adapter path** (`maps/MobileTradeRoom*.asm`, `.Mobile`/`.SelectThreeMons`
  branches in `PokeCenter2F.asm:76-83,150-169,229-260`) is out of scope: it is a different physical
  transport (mobile adapter vs. Game Boy Link Cable) reaching the *same* `LinkTrade`/
  `LinkCommunications` code, and it does not exist in Gold/Silver at all (G `PokeCenter2F.asm` has
  no `CheckMobileAdapterStatusSpecial` call). A cable-Cable-Club takeover is orthogonal to it; mobile
  support would be a separate, Crystal-only transport question, not a different local-write ABI.
- **Colosseum (battle-only link)** commits no party mutation at all — it is a battle, not a trade —
  so it is out of scope for this ticket's ABI question, though its receptionist script shares the
  same four `special` takeover points 1 (`SetBitsForBattleRequest` instead of
  `SetBitsForLinkTradeRequest`, otherwise identical shape, C `PokeCenter2F.asm:171-199`) and would
  need its own (non-trade) native-battle design if ever taken over.

## Recommended design + gate controls

**Shape:** a two-site companion takeover mirroring Gen 1's lease pattern but split across the two
Gen-2 call sites identified above, reusing Gen 1's proven ABI concepts (magic+version header,
monotonic generation counters published last, bounded frame windows, nonzero visit token) rather
than inventing a new protocol shape:

1. **Receptionist site** — replace `WaitForLinkedFriend` (and `CheckLinkTimeout_Receptionist`) with
   a QUERY/OFFER-shaped mailbox exchange (per assumption: address lives in always-mapped RAM, from
   ticket 14 once resolved), gated by the same eligibility check the four scripts already run
   (`checkevent`/`checkflag` before the `special` calls) so an ineligible visit never reaches the
   mailbox at all — this reproduces Gen 1's T-1/T-2 requirement shape (menu/offer gated, CANCEL
   falls through) without touching script bytecode.
2. **`LinkTrade` site** — replace the `ScrollingMenuJoypad` selection sync
   (`PlaceWaitingTextAndSyncAndExchangeNybble` calls, C `:1770,1789`) with a PROMPT/APPLY mailbox
   exchange carrying the outgoing slot, the 48-byte record + names (+ mail, Trade-Center-only) for
   the incoming mon, and the partner's decision, before falling into the existing
   `TradeAnimation`/`TradeAnimationPlayer2`/`AddTempmonToParty`/`EvolvePokemon`/`SaveAfterLinkTrade`
   chain unmodified — this preserves ticket 13's already-verified save behavior (recomputes both
   checksums, backs up mail/RTC, does **not** call `SaveBox`/`SavePlayerData`) with zero changes to
   the commit path itself.
3. Keep the Mew/Celebi checkbyte loop (C `:2001-2039`) and `CheckTimeCapsuleCompatibility`-shaped
   item/mail/species/move validation intact and exercised on the mailbox-supplied record, not
   bypassed, so illegal payloads are refused by the same logic vanilla uses against a legitimate
   partner.

**Negative controls a live gate needs**, mapped from Gen 1's own gate shape
(`docs/purergb/PLAN.md` receptionist/APEX gates) and this flow's specific failure points:

| Control | What it proves | Where it must be exercised |
|---|---|---|
| Decline at receptionist intro `yesorno` | Cancel path returns to overworld, no mailbox write persists, no `special` side effect (mirrors T-1's CABLE CLUB/CANCEL fall-through) | Site 1, step 2 of the flow |
| Decline at `LinkTrade`'s Cancel menu item, or B-press | Both sides see "trade was canceled" text (C `:1772-1783`), no `AddTempmonToParty` call, no save | Site 2 |
| Timeout at `WaitForLinkedFriend` / `CheckLinkTimeout_Receptionist` | `.FriendNotReady`/`.LinkTimedOut` paths taken, mailbox generation not advanced past QUERY, no partial offer state persists | Site 1 |
| Disconnect mid-trade (after PROMPT, before APPLY completes) | No `AddTempmonToParty`/`EvolvePokemon` runs on a half-exchanged record; the outgoing mon (already removed by `RemoveMonFromPartyOrBox REMOVE_PARTY`, C `:1943-1955`) is not silently lost — this is the same class of risk ticket 13 flagged for `SaveAfterLinkTrade`'s scope | Site 2, between removal (C `:1943`) and successful `AddTempmonToParty` (C `:1994`) |
| Save failure / no host flush after `SaveAfterLinkTrade` | Ticket 13: `SaveAfterLinkTrade` recomputes checksums and returns; it is not proof of physical SaveRAM durability. A live gate must independently confirm both peers' cartridges show the swapped party post-reload, per T-4's PYDEC-readback pattern | Post-`.save` (C `:2044`) |
| Illegal payload rejection (item/species/move/mail out of range) | Companion-supplied record is refused the same way a genuine incompatible partner would be (Time-Capsule-shaped compatibility check reused, or an equivalent Gen2↔Gen2 range check since Trade Center itself has no such gate today — this is a **new** validation the takeover must add, since vanilla Gen2↔Gen2 trades never receive out-of-range data from a genuine cartridge) | Site 2, before `AddTempmonToParty` |

**Gen 1 T-1..T-4 mapping:**
- **T-1** (receptionist menu gated, CABLE CLUB/CANCEL fall through) → Takeover point 1: the
  eligibility `checkevent`/`checkflag` gates plus a CANCEL/decline path that falls through to
  vanilla `.Cancel`/`Script_*Closed`, same shape as Gen 1's dispatch swap.
- **T-2** (ineligible offer refused in-game, eligible = valid pair) → the mailbox QUERY/OFFER
  exchange at Takeover point 1, plus (new, since Gen 2 has no equivalent native refusal text
  in-flow) an explicit "trade unavailable" style notice mirroring Gen 1's `_handle_trade_offer`
  shape.
- **T-3** (partner prompt YES/NO/B, screen restored) → the `LinkTrade` selection menu itself (C
  `:1735-1770`) already provides this natively; a takeover only needs to feed it the partner's
  offered mon name/species, not reimplement the YES/NO.
- **T-4** (apply: animation, evolution, save; both sides decode swapped mons; received mon in last
  party slot) → Site 2's unmodified fall-through into `TradeAnimation(Player2)` →
  `AddTempmonToParty` (append, so "last party slot" holds by construction, matching ticket 13's
  finding that the original slot is compacted away and the new mon is appended, not written back
  in place) → `EvolvePokemon` → `SaveAfterLinkTrade`.

## Open questions

- Exact mailbox address/bank and its read/write contract are ticket 14's job; this design assumes
  "exists in always-mapped RAM" per the task brief and does not propose one.
- Whether one shared hook implementation can serve all three receptionist scripts (Trade/Battle/
  Time Capsule) without duplicating the `special`-replacement four times, or whether Gen 2's
  `special` dispatch table (unlike Gen 1's text-script opcode table) makes a single shared routine
  natural — not verified against the `special` dispatch mechanism's source (`engine/specials.asm`
  or equivalent) in this pass.
- Whether `LinkTrade`'s menu code (`ScrollingMenuJoypad`, native 2D menu machinery) can be reused
  unmodified by a takeover that only replaces the sync farcalls, or whether the takeover needs to
  also own the menu's underlying data source (`wCurOTTradePartyMon`, `wOTPartySpecies` staging) —
  this document assumes the menu is reusable if OT-party staging is filled correctly, but that has
  not been verified against how `ScrollingMenuJoypad` reads its item list.
- Whether Trade Center vs Colosseum vs Time Capsule room-compatibility (`CheckBothSelectedSameRoom`)
  needs replication in the takeover, or whether a single-cartridge-pair (non-serial) session makes
  the concept vacuous — flagged but not resolved here.
- Live-gate qualification for all of the above negative controls is unrun; this document proposes
  the matrix, per the worker card's falsifier requirement, but running it is implementation-phase
  work, not research.
- Exact `special` dispatch mechanism (jump table vs. direct call site inlined per script) was not
  traced in `engine/specials.asm`; the design above assumes replacing the routine body is
  sufficient and equivalent to Gen 1's opcode-table swap, but the two dispatch mechanisms were not
  directly compared line-for-line.
