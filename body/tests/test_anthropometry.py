"""人体测量的测试。"""

import pytest

from nova_body.anthropometry import (
    MASS_FRACTION,
    PAIRED_SEGMENTS,
    STANDING_CHAIN,
    Segment,
    human_segment_mass_kg,
    segment_count,
    segment_length_m,
)

NOVA_HEIGHT_M = 1.70


def test_standing_chain_adds_up_to_height():
    """从脚底到头顶的几段，长度加起来等于身高。"""
    total = sum(segment_length_m(segment, NOVA_HEIGHT_M) for segment in STANDING_CHAIN)
    assert total == pytest.approx(NOVA_HEIGHT_M)


def test_mass_fractions_add_up_to_whole_body():
    """各段的质量比例加起来是 1（成对的段算两侧）。"""
    total = sum(MASS_FRACTION[segment] * segment_count(segment) for segment in Segment)
    assert total == pytest.approx(1.0)


@pytest.mark.parametrize("segment", list(Segment), ids=[segment.value for segment in Segment])
def test_only_limb_segments_are_paired(segment):
    """手臂和腿的段有 2 个，头和躯干只有 1 个。"""
    expected = 2 if segment in PAIRED_SEGMENTS else 1
    assert segment_count(segment) == expected
    assert (segment in {Segment.HEAD, Segment.TORSO}) == (expected == 1)


def test_forearm_length_matches_human_proportion():
    """1.70 m 的人，前臂约 0.25 m。"""
    assert segment_length_m(Segment.FOREARM, NOVA_HEIGHT_M) == pytest.approx(0.248, abs=0.001)


def test_human_segment_mass_scales_with_body_mass():
    """体重翻倍，每一段的质量也翻倍。"""
    assert human_segment_mass_kg(Segment.THIGH, 140.0) == pytest.approx(2 * human_segment_mass_kg(Segment.THIGH, 70.0))


@pytest.mark.parametrize("height_m", [0.0, -1.7], ids=["身高是 0", "身高是负数"])
def test_rejects_non_positive_height(height_m):
    """身高不是正数时拒绝。"""
    with pytest.raises(ValueError, match="身高必须大于 0"):
        segment_length_m(Segment.THIGH, height_m)


@pytest.mark.parametrize("body_mass_kg", [0.0, -70.0], ids=["体重是 0", "体重是负数"])
def test_rejects_non_positive_body_mass(body_mass_kg):
    """体重不是正数时拒绝。"""
    with pytest.raises(ValueError, match="体重必须大于 0"):
        human_segment_mass_kg(Segment.THIGH, body_mass_kg)
