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
#include "beacon.h" /* integration prototype; the policy itself stays beacon-independent */

/* ------------------------------------------------------------------ the dispatch contract
 *
 * patch/src/nds/gen4/dispatch.c:28-31 calls, under SLINK_GEN4_TRADE:
 *
 *     void Slink_NDS_Trade_Service(SlinkGen4State *st, volatile SlinkMailboxV2 *m);
 *
 * beacon.h now embeds the policy and a persistent seam in C5 layout 2. Include the
 * actual type rather than declaring a different struct tag for the anonymous parent.
 *
 * The policy is deliberately independent of SlinkGen4State as well: it takes its own
 * SlinkGen4TradePolicy by pointer, so it can be compiled and driven by a host gcc with
 * no game header at all.
 */

/* ------------------------------------------------------------------ the capability contribution
 * C5's whole advertised set: the shared SLINK_CAP_DURABLE_TRADE (abi.h:88-96), whose bit
 * abi.h:155 documents as "only implemented/qualified features". It is C5's, declared
 * here rather than in the beacon, and the beacon is what composes the PUBLISHED word:
 * SLINK_GEN4_CAPABILITIES (zero at C2) OR-ed with every compiled-in card's contribution
 * word, once the fan-out has run (patch/src/nds/gen4/beacon.h, Slink_NDS_PublishCaps).
 * A host must not gate liveness on the bit (README.md:156-158). */
void Slink_NDS_Trade_Service(SlinkGen4State *st, volatile SlinkMailboxV2 *m);
int Slink_NDS_Trade_Bind(SlinkGen4State *st, const SlinkGen4TradeSeam *seam,
                       volatile SlinkTradeWitnessV2 *witness,
                       const volatile SlinkRecordStageV1 *stage, uint32_t save_timeout_frames);
int Slink_NDS_Trade_Init(SlinkGen4State *st, void *context, volatile SlinkTradeWitnessV2 *witness,
                       const volatile SlinkRecordStageV1 *stage, uint32_t save_timeout_frames);
int Slink_NDS_Trade_CommitEntered(SlinkGen4State *st, unsigned slot);
int Slink_NDS_Trade_Commit(SlinkGen4State *st, unsigned slot);

#define SLINK_GEN4_TRADE_CAPABILITIES SLINK_CAP_DURABLE_TRADE

/* ------------------------------------------------------------------ wiring recipe (trade.c, not this card)
 *
 *  1. Own the state. A SlinkGen4TradePolicy is allocated inside the service SysTask's heap
 *     data block (patch/src/nds/gen4/README.md:12-13, :126-128) -- never a file-scope
 *     object: a static .bss symbol moves SDK_STATIC_BSS_END = 0x021E5900 and every pinned
 *     overlay address above it.
 *  2. Copy the constructed seam into st->trade.seam (persistent heap storage), then
 *     Init once per boot after the beacon's own reset latch. Layout 0 is fresh;
 *     any nonzero stale layout must REFUSE before a write, never reinterpret layout 1:
 *
 *         Slink_Gen4TradePolicy_Init(&st->trade.policy, &st->trade.seam, witness, stage, TIMEOUT_FRAMES)
 *
 *     witness = arena_base + SLINK_WITNESS_OFFSET (beacon.c:100-102 derives the base);
 *     stage   = arena_base + SLINK_BLOB_OFFSET. The ABSOLUTE base must not appear in
 *     source: census W2 FAILs a 7-8 hex-digit literal inside the span.
 *     TIMEOUT_FRAMES must be nonzero (trade_producer.h:260 refuses zero with BAD_ARGS)
 *     and is C5 SOURCE (§3.5, :318-319): it bounds the native save watchdog, not the
 *     scene.
 *  3. Every service visit, after the beacon has stamped the header:
 *
 *         Slink_Gen4TradePolicy_Service(&st->trade.policy, m);
 *
 *  4. From the ScrCmd (the opcode-1 gScriptCmdTable slot, C5_TRADE_SPEC.md:188-193), in
 *     the order §3.3 fixes:
 *
 *         if (Slink_Gen4Trade_CommitEntered(&st->trade.policy, slot))
 *             Slink_Gen4Trade_Commit(&st->trade.policy, slot);
 *
 *     slot comes from the ScrCmdContext (OPEN -- §3.3 step 1). Do not call Commit first:
 *     without the marker it refuses, and the marker is the only evidence that a mutation
 *     is about to happen.
 *
 *  5. Capability. Every service visit, C5's Service declares its contribution to the
 *     published word:
 *
 *         st->trade.caps = SLINK_GEN4_TRADE_CAPABILITIES;
 *
 *     The mailbox header stays the beacon's: it is stamped once, after every producer has
 *     run, out of the state block (patch/src/nds/gen4/beacon.h, Slink_NDS_PublishCaps),
 *     so a bit C5 sets there would be overwritten later in the same visit. For the same
 *     reason slink_trade_advertise(m) (trade_producer.h:28-33) is NOT the mechanism on
 *     this title: its `m->capabilities |= SLINK_CAP_DURABLE_TRADE` is true for one
 *     statement, and the beacon's whole-word stamp is what a host reads afterwards. No
 *     host may gate liveness on the bit (README.md:156-158).
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