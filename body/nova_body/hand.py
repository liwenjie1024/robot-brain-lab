"""手的骨架：22 个关节（机体规格 3.2 节）。四根手指各 4 个、拇指 5 个、手掌 1 个。

这里写的是左手，坐标和 skeleton.py 一样：手垂着的时候，手指朝下（-z），手心朝身体（-y），拇指一侧朝前（+x）。
右手是镜像。手里的位置都写成"往指尖多远、往拇指一侧多远、往手心多远"，是手长的倍数。

核心版用"驱动放在手里"的做法（B）：远指间跟着近指间动，其它 18 个关节各有一个小电机。
手指各节的长度比例：Buchholz、Armstrong、Goldstein (1992)。关节的位置、力矩、各节的重量是估的，
做到"手和动作脑"（P4）时再核对（拇指对掌、33 种抓握）。
"""

from dataclasses import dataclass

from nova_body.body import Side
from nova_body.skeleton import AXIS_BACKWARD, AXIS_LEFT, AXIS_RIGHT, AXIS_UP, Vector, mirror_point


@dataclass(frozen=True)
class HandJoint:
    """手的一个关节。

    peak_torque_nm 是这个关节的小电机能出的峰值力矩；None 表示没有电机，跟着 follows 那个关节动。
    follow_ratio：这个关节的角度 = follow_ratio x 被跟着的关节的角度。
    """

    key: str
    name: str
    axis: Vector
    lower_deg: float
    upper_deg: float
    positive: str
    peak_torque_nm: float | None
    follows: str | None = None
    follow_ratio: float = 0.0


@dataclass(frozen=True)
class Phalanx:
    """手指的一节：长度是手长的倍数，重量是整只手的几分之几，连到上一节的关节。"""

    key: str
    name: str
    length_ratio: float
    mass_fraction: float
    joints: tuple[HandJoint, ...]


@dataclass(frozen=True)
class Digit:
    """一根手指。

    base 是指根关节在手里的位置：(往指尖, 往拇指一侧, 往手心)，手长的倍数。
    direction 是零位时手指指的方向，用同样的三个分量。on_ulnar_palm：指根长在能拢起来的那半边手掌上。
    """

    key: str
    name: str
    base: Vector
    direction: Vector
    radius_ratio: float
    on_ulnar_palm: bool
    phalanges: tuple[Phalanx, ...]


# 指尖用 25 N 按东西时各关节要出的力矩（驱动放在手里的手，力量约 20~30 N）。
FINGER_MCP_TORQUE_NM = 2.5
FINGER_SPREAD_TORQUE_NM = 0.6
FINGER_PIP_TORQUE_NM = 1.2
THUMB_CMC_TORQUE_NM = 3.0
THUMB_MCP_TORQUE_NM = 1.6
THUMB_SPREAD_TORQUE_NM = 0.6
THUMB_IP_TORQUE_NM = 0.8
PALM_ARCH_TORQUE_NM = 1.0

# 远指间最多弯 80°，近指间最多弯 105°，两个一起动。
DIP_FOLLOW_RATIO = 80.0 / 105.0

FINGER_RADIUS_RATIO = 0.045
THUMB_RADIUS_RATIO = 0.055
# 一根手指的重量分到三节：近节、中节、远节。
FINGER_MASS_SPLIT = (0.5, 0.3, 0.2)
THUMB_MASS_SPLIT = (0.45, 0.33, 0.22)
FINGER_MASS_FRACTION = 0.09
THUMB_MASS_FRACTION = 0.14
# 手掌分两半：食指和中指那半边（连着手腕）、无名指和小指那半边（能拢起来）。
RADIAL_PALM_MASS_FRACTION = 0.36
ULNAR_PALM_MASS_FRACTION = 0.14

# 手掌的形状，手长的倍数：(往指尖的范围, 往拇指一侧的范围)，和半个厚度。
PALM_HALF_THICKNESS_RATIO = 0.075
RADIAL_PALM_SPAN = ((0.04, 0.44), (-0.015, 0.24))
ULNAR_PALM_SPAN = ((0.06, 0.40), (-0.25, -0.015))
# 手掌拢起来的转轴：沿着手指的方向，在中指和无名指的掌骨之间。
PALM_ARCH_PIVOT: Vector = (0.06, -0.015, 0.0)
# 手掌相机在手心的位置。
PALM_CAMERA_POSITION: Vector = (0.25, 0.08, PALM_HALF_THICKNESS_RATIO)

FINGER_DIRECTION: Vector = (1.0, 0.0, 0.0)
# 零位时拇指在手掌的平面里，往拇指一侧张开 45°。
THUMB_DIRECTION: Vector = (0.7071067811865476, 0.7071067811865476, 0.0)
# 拇指往手心抬起来的转轴（左手，身体的坐标）：和拇指的方向、手心的方向都垂直。
THUMB_LIFT_AXIS: Vector = (-0.7071067811865476, 0.0, -0.7071067811865476)

PALM_ARCH = HandJoint("palm_arch", "手掌 拢", AXIS_UP, 0.0, 20.0, "拢成碗", PALM_ARCH_TORQUE_NM)


