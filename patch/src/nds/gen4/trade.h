/* Gen 4 (HG/SS) companion trade -- integration contract. Card C5.
 * Spec: docs/gen4/companion/C5_TRADE_SPEC.md. The POLICY lives in trade_policy.h; this
 * file is the seam between that policy and dispatch.c, plus the wiring recipe for the
 * real trade.c.
 *
 * Build include paths: -I patch/src/nds/common -I patch/src/nds/gen4.
 * No file-scope object here either (patch/src/nds/gen4/README.md:50-59).
 */
#ifndef SLINK_GEN4_TRADE_H
#define SLINK_GEN4_TRADE_H

#include "abi.h"
#include "trade_policy.h"

/* ------------------------------------------------------------------ the dispatch contract
 *
 * patch/src/nds/gen4/dispatch.c:28-31 calls, under SLINK_GEN4_TRADE:
 *
 *     void Slink_NDS_Trade_Service(SlinkGen4State *st, volatile SlinkMailboxV2 *m);
 *
 * It is deliberately NOT a C declaration here. SlinkGen4State is an ANONYMOUS-struct
 * typedef in beacon.h (patch/src/nds/gen4/beacon.h:88-98) and another card owns that file
 * and is appending its own state to it; the type carries no tag, so it cannot be
 * forward-declared compatibly here -- `struct SlinkGen4State;` would be a DIFFERENT
 * incomplete type and every use of it would be a hard error (or worse, a mismatched
 * declaration). The real prototype lands in trade.c beside its definition, once that
 * state exists.
 *
 * The policy is deliberately independent of SlinkGen4State as well: it takes its own
 * SlinkGen4TradePolicy by pointer, so it can be compiled and driven by a host gcc with
 * no game header at all.
 */

/* ------------------------------------------------------------------ wiring recipe (trade.c, not this card)
 *
 *  1. Own the state. A SlinkGen4TradePolicy is allocated inside the service SysTask's heap
 *     data block (patch/src/nds/gen4/README.md:12-13, :126-128) -- never a file-scope
 *     object: a static .bss symbol moves SDK_STATIC_BSS_END = 0x021E5900 and every pinned
 *     overlay address above it.
 *  2. Init once per boot, after the beacon's own reset latch:
 *
 *         Slink_Gen4TradePolicy_Init(&st->trade, &seam, witness, stage, TIMEOUT_FRAMES)
 *
 *     witness = arena_base + SLINK_WITNESS_OFFSET (beacon.c:100-102 derives the base);
 *     stage   = arena_base + SLINK_BLOB_OFFSET. The ABSOLUTE base must not appear in
 *     source: census W2 FAILs a 7-8 hex-digit literal inside the span.
 *     TIMEOUT_FRAMES must be nonzero (trade_producer.h:260 refuses zero with BAD_ARGS)
 *     and is C5 SOURCE (§3.5, :318-319): it bounds the native save watchdog, not the
 *     scene.
 *  3. Every service visit, after the beacon has stamped the header:
 *
 *         Slink_Gen4TradePolicy_Service(&st->trade, m);
 *
 *  4. From the ScrCmd (the opcode-1 gScriptCmdTable slot, C5_TRADE_SPEC.md:188-193), in
 *     the order §3.3 fixes:
 *
 *         if (Slink_Gen4Trade_CommitEntered(&st->trade, slot))
 *             Slink_Gen4Trade_Commit(&st->trade, slot);
 *
 *     slot comes from the ScrCmdContext (OPEN -- §3.3 step 1). Do not call Commit first:
 *     without the marker it refuses, and the marker is the only evidence that a mutation
 *     is about to happen.
 *
 *  5. Capability. C5 advertises the shared SLINK_CAP_DURABLE_TRADE via
 *     slink_trade_advertise(m) (trade_producer.h:28-33), but the single-writer owner of
 *     `capabilities` is the beacon, which ASSIGNS m->capabilities = SLINK_GEN4_CAPABILITIES
 *     on every visit BEFORE dispatch (patch/src/nds/gen4/beacon.c:244-245, :262) and
 *     SLINK_GEN4_CAPABILITIES is 0u (beacon.h:63). The policy therefore does NOT write
 *     the mailbox header: the C2 owner must add SLINK_CAP_DURABLE_TRADE there, or a
 *     per-visit advertise from C5 would be erased on the next visit. No host may gate
 *     liveness on the bit (README.md:156-158).
 */

/* ------------------------------------------------------------------ what this policy deliberately does NOT do
 *
 *  - No box arm. Party slot overwrite only (DECISIONS_2026-10-02_companion.md:12;
 *    C5_TRADE_SPEC.md:17-19, :68-72; FEATURE_BAR.md:197-201).
 *  - No cipher. The host stages at-rest bytes; the ROM only calls the engine's own
 *    MonDecryptSegment / CalcMonChecksum (C5_TRADE_SPEC.md:225-232).
 *  - No new ABI field, offset, opcode or capability (C2_BEACON_SPEC.md:47-49).
 *  - No trade evolution. The owner ruling is a raw slot overwrite; SCENE_EVOLUTION_DONE
 *    is stamped by tp_service without any evolution code and must never be read as
 *    "evolution ran" (C5_TRADE_SPEC.md:380-385).
 *  - No box, no CountPCEmptySpace, no writable 0x88 scratch.
 */

/* ------------------------------------------------------------------ OPEN, deliberately undecided here
 *
 * Each of these is a seam function in SlinkGen4TradeSeam (trade_policy.h) and none of
 * them is answered by this policy:
 *
 *   OPEN 1  the ScrCmdContext result slot carrying the chosen slot   -- seam
 *           script_chosen_slot;        spec §3.3 step 1 (:262), §2.2 (:149-155)
 *   OPEN 2  WRITE_STATUS_* -> SLINK_SAVEPOLL mapping                -- seam post_save_poll
 *           takes an ALREADY-mapped SlinkSavePoll;         spec §7 Q2 (:466-469), §3.5
 *   OPEN 3  safe_field's Gen 4 predicate                           -- seam safe_field;
 *           absent => refuse                             spec §7 Q6 (:484-486)
 *   OPEN 4  poll_scene's shape and bound                          -- seam poll_scene;
 *           absent => terminal abort               spec §7 Q7 (:487-490)
 *   OPEN 5  pre-save semantics: consent -> ready with no pre-commit save
 *           -- seam poll_pre_save, forwarded verbatim; spec §7 Q3 (:470-473)
 *   OPEN 6  UpdatePokedexWithReceivedSpecies                       -- seam commit_party_slot
 *           spec §7 Q4 (:474-477), §3.3 step 5 (:266)
 *   OPEN 7  Save_PrepareForAsyncWrite mode + legality from a SysTask -- seam post_save_begin;
 *           spec §7 Q1 (:461-465)
 *   OPEN 8  the pinned save_timeout_frames value                    -- the Init argument;
 *           spec §3.5, §7 Q7's 6000-frame host SCENE budget (README.md:85-88)
 */

#endif /* SLINK_GEN4_TRADE_H */