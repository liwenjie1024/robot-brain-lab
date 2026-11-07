"""몸의 WebSocket 연결: 상태·사건 받기, 명령의 답 기다리기, 끊기면 다시 붙기"""

import json
import threading
import time

import pytest
from websockets.sync.server import ServerConnection, serve

from bl01_driver.sim_link import DISCONNECTED, NO_REPLY, NOT_CONNECTED, SimLink, scene_url

from .samples import SHOT_HIT, STATE

SCENE = '{"robot": {"name": "BL-01"}}'
WAIT_S = 3.0


class FakeBody:
    """시험용 몸: 붙으면 상태와 사건을 하나씩 보내고, 명령에는 정한 대로 답한다"""

    def __init__(self) -> None:
        self.received: list[dict] = []
        self.reply = "ack"
        self.connections: list[ServerConnection] = []
        self._server = serve(self._handle, "127.0.0.1", 0)
        self.port = self._server.socket.getsockname()[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/ws"

    def _handle(self, connection: ServerConnection) -> None:
        self.connections.append(connection)
        connection.send(json.dumps(STATE))
        connection.send(json.dumps(SHOT_HIT))
        for raw in connection:
            command = json.loads(raw)
            self.received.append(command)
            if self.reply == "ack":
                connection.send(json.dumps({"type": "ack", "id": command["id"], "commandType": command["type"], "simTime": 1.0}))
            elif self.reply == "rejected":
                connection.send(json.dumps({"type": "rejected", "id": command["id"], "reason": "범위 밖: forward 99"}))

    def drop_clients(self) -> None:
        for connection in self.connections:
            connection.close()

    def close(self) -> None:
        self._server.shutdown()


def wait_until(condition, timeout: float = WAIT_S) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "기다린 일이 일어나지 않았다"
        time.sleep(0.01)


@pytest.fixture
def body():
    fake = FakeBody()
    yield fake
    fake.close()


@pytest.fixture
def link(body):
    created = SimLink(body.url, reply_timeout_s=0.5, retry_delays_s=(0.05,), load_scene=lambda _url: SCENE)
    created.states, created.events, created.connections, created.scenes = [], [], [], []
    created.on_state = created.states.append
    created.on_event = created.events.append
    created.on_connection = created.connections.append
    created.on_scene = created.scenes.append
    yield created
    created.stop()


def test_receives_scene_state_and_events_after_connecting(link):
    """붙으면 장면 설명을 먼저 받고, 상태·사건을 넘긴다"""
    link.start()

    wait_until(lambda: link.states and link.events)

    assert link.scenes == [SCENE]
    assert link.connections == [True]
    assert link.states[0]["seq"] == 41
    assert link.events[0]["type"] == "shot"


def test_command_waits_for_ack_and_numbers_each_command(body, link):
    """명령마다 번호를 붙여 보내고 같은 번호의 답(ack)을 기다린다"""
    link.start()
    wait_until(lambda: link.connected)

    first = link.send({"type": "fire"})
    second = link.send({"type": "aim", "unit": "drone-1"})

    assert (first.accepted, second.accepted) == (True, True)
    assert [command["id"] for command in body.received] == ["ros-1", "ros-2"]
    assert body.received[1] == {"type": "aim", "unit": "drone-1", "id": "ros-2"}


def test_rejection_returns_reason(body, link):
    """실패: 몸이 거절하면 그 까닭을 그대로 돌려준다"""
    body.reply = "rejected"
    link.start()
    wait_until(lambda: link.connected)

    outcome = link.send({"type": "velocity", "forward": 99, "sideways": 0, "up": 0, "turn": 0})

    assert (outcome.accepted, outcome.reason) == (False, "범위 밖: forward 99")


def test_no_reply_times_out(body, link):
    """실패: 정한 시간 안에 답이 없으면 시간 초과로 끝낸다"""
    body.reply = "none"
    link.start()
    wait_until(lambda: link.connected)

    started = time.monotonic()
    outcome = link.send({"type": "fire"})

    assert (outcome.accepted, outcome.reason) == (False, NO_REPLY)
    assert 0.4 < time.monotonic() - started < 2.0


def test_not_connected_fails_at_once():
    """실패: 붙기 전에는 기다리지 않고 바로 까닭을 돌려준다"""
    outcome = SimLink("ws://127.0.0.1:9/ws").send({"type": "fire"})

    assert (outcome.accepted, outcome.reason) == (False, NOT_CONNECTED)


def test_reconnects_after_body_drops(body, link):
    """끊기면 끊김을 알리고, 정한 간격 뒤 다시 붙어 장면 설명부터 다시 받는다"""
    link.start()
    wait_until(lambda: link.connected)

    body.drop_clients()

    wait_until(lambda: link.connections[-3:] == [True, False, True])
    assert len(link.scenes) == 2


def test_pending_command_fails_when_connection_drops(body, link):
    """순서: 답을 기다리는 동안 끊기면 기다리던 명령을 끊김으로 끝낸다"""
    body.reply = "none"
    link.start()
    wait_until(lambda: link.connected)
    results = []
    sender = threading.Thread(target=lambda: results.append(link.send({"type": "fire"})))

    sender.start()
    wait_until(lambda: body.received)
    body.drop_clients()
    sender.join(WAIT_S)

    assert results[0].reason == DISCONNECTED


@pytest.mark.parametrize(
    ("socket", "expected"),
    [("ws://sim:8765/ws", "http://sim:8765/scene"), ("wss://robot.example:443/ws", "https://robot.example:443/scene")],
    ids=["ws", "wss"],
)
def test_scene_url(socket, expected):
    """장면 설명 주소는 WebSocket 주소에서 만든다"""
    assert scene_url(socket) == expected
