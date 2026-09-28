# Radical Red native trade reset: development receipts (2026-09-28)

These are two **development PHYSICAL** runs on the patched RR companion. They are separate
source heads and separate private install roots. Both ran ordinary NPC/menu inputs, native
game saves, clean `client.exit()`, and a cold `seed=False` relaunch of each cartridge's own
battery. Neither driver invoked a manual game SAVE after the trade. They are **not** receipts
from the eventual frozen final cut.

| case | exact source | result | private root | retained server data |
|---|---|---|---|---|
| post-success reset | `3383c8d28a5895ca5f296c7b0d73ab836e4cdd6a` | A/B final PASS, PYDEC PASS | `C:/slink-wt/rr-reset-success-dev-3383` | `C:/Users/howar/AppData/Local/Temp/slink_duo_trade_reset_success_gen3_7t_jz54n` |
| COMMIT_ENTERED interruption | `b1e039f85706896a5ccc05ef7e236fc800237835` | A/B final PASS, PYDEC PASS | `C:/slink-wt/rr-reset-commit-dev-b1e` | `C:/Users/howar/AppData/Local/Temp/slink_duo_trade_reset_commit_gen3_rp368q57` |

Each root staged `patch/build/slink_RR.gba`, SHA-1
`da579690db7d6933a0952a1f490312842793f71a`, SHA-256
`d945a8d8c279917b7760f240f3f838f63c194c8f434a64d6b04e02427316a7c5`.
The A/B `rr_battle2{,_b}.sav` fixtures had SHA-256
`4145232bca94592323a46fcbe606e153abde52a89594fd86ae790c93abd276ac` and
`7fd07ae381ab550e928e97d2f591738c9ef471d71e8f4f76e86886c28706fc97`.
The [manifest](manifest.json) records the byte length and SHA-256 of the ROM, fixtures,
production/harness sources, full private server wires, batteries, journal, and every retained
private data file. Its wire excerpts are copied **verbatim** from the full wire files; the
manifest gives their one-based source line numbers and the full-file hashes. The full battery
and journal files remain in the private data roots above rather than this docs commit.

Both commands ran from their respective roots after loading `C:/slink-wt/g3-env.sh` into the
PowerShell process, setting `SLINK_ARMGCC` to the vendored ARM GCC bin and a private
`SLINK_STATE_DIR`:

```text
python tools/e2e_duo.py --game gen3_rr --scenario trade_reset_success_gen3 --keep-data --lane rr-reset-success-dev-3383
python tools/e2e_duo.py --game gen3_rr --scenario trade_reset_commit_gen3 --keep-data --lane rr-reset-commit-dev-b1e
```

The [success runner](success_runner.log), [A initial](success_a_initial.txt) and
[B initial](success_b_initial.txt), [A reload](success_a_reload.txt) and
[B reload](success_b_reload.txt), and [PYDEC](success_pydec.txt) files are raw receipts.
Both initial cartridges logged the native pre-save and post-save; PYDEC verified each save-hook
flash dump against the flushed battery, selected-sector checksums/counter, RR extension
`LIVE_RAM_MATCH`, and partner-key party readback. Counters went **4→6** on each side. Wire
shows each visible two-mon tick immediately before `apply_ready` (A `t388→390`, B `t406→408`),
and the real `trade_done` reports (A `t586`, B `t618`). The server persisted the re-keyed
partner pair and no pending trade before the harness released `RESET_EXIT`. After clean exit,
each unseeded reload read the partner key and counter 6. The final A/B/PYDEC results are PASS.
The [final link state](success_final_links.json) and
[initial-exit link state](success_initial_links.json) are raw server JSON. This earlier head did
not yet archive its pre-GO link list separately; the live oracle held that baseline in memory.

The [commit runner](commit_runner.log), [A initial](commit_a_initial.txt),
[B initial](commit_b_initial.txt), [A reload](commit_a_reload.txt),
[B reload](commit_b_reload.txt), and [PYDEC](commit_pydec.txt) files are raw receipts.
A observed native `COMMIT_ENTERED` bits 3 at frame 7183 after the native pre-save and cleanly
exited with the *named expected partial* `RESULT: FAIL (EXPECTED_RESET_PARTIAL_COMMIT)`;
there was no A post-save or initial `trade_done`. Its selected flash counter went **4→5**.
B completed the native scene and both game saves, counter **4→6**, then its real report reached
the server (wire `t676`, paired reply `t677`) before B's clean exit. On distinct unseeded cold
reloads, A read its old key/counter 5 and B the received key/counter 6. A's production client
declared its token-bound uncertainty with `after_reset:true` (wire `t472`, paired reply `t473`)
and only then received the host's clean-exit release. PYDEC independently matched both native
save-site dumps to the flushed batteries and RR extension; the final A/B/PYDEC results are PASS.
The [pre-GO target link](commit_staged_links.json),
[initial-exit links](commit_initial_links.json), and [final links](commit_final_links.json)
are raw server JSON. The target `duo` link retained the original A/B keys and fields; a
separate Route 1 dead-zone encounter row was created by ordinary play.

**Limit:** the COMMIT case ends in a persisted **split conflict**: server verdict A=`none`,
B=`traded`, pending phase=`conflict`. The original target link is unchanged pending human
resolution. This PASS proves the pre-save/commit interruption, clean battery reload,
token-bound `after_reset` declaration, server receipt, and refusal to guess a settlement.
It does **not** prove eventual trade settlement or automatic conflict repair. The raw
[A wire](commit_wire_a_excerpt.jsonl) and [B wire](commit_wire_b_excerpt.jsonl) excerpts are
only an index into the hashed full private transcripts.

Earlier receipts remain failures: `C:/slink-wt/rr-reset-success-dev-b1.log` (GO-order harness),
`C:/slink-wt/rr-reset-success-dev-b2.log` (fresh-install session counter),
`C:/slink-wt/rr-reset-success-dev-f1-056.log` (server canceled a legitimate hidden pre-save),
`C:/slink-wt/rr-reset-success-dev-37.log` (oracle import and premature queued-report exit),
`C:/slink-wt/rr-reset-commit-dev-f1-3383.log` (host waited on an incidental persisted
`done.b` field), `C:/slink-wt/rr-reset-commit-dev-5d.log` (boot witness cleared), and
`C:/slink-wt/rr-reset-commit-dev-121.log` (whole-link-list oracle rejected an unrelated
encounter). The read-only gate diagnostics are archived at
`C:/slink-wt/rr-reset-commit-diag-5d-evidence` and
`C:/slink-wt/rr-reset-commit-diag-2c-evidence`; neither is a reset PASS. No prior failure is
renamed or used as final-cut qualification.
