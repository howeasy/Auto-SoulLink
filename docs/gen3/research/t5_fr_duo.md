# T5-FR-DUO carrier

This card prepares the first two-client FireRed native trade lane. **No emulator
was run by this card.** All results below are SOURCE/build/MODEL checks; the
coordinator owns the physical runs. READY stays 0 and the candidate receipt
stays `production: false`. No UPS is published.

Branch: `codex/gen3-t5-fr-duo`, worktree `C:/slink-wt/g3-t5-fr-duo`.
Base `4f28fbec`; integration `59aae206` merged as `b055b022`; producer
`cc3c032a` merged as `3ea87ea2`. Emerald resolved the two ABI hunks; the resulting
ABI blob `cd4da5266f1fbf63d3f33e36682ebf9b7d153e26` exactly matches that producer.
This card did not edit producer logic or its build tool. Later carrier/sound/
rival milestones on Emerald's branch are separate from this pinned composition.

## Authorized carrier boundary

The coordinator authorized a **HARNESS_ONLY offer/selection seam** because the
pinned candidate has PREPARE/SCENE/WITHDRAW/STATUS/INFO, but no NPC counter or
chooser/offer opcodes. Both initial and reload receipts must contain:

```text
HARNESS_ONLY native NPC/party-chooser/offer carrier: UNTESTED (HARNESS_ONLY selection)
```

The seam sends the accepted server protocol: A's trade_request, Trade choice,
slot 1 selection, and B's accept/decline answer. Native PREPARE consent and
pre-save, guarded mutation, real trade scene, evolution, native post-save,
host SaveRAM flush, journal and server settlement are **not substituted**.
Ordinary A inputs run only while the native producer owns PRE_SAVE or SCENE.
There are no raw party swaps or native-witness writes in the carrier.

The native NPC/chooser/offer carrier remains required for a later row; this
seam is not evidence of its parity. Emerald's subsequent single-cartridge
carrier proof does not automatically qualify this duo's client binding.

## Test-only admission

`tools/gen3_trade_duo.py` checks the existing private build's hashes, payload,
detours and exact patch closure. Undoing only the source-bound build spans must
recover the SHA1-pinned clean FireRed. An unrelated ROM edit cannot be authorized
by merely changing a receipt digest. No ROM is committed.

The runner creates a private pack projection under
`patch/build/t5_fr_trade_<lane>_<attempt>/`, with a unique nonce. It exports
`SLINK_DUO_FR_TRADE_CANDIDATE=<nonce>` only to its own emulator subprocesses.
The test-only Lua loader requires that nonce, the explicit `gen3_fr_trade` row,
FireRed, an allowed T5 scenario and the exact cartridge digest. It logs the
environment name/value, `production:false`, READY0 and the cartridge identity.

Only that validated loader redirects its local Entry instance to the private
pack. The projection explicitly marks its constructor row `harness_only:true`,
`source_production:false`, and `production:true` to exercise the real consumer's
production gate; it is not a qualification claim. The builder receipt and
top-level manifest remain false. The normal Entry/bootstrap never reads this
projection or the environment flag and rejects the actual candidate with the
flag set. No shipped pack or production admission was changed.

The private checkpoint uses an explicit ABI2 native block: INFO.state must be
CLOSED. The ABI1 byte drawn/ack comparison is preserved for ABI1. All normal
ROM/CPU/write-policy checks remain active.

## Inputs and mandatory oracles

Both sides use the same private FireRed candidate. The two committed FireRed
town saves are copied, then **SYNTH** edits only slot 1's species to Kadabra,
held item/mail to none, and ability selector to 0. PID/OT, genome, nickname,
moves, level/experience, story, map, other party records and boxes are retained.
The native evolution recomputes stats. The manifest records seed/output hashes.
Kadabra's expected trade target is read from the cartridge's pret-derived
evolution table (method EVO_TRADE=5), not from RR data.

The raw evidence binds PREPARE and SCENE publications to epoch, visit, all token
bytes, outgoing identity and each native milestone sequence. ROM-symbol hooks
record `DoInGameTradeScene`, `TradeMons+8`, `TradeEvolutionScene` and
`TrySavingData`. The oracle requires exactly two native saves, commit between
them, real scene/evolution entry, durable final/ACK and both received identity
words. Equal-frame milestones are valid; native timestamps are not used as a
separate host clock.

A coherent sealed journal snapshot is copied while SCENE is published and the
CPU is still paused, before native commit. Python independently decodes the
framing, FNV seals, revision/counter chain and player/ROM/run/trainer-bound intent.
The two players must own distinct journal epochs. The existing client must also
reconcile its journal after receiving the server's committed final.

At the real SaveRAM call, the carrier copies the live flash before calling the
host API and reads the battery file immediately after return. Python requires
byte equality, complete/checksummed sectors, the expected identities/evolution
and exactly +2 save counters before trade_done. A later manual save or exit flush
cannot repair a missing witness. The post-trade scenario issues no manual SAVE.

The server's persisted trade_final must be committed for both players and its
one live pair must migrate to the exchanged keys. Both original emulator
processes then exit normally. The runner cold-launches both again with
`seed=False`, reads actual party RAM, and verifies the saved identities and
evolution survived without another save. The final result gate consumes these
reload receipts, not the initial PASS files.

The decline row requires the server's cancel acknowledgement, no native
PREPARE/SCENE/commit/save, no apply commands, byte-identical party readbacks,
unchanged pair ownership, unchanged save counter, and cold reload. Its explicit
host flush does not issue an in-game save.

