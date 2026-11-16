"""给网页的服务的测试：拿样子、拿网格、连上来看状态、发命令；先做完命令再答复；只让认识的网页连。

前一半直接测"收到一条命令怎么办""钟走了怎么办"，不经过网络；后一半真的起一个服务连上去。
"""

import asyncio
import json

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

from nova_sim.bodies import G1, NOVA, Choice
from nova_sim.live import LiveSim
from nova_sim.protocol import MESSAGE, SCENE, problems
from nova_sim.scene import SceneError, drawn_meshes, mesh_payload
from nova_sim.server import PROGRAM_ERROR, STATE_EVERY_TICKS, TICK_S, Hub, create_app

ALLOWED_ORIGIN = "http://localhost:5280"
RECEIVE_TIMEOUT_S = 5.0


def command(kind: str, identifier: int = 1, **fields) -> str:
    return json.dumps({"type": kind, "id": identifier, **fields})


@pytest.fixture
def hub(choices) -> Hub:
    """测试台上放着 Nova，两个身体都能选。"""
    return Hub(choices)


@pytest.fixture
def watched(hub) -> Hub:
    """有一个网页连着的测试台（没有网页连着的时候仿真不走）。"""
    hub.clients.add(object())
    return hub


# 收到命令 --------------------------------------------------------------------------------------------


def test_starts_with_nova_on_the_bench(hub):
    """一开始测试台上是 Nova，第 0 回。"""
    assert (hub.sim.key, hub.sim.episode) == (NOVA, 0)
    assert hub.scene()["body"] == NOVA
    assert problems(SCENE, hub.scene()) == []


def test_does_each_command_and_then_acknowledges_it(watched):
    """每种命令：做完，按编号答复"照做了"。"""
    hub = watched
    assert hub.receive(command("pause", 10)) == {"type": "ack", "id": 10, "ok": True, "reason": ""}
    assert not hub.sim.running
    assert hub.receive(command("resume", 11))["ok"]
    assert hub.sim.running
    assert hub.receive(command("control", 12, on=False))["ok"]
    assert not hub.sim.controlled
    assert hub.receive(command("control", 13, on=True))["ok"]
    assert hub.receive(command("push", 14, direction="left", share=0.04))["ok"]
    assert hub.sim.state()["push"] is not None
    assert hub.receive(command("reset", 15))["ok"]
    assert (hub.sim.episode, hub.sim.state()["push"]) == (1, None)


def test_says_why_when_it_cannot_do_a_command(watched):
    """做不了的命令：答复里写着为什么，仿真不变。"""
    hub = watched
    hub.receive(command("push", 1, direction="left", share=0.04))
    again = hub.receive(command("push", 2, direction="left", share=0.04))
    assert again == {"type": "ack", "id": 2, "ok": False, "reason": "上一下还没推完"}
    hub.receive(command("pause", 3))
    assert hub.receive(command("push", 4, direction="right", share=0.04))["reason"] == "暂停着的时候推不了，先点继续"


@pytest.mark.parametrize(
    ("text", "identifier", "reason"),
    [
        ("not json at all", None, "命令读不出来：不是 JSON"),
        (command("dance", 7), 7, "不认识的命令 'dance'"),
        (command("push", 8, direction="left", share=0.9), 8, "share：0.9 is greater than the maximum of 0.5"),
        (command("push", 9, direction="up", share=0.1), 9, "direction："),
        ('{"type": "reset", "id": -3}', None, "id："),
    ],
    ids=["不是 JSON", "不认识的命令", "推力太大", "不认识的方向", "编号是负的"],
)
def test_refuses_a_malformed_command_without_touching_the_simulation(watched, text, identifier, reason):
    """写得不对的命令：拒绝，答复里带着读得出来的编号和原因；仿真原样不动。"""
    hub = watched
    before = hub.sim.state()
    answer = hub.receive(text)
    assert (answer["type"], answer["id"], answer["ok"]) == ("ack", identifier, False)
    assert reason in answer["reason"]
    assert problems(MESSAGE, answer) == []
    assert hub.sim.state() == before


def test_same_command_twice_is_done_twice(watched):
    """同一条命令来两次（比如网页重发）：做两次，各答复一次。重新开始两次就是又过了两回。"""
    hub = watched
    assert hub.receive(command("reset", 5))["ok"]
    assert hub.receive(command("reset", 5))["ok"]
    assert hub.sim.episode == 2


