"""站姿的测试：躯干竖直，脚底贴地，重心在两只脚的正中间上面，没有关节顶在范围的边上。

前一半每个身体（Nova 和基线）都跑；中间是只有 Nova 才有的；后一半用一个最小的两条腿的身体，
测算法本身：关节的正方向怎么定都一样、左右不对称时怎么分体重、摆不出来时报什么错。
"""

import math
from dataclasses import replace

import mujoco
import numpy as np
import pytest

from nova_body.bench import add_floor, stiffness_for, use_bench_settings
from nova_body.body import Anatomy, Leg, Side
from nova_body.hand import hand_joints
from nova_body.model import RELAXED_DEG
from nova_body.posture import (
    KNEE_BEND_DEG,
    PostureError,
    deepest_knee_bend_deg,
    solve_stand_pose,
    toe_up_limit_deg,
)

X, Y, Z = 0, 1, 2
AXIS_LEFT = (0.0, 1.0, 0.0)
AXIS_RIGHT = (0.0, -1.0, 0.0)
TINY_PEAK_TORQUE_NM = 100.0
TINY_TRUNK_KG = 10.0


def in_stand_pose(body) -> mujoco.MjData:
    """摆在站姿上的状态（只算位置，不仿真）。"""
    data = mujoco.MjData(body.model)
    data.qpos[:] = body.stand.qpos
    mujoco.mj_forward(body.model, data)
    return data


def angle_of(body, name: str) -> float:
    """站姿里这个关节的角度。"""
    return body.stand.qpos[body.model.joint(name).qposadr[0]]


def holding_by_joint(body) -> dict[str, float]:
    """站姿里每个有驱动器带着的关节得到的力矩：每个驱动器的力 x 系数，加起来。"""
    torques = {joint.name: 0.0 for joint in body.joints}
    for actuator, force in zip(body.actuators, body.stand.holding_torque_nm, strict=True):
        for name, coefficient in actuator.joints:
            torques[name] += coefficient * force
    return torques


def other_side(name: str) -> str:
    return name.replace("left_", "right_")


# 每个身体 --------------------------------------------------------------------------------------------


def test_knee_is_slightly_bent_and_hip_and_ankle_cancel_it(body):
    """膝弯 15°；髋 = 膝 - 踝，所以躯干是竖直的、脚底是平的。"""
    stand = body.stand
    assert stand.knee_deg == KNEE_BEND_DEG
    assert stand.hip_deg == pytest.approx(stand.knee_deg - stand.ankle_deg)
    assert 0 < stand.ankle_deg < stand.knee_deg


def test_trunk_is_upright_and_feet_are_flat(body):
    """站姿里骨盆、胸和两只脚都没有歪。"""
    model, data = body.model, in_stand_pose(body)
    feet = [leg.foot for leg in body.anatomy.legs.values()]
    for name in (body.anatomy.root, body.anatomy.trunk, *feet):
        assert data.xmat[model.body(name).id].reshape(3, 3) == pytest.approx(np.eye(3), abs=1e-9), name


def test_soles_are_on_the_floor(body):
    """两只脚的脚底正好贴着地面。"""
    model, data = body.model, in_stand_pose(body)
    for leg in body.anatomy.legs.values():
        assert data.site_xpos[model.site(leg.sole).id][Z] == pytest.approx(0.0, abs=1e-9)


def test_center_of_mass_is_above_the_middle_of_the_feet(body):
    """重心在两只脚的正中间上面：前后正好，左右差不到 1 mm。"""
    model, data = body.model, in_stand_pose(body)
    center = data.subtree_com[model.body(body.anatomy.root).id]
    middle = np.mean([data.site_xpos[model.site(leg.sole).id] for leg in body.anatomy.legs.values()], axis=0)
    assert center[X] == pytest.approx(middle[X], abs=1e-6)
    assert center[Y] == pytest.approx(middle[Y], abs=1e-3)
    assert center[Z] == pytest.approx(body.stand.center_of_mass_height_m)


