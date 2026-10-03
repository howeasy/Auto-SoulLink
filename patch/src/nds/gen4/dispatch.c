/* Gen 4 companion producer fan-out -- card C2. Spec: docs/gen4/companion/C2_BEACON_SPEC.md.
 *
 * C2-C5 are ONE companion build, not four (docs/gen4/RESUME.md:42: a per-card build
 * would force a C6 re-pin plus a re-run of every receipt). So this file carries all
 * four modules' call sites from the start, with C3, C4 and C5 compiled out until their
 * own card lands. There is nothing to route and nothing to gate: each producer is
 * called unconditionally, in a fixed order, and each one returns without acking any
 * opcode it does not own.
 *
 *   order  module  card  shared producer it wraps            own opcodes
 *   -----  ------  ----  -----------------------------------  --------------------------
 *     1    sound   C3    (none -- C3 reuses tp_ack only)     19 PLAY_SE, 9 PLAY_FANFARE
 *     2    panel   C4    slink_panel_* (panel_producer.h)   27 SHOW_INFO
 *     3    trade   C5    slink_trade_service                 29, 21, 30, 31
 *
 * A module that is not in this build contributes nothing: no opcode is consumed, no
 * ack is written, no capability bit is advertised. The beacon owns the mailbox header
 * around them either way.
 *
 * NO file-scope object here either (see beacon.h): no producer table, no descriptor
 * array. The call order is the source order.
 */
#include "global.h"

#include "beacon.h"
#include "dispatch.h"

void Slink_NDS_Dispatch(SlinkGen4State *st, volatile SlinkMailboxV2 *m)
{
#if defined(SLINK_GEN4_SOUND)
    Slink_NDS_Sound_Service(st, m); /* C3 -- patch/src/nds/gen4/sound.c */
#else
    (void)st;
    (void)m;
#endif

#if defined(SLINK_GEN4_PANEL)
    Slink_NDS_Panel_Service(st, m); /* C4 -- patch/src/nds/gen4/panel.c */
#endif

#if defined(SLINK_GEN4_TRADE)
    Slink_NDS_Trade_Service(st, m); /* C5 -- patch/src/nds/gen4/trade.c */
#endif
}