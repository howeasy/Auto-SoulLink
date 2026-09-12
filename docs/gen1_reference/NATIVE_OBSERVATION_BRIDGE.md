# Native checkpoint observations

The production frame bundle can include `native_checkpoint` with schema
`rby-native-observation-v1` and an actual `party` readback, alongside its complete
same-frame inventory. `server/gen1_native_observation.py` validates the actual
party readback, trainer, cartridge, raw party storage, active box, all inactive
boxes, map and current-box flag against the full-save source. The party readback
must explicitly report overworld state. The full-save point does not contain
`wIsInBattle`, so it cannot supply that fact by itself.

The compact party witness, its immutable event reference, the frame completion, inventory
transition and result digest commit together. A failed checkpoint aborts the
whole frame settlement. The full checkpoint is reconstructed from that witness
and its original inventory event; no second CartRAM copy is stored. The paired checkpoint reader requires each stored frame
to equal the corresponding settled ledger frame. A newer outstanding ordinary
grant immediately makes the old checkpoint ineligible for a new native offer.

Receptionist menu eligibility uses a separate candidate reader: the visiting
player must be at its current settled checkpoint; the peer may be finishing an
already granted range. Creating the receptionist obligation stops new ordinary
grants. The later trade offer and preparation both use the strict paired reader
and revalidate the selected link, so menu eligibility grants no trade authority.

Final native handoff can retain the actual post-trade checkpoint in the same
atomic event as its inventory settlement. It refers to the native command's
verified return and consumed credits, including unused credits retired by the
return. Its party witness remains explicit and its save bytes are reused from
the original event rather than duplicated in the observation component.

This supplies observations to `NativeTradePolicy.read_checkpoints`. It grants no
frames, verifies no save-file flush, and does not claim that the complete native
launcher path is qualified. Client production wiring and native-to-ordinary
handoff retain their separate execution and recovery requirements.

Focused tests use the real journal and modeled source snapshots. The existing
native-emulator tests qualify original animation separately; they do not yet
qualify this complete launcher composition.
