"""从 mjlab 的训练环境写规约的测试：关节、观测、命令都照训练的设置写；写出来的规约合格；
规约表达不了的（历史、剪裁、延迟、每一维不同的缩放、别的观测）导出时就拒绝；身体的模型写得出来、读得回来。"""

import json
import math
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import mujoco
import pytest
import torch
from mjlab.asset_zoo.robots.unitree_g1.g1_constants import (
    ACTUATOR_5020,
    ACTUATOR_7520_22,
    STIFFNESS_7520_22,
)
from mjlab.sensor import GridPatternCfg
from nova_body.policy import POLICY_SCHEMA_PATH as POLICY_SCHEMA
from nova_body.policy import check_contract

from nova_train.contract import (
    ExportError,
    _contract_term,
    _scalar_scale,
    build_contract,
    command_section,
    export_body,
    height_scan_spec,
    joints_section,
    observations_section,
)

G1_JOINTS = 29
VELOCITY_STAGE_STEP = 5000 * 24


def test_joints_follow_the_action_order_with_training_gains(g1_env):
    """29 个关节按动作的顺序；膝的软硬、力矩的上限是 mjlab 给 G1 定的（7520-22 电机）。"""
    joints = joints_section(g1_env)
    assert len(joints) == G1_JOINTS
    assert [joint["name"] for joint in joints] == list(g1_env.scene["robot"].joint_names)
    knee = next(joint for joint in joints if joint["name"] == "left_knee_joint")
    assert knee["stiffness_nm_per_rad"] == pytest.approx(STIFFNESS_7520_22)
    assert knee["torque_limit_nm"] == pytest.approx(ACTUATOR_7520_22.effort_limit)
    assert knee["action_scale_rad"] == pytest.approx(0.25 * ACTUATOR_7520_22.effort_limit / STIFFNESS_7520_22)
    assert knee["default_position_rad"] == pytest.approx(0.669, abs=1e-6)


def test_ankles_get_twice_one_motor_like_mjlab_says(g1_env):
    """踝是两个电机并联：mjlab 当成一个关节、两个电机的力矩加起来（2 x 25 N·m）。"""
    joints = {joint["name"]: joint for joint in joints_section(g1_env)}
    assert joints["left_ankle_pitch_joint"]["torque_limit_nm"] == pytest.approx(2 * ACTUATOR_5020.effort_limit)


def test_observations_are_the_actor_terms_in_order(g1_env):
    """策略看的观测：速度、角速度、重力的方向、关节的角度和转速、上一次的动作、命令；一行 99 个；IMU 在骨盆上。"""
    joint_names = [joint["name"] for joint in joints_section(g1_env)]
    observations, imu_site = observations_section(g1_env, joint_names)
    assert [item["term"] for item in observations] == [
        "base_lin_vel",
        "base_ang_vel",
        "projected_gravity",
        "joint_pos",
        "joint_vel",
        "last_action",
        "command",
    ]
    assert [item["size"] for item in observations] == [3, 3, 3, 29, 29, 29, 3]
    assert sum(item["size"] for item in observations) == 99
    assert all(item["scale"] == 1.0 for item in observations)
    assert imu_site == "imu_in_pelvis"


def test_observations_in_another_joint_order_are_refused(g1_env):
    """观测里关节的顺序和动作的不一样就拒绝（测试台只用一个顺序）。"""
    joint_names = [joint["name"] for joint in joints_section(g1_env)]
    with pytest.raises(ExportError, match="顺序"):
        observations_section(g1_env, list(reversed(joint_names)))


def test_command_ranges_follow_the_curriculum(g1_env):
    """命令的范围：刚开始练是 x、y ±1 m/s、转 ±0.5 rad/s；练到课程的第二步，往前到 2 m/s、转 ±0.7。"""
    start = command_section(g1_env, common_step_counter=0)
    assert start["fields"] == ["lin_vel_x", "lin_vel_y", "ang_vel_z"]
    assert start["ranges"] == {"lin_vel_x": [-1.0, 1.0], "lin_vel_y": [-1.0, 1.0], "ang_vel_z": [-0.5, 0.5]}
    later = command_section(g1_env, common_step_counter=VELOCITY_STAGE_STEP)
    assert later["ranges"] == {"lin_vel_x": [-1.5, 2.0], "lin_vel_y": [-1.0, 1.0], "ang_vel_z": [-0.7, 0.7]}
    just_before = command_section(g1_env, common_step_counter=VELOCITY_STAGE_STEP - 1)
    assert just_before["ranges"] == start["ranges"]


