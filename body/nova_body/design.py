"""Nova 的关节和驱动：机体规格第 2、3 节的表，写成数据。

这里是关节表的源头：质量闭环和以后的模型生成都读它。
每组关节带一个记号（核心、待证明……），清单见 docs/核心和待证明.md。
"""

from dataclasses import dataclass, replace
from enum import StrEnum

from nova_body.anthropometry import Segment


class Drive(StrEnum):
    """驱动的方式。"""

    ROTARY = "旋转"
    SCREW = "直线推杆"
    CAPSTAN = "绞盘"
    MICRO = "微型"
    PASSIVE = "被动"


class Tag(StrEnum):
    """核心和待证明的记号。"""

    CORE = "核心"
    TO_PROVE = "待证明"
    LATER = "以后"


class Strength(StrEnum):
    """驱动器按哪一档力量定。"""

    DAILY = "做家务的动作要的（1.5 步从动作算的）"
    HUMAN_PEAK = "人的峰值（初估）"


class TorqueRule(StrEnum):
    """这组关节要的峰值力矩，跟着什么变。"""

    FIXED = "固定"
    BODY_MASS = "随体重"
    SHOULDER_LOAD = "肩：端着东西伸直手臂"
    ELBOW_LOAD = "肘：端着东西伸直前臂"


@dataclass(frozen=True)
class JointGroup:
    """一组关节（一侧的）。

    peak_torques_nm 是每个自由度的峰值力矩，按体重 70 kg、力量照人定（"人的峰值，初估"）。
    daily_torques_nm、speeds_rad_s 是 1.5 步从动作算出来的目标（见 DAILY_TARGETS）；空的就是没算。
    parallel 表示两个驱动器并联带两个自由度：每个驱动器要出两个力矩之和的一半。
    fixed_mass_kg 用在不按力矩算重量的组（微型、被动、力还没测的）：是这一组一侧的总重。
    """

    key: str
    name: str
    segment: Segment
    paired: bool
    dof: int
    actuators: int
    drive: Drive
    tag: Tag
    peak_torques_nm: tuple[float, ...] = ()
    torque_rule: TorqueRule = TorqueRule.FIXED
    parallel: bool = False
    fixed_mass_kg: float | None = None
    dual_winding: bool = False
    daily_torques_nm: tuple[float, ...] = ()
    speeds_rad_s: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if self.fixed_mass_kg is None and len(self.peak_torques_nm) != self.dof:
            raise ValueError(f"{self.name}：有 {self.dof} 个自由度，却给了 {len(self.peak_torques_nm)} 个力矩")
        if self.parallel and (self.dof, self.actuators) != (PARALLEL_PAIR, PARALLEL_PAIR):
            raise ValueError(f"{self.name}：并联的一组必须是 2 个自由度、2 个驱动器")
        for label, values in (("动作算的力矩", self.daily_torques_nm), ("转速", self.speeds_rad_s)):
            if values and len(values) != self.dof:
                raise ValueError(f"{self.name}：有 {self.dof} 个自由度，{label}却给了 {len(values)} 个")

    @property
    def sides(self) -> int:
        """身上有几组：成对的 2 组，其它 1 组。"""
        return 2 if self.paired else 1

    def spec_torques_nm(self, strength: Strength) -> tuple[float, ...]:
        """按这一档力量，每个自由度的峰值力矩（体重 70 kg 时）。动作没算出目标的组用人的峰值。"""
        if strength is Strength.DAILY and self.daily_torques_nm:
            return self.daily_torques_nm
        return self.peak_torques_nm

    def actuator_torques_nm(self, strength: Strength) -> tuple[float, ...]:
        """每个驱动器要出的峰值力矩（体重 70 kg 时）。按固定重量算的组返回空。

        并联的两个驱动器按"两个力矩的峰值同时来"算：保守（动作里同时要的那一刻小一些，见力量的报告）。
        """
        if self.fixed_mass_kg is not None:
            return ()
        torques = self.spec_torques_nm(strength)
        if self.parallel:
            shared = sum(torques) / PARALLEL_PAIR
            return (shared, shared)
        return torques


PARALLEL_PAIR = 2

