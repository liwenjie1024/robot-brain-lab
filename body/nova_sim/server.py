"""给网页的服务：拿身体的样子（/scene）、网格（/mesh/编号），连上来看状态、发命令（/ws）。

仿真只在一个地方往前走（下面的 run），命令也在同一个循环里做，所以不会两处同时改它。
答复一条命令之前，命令已经做完了；所以答复以后发出去的状态，一定是做完以后的。
"""

import asyncio
import contextlib
import json
import os
import sys
import traceback
from collections.abc import AsyncIterator
from functools import partial

from aiohttp import WSMsgType, web

from nova_sim.bodies import NOVA, Choice
from nova_sim.live import CommandRejectedError, LiveSim
from nova_sim.protocol import CommandError, ack, command_id, hello, parse_command
from nova_sim.scene import SceneError, describe_scene, drawn_meshes, mesh_payload

DEFAULT_PORT = 8870
# 仿真每秒往前走 60 回；每 2 回给网页发一次状态（每秒 30 次）。
TICK_S = 1.0 / 60.0
STATE_EVERY_TICKS = 2
HEARTBEAT_S = 20.0
# 命令都很短。比这个长的不收。
MAX_COMMAND_BYTES = 4096
FORBIDDEN = 403
NOT_FOUND = 404
# 只让我们自己的网页连上来发命令（浏览器会带上网页的来源）。不是浏览器的工具不带来源，放行。
DEFAULT_ORIGINS = "http://localhost:5280,http://127.0.0.1:5280"
PROGRAM_ERROR = "仿真的程序出错了，已经停下（详细的在服务的日志里）。请重新开始"

to_json = partial(json.dumps, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
HUB = web.AppKey("hub", object)


class Hub:
    """现在放在测试台上的那个身体，和连着的网页。"""

    def __init__(self, choices: dict[str, Choice], first: str = NOVA) -> None:
        self.choices = choices
        self.clients: set[web.WebSocketResponse] = set()
        self.sim = LiveSim(first, self._body(first))
        self._ticks = 0

    def scene(self) -> dict:
        """现在这个身体的样子。"""
        return describe_scene(self.sim.key, self.sim.body, self.choices.values())

    def mesh(self, mesh: int) -> bytes:
        """现在这个身体的一个网格。不是它用到的网格就报错。"""
        if mesh not in drawn_meshes(self.sim.body):
            raise SceneError(f"现在这个身体没有用到第 {mesh} 个网格")
        return mesh_payload(self.sim.body.model, mesh)

    def receive(self, text: str) -> dict:
        """收到网页发来的一条命令：检查、照做，返回答复。"""
        try:
            command = parse_command(text)
        except CommandError as error:
            return ack(command_id(text), str(error))
        try:
            self._apply(command)
        except CommandRejectedError as error:
            return ack(command["id"], str(error))
        return ack(command["id"])

    def tick(self, wall_seconds: float) -> dict | None:
        """钟走了 wall_seconds 秒。没有网页连着就不算（省电脑的力气）。到了该发状态的时候返回状态。"""
        if not self.clients:
            return None
        try:
            self.sim.advance(wall_seconds)
        except Exception:
            traceback.print_exc(file=sys.stderr)
            self.sim.pause()
            self.sim.problem = PROGRAM_ERROR
        self._ticks += 1
        return self.sim.state() if self._ticks % STATE_EVERY_TICKS == 0 else None

    def _apply(self, command: dict) -> None:
        kind = command["type"]
        if kind == "reset":
            self.sim.reset()
        elif kind == "pause":
            self.sim.pause()
        elif kind == "resume":
            self.sim.resume()
        elif kind == "control":
            self.sim.set_controlled(command["on"])
        elif kind == "push":
            self.sim.push(command["direction"], command["share"])
        elif kind == "body":
            self.sim = LiveSim(command["body"], self._body(command["body"]), self.sim.episode + 1)

    def _body(self, key: str):
        choice = self.choices.get(key)
        if choice is None:
            raise CommandRejectedError(f"没有叫 {key} 的身体")
        if choice.body is None:
            raise CommandRejectedError(f"{choice.name} 现在用不了：{choice.reason}")
        return choice.body


def create_app(hub: Hub, origins: str | None = None) -> web.Application:
    """做出服务。origins 是允许连上来的网页的来源，用逗号分开。"""
    allowed = set((origins or os.environ.get("NOVA_VIEW_ORIGINS", DEFAULT_ORIGINS)).split(","))
    app = web.Application()
    app[HUB] = hub
    app.add_routes(
        [
            web.get("/health", _health),
            web.get("/scene", _scene),
            web.get("/mesh/{mesh}", _mesh),
            web.get("/ws", partial(_websocket, allowed=allowed)),
        ]
    )
    app.cleanup_ctx.append(_keep_running)
    return app


async def run(hub: Hub) -> None:
    """让仿真跟着钟往前走，隔一会儿给每个网页发一次状态。一直跑到被取消。"""
    loop = asyncio.get_running_loop()
    last = loop.time()
    while True:
        await asyncio.sleep(TICK_S)
        now = loop.time()
        state = hub.tick(now - last)
        last = now
        if state is not None:
            await _send_to_all(hub, to_json(state))


async def _keep_running(app: web.Application) -> AsyncIterator[None]:
    task = asyncio.create_task(run(app[HUB]))
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _send_to_all(hub: Hub, text: str) -> None:
    for client in list(hub.clients):
        try:
            await client.send_str(text)
        except (ConnectionError, RuntimeError):
            # 这个网页已经断了；它那边的循环会把它从名单里拿掉。
            hub.clients.discard(client)


async def _health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def _scene(request: web.Request) -> web.Response:
    return web.json_response(request.app[HUB].scene(), dumps=to_json)


async def _mesh(request: web.Request) -> web.Response:
    hub: Hub = request.app[HUB]
    try:
        return web.Response(body=hub.mesh(int(request.match_info["mesh"])), content_type="application/octet-stream")
    except (ValueError, SceneError) as error:
        return web.Response(status=NOT_FOUND, text=str(error))


async def _websocket(request: web.Request, allowed: set[str]) -> web.StreamResponse:
    origin = request.headers.get("Origin")
    if origin is not None and origin not in allowed:
        return web.Response(status=FORBIDDEN, text=f"不认识的来源：{origin}")
    hub: Hub = request.app[HUB]
    socket = web.WebSocketResponse(heartbeat=HEARTBEAT_S, max_msg_size=MAX_COMMAND_BYTES)
    await socket.prepare(request)
    await socket.send_str(to_json(hello(hub.sim.key, hub.sim.episode)))
    hub.clients.add(socket)
    try:
        async for message in socket:
            if message.type is WSMsgType.TEXT:
                await socket.send_str(to_json(hub.receive(message.data)))
            elif message.type is WSMsgType.BINARY:
                await socket.send_str(to_json(ack(None, "命令要用文字发，不收二进制的")))
    finally:
        hub.clients.discard(socket)
    return socket
