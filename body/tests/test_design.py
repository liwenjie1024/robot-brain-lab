"""关节表的测试：和机体规格、核心和待证明的清单对得上。"""

import pytest

from nova_body.anthropometry import Segment
from nova_body.design import (
    CORE_BODY,
    FULL_BODY,
    HAND_ALL_TENDON,
    HAND_HYBRID,
    HAND_IN_HAND,
    JOINT_GROUPS,
    Drive,
    JointGroup,
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
    """并联的一组：每个驱动器出两个力矩之和的一半（踝：250 和 100，各出 175）。"""
    ankle = next(group for group in JOINT_GROUPS if group.key == "ankle")
    assert ankle.actuator_torques_nm() == (175.0, 175.0)


def test_fixed_mass_group_has_no_torques():
    """按固定重量估的组不给力矩。"""
    eyes = next(group for group in JOINT_GROUPS if group.key == "eyes")
    assert eyes.actuator_torques_nm() == ()


def test_rejects_torque_count_that_differs_from_dof():
    """力矩的个数和自由度对不上时拒绝。"""
    with pytest.raises(ValueError, match="2 个自由度，却给了 1 个力矩"):
        JointGroup("bad", "写错的关节", Segment.TORSO, False, 2, 2, Drive.ROTARY, Tag.CORE, (10.0,))


def test_rejects_parallel_group_that_is_not_a_pair():
    """并联的一组必须是 2 个自由度、2 个驱动器。"""
    with pytest.raises(ValueError, match="并联的一组必须是 2 个自由度、2 个驱动器"):
        JointGroup("bad", "写错的并联", Segment.TORSO, False, 1, 1, Drive.ROTARY, Tag.CORE, (10.0,), parallel=True)
