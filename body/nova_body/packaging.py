"""放不放得下（1.6 步）：按驱动器的重量估它有多大（直径、长度），把一段身体里的东西的体积加起来，和这一段比。

粗算，不排位置：电机是圆柱，别的东西（超级电容、安全板、制动器……）按它们的密度算体积。
一个盒子里不能全塞满：圆柱之间、线、冷却液的管、骨架要留空，能用来放东西的按六成算（粗估）。
"""

import math
from dataclasses import dataclass

import numpy as np

from nova_body.anthropometry import Segment, segment_count
from nova_body.mass_closure import MassBudget
from nova_body.model import ITEM_KINDS, PART_STYLES, PartKind
from nova_body.skeleton import Dimensions

# 驱动器的大小随重量变：RobStride 05、02、06、03、04（重量 kg、直径 m、长度 m，经销商的页面）。
SIZE_SAMPLES: tuple[tuple[float, float, float], ...] = (
    (0.191, 0.046, 0.044),
    (0.380, 0.0785, 0.0415),
    (0.621, 0.088, 0.049),
    (0.880, 0.106, 0.056),
    (1.420, 0.120, 0.056),
)
USABLE_SHARE = 0.6


def _fit(column: int) -> tuple[float, float]:
    """在对数坐标里拟合：大小 = 系数 x 重量^指数。"""
    masses = np.log([sample[0] for sample in SIZE_SAMPLES])
    sizes = np.log([sample[column] for sample in SIZE_SAMPLES])
    exponent, log_coefficient = np.polyfit(masses, sizes, deg=1)
    return math.exp(float(log_coefficient)), float(exponent)


DIAMETER_FIT = _fit(1)
LENGTH_FIT = _fit(2)


def drive_size_m(mass_kg: float) -> tuple[float, float]:
    """这么重的驱动器大约多大：直径、长度（米）。"""
    if not mass_kg > 0:
        raise ValueError(f"驱动器的重量必须大于 0，收到的是 {mass_kg}")
    (diameter_coefficient, diameter_exponent), (length_coefficient, length_exponent) = DIAMETER_FIT, LENGTH_FIT
    return diameter_coefficient * mass_kg**diameter_exponent, length_coefficient * mass_kg**length_exponent


@dataclass(frozen=True)
class Content:
    """一段身体（一侧）里的一样东西：几个、每个多大（体积）、电机的直径（别的东西是 None）。"""

    name: str
    count: int
    volume_each_m3: float
    diameter_m: float | None = None

    @property
    def volume_m3(self) -> float:
        """这样东西一共占多大。"""
        return self.count * self.volume_each_m3


@dataclass(frozen=True)
class SegmentFit:
    """一段身体放不放得下：它的大小（盒子）、里面的东西。"""

    name: str
    box_m: tuple[float, float, float]
    contents: tuple[Content, ...]

    @property
    def box_volume_m3(self) -> float:
        """这一段的盒子多大。"""
        return math.prod(self.box_m)

    @property
    def used_m3(self) -> float:
        """里面的东西一共多大。"""
        return sum(content.volume_m3 for content in self.contents)

    @property
    def share(self) -> float:
        """里面的东西占这一段的几成。"""
        return self.used_m3 / self.box_volume_m3

    @property
    def widest_m(self) -> float:
        """最粗的电机的直径。"""
        return max((content.diameter_m for content in self.contents if content.diameter_m is not None), default=0.0)

    @property
    def fits(self) -> bool:
        """放得下：占的不超过能用的那六成，最粗的电机也比这一段最窄的那一边细。"""
        return self.share <= USABLE_SHARE and self.widest_m <= min(self.box_m)


def pelvis_fit(budget: MassBudget, dims: Dimensions) -> SegmentFit:
    """骨盆（髋关节到腰椎的关节）里放得下放不下。"""
    box = (2 * dims.pelvis_half_depth, 2 * dims.pelvis_half_width, dims.pelvis_length + dims.pelvis_below_hip)
    return SegmentFit("骨盆", box, _contents(budget, Segment.PELVIS))


def _contents(budget: MassBudget, segment: Segment) -> tuple[Content, ...]:
    """这一段（一侧）里的驱动器和别的东西。推杆跨在关节上的，体积也只算分到这一段的那一份。"""
    per_body = segment_count(segment)
    found = []
    for line in budget.actuators:
        if line.segment is not segment or line.drive is None:
            continue
        diameter, length = drive_size_m(line.drive.mass_kg)
        volume = math.pi / 4 * diameter**2 * length * line.share
        found.append(Content(line.name, line.count // per_body, volume, diameter))
    for item in budget.items:
        if item.segment is not segment:
            continue
        density = PART_STYLES[ITEM_KINDS.get(item.key, PartKind.FALLBACK)].density
        found.append(Content(item.name, item.count // per_body, item.mass_each_kg / density))
    return tuple(found)