def test_center_of_mass_is_about_as_high_as_a_persons(body):
    """重心的高度在身高的 0.5~0.6 之间（人约 0.55~0.57）。"""
    assert 0.5 < body.stand.center_of_mass_height_m / body.height_m < 0.6


def test_no_joint_rests_on_its_limit(body):
    """站姿里没有关节顶在范围的边上（顶着的话，关节的限位一直在出力）。"""
    for joint in body.joints:
        assert joint.lower_rad < angle_of(body, joint.name) < joint.upper_rad, joint.name


def test_targets_carry_the_torque_that_holds_against_gravity(body):
    """每个驱动器的目标 = 它带着的关节的角度 x 系数加起来 + 顶住重力要的力 ÷ 刚度；目标都在它的范围里。"""
    for index, actuator in enumerate(body.actuators):
        force = body.stand.holding_torque_nm[index]
        length = sum(coefficient * angle_of(body, name) for name, coefficient in actuator.joints)
        expected = length + force / stiffness_for(actuator.peak_torque_nm)
        assert body.stand.ctrl[index] == pytest.approx(expected), actuator.name
        assert actuator.lower <= body.stand.ctrl[index] <= actuator.upper, actuator.name
        assert abs(force) < actuator.peak_torque_nm, actuator.name


def test_standing_costs_little_torque(body):
    """站着几乎不费力：每个驱动器出的力都不到它峰值的 15%；每个关节得到的力矩也不到它峰值的 15%。"""
    for actuator, force in zip(body.actuators, body.stand.holding_torque_nm, strict=True):
        assert abs(force) < 0.15 * actuator.peak_torque_nm, actuator.name
    holding = holding_by_joint(body)
    for joint in body.joints:
        assert abs(holding[joint.name]) < 0.15 * joint.peak_torque_nm, joint.name


def test_ankles_work_the_hardest(body):
    """站着时最费力的是踝：重心在脚的中间上面，比踝靠前，要踝顶着。"""
    holding = holding_by_joint(body)
    hardest = max(holding, key=lambda name: abs(holding[name]))
    assert hardest in {leg.ankle_pitch for leg in body.anatomy.legs.values()}


def test_left_and_right_hold_with_about_the_same_torque(body):
    """左右两侧出的力矩一样大（方向怎么算正，各个身体不一样，所以只比大小）。"""
    torque_of = holding_by_joint(body)
    paired = [joint for joint in body.joints if joint.name.startswith("left_")]
    assert paired
    for joint in paired:
        twin = torque_of[other_side(joint.name)]
        assert abs(torque_of[joint.name]) == pytest.approx(abs(twin), abs=0.01 * joint.peak_torque_nm), joint.name


def test_both_sides_have_the_same_pose(body):
    """左右两侧的关节摆的角度一样大。"""
    for joint in body.joints:
        if joint.name.startswith("left_"):
            left, right = angle_of(body, joint.name), angle_of(body, other_side(joint.name))
            assert abs(left) == pytest.approx(abs(right), abs=1e-12), joint.name


@pytest.mark.parametrize("knee_deg", [5.0, 15.0, 25.0], ids=["几乎站直", "平常", "弯一些"])
def test_any_reasonable_knee_bend_has_a_stand_pose(body, knee_deg):
    """膝弯多少都能找到站姿：重心还是在脚的正中间上面，脚底贴地。"""
    model = body.model
    pose = solve_stand_pose(model, body.anatomy, knee_deg)
    data = mujoco.MjData(model)
    data.qpos[:] = pose.qpos
    mujoco.mj_forward(model, data)
    center = data.subtree_com[model.body(body.anatomy.root).id]
    sole = data.site_xpos[model.site(body.anatomy.legs[Side.LEFT].sole).id]
    assert center[X] == pytest.approx(sole[X], abs=1e-6)
    assert sole[Z] == pytest.approx(0.0, abs=1e-9)
    assert pose.knee_deg == knee_deg


