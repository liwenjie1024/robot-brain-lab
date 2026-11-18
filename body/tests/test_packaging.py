"""放不放得下的测试：驱动器的大小和真实产品对得上、越重越大；骨盆里的东西加起来和骨盆比；推杆只算分到骨盆的那一半。"""

import math
from dataclasses import replace

import pytest

from nova_body.packaging import SIZE_SAMPLES, USABLE_SHARE, Content, SegmentFit, drive_size_m, pelvis_fit


@pytest.mark.parametrize(("mass", "diameter", "length"), SIZE_SAMPLES, ids=["RS05", "RS02", "RS06", "RS03", "RS04"])
def test_drive_size_follows_the_products(mass, diameter, length):
    """按重量估的大小，和拟合用的那几个产品差不到两成。"""
    estimated_diameter, estimated_length = drive_size_m(mass)
    assert estimated_diameter == pytest.approx(diameter, rel=0.2)
    assert estimated_length == pytest.approx(length, rel=0.2)


def test_heavier_drives_are_bigger():
    """越重的驱动器越粗，也稍长一点。"""
    light, heavy = drive_size_m(0.5), drive_size_m(2.0)
    assert heavy[0] > light[0] and heavy[1] > light[1]


def test_refuses_a_massless_drive():
    """重量不是正数：报错。"""
    with pytest.raises(ValueError, match="必须大于 0"):
        drive_size_m(0.0)


def test_pelvis_holds_the_hip_and_lumbar_drives(nova):
    """Nova 的骨盆：髋的四个电机、腰的电机和推杆的一半、安全板、髋的制动器；
    加起来不到能用的六成，最粗的电机比骨盆最窄的那一边细。"""
    fit = pelvis_fit(nova.budget, nova.dimensions)
    names = {content.name for content in fit.contents}
    assert {"髋 前后", "髋 侧摆", "腰椎 转", "腰椎 前后、侧弯", "安全控制板", "髋的制动器"} <= names
    assert "超级电容" not in names
    assert fit.used_m3 == pytest.approx(sum(content.volume_m3 for content in fit.contents))
    assert fit.share == pytest.approx(fit.used_m3 / math.prod(fit.box_m))
    assert fit.share < USABLE_SHARE
    assert fit.widest_m < min(fit.box_m)
    assert fit.fits


def test_pushers_count_only_their_pelvis_half(nova):
    """推杆跨在腰的关节上：骨盆里只算一半的体积。"""
    fit = pelvis_fit(nova.budget, nova.dimensions)
    pushers = next(content for content in fit.contents if content.name == "腰椎 前后、侧弯")
    drive = nova.budget.drives["lumbar_pitch_roll"][0]
    diameter, length = drive_size_m(drive.mass_kg)
    assert pushers.volume_each_m3 == pytest.approx(math.pi / 4 * diameter**2 * length / 2)


@pytest.mark.parametrize(
    ("share", "widest", "fits"),
    [(0.5, 0.10, True), (USABLE_SHARE + 0.01, 0.10, False), (0.5, 0.25, False)],
    ids=["放得下", "太满", "电机太粗"],
)
def test_fit_needs_room_and_a_thin_enough_motor(share, widest, fits):
    """放得下要两样：占的不超过六成，最粗的电机比最窄的那一边细。"""
    box = (0.2, 0.3, 0.2)
    volume = share * math.prod(box)
    fit = SegmentFit("试", box, (Content("东西", 1, volume, widest),))
    assert fit.fits is fits


def test_moving_the_supercapacitor_back_would_overfill_the_pelvis(nova):
    """超级电容放回骨盆的话，就超过了能用的六成（所以挪到了腹部）。"""
    fit = pelvis_fit(nova.budget, nova.dimensions)
    supercapacitor = Content("超级电容", 1, 1.0 / 1500.0)
    crowded = replace(fit, contents=(*fit.contents, supercapacitor))
    assert crowded.share > USABLE_SHARE - 0.02
