const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

function fixture() {
  return JSON.parse(fs.readFileSync(path.join(__dirname, '../fixtures/ui/calc_synthetic.json'), 'utf8'));
}
function browserEngine() {
  const context = {console, document: {querySelectorAll: () => []}};
  context.window = context;
  vm.createContext(context);
  // No Node require/exports globals: execute exactly the browser build.
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../../calc/dist/calc/slink-browser.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../../server/static/calc-preview.js'), 'utf8'), context);
  return context.SLinkCalc;
}

test('real browser bundle calculates named moves with max-HP percentages and current-HP KO checks', () => {
  const engine = browserEngine(), input = fixture();
  const before = JSON.stringify(input), row = engine.calculate(input)[0];
  assert.equal(row.minimum, 33);
  assert.equal(row.maximum, 39);
  assert.equal(row.defenderMaxHP, 105);
  assert.equal(row.defenderCurrentHP, 10);
  assert.equal(row.lowPercent, 31.4);
  assert.equal(row.highPercent, 37.1);
  assert.equal(row.ohko, true);
  assert.equal(JSON.stringify(input), before);
  input.defender.options.curHP = 60;
  const twoHits = engine.calculate(input)[0];
  assert.equal(twoHits.ohko, false);
  assert.equal(twoHits.twoHko, true);
  assert.equal(twoHits.lowPercent, 31.4);
});

test('missing inputs, numeric move IDs and unselected doubles targets are unavailable', () => {
  const engine = browserEngine(), input = fixture();
  assert.throws(() => engine.calculate({...input, moves: [33]}), /move names/);
  assert.throws(() => engine.calculate({...input, complete: false}), /Complete battle inputs/);
  assert.throws(() => engine.calculate({...input, field: {gameType: 'Doubles'}}), /Select a doubles target/);
  const missing = fixture();
  delete missing.attacker.options.ivs;
  assert.throws(() => engine.calculate(missing), /Complete Pokémon inputs/);
});
