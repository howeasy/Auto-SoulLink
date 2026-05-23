"""server/chrome.py — shared page chrome (the dashboard sidebar nav).

The sidebar is rendered as a plain HTML string so it can be injected into
both Jinja-templated pages (memorial, stream_index, manager) AND raw HTML
string pages (status / debug / twitch / OBS in ``server.py``, calc in
``calc/dist/normal.html``). Keeping the source-of-truth here means adding a
new nav item is a one-line change.

Only the dashboard.css / dashboard.js pair is required for the sidebar to
render correctly — pages that include this chrome should link those.
"""

from __future__ import annotations


# Each nav item: (slug, href, label, svg-path-d, item-classes)
#
# Order is intentional: Manager is the first slot so it's always reachable
# at the top of the rail. The other items follow the page-frequency order
# the user works through during a run (status → memorial → stream → twitch
# → OBS → calc → debug). The Manager item's href is a placeholder; if a
# concrete `manager_port` is passed to ``build_sidebar_html`` we rewrite
# the href at parse time via an inline script (see below) so it points at
# ``//{hostname}:{manager_port}``. When ``manager_port`` is None (e.g. when
# the manager page itself renders the sidebar), the item is filtered out
# entirely so the rail doesn't dead-link.
_NAV_ITEMS = [
    ("manager",  "#",                 "Manager",  "M2 1h12v3H2zm0 5h12v3H2zm0 5h12v3H2z",                                                                          "nav-manager"),
    ("status",   "/",                 "Status",   "M1 2h6v6H1zm8 0h6v6H9zM1 10h6v4H1zm8 0h6v4H9z",                                                                "nav-status"),
    ("memorial", "/memorial",         "Memorial", "M6 1h4v3h3v3h-3v8H6V7H3V4h3z",                                                                                  "nav-memorial"),
    ("stream",   "/stream",           "Stream",   "M5 1h2v2H5zM9 1h2v2H9zM1 4h14v10H1zM6 6v6l5-3z",                                                                "nav-stream"),
    ("twitch",   "/twitch",           "Twitch",   "M2 2v8h3v3l3-3h6V2zm3 3h1v3H5zm4 0h1v3H9z",                                                                     "nav-twitch"),
    ("obs",      "/obs",              "OBS",      "M3 4h2l1-1h4l1 1h2v8H3zm5 1a3 3 0 100 6 3 3 0 000-6zm0 2a1 1 0 100 2 1 1 0 000-2z",                             "nav-obs"),
    ("calc",     "/calc/normal.html", "Calc",     "M2 1h12v14H2zM4 3v3h8V3zM4 7v2h2V7zm3 0v2h2V7zm3 0v2h2V7zM4 10v2h2v-2zm3 0v2h2v-2zm3 0v5h2v-5z",               "nav-calc"),
    ("debug",    "/debug",            "Debug",    "M6 1l1 2h2l1-2 1 1-1 2h1v1h2v2h-2v2h2v2h-2v1l-3 2-3-2v-1H3v-2h2V9H3V7h2V5h1L5 3z",                             "nav-debug"),
]

# SLink Pokéball logo (kept verbatim so the SVG path data isn't duplicated).
_LOGO_SVG = (
    '<svg viewBox="0 0 595.3 594.1">'
    '<path fill="#fff" d="M297.6,380.9c-40.4,0-74.1-28.6-82.1-66.6H81.1c9.5,110.5,102.2,197.2,215.1,197.2s205.7-86.7,215.1-197.2H379.7C371.7,352.4,338,380.9,297.6,380.9z"/>'
    '<path fill="#FF1C1C" d="M297.7,213.2c40.4,0,74.1,28.6,82.1,66.6h134.4C504.7,169.2,412,82.5,299,82.5S93.4,169.2,83.9,279.7h131.7C223.6,241.7,257.3,213.2,297.7,213.2z"/>'
    '<path fill="#fff" d="M347.1,297c0-6.1-1.1-11.9-3.2-17.3c-7-18.8-25.1-32.1-46.3-32.1s-39.3,13.4-46.3,32.1c-2,5.4-3.1,11.2-3.1,17.3s1.1,11.9,3.1,17.3c7,18.8,25.1,32.1,46.3,32.1c21.2,0,39.3-13.4,46.3-32.1C346,309,347.1,303.1,347.1,297z"/>'
    '<path d="M299,82.5c113,0,205.7,86.7,215.1,197.2H379.7c-8-38-41.7-66.6-82.1-66.6c-40.4,0-74.1,28.6-82.1,66.6H83.9C93.4,169.2,186.1,82.5,299,82.5z M343.9,279.7c2,5.4,3.1,11.2,3.1,17.3s-1.1,11.9-3.1,17.3c-7,18.8-25.1,32.1-46.3,32.1c-21.2,0-39.3-13.4-46.3-32.1c-2-5.4-3.1-11.2-3.1-17.3s1.1-11.9,3.1-17.3c7-18.8,25.1-32.1,46.3-32.1S336.9,261,343.9,279.7z M296.2,511.6c-113,0-205.7-86.7-215.1-197.2h134.4c8,38,41.7,66.6,82.1,66.6s74.1-28.6,82.1-66.6h131.7C501.9,424.8,409.2,511.6,296.2,511.6z M297.6,41.3C156.4,41.3,41.9,155.8,41.9,297s114.5,255.7,255.7,255.7S553.4,438.3,553.4,297S438.9,41.3,297.6,41.3z"/>'
    '</svg>'
)


