/* One serial polling coordinator per application document. */
(function () {
  'use strict';
  var subscriptions = new Map(), timer = null, running = false, suspended = false;
  async function tick() {
    timer = null;
    if (running || suspended) return;
    running = true;
    try { await Promise.allSettled([...subscriptions.values()].map(function (read) { return Promise.resolve().then(read); })); }
    finally { running = false; if (!suspended) timer = setTimeout(tick, 2000); }
  }
  window.SLinkPoll = Object.freeze({
    subscribe: function (id, read) { subscriptions.set(id, read); if (!running && timer === null) timer = setTimeout(tick, 0); },
    refresh: function () { if (!running) { if (timer !== null) clearTimeout(timer); timer = setTimeout(tick, 0); } }
  });
  window.addEventListener('pagehide', function () { suspended = true; if (timer !== null) clearTimeout(timer); timer = null; });
  window.addEventListener('pageshow', function () { if (suspended) { suspended = false; SLinkPoll.refresh(); } });
})();
