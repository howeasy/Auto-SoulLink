const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

function editor() {
  const nodes = new Map();
  let poll, pending, revision = 1;
  class Element {
    constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.events = {}; this.value = ''; this.isConnected = true; }
    setAttribute(key, value) { this.attributes[key] = value; if (key === 'value') this.value = value; if (key === 'data-source-id') this.dataset.sourceId = value; }
    getAttribute(key) { return this.attributes[key]; }
    addEventListener(key, callback) { this.events[key] = callback; }
    append(...items) { this.children.push(...items); }
    replaceChildren(...items) { this.children = items; }
    querySelectorAll(selector) { return selector === 'button' ? this.children.filter(item => item.tagName === 'button') : []; }
    querySelector() { return null; }
    focus() { document.activeElement = this; }
  }
  const document = {activeElement: null, createElement: tag => new Element(tag),
    getElementById(id) { if (!nodes.has(id)) nodes.set(id, new Element('div')); return nodes.get(id); }};
  const node = id => document.getElementById(id);
  node('application-state').textContent = '{"run_id":"run_a"}';
  const saved = () => ({id: 'source', revision, name: 'Saved ' + revision, run_id: 'run_a', preset: 'party', players: ['a'], layout: '', theme: 'transparent', controls: {}});
  const collection = () => ({sources: [saved()], runs: [{run_id: 'run_a', name: 'Run A', status: 'running'}],
    presets: [{id: 'party', name: 'Party', player_choices: [['a'], ['b'], ['a', 'b']], layouts: [''], defaults: {}, event_filters: [], sizes: [{label: '280×380', width: 280, height: 380}]}]});
  const response = data => ({ok: true, json: async () => data});
  const context = {document, structuredClone, location: {origin: 'http://localhost'},
    SLinkPoll: {subscribe(name, callback) { poll = callback; }, refresh() {}},
    fetch: async (url, options = {}) => {
      if (options.method === 'PATCH') { revision++; return response({source: saved()}); }
      if (pending) return pending;
      return response(collection());
    }};
  context.window = context;
  vm.createContext(context);
  for (const file of ['dom.js', 'broadcast-sources.js']) vm.runInContext(fs.readFileSync(path.join(__dirname, '../../server/static', file), 'utf8'), context);
  return {node, poll: () => poll(), choose: () => node('source-list').children[0].events.click(),
    defer() { const stale = collection(); let release; pending = new Promise(resolve => { release = () => resolve(response(stale)); }); return release; }};
}

test('unchanged polling preserves source controls and switching preserves an unsaved draft', async () => {
  const page = editor();
  await page.poll(); page.choose();
  const button = page.node('source-list').children[0];
  button.focus();
  await page.poll();
  assert.equal(page.node('source-list').children[0], button);
  page.node('source-name').value = 'My draft';
  page.node('source-editor').events.input();
  page.node('source-new').events.click();
  assert.equal(page.node('source-name').value, 'My draft');
  assert.match(page.node('sources-message').textContent, /Save or discard/);
  page.node('source-reset').events.click();
  assert.equal(page.node('source-name').value, 'Saved 1');
});

test('a delayed collection response cannot replace a newer successful save', async () => {
  const page = editor();
  await page.poll(); page.choose();
  const release = page.defer();
  const waiting = page.poll();
  await page.node('source-editor').events.submit({preventDefault() {}});
  assert.equal(page.node('source-name').value, 'Saved 2');
  release(); await waiting;
  assert.equal(page.node('source-name').value, 'Saved 2');
  assert.equal(page.node('source-revision').textContent, 'Configuration revision 2');
});
