"""把一个策略（小脑层）接到测试台上的身体：按策略的周期给它观测，把它的动作变成每个关节的目标和软硬。

策略不直接碰驱动器（2.1 步起）：它给的关节命令（JointCommand）交给脊髓层，脊髓层每 1 毫秒换成每个驱动器的命令
（并联的一对按和、差换算），中间守住硬限制。策略不管的关节（比如 Nova 的手指）照测试台给的命令（base）顶着。
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace

import mujoco
import nova_rt
import numpy as np

from nova_body.policy import JOINT_TERMS, ObservationTerm, Policy, PolicyError
from nova_body.spine import JointCommand

# 步长 x 整数要正好是策略的周期，差这么多以内算正好（浮点数的误差）。
PERIOD_TOLERANCE = 1e-6
SPATIAL_SIZE = 6
# 身体自己感觉得到的那几项观测，在 BodySense 里叫什么。
SENSED_TERMS = {
    ObservationTerm.BASE_LIN_VEL: "base_lin_vel",
    ObservationTerm.BASE_ANG_VEL: "base_ang_vel",
    ObservationTerm.PROJECTED_GRAVITY: "projected_gravity",
}


@dataclass(frozen=True)
class BodySense:
    """身体自己感觉到的（IMU 和状态估计给的），代替仿真里的真数给策略看。

    base_lin_vel、base_ang_vel 在 IMU 的坐标里（m/s、rad/s），projected_gravity 在骨盆的坐标里（单位向量）。
    """

    base_lin_vel: np.ndarray
    base_ang_vel: np.ndarray
    projected_gravity: np.ndarray


@dataclass(frozen=True)
class JointBinding:
    """策略的关节在模型和脊髓层里的位置：角度、转速在 qpos、qvel 的第几个，是脊髓层的第几个关节。"""

    qpos_addresses: np.ndarray
    dof_addresses: np.ndarray
    spine_indices: np.ndarray
    defaults_rad: np.ndarray
    scales_rad: np.ndarray


def bind_joints(model: mujoco.MjModel, policy: Policy, spine: nova_rt.Spine) -> JointBinding:
    """找出策略的每个关节在模型、脊髓层里的位置。模型里没有、不是转动的关节、没有驱动器带着，都拒绝。"""
    spine_index = {name: index for index, name in enumerate(spine.joint_names)}
    qpos, dofs, indices = [], [], []
    for joint in policy.joints:
        joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint.name)
        if joint_id < 0:
            raise PolicyError(f"身体的模型里没有关节 {joint.name}")
        if model.jnt_type[joint_id] != mujoco.mjtJoint.mjJNT_HINGE:
            raise PolicyError(f"关节 {joint.name} 不是转动的关节")
        if joint.name not in spine_index:
            raise PolicyError(f"关节 {joint.name} 没有驱动器带着（脊髓层管不了它）")
        qpos.append(model.jnt_qposadr[joint_id])
        dofs.append(model.jnt_dofadr[joint_id])
        indices.append(spine_index[joint.name])
    return JointBinding(
        qpos_addresses=np.array(qpos),
        dof_addresses=np.array(dofs),
        spine_indices=np.array(indices),
        defaults_rad=np.array([joint.default_position_rad for joint in policy.joints]),
        scales_rad=np.array([joint.action_scale_rad for joint in policy.joints]),
    )


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


def policy_command(policy: Policy, binding: JointBinding, base: JointCommand | None, joint_count: int) -> JointCommand:
    """策略还没算的时候的关节命令：策略的关节在默认的姿势，软硬照规约；别的关节照 base。"""
    if base is None:
        if len(binding.spine_indices) != joint_count:
            raise PolicyError("策略没有管全部的关节，别的关节要测试台给命令（base）")
        zeros = np.zeros(joint_count)
        base = JointCommand(zeros, zeros, zeros, zeros, zeros)
    indices = binding.spine_indices
    command = JointCommand(*(np.array(values, dtype=float) for values in _fields(base)))
    command.position_rad[indices] = binding.defaults_rad
    command.velocity_rad_s[indices] = 0.0
    command.stiffness_nm_per_rad[indices] = [joint.stiffness_nm_per_rad for joint in policy.joints]
    command.damping_nms_per_rad[indices] = [joint.damping_nms_per_rad for joint in policy.joints]
    command.torque_nm[indices] = 0.0
    return command


def _fields(command: JointCommand) -> tuple[np.ndarray, ...]:
    return (
        command.position_rad,
        command.velocity_rad_s,
        command.stiffness_nm_per_rad,
        command.damping_nms_per_rad,
        command.torque_nm,
    )


class PolicyRunner:
    """测试台每一步（mj_step 之前）调用 step：到了策略的时候就算一次，回这一步的关节命令（给脊髓层）。"""

    def __init__(self, model: mujoco.MjModel, policy: Policy, spine: nova_rt.Spine, base: JointCommand | None = None):
        self._model = model
        self._policy = policy
        self._binding = bind_joints(model, policy, spine)
        self._resting = policy_command(policy, self._binding, base, spine.joint_count)
        self._command = self._resting
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
        """从头开始：上一次的动作清零，关节回到默认的姿势，下一步就算一次。"""
        self._last_action = np.zeros(self._policy.action_size)
        self._command = self._resting
        self._step = 0

    def step(self, data: mujoco.MjData, command: Mapping[str, float], sense: BodySense | None = None) -> JointCommand:
        """mj_step 之前调用，回这一步的关节命令。sense 给了就用身体自己感觉到的速度、角速度、重力方向，
        不给就用仿真里的真数。命令超出练过的范围、策略给出不是数的动作，都拒绝（PolicyError）。"""
        if self._step % self._steps_per_action == 0:
            command_vector = self._policy.command.vector(command)
            action = self._policy.act(self.observation(data, command_vector, sense))
            if not np.isfinite(action).all():
                raise PolicyError("策略给出了不是数的动作（NaN 或无穷大）")
            self._last_action = action
            position = self._command.position_rad.copy()
            position[self._binding.spine_indices] = self._binding.defaults_rad + self._binding.scales_rad * action
            self._command = replace(self._command, position_rad=position)
        self._step += 1
        return self._command

    def observation(
        self, data: mujoco.MjData, command_vector: np.ndarray, sense: BodySense | None = None
    ) -> np.ndarray:
        """按规约的顺序接成一行。先 mj_forward：mj_step 以后速度、姿态这些算出来的量还是上一步的。"""
        mujoco.mj_forward(self._model, data)
        parts = [
            self._term(observation.term, data, command_vector, sense) * observation.scale
            for observation in self._policy.observations
        ]
        return np.concatenate(parts)

    def _term(
        self, term: ObservationTerm, data: mujoco.MjData, command_vector: np.ndarray, sense: BodySense | None
    ) -> np.ndarray:
        if sense is not None and term in SENSED_TERMS:
            return np.asarray(getattr(sense, SENSED_TERMS[term]), dtype=float)
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
