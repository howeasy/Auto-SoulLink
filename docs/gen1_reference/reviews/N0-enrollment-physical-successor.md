# N0 actual-CLI enrollment: first physical invocation

**HOLD: controller completion predicate was invalid for a quiet bedroom.** This is not a passing N0 receipt or evidence of a production failure. The original controller and all artifacts remain frozen.

Run `run_20260913_175541_a34844`, runtime `51b1b1750061865a2011a36874c2447f`, began 2026-09-13 17:55:41 UTC on HOUNDOOM, docs HEAD9c9b164, product15727ec/source-testsa1714c5. Existing Python3.12 executed `.cache/n0-enrollment-successor.py` (SHA256 `861ff075b400a33425ce94d727635851a75804202e85bf8256054012efb6ca06`) after fresh input/hash and ownership checks. Actual Manager POST/downloads and unchanged product CLI launched two fresh Yellow cartridges; the owner supplied normal New Game inputs. No game-state staging or automated input occurred.

## Observed boundary

- Identity-checked EmuHawk A21120 and B39444 ran under owned CLI42016/43812, with separate private roots and TCP56868. Exact create times and argv are retained in the process JSONs.
- The coordinator read the existing journal through `server.journal_reader.read_journal`, without reopening/mutating the runtime. Checked snapshot revision16 held both clean/released native reattach records, initial observations, New Game bootstraps and initial-save receipt operations. A receipt operation was `710740a4364b4796a3fbe3c45423d2ea`; B was `b4b99dad1da44b2fb4e351d01ba2d423`.
- The owner reported both characters in bedrooms with Gameplay ready visible. Client A's retained cursor was compacted and its inbox/outbox empty. Cursor compaction shows construction progress; it does not alone prove a current service lease or completed release.
- No normal observation had been published. Source `lua/gen1_observation_loop.lua:56` seeds a fingerprint without publishing; its publication predicate at line103 suppresses unchanged, battle-free heartbeat observations without signals/receipts. Root and Claude independently verified this. The controller's nonempty-stream prerequisite was therefore false for its requested idle test. Earlier heartbeat-suspension speculation was not established as this run's cause.

## Controlled termination and retained evidence

The final summary also records a resource cleanup error: `close runtime connections before closing their journal`. The process-survivor audit is clean, but the controller attempted runtime.close before its accepted TCP handlers had completed on the asyncio loop. This is an additional controller defect, not an error-free cleanup receipt; R2 must drain only its owned handlers before closing the runtime. Stop time from the progress receipt is 18:03:49 UTC.

After confirming the invalid predicate, the coordinator terminated only CLI42016 after matching its recorded create time and command. The unchanged controller detected that exit, preserved HOLD, and cleaned its recorded descendants and peer. Unified session57983 completed with exit1 (tool receipt `a8df8e`). The final `a CLI exited before enrollment` exception is the consequence of this intentional stop, not the original reason for the stalled check.

Summary `.cache/n0-enrollment-successor-summary.json` SHA256 `0a73bc911f7c5a0defdabcb39fdeb72a5e5e12c7f843b18a0aabbbde60b9a494`; console `.cache/n0-enrollment-successor-console.txt` SHA256 `f53b9b23e34194aeaf064bfe9fc694b45500d8b95d6d6e193a8357df04618a46`. All four captured CLI/EmuHawk identities exited; survivors and unknown-survivor arrays are empty. A fresh process census found no EmuHawk. Original BizHawk config before/after SHA256 remains `92ca34c62c4db6ed25df2edc4bd1e1c519790c1f3a894623570eb99d914592d6`.

All bundles, client journals, save files, server journal, process/ready/progress records remain under `.cache/n0-enrollment-successor/`. The controller never reached its final file-byte/current-service audit, so the two save ACKs alone are not accepted as that full oracle. No frame-rate, native trade, recovery/resume or gameplay campaign proof follows.

Next: a separately reviewed R2 controller must allow zero normal observations only alongside a current service lease, full audited enrollment, matching save receipts/files and empty queues. Any existing stream must still have contiguous acknowledged observations. Preserve this first invocation unchanged; do not relabel it green.
