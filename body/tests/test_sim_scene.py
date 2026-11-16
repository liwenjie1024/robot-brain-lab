"""给网页的"样子"的测试：每个身体（Nova 和基线）写出来都合规约；网页按它摆出来的位置和仿真里的一样。"""

import json
from dataclasses import replace

import mujoco
import numpy as np
import pytest

from nova_body.bench import FLOOR
from nova_body.body import Region, Side
from nova_sim.bodies import G1, NOVA, Choice
from nova_sim.protocol import SCENE, problems
from nova_sim.scene import SceneError, describe_scene, drawn_meshes, link_index, mesh_payload

G1_COLLISION_GROUP = 3


def at_stand(body) -> mujoco.MjData:
    data = mujoco.MjData(body.model)
    data.qpos[:] = body.stand.qpos
    mujoco.mj_forward(body.model, data)
    return data


def in_world(data: mujoco.MjData, link: int, position, orientation=None):
    """网页的算法：一段身体的位置和姿态，加上东西在这一段里的位置（和姿态），得到它在世界里的位置（和姿态）。"""
    body = link + 1
    rotation = data.xmat[body].reshape(3, 3)
    world = data.xpos[body] + rotation @ np.asarray(position)
    if orientation is None:
        return world
    local = np.zeros(9)
    mujoco.mju_quat2Mat(local, np.asarray(orientation, dtype=float))
    return world, rotation @ local.reshape(3, 3)


@pytest.fixture(scope="module")
def scene(body, choices) -> dict:
    return describe_scene("some-key", body, choices.values())


# 每个身体 --------------------------------------------------------------------------------------------


def test_scene_follows_the_contract(scene, body):
    """写出来的样子合规约，能直接变成 JSON；记号、名字、质量、身高、步长都是这个身体的。"""
    assert problems(SCENE, scene) == []
    assert json.loads(json.dumps(scene, allow_nan=False)) == scene
    assert (scene["body"], scene["name"]) == ("some-key", body.name)
    assert scene["mass_kg"] == pytest.approx(body.mass_kg)
    assert scene["height_m"] == body.height_m
    assert scene["timestep_s"] == 0.001


def test_links_are_the_model_bodies_without_the_world(scene, body):
    """links 是模型里的每一段身体（不要"世界"），骨盆是 root 指的那一个。"""
    model = body.model
    assert scene["links"] == [model.body(index).name for index in range(1, model.nbody)]
    assert scene["links"][scene["root"]] == body.anatomy.root
    assert link_index(model.body(body.anatomy.root).id) == scene["root"]


def test_every_drawn_shape_is_listed_once(scene, body):
    """要画的每个形状都在，地面不在；长在哪一段、什么颜色都写着。"""
    model = body.model
    drawn = [
        geom
        for geom in range(model.ngeom)
        if model.geom_group[geom] in body.drawn_groups and model.geom(geom).name != FLOOR
    ]
    assert len(scene["shapes"]) == len(drawn) > 0
    for shape, geom in zip(scene["shapes"], drawn, strict=True):
        assert shape["link"] == model.geom_bodyid[geom] - 1
        assert all(0.0 <= value <= 1.0 for value in shape["color"])
        assert (shape["mesh"] is None) == (shape["kind"] != "mesh")


def test_shapes_land_where_the_simulation_has_them(scene, body):
    """网页按"这一段的位置和姿态 + 形状在这一段里的位置和姿态"摆出来的，和仿真里每个形状的位置、姿态一样。"""
    model, data = body.model, at_stand(body)
    drawn = [
        geom
        for geom in range(model.ngeom)
        if model.geom_group[geom] in body.drawn_groups and model.geom(geom).name != FLOOR
    ]
    for shape, geom in zip(scene["shapes"], drawn, strict=True):
        position, rotation = in_world(data, shape["link"], shape["position"], shape["orientation"])
        assert position == pytest.approx(data.geom_xpos[geom], abs=1e-9)
        assert rotation == pytest.approx(data.geom_xmat[geom].reshape(3, 3), abs=1e-9)


