/* Shared sprite chroma-key and badge alpha cleanup for board and OBS pages. */
(function () {
  'use strict';
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

  function processSprites() {
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
        loader.onerror = function () { URL.revokeObjectURL(burl); };
        loader.onload = function () {
          try {
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
          } catch (_) { /* keep original when pixels cannot be read */ }
          finally { URL.revokeObjectURL(burl); }
        };
        loader.src = burl;
      })
      .catch(function () { /* network unavailable — leave the original */ });
  }

  function processBadges() {
    document.querySelectorAll('img.bdg-img').forEach(trimBadge);
  }

  function process() { processSprites(); processBadges(); }
  window.SLinkImages = Object.freeze({processSprites: processSprites, processBadges: processBadges,
    cachedSprite: function (src) { return spriteCache[src]; }});
  document.addEventListener('DOMContentLoaded', process);
  document.addEventListener('htmx:afterSettle', process);
})();