_SPEC_GROUPS: tuple[JointGroup, ...] = (
    # 头
    JointGroup("neck_lower", "下颈 前后", Segment.CHEST, False, 1, 1, Drive.ROTARY, Tag.TO_PROVE, (30.0,)),
    JointGroup("neck_upper", "上颈 转、点头", Segment.HEAD, False, 2, 2, Drive.ROTARY, Tag.CORE, (20.0, 20.0)),
    JointGroup("neck_upper_roll", "上颈 侧屈", Segment.HEAD, False, 1, 1, Drive.ROTARY, Tag.TO_PROVE, (20.0,)),
    JointGroup("eyes", "眼 左右、上下", Segment.HEAD, False, 4, 4, Drive.MICRO, Tag.TO_PROVE, fixed_mass_kg=0.12),
    JointGroup("eyelids", "眼睑", Segment.HEAD, False, 2, 2, Drive.MICRO, Tag.LATER, fixed_mass_kg=0.02),
    # 躯干
    JointGroup(
        "lumbar_pitch_roll",
        "腰椎 前后、侧弯",
        Segment.PELVIS,
        False,
        2,
        2,
        Drive.SCREW,
        Tag.CORE,
        (250.0, 150.0),
        TorqueRule.BODY_MASS,
        parallel=True,
        dual_winding=True,
    ),
    JointGroup(
        "lumbar_yaw",
        "腰椎 转",
        Segment.PELVIS,
        False,
        1,
        1,
        Drive.ROTARY,
        Tag.CORE,
        (60.0,),
        TorqueRule.BODY_MASS,
        dual_winding=True,
    ),
    JointGroup(
        "thoracic_yaw",
        "胸椎 转",
        Segment.CHEST,
        False,
        1,
        1,
        Drive.ROTARY,
        Tag.TO_PROVE,
        (100.0,),
        TorqueRule.BODY_MASS,
    ),
    JointGroup(
        "thoracic_pitch_roll",
        "胸椎 前后、侧弯",
        Segment.CHEST,
        False,
        2,
        2,
        Drive.SCREW,
        Tag.TO_PROVE,
        (125.0, 125.0),
        TorqueRule.BODY_MASS,
        parallel=True,
    ),
    # 肩胛的推杆要多大的力还没测（机体规格写的是"几百 N，待测"），先按每个 0.3 kg 估。
    JointGroup(
        "scapula", "肩胛 上提、前伸、上旋", Segment.CHEST, True, 3, 3, Drive.SCREW, Tag.TO_PROVE, fixed_mass_kg=0.9
    ),
    # 手臂
    JointGroup(
        "shoulder_pitch",
        "肩 前后",
        Segment.CHEST,
        True,
        1,
        1,
        Drive.ROTARY,
        Tag.CORE,
        (135.0,),
        TorqueRule.SHOULDER_LOAD,
    ),
    JointGroup(
        "shoulder_roll",
        "肩 侧摆",
        Segment.UPPER_ARM,
        True,
        1,
        1,
        Drive.ROTARY,
        Tag.CORE,
        (135.0,),
        TorqueRule.SHOULDER_LOAD,
    ),
    JointGroup("shoulder_yaw", "肩 转", Segment.UPPER_ARM, True, 1, 1, Drive.ROTARY, Tag.CORE, (60.0,)),
    JointGroup("elbow", "肘", Segment.UPPER_ARM, True, 1, 1, Drive.ROTARY, Tag.CORE, (100.0,), TorqueRule.ELBOW_LOAD),
    JointGroup("forearm_roll", "前臂转", Segment.FOREARM, True, 1, 1, Drive.ROTARY, Tag.CORE, (15.0,)),
    JointGroup(
        "wrist", "腕 屈伸、侧偏", Segment.FOREARM, True, 2, 2, Drive.ROTARY, Tag.CORE, (25.0, 25.0), parallel=True
    ),
    # 腿
    JointGroup(
        "hip_pitch",
        "髋 前后",
        Segment.PELVIS,
        True,
        1,
        1,
        Drive.ROTARY,
        Tag.CORE,
        (300.0,),
        TorqueRule.BODY_MASS,
        dual_winding=True,
    ),
    JointGroup(
        "hip_roll",
        "髋 侧摆",
        Segment.PELVIS,
        True,
        1,
        1,
        Drive.ROTARY,
        Tag.CORE,
        (200.0,),
        TorqueRule.BODY_MASS,
        dual_winding=True,
    ),
    JointGroup(
        "hip_yaw",
        "髋 转",
        Segment.THIGH,
        True,
        1,
        1,
        Drive.ROTARY,
        Tag.CORE,
        (120.0,),
        TorqueRule.BODY_MASS,
        dual_winding=True,
    ),
    JointGroup(
        "knee",
        "膝",
        Segment.THIGH,
        True,
        1,
        1,
        Drive.ROTARY,
        Tag.CORE,
        (300.0,),
        TorqueRule.BODY_MASS,
        dual_winding=True,
    ),
    JointGroup(
        "ankle",
        "踝 前后、侧",
        Segment.SHANK,
        True,
        2,
        2,
        Drive.ROTARY,
        Tag.CORE,
        (250.0, 100.0),
        TorqueRule.BODY_MASS,
        parallel=True,
        dual_winding=True,
    ),
    JointGroup("big_toe", "大脚趾", Segment.SHANK, True, 1, 1, Drive.CAPSTAN, Tag.TO_PROVE, fixed_mass_kg=0.15),
    JointGroup("toes_arch", "其它脚趾、足弓", Segment.FOOT, True, 2, 0, Drive.PASSIVE, Tag.TO_PROVE, fixed_mass_kg=0.1),
)


