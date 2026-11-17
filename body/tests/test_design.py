"""关节表的测试：和机体规格、核心和待证明的清单对得上。"""

import pytest

from nova_body.anthropometry import Segment
from nova_body.design import (
    CORE_BODY,
    DAILY_TARGETS,
    FULL_BODY,
    HAND_ALL_TENDON,
    HAND_HYBRID,
    HAND_IN_HAND,
    JOINT_GROUPS,
    Drive,
    JointGroup,
    Strength,
    Tag,
)


def test_full_body_matches_spec():
    """完整版是 98 个自由度、90 个驱动器（机体规格第 2 节）。"""
    assert FULL_BODY.total_dof() == 98
    assert FULL_BODY.total_actuators() == 90


def test_core_body_matches_scope_list():
    """核心版是 75 个自由度（核心和待证明第 3 节）。"""
    assert CORE_BODY.total_dof() == 75


def test_core_body_has_only_core_joints():
    """核心版里只有标了"核心"的关节。"""
    assert {group.tag for group in CORE_BODY.joint_groups()} == {Tag.CORE}


def test_full_body_contains_every_joint_group():
    """完整版包含全部的关节组。"""
    assert FULL_BODY.joint_groups() == JOINT_GROUPS


def test_joint_group_keys_are_unique():
    """每组关节的名字不重复。"""
    keys = [group.key for group in JOINT_GROUPS]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("hand", [HAND_ALL_TENDON, HAND_IN_HAND, HAND_HYBRID], ids=["全肌腱", "驱动放在手里", "混合"])
def test_every_hand_has_22_joints(hand):
    """三种手都是 22 个关节，只是里面的驱动不同。"""
    assert hand.dof == 22


def test_parallel_pair_shares_the_load():
    """并联的一组：每个驱动器出两个力矩之和的一半（踝按人的峰值：250 和 100，各出 175）。"""
    ankle = next(group for group in JOINT_GROUPS if group.key == "ankle")
    assert ankle.actuator_torques_nm(Strength.HUMAN_PEAK) == (175.0, 175.0)
    pitch, roll = ankle.daily_torques_nm
    assert ankle.actuator_torques_nm(Strength.DAILY) == ((pitch + roll) / 2, (pitch + roll) / 2)


def test_fixed_mass_group_has_no_torques():
    """按固定重量估的组不给力矩，哪一档力量都一样。"""
    eyes = next(group for group in JOINT_GROUPS if group.key == "eyes")
    assert eyes.actuator_torques_nm(Strength.DAILY) == ()
    assert eyes.actuator_torques_nm(Strength.HUMAN_PEAK) == ()


def test_daily_strength_uses_the_motion_targets_where_there_are_some():
    """做家务的那一档：动作算出了目标的组用目标，没算出来的（颈）还用人的峰值。"""
    groups = {group.key: group for group in JOINT_GROUPS}
    knee, neck = groups["knee"], groups["neck_upper"]
    assert knee.spec_torques_nm(Strength.DAILY) == knee.daily_torques_nm
    assert knee.spec_torques_nm(Strength.HUMAN_PEAK) == knee.peak_torques_nm == (300.0,)
    assert neck.daily_torques_nm == ()
    assert neck.spec_torques_nm(Strength.DAILY) == neck.peak_torques_nm


def test_every_target_has_one_value_per_degree_of_freedom():
    """写进设计的目标：每个自由度一个力矩、一个转速，都是正的，组的名字都认得。"""
    keys = {group.key for group in JOINT_GROUPS}
    for key, (torques, speeds) in DAILY_TARGETS.items():
        group = next(group for group in JOINT_GROUPS if group.key == key)
        assert key in keys
        assert len(torques) == len(speeds) == group.dof
        assert all(value > 0 for value in (*torques, *speeds))


@pytest.mark.parametrize("field", ["daily_torques_nm", "speeds_rad_s"], ids=["力矩", "转速"])
def test_rejects_targets_whose_count_differs_from_dof(field):
    """目标的个数和自由度对不上：拒绝。"""
    with pytest.raises(ValueError, match="有 1 个自由度"):
        JointGroup("x", "x", Segment.THIGH, True, 1, 1, Drive.ROTARY, Tag.CORE, (10.0,), **{field: (1.0, 2.0)})


def test_rejects_torque_count_that_differs_from_dof():
    """力矩的个数和自由度对不上时拒绝。"""
    with pytest.raises(ValueError, match="2 个自由度，却给了 1 个力矩"):
        JointGroup("bad", "写错的关节", Segment.CHEST, False, 2, 2, Drive.ROTARY, Tag.CORE, (10.0,))


def test_rejects_parallel_group_that_is_not_a_pair():
    """并联的一组必须是 2 个自由度、2 个驱动器。"""
    with pytest.raises(ValueError, match="并联的一组必须是 2 个自由度、2 个驱动器"):
        JointGroup("bad", "写错的并联", Segment.CHEST, False, 1, 1, Drive.ROTARY, Tag.CORE, (10.0,), parallel=True)
