"""몸에 보내는 명령을 경계에서 확인한다. 모양은 contracts/sim/command.schema.json으로, 값의 범위는 limits로 본다.
안쪽 코드는 여기서 만든 명령 객체만 다룬다.
지금 상태 때문에 못 하는 명령(쏠 준비가 안 됨 등)은 시뮬레이션이 거절한다."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import jsonschema

from .flight import HOLD, FlightCommand
from .limits import CommandLimits, Range
from .scenarios import SCENARIOS

DEFAULT_CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"
COMMAND_SCHEMA = Path("sim") / "command.schema.json"
MILLIS_PER_SECOND = 1000.0


@dataclass(frozen=True)
class Fly:
    flight: FlightCommand
    id: str | None = None
    type: str = "velocity"


@dataclass(frozen=True)
class AimUnit:
    unit: str
    id: str | None = None
    type: str = "aim"


@dataclass(frozen=True)
class AimPoint:
    point: tuple[float, float, float]
    id: str | None = None
    type: str = "aimPoint"


@dataclass(frozen=True)
class LowerAim:
    id: str | None = None
    type: str = "lowerAim"


@dataclass(frozen=True)
class Guard:
    raised: bool
    unit: str | None = None
    id: str | None = None
    type: str = "guard"


@dataclass(frozen=True)
class Fire:
    id: str | None = None
    type: str = "fire"


@dataclass(frozen=True)
class Push:
    force: tuple[float, float, float]
    duration_s: float
    id: str | None = None
    type: str = "push"


@dataclass(frozen=True)
class Reset:
    scenario: str | None = None
    id: str | None = None
    type: str = "reset"


Command = Fly | AimUnit | AimPoint | LowerAim | Guard | Fire | Push | Reset


class CommandRejectedError(ValueError):
    """명령을 받을 수 없다. 메시지는 보낸 쪽에 그대로 알린다."""

    def __init__(self, reason: str, command_id: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.command_id = command_id


@cache
def _validator() -> jsonschema.Draft202012Validator:
    contracts_dir = Path(os.environ.get("CONTRACTS_DIR", DEFAULT_CONTRACTS_DIR))
    schema = json.loads((contracts_dir / COMMAND_SCHEMA).read_text("utf-8"))
    return jsonschema.Draft202012Validator(schema)


def parse_command(text: str, limits: CommandLimits) -> Command:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise CommandRejectedError(f"JSON이 아닙니다: {error.msg}") from error
    command_id = raw.get("id") if isinstance(raw, dict) and isinstance(raw.get("id"), str) else None
    error = jsonschema.exceptions.best_match(_validator().iter_errors(raw))
    if error is not None:
        raise CommandRejectedError(f"명령 모양이 맞지 않습니다: {error.message}", command_id)

    parser = _PARSERS.get(raw["type"])
    if parser is None:
        raise CommandRejectedError(f"모르는 명령입니다: {raw['type']}", command_id)
    return parser(raw, limits, command_id)


def _velocity(raw: dict, limits: CommandLimits, command_id: str | None) -> Command:
    flight = FlightCommand(raw["forward"], raw["sideways"], raw["up"], raw["turn"])
    _require_within("앞뒤 속도", flight.forward, limits.forward, command_id)
    _require_within("옆 속도", flight.sideways, limits.sideways, command_id)
    _require_within("오르내리는 속도", flight.up, limits.up, command_id)
    _require_within("도는 속도", flight.turn, limits.turn, command_id)
    return Fly(flight, command_id)


def _push(raw: dict, limits: CommandLimits, command_id: str | None) -> Command:
    force = _finite_vector(raw["force"], "미는 힘", command_id)
    _require_within("미는 힘", math.hypot(*force), limits.push_force, command_id)
    _require_within("미는 시간(ms)", raw["durationMs"], limits.push_duration_ms, command_id)
    return Push(force, raw["durationMs"] / MILLIS_PER_SECOND, command_id)


def _reset(raw: dict, _limits: CommandLimits, command_id: str | None) -> Command:
    scenario = raw.get("scenario")
    if scenario is not None and scenario not in SCENARIOS:
        raise CommandRejectedError(f"모르는 시험 장면입니다: {scenario}", command_id)
    return Reset(scenario, command_id)


# 모양은 스키마로 이미 확인했다. 여기서는 값의 범위와 객체 만들기만 한다.
_PARSERS: dict[str, Callable[[dict, CommandLimits, str | None], Command]] = {
    "velocity": _velocity,
    "stop": lambda _raw, _limits, command_id: Fly(HOLD, command_id),
    "aim": lambda raw, _limits, command_id: AimUnit(raw["unit"], command_id),
    "aimPoint": lambda raw, _limits, command_id: AimPoint(
        _finite_vector(raw["point"], "겨눌 점", command_id), command_id
    ),
    "lowerAim": lambda _raw, _limits, command_id: LowerAim(command_id),
    "guard": lambda raw, _limits, command_id: Guard(raw["raised"], raw.get("unit"), command_id),
    "fire": lambda _raw, _limits, command_id: Fire(command_id),
    "push": _push,
    "reset": _reset,
}


def _finite_vector(values: list[float], label: str, command_id: str | None) -> tuple[float, float, float]:
    vector = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in vector):
        raise CommandRejectedError(f"{label}에 숫자가 아닌 값이 있습니다", command_id)
    return (vector[0], vector[1], vector[2])


def _require_within(label: str, value: float, allowed: Range, command_id: str | None) -> None:
    if not math.isfinite(value) or not allowed.contains(value):
        # 유효 숫자 6자리: 범위를 조금 넘은 값(400.018)도 넘었다는 것이 보이면서 길지 않게
        raise CommandRejectedError(
            f"{label} {value:.6g}이(가) 범위({allowed.min:g} ~ {allowed.max:g})를 벗어났습니다", command_id
        )
