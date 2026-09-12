# Registration batch 1, 2026-09-12 (branch `claude/gen1-registration`, base `gen1/rc` ffcc118)

Non-emulator closure batch delegated by Codex (task cx-71456305): the 18 ordered-contract rows, and the 3
canonical-validation, 7 unit-protocol and 10 live-memory rows that were missing proofs. Rule applied: a proof is
registered only on a test or validator whose assertions cover the row's description, read clause by clause;
where any clause is covered by nothing, the row stays open and the clause is named here. Hashes were pinned with
`tools/repin_gen1_release_hashes.py` (which uses the gate's own `proof_sha256`); nothing else in the tree changed.

## Registered: 28 rows (187 -> 215 of 388)

| Rows | Proof lane and source | What the registered assertions cover |
| --- | --- | --- |
| `contract.<a>.<b>.hello-{ab,ba}` (18) | `unit`, `tests/unit/test_gen1_sessions.py::test_all_ordered_title_pairs_in_both_hello_orders[orderN-titlesM]` plus `::test_refused_hello_never_changes_rule_identity_or_cartridge_caches[final_rom_sha1-...]` | A real `SLinkServer` from a clean-profile contract for the pair; HELLO in the row's order: both ACK, one shared `admission_epoch`, distinct session ids, per-player variant and adapter selected, a semantic event ACKs and every issued command carries that player's epoch, session, seq and operation id; a wrong `final_rom_sha1` is refused with zero mutation |
| `memory.{red,blue,yellow}.write-safe` (3) | `live-gates`, `tests/live/test_gen1_gates.py::test_gen1_write_checkpoint[overworld-town-<v>]` and `[battle-battle-<v>]` | `lua/tests/test_gen1_write_safety_overworld.lua` samples the production `isPartyWriteSafe` every frame under ROM exec hooks across the overworld, every START-menu row, the real PC menus and selectors, the cable club, blackout, reset and title (Yellow adds PrintBox); `test_gen1_write_safety_battle.lua` proves boot, a real wild battle and the capture naming screen never qualify |
| `protocol.unit` | `unit`, `tests/unit/test_gen1_release_gate.py` (5 outcome cases + inventory drift) | Real pytest subprocess evidence: a skip, an xfail, a non-strict xpass, a module-level skip and a -k deselection are each rejected by the gate, and an expected node vanishing from a passing report is inventory drift |
| `protocol.transport` | `unit`, `tests/unit/test_connector_fragmentation.py` (3), `test_gen1_runtime_server.py` (reconnect replay), `test_gen1_command_validation.py` (2 NACK cases), `test_client_invariants.py` (2, deferred executor, source-pinned) | Partial send offsets resume exactly, split receives reassemble once, queue bounds refuse and recover, a replayed operation id after reconnect yields no new events, an injected handler exception NACKs and the next command runs; the deferred-executor clause is proven by source pinning only (stated in the basis) |
| `protocol.admission` | `unit`, `tests/unit/test_gen1_sessions.py` (refused-hello params, stale epoch, contract rotation), `test_gen1_admission.py` | Wrong final hash, profile hash, capabilities and nonce each refused with zero mutation; a stale `admission_epoch` NACKs a semantic event; a rewritten contract rotates the epoch and de-admits both players; a rejected hello queues no write |
| `protocol.transactions` | `unit`, `tests/unit/test_protocol_journal.py` (4), `test_gen1_sessions.py` (seq), `test_gen1_player_scoped_rules.py` (collision) | Durable operation ids replay without duplication and refuse a changed payload, nonces are durable and per-player, skipped sequence NACKs, explicit ACK/NACK receipts are durable and immutable, a refused commit mutates nothing, duplicated keys collide before any rule effect |
| `protocol.server` | `unit`, `tests/unit/test_gen1_runtime_server.py` (3), `test_gen1_sessions.py` (real TCP), `test_manager_http_hardening.py` | A faint over real TCP kills the link and holds the partner; HTTP reads work and unbound writes refuse with the journal unchanged; an unconfigured durable hello cannot fall through; the Manager proxies a write into a live run and persists it |
| `protocol.ap-regression` | `unit`, `tests/unit/test_legacy_hello_admission.py`, `test_runtime_boundary.py`, `test_gen1_staged_state.py`, `test_gen1_strict_profile_contracts.py` (2) | red_ap and blue_ap hellos keep the existing adapter and command behaviour, do not inherit RBY restrictions, cannot use the staged store, and every inherited new R/B field is nil in AP unless independently verified against the alchav symbols |
| `canonical.constants` | `constants` validator (87 rows), `party-codec-data` validator, `unit` negative control `test_gen1_strict_profile_contracts.py`, codec min-level `test_gen1_party_codec.py`, SRAM checksum `test_gen1_sram_boxes.py` | Capacities, layouts, name alphabet and terminators, PP and status masks, big-endian stats, SRAM geometry and checksum invariants from pinned source; the codec and min-level clause that `canonical.structure-limits` deferred here |

## Left open: 10 rows, with the clause nothing proves

| Row | Unproven clause | What would settle it |
| --- | --- | --- |
| `memory.{red,blue,yellow}.differential` | "boundary failures": no gate asserts `depositPartyMon` refusing last-mon (pc=1), box-full (bc=20) or an invalid slot, nor `retrieveBoxMon` refusing party-full; `test_gen1_storage_differential.lua` iterates legal counts only | one clone-state refusal gate asserting refusal plus a byte-identical WRAM/HRAM/SRAM snapshot; everything else in the description is already asserted by the differential, stats and persistence gates |
| `memory.{red,blue,yellow}.storage` | "invalid current box refusal" (no gate drives `wCurrentBoxNum >= 12`), "whole empty reserved box" (no gate seeds a non-empty Box 12 tail), "canonical initiator deposit undo" (server-side only, no live gate) | three small gate cases; the other clauses are asserted by `test_gen1_writes_gate.lua`, `test_gen1_storage_persistence.lua` and `test_gen1_boxroundtrip_gate.lua` |
| `memory.yellow.pc-restrictions` | only the deposit permission branch is proven (`test_gen1_yellow_pc_policy.lua`); release permission, happiness, synchronized boxing and the confirmation/menu/rollback proof the description itself requires are not | a Yellow gate driving the real Bill's PC deposit and release menus to confirmation on a disabled starter with a rollback snapshot |
| `protocol.dom` | "stream active-run pins": nothing exercises `/api/stream/pin` or `RunManager._active_stream_run`; "capability-gated controls" is proven server-side only | one aiohttp test pinning a registry run and asserting the overlay context follows it; the other clauses have ready proofs in `test_routes_smoke.py`, `test_gen1_presentation.py`, `test_http_server_security.py`, `test_manager_xss.py`, `test_rom_type_routing.py`, `test_gen1_archipelago.py` |
| `canonical.rom-layout` | "UPR pointer root": no validator or test byte-validates the `upr_layout.json` roots against the pret symbols and the clean ROM (only `TradeTableOffset` is checked, in the NPC-exchange generator); the other five clauses pass in `verify_gen1_rom_layout.py` (37 ok) | a rom-layout check that each profile root equals its pret symbol and the ROM byte at the root |
| `canonical.generated-data` | "maps" (`area_map.json` is hand-maintained), "every encounter method" (no rod tables), "moves" (`moves.json` has no source check), "trainers" (class names checked against a transcribed list, no parties), "types" (adapter table not cross-checked); encounters, statics, gifts, items and evolution families are proven | a pinned-source `--check` generator or test per clause, as `test_gen1_items.py` does |

## Adapter-isolation read of the shared modules Phase 6 touched

Only one shared (non-`gen1_`, non-`rby`) runtime file changed in Phase 6: `lua/instruction_executor.lua`.
`server/instruction_authority.py` was not touched and reads generic. One leakage worth a follow-up in the shared
layer, not fixed here: the executor assumes a Game Boy CPU model. `lua/instruction_executor.lua:39` reads the
loaded-ROM-bank register through a field named after the pret RBY symbol (`authority.addresses.hLoadedROMBank`),
`:46` computes the return address as a 16-bit little-endian word at `sp`, and `server/instruction_authority.py:31`
carries `bank` in `ENVELOPE_FIELDS`. A GBA binding (32-bit stack, no ROM banks) cannot satisfy that contract
without a platform seam; the binding plan step c already lists the mGBA hook-offset question, and this belongs
beside it. `server/battle_force_authority.py` and `lua/battle_force_authority.lua` are RBY bindings by design and
are placed correctly.

## Verification

- `python -m pytest @.cache/batch_unit_nodes.txt -q -p no:randomly`: 56 passed (every unit node the batch registered).
- `python tools/repin_gen1_release_hashes.py`: 0 stale, 0 missing.
- `python tools/verify_gen1_release.py --list`: 215 registered / 173 missing.
- `python tools/verify_gen1_release.py --quick` and the inventory refresh: recorded in the commit message.
