"""骨架的测试：关节和机体规格、关节表对得上；左右镜像是对的；尺寸加起来是身高。"""

import math
import re
from dataclasses import fields

import numpy as np
import pytest

from nova_body.design import CORE_BODY
from nova_body.skeleton import (
    LINKS,
    ROOT_LINK,
    SHOULDER_BREADTH_RATIO,
    Dimensions,
    Joint,
    Side,
    link,
    mirror_axis,
    mirror_point,
    side_prefix,
    sides_of,
    sole_site,
)

NOVA_HEIGHT_M = 1.70
BODY_DOF = 31

SPEC_RANGES_DEG = {
    "lumbar_yaw": (-45, 45),
    "lumbar_roll": (-35, 35),
    "lumbar_pitch": (-25, 80),
    "neck_yaw": (-75, 75),
    "neck_pitch": (-50, 45),
    "shoulder_pitch": (-60, 180),
    "shoulder_roll": (-30, 180),
    "shoulder_yaw": (-70, 90),
    "elbow": (0, 150),
    "forearm_roll": (-80, 80),
    "wrist_flex": (-70, 80),
    "wrist_deviation": (-30, 20),
    "hip_pitch": (-30, 130),
    "hip_roll": (-30, 60),
    "hip_yaw": (-45, 45),
    "knee": (0, 150),
    "ankle_pitch": (-50, 20),
    "ankle_roll": (-20, 35),
}


def all_joints() -> list[Joint]:
    """骨架里一侧的全部关节。"""
    return [joint for part in LINKS for joint in part.joints]


def rotate(vector, axis, angle: float) -> np.ndarray:
    """把一个向量绕一根轴转一个角度（罗德里格斯公式）。"""
    vector, axis = np.asarray(vector, dtype=float), np.asarray(axis, dtype=float)
    return (
        vector * math.cos(angle)
        + np.cross(axis, vector) * math.sin(angle)
        + axis * np.dot(axis, vector) * (1 - math.cos(angle))
    )


def test_body_has_31_joints():
    """身体（不算手）是 31 个自由度：腿 12、腰 3、手臂 14、颈 2。"""
    total = sum(len(part.joints) * len(sides_of(part)) for part in LINKS)
    assert total == BODY_DOF


def test_every_core_joint_group_is_fully_covered():
    """核心版的每组关节，骨架里正好每个自由度有一个关节，不多不少。"""
    covered = sorted((joint.group, joint.index) for joint in all_joints())
    expected = sorted((group.key, index) for group in CORE_BODY.joint_groups() for index in range(group.dof))
    assert covered == expected


def test_joint_keys_are_unique():
    """关节的名字不重复。"""
    keys = [joint.key for joint in all_joints()]
    assert len(keys) == len(set(keys))


def test_paired_joints_belong_to_paired_groups():
    """左右各一个的段，它的关节组在关节表里也是成对的；中间的段反过来。"""
    groups = {group.key: group for group in CORE_BODY.joint_groups()}
    for part in LINKS:
        for joint in part.joints:
            assert groups[joint.group].paired == part.paired, joint.name


def test_links_form_a_tree_from_the_pelvis():
    """从骨盆开始是一棵树：每一段的上一段都排在它前面。"""
    seen: set[str] = set()
    for part in LINKS:
        if part.key == ROOT_LINK:
            assert part.parent is None
        else:
            assert part.parent in seen, part.name
        seen.add(part.key)


@pytest.mark.parametrize("key", list(SPEC_RANGES_DEG), ids=list(SPEC_RANGES_DEG))
def test_joint_range_matches_spec(key):
    """每个关节的范围和机体规格第 2 节的"关节范围"一样。"""
    joint = next(joint for joint in all_joints() if joint.key == key)
    assert (joint.lower_deg, joint.upper_deg) == SPEC_RANGES_DEG[key]


def test_every_joint_axis_is_a_unit_vector():
    """转轴都是单位长度。"""
    for joint in all_joints():
        assert np.linalg.norm(joint.axis) == pytest.approx(1.0), joint.name


def test_joint_rejects_empty_range():
    """范围的下限不小于上限时拒绝。"""
    with pytest.raises(ValueError, match=re.escape("下限 10.0° 必须小于上限 10.0°")):
        Joint("bad", "写错的关节", "knee", 0, (0.0, 1.0, 0.0), 10.0, 10.0, "弯")


def test_link_lookup():
    """能按名字找到一段；没有的名字报错。"""
    assert link("thigh").name == "大腿"
    with pytest.raises(KeyError, match="没有 tail 这一段"):
        link("tail")


