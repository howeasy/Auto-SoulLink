/* overlay-helpers.js — post-swap utilities for templated stream overlays.
 *
 * The templated overlays at /stream/* use HTMX `hx-trigger="every 2s"`
 * to morph in fresh #root content from the server. Three pieces of
 * post-swap behaviour run here:
 *
 *   1. refitOnSpriteLoad — re-run autoFit and the marquees once a sprite
 *      that was still loading at paint time lands.
 *   2. processBadges — PokeAPI badge PNGs have anti-aliased fringe against
 *      a light bg; snap semi-transparent pixels to fully transparent so
 *      badges look clean on any theme.
 *   3. autoFit — if #root content overflows its container, transform-scale
 *      to fit. Critical for the broadcaster who picks weird OBS dimensions.
 *
 * All three run on `htmx:afterSettle` (after the morph completes) and on
 * `DOMContentLoaded` (so the initial server-rendered HTML gets the same
 * treatment).
 */

(function () {
  'use strict';

  // ── Sprite load → refit ─────────────────────────────────────────────
  // Re-fit + re-measure marquees once a sprite finishes loading — the
  // encounter-table marquee in particular needs its scrollHeight recomputed
  // after the sprites land, otherwise the initial-paint measure happens
  // against an empty grid and the overflow check fails.
  function refitOnSpriteLoad() {
    document.querySelectorAll('img.mon-sprite, img.enc-sprite').forEach(function (img) {
      if (img.complete && img.naturalWidth) return;
      img.addEventListener('load', function () {
        autoFit();
        applyMarquees();
      }, { once: true });
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
    refitOnSpriteLoad();
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
  var MARQUEE_IDS = { ttrack: 1, 'mem-list': 1, 'trn-list': 1, 'et-list': 1, 'bl-list': 1 };
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
  // load events fired, but the listeners we attach inside refitOnSpriteLoad
  // handle that case).
  document.body.addEventListener('htmx:afterSettle', runAll);
  // Window resize — refit existing content, no re-fetch needed.
  window.addEventListener('resize', autoFit);

  // Expose for debugging / future stream pages that want to call helpers
  // directly.
  window.SLinkOverlay = { processBadges: processBadges, autoFit: autoFit };
})();
