"""测试台上跑一个策略（2.2 步起，考试都用它）：小脑层（策略）→ 脊髓层（反射、硬限制、换算）→ 驱动器那一层 → 仿真，
状态估计跟着跑。

"大脑"有两种，样子一样（BenchBrain：怎么建身体、默认的姿势、每一步的控制器）：练出来的、有规约的策略（ContractBrain），
和现成的 SONIC（sonic_brain.SonicBrain）。身体用练的时候的那个模型（规约里写的、核对过 SHA-256），
换成测试台的步长、积分的方法和地面，可以再加一段楼梯。
可以从站着、趴着、仰着、侧躺着开始。量的都是仿真里的真数（考试的裁判不信身体自己报的）。
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import mujoco
import nova_rt
import numpy as np

from nova_body import actuation
from nova_body.actuation import DriveLayer
from nova_body.bench import FLOOR, Stairs, add_floor, add_stairs, use_bench_settings
from nova_body.estimation import BodyFeel
from nova_body.policy import Policy
from nova_body.policy_bodies import info_for
from nova_body.policy_runner import BodySense, PolicyRunner, root_body
from nova_body.spinal import SpinalLayer, reflexes_for, tilt_rad
from nova_body.spine import JointCommand, spine_for

# 开始时最低的一点离地面这么高，落下去再开始（和练的时候一样，从一点点高的地方放下）。
START_CLEARANCE_M = 0.01
# 骨盆歪过这么多度，或者离脚下的地面低到站着时的这么多倍，就算摔倒了。
FALLEN_TILT_DEG = 60.0
FALLEN_HEIGHT_SHARE = 0.5
# 骨盆离脚下的地面至少是站着时的这么多倍，歪不过这么多度，算站着（站起来了、站在这一级上了）。
UPRIGHT_HEIGHT_SHARE = 0.8
UPRIGHT_TILT_DEG = 20.0
STILL = {"lin_vel_x": 0.0, "lin_vel_y": 0.0, "ang_vel_z": 0.0}


class StartPose(StrEnum):
    """从什么样子开始。"""

    STANDING = "站着"
    PRONE = "趴着"
    SUPINE = "仰着"
    SIDE = "侧躺着"


# 躺着的样子：骨盆的前方（x 轴）和头的方向（z 轴）朝世界的哪边。都是头朝 +x 躺着。
LYING_AXES: dict[StartPose, tuple[tuple[float, float, float], tuple[float, float, float]]] = {
    StartPose.PRONE: ((0.0, 0.0, -1.0), (1.0, 0.0, 0.0)),  # 脸朝下
    StartPose.SUPINE: ((0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),  # 脸朝上
    StartPose.SIDE: ((0.0, 1.0, 0.0), (1.0, 0.0, 0.0)),  # 右边着地（左边朝上）
}


@dataclass(frozen=True)
class Tick:
    """一步里脊髓层改过命令没有（硬限制）、反射动过没有，现在是什么模式。"""

    limited: bool
    reflexes: bool
    mode: int


class Runner(Protocol):
    def step(
        self, data: mujoco.MjData, command: Mapping[str, float], sense: BodySense | None = None
    ) -> JointCommand: ...


class BenchBrain(Protocol):
    """测试台上的一个"大脑"：名字、身体的名字（policy_bodies 里认得的）、每秒算几次、怎么建身体、默认的姿势、控制器。"""

    name: str
    body_name: str
    rate_hz: float

    def load_body(self, stairs: Stairs | None = None) -> mujoco.MjModel: ...

    def default_positions(self) -> dict[str, float]: ...

    def runner(self, model: mujoco.MjModel, spine: nova_rt.Spine) -> Runner: ...


class ContractBrain:
    """练出来的、有规约的策略。"""

    def __init__(self, policy: Policy) -> None:
        self.policy = policy
        self.name, self.body_name, self.rate_hz = policy.name, policy.body_name, policy.rate_hz

    def load_body(self, stairs: Stairs | None = None) -> mujoco.MjModel:
        return load_policy_body(self.policy, stairs)

    def default_positions(self) -> dict[str, float]:
        return default_positions(self.policy)

    def runner(self, model: mujoco.MjModel, spine: nova_rt.Spine) -> PolicyRunner:
        return PolicyRunner(model, self.policy, spine)


def as_brain(brain: "Policy | BenchBrain") -> BenchBrain:
    return ContractBrain(brain) if isinstance(brain, Policy) else brain


def default_positions(policy: Policy) -> dict[str, float]:
    return {joint.name: joint.default_position_rad for joint in policy.joints}


def load_policy_body(policy: Policy, stairs: Stairs | None = None) -> mujoco.MjModel:
    """练的时候用的身体模型，放到测试台上：测试台的步长、积分的方法、地面（和楼梯）。"""
    spec = mujoco.MjSpec.from_file(str(policy.body_model_path))
    use_bench_settings(spec)
    if not any(geom.name == FLOOR for geom in spec.geoms):
        add_floor(spec)
    if stairs is not None:
        add_stairs(spec, stairs)
    return spec.compile()


def start_data(
    model: mujoco.MjModel, defaults: Mapping[str, float], pose: StartPose = StartPose.STANDING, x_m: float = 0.0
) -> mujoco.MjData:
    """默认的姿势（关节的名字 → 角度），站着或者躺着，在 x_m 处，最低的一点比地面高一点。"""
    data = mujoco.MjData(model)
    root_address = model.jnt_qposadr[free_joint(model)]
    for name, position in defaults.items():
        joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
        data.qpos[model.jnt_qposadr[joint_id]] = position
    data.qpos[root_address] = x_m
    if pose in LYING_AXES:
        data.qpos[root_address + 3 : root_address + 7] = lying_quaternion(*LYING_AXES[pose])
    mujoco.mj_forward(model, data)
    data.qpos[root_address + 2] += START_CLEARANCE_M - lowest_point_m(model, data)
    mujoco.mj_forward(model, data)
    return data


def lying_quaternion(forward: tuple[float, float, float], head: tuple[float, float, float]) -> np.ndarray:
    """骨盆的前方、头的方向朝世界的这两边时，骨盆的转动（四元数）。"""
    x, z = np.array(forward), np.array(head)
    quaternion = np.zeros(4)
    mujoco.mju_mat2Quat(quaternion, np.column_stack([x, np.cross(z, x), z]).flatten())
    return quaternion


def lowest_point_m(model: mujoco.MjModel, data: mujoco.MjData) -> float:
    """身体能碰到地面的形状里最低的一点（按每个形状的包围盒算）。"""
    lowest = math.inf
    corners = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], dtype=float)
    for geom in range(model.ngeom):
        if model.geom_bodyid[geom] == 0 or model.geom_contype[geom] == 0:
            continue
        center, half = model.geom_aabb[geom, :3], model.geom_aabb[geom, 3:]
        rotation = data.geom_xmat[geom].reshape(3, 3)
        points = data.geom_xpos[geom] + (center + corners * half) @ rotation.T
        lowest = min(lowest, float(points[:, 2].min()))
    return lowest


def free_joint(model: mujoco.MjModel) -> int:
    return next(joint for joint in range(model.njnt) if model.jnt_type[joint] == mujoco.mjtJoint.mjJNT_FREE)


class PolicyBench:
    """测试台上的一个策略：每 step 一次 = 仿真 1 毫秒（策略按它自己的周期算）。

    sensed：策略看身体自己感觉到的速度、角速度、重力方向（IMU 和状态估计）；不认识的身体做不了，就拒绝。
    fall_reflex：跌倒的反射开着没有（考"起来"的时候关掉，像小脑层在做起来的动作时那样）。
    """

    def __init__(
        self,
        policy: "Policy | BenchBrain",
        *,
        sensed: bool = True,
        stairs: Stairs | None = None,
        start: StartPose = StartPose.STANDING,
        x_m: float = 0.0,
        fall_reflex: bool = True,
    ) -> None:
        self.brain = as_brain(policy)
        self.sensed = sensed
        self.stairs = stairs
        self.fall_reflex = fall_reflex
        self.model = self.brain.load_body(stairs)
        self.spine = spine_for(self.model)
        self.spinal = SpinalLayer(self.spine, reflexes_for(self.model, self.spine))
        self.drives = DriveLayer(self.model, [None] * self.model.nu)
        self.runner = self.brain.runner(self.model, self.spine)
        self.data = start_data(self.model, self.brain.default_positions(), start, x_m)
        info = info_for(self.brain.body_name)
        if sensed and info.estimator is None:
            raise ValueError(f"测试台不知道身体 {self.brain.body_name} 的 IMU 和脚在哪，做不了状态估计")
        self.feel = BodyFeel(self.model, info.estimator, self.spine, self.data) if info.estimator else None
        self.root = root_body(self.model)
        trunk = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, info.trunk) if info.trunk else self.root
        if trunk < 0:
            raise ValueError(f"身体的模型里没有推的地方 {info.trunk}")
        self.trunk = trunk
        self.timestep = float(self.model.opt.timestep)
        self.standing_height_m = self._standing_height()
        self.work_j = 0.0
        self.distance_m = 0.0
        self._no_temperatures = np.full(self.model.nu, math.nan)
        self._no_contacts = [False] * self.spine.joint_count
        root_address = self.model.jnt_qposadr[free_joint(self.model)]
        self._ground = slice(root_address, root_address + 2)

    def _standing_height(self) -> float:
        standing = start_data(self.model, self.brain.default_positions())
        return float(standing.xpos[self.root][2])

    @property
    def time_s(self) -> float:
        return float(self.data.time)

    @property
    def weight_n(self) -> float:
        return mujoco.mj_getTotalmass(self.model) * float(np.linalg.norm(self.model.opt.gravity))

    def pelvis_xy(self) -> np.ndarray:
        """骨盆在地上的位置（x、y）。"""
        return self.data.xpos[self.root][:2].copy()

    def step(self, command, push_n: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> Tick:
        """走 1 毫秒。push_n 是这一步推在胸上的力（世界坐标，牛顿）。"""
        self.data.xfrc_applied[self.trunk, :3] = push_n
        sense = self.feel.step(self.data, self.timestep) if self.feel else None
        joint_command = self.runner.step(self.data, command, sense if self.sensed else None)
        result = self.spinal.step(
            self.data,
            joint_command,
            tilt=self._reflex_tilt_rad(),
            temperatures=self._no_temperatures,
            contacts=self._no_contacts,
            stop=nova_rt.STOP_NONE,
            dt=self.timestep,
            fall_armed=self.fall_reflex,
        )
        self.drives.command_impedance(result.impedance)
        before = self.data.qpos[self._ground].copy()
        actuation.step(self.model, self.data, self.drives)
        if self.feel:
            self.feel.sample(self.data)
        power = self.data.actuator_force * self.data.actuator_velocity
        self.work_j += float(np.clip(power, 0.0, None).sum()) * self.timestep
        self.distance_m += float(np.linalg.norm(self.data.qpos[self._ground] - before))
        return Tick(bool(result.limited.any()), bool(result.reflexes.any()), result.mode)

    def _reflex_tilt_rad(self) -> float:
        """反射看的歪斜：状态估计估出来的；测试台不认识的身体没有状态估计，看真的。"""
        if self.feel:
            return tilt_rad(self.feel.estimator.rotation)
        return math.radians(self.tilt_deg())

    def tilt_deg(self) -> float:
        up = self.data.xmat[self.root].reshape(3, 3)[:, 2]
        return math.degrees(math.acos(max(-1.0, min(1.0, float(up[2])))))

    def pelvis_height_m(self) -> float:
        """骨盆离脚下的地面多高（有楼梯时减去那一级的高度）。"""
        x = float(self.data.xpos[self.root][0])
        ground = self.stairs.height_at(x) if self.stairs else 0.0
        return float(self.data.xpos[self.root][2]) - ground

    def fallen(self) -> bool:
        too_low = self.pelvis_height_m() < FALLEN_HEIGHT_SHARE * self.standing_height_m
        return too_low or self.tilt_deg() > FALLEN_TILT_DEG

    def upright(self) -> bool:
        tall = self.pelvis_height_m() >= UPRIGHT_HEIGHT_SHARE * self.standing_height_m
        return tall and self.tilt_deg() < UPRIGHT_TILT_DEG

    def heading_velocity(self) -> np.ndarray:
        """骨盆的速度，按它朝的方向（只转了偏航）：往前、往左、往左转。"""
        address = self.model.jnt_dofadr[free_joint(self.model)]
        linear_world = self.data.qvel[address : address + 3]
        angular_local = self.data.qvel[address + 3 : address + 6]
        rotation = self.data.xmat[self.root].reshape(3, 3)
        yaw = math.atan2(rotation[1, 0], rotation[0, 0])
        cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
        forward = cos_yaw * linear_world[0] + sin_yaw * linear_world[1]
        left = -sin_yaw * linear_world[0] + cos_yaw * linear_world[1]
        turn = float((rotation @ angular_local)[2])
        return np.array([forward, left, turn])

    def estimate_errors(self) -> tuple[float, float] | None:
        """状态估计和真的差多少：速度（m/s）、歪斜（度）。没做状态估计就是 None。"""
        return self.feel.errors(self.data) if self.feel else None
