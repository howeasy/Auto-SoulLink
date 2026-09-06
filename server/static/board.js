(function () {
  'use strict';
  var dialog = document.getElementById('debug-dialog');
  var returnFocus, debugScript;
  var details = new Map();
  var fonts = ['jersey', 'pixelify', 'classic', 'plex'];

  function payload(id) {
    try { return JSON.parse(document.getElementById(id).textContent); }
    catch (_) { return null; }
  }
  function font(value) {
    if (!fonts.includes(value)) value = 'jersey';
    document.body.classList.remove(...fonts.map(function (name) { return 'font-' + name; }));
    document.body.classList.add('font-' + value);
    document.getElementById('board-font').value = value;
    try { localStorage.setItem('slink-font', value); } catch (_) {}
  }
  function detailKey(node) { return 'slink-board-details:' + node.getAttribute('data-details-key'); }
  function remember(node) {
    var key = detailKey(node);
    details.set(key, node.open);
    try { localStorage.setItem(key, node.open ? '1' : '0'); } catch (_) {}
  }
  function restoreDetails() {
    document.querySelectorAll('details[data-details-key]').forEach(function (node) {
      var key = detailKey(node), open = details.get(key);
      if (open === undefined) {
        try { var saved = localStorage.getItem(key); if (saved !== null) open = saved === '1'; } catch (_) {}
      }
      if (open !== undefined && node.open !== open) node.open = open;
    });
  }
  function operation(button) {
    var action = button.getAttribute('onclick') || '';
    if (action.startsWith('resetRun')) return 'reset';
    if (button.classList.contains('slot-link')) return 'restore';
    if (action.startsWith('doManualLink') || button.getAttribute('data-action') === 'unlink') return 'manual_link';
    if (button.hasAttribute('data-action') || /^(injectEvent|queueCmd|toggleBalls|setAreaState|clearPending)/.test(action)) return 'debug_mutation';
    return null;
  }
  function availability() {
    var decisions = payload('board-debug-operations') || {};
    dialog.querySelectorAll('button').forEach(function (button) {
      var name = operation(button);
      if (!name) return;
      var decision = decisions[name];
      if (!decision || decision.available !== true) {
        button.disabled = true;
        button.dataset.unavailableOperation = name;
        button.title = decision && decision.reason || 'This action is unavailable.';
        var panel = button.closest('.panel') || button.parentElement;
        var id = 'unavailable-' + name + '-' + Array.from(dialog.querySelectorAll('.panel')).indexOf(panel);
        var reason = document.getElementById(id);
        if (!reason) { reason = SLinkDOM.el('p', {id: id, className: 'board-unavailable-reason'}); panel.append(reason); }
        reason.textContent = button.title;
        button.setAttribute('aria-describedby', id);
      } else if (button.dataset.unavailableOperation) {
        button.disabled = false;
        delete button.dataset.unavailableOperation;
        button.removeAttribute('aria-describedby');
        button.removeAttribute('title');
      }
    });
  }
  function refreshDebug() {
    if (!dialog.open || !window.SLinkDebug) return;
    window.SLinkDebug.refresh(payload('board-status')).then(availability).catch(function () {
      document.getElementById('sse-badge').textContent = 'Debug refresh unavailable';
    });
  }
  async function openDebug(trigger) {
    if (trigger.disabled || dialog.open) return;
    returnFocus = document.activeElement;
    dialog.showModal();
    document.body.classList.add('board-modal-open');
    document.getElementById('debug-close').focus();
    availability();
    if (!debugScript) {
      window.SLinkDebugEmbedded = true;
      debugScript = new Promise(function (resolve, reject) {
        var script = document.createElement('script');
        script.src = '/static/debug.js';
        script.onload = resolve;
        script.onerror = reject;
        document.head.append(script);
      });
    }
    try { await debugScript; refreshDebug(); }
    catch (_) { document.getElementById('sse-badge').textContent = 'Debug could not load.'; }
  }
  document.querySelectorAll('[data-debug-open]').forEach(function (button) {
    button.addEventListener('click', function () { openDebug(button); });
  });
  document.getElementById('debug-close').addEventListener('click', function () { dialog.close(); });
  dialog.addEventListener('keydown', function (event) {
    if (event.key !== 'Tab') return;
    var controls = Array.from(dialog.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'))
      .filter(function (node) { return node.getClientRects().length && !node.closest('[hidden]'); });
    var first = controls[0], last = controls[controls.length - 1];
    if (!first) { event.preventDefault(); document.getElementById('debug-close').focus(); }
    else if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  document.addEventListener('focusin', function (event) {
    if (dialog.open && !dialog.contains(event.target)) document.getElementById('debug-close').focus();
  });
  dialog.addEventListener('close', function () {
    document.body.classList.remove('board-modal-open');
    var target = returnFocus && returnFocus.isConnected ? returnFocus : document.querySelector('[data-debug-open]');
    if (target) target.focus();
  });
  dialog.addEventListener('click', function (event) {
    var rect = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
  });
  document.addEventListener('keydown', function (event) {
    if (event.key !== '`' || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.target.closest('input, textarea, select, [contenteditable="true"]')) return;
    event.preventDefault();
    if (dialog.open) dialog.close();
    else openDebug(document.querySelector('[data-debug-open]'));
  });
  document.addEventListener('toggle', function (event) {
    if (event.target.matches('details[data-details-key]')) remember(event.target);
  }, true);
  if (window.Idiomorph && Idiomorph.defaults && Idiomorph.defaults.callbacks) {
    var previous = Idiomorph.defaults.callbacks.beforeAttributeUpdated;
    Idiomorph.defaults.callbacks.beforeAttributeUpdated = function (name, node, type) {
      if (name === 'open' && node.matches('details[data-details-key]')) return false;
      return previous ? previous(name, node, type) : true;
    };
  }
  document.addEventListener('htmx:afterSettle', function () {
    document.getElementById('board-connection-error').hidden = true;
    var available = document.querySelector('[data-run-available]');
    document.querySelectorAll('[data-debug-open]').forEach(function (button) {
      button.disabled = available && available.dataset.runAvailable !== 'true';
    });
    if (available && available.dataset.runAvailable !== 'true' && dialog.open) dialog.close();
    restoreDetails();
    refreshDebug();
  });
  ['htmx:responseError', 'htmx:sendError'].forEach(function (name) {
    document.addEventListener(name, function () { document.getElementById('board-connection-error').hidden = false; });
  });
  document.addEventListener('slink:debug-rendered', availability);
  document.getElementById('board-font').addEventListener('change', function (event) { font(event.target.value); });
  var preference = 'jersey';
  try { preference = localStorage.getItem('slink-font') || preference; } catch (_) {}
  font(preference);
  window.addEventListener('storage', function (event) { if (event.key === 'slink-font') font(event.newValue); });
  var theme = document.querySelector('.theme-switcher');
  if (theme) document.getElementById('board-theme-slot').append(theme);
  document.querySelectorAll('[data-calc-link]').forEach(function (link) {
    var url = new URL(link.href);
    url.searchParams.set('slink', window.location.origin + SLinkRun.base);
    link.href = url.href;
  });
  restoreDetails();
})();
