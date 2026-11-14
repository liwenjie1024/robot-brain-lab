"""手的骨架的测试：和机体规格 3.2 节对得上。"""

import numpy as np
import pytest

from nova_body.design import HAND_IN_HAND
from nova_body.hand import (
    DIGITS,
    PALM_ARCH,
    PALM_ARCH_PIVOT,
    RADIAL_PALM_SPAN,
    THUMB_DIRECTION,
    THUMB_LIFT_AXIS,
    ULNAR_PALM_SPAN,
    from_hand,
    hand_actuated_joints,
    hand_joints,
    hand_mass_fractions_total,
)
from nova_body.skeleton import Side

FINGERS = ("index", "middle", "ring", "little")

SPEC_RANGES_DEG = {
    "palm_arch": (0, 20),
    "thumb_cmc_lift": (0, 50),
    "thumb_mcp_flex": (0, 60),
    "thumb_mcp_spread": (-10, 10),
    "thumb_ip": (0, 80),
    **{f"{finger}_mcp_spread": (-20, 20) for finger in FINGERS},
    **{f"{finger}_mcp_flex": (-30, 90) for finger in FINGERS},
    **{f"{finger}_pip": (0, 105) for finger in FINGERS},
    **{f"{finger}_dip": (0, 80) for finger in FINGERS},
}


def joint(key: str):
    """按名字找手的一个关节。"""
    return next(candidate for candidate in hand_joints() if candidate.key == key)


def test_hand_has_22_joints_and_18_motors():
    """一只手 22 个关节、18 个小电机，和关节表里"驱动放在手里"的手一样。"""
    assert len(hand_joints()) == HAND_IN_HAND.dof
    assert len(hand_actuated_joints()) == HAND_IN_HAND.actuators


def test_joint_keys_are_unique():
    """手的关节名字不重复。"""
    keys = [candidate.key for candidate in hand_joints()]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("key", list(SPEC_RANGES_DEG), ids=list(SPEC_RANGES_DEG))
def test_joint_range_matches_spec(key):
    """每个关节的范围和机体规格 3.2 节一样。"""
    assert (joint(key).lower_deg, joint(key).upper_deg) == SPEC_RANGES_DEG[key]


def test_thumb_base_bends_about_50_degrees():
    """拇指腕掌的弯伸一共约 50°。"""
    bend = joint("thumb_cmc_flex")
    assert bend.upper_deg - bend.lower_deg == 50


@pytest.mark.parametrize("finger", FINGERS, ids=FINGERS)
def test_far_joint_follows_near_joint(finger):
    """远指间没有电机，跟着同一根手指的近指间动：近指间弯到头（105°）时，远指间正好也到头（80°）。"""
    far = joint(f"{finger}_dip")
    near = joint(f"{finger}_pip")
    assert far.peak_torque_nm is None
    assert far.follows == near.key
    assert far.follow_ratio * near.upper_deg == pytest.approx(far.upper_deg)


def test_only_far_joints_have_no_motor():
    """没有电机的只有 4 个远指间。"""
    without_motor = {candidate.key for candidate in hand_joints() if candidate.peak_torque_nm is None}
    assert without_motor == {f"{finger}_dip" for finger in FINGERS}


def test_hand_mass_fractions_add_up():
    """手掌和各节手指的重量比例加起来是 1。"""
    assert hand_mass_fractions_total() == pytest.approx(1.0)


def test_middle_fingertip_is_one_hand_length_from_the_wrist():
    """中指的指尖离手腕正好一个手长。"""
    middle = next(digit for digit in DIGITS if digit.key == "middle")
    reach = middle.base[0] + sum(phalanx.length_ratio for phalanx in middle.phalanges)
    assert reach == pytest.approx(1.0)


def test_middle_finger_is_the_longest():
    """中指伸得最远，小指最近。"""
    reach = {
        digit.key: digit.base[0] + sum(phalanx.length_ratio for phalanx in digit.phalanges)
        for digit in DIGITS
        if digit.key in FINGERS
    }
    assert max(reach, key=reach.get) == "middle"
    assert min(reach, key=reach.get) == "little"


def test_ring_and_little_fingers_are_on_the_cupping_half():
    """无名指和小指长在能拢起来的那半边手掌上，别的手指不在。"""
    assert {digit.key for digit in DIGITS if digit.on_ulnar_palm} == {"ring", "little"}


def test_finger_bases_sit_on_their_half_of_the_palm():
    """每根手指的指根都在它那半边手掌的宽度里；两半手掌在拢起来的转轴那里相接。"""
    for digit in DIGITS:
        _, (low, high) = ULNAR_PALM_SPAN if digit.on_ulnar_palm else RADIAL_PALM_SPAN
        assert low < digit.base[1] < high, digit.name
    assert ULNAR_PALM_SPAN[1][1] == RADIAL_PALM_SPAN[1][0] == PALM_ARCH_PIVOT[1]


def test_palm_arch_has_a_motor():
    """手掌拢起来有自己的电机。"""
    assert PALM_ARCH.peak_torque_nm is not None
    assert PALM_ARCH in hand_joints()


@pytest.mark.parametrize(
    ("side", "toward_palm"),
    [(Side.LEFT, (0.0, -1.0, 0.0)), (Side.RIGHT, (0.0, 1.0, 0.0))],
    ids=["左手的手心朝右", "右手的手心朝左"],
)
def test_hand_directions_in_body_coordinates(side, toward_palm):
    """手垂着的时候：指尖朝下，拇指一侧朝前，手心朝身体。"""
    assert from_hand((1.0, 0.0, 0.0), side) == (0.0, 0.0, -1.0)
    assert from_hand((0.0, 1.0, 0.0), side) == (1.0, 0.0, 0.0)
    assert from_hand((0.0, 0.0, 1.0), side) == pytest.approx(toward_palm)


def test_thumb_lift_axis_is_square_to_thumb_and_palm():
    """拇指往手心抬的转轴，和拇指的方向、手心的方向都垂直，长度是 1。"""
    thumb = np.array(from_hand(THUMB_DIRECTION, Side.LEFT))
    palm = np.array(from_hand((0.0, 0.0, 1.0), Side.LEFT))
    assert np.linalg.norm(THUMB_LIFT_AXIS) == pytest.approx(1.0)
    assert np.dot(THUMB_LIFT_AXIS, thumb) == pytest.approx(0.0)
    assert np.dot(THUMB_LIFT_AXIS, palm) == pytest.approx(0.0)
    # 绕这根轴往正方向转，拇指是转向手心的。
    assert np.cross(thumb, palm) == pytest.approx(np.array(THUMB_LIFT_AXIS))