def test_deeper_knee_bend_lowers_the_pelvis(body):
    """膝弯得越多，骨盆越低。"""
    heights = [solve_stand_pose(body.model, body.anatomy, knee_deg).pelvis_height_m for knee_deg in (5.0, 15.0, 25.0)]
    assert heights == sorted(heights, reverse=True)
    assert len(set(heights)) == len(heights)


def test_solving_twice_gives_the_same_pose(body):
    """同一个模型算两次，站姿一样；和这个身体带着的那份也一样。"""
    first = solve_stand_pose(body.model, body.anatomy)
    assert first == solve_stand_pose(body.model, body.anatomy)
    assert first == body.stand


def test_stand_pose_is_stored_in_the_model(body):
    """站姿存在模型里，名字是 stand；膝是弯 15° 的。"""
    key = body.model.key("stand")
    assert key.qpos == pytest.approx(np.array(body.stand.qpos))
    assert key.ctrl == pytest.approx(np.array(body.stand.ctrl))
    knee = body.model.joint(body.anatomy.legs[Side.LEFT].knee)
    assert abs(math.degrees(key.qpos[knee.qposadr[0]])) == pytest.approx(KNEE_BEND_DEG)


# 只有 Nova ------------------------------------------------------------------------------------------


def test_nova_ankles_hold_the_body_over_the_middle_of_the_feet(nova):
    """重心在脚的正中间上面，比踝靠前：地面在脚的正中间托着一半体重，脚自己的重量托在它的重心上，
    两个踝各出这两个力绕踝的力矩之差，往脚尖向下的方向。"""
    d = nova.dimensions
    names = [joint.name for joint in nova.actuated_joints]
    holding = nova.body.joint_holding_torques_nm
    lever = d.foot_length / 2 - d.heel_behind_ankle
    model = nova.model
    data = mujoco.MjData(model)
    data.qpos[:] = nova.stand.qpos
    mujoco.mj_kinematics(model, data)
    mujoco.mj_comPos(model, data)
    foot = model.body("left_foot").id
    foot_kg = float(model.body_subtreemass[foot])
    foot_lever = float(data.subtree_com[foot][0] - data.xanchor[model.joint("left_ankle_pitch").id][0])
    expected = -(nova.budget.total_kg / 2 * lever - foot_kg * foot_lever) * 9.81
    for side in Side:
        torque = holding[names.index(f"{side.value}_ankle_pitch")]
        assert torque == pytest.approx(expected, rel=0.01)


def test_nova_is_the_same_on_both_sides(nova):
    """Nova 是按左右镜像生成的：两侧的角度、出的力矩都一模一样（同一个正方向是同一个动作）。"""
    torque_of = dict(
        zip((joint.name for joint in nova.actuated_joints), nova.body.joint_holding_torques_nm, strict=True)
    )
    for joint in nova.joints:
        if joint.side is Side.LEFT:
            twin = other_side(joint.name)
            assert angle_of(nova.body, joint.name) == angle_of(nova.body, twin), joint.name
            if joint.name in torque_of:
                assert torque_of[joint.name] == pytest.approx(torque_of[twin], abs=1e-9), joint.name


def test_nova_stands_with_less_than_a_tenth_of_its_strength(nova):
    """Nova 站着时每个关节出的力矩都不到它峰值的 10%。"""
    for joint, torque in zip(nova.actuated_joints, nova.body.joint_holding_torques_nm, strict=True):
        assert abs(torque) < 0.10 * joint.peak_torque_nm, joint.name


def test_nova_far_finger_joints_match_the_near_ones(nova):
    """站姿里远指间的角度已经按联动的比例摆好。"""
    for joint in nova.joints:
        if joint.follows is not None:
            near, far = angle_of(nova.body, joint.follows), angle_of(nova.body, joint.name)
            assert far == pytest.approx(joint.follow_ratio * near), joint.name
            assert far > 0


