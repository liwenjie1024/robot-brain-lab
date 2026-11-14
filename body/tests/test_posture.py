"""站姿的测试：躯干竖直，脚底贴地，重心在两只脚的正中间上面，没有关节顶在范围的边上。"""

import math

import mujoco
import numpy as np
import pytest

from nova_body.hand import hand_joints
from nova_body.posture import KNEE_BEND_DEG, RELAXED_DEG, PostureError, solve_stand_pose
from nova_body.skeleton import ROOT_LINK, Side, sole_site

X, Y, Z = 0, 1, 2


def in_stand_pose(nova) -> mujoco.MjData:
    """摆在站姿上的状态（只算位置，不仿真）。"""
    data = mujoco.MjData(nova.model)
    data.qpos[:] = nova.stand.qpos
    mujoco.mj_forward(nova.model, data)
    return data


def test_knee_is_slightly_bent_and_hip_and_ankle_cancel_it(nova):
    """膝弯 15°；髋 = 膝 - 踝，所以躯干是竖直的、脚底是平的。"""
    stand = nova.stand
    assert stand.knee_deg == KNEE_BEND_DEG
    assert stand.hip_deg == pytest.approx(stand.knee_deg - stand.ankle_deg)
    assert 0 < stand.ankle_deg < stand.knee_deg


def test_trunk_is_upright_and_feet_are_flat(nova):
    """站姿里骨盆和两只脚都没有歪。"""
    model, data = nova.model, in_stand_pose(nova)
    for name in (ROOT_LINK, "chest", "left_foot", "right_foot"):
        assert data.xmat[model.body(name).id].reshape(3, 3) == pytest.approx(np.eye(3), abs=1e-9), name


def test_soles_are_on_the_floor(nova):
    """两只脚的脚底正好贴着地面。"""
    model, data = nova.model, in_stand_pose(nova)
    for side in Side:
        assert data.site_xpos[model.site(sole_site(side)).id][Z] == pytest.approx(0.0, abs=1e-9)


def test_center_of_mass_is_above_the_middle_of_the_feet(nova):
    """重心在两只脚的正中间上面（前后、左右都是）。"""
    model, data = nova.model, in_stand_pose(nova)
    center = data.subtree_com[model.body(ROOT_LINK).id]
    middle = np.mean([data.site_xpos[model.site(sole_site(side)).id] for side in Side], axis=0)
    assert center[X] == pytest.approx(middle[X], abs=1e-6)
    assert center[Y] == pytest.approx(middle[Y], abs=1e-9)
    assert center[Z] == pytest.approx(nova.stand.center_of_mass_height_m)


def test_center_of_mass_is_about_as_high_as_a_persons(nova):
    """重心的高度在身高的 0.5~0.6 之间（人约 0.55~0.57）。"""
    ratio = nova.stand.center_of_mass_height_m / nova.dimensions.height
    assert 0.5 < ratio < 0.6


def test_no_joint_rests_on_its_limit(nova):
    """站姿里没有关节顶在范围的边上（顶着的话，关节的限位一直在出力）。"""
    model = nova.model
    for joint in nova.joints:
        angle = nova.stand.qpos[model.joint(joint.name).qposadr[0]]
        assert joint.lower_rad < angle < joint.upper_rad, joint.name


def test_targets_carry_the_torque_that_holds_against_gravity(nova):
    """每个驱动器的目标 = 关节的角度 + 顶住重力要的力矩 ÷ 刚度；目标都在关节的范围里。"""
    model = nova.model
    for index, joint in enumerate(nova.actuated_joints):
        angle = nova.stand.qpos[model.joint(joint.name).qposadr[0]]
        torque = nova.stand.holding_torque_nm[index]
        assert nova.stand.ctrl[index] == pytest.approx(angle + torque / joint.stiffness), joint.name
        assert joint.lower_rad <= nova.stand.ctrl[index] <= joint.upper_rad, joint.name
        assert abs(torque) < joint.peak_torque_nm, joint.name


def test_ankles_hold_the_body_over_the_middle_of_the_feet(nova):
    """重心在脚的正中间上面，比踝靠前，所以两个踝各出"一半体重 x 这段距离"的力矩，往脚尖向下的方向。"""
    d = nova.dimensions
    names = [joint.name for joint in nova.actuated_joints]
    lever = d.foot_length / 2 - d.heel_behind_ankle
    foot_kg = float(nova.model.body_subtreemass[nova.model.body("left_foot").id])
    expected = -(nova.budget.total_kg / 2 - foot_kg) * 9.81 * lever
    for side in Side:
        torque = nova.stand.holding_torque_nm[names.index(f"{side.value}_ankle_pitch")]
        assert torque == pytest.approx(expected, rel=0.01)


