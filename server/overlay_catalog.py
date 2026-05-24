"""server/overlay_catalog.py — single source of truth for the OBS overlay
launcher at /stream/.

Each entry describes one browser-source-ready overlay: its URL slug, display
title, one-line description, family (used for left-rail grouping), the
recommended pixel sizes, the layout variants it supports, and (optionally)
the speed / filter controls it accepts as query parameters.

The launcher template renders the entire catalog as a master-detail UI; the
overlay metadata is also serialised to JSON inside the page so the Alpine
component can switch the right-pane preview without a round-trip.

Adding a new overlay = appending one dict here + registering the route.
No copy-paste of HTML cards required.
"""

from __future__ import annotations

from typing import Any

# Family slugs and the order they appear in the launcher left rail.
FAMILIES = [
    ("overview", "Overview"),
    ("party",    "Party"),
    ("links",    "Links"),
    ("battle",   "Battle"),
    ("death",    "Memorial & Counters"),
    ("badges",   "Gym Badges"),
    ("misc",     "Misc"),
]

# Pre-canned speed pills (used by overlays that auto-scroll).
SPEED_PILLS = ["0.5", "1", "1.5", "2", "3"]

# Pre-canned event filter pills (used by /stream/events and /stream/ticker).
EVENT_FILTERS_DEFAULT_ON = [
    "capture", "shiny", "faint", "force_faint", "whiteout",
    "area_enter", "no_catch", "linked", "dead_zone", "violation",
    "memorialize", "key_change", "hello", "reroll",
]
EVENT_FILTERS_DEFAULT_OFF = ["party_to_box", "box_to_party"]


