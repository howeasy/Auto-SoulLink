"""Serve a disposable manager and hydrated HTTP fixtures; never start game TCP.

Lifecycle buttons operate only on this process's synthetic run records. This
supports browser checks of one-origin navigation, polling, and stopped views.
It is not live cartridge or admission evidence.
"""

import asyncio
import json
from html import escape
from urllib.parse import urlencode
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiohttp import web  # noqa: E402

from server import manager  # noqa: E402
from server.broadcast_presets import ALIASES, PRESETS  # noqa: E402
from server.server import build_app  # noqa: E402
from tests.dashboard_scenarios import dashboard_scenario  # noqa: E402
from tests.broadcast_scenarios import capability_scenario, VARIANTS  # noqa: E402
from tests.obs_fixture import OBSFixture  # noqa: E402
from server.obs_controller import OBSController  # noqa: E402
from server.obs_run_bridge import OBSRunBridge  # noqa: E402


async def serve():
    runners, alive, servers = [], set(), {}
    with tempfile.TemporaryDirectory(prefix="slink-manager-review-") as temporary:
        manager.MANAGER_DIR = temporary
        manager.REGISTRY_PATH = str(Path(temporary) / "registry.json")
        manager._is_alive = lambda pid: pid in alive
        manager._kill_run = lambda pid: alive.discard(pid)
        manager._stop_owned_run = lambda run: alive.discard(run.get("pid"))

        async def start_http(run, scenario="empty"):
            if run["run_id"] in servers:
                alive.add(run["http_port"])
                return run["http_port"]
            directory = Path(temporary) / run["run_id"]
            # Creation writes run.json first; hydrate a separate isolated folder.
            server = (capability_scenario if scenario in VARIANTS else dashboard_scenario)(scenario, Path(temporary) / ("fixture-" + run["run_id"]))
            server._run_id, server._run_name, server._manager_port = run["run_id"], run["name"], 8090
            server.obs = OBSController(str(directory / "obs.json"), managed=True)
            server.obs_bridge = OBSRunBridge(server.obs, run["run_id"], 8090)
            server.obs.event_sink = server.obs_bridge.submit
            directory.mkdir(exist_ok=True)
            (directory / "links.json").write_text(json.dumps(server.state.to_document()), encoding="utf-8")
            app = build_app(server)
            runner = web.AppRunner(app)
            await runner.setup()
            runners.append(runner)
            site = web.TCPSite(runner, "127.0.0.1", run.get("http_port", 0))
            await site.start()
            run["http_port"] = site._server.sockets[0].getsockname()[1]
            alive.add(run["http_port"])
            servers[run["run_id"]] = server
            return run["http_port"]

        async def spawn(run, host, manager_port=8090):
            return await start_http(run)
        manager._spawn_run = spawn
        fixture = OBSFixture()
        try:
            obs_runner = web.AppRunner(fixture.app)
            await obs_runner.setup()
            runners.append(obs_runner)
            obs_site = web.TCPSite(obs_runner, "127.0.0.1", 0)
            await obs_site.start()
            obs_port = obs_site._server.sockets[0].getsockname()[1]
            runs = []
            for game in ("gen3", "gen1", "gen2", "gen4", "gen5", "doubles"):
                run = {"run_id": "review_" + game, "name": game.upper() + (" capability sample — no live admission" if game in VARIANTS else " review"), "status": "running",
                       "tcp_port": 54321 + len(runs), "http_port": 0,
                       "game_family": "gen1_rby" if game == "gen1" else "gen3_frlge"}
                run["pid"] = await start_http(run, game)
                runs.append(run)
            manager._save_registry(runs)
            service = manager.RunManager("127.0.0.1", 0)
            async def broadcast_review(request):
                game, preset = request.match_info["game"], request.match_info["preset"]
                if "review_" + game not in servers or preset not in PRESETS:
                    raise web.HTTPNotFound()
                record = PRESETS[preset]
                slug = next(slug for slug, alias in ALIASES.items() if alias["preset"] == preset)
                frames = []
                for size in record["sizes"]:
                    label = size["label"].lower()
                    layout = "thin-v" if "sidebar" in label else "thin-h" if "strip" in label else "h" if "horizontal" in label else ""
                    if layout not in record["layouts"]:
                        layout = ""
                    query = urlencode({"layout": layout, "theme": request.query.get("theme", "transparent")})
                    url = f"/runs/review_{game}/stream/{slug}?{query}"
                    frames.append(f'<section><h2>{escape(size["label"])}</h2><iframe title="{escape(size["label"])}" src="{escape(url)}" width="{size["width"]}" height="{size["height"]}"></iframe></section>')
                links = " ".join(f'<a href="/review/broadcast/{game}/{key}">{escape(key)}</a>' for key in PRESETS)
                return web.Response(text='<html><title>Broadcast fixture review</title><style>body{font:14px sans-serif;background:#777;color:white}a{color:white}iframe{border:0;background:repeating-conic-gradient(#ddd 0% 25%,#fff 0% 50%) 0/24px 24px}section{display:inline-block;vertical-align:top;margin:10px}</style><h1>Synthetic '+escape(game)+' — '+escape(preset)+'</h1><nav>'+links+'</nav>'+''.join(frames)+'</html>',content_type="text/html")

            review_app = manager.build_app(service)
            review_app.router.add_get("/review/broadcast/{game}/{preset}", broadcast_review)
            runner = web.AppRunner(review_app)
            await runner.setup()
            runners.append(runner)
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            for server in servers.values():
                server._manager_port = port
                server.obs_bridge.manager_url = f"http://127.0.0.1:{port}"
            print(json.dumps({"manager": port, "obs": obs_port, "pid": os.getpid(), "fixtures_only": True}), flush=True)
            await asyncio.Event().wait()
        finally:
            for server in servers.values():
                await server.obs_bridge.close()
                await server.obs.stop_workers()
            for runner in reversed(runners):
                await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(serve())
