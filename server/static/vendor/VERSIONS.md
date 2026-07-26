# Vendored JavaScript libraries

These files are bundled locally — **not loaded from a CDN** — because OBS
browser sources cache CDN assets aggressively and unpredictably. A version
bump here is the only way the runtime sees a new version.

Source: https://unpkg.com/{name}@{version}/dist/{file}

| File | Library | Version | Purpose |
|---|---|---|---|
| `htmx.min.js` | [htmx.org](https://htmx.org/) | 2.0.3 | HTML-over-the-wire core |
| `idiomorph-ext.min.js` | [idiomorph](https://github.com/bigskysoftware/idiomorph) | 0.7.3 | HTMX swap strategy that morphs DOM by `id`, preserving sprites |
| `alpine.min.js` | [Alpine.js](https://alpinejs.dev/) | 3.14.1 | Reactive sprinkles (mouse-pause, theme switcher, sort persistence) |
| `overlay-helpers.js` | First-party | — | Post-swap utilities for templated stream overlays: sprite chroma-key, badge alpha-fringe trim, `#root` autoFit |

To update: refetch from unpkg with the new version pinned, then bump the version cells above.
