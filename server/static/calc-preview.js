// The preview never fills missing battle observations from trainer sets.
(function () {
  'use strict';
  var enginePromise;
  var stats = ['hp', 'atk', 'def', 'spa', 'spd', 'spe'];

  function baseURL() { return new URL('./', window.location.href); }
  function calculatorLink() {
    var url = new URL('calc/normal.html', baseURL());
    url.searchParams.set('slink', baseURL().href.replace(/\/$/, ''));
    return SLinkDOM.el('a', {className: 'calc-open-btn', href: url.href, target: '_blank', rel: 'noopener'}, 'Open in RR Calc');
  }
  function unavailable(node, reason) {
    node.style.display = '';
    node.setAttribute('data-calc-state', 'unavailable');
    node.replaceChildren(SLinkDOM.el('h5', {}, 'Damage preview unavailable'), SLinkDOM.el('p', {}, reason), calculatorLink());
  }
  function ensureEngine() {
    if (window.calc && window.calc.calculate && window.calc.Generations) return Promise.resolve(window.calc);
    if (!enginePromise) enginePromise = new Promise(function (resolve, reject) {
      var script = document.createElement('script');
      script.src = new URL('calc/calc/slink-browser.js', baseURL()).href;
      script.onload = function () {
        if (window.calc && window.calc.calculate && window.calc.Generations) resolve(window.calc);
        else reject(new Error('The calculator could not initialize.'));
      };
      script.onerror = function () { reject(new Error('The calculator browser build is unavailable.')); };
      document.head.append(script);
    });
    return enginePromise;
  }
  function completePokemon(mon) {
    if (!mon || typeof mon.species !== 'string' || !mon.species || !mon.options) return false;
    var options = mon.options;
    if (!Number.isInteger(options.level) || options.level < 1 || options.level > 100) return false;
    if (!Number.isInteger(options.curHP) || options.curHP <= 0 || typeof options.nature !== 'string') return false;
    if (typeof options.ability !== 'string' || typeof options.item !== 'string' || typeof options.status !== 'string') return false;
    return ['ivs', 'evs', 'boosts'].every(function (key) {
      return options[key] && stats.every(function (stat) {
        var value = options[key][stat];
        return Number.isInteger(value) && (key === 'ivs' ? value >= 0 && value <= 31 : key === 'evs' ? value >= 0 && value <= 252 : value >= -6 && value <= 6);
      });
    });
  }
  function calculate(input) {
    if (!input || input.complete !== true || !input.field || !['Singles', 'Doubles'].includes(input.field.gameType)) throw new Error('Complete battle inputs are required.');
    if (input.field.gameType === 'Doubles' && input.targetSelected !== true) throw new Error('Select a doubles target before calculating.');
    if (!completePokemon(input.attacker) || !completePokemon(input.defender)) throw new Error('Complete Pokémon inputs are required.');
    if (!Array.isArray(input.moves) || !input.moves.length || input.moves.some(function (move) { return typeof move !== 'string' || !move; })) throw new Error('Resolved move names are required.');
    var calc = window.calc;
    if (!calc || !calc.calculate) throw new Error('The calculator is not loaded.');
    if (!Number.isInteger(input.generation) || input.generation < 1 || input.generation > 9) throw new Error('A calculator generation is required.');
    var generation = calc.Generations.get(input.generation);
    var attacker = new calc.Pokemon(generation, input.attacker.species, input.attacker.options);
    var defender = new calc.Pokemon(generation, input.defender.species, input.defender.options);
    var maximum = defender.maxHP(), current = defender.curHP();
    return input.moves.map(function (name) {
      var result = calc.calculate(generation, attacker, defender, new calc.Move(generation, name), new calc.Field(input.field));
      var range = result.range();
      if (!range.every(Number.isFinite)) throw new Error('The calculator returned an invalid damage range.');
      return {move: name, minimum: range[0], maximum: range[1],
        lowPercent: Math.round(range[0] / maximum * 1000) / 10,
        highPercent: Math.round(range[1] / maximum * 1000) / 10,
        ohko: range[0] >= current, twoHko: range[0] * 2 >= current && range[0] < current,
        defenderMaxHP: maximum, defenderCurrentHP: current};
    });
  }
  function render(node) {
    var raw = node.getAttribute('data-calc-input');
    if (!raw) {
      unavailable(node, 'Verified battle details are not available for this run. Open Calc to enter them.');
      return;
    }
    var input;
    try { input = JSON.parse(raw); }
    catch (_) { unavailable(node, 'The battle details could not be read.'); return; }
    if (node.getAttribute('data-calc-rendered') === raw) return;
    ensureEngine().then(function () {
      // A refresh can replace or retarget this node while the bundle loads.
      if (!node.isConnected || node.getAttribute('data-calc-input') !== raw) return;
      try {
        var rows = calculate(input);
        var title = input.provenance === 'synthetic' ? 'Synthetic calculation fixture' : 'Damage estimate';
        var table = SLinkDOM.table(['Move', 'Dmg %', ''], rows.map(function (row) {
          var color = row.ohko ? 'ohko' : row.twoHko ? 'twohko' : '';
          return [row.move, SLinkDOM.el('span', {className: color}, row.lowPercent + '–' + row.highPercent + '%'),
            SLinkDOM.el('span', {className: color}, row.ohko ? 'OHKO' : row.twoHko ? '2HKO' : '')];
        }), 'calc-preview-table');
        node.replaceChildren(SLinkDOM.el('h5', {}, title + ' · vs ' + input.defender.species), table, calculatorLink());
        node.style.display = '';
        node.setAttribute('data-calc-state', 'ready');
        node.setAttribute('data-calc-rendered', raw);
      } catch (error) { unavailable(node, error.message); }
    }).catch(function (error) {
      if (node.isConnected && node.getAttribute('data-calc-input') === raw) unavailable(node, error.message);
    });
  }
  function renderAll() {
    document.querySelectorAll('.calc-preview[data-in-battle]').forEach(render);
  }
  window._slinkCalcRender = renderAll;
  window.SLinkCalc = Object.freeze({renderAll: renderAll, checkAndInit: renderAll, calculate: calculate});
  renderAll();
})();
