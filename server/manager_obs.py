"""HTTP ownership and private execution transport for manager OBS settings."""

import asyncio
import copy
from pathlib import Path

import aiohttp
from aiohttp import web

from server.http_safety import local_operator
from server.obs_arbitration import OBSArbiter, OBSConfigError, endpoint
from server.run_proxy import upstream


class ManagerOBSMixin:
    def initialize_obs(self, directory):
        self._obs_apply_locks = {}
        self._obs_applications = {}
        self._obs_sync_lock = asyncio.Lock()
        self._obs_sync_key = None
        self._obs_authority_error = None
        self.obs = OBSArbiter(Path(directory) / "obs_manager.json", self._obs_run, self._execute_obs)

    def _obs_run(self, run_id):
        return next((run for run in self._get() if run["run_id"] == run_id), None)

    async def _obs_call(self, run, action, *, body=None, query=None):
        if run is None or run.get("status") != "running":
            return {"ok": False, "confirmed": True, "error": "The source run is stopped or unavailable."}
        try:
            async with self._http_session.request(
                "POST" if body is not None else "GET", upstream(run) + "/_internal/obs/" + action,
                json=body, params=query, headers={"X-SLink-Target-Run": run["run_id"]},
                timeout=aiohttp.ClientTimeout(total=22, sock_connect=3), allow_redirects=False,
            ) as response:
                if response.headers.get("X-SLink-Run-Id") != run["run_id"]:
                    return {"ok": False, "confirmed": False, "error": "The run execution identity could not be verified."}
                result = await response.json()
                if response.status >= 400:
                    return {"ok": False, "confirmed": True, "error": result.get("error", "The run rejected OBS configuration.")}
                return result
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return {"ok": False, "confirmed": False, "error": "The run did not confirm OBS execution or configuration."}

    async def _apply_obs(self, run, config):
        if run is None:
            return {"ok": False, "confirmed": True, "error": "Choose a source run."}
        async with self._obs_apply_locks.setdefault(run["run_id"], asyncio.Lock()):
            result = await self._obs_call(run, "config", body={"revision": config["revision"], "config": {
                "enabled": config["enabled"], "connections": copy.deepcopy(config["connections"])}})
            if result.get("applied_revision") != config["revision"]:
                result = {**result, "ok": False, "error": result.get("error", "The run did not apply the OBS configuration revision.")}
            else:
                result["ok"] = True
            self._obs_applications[run["run_id"]] = result
            return result

    async def _execute_obs(self, decision):
        if decision["revision"] != self.obs.config["revision"]:
            return {"ok": False, "confirmed": True, "error": "OBS settings changed before execution."}
        if not await self._ensure_obs_authority(decision["config"]):
            return {"ok": False, "confirmed": True, "error": self._obs_authority_error or "OBS configuration changed before execution."}
        run = self._obs_run(decision["run_id"])
        if decision["revision"] != self.obs.config["revision"]:
            return {"ok": False, "confirmed": True, "error": "OBS settings changed before execution."}
        return await self._obs_call(run, "scene", body={"revision": decision["revision"],
            "decision_id": f"{decision['run_id']}:{decision['batch_id']}:{decision['player']}",
            "player": decision["player"], "scene": decision["scene"]})

    async def _ensure_obs_authority(self, config):
        async with self._obs_sync_lock:
            if config["revision"] != self.obs.config["revision"]:
                return False
            runs = [run for run in self._get() if run.get("status") == "running"]
            key = config["revision"], tuple(sorted((run["run_id"], run.get("pid"), run.get("http_port")) for run in runs))
            if self._obs_sync_key == key:
                return True
            results = await asyncio.gather(*(self._apply_obs(run, config) for run in runs))
            if not all(result.get("ok") for result in results):
                self._obs_authority_error = "Scene automation is paused until every running server accepts the manager's configuration. Restart runs using an older server."
                return False
            if config["revision"] != self.obs.config["revision"]:
                return False
            self._obs_sync_key, self._obs_authority_error = key, None
            return True

    async def handle_obs_events(self, request):
        if not local_operator(request):
            raise web.HTTPNotFound()
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("run_id"), str):
                raise OBSConfigError("An explicit source run is required.")
            receipt = await self.obs.submit(body["run_id"], body.get("batch_id"), body.get("fired"))
            return web.json_response({"ok": True, **receipt}, status=202)
        except (OBSConfigError, ValueError) as error:
            return web.json_response({"ok": False, "error": str(error)}, status=400)

    async def handle_global_obs_status(self, request):
        run_id = request.query.get("run_id")
        if run_id:
            run = self._obs_run(run_id)
            if run and run.get("status") == "running":
                self._obs_applications[run_id] = await self._obs_call(run, "status")
            else:
                self._obs_applications[run_id] = {"ok": False, "applied_revision": None,
                    "error": "This source run is stopped." if run else "This source run no longer exists."}
        return web.json_response({**self.obs.status(), "applications": copy.deepcopy(self._obs_applications), "authority_error": self._obs_authority_error,
                                  "runs": [{"run_id": run["run_id"], "name": run.get("name", run["run_id"]),
                                            "status": run.get("status")} for run in self._get()]})

    async def handle_global_obs_config(self, request):
        try:
            body = await request.json()
            result = await self.obs.update(body)
        except (OBSConfigError, ValueError) as error:
            return web.json_response({"ok": False, "error": str(error)}, status=409 if "changed" in str(error) else 400)
        config = copy.deepcopy(self.obs.config)
        await self._ensure_obs_authority(config)
        return web.json_response({"ok": True, **result, "applications": copy.deepcopy(self._obs_applications), "authority_error": self._obs_authority_error})

    async def handle_global_obs_scenes(self, request):
        player = request.match_info["player"]
        run = self._obs_run(request.query.get("run_id"))
        if player not in ("a", "b") or run is None:
            return web.json_response({"ok": False, "error": "Choose a source run and player.", "scenes": []}, status=400)
        applied = await self._apply_obs(run, copy.deepcopy(self.obs.config))
        if not applied.get("ok"):
            return web.json_response(applied, status=503)
        result = await self._obs_call(run, "scenes", query={"player": player})
        return web.json_response(result)

    async def handle_global_obs_resume(self, request):
        try:
            body = await request.json()
            if not isinstance(body, dict) or body.get("player") not in ("a", "b") or body.get("revision") != self.obs.config["revision"]:
                raise ValueError("Choose the current OBS connection to resume.")
            key = endpoint(self.obs.config["connections"][body["player"]])
            self.obs.blocked_endpoints.pop(key, None)
            return web.json_response({"ok": True})
        except (ValueError, TypeError) as error:
            return web.json_response({"ok": False, "error": str(error)}, status=400)

    async def handle_global_obs_test(self, request):
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Choose a source run, player, and scene.")
            result = await self.obs.submit_scene(body.get("run_id"), body.get("player"), body.get("scene"))
            return web.json_response({"ok": True, **result}, status=202)
        except (OBSConfigError, ValueError) as error:
            return web.json_response({"ok": False, "error": str(error)}, status=400)
