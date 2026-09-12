# UPR RC implementation checkpoint

The external runner and complete settings catalog are implemented. Output remains
`produced_requires_semantic_scan`; neither the Manager nor external-ROM admission
may treat this status as approval. All generated artifacts stay in this worktree.

The user supplies the official UPR ZX 4.6.1 JAR, SHA-256
`380dc1e6c704a9a4ed8433e8b7892a149390f8912b9107a2a0e7263cfd71c7d8`.
It was compared with the JAR in the official release ZIP. Source tag v4.6.1
resolves to `7f00eb866ed35c8fe3963f078b6a2e0979dc2b8c`.
No ROM or third-party JAR is included in the distributable changes.

`server/upr_catalog.py` and `data/upr_zx_4_6_1_settings.json` describe all 408
option bits: 146 fields and 24 reserved-bit entries. Boolean, enum, integer and
reserved encodings are explicit. The generator verifies the pinned Settings.java
source and refuses overlapping fields. `server/gen1_upr_policy.py` owns the RBY
allowlist separately. Every forbidden boolean is false, every forbidden enum is
unchanged (or its explicit inactive NONE/LEGENDARIES value), and disabled numeric
controls use canonical values. Ambiguous enum selections and reserved bits refuse.
Effective settings may differ only by the exact source-defined inactive starter
sentinel replacement, checked against the canonical title's starter order.

The stock CLI has no seed flag. SLink's small Java bridge calls the existing public
`Randomizer.randomize(filename, log, seed)` overload, in a separate JVM with an
argument array. It refuses migration, wrong handlers, existing output, and invalid
seeds. The Python runner snapshots the supplied JAR, own bridge, settings, names
and input, and checks they remain unchanged. Logs require exactly one version,
seed and effective-settings line. Pair production runs sequentially, snapshots
names once, requires different exact seeds and writes pair provenance only after
both runs succeed. Failure evidence remains in staging.

Gen1-specific policy is isolated in `tools/upr/SLinkGen1RomHandler.java`; the JAR
is unchanged. It requires one of the exact clean US-English R/B/Y hashes. Source
review found implicit writes that conflict with the locked scope:

- `getStaticPokemon` includes the uncatchable Tower ghost. Its entry is constrained
  to canonical Marowak through UPR's public restricted-pool API. The actual log
  therefore reports the species that was written.
- `setTrainers` disables special trainer moves and the R/B champion branch even
  when the moveset option is false. The adapter preserves those original bytes.
- `setTMMoves` also changes R/B gym leaders' forced moves. Those bytes are preserved
  while the TM assignment and descriptive text use UPR's normal implementation.
- Yellow TM48's 22-byte text allocation can receive a 23-byte stock template for
  twelve-byte move names, overwriting the following dialogue opcode. The adapter
  omits only the exclamation mark in that case, retains the full move name and
  restores the following opcode. The scanner uses source-symbol bounds for every
  TM/starter text span and accepts only that precise correction. Seed 4 selects
  THUNDER WAVE and exercises the real corrected output; reconstructed stock
  overflow is rejected. This was found by checking all 165 move-name extents.

The authoritative recipe includes the Gen1 adapter hash. Its outputs intentionally
need not match the stock CLI's implicit side effects. It does not enable any extra
settings. The independent semantic scan must verify these protected domains too.

Own bridge classes target Java 8. `tools/build_upr_bridge.py` records normalized
source hashes, class hashes and compiler identity. The qualified compiler is
Temurin 8u482-b08; the runtime test uses the installed Java 8. The compiler/JAR stay
local, while only SLink's own small classes and source are distributable.

Evidence: `.cache/upr-pair-final.xml`: 146 passes, no skips, in 19.53 seconds.
This includes 30 actual JAR cases (unchanged, each category and combined on R/B/Y),
each repeated with the same exact seed, three distinct-seed pair cases including
Yellow/Yellow, actual wrong-handler/changed-input refusals, and portable codec,
policy and strict-log regressions. Prior intermediate evidence is retained.

