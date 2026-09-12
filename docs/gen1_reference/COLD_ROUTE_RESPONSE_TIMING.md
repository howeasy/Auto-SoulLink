# Cold-run response timing investigation

The input-only paired Yellow route in `.cache/cold-native-launcher-03kuvxcx`
stopped during the original rival battle at player b frame 13942. Both players'
starters had been source-settled and linked. The refusal was `unanswered ordinary
grant requires reconciliation: response deadline expired`. No further frames
were authorized. This failed route is not native-trade qualification.

Offline measurements use a SQLite backup of that 24 MB journal. The original
evidence remains unchanged. `.cache/profile_cold_control.py` restores admitted
transport-owner fixtures and executes the real `runtime.process` control path,
replaying the retained b grant. `.cache/profile_cold_roundtrip.py` additionally
models a zero-step return and fresh grant on the copied journal. These cases
measure software execution and commits, not live cartridge or transport proof.

| Work | Before changes | After changes |
| --- | ---: | ---: |
| Complete state audit | 155 ms | 100 ms |
| Control without frame sidecar | 161–165 ms | 111–117 ms |
| Retained finite grant replay | 189–202 ms | 132–137 ms |
| All document exports per audit | 30–33 ms | 17–19 ms |

The final full-path modeled return took 135 ms, including a 14 ms commit. The
fresh grant took 156 ms, including a 10 ms commit. A sync took 54 ms, including a
7 ms commit; the presentation projection took 4 ms. Reports are in
`.cache/cold-control-walltime.json` and `.cache/cold-full-roundtrip-walltime.json`.
These are short wall-clock samples, not latency percentile guarantees.

Two bounded changes account for the improvement:

- The shared JSON copy helper replaces domain-object `deepcopy` machinery only
  for `Gen1RuntimeState`'s plain document containers. Every export remains detached.
- `inventory(source, save)` caches successful deterministic decoding through the
  existing bounded `VerifiedContentCache`. Every call includes the complete
  source/save content and freshly read codec-file hash, source save geometry and
  identity offsets. Returned inventory structures remain detached.

Observation metadata/binding/frame/host checks, journal record checksums and
provenance, receipts and current authority remain uncached. There is no global
SQL-version state cache. Deadlines, grant sizes and frame-consumption guards are
unchanged. Tests explicitly warm the inventory cache then alter dependencies,
source/save identity, observation authority and journal records.

The serialized backend means one player's request can wait behind the other's
return or grant processing. The measured return plus fresh grant is approximately
291 ms before client and transport overhead. The previous live timing trace
measured roughly 200–230 ms grant replies on a smaller startup journal, but did
not instrument the failing grown-journal request. Consequently the precise
timeout outlier's division between queueing, client scheduling, server work and
host contention remains unmeasured. The prepared owner-loop instrumentation in
`.cache/profile_ordinary_owner.py` and a new cold live rerun are the next checks.
