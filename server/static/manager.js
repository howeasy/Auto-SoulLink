(function () {
  'use strict';
  var busy = false;
  async function post(path, body) {
    var response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
    var result = await response.json();
    if (!response.ok || result.ok === false) throw new Error(result.error || 'The request could not be completed.');
    return result;
  }
  function feedback(message) {
    var node = document.getElementById('manager-result');
    if (!node) {
      node = document.createElement('p'); node.id = 'manager-result'; node.className = 'board-note warning'; node.setAttribute('role', 'status');
      document.querySelector('.board-main').prepend(node);
    }
    node.textContent = message;
  }
  document.addEventListener('htmx:beforeRequest', function (event) { if (busy) event.preventDefault(); });
  async function change(action, id, button) {
    if (busy) return;
    busy = true; button.disabled = true;
    if (window.htmx) htmx.trigger('#content', 'htmx:abort');
    try {
      await post('/api/runs/' + encodeURIComponent(id) + '/' + action);
      if (action === 'delete') window.location.assign('/');
      else window.location.reload();
    } catch (error) { feedback(error.message); button.disabled = false; busy = false; }
  }
  document.addEventListener('click', function (event) {
    var button = event.target.closest('[data-run-action], [data-delete-review]');
    if (!button) return;
    var holder = button.closest('[data-run-id]');
    if (!holder) return;
    var action = button.dataset.runAction;
    if (button.hasAttribute('data-delete-review')) {
      var name = document.querySelector('.board-runname').textContent;
      if (!window.confirm('Delete “' + name + '”? This permanently removes this run’s saved progress and cartridge artifacts.')) return;
      action = 'delete';
    }
    change(action, holder.dataset.runId, button);
  });
  document.addEventListener('submit', async function (event) {
    var form = event.target;
    if (!form.matches('[data-cartridge-form]')) return;
    event.preventDefault();
    var button = form.querySelector('[type="submit"]');
    button.disabled = true;
    try {
      await post('/api/runs/' + encodeURIComponent(form.dataset.runId) + '/cartridges', Object.fromEntries(new FormData(form)));
      window.location.reload();
    } catch (error) { feedback(error.message); button.disabled = false; }
  });
  var form = document.getElementById('new-run');
  if (!form) return;
  function family() {
    var gen1 = form.elements.game_family.value === 'gen1_rby';
    form.querySelector('[data-gen1-setup]').hidden = !gen1;
    form.elements.auto_start.checked = !gen1;
  }
  form.elements.game_family.addEventListener('change', family);
  family();
  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    var button = form.querySelector('[type="submit"]'), result = document.getElementById('create-result');
    button.disabled = true; result.textContent = 'Creating run…';
    var body = Object.fromEntries(new FormData(form));
    form.querySelectorAll('[type="checkbox"]').forEach(function (input) { body[input.name] = input.checked; });
    try {
      var response = await post('/api/runs/new', body);
      window.location.assign('/runs/' + encodeURIComponent(response.run.run_id) + '/?view=setup');
    } catch (error) { result.textContent = error.message; button.disabled = false; }
  });
  var fonts = ['jersey', 'pixelify', 'classic', 'plex'], picker = document.getElementById('board-font');
  function font(value) {
    if (!fonts.includes(value)) value = 'jersey';
    document.body.classList.remove(...fonts.map(function (name) { return 'font-' + name; }));
    document.body.classList.add('font-' + value); picker.value = value;
    try { localStorage.setItem('slink-font', value); } catch (_) {}
  }
  var preference = 'jersey';
  try { preference = localStorage.getItem('slink-font') || preference; } catch (_) {}
  font(preference);
  picker.addEventListener('change', function () { font(picker.value); });
  window.addEventListener('storage', function (event) { if (event.key === 'slink-font') font(event.newValue); });
  var theme = document.querySelector('.theme-switcher');
  if (theme) document.getElementById('board-theme-slot').append(theme);
})();
