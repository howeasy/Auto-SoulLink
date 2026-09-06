"""Serve isolated, read-only rendering scenarios on temporary loopback ports.

These are UI fixtures, not cartridge admission or live gameplay evidence.
No manager, TCP listener, saved run or real data directory is opened.
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiohttp import web  # noqa: E402

from server.server import build_app  # noqa: E402
from tests.dashboard_scenarios import SCENARIOS, dashboard_scenario  # noqa: E402

PROBE = '<img data-ui-probe="unsafe">'


def add_synthetic_calc(server):
    build = server._build_dashboard_context
    sample = (ROOT / "tests/fixtures/ui/calc_synthetic.json").read_text(encoding="utf-8")

    def context():
        result = build()
        result["players"]["b"]["battle"]["calc"]["calc-input"] = sample
        return result

    server._build_dashboard_context = context


@web.middleware
async def readonly(request, handler):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        return web.json_response({"error": "Read-only rendering fixture"}, status=405)
    if request.app["ui_scenario"] == "security":
        if request.path == "/api/debug/backups":
            return web.json_response({"backups": [{"slot": 1, "modified": PROBE, "size": 1024}]})
        if request.path == "/api/debug/raw_state":
            return web.json_response({"player_identity": {"a": {"trainer_name": PROBE, "ot_id": PROBE}},
                                      "_live": {"identity_errors": {"a": PROBE}},
                                      "_memorial": {"memorial_box_index": 2,
                                                    "memorial_box_contents": {"a": [{"slot": 0, "key": PROBE, "nickname": PROBE,
                                                                                       "species_name": PROBE, "status": "quarantined"}]},
                                                    "memorial_log": [{"area_id": PROBE, "a": {"nickname": PROBE}, "cause": PROBE}]}})
    response = await handler(request)
    if request.path == "/":
        print("UI_RENDER " + request.app["ui_scenario"], flush=True)
    return response


async def serve(scenarios):
    runners = []
    with tempfile.TemporaryDirectory(prefix="slink-ui-scenarios-") as temporary:
        ports = {}
        try:
            for name in scenarios:
                server = dashboard_scenario("gen3" if name in ("calc", "security") else name, Path(temporary) / name)
                server._run_name = name.upper() + " rendering fixture"
                if name == "calc":
                    add_synthetic_calc(server)
                if name == "security":
                    server.trainer_name["a"] = PROBE
                    for mon in server.party_details["a"].values():
                        mon["nickname"] = PROBE
                    for link in server.state.links:
                        if link.a:
                            link.a.nickname = PROBE
                app = build_app(server)
                app["ui_scenario"] = name
                app.middlewares.insert(0, readonly)
                runner = web.AppRunner(app)
                await runner.setup()
                runners.append(runner)
                site = web.TCPSite(runner, "127.0.0.1", 0)
                await site.start()
                ports[name] = site._server.sockets[0].getsockname()[1]
            print(json.dumps({"UI_SCENARIOS": ports, "pid": os.getpid()}), flush=True)
            await asyncio.Event().wait()
        finally:
            for runner in runners:
                await runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", action="append", choices=(*SCENARIOS, "calc", "security"))
    asyncio.run(serve(parser.parse_args().scenario or ["gen3", "gen1"]))
