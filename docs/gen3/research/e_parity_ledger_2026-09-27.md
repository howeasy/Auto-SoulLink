# E-PARITY ledger — 2026-09-27

This records the original peer reply for `cx-d481539d`, sent at 11:51:56Z,
plus a dated update below. The original references and verdicts are a historical
snapshot of `21a7a614` through `b828c656`; they are not current-cut claims.
The reply was recovered from this peer's local conversation receipt and was
not previously committed.

## Original reply (historical)

SUMMARY
E-PARITY is complete, read-only: no edits, commits, tests, builds or emulator runs. I started at integration 21a7a614d773b7c0c303a2c8ab0261238e5cd5ec and checked the subsequent delta to b828c656171e565816597456a7c75bc8f7dddee9; that delta adds the RR evolution SYNTH carrier and journal ignores, not a passing RR evolution receipt. The core FR/LG/RR/Emerald loop has live evidence, but companion parity, explicit rule gates, web UI qualification and expansion runtime still have gaps.

FINDINGS
Scope: FR/LG US 1.0, RR 4.1 (companion where required), Emerald US/EU English rev 0, and expansion reference build 28877d73 only. SHIPPED below means implemented plus a located passing feature-relevant duo/live row, at the cited historical cut; it is NOT a new release signature or current-HEAD recut. SOURCE-ONLY means the requested feature lacks its qualifying live row; narrower partial evidence is called out. MISSING means no production title implementation/binding, including an unimplemented title-specific binding behind generic helpers. HELD means an explicit current admission/readiness hold. OWNER-RULED OUT is RC scope only.

C*/L*/O* references are expanded immediately after the single table. Every SHIPPED cell has both a code reference and a live reference. Confidence is high for the explicit code/admission gates and positive receipts, medium for negative evidence searches (SOURCE-ONLY does not assert that no uncommitted receipt exists).

