"""명령 값의 범위. 비행 제어가 기체를 똑바로 세운 채 따라갈 수 있는 범위다 (실제로 날려 보고 정함,
docs/architecture.md). GET /scene의 limits로 그대로 알린다."""

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
    forward: Range = Range(-15.0, 40.0)
    sideways: Range = Range(-20.0, 20.0)
    up: Range = Range(-15.0, 20.0)
    turn: Range = Range(-1.2, 1.2)
    # 약 37t 기체를 크게 흔드는 충격 (맞았을 때를 흉내 낸다)
    push_force: Range = Range(0.0, 3_000_000.0)
    push_duration_ms: Range = Range(10.0, 1000.0)

    def as_dict(self) -> dict[str, dict[str, float]]:
        return {
            "forward": self.forward.as_dict(),
            "sideways": self.sideways.as_dict(),
            "up": self.up.as_dict(),
            "turn": self.turn.as_dict(),
            "pushForce": self.push_force.as_dict(),
            "pushDurationMs": self.push_duration_ms.as_dict(),
        }


DEFAULT_LIMITS = CommandLimits()
