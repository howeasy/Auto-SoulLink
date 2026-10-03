// trade-resolve.js — the board's "resolve by hand" form for an uncertain or conflicted native
// trade (_board.html, the trade-problem banner). It posts the existing endpoint unchanged:
//   POST /api/debug/resolve_trade {"token", "action": adopt|commit|rollback, "sides"?: {"a"|"b": "traded"|"none"}}
// (server.py handle_debug_resolve_trade -> SoulLinkState.resolve_trade). On the Manager the
// board lives under /runs/<id>, whose relay carries the call to that run, as dashboard.js's
// calc buttons do. It changes rule state, so it asks first, and shows the answer in the form.
// The form is data-morph-keep (dashboard.js), so the 2 s board refresh leaves the choices alone.
(function () {
  'use strict';

  function body(form) {
    var picked = form.querySelector('input[name="action"]:checked');
    var b = { token: form.getAttribute('data-token'), action: picked ? picked.value : '' };
    var sides = {};
    ['a', 'b'].forEach(function (pid) {
      var sel = form.querySelector('select[name="side_' + pid + '"]');
      if (sel && sel.value) sides[pid] = sel.value;
    });
    if (Object.keys(sides).length) b.sides = sides;
    return b;
  }

  function url() {
    var run = /^\/runs\/[^\/]+/.exec(location.pathname);
    return (run ? run[0] : '') + '/api/debug/resolve_trade';
  }

  document.addEventListener('submit', function (ev) {
    var form = ev.target && ev.target.closest && ev.target.closest('form.trade-resolve');
    if (!form) return;
    ev.preventDefault();
    var out = form.querySelector('.trade-resolve-out');
    var say = function (msg) { out.textContent = msg; };
    var b = body(form);
    if (!b.action) { say('Pick an action first.'); return; }
    var sides = b.sides ? Object.keys(b.sides).map(function (p) { return p.toUpperCase() + ' ' + b.sides[p]; }).join(', ') : '';
    if (!window.confirm('Resolve trade ' + b.token + ': ' + b.action + (sides ? ' (' + sides + ')' : '')
        + '?\n\nThis rewrites the run\'s links for both players and cannot be undone.')) return;
    var btn = form.querySelector('button[type="submit"]');
    if (btn) btn.disabled = true;
    say('Resolving…');
    fetch(url(), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (d) {
          if (r.ok && d.ok) say('Resolved. The board updates on its next refresh.');
          else say('Refused: ' + (d.error || ('HTTP ' + r.status)));
        });
      })
      .catch(function (e) { say('Not sent: ' + e.message); })
      .then(function () { if (btn) btn.disabled = false; });
  });
})();