| Player-facing feature | FR | LG | RR | Emerald | Expansion |
|---|---|---|---|---|---|
| Native SOULLINK info panel | MISSING C4 | MISSING C4 | SHIPPED C4/Lpanel | MISSING C4 | MISSING C4/X |
| Native Sounds option / companion sound parity | SOURCE-ONLY C5 | SOURCE-ONLY C5 | SHIPPED C5/Lsound | SOURCE-ONLY C5 | MISSING C5/X |
| Ordinary linked faint propagation | SHIPPED C1/F14 | SHIPPED C1/F14,F24 | SHIPPED C1/R6 | SHIPPED C1/E14 | HELD X |
| Prompt active linked faint in battle, singles | SHIPPED C1/F23 | SHIPPED C1/F24 | SHIPPED C1/R7 | SHIPPED C1/E19 | HELD X |
| Explode Mode | MISSING C6 | MISSING C6 | SHIPPED C6/R14 | MISSING C6 | MISSING C6/X |
| Rival Team Swap | MISSING C7 | MISSING C7 | SHIPPED C7/R16 | MISSING C7 | MISSING C7/X |
| Soul Link phone / Match Call contact | MISSING C8 | MISSING C8 | MISSING C8 | SOURCE-ONLY C8 | MISSING C8/X |
| Soul Link PC-trade NPC: native trade/evolution/save/recovery | HELD T | HELD T | HELD T | HELD T | MISSING T/X |
| Ordinary cartridge NPC trade tracking | SHIPPED C9/LnpcF | SHIPPED C9/LnpcL | SOURCE-ONLY C9 | SHIPPED C9/LnpcE | HELD X |
| Trainer name/class/battle panel | SOURCE-ONLY U | SOURCE-ONLY U | SOURCE-ONLY U | SOURCE-ONLY U | SOURCE-ONLY UX |
| Upcoming Key Trainers UI | SOURCE-ONLY U | SOURCE-ONLY U | SOURCE-ONLY U | SOURCE-ONLY U | SOURCE-ONLY UX |
| Web calc Prep and trainer-to-Prep navigation | SOURCE-ONLY U | SOURCE-ONLY U | SOURCE-ONLY U | SOURCE-ONLY U | SOURCE-ONLY UX |
| Web damage-calc integration | SOURCE-ONLY U | SOURCE-ONLY U | SOURCE-ONLY U | SOURCE-ONLY U | SOURCE-ONLY UX |
| Allowed randomized ROM admission / per-ROM table projections | SHIPPED C10/LrandF | SHIPPED C10/LrandF | MISSING C10 | SHIPPED C10/LrandE | MISSING C10/X |
| Natural randomized capture/link/save path | SHIPPED C10/LrandLink | SHIPPED C10/LrandLink | MISSING C10 | SOURCE-ONLY C10 | MISSING C10/X |
| Overworld peer presence / ghost | OWNER-RULED OUT O1 | OWNER-RULED OUT O1 | OWNER-RULED OUT O1 | OWNER-RULED OUT O2 | MISSING X/O? |
| Natural encounter capture and area pairing | SHIPPED C1/F15 | SHIPPED C1/F15 | SHIPPED C1/R11 | SHIPPED C1/E17 | HELD X |
| Gifts/statics and fixed-gift clause behavior | SOURCE-ONLY C1/C3 | SOURCE-ONLY C1/C3 | SOURCE-ONLY C1/C3 | SOURCE-ONLY C1/C3 | HELD X |
| Party/PC box synchronization | SHIPPED C2/F16 | SHIPPED C2/F16 | SHIPPED C2/R9 | SHIPPED C2/E18 | HELD X |
| Memorial placement after death | SHIPPED C2/F14 | SHIPPED C2/F14 | SHIPPED C2/R6 | SHIPPED C2/E14 | HELD X |
| Whiteout / rebuild / last-pair game-over | SHIPPED C1/F19 | SHIPPED C1/F20 | SHIPPED C1/R10 | SHIPPED C1/E20 | HELD X |
| Field-poison faint tracking | SHIPPED C9/LpoisonF | SHIPPED C9/LpoisonL | MISSING C9p | SHIPPED C9/LpoisonE | HELD X |
| Ordinary evolution tracking | SHIPPED C9/LevoF | SHIPPED C9/LevoL | SOURCE-ONLY C9 | SHIPPED C9/LevoE | HELD X |
| Reconnect and wrong-save refusal | SHIPPED C1/F17 | SHIPPED C1/F17 | SHIPPED C1/R13 | SHIPPED C1/E15 | HELD X |
| Dead-zone propagation | SHIPPED C3/F18 | SHIPPED C3/F18 | SHIPPED C3/R12 | SHIPPED C3/E16 | HELD X |
| Pre-Pokéball gate and later activation | SOURCE-ONLY C3b | SOURCE-ONLY C3b | SOURCE-ONLY C3b | SOURCE-ONLY C3b | HELD X |
| Species/evolution-family and dupes reroll clause | SOURCE-ONLY C3r | SOURCE-ONLY C3r | SOURCE-ONLY C3r | SOURCE-ONLY C3r | HELD X |
| Gender clause | SOURCE-ONLY C3r | SOURCE-ONLY C3r | SOURCE-ONLY C3r | SOURCE-ONLY C3r | HELD X |
| Type clause | SOURCE-ONLY C3r | SOURCE-ONLY C3r | SOURCE-ONLY C3r | SOURCE-ONLY C3r | HELD X |
| Shiny exception / bonus-pair behavior | SOURCE-ONLY C3s | SOURCE-ONLY C3s | SOURCE-ONLY C3s | SOURCE-ONLY C3s | HELD X |
| Player PC-release propagation | SOURCE-ONLY C3l | SOURCE-ONLY C3l | SOURCE-ONLY C3l | SOURCE-ONLY C3l | HELD X |

