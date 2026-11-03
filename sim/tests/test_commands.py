"""명령 확인: 경계에서 모양과 범위를 보고, 거절하면 보낸 쪽이 고칠 수 있게 까닭을 알린다."""

from __future__ import annotations

import json

import pytest

from robot_sim.commands import CommandRejectedError, Push, Reset, SetVelocity, parse_command
from robot_sim.limits import DEFAULT_LIMITS
from robot_sim.locomotion import STANDING_STILL, Velocity


def parse(message: dict | str):
    return parse_command(message if isinstance(message, str) else json.dumps(message), DEFAULT_LIMITS)


def test_velocity_command_with_id():
    """걷기 속도 명령을 번호와 함께 받는다"""
    command = parse({"type": "velocity", "id": "c-1", "forward": 0.5, "sideways": -0.2, "turn": 0.3})

    assert command == SetVelocity(Velocity(0.5, -0.2, 0.3), "c-1")


def test_stop_is_zero_velocity():
    """멈춤은 속도 0 명령이다"""
    assert parse({"type": "stop"}) == SetVelocity(STANDING_STILL)


def test_push_converts_milliseconds():
    """밀기 시간은 ms로 받아 초로 바꾼다"""
    command = parse({"type": "push", "force": [0, 150, 0], "durationMs": 100})

    assert command == Push((0.0, 150.0, 0.0), 0.1)


def test_reset():
    assert parse({"type": "reset", "id": "r"}) == Reset("r")


@pytest.mark.parametrize("forward", [-0.5, 1.0], ids=["가장 느린 뒤", "가장 빠른 앞"])
def test_velocity_at_limit_is_accepted(forward):
    """경계값: 범위 끝 값은 받는다"""
    assert parse({"type": "velocity", "forward": forward, "sideways": 0, "turn": 0}).velocity.forward == forward


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ({"type": "velocity", "forward": 1.01, "sideways": 0, "turn": 0}, "앞뒤 속도 1.01"),
        ({"type": "velocity", "forward": 0, "sideways": 0.6, "turn": 0}, "옆 속도 0.6"),
        ({"type": "velocity", "forward": 0, "sideways": 0, "turn": -1.5}, "도는 속도 -1.5"),
        ({"type": "push", "force": [300, 300, 0], "durationMs": 100}, "미는 힘"),
        ({"type": "push", "force": [100, 0, 0], "durationMs": 5}, "미는 시간(ms) 5"),
    ],
    ids=["앞 속도 초과", "옆 속도 초과", "도는 속도 초과", "힘 초과(합)", "너무 짧은 밀기"],
)
def test_out_of_range_values_are_rejected_with_reason(message, reason):
    """범위를 벗어난 값은 잘라 쓰지 않고 거절한다 (두뇌의 실수가 드러나게)"""
    with pytest.raises(CommandRejectedError) as rejected:
        parse(message)

    assert reason in rejected.value.reason
    assert "범위" in rejected.value.reason


@pytest.mark.parametrize(
    "message",
    [
        {"type": "fly"},
        {"type": "velocity", "forward": 0.5},
        {"type": "velocity", "forward": "fast", "sideways": 0, "turn": 0},
        {"type": "velocity", "forward": 0, "sideways": 0, "turn": 0, "extra": 1},
        {"type": "push", "force": [1, 2], "durationMs": 100},
        [1, 2, 3],
    ],
    ids=["모르는 명령", "빠진 값", "숫자가 아님", "모르는 필드", "힘이 3개가 아님", "객체가 아님"],
)
def test_malformed_commands_are_rejected(message):
    """모양이 틀린 명령은 거절한다"""
    with pytest.raises(CommandRejectedError) as rejected:
        parse(message)

    assert rejected.value.reason.startswith("명령 모양이 맞지 않습니다")


def test_not_json_is_rejected():
    with pytest.raises(CommandRejectedError) as rejected:
        parse("{앞으로")

    assert rejected.value.reason.startswith("JSON이 아닙니다")


def test_nan_speed_is_rejected():
    """실패: JSON의 NaN도 숫자로 읽히지만 범위 확인에서 거절한다"""
    with pytest.raises(CommandRejectedError):
        parse('{"type": "velocity", "forward": NaN, "sideways": 0, "turn": 0}')


def test_push_just_over_limit_is_rejected_readably():
    """경계값: 크기가 한도를 조금 넘는 밀기(400.02N)는 거절하고, 까닭에 넘은 값을 짧게 적는다"""
    with pytest.raises(CommandRejectedError) as rejected:
        parse({"type": "push", "force": [-282.9, -282.9, 0], "durationMs": 100})

    assert rejected.value.reason == "미는 힘 400.081이(가) 범위(0 ~ 400)를 벗어났습니다"


def test_rejection_keeps_command_id():
    """거절한 명령의 번호를 알려 보낸 쪽이 어떤 명령인지 안다"""
    with pytest.raises(CommandRejectedError) as rejected:
        parse({"type": "velocity", "id": "c-9", "forward": 3, "sideways": 0, "turn": 0})

    assert rejected.value.command_id == "c-9"