def test_nova_relaxed_angles_name_real_joints(nova):
    """放松的角度表里写的关节，模型里都有；手的每根手指都微微弯着；站姿里就是这些角度。"""
    keys = {joint.key for joint in nova.joints}
    assert set(RELAXED_DEG) <= keys
    bent = {joint.key for joint in hand_joints() if RELAXED_DEG.get(joint.key, 0) > 0}
    assert {"index_pip", "middle_pip", "ring_pip", "little_pip", "thumb_ip"} <= bent
    for key, degrees in RELAXED_DEG.items():
        for side in Side:
            assert angle_of(nova.body, f"{side.value}_{key}") == pytest.approx(math.radians(degrees))


@pytest.mark.parametrize("knee_deg", [100.0, 120.0], ids=["膝弯 100°", "深蹲"])
def test_nova_deep_squat_with_upright_trunk_is_rejected(nova, knee_deg):
    """躯干竖直时蹲不到底：踝最多转 45°，膝弯过 86° 以后重心到不了脚的中间。报错，不给一个站不住的姿势。"""
    with pytest.raises(PostureError, match="找不到让重心落在脚中间的站姿"):
        solve_stand_pose(nova.model, nova.body.anatomy, knee_deg)


def test_nova_pelvis_is_below_the_straight_standing_height(nova):
    """膝弯着，所以骨盆比站直的时候低。"""
    assert nova.stand.pelvis_height_m < nova.dimensions.hip_height


# 算法本身：一个最小的两条腿的身体 ----------------------------------------------------------------------


def tiny_biped(
    *,
    hip_axis=AXIS_LEFT,
    knee_axis=AXIS_LEFT,
    ankle_axis=AXIS_LEFT,
    hips_y=(0.1, -0.1),
    trunk_y=0.0,
    ankle_range=(-0.9, 0.9),
    foot_tilt_rad=0.0,
    free=True,
) -> tuple[mujoco.MjModel, Anatomy]:
    """躯干是一个盒子，每条腿是大腿、小腿、脚三段，三个关节都绕左右方向转。

    可以改：每个关节的正方向、两条腿的左右位置、躯干偏到哪一侧、踝能转多少、脚装得歪不歪、骨盆固定不固定。
    """
    spec = mujoco.MjSpec()
    spec.compiler.degree = False
    use_bench_settings(spec)
    add_floor(spec)
    trunk = spec.worldbody.add_body(name="trunk", pos=[0.0, 0.0, 1.0])
    if free:
        trunk.add_freejoint(name="root")
    box = mujoco.mjtGeom.mjGEOM_BOX
    trunk.add_geom(type=box, size=[0.1, 0.15, 0.2], pos=[0.0, trunk_y, 0.25], mass=TINY_TRUNK_KG)
    legs = {}
    for side, hip_y in zip(Side, hips_y, strict=True):
        name = side.value
        thigh = trunk.add_body(name=f"{name}_thigh", pos=[0.0, hip_y, 0.0])
        shank = thigh.add_body(name=f"{name}_shank", pos=[0.0, 0.0, -0.4])
        foot = shank.add_body(
            name=f"{name}_foot",
            pos=[0.0, 0.0, -0.4],
            quat=[math.cos(foot_tilt_rad / 2), 0.0, math.sin(foot_tilt_rad / 2), 0.0],
        )
        parts = (
            (thigh, "hip", hip_axis, (-2.0, 2.0)),
            (shank, "knee", knee_axis, (-2.5, 2.5)),
            (foot, "ankle", ankle_axis, ankle_range),
        )
        for part, joint, axis, limits in parts:
            part.add_joint(
                name=f"{name}_{joint}",
                type=mujoco.mjtJoint.mjJNT_HINGE,
                axis=list(axis),
                range=list(limits),
                limited=mujoco.mjtLimited.mjLIMITED_TRUE,
            )
            actuator = spec.add_actuator(
                name=f"{name}_{joint}", trntype=mujoco.mjtTrn.mjTRN_JOINT, target=f"{name}_{joint}"
            )
            actuator.set_to_position(kp=stiffness_for(TINY_PEAK_TORQUE_NM))
        capsule = mujoco.mjtGeom.mjGEOM_CAPSULE
        thigh.add_geom(type=capsule, size=[0.05, 0.0, 0.0], fromto=[0.0, 0.0, 0.0, 0.0, 0.0, -0.4], mass=2.0)
        shank.add_geom(type=capsule, size=[0.04, 0.0, 0.0], fromto=[0.0, 0.0, 0.0, 0.0, 0.0, -0.4], mass=1.0)
        foot.add_geom(type=box, size=[0.1, 0.04, 0.02], pos=[0.03, 0.0, -0.03], mass=0.5)
        foot.add_site(name=f"{name}_sole", pos=[0.03, 0.0, -0.05])
        legs[side] = Leg(f"{name}_hip", f"{name}_knee", f"{name}_ankle", f"{name}_foot", f"{name}_sole")
    return spec.compile(), Anatomy(root="trunk", trunk="trunk", legs=legs, relaxed_rad={})


