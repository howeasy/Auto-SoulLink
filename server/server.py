"""
SLink TCP server — Soul Link Nuzlocke coordinator.

Each BizHawk instance connects via LuaSocket and sends newline-delimited JSON
events (area_enter, capture, faint, etc.).  The server responds with a
newline-delimited JSON object: {"commands": [...]}.

A separate HTTP status page is served on --http-port (default 8080) for
live monitoring in a browser.

Transport: asyncio.start_server for the game protocol (no aiohttp on that path).
Status UI:  aiohttp on a separate port — browser-only, never touched by Lua.

Run:
    python -m server.server [--host 0.0.0.0] [--port 54321] [--http-port 8080]
"""

import asyncio
import json
import logging
import logging.handlers
import argparse
import os
import re
import html
import shutil
import mimetypes
from collections import deque
from datetime import datetime

from server.stream_overlays import (
    _stream_overlay_page,
    _STREAM_PARTY_JS,
    _STREAM_ENEMY_FOCUS_JS,
    _STREAM_ENEMY_TRAINER_JS,
    _STREAM_LINKS_JS,
    _STREAM_LINKED_PARTY_JS,
    _STREAM_BOXED_LINKS_JS,
    _STREAM_DEATHS_JS,
    _STREAM_ATTEMPTS_JS,
    _STREAM_AREAS_JS,
    _STREAM_EVENTS_JS,
    _STREAM_BADGES_JS,
    _STREAM_ENCOUNTERS_JS,
    _STREAM_MEMORIAL_JS,
    _STREAM_TICKER_JS,
    _STREAM_FOCUS_JS,
    _STREAM_AREA_ENCOUNTER_JS,
    _STREAM_ENC_TABLE_JS,
    _STREAM_INDEX_HTML,
    _MEMORIAL_HTML,
)

try:
    from aiohttp import web as aiohttp_web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

try:
    from .state import SoulLinkState, LINKS_PATH, DATA_DIR
    from .pokemon_data import (
        GENDER_SYMBOL as _GENDER_SYMBOL,
    )
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from server.state import SoulLinkState, LINKS_PATH, DATA_DIR
    from server.pokemon_data import (
        GENDER_SYMBOL as _GENDER_SYMBOL,
    )

try:
    from .obs_controller import OBSController, obs_config_path, ALL_TRIGGER_EVENTS
except ImportError:
    from server.obs_controller import OBSController, obs_config_path, ALL_TRIGGER_EVENTS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

VALID_PLAYERS = {"a", "b"}
_EVENTS_MAX = 200  # max entries kept in memory and written to events.json


def _configure_logging(data_dir: str | None, verbose: bool) -> None:
    """Add a RotatingFileHandler next to links.json.

    Without ``--verbose``: both file and console stay at INFO.
    With    ``--verbose``: file and console are both lowered to DEBUG so every
    state-machine decision is captured for post-mortem analysis.
    """
    log_dir = data_dir if data_dir else DATA_DIR
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "slink.log")

    fh = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG if verbose else logging.INFO)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    root = logging.getLogger()
    root.addHandler(fh)

    if verbose:
        root.setLevel(logging.DEBUG)
        # Also lower the existing console StreamHandler so DEBUG appears on screen.
        for h in root.handlers:
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.handlers.RotatingFileHandler):
                h.setLevel(logging.DEBUG)
        log.info(f"[--verbose] DEBUG logging enabled → {log_path}")
    else:
        log.info(f"Logging to {log_path}")



from server.html_render import (
    TYPE_COLOR as _TYPE_COLOR,
    SPLIT_ICONS as _SPLIT_ICONS,
    STAT_STAGE_LABELS as _STAT_STAGE_LABELS,
    type_badges_html as _type_badges_html,
    move_table_html as _move_table_html,
    status_icon_html as _status_icon_html,
    stat_stages_html as _stat_stages_html,
)


# ── Damage Calculator integration ────────────────────────────────────────────

_CALC_DIST_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "calc", "dist")

_NATURE_NAMES = (
    "Hardy","Lonely","Brave","Adamant","Naughty",
    "Bold","Docile","Relaxed","Impish","Lax",
    "Timid","Hasty","Serious","Jolly","Naive",
    "Modest","Mild","Quiet","Bashful","Rash",
    "Calm","Gentle","Sassy","Careful","Quirky",
)

def _nature_from_key(key: str) -> str:
    """Derive nature name from a monKey ('PERS_HEX:OTID_HEX...')."""
    try:
        return _NATURE_NAMES[int(key.split(":")[0], 16) % 25]
    except Exception:
        return "Hardy"




def _build_mon_entry(key, detail, adapter):
    """Build a JSON-serialisable dict for one mon, suitable for /api/calc/mons."""
    sid = detail.get("species_id", 0)
    if not sid:
        return None
    species = adapter.species_name(sid)
    nature   = _nature_from_key(key)
    abl_name = detail.get("ability_name", "") or adapter.ability_name(detail.get("ability_id", 0), sid)
    item_id  = detail.get("held_item_id", 0)
    item     = adapter.item_name(item_id) if item_id else ""
    raw_moves = [m for m in (detail.get("moves") or []) if m][:4]
    moves = []
    for m in raw_moves:
        if isinstance(m, int):
            name = adapter.move_name(m)
            if name:
                moves.append(name)
        elif isinstance(m, str) and m:
            moves.append(m)
    level    = detail.get("level", 0)
    nick     = detail.get("nickname", "")
    hp       = detail.get("hp", 0)
    maxhp    = max(detail.get("maxHP", 1), 1)
    hp_pct   = max(0, min(100, int(hp / maxhp * 100)))
    disp     = f"{species} ({nick})" if nick and nick != species else species
    lines    = [disp + (f" @ {item}" if item else "")]
    lines   += [f"Ability: {abl_name}" if abl_name else "Ability: None"]
    lines   += [f"Level: {level}", f"{nature} Nature"]
    for m in moves:
        lines.append(f"- {m}")
    return {
        "key":           key,
        "nickname":      nick,
        "species_name":  species,
        "level":         level,
        "nature":        nature,
        "ability_name":  abl_name,
        "item_name":     item,
        "moves":         moves,
        "hp_pct":        hp_pct,
        "hp":            hp,
        "maxHP":         maxhp,
        "status_cond":   detail.get("status_cond", 0),
        "stat_stages":   detail.get("stat_stages"),
        "slot":          detail.get("slot", 999),
        "active":        detail.get("active", False),
        "showdown_paste": "\n".join(lines),
    }


# ── Inline damage-preview widget (lazy-loaded on the status page) ───────────
# Uses the calc engine served at /calc/ — silent no-op if not built.
# Raw string so no {{ }} escaping needed.
_CALC_PREVIEW_JS = r"""
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

  // Called by doRefresh() after each morphDOM
  window._slinkCalcRender = function () { checkAndInit(); _renderAll(); };

  checkAndInit();
  return { renderAll: _renderAll, checkAndInit: checkAndInit };
})();
"""


