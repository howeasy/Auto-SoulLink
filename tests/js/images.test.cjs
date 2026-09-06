const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

function images({tainted = false, alpha = false} = {}) {
  const pixels = new Uint8ClampedArray(alpha ? [1, 2, 3, 199, 4, 5, 6, 200] : [0, 255, 0, 255, 9, 8, 7, 255]);
  let canvases = 0, requests = 0;
  const revoked = [], sprites = [], badges = [];
  function img(src) { return {src, dataset: {}, naturalWidth: 2, naturalHeight: 1, complete: true,
    getAttribute(name) { return this[name]; }, addEventListener() {}}; }
  const context = {document: {addEventListener() {},
    querySelectorAll(selector) { return selector === 'img.bdg-img' ? badges : sprites; },
    createElement(tag) { assert.equal(tag, 'canvas'); canvases++; return {
      getContext() { return {drawImage() {}, getImageData() { if (tainted) throw new Error('SecurityError'); return {data: pixels}; }, putImageData() {}}; },
      toDataURL() { return 'data:image/png;base64,clean'; }}; }},
    fetch: async () => { requests++; return {blob: async () => ({})}; },
    URL: {createObjectURL() { return 'blob:test'; }, revokeObjectURL(url) { revoked.push(url); }},
    Image: class { constructor() { this.naturalWidth = 2; this.naturalHeight = 1; } set src(_) { this.onload(); } }};
  context.window = context;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../server/static/images.js'), 'utf8'), context);
  return {api: context.SLinkImages, img, sprites, badges, pixels, revoked,
    get canvases() { return canvases; }, get requests() { return requests; }};
}

test('shared chroma-key removes only background-colored pixels and reuses the result', () => {
  const page = images(), url = 'https://example.test/funnotbun/pikachu.png';
  const first = page.img(url); page.sprites.push(first); page.api.processSprites();
  assert.equal(page.pixels[3], 0);
  assert.equal(page.pixels[7], 255);
  const second = page.img(url); page.sprites.push(second); page.api.processSprites();
  assert.equal(first.src, second.src);
  assert.equal(page.canvases, 1);
  assert.equal(page.api.cachedSprite(url), first.src);
});

test('unreadable sprite pixels leave the original image in place', () => {
  const page = images({tainted: true}), original = 'https://example.test/funnotbun/pikachu.png';
  const sprite = page.img(original); page.sprites.push(sprite); page.api.processSprites();
  assert.equal(sprite.src, original);
  assert.equal(page.api.cachedSprite(original), undefined);
});

test('badge alpha cleanup preserves the threshold and releases temporary URLs even on failure', async () => {
  for (const tainted of [false, true]) {
    const page = images({tainted, alpha: true}), original = 'https://example.test/badge.png';
    const badge = page.img(original); page.badges.push(badge); page.api.processBadges();
    await new Promise(setImmediate);
    assert.deepEqual(page.revoked, ['blob:test']);
    assert.equal(page.requests, 1);
    if (tainted) assert.equal(badge.src, original);
    else { assert.equal(page.pixels[3], 0); assert.equal(page.pixels[7], 255); assert.match(badge.src, /^data:/); }
  }
});
