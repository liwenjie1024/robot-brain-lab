"""표적 드론: 시험장에서 기체가 맞히고 피할 상대.

시험 대상이 아니라 시험 장치라서, 추진기를 흉내 내지 않고 몸통에 힘을 바로 걸어 정한 길을 따라가게 한다.
모델의 드론 수는 늘 MAX_DRONES로 고정하고(화면이 받는 모양이 바뀌지 않게), 장면에서 쓰지 않는 드론은
시험장 밖에 세워 둔다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import mujoco
import numpy as np

from .mecha import DRONE_BIT, DRONE_GROUP, MECHA_BIT, WORLD_BIT

MAX_DRONES = 4
DRONE_RADIUS_M = 1.6
DRONE_MASS_KG = 1500.0
DRONE_MAX_HP = 60.0
# 쓰지 않는 드론을 세워 두는 곳 (시험장 밖, 서로 겹치지 않게 x로 벌린다)
PARK_ORIGIN = (3000.0, 3000.0, 200.0)
PARK_SPACING_M = 20.0
GRAVITY = 9.81
POSITION_GAIN = 1.2
VELOCITY_GAIN = 2.0
MAX_ACCELERATION = 12.0
ATTITUDE_GAIN = 6.0
SPIN_DAMPING = 3.0

DRONE_COLORS = {
    "core": [0.2, 0.22, 0.26, 1.0],
    "ring": [0.55, 0.12, 0.12, 1.0],
    "eye": [1.0, 0.25, 0.2, 1.0],
}


def drone_id(index: int) -> str:
    return f"drone-{index + 1}"


def drone_body_name(index: int) -> str:
    return f"drone_{index + 1}"


def park_position(index: int) -> tuple[float, float, float]:
    x, y, z = PARK_ORIGIN
    return (x + index * PARK_SPACING_M, y, z)


def add_drone(spec: mujoco.MjSpec, index: int) -> None:
    body = spec.worldbody.add_body(name=drone_body_name(index), pos=list(park_position(index)))
    body.add_freejoint(name=f"{drone_body_name(index)}_root")
    common = {"group": DRONE_GROUP, "contype": DRONE_BIT, "conaffinity": WORLD_BIT | MECHA_BIT}
    body.add_geom(
        type=mujoco.mjtGeom.mjGEOM_SPHERE,
        size=[DRONE_RADIUS_M, 0, 0],
        mass=DRONE_MASS_KG * 0.8,
        rgba=DRONE_COLORS["core"],
        **common,
    )
    body.add_geom(
        type=mujoco.mjtGeom.mjGEOM_CYLINDER,
        size=[DRONE_RADIUS_M * 1.6, 0.2, 0],
        mass=DRONE_MASS_KG * 0.15,
        rgba=DRONE_COLORS["ring"],
        **common,
    )
    body.add_geom(
        type=mujoco.mjtGeom.mjGEOM_SPHERE,
        size=[0.5, 0, 0],
        pos=[DRONE_RADIUS_M, 0, 0],
        mass=DRONE_MASS_KG * 0.05,
        rgba=DRONE_COLORS["eye"],
        **common,
    )


@dataclass(frozen=True)
class DronePlan:
    """장면에서 드론 하나가 할 일. orbit_radius가 0이면 제자리에 떠 있다."""

    home: tuple[float, float, float]
    orbit_radius: float = 0.0
    orbit_speed: float = 0.0
    orbit_phase: float = 0.0
    armed: bool = False

    def target_at(self, time: float) -> tuple[np.ndarray, np.ndarray]:
        """이 시각에 있어야 할 위치와 속도"""
        home = np.array(self.home)
        if self.orbit_radius <= 0 or self.orbit_speed == 0:
            return home, np.zeros(3)
        rate = self.orbit_speed / self.orbit_radius
        angle = self.orbit_phase + rate * time
        offset = np.array([math.cos(angle), math.sin(angle), 0.0]) * self.orbit_radius
        velocity = np.array([-math.sin(angle), math.cos(angle), 0.0]) * self.orbit_speed
        return home + offset, velocity


class DronePilot:
    """드론 하나를 정한 길로 움직이는 힘. 파괴되면 힘을 끊어 떨어지게 한다."""

    def __init__(self, model: mujoco.MjModel, index: int) -> None:
        self.body = model.body(drone_body_name(index)).id
        joint = model.body_jntadr[self.body]
        self._qvel = model.jnt_dofadr[joint]
        self._mass = float(model.body_subtreemass[self.body])
        self._inertia = float(np.mean(model.body_inertia[self.body]))
        self._index = index

    def apply(self, data: mujoco.MjData, plan: DronePlan | None, alive: bool, time: float) -> None:
        wrench = data.xfrc_applied[self.body]
        if not alive:
            wrench[:] = 0
            return
        target, target_velocity = plan.target_at(time) if plan else (np.array(park_position(self._index)), np.zeros(3))
        position = data.xpos[self.body]
        velocity = data.qvel[self._qvel : self._qvel + 3]
        acceleration = POSITION_GAIN * (target - position) + VELOCITY_GAIN * (target_velocity - velocity)
        norm = np.linalg.norm(acceleration)
        if norm > MAX_ACCELERATION:
            acceleration *= MAX_ACCELERATION / norm
        wrench[:3] = self._mass * (acceleration + np.array([0.0, 0.0, GRAVITY]))
        # 똑바로 떠 있게: 몸의 위쪽 축을 세계 위로 돌리고 도는 것을 줄인다.
        up = data.xmat[self.body].reshape(3, 3)[:, 2]
        tilt = np.cross(up, np.array([0.0, 0.0, 1.0]))
        spin = data.qvel[self._qvel + 3 : self._qvel + 6]
        world_spin = data.xmat[self.body].reshape(3, 3) @ spin
        wrench[3:] = self._inertia * (ATTITUDE_GAIN * tilt - SPIN_DAMPING * world_spin)
