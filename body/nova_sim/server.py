"""给网页的服务：拿一个身体的样子（/scene/记号）、网格（/mesh/记号/编号），连上来看状态、发命令（/ws）。

仿真只在一个地方往前走（下面的 run），命令也在同一个循环里做，所以不会两处同时改它。
答复一条命令之前，命令已经做完了；所以答复以后发出去的状态，一定是做完以后的。
给每个网页发东西都经过它自己的队列（channel）：仿真的循环只往里放，不等网页收。
样子和网格按身体的记号拿：拿的中间测试台上换了身体，拿到的也还是要的那个身体的。
"""

import asyncio
import contextlib
import json
import os
import sys
import traceback
from collections.abc import AsyncIterator
from functools import partial
from typing import Protocol

from aiohttp import WSCloseCode, WSMsgType, web

from nova_body.body import Body
from nova_sim.bodies import NOVA, Choice
from nova_sim.channel import ClientChannel
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
# 关掉收不动的网页时说的话（WebSocket 关连接时带的一句，网页会自己再连）。
TOO_SLOW = "网页收得太慢，积压太多，先断开"

to_json = partial(json.dumps, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
HUB = web.AppKey("hub", object)


class NoSuchBodyError(LookupError):
    """没有这个身体，或者它现在用不了。说的话是给人看的。"""


class TextSender(Protocol):
    """能发文字消息的连接（aiohttp 的 WebSocket；测试时换成假的）。"""

    async def send_str(self, data: str) -> None: ...


class Hub:
    """现在放在测试台上的那个身体，和连着的网页（每个网页一个发送队列）。"""

    def __init__(self, choices: dict[str, Choice], first: str = NOVA) -> None:
        self.choices = choices
        self.clients: set[ClientChannel] = set()
        self.sim = LiveSim(first, self.body_of(first))
        self._ticks = 0

    def body_of(self, key: str) -> Body:
        """记号是 key 的身体。没有、或者现在用不了就报错，说为什么。"""
        choice = self.choices.get(key)
        if choice is None:
            raise NoSuchBodyError(f"没有叫 {key} 的身体")
        if choice.body is None:
            raise NoSuchBodyError(f"{choice.name} 现在用不了：{choice.reason}")
        return choice.body

    def scene(self, key: str) -> dict:
        """一个身体的样子。不一定是现在测试台上的那个：每个身体一开始都准备好了。"""
        return describe_scene(key, self.body_of(key), self.choices.values())

    def mesh(self, key: str, mesh: int) -> bytes:
        """一个身体的一个网格。不是这个身体画出来要用的网格就报错。"""
        body = self.body_of(key)
        if mesh not in drawn_meshes(body):
            raise SceneError(f"{body.name} 没有用到第 {mesh} 个网格")
        return mesh_payload(body.model, mesh)

    def receive(self, text: str) -> dict:
        """收到网页发来的一条命令：检查、照做，返回答复。"""
        try:
            command = parse_command(text)
        except CommandError as error:
            return ack(command_id(text), str(error))
        try:
            self._apply(command)
        except (CommandRejectedError, NoSuchBodyError) as error:
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
            self.sim = LiveSim(command["body"], self.body_of(command["body"]), self.sim.episode + 1)


def create_app(hub: Hub, origins: str | None = None) -> web.Application:
    """做出服务。origins 是允许连上来的网页的来源，用逗号分开。"""
    allowed = set((origins or os.environ.get("NOVA_VIEW_ORIGINS", DEFAULT_ORIGINS)).split(","))
    app = web.Application()
    app[HUB] = hub
    app.add_routes(
        [
            web.get("/health", _health),
            web.get("/scene/{body}", _scene),
            # 编号只能是数字：别的（字母、负数）这里就是 404，不用往里传。
            web.get(r"/mesh/{body}/{mesh:\d+}", _mesh),
            web.get("/ws", partial(_websocket, allowed=allowed)),
        ]
    )
    app.cleanup_ctx.append(_keep_running)
    return app


async def run(hub: Hub) -> None:
    """让仿真跟着钟往前走，隔一会儿往每个网页的队列里放一条状态。一直跑到被取消。

    这里不等任何一个网页收：放进队列是马上就好的，发由每个网页自己的发送循环（pump）去等。
    """
    loop = asyncio.get_running_loop()
    last = loop.time()
    while True:
        await asyncio.sleep(TICK_S)
        now = loop.time()
        state = hub.tick(now - last)
        last = now
        if state is not None:
            text = to_json(state)
            for channel in hub.clients:
                channel.put_state(text)


async def pump(channel: ClientChannel, socket: TextSender) -> None:
    """把一个网页的队列里的东西按顺序发出去，一直发到被取消。

    发不出去了就停下：那是连接已经断了，收命令的那个循环也会跟着停（停的时候取消这里）。
    """
    with contextlib.suppress(ConnectionError, RuntimeError):
        while True:
            await socket.send_str(await channel.next())


async def _keep_running(app: web.Application) -> AsyncIterator[None]:
    task = asyncio.create_task(run(app[HUB]))
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def _scene(request: web.Request) -> web.Response:
    hub: Hub = request.app[HUB]
    try:
        return web.json_response(hub.scene(request.match_info["body"]), dumps=to_json)
    except NoSuchBodyError as error:
        return web.Response(status=NOT_FOUND, text=str(error))


async def _mesh(request: web.Request) -> web.Response:
    hub: Hub = request.app[HUB]
    try:
        payload = hub.mesh(request.match_info["body"], int(request.match_info["mesh"]))
    except (NoSuchBodyError, SceneError) as error:
        return web.Response(status=NOT_FOUND, text=str(error))
    return web.Response(body=payload, content_type="application/octet-stream")


async def _websocket(request: web.Request, allowed: set[str]) -> web.StreamResponse:
    origin = request.headers.get("Origin")
    if origin is not None and origin not in allowed:
        return web.Response(status=FORBIDDEN, text=f"不认识的来源：{origin}")
    hub: Hub = request.app[HUB]
    socket = web.WebSocketResponse(heartbeat=HEARTBEAT_S, max_msg_size=MAX_COMMAND_BYTES)
    await socket.prepare(request)
    channel = ClientChannel()
    # 先放招呼，再登记：这样这个网页收到的第一条一定是招呼，状态都在它后面。
    channel.put(to_json(hello(hub.sim.key, hub.sim.episode)))
    hub.clients.add(channel)
    sending = asyncio.create_task(pump(channel, socket))
    try:
        async for message in socket:
            if message.type is WSMsgType.TEXT:
                channel.put(to_json(hub.receive(message.data)))
            elif message.type is WSMsgType.BINARY:
                channel.put(to_json(ack(None, "命令要用文字发，不收二进制的")))
            if channel.overflowing:
                await socket.close(code=WSCloseCode.TRY_AGAIN_LATER, message=TOO_SLOW.encode())
    finally:
        hub.clients.discard(channel)
        sending.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sending
    return socket
