"""脊髓层在测试台上合起来（2.1 步）：反射（C++）→ 硬限制和换算（C++ 的 Spine）→ 交给驱动器那一层的命令。

每 1 毫秒，小脑层的关节命令先过反射：
- 保护：驱动器那一层报的绕组温度；
- 碰撞：手臂上的皮肤受力，带着那一段的手臂关节变软（脚踩地、手指拿东西本来就受力，不算）；
- 跌倒：状态估计给的身体歪了多少；
- 停止：安全那边的要求（0 / 1 / 2 类）。
再交给 Spine 守住硬限制、换成驱动器的命令（保护的反射把驱动器能出的力的比例也交过去）。
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import mujoco
import nova_rt
import numpy as np

from nova_body.actuation import DriveLayer, ImpedanceCommand
from nova_body.body import Body, Region
from nova_body.drives import DriveSpec
from nova_body.sensing import Readings
from nova_body.spine import JointCommand, actuator_joint_indices, impedance_command, model_transmissions

# 皮肤上受的力大过这么多才算被碰到（皮肤的噪声是 0.05 N，擦一下不算）。
SKIN_CONTACT_N = 5.0
# 哪几段的皮肤受力算"被碰到"：手臂（上臂、前臂、手掌）。脚、腿踩地，指尖拿东西，本来就受力。
ARM_SKIN_LABELS = ("上臂", "前臂", "手")


@dataclass(frozen=True)
class SpinalStep:
    """脊髓层一步的结果：给驱动器的命令，每个关节被硬限制、被反射改过没有，现在是什么模式。"""

    impedance: ImpedanceCommand
    limited: np.ndarray
    reflexes: np.ndarray
    mode: int


def brake_damping(model: mujoco.MjModel, drives: Sequence[DriveSpec | None] | None) -> list[float]:
    """0 类停止时每个关节的刹车阻尼：驱动器断电、绕组短接时的阻尼（Km²），换到关节上（Cᵀ D C 的对角）。
    没有驱动器模型的身体是 0（断电了什么都不剩）。"""
    joints = actuator_joint_indices(model)
    coefficients = _coefficients(model)
    damping = np.zeros(max((index for actuator in joints for index in actuator), default=-1) + 1)
    if drives is None:
        return damping.tolist()
    for actuator, drive in enumerate(drives):
        if drive is None:
            continue
        for joint, coefficient in zip(joints[actuator], coefficients[actuator], strict=True):
            damping[joint] += drive.km_nm_per_sqrt_w**2 * coefficient**2
    return damping.tolist()


def reflexes_for(model: mujoco.MjModel, spine: nova_rt.Spine, drives: Sequence[DriveSpec | None] | None = None):
    """照模型建反射：每个驱动器带着哪几个关节（标记要标到它们上面），每个关节的刹车阻尼。"""
    return nova_rt.Reflexes(
        joint_count=spine.joint_count,
        actuator_joints=actuator_joint_indices(model),
        brake_damping=brake_damping(model, drives),
    )


def actuator_temperatures(drives: DriveLayer, actuator_count: int) -> np.ndarray:
    """每个驱动器的绕组温度（°C）；没有驱动器模型的是 NaN（反射就不降它）。"""
    temperatures = np.full(actuator_count, math.nan)
    temperatures[drives.modeled] = drives.winding_c
    return temperatures


def tilt_rad(rotation: np.ndarray) -> float:
    """身体（IMU）的竖轴和世界的竖轴差多少弧度。"""
    return math.acos(max(-1.0, min(1.0, float(np.asarray(rotation)[2, 2]))))


class SkinMap:
    """手臂上的皮肤受力 → 带着那一段的手臂关节（从躯干到那一段，一路上的手臂关节）算被碰到。"""

    def __init__(self, body: Body, model: mujoco.MjModel, spine: nova_rt.Spine, threshold_n: float = SKIN_CONTACT_N):
        self._threshold = threshold_n
        self._joint_count = spine.joint_count
        spine_index = {name: index for index, name in enumerate(spine.joint_names)}
        arm_joints = {joint.name for joint in body.joints if joint.region == Region.ARM}
        self._sensors: list[tuple[int, list[int]]] = []
        for index, sensor in enumerate(body.touch_sensors):
            if not any(sensor.label.endswith(label) for label in ARM_SKIN_LABELS):
                continue
            chain = _joints_up_to_root(model, _sensor_body(model, sensor.sensor))
            joints = [spine_index[name] for name in chain if name in arm_joints and name in spine_index]
            if joints:
                self._sensors.append((index, joints))

    @property
    def covered_joints(self) -> set[int]:
        """皮肤管得着的关节（脊髓层的编号）。"""
        return {joint for _, joints in self._sensors for joint in joints}

    def contacts(self, readings: Readings) -> list[bool]:
        contact = [False] * self._joint_count
        for index, joints in self._sensors:
            if float(np.linalg.norm(readings.touches[index])) > self._threshold:
                for joint in joints:
                    contact[joint] = True
        return contact


class SpinalLayer:
    """脊髓层的一步：反射 → 硬限制和换算。读的是驱动器的位置和转速（真机上是驱动器上的编码器）。"""

    def __init__(self, spine: nova_rt.Spine, reflexes) -> None:
        self._spine = spine
        self._reflexes = reflexes

    @property
    def mode(self) -> int:
        return self._reflexes.mode

    def reset(self) -> None:
        self._reflexes.reset()

    def step(
        self,
        data: mujoco.MjData,
        command: JointCommand,
        *,
        tilt: float,
        temperatures: np.ndarray,
        contacts: Sequence[bool],
        stop: int,
        dt: float,
    ) -> SpinalStep:
        actuator_position = data.actuator_length.copy()
        actuator_velocity = data.actuator_velocity.copy()
        reflex = self._reflexes.step(
            command.position_rad,
            command.velocity_rad_s,
            command.stiffness_nm_per_rad,
            command.damping_nms_per_rad,
            command.torque_nm,
            self._spine.joints_from_actuators(actuator_position),
            tilt,
            np.asarray(temperatures, dtype=float),
            list(contacts),
            stop,
            dt,
        )
        result = self._spine.step(
            actuator_position,
            actuator_velocity,
            reflex.position_rad,
            reflex.velocity_rad_s,
            reflex.stiffness,
            reflex.damping,
            reflex.torque_nm,
            actuator_force_scale=reflex.actuator_force_scale,
        )
        return SpinalStep(impedance_command(result), np.array(result.limited), np.array(reflex.flags), reflex.mode)


def _coefficients(model: mujoco.MjModel) -> list[list[float]]:
    return [[coefficient for _, coefficient in actuator] for actuator in model_transmissions(model)]


def _sensor_body(model: mujoco.MjModel, sensor: str) -> int:
    """皮肤的传感器挂在哪一段上：接触传感器看它对着的身体（ref），别的看它的点（site）在哪一段。"""
    found = model.sensor(sensor)
    if int(found.reftype[0]) in (mujoco.mjtObj.mjOBJ_BODY, mujoco.mjtObj.mjOBJ_XBODY):
        return int(found.refid[0])
    if int(found.objtype[0]) == mujoco.mjtObj.mjOBJ_SITE:
        return int(model.site_bodyid[int(found.objid[0])])
    raise ValueError(f"不知道皮肤的传感器 {sensor} 挂在哪一段上")


def _joints_up_to_root(model: mujoco.MjModel, body: int) -> list[str]:
    """从这一段往上到根，一路上的关节的名字。"""
    names = []
    while body > 0:
        start, count = int(model.body_jntadr[body]), int(model.body_jntnum[body])
        names += [mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, joint) for joint in range(start, start + count)]
        body = int(model.body_parentid[body])
    return names