def test_tiny_body_stands_upright_over_its_feet():
    """最小的身体也能算出站姿：躯干竖直，脚底贴地，重心在两只脚的正中间上面。"""
    model, anatomy = tiny_biped()
    pose = solve_stand_pose(model, anatomy)
    data = mujoco.MjData(model)
    data.qpos[:] = pose.qpos
    mujoco.mj_forward(model, data)
    assert data.xmat[model.body("trunk").id].reshape(3, 3) == pytest.approx(np.eye(3), abs=1e-12)
    for leg in anatomy.legs.values():
        assert data.site_xpos[model.site(leg.sole).id][Z] == pytest.approx(0.0, abs=1e-12)
        assert data.site_xpos[model.site(leg.sole).id][X] == pytest.approx(data.subtree_com[1][X], abs=1e-9)
    assert pose.hip_deg == pytest.approx(pose.knee_deg - pose.ankle_deg)


@pytest.mark.parametrize(
    ("hip_axis", "knee_axis", "ankle_axis"),
    [(AXIS_RIGHT, AXIS_RIGHT, AXIS_RIGHT), (AXIS_RIGHT, AXIS_LEFT, AXIS_RIGHT), (AXIS_LEFT, AXIS_RIGHT, AXIS_LEFT)],
    ids=["全部反过来", "髋和踝反过来（Nova 的定法）", "只有膝反过来"],
)
def test_pose_does_not_depend_on_which_way_joints_count_positive(hip_axis, knee_axis, ankle_axis):
    """关节往哪边算正，各个身体不一样。按动作说的站姿（膝弯、脚尖向上、髋向前抬）和要出的力矩大小都不变。"""
    usual_model, anatomy = tiny_biped()
    other_model, _ = tiny_biped(hip_axis=hip_axis, knee_axis=knee_axis, ankle_axis=ankle_axis)
    usual, other = solve_stand_pose(usual_model, anatomy), solve_stand_pose(other_model, anatomy)
    assert other.ankle_deg == pytest.approx(usual.ankle_deg, abs=1e-12)
    assert other.pelvis_height_m == pytest.approx(usual.pelvis_height_m, abs=1e-12)
    assert np.abs(other.qpos) == pytest.approx(np.abs(usual.qpos), abs=1e-12)
    assert np.abs(other.holding_torque_nm) == pytest.approx(np.abs(usual.holding_torque_nm), abs=1e-9)
    flipped = [axis != AXIS_LEFT for axis in (hip_axis, knee_axis, ankle_axis)] * 2
    for index, is_flipped in enumerate(flipped):
        sign = -1.0 if is_flipped else 1.0
        assert other.holding_torque_nm[index] == pytest.approx(sign * usual.holding_torque_nm[index], abs=1e-9)


