# Native trade entry point for Gen 2

Type: research
Status: resolved
Blocked by: 13,14

## Question

Gen 1 uses the Cable Club receptionist with the cartridge's own YES/NO and both animations (docs/gen1_requirements.md T rows). Gen 2's Cable Club has the Time Capsule, the Trade Center and the Colosseum; Crystal also has the Mobile Adapter path. Which entry point does the Gen 2 companion patch take over, what ABI windows exist (`DelayFrame` / serial `Link_*` sites), and what does the receptionist gate look like? Depends on the link-trade write routine (13) and free RAM (14).

## Answer

Research lane R8 (`docs/gen2/research/native_trade_entry.md`, 312 lines). Gen 2 has four receptionists (Trade Center / Colosseum / Time Capsule / Crystal Mobile) with the flow spread across shared `special` routines (`SetBitsForLinkTradeRequest`, `WaitForLinkedFriend`, `CheckLinkTimeout_Receptionist`, `CheckBothSelectedSameRoom`) and `LinkTrade` in the destination room. Two takeover sites, versus Gen 1's one: the receptionist specials (QUERY-shaped, the Gen 1 availability window) and `LinkTrade`'s selection/sync block plus the two `TradeAnimation`/`TradeAnimationPlayer2` predefs (OFFER/APPLY-shaped, the Gen 1 180-frame window). ABI: `wOTPartyMons`, `wCurTradePartyMon`, `wTempMonSpecies`, mail buffers; 48-byte `PARTYMON_STRUCT_LENGTH` records; held items need validation (new work), mail is Trade-Center-only, species/moves gated by `CheckTimeCapsuleCompatibility`. Time Capsule and Mobile out of scope with cited reasons. The commit chain from ticket 13 is reused unmodified. Six negative controls (decline, cancel, timeout, mid-trade disconnect, save failure, illegal payload) mapped to T-1..T-4. Mailbox address still waits on ticket 14 (P1 linker map); the `special` dispatch mechanism and menu reuse are unverified (open questions 6).

CORRECTED 2026-09-21 (Codex cx-51f03e2d): Time Capsule converts held items (not 'no conversion'); CheckTimeCapsuleCompatibility is a Gen 1 gate, never a Gen 2 item validator; Mobile path not shown equivalent; the takeover must cover the room payload exchange and post-trade serial sync. Time Capsule out of scope (O-14).

2026-09-26 update: built and PHYSICALLY qualified -- trade ASM under `patch/gen2/src`, `lua/gen2/trade_overlay.lua`
(see [ticket 28](../../issues/28-p4-trade.md)); `tools/verify_gen2_release.py --lane live-trade-gates`
PASSES (T-1..T-4 on C-C/G-S/C-G, tag `gen2-rc-evidence-2026-09-25`). The mailbox dependency (ticket 14)
closed per O-27.
