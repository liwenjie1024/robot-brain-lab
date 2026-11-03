"""규약: 몸이 실제로 내보내는 메시지·모델 설명이 contracts/sim의 스키마에 맞는지 (화면·두뇌가 이 스키마로 검증한다)."""

from __future__ import annotations

import json

import jsonschema
import numpy as np
import pytest

from robot_sim.commands import DEFAULT_CONTRACTS_DIR, AimUnit, CommandRejectedError, Fire, Reset
from robot_sim.limits import DEFAULT_LIMITS
from robot_sim.runner import RealtimeRunner, rejected_message
from robot_sim.scene import describe, moving_bodies
from tests.conftest import take_off, ticks_until


def validator(name: str) -> jsonschema.Draft202012Validator:
    schema = json.loads((DEFAULT_CONTRACTS_DIR / "sim" / f"{name}.schema.json").read_text("utf-8"))
    return jsonschema.Draft202012Validator(schema)


@pytest.fixture
def messages(simulation):
    """실제 진행에서 나온 메시지를 모은다 (JSON으로 한 번 오가게 해 보내는 모양 그대로)"""
    collected: list[dict] = []

    def keep(message: dict) -> None:
        collected.append(json.loads(json.dumps(message)))

    runner = RealtimeRunner(simulation, moving_bodies(simulation.model), keep, keep)
    return runner, collected


def test_state_and_combat_messages_match_schema(simulation, messages):
    runner, collected = messages
    simulation.apply(Reset("skirmish"))
    take_off(simulation)
    simulation.apply(AimUnit("drone-1"))
    ticks_until(simulation, lambda: simulation.mecha_status()["weapon"]["aimError"] < 0.5, 3.0)
    simulation.apply(Fire())
    for _ in range(200):
        runner.tick()

    message_validator = validator("message")
    kinds = {message["type"] for message in collected}
    for message in collected:
        message_validator.validate(message)
    assert {"state", "shot"} <= kinds
    assert any(message["type"] == "state" and message["threats"] for message in collected)


def test_destroyed_event_matches_schema(simulation, messages):
    runner, collected = messages
    unit = simulation.units.get("drone-1")
    simulation.units.damage(unit, unit.max_hp - 1)
    take_off(simulation)
    simulation.apply(AimUnit("drone-1"))
    while unit.alive:
        ticks_until(simulation, lambda: simulation.mecha_status()["weapon"]["aimError"] < 0.5, 3.0)
        try:
            simulation.apply(Fire())
        except CommandRejectedError:
            continue
        runner.tick()

    destroyed = [message for message in collected if message["type"] == "destroyed"]
    assert len(destroyed) == 1
    validator("message").validate(destroyed[0])


def test_replies_match_schema():
    message_validator = validator("message")
    message_validator.validate({"type": "ack", "id": "c-1", "commandType": "fire", "simTime": 1.5})
    message_validator.validate(rejected_message("소총이 아직 식는 중입니다", "c-2"))
    message_validator.validate(rejected_message("JSON이 아닙니다", None))


def test_scene_description_matches_schema(simulation):
    rates = {"physicsHz": 500.0, "controlHz": 50.0, "stateHz": 50.0}
    scene = json.loads(json.dumps(describe(simulation.model, simulation.units, DEFAULT_LIMITS, rates)))

    validator("scene").validate(scene)


def test_state_bodies_follow_scene_order(simulation, messages):
    """상태의 몸체 자세는 모델 설명의 movingBodies 순서로 7개씩이다"""
    runner, collected = messages
    runner.tick()
    state = next(message for message in collected if message["type"] == "state")

    poses = np.array(state["bodies"]).reshape(-1, 7)
    bodies = moving_bodies(simulation.model)
    assert len(poses) == len(bodies)
    assert poses[0][:3] == pytest.approx(simulation.data.xpos[bodies[0]], abs=1e-3)
