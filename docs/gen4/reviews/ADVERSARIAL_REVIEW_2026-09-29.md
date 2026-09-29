# Gen 4 plan and research adversarial review — 2026-09-29

Review cut: `7da76fbff629b9190b290a7324a557c03171a061`, plan rev 4 plus the later C1-7/C1-8 research. Coordinator: Codex `01a0ef70-cfd3-7931-9bdf-dd9401a9de18`. The source tree was clean at intake. This receipt records review findings; it does not change the plan, authorize implementation, sign G0, or qualify a release.

**Verdict: revise before G0 approval.** The shared-core direction, hash admission, dynamic save-array access, per-build hge packs, and separate evidence classes are sound choices. The strongest remaining risks concern the required active faint and whether the proposed gates can distinguish it from a later checkpoint write. Several source claims in the new research are incorrect or have not reached the plan. The work should advance through bounded mechanism experiments after these contracts are corrected, rather than through another broad research round.

No unit suites, emulators, builds, or production edits were run for this review. Findings below are SOURCE reasoning, existing FILE/research-PHYSICAL observations, or explicit unknowns. A proposed failing sequence is a falsifier to implement, not an executed test result.

## Coverage and primary inputs

The coordinator read `PLAN.md`, `RESUME.md`, all 14 research Markdown files, and the data schemas/inventory. Independent reviewers inspected the four research JSON artifacts and the relevant primary sources. The review also inspected the current shared session, identity, deferred queue, hook registry, write permit, server pairing/admission, release packaging, and lane-verdict code.

Local primary source heads were verified read-only:

| Source | Verified head |
|---|---|
| `E:/Howard/hgss_archipelago-master/.tooling/pokeheartgold` | `ad7a3afa0cfc144fe6837c410cb95b2727217f54` |
| `E:/Howard/HGEngine_ROMHack/hg-engine` | `fc517576498305ecb5f5e1de44681c6e3822361b` |
| `.cache/gen4/pokeplatinum` | `c248fb3f8cc9934ded800e489567c5c0eeee92eb` |

The three local xMAP SHA256 values were recomputed and match `research/README.md:43-45`. The HGSS citation checkout is older than the xMAP's originating source (`research/README.md:42,48`); source semantics and compiled layout therefore remain separate evidence until the generator proves their correspondence. Existing live research receipts were inspected; none were promoted to G1/G4 qualification.

## Required corrections

### F1 — P1: the plan has conflicting one-copy and two-copy write contracts

`PLAN.md:149` describes `battle_faint` as writing `BattleMon.hp`, with a receipt only for that field, while its C1-8 card at `:295` already specifies both HP copies. The later `research/battle_faint.md:12-16,30-38` correctly establishes two copies and requires both. Pret `src/battle/battle_controller_player.c:3430-3468` uses party HP for replacement; `asm/overlay_12_022378C0.s:892-895` copies the battle party to setup, then `src/battle/battle_setup.c:425-434` copies it to save. There is no guaranteed end-of-battle BattleMon-to-party synchronization. The research has the correction; architecture and gate receipts must consistently adopt it.

**Failure:** live battle HP reaches zero, but replacement logic or native save still sees the original party HP. A successful write receipt can mask a mon that reloads alive.

**Correction:** make the two-copy write an explicit storage/profile/permit contract. Revalidate PID:OTID, slot, battler ownership, pointer epoch, and encryption state immediately before writing. Cover both spans in one prevalidated batch and record both before/after values. The shared permit emits bytes sequentially (`lua/write_permit.lua:135-155`); prevalidation is not rollback. A partially completed batch must fail visibly and revoke further mutation, rather than return success.

**First falsifier:** change only BattleMon HP while leaving party HP intact; the active-faint oracle must fail. Then prove both-copy behavior on win, status-only turn, switching, and loss with the loss-specific witness in F5.

### F2 — P1: controller command 11 is not an established safe or observable seam

