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
    SLinkPoll: {subscribe(id, read) { assert.equal(id, 'obs'); poll = read; }}};
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
