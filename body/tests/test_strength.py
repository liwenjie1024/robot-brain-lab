import math

import mujoco
import numpy as np
import pytest

from nova_body.design import JOINT_GROUPS, TorqueRule
from nova_body.motions import LEAN_MARGIN_M, Level, Motion, MotionBuilder
from nova_body.strength import (
    G1,
    MOTIONS,
    NOVA,
    REFERENCE_BODY_MASS_KG,
    SPEED_MARGIN,
    TORQUE_MARGIN,
    MotionDemand,
    MotionEntry,
    Task,
    Uses,
    can_do,
    group_targets,
    joint_needs,
    measure_motion,
    motion_entry,
    parallel_pairs,
    run_tasks,
    tasks_for,
)


def demand_of(body, key: str, *, torques, speeds=None, level=Level.CORE, feasible=True, shared=None) -> MotionDemand:
    """一个做好了的动作的结果（测试用：直接给每个关节的力矩和转速）。"""
    count = len(body.joints)
    return MotionDemand(
        key=key,
        name=key,
        description="",
        level=level,
        feasible=feasible,
        duration_s=1.0,
        reach_error_m=0.0,
        balance_error_m=0.0,
        torques_nm=np.asarray(torques, dtype=float),
        torque_times_s=np.zeros(count),
        speeds_rad_s=np.zeros(count) if speeds is None else np.asarray(speeds, dtype=float),
        shared_nm=shared or {},
        edge_margin_m=0.01,
        friction_ratio=0.1,
        unbalanced_n=0.0,
    )


def index_of(body, name: str) -> int:
    return [joint.name for joint in body.joints].index(name)


# 动作的清单 ------------------------------------------------------------------------------------------


def test_motion_keys_are_unique_and_can_be_found():
    """每个动作的名字不重复，按名字找得到；没有的名字报错。"""
    keys = [entry.key for entry in MOTIONS]
    assert len(keys) == len(set(keys))
    assert motion_entry("squat").name == "蹲到底再站起"
    with pytest.raises(KeyError, match="no_such_motion"):
        motion_entry("no_such_motion")


def test_the_plan_names_every_kind_of_motion():
    """P1 计划里说的：走、上下楼、蹲起、端东西，都在清单里。"""
    keys = {entry.key for entry in MOTIONS}
    assert {"walk", "stairs_up", "stairs_down", "squat", "lift_box", "carry_walk"} <= keys


def test_baseline_only_does_the_motions_that_need_legs(g1):
    """G1 没有手心、膝盖的点：只做只用腿的动作。Nova 全部都做。"""
    builder = MotionBuilder(g1)
    names = [task.motion for task in tasks_for(g1, G1)]
    assert names == [entry.key for entry in MOTIONS if entry.uses is Uses.LEGS]
    assert not any(can_do(builder, entry) for entry in MOTIONS if entry.uses is not Uses.LEGS)


def test_nova_does_every_motion(nova):
    """Nova 有手心、膝盖、脚尖的点：清单里的动作都做。"""
    assert [task.motion for task in tasks_for(nova.body, NOVA)] == [entry.key for entry in MOTIONS]


# 量一个动作 ------------------------------------------------------------------------------------------


def test_motion_that_cannot_be_done_is_not_measured(g1):
    """做不出来的动作（脚差得太多）：不算逆动力学，力矩、转速都是 nan。"""
    builder = MotionBuilder(g1)
    impossible = Motion("x", "做不出来的", "", Level.CORE, 0.01, [], reach_error_m=1.0, balance_error_m=0.0)
    entry = MotionEntry("x", "做不出来的", "", Uses.LEGS, lambda _builder, _entry: impossible)
    result = measure_motion(g1, builder, entry)
    assert not result.feasible
    assert np.isnan(result.torques_nm).all()
    assert np.isnan(result.speeds_rad_s).all()


def test_measuring_a_real_motion_gives_the_ankle_torque_of_leaning(g1):
    """真的做一遍"前倾、后仰"（一个进程里算）：做得出来；踝要的力矩比"一半体重 x 重心停着时到踝的前后距离"
    大一点（重心在动，停下来的时候压力中心比重心更靠外），但不会超过压力中心到了脚尖（脚跟）外 1 cm 的时候。"""
    (result,) = run_tasks([Task(G1, "lean")], workers=1)
    assert result.feasible
    mass = float(g1.model.body_subtreemass[g1.model.body(g1.anatomy.root).id])
    leg = g1.anatomy.legs["left"]
    ankle = result.torques_nm[index_of(g1, leg.ankle_pitch)]
    builder = MotionBuilder(g1)
    data = mujoco.MjData(g1.model)
    data.qpos[:] = g1.stand.qpos
    mujoco.mj_kinematics(g1.model, data)
    ankle_x = data.xanchor[g1.model.joint(leg.ankle_pitch).id][0]
    sole_x = builder.soles["left"][0]
    front = sole_x + g1.foot_length_m / 2 - LEAN_MARGIN_M - ankle_x
    back = ankle_x - (sole_x - g1.foot_length_m / 2 + LEAN_MARGIN_M)
    half_weight = mass / 2 * 9.81
    assert half_weight * max(front, back) <= ankle <= half_weight * (max(front, back) + LEAN_MARGIN_M + 0.01)
    assert np.isfinite(result.torques_nm).all()


