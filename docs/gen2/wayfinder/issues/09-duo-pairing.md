# Which duo pairings the lanes run

Type: grilling
Status: resolved
Blocked by: none

## Question

Crystal<->Crystal only, Gold<->Silver, or every cross-version pair?

## Answer

Gold<->Silver allowed; Crystal<->Crystal only (no Crystal<->Gold/Silver). Round 2 Q10. Pairing enforcement uses the existing `pairing_kind` adapter hook (gen3-P3a-C3a-1 in the RC guide checkpoint), no `game_id` branch.

Amended 2026-09-21 (O-11): any Gold/Silver combination (G<->S, G<->G, S<->S) is allowed; Crystal only with Crystal.

Amended 2026-09-21 (O-16): Crystal<->Gold/Silver admitted too (one shared foundation makes it simple); lanes stay C<->C and G<->S with one C<->G link scenario in the coverage map.

Amended 2026-09-24 (O-34): C<->G/S native-trade coverage expands beyond the one `link` scenario --
the full trade matrix (T-1..T-4) is proven on all three pairings (C-C, G-S, C-G), not just link.
`tools/verify_gen2_release.py --lane duo-link` and `--lane duo-pairs` both PASS as of 2026-09-26
(98/98 sweep cells pinned, tag `gen2-rc-evidence-2026-09-25`); see [ticket 24](../../issues/24-p3b-duos.md).
