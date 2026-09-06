const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {test} = require('node:test');

test('Calc asset build distinguishes JSON sets from executable set extensions on every platform', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'slink-calc-assets-'));
  try {
    const sets = path.join(root, 'src/js/data/sets');
    fs.mkdirSync(sets, {recursive: true});
    fs.mkdirSync(path.join(root, 'calc/dist'), {recursive: true});
    fs.writeFileSync(path.join(sets, 'normal.js'), 'var SETDEX_SV = {\n  "Rattata": {"Trainer": {"level": 50}}\n};\n');
    const extension = '(function () {\n  var ADD = {"Rattata": {}};\n  window.extraSets = ADD;\n})();\n';
    fs.writeFileSync(path.join(sets, 'slink_priority.js'), extension);
    for (const name of ['normal', 'hardcore']) {
      fs.writeFileSync(path.join(root, 'src', name + '.template.html'), '<html><script src="./js/data/sets/normal.js?"></script></html>');
    }
    execFileSync(process.execPath, [path.join(__dirname, '../../calc/build'), 'view'], {cwd: root, stdio: 'pipe'});
    assert.equal(fs.readFileSync(path.join(root, 'dist/js/data/sets/normal.js'), 'utf8'), 'var SETDEX_SV = {"Rattata":{"Trainer":{"level":50}}};');
    assert.equal(fs.readFileSync(path.join(root, 'dist/js/data/sets/slink_priority.js'), 'utf8'), extension);
    assert.ok(fs.existsSync(path.join(root, 'dist/normal.html')));
  } finally {
    // Delete only the exact directory returned by mkdtemp, never its parent.
    assert.ok(root.startsWith(path.join(os.tmpdir(), 'slink-calc-assets-')));
    fs.rmSync(root, {recursive: true, force: true});
  }
});
