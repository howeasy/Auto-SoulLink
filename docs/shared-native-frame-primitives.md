# Shared native frame primitives

These modules contain no generation addresses, cartridge policies or host-frame
calls. Each generation supplies its qualified execution and evidence binding.

- `execution_window.new(options)` creates finite, expiring credits for one exact
  operation ID/digest, physical context, admission binding and phase. Its colon-call
  API is `challenge`, `accept`, `ready`, `consume`, `revoke`, `status`. A private
  verifier must approve the exact grant; a credit is spent before any host step.
  Neither renewal nor revocation refunds the operation-wide budget. Invalid scope,
  replay, expired authority or clock rollback cannot provide frames. The closed
  string scope is validated/copied directly on the frame path; metatables and
  array-tagged scopes remain invalid.
- `frame_pacer.new(options)` takes a monotonic clock and integer video-rate
  numerator/denominator. `take(permitted, user_paused)` schedules at most one frame
  and discards long-stall time debt. It grants no execution permission. `status`
  reports its clock/scheduling state. Call the qualified host only after both
  pacing and execution authority allow the frame.
- `json_codec` retains its existing bounded wire API. Ordinary ASCII string spans
  are scanned in the native matcher, stopping at escape, quote, control and UTF-8
  boundaries. Unicode validity and encoded/decoded resource bounds are unchanged.

The modules require the existing shared `json_codec` and `platform_identity`;
callers may supply a nonce generator for window challenges. No new dependency is
introduced. Generation-specific command/ROM/checkpoint validators, suspension,
reconciliation and host ownership remain separate. Importing these modules never
selects ordinary execution, recovery execution or a production runtime.

The Gen1 consumer passes eight actual paired TCP scenarios, including Y/Y,
combined-UPR Y/Y, original native consent/animation, refusal, expiry response and
transport faults. This evidence qualifies that consumer; other generations must
qualify their own cartridge policies and host implementation. The standalone cut
contains only these modules, their portable tests and this contract.
