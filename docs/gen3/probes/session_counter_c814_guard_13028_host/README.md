# Gen 3 session-counter cold-start host probe

**Evidence kind: installed NLua host test, not emulator or final-cut evidence.** The old
counter source was `c814fdd0`; the guarded source was `13028cf9`. Each pair used a newly
created local install root. `manifest.json` pins the two source blobs, the installed
`NLua.dll` and `lua54.dll`, the command shape, and SHA-256 hashes for all 16 raw files here.

| Raw run | Concurrent result | Final baton |
|---|---|---:|
| `old_fail` (`run-025`) | A returned **nil** in 18 ms; B returned **1** | 1 |
| `new_pair` (`run-045`) | A returned **1**; B returned **2** | 2 |
| `new_held` (`run-046`) | A held the OS guard after claiming the baton but before reading; B observed two busy acquisitions. After release A returned **1**, B **2** | 2 |

In `old_fail`, the A and B tokens were distinct. B won the `.born` record and published
generation zero. Both installed-Lua `os.rename(baton, private-name)` calls then reported
success on that published generation. A's immediate read-only check found its private name
absent; `io.open` returned ENOENT and A minted no identity. B read zero and published one.
This reproduces the fresh-install failure without the old 3,000-spin bound expiring. A
separate installed-Lua check confirmed Windows rename refuses an existing destination
with errno 17 and reports a missing source with errno 2.

The guarded implementation keeps the `.born`/`.baton` format and old-value-preserving
publish logic. A permanent FileStream `Share.None` guard serializes the complete transaction;
the contending client yields an emulator frame between bounded lock attempts. In the
deliberately held host run, B could not claim a baton until A released the guard. Guard
release uncertainty suppresses the value. No failed-root counter was reset or repaired.

**Limit:** both clients on an install must use the updated runtime. An older client ignores
the guard, so mixed old/new concurrency is not qualified. The host probe does not prove
BizHawk's startup frame-yield path; a fresh simultaneous emulator run remains required.
