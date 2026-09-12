# Native UI client integration

The native receptionist and partner prompt now feed the existing paired trade
coordinator through durable client journals. All nine ordered RBY combinations,
including Yellow/Yellow, pass the integrated native UI-to-animation test. The
older nine paired COMMIT-to-save cases also pass:18 cases in180.73 seconds in
`.cache/native-ui-pairs.xml`. This is a controlled cartridge integration test,
not default-launcher, production network or host-recovery qualification.

The initiator presses the existing receptionist, selects SLINK TRADE and chooses
its linked party member. `gen1_receptionist_client` observes the actual native
entry before replying at the source-pinned query/offer wait points. It retains
the visit token, generation, full party snapshot and selected key. A durable
offer and its detector marker publish together. The native “offer sent” result
is written only after the exact server ACK is retained in the journal baseline.
A query marker alone, a changed party, an unknown token or missing ACK cannot
establish success.

`gen1_partner_prompt_executor` uses the shared intent-before-effect executor and
a separate durable native lease. It stages the original partner Yes/No prompt
at a verified overworld checkpoint, records the actual service/prompt/choice
sequence, and verifies unchanged full party, CartRAM digest, map, tiles and native
control fields. The native decision survives inbox publication failure. An armed
lease with lost live execution evidence requires recovery and cannot be rearmed.
The prompt releases only after its exact terminal event is durably confirmed;
the first returned checkpoint must still match the recorded view.

`gen1_trade_events` maps only the cartridge trade command types to coordinator
events. `gen1_saved_trade_executor` composes the existing animation executor and
SaveRAM provider: persist native-applied evidence once, flush/read the actual
owned save file, then publish the file-verified terminal receipt. A failed file
readback leaves the command incomplete and never runs the animation again.

`gen1_trade_ui_receipts.py` independently validates the selected receptionist
member and native partner result against the server-owned proposal/artifact.
Full 404-byte party-block validation is reused with native trade receipts.
The shared coordinator still requires both native/file verifications before
atomic ownership migration and release. Identical Yellow parties still execute
both original animations.

## Exact remaining RC boundary

The new tests use actual cartridges, native UI, journals, original animations,
server result validation and isolated files. Test-only file transport waits
without advancing frames during response latency. Linked availability, paired
host authority, preparation control and initial rule/identity bootstrap remain
explicit fixtures. They are not a production scheduler or automatic admission.

Next, bind these modules to the ordinary runtime's qualified controller and
artifact admission. Its held-service launcher still supplies no trade policy or
frame authority. Complete native abort/closure scheduling, offer expiry and busy
partner delivery under real network timing, reset/load/rewind recovery, final
R/B full and Yellow trade-only artifacts, and the remaining RC release gates.
Keep presentation polish and further internal refactors deferred unless they
block those concrete conditions.

Native UI cutoff:4,230 unit/integration tests passed with2 existing Windows symlink skips (81.19s);18 actual paired trade cases passed (180.73s), and5 actual held-network/launcher cases passed (20.75s). Parsed238 current Lua files plus the frozen v1 reader fixture. Evidence:.cache/native-ui-full.xml,.cache/native-ui-pairs.xml,.cache/native-ui-held.xml. Shared client-journal26aee4348a27e799b95a8f6ba9b0eaeb7ad0395c is published and handed to Gen2/Gen3/UI. No default gameplay/trade activation is claimed.
