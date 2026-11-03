"""시험장 모델: 바닥 + 기체 + 표적 드론 자리(MAX_DRONES개).

두 번 만든다. 처음 만든 모델로 기체의 무게 중심·질량·관성을 재고, 추진기 힘이 걸리는 점을 무게 중심으로 옮기고
추진기 힘 한도를 질량에 맞춘 뒤 다시 만든다 (기체 모양을 바꿔도 손으로 값을 고치지 않게).
"""

from __future__ import annotations

import mujoco

from .drones import MAX_DRONES, add_drone
from .flight import MassProperties, thruster_ranges
from .mecha import (
    DRONE_BIT,
    MECHA_BIT,
    ROOT_BODY,
    STAND_HEIGHT_M,
    WORLD_BIT,
    WORLD_GROUP,
    add_mecha,
    move_thrust_site,
    set_thruster_ranges,
)

PHYSICS_DT = 0.002
FLOOR_HALF_SIZE_M = 2000.0
FLOOR_GRID_SPACING_M = 10.0
FLOOR_RGBA = [0.22, 0.25, 0.3, 1.0]
START_POSITION = (0.0, 0.0, STAND_HEIGHT_M)


def build_arena() -> tuple[mujoco.MjModel, MassProperties]:
    spec = _arena_spec()
    first = spec.compile()
    properties = MassProperties.measure(first)
    move_thrust_site(spec, _center_of_mass_in_torso(first))
    set_thruster_ranges(spec, thruster_ranges(properties))
    return spec.compile(), properties


def _arena_spec() -> mujoco.MjSpec:
    spec = mujoco.MjSpec()
    # 각은 모두 라디안으로 넘긴다 (기본값은 도라서, 관절 범위가 1/57로 줄어든다).
    spec.compiler.degree = False
    spec.option.timestep = PHYSICS_DT
    spec.worldbody.add_geom(
        name="floor",
        type=mujoco.mjtGeom.mjGEOM_PLANE,
        size=[FLOOR_HALF_SIZE_M, FLOOR_HALF_SIZE_M, FLOOR_GRID_SPACING_M],
        rgba=FLOOR_RGBA,
        group=WORLD_GROUP,
        contype=WORLD_BIT,
        conaffinity=MECHA_BIT | DRONE_BIT,
    )
    add_mecha(spec, START_POSITION)
    for index in range(MAX_DRONES):
        add_drone(spec, index)
    return spec


def _center_of_mass_in_torso(model: mujoco.MjModel) -> list[float]:
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    root = model.body(ROOT_BODY).id
    # 처음 자세의 몸통은 돌아가 있지 않아 세계 좌표의 차가 곧 몸통 기준 위치다.
    return (data.subtree_com[root] - data.xpos[root]).tolist()
