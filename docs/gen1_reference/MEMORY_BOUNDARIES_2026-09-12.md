# Live memory boundaries, 2026-09-12 (branch `claude/gen1-memory-boundaries`, base `gen1/rc` 5ff5f17)

Delegated by Codex (task cx-64732c2e): close the six `memory.{red,blue,yellow}.{differential,storage}` rows,
whose unproven clauses batch 1 named (boundary failures; invalid current box, whole empty reserved box,
canonical initiator deposit undo). One new live gate, `lua/tests/test_gen1_storage_boundaries.lua`, run on
Red, Blue and Yellow through `tests/live/test_gen1_gates.py::test_gen1_gate`, plus the existing gates the
other clauses already had. 221 registered / 167 missing of 388 after this lane (the nonlive lane's three rows are not in this base).

## The gate

Seeding and the canonical `_MoveMon`/`_RemovePokemon` trampoline are the ones
`test_gen1_storage_differential.lua` proved; no expected byte comes from a formula. Two oracles:

- **whole image**: WRAM `C000-DFFF`, HRAM `FF80-FFFE`, all 32 KB of `CartRAM` and the SRAM bank register,
  compared byte for byte. The comparator is proven on a one-byte SRAM mutation and a one-byte WRAM mutation.
- **authoritative records**: the differential gate's ranges (party/box counts and species lists, structs,
  OT and nickname arrays, dex owned/seen, current box, bank).

| Clause | Cases | Assertion |
| --- | --- | --- |
| deposit refuses the last party member | box 0, 10, 19 | `false, "last mon in party"`, whole image identical |
| deposit refuses a full current box | party 2 and 6, every slot | `false, "box full"`, identical |
| deposit refuses an invalid slot | -1, count, 6, 1.5, `"1"`, `true`, `nil` | `false, "invalid slot"`, identical |
| withdraw refuses a full party | box 1 and 20, first and last slot | `false, "party full"`, identical |
| positive controls | party 2 / box 19 deposit; party 5 / box 20 withdraw | succeed with the expected counts |
| invalid current box | `wCurrentBoxNum` 12, 13, 127, `$8C`, `$8D`, `$FF` | both writers `false, "invalid current box"`, identical; 11, `$8B`, 0, `$80` are legal and deposit succeeds |
| canonical initiator deposit undo | 60 cases: party 2..6, box 0/5/18, every slot | after the cartridge's own MoveMon deposit, `retrieveBoxMon` of the deposited key equals the cartridge's inverse MoveMon withdraw on a cloned state over the authoritative records, and both counts are restored |
| canonical initiator withdraw undo | 18 cases: party 1/3/5, box 1/7/20, first and last slot | after the cartridge's own withdraw, `depositPartyMon` of the appended slot equals the cartridge's inverse deposit |
| whole empty reserved box, live record hidden | slot 0, 7, 19 of box 12 past a zero count, initialized bit set | `depositMemorialMon` refuses `"memorial box contains a live Pokemon"`, whole image identical |
| whole empty reserved box, dead tail | dead record at slot 19 | the memorial succeeds writing only slot 0 of the struct, OT and nickname arrays; every other byte of the box-12 image past count/species[0..1] and boxes 7..11 of the same bank are byte-identical |

36 refusals per title, each exact and mutation-free.

## Independent correction after code review

