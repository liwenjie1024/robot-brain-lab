"""测试台眼里的"一个身体"。

Nova（代码生成的）和基线（现成的 Unitree G1）都按这里的样子交给测试台。
测试台（站姿、站着、画图）只认这里写的东西，不管身体是哪一个、是怎么来的。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

import mujoco


class Side(StrEnum):
    """身体的哪一侧。"""

    LEFT = "left"
    RIGHT = "right"


SIDE_NAMES: dict[Side, str] = {Side.LEFT: "左", Side.RIGHT: "右"}


@dataclass(frozen=True)
class Leg:
    """一条腿上测试台要认得的东西，都是模型里的名字。

    三个关节都绕左右方向的轴转。sole 是脚底正中间的一个点（site），在贴着地面的那一面上。
    """

    hip_pitch: str
    knee: str
    ankle_pitch: str
    foot: str
    sole: str


@dataclass(frozen=True)
class Imu:
    """一个 IMU：装在哪，量加速度和量角速度的两个传感器在模型里叫什么。"""

    label: str
    accelerometer: str
    gyro: str


@dataclass(frozen=True)
class Anatomy:
    """身体上测试台要认得的地方。

    root 是骨盆（看它的高度、歪了多少），trunk 是胸（推的地方），都是模型里身体的名字。
    relaxed_rad 是站着时别的关节放在哪（弧度）：腿上的那三个关节由站姿来算，没写的关节是 0。
    """

    root: str
    trunk: str
    legs: Mapping[Side, Leg]
    relaxed_rad: Mapping[str, float]


@dataclass(frozen=True)
class DrivenJoint:
    """一个有驱动器的关节。"""

    name: str
    label: str
    lower_rad: float
    upper_rad: float
    peak_torque_nm: float


@dataclass(frozen=True)
class StandPose:
    """站姿。qpos 是模型的全部位置。

    holding_torque_nm 是每个驱动器在站姿上要出的力矩（顶住重力）。
    ctrl 是每个驱动器的目标：关节的角度 + 这个力矩 ÷ 刚度。这样驱动器在站姿上正好出这么大的力矩。
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

    joints 的顺序和模型里的驱动器一样。height_m 是站直时的身高。
    foot_length_m 是脚底着地的那一段有多长（压力中心只能在这一段里）。
    drawn_groups 是画图时画哪几组形状。
    """

    name: str
    model: mujoco.MjModel
    anatomy: Anatomy
    joints: tuple[DrivenJoint, ...]
    imus: tuple[Imu, ...]
    stand: StandPose
    height_m: float
    foot_length_m: float
    drawn_groups: tuple[int, ...]

    @property
    def mass_kg(self) -> float:
        """模型里整个身体的质量。"""
        return float(self.model.body_subtreemass[self.model.body(self.anatomy.root).id])