Code references:
- C1: capture/acquisition at [client.lua:404](C:/slink-wt/g3-int/lua/gen3/client.lua:404), faint observation :394, active-faint executor :825, signal handling :1135, hello/reconnect snapshot :1014; server capture/faint/whiteout handlers at [state.py:2212](C:/slink-wt/g3-int/server/state.py:2212), :2704, :3015. These are shared title-bound paths, not independent per-title implementations.
- C2: [boxes.lua:364](C:/slink-wt/g3-int/lua/gen3/boxes.lua:364) deposit, :401 withdraw, :430 memorialize; [state.py:3102](C:/slink-wt/g3-int/server/state.py:3102)/:3150 synchronize the pair.
- C3: [state.py:2229](C:/slink-wt/g3-int/server/state.py:2229) gift/shiny admission, :2862 no-catch/deadzone. C3b: [client.lua:365](C:/slink-wt/g3-int/lua/gen3/client.lua:365) ball latch and [state.py:2714](C:/slink-wt/g3-int/server/state.py:2714) faint gate; tests exist at tests/unit/test_state.py:1954-2153, but I did not locate a Gen 3 live negative before-balls row. C3r: [state.py:2771](C:/slink-wt/g3-int/server/state.py:2771) dupes and :3905/:3929/:3964/:3971 pair clauses. C3s: [state.py:2230](C:/slink-wt/g3-int/server/state.py:2230) shiny/bonus flow. C3l: [client.lua:445](C:/slink-wt/g3-int/lua/gen3/client.lua:445)/:1162 and [state.py:2736](C:/slink-wt/g3-int/server/state.py:2736).
- C4: production native construction is RR-only at [entry.lua:352](C:/slink-wt/g3-int/lua/gen3/entry.lua:352). FR/LG and Emerald profiles have no native block. [native.lua:720](C:/slink-wt/g3-int/lua/gen3/native.lua:720) explicitly returns v2 panel binding unavailable; [gen3_frlge.py:533](C:/slink-wt/g3-int/server/adapters/gen3_frlge.py:533) advertises panels only for RR.
- C5: [native.lua:504](C:/slink-wt/g3-int/lua/gen3/native.lua:504), [client.lua:1648](C:/slink-wt/g3-int/lua/gen3/client.lua:1648), [manager.py:175](C:/slink-wt/g3-int/server/manager.py:175). FR/LG/E have an engine-audio m4a fallback, and FR/LG duo logs contain sound writes; that does not close the requested companion Native Sounds option, which Manager still refuses for those titles. I have not labelled the fallback missing.
- C6: [client.lua:611](C:/slink-wt/g3-int/lua/gen3/client.lua:611) requires CHOSEN_MOVE_ADDR for Explosion; all three FR/LG/E profiles lack it. Executor :729/:863 is present but not a title binding. [gen3_frlge.py:542](C:/slink-wt/g3-int/server/adapters/gen3_frlge.py:542) and manager.py:165 remain RR-only.
- C7: [native.lua:594](C:/slink-wt/g3-int/lua/gen3/native.lua:594) hard-binds the window to titles.radical_red; :615 is the swap, [client.lua:1338](C:/slink-wt/g3-int/lua/gen3/client.lua:1338) is the epoch guard, manager.py:169 permits RR only. No FR/LG/E native construction/window binding exists.
- C8: [native.lua:334](C:/slink-wt/g3-int/lua/gen3/native.lua:334)/:419 and [client.lua:1728](C:/slink-wt/g3-int/lua/gen3/client.lua:1728) implement the Emerald-only v2 consumer; [abi.h:59](C:/slink-wt/g3-int/patch/src/trade_targets/abi.h:59)/:68 define opcode/capability. Production Entry still constructs only RR ABI1; no admitted Emerald companion contact/live call receipt was located. An ABI enum and injected tests are not a shipped producer.
- T: [native.lua:146](C:/slink-wt/g3-int/lua/gen3/native.lua:146) unconditionally returns false for trade_capable; typed visit/eligibility methods are unavailable. [firered.h:29](C:/slink-wt/g3-int/patch/src/trade_targets/firered.h:29), [leafgreen.h:19](C:/slink-wt/g3-int/patch/src/trade_targets/leafgreen.h:19), [emerald.h:19](C:/slink-wt/g3-int/patch/src/trade_targets/emerald.h:19), [radical_red.h:19](C:/slink-wt/g3-int/patch/src/trade_targets/radical_red.h:19) all keep READY=0. T3-R6's journal/flush/recovery work does not remove that hold.
- C9: ordinary NPC trade at [client.lua:479](C:/slink-wt/g3-int/lua/gen3/client.lua:479)/:1117/:1165; evolution and poison dispatch at :1154/:1169. C9p: the RR site table contains no poison event, and [gen3_engine_sites.md:44](C:/slink-wt/g3-int/docs/gen3_engine_sites.md:44)/:338 records the unqualified/disabled field-poison path. This is no owner exclusion; it also is not a recommendation to change RR's game mechanics.
- U: [gen3_frlge.py:658](C:/slink-wt/g3-int/server/adapters/gen3_frlge.py:658)/:676/:740/:798; [server.py:967](C:/slink-wt/g3-int/server/server.py:967); [_board.html:211](C:/slink-wt/g3-int/server/templates/_board.html:211); [slink_bridge.js:192](C:/slink-wt/g3-int/calc/src/js/slink_bridge.js:192)/:806. UX adds [gen3_expansion.py:279](C:/slink-wt/g3-int/server/adapters/gen3_expansion.py:279)/:322. The code and per-ROM projection rows exist. Those rows check trainer_brief/table data, not browser navigation, Upcoming grouping, Prep selection or calc correctness end-to-end; I found no corresponding passing live UI row, so these cells remain SOURCE-ONLY under the requested standard.
- C10: [entry.lua:62](C:/slink-wt/g3-int/lua/gen3/entry.lua:62)/:75; [gen3_frlge.py:418](C:/slink-wt/g3-int/server/adapters/gen3_frlge.py:418) opts in only FR/LG/E; base.py:332 defaults false for expansion. RR built-in randomizer modes were not established by the managed UPR/per-ROM evidence and are not silently counted as this feature.
- X: [expansion profile.json:108](C:/slink-wt/g3-int/data/games/gen3_exp/28877d73/profile.json:108) admitted=false; [write_checkpoint.json:3](C:/slink-wt/g3-int/data/games/gen3_exp/28877d73/write_checkpoint.json:3) admitted=false and :140 lacks an admitted parked-CPU range. [entry.lua:62](C:/slink-wt/g3-int/lua/gen3/entry.lua:62)/:115 omits gen3_exp from PACKS/ROUTED. Masked record code does exist at reads.lua:179/:266, and server adapter registration exists at server/adapters/__init__.py:236; those do not admit the game.

