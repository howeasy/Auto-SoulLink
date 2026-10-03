/* Toolchain compatibility for the shared NDS companion stack (card NDS-8).
 *
 * The NDS titles build with mwccarm 2.0/sp2p2 (the pret NDS toolchain). That
 * compiler predates C99 <stdint.h> and rejects the C11 declaration
 * _Static_assert, so abi.h - whose layouts are spelled in fixed-width types and
 * whose invariants are compile-time asserts - could not be compiled on target at
 * all. This header is the single place that knows the difference.
 *
 * Contract:
 *   - Any compiler that HAS <stdint.h> includes it, unchanged.
 *   - Under __MWERKS__ the fixed-width types are declared here instead, using
 *     the Nitro SDK spellings (nds/types.h: u8 = unsigned char,
 *     u16 = unsigned short, u32 = unsigned long) so a per-title header may pass
 *     a nitro u32 where the ABI wants uint32_t without a conversion.
 *   - SLINK_STATIC_ASSERT(cond, msg) evaluates cond at compile time on both, and
 *     is the ONLY spelling abi.h uses.
 *
 * There is no game content here: no addresses, no layout, no rules.
 */
#ifndef SLINK_NDS_COMPAT_H
#define SLINK_NDS_COMPAT_H

#if defined(__MWERKS__)
typedef unsigned char uint8_t;          /* nitro u8  */
typedef unsigned short uint16_t;        /* nitro u16 */
typedef signed char int8_t;
typedef short int16_t;
/* On the target (ILP32 ARM) long IS 32 bits and IS nitro u32, so it is the
 * spelling that keeps uint32_t and u32 the same type. __LONG_MAX__ is a compiler
 * builtin (gcc, clang): where it is absent the target spelling stands, and where
 * it proves long is WIDER than 32 bits (a 64-bit host gcc walking this path,
 * which is how the MWERKS branch is tested) unsigned int is the only 32-bit
 * spelling. What the ABI layouts require is the 32-bit WIDTH, and that holds on
 * every branch. */
#if defined(__LONG_MAX__) && __LONG_MAX__ > 4294967295L
typedef unsigned int uint32_t;
typedef int int32_t;
#else
typedef unsigned long uint32_t;         /* nitro u32 */
typedef long int32_t;
#endif
typedef unsigned long long uint64_t;
typedef long long int64_t;
#else
#include <stdint.h>
#endif

/* _Static_assert is C11 6.7.10; mwccarm 2.0/sp2p2 parses it as a declaration
 * and rejects the file. The fallback is the C89 negative-array-size typedef: a
 * false condition makes the array size -1, a hard error on both compilers. The
 * array name carries the line, so every assert in one translation unit stays
 * unique. The message is dropped in that branch because an array type cannot
 * carry one; the C11 branch is the one that reports messages. */
#ifndef SLINK_STATIC_ASSERT
#  if defined(__MWERKS__)
#    define SLINK_STATIC_ASSERT_(cond, line) \
    typedef char slink_static_assert_##line[(cond) ? 1 : -1]
     /* one more level so __LINE__ is expanded before the ## paste (otherwise every
      * assert is named slink_static_assert___LINE__ and C89 rejects the redefinition) */
#    define SLINK_STATIC_ASSERT_X(cond, line) SLINK_STATIC_ASSERT_(cond, line)
#    define SLINK_STATIC_ASSERT(cond, msg) SLINK_STATIC_ASSERT_X(cond, __LINE__)
#  else
#    define SLINK_STATIC_ASSERT(cond, msg) _Static_assert(cond, msg)
#  endif
#endif

/* No SLINK_ALIGNAS: _Alignas is C11-only and the only users were two buffers whose word alignment
 * is a layout fact, now proved with SLINK_STATIC_ASSERT(offsetof(...) % 4 == 0) in trade_producer.h. */

#endif
