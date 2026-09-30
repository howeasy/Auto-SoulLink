#ifndef SLINK_NATIVE_CHOICE_H
#define SLINK_NATIVE_CHOICE_H
#include <stdint.h>
#ifdef SLINK_TARGET_CARRIER_CANCEL
#define SLINK_CHOICE_PENDING 0xffffu
#else
#define SLINK_CHOICE_PENDING 0xffu
#endif
static inline int slink_native_choice_result(uint16_t value,uint8_t *result)
{
    if (value==SLINK_CHOICE_PENDING || value==0xffffu) return 0;
#ifdef SLINK_TARGET_CARRIER_CANCEL
    if (value==SLINK_TARGET_CARRIER_CANCEL) value=7;
#endif
    if (value==0xffu) return 0;
    if (!(value<6 || value==7)) return -1;
    *result=(uint8_t)value;return 1;
}
#endif