Live receipt references (F/R/E numbers are exact one-based summary lines identifying the passing row and its raw receipt):
- F#: [FR/LG frozen summary](C:/slink-wt/g3-int/docs/gen3/probes/fc_SUMMARY_a2985d5a.txt:14): F14 faint; F15 natural link; F16 boxsync; F17 reconnect; F18 deadzone; F19/F20 whiteout; F23/F24 active faint. FR-as-A rows exercise an FR/LG pair; the active-faint and whiteout rows include the reverse orientation. F15's raw receipt has a failed RNG hunt followed by the accepted PASS/PYDEC at lines 96-107, not an all-attempts-pass claim.
- R#: [RR frozen summary](C:/slink-wt/g3-int/docs/gen3/probes/fc_SUMMARY_a2985d5a_rr.txt:6): R6 faint; R7 active faint; R9 boxsync; R10 whiteout; R11 link; R12 deadzone; R13 reconnect; R14 Explode; R16 real rival swap. R15 is only a stale-battle-id refusal control and was NOT used to qualify Rival Swap. The raw Explode row records engine Explosion KO without input at fc_explode_gen3_rr_as_a_a2985d5a.txt:27; the real rival row records two enemy mons and independent readback at fc_rival_swap_real_gen3_rr_as_a_a2985d5a.txt:24-30.
- E#: [Emerald frozen summary](C:/slink-wt/g3-int/docs/gen3/probes/fc_SUMMARY_94c980f3_emerald.txt:14): E14 faint; E15 reconnect; E16 deadzone; E17 link; E18 boxsync; E19 active faint; E20 whiteout.
- Lpanel: [RR START-panel duo](C:/slink-wt/g3-int/docs/gen3/probes/rr_infopanel_gen3_gen3_rr_as_a_f78b533a_r2.txt:25), direct drawn-row/close readback and PYDEC PASS at :32. This supersedes the stale ledger claim that no new-client infopanel duo exists.
- Lsound: [RR live opcode gates](C:/slink-wt/g3-int/docs/gen3/probes/fc_rr_opcode_gates_a2985d5a.txt:10), 26/26 executed; [test_lua_gates.py:79](C:/slink-wt/g3-int/tests/live/test_lua_gates.py:79) includes test_live_playse.lua. Deferred text/ghost skips are explicitly not counted.
- LnpcF: [FR NPC trade](C:/slink-wt/g3-int/docs/gen3/probes/fc_npc_trade_gen3_fr_as_a_bd2d191b.txt:27), PYDEC :36. LnpcL: [LG NPC trade](C:/slink-wt/g3-int/docs/gen3/probes/fc_npc_trade_gen3_lg_as_a_2467b357.txt:27), PYDEC :36. LnpcE: [Emerald NPC trade](C:/slink-wt/g3-int/docs/gen3/probes/fc_npc_trade_gen3_emerald_T3_R4_eca04eb1.txt:38), PYDEC :47. These are ordinary NPC exchanges, not T's held Soul Link trade.
- LevoF: [FR evolution](C:/slink-wt/g3-int/docs/gen3/probes/fc_evolve_gen3_fr_as_a_58a4f1fe.txt:29), PYDEC :38. LevoL: [LG evolution](C:/slink-wt/g3-int/docs/gen3/probes/fc_evolve_gen3_lg_as_a_95876c55.txt:31), PYDEC :40. LevoE: [Emerald evolution](C:/slink-wt/g3-int/docs/gen3/probes/fc_evolve_gen3_emerald_58a4f1fe.txt:28), PYDEC :37.
- LpoisonF: [FR poison](C:/slink-wt/g3-int/docs/gen3/probes/fc_poison_faint_gen3_fr_as_a_a2fa1f94.txt:33), PYDEC :47. LpoisonL: [LG poison](C:/slink-wt/g3-int/docs/gen3/probes/fc_poison_faint_gen3_lg_as_a_95876c55.txt:30), PYDEC :44. LpoisonE: [Emerald poison](C:/slink-wt/g3-int/docs/gen3/probes/fc_poison_faint_gen3_emerald_9ce65d28.txt:27), PYDEC :41.
- LrandF: [FR/LG admission](C:/slink-wt/g3-int/docs/gen3/probes/fc_admit_randomized_frlg_r4_39da30fd.txt:49), PYDEC :55, plus [per-ROM trainer projections](C:/slink-wt/g3-int/docs/gen3/probes/fc_trainer_panel_gen3_rand_r4_39da30fd.txt:31). LrandE: [Emerald admission](C:/slink-wt/g3-int/docs/gen3/probes/fc_admit_randomized_emerald_emerald_rand_061ee4f5.txt:51), PYDEC :57, plus [Emerald trainer projections](C:/slink-wt/g3-int/docs/gen3/probes/fc_trainer_panel_gen3_rand_emerald_rand_061ee4f5.txt:37).
- LrandLink: [FR/LG randomized natural-link PASS](C:/slink-wt/g3-int/docs/gen3/probes/fc_link_gen3_rand_r4_driver_d998cc65.txt:37), strict saved-ball and PYDEC PASS :46-51. It supersedes the out-of-balls failure at 39da30fd and the ball-accounting failure at 2bd0ee22. Emerald's receipt explicitly disclaims randomized natural capture and UI navigation at fc_trainer_panel_gen3_rand_emerald_rand_061ee4f5.txt:8.

