"""把一个策略接到测试台上的身体：按策略的周期给它观测，按它的动作设关节的目标。

这是 2.0 步的第一版：只接"一个关节一个驱动器（位置控制）"的身体，比如 G1。
并联的一对（Nova 的踝、腰、腕）要先把关节的目标换算成驱动器的命令，那是 2.1 步脊髓层的事。
"""

from collections.abc import Mapping
from dataclasses import dataclass

import mujoco
import numpy as np

from nova_body.policy import JOINT_TERMS, ObservationTerm, Policy, PolicyError

# 步长 x 整数要正好是策略的周期，差这么多以内算正好（浮点数的误差）。
PERIOD_TOLERANCE = 1e-6
SPATIAL_SIZE = 6


@dataclass(frozen=True)
class JointBinding:
    """策略的关节在模型里的位置：角度、转速在 qpos、qvel 的第几个，哪个驱动器带着它。"""

    qpos_addresses: np.ndarray
    dof_addresses: np.ndarray
    actuator_ids: np.ndarray
    defaults_rad: np.ndarray
    scales_rad: np.ndarray


def bind_joints(model: mujoco.MjModel, policy: Policy) -> JointBinding:
    """找出策略的每个关节和带着它的驱动器。找不到、不是一个关节一个驱动器，都拒绝。"""
    actuator_of = _single_joint_actuators(model)
    qpos, dofs, actuators = [], [], []
    for joint in policy.joints:
        joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint.name)
        if joint_id < 0:
            raise PolicyError(f"身体的模型里没有关节 {joint.name}")
        if model.jnt_type[joint_id] != mujoco.mjtJoint.mjJNT_HINGE:
            raise PolicyError(f"关节 {joint.name} 不是转动的关节")
        if joint_id not in actuator_of:
            raise PolicyError(f"关节 {joint.name} 没有单独带着它的位置驱动器（并联的要等 2.1 步的脊髓层换算）")
        qpos.append(model.jnt_qposadr[joint_id])
        dofs.append(model.jnt_dofadr[joint_id])
        actuators.append(actuator_of[joint_id])
    return JointBinding(
        qpos_addresses=np.array(qpos),
        dof_addresses=np.array(dofs),
        actuator_ids=np.array(actuators),
        defaults_rad=np.array([joint.default_position_rad for joint in policy.joints]),
        scales_rad=np.array([joint.action_scale_rad for joint in policy.joints]),
    )


def _single_joint_actuators(model: mujoco.MjModel) -> dict[int, int]:
    """关节 → 只带着它一个、传动比是 1 的位置驱动器。"""
    found: dict[int, int] = {}
    for actuator in range(model.nu):
        is_joint = model.actuator_trntype[actuator] == mujoco.mjtTrn.mjTRN_JOINT
        is_position = (
            model.actuator_gaintype[actuator] == mujoco.mjtGain.mjGAIN_FIXED
            and model.actuator_biastype[actuator] == mujoco.mjtBias.mjBIAS_AFFINE
        )
        if is_joint and is_position and model.actuator_gear[actuator, 0] == 1.0:
            found[int(model.actuator_trnid[actuator, 0])] = actuator
    return found


def apply_joint_gains(model: mujoco.MjModel, policy: Policy, binding: JointBinding) -> None:
    """把策略练的时候的软硬写进驱动器：力矩 = 刚度 x (目标 - 角度) - 阻尼 x 转速，最多出 torque_limit_nm。"""
    for joint, actuator in zip(policy.joints, binding.actuator_ids, strict=True):
        model.actuator_gainprm[actuator, :] = 0.0
        model.actuator_gainprm[actuator, 0] = joint.stiffness_nm_per_rad
        model.actuator_biasprm[actuator, :] = 0.0
        model.actuator_biasprm[actuator, 1] = -joint.stiffness_nm_per_rad
        model.actuator_biasprm[actuator, 2] = -joint.damping_nms_per_rad
        model.actuator_forcelimited[actuator] = 1
        model.actuator_forcerange[actuator] = (-joint.torque_limit_nm, joint.torque_limit_nm)
        model.actuator_ctrllimited[actuator] = 0


