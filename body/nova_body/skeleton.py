"""骨架：身体有哪几段、每个关节绕哪根轴转、能转多少、各处的尺寸。

坐标：x 朝前，y 朝左，z 朝上。零位是站直，手臂垂在身体两侧，手心朝里，拇指朝前。
这里写的是身体左侧（和中间）的关节。右侧是左侧的镜像：位置的 y 反过来，转轴用 mirror_axis 换，
这样同一个正方向在两侧是同一个动作（比如"外展"都是往外）。

范围来自机体规格第 2 节的"关节范围"。核心版没有胸椎、下颈和肩胛，
所以腰椎担了整条脊柱的范围，上颈担了整个颈的范围，肩担了"肩（含肩胛）"的范围。
手的关节在 hand.py。
"""

from dataclasses import dataclass
from enum import StrEnum

from nova_body.anthropometry import Segment, segment_length_m

Vector = tuple[float, float, float]

AXIS_FORWARD: Vector = (1.0, 0.0, 0.0)
AXIS_BACKWARD: Vector = (-1.0, 0.0, 0.0)
AXIS_LEFT: Vector = (0.0, 1.0, 0.0)
AXIS_RIGHT: Vector = (0.0, -1.0, 0.0)
AXIS_UP: Vector = (0.0, 0.0, 1.0)


class Side(StrEnum):
    """身体的哪一侧。"""

    LEFT = "left"
    RIGHT = "right"


SIDE_NAMES: dict[Side, str] = {Side.LEFT: "左", Side.RIGHT: "右"}


def mirror_point(point: Vector, side: Side | None) -> Vector:
    """左侧的位置换到这一侧：右侧把 y 反过来。中间的（None）不变。"""
    x, y, z = point
    return (x, -y, z) if side is Side.RIGHT else point


def mirror_axis(axis: Vector, side: Side | None) -> Vector:
    """左侧的转轴换到这一侧。中间的（None）不变。

    镜像以后的转动，是绕 (-x, y, -z) 转同样的角度。这样右侧的正方向和左侧是同一个动作。
    """
    x, y, z = axis
    return (-x, y, -z) if side is Side.RIGHT else axis


@dataclass(frozen=True)
class Joint:
    """一个关节（一个自由度）。

    group 和 index 指到 design.JOINT_GROUPS：哪一组关节里的第几个自由度（峰值力矩从那里来）。
    axis 是左侧（或中间）的转轴；positive 是往正方向转时做的动作。
    """

    key: str
    name: str
    group: str
    index: int
    axis: Vector
    lower_deg: float
    upper_deg: float
    positive: str

    def __post_init__(self) -> None:
        if self.lower_deg >= self.upper_deg:
            raise ValueError(f"{self.name}：范围的下限 {self.lower_deg}° 必须小于上限 {self.upper_deg}°")


@dataclass(frozen=True)
class Link:
    """身体的一段，和把它连到上一段的关节（按从身体往外的顺序）。"""

    key: str
    name: str
    segment: Segment
    parent: str | None
    paired: bool
    joints: tuple[Joint, ...] = ()