## Coordinator live commands

Run from a clean checkout of the completed T5 branch. One emulator lane only.
The candidate build is an offline compiler operation; the following two duo
commands are the **unrun physical handoff**, once each:

```powershell
$env:SLINK_ARMGCC='E:/Google Drive/SLink/patch/vendor/armgcc/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin'
python patch/tools/build.py --target firered --trade-candidate --rom 'E:/Google Drive/SLink/Pokemon - FireRed Version (USA).gba'
python tools/e2e_duo.py --game gen3_fr_trade --scenario native_trade_firered --lane t5-fr-trade --keep-data --wire-log
python tools/e2e_duo.py --game gen3_fr_trade --scenario native_trade_decline_firered --lane t5-fr-decline --keep-data --wire-log
```

The runner supplies the override and unique `--run-id`; do not put either in a
server config or a player launcher. It tracks only its own PIDs for cleanup.
The two T5 rows belong only to `gen3_fr_trade`; the existing RR and normal FR/LG
scenario selections are unchanged. `--list --game gen3_fr_trade` is read-only.

Expected artifacts per row:

- `patch/build/t5_fr_trade_<lane>_1/manifest.json`, private pack files and SYNTH
  saves; original candidate `patch/build/candidate-firered-trade/receipt.json`.
- `patch/build/e2e_<scenario>_{a,b}_result.txt` for initial legs and
  `e2e_<scenario>_{a,b}_native_trade_reload_result.txt` for reloads.
- Raw `patch/build/t5_<nonce>_<side>_<phase>_*.bin` snapshots referenced by T5 JSON
  receipt lines: mailbox/witness, journal/guard, party, flash and flushed disk.
- `patch/build/e2e_<scenario>_pydec_result.txt` with source/ROM/input provenance,
  owned process IDs, HARNESS_ONLY boundary, and independent oracle verdict.
- The printed retained data directory with `links.json`, `server.log` and wire
  logs. It is retained for T5 even without --keep-data.

Success requires both cold-reload RESULT lines and the Python oracle pass.
Initial RESULT: PASS alone is insufficient. On any missing hook, capability,
journal, flush, settlement or reload witness, the row fails by name.

## Verification and follow-ups

T3 review follow-ups are committed separately as `eabd1db3`: a dead trade session
logs its reason once (console only), automatic binding explicitly refuses an
owned context, UNCERTAIN is explicitly excluded from capability, and the host
SaveRAM no-status limit is documented. Logging controls failed before the fix;
284 focused tests passed after it. Equivalent defensive guards retain their
existing behavior and are covered by ownership/phase controls.

Carrier verification includes positive, negative and revert controls for native
binding, flash/file equality, save ordering, identity/evolution, sealed journal,
server final, link migration and cold reload. Lua producer-shaped tests exercise
the actual observer and offer bridge without an emulator. Full-suite results
will be recorded after the committed cut is tested with `g3-env.sh` and
`-o tmp_path_retention_policy=failed`.

The first full gate stopped on the producer merge's stale RR profile `_src`
citations (7,525 passed, 1,202 skipped before fail-fast). Regenerating profiles
changed only RR's 58 source-line references: a recursive comparison excluding
`_src`/`source` proved every gameplay value identical, and the FR/LG and Emerald
profiles were byte-equivalent as data. All 78 profile tests and the generated
write-checkpoint check then passed. This metadata repair is kept separate from
the carrier implementation.


## Final unit/build receipt — 2026-09-27

Carrier implementation: `3ad04f063611d1fae8f0622821dcf8c29af4707d`.
Generated-citation repair: `ed95ba185f0025b8da7ad94d1f59f5fbbca9b6ed`.
Source remained at the latter commit for the completed full gate.

```text
source /c/slink-wt/g3-env.sh
python -m pytest tests/unit -q -p no:randomly -n 2 --dist=loadfile --maxfail=1 -o tmp_path_retention_policy=failed
15041 passed, 1519 skipped in 1381.77s (0:23:01)
Exit code: 0
```

Additional process-local bindings: `PYTHONPATH=C:/slink-wt/g3-t5-fr-duo/.cache/test-deps`
(pytest-xdist 3.8.0, execnet 2.1.1); `SLINK_ARMGCC` as in the live command above;
TEMP/TMP/TMPDIR=`D:/slink-wt/g3-t5-fr-duo-test-temp`. No retained --basetemp was used.
The 1,519 skips are not qualification passes.

Full output: `.cache/t5-fr-duo-full-unit.txt`; SHA-256
`7c7352199a990dae13fbd14c5ba1ce0c2419cff78efe5a44814076e727221a71`.
The two new carrier test files contain 64 controls. The related focused run
passed 1,039 tests with one skip; the final carrier-only run passed all 64.
Ruff passed. All 305 Lua files parsed with the repository checker, and the five
changed/bound native/safety/duo modules also compiled under Lua 5.4.

The private candidate built offline with the specified xPack compiler:
ROM SHA1 `41c66e6b8dceffd295ad8355e3b0a39ecea106f3`, payload SHA256
`b622049ccc5f4521e96bc8c8db1c31ddfdfdcdffbe2e99362cc476d1015c90d4`.
Offline preparation recovered the clean-ROM pin, generated both SYNTH saves and
read evolution target 65 from the ROM. Both live rows remain **UNRUN**, with the
commands and acceptance criteria above handed to the coordinator. No emulator,
production artifact, READY flag, UPS, or master branch was changed by this card.