def test_tasks_keep_their_order(g1):
    """一起算很多个动作，结果的顺序和给的一样。"""
    results = run_tasks([Task(G1, "lean"), Task(G1, "squat")], workers=1)
    assert [result.key for result in results] == ["lean", "squat"]


# 汇总 ------------------------------------------------------------------------------------------------


def test_joint_need_is_the_largest_over_the_motions_that_count(g1):
    """每个关节取做得出来的核心动作里最大的那个；做不出来的、运动员级的不算。"""
    count = len(g1.joints)
    knee = index_of(g1, g1.anatomy.legs["left"].knee)
    small, big, huge = np.zeros(count), np.zeros(count), np.zeros(count)
    small[knee], big[knee], huge[knee] = 10.0, 40.0, 500.0
    demands = [
        demand_of(g1, "a", torques=small, speeds=small),
        demand_of(g1, "b", torques=big, speeds=big),
        demand_of(g1, "c", torques=huge, speeds=huge, feasible=False),
        demand_of(g1, "d", torques=huge, speeds=huge, level=Level.REFERENCE),
    ]
    need = next(need for need in joint_needs(g1, demands) if need.name == g1.anatomy.legs["left"].knee)
    assert (need.torque_nm, need.torque_motion, need.speed_rad_s, need.speed_motion) == (40.0, "b", 40.0, "b")


def test_joint_needs_require_at_least_one_motion_that_counts(g1):
    """一个能做的核心动作都没有：报错。"""
    count = len(g1.joints)
    with pytest.raises(ValueError, match="没有一个能做的核心动作"):
        joint_needs(g1, [demand_of(g1, "a", torques=np.zeros(count), feasible=False)])


def test_hand_joints_are_not_given_targets(nova):
    """手指不算：手里的力（抓多紧）不是这些动作能算出来的。"""
    body = nova.body
    count = len(body.joints)
    needs = joint_needs(body, [demand_of(body, "a", torques=np.ones(count), speeds=np.ones(count))])
    assert all("指" not in need.label for need in needs)


def test_group_targets_add_margins_and_scale_with_body_mass(nova):
    """目标 = 动作里最大的 x 1.5（转速 x 1.3），左右取大的；随体重的组按 70 kg 折算，手臂的不折算。"""
    body = nova.body
    count = len(body.joints)
    torques, speeds = np.ones(count), np.ones(count)
    torques[index_of(body, "left_knee")], torques[index_of(body, "right_knee")] = 100.0, 120.0
    speeds[index_of(body, "left_knee")] = 6.0
    torques[index_of(body, "left_elbow")] = 20.0
    mass = 80.0
    demands = [demand_of(body, "a", torques=torques, speeds=speeds)]
    targets = {target.group.key: target for target in group_targets(joint_needs(body, demands), demands, mass)}
    knee, elbow = targets["knee"], targets["elbow"]
    assert knee.group.torque_rule is TorqueRule.BODY_MASS
    assert knee.daily_torques_nm == pytest.approx((120.0 * TORQUE_MARGIN * REFERENCE_BODY_MASS_KG / mass,))
    assert knee.speed_targets_rad_s == pytest.approx((6.0 * SPEED_MARGIN,))
    assert elbow.daily_torques_nm == pytest.approx((20.0 * TORQUE_MARGIN,))


def test_parallel_groups_use_the_largest_simultaneous_share(nova):
    """并联的一组（踝）：每个驱动器的目标是"同一刻两个力矩之和的一半"里最大的，留余地、折算。"""
    body = nova.body
    count = len(body.joints)
    shared = {("left_ankle_pitch", "left_ankle_roll"): 30.0, ("right_ankle_pitch", "right_ankle_roll"): 50.0}
    demands = [demand_of(body, "a", torques=np.ones(count), speeds=np.ones(count), shared=shared)]
    targets = {target.group.key: target for target in group_targets(joint_needs(body, demands), demands, 70.0)}
    assert targets["ankle"].shared_nm == pytest.approx(50.0 * TORQUE_MARGIN)
    assert targets["knee"].shared_nm is None


def test_parallel_pairs_follow_the_design_groups(nova, g1):
    """Nova 里并联的关节：腰（前后、侧弯）、左右的腕、左右的踝；G1 的关节名字和设计对不上，没有。"""
    pairs = set(parallel_pairs(nova.body))
    expected_groups = {group.key for group in JOINT_GROUPS if group.parallel}
    assert ("lumbar_pitch", "lumbar_roll") in pairs
    assert {("left_ankle_pitch", "left_ankle_roll"), ("right_ankle_pitch", "right_ankle_roll")} <= pairs
    assert {("left_wrist_flex", "left_wrist_deviation"), ("right_wrist_flex", "right_wrist_deviation")} <= pairs
    assert len(pairs) == 5
    assert "ankle" in expected_groups
    assert parallel_pairs(g1) == []


def test_design_targets_match_what_the_motions_ask_for_in_shape(nova):
    """写进设计的目标，每组的个数和这一遍能算出的目标一样（数在力量的报告里对）。"""
    body = nova.body
    count = len(body.joints)
    demands = [demand_of(body, "a", torques=np.ones(count), speeds=np.ones(count))]
    for target in group_targets(joint_needs(body, demands), demands, 70.0):
        if target.group.daily_torques_nm:
            assert len(target.group.daily_torques_nm) == len(target.daily_torques_nm)
            assert not any(math.isnan(value) for value in target.daily_torques_nm)
