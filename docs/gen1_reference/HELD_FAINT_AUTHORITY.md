# Held faint command authority

Generated initial-observation launchers now select the force-faint adapter for
an exact pending death command. The game stays in its independent fixed-frame
overworld hold. The server issues a separate one-use held-write permit; the
existing frame-window protocol is not used to grant this RAM write.

The existing control service verifies the session, fresh paired owners, oldest
pending command and unchanged journal revision around verification. The Gen1
verifier additionally checks the pending death, original admission/context,
enrolled host and frame, ROM/save identity, exact safe overworld CPU/stack/ROM
evidence, prepared before/after party, and current readback. It refuses battle,
text, scripts, serial/Cable Club/printer ownership, divergent bytes and unrelated
commands. The safe checkpoint data is generated from the already qualified
client profiles and independently interpreted by the server.

The shared permit binds command ID/body digest, context, admission binding,
phase and evidence. It has one use and a challenge-derived lifetime of at most
one second, with no frame budget or frame API. Scope/clock callbacks cannot
extend expiry or restore revoked permission. The client spends it before the
write and checks ownership/frame/permit immediately around the write and its
readback. Unknown commands remain deferred.

Preparation can proceed without write permission. The executor then waits in a
typed pending state, including when the target already has zero HP. Both a write
and a no-op ACK require the fresh permit. The normal command journal persists
intent and receipt; the server's existing exact faint acknowledgement closes
only that command. Initial-history and memorial/recovery blockers remain, and
ordinary gameplay is never released by this path.

Actual downloaded launchers on Y/Y, R/B and B/Y now receive the production
control permit over TCP, clear only the target party HP, and deliver the physical
ACK back to the server. All other WRAM, SRAM and frame counts remain unchanged.
A withheld-permit case retains the command without a write or ACK. The complete
ten-case launcher regression passes in 108.13s (`.cache/held-faint-live.xml`).
The final rerun passes all ten in 56.98s (`.cache/held-faint-final-live.xml`).

These tests seed an explicitly labeled linked/death source fixture from the real
enrolled peers; they do not pretend the actor naturally played through a faint.
The recipient's generated launcher, hold, checkpoint, request/grant, memory
write and acknowledgement are production code. Natural gameplay, battle-write
authority, memorial/save closure, controlled recovery and remaining acquisition
bindings still need release qualification.

The Claude peer tool was rediscovered after the user's schema update. The schema
exposed to this thread retained the documented request/review fields. Two bounded
headless reviews timed out and were stopped without findings; no independent
peer verdict is claimed. Local source checks and executable evidence remain the
basis for this cut.

The broad suite passes 5,073 tests with two existing Windows symlink skips in
432.62s (`.cache/held-faint-full.xml`). The later extraction of the shared
operation-scope codec passes 85 focused and frame-compatibility tests in 33.21s
(`.cache/held-faint-final-unit.xml`). The final portable run passes 4,638 tests
with 437 declared environment deferrals in 364.37s. Four subsequently supplied
generic suspension tests from UI commit `0171d381` were adopted byte-for-byte and
pass separately in 0.30s; they were not part of that earlier portable run.

The five-file shared cut is `bc3ad9de03683725f5dcb4657cd6d4b2c34448a6` on
`codex/shared-held-write-permit-v1`, parent `6d85974`. Its exact isolated tree
passes 3,098 tests with 15 existing skips and 11 subtests in 37.12s, required Ruff
and 228 Lua 5.4 parses. GitHub run 34246610175 is green. No generation verifier
or launcher policy is included in the shared cut.
