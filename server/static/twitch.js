var _cfgLoaded = false;
    function showToast(msg, ok) {
      var t = document.createElement('div');
      t.textContent = msg;
      t.style.cssText = 'position:fixed;bottom:1.5em;right:1.5em;background:'+(ok?'#1a3a1a':'#3a1a1a')+';color:'+(ok?'#3de85a':'#f03838')+';border-radius:5px;padding:8px 16px;font-size:.85em;z-index:999';
      document.body.appendChild(t);
      setTimeout(function(){if(t.parentNode)t.parentNode.removeChild(t);},2500);
    }
    function post(url, body) {
      return SLinkRun.fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})}).then(function(r){return r.json();});
    }
    var _cfgInputIds = ['cfg-channel','cfg-nick','cfg-prefix','cfg-cooldown','cfg-client-id'];
    function _anyConfigFocused() {
      var a = document.activeElement;
      return a && _cfgInputIds.indexOf(a.id) !== -1;
    }
    function loadStatus(forceConfig) {
      SLinkRun.fetch('/api/bot/status').then(function(r){return r.json();}).then(function(j){
        var badge = document.getElementById('status-badge');
        var chan  = document.getElementById('status-channel');
        var tBadge = document.getElementById('token-badge');
        var cidBadge = document.getElementById('clientid-badge');
        var errBox = document.getElementById('status-error');
        if (!badge) return;
        if (j.status === 'connected') { badge.className='status-badge sb-on'; badge.textContent='Connected'; }
        else if (j.status === 'disabled') { badge.className='status-badge sb-dis'; badge.textContent='Disabled'; }
        else { badge.className='status-badge sb-off'; badge.textContent='Disconnected'; }
        chan.textContent = j.channel ? '#' + j.channel : '';
        // Inline SVG icons match the sidebar theming better than ✓/✗
        // emojis — labels are static strings so innerHTML is safe (no
        // user input flows through here).
        const _icoCheck = '<svg class="inline-ico" aria-hidden="true"><use href="#i-check"/></svg>';
        const _icoX     = '<svg class="inline-ico" aria-hidden="true"><use href="#i-x"/></svg>';
        if (tBadge) {
          if (j.access_token_set) {
            tBadge.style.cssText = 'background:#1a2a1a;color:#3de85a;border:1px solid #3de85a;margin-left:1em;font-size:.82em;padding:3px 10px;border-radius:3px;display:inline-block';
            tBadge.innerHTML = _icoCheck + ' Access Token set';
          } else {
            tBadge.style.cssText = 'background:#3a1a1a;color:var(--c-dead);border:1px solid #f03838;margin-left:1em;font-size:.82em;padding:3px 10px;border-radius:3px;display:inline-block';
            tBadge.innerHTML = _icoX + ' TWITCH_ACCESS_TOKEN not set';
          }
        }
        if (cidBadge) {
          if (j.client_id_set) {
            cidBadge.style.cssText = 'background:#1a2a1a;color:#3de85a;border:1px solid #3de85a;margin-left:.5em;font-size:.82em;padding:3px 10px;border-radius:3px;display:inline-block';
            cidBadge.innerHTML = _icoCheck + ' Client ID set';
          } else {
            cidBadge.style.cssText = 'background:#3a1a1a;color:var(--c-dead);border:1px solid #f03838;margin-left:.5em;font-size:.82em;padding:3px 10px;border-radius:3px;display:inline-block';
            cidBadge.innerHTML = _icoX + ' Client ID not set';
          }
        }
        if (errBox) {
          if (j.last_error) {
            errBox.style.display = 'block';
            errBox.textContent = j.last_error;
          } else {
            errBox.style.display = 'none';
            errBox.textContent = '';
          }
        }
        if (j.config && (forceConfig || !_cfgLoaded) && !_anyConfigFocused()) {
          document.getElementById('cfg-channel').value = j.config.channel || '';
          document.getElementById('cfg-nick').value = j.config.nick || '';
          document.getElementById('cfg-prefix').value = j.config.prefix || '!';
          document.getElementById('cfg-cooldown').value = j.config.command_cooldown_sec || 5;
          var ciEl = document.getElementById('cfg-client-id');
          if (ciEl) ciEl.value = j.config.client_id || '';
          _cfgLoaded = true;
        }
        var ll = document.getElementById('log-list');
        if (j.activity && j.activity.length) {
          ll.replaceChildren();
          j.activity.forEach(function(e){
            var d = document.createElement('div'); d.className='log-entry';
            var stamp = document.createElement('span'); stamp.className = 'log-ts'; stamp.textContent = String(e.ts).substring(11,19);
            var message = document.createElement('span'); message.className = 'log-txt'; message.textContent = e.text;
            d.replaceChildren(stamp, message);
            ll.appendChild(d);
          });
        }
      }).catch(function(){});
    }
    function saveConfig() {
      var ciEl = document.getElementById('cfg-client-id');
      var body = {
        channel:  document.getElementById('cfg-channel').value.trim(),
        nick:     document.getElementById('cfg-nick').value.trim(),
        prefix:   document.getElementById('cfg-prefix').value.trim() || '!',
        command_cooldown_sec: parseInt(document.getElementById('cfg-cooldown').value,10)||5,
        client_id: ciEl ? ciEl.value.trim() : ''
      };
      post('/api/bot/config', body).then(function(j){ showToast(j.ok?'Saved':'Error: '+(j.error||'?'), j.ok); loadStatus(true); });
    }
    function reloadBot() { post('/api/bot/reload').then(function(j){ showToast(j.ok?'Reconnecting…':'Error', j.ok); setTimeout(loadStatus,1200); }); }
    function enableBot()  { post('/api/bot/enable').then(function(j){ showToast(j.ok?'Enabled':'Error', j.ok); loadStatus(); }); }
    function disableBot() { post('/api/bot/disable').then(function(j){ showToast(j.ok?'Disabled':'Error', j.ok); loadStatus(); }); }
    function previewCmd() {
      var cmd = document.getElementById('prev-cmd').value;
      var arg = document.getElementById('prev-arg').value.trim();
      var box = document.getElementById('preview-out');
      box.textContent = 'Loading…';
      post('/api/bot/preview', {command: cmd, arg: arg}).then(function(j){
        box.textContent = j.reply || '(no reply)';
      }).catch(function(){ box.textContent = 'Error'; });
    }
    loadStatus();
    setInterval(loadStatus, 5000);