def test_the_built_contract_passes_the_schema(g1_env):
    """写出来的规约照 JSON Schema 检查是合格的；每秒算 50 次（5 毫秒 x 4）。"""
    contract = build_contract(
        g1_env,
        name="g1-test",
        body="unitree_g1",
        task="Mjlab-Velocity-Flat-Unitree-G1",
        iterations=0,
        common_step_counter=0,
        onnx={"file": "policy.onnx", "sha256": "0" * 64, "input": "obs", "output": "actions"},
        body_model={"model": "body/scene.xml", "sha256": "1" * 64},
    )
    check_contract(contract)
    assert contract["rate_hz"] == pytest.approx(50.0)
    assert contract["trained"]["version"] == "1.6.0"


def test_the_body_model_is_written_with_meshes_and_reloads(g1_env, tmp_path: Path):
    """身体写成 MJCF 和网格，读得回来：29 个驱动器，关节的名字不带 robot/ 的前缀，软硬和训练的一样。"""
    xml = export_body(g1_env, tmp_path / "body")
    model = mujoco.MjModel.from_xml_path(str(xml))
    assert model.nu == G1_JOINTS
    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "left_knee_joint") >= 0
    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, "imu_in_pelvis") >= 0
    knee = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, "left_knee_joint")
    assert model.actuator_gainprm[knee, 0] == pytest.approx(STIFFNESS_7520_22)
    assert any(path.suffix.lower() == ".stl" for path in (tmp_path / "body" / "assets").iterdir())


def test_the_body_is_not_written_into_a_directory_that_has_files(g1_env, tmp_path: Path):
    """目录里已经有东西就不往里面写（不盖掉别的）。"""
    target = tmp_path / "body"
    target.mkdir()
    (target / "keep.txt").write_text("别动", encoding="utf-8")
    with pytest.raises(ExportError, match="已经有东西"):
        export_body(g1_env, target)


def builtin_sensor():
    """名字和 mjlab 的函数一样的假函数。"""


def joint_pos_rel():
    """名字和 mjlab 的函数一样的假函数。"""


def term_cfg(func, **changes):
    values = {"func": func, "history_length": 0, "clip": None, "delay_max_lag": 0, "params": {}}
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("changes", "message"),
    [({"history_length": 3}, "历史"), ({"clip": (-1.0, 1.0)}, "剪裁"), ({"delay_max_lag": 2}, "延迟")],
    ids=["有历史", "有剪裁", "有延迟"],
)
def test_observations_the_contract_cannot_express_are_refused(changes, message):
    """观测有历史、剪裁、延迟，这一版的规约表达不了，导出时就拒绝。"""
    with pytest.raises(ExportError, match=message):
        _contract_term("base_lin_vel", term_cfg(builtin_sensor, **changes))


def test_an_unknown_observation_is_refused():
    """规约里没有的观测（脚离地多高）拒绝。"""
    with pytest.raises(ExportError, match="没有观测 foot_height"):
        _contract_term("foot_height", term_cfg(builtin_sensor))


def test_an_observation_computed_another_way_is_refused():
    """名字对、算法不对（joint_pos 不是 joint_pos_rel 算的）也拒绝。"""
    with pytest.raises(ExportError, match="joint_pos 是 builtin_sensor 算的"):
        _contract_term("joint_pos", term_cfg(builtin_sensor))


def test_a_known_observation_maps_to_its_contract_term():
    """认得的观测换成规约里的名字（joint_pos → joint_pos）。"""
    assert _contract_term("joint_pos", term_cfg(joint_pos_rel)) == "joint_pos"


@pytest.mark.parametrize(
    ("scale", "expected"),
    [(None, 1.0), (0.2, 0.2), (2, 2.0), (torch.tensor(0.2), 0.2), ((0.5, 0.5, 0.5), 0.5)],
    ids=["没有缩放", "小数", "整数", "建好环境后的张量", "每一维都一样"],
)
def test_a_single_scale_is_kept(scale, expected):
    """一个数的缩放照写（没有就是 1）；mjlab 建好环境后换成的张量、每一维都一样的，也是一个数。"""
    assert math.isclose(_scalar_scale("height_scan", scale), expected)


