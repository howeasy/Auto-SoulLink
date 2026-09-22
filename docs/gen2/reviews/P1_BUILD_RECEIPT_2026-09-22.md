# Gen 2 P1 build implementation receipt — 2026-09-22

Status: committed and pushed as `93ccb8ee5a12ad892b9db04bbf7341572fc63675`; local reproduction, independent review and both GitHub workflows passed. This is source-build evidence, not an owner G1 signature, runtime qualification or release verdict.

## Source and authorization

Implementation checkout: E:/Google Drive/SLink/.claude/worktrees/gen2-foundation, branch codex/gen2-foundation, baseline645bc73468df11c9d1e60caf405ce73e21d04937. Owner explicitly resumed coding after restarting with ten built-in worker slots. The sole guide remains the dispatch authority.

## Implemented cuts and review

| Component | Frozen SHA256 | Checks / review |
| --- | --- | --- |
| tools/build_gen2_syms.py | 451027d023cc735702b9abf0d0d94a90157ea7684aa76ce09ac9152e473c01c0 | 35 author+independent CLI tests; Ruff; non-author ACCEPT after shell and PATH fixes |
| tools/gen_gen2_admission.py | 81e2a19dccdf5739ebaff64739cb141d63e868c9633bd4b1fa1443d84ec593ab | 43 tests; Ruff; non-author ACCEPT after raw-byte lock fix |
| tools/rgbds_map.py | 6abc59e97e3eba6fd935df28af371061f8b9c91c038f48dff3eaf7fe57144f8b | 52 tests, ten independent boundary probes, pinned-emitter review ACCEPT |
| .github/workflows/gen2-syms.yml | d30fd0feca15bb27609fc7d29d1e13e63a7e0b47bf10e55b21744d7fe7d60edf | Independent review ACCEPT; actual GitHub rebuild/check/upload job SUCCESS |
| tests/unit/test_release_lanes.py | ebecc3432652f94224fbcbe0d99007789c04324ad6e6cfbd5a50e12232c7f9d0 | 19 tests and Ruff; added neutral --list regression |

The builder keeps upstream make recipes, verifies exact source HEADs and clean trees, all four RGBDS versions, executable identities and binary hashes, all four ROM hashes and eight artifacts, then publishes. --check publishes nothing. Existing artifact hashes cannot be replaced through bootstrap. Handled publication I/O errors roll back; crash-atomic multi-file publication is not claimed.

The admission generator records SOURCE-built facts, retains G1=PENDING, and cannot manufacture ADMITTED status. It verifies one raw lock-byte snapshot, matching provenance and actual adjacent artifact bytes. The map parser is reusable RGBDS tooling; free ranges remain CANDIDATE and ownership/persistence UNKNOWN.

## Defects caught and corrected

1. Recursive make expanded an unquoted path containing Google Drive. The invocation uses verified PATH with MAKE=make and explicit tool bindings.
2. Inherited PowerShell SHELL/MAKESHELL interpreted rm -f as a PowerShell alias. Three public-CLI host-environment controls reproduced and closed this.
3. An RGBDS override directory could shadow recorded make/gcc/sh. All seven PATH resolutions now require the same file identity as the recorded executable before building and before publication; impostor cases fail, a same-file hardlink passes.
4. Consumer canonical JSON hashing disagreed with producer raw lock hashing. LF, CRLF and compact JSON now pass with their own correct byte-bound receipts; mismatched bytes/dicts/digests and duplicate keys fail. The CLI parses/hashes one snapshot.
5. A production attempt overlapped a coordinator-authorized builder edit. Its successful output was preserved as an attempt, not accepted as a frozen-source receipt; the final451027 cut was rerun.

## Build evidence

Private source clones, pinned tool verification and raw builds are under implementation .cache/gen2-build. All four canonical ROM SHA1s matched. OMP Gen2-Base task cx-33c0dd87 independently computed4ROMsha1+8SYM/MAPsha256:12/12PASS, plus4ROMsha256 cross-checks. See [OMP audit](OMP_P1_AUDIT_2026-09-22.md).

Production attempts are preserved in .cache/gen2-build/receipts/production-publication*.json and corresponding logs. Attempt3's record mode and same-cut --check both passed under frozen451027/6abc. All eleven publication files retained identical bytes and timestamps through --check; code hashes remained unchanged.

All eight symbol/map outputs are CRLF-only. .gitattributes marks them -text with cr-at-eol whitespace handling; lock/report JSON is LF. All eight staged Git blob hashes matched the recorded artifact bytes before the exact25-file commit. No ROM is a tracked output or CI upload.

The combined focused P1/shared suite passed209 tests. The three admission catalogs are BUILT, with G1=PENDING and no ADMITTED rows; future overlay/ghost targets remain planned and hashless. Crystal1.1 is build-only.

## Authorized remote verification

The owner explicitly authorized pushing only93ccb8e to codex/gen2-foundation in howeasy/Auto-SoulLink and running gen2-syms. Both results were re-read through gh and resolve to that exact head:

- [gen2-syms35739332750](https://github.com/howeasy/Auto-SoulLink/actions/runs/35739332750): completed/SUCCESS. Four-ROM rebuild/check, temporary reproduction, exact non-ROM artifact comparison and upload passed.
- [tests35739332625](https://github.com/howeasy/Auto-SoulLink/actions/runs/35739332625): completed/SUCCESS.

This authority does not authorize a master merge or release. Later P2/P3 changes remain local candidates until their own review/integration.

## Baseline limit

The unchanged645bc73 source snapshot ran once:3247passed,737skipped,5setup errors,0assertion failures; Lua193/193passed and1046sourcefilesunchanged. Five errors require the missing Blue ROM in the isolated snapshot. Skips are classified in root.cache/gen2-orchestration-20260922/baseline/README.md. This is SOURCE/MODEL with unavailable prerequisites, not an all-green Gen1 regression or physical proof.

## Planning corrections

The spec/binding/35-ticket review found only the optional second-review wording in ticket23; coordinator removed if available, preserving the required second review. Stat research/ticket20 corrections were independently ACCEPTED against both exact pret pins. All53 requirement IDs and35 substeps remain covered. F-3 PYDEC/GAME applicability remains unqualified for its later coverage decision.

## Remaining gates

P1 technical source-build evidence above is complete. Owner gate signatures, P2 mapping/source acceptance, played fixtures, runtime binding and physical qualification remain separately tracked; none is inferred from CI success.
