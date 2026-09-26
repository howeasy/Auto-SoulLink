# Shared fixture qualification orchestration

`tools/fixture_qualification.py` owns bounded enumeration, immutable byte snapshots,
ordered required-stage invocation, receipt binding, and aggregate reporting.
It never generates a save, launches an emulator, knows a cartridge checksum,
decodes a Pokémon, or declares a release/physical gate complete.

The interface is `enumerate_fixtures(directory, suffix=..., max_fixtures=...)`
followed by `qualify_fixtures(cases, callbacks, scope=...)`. A `FixtureCase` names
artifact paths and textual source provenance. `StageContext` supplies immutable
artifact bytes, source facts, the current stage, and a fingerprint. A callback
returns an explicit `StageReceipt` with that stage/fingerprint, status, diagnostic
text, and nonempty evidence for PASS. Any produced artifact paths belong in
`outputs`; the runner reads and hashes them for the following stage.

Two scopes have fixed required chains:

| Scope | Required stages | Meaning of `passed` |
|---|---|---|
| `static` | `qualify` | Only the game's static byte oracle passed. |
| `full` | `qualify`, `boot`, `resave`, `post_oracle` | Every registered stage returned a valid PASS receipt. The game owns what each oracle proves. |

Full qualification refuses before invocation if any callback is absent. Re-save
must return an output artifact; its observed bytes become `resave:<role>` inputs
for the independent post-oracle. The original inputs remain immutable. The runner
does not infer successful boot/readback from a process exit, a log substring, a
checksum alone, or an earlier static PASS.

Each fingerprint binds the attempt ID, fixture name, scope, complete ordered chain,
source provenance, observed artifact hashes, and preceding receipts. Replaying a
receipt from another attempt/input/stage fails. Artifacts are re-read before and
after each callback; a changed input or re-save output refuses. A callback exception,
FAIL, SKIP, malformed receipt, missing artifact, empty inventory or exceeded bound
cannot become PASS. No callback is invoked after a failed stage. Default limits are
64 cases, 64 artifact roles, and 64 MiB per artifact; callers can lower the bounds.

Produced outputs join the inventory-wide immutable path/hash ledger. A later case
cannot replace an earlier artifact with different bytes and still qualify. Before
returning, the runner revalidates every row's complete input/output artifact set;
any stale earlier row loses its PASS, even if its own post-oracle passed earlier.
Use distinct immutable output snapshots for independently qualified cases.

Reports contain required stages, actual input/output path/size/SHA256 records,
per-stage receipts and failures, and the aggregate boolean. They contain no ROM
or save bytes. The shared module writes no files. A caller may serialize a report
when its task authorizes that publication.

## Gen 1 binding

`tools/gen1_fixtures.py` rebinds `--qualify` through `qualification_report()`.
The existing `qualify(sram, rom, notes)` remains the independent game-owned oracle:
save size, main/backing-box checksums, party decoding, growth-curve consistency,
and the native stored-stat band remain there. Its implementation is unchanged.
Cartridge selection, source dependencies, fixture naming, party summaries and
scripted-play generation also remain Gen 1-owned. The shared module never imports
the production Lua reader or incorporates it into PYDEC.

The Gen 1 binder includes the scanner's symbol/admission/anchor/profile JSON inputs
in its artifact set. During the oracle call it temporarily fills that independent
scanner's lazy caches from the captured bytes, restoring prior caches on every
exit. An old process cache therefore cannot pretend to validate freshly hashed
source files; neither is mutable disk text read behind the captured provenance.
The Gen 1 tool runs synchronously; this binder is not a concurrent service over
the scanner's module-level caches. Callbacks likewise run synchronously and own
their timeout/process policy through the existing game harness.

The ordinary CLI preserves one diagnostic per fixture and does not launch an
emulator. Missing/empty inventories now fail instead of vacuously passing. `LEGACY`
remains a diagnostic label; it cannot qualify bad bytes (the current allowlist is
empty). `qualification_report(scope="full", stage_callbacks=...)` is the explicit
seam for an authorized game boot/re-save chain. It has no default live callbacks,
and callers cannot replace the independent `qualify` callback through this seam.

Tests exercise a second synthetic game binding, complete and missing chains,
stale attempts, changed inputs/outputs, failed independent oracles and the Gen 1
rebind. These are MODEL controls. No Gen 2 fixture inventory or physical boot,
re-save, gameplay, or durability evidence is created by this extraction.
