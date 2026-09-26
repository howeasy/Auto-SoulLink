# Gen 2 planning: peer review and audit record

Every Codex round, OMP card and subagent research lane that fed the Gen 2 plan, with what
changed because of it. Message ids are the citation; the reconciled facts live in the
research notes and the plan, never only here.

Worktree `claude/gen2-planning-kickoff-a18801` at `4bf0f3b` (brief base master `bdd9a8c`).
Coordinator: Claude Fable 5.1 session df123a. Peers: Codex live thread "Gen2 Base"
(`workingDirectory` = repo root, otherwise unlisted), OMP live session "Gen2-Base" (pid 45140).

## Owner rulings (chat, 2026-09-21)

| # | Ruling | Effect on the plan |
|---|---|---|
| O-1 | "This will lead into implementation" | Destination = plan → spec → tickets; implementation in later sessions off signed gates |
| O-2 | "Include GSC. Crystal is most important but all should be done" | Gold and Silver are full admission targets in this plan, ordered after Crystal |
| O-3 | "Trash Gen2 code once we replace it. Gen1 is canonical" | Rewrite into `lua/gen2/*` mirroring `lua/gen1/*`; old Gen 2 client/profile/adapter deleted at cutover |
| O-4 | "All native feature should exist in first RC" | Native trade, START-menu panel and native sound are RC-gated, not deferred |
| O-5 | "Move to fresh upstream HEAD" | Pins: pokecrystal `7a7881d0d62e0ddbd82dcf10e7116807487ac651`, pokegold `656583c939d30f920a316177311a502dd222b57c` (ls-remote 2026-09-21); AP Crystal fork to be re-pinned at its current HEAD ("definitely behind too") |
| O-6 | "Gen2 new ledger" | `docs/gen2/gen2_requirements.md` + `tests/gen2_release_requirements.json` + `tools/verify_gen2_release.py`, separate tag |
| O-10 | "We can inject balls for tests and validation" (after R4 found no Poké Ball before the Mr. Pokémon errand) | `battle` fixtures carry bag-injected balls; the one staging exception, on the F-6 row and the limits list; the errand is not driven |
| O-11 | "GS combination allowed. Only C to C." | Pairing matrix: G↔S, G↔G, S↔S admitted; Crystal only with Crystal; closes A-8; foundation table G+S shared / C own |
| O-12 | "We can use whatever the local dump is" (Crystal revision) | Closes A-1; hashed at P1; the other revision is a recorded limit |
| O-13 | "Make peer ghost after RC. Research now." | P5 post-RC; design research lane R9 dispatched (closes A-2) |
| O-14 | "No time capsule." | Time Capsule a recorded limit; held items carried (coordinator default), mail a limit (closes A-3) |
| O-15 | "Eggs are gifts" | hatch = gift capture under `gift_daycare` (closes A-4) |
| O-16 | "One family. We can allow C to GS games if its simple to do." | one Manager family; C↔G/S admitted because one shared foundation makes it trivial; supersedes O-11's C-only clause (closes A-6, A-8) |
| O-17 | "Roamers are considered extra catches if found. Its a legend." | standalone `legend_<species>` pair, never consumes/locks the map (closes A-7 part 1) |
| O-18 | "Bug contest is a separate zone and capture and allowed." | capture zone `national_park_contest` (closes A-7 part 2) |
| O-19 | "Remember shared modules is a core of this project. So we need to use and create them wherever appropriate for re-use in future gens or games." | PLAN §5.15 shared-module extraction rule; P3b exit evidence lists extractions with Gen 1 rebound |
| O-20 | "We can cherry pick off branch. Its fine. Just need to keep an eye on if it drifts" | base cut = master + the three Gen 3 commits; drift watch recorded per gate (closes A-9) |
| O-21 | "Lets change the Suicune in Crystal to be considered legend like in GS. Other than that I think we are fine" (2026-09-23, after the C↔G/S area diff) | Crystal's Tin Tower Suicune (`TinTower1FSuicuneBattleScript`, L40) publishes `legend_245` like the G/S roamer: an extra catch, never consumes or locks `tin_tower`, so Suicune pairs uniformly across C↔C, C↔G/S and G↔S. Accepted as-is: Crystal-only Celebi (`ilex_forest` static) and Dragon's Den Dratini gift stay unpaired in cross-title runs; the Crystal-only `battle_tower` area has no acquisition; Gold/Silver `UnusedEnteiScript` not pursued |
| O-22 | "As long as everything is working do what you need to do" (2026-09-23, answering the coordinator's question on Gen 2 production admission authority from docs/gen2/reviews/P3B7_PLAN_CODEX_2026-09-23.md) | Conditional admission authority for the selected Crystal/Gold/Silver rows. Card U3 may move `data/games/gen2_{crystal,gold,silver}/admission.json` from G1 PENDING to admitted, and let `Entry.build` compose production, ONLY after that title's U1 hook proof and U2 write-window proof pass PHYSICAL with receipts and the unit/live gates stay green. A failed or missing gate keeps that title PENDING; no worker infers admission from fixture success alone. |
| O-23 | "If theyre the same just count both. Save time" (2026-09-23, answering whether Silver's O-22 write-window proof may be Gold's receipt) | Silver's U2 requirement is satisfied by the Gold write-window receipt (`tests/fixtures/gen2/receipts/gold.write_window.json`) while Silver's checkpoint rows stay byte-identical to Gold's (enforced by `lua/gen2_write_safety.lua` M.RECEIPT_TITLE + the pinned Gold sha1). Engine sites are NOT shared: each title keeps its own U1 receipt (Silver's capture rows differ). With U1 PHYSICAL on all three titles (7c08529, eac806c, 92318de), Crystal, Gold and Silver all satisfy O-22. |
| O-24 | "A" (2026-09-23, choosing among A server-side repair / B protocol ack / C leave it, for the unacked force_faint silent-loss class found by OMP review O13, cx-88d76f1f) | Server-side repair, all generations: `force_faint` stays fire-and-forget on the wire (no protocol change), but when a player's party snapshot still shows a mon whose link entry is DEAD alive (HP > 0), the server re-issues `force_faint` for that key, bounded and logged, deduped against a pending death command. Dead stays dead: a deliberately revived dead mon is re-killed too. Lives in shared `server/state.py` as game-agnostic reconcile logic (adapter guard + Gen 3 unit regression required). |
| O-25 | "Refuse AP" (2026-09-23, choosing between keeping the legacy client/adapter for Archipelago Crystal or refusing AP; options and evidence in OMP card O17 cx-81c600c6) | Archipelago Crystal (`crystal_ap`, header `AP_CRYSTAL`) is REFUSED, not supported. It cannot join the new client: every AP seed is a different ROM, admission is pinned-hash with `unknown_hash_policy: REFUSE`, no ROM-side fork source exists, and `Gen2GSCAdapter` refuses the spelling. The refusal must be loud in both the launcher (`lua/slink.lua` names the detected AP cartridge) and the server (a `Crystal (AP)` hello is refused as an unrouted rom_type). This unblocks the P3b.8 REMOVE of the legacy Gen 2 client, adapter, data pack and their tests/tooling. Supersedes the O-8 "defer AP post-RC" stance: AP is out, not deferred. |
| O-26 | "Recorded limit" (2026-09-23, choosing how to prove the `shiny_bonus` duo scenario, D-5; options in docs/gen2/reviews/DUO_SCENARIO_ROADMAP_2026-09-23.md row 18) | The shiny-bonus pairing is NOT proven physically. Natural shinies are 1/8192 and the harness never writes DVs; the only fixed shiny (Crystal's Lake of Rage red Gyarados) would need a long scripted fixture plus a new static-acquisition site. D-5 stays SOURCE/MODEL-proven (the server `bonus_keys` rule and client shiny derivation unit tests) and ships as a documented release limit. |
| O-27 | "Accept all" (2026-09-23, the five P4 decisions in docs/gen2/reviews/P4_PLAN_2026-09-23.md, commit 204c899a) | **D1 (ticket 14)** mailbox = unused WRAM0 at Crystal `$CFD8-$CFFF` (40 B) / Gold+Silver `$C1D9-$C1FF` (39 B), reserved as a fixed SECTION in the patched build; lifecycle cleared by Init (power-on/soft reset), not by New Game (the service rewrites its header), never saved, never touched by link code; writer exclusion by the source census (card P4.1b) with a live write-watch as tripwire only. **D2 (ticket 15)** native trade = the Gen 1 shape: the Trade Center receptionist becomes SLINK TRADE, lease-driven through the mailbox, cartridge-native menus/animations and the real commit chain (AddTempmonToParty -> EvolvePokemon -> SaveAfterLinkTrade); no Gen 2 branch in the server trade FSM. **D3** a mail holder or an item the receiver cannot hold is refused before commit, never stripped. **D4** pairing: patched<->patched and clean<->clean only (the pureRGB rule), adapter data only. **D5 (ticket 16)** native sound from one main-thread DelayFrame bridge, verified per context; a GetJoypad site only if a context misses its deadline. Coordinator decisions under this ruling: build as a source overlay on the pinned pret checkout (D6), and extract the trade-lease framing to a shared `lua/gb_trade_lease.lua` (plan amendment). |
| O-28 | "Replace EXIT (Recommended)" (2026-09-23, the P4.1e START-menu layout) | A 9th START row overflows the 18-row tilemap (bottom = top+2n+1 = 19; no native compact/scroll mode, Codex source check). SLINK takes the visible EXIT row in `StartMenu.SetUpMenuItems` (both repos); the EXIT index/table stays, SLINK is appended as index 9; B/START still close the menu. Rejected: single-spaced compact rows (restyle + cursor risk) and a conditional row (SLINK vanishes in a full menu and the contest). |
| O-29 | "Beautiful. Do it" (2026-09-23, easter egg) | Soul Link phone calls on the SLink-patched Gen 2 ROMs via the native special-call path (`specialphonecall` / `CheckSpecialPhoneCall`, C engine/phone/phone.asm:242-287): the server triggers, Lua requests through a spare mailbox byte, the patch service sets the pending call. First scope 2-3 fixed-text calls (partner death, dead zone, first link). Card P4.5: plan now (P4.5a), asm after the P4.1g live panel gate. Clean ROMs never ring. Flavour only; never blocks the release. |
| O-30 | "That's not how Gen 1 works anymore. Needs to be fixed." (2026-09-23, linked death while in battle) | Gen 2 must kill the linked mon IN battle like Gen 1 does now (lua/gen1/client.lua on_battle_loop_head; lua/gen1/writes.lua W-2 faint_active_battler: battle HP 0 + CANNOT_MOVE + party mirror at the battle-loop head, active_faint_guard, bench faint at the loop head). The Gen 2 "deferred to battle end" path is superseded. Card gen2-inbattle-faint: source facts, evolution-escape fallback, client/writes port, U1 battle_loop_head site + U2 in-battle write kind proven per title, then a duo with the linked mon active. Owner addition, same day: "All faints should be able to happen in battle." -- every death command (partner death, clause rejection, O-24 repair, identity_lost) lands in battle on the active battler and the bench; link-cable battles are the only principled exception pending facts; any other exclusion needs an owner ruling; Gen 1's remaining battle-end holds are reported for the same rule. |
| O-31 | "Test-only setup" (2026-09-24, P4.3e trade specimens) | The trade-evolution and D3 refusal (held mail / item the partner cannot hold) cases are proven PHYSICALLY with a DISCLOSED harness-only write, a narrow exception to the no-staging rule like O-10: the harness plants only the minimum state (e.g. the wild encounter species before a normal catch, or the held-item byte of the offered linked mon), records every write (address, before/after bytes, frame) in the receipt, and the rest of the run is normal inputs and native code. Never used for any other scenario; production data/source unchanged. |
| O-32 | "Lets match gen1. Death should be immediate if possible." (2026-09-24, O-30 review MINOR-4) | A Gen 2 bench (non-active) linked mon's death lands on receipt mid-battle, like Gen 1's battle_bench write, instead of waiting for the battle_hold. Needs a new receipt-time Gen 2 write kind proven PHYSICALLY (U2) per title before production uses it; until then the battle_hold path stays. Only where it is safe (never mid party-menu/switch copy; link battles excluded per O-30). Card gen2-bench-write. |
| O-33 | "We dont need to test all the way to violet city. Do synth work as you need to. Lets get this finished. Emulator runs are taking way too long" (2026-09-24) | Supersedes the no-staging rule (O-10/O-31 exceptions) for SETUP: a worker may build synthetic fixtures (save/SRAM images or states constructed by tools from pinned decomp facts: party/box contents, levels/exp, items, event flags, map position, RTC offset, egg step counters, wSavedAtLeastOnce) to skip long scripted walks and story progress. The behaviour UNDER TEST must still run natively (normal scripted inputs, native game code, production client/server). Every receipt that used a synthetic setup records it (SYNTH disclosure: builder, fields changed, source facts), like O-31 HARNESS_WRITE; oracles never treat synthetic fields as evidence. Goal: cut emulator wall time (no Violet City walk, no clock windows). |
| O-34 | "Allow and test" (2026-09-24, AskUserQuestion: native trades Crystal<->Gold/Silver) | O-16 wins over the round-2 Q10 wording: native trades are allowed on C<->C, G<->S AND C<->G/S, and the full trade matrix is proven on all three pairings. Reverses the coordinator's same-day Q10 reading (6e29f986, bad46a70): the C-G trade rows and runner registration come back. |
| O-35 | "Yes, kill the partner" (2026-09-24, AskUserQuestion: PC release of a linked mon) | Releasing a linked mon from the PC counts as losing it: the server kills and memorializes its soul-linked partner like a faint (generation-neutral server rule; Gen 1 + Gen 2 proven; closes the S-6 gap). pc_ops oracles flip from release=unpropagated to partner dead. |
| O-36 | "As high as we need to" (2026-09-24, emulation speed for normal runs) | Supersedes the standing "route runs at 300%" rule: route, setup and duo runs may run at any speed up to unthrottled, whatever cuts wall time, provided the harness bounds are frame-based (not wall-clock) and the result is unchanged. Qualification runs stay at 100% unless separately ruled. Part of the emulator-time initiative (preflight cache, parallel lanes, O-33 synthetic starts). |
| O-30a | Owner picks (2026-09-23, AskUserQuestion on the O-30 exclusions): Contest = "Kill on return (Recommended)"; Battle Tower = "Kill now + re-kill (Recommended)" | Clarifies O-30's exclusions, recorded here per review NIT-8 (67687183). Bug-Catching Contest: the party is dropped off during the contest, so a death for a hidden mon is deferred and lands on ContestReturnMons. Battle Tower: kill in battle, then re-zero; the tower reloads + heals the party between its up-to-7 battles, so the re-zero must re-apply at each battle hold, not only at the overworld checkpoint (review MAJOR-2, card FAINT-FIX). The tutorial (catching demo) battle needs no exclusion (review verified). Link-cable battles remain the only principled exception. |
| O-7 | Matt Pocock skills setup: local-markdown tracker under `docs/<effort>/`, default triage labels, Agent-skills block in root `CLAUDE.md` under a one-off exception to rule 0.7 | `docs/agents/{issue-tracker,triage-labels,domain}.md` written |

Round 2 (chat, 2026-09-21): Q3 fixtures "Do whatever is best" → town + Route 29 battle from scripted
play for all three titles (ticket 07); Q8 Archipelago "investigated and fully documented, post-RC"
(ticket 08); Q9 peer ghost "if possible, implement" (ticket 17, gate P5); Q10 "G to S allowed. C to C
only" (ticket 09). Owner also supplied the AP pin link (gerbiljames/Archipelago-Crystal 6.0.0-rc.1).

## Codex "Gen2 Base"

### cx-3569f8d9 — FACT_CHECK gen2-C1 (round 1, 2026-09-21), six premises

Sources: pokecrystal@3438c70, pokegold@e78abb8 (the cached shas; the pin moved to HEAD
afterwards and the wram delta is confined to the `wLinkData` union, same 1300-byte size,
so the cited symbol addresses are unaffected; file:line numbers for `ram/wram.asm` past
line 953 (Crystal) / 492 (Gold) shift by +54 at HEAD and must be re-cited).

| # | Premise (project claim) | Verdict | What changes in the plan |
|---|---|---|---|
| 1 | New Bark west exit script-locked until Elm's starter (`docs/gen1_gen2_runtime_checks.md:205-206`) | CONFIRMED: scene-conditioned coordinate event `SCENE_NEWBARKTOWN_TEACHER_STOPS_YOU` at (1,8)/(1,9), `maps/NewBarkTown.asm:6-9,304-305`; cleared by `ElmDirectionsScript` (`maps/ElmsLab.asm:274-277`); only connections are west Route 29 and east Route 27 (`data/maps/attributes.asm:119-121`), east edge is water (`johto_collision.asm:6,89`), Surf needs Fog Badge (`engine/events/overworld.asm:505-511`) | The lock is SOURCE, not a comment. Any grass fixture must run Elm's script; the plan states it from these lines |
| 2 | Boxes sit outside the save checksum, so a Box 14 memorial survives without checksum work (`:193-198`) | CONFIRMED for the checksum (Crystal primary sums bank 1 `[sGameData,sGameDataEnd)`, `engine/menus/save.asm:526-537`; backup `:583-594`; G/S backup sums five ranges incl. bank 3 `sBackupCurMapData`, pokegold `save.asm:495-535`); no per-box checksum (`macros/ram.asm:102-123`). REFUTED as a survival guarantee: `_SaveGameData` → `SaveBox` copies the active `sBox` over the `wCurBox` backing slot (`save.asm:266-281, 521-524, 874-973`), and `EraseBoxes` clears all boxes (`:1038-1077`) | Memorial write must never target the ACTIVE box (or must be re-asserted after the game's own SaveBox), and the memorial gate needs a negative control across a SAVE with Box 14 active. Mirrors Gen 1 W-5 / the `EmptyAllSRAMBoxes` hazard |
| 3 | `MEMORIAL_BOX_INDEX` 13 = flat CartRAM `0x79E0` | CONFIRMED by derivation: `sBox14 = $A000 + 6*$450 = $B9E0` in bank 3, flat `3*$2000 + $19E0 = $79E0` (`ram/sram.asm:177-193`, `layout.link:375-378`, `BOX_LENGTH=$450` `constants/pokemon_data_constants.asm:141`) | Value kept as a hypothesis until R2 confirms BizHawk's CartRAM is bank-linear (the formula is assumed, not inspected) |
| 4 | Gold/Silver share WRAM/SRAM; only trainer data differs | Layout sharing CONFIRMED (`pokegold ram.asm:5-6`, no `_GOLD/_SILVER` branches in `ram/*.asm`; `Makefile:37-42,132-137,198-199`). "Only trainer data" REFUTED: wild tables differ (`data/wild/johto_grass.asm:341-364`) | Gold and Silver need separate encounter/area packs and separate admission rows; one profile, two data packs |
| 5 | Does Gen 2 have an `EmptyAllSRAMBoxes`-like hazard? | CONFIRMED: `ErasePreviousSave` → `EraseBoxes` (`save.asm:360-366`), reached from `AskOverwriteSaveFile` `.erase` (`:181-199`) and `HallOfFame_InitSaveIfNeeded` when `wSavedAtLeastOnce`==0 (`:470-475`); `TryLoadSaveFile` corrupt path only prints an error (`:596-640`) | The write checkpoint must refuse memorial/box writes before the first SAVE (`wSavedAtLeastOnce`) and around New Game overwrite; mirrors Gen 1's first-save rule |
| 6 | Where is whiteout decided; HealParty order | CONFIRMED: `UpdateFaintedPlayerMon` adds LOSE to `wBattleResult` (`engine/battle/core.asm:2656-2688`), `LostBattle` only when no party HP (`:2607-2619`, `CheckPlayerPartyForFitMon :3633-3648`); `Script_reloadmapafterbattle` → `Script_BattleWhiteout` (`engine/overworld/scripting.asm:1174-1184`); `Script_Whiteout` calls `HealParty` at `engine/events/whiteout.asm:14` BEFORE `WarpToSpawnPoint :20`. A transient LOSE is not a whiteout | Faint-time party bytes must be captured at the faint site, not after; whiteout site = `Script_Whiteout` entry (pre-HealParty), same shape as Gen 1 S-4 |

Reconciliation: accepted 6/6; nothing rejected. Coordinator spot-checks pending against the
HEAD clones (items 2 and 6 line numbers) before the values enter `gen2_requirements.md`.

### cx-8172d76c — DELEGATE gen2-C2, engine-site / signal assumption audit (round 1, 2026-09-21)

Output: `docs/gen2/research/codex_engine_site_audit.md` (146 lines). Accepted. Findings: (1) a
full-party (boxed) catch never emits `capture` (`gen2_crystal_client.lua:680-696`); (2) the
withdrawal debounce cannot complete on ordinary stable reappearance (`:936-977`); (3) the egg marker
is read from the record instead of the species list (`memory_gb.lua:353-355` vs
`move_mon.asm:1175-1188`), and Mr. Pokemon's Mystery Egg is a key item, not `giveegg`; (4) safe /
reset / identity are heuristics; (5) several comments contradict code. PROFILE_SYMBOL_CHECK 60/60.
What changed: the three defects are recorded as rewrite reasons (PLAN §1); the candidate site
table is the ticket-12 input; "script-bytecode labels are not bus_exec sites" adopted (PLAN §5.3).

### cx-02b0f4b5 — DELEGATE gen2-C3, checkpoint predicate + link-trade routine (round 1, DONE)

Output: `docs/gen2/research/codex_checkpoint_and_linktrade.md` (168 lines). Coordinator verified
four claims against the HEAD clones (the `CheckAPressOW` anchor at `events.asm:495`, the
`AddTempmonToParty:1994` → `EvolvePokemon:1998` → `SaveAfterLinkTrade:2044` sequence, the `Joypad`
`reti` stub, menus reaching `DelayFrame`). Outcome recorded: accepted 4, open 3 (strict-predicate
liveness, universal UI-open byte, host save durability → P3b live gate). What changed: PLAN §5.4
(anchor), §5.12 (sound sites collapse to `DelayFrame`; trade commit sequence is SOURCE); tickets
10 and 13 resolved.

### cx-2a7de2fa / cx-3c7fffe9 — REVIEW gen2-C8 rounds 2-3, binding plan (`8e720b5`, `2e7f23d`)

Round 2: 5 of 7 blockers CLOSED, 7 and N2 PARTIAL (validator filename split across the two
documents; P6.3 closure not applicability-aware, N-3 demanded at the first G6). Fixed by the
coordinator at 2e7f23d (one `tools/coverage_map.py`; P6.3 applicability first, per-gate count, N-3
post-RC). Round 3: both CLOSED, **APPROVE for /to-spec + /to-tickets consumption**. Not
implementation, gate or release approval.

### cx-bb137561 — REVIEW gen2-C8, closure of the binding-plan rewrite (`874b2b2`)

REJECT with 7 blockers (7 leases + validator consumer, 11 shim, 12 P4 client lease, 15 R-1/R-3
acceptance, N1 active-box scope, N2 SOURCE-only closure, N3 REMOVE vs REPLACE); 11 of 18 prior
findings CLOSED, structure verified (34 substeps, 53 ids). Accepted 7/7. Plan-side amendments by the
coordinator (this commit); binding-plan amendments by the D4 worker, round 2; Codex C8 round 2 to
close.

### cx-4cf35727 follow-up: cx-abfd0b86 — card gen2-A4, citation resolver over the two annexes (DONE)

`DONE gen2-A4: 456 citations, 452 resolve, 6 real defects` (four distinct: three more
`SWEEP docs/shared_runtime.md` prefixes, two BizHawk source cites without a root, the ambiguous bare
`core.asm` in the comparison; plus the `NewBarkTown.asm:8` → `:8-9` near-miss). Accepted 6/6; the
binding-plan fixes applied by the coordinator, the comparison's two by the D6 card.

### cx-10a9cf49 — FACT_CHECK gen2-C10, GEN2_STANDARD_COMPARISON.md cold check (2026-09-21)

21 items: 17 WRONG cells (sound ids from the wrong constants; "every symbol in WRAM bank 1"; cached
stats as the only withdrawal path; Gen 1 waits for the game to initialise boxes; "no identity";
species clause wholly inert; "every sync path reports back"; four inflated Gen 1 grade cells F-3/D-7/
S-5+D-10/T-3+T-4; wrong trainer-start site; 12 lanes; 189 rows; same-cartridge pairing as a Gen 2
exclusive; the MODEL tally), 3 OVERSTATED, 1 STALE group, 3 CONFIRMED groups. Accepted 21/21;
corrections applied by an Opus card (gen2-D6) with the citations as its brief; a separate
"historical run" column replaces the mixed P label.

### cx-2c3f2d06 — FACT_CHECK gen2-C9, GEN1_STANDARD_DIGEST.md cold check (2026-09-21)

22 verdicts: 14 groups CONFIRMED (contract table, all 13 stages' grades and limits, 18 scenario names,
19 lanes, 14 saves), 6 WRONG (SRAM initialisation refusal; universal two-frame settling; recalculation
only on level change; live-new-gates covering every fixture; legacy directory convention presented as
current; 112 receipts vs 119 tracked), 2 OVERSTATED (interruption never loses a mon; retry summary
complete). Accepted 8/8; corrections applied by a Sonnet card (gen2-D5) with the citations as its brief.
Standing note adopted: distinguish a limit described as MODEL, an M cell with a receipt, and a P
subclause closed.

### cx-ec7d3f33 — REVIEW gen2-C7, binding plan §5 vs PLAN §6/§5.15 (2026-09-21)

18 contradictions (stale Step 0 source of truth; Gold/Silver deferred past G2; ROM reader ownership;
no fixture step; both Crystal revisions admitted; checkpoint file outside the lease; explicit ban on the
shared permit vs 5.15; Step 4 mixing P2 packs with P3b physical gates; script-label whiteout hook; stale
pairing refusal; unleased launcher + weak exits; native steps without ticket prerequisites; runner last
and no shared core; ghost before release; requirement rows without exits; deliverables without rows;
held items droppable; egg/roamer/contest rulings absent). Accepted 18/18. Plan-side fixes applied by
the coordinator (PLAN §5.9 one foundation, P3a falsifier, P5 after G6, P6 prerequisite, P3b fixture
prerequisite; requirements S-8/S-9g/S-10g/C-6g/T-3/pins/exclusions). Binding plan §5 rewrite delegated
to an Opus card (gen2-D4) with the 18 findings as its brief; Codex C8 re-checks the result.

### cx-116c6ad2 — REVIEW gen2-C6, closure of C5 on §5.15 (`7f554f5`)

APPROVE §5.15 as worded; 11/11 CLOSED; no new issues. Note kept: each row's lane list is read with the
header's affected-artifact/lane requirement, not as an exemption (Gen 3 lanes apply when a card rebinds Gen 3).

### cx-8ce81ab4 — ADVERSARIAL_REVIEW gen2-C5, shared-module extraction rule (2026-09-21)

Verdict: REJECT the wording, support the priority. 11 findings (per-candidate: registry EXTRACT with
platform binding; write gate EXTRACT with injected policies; checkpoint EXTRACT-GB-ONLY; `Entry.admit`
framework EXTRACT, policy per game; box writer KEEP-PER-GEN with two small pieces; panel EXTRACT-GB-ONLY
versioned; codec/qualifier orchestration EXTRACT; coverage validator EXTRACT; duo-oracle orchestration
missing → EXTRACT; harness bind-not-clone; guard clause). Accepted 11/11; §5.15 rewritten as 5.15a-j;
binding plan §3/§6 amended by coordinator note. Codex also corrected a stale path: the scripted-play
driver is `lua/tests/gen1_scripted_play.lua`, not `gen1_scripted_new_game.lua` (which does not exist
at this cut; the R4 brief had used the wrong name, the note itself cites nothing from it).

### cx-51f03e2d — FACT_CHECK gen2-C4, pokegold check of R7/R8 (2026-09-21)

Six verdicts: 1 MISLEADING, 2 MISLEADING, 3 FALSE (objects ARE saved), 4 VERIFIED (cable routine
map for Gold), 5 MISLEADING (Time Capsule converts items), 6 FALSE (notes not transferable to Gold
unqualified). Accepted 6/6; coordinator spot-checked `save.asm:498-508` and `wram.asm:2993/3038/3049/3378`
ranges. What changed: correction headers on `sound_sites_and_peer_ghost.md` and `native_trade_entry.md`,
tickets 15/16/17 amended, PLAN §5.12 rewritten, R9 steered mid-flight.

### cx-ea796926 — ADVERSARIAL_REVIEW gen2-CR3, round 3 on rev 3 (`7e76dcd`, 2026-09-21)

Verdict: **APPROVE for owner presentation** (explicitly not implementation, gate or release
approval). Blocking 4, 7a/b/c, 9: CLOSED. Follow-ups: 6, N1, N2 closed; 3 and the "six files"
heading were wording residues; new N3: the `sScratch` SRAM fallback I had suggested is refuted by
the frozen survey and pret writer sites. Reconciliation: accepted 3/3, applied in rev 3.1 (this
commit). Codex's standing notes adopted: the imported runner's failure behaviour (skips/xfail/
deselect/error/`--quick` never yield release success) is verified at P2; A-8 unresolved does not
block presentation; the negative WRAM survey is a feasibility risk whose gate must stop, not a
reason to reopen O-4.

### cx-2350bfd7 — ADVERSARIAL_REVIEW gen2-CR2, round 2 on rev 2 (`f1a69f3`, 2026-09-21)

Verdict: **REJECT rev 2**, blocking findings 4, 7, 9; closure assessment of round 1: 1/2/3/5/8
CLOSED, 4/6/7/9 PARTIAL; two new findings N1, N2. Reconciliation: accepted 11/11 (coordinator
verified `910dbdd` exists on the Gen 3 branch and carries `tools/release_lanes.py` + the
`verify_gen1_release.py` rewrite). Applied in rev 3: (4) G1 freezes BUILT/ADMITTED hashes and
PLANNED overlay/ghost slots without hashes; (7a) base cut = master + `80261f3` + `959c578` +
`910dbdd`, Gen 1 regression lanes green, conformance helpers not assumed; (7b) registry rows +
tests in the P3a lease; (7c) packaging manifest + extracted-bundle boot test in P3b before the
cutover census; (9) A-8 must be answered at G0, same-title G/S pairs UNADMITTED until then,
title-cased aliases covered; (3) G2 = zero UNMAPPED; (6) N-2 wording; (N1) identical-full-key
falsifier + same-OT control; (N2) B-17 wording; stale "six files"/"two saves" aligned. Codex's
disagreement notes adopted verbatim: the free-WRAM survey does not reopen O-4; a failed
feasibility gate stops or escalates, never borrows a cleared region.

### cx-cbcd55de — ADVERSARIAL_REVIEW gen2-CR1 of PLAN.md rev 1 (round 1, 2026-09-21)

Verdict: **REJECT rev 1** (source direction sound; evidence contracts too weak). Nine findings, 19
citation spot-checks (all supported except the sound inference). Reconciliation: **accepted 9/9**,
rejected 0. Amendments applied in rev 2 (PLAN §12 lists them): G3 relabelled as an internal
milestone with the first RC at G4 (O-4 kept); played `_ot2` Crystal fixtures as the A/B identities
and wrong-save control, ticket 22 in the P3b prerequisites, O-10 ball injection instead of the
errand; a coverage map (`docs/gen2/gen2_coverage_map.md`) as a P2 deliverable with zero-UNCOVERED
blocking G2, C-0/C-4/D-13 marked MODEL-only by design, S-3 reworded (box insertion independent of
`BATTLERESULT_BOX_FULL`); an admitted-artifact matrix frozen at G1 with a reopen rule for every
ROM/patch/site change; the save contract (both layouts, five G/S backup spans, recovery controls,
success-only witness; `SaveAfterLinkTrade` never substitutes for a scenario save); the sound
"collapses to DelayFrame" inference withdrawn; ROM readers and the runner skeleton moved to P2,
`tests/unit/test_protocol_schema.py` path fixed, §6.1 gate ledger added, leases refined; cutover
census + frozen bundle + rollback section; pairing hook pinned from the Gen 3 lane (owner: "Work
with Gen3 if it has a shared module we need"), full symmetric matrix, A-8 for G↔G/S↔S. Codex's
own outcome: no further round opened by the reviewer; the coordinator requests a bounded round 2 on
rev 2.

## OMP "Gen2-Base"

### cx-1deb32f4 — card gen2-A1, profile address vs pret symbol audit (DONE 2026-09-21)

Output: `docs/gen2/research/omp_address_audit.md`. `DONE gen2-A1: 179 fields, 102 covered by
verifier, 2 mismatches, 77 uncovered`. Findings accepted 5/5: (1) `crystal_ap` is never reached by
`tools/verify_profile_addresses.py` (it sits outside `M.PROFILES`, `gen2_crystal.lua:521`); (2)
`data/pret_syms.json` has no `rom_sha1`; (3) `data/pret_rom_syms.json` covers Gen 1 only; (4) dead
`SFX_DISPATCH_ADDR -> wMusicID` mapping (profile value nil); (5) the 2 mismatches are the documented
AP fork overrides. Reconciliation: consistent with R1's HEAD rebuild (zero address changes). What
changed: PLAN §5.1 (Gen 2 stops reading the unpinned JSON) and §5.9 (AP not admitted in the RC).

### cx-4cf35727 — card gen2-A3, citation resolver over PLAN.md + gen2_requirements.md at `f1a69f3` (DONE)

Output: `docs/gen2/research/omp_citation_audit.md`. `DONE gen2-A3: 63 citations, 60 resolve, 22
keyword at cited line, 22 misses` (the keyword column is rule noise by OMP's own reading; the real
defects are 3 unresolved + 1 ambiguous + 2 wording). Accepted 4/4 fixes: `SWEEP docs/shared_runtime.md:59`
→ `docs/shared_runtime.md:59` (the file is in THIS worktree; the SWEEP prefix was wrong), `docs/gen1_requirements.md:161-190`
→ `:161-189`, `core.asm:2656-2688` → `engine/battle/core.asm:2656-2688`, `red_town_ot2` → `town_ot2`.
`link.asm:1998` is `EvolvePokemon` as the sentence says (keyword rule picked the previous identifier).

### cx-6660f9e1 — card gen2-A2, symbol declaration lines + routine labels (DONE)

Output: `docs/gen2/research/omp_symbol_lines.md`. `DONE gen2-A2: 54/60 symbols found, 6 not found`.
Accepted 10/10 findings; coordinator spot-check: the `ElmDirectionsScript` release path matches
Codex `cx-3569f8d9` item 1. What changed: OPEN_QUESTIONS B-15/B-17/B-18 resolved; four Gen 1 symbol
names that the old Gen 2 profile comments carry (`wNewSoundID`, `wChannelSoundIDs`, `sPartyCount`,
`sPartyMons`) are recorded as non-existent in Gen 2 (a rule-0.8 confirmation); `wGameTimerPaused`
is the real label.

## Gen 3 lane (cross-session, 2026-09-21)

Owner ruling: "Work with Gen3 if it has a shared module we need." Reply from the Gen 3 session:
shared pairing change = `80261f3` + `959c578` on `claude/gen3-migration-planning-5d8e45`, G3a
signed; not merged; cherry-picks cleanly (owner's call, A-9). Reuse list adopted into PLAN §5.9/§6:
foundation table for Crystal vs Gold/Silver, `tools/release_lanes.py` as the runner core,
`tests/unit/conformance_map.py` + `--wire-log` for protocol characterisation, `lua/sfx_arbiter.lua`
(already on master `e9faff0`), the Gen 3 instrument rules (no per-frame console.log, ≤ ~20 exec
hooks per probe).

## Subagent research lanes (Sonnet)

| id | note | status |
|---|---|---|
| gen2-R1 | `research/pret_gen2_symbols.md` (re-pinned to HEAD mid-flight; scratch RGBDS build: zero address changes) | done, 14 open questions folded into OPEN_QUESTIONS B-13..B-18 |
| gen2-R2 | `research/bizhawk_gambatte_gbc.md`, `research/rom_hashes.md` | done, 8 open questions (B-8..B-10, A-1) |
| gen2-R3 | `research/archipelago_crystal.md` (pinned to 6.0.0-rc.1 per the owner) | done, 8 open questions (B-19) |
| gen2-D1 | `GEN1_STANDARD_DIGEST.md` (Opus) | running |
| gen2-D2 | `GEN2_STANDARD_COMPARISON.md` (Opus) | running |
| gen2-D3 | `GEN2_BINDING_PLAN.md` (Opus) | done, 496 lines; load-bearing finding: the FRAMEWORK.md spine is on `gen1/rc`, not master (coordinator verified by `ls`); Gen 2 binds master's shared set (PLAN §2) |
| gen2-R4 | `research/stat_control_and_fixture_budget.md` (Sonnet; tickets 20, 22) | done; coordinator verified `ElmsLab.asm:498-508`, `marts.asm:40-44`, `MrPokemonsHouse.asm:127`; led to O-10 |
| gen2-R6 | `research/free_wram_survey.md` (Sonnet; ticket 14, WRAM half) | done; NEGATIVE: no provably free WRAM from source; needs the P1 linker map; recorded as the plan's largest risk (PLAN §11) |
| gen2-R9 | `research/peer_ghost_design.md` (Sonnet; ticket 17 design, post-RC) | done, 331 lines; incorporates the C4 corrections, re-verified on both clones; 7 open questions |
| gen2-R8 | `research/native_trade_entry.md` (Sonnet; ticket 15) | done, 312 lines; coordinator verified the four receptionist specials and both animation predefs exist |
| gen2-R7 | `research/sound_sites_and_peer_ghost.md` (Sonnet; tickets 16, 17) | done, 313 lines; coordinator verified `GetJoypad` site, `NUM_OBJECT_STRUCTS`, `NOCLIP_OBJS`, `wOverworldDelay`; pokecrystal only |
| gen2-R5 | `research/gamedb_and_encounters.md` (Sonnet; tickets 18, 21) | done, 346 lines; gamedb lines for the four sha1s quoted (all GBC); wild-file inventory with `_GOLD/_SILVER` splits; 9 open questions |

## Skills that actually ran

`/ask-matt` (owner-invoked; routed wayfinder → to-spec → to-tickets), `/setup-matt-pocock-skills`
(owner-invoked; outputs above), `/wayfinder` (owner-invoked; charting in progress),
`/grilling` + `/domain-modeling` (model-invoked, round 1 done), `/research` (model-invoked,
three lanes). `/to-spec`, `/to-tickets`, `/grill-with-docs`, `/codebase-design`: not yet.
