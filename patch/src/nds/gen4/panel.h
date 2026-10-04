/* Gen 4 (HG/SS) companion C4: the info PANEL -- the INTERFACE.
 * Card C4 -- docs/gen4/companion/C4_PANEL_SPEC.md, whose DECISION BLOCK (its lines
 * 1-18) binds, plus docs/gen4/companion/C4_FACTS.md for the facts this card settled.
 *
 * Header-only, no game include, NO file-scope object (patch/src/nds/gen4/README.md:57-59).
 * Nothing here names an address: the mailbox base, the info region and the engine
 * predicates are all supplied by the caller through the seam in panel_policy.h, which is
 * why this header also carries no SlinkGen4State.
 *
 * ---------------------------------------------------------------- the dispatch contract
 * The C2 dispatcher already calls, under SLINK_GEN4_PANEL (dispatch.c:41-43):
 *
 *     void Slink_NDS_Panel_Service(SlinkGen4State *st, volatile SlinkMailboxV2 *m);
 *
 * and dispatch.c:42 comments the implementation as patch/src/nds/gen4/panel.c. That
 * declaration is DELIBERATELY NOT repeated here: SlinkGen4State is an anonymous-struct
 * typedef in beacon.h, so a forward declaration here would be a second, incompatible type
 * and would break the very call site above. The contract is therefore documented, and
 * panel.c is its only author:
 *
 *   st  the beacon's state block. panel.c owns st->panel and nothing else in it: the
 *       per-card rule is one writer per sub-struct. The panel sub-struct (beacon.h) is
 *       { uint32_t layout; SlinkPanelProducer producer; uint32_t caps; } -- byte-for-byte
 *       the shape of SlinkGen4PanelState in panel_policy.h, so the policy can be driven
 *       against &st->panel with no copy and no second transaction. st->panel.caps is C4's
 *       contribution to the published word and, like every card's, is composed by
 *       Slink_NDS_PublishCaps() after the fan-out (beacon.h:256-273): the policy writes it,
 *       this Service never writes m->capabilities.
 *   m   the mailbox (abi.h:148-159). panel.c MUST NOT write it except through the shared
 *       producer, which owns every ack (panel_producer.h:51, :58, :62 -> tp_ack).
 *
 * Required behaviour of the implementation, in order, once per service visit:
 *   0. stamp/validate the sub-struct layout (panel_policy.h does this; a mismatch resets)
 *   1. exactly one call to slink_gen4_panel_step() (panel_policy.h), which is the ONLY
 *      thing that touches the mailbox, the info region and the producer
 *   2. nothing of its own beyond that. In particular panel.c does not publish a result
 *      byte: the app's poll() writes it (panel_producer.h:15, :38, :42), through
 *      slink_gen4_panel_result() (panel_policy.h), so the A/close rule is one function.
 *
 * ---------------------------------------------------------------- the opcode and the cap
 * SLINK_OP_SHOW_INFO (27, abi.h:83) is the only opcode the panel consumes, and only by
 * letting the shared producer ack it (panel_producer.h:46-52). SLINK_CAP_INFO_PANEL is
 * 1 << 1 (abi.h:90) and is the ROM-side half of falsifier F9: no cap, no row
 * (C4_PANEL_SPEC.md:71-75).
 */
#ifndef SLINK_GEN4_PANEL_H
#define SLINK_GEN4_PANEL_H

#include "abi.h"

/* Layout stamp for the panel's sub-struct. Equal to beacon.h's SLINK_GEN4_STATE_PANEL_LAYOUT
 * by value (both 1) and re-declared here so this card does not include beacon.h and
 * therefore does not depend on SlinkGen4State; the equality and the struct-shape parity are
 * pinned by tests/unit/test_gen4_panel_policy.py. */
#define SLINK_GEN4_PANEL_LAYOUT 1u

/* C4's contribution to the published capability word, in the same shape as C3's
 * SLINK_GEN4_SOUND_CAPABILITIES and C5's SLINK_GEN4_TRADE_CAPABILITIES: the card writes its
 * own contribution word, the beacon composes the mailbox word once after the fan-out, and
 * no card ever assigns m->capabilities. The #if in dispatch.c is the gate -- the Service
 * exists exactly when the row and the overlay are in this build (C4_PANEL_SPEC.md:71-75,
 * :151-156) -- so the contribution is unconditional here; a readiness latch, if one is ever
 * needed, goes where C3's does (sound_policy.h:122-126). */
#define SLINK_GEN4_PANEL_CAPABILITIES SLINK_CAP_INFO_PANEL

/* The result words. abi.h:213-214 documents `result` as "0 A/more, 0x7F B/close, valid at
 * closed_seq"; the ABI owner's Q1 ruling (C4_PANEL_SPEC.md:7-11) widens it to "0x7F closes
 * for ANY reason, 0 only when A advances to a further page" -- the Gen 2 no-wrap UX. The
 * rule lives in one function, slink_gen4_panel_result() in panel_policy.h. */
#define SLINK_GEN4_PANEL_RESULT_MORE  0x00u
#define SLINK_GEN4_PANEL_RESULT_CLOSE 0x7Fu

#endif /* SLINK_GEN4_PANEL_H */