@pytest.mark.parametrize(
    ("side", "expected"),
    [(Side.LEFT, (1.0, 2.0, 3.0)), (Side.RIGHT, (1.0, -2.0, 3.0)), (None, (1.0, 2.0, 3.0))],
    ids=["左侧不变", "右侧 y 反过来", "中间不变"],
)
def test_mirror_point(side, expected):
    """位置换到另一侧：只有右侧把 y 反过来。"""
    assert mirror_point((1.0, 2.0, 3.0), side) == expected


@pytest.mark.parametrize(
    ("side", "expected"),
    [(Side.LEFT, (1.0, 2.0, 3.0)), (Side.RIGHT, (-1.0, 2.0, -3.0)), (None, (1.0, 2.0, 3.0))],
    ids=["左侧不变", "右侧 x 和 z 反过来", "中间不变"],
)
def test_mirror_axis(side, expected):
    """转轴换到另一侧：只有右侧把 x 和 z 反过来。"""
    assert mirror_axis((1.0, 2.0, 3.0), side) == expected


@pytest.mark.parametrize("joint", all_joints(), ids=[joint.key for joint in all_joints()])
def test_right_side_rotation_mirrors_the_left(joint):
    """右侧绕镜像的轴转同样的角度，结果正好是左侧的镜像：同一个正方向是同一个动作。"""
    point, angle = (0.3, 0.2, -0.5), 0.7
    left = rotate(point, joint.axis, angle)
    right = rotate(mirror_point(point, Side.RIGHT), mirror_axis(joint.axis, Side.RIGHT), angle)
    assert right == pytest.approx(np.array(mirror_point(tuple(left), Side.RIGHT)))


def test_names_in_the_model():
    """模型里的名字：左右侧带前缀，中间的不带。"""
    assert side_prefix(Side.LEFT) == "left_"
    assert side_prefix(Side.RIGHT) == "right_"
    assert side_prefix(None) == ""
    assert sole_site(Side.RIGHT) == "right_sole"
    assert sides_of(link("thigh")) == (Side.LEFT, Side.RIGHT)
    assert sides_of(link("chest")) == (None,)


def test_dimensions_add_up_to_height():
    """从脚底到头顶：踝、小腿、大腿、骨盆、胸、颈、头，加起来是身高。"""
    d = Dimensions.for_height(NOVA_HEIGHT_M)
    total = d.shoulder_height + d.neck_joint_above_shoulder + d.head_top_above_neck_joint
    assert total == pytest.approx(NOVA_HEIGHT_M)
    assert d.hip_height == pytest.approx(0.530 * NOVA_HEIGHT_M)
    assert d.shoulder_height == pytest.approx(0.818 * NOVA_HEIGHT_M)


def test_arm_reaches_mid_thigh():
    """手臂垂下来，指尖在大腿中间的高度（人也是）。"""
    d = Dimensions.for_height(NOVA_HEIGHT_M)
    fingertip_height = d.shoulder_height - d.upper_arm_length - d.forearm_length - d.hand_length
    knee_height = d.ankle_height + d.shank_length
    assert knee_height < fingertip_height < d.hip_height


def test_shoulders_are_as_wide_as_a_person():
    """肩最外侧的宽度是身高的 0.259；手臂垂下来不碰到胸和骨盆的外壳。"""
    d = Dimensions.for_height(NOVA_HEIGHT_M)
    assert 2 * (d.shoulder_half_spacing + d.upper_arm_radius) == pytest.approx(SHOULDER_BREADTH_RATIO * NOVA_HEIGHT_M)
    assert d.shoulder_half_spacing - d.upper_arm_radius > d.chest_half_width


def test_feet_do_not_overlap():
    """两只脚之间有空隙；踝在脚里面。"""
    d = Dimensions.for_height(NOVA_HEIGHT_M)
    assert d.hip_half_spacing > d.foot_width / 2
    assert 0 < d.heel_behind_ankle < d.foot_length
    assert d.sole_thickness < d.ankle_height


def test_dimensions_scale_with_height():
    """身高翻倍，每个尺寸都翻倍。"""
    small, large = Dimensions.for_height(1.0), Dimensions.for_height(2.0)
    for field in fields(Dimensions):
        assert getattr(large, field.name) == pytest.approx(2 * getattr(small, field.name)), field.name


@pytest.mark.parametrize("height_m", [0.0, -1.7], ids=["身高是 0", "身高是负数"])
def test_dimensions_reject_non_positive_height(height_m):
    """身高不是正数时拒绝。"""
    with pytest.raises(ValueError, match="身高必须大于 0"):
        Dimensions.for_height(height_m)
