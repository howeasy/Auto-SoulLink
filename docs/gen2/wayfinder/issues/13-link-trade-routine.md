# Where Gen 2 writes the received mon in a link trade

Type: research
Status: resolved
Blocked by: none

## Question

`engine/link/link_trade.asm` is UI only; the routine that writes the received party mon in a Cable Club link trade (and the Time Capsule path) was not located (pret_gen2_symbols.md open question 4). Find it in pokecrystal@7a7881d (`engine/link/link.asm` after the HEAD rename to `wLinkReceivedPartyData` etc.), state the write site and the save that follows, because the native-trade design (ticket 15) and the trade `key_change` row depend on it.

## Answer

Resolved by Codex `cx-02b0f4b5` (§B), coordinator-verified: `LinkTrade` commits through `predef AddTempmonToParty` (`pokecrystal@7a7881d engine/link/link.asm:1994`), then `callfar EvolvePokemon` (`:1998`), then `farcall SaveAfterLinkTrade` (`:2044`); pokegold `:1808-1874`. Staging/conversion before that point is not a local-party commit. `SaveAfterLinkTrade` recomputes both checksums but calls neither `SaveBox` nor `SavePlayerData`. Open (ticket 15): the two-sided takeover protocol (receptionist wait, payload/patch/mail exchange, confirmation, both animations, post-evolution identity, save acknowledgment) and host SaveRAM durability after the cartridge save.
