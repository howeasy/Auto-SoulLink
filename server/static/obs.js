var triggers = [];
    var triggersLoaded = false;
    var _dragSrcIdx = null;
    // Area picker data, loaded once from /api/obs/areas.
    // _areaNameById maps both literal area_ids and "group:<id>" to display labels.
    var _areaGroups = [];   // [{id,label,count}]
    var _areaList   = [];   // [{id,name,group}]
    var _areaNameById = {}; // {area_id_or_group_key: friendly_label}

    function esc(s) {
      return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }
    function msg(text, isErr) {
      var el = document.getElementById('msg');
      el.textContent = text;
      el.className = isErr ? 'err' : '';
    }

    function areaFilterLabel(v) {
      if (!v) return '<span style="color:var(--c-dim)">—</span>';
      if (v.indexOf('group:') === 0) {
        var label = _areaNameById[v] || v.slice(6);
        return '<span style="background:#1a2a3a;color:#6af;border:1px solid #2a4a6a;border-radius:3px;padding:1px 6px;font-size:.78em">☰ '
          + esc(label) + '</span>';
      }
      var name = _areaNameById[v];
      if (name) return '<code title="' + esc(v) + '">' + esc(name) + '</code>';
      return '<code>' + esc(v) + '</code>';
    }

    function renderTriggers() {
      var tbody = document.getElementById('triggers-body');
      if (!triggers.length) {
        tbody.innerHTML = '<tr><td colspan="8" style="color:var(--c-dim);text-align:center;padding:1em">No triggers — add one below</td></tr>';
        return;
      }
      tbody.innerHTML = triggers.map(function(t, i) {
        var af = areaFilterLabel(t.area_id_filter);
        return '<tr draggable="true" data-idx="' + i + '">' +
          '<td><span class="drag-handle" title="Drag to reorder">&#8942;&#8942;</span></td>' +
          '<td><span class="priority-badge">#' + (i+1) + '</span></td>' +
          '<td><code>' + esc(t.event) + '</code></td>' +
          '<td>' + esc(t.player_filter || 'any') + '</td>' +
          '<td>' + esc(t.target || 'own') + '</td>' +
          '<td>' + esc(t.scene) + '</td>' +
          '<td>' + af + '</td>' +
          '<td><button class="btn btn-r" style="padding:2px 8px;font-size:.75em" onclick="delTrigger(' + i + ')">&#10005;</button></td>' +
          '</tr>';
      }).join('');
      // Attach drag events to rows
      Array.from(tbody.querySelectorAll('tr[draggable]')).forEach(function(row) {
        row.addEventListener('dragstart', function(e) {
          _dragSrcIdx = parseInt(row.dataset.idx);
          e.dataTransfer.effectAllowed = 'move';
          e.dataTransfer.setData('text/plain', String(_dragSrcIdx));
        });
        row.addEventListener('dragover', function(e) {
          e.preventDefault();
          e.dataTransfer.dropEffect = 'move';
          tbody.querySelectorAll('tr').forEach(function(r){ r.classList.remove('drag-over'); });
          row.classList.add('drag-over');
        });
        row.addEventListener('dragleave', function() {
          row.classList.remove('drag-over');
        });
        row.addEventListener('drop', function(e) {
          e.preventDefault();
          row.classList.remove('drag-over');
          var destIdx = parseInt(row.dataset.idx);
          if (_dragSrcIdx === null || _dragSrcIdx === destIdx) return;
          var moved = triggers.splice(_dragSrcIdx, 1)[0];
          triggers.splice(destIdx, 0, moved);
          _dragSrcIdx = null;
          renderTriggers();
          autoSaveTriggers();
        });
      });
    }

    function autoSaveTriggers() {
      SLinkRun.fetch('/api/obs/triggers', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({triggers:triggers})})
        .then(function(r){return r.json();}).then(function(d) {
          msg(d.ok ? '\u2714 Triggers saved' : 'Save error: '+(d.error||'unknown'), !d.ok);
        }).catch(function(e){ msg('Save failed: '+e, true); });
    }

    function addTrigger() {
      var scene = document.getElementById('new-scene').value.trim();
      if (!scene) { msg('Scene name is required', true); return; }
      triggers.push({
        id: 't' + Date.now(),
        event: document.getElementById('new-evt').value,
        player_filter: document.getElementById('new-pf').value,
        target: document.getElementById('new-tgt').value,
        scene: scene,
        area_id_filter: document.getElementById('new-area').value
      });
      document.getElementById('new-scene').value = '';
      document.getElementById('new-area').value = '';
      renderTriggers();
      autoSaveTriggers();
    }

    function delTrigger(i) {
      triggers.splice(i, 1);
      renderTriggers();
      autoSaveTriggers();
    }

    function loadStatus(signal) {
      return SLinkRun.fetch('/api/obs/status',{signal:signal}).then(function(r){return r.json();}).then(function(d) {
        ['a','b'].forEach(function(p) {
          var badge = document.getElementById('status-' + p);
          var cs = (d.connections && d.connections[p]) ? d.connections[p].status : 'disconnected';
          badge.textContent = cs;
          badge.className = 'sb ' + (cs==='connected'?'sb-ok':cs==='connecting'?'sb-mid':'sb-off');
        });
        ['a','b'].forEach(function(p) {
          var c = d.connections && d.connections[p];
          if (c) {
            var he = document.getElementById('host-' + p);
            var pe = document.getElementById('port-' + p);
            if (document.activeElement !== he) he.value = c.host || '';
            if (document.activeElement !== pe) pe.value = c.port || 4455;
          }
        });
        var en = document.getElementById('enabled');
        if (document.activeElement !== en) en.checked = !!d.enabled;
        if (!triggersLoaded && d.triggers) {
          triggers = d.triggers;
          triggersLoaded = true;
          renderTriggers();
        }
        return Promise.allSettled([loadScenes('a', signal), loadScenes('b', signal)]);
      }).catch(function(){});
    }

    var _scenesCache = {a: [], b: []};
    function loadScenes(player, signal) {
      return SLinkRun.fetch('/api/obs/scenes/' + player, {signal:signal}).then(function(r){return r.json();}).then(function(d) {
        _scenesCache[player] = d.scenes || [];
        _updateSceneLists();
      }).catch(function(){});
    }
    function _updateSceneLists() {
      var setA = new Set(_scenesCache.a);
      var setB = new Set(_scenesCache.b);
      // Per-player datalists (raw scene names)
      ['a','b'].forEach(function(p) {
        var dl = document.getElementById('scene-list-' + p);
        if (!dl) return;
        dl.innerHTML = '';
        _scenesCache[p].forEach(function(s) {
          var o = document.createElement('option'); o.value = s; dl.appendChild(o);
        });
      });
      // Combined datalist: common scenes unlabeled, unique scenes prefixed with [A]/[B]
      var dlBoth = document.getElementById('scene-list-both');
      if (!dlBoth) return;
      dlBoth.innerHTML = '';
      var added = new Set();
      _scenesCache.a.forEach(function(s) {
        var o = document.createElement('option');
        o.value = setB.has(s) ? s : '[A] ' + s;
        dlBoth.appendChild(o); added.add(s);
      });
      _scenesCache.b.forEach(function(s) {
        if (added.has(s)) return;
        var o = document.createElement('option');
        o.value = '[B] ' + s;
        dlBoth.appendChild(o);
      });
    }
    // Strip [A]/[B] prefix inserted by combined datalist when user selects an entry
    document.getElementById('new-scene').addEventListener('change', function() {
      var m = this.value.match(/^\[(?:A|B)\] (.+)/);
      if (m) this.value = m[1];
    });

    function saveConfig() {
      var cfg = {
        enabled: document.getElementById('enabled').checked,
        connections: {
          a: { host: document.getElementById('host-a').value.trim(),
               port: parseInt(document.getElementById('port-a').value)||4455,
               password: document.getElementById('pw-a').value },
          b: { host: document.getElementById('host-b').value.trim(),
               port: parseInt(document.getElementById('port-b').value)||4455,
               password: document.getElementById('pw-b').value }
        },
        triggers: triggers
      };
      SLinkRun.fetch('/api/obs/config', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)})
        .then(function(r){return r.json();}).then(function(d) {
          if (d.ok) {
            msg('Config saved!', false);
            document.getElementById('pw-a').value = '';
            document.getElementById('pw-b').value = '';
          } else { msg('Error: ' + (d.error||'unknown'), true); }
        }).catch(function(e){ msg('Request failed: '+e, true); });
    }

    function connect(player) {
      var host = document.getElementById('host-'+player).value.trim();
      var port = parseInt(document.getElementById('port-'+player).value)||4455;
      var pw   = document.getElementById('pw-'+player).value;
      var body = {player:player, host:host, port:port};
      if (pw) body.password = pw;
      SLinkRun.fetch('/api/obs/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
        .then(function(r){return r.json();}).then(function(d){
          if (d.ok && pw) document.getElementById('pw-'+player).value='';
          msg(d.ok ? ('Connecting player '+player.toUpperCase()+'...') : ('Error: '+d.error), !d.ok);
          setTimeout(loadStatus, 1500);
        });
    }

    function disconnect(player) {
      SLinkRun.fetch('/api/obs/disconnect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({player:player})})
        .then(function(r){return r.json();}).then(function(d){
          msg(d.ok ? ('Disconnected player '+player.toUpperCase()) : ('Error: '+d.error), !d.ok);
          setTimeout(loadStatus, 500);
        });
    }

    function testScene(player) {
      var scene = prompt('Scene name to switch to for Player ' + player.toUpperCase() + ':');
      if (!scene) return;
      SLinkRun.fetch('/api/obs/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({player:player,scene:scene})})
        .then(function(r){return r.json();}).then(function(d){
          msg(d.ok ? ('\u2714 Scene changed to "'+scene+'"') : ('Error: '+d.error), !d.ok);
        });
    }

    // Populate the area-filter <select> with grouped entries from the active game.
    // The select has:
    //   - "(any area)"
    //   - <optgroup "Area Groups">   group:<id> options (e.g. group:route)
    //   - <optgroup "<Group label>"> one per non-empty group, with the areas inside
    // If an existing trigger's area_id_filter isn't in the loaded list (legacy
    // free-text value), we add a "Custom" optgroup so the dropdown can still
    // round-trip it on re-render.
    function loadAreas() {
      SLinkRun.fetch('/api/obs/areas').then(function(r){return r.json();}).then(function(d){
        _areaGroups = d.groups || [];
        _areaList   = d.areas  || [];
        _areaNameById = {};
        _areaGroups.forEach(function(g){
          _areaNameById['group:' + g.id] = 'All ' + g.label + ' (' + g.count + ')';
        });
        _areaList.forEach(function(a){ _areaNameById[a.id] = a.name; });
        rebuildAreaSelect();
        // Re-render triggers so existing area filters get pretty labels.
        if (triggersLoaded) renderTriggers();
      }).catch(function(){});
    }

    function rebuildAreaSelect() {
      var sel = document.getElementById('new-area');
      if (!sel) return;
      var prev = sel.value;
      sel.innerHTML = '';
      var defaultOpt = document.createElement('option');
      defaultOpt.value = ''; defaultOpt.textContent = '(any area)';
      sel.appendChild(defaultOpt);
      // Groups optgroup
      if (_areaGroups.length) {
        var og = document.createElement('optgroup');
        og.label = 'Area Groups';
        _areaGroups.forEach(function(g){
          var o = document.createElement('option');
          o.value = 'group:' + g.id;
          o.textContent = 'All ' + g.label + ' (' + g.count + ')';
          og.appendChild(o);
        });
        sel.appendChild(og);
      }
      // One optgroup per group, listing specific areas
      _areaGroups.forEach(function(g){
        var items = _areaList.filter(function(a){ return a.group === g.id; });
        if (!items.length) return;
        var og = document.createElement('optgroup');
        og.label = g.label;
        items.forEach(function(a){
          var o = document.createElement('option');
          o.value = a.id; o.textContent = a.name;
          og.appendChild(o);
        });
        sel.appendChild(og);
      });
      // Preserve any prior selection (incl. legacy free-text values)
      if (prev) {
        var have = Array.prototype.some.call(sel.options, function(o){ return o.value === prev; });
        if (!have) {
          var og2 = document.createElement('optgroup');
          og2.label = 'Custom';
          var o = document.createElement('option');
          o.value = prev; o.textContent = prev;
          og2.appendChild(o);
          sel.appendChild(og2);
        }
        sel.value = prev;
      }
    }

    loadAreas();
    if (window.SLinkPoll) SLinkPoll.subscribe('obs', function (signal) { return loadStatus(signal); });
    else { loadStatus(); setInterval(loadStatus, 5000); }
