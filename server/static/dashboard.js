/* dashboard.js — client-side glue for the per-run status dashboard.
 *
 * Loaded by server.py:_STATUS_HTML with `defer` so it runs after the body
 * markup parses. Refresh is owned by HTMX — the #content div declares
 *   hx-ext="morph,sse" sse-connect="/api/events"
 *   hx-trigger="sse:ping" hx-swap="morph:outerHTML"
 * — idiomorph preserves <img> identity (data-species) and <details open>
 * state across swaps. This file just handles:
 *
 *   • Sprite background removal (funnotbun chroma-key)
 *   • Mouse-interaction pause via htmx:beforeSwap
 *   • Attempts +/- handler (delegates refresh to htmx.trigger)
 *   • Sort + filter re-application after each swap
 *
 * The calc-preview render is rendered separately by the inline {calc_js}
 * block in _STATUS_HTML because it consumes Python-injected state.
 */

// Idempotence sentinel — base.html loads dashboard.js conditionally on
// sidebar_html, and dashboard.html's head_extra block loads it again. Without
// this guard the IIFEs below would re-run, resetting closure state (sort
// column, active filter, etc.) on the second execution. Bail out early if
// we've already initialised in this document.
if (window._slinkDashInit) {
  // Already loaded — skip the body of this file.
} else {
  window._slinkDashInit = true;

(function() {
  // Cache processed sprite data URLs by original src to avoid re-processing.
  var spriteCache = {};

  // Remove solid background from GBA-style sprite PNGs.
  // Reads top-left pixel as bg color and sets all matching pixels transparent.
  function removeSpriteBackground(img) {
    if (img.dataset.bgRemoved || !img.naturalWidth) return;
    var src = img.src;
    // Only process funnotbun sprites (they have solid bg; PokeAPI are already transparent).
    if (src.indexOf('funnotbun') === -1) return;
    if (spriteCache[src]) {
      img.src = spriteCache[src];
      img.dataset.bgRemoved = '1';
      return;
    }
    var c = document.createElement('canvas');
    c.width = img.naturalWidth;
    c.height = img.naturalHeight;
    var ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0);
    try {
      var data = ctx.getImageData(0, 0, c.width, c.height);
      var px = data.data;
      var bgR = px[0], bgG = px[1], bgB = px[2];
      for (var i = 0; i < px.length; i += 4) {
        if (px[i] === bgR && px[i + 1] === bgG && px[i + 2] === bgB) {
          px[i + 3] = 0;
        }
      }
      ctx.putImageData(data, 0, 0);
      var dataUrl = c.toDataURL();
      spriteCache[src] = dataUrl;
      img.src = dataUrl;
    } catch (e) {
      // CORS or security error — leave original.
    }
    img.dataset.bgRemoved = '1';
  }

  function processAllSprites() {
    document.querySelectorAll('img.mon-sprite, img.enc-sprite').forEach(function(img) {
      if (img.dataset.bgRemoved) return;
      var origSrc = img.getAttribute('src');
      if (origSrc && spriteCache[origSrc]) {
        img.src = spriteCache[origSrc];
        img.dataset.bgRemoved = '1';
        return;
      }
      if (img.complete && img.naturalWidth) {
        removeSpriteBackground(img);
      } else {
        img.crossOrigin = 'anonymous';
        img.addEventListener('load', function() { removeSpriteBackground(img); }, { once: true });
      }
    });
  }

  // After HTMX swaps in new content, re-run sprite chroma-key + sort + filter
  // + calc-preview pipeline. (DOMContentLoaded covers the initial paint;
  // htmx:afterSettle covers every refresh.)
  function refreshClientUI() {
    if (window._slinkEncSort)   window._slinkEncSort();
    if (window._slinkEncFilter) window._slinkEncFilter();
    if (window._slinkSearch)    window._slinkSearch();
    processAllSprites();
    if (window._slinkCalcRender) window._slinkCalcRender();
  }
  document.body.addEventListener('htmx:afterSettle', refreshClientUI);

  // Mouse-interaction pause — preserve clicks even when an SSE ping arrives
  // mid-mousedown. Cancel beforeSwap if the user is interacting and re-fire
  // the morph after mouseup.
  var userInteracting = false;
  var pendingSwap = null;
  document.addEventListener('mousedown', function() { userInteracting = true; });
  document.addEventListener('mouseup', function() {
    setTimeout(function() {
      userInteracting = false;
      if (pendingSwap && window.htmx) {
        pendingSwap = null;
        window.htmx.trigger(document.body, 'sse:ping');
      }
    }, 250);
  });
  document.body.addEventListener('htmx:beforeSwap', function(ev) {
    if (userInteracting) { ev.preventDefault(); pendingSwap = true; return; }
    // Pre-swap chroma-key: HTMX's polling refresh fetches a fresh HTML
    // response, and idiomorph syncs every <img>'s src back to the original
    // funnotbun URL (with green/blue background) — even on elements we've
    // already chroma-keyed. The CSS visibility-hidden rule then hides the
    // sprite for a frame until JS re-processes it, which reads as a flicker
    // every 2 seconds.
    //
    // Fix: rewrite each funnotbun src in the incoming HTML to the cached
    // transparent data URL we've already computed, and tag it
    // `data-bg-removed="1"`. By the time idiomorph applies the morph the
    // sprite already points at the transparent version, so there's no
    // background to flash. HTMX exposes the modifiable response body on
    // `event.detail.serverResponse` (xhr.responseText is read-only per spec
    // — that's why earlier attempts to assign back to xhr did nothing).
    try {
      var html = ev.detail && ev.detail.serverResponse;
      if (!html || html.indexOf('funnotbun') === -1) return;
      var changed = false;
      var rewritten = html.replace(
        /<img\b([^>]*?)\bsrc=(["'])([^"']*funnotbun[^"']*)\2([^>]*)>/g,
        function(match, before, q, src, after) {
          if (!spriteCache[src]) return match;
          changed = true;
          // Drop any existing data-bg-removed in the before/after chunks
          // so we don't end up with duplicates, then re-add it cleanly.
          var clean = (before + after).replace(/\s*data-bg-removed=(["'])[^"']*\1/g, '');
          return '<img' + clean + ' src=' + q + spriteCache[src] + q + ' data-bg-removed="1">';
        },
      );
      if (changed) ev.detail.serverResponse = rewritten;
    } catch (_) { /* fall back to post-swap chroma-key */ }
  });

  // Initial paint.
  processAllSprites();

  // Attempts +/- adjustor; posts the new count then asks HTMX to refresh.
  window.adjAttempts = function(delta) {
    var bar = document.getElementById('attempts-bar');
    var cur = bar ? parseInt(bar.dataset.count, 10) : 0;
    var next = Math.max(0, cur + delta);
    fetch('/api/attempts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ count: next })
    })
      .then(function(r) { return r.json(); })
      .then(function(j) {
        if (j.ok && window.htmx) {
          window.htmx.trigger(document.body, 'sse:ping');
        }
      });
  };
})();


// ── Encounters table sort ───────────────────────────────────────────────────
(function() {
  var sortCol = -1, sortAsc = true;

  function naturalCmp(a, b) {
    return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
  }

  function getSortVal(td) {
    var v = td.getAttribute('data-sort');
    if (v !== null) return v;
    return td.textContent.trim();
  }

  function applySort() {
    var tbl = document.getElementById('enc-table');
    if (!tbl) return;
    var ths = tbl.querySelectorAll('thead th');
    ths.forEach(function(th, i) {
      th.classList.remove('sort-asc', 'sort-desc');
      if (i === sortCol) th.classList.add(sortAsc ? 'sort-asc' : 'sort-desc');
    });
    var tbody = tbl.querySelector('tbody');
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort(function(ra, rb) {
      var a = getSortVal(ra.children[sortCol]);
      var b = getSortVal(rb.children[sortCol]);
      var aNum = parseFloat(a), bNum = parseFloat(b);
      var cmp = (!isNaN(aNum) && !isNaN(bNum)) ? aNum - bNum : naturalCmp(a, b);
      return sortAsc ? cmp : -cmp;
    });
    rows.forEach(function(r) { tbody.appendChild(r); });
  }

  function bindHeaders() {
    var tbl = document.getElementById('enc-table');
    if (!tbl) return;
    tbl.querySelectorAll('thead th.sortable').forEach(function(th) {
      var ci = parseInt(th.getAttribute('data-col'), 10);
      th.onclick = function() {
        if (sortCol === ci) { sortAsc = !sortAsc; }
        else { sortCol = ci; sortAsc = true; }
        applySort();
      };
    });
    if (sortCol >= 0) applySort();
  }

  window._slinkEncSort = bindHeaders;
  bindHeaders();
  // Idiomorph reorders rows to match the server's default ordering on every
  // 2 s poll. refreshClientUI re-sorts on htmx:afterSettle, but settle fires
  // ~20 ms after swap — long enough for the browser to paint the unsorted
  // state, which reads as a flicker while a sort is active. Re-apply
  // synchronously in afterSwap (same task as the morph, before paint), same
  // pattern as the search filter above.
  document.body.addEventListener('htmx:afterSwap', function() {
    if (sortCol >= 0) applySort();
  });
})();


// ── Encounters table filter ─────────────────────────────────────────────────
(function() {
  var activeFilter = 'all';
  var FILTER_GROUPS = {
    'linked':    ['alive', 'linked'],
    'pending':   ['pending_a', 'pending_b', 'pending_both'],
    'pending_a': ['pending_a', 'pending_both'],
    'pending_b': ['pending_b', 'pending_both'],
    'dead':      ['dead', 'dead_zone', 'memorial']
  };

  function applyFilter() {
    var tbl = document.getElementById('enc-table');
    if (!tbl) return;
    var rows = tbl.querySelectorAll('tbody tr');
    rows.forEach(function(tr) {
      var st = tr.getAttribute('data-status') || '';
      if (activeFilter === 'all') {
        tr.style.display = '';
      } else {
        var group = FILTER_GROUPS[activeFilter] || [];
        tr.style.display = group.indexOf(st) >= 0 ? '' : 'none';
      }
    });
    var btns = document.querySelectorAll('#enc-filters .filter-btn');
    btns.forEach(function(b) {
      b.classList.toggle('active', b.getAttribute('data-filter') === activeFilter);
    });
  }

  function bindFilters() {
    var container = document.getElementById('enc-filters');
    if (!container) return;
    container.querySelectorAll('.filter-btn').forEach(function(btn) {
      btn.onclick = function() {
        activeFilter = btn.getAttribute('data-filter');
        applyFilter();
      };
    });
    applyFilter();
  }

  window._slinkEncFilter = bindFilters;
  bindFilters();
})();


// ── Global table-row search ──────────────────────────────────────────────
// Filters every <tr> in every table on the page based on a case-insensitive
// substring match against the row's text. Lives in .dash-search, which is
// outside the #content morph zone, so the input stays focused and the
// query survives every 2 s polling swap.
//
// Implementation notes:
//   * Pairs the input value to <tr.dash-search-hide> via a utility class so
//     the encounter-filter and other consumers can stack without inline
//     style fights.
//   * Re-runs after every htmx:afterSettle (refreshClientUI wires this up
//     via window._slinkSearch).
//   * `move-row` rows are tied to the row immediately above (the mon they
//     describe). When a mon row hides, its move row hides too; when a mon
//     row matches, its move row is forced visible regardless of whether
//     the move text itself matches the query.
(function() {
  var query = '';
  function applySearch() {
    var rows = document.querySelectorAll('table tr');
    // Pass 1: each row hides/shows based on its own text content.
    rows.forEach(function(tr) {
      // Skip header rows — they should never disappear.
      if (tr.parentElement && tr.parentElement.tagName === 'THEAD') {
        tr.classList.remove('dash-search-hide');
        return;
      }
      if (!query) { tr.classList.remove('dash-search-hide'); return; }
      var text = (tr.textContent || '').toLowerCase();
      tr.classList.toggle('dash-search-hide', text.indexOf(query) === -1);
    });
    // Pass 2: a `move-row` follows its parent mon row. Match its visibility
    // to the row directly above so the moves table doesn't orphan-show under
    // a filtered-out mon.
    if (query) {
      document.querySelectorAll('tr.move-row').forEach(function(mr) {
        var prev = mr.previousElementSibling;
        if (prev && !prev.classList.contains('dash-search-hide')) {
          mr.classList.remove('dash-search-hide');
        } else {
          mr.classList.add('dash-search-hide');
        }
      });
    }
  }
  function bindSearch() {
    var input = document.getElementById('dash-search-input');
    if (!input) return;
    var wrap = input.closest('.dash-search');
    var clearBtn = wrap && wrap.querySelector('.dash-search-clear');
    function setQuery(q) {
      query = (q || '').trim().toLowerCase();
      if (wrap) wrap.classList.toggle('has-query', !!query);
      applySearch();
    }
    // Avoid double-binding when htmx:afterSettle re-runs us; the input lives
    // outside #content so it's not replaced by the morph.
    if (!input.dataset.searchBound) {
      input.addEventListener('input', function() { setQuery(input.value); });
      if (clearBtn) {
        clearBtn.addEventListener('click', function() {
          input.value = '';
          setQuery('');
          input.focus();
        });
      }
      input.dataset.searchBound = '1';
    }
    // Re-apply against newly-morphed rows. Input value persists across
    // refreshes because the input is outside #content.
    setQuery(input.value);
  }
  window._slinkSearch = bindSearch;
  bindSearch();
  // Idiomorph strips `dash-search-hide` from rows on every 2 s poll to match
  // the fresh server HTML. refreshClientUI's `htmx:afterSettle` hook re-adds
  // it, but settle fires ~20 ms after swap — long enough for the browser to
  // paint the unfiltered state, which reads as a flicker while a query is
  // active. Re-apply synchronously in `afterSwap` (same task as the morph,
  // before paint) so the final-state DOM is the only thing the user sees.
  document.body.addEventListener('htmx:afterSwap', function() {
    if (query) applySearch();
  });
})();


// ── Theme bootstrap for non-templated pages ───────────────────────────────
// The Jinja-rendered pages (status via dashboard.html, manager, memorial)
// already set `<body class="theme-X">` server-side via resolve_theme. The
// raw-string pages (_DEBUG_HTML, _TWITCH_PAGE_HTML, _OBS_PAGE_HTML) don't,
// so this block reads ?theme= → localStorage → default and applies the
// matching body class + <link rel="stylesheet"> on first paint. Skipped if
// the body already carries a theme class (don't fight the server).
(function() {
  var body = document.body;
  if (!body) return;
  var existing = (body.className || '').split(/\s+/).find(function(c) {
    return c.indexOf('theme-') === 0;
  });
  if (existing) return;  // server already themed this page
  var theme = 'default';
  try {
    theme = (new URLSearchParams(location.search)).get('theme')
            || localStorage.getItem('slink-theme')
            || 'default';
  } catch (_) {}
  body.className = (body.className || '').trim() + ' theme-' + theme;
  if (!document.getElementById('slink-theme')) {
    var link = document.createElement('link');
    link.rel  = 'stylesheet';
    link.id   = 'slink-theme';
    link.href = '/static/themes/' + theme + '.css';
    document.head.appendChild(link);
  }
})();


// ── Theme switcher (vanilla, page-agnostic) ───────────────────────────────
// One source of truth for the theme picker UI. Two cases:
//
//   1. Jinja pages (status via dashboard.html, manager, memorial) render the
//      Alpine-driven _theme_switcher.html partial — this script just moves
//      that existing `.theme-switcher` element into the sidebar slot.
//
//   2. Non-Jinja pages (debug / twitch / OBS, served as raw HTML strings)
//      have no `.theme-switcher` element. This script then BUILDS one from
//      scratch and drops it into the sidebar slot. The DOM matches the
//      Alpine version close enough that the same in-sidebar CSS styles it.
//
// Either way the active theme persists via localStorage["slink-theme"] and
// syncs across tabs via the `storage` event (set by the bootstrap above).
(function() {
  var THEMES = [
    { slug: 'default',              label: 'Default',     swatch: '#070910' },
    { slug: 'light',                label: 'Light',       swatch: '#eef2fc' },
    { slug: 'funtastic-grape',      label: 'Grape',       swatch: '#9933cc' },
    { slug: 'funtastic-jungle',     label: 'Jungle',      swatch: '#00cc66' },
    { slug: 'funtastic-fire',       label: 'Fire',        swatch: '#ff6600' },
    { slug: 'funtastic-ice',        label: 'Ice',         swatch: '#66ccff' },
    { slug: 'funtastic-watermelon', label: 'Watermelon',  swatch: '#ff3366' },
    { slug: 'funtastic-smoke',      label: 'Smoke',       swatch: '#333333' },
  ];

  function currentTheme() {
    var b = document.body || {};
    var cls = (b.className || '').split(/\s+/).find(function(c) { return c.indexOf('theme-') === 0; });
    if (cls) return cls.replace(/^theme-/, '');
    try { return localStorage.getItem('slink-theme') || 'default'; } catch (_) { return 'default'; }
  }

  function applyTheme(name) {
    var b = document.body;
    var wantClass = 'theme-' + name;
    if (!b.classList.contains(wantClass)) {
      b.className = (b.className || '').split(/\s+/).filter(function(c) {
        return c && c.indexOf('theme-') !== 0;
      }).concat(wantClass).join(' ').trim();
    }
    var link = document.getElementById('slink-theme');
    var wantHref = '/static/themes/' + name + '.css';
    if (link && link.getAttribute('href') !== wantHref) {
      link.href = wantHref;
    }
    try { localStorage.setItem('slink-theme', name); } catch (_) {}
    // Mirror to a cookie so server-rendered pages (calc) can resolve the
    // active theme on first paint instead of flashing default and snapping
    // via a client-side override. 1-year expiry, path=/, SameSite=Lax.
    try {
      document.cookie = 'slink-theme=' + encodeURIComponent(name)
        + '; max-age=31536000; path=/; samesite=lax';
    } catch (_) {}
    // Refresh our own widget's swatch + label so it shows the right state.
    var sw = document.querySelector('.theme-switcher--vanilla');
    if (sw) refreshVanillaWidget(sw);
  }

  function refreshVanillaWidget(root) {
    var active = currentTheme();
    var swatch = root.querySelector('.theme-swatch');
    var nameEl = root.querySelector('.theme-name');
    var def = THEMES.find(function(t) { return t.slug === active; }) || THEMES[0];
    if (swatch) swatch.style.background = def.swatch;
    if (nameEl) nameEl.textContent = def.label;
    Array.prototype.forEach.call(root.querySelectorAll('.theme-pill'), function(btn) {
      btn.classList.toggle('active', btn.getAttribute('data-theme') === active);
    });
  }

  function buildVanillaWidget() {
    var d = document.createElement('div');
    d.className = 'theme-switcher theme-switcher--vanilla';
    var html = ''
      + '<details>'
      + '<summary>'
      +   '<span class="theme-swatch"></span>'
      +   '<span class="theme-name"></span>'
      +   '<span class="theme-caret">▾</span>'
      + '</summary>'
      + '<div class="theme-pills" role="radiogroup" aria-label="Theme">';
    THEMES.forEach(function(t) {
      html += '<button type="button" class="theme-pill" data-theme="' + t.slug + '" title="' + t.label + '">'
            +   '<span class="theme-swatch" style="background:' + t.swatch + '"></span>'
            +   '<span class="theme-label">' + t.label + '</span>'
            + '</button>';
    });
    html += '</div></details>';
    d.innerHTML = html;
    Array.prototype.forEach.call(d.querySelectorAll('.theme-pill'), function(btn) {
      btn.addEventListener('click', function() {
        applyTheme(btn.getAttribute('data-theme'));
        var details = d.querySelector('details');
        if (details) details.open = false;
      });
    });
    refreshVanillaWidget(d);
    return d;
  }

  function relocate() {
    var slot = document.querySelector('.dash-sidebar-theme, .mgr-rail-theme');
    if (!slot) return;
    var switcher = document.querySelector('.theme-switcher');
    if (!switcher) {
      // No Alpine widget on this page — build the vanilla version.
      switcher = buildVanillaWidget();
      slot.appendChild(switcher);
    } else if (switcher.parentElement !== slot) {
      slot.appendChild(switcher);
    }
    switcher.classList.add('theme-switcher--in-sidebar');
  }
  relocate();
  document.body.addEventListener('htmx:afterSettle', relocate);
  // Cross-tab sync — keep the vanilla widget's selection in sync with
  // whatever the localStorage value says (changed by another tab).
  window.addEventListener('storage', function(ev) {
    if (ev.key === 'slink-theme' && ev.newValue) applyTheme(ev.newValue);
  });
})();


// ── Font picker (Pixelify ↔ Classic) ──────────────────────────────────────
// Mirrors the theme switcher in structure and styling, but flips a single
// CSS variable (`--font-ui` in slink.css) via a body class rather than
// swapping a <link>. Two options:
//   * pixelify (default) — the new Pixelify Sans / Press Start 2P chain
//   * classic            — the pre-rework system-ui / Segoe UI chain
//
// Lives ABOVE the theme picker in the sidebar (.dash-sidebar-font slot).
// State persists in localStorage["slink-font"] and syncs across tabs via
// the `storage` event, matching the theme picker's behaviour.
//
// The calc page applies the saved font synchronously in its <head> (see
// calc/src/normal.template.html) so a hard refresh on calc paints with
// the right body font on first frame, no FOUC.
(function() {
  var FONTS = [
    { slug: 'pixelify', label: 'Pixelify',   sample: 'Aa' },
    { slug: 'classic',  label: 'Classic',    sample: 'Aa' },
  ];

  function currentFont() {
    var b = document.body || {};
    var cls = (b.className || '').split(/\s+/).find(function(c) { return c.indexOf('font-') === 0; });
    if (cls) return cls.replace(/^font-/, '');
    try { return localStorage.getItem('slink-font') || 'pixelify'; } catch (_) { return 'pixelify'; }
  }

  function applyFont(name) {
    if (name !== 'classic') name = 'pixelify';
    var b = document.body;
    var wantClass = 'font-' + name;
    if (!b.classList.contains(wantClass)) {
      // Strip any previous `font-*` class so we don't accumulate.
      b.className = (b.className || '').split(/\s+/).filter(function(c) {
        return c && c.indexOf('font-') !== 0;
      }).concat(wantClass).join(' ').trim();
    }
    try { localStorage.setItem('slink-font', name); } catch (_) {}
    var sw = document.querySelector('.font-switcher');
    if (sw) refreshFontWidget(sw);
  }

  function refreshFontWidget(root) {
    var active = currentFont();
    var nameEl = root.querySelector('.font-name');
    var def = FONTS.find(function(f) { return f.slug === active; }) || FONTS[0];
    if (nameEl) nameEl.textContent = def.label;
    // The summary's sample previews the ACTIVE font (matches theme picker
    // pattern where the summary swatch shows the active palette colour).
    var summarySample = root.querySelector('summary .font-sample');
    if (summarySample) {
      summarySample.style.fontFamily = active === 'classic'
        ? 'ui-monospace, \'SFMono-Regular\', Menlo, Consolas, monospace'
        : '\'Pixelify Sans\', \'Press Start 2P\', monospace';
    }
    Array.prototype.forEach.call(root.querySelectorAll('.font-pill'), function(btn) {
      btn.classList.toggle('active', btn.getAttribute('data-font') === active);
    });
  }

  function buildFontWidget() {
    var d = document.createElement('div');
    d.className = 'font-switcher font-switcher--in-sidebar';
    var html = ''
      + '<details>'
      + '<summary>'
      +   '<span class="font-sample">Aa</span>'
      +   '<span class="font-name"></span>'
      +   '<span class="font-caret">▾</span>'
      + '</summary>'
      + '<div class="font-pills" role="radiogroup" aria-label="Font">';
    FONTS.forEach(function(f) {
      // The pill's sample is rendered in its target font so the user can
      // preview "Pixelify Sans" vs the pre-rework monospace face without
      // applying the choice. Strings match the slink.css --font-mono /
      // --font-heading tokens so the preview tracks the actual swap.
      var sampleFont = f.slug === 'classic'
        ? 'ui-monospace, \'SFMono-Regular\', Menlo, Consolas, monospace'
        : '\'Pixelify Sans\', \'Press Start 2P\', monospace';
      html += '<button type="button" class="font-pill" data-font="' + f.slug + '" title="' + f.label + '">'
            +   '<span class="font-sample" style="font-family:' + sampleFont + '">Aa</span>'
            +   '<span class="font-label">' + f.label + '</span>'
            + '</button>';
    });
    html += '</div></details>';
    d.innerHTML = html;
    Array.prototype.forEach.call(d.querySelectorAll('.font-pill'), function(btn) {
      btn.addEventListener('click', function() {
        applyFont(btn.getAttribute('data-font'));
        var details = d.querySelector('details');
        if (details) details.open = false;
      });
    });
    refreshFontWidget(d);
    return d;
  }

  function relocate() {
    // The calc page (body.dark-theme) intentionally skips the font picker:
    // its Bootstrap body is locked to `font-family: monospace !important` so
    // a font swap wouldn't change anything visible, and the picker would
    // just be dead chrome. Skip building/relocating there.
    if (document.body.classList.contains('dark-theme')) return;
    var slot = document.querySelector('.dash-sidebar-font, .mgr-rail-font');
    if (!slot) return;
    var widget = document.querySelector('.font-switcher');
    if (!widget) {
      widget = buildFontWidget();
      slot.appendChild(widget);
    } else if (widget.parentElement !== slot) {
      slot.appendChild(widget);
    }
  }

  // Apply persisted font on first paint so the picker's label matches
  // the body class, and so non-templated pages (debug/twitch/OBS/calc
  // sidebar context) get the right font without a flash. We still mark
  // the body class on calc so the slink.css --font-ui token resolves
  // correctly for the sidebar (which DOES flip even on calc).
  try {
    var saved = localStorage.getItem('slink-font');
    if (saved === 'classic' || saved === 'pixelify') {
      if (!document.body.classList.contains('font-' + saved)) {
        applyFont(saved);
      }
    } else if (!document.body.className.split(/\s+/).some(function(c) { return c.indexOf('font-') === 0; })) {
      // Default = pixelify; mark the body so the picker label has a value.
      document.body.classList.add('font-pixelify');
    }
  } catch (_) {}

  relocate();
  document.body.addEventListener('htmx:afterSettle', relocate);
  window.addEventListener('storage', function(ev) {
    if (ev.key === 'slink-font' && ev.newValue) applyFont(ev.newValue);
  });
})();


// ── Sidebar collapse toggle ────────────────────────────────────────────────
// Persists between SSE swaps + page navigations. The body class is the
// source of truth; toggleSidebar flips it and writes localStorage. On load
// we read localStorage and re-apply so the choice survives hard refresh.
(function() {
  var KEY = 'slink-sidebar-collapsed';
  function apply(collapsed) {
    document.body.classList.toggle('dash-collapsed', collapsed);
  }
  function read() {
    try { return window.localStorage.getItem(KEY) === '1'; }
    catch (_) { return false; }
  }
  function write(v) {
    try { window.localStorage.setItem(KEY, v ? '1' : '0'); }
    catch (_) {}
  }
  function toggle() {
    var next = !document.body.classList.contains('dash-collapsed');
    apply(next);
    write(next);
  }
  // The logo doubles as the expand-toggle when the sidebar is collapsed
  // (the hamburger button is hidden in that state so the logo can centre).
  document.addEventListener('click', function(ev) {
    var logo = ev.target.closest && ev.target.closest('.dash-sidebar .slink-logo');
    if (logo && document.body.classList.contains('dash-collapsed')) {
      ev.preventDefault();
      toggle();
    }
  });
  // Re-apply after each HTMX morph in case the body class got reset.
  document.body.addEventListener('htmx:afterSettle', function() {
    apply(read());
  });
  // Sync across tabs.
  window.addEventListener('storage', function(ev) {
    if (ev.key === KEY) apply(ev.newValue === '1');
  });
  apply(read());
  window.SLinkDash = Object.assign(window.SLinkDash || {}, {
    toggleSidebar: toggle,
  });
})();


// ── Linked-party combined view toggle ────────────────────────────────────
// Same body-class pattern as the sidebar — immune to HTMX morph resets.
(function() {
  var KEY = 'slink-lp-view';
  function apply(on) {
    document.body.classList.toggle('lp-view', on);
  }
  function read() {
    try { return window.localStorage.getItem(KEY) === '1'; }
    catch (_) { return false; }
  }
  function write(v) {
    try { window.localStorage.setItem(KEY, v ? '1' : '0'); }
    catch (_) {}
  }
  function toggle() {
    var next = !document.body.classList.contains('lp-view');
    apply(next);
    write(next);
  }
  function setView(on) {
    var v = !!on;
    apply(v);
    write(v);
  }
  document.body.addEventListener('htmx:afterSettle', function() { apply(read()); });
  window.addEventListener('storage', function(ev) {
    if (ev.key === KEY) apply(ev.newValue === '1');
  });
  apply(read());
  window.SLinkDash = Object.assign(window.SLinkDash || {}, {
    toggleLpView: toggle,
    setLpView: setView,
  });
})();


// ── <details> open-state persistence across morph swaps ──────────────────
// idiomorph syncs ALL attributes between the new server HTML and the
// existing DOM. When the server response doesn't carry `open` (the server
// has no idea what the user has expanded), idiomorph dutifully removes it,
// collapsing every <details> on each 2 s polling swap.
//
// Fix: each <details data-details-key="…"> participates in opt-in
// persistence. The toggle event saves `open` to localStorage; htmx:afterSettle
// re-applies the saved state. Keys are namespaced (`moves:KEY`, `enc:AREA`)
// to avoid collisions across element kinds.
(function() {
  var STORAGE_PREFIX = 'slink-details-open:';
  function keyFor(el) {
    var k = el.getAttribute('data-details-key');
    return k ? STORAGE_PREFIX + k : null;
  }
  // ── Cross-morph preservation via idiomorph callback ────────────────────
  // The polling response carries no `open` attribute (the server has no
  // idea what the user has expanded). By default idiomorph dutifully syncs
  // the new HTML's attribute set onto the existing DOM, stripping `open`
  // and collapsing the widget on every 2 s tick. Hooking into idiomorph's
  // `beforeAttributeUpdated` callback (returning false to veto the update)
  // is the cleanest fix — it tells the diffing engine "leave this attribute
  // alone on these elements" without race-prone restore-after-the-fact
  // dance. Vetoes specifically the `open` attribute on the data-details-key
  // elements; every other attribute on every other element still syncs.
  function installIdiomorphHook() {
    if (!window.Idiomorph || !Idiomorph.defaults || !Idiomorph.defaults.callbacks) return;
    Idiomorph.defaults.callbacks.beforeAttributeUpdated = function(attrName, node, mutationType) {
      if (attrName === 'open' && node && node.hasAttribute && node.hasAttribute('data-details-key')) {
        return false;
      }
    };
  }
  // The htmx-ext-morph extension loads `idiomorph-ext.min.js` which exposes
  // `Idiomorph` as a global. dashboard.html now loads idiomorph BEFORE
  // dashboard.js, but be defensive in case the order ever drifts: defer
  // scripts run with document.readyState === "interactive" (before
  // DOMContentLoaded fires), so registering on DOMContentLoaded reliably
  // runs us after every other defer script has executed. The `load`
  // listener is a final safety net if anything is still pending. The
  // install function is idempotent — it just reassigns a property — so
  // firing twice is harmless.
  if (window.Idiomorph) {
    installIdiomorphHook();
  } else {
    document.addEventListener('DOMContentLoaded', installIdiomorphHook);
    window.addEventListener('load', installIdiomorphHook);
  }

  // ── Cross-session persistence via localStorage ─────────────────────────
  // The idiomorph callback handles cross-morph; this handles page reload.
  // Listen for clicks on summaries (user intent — synthetic toggle events
  // from idiomorph would also fire here, but the callback above means they
  // never happen for our keyed details). The click runs BEFORE the browser
  // flips the open attribute, so persist the inverse of the current state.
  document.body.addEventListener('click', function(ev) {
    var summary = ev.target && ev.target.closest && ev.target.closest('summary');
    if (!summary) return;
    var details = summary.parentElement;
    if (!details || details.tagName !== 'DETAILS') return;
    var k = keyFor(details);
    if (!k) return;
    var willOpen = !details.open;
    try {
      if (willOpen) window.localStorage.setItem(k, '1');
      else          window.localStorage.removeItem(k);
    } catch (_) {}
  });
  // Restore from localStorage on initial paint AND on every settle (so
  // newly-injected details elements pick up their saved state). This only
  // OPENS widgets — never closes them. Closing is the user's job via the
  // summary click. This guards against an empty/raced localStorage value
  // accidentally collapsing a widget the morph-veto has been keeping open.
  function restoreAll() {
    var nodes = document.querySelectorAll('details[data-details-key]');
    Array.prototype.forEach.call(nodes, function(el) {
      var k = keyFor(el);
      if (!k) return;
      var saved = null;
      try { saved = window.localStorage.getItem(k); } catch (_) {}
      if (saved === '1' && !el.open) el.open = true;
      // If saved is null but el.open is already true (e.g., user opened it
      // earlier this session, idiomorph veto kept it open), repaint the
      // saved state so a hard reload from a different tab honours it too.
      if (saved !== '1' && el.open) {
        try { window.localStorage.setItem(k, '1'); } catch (_) {}
      }
    });
  }
  document.body.addEventListener('htmx:afterSettle', restoreAll);
  if (document.readyState !== 'loading') restoreAll();
  else document.addEventListener('DOMContentLoaded', restoreAll);
})();

}  // close `if (window._slinkDashInit)` sentinel