def test_joints_are_the_driven_joints_in_order(scene, body):
    """关节就是有驱动器的那些，顺序和模型里的驱动器一样；每个都写着在身体的哪一部分。"""
    assert [joint["name"] for joint in scene["joints"]] == [joint.name for joint in body.joints]
    for listed, joint in zip(scene["joints"], body.joints, strict=True):
        assert listed["label"] == joint.label
        assert listed["region"] == joint.region.value
        assert (listed["lower_rad"], listed["upper_rad"]) == (joint.lower_rad, joint.upper_rad)
        assert listed["peak_torque_nm"] == joint.peak_torque_nm
    assert {joint["region"] for joint in scene["joints"]} <= {region.value for region in Region}


def test_feet_are_left_then_right_with_the_sole_point(scene, body):
    """两只脚：先左后右；脚底的点按网页的算法摆出来，就是仿真里脚底的那个点；着地的那一块多长多宽。"""
    model, data = body.model, at_stand(body)
    assert [foot["label"] for foot in scene["feet"]] == ["左脚", "右脚"]
    for foot, side in zip(scene["feet"], Side, strict=True):
        leg = body.anatomy.legs[side]
        assert scene["links"][foot["link"]] == leg.foot
        sole = data.site_xpos[model.site(leg.sole).id]
        assert in_world(data, foot["link"], foot["sole"]) == pytest.approx(sole, abs=1e-9)
        assert sole[2] == pytest.approx(0.0, abs=1e-9)
        assert (foot["length_m"], foot["width_m"]) == (body.foot_length_m, body.foot_width_m)


def test_senses_are_listed_by_their_labels(scene, body):
    """每种感觉按名字列出来，顺序和这个身体的清单一样。"""
    assert [imu["label"] for imu in scene["imus"]] == [imu.label for imu in body.imus]
    assert [sensor["label"] for sensor in scene["force_sensors"]] == [sensor.label for sensor in body.force_sensors]
    assert [sensor["label"] for sensor in scene["touch_sensors"]] == [sensor.label for sensor in body.touch_sensors]


def test_cameras_look_from_where_the_model_has_them(scene, body):
    """相机按网页的算法摆出来的位置和朝向，和仿真里的一样；视角是模型里写的。"""
    model, data = body.model, at_stand(body)
    assert [camera["label"] for camera in scene["cameras"]] == [view.label for view in body.cameras]
    for listed, view in zip(scene["cameras"], body.cameras, strict=True):
        camera = model.camera(view.camera).id
        position, rotation = in_world(data, listed["link"], listed["position"], listed["orientation"])
        assert position == pytest.approx(data.cam_xpos[camera], abs=1e-9)
        assert rotation == pytest.approx(data.cam_xmat[camera].reshape(3, 3), abs=1e-9)
        assert listed["fovy_deg"] == pytest.approx(float(model.cam_fovy[camera]))


def test_choices_say_which_bodies_can_be_put_on_the_bench(nova, g1):
    """能选的身体都列着；用不了的写着为什么。"""
    choices = [Choice(NOVA, "Nova", nova.body), Choice(G1, "G1", None, "文件还没下载")]
    listed = describe_scene(NOVA, nova.body, choices)["choices"]
    assert listed == [
        {"body": "nova", "name": "Nova", "available": True, "reason": ""},
        {"body": "g1", "name": "G1", "available": False, "reason": "文件还没下载"},
    ]


# 各自的 ----------------------------------------------------------------------------------------------


def test_nova_is_drawn_from_simple_shapes(nova, choices):
    """Nova 是盒子、球、胶囊、椭球，没有网格；五台相机都在。"""
    scene = describe_scene(NOVA, nova.body, choices.values())
    assert {shape["kind"] for shape in scene["shapes"]} == {"box", "sphere", "capsule", "ellipsoid"}
    assert scene["meshes"] == []
    assert drawn_meshes(nova.body) == set()
    assert len(scene["shapes"]) == nova.model.ngeom - 1
    assert [camera["label"] for camera in scene["cameras"]] == ["左眼", "右眼", "胸前（朝下）", "左手掌", "右手掌"]
    assert len(scene["force_sensors"]) == 4
    assert len(scene["touch_sensors"]) == 25


