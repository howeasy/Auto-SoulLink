# Native trade interaction components

The unadvertised R/B/Y prototype now supports both ends of trade interaction:
an initiator chooses an eligible party member at the existing receptionist,
and a partner can answer the cartridge's normal YES/NO menu from a verified
overworld checkpoint. These are native interaction components. Production
admission, durable offer/COMMIT coordination and paired forward recovery are
still unbound; the public pc_trade capability remains false.

## Initiator

The single TX_SCRIPT_CABLE_CLUB_RECEPTIONIST dispatch reaches the existing
physical object. No sprite or map object is inserted. All twelve receptionist
locations per title, including Indigo Plateau, have actual input-driven tests.

The main menu offers SLINK TRADE, CABLE CLUB and CANCEL. The filtered list maps
visible rows back to physical party slots and uses native cursor/input/button
sound handling. Held A/B must be released before another selection. The codec's
source-derived name alphabet is reused by assembly validation; an empty,
unterminated or control-bearing selected nickname is never interpreted as text.
The selection is checked again for current slot, species and HP before an offer.
The host must additionally revalidate complete party/blob identity and linkage.

Availability queries borrow only the first16 bytes of the serial/map union for
at most30 frames. The host returns a nonzero four-byte correlation token,
eligible mask and matching generation. The token stays on the native call's
stack through selection and is copied into the subsequent offer lease. The
small generation byte alone is not unique across separate visits.

Offers wait at most180 frames for a receipt matching magic, version, command,
generation, selected slot and all four token bytes. The result starts at FF.
The union is restored before any text is drawn, and the original text engine
honors normal text speed, the end-of-text prompt and button sound.

| Reply | Native feedback | Required host meaning |
| --- | --- | --- |
| Matching result0 | Trade offer sent. Awaiting partner. | The offer was durably accepted by the coordinator. It does not mean the partner accepted or the trade completed. |
| Matching result1 | Trade unavailable. Offer not sent. | Authoritative rejection with no accepted offer. |
| Missing, stale or malformed reply | Offer status is not confirmed. | Delivery is unresolved; do not mint a replacement operation or infer non-delivery. |
| No eligible party member | No linked POKéMON in your party. | No physical offer or trade was performed. |
| Unreadable selected names | Party data cannot be read. | No native name parsing or offer publication. |
| Selection disappeared/fainted/became invalid | That POKéMON is not available. | No offer publication. |

The token is local correlation, not authentication, a durable operation ID or
execution authority. A production host must associate it with the complete
admitted context and durable operation. It may write a reply only while that
exact native lease is still observed. A late response must not overwrite a
union returned to normal cartridge use. Unknown delivery must retain its
original durable identity through reconnect and recovery.

CABLE CLUB and unavailable SLink queries call the original CableClubNPC.
The live comparison currently covers its no-connection dialogue path.
Connected serial exchange remains an explicit outstanding acceptance case.

## Partner

Foreground command3 invokes the trade-specific prompt; command5 retains the
original physical trade engine. The partner prompt validates the selected
live slot, incoming record geometry/species/HP and both bounded nicknames.
It uses the same shared trade UI validation/input helpers as the receptionist.

The question displays the actual two names, followed by the original
YesNoChoice routine. It returns0 for YES,1 for NO/B and3 for an unavailable
request. It does not remove/append a Pokémon, run a trade animation/evolution,
or call a save routine. Acceptance is still only an input to durable preparation.

All25 saved presentation/menu fields, caller registers, stack balance, ROM bank
and map presentation are restored. The foreground service publishes its result
and waits for the corresponding consumed receipt before releasing the borrowed
union and resuming ordinary play. Stale release generations or token bytes
cannot release that wait.

Current actual cartridge coverage includes Pallet's town fixture, Viridian
Pokémon Center and Indigo Plateau on all three titles. It covers YES, NO, B,
held A/B, party counts1–6 and every slot, unreadable names, absent/fainted
selection, fainted incoming data and injected last-moment ownership refusals.
Injected battle/serial/printer flags test the local guard; they do not constitute
natural battle/menu queueing or complete host recovery qualification.

## Reuse and identity

- trade_ui.asm owns shared RBY trade text, key-release, cursor and name/slot
  validation. Receptionist and partner flows do not carry duplicate UI routines.
- gb_foreground_observer.lua observes bank-qualified routine calls and caller
  restoration without writing registers/memory or advancing frames. The trade
  and prompt gates both use it.
- gen1_map_fixture.lua provides the one-shot native map-loader setup used by
  both interaction gates. The GB runner owns isolated SaveRAM and per-run inputs.
- The shared command executor was imported exactly from b1049d4. Armed native
  commands remain PENDING, without reapply, fabricated ACK or frame permission.
  The existing shared platform_execution.lua bytes remain unchanged.

PartyCodec.prepare_exchange and its Lua counterpart check occupancy within the
recipient's retained party and verified boxes. Equal outgoing/incoming raw keys
can be valid across separate players, including Yellow/Yellow. The selected
outgoing slot is removed before the received member is appended. Local retained
party/box and predicted-evolution collisions continue to refuse preparation.
The shared identity registry, not the codec, binds distinct physical instances
and logical members; a raw key cannot identify a participant globally.

A same-key trade may leave the entire party byte-for-byte unchanged. Separate
live foreground cases require the original animation and canonical save call
even in that situation. A future receipt classifier must require operation-bound
native completion evidence; party equality alone cannot prove that the required
animation occurred. This is not yet a two-instance Yellow/Yellow trade proof.

## Evidence and remaining integration

The combined interaction run passed24 pytest cases in424.83 seconds, with no
skips or deselection:225 receptionist interactions and327 partner cases.
The separate shared-executor/Gen1-receipt selection passed147 tests.
The codec/identity selection passed183 tests, including matching cross-player
keys and retained local collision refusals.

The physical/foreground selection subsequently passed12 live tests in324.93
seconds:108 successful physical trades,40 refusals, three real reset/CONTINUE
cases, and six foreground cases including the identical-party-byte examples.
The full unit/integration run passed3,886 tests with two existing Windows file
symlink tests skipped for missing process privilege. Its strict release verdict
therefore remains blocked. Portable CI passed3,580 selected tests with308
explicitly named deferrals and does not grant release approval.

The current native artifacts reserve the trade service at4500, physical engine
at4800, receptionist at4C00, shared trade UI at5400 and partner prompt at5800,
all in the source-verified empty bank3F for R/B or3B for Yellow. These are local
prototype spans, not the final companion distribution manifest.

Remaining work includes the real client lease stager, durable offer/expiry and
queued busy-partner flow, command/receipt binding, the paired transaction state
machine, both-endpoint physical/save verification and forward recovery.
Natural union-pattern exclusion and host reset/load/rewind interlocks remain
required before this foreground prototype can be production-selected.
Final R/B full and Yellow trade-only companion integration also remains open.

The [independent result policy](TRADE_RESULT_VERIFICATION.md) now verifies
trade evolution at move-learning levels, including original move selection,
HM refusal, PP behavior and complete canonical save-region readback.
Production receipt binding and full save-file durability remain open.
No SRAM layout or persistent cartridge marker was added by this work.

Local reproduction:

    SLINK_LIVE=1 python -m pytest tests/live/test_gen1_receptionist.py tests/live/test_gen1_partner_prompt.py -q

Full ROMs, screenshots, input snapshots and observed results remain local under
.cache and patch/gen1/build. They are not release assets or redistributed ROMs.
