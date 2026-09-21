# RR companion shadow explained differences

Card gen3-P3-C3-8, 2026-09-21. These capture-specific ledgers annotate differences; they do not qualify G3. All twelve supplied observer logs have zero `SHADOW ` records. Consequently **all 14 reducer kinds remain UNCOVERED**, even for an empty wire event stream (`tools/gen3_shadow_diff.py:25-29,226-230,252-255`). The 19 registered engine sites and 14 reducer kinds are different inventories; registration/liveness is not semantic coverage.

## Run

From the planning worktree, substitute a scenario name for `<s>`:

```powershell
python tools/gen3_shadow_diff.py --wire patch/build/shadow_wire/<s>_a_old_client.shadowrun.jsonl --shadow patch/build/shadow_wire/<s>_a.shadow.log --ledger docs/gen3/shadow_ledger/<s>.json --json
```

Each scenario ledger includes both players. For the complete check, use:

```powershell
python tools/gen3_shadow_diff.py --wire patch/build/shadow_wire/<s>_a_old_client.shadowrun.jsonl patch/build/shadow_wire/<s>_b_old_client.shadowrun.jsonl --shadow patch/build/shadow_wire/<s>_a.shadow.log patch/build/shadow_wire/<s>_b.shadow.log --ledger docs/gen3/shadow_ledger/<s>.json --json
```

Expected: exit **1**, `passed: false`, all coverage rows UNCOVERED, and no unexplained deltas for these exact captures. The single-player trade command leaves the other side's entries in `unused_ledger`; run both players for zero unused entries. `owner: OPEN ...` is human tracking text: the comparator treats it as an explanation, not a resolved qualification (`tools/gen3_shadow_diff.py:246-255`). **Do not interpret an annotated OPEN delta as closed.** Natural-play sources/route receipts remain C3-7 work.

No `--frame-bound` is needed: none of these absent-shadow deltas has a matched timing pair. Wire `t` is capture order, never emulator frame (`tests/fixtures/gen3/wire/README.md:26-30`; `tools/gen3_shadow_diff.py:1-7`).

## Exact expected reduction

Source captures are under `patch/build/shadow_wire/`. Line citations in the JSON are 1-based physical JSONL lines; these records also happen to have the same `t`. Keys follow the reducer's `key`, then `new_key`, then map/slot fallback (`tools/gen3_shadow_diff.py:78-86`). No artificial slot keys were substituted.

| Scenario | A compared events | B compared events | A/B commanded_write | Ledger entries | Explanation status |
|---|---:|---:|---:|---:|---|
| faint | 1 faint | 0 | 0 / 1 | 1 | A direct HP injection explained |
| explode | 1 faint | 0 | 0 / 1 | 1 | A direct HP injection explained |
| boxsync | 0 | 0 | 0 / 0 | 0 | No semantic deltas; native movement is not automatically pc_move |
| ghost | 0 | 0 | 0 / 0 | 0 | Ghost movement is outside reducer kinds |
| infopanel | 0 | 0 | 0 / 0 | 0 | Panel/UI commands are outside reducer kinds |
| trade | trade_done, pc_move(deposit), mon_given | trade_done, pc_move(deposit), mon_given | 0 / 0 | 6 | OPEN: route not proven; likely polling artifacts around swap |

`commanded_write` is **not allowed in a ledger**: it is not in KINDS, load_ledger rejects it, and main reports it separately from compare (`tools/gen3_shadow_diff.py:25-29,112-116,133-138,209-217,275-279`). Thus B's force_faint (`faint_b_old_client.shadowrun.jsonl:239`) and force_explode (`explode_b_old_client.shadowrun.jsonl:55`) are documented here, not as bogus ledger deltas. No complementary faint notification occurs in these B captures.

A's faint is still a compared event: the reducer recognizes injected HP by one exact SHA256, not by filename or scenario (`tools/gen3_shadow_diff.py:40-45,89-91,133-138`). This batch's faint-A hash is `ef41d911ffb03cfb48a3ce51ac78f8bf6d94faec4eb72726438121d1a898a398`, which differs from that whitelist. Ledger the actual retained event; do not silently expand the whitelist or invent another commanded_write.

## Reasons for empty ledgers and limits of trade explanations

