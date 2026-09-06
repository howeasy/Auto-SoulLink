# Unstubbed RR withdrawal conversion comparison

`tests/rr/native/test_withdrawal_cpu.py` executes the actual RR4.1
`CompressedMonToMon` entry at `0x090B6A24` in a CPU-only harness and compares all
100 output bytes with the inactive `lua/rr/withdrawal_oracle.lua`. No native routine
is replaced, intercepted, given a fabricated result or bypassed. Code and memory
hooks only record observations. ROM memory is read/execute-only.

This is stronger than a second arithmetic model, but it is **not mGBA, PC withdrawal,
native mailbox, guarded storage, campaign or two-player gameplay evidence**. The
existing RR conversion and storage code remain the production mechanism. The oracle
stays an inactive reference helper; passing this comparison does not authorize its
integration or substitute Lua writes for native conversion.

## Inputs and scope

The base ROM must have SHA256
`679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f`.
The optional selected companion ROM must match its generated native manifest and
that same base-ROM identity. Selected stock conversion and data regions are also
compared byte-for-byte to the pinned base. Normal native build/source verification
remains a separate required lane.

The reviewed companion for this run is frozen `ghost-probe-03`:

- ROM SHA256 `3b69f1c2518fb4487d53f56d6003f328f91d05a9603de7278d9bbce488546301`
- ROM SHA1 `65c6b2739bab54f8ffda590d79ba551a0b7baec8`
- Build ID `a568a586fee86a54150bd09d148f78eb7e85f6b521b58a2d56a043a5dd8d101c`

There are 705 distinct case IDs with 705 distinct 58-byte source records:

| Group | Cases per ROM/mode | Selection |
|---|---:|---|
| Growth/nature | 150 | Each of six growth rows and all 25 PID-derived natures, including high unsigned PIDs |
| EXP | 174 | Each growth row; threshold-minus-one/exact/plus-one at levels 1/2/49/50/99/100/101/249/250, plus EXP 0 and `0xFFFFFFFF` |
| IV/EV/species | 100 | Four IV patterns and five EV patterns across species 25/113/303/1356/1375, including Shedinja, high HP and expanded forms |
| PP bonuses | 256 | Every packed PP-up byte; each slot's counts 0..3 and interactions with other slots |
| Move packing | 24 | Six four-slot patterns with uniform counts 0..3, including empty slots and internal move IDs 512/700 exercising high packed bits |
| Captured Treecko | 1 | Represented fields reconstructed from the independently captured field Treecko record |

IV patterns cover 0/1/15/16/30/31. EV patterns cover 0/1/2/3/4/7/8/251/252/255 and
floor boundaries. Byte-domain edge cases such as six EV bytes 255 and level 250 are
**not assertions of legal campaign acquisition or training**. Learned-move legality
is also outside this conversion test. No bad-egg or active-frontier case is executed;
the oracle explicitly refuses those contexts in its separate pure-reference tests.

Each group runs under both synthetic MGM RAM states and on both ROMs: 24 pytest
groups and 2,820 actual native conversion calls. MGM is set as bit `0x04` at
`0x0203B25A`; Default difficulty/randomizer state is clear. Expanded frontier
flag `0x0930` is explicitly clear at `0x0203B17A` bit 0. Actual native reads must
reach that frontier byte, and no read may cover the MGM byte in these selected
standard-branch cases. The mode bytes must remain unchanged.

## Native execution assertions

Each call starts with a 58-byte source at `0x02010000` and 100-byte destination at `0x02011000`.
The destination is deliberately filled with `0xA5` to check complete overwrite;
this is synthetic setup and does not waive the production destination-vacancy guard.
Distinct 64-byte canaries surround both buffers.

The executable entry hooks must observe every actual routine in this set:

