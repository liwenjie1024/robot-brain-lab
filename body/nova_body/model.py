"""身体的模型：用代码生成 MuJoCo 的模型（核心版，75 个自由度）。

模型从三处拿数据：
- 骨架（skeleton.py、hand.py）：关节的位置、转轴和范围。
- 质量闭环（mass_closure.py）：每一段、每个驱动器、每样东西的重量，每个关节的峰值力矩。
- 这个文件：每样东西放在身体里的哪个位置（机体规格第 6 节），各段的形状。

现在是简化的模型，和真机不一样的地方：
- 膝、踝、腕的连杆和腰椎的推杆没有建，每个关节直接由一个驱动器带动。
- 每个驱动器是"位置 + 阻尼"的控制，代表驱动器里自己跑的阻抗环；刚度和阻尼以后可以在运行时改。
  摩擦、力矩-速度、发热到做驱动器的模型（1.6）时再建。
- 身体的各段之间不算碰撞，只算和地面的碰撞。

地面、步长、关节位置控制的软硬是测试台定的（bench.py），对每个身体都一样。
"""

import math
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

import mujoco
import numpy as np

from nova_body.actuator_mass import ActuatorMassModel, best_today_model
from nova_body.anthropometry import Segment, segment_count
from nova_body.bench import (
    add_floor,
    add_joint_sensors,
    damping_for,
    stiffness_for,
    store_stand_pose,
    use_bench_settings,
)
from nova_body.body import (
    SIDE_NAMES,
    Anatomy,
    Body,
    CameraView,
    DrivenJoint,
    ForceSensor,
    Imu,
    Leg,
    Region,
    Side,
    StandPose,
    TouchSensor,
)
from nova_body.design import CORE_BODY
from nova_body.hand import (
    DIGITS,
    PALM_ARCH,
    PALM_ARCH_PIVOT,
    PALM_CAMERA_POSITION,
    PALM_HALF_THICKNESS_RATIO,
    RADIAL_PALM_MASS_FRACTION,
    RADIAL_PALM_SPAN,
    ULNAR_PALM_MASS_FRACTION,
    ULNAR_PALM_SPAN,
    Digit,
    HandJoint,
    from_hand,
)
from nova_body.mass_closure import Assumptions, MassBudget, close_mass, joint_peak_torques_nm
from nova_body.posture import solve_stand_pose
from nova_body.skeleton import (
    LINKS,
    ROOT_LINK,
    Dimensions,
    Joint,
    Link,
    Vector,
    link,
    mirror_axis,
    mirror_point,
    side_prefix,
    sides_of,
    sole_site,
)

MODEL_NAME = "nova_core"
BODY_NAME = "Nova（核心版）"
ROOT_JOINT = "root"
TRUNK_LINK = "chest"
FOOT_LINK = "foot"
HIP_PITCH, KNEE, ANKLE_PITCH = "hip_pitch", "knee", "ankle_pitch"
PELVIS_IMU = "pelvis_imu"
HEAD_IMU = "head_imu"
CHEST_DEPTH_CAMERA = "chest_depth_camera"
# 骨架上的关节在身体的哪一部分。腕的两个关节算手臂；手指的关节另外算"手"。
SEGMENT_REGIONS: dict[Segment, Region] = {
    Segment.CHEST: Region.WAIST,
    Segment.HEAD: Region.NECK,
    Segment.UPPER_ARM: Region.ARM,
    Segment.FOREARM: Region.ARM,
    Segment.HAND: Region.ARM,
    Segment.THIGH: Region.LEG,
    Segment.SHANK: Region.LEG,
    Segment.FOOT: Region.LEG,
}
# IMU 装在哪：模型里那个点的名字，和它在身体的哪里。
IMU_SITES: dict[str, str] = {PELVIS_IMU: "骨盆", HEAD_IMU: "头"}

ACCELERATION_SUFFIX = "_acc"
GYRO_SUFFIX = "_gyro"
FORCE_SUFFIX = "_force"
MOMENT_SUFFIX = "_moment"
CONTACT_SUFFIX = "_contact"

# 电机转子折算到关节上的惯量，每 N·m 峰值力矩多少 kg·m²。和现有的低减速比关节同一个量级；
# 做驱动器的模型（1.6）时按电机和减速比定。
ARMATURE_PER_NM = 1.5e-4
PASSIVE_DAMPING_PER_NM = 1.0e-3
# 手里的小电机减速比大，折算的惯量不随力矩变。
HAND_ARMATURE = 3.0e-4
HAND_PASSIVE_DAMPING = 5.0e-3
FOLLOWER_ARMATURE = 5.0e-5

SHELL_GROUP = 0
PART_GROUP = 1

# contact 传感器的设置：报什么（力）、多个接触怎么合（合力）、报几个。
CONTACT_DATA_FORCE = 2
CONTACT_REDUCE_NET_FORCE = 3
CONTACT_SLOTS = 1
EQUALITY_DATA_SIZE = 12

# 胸的外壳从腰椎的关节上面一点开始，到肩上面一点；剩下的是颈。
CHEST_BOTTOM_GAP_FRACTION = 0.04
CHEST_TOP_ABOVE_SHOULDER_RADII = 0.8
NECK_SHARE_OF_CHEST = 0.07
HEAD_CENTER_FORWARD_FRACTION = 0.15
FOREARM_SHELL_FRACTION = 0.92
SHANK_END_GAP_RADII = 0.5
SOLE_SHARE_OF_FOOT = 0.7
ANKLE_BALL_RADII = 0.8