Owner ruling references:
- O1: [Gen 3 PLAN:21](C:/slink-wt/g3-int/docs/gen3/PLAN.md:21) removes peer ghost from the Gen 3 RC; [Emerald PLAN:22](C:/slink-wt/g3-int/docs/gen3_emerald/PLAN.md:22) explicitly confirms the FR/RR deferral while recording Emerald's.
- O2: [Emerald PLAN:22](C:/slink-wt/g3-int/docs/gen3_emerald/PLAN.md:22) explicitly defers Emerald ghost. O?: I found no explicit expansion-ghost ruling, so its cell is MISSING, not inferred out.
- Required, not exclusions: [G4 ruling 27:520](C:/slink-wt/g3-int/docs/gen3/G4_request_draft.md:520) patched trades; ruling 28 :518 trainers/Upcoming/Prep; ruling 29 :516 randomized; ruling 30 :514 FR/LG panel/sounds/Explode/Rival. [Emerald PLAN:21](C:/slink-wt/g3-int/docs/gen3_emerald/PLAN.md:21) carries those requirements to Emerald; :23 requires Match Call. “FR/LG have no PokéNav” is not treated as an owner ban on a parity-equivalent call feature.
- Randomized cells cover the allowed envelope only: [G4:500-511](C:/slink-wt/g3-int/docs/gen3/G4_request_draft.md:500) explicitly holds rule-changing randomizations post-RC.
- Do not confuse web calc/Prep with native battle-calc overlay: native overlay is explicitly RR-only under [G4:514](C:/slink-wt/g3-int/docs/gen3/G4_request_draft.md:514) and [Emerald PLAN:21](C:/slink-wt/g3-int/docs/gen3_emerald/PLAN.md:21). Native notification boxes are also explicitly deferred by [Gen 3 PLAN:14](C:/slink-wt/g3-int/docs/gen3/PLAN.md:14); ordinary HUD notifications are the intended path.