OVERLAYS: list[dict[str, Any]] = [
    # ── OVERVIEW ────────────────────────────────────────────────────────
    # Synthetic entry — the launcher template renders this as a grid of all
    # OTHER overlays in small iframes instead of a single preview. Slug "all"
    # is reserved; no /stream/all route exists (the iframe URLs in the grid
    # point at the individual overlays' real slugs).
    {
        "slug": "all", "family": "overview",
        "title": "All Overlays",
        "desc": "Live grid of every overlay at once. Useful for spot-checking which scenes are active before you start streaming.",
        "sizes": ["—"],
        "layouts": [""],
    },

    # ── PARTY ──────────────────────────────────────────────────────────
    {
        "slug": "party-a", "family": "party",
        "title": "Player A Party",
        "desc": "Sprites, HP bars, and levels. Tall side panel alongside the game.",
        "sizes": ["Vertical: 280×380", "Horizontal: 580×130", "Strip: 1200×150"],
        "layouts": ["", "h", "thin-h", "thin-v"],
    },
    {
        "slug": "party-b", "family": "party",
        "title": "Player B Party",
        "desc": "Sprites, HP bars, and levels. Tall side panel alongside the game.",
        "sizes": ["Vertical: 280×380", "Horizontal: 580×130", "Strip: 1200×150"],
        "layouts": ["", "h", "thin-h", "thin-v"],
    },

    # ── LINKS ──────────────────────────────────────────────────────────
    {
        "slug": "links", "family": "links",
        "title": "Linked Pairs",
        "desc": "Alive pairs as full cards (area + sprites). Dead pairs as a dimmed list below.",
        "sizes": ["Vertical: 420×340", "Horizontal: 900×200", "Strip: 1400×180"],
        "layouts": ["", "h", "thin-h", "thin-v"],
    },
    {
        "slug": "linked-party", "family": "links",
        "title": "Linked Party ★",
        "desc": "Linked pairs where both mons are currently in party — HP bars, levels, area. Primary overlay for active streaming.",
        "sizes": ["Standard: 500×320", "Bottom strip: 1400×150", "Sidebar: 160×500"],
        "layouts": ["", "thin-h", "thin-v"],
    },
    {
        "slug": "boxed-links", "family": "links",
        "title": "Boxed Links",
        "desc": "Alive linked pairs where one or both mons are currently in the PC box. Auto-scrolls when the list overflows the overlay height.",
        "sizes": ["Sidebar: 200×600", "Standard: 420×340"],
        "layouts": ["", "thin-v"],
        "speeds": SPEED_PILLS,
        "pauses": ["0", "1", "2", "4"],
    },

    # ── BATTLE ─────────────────────────────────────────────────────────
    {
        "slug": "enemy-focus-a", "family": "battle",
        "title": "Enemy Focus · A",
        "desc": "Active enemy(ies) for wild or trainer battles — sprite, HP, status, stat stages, 4-move grid with live PP.",
        "sizes": ["Recommended: 340×260", "Doubles: 480×260"],
        "layouts": [""],
    },
    {
        "slug": "enemy-focus-b", "family": "battle",
        "title": "Enemy Focus · B",
        "desc": "Active enemy(ies) for wild or trainer battles — sprite, HP, status, stat stages, 4-move grid with live PP.",
        "sizes": ["Recommended: 340×260", "Doubles: 480×260"],
        "layouts": [""],
    },
    {
        "slug": "enemy-trainer-a", "family": "battle",
        "title": "Enemy Trainer · A",
        "desc": "Trainer's full enemy team in compact PARTY-style rows. Auto-scrolls when the list overflows. Hidden during wild encounters.",
        "sizes": ["Recommended: 280×220"],
        "layouts": [""],
        "speeds": SPEED_PILLS,
        "pauses": ["0", "1", "2", "4"],
    },
    {
        "slug": "enemy-trainer-b", "family": "battle",
        "title": "Enemy Trainer · B",
        "desc": "Trainer's full enemy team in compact PARTY-style rows. Auto-scrolls when the list overflows. Hidden during wild encounters.",
        "sizes": ["Recommended: 280×220"],
        "layouts": [""],
        "speeds": SPEED_PILLS,
        "pauses": ["0", "1", "2", "4"],
    },
    {
        "slug": "focus-a", "family": "battle",
        "title": "Focus Card — Player A",
        "desc": "Active battle mon hero card: sprite, HP, status, stat stages, 4-move grid with PP bars.",
        "sizes": ["Recommended: 340×380"],
        "layouts": [""],
    },
    {
        "slug": "focus-b", "family": "battle",
        "title": "Focus Card — Player B",
        "desc": "Active battle mon hero card: sprite, HP, status, stat stages, 4-move grid with PP bars.",
        "sizes": ["Recommended: 340×380"],
        "layouts": [""],
    },

    # ── DEATH / COUNTERS ───────────────────────────────────────────────
    {
        "slug": "deaths", "family": "death",
        "title": "Death Counter",
        "desc": "Alive / dead pair counts with glow. Scales to any size — great for a corner badge.",
        "sizes": ["Recommended: 280×160"],
        "layouts": [""],
    },
    {
        "slug": "attempts", "family": "death",
        "title": "Attempts Counter",
        "desc": "Manual run attempt counter with glow. Set the number via the dashboard or API.",
        "sizes": ["Recommended: 200×160"],
        "layouts": [""],
        "attempts_input": True,
    },
    {
        "slug": "stream-memorial", "family": "death",
        "title": "Memorial Scroll",
        "desc": "Chronological scrolling list of all dead pairs with sprites. Auto-scrolls when content exceeds height.",
        "sizes": ["Sidebar: 320×600"],
        "layouts": [""],
        "speeds": SPEED_PILLS,
    },

    # ── BADGES ─────────────────────────────────────────────────────────
    {
        "slug": "badges-a", "family": "badges",
        "title": "Gym Badges — Player A",
        "desc": "Player A's earned gym badges. Unearned badges are dimmed.",
        "sizes": ["Recommended: 340×80"],
        "layouts": [""],
    },
    {
        "slug": "badges-b", "family": "badges",
        "title": "Gym Badges — Player B",
        "desc": "Player B's earned gym badges. Unearned badges are dimmed.",
        "sizes": ["Recommended: 340×80"],
        "layouts": [""],
    },

    # ── MISC ───────────────────────────────────────────────────────────
    {
        "slug": "areas", "family": "misc",
        "title": "Area Tracker",
        "desc": "Linked / dead zone / pending area counts at a glance.",
        "sizes": ["Vertical: 220×160", "Horizontal: 380×80"],
        "layouts": ["", "h"],
    },
    {
        "slug": "events", "family": "misc",
        "title": "Event Feed",
        "desc": "Live feed of captures, faints, area entries, and soul link events.",
        "sizes": ["Recommended: 400×280"],
        "layouts": [""],
        "event_filters": True,
    },
    {
        "slug": "encounters", "family": "misc",
        "title": "Encounter Tracker",
        "desc": "Total encounters, shiny count, and last linked encounter pair.",
        "sizes": ["Standard: 340×200", "Wide: 560×120"],
        "layouts": [""],
    },
    {
        "slug": "ticker", "family": "misc",
        "title": "Event Ticker",
        "desc": "Horizontally scrolling marquee of recent events. Place at the bottom of the stream.",
        "sizes": ["Bottom strip: 1920×60"],
        "layouts": [""],
        "speeds": SPEED_PILLS,
        "event_filters": True,
    },
    {
        "slug": "enc-table-a", "family": "misc",
        "title": "Wild Encounters — Player A",
        "desc": "Encounter rates for Player A's current area (Radical Red only). Walking / Surfing / Fishing with species, rate %, level range.",
        "sizes": ["Recommended: 280×320"],
        "layouts": [""],
        "speeds": SPEED_PILLS,
    },
    {
        "slug": "enc-table-b", "family": "misc",
        "title": "Wild Encounters — Player B",
        "desc": "Encounter rates for Player B's current area (Radical Red only). Walking / Surfing / Fishing with species, rate %, level range.",
        "sizes": ["Recommended: 280×320"],
        "layouts": [""],
        "speeds": SPEED_PILLS,
    },
    {
        "slug": "area-encounter", "family": "misc",
        "title": "Area Encounter",
        "desc": "Soul Link status for the current area: linked pair, pending captures, or dead zone. Auto-follows the most active area.",
        "sizes": ["Recommended: 380×160"],
        "layouts": [""],
    },
]


LAYOUT_LABELS = {
    "":       "Default",
    "h":      "Horizontal",
    "thin-h": "Thin strip",
    "thin-v": "Thin sidebar",
}


def build_index_context(request) -> dict[str, Any]:
    """Render-time context for the master-detail launcher template
    (server/templates/stream_index.html). Same shape used by both
    ``server.py`` and ``manager.py`` so the launcher renders identically on
    the per-run dashboard (port 8080+) and the manager (port 8090).
    """
    import json
    # Lazy import keeps this module free of an aiohttp dependency at
    # import time, so tests that only need the catalog stay light.
    from server.templating import resolve_theme

    return {
        "page_title":              "Soul Link Overlays",
        "theme":                   resolve_theme(request),
        "hide_chrome":             False,
        "is_stream":               False,  # launcher is broadcaster-facing chrome
        "families":                FAMILIES,
        "overlays":                OVERLAYS,
        "overlays_json":           json.dumps(OVERLAYS),
        "layout_labels_json":      json.dumps(LAYOUT_LABELS),
        "default_filters_on_json": json.dumps(EVENT_FILTERS_DEFAULT_ON),
    }