`research/battle_faint.md:19-21,34` calls command 11 the safe point before turn end. Pret `src/battle/battle_controller_player.c:1571-1655` still processes Future Sight, Perish Song, and Trick Room there, including transitions into battle scripts. `asm/overlay_12_022378C0.s:743-786` contains two guarded `BattleContext_Main` calls within one battle update; each dispatches the current command (`battle_controller_player.c:159-170`). Consequently, a frame poll has no established guarantee of observing every command-11 interval. This is a source-supported coverage risk, not a reproduced live miss.

**Correction:** derive a pinned execution boundary after outstanding HP effects and before the relevant replacement/outcome sweep, or prove a poll coverage/liveness bound. Budget any required controller hook. State how a command received at the selection screen is serviced: command 5 can await input indefinitely, so “end of the current turn” does not establish D7's “immediately” requirement (`PLAN.md:34`). Do not silently substitute a turn-end definition for the owner's requirement.

**First falsifiers:** a complete transition census that detects a missed candidate seam; Future Sight and Perish Song due on the same turn; forced faint received while input is idle, during a switch, and during a run attempt. Record command-to-game-effect latency separately from network latency.

### F3 — P1: the raw party-tail recipe assumes an encrypted record

`research/battle_faint.md:35-36` always XORs the HP word with the PID stream. Pret `src/pokemon.c:122-143` exposes `AcquireMonLock`/`ReleaseMonLock`: while `partyDecrypted` is set the tail is plaintext. `GetMonData` and `SetMonData` branch on that state (`pokemon.c:410-426,886-904`).

**Failure:** an encrypted-form zero written into a locked plaintext record becomes a nonzero/corrupt HP value, then is re-encrypted on release.

**Correction and falsifier:** either refuse locked records at the write seam or explicitly support their representation. A lock-state model must go red for unconditional XOR. Preserve flags and checksum rules: party-tail-only HP edits are outside the box checksum; box-data edits require checksum regeneration. Reject a same-species but wrong-key party copy—the species invariant in `research/battle_pointer.md:17` is structural evidence, not identity evidence.

### F4 — P1: zero HP and replacement do not prove the required faint sequence

`PLAN.md:261` requires a game faint sequence. `research/battle_faint.md:28,37` leaves FAINTED state untouched. Pret `src/battle/battle_command.c:978-1003` sets that state through the faint command; controller `TryFaintMon` (`battle_controller_player.c:3658-3682`) reacts to the bit. The turn-end HP sweeps establish replacement or outcome, not by themselves the normal faint subscript/animation.

The G4 oracle (`PLAN.md:228`) combines a client self-reported write receipt with a save witness. Both can pass if the battle operation fails and a later checkpoint write produces zero saved HP. An earlier G1 research pass does not prove the actual G4 duo run.

**Correction:** each active-faint G4 scenario needs an independent, encounter-bound observation of the game's required faint behavior, within the agreed bound, before checkpoint fallback is possible. Require no wrong-battler effect and exactly one linked effect. Normal animation remains a PHYSICAL unknown; it is not proved absent by this review.

**First falsifier:** disable the battle-context operation but keep the deferred party-faint path and client receipt producer; `linked_faint_active` must fail. Apply the same control in doubles.

### F5 — P1: wild-loss provenance and post-heal evidence are incomplete

`PLAN.md:131` permits whiteout polling through `BattleSetup` or `VAR_BATTLE_RESULT`. Pret `src/encounter.c:102-107` writes VAR in `Encounter_GetResult`, but the wild-loss path (`:369-375`) reads setup's `winFlag` directly and jumps to blackout without that VAR update. A VAR-only observer can miss a wild loss or consume a stale earlier result. The app-derived zero-hook chain disappears on application teardown (`research/battle_pointer.md:12-26`), so outcome lifetime must outlive that chain without keeping a stale writable pointer.

