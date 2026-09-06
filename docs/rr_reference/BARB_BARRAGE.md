# Barb Barrage calculator branch

The calculator had two `Barb Barrage` switch cases. The first joined Hex's
any-status/Comatose multiplier; the later poison-only case could never execute.
Only that later block was removed. Removing the first label would have changed
existing RR calculator behavior for burn, paralysis, sleep, freeze and Comatose.

The actual calculator sources were executed for level50 Qwilfish-Hisui against
level50 Snorlax: healthy60BP/46–55 damage; each of the six status values and
Comatose120BP/93–109 damage. All eight current-source cases pass and match the
preserved original. The source diff was checked to contain only removal of the
unreachable block. [Replay identities and results](barb_barrage_replay.json).

```powershell
node tests/rr/reference/barb_barrage.cjs . 'E:/Google Drive/SLink/calc/calc/node_modules/typescript'
```

The dev TypeScript package is explicit and pinned by the script to4.9.5. It compiles
the actual selected source in this private Node process, writes no emitted modules
and requires no repository fallback for calculator source files. This is not a
browser build, extracted-player-package smoke test or admitted-ROM damage test.
The exact RR damage hook and observed live inputs remain separate validation gates.
