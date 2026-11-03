"""운동 제어(System 0): 미리 학습된 걷기 정책이 이 시뮬레이터에서 명령대로 걷고 버티는지."""

from __future__ import annotations

import math

import numpy as np
import pytest

from robot_sim.locomotion import STANDING_STILL, BodySense, Velocity, gravity_in_body
from tests.conftest import run_for


def test_stands_in_place_without_falling(simulation):
    """멈춤 명령이면 5초 동안 넘어지지 않고 제자리 근처에 있다"""
    fell = run_for(simulation, 5.0, STANDING_STILL)

    status = simulation.status()
    assert not fell
    assert math.hypot(status.position[0], status.position[1]) < 0.3


def test_walks_forward_at_commanded_speed(simulation):
    """앞으로 0.5m/s면 넘어지지 않고 그 속도 가까이로 앞으로 간다"""
    run_for(simulation, 1.0, STANDING_STILL)
    start_x = simulation.status().position[0]

    fell = run_for(simulation, 5.0, Velocity(0.5, 0.0, 0.0))

    status = simulation.status()
    assert not fell
    assert status.position[0] - start_x > 1.8
    assert status.velocity.forward == pytest.approx(0.5, abs=0.15)


def test_turns_left_at_commanded_rate(simulation):
    """왼쪽으로 0.8rad/s면 제자리에서 왼쪽으로 돈다"""
    fell = run_for(simulation, 3.0, Velocity(0.0, 0.0, 0.8))

    status = simulation.status()
    assert not fell
    assert status.yaw > 1.5
    assert status.velocity.turn == pytest.approx(0.8, abs=0.2)


@pytest.mark.parametrize(
    ("command", "axis", "sign"),
    [
        (Velocity(-0.5, 0.0, 0.0), 0, -1),
        (Velocity(0.0, 0.5, 0.0), 1, 1),
        (Velocity(0.0, -0.5, 0.0), 1, -1),
    ],
    ids=["뒤로", "왼쪽으로", "오른쪽으로"],
)
def test_walks_backward_and_sideways(simulation, command, axis, sign):
    """뒤·옆으로 걷는 명령도 넘어지지 않고 그쪽으로 간다"""
    fell = run_for(simulation, 4.0, command)

    assert not fell
    assert sign * simulation.status().position[axis] > 0.8


def test_fastest_allowed_forward_speed_keeps_balance(simulation):
    """경계값: 허용한 가장 빠른 앞 속도(1.0m/s)로도 넘어지지 않는다"""
    fell = run_for(simulation, 5.0, Velocity(1.0, 0.0, 0.0))

    assert not fell
    assert simulation.status().velocity.forward > 0.7


@pytest.mark.parametrize(
    "force", [(150, 0, 0), (-150, 0, 0), (0, 150, 0), (0, -150, 0)], ids=["앞", "뒤", "왼쪽", "오른쪽"]
)
def test_recovers_from_moderate_push(simulation, force):
    """150N으로 0.1초 밀어도 버티고 다시 선다"""
    run_for(simulation, 2.0, STANDING_STILL)

    simulation.push(force, 0.1)
    fell = run_for(simulation, 3.0)

    assert not fell


def test_strong_push_is_reported_as_fallen(simulation):
    """실패: 400N으로 0.2초 밀면 넘어지고, 상태가 넘어짐으로 바뀐다"""
    run_for(simulation, 2.0, STANDING_STILL)

    simulation.push((400, 0, 0), 0.2)
    fell = run_for(simulation, 3.0)

    assert fell
    assert simulation.status().fallen


def test_push_ends_after_its_duration(simulation):
    """밀기는 정한 시간이 지나면 저절로 풀린다"""
    simulation.push((100, 0, 0), 0.1)
    assert simulation.status().pushing

    run_for(simulation, 0.2)

    assert not simulation.status().pushing
    assert not simulation.data.xfrc_applied.any()


def test_reset_returns_to_start_and_clears_memory(simulation):
    """처음으로 되돌리면 넘어진 로봇도 처음 자세로 서고, 같은 명령이면 같은 결과가 나온다"""
    first = run_for(simulation, 3.0, Velocity(0.5, 0.0, 0.0))
    first_position = simulation.status().position
    simulation.push((400, 0, 0), 0.2)
    run_for(simulation, 2.0)

    simulation.reset()
    assert not simulation.status().fallen
    assert simulation.sim_time == 0
    second = run_for(simulation, 3.0, Velocity(0.5, 0.0, 0.0))

    assert first == second
    assert simulation.status().position == pytest.approx(first_position, abs=1e-6)


def test_observation_matches_trained_layout(simulation):
    """관측 값은 정책이 배운 길이(47)이고, 똑바로 서 있으면 중력이 몸 아래쪽(-z)을 향한다"""
    config = simulation.controller.config
    sense = BodySense(
        base_quaternion=np.array([1.0, 0.0, 0.0, 0.0]),
        base_angular_velocity=np.zeros(3, dtype=np.float32),
        joint_positions=config.default_angles.copy(),
        joint_velocities=np.zeros(config.num_actions, dtype=np.float32),
    )

    observation = simulation.controller.observation(Velocity(0.5, 0.0, 0.0), sense, 0.0)

    assert observation.shape == (config.num_obs,)
    assert observation[3:6] == pytest.approx([0.0, 0.0, -1.0])
    assert observation[6] == pytest.approx(0.5 * config.cmd_scale[0])
    assert observation[-2:] == pytest.approx([0.0, 1.0])


def test_gravity_points_sideways_when_lying_on_side():
    """옆으로 90도 누우면 중력이 몸의 옆쪽을 향한다 (넘어짐 판정의 바탕)"""
    half = math.sqrt(0.5)

    gravity = gravity_in_body(np.array([half, half, 0.0, 0.0]))

    assert gravity == pytest.approx([0.0, -1.0, 0.0], abs=1e-6)
