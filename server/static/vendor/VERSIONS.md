# Vendored JavaScript libraries

These files are bundled locally — **not loaded from a CDN** — because OBS
browser sources cache CDN assets aggressively and unpredictably. A version
bump here is the only way the runtime sees a new version.

Source: https://unpkg.com/{name}@{version}/dist/{file}

| File | Library | Version | Purpose |
|---|---|---|---|
| `htmx.min.js` | [htmx.org](https://htmx.org/) | 2.0.3 | HTML-over-the-wire core |
| `htmx-ext-sse.min.js` | [htmx-ext-sse](https://htmx.org/extensions/server-sent-events/) | 2.2.2 | Server-Sent Events extension for HTMX |
| `idiomorph-ext.min.js` | [idiomorph](https://github.com/bigskysoftware/idiomorph) | 0.7.3 | HTMX swap strategy that morphs DOM by `id`, preserving sprites |
| `alpine.min.js` | [Alpine.js](https://alpinejs.dev/) | 3.14.1 | Reactive sprinkles (mouse-pause, theme switcher, sort persistence) |
| `alpine-persist.min.js` | [@alpinejs/persist](https://alpinejs.dev/plugins/persist) | 3.14.1 | `$persist()` magic — backs Alpine state with `localStorage` |
| `overlay-helpers.js` | First-party | — | Post-swap utilities for templated stream overlays: sprite chroma-key, badge alpha-fringe trim, `#root` autoFit |

To update: refetch from unpkg with the new version pinned, then bump the version cells above.
