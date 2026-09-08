const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

test('application polling stays serial and resumes after browser back navigation', async () => {
  const timers = new Map(), events = new Map(), delays = new Map();
  let next = 0, release, reads = 0;
  const gate = new Promise(resolve => { release = resolve; });
  const context = {AbortController, setTimeout(fn, delay) { timers.set(++next, fn); delays.set(next, delay); return next; }, clearTimeout(id) { timers.delete(id); },
    addEventListener(name, fn) { events.set(name, fn); }};
  context.window = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../../server/static/poll.js'), 'utf8'), context);
  context.SLinkPoll.subscribe('slow', async () => { reads++; await gate; });
  context.SLinkPoll.subscribe('failing', () => { reads++; throw new Error('isolated failure'); });
  assert.equal(timers.size, 1);
  const [id, tick] = timers.entries().next().value;
  timers.delete(id);
  const running = tick();
  await Promise.resolve();
  context.SLinkPoll.refresh();
  context.SLinkPoll.refresh();
  assert.equal(reads, 2);
  assert.equal(timers.size, 1, 'only the active read deadline remains');
  assert.equal(delays.get(timers.keys().next().value), 10000);
  release();
  await running;
  assert.equal(timers.size, 1);
  assert.equal(delays.get(timers.keys().next().value), 0, 'refresh during a read queues one immediate follow-up');
  const [followUpId, followUp] = timers.entries().next().value;
  timers.delete(followUpId);
  await followUp();
  assert.equal(reads, 4);
  assert.equal(timers.size, 1);
  assert.equal(delays.get(timers.keys().next().value), 2000, 'coalesced refresh returns to normal cadence');
  events.get('pagehide')();
  assert.equal(timers.size, 0);
  context.SLinkPoll.refresh();
  context.SLinkPoll.subscribe('hidden', () => {});
  assert.equal(timers.size, 0, 'hidden documents must not schedule polling');
  events.get('pageshow')();
  assert.equal(timers.size, 1);
  const [resumedId, resumed] = timers.entries().next().value;
  timers.delete(resumedId);
  await resumed();
  assert.equal(reads, 6);
  assert.equal(timers.size, 1);
  assert.equal(delays.get(timers.keys().next().value), 2000, 'immediate refresh does not create a polling loop');
});

function coordinator() {
  const timers = new Map(), events = new Map();
  let next = 0;
  const context = {AbortController,
    setTimeout(fn, delay) { timers.set(++next, {fn, delay}); return next; },
    clearTimeout(id) { timers.delete(id); }, addEventListener(name, fn) { events.set(name, fn); }};
  context.window = context;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../server/static/poll.js'), 'utf8'), context);
  return {poll: context.SLinkPoll, timers, events, fire(delay) {
    const entry = [...timers].find(([, timer]) => timer.delay === delay);
    assert.ok(entry, 'expected timer with delay ' + delay);
    timers.delete(entry[0]); return entry[1].fn();
  }};
}

test('a stalled response body is aborted and the next serial poll recovers', async () => {
  const page = coordinator();
  let reads = 0, aborted = 0, rendered = 0, signal;
  page.poll.subscribe('body', async current => {
    signal = current;
    reads++;
    // Headers have arrived, but body consumption is still bound to fetch's signal.
    const response = {text: () => reads > 1 ? Promise.resolve('fresh') : new Promise((resolve, reject) => {
      current.addEventListener('abort', () => { aborted++; reject(new Error('aborted body')); }, {once: true});
    })};
    await response.text();
    rendered++;
  });
  const running = page.fire(0);
  await Promise.resolve();
  assert.equal(reads, 1);
  page.poll.refresh();
  assert.equal(page.timers.size, 1);
  page.fire(10000);
  await running;
  assert.equal(signal.aborted, true);
  assert.equal(aborted, 1);
  assert.equal(rendered, 0);
  assert.equal(page.timers.size, 1);
  await page.fire(0);
  assert.equal(reads, 2);
  assert.equal(rendered, 1);
  assert.equal(signal.aborted, false);
  assert.equal(page.timers.size, 1);
  assert.equal([...page.timers.values()][0].delay, 2000);
});

