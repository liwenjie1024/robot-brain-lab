"""몸의 서버: 화면용 모델 설명(GET /scene, /meshes/{id}), 상태와 명령(WebSocket /ws)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque

from aiohttp import WSMsgType, web

from .commands import CommandRejectedError, parse_command
from .limits import CommandLimits
from .runner import RealtimeRunner
from .scene import describe, mesh_binary, moving_bodies
from .simulation import Simulation

log = logging.getLogger(__name__)

# 명령 하나는 수백 바이트다. 큰 메시지는 경계에서 끊는다.
MAX_COMMAND_BYTES = 16 * 1024
HEARTBEAT_SECONDS = 10.0
COMPACT_JSON = (",", ":")

SIMULATION = web.AppKey("simulation", Simulation)
LIMITS = web.AppKey("limits", CommandLimits)
RUNNER = web.AppKey("runner", RealtimeRunner)
SCENE = web.AppKey("scene", dict)


class ClientChannel:
    """WebSocket 하나로 보낼 것을 만든 순서대로 보낸다. 명령의 답은 빠짐없이 보내고, 아직 못 보낸 상태가 이어서 쌓이면
    가장 새 것만 남긴다 (느린 화면이 밀리지 않게). 답이 앞서 만든 상태를 앞지르지 않아야, 받는 쪽이 답 뒤의 상태에서
    명령이 적용된 것을 본다."""

    def __init__(self, socket: web.WebSocketResponse) -> None:
        self._socket = socket
        self._outbox: deque[tuple[bool, str]] = deque()
        self._wake = asyncio.Event()

    def offer_state(self, text: str) -> None:
        if self._outbox and self._outbox[-1][0]:
            self._outbox[-1] = (True, text)
        else:
            self._outbox.append((True, text))
        self._wake.set()

    def reply(self, message: dict) -> None:
        self._outbox.append((False, json.dumps(message, ensure_ascii=False, separators=COMPACT_JSON)))
        self._wake.set()

    async def run_sender(self) -> None:
        while not self._socket.closed:
            await self._wake.wait()
            self._wake.clear()
            while self._outbox:
                _, text = self._outbox.popleft()
                await self._socket.send_str(text)


class StateHub:
    """시뮬레이션 스레드가 만든 상태를 이벤트 루프에서 모든 연결로 나눠 준다."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._clients: set[ClientChannel] = set()

    def add(self, client: ClientChannel) -> None:
        self._clients.add(client)

    def remove(self, client: ClientChannel) -> None:
        self._clients.discard(client)

    def publish_from_thread(self, message: dict) -> None:
        # JSON은 시뮬레이션 스레드에서 만들어 이벤트 루프의 일을 줄인다.
        text = json.dumps(message, separators=COMPACT_JSON)
        self._loop.call_soon_threadsafe(self._fan_out, text)

    def _fan_out(self, text: str) -> None:
        for client in self._clients:
            client.offer_state(text)


HUB = web.AppKey("hub", StateHub)


def create_app(simulation: Simulation, limits: CommandLimits) -> web.Application:
    app = web.Application()
    app[SIMULATION] = simulation
    app[LIMITS] = limits
    control_hz = 1.0 / simulation.controller.config.control_dt
    app[SCENE] = describe(
        simulation.model,
        simulation.pelvis_body,
        limits,
        {"physicsHz": 1.0 / simulation.model.opt.timestep, "controlHz": control_hz, "stateHz": control_hz},
    )
    app.on_startup.append(_start_simulation)
    app.on_cleanup.append(_stop_simulation)
    app.router.add_get("/health", _health)
    app.router.add_get("/scene", _scene)
    app.router.add_get("/meshes/{mesh_id}", _mesh)
    app.router.add_get("/ws", _websocket)
    return app


async def _start_simulation(app: web.Application) -> None:
    hub = StateHub(asyncio.get_running_loop())
    simulation = app[SIMULATION]
    runner = RealtimeRunner(simulation, moving_bodies(simulation.model), hub.publish_from_thread)
    app[HUB] = hub
    app[RUNNER] = runner
    runner.start()
    log.info("시뮬레이션을 시작했습니다 (제어 %.0fHz)", app[SCENE]["rates"]["controlHz"])


async def _stop_simulation(app: web.Application) -> None:
    app[RUNNER].stop()


async def _health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def _scene(request: web.Request) -> web.Response:
    return web.json_response(request.app[SCENE], dumps=lambda value: json.dumps(value, ensure_ascii=False))


async def _mesh(request: web.Request) -> web.Response:
    try:
        body = mesh_binary(request.app[SIMULATION].model, int(request.match_info["mesh_id"]))
    except (KeyError, ValueError):
        raise web.HTTPNotFound(text="그런 메시가 없습니다") from None
    return web.Response(body=body, content_type="application/octet-stream")


async def _websocket(request: web.Request) -> web.WebSocketResponse:
    socket = web.WebSocketResponse(heartbeat=HEARTBEAT_SECONDS, max_msg_size=MAX_COMMAND_BYTES)
    await socket.prepare(request)
    app = request.app
    loop = asyncio.get_running_loop()
    channel = ClientChannel(socket)
    app[HUB].add(channel)
    sender = asyncio.create_task(channel.run_sender())
    try:
        async for message in socket:
            if message.type == WSMsgType.TEXT:
                _handle_command(app, loop, channel, message.data)
            elif message.type == WSMsgType.BINARY:
                channel.reply({"type": "rejected", "reason": "명령은 글자(JSON)로 보내야 합니다"})
    finally:
        app[HUB].remove(channel)
        sender.cancel()
    return socket


def _handle_command(app: web.Application, loop: asyncio.AbstractEventLoop, channel: ClientChannel, text: str) -> None:
    try:
        command = parse_command(text, app[LIMITS])
    except CommandRejectedError as error:
        rejected = {"type": "rejected", "reason": error.reason}
        if error.command_id is not None:
            rejected["id"] = error.command_id
        channel.reply(rejected)
        return
    app[RUNNER].submit(command, lambda reply: loop.call_soon_threadsafe(channel.reply, reply))