# 1.5 步从动作算出来的目标（docs/报告/力量.md）：每组每个自由度的力矩（N·m，体重 70 kg 时，已经 x 1.5）
# 和最高转速（rad/s，已经 x 1.3）。腿和腰的力矩"随体重"，质量闭环再按算出来的体重放大。
# 没列力矩的组，动作里几乎不出力，算不出有意义的目标（拧门把手、转头这些动作还没写），还用人的峰值。
DAILY_TARGETS: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] = {
    "lumbar_pitch_roll": ((184.2, 57.8), (1.45, 3.43)),
    "lumbar_yaw": ((31.5,), (2.24,)),
    "shoulder_pitch": ((145.5,), (2.47,)),
    "shoulder_roll": ((31.5,), (3.11,)),
    "elbow": ((29.7,), (3.03,)),
    "hip_pitch": ((258.1,), (12.58,)),
    "hip_roll": ((167.6,), (4.3,)),
    "hip_yaw": ((109.8,), (2.98,)),
    "knee": ((338.3,), (12.38,)),
    "ankle": ((230.3, 33.9), (8.29, 0.95)),
}


def _with_targets(group: JointGroup) -> JointGroup:
    if group.key not in DAILY_TARGETS:
        return group
    torques, speeds = DAILY_TARGETS[group.key]
    return replace(group, daily_torques_nm=torques, speeds_rad_s=speeds)


JOINT_GROUPS: tuple[JointGroup, ...] = tuple(_with_targets(group) for group in _SPEC_GROUPS)


@dataclass(frozen=True)
class HandDesign:
    """手里面怎么驱动（机体规格第 3 节的三种）。数是一只手的。

    hand_mass_kg 是手本身：骨架、手里的驱动、皮肤、相机。
    forearm_drive_mass_kg 是放在前臂里、给手用的驱动。
    """

    key: str
    name: str
    tag: Tag
    dof: int
    actuators: int
    hand_mass_kg: float
    forearm_drive_mass_kg: float


FOREARM_CAPSTAN_KG = 0.12
POWER_TENDON_DRIVE_KG = 0.25

# A：机体规格 3.1 节估的手重约 0.78 kg，取 0.8；前臂里 12 个绞盘。
HAND_ALL_TENDON = HandDesign("A", "全肌腱", Tag.TO_PROVE, 22, 20, 0.8, 12 * FOREARM_CAPSTAN_KG)
# B：22 个关节里 4 个远指间是联动的，所以 18 个小电机都在手里。手重是估的。
HAND_IN_HAND = HandDesign("B", "驱动放在手里", Tag.CORE, 22, 18, 1.0, 0.0)
# C：18 个小电机在手里，另加 2 根"力量肌腱"的驱动在前臂。
HAND_HYBRID = HandDesign("C", "混合", Tag.TO_PROVE, 22, 20, 0.95, 2 * POWER_TENDON_DRIVE_KG)

HAND_COUNT = 2


@dataclass(frozen=True)
class BodyVariant:
    """一种身体：包含哪些记号的关节，用哪种手。"""

    key: str
    name: str
    tags: frozenset[Tag]
    hand: HandDesign

    def joint_groups(self) -> tuple[JointGroup, ...]:
        """这种身体里有的关节组。"""
        return tuple(group for group in JOINT_GROUPS if group.tag in self.tags)

    def total_dof(self) -> int:
        """全身的自由度（含两只手）。"""
        return sum(group.dof * group.sides for group in self.joint_groups()) + self.hand.dof * HAND_COUNT

    def total_actuators(self) -> int:
        """全身的驱动器数（含两只手）。"""
        return sum(group.actuators * group.sides for group in self.joint_groups()) + self.hand.actuators * HAND_COUNT


CORE_BODY = BodyVariant("core", "核心版", frozenset({Tag.CORE}), HAND_IN_HAND)
FULL_BODY = BodyVariant("full", "完整版", frozenset({Tag.CORE, Tag.TO_PROVE, Tag.LATER}), HAND_ALL_TENDON)
