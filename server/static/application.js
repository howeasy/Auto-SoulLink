(function () {
  'use strict';
  var state = JSON.parse(document.getElementById('application-state').textContent);
  function rail(runs) {
    var list = document.getElementById('run-list');
    if (!list) return;
    var live = new Set();
    runs.forEach(function (run) {
      var id = 'run-link-' + run.run_id, link = document.getElementById(id);
      if (!link) { link = SLinkDOM.el('a', {id:id, className:'board-run-link'}); list.append(link); }
      live.add(id);
      link.href = '/runs/' + encodeURIComponent(run.run_id) + '/' + state.destination + (state.tab ? '?tab=' + encodeURIComponent(state.tab) : '');
      link.classList.toggle('active', run.run_id === state.run_id);
      if (run.run_id === state.run_id) link.setAttribute('aria-current','true'); else link.removeAttribute('aria-current');
      link.replaceChildren(SLinkDOM.el('span',{className:'board-dot '+run.status}), SLinkDOM.el('span', {}, SLinkDOM.el('b',{},run.name), SLinkDOM.el('small',{},run.status)));
    });
    list.querySelectorAll('.board-run-link').forEach(function (link) { if (!live.has(link.id)) link.remove(); });
  }
  SLinkPoll.subscribe('application', async function (signal) {
    var running = !state.manager;
    try {
      if (state.manager) {
        var response = await fetch('/api/runs', {signal:signal}), data = await response.json();
        if (!response.ok) throw new Error(data.error);
        rail(data.runs);
        running = data.runs.some(function (run) { return run.run_id === state.run_id && run.status === 'running'; });
      }
      var ui = null;
      if (running && state.run_id) {
        var response = await SLinkRun.fetch('/api/ui-state', {signal:signal});
        if (!response.ok) throw new Error('Run unavailable');
        ui = await response.json();
      }
      document.getElementById('board-status').textContent = JSON.stringify(ui && ui.status);
      document.getElementById('board-debug-operations').textContent = JSON.stringify(ui && ui.debug_operations || {});
      document.querySelector('[data-run-available]').dataset.runAvailable = ui ? 'true' : 'false';
      document.getElementById('board-connection-error').hidden = !state.run_id || !!ui;
    } catch (_) {
      document.querySelector('[data-run-available]').dataset.runAvailable = 'false';
      document.getElementById('board-connection-error').hidden = !state.run_id;
    }
    document.dispatchEvent(new CustomEvent('slink:page-update'));
  });
})();