def test_standing_costs_little_torque(nova):
    """站着几乎不费力：每个关节出的力矩都不到它峰值的 10%。"""
    for joint, torque in zip(nova.actuated_joints, nova.stand.holding_torque_nm, strict=True):
        assert abs(torque) < 0.10 * joint.peak_torque_nm, joint.name


def test_left_and_right_hold_with_the_same_torque(nova):
    """左右两侧出的力矩一样大。"""
    torque_of = dict(zip((joint.name for joint in nova.actuated_joints), nova.stand.holding_torque_nm, strict=True))
    for name, torque in torque_of.items():
        if name.startswith("left_"):
            assert torque == pytest.approx(torque_of["right_" + name.removeprefix("left_")], abs=1e-9), name


def test_far_finger_joints_match_the_near_ones(nova):
    """站姿里远指间的角度已经按联动的比例摆好。"""
    model = nova.model
    for joint in nova.joints:
        if joint.follows is not None:
            near = nova.stand.qpos[model.joint(joint.follows).qposadr[0]]
            far = nova.stand.qpos[model.joint(joint.name).qposadr[0]]
            assert far == pytest.approx(joint.follow_ratio * near), joint.name


def test_both_sides_have_the_same_pose(nova):
    """左右两侧的关节角度一样。"""
    model = nova.model
    for joint in nova.joints:
        if joint.side is Side.LEFT:
            twin = "right_" + joint.name.removeprefix("left_")
            left = nova.stand.qpos[model.joint(joint.name).qposadr[0]]
            assert left == nova.stand.qpos[model.joint(twin).qposadr[0]], joint.name


def test_relaxed_angles_name_real_joints(nova):
    """放松的角度表里写的关节，模型里都有；手的每根手指都微微弯着。"""
    keys = {joint.key for joint in nova.joints}
    assert set(RELAXED_DEG) <= keys
    bent = {joint.key for joint in hand_joints() if RELAXED_DEG.get(joint.key, 0) > 0}
    assert {"index_pip", "middle_pip", "ring_pip", "little_pip", "thumb_ip"} <= bent


@pytest.mark.parametrize("knee_deg", [5.0, 15.0, 25.0], ids=["几乎站直", "平常", "弯一些"])
def test_any_reasonable_knee_bend_has_a_stand_pose(nova, knee_deg):
    """膝弯多少都能找到站姿：重心还是在脚的正中间上面，膝弯得越多骨盆越低。"""
    pose = solve_stand_pose(nova.model, knee_deg)
    data = mujoco.MjData(nova.model)
    data.qpos[:] = pose.qpos
    mujoco.mj_forward(nova.model, data)
    center = data.subtree_com[nova.model.body(ROOT_LINK).id]
    sole = data.site_xpos[nova.model.site(sole_site(Side.LEFT)).id]
    assert center[X] == pytest.approx(sole[X], abs=1e-6)
    assert sole[Z] == pytest.approx(0.0, abs=1e-9)
    assert pose.pelvis_height_m <= nova.dimensions.hip_height


def test_deeper_knee_bend_lowers_the_pelvis(nova):
    """膝弯得越多，骨盆越低。"""
    heights = [solve_stand_pose(nova.model, knee_deg).pelvis_height_m for knee_deg in (5.0, 15.0, 25.0)]
    assert heights == sorted(heights, reverse=True)
    assert len(set(heights)) == len(heights)


def test_solving_twice_gives_the_same_pose(nova):
    """同一个模型算两次，站姿一样；和存在模型里的也一样。"""
    assert solve_stand_pose(nova.model) == solve_stand_pose(nova.model)
    assert solve_stand_pose(nova.model).ankle_deg == pytest.approx(nova.stand.ankle_deg)


@pytest.mark.parametrize("knee_deg", [60.0, 120.0], ids=["半蹲", "深蹲"])
def test_deep_squat_with_upright_trunk_is_rejected(nova, knee_deg):
    """躯干竖直时蹲不深：踝最多转 20°，重心到不了脚的中间。报错，不给一个站不住的姿势。"""
    with pytest.raises(PostureError, match="找不到让重心落在脚中间的站姿"):
        solve_stand_pose(nova.model, knee_deg)


def test_stand_pose_is_stored_in_the_model(nova):
    """站姿存在模型里，名字是 stand。"""
    key = nova.model.key("stand")
    assert key.qpos == pytest.approx(np.array(nova.stand.qpos))
    assert key.ctrl == pytest.approx(np.array(nova.stand.ctrl))
    assert math.degrees(key.qpos[nova.model.joint("left_knee").qposadr[0]]) == pytest.approx(KNEE_BEND_DEG)
