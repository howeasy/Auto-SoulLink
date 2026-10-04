// conn-watch.js — say so when the 2 s poll stops getting answers, instead of freezing on
// stale data. One handler for the board (#content polls) and every stream overlay (<body>
// polls): a failed poll puts .conn-lost on <body> and fills any .mk-connlost strip; the
// next good poll clears both. The strip is a role=status region, written only on a change
// so a screen reader hears it once. Overlays style body.stream.conn-lost (slink.css).
(function () {
  'use strict';
  var lost = false;

  function isPoll(e) {
    var elt = e.detail && e.detail.elt;
    return !!(elt && elt.getAttribute && /^every\s/.test(elt.getAttribute('hx-trigger') || ''));
  }

  function set(now) {
    if (now === lost) return;
    lost = now;
    document.body.classList.toggle('conn-lost', now);
    document.querySelectorAll('.mk-connlost').forEach(function (el) {
      el.textContent = now ? 'Connection lost — retrying…' : '';
    });
  }

  ['htmx:sendError', 'htmx:responseError', 'htmx:timeout'].forEach(function (name) {
    document.addEventListener(name, function (e) { if (isPoll(e)) set(true); });
  });
  document.addEventListener('htmx:afterRequest', function (e) {
    if (isPoll(e) && e.detail.successful) set(false);
  });
})();
