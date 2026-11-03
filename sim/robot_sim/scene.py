"""화면이 몸을 그릴 수 있게 모델을 설명한다 (contracts/sim/scene.schema.json).

화면은 로봇을 몰라도 된다: 모양(geom)·메시와 움직이는 몸체 순서만 받아 그리고, 상태 메시지의 자세로 옮긴다.
"""

from __future__ import annotations

import struct

import mujoco
import numpy as np

from .limits import CommandLimits

# 로봇 모델에서 보이기만 하는 모양의 묶음 (충돌용 모양은 같은 메시를 겹쳐 그리게 되어 뺀다)
VISUAL_GROUP = 1
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


def moving_bodies(model: mujoco.MjModel) -> np.ndarray:
    """세계에 붙어 있지 않은 몸체 (상태 메시지가 자세를 보내는 순서)"""
    return np.array([body for body in range(1, model.nbody) if model.body_weldid[body] != 0], dtype=np.int32)


def drawn_geoms(model: mujoco.MjModel, robot_root: int) -> list[int]:
    geoms = []
    for geom in range(model.ngeom):
        on_robot = model.body_rootid[model.geom_bodyid[geom]] == robot_root
        if (not on_robot or model.geom_group[geom] == VISUAL_GROUP) and int(model.geom_type[geom]) in SHAPES:
            geoms.append(geom)
    return geoms


def describe(
    model: mujoco.MjModel,
    robot_root: int,
    limits: CommandLimits,
    rates: dict[str, float],
) -> dict:
    geoms = []
    for geom in drawn_geoms(model, robot_root):
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
        "robot": {
            "name": "Unitree G1 (다리 12관절)",
            "description": "시험용 몸. 다리는 미리 학습된 걷기 정책이 움직이고 윗몸은 고정되어 있다.",
        },
        "movingBodies": moving_bodies(model).tolist(),
        "geoms": geoms,
        "meshes": meshes,
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
