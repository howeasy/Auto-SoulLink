# Handoff: the Emerald lane joins the combined Gen 3 orchestrator (2026-09-26)

**Owner decision (2026-09-26):** "We will combine the next work." From the next session, ONE
orchestrator runs all remaining Gen 3 work: FireRed/LeafGreen, Radical Red, Emerald, and the
pokeemerald-expansion track as a sub-lane. This file is the Emerald lane's half. The Gen 3 lane
("Gen3 migration planning") writes its own half on `claude/gen3-migration-planning-5d8e45`:
`docs/gen3/HANDOFF_combined_gen3_2026-09-26.md` at branch head 17988de4 (it lists must-fix-before-landing items in §0a: randomized server refusal blockers from Codex FRLG review cx-42eabc05).

## 0. Rules that bind every session (owner)

- **Nothing lands on master**, local or remote, without the owner's explicit approval of that
  landing. All work stays on worktree branches. Merging master INTO a branch is fine.
- A gate (EG*/XG*/G*) is signed only on an explicit owner "yes" in chat. Never infer it.
- **A scope exclusion counts only if it traces to an owner ruling.** An agent-written "out of
  scope" line is a proposal; put it to the owner as a question. (Randomizer was mis-scoped this
  way; the owner: "IT SHOULD NOT BE OUT OF SCOPE. I DIDNT DECIDE ANY OF THIS.")
- Mimic the accepted frameworks (Gen 1/2/RR in-game trade and native menus). Never invent HUD
  or hotkey UX. The HUD is player-facing only.
- The target is to **match or beat the Gen 1/2 feature set** on every Gen 3 title.
- One writer per file. Kill only your own EmuHawk PIDs, never by image name. Every emulator run
  sets a PRIVATE `SLINK_STATE_DIR` (see §5 incident).
- Shared `server/**`, `lua/*.lua` and `lua/core/**` changes stale Gen 2's receipts. Ping
  "Gen 2 Boogaloo" before any master batch.
- Never commit ROMs or patched ROMs. The Linux VM `hgbox` is used only under `~/slink-exp`.
- Workers: at most 3 Haiku/Sonnet/Opus subagents at once, `model` explicit, prefer Sonnet.
  Headless OMP for bounded reviews, tests and small code, each with an explicit kill limit;
  never trusted implicitly, so verify every finding. Codex = live named threads only, **no
  headless Codex**.

## 1. Owner rulings that shape the remaining work (all 2026-09-26 unless noted)