The independent scanner now accounts for every changed byte in the entire 1MiB
image. Immutable pointer roots come from the hash-verified clean image. Evolution
records use bounded candidate pointers, canonical target/family/learnset checks,
and an independently reconstructed UPR packing layout, including aliases and
zero-filled unused space. Other claims validate species, levels, items, exact
starter/Pokédex/gift-access and TM text serialization, intro and Fastest Text.
Every byte outside those checked claims must remain canonical. Generated candidates
also preserve disabled categories and the exact selected trainer-level modifier.
Yellow's rival starter/trainer byte is an explicit shared alias.

`server/gen1_companion_patch.py` applies only the installed, checked companion
spans, verifies all preimages/header/bank bounds, and reverses those exact spans
for the final semantic rescan. Any changed patch byte, unexplained edit, reapply
or preimage conflict refuses. `server/gen1_upr_pipeline.py` runs the full pair
producer, writes flushed final ROM/UPS files, checks their readback and commits
one preparation manifest last. Its CLI is `tools/prepare_gen1_randomized_pair.py`.
The status remains `prepared_requires_runtime_admission`, with `runtime_ready=false`.

Additional evidence: `.cache/upr-structural-first.xml`: 112 passes including
20 corruption domains per title, source/size refusal and structural checks.
`.cache/upr-producer-first.xml`: four actual final-file/pair-publication cases.
`.cache/upr-final-live-matrix.xml`: 13 passes in 261.31 seconds: generated final
R/B, B/Y, Y/Y native trade pairs; all four changed trade-evolution methods on
R/B and Y/Y; two R/B panel cases with 12 native scenarios each. The original
animations and verified files are required even for unchanged received blobs.
These still use owned fixtures, file transport and explicit test authority.

Prepared-artifact adoption now has a bounded held-service path.
`PreparedCartridges` rechecks the full files and reruns both exact recipes in fresh
private staging on every open. Editable JSON/log hashes alone cannot establish a
seed claim: the reproduced bytes and effective settings must match. The resulting
metadata is scoped to that runtime's contract, without changing the installed
default catalog. Final manifests/ROMs are retained in memory as detached/immutable
values. Existing preparation directories are path-bound and require Java plus
their retained generation inputs on reopen; relocation is deferred.

`gen1_run_config` accepts an explicit artifact directory inside the owned run.
Runtime reopening reproduces/revalidates it. The Manager and server generate the
same checked held launcher, and Lua requires the exact loaded final SHA-1 and
strict prepared metadata/capabilities. No gameplay snapshots are accepted through
HELLO, and no ordinary execution is enabled by this adoption.

Evidence: six preparation/rehashed-forgery cases; three scoped runtime/config/
Manager/reopen cases; fourteen Lua metadata/capability refusals; and three actual
R/B, B/Y, Y/Y generated-launcher cases with separate processes/journals, unchanged
frames/RAM and pending commands retained. Logs are `.cache/prepared-cartridges-first.xml`,
`.cache/prepared-manager-admission.xml`, `.cache/prepared-metadata-first.xml` and
`.cache/prepared-launcher-live-first.xml`. The last live matrix passed in20.52s.

The [browser patcher](BROWSER_PATCHER_RC.md) now has real clean and combined-UPR
R/B,B/Y,Y/Y E2E, exact downloaded hashes and refusal coverage with no uploads.
Remaining RC work: Manager generation UI/API selection, external-import workflow,
packaging and full runtime/recovery/campaign qualification.
The legacy `upr_pipeline.py` is not yet switched to this producer.
No generation/runtime publication cut is frozen yet. Optional formatting cleanup
is deferred; CI correctness lint passes. The reusable byte-accounting primitive
is frozen separately as `7a5c7aabd9b9383a2707e9c02ce54095afb58860`.

Primary evidence: upstream `Settings.java`, `Randomizer.java`,
`cli/CliRandomizer.java`, `FileFunctions.java`, `romhandlers/Gen1RomHandler.java`,
`romhandlers/AbstractRomHandler.java`, `constants/Gen1Constants.java` and
`config/gen1_offsets.ini` at the pinned commit, plus the real output logs.
