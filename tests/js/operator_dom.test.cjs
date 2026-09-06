const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

// This test double forbids HTML parsing. Browser review separately confirms
// rendering; these tests exercise actual application functions with API text.
class Element {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.attributes = {}; this.style = {}; this.value = ''; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name]; }
  append(...values) { this.children.push(...values.map(value => value instanceof Element ? value : String(value))); }
  replaceChildren(...values) { this.children = []; this.append(...values); }
  set textContent(value) { this.replaceChildren(String(value)); }
  get textContent() { return this.children.map(child => child instanceof Element ? child.textContent : child).join(''); }
  set innerHTML(_) { throw Error('A renderer tried to parse HTML'); }
  addEventListener() {}
  querySelectorAll() { return []; }
  get options() { return this.children.filter(child => child instanceof Element && child.tagName === 'OPTION'); }
}

function loadDebug(responses, embedded = false) {
  const nodes = new Map();
  const document = {body: new Element('body'), activeElement: null,
    createElement: tag => new Element(tag), querySelectorAll: () => [],
    getElementById(id) { if (!nodes.has(id)) nodes.set(id, new Element('div')); return nodes.get(id); }};
  const counts = {timers: 0, streams: 0};
  const context = {document, console, SLinkDebugEmbedded: embedded, counts, setTimeout: () => 0, clearTimeout() {}, setInterval: () => { counts.timers++; return 0; },
    EventSource: class { constructor() { counts.streams++; } addEventListener() {} close() {} },
    fetch: async url => ({json: async () => responses[url] || {}})};
  context.window = context;
  vm.createContext(context);
  for (const name of ['dom.js', 'debug.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../../server/static', name), 'utf8'), context, {filename: name});
  }
  return context;
}

test('embedded Debug uses the board coordinator without another timer or SSE connection', async () => {
  const context = loadDebug({}, true);
  assert.equal(context.counts.timers, 0);
  assert.equal(context.counts.streams, 0);
  await context.SLinkDebug.refresh({players: {a: {queued: 0}, b: {queued: 0}}, links: [], area_states: {}, pending_captures: {}});
  assert.equal(context.document.getElementById('sse-badge').textContent, 'Board refresh');
  assert.equal(context.counts.timers, 0);
  assert.equal(context.counts.streams, 0);
});

test('debug dynamic labels, keys and attributes remain literal text', async () => {
  const attack = '<img data-ui-probe="unsafe" onerror="bad()">';
  const status = {players: {a: {party_details: {[attack]: {nickname: attack, species_name: attack}}}, b: {party_details: {}}},
    links: [{area_id: attack, area_display: attack, a_nickname: attack, a_species_name: attack, status: 'dead'}],
    pending_captures: {}, area_states: {}};
  const context = loadDebug({'/api/status': status});
  context._lastStatus = status;
  context._allAreas = {[attack]: attack};
  context.updateDataLists();
  context.renderLinksTable();
  const keys = context.document.getElementById('dl-keys');
  assert.equal(keys.options[0].getAttribute('value'), attack);
  assert.ok(keys.textContent.includes(attack));
  assert.ok(context.document.getElementById('ml-links-table').textContent.includes(attack));
  context._mlData = {a_options: [{key: attack, label: attack, pending_area: attack}], b_options: [],
    areas: {[attack]: {d: attack, s: 'unseen', p: ''}}, area_ids: [attack]};
  context._mlPopulateMons('a');
  context.mlFilterAreas();
  const mon = context.document.getElementById('ml-a').options[1];
  assert.equal(mon.getAttribute('value'), attack);
  assert.equal(mon.getAttribute('data-area'), attack);
  assert.equal(mon.textContent, attack);
  assert.ok(context.document.getElementById('ml-area').textContent.includes(attack));
});

test('debug backup, live state and memorial API text cannot become markup', async () => {
  const attack = '<img data-ui-probe="unsafe">';
  const raw = {player_identity: {a: {trainer_name: attack, ot_id: attack}},
    _live: {identity_errors: {b: attack}, party_size: {a: attack}},
    _memorial: {memorial_box_index: 2, pending_memorials: {a: [{key: attack, species_name: attack}]},
      memorial_box_contents: {a: [{key: attack, nickname: attack, species_name: attack, slot: 1, status: attack}]},
      memorial_log: [{area_id: attack, a: {nickname: attack}, b: {species: attack}, cause: attack}]}};
  const context = loadDebug({'/api/debug/raw_state': raw, '/api/debug/backups': {backups: [{slot: 1, modified: attack, size: 1024}]}});
  await context.loadBackups();
  await context.loadLiveState();
  await context.loadMemorial();
  for (const id of ['backup-list', 'live-state-content', 'memorial-content']) {
    assert.ok(context.document.getElementById(id).textContent.includes(attack), id);
  }
});
