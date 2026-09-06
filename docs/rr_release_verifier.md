# RR release inventory and evidence verifier

This verifies RR evidence completeness and consistency. It does not execute the game or approve an unvalidated runtime. It imports no unpublished foundation modules. Python 3.10+ and the standard
library are sufficient; this staging copy was tested on Python 3.12.

`tools/rr/inventory.py` defines mandatory cases; `tests/rr/release_inventory.json` is its uncompleted export. Candidate
hashes and supported postgame checkpoint names are intentionally unresolved. No completed
gameplay records are supplied. Missing implementations and missing captures count as **FAIL**.

## Commands

Run from the source worktree root:

```powershell
python -m pytest tests/unit/test_rr_release_gate.py -q
python -m tools.rr.release --inventory --output tests/rr/release_inventory.json
python -m tools.rr.release --inventory candidate-inventory.json --evidence capture/evidence.json --output report.json
```

`--inventory` without a value exports requirements only; it makes no readiness determination.
`--inventory FILE` loads a candidate inventory. Without that file, verification uses the bundled
unresolved template and fails. The candidate file can append cases but cannot remove or weaken
bundled cases. Re-export `inventory.json` after a deliberate source inventory revision.

Verification writes a full JSON report and a concise human summary. Exit 0 means complete
**declared release** evidence passed; exit 1 means failure or synthetic self-test only; invocation
errors use exit 2. Missing/malformed evidence also produces a failing JSON report. No mtime is
used as evidence. An output path cannot overwrite the input inventory, evidence JSON, or any
referenced artifact, including a symlink/junction/hardlink alias of an existing input.

## Required matrix and acceptance policy

Only RR 4.1 Default Mode is supported. `default_mgm_off` means both players have MGM off;
`default_mgm_on` means both have it on. Mixed-MGM, other RR modes, vanilla games, randomized
profiles and other ROM builds are excluded. Both players need the exact current companion and
matching native ABI2/build/layout/capability descriptor.

The current inventory has **228 required cases: 114 per mode**, including the timing cases.
It has these groups: foundation, admission, storage, battle, acquisition, native,
ghost, presentation, distribution, campaign and soak. Counts are calculated directly from
inventory cases in every report, including missing cases. Twenty **distinct timing scenarios**
exist per mode, each requiring at least twenty meaningful repetitions: 800 total minimum
timing repetitions across the two modes. Repeating an identical schedule under new IDs does
not satisfy this requirement. Every recorded repetition must pass on its first attempt;
failed attempts cannot be replaced by a later passing record.

Each mode also requires at least **7,200 active wall-clock seconds at normal speed**. Turbo time
and paused time cannot fulfill that minimum. The declared start/end interval must cover the
active time. Required completed scenario counts per soak are:

| Scenario | Minimum |
|---|---:|
| Map transitions | 100 |
| Battles completed | 30 |
| Storage roundtrips | 25 |
| Native trades completed | 5 |
| Ghost mode transitions | 30 |
| Reconnect recoveries | 10 |
| Native UI cycles | 50 |

These counts are explicit proposed release policy, not observed results. The coordinator can
deliberately revise the source inventory before declaring a candidate; a supplied JSON file
cannot weaken them. Supported postgame checkpoints must be named in the candidate contract
before validation; an unnamed or empty postgame target fails.

## Candidate contract

Fill `candidate` in an exported inventory:

- `candidate_id`, exact `source_commit`, `native_build_id`.
- `game: "rr4.1"`, `base_rom_md5: "8529f3a45d32bce4da637976fcf269d4"`, `native_abi: 2`.
- `layout_sha256` and `capabilities_sha256`, lowercase hexadecimal SHA-256.
- `bindings`: exact SHA-256 for `source`, `rom`, `patch`, `client`, `data`, `emulator`.
- `fixtures`: separate exact fixture-bundle hashes for both mode IDs.
- `postgame_checkpoints`: nonempty, unique, named supported checkpoints.

The source artifact is the candidate source snapshot; `rom` is the exact **loaded patched ROM**,
`patch` the distributed companion UPS, and client/data/emulator artifacts are the exact files
or stable bundles actually used. Bundle construction/canonicalization belongs to the future
capture harness. Pin a fixture bundle containing the complete fixture provenance, including
each initial save/state. Binding a bundle does not permit silently swapping an internal fixture.

