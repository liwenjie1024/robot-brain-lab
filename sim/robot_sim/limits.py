"""명령 값의 범위. 걷기 정책이 배운 범위(upstream 학습 설정의 명령 범위 ±1)보다 안쪽으로 잡아,
범위 끝에서 걸음이 흐트러져 넘어지는 일을 줄인다. GET /scene의 limits로 그대로 알린다."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Range:
    min: float
    max: float

    def contains(self, value: float) -> bool:
        return self.min <= value <= self.max

    def as_dict(self) -> dict[str, float]:
        return {"min": self.min, "max": self.max}


@dataclass(frozen=True)
class CommandLimits:
    forward: Range = Range(-0.5, 1.0)
    sideways: Range = Range(-0.5, 0.5)
    turn: Range = Range(-1.0, 1.0)
    # 서 있는 G1(약 35kg)을 크게 흔들되 시험 장치가 로봇을 날려 보내지는 않을 만큼
    push_force: Range = Range(0.0, 400.0)
    push_duration_ms: Range = Range(10.0, 1000.0)

    def as_dict(self) -> dict[str, dict[str, float]]:
        return {
            "forward": self.forward.as_dict(),
            "sideways": self.sideways.as_dict(),
            "turn": self.turn.as_dict(),
            "pushForce": self.push_force.as_dict(),
            "pushDurationMs": self.push_duration_ms.as_dict(),
        }


DEFAULT_LIMITS = CommandLimits()
