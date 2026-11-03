"""명령 확인: 경계에서 모양과 범위를 보고, 거절하면 보낸 쪽이 고칠 수 있게 까닭을 알린다."""

from __future__ import annotations

import json

import pytest

from robot_sim.commands import (
    AimPoint,
    AimUnit,
    CommandRejectedError,
    Fire,
    Fly,
    Guard,
    LowerAim,
    Push,
    Reset,
    parse_command,
)
from robot_sim.flight import HOLD, FlightCommand
from robot_sim.limits import DEFAULT_LIMITS

FLY = {"type": "velocity", "forward": 0, "sideways": 0, "up": 0, "turn": 0}


def parse(message: dict | str):
    return parse_command(message if isinstance(message, str) else json.dumps(message), DEFAULT_LIMITS)


def test_velocity_command_with_id():
    """비행 속도 명령을 번호와 함께 받는다"""
    command = parse({**FLY, "id": "c-1", "forward": 20, "up": 5, "turn": 0.3})

    assert command == Fly(FlightCommand(20, 0, 5, 0.3), "c-1")


def test_stop_is_hold():
    assert parse({"type": "stop"}) == Fly(HOLD)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ({"type": "aim", "unit": "drone-1"}, AimUnit("drone-1")),
        ({"type": "aimPoint", "point": [100, 0, 30]}, AimPoint((100.0, 0.0, 30.0))),
        ({"type": "lowerAim"}, LowerAim()),
        ({"type": "guard", "raised": True}, Guard(True)),
        ({"type": "guard", "raised": True, "unit": "drone-2"}, Guard(True, "drone-2")),
        ({"type": "fire", "id": "f"}, Fire("f")),
        ({"type": "push", "force": [0, 1_000_000, 0], "durationMs": 200}, Push((0.0, 1_000_000.0, 0.0), 0.2)),
        ({"type": "reset"}, Reset()),
        ({"type": "reset", "scenario": "skirmish"}, Reset("skirmish")),
    ],
    ids=["유닛 겨누기", "점 겨누기", "내리기", "방패", "유닛 쪽 방패", "쏘기", "밀기", "되돌리기", "장면 고르기"],
)
def test_combat_and_test_commands(message, expected):
    assert parse(message) == expected


@pytest.mark.parametrize(("field", "value"), [("forward", 40), ("forward", -15), ("up", 20), ("turn", -1.2)])
def test_values_at_limit_are_accepted(field, value):
    """경계값: 범위 끝 값은 받는다"""
    assert getattr(parse({**FLY, field: value}).flight, field) == value


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ({**FLY, "forward": 40.5}, "앞뒤 속도 40.5"),
        ({**FLY, "sideways": -21}, "옆 속도 -21"),
        ({**FLY, "up": 25}, "오르내리는 속도 25"),
        ({**FLY, "turn": 2}, "도는 속도 2"),
        ({"type": "push", "force": [2_500_000, 2_500_000, 0], "durationMs": 100}, "미는 힘"),
        ({"type": "push", "force": [100, 0, 0], "durationMs": 5}, "미는 시간(ms) 5"),
    ],
    ids=["앞 속도 초과", "옆 속도 초과", "오르기 초과", "돌기 초과", "힘 초과(합)", "너무 짧은 밀기"],
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
        {"type": "velocity", "forward": 0.5, "sideways": 0, "turn": 0},
        {**FLY, "forward": "fast"},
        {**FLY, "extra": 1},
        {"type": "aim"},
        {"type": "guard"},
        {"type": "reset", "scenario": "moon"},
        {"type": "aimPoint", "point": [1, 2]},
        [1, 2, 3],
    ],
    ids=[
        "모르는 명령",
        "오르기 빠짐",
        "숫자가 아님",
        "모르는 필드",
        "겨눌 유닛 빠짐",
        "방패 상태 빠짐",
        "모르는 장면",
        "점이 3개가 아님",
        "객체가 아님",
    ],
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


@pytest.mark.parametrize(
    "text",
    [
        '{"type": "velocity", "forward": NaN, "sideways": 0, "up": 0, "turn": 0}',
        '{"type": "aimPoint", "point": [Infinity, 0, 0]}',
    ],
    ids=["속도 NaN", "점 무한대"],
)
def test_non_finite_numbers_are_rejected(text):
    """실패: JSON의 NaN·Infinity도 숫자로 읽히지만 경계에서 거절한다"""
    with pytest.raises(CommandRejectedError):
        parse(text)


def test_push_just_over_limit_is_rejected_readably():
    """경계값: 크기가 한도를 조금 넘는 밀기는 거절하고, 까닭에 넘은 값을 짧게 적는다"""
    with pytest.raises(CommandRejectedError) as rejected:
        parse({"type": "push", "force": [-2121400, -2121400, 0], "durationMs": 100})

    assert rejected.value.reason == "미는 힘 3.00011e+06이(가) 범위(0 ~ 3e+06)를 벗어났습니다"


def test_rejection_keeps_command_id():
    """거절한 명령의 번호를 알려 보낸 쪽이 어떤 명령인지 안다"""
    with pytest.raises(CommandRejectedError) as rejected:
        parse({**FLY, "id": "c-9", "forward": 300})

    assert rejected.value.command_id == "c-9"