# 眼的间距 63 mm（机体规格第 4 节）。眼在脸的前面往里一点。
EYE_SPACING_M = 0.063
EYE_FORWARD_FRACTION = 0.85
# 眼：约 100° 的镜头，竖直方向约 91°。手掌相机是广角。看脚下的深度相机朝前下方。
EYE_FOVY_DEG = 91.0
PALM_CAMERA_FOVY_DEG = 100.0
CHEST_DEPTH_FOVY_DEG = 90.0
CHEST_DEPTH_PITCH_DOWN_DEG = 55.0
CHEST_DEPTH_HEIGHT_FRACTION = 0.8
UP: Vector = (0.0, 0.0, 1.0)
FORWARD: Vector = (1.0, 0.0, 0.0)
PALM_ORIGIN: Vector = (0.0, 0.0, 0.0)
# 手心正中间（手里的坐标：往指尖、往拇指一侧、往手心，手长的倍数）：拿东西、撑地的地方。
PALM_CENTER: Vector = (0.24, 0.0, PALM_HALF_THICKNESS_RATIO)
# 跪地时着地的点在膝关节下面多远（身高的倍数）：胫骨的上端。
KNEE_FRONT_BELOW_JOINT_RATIO = 0.03

_FINGERS = tuple(digit.key for digit in DIGITS if digit.key != "thumb")

# 站着放松时各关节的角度（度），左右一样。没写的是 0。腿的三个关节由站姿来算。
# 手臂稍微离开身体，手指微微弯着，这样没有关节顶在范围的边上。
RELAXED_DEG: dict[str, float] = {
    "shoulder_roll": 6.0,
    "elbow": 12.0,
    "palm_arch": 5.0,
    "thumb_cmc_lift": 15.0,
    "thumb_mcp_flex": 10.0,
    "thumb_ip": 10.0,
    **{f"{finger}_mcp_flex": 15.0 for finger in _FINGERS},
    **{f"{finger}_pip": 25.0 for finger in _FINGERS},
}


class ModelError(RuntimeError):
    """模型建不出来：数据对不上。"""


class PartKind(StrEnum):
    """模型里的一块东西是什么。"""

    SHELL = "shell"
    MOTOR = "motor"
    BATTERY = "battery"
    COMPUTER = "computer"
    COOLING = "cooling"
    FALLBACK = "fallback"
    SENSOR = "sensor"
    FOOT = "foot"


@dataclass(frozen=True)
class PartStyle:
    """一类东西在模型里的样子。

    density（kg/m³）只用来定它画出来多大，重量是质量闭环给的。
    aspect 是盒子三条边（前后、左右、上下）的比例；None 就画成球。
    """

    name: str
    density: float
    rgba: tuple[float, float, float, float]
    aspect: Vector | None = None


PART_STYLES: dict[PartKind, PartStyle] = {
    PartKind.SHELL: PartStyle("骨架、线、皮肤", 0.0, (0.78, 0.80, 0.84, 0.35)),
    PartKind.MOTOR: PartStyle("关节的驱动器", 2500.0, (0.16, 0.42, 0.82, 1.0)),
    PartKind.BATTERY: PartStyle("电池", 2200.0, (0.93, 0.55, 0.13, 1.0), (0.5, 1.0, 0.6)),
    PartKind.COMPUTER: PartStyle("电脑", 1000.0, (0.20, 0.66, 0.38, 1.0), (0.4, 1.0, 0.8)),
    PartKind.COOLING: PartStyle("液冷", 800.0, (0.25, 0.72, 0.80, 1.0), (0.3, 1.0, 1.0)),
    PartKind.FALLBACK: PartStyle("保底的东西（超级电容、制动器、安全板）", 1500.0, (0.80, 0.27, 0.27, 1.0)),
    PartKind.SENSOR: PartStyle("传感器", 1000.0, (0.58, 0.36, 0.78, 1.0)),
    # 脚里的东西主要是一块脚板，画成扁的盒子，不会从脚底下面冒出来。
    PartKind.FOOT: PartStyle(
        "脚里的东西（力传感器、压力皮肤、脚板）", 2700.0, (0.45, 0.45, 0.50, 1.0), (1.0, 0.45, 0.12)
    ),
}

# 不是驱动器的东西各算哪一类。没列在这里的都是关节的驱动器。
ITEM_KINDS: dict[str, PartKind] = {
    "battery": PartKind.BATTERY,
    "computer": PartKind.COMPUTER,
    "cooling": PartKind.COOLING,
    "supercapacitor": PartKind.FALLBACK,
    "safety_board": PartKind.FALLBACK,
    "hip_brake": PartKind.FALLBACK,
    "knee_brake": PartKind.FALLBACK,
    "sensors": PartKind.SENSOR,
    "foot_hardware": PartKind.FOOT,
}
# 手的重量分到手掌和各节手指上，不单独放一块。
SPREAD_OVER_HAND = "hand"


@dataclass(frozen=True)
class ModelJoint:
    """模型里的一个关节。

    peak_torque_nm 是 None 的关节没有驱动器，跟着 follows 那个关节动。
    """

    name: str
    label: str
    key: str
    side: Side | None
    region: Region
    lower_rad: float
    upper_rad: float
    positive: str
    peak_torque_nm: float | None = None
    follows: str | None = None
    follow_ratio: float = 0.0

    @property
    def stiffness(self) -> float:
        """位置控制的刚度（N·m/rad）。没有驱动器的是 0。"""
        return 0.0 if self.peak_torque_nm is None else stiffness_for(self.peak_torque_nm)

    @property
    def damping(self) -> float:
        """位置控制的阻尼（N·m·s/rad）。没有驱动器的是 0。"""
        return 0.0 if self.peak_torque_nm is None else damping_for(self.peak_torque_nm)


