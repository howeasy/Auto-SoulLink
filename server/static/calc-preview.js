// calc-preview.js — the in-battle damage preview for Radical Red runs.
// Reads #calc-preview-{pid}[data-in-battle] on the board and lazy-loads the calc engine
// served at /calc/. Silent no-op if the calc is not built. Formerly _CALC_PREVIEW_JS in
// server.py, where 163 lines of JavaScript lived inside a Python string.
// ── RR Damage Calculator Preview ────────────────────────────────────────────
window.SLinkCalc = (function () {
  var _calcLoaded = false, _dataLoaded = false;

  function _loadSeq(srcs, cb) {
    var i = 0;
    (function next() {
      if (i >= srcs.length) { cb(); return; }
      var s = document.createElement('script');
      s.src = srcs[i++];
      s.onload = next;
      s.onerror = next;  // skip on 404 — calc might not be built yet
      document.head.appendChild(s);
    })();
  }

  function _init() {
    if (_calcLoaded) return;
    _calcLoaded = true;
    _loadSeq(['/calc/calc/calc.js'], function () {
      if (typeof window.calc === 'undefined') return;  // calc not built
      var s1 = document.createElement('script');
      s1.src = '/calc/js/data/sets/normal.js';
      s1.onload = function () {
        window.SETDEX_NORMAL = window.SETDEX_SV || {};
        var s2 = document.createElement('script');
        s2.src = '/calc/js/data/sets/hardcore.js';
        s2.onload = function () {
          window.SETDEX_HC  = window.SETDEX_SV || {};
          window.SETDEX_SV  = window.SETDEX_NORMAL;  // restore
          _dataLoaded = true;
          _renderAll();
        };
        s2.onerror = function () { _dataLoaded = true; _renderAll(); };
        document.head.appendChild(s2);
      };
      s1.onerror = function () { _dataLoaded = true; _renderAll(); };
      document.head.appendChild(s1);
    });
  }

  function _buildPokemon(gen, species, opts) {
    try { return new window.calc.Pokemon(gen, species, opts); }
    catch (e) {
      try { return new window.calc.Pokemon(gen, species.replace(/[♂♀]/g, '').trim(), opts); }
      catch (e2) { return null; }
    }
  }

  function _calcMove(gen, atk, def, moveName) {
    try {
      var result = window.calc.calculate(gen, atk, def,
        new window.calc.Move(gen, moveName), new window.calc.Field());
      var dmg = result.damage;
      if (!dmg || !dmg.length) return null;
      var flat = Array.isArray(dmg[0]) ? [].concat.apply([], dmg) : dmg;
      var lo = flat[0], hi = flat[flat.length - 1];
      var mhp = def.originalCurHP || def.stats.hp || 1;
      return {
        lo:     Math.round(lo / mhp * 1000) / 10,
        hi:     Math.round(hi / mhp * 1000) / 10,
        ohko:   lo >= mhp,
        twoHko: lo * 2 >= mhp && lo < mhp,
      };
    } catch (e) { return null; }
  }

  function _renderPreview(pid) {
    var div = document.getElementById('calc-preview-' + pid);
    if (!div || !div.getAttribute('data-in-battle')) {
      if (div) div.style.display = 'none';
      return;
    }
    if (!window.calc || !_dataLoaded) { div.style.display = 'none'; return; }
    try {
      var pMoves = JSON.parse(div.getAttribute('data-player-moves') || '[]');
      var tKey   = div.getAttribute('data-trainer-key') || '';
      var isTr   = div.getAttribute('data-is-trainer') === '1';
      var eSp    = div.getAttribute('data-enemy-species') || '';
      var eLv    = parseInt(div.getAttribute('data-enemy-level')  || '0', 10);
      var pSp    = div.getAttribute('data-player-species') || '';
      var pLv    = parseInt(div.getAttribute('data-player-level')  || '0', 10);
      var pNat   = div.getAttribute('data-player-nature')  || 'Hardy';
      var pAbl   = div.getAttribute('data-player-ability') || undefined;
      var pItm   = div.getAttribute('data-player-item')    || undefined;
      if (!pSp || !eSp) { div.style.display = 'none'; return; }

      var gen = window.calc.Generations.get(9);

      // Auto-detect difficulty by level-matching the active enemy
      var difficulty = 'normal';
      var trainerSet = null;
      if (isTr && tKey && window.SETDEX_NORMAL) {
        var nEntry = window.SETDEX_NORMAL[eSp] && window.SETDEX_NORMAL[eSp][tKey];
        var hEntry = window.SETDEX_HC     && window.SETDEX_HC[eSp] && window.SETDEX_HC[eSp][tKey];
        if (hEntry && hEntry.level == eLv && !(nEntry && nEntry.level == eLv))
          difficulty = 'hardcore';
        trainerSet = difficulty === 'hardcore' ? hEntry : nEntry;
      }

      var defOpts = { level: eLv, evs: {}, ivs: {hp:31,at:31,df:31,sa:31,sd:31,sp:31} };
      if (trainerSet) {
        if (trainerSet.nature)  defOpts.nature  = trainerSet.nature;
        if (trainerSet.ability) defOpts.ability = trainerSet.ability;
        if (trainerSet.item)    defOpts.item    = trainerSet.item;
        if (trainerSet.ivs)     defOpts.ivs     = trainerSet.ivs;
        if (trainerSet.evs)     defOpts.evs     = trainerSet.evs;
      }
      var defender = _buildPokemon(gen, eSp, defOpts);
      if (!defender) { div.style.display = 'none'; return; }

      var atkOpts = {
        level: pLv, nature: pNat,
        ability: pAbl || undefined, item: pItm || undefined,
        moves: pMoves, evs: {}, ivs: {hp:31,at:31,df:31,sa:31,sd:31,sp:31},
      };
      var attacker = _buildPokemon(gen, pSp, atkOpts);
      if (!attacker) { div.style.display = 'none'; return; }

      var rows = [];
      pMoves.forEach(function (m) {
        if (!m) return;
        var r = _calcMove(gen, attacker, defender, m);
        if (r) rows.push({ move: m, lo: r.lo, hi: r.hi, ohko: r.ohko, twoHko: r.twoHko });
      });
      if (!rows.length) { div.style.display = 'none'; return; }

      var diffBadge = difficulty === 'hardcore'
        ? ' <span style="color:#f80;font-size:0.78em">HC</span>' : '';
      var h = '<h5>\u2694 vs ' + eSp + diffBadge + '</h5>';
      h += '<table class="calc-preview-table"><thead>'
        +  '<tr><th>Move</th><th>Dmg\u202f%</th><th></th></tr>'
        +  '</thead><tbody>';
      rows.forEach(function (r) {
        var c   = r.ohko ? 'ohko' : (r.twoHko ? 'twohko' : '');
        var lbl = r.ohko ? 'OHKO' : (r.twoHko ? '2HKO'   : '');
        h += '<tr><td>' + r.move + '</td>'
          +  '<td class="' + c + '">' + r.lo + '\u2013' + r.hi + '%</td>'
          +  '<td class="' + c + '">' + lbl + '</td></tr>';
      });
      h += '</tbody></table>';
      var page = difficulty === 'hardcore' ? '/calc/hardcore.html' : '/calc/normal.html';
      h += '<a class="calc-open-btn" href="' + page + '" target="_blank">'
        +  '\u2694\ufe0f Open in RR Calc</a>';
      div.innerHTML    = h;
      div.style.display = '';
    } catch (e) { div.style.display = 'none'; }
  }

  function _renderAll() { _renderPreview('a'); _renderPreview('b'); }

  function checkAndInit() {
    if (!_calcLoaded && document.querySelector('[data-in-battle]')) _init();
  }

  // Called by dashboard.js refreshClientUI() after each HTMX swap.
  window._slinkCalcRender = function () { checkAndInit(); _renderAll(); };

  checkAndInit();
  return { renderAll: _renderAll, checkAndInit: checkAndInit };
})();