| Ruling | Effect |
|---|---|
| EG4 signed for the Emerald lane ONLY | rc2 merged into `claude/gen3-emerald` (4ccac5b4). No RC label and no master landing until trainer panels, trade and randomized support land. |
| Admission | Unknown-hash BPEE is admitted by its 21 engine-site anchors, like FR/LG/RR; header-only builds are refused. |
| Live duo | The owner plays one live Emerald↔Emerald session on the lane (not yet done). |
| Trainer panels mandatory (Gen 3 ruling 28) | Trainer names, Upcoming Key Trainers and the calc Prep tab are required for vanilla FR/LG AND Emerald. |
| Patched trade (Gen 3 ruling 27) | In-game trade on patched FR/LG/Emerald, plus durable RR trade: native scene, evolve on receipt, native save before DONE, no raw-swap success. |
| Companion parity (Gen 3 ruling 30 + "match or beat") | FR/LG AND Emerald companions carry the SOULLINK info panel, native sounds, Explode Mode and Rival Team Swap. The in-battle calc display stays RR-only. |
| Match Call | Emerald gets a Soul Link PokéNav Match Call contact (mirrors Gen 2's phone call). |
| Randomized Gen 3 (Gen 3 rulings 29/31) | IN the RC. Rule-changing randomizations (evolutions, types, abilities, base stats) are REFUSED for the RC. An unknown-hash `rand` cart whose tables equal pret pairs as clean. |
| Expansion calc | IN the expansion RC. |
| Languages | US/EU English Emerald only; other dumps are refused by name. |
| Post-RC | Peer ghost and Archipelago Emerald (as for FR/RR). |
| Earlier (still binding) | XG0 signed (expansion 1.17.0 pinned build on hgbox). Frontier/Pyramid/Trainer Hill/Contests/Secret Bases: writes refused. Binary-only expansion hacks out. |

All are recorded in `docs/gen3_emerald/PLAN.md` §0 (ee4f7b04, 02cbebe7). Gen 3's rulings live in
`docs/gen3/PLAN.md` §0 and G4 §6 on the Gen 3 branch.

## 2. Branches and worktrees (Emerald side)

| Worktree | Branch | Head | State |
|---|---|---|---|
| `E:/Google Drive/SLink/.claude/worktrees/gen3-emerald` | `claude/gen3-emerald` | b5eca942 (+ this handoff commit) | **Integration lane.** master 5313d94e + EG4 rc2 + expansion x1/xr/xa/x3 + XC0 all merged and reviewed. Full unit suite: 10757 passed at 055279a5, and the one citation failure is fixed in 436df532. |
| `C:/slink-wt/em-t2` | `claude/gen3-emerald-t2` | c00fda11 (clean) | T2 companion producer (Codex "Emerald"). See §3. |
| `C:/slink-wt/em-t3` | `claude/gen3-emerald-t3` | 292b694c committed; T3-R1 review fixes UNCOMMITTED WIP in the worktree (client.lua, native.lua, trade.lua + tests) | T3 client (Codex "Emerald-2"). See §3. |
| `C:/slink-wt/em-xc1` | `claude/gen3-emerald-xc1` | 883053a6, merged into the lane b5eca942 | Expansion calc XC1-XC3 plus review fixes. See §4. Not merged yet. |
| `C:/slink-wt/em-xint` | `claude/gen3-emerald-xint` | 88cdd20c | Merged into the lane (ff). Parked. |
| em-x1, em-xr, em-xa, em-x3, em-xc, em-rc, em-rc2, em-docs, em-skips, em-calc, em-trade, em-x, em-legs, em-fx, em-eg4 | — | — | Merged or parked. Safe to clean up later (use `shutil.rmtree` with onerror chmod; never Remove-Item). |
| `C:/slink-wt/emerald-fc` | detached | 94c980f3 | Final-cut lane (EG4 cut 24/24). |

`patch/build/slink_RR.gba` (gitignored) must be the 7a386749 companion build in any worktree
that runs the Gen 3 tests. Copy it from the Gen 3 worktree.

## 3. Trade + companion (the biggest remaining piece)

The contract is `docs/gen3/research/patched_trade_design.md` + `patched_trade_bindings.md`
(Gen 3-approved). Gen 3 accepted the N-3 amendment for RR (35e2521b on their branch): no
raw-swap success; a pre-mutation failure cancels; a post-commit failure is uncertain.

**T2 producer: Codex "Emerald", peer id 01a0dec7-36cf-7640-9c72-65546322dec4.**
Reach it with `delivery=steer` and an explicit `peer` (name-based live queueing fails with
"unique session label").
- Lease: `patch/src/handlers.c`, `patch/tools/build.py`, `patch/src/slink.ld`,
  `patch/src/trade_targets/*`, `patch/dist/SLink-{FR,LG,Emerald,RR}.ups`, `server/patcher.py`,
  `tests/unit/test_patch_*.py`.
- Done:
  - ABI v2 `abi.h` (0eabd996 → 118c6f18 → c75e4bbc Match Call → 55d63a67 panel/control fields;
    RR v1 citations preserved, and the RR UPS reproduces md5 c372c428).
  - FR arena: heap clamp 0x1C000→0x1B000 with a PHYSICAL peak census (evolution 0x147BC, PC
    0x10018; 26 KB margin) and a native exhaustion negative control.
- Latest: c00fda11 records an isolated FR scene heap census including a diagnostic trade evolution (private state dir). OPEN: battle-party census, the FR trade producer, then panel/sounds/explode/rival swap.
- Every target is READY=0 and no UPS is published.
- Order: FR (trade → panel → sounds → explode → rival swap), then LG, then Emerald (plus Match
  Call), then the RR durable-trade delta.

**T3 client: Codex "Emerald-2", peer id 01a0ded3-f74e-7bf1-8999-f87761bcee21.**
- Lease: `lua/gen3/{native,entry,client,safety,trade}.lua`, `tools/gen_gen3_profile.py` (sole
  writer: native_block + rom_tables), and `tests/unit/test_gen3_{native,client,entry,profile_native,trade}.py`.
- Committed chain:
  - e8f51695 durable lifecycle;
  - f4ec8c85 KEY-SCOPE-5 box census;
  - a5469ea3 R0 rom_tables;
  - 637bcd17 CR-R1 `rand` kind;
  - d63609af, a merge of Gen 3's rom_content.lua 5a8033de;
  - e5f8da76 CR-R2 hook;
  - 292b694c, a merge of T2 c75e4bbc.
- **The e8f51695 review (OMP cx-d7cb155f, coordinator-verified) found BLOCKERS; T3-R1 fixes 8
  findings:**
  1. after_reset only after a real reset;
  2. cross-wire tests against server/state.py;
  3. a certain immediate refusal for v1/RR, with menu cancel;
  4. HUD and log output for uncertainty;
  5. a declared native milestone interface, with a shipped-native arity test;
  6. pack-supplied separate deadlines;
  7. reads-facade key decode;
  8. epoch-scoped records.
- At stop: T3-R1 is UNCOMMITTED work in em-t3 (6 files). The next orchestrator must first get Emerald-2's status report or inspect `git -C C:/slink-wt/em-t3 diff`; do not merge em-t3 into any integration branch until T3-R1 is committed green AND re-reviewed (the BLOCKERs above).
- Next: A (native_block → v2 abi.h; merge T2 55d63a67; RR v1 --check already current), then C
  (Match Call client).
- **Interim:** RR trade is refused rather than succeeding via v1 until the RR v2 target
  qualifies. The RR re-cut comes after durable trade.

**Still to plan and run:**
- T4, the server trade contract in `server/adapters/gen3_frlge.py`, sequenced after Gen 3's
  trainer and randomized writes to that file;
- T5, the two-player duos: FR↔LG, E↔E, RR↔RR, with the negative controls in design §6.

**Packaging:** add `lua/gen3/trade.lua` and `lua/gen3/rom_content.lua` to `tools/make_release.py`
`_LUA_GEN3` at integration.

## 4. Expansion track (pokeemerald-expansion 1.17.0, ROM sha1 28877d73)

- Merged into the lane, all independently reviewed:
  - x1 compiler facts + the unadmitted `gen3_exp` pack;
  - xr field masks;
  - xa adapter (F1-F6 fixed 401974cc);
  - x3 harness title syms (nils falsifiable, slices committed);
  - XC0 battle-config values (432 macros).
- `claude/gen3-emerald-xc1`: calc_profile `{gen: 9, dex: "expansion"}` (now gated on
  GEN_LATEST == GEN_9), calc_names.json, and calc_stats through the masked codec (a16388ae,
  bc87ed13, 883053a6 layout bound to facts.json, merged b5eca942).
  - Review cx-7cb40977 left one open MAJOR: an unmapped held item/ability (54 Mega Stones etc.)
    is silently dropped from the maths while still displayed. It needs a warning in the shared
    `calc/src/js/slink_bridge.js`, which is **calc-lane-owned**. Raise it with the calc session.
  - Merge xc1 into the lane once M3 lands.
- Next:
  - XC4: trainer sets for the Prep tab and Upcoming Key Trainers;
  - the X1 OPEN items (pc_deposit/pc_release sites inlined, CPU parking, commit handoff);
  - the XG1 request;
  - X3 probes and duos on the reference build;
  - XG2: an owner decision on shinyModifier, which needs a shared state.py change.
- Design: `docs/gen3_emerald/research/expansion_calc_design_2026-09-26.md`.

## 5. Open items and incidents

- **Incident:** T2 overwrote the shared `E:/Howard/Bizhawk/GBA/State/slink_fr_battle.State`
  (17:27 local), because the reused `lua/tests/gen3_scripted_play.lua` falls back to the shared
  state dir when `SLINK_STATE_DIR` is unset (`lua/tests/playlib.lua:560-566`). The Gen 3 lane was
  told to regenerate it before trusting any FR checkpoint battle-row receipt.
- Gen 3 owns the refused key_change retry (a shared lua/core change) as a follow-up.
- Their `reports_box_census()` override lands only together with T3 f4ec8c85.
- The Emerald binding of trainers and randomized comes AFTER Gen 3's FR/LG versions are green on
  their branch. Emerald randomized needs pokeemerald `rom_tables` with strides verified from
  pokeemerald's own structs.
- Queue:
  - DUO-SAVESTATE-CLEANUP;
  - legacy `emerald` stub deletion in `data/games/gen3_frlg/profile.json` (generator-owned, T3 lease);
  - PREMASTER-GEN1-GATE;
  - the Gen 1/Gen 3 owners review the allow-list commit 5d0b8504.
- Before any master batch: owner approval, a Gen 2 ping (server.py debug-area change 401974cc,
  the protocol re-cites), and tell Gen 3 the pack hashes moved.

## 6. Owner to-do

1. Play the live Emerald↔Emerald session on the lane:
   - from `E:/Google Drive/SLink/.claude/worktrees/gen3-emerald`, run
     `python -m server.manager --host 0.0.0.0`;
   - create a run;
   - two EmuHawks load `Pokemon - Emerald Version (USA, Europe).gba` and their saves, then
     `lua/slink.lua`.
2. Decide at XG2 on expansion shinyModifier (shared state.py).

## 7. Records

- Guide checkpoint: `C:/Users/howar/.claude/hooks/slink/RC_MASTER_GUIDE.md` (emerald-* workers).
- Register: `C:/Users/howar/.claude/hooks/slink/WORKTREE_REGISTER.md`.
- Resume: `docs/gen3_emerald/RESUME.md` checkpoint 7.
- Plan and ledger: `docs/gen3_emerald/{PLAN,REQUIREMENTS}.md`.
- EG4 request: `docs/gen3_emerald/EG4_request.md`.