@dataclass(frozen=True)
class NovaModel:
    """生成好的身体，和它是按什么数据生成的。

    body 是交给测试台的那一份（模型、站姿、测试台要认得的地方）。
    joints 是全部的关节，包括没有驱动器、跟着别的关节动的。
    """

    spec: mujoco.MjSpec
    body: Body
    budget: MassBudget
    assumptions: Assumptions
    dimensions: Dimensions
    joints: tuple[ModelJoint, ...]
    part_kinds: dict[str, PartKind]

    @property
    def model(self) -> mujoco.MjModel:
        """MuJoCo 的模型。"""
        return self.body.model

    @property
    def stand(self) -> StandPose:
        """站姿。"""
        return self.body.stand

    @property
    def actuated_joints(self) -> tuple[ModelJoint, ...]:
        """有驱动器的关节，顺序和模型里的驱动器一样。"""
        return tuple(joint for joint in self.joints if joint.peak_torque_nm is not None)


def part_legend() -> tuple[tuple[str, tuple[float, float, float, float]], ...]:
    """画图用的图例：每种颜色是什么东西。"""
    return tuple((style.name, style.rgba) for style in PART_STYLES.values())


def eye_camera(side: Side) -> str:
    """眼的相机。"""
    return f"{side.value}_eye"


def palm_camera(side: Side) -> str:
    """手掌的相机。"""
    return f"{side.value}_palm_camera"


def palm_site(side: Side) -> str:
    """手心正中间的点。"""
    return f"{side.value}_palm"


def knee_front_site(side: Side) -> str:
    """膝盖前面跪地时着地的点。"""
    return f"{side.value}_knee_front"


def toe_site(side: Side) -> str:
    """脚尖：脚底最前面那条边的中间。"""
    return f"{side.value}_toe"


def ankle_ft_site(side: Side) -> str:
    """踝部六轴力传感器的位置。"""
    return f"{side.value}_ankle_ft"


def wrist_ft_site(side: Side) -> str:
    """腕部六轴力传感器的位置。"""
    return f"{side.value}_wrist_ft"


def tip_site(side: Side, digit_key: str) -> str:
    """指尖的位置。"""
    return f"{side.value}_{digit_key}_tip"


def tip_force_sensor(side: Side, digit_key: str) -> str:
    """指尖的力传感器。"""
    return tip_site(side, digit_key) + FORCE_SUFFIX


def build_nova(
    assumptions: Assumptions | None = None,
    actuator_model: ActuatorMassModel | None = None,
    *,
    joint_ranges_deg: Mapping[str, tuple[float, float]] | None = None,
) -> NovaModel:
    """生成核心版的身体：先算质量闭环，再按算出来的质量生成模型。

    joint_ranges_deg 用来试别的关节范围：按骨架里关节的名字（比如 ankle_pitch）给 (下限, 上限)，两侧一样。
    """
    assumptions = assumptions or Assumptions()
    budget = close_mass(CORE_BODY, assumptions, actuator_model or best_today_model())
    return build_from_budget(budget, assumptions, joint_ranges_deg=joint_ranges_deg)


def build_from_budget(
    budget: MassBudget,
    assumptions: Assumptions,
    *,
    joint_ranges_deg: Mapping[str, tuple[float, float]] | None = None,
) -> NovaModel:
    """按一份算好的质量生成身体。

    生成两遍：第一遍的模型用来算站姿（要知道重心在哪），第二遍把站姿存进模型里。
    """
    anatomy = _anatomy()
    ranges = dict(joint_ranges_deg or {})
    stand = solve_stand_pose(_Builder(budget, assumptions, ranges).compile(stand=None), anatomy)
    builder = _Builder(budget, assumptions, ranges)
    body = Body(
        name=BODY_NAME,
        model=builder.compile(stand),
        anatomy=anatomy,
        joints=tuple(
            DrivenJoint(
                name=joint.name,
                label=joint.label,
                region=joint.region,
                lower_rad=joint.lower_rad,
                upper_rad=joint.upper_rad,
                peak_torque_nm=joint.peak_torque_nm,
            )
            for joint in builder.joints
            if joint.peak_torque_nm is not None
        ),
        imus=tuple(Imu(place, site + ACCELERATION_SUFFIX, site + GYRO_SUFFIX) for site, place in IMU_SITES.items()),
        stand=stand,
        height_m=builder.dims.height,
        foot_length_m=builder.dims.foot_length,
        foot_width_m=builder.dims.foot_width,
        drawn_groups=(SHELL_GROUP, PART_GROUP),
        force_sensors=_force_sensors(),
        touch_sensors=_touch_sensors(),
        cameras=_cameras(),
    )
    return NovaModel(
        spec=builder.spec,
        body=body,
        budget=budget,
        assumptions=assumptions,
        dimensions=builder.dims,
        joints=tuple(builder.joints),
        part_kinds=builder.kinds,
    )


def _force_sensors() -> tuple[ForceSensor, ...]:
    """踝和腕的六轴力传感器。"""
    places = (("踝", ankle_ft_site), ("腕", wrist_ft_site))
    return tuple(
        ForceSensor(SIDE_NAMES[side] + place, site(side) + FORCE_SUFFIX, site(side) + MOMENT_SUFFIX)
        for place, site in places
        for side in Side
    )


def _touch_sensors() -> tuple[TouchSensor, ...]:
    """接触力：先是身体的每一段（手算一整段），再是每个指尖。"""
    segments = [
        TouchSensor(
            part.name if side is None else f"{SIDE_NAMES[side]} {part.name}",
            side_prefix(side) + part.key + CONTACT_SUFFIX,
        )
        for part in LINKS
        for side in sides_of(part)
    ]
    fingertips = [
        TouchSensor(f"{SIDE_NAMES[side]} {digit.name}指尖", tip_force_sensor(side, digit.key))
        for side in Side
        for digit in DIGITS
    ]
    return (*segments, *fingertips)


def _cameras() -> tuple[CameraView, ...]:
    """相机：两只眼、胸前看脚下的那台、两个手掌。"""
    eyes = [CameraView(f"{SIDE_NAMES[side]}眼", eye_camera(side)) for side in Side]
    palms = [CameraView(f"{SIDE_NAMES[side]}手掌", palm_camera(side)) for side in Side]
    return (*eyes, CameraView("胸前（朝下）", CHEST_DEPTH_CAMERA), *palms)