# 换身体 ----------------------------------------------------------------------------------------------


def test_switches_to_the_baseline_and_back(watched):
    """换成基线：测试台上是 G1，算新的一回，样子也是 G1 的；再换回 Nova。"""
    hub = watched
    assert hub.receive(command("body", 1, body=G1))["ok"]
    assert (hub.sim.key, hub.sim.episode) == (G1, 1)
    scene = hub.scene()
    assert (scene["body"], scene["name"]) == (G1, "Unitree G1")
    assert hub.sim.state()["body"] == G1
    assert hub.receive(command("body", 2, body=NOVA))["ok"]
    assert (hub.sim.key, hub.sim.episode) == (NOVA, 2)


def test_choosing_the_same_body_starts_it_over(watched):
    """选现在这个身体：从头再来，算新的一回。"""
    hub = watched
    hub.tick(0.5)
    assert hub.receive(command("body", 1, body=NOVA))["ok"]
    assert (hub.sim.episode, hub.sim.time_s) == (1, 0.0)


def test_refuses_a_body_that_is_not_there(nova):
    """没有这个身体，或者它的文件还没下载：拒绝，说为什么；测试台上还是原来那个。"""
    choices = {NOVA: Choice(NOVA, "Nova", nova.body), G1: Choice(G1, "Unitree G1", None, "文件还没下载")}
    hub = Hub(choices)
    unknown = hub.receive(command("body", 1, body="atlas"))
    assert (unknown["ok"], unknown["reason"]) == (False, "没有叫 atlas 的身体")
    missing = hub.receive(command("body", 2, body=G1))
    assert (missing["ok"], missing["reason"]) == (False, "Unitree G1 现在用不了：文件还没下载")
    assert (hub.sim.key, hub.sim.episode) == (NOVA, 0)
    assert hub.scene()["choices"][1] == {"body": G1, "name": "Unitree G1", "available": False, "reason": "文件还没下载"}


def test_cannot_start_with_a_body_that_is_not_there(nova):
    """一开始要放的身体用不了：起不来，说为什么。"""
    choices = {G1: Choice(G1, "Unitree G1", None, "文件还没下载")}
    with pytest.raises(Exception, match="Unitree G1 现在用不了：文件还没下载"):
        Hub(choices, first=G1)


# 网格 ------------------------------------------------------------------------------------------------


def test_serves_only_the_meshes_of_the_body_on_the_bench(watched, g1):
    """网格只给现在这个身体用到的：Nova 没有网格；换成 G1 以后拿得到。"""
    hub = watched
    with pytest.raises(SceneError, match="现在这个身体没有用到第 0 个网格"):
        hub.mesh(0)
    hub.receive(command("body", 1, body=G1))
    mesh = min(drawn_meshes(g1))
    assert hub.mesh(mesh) == mesh_payload(g1.model, mesh)
    with pytest.raises(SceneError, match="没有用到第 999 个网格"):
        hub.mesh(999)


# 钟走了 ----------------------------------------------------------------------------------------------


def test_simulation_waits_while_nobody_is_watching(hub):
    """没有网页连着：钟怎么走，仿真都不动，也不发状态。"""
    for _ in range(10):
        assert hub.tick(TICK_S) is None
    assert hub.sim.time_s == 0.0


def test_sends_a_state_every_other_tick_while_watched(watched):
    """有网页连着：仿真跟着钟走，每 2 格发一次状态。"""
    hub = watched
    sent = [hub.tick(TICK_S) for _ in range(6)]
    assert [state is not None for state in sent] == [False, True] * 3
    assert STATE_EVERY_TICKS == 2
    assert sent[-1]["time_s"] == pytest.approx(6 * TICK_S, abs=0.002)
    assert problems(MESSAGE, sent[-1]) == []


def test_program_error_stops_the_simulation_and_is_reported(watched, capsys):
    """仿真的程序自己出错了：停下，状态里说出了问题，详细的写进日志；服务还活着，重新开始就好了。"""
    hub = watched

    def broken(_seconds: float) -> None:
        raise RuntimeError("boom")

    working = hub.sim.advance
    hub.sim.advance = broken
    states = [hub.tick(TICK_S) for _ in range(2)]
    assert states[1]["problem"] == PROGRAM_ERROR
    assert not states[1]["running"]
    assert "RuntimeError: boom" in capsys.readouterr().err
    hub.sim.advance = working
    assert hub.receive(command("reset"))["ok"]
    assert hub.sim.state()["problem"] is None