## Evidence shape

The harness supplies one JSON document with these required fields:

- `schema_version: 1`, nonempty `run_id`, `purpose: "release"` or `"self_test"`.
- `candidate`: the inventory's candidate scalar fields through capability/layout digests.
- `artifacts`: map of artifact ID to `{path, kind, sha256}`. Paths are relative to the evidence
  JSON's parent, use forward slashes, resolve to contained files, and are hashed from content.
  Absolute/drive/UNC paths, escaping links/junctions, absent files and mismatched hashes fail.
- `contexts`: exactly both mode IDs. Each holds full `bindings` mapping all seven roles
  (`source`, `rom`, `patch`, `client`, `data`, `emulator`, `fixture`) to artifact IDs, plus `players`.
- Each context has exactly players `a` and `b`. A player records `{player, mode, rom, patch,
  companion_present: true, native_descriptor}`. `rom`/`patch` reference its bound artifacts;
  `native_descriptor` references a verified JSON artifact of kind `native_descriptor`.
- Descriptor contents are exactly `{game, abi, build_id, layout_sha256, capabilities_sha256}`
  and must match the candidate. These must be captured from each loaded runtime by the harness.
- `records`: one record per exact inventory case ID. Every record contains `case_id`, matching
  `run_id` and `mode`, `status: "pass"`, `attempt: 1`, `capture_kind: "live"`, full `bindings`,
  and `assertions`. Self-test records instead require `capture_kind: "synthetic"`.
- Each assertion is `{id, status: "pass", artifact_ids: [...]}`. IDs must exactly match the
  inventory's required assertions, once each. At least one verified artifact is required.
- `accounting`: `retry_policy: "none"`, `omitted_attempts: 0`, exact `record_count`, and exact
  `selected_case_ids`/`executed_case_ids`; `skipped_case_ids`, `xfail_case_ids` and
  `deselected_case_ids` must all be empty.

Timing records additionally contain `attempt_count` and `repetitions`. Each repetition has a
unique nonempty `repetition_id`, `attempt: 1`, `status: "pass"`, the exact `scenario` from the
inventory, all case assertions, and a `schedule` containing exactly:

- `dispatch_offset_frames`: integer -120 through 120.
- `latency_ms`, `pause_frames`: nonnegative integers.
- `disconnect_at`: `none`, `before_stage`, `after_stage`, `after_apply`, `before_readback`, or `after_receipt`.
- `input_pattern`: `neutral`, `a_held`, `b_held`, `alternating_ab`, `mash_a`, or `menu_navigation`.

At least twenty distinct combinations of these meaningful scheduling fields are required per
timing case. The harness must log schedules actually applied; decorative IDs/nonces are not
schedule diversity. Preserve all attempts in the run accounting and capture artifacts.

Soak `observations` contain `normal_speed_wall_seconds`, `active_wall_seconds`,
`speed_multiplier_min: 1.0`, `speed_multiplier_max: 1.0`, timezone-aware `started_utc`/`ended_utc`,
and `scenario_counts` using the table above. The postgame record's `observations` contains
`completed_checkpoints`, exactly matching the candidate's named checkpoint list.

## Boundaries and integration

The verifier checks completeness, contracts, required assertions, accounting and artifact
content integrity. It cannot authenticate arbitrary capture bytes or infer whether a human
or harness truthfully observed gameplay. Hashes bind evidence; they do not replace independent
oracles, actual loaded-ROM inspection, controller-driven scenarios, or trustworthy capture.
The runtime harness must produce real observations and preserve failure evidence. This tool
does not decode GBA ROMs, apply UPS patches, control emulator speed, or validate screenshot
pixels itself; the named distribution/visual assertions require those independent producers.

All positive test manifests are generated temporarily by `synthetic_manifest()` inside this
staging folder and removed after tests. Even a complete `purpose: "self_test"` manifest yields
`SELF_TEST_ONLY`, `release_ready: false`, and CLI exit 1. Those tests verify the verifier and
must never be reported as passing RR gameplay or campaign evidence.

Future integration should connect this standalone gate to the published shared foundation/UI
handoffs and the eventual RR harness, without importing unpublished worktree modules. No repo
files, runtime binaries, user saves, or emulator processes were changed to create this package.
