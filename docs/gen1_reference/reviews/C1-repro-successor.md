# C1 successor first falsifier — MODEL ONLY

The real public runtime reproduces the known W0 rejection with two source-qualified linked pairs. The rejected compound observation is atomic. Reopening retains the acquisition/rule/identity state and keeps recovery held. This report closes no gameplay or release requirement and grants no implementation authority.

Owner: isolated Codex `/root/c1_repro`, HOUNDOOM. Coordinator: Codex task `01a09ae0-ad6f-7b01-8753-5e6b71eb1cfa`. Canonical checkout: `E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2`, branch `gen1/rc`. Acknowledged clean `fd06f58`; activated `343b619`; bounded OS-temp extension `094e1ff`; source remains `19edbb2`. At report verification HEAD was `03955fc0bdcf8c96d1e92e86667ca57ae7a4ec73`; `git diff --name-only 19edbb2 -- server tests lua data` was empty. Concurrent N0/D0b reports belong to their owners.

## Executable result

Run from the canonical checkout with the existing interpreter:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& 'C:/Users/howar/AppData/Local/Programs/Python/Python312/python.exe' -B .cache/c1-successor-probe.py
```

Final run, 2026-09-13 13:44 UTC: Python **exit 1**, intentional red verdict, **4.355 seconds**. The wrapper shell itself exits 0 after reading output; the retained log explicitly records `FINAL_PROBE_EXIT=1`.

```text
JournalError: whiteout found a linked party member its faint settlement left alive
atomicity: PASS: exact journal snapshot/state unchanged; no activation/death/whiteout/outbox publication
reopen: PASS: rules/identities/non-runtime components/outboxes unchanged;
        expected runtime_opened revision +1; recovery remains held