# 真的连上去 ------------------------------------------------------------------------------------------


def serve(hub: Hub, scenario, origins: str | None = None):
    """起一个服务，连上去做 scenario 里的事。"""

    async def run():
        async with TestClient(TestServer(create_app(hub, origins))) as client:
            return await scenario(client)

    return asyncio.run(run())


async def next_message(socket, kind: str) -> dict:
    """等下一条这种消息。"""
    while True:
        message = await socket.receive_json(timeout=RECEIVE_TIMEOUT_S)
        if message["type"] == kind:
            return message


def test_health_and_scene_over_http(hub):
    """/health 说服务活着；/scene 给出现在这个身体的样子，合规约。"""

    async def scenario(client):
        health = await client.get("/health")
        scene = await client.get("/scene")
        return health.status, await health.json(), scene.status, scene.content_type, await scene.json()

    health_status, health, scene_status, content_type, scene = serve(hub, scenario)
    assert (health_status, health) == (200, {"ok": True})
    assert (scene_status, content_type) == (200, "application/json")
    assert problems(SCENE, scene) == []
    assert scene["name"] == "Nova（核心版）"


def test_mesh_over_http(hub, g1):
    """/mesh/编号 给出网格的二进制；不是数、没有的编号、别的身体的网格都是 404。"""
    hub.receive(command("body", 1, body=G1))
    mesh = min(drawn_meshes(g1))

    async def scenario(client):
        good = await client.get(f"/mesh/{mesh}")
        results = [(good.status, good.content_type, await good.read())]
        for path in ("/mesh/abc", "/mesh/99999", "/mesh/-1"):
            bad = await client.get(path)
            results.append((bad.status, await bad.text()))
        return results

    good, not_a_number, unknown, negative = serve(hub, scenario)
    assert good == (200, "application/octet-stream", mesh_payload(g1.model, mesh))
    assert not_a_number[0] == unknown[0] == negative[0] == 404
    assert "没有用到第 99999 个网格" in unknown[1]


def test_page_gets_a_hello_then_states_that_move_on(hub):
    """网页连上来：先收到招呼，然后状态不停地来，仿真的时间在往前走。"""

    async def scenario(client):
        async with client.ws_connect("/ws", origin=ALLOWED_ORIGIN) as socket:
            greeting = await socket.receive_json(timeout=RECEIVE_TIMEOUT_S)
            first = await next_message(socket, "state")
            second = await next_message(socket, "state")
            return greeting, first, second

    greeting, first, second = serve(hub, scenario)
    assert greeting == {"type": "hello", "body": NOVA, "episode": 0}
    for message in (greeting, first, second):
        assert problems(MESSAGE, message) == []
    assert second["time_s"] > first["time_s"] >= 0.0


def test_command_is_done_before_it_is_acknowledged(hub):
    """发"重新开始"：先收到答复；答复以后的第一条状态已经是新的一回了。"""

    async def scenario(client):
        async with client.ws_connect("/ws", origin=ALLOWED_ORIGIN) as socket:
            await next_message(socket, "state")
            await socket.send_str(command("reset", 42))
            answer = await next_message(socket, "ack")
            after = await next_message(socket, "state")
            return answer, after

    answer, after = serve(hub, scenario)
    assert answer == {"type": "ack", "id": 42, "ok": True, "reason": ""}
    assert after["episode"] == 1


def test_bad_messages_get_an_answer_and_the_connection_stays(hub):
    """读不懂的命令、二进制的消息：答复说为什么，连接不断，后面的命令照做。"""

    async def scenario(client):
        async with client.ws_connect("/ws", origin=ALLOWED_ORIGIN) as socket:
            await socket.send_str("nonsense")
            garbage = await next_message(socket, "ack")
            await socket.send_bytes(b"\x00\x01")
            binary = await next_message(socket, "ack")
            await socket.send_str(command("pause", 3))
            fine = await next_message(socket, "ack")
            return garbage, binary, fine

    garbage, binary, fine = serve(hub, scenario)
    assert (garbage["id"], garbage["ok"], garbage["reason"]) == (None, False, "命令读不出来：不是 JSON")
    assert (binary["ok"], binary["reason"]) == (False, "命令要用文字发，不收二进制的")
    assert fine == {"type": "ack", "id": 3, "ok": True, "reason": ""}


