"""把一个身体写成给网页的"样子"（contracts/sim/scene.schema.json）：有哪些段、每个形状长在哪、
有哪些关节和感觉。网页只按这个画，不认身体是哪一个。
"""

from collections.abc import Iterable

import mujoco
import numpy as np

from nova_body.bench import FLOOR
from nova_body.body import SIDE_NAMES, Body
from nova_body.drawing import shape_color
from nova_sim.bodies import Choice

SHAPE_KINDS = {
    mujoco.mjtGeom.mjGEOM_BOX: "box",
    mujoco.mjtGeom.mjGEOM_SPHERE: "sphere",
    mujoco.mjtGeom.mjGEOM_CAPSULE: "capsule",
    mujoco.mjtGeom.mjGEOM_ELLIPSOID: "ellipsoid",
    mujoco.mjtGeom.mjGEOM_MESH: "mesh",
}
FOOT_LABEL = "脚"
# 模型里第 0 个身体是"世界"，不是身体的一段；给网页的清单里不要它。
WORLD_BODIES = 1
VERTEX_SIZE = 3
MESH_HEADER_TYPE = "<u4"
MESH_VERTEX_TYPE = "<f4"
MESH_FACE_TYPE = "<u4"


class SceneError(RuntimeError):
    """这个身体写不成给网页的样子。"""


def link_index(body_id: int) -> int:
    """模型里一段身体的编号，换成它在给网页的清单（links）里是第几个。"""
    if body_id < WORLD_BODIES:
        raise SceneError("世界不是身体的一段")
    return int(body_id) - WORLD_BODIES


def describe_scene(key: str, body: Body, choices: Iterable[Choice]) -> dict:
    """这个身体的样子，和现在能选哪些身体。"""
    model = body.model
    shapes = [_shape(model, geom) for geom in _drawn_geoms(body)]
    return {
        "body": key,
        "name": body.name,
        "choices": [
            {"body": choice.key, "name": choice.name, "available": choice.body is not None, "reason": choice.reason}
            for choice in choices
        ],
        "mass_kg": body.mass_kg,
        "height_m": body.height_m,
        "timestep_s": float(model.opt.timestep),
        "links": [model.body(index).name for index in range(WORLD_BODIES, model.nbody)],
        "root": link_index(model.body(body.anatomy.root).id),
        "push_point": _push_point(body),
        "shapes": shapes,
        "meshes": [
            {"id": mesh, "vertices": int(model.mesh_vertnum[mesh]), "faces": int(model.mesh_facenum[mesh])}
            for mesh in sorted({shape["mesh"] for shape in shapes if shape["mesh"] is not None})
        ],
        "joints": [
            {
                "name": joint.name,
                "label": joint.label,
                "region": joint.region.value,
                "lower_rad": joint.lower_rad,
                "upper_rad": joint.upper_rad,
                "peak_torque_nm": joint.peak_torque_nm,
            }
            for joint in body.joints
        ],
        "imus": [{"label": imu.label} for imu in body.imus],
        "force_sensors": [{"label": sensor.label} for sensor in body.force_sensors],
        "touch_sensors": [{"label": sensor.label} for sensor in body.touch_sensors],
        "feet": _feet(body),
        "cameras": _cameras(body),
    }


def drawn_meshes(body: Body) -> set[int]:
    """这个身体画出来要用到的网格的编号。"""
    model = body.model
    return {
        int(model.geom_dataid[geom])
        for geom in _drawn_geoms(body)
        if model.geom_type[geom] == mujoco.mjtGeom.mjGEOM_MESH
    }


def mesh_payload(model: mujoco.MjModel, mesh: int) -> bytes:
    """一个网格的点和面，给网页的二进制格式（都是小端）：

    点的个数、面的个数（各一个 32 位无符号整数），然后是每个点的 x、y、z（32 位浮点数），
    然后是每个三角形三个点的编号（32 位无符号整数）。
    """
    if not 0 <= mesh < model.nmesh:
        raise SceneError(f"没有第 {mesh} 个网格")
    first_vertex, vertices = int(model.mesh_vertadr[mesh]), int(model.mesh_vertnum[mesh])
    first_face, faces = int(model.mesh_faceadr[mesh]), int(model.mesh_facenum[mesh])
    header = np.array([vertices, faces], dtype=MESH_HEADER_TYPE)
    points = model.mesh_vert[first_vertex : first_vertex + vertices].astype(MESH_VERTEX_TYPE)
    triangles = model.mesh_face[first_face : first_face + faces].astype(MESH_FACE_TYPE)
    return header.tobytes() + points.tobytes() + triangles.tobytes()


def _drawn_geoms(body: Body) -> list[int]:
    """要画的形状：在这个身体要画的那几组里，而且不是地面。"""
    model = body.model
    return [
        geom
        for geom in range(model.ngeom)
        if model.geom_group[geom] in body.drawn_groups and model.geom(geom).name != FLOOR
    ]


def _shape(model: mujoco.MjModel, geom: int) -> dict:
    kind = SHAPE_KINDS.get(int(model.geom_type[geom]))
    if kind is None:
        raise SceneError(f"网页还不会画这种形状：{int(model.geom_type[geom])}（{model.geom(geom).name}）")
    return {
        "link": link_index(model.geom_bodyid[geom]),
        "kind": kind,
        "size": _numbers(model.geom_size[geom]),
        "position": _numbers(model.geom_pos[geom]),
        "orientation": _numbers(model.geom_quat[geom]),
        "color": list(shape_color(model, geom)),
        "mesh": int(model.geom_dataid[geom]) if kind == "mesh" else None,
    }


def _push_point(body: Body) -> dict:
    """推的力加在胸这一段的重心上（仿真里往一段身体上加力，就是加在它的重心）。"""
    trunk = body.model.body(body.anatomy.trunk)
    return {"link": link_index(trunk.id), "position": _numbers(trunk.ipos)}


def _feet(body: Body) -> list[dict]:
    model = body.model
    feet = []
    for side, leg in body.anatomy.legs.items():
        sole = model.site(leg.sole)
        foot = model.body(leg.foot).id
        if sole.bodyid[0] != foot:
            raise SceneError(f"{leg.sole} 这个点不在 {leg.foot} 上")
        feet.append(
            {
                "label": SIDE_NAMES[side] + FOOT_LABEL,
                "link": link_index(foot),
                "sole": _numbers(sole.pos),
                "length_m": body.foot_length_m,
                "width_m": body.foot_width_m,
            }
        )
    return feet


def _cameras(body: Body) -> list[dict]:
    model = body.model
    cameras = []
    for view in body.cameras:
        camera = model.camera(view.camera)
        cameras.append(
            {
                "label": view.label,
                "link": link_index(camera.bodyid[0]),
                "position": _numbers(camera.pos),
                "orientation": _numbers(camera.quat),
                "fovy_deg": float(camera.fovy[0]),
            }
        )
    return cameras


def _numbers(values: np.ndarray) -> list[float]:
    return [float(value) for value in values]
