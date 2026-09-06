// Execute the actual RR calculator TypeScript; dev compiler is explicit.
// This preserves existing calculator behavior, not a cartridge damage proof.
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const crypto = require('crypto');
const root = path.resolve(process.argv[2] || process.cwd());
assert(process.argv[3], 'Supply the TypeScript package directory explicitly');
const ts = require(path.resolve(process.argv[3]));
assert.strictEqual(ts.version, '4.9.5');
const sources = {};
require.extensions['.ts'] = (mod, file) => {
  assert(file.startsWith(path.join(root, 'calc', 'calc', 'src') + path.sep));
  const source = fs.readFileSync(file);
  sources[path.relative(root, file)] = crypto.createHash('sha256').update(source).digest('hex');
  mod._compile(ts.transpileModule(source.toString('utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020},
  }).outputText, file);
};
const C = require(path.join(root, 'calc/calc/src/index.ts'));
const power = require(path.join(root, 'calc/calc/src/mechanics/gen789.ts')).calculateBasePowerSMSSSV;
const gen = C.Generations.get(9);
const rows = [];
for (const [status, ability] of [['', 'Thick Fat'], ['psn', 'Thick Fat'], ['tox', 'Thick Fat'],
  ['brn', 'Thick Fat'], ['par', 'Thick Fat'], ['slp', 'Thick Fat'], ['frz', 'Thick Fat'], ['', 'Comatose']]) {
  const a = new C.Pokemon(gen, 'Qwilfish-Hisui', {level: 50, ability: 'Poison Point'});
  const d = new C.Pokemon(gen, 'Snorlax', {level: 50, ability, status});
  const move = new C.Move(gen, 'Barb Barrage');
  const bp = power(gen, a, d, move, new C.Field(), false, {});
  const damage = C.calculate(gen, a, d, move).range();
  const boosted = !!status || ability === 'Comatose';
  assert.strictEqual(bp, boosted ? 120 : 60);
  assert.deepStrictEqual(damage, boosted ? [93, 109] : [46, 55]);
  rows.push({status, ability, bp, damage});
}
console.log(JSON.stringify({scope: 'RR calculator-source regression; no native damage or live-input proof',
  node: process.version, typescript: ts.version, cases: rows, sources}, null, 2));