def test_stand_targets_of_the_tiny_body_carry_the_holding_torque():
    """目标 = 角度 + 力矩 ÷ 刚度：膝是弯的，所以膝的目标和角度不一样。"""
    model, anatomy = tiny_biped()
    pose = solve_stand_pose(model, anatomy)
    stiffness = stiffness_for(TINY_PEAK_TORQUE_NM)
    for index in range(model.nu):
        angle = pose.qpos[model.jnt_qposadr[model.actuator_trnid[index, 0]]]
        assert pose.ctrl[index] == pytest.approx(angle + pose.holding_torque_nm[index] / stiffness)
    knee = [model.actuator(index).name for index in range(model.nu)].index("left_knee")
    assert abs(pose.holding_torque_nm[knee]) > 1.0


def test_weight_goes_to_the_foot_nearer_the_center_of_mass():
    """躯干偏向左侧时，左脚托的体重多，所以左腿的踝和膝出的力矩比右腿大。偏得越多差得越多。"""
    model, anatomy = tiny_biped(trunk_y=0.04)
    pose = solve_stand_pose(model, anatomy)
    names = [model.actuator(index).name for index in range(model.nu)]
    torque = dict(zip(names, pose.holding_torque_nm, strict=True))
    assert abs(torque["left_ankle"]) > abs(torque["right_ankle"]) > 0
    assert abs(torque["left_knee"]) > abs(torque["right_knee"]) > 0
    more_model, _ = tiny_biped(trunk_y=0.08)
    more = dict(zip(names, solve_stand_pose(more_model, anatomy).holding_torque_nm, strict=True))
    assert abs(more["left_ankle"]) > abs(torque["left_ankle"])
    assert abs(more["right_ankle"]) < abs(torque["right_ankle"])


def test_symmetric_body_splits_its_weight_in_half():
    """身体左右对称时，两条腿出的力矩一样。"""
    model, anatomy = tiny_biped()
    pose = solve_stand_pose(model, anatomy)
    half = model.nu // 2
    assert pose.holding_torque_nm[:half] == pytest.approx(pose.holding_torque_nm[half:], abs=1e-9)


def test_rejects_a_center_of_mass_outside_the_feet():
    """重心偏到两只脚的外面：站不住，报错。"""
    model, anatomy = tiny_biped(trunk_y=0.6)
    with pytest.raises(PostureError, match="重心不在两只脚之间"):
        solve_stand_pose(model, anatomy)


def test_rejects_feet_that_are_not_apart():
    """两只脚在左右方向上叠在一起：报错。"""
    model, anatomy = tiny_biped(hips_y=(0.1, 0.1))
    with pytest.raises(PostureError, match="两只脚在左右方向上没有分开"):
        solve_stand_pose(model, anatomy)


def test_rejects_an_ankle_that_cannot_turn_enough():
    """踝能转的范围太小，重心到不了脚的中间：报错。"""
    model, anatomy = tiny_biped(ankle_range=(-0.01, 0.01))
    with pytest.raises(PostureError, match="找不到让重心落在脚中间的站姿"):
        solve_stand_pose(model, anatomy, 30.0)


def test_rejects_a_foot_that_is_mounted_tilted():
    """脚装歪了的身体，"三个关节加起来是 0"摆出来脚底不平：报错，不给一个歪的站姿。"""
    model, anatomy = tiny_biped(foot_tilt_rad=0.2)
    with pytest.raises(PostureError, match="是歪的"):
        solve_stand_pose(model, anatomy)


def test_rejects_a_body_that_is_bolted_down():
    """骨盆没有自由关节（固定住的身体）：不用算站姿，报错。"""
    model, anatomy = tiny_biped(free=False)
    with pytest.raises(PostureError, match="没有自由关节"):
        solve_stand_pose(model, anatomy)