def _finger(key: str, name: str, base: Vector, lengths: tuple[float, float, float], on_ulnar_palm: bool) -> Digit:
    """食指到小指：掌指（摆、弯）、近指间、远指间（跟着近指间）。"""
    proximal, middle, distal = lengths
    near, mid, far = FINGER_MASS_SPLIT
    pip = f"{key}_pip"
    return Digit(
        key,
        name,
        base,
        FINGER_DIRECTION,
        FINGER_RADIUS_RATIO,
        on_ulnar_palm,
        (
            Phalanx(
                f"{key}_proximal",
                f"{name} 近节",
                proximal,
                FINGER_MASS_FRACTION * near,
                (
                    HandJoint(
                        f"{key}_mcp_spread",
                        f"{name} 掌指 摆",
                        AXIS_RIGHT,
                        -20.0,
                        20.0,
                        "向拇指一侧摆",
                        FINGER_SPREAD_TORQUE_NM,
                    ),
                    HandJoint(
                        f"{key}_mcp_flex", f"{name} 掌指 弯", AXIS_BACKWARD, -30.0, 90.0, "弯", FINGER_MCP_TORQUE_NM
                    ),
                ),
            ),
            Phalanx(
                f"{key}_middle",
                f"{name} 中节",
                middle,
                FINGER_MASS_FRACTION * mid,
                (HandJoint(pip, f"{name} 近指间", AXIS_BACKWARD, 0.0, 105.0, "弯", FINGER_PIP_TORQUE_NM),),
            ),
            Phalanx(
                f"{key}_distal",
                f"{name} 远节",
                distal,
                FINGER_MASS_FRACTION * far,
                (
                    HandJoint(
                        f"{key}_dip",
                        f"{name} 远指间",
                        AXIS_BACKWARD,
                        0.0,
                        80.0,
                        "弯",
                        None,
                        follows=pip,
                        follow_ratio=DIP_FOLLOW_RATIO,
                    ),
                ),
            ),
        ),
    )


def _thumb() -> Digit:
    """拇指：腕掌（弯、抬）、掌指（弯、摆）、指间。"""
    near, mid, far = THUMB_MASS_SPLIT
    return Digit(
        "thumb",
        "拇指",
        (0.10, 0.12, 0.03),
        THUMB_DIRECTION,
        THUMB_RADIUS_RATIO,
        False,
        (
            Phalanx(
                "thumb_metacarpal",
                "拇指 掌骨",
                0.251,
                THUMB_MASS_FRACTION * near,
                (
                    HandJoint(
                        "thumb_cmc_flex", "拇指 腕掌 弯", AXIS_LEFT, -15.0, 35.0, "横过手心", THUMB_CMC_TORQUE_NM
                    ),
                    HandJoint(
                        "thumb_cmc_lift", "拇指 腕掌 抬", THUMB_LIFT_AXIS, 0.0, 50.0, "向手心抬", THUMB_CMC_TORQUE_NM
                    ),
                ),
            ),
            Phalanx(
                "thumb_proximal",
                "拇指 近节",
                0.196,
                THUMB_MASS_FRACTION * mid,
                (
                    HandJoint("thumb_mcp_flex", "拇指 掌指 弯", AXIS_LEFT, 0.0, 60.0, "弯", THUMB_MCP_TORQUE_NM),
                    HandJoint(
                        "thumb_mcp_spread",
                        "拇指 掌指 摆",
                        THUMB_LIFT_AXIS,
                        -10.0,
                        10.0,
                        "向手心摆",
                        THUMB_SPREAD_TORQUE_NM,
                    ),
                ),
            ),
            Phalanx(
                "thumb_distal",
                "拇指 远节",
                0.158,
                THUMB_MASS_FRACTION * far,
                (HandJoint("thumb_ip", "拇指 指间", AXIS_LEFT, 0.0, 80.0, "弯", THUMB_IP_TORQUE_NM),),
            ),
        ),
    )


# 掌指关节离手腕多远：让中指的指尖正好在一个手长的地方；其它手指按人手的样子排。
DIGITS: tuple[Digit, ...] = (
    _thumb(),
    _finger("index", "食指", (0.447, 0.165, 0.0), (0.245, 0.143, 0.097), on_ulnar_palm=False),
    _finger("middle", "中指", (0.456, 0.045, 0.0), (0.266, 0.170, 0.108), on_ulnar_palm=False),
    _finger("ring", "无名指", (0.420, -0.075, 0.0), (0.244, 0.165, 0.107), on_ulnar_palm=True),
    _finger("little", "小指", (0.375, -0.185, 0.0), (0.204, 0.117, 0.093), on_ulnar_palm=True),
)


def from_hand(vector: Vector, side: Side) -> Vector:
    """手里的 (往指尖, 往拇指一侧, 往手心) 换成身体的坐标（零位时）。"""
    toward_tip, toward_thumb, toward_palm = vector
    return mirror_point((toward_thumb, -toward_palm, -toward_tip), side)


def hand_joints() -> tuple[HandJoint, ...]:
    """一只手的全部关节：手掌 1 个 + 五根手指的。"""
    return (PALM_ARCH, *(joint for digit in DIGITS for phalanx in digit.phalanges for joint in phalanx.joints))


def hand_actuated_joints() -> tuple[HandJoint, ...]:
    """有小电机的关节。"""
    return tuple(joint for joint in hand_joints() if joint.peak_torque_nm is not None)


def hand_mass_fractions_total() -> float:
    """手掌和各节手指的重量比例加起来（应该是 1）。"""
    digits = sum(phalanx.mass_fraction for digit in DIGITS for phalanx in digit.phalanges)
    return RADIAL_PALM_MASS_FRACTION + ULNAR_PALM_MASS_FRACTION + digits
