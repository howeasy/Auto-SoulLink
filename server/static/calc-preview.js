// calc-preview.js — the in-battle damage preview for Radical Red runs.
// Reads #calc-preview-{pid}[data-in-battle] (its data-calc JSON is _calc_preview in server.py)
// and lazy-loads the damage engine exactly as the full calc page does: the same CommonJS shim
// and the same compiled files in the same order (calc/src/normal.template.html). Those files
// come from calc/dist, a local build (`cd calc && npm run build`, docs/REFERENCE.md); without it
// the preview stays hidden and tries again later. Loaded on every board: a no-op out of battle.
window.SLinkCalc = (function () {
  // The full page's engine scripts, in its order. tests/unit/test_calc_preview.py holds this
  // list to the template, so the two cannot drift apart.
  var ENGINE = [
    'calc/util.js', 'calc/stats.js', 'calc/data/species.js',
    'calc/data/types.js', 'calc/data/natures.js', 'calc/data/abilities.js',
    'calc/data/moves.js', 'calc/data/items.js', 'calc/data/index.js',
    'calc/move.js', 'calc/pokemon.js', 'calc/field.js', 'calc/items.js',
    'calc/mechanics/util.js', 'calc/mechanics/gen789.js', 'calc/mechanics/gen56.js',
    'calc/mechanics/gen4.js', 'calc/mechanics/gen3.js', 'calc/mechanics/gen12.js',
    'calc/calc.js', 'calc/desc.js', 'calc/result.js', 'calc/adaptable.js', 'calc/index.js',
  ];
  // Each page's setdex is its base sets plus the priority trainers merged into SETDEX_SV.
  var NORMAL_SETS   = ['js/data/sets/normal.js',   'js/data/sets/slink_priority.js'];
  var HARDCORE_SETS = ['js/data/sets/hardcore.js', 'js/data/sets/slink_priority.js'];
  var RETRY_MS = 30000;  // an unbuilt calc 404s; don't re-ask on every 2 s board refresh
  var _state = 'idle', _failedAt = 0;  // idle | loading | ready

  function _load(srcs, ok, fail) {
    var i = 0;
    (function next() {
      if (i >= srcs.length) { ok(); return; }
      var s = document.createElement('script');
      s.src = '/calc/' + srcs[i++];
      s.onload = next;
      s.onerror = fail;
      document.head.appendChild(s);
    })();
  }

  function _init() {
    if (_state !== 'idle' || Date.now() - _failedAt < RETRY_MS) return;
    _state = 'loading';
    // The full page's inline shim: every compiled module writes onto one shared exports
    // object, and require() hands that object back.
    window.__createBinding = function (o, m, k) { o[k] = m[k]; };
    window.calc = window.exports = {};
    window.require = function () { return window.exports; };
    function fail() { _state = 'idle'; _failedAt = Date.now(); }
    _load(ENGINE.concat(NORMAL_SETS), function () {
      window.SETDEX_NORMAL = window.SETDEX_SV || {};
      _load(HARDCORE_SETS, function () {
        window.SETDEX_HC = window.SETDEX_SV || {};
        window.SETDEX_SV = window.SETDEX_NORMAL;
        if (!window.calc.Pokemon || !window.calc.Generations) { fail(); return; }
        _state = 'ready';
        _renderAll();
      }, fail);
    }, fail);
  }

  // Trainer sets use the calc UI's stat keys; the engine wants its own.
  var STAT_KEYS = { hp: 'hp', at: 'atk', df: 'def', sa: 'spa', sd: 'spd', sp: 'spe' };
  function _stats(t) {
    var out = {};
    for (var k in (t || {})) out[STAT_KEYS[k] || k] = t[k];
    return out;
  }

  function _esc(s) {
    return String(s).replace(/[&<>"']/g, function (ch) { return '&#' + ch.charCodeAt(0) + ';'; });
  }

  function _buildPokemon(gen, species, opts, hpPct) {
    var names = [species, species.replace(/[♂♀]/g, '').trim()];
    for (var i = 0; i < names.length; i++) {
      try {
        var p = new window.calc.Pokemon(gen, names[i], opts);
        if (!p.species || !p.species.baseStats) continue;
        // Live HP is a percentage; the stats behind it are the engine's, so scale to them.
        if (hpPct > 0 && hpPct < 100) p.originalCurHP = Math.max(1, Math.round(p.rawStats.hp * hpPct / 100));
        return p;
      } catch (e) { /* try the next spelling */ }
    }
    return null;
  }

  function _sum(a) { return a.reduce(function (x, y) { return x + y; }, 0); }

  function _calcMove(gen, atk, def, moveName, field) {
    try {
      var move = new window.calc.Move(gen, moveName, { ability: atk.ability, item: atk.item, species: atk.name });
      var dmg = window.calc.calculate(gen, atk, def, move, field).damage;
      var lo, hi;
      if (typeof dmg === 'number') { lo = hi = dmg; }
      else if (Array.isArray(dmg[0])) {  // one roll list per hit (Parental Bond and the like)
        lo = _sum(dmg.map(function (h) { return h[0]; }));
        hi = _sum(dmg.map(function (h) { return h[h.length - 1]; }));
      } else { lo = dmg[0]; hi = dmg[dmg.length - 1]; }
      if (!hi) return null;  // status moves and immunities
      var max = def.maxHP() || 1, cur = def.curHP() || max;
      return {
        lo: Math.round(lo / max * 1000) / 10,
        hi: Math.round(hi / max * 1000) / 10,
        ohko: lo >= cur,
        twoHko: lo * 2 >= cur && lo < cur,
      };
    } catch (e) { return null; }
  }

  function _renderPreview(pid) {
    var div = document.getElementById('calc-preview-' + pid);
    if (!div) return;
    div.style.display = 'none';
    if (!div.getAttribute('data-in-battle') || _state !== 'ready') return;
    try {
      var c = JSON.parse(div.getAttribute('data-calc') || '{}');
      var moves = (c.player_moves || []).filter(Boolean);
      if (!c.player_species || !c.enemy_species || !moves.length) return;
      var gen = window.calc.Generations.get(9);

      // Trainer battles: pick the difficulty whose set matches the active enemy's level.
      var difficulty = 'normal', set = null;
      if (c.is_trainer && c.trainer_key) {
        var n = (window.SETDEX_NORMAL[c.enemy_species] || {})[c.trainer_key];
        var h = (window.SETDEX_HC[c.enemy_species] || {})[c.trainer_key];
        if (h && h.level == c.enemy_level && !(n && n.level == c.enemy_level)) difficulty = 'hardcore';
        set = difficulty === 'hardcore' ? h : n;
      }
      set = set || {};
      var defender = _buildPokemon(gen, c.enemy_species, {
        level: c.enemy_level, nature: set.nature, ability: set.ability, item: set.item,
        ivs: _stats(set.ivs), evs: _stats(set.evs),
        status: c.enemy_status || '', boosts: c.enemy_boosts || {},
      }, c.enemy_hp_pct);
      var attacker = _buildPokemon(gen, c.player_species, {
        level: c.player_level, nature: c.player_nature || 'Hardy',
        ability: c.player_ability || undefined, item: c.player_item || undefined, moves: moves,
        status: c.player_status || '', boosts: c.player_boosts || {},
      }, c.player_hp_pct);
      if (!defender || !attacker) return;
      var field = new window.calc.Field({ gameType: c.is_doubles ? 'Doubles' : 'Singles' });

      var rows = '';
      moves.forEach(function (m) {
        var r = _calcMove(gen, attacker, defender, m, field);
        if (!r) return;
        var cls = r.ohko ? 'ohko' : (r.twoHko ? 'twohko' : '');
        rows += '<tr><td>' + _esc(m) + '</td>'
          + '<td class="' + cls + '">' + r.lo + '–' + r.hi + '%</td>'
          + '<td class="' + cls + '">' + (r.ohko ? 'OHKO' : (r.twoHko ? '2HKO' : '')) + '</td></tr>';
      });
      if (!rows) return;
      var badge = difficulty === 'hardcore' ? ' <span style="color:#f80;font-size:0.78em">HC</span>' : '';
      div.innerHTML = '<h5>⚔ vs ' + _esc(c.enemy_species) + badge + '</h5>'
        + '<table class="calc-preview-table"><thead><tr><th>Move</th><th>Dmg %</th><th></th></tr></thead>'
        + '<tbody>' + rows + '</tbody></table>'
        + '<a class="calc-open-btn" href="/calc/' + difficulty + '.html" target="_blank">'
        + '⚔️ Open in RR Calc</a>';
      div.style.display = '';
    } catch (e) { /* a matchup the engine cannot model stays hidden */ }
  }

  function _renderAll() { _renderPreview('a'); _renderPreview('b'); }

  function checkAndInit() {
    if (document.querySelector('[data-in-battle]')) _init();
  }

  // Called by dashboard.js refreshClientUI() after each HTMX swap.
  window._slinkCalcRender = function () { checkAndInit(); _renderAll(); };

  checkAndInit();
  return { renderAll: _renderAll, checkAndInit: checkAndInit };
})();
