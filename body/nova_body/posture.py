"""站姿：站着的时候各关节放在什么角度。

膝微弯；髋和踝配合着，让躯干竖直、脚底贴地。踝的角度用数值方法找：让重心正好在两只脚的正中间上面。
手臂自然垂着，稍微离开身体；手指微微弯着。这样没有关节顶在范围的边上。

驱动器的目标不只是关节的角度，还带上了"顶住重力要的力矩"，所以站姿正好是平衡的位置，身体不会往下沉。
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

import mujoco
import numpy as np

from nova_body.hand import DIGITS, hand_joints
from nova_body.skeleton import ROOT_LINK, Side, sole_site

KNEE_BEND_DEG = 15.0
FREE_JOINT_HEIGHT_INDEX = 2
FREE_JOINT_DOF = 6
BISECTION_STEPS = 60
# 站姿平衡时，整个身体受的合力和合力矩应该是 0；大于这个数（N 或 N·m）就是不平衡。
BALANCE_TOLERANCE = 1.0e-6

_FINGERS = tuple(digit.key for digit in DIGITS if digit.key != "thumb")

# 放松时各关节的角度（度），左右一样。没写的是 0。腿的三个关节另外算。
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


class PostureError(RuntimeError):
    """找不到能站住的姿势。"""


@dataclass(frozen=True)
class StandPose:
    """站姿。qpos 是模型的全部位置。

    holding_torque_nm 是每个驱动器在站姿上要出的力矩（顶住重力）。
    ctrl 是每个驱动器的目标：关节的角度 + 这个力矩 ÷ 刚度。这样驱动器在站姿上正好出这么大的力矩。
    """

    qpos: tuple[float, ...]
    ctrl: tuple[float, ...]
    holding_torque_nm: tuple[float, ...]
    knee_deg: float
    ankle_deg: float
    hip_deg: float
    pelvis_height_m: float
    center_of_mass_height_m: float


def solve_stand_pose(model: mujoco.MjModel, knee_deg: float = KNEE_BEND_DEG) -> StandPose:
    """算出站姿：膝弯 knee_deg，躯干竖直，重心在两只脚的正中间上面，脚底贴地。"""
    data = mujoco.MjData(model)
    knee = math.radians(knee_deg)
    root = model.body(ROOT_LINK).id

    def center_of_mass_ahead_of_feet(ankle: float) -> float:
        _set_pose(model, data, knee, ankle)
        return float(data.subtree_com[root][0] - _between_soles(model, data)[0])

    ankle_limit = float(model.joint(f"{Side.LEFT.value}_ankle_pitch").range[1])
    ankle = _find_zero(center_of_mass_ahead_of_feet, 0.0, ankle_limit)
    _set_pose(model, data, knee, ankle)
    # 把整个身体放低（或抬高），让脚底正好贴着地面。
    data.qpos[FREE_JOINT_HEIGHT_INDEX] -= _between_soles(model, data)[2]
    _update_positions(model, data)
    torques = _holding_torques(model, data)
    driven = [int(model.actuator_trnid[index, 0]) for index in range(model.nu)]
    holding = [float(torques[model.jnt_dofadr[joint]]) for joint in driven]
    stiffness = model.actuator_gainprm[:, 0]
    return StandPose(
        qpos=tuple(float(value) for value in data.qpos),
        ctrl=tuple(
            float(data.qpos[model.jnt_qposadr[joint]] + torque / stiffness[index])
            for index, (joint, torque) in enumerate(zip(driven, holding, strict=True))
        ),
        holding_torque_nm=tuple(holding),
        knee_deg=knee_deg,
        ankle_deg=math.degrees(ankle),
        hip_deg=math.degrees(knee - ankle),
        pelvis_height_m=float(data.qpos[FREE_JOINT_HEIGHT_INDEX]),
        center_of_mass_height_m=float(data.subtree_com[root][2]),
    )


def _set_pose(model: mujoco.MjModel, data: mujoco.MjData, knee: float, ankle: float) -> None:
    """按膝和踝的角度摆好全身。髋 = 膝 - 踝，这样躯干是竖直的，脚底是平的。"""
    data.qpos[:] = model.qpos0
    angles = {key: math.radians(degrees) for key, degrees in RELAXED_DEG.items()}
    angles |= {"knee": knee, "ankle_pitch": ankle, "hip_pitch": knee - ankle}
    for joint in hand_joints():
        if joint.follows is not None:
            angles[joint.key] = joint.follow_ratio * angles.get(joint.follows, 0.0)
    for side in Side:
        for key, angle in angles.items():
            data.qpos[model.joint(f"{side.value}_{key}").qposadr[0]] = angle
    _update_positions(model, data)


def _update_positions(model: mujoco.MjModel, data: mujoco.MjData) -> None:
    mujoco.mj_kinematics(model, data)
    mujoco.mj_comPos(model, data)


def _between_soles(model: mujoco.MjModel, data: mujoco.MjData) -> np.ndarray:
    """两只脚底正中间的点。"""
    soles = [data.site_xpos[model.site(sole_site(side)).id] for side in Side]
    return np.mean(soles, axis=0)


def _holding_torques(model: mujoco.MjModel, data: mujoco.MjData) -> np.ndarray:
    """站姿上每个自由度要多大的力才能不动：顶住重力，减去地面托着两只脚的力。

    重心在两只脚的正中间上面，所以地面托每只脚的力是一半体重，作用在脚底的正中间。
    """
    mujoco.mj_forward(model, data)
    half_weight = -model.opt.gravity[2] * model.body_subtreemass[model.body(ROOT_LINK).id] / 2
    from_floor = np.zeros(model.nv)
    for side in Side:
        site = model.site(sole_site(side)).id
        push_up = np.array([0.0, 0.0, half_weight])
        mujoco.mj_applyFT(model, data, push_up, np.zeros(3), data.site_xpos[site], model.site_bodyid[site], from_floor)
    torques = data.qfrc_bias - from_floor
    if np.abs(torques[:FREE_JOINT_DOF]).max() > BALANCE_TOLERANCE:
        raise PostureError("站姿不平衡：地面托着两只脚的力顶不住整个身体")
    # 跟着别的关节动的关节没有驱动器，它要的力矩由带着它的那个关节出。
    for index in range(model.neq):
        if model.eq_type[index] == mujoco.mjtEq.mjEQ_JOINT:
            follower = model.jnt_dofadr[model.eq_obj1id[index]]
            leader = model.jnt_dofadr[model.eq_obj2id[index]]
            torques[leader] += model.eq_data[index, 1] * torques[follower]
    return torques


def _find_zero(function: Callable[[float], float], low: float, high: float) -> float:
    """二分法：function 在 low 是负的、在 high 是正的，找它等于 0 的地方。"""
    if function(low) > 0 or function(high) < 0:
        raise PostureError("找不到让重心落在脚中间的站姿：踝在能转的范围里做不到")
    for _ in range(BISECTION_STEPS):
        middle = (low + high) / 2
        if function(middle) < 0:
            low = middle
        else:
            high = middle
    return (low + high) / 2