verdict: RED: exact W0 collateral rejection reproduced
```

Durable outputs and SHA256:

| File | SHA256 |
| --- | --- |
| `.cache/c1-successor-probe.py` | `b39fb7efa0d7c99ff23c1156495c14050e2030751b01a06aa874951b6c2372b7` |
| `.cache/c1-successor-probe.txt` | `e9ca47bb33fdb388c2c36334b10fb244c1731a60d86abc8c458232c7a1cae874` |

The final runtime scratch was `C:/Users/howar/AppData/Local/Temp/slink-c1-successor-j6b0mgxy`. The probe checks its resolved containment within the OS temp root and confirms it was removed. Runtime configuration/journal scratch only; imported bytecode was disabled. No production/test-suite edits, emulator, dependency installation, suite execution, or commit occurred.

## Minimal behavioral boundary and fixture qualification

1. Enroll Red/Blue owners, submit synthetic source-shaped bootstrap evidence, and acknowledge the initial saves through public `runtime.process` helpers.
2. Submit Eevee and Lapras grant call/return receipts through public free-service `observation` batches with coherent inventory checkpoints. The second receipt retains the first acquired mon in its call and return party. Grant fresh stats, moves, species, levels, source sites, ROM hash, trainer/OT identity, context and physical-instance bindings come from existing fixture builders and pass the actual production decoders. Both players have matching local mon keys but separate logical ownership contexts.
3. Complete the resulting storage read/apply obligations with the existing storage fixture receipt shapes, sent as public `command_ack` requests. These are synthetic image/file proofs; no real SaveRAM file or physical write is asserted. HUD acknowledgments use the existing unit helper's independent journal lane; HUD transport/FIFO is outside this receipt's claim.
4. Before the trigger, `runtime.state()` verifies four settled acquisitions, four logical members, two ALIVE logical/rule links, two party keys per player, and empty outboxes. Pair keys are `1111:0000:66` in `celadon_mansion_roof` and `2222:0000:13` in `silph_co`.
5. Submit one compound observation containing source-qualified ball activation at frame 210 and a battle-faint signal at frame 211. Its two acquired party members both have zero HP; active slot 0 names the Eevee. The Lapras pair is still ALIVE in rules. This is the exact modeled collateral seam, with no direct rule/identity insertion or mutation.
6. `settle` stages Eevee's death; the same signal's whiteout kills the still-ALIVE Lapras pair in shared rules and emits its collateral peer command; `settle_whiteout` raises. The exact pre-event journal snapshot at revision 27 remains unchanged, including all state, outboxes, activation and death/whiteout records. `open_runtime` validates the retained source history; its intentional `runtime_opened` transaction adds one revision and invalidates recovery authority.

**Scope limit:** these receipts are synthetic source-qualified inputs. The probe does not establish that a natural cartridge execution can leave another zero-HP linked member without an earlier settled callback, or that the original observer would deliver this exact signal history. It proves the accepted model input reaches W0 at the real process/state/journal boundary. There is no boxed-survivor/rebuild, Blue-initiated or Yellow execution receipt here. The two grants are the smallest failing linked-state cardinality; setup includes the lifecycle/storage obligations needed by this public path, not a globally minimal Pokémon route.

## Source anchors

- Existing fixture boundaries: [observation transport](../../../tests/unit/test_gen1_observation_runtime.py#L40) builds the envelope and calls `runtime.process`; [grant synthesis](../../../tests/unit/test_gen1_grant_receipt.py#L50) and [receipt construction](../../../tests/unit/test_gen1_grant_receipt.py#L116) provide original-engine-shaped records; [acquisition fixture metadata](../../../tests/unit/test_gen1_acquisition_runtime.py#L48) provides admitted context/identity bindings. [Storage read/write helpers](../../../tests/unit/test_gen1_storage_runtime.py#L93) define the synthetic receipt path copied into the probe's public ACK adapter. The initial save helper is [public process](../../../tests/unit/test_gen1_initial_save_runtime.py#L69).
- [Acquisition staging](../../../server/gen1_acquisition_runtime.py#L221) redecodes each source row, creates a stable witnessed identity, applies shared capture rules and pairs logical members; [mask restoration](../../../server/gen1_acquisition_runtime.py#L354) keeps physical party authority separate. [Observation staging](../../../server/gen1_observation_runtime.py#L153) defers inventory while physical obligations exist and [schedules storage](../../../server/gen1_observation_runtime.py#L280).
- [Faint signal validation](../../../server/gen1_engine_signals.py#L25) binds source site/shape/identity; lines 72–80 pin active slot, battle species and zero battle HP. [Faint settlement](../../../server/gen1_faint_runtime.py#L117) requires activation and a qualified logical pair; lines 177–230 create the source death and then call whiteout. [Whiteout predicate and rejection](../../../server/gen1_whiteout.py#L30) use the same all-party HP snapshot and reject any collateral force command at line 65.
- [Shared whiteout](../../../server/state.py#L2013) deliberately retires every remaining ALIVE linked party member, excluding boxed members, and emits peer force-faint commands. [Persisted death verification](../../../server/gen1_faint_runtime.py#L396) currently requires a decoded faint whose key and cause match that death, its unique signal-derived identifier, exact logical members, and physical/memorial obligations. A collateral Lapras record cannot truthfully reuse the Eevee's decoded key. [Whiteout verification](../../../server/gen1_whiteout.py#L78) also requires the triggering settled death. Simply removing the rejection or inventing a second direct-faint signal would not supply the missing durable provenance.
- [Observation commit](../../../server/gen1_observation_runtime.py#L88) publishes only after staging; [runtime reopening](../../../server/durable_runtime.py#L92) verifies state, invalidates admission and records `runtime_opened`. This explains the corrected reopen oracle.
- Local original-source HEADs match [pins](../../../data/pret_sources.lock.json#L5): pokered `405b6246372d7e5a2cb029cbb65219b13286b8c9`; pokeyellow `0a0851546ff65f65c4bb2af2b95e279e709a8653`. Pokered `engine/battle/core.asm:1003–1023` places `RemoveFaintedPlayerMon` before HP/status copy-down and `:1455–1469` ORs all party HP in `AnyPartyAlive`; Yellow counterparts are `:1015` and `:1494`. Both `engine/events/black_out.asm:48` dispatch `HealParty`. These are SOURCE facts, not live-engine observations.

## Exploratory outcomes retained separately

The log is append-only within this task and includes three setup failures before the requested trigger. First-pair gift settlement opened storage jobs and cleared usable party keys; the next Lapras inventory was deferred. No W0 claim comes from those attempts. Coordinator then granted existing storage/ACK fixture use. The next attempt reached the exact W0 error and passed immediate atomicity, but its overly strict whole-snapshot reopen assertion failed because `runtime_opened` intentionally changes recovery state. The final run corrects that oracle using verified source behavior. This is not a second product defect or a bypass of storage ownership.

## Smallest next reviewable slice and refusal oracles

Proposed production files: `server/gen1_whiteout.py` and `server/gen1_faint_runtime.py`. Proposed tests: `tests/unit/test_gen1_whiteout.py` for this public-runtime regression and `tests/unit/test_gen1_faint_runtime.py` for collateral provenance/restore/receipt refusals. No shared `state.py`, runtime dispatcher, manifest, Lua or storage writer is proposed from this result. If a truthful collateral provenance representation needs another owning file, return to the coordinator before enlarging the claim.

The next design must define collateral death identity from the triggering validated whiteout plus the acquired roster member, preserve one physical obligation per linked pair, and distinguish that member from the directly fainted slot. This is an unresolved implementation design, not approval of a schema or policy. Independent review must first decide whether the accepted model history is a required settlement case or should be an earlier explicit source-history refusal; this probe alone does not settle natural reachability.

Required focused oracles for an eventual claim:

- Positive: the exact two-pair case records both true logical deaths and their peer obligations atomically; each surviving physical/memorial hold remains until its own verified receipt. A later duplicate callback/replay creates no extra death/command. Existing one-link, one-living-member, pre-activation, and ordinary direct-faint cases remain valid.
- Source/identity refusals: wrong source hash/site/context/ROM/OT; wrong trigger index/key; changed collateral key/blob or non-party/boxed member; missing logical acquisition/link; duplicated or borrowed member; fabricated direct-faint evidence for the collateral pair. Refusal must preserve journal snapshot and both outboxes.
- Restore/receipt refusals: altered trigger-to-member linkage, duplicate collateral identifier, absent or extra physical command, wrong command owner/key/death ID, wrong before/after HP or file proof, and premature memorial completion. Verify the aggregate state and journal after reopen without treating a fresh recovery hold as gameplay continuation.

Next owner: coordinator reviews this first falsifier and the natural-reachability boundary, obtains independent source/fixture review, and records a nine-part accepted claim before any implementation READY. Diagnosis Phase 1 is complete at MODEL ONLY level; no speculative fix was applied.
