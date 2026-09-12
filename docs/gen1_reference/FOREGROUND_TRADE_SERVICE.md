# Foreground trade service prototype

`patch/gen1/src/trade_service.asm` now enters the physical trade engine through
the cartridge's terminal `DelayFrame` path. The new live test does not redirect
the CPU or inject an IRQ return. Red, Blue and Yellow each passed a real
Haunter-to-Gengar exchange through this entry, including the original animation,
native evolution, canonical save call and return to the original map.
Three additional foreground cases trade byte-identical party data and still
require the original animation/save before completion. Both foreground trade
and partner-prompt gates use the same read-only Game Boy execution observer.

The bridge preserves AF, BC, DE and HL, the original stack balance and ROM bank.
It only calls the foreground service for either of the two source-verified
overworld-loop return addresses. Other `DelayFrame` callers return normally.
The builder verifies the original 11-byte routine, patches its final three
bytes, and uses source-declared unused RST space for the ROM0 bridge. It preserves
RST00, RST38, the hardware interrupt entries and `$0100–$014F`, and rejects
source use of the reserved RST vectors. This is an unadvertised prototype build,
not a replacement for the released companion manifest.

## Borrowed scratch, not an idle mailbox

The first 16 bytes of `wSerialPartyMonsPatchList` alias `wSurroundingTiles` and
`wTileMapBackup`; Yellow also uses this union for animated objects. Leaving a
control mailbox there during ordinary play would corrupt cartridge scratch.

The prototype uses a temporary foreground lease. A local, validated caller
captures the original 16 bytes into the unused second enemy-party slot after
staging the single incoming Pokémon in enemy slot zero. These backup bytes must
come from local memory, never from a server payload. The request generation is
published last.

The service retains control fields on its stack and restores the union before
calling the native engine. After the engine has restored the map, the service
captures the new union preimage and publishes completion with ACK generation
last. It waits in the foreground until the client releases the matching
generation and digest, then restores that new preimage before returning.
Uncertain append results cannot release through the ordinary completion path.
There is no completion timeout that invents success.

The live tests reject a stale release generation and a changed digest, then
verify restoration of the union, complete caller registers and the traded party.
The initial test attempts timed out because the harness incorrectly treated the
JSON-null sentinel as Lua false before arming a request. Correcting that harness
check yielded three passing foreground tests; it did not change the native engine.

## Outstanding qualification

No production command or capability selects this service. The caller-side lease
stager, typed preparation/durable receipt binding, exhaustive stale/ambiguous
overlay refusal and natural union-writer analysis remain required. In particular,
a control-shaped byte pattern alone must not become production effect authority.
The [receptionist, eligible-party picker and partner prompt](RECEPTIONIST_TRADE_FLOW.md)
now have separate live component tests. Their production binding, all paired
trades including Yellow/Yellow, and forward recovery still need end-to-end proof.
The separate host broker owns reset/load interception work.

Reproduce with pinned local inputs and `SLINK_LIVE=1`:

```text
python -m pytest tests/live/test_gen1_foreground_trade.py -q
```

The builder option is `python -m tools.build_gen1_native_trade --foreground`.
The IRQ-injection option and foreground option are mutually exclusive. Generated
ROMs and per-title `.cache/foreground-trade-result-*.json` evidence remain local.
