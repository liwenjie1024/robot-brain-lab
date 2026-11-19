"""脊髓层（C++，nova_rt）接到测试台的身体上（P2 的 2.1 步）。

照模型里的驱动器建它：每个驱动器带着哪些关节、系数多少（只带一个关节的位置驱动器，或者带着一根固定肌腱：
比如并联的一对按和、差带两个关节）、力的上限；每个关节的范围、峰值力矩。驱动器有模型（转速、功率）就用上，
没有（基线的身体）就不限转速和功率。

测试台每 1 毫秒：读驱动器的位置和转速 → 脊髓层 → 驱动器的命令（目标、软硬、前馈力）交给驱动器那一层。
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import mujoco
import nova_rt
import numpy as np

from nova_body.actuation import ImpedanceCommand
from nova_body.bench import STAND_KEY
from nova_body.body import Body
from nova_body.drives import DriveSpec

# 目标离关节范围的两头至少这么远：不让关节撞到头（撞到头的冲击很大，真机上会坏）。
ANGLE_MARGIN_RAD = math.radians(0.5)


class SpineError(ValueError):
    """模型里有脊髓层接不了的驱动器（不是位置控制的、带着的东西不认得）。"""


@dataclass(frozen=True)
class JointCommand:
    """给脊髓层的：每个关节的目标、目标转速、刚度、阻尼、前馈力矩。顺序是脊髓层的关节的顺序。"""

    position_rad: np.ndarray
    velocity_rad_s: np.ndarray
    stiffness_nm_per_rad: np.ndarray
    damping_nms_per_rad: np.ndarray
    torque_nm: np.ndarray


def spine_joints(model: mujoco.MjModel) -> list[int]:
    """驱动器带着的关节在模型里的编号，按模型里的顺序。这就是脊髓层的关节的顺序。"""
    driven = {joint for transmissions in model_transmissions(model) for joint, _ in transmissions}
    return sorted(driven)


def spine_for(model: mujoco.MjModel, drives: Sequence[DriveSpec | None] | None = None) -> nova_rt.Spine:
    """照模型（和驱动器的模型）建脊髓层。力的上限按模型里写的（驱动器那一层每一步改它以前的）。"""
    joints = spine_joints(model)
    index_of = {joint: index for index, joint in enumerate(joints)}
    transmissions = [
        [(index_of[joint], coefficient) for joint, coefficient in actuator] for actuator in model_transmissions(model)
    ]
    peaks = [_actuator_peak(model, actuator) for actuator in range(model.nu)]
    if drives is not None and len(drives) != model.nu:
        raise SpineError(f"模型里有 {model.nu} 个驱动器，驱动器的模型却给了 {len(drives)} 个")
    limits = [
        _joint_limits(model, joint, index_of[joint], transmissions=transmissions, peaks=peaks, drives=drives)
        for joint in joints
    ]
    return nova_rt.Spine(
        joint_names=[mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, joint) for joint in joints],
        joint_limits=limits,
        actuator_names=[
            mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, actuator) for actuator in range(model.nu)
        ],
        transmissions=transmissions,
        actuator_peak_forces=peaks,
        angle_margin_rad=ANGLE_MARGIN_RAD,
    )


def actuator_joint_indices(model: mujoco.MjModel) -> list[list[int]]:
    """每个驱动器带着的关节，用脊髓层的关节编号。"""
    index_of = {joint: index for index, joint in enumerate(spine_joints(model))}
    return [[index_of[joint] for joint, _ in actuator] for actuator in model_transmissions(model)]


def step_spine(spine: nova_rt.Spine, data: mujoco.MjData, command: JointCommand) -> nova_rt.StepResult:
    """读驱动器的位置和转速（真机上是驱动器上的编码器），算这一步给驱动器的命令。"""
    return spine.step(
        data.actuator_length.copy(),
        data.actuator_velocity.copy(),
        command.position_rad,
        command.velocity_rad_s,
        command.stiffness_nm_per_rad,
        command.damping_nms_per_rad,
        command.torque_nm,
    )


def impedance_command(result: nova_rt.StepResult) -> ImpedanceCommand:
    """脊髓层一步的结果，交给驱动器那一层的样子。"""
    return ImpedanceCommand(
        position=np.array(result.actuator_position),
        stiffness=np.array(result.actuator_stiffness),
        damping=np.array(result.actuator_damping),
        force=np.array(result.actuator_force),
    )


def joint_gains_from_actuators(
    spine: nova_rt.Spine, stiffness: Sequence[float], damping: Sequence[float]
) -> tuple[np.ndarray, np.ndarray]:
    """每个驱动器自己的软硬，换成关节的（Cᵀ K C 的对角）。并联的一对两个驱动器一样软硬时，正好没有交叉的项。"""
    joint_stiffness = np.zeros(spine.joint_count)
    joint_damping = np.zeros(spine.joint_count)
    for (actuators, joints), forward in _group_matrices(spine):
        k = np.diag(np.asarray(stiffness, dtype=float)[actuators])
        d = np.diag(np.asarray(damping, dtype=float)[actuators])
        joint_stiffness[joints] = np.diag(forward.T @ k @ forward)
        joint_damping[joints] = np.diag(forward.T @ d @ forward)
    return joint_stiffness, joint_damping


def stand_command(body: Body, model: mujoco.MjModel, spine: nova_rt.Spine) -> JointCommand:
    """站姿当成关节的命令：目标是站姿（模型里的关键帧 stand）的角度，软硬是测试台给驱动器的软硬换到关节上，
    前馈是顶住重力的力矩。策略不管的关节、测试台让身体站着时用它。"""
    joints = spine_joints(model)
    key = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, STAND_KEY)
    if key < 0:
        raise SpineError("模型里没有站姿（关键帧 stand）")
    stiffness, damping = joint_gains_from_actuators(spine, model.actuator_gainprm[:, 0], -model.actuator_biasprm[:, 2])
    return JointCommand(
        position_rad=model.key_qpos[key][model.jnt_qposadr[joints]].copy(),
        velocity_rad_s=np.zeros(len(joints)),
        stiffness_nm_per_rad=stiffness,
        damping_nms_per_rad=damping,
        torque_nm=np.array(body.joint_holding_torques_nm),
    )


def _group_matrices(spine: nova_rt.Spine):
    """每一组的驱动器、关节和换算矩阵 C_g（从单位向量量出来，和 C++ 里用的一样）。"""
    for actuators, joints in spine.groups:
        forward = np.zeros((len(actuators), len(joints)))
        for column, joint in enumerate(joints):
            unit = np.zeros(spine.joint_count)
            unit[joint] = 1.0
            forward[:, column] = spine.actuators_from_joints(unit)[actuators]
        yield (np.array(actuators), np.array(joints)), forward


def model_transmissions(model: mujoco.MjModel) -> list[list[tuple[int, float]]]:
    """每个驱动器带着的（模型里的关节编号、系数）。驱动器"转"的量 = 系数 x 关节角度加起来。"""
    found = []
    for actuator in range(model.nu):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, actuator)
        is_position = (
            model.actuator_gaintype[actuator] == mujoco.mjtGain.mjGAIN_FIXED
            and model.actuator_biastype[actuator] == mujoco.mjtBias.mjBIAS_AFFINE
        )
        if not is_position:
            raise SpineError(f"驱动器 {name} 不是位置控制的（脊髓层给的是目标和软硬）")
        gear = float(model.actuator_gear[actuator, 0])
        target = int(model.actuator_trnid[actuator, 0])
        if model.actuator_trntype[actuator] == mujoco.mjtTrn.mjTRN_JOINT:
            found.append([(target, gear)])
        elif model.actuator_trntype[actuator] == mujoco.mjtTrn.mjTRN_TENDON:
            found.append(_fixed_tendon(model, target, gear, name))
        else:
            raise SpineError(f"驱动器 {name} 带着的东西脊髓层不认得（只认关节和固定肌腱）")
    return found


def _fixed_tendon(model: mujoco.MjModel, tendon: int, gear: float, actuator: str) -> list[tuple[int, float]]:
    start, count = int(model.tendon_adr[tendon]), int(model.tendon_num[tendon])
    wraps = []
    for wrap in range(start, start + count):
        if model.wrap_type[wrap] != mujoco.mjtWrap.mjWRAP_JOINT:
            raise SpineError(f"驱动器 {actuator} 的肌腱不是固定肌腱（只带着关节）")
        wraps.append((int(model.wrap_objid[wrap]), gear * float(model.wrap_prm[wrap])))
    return wraps


def _actuator_peak(model: mujoco.MjModel, actuator: int) -> float:
    if not model.actuator_forcelimited[actuator]:
        return math.inf
    low, high = model.actuator_forcerange[actuator]
    return float(min(-low, high))


def _joint_limits(
    model: mujoco.MjModel,
    joint: int,
    index: int,
    *,
    transmissions: list[list[tuple[int, float]]],
    peaks: list[float],
    drives: Sequence[DriveSpec | None] | None,
) -> nova_rt.JointLimits:
    """关节的范围、峰值力矩（带着它的驱动器都往这一边出全力；模型在关节上写了上限就取小的），
    有驱动器的模型时再加转速（最慢的那个驱动器的空载转速）和功率（带着它的驱动器的峰值功率加起来）。"""
    lower, upper = model.jnt_range[joint] if model.jnt_limited[joint] else (-math.inf, math.inf)
    carriers = [
        (actuator, abs(coefficient))
        for actuator, actuator_transmissions in enumerate(transmissions)
        for joint_index, coefficient in actuator_transmissions
        if joint_index == index
    ]
    peak = sum(peaks[actuator] * coefficient for actuator, coefficient in carriers)
    if model.jnt_actfrclimited[joint]:
        peak = min(peak, float(min(-model.jnt_actfrcrange[joint, 0], model.jnt_actfrcrange[joint, 1])))
    speed, power = math.inf, math.inf
    if drives is not None and all(drives[actuator] is not None for actuator, _ in carriers):
        speed = min(drives[actuator].no_load_speed_rad_s / coefficient for actuator, coefficient in carriers)
        power = sum(drives[actuator].peak_torque_nm * drives[actuator].knee_speed_rad_s for actuator, _ in carriers)
    return nova_rt.JointLimits(float(lower), float(upper), peak, speed, power)
