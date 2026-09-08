# Single-use held-write permits

`server/held_write_permit.py` and `lua/held_write_permit.lua` implement an expiring
one-use permission bound to the existing command scope: operation ID, exact body
digest, physical context generation, admission binding digest and phase.

The server's generation verifier constructs `VerifiedHeldWrite` with an evidence
digest and the current journal-state digest. `issue` only encodes an exact
challenge response. It does not validate a cartridge or confer authority by
itself. Responses contain `uses=1` and a lifetime of at most 1,000 milliseconds;
there is no frame count or frame-execution API.

The client supplies a monotonic clock, current scope and private proof verifier.
Its deadline starts when the challenge is created, so transit and verification
time consume the lifetime. Callback-time expiry, scope changes or revocation
cannot restore a grant. `consume()` spends the write permission before the
caller invokes its adapter. `valid()` can still authorize readback until the
same deadline, but cannot refund the consumed use. Replays and malformed
responses fail closed; `revoke()` removes outstanding challenges and grants.

Generation bindings retain independent physical holds and prove their complete
preimage, expected postimage, permitted addresses and safe checkpoint. They
must also check ownership immediately around their writes/readback. A permit
does not authorize ordinary frames, saves, recovery or arbitrary memory access.
No-op completion still needs the binding's fresh permit and readback.

The Gen1 consumer selects only the oldest pending death's force-faint command
under its original fixed-frame overworld hold. Other generations must provide
and qualify their own physical and journal policy before using these helpers.
