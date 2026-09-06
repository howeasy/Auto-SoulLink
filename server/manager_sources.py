"""Saved source HTTP routes, tied only to their explicitly stored run."""

import copy

import aiohttp
import aiohttp_jinja2
from aiohttp import web

from server.broadcast_presets import catalog
from server.broadcast_sources import SourceError
from server.run_proxy import upstream


class ManagerSourcesMixin:
    async def handle_sources(self, request):
        identifier = request.match_info.get("source_id")
        try:
            if request.method in ("GET", "HEAD"):
                return web.json_response({"source": self.sources.get(identifier)} if identifier else
                                         {"sources": self.sources.list(), "presets": catalog(),
                                          "runs": [{"run_id": run["run_id"], "name": run.get("name", run["run_id"]), "status": run.get("status")} for run in self._get()]}, headers={"Cache-Control": "no-store"})
            body = await request.json()
            if request.method == "POST" and not identifier:
                source = await self.sources.create(body)
                return web.json_response({"source": source}, status=201)
            if request.method == "PATCH" and identifier:
                return web.json_response({"source": await self.sources.update(identifier, body)})
            if request.method == "DELETE" and identifier:
                await self.sources.delete(identifier, body.get("revision") if isinstance(body, dict) else None)
                return web.json_response({"ok": True})
            raise web.HTTPMethodNotAllowed(request.method, ["GET", "POST", "PATCH", "DELETE"])
        except SourceError as error:
            return web.json_response({"error": str(error)}, status=error.status)
        except ValueError:
            return web.json_response({"error": "A JSON source configuration is required."}, status=400)

    async def _source_context(self, source):
        run = next((run for run in self._get() if run["run_id"] == source["run_id"]), None)
        context = {"preset": source["preset"], "players": [], "pairs": [], "run_id": source["run_id"],
                   "run_name": run.get("name", run["run_id"]) if run else "The assigned run was deleted", "controls": source["controls"]}
        if run is None:
            context.update(availability="deleted", availability_label="Run deleted")
        elif run.get("status") != "running":
            context.update(availability="stopped", availability_label="Run archived" if run.get("status") == "archived" else "Run stopped")
            if source["preset"] in ("links", "linked-party", "boxed-links", "stream-memorial", "area-encounter"):
                saved = await self._saved_board(run)
                rows = copy.deepcopy(saved["rows"])
                if source["preset"] == "stream-memorial":
                    rows = [row for row in rows if row["zone"] == "fallen"]
                for row in rows:
                    for pid in ("a", "b"):
                        if row[pid]:
                            row[pid].update(name=row[pid].get("nickname") or row[pid].get("species_name") or "Unknown Pokémon",
                                            show_hp=False, moves=[], stages_html="")
                context["pairs"] = rows
        else:
            try:
                async with self._http_session.post(upstream(run) + "/_ui/broadcast-context",
                    json={key: source[key] for key in ("preset", "players", "controls")},
                    headers={"X-SLink-Target-Run": run["run_id"]}, timeout=aiohttp.ClientTimeout(total=5), allow_redirects=False) as response:
                    response.raise_for_status()
                    payload = await response.json()
                    if payload.get("run_id") != run["run_id"] or payload.get("schema") != 1:
                        raise ValueError("wrong source run")
                    context = payload["context"]
            except (aiohttp.ClientError, TimeoutError, ValueError, KeyError):
                context.update(availability="unavailable", availability_label="Run temporarily unavailable")
        context.update(source_name=source["name"], theme=source["theme"], layout=source["layout"], revision=source["revision"],
                       saved_source=True, fragment_url="/broadcast/sources/" + source["id"] + "/fragment")
        return context

    async def handle_source_page(self, request):
        identifier = request.match_info["source_id"]
        fragment = request.path.endswith("/fragment")
        try:
            source = self.sources.get(identifier)
            requested = request.query.get("revision")
            if fragment and requested is not None and requested != str(source["revision"]):
                return web.json_response({"revision": source["revision"]}, status=409,
                                         headers={"X-SLink-Source-Revision": str(source["revision"]), "Cache-Control": "no-store"})
            context = await self._source_context(source)
            latest = self.sources.get(identifier)
            # A slow response from the previous run cannot restore its content.
            if latest["revision"] != source["revision"]:
                if not fragment:
                    raise web.HTTPFound(request.path)
                return web.json_response({"revision": latest["revision"]}, status=409,
                                         headers={"X-SLink-Source-Revision": str(latest["revision"]), "Cache-Control": "no-store"})
            template = "broadcast/_source_root.html" if fragment else "broadcast/source.html"
            response = aiohttp_jinja2.render_template(template, request, context)
            response.headers.update({"X-SLink-Source-Revision": str(source["revision"]), "Cache-Control": "no-store"})
            return response
        except SourceError as error:
            if fragment:
                return web.json_response({"error": str(error)}, status=error.status, headers={"Cache-Control": "no-store"})
            context = {"preset": "links", "source_name": "Saved broadcast source", "players": [], "pairs": [], "controls": {},
                       "availability": "deleted" if error.status == 404 else "unavailable", "availability_label": str(error),
                       "run_name": "", "theme": "transparent", "layout": "", "revision": 0, "saved_source": True,
                       "fragment_url": "/broadcast/sources/" + identifier + "/fragment"}
            return aiohttp_jinja2.render_template("broadcast/source.html", request, context, status=error.status)