test('page exit aborts active reads and back navigation resumes with a fresh signal', async () => {
  const page = coordinator();
  const signals = [];
  page.poll.subscribe('waiting', signal => {
    signals.push(signal);
    return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new Error('left page')), {once: true}));
  });
  const running = page.fire(0);
  await Promise.resolve();
  page.events.get('pagehide')();
  assert.equal(signals[0].aborted, true);
  page.events.get('pageshow')(); // May arrive before abort rejection has unwound.
  await running;
  assert.equal(page.timers.size, 1);
  const resumed = page.fire(0);
  await Promise.resolve();
  assert.equal(signals.length, 2);
  assert.notEqual(signals[0], signals[1]);
  assert.equal(signals[1].aborted, false);
  page.events.get('pagehide')();
  await resumed;
  assert.equal(page.timers.size, 0);
});

test('deadline cancels a real fetch after headers arrive but its body stalls', async () => {
  const server = http.createServer((request, response) => {
    response.writeHead(200, {'Content-Type': 'text/plain'});
    response.flushHeaders(); // Intentionally leave the response body unfinished.
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const page = coordinator();
  let bodyStarted, failure, rendered = false;
  const headers = new Promise(resolve => { bodyStarted = resolve; });
  page.poll.subscribe('streaming', async signal => {
    try {
      const response = await fetch('http://127.0.0.1:' + server.address().port, {signal});
      bodyStarted();
      await response.text();
      rendered = true;
    } catch (error) { failure = error; }
  });
  try {
    const running = page.fire(0);
    await headers;
    page.fire(10000);
    await running;
    assert.equal(failure.name, 'AbortError');
    assert.equal(rendered, false);
    assert.equal(page.timers.size, 1);
    assert.equal([...page.timers.values()][0].delay, 2000);
  } finally {
    page.events.get('pagehide')();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
});

test('OBS polling awaits both scene bodies and passes through the tick signal', async () => {
  const nodes = new Map(), signals = [];
  let poll, settled = false, aborted = 0;
  function element() { return {value: '', options: [], addEventListener() {}, appendChild(node) { this.options.push(node); }}; }
  const context = {Set, Promise,
    document: {activeElement: null, getElementById(id) { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); },
      createElement: element, querySelectorAll() { return []; }},
    SLinkRun: {async fetch(url, options) {
      if (!url.includes('/scenes/')) return {json: async () => ({connections: {}, groups: [], areas: []})};
      signals.push(options && options.signal);
      return {json: () => new Promise((resolve, reject) => options.signal.addEventListener('abort', () => {
        aborted++; reject(new Error('scene body aborted'));
      }, {once: true}))};
    }},
    SLinkPoll: {subscribe(id, read) { assert.equal(id, 'obs'); poll = read; }, status() {}}};
  context.window = context;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../server/static/obs.js'), 'utf8'), context);
  const controller = new AbortController();
  const reading = poll(controller.signal).then(() => { settled = true; });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(signals, [controller.signal, controller.signal]);
  assert.equal(settled, false, 'scene reads must remain inside the polling tick');
  controller.abort();
  await reading;
  assert.equal(aborted, 2);
  assert.equal(settled, true);
});

for (const [file, banner] of [
  ['application.js', 'board-connection-error'], ['broadcast-source.js', 'source-error'],
  ['broadcast-sources.js', 'sources-stale'], ['manager-obs.js', 'manager-obs-stale'],
  ['obs.js', 'obs-stale'], ['twitch.js', 'twitch-stale'],
]) {
  test(file + ' forwards the poll signal and shows a recoverable timeout state', async () => {
    const nodes = new Map(), calls = [];
    let read, collect = false, fail = true;
    function element() { return {hidden: true, textContent: '', value: '', style: {}, dataset: {}, options: [],
      classList: {add() {}, remove() {}, toggle() {}, contains() { return false; }},
      addEventListener() {}, append(...items) { this.options.push(...items); }, appendChild(item) { this.options.push(item); },
      replaceChildren(...items) { this.options = items; }, setAttribute() {}, removeAttribute() {},
      querySelector() { return null; }, querySelectorAll() { return []; }}; }
    const node = id => { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); };
    node('application-state').textContent = '{"manager":true,"run_id":"run_a","destination":"broadcast"}';
    node('root').dataset = {sourceRevision: '2'};
    const data = {runs: [{run_id: 'run_a', status: 'running', name: 'Run A'}], sources: [], presets: [],
      status: 'disabled', config: {revision: 1, enabled: false, rules: [], connections: {a: {host: '', port: 1}, b: {host: '', port: 1}}},
      applications: {}, records: [], blocked_endpoints: [], connections: {}, scenes: [], groups: [], areas: []};
    async function fetch(url, options) {
      if (collect) {
        calls.push({url, signal: options && options.signal});
        if (fail) return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => {
          const error = new Error('BROWSER_INTERNAL_ABORT_TEXT'); error.name = 'AbortError'; reject(error);
        }, {once: true}));
      }
      return {ok: true, status: 200, json: async () => data, text: async () => '<main/>', headers: {get() { return '2'; }}};
    }
    const context = {AbortController, URL, fetch, setTimeout() {}, clearTimeout() {}, addEventListener() {},
      requestAnimationFrame() {}, matchMedia: () => ({matches: true}), innerHeight: 600, innerWidth: 800,
      location: {href: 'http://localhost/', reload() {}},
      CustomEvent: class {}, DOMParser: class { parseFromString() { return {getElementById: () => ({dataset: {revision: '2'}})}; } },
      Idiomorph: {morph() {}},
      document: {activeElement: null, body: {dataset: {sourceRevision: '2', savedSource: 'true', fragmentUrl: '/fragment'}},
        getElementById: node, createElement: element, querySelector: () => element(), querySelectorAll: () => [],
        addEventListener() {}, dispatchEvent() {}},
      SLinkRun: {fetch}, SLinkDOM: {el: element}};
    context.window = context;
    vm.createContext(context);
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../../server/static/poll.js'), 'utf8'), context);
    context.SLinkPoll = {...context.SLinkPoll, subscribe(id, callback) { assert.equal(read, undefined); read = callback; }};
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../../server/static', file), 'utf8'), context);
    await new Promise(resolve => setImmediate(resolve));
    collect = true;
    const controller = new AbortController(), pending = read(controller.signal);
    await new Promise(resolve => setImmediate(resolve));
    assert.ok(calls.length > 0);
    assert.ok(calls.every(call => call.signal === controller.signal), 'every request needs the tick signal');
    controller.abort();
    await pending;
    assert.equal(node(banner).hidden, false);
    assert.ok([...nodes.values()].every(item => !item.textContent.includes('BROWSER_INTERNAL_ABORT_TEXT')));
    fail = false; calls.length = 0;
    const fresh = new AbortController();
    await read(fresh.signal);
    assert.ok(calls.every(call => call.signal === fresh.signal));
    assert.equal(node(banner).hidden, true, 'successful recovery clears the stale indicator');
    if (banner.endsWith('-stale')) {
      fail = true;
      const leaving = new AbortController(), exiting = read(leaving.signal);
      await new Promise(resolve => setImmediate(resolve));
      leaving.abort('slink-pagehide');
      await exiting;
      assert.equal(node(banner).hidden, true, 'page exit must not publish a timeout notice');
    }
  });
}

test('every production subscriber has signal and timeout presentation coverage', () => {
  const root = path.join(__dirname, '../../server/static');
  const subscribers = fs.readdirSync(root, {recursive: true}).filter(file => file.endsWith('.js') &&
    /SLinkPoll\s*\.\s*subscribe\s*\(/.test(fs.readFileSync(path.join(root, file), 'utf8'))).sort();
  assert.deepEqual(subscribers, ['application.js', 'broadcast-source.js', 'broadcast-sources.js',
    'manager-obs.js', 'obs.js', 'twitch.js']);
});

test('a noncooperative reader cannot overlap a new tick after cancellation', async () => {
  const page = coordinator();
  let release, signal;
  const gate = new Promise(resolve => { release = resolve; });
  page.poll.subscribe('ignores-abort', received => { signal = received; return gate; });
  const running = page.fire(0);
  await Promise.resolve();
  page.fire(10000);
  page.poll.refresh();
  await Promise.resolve();
  assert.equal(signal.aborted, true);
  assert.equal(page.timers.size, 0, 'must wait for actual work to settle, never race abandoned DOM work');
  release();
  await running;
  assert.equal(page.timers.size, 1);
  assert.equal([...page.timers.values()][0].delay, 0);
});