def build_sidebar_html(
    active: str,
    *,
    tcp_port: int | str | None = None,
    manager_port: int | None = None,
) -> str:
    """Render the dashboard sidebar as a plain HTML string.

    ``active`` is the slug of the page rendering this sidebar — the matching
    item gets ``aria-current="page"``; all other items get
    ``target="_blank" rel="noopener"``.

    ``tcp_port`` is shown in the brand subtitle. Pass ``None`` for pages that
    aren't tied to a specific run (manager, stream gallery on the manager,
    calc loaded outside the SLink server). The subtitle then renders as a
    bare label without a port number.

    ``manager_port`` enables the "Manager" nav item; pass ``None`` to omit it
    (e.g. when the page IS the manager).
    """
    nav_parts: list[str] = []
    # Element id for the Manager nav anchor — rewritten at parse-time by the
    # inline <script> below so the href points at the correct manager port
    # for the current host. The id is scoped to the active page so multiple
    # sidebars on a single domain don't collide.
    mgr_id = f"mgr-link-{active}"
    for slug, href, label, path_d, cls in _NAV_ITEMS:
        # Skip the Manager item when no manager_port is supplied (i.e. the
        # manager page itself is rendering this sidebar) — otherwise it'd
        # be a dead link with no port to dial.
        if slug == "manager" and not manager_port:
            continue
        is_active = (slug == active)
        # Tab-open policy: only the calc tool spawns a new tab (it's a
        # standalone reference page that benefits from staying open beside
        # the dashboard). Every other nav item — including Manager — swaps
        # in place, matching the project's new "sidebar = page navigation"
        # convention.
        if is_active:
            extra = ' aria-current="page"'
        elif slug == "calc":
            extra = ' target="_blank" rel="noopener"'
        else:
            extra = ''
        # Manager anchor gets the runtime-rewriteable id + a `#` placeholder
        # href that the script at the bottom replaces with the manager URL.
        if slug == "manager":
            anchor_open = f'<a id="{mgr_id}" class="dash-side-item {cls}" href="#"{extra}>'
        else:
            anchor_open = f'<a class="dash-side-item {cls}" href="{href}"{extra}>'
        nav_parts.append(
            f'{anchor_open}'
            f'<svg class="dash-side-ico" viewBox="0 0 16 16" aria-hidden="true">'
            f'<path fill="currentColor" d="{path_d}"/>'
            f'</svg>'
            f'<span class="dash-side-label">{label}</span>'
            f'</a>'
        )
    if manager_port:
        # The Manager item is rendered at the TOP of the rail (see the
        # _NAV_ITEMS order); the inline <script> appended at the end of the
        # nav rewrites its href to the live host:port pair. Keeping this as
        # a one-shot script (no event listener, no fallback) is fine because
        # by the time the script tag is parsed the anchor it references is
        # already in the DOM.
        nav_parts.append(
            f'<script>document.getElementById("{mgr_id}").href='
            f'"//" + window.location.hostname + ":{manager_port}";</script>'
        )
    port_label = f"TCP {tcp_port}" if tcp_port else "Tracker"
    return (
        '<aside class="dash-sidebar" hx-boost="false">'
        '<header class="dash-sidebar-brand">'
        f'<span class="slink-logo" aria-hidden="true">{_LOGO_SVG}</span>'
        '<div class="dash-sidebar-title">'
        '<span class="dash-sidebar-name">Soul Link</span>'
        f'<span class="dash-sidebar-port">{port_label}</span>'
        '</div>'
        '<button class="dash-sidebar-toggle" type="button" aria-label="Toggle navigation" '
        'onclick="window.SLinkDash &amp;&amp; window.SLinkDash.toggleSidebar()">'
        '<svg class="dash-sidebar-toggle-ico" viewBox="0 0 16 16" aria-hidden="true">'
        '<path fill="currentColor" d="M2 3h12v2H2zm0 4h12v2H2zm0 4h12v2H2z"/>'
        '</svg></button>'
        '</header>'
        '<nav class="dash-sidebar-nav" aria-label="Primary">'
        + ''.join(nav_parts) +
        '</nav>'
        # Font picker sits ABOVE the theme picker — dashboard.js builds the
        # widget and drops it into the .dash-sidebar-font slot at parse
        # time. Stacked so the user reads "font then theme" top-to-bottom,
        # which matches the visual weight of the two controls (font is a
        # broader voice choice; theme is the palette).
        '<div class="dash-sidebar-font"></div>'
        '<div class="dash-sidebar-theme"></div>'
        '</aside>'
    )