def _anatomy() -> Anatomy:
    """测试台要认得的地方：骨盆、胸、两条腿上的关节和脚底，站着时手臂和手放在哪。"""
    legs = {
        side: Leg(
            hip_pitch=f"{side.value}_{HIP_PITCH}",
            knee=f"{side.value}_{KNEE}",
            ankle_pitch=f"{side.value}_{ANKLE_PITCH}",
            foot=f"{side.value}_{FOOT_LINK}",
            sole=sole_site(side),
            knee_front=knee_front_site(side),
            toe=toe_site(side),
        )
        for side in Side
    }
    relaxed = {f"{side.value}_{key}": math.radians(degrees) for side in Side for key, degrees in RELAXED_DEG.items()}
    palms = {side: palm_site(side) for side in Side}
    return Anatomy(root=ROOT_LINK, trunk=TRUNK_LINK, legs=legs, relaxed_rad=relaxed, palms=palms)


def _placements(d: Dimensions) -> dict[tuple[Segment, str], tuple[Vector, ...]]:
    """每样东西在它那一段里的位置（左侧的身体；右侧是镜像）。按机体规格第 6 节粗放的。

    位置是相对这一段的原点（把它连到上一段的那个关节）。
    """
    hip_motor_y = 0.8 * d.pelvis_half_width
    shoulder_motor_y = d.shoulder_half_spacing - 1.6 * d.upper_arm_radius
    return {
        # 骨盆：髋前后的电机在髋的外侧，髋侧摆的在后面；腰的推杆在两侧，腰转的电机在腰椎的关节下面。
        (Segment.PELVIS, "hip_pitch"): ((0.0, hip_motor_y, 0.0), (0.0, -hip_motor_y, 0.0)),
        (Segment.PELVIS, "hip_roll"): (
            (-0.6 * d.pelvis_half_depth, d.hip_half_spacing, 0.0),
            (-0.6 * d.pelvis_half_depth, -d.hip_half_spacing, 0.0),
        ),
        (Segment.PELVIS, "hip_brake"): (
            (0.5 * d.pelvis_half_depth, hip_motor_y, 0.2 * d.pelvis_length),
            (0.5 * d.pelvis_half_depth, -hip_motor_y, 0.2 * d.pelvis_length),
        ),
        (Segment.PELVIS, "lumbar_yaw"): ((0.0, 0.0, 0.8 * d.pelvis_length),),
        (Segment.PELVIS, "lumbar_pitch_roll"): (
            (-0.4 * d.pelvis_half_depth, 0.5 * d.pelvis_half_width, 0.6 * d.pelvis_length),
            (-0.4 * d.pelvis_half_depth, -0.5 * d.pelvis_half_width, 0.6 * d.pelvis_length),
        ),
        (Segment.PELVIS, "supercapacitor"): ((0.4 * d.pelvis_half_depth, 0.0, 0.35 * d.pelvis_length),),
        (Segment.PELVIS, "safety_board"): ((-0.5 * d.pelvis_half_depth, 0.0, 0.25 * d.pelvis_length),),
        # 胸和腹：电池在腹部（腰椎的关节上面），电脑在胸前，液冷在背上，肩前后的电机在肩的里侧。
        (Segment.CHEST, "battery"): ((0.2 * d.chest_half_depth, 0.0, 0.22 * d.chest_length),),
        (Segment.CHEST, "computer"): ((0.3 * d.chest_half_depth, 0.0, 0.66 * d.chest_length),),
        (Segment.CHEST, "cooling"): ((-0.55 * d.chest_half_depth, 0.0, 0.62 * d.chest_length),),
        (Segment.CHEST, "shoulder_pitch"): (
            (0.0, shoulder_motor_y, d.chest_length),
            (0.0, -shoulder_motor_y, d.chest_length),
        ),
        # 头：颈的两个电机在关节那里，传感器在脸上。
        (Segment.HEAD, "neck_upper"): ((0.0, 0.0, 0.0), (-0.3 * d.head_half_length, 0.0, 0.2 * d.head_half_height)),
        (Segment.HEAD, "sensors"): ((0.6 * d.head_half_length, 0.0, d.eye_above_neck_joint),),
        # 手臂：电机尽量靠近身体的一端。
        (Segment.UPPER_ARM, "shoulder_roll"): ((0.0, 0.0, 0.0),),
        (Segment.UPPER_ARM, "shoulder_yaw"): ((0.0, 0.0, -0.28 * d.upper_arm_length),),
        (Segment.UPPER_ARM, "elbow"): ((0.0, 0.0, -d.upper_arm_length),),
        (Segment.FOREARM, "forearm_roll"): ((0.0, 0.0, -0.15 * d.forearm_length),),
        (Segment.FOREARM, "wrist"): (
            (0.4 * d.forearm_radius, 0.0, -0.38 * d.forearm_length),
            (-0.4 * d.forearm_radius, 0.0, -0.38 * d.forearm_length),
        ),
        # 腿：膝和踝的电机放在上面，经连杆带动关节，所以腿的下端轻。
        (Segment.THIGH, "hip_yaw"): ((0.0, 0.0, -0.16 * d.thigh_length),),
        (Segment.THIGH, "knee"): ((0.0, 0.0, -0.38 * d.thigh_length),),
        (Segment.THIGH, "knee_brake"): ((0.5 * d.thigh_radius, 0.0, -0.38 * d.thigh_length),),
        (Segment.SHANK, "ankle"): (
            (-0.3 * d.shank_radius, 0.45 * d.shank_radius, -0.25 * d.shank_length),
            (-0.3 * d.shank_radius, -0.45 * d.shank_radius, -0.25 * d.shank_length),
        ),
        # 脚：力传感器在踝的正下面，脚板和压力皮肤铺满脚底，合起来放在两者中间。
        (Segment.FOOT, "foot_hardware"): (((d.foot_length / 2 - d.heel_behind_ankle) / 2, 0.0, -0.6 * d.ankle_height),),
    }


