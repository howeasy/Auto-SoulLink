/* eslint-disable max-len */

// Hand-worked coverage for the Gen 1/2 "real stat exp" fix (see stats.ts calcStatRBYFromDV /
// pokemon.ts calcStat) plus two other multi-gen sanity checks (Gen 1 crit, Gen 3 Crunch category).
// Only ranges/categories are asserted - this fork's desc() strings differ from upstream Smogon
// calc (a known baseline difference), so desc() is intentionally not checked here.

import {Stats} from '../stats';
import {inGen} from './helper';

describe('SLink multi-gen', () => {
  describe('Gen 2 stat exp (raw stat exp, not modern 0-252 EVs)', () => {
    // pret/pokecrystal engine/pokemon/move_mon.asm CalcMonStatC (~line 1424) shares the exact
    // same formula as pret/pokered home/move_mon.asm CalcStat (line 54): for a non-HP stat,
    //   stat = floor(((base + dv) * 2 + floor(min(255, ceil(sqrt(statExp))) / 4)) * level / 100) + 5
    // base=65, dv=8, level=50 => (base + dv) * 2 = 146.
    test('stat exp 0 vs 65535 vs 10000', () => {
      // statExp=0: ceil(sqrt(0))=0 (the game's incremental search actually lands on b=1, but
      // floor(1/4)=floor(0/4)=0 either way, see stats.ts comment) => bonus=0
      //   floor(146 * 50 / 100) + 5 = floor(73) + 5 = 78
      expect(Stats.calcStatRBYFromDV('atk', 65, 8, 50, 0)).toBe(78);

      // statExp=65535 (max, the default): ceil(sqrt(65535))=256, capped to 255 (the game's
      // search table only goes up to 255 - engine/math/get_square_root.asm NUM_SQUARE_ROOTS=255),
      // floor(255/4)=63 => this is the old hard-coded "+ 63" constant this fix replaces
      //   floor((146 + 63) * 50 / 100) + 5 = floor(104.5) + 5 = 109
      expect(Stats.calcStatRBYFromDV('atk', 65, 8, 50)).toBe(109);
      expect(Stats.calcStatRBYFromDV('atk', 65, 8, 50, 65535)).toBe(109);

      // statExp=10000: sqrt(10000)=100 exactly, ceil=100, floor(100/4)=25
      //   floor((146 + 25) * 50 / 100) + 5 = floor(85.5) + 5 = 90
      expect(Stats.calcStatRBYFromDV('atk', 65, 8, 50, 10000)).toBe(90);
    });
  });

  describe('Gen 1 critical hit (doubles level, ignores stat stages)', () => {
    // pret/pokered engine/battle/core.asm: GetDamageVarsForPlayerAttack resets the attacker's
    // attack/defender's defense to their unmodified (unboosted) values on a crit (~line 4056-4070
    // for the physical-attack case), then `sla e ; double level if it was a critical hit`
    // (line 4136) doubles the level used by CalculateDamage (line 4299).
    //
    // Mew (gen 1 base 100 in every stat, see data/species.ts) at level 50, DV/stat exp maxed by
    // default (see stats.ts calcStatRBYFromDV) gives:
    //   atk = def = floor(((100 + 15) * 2 + 63) * 50 / 100) + 5
    //             = floor(293 * 50 / 100) + 5 = floor(146.5) + 5 = 151
    // Pound is a 40 BP Normal physical move (data/moves.ts); Mew is pure Psychic, so no STAB and
    // Normal is neutral vs Psychic (no type-effectiveness multiplier).
    //
    // Non-crit: CalculateDamage uses level=50.
    //   floor(2*50/5 + 2) = 22
    //   floor(22 * 151 * 40 / 151) = floor(880) = 880 (151 cancels exactly: 22*40=880)
    //   floor(880 / 50) = 17, +2 = 19 (baseDamage)
    //   range = [floor(19*217/255), 19] = [floor(16.16), 19] = [16, 19]
    //
    // Crit: level doubles to 100, attack/defense unchanged (no boosts to ignore here).
    //   floor(2*100/5 + 2) = 42
    //   floor(42 * 151 * 40 / 151) = 42*40 = 1680
    //   floor(1680 / 50) = 33, +2 = 35 (baseDamage)
    //   range = [floor(35*217/255), 35] = [floor(29.78), 35] = [29, 35]
    inGen(1, ({calculate, Pokemon, Move}) => {
      test('Pound non-crit vs crit', () => {
        const mew = Pokemon('Mew', {level: 50});
        const target = Pokemon('Mew', {level: 50});

        const normal = calculate(mew, target, Move('Pound'));
        expect(normal.range()).toEqual([16, 19]);

        const crit = calculate(mew, target, Move('Pound', {isCrit: true}));
        expect(crit.range()).toEqual([29, 35]);
      });
    });
  });

  describe('Gen 3 Crunch is Special (Dark is a special type pre-Gen 4)', () => {
    // move.ts: `this.category = data.category || (gen.num < 4 ? (SPECIAL.includes(data.type) ?
    // 'Special' : 'Physical') : 'Status')`. data/moves.ts only patches Crunch's category to
    // 'Physical' starting in the DPP (Gen 4) patch, so for gen <= 3 it falls through to the
    // type-based rule, and Dark is in the pre-Gen-4 SPECIAL type list.
    //
    // Mew (level 100, gen 3 base spa 100, default 0 EV / 31 IV, no nature) vs Snorlax (gen 3 base
    // spd 110, same defaults):
    //   spa = floor((100*2 + 31 + floor(0/4)) * 100 / 100) + 5 = floor(231) + 5 = 236
    //   spd = floor((110*2 + 31 + floor(0/4)) * 100 / 100) + 5 = floor(251) + 5 = 256
    // Crunch is 80 BP Dark (data/moves.ts); Mew is pure Psychic (no STAB), Dark is neutral vs
    // Normal (Snorlax), so no type-effectiveness multiplier.
    //   floor(2*100/5 + 2) = 42
    //   floor(42 * 236 * 80 / 256) = floor(792960 / 256) = 3097
    //   floor(3097 / 50) = 61, +2 = 63 (baseDamage; Special moves skip the physical max(1, ...))
    //   range = [floor(63*85/100), 63] = [floor(53.55), 63] = [53, 63]
    inGen(3, ({calculate, Pokemon, Move}) => {
      test('Crunch category and damage', () => {
        const move = Move('Crunch');
        expect(move.category).toBe('Special');

        const mew = Pokemon('Mew');
        const snorlax = Pokemon('Snorlax');
        const result = calculate(mew, snorlax, move);
        expect(result.range()).toEqual([53, 63]);
      });
    });
  });
});
