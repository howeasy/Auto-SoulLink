# Reusable Soul Link subsystem boundaries

The project target is modularity at the major subsystem boundaries. Shared
mechanisms are reused across generations; cartridge semantics stay in generation
adapters. RC work connects those boundaries first. Optional internal cleanup and
optimization can follow without duplicating a generation's infrastructure.

The new [Gen 1 memorial verifier](gen1_reference/MEMORIAL_SAVE_PROOF.md) reuses
the shared save-file receipt contract and the existing RBY full-save/inventory
codecs. Box geometry, party compaction and Yellow effects remain generation-owned.
Prepared command execution and durable reservation integration are still required.

The observation checkpoint helpers are published at `160412c` on
`codex/shared-observation-checkpoints-v1`. See
[their binding contract](shared-observation-checkpoints.md). The exact shared
tree and GitHub CI pass; each generation still owns physical sampling and policy.
The staged party-grant helper is published at `085acbe` on
`codex/shared-party-grants-v1`; [its contract](shared-party-grants.md) requires
generation-owned source, exemption and physical validation before use.
Linked-death staging is published at `6d85974` on
`codex/shared-linked-death-v1`; [its contract](shared-linked-death.md) separates
rule death from generation-owned physical, memorial and recovery completion.
The one-use held-write permit and common operation-scope codec are published at
`bc3ad9de` on `codex/shared-held-write-permit-v1`. They grant no frames; Gen1's
verifier and default-launcher faint selection remain generation-owned.
The follow-up `20b80e31` on `codex/shared-driver-validation-v1` validates driver
identifier factories, clarifies the pacer's transition semantics and carries
the exact `9b3e1fd` test normalization. Production frame modules are unchanged.

| Subsystem | Shared mechanism | Generation-owned binding / remaining work |
| --- | --- | --- |
| Protocol and delivery | protocol.py, connector.lua, client_session.lua, bounded json_codec | Metadata schema, cartridge contract, supported events |
| Persistence and replay | ProtocolJournal, client_journal with atomic typed completions/acknowledged baselines, state_store, journal_reader | Explicit run/bootstrap and physical evidence interpretation |
| Logical identity | IdentityRegistry; player_keys lookup helpers | Acquisition, evolution, NPC exchange, eggs and retirement witnesses |
| Observation checkpoints | observation_stream.lua and keyed_inventory.py | Owned complete snapshots, source predicates, generation limits and rule/command interpretation; checkpoint evidence grants no gameplay authority |
| Engine signal publication | client_journal atomic batches and ProtocolJournal atomic records | Gen1 source hooks retain battle/poison faint and starter call/return witnesses; the frame owner must flush before further execution |
| Rules | SoulLinkState and staged-state composition | Encounter/acquisition categories, cartridge clauses and event validation |
| Exempt party grants | party_grant_rules on detached staged rules | Generation proves source, exemption, party presence and peer; Gen1 joins starter signals and stable inventories before logical acquisition/link formation |
| Linked deaths | linked_death_rules on detached staged rules | Generation proves activation/source/identity, publishes its selected command and verifies physical/storage receipts; rule death alone never completes memorial work |
| Physical commands | command_executor, staged_command and exact body envelopes | Safe checkpoints, ordered child effects, payload codecs and fresh final readback policies |
| Trade | TradeCoordinator and atomic component-composition callback | Receptionist/partner UI, native animation/evolution/save, full rule binding and phase-specific recovery |
| Storage and saves | binary_codec, platform_storage, platform_saveram, save_file_receipt; stat_experience | Party/box geometry, mail/eggs/RTC, canonical storage behavior and full-save transforms |
| Runtime | Shared durable client/server pumps, owned semantic routing and suspension hook (e1d2acf) | Per-generation metadata/stage/adapters, observations and durable interruption policy |
| Holds and recovery | platform_execution, control_service, RecoveryBarrier | Qualified reset/load/rewind handling, rebind and bounded native recovery |
| Bounded frame scheduling | execution_window and frame_pacer; finite scoped credits and monotonic video pacing | Evidence policy, cartridge rate and independently qualified host; no ordinary/recovery authority inferred |
| Held writes | held_write_permit; one expiring use with no frame API | Exact command, pre/postimage, held checkpoint and independently qualified host/write policy |
| Launch and inspection | runtime_launcher, journal_reader | Prepared-run descriptors, complete client-file closures and entry policy |
| Run ownership | RuntimeLease | Acquire before runtime mutation and retain through shutdown; readers remain available |
| Binary patch composition | patch_plan and the existing UPS codec | Canonical source identity, symbol/free-space reservations, companion layout and admission |
| ROM change accounting | rom_change_audit (7a5c7aa), exhaustive read-only validated byte claims | Per-generation canonical source, pointers/aliases, semantic domains and exact serialization |
| UPR generation | upr_catalog and upr_runner: full format, seed/log/name integrity and sequential JVM pairs | gen1_upr_policy, Gen1 Java adapter, full cartridge scan and companion preparation; other generations require their own qualification |
| UI/runtime facts | Shared read-only runtime boundary | Accurate per-generation facts/capabilities; UI owns rendering |
| Source/provenance | Existing pinned-source/build and release-gate patterns | Cartridge content profiles, approved randomizer domains and final artifact validation |

Shared infrastructure is already consumed by Gen1, Gen2 and Gen3 workstreams.
Availability is not qualification: each generation must verify its native policy.
The Gen1 RC notes identify the still-unbound feature paths, rather than calling
an imported module or passing unit suite a completed feature.

The separate bounded host mechanism currently has Gambatte-only evidence. It
must not be treated as mGBA qualification or as a recovery execution grant.

Native partner consent now composes the shared journal/executor/driver/windows
in Gen1. Its prompt layout, native YES/NO evidence and return-before-preparation
rules remain RBY adapters. The runtime performance work improves the shared JSON
scanner and flat execution-scope checks; it introduces no RBY fields into either
module. Reuse these mechanisms when another generation needs them, and introduce
a new shared module when a concrete mechanism would otherwise be duplicated.
The receptionist/full-save continuation adds the shared staged-command mechanism
and remote file-image verifier. Gen1 binds its prompt return, complete save and
preparation stages; RBY native UI, memory layout and save rules remain adapters.
