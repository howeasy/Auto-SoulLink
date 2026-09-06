/* Explicit run-scoped calls; ordinary manager requests continue to use fetch. */
(function () {
  'use strict';
  var match = window.location.pathname.match(/^\/runs\/([A-Za-z0-9][A-Za-z0-9_-]{0,127})(?:\/|$)/);
  var base = match ? '/runs/' + match[1] : '';
  function url(path) {
    if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//')) throw new Error('A run-relative path is required');
    return base + path;
  }
  window.SLinkRun = Object.freeze({base: base, url: url, fetch: function (path, options) { return fetch(url(path), options); }});
})();