_STATUS_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{page_title}</title>
  <style>
    body {{ font-family: monospace; font-size: 20px; background: #111; color: #eee; padding: 1em; margin: 0 auto; max-width: 2400px; }}
    h1 {{ color: #ff0; margin-bottom: 0.2em; }}
    h2 {{ color: #0af; margin-top: 2em; margin-bottom: 0.5em; }}
    h3 {{ color: #eee; margin: 0 0 0.4em 0; font-size: 1.05em; }}
    p.sub {{ color: #888; margin: 0 0 1em 0; font-size: 0.9em; }}
    .players-grid {{ display: flex; gap: 2em; flex-wrap: wrap; margin-bottom: 1.5em; }}
    .player-card {{ flex: 1; min-width: 300px; background: #1a1a1a; border: 1px solid #333; padding: 1.2em 1.4em; border-radius: 4px; overflow-x: auto; }}
    .player-card.online {{ border-color: #4f4; }}
    .player-card.offline {{ border-color: #555; opacity: 0.75; }}
    .card-hdr {{ display: flex; justify-content: space-between; align-items: flex-start; }}
    .card-hdr h3 {{ margin: 0 0 0.4em 0; }}
    .launcher-dl {{ color: #667; font-size: 0.9em; text-decoration: none; padding: 2px 4px; border-radius: 3px; }}
    .launcher-dl:hover {{ color: #6af; background: #1a2a3a; }}
    .badge {{ display: inline-block; padding: 2px 7px; border-radius: 3px; font-size: 0.85em; margin-left: 0.5em; }}
    .badge-online {{ background: #1a3a1a; color: #4f4; }}
    .badge-offline {{ background: #2a2a2a; color: #888; }}
    .badge-active {{ background: #1a3a1a; color: #4f4; }}
    .badge-waiting {{ background: #2a1a00; color: #fa0; }}
    .badge-lock {{ background: #1a2a3a; color: #6af; font-size: 0.85em; padding: 2px 8px; border-radius: 10px; }}
    .badge-bonus {{ background: #2a2000; color: #ffd700; }}
    .dbl-chip {{ background: #663; color: #ffa; font-size: .75em; padding: 1px 5px; border-radius: 3px; font-weight: bold; margin-left: 0.4em; }}
    .bonus-pair-row td {{ background: #1a1500; }}
    .bonus-pair-row td:first-child {{ border-left: 3px solid #ffd700; padding-left: 5px; }}
    .gym-badges {{ display: inline-flex; gap: 3px; margin-left: 0.7em; vertical-align: middle; }}
    .gym-badge {{ width: 16px; height: 16px; border-radius: 50%; display: inline-block; border: 1px solid #555; opacity: 0.25; cursor: default; }}
    .gym-badge.earned {{ opacity: 1; border-color: #fff8; box-shadow: 0 0 4px #fff4; }}
    .lock-rules {{ margin: 0.5em 0 0.8em 0; font-size: 0.95em; color: #ccc; }}
    .attempts-bar {{ display: inline-flex; align-items: center; gap: 0.5em; margin: 0.3em 0 0.8em 0; font-size: 0.9em; color: #888; }}
    .attempts-num {{ color: #f8d030; font-weight: bold; }}
    .adj-btn {{ background: #1a1c28; color: #f8d030; border: 1px solid #444; border-radius: 3px; padding: 1px 8px; cursor: pointer; font-size: 0.95em; line-height: 1.6; font-family: inherit; }}
    .adj-btn:hover {{ background: #2a2c38; border-color: #f8d030; }}
    .info-row {{ display: flex; gap: 2em; margin: 0.5em 0 0.35em 0; font-size: 0.9em; color: #aaa; }}
    .info-row span b {{ color: #eee; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 1em; table-layout: auto; }}
    th {{ background: #222; color: #ff0; padding: 5px 8px; text-align: left; border-bottom: 1px solid #444; font-size: 0.8em; white-space: nowrap; }}
    td {{ padding: 5px 8px; border-bottom: 1px solid #1e1e1e; font-size: 0.82em; }}
    tr:hover td {{ background: #222; }}
    .alive    {{ color: #4f4; }}
    .dead     {{ color: #f44; }}
    .dead_zone {{ color: #f44; }}
    .pending_a, .pending_b, .pending_both, .pending {{ color: #fa0; }}
    .unseen   {{ color: #666; }}
    .yes      {{ color: #4f4; }}
    .no       {{ color: #888; }}
    .empty    {{ color: #666; font-style: italic; }}
    .warn     {{ color: #fa0; }}
    .fainted  {{ color: #f44; opacity: 0.7; }}
    .dim      {{ color: #666; }}
    .area     {{ color: #7cf; }}
    .gender-male   {{ color: #6af; }}
    .gender-female {{ color: #f9a; }}
    .shiny-star    {{ color: #FFD700; }}
    .killfeed-cause {{ }}
    .kf-inline  {{ font-size: 0.84em; }}
    .kf-battle  {{ color: #f88; }}
    .kf-dead_zone {{ color: #f44; }}
    .kf-whiteout  {{ color: #f80; }}
    .kf-unknown   {{ color: #666; }}
    .battle-panel {{ background: #1a1000; border: 1px solid #a60; border-radius: 4px; padding: 0.8em 1.1em; margin: 0.9em 0 0.9em 0; }}
    .battle-panel h4 {{ color: #fa0; }}
    .calc-preview {{ background: #0d1a00; border: 1px solid #6a0; border-radius: 3px; padding: 0.5em 0.8em; margin: 0.6em 0 0; }}
    .calc-preview h5 {{ color: #8f4; margin: 0 0 0.4em; font-size: 0.9em; }}
    .calc-preview-table {{ width: 100%; border-collapse: collapse; font-size: 0.82em; }}
    .calc-preview-table th {{ background: #1a2a0a; color: #8f4; padding: 2px 7px; text-align: left; border-bottom: 1px solid #3a4a2a; }}
    .calc-preview-table td {{ padding: 2px 7px; border-bottom: 1px solid #1a2a0a; }}
    .calc-preview-table .ohko   {{ color: #f44; font-weight: bold; }}
    .calc-preview-table .twohko {{ color: #fa0; }}
    .calc-open-btn {{ display: inline-block; margin-top: 0.5em; padding: 2px 9px; background: #0d1020; color: #6af; border: 1px solid #48a; border-radius: 3px; text-decoration: none; font-size: 0.82em; }}
    .calc-open-btn:hover {{ background: #1a2040; }}
    .hp-bar-bg {{ display:inline-block; width:70px; height:7px; background:#333; border-radius:3px; vertical-align:middle; margin-right:3px; }}
    .hp-bar    {{ height:7px; border-radius:3px; }}
    .hp-high   {{ background:#4f4; }}
    .hp-mid    {{ background:#fa0; }}
    .hp-low    {{ background:#f44; }}
    .foe-table td {{ padding: 2px 6px; border-bottom: 1px solid #1e1e1e; }}
    .foe-table th {{ padding: 2px 6px; }}
    .foe-moves-row > td {{ padding: 0 6px 4px 38px; border-bottom: 1px solid #1e1e1e; }}
    .foe-moves-row .move-table {{ margin: 0; }}
    .active-foe td:nth-child(2) {{ color: #ff0; }}
    .active-mon td:first-child {{ color: #ff0; }}
    .mon-sprite {{ width:48px; height:48px; image-rendering:pixelated; vertical-align:middle; margin:-2px 2px -2px 0; clip-path:inset(2px); }}
    .held-item {{ color:#adf; font-size:0.80em; display:block; margin-top:0.1em; }}
    .held-item::before {{ content:"ITEM: "; color:#778; font-weight:600; }}
    .ability {{ color:#cba; font-size:0.82em; }}
    .status-icon {{ display:inline-block; padding:1px 5px; border-radius:3px; font-size:0.75em;
      font-weight:bold; white-space:nowrap; vertical-align:middle; margin-left:3px; }}
    .s-slp {{ background:#7a7a7a; color:#fff; }}
    .s-psn {{ background:#c040c0; color:#fff; }}
    .s-brn {{ background:#d06020; color:#fff; }}
    .s-frz {{ background:#5ab8e4; color:#fff; }}
    .s-par {{ background:#c8a800; color:#000; }}
    .s-tox {{ background:#6a00aa; color:#fff; }}
    .stat-stage {{ display:inline-block; padding:1px 6px; border-radius:3px; font-size:0.75em;
      font-weight:bold; white-space:nowrap; vertical-align:middle; margin-left:3px;
      border:1px solid; }}
    .ss-up {{ background:rgba(46,204,113,0.15); color:#5af09a; border-color:rgba(46,204,113,0.55); }}
    .ss-dn {{ background:rgba(231,76,60,0.15); color:#ff7f72; border-color:rgba(231,76,60,0.55); }}
    .sortable {{ cursor:pointer; user-select:none; position:relative; padding-right:14px !important; }}
    .sortable:hover {{ color:#fff; }}
    .sortable::after {{ content:"⇅"; position:absolute; right:2px; font-size:0.75em; opacity:0.4; }}
    .sortable.sort-asc::after {{ content:"▲"; opacity:0.9; }}
    .sortable.sort-desc::after {{ content:"▼"; opacity:0.9; }}
    .enc-filters {{ margin: 0.4em 0; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }}
    .filter-label {{ color: #888; font-size: 0.85em; margin-right: 2px; }}
    .filter-btn {{ background: #222; color: #aaa; border: 1px solid #444; border-radius: 3px; padding: 3px 10px; font-size: 0.85em; font-family: monospace; cursor: pointer; }}
    .filter-btn:hover {{ color: #fff; border-color: #666; }}
    .filter-btn.active {{ background: #1a2a3a; color: #6af; border-color: #6af; }}
    .event-type-capture {{ color: #4f4; }}
    .event-type-faint {{ color: #f44; }}
    .event-type-whiteout {{ color: #f80; }}
    .event-type-no_catch {{ color: #fa0; }}
    .event-type-area_enter {{ color: #7cf; }}
    .event-type-hello {{ color: #aaa; }}
    .event-type-linked {{ color: #4f4; font-weight: bold; }}
    .event-type-dead_zone {{ color: #f44; font-weight: bold; }}
    .event-type-force_faint {{ color: #f88; }}
    .event-type-key_change {{ color: #c8f; }}
    .event-type-violation {{ color: #f80; font-weight: bold; }}
    .event-type-reroll {{ color: #8cf; }}
    .event-type-shiny {{ color: #f8d030; font-weight: bold; }}
    .event-type-memorialize {{ color: #aaa; opacity: .35; }}
    .event-type-party_to_box {{ color: #60a8f8; }}
    .event-type-box_to_party {{ color: #60a8f8; }}
    /* ── Move table (collapsible) ───────────────────────────── */
    .move-row td {{ padding: 0 !important; }}
    .move-row details {{ margin: 0; padding-left: 8px; max-width: 80%; }}
    .move-row summary {{ cursor: pointer; padding: 2px 8px; font-size: 0.9em; color: #888;
      user-select: none; list-style: none; }}
    .move-row summary::-webkit-details-marker {{ display: none; }}
    .move-row summary::before {{ content: "▶ "; font-size: 0.7em; }}
    .move-row[open] summary::before,
    .move-row details[open] summary::before {{ content: "▼ "; font-size: 0.7em; }}
    .move-table {{ width: 100%; border-collapse: collapse; margin: 2px 0; font-size: 0.92em; }}
    .move-table th {{ background: #222; padding: 1px 5px; font-size: 0.88em; color: #999;
      text-align: left; border-bottom: 1px solid #333; }}
    .move-table td {{ padding: 1px 5px; border-bottom: 1px solid #222; }}
    .move-table .move-name {{ font-weight: 600; white-space: nowrap; }}
    .move-table .type-badge {{ display: inline-block; padding: 1px 5px; border-radius: 3px;
      font-size: 0.82em; font-weight: bold; color: #fff; text-transform: uppercase;
      text-shadow: 1px 1px rgba(0,0,0,0.5); white-space: nowrap; }}
    .split-icon {{ height: 18px; vertical-align: middle; }}
    .split-physical {{ filter: brightness(200%); }}
    .split-special {{ filter: brightness(200%); }}
    .split-status {{ filter: brightness(300%); }}
    .move-table .pp-cell {{ white-space: nowrap; }}
    .move-table .pp-low {{ color: #fa0; }}
    .move-table .pp-zero {{ color: #f44; }}
    .move-table .mv-pwr, .move-table .mv-acc {{ text-align: center; }}
    /* ── Encounter widget ────────────────────────────────────── */
    .enc-widget summary, .area-enc-details summary {{
      cursor: pointer; list-style: none; user-select: none;
      color: #667; font-size: 0.78em; padding: 1px 0; }}
    .enc-widget summary::-webkit-details-marker,
    .area-enc-details summary::-webkit-details-marker {{ display: none; }}
    .enc-widget summary::before, .area-enc-details summary::before
      {{ content: "▶ "; font-size: 0.7em; }}
    .enc-widget[open] summary::before, .area-enc-details[open] summary::before
      {{ content: "▼ "; font-size: 0.7em; }}
    .enc-widget:hover summary {{ color: #99b; }}
    .enc-widget[open] summary {{ color: #88a; }}
    .enc-widget {{ margin: 0 0 0.9em; }}
    .enc-methods {{ display: flex; flex-wrap: wrap; gap: 0.3em 1.2em;
      padding: 0.3em 0.5em 0.1em; }}
    .enc-method {{ min-width: 155px; }}
    .enc-method-label {{ color: #999; font-size: 0.78em; font-weight: bold;
      display: block; margin-bottom: 1px; }}
    .enc-list {{ display: flex; flex-direction: column; gap: 0; }}
    .enc-entry {{ display: flex; align-items: center; gap: 3px;
      font-size: 0.78em; line-height: 1.4; }}
    .enc-sprite {{ width: 20px; height: 20px; image-rendering: pixelated;
      vertical-align: middle; flex-shrink: 0; }}
    .enc-name {{ color: #ddd; flex: 1; min-width: 0;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .enc-rate {{ font-weight: bold; white-space: nowrap; min-width: 2.8em;
      text-align: right; }}
    .enc-lv {{ color: #666; font-size: 0.88em; white-space: nowrap; }}
    .area-enc-details summary {{ color: #7af; }}
    .card-hdr-right {{ display: flex; align-items: center; gap: 4px; }}
  </style>
</head>
<body>
  <h1><svg viewBox="0 0 595.3 594.1" style="width:1.3em;height:1.3em;vertical-align:-0.15em;margin-right:0.12em"><path fill="#fff" d="M297.6,380.9c-40.4,0-74.1-28.6-82.1-66.6H81.1c9.5,110.5,102.2,197.2,215.1,197.2s205.7-86.7,215.1-197.2H379.7C371.7,352.4,338,380.9,297.6,380.9z"/><path fill="#FF1C1C" d="M297.7,213.2c40.4,0,74.1,28.6,82.1,66.6h134.4C504.7,169.2,412,82.5,299,82.5S93.4,169.2,83.9,279.7h131.7C223.6,241.7,257.3,213.2,297.7,213.2z"/><path fill="#fff" d="M347.1,297c0-6.1-1.1-11.9-3.2-17.3c-7-18.8-25.1-32.1-46.3-32.1s-39.3,13.4-46.3,32.1c-2,5.4-3.1,11.2-3.1,17.3s1.1,11.9,3.1,17.3c7,18.8,25.1,32.1,46.3,32.1c21.2,0,39.3-13.4,46.3-32.1C346,309,347.1,303.1,347.1,297z"/><path d="M299,82.5c113,0,205.7,86.7,215.1,197.2H379.7c-8-38-41.7-66.6-82.1-66.6c-40.4,0-74.1,28.6-82.1,66.6H83.9C93.4,169.2,186.1,82.5,299,82.5z M343.9,279.7c2,5.4,3.1,11.2,3.1,17.3s-1.1,11.9-3.1,17.3c-7,18.8-25.1,32.1-46.3,32.1c-21.2,0-39.3-13.4-46.3-32.1c-2-5.4-3.1-11.2-3.1-17.3s1.1-11.9,3.1-17.3c7-18.8,25.1-32.1,46.3-32.1S336.9,261,343.9,279.7z M296.2,511.6c-113,0-205.7-86.7-215.1-197.2h134.4c8,38,41.7,66.6,82.1,66.6s74.1-28.6,82.1-66.6h131.7C501.9,424.8,409.2,511.6,296.2,511.6z M297.6,41.3C156.4,41.3,41.9,155.8,41.9,297s114.5,255.7,255.7,255.7S553.4,438.3,553.4,297S438.9,41.3,297.6,41.3z"/></svg>{page_title}</h1>
  <p class="sub">Live updates via SSE &mdash; <span id="ts">{timestamp}</span></p>
  <p class="sub">TCP port: {tcp_port} &nbsp;·&nbsp; <a href="/memorial" style="color:#f44;text-decoration:none">&#x1FAA6; Memorial Wall</a> &nbsp;·&nbsp; <a href="/stream" style="color:#6af;text-decoration:none">&#127909; Stream Overlays</a> &nbsp;·&nbsp; <a href="/twitch" style="color:#f8d030;text-decoration:none">&#129302; Twitch Bot</a> &nbsp;·&nbsp; <a href="/obs" style="color:#b8f0ff;text-decoration:none">&#128225; OBS</a> &nbsp;·&nbsp; <a href="/debug" style="color:#f90;text-decoration:none">&#128295; Debug</a> &nbsp;·&nbsp; <a href="/calc/normal.html" style="color:#fa0;text-decoration:none">&#9876;&#65039; RR Calc</a>{manager_link}</p>
  <div id="content">
  {body}
  </div>
  <script>
    (function() {{
      var FALLBACK_INTERVAL = 10000;  // Fallback poll if SSE disconnects
      var timer = null;
      var refreshPaused = false;
      var refreshInFlight = false;
      var refreshPending = false;
      var userInteracting = false;
      var interactionTimer = null;
      // Pause DOM morphing while the user is pressing a mouse button so that
      // an SSE ping landing between mousedown and click cannot replace the
      // element under the cursor and swallow the click event.
      document.addEventListener("mousedown", function() {{
        userInteracting = true;
        if (interactionTimer) {{ clearTimeout(interactionTimer); interactionTimer = null; }}
      }});
      document.addEventListener("mouseup", function() {{
        interactionTimer = setTimeout(function() {{
          userInteracting = false;
          interactionTimer = null;
          if (refreshPending) {{ refreshPending = false; doRefresh(); }}
        }}, 250);
      }});
      // Cache processed sprite data URLs by original src to avoid re-processing
      var spriteCache = {{}};

      // ── SSE connection ──
      var evtSource = null;
      function connectSSE() {{
        if (evtSource) {{ try {{ evtSource.close(); }} catch(e) {{}} }}
        evtSource = new EventSource("/api/events");
        evtSource.addEventListener("ping", function() {{
          triggerRefresh();
        }});
        evtSource.onerror = function() {{
          // SSE disconnected — fall back to timer polling until reconnect.
          // EventSource auto-reconnects (with retry: 3000 from server).
          if (!timer) scheduleRefresh();
        }};
        evtSource.onopen = function() {{
          // SSE connected — cancel fallback timer
          if (timer) {{ clearTimeout(timer); timer = null; }}
        }};
      }}
      connectSSE();

      // Remove solid background from GBA-style sprite PNGs.
      // Reads top-left pixel as bg color and sets all matching pixels transparent.
      function removeSpriteBackground(img) {{
        if (img.dataset.bgRemoved || !img.naturalWidth) return;
        var src = img.src;
        // Only process funnotbun sprites (they have solid bg; PokeAPI are already transparent)
        if (src.indexOf('funnotbun') === -1) return;
        if (spriteCache[src]) {{
          img.src = spriteCache[src];
          img.dataset.bgRemoved = '1';
          return;
        }}
        var c = document.createElement('canvas');
        c.width = img.naturalWidth;
        c.height = img.naturalHeight;
        var ctx = c.getContext('2d');
        ctx.drawImage(img, 0, 0);
        try {{
          var data = ctx.getImageData(0, 0, c.width, c.height);
          var px = data.data;
          // Top-left pixel is the background color
          var bgR = px[0], bgG = px[1], bgB = px[2];
          for (var i = 0; i < px.length; i += 4) {{
            if (px[i] === bgR && px[i+1] === bgG && px[i+2] === bgB) {{
              px[i+3] = 0;  // set alpha to 0
            }}
          }}
          ctx.putImageData(data, 0, 0);
          var dataUrl = c.toDataURL();
          spriteCache[src] = dataUrl;
          img.src = dataUrl;
        }} catch(e) {{
          // CORS or security error — leave original
        }}
        img.dataset.bgRemoved = '1';
      }}

      // Process all current and future .mon-sprite and .enc-sprite images
      function processAllSprites() {{
        document.querySelectorAll('img.mon-sprite, img.enc-sprite').forEach(function(img) {{
          if (img.dataset.bgRemoved) return;
          // Check cache first — apply instantly without waiting for network load
          var origSrc = img.getAttribute('src');
          if (origSrc && spriteCache[origSrc]) {{
            img.src = spriteCache[origSrc];
            img.dataset.bgRemoved = '1';
            return;
          }}
          if (img.complete && img.naturalWidth) {{
            removeSpriteBackground(img);
          }} else {{
            img.crossOrigin = 'anonymous';
            img.addEventListener('load', function() {{ removeSpriteBackground(img); }}, {{once: true}});
          }}
        }});
      }}

      function scheduleRefresh() {{
        if (timer) clearTimeout(timer);
        timer = setTimeout(doRefresh, FALLBACK_INTERVAL);
      }}

      function triggerRefresh() {{
        // Debounce: if a fetch is already in flight or the user is interacting
        // (mouse held down), mark pending and return — flush on mouseup.
        if (refreshInFlight || userInteracting) {{ refreshPending = true; return; }}
        doRefresh();
      }}

      function syncAttrs(t, s) {{
        // Copy attributes from source to target
        for (var i = 0; i < s.attributes.length; i++) {{
          var a = s.attributes[i];
          // Preserve user-toggled "open" on <details> elements
          if (a.name === "open" && t.tagName === "DETAILS") continue;
          if (t.getAttribute(a.name) !== a.value) t.setAttribute(a.name, a.value);
        }}
        // Remove attributes not in source
        for (var i = t.attributes.length - 1; i >= 0; i--) {{
          var nm = t.attributes[i].name;
          // Preserve user-toggled "open" on <details> elements
          if (nm === "open" && t.tagName === "DETAILS") continue;
          if (!s.hasAttribute(nm)) t.removeAttribute(nm);
        }}
      }}

      function morphDOM(target, source) {{
        if (target.isEqualNode(source)) return;
        syncAttrs(target, source);
        var tc = Array.from(target.childNodes);
        var sc = Array.from(source.childNodes);

        // Key-based matching for TBODY elements: match <tr> children by data-key
        // instead of position so row insertions/removals don't shift sprites.
        if (target.tagName === "TBODY") {{
          var tMap = {{}};
          tc.forEach(function(n) {{
            if (n.nodeType === 1 && n.getAttribute) {{
              var k = n.getAttribute("data-key");
              if (k) tMap[k] = n;
            }}
          }});
          // Reconcile children in-place without detaching (prevents sprite flicker)
          var cursor = target.firstChild;
          sc.forEach(function(sn) {{
            var k = (sn.nodeType === 1 && sn.getAttribute) ? sn.getAttribute("data-key") : null;
            var reuse = k ? tMap[k] : null;
            if (reuse) {{
              morphDOM(reuse, sn);
              if (reuse !== cursor) {{
                target.insertBefore(reuse, cursor);
              }} else {{
                cursor = cursor.nextSibling;
              }}
              delete tMap[k];
            }} else {{
              var newNode = document.importNode(sn, true);
              target.insertBefore(newNode, cursor);
            }}
          }});
          // Remove leftover old keyed nodes no longer in source
          Object.keys(tMap).forEach(function(k) {{ target.removeChild(tMap[k]); }});
          // Remove any remaining unkeyed trailing nodes
          while (target.childNodes.length > sc.length) target.removeChild(target.lastChild);
          return;
        }}

        // Positional matching (non-keyed containers)
        var minLen = Math.min(tc.length, sc.length);
        for (var i = 0; i < minLen; i++) {{
          var tn = tc[i], sn = sc[i];
          if (tn.nodeType !== sn.nodeType) {{
            target.replaceChild(document.importNode(sn, true), tn);
          }} else if (tn.nodeType === 3) {{
            if (tn.nodeValue !== sn.nodeValue) tn.nodeValue = sn.nodeValue;
          }} else if (tn.nodeType === 1) {{
            if (tn.tagName !== sn.tagName) {{
              target.replaceChild(document.importNode(sn, true), tn);
            }} else if (tn.tagName === "IMG") {{
              // Compare by stable data-species attribute, not live src (which onerror mutates).
              var tSpecies = tn.getAttribute("data-species");
              var sSpecies = sn.getAttribute("data-species");
              if (tSpecies !== sSpecies) {{
                target.replaceChild(document.importNode(sn, true), tn);
              }}
              // If same species, preserve current src (may have fallen back via onerror).
            }} else {{
              morphDOM(tn, sn);
            }}
          }}
        }}
        // Append extra source nodes
        for (var i = minLen; i < sc.length; i++) {{
          target.appendChild(document.importNode(sc[i], true));
        }}
        // Remove extra target nodes (from the end to avoid index shift)
        while (target.childNodes.length > sc.length) target.removeChild(target.lastChild);
      }}

      function doRefresh() {{
        if (refreshPaused) {{ return; }}
        refreshInFlight = true;
        var sx = window.scrollX, sy = window.scrollY;
        fetch(window.location.href, {{cache: "no-store"}})
          .then(function(r) {{ return r.text(); }})
          .then(function(html) {{
            var parser = new DOMParser();
            var doc = parser.parseFromString(html, "text/html");
            var newContent = doc.getElementById("content");
            var newTs = doc.getElementById("ts");
            if (newContent) {{
              morphDOM(document.getElementById("content"), newContent);
            }}
            if (newTs) {{
              document.getElementById("ts").textContent = newTs.textContent;
            }}
            if (window._slinkEncSort) window._slinkEncSort();
            if (window._slinkEncFilter) window._slinkEncFilter();
            window.scrollTo(sx, sy);
            processAllSprites();
            if (window._slinkCalcRender) {{ window._slinkCalcRender(); }}
          }})
          .catch(function() {{ /* server temporarily unreachable */ }})
          .finally(function() {{
            refreshInFlight = false;
            // If another SSE ping arrived while we were fetching, do one more refresh
            if (refreshPending) {{ refreshPending = false; doRefresh(); }}
          }});
      }}

      processAllSprites();  // Initial page load

      window.adjAttempts = function(delta) {{
        var bar = document.getElementById('attempts-bar');
        var cur = bar ? parseInt(bar.dataset.count, 10) : 0;
        var next = Math.max(0, cur + delta);
        fetch('/api/attempts', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{count:next}})}})
          .then(function(r) {{ return r.json(); }})
          .then(function(j) {{ if (j.ok) {{ triggerRefresh(); }} }});
      }};
    }})();

    // ── Encounters table sort ───────────────────────────────────────────
    (function() {{
      // Persisted sort state across auto-refreshes
      var sortCol = -1, sortAsc = true;

      function naturalCmp(a, b) {{
        return a.localeCompare(b, undefined, {{numeric: true, sensitivity: "base"}});
      }}

      function getSortVal(td, col) {{
        var v = td.getAttribute("data-sort");
        if (v !== null) return v;
        return td.textContent.trim();
      }}

      function applySort() {{
        var tbl = document.getElementById("enc-table");
        if (!tbl) return;
        var ths = tbl.querySelectorAll("thead th");
        ths.forEach(function(th, i) {{
          th.classList.remove("sort-asc", "sort-desc");
          if (i === sortCol) th.classList.add(sortAsc ? "sort-asc" : "sort-desc");
        }});
        var tbody = tbl.querySelector("tbody");
        if (!tbody) return;
        var rows = Array.from(tbody.querySelectorAll("tr"));
        rows.sort(function(ra, rb) {{
          var a = getSortVal(ra.children[sortCol], sortCol);
          var b = getSortVal(rb.children[sortCol], sortCol);
          var aNum = parseFloat(a), bNum = parseFloat(b);
          var cmp = (!isNaN(aNum) && !isNaN(bNum)) ? aNum - bNum : naturalCmp(a, b);
          return sortAsc ? cmp : -cmp;
        }});
        rows.forEach(function(r) {{ tbody.appendChild(r); }});
      }}

      function bindHeaders() {{
        var tbl = document.getElementById("enc-table");
        if (!tbl) return;
        tbl.querySelectorAll("thead th.sortable").forEach(function(th) {{
          var ci = parseInt(th.getAttribute("data-col"), 10);
          th.onclick = function() {{
            if (sortCol === ci) {{ sortAsc = !sortAsc; }}
            else {{ sortCol = ci; sortAsc = true; }}
            applySort();
          }};
        }});
        if (sortCol >= 0) applySort();
      }}

      // Expose so the refresh handler can call synchronously (no flicker)
      window._slinkEncSort = bindHeaders;
      bindHeaders();
    }})();

    // ── Encounters table filter ──────────────────────────────────────────
    (function() {{
      var activeFilter = "all";
      var FILTER_GROUPS = {{
        "linked":    ["alive", "linked"],
        "pending":   ["pending_a", "pending_b", "pending_both"],
        "pending_a": ["pending_a", "pending_both"],
        "pending_b": ["pending_b", "pending_both"],
        "dead":      ["dead", "dead_zone", "memorial"]
      }};

      function applyFilter() {{
        var tbl = document.getElementById("enc-table");
        if (!tbl) return;
        var rows = tbl.querySelectorAll("tbody tr");
        rows.forEach(function(tr) {{
          var st = tr.getAttribute("data-status") || "";
          if (activeFilter === "all") {{
            tr.style.display = "";
          }} else {{
            var group = FILTER_GROUPS[activeFilter] || [];
            tr.style.display = group.indexOf(st) >= 0 ? "" : "none";
          }}
        }});
        var btns = document.querySelectorAll("#enc-filters .filter-btn");
        btns.forEach(function(b) {{
          b.classList.toggle("active", b.getAttribute("data-filter") === activeFilter);
        }});
      }}

      function bindFilters() {{
        var container = document.getElementById("enc-filters");
        if (!container) return;
        container.querySelectorAll(".filter-btn").forEach(function(btn) {{
          btn.onclick = function() {{
            activeFilter = btn.getAttribute("data-filter");
            applyFilter();
          }};
        }});
        applyFilter();
      }}

      window._slinkEncFilter = bindFilters;
      bindFilters();
    }})();

{calc_js}
  </script>
</body>
</html>"""



# ── Debug page ─────────────────────────────────────────────────────────────────

_DEBUG_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<title>Debug — {page_title}</title>
<style>
  :root { --bg:#111; --panel:#1a1a1a; --border:#333; --text:#e2e8f0; --muted:#94a3b8;
          --green:#4ade80; --red:#f87171; --yellow:#fbbf24; --blue:#60a5fa; --orange:#f97316; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:var(--bg); color:var(--text); font-family:'Segoe UI',system-ui,sans-serif; padding:1.5em; font-size:0.92em; }
  h1 { color:var(--orange); margin-bottom:0.2em; font-size:1.3em; }
  .nav { color:var(--muted); font-size:0.85em; margin-bottom:0.8em; }
  .nav a { color:var(--blue); text-decoration:none; }
  .nav a:hover { text-decoration:underline; }

  /* ── Live status banner ── */
  .live-bar { display:flex; gap:1.2em; flex-wrap:wrap; align-items:center;
              background:#0d1117; border:1px solid var(--border); border-radius:6px;
              padding:0.6em 1em; margin-bottom:1em; font-size:0.85em; }
  .live-bar .sse-dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:4px; }
  .live-bar .sse-ok { background:var(--green); box-shadow:0 0 4px var(--green); }
  .live-bar .sse-off { background:var(--red); box-shadow:0 0 4px var(--red); }
  .live-bar .player-pill { display:inline-flex; align-items:center; gap:4px; padding:2px 10px;
                           border-radius:12px; font-weight:600; font-size:0.9em; }
  .live-bar .player-pill.on { background:#14532d; color:var(--green); }
  .live-bar .player-pill.off { background:#1c1c1c; color:#555; }
  .live-bar .stat { color:var(--muted); }
  .live-bar .stat b { color:var(--text); font-variant-numeric:tabular-nums; }
  .live-bar .event-log { flex:1; text-align:right; color:#666; font-family:monospace; font-size:0.9em;
                         overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:400px; }

  .grid { display:grid; grid-template-columns:1fr 1fr; gap:1em; }
  @media(max-width:900px) { .grid { grid-template-columns:1fr; } }
  .panel { background:var(--panel); border:1px solid var(--border); border-radius:6px; padding:1em; }
  .panel h2 { color:var(--orange); font-size:1em; margin-bottom:0.7em; border-bottom:1px solid var(--border); padding-bottom:0.4em;
              display:flex; align-items:center; justify-content:space-between; }
  .panel h2 .h2-left { display:flex; align-items:center; gap:0.3em; }
  .panel.full { grid-column:1/-1; }
  label { display:block; color:var(--muted); font-size:0.85em; margin-bottom:2px; }
  input, select, textarea { background:#0d1b2a; border:1px solid var(--border); color:var(--text);
    padding:5px 8px; border-radius:4px; font-size:0.88em; font-family:inherit; width:100%; }
  select { cursor:pointer; }
  textarea { min-height:100px; resize:vertical; }
  .row { display:flex; gap:0.6em; margin-bottom:0.6em; }
  .row > * { flex:1; }
  .btn { padding:6px 14px; border-radius:5px; border:none; cursor:pointer; font-size:0.85em; font-weight:600;
         transition:filter 0.15s; }
  .btn-orange { background:#7c2d12; color:var(--orange); }
  .btn-red { background:#7f1d1d; color:var(--red); }
  .btn-green { background:#14532d; color:var(--green); }
  .btn-blue { background:#1e3a5f; color:var(--blue); }
  .btn:hover { filter:brightness(1.3); }
  .btn:active { filter:brightness(0.9); }
  .btn-sm { padding:3px 10px; font-size:0.8em; }
  .result { margin-top:0.6em; padding:0.5em; background:#0d1b2a; border-radius:4px;
    font-family:monospace; font-size:0.82em; white-space:pre-wrap; word-break:break-all;
    max-height:300px; overflow-y:auto; color:var(--muted); display:none; }
  .result.ok { border-left:3px solid var(--green); }
  .result.err { border-left:3px solid var(--red); }
  .flash { animation: flash-border 0.5s ease-out; }
  @keyframes flash-border { 0% { border-color:#4af; } 100% { border-color:var(--border); } }
  #raw-state { max-height:500px; overflow:auto; }
  #raw-state pre { white-space:pre-wrap; word-break:break-all; color:var(--muted); font-size:0.82em; }
  .backup-table { width:100%; font-size:0.9em; border-collapse:collapse; }
  .backup-table th { text-align:left; color:var(--muted); padding:3px 6px; border-bottom:1px solid var(--border); }
  .backup-table td { padding:3px 6px; }
  .backup-table tr:hover { background:#1a1a2a; }
  .backup-table .slot-link { color:#0af; cursor:pointer; text-decoration:underline; }
  .backup-table .slot-link:hover { color:#4cf; }
  .ml-table { width:100%; font-size:0.85em; border-collapse:collapse; }
  .ml-table th { text-align:left; color:var(--muted); padding:3px 6px; border-bottom:1px solid var(--border); font-weight:600; }
  .ml-table td { padding:3px 6px; font-family:monospace; }
  .ml-table tr:hover { background:#1a1a2a; }
  .ml-table .st-alive { color:var(--green); }
  .ml-table .st-dead { color:var(--red); }
  .ml-table .st-memorial { color:#888; }
  .ml-table .btn-unlink { padding:2px 8px; font-size:0.8em; }
  .ml-table .btn-revive { padding:2px 8px; font-size:0.8em; background:#2a6; color:#fff; border:none; border-radius:3px; cursor:pointer; }
  .ml-table .btn-revive:hover { background:#3b7; }
</style>
</head><body>
<h1>&#128295; Debug Console</h1>
<div class="nav"><a href="/">&#8592; Status Page</a> · <a href="/memorial">&#129702; Memorial</a></div>

<!-- Live status banner -->
<div class="live-bar">
  <span id="sse-badge"><span class="sse-dot sse-off"></span> connecting…</span>
  <span class="player-pill off" id="pill-a">A: offline</span>
  <span class="player-pill off" id="pill-b">B: offline</span>
  <span class="stat">Links: <b id="lb-links">0</b></span>
  <span class="stat">Areas: <b id="lb-areas">0</b></span>
  <span class="stat">Queued: <b id="lb-queued">0/0</b></span>
  <span class="event-log" id="lb-last-event">—</span>
</div>

<div class="grid">

  <!-- Inject Event -->
  <div class="panel">
    <h2><span class="h2-left">&#9889; Inject Event</span></h2>
    <div class="row">
      <div><label>Player</label><select id="ev-player"><option value="a">A</option><option value="b">B</option></select></div>
      <div><label>Event</label><select id="ev-type">
        <option value="area_enter">area_enter</option>
        <option value="capture">capture</option>
        <option value="faint">faint</option>
        <option value="no_catch">no_catch</option>
        <option value="whiteout">whiteout</option>
        <option value="party_to_box">party_to_box</option>
        <option value="box_to_party">box_to_party</option>
        <option value="key_change">key_change</option>
        <option value="hello">hello</option>
        <option value="tick">tick</option>
        <option value="stats_cache">stats_cache</option>
        <option value="sync_retrieve_done">sync_retrieve_done</option>
        <option value="sync_retrieve_failed">sync_retrieve_failed</option>
        <option value="safe">safe</option>
      </select></div>
    </div>
    <div class="row">
      <div><label>Mon Key</label><input id="ev-key" placeholder="AABBCCDD:11223344" list="dl-keys"></div>
      <div><label>Area ID</label><input id="ev-area" placeholder="route_1" list="dl-areas"></div>
    </div>
    <div class="row">
      <div><label>Extra JSON fields</label><input id="ev-extra" placeholder='{"level":12,"species_id":25}'></div>
    </div>
    <button class="btn btn-orange" onclick="injectEvent()">Send Event</button>
    <div class="result" id="ev-result"></div>
  </div>

  <!-- Queue Command -->
  <div class="panel">
    <h2><span class="h2-left">&#128228; Queue Command</span></h2>
    <div class="row">
      <div><label>Target Player</label><select id="cmd-player"><option value="a">A</option><option value="b">B</option></select></div>
      <div><label>Command</label><select id="cmd-type">
        <option value="force_faint">force_faint</option>
        <option value="box_mon">box_mon</option>
        <option value="party_mon">party_mon</option>
        <option value="memorialize">memorialize</option>
        <option value="unresolve_area">unresolve_area</option>
        <option value="hud_show">hud_show</option>
        <option value="noop">noop</option>
      </select></div>
    </div>
    <div class="row">
      <div><label>Mon Key</label><input id="cmd-key" placeholder="AABBCCDD:11223344" list="dl-keys"></div>
    </div>
    <div class="row">
      <div><label>Extra JSON fields</label><input id="cmd-extra" placeholder='{"text":"Hello","r":255,"g":0,"b":0}'></div>
    </div>
    <button class="btn btn-blue" onclick="queueCmd()">Queue Command</button>
    <div class="result" id="cmd-result"></div>
  </div>

  <!-- Toggle State -->
  <div class="panel">
    <h2><span class="h2-left">&#9881; State Toggles</span></h2>
    <div class="row">
      <div><label>Player</label><select id="tog-player"><option value="a">A</option><option value="b">B</option></select></div>
    </div>
    <div class="row">
      <button class="btn btn-green" onclick="toggleBalls(true)">Set Pokeballs &#10003;</button>
      <button class="btn btn-red" onclick="toggleBalls(false)">Clear Pokeballs &#10007;</button>
    </div>
    <div class="result" id="tog-result"></div>
    <h2 style="margin-top:1em"><span class="h2-left">&#128506; Area State</span></h2>
    <div class="row">
      <div><label>Area ID</label><input id="area-id" placeholder="route_1" list="dl-areas"></div>
      <div><label>New State</label><select id="area-state">
        <option value="unseen">unseen</option>
        <option value="pending_a">pending_a</option>
        <option value="pending_b">pending_b</option>
        <option value="pending_both">pending_both</option>
        <option value="linked">linked</option>
        <option value="dead_zone">dead_zone</option>
      </select></div>
    </div>
    <button class="btn btn-orange" onclick="setAreaState()">Set Area State</button>
    <div class="result" id="area-result"></div>
  </div>

  <!-- Live State Info -->
  <div class="panel">
    <h2><span class="h2-left">&#128270; Live State</span>
      <button class="btn btn-blue btn-sm" onclick="loadLiveState()">&#8635; Refresh</button></h2>
    <div id="live-state-content" style="font-size:0.85em;color:var(--muted)">Loading…</div>
  </div>

  <!-- Danger Zone -->
  <div class="panel">
    <h2><span class="h2-left">&#9888; Danger Zone</span></h2>
    <div class="row">
      <button class="btn btn-red" onclick="resetRun()">&#128163; Reset Run</button>
      <button class="btn btn-red" onclick="clearPending()">Clear All Pending</button>
    </div>
    <div class="row">
      <div><label>Clear Pending for Area</label><input id="clear-area" placeholder="route_1" list="dl-areas"></div>
      <button class="btn btn-orange" onclick="clearPendingArea()" style="flex:0 0 auto;align-self:flex-end">Clear</button>
    </div>
    <div class="result" id="danger-result"></div>
    <h2 style="margin-top:1em"><span class="h2-left">&#128190; Rollback to Backup</span></h2>
    <div id="backup-list" style="color:#888">Loading backups…</div>
    <div class="result" id="rollback-result"></div>
  </div>

  <!-- Manual Link / Unlink -->
  <div class="panel full">
    <h2><span class="h2-left">&#128279; Link Management</span>
      <button class="btn btn-blue btn-sm" onclick="mlRefresh()">&#8635; Refresh</button></h2>

    <!-- Current links table -->
    <div id="ml-links-table" style="margin-bottom:1em;max-height:250px;overflow-y:auto"></div>

    <!-- Create new link -->
    <h3 style="color:var(--green);font-size:0.9em;margin-bottom:0.5em">Create Link</h3>
    <div class="row">
      <div><label id="ml-label-a">Player A</label>
        <select id="ml-a" onchange="mlMonChanged('a')" style="font-family:monospace;font-size:0.88em"></select></div>
      <div><label id="ml-label-b">Player B</label>
        <select id="ml-b" onchange="mlMonChanged('b')" style="font-family:monospace;font-size:0.88em"></select></div>
    </div>
    <div class="row">
      <div><label>Area</label>
        <select id="ml-area" style="font-family:monospace;font-size:0.88em"></select></div>
      <div><label>Filter areas</label>
        <input id="ml-area-filter" type="text" placeholder="type to filter…" oninput="mlFilterAreas()" style="font-family:monospace;font-size:0.85em"></div>
    </div>
    <div style="display:flex;gap:0.6em;align-items:center;margin-top:0.4em">
      <button class="btn btn-green" onclick="doManualLink()">&#128279; Link</button>
      <label style="display:inline;font-size:0.8em;cursor:pointer;color:var(--muted)">
        <input type="checkbox" id="ml-override" style="width:auto"> Override existing links
      </label>
      <span id="ml-warn" style="font-size:0.85em;color:var(--yellow)"></span>
    </div>
    <div class="result" id="ml-result"></div>
  </div>

  <!-- Memorial Box Monitor -->
  <div class="panel full">
    <h2><span class="h2-left">&#129702; Memorial Box Monitor</span>
      <button class="btn btn-blue btn-sm" onclick="loadMemorial()">&#8635; Refresh</button></h2>
    <div id="memorial-content" style="font-size:0.85em;color:var(--muted)">Loading…</div>
  </div>

  <!-- Raw State -->
  <div class="panel full" id="raw-state">
    <h2><span class="h2-left">&#128196; Raw State</span>
      <span>
        <label style="display:inline;font-size:0.75em;cursor:pointer;color:var(--muted);margin-right:0.5em">
          <input type="checkbox" id="raw-auto" checked style="width:auto"> auto
        </label>
        <button class="btn btn-blue btn-sm" onclick="loadRaw()">&#8635; Refresh</button>
      </span>
    </h2>
    <pre id="raw-json">Loading…</pre>
  </div>

</div>

<!-- Shared datalists for autofill -->
<datalist id="dl-keys"></datalist>
<datalist id="dl-areas"></datalist>

<script>
// ── Helpers ──────────────────────────────────────────────────────────────
function showResult(el, ok, data) {
  el.style.display = 'block';
  el.className = 'result ' + (ok ? 'ok' : 'err');
  el.textContent = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
}
async function api(method, path, body) {
  var opts = {method: method, headers: {'Content-Type':'application/json'}};
  if (body !== undefined) opts.body = JSON.stringify(body);
  var r = await fetch(path, opts);
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
  var src = new EventSource('/api/events');
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
  var el = document.getElementById('sse-badge');
  el.innerHTML = '<span class="sse-dot ' + (ok ? 'sse-ok' : 'sse-off') + '"></span> ' + (ok ? 'live' : 'disconnected');
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
    if (p && p.last_event && p.last_event !== '\\u2014') {
      events.push(pid.toUpperCase() + ': ' + p.last_event);
    }
  });
  document.getElementById('lb-last-event').textContent = events.join('  \\u2502  ') || '\\u2014';
}

// ── Datalist autofill ───────────────────────────────────────────────────
var _allAreas = null;  // {aid: display_name} — loaded once from manual_link_data

function updateDataLists() {
  var d = _lastStatus;
  if (!d) return;

  // ── Mon keys ──
  var keys = {};
  ['a','b'].forEach(function(pid) {
    var p = d.players && d.players[pid];
    if (!p) return;
    var det = p.party_details || {};
    Object.keys(det).forEach(function(k) {
      var m = det[k];
      var nick = m.nickname || '';
      var sp = m.species_name || '';
      var short = k.substring(0, 8);
      keys[k] = pid.toUpperCase() + ' party: ' + short + ' ' + nick + (sp ? ' (' + sp + ')' : '');
    });
  });
  (d.links || []).forEach(function(lnk) {
    if (lnk.a_key && !keys[lnk.a_key]) {
      keys[lnk.a_key] = 'A link: ' + lnk.a_key.substring(0,8) + ' ' + (lnk.a_nickname||'') + ' (' + (lnk.a_species_name||'') + ') [' + lnk.status + ']';
    }
    if (lnk.b_key && !keys[lnk.b_key]) {
      keys[lnk.b_key] = 'B link: ' + lnk.b_key.substring(0,8) + ' ' + (lnk.b_nickname||'') + ' (' + (lnk.b_species_name||'') + ') [' + lnk.status + ']';
    }
  });
  var pc = d.pending_captures || {};
  Object.keys(pc).forEach(function(area) {
    Object.keys(pc[area]).forEach(function(pid) {
      var info = pc[area][pid];
      var k = info.key;
      if (k && !keys[k]) {
        keys[k] = pid.toUpperCase() + ' pending@' + area + ': ' + k.substring(0,8) + ' ' + (info.nickname||'');
      }
    });
  });
  var dlKeys = document.getElementById('dl-keys');
  var kh = '';
  Object.keys(keys).forEach(function(k) { kh += '<option value="' + k + '">' + keys[k] + '</option>'; });
  dlKeys.innerHTML = kh;

  // ── Areas (all from area_map + state annotations) ──
  if (!_allAreas) return;  // not loaded yet
  var states = d.area_states || {};
  var dlAreas = document.getElementById('dl-areas');
  var ah = '';
  // Pending first
  var pendingIds = Object.keys(pc).sort();
  var seen = {};
  pendingIds.forEach(function(aid) {
    seen[aid] = true;
    var pids = Object.keys(pc[aid]).map(function(p){return p.toUpperCase();}).join('+');
    var disp = _allAreas[aid] || aid;
    ah += '<option value="' + aid + '">\\u26a0 ' + disp + ' [PENDING ' + pids + ']</option>';
  });
  // Then all areas, grouped by state
  var active = [], rest = [];
  Object.keys(_allAreas).sort().forEach(function(aid) {
    if (seen[aid]) return;
    var st = states[aid] || '';
    if (st && st !== 'unseen') active.push(aid);
    else rest.push(aid);
  });
  active.forEach(function(aid) {
    var st = states[aid];
    var disp = _allAreas[aid] || aid;
    ah += '<option value="' + aid + '">' + disp + ' [' + st + ']</option>';
  });
  rest.forEach(function(aid) {
    var disp = _allAreas[aid] || aid;
    ah += '<option value="' + aid + '">' + disp + '</option>';
  });
  dlAreas.innerHTML = ah;
}

async function loadAllAreas() {
  try {
    var r = await fetch('/api/debug/manual_link_data');
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
  var r = await fetch('/api/debug/backups');
  var j = await r.json();
  var el = document.getElementById('backup-list');
  if (!j.backups || j.backups.length === 0) {
    el.innerHTML = '<span style="color:#555;font-size:0.9em">No backups yet — created every 5 min when both players connected.</span>';
    return;
  }
  window._backupData = {};
  var rows = j.backups.map(function(b) {
    window._backupData[b.slot] = b;
    var sum = b.summary;
    var detail = sum ? '<span style="color:#4f8">'+sum.links_alive+'&#x2764;</span> <span style="color:#f55">'+sum.links_dead+'&#x2620;</span> '+sum.areas_pending+' pending '+sum.areas_dead_zone+' dz' : '<span style="color:#666">?</span>';
    return '<tr><td class="slot-link" onclick="doRollback('+b.slot+')">#' + b.slot + '</td><td>' + b.modified + '</td><td>' + detail + '</td><td>' + (b.size/1024).toFixed(1) + 'K</td></tr>';
  });
  el.innerHTML = '<table class="backup-table"><tr><th>Slot</th><th>Time</th><th>State</th><th>Size</th></tr>' + rows.join('') + '</table>';
}
async function doRollback(slot) {
  if (slot === undefined) return;
  var info = window._backupData && window._backupData[slot];
  var msg = 'Roll back to backup slot #' + slot + '?';
  if (info) {
    msg += '\\n\\nBackup from: ' + info.modified;
    if (info.summary) {
      var s = info.summary;
      msg += '\\n  ' + s.links_alive + ' alive links, ' + s.links_dead + ' dead';
      msg += '\\n  ' + s.areas_pending + ' pending areas, ' + s.areas_dead_zone + ' dead zones';
    }
  }
  msg += '\\n\\nCurrent state will be saved as pre_rollback.';
  if (!confirm(msg)) return;
  var j = await api('POST', '/api/debug/rollback', {slot: slot});
  showResult(document.getElementById('rollback-result'), j.ok, j.message || j.error);
  if (j.ok) loadBackups();
}

// ── Raw State ───────────────────────────────────────────────────────────
async function loadRaw() {
  try {
    var r = await fetch('/api/debug/raw_state');
    var j = await r.json();
    document.getElementById('raw-json').textContent = JSON.stringify(j, null, 2);
  } catch(e) {}
}

// ── Live State Info ─────────────────────────────────────────────────────
async function loadLiveState() {
  try {
    var r = await fetch('/api/debug/raw_state');
    var j = await r.json();
    var live = j._live || {};
    var h = '';

    // Lock rules
    var rules = j.rules || {};
    var ruleItems = [];
    if (rules.species_lock) ruleItems.push('<span style="color:#f97316">Species</span>');
    if (rules.gender_lock) ruleItems.push('<span style="color:#a78bfa">Gender</span>');
    if (rules.type_lock) ruleItems.push('<span style="color:#38bdf8">Type</span>');
    h += '<div style="margin-bottom:0.6em"><b style="color:var(--text)">Lock Rules:</b> ' + (ruleItems.length ? ruleItems.join(' \\u00b7 ') : '<span style="color:#555">none</span>') + '</div>';

    // Player identity
    var ident = j.player_identity || {};
    h += '<div style="margin-bottom:0.6em"><b style="color:var(--text)">Identity Lock:</b><br>';
    ['a','b'].forEach(function(pid) {
      var id = ident[pid];
      if (id) {
        h += '&nbsp;&nbsp;' + pid.toUpperCase() + ': <span style="color:var(--green)">' + (id.trainer_name||'?') + '</span> (OT: ' + (id.ot_id||'?') + ')<br>';
      } else {
        h += '&nbsp;&nbsp;' + pid.toUpperCase() + ': <span style="color:#555">not locked</span><br>';
      }
    });
    h += '</div>';

    // Identity errors
    var identErr = live.identity_errors || {};
    if (identErr.a || identErr.b) {
      h += '<div style="margin-bottom:0.6em;color:var(--red)"><b>Identity Errors:</b><br>';
      if (identErr.a) h += '&nbsp;&nbsp;A: ' + identErr.a + '<br>';
      if (identErr.b) h += '&nbsp;&nbsp;B: ' + identErr.b + '<br>';
      h += '</div>';
    }

    // Party keys
    var pk = live.party_keys || {};
    h += '<div style="margin-bottom:0.6em"><b style="color:var(--text)">Party Keys:</b><br>';
    ['a','b'].forEach(function(pid) {
      var keys = pk[pid] || [];
      h += '&nbsp;&nbsp;' + pid.toUpperCase() + ' (' + keys.length + '): ';
      h += keys.length ? keys.map(function(k){return '<code style="color:#60a5fa">'+k.substring(0,8)+'</code>';}).join(', ') : '<span style="color:#555">empty</span>';
      h += '<br>';
    });
    h += '</div>';

    // Bonus keys (shinies)
    var bk = live.bonus_keys || j.bonus_keys || {};
    var hasBk = (bk.a && bk.a.length) || (bk.b && bk.b.length);
    h += '<div style="margin-bottom:0.6em"><b style="color:var(--text)">Bonus Keys (Shinies):</b><br>';
    ['a','b'].forEach(function(pid) {
      var keys = bk[pid] || [];
      h += '&nbsp;&nbsp;' + pid.toUpperCase() + ': ';
      h += keys.length ? keys.map(function(k){return '<code style="color:#fbbf24">'+k.substring(0,8)+'</code>';}).join(', ') : '<span style="color:#555">none</span>';
      h += '<br>';
    });
    h += '</div>';

    // Pending bonus (shiny bonus queue — waiting for partner catch)
    var pb_bonus = live.pending_bonus || j.pending_bonus || {};
    var hasPbBonus = (pb_bonus.a && pb_bonus.a.length) || (pb_bonus.b && pb_bonus.b.length);
    if (hasPbBonus) {
      h += '<div style="margin-bottom:0.6em"><b style="color:var(--text)">Pending Bonus (Awaiting Partner):</b><br>';
      ['a','b'].forEach(function(pid) {
        var keys = pb_bonus[pid] || [];
        if (!keys.length) return;
        h += '&nbsp;&nbsp;' + pid.toUpperCase() + ': ';
        h += keys.map(function(k){return '<code style="color:#ffd700">\u23f3 '+k.substring(0,8)+'</code>';}).join(', ');
        h += '<br>';
      });
      h += '</div>';
    }

    // Pokeballs obtained
    var pb = j.pokeballs_obtained || {};
    h += '<div style="margin-bottom:0.6em"><b style="color:var(--text)">Pok\\u00e9balls Obtained:</b> ';
    h += 'A: ' + (pb.a ? '<span style="color:var(--green)">\\u2713</span>' : '<span style="color:var(--red)">\\u2717</span>');
    h += ' &nbsp; B: ' + (pb.b ? '<span style="color:var(--green)">\\u2713</span>' : '<span style="color:var(--red)">\\u2717</span>');
    h += '</div>';

    // Party size (physical)
    var ps = live.party_size || {};
    h += '<div style="margin-bottom:0.6em"><b style="color:var(--text)">Party Size (physical):</b> ';
    h += 'A: ' + (ps.a !== undefined ? ps.a : '?') + ' &nbsp; B: ' + (ps.b !== undefined ? ps.b : '?');
    h += '</div>';

    // Mon stats cache count
    var msCount = Object.keys(j.mon_stats || {}).length;
    h += '<div><b style="color:var(--text)">Mon Stats Cached:</b> ' + msCount + ' entries</div>';

    document.getElementById('live-state-content').innerHTML = h;
  } catch(e) {
    document.getElementById('live-state-content').innerHTML = '<span style="color:var(--red)">Error loading state</span>';
  }
}

// ── Memorial Box Monitor ────────────────────────────────────────────────
async function loadMemorial() {
  try {
    var r = await fetch('/api/debug/raw_state');
    var j = await r.json();
    var mem = j._memorial || {};
    var boxIdx = mem.memorial_box_index;
    var boxContents = mem.memorial_box_contents || {};
    var pendingMem = mem.pending_memorials || {};
    var memLog = mem.memorial_log || [];
    var h = '';

    // 1. Memorial box info
    if (boxIdx >= 0) {
      h += '<div style="margin-bottom:0.8em"><b style="color:var(--text)">Memorial Box:</b> Box ' + (boxIdx + 1) + ' (index ' + boxIdx + ')</div>';
    } else {
      h += '<div style="margin-bottom:0.8em"><b style="color:var(--text)">Memorial Box:</b> <span style="color:#555">No dedicated memorial box (Gen 1/2)</span></div>';
    }

    // 2. Pending memorials
    var hasPending = false;
    ['a','b'].forEach(function(pid) {
      var pkeys = pendingMem[pid] || [];
      if (pkeys.length > 0) hasPending = true;
    });
    if (hasPending) {
      h += '<div style="margin-bottom:0.8em"><b style="color:var(--yellow)">\\u23f3 Pending Memorials</b> <span style="color:var(--muted);font-size:0.85em">(awaiting Lua confirmation)</span><br>';
      ['a','b'].forEach(function(pid) {
        var pkeys = pendingMem[pid] || [];
        if (!pkeys.length) return;
        h += '&nbsp;&nbsp;<b>' + pid.toUpperCase() + ':</b> ';
        h += pkeys.map(function(pk) {
          return '<code style="color:var(--yellow)">' + pk.species_name + '</code> <span style="color:#555">[' + pk.key.substring(0,8) + ']</span>';
        }).join(', ');
        h += '<br>';
      });
      h += '</div>';
    }

    // 3. Memorial box contents (live PC scan)
    if (boxIdx >= 0) {
      h += '<div style="margin-bottom:0.8em"><b style="color:var(--text)">Box ' + (boxIdx + 1) + ' Contents</b>';
      var totalSlots = 0;
      ['a','b'].forEach(function(pid) {
        var entries = boxContents[pid] || [];
        totalSlots += entries.length;
      });
      if (totalSlots === 0) {
        h += ' <span style="color:#555;font-size:0.9em">— empty or not scanned by emulator</span></div>';
      } else {
        h += '</div>';
        ['a','b'].forEach(function(pid) {
          var entries = boxContents[pid] || [];
          if (!entries.length) return;
          h += '<div style="margin-left:0.5em;margin-bottom:0.5em">';
          h += '<b style="color:var(--muted)">' + pid.toUpperCase() + '</b>';
          h += '<table class="ml-table" style="margin-top:0.3em"><thead><tr>';
          h += '<th>Slot</th><th>Species</th><th>Nickname</th><th>Key</th><th>Status</th>';
          h += '</tr></thead><tbody>';
          entries.forEach(function(e) {
            var statusColor = '#888';
            var statusLabel = e.status;
            if (e.status === 'dead') { statusColor = 'var(--red)'; statusLabel = '\\u2620 dead'; }
            else if (e.status === 'pending_memorial') { statusColor = 'var(--yellow)'; statusLabel = '\\u23f3 pending'; }
            else if (e.status === 'quarantined') { statusColor = 'var(--orange)'; statusLabel = '\\u26a0 QUARANTINED'; }
            else if (e.status === 'unknown') { statusColor = 'var(--yellow)'; statusLabel = '? unknown'; }
            h += '<tr' + (e.status === 'quarantined' ? ' style="background:#3a1a0a"' : '') + '>';
            h += '<td>' + (e.slot + 1) + '</td>';
            h += '<td>' + (e.species_name || '#' + e.species_id) + '</td>';
            h += '<td>' + (e.nickname || '<span style="color:#555">—</span>') + '</td>';
            h += '<td style="font-family:monospace;font-size:0.9em">' + e.key.substring(0,8) + '</td>';
            h += '<td style="color:' + statusColor + ';font-weight:600">' + statusLabel + '</td>';
            h += '</tr>';
          });
          h += '</tbody></table></div>';
        });
      }
    }

    // 4. Memorial log (completed memorializations)
    if (memLog.length > 0) {
      h += '<details style="margin-top:0.6em"><summary style="cursor:pointer;color:var(--text);font-weight:600">\\u1FAA6 Memorial Log (' + memLog.length + ' pairs)</summary>';
      h += '<table class="ml-table" style="margin-top:0.3em"><thead><tr>';
      h += '<th>Area</th><th>Player A</th><th>Player B</th><th>Cause</th>';
      h += '</tr></thead><tbody>';
      memLog.forEach(function(entry) {
        var a = entry.a || {};
        var b = entry.b || {};
        h += '<tr>';
        h += '<td>' + (entry.area_id || '?') + '</td>';
        h += '<td style="color:var(--red)">' + (a.nickname || a.species || '?') + '</td>';
        h += '<td style="color:var(--red)">' + (b.nickname || b.species || '?') + '</td>';
        h += '<td style="color:var(--muted)">' + (entry.cause || '?') + '</td>';
        h += '</tr>';
      });
      h += '</tbody></table></details>';
    } else {
      h += '<div style="margin-top:0.6em;color:#555">No memorial log entries yet.</div>';
    }

    document.getElementById('memorial-content').innerHTML = h;
  } catch(e) {
    document.getElementById('memorial-content').innerHTML = '<span style="color:var(--red)">Error loading memorial data</span>';
  }
}

// ── Manual Link ─────────────────────────────────────────────────────────
var _mlData = {a_options:[], b_options:[], areas:{}, area_ids:[], name_a:"Player A", name_b:"Player B"};
var _mlForceLink = false;

async function mlRefresh() {
  try {
    var r = await fetch('/api/debug/manual_link_data');
    _mlData = await r.json();
  } catch(e) { _mlData = {a_options:[], b_options:[], areas:{}, area_ids:[], name_a:"Player A", name_b:"Player B"}; }
  document.getElementById('ml-label-a').textContent = _mlData.name_a;
  document.getElementById('ml-label-b').textContent = _mlData.name_b;
  _mlPopulateMons('a');
  _mlPopulateMons('b');
  mlFilterAreas();
}

function _mlPopulateMons(pid) {
  var sel = document.getElementById('ml-' + pid);
  var cur = sel.value;
  var opts = (pid === 'a') ? _mlData.a_options : _mlData.b_options;
  var h = '<option value="">-- select --</option>';
  for (var i = 0; i < opts.length; i++) {
    var o = opts[i];
    var dis = o.linked ? ' disabled' : '';
    var lbl = o.label + (o.linked ? ' \\u2714' : '');
    h += '<option value="' + o.key + '" data-area="' + (o.pending_area||'') + '"' + dis + '>' + lbl + '</option>';
  }
  sel.innerHTML = h;
  if (cur) { sel.value = cur; }
}

function mlFilterAreas() {
  var sel = document.getElementById('ml-area');
  var cur = sel.value;
  var fi = (document.getElementById('ml-area-filter').value || '').toLowerCase();
  var areas = _mlData.areas || {};
  var ids = _mlData.area_ids || [];
  var groups = {pending:[], unseen:[], other:[]};
  for (var i = 0; i < ids.length; i++) {
    var aid = ids[i];
    var info = areas[aid] || {d:aid, s:'unseen', p:''};
    if (fi && info.d.toLowerCase().indexOf(fi) === -1 && aid.indexOf(fi) === -1) continue;
    if (info.p) groups.pending.push(aid);
    else if (info.s === 'unseen' || info.s === 'pending_a' || info.s === 'pending_b' || info.s === 'pending_both') groups.unseen.push(aid);
    else groups.other.push(aid);
  }
  var h = '<option value="">-- select area --</option>';
  function addGroup(label, arr, color) {
    if (!arr.length) return;
    h += '<option disabled style="color:' + color + ';font-weight:bold">\\u2500\\u2500\\u2500 ' + label + ' \\u2500\\u2500\\u2500</option>';
    for (var j = 0; j < arr.length; j++) {
      var aid = arr[j];
      var info = areas[aid] || {d:aid, s:'unseen', p:''};
      var suffix = '';
      if (info.p) suffix = ' [pending: ' + info.p.toUpperCase() + ']';
      else if (info.s === 'linked') suffix = ' [linked]';
      else if (info.s === 'dead_zone') suffix = ' [dead]';
      h += '<option value="' + aid + '">' + info.d + suffix + '</option>';
    }
  }
  addGroup('Pending Captures', groups.pending, '#fa0');
  addGroup('Available', groups.unseen, '#4f4');
  addGroup('Resolved', groups.other, '#888');
  sel.innerHTML = h;
  if (cur) { sel.value = cur; }
}

function mlMonChanged(player) {
  var areas = _mlData.areas || {};
  var aOpt = document.getElementById('ml-a').selectedOptions[0];
  var bOpt = document.getElementById('ml-b').selectedOptions[0];
  var warnEl = document.getElementById('ml-warn');
  warnEl.innerHTML = '';
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
    warnEl.innerHTML = '\\u26a0 A pending on ' + aDisp + ', B pending on ' + bDisp;
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
    document.getElementById('ml-warn').innerHTML = '';
  } else if (j.requires_force) {
    document.getElementById('ml-warn').innerHTML = '\\u26a0 ' + j.error;
    res.style.display = 'block';
    res.className = 'result err';
    res.innerHTML = '<button class="btn btn-orange" onclick="_mlForceLink=true;doManualLink()">Link anyway</button>';
  } else {
    showResult(res, false, j.error || 'Unknown error');
  }
}

// ── Links table + unlink ────────────────────────────────────────────────
function renderLinksTable() {
  var d = _lastStatus;
  var el = document.getElementById('ml-links-table');
  if (!d || !d.links || d.links.length === 0) {
    el.innerHTML = '<span style="color:#555;font-size:0.85em">No links yet.</span>';
    return;
  }
  var h = '<table class="ml-table"><thead><tr><th>Area</th><th>A</th><th>B</th><th>Status</th><th></th></tr></thead><tbody>';
  d.links.forEach(function(lnk, idx) {
    var stCls = lnk.status === 'alive' ? 'st-alive' : (lnk.status === 'dead' || lnk.status === 'memorial' ? 'st-dead' : 'st-memorial');
    var aLbl = lnk.a_nickname ? lnk.a_nickname + ' (' + (lnk.a_species_name||'') + ')' : (lnk.a_key ? lnk.a_key.substring(0,8) : '\\u2014');
    var bLbl = lnk.b_nickname ? lnk.b_nickname + ' (' + (lnk.b_species_name||'') + ')' : (lnk.b_key ? lnk.b_key.substring(0,8) : '\\u2014');
    h += '<tr>';
    h += '<td>' + (lnk.area_display || lnk.area_id) + '</td>';
    h += '<td>' + aLbl + '</td>';
    h += '<td>' + bLbl + '</td>';
    h += '<td class="' + stCls + '">' + lnk.status + '</td>';
    h += '<td>';
    if (lnk.status === 'dead' || lnk.status === 'memorial') {
      h += '<button class="btn btn-revive" onclick="doRevive(\\''+lnk.area_id+'\\','+idx+')" title="Revive this pair">&#x2764;</button> ';
    }
    h += '<button class="btn btn-red btn-unlink" onclick="doUnlink(\\''+lnk.area_id+'\\','+idx+')">\\u2716</button>';
    h += '</td>';
    h += '</tr>';
  });
  h += '</tbody></table>';
  el.innerHTML = h;
}

async function doUnlink(areaId, idx) {
  var d = _lastStatus;
  var lnk = d && d.links && d.links[idx];
  var desc = lnk ? (lnk.a_nickname||'?') + ' <-> ' + (lnk.b_nickname||'?') + ' on ' + (lnk.area_display || areaId) : 'link #' + idx;
  if (!confirm('Unlink ' + desc + '?\\n\\nThis removes the link entry. Both mons become available for relinking.')) return;
  var j = await api('POST', '/api/debug/unlink', {area_id: areaId, index: idx});
  showResult(document.getElementById('ml-result'), j.ok, j.message || j.error || JSON.stringify(j));
}

async function doRevive(areaId, idx) {
  var d = _lastStatus;
  var lnk = d && d.links && d.links[idx];
  var desc = lnk ? (lnk.a_nickname||'?') + ' <-> ' + (lnk.b_nickname||'?') + ' on ' + (lnk.area_display || areaId) : 'link #' + idx;
  if (!confirm('Revive ' + desc + '?\\n\\nThis sets the link back to alive. You will need to manually restore the mons from the memorial box in-game.')) return;
  var j = await api('POST', '/api/debug/revive', {area_id: areaId, index: idx});
  showResult(document.getElementById('ml-result'), j.ok, j.message || j.error || JSON.stringify(j));
}

// ── Init ────────────────────────────────────────────────────────────────
initSSE();
// Fetch initial status to populate datalists immediately
(async function() {
  try {
    var r = await fetch('/api/status');
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
</script>
</body></html>"""


def _bot_load_config(data_dir: str | None) -> dict:
    """Load bot config from data/twitch_bot.json. Returns defaults if absent."""
    bot_dir = data_dir or DATA_DIR
    path = os.path.join(bot_dir, "twitch_bot.json")
    defaults = {"channel": "", "nick": "", "prefix": "!", "command_cooldown_sec": 5, "enabled": True}
    if not os.path.exists(path):
        return dict(defaults)
    try:
        with open(path) as f:
            cfg = json.load(f)
        for k, v in defaults.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception:
        return dict(defaults)



def _bot_save_config(data_dir: str | None, cfg: dict):
    """Save bot config to data/twitch_bot.json. Tokens are never stored here — use env vars."""
    bot_dir = data_dir or DATA_DIR
    path = os.path.join(bot_dir, "twitch_bot.json")
    safe = dict(cfg)
    os.makedirs(bot_dir, exist_ok=True)
    with open(path, "w") as f:
        json.dump(safe, f, indent=2)


# ── per-connection handler ─────────────────────────────────────────────────────

class SLinkServer:
    def __init__(self, data_dir: str = None, run_id: str = None,
                 run_name: str = "", tcp_port: int = 0,
                 manager_port: int = 0,
                 species_lock: bool = False, gender_lock: bool = False,
                 type_lock: bool = False):
        self._data_dir = data_dir  # None → use global DATA_DIR (backward compat)
        self._run_id   = run_id
        self._run_name = run_name
        self._tcp_port = tcp_port
        self._manager_port = manager_port
        self._last_seq: dict[str, int] = {}
        self.state = SoulLinkState.load(data_dir=data_dir,
                                        species_lock=species_lock,
                                        gender_lock=gender_lock,
                                        type_lock=type_lock)
        # Game adapter — shared with state machine for consistent behavior.
        # Provides both rules and presentation methods.
        self.adapter = self.state.adapter
        # Track live connections: player_id → {rom_type, last_event, connected}
        self.connected_players: dict[str, dict] = {}
        # Per-player display data (updated from events, used only for status page)
        self.player_area: dict[str, str] = {"a": "", "b": ""}
        self.player_area_id: dict[str, str] = {"a": "", "b": ""}  # raw area_id for state lookups
        self.player_ball_count: dict[str, int] = {"a": 0, "b": 0}
        self.player_badges: dict[str, int] = {"a": 0, "b": 0}
        self.player_kanto_badges: dict[str, int] = {"a": 0, "b": 0}
        self.trainer_name: dict[str, str] = {
            "a": self.state.trainer_names.get("a", ""),
            "b": self.state.trainer_names.get("b", ""),
        }
        self.pc_boxes: dict[str, list] = {"a": [], "b": []}
        # key → {level, hp, maxHP, nickname, species_id, gender} — best-effort party snapshot
        self.party_details: dict[str, dict[str, dict]] = {"a": {}, "b": {}}
        # Persistent per-monKey cache of display info (species_id, nickname, level, gender).
        # Survives party↔box transitions so sprites don't go blank between ticks.
        self._mon_cache: dict[str, dict] = {}
        # Orphan keys already warned about — suppress repeat warnings on every tick.
        self._warned_orphan_keys: set[str] = set()
        # Battle state: in_battle flag + enemy team snapshot
        self.battle_state: dict[str, dict] = {
            "a": {"in_battle": False, "is_trainer_battle": False, "enemy_party": [],
                  "trainer_id": 0, "opponent_name": "", "opponent_class": "",
                  "is_doubles": False},
            "b": {"in_battle": False, "is_trainer_battle": False, "enemy_party": [],
                  "trainer_id": 0, "opponent_name": "", "opponent_class": "",
                  "is_doubles": False},
        }
        # Ring buffer of recent events for the stream overlay event feed.
        self._recent_events: deque[dict] = deque(maxlen=_EVENTS_MAX)
        self._events_path = (
            os.path.join(data_dir, "events.json") if data_dir
            else os.path.join(DATA_DIR, "events.json")
        )
        self._load_events()
        # SSE: set of asyncio.Queue (one per connected browser).
        # Each queue holds at most 1 item (coalescing — latest snapshot wins).
        self._sse_clients: set[asyncio.Queue] = set()
        self._sse_heartbeat_task: asyncio.Task | None = None
        # Rolling backup: copy links.json every 5 min when both players connected.
        self._backup_task: asyncio.Task | None = None
        self._backup_interval = 300  # seconds
        self._backup_max = 6
        self._bot_activity = []   # ring buffer, max 50 entries [{ts, text}]
        self._bot_last_error: str = ""
        self._bot_task = None
        self._bot_instance = None
        # OBS WebSocket integration
        _obs_cfg = obs_config_path(data_dir)
        self.obs = OBSController(_obs_cfg)

    def _get_sprite_html(self, species_id: int, form: int = 0) -> str:
        """Get sprite HTML by delegating to the game adapter.

        Optional `form` byte (default 0) is the alt-form discriminator from Block B
        (Gen 4+). Adapters that ignore it still produce correct base-form sprites.
        """
        if self.adapter and hasattr(self.adapter, "sprite_html"):
            return self.adapter.sprite_html(species_id, form)
        return ""  # Dead fallback

    _METHOD_ICON: dict[str, str] = {
        "Day":        "☀",
        "Night":      "🌙",
        "Surfing":    "🌊",
        "Rock Smash": "🪨",
        "Old Rod":    "🎣 Old",
        "Good Rod":   "🎣 Good",
        "Super Rod":  "🎣 Super",
    }

    def _encounter_html(self, area_id: str) -> str:
        """Return collapsible encounter widget HTML for an area, or '' if none.

        Only populated for RR runs (adapter.encounter_table returns non-None).
        """
        enc = self.adapter.encounter_table(area_id)
        if not enc:
            return ""

        methods_html = ""
        for method, entries in enc.items():
            if not entries:
                continue
            icon = self._METHOD_ICON.get(method, "")
            label = f"{icon} {method}" if icon else method
            rows = ""
            for e in entries:
                sid = e.get("species_id", 0)
                name = e.get("name", "?")
                rate = e.get("rate", 0)
                min_lv = e.get("min_level", 0)
                max_lv = e.get("max_level", 0)
                # Rate colour: hsl(rate*2, 85%, 45%) — green=high, red=low
                rate_color = f"hsl({min(rate * 2, 120)}, 85%, 48%)"
                if sid:
                    sprite_tag = self.adapter.sprite_html(sid)
                    # Replace mon-sprite class with enc-sprite for smaller 20px icon
                    sprite_tag = sprite_tag.replace('class="mon-sprite"', 'class="enc-sprite"')
                else:
                    sprite_tag = '<span class="enc-sprite"></span>'
                lv_text = f"lv{min_lv}" if min_lv == max_lv else f"lv{min_lv}–{max_lv}"
                rows += (
                    f'<div class="enc-entry">'
                    f'{sprite_tag}'
                    f'<span class="enc-name">{name}</span>'
                    f'<span class="enc-rate" style="color:{rate_color}">{rate}%</span>'
                    f'<span class="enc-lv">({lv_text})</span>'
                    f'</div>'
                )
            methods_html += (
                f'<div class="enc-method">'
                f'<span class="enc-method-label">{label}</span>'
                f'<div class="enc-list">{rows}</div>'
                f'</div>'
            )

        if not methods_html:
            return ""
        return (
            f'<details class="enc-widget">'
            f'<summary>🎯 Encounters</summary>'
            f'<div class="enc-methods">{methods_html}</div>'
            f'</details>'
        )

    def _enc_table_for_status(self, area_id: str) -> dict | None:
        """Return encounter table dict with sprite_src added to each entry.

        sprite_src is just the image URL — much smaller than sprite_html
        (~115 chars vs ~400 chars per entry). The overlay JS builds the
        <img> tag. CFRU→NatDex conversion is handled by the adapter.

        Returns None when no encounter data exists (non-RR or unmapped area).
        """
        enc = self.adapter.encounter_table(area_id)
        if not enc:
            return None
        return {
            method: [
                {**e, "sprite_src": self.adapter.sprite_src(e.get("species_id", 0))}
                for e in entries
            ]
            for method, entries in enc.items()
        }

    # rom_type string → adapter game_id mapping.
    _ROM_TYPE_TO_GAME_ID: dict[str, str] = {
        "firered": "gen3_frlge", "leafgreen": "gen3_frlge", "emerald": "gen3_frlge",
        "firered_ap": "gen3_frlge", "leafgreen_ap": "gen3_frlge",
        "firered_rr": "gen3_frlge",
        "heartgold": "gen4_hgsspt", "soulsilver": "gen4_hgsspt",
        "platinum": "gen4_hgsspt", "hgss": "gen4_hgsspt",
        "renegade_platinum": "gen4_hgsspt",  # Drayano60 difficulty hack on Platinum
        "Red": "gen1_rby", "Blue": "gen1_rby", "Yellow": "gen1_rby",
        "red": "gen1_rby", "blue": "gen1_rby", "yellow": "gen1_rby",
        "Crystal": "gen2_crystal", "crystal": "gen2_crystal",
        "pokemon_black": "gen5_bw",
        "pokemon_white": "gen5_bw",
        "pokemon_black_2": "gen5_bw",
        "pokemon_white_2": "gen5_bw",
    }

    _VARIANT_LABEL: dict[str, str] = {
        "firered": "FireRed", "leafgreen": "LeafGreen",
        "firered_ap": "FireRed (AP)", "leafgreen_ap": "LeafGreen (AP)",
        "firered_rr": "Radical Red",
        "heartgold": "HeartGold", "soulsilver": "SoulSilver",
        "platinum": "Platinum", "hgss": "HGSS",
        "Red": "Red", "Blue": "Blue", "Yellow": "Yellow",
        "red": "Red", "blue": "Blue", "yellow": "Yellow",
        "Crystal": "Crystal", "crystal": "Crystal",
        "pokemon_black": "Pokémon Black",
        "pokemon_white": "Pokémon White",
        "pokemon_black_2": "Pokémon Black 2",
        "pokemon_white_2": "Pokémon White 2",
    }

    def _page_title(self) -> str:
        """Build dynamic page title: Pokémon Soul Link Tracker — <variant> — <run name>.

        Game variant is committed once on first hello and persisted in links.json,
        so it survives server restarts and client disconnects.
        """
        parts = ["Pokémon Soul Link Tracker"]
        if self.state.rom_type:
            variant = self._VARIANT_LABEL.get(self.state.rom_type, self.state.rom_type)
            parts.append(variant)
        if self._run_name:
            parts.append(html.escape(self._run_name))
        return " — ".join(parts)

    def _notify_sse(self):
        """Push an update notification to all connected SSE clients.

        Uses coalescing: each queue holds at most 1 item.  If the queue is
        full (client hasn't consumed the previous update yet), the old item
        is replaced with a fresh sentinel so the client always gets the
        latest state when it reads.
        """
        if not self._sse_clients:
            return
        for q in self._sse_clients:
            # Drain any unconsumed item, then put the new sentinel.
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(True)
            except asyncio.QueueFull:
                pass  # should not happen after drain, but be safe

    async def _sse_heartbeat_loop(self):
        """Send SSE keepalive comments every 15 seconds to detect dead clients."""
        try:
            while True:
                await asyncio.sleep(15)
                # Heartbeat is handled inside handle_sse via a timeout on queue.get
        except asyncio.CancelledError:
            pass

    # ── Rolling backups ───────────────────────────────────────────────────────

    def _both_connected(self) -> bool:
        return (self.connected_players.get("a", {}).get("connected", False)
                and self.connected_players.get("b", {}).get("connected", False))

    def _do_backup(self):
        """Copy links.json (and events.json) → rolling backup slot.  Keeps up to _backup_max files."""
        links_path = self.state._links_path
        if not os.path.exists(links_path):
            return
        backup_dir = os.path.join(os.path.dirname(links_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        # Rotate: delete oldest if at max, shift numbers up
        for i in range(self._backup_max, 1, -1):
            for stem in ("links", "events"):
                src = os.path.join(backup_dir, f"{stem}.backup.{i - 1}.json")
                dst = os.path.join(backup_dir, f"{stem}.backup.{i}.json")
                if os.path.exists(src):
                    os.replace(src, dst)
        # Copy current as slot 1 (newest)
        shutil.copy2(links_path, os.path.join(backup_dir, "links.backup.1.json"))
        if os.path.exists(self._events_path):
            shutil.copy2(self._events_path, os.path.join(backup_dir, "events.backup.1.json"))
        log.info(f"Rolling backup saved ({backup_dir})")

    async def _backup_loop(self):
        """Background task: backup links.json every _backup_interval seconds
        while both players are actively connected."""
        try:
            while True:
                await asyncio.sleep(self._backup_interval)
                if self._both_connected():
                    try:
                        self._do_backup()
                    except Exception as e:
                        log.warning(f"Backup failed: {e}")
        except asyncio.CancelledError:
            pass

    def start_backup_task(self):
        if self._backup_task is None or self._backup_task.done():
            self._backup_task = asyncio.ensure_future(self._backup_loop())

    async def handle_sse(self, request):
        """GET /api/events — Server-Sent Events stream.

        Emits two named event types:
          - ``event: status``  — full JSON status dict (for stream overlays)
          - ``event: ping``    — empty data (triggers fetch+morph on main page)

        Clients that only need the ping can ignore ``status`` events and
        vice-versa, keeping the architecture flexible with a single endpoint.
        """
        resp = aiohttp_web.StreamResponse()
        resp.content_type = "text/event-stream"
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Accel-Buffering"] = "no"  # disable nginx buffering
        resp.force_close()  # disable HTTP keep-alive; SSE connections must not be reused
        await resp.prepare(request)

        async def _write(data: bytes) -> bool:
            """Write with a 10-second timeout. Returns False on failure/timeout."""
            try:
                await asyncio.wait_for(resp.write(data), timeout=10.0)
                return True
            except (asyncio.TimeoutError, ConnectionResetError, ConnectionAbortedError,
                    asyncio.CancelledError):
                return False
            except Exception as e:
                log.debug(f"SSE write error: {e}")
                return False

        q: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._sse_clients.add(q)
        try:
            # Send retry hint and an immediate ping so clients fetch the initial state
            if not await _write(b"retry: 3000\n\n"):
                return resp
            if not await _write(b"event: ping\ndata: \n\n"):
                return resp

            while True:
                try:
                    await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    if not await _write(b": heartbeat\n\n"):
                        break
                    continue
                except asyncio.CancelledError:
                    break

                # Real update — send a tiny ping; clients fetch /api/status themselves
                if not await _write(b"event: ping\ndata: \n\n"):
                    break
        except Exception as e:
            log.debug(f"SSE handler exited: {e}")
        finally:
            self._sse_clients.discard(q)
        return resp

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        log.info(f"Client connected: {peer}")
        player_id_for_conn: str | None = None
        try:
            async for raw in reader:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError as e:
                    log.warning(f"Bad JSON from {peer}: {e}")
                    await self._respond(writer, [{"cmd": "noop"}])
                    continue

                player_id = msg.get("player", "")
                if player_id not in VALID_PLAYERS:
                    log.warning(f"Rejected unknown player_id: {repr(player_id)} from {peer}")
                    await self._respond(writer, [{"cmd": "noop"}])
                    continue

                # Track which player owns this connection.
                if player_id_for_conn is None:
                    player_id_for_conn = player_id

                # Update connection info
                self.connected_players[player_id] = {
                    "connected":  True,
                    "last_event": msg.get("event", "?"),
                    "last_seen":  datetime.now().strftime("%H:%M:%S"),
                    "rom_type":   self.connected_players.get(player_id, {}).get("rom_type", "?"),
                }
                if msg.get("event") == "hello":
                    self.connected_players[player_id]["rom_type"] = msg.get("rom_type", "?")
                    # Resolve correct adapter from rom_type.
                    # Once rom_type is committed (set-once), the adapter is locked — ignore
                    # any later hello that carries a different rom_type (e.g. early-boot
                    # detect_variant returning 'vanilla' before IWRAM is initialised).
                    rom_type = msg.get("rom_type", "")
                    if not self.state.rom_type:
                        new_game_id = self._ROM_TYPE_TO_GAME_ID.get(rom_type)
                        new_is_rr = rom_type.endswith("_rr")
                        if new_game_id and new_game_id != self.state.adapter.game_id:
                            from server.adapters import get_adapter
                            self.state.adapter = get_adapter(new_game_id, is_rr=new_is_rr, rom_type=rom_type)
                            self.state.is_rr = new_is_rr
                            self.adapter = self.state.adapter
                            log.info(f"Adapter switched to {new_game_id} (rom_type={rom_type})")
                            log.debug(f"[ADAPTER] player={player_id}  game_id={new_game_id}  is_rr={new_is_rr}  rom_type={rom_type!r}  reason=game_id_changed")
                        elif new_is_rr != self.state.is_rr:
                            self.state.is_rr = new_is_rr
                            from server.adapters import get_adapter
                            self.state.adapter = get_adapter(
                                self.state.adapter.game_id, is_rr=new_is_rr, rom_type=rom_type)
                            self.adapter = self.state.adapter
                            log.info(f"Adapter updated: is_rr={new_is_rr}")
                            log.debug(f"[ADAPTER] player={player_id}  game_id={self.state.adapter.game_id}  is_rr={new_is_rr}  rom_type={rom_type!r}  reason=is_rr_changed")
                    elif rom_type and rom_type != self.state.rom_type:
                        log.warning(f"[{player_id}] hello rom_type={rom_type!r} ignored — "
                                    f"run already locked to {self.state.rom_type!r}")
                # Duplicate-event guard.  Detect client restarts by seq resetting to 0/1.
                seq = msg.get("seq", -1)
                if seq != -1:
                    last = self._last_seq.get(player_id, -1)
                    if seq <= last:
                        if seq <= 1 and last > 10:
                            log.info(f"[{player_id}] client restart (seq {last}→{seq}), resetting")
                            self._last_seq[player_id] = -1
                        else:
                            log.debug(f"[{player_id}] duplicate seq {seq}, skipping")
                            await self._respond(writer, [{"cmd": "noop"}])
                            continue
                    self._last_seq[player_id] = seq
                    log.debug(f"[TCP] player={player_id}  seq={seq}  last={last}  outcome=accepted  event={msg.get('event','?')}")

                commands = self._dispatch(player_id, msg)
                await self._respond(writer, commands)
                # Log non-trivial responses at DEBUG for post-mortem tracing.
                _real_cmds = [c for c in commands if c.get("cmd") not in ("noop", "resolved_areas")]
                if _real_cmds:
                    _summary = ", ".join(
                        c["cmd"] + (":" + c["key"][:8] if "key" in c else "")
                        for c in _real_cmds
                    )
                    log.debug(f"[CMD FLUSH] player={player_id}  {len(_real_cmds)} cmd(s): {_summary}")
                # Notify SSE clients after TCP response (no game-client latency impact)
                self._notify_sse()

        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            log.info(f"Client disconnected: {peer}")
            if player_id_for_conn:
                info = self.connected_players.get(player_id_for_conn, {})
                info["connected"] = False
                self.connected_players[player_id_for_conn] = info
                self._notify_sse()  # Push disconnect status to browsers
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    @staticmethod
    async def _respond(writer: asyncio.StreamWriter, commands: list):
        data = json.dumps({"commands": commands}) + "\n"
        writer.write(data.encode("utf-8"))
        await writer.drain()

    def _cache_mon_info(self, key: str, detail: dict):
        """Update the persistent per-monKey display cache from a detail dict.

        Also backfills level=0 and stale nicknames in any LinkEntry MonInfo
        for this key, so data gets corrected once the mon connects with
        live party data.
        """
        entry = self._mon_cache.get(key, {})
        for field in ("species_id", "nickname", "level", "gender", "held_item_id"):
            val = detail.get(field)
            if val:  # only overwrite with non-empty / non-zero
                entry[field] = val
        self._mon_cache[key] = entry
        # Backfill mon_stats for PC box level display (covers shiny/bonus mons)
        lv = detail.get("level", 0)
        maxhp = detail.get("maxHP", 0)
        if lv and key not in self.state.mon_stats:
            self.state.mon_stats[key] = {"level": lv}
            if maxhp:
                self.state.mon_stats[key]["maxHP"] = maxhp
        elif lv and not self.state.mon_stats.get(key, {}).get("level"):
            self.state.mon_stats[key]["level"] = lv
        # Backfill level and nickname into link entries
        nick = detail.get("nickname", "")
        species_id = detail.get("species_id", 0)
        if (lv or nick or species_id) and self.state._key_index.get(key):
            link_entry = self.state._key_index[key]
            dirty = False
            for mi in (link_entry.a, link_entry.b):
                if mi and mi.key == key:
                    if lv and not mi.level:
                        mi.level = lv
                        dirty = True
                    if nick and nick != mi.nickname:
                        mi.nickname = nick
                        dirty = True
                    if species_id and species_id != mi.species:
                        mi.species = species_id
                        dirty = True
            if dirty:
                self.state._save()

    def _mon_display_name(self, player_id: str, key: str) -> str:
        if not key:
            return "?"
        detail = self.party_details.get(player_id, {}).get(key, {})
        if detail.get("nickname"):
            return detail["nickname"]
        cached = self._mon_cache.get(key, {})
        if cached.get("nickname"):
            return cached["nickname"]
        species_id = detail.get("species_id", 0) or cached.get("species_id", 0)
        if species_id:
            return self.adapter.species_name(species_id)
        link_entry = self.state._key_index.get(key)
        if link_entry:
            for mon in (link_entry.a, link_entry.b):
                if mon and mon.key == key:
                    return mon.nickname or self.adapter.species_name(mon.species) or key[:8]
        return key[:8]

    def _load_events(self):
        """Load persisted recent events from events.json on startup."""
        try:
            with open(self._events_path, "r", encoding="utf-8") as f:
                events = json.load(f)
            self._recent_events = deque(events[:_EVENTS_MAX], maxlen=_EVENTS_MAX)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_events(self):
        """Persist the recent events ring buffer to events.json."""
        try:
            os.makedirs(os.path.dirname(self._events_path), exist_ok=True)
            with open(self._events_path, "w", encoding="utf-8") as f:
                # Belt-and-suspenders: never write more than _EVENTS_MAX entries.
                json.dump(list(self._recent_events)[:_EVENTS_MAX], f)
        except Exception as e:
            log.warning(f"Failed to save events.json: {e}")

    def _log_event(self, player_id: str, event_type: str, text: str,
                   area_id: str = "", key: str = ""):
        """Append a timestamped entry to the recent events ring buffer."""
        self._recent_events.appendleft({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "player": player_id,
            "type": event_type,
            "text": text,
            "area_id": area_id,
            "key": key,
        })
        self._save_events()

    def _dispatch(self, player_id: str, msg: dict) -> list:
        event = msg.get("event", "unknown")
        # Snapshot area state before the event so we can detect outcome transitions.
        _pre_area_state = self.state.area_states.get(msg.get("area_id", ""))
        _pre_battle = self.battle_state[player_id]["in_battle"]
        _pre_memorial_status = None
        if event == "memorialize_done":
            _pre_memorial_link = self.state._key_index.get(msg.get("key", ""))
            if _pre_memorial_link:
                _pre_memorial_status = getattr(_pre_memorial_link.status, "value", _pre_memorial_link.status)

        # Block all events from a player whose identity was rejected.
        # Only a hello with correct identity can clear the error.
        if event != "hello" and self.state.identity_error.get(player_id):
            return [{"cmd": "noop"}]

        if event == "hello":
            area    = msg.get("area_id", "")
            loc     = msg.get("loc_name", "")
            party_n = len(msg.get("party", []))
            rom     = msg.get("rom_type", "unknown")
            log.info(f"[{player_id}] hello rom={rom} area='{area or loc}' party={party_n}")

            # Run state machine first (handles identity lock check).
            cmds = self.state.handle_event(player_id, msg)

            if msg.get("_rejected"):
                # Identity mismatch — log it, surface error, but don't update display data.
                self._log_event(player_id, "hello",
                                f"REJECTED — wrong save/slot", area or loc)
                return cmds

            self._log_event(player_id, "hello",
                            f"Connected ({rom}, {party_n} mons)", loc or area)
            self.player_area[player_id] = loc or area
            self.player_area_id[player_id] = area
            # Commit ROM type once — static for the run's lifetime.
            _dirty = False
            if rom and rom != "unknown" and not self.state.rom_type:
                self.state.rom_type = rom
                _dirty = True
                log.info(f"Committed ROM type '{rom}' for this run")
            if "ball_count" in msg:
                self.player_ball_count[player_id] = msg["ball_count"]
            if "badges" in msg:
                self.player_badges[player_id] = msg["badges"]
            if "kanto_badges" in msg:
                self.player_kanto_badges[player_id] = msg["kanto_badges"]
            if "trainer_name" in msg:
                tname = msg["trainer_name"]
                self.trainer_name[player_id] = tname
                # Commit trainer name once per player — static for the run.
                if tname and not self.state.trainer_names.get(player_id):
                    self.state.trainer_names[player_id] = tname
                    _dirty = True
                    log.info(f"Committed trainer name '{tname}' for player {player_id}")
            if _dirty:
                self.state._save()
            if "pc_boxes" in msg:
                self.pc_boxes[player_id] = msg["pc_boxes"]
                for bentry in msg["pc_boxes"]:
                    bk = bentry.get("key", "")
                    if bk:
                        self._cache_mon_info(bk, bentry)
                self._check_memorial_box_contamination(player_id, msg["pc_boxes"])
            # Seed party_details from snapshot
            self.party_details[player_id] = {
                m["key"]: {
                    "level":        m.get("level", 0),
                    "hp":           m.get("hp", 1),
                    "maxHP":        m.get("maxHP", 1),
                    "nickname":     m.get("nickname", ""),
                    "species_id":   m.get("species_id", 0),
                    "held_item_id": m.get("held_item_id", m.get("held_item", 0)),
                    "ability_id":   m.get("ability_id", m.get("ability", 0)),
                    "gender":       self.adapter.gender_from_key(m["key"], m.get("species_id", 0)),
                    "moves":        m.get("moves", []),
                    "pp":           m.get("pp", []),
                    "slot":         m.get("slot", idx),
                    "active":       m.get("active", False),
                    "status_cond":  m.get("status_cond", 0),
                }
                for idx, m in enumerate(msg.get("party", [])) if m.get("key")
            }
            for k, det in self.party_details[player_id].items():
                self._cache_mon_info(k, det)
            # Seed battle state from hello (so page reflects battle immediately)
            if "in_battle" in msg:
                self.battle_state[player_id]["in_battle"] = bool(msg["in_battle"])
            if "is_trainer_battle" in msg:
                self.battle_state[player_id]["is_trainer_battle"] = bool(msg["is_trainer_battle"])
            if "enemy_party" in msg:
                self.battle_state[player_id]["enemy_party"] = msg["enemy_party"]
            return cmds
        elif event == "area_enter":
            area = msg.get("area_id", "")
            loc  = msg.get("loc_name", "")
            disp = loc or area  # prefer specific location name for display
            log.info(f"[{player_id}] area_enter → '{disp}'")
            if disp:
                self.player_area[player_id] = disp
                # Use area_id for display name resolution (has underscores for proper formatting)
                disp_name = self.adapter.area_display_name(area or disp)
                self._log_event(player_id, "area_enter",
                                f"Entered {disp_name}", disp)
            if area:
                self.player_area_id[player_id] = area
        elif event == "capture":
            key = msg.get("key", "")
            log.info(f"[{player_id}] capture key={key} lv={msg.get('level','?')} area='{msg.get('area_id','')}'")
            if key:
                sid = msg.get("species_id", 0)
                sp_name = self.adapter.species_name(sid) if sid else "?"
                self._log_event(player_id, "capture",
                                f"Caught {sp_name} Lv{msg.get('level','?')}",
                                msg.get("area_id", ""), key)
                detail = {
                    "level":        msg.get("level", 0),
                    "hp":           1,
                    "maxHP":        1,
                    "nickname":     msg.get("nickname", ""),
                    "species_id":   sid,
                    "held_item_id": msg.get("held_item_id", msg.get("held_item", 0)),
                    "ability_id":   msg.get("ability_id", msg.get("ability", 0)),
                    "gender":       self.adapter.gender_from_key(key, sid),
                }
                self.party_details[player_id][key] = detail
                self._cache_mon_info(key, detail)
        elif event == "faint":
            key = msg.get("key", "")
            log.info(f"[{player_id}] faint key={key} area='{msg.get('area_id','')}'")
            if key and key in self.party_details[player_id]:
                self.party_details[player_id][key]["hp"] = 0
                nick = self.party_details[player_id][key].get("nickname", "")
                self._log_event(player_id, "faint",
                                f"{nick or key[:8]} fainted!",
                                msg.get("area_id", ""), key)
            # Enrich msg with cached battle-state killer info for state machine killfeed tracking.
            bs = self.battle_state.get(player_id, {})
            enemy = bs.get("enemy_party") or []
            active_foe = next((e for e in enemy if e.get("hp", 1) > 0), enemy[0] if enemy else None)
            if active_foe:
                msg["_killer_species"] = active_foe.get("species_id", 0)
                msg["_killer_level"]   = active_foe.get("level", 0)
            msg["_is_trainer"] = bool(bs.get("is_trainer_battle", False))
            if msg["_is_trainer"]:
                msg["_trainer_name"] = bs.get("opponent_name", "")
                msg["_trainer_class"] = bs.get("opponent_class", "")
            # Inject current level from party_details so memorial shows death-time level.
            pd = self.party_details[player_id].get(key, {})
            if pd.get("level"):
                msg["_level"] = pd["level"]
        elif event == "no_catch":
            log.info(f"[{player_id}] no_catch area='{msg.get('area_id','')}'")
            self._log_event(player_id, "no_catch",
                            f"Missed catch at {self.adapter.area_display_name(msg.get('area_id',''))}",
                            msg.get("area_id", ""))
        elif event == "whiteout":
            log.info(f"[{player_id}] whiteout")
            for key in self.party_details[player_id]:
                self.party_details[player_id][key]["hp"] = 0
            self._log_event(player_id, "whiteout", "WHITED OUT! All party mons fainted")
        elif event == "party_to_box":
            key = msg.get("key", "")
            log.info(f"[{player_id}] party_to_box key={key}")
            self.party_details[player_id].pop(key, None)
        elif event == "stats_cache":
            key = msg.get("key", "")
            log.debug(f"[{player_id}] stats_cache key={key}")
            self.party_details[player_id].pop(key, None)
        elif event == "box_to_party":
            key = msg.get("key", "")
            log.info(f"[{player_id}] box_to_party key={key}")
            if key and key not in self.party_details[player_id]:
                # Populate from persistent cache so sprites don't go blank until next tick.
                cached = self._mon_cache.get(key, {})
                self.party_details[player_id][key] = {
                    "level":        cached.get("level", 0),
                    "hp":           1,
                    "maxHP":        1,
                    "nickname":     cached.get("nickname", ""),
                    "species_id":   cached.get("species_id", 0),
                    "held_item_id": cached.get("held_item_id", 0),
                    "gender":       cached.get("gender", ""),
                }
        elif event == "memorialize_done":
            key = msg.get("key", "")
            log.info(f"[{player_id}] memorialize_done key={key}")
            self.party_details[player_id].pop(key, None)
        elif event == "key_change":
            old_key = msg.get("old_key", "")
            new_key = msg.get("new_key", "")
            log.info(f"[{player_id}] key_change {old_key[:8]} → {new_key[:8]}")
            # Migrate party_details: move old entry to new key
            old_detail = self.party_details[player_id].pop(old_key, None)
            if old_detail:
                self.party_details[player_id][new_key] = old_detail
            # Migrate _mon_cache
            old_mon = self._mon_cache.pop(old_key, None)
            if old_mon:
                self._mon_cache[new_key] = old_mon
        elif event == "safe":
            log.debug(f"[{player_id}] safe state")
        elif event == "tick":
            if "ball_count" in msg:
                self.player_ball_count[player_id] = msg["ball_count"]
            if "badges" in msg:
                self.player_badges[player_id] = msg["badges"]
            if "kanto_badges" in msg:
                self.player_kanto_badges[player_id] = msg["kanto_badges"]
            if "trainer_name" in msg:
                self.trainer_name[player_id] = msg["trainer_name"]
            if "pc_boxes" in msg:
                self.pc_boxes[player_id] = msg["pc_boxes"]
                for bentry in msg["pc_boxes"]:
                    bk = bentry.get("key", "")
                    if bk:
                        self._cache_mon_info(bk, bentry)
                self._check_memorial_box_contamination(player_id, msg["pc_boxes"])
            if "in_battle" in msg:
                was_in_battle = self.battle_state[player_id]["in_battle"]
                now_in_battle = bool(msg["in_battle"])
                self.battle_state[player_id]["in_battle"] = now_in_battle
                if was_in_battle and not now_in_battle:
                    self.battle_state[player_id]["trainer_id"] = 0
                    self.battle_state[player_id]["opponent_name"] = ""
                    self.battle_state[player_id]["opponent_class"] = ""
                    self.battle_state[player_id]["is_trainer_battle"] = False
                    self.battle_state[player_id]["enemy_party"] = []
                    self.battle_state[player_id]["is_doubles"] = False
            if "is_trainer_battle" in msg:
                self.battle_state[player_id]["is_trainer_battle"] = bool(msg["is_trainer_battle"])
            if "trainer_id" in msg:
                tid = msg["trainer_id"]
                self.battle_state[player_id]["trainer_id"] = tid
                # Resolve trainer name/class via adapter
                tr_name, tr_class = self.adapter.trainer_info(tid)
                if tr_class:
                    self.battle_state[player_id]["opponent_name"] = tr_name
                    self.battle_state[player_id]["opponent_class"] = tr_class
                elif "opponent_name" in msg or "opponent_class" in msg:
                    # Non-RR (e.g. Gen 1/2 client emits class+name directly because
                    # trainer_id alone is ambiguous without class context). Accept
                    # whatever the client provided.
                    if msg.get("opponent_name"):
                        self.battle_state[player_id]["opponent_name"] = msg["opponent_name"]
                    if msg.get("opponent_class"):
                        self.battle_state[player_id]["opponent_class"] = msg["opponent_class"]
            if "enemy_party" in msg:
                self.battle_state[player_id]["enemy_party"] = msg["enemy_party"]
            if "is_doubles" in msg:
                self.battle_state[player_id]["is_doubles"] = bool(msg["is_doubles"])
            elif "enemy_party" in msg:
                # Passive inference: >1 active enemy implies doubles (benefits Gen 4/5 automatically).
                active_count = sum(1 for e in msg["enemy_party"] if e.get("active"))
                if active_count > 1:
                    self.battle_state[player_id]["is_doubles"] = True
            # Dupes clause: notify at wild battle start (before handle_event flushes the queue).
            if "in_battle" in msg and not was_in_battle and now_in_battle \
                    and not self.battle_state[player_id].get("is_trainer_battle"):
                _battle_area_id = msg.get("area_id", "")
                _ep = self.battle_state[player_id].get("enemy_party", [])
                _enc_species = _ep[0].get("species_id", 0) if _ep else 0
                if _battle_area_id and _enc_species:
                    # Check if partner is also in a concurrent wild battle on the same area.
                    _partner_id = "b" if player_id == "a" else "a"
                    _partner_bs = self.battle_state[_partner_id]
                    _partner_battle_species = 0
                    if (_partner_bs.get("in_battle") and not _partner_bs.get("is_trainer_battle")
                            and self.player_area_id.get(_partner_id) == _battle_area_id):
                        _partner_ep = _partner_bs.get("enemy_party", [])
                        _partner_battle_species = _partner_ep[0].get("species_id", 0) if _partner_ep else 0
                    if self.state.check_dupe_on_encounter(player_id, _battle_area_id, _enc_species,
                                                          partner_battle_species=_partner_battle_species):
                        _sp_name = self.adapter.species_name(_enc_species)
                        self._log_event(player_id, "reroll",
                                        f"🔁 Dupes clause: {_sp_name} -- reroll!", _battle_area_id)
            # Update location from tick in case area_enter was missed (e.g. on reconnect).
            tick_area = msg.get("loc_name", "") or msg.get("area_id", "")
            if tick_area:
                self.player_area[player_id] = tick_area
            tick_area_id = msg.get("area_id", "")
            if tick_area_id:
                self.player_area_id[player_id] = tick_area_id
            log.debug(f"[{player_id}] tick")
        else:
            log.debug(f"[{player_id}] unknown event '{event}' seq={msg.get('seq','?')}")

        # On tick, replace party_details entirely from the authoritative party snapshot.
        # This prevents captures that went straight to the PC box (full-party captures)
        # from appearing as phantom party mons between ticks.
        if "party" in msg and event == "tick":
            self.party_details[player_id] = {
                m["key"]: {
                    "level":        m.get("level", 0),
                    "hp":           m.get("hp", 1),
                    "maxHP":        m.get("maxHP", 1),
                    "nickname":     m.get("nickname", ""),
                    "species_id":   m.get("species_id", 0),
                    "held_item_id": m.get("held_item_id", m.get("held_item", 0)),
                    "ability_id":   m.get("ability_id", m.get("ability", 0)),
                    "gender":       self.adapter.gender_from_key(m["key"], m.get("species_id", 0)),
                    "moves":        m.get("moves", []),
                    "pp":           m.get("pp", []),
                    "slot":         m.get("slot", idx),
                    "active":       m.get("active", False),
                    "status_cond":  m.get("status_cond", 0),
                    "stat_stages":  m.get("stat_stages"),
                }
                for idx, m in enumerate(msg["party"]) if m.get("key")
            }
            for k, det in self.party_details[player_id].items():
                self._cache_mon_info(k, det)

        cmds = self.state.handle_event(player_id, msg)

        # Post-dispatch: log outcome events that require state-machine results.
        _partner = "b" if player_id == "a" else "a"
        _area_id = msg.get("area_id", "")
        if event in ("capture", "no_catch") and _area_id:
            _new_state = self.state.area_states.get(_area_id)
            if _new_state is not None and _new_state != _pre_area_state:
                _area_disp = self.adapter.area_display_name(_area_id)
                _sv = _new_state.value if hasattr(_new_state, "value") else str(_new_state)
                if _sv == "linked":
                    _cap_key = msg.get("key", "")
                    _link = self.state._key_index.get(_cap_key) if _cap_key else None
                    if _link:
                        _ma = _link.a if player_id == "a" else _link.b
                        _mb = _link.b if player_id == "a" else _link.a
                        _ma_nick = (_ma.nickname or self.adapter.species_name(_ma.species)) if _ma else "?"
                        _mb_nick = (_mb.nickname or self.adapter.species_name(_mb.species)) if _mb else "?"
                        self._log_event(player_id, "linked",
                                        f"✓ Linked {_ma_nick} × {_mb_nick} on {_area_disp}", _area_id)
                        self._log_event(_partner, "linked",
                                        f"✓ Linked {_mb_nick} × {_ma_nick} on {_area_disp}", _area_id)
                elif _sv == "dead_zone":
                    self._log_event(player_id, "dead_zone",
                                    f"☠ Dead zone: {_area_disp}", _area_id)
                    self._log_event(_partner, "dead_zone",
                                    f"☠ Dead zone: {_area_disp}", _area_id)

        if event == "faint" and msg.get("key"):
            _faint_key = msg["key"]
            _link = self.state._key_index.get(_faint_key)
            if _link:
                _p_mon = _link.b if player_id == "a" else _link.a
                if _p_mon and any(
                    c.get("cmd") == "force_faint" and c.get("key") == _p_mon.key
                    for c in self.state.queued_commands.get(_partner, [])
                ):
                    _cached = self._mon_cache.get(_p_mon.key, {})
                    _p_nick = (
                        _cached.get("nickname") or
                        self.adapter.species_name(_cached.get("species_id", 0)) or
                        _p_mon.key[:8]
                    )
                    self._log_event(_partner, "force_faint",
                                    f"⚡ {_p_nick} force fainted!",
                                    _area_id, _p_mon.key)

        if event == "capture":
            _cap_key = msg.get("key", "")
            if _cap_key and _cap_key in self.state.bonus_keys.get(player_id, set()):
                _nick = self._mon_display_name(player_id, _cap_key)
                self._log_event(player_id, "shiny",
                                f"✨ Shiny {_nick}!", _area_id, _cap_key)

        if event == "party_to_box":
            _box_key = msg.get("key", "")
            if _box_key:
                _nick = self._mon_display_name(player_id, _box_key)
                self._log_event(player_id, "party_to_box",
                                f"📦 {_nick} deposited", "", _box_key)

        if event == "box_to_party":
            _box_key = msg.get("key", "")
            if _box_key:
                _nick = self._mon_display_name(player_id, _box_key)
                self._log_event(player_id, "box_to_party",
                                f"↑ {_nick} retrieved", "", _box_key)

        if event == "memorialize_done":
            _mem_key = msg.get("key", "")
            _link = self.state._key_index.get(_mem_key) if _mem_key else None
            _post_status = getattr(getattr(_link, "status", None), "value", getattr(_link, "status", None))
            if _link and _post_status == "memorial" and _pre_memorial_status != "memorial":
                _a_name = (_link.a.nickname or self.adapter.species_name(_link.a.species)) if _link.a else "?"
                _b_name = (_link.b.nickname or self.adapter.species_name(_link.b.species)) if _link.b else "?"
                self._log_event(player_id, "memorialize",
                                f"⚰ {_a_name} × {_b_name} laid to rest", _link.area_id, _mem_key)

        if event == "key_change":
            _new_key = msg.get("new_key", "")
            _migrated = self.party_details[player_id].get(_new_key, {})
            _nick = _migrated.get("nickname", "") or msg.get("old_key", "")[:8]
            self._log_event(player_id, "key_change",
                            f"🔄 {_nick or _new_key[:8]} nature changed", "", _new_key)

        # Log clause violations (capture rejected) and dupes rerolls (no_catch suppressed).
        # gui_prompt commands are only queued for these scenarios, so they're a reliable signal.
        if event in ("capture", "no_catch"):
            for c in cmds:
                if c.get("cmd") == "gui_prompt":
                    _prompt_text = c.get("text", "")
                    if "catch again" in _prompt_text.lower():
                        self._log_event(player_id, "violation",
                                        f"⚠ {_prompt_text}", _area_id)
                    elif "reroll" in _prompt_text.lower():
                        self._log_event(player_id, "reroll",
                                        f"🔁 {_prompt_text}", _area_id)

        self._emit_obs_triggers(player_id, msg, cmds, _pre_area_state, _pre_battle)
        return cmds


    def _emit_obs_triggers(self, player_id: str, msg: dict, cmds: list,
                           pre_area_state, pre_battle: bool):
        """Collect all game events that fired this dispatch cycle and submit them
        to OBSController.submit_fired() for priority-ordered scene resolution.

        Rules are evaluated in list order — the first matching rule per target player
        wins regardless of how many events fire simultaneously.
        """
        event = msg.get("event", "")
        _area_id = msg.get("area_id", "")
        _partner = "b" if player_id == "a" else "a"

        # fired: list of (trigger_name, src_player, metadata)
        fired = []

        # battle_start / battle_end — in_battle transition from tick
        if event == "tick" and "in_battle" in msg:
            now_battle = self.battle_state[player_id]["in_battle"]
            if not pre_battle and now_battle:
                fired.append(("battle_start", player_id, {}))
                if self.battle_state[player_id].get("is_trainer_battle"):
                    fired.append(("trainer_battle_start", player_id, {}))
                else:
                    fired.append(("wild_battle_start", player_id, {}))
                _cur_area = self.player_area_id.get(player_id, "")
                if self._area_has_open_encounter(_cur_area):
                    fired.append(("battle_start_new", player_id, {}))
            elif pre_battle and not now_battle:
                fired.append(("battle_end", player_id, {}))

        if event == "faint":
            fired.append(("faint", player_id, {}))
            # link_death — partner receives force_faint command
            _faint_key = msg.get("key", "")
            if _faint_key:
                _link = self.state._key_index.get(_faint_key)
                if _link:
                    _p_mon = _link.b if player_id == "a" else _link.a
                    if _p_mon and any(
                        c.get("cmd") == "force_faint" and c.get("key") == _p_mon.key
                        for c in self.state.queued_commands.get(_partner, [])
                    ):
                        fired.append(("link_death", _partner, {}))

        if event == "whiteout":
            fired.append(("whiteout", player_id, {}))

        if event == "capture":
            fired.append(("capture", player_id, {}))
            _cap_key = msg.get("key", "")
            if _cap_key and _cap_key in self.state.bonus_keys.get(player_id, set()):
                fired.append(("shiny", player_id, {}))

        if event == "area_enter":
            fired.append(("area_enter", player_id, {"area_id": _area_id}))
            if self._area_has_open_encounter(_area_id):
                fired.append(("area_enter_new", player_id, {"area_id": _area_id}))

        if event == "party_to_box":
            fired.append(("party_to_box", player_id, {}))

        if event == "box_to_party":
            fired.append(("box_to_party", player_id, {}))

        if event == "memorialize_done":
            fired.append(("memorialize_done", player_id, {}))

        # linked / dead_zone — area state transition post-dispatch
        if event in ("capture", "no_catch") and _area_id:
            _new_state = self.state.area_states.get(_area_id)
            if _new_state is not None and _new_state != pre_area_state:
                _sv = _new_state.value if hasattr(_new_state, "value") else str(_new_state)
                if _sv == "linked":
                    fired.append(("linked", player_id, {}))
                    fired.append(("linked", _partner, {}))
                elif _sv == "dead_zone":
                    fired.append(("dead_zone", player_id, {}))
                    fired.append(("dead_zone", _partner, {}))

        if self.state.run_over:
            fired.append(("run_over", player_id, {}))

        if fired:
            self.obs.submit_fired(fired)

    def _area_display(self, area_id: str) -> str:
        """Return a human-readable display name for area_id, handling bonus pair synthetic IDs."""
        if area_id.startswith("_bonus_"):
            return "✦ Bonus Pair"
        return self.adapter.area_display_name(area_id)

    def _area_has_open_encounter(self, area_id: str) -> bool:
        """True if area_id is an active nuzlocke area that hasn't been fully resolved.

        Returns False if: area not tracked, already linked, or dead zone.
        """
        if not area_id:
            return False
        state = self.state.area_states.get(area_id)
        if state is None:
            return False
        sv = state.value if hasattr(state, "value") else str(state)
        return sv not in ("linked", "dead_zone")

    def _build_status_dict(self) -> dict:
        """Serialize current server state to a JSON-safe dict."""
        s = self.state

        def _enrich_killer(killer):
            """Add species_name to a killer dict for the memorial/killfeed."""
            if not killer:
                return killer
            k = dict(killer)
            sp = k.get("species", 0)
            if sp:
                k["species_name"] = self.adapter.species_name(sp)
            return k

        def _enrich_party(pid):
            """Add species_name, ability_name, sprite_html, and move_details to each party detail entry."""
            raw = self.party_details.get(pid, {})
            enriched = {}
            for key, det in raw.items():
                d = dict(det)
                sid = d.get("species_id", 0)
                form = d.get("form", 0)
                d["species_name"] = self.adapter.species_name(sid) if sid else ""
                d["sprite_html"] = self._get_sprite_html(sid, form) if sid else ""
                aid = d.get("ability_id", 0)
                d["ability_name"] = self.adapter.ability_name(aid, sid) if aid else ""
                # Enrich moves: resolve raw move IDs -> full move detail dicts.
                # Gen 3 sends pp_bonuses as a packed bitfield (2 bits per move).
                # Gen 4 sends pp_ups as a list[4]. Support both shapes.
                raw_moves = d.get("moves", [])
                raw_pp = d.get("pp", [])
                pp_bonuses = d.get("pp_bonuses", 0)
                pp_ups_list = d.get("pp_ups") or []
                move_details = []
                for idx, mid in enumerate(raw_moves):
                    if mid and mid > 0:
                        md = self.adapter.move_data(mid)
                        if md:
                            md = dict(md)
                            base_pp = md.get("pp", 0)
                            if idx < len(pp_ups_list):
                                pp_ups = pp_ups_list[idx]
                            else:
                                pp_ups = (pp_bonuses >> (idx * 2)) & 0x3
                            if base_pp:
                                md["pp"] = base_pp + (base_pp * pp_ups) // 5
                            md["current_pp"] = raw_pp[idx] if idx < len(raw_pp) else md["pp"]
                            move_details.append(md)
                d["move_details"] = move_details
                enriched[key] = d
            return enriched

        def _enrich_box(pid):
            """Add move_details to PC box entries."""
            raw_boxes = self.pc_boxes.get(pid, [])
            enriched = []
            for bentry in raw_boxes:
                b = dict(bentry)
                raw_moves = b.get("moves", [])
                move_details = []
                for mid in raw_moves:
                    if mid and mid > 0:
                        md = self.adapter.move_data(mid)
                        if md:
                            md = dict(md)
                            md["current_pp"] = md.get("pp", 0)  # box mons: show max PP
                            move_details.append(md)
                b["move_details"] = move_details
                enriched.append(b)
            return enriched

        def _enrich_battle_state(pid):
            """Add sprite_html, species_name, and move_details to each enemy_party entry."""
            bs = dict(self.battle_state.get(pid, {"in_battle": False, "enemy_party": []}))
            ep = bs.get("enemy_party", [])
            enriched = []
            for em in ep:
                em2 = dict(em)
                sid = em2.get("species_id", 0)
                form = em2.get("form", 0)
                if sid and not em2.get("sprite_html"):
                    em2["sprite_html"] = self._get_sprite_html(sid, form)
                if sid and not em2.get("species_name"):
                    em2["species_name"] = self.adapter.species_name(sid)
                # Enrich moves: resolve raw move IDs -> full move detail dicts (mirrors _enrich_party).
                # Gen 3 sends pp_bonuses (packed u8); Gen 4 sends pp_ups list[4]. Support both.
                raw_moves = em2.get("moves", [])
                raw_pp = em2.get("pp", [])
                pp_bonuses = em2.get("pp_bonuses", 0)
                pp_ups_list = em2.get("pp_ups") or []
                move_details = []
                for idx, mid in enumerate(raw_moves):
                    if mid and mid > 0:
                        md = self.adapter.move_data(mid)
                        if md:
                            md = dict(md)
                            base_pp = md.get("pp", 0)
                            if idx < len(pp_ups_list):
                                pp_ups = pp_ups_list[idx]
                            else:
                                pp_ups = (pp_bonuses >> (idx * 2)) & 0x3
                            if base_pp:
                                md["pp"] = base_pp + (base_pp * pp_ups) // 5
                            md["current_pp"] = raw_pp[idx] if idx < len(raw_pp) else md["pp"]
                            move_details.append(md)
                em2["move_details"] = move_details
                enriched.append(em2)
            bs["enemy_party"] = enriched
            return bs

        return {
            "players": {
                pid: {
                    "connected":      self.connected_players.get(pid, {}).get("connected", False),
                    "rom_type":       self.connected_players.get(pid, {}).get("rom_type", "?"),
                    "last_event":     self.connected_players.get(pid, {}).get("last_event", "—"),
                    "last_seen":      self.connected_players.get(pid, {}).get("last_seen", "—"),
                    "nuzlocke_active": s.pokeballs_obtained.get(pid, False),
                    "current_area":   self.player_area.get(pid, ""),
                    "current_area_id": self.player_area_id.get(pid, ""),
                    "current_area_display": self.adapter.area_display_name(
                        self.player_area_id.get(pid, "") or self.player_area.get(pid, "")
                    ),
                    "ball_count":     self.player_ball_count.get(pid, 0),
                    "badges":         self.player_badges.get(pid, 0),
                    "kanto_badges":   self.player_kanto_badges.get(pid, 0),
                    "trainer_name":   self.trainer_name.get(pid, ""),
                    "pc_boxes":       _enrich_box(pid),
                    "party_keys":     self._get_party_ordered(pid),
                    "party_details":  _enrich_party(pid),
                    "queued":         len(s.queued_commands.get(pid, [])),
                    "battle_state":   _enrich_battle_state(pid),
                    "identity_error": s.identity_error.get(pid, ""),
                    "encounter_table": self._enc_table_for_status(
                        self.player_area_id.get(pid, "") or self.player_area.get(pid, "")
                    ),
                }
                for pid in ["a", "b"]
            },
            "links": [
                {
                    "area_id":    e.area_id,
                    "area_display": self._area_display(e.area_id),
                    "a_key":      e.a.key if e.a else None,
                    "a_nickname": e.a.nickname if e.a else "",
                    "a_species":  e.a.species if e.a else 0,
                    "a_species_name": self.adapter.species_name(e.a.species) if e.a and e.a.species else "",
                    "a_sprite_html": self._get_sprite_html(e.a.species) if e.a and e.a.species else "",
                    "a_level":    self._resolve_level("a", e.a),
                    "a_shiny":    e.a.is_shiny if e.a else False,
                    "b_key":      e.b.key if e.b else None,
                    "b_nickname": e.b.nickname if e.b else "",
                    "b_species":  e.b.species if e.b else 0,
                    "b_species_name": self.adapter.species_name(e.b.species) if e.b and e.b.species else "",
                    "b_sprite_html": self._get_sprite_html(e.b.species) if e.b and e.b.species else "",
                    "b_level":    self._resolve_level("b", e.b),
                    "b_shiny":    e.b.is_shiny if e.b else False,
                    "a_enc_species": e.encounter_a.species if e.encounter_a else 0,
                    "a_enc_level":   e.encounter_a.level   if e.encounter_a else 0,
                    "b_enc_species": e.encounter_b.species if e.encounter_b else 0,
                    "b_enc_level":   e.encounter_b.level   if e.encounter_b else 0,
                    "status":     e.status.value,
                }
                for e in s.links
            ],
            "area_states": {k: v.value for k, v in s.area_states.items()},
            "pending_captures": {
                area: {
                    pid: {
                        "key": mon.key, "nickname": mon.nickname,
                        "species": mon.species, "level": mon.level,
                        "species_name": self.adapter.species_name(mon.species) if mon.species else "",
                    }
                    for pid, mon in players.items()
                }
                for area, players in s.pending_captures.items()
            },
            "rules": {
                "species_lock": s.species_lock,
                "gender_lock": s.gender_lock,
                "type_lock": s.type_lock,
            },
            "recent_events": list(self._recent_events),
            "killfeed": sorted(
                [
                    {
                        "killed_at":        e.killed_at,
                        "area_id":          e.area_id,
                        "area_display":     self._area_display(e.area_id),
                        "cause":            e.cause,
                        "killer":           _enrich_killer(e.killer),
                        "initiating_player": e.initiating_player,
                        "a_key":      e.a.key      if e.a else None,
                        "a_nickname": e.a.nickname if e.a else "",
                        "a_species":  e.a.species  if e.a else 0,
                        "a_species_name": self.adapter.species_name(e.a.species) if e.a and e.a.species else "",
                        "a_sprite_html": self._get_sprite_html(e.a.species) if e.a and e.a.species else "",
                        "a_level":    self._resolve_level("a", e.a),
                        "b_key":      e.b.key      if e.b else None,
                        "b_nickname": e.b.nickname if e.b else "",
                        "b_species":  e.b.species  if e.b else 0,
                        "b_species_name": self.adapter.species_name(e.b.species) if e.b and e.b.species else "",
                        "b_sprite_html": self._get_sprite_html(e.b.species) if e.b and e.b.species else "",
                        "b_level":    self._resolve_level("b", e.b),
                        "status":     e.status.value,
                    }
                    for e in s.links if e.killed_at
                ],
                key=lambda x: x["killed_at"],
                reverse=True,
            ),
            "run_over": s.run_over,
            "attempts_count": s.attempts_count,
            "bonus_keys": {
                pid: sorted(s.bonus_keys.get(pid, set()))
                for pid in ["a", "b"]
            },
            "pending_bonus": {
                pid: list(s.pending_bonus.get(pid, []))
                for pid in ["a", "b"]
            },
            "badge_slugs": self.adapter.gym_badge_slugs(s.rom_type or ""),
        }

    def _build_status_html(self) -> str:
        d = self._build_status_dict()
        parts = []
        s = self.state

        def mon_label(key_val, nickname, species_id, gender="", shiny=False):
            nick = html.escape(nickname) if nickname else ""
            sp_name = html.escape(self.adapter.species_name(species_id)) if species_id else ""
            sym = _GENDER_SYMBOL.get(gender, "")
            sym_html = (f' <span class="gender-{gender}">{html.escape(sym)}</span>' if sym else "")
            shiny_html = ' <span class="shiny-star">✦</span>' if shiny else ""
            if nick and sp_name:
                return f"{nick}{shiny_html}{sym_html} <span class='dim'>({sp_name})</span>"
            elif nick:
                return f"{nick}{shiny_html}{sym_html}"
            elif sp_name:
                return f"{sp_name}{shiny_html}{sym_html}"
            return html.escape(key_val[:8]) + "…"

        def _enc_status(a_state: str, b_state: str, na: str, nb: str) -> str:
            """Build a text status cell for pending encounters, matching the linked/dead style.
            a_state/b_state: 'caught', 'entered', or 'none'.
            na/nb: trainer display names."""
            _PSTATE_ICON = {
                "caught":  "✓",
                "entered": "⏳",
                "none":    "❌",
            }
            _PSTATE_WORD = {
                "caught":  "caught",
                "entered": "pending capture",
                "none":    "not visited",
            }
            a_icon = _PSTATE_ICON[a_state]
            b_icon = _PSTATE_ICON[b_state]
            a_word = _PSTATE_WORD[a_state]
            b_word = _PSTATE_WORD[b_state]
            return (
                f'<span class="pending">'
                f'{html.escape(na)}: {a_icon} {a_word}<br>'
                f'{html.escape(nb)}: {b_icon} {b_word}'
                f'</span>'
            )

        # ── GAME OVER banner ──────────────────────────────────────────────────
        if d.get("run_over"):
            parts.append(
                '<div style="background:#b00;color:#fff;text-align:center;padding:1em 0.5em;'
                'font-size:1.8em;font-weight:bold;letter-spacing:0.15em;border-radius:8px;'
                'margin-bottom:1em;text-shadow:2px 2px 4px #000">'
                '💀 GAME OVER — SOUL LINK 💀</div>'
            )

        # ── Lock Rules banner ─────────────────────────────────────────────────
        lock_badges = []
        if s.species_lock:
            lock_badges.append('<span class="badge badge-lock">🧬 Species Clause</span>')
        if s.gender_lock:
            lock_badges.append('<span class="badge badge-lock">⚥ Gender Clause</span>')
        if s.type_lock:
            lock_badges.append('<span class="badge badge-lock">🔮 Type Clause</span>')
        if lock_badges:
            parts.append(f'<div class="lock-rules">Rules: {" ".join(lock_badges)}</div>')

        # ── Attempt counter ───────────────────────────────────────────────────
        attempts = s.attempts_count
        parts.append(
            f'<div class="attempts-bar" id="attempts-bar" data-count="{attempts}">'
            f'<span class="dim">Attempt:</span>'
            f'<span class="attempts-num">#{attempts}</span>'
            f'<button class="adj-btn" onclick="adjAttempts(-1)">&#8722;</button>'
            f'<button class="adj-btn" onclick="adjAttempts(+1)">+</button>'
            f'</div>'
        )

        # ── Players (side-by-side cards) ─────────────────────────────────────
        parts.append('<h2>Players</h2><div class="players-grid">')
        ROM_LABEL = {
            "firered": "FireRed",
            "leafgreen": "LeafGreen",
            "firered_ap": "FireRed (AP)",
            "leafgreen_ap": "LeafGreen (AP)",
            "firered_rr": "FireRed (Radical Red)",
            "leafgreen_rr": "LeafGreen (Radical Red)",
            "heartgold": "HeartGold",
            "soulsilver": "SoulSilver",
            "platinum": "Platinum",
            "hgss": "HGSS",
            "red": "Red", "blue": "Blue", "yellow": "Yellow",
            "Red": "Red", "Blue": "Blue", "Yellow": "Yellow",
        }
        # Gen 1 has no abilities — hide that column
        has_abilities = not (self.adapter and self.adapter.game_id in ("gen1_rby", "gen2_crystal"))
        for pid in ["a", "b"]:
            p = d["players"][pid]
            is_online = p["connected"]
            card_cls  = "online" if is_online else "offline"
            conn_badge = ('<span class="badge badge-online">&#9679; online</span>'
                          if is_online else
                          '<span class="badge badge-offline">&#9675; offline</span>')
            nuz_badge = ('<span class="badge badge-active">Nuzlocke active</span>'
                         if p["nuzlocke_active"] else
                         '<span class="badge badge-waiting">Waiting for Pokéballs</span>')
            pending_bonus_cnt = len(s.pending_bonus.get(pid, []))
            pending_bonus_badge = (
                f'<span class="badge badge-bonus">&#10022; {pending_bonus_cnt} bonus pending</span>'
                if pending_bonus_cnt > 0 else ""
            )
            # Gym badge icons — 8 colored circles, earned ones are bright
            # badges is a bitmask: bit 0 = Boulder, bit 1 = Cascade, etc.
            badge_mask = p.get("badges", 0)
            GYM_BADGES = [
                ("#a0a0a0", "Boulder Badge"),   # bit 0 - Brock (gray/stone)
                ("#4488ff", "Cascade Badge"),    # bit 1 - Misty (blue/water)
                ("#ffcc00", "Thunder Badge"),    # bit 2 - Lt. Surge (yellow/electric)
                ("#44cc44", "Rainbow Badge"),    # bit 3 - Erika (green/grass)
                ("#cc44cc", "Soul Badge"),       # bit 4 - Koga (purple/poison)
                ("#ff6688", "Marsh Badge"),      # bit 5 - Sabrina (pink/psychic)
                ("#ff4400", "Volcano Badge"),    # bit 6 - Blaine (red/fire)
                ("#88cc44", "Earth Badge"),      # bit 7 - Giovanni (olive/ground)
            ]
            gym_html = '<span class="gym-badges">'
            for i, (color, name) in enumerate(GYM_BADGES):
                earned = "earned" if (badge_mask & (1 << i)) else ""
                gym_html += f'<span class="gym-badge {earned}" style="background:{color}" title="{name}"></span>'
            gym_html += '</span>'
            rom_lbl   = ROM_LABEL.get(p["rom_type"], p["rom_type"])
            area_disp = self.adapter.area_display_name(p.get("current_area_id") or p["current_area"]) or '<span class="dim">unknown</span>'
            balls     = p["ball_count"]
            balls_cls = "yes" if balls > 0 else "warn"
            trainer   = html.escape(p.get("trainer_name", ""))
            trainer_str = f'<span style="color:#ff0">{trainer}</span> &mdash; ' if trainer else ""

            parts.append(f'<div class="player-card {card_cls}">')
            _safe_run = re.sub(r'[^\w-]', '_', self._run_name or self._run_id or "SLink").strip('_') or "SLink"
            dl_icon = (
                f'<a class="launcher-dl" href="/launcher/{pid}" download="slink_{_safe_run}_{pid}.lua" '
                f'title="Download BizHawk launcher script for Player {pid.upper()}">'
                f'&#11015;</a>'
            )
            enc_html = self._encounter_html(p.get("current_area_id") or "")
            parts.append(
                f'<div class="card-hdr">'
                f'<h3>{trainer_str}Player {pid.upper()} &mdash; {rom_lbl}{conn_badge}{nuz_badge}{pending_bonus_badge}{gym_html}</h3>'
                f'<div class="card-hdr-right">{dl_icon}</div></div>'
            )
            parts.append(
                f'<div class="info-row">'
                f'<span>&#128205; <b class="area">{area_disp}</b></span>'
                f'<span>&#9702; Pokéballs: <b class="{balls_cls}">{balls}</b></span>'
                f'<span>Last: <b>{p["last_event"]}</b> @ {p["last_seen"]}</span>'
                f'</div>'
            )
            if enc_html:
                parts.append(enc_html)
            # Identity error banner
            id_err = p.get("identity_error", "")
            if id_err:
                parts.append(
                    f'<div style="background:#600;color:#fcc;padding:0.5em 0.8em;'
                    f'border:1px solid #f44;border-radius:4px;margin:0.4em 0;'
                    f'font-weight:bold;">'
                    f'&#9888; {html.escape(id_err)}'
                    f'</div>'
                )

            # Build reverse lookup: key → (area_id, waiting_for_partner_id)
            # so unlinked mons can show which area they're pending in.
            pending_key_area: dict[str, str] = {}
            for pc_area, pc_players in d["pending_captures"].items():
                for pc_pid, pc_info in pc_players.items():
                    if pc_pid == pid:
                        pending_key_area[pc_info["key"]] = pc_area

            # Party table
            # Battle state (shown above party)
            bs = p.get("battle_state", {})
            if bs.get("in_battle"):
                is_trainer = bs.get("is_trainer_battle", False)
                battle_lbl = "Trainer Battle" if is_trainer else "Wild Battle"
                opp_name = html.escape(bs.get("opponent_name", "")) if is_trainer else ""
                opp_class = html.escape(bs.get("opponent_class", "")) if is_trainer else ""
                if opp_name:
                    if opp_class:
                        battle_lbl = f"vs {opp_class} {opp_name}"
                    else:
                        battle_lbl = f"vs {opp_name}"
                elif opp_class:
                    battle_lbl = f"vs {opp_class}"
                # Check if this is a new encounter (wild battle in an unresolved area)
                # Only show for nuzlocke-active players — pre-nuzlocke battles are not encounters.
                new_enc = False
                if not is_trainer and p.get("nuzlocke_active", False):
                    cur_area = p.get("current_area_id", "")
                    area_st = d["area_states"].get(cur_area, "unseen")
                    has_pending = cur_area in d.get("pending_captures", {}) and pid in d["pending_captures"][cur_area]
                    if cur_area and area_st not in ("linked", "dead_zone") and not has_pending:
                        new_enc = True
                new_enc_badge = ' <span style="color:#5f5;font-weight:bold">★ NEW ENCOUNTER</span>' if new_enc else ""
                doubles_chip = (' <span class="dbl-chip">⚔⚔&nbsp;DOUBLES</span>'
                                if bs.get("is_doubles") else "")
                parts.append('<div class="battle-panel">')
                parts.append(f'<h4 style="margin:0 0 0.3em">⚔ IN BATTLE &mdash; {battle_lbl}{new_enc_badge}{doubles_chip}</h4>')
                enemy_party = bs.get("enemy_party", [])
                if enemy_party:
                    parts.append(f'<table class="foe-table"><tr><th></th><th>Foe</th><th>Lv</th><th>HP</th><th>Type</th>{"<th>Ability</th>" if has_abilities else ""}</tr>')
                    for ei, em in enumerate(enemy_party):
                        esid   = em.get("species_id", 0)
                        elv    = em.get("level", 0)
                        ehp    = em.get("hp", 0)
                        emaxHP = em.get("maxHP", 1)
                        active = em.get("active", False)
                        eaid   = em.get("ability_id", 0)
                        eiid   = em.get("held_item_id", 0)
                        esc    = em.get("status_cond", 0)
                        ename  = html.escape(self.adapter.species_name(esid)) if esid else "?"
                        eabl   = self.adapter.ability_name(eaid, esid) if eaid else ""
                        eadesc = self.adapter.ability_description(eaid) if eaid else ""
                        eitem  = self.adapter.item_name(eiid) if eiid else ""
                        eitem_html = (f'<span class="held-item">{html.escape(eitem)}</span>'
                                      if eitem else "")
                        esprite = self._get_sprite_html(esid)
                        etype_cell = _type_badges_html(esid, adapter=self.adapter)
                        pct    = max(0, min(100, int(ehp / emaxHP * 100))) if emaxHP else 0
                        bar_cls = "hp-high" if pct > 50 else ("hp-mid" if pct > 20 else "hp-low")
                        hp_bar = (
                            f'<div class="hp-bar-bg">'
                            f'<div class="hp-bar {bar_cls}" style="width:{pct}%"></div>'
                            f'</div>'
                            f'<span class="dim">{ehp}/{emaxHP}</span>'
                            + _status_icon_html(esc)
                            + (active and _stat_stages_html(em.get("stat_stages")) or "")
                        )
                        foe_cls = "fainted" if ehp == 0 else ("active-foe" if active else "")
                        active_marker = "⚔ " if active else ""
                        foe_key = em.get("key", f"foe-{ei}")
                        abl_html = (f'<span class="ability" title="{html.escape(eadesc)}">{html.escape(eabl)}</span>'
                                    if eabl else '<span class="dim">—</span>')
                        parts.append(
                            f'<tr class="{foe_cls}" data-key="{html.escape(foe_key)}">'
                            f'<td>{esprite}</td>'
                            f'<td>{active_marker}{ename}{eitem_html}</td>'
                            f'<td>{elv}</td>'
                            f'<td>{hp_bar}</td>'
                            f'<td>{etype_cell}</td>'
                            f'{"<td>" + abl_html + "</td>" if has_abilities else ""}</tr>'
                        )
                        emove_html = _move_table_html(em.get("move_details", []),
                                                      mon_key=f"enemy:{ei}")
                        if emove_html:
                            foe_cols = 6 if has_abilities else 5
                            parts.append(
                                f'<tr class="foe-moves-row" data-key="{html.escape(foe_key)}:moves">'
                                f'<td colspan="{foe_cols}">{emove_html}</td></tr>'
                            )
                    parts.append("</table>")
                else:
                    parts.append('<p class="empty">No foe data yet.</p>')
                # ── Phase 3: calc preview data div (rendered by SLinkCalc JS) ──
                if getattr(s, 'is_rr', False):
                    _pkeys = p.get("party_keys", [])
                    _pdetails = p.get("party_details", {})
                    _atk = None
                    _atk_key = None
                    for _pk in _pkeys:
                        _d = _pdetails.get(_pk, {})
                        if _d.get("active") and _d.get("hp", 0) > 0:
                            _atk = _d
                            _atk_key = _pk
                            break
                    if not _atk:
                        for _pk in _pkeys:
                            _d = _pdetails.get(_pk, {})
                            if _d.get("hp", 0) > 0:
                                _atk = _d
                                _atk_key = _pk
                                break
                    _def = next(
                        (em for em in enemy_party if em.get("active")),
                        next((em for em in enemy_party if em.get("hp", 0) > 0), None))
                    if _atk and _def and _atk_key:
                        _asid = _atk.get("species_id", 0)
                        _esid = _def.get("species_id", 0)
                        _aname = html.escape(self.adapter.species_name(_asid)) if _asid else ""
                        _ename = html.escape(self.adapter.species_name(_esid)) if _esid else ""
                        _amoves = [m for m in (_atk.get("moves") or []) if m][:4]
                        _amoves_json = html.escape(json.dumps(_amoves))
                        _ehp  = _def.get("hp", 0)
                        _emhp = max(_def.get("maxHP", 1), 1)
                        _ehp_pct = max(0, min(100, int(_ehp / _emhp * 100)))
                        _tkey = ""
                        _istr = "0"
                        if is_trainer and bs.get("opponent_class") and bs.get("opponent_name"):
                            _tkey = html.escape(
                                f"{bs['opponent_class']} {bs['opponent_name']}")
                            _istr = "1"
                        _abl = html.escape(_atk.get("ability_name", ""))
                        _itm = html.escape(
                            self.adapter.item_name(_atk.get("held_item_id", 0)))
                        parts.append(
                            f'<div id="calc-preview-{pid}" class="calc-preview"'
                            f' data-in-battle="1"'
                            f' data-trainer-key="{_tkey}"'
                            f' data-is-trainer="{_istr}"'
                            f' data-player-species="{_aname}"'
                            f' data-player-level="{_atk.get("level", 0)}"'
                            f' data-player-nature="{html.escape(_nature_from_key(_atk_key))}"'
                            f' data-player-ability="{_abl}"'
                            f' data-player-item="{_itm}"'
                            f' data-player-moves="{_amoves_json}"'
                            f' data-enemy-species="{_ename}"'
                            f' data-enemy-level="{_def.get("level", 0)}"'
                            f' data-enemy-hp-pct="{_ehp_pct}"'
                            f' style="display:none"></div>'
                        )
                parts.append('</div>')

            # Party
            party_keys = p["party_keys"]
            if party_keys:
                q = p["queued"]
                q_str = f'<span class="warn">{q} queued</span>' if q > 0 else ""
                abl_hdr = '<th>Ability</th>' if has_abilities else ''
                parts.append(f'<table><thead><tr><th>Pokémon</th><th>Lv</th><th>HP</th><th>Type</th>{abl_hdr}<th>Partner</th><th>Link</th></tr></thead><tbody>')
                for key in party_keys:
                    detail      = p["party_details"].get(key, {})
                    level       = detail.get("level", 0)
                    hp          = detail.get("hp", 1)
                    maxhp       = detail.get("maxHP", 1)
                    sid         = detail.get("species_id", 0)
                    item_id     = detail.get("held_item_id", 0)
                    is_active   = detail.get("active", False)
                    row_cls     = "fainted" if hp == 0 else ("active-mon" if is_active else "")
                    lv_str      = str(level) if level else '<span class="dim">?</span>'
                    item_str    = self.adapter.item_name(item_id)
                    item_html   = (f'<span class="held-item">{html.escape(item_str)}</span>'
                                   if item_str else "")
                    # Shiny: unlinked shiny (still in bonus_keys) or linked MonInfo.is_shiny
                    _party_entry = s._key_index.get(key)
                    _own_mi = (_party_entry.a if pid == "a" else _party_entry.b) if _party_entry else None
                    is_shiny_mon = key in s.bonus_keys.get(pid, set()) or bool(_own_mi and _own_mi.is_shiny)
                    active_pfx  = '⚔ ' if is_active else ''
                    sprite_html = self._get_sprite_html(sid)
                    mon_str     = (
                        f'<div style="display:inline-flex;align-items:center;gap:4px">'
                        + (f'<div style="flex-shrink:0">{sprite_html}</div>' if sprite_html else '')
                        + f'<div>{active_pfx}{mon_label(key, detail.get("nickname", ""), sid, detail.get("gender", ""), shiny=is_shiny_mon)}{item_html}</div>'
                        + f'</div>'
                    )
                    pct     = max(0, min(100, int(hp / maxhp * 100))) if maxhp else 0
                    bar_cls = "hp-high" if pct > 50 else ("hp-mid" if pct > 20 else "hp-low")
                    status_cond = detail.get("status_cond", 0)
                    is_active   = detail.get("active", False)
                    hp_cell = (
                        f'<div class="hp-bar-bg">'
                        f'<div class="hp-bar {bar_cls}" style="width:{pct}%"></div>'
                        f'</div>'
                        f'<span class="dim">{hp}/{maxhp}</span>'
                        + _status_icon_html(status_cond)
                        + (is_active and _stat_stages_html(detail.get("stat_stages")) or "")
                    )
                    type_cell = _type_badges_html(sid, adapter=self.adapter)
                    abl_name = detail.get("ability_name", "")
                    abl_id = detail.get("ability_id", 0)
                    abl_desc = self.adapter.ability_description(abl_id) if abl_id else ""
                    ability_cell = (f'<span class="ability" title="{html.escape(abl_desc)}">{html.escape(abl_name)}</span>'
                                   if abl_name else '<span class="dim">—</span>')

                    entry = s._key_index.get(key)
                    if entry:
                        p_mon = entry.b if pid == "a" else entry.a
                        if p_mon:
                            p_pid = "b" if pid == "a" else "a"
                            p_gender = self.adapter.gender_from_key(p_mon.key, p_mon.species)
                            # Prefer live nickname from partner's party/box data
                            p_nick = p_mon.nickname
                            p_det = self.party_details.get(p_pid, {}).get(p_mon.key)
                            if p_det and p_det.get("nickname"):
                                p_nick = p_det["nickname"]
                            else:
                                for bx_e in self.pc_boxes.get(p_pid, []):
                                    if bx_e.get("key") == p_mon.key and bx_e.get("nickname"):
                                        p_nick = bx_e["nickname"]
                                        break
                            partner_str = mon_label(p_mon.key, p_nick, p_mon.species, p_gender,
                                                    shiny=p_mon.is_shiny)
                        else:
                            partner_str = '<span class="dim">—</span>'
                        link_cls = entry.status.value
                        link_lbl = entry.status.value
                    else:
                        pend_area = pending_key_area.get(key)
                        if pend_area:
                            partner_id = "b" if pid == "a" else "a"
                            partner_name = html.escape(
                                d["players"][partner_id].get("trainer_name") or partner_id.upper()
                            )
                            area_lbl = html.escape(self.adapter.area_display_name(pend_area))
                            partner_str = (
                                f'<span class="pending_b" style="font-size:0.85em">'
                                f'waiting for <b>{partner_name}</b> @ {area_lbl}'
                                f'</span>'
                            )
                            link_cls = "pending_b"
                            link_lbl = "pending"
                        elif key in d.get("bonus_keys", {}).get(pid, []):
                            partner_str = '<span style="color:#ffd700">★ Shiny Clause</span>'
                            link_cls    = "alive"
                            link_lbl    = "★ bonus"
                        else:
                            partner_str = '<span class="dim">unlinked</span>'
                            link_cls    = "dim"
                            link_lbl    = "—"

                    abl_td = f'<td>{ability_cell}</td>' if has_abilities else ''
                    colspan = 7 if has_abilities else 6
                    move_details = detail.get("move_details", [])
                    move_html = _move_table_html(move_details, mon_key=key)
                    parts.append(
                        f'<tr class="{row_cls}" data-key="{html.escape(key)}">'
                        f'<td>{mon_str}</td>'
                        f'<td>{lv_str}</td>'
                        f'<td>{hp_cell}</td>'
                        f'<td>{type_cell}</td>'
                        f'{abl_td}'
                        f'<td>{partner_str}</td>'
                        f'<td class="{link_cls}">{link_lbl}</td></tr>'
                    )
                    if move_html:
                        parts.append(
                            f'<tr class="move-row {row_cls}" data-key="{html.escape(key)}-moves">'
                            f'<td colspan="{colspan}">{move_html}</td></tr>'
                        )
                parts.append("</tbody></table>")
                if q_str:
                    parts.append(f'<p style="margin:0;font-size:0.85em">{q_str}</p>')
            else:
                parts.append('<p class="empty">No party mons.</p>')

            # PC boxes
            boxes = p.get("pc_boxes", [])
            # Build set of memorial mon keys from the link table (covers overflow boxes too)
            from server.state import LinkStatus as _LS
            _memorial_keys: set[str] = {
                mi.key
                for e in s.links
                if e.status in (_LS.MEMORIAL, _LS.DEAD)
                for mi in (e.a, e.b) if mi and mi.key
            }
            # Also exclude pending memorials (awaiting Lua confirmation)
            for _pm_keys in s.pending_memorials.values():
                _memorial_keys.update(_pm_keys)
            # Also exclude the dedicated memorial box and overflow boxes by physical index
            _mem_idx = self.adapter.memorial_box_index if self.adapter else -1
            boxes = [
                b for b in boxes
                if b.get("key", "") not in _memorial_keys
                and (_mem_idx < 0 or b.get("box") not in self._memorial_box_indices())
            ]
            if boxes:
                parts.append('<h3 style="margin-top:0.8em;font-size:0.95em">PC Boxes</h3>')
                parts.append(f'<table><thead><tr><th>Box</th><th>Slot</th><th>Lv</th><th>Pokémon</th><th>Type</th>{"<th>Ability</th>" if has_abilities else ""}<th>Partner</th><th>Link</th></tr></thead><tbody>')
                for bentry in boxes:
                    b_sid     = bentry.get("species_id", 0)
                    b_gender  = self.adapter.gender_from_key(bentry.get("key", ""), b_sid)
                    b_item_id = bentry.get("held_item_id", 0)
                    b_item_s  = self.adapter.item_name(b_item_id)
                    b_item_h  = (f'<span class="held-item">{html.escape(b_item_s)}</span>'
                                 if b_item_s else "")
                    # Shiny: unlinked shiny or linked MonInfo.is_shiny
                    _bx_key_tmp = bentry.get("key", "")
                    _bx_entry_tmp = s._key_index.get(_bx_key_tmp)
                    _bx_own_mi = (_bx_entry_tmp.a if pid == "a" else _bx_entry_tmp.b) if _bx_entry_tmp else None
                    _bx_is_shiny = _bx_key_tmp in s.bonus_keys.get(pid, set()) or bool(_bx_own_mi and _bx_own_mi.is_shiny)
                    b_sprite_html = self._get_sprite_html(b_sid)
                    b_label   = (
                        f'<div style="display:inline-flex;align-items:center;gap:4px">'
                        + (f'<div style="flex-shrink:0">{b_sprite_html}</div>' if b_sprite_html else '')
                        + f'<div>{mon_label(bentry.get("key", ""), bentry.get("nickname", ""), b_sid, b_gender, shiny=_bx_is_shiny)}{b_item_h}</div>'
                        + f'</div>'
                    )
                    b_types   = _type_badges_html(b_sid, adapter=self.adapter)
                    b_aid     = bentry.get("ability_id", 0)
                    b_abl     = self.adapter.ability_name(b_aid, b_sid) if b_aid else ""
                    b_adesc   = self.adapter.ability_description(b_aid) if b_aid else ""
                    b_abl_h   = (f'<span class="ability" title="{html.escape(b_adesc)}">{html.escape(b_abl)}</span>'
                                 if b_abl else '<span class="dim">—</span>')

                    # Level: check mon_stats cache, then link entry
                    bx_key = bentry.get("key", "")
                    bx_lv = ""
                    cached_stats = s.mon_stats.get(bx_key)
                    if cached_stats and cached_stats.get("level"):
                        bx_lv = str(cached_stats["level"])
                    else:
                        bx_entry_lv = s._key_index.get(bx_key)
                        if bx_entry_lv:
                            mi = bx_entry_lv.a if bx_entry_lv.a and bx_entry_lv.a.key == bx_key else bx_entry_lv.b
                            if mi and mi.level:
                                bx_lv = str(mi.level)
                    # Fallback: check party_details from any player (mon may
                    # be in the other client's party during solo-test setups).
                    if not bx_lv:
                        for _pid2 in ("a", "b"):
                            pdet = self.party_details.get(_pid2, {}).get(bx_key)
                            if pdet and pdet.get("level"):
                                bx_lv = str(pdet["level"])
                                break
                    # Fallback: check _mon_cache (populated from party sightings)
                    if not bx_lv:
                        mc = self._mon_cache.get(bx_key)
                        if mc and mc.get("level"):
                            bx_lv = str(mc["level"])

                    bx_entry = s._key_index.get(bx_key) if bx_key else None
                    if bx_entry:
                        bx_p_mon = bx_entry.b if pid == "a" else bx_entry.a
                        if bx_p_mon:
                            bx_p_pid = "b" if pid == "a" else "a"
                            bx_p_gender = self.adapter.gender_from_key(bx_p_mon.key, bx_p_mon.species)
                            # Prefer live nickname from partner's party/box data
                            bx_p_nick = bx_p_mon.nickname
                            bx_p_det = self.party_details.get(bx_p_pid, {}).get(bx_p_mon.key)
                            if bx_p_det and bx_p_det.get("nickname"):
                                bx_p_nick = bx_p_det["nickname"]
                            else:
                                for bx_e2 in self.pc_boxes.get(bx_p_pid, []):
                                    if bx_e2.get("key") == bx_p_mon.key and bx_e2.get("nickname"):
                                        bx_p_nick = bx_e2["nickname"]
                                        break
                            bx_partner_str = mon_label(bx_p_mon.key, bx_p_nick, bx_p_mon.species, bx_p_gender,
                                                        shiny=bx_p_mon.is_shiny)
                        else:
                            bx_partner_str = '<span class="dim">—</span>'
                        bx_link_cls = bx_entry.status.value
                        bx_link_lbl = bx_entry.status.value
                    else:
                        bx_pend_area = pending_key_area.get(bx_key)
                        if bx_pend_area:
                            bx_partner_id = "b" if pid == "a" else "a"
                            bx_partner_name = html.escape(
                                d["players"][bx_partner_id].get("trainer_name") or bx_partner_id.upper()
                            )
                            bx_area_lbl = html.escape(self.adapter.area_display_name(bx_pend_area))
                            bx_partner_str = (
                                f'<span class="pending_b" style="font-size:0.85em">'
                                f'waiting for <b>{bx_partner_name}</b> @ {bx_area_lbl}'
                                f'</span>'
                            )
                            bx_link_cls = "pending_b"
                            bx_link_lbl = "pending"
                        elif bx_key in d.get("bonus_keys", {}).get(pid, []):
                            bx_partner_str = '<span style="color:#ffd700">★ Shiny Clause</span>'
                            bx_link_cls    = "alive"
                            bx_link_lbl    = "★ bonus"
                        else:
                            bx_partner_str = '<span class="dim">—</span>'
                            bx_link_cls    = "dim"
                            bx_link_lbl    = "—"

                    bx_abl_td = f'<td>{b_abl_h}</td>' if has_abilities else ''
                    bx_colspan = 8 if has_abilities else 7
                    bx_move_details = bentry.get("move_details", [])
                    bx_move_html = _move_table_html(bx_move_details, is_box=True, mon_key=bx_key)
                    parts.append(
                        f'<tr data-key="{html.escape(bx_key)}"><td>{bentry.get("box",0)+1}</td>'
                        f'<td>{bentry.get("slot",0)+1}</td>'
                        f'<td>{bx_lv}</td>'
                        f'<td>{b_label}</td>'
                        f'<td>{b_types}</td>'
                        f'{bx_abl_td}'
                        f'<td>{bx_partner_str}</td>'
                        f'<td class="{bx_link_cls}">{bx_link_lbl}</td></tr>'
                    )
                    if bx_move_html:
                        parts.append(
                            f'<tr class="move-row" data-key="{html.escape(bx_key)}-moves">'
                            f'<td colspan="{bx_colspan}">{bx_move_html}</td></tr>'
                        )
                parts.append("</tbody></table>")

            parts.append("</div>")  # player-card
        parts.append("</div>")  # players-grid

        # ── Encounters (consolidated: links + pending + area states) ────────
        name_a = html.escape(d["players"]["a"].get("trainer_name") or "A")
        name_b = html.escape(d["players"]["b"].get("trainer_name") or "B")

        killfeed = d.get("killfeed", [])
        kf_by_area: dict[str, dict] = {kf["area_id"]: kf for kf in killfeed}

        def _kf_inline_html(kf: dict) -> str:
            """Compact cause + time line for embedding in the Status cell."""
            cause    = kf.get("cause", "")
            killer   = kf.get("killer") or {}
            initiator = kf.get("initiating_player", "")
            killed_at = kf.get("killed_at", "")
            try:
                from datetime import datetime as _dt
                time_str = _dt.fromisoformat(killed_at).strftime("%H:%M")
            except Exception:
                time_str = killed_at[11:16] if len(killed_at) >= 16 else ""
            if cause == "battle":
                k_species = killer.get("species", 0)
                k_level   = killer.get("level", 0)
                k_trainer = killer.get("is_trainer", False)
                k_tname   = killer.get("trainer_name", "")
                k_tclass  = killer.get("trainer_class", "")
                if k_species:
                    sp_name = html.escape(self.adapter.species_name(k_species))
                    if k_trainer and k_tname:
                        owner = f"{html.escape(k_tclass)} {html.escape(k_tname)}" if k_tclass else html.escape(k_tname)
                        prefix = f"{owner}'s"
                    elif k_trainer:
                        prefix = "Trainer's"
                    else:
                        prefix = "Wild"
                    cause_html = f'<span class="killfeed-cause kf-battle">⚔ {prefix} {sp_name} Lv{k_level}</span>'
                else:
                    cause_html = '<span class="killfeed-cause kf-battle">⚔ Fainted in battle</span>'
            elif cause == "dead_zone":
                iname = html.escape(
                    d["players"][initiator].get("trainer_name") or initiator.upper()
                ) if initiator else "?"
                cause_html = f'<span class="killfeed-cause kf-dead_zone">🚫 {iname} missed</span>'
            elif cause == "whiteout":
                iname = html.escape(
                    d["players"][initiator].get("trainer_name") or initiator.upper()
                ) if initiator else "?"
                cause_html = f'<span class="killfeed-cause kf-whiteout">💀 {iname} whited out</span>'
            else:
                cause_html = ""
            time_html = (f' <span class="dim">· {html.escape(time_str)}</span>' if time_str else "")
            return f'<br><span class="kf-inline">{cause_html}{time_html}</span>'

        # Build a unified row set keyed by area_id.
        # Each row: {area_id, a_html, a_lv, b_html, b_lv, state_label, state_cls, sort_key}
        encounter_rows: list[dict] = []

        # 1) Rows from links (linked / dead / memorial)
        for lnk in d["links"]:
            a_key = lnk.get("a_key")
            b_key = lnk.get("b_key")
            a_sid = lnk.get("a_species", 0)
            b_sid = lnk.get("b_species", 0)
            a_spr = self._get_sprite_html(a_sid)
            b_spr = self._get_sprite_html(b_sid)
            if a_key:
                a_gender = self.adapter.gender_from_key(a_key, a_sid)
                a_lbl = a_spr + mon_label(a_key, lnk.get("a_nickname", ""), a_sid, a_gender,
                                          shiny=lnk.get("a_shiny", False))
            elif lnk.get("a_enc_species"):
                sp_name = self.adapter.species_name(lnk["a_enc_species"])
                a_lbl = f'<span class="dim">{sp_name} <em>(fled/KO)</em></span>'
            else:
                a_lbl = '<span class="dim">— no catch</span>'
            if b_key:
                b_gender = self.adapter.gender_from_key(b_key, b_sid)
                b_lbl = b_spr + mon_label(b_key, lnk.get("b_nickname", ""), b_sid, b_gender,
                                          shiny=lnk.get("b_shiny", False))
            elif lnk.get("b_enc_species"):
                sp_name = self.adapter.species_name(lnk["b_enc_species"])
                b_lbl = f'<span class="dim">{sp_name} <em>(fled/KO)</em></span>'
            else:
                b_lbl = '<span class="dim">— no catch</span>'
            alv = lnk.get("a_level") or (lnk.get("a_enc_level") or "—") if not a_key else lnk.get("a_level") or "?"
            blv = lnk.get("b_level") or (lnk.get("b_enc_level") or "—") if not b_key else lnk.get("b_level") or "?"
            status = lnk["status"]
            kf = kf_by_area.get(lnk["area_id"])
            kf_extra = _kf_inline_html(kf) if kf else ""
            area_st = d["area_states"].get(lnk["area_id"], "")
            # A dead link in a dead_zone area should display as "Dead zone"
            is_dead_zone = (status in ("dead", "dead_zone") and area_st == "dead_zone")
            STATUS_ICONS = {
                "alive":     '<span class="alive">✓ linked</span>',
                "dead":      f'<span class="dead_zone">☠ dead zone</span>{kf_extra}' if is_dead_zone else f'<span class="dead">☠ dead</span>{kf_extra}',
                "memorial":  f'<span class="dead_zone">☠ dead zone</span> <span class="dim" style="font-size:0.82em">· boxed</span>{kf_extra}' if is_dead_zone else f'<span class="dead">☠ dead</span> <span class="dim" style="font-size:0.82em">· boxed</span>{kf_extra}',
                "dead_zone": f'<span class="dead_zone">☠ dead zone</span>{kf_extra}',
            }
            status_html = STATUS_ICONS.get(status, status)
            row_cls = "dead_zone" if is_dead_zone else status
            encounter_rows.append({
                "area": lnk["area_id"],
                "a_html": a_lbl, "a_lv": alv,
                "b_html": b_lbl, "b_lv": blv,
                "state": status_html, "cls": row_cls,
                "sort": 0 if status == "alive" else 1,
            })

        # Collect areas already covered by links
        linked_areas = {r["area"] for r in encounter_rows}

        # 2) Rows from pending captures (areas not yet linked)
        for area, players in sorted(d["pending_captures"].items()):
            if area in linked_areas:
                continue
            a_info = players.get("a")
            b_info = players.get("b")
            if a_info:
                cap_sid = a_info.get("species", 0)
                cap_gender = self.adapter.gender_from_key(a_info["key"], cap_sid)
                a_lbl = (self._get_sprite_html(cap_sid)
                         + mon_label(a_info["key"], a_info.get("nickname", ""), cap_sid, cap_gender))
                a_lv = a_info.get("level") or "?"
            else:
                a_lbl = f'<span class="dim">waiting…</span>'
                a_lv = "—"
            if b_info:
                cap_sid = b_info.get("species", 0)
                cap_gender = self.adapter.gender_from_key(b_info["key"], cap_sid)
                b_lbl = (self._get_sprite_html(cap_sid)
                         + mon_label(b_info["key"], b_info.get("nickname", ""), cap_sid, cap_gender))
                b_lv = b_info.get("level") or "?"
            else:
                b_lbl = f'<span class="dim">waiting…</span>'
                b_lv = "—"
            state_val = d["area_states"].get(area, "unseen")
            # Determine per-player state for progress bar:
            # "caught" if they have a pending capture, "entered" if the area state
            # implies they've been there, "none" otherwise.
            a_st = "caught" if a_info else ("entered" if state_val in ("pending_b", "pending_both") else "none")
            b_st = "caught" if b_info else ("entered" if state_val in ("pending_a", "pending_both") else "none")
            label = _enc_status(a_st, b_st, name_a, name_b)
            encounter_rows.append({
                "area": area,
                "a_html": a_lbl, "a_lv": a_lv,
                "b_html": b_lbl, "b_lv": b_lv,
                "state": label, "cls": state_val,
                "sort": -1,  # pending at top
            })
            linked_areas.add(area)

        # 3) Rows from area_states not covered above (pending_both with no captures, etc.)
        for area, state_val in sorted(d["area_states"].items()):
            if area in linked_areas:
                continue
            if state_val in ("unseen",):
                continue  # skip unseen — nothing to show
            # No pending captures → "entered only"
            if state_val == "pending_b":
                label = _enc_status("entered", "none", name_a, name_b)
            elif state_val == "pending_a":
                label = _enc_status("none", "entered", name_a, name_b)
            elif state_val == "pending_both":
                label = _enc_status("entered", "entered", name_a, name_b)
            elif state_val == "dead_zone":
                kf = kf_by_area.get(area)
                kf_extra = _kf_inline_html(kf) if kf else ""
                label = f'<span class="dead_zone">☠ dead zone</span>{kf_extra}'
            elif state_val == "linked":
                label = '<span class="linked">✓ linked</span>'
            else:
                label = state_val
            encounter_rows.append({
                "area": area,
                "a_html": '<span class="dim">—</span>', "a_lv": "—",
                "b_html": '<span class="dim">—</span>', "b_lv": "—",
                "state": label, "cls": state_val,
                "sort": -1 if "pending" in state_val else 2,
            })

        # Sort: pending first, alive, then dead/memorial
        encounter_rows.sort(key=lambda r: (r["sort"], r["area"]))

        _STATUS_SORT_VAL = {
            "pending_a": "0", "pending_b": "0", "pending_both": "0",
            "alive": "1", "linked": "1",
            "dead": "2", "dead_zone": "3", "memorial": "4",
        }

        n_alive = sum(1 for r in encounter_rows if r["cls"] == "alive")
        n_dead  = sum(1 for r in encounter_rows if r["cls"] in ("dead", "dead_zone", "memorial"))
        n_pend  = sum(1 for r in encounter_rows if "pending" in r["cls"])
        n_pend_a = sum(1 for r in encounter_rows if r["cls"] in ("pending_a", "pending_both"))
        n_pend_b = sum(1 for r in encounter_rows if r["cls"] in ("pending_b", "pending_both"))
        parts.append(
            f'<h2>Encounters ({len(encounter_rows)} areas'
            f' &mdash; {n_alive} linked, {n_dead} dead, {n_pend} pending)</h2>'
        )
        if encounter_rows:
            parts.append(
                '<div id="enc-filters" class="enc-filters">'
                '<span class="filter-label">Filter:</span>'
                '<button class="filter-btn active" data-filter="all">All</button>'
                f'<button class="filter-btn" data-filter="linked">✓ Linked ({n_alive})</button>'
                f'<button class="filter-btn" data-filter="pending">⏳ Pending ({n_pend})</button>'
                f'<button class="filter-btn" data-filter="pending_a">⏳ {name_a} ({n_pend_a})</button>'
                f'<button class="filter-btn" data-filter="pending_b">⏳ {name_b} ({n_pend_b})</button>'
                f'<button class="filter-btn" data-filter="dead">☠ Dead ({n_dead})</button>'
                '</div>'
            )
            parts.append(
                f'<table id="enc-table"><thead><tr>'
                f'<th class="sortable" data-col="0">Area</th>'
                f'<th class="sortable" data-col="1">{name_a}</th>'
                f'<th class="sortable" data-col="2">{name_b}</th>'
                f'<th class="sortable" data-col="3">Status</th>'
                f'</tr></thead><tbody>'
            )
            for r in encounter_rows:
                area_disp = self._area_display(r["area"])
                st_sort = _STATUS_SORT_VAL.get(r["cls"], "9")
                is_bonus = r["area"].startswith("_bonus_")
                row_cls = ' class="bonus-pair-row"' if is_bonus else ''
                area_cell = area_disp
                parts.append(
                    f'<tr{row_cls} data-status="{html.escape(r["cls"])}" data-key="{html.escape(r["area"])}">'
                    f'<td data-sort="{html.escape(area_disp)}">{area_cell}</td>'
                    f'<td>{r["a_html"]}</td>'
                    f'<td>{r["b_html"]}</td>'
                    f'<td data-sort="{st_sort}">{r["state"]}</td></tr>'
                )
            parts.append("</tbody></table>")
        else:
            parts.append("<p class='empty'>No encounters yet.</p>")

        parts.append('')

        # Recent events panel
        parts.append('<h2>Recent Events</h2>')
        events = list(self._recent_events)
        if events:
            parts.append('<div style="max-height:300px;overflow-y:auto;border:1px solid #333;border-radius:3px;">')
            parts.append(
                '<table style="margin-bottom:0"><thead><tr>'
                '<th style="position:sticky;top:0;background:#222">Time</th>'
                '<th style="position:sticky;top:0;background:#222;text-align:left">Player</th>'
                '<th style="position:sticky;top:0;background:#222">Details</th>'
                '</tr></thead><tbody>'
            )
            for ev in events:
                ev_type   = html.escape(ev.get("type", "hello"))
                _pid      = ev.get("player", "")
                ev_player = html.escape(
                    self.trainer_name.get(_pid, "") or _pid.upper()
                )
                ev_text   = html.escape(ev.get("text", ""))
                # Convert ISO timestamp to 12H format (e.g. "8:26 PM")
                _raw_ts = ev.get("ts", "")
                try:
                    _dt = datetime.fromisoformat(_raw_ts)
                    ev_ts = html.escape(_dt.strftime("%I:%M:%S %p").lstrip("0"))
                except (ValueError, AttributeError):
                    ev_ts = html.escape(_raw_ts[-8:])
                parts.append(
                    f'<tr>'
                    f'<td class="dim" style="white-space:nowrap">{ev_ts}</td>'
                    f'<td style="text-align:left;white-space:nowrap"><b>{ev_player}</b></td>'
                    f'<td class="event-type-{ev_type}">{ev_text}</td>'
                    f'</tr>'
                )
            parts.append('</tbody></table></div>')
        else:
            parts.append("<p class='empty'>No events yet.</p>")

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mgr_link = ""
        if self._manager_port:
            mgr_link = (
                f' &nbsp;·&nbsp; <a id="mgr-link" href="#" style="color:#4ade80;text-decoration:none">'
                f'&#127968; Run Manager</a>'
                f'<script>document.getElementById("mgr-link").href='
                f'"//" + window.location.hostname + ":{self._manager_port}";</script>'
            )
        return _STATUS_HTML.format(timestamp=ts, body="\n".join(parts),
                                   page_title=self._page_title(),
                                   tcp_port=self._tcp_port or "N/A",
                                   manager_link=mgr_link,
                                   calc_js=_CALC_PREVIEW_JS)

    async def handle_status_html(self, request):
        return aiohttp_web.Response(
            text=self._build_status_html(),
            content_type="text/html",
        )

    async def handle_status_json(self, request):
        return aiohttp_web.json_response(self._build_status_dict())

    # ── RR Damage Calculator handlers ───────────────────────────────────────

    async def handle_calc_redirect(self, request):
        raise aiohttp_web.HTTPFound('/calc/normal.html')

    async def handle_calc_files(self, request):
        """Serve static files from calc/dist/ with basic path-traversal protection."""
        path = request.match_info.get('path', '')
        safe = os.path.normpath(path).lstrip('/\\')
        if '..' in safe:
            raise aiohttp_web.HTTPForbidden()
        abs_path = os.path.join(_CALC_DIST_DIR, safe)
        if not os.path.isfile(abs_path):
            raise aiohttp_web.HTTPNotFound()
        mime, _ = mimetypes.guess_type(abs_path)
        ct = mime or 'application/octet-stream'
        with open(abs_path, 'rb') as fh:
            return aiohttp_web.Response(body=fh.read(), content_type=ct)

    async def handle_calc_mons(self, request):
        """Return live party + linked mons for both players as Showdown pastes."""
        d = self._build_status_dict()
        s = self.state
        result = {}
        for pid in ("a", "b"):
            p = d["players"][pid]
            party, linked = [], []
            # Party mons
            for key in p.get("party_keys", []):
                detail = p["party_details"].get(key, {})
                entry = _build_mon_entry(key, detail, self.adapter)
                if entry:
                    entry["loc"] = "party"
                    entry["hp_pct"] = (
                        max(0, min(100, int(detail.get("hp", 0)
                                           / max(detail.get("maxHP", 1), 1) * 100))))
                    party.append(entry)
            # Linked alive mons not already in party
            party_key_set = set(p.get("party_keys", []))
            for lnk in s.links:
                if lnk.status.value != "alive":
                    continue
                mi = lnk.a if pid == "a" else lnk.b
                if not mi or not mi.key or mi.key in party_key_set:
                    continue
                stats = s.mon_stats.get(mi.key, {})
                detail = {
                    "species_id":   mi.species,
                    "level":        mi.level or stats.get("level", 0),
                    "nickname":     mi.nickname or "",
                    "hp":           0,
                    "maxHP":        0,
                    "held_item_id": 0,
                    "ability_id":   0,
                    "ability_name": "",
                    "moves":        stats.get("moves", []),
                }
                entry = _build_mon_entry(mi.key, detail, self.adapter)
                if entry:
                    entry["loc"] = "box"
                    linked.append(entry)
            bs = p.get("battle_state", {})
            enemy = []
            if bs.get("in_battle"):
                is_trainer = bs.get("is_trainer_battle", False)
                opp_name  = bs.get("opponent_name", "")
                opp_class = bs.get("opponent_class", "")
                trainer_label = " ".join(filter(None, [opp_class, opp_name])) if is_trainer else "Wild"
                for ei, em in enumerate(bs.get("enemy_party", [])):
                    esid  = em.get("species_id", 0)
                    if not esid:
                        continue
                    detail = {
                        "species_id":   esid,
                        "level":        em.get("level", 0),
                        "nickname":     "",
                        "hp":           em.get("hp", 0),
                        "maxHP":        em.get("maxHP", 1),
                        "held_item_id": em.get("held_item_id", 0),
                        "ability_id":   em.get("ability_id", 0),
                        "ability_name": "",
                        "moves":        em.get("moves", []),
                        "status_cond":  em.get("status_cond", 0),
                        "stat_stages":  em.get("stat_stages"),
                    }
                    entry = _build_mon_entry(f"foe-{ei}", detail, self.adapter)
                    if entry:
                        entry["loc"]    = "enemy"
                        entry["active"] = em.get("active", False)
                        entry["hp_pct"] = max(0, min(100, int(
                            em.get("hp", 0) / max(em.get("maxHP", 1), 1) * 100)))
                        entry["trainer_label"] = trainer_label
                        enemy.append(entry)
            result[pid] = {
                "trainer_name": p.get("trainer_name", pid.upper()),
                "party":  party,
                "linked": linked,
                "enemy":  enemy,
            }
        return aiohttp_web.json_response(result)

    async def handle_memorial_html(self, request):
        return aiohttp_web.Response(
            text=_MEMORIAL_HTML.replace("{page_title}", html.escape(self._page_title())),
            content_type="text/html",
        )

    # ── Stream overlay handlers ──────────────────────────────────────────────

    async def handle_stream_index(self, request):
        return aiohttp_web.Response(text=_STREAM_INDEX_HTML, content_type="text/html")

    async def handle_stream_party_a(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Player A Party",
                                     _STREAM_PARTY_JS.replace("%PLAYER%", "a")),
            content_type="text/html")

    async def handle_stream_party_b(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Player B Party",
                                     _STREAM_PARTY_JS.replace("%PLAYER%", "b")),
            content_type="text/html")

    async def handle_stream_enemy_focus_a(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Enemy Focus A",
                                      _STREAM_ENEMY_FOCUS_JS.replace("%PLAYER%", "a")),
            content_type="text/html")

    async def handle_stream_enemy_focus_b(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Enemy Focus B",
                                      _STREAM_ENEMY_FOCUS_JS.replace("%PLAYER%", "b")),
            content_type="text/html")

    async def handle_stream_enemy_trainer_a(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Enemy Trainer A",
                                      _STREAM_ENEMY_TRAINER_JS.replace("%PLAYER%", "a")),
            content_type="text/html")

    async def handle_stream_enemy_trainer_b(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Enemy Trainer B",
                                      _STREAM_ENEMY_TRAINER_JS.replace("%PLAYER%", "b")),
            content_type="text/html")

    async def handle_stream_links(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Linked Pairs", _STREAM_LINKS_JS),
            content_type="text/html")

    async def handle_stream_linked_party(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Linked Party", _STREAM_LINKED_PARTY_JS),
            content_type="text/html")

    async def handle_stream_boxed_links(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Boxed Links", _STREAM_BOXED_LINKS_JS),
            content_type="text/html")

    async def handle_stream_deaths(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Death Counter", _STREAM_DEATHS_JS),
            content_type="text/html")

    async def handle_stream_attempts(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Attempts Counter", _STREAM_ATTEMPTS_JS),
            content_type="text/html")

    async def handle_stream_areas(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Area Tracker", _STREAM_AREAS_JS),
            content_type="text/html")

    async def handle_api_attempts(self, request):
        """POST /api/attempts — set the manual attempts counter."""
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        count = body.get("count")
        if count is None or not isinstance(count, int) or count < 0:
            return aiohttp_web.json_response(
                {"ok": False, "error": "count must be a non-negative integer"}, status=400)
        self.state.attempts_count = count
        self.state._save()
        self._notify_sse()
        return aiohttp_web.json_response({"ok": True, "attempts_count": count})

    async def handle_stream_events(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Event Feed", _STREAM_EVENTS_JS),
            content_type="text/html")

    async def handle_stream_badges_a(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Gym Badges A",
                                     _STREAM_BADGES_JS.replace("%PLAYER%", "a")),
            content_type="text/html")

    async def handle_stream_badges_b(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Gym Badges B",
                                     _STREAM_BADGES_JS.replace("%PLAYER%", "b")),
            content_type="text/html")

    async def handle_stream_encounters(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Encounter Tracker", _STREAM_ENCOUNTERS_JS),
            content_type="text/html")

    async def handle_stream_stream_memorial(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Memorial Scroll", _STREAM_MEMORIAL_JS),
            content_type="text/html")

    async def handle_stream_ticker(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Event Ticker", _STREAM_TICKER_JS),
            content_type="text/html")

    async def handle_stream_focus_a(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Focus A",
                                     _STREAM_FOCUS_JS.replace("%PLAYER%", "a")),
            content_type="text/html")

    async def handle_stream_focus_b(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Focus B",
                                     _STREAM_FOCUS_JS.replace("%PLAYER%", "b")),
            content_type="text/html")

    async def handle_stream_area_encounter(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Area Encounter", _STREAM_AREA_ENCOUNTER_JS),
            content_type="text/html")

    async def handle_stream_enc_table_a(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Encounter Table A", _STREAM_ENC_TABLE_JS.replace("%PLAYER%", "a")),
            content_type="text/html")

    async def handle_stream_enc_table_b(self, request):
        return aiohttp_web.Response(
            text=_stream_overlay_page("Encounter Table B", _STREAM_ENC_TABLE_JS.replace("%PLAYER%", "b")),
            content_type="text/html")

    # ── Launcher script download ─────────────────────────────────────────────

    _LAUNCHER_TEMPLATE = (
        '-- Auto-generated by SLink - {run_name}\n'
        '-- Player {player_upper}: load this script in BizHawk Lua Console\n'
        '-- This file can be loaded from any location (Desktop, Downloads, etc.)\n'
        '--\n'
        '-- Override: set SLINK_ROOT to skip auto-detection entirely:\n'
        'local SLINK_ROOT = nil  -- e.g. "C:/SLink/"\n'
        '\n'
        'SLINK_HOST   = "{host}"\n'
        'SLINK_PORT   = {tcp_port}\n'
        'SLINK_PLAYER = "{player}"\n'
        '\n'
        '-- Config file lives next to this launcher and caches the project root path.\n'
        'local _launcher_dir = ((debug.getinfo(1, "S") or {{}}).source or ""):match("@(.+[\\\\/])") or ""\n'
        'local _cfg_path = _launcher_dir .. "slink_path.cfg"\n'
        '\n'
        'local function _valid_root(path)\n'
        '    if not path or path == "" or path == "nil" then return false end\n'
        '    local f = io.open(path .. "lua/slink.lua", "r")\n'
        '    if f then f:close(); return true end\n'
        '    return false\n'
        'end\n'
        '\n'
        '-- 1. Load cached path from config file\n'
        'if not SLINK_ROOT then\n'
        '    local f = io.open(_cfg_path, "r")\n'
        '    if f then\n'
        '        local cached = f:read("*l"); f:close()\n'
        '        if _valid_root(cached) then SLINK_ROOT = cached end\n'
        '    end\n'
        'end\n'
        '\n'
        '-- 2. Auto-detect: search from this script\'s directory upward for lua/slink.lua\n'
        'if not SLINK_ROOT then\n'
        '    local dir = _launcher_dir\n'
        '    for _, rel in ipairs({{"", "../", "../../", "../../../"}}) do\n'
        '        if _valid_root(dir .. rel) then SLINK_ROOT = dir .. rel; break end\n'
        '    end\n'
        'end\n'
        '\n'
        '-- 3. Fallback: show folder picker\n'
        'if not SLINK_ROOT then\n'
        '    luanet.load_assembly("System.Windows.Forms")\n'
        '    local FBD = luanet.import_type("System.Windows.Forms.FolderBrowserDialog")\n'
        '    local DR = luanet.import_type("System.Windows.Forms.DialogResult")\n'
        '    local dlg = FBD()\n'
        '    dlg.Description = "Select the SLink project folder (the folder that contains lua/ and server/)"\n'
        '    dlg.ShowNewFolderButton = false\n'
        '    local result = dlg:ShowDialog()\n'
        '    if result == DR.OK then\n'
        '        local path = tostring(dlg.SelectedPath)\n'
        '        if path and path ~= "" then\n'
        '            SLINK_ROOT = path:gsub("\\\\", "/") .. "/"\n'
        '        end\n'
        '    end\n'
        'end\n'
        '\n'
        'if not SLINK_ROOT then\n'
        '    error("[SLink] No project folder selected — cannot start.", 2)\n'
        'end\n'
        '\n'
        '-- Save path for next run\n'
        'local f = io.open(_cfg_path, "w")\n'
        'if f then f:write(SLINK_ROOT); f:close() end\n'
        '\n'
        'dofile(SLINK_ROOT .. "lua/slink.lua")\n'
    )

    async def handle_launcher(self, request):
        """GET /launcher/{player} — serve a per-player launcher .lua file."""
        player = request.match_info["player"]
        if player not in ("a", "b"):
            return aiohttp_web.Response(text="player must be 'a' or 'b'", status=400)
        host_header = request.host or "127.0.0.1"
        connect_host = host_header.split(":")[0] or "127.0.0.1"
        run_name = self._run_name or self._run_id or "SLink"
        content = self._LAUNCHER_TEMPLATE.format(
            run_name=run_name,
            player_upper=player.upper(),
            host=connect_host,
            tcp_port=self._tcp_port,
            player=player,
        )
        safe_name = re.sub(r'[^\w-]', '_', run_name).strip('_') or "SLink"
        filename = f"slink_{safe_name}_{player}.lua"
        return aiohttp_web.Response(
            text=content,
            content_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ── Twitch bot management page ───────────────────────────────────────────

    _TWITCH_PAGE_HTML = r"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Twitch Bot — Soul Link</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap" rel="stylesheet">
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:system-ui,'Segoe UI',sans-serif;background:#0a0c14;color:#e0e0e0;padding:1.5em;min-height:100vh}
    h1{font-family:'Press Start 2P',monospace;color:#f8d030;font-size:1em;margin-bottom:.3em}
    .sub{color:#888;font-size:.85em;margin-bottom:1.5em}
    .sub a{color:#6af;text-decoration:none}
    .panel{background:#12141e;border:1px solid #2a2c3a;border-radius:8px;padding:1.2em;margin-bottom:1.2em}
    .panel h2{font-family:'Press Start 2P',monospace;font-size:.7em;color:#f8d030;margin-bottom:.8em;letter-spacing:.05em}
    .status-badge{display:inline-block;padding:3px 12px;border-radius:3px;font-size:.82em;font-weight:700;letter-spacing:.05em}
    .sb-on{background:#1a4a1a;color:#3de85a;border:1px solid #3de85a}
    .sb-off{background:#3a1a1a;color:#f03838;border:1px solid #f03838}
    .sb-dis{background:#2a2a2a;color:#888;border:1px solid #888}
    label{display:block;color:#aaa;font-size:.8em;margin-bottom:.2em;margin-top:.7em}
    input[type=text],input[type=number]{width:100%;background:#1a1c28;color:#e0e0e0;border:1px solid #363850;border-radius:4px;padding:6px 10px;font-size:.85em}
    input[type=text]:focus,input[type=number]:focus{outline:none;border-color:#f8d030}
    .btn{background:#1a2a3a;color:#6af;border:1px solid #6af;border-radius:4px;padding:6px 14px;cursor:pointer;font-size:.82em;white-space:nowrap}
    .btn:hover{background:#2a3a4a}
    .btn-red{color:#f03838;border-color:#f03838}.btn-red:hover{background:#3a1a1a}
    .btn-grn{color:#3de85a;border-color:#3de85a}.btn-grn:hover{background:#1a3a1a}
    .btn-row{display:flex;gap:.6em;flex-wrap:wrap;margin-top:.8em}
    .hint{color:#666;font-size:.75em;margin-top:.3em}
    table{width:100%;border-collapse:collapse;font-size:.83em}
    th{text-align:left;color:#888;padding:4px 8px;border-bottom:1px solid #2a2c3a;font-weight:400}
    td{padding:4px 8px;border-bottom:1px solid #1a1c24;vertical-align:top}
    td.cmd{font-family:monospace;color:#f8d030;white-space:nowrap}
    td.arg{font-family:monospace;color:#aaa;white-space:nowrap}
    .log-entry{font-size:.78em;padding:4px 0;border-bottom:1px solid #1a1c24;display:flex;gap:.7em}
    .log-ts{color:#555;flex-shrink:0;white-space:nowrap}
    .log-txt{color:#ccc;word-break:break-all}
    #log-list .log-entry:last-child{border-bottom:none}
    .empty{color:#555;font-size:.82em;font-style:italic}
    .preview-box{background:#1a1c28;border:1px solid #363850;border-radius:4px;padding:8px 12px;font-size:.82em;min-height:2em;color:#6af;font-family:monospace;white-space:pre-wrap;word-break:break-all}
    select{background:#1a1c28;color:#e0e0e0;border:1px solid #363850;border-radius:4px;padding:6px 10px;font-size:.85em;width:100%}
    .row2{display:grid;grid-template-columns:1fr 1fr;gap:1em}
    @media(max-width:600px){.row2{grid-template-columns:1fr}}
    .sec-note{color:#f8d030;background:rgba(248,208,48,.07);border:1px solid rgba(248,208,48,.2);border-radius:4px;padding:8px 12px;font-size:.78em;margin-bottom:.8em}
  </style>
</head>
<body>
  <h1>&#x1F916; Twitch Bot</h1>
  <p class="sub"><a href="/">&larr; Status Page</a> &nbsp;&middot;&nbsp; <a href="/debug">Debug</a></p>

  <div class="panel">
    <h2>STATUS</h2>
    <span id="status-badge" class="status-badge sb-dis">Loading&hellip;</span>
    <span id="status-channel" style="margin-left:.8em;color:#888;font-size:.85em"></span>
    <span id="token-badge" style="margin-left:1em;font-size:.82em;padding:3px 10px;border-radius:3px;display:inline-block"></span>
    <span id="clientid-badge" style="margin-left:.5em;font-size:.82em;padding:3px 10px;border-radius:3px;display:inline-block"></span>
    <div id="status-error" style="display:none;margin-top:.7em;background:rgba(240,56,56,.1);border:1px solid #f03838;border-radius:4px;padding:7px 12px;color:#f03838;font-size:.82em;font-family:monospace;word-break:break-all"></div>
  </div>

  <div class="panel">
    <h2>CONFIGURATION</h2>
    <div class="sec-note">
      &#x26A0; <strong>twitchio 3.x setup — Twitch IRC is discontinued. You must use EventSub.</strong><br>
      <strong>Step 1 — Register your app</strong> at <a href="https://dev.twitch.tv/console" target="_blank" style="color:#f8d030">dev.twitch.tv/console</a> → Register Your Application.<br>
      &nbsp;&nbsp;• Name: anything &nbsp;• Category: Chat Bot &nbsp;• OAuth Redirect URL: <code>https://twitchtokengenerator.com/</code> &nbsp;• Client Type: Confidential<br>
      &nbsp;&nbsp;Copy your <strong>Client ID</strong> and click <em>New Secret</em> to generate a <strong>Client Secret</strong>.<br>
      <strong>Step 2 — Get tokens</strong> at <a href="https://twitchtokengenerator.com" target="_blank" style="color:#f8d030">twitchtokengenerator.com</a> → Custom Scope Token → paste your Client ID → enable scopes: <code>user:read:chat</code> <code>user:write:chat</code> <code>user:bot</code> <code>channel:bot</code> → Generate. Copy <strong>Access Token</strong> and <strong>Refresh Token</strong>.<br>
      <strong>Step 3 — Set env vars</strong> before starting the server (cmd.exe — no spaces, no quotes):<br>
      &nbsp;&nbsp;<code>set TWITCH_ACCESS_TOKEN=...</code> &nbsp; ← from twitchtokengenerator<br>
      &nbsp;&nbsp;<code>set TWITCH_REFRESH_TOKEN=...</code> &nbsp; ← from twitchtokengenerator<br>
      &nbsp;&nbsp;<code>set TWITCH_CLIENT_SECRET=...</code> &nbsp; ← from dev.twitch.tv/console → your app → New Secret<br>
      <strong>Step 4 — Fill in Channel and Client ID below</strong>, click Save Config, then Reconnect.
    </div>
    <div class="row2">
      <div>
        <label>Channel (without #)</label>
        <input type="text" id="cfg-channel" placeholder="your_channel">
        <label>Bot Nick</label>
        <input type="text" id="cfg-nick" placeholder="slink_bot">
      </div>
      <div>
        <label>Client ID (from dev.twitch.tv/console)</label>
        <input type="text" id="cfg-client-id" placeholder="abcdef1234567890abcdef1234567890" style="width:260px">
        <label>Command Prefix</label>
        <input type="text" id="cfg-prefix" value="!" maxlength="3" style="width:80px">
        <label>Command Cooldown (seconds)</label>
        <input type="number" id="cfg-cooldown" min="1" max="60" value="5" style="width:80px">
      </div>
    </div>
    <div class="btn-row">
      <button class="btn" onclick="saveConfig()">Save Config</button>
      <button class="btn" onclick="reloadBot()">Reconnect</button>
      <button class="btn btn-grn" onclick="enableBot()">Enable</button>
      <button class="btn btn-red" onclick="disableBot()">Disable</button>
    </div>
  </div>

  <div class="panel">
    <h2>COMMAND PREVIEW</h2>
    <p style="color:#888;font-size:.82em;margin-bottom:.7em">Test what the bot would reply — no message is sent to chat.</p>
    <div style="display:flex;gap:.6em;flex-wrap:wrap;align-items:flex-end">
      <div style="flex:1;min-width:160px">
        <label>Command</label>
        <select id="prev-cmd">
          <option value="soullink">!soullink</option>
          <option value="clauses">!clauses</option>
          <option value="rip">!rip</option>
          <option value="runstats">!runstats</option>
          <option value="alltime">!alltime</option>
          <option value="lastrun">!lastrun</option>
          <option value="attempts">!attempts</option>
          <option value="partner">!partner &lt;name&gt;</option>
          <option value="area">!area &lt;name&gt;</option>
        </select>
      </div>
      <div style="flex:1;min-width:120px">
        <label>Argument (optional)</label>
        <input type="text" id="prev-arg" placeholder="e.g. PIDGEY">
      </div>
      <button class="btn" onclick="previewCmd()" style="margin-bottom:2px">Preview</button>
    </div>
    <div id="preview-out" class="preview-box" style="margin-top:.7em">&hellip;</div>
  </div>

  <div class="panel">
    <h2>COMMAND REFERENCE</h2>
    <table>
      <thead><tr><th>Command</th><th>Arg</th><th>Description</th></tr></thead>
      <tbody>
        <tr><td class="cmd">!soullink</td><td class="arg"></td><td>Plain-English Soul Link rules for new viewers</td></tr>
        <tr><td class="cmd">!clauses</td><td class="arg"></td><td>Active clause rules (Species / Gender / Type)</td></tr>
        <tr><td class="cmd">!rip</td><td class="arg"></td><td>Most recent death with killer detail</td></tr>
        <tr><td class="cmd">!runstats</td><td class="arg"></td><td>Attempt #, alive/dead/shinies, oldest linked pair</td></tr>
        <tr><td class="cmd">!alltime</td><td class="arg"></td><td>Cross-run aggregate: attempts, deaths, shinies, best run</td></tr>
        <tr><td class="cmd">!lastrun</td><td class="arg"></td><td>How the previous run ended</td></tr>
        <tr><td class="cmd">!attempts</td><td class="arg"></td><td>Current attempt number</td></tr>
        <tr><td class="cmd">!partner</td><td class="arg">&lt;name&gt;</td><td>Look up a mon's Soul Link partner by nickname</td></tr>
        <tr><td class="cmd">!area</td><td class="arg">&lt;name&gt;</td><td>Look up the link status of an area</td></tr>
      </tbody>
    </table>
  </div>

  <div class="panel">
    <h2>RECENT ACTIVITY</h2>
    <div id="log-list"><span class="empty">No activity yet.</span></div>
  </div>

  <script>
    var _cfgLoaded = false;
    function showToast(msg, ok) {
      var t = document.createElement('div');
      t.textContent = msg;
      t.style.cssText = 'position:fixed;bottom:1.5em;right:1.5em;background:'+(ok?'#1a3a1a':'#3a1a1a')+';color:'+(ok?'#3de85a':'#f03838')+';border-radius:5px;padding:8px 16px;font-size:.85em;z-index:999';
      document.body.appendChild(t);
      setTimeout(function(){if(t.parentNode)t.parentNode.removeChild(t);},2500);
    }
    function post(url, body) {
      return fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})}).then(function(r){return r.json();});
    }
    var _cfgInputIds = ['cfg-channel','cfg-nick','cfg-prefix','cfg-cooldown','cfg-client-id'];
    function _anyConfigFocused() {
      var a = document.activeElement;
      return a && _cfgInputIds.indexOf(a.id) !== -1;
    }
    function loadStatus(forceConfig) {
      fetch('/api/bot/status').then(function(r){return r.json();}).then(function(j){
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
        if (tBadge) {
          if (j.access_token_set) {
            tBadge.style.cssText = 'background:#1a2a1a;color:#3de85a;border:1px solid #3de85a;margin-left:1em;font-size:.82em;padding:3px 10px;border-radius:3px;display:inline-block';
            tBadge.textContent = '✓ Access Token set';
          } else {
            tBadge.style.cssText = 'background:#3a1a1a;color:#f03838;border:1px solid #f03838;margin-left:1em;font-size:.82em;padding:3px 10px;border-radius:3px;display:inline-block';
            tBadge.textContent = '✗ TWITCH_ACCESS_TOKEN not set';
          }
        }
        if (cidBadge) {
          if (j.client_id_set) {
            cidBadge.style.cssText = 'background:#1a2a1a;color:#3de85a;border:1px solid #3de85a;margin-left:.5em;font-size:.82em;padding:3px 10px;border-radius:3px;display:inline-block';
            cidBadge.textContent = '✓ Client ID set';
          } else {
            cidBadge.style.cssText = 'background:#3a1a1a;color:#f03838;border:1px solid #f03838;margin-left:.5em;font-size:.82em;padding:3px 10px;border-radius:3px;display:inline-block';
            cidBadge.textContent = '✗ Client ID not set';
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
          ll.innerHTML = '';
          j.activity.forEach(function(e){
            var d = document.createElement('div'); d.className='log-entry';
            d.innerHTML='<span class="log-ts">'+e.ts.substring(11,19)+'</span><span class="log-txt">'+e.text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')+'</span>';
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
  </script>
</body>
</html>"""

    async def handle_twitch_page(self, request):
        return aiohttp_web.Response(text=self._TWITCH_PAGE_HTML, content_type="text/html")

    # ── OBS integration page & API ────────────────────────────────────────────

    _OBS_PAGE_HTML = r"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>OBS Triggers — Soul Link</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap" rel="stylesheet">
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:system-ui,'Segoe UI',sans-serif;background:#0a0c14;color:#e0e0e0;padding:1.5em;min-height:100vh}
    h1{font-family:'Press Start 2P',monospace;color:#b8f0ff;font-size:1em;margin-bottom:.3em}
    .sub{color:#888;font-size:.85em;margin-bottom:1.5em}
    .sub a{color:#6af;text-decoration:none}
    .panel{background:#12141e;border:1px solid #2a2c3a;border-radius:8px;padding:1.2em;margin-bottom:1.2em}
    .panel h2{font-family:'Press Start 2P',monospace;font-size:.7em;color:#b8f0ff;margin-bottom:.8em;letter-spacing:.05em}
    .sb{display:inline-block;padding:3px 10px;border-radius:3px;font-size:.8em;font-weight:700}
    .sb-ok{background:#1a4a1a;color:#3de85a;border:1px solid #3de85a}
    .sb-off{background:#3a1a1a;color:#f03838;border:1px solid #f03838}
    .sb-mid{background:#3a2a1a;color:#f8a030;border:1px solid #f8a030}
    label{display:block;color:#aaa;font-size:.8em;margin-bottom:.2em;margin-top:.6em}
    input[type=text],input[type=number],input[type=password],select{width:100%;background:#1a1c28;color:#e0e0e0;border:1px solid #363850;border-radius:4px;padding:6px 10px;font-size:.85em}
    input:focus,select:focus{outline:none;border-color:#b8f0ff}
    .btn{background:#1a2a3a;color:#6af;border:1px solid #6af;border-radius:4px;padding:6px 14px;cursor:pointer;font-size:.82em}
    .btn:hover{background:#2a3a4a}
    .btn-g{color:#3de85a;border-color:#3de85a}.btn-g:hover{background:#1a3a1a}
    .btn-r{color:#f03838;border-color:#f03838}.btn-r:hover{background:#3a1a1a}
    .btn-s{color:#b8f0ff;border-color:#b8f0ff}.btn-s:hover{background:#1a3050}
    .grid2{display:grid;grid-template-columns:1fr 1fr;gap:1.2em}
    table{width:100%;border-collapse:collapse;font-size:.82em}
    th{color:#888;font-weight:600;padding:5px 8px;text-align:left;border-bottom:1px solid #2a2c3a}
    td{padding:5px 8px;border-bottom:1px solid #1e2030;vertical-align:middle}
    tr:hover td{background:#1a1c28}
    .frow{display:flex;gap:.5em;align-items:flex-end;flex-wrap:wrap}
    .frow>*{flex:1;min-width:110px}
    .frow>.btn{flex:0;margin-top:1.1em}
    #msg{margin:.6em 0;font-size:.82em;color:#3de85a;min-height:1.2em}
    #msg.err{color:#f03838}
    .cbtns{display:flex;gap:.4em;margin-top:.7em;flex-wrap:wrap}
    code{color:#b8f0ff;background:#1a1c28;padding:1px 5px;border-radius:3px;font-size:.9em}
  </style>
</head>
<body>
  <h1>&#128225; OBS Scene Triggers</h1>
  <p class="sub"><a href="/">&#8592; Back to status</a></p>
  <div id="msg"></div>

  <div class="panel">
    <h2>CONNECTIONS</h2>
    <div class="grid2">
      <div>
        <div style="display:flex;align-items:center;gap:.5em;margin-bottom:.4em">
          <strong style="font-size:.9em">Player A</strong>
          <span id="status-a" class="sb sb-off">disconnected</span>
        </div>
        <label>Host<input id="host-a" type="text" placeholder="192.168.1.x"></label>
        <label>Port<input id="port-a" type="number" value="4455" min="1" max="65535"></label>
        <label>Password <small style="color:#666">(blank = keep current)</small>
          <input id="pw-a" type="password" placeholder=""></label>
        <div class="cbtns">
          <button class="btn btn-g" onclick="connect('a')">Connect</button>
          <button class="btn btn-r" onclick="disconnect('a')">Disconnect</button>
          <button class="btn" onclick="testScene('a')">Test Scene</button>
        </div>
      </div>
      <div>
        <div style="display:flex;align-items:center;gap:.5em;margin-bottom:.4em">
          <strong style="font-size:.9em">Player B</strong>
          <span id="status-b" class="sb sb-off">disconnected</span>
        </div>
        <label>Host<input id="host-b" type="text" placeholder="192.168.1.x"></label>
        <label>Port<input id="port-b" type="number" value="4455" min="1" max="65535"></label>
        <label>Password <small style="color:#666">(blank = keep current)</small>
          <input id="pw-b" type="password" placeholder=""></label>
        <div class="cbtns">
          <button class="btn btn-g" onclick="connect('b')">Connect</button>
          <button class="btn btn-r" onclick="disconnect('b')">Disconnect</button>
          <button class="btn" onclick="testScene('b')">Test Scene</button>
        </div>
      </div>
    </div>
    <div style="margin-top:1em;display:flex;align-items:center;gap:1em;flex-wrap:wrap">
      <label style="margin:0;display:flex;align-items:center;gap:.4em;color:#e0e0e0;cursor:pointer">
        <input type="checkbox" id="enabled"> Enable OBS integration
      </label>
      <button class="btn btn-s" onclick="saveConfig()">&#128190; Save Config</button>
    </div>
  </div>

  <div class="panel">
    <h2>TRIGGER RULES</h2>
    <p style="margin:0 0 .6em;color:#888;font-size:.85em">Rules are evaluated <strong>top-to-bottom</strong> — when multiple events fire at once, the highest row wins per OBS player. Drag <span style="font-size:1em">⠿</span> to reorder.</p>
    <table id="triggers-table">
      <thead><tr><th style="width:1.6em"></th><th>#</th><th>Event</th><th>Player Filter</th><th>Target OBS</th><th>Scene</th><th>Area Filter</th><th></th></tr></thead>
      <tbody id="triggers-body"></tbody>
    </table>
  </div>

  <div class="panel">
    <h2>ADD TRIGGER</h2>
    <div class="frow">
      <div>
        <label>Event</label>
        <select id="new-evt">
          <option value="battle_start">battle_start</option>
          <option value="wild_battle_start">wild_battle_start</option>
          <option value="trainer_battle_start">trainer_battle_start</option>
          <option value="battle_end">battle_end</option>
          <option value="faint">faint (own mon)</option>
          <option value="link_death">link_death (partner)</option>
          <option value="whiteout">whiteout</option>
          <option value="capture">capture</option>
          <option value="shiny">shiny</option>
          <option value="linked">linked (area linked)</option>
          <option value="dead_zone">dead_zone</option>
          <option value="area_enter">area_enter</option>
          <option value="area_enter_new">area_enter_new (open slot)</option>
          <option value="battle_start_new">battle_start_new (open slot)</option>
          <option value="party_to_box">party_to_box</option>
          <option value="box_to_party">box_to_party</option>
          <option value="run_over">run_over</option>
          <option value="memorialize_done">memorialize_done</option>
        </select>
      </div>
      <div>
        <label>Player Filter</label>
        <select id="new-pf">
          <option value="any">any</option>
          <option value="a">Player A only</option>
          <option value="b">Player B only</option>
        </select>
      </div>
      <div>
        <label>Target OBS</label>
        <select id="new-tgt">
          <option value="own">own (triggering player)</option>
          <option value="a">Player A</option>
          <option value="b">Player B</option>
          <option value="both">both</option>
        </select>
      </div>
      <div>
        <label>Scene Name</label>
        <input id="new-scene" type="text" list="scene-list-both" placeholder="e.g. Battle Scene">
        <datalist id="scene-list-a"></datalist>
        <datalist id="scene-list-b"></datalist>
        <datalist id="scene-list-both"></datalist>
      </div>
      <div>
        <label>Area Filter <small style="color:#666">(area_enter only)</small></label>
        <input id="new-area" type="text" placeholder="e.g. route_1">
      </div>
      <button class="btn btn-g" onclick="addTrigger()">+ Add</button>
    </div>
  </div>

  <style>
    .drag-handle { cursor: grab; color: #888; font-size: 1.1em; user-select: none; padding: 0 4px; }
    .drag-handle:active { cursor: grabbing; }
    tr.drag-over td { border-top: 2px solid #58a6ff; }
    .priority-badge { display:inline-block;min-width:1.6em;text-align:center;background:#30363d;color:#8b949e;border-radius:3px;font-size:.75em;padding:1px 4px;font-family:monospace; }
  </style>

  <script>
    var triggers = [];
    var triggersLoaded = false;
    var _dragSrcIdx = null;

    function esc(s) {
      return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }
    function msg(text, isErr) {
      var el = document.getElementById('msg');
      el.textContent = text;
      el.className = isErr ? 'err' : '';
    }

    function renderTriggers() {
      var tbody = document.getElementById('triggers-body');
      if (!triggers.length) {
        tbody.innerHTML = '<tr><td colspan="8" style="color:#555;text-align:center;padding:1em">No triggers — add one below</td></tr>';
        return;
      }
      tbody.innerHTML = triggers.map(function(t, i) {
        var af = t.area_id_filter ? ('<code>' + esc(t.area_id_filter) + '</code>') : '<span style="color:#444">—</span>';
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
      fetch('/api/obs/triggers', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({triggers:triggers})})
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
        area_id_filter: document.getElementById('new-area').value.trim()
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

    function loadStatus() {
      fetch('/api/obs/status').then(function(r){return r.json();}).then(function(d) {
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
        loadScenes('a');
        loadScenes('b');
      }).catch(function(){});
    }

    var _scenesCache = {a: [], b: []};
    function loadScenes(player) {
      fetch('/api/obs/scenes/' + player).then(function(r){return r.json();}).then(function(d) {
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
      fetch('/api/obs/config', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)})
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
      fetch('/api/obs/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
        .then(function(r){return r.json();}).then(function(d){
          if (d.ok && pw) document.getElementById('pw-'+player).value='';
          msg(d.ok ? ('Connecting player '+player.toUpperCase()+'...') : ('Error: '+d.error), !d.ok);
          setTimeout(loadStatus, 1500);
        });
    }

    function disconnect(player) {
      fetch('/api/obs/disconnect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({player:player})})
        .then(function(r){return r.json();}).then(function(d){
          msg(d.ok ? ('Disconnected player '+player.toUpperCase()) : ('Error: '+d.error), !d.ok);
          setTimeout(loadStatus, 500);
        });
    }

    function testScene(player) {
      var scene = prompt('Scene name to switch to for Player ' + player.toUpperCase() + ':');
      if (!scene) return;
      fetch('/api/obs/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({player:player,scene:scene})})
        .then(function(r){return r.json();}).then(function(d){
          msg(d.ok ? ('\u2714 Scene changed to "'+scene+'"') : ('Error: '+d.error), !d.ok);
        });
    }

    loadStatus();
    setInterval(loadStatus, 5000);
  </script>
</body>
</html>"""

    async def handle_obs_page(self, request):
        return aiohttp_web.Response(text=self._OBS_PAGE_HTML, content_type="text/html")

    async def handle_obs_status(self, request):
        """GET /api/obs/status — connection status + config (passwords omitted)."""
        status = self.obs.get_status()
        # Include triggers (no passwords in triggers)
        status["triggers"] = self.obs._config.get("triggers", [])
        return aiohttp_web.json_response(status)

    async def handle_obs_config(self, request):
        """POST /api/obs/config — save config and hot-reload connections."""
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        new_cfg = {
            "enabled": bool(body.get("enabled", False)),
            "connections": {},
            "triggers": body.get("triggers", []),
        }
        for pid in ("a", "b"):
            conn_in = body.get("connections", {}).get(pid, {})
            existing_pw = self.obs._config.get("connections", {}).get(pid, {}).get("password", "")
            new_cfg["connections"][pid] = {
                "host": str(conn_in.get("host", "")),
                "port": int(conn_in.get("port", 4455)),
                # Empty password = keep existing; non-empty = update
                "password": conn_in.get("password") or existing_pw,
            }
        # Ensure each trigger has an id
        import uuid as _uuid
        for t in new_cfg["triggers"]:
            if not t.get("id"):
                t["id"] = _uuid.uuid4().hex[:8]
        await self.obs.apply_new_config(new_cfg)
        return aiohttp_web.json_response({"ok": True})

    async def handle_obs_triggers(self, request):
        """POST /api/obs/triggers — save only the triggers list (auto-save, no creds)."""
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        import uuid as _uuid
        triggers = body.get("triggers", [])
        for t in triggers:
            if not t.get("id"):
                t["id"] = _uuid.uuid4().hex[:8]
        # Update triggers in-place — don't restart OBS connections (would briefly disconnect both players)
        self.obs._config["triggers"] = triggers
        self.obs.save_config()
        return aiohttp_web.json_response({"ok": True})

    async def handle_obs_scenes(self, request):
        """GET /api/obs/scenes/{player} — list available scene names from OBS."""
        player = request.match_info.get("player", "a")
        if player not in ("a", "b"):
            return aiohttp_web.json_response({"ok": False, "scenes": []}, status=400)
        scenes = await self.obs.list_scenes(player)
        return aiohttp_web.json_response({"ok": True, "scenes": scenes})

    async def handle_obs_test(self, request):
        """POST /api/obs/test — fire a test scene change immediately."""
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        player = body.get("player", "a")
        scene  = body.get("scene", "")
        if player not in ("a", "b"):
            return aiohttp_web.json_response({"ok": False, "error": "Invalid player"}, status=400)
        if not scene:
            return aiohttp_web.json_response({"ok": False, "error": "scene required"}, status=400)
        result = await self.obs.test_scene(player, scene)
        return aiohttp_web.json_response(result)

    async def handle_obs_connect(self, request):
        """POST /api/obs/connect — save connection settings for this player and (re)connect."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        player = body.get("player", "a")
        if player not in ("a", "b"):
            return aiohttp_web.json_response({"ok": False, "error": "Invalid player"}, status=400)
        # Persist any connection settings provided — preserves the other player's settings
        host = str(body.get("host", "")).strip()
        port_raw = body.get("port")
        port = int(port_raw) if port_raw else None
        password = body.get("password")  # None = not provided; "" = explicitly cleared
        if host or port is not None or password:
            conns = {k: dict(v) for k, v in self.obs._config.get("connections", {}).items()}
            conn = dict(conns.get(player, {}))
            if host:
                conn["host"] = host
            if port is not None:
                conn["port"] = port
            if password:  # only update if non-empty; blank = keep existing
                conn["password"] = password
            conns[player] = conn
            self.obs._config = {**self.obs._config, "connections": conns}
            self.obs.save_config()
        await self.obs.connect_player(player)
        return aiohttp_web.json_response({"ok": True})

    async def handle_obs_disconnect(self, request):
        """POST /api/obs/disconnect — disconnect a player's OBS."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        player = body.get("player", "a")
        if player not in ("a", "b"):
            return aiohttp_web.json_response({"ok": False, "error": "Invalid player"}, status=400)
        await self.obs.disconnect_player(player)
        return aiohttp_web.json_response({"ok": True})

    async def handle_bot_status(self, request):
        """GET /api/bot/status — returns current bot status + config + recent activity."""
        cfg = _bot_load_config(self._data_dir)
        access_token = os.environ.get("TWITCH_ACCESS_TOKEN", "")
        connected = (self._bot_instance is not None
                     and self._bot_task is not None
                     and not self._bot_task.done()
                     and bool(access_token))
        status = "disabled" if not cfg.get("enabled", True) else ("connected" if connected else "disconnected")
        return aiohttp_web.json_response({
            "ok": True,
            "status": status,
            "access_token_set": bool(access_token),
            "client_id_set": bool(cfg.get("client_id", "")),
            "last_error": self._bot_last_error,
            "channel": cfg.get("channel", ""),
            "config": {k: v for k, v in cfg.items() if k != "token"},
            "activity": list(self._bot_activity[-50:]),
        })

    async def handle_bot_config(self, request):
        """POST /api/bot/config — save non-sensitive config to data/twitch_bot.json."""
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        cfg = _bot_load_config(self._data_dir)
        allowed = {"channel", "nick", "prefix", "command_cooldown_sec", "enabled", "client_id"}
        for k in allowed:
            if k in body:
                cfg[k] = body[k]
        _bot_save_config(self._data_dir, cfg)
        return aiohttp_web.json_response({"ok": True})

    async def handle_bot_reload(self, request):
        """POST /api/bot/reload — cancel + restart the bot task."""
        await self._restart_bot()
        return aiohttp_web.json_response({"ok": True})

    async def handle_bot_enable(self, request):
        """POST /api/bot/enable — mark enabled in config and restart."""
        cfg = _bot_load_config(self._data_dir)
        cfg["enabled"] = True
        _bot_save_config(self._data_dir, cfg)
        await self._restart_bot()
        return aiohttp_web.json_response({"ok": True})

    async def handle_bot_disable(self, request):
        """POST /api/bot/disable — mark disabled and cancel task."""
        cfg = _bot_load_config(self._data_dir)
        cfg["enabled"] = False
        _bot_save_config(self._data_dir, cfg)
        if self._bot_task and not self._bot_task.done():
            self._bot_task.cancel()
            try:
                await self._bot_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._bot_task = None
        self._bot_instance = None
        return aiohttp_web.json_response({"ok": True})

    async def handle_bot_preview(self, request):
        """POST /api/bot/preview — return what a command would reply without sending."""
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        cmd = (body.get("command") or "").lower().strip()
        arg = (body.get("arg") or "").strip()
        if self._bot_instance:
            reply = await self._bot_instance.build_reply(cmd, arg)
        else:
            try:
                from server.twitch_bot import build_reply_standalone
                reply = await build_reply_standalone(cmd, arg, self, self._data_dir or DATA_DIR)
            except Exception as e:
                reply = f"(Bot not running — {e})"
        return aiohttp_web.json_response({"ok": True, "reply": reply})

    async def _restart_bot(self):
        """Cancel the existing bot task (if any) and start a fresh one."""
        if self._bot_task and not self._bot_task.done():
            self._bot_task.cancel()
            try:
                await self._bot_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._bot_task = None
        self._bot_instance = None
        cfg = _bot_load_config(self._data_dir)
        if not cfg.get("enabled", True):
            return
        access_token = os.environ.get("TWITCH_ACCESS_TOKEN", "")
        if not access_token:
            self._bot_last_error = (
                "TWITCH_ACCESS_TOKEN environment variable is not set. "
                "Set it before starting the server (see /twitch for instructions)."
            )
            log.warning("Twitch bot: TWITCH_ACCESS_TOKEN not set — bot disabled")
            return
        refresh_token = os.environ.get("TWITCH_REFRESH_TOKEN", "")
        client_secret = os.environ.get("TWITCH_CLIENT_SECRET", "")
        if not client_secret:
            self._bot_last_error = (
                "TWITCH_CLIENT_SECRET environment variable is not set. "
                "Generate a Client Secret at dev.twitch.tv/console → your app → New Secret."
            )
            log.warning("Twitch bot: TWITCH_CLIENT_SECRET not set — bot disabled")
            return
        client_id = cfg.get("client_id", "")
        if not client_id:
            self._bot_last_error = (
                "Client ID is not configured. Register an app at dev.twitch.tv/console, "
                "copy the Client ID, and save it in the config form."
            )
            log.warning("Twitch bot: client_id not set — bot disabled")
            return
        if not cfg.get("channel"):
            self._bot_last_error = "Channel is not configured. Enter a channel name and save."
            log.warning("Twitch bot: channel not set — bot disabled")
            return
        self._bot_last_error = ""
        try:
            from server.twitch_bot import SLinkChatBot
            bot = SLinkChatBot(
                self, self._data_dir or DATA_DIR, cfg,
                access_token=access_token,
                refresh_token=refresh_token,
                client_id=client_id,
                client_secret=client_secret,
            )
            self._bot_instance = bot
            self._bot_task = asyncio.create_task(bot.start())
            self._bot_task.add_done_callback(self._on_bot_done)
            log.info(f"Twitch bot started for channel #{cfg.get('channel','?')}")
        except Exception as e:
            self._bot_last_error = f"Startup failed: {e}"
            log.error(f"Twitch bot startup failed: {e}")

    def _on_bot_done(self, task):
        if task.cancelled():
            pass
        elif task.exception():
            err = str(task.exception())
            self._bot_last_error = f"Connection failed: {err}"
            log.error(f"Twitch bot task failed: {err}")
            entry = {"ts": datetime.utcnow().isoformat(), "text": f"⚠ Error: {err}"}
            self._bot_activity.append(entry)
            if len(self._bot_activity) > 50:
                self._bot_activity = self._bot_activity[-50:]
        self._bot_task = None
        self._bot_instance = None

    # ── Debug page & API ─────────────────────────────────────────────────────

    async def handle_debug_html(self, request):
        return aiohttp_web.Response(
            text=_DEBUG_HTML.replace("{page_title}", html.escape(self._page_title())),
            content_type="text/html",
        )

    async def handle_debug_manual_link_data(self, request):
        """GET /api/debug/manual_link_data — return mon options + area data for manual linking."""
        s = self.state
        # Build reverse map: monKey → pending area
        pending_key_to_area: dict[tuple, str] = {}
        for pc_area, players in s.pending_captures.items():
            for pid_pc, mon_pc in players.items():
                pending_key_to_area[(pid_pc, mon_pc.key)] = pc_area

        result: dict = {}
        for pid in ["a", "b"]:
            opts = []
            seen_keys = set()
            # Party mons
            for key in self._get_party_ordered(pid):
                det = self.party_details[pid][key]
                nick = det.get("nickname", "")
                sid = det.get("species_id", 0)
                sp_name = self.adapter.species_name(sid) if sid else "?"
                lv = det.get("level", 0)
                linked = key in s._key_index
                label = f"{nick or sp_name} Lv{lv} [{key[:8]}]"
                pend = pending_key_to_area.get((pid, key), "")
                opts.append({"key": key, "label": label, "linked": linked,
                             "pending_area": pend, "loc": "party"})
                seen_keys.add(key)
            # Box mons
            for bentry in self.pc_boxes.get(pid, []):
                key = bentry.get("key", "")
                if not key:
                    continue
                nick = bentry.get("nickname", "")
                sid = bentry.get("species_id", 0)
                sp_name = self.adapter.species_name(sid) if sid else "?"
                box_num = bentry.get("box", 0) + 1
                linked = key in s._key_index
                label = f"{nick or sp_name} [Box{box_num}] [{key[:8]}]"
                pend = pending_key_to_area.get((pid, key), "")
                opts.append({"key": key, "label": label, "linked": linked,
                             "pending_area": pend, "loc": "box"})
                seen_keys.add(key)
            # Linked/dead/memorial mons from link entries (not already shown)
            for entry in s.links:
                mon = entry.a if pid == "a" else entry.b
                if not mon or mon.key in seen_keys:
                    continue
                nick = mon.nickname or ""
                sp_name = self.adapter.species_name(mon.species) if mon.species else "?"
                status_tag = entry.status.value.upper()
                label = f"{nick or sp_name} Lv{mon.level} [{mon.key[:8]}] ({status_tag})"
                opts.append({"key": mon.key, "label": label, "linked": True,
                             "pending_area": "", "loc": status_tag.lower()})
                seen_keys.add(mon.key)
            # Pending captures not yet in party/box display (e.g. quarantined)
            for pc_area, players in s.pending_captures.items():
                cap = players.get(pid)
                if cap and cap.key not in seen_keys:
                    sp_name = self.adapter.species_name(cap.species) if cap.species else "?"
                    label = f"{cap.nickname or sp_name} Lv{cap.level} [{cap.key[:8]}] (PENDING)"
                    opts.append({"key": cap.key, "label": label, "linked": False,
                                 "pending_area": pc_area, "loc": "pending"})
                    seen_keys.add(cap.key)
            result[f"{pid}_options"] = opts

        # Build area list
        try:
            _base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            # Try adapter-specific area map first, fall back to gen3_frlge
            _game_id = self.adapter.game_id if self.adapter else "gen3_frlge"
            _map_path = os.path.join(_base_dir, "data", "games", _game_id, "area_map.json")
            if not os.path.exists(_map_path):
                _map_path = os.path.join(_base_dir, "data", "games", "gen3_frlge", "area_map.json")
            with open(_map_path) as _mf:
                _all_area_ids = sorted(set(v for v in json.load(_mf).values() if v))
        except Exception:
            _all_area_ids = []
        all_area_set = set(_all_area_ids)
        for extra_src in [s.area_states.keys(), s.pending_captures.keys()]:
            for extra in extra_src:
                if extra and extra not in all_area_set:
                    _all_area_ids.append(extra)
                    all_area_set.add(extra)
        if "gift" not in all_area_set:
            _all_area_ids.append("gift")
        _all_area_ids.sort()

        area_data: dict[str, dict] = {}
        for aid in _all_area_ids:
            disp = self.adapter.area_display_name(aid)
            st = s.area_states.get(aid)
            st_str = st.value if st else "unseen"
            pend_who = ""
            if aid in s.pending_captures:
                pend_who = ",".join(sorted(s.pending_captures[aid].keys()))
            area_data[aid] = {"d": disp, "s": st_str, "p": pend_who}

        result["areas"] = area_data
        result["area_ids"] = _all_area_ids
        result["name_a"] = self.trainer_name.get("a") or "Player A"
        result["name_b"] = self.trainer_name.get("b") or "Player B"
        return aiohttp_web.json_response(result)

    async def handle_debug_raw_state(self, request):
        """GET /api/debug/raw_state — return raw links.json content + live state."""
        s = self.state
        raw = {}
        if os.path.exists(s._links_path):
            with open(s._links_path) as f:
                raw = json.load(f)
        raw["_live"] = {
            "queued_commands": {p: list(cmds) for p, cmds in s.queued_commands.items()},
            "connected_players": {p: dict(d) for p, d in self.connected_players.items()},
            "player_area": dict(self.player_area),
            "player_ball_count": dict(self.player_ball_count),
            "party_keys": {p: sorted(keys) for p, keys in s.party_keys.items()},
            "bonus_keys": {p: sorted(keys) for p, keys in s.bonus_keys.items()},
            "pending_bonus": {p: list(q) for p, q in s.pending_bonus.items()},
            "party_size": dict(s.party_size),
            "identity_errors": dict(s.identity_error),
            "battle_state": {p: {"in_battle": bs["in_battle"],
                                  "is_trainer": bs["is_trainer_battle"]}
                             for p, bs in self.battle_state.items()},
            "recent_events": list(self._recent_events),
        }
        # Memorial data for debug panel
        mem_box_idx = self.adapter.memorial_box_index if self.adapter else -1
        memorial_log = []
        mem_path = s._memorial_path
        if os.path.exists(mem_path):
            try:
                with open(mem_path) as mf:
                    memorial_log = json.load(mf)
            except Exception:
                pass
        # Build memorial box contents from pc_boxes (mons in the memorial box)
        memorial_box_contents: dict[str, list] = {}
        if mem_box_idx >= 0:
            # Collect all dead/memorial keys from link entries for cross-referencing
            dead_keys: set[str] = set()
            pending_mem_keys: set[str] = set()
            pending_cap_keys: set[str] = set()
            for entry in s.links:
                if entry.status.value in ("dead", "memorial"):
                    if entry.a:
                        dead_keys.add(entry.a.key)
                    if entry.b:
                        dead_keys.add(entry.b.key)
            for pid in ("a", "b"):
                pending_mem_keys.update(s.pending_memorials.get(pid, set()))
                for _area, players in s.pending_captures.items():
                    cap = players.get(pid)
                    if cap:
                        pending_cap_keys.add(cap.key)
            for pid in ("a", "b"):
                entries = []
                for bentry in self.pc_boxes.get(pid, []):
                    if bentry.get("box") == mem_box_idx:
                        key = bentry.get("key", "")
                        status = "dead" if key in dead_keys else "unknown"
                        if key in pending_mem_keys and status == "unknown":
                            status = "pending_memorial"
                        if key in pending_cap_keys:
                            status = "quarantined"  # should NOT be here
                        entries.append({
                            "slot": bentry.get("slot", 0),
                            "key": key,
                            "species_id": bentry.get("species_id", 0),
                            "nickname": bentry.get("nickname", ""),
                            "species_name": self.adapter.species_name(bentry.get("species_id", 0)) if self.adapter else "",
                            "status": status,
                        })
                entries.sort(key=lambda e: e["slot"])
                memorial_box_contents[pid] = entries
        raw["_memorial"] = {
            "memorial_box_index": mem_box_idx,
            "memorial_log": memorial_log,
            "memorial_box_contents": memorial_box_contents,
            "pending_memorials": {
                pid: [
                    {
                        "key": k,
                        "species_name": self._memorial_key_species(k),
                    }
                    for k in keys
                ]
                for pid, keys in s.pending_memorials.items()
            },
        }
        return aiohttp_web.json_response(raw)

    async def handle_debug_inject_event(self, request):
        """POST /api/debug/inject_event — send a synthetic event through the state machine."""
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        player = body.pop("player", "a")
        if player not in ("a", "b"):
            return aiohttp_web.json_response({"ok": False, "error": "player must be 'a' or 'b'"}, status=400)
        if "event" not in body:
            return aiohttp_web.json_response({"ok": False, "error": "event field required"}, status=400)
        try:
            cmds = self.state.handle_event(player, body)
            self._notify_sse()
            return aiohttp_web.json_response({
                "ok": True,
                "player": player,
                "event": body.get("event"),
                "commands_returned": cmds,
            })
        except Exception as e:
            log.exception(f"Debug inject_event error: {e}")
            return aiohttp_web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_debug_queue_command(self, request):
        """POST /api/debug/queue_command — manually queue a command for a player."""
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        player = body.pop("player", "a")
        if player not in ("a", "b"):
            return aiohttp_web.json_response({"ok": False, "error": "player must be 'a' or 'b'"}, status=400)
        cmd_type = body.get("cmd", "noop")
        cmd = {"cmd": cmd_type}
        for k, v in body.items():
            if k not in ("player",):
                cmd[k] = v
        self.state.queued_commands.setdefault(player, []).append(cmd)
        self._notify_sse()
        return aiohttp_web.json_response({
            "ok": True,
            "player": player,
            "command": cmd,
            "queue_length": len(self.state.queued_commands[player]),
        })

    async def handle_debug_set_pokeballs(self, request):
        """POST /api/debug/set_pokeballs — toggle pokeballs_obtained."""
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        player = body.get("player", "a")
        value = bool(body.get("value", True))
        self.state.pokeballs_obtained[player] = value
        self.state._save()
        self._notify_sse()
        return aiohttp_web.json_response({
            "ok": True, "player": player,
            "pokeballs_obtained": value,
        })

    async def handle_debug_set_area_state(self, request):
        """POST /api/debug/set_area_state — manually set an area's state."""
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        area_id = body.get("area_id", "").strip()
        new_state = body.get("state", "").strip()
        if not area_id:
            return aiohttp_web.json_response({"ok": False, "error": "area_id required"}, status=400)
        from server.state import AreaStatus
        valid = {s.value: s for s in AreaStatus}
        if new_state not in valid:
            return aiohttp_web.json_response({"ok": False, "error": f"Invalid state. Valid: {list(valid.keys())}"}, status=400)
        if new_state == "unseen":
            self.state.area_states.pop(area_id, None)
        else:
            self.state.area_states[area_id] = valid[new_state]
        self.state._save()
        self._notify_sse()
        return aiohttp_web.json_response({
            "ok": True, "area_id": area_id, "state": new_state,
        })

    async def handle_debug_clear_pending(self, request):
        """POST /api/debug/clear_pending — clear pending captures (all or by area)."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        area_id = body.get("area_id", "").strip()
        if area_id:
            removed = area_id in self.state.pending_captures
            self.state.pending_captures.pop(area_id, None)
            msg = f"Cleared pending for {area_id}" if removed else f"No pending for {area_id}"
        else:
            count = len(self.state.pending_captures)
            self.state.pending_captures.clear()
            msg = f"Cleared all pending captures ({count} areas)"
        self.state._save()
        self._notify_sse()
        return aiohttp_web.json_response({"ok": True, "message": msg})

    async def handle_debug_unlink(self, request):
        """POST /api/debug/unlink — remove a link entry.

        Body: {"area_id": "route_1", "index": 0}
        Uses index as tiebreaker if multiple links share an area (shouldn't happen
        but be safe). Removes the link entry, cleans up _key_index and area_states.
        """
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        area_id = body.get("area_id", "").strip()
        idx = body.get("index", -1)
        if not area_id:
            return aiohttp_web.json_response({"ok": False, "error": "area_id required"}, status=400)

        from server.state import AreaStatus

        s = self.state
        # Find the entry — match by area_id and list index for safety
        entry = None
        if isinstance(idx, int) and 0 <= idx < len(s.links):
            candidate = s.links[idx]
            if candidate.area_id == area_id:
                entry = candidate
        # Fallback: search by area_id
        if entry is None:
            for e in s.links:
                if e.area_id == area_id:
                    entry = e
                    break
        if entry is None:
            return aiohttp_web.json_response(
                {"ok": False, "error": f"No link found for area {area_id}"}, status=404)

        # Remove from _key_index
        if entry.a and entry.a.key in s._key_index:
            del s._key_index[entry.a.key]
        if entry.b and entry.b.key in s._key_index:
            del s._key_index[entry.b.key]

        # Remove from links list
        s.links.remove(entry)

        # Reset area state to unseen (unless there are pending captures)
        if area_id in s.pending_captures:
            remaining = s.pending_captures[area_id]
            if "a" in remaining and "b" not in remaining:
                s.area_states[area_id] = AreaStatus.PENDING_B
            elif "b" in remaining and "a" not in remaining:
                s.area_states[area_id] = AreaStatus.PENDING_A
            elif "a" in remaining and "b" in remaining:
                s.area_states[area_id] = AreaStatus.PENDING_BOTH
        else:
            s.area_states[area_id] = AreaStatus.UNSEEN

        a_name = entry.a.nickname if entry.a else "?"
        b_name = entry.b.nickname if entry.b else "?"

        s._save()
        log.info(f"[unlink] Removed link: {a_name} <-> {b_name} on {area_id}")
        self._notify_sse()
        return aiohttp_web.json_response({
            "ok": True,
            "message": f"Unlinked {a_name} <-> {b_name} on {self.adapter.area_display_name(area_id)}. Area reset.",
        })

    async def handle_debug_revive(self, request):
        """POST /api/debug/revive — revive a dead/memorial link back to alive.

        Body: {"area_id": "route_22", "index": 0}
        Sets status back to alive, clears death metadata, removes from pending_memorials,
        and re-adds keys to party_keys. User must manually restore mons in-game.
        """
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        area_id = body.get("area_id", "").strip()
        idx = body.get("index", -1)
        if not area_id:
            return aiohttp_web.json_response({"ok": False, "error": "area_id required"}, status=400)

        from server.state import LinkStatus

        s = self.state
        # Find the entry
        entry = None
        if isinstance(idx, int) and 0 <= idx < len(s.links):
            candidate = s.links[idx]
            if candidate.area_id == area_id:
                entry = candidate
        if entry is None:
            for e in s.links:
                if e.area_id == area_id and e.status in (LinkStatus.DEAD, LinkStatus.MEMORIAL):
                    entry = e
                    break
        if entry is None:
            return aiohttp_web.json_response(
                {"ok": False, "error": f"No dead/memorial link found for area {area_id}"}, status=404)
        if entry.status == LinkStatus.ALIVE:
            return aiohttp_web.json_response(
                {"ok": False, "error": "Link is already alive"}, status=400)

        # Revive: set status to alive, clear death metadata
        entry.status = LinkStatus.ALIVE
        entry.killed_at = None
        entry.cause = None
        entry.killer = None
        entry.initiating_player = None

        # Remove from pending_memorials and re-add to party_keys
        if entry.a:
            s.pending_memorials["a"].discard(entry.a.key)
            s.party_keys["a"].add(entry.a.key)
        if entry.b:
            s.pending_memorials["b"].discard(entry.b.key)
            s.party_keys["b"].add(entry.b.key)

        a_name = entry.a.nickname if entry.a else "?"
        b_name = entry.b.nickname if entry.b else "?"

        s._save()
        log.info(f"[revive] Revived link: {a_name} <-> {b_name} on {area_id}")
        self._notify_sse()
        return aiohttp_web.json_response({
            "ok": True,
            "message": f"Revived {a_name} <-> {b_name} on {self.adapter.area_display_name(area_id)}. Restore mons from memorial box manually.",
        })

    async def handle_debug_list_backups(self, request):
        """GET /api/debug/backups — list available rolling backups with summary."""
        backup_dir = os.path.join(os.path.dirname(self.state._links_path), "backups")
        backups = []
        if os.path.isdir(backup_dir):
            for i in range(1, self._backup_max + 1):
                fp = os.path.join(backup_dir, f"links.backup.{i}.json")
                if os.path.exists(fp):
                    stat = os.stat(fp)
                    entry: dict = {
                        "slot": i,
                        "file": f"links.backup.{i}.json",
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    # Read backup JSON for summary stats
                    try:
                        with open(fp, "r") as fh:
                            data = json.loads(fh.read())
                        links = data.get("links", [])
                        alive = sum(1 for lnk in links if lnk.get("status") == "alive")
                        dead = sum(1 for lnk in links if lnk.get("status") in ("dead", "memorial"))
                        areas = data.get("area_states", {})
                        pending = sum(1 for v in areas.values() if v.startswith("pending"))
                        dead_zones = sum(1 for v in areas.values() if v == "dead_zone")
                        entry["summary"] = {
                            "links_alive": alive,
                            "links_dead": dead,
                            "areas_pending": pending,
                            "areas_dead_zone": dead_zones,
                        }
                    except Exception:
                        entry["summary"] = None
                    backups.append(entry)
        return aiohttp_web.json_response({"ok": True, "backups": backups})

    async def handle_debug_rollback(self, request):
        """POST /api/debug/rollback — restore links.json (and events.json) from a backup slot."""
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        slot = body.get("slot")
        if not isinstance(slot, int) or slot < 1 or slot > self._backup_max:
            return aiohttp_web.json_response(
                {"ok": False, "error": f"Invalid slot (1-{self._backup_max})"}, status=400)
        backup_dir = os.path.join(os.path.dirname(self.state._links_path), "backups")
        backup_links  = os.path.join(backup_dir, f"links.backup.{slot}.json")
        backup_events = os.path.join(backup_dir, f"events.backup.{slot}.json")
        if not os.path.exists(backup_links):
            return aiohttp_web.json_response(
                {"ok": False, "error": f"Backup slot {slot} not found"}, status=404)
        os.makedirs(backup_dir, exist_ok=True)
        # Save current state as pre-rollback snapshots
        if os.path.exists(self.state._links_path):
            shutil.copy2(self.state._links_path,
                         os.path.join(backup_dir, "links.pre_rollback.json"))
        if os.path.exists(self._events_path):
            shutil.copy2(self._events_path,
                         os.path.join(backup_dir, "events.pre_rollback.json"))
        # Restore links.json and reload state
        shutil.copy2(backup_links, self.state._links_path)
        self.state = SoulLinkState.load(
            data_dir=self._data_dir,
            species_lock=self.state.species_lock,
            gender_lock=self.state.gender_lock,
            type_lock=self.state.type_lock)
        self.adapter = self.state.adapter
        # Restore events.json and reload ring buffer
        if os.path.exists(backup_events):
            shutil.copy2(backup_events, self._events_path)
        else:
            # No events backup for this slot — clear the ring buffer so it stays in sync.
            open(self._events_path, "w").write("[]")
        self._load_events()
        log.warning(f"⚠  Rolled back to backup slot {slot}")
        self._notify_sse()
        return aiohttp_web.json_response({
            "ok": True,
            "message": f"Rolled back to backup slot {slot}. Pre-rollback state saved."
        })

    async def handle_reset_api(self, request):
        """POST /api/reset — wipe all Soul Link state and start a fresh run."""
        links_path = self.state._links_path
        if os.path.exists(links_path):
            os.remove(links_path)
        self.state = SoulLinkState(data_dir=self._data_dir,
                                   species_lock=self.state.species_lock,
                                   gender_lock=self.state.gender_lock,
                                   type_lock=self.state.type_lock)
        self.adapter = self.state.adapter
        self._last_seq.clear()
        self.connected_players.clear()
        # Clear derived display caches so SSE doesn't broadcast stale data.
        self.player_area = {"a": "", "b": ""}
        self.player_area_id = {"a": "", "b": ""}
        self.player_ball_count = {"a": 0, "b": 0}
        self.player_badges = {"a": 0, "b": 0}
        self.player_kanto_badges = {"a": 0, "b": 0}
        self.trainer_name = {"a": "", "b": ""}
        self.pc_boxes = {"a": [], "b": []}
        self.party_details = {"a": {}, "b": {}}
        self._mon_cache.clear()
        self.battle_state = {
            p: {"in_battle": False, "is_trainer_battle": False, "enemy_party": [],
                "trainer_id": 0, "opponent_name": "", "opponent_class": "",
                "is_doubles": False}
            for p in ("a", "b")
        }
        self._recent_events.clear()
        self._save_events()
        log.warning("⚠  State reset via API — all links, area states, and captures cleared.")
        self._notify_sse()
        return aiohttp_web.json_response({"ok": True, "message": "State reset. Starting fresh run."})

    def _memorial_key_species(self, key: str) -> str:
        """Look up a species name for a pending memorial key."""
        s = self.state
        entry = s._key_index.get(key)
        if entry:
            mon = entry.a if (entry.a and entry.a.key == key) else entry.b
            if mon:
                name = mon.nickname or (self.adapter.species_name(mon.species) if mon.species else "")
                if name:
                    return name
        return key[:8] if key else "?"

    def _memorial_box_indices(self) -> set[int]:
        """Return set of box indices used for memorial storage (primary + overflow).

        The primary memorial box is always excluded. Overflow is calculated from
        the number of dead/memorial links — each dead link contributes one mon per
        player to the memorial boxes. Boxes fill at 30 mons each.
        """
        from server.state import LinkStatus
        mem_idx = self.adapter.memorial_box_index if self.adapter else -1
        if mem_idx < 0:
            return set()
        indices = {mem_idx}
        mons_per_box = 30
        # Count dead/memorial mons: each such link has one mon per player in memorial
        dead_count = sum(1 for e in self.state.links
                         if e.status in (LinkStatus.DEAD, LinkStatus.MEMORIAL))
        # Add pending memorials (not yet moved but will be)
        for pid in ("a", "b"):
            dead_count += len(self.state.pending_memorials[pid])
        # How many overflow boxes beyond the primary?
        overflow_boxes = max(0, (dead_count - mons_per_box) // mons_per_box)
        for i in range(1, overflow_boxes + 1):
            if mem_idx - i >= 0:
                indices.add(mem_idx - i)
        return indices

    def _check_memorial_box_contamination(self, player_id: str, pc_boxes: list):
        """Scan pc_boxes for memorial box integrity violations and take corrective action.

        Three checks (all require a dedicated memorial box, i.e. mem_idx >= 0):

        1. Non-dead mon in memorial box — quarantine relocation (existing behaviour).
           A pending-capture that somehow ended up in the memorial box is pulled out
           and re-deposited to a normal box via party_mon + box_mon.

        2. Dead/memorial mon found in a regular (non-memorial) box — re-memorialize.
           Handles the case where a player manually retrieves a dead mon from the
           memorial box via the PC menu, or a write glitch placed it in the wrong box.

        3. Orphan in memorial box — log-only warning.
           A mon in the memorial box whose key is not tracked as dead/memorial and is
           not in pending_memorials.  We don't auto-fix this because it may be a mon
           the player placed there manually; it is surfaced as "unknown" in the debug
           panel so a human can investigate.
        """
        mem_idx = self.adapter.memorial_box_index if self.adapter else -1
        if mem_idx < 0:
            return
        s = self.state

        # Collect keys that belong in the memorial box (dead/memorial link entries).
        all_dead_keys: set[str] = set()
        for entry in s.links:
            if entry.status.value in ("dead", "memorial"):
                if entry.a:
                    all_dead_keys.add(entry.a.key)
                if entry.b:
                    all_dead_keys.add(entry.b.key)

        # Also treat pending_memorials for *this* player as "expected in memorial box"
        # so they are not flagged as orphans while still in transit.
        pending_for_player: set[str] = set(s.pending_memorials.get(player_id, set()))
        expected_in_memorial = all_dead_keys | pending_for_player

        for bentry in pc_boxes:
            box = bentry.get("box")
            key = bentry.get("key", "")
            if not key:
                continue
            nick = bentry.get("nickname", "") or (
                self.adapter.species_name(bentry.get("species_id", 0)) if self.adapter else key[:8]
            )

            if box == mem_idx:
                # ── Check 1: non-dead mon in memorial box ──────────────────────
                if key not in expected_in_memorial:
                    log.warning(
                        f"[{player_id}] ⚠ NON-DEAD mon in memorial box: {nick} [{key[:8]}] "
                        f"(box {mem_idx} slot {bentry.get('slot', '?')})"
                    )
                    # Relocate if it is a quarantined pending capture.
                    for _area, players in s.pending_captures.items():
                        cap = players.get(player_id)
                        if cap and cap.key == key:
                            log.warning(
                                f"[{player_id}] Quarantined mon {key[:8]} found in memorial box! "
                                f"Queueing party_mon + box_mon to relocate."
                            )
                            stats = s.mon_stats.get(key, {})
                            s.queued_commands[player_id].append({"cmd": "party_mon", "key": key, "stats": stats})
                            s.queued_commands[player_id].append({"cmd": "box_mon", "key": key})
                            break

                    # ── Check 3: orphan in memorial box (log-only, once per key) ────
                    # Only log if not a quarantine case (already logged above).
                    else:
                        if key not in self._warned_orphan_keys:
                            self._warned_orphan_keys.add(key)
                            log.warning(
                                f"[{player_id}] ⚠ Orphan mon in memorial box: {nick} [{key[:8]}] "
                                f"(box {mem_idx} slot {bentry.get('slot', '?')}) — "
                                f"not tracked as dead/memorial; investigate manually"
                            )

            elif key in all_dead_keys:
                # ── Check 2: dead/memorial mon found in a regular box ───────────
                # This happens if the player moved a dead mon out of the memorial box
                # via the PC, or if a previous memorialize write went to the wrong box.
                already_queued = any(
                    c.get("cmd") == "memorialize" and c.get("key") == key
                    for c in s.queued_commands.get(player_id, [])
                )
                if not already_queued:
                    log.warning(
                        f"[{player_id}] ⚠ DEAD mon in regular box {box}: {nick} [{key[:8]}] "
                        f"(slot {bentry.get('slot', '?')}) — re-queuing memorialize"
                    )
                    s._queue_memorialize(player_id, key)

    def _get_party_ordered(self, pid: str) -> list:
        """Return monKeys for player `pid` sorted by party slot order.

        Uses the ``slot`` field stored in party_details (populated from the Lua
        snapshot's ``slot=i`` field).  Falls back to 999 for old clients that
        don't send slot info, which puts them at the end in original order.
        """
        pd = self.party_details.get(pid, {})
        return sorted(pd.keys(), key=lambda k: pd[k].get("slot", 999))

    def _resolve_level(self, player_id: str, mi) -> int:
        """Return the best available level for a MonInfo.

        Falls back through mon_stats cache and party_details when the stored
        level is 0 (e.g. manual links that didn't capture level at creation).
        """
        if not mi:
            return 0
        if mi.level:
            return mi.level
        # Try mon_stats cache (set when mon was deposited to box)
        cached = self.state.mon_stats.get(mi.key)
        if cached and cached.get("level"):
            return cached["level"]
        # Try live party_details from either player
        for pid in ("a", "b"):
            det = self.party_details.get(pid, {}).get(mi.key)
            if det and det.get("level"):
                return det["level"]
        return 0

    def _lookup_mon_detail(self, player_id: str, key: str) -> dict:
        """Look up mon details from party_details first, then pc_boxes.

        Enriches with level from mon_stats cache or the link entry when the
        primary source (e.g. pc_boxes) doesn't carry it.
        """
        det = self.party_details.get(player_id, {}).get(key)
        if det:
            return det
        result: dict = {}
        for bentry in self.pc_boxes.get(player_id, []):
            if bentry.get("key") == key:
                result = dict(bentry)
                break
        if not result:
            # Check pending_captures as last resort
            for _area, players in self.state.pending_captures.items():
                mon = players.get(player_id)
                if mon and mon.key == key:
                    return {"nickname": mon.nickname, "species_id": mon.species, "level": mon.level}
        # Enrich with level from mon_stats cache or existing link entry
        if result and not result.get("level"):
            cached = self.state.mon_stats.get(key)
            if cached and cached.get("level"):
                result["level"] = cached["level"]
            else:
                link_entry = self.state._key_index.get(key)
                if link_entry:
                    mi = link_entry.a if link_entry.a and link_entry.a.key == key else link_entry.b
                    if mi and mi.level:
                        result["level"] = mi.level
        # Also check the OTHER player's party_details (for solo-testing with same OT)
        if result and not result.get("level"):
            other = "b" if player_id == "a" else "a"
            other_det = self.party_details.get(other, {}).get(key)
            if other_det and other_det.get("level"):
                result["level"] = other_det["level"]
        return result

    def _find_pending_area_for_key(self, player_id: str, key: str) -> str | None:
        """Return the area_id where this key has a pending capture, or None."""
        for area, players in self.state.pending_captures.items():
            mon = players.get(player_id)
            if mon and mon.key == key:
                return area
        return None

    async def handle_inject_link_api(self, request):
        """POST /api/inject_link — manually create a linked pair.

        Body (JSON): {"a_key": "...", "b_key": "...", "area_id": "route_1",
                      "force": false}

        Looks up mon info from party, box, AND pending_captures.
        If either mon has a pending capture on a different area than specified
        and force is not set, returns a warning with requires_force=true.
        On success, cleans up pending_captures and updates area_states.
        """
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        a_key  = body.get("a_key", "").strip()
        b_key  = body.get("b_key", "").strip()
        area   = body.get("area_id", "manual").strip()
        force  = body.get("force", False)
        override = body.get("override", False)
        if not a_key or not b_key:
            return aiohttp_web.json_response(
                {"ok": False, "error": "a_key and b_key are required"}, status=400)

        from server.state import LinkEntry, MonInfo, LinkStatus, AreaStatus

        s = self.state

        # If override requested, unlink existing entries for these keys
        if override:
            for key_to_free in [a_key, b_key]:
                old_entry = s._key_index.get(key_to_free)
                if old_entry:
                    if old_entry.a and old_entry.a.key in s._key_index:
                        del s._key_index[old_entry.a.key]
                    if old_entry.b and old_entry.b.key in s._key_index:
                        del s._key_index[old_entry.b.key]
                    if old_entry in s.links:
                        s.links.remove(old_entry)
                    old_area = old_entry.area_id
                    if old_area and old_area != area and old_area not in s.pending_captures:
                        s.area_states[old_area] = AreaStatus.UNSEEN
                    log.info(f"[inject_link] override: removed old link on {old_area}")

        # Reject already-linked keys (unless override already cleared them)
        if a_key in s._key_index:
            return aiohttp_web.json_response(
                {"ok": False, "error": f"Player A mon {a_key[:8]} is already linked."}, status=400)
        if b_key in s._key_index:
            return aiohttp_web.json_response(
                {"ok": False, "error": f"Player B mon {b_key[:8]} is already linked."}, status=400)

        # Detect pending-area conflicts
        a_pend_area = self._find_pending_area_for_key("a", a_key)
        b_pend_area = self._find_pending_area_for_key("b", b_key)
        conflicts = []
        if a_pend_area and a_pend_area != area:
            a_det = self._lookup_mon_detail("a", a_key)
            a_name = a_det.get("nickname") or f"#{a_det.get('species_id', '?')}"
            conflicts.append(f"Player A's {a_name} is pending on {self.adapter.area_display_name(a_pend_area)}")
        if b_pend_area and b_pend_area != area:
            b_det = self._lookup_mon_detail("b", b_key)
            b_name = b_det.get("nickname") or f"#{b_det.get('species_id', '?')}"
            conflicts.append(f"Player B's {b_name} is pending on {self.adapter.area_display_name(b_pend_area)}")
        if conflicts and not force:
            return aiohttp_web.json_response({
                "ok": False, "requires_force": True,
                "conflicts": conflicts,
                "error": " | ".join(conflicts) + " — use Link anyway to override.",
            })

        # Pull mon info from party, box, or pending_captures
        a_det = self._lookup_mon_detail("a", a_key)
        b_det = self._lookup_mon_detail("b", b_key)
        entry = LinkEntry(
            area_id=area,
            a=MonInfo(key=a_key,
                      nickname=a_det.get("nickname", ""),
                      species=a_det.get("species_id", 0),
                      level=a_det.get("level", 0)),
            b=MonInfo(key=b_key,
                      nickname=b_det.get("nickname", ""),
                      species=b_det.get("species_id", 0),
                      level=b_det.get("level", 0)),
            status=LinkStatus.ALIVE,
        )
        s.links.append(entry)
        s._index_entry(entry)
        s.area_states[area] = AreaStatus.LINKED

        # Clean up pending_captures for both mons
        for pid, key, pend_area in [("a", a_key, a_pend_area), ("b", b_key, b_pend_area)]:
            if pend_area and pend_area in s.pending_captures:
                s.pending_captures[pend_area].pop(pid, None)
                if not s.pending_captures[pend_area]:
                    del s.pending_captures[pend_area]
                # Recompute area_state for the old pending area (if different from link area)
                if pend_area != area:
                    remaining = s.pending_captures.get(pend_area, {})
                    if not remaining:
                        # No one pending here anymore — revert to unseen
                        s.area_states[pend_area] = AreaStatus.UNSEEN
                    elif "a" in remaining and "b" not in remaining:
                        s.area_states[pend_area] = AreaStatus.PENDING_B
                    elif "b" in remaining and "a" not in remaining:
                        s.area_states[pend_area] = AreaStatus.PENDING_A
            # Also clean pending on the link area itself
            if area in s.pending_captures:
                s.pending_captures[area].pop(pid, None)
                if not s.pending_captures[area]:
                    del s.pending_captures[area]

        # Only add to party_keys if the mon is actually in the party
        if a_key in self.party_details.get("a", {}):
            s.party_keys["a"].add(a_key)
        if b_key in self.party_details.get("b", {}):
            s.party_keys["b"].add(b_key)

        s._save()
        a_name = a_det.get("nickname") or a_key[:8]
        b_name = b_det.get("nickname") or b_key[:8]
        log.info(f"[inject_link] A:{a_name}({a_key[:8]}) <-> B:{b_name}({b_key[:8]}) area={area}")
        self._notify_sse()
        return aiohttp_web.json_response({
            "ok": True,
            "a_key": a_key, "b_key": b_key, "area_id": area,
            "message": f"Linked {a_name} <-> {b_name} on {self.adapter.area_display_name(area)}.",
        })

    async def handle_inject_link_by_slot_api(self, request):
        """POST /api/inject_link_by_slot — link party slots without knowing the keys.

        Body (JSON): {"a_slot": 0, "b_slot": 0, "area_id": "test"}
        Resolves slot indices to keys, then delegates to handle_inject_link_api.
        """
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "invalid JSON"}, status=400)

        a_slot = int(body.get("a_slot", 0))
        b_slot = int(body.get("b_slot", 0))

        s = self.state
        a_keys = sorted(s.party_keys.get("a", set()))
        b_keys = sorted(s.party_keys.get("b", set()))

        if not a_keys:
            return aiohttp_web.json_response(
                {"ok": False, "error": "No party keys known for player A."}, status=400)
        if not b_keys:
            return aiohttp_web.json_response(
                {"ok": False, "error": "No party keys known for player B."}, status=400)
        if a_slot >= len(a_keys):
            return aiohttp_web.json_response(
                {"ok": False, "error": f"a_slot {a_slot} out of range (A has {len(a_keys)} party mons)"}, status=400)
        if b_slot >= len(b_keys):
            return aiohttp_web.json_response(
                {"ok": False, "error": f"b_slot {b_slot} out of range (B has {len(b_keys)} party mons)"}, status=400)

        # Build a fake request that delegates to inject_link
        resolved = {
            "a_key": a_keys[a_slot], "b_key": b_keys[b_slot],
            "area_id": body.get("area_id", "manual"),
            "force": body.get("force", False),
        }
        class _Req:
            async def json(self_): return resolved
        return await self.handle_inject_link_api(_Req())


# ── entrypoint ─────────────────────────────────────────────────────────────────

async def main(host: str, port: int, http_port: int, reset: bool = False,
               data_dir: str = None, run_id: str = None, run_name: str = "",
               species_lock: bool = False, gender_lock: bool = False,
               type_lock: bool = False,
               manager_port: int = 0, verbose: bool = False):
    _configure_logging(data_dir, verbose)
    if reset:
        links_path = os.path.join(data_dir, "links.json") if data_dir else LINKS_PATH
        if os.path.exists(links_path):
            os.remove(links_path)
            log.warning("⚠  --reset: links.json deleted. Starting a fresh run.")
        else:
            log.info("--reset: no existing state found, starting fresh.")
    srv = SLinkServer(data_dir=data_dir, run_id=run_id, run_name=run_name,
                      tcp_port=port, manager_port=manager_port,
                      species_lock=species_lock, gender_lock=gender_lock,
                      type_lock=type_lock)

    # TCP game server
    tcp_server = await asyncio.start_server(srv.handle_client, host, port)
    addrs = ", ".join(str(s.getsockname()) for s in tcp_server.sockets)
    run_label = f" [{run_id}]" if run_id else ""
    log.info(f"SLink{run_label} TCP server listening on {addrs}")

    # Start rolling backup task
    srv.start_backup_task()
    # Start OBS worker tasks
    srv.obs.start_workers()

    # HTTP status page
    if AIOHTTP_AVAILABLE:
        app = aiohttp_web.Application()
        app.router.add_get("/",            srv.handle_status_html)
        app.router.add_get("/memorial",    srv.handle_memorial_html)
        app.router.add_get("/api/status",  srv.handle_status_json)
        app.router.add_get("/api/events",  srv.handle_sse)
        app.router.add_post("/api/reset",              srv.handle_reset_api)
        app.router.add_post("/api/inject_link",        srv.handle_inject_link_api)
        app.router.add_post("/api/inject_link_by_slot", srv.handle_inject_link_by_slot_api)
        # Stream overlay routes
        app.router.add_get("/stream",          srv.handle_stream_index)
        app.router.add_get("/stream/",         srv.handle_stream_index)
        app.router.add_get("/stream/party-a",        srv.handle_stream_party_a)
        app.router.add_get("/stream/party-b",        srv.handle_stream_party_b)
        app.router.add_get("/stream/enemy-focus-a",   srv.handle_stream_enemy_focus_a)
        app.router.add_get("/stream/enemy-focus-b",   srv.handle_stream_enemy_focus_b)
        app.router.add_get("/stream/enemy-trainer-a", srv.handle_stream_enemy_trainer_a)
        app.router.add_get("/stream/enemy-trainer-b", srv.handle_stream_enemy_trainer_b)
        app.router.add_get("/stream/links",          srv.handle_stream_links)
        app.router.add_get("/stream/linked-party", srv.handle_stream_linked_party)
        app.router.add_get("/stream/boxed-links",  srv.handle_stream_boxed_links)
        app.router.add_get("/stream/deaths",   srv.handle_stream_deaths)
        app.router.add_get("/stream/attempts", srv.handle_stream_attempts)
        app.router.add_post("/api/attempts",   srv.handle_api_attempts)
        app.router.add_get("/stream/areas",    srv.handle_stream_areas)
        app.router.add_get("/stream/events",   srv.handle_stream_events)
        app.router.add_get("/stream/badges-a", srv.handle_stream_badges_a)
        app.router.add_get("/stream/badges-b", srv.handle_stream_badges_b)
        app.router.add_get("/stream/encounters",      srv.handle_stream_encounters)
        app.router.add_get("/stream/stream-memorial", srv.handle_stream_stream_memorial)
        app.router.add_get("/stream/ticker",          srv.handle_stream_ticker)
        app.router.add_get("/stream/focus-a",         srv.handle_stream_focus_a)
        app.router.add_get("/stream/focus-b",         srv.handle_stream_focus_b)
        app.router.add_get("/stream/area-encounter",  srv.handle_stream_area_encounter)
        app.router.add_get("/stream/enc-table-a",     srv.handle_stream_enc_table_a)
        app.router.add_get("/stream/enc-table-b",     srv.handle_stream_enc_table_b)
        app.router.add_get("/launcher/{player}", srv.handle_launcher)
        # Twitch bot routes
        app.router.add_get("/twitch",               srv.handle_twitch_page)
        app.router.add_get("/api/bot/status",       srv.handle_bot_status)
        app.router.add_post("/api/bot/config",      srv.handle_bot_config)
        app.router.add_post("/api/bot/reload",      srv.handle_bot_reload)
        app.router.add_post("/api/bot/enable",      srv.handle_bot_enable)
        app.router.add_post("/api/bot/disable",     srv.handle_bot_disable)
        app.router.add_post("/api/bot/preview",     srv.handle_bot_preview)
        # OBS scene trigger routes
        app.router.add_get("/obs",                  srv.handle_obs_page)
        app.router.add_get("/api/obs/status",       srv.handle_obs_status)
        app.router.add_post("/api/obs/config",      srv.handle_obs_config)
        app.router.add_post("/api/obs/triggers",    srv.handle_obs_triggers)
        app.router.add_get("/api/obs/scenes/{player}", srv.handle_obs_scenes)
        app.router.add_post("/api/obs/test",        srv.handle_obs_test)
        app.router.add_post("/api/obs/connect",     srv.handle_obs_connect)
        app.router.add_post("/api/obs/disconnect",  srv.handle_obs_disconnect)
        # Debug routes
        app.router.add_get("/debug",                       srv.handle_debug_html)
        app.router.add_get("/api/debug/raw_state",         srv.handle_debug_raw_state)
        app.router.add_get("/api/debug/manual_link_data",  srv.handle_debug_manual_link_data)
        app.router.add_post("/api/debug/inject_event",     srv.handle_debug_inject_event)
        app.router.add_post("/api/debug/queue_command",    srv.handle_debug_queue_command)
        app.router.add_post("/api/debug/set_pokeballs",    srv.handle_debug_set_pokeballs)
        app.router.add_post("/api/debug/set_area_state",   srv.handle_debug_set_area_state)
        app.router.add_post("/api/debug/clear_pending",    srv.handle_debug_clear_pending)
        app.router.add_post("/api/debug/unlink",            srv.handle_debug_unlink)
        app.router.add_post("/api/debug/revive",            srv.handle_debug_revive)
        app.router.add_get("/api/debug/backups",            srv.handle_debug_list_backups)
        app.router.add_post("/api/debug/rollback",          srv.handle_debug_rollback)
        # RR Damage Calculator routes
        app.router.add_get("/calc",           srv.handle_calc_redirect)
        app.router.add_get("/calc/",          srv.handle_calc_redirect)
        app.router.add_get("/calc/{path:.*}", srv.handle_calc_files)
        app.router.add_get("/api/calc/mons",  srv.handle_calc_mons)
        runner = aiohttp_web.AppRunner(app)
        await runner.setup()
        http_site = aiohttp_web.TCPSite(runner, host, http_port)
        await http_site.start()
        # Start Twitch bot if configured
        await srv._restart_bot()
        log.info(f"SLink{run_label} status page at http://{host if host != '0.0.0.0' else 'localhost'}:{http_port}/")
    else:
        log.warning("aiohttp not installed — HTTP status page disabled. Run: pip install aiohttp")
        runner = None

    async with tcp_server:
        await tcp_server.serve_forever()

    if runner:
        await runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SLink Soul Link server")
    parser.add_argument("--host",      default="0.0.0.0",  help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port",      type=int, default=54321, help="TCP port (default: 54321)")
    parser.add_argument("--http-port", type=int, default=8080,  help="HTTP status port (default: 8080)")
    parser.add_argument("--reset",     action="store_true",     help="Clear all saved state and start a fresh run")
    parser.add_argument("--data-dir",  default=None,            help="Data directory for links/memorial JSON (default: data/)")
    parser.add_argument("--run-id",    default=None,            help="Optional run label (used in log output)")
    parser.add_argument("--run-name",  default="",              help="Human-readable run name (shown in page title)")
    parser.add_argument("--species-clause", action="store_true", dest="species_lock", help="Reject links where both mons share the same evolution family")
    parser.add_argument("--gender-clause",  action="store_true", dest="gender_lock",  help="Reject links where both mons share the same gender")
    parser.add_argument("--type-clause",    action="store_true", dest="type_lock",    help="Reject links where both mons share any type")
    parser.add_argument("--manager-port", type=int, default=0,   help="Manager HTTP port (enables 'Run Manager' link on status page)")
    parser.add_argument("--verbose",      action="store_true",   help="Enable DEBUG-level logging to file and console (default: INFO only)")
    args = parser.parse_args()
    asyncio.run(main(args.host, args.port, args.http_port, args.reset, args.data_dir, args.run_id,
                     run_name=args.run_name,
                     species_lock=args.species_lock, gender_lock=args.gender_lock,
                     type_lock=args.type_lock,
                     manager_port=args.manager_port,
                     verbose=args.verbose))