def test_every_page_sees_the_same_simulation(hub):
    """两个网页连着：看到的是同一个仿真；一个发的命令，另一个也看得到结果。走掉一个，另一个照常。"""

    async def scenario(client):
        async with client.ws_connect("/ws") as first:
            async with client.ws_connect("/ws") as second:
                await next_message(second, "state")
                connected = len(hub.clients)
                await first.send_str(command("control", 1, on=False))
                await next_message(first, "ack")
                seen = await next_message(second, "state")
                while seen["controlled"]:
                    seen = await next_message(second, "state")
            await asyncio.sleep(0.1)
            still = await next_message(first, "state")
            return connected, seen, still, len(hub.clients)

    connected, seen, still, remaining = serve(hub, scenario)
    assert connected == 2
    assert not seen["controlled"]
    assert still["type"] == "state"
    assert remaining == 1


def test_simulation_stands_still_between_visits(hub):
    """网页走了以后仿真就停在那里；再连上来时，接着刚才的时间走，没有白白走掉。"""

    async def scenario(client):
        async with client.ws_connect("/ws") as socket:
            await next_message(socket, "state")
            last = await next_message(socket, "state")
        await asyncio.sleep(0.5)
        left_at = hub.sim.time_s
        async with client.ws_connect("/ws") as socket:
            back = await next_message(socket, "state")
        return last, left_at, back

    last, left_at, back = serve(hub, scenario)
    assert left_at == pytest.approx(last["time_s"], abs=0.1)
    assert back["time_s"] == pytest.approx(left_at, abs=0.1)


@pytest.mark.parametrize(
    ("origin", "welcome"),
    [
        (ALLOWED_ORIGIN, True),
        ("http://127.0.0.1:5280", True),
        (None, True),
        ("http://localhost:5180", False),
        ("https://example.com", False),
    ],
    ids=["我们的网页", "我们的网页（数字地址）", "不是浏览器的工具", "别的端口的网页", "别的网站"],
)
def test_only_known_pages_may_connect(hub, origin, welcome):
    """只让我们自己的网页连上来发命令；别的网站的网页连不上（403）。不带来源的工具放行。"""

    async def scenario(client):
        try:
            async with client.ws_connect("/ws", origin=origin) as socket:
                return (await socket.receive_json(timeout=RECEIVE_TIMEOUT_S))["type"]
        except aiohttp.WSServerHandshakeError as error:
            return error.status

    assert serve(hub, scenario) == ("hello" if welcome else 403)


def test_allowed_pages_can_be_configured(hub):
    """允许哪些网页连，可以配置。"""

    async def scenario(client):
        async with client.ws_connect("/ws", origin="http://localhost:9999") as socket:
            return (await socket.receive_json(timeout=RECEIVE_TIMEOUT_S))["type"]

    assert serve(hub, scenario, origins="http://localhost:9999") == "hello"


def test_oversized_message_closes_the_connection(hub):
    """命令都很短。发来一条很长的：不收，连接关掉；服务照常，仿真没变。"""

    async def scenario(client):
        async with client.ws_connect("/ws") as socket:
            await socket.receive_json(timeout=RECEIVE_TIMEOUT_S)
            await socket.send_str(json.dumps({"type": "reset", "id": 1, "padding": "x" * 10_000}))
            while True:
                message = await socket.receive(timeout=RECEIVE_TIMEOUT_S)
                if message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING}:
                    break
        health = await client.get("/health")
        return health.status

    assert serve(hub, scenario) == 200
    assert hub.sim.episode == 0


def test_fresh_simulation_per_hub(choices):
    """每个测试台有自己的仿真：一个里面推倒了，另一个不受影响。"""
    first, second = Hub(choices), Hub(choices)
    first.clients.add(object())
    first.receive(command("control", 1, on=False))
    for _ in range(120):
        first.tick(TICK_S)
    assert first.sim.fallen
    assert isinstance(second.sim, LiveSim)
    assert not second.sim.fallen and second.sim.controlled
