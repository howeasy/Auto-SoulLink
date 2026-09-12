# Ordinary frame turnover: measured startup path

This profiles normal Yellow/Yellow bedroom gameplay through the real launcher,
server, frame ledger, journal, and bounded host. It is startup-path evidence,
not full gameplay or vanilla-speed qualification.

The initial 300+ frame trace is `.cache/ordinary-turnover-profile-before-caches.json`, produced
by `.cache/profile_ordinary_turnover.py`. The script records source closure hashes
before and after and refuses results if they differ. Timing wrappers delegate
the original functions without changing authority, inputs, frames, or memory.
The source run is `.cache/gen1-bootstrap-launcher-qng1g2nd`.

| Measurement | Player a | Player b |
| --- | ---: | ---: |
| Completed frames | 312 | 301 |
| Grants | 13 | 13 |
| Granted credits | 780 | 780 |
| End-to-end seconds | 27.216 | 27.442 |
| End-to-end FPS | 11.46 | 10.97 |
| Mean grant reply delay | 494 ms | 508 ms |
| Mean full main-journal publication | 69 ms | 71 ms |
| Median final-step to publication-start delay | 643 ms | 637 ms |
| Mean publication-to-observed-ACK delay | 497 ms | 535 ms |
| Mean bounded host step | 3.69 ms | 3.70 ms |
| Mean active frame-client step | 11.35 ms | 11.70 ms |

The 1000 ms grant deadline starts at the client challenge. About half its lifetime
was spent awaiting the grant; most later ranges consequently consumed only
21–26 of 60 offered frame credits. Per-step work was below the approximately
16.74 ms cartridge frame period. The principal losses were protocol turnover.

A second delay arose because frame closure waited for an in-flight request, but
the runtime could enqueue another control or sync request before returning to
the frame loop. Final-step to publication-start delay reached 1.33 seconds;
the actual main-journal publication was roughly 70 ms. The added
`flush_closed_after_response()` closes an ended range inside a verified control
response callback before another request can be queued. It advances no frame and
consumes no execution credit.

After the bounded pure-validation caches, exact raw-snapshot reuse, and closure
flush were installed, a second source-stable trace completed 323/310 frames
across eight grants per player. The actual acquisition observer hooks were
installed but produced no bedroom acquisitions. Retained evidence is
`.cache/ordinary-turnover-profile.json`, source run
`.cache/gen1-bootstrap-launcher-9grgqbnr`.

| Current measurement | Player a | Player b |
| --- | ---: | ---: |
| Completed frames | 323 | 310 |
| End-to-end seconds | 11.143 | 10.979 |
| End-to-end FPS | 28.99 | 28.24 |
| Mean grant reply delay | 203 ms | 231 ms |
| Mean main-journal publication | 61 ms | 62 ms |
| Mean publication-to-observed-ACK delay | 318 ms | 279 ms |
| Mean bounded host step | 3.89 ms | 3.97 ms |
| Mean active frame-client step | 11.29 ms | 11.17 ms |
| Mean full inventory capture | 27.97 ms | 26.43 ms |

This is about 2.5 times the initial end-to-end throughput, with unchanged grant
lifetimes and clean screenshots on both endpoints. No in-flight closure deferral
occurred in this faster trace, so it does not isolate the contribution of the
response-flush change. Per-step work still fits within the cartridge frame
period. Remaining losses are grant delivery and full-inventory/event/ACK turnover;
this is still not cartridge-rate continuous gameplay.

A cProfile audit on a SQLite backup of this run initially cost 266 ms. Reusing an
exact already-validated raw snapshot for record revision checks, together with
bounded deterministic bootstrap/initial-save caches, reduced it to 169 ms in the
same five-audit profile. Remaining costs include approximately 72 ms of deep
copies and repeated inventory/provenance checks. The current profile is retained
in `.cache/ordinary-state-cprofile.txt`.

An SQL-change-only cache would be insufficient: the measured audit also reads
party_codec.json, admission_profiles.json, and companion_profiles.json. Prepared
cartridges may add other dependencies. Any broader proof cache must invalidate
for those resource contents as well as owned/external SQL changes; current
authority and owner checks must remain fresh.

No wider deadlines or proof bypasses were used. With mandatory stop-and-wait
between finite grants, nonzero request/ACK latency necessarily lowers sustained
throughput. The measured startup path must not be described as vanilla-speed
gameplay until continuous evidence demonstrates an acceptable rate.

## Refresh 2026-09-10 (Claude peer, same script, machine otherwise idle)

Re-ran `.cache/profile_ordinary_turnover.py` unchanged against the current tree
(source run `.cache/gen1-bootstrap-launcher-ehtld3qv`; the previous retained
profile was copied to `.cache/ordinary-turnover-profile-retained-2026-09-09.json`
before the script overwrote `.cache/ordinary-turnover-profile.json`).

| Measurement | Player a | Player b |
| --- | ---: | ---: |
| Completed frames | 321 | 328 |
| Grants (acknowledged sequence) | 8 | 8 |
| End-to-end seconds | 10.339 | 10.497 |
| End-to-end FPS | 31.05 | 31.25 |
| Effective FPS while stepping | 32.44 | 32.91 |
| Persist seconds inside the loop | 1.895 | 1.934 |
| Persist per step | 5.9 ms | 5.9 ms |

Same shape as the 2026-09-09 trace: about 40 frames per grant against 60 offered,
one stop-and-wait publication/ACK per grant, and roughly a third of the wall clock
spent in per-step persistence and turnover. The cartridge period is 16.74 ms; the
loop is at about half rate with no gameplay signals firing (bedroom only).
