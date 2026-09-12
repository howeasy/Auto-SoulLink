# Shared server runtime lease

`with RuntimeLease(path):` holds one OS-backed exclusive lock for cooperating
server processes using the same lock path. The parent directory must already
exist. Use it before opening or mutating the runtime journal; retain it until
connections and that journal close.

Windows uses a nonblocking `msvcrt` byte lock; other supported Python platforms
use nonblocking `fcntl.flock`. A competing acquisition refuses. Closing the exact
owned handle, including process exit, releases ownership. The persistent lock
file is not a PID marker and is not deleted to recover ownership.

This does not lock the SQLite database. Independent read-only snapshot/WAL readers
remain available. It does not grant cartridge admission, execution authority or
protection from noncooperating code that ignores/replaces the lock path.

Five tests exercise actual Windows lock exclusion, separate Python processes,
normal/exceptional release, failed contenders and journal/WAL readers. No emulator
or generation is activated by this helper.