LINKS: tuple[Link, ...] = (
    Link("pelvis", "骨盆", Segment.PELVIS, None, False),
    Link(
        "chest",
        "胸和腹",
        Segment.CHEST,
        "pelvis",
        False,
        (
            Joint("lumbar_yaw", "腰 转", "lumbar_yaw", 0, AXIS_UP, -45.0, 45.0, "向左转"),
            Joint("lumbar_roll", "腰 侧弯", "lumbar_pitch_roll", 1, AXIS_FORWARD, -35.0, 35.0, "向右弯"),
            Joint("lumbar_pitch", "腰 前后", "lumbar_pitch_roll", 0, AXIS_LEFT, -25.0, 80.0, "向前弯"),
        ),
    ),
    Link(
        "head",
        "头",
        Segment.HEAD,
        "chest",
        False,
        (
            Joint("neck_yaw", "颈 转", "neck_upper", 0, AXIS_UP, -75.0, 75.0, "向左转"),
            Joint("neck_pitch", "颈 点头", "neck_upper", 1, AXIS_LEFT, -50.0, 45.0, "低头"),
        ),
    ),
    Link(
        "upper_arm",
        "上臂",
        Segment.UPPER_ARM,
        "chest",
        True,
        (
            Joint("shoulder_pitch", "肩 前后", "shoulder_pitch", 0, AXIS_RIGHT, -60.0, 180.0, "向前举"),
            Joint("shoulder_roll", "肩 侧摆", "shoulder_roll", 0, AXIS_FORWARD, -30.0, 180.0, "向外举"),
            Joint("shoulder_yaw", "肩 转", "shoulder_yaw", 0, AXIS_UP, -70.0, 90.0, "向外转"),
        ),
    ),
    Link(
        "forearm",
        "前臂",
        Segment.FOREARM,
        "upper_arm",
        True,
        (
            Joint("elbow", "肘", "elbow", 0, AXIS_RIGHT, 0.0, 150.0, "弯"),
            Joint("forearm_roll", "前臂转", "forearm_roll", 0, AXIS_UP, -80.0, 80.0, "手心转向前"),
        ),
    ),
    Link(
        "hand",
        "手",
        Segment.HAND,
        "forearm",
        True,
        (
            Joint("wrist_flex", "腕 屈伸", "wrist", 0, AXIS_BACKWARD, -70.0, 80.0, "向手心弯"),
            Joint("wrist_deviation", "腕 侧偏", "wrist", 1, AXIS_RIGHT, -30.0, 20.0, "向拇指一侧偏"),
        ),
    ),
    Link(
        "thigh",
        "大腿",
        Segment.THIGH,
        "pelvis",
        True,
        (
            Joint("hip_pitch", "髋 前后", "hip_pitch", 0, AXIS_RIGHT, -30.0, 130.0, "向前抬"),
            Joint("hip_roll", "髋 侧摆", "hip_roll", 0, AXIS_FORWARD, -30.0, 60.0, "向外摆"),
            Joint("hip_yaw", "髋 转", "hip_yaw", 0, AXIS_UP, -45.0, 45.0, "脚尖向外"),
        ),
    ),
    Link(
        "shank",
        "小腿",
        Segment.SHANK,
        "thigh",
        True,
        (Joint("knee", "膝", "knee", 0, AXIS_LEFT, 0.0, 150.0, "弯"),),
    ),
    Link(
        "foot",
        "脚",
        Segment.FOOT,
        "shank",
        True,
        (
            Joint("ankle_pitch", "踝 前后", "ankle", 0, AXIS_RIGHT, -50.0, 20.0, "脚尖向上"),
            Joint("ankle_roll", "踝 侧", "ankle", 1, AXIS_BACKWARD, -20.0, 35.0, "脚底转向里"),
        ),
    ),
)


ROOT_LINK = "pelvis"


def link(key: str) -> Link:
    """按名字找一段。"""
    for candidate in LINKS:
        if candidate.key == key:
            return candidate
    raise KeyError(f"骨架里没有 {key} 这一段")


def side_prefix(side: Side | None) -> str:
    """模型里名字的前缀：左右侧的带 left_、right_，中间的不带。"""
    return "" if side is None else f"{side.value}_"


def sides_of(part: Link) -> tuple[Side | None, ...]:
    """这一段在身上的几处：成对的有左右两侧，其它只有中间一个（None）。"""
    return (Side.LEFT, Side.RIGHT) if part.paired else (None,)


def sole_site(side: Side) -> str:
    """模型里脚底正中间那个点的名字。"""
    return f"{side.value}_sole"


# 下面的比例都是占身高的比例。
# 两个髋关节中心的距离约是身高的 0.10（成年人约 0.17 m）。
HIP_HALF_SPACING_RATIO = 0.05
# Winter：肩宽（两肩最外侧）是身高的 0.259，脚长 0.152，脚宽 0.055，眼的高度 0.936。
SHOULDER_BREADTH_RATIO = 0.259
FOOT_LENGTH_RATIO = 0.152
FOOT_WIDTH_RATIO = 0.055
EYE_HEIGHT_RATIO = 0.936
# 上颈的关节（头和颈之间）的高度：约在耳垂下面，1.70 m 的人约 1.53 m。
NECK_JOINT_HEIGHT_RATIO = 0.90
# 踝在脚跟前面多远，占脚长的比例。
HEEL_TO_ANKLE_FRACTION = 0.26
# 各段的粗细（半径）：1.70 m 的人，大腿约 7.5 cm、小腿 5 cm、上臂 4.5 cm、前臂 3.8 cm。
THIGH_RADIUS_RATIO = 0.044
SHANK_RADIUS_RATIO = 0.029
UPPER_ARM_RADIUS_RATIO = 0.026
FOREARM_RADIUS_RATIO = 0.022
NECK_RADIUS_RATIO = 0.030
# 躯干：半个宽度、半个厚度。胸比肩窄，手臂垂下来时不碰到。
CHEST_HALF_WIDTH_RATIO = 0.072
CHEST_HALF_DEPTH_RATIO = 0.056
PELVIS_HALF_WIDTH_RATIO = 0.082
PELVIS_HALF_DEPTH_RATIO = 0.050
# 骨盆在髋关节下面还有一截（到裆）。
PELVIS_BELOW_HIP_RATIO = 0.047
# 头：半个长（前后）、半个宽、半个高。Winter：下巴到头顶是身高的 0.13。
HEAD_HALF_LENGTH_RATIO = 0.057
HEAD_HALF_WIDTH_RATIO = 0.045
HEAD_HALF_HEIGHT_RATIO = 0.065
SOLE_THICKNESS_RATIO = 0.015


