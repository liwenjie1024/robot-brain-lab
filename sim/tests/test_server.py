"""서버: 실제로 띄워 화면·두뇌가 쓰는 방식 그대로 묻고 명령한다."""

from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from robot_sim.limits import DEFAULT_LIMITS
from robot_sim.server import MAX_COMMAND_BYTES, create_app

WAIT_SECONDS = 5.0
FLY = {"type": "velocity", "forward": 0, "sideways": 0, "up": 0, "turn": 0}


@pytest.fixture
async def client(simulation):
    async with TestClient(TestServer(create_app(simulation, DEFAULT_LIMITS))) as test_client:
        yield test_client


async def next_message(socket, wanted_type: str) -> dict:
    """원하는 종류의 메시지가 올 때까지 읽는다 (상태 메시지가 계속 섞여 온다)."""
    async with asyncio.timeout(WAIT_SECONDS):
        while True:
            message = await socket.receive()
            assert message.type == WSMsgType.TEXT, message
            data = json.loads(message.data)
            if data["type"] == wanted_type:
                return data


async def messages_until_state(socket) -> list[dict]:
    """다음 상태 메시지가 올 때까지 받은 것을 순서대로 (상태 포함)"""
    received = []
    async with asyncio.timeout(WAIT_SECONDS):
        while True:
            data = json.loads((await socket.receive()).data)
            received.append(data)
            if data["type"] == "state" and len(received) > 1:
                return received


async def test_scene_is_served(client):
    """화면은 /scene으로 시험장 모양·유닛·장면 목록을 받는다"""
    scene = await (await client.get("/scene")).json()

    assert scene["robot"]["name"] == "BL-01"
    assert {unit["id"] for unit in scene["units"]} >= {"mecha", "drone-1"}
    assert "skirmish" in [scenario["name"] for scenario in scene["scenarios"]]


async def test_unknown_mesh_is_404(client):
    assert (await client.get("/meshes/0")).status == 404
    assert (await client.get("/meshes/abc")).status == 404


async def test_streams_state_in_order(client):
    """연결하면 제어 주기마다 상태가 순서대로 온다 (기체, 이 장면의 드론, 위협)"""
    async with client.ws_connect("/ws") as socket:
        first = await next_message(socket, "state")
        second = await next_message(socket, "state")

    assert second["seq"] > first["seq"]
    assert second["simTime"] > first["simTime"]
    assert first["scenario"] == "targets"
    assert first["mecha"]["mode"] == "landed"
    assert [unit["id"] for unit in first["units"]] == ["drone-1", "drone-2", "drone-3"]
    assert first["threats"] == []


async def test_velocity_command_is_acknowledged_and_followed(client):
    """비행 명령을 보내면 번호로 받았다고 알리고, 그 뒤 상태의 명령 값이 바뀌어 있다"""
    async with client.ws_connect("/ws") as socket:
        await socket.send_json({**FLY, "id": "c-1", "up": 5})
        ack = await next_message(socket, "ack")
        state = await next_message(socket, "state")

    assert ack["id"] == "c-1"
    assert ack["commandType"] == "velocity"
    assert state["mecha"]["command"]["up"] == 5


async def test_fire_ack_comes_before_its_shot_event(client):
    """순서: 쏘기의 답 → 사격 사건 → 상태 순서로 온다 (두뇌가 답 뒤에 결과를 본다)"""
    async with client.ws_connect("/ws") as socket:
        await next_message(socket, "state")
        await socket.send_json({"type": "fire", "id": "f-1"})
        await next_message(socket, "ack")
        following = await messages_until_state(socket)

    assert following[0]["type"] == "shot"
    assert following[0]["shooter"] == "mecha"
    assert following[-1]["type"] == "state"


async def test_runtime_rejection_keeps_id(client):
    """실패: 모양은 맞지만 지금 할 수 없는 명령(식는 중 사격, 없는 표적)은 번호와 까닭을 붙여 거절한다"""
    async with client.ws_connect("/ws") as socket:
        await socket.send_json({"type": "fire", "id": "f-1"})
        await socket.send_json({"type": "fire", "id": "f-2"})
        await socket.send_json({"type": "aim", "id": "a-1", "unit": "drone-9"})
        await next_message(socket, "ack")
        cooling = await next_message(socket, "rejected")
        unknown = await next_message(socket, "rejected")

    assert cooling["id"] == "f-2"
    assert "식는 중" in cooling["reason"]
    assert unknown == {"type": "rejected", "id": "a-1", "reason": "그런 표적이 없습니다: drone-9"}


async def test_invalid_command_is_rejected_without_stopping_stream(client):
    """실패: 모양·범위가 틀린 명령은 까닭과 함께 거절하고, 연결과 상태 보내기는 계속된다"""
    async with client.ws_connect("/ws") as socket:
        await socket.send_json({**FLY, "id": "c-2", "forward": 90})
        rejected = await next_message(socket, "rejected")
        state = await next_message(socket, "state")

    assert rejected["id"] == "c-2"
    assert "범위" in rejected["reason"]
    assert state["mecha"]["command"]["forward"] == 0


async def test_binary_frames_are_rejected(client):
    async with client.ws_connect("/ws") as socket:
        await socket.send_bytes(b"\x00\x01")
        rejected = await next_message(socket, "rejected")

    assert "JSON" in rejected["reason"]


async def test_oversized_message_closes_connection(client):
    """실패: 명령 크기 한도를 넘는 메시지는 경계에서 끊는다"""
    async with client.ws_connect("/ws") as socket:
        await socket.send_str("x" * (MAX_COMMAND_BYTES + 1))
        async with asyncio.timeout(WAIT_SECONDS):
            while (message := await socket.receive()).type == WSMsgType.TEXT:
                pass

    assert message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING}


async def test_commands_apply_in_sent_order(client):
    """순서: 연달아 보낸 명령은 보낸 순서대로 적용되어 마지막 명령이 남는다"""
    async with client.ws_connect("/ws") as socket:
        for index, up in enumerate([2, 4, 0, 6]):
            await socket.send_json({**FLY, "id": f"c-{index}", "up": up})
        acks = [await next_message(socket, "ack") for _ in range(4)]
        state = await next_message(socket, "state")

    assert [ack["id"] for ack in acks] == ["c-0", "c-1", "c-2", "c-3"]
    assert state["mecha"]["command"]["up"] == 6


async def test_two_clients_receive_state(client):
    """화면과 두뇌처럼 둘이 붙어도 둘 다 상태를 받는다"""
    async with client.ws_connect("/ws") as first, client.ws_connect("/ws") as second:
        assert (await next_message(first, "state"))["type"] == "state"
        assert (await next_message(second, "state"))["type"] == "state"


async def test_reset_to_another_scenario(client):
    """처음으로 되돌리며 시험 장면을 바꾸면 그 장면의 드론으로 상태가 온다"""
    async with client.ws_connect("/ws") as socket:
        await socket.send_json({"type": "reset", "id": "r-1", "scenario": "empty"})
        ack = await next_message(socket, "ack")
        state = await next_message(socket, "state")

    assert ack == {"type": "ack", "id": "r-1", "commandType": "reset", "simTime": 0.0}
    assert state["scenario"] == "empty"
    assert state["units"] == []
