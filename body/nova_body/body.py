"""测试台眼里的"一个身体"。

Nova（代码生成的）和基线（现成的 Unitree G1）都按这里的样子交给测试台。
测试台（站姿、站着、画图）只认这里写的东西，不管身体是哪一个、是怎么来的。
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

import mujoco

from nova_body.drives import DriveSpec


class Side(StrEnum):
    """身体的哪一侧。"""

    LEFT = "left"
    RIGHT = "right"


SIDE_NAMES: dict[Side, str] = {Side.LEFT: "左", Side.RIGHT: "右"}


class ImuGrade(StrEnum):
    """IMU 是哪一种（噪声、零偏差得多）。"""

    STANDARD = "一般的"
    PRECISE = "高精度的"


class Region(StrEnum):
    """关节在身体的哪一部分。给人看的时候按这个分组。"""

    LEG = "腿"
    WAIST = "腰"
    NECK = "颈"
    ARM = "手臂"
    HAND = "手"


@dataclass(frozen=True)
class Leg:
    """一条腿上测试台要认得的东西，都是模型里的名字。

    三个关节都绕左右方向的轴转。sole 是脚底正中间的一个点（site），在贴着地面的那一面上。
    knee_front 是膝盖前面跪地时着地的点，toe 是脚尖（脚底最前面的那条边的中间）。没有就是 None。
    """

    hip_pitch: str
    knee: str
    ankle_pitch: str
    foot: str
    sole: str
    knee_front: str | None = None
    toe: str | None = None


@dataclass(frozen=True)
class Imu:
    """一个 IMU：装在哪，量加速度和量角速度的两个传感器在模型里叫什么，是哪一种。"""

    label: str
    accelerometer: str
    gyro: str
    grade: ImuGrade = ImuGrade.STANDARD


@dataclass(frozen=True)
class ForceSensor:
    """一个六轴力传感器：装在哪，量力和量力矩的两个传感器在模型里叫什么。

    noise_scale 是噪声按一般的（腕那样的量程）的几倍：量程大的（踝要扛住体重）噪声也大。
    """

    label: str
    force: str
    moment: str
    noise_scale: float = 1.0


@dataclass(frozen=True)
class TouchSensor:
    """一处受到的接触力（三个方向的合力，世界坐标）：在哪，传感器在模型里叫什么。"""

    label: str
    sensor: str


@dataclass(frozen=True)
class CameraView:
    """一台相机：装在哪，在模型里叫什么。"""

    label: str
    camera: str


@dataclass(frozen=True)
class Anatomy:
    """身体上测试台要认得的地方。

    root 是骨盆（看它的高度、歪了多少），trunk 是胸（推的地方），都是模型里身体的名字。
    relaxed_rad 是站着时别的关节放在哪（弧度）：腿上的那三个关节由站姿来算，没写的关节是 0。
    palms 是手心正中间的点（拿东西、撑地的地方）。没有手的身体是空的。
    """

    root: str
    trunk: str
    legs: Mapping[Side, Leg]
    relaxed_rad: Mapping[str, float]
    palms: Mapping[Side, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DrivenJoint:
    """一个有驱动器带着的关节。region 是它在身体的哪一部分。

    peak_torque_nm 是这个关节单独用力时最多能出多大的力矩：带着它的驱动器都往这一个方向出全力
    （并联的一对，两个驱动器一起出，是一个的两倍）。
    """

    name: str
    label: str
    region: Region
    lower_rad: float
    upper_rad: float
    peak_torque_nm: float


@dataclass(frozen=True)
class Actuator:
    """一个驱动器。joints 是它带着的关节和系数：驱动器"转"的量 = 每个关节的角度 x 系数加起来，
    关节得到的力矩 = 驱动器的力 x 系数。一般的驱动器带一个关节，系数 1；并联的一对，一个是和（+1、+1）、
    一个是差（+1、-1）。peak_torque_nm 是它最多出多大的力（力矩的单位），lower、upper 是目标的范围。
    drive 是它的驱动器模型（力矩-转速、发热）；没有模型的（基线、手指）是 None。
    """

    name: str
    label: str
    joints: tuple[tuple[str, float], ...]
    peak_torque_nm: float
    lower: float
    upper: float
    drive: DriveSpec | None = None


@dataclass(frozen=True)
class StandPose:
    """站姿。qpos 是模型的全部位置。

    holding_torque_nm 是每个驱动器在站姿上要出的力（顶住重力；力矩的单位）。
    ctrl 是每个驱动器的目标：它现在的"长度"（带着的关节的角度 x 系数加起来）+ 这个力 ÷ 刚度。
    这样驱动器在站姿上正好出这么大的力。
    三个角度是按动作说的，不管这个身体的关节往哪边算正：膝弯了多少、脚尖向上多少、髋向前抬多少。
    """

    qpos: tuple[float, ...]
    ctrl: tuple[float, ...]
    holding_torque_nm: tuple[float, ...]
    knee_deg: float
    ankle_deg: float
    hip_deg: float
    pelvis_height_m: float
    center_of_mass_height_m: float


@dataclass(frozen=True)
class Body:
    """放上测试台的一个身体。

    joints 是有驱动器带着的关节（顺序和模型里一样）；actuators 是驱动器，顺序和模型里的驱动器一样。
    height_m 是站直时的身高。
    foot_length_m、foot_width_m 是脚底着地的那一块有多长、多宽（压力中心只能在这一块里）。
    drawn_groups 是画图时画哪几组形状。
    后面三样是这个身体自己带的别的感觉，没有就是空的：六轴力、接触力、相机。
    """

    name: str
    model: mujoco.MjModel
    anatomy: Anatomy
    joints: tuple[DrivenJoint, ...]
    actuators: tuple[Actuator, ...]
    imus: tuple[Imu, ...]
    stand: StandPose
    height_m: float
    foot_length_m: float
    foot_width_m: float
    drawn_groups: tuple[int, ...]
    force_sensors: tuple[ForceSensor, ...] = ()
    touch_sensors: tuple[TouchSensor, ...] = ()
    cameras: tuple[CameraView, ...] = ()

    @property
    def joint_holding_torques_nm(self) -> tuple[float, ...]:
        """站姿里每个有驱动器带着的关节得到的力矩（每个驱动器的力 x 系数，加起来），顺序和 joints 一样。"""
        torques = dict.fromkeys((joint.name for joint in self.joints), 0.0)
        for actuator, force in zip(self.actuators, self.stand.holding_torque_nm, strict=True):
            for name, coefficient in actuator.joints:
                torques[name] += coefficient * force
        return tuple(torques[joint.name] for joint in self.joints)

    @property
    def mass_kg(self) -> float:
        """模型里整个身体的质量。"""
        return float(self.model.body_subtreemass[self.model.body(self.anatomy.root).id])