Further, `src/blackout.c:189-205` heals the save party after wild loss. Special battle paths also heal (`src/encounter.c:145-156`). The trainer-follower branch can heal after a **win** (`:154-156,379-380`), so the persistence probe must include a win with that NPC-follower flag set. `src/scrcmd_battle.c:109-110` reads a follower **trainer number** for this flag; it is not proof that HGSS's ordinary walking Pokémon triggers healing. A blanket post-whiteout “saved HP must be zero” oracle is wrong for native healing; zero HP obtained through a later SLink correction would not prove battle copy-back. Likewise a post-win native heal is a distinct persistence problem even if the earlier in-battle faint actually occurred.

**Correction:** retain an encounter identity/outcome receipt through copy-back and blackout, clear it exactly once, and separate pre-heal two-copy/outcome evidence from post-heal native save/reload evidence and SLink death state. Do not reopen the owner's whiteout policy implicitly.

**First falsifiers:** win followed by wild loss, two successive wild losses, last-mon linked faint, win with an NPC follower, and ordinary trainer loss. Each must report the correct outcome, emit whiteout exactly once when appropriate, and preserve evidence of the expected native healing phase.

### F6 — P1: shared battle-command gating needs an explicit eligibility/epoch contract

The plan promises unchanged `lua/core/session.lua` (`PLAN.md:108-111`). Its held battle queue checks `writes_enabled`, but not connection/hello eligibility before invoking the game writer (`lua/core/session.lua:168-189`). `frame_end` clears hello on disconnect (`:363-367`) and still flushes the battle queue (`:423`). Deferred writes separately check the connection (`:427-433`). Save reset handling invokes the driver's reset hook; the queue lifetime is not automatically a Gen 4 battle epoch.

**Failure:** hold a `force_faint`, disconnect, then reach the battle write seam; the queue can still invoke the writer. A stale command must not attach to a new battle/save merely because a key resolves.

**Correction:** use the existing `session:eligible()` (`:109-110`) and explicit save/battle epochs in the Gen 4 write binding, with reset/disconnect behavior specified. If the generic queue contract changes, put that lifecycle rule in the shared session and review its Gen 1–3 effects. Do not duplicate transport or session policy inside the game adapter.

**First falsifiers:** disconnect while held, reconnect to a wrong save, same-key record after reset, ended battle before application, and duplicate server commands. Refusal must produce no bytes and no success receipt.

### F7 — P1: phase registration has undefined static phases and failed-close handling

`PLAN.md:122-134` arms phases on overlay residency. The party/PC sites are static ARM9 functions and the plan names no actual activation predicate for that phase; those mutators also serve non-UI acquisition paths. The one-frame-late registration is declared harmless (`:124`) without a producer reachability proof.

Additionally, `lua/hook_registry.lua:58-76` may fail to unregister a handle and retain the owner reservation. `status().registered` (`:47-49`) is a cumulative successful-registration count, not a current external handle census. Dropping a failed-close registry from the open-registry table can undercount live hooks, while the next arm fails on a reserved owner (`:104`).

**Correction:** define each phase's activation and full caller coverage; prove the earliest reachable event cannot precede arming, or supply reconciliation. Retain failed-close registries, retry cleanup or latch failure, and count remaining live handles truthfully. Specify the single session-facing composite's drain/close/status contract: drain queued events before removing a phase, retain pending closed-registry events until delivered, handle `Registry.new`'s `nil,error,failed_registry` return, and surface fault identity. `lua/core/session.lua:360,373,386` provides both pre-drain and post-drain seams; do not leave ordering accidental. A first-fatal global signal latch is acceptable if it stops the whole unsafe system; independent phase recovery would require distinct fault reporting. Resource lifecycle belongs in the shared NDS/platform layer; packs supply game-specific triggers and sites.

**First falsifiers:** earliest phase-entry event; event queued immediately before phase closure; battle-to-PC/script acquisition; load/unload within one polling interval; unregister returning false followed by phase re-entry; registry construction failing after its first registration. Hook failure must stop unsafe decisions, not merely produce a banner.

### F8 — P1: release verdicts must reject missing required artifact cells

