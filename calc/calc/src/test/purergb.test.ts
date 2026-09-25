/* eslint-disable max-len */

// Prototype coverage for pureRGB's Gen 1 patch (calc/calc/src/data/purergb.ts, useDex()). See
// docs/calc_multigen/PURERGB_MECHANICS.md for what this is and isn't modelling yet - this only
// exercises the plumbing (new types resolve, a reskinned move resolves, restoring vanilla works),
// not the alternate-STAB or dynamic-Ghost-category rules that still need a mechanics/gen12.ts
// change gated on a pureRGB flag.
//
// Stat formula (shared with the existing Gen 1/2 tests, see slink_multigen.test.ts): default
// (max) DVs/stat exp, pret/pokered home/move_mon.asm CalcStat -
//   stat = floor(((base + 15) * 2 + 63) * level / 100) + 5

import {useDex} from '../data/purergb';
import {inGen} from './helper';

afterEach(() => {
  useDex('vanilla'); // never leak pureRGB state into a later test file/run
});

describe('pureRGB Gen 1 patch (prototype)', () => {
  describe('new-type effectiveness: Fighting vs Crystal/Ground (Hardened Onix)', () => {
    // data/types/type_matchups.asm: `db FIGHTING, CRYSTAL, SUPER_EFFECTIVE` (2x); Fighting vs
    // Ground has no entry, so it's neutral (1x) - total type multiplier 2x.
    //
    // Machamp (pure Fighting, base atk 130) at level 50:
    //   atk = floor(((130 + 15) * 2 + 63) * 50 / 100) + 5 = floor(353 * 0.5) + 5 = 176 + 5 = 181
    // Hardened Onix (Crystal/Ground, base def 180) at level 50:
    //   def = floor(((180 + 15) * 2 + 63) * 50 / 100) + 5 = floor(453 * 0.5) + 5 = 226 + 5 = 231
    // Karate Chop: 50 BP Fighting, Physical (data/games/gen1_purergb/moves.json id 2).
    //   floor(2*50/5 + 2) = 22
    //   floor(22 * 181 * 50 / 231) = floor(199100 / 231) = 861
    //   floor(861 / 50) = 17, +2 = 19 (baseDamage)
    //   STAB (Machamp is Fighting): floor(19 * 1.5) = 28
    //   type effectiveness (gen 1 applies each defending type separately): floor(28 * 2) = 56,
    //   then floor(56 * 1) = 56 (Ground, the second type, is neutral)
    //   range = [floor(56*217/255), 56] = [floor(47.65), 56] = [47, 56]
    inGen(1, ({calculate, Pokemon, Move}) => {
      test('Karate Chop vs Hardened Onix', () => {
        useDex('purergb');

        const onix = Pokemon('Hardened Onix', {level: 50});
        expect(onix.types).toEqual(['Crystal', 'Ground']);

        const machamp = Pokemon('Machamp', {level: 50});
        const result = calculate(machamp, onix, Move('Karate Chop'));
        expect(result.range()).toEqual([47, 56]);
      });
    });
  });

  describe('custom move: Dust Claw (Fury Swipes reskin, data/games/gen1_purergb/moves.json id 154)', () => {
    // Dust Claw: 40 BP Ground, Physical. Sandshrew (Ground/Normal, base atk 75) vs Machamp
    // (pure Fighting, base def 80), both level 50 - Ground vs Fighting has no type_matchups.asm
    // entry, so it's neutral.
    //   atk = floor(((75 + 15) * 2 + 63) * 50 / 100) + 5 = floor(243 * 0.5) + 5 = 121 + 5 = 126
    //   def = floor(((80 + 15) * 2 + 63) * 50 / 100) + 5 = floor(253 * 0.5) + 5 = 126 + 5 = 131
    //   floor(2*50/5 + 2) = 22
    //   floor(22 * 126 * 40 / 131) = floor(110880 / 131) = 846
    //   floor(846 / 50) = 16, +2 = 18 (baseDamage)
    //   STAB (Sandshrew is Ground): floor(18 * 1.5) = 27
    //   no type effectiveness multiplier (neutral both types)
    //   range = [floor(27*217/255), 27] = [floor(22.98), 27] = [22, 27]
    inGen(1, ({calculate, Pokemon, Move}) => {
      test('Sandshrew Dust Claw vs Machamp', () => {
        useDex('purergb');

        const move = Move('Dust Claw');
        expect(move.type).toBe('Ground');
        expect(move.category).toBe('Physical');

        const sandshrew = Pokemon('Sandshrew', {level: 50});
        const machamp = Pokemon('Machamp', {level: 50});
        const result = calculate(sandshrew, machamp, move);
        expect(result.range()).toEqual([22, 27]);
      });
    });
  });

  describe("useDex('vanilla') restores vanilla Gen 1", () => {
    // Same Mew/Pound case as slink_multigen.test.ts's "Gen 1 critical hit" - if this still passes
    // after a purergb round trip, the Species/Moves.prototype patch and the Gen 1 type chart both
    // came back cleanly.
    inGen(1, ({calculate, Pokemon, Move}) => {
      test('Mew Pound non-crit after a purergb round trip', () => {
        useDex('purergb');
        expect(Pokemon('Sandshrew').types).toEqual(['Ground', 'Normal']);

        useDex('vanilla');
        const mew = Pokemon('Mew', {level: 50});
        const target = Pokemon('Mew', {level: 50});
        const result = calculate(mew, target, Move('Pound'));
        expect(result.range()).toEqual([16, 19]);

        // pureRGB-only species/moves/types are gone again
        expect(Pokemon('Sandshrew').types).toEqual(['Ground']);
        expect(target.types).toEqual(['Psychic']);
      });
    });
  });
});