def _look_quaternion(look: Vector, up: Vector) -> np.ndarray:
    """相机朝 look 看、画面的上方是 up 时的姿态。MuJoCo 的相机朝自己的 -z 看，y 是画面的上方。"""
    backward = -np.asarray(look, dtype=float)
    backward /= np.linalg.norm(backward)
    right = np.cross(np.asarray(up, dtype=float), backward)
    right /= np.linalg.norm(right)
    true_up = np.cross(backward, right)
    quaternion = np.zeros(4)
    mujoco.mju_mat2Quat(quaternion, np.column_stack([right, true_up, backward]).flatten())
    return quaternion


class _Builder:
    """把一个身体一步步加进 MjSpec。"""

    def __init__(
        self, budget: MassBudget, assumptions: Assumptions, ranges_deg: dict[str, tuple[float, float]]
    ) -> None:
        self.budget = budget
        self._ranges_deg = ranges_deg
        self.dims = Dimensions.for_height(assumptions.height_m)
        self.joints: list[ModelJoint] = []
        self.kinds: dict[str, PartKind] = {}
        self._placements = _placements(self.dims)
        self._torques = {
            group.key: joint_peak_torques_nm(group, assumptions, budget) for group in CORE_BODY.joint_groups()
        }
        self.spec = mujoco.MjSpec()
        self.spec.modelname = MODEL_NAME
        # MjSpec 的角度默认是度；这里全部用弧度。
        self.spec.compiler.degree = False
        use_bench_settings(self.spec)
        add_floor(self.spec)
        self._add_bodies()
        self._add_drives()
        self._add_sensors()

    def compile(self, stand: StandPose | None) -> mujoco.MjModel:
        """编译成模型。给了站姿就把它存成关键帧。"""
        if stand is not None:
            store_stand_pose(self.spec, stand)
        return self.spec.compile()

    # 身体 -------------------------------------------------------------------------------------------

    def _add_bodies(self) -> None:
        d = self.dims
        pelvis = self._add_link(self.spec.worldbody, link(ROOT_LINK), None, (0.0, 0.0, d.hip_height))
        pelvis.add_freejoint(name=ROOT_JOINT)
        self._shape_pelvis(pelvis)
        chest = self._add_link(pelvis, link("chest"), None, (0.0, 0.0, d.pelvis_length))
        self._shape_chest(chest)
        head = self._add_link(chest, link("head"), None, (0.0, 0.0, d.chest_length + d.neck_joint_above_shoulder))
        self._shape_head(head)
        # 按"先把一段和它带着的都加完，再加下一段"的顺序加，这样关节清单的顺序和模型里的一样。
        for side in Side:
            self._add_arm(chest, side)
        for side in Side:
            self._add_leg(pelvis, side)

    def _add_link(self, parent, part: Link, side: Side | None, position: Vector):
        """加一段身体：它的关节，和它里面的驱动器、别的东西。外壳另外加。"""
        body = parent.add_body(name=side_prefix(side) + part.key, pos=list(mirror_point(position, side)))
        for joint in part.joints:
            self._add_skeleton_joint(body, joint, side, SEGMENT_REGIONS[part.segment])
        self._add_parts(body, part.segment, side)
        return body

    def _shape_pelvis(self, pelvis) -> None:
        d = self.dims
        bottom, top = -d.pelvis_below_hip, d.pelvis_length
        self._add_shell(
            pelvis,
            "shell",
            self.budget.spread_on_kg(Segment.PELVIS),
            mujoco.mjtGeom.mjGEOM_BOX,
            pos=[0.0, 0.0, (bottom + top) / 2],
            size=[d.pelvis_half_depth, d.pelvis_half_width, (top - bottom) / 2],
        )
        pelvis.add_site(name=PELVIS_IMU, pos=[0.0, 0.0, top / 2])

    def _shape_chest(self, chest) -> None:
        d = self.dims
        spread = self.budget.spread_on_kg(Segment.CHEST)
        bottom = CHEST_BOTTOM_GAP_FRACTION * d.chest_length
        top = d.chest_length + CHEST_TOP_ABOVE_SHOULDER_RADII * d.upper_arm_radius
        neck_top = d.chest_length + d.neck_joint_above_shoulder - d.neck_radius
        self._add_shell(
            chest,
            "shell",
            spread * (1 - NECK_SHARE_OF_CHEST),
            mujoco.mjtGeom.mjGEOM_BOX,
            pos=[0.0, 0.0, (bottom + top) / 2],
            size=[d.chest_half_depth, d.chest_half_width, (top - bottom) / 2],
        )
        self._add_shell(
            chest,
            "neck",
            spread * NECK_SHARE_OF_CHEST,
            mujoco.mjtGeom.mjGEOM_CAPSULE,
            size=[d.neck_radius, 0.0, 0.0],
            fromto=[0.0, 0.0, top, 0.0, 0.0, neck_top],
        )
        pitch = math.radians(CHEST_DEPTH_PITCH_DOWN_DEG)
        self._add_camera(
            chest,
            CHEST_DEPTH_CAMERA,
            (d.chest_half_depth, 0.0, CHEST_DEPTH_HEIGHT_FRACTION * d.chest_length),
            look=(math.cos(pitch), 0.0, -math.sin(pitch)),
            up=(math.sin(pitch), 0.0, math.cos(pitch)),
            fovy_deg=CHEST_DEPTH_FOVY_DEG,
        )

    def _shape_head(self, head) -> None:
        d = self.dims
        center = (
            HEAD_CENTER_FORWARD_FRACTION * d.head_half_length,
            0.0,
            d.head_top_above_neck_joint - d.head_half_height,
        )
        self._add_shell(
            head,
            "shell",
            self.budget.spread_on_kg(Segment.HEAD),
            mujoco.mjtGeom.mjGEOM_ELLIPSOID,
            pos=list(center),
            size=[d.head_half_length, d.head_half_width, d.head_half_height],
        )
        head.add_site(name=HEAD_IMU, pos=list(center))
        eye_forward = center[0] + EYE_FORWARD_FRACTION * d.head_half_length
        for side in Side:
            eye = mirror_point((eye_forward, EYE_SPACING_M / 2, d.eye_above_neck_joint), side)
            self._add_camera(head, eye_camera(side), eye, look=FORWARD, up=UP, fovy_deg=EYE_FOVY_DEG)

    def _add_arm(self, chest, side: Side) -> None:
        d = self.dims
        upper_arm = self._add_link(chest, link("upper_arm"), side, (0.0, d.shoulder_half_spacing, d.chest_length))
        self._add_limb_shell(upper_arm, Segment.UPPER_ARM, d.upper_arm_radius, d.upper_arm_length)
        forearm = self._add_link(upper_arm, link("forearm"), side, (0.0, 0.0, -d.upper_arm_length))
        self._add_limb_shell(forearm, Segment.FOREARM, d.forearm_radius, FOREARM_SHELL_FRACTION * d.forearm_length)
        self._add_hand(forearm, side)

    def _add_leg(self, pelvis, side: Side) -> None:
        d = self.dims
        thigh = self._add_link(pelvis, link("thigh"), side, (0.0, d.hip_half_spacing, 0.0))
        self._add_limb_shell(thigh, Segment.THIGH, d.thigh_radius, d.thigh_length)
        shank = self._add_link(thigh, link("shank"), side, (0.0, 0.0, -d.thigh_length))
        # 小腿的外壳在踝上面一点就结束，不会碰到地面。
        self._add_limb_shell(
            shank, Segment.SHANK, d.shank_radius, d.shank_length - SHANK_END_GAP_RADII * d.shank_radius
        )
        shank.add_site(name=knee_front_site(side), pos=[d.shank_radius, 0.0, -KNEE_FRONT_BELOW_JOINT_RATIO * d.height])
        foot = self._add_link(shank, link("foot"), side, (0.0, 0.0, -d.shank_length))
        self._shape_foot(foot, side)

    def _shape_foot(self, foot, side: Side) -> None:
        d = self.dims
        spread = self.budget.spread_on_kg(Segment.FOOT)
        center_forward = d.foot_length / 2 - d.heel_behind_ankle
        self._add_shell(
            foot,
            "sole",
            spread * SOLE_SHARE_OF_FOOT,
            mujoco.mjtGeom.mjGEOM_BOX,
            pos=[center_forward, 0.0, -d.ankle_height + d.sole_thickness / 2],
            size=[d.foot_length / 2, d.foot_width / 2, d.sole_thickness / 2],
        )
        self._add_shell(
            foot,
            "ankle",
            spread * (1 - SOLE_SHARE_OF_FOOT),
            mujoco.mjtGeom.mjGEOM_SPHERE,
            size=[ANKLE_BALL_RADII * d.shank_radius, 0.0, 0.0],
        )
        foot.add_site(name=sole_site(side), pos=[center_forward, 0.0, -d.ankle_height])
        foot.add_site(name=toe_site(side), pos=[d.foot_length - d.heel_behind_ankle, 0.0, -d.ankle_height])
        foot.add_site(name=ankle_ft_site(side), pos=[0.0, 0.0, 0.0])

    def _add_limb_shell(self, body, segment: Segment, radius: float, length: float) -> None:
        """手臂和腿的外壳：从这一段的原点往下的一根胶囊。"""
        self._add_shell(
            body,
            "shell",
            self.budget.spread_on_kg(segment),
            mujoco.mjtGeom.mjGEOM_CAPSULE,
            size=[radius, 0.0, 0.0],
            fromto=[0.0, 0.0, 0.0, 0.0, 0.0, -length],
        )

    # 手 ---------------------------------------------------------------------------------------------

    def _add_hand(self, forearm, side: Side) -> None:
        d = self.dims
        hand_mass = self.budget.by_segment[Segment.HAND]
        palm = self._add_link(forearm, link("hand"), side, (0.0, 0.0, -d.forearm_length))
        self._add_palm_half(palm, RADIAL_PALM_SPAN, PALM_ORIGIN, hand_mass * RADIAL_PALM_MASS_FRACTION, side)
        for digit in DIGITS:
            if not digit.on_ulnar_palm:
                self._add_digit(palm, PALM_ORIGIN, digit, side, hand_mass)
        ulnar = palm.add_body(name=f"{palm.name}_ulnar", pos=self._hand_point(PALM_ARCH_PIVOT, side))
        self._add_hand_joint(ulnar, PALM_ARCH, side)
        self._add_palm_half(ulnar, ULNAR_PALM_SPAN, PALM_ARCH_PIVOT, hand_mass * ULNAR_PALM_MASS_FRACTION, side)
        for digit in DIGITS:
            if digit.on_ulnar_palm:
                self._add_digit(ulnar, PALM_ARCH_PIVOT, digit, side, hand_mass)
        palm.add_site(name=wrist_ft_site(side), pos=[0.0, 0.0, 0.0])
        palm.add_site(name=palm_site(side), pos=self._hand_point(PALM_CENTER, side))
        self._add_camera(
            palm,
            palm_camera(side),
            tuple(self._hand_point(PALM_CAMERA_POSITION, side)),
            look=from_hand((0.0, 0.0, 1.0), side),
            up=UP,
            fovy_deg=PALM_CAMERA_FOVY_DEG,
        )

    def _hand_point(self, point: Vector, side: Side) -> list[float]:
        """手里的一个点（手长的倍数）换成身体坐标里的米。"""
        return [self.dims.hand_length * value for value in from_hand(point, side)]

    def _add_palm_half(self, body, span, origin: Vector, mass: float, side: Side) -> None:
        """加半边手掌：一个扁的盒子。span 是它在手里占的范围，origin 是这个身体的原点在手里的位置。"""
        (tip_from, tip_to), (thumb_from, thumb_to) = span
        center = ((tip_from + tip_to) / 2 - origin[0], (thumb_from + thumb_to) / 2 - origin[1], -origin[2])
        length = self.dims.hand_length
        # 盒子的三条半边：身体的 x 是往拇指一侧，y 是手心的方向，z 是往指尖。
        size = [
            length * (thumb_to - thumb_from) / 2,
            length * PALM_HALF_THICKNESS_RATIO,
            length * (tip_to - tip_from) / 2,
        ]
        self._add_shell(body, "palm", mass, mujoco.mjtGeom.mjGEOM_BOX, pos=self._hand_point(center, side), size=size)

    def _add_digit(self, parent, origin: Vector, digit: Digit, side: Side, hand_mass: float) -> None:
        """加一根手指：一节一节接上去，最后在指尖放一个点。"""
        length = self.dims.hand_length
        radius = digit.radius_ratio * length
        direction = np.array(from_hand(digit.direction, side))
        position = np.array(self._hand_point(digit.base, side)) - np.array(self._hand_point(origin, side))
        body = parent
        for phalanx in digit.phalanges:
            body = body.add_body(name=f"{side.value}_{phalanx.key}", pos=position)
            for joint in phalanx.joints:
                self._add_hand_joint(body, joint, side)
            reach = phalanx.length_ratio * length
            # 最后一节的胶囊短一个半径，圆头正好到指尖。
            shell_reach = reach - radius if phalanx is digit.phalanges[-1] else reach
            self._add_shell(
                body,
                "shell",
                hand_mass * phalanx.mass_fraction,
                mujoco.mjtGeom.mjGEOM_CAPSULE,
                size=[radius, 0.0, 0.0],
                fromto=[0.0, 0.0, 0.0, *(direction * shell_reach)],
            )
            position = direction * reach
        body.add_site(name=tip_site(side, digit.key), pos=position)

    # 关节 -------------------------------------------------------------------------------------------

    def _add_skeleton_joint(self, body, joint: Joint, side: Side | None, region: Region) -> None:
        torque = self._torques[joint.group][joint.index]
        lower_deg, upper_deg = self._ranges_deg.get(joint.key, (joint.lower_deg, joint.upper_deg))
        model_joint = ModelJoint(
            name=side_prefix(side) + joint.key,
            label=joint.name if side is None else f"{SIDE_NAMES[side]} {joint.name}",
            key=joint.key,
            side=side,
            region=region,
            lower_rad=math.radians(lower_deg),
            upper_rad=math.radians(upper_deg),
            positive=joint.positive,
            peak_torque_nm=torque,
        )
        self._add_joint(
            body, model_joint, mirror_axis(joint.axis, side), ARMATURE_PER_NM * torque, PASSIVE_DAMPING_PER_NM * torque
        )

    def _add_hand_joint(self, body, joint: HandJoint, side: Side) -> None:
        model_joint = ModelJoint(
            name=f"{side.value}_{joint.key}",
            label=f"{SIDE_NAMES[side]} {joint.name}",
            key=joint.key,
            side=side,
            region=Region.HAND,
            lower_rad=math.radians(joint.lower_deg),
            upper_rad=math.radians(joint.upper_deg),
            positive=joint.positive,
            peak_torque_nm=joint.peak_torque_nm,
            follows=None if joint.follows is None else f"{side.value}_{joint.follows}",
            follow_ratio=joint.follow_ratio,
        )
        armature = FOLLOWER_ARMATURE if joint.peak_torque_nm is None else HAND_ARMATURE
        self._add_joint(body, model_joint, mirror_axis(joint.axis, side), armature, HAND_PASSIVE_DAMPING)

    def _add_joint(self, body, joint: ModelJoint, axis: Vector, armature: float, passive_damping: float) -> None:
        body.add_joint(
            name=joint.name,
            type=mujoco.mjtJoint.mjJNT_HINGE,
            axis=list(axis),
            range=[joint.lower_rad, joint.upper_rad],
            limited=mujoco.mjtLimited.mjLIMITED_TRUE,
            armature=armature,
            damping=passive_damping,
        )
        self.joints.append(joint)

    def _add_drives(self) -> None:
        """每个有电机的关节加一个位置驱动器；跟着别的关节动的，加一条联动。"""
        for joint in self.joints:
            if joint.peak_torque_nm is not None:
                actuator = self.spec.add_actuator(name=joint.name, trntype=mujoco.mjtTrn.mjTRN_JOINT, target=joint.name)
                actuator.set_to_position(kp=joint.stiffness, kv=joint.damping)
                actuator.forcelimited = mujoco.mjtLimited.mjLIMITED_TRUE
                actuator.forcerange = [-joint.peak_torque_nm, joint.peak_torque_nm]
                actuator.ctrllimited = mujoco.mjtLimited.mjLIMITED_TRUE
                actuator.ctrlrange = [joint.lower_rad, joint.upper_rad]
            elif joint.follows is not None:
                coupling = self.spec.add_equality(
                    name=f"{joint.name}_follows",
                    type=mujoco.mjtEq.mjEQ_JOINT,
                    name1=joint.name,
                    name2=joint.follows,
                    objtype=mujoco.mjtObj.mjOBJ_JOINT,
                )
                # 这个关节的角度 = 0 + 比例 x 被跟着的关节的角度。
                coupling.data = [0.0, joint.follow_ratio] + [0.0] * (EQUALITY_DATA_SIZE - 2)

    # 身体里的东西 -----------------------------------------------------------------------------------

    def _add_parts(self, body, segment: Segment, side: Side | None) -> None:
        """这一段里的驱动器和别的东西，各放一个带质量的小块。"""
        for key, masses in self._units_in(segment).items():
            positions = self._placements.get((segment, key))
            if positions is None:
                raise ModelError(f"模型里还没有给 {key} 定位置（在{segment.value}这一段）")
            if len(positions) != len(masses):
                raise ModelError(f"{key}：这一段里有 {len(masses)} 个，却给了 {len(positions)} 个位置")
            for index, (mass, position) in enumerate(zip(masses, positions, strict=True), start=1):
                suffix = f"_{index}" if len(masses) > 1 else ""
                self._add_part(body, f"{body.name}.{key}{suffix}", key, mass, mirror_point(position, side))

    def _units_in(self, segment: Segment) -> dict[str, list[float]]:
        """这一段的一个身体里，每样东西各有几个、各多重。"""
        units: dict[str, list[float]] = defaultdict(list)
        for part in (*self.budget.actuators, *self.budget.items):
            if part.segment is not segment or part.key == SPREAD_OVER_HAND:
                continue
            per_body, left_over = divmod(part.count, segment_count(segment))
            if left_over:
                raise ModelError(f"{part.name}：{part.count} 个分不到左右两侧")
            units[part.key] += [part.mass_each_kg] * per_body
        return units

    def _add_part(self, body, name: str, key: str, mass: float, position: Vector) -> None:
        """加一个不参加碰撞的小块，只带质量。大小按这类东西的密度定。"""
        kind = ITEM_KINDS.get(key, PartKind.MOTOR)
        style = PART_STYLES[kind]
        volume = mass / style.density
        if style.aspect is None:
            geom_type = mujoco.mjtGeom.mjGEOM_SPHERE
            size = [(3 * volume / (4 * math.pi)) ** (1 / 3), 0.0, 0.0]
        else:
            geom_type = mujoco.mjtGeom.mjGEOM_BOX
            scale = (volume / math.prod(style.aspect)) ** (1 / 3)
            size = [scale * edge / 2 for edge in style.aspect]
        body.add_geom(
            name=name,
            type=geom_type,
            size=size,
            pos=list(position),
            mass=mass,
            rgba=list(style.rgba),
            contype=0,
            conaffinity=0,
            group=PART_GROUP,
        )
        self.kinds[name] = kind

    def _add_shell(self, body, label: str, mass: float, geom_type, **shape) -> None:
        """加一块外壳：带着骨架、线、皮肤的质量，会和地面碰撞（碰撞的软硬和摩擦由地面定）。"""
        name = f"{body.name}.{label}"
        body.add_geom(
            name=name,
            type=geom_type,
            mass=mass,
            rgba=list(PART_STYLES[PartKind.SHELL].rgba),
            contype=1,
            conaffinity=0,
            group=SHELL_GROUP,
            **shape,
        )
        self.kinds[name] = PartKind.SHELL

    def _add_camera(self, body, name: str, position: Vector, *, look: Vector, up: Vector, fovy_deg: float) -> None:
        # 相机的视角在 MuJoCo 里总是用度。
        body.add_camera(name=name, pos=list(position), quat=_look_quaternion(look, up), fovy=fovy_deg)

    # 传感器 -----------------------------------------------------------------------------------------

    def _add_sensors(self) -> None:
        add_joint_sensors(
            self.spec,
            joints=[joint.name for joint in self.joints],
            driven=[joint.name for joint in self.joints if joint.peak_torque_nm is not None],
        )
        for site in IMU_SITES:
            self._add_sensor(site + ACCELERATION_SUFFIX, mujoco.mjtSensor.mjSENS_ACCELEROMETER, site)
            self._add_sensor(site + GYRO_SUFFIX, mujoco.mjtSensor.mjSENS_GYRO, site)
        for side in Side:
            for site in (ankle_ft_site(side), wrist_ft_site(side)):
                self._add_sensor(site + FORCE_SUFFIX, mujoco.mjtSensor.mjSENS_FORCE, site)
                self._add_sensor(site + MOMENT_SUFFIX, mujoco.mjtSensor.mjSENS_TORQUE, site)
            for digit in DIGITS:
                tip_body = f"{side.value}_{digit.phalanges[-1].key}"
                self._add_contact_sensor(tip_force_sensor(side, digit.key), tip_body, whole_subtree=False)
        for part in LINKS:
            for side in sides_of(part):
                body = side_prefix(side) + part.key
                # 手这一段包括手掌和所有手指。
                self._add_contact_sensor(body + CONTACT_SUFFIX, body, whole_subtree=part.segment is Segment.HAND)

    def _add_sensor(self, name: str, sensor_type, target: str) -> None:
        self.spec.add_sensor(name=name, type=sensor_type, objtype=_SENSOR_TARGETS[sensor_type], objname=target)

    def _add_contact_sensor(self, name: str, body: str, *, whole_subtree: bool) -> None:
        """这个身体（或它带着的整个子树）受到的接触力的合力，在世界坐标里。"""
        target = mujoco.mjtObj.mjOBJ_XBODY if whole_subtree else mujoco.mjtObj.mjOBJ_BODY
        sensor = self.spec.add_sensor(name=name, type=mujoco.mjtSensor.mjSENS_CONTACT, reftype=target, refname=body)
        sensor.intprm = [CONTACT_DATA_FORCE, CONTACT_REDUCE_NET_FORCE, CONTACT_SLOTS]


_SENSOR_TARGETS = {
    mujoco.mjtSensor.mjSENS_ACCELEROMETER: mujoco.mjtObj.mjOBJ_SITE,
    mujoco.mjtSensor.mjSENS_GYRO: mujoco.mjtObj.mjOBJ_SITE,
    mujoco.mjtSensor.mjSENS_FORCE: mujoco.mjtObj.mjOBJ_SITE,
    mujoco.mjtSensor.mjSENS_TORQUE: mujoco.mjtObj.mjOBJ_SITE,
}
