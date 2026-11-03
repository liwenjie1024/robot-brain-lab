"""System 0 (팔 제어): 겨눌 점을 받아 어깨 두 관절의 각을 정하고, 관절 힘으로 그 각을 지킨다.

팔은 아래로 늘어진 자세(0, 0)에서 시작한다. 들기 각 φ만큼 앞으로 들고 돌리기 각 ψ만큼 옆으로 돌리면
팔(=소총)의 방향은 몸통 기준 (sinφ·cosψ, sinφ·sinψ, -cosφ)다. 이것을 거꾸로 풀어 각을 정한다.
관절 힘은 PD에 중력·관성 힘(MuJoCo qfrc_bias)을 더해, 무거운 팔을 큰 이득 없이 버티게 한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import mujoco
import numpy as np

from .mecha import LEFT_ARM, RIGHT_ARM, ROOT_BODY, ArmJoints

POSITION_GAIN = 3.0e6
VELOCITY_GAIN = 6.0e5
# 팔이 거의 아래를 가리키면 돌리기 각이 정해지지 않는다. 그때는 지금 돌리기 각을 둔다.
MIN_PITCH_FOR_YAW = 0.05


@dataclass(frozen=True)
class Pose:
    yaw: float
    pitch: float


READY_POSES = {
    "right": Pose(math.radians(-10), math.radians(30)),
    "left": Pose(math.radians(10), math.radians(25)),
}


def angles_toward(direction: np.ndarray, current_yaw: float) -> Pose:
    """몸통 기준 방향으로 팔을 돌릴 각 (범위는 따로 자른다)"""
    unit = direction / np.linalg.norm(direction)
    pitch = math.acos(float(np.clip(-unit[2], -1.0, 1.0)))
    yaw = math.atan2(unit[1], unit[0]) if pitch > MIN_PITCH_FOR_YAW else current_yaw
    return Pose(yaw, pitch)


class Arm:
    def __init__(self, model: mujoco.MjModel, joints: ArmJoints) -> None:
        self.side = joints.side
        self._torso = model.body(ROOT_BODY).id
        self._shoulder = model.body(f"mecha_{joints.side}_shoulder").id
        ids = [model.joint(joints.yaw).id, model.joint(joints.pitch).id]
        self._qpos = model.jnt_qposadr[ids]
        self._dof = model.jnt_dofadr[ids]
        self._ranges = model.jnt_range[ids].copy()
        self._actuators = [model.actuator(f"{name}_motor").id for name in (joints.yaw, joints.pitch)]
        self._limit = model.actuator_ctrlrange[self._actuators].copy()
        self.target = READY_POSES[joints.side]

    def hold(self, pose: Pose) -> None:
        self.target = self._clamped(pose)

    def point_at(self, data: mujoco.MjData, world_point: np.ndarray) -> None:
        rotation = data.xmat[self._torso].reshape(3, 3)
        direction = rotation.T @ (world_point - data.xpos[self._shoulder])
        if np.linalg.norm(direction) == 0:
            return
        self.target = self._clamped(angles_toward(direction, self.target.yaw))

    def apply(self, data: mujoco.MjData) -> None:
        target = np.array([self.target.yaw, self.target.pitch])
        torque = (
            POSITION_GAIN * (target - data.qpos[self._qpos])
            - VELOCITY_GAIN * data.qvel[self._dof]
            + data.qfrc_bias[self._dof]
        )
        data.ctrl[self._actuators] = np.clip(torque, self._limit[:, 0], self._limit[:, 1])

    def relax(self, data: mujoco.MjData) -> None:
        data.ctrl[self._actuators] = 0.0

    def _clamped(self, pose: Pose) -> Pose:
        (yaw_low, yaw_high), (pitch_low, pitch_high) = self._ranges
        return Pose(float(np.clip(pose.yaw, yaw_low, yaw_high)), float(np.clip(pose.pitch, pitch_low, pitch_high)))


def build_arms(model: mujoco.MjModel) -> dict[str, Arm]:
    return {"right": Arm(model, RIGHT_ARM), "left": Arm(model, LEFT_ARM)}
