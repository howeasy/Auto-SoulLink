/* Gen 4 companion producer fan-out. Card C2 -- docs/gen4/companion/C2_BEACON_SPEC.md.
 *
 * ONE rule, and it is the rule: the dispatcher calls EVERY producer on EVERY visit and
 * performs no opcode pre-route. Producer isolation is per producer, not here
 * (C2_BEACON_SPEC.md:6-12; C3_SOUND_SPEC.md:150-162; C5_TRADE_SPEC.md:22-30). The
 * shared trade producer already leaves foreign opcodes alone while its own state
 * machine still runs, because the async-save watchdog depends on it
 * (patch/src/nds/common/trade_producer.h:249-254).
 */
#ifndef SLINK_GEN4_DISPATCH_H
#define SLINK_GEN4_DISPATCH_H

#include "beacon.h"

void Slink_NDS_Dispatch(SlinkGen4State *st, volatile SlinkMailboxV2 *m);

#endif /* SLINK_GEN4_DISPATCH_H */