G4 names missing SS/hge inputs as skips (`PLAN.md:234`); G6 requires only “zero unexplained skips” (`:237`). Shared `tools/release_lanes.py:56-67,79-106` accepts manifest-explained pytest skips, and `tools/e2e_duo.py:7681-7687` accepts signed-limit scenario skips. That machinery can support development reporting, but it is insufficient as the shipped-artifact completeness policy.

**Correction:** define exact required scenario IDs, both HG↔SS directions, hge columns, prerequisites, and independent oracle bindings. A named missing-input skip is OPEN and blocks that artifact's signature/release. D14 explicitly limits special-mode live play. Platinum is a non-shipping bind scope under D3, but its missing save-decode cell remains OPEN and cannot be claimed complete. Do not make mandatory SS/hge rows allowed skips merely because their absence is explained.

**First falsifiers:** remove the SS fixture, remove one hge save, omit doubles or NPC trade, deselect an expected scenario, or substitute an earlier-cut receipt. The verifier must refuse release even if the lower-level process exits zero.

### F9 — P1: G0/G2 prerequisites and card ownership need a coherent sequence

G0 requires a ledger and source lock (`PLAN.md:221`), but these are still C0-1/C0-2 cards (`:287-288`) and `RESUME.md:13-21` says to obtain G0 before dispatching the wave. G2 simultaneously requires decoding a populated hge mon and marks populated hge fixtures OPEN until D15 (`PLAN.md:223`); the research input snapshot is empty (`research/offline_measurements.md:94-100`). These are genuine prerequisites, not reasons to sign empty cells.

**Correction:** either complete C0 artifacts before G0 or split design approval from the pins/ledger signature. Keep the hge-mon G2 cell blocked on an available populated fixture. Assign row n and row o explicitly: C1-1 currently exits at a–m (`PLAN.md:290`), while G1 requires a–o. Replace the completed C1-7 research card with its actual remaining probe dependency; `RESUME.md` must match HEAD. Future implementation cards must acquire exact file leases before dispatch, rather than inherit the broad `G2+` wildcard row.

**First falsifier:** request G0/G2 signoff with the documented missing artifacts; the ledger must name the blockers and refuse those signatures.

## Further bounded corrections and input

**F11 — P1: hge overlay-byte corroboration selected the wrong ROM image.** `research/data/hge_site_survival.json:93-115` reports both `BtlCmd_TryFaintMon` and `ov12_0223843C` as ARM9 zero bytes. `.cache/gen4/offline/common.py:45-58` selects an ARM9 address match before considering overlays. The expanded hge ARM9 extends to `0x022477C8`, covering those addresses, so the offline resolver reads its padding instead of the owning overlay. This is a wrong-region read inside the expanded ARM9, not an out-of-bounds read. The SOURCE replacement claim may be true, but that FILE result does not independently corroborate it.

**Correction:** resolve a site by its declared binary/overlay identity and build provenance, then its address and complete extent. Re-measure both original ov12 sites and the build-specific replacement sites. `.cache/gen4/hge/offsets.ini:91` supplies `BtlCmd_TryFaintMon = 0x023CEDD0`; C0-3 already obtains those build exports, so absent replacement columns in the committed research JSON do not by themselves make pack generation impossible. Keep useful replacement addresses/provenance in the generated pack and verify ov130 residency/bytes before claiming a live hge faint mechanism.

**First falsifier:** give the resolver an hge overlay site whose RAM address also falls inside the expanded ARM9; it must select the named overlay and reject an ARM9-only zero-byte corroboration. Repeat with two different overlays sharing one address.

