"""전투의 공통 부분: 맞힐 수 있는 것(유닛)과 체력, 사격 광선, 사건(사격·격파)."""

from __future__ import annotations

from dataclasses import dataclass, field

import mujoco
import numpy as np

from .drones import DRONE_MAX_HP, MAX_DRONES, drone_body_name, drone_id
from .mecha import MECHA_NAME, ROOT_BODY, SHIELD_GEOM

MECHA_ID = "mecha"
MECHA_MAX_HP = 1000.0
GROUP_COUNT = 6


@dataclass
class Unit:
    id: str
    kind: str
    name: str
    body: int
    max_hp: float
    hp: float
    active: bool = True

    @property
    def alive(self) -> bool:
        return self.active and self.hp > 0


@dataclass(frozen=True)
class Hit:
    unit: str
    damage: float
    blocked: bool

    def as_dict(self) -> dict:
        return {"unit": self.unit, "damage": self.damage, "blocked": self.blocked}


@dataclass(frozen=True)
class ShotEvent:
    shooter: str
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    hit: Hit | None
    sim_time: float

    def as_message(self) -> dict:
        message = {
            "type": "shot",
            "simTime": self.sim_time,
            "shooter": self.shooter,
            "from": list(self.start),
            "to": list(self.end),
        }
        if self.hit is not None:
            message["hit"] = self.hit.as_dict()
        return message


@dataclass(frozen=True)
class DestroyedEvent:
    unit: str
    sim_time: float

    def as_message(self) -> dict:
        return {"type": "destroyed", "simTime": self.sim_time, "unit": self.unit}


Event = ShotEvent | DestroyedEvent


@dataclass
class Units:
    """기체와 드론의 체력. 몸체 번호로 맞은 유닛을 찾는다."""

    model: mujoco.MjModel
    all: dict[str, Unit] = field(default_factory=dict)

    def __post_init__(self) -> None:
        mecha_body = self.model.body(ROOT_BODY).id
        self.all[MECHA_ID] = Unit(MECHA_ID, "mecha", MECHA_NAME, mecha_body, MECHA_MAX_HP, MECHA_MAX_HP)
        for index in range(MAX_DRONES):
            body = self.model.body(drone_body_name(index)).id
            name = f"표적 드론 {index + 1}"
            self.all[drone_id(index)] = Unit(drone_id(index), "drone", name, body, DRONE_MAX_HP, DRONE_MAX_HP, False)
        self._by_root = {unit.body: unit for unit in self.all.values()}
        self._shield_geom = self.model.geom(SHIELD_GEOM).id

    @property
    def mecha(self) -> Unit:
        return self.all[MECHA_ID]

    def get(self, unit_id: str) -> Unit | None:
        return self.all.get(unit_id)

    def drones(self) -> list[Unit]:
        return [unit for unit in self.all.values() if unit.kind == "drone"]

    def reset(self, active_drones: set[str]) -> None:
        for unit in self.all.values():
            unit.hp = unit.max_hp
            unit.active = unit.kind == "mecha" or unit.id in active_drones

    def of_geom(self, geom: int) -> Unit | None:
        return self._by_root.get(int(self.model.body_rootid[self.model.geom_bodyid[geom]]))

    def is_shield(self, geom: int) -> bool:
        return geom == self._shield_geom

    def damage(self, unit: Unit, amount: float) -> bool:
        """맞혔다. 이번에 체력이 다해 파괴되었으면 True."""
        was_alive = unit.alive
        unit.hp = max(0.0, unit.hp - amount)
        return was_alive and not unit.alive


def ray_groups(*groups: int) -> np.ndarray:
    mask = np.zeros(GROUP_COUNT, dtype=np.uint8)
    mask[list(groups)] = 1
    return mask


def cast(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    start: np.ndarray,
    direction: np.ndarray,
    *,
    groups: np.ndarray,
    max_range: float,
) -> tuple[np.ndarray, int | None]:
    """광선이 처음 닿는 곳. 사거리 안에 아무것도 없으면 사거리 끝과 None."""
    unit_direction = direction / np.linalg.norm(direction)
    geom = np.zeros(1, dtype=np.int32)
    distance = mujoco.mj_ray(model, data, start, unit_direction, groups, 1, -1, geom)
    if distance < 0 or distance > max_range:
        return start + unit_direction * max_range, None
    return start + unit_direction * distance, int(geom[0])