def test_g1_is_drawn_from_its_35_meshes(g1, choices):
    """基线是 35 个网格，每个形状用一个；没有相机、力传感器、接触的传感器。"""
    scene = describe_scene(G1, g1, choices.values())
    assert {shape["kind"] for shape in scene["shapes"]} == {"mesh"}
    assert len(scene["shapes"]) == len(scene["meshes"]) == 35
    assert {shape["mesh"] for shape in scene["shapes"]} == {mesh["id"] for mesh in scene["meshes"]} == drawn_meshes(g1)
    assert (scene["cameras"], scene["force_sensors"], scene["touch_sensors"]) == ([], [], [])
    assert [imu["label"] for imu in scene["imus"]] == ["骨盆", "躯干"]


# 网格 ------------------------------------------------------------------------------------------------


def test_mesh_payload_carries_the_points_and_triangles(g1):
    """网格的二进制：开头是点和面的个数，后面是每个点、每个三角形，和模型里的一样。"""
    model = g1.model
    for mesh in sorted(drawn_meshes(g1))[:5]:
        payload = mesh_payload(model, mesh)
        vertices, faces = np.frombuffer(payload, dtype="<u4", count=2)
        assert (vertices, faces) == (model.mesh_vertnum[mesh], model.mesh_facenum[mesh])
        assert len(payload) == 8 + 12 * vertices + 12 * faces
        points = np.frombuffer(payload, dtype="<f4", count=3 * vertices, offset=8).reshape(-1, 3)
        triangles = np.frombuffer(payload, dtype="<u4", offset=8 + 12 * vertices).reshape(-1, 3)
        start = model.mesh_vertadr[mesh]
        assert np.array_equal(points, model.mesh_vert[start : start + vertices])
        first = model.mesh_faceadr[mesh]
        assert np.array_equal(triangles, model.mesh_face[first : first + faces])
        assert triangles.max() < vertices


@pytest.mark.parametrize("mesh", [-1, 35, 10_000], ids=["负的", "正好超出一个", "大得多"])
def test_mesh_payload_rejects_an_unknown_mesh(g1, mesh):
    """没有这个编号的网格：报错。"""
    with pytest.raises(SceneError, match=f"没有第 {mesh} 个网格"):
        mesh_payload(g1.model, mesh)


# 写不出来的时候 --------------------------------------------------------------------------------------


def test_rejects_a_shape_the_page_cannot_draw(g1, choices):
    """基线碰撞用的那一组里有圆柱，网页还不会画：报错，不悄悄漏掉。"""
    with_colliders = replace(g1, drawn_groups=(G1_COLLISION_GROUP,))
    with pytest.raises(SceneError, match="网页还不会画这种形状"):
        describe_scene(G1, with_colliders, choices.values())


def test_rejects_a_sole_point_that_is_not_on_its_foot(nova, choices):
    """脚底的点不在这只脚上（左脚写成了右脚的点）：报错。"""
    anatomy = nova.body.anatomy
    legs = {**anatomy.legs, Side.LEFT: replace(anatomy.legs[Side.LEFT], sole=anatomy.legs[Side.RIGHT].sole)}
    wrong = replace(nova.body, anatomy=replace(anatomy, legs=legs))
    with pytest.raises(SceneError, match="right_sole 这个点不在 left_foot 上"):
        describe_scene(NOVA, wrong, choices.values())


def test_the_world_is_not_a_link():
    """模型里的"世界"不是身体的一段。"""
    with pytest.raises(SceneError, match="世界不是身体的一段"):
        link_index(0)
    assert link_index(1) == 0
