# Soul Link Match Call client (Card C)

This is the Emerald v2 consumer and MODEL contract. No Emerald companion target is
qualified, no READY value changes, and durable trade capability remains false.
T2 owns the PokéNav contact, native text, safe UI entry, and record lifetime.

## Gen 2 feature map

| Accepted Gen 2 behavior | Emerald consumer |
|---|---|
| `server/state.py:_propagate_faint` tags the partner's battle-death command `fallen`; identity-loss retirement is not tagged | Same existing command and `phone_data`; no server change |
| Both dead-zone messages are tagged `dead_zone` | Same receiver-relative trainer name; generic dead-zone body |
| Both messages for the first two-sided link are tagged `first_link` | Same content; first-link publication is limited to once per client process |
| `_phone_data` / `_phone_extra` supply the other trainer and caller/receiver mons | Reused unchanged; the tag never replaces or consumes the original command |
| `lua/gen2/phone.lua`: one in-flight call, one pending candidate, lower event ID wins, newest equal-priority data wins | Same queue policy, including replacement before native publication |
| Gen 2 starts its 10,800-frame gap on observed delivery, not request ACK | Same emulator-frame gap after matching DELIVERED/COMPLETE evidence; no gap for REFUSED |
| Capability/freshness loss discards local queued/in-flight calls without replay | Same behavior on capability loss, native reset, or epoch loss |

Gen 2's literal content is in `patch/gen2/src/phone.asm`:

- Fallen: the partner reports that their mon died and the linked receiver mon went with it.
- Dead zone: the catch got away and the place is a dead zone; the body is unchanged when named.
- First link: the first pair is linked, with the reminder to keep them alive.
- Named fallen/first-link text uses the caller trainer, caller nickname (species fallback),
  and receiver **species name**, matching the accepted Gen 2 scripts.

The producer must mirror those templates in native Match Call text. The client transports
the structured content; it creates no new HUD, hotkey, menu, or server event.

## Agreed ABI envelope

T2 confirmed these semantics against `patch/src/trade_targets/abi.h` at `76607600`:

- Only an Emerald companion with `SLINK_CAP_MATCH_CALL` and a bound nonzero epoch accepts tags.
  FR/LG, RR, clean Emerald, absent beacons, and unknown capability bits receive no call writes.
- `OP_MATCH_CALL` uses `args[0]=event` (fallen=1, dead_zone=2, first_link=3), other args zero.
  The 36-byte `SlinkCallRecordV2` is staged at `BASE+TEXT_OFFSET` before opcode publication.
- Trainer and nickname fields are bounded, glyph-only, and terminated with 0xFF. Species are
  u16 bounded by the pack's species table, not Gen 2 bytes. Missing usable trainer data clears
  names and selects the generic call.
  The receiver nickname is transported because the ABI includes it; it does not change
  the Gen 2 receiver-species wording.
- `has_names=1` means a usable trainer, not that both mons are present. Zero species means
  missing metadata. Native keeps the generic body unless both species are usable, as Gen 2
  does; it still accepts trainer-only dead-zone calls and independently validates table indexes.
- Native validates and copies the record to `CALL_RECORD_OFFSET`, publishes a coherent
  ARMED/REFUSED witness, then ACKs. Host never writes the native record or witness.
- ACK/ARMED are not delivery. Stable equal nonzero even revisions, matching epoch/seq/event,
  and DELIVERED/COMPLETE are required. A matching witness left over from before publication
  is not new evidence. Frame zero is valid; a timestamp alone is never delivery.
- DELIVERED still owns the record. COMPLETE releases it; native retains the delivery fields.
  A foreign-epoch open UI blocks a new record and is never attributed to the current host.
- Native retains old open-UI text through host epoch rollover and preserves its cooldown.
  Real game reset clears pending native state; neither side replays the old call.
- An occupied-slot refusal may use a prompt mailbox FAIL without replacing the older owned
  record/witness. It refuses only the new request and provides no delivery evidence.

## Binding and evidence limits

The client binds a nonzero u32 from the existing bootstrap session-counter word; an absent
or unusable seed invents no epoch. The native queue owns the handshake and all staging.
This handshake is a host field write, not a native acknowledgement. Automatic attempts require
a coherent free call slot, are limited to three attempts, and stop with a named log on exhaustion.
Explicit rebind repeats the ownership checks. Acknowledged handshake/producer acceptance is a
separate T2 prerequisite; matching readback alone does not prove native acceptance. Phone-path
errors are logged without dropping the original tagged command.
The production generator still emits no READY=1 v2 binding; BASE resolution and qualified
per-title entry/safety routing remain prerequisites in `T3_NATIVE_V2_STATUS.md`.

`tests/unit/test_gen3_native.py` models the actual native module, canonical ABI layout,
queue writes, record contents, delivery witnesses and negative controls.
The shared-client command test uses an injected binder on the existing companion harness;
it proves forwarding/original-command behavior, not Emerald admission. Existing
`test_state_phone_tags.py` and `test_gen2_phone.py` remain the server/Gen 2 references.
Physical Match Call and native text/contact verification wait for T2's qualified Emerald target.
