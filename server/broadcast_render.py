"""One rendering path for legacy URLs and saved broadcast documents."""

import math

import aiohttp_jinja2

from server.broadcast_presets import ALIASES, EVENT_FILTERS, PRESETS, default_controls
from server.broadcast_projection import build_broadcast_context
from server.templating import resolve_theme


def legacy_configuration(request, slug):
    alias = ALIASES[slug]
    preset = alias["preset"]
    controls = default_controls(preset)
    for name in ("speed", "pause"):
        if name in controls:
            try:
                value = float(request.query.get(name, controls[name]))
                if math.isfinite(value):
                    controls[name] = max(.1 if name == "speed" else 0, min(5 if name == "speed" else 30, value))
            except (ValueError, TypeError):
                pass
    if "filter" in controls:
        raw = request.query.get("filter", "")
        controls["filter"] = [item for item in raw.split(",") if item in EVENT_FILTERS] if raw else None
    layout = request.query.get("layout", "")
    return {**alias, "controls": controls, "layout": layout if layout in PRESETS[preset]["layouts"] else "",
            "theme": resolve_theme(request), "name": PRESETS[preset]["name"]}


def render_legacy(server, request, slug):
    source = legacy_configuration(request, slug)
    context = build_broadcast_context(server, source["preset"], source["players"], source["controls"])
    path = request.path.removesuffix("/fragment")
    query = request.raw_path.partition("?")[2]
    context.update(source_name=source["name"], theme=source["theme"], layout=source["layout"], revision=0,
                   fragment_url=path + "/fragment" + ("?" + query if query else ""), saved_source=False)
    template = "broadcast/_source_root.html" if request.path.endswith("/fragment") else "broadcast/source.html"
    response = aiohttp_jinja2.render_template(template, request, context)
    response.headers["Cache-Control"] = "no-store"
    return response
