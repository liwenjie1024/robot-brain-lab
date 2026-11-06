"""화면이 시험장을 그릴 수 있게 모델을 설명한다 (contracts/sim/scene.schema.json).

화면은 기체를 몰라도 된다: 모양(geom)·메시와 움직이는 몸체 순서만 받아 그리고, 상태 메시지의 자세로 옮긴다.
"""

from __future__ import annotations

import struct

import mujoco
import numpy as np

from .combat import Units
from .limits import CommandLimits
from .mecha import MECHA_HEIGHT_M, MECHA_NAME
from .scenarios import SCENARIOS

# 열거형 값은 numpy 정수와 해시가 달라 int로 바꿔 키로 쓴다 (모델 배열의 값은 numpy 정수다).
SHAPES = {
    int(mujoco.mjtGeom.mjGEOM_PLANE): "plane",
    int(mujoco.mjtGeom.mjGEOM_SPHERE): "sphere",
    int(mujoco.mjtGeom.mjGEOM_CAPSULE): "capsule",
    int(mujoco.mjtGeom.mjGEOM_CYLINDER): "cylinder",
    int(mujoco.mjtGeom.mjGEOM_BOX): "box",
    int(mujoco.mjtGeom.mjGEOM_MESH): "mesh",
}
MESH_HEADER = struct.Struct("<II")
ROBOT_DESCRIPTION = (
    "시험 기체. 등의 추진기로 날고(비행 제어 System 0), 오른팔의 빔 소총으로 쏘고 왼팔의 방패로 막는다. "
    "이 프로젝트의 독자 설계다."
)


def moving_bodies(model: mujoco.MjModel) -> np.ndarray:
    """세계에 붙어 있지 않은 몸체 (상태 메시지가 자세를 보내는 순서)"""
    return np.array([body for body in range(1, model.nbody) if model.body_weldid[body] != 0], dtype=np.int32)


def drawn_geoms(model: mujoco.MjModel) -> list[int]:
    return [geom for geom in range(model.ngeom) if int(model.geom_type[geom]) in SHAPES]


def describe(model: mujoco.MjModel, units: Units, limits: CommandLimits, rates: dict[str, float]) -> dict:
    geoms = []
    for geom in drawn_geoms(model):
        shape = SHAPES[int(model.geom_type[geom])]
        item = {
            "body": int(model.geom_bodyid[geom]),
            "shape": shape,
            "size": model.geom_size[geom].tolist(),
            "position": model.geom_pos[geom].tolist(),
            "quaternion": model.geom_quat[geom].tolist(),
            "rgba": model.geom_rgba[geom].tolist(),
        }
        if shape == "mesh":
            item["mesh"] = int(model.geom_dataid[geom])
        geoms.append(item)
    meshes = [
        {
            "id": mesh,
            "name": model.mesh(mesh).name,
            "vertexCount": int(model.mesh_vertnum[mesh]),
            "faceCount": int(model.mesh_facenum[mesh]),
        }
        for mesh in range(model.nmesh)
    ]
    return {
        "robot": {"name": MECHA_NAME, "description": ROBOT_DESCRIPTION, "height": MECHA_HEIGHT_M},
        "movingBodies": moving_bodies(model).tolist(),
        "geoms": geoms,
        "meshes": meshes,
        "units": [
            {"id": unit.id, "kind": unit.kind, "name": unit.name, "body": unit.body} for unit in units.all.values()
        ],
        "scenarios": [
            {
                "name": scenario.name,
                "label": scenario.label,
                "description": scenario.description,
                "drones": len(scenario.drones),
                "armedDrones": sum(plan.armed for plan in scenario.drones),
            }
            for scenario in SCENARIOS.values()
        ],
        "limits": limits.as_dict(),
        "rates": rates,
    }


def mesh_binary(model: mujoco.MjModel, mesh: int) -> bytes:
    """[꼭짓점 수, 삼각형 수, 꼭짓점 xyz(f32)..., 삼각형 번호(u32)...] little endian"""
    if not 0 <= mesh < model.nmesh:
        raise KeyError(mesh)
    vertex_start, vertex_count = model.mesh_vertadr[mesh], model.mesh_vertnum[mesh]
    face_start, face_count = model.mesh_faceadr[mesh], model.mesh_facenum[mesh]
    vertices = model.mesh_vert[vertex_start : vertex_start + vertex_count].astype("<f4")
    faces = model.mesh_face[face_start : face_start + face_count].astype("<u4")
    return MESH_HEADER.pack(int(vertex_count), int(face_count)) + vertices.tobytes() + faces.tobytes()