The first version of this gate initialized SRAM before testing hidden Box 12 records. That left
the actual first-use branch untested: both the Lua memorial writer and the Python grave append
treated a zero count as empty even when a live/dead record or name tail was hidden beyond it.
The corrected writers now require the entire unowned, pre-initialization Box 12 image to be
empty **before any initialization or grave write**. Count must be zero; the pre-init species
terminator may be zero or `FF` (the cartridge's init installs `FF`); every remaining byte must
be zero or `FF`. An impossible active-Box-12/uninitialized combination is refused. The already
initialized dead-tail rule is unchanged.

The revised live gate adds six first-use refusals per title: hidden live records at slots 0, 7,
and 19, a hidden dead record at 19, an unowned nickname tail, and an unowned species-list tail.
Every refusal preserves whole WRAM, HRAM, 32 KiB CartRAM and the bank register. A genuinely
empty first-use image succeeds and persists the initialized bit. The gate now exercises **42
exact refusals per title**. The Python policy and append paths have a separate 12-case
Red/Blue/Yellow matrix that asserts the detached fields and CartRAM are unchanged before a
refusal. Six initially failing executor tests were stale `operation_held` fixtures; two positive
storage-runtime scenarios had arbitrary synthetic pre-ChangeBox SRAM and now explicitly seed a
clean unowned Box 12, rather than weakening production admission.

The former inactive-box scan test seeded only Box 12. Its replacement seeds a unique valid
record in **all twelve SRAM boxes**, runs all twelve active-box selectors on Red, Blue, and
Yellow, requires exactly eleven inactive SRAM keys plus the active WRAM key, excludes the stale
active SRAM key, and proves each inactive source is read by poisoning it. The direct
`gen1_gatelib.lua` dependency is pinned on all six rows, and exact storage-runtime sibling
pytest nodes are registered on the three storage rows; no manifest row was removed.

Corrected evidence: `SLINK_LIVE=1 python -m pytest tests/live/test_gen1_gates.py -q -p no:randomly
-k storage_boundaries --junitxml=.cache/memory_boundaries_corrected_live.xml` passed Red, Blue,
and Yellow (3 passed, 0 skipped, 56 other gates deselected, 18.20 s), with zero gate checks
failed. The affected non-live sweep passed 254 tests; `tools/lua_syntax_check.py` parsed 302
files. The full 15-gate matrix below predates the correction and is not claimed as a post-fix
rerun.

## Registration

| Row | Clause | Proof |
| --- | --- | --- |
| `memory.<v>.differential` | counts, slots, compaction/append, HP/status, names, lists, dex | `test_gen1_gate[<v>-lua/tests/test_gen1_storage_differential.lua]` (1661 canonical cases) |
| | boundary failures | `test_gen1_gate[<v>-lua/tests/test_gen1_storage_boundaries.lua]` |
| | stats/level derivation | `test_gen1_gate[<v>-lua/tests/test_gen1_stats_differential.lua]` |
| | SRAM bank/checksum, immediate reload persistence | `test_gen1_gate[<v>-lua/tests/test_gen1_storage_persistence.lua]` |
| `memory.<v>.storage` | active box WRAM plus eleven SRAM boxes | `test_gen1_withdraw_and_explode.py::test_storage_scan_uses_wram_for_current_box_and_sram_for_other_eleven` |
| | invalid current box, whole empty reserved box, canonical initiator undo | the boundaries gate |
| | recomputed withdrawn stats | `test_gen1_gate[<v>-lua/tests/test_gen1_boxroundtrip_gate.lua]` |
| | initialized bit/checksum before memorial | the persistence gate |
| | NACK and server-side compensation | `test_gen1_storage_runtime.py::test_unsafe_or_invalid_peer_read_never_writes_peer_and_restores_initiator[invalid_box]` and siblings |

## Live results (2026-09-12, EmuHawk at E:/Howard/Bizhawk)

`SLINK_LIVE=1 python -m pytest tests/live/test_gen1_gates.py -k "storage_boundaries or storage_differential or
storage_persistence or stats_differential or boxroundtrip"`: 15 passed (5 gates x 3 titles, 197 s), JUnit in
`.cache/memory_boundaries_live.xml`. The boundaries gate alone: Red 56 ok, Blue 56 ok, Yellow 56 ok, 0
failed. The first three-title run overlapped Codex's free-service duo gate (a second EmuHawk was live); the
rerun above was made with no other EmuHawk process, same result.

## Re-pins

`tools/repin_gen1_release_hashes.py --write` re-pinned 3,269 entries over 89 rows and 32 files: gen1/rc moved
from aca99ef to 5ff5f17 under the registered proofs (`server/gen1_runtime.py`, `gen1_launcher.py`,
`durable_runtime.py`, `lua/gen1_client_entry.lua`, `gen1_initial_observation.lua`, `gen1_full_save.lua`,
`gen1_held_faint.lua`, their tests) plus this lane's `tests/live/test_gen1_gates.py`. The gate run is the review.
