# Native runtime wiring cut

All source changes belong to gen1-rby-code-sweep-8d06e2. Default generated
launchers remain held_service. This cut wires the native command lane; it does
not declare ordinary gameplay or the full Gen1 RC ready.

The subsequent [partner runtime cut](NATIVE_PARTNER_RUNTIME.md) adds actual native
consent, acknowledged return-before-preparation, decline and answered-after-expiry
abort. Its stable native TCP matrix passes8 cases in432.37s. Bootstrap and
receptionist origin remain explicit fixtures; consent now uses production policy.

## Connected production components

`lua/gen1_native_runtime.lua` composes the existing durable TCP pump, typed journal,
native preparation/animation/release executors, pinned bounded host, operation
windows, cartridge-rate pacer and owned SaveRAM provider. Preparation/readback
can occur under a hold; staging writes and every native frame need the current
command's verified grant. Unknown commands remain pending and held.

`server/gen1_native_binding.py` selects the verifier from the already owned
contract. Canonical runs supply exact immutable ROM bytes; reproduced UPR runs
use their existing validated registry. The client separately checks all execution
layout fields against the qualified RBY profile before constructing the host or
native adapter. A correct ROM hash label cannot authorize altered RAM addresses.

`NativeExecutionPolicy` checks initial intent/checkpoint against committed paired
preparation, admitted ROM, current context and bounded-host report. Renewals retain
the same intent, original routine prefix and frame continuity. Grants are at most
60 frames and expire after1000ms; the operation ceiling is60000 frames, including
original move-learning UI. Pause consumes no frames. Reopen/recovery does not
inherit an initial native grant.

`NativeTradePolicy` supplies actual receptionist/partner receipt validators,
preparation, native-result verification and rule finalization. Save verification
uses the complete image and the file hash from the owned provider; the server
never opens the remote client's path. It checks canonical save bytes, protects
Hall of Fame and inactive boxes, and permits only the source-defined sprite
workspace outside the independently checked save region.

The shared `TradeDriver` advances accepted offers to preparation, both verified
preparations to COMMIT, and both verified native/files to finalization. The RBY
binding invokes it after typed events and verified control requests. All existing
private authority, liveness and atomic journal checks remain in force.

## Network servicing and copies

The native loop services TCP every200ms and checks frame authority on every owned
step. Its response budget is1000ms; this does not extend native grant expiration.
Heavy terminal file/journal receipt work waits for an in-flight response, avoiding
reply starvation. An exact obsolete grant can only be discarded after durable
completion and can never be transferred to another command.

The shared state store now copies its private validated JSON tree directly on
read. Open/commit still perform full validation, checksum, preimage, publication
and readback checks. This removed repeated parsing of prepared save evidence from
the frame loop. Measured native playback improved from about83s to about48.5s for
2618 frames (about43.8s of cartridge time). Normal network tests require elapsed
time within0.95x to1.15x+1s of that frame duration. The latency fault separately
accounts for its deliberately injected delays.

## Qualification boundary

The actual emulator tests bootstrap a known linked party and supply receptionist
origin as a declared fixture. Partner consent, preparation, TCP,
grant validation, original animation, complete file proof, automatic finalization
and typed release use the production modules. Additional cases cover deliberate
socket loss, delayed renewals and reproduced combined-UPR Yellow/Yellow.

Ordinary bootstrap/observations, natural receptionist initiation,
interrupted/idle-expiry retirement and controlled recovery remain unselected. The cartridge
routine qualified here is SavePartyAndDexData, which writes party/dex/checksum
(and Yellow Pikachu state). It does not establish full world/current-box save
freshness. That pre-trade integration, production launch/save-path isolation,
campaign/storage matrices, packaging and the human session remain RC gates.

The shared snapshot/driver support is frozen at
3801f83a68d2164257684ed2fd81ffffb1b4b917, on top of the corrected CI dependency
baseline e8aa574. RBY-specific runtime/controller selection is not included in that
shared cut. Exact final verification counts are recorded in RC_STATUS_AND_ESTIMATE
and the continuation checkpoint after the final runs finish.

The consumer formatting child e261d1388eefd73159b03211ccf1222da4a4f6c5 changes only
the shared driver and its test formatting/imports. Runtime AST and test bodies
were compared and unchanged; six isolated-checkout tests and full Ruff pass.

Final broad regression: `.cache/native-runtime-full.xml`,4674 passed with the two
pre-existing Windows symlink skips,206.23s. Required project Ruff checks pass and
250 Lua files parse under explicit Lua5.4. The shared formatting child is also
green in GitHub run34124342726. None of these results grants full RC approval.

Final actual native matrix: `.cache/native-runtime-cut-live.xml`,6 passed in
366.86s, with no skipped cases. This includes the deliberate550ms response delays;
normal playback bounds remain unchanged, and the fault case separately accounts
for its injected delay budget. The delayed path records either verified disposal
of an obsolete grant or deferred terminal readback while the reply is in flight.
