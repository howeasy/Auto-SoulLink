/* overlay-helpers.js — post-swap utilities for templated stream overlays.
 *
 * The templated overlays at /stream/* use HTMX `hx-trigger="every 2s"`
 * to morph in fresh #root content from the server. Three pieces of
 * post-swap behaviour run here:
 *
 *   1. processSprites — funnotbun custom sprites ship with a solid
 *      background pixel; canvas chroma-key it to transparent and cache the
 *      resulting data URL so subsequent renders don't re-process.
 *   2. processBadges — PokeAPI badge PNGs have anti-aliased fringe against
 *      a light bg; snap semi-transparent pixels to fully transparent so
 *      badges look clean on any theme.
 *   3. autoFit — if #root content overflows its container, transform-scale
 *      to fit. Critical for the broadcaster who picks weird OBS dimensions.
 *
 * All three run on `htmx:afterSettle` (after the morph completes) and on
 * `DOMContentLoaded` (so the initial server-rendered HTML gets the same
 * treatment). Idiomorph preserves <img> identity across morphs, so once
 * a sprite is chroma-keyed it stays keyed.
 *
 * NOT loaded by the dashboard — the dashboard has its own copy of the
 * sprite background-removal pipeline inline at server.py:610–665.
 */

(function () {
  'use strict';

  // ── Sprite chroma-key (funnotbun-style solid-bg PNGs) ─────────────────
  var spriteCache = {};

  function removeSpriteBackground(img) {
    if (img.dataset.bgRemoved || !img.naturalWidth) return;
    var src = img.src;
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
      // CORS / SecurityError — leave original sprite alone.
    }
    img.dataset.bgRemoved = '1';
  }

  function processSprites() {
    document.querySelectorAll('img.mon-sprite, img.enc-sprite').forEach(function (img) {
      if (img.dataset.bgRemoved) return;
      var cached = img.getAttribute('src');
      if (cached && spriteCache[cached]) {
        img.src = spriteCache[cached];
        img.dataset.bgRemoved = '1';
        return;
      }
      if (img.complete && img.naturalWidth) {
        removeSpriteBackground(img);
      } else {
        img.crossOrigin = 'anonymous';
        // Re-fit + re-measure marquees once a sprite finishes loading —
        // the encounter-table marquee in particular needs its scrollHeight
        // recomputed after the funnotbun sprites land, otherwise the
        // initial-paint measure happens against an empty grid and the
        // overflow check fails.
        img.addEventListener('load', function () {
          removeSpriteBackground(img);
          autoFit();
          applyMarquees();
        }, { once: true });
      }
    });
  }

  // ── Badge alpha-fringe trimming ──────────────────────────────────────
  // PokeAPI badge sprites (PNG, anti-aliased against a light bg) carry
  // semi-transparent edge pixels that read as grey haloes against dark
  // overlays. Snap any alpha < 200 to 0 so the silhouette is crisp.
  var badgeCache = {};

  function trimBadge(img) {
    if (img.dataset.trimmed) return;
    img.dataset.trimmed = '1';
    var src = img.getAttribute('src');
    if (!src || src.indexOf('data:') === 0) return;
    if (badgeCache[src]) { img.src = badgeCache[src]; return; }
    // fetch() forces a fresh CORS response even when the browser cache
    // holds a non-CORS entry — otherwise canvas.getImageData() throws
    // SecurityError on the cached image.
    fetch(src, { mode: 'cors', credentials: 'omit' })
      .then(function (r) { return r.blob(); })
      .then(function (blob) {
        var burl = URL.createObjectURL(blob);
        var loader = new Image();
        loader.onload = function () {
          var w = loader.naturalWidth, h = loader.naturalHeight;
          var c = document.createElement('canvas');
          c.width = w; c.height = h;
          var ctx = c.getContext('2d');
          ctx.drawImage(loader, 0, 0);
          var data = ctx.getImageData(0, 0, w, h);
          var px = data.data;
          for (var j = 3; j < px.length; j += 4) {
            px[j] = px[j] < 200 ? 0 : 255;
          }
          ctx.putImageData(data, 0, 0);
          var dataUrl = c.toDataURL();
          badgeCache[src] = dataUrl;
          img.src = dataUrl;
          URL.revokeObjectURL(burl);
        };
        loader.src = burl;
      })
      .catch(function () { /* network unavailable — leave the original */ });
  }

  function processBadges() {
    document.querySelectorAll('img.bdg-img').forEach(trimBadge);
  }

  // ── autoFit — scale #root down if its content overflows ─────────────
  //
  // CSS transforms don't affect layout (scrollHeight / clientHeight are
  // unchanged by a scale), so we measure WITHOUT first clearing the
  // existing transform. The naive "reset → measure → re-apply" sequence
  // forces a recomposite of the root layer on every poll even when the
  // desired scale is identical to the current one — that recomposite is
  // exactly the focus-card flicker visible in the All Overlays grid.
  //
  // We only mutate the inline style when the new scale would differ from
  // the current one by more than half a percent. Below that threshold the
  // visual difference is imperceptible and any churn just costs us a frame.
  function autoFit() {
    var root = document.getElementById('root');
    if (!root) return;
    var sh = root.scrollHeight;
    var ch = root.clientHeight;
    var desired = (sh > ch && ch > 0) ? (ch / sh) : 1;
    var match = (root.style.transform || '').match(/scale\(([\d.]+)\)/);
    var current = match ? parseFloat(match[1]) || 1 : 1;
    if (Math.abs(desired - current) < 0.005) return;
    if (desired < 1) {
      root.style.transformOrigin = 'top center';
      root.style.transform = 'scale(' + desired + ')';
    } else {
      root.style.transform = '';
      root.style.transformOrigin = '';
    }
  }

  // ── Marquee — apply CSS animation to elements that opt in via
  // data-marquee="<keyframe-name>" and only when their content actually
  // overflows the parent twice (the marker the templates use to mean "the
  // doubled list is wider/taller than the mask, so a seamless loop is
  // visually justified"). Runs on every paint so HTMX morph swaps (which
  // do not re-execute inline <script> tags) re-evaluate after sprites land.
  function applyMarquees() {
    var speed = parseFloat(new URLSearchParams(window.location.search).get('speed') || '1') || 1;
    speed = Math.min(3, Math.max(0.25, speed));
    document.querySelectorAll('[data-marquee]').forEach(function (el) {
      var kf = el.getAttribute('data-marquee');
      var base = parseFloat(el.getAttribute('data-marquee-base') || '0');
      if (!kf || !base) return;
      var parent = el.parentElement;
      if (!parent) return;
      // The templates double their content so the marquee can loop; require
      // the rendered content to exceed twice the visible mask before
      // animating, otherwise we'd just oscillate a small ribbon visibly.
      var measure = el.scrollHeight || el.scrollWidth;
      var bound = parent.clientHeight || parent.clientWidth;
      // Track what we last applied via a data attribute. Reading `el.style.
      // animation` back returns the browser-normalized longhand form (e.g.
      // "30s linear 0s infinite normal none running enc-scroll") which
      // never string-equals what we set ("enc-scroll 30s linear infinite"),
      // so comparing against the read-back value would re-assign every
      // call and restart the CSS animation from frame 0 — visible as a
      // scroll reset every 2 s.
      var want = (measure > bound * 2) ? (kf + ' ' + (base / speed) + 's linear infinite') : '';
      if (el.getAttribute('data-marquee-applied') === want) return;
      el.style.animation = want;
      if (want) el.setAttribute('data-marquee-applied', want);
      else el.removeAttribute('data-marquee-applied');
    });
  }

  function runAll() {
    processSprites();
    processBadges();
    autoFit();
    applyMarquees();
  }

  // ── Idiomorph beforeAttributeUpdated hook — protect JS-set marquee styles
  //
  // The polling fragment carries no inline `style` attribute on the marquee
  // host elements (the server-side template only stamps the `data-marquee`
  // metadata; the running animation is set by JS on the client). Without
  // intervention, idiomorph dutifully syncs the incoming "no style" onto the
  // existing element and strips the `animation` property — that's the
  // 2-second scroll reset on the encounters / memorial / ticker / enemy
  // trainer overlays.
  //
  // Veto `style` updates on any element either tagged `data-marquee` (the
  // new declarative path used by enc-table) or with one of the known
  // marquee IDs whose inline templates still set the animation directly.
  // Same pattern dashboard.js:701 uses to preserve <details open> across
  // morph swaps. Adding `data-marquee` to additional templates extends this
  // protection without further code changes here.
  var MARQUEE_IDS = { ttrack: 1, 'mem-list': 1, 'trn-list': 1, 'et-list': 1 };
  function installIdiomorphHook() {
    if (!window.Idiomorph || !Idiomorph.defaults || !Idiomorph.defaults.callbacks) return;
    Idiomorph.defaults.callbacks.beforeAttributeUpdated = function (attrName, node, mutationType) {
      if (attrName !== 'style' || !node || !node.hasAttribute) return;
      if (node.hasAttribute('data-marquee')) return false;
      if (node.id && MARQUEE_IDS[node.id]) return false;
    };
  }

  // Initial render — server-rendered HTML lands before HTMX hooks anything.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      installIdiomorphHook();
      runAll();
    });
  } else {
    installIdiomorphHook();
    runAll();
  }

  // Subsequent renders — HTMX morphs new content into #root every 2 s.
  // afterSettle fires once the swap is complete (sprites may not yet have
  // load events fired, but the listeners we attach inside processSprites
  // handle that case).
  document.body.addEventListener('htmx:afterSettle', runAll);
  // Window resize — refit existing content, no re-fetch needed.
  window.addEventListener('resize', autoFit);

  // ── Pre-swap funnotbun src rewrite — prevents the 2-second sprite flash
  // (parallel to the dashboard.js:104 handler).
  //
  // The polling fragment carries every <img>'s ORIGINAL funnotbun URL
  // (green/blue background). Idiomorph dutifully syncs the incoming `src`
  // back onto the existing DOM, even though processSprites already replaced
  // it with a transparent data URL. The CSS `visibility:hidden` rule then
  // hides the funnotbun src for a frame until the load+chroma-key cycle
  // completes — that's the flicker every 2 s.
  //
  // Rewrite each funnotbun src in the incoming HTML to the cached
  // transparent data URL we computed on initial paint, and tag the element
  // `data-bg-removed="1"`. By the time idiomorph applies the morph the
  // src already matches the post-processed value, so morph sees nothing to
  // change and the browser never re-fetches. HTMX exposes the modifiable
  // response body on `event.detail.serverResponse`.
  document.body.addEventListener('htmx:beforeSwap', function (ev) {
    try {
      var html = ev.detail && ev.detail.serverResponse;
      if (!html || html.indexOf('funnotbun') === -1) return;
      var changed = false;
      var rewritten = html.replace(
        /<img\b([^>]*?)\bsrc=(["'])([^"']*funnotbun[^"']*)\2([^>]*)>/g,
        function (match, before, q, src, after) {
          if (!spriteCache[src]) return match;
          changed = true;
          var clean = (before + after).replace(/\s*data-bg-removed=(["'])[^"']*\1/g, '');
          return '<img' + clean + ' src=' + q + spriteCache[src] + q + ' data-bg-removed="1">';
        }
      );
      if (changed) ev.detail.serverResponse = rewritten;
    } catch (_) { /* fall through to post-swap chroma-key */ }
  });

  // Expose for debugging / future stream pages that want to call helpers
  // directly (e.g., one-shot sprite re-processing after a manual mutation).
  window.SLinkOverlay = { processSprites: processSprites, processBadges: processBadges, autoFit: autoFit };
})();