DISAGREEMENTS
1. Historical plan/ledger “missing” statements are not current status. Emerald trainer adapters exist; RR has a passing normal-input info-panel duo; Emerald NPC trade/evolution/poison have later PASS rows. Conversely, the R6 durability fix is not a trade-capability release.
2. A passing randomized trainer projection is not a passing Upcoming/Prep browser flow. I keep those UI cells SOURCE-ONLY under your requested evidence bar, despite existing implementation and earlier prose saying “UI-checked.”
3. Gen 1/2 themselves have feature/gate distinctions: the Gen 2 phone source exists at lua/gen2/phone.lua:1, but the old Gen 2 requirements ledger is not proof every native feature is physically shipped. This table uses the requested union of player-facing features, not an unsupported claim that every baseline gate is closed.

UNKNOWN / UNVERIFIED
- No new runtime qualification was performed. All positive live evidence belongs to its stated cut and admitted artifact; a final integration recut remains separate.
- SOURCE-ONLY cells may have evidence outside the committed paths I inspected. A named passing feature-level receipt would change those cells.
- Active-faint SHIPPED cells are the demonstrated singles paths, not all doubles/Steven/target-menu/Safari contexts. Owner-signed FRLG limits are G4_request_draft.md:472; Emerald EG4_request.md:37-39/:48 carries its narrower context limits.
- RR field-poison has no qualified event in this ROM. That needs an applicability/ruling decision or a real engine-path witness, not a guessed new poison mechanic.
- Expansion's adapter/data/codec and reproducible build are not production admission or live parity. Its write checkpoint still explicitly refuses the unmeasured CPU condition.

RECOMMENDATION
Five highest-value MISSING/SOURCE-ONLY cells, each as a first bounded vertical card; shared files require sequential ownership:

1. FR native info panel — MISSING. Card FR-PANEL-V2: implement only the FR SOULLINK menu/panel path, preserving trade holds. Files: C:/slink-wt/g3-int/lua/gen3/entry.lua, lua/gen3/native.lua; tools/gen_gen3_profile.py; data/games/gen3_frlg/profile.json; patch/src/trade_targets/abi.h and firered.h plus the new FR panel producer/hook module; server/adapters/gen3_frlge.py; tests/unit/test_gen3_native.py; lua/tests/duo/scenario_gen3_infopanel.lua. First falsifier: the production-built FR companion must construct native automatically and a normal START open must draw exactly the server rows and close via A/B; current RR-only construction/v2-unavailable panel must fail this. Reuse the RR independent row readback, not a raw test-only poster.

