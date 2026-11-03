"""몸에 보내는 명령을 경계에서 확인한다. 모양은 contracts/sim/command.schema.json으로, 값의 범위는 limits로 본다.
안쪽 코드는 여기서 만든 명령 객체만 다룬다."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import jsonschema

from .limits import CommandLimits, Range
from .locomotion import STANDING_STILL, Velocity

DEFAULT_CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"
COMMAND_SCHEMA = Path("sim") / "command.schema.json"
MILLIS_PER_SECOND = 1000.0


@dataclass(frozen=True)
class SetVelocity:
    velocity: Velocity
    id: str | None = None
    type: str = "velocity"


@dataclass(frozen=True)
class Push:
    force: tuple[float, float, float]
    duration_s: float
    id: str | None = None
    type: str = "push"


@dataclass(frozen=True)
class Reset:
    id: str | None = None
    type: str = "reset"


Command = SetVelocity | Push | Reset


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

    match raw["type"]:
        case "velocity":
            velocity = Velocity(raw["forward"], raw["sideways"], raw["turn"])
            _require_within("앞뒤 속도", velocity.forward, limits.forward, command_id)
            _require_within("옆 속도", velocity.sideways, limits.sideways, command_id)
            _require_within("도는 속도", velocity.turn, limits.turn, command_id)
            return SetVelocity(velocity, command_id)
        case "stop":
            return SetVelocity(STANDING_STILL, command_id)
        case "push":
            force = tuple(float(value) for value in raw["force"])
            _require_within("미는 힘", math.hypot(*force), limits.push_force, command_id)
            _require_within("미는 시간(ms)", raw["durationMs"], limits.push_duration_ms, command_id)
            return Push((force[0], force[1], force[2]), raw["durationMs"] / MILLIS_PER_SECOND, command_id)
        case "reset":
            return Reset(command_id)
        case other:
            raise CommandRejectedError(f"모르는 명령입니다: {other}", command_id)


def _require_within(label: str, value: float, allowed: Range, command_id: str | None) -> None:
    if not math.isfinite(value) or not allowed.contains(value):
        # 유효 숫자 6자리: 범위를 조금 넘은 값(400.018)도 넘었다는 것이 보이면서 길지 않게
        raise CommandRejectedError(
            f"{label} {value:.6g}이(가) 범위({allowed.min:g} ~ {allowed.max:g})를 벗어났습니다", command_id
        )