**F10 — P1: 13 NPC data records are not 13 executed exchanges.** D11 (`PLAN.md:42`) says 13 NPC trades are supported as `key_change`. The manifest has 11 `LoadNPCTrade` sites but ten distinct IDs `{0,1,2,3,5,8,9,10,11,12}`; ID 8 occurs in both Power Plant scripts. IDs 6/7 are Shuckie/Kenya grants: `src/scrcmd_c.c:3487-3494` routes `GiveLoanMon` to `NPCTrade_MakeAndGiveLoanMon`, which adds a mon without replacing an outgoing slot (`src/npc_trade.c:56-70`). ID 4 Rapidash has an enum/NARC record but no authored `LoadNPCTrade 4` or direct initializer in the pinned source scan. In contrast, same-species Steelix/Pikachu really execute trades (`scr_seq_0913_T26GYM0101.s:228-230`, `scr_seq_0834_T11R0601.s:153-160`); `src/npc_trade.c:153-165` copies the outgoing mon and replaces its selected slot.

**Correction:** present the corrected factual inventory to the owner: ten authored exchange identities, eleven load sites, two loan/gift paths, and one dormant record. Send `key_change` only for an executed replacement with old/new PID:OTID evidence; do not infer it from the presence of an NPC record or from equal/unequal species. Track hge's authored inventory separately rather than assuming the vanilla counts.

**First falsifiers:** `GiveLoanMon 6/7` and dormant record 4 must not emit fabricated `key_change`; same-species Steelix/Pikachu exchanges must change identity through the real exchange path. This corrects the premise underlying D11, rather than silently removing supported acquisitions.

1. **P2 — tag mapping table is wrong.** `research/battle_pointer.md:49-53` lists only local battler 0 in TAG. Pret creates two-enemy TAG without a follower (`src/encounter.c:701-721`); player battlers are 0 and 2 (`include/constants/battle.h:6-9`), and player-side TAG selects `trainerParty[b&1]` (`src/battle/battle_system.c:92-99`). Correct the table and test both local battlers, or explicitly limit the support claim. The proposed owner predicate can be correct; the prose table is not.

2. **P2 — G1 has two incorrect controls.** `PLAN.md:249` requires loader-hook hits equal all transitions. The raw HG log (`C:/slink/g4/probe/runs/hg_p3/out.txt:10,39`) has 15 hits/newly-active IDs but 22 table transitions; hge has 16 hits, 19 newly-active IDs and 27 transitions (`hge_p3/out.txt:10,41`). Loads and all transitions are different quantities even on HG; hge additionally has internal loads that bypass the hook (`research/platform.md:147`). Define a coverage comparison that accounts for observed loads, unloads and internal loads rather than a loose numerical allowance. `PLAN.md:254` and `research/sources_and_symbols.md:58` use the archived SaveData chain as a negative, while `research/platform.md:97` shows it aliases the real pointer after frame 197. Symbol-provenance rejection is valid, but steady-state value inequality is not an oracle; use early boot or an independently invalid chain.

3. **P2 — performance is a duplex requirement.** The raw `C:/slink/g4/probe/runs/hg_p6b/out.txt` confirms approximately 64 fps with four hooks in a 600-frame, single-instance idle CPU-time benchmark. That verifies the reported sample, not sustained two-client gameplay, memory polling, Lua scans, networking, or saves. Keep four as a maximum resource budget and add a G4 whole-duo performance/event-completeness receipt. State the accepted rate; follow the existing route-test versus qualification speed policy. No new near-3× Gen 4 promise is inferred here.

4. **P2 — acquisition completeness cannot be the script count.** The JSON's 61 script hits are an inventory, not an exhaustive producer oracle. `research/acquisition.md:35-41` also requires C-only `Party_AddMon` paths. Join script producers, C producers, 13 NARC records, runtime variable outcomes, and supported catch/gift/loan/daycare/contest policies. Preserve unresolved variable branches explicitly; do not silently drop them. D14's live limits do not remove its SOURCE/MODEL semantic obligations.

5. **P2 — D9 needs an admission interpretation.** `PLAN.md:40` says HG↔SS only, while the proposed map (`:177`) puts both titles in one foundation. `server/server.py:740-758` accepts same-foundation/same-kind pairings, which also permits HG↔HG and SS↔SS. If D9 is normative admission scope, enforce its title-pair relation using shared admission with game policy data and negative controls. If it only enumerates qualification lanes, say so explicitly; this review does not invent an owner ruling.

