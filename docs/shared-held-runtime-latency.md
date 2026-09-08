# Bounded held-service work

The shared durable client now gives queued semantic traffic one opportunity
after a completed control response, even if the soft heartbeat interval elapsed
during that response. The watchdog, response deadlines and authority checks are
unchanged. This prevents slow but timely control roundtrips from starving large
durable ACKs. No new frame or mutation permission follows from the scheduling
change. A synthetic Lua transport regression verifies control/receipt progress
with roundtrips longer than the soft heartbeat interval while the host stays held.

`durable_runtime:is_bound()` returns the same binding availability used by status
without copying a large execution receipt. `status({summary=true})` omits that
receipt; the default `status()` remains unchanged. Callers needing actual proof
must still read the journal or full execution result.

`state_store:revision()` exposes the current in-memory, committed revision without
cloning the payload. It refuses a closed or faulted store, just like `read()`.
It is a cache invalidation token, not filesystem tamper proof. `commit()` retains
its external-file comparison and atomic readback checks. Gen 1 caches its immutable
pending command scope only until that revision changes.

`platform_saveram.new` accepts an omitted `path` to bind the current configured
host SaveRAM path once. Explicit paths retain their existing checks. Both modes
verify the pinned host/core and recheck the same destination and caller authority
before and after flushing. Host qualification may be prepared read-only; each
actual flush still requires the generation's current private authority.
