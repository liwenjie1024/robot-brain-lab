"""서버: 실제로 띄워 화면·두뇌가 쓰는 방식 그대로 묻고 명령한다."""

from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from robot_sim.limits import DEFAULT_LIMITS
from robot_sim.scene import MESH_HEADER
from robot_sim.server import MAX_COMMAND_BYTES, create_app

WAIT_SECONDS = 5.0


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


async def test_scene_and_meshes_are_served(client):
    """화면은 /scene으로 모양을 받고 /meshes/{id}로 메시를 받는다"""
    scene = await (await client.get("/scene")).json()
    mesh_id = next(geom["mesh"] for geom in scene["geoms"] if geom["shape"] == "mesh")
    mesh = await client.get(f"/meshes/{mesh_id}")

    body = await mesh.read()
    vertices, _ = MESH_HEADER.unpack_from(body)
    assert scene["robot"]["name"].startswith("Unitree G1")
    assert vertices == next(m["vertexCount"] for m in scene["meshes"] if m["id"] == mesh_id)


async def test_unknown_mesh_is_404(client):
    assert (await client.get("/meshes/999")).status == 404
    assert (await client.get("/meshes/abc")).status == 404


async def test_streams_state_in_order(client, simulation):
    """연결하면 제어 주기마다 상태가 순서대로 온다"""
    async with client.ws_connect("/ws") as socket:
        first = await next_message(socket, "state")
        second = await next_message(socket, "state")

    assert second["seq"] > first["seq"]
    assert second["simTime"] > first["simTime"]
    assert len(first["bodies"]) == 13 * 7
    assert first["robot"]["posture"] == "standing"


async def test_velocity_command_is_acknowledged_and_followed(client):
    """걷기 명령을 보내면 번호로 받았다고 알리고, 상태의 명령 값이 바뀐다"""
    async with client.ws_connect("/ws") as socket:
        await socket.send_json({"type": "velocity", "id": "c-1", "forward": 0.5, "sideways": 0, "turn": 0})
        ack = await next_message(socket, "ack")
        state = await next_message(socket, "state")

    assert ack["id"] == "c-1"
    assert ack["commandType"] == "velocity"
    assert state["robot"]["command"] == {"forward": 0.5, "sideways": 0.0, "turn": 0.0}


async def test_invalid_command_is_rejected_without_stopping_stream(client):
    """실패: 틀린 명령은 까닭과 함께 거절하고, 연결과 상태 보내기는 계속된다"""
    async with client.ws_connect("/ws") as socket:
        await socket.send_json({"type": "velocity", "id": "c-2", "forward": 9, "sideways": 0, "turn": 0})
        rejected = await next_message(socket, "rejected")
        state = await next_message(socket, "state")

    assert rejected["id"] == "c-2"
    assert "범위" in rejected["reason"]
    assert state["robot"]["command"]["forward"] == 0.0


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
        for index, forward in enumerate([0.2, 0.4, 0.0, 0.6]):
            command = {"type": "velocity", "id": f"c-{index}", "forward": forward, "sideways": 0, "turn": 0}
            await socket.send_json(command)
        acks = [await next_message(socket, "ack") for _ in range(4)]
        state = await next_message(socket, "state")

    assert [ack["id"] for ack in acks] == ["c-0", "c-1", "c-2", "c-3"]
    assert state["robot"]["command"]["forward"] == 0.6


async def test_two_clients_receive_state(client):
    """화면과 두뇌처럼 둘이 붙어도 둘 다 상태를 받는다"""
    async with client.ws_connect("/ws") as first, client.ws_connect("/ws") as second:
        assert (await next_message(first, "state"))["type"] == "state"
        assert (await next_message(second, "state"))["type"] == "state"


async def test_reset_command(client):
    async with client.ws_connect("/ws") as socket:
        await socket.send_json({"type": "reset", "id": "r-1"})
        ack = await next_message(socket, "ack")

    assert ack == {"type": "ack", "id": "r-1", "commandType": "reset", "simTime": 0.0}