6. **P2 — Platinum bind is narrower than universal reuse.** D3 correctly limits it to SOURCE profile plus codec. `PLAN.md:206-213` nevertheless says every module counts as shared only on pack-only Platinum binding. `research/platinum_bind.md:24-34` leaves runtime idle/dirty offsets open; generating a profile cannot execute safety/storage/event semantics. Add a Platinum-shaped model using different save/box geometry, pointer chains, whole-save dirty flag, and idle clauses, or leave those reuse cells OPEN. No Platinum emulator scope is added.

7. **P2 — define fire-time pin width explicitly.** The measured callback `val` is a four-byte little-endian word, while the committed site JSON stores longer byte pins and `PLAN.md:121,139` uses the same "pin" language for registration and fire time. Specify the full registration byte extent and four-byte fire word separately, including signed/unsigned normalization. A fire-word pass proves only that word, not an eight-byte trampoline's target. Keep active-owner byte mismatches fail-closed: `PLAN.md:137` already drops inactive-overlay hits before checking bytes. OMP's proposal to drop every mismatch would weaken that protection and is rejected. Clarify row b to distinguish inactive-overlay rejection from active-owner corruption.

8. **P2 — empty hge save measurements are not unique layout proof.** `.cache/gen4/offline/task7_hge_save.json` records two empty party candidates, `0x90` and `0xCAB4`; the scan (`task7_hge_save.py:93-103`) cannot select one using a zero first PID. `research/offline_measurements.md:97` and `PLAN.md:88` therefore overstate FILE confirmation of `party_off`. Source projection may support `0x90`, but this particular scan is ambiguous. Keep the existing G2 populated-mon and dirty-flag cells (`PLAN.md:223`), label the empty-save measurement unresolved, and hash the exact battery files used for each FILE claim. Probe-save hashes and the separately measured AP-named save are different inputs; they must not be silently substituted. A zero dirty-flag value in an untouched PC does not locate or qualify its live mutation/persistence behavior.

9. **P2 — bind the active-faint receipt to the harness explicitly.** `lua/core/session.lua:189-196` consumes `battle_write`'s disposition, not an arbitrary returned receipt. Define a client-emitted receipt format/sink, encounter and source-cut identifiers, ordering relative to game observations and battle end, and an unconditional harness failure when it is absent or malformed. Model delivery during the overlay-load lag: `session.lua:257-260` can route to deferred when the proposed residency-based `in_battle` is still false. Determine battle setup/application state independently enough to avoid claiming deferred writes as D7. If the battle ends before application, retain truthful interruption/persistence evidence; do not declare D7 fulfilled or silently reinterpret D12's no-fallback ruling.

10. **P2 — make convergence and legacy retirement explicit exit conditions.** A reducer copy permitted by `PLAN.md:150` needs a named owner/disposition when the shared reducer arrives; a `ponytail` note alone is not a rebind plan. Preserve D1 and decide the shared seam on the actual implementation cut. Broaden the retirement grep to product code and generated outputs, including `lua/slink.lua:198`'s old client-map row, `lua/game_detect.lua:72-73`'s support message, and `tools/gen_gen4_area_map.py:1367`'s old Platinum destination. Keep the explicitly preserved Gen 5 path; do not infer a new Platinum runtime scope from a stale generator row.

## Recommended next bounded work

First update the plan, research contradictions, and requirement ledger around F1–F11. Freeze an explicit active-faint contract: identity and pointer lifetime, legal execution seam, representation, complete/partial write behavior, latency, game-observed faint, healing, and retry semantics. Complete the C0 pins/ledger prerequisites before requesting G0, or obtain an explicit revised design-only G0 signature that separates the later pins/ledger signature. After that authority is established, pure codec and pack work can proceed in parallel.