| Address | Native routine |
|---|---|
| `0x090B6A24` | `CompressedMonToMon` |
| `0x090B6924` | `CreateBoxMonFromCompressedMon` |
| `0x0803E774` | `BoxMonToMon` |
| `0x090788FC` | RR stat calculator |
| `0x0804101C` | PP reconstruction |
| `0x0803E7C4` | EXP-derived level |
| `0x08042E9C` | PID-derived nature |
| `0x08043698` | Nature modifier |
| `0x0806E6D0` | Actual flag getter |

The function must return within 200,000 instructions and the two-second per-call
ceiling. Every output byte must equal the oracle; mismatch diagnostics identify the
case, mode, byte offset, expected value and actual value. Source and all canaries
must remain identical. Observed EWRAM writes are limited to the 100-byte destination and the
one established auxiliary byte below, so even a transient source/neighbor write
that is later restored fails the allowlist assertion.

## Established auxiliary side effect

The conversion is not entirely local to its destination. The actual stat calculator
also writes `0x02023FE7`, `gBattleScripting + 0x23` (pret name `levelUpHP`, CFRU
`field_23`). RR stores it at `0x090789EC`/`0x09078AE2`, using the literal
`gBattleScripting = 0x02023FC4` plus 4 and instruction offset `0x1F`.

The available CFRU `CalculateMonStatsNew` source sets this byte from the HP delta
and forces zero to one. Because `BoxMonToMon` clears old max HP before calculation,
the observed byte must be `(newMaxHP & 255)`, or 1 if that value is zero. The CPU
tests assert that value and reject any other EWRAM write outside the destination.
This side effect is retained and documented; the test does not patch it away.
Production scene/party ownership remains necessary before calling native storage.

## Results and provenance

The first full run completed 24 groups and 2,820 unstubbed calls without a discrepancy.
The comparison includes the opaque output marker `+0x4F = 0x80`, exact stats/HP,
all PP values including native move 0 PP, header preservation and zeroed padding.

The Treecko input comes from the same recorded field bytes used by the pure oracle
tests; its raw party SHA256 is
`b9133a60d0c484c4477aadf5e2acd18082c4ce84b735afa285ed2ec98be2490c`.
The field record itself had `+0x4F=0`. This CPU test creates its represented58-byte
input and observes the stock builder produce `+0x4F=0x80`. It does not assert that
the original field record came from a withdrawal.

JUnit properties record classification, number of native cases, exact ROM SHA256,
oracle SHA256 and an ordered hash of each group's input-plus-actual-output bytes.
They are component-comparison provenance, not completed physical release-ledger cases.

Install only the explicit test dependency and run from the RR worktree:

```powershell
python -m pip install --target patch/build/native-cpu-deps -r tests/rr/native/requirements-cpu.txt
$env:PYTHONPATH = (Resolve-Path patch/build/native-cpu-deps).Path
$env:SLINK_RR_NATIVE_OUTPUT = (Resolve-Path patch/build/ghost-probe-03).Path
python -m pytest -q -p no:faulthandler -o junit_family=xunit1 tests/rr/native/test_withdrawal_cpu.py --rr-repo . --rr-rom 'E:/Google Drive/SLink/Pokemon - Radical Red.gba' --junitxml=patch/build/withdrawal-cpu-03.xml
python -m ruff check tests/rr/native/test_withdrawal_cpu.py
```

For the base ROM alone, select
`tests/rr/native/test_withdrawal_cpu.py::test_base_rr_conversion_matches_full_oracle_without_routine_stubs`;
the candidate fixture is then unnecessary. The Windows `-p no:faulthandler` flag
handles Unicorn's documented internally handled Windows exception as explained in
`patch/src/NATIVE_GHOST_MOTION.md`; it does not suppress Unicorn execution errors or
test assertions. No test is skipped, xfailed or silently deselected.

Remaining evidence includes actual compressed-box acquisition/deposit/withdrawal,
full source clearing/count/survivor checks under mGBA, authoritative mode/frontier
context through preparation and execution, reservation/receipt binding, resets and
uncertain recovery, and real paired gameplay. These results do not close S04 alone.
