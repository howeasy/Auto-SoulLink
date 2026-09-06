"""A small loopback OBS protocol fixture; never controls an OBS installation.

Message framing follows the official obs-websocket 5.x protocol:
https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
"""

import asyncio
import json

import msgpack

from aiohttp import WSMsgType, web


class OBSFixture:
    def __init__(self):
        self.app = web.Application()
        self.app.router.add_get("/", self.socket)
        self.app.on_cleanup.append(self.close)
        self.scenes = ["Board", "Battle", "Caught", "Other run"]
        self.current = "Board"
        self.requests = []
        self.sockets = set()
        self.release = asyncio.Event()
        self.release.set()
        self.received = asyncio.Event()
        self.active = self.peak = 0

    async def socket(self, request):
        ws = web.WebSocketResponse(protocols=("obswebsocket.msgpack", "obswebsocket.json"))
        await ws.prepare(request)
        self.sockets.add(ws)
        async def send(frame):
            if ws.ws_protocol == "obswebsocket.msgpack":
                await ws.send_bytes(msgpack.packb(frame))
            else:
                await ws.send_json(frame)
        await send({"op": 0, "d": {"obsStudioVersion": "fixture", "obsWebSocketVersion": "5.5.2", "rpcVersion": 1}})
        identified = False
        try:
            async for message in ws:
                if message.type not in (WSMsgType.TEXT, WSMsgType.BINARY):
                    continue
                frame = msgpack.unpackb(message.data) if message.type == WSMsgType.BINARY else json.loads(message.data)
                if frame["op"] == 1:
                    identified = True
                    await send({"op": 2, "d": {"negotiatedRpcVersion": 1}})
                elif frame["op"] == 6 and identified:
                    data = frame["d"]
                    kind = data["requestType"]
                    payload, ok, comment = {}, True, ""
                    if kind == "GetSceneList":
                        payload = {"scenes": [{"sceneName": name, "sceneIndex": index} for index, name in enumerate(self.scenes)],
                                   "currentProgramSceneName": self.current}
                    elif kind == "SetCurrentProgramScene":
                        scene = data.get("requestData", {}).get("sceneName")
                        self.requests.append(scene)
                        self.active += 1
                        self.peak = max(self.peak, self.active)
                        self.received.set()
                        try:
                            await self.release.wait()
                            ok = scene in self.scenes
                            if ok:
                                self.current = scene
                            else:
                                comment = "Scene unavailable in the isolated fixture"
                        finally:
                            self.active -= 1
                    else:
                        ok, comment = False, "Request unsupported by the isolated fixture"
                    await send({"op": 7, "d": {"requestType": kind, "requestId": data["requestId"],
                        "requestStatus": {"result": ok, "code": 100 if ok else 600, "comment": comment}, "responseData": payload}})
        finally:
            self.sockets.discard(ws)
        return ws

    async def close(self, app=None):
        await asyncio.gather(*(ws.close() for ws in list(self.sockets)), return_exceptions=True)
