# Known-positive stat control for Gen 2

Type: research
Status: resolved
Blocked by: none

## Question

Gen 1 R-2 recomputes stats from DVs/stat-exp/base stats and requires equality (CONTROL oracle). `shared-stat-experience-contract` says Gen 2 must compare against `CalcMonStats` first. Cite `CalcMonStats`/`CalcMonStatC` in pokecrystal@7a7881d, the Sp.Atk/Sp.Def split from one Special stat-exp, and the Shiny/gender-from-DVs derivation (shiny bonus pairs and the gender clause depend on it).

## Answer

Resolved for SOURCE research by R4, with the 2026-09-22 arithmetic correction recorded in
`docs/gen2/research/stat_control_and_fixture_budget.md` §A. Exact pins:
**C** = `pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651`,
**G** = `pokegold@656583c939d30f920a316177311a502dd222b57c`.
`CalcMonStats` is at both pins' `engine/pokemon/move_mon.asm:1402-1422`;
`CalcMonStatC` is C:1424-1617 / G:1424-1630 in that file.

For stat-exp words `0..65535`, the integer control is:

```python
root = min(255, 1 + isqrt(max(0, stat_exp - 1)))
bonus = root // 4 if use_stat_exp else 0
raw = ((2 * (base + dv) + bonus) * level) // 100
stat = min(999, raw + (level + 10 if is_hp else 5))
```

The DV is added **before doubling** (C `move_mon.asm:1533-1546`; G:1546-1559).
The square root rounds upward, caps at 255, and returns 1 for zero
(C `engine/math/get_square_root.asm:9-29`; G `move_mon.asm:1458-1477`). Level scaling
truncates before the HP/non-HP constants and clamp (C `move_mon.asm:1556-1611`;
G:1569-1624; both `constants/battle_constants.asm:75-78`). MODEL controls
`base/DV/stat_exp/level = 50/15/0/100`, `50/0/10/100`, `50/15/10/37` yield non-HP
135, 106, 53 respectively; the last yields HP 95. These expose the original note's
undoubled DV and floor-root errors.

Sp.Atk/Sp.Def use distinct bases but share `MON_SPC_EXP` (both `move_mon.asm:1438-1457`)
and the Special DV (C:1479-1482,1528-1531; G:1492-1495,1541-1544); both structs declare
five stat-exp words (`constants/pokemon_data_constants.asm:82-88`). Gender compares the
combined Atk/Spd DV byte with `BASE_GENDER` (C `engine/pokemon/mon_stats.asm:179-235`;
G:181-237). Byte **254** is always female and **255** is genderless, as resolved in
`OPEN_QUESTIONS.md` B-11 (both `constants/pokemon_data_constants.asm:35-41` and
`macros/data.asm:23`). Shininess remains the four-nibble DV predicate
(C `engine/gfx/color.asm:8-38`); Unown letter comes from packed DV middle bits
(C `engine/gfx/load_pics.asm:1-42`).

Section A7 retains the recomputation call-site and stored-stat staleness research for the
CONTROL timing contract. The codec must implement and independently qualify the corrected
control; this research does not establish that any existing codec does so. No GAME control,
PHYSICAL evidence, or gate sign-off is supplied by these SOURCE/MODEL findings.