def test_rejects_a_body_with_one_leg():
    """只给了一条腿：报错。"""
    model, anatomy = tiny_biped()
    one_leg = replace(anatomy, legs={Side.LEFT: anatomy.legs[Side.LEFT]})
    with pytest.raises(PostureError, match="要两条腿才能站，这个身体有 1 条"):
        solve_stand_pose(model, one_leg)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"knee": "left_elbow"}, "模型里没有叫 left_elbow 的关节"),
        ({"foot": "left_hoof"}, "模型里没有叫 left_hoof 的身体"),
        ({"sole": "left_palm"}, "模型里没有叫 left_palm 的点"),
    ],
    ids=["没有的关节", "没有的身体", "没有的点"],
)
def test_rejects_names_that_are_not_in_the_model(change, message):
    """腿上写的名字模型里没有：说清楚是哪个名字。"""
    model, anatomy = tiny_biped()
    legs = {**anatomy.legs, Side.LEFT: replace(anatomy.legs[Side.LEFT], **change)}
    with pytest.raises(PostureError, match=message):
        solve_stand_pose(model, replace(anatomy, legs=legs))


def test_rejects_an_unknown_root_and_an_unknown_relaxed_joint():
    """骨盆的名字不对，或者放松的姿势里写了没有的关节：报错。"""
    model, anatomy = tiny_biped()
    with pytest.raises(PostureError, match="模型里没有叫 hips 的身体"):
        solve_stand_pose(model, replace(anatomy, root="hips"))
    with pytest.raises(PostureError, match="模型里没有叫 left_wing 的关节"):
        solve_stand_pose(model, replace(anatomy, relaxed_rad={"left_wing": 0.1}))


def test_rejects_a_leg_joint_that_does_not_turn_sideways_axis(nova):
    """拿一个不是绕左右方向转的关节（髋的侧摆）当膝：报错。"""
    anatomy = nova.body.anatomy
    legs = {**anatomy.legs, Side.LEFT: replace(anatomy.legs[Side.LEFT], knee="left_hip_roll")}
    with pytest.raises(PostureError, match="left_hip_roll 不是绕左右方向转的关节"):
        solve_stand_pose(nova.model, replace(anatomy, legs=legs))


def test_relaxed_angles_are_used_and_coupled_joints_follow(nova):
    """放松的姿势改了，站姿就跟着改；跟着别的关节动的关节按比例摆好。"""
    anatomy = nova.body.anatomy
    wider = replace(anatomy, relaxed_rad={**anatomy.relaxed_rad, "left_index_pip": 0.6, "right_index_pip": 0.6})
    pose = solve_stand_pose(nova.model, wider)
    model = nova.model
    assert pose.qpos[model.joint("left_index_pip").qposadr[0]] == pytest.approx(0.6)
    follower = next(joint for joint in nova.joints if joint.follows == "left_index_pip")
    assert pose.qpos[model.joint(follower.name).qposadr[0]] == pytest.approx(follower.follow_ratio * 0.6)


# 躯干竖直时能蹲多深 ----------------------------------------------------------------------------------


def test_deepest_knee_bend_is_the_last_one_that_still_stands(body):
    """躯干竖直时膝最多能弯到的角度：这个角度还摆得出站姿，再多 1° 就摆不出来了。"""
    deepest = deepest_knee_bend_deg(body)
    assert deepest > KNEE_BEND_DEG
    pose = solve_stand_pose(body.model, body.anatomy, deepest)
    assert pose.ankle_deg <= toe_up_limit_deg(body.model, body.anatomy)
    with pytest.raises(PostureError, match="找不到让重心落在脚中间的站姿"):
        solve_stand_pose(body.model, body.anatomy, deepest + 1.0)


