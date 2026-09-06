const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

function source() {
  let poll, response, frame, reloads = 0, morphs = 0;
  const motion = {matches: true};
  const root = {dataset: {availability: 'live', scrollEnabled: 'true'}, style: {}, className: 'preset-links', classList: {contains() { return false; }},
    scrollHeight: 500, clientHeight: 100, scrollTop: 0,
    querySelector() { return null; }, replaceChildren() { this.children = []; },
    append(node) { this.children.push(node); }};
  const error = {hidden: false};
  const context = {URL, Map, Number, String, Math, innerHeight: 380, innerWidth: 280,
    document: {body: {dataset: {sourceRevision: '2', savedSource: 'true', fragmentUrl: '/broadcast/sources/id/fragment'}},
      getElementById(id) { return id === 'root' ? root : error; },
      createElement() { return {}; }, addEventListener() {}},
    location: {href: 'http://localhost/broadcast/sources/id', reload() { reloads++; }},
    fetch: async () => response,
    DOMParser: class { parseFromString() { return {getElementById() { return {dataset: {revision: '2'}}; }}; } },
    Idiomorph: {morph() { morphs++; root.dataset.availability = 'live'; }},
    SLinkPoll: {subscribe(name, callback) { assert.equal(name, 'broadcast-source'); poll = callback; }},
    addEventListener() {}, requestAnimationFrame(callback) { frame = callback; }, matchMedia() { return motion; }};
  context.window = context;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../server/static/broadcast-source.js'), 'utf8'), context);
  return {root, error, motion, animate: now => frame(now), get reloads() { return reloads; }, get morphs() { return morphs; },
    async tick(status, revision = '2') { response = {status, ok: status === 200, headers: {get() { return revision; }}, text: async () => '<main/>'}; await poll(); }};
}

test('deleted sources clear telemetry and stale error banners; polling can recover', async () => {
  const page = source();
  await page.tick(404);
  assert.equal(page.root.dataset.availability, 'deleted');
  assert.equal(page.root.dataset.scrollEnabled, 'false');
  assert.equal(page.error.hidden, true);
  assert.match(page.root.children[0].textContent, /deleted/);
  await page.tick(503);
  assert.equal(page.error.hidden, false);
  await page.tick(200);
  assert.equal(page.morphs, 1);
  assert.equal(page.error.hidden, true);
});

test('configuration changes reload the shell before any previous-run content is applied', async () => {
  const page = source();
  await page.tick(409);
  await page.tick(200, '3');
  assert.equal(page.reloads, 2);
  assert.equal(page.morphs, 0);
});


test('reduced motion stops scrolling and configured speed resumes without another loop', () => {
  const page = source();
  page.animate(100); page.animate(200);
  assert.equal(page.root.scrollTop, 0);
  page.motion.matches = false;
  page.root.dataset.scrollSpeed = '2';
  page.animate(300);
  assert.ok(Math.abs(page.root.scrollTop - 4.4) < 1e-9);
  page.motion.matches = true;
  page.animate(400);
  assert.ok(Math.abs(page.root.scrollTop - 4.4) < 1e-9);
});
