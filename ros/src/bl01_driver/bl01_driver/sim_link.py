"""몸(시뮬레이터)의 WebSocket(/ws)과 장면 설명(/scene)에 붙는 연결.

실제 로봇의 제조사 SDK 자리다: 드라이버 노드는 이것으로 몸과 말하고, 바깥에는 ROS 2로만 보인다.
받는 일은 따로 스레드 하나가 하고, 명령은 여러 스레드(ROS 서비스)에서 보내 답(ack·rejected)을 기다린다.
"""

from __future__ import annotations

import itertools
import json
import logging
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI
from websockets.sync.client import ClientConnection, connect

log = logging.getLogger(__name__)

REPLY_TIMEOUT_S = 2.0
OPEN_TIMEOUT_S = 3.0
SCENE_TIMEOUT_S = 3.0
# 끊기면 이 간격으로 다시 붙는다 (마지막 값을 계속 쓴다)
RETRY_DELAYS_S = (0.5, 1.0, 2.0, 5.0)
NOT_CONNECTED = "몸(시뮬레이터)과 연결되어 있지 않습니다"
NO_REPLY = "몸이 답하지 않습니다 (시간 초과)"
DISCONNECTED = "몸과 연결이 끊겨 답을 받지 못했습니다"
COMBAT_TYPES = frozenset({"shot", "destroyed"})


@dataclass(frozen=True)
class Outcome:
    """명령의 답: 받았는지, 받지 않았으면 까닭"""

    accepted: bool
    reason: str = ""


class _Pending:
    def __init__(self) -> None:
        self.done = threading.Event()
        self.outcome = Outcome(False, NO_REPLY)

    def finish(self, outcome: Outcome) -> None:
        self.outcome = outcome
        self.done.set()


def scene_url(socket_url: str) -> str:
    """ws://sim:8765/ws → http://sim:8765/scene"""
    parts = urlsplit(socket_url)
    scheme = "https" if parts.scheme == "wss" else "http"
    return urlunsplit((scheme, parts.netloc, "/scene", "", ""))


def fetch_scene(url: str) -> str:
    with urllib.request.urlopen(url, timeout=SCENE_TIMEOUT_S) as response:
        text = response.read().decode("utf-8")
    json.loads(text)  # JSON이 아니면 여기서 실패한다 (받는 쪽은 규약 스키마로 다시 확인한다)
    return text


def _ignore(*_args: object) -> None:
    return None


class SimLink:
    def __init__(
        self,
        url: str,
        *,
        reply_timeout_s: float = REPLY_TIMEOUT_S,
        retry_delays_s: tuple[float, ...] = RETRY_DELAYS_S,
        load_scene: Callable[[str], str] = fetch_scene,
    ) -> None:
        self._url = url
        self._reply_timeout_s = reply_timeout_s
        self._retry_delays_s = retry_delays_s
        self._load_scene = load_scene
        self.on_state: Callable[[dict], None] = _ignore
        self.on_event: Callable[[dict], None] = _ignore
        self.on_connection: Callable[[bool], None] = _ignore
        self.on_scene: Callable[[str], None] = _ignore
        self._socket: ClientConnection | None = None
        self._send_lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._ids = itertools.count(1)
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._run, name="sim-link", daemon=True)

    @property
    def connected(self) -> bool:
        return self._socket is not None

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        socket = self._socket
        if socket is not None:
            socket.close()
        self._thread.join(timeout=OPEN_TIMEOUT_S + 1)

    def send(self, command: dict) -> Outcome:
        """명령을 보내고 답을 기다린다 (몸이 범위를 확인하고 받지 않으면 까닭을 돌려준다)."""
        socket = self._socket
        if socket is None:
            return Outcome(False, NOT_CONNECTED)
        command_id = f"ros-{next(self._ids)}"
        pending = _Pending()
        with self._pending_lock:
            self._pending[command_id] = pending
        try:
            with self._send_lock:
                socket.send(json.dumps({**command, "id": command_id}))
        except ConnectionClosed:
            pending.finish(Outcome(False, DISCONNECTED))
        pending.done.wait(self._reply_timeout_s)
        with self._pending_lock:
            self._pending.pop(command_id, None)
        return pending.outcome

    def _run(self) -> None:
        attempt = 0
        while not self._stopping.is_set():
            try:
                self._serve_once()
                attempt = 0
            except (OSError, ConnectionClosed, InvalidHandshake, InvalidURI, TimeoutError, ValueError) as error:
                log.warning("몸에 붙지 못했거나 끊겼다: %s", error)
            if self._stopping.is_set():
                return
            delay = self._retry_delays_s[min(attempt, len(self._retry_delays_s) - 1)]
            attempt += 1
            self._stopping.wait(delay)

    def _serve_once(self) -> None:
        """한 번 붙어서 끊길 때까지 받는다. 붙으면 장면 설명부터 받아 둔다 (명령 범위·유닛 이름)."""
        self.on_scene(self._load_scene(scene_url(self._url)))
        with connect(self._url, open_timeout=OPEN_TIMEOUT_S) as socket:
            self._socket = socket
            self.on_connection(True)
            log.info("몸에 붙었다: %s", self._url)
            try:
                for raw in socket:
                    self._handle(raw)
            finally:
                self._socket = None
                self._fail_pending()
                self.on_connection(False)

    def _handle(self, raw: str | bytes) -> None:
        try:
            message = json.loads(raw)
        except ValueError:
            log.warning("몸이 JSON이 아닌 메시지를 보냈다")
            return
        kind = message.get("type") if isinstance(message, dict) else None
        if kind == "state":
            self.on_state(message)
        elif kind in COMBAT_TYPES:
            self.on_event(message)
        elif kind in ("ack", "rejected"):
            self._finish(message)

    def _finish(self, message: dict) -> None:
        command_id = message.get("id")
        with self._pending_lock:
            pending = self._pending.get(command_id) if isinstance(command_id, str) else None
        if pending is not None:
            accepted = message["type"] == "ack"
            pending.finish(Outcome(accepted, "" if accepted else str(message.get("reason", ""))))

    def _fail_pending(self) -> None:
        with self._pending_lock:
            pending = list(self._pending.values())
        for item in pending:
            item.finish(Outcome(False, DISCONNECTED))
