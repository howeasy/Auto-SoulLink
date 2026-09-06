# Portable CI and local release evidence

`python tools/verify_portable_ci.py` runs the unit and integration tests that can
be validated from a public checkout on Linux or Windows. Its result is a
**portable CI verdict, never release approval**. The GitHub job has the same name
and uploads `.cache/portable-ci/report.json` on success or failure.

`tests/portable_ci_inventory.json` lists every collected unit/integration node
exactly once, including each parameterized case. A group records the required
local inputs, supported platforms, and the reason for its classification. This
is a reviewed list, with no module-wide or wildcard exclusions. Adding, deleting,
renaming or changing the parameters of a test requires an inventory review.

The plugin selects tests before fixture setup. It does not inspect the machine
and quietly change coverage when a ROM, source cache or JAR happens to exist.
Every deferred node appears in the report with its group, input requirements and
reason. Resource descriptions include the local provisioning path. Deferred
tests count as deselected in pytest's own output, not passed or skipped.

The lane fails on an unclassified or missing node, duplicate classification,
collection failure or skip, or additional deselection. Each selected test must
pass setup, call and teardown exactly once. Skips, XFAIL, XPASS, teardown failures,
`--collect-only`, and selectors such as `-k` that omit an expected test cannot
produce a passing report. The report always contains `release_approved: false`.

Linux runs the actual symlink escape checks. Windows runs the actual NTFS
junction escape checks and explicitly defers the two symlink cases that require
optional Windows symlink privilege. The full local suite still runs those
symlink cases normally; this policy does not remove their existing assertions.

The other deferrals cover actual clean cartridge bytes, pinned source or full
build provenance, the built Red companion ROM, real UPR/Java execution, and the
installed Crystal apworld oracle. Synthetic codec, protocol, recovery, HTTP,
manager, filesystem, and cross-generation regression tests remain in the lane.
Tracked battery-save fixtures and generated data are ordinary checked inputs;
their absence is a failure rather than a reason to defer more tests.

Some source mutation tests previously passed without their source inputs because
the verifier reported missing evidence before reaching the intended mutation.
They are explicitly classified as local source tests. The manager's injected
publication-failure case likewise needs clean dumps to reach publication. Their
assertions have not been changed or counted as portable proof.

## Updating the inventory

Run `python -m pytest tests/unit tests/integration --collect-only -q` to inspect
the actual node IDs. Review the changed tests and their fixtures before adding
their exact IDs to the appropriate group. Use `portable` only when the test uses
tracked inputs, synthetic fixtures and the declared Python dependencies. A new
external input needs a resource description and provisioning instructions; do
not classify from a failed run or broad filename match alone.

Run `python tools/verify_portable_ci.py` after the update. Check both the selected
and deferred lists in its report. The inventory is intentionally not regenerated
automatically from whichever tests happen to pass on a developer's machine.

## The local release gate stays strict

Ordinary `python -m pytest tests/unit tests/integration` does not load this
selection policy. `tools/verify_gen1_release.py`, its evidence plugin, release
inventory and input/requirement manifests are unchanged by the CI policy.

The full Gen 1 release gate still requires all pinned inputs and its unit,
ROM-layout, Lua-parse, profile-address, patch-build, live emulator and paired
cartridge lanes. Missing inputs, hash drift, skips, XFAIL/XPASS or deselection
remain failures. `--quick` is still not a release verdict. Passing public CI
does not qualify the native trade path, UPR publication or durable production
bindings.

## Reviewed UI Phase 0 inventory addition

UI integration adds 28 exact nodes: 14 archived-fixture shape/content checks,
5 isolated hydration/refusal/key-index checks, and 9 offline inventory/parser/
router-parity checks. Their inputs are tracked data, synthetic state, temporary
directories, the Git checkout and existing Python dependencies; none need a ROM,
JAR, emulator, live run or application startup. They belong to `portable`.
No existing node was removed or reclassified. The resulting Phase0 inventory
contains 3694 nodes, with 3386 selected and 308 explicitly deferred on each
supported profile. Later phase additions require their own inventory review.