Then run the existing C1-8 mechanism experiment as the first critical physical cut, with the corrected G1 controls. It must prove singles and doubles on HG and the pinned hge build, including loss and status turns; failure blocks D12. Do not spend another wave re-proving completed C1-7 source research. Continue semantics, storage, adapter/data and shared integration only with the measured mechanism and exact leases.

Keep shared session/transport/identity/permit/presentation behavior in existing shared modules. The NDS layer owns overlay/resource mechanics; title packs and game adapters own game facts. Preserve the retirement and Manager re-admission boundaries, one reviewed shared-integration card, no master merge/push/tag without owner authority, and no release claim from local/model checks.

## Independent review and reconciliation

Three cold Sol reviewers covered architecture, battle/save behavior, and qualification/data/platform contracts. Their overlapping active-faint finding was reconciled against primary source rather than counted three times. All six battle findings were checked at cited source locations; normal-animation and poll-miss behavior remain PHYSICAL unknowns. The architecture same-title pairing finding is conditional on D9's interpretation. The acquisition inventory is incomplete as a proof, not disproved as a measured count. Required input skips are valid development OPEN cells, not implementation failures or release passes.

The qualification reviewer also independently checked this receipt and corrected four issues: F1 is an internal plan conflict, several source-line references were off, Platinum's OPEN bind cell is not a signed skip waiver, and the recommended sequence must not bypass G0 authority. Those corrections are incorporated above.

OMP source-pins `cx-3df0ff9c`, acquisition `cx-517c9f40`, and platform `cx-fe49f72d` each failed with `PEER_FAILED: server_error: Provider returned an empty response`; their rounds closed without review evidence. Live fallback `cx-77944d7a` completed; its source/FILE findings are reconciled above. Accepted six material claims (trade reachability, image selection, transition arithmetic, pin width, empty-save ambiguity, close failure); rejected the out-of-bounds label, blanket mismatch-drop proposal, and the claim that missing committed replacement columns prevent a generator supplied with the specified build exports. Hge live battle behavior remains OPEN. Failed launches are not independent review receipts.

The owner opened two additional live OMP sessions. Battle verification `cx-03467a46` and architecture/gates verification `cx-61c7e810` completed read-only and their accepted claims are incorporated above. The battle pass independently confirmed the two-copy model, crypto word index, TAG error and NPC-follower win-heal path. Its assertions that this affects virtually every ordinary save, that absent hge C names prove an absent sweep, that a mandatory party-substruct CRC step follows, and that D12 permits a checkpoint substitute were rejected or bounded. The general footer is regenerated at save time (`src/save.c:362-374,596-600`); the inspected substruct-CRC callers do not establish a SAVE_PARTY requirement. Native party-write persistence still requires the already-planned G1 row i proof. Hge's actual effect remains OPEN; `rom.ld:682` exports the vanilla `ov12_0224D7EC` and the inspected hooks do not by themselves prove its replacement.

The architecture/gates pass added phase drain ordering, composite fault handling, receipt transport and explicit retirement coverage. Its claims that an unimplemented Gen 4 verifier already passes, that mandatory missing artifact lanes may be signed away, or that D3 must expand into a Platinum emulator bring-up were rejected. Nil construction must be handled, but a crash depends on a future naive composite; it is not a reproduced defect. All three completed OMP exchanges have recorded reconciliation outcomes. All Sol and live OMP workers finished; no emulator lane or worker task remains running for this review.

The owner assigned guide editing to Claude and asked this coordinator to pause guide work; no further guide/register mutations were made after that instruction. An earlier coordinator PowerShell serialization error removed the checkpoint JSON; it was disclosed immediately and restoration is left to Claude under that owner instruction. This review receipt does not claim that restoration has occurred.

Final independent receipt check: Sol qualification reviewer found one remaining F11 JSON citation-range error; corrected to93-115. Otherwise cleared with stated SOURCE/PHYSICAL limits. No production files were edited and no test suite or emulator was run. Receipt-only commit preserves the reviewed production cut7da76fbf.
