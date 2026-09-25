import * as I from './interface';

import {Abilities} from './abilities';
import {Items} from './items';
import {Moves} from './moves';
import {Species} from './species';
import {Types} from './types';
import {Natures} from './natures';

export const Generations: I.Generations = new (class {
  get(gen: I.GenerationNum) {
    return new Generation(gen);
  }
})();

// pureRGB (Gen 1 fork, data/games/gen1_purergb) support: swaps SPECIES/MOVES/TYPE_CHART's Gen 1
// slot in place. See calc/calc/src/data/purergb.ts and docs/calc_multigen/PURERGB_MECHANICS.md.
export {useDex} from './purergb';

class Generation implements I.Generation {
  num: I.GenerationNum;

  abilities: Abilities;
  items: Items;
  moves: Moves;
  species: Species;
  types: Types;
  natures: Natures;

  constructor(num: I.GenerationNum) {
    this.num = num;

    this.abilities = new Abilities(num);
    this.items = new Items(num);
    this.moves = new Moves(num);
    this.species = new Species(num);
    this.types = new Types(num);
    this.natures = new Natures();
  }
}