2. Emerald Explode Mode — MISSING. Card E-EXPLODE-BIND: source-pin the missing Explosion action/move-buffer facts and its exact commit predicate, then opt the title into the existing executor. Files: tools/gen_gen3_profile.py, tools/gen_gen3_checkpoint.py (or the current checkpoint generator entry), data/games/gen3_emerald/profile.json and write_checkpoint.json, lua/gen3/client.lua, server/adapters/gen3_frlge.py, server/manager.py, tests/unit/test_gen3_client.py, tools/e2e_duo.py and lua/tests/duo/duo_gen3_main.lua. First falsifier: a linked active Emerald mon currently cannot produce an engine Explosion from force_explode because CHOSEN_MOVE_ADDR is absent. Require engine move/PP/faint evidence with no player press and no silent HP-zero substitute, then saved-state readback.

3. FR Rival Team Swap — MISSING. Card FR-RIVAL-WINDOW: one exact FR rival and one engine-owned pre-snapshot window before generalizing to LG/E. Files: lua/gen3/native.lua, tools/gen_gen3_profile.py, data/games/gen3_frlg/profile.json/write_checkpoint.json, the FR companion rival producer/hook, server/adapters/gen3_frlge.py, server/manager.py, tests/unit/test_gen3_native.py, lua/tests/duo/scenario_gen3_rival_swap_real.lua, tools/e2e_duo.py. First falsifier: a valid FR request currently has no FR native/window binding; after implementation its enemy party must equal the partner's independent blob decode before battle initialization. Stale session/battle IDs and closed windows must leave enemy RAM untouched.

4. Emerald Match Call — SOURCE-ONLY. Card E-CALL-PRODUCER: finish the real contact/call producer and production v2 construction, not more injected-consumer tests. Files: patch/src/trade_targets/abi.h and emerald.h, a new Emerald Match Call producer/hook module, tools/gen_gen3_profile.py, data/games/gen3_emerald/profile.json, lua/gen3/entry.lua/native.lua/client.lua, tests/unit/test_gen3_native.py and test_gen3_client.py, plus a live call carrier. First falsifier: a normal-input Emerald boot/contact lookup must expose the Soul Link contact and deliver first_link once after a valid epoch handshake; mailbox ACK alone must not count as delivery. A busy native UI must hold the call. Keep the phone capability separate from trade READY.

5. Emerald natural randomized linking — SOURCE-ONLY. Card E-RAND-CATCH: extend the existing randomized-link carrier/oracle to E↔E with the already pinned allowed-seed inputs. Files: tools/e2e_duo.py, tools/gen3_fixtures.py, lua/tests/duo/scenario_gen3_rand_link.lua and scenario_gen3_rand_common.lua, tests/unit/test_e2e_duo_gen3_rand.py, and the final-cut row list. First falsifier: both real catches must belong to each OWN randomized encounter table, form the correct server link, and survive save/reload; consumed balls must equal recorded throws. Existing Emerald admission/table projection PASSes do not satisfy this. Carry over the FR d998cc65 strict oracle and disclosed fixture policy.

The all-title native-trade hold and expansion admission hold are separate critical prerequisites already visible in the table; I did not disguise either as one of the requested MISSING/SOURCE-ONLY picks.

TESTS / VERIFICATION
Read-only git/source/JSON inspection and committed-receipt review only. I checked current production admission/capability gates, matched positive rows to their title/artifact and inspected raw decisive PASS/PYDEC lines, including the failing-then-passing randomized sequence. No tests were executed because the assignment forbids writes; no files were created or changed. The inspected integration worktree was clean at start and end; the observed HEAD advance was the coordinator's RR-SYNTH merge, whose changed-file list I reviewed.

## Changes since the original reply — CLAUSE-LIVE-REST

Current private qualification base: `bb49090cc5318a84e62d8f8170065199a423ddde`
(integration `f17239ec` plus C3 `97205f26`, including reader `58ae29fc`).
Coordinator authorized concurrent Gen 3 lanes with private `SLINK_STATE_DIR`
and termination restricted to owned PIDs. Other workers' emulators remain untouched.

