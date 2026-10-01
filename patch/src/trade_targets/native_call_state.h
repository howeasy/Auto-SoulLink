#ifndef SLINK_NATIVE_CALL_STATE_H
#define SLINK_NATIVE_CALL_STATE_H
/* pokeemerald match_call.c sMatchCallTaskFuncs: state5 prints the message;
 * states6/7 can only follow that message's completion and A/B acceptance. */
static inline int slink_match_call_message_started(unsigned state)
{
    return state>=5u && state<=7u;
}
#endif