def test_a_per_dimension_scale_is_refused():
    """每一维不同的缩放，这一版的规约表达不了，拒绝。"""
    with pytest.raises(ExportError, match="每一维的缩放不一样"):
        _scalar_scale("base_lin_vel", (1.0, 2.0, 3.0))
    with pytest.raises(ExportError, match="每一维的缩放不一样"):
        _scalar_scale("base_lin_vel", torch.tensor([1.0, 2.0, 3.0]))


def height_scan():
    """名字和 mjlab 的函数一样的假函数。"""


SCAN_MODEL_XML = (
    '<mujoco><worldbody><body name="robot/pelvis"><freejoint/><geom size="0.1"/></body></worldbody></mujoco>'
)


def raycast(**changes):
    """mjlab 练楼梯时的那个射线传感器的设置（骨盆下面 1.6 m x 1.0 m，每 10 cm 一点），可以改几样。"""
    values = {
        "frame": SimpleNamespace(type="body", name="pelvis", entity="robot"),
        "pattern": GridPatternCfg(size=(1.6, 1.0), resolution=0.1),
        "ray_alignment": "yaw",
        "max_distance": 5.0,
        "exclude_parent_body": True,
        "include_geom_groups": (0,),
    }
    values.update(changes)
    return SimpleNamespace(**values)


def scan_term(**params):
    return term_cfg(height_scan, params={"sensor_name": "terrain_scan", **params})


def test_a_height_scan_is_written_the_way_mjlab_casts_it():
    """mjlab 的高度扫描照它的设置写进规约：从骨盆、只跟着转偏航、网格多大多密、最远 5 m、只打第 0 组；
    写出来的合规约的格式。"""
    model = mujoco.MjModel.from_xml_string(SCAN_MODEL_XML)
    scan = height_scan_spec(scan_term(), raycast(), model)
    assert scan == {
        "frame_body": "pelvis",
        "alignment": "yaw",
        "size_m": [1.6, 1.0],
        "resolution_m": [0.1, 0.1],
        "offset_m": [0.0, 0.0],
        "max_distance_m": 5.0,
        "geom_groups": [0],
    }
    schema = json.loads(POLICY_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(scan, {"$defs": schema["$defs"], **schema["properties"]["height_scan"]})
    assert _contract_term("height_scan", scan_term()) == "height_scan"


@pytest.mark.parametrize(
    ("term_params", "changes", "message"),
    [
        ({"offset": 0.5}, {}, "减了一个常数"),
        ({"miss_value": 1.0}, {}, "打不到的射线"),
        ({}, {"ray_alignment": "base"}, "偏航"),
        ({}, {"pattern": GridPatternCfg(direction=(1.0, 0.0, 0.0))}, "竖直朝下"),
        ({}, {"pattern": SimpleNamespace(direction=(0.0, 0.0, -1.0))}, "竖直朝下"),
        ({}, {"frame": (SimpleNamespace(type="body", name="pelvis", entity="robot"),)}, "一个身体"),
        ({}, {"frame": SimpleNamespace(type="site", name="imu", entity="robot")}, "一个身体"),
        ({}, {"exclude_parent_body": False}, "不打它出发的"),
        ({}, {"include_geom_groups": None}, "哪几组"),
        ({}, {"frame": SimpleNamespace(type="body", name="torso", entity="robot")}, "没有高度扫描的身体"),
    ],
    ids=[
        "减常数",
        "打不到另算",
        "跟着全身转",
        "不朝下",
        "不是网格",
        "几个身体",
        "从一个点",
        "打自己",
        "不说组",
        "没有这个身体",
    ],
)
def test_height_scans_the_contract_cannot_express_are_refused(term_params, changes, message):
    """规约表达不了的高度扫描，导出时就拒绝。"""
    model = mujoco.MjModel.from_xml_string(SCAN_MODEL_XML)
    with pytest.raises(ExportError, match=message):
        height_scan_spec(scan_term(**term_params), raycast(**changes), model)
