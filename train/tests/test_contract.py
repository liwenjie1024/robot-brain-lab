"""从 mjlab 的训练环境写规约的测试：关节、观测、命令都照训练的设置写；写出来的规约合格；
规约表达不了的（历史、剪裁、延迟、每一维不同的缩放、别的观测）导出时就拒绝；身体的模型写得出来、读得回来。"""

import math
from pathlib import Path
from types import SimpleNamespace

import mujoco
import pytest
from mjlab.asset_zoo.robots.unitree_g1.g1_constants import (
    ACTUATOR_5020,
    ACTUATOR_7520_22,
    STIFFNESS_7520_22,
)
from nova_body.policy import check_contract

from nova_train.contract import (
    ExportError,
    _contract_term,
    _scalar_scale,
    build_contract,
    command_section,
    export_body,
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
    """规约里没有的观测（脚下的高度）拒绝。"""
    with pytest.raises(ExportError, match="没有观测 height_scan"):
        _contract_term("height_scan", term_cfg(builtin_sensor))


def test_an_observation_computed_another_way_is_refused():
    """名字对、算法不对（joint_pos 不是 joint_pos_rel 算的）也拒绝。"""
    with pytest.raises(ExportError, match="joint_pos 是 builtin_sensor 算的"):
        _contract_term("joint_pos", term_cfg(builtin_sensor))


def test_a_known_observation_maps_to_its_contract_term():
    """认得的观测换成规约里的名字（joint_pos → joint_pos）。"""
    assert _contract_term("joint_pos", term_cfg(joint_pos_rel)) == "joint_pos"


@pytest.mark.parametrize(("scale", "expected"), [(None, 1.0), (0.2, 0.2), (2, 2.0)], ids=["没有缩放", "小数", "整数"])
def test_a_single_scale_is_kept(scale, expected):
    """一个数的缩放照写（没有就是 1）。"""
    assert math.isclose(_scalar_scale("height_scan", scale), expected)


def test_a_per_dimension_scale_is_refused():
    """每一维不同的缩放，这一版的规约表达不了，拒绝。"""
    with pytest.raises(ExportError, match="每一维的缩放不一样"):
        _scalar_scale("base_lin_vel", (1.0, 2.0, 3.0))
