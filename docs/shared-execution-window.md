# Operation execution windows: component checkpoint

`lua/execution_window.lua` supplies finite, expiring frame credits for one exact
operation scope. It does not call the host, write RAM, admit a session, issue a
server permission or bypass recovery. The scope includes operation identity and
digest, physical-context generation, admitted-binding digest and a named phase.
The caller recomputes that scope from its owned current command/context.

The frame path copies and compares the five validated string fields directly.
Unknown fields, array-tagged scopes and metatables remain rejected. Detached
challenge copies cannot alter the private pending scope. This avoids JSON
serialization on every frame without changing grant bytes or authority checks.

`challenge()` creates a fresh bounded nonce and records the local monotonic start.
`accept(packet)` requires its exact pending challenge/scope, finite frame/lifetime
bounds and a caller-provided private proof verifier. Verification must finish
before the original deadline, with unchanged scope. Response arrival never starts
a younger lease. `ready()` is read-only authority checking; `consume(scope)` spends
one credit before the host call. Host failure never refunds or retries a frame.
Renewal uses a fresh challenge. Replays, changed scope, expired/exhausted budgets
and invalid proofs provide no credits; clock failure latches the service.

Renewal and explicit revocation do not refund consumed credits. An operation-wide
ceiling (default 6,000 frames, bounded configurable maximum 60,000) remains in
force for the same operation ID across windows, phases, digests and context/binding
changes within this service. Each changed scope still needs its own verified grant.
A replacement service requires
its generation policy to account for any previous physical progress.

Qualification: 31 portable Lua 5.4 window tests, eight Python response-codec tests,
ten real-journal/private-owner checks, three Lua/Python pump checks and two actual
TCP cases (`.cache/operation-authority-final.xml`: 54 passes).
Three actual R/B/Y Gambatte tests (`.cache/execution-window-live-second.xml`)
consume three ten-frame grants, verify exactly 30 native VBlank callbacks/frames,
hold at every exhausted window, and reject an expired grant before another frame.
The issuer/proof remains an explicit fixture. These are not paired network or
production recovery results. The live check exposed and fixed a hidden dependency:
`platform_clock.new()` now loads its own System assembly before creating Stopwatch.

The shared durable client pump has an optional `operation_execution` binding with
dot-call `request`, `accept`, `authorize_apply`, `revoke` and `status` callbacks.
It only accepts grants on validated current control responses, clears them on
initialization/admission/revocation and lets the configured policy require an
operation grant even if an ordinary ticket exists. The default behavior remains
ordinary-authority-only. Gen1 unwraps exact stored bodies before authorization.

`server/execution_window.py` encodes typed verified responses. The separate RBY
binding requires the oldest pending command, fresh paired private owners,
independent generation verification and the exact current journal-state digest.
It rechecks ownership, liveness and journal revision after verification and does
not clear any recovery barrier or acknowledge a command. No default verifier is
installed. Real TCP replay and peer-loss cases refuse further authority.

Remaining: actual cartridge/native evidence verifier, command router and owned
runtime scheduler selection; cancellation/reconnect and controlled recovery.
Current interoperability tests model the physical verifier/effect explicitly.
This API is not yet a frozen shared cut.

`lua/frame_pacer.lua` separately schedules the cartridge video ratio, honors user
pause/lost permission and discards long-stall time debt rather than bursting frames.
It grants no permission. Eleven portable tests and R/B/Y actual normal-speed tests
pass. Pinned Gambatte exposes 262144/4389 Hz; 30 paced frames took about 0.516–0.519s
including held-yield overhead. A full randomized Y/Y native trade passed at normal
speed: 3,223 scheduled frames over 55.43s on player A, both original animations
and files verified (`.cache/paced-native-yellow.xml`, 60.46s test duration).
