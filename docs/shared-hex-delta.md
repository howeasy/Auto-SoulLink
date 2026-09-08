# Exact byte-image deltas

`server/hex_delta.py` and `lua/hex_delta.lua` represent same-length canonical
uppercase hex images as ordered, nonoverlapping byte runs. Each run retains its
offset and both the old and new bytes. Neither module contains memory addresses,
cartridge policy, file IO or execution authority.

Python `between(before, after)` produces the compact delta. Both languages expose
`apply(before, delta)` and `recover_before(current, delta)`. The latter permits
each changed byte to equal its old or new value, and restores the old bytes in
the returned image. It refuses any third value. It leaves bytes outside the runs
untouched. Callers **must compare the complete reconstructed preimage digest** to
their owned prepared digest before considering partial-write recovery. A delta
alone cannot establish ownership, validate unchanged bytes or authorize writes.

Gen 1 uses this to keep full snapshots out of command bodies. The server journals
complete prepared images; commands carry compact changes and both image digests.
Fresh command-scoped permission is required for initial writes, explained partial
repairs and save-file persistence. Other generations must supply their own
snapshot geometry, semantic transforms, checkpoint and recovery policy.

The portable tests compare both implementations with varied image sizes through
32 KiB, exact reconstruction, unchanged images, hostile runs and partial-prefix
recovery. The real RBY launchers additionally exercise interrupted writes.
