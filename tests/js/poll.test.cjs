const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

test('application polling stays serial and resumes after browser back navigation', async () => {
  const timers = new Map(), events = new Map();
  let next = 0, release, reads = 0;
  const gate = new Promise(resolve => { release = resolve; });
  const context = {setTimeout(fn) { timers.set(++next, fn); return next; }, clearTimeout(id) { timers.delete(id); },
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
  assert.equal(timers.size, 0);
  release();
  await running;
  assert.equal(timers.size, 1);
  events.get('pagehide')();
  assert.equal(timers.size, 0);
  events.get('pageshow')();
  assert.equal(timers.size, 1);
  const [resumedId, resumed] = timers.entries().next().value;
  timers.delete(resumedId);
  await resumed();
  assert.equal(reads, 4);
  assert.equal(timers.size, 1);
});
