# CLAUSE-FIX — first live clause failures

Base `c8b06d8120fe161c973b1803a53ce8471ebcbf6a` (integration after the
generated-stub fix and Emerald rival UI merge). No emulator launched here.

The coordinator reported that RELEASE produced no TX and that catches ended
with outcome 4 after a lead faint. The production release branch only logged a
party departure and had no boxed-release path. It now pairs fire-time identity
censuses at `pc_release_begin` and `pc_release`, requiring the same reset epoch
and native stack invocation, complete party/all-box reads and exactly one
disappearance. The key comes from the pre-purge record. No beginning hook,
wrong stack, failed census or ambiguous removal yields a guessed release.

The report enters `owed_reports`, the same response-bound outbox used for
trade reports. A disconnect before the corresponding unrefused reply causes
replay after re-hello. Repeated completion observations do not enqueue a
second release. Tests cover party and boxed releases on FR, LG, Emerald, RR
clean and RR companion, a key present only at the entry hook, and refusal
controls. The native `release_gen3` row already deposits before RELEASE; it
now additionally requires `RELEASE_PREIMAGE` to name a **boxed** source, which
the Python saved-state oracle checks before the durable TX and partner
memorial. Moving-cursor release with no party/box preimage remains unqualified.

The catch driver used B while waiting after a throw. On a wild lead faint,
that declines "Use next Pokemon?" and flees before a forced party screen can
be observed. The input policy now selects A on an observed active HP-zero
mon, sends out the living slot-1 reserve through the existing native helper,
and resumes instrumented throws. It also handles a forced party menu already
up at the top of the loop. Outcome failures include controller 0 and action
cursor diagnostics. Only an observed faint earns the new
`hunt ended lead fainted while catching` RNG class; an unexplained outcome 4
remains FINAL. `runner never released B (A_PENDING)` remains CONSEQUENCE.

`ball_gate_gen3` keeps the native zero-ball pickup/activation and independently
checked saved Ball count. Its bounded budget rises from three to eight whole
runs; only CAUSE_RNG with no unrelated FINAL failure may retry. The general
catch rows retain their existing retry policy. This improves opportunity to
observe a legal one-ball catch, without manufacturing the activation or a
capture. Exhausting eight attempts remains a failed/unobserved live row.

Red-before/green-after controls: missing release TX (eight initial failures),
forced-party/use-next handling and diagnostics (three), RNG classification and
ball-gate budget (five). The full gate initially exposed the existing scenario
selection test's old three-attempt expectation; that expectation now names the
explicit eight-attempt ball-gate rule. No production failure was bypassed.

Validation uses default pytest temporary directories and retention on failure.
The final full-suite receipt is `.cache/clause-fix-full-final.{log,xml}`.
Final result: **12196 passed, 4395 optional skips, zero failures** (544.38 s).
The 20 release/retry controls and 10 catch-driver controls all ran with zero
skips; protocol citation checks and Ruff passed.
Rerun the existing 24 clause rows from integration after merging this fix;
there are no changed fixture prerequisites. SOURCE/MODEL controls do not
substitute for the coordinator's PHYSICAL rerun.