def test_ankle_range_decides_how_deep_each_body_can_squat(nova, g1):
    """Nova 的踝让脚尖向上 45°，膝最多弯到 86°；G1 的踝能到 50°，膝能弯到 97°。"""
    assert toe_up_limit_deg(nova.model, nova.body.anatomy) == pytest.approx(45.0)
    assert toe_up_limit_deg(g1.model, g1.anatomy) == pytest.approx(50.0, abs=0.01)
    assert deepest_knee_bend_deg(nova.body) == 86.0
    assert deepest_knee_bend_deg(g1) == 97.0


def test_toe_up_limit_does_not_depend_on_which_way_the_ankle_counts_positive():
    """踝往哪边算正都一样：能让脚尖向上多少，看的是动作。"""
    usual, anatomy = tiny_biped(ankle_range=(-0.3, 0.9))
    flipped, _ = tiny_biped(ankle_axis=AXIS_RIGHT, ankle_range=(-0.9, 0.3))
    assert toe_up_limit_deg(usual, anatomy) == pytest.approx(math.degrees(0.3))
    assert toe_up_limit_deg(flipped, anatomy) == pytest.approx(math.degrees(0.3))


def test_coarser_steps_find_a_shallower_or_equal_bend(nova):
    """一格 5° 地试，找到的是不超过最深那个角度的 5 的倍数。"""
    assert deepest_knee_bend_deg(nova.body, step_deg=5.0) == 85.0


@pytest.mark.parametrize("step_deg", [0.0, -1.0], ids=["0 度", "负的"])
def test_rejects_a_step_that_is_not_positive(nova, step_deg):
    """每一格不是正数：拒绝。"""
    with pytest.raises(ValueError, match="每一格要大于 0 度"):
        deepest_knee_bend_deg(nova.body, step_deg)


def test_weak_motors_limit_how_deep_a_body_can_squat(nova):
    """电机太弱、顶不住的时候，能蹲的深度就由力矩定：峰值力矩只有原来的 2% 时，连 1° 都顶不住。"""
    weak = replace(
        nova.body,
        actuators=tuple(replace(item, peak_torque_nm=0.02 * item.peak_torque_nm) for item in nova.body.actuators),
    )
    with pytest.raises(PostureError, match="膝弯多少都站不住"):
        deepest_knee_bend_deg(weak)
    half = replace(
        nova.body,
        actuators=tuple(replace(item, peak_torque_nm=0.5 * item.peak_torque_nm) for item in nova.body.actuators),
    )
    assert deepest_knee_bend_deg(half) == deepest_knee_bend_deg(nova.body)


# 关节的范围 ------------------------------------------------------------------------------------------


def test_rejects_a_knee_bent_the_wrong_way(nova):
    """膝往前弯（负的角度）：Nova 的膝做不到，报错，说清楚是哪个关节。"""
    with pytest.raises(PostureError, match=r"站姿里 left_knee 要转到 -5\.0°，超出了它能转的范围"):
        solve_stand_pose(nova.model, nova.body.anatomy, -5.0)


def test_rejects_a_relaxed_angle_outside_the_joint_range(nova):
    """放松的姿势里写了关节转不到的角度（肘最多弯 150°）：报错，不给一个摆不出来的站姿。"""
    anatomy = nova.body.anatomy
    too_far = replace(anatomy, relaxed_rad={**anatomy.relaxed_rad, "left_elbow": math.radians(170.0)})
    with pytest.raises(PostureError, match=r"站姿里 left_elbow 要转到 170\.0°，超出了它能转的范围"):
        solve_stand_pose(nova.model, too_far)


def test_angle_right_at_the_end_of_the_range_is_accepted(nova):
    """正好在范围的边上（肘弯 150°）不算超出。"""
    anatomy = nova.body.anatomy
    at_the_end = replace(anatomy, relaxed_rad={**anatomy.relaxed_rad, "left_elbow": math.radians(150.0)})
    pose = solve_stand_pose(nova.model, at_the_end)
    assert pose.qpos[nova.model.joint("left_elbow").qposadr[0]] == pytest.approx(math.radians(150.0))