def steps_per_action(timestep_s: float, rate_hz: float) -> int:
    """策略每隔几步算一次。步长 x 整数不正好是策略的周期就拒绝（不然策略的时间就乱了）。"""
    ratio = 1.0 / (rate_hz * timestep_s)
    steps = round(ratio)
    if steps < 1 or abs(ratio - steps) > PERIOD_TOLERANCE * ratio:
        raise PolicyError(f"仿真的步长 {timestep_s:g} s 凑不成策略的周期（每秒 {rate_hz:g} 次）")
    return steps


def root_body(model: mujoco.MjModel) -> int:
    """骨盆：带着自由关节的那个身体。"""
    free = [joint for joint in range(model.njnt) if model.jnt_type[joint] == mujoco.mjtJoint.mjJNT_FREE]
    if len(free) != 1:
        raise PolicyError(f"身体的模型要正好一个自由关节（骨盆），现在有 {len(free)} 个")
    return int(model.jnt_bodyid[free[0]])


class PolicyRunner:
    """测试台每一步（mj_step 之前）调用 step：到了策略的时候就算一次，设好关节的目标。

    建的时候会把策略的软硬写进模型的驱动器（apply_joint_gains）。
    """

    def __init__(self, model: mujoco.MjModel, policy: Policy):
        self._model = model
        self._policy = policy
        self._binding = bind_joints(model, policy)
        apply_joint_gains(model, policy, self._binding)
        self._imu_site = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, policy.imu_site)
        if self._imu_site < 0:
            raise PolicyError(f"身体的模型里没有 IMU 的点 {policy.imu_site}")
        self._root = root_body(model)
        gravity = np.asarray(model.opt.gravity, dtype=float)
        if not np.any(gravity):
            raise PolicyError("模型里没有重力，算不了重力的方向")
        self._gravity_direction = gravity / np.linalg.norm(gravity)
        self._steps_per_action = steps_per_action(float(model.opt.timestep), policy.rate_hz)
        self._last_action = np.zeros(policy.action_size)
        self._step = 0

    @property
    def policy(self) -> Policy:
        return self._policy

    @property
    def steps_per_action(self) -> int:
        return self._steps_per_action

    @property
    def last_action(self) -> np.ndarray:
        return self._last_action.copy()

    def reset(self) -> None:
        """从头开始：上一次的动作清零，下一步就算一次。"""
        self._last_action = np.zeros(self._policy.action_size)
        self._step = 0

    def step(self, data: mujoco.MjData, command: Mapping[str, float]) -> None:
        """mj_step 之前调用。命令超出练过的范围就拒绝（PolicyError）。"""
        if self._step % self._steps_per_action == 0:
            command_vector = self._policy.command.vector(command)
            action = self._policy.act(self.observation(data, command_vector))
            self._last_action = action
            data.ctrl[self._binding.actuator_ids] = self._binding.defaults_rad + self._binding.scales_rad * action
        self._step += 1

    def observation(self, data: mujoco.MjData, command_vector: np.ndarray) -> np.ndarray:
        """按规约的顺序接成一行。先 mj_forward：mj_step 以后速度、姿态这些算出来的量还是上一步的。"""
        mujoco.mj_forward(self._model, data)
        parts = [
            self._term(observation.term, data, command_vector) * observation.scale
            for observation in self._policy.observations
        ]
        return np.concatenate(parts)

    def _term(self, term: ObservationTerm, data: mujoco.MjData, command_vector: np.ndarray) -> np.ndarray:
        if term in (ObservationTerm.BASE_LIN_VEL, ObservationTerm.BASE_ANG_VEL):
            velocity = np.zeros(SPATIAL_SIZE)
            mujoco.mj_objectVelocity(self._model, data, mujoco.mjtObj.mjOBJ_SITE, self._imu_site, velocity, 1)
            return velocity[3:] if term == ObservationTerm.BASE_LIN_VEL else velocity[:3]
        if term == ObservationTerm.PROJECTED_GRAVITY:
            rotation = data.xmat[self._root].reshape(3, 3)
            return rotation.T @ self._gravity_direction
        if term in JOINT_TERMS:
            return self._joint_term(term, data)
        return command_vector

    def _joint_term(self, term: ObservationTerm, data: mujoco.MjData) -> np.ndarray:
        if term == ObservationTerm.JOINT_POS:
            return data.qpos[self._binding.qpos_addresses] - self._binding.defaults_rad
        if term == ObservationTerm.JOINT_VEL:
            return data.qvel[self._binding.dof_addresses].copy()
        return self._last_action.copy()
