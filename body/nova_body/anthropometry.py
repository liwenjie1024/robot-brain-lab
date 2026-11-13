"""人体测量：按身高算各段的长度，按体重算各段的质量。

Nova 的比例照人（机体规格第 1 节）：
- 长度的比例：Winter《Biomechanics and Motor Control of Human Movement》。
- 质量的比例：de Leva (1996)，男性。
"""

from enum import StrEnum


class Segment(StrEnum):
    """身体的段。手臂和腿的段左右各一个；这个模块里的数都是一侧的。"""

    HEAD = "head"
    TORSO = "torso"
    UPPER_ARM = "upper_arm"
    FOREARM = "forearm"
    HAND = "hand"
    THIGH = "thigh"
    SHANK = "shank"
    FOOT = "foot"


SEGMENT_NAMES: dict[Segment, str] = {
    Segment.HEAD: "头和颈",
    Segment.TORSO: "躯干和骨盆",
    Segment.UPPER_ARM: "上臂",
    Segment.FOREARM: "前臂",
    Segment.HAND: "手",
    Segment.THIGH: "大腿",
    Segment.SHANK: "小腿",
    Segment.FOOT: "脚",
}

PAIRED_SEGMENTS: frozenset[Segment] = frozenset(
    {Segment.UPPER_ARM, Segment.FOREARM, Segment.HAND, Segment.THIGH, Segment.SHANK, Segment.FOOT}
)

# 各段的长度占身高的比例。躯干是从髋到肩，头和颈是从肩到头顶，脚是踝的高度。
LENGTH_RATIO: dict[Segment, float] = {
    Segment.HEAD: 0.182,
    Segment.TORSO: 0.288,
    Segment.UPPER_ARM: 0.186,
    Segment.FOREARM: 0.146,
    Segment.HAND: 0.108,
    Segment.THIGH: 0.245,
    Segment.SHANK: 0.246,
    Segment.FOOT: 0.039,
}

# 站着的时候，从脚底到头顶依次经过这几段；它们的长度加起来就是身高。
STANDING_CHAIN: tuple[Segment, ...] = (Segment.FOOT, Segment.SHANK, Segment.THIGH, Segment.TORSO, Segment.HEAD)

# 各段的质量占体重的比例。成对的段是一侧的值。
MASS_FRACTION: dict[Segment, float] = {
    Segment.HEAD: 0.0694,
    Segment.TORSO: 0.4346,
    Segment.UPPER_ARM: 0.0271,
    Segment.FOREARM: 0.0162,
    Segment.HAND: 0.0061,
    Segment.THIGH: 0.1416,
    Segment.SHANK: 0.0433,
    Segment.FOOT: 0.0137,
}


def segment_count(segment: Segment) -> int:
    """这一段在身上有几个：成对的 2 个，其它 1 个。"""
    return 2 if segment in PAIRED_SEGMENTS else 1


def segment_length_m(segment: Segment, height_m: float) -> float:
    """身高是 height_m 的人，这一段有多长。"""
    if height_m <= 0:
        raise ValueError(f"身高必须大于 0，收到的是 {height_m}")
    return LENGTH_RATIO[segment] * height_m


def human_segment_mass_kg(segment: Segment, body_mass_kg: float) -> float:
    """体重是 body_mass_kg 的人，这一段（一侧）有多重。"""
    if body_mass_kg <= 0:
        raise ValueError(f"体重必须大于 0，收到的是 {body_mass_kg}")
    return MASS_FRACTION[segment] * body_mass_kg