| Cell | Scope of this card | Current evidence |
| --- | --- | --- |
| C3s shiny/bonus | FR, LG, RR, Emerald | All four title-as-A cells LIVE/PYDEC PASS. One-time wild PID setup is disclosed; all four catches, both pair formations and saves use native input/production events. Emerald passed on attempt2 after a native whiteout on attempt1. See the title-specific receipts and `clause_live_rest_2026-09-27.md`. |
| C3l PC release | FR/LG/RR; Emerald already passed | Fresh FR/LG/RR native PC release, partner retirement/memorial, save-witness and PYDEC PASS at `6349ba01`; title-specific receipts below. |
| C3b ball gate | LG and Emerald; FR already passed | LG and Emerald PASS at clean `6349ba01`: native pre-ball suppression/reward activation, disclosed20-ball second phase, real link and matching final saves. A stale final-result reader was fixed red/green before the accepted runs. The older RR receipt was FAIL, so RR was rerun and also PASS at `49d99c6c`. |
| C3r species/gender/type/family | RR | RR gender PASS attempt4/8 and type PASS attempt1/3 at `49d99c6c`. RR species/dupes PASS attempt3/8 and evolution family PASS attempt8/16 at `a643a2b6`. Family observed native Galarian Zigzagoon1222 against B's evolved Galarian Linoone1223. An earlier family attempt exposed an oracle map-shape bug (numeric787 vs text3.19), fixed red/green before the accepted run. Other title/rule combinations are outside this card's new live receipts. |

C3 also corrected RR base/Galarian evolution families and the family fixture,
retained retry evidence, and added 16 RR family attempts. Its full gate was
12335 passed / 4395 skipped / zero failures; SOURCE/MODEL only.
The RR encounter peer owns the separate ROM-authoritative catalog and the
regeneration of the family artifact after extending the species catalog.

Other original cells are historical context, not re-audited by this card.
Final title-by-row receipts and code cuts are listed in
`docs/gen3/research/clause_live_rest_2026-09-27.md`.

### Accepted live receipts at 6349ba01

- LG gate: `docs/gen3/probes/clause_live_rest_ball_gate_lgfr_6349ba01.txt`.
- Emerald gate: `docs/gen3/probes/clause_live_rest_ball_gate_emerald_6349ba01.txt`.
- FR release: `docs/gen3/probes/clause_live_rest_release_gen3_gen3_frlg_6349ba01.txt`.
- LG release: `docs/gen3/probes/clause_live_rest_release_gen3_gen3_lgfr_6349ba01.txt`.
- RR release: `docs/gen3/probes/clause_live_rest_release_gen3_gen3_rr_6349ba01.txt`.
- RR ball gate: `docs/gen3/probes/clause_live_rest_ball_gate_gen3_gen3_rr_49d99c6c.txt`.
- RR gender and type: `docs/gen3/probes/clause_live_rest_gender_clause_gen3_gen3_rr_49d99c6c.txt` and `clause_live_rest_type_clause_gen3_gen3_rr_49d99c6c.txt`.
- RR family: `docs/gen3/probes/clause_live_rest_species_family_gen3_gen3_rr_a643a2b6.txt`.
- RR species/dupes: `docs/gen3/probes/clause_live_rest_species_clause_gen3_gen3_rr_a643a2b6.txt`.
- FR/LG/RR/Emerald shiny bonus: `docs/gen3/probes/clause_live_rest_shiny_bonus_gen3_gen3_{frlg,lgfr,rr}_49d99c6c.txt` and `clause_live_rest_shiny_bonus_gen3_gen3_emerald_a643a2b6.txt`.

The raw receipts, both SaveRAMs, witness dumps and manifests are retained under
`C:/slink-wt/g3-clause-live-rest/.cache/live/`; server states remain in the
private `.cache/state/` of the named run checkout. The first LG run exposed
`wait_results` reading phase-one results; its failed receipt is retained.
An Emerald run was also refused for an uncommitted LG receipt file (+dirty);
it was not promoted. The accepted Emerald run uses the separate frozen clean
checkout `C:/slink-wt/g3-clause-run`, separating development from qualification.

Final combined-code unit run: **12611 passed / 4244 skipped / zero failures**;
all 154 selected clause, reader, shiny and citation controls ran with no skip.
The first full run identified 11 stale `docs/protocol.md` offsets after the
integrated `state.py` changes; the citations were repaired and the final full
rerun exited 0. See `clause_live_rest_2026-09-27.md` for the evidence boundary.