* **boxsync:** captures contain only hello/ghost_pos/status/tick/stats_cache client events, none in KINDS (`boxsync_{a,b}_old_client.shadowrun.jsonl`, complete streams; reducer filter `tools/gen3_shadow_diff.py:119-126`). Scenario waits for injected box_mon/party_mon (lua/tests/duo/scenario_boxsync.lua:11-43); patch native handlers directly compress/decompress/compact (patch/src/handlers.c:2079-2123), bypassing the PC operation hooks in docs/gen3_engine_sites.md:188-216,360-478. Do not invent deposit/withdraw deltas from server commands or tick party changes: this reducer does not derive them.
* **ghost:** captures contain hello/ghost_pos/status/tick only. Script walks while the partner checks ghost movement (`lua/tests/duo/scenario_ghost.lua:29-49,53-145`); no ghost-specific engine pin exists in the 19-site inventory (`docs/gen3_engine_sites.md:58-518`). The reducer ignores ghost_pos (`tools/gen3_shadow_diff.py:25-29,119-126`).
* **infopanel:** captures contain hello/ghost_pos/status/tick only. START/paging/B and native field-lock checks exercise UI (`lua/tests/duo/scenario_infopanel.lua:67-113`), not acquisition/trade/save/map operation sites (`docs/gen3_engine_sites.md:58-518`). No inferred semantic rows are added.
* **trade:** the captured completion names each side's outgoing key, followed by outgoing party_to_box and incoming gift capture (exact rows cited in trade.json). This is consistent with fallback posting OP_SET_PARTY_MON then immediately emitting trade_done before execution (`lua/clients/gen3_frlge_client.lua:2224-2231`), followed by disappearance/gift polling (`:3712-3738,3834-3848,3887`). **That is an inference, not a route receipt.** Normal native TradeMons should hit trade sites (`docs/gen3_engine_sites.md:278-296,500-518`); scenario PASS only requires final partner-key swap/stability (`lua/tests/duo/scenario_trade.lua:25-42`). All six trade explanations therefore retain OPEN ownership. Neither these ledgers nor zero SHADOW lines prove the engine never traversed TradeMons.

## Updated evidence supersedes part of the earlier note

The earlier `docs/gen3/research/shadow_explode_battle_end.md` inferred a new battle start from the scenario's comment/name. The later physical census states `slink_prebattle.State` was captured **after battle initialization**: active battle callbacks execute, battle-init entries do not, and battle_end 0x08015BD0 fires once at frame 2484 when the extended run returns to the field (`docs/gen3/probes/census_rr_battle_2026-09-21.txt:1-5`). Thus the old note's demand for a battle_begin fire is not applicable to this fixture. Explode still exits on outcome before requiring field return (`lua/tests/duo/scenario_explode.lua:90-106`; `lua/tests/duo/duo_main.lua:179-187`). No battle_begin or battle_end wire event appears in this batch to ledger.

Do not promote the census's final generalization to 19 physically qualified sites: its pinned-address run reports only frame_control and battle_end firing (`census_rr_battle_2026-09-21.txt:5`). `docs/gen3/research/rr_site_reachability.md:18-26,34-57` establishes static byte/caller evidence, explicitly using upper-bound geometric BL counts. Its introductory claim of an instrumentation problem is not itself physical proof of all remaining sites. Natural-play coverage remains OPEN.

## Verification performed / still required

Read and JSON-parsed all twelve wire captures with PowerShell; inventoried client event names and semantic rows; counted zero SHADOW records in all twelve observer logs. JSON ledger syntax and four required fields checked separately. These are source/capture checks, not a run of the Python reducer.

Attempting the actual combined trade reducer through `E:/Google Drive/SLink/.venv/Scripts/python.exe -B` failed before Python launched:

```text
Unable to create process using '"C:\Users\howar\AppData\Local\Programs\Python\Python312\python.exe" -B tools/gen3_shadow_diff.py --wire patch/build/shadow_wire/trade_a_old_client.shadowrun.jsonl patch/build/shadow_wire/trade_b_old_client.shadowrun.jsonl --shadow patch/build/shadow_wire/trade_a.shadow.log patch/build/shadow_wire/trade_b.shadow.log --ledger docs/gen3/shadow_ledger/trade.json --json'
```

Coordinator must run all six combined commands above and check **zero unexplained deltas**, **zero unused entries**, and **14 UNCOVERED rows**. Expected exit 1 is coverage failure, not a parser error; an `error` field or a changed delta count requires investigation. No emulator, production-code edits, or commits on this card.