@dataclass(frozen=True)
class Dimensions:
    """这个身高的身体各处的尺寸，单位是米。"""

    height: float
    ankle_height: float
    shank_length: float
    thigh_length: float
    pelvis_length: float
    chest_length: float
    upper_arm_length: float
    forearm_length: float
    hand_length: float
    hip_half_spacing: float
    shoulder_half_spacing: float
    neck_joint_above_shoulder: float
    eye_above_neck_joint: float
    head_top_above_neck_joint: float
    foot_length: float
    foot_width: float
    heel_behind_ankle: float
    sole_thickness: float
    thigh_radius: float
    shank_radius: float
    upper_arm_radius: float
    forearm_radius: float
    neck_radius: float
    chest_half_width: float
    chest_half_depth: float
    pelvis_half_width: float
    pelvis_half_depth: float
    pelvis_below_hip: float
    head_half_length: float
    head_half_width: float
    head_half_height: float

    @classmethod
    def for_height(cls, height_m: float) -> "Dimensions":
        """按身高算出全部尺寸。"""
        if height_m <= 0:
            raise ValueError(f"身高必须大于 0，收到的是 {height_m}")
        ankle = segment_length_m(Segment.FOOT, height_m)
        shank = segment_length_m(Segment.SHANK, height_m)
        thigh = segment_length_m(Segment.THIGH, height_m)
        pelvis = segment_length_m(Segment.PELVIS, height_m)
        chest = segment_length_m(Segment.CHEST, height_m)
        shoulder_height = ankle + shank + thigh + pelvis + chest
        neck_joint_height = NECK_JOINT_HEIGHT_RATIO * height_m
        upper_arm_radius = UPPER_ARM_RADIUS_RATIO * height_m
        foot_length = FOOT_LENGTH_RATIO * height_m
        return cls(
            height=height_m,
            ankle_height=ankle,
            shank_length=shank,
            thigh_length=thigh,
            pelvis_length=pelvis,
            chest_length=chest,
            upper_arm_length=segment_length_m(Segment.UPPER_ARM, height_m),
            forearm_length=segment_length_m(Segment.FOREARM, height_m),
            hand_length=segment_length_m(Segment.HAND, height_m),
            hip_half_spacing=HIP_HALF_SPACING_RATIO * height_m,
            # 肩关节的中心在肩最外侧往里一个上臂的半径。
            shoulder_half_spacing=SHOULDER_BREADTH_RATIO * height_m / 2 - upper_arm_radius,
            neck_joint_above_shoulder=neck_joint_height - shoulder_height,
            eye_above_neck_joint=EYE_HEIGHT_RATIO * height_m - neck_joint_height,
            head_top_above_neck_joint=height_m - neck_joint_height,
            foot_length=foot_length,
            foot_width=FOOT_WIDTH_RATIO * height_m,
            heel_behind_ankle=HEEL_TO_ANKLE_FRACTION * foot_length,
            sole_thickness=SOLE_THICKNESS_RATIO * height_m,
            thigh_radius=THIGH_RADIUS_RATIO * height_m,
            shank_radius=SHANK_RADIUS_RATIO * height_m,
            upper_arm_radius=upper_arm_radius,
            forearm_radius=FOREARM_RADIUS_RATIO * height_m,
            neck_radius=NECK_RADIUS_RATIO * height_m,
            chest_half_width=CHEST_HALF_WIDTH_RATIO * height_m,
            chest_half_depth=CHEST_HALF_DEPTH_RATIO * height_m,
            pelvis_half_width=PELVIS_HALF_WIDTH_RATIO * height_m,
            pelvis_half_depth=PELVIS_HALF_DEPTH_RATIO * height_m,
            pelvis_below_hip=PELVIS_BELOW_HIP_RATIO * height_m,
            head_half_length=HEAD_HALF_LENGTH_RATIO * height_m,
            head_half_width=HEAD_HALF_WIDTH_RATIO * height_m,
            head_half_height=HEAD_HALF_HEIGHT_RATIO * height_m,
        )

    @property
    def hip_height(self) -> float:
        """站直时髋关节的高度。"""
        return self.ankle_height + self.shank_length + self.thigh_length

    @property
    def shoulder_height(self) -> float:
        """站直时肩关节的高度。"""
        return self.hip_height + self.pelvis_length + self.chest_length
