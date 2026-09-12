# Shared helper boundary corrections

Independent RR/GSC review of9704623 reproduced three defects: matching malformed
expected/reported host profiles could pass save-file validation; callback-time
context changes could cross an effect or final ACK boundary; sparse stage lists
could omit a required child. A configured converter returning nil also silently
fell back to generic results.

The corrected file verifier validates both host identifiers as plain bounded
ASCII identifiers and still requires exact equality. The private caller retains
responsibility for selecting a qualified host; this generic helper is not a host
registry. Valid existing Gen1 host constants are unchanged.

The staged adapter rejects sparse/keyed/empty lists, captures callback references,
validates converter configuration and requires a nonempty object from a supplied
converter. It rechecks physical context after callbacks, before effects and durable
progression, after commits and after final verification/conversion. A failed or
changed-context child cannot lead to another child's effect or an outer ACK.

The stage tests now use the exact shared Lua5.4 fixture from d3e773ce. This corrects
the previous dependency-default Lua5.5 model runtime; existing actual BizHawk and
explicit Lua5.4 parse results retain their original scope. The shared syntax
runner is now explicitly Lua5.4 as well.

Evidence: nine matching-invalid host cases reproduced before the correction;
callback/configuration repros are in `.cache/staged-callbacks-before.log`.
After correction,112 shared client checks pass under explicit Lua5.4 and two
actual saved receptionist/trade consumers (Y/Y and R/B) pass in153.41s. Exact
isolated shared tree:3052passes,15 unchanged baseline environment/fixture skips,
11subtests,46.80s. The behavioral head eefcbba is green in GitHub34183759047.

The branch `codex/shared-staged-command-v1` contains host-shape child89ef524,
behavioral/context/configuration child eefcbba and syntax-runner child77c7562.
The last child changes only the syntax runner and parses226 shared-tree Lua files
under confirmed Lua5.4. Full Gen1 source/fixture regression and final child CI
results: `.cache/staged-correction-full.xml`,4803passes with the same two Windows
symlink skips,201.25s. Exact bug-class Ruff checks and257 explicitLua5.4 parses
pass. Final head77c7562 is green in GitHub34183965202 and verified on the remote.
Current collection contains4658unit/147integration/227live/45duo cases; collection
is not new execution evidence for the unchanged full live matrix.

GSC independently confirmed the sparse-list/nil-converter/malformed-host repros
are fixed under Lua5.4, with123 focused checks and its complete32790-byte image
still valid. The native Y/Y and R/B smoke checks above are the current live
consumer evidence for this helper-only change; the prior16-case native matrix
retains its earlier cutoff.

These corrections do not enable ordinary gameplay or recovery, and do not change
the RBY save layout or original trade animation. Consumers should adopt the latest
corrected shared head rather than9704623.
