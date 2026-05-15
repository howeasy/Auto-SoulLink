/**
 * slink_bridge.js
 * SLink Soul Link server ↔ Radical Red damage-calc bridge panel.
 *
 * Injects a floating, draggable panel into the calc page that shows live
 * party data from the SLink server and lets players one-click load any mon
 * into the attacker (#p1) or defender (#p2) slot.
 *
 * No additional dependencies — jQuery and window.addSets are already present
 * on every calc page.
 */
(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // Config
  // ---------------------------------------------------------------------------

  var PANEL_ID = 'slink-bridge-panel';
  var LS_POS   = 'slink_bridge_pos';        // localStorage key for position
  var LS_COL   = 'slink_bridge_collapsed';  // localStorage key for collapse

  /**
   * Resolve SLink server base URL:
   *   ?slink=http://192.168.1.5:8086  →  that origin
   *   (default)                        →  same origin as the calc page
   *                                       (calc is served by the SLink server)
   */
  var SLINK_BASE = (function () {
    try {
      var p = new URLSearchParams(window.location.search);
      var v = p.get('slink');
      if (v) return v.replace(/\/$/, '');
    } catch (e) { /* URLSearchParams not available — fall through */ }
    return window.location.protocol + '//' + window.location.host;
  })();

  // ---------------------------------------------------------------------------
  // Colour palette (dark theme matching the calc)
  // ---------------------------------------------------------------------------

  var C = {
    panelBg  : '#1a1a2e',
    headerBg : '#16213e',
    border   : '#0f3460',
    btn      : '#e94560',
    activeTab: '#0f3460',
    text     : '#eee',
    dim      : '#888',
    item     : '#adf',
    nature   : '#cba',   // also used for ability
    hpGreen  : '#4caf50',
    hpYellow : '#ffeb3b',
    hpRed    : '#f44336',
  };

  // ---------------------------------------------------------------------------
  // Runtime state
  // ---------------------------------------------------------------------------

  var _data           = null;   // latest /api/calc/mons payload
  var _connected      = false;
  var _fetching       = false;  // true while a fetch is in-flight
  var _fetchPending   = false;  // SSE ping arrived while interacting; flush on mouseup
  var _userInteracting = false;
  var _interactionTimer = null;
  var _activeTab      = 'a';
  var _diffCache      = {};     // "side:trainerKey" → {mode, matched, total}
  var _lastTrainerKey = { a: null, b: null };
  var _setdexReady    = false;
  var _sseSource      = null;
  var _retryTimer     = null;

  // RR set names that differ from the calc engine's move name table.
  // Funnotbun uses its own names for some moves; two RR customs don't exist in
  // the calc at all (Soupercell Slam, Forbidden Spell) and are added to moves.ts.
  var MOVE_ALIASES = {
    'Drain Kiss': 'Draining Kiss',    // funnotbun canonical → calc name
    'Disarm Cry': 'Disarming Voice',  // funnotbun canonical → calc name
  };
  function _normalizeMoveName(name) {
    return MOVE_ALIASES[name] || name;
  }

  // Prep tab state — mode is fixed to the current page (no cross-mode toggle)
  var _pageIsHC      = /hardcore/i.test(window.location.href);
  var _prepMode      = _pageIsHC ? 'hardcore' : 'normal';
  var _prepTrainer   = localStorage.getItem('slink_prep_trainer')   || '';
  var _prepEncounter = localStorage.getItem('slink_prep_encounter') || '';       // '' = first enc
  var _trainerIndex  = { nm: {}, hc: {} };  // baseName → { encounters, encounterOrder }
  var _trainerNames  = [];                  // sorted union of trainer names for datalist

  // ---------------------------------------------------------------------------
  // SETDEX_HC loading trick
  //
  // Both normal.js and hardcore.js define `var SETDEX_SV`.  To have both
  // datasets accessible simultaneously we snapshot the current one, then
  // dynamically load the other file so difficulty detection can compare levels
  // against both.
  //
  // End-state (regardless of which page we're on):
  //   window.SETDEX_SV  = normal trainer data  (calc unaffected)
  //   window.SETDEX_HC  = hardcore trainer data (bridge badge detection)
  // ---------------------------------------------------------------------------

  function initSetdex() {
    // Snapshot whatever is loaded right now
    window.SETDEX_NORMAL_SNAP = window.SETDEX_SV || {};

    var isHC = /hardcore/i.test(window.location.href);
    var src  = isHC ? './js/data/sets/normal.js' : './js/data/sets/hardcore.js';

    var s    = document.createElement('script');
    s.src    = src;

    s.onload = function () {
      if (isHC) {
        // We just loaded normal.js → SETDEX_SV is now normal data.
        // The original HC snapshot becomes SETDEX_HC.
        window.SETDEX_HC = window.SETDEX_NORMAL_SNAP;  // original HC
        // SETDEX_SV is already normal (just loaded). Spec: "no restore needed".
      } else {
        // We just loaded hardcore.js → SETDEX_SV is now HC data.
        // Capture it, then restore normal so the calc is unaffected.
        window.SETDEX_HC = window.SETDEX_SV;           // capture HC
        window.SETDEX_SV = window.SETDEX_NORMAL_SNAP;  // restore normal
      }

      // * prefix = boss/ace encounter, NOT HC-only.  Keep all keys in SETDEX_SV.

      _setdexReady = true;
      _buildBothIndexes();   // build prep-tab trainer index now both setdexes are ready
      _enrichEnemyMons(); // re-run with both datasets now available
      refreshPanel(); // re-render difficulty badges now both datasets are live
    };

    s.onerror = function () {
      // Other dataset file not found; difficulty detection will score 0 on it.
      _setdexReady = true;
    };

    document.head.appendChild(s);
  }

  // ---------------------------------------------------------------------------
  // Difficulty badge detection + trainer party-composition matching
  // ---------------------------------------------------------------------------

  /**
   * Given an enemy party array and a setdex, find the bare trainer set-key
   * (e.g. "Lass Anne") whose mons best match the enemy party by species+level.
   *
   * Algorithm:
   *   For every species in the setdex, for every set key, tally how many
   *   enemy mons match that (setKey, level) pair.  The set key with the most
   *   matches wins.  Ties are broken by fewest misses.
   *
   * @param {Array}  enemyParty  [{species_name, level}, ...]
   * @param {Object} setdex      SETDEX_SV or SETDEX_HC
   * @returns {string|null}      Bare set key ("Lass Anne") or null
   */
  function _findTrainerKeyByParty(enemyParty, setdex) {
    if (!enemyParty || !enemyParty.length || !setdex) return null;

    // tally[bareKey] = number of enemy mons that match a set entry under that key
    var tally = {};

    enemyParty.forEach(function (em) {
      if (!em.species_name || !em.level) return;
      var sets = setdex[em.species_name];
      if (!sets) return;
      Object.keys(sets).forEach(function (setKey) {
        if (sets[setKey].level === em.level) {
          var bare = setKey.charAt(0) === '*' ? setKey.slice(1) : setKey;
          // Strip trailing " Set N" for multi-set trainers ("Rival Blue Set 1" → "Rival Blue")
          var baseBare = bare.replace(/\s+Set\s+\d+$/i, '');
          tally[baseBare] = (tally[baseBare] || 0) + 1;
        }
      });
    });

    // Pick the key with the highest match count
    var bestKey = null, bestScore = 0;
    Object.keys(tally).forEach(function (k) {
      if (tally[k] > bestScore) { bestScore = tally[k]; bestKey = k; }
    });

    // Require at least half the party to match to avoid false positives
    return (bestScore >= Math.max(1, Math.ceil(enemyParty.length / 2))) ? bestKey : null;
  }

  /**
   * Detect whether a battle is Normal or Hardcore difficulty by comparing the
   * enemy party against both setdexes and seeing which scores more matches.
   *
   * @param {Array} enemyParty [{species_name, level}, ...]
   * @returns {{mode, matchedKey, matched, total}}
   */
  function detectDifficulty(enemyParty) {
    var sv = window.SETDEX_SV || {};
    var hc = window.SETDEX_HC || {};

    var svKey = _findTrainerKeyByParty(enemyParty, sv);
    var hcKey = _findTrainerKeyByParty(enemyParty, hc);

    // Count exact species+level matches for the discovered key in each db
    function countMatches(party, db, trainerKey) {
      if (!trainerKey) return 0;
      var score = 0;
      party.forEach(function (em) {
        var sets = em.species_name && db[em.species_name];
        if (!sets) return;
        Object.keys(sets).forEach(function (sk) {
          var bare = (sk.charAt(0) === '*' ? sk.slice(1) : sk)
                      .replace(/\s+Set\s+\d+$/i, '');
          if (bare === trainerKey && sets[sk].level === em.level) score++;
        });
      });
      return score;
    }

    var svScore = countMatches(enemyParty, sv, svKey);
    var hcScore = countMatches(enemyParty, hc, hcKey);
    var useHC   = hcScore > svScore;

    return {
      mode      : useHC ? 'hardcore' : 'normal',
      matchedKey: useHC ? hcKey : svKey,
      matched   : useHC ? hcScore : svScore,
      total     : (enemyParty || []).length,
    };
  }

  /**
   * Returns the cached difficulty result for the active battle, or null if
   * the player isn't in a trainer battle.
   */
  function getDifficultyBadge(pd, side) {
    if (!pd || !pd.enemy || !pd.enemy.length) return null;

    var trainerLabel = (pd.enemy[0] && pd.enemy[0].trainer_label) || '';
    if (!trainerLabel || trainerLabel === 'Wild') return null;

    // Cache key: stringify the party comp (species+level) so it invalidates when the team changes
    var partyKey = pd.enemy.map(function (e) { return e.species_name + ':' + e.level; }).join(',');
    if (_lastTrainerKey[side] !== partyKey) {
      _lastTrainerKey[side] = partyKey;
      delete _diffCache[side + ':' + partyKey];
    }

    var k = side + ':' + partyKey;
    if (!_diffCache[k]) {
      _diffCache[k] = detectDifficulty(pd.enemy);
    }
    return _diffCache[k];
  }

  // ---------------------------------------------------------------------------
  // Enemy set enrichment — look up trainer movesets from SETDEX_SV / SETDEX_HC
  // ---------------------------------------------------------------------------

  /**
   * For each enemy mon in _data, find the matching trainer set by party
   * composition and populate moves + rebuild the showdown paste.
   */
  function _enrichEnemyMons() {
    if (!_data) return;

    ['a', 'b'].forEach(function (side) {
      var pd = _data[side];
      if (!pd || !pd.enemy || !pd.enemy.length) return;

      var trainerLabel = (pd.enemy[0] && pd.enemy[0].trainer_label) || '';
      // Wild battles never have setdex entries; trainer battles with empty labels may still match
      if (trainerLabel === 'Wild') return;

      var matchedKey, mode, trEntry;

      // ── Method 1: direct _trainerIndex lookup by trainer_label (same path as Prep tab) ──
      // This is the primary method and mirrors exactly how the Prep tab resolves moves.
      if (trainerLabel && (_trainerIndex.nm[trainerLabel] || _trainerIndex.hc[trainerLabel])) {
        var nmEntry = _trainerIndex.nm[trainerLabel];
        var hcEntry = _trainerIndex.hc[trainerLabel];

        // Detect mode by counting exact-level species matches in each index
        var nmScore = 0, hcScore = 0;
        pd.enemy.forEach(function (em) {
          if (!em.species_name || !em.level) return;
          function scoreEntry(entry) {
            if (!entry) return 0;
            var n = 0;
            Object.keys(entry.encounters).forEach(function (enc) {
              entry.encounters[enc].forEach(function (item) {
                if (item.species === em.species_name && item.set.level === em.level) n++;
              });
            });
            return n;
          }
          nmScore += scoreEntry(nmEntry);
          hcScore += scoreEntry(hcEntry);
        });

        if (hcScore > nmScore) { mode = 'hardcore'; trEntry = hcEntry; }
        else if (nmEntry)      { mode = 'normal';   trEntry = nmEntry; }
        else                   { mode = 'hardcore'; trEntry = hcEntry; }
        matchedKey = trainerLabel;
      }

      // ── Method 2: fallback — detect trainer by party composition (species+level tally) ──
      if (!matchedKey) {
        var diff   = detectDifficulty(pd.enemy);
        matchedKey = diff.matchedKey;
        mode       = diff.mode;
        // trEntry stays null; we'll use raw setdex below
      }

      if (!matchedKey) return;

      pd.enemy.forEach(function (mon) {
        if (!mon.species_name) return;

        var best = null;

        if (trEntry) {
          // Method 1 path: search all encounters for this species, pick closest level
          var bestDist = Infinity;
          Object.keys(trEntry.encounters).forEach(function (encLabel) {
            trEntry.encounters[encLabel].forEach(function (item) {
              if (item.species === mon.species_name) {
                var dist = Math.abs((item.set.level || 0) - mon.level);
                if (dist < bestDist) { bestDist = dist; best = item.set; }
              }
            });
          });
        } else {
          // Method 2 path: use raw setdex with setKey matching
          var setdex = (mode === 'hardcore' ? (window.SETDEX_HC || window.SETDEX_SV) : window.SETDEX_SV) || {};
          var sets   = setdex[mon.species_name];
          if (!sets) return;

          var candidates = [];
          Object.keys(sets).forEach(function (setKey) {
            var bare     = (setKey.charAt(0) === '*' ? setKey.slice(1) : setKey);
            var baseBare = bare.replace(/\s+Set\s+\d+$/i, '');
            if (baseBare === matchedKey) candidates.push({ key: setKey, set: sets[setKey] });
          });
          if (!candidates.length) return;

          candidates.sort(function (a, b) {
            return Math.abs((a.set.level || 0) - mon.level) -
                   Math.abs((b.set.level || 0) - mon.level);
          });
          best = candidates[0].set;
        }

        if (!best) return;

        mon.moves        = best.moves   || [];
        mon.nature       = best.nature  || mon.nature       || 'Hardy';
        mon.ability_name = best.ability || mon.ability_name || '';
        mon.item_name    = best.item    || mon.item_name    || '';
        mon._diff_mode   = mode;
        mon._matched_key = matchedKey;

        // Rebuild showdown paste
        var dispName = (mon.nickname && mon.nickname !== mon.species_name)
          ? mon.species_name + ' (' + mon.nickname + ')'
          : mon.species_name;
        var lines = [dispName + (mon.item_name ? ' @ ' + mon.item_name : '')];
        if (mon.ability_name) lines.push('Ability: ' + mon.ability_name);
        lines.push('Level: ' + mon.level);
        lines.push((mon.nature || 'Hardy') + ' Nature');
        mon.moves.forEach(function (m) { lines.push('- ' + m); });
        mon.showdown_paste = lines.join('\n');
      });
    });
  }

  // ---------------------------------------------------------------------------
  // Trainer index — inverted lookup for Prep tab
  // ---------------------------------------------------------------------------

  // Trainers fought at multiple points in the game (e.g. Rocket Admin Archer) have
  // mons from different fights all sharing the plain trainer-name key, which collapses
  // them into one '__base__' bucket.  Only the mon that appears in EVERY fight
  // (often the trainer's signature ace) gets "Set N" suffixes.  We split '__base__'
  // (and 'Boss') by level-gap clustering and merge each cluster with the nearest
  // numbered encounter so every fight gets its own encounter tab.
  var LEVEL_GAP_THRESHOLD = 15;  // levels; mons further apart belong to different fights

  /**
   * Post-process a single encounter group (e.g. '__base__' or 'Boss'):
   *   - Sort mons by level and cluster by gaps > LEVEL_GAP_THRESHOLD
   *   - If only one cluster → nothing to do
   *   - Otherwise merge each cluster into the closest numbered Set-N encounter
   *     (within LEVEL_GAP_THRESHOLD) or create synthetic 'Encounter N' labels
   *   - Delete the original flat group
   *
   * @param {Object} tr         Trainer entry { encounters, encounterOrder }
   * @param {string} baseLabel  '__base__' or 'Boss'
   * @param {RegExp} numberedRe Matches the numbered variants of this group ('Set N' or 'Boss Set N')
   * @param {string} synthPfx   Prefix for synthetic labels ('Encounter ' or 'Boss Encounter ')
   */
  function _splitEncounterGroup(tr, baseLabel, numberedRe, synthPfx) {
    var baseEnc = tr.encounters[baseLabel];
    if (!baseEnc || baseEnc.length <= 1) return;

    // Sort ascending so gaps are easy to detect
    var sorted = baseEnc.slice().sort(function (a, b) {
      return (a.set.level || 0) - (b.set.level || 0);
    });

    // Build level-gap clusters
    var groups = [[sorted[0]]];
    for (var i = 1; i < sorted.length; i++) {
      var prevLvl = sorted[i - 1].set.level || 0;
      var currLvl = sorted[i].set.level     || 0;
      if (currLvl - prevLvl > LEVEL_GAP_THRESHOLD) groups.push([]);
      groups[groups.length - 1].push(sorted[i]);
    }
    if (groups.length <= 1) return;  // all at similar levels — no split needed

    function avgLvl(mons) {
      if (!mons.length) return 0;
      return mons.reduce(function (s, m) { return s + (m.set.level || 0); }, 0) / mons.length;
    }

    // Numbered Set-N keys available to absorb clusters (e.g. 'Set 1', 'Boss Set 2')
    var numberedKeys = Object.keys(tr.encounters).filter(function (k) {
      return numberedRe.test(k);
    });
    var usedKeys    = {};
    var synthCount  = 0;

    groups.forEach(function (group) {
      var ga = avgLvl(group);

      // Find the nearest unused numbered encounter
      var bestKey = null, bestDist = Infinity;
      numberedKeys.forEach(function (k) {
        if (usedKeys[k]) return;
        var dist = Math.abs(avgLvl(tr.encounters[k]) - ga);
        if (dist < bestDist) { bestDist = dist; bestKey = k; }
      });

      if (bestKey && bestDist <= LEVEL_GAP_THRESHOLD) {
        // Merge cluster mons into the numbered encounter (prepend; per-enc sort runs later)
        usedKeys[bestKey] = true;
        tr.encounters[bestKey] = group.concat(tr.encounters[bestKey]);
      } else {
        synthCount++;
        tr.encounters[synthPfx + synthCount] = group;
      }
    });

    delete tr.encounters[baseLabel];
  }

  /**
   * Build an inverted trainer index from a SETDEX.
   *
   * Input:  SETDEX_SV or SETDEX_HC  (species → setKey → set-entry)
   * Output: {
   *   "Leader Falkner": { encounters: { null: [mons], "HC": [mons] },
   *                       encounterOrder: ["HC", null] },
   *   "Rival Blue":     { encounters: { "Set 1": [mons], null: [mons] },
   *                       encounterOrder: ["Set 1", null] },
   *   ...
   * }
   *
   * Encounter label decoding (* = boss/ace variant, Set N = numbered encounter):
   *   non-starred + no Set N  → '__base__'   ("Base" single encounter)
   *   starred     + no Set N  → 'Boss'
   *   non-starred + Set N     → 'Set N'
   *   starred     + Set N     → 'Boss Set N'
   */
  function _buildTrainerIndex(setdex) {
    var index = {};

    Object.keys(setdex).forEach(function (species) {
      var sets = setdex[species];
      Object.keys(sets).forEach(function (setKey) {
        var isAce   = setKey.charAt(0) === '*';
        var bare    = isAce ? setKey.slice(1) : setKey;
        var setNm   = bare.match(/\s+Set\s+(\d+)$/i);
        var setNum  = setNm ? 'Set ' + setNm[1] : null;
        var base    = setNm ? bare.slice(0, bare.length - setNm[0].length) : bare;

        var encLabel;
        if (isAce && setNum)       encLabel = 'Boss ' + setNum;
        else if (isAce)            encLabel = 'Boss';
        else if (setNum)           encLabel = setNum;
        else                       encLabel = '__base__';   // single / base encounter

        if (!index[base]) index[base] = { encounters: {}, encounterOrder: [] };
        var tr = index[base];
        if (!tr.encounters[encLabel]) tr.encounters[encLabel] = [];
        tr.encounters[encLabel].push({ species: species, set: sets[setKey] });
      });
    });

    // Split multi-fight flat groups, then sort mons within each encounter,
    // then build encounterOrder.
    Object.keys(index).forEach(function (base) {
      var tr  = index[base];
      var enc = tr.encounters;

      // Split '__base__' mons by level-gap clusters (multi-fight trainers like Archer)
      _splitEncounterGroup(tr, '__base__', /^Set\s+\d+$/i,       'Encounter ');
      // Split 'Boss' mons similarly (starred multi-fight aces)
      _splitEncounterGroup(tr, 'Boss',     /^Boss\s+Set\s+\d+$/i, 'Boss Encounter ');

      // Sort mons within each encounter by level desc
      Object.keys(enc).forEach(function (lbl) {
        enc[lbl].sort(function (a, b) {
          return (b.set.level || 0) - (a.set.level || 0);
        });
      });

      // Sort encounterOrder: '__base__' first (single-fight trainers), then
      // non-Boss encounters ascending by avg level (game-chronological order),
      // then Boss encounters ascending by avg level.
      tr.encounterOrder = Object.keys(enc).sort(function (a, b) {
        if (a === '__base__') return -1;
        if (b === '__base__') return  1;
        var aBoss = /^Boss/.test(a);
        var bBoss = /^Boss/.test(b);
        if (aBoss !== bBoss) return aBoss ? 1 : -1;  // Boss after non-Boss
        function avg(mons) {
          if (!mons.length) return 0;
          return mons.reduce(function (s, m) { return s + (m.set.level || 0); }, 0) / mons.length;
        }
        return avg(enc[a]) - avg(enc[b]);  // ascending = game-chronological
      });
    });

    return index;
  }

  /**
   * Build both indexes (NM + HC) and update the trainer names list for autocomplete.
   * Called once both setdexes are ready (from initSetdex onload).
   */
  function _buildBothIndexes() {
    _trainerIndex.nm = _buildTrainerIndex(window.SETDEX_SV || {});   // Normal sets (normal.js)
    _trainerIndex.hc = _buildTrainerIndex(window.SETDEX_HC || {});   // HC sets (hardcore.js)

    var allNames = {};
    Object.keys(_trainerIndex.nm).forEach(function (k) { allNames[k] = 1; });
    Object.keys(_trainerIndex.hc).forEach(function (k) { allNames[k] = 1; });
    _trainerNames = Object.keys(allNames).sort();
  }

  // ---------------------------------------------------------------------------
  // Import mechanism
  // ---------------------------------------------------------------------------

  /**
   * Load a mon's Showdown paste into the calc's attacker (#p1) or defender (#p2).
   *
   * Steps:
   *   1. Call addSets(showdown_paste, setName) to register the set.
   *   2. Set the set-selector value and trigger change for Select2 compat.
   *
   * @param {Object}        mon        Mon entry from /api/calc/mons
   * @param {'p1'|'p2'}     targetSide Attacker or defender panel
   */
  function importMon(mon, targetSide) {
    if (!mon || !mon.species_name) {
      showToast('⚠ Cannot import: missing mon data.', 'error');
      return;
    }
    _loadMonIntoPanel(mon, targetSide);
  }

  /**
   * Directly populate a calc panel (#p1 or #p2) from a mon object.
   *
   * The calc uses Select2 v3.4.5 whose initSelection callback always returns
   * the first valid set (ignoring the value), so .val(value).change() does not
   * load the right species.  Instead we:
   *   1. Use select2('data', …) to force the set-selector to the species Blank Set
   *      and trigger its change handler — this loads base stats and types.
   *   2. Directly override the individual fields (level, nature, ability, item,
   *      moves) and fire change on each to trigger recalculation.
   */
  function _loadMonIntoPanel(mon, side) {
    var $jq = window.$;
    if (!$jq) {
      showToast('⚠ jQuery not available — is the calc fully loaded?', 'error');
      return;
    }

    var pokeObj = $jq('#' + side);
    if (!pokeObj.length) {
      showToast('⚠ Panel #' + side + ' not found.', 'error');
      return;
    }

    var species = mon.species_name;
    if (!window.pokedex || !window.pokedex[species]) {
      showToast('⚠ Species "' + species + '" not in calc data.', 'error');
      return;
    }

    var ss = pokeObj.find('.set-selector');

    // ── Enemy mon with a matched setdex key ──────────────────────────────────
    // Inject the enriched set directly into SETDEX_SV so the change handler
    // loads it natively, and the dropdown shows the real trainer set name
    // (e.g. "Stufful (Lass Anne)") confirming the match.
    if (mon._matched_key) {
      var setName = mon._matched_key;
      if (!window.SETDEX_SV[species]) window.SETDEX_SV[species] = {};
      window.SETDEX_SV[species][setName] = {
        nature  : mon.nature       || 'Hardy',
        ability : mon.ability_name || '',
        item    : mon.item_name    || '',
        level   : mon.level        || 50,
        moves   : (mon.moves || []).map(_normalizeMoveName),
      };
      var namedId = species + ' (' + setName + ')';
      ss.select2('data', { id: namedId, text: namedId, pokemon: species, set: setName })
        .trigger('change');
      setTimeout(function () {
        try { ss.select2('container').find('.select2-chosen').text(namedId); } catch (e) {}
      }, 0);
      setTimeout(function () { _applyBattleState(pokeObj, mon); }, 0);
      showToast('✓ ' + species + ' (' + setName + ') → ' + (side === 'p1' ? 'Attacker' : 'Defender'), 'ok');
      return;
    }

    // ── Player mon — Blank Set + manual field overrides ──────────────────────
    var blankId = species + ' (Blank Set)';
    ss.select2('data', { id: blankId, text: blankId, pokemon: species, set: 'Blank Set' })
      .trigger('change');

    // Select2's initSelection callback fires asynchronously and resets the
    // display back to the default.  Use select2('container') to directly
    // patch the visible label after the event loop clears.
    var displayLabel = mon.nickname && mon.nickname !== species
      ? species + ' (' + mon.nickname + ')'
      : species;
    setTimeout(function () {
      try { ss.select2('container').find('.select2-chosen').text(displayLabel); } catch (e) {}
    }, 0);

    // Step 2: Override with our mon's live data.
    if (mon.level) {
      pokeObj.find('.level').val(mon.level).trigger('change');
    }

    if (mon.nature) {
      var natSel = pokeObj.find('.nature');
      if (natSel.find('option[value="' + mon.nature + '"]').length) {
        natSel.val(mon.nature).trigger('change');
      }
    }

    if (mon.ability_name) {
      var ablSel = pokeObj.find('.ability');
      if (ablSel.find('option[value="' + mon.ability_name + '"]').length) {
        ablSel.val(mon.ability_name).trigger('change');
      }
    }

    if (mon.item_name) {
      var itmSel = pokeObj.find('.item');
      if (itmSel.find('option[value="' + mon.item_name + '"]').length) {
        itmSel.val(mon.item_name).trigger('change');
      }
    }

    // Moves: move-selector is a standard <select> wrapped by Select2,
    // so .val(name).trigger('change') works correctly.
    var moves = mon.moves || [];
    for (var i = 0; i < 4; i++) {
      var moveObj = pokeObj.find('.move' + (i + 1) + ' select.move-selector');
      var moveName = _normalizeMoveName(moves[i] || '(No Move)');
      moveObj.attr('data-prev', moveObj.val());
      moveObj.val(moveName);
      if (!moveObj.val()) moveObj.val('(No Move)'); // fallback if not found
      moveObj.trigger('change');
    }

    setTimeout(function () { _applyBattleState(pokeObj, mon); }, 0);

    showToast(
      '✓ ' + species + ' → ' + (side === 'p1' ? 'Attacker' : 'Defender'),
      'ok'
    );
  }

  // ---------------------------------------------------------------------------
  // Hash-based prefill
  //
  //   #slink-prefill=<base64>
  //   base64 decodes to two Showdown pastes separated by "\n---\n"
  //   → first paste → #p1 (attacker), second → #p2 (defender)
  // ---------------------------------------------------------------------------

  function processHashPrefill() {
    var hash = window.location.hash || '';
    if (hash.indexOf('#slink-prefill=') !== 0) return;

    try {
      var encoded = hash.slice('#slink-prefill='.length);
      var decoded = atob(encoded);
      var parts   = decoded.split('\n---\n');
      if (parts.length >= 1 && parts[0].trim()) _importPasteIntoSide(parts[0].trim(), 'p1');
      if (parts.length >= 2 && parts[1].trim()) _importPasteIntoSide(parts[1].trim(), 'p2');
    } catch (e) {
      showToast('⚠ Hash prefill decode failed: ' + e.message, 'error');
    }

    // Remove hash so page reloads don't repeat the import
    try {
      history.replaceState(null, '', window.location.pathname + window.location.search);
    } catch (e) { /* restricted environment */ }
  }

  function _importPasteIntoSide(paste, side) {
    var mon = _parsePasteToMon(paste);
    if (!mon) {
      showToast('⚠ Could not parse prefill paste.', 'error');
      return;
    }
    _loadMonIntoPanel(mon, side);
  }

  /**
   * Parse a Showdown paste into a mon object compatible with _loadMonIntoPanel.
   * Handles all common formats:
   *   "Charizard (NICKNAME) @ Charcoal\nAbility: Blaze\nLevel: 50\nAdamant Nature\n- Flamethrower\n..."
   */
  function _parsePasteToMon(paste) {
    var lines = (paste || '').split('\n');
    var line1 = (lines[0] || '').trim();

    // Extract species: strip nickname "(…)" then item "@ …"
    var species = line1.replace(/\s*\([^)]*\)/, '').replace(/@.*$/, '').trim();
    if (!species) return null;

    // Extract item from first line
    var item = '';
    var atIdx = line1.indexOf('@');
    if (atIdx >= 0) item = line1.slice(atIdx + 1).trim();

    var ability = '', level = 0, nature = '';
    var moves = [];

    for (var i = 1; i < lines.length; i++) {
      var l = lines[i].trim();
      if (!l) continue;
      if (l.indexOf('Ability: ') === 0) {
        ability = l.slice('Ability: '.length).trim();
      } else if (l.indexOf('Level: ') === 0) {
        level = parseInt(l.slice('Level: '.length), 10) || 0;
      } else if (l.slice(-7) === ' Nature') {
        nature = l.slice(0, l.length - 7).trim();
      } else if (l.indexOf('- ') === 0) {
        var m = l.slice(2).trim();
        if (m && m !== '(No Move)') moves.push(m);
      }
    }

    return {
      species_name: species,
      level:        level,
      nature:       nature,
      ability_name: ability,
      item_name:    item,
      moves:        moves,
      showdown_paste: paste,
    };
  }

  // ---------------------------------------------------------------------------
  // Toast notifications
  // ---------------------------------------------------------------------------

  function showToast(msg, type) {
    var bgColor = type === 'error' ? '#e94560'
                : type === 'warn'  ? '#c67c00'
                :                    '#0f3460';
    var el = ce('div');
    el.textContent = msg;
    css(el, {
      position    : 'fixed',
      bottom      : '80px',
      right       : '20px',
      zIndex      : '10000',
      background  : bgColor,
      color       : '#fff',
      padding     : '8px 14px',
      borderRadius: '4px',
      fontFamily  : 'monospace',
      fontSize    : '12px',
      maxWidth    : '340px',
      lineHeight  : '1.5',
      opacity     : '1',
      transition  : 'opacity 0.5s',
      pointerEvents: 'none',
      boxShadow   : '0 2px 8px rgba(0,0,0,0.5)',
    });
    document.body.appendChild(el);
    setTimeout(function () {
      el.style.opacity = '0';
      setTimeout(function () { el.parentNode && el.parentNode.removeChild(el); }, 600);
    }, 3500);
  }

  // ---------------------------------------------------------------------------
  // Panel skeleton (built once; content refreshed separately)
  // ---------------------------------------------------------------------------

  function buildPanel() {
    if (document.getElementById(PANEL_ID)) return;

    var panel = ce('div');
    panel.id  = PANEL_ID;
    css(panel, {
      position    : 'fixed',
      bottom      : '20px',
      right       : '20px',
      width       : '440px',
      background  : C.panelBg,
      border      : '1px solid ' + C.border,
      borderRadius: '6px',
      zIndex      : '9999',
      fontFamily  : 'monospace',
      fontSize    : '12px',
      color       : C.text,
      boxShadow   : '0 4px 24px rgba(0,0,0,0.7)',
      userSelect  : 'none',
    });

    // ── Header ────────────────────────────────────────────────────────────────
    var header = ce('div');
    header.id  = PANEL_ID + '-header';
    css(header, {
      background    : C.headerBg,
      borderBottom  : '1px solid ' + C.border,
      padding       : '6px 10px',
      display       : 'flex',
      alignItems    : 'center',
      justifyContent: 'space-between',
      cursor        : 'move',
      borderRadius  : '6px 6px 0 0',
    });

    var title = ce('span');
    title.textContent = '🔗 SLink Party';
    css(title, { fontWeight: 'bold', color: C.text, fontSize: '13px' });

    var toggleBtn = ce('button');
    toggleBtn.id  = PANEL_ID + '-toggle';
    toggleBtn.textContent = _isCollapsed() ? '▼' : '▲';
    css(toggleBtn, {
      background: 'transparent',
      border    : 'none',
      color     : C.text,
      cursor    : 'pointer',
      fontSize  : '14px',
      padding   : '0 4px',
      lineHeight: '1',
    });
    toggleBtn.onclick = toggleCollapse;

    header.appendChild(title);
    header.appendChild(toggleBtn);

    // ── Body (collapsible) ────────────────────────────────────────────────────
    var body = ce('div');
    body.id   = PANEL_ID + '-body';
    if (_isCollapsed()) body.style.display = 'none';

    panel.appendChild(header);
    panel.appendChild(body);
    document.body.appendChild(panel);

    // Restore saved position after panel is in the DOM so offsetWidth/Height
    // are accurate. Clamping here also fixes stale positions from smaller screens.
    var savedPos = _loadPos();
    if (savedPos) {
      panel.style.bottom = '';
      panel.style.right  = '';
      var clamped = _clampPos(savedPos.x, savedPos.y, panel);
      panel.style.left   = clamped.x + 'px';
      panel.style.top    = clamped.y + 'px';
    }

    initDrag(header, panel);

    // Re-clamp on window resize so the panel can never escape the viewport.
    window.addEventListener('resize', function () {
      if (!panel.style.left) return; // still using default bottom/right CSS
      var r = panel.getBoundingClientRect();
      var c = _clampPos(r.left, r.top, panel);
      panel.style.left = c.x + 'px';
      panel.style.top  = c.y + 'px';
      _savePos(c.x, c.y); // persist so reload doesn't restore the stale position
    });
  }

  // ---------------------------------------------------------------------------
  // Panel content refresh (called on every data update)
  // ---------------------------------------------------------------------------

  function refreshPanel() {
    var body = document.getElementById(PANEL_ID + '-body');
    if (!body) return;

    // Preserve scroll position across rebuilds
    var savedScroll = 0;
    var oldContent  = body.querySelector('div[data-slink-scroll]');
    if (oldContent) savedScroll = oldContent.scrollTop;

    body.innerHTML = '';
    if (_isCollapsed()) return;

    // Prep tab is available even without SLink data (it only needs the SETDEX)
    if (!_data && _activeTab !== 'prep') {
      var msg = ce('div');
      css(msg, { padding: '10px', textAlign: 'center', color: C.text, fontSize: '12px' });
      msg.textContent = _fetching ? '⟳ Connecting to SLink...' : '⚠ No data';
      body.appendChild(msg);

      // Still render tab row so user can switch to Prep
      var tabRowFallback = ce('div');
      css(tabRowFallback, { display: 'flex', borderBottom: '1px solid ' + C.border, marginBottom: '4px' });
      var prepTabFb = ce('button');
      css(prepTabFb, {
        flex: '1', padding: '7px 10px', background: 'transparent', border: 'none',
        color: C.text, cursor: 'pointer', fontFamily: 'monospace', fontSize: '12px',
      });
      prepTabFb.textContent = '📋 Prep';
      prepTabFb.onclick = function () { _activeTab = 'prep'; refreshPanel(); };
      tabRowFallback.appendChild(prepTabFb);
      body.insertBefore(tabRowFallback, msg);

      body.appendChild(_statusFooter());
      return;
    }

    // ── Tab row ───────────────────────────────────────────────────────────────
    var tabRow = ce('div');
    css(tabRow, { display: 'flex', borderBottom: '1px solid ' + C.border });

    ['a', 'b', 'prep'].forEach(function (side) {
      var isPrep = side === 'prep';
      var pd     = (!isPrep && _data) ? _data[side] : null;
      var badge  = !isPrep ? getDifficultyBadge(pd, side) : null;

      var tab = ce('button');
      css(tab, {
        flex          : '1',
        padding       : '7px 10px',
        background    : _activeTab === side ? C.activeTab : 'transparent',
        border        : 'none',
        borderRight   : side !== 'prep' ? '1px solid ' + C.border : 'none',
        color         : C.text,
        cursor        : 'pointer',
        fontFamily    : 'monospace',
        fontSize      : '12px',
        display       : 'flex',
        alignItems    : 'center',
        justifyContent: 'center',
        gap           : '6px',
      });

      var labelSpan = ce('span');
      if (isPrep) {
        labelSpan.textContent = '📋 Prep';
      } else {
        labelSpan.textContent = 'Player ' + side.toUpperCase();
        if (pd && pd.trainer_name) {
          labelSpan.textContent += ' (' + pd.trainer_name + ')';
        }
      }
      tab.appendChild(labelSpan);

      // Difficulty badge — only on the tab for the player currently in battle
      if (badge) {
        var badgeEl = ce('span');
        badgeEl.textContent = badge.mode === 'hardcore'
          ? 'HC ✓ ' + badge.matched + '/' + badge.total
          : 'Normal';
        css(badgeEl, {
          padding     : '1px 6px',
          borderRadius: '3px',
          background  : badge.mode === 'hardcore' ? '#c0392b' : '#27ae60',
          color       : '#fff',
          fontSize    : '10px',
          fontWeight  : 'bold',
        });
        tab.appendChild(badgeEl);
      }

      tab.onclick = (function (s) {
        return function () { _activeTab = s; refreshPanel(); };
      })(side);

      tabRow.appendChild(tab);
    });

    body.appendChild(tabRow);

    // ── Active tab content ────────────────────────────────────────────────────
    var content = ce('div');
    content.setAttribute('data-slink-scroll', '1');
    css(content, {
      padding  : '6px 8px',
      maxHeight: '420px',
      overflowY: 'auto',
    });

    if (_activeTab === 'prep') {
      _renderPrepTab(content);
      body.appendChild(content);
      content.scrollTop = savedScroll;  // restore scroll after appending to DOM
      body.appendChild(_statusFooter());
      return;
    }

    var pd      = _data[_activeTab];
    var hasContent = false;

    if (pd) {
      if (pd.party && pd.party.length > 0) {
        content.appendChild(_sectionHeader('⚔ Party'));
        var sortedParty = pd.party.slice().sort(function (a, b) {
          return (a.slot !== undefined ? a.slot : 999) - (b.slot !== undefined ? b.slot : 999);
        });
        sortedParty.forEach(function (mon) { content.appendChild(_monRow(mon, false, false)); });
        hasContent = true;
      }

      if (pd.enemy && pd.enemy.length > 0) {
        var oppLabel = pd.enemy[0].trainer_label || '';
        content.appendChild(_sectionHeader('🎯 ' + (oppLabel ? 'Enemy: ' + oppLabel : 'Enemy Battle')));
        pd.enemy.forEach(function (mon) {
          content.appendChild(_monRow(mon, mon.hp_pct === 0, true));
        });
        hasContent = true;
      }

      if (pd.linked && pd.linked.length > 0) {
        content.appendChild(_sectionHeader('🔗 Linked'));
        pd.linked.forEach(function (mon) {
          content.appendChild(_monRow(mon, mon.link_status === 'dead', false));
        });
        hasContent = true;
      }
    }

    if (!hasContent) {
      var empty = ce('div');
      empty.textContent = 'No data for this player yet.';
      css(empty, { color: C.dim, padding: '12px', textAlign: 'center' });
      content.appendChild(empty);
    }

    body.appendChild(content);
    content.scrollTop = savedScroll; // restore scroll position
    body.appendChild(_statusFooter());
  }

  // ── Section header ──────────────────────────────────────────────────────────

  function _sectionHeader(text) {
    var el = ce('div');
    el.textContent = text;
    css(el, {
      color        : C.dim,
      fontSize     : '10px',
      textTransform: 'uppercase',
      letterSpacing: '0.08em',
      padding      : '6px 0 2px',
      borderTop    : '1px solid ' + C.border,
      marginTop    : '4px',
    });
    return el;
  }

  // ---------------------------------------------------------------------------
  // Prep tab rendering
  // ---------------------------------------------------------------------------

  /**
   * Populate `container` with the Prep tab UI:
   *   [Normal] [Hardcore] mode toggle
   *   Search input with datalist
   *   Trainer party display with encounter sub-toggle
   */
  function _renderPrepTab(container) {
    var activeIndex = _pageIsHC ? _trainerIndex.hc : _trainerIndex.nm;

    // ── Custom search input with dropdown ───────────────────────────────────
    var listNames = _pageIsHC
      ? Object.keys(_trainerIndex.hc).sort()
      : Object.keys(_trainerIndex.nm).sort();

    var searchWrap = ce('div');
    css(searchWrap, { position: 'relative', marginBottom: '6px' });

    var searchInput = ce('input');
    searchInput.type        = 'text';
    searchInput.placeholder = 'Search trainer… (e.g. "rival blue" or "falkner")';
    searchInput.autocomplete = 'off';
    searchInput.value       = _prepTrainer;
    css(searchInput, {
      width        : '100%',
      boxSizing    : 'border-box',
      padding      : '5px 28px 5px 8px',
      background   : '#0d1a2e',
      border       : '1px solid ' + C.border,
      borderRadius : '3px',
      color        : C.text,
      fontFamily   : 'monospace',
      fontSize     : '12px',
      outline      : 'none',
    });

    var clearBtn = ce('button');
    clearBtn.textContent = '✕';
    css(clearBtn, {
      position  : 'absolute',
      right     : '5px',
      top       : '50%',
      transform : 'translateY(-50%)',
      background: 'transparent',
      border    : 'none',
      color     : C.dim,
      cursor    : 'pointer',
      fontSize  : '13px',
      padding   : '0',
      lineHeight: '1',
      display   : _prepTrainer ? 'block' : 'none',
    });
    clearBtn.onclick = function (e) {
      e.stopPropagation();
      _prepTrainer   = '';
      _prepEncounter = '';
      localStorage.removeItem('slink_prep_trainer');
      localStorage.removeItem('slink_prep_encounter');
      refreshPanel();
    };

    // Dropdown list
    var dropdownEl = ce('div');
    css(dropdownEl, {
      display     : 'none',
      position    : 'absolute',
      top         : '100%',
      left        : '0',
      right       : '0',
      zIndex      : '99999',
      background  : '#0d1a2e',
      border      : '1px solid ' + C.border,
      borderTop   : 'none',
      borderRadius: '0 0 3px 3px',
      maxHeight   : '220px',
      overflowY   : 'auto',
      boxShadow   : '0 4px 12px rgba(0,0,0,0.6)',
    });

    var ddHighlight = -1; // index of keyboard-highlighted item

    /** Return names matching all space-separated tokens (same logic as the calc set selector) */
    function filterNames(term) {
      if (!term) return listNames.slice(0, 30);
      var tokens = term.toUpperCase().split(/\s+/).filter(function (t) { return t; });
      return listNames.filter(function (n) {
        var up = n.toUpperCase();
        return tokens.every(function (tok) { return up.indexOf(tok) >= 0; });
      });
    }

    /** Wrap matching tokens in a red <mark> span (same style as the calc) */
    function hlHtml(name, term) {
      if (!term) return document.createTextNode(name);
      var frag = document.createDocumentFragment();
      var tokens = term.split(/\s+/).filter(function (t) { return t; });
      var re = new RegExp('(' + tokens.map(function (t) {
        return t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      }).join('|') + ')', 'gi');
      var parts = name.split(re);
      parts.forEach(function (part) {
        if (re.test(part)) {
          var mark = ce('mark');
          mark.textContent = part;
          css(mark, { background: C.btn, color: '#fff', borderRadius: '2px', padding: '0 2px' });
          frag.appendChild(mark);
        } else {
          frag.appendChild(document.createTextNode(part));
        }
      });
      return frag;
    }

    function buildDropdown(term) {
      dropdownEl.innerHTML = '';
      ddHighlight = -1;
      var matches = filterNames(term);
      if (!matches.length || (matches.length === 1 && matches[0] === term)) {
        dropdownEl.style.display = 'none';
        return;
      }
      matches.forEach(function (name, idx) {
        var item = ce('div');
        css(item, {
          padding   : '5px 8px',
          cursor    : 'pointer',
          fontFamily: 'monospace',
          fontSize  : '12px',
          color     : C.text,
          borderBottom: idx < matches.length - 1 ? '1px solid rgba(255,255,255,0.05)' : 'none',
        });
        item.appendChild(hlHtml(name, term));
        item.addEventListener('mousedown', function (e) {
          e.preventDefault(); // prevent input blur before we set value
          selectTrainer(name);
        });
        item.addEventListener('mouseenter', function () {
          setHighlight(idx);
        });
        dropdownEl.appendChild(item);
      });
      dropdownEl.style.display = 'block';
    }

    function setHighlight(idx) {
      var items = dropdownEl.children;
      if (ddHighlight >= 0 && items[ddHighlight]) {
        items[ddHighlight].style.background = '';
      }
      ddHighlight = idx;
      if (ddHighlight >= 0 && items[ddHighlight]) {
        items[ddHighlight].style.background = C.activeTab;
        // Scroll into view
        var el = items[ddHighlight];
        if (el.offsetTop < dropdownEl.scrollTop) {
          dropdownEl.scrollTop = el.offsetTop;
        } else if (el.offsetTop + el.offsetHeight > dropdownEl.scrollTop + dropdownEl.clientHeight) {
          dropdownEl.scrollTop = el.offsetTop + el.offsetHeight - dropdownEl.clientHeight;
        }
      }
    }

    function selectTrainer(name) {
      _prepTrainer   = name;
      _prepEncounter = '';
      localStorage.setItem('slink_prep_trainer', name);
      localStorage.removeItem('slink_prep_encounter');
      dropdownEl.style.display = 'none';
      refreshPanel();
    }

    searchInput.addEventListener('input', function () {
      var val = searchInput.value;
      clearBtn.style.display = val ? 'block' : 'none';
      buildDropdown(val.trim());
    });

    searchInput.addEventListener('keydown', function (e) {
      var items = dropdownEl.children;
      var count = items.length;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setHighlight(Math.min(ddHighlight + 1, count - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setHighlight(Math.max(ddHighlight - 1, 0));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (ddHighlight >= 0 && items[ddHighlight]) {
          selectTrainer(items[ddHighlight].textContent);
        } else {
          var val = searchInput.value.trim();
          if (activeIndex[val]) selectTrainer(val);
        }
      } else if (e.key === 'Escape') {
        dropdownEl.style.display = 'none';
      }
    });

    searchInput.addEventListener('focus', function () {
      if (searchInput.value && !activeIndex[searchInput.value.trim()]) {
        buildDropdown(searchInput.value.trim());
      }
    });

    searchInput.addEventListener('blur', function () {
      // Slight delay so mousedown on a dropdown item fires first
      setTimeout(function () { dropdownEl.style.display = 'none'; }, 150);
    });

    searchWrap.appendChild(searchInput);
    searchWrap.appendChild(clearBtn);
    searchWrap.appendChild(dropdownEl);
    container.appendChild(searchWrap);

    // ── Results area ─────────────────────────────────────────────────────────
    if (!_prepTrainer) {
      if (!_setdexReady) {
        var loading = ce('div');
        loading.textContent = '⟳ Loading trainer data…';
        css(loading, { color: C.dim, textAlign: 'center', padding: '12px', fontSize: '11px' });
        container.appendChild(loading);
      } else {
        var hint = ce('div');
        hint.textContent = 'Type a trainer name to see their party.';
        css(hint, { color: C.dim, textAlign: 'center', padding: '12px', fontSize: '11px' });
        container.appendChild(hint);
      }
      return;
    }

    var trEntry = activeIndex[_prepTrainer];

    if (!trEntry) {
      // The dropdown handles discovery; this only shows if user typed something
      // and committed (Enter) without selecting from the list.
      var noMatch = ce('div');
      noMatch.textContent = 'No trainer found for "' + _prepTrainer + '". Try a different search.';
      css(noMatch, { color: C.dim, textAlign: 'center', padding: '10px', fontSize: '11px' });
      container.appendChild(noMatch);
      return;
    }

    // ── Trainer found — encounter sub-toggle + party ──────────────────────────
    var encOrder = trEntry.encounterOrder;

    // Resolve active encounter: use saved label if valid, else first in order.
    // _prepEncounter defaults to '' which is falsy, so it falls back to encOrder[0].
    // When the user selects '__base__' it is stored literally and matched here.
    var encLabel = (_prepEncounter && trEntry.encounters[_prepEncounter] !== undefined)
      ? _prepEncounter
      : encOrder[0];

    if (encOrder.length > 1) {
      var encRow = ce('div');
      css(encRow, { display: 'flex', gap: '4px', marginBottom: '6px', flexWrap: 'wrap' });

      encOrder.forEach(function (lbl) {
        var mons    = trEntry.encounters[lbl] || [];
        var avgLvl  = mons.length
          ? Math.round(mons.reduce(function (s, m) { return s + (m.set.level || 0); }, 0) / mons.length)
          : 0;
        var dispLbl = lbl === '__base__' ? 'Base' : lbl;

        var btn = ce('button');
        btn.textContent = dispLbl + (avgLvl ? ' ~Lv' + avgLvl : '');
        css(btn, {
          padding     : '3px 8px',
          border      : '1px solid ' + C.border,
          borderRadius: '3px',
          cursor      : 'pointer',
          fontFamily  : 'monospace',
          fontSize    : '10px',
          background  : lbl === encLabel ? C.activeTab : 'transparent',
          color       : lbl === encLabel ? C.text : C.dim,
          fontWeight  : lbl === encLabel ? 'bold' : 'normal',
        });
        btn.onclick = (function (l) {
          return function () {
            _prepEncounter = l;
            localStorage.setItem('slink_prep_encounter', l);
            refreshPanel();
          };
        })(lbl);
        encRow.appendChild(btn);
      });

      container.appendChild(encRow);
    }

    var mons = trEntry.encounters[encLabel] || [];
    if (!mons.length) {
      var emptyEnc = ce('div');
      emptyEnc.textContent = 'No mons found for this encounter.';
      css(emptyEnc, { color: C.dim, padding: '10px', fontSize: '11px' });
      container.appendChild(emptyEnc);
      return;
    }

    mons.forEach(function (monEntry) {
      container.appendChild(_prepMonRow(monEntry, _prepTrainer));
    });
  }

  /**
   * Build a single mon row for the Prep tab.
   * Similar to _monRow but simpler — no HP bar, no active state.
   */
  function _prepMonRow(monEntry, baseName) {
    var species = monEntry.species;
    var set     = monEntry.set;

    var row = ce('div');
    var _downY = 0;
    css(row, {
      display      : 'flex',
      alignItems   : 'flex-start',
      gap          : '6px',
      padding      : '5px 2px',
      borderBottom : '1px solid rgba(255,255,255,0.05)',
      cursor       : 'pointer',
      borderLeft   : '2px solid transparent',
    });
    row.onmouseenter = function () { row.style.background = 'rgba(255,255,255,0.06)'; };
    row.onmouseleave = function () { row.style.background = ''; };
    row.onmousedown  = function (e) { _downY = e.clientY; };
    row.onclick = function (e) {
      if (Math.abs(e.clientY - _downY) > 6) return;
      e.stopPropagation();
      importMon({
        species_name: species,
        level       : set.level   || 50,
        nature      : set.nature  || 'Hardy',
        ability_name: set.ability || '',
        item_name   : set.item    || '',
        moves       : set.moves   || [],
        _matched_key: baseName,
      }, 'p2');
    };

    // ── Info block ────────────────────────────────────────────────────────────
    var info = ce('div');
    css(info, { flex: '1', minWidth: '0', lineHeight: '1.7' });

    // Line 1: name + meta tokens
    var line1 = ce('div');
    css(line1, { display: 'flex', flexWrap: 'wrap', gap: '5px', alignItems: 'baseline' });

    var nameEl = ce('span');
    nameEl.textContent = species;
    css(nameEl, {
      color      : '#ffd700',
      fontWeight : 'bold',
      maxWidth   : '140px',
      overflow   : 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace : 'nowrap',
    });
    line1.appendChild(nameEl);

    if (set.level) {
      var lvlEl = ce('span');
      lvlEl.textContent = 'Lv' + set.level;
      css(lvlEl, { color: C.dim, fontSize: '11px' });
      line1.appendChild(lvlEl);
    }

    if (set.nature) {
      var natEl = ce('span');
      natEl.textContent = set.nature;
      css(natEl, { color: C.nature, fontSize: '11px' });
      line1.appendChild(natEl);
    }

    if (set.ability) {
      var ablEl = ce('span');
      ablEl.textContent = set.ability;
      css(ablEl, { color: C.nature, fontSize: '11px' });
      line1.appendChild(ablEl);
    }

    if (set.item) {
      var itmEl = ce('span');
      itmEl.textContent = '@ ' + set.item;
      css(itmEl, { color: C.item, fontSize: '11px' });
      line1.appendChild(itmEl);
    }

    info.appendChild(line1);

    // Move chips
    if (set.moves && set.moves.length) {
      var moveLine = ce('div');
      css(moveLine, { display: 'flex', flexWrap: 'wrap', gap: '3px', marginTop: '2px' });
      set.moves.forEach(function (mv) {
        var chip = ce('span');
        chip.textContent = mv;
        css(chip, {
          background  : 'rgba(255,255,255,0.07)',
          borderRadius: '3px',
          padding     : '0 4px',
          fontSize    : '10px',
          color       : '#cde',
          whiteSpace  : 'nowrap',
        });
        moveLine.appendChild(chip);
      });
      info.appendChild(moveLine);
    }

    row.appendChild(info);

    return row;
  }

  // ── Battle-state helpers ────────────────────────────────────────────────────

  // Maps Gen 3 status condition bitmask to a calc status string.
  function _statusCondToCalc(sc) {
    if (!sc) return 'Healthy';
    if (sc & 0x7)  return 'Asleep';
    if (sc & 0x80) return 'Badly Poisoned'; // Toxic — check before plain PSN (bit 3)
    if (sc & 0x08) return 'Poisoned';
    if (sc & 0x10) return 'Burned';
    if (sc & 0x20) return 'Frostbitten';    // "Frozen" in the calc for all gens
    if (sc & 0x40) return 'Paralyzed';
    return 'Healthy';
  }

  // Returns a DOM line of stage chips for non-neutral stages, or null.
  // Only call when mon.active is true (stages only exist for the active battler).
  function _statStageBadges(stages) {
    if (!stages || !stages.length) return null;
    var labels = ['ATK', 'DEF', 'SPD', 'SATK', 'SDEF'];
    var wrap = null;
    for (var i = 0; i < 5; i++) {
      var raw = stages[i];
      if (typeof raw !== 'number') continue;
      var stage = raw - 6;
      if (stage === 0) continue;
      if (!wrap) {
        wrap = ce('div');
        css(wrap, { display: 'flex', flexWrap: 'wrap', gap: '3px', marginTop: '2px' });
      }
      var chip = ce('span');
      chip.textContent = (stage > 0 ? '+' : '') + stage + '\u00a0' + labels[i];
      css(chip, {
        background  : stage > 0 ? 'rgba(76,175,80,0.25)' : 'rgba(244,67,54,0.25)',
        color       : stage > 0 ? '#81c784' : '#e57373',
        borderRadius: '3px',
        padding     : '0 4px',
        fontSize    : '10px',
        whiteSpace  : 'nowrap',
      });
      wrap.appendChild(chip);
    }
    return wrap;
  }

  // Applies battle state (status, stat stages, HP) to a calc panel element.
  // Must be called from setTimeout(fn, 0) so it runs after the synchronous
  // set-selector change handler (which resets these fields).
  function _applyBattleState(pokeObj, mon) {
    // Status — always apply to override any item-auto-set (e.g. Flame Orb → Burned)
    var status = _statusCondToCalc(mon.status_cond || 0);
    pokeObj.find('.status').val(status).trigger('change');

    // Stat stages (only present for active battler; null for benched mons)
    var stageMap = ['.at', '.df', '.sp', '.sa', '.sd'];
    var stages = mon.stat_stages;
    if (stages) {
      for (var i = 0; i < 5; i++) {
        var raw = stages[i];
        if (typeof raw !== 'number') continue;
        var stage = raw - 6;
        if (stage === 0 || stage < -6 || stage > 6) continue;
        pokeObj.find(stageMap[i] + ' .boost').val(stage).trigger('change');
      }
    }

    // HP — use raw hp/maxHP for precision; skip fainted (hp=0) or full health
    var hp = mon.hp, maxHP = mon.maxHP;
    if (hp > 0 && maxHP > 0 && hp < maxHP) {
      var pct = Math.max(1, Math.round(hp / maxHP * 100));
      pokeObj.find('.percent-hp').val(pct).trigger('keyup');
    }
  }

  // ── Individual mon row ──────────────────────────────────────────────────────
  //   [sprite] NICKNAME / Species   Lv50  Timid  Blaze  @ Charcoal  [← Atk]  (enemy: [Def →])

  function _monRow(mon, isDead, isEnemy) {
    // Compute hp_pct if the API gave us raw hp/maxHP instead
    var hpPct = mon.hp_pct;
    if (hpPct === undefined && mon.hp !== undefined && mon.maxHP) {
      hpPct = Math.max(0, Math.round(100 * mon.hp / mon.maxHP));
    }

    var row = ce('div');
    var isPlayerActive = !isEnemy && mon.active;
    var side = isEnemy ? 'p2' : 'p1';
    css(row, {
      display    : 'flex',
      alignItems : 'center',
      gap        : '6px',
      padding    : '4px 2px',
      borderBottom: '1px solid rgba(255,255,255,0.05)',
      opacity    : isDead ? '0.4' : '1',
      transition : 'opacity 0.2s, background 0.1s',
      background : (mon.active) ? 'rgba(255,165,0,0.08)' : '',
      borderLeft : (mon.active) ? '2px solid #fa0' : '2px solid transparent',
      cursor     : mon.showdown_paste ? 'pointer' : 'default',
    });
    if (mon.showdown_paste) {
      var _downY = 0;
      row.onmouseenter = function () {
        if (!mon.active) row.style.background = 'rgba(255,255,255,0.06)';
      };
      row.onmouseleave = function () {
        row.style.background = mon.active ? 'rgba(255,165,0,0.08)' : '';
      };
      row.onmousedown = function (e) { _downY = e.clientY; };
      row.onclick = function (e) {
        if (Math.abs(e.clientY - _downY) > 6) return; // was a scroll drag
        e.stopPropagation();
        importMon(mon, side);
      };
    }

    // ── Sprite (32 × 32) ─────────────────────────────────────────────────────
    var spriteCell = ce('div');
    css(spriteCell, { width: '32px', height: '32px', flexShrink: '0', textAlign: 'center' });

    if (mon.sprite_html) {
      // Parse the <img> out of the server-provided HTML snippet
      var tmp = ce('div');
      tmp.innerHTML = mon.sprite_html;
      var img = tmp.querySelector('img');
      if (img) {
        css(img, { width: '32px', height: '32px', imageRendering: 'pixelated' });
        spriteCell.appendChild(img);
      }
    }
    row.appendChild(spriteCell);

    // ── Info block ────────────────────────────────────────────────────────────
    var info = ce('div');
    css(info, { flex: '1', minWidth: '0', lineHeight: '1.7' });

    // Line 1: name + meta tokens
    var line1 = ce('div');
    css(line1, { display: 'flex', flexWrap: 'wrap', gap: '5px', alignItems: 'baseline' });

    // Name: "NICKNAME / Species" or just "Species" if nickname matches
    var nameEl = ce('span');
    var hasDistinctNickname = mon.nickname && mon.nickname !== mon.species_name;
    nameEl.textContent = hasDistinctNickname
      ? mon.nickname + ' / ' + (mon.species_name || '')
      : (mon.species_name || '???');
    css(nameEl, {
      color       : isDead ? C.dim : '#ffd700',
      fontWeight  : 'bold',
      maxWidth    : '140px',
      overflow    : 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace  : 'nowrap',
    });
    line1.appendChild(nameEl);

    // Level (grey)
    if (mon.level) {
      var lvlEl = ce('span');
      lvlEl.textContent = 'Lv' + mon.level;
      css(lvlEl, { color: C.dim, fontSize: '11px' });
      line1.appendChild(lvlEl);
    }

    // Nature (warm)
    if (mon.nature) {
      var natEl = ce('span');
      natEl.textContent = mon.nature;
      css(natEl, { color: C.nature, fontSize: '11px' });
      line1.appendChild(natEl);
    }

    // Ability (warm)
    if (mon.ability_name) {
      var ablEl = ce('span');
      ablEl.textContent = mon.ability_name;
      css(ablEl, { color: C.nature, fontSize: '11px' });
      line1.appendChild(ablEl);
    }

    // Item (blue)
    if (mon.item_name) {
      var itmEl = ce('span');
      itmEl.textContent = '@ ' + mon.item_name;
      css(itmEl, { color: C.item, fontSize: '11px' });
      line1.appendChild(itmEl);
    }

    // Status badge (BRN / PSN / TOX / PAR / SLP / FRZ)
    var statusStr = _statusCondToCalc(mon.status_cond || 0);
    if (statusStr !== 'Healthy') {
      var STATUS_ABBR = {
        'Burned': 'BRN', 'Poisoned': 'PSN', 'Badly Poisoned': 'TOX',
        'Paralyzed': 'PAR', 'Asleep': 'SLP', 'Frostbitten': 'FRZ',
      };
      var STATUS_COLOR = {
        'Burned': '#e67e22', 'Poisoned': '#9b59b6', 'Badly Poisoned': '#6c3483',
        'Paralyzed': '#f1c40f', 'Asleep': '#95a5a6', 'Frostbitten': '#3498db',
      };
      var sbEl = ce('span');
      sbEl.textContent = STATUS_ABBR[statusStr] || statusStr;
      css(sbEl, {
        background  : STATUS_COLOR[statusStr] || '#666',
        color       : '#fff',
        borderRadius: '3px',
        padding     : '0 4px',
        fontSize    : '10px',
        fontWeight  : 'bold',
        whiteSpace  : 'nowrap',
      });
      line1.appendChild(sbEl);
    }

    info.appendChild(line1);

    // Move list (enemy mons only, when set data was matched)
    if (isEnemy && mon.moves && mon.moves.length) {
      var moveLine = ce('div');
      css(moveLine, { display: 'flex', flexWrap: 'wrap', gap: '3px', marginTop: '2px' });
      mon.moves.forEach(function (mv) {
        var chip = ce('span');
        chip.textContent = mv;
        css(chip, {
          background  : 'rgba(255,255,255,0.07)',
          borderRadius: '3px',
          padding     : '0 4px',
          fontSize    : '10px',
          color       : '#cde',
          whiteSpace  : 'nowrap',
        });
        moveLine.appendChild(chip);
      });
      // Difficulty badge on the move line
      if (mon._diff_mode) {
        var dBadge = ce('span');
        dBadge.textContent = mon._diff_mode === 'hardcore' ? 'HC' : 'NM';
        css(dBadge, {
          background  : mon._diff_mode === 'hardcore' ? '#c0392b' : '#27ae60',
          borderRadius: '3px',
          padding     : '0 4px',
          fontSize    : '10px',
          color       : '#fff',
          fontWeight  : 'bold',
          whiteSpace  : 'nowrap',
        });
        moveLine.appendChild(dBadge);
      }
      info.appendChild(moveLine);
    }

    // Stat stage chips (active battler only — stages are null for benched mons)
    if (mon.active && mon.stat_stages) {
      var stageLine = _statStageBadges(mon.stat_stages);
      if (stageLine) info.appendChild(stageLine);
    }

    // HP bar (if available)
    if (hpPct !== undefined && hpPct !== null) {
      info.appendChild(_hpBar(hpPct));
    }

    row.appendChild(info);

    return row;
  }

  // ── HP bar ──────────────────────────────────────────────────────────────────

  function _hpBar(pct) {
    pct = Math.max(0, Math.min(100, pct));
    var color = pct > 50 ? C.hpGreen : pct > 20 ? C.hpYellow : C.hpRed;

    var track = ce('div');
    css(track, {
      background  : 'rgba(255,255,255,0.1)',
      borderRadius: '2px',
      height      : '4px',
      marginTop   : '3px',
      overflow    : 'hidden',
    });

    var fill = ce('div');
    css(fill, {
      background  : color,
      height      : '100%',
      width       : pct + '%',
      borderRadius: '2px',
      transition  : 'width 0.3s',
    });
    track.appendChild(fill);
    return track;
  }

  // ── Button factory ──────────────────────────────────────────────────────────

  function _actionBtn(label, mon, side) {
    var btn = ce('button');
    btn.textContent = label;
    css(btn, {
      background  : C.btn,
      border      : 'none',
      color       : '#fff',
      padding     : '3px 7px',
      cursor      : 'pointer',
      borderRadius: '3px',
      fontFamily  : 'monospace',
      fontSize    : '10px',
      whiteSpace  : 'nowrap',
    });
    btn.disabled = _fetching;
    if (_fetching) css(btn, { opacity: '0.5', cursor: 'not-allowed' });
    btn.onclick = function (e) {
      e.stopPropagation();
      importMon(mon, side);
    };
    return btn;
  }

  // ── Status footer ───────────────────────────────────────────────────────────

  function _statusFooter() {
    var el = ce('div');
    css(el, {
      padding  : '5px 10px',
      borderTop: '1px solid ' + C.border,
      fontSize : '11px',
      color    : _connected ? '#4caf50' : '#e94560',
      textAlign: 'center',
    });
    el.textContent = _connected
      ? '🔗 SLink connected'
      : '⚠ SLink not connected (retrying...)';
    return el;
  }

  // ---------------------------------------------------------------------------
  // Collapse / expand
  // ---------------------------------------------------------------------------

  function _isCollapsed() {
    return localStorage.getItem(LS_COL) === '1';
  }

  function toggleCollapse() {
    var nowCollapsed = !_isCollapsed();
    localStorage.setItem(LS_COL, nowCollapsed ? '1' : '0');

    var body  = document.getElementById(PANEL_ID + '-body');
    var btn   = document.getElementById(PANEL_ID + '-toggle');
    if (body) body.style.display   = nowCollapsed ? 'none' : '';
    if (btn)  btn.textContent      = nowCollapsed ? '▼'    : '▲';
    if (!nowCollapsed) refreshPanel(); // rebuild content on expand
  }

  // ---------------------------------------------------------------------------
  // Drag-to-reposition
  // ---------------------------------------------------------------------------

  function initDrag(handle, panel) {
    var ox, oy, ol, ot;

    handle.addEventListener('mousedown', function (e) {
      if (e.target.tagName === 'BUTTON') return; // don't intercept toggle btn
      e.preventDefault();

      // Convert bottom/right CSS to left/top so we can offset from there
      var r = panel.getBoundingClientRect();
      panel.style.left   = r.left + 'px';
      panel.style.top    = r.top  + 'px';
      panel.style.bottom = '';
      panel.style.right  = '';

      ox = e.clientX; oy = e.clientY;
      ol = r.left;    ot = r.top;

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup',   onUp);
    });

    function onMove(e) {
      var c = _clampPos(ol + e.clientX - ox, ot + e.clientY - oy, panel);
      panel.style.left = c.x + 'px';
      panel.style.top  = c.y + 'px';
    }

    function onUp() {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup',   onUp);
      var r = panel.getBoundingClientRect();
      _savePos(r.left, r.top);
    }
  }

  function _savePos(x, y) {
    try {
      localStorage.setItem(LS_POS, JSON.stringify({ x: Math.round(x), y: Math.round(y) }));
    } catch (e) { /* storage unavailable */ }
  }

  /** Clamp panel position so it stays fully within the viewport. */
  function _clampPos(x, y, panel) {
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var pw = panel.offsetWidth  || 440;
    var ph = panel.offsetHeight || 50;
    // Keep panel fully visible; if viewport is narrower than panel, pin to 0.
    x = Math.max(0, Math.min(Math.max(0, vw - pw), x));
    y = Math.max(0, Math.min(Math.max(0, vh - ph), y));
    return { x: x, y: y };
  }

  function _loadPos() {
    try {
      var v = localStorage.getItem(LS_POS);
      if (!v) return null;
      var p = JSON.parse(v);
      if (typeof p.x === 'number' && typeof p.y === 'number') return p;
    } catch (e) {}
    return null;
  }

  // ---------------------------------------------------------------------------
  // Network: fetch + SSE (with polling fallback)
  // ---------------------------------------------------------------------------

  /** Fetch latest mon data; update _data and _connected; re-render. */
  function fetchMons() {
    _fetching = true;
    return fetch(SLINK_BASE + '/api/calc/mons')
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (json) {
        _fetching  = false;
        _data      = json;
        _connected = true;
        _enrichEnemyMons();
        // Don't repaint while the user is typing inside the panel.
        if (_isPanelInputFocused()) { _fetchPending = true; return; }
        refreshPanel();
      })
      .catch(function (err) {
        _fetching  = false;
        _connected = false;
        if (!_isPanelInputFocused()) refreshPanel();
        return Promise.reject(err);
      });
  }

  // Interaction guard: pause SSE-triggered fetches while the mouse is held
  // down (click guard) or while the user is scrolling the panel (wheel guard),
  // so a ping cannot repaint the panel mid-interaction.
  function _armInteraction() {
    _userInteracting = true;
    if (_interactionTimer) { clearTimeout(_interactionTimer); _interactionTimer = null; }
  }
  function _releaseInteraction() {
    _interactionTimer = setTimeout(function () {
      _userInteracting = false;
      _interactionTimer = null;
      if (_fetchPending) { _fetchPending = false; fetchMons(); }
    }, 250);
  }

  document.addEventListener('mousedown', _armInteraction);
  document.addEventListener('mouseup',   _releaseInteraction);

  // Wheel guard: scrolling the panel replaces the DOM element under the cursor,
  // which stops wheel events mid-scroll.  Pause rebuilds while wheel is active.
  document.addEventListener('wheel', function (e) {
    var panel = document.getElementById(PANEL_ID);
    if (panel && panel.contains(e.target)) {
      _armInteraction();
      _releaseInteraction();
    }
  }, { passive: true });

  // Typing guard: don't wipe the panel while the user is typing in an input
  // inside it (e.g. the Prep tab search box).
  function _isPanelInputFocused() {
    var ae = document.activeElement;
    if (!ae) return false;
    var tag = ae.tagName;
    if (tag !== 'INPUT' && tag !== 'TEXTAREA') return false;
    var panel = document.getElementById(PANEL_ID);
    return !!(panel && panel.contains(ae));
  }

  // When the input loses focus, flush any deferred fetch.
  document.addEventListener('focusout', function (e) {
    var panel = document.getElementById(PANEL_ID);
    if (!panel || !panel.contains(e.target)) return;
    var tag = e.target.tagName;
    if (tag !== 'INPUT' && tag !== 'TEXTAREA') return;
    // Small delay so the new focus settles before we re-check.
    setTimeout(function () {
      if (!_isPanelInputFocused() && _fetchPending) {
        _fetchPending = false;
        fetchMons();
      }
    }, 100);
  });

  /**
   * Subscribe to /api/events SSE.  Re-fetches /api/calc/mons on every ping.
   * If SSE errors out, schedules a retry after 10 s.
   * If EventSource is unavailable, falls back to 5 s polling.
   */
  function startSSE() {
    if (typeof EventSource === 'undefined') {
      console.warn('[SLink bridge] EventSource not supported — falling back to 5 s polling.');
      _pollFallback();
      return;
    }

    if (_sseSource) { _sseSource.close(); _sseSource = null; }

    var src   = new EventSource(SLINK_BASE + '/api/events');
    _sseSource = src;

    // Re-fetch on each state change signal — defer if user is interacting or typing
    src.addEventListener('ping',   function () { (_userInteracting || _isPanelInputFocused()) ? (_fetchPending = true) : fetchMons(); });
    src.addEventListener('status', function () { (_userInteracting || _isPanelInputFocused()) ? (_fetchPending = true) : fetchMons(); }); // belt-and-suspenders

    src.onerror = function () {
      src.close();
      _sseSource = null;
      _connected = false;
      refreshPanel();

      // Retry: fetch once to check liveness, then restart SSE if successful
      clearTimeout(_retryTimer);
      _retryTimer = setTimeout(function () {
        fetchMons().then(startSSE).catch(startSSE);
      }, 10000);
    };
  }

  /** Polling fallback for browsers without EventSource support. */
  function _pollFallback() {
    fetchMons()
      .catch(function () {})
      .then(function () {
        setTimeout(_pollFallback, 5000);
      });
  }

  // ---------------------------------------------------------------------------
  // DOM helpers
  // ---------------------------------------------------------------------------

  /** Create an element, optionally setting HTML attributes from an object. */
  function ce(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) { el.setAttribute(k, attrs[k]); });
    }
    return el;
  }

  /** Apply a plain-object style map to an element. */
  function css(el, styles) {
    Object.keys(styles).forEach(function (k) { el.style[k] = styles[k]; });
  }

  // ---------------------------------------------------------------------------
  // Initialisation
  // ---------------------------------------------------------------------------

  function init() {
    buildPanel();
    initSetdex();
    processHashPrefill();
    // Initial fetch; start SSE regardless of whether it succeeds
    fetchMons().then(startSSE).catch(startSSE);
  }

  // Run after DOM is ready (handles both inline <script> and deferred loading)
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
