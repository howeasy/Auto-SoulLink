function _debugSection(title, children) {
  return SLinkDOM.el('div', {className: 'debug-data-row'}, SLinkDOM.el('b', {}, title), ' ', children);
}
function _debugOption(value, text) {
  return SLinkDOM.el('option', {value: value}, text);
}
// ── Helpers ──────────────────────────────────────────────────────────────
function showResult(el, ok, data) {
  el.style.display = 'block';
  el.className = 'result ' + (ok ? 'ok' : 'err');
  el.textContent = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
}
async function api(method, path, body) {
  var opts = {method: method, headers: {'Content-Type':'application/json'}};
  if (body !== undefined) opts.body = JSON.stringify(body);
  var r = await SLinkRun.fetch(path, opts);
  return await r.json();
}
function flashPanel(el) {
  while (el && !el.classList.contains('panel')) el = el.parentElement;
  if (el) { el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash'); }
}

// ── SSE live updates ────────────────────────────────────────────────────
var _sseOk = false;
var _lastStatus = null;
var _refreshQueued = false;

function initSSE() {
  var src = new EventSource(SLinkRun.url('/api/events'));
  src.addEventListener('status', function(e) {
    _sseOk = true;
    updateSSEBadge(true);
    try { _lastStatus = JSON.parse(e.data); } catch(x) {}
    scheduleRefresh();
  });
  src.addEventListener('ping', function() {
    _sseOk = true;
    updateSSEBadge(true);
    scheduleRefresh();
  });
  src.onerror = function() {
    _sseOk = false;
    updateSSEBadge(false);
  };
  src.onopen = function() {
    _sseOk = true;
    updateSSEBadge(true);
  };
}

function updateSSEBadge(ok) {
  document.getElementById('sse-badge').replaceChildren(
    SLinkDOM.el('span', {className: 'sse-dot ' + (ok ? 'sse-ok' : 'sse-off')}), ok ? ' live' : ' disconnected');
}

function scheduleRefresh() {
  if (_refreshQueued) return;
  _refreshQueued = true;
  requestAnimationFrame(function() {
    _refreshQueued = false;
    refreshAll();
  });
}

function refreshAll() {
  updateLiveBar();
  // Skip DOM-rebuilding refreshes if user is interacting with a form element
  var ae = document.activeElement;
  var interacting = ae && (ae.tagName === 'SELECT' || ae.tagName === 'INPUT');
  if (!interacting) {
    updateDataLists();
    renderLinksTable();
    mlRefresh();
    loadBackups();
  }
  if (document.getElementById('raw-auto').checked) { loadRaw(); loadLiveState(); loadMemorial(); }
}

function updateLiveBar() {
  var d = _lastStatus;
  if (!d || !d.players) return;
  ['a','b'].forEach(function(pid) {
    var p = d.players[pid];
    var pill = document.getElementById('pill-' + pid);
    var on = p && p.connected;
    pill.className = 'player-pill ' + (on ? 'on' : 'off');
    var name = (p && p.trainer_name) || pid.toUpperCase();
    var area = (p && p.current_area_display) || '';
    pill.textContent = name + ': ' + (on ? (area || 'connected') : 'offline');
  });
  var alive = 0, dead = 0;
  (d.links || []).forEach(function(l) { if (l.status === 'alive') alive++; else dead++; });
  document.getElementById('lb-links').textContent = alive + ' alive / ' + dead + ' dead';
  var areaCount = Object.keys(d.area_states || {}).length;
  document.getElementById('lb-areas').textContent = areaCount;
  var qa = d.players.a.queued || 0, qb = d.players.b.queued || 0;
  var qEl = document.getElementById('lb-queued');
  qEl.textContent = qa + ' / ' + qb;
  qEl.style.color = (qa + qb > 0) ? '#fbbf24' : '';
  // Last event
  var events = [];
  ['a','b'].forEach(function(pid) {
    var p = d.players[pid];
    if (p && p.last_event && p.last_event !== '\u2014') {
      events.push(pid.toUpperCase() + ': ' + p.last_event);
    }
  });
  document.getElementById('lb-last-event').textContent = events.join('  \u2502  ') || '\u2014';
}

// ── Datalist autofill ───────────────────────────────────────────────────
var _allAreas = null;  // {aid: display_name} — loaded once from manual_link_data

function updateDataLists() {
  var d = _lastStatus;
  if (!d) return;
  var keys = new Map();
  ['a', 'b'].forEach(function (pid) {
    var player = d.players && d.players[pid];
    Object.entries((player && player.party_details) || {}).forEach(function (entry) {
      var key = entry[0], mon = entry[1];
      keys.set(key, pid.toUpperCase() + ' party: ' + key.substring(0, 8) + ' ' + (mon.nickname || '') + (mon.species_name ? ' (' + mon.species_name + ')' : ''));
    });
  });
  (d.links || []).forEach(function (link) {
    ['a', 'b'].forEach(function (pid) {
      var key = link[pid + '_key'];
      if (key && !keys.has(key)) keys.set(key, pid.toUpperCase() + ' link: ' + key.substring(0, 8) + ' ' + (link[pid + '_nickname'] || '') + ' (' + (link[pid + '_species_name'] || '') + ') [' + link.status + ']');
    });
  });
  var pending = d.pending_captures || {};
  Object.entries(pending).forEach(function (entry) {
    Object.entries(entry[1]).forEach(function (capture) {
      var pid = capture[0], mon = capture[1];
      if (mon.key && !keys.has(mon.key)) keys.set(mon.key, pid.toUpperCase() + ' pending@' + entry[0] + ': ' + mon.key.substring(0, 8) + ' ' + (mon.nickname || ''));
    });
  });
  document.getElementById('dl-keys').replaceChildren(...Array.from(keys, function (entry) { return _debugOption(entry[0], entry[1]); }));
  if (!_allAreas) return;
  var states = d.area_states || {}, seen = new Set(), options = [];
  Object.keys(pending).sort().forEach(function (area) {
    seen.add(area);
    options.push(_debugOption(area, '⚠ ' + (_allAreas[area] || area) + ' [PENDING ' + Object.keys(pending[area]).map(function (pid) { return pid.toUpperCase(); }).join('+') + ']'));
  });
  var active = [], rest = [];
  Object.keys(_allAreas).sort().forEach(function (area) {
    if (!seen.has(area)) (states[area] && states[area] !== 'unseen' ? active : rest).push(area);
  });
  active.concat(rest).forEach(function (area) {
    options.push(_debugOption(area, (_allAreas[area] || area) + (active.includes(area) ? ' [' + states[area] + ']' : '')));
  });
  document.getElementById('dl-areas').replaceChildren(...options);
}

async function loadAllAreas() {
  try {
    var r = await SLinkRun.fetch('/api/debug/manual_link_data');
    var ml = await r.json();
    _allAreas = {};
    var areas = ml.areas || {};
    (ml.area_ids || []).forEach(function(aid) {
      _allAreas[aid] = (areas[aid] && areas[aid].d) || aid;
    });
    updateDataLists();
  } catch(e) {}
}

// ── Inject Event ────────────────────────────────────────────────────────
async function injectEvent() {
  var ev = {event: document.getElementById('ev-type').value,
            player: document.getElementById('ev-player').value};
  var key = document.getElementById('ev-key').value.trim();
  var area = document.getElementById('ev-area').value.trim();
  if (key) ev.key = key;
  if (area) ev.area_id = area;
  var extra = document.getElementById('ev-extra').value.trim();
  if (extra) { try { Object.assign(ev, JSON.parse(extra)); } catch(e) { showResult(document.getElementById('ev-result'), false, 'Invalid JSON: '+e); return; } }
  var j = await api('POST', '/api/debug/inject_event', ev);
  showResult(document.getElementById('ev-result'), j.ok, j);
  flashPanel(document.getElementById('ev-result'));
}

// ── Queue Command ───────────────────────────────────────────────────────
async function queueCmd() {
  var cmd = {cmd: document.getElementById('cmd-type').value,
             player: document.getElementById('cmd-player').value};
  var key = document.getElementById('cmd-key').value.trim();
  if (key) cmd.key = key;
  var extra = document.getElementById('cmd-extra').value.trim();
  if (extra) { try { Object.assign(cmd, JSON.parse(extra)); } catch(e) { showResult(document.getElementById('cmd-result'), false, 'Invalid JSON: '+e); return; } }
  var j = await api('POST', '/api/debug/queue_command', cmd);
  showResult(document.getElementById('cmd-result'), j.ok, j);
  flashPanel(document.getElementById('cmd-result'));
}

// ── Toggles ─────────────────────────────────────────────────────────────
async function toggleBalls(val) {
  var p = document.getElementById('tog-player').value;
  var j = await api('POST', '/api/debug/set_pokeballs', {player: p, value: val});
  showResult(document.getElementById('tog-result'), j.ok, j);
}
async function setAreaState() {
  var j = await api('POST', '/api/debug/set_area_state', {
    area_id: document.getElementById('area-id').value.trim(),
    state: document.getElementById('area-state').value
  });
  showResult(document.getElementById('area-result'), j.ok, j);
}

// ── Danger Zone ─────────────────────────────────────────────────────────
async function resetRun() {
  if (!confirm('Reset ALL run state? This cannot be undone.')) return;
  var j = await api('POST', '/api/reset');
  showResult(document.getElementById('danger-result'), j.ok, j);
}
async function clearPending() {
  if (!confirm('Clear ALL pending captures?')) return;
  var j = await api('POST', '/api/debug/clear_pending', {});
  showResult(document.getElementById('danger-result'), j.ok, j);
}
async function clearPendingArea() {
  var area = document.getElementById('clear-area').value.trim();
  if (!area) { alert('Enter an area ID'); return; }
  var j = await api('POST', '/api/debug/clear_pending', {area_id: area});
  showResult(document.getElementById('danger-result'), j.ok, j);
}

// ── Backups ─────────────────────────────────────────────────────────────
async function loadBackups() {
  var response = await SLinkRun.fetch('/api/debug/backups'), data = await response.json();
  var target = document.getElementById('backup-list');
  if (!data.backups || !data.backups.length) {
    target.textContent = 'No backups yet — created every 5 min when both players connected.';
    return;
  }
  window._backupData = {};
  target.replaceChildren(SLinkDOM.table(['Slot', 'Time', 'State', 'Size'], data.backups.map(function (backup) {
    window._backupData[backup.slot] = backup;
    var summary = backup.summary;
    var detail = summary ? summary.links_alive + '♥ ' + summary.links_dead + '☠ ' + summary.areas_pending + ' pending ' + summary.areas_dead_zone + ' dz' : '?';
    return [SLinkDOM.el('button', {className: 'slot-link', type: 'button', onclick: function () { doRollback(backup.slot); }}, '#' + backup.slot), backup.modified, detail, (backup.size / 1024).toFixed(1) + 'K'];
  }), 'backup-table'));
}
async function doRollback(slot) {
  if (slot === undefined) return;
  var info = window._backupData && window._backupData[slot];
  var msg = 'Roll back to backup slot #' + slot + '?';
  if (info) {
    msg += '\n\nBackup from: ' + info.modified;
    if (info.summary) {
      var s = info.summary;
      msg += '\n  ' + s.links_alive + ' alive links, ' + s.links_dead + ' dead';
      msg += '\n  ' + s.areas_pending + ' pending areas, ' + s.areas_dead_zone + ' dead zones';
    }
  }
  msg += '\n\nCurrent state will be saved as pre_rollback.';
  if (!confirm(msg)) return;
  var j = await api('POST', '/api/debug/rollback', {slot: slot});
  showResult(document.getElementById('rollback-result'), j.ok, j.message || j.error);
  if (j.ok) loadBackups();
}

// ── Raw State ───────────────────────────────────────────────────────────
async function loadRaw() {
  try {
    var r = await SLinkRun.fetch('/api/debug/raw_state');
    var j = await r.json();
    document.getElementById('raw-json').textContent = JSON.stringify(j, null, 2);
  } catch(e) {}
}

// ── Live State Info ─────────────────────────────────────────────────────
async function loadLiveState() {
  var target = document.getElementById('live-state-content');
  try {
    var response = await SLinkRun.fetch('/api/debug/raw_state'), data = await response.json(), live = data._live || {};
    var rules = data.rules || {}, identity = data.player_identity || {}, errors = live.identity_errors || {};
    var rows = [], rulesText = ['species', 'gender', 'type'].filter(function (rule) { return rules[rule + '_lock']; });
    rows.push(_debugSection('Lock Rules:', rulesText.length ? rulesText.map(function (name) { return name[0].toUpperCase() + name.slice(1); }).join(' · ') : 'none'));
    rows.push(_debugSection('Identity Lock:', ['a', 'b'].map(function (pid) {
      var value = identity[pid];
      return SLinkDOM.el('div', {}, pid.toUpperCase() + ': ' + (value ? (value.trainer_name || '?') + ' (OT: ' + (value.ot_id || '?') + ')' : 'not locked'));
    })));
    if (errors.a || errors.b) rows.push(_debugSection('Identity Errors:', ['a', 'b'].filter(function (pid) { return errors[pid]; }).map(function (pid) {
      return SLinkDOM.el('div', {style: {color: 'var(--red)'}}, pid.toUpperCase() + ': ' + errors[pid]);
    })));
    function keyRows(title, groups, empty) {
      return _debugSection(title, ['a', 'b'].map(function (pid) {
        var keys = groups[pid] || [];
        return SLinkDOM.el('div', {}, pid.toUpperCase() + ' (' + keys.length + '): ' + (keys.length ? keys.map(function (key) { return String(key).substring(0, 8); }).join(', ') : empty));
      }));
    }
    rows.push(keyRows('Party Keys:', live.party_keys || {}, 'empty'));
    rows.push(keyRows('Bonus Keys (Shinies):', live.bonus_keys || data.bonus_keys || {}, 'none'));
    var pending = live.pending_bonus || data.pending_bonus || {};
    if ((pending.a || []).length || (pending.b || []).length) rows.push(keyRows('Pending Bonus (Awaiting Partner):', pending, 'none'));
    var balls = data.pokeballs_obtained || {}, size = live.party_size || {};
    rows.push(_debugSection('Pokéballs Obtained:', 'A: ' + (balls.a ? '✓' : '✗') + ' B: ' + (balls.b ? '✓' : '✗')));
    rows.push(_debugSection('Party Size (physical):', 'A: ' + (size.a === undefined ? '?' : size.a) + ' B: ' + (size.b === undefined ? '?' : size.b)));
    rows.push(_debugSection('Mon Stats Cached:', Object.keys(data.mon_stats || {}).length + ' entries'));
    target.replaceChildren(...rows);
  } catch (error) { target.textContent = 'Error loading state'; }
}

// ── Memorial Box Monitor ────────────────────────────────────────────────
async function loadMemorial() {
  var target = document.getElementById('memorial-content');
  try {
    var response = await SLinkRun.fetch('/api/debug/raw_state'), data = await response.json(), memorial = data._memorial || {};
    var index = memorial.memorial_box_index, contents = memorial.memorial_box_contents || {}, pending = memorial.pending_memorials || {};
    var rows = [_debugSection('Memorial Box:', index >= 0 ? 'Box ' + (index + 1) + ' (index ' + index + ')' : 'No dedicated memorial box (Gen 1/2)')];
    var pendingCount = (pending.a || []).length + (pending.b || []).length;
    if (pendingCount) rows.push(_debugSection('Pending Memorial (' + pendingCount + '):', ['a', 'b'].map(function (pid) {
      return SLinkDOM.el('div', {}, pid.toUpperCase() + ': ' + (pending[pid] || []).map(function (mon) { return mon.species_name + ' [' + String(mon.key).substring(0, 8) + ']'; }).join(', '));
    })));
    if (index >= 0) {
      var total = (contents.a || []).length + (contents.b || []).length;
      rows.push(_debugSection('Box ' + (index + 1) + ' Contents', total ? '' : '— empty or not scanned by emulator'));
      ['a', 'b'].forEach(function (pid) {
        var entries = contents[pid] || [];
        if (!entries.length) return;
        rows.push(_debugSection(pid.toUpperCase(), SLinkDOM.table(['Slot', 'Species', 'Nickname', 'Key', 'Status'], entries.map(function (mon) {
          var labels = {dead: '☠ dead', pending_memorial: '⏳ pending', quarantined: '⚠ QUARANTINED', unknown: '? unknown'};
          var colors = {dead: 'var(--red)', pending_memorial: 'var(--yellow)', quarantined: 'var(--orange)', unknown: 'var(--yellow)'};
          return [mon.slot + 1, mon.species_name || '#' + mon.species_id, mon.nickname || '—', String(mon.key).substring(0, 8),
            SLinkDOM.el('span', {style: {color: colors[mon.status] || 'var(--c-dim)', fontWeight: '600'}}, labels[mon.status] || mon.status)];
        }), 'ml-table')));
      });
    }
    var log = memorial.memorial_log || [];
    if (log.length) rows.push(SLinkDOM.el('details', {}, SLinkDOM.el('summary', {}, '🪦 Memorial Log (' + log.length + ' pairs)'),
      SLinkDOM.table(['Area', 'Player A', 'Player B', 'Cause'], log.map(function (entry) {
        var a = entry.a || {}, b = entry.b || {};
        return [entry.area_id || '?', a.nickname || a.species || '?', b.nickname || b.species || '?', entry.cause || '?'];
      }), 'ml-table')));
    else rows.push(SLinkDOM.el('div', {}, 'No memorial log entries yet.'));
    target.replaceChildren(...rows);
  } catch (error) { target.textContent = 'Error loading memorial data'; }
}

// ── Manual Link ─────────────────────────────────────────────────────────
var _mlData = {a_options:[], b_options:[], areas:{}, area_ids:[], name_a:"Player A", name_b:"Player B"};
var _mlForceLink = false;

async function mlRefresh() {
  try {
    var r = await SLinkRun.fetch('/api/debug/manual_link_data');
    _mlData = await r.json();
  } catch(e) { _mlData = {a_options:[], b_options:[], areas:{}, area_ids:[], name_a:"Player A", name_b:"Player B"}; }
  document.getElementById('ml-label-a').textContent = _mlData.name_a;
  document.getElementById('ml-label-b').textContent = _mlData.name_b;
  _mlPopulateMons('a');
  _mlPopulateMons('b');
  mlFilterAreas();
}

function _mlPopulateMons(pid) {
  var select = document.getElementById('ml-' + pid), current = select.value;
  var options = (pid === 'a' ? _mlData.a_options : _mlData.b_options) || [];
  select.replaceChildren(_debugOption('', '-- select --'), ...options.map(function (mon) {
    var option = _debugOption(mon.key, mon.label + (mon.linked ? ' ✔' : ''));
    option.setAttribute('data-area', mon.pending_area || '');
    option.disabled = Boolean(mon.linked);
    return option;
  }));
  if (current) select.value = current;
}

function mlFilterAreas() {
  var select = document.getElementById('ml-area'), current = select.value;
  var filter = (document.getElementById('ml-area-filter').value || '').toLowerCase();
  var areas = _mlData.areas || {}, groups = {pending: [], unseen: [], other: []};
  (_mlData.area_ids || []).forEach(function (area) {
    var info = areas[area] || {d: area, s: 'unseen', p: ''};
    if (filter && info.d.toLowerCase().indexOf(filter) === -1 && area.indexOf(filter) === -1) return;
    (info.p ? groups.pending : ['unseen', 'pending_a', 'pending_b', 'pending_both'].includes(info.s) ? groups.unseen : groups.other).push(area);
  });
  var options = [_debugOption('', '-- select area --')];
  [['Pending Captures', groups.pending], ['Available', groups.unseen], ['Resolved', groups.other]].forEach(function (group) {
    if (!group[1].length) return;
    var heading = _debugOption('', '─── ' + group[0] + ' ───');
    heading.disabled = true;
    options.push(heading);
    group[1].forEach(function (area) {
      var info = areas[area] || {d: area, s: 'unseen', p: ''};
      var suffix = info.p ? ' [pending: ' + info.p.toUpperCase() + ']' : info.s === 'linked' ? ' [linked]' : info.s === 'dead_zone' ? ' [dead]' : '';
      options.push(_debugOption(area, info.d + suffix));
    });
  });
  select.replaceChildren(...options);
  if (current) select.value = current;
}

function mlMonChanged(player) {
  var areas = _mlData.areas || {};
  var aOpt = document.getElementById('ml-a').selectedOptions[0];
  var bOpt = document.getElementById('ml-b').selectedOptions[0];
  var warnEl = document.getElementById('ml-warn');
  warnEl.textContent = '';
  var aArea = aOpt ? aOpt.getAttribute('data-area') || '' : '';
  var bArea = bOpt ? bOpt.getAttribute('data-area') || '' : '';
  var targetArea = (player === 'a') ? (aArea || bArea) : (bArea || aArea);
  if (targetArea) {
    var sel = document.getElementById('ml-area');
    for (var i = 0; i < sel.options.length; i++) {
      if (sel.options[i].value === targetArea) { sel.selectedIndex = i; break; }
    }
  }
  if (aArea && bArea && aArea !== bArea) {
    var aDisp = (areas[aArea]||{}).d || aArea;
    var bDisp = (areas[bArea]||{}).d || bArea;
    warnEl.textContent = '\u26a0 A pending on ' + aDisp + ', B pending on ' + bDisp;
  }
}

async function doManualLink() {
  var aKey = document.getElementById('ml-a').value;
  var bKey = document.getElementById('ml-b').value;
  var area = document.getElementById('ml-area').value;
  var res = document.getElementById('ml-result');
  var override = document.getElementById('ml-override').checked;
  if (!aKey || !bKey) { showResult(res, false, 'Select a mon from each player.'); return; }
  if (!area) { showResult(res, false, 'Select an area.'); return; }
  var j = await api('POST', '/api/inject_link', {a_key: aKey, b_key: bKey, area_id: area, force: _mlForceLink, override: override});
  if (j.ok) {
    showResult(res, true, j.message || 'Linked!');
    _mlForceLink = false;
    document.getElementById('ml-warn').textContent = '';
  } else if (j.requires_force) {
    document.getElementById('ml-warn').textContent = '\u26a0 ' + j.error;
    res.style.display = 'block';
    res.className = 'result err';
    res.replaceChildren(SLinkDOM.el('button', {className: 'btn btn-orange', onclick: function () { _mlForceLink = true; doManualLink(); }}, 'Link anyway'));
  } else {
    showResult(res, false, j.error || 'Unknown error');
  }
}

// ── Links table + unlink ────────────────────────────────────────────────
function renderLinksTable() {
  var target = document.getElementById('ml-links-table'), data = _lastStatus;
  if (!data || !data.links || !data.links.length) { target.textContent = 'No links yet.'; return; }
  target.replaceChildren(SLinkDOM.table(['Area', 'A', 'B', 'Status', ''], data.links.map(function (link, index) {
    var statusClass = link.status === 'alive' ? 'st-alive' : ['dead', 'memorial'].includes(link.status) ? 'st-dead' : 'st-memorial';
    var names = ['a', 'b'].map(function (pid) {
      return link[pid + '_nickname'] ? link[pid + '_nickname'] + ' (' + (link[pid + '_species_name'] || '') + ')' : link[pid + '_key'] ? link[pid + '_key'].substring(0, 8) : '—';
    });
    var buttons = SLinkDOM.el('span', {});
    if (['dead', 'memorial'].includes(link.status)) buttons.append(SLinkDOM.el('button', {className: 'btn btn-revive', 'data-action': 'revive', 'data-area-id': link.area_id, 'data-link-idx': index, title: 'Revive this pair'}, '♥'), ' ');
    buttons.append(SLinkDOM.el('button', {className: 'btn btn-red btn-unlink', 'data-action': 'unlink', 'data-area-id': link.area_id, 'data-link-idx': index}, '✖'));
    return [link.area_display || link.area_id, names[0], names[1], SLinkDOM.el('span', {className: statusClass}, link.status), buttons];
  }), 'ml-table'));
}

async function doUnlink(areaId, idx) {
  var d = _lastStatus;
  var lnk = d && d.links && d.links[idx];
  var desc = lnk ? (lnk.a_nickname||'?') + ' <-> ' + (lnk.b_nickname||'?') + ' on ' + (lnk.area_display || areaId) : 'link #' + idx;
  if (!confirm('Unlink ' + desc + '?\n\nThis removes the link entry. Both mons become available for relinking.')) return;
  var j = await api('POST', '/api/debug/unlink', {area_id: areaId, index: idx});
  showResult(document.getElementById('ml-result'), j.ok, j.message || j.error || JSON.stringify(j));
}

async function doRevive(areaId, idx) {
  var d = _lastStatus;
  var lnk = d && d.links && d.links[idx];
  var desc = lnk ? (lnk.a_nickname||'?') + ' <-> ' + (lnk.b_nickname||'?') + ' on ' + (lnk.area_display || areaId) : 'link #' + idx;
  if (!confirm('Revive ' + desc + '?\n\nThis sets the link back to alive. You will need to manually restore the mons from the memorial box in-game.')) return;
  var j = await api('POST', '/api/debug/revive', {area_id: areaId, index: idx});
  showResult(document.getElementById('ml-result'), j.ok, j.message || j.error || JSON.stringify(j));
}

// ── Init ────────────────────────────────────────────────────────────────
// Delegated click handler — survives every innerHTML rebuild because it's
// bound to document.body, which renderLinksTable / mlRefresh / loadBackups
// never replace. Buttons inside refresh-rebuilt panels carry data-action +
// the parameters they used to bake into inline onclick="". See
// renderLinksTable above for the matching markup.
document.body.addEventListener('click', function(ev) {
  var btn = ev.target && ev.target.closest && ev.target.closest('[data-action]');
  if (!btn) return;
  var act  = btn.getAttribute('data-action');
  var area = btn.getAttribute('data-area-id');
  var idx  = parseInt(btn.getAttribute('data-link-idx'), 10);
  if      (act === 'unlink') doUnlink(area, idx);
  else if (act === 'revive') doRevive(area, idx);
});

var _embeddedRefreshBusy = false;
window.SLinkDebug = {
  refresh: async function(status) {
    if (_embeddedRefreshBusy || !status) return;
    _embeddedRefreshBusy = true;
    try {
      _lastStatus = status;
      updateLiveBar();
      document.getElementById('sse-badge').textContent = 'Board refresh';
      var focused = document.activeElement;
      var interacting = focused && ['SELECT', 'INPUT', 'TEXTAREA'].includes(focused.tagName);
      var jobs = [];
      if (!interacting) {
        updateDataLists();
        renderLinksTable();
        jobs.push(mlRefresh(), loadBackups());
        if (!_allAreas) jobs.push(loadAllAreas());
      }
      if (document.getElementById('raw-auto').checked) jobs.push(loadRaw(), loadLiveState(), loadMemorial());
      await Promise.all(jobs);
    } finally {
      _embeddedRefreshBusy = false;
      if (document.dispatchEvent) document.dispatchEvent(new CustomEvent('slink:debug-rendered'));
    }
  }
};

if (!window.SLinkDebugEmbedded) {
initSSE();
// Fetch initial status to populate datalists immediately
(async function() {
  try {
    var r = await SLinkRun.fetch('/api/status');
    _lastStatus = await r.json();
    updateLiveBar();
    updateDataLists();
  } catch(e) {}
})();
loadAllAreas();
loadRaw();
loadLiveState();
loadMemorial();
mlRefresh();
loadBackups();
// Fallback poll in case SSE disconnects
setInterval(function() { if (!_sseOk) refreshAll(); }, 10000);
}
