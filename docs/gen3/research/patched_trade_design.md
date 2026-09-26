Replaces the withdrawn HUD design at `4f9f30c5`, owner ruling 2026-09-26.

# Patched Gen 3 trade: shared contract (T1, design only)

The Emerald lane is the **only implementation writer** for FR, LG, Emerald and RR;
the Gen 3 lane supplies facts and reviews. T2/T3 wait until the coordinator merges
the RR fix batch from master into this lane. No code, build, emulator or admission
change is authorized by this document alone. Owner/coordinator directions are from
the T1 card and follow-up of 2026-09-26.

## 1. Evidence and scope

- **R:** SLink `4f9f30c5df2a11dc2d3c64b8d21f8610010f7b2d`, this card's base.
- **G:** Gen 3 lane `bfadb7e30b377b38061668bc585e9aea5f35c871`; read with `git show`.
- **W:** Gen 3 watchdog-doc correction `02db4dd5` (do not restore R's stale claim).
- **F/E:** pret pins, exact owner-ROM hashes, signatures, byte anchors and symbol
  lines are in [patched_trade_bindings.md](patched_trade_bindings.md).
- **X:** pokeemerald-expansion `e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7`.
- **SOURCE** establishes code/data and candidates; **MODEL** tests failure logic;
  **PHYSICAL** requires ordinary game execution and independent saved-state readback.
  T1 supplies SOURCE only. Candidate padding/addresses are not qualified resources.

Owner rulings: "Supported on patched ROMs only"; "Evolve on receipt"; for reset
without save, "Look at how other patched gen1/2 do it." The UX is the accepted RR
flow: A-button companion NPC, server-sequenced native menus and the game's scene.
There is no new HUD input controller and no clean-ROM trade fallback.

**RR is a full client**, not merely a regression row. All four titles receive the
save-before-DONE and uncertainty contract below. Evolution follows each cartridge's
own trade-evolution data, not a hardcoded vanilla species list. RR retains trade
methods in the inspected binary (bindings §6); its item alternatives do not remove
those entries. This is SOURCE evidence, not a played evolution receipt.

## 2. Accepted precedents and current gaps

Gen 1 patched R/B reuses the Cable Club receptionist, asks to save before the offer,
runs `InternalClockTradeAnim`, evolves the appended received mon, and calls full
`SaveGameData` before returning success (R `patch/gen1/src/trade_receptionist.asm:1,53-81`;
`patch/gen1/src/native_trade.asm:186-234`). pureRGB's overlay does the same through
linker-resolved farcalls; clean pureRGB does not advertise native trade
(R `patch/gen1/purergb/overlay/native_trade.asm:172-220`;
`server/adapters/gen1_purergb.py:236-249`).

Crystal uses its existing Trade receptionist; both proposer and responder perform
native full pre-saves. Commit removes, animates, appends, evolves, then calls
`SaveAfterLinkTrade` and `BackupGSBallFlag` before completion
(R `patch/gen2/src/trade_receptionist.asm:27-34`;
`trade_service.asm:174-184`; `trade_commit.asm:79-169`, in that same directory).
Its reset-commit test interrupts **after native save return, before DONE**; it is not
proof for arbitrary power loss during flash writes
(R `lua/tests/duo/gen2_trade.lua:73-75,1262-1295`).

RR already has native NPC/menu/scene execution. Its existing success ACK means CB2
returned to the field, and its new duo saves afterward on the runner's `SAVE`.
Neither is proof of native save-before-DONE (G `patch/src/handlers.c:1119-1141`;
`lua/tests/duo/scenario_gen3_trade.lua:3-14,299-301`). `OP_SET_PARTY_MON` is raw copying,
not evolution/save (W `patch/src/handlers.c:2024-2036`); `EV_EVOLVE` polling observes a
change, it does not cause one (same file:1784).

Clean FR/LG has no SLink executor: native binding is RR-companion-only and
`apply_trade` refuses without it (R `lua/gen3/entry.lua:316-321`;
`client.lua:1515-1520`). `SLink-RR.ups` is RR-input-bound and cannot be applied to FR
just because RR is FR-based (R `server/patcher.py:51-75`;
`patch/tools/build.py:90-95,193-208`). Normal game NPC trade observation is separate:
the `TradeMons` hook marks record swap, not scene/evolution/save completion
(R `data/games/gen3_frlg/engine_signals.json:531`).

## 3. Required lifecycle

1. **Admission:** exact admitted companion artifact, ABI/beacon, title bindings,
   session and safe native window. Clean/unknown artifacts refuse without writes.
2. **Offer/confirm:** ordinary A-button NPC interaction drives server
   `show_choices` → `choose_mon` → partner `show_menu`; retain native B/NO cancel.
   Both cartridges obtain native save consent and a successful pre-trade save
   before they may answer ready. No offer/ready packet means a swap has occurred.
3. **Prepare:** advertise `trade_prepare: true` only when fully implemented;
   `apply_prepare {token,slot,old_key}` revalidates the live offered identity,
   accepted visit and capacity/eligibility. Both `apply_ready {token,ok:true}`
   responses are required. Readiness expires/withdraws rather than authorizing a
   future unrelated menu or party slot.
4. **Apply:** receive tokened partner blob, relocate outgoing identity at dispatch,
   own staging until ACK, and revalidate before the first irreversible mutation.
   Publish an observable commit-entry milestone; do not infer it from elapsed time.
5. **Native receive:** stage partner data, invoke the game's trade scene, perform
   its `EVO_MODE_TRADE` evolution, then read the final received identity/species.
   Preserve native item/name/friendship/Dex behavior; validate title-specific mail
   and egg eligibility before commit instead of manufacturing incomplete records.
6. **Durable completion:** native post-trade save must report success, with the
   final evolved mon included, before patch DONE/`trade_done` can mean success.
   Save failure or unknown outcome cannot be converted into success by field return.
7. **Server completion:** emit `trade_done {token,slot,new_key,new_species}` only for
   the verified final result. Preserve token matching and paired atomic settlement.

Steps 2's UI is existing RR behavior (R `server/state.py:816-838,955-965`);
steps 3/7 reuse shared protocol (same file:991-1032,1064-1130,1186-1211).
Gen 3 currently lacks the prepare declaration (R `lua/gen3/native.lua:83`;
`client.lua:970-985`); the pre/post-save and commit milestones are new requirements.

**No raw-swap success:** retire `OP_SET_PARTY_MON` as a successful trade fallback.
A pre-mutation failure can cancel. A recovery executor is allowed only if it uses
the same native evolution/save lifecycle; a timeout must never overwrite a scene
that may already have committed (R `client.lua:1432-1475`; `native.lua:426-434`).

## 4. Reset, uncertainty and ownership

- Before commit entry: withdraw unpicked APPLY and report unchanged, never claim
  that a transient RAM snapshot proves durable success.
- After commit entry with lost DONE, failed save or reset: preserve token/owed
  uncertainty, send `trade_done {token,uncertain:true}` after the eligible hello.
  Where RAM may reflect an unsaved result, use `after_reset:true` and require
  evidence from the reloaded save. Do not release the uncertain lease into reuse.
- After successful completion, a reset without an additional manual save must
  reload the received/evolved mon. Test this independently on **RR as well**.
- Server restart restores applying as uncertain. Both traded commits; both unchanged
  rolls back; conflicting evidence stays visible for reconciliation, never guesses.
  Do not roll back one cartridge's RAM to imitate a distributed transaction.

Precedent: R `lua/gen1/client.lua:2094-2117,2160-2177`;
`lua/gen2/client.lua:771-807,848-862`; `server/state.py:1114-1124,1147-1157,1186-1262`.
The watchdog asks capable silent clients to withdraw, then awaits evidence
(R `state.py:709-736`; W `docs/gen3/PLAN.md:240`). Current Gen 3 reset simply drops
its trade state and must change (R `lua/gen3/client.lua:936-942`).

All host writes remain behind `writes.lua`'s gate, with the native queue owning
staging and dispatch-time identity checks (R `native.lua:217-250`;
`client.lua:1311-1334`). Save success and native completion need separate witnesses.

## 5. Binding and safety contract

Per-title companion targets must supply their own native function/data addresses,
ROM detour, EWRAM allocation, ABI/capabilities, callback lifecycle and save caller.
The existing RR builder/payload is modern freestanding ARM GCC; recreating the
original FR/LG/E ROM with agbcc is a different operation. Do not silently modern-
rebuild a clean cartridge while retaining its old identity (bindings §§1–4).

Generalize admission at R `entry.lua:320` and `native.lua:66`, plus the generator's
RR-only `native_block` source selection (`tools/gen_gen3_profile.py:670-689,1042`).
Keep RR rival-swap branches (`native.lua:259,318`) and its IRQ exception
(`safety.lua:118-125`) RR-only. Bind capabilities; do not delete safety guards.

`native_trade_ui` means **cartridge-owned menu sequencing**, not patch presence.
This RR-style server-sequenced native UI retains False. True requires the complete
Gen 1/2 `trade_query`/`trade_mask`/`trade_offer` protocol; changing only the flag
skips menus and changes payloads (R `server/adapters/base.py:331-345`;
`state.py:823-838,936-938,1074-1076`). Preserve foundation pairing; this card does not
authorize FR↔Emerald or RR↔FR trading.

Every name copy to `gStringVar*` must cap to destination capacity and append the
native terminator, including maximum-length source fields. Re-derive capacities
per title: FR/LG/RR Var1=32, Var3=20; E Var1/Var3=256 (bindings §5).
RR's full 10-letter nickname caused an actual expansion overrun; its bounded-copy
and chooser-return fixes are mandatory inputs (G `handlers.c:1030-1057,1127-1140`).
Make `lua/tests/test_live_tradescene.lua`'s fullname case a standard red test for
every title. START-row fix `03b19b71` must also survive integration.

For expansion, implement the companion in source, reserve named linker objects,
and regenerate all build-specific facts/identity; do not transplant RR addresses.
Its evolution API/parties/names differ (X `src/trade.c:3872-3878,4372-4383`;
`include/constants/global.h:156-157`). It is a subsequent target of this lifecycle.

## 6. T2–T6 cards: exclusive ownership and first falsifiers

All are future leases inside the **Emerald lane**; Gen 3 reviews, not a second writer.
T2/T3 start only after master carries `2c553181`, `03b19b71`, rebuilt UPS and their
generator/site/research repins, and the coordinator merges that batch here.

| Phase | Exclusive writer/files | First falsifier, then exit evidence |
|---|---|---|
| T2 producer | One writer: `patch/src/handlers.c`, `patch/tools/build.py`, `patch/src/slink.ld`; proposed new `patch/src/trade_targets/{firered,leafgreen,emerald,radical_red}.{h,ld}`, `patch/dist/SLink-{FR,LG,Emerald,RR}.ups`, `server/patcher.py`. | Red: FR arena placed at RR mailbox overlaps allocator; wrong base/detour bytes refuse; fullname probe fails old unbounded copy. Green: per-title arenas/detours, native scene/evolution/save-success milestones, hashes and opcode probes. RR receives the same durable lifecycle. |
| T3 shared client | One writer: `lua/gen3/{native,entry,client,safety}.lua`, optional `lua/gen3/trade.lua`, `tools/gen_gen3_profile.py`, related `tests/unit/test_gen3_{native,client,entry,profile_native}.py`. Separate pack writers only after schema freezes: `data/games/gen3_{frlg,rr,emerald}/`. | Red: completion before save success, late APPLY after withdrawal, reset dropping uncertainty, or raw-swap reporting success. Green: typed milestones, prepare/withdraw/token guards, clean-ROM refusal, unchanged unrelated gates, generated companion pins. |
| T4 server contract | One writer: `server/adapters/gen3_frlge.py`, proposed `tests/unit/test_gen3_trade_server.py`; `server/state.py`/`server.py` only for a demonstrated contract gap. | Red: stale token/one-sided result commits, or native_trade_ui=True skips required menus. Green: existing paired prepare/persist/uncertainty settlement reused, adapter guard and independent review for shared-server changes. |
| T5 qualification | One writer: `tools/e2e_duo.py`, `lua/tests/duo/scenario_gen3_trade.lua`, proposed `scenario_gen3_trade_{evolve,reset_wait,reset_commit,abort}.lua` in the same directory, `tests/unit/test_e2e_duo_gen3.py`, `lua/tests/test_live_tradescene.lua`. One serialized emulator lane. | Red: remove native save, suppress evolution, truncate full names, or inject lost-DONE/reset; oracle must fail. Green: FR↔LG, E↔E and RR↔RR native entry/scene/save/reload, negative controls, per-title receipts. |
| T6 expansion | One writer after X1 owners release: proposed `patch/expansion/0001-slink-trade.patch`, `tools/build_expansion.py`, `data/gen3_exp_sources.lock.json`, `tests/unit/test_build_expansion.py`; `tools/{gen_expansion_facts,extract_expansion_data}.py`, `data/games/gen3_exp/`, `server/adapters/gen3_expansion.py` binding updates coordinated as a single lease. | Red: changed layout/config or old ROM hash admitted, 12-char name overrun, incorrect evolution API. Green: two builds of the new companion identity, generated facts, same lifecycle duos. |

T5 must include clean/no-patch, B/NO, stale token, reorder, missing beacon,
scene failure, peer disconnect, save failure, reset-wait, reset after native save
before DONE, and reset after success **without manual save**. Ordinary NPC/menu
inputs and independent decoded save/reload are required; harness SAVE cannot
substitute for the native-save witness (R `gen2_trade.lua:1262-1295`, under
`lua/tests/duo/`). A record-swap hook is insufficient (`engine_signals.json:531`,
under `data/games/gen3_frlg/`).

## 7. Proposed Gen 3 documentation amendments (review before master)

Do not edit PLAN/requirements in T1. Gen 3 approves the eventual diff:

- Replace PLAN §10's withdrawn HUD fallback wording with this patched-only shared
  companion contract; keep clean FR/LG unsupported and clarify RR's full scope.
- Revise requirements N-3 to forbid raw-copy trade success, require native
  evolution where the cartridge defines it and native save-before-DONE; add
  prepare/withdraw/reset/reload evidence for all four titles.
- Retain W `02db4dd5`'s corrected watchdog wording. Update older missing-RR-duo
  wording using G's `trade_gen3`/`trade_decline_gen3`, without claiming those
  ordinary post-scene-save duos prove the new durability contract
  (G `tools/e2e_duo.py:413-417`; `scenario_gen3_trade.lua:299-301`).
- Revise Emerald E5/HUD references in the coordinator's own docs card, after
  approval; do not create a competing FR/LG implementation in another lane.

No new UX or gameplay-policy question remains in T1. Implementation gates and
review acceptance are still required; neither this design nor binding candidates
constitute a release or runtime sign-off.
