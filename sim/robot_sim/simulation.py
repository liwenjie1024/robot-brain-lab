"""시험장(바닥 + 시험용 몸)을 만들고 제어 주기 단위로 물리를 진행한다."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import mujoco
import numpy as np

from .locomotion import STANDING_STILL, BodySense, Velocity, WalkingController, gravity_in_body

ROBOT_ROOT_BODY = "pelvis"
FLOOR_RGBA = [0.22, 0.25, 0.3, 1.0]
FLOOR_HALF_SIZE_M = 20.0
FLOOR_GRID_SPACING_M = 0.05
# 서 있을 때 골반 높이는 약 0.78m. 이보다 많이 낮거나 많이 기울면 넘어진 것으로 본다.
FALLEN_PELVIS_HEIGHT_M = 0.45
FALLEN_TILT_DEGREES = 60.0
FREE_JOINT_POSITION_SIZE = 7


def build_arena(robot_xml: Path) -> mujoco.MjModel:
    """시험용 몸 모델에 바닥을 더한다. 메시 경로가 로봇 파일 기준이라 로봇 파일을 먼저 읽고 덧붙인다."""
    spec = mujoco.MjSpec.from_file(str(robot_xml))
    spec.worldbody.add_geom(
        name="floor",
        type=mujoco.mjtGeom.mjGEOM_PLANE,
        size=[FLOOR_HALF_SIZE_M, FLOOR_HALF_SIZE_M, FLOOR_GRID_SPACING_M],
        rgba=FLOOR_RGBA,
    )
    return spec.compile()


@dataclass(frozen=True)
class RobotStatus:
    position: tuple[float, float, float]
    yaw: float
    velocity: Velocity
    command: Velocity
    fallen: bool
    pushing: bool

    def as_dict(self) -> dict:
        return {
            "position": list(self.position),
            "yaw": self.yaw,
            "velocity": _velocity_dict(self.velocity),
            "command": _velocity_dict(self.command),
            "posture": "fallen" if self.fallen else "standing",
            "pushing": self.pushing,
        }


def _velocity_dict(velocity: Velocity) -> dict[str, float]:
    return {"forward": velocity.forward, "sideways": velocity.sideways, "turn": velocity.turn}


def yaw_of(quaternion_wxyz: np.ndarray) -> float:
    w, x, y, z = quaternion_wxyz
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


class Simulation:
    """한 번의 제어 주기(step_control_tick) = 물리 여러 번 + 걷기 정책 한 번. 한 스레드에서만 부른다."""

    def __init__(self, model: mujoco.MjModel, controller: WalkingController) -> None:
        self.model = model
        self.data = mujoco.MjData(model)
        self.controller = controller
        model.opt.timestep = controller.config.simulation_dt
        self._pelvis = model.body(ROBOT_ROOT_BODY).id
        self._free_qpos = model.jnt_qposadr[model.body_jntadr[self._pelvis]]
        self._free_dof = model.jnt_dofadr[model.body_jntadr[self._pelvis]]
        # 액추에이터 순서가 정책이 배운 관절 순서다 (모델 파일의 motor 순서).
        joints = model.actuator_trnid[:, 0]
        self._joint_qpos = model.jnt_qposadr[joints]
        self._joint_dof = model.jnt_dofadr[joints]
        self._min_upright = math.cos(math.radians(FALLEN_TILT_DEGREES))
        self._command = STANDING_STILL
        self._push_until = 0.0
        self.reset()

    @property
    def sim_time(self) -> float:
        return float(self.data.time)

    @property
    def pelvis_body(self) -> int:
        return self._pelvis

    def reset(self) -> None:
        mujoco.mj_resetData(self.model, self.data)
        self.controller.reset()
        self._command = STANDING_STILL
        self._push_until = 0.0
        mujoco.mj_forward(self.model, self.data)

    def set_command(self, velocity: Velocity) -> None:
        self._command = velocity

    def push(self, force: tuple[float, float, float], duration_s: float) -> None:
        self.data.xfrc_applied[self._pelvis, :3] = force
        self._push_until = self.sim_time + duration_s

    def step_control_tick(self) -> None:
        data = self.data
        for _ in range(self.controller.config.control_decimation):
            if self._push_until and self.sim_time >= self._push_until:
                data.xfrc_applied[self._pelvis, :] = 0
                self._push_until = 0.0
            data.ctrl[:] = self.controller.joint_torques(data.qpos[self._joint_qpos], data.qvel[self._joint_dof])
            mujoco.mj_step(self.model, data)
        self.controller.update_targets(self._command, self._sense(), self.sim_time)

    def _sense(self) -> BodySense:
        data = self.data
        return BodySense(
            base_quaternion=data.qpos[self._free_qpos + 3 : self._free_qpos + FREE_JOINT_POSITION_SIZE].copy(),
            base_angular_velocity=data.qvel[self._free_dof + 3 : self._free_dof + 6].astype(np.float32),
            joint_positions=data.qpos[self._joint_qpos].astype(np.float32),
            joint_velocities=data.qvel[self._joint_dof].astype(np.float32),
        )

    def status(self) -> RobotStatus:
        data = self.data
        quaternion = data.xquat[self._pelvis]
        yaw = yaw_of(quaternion)
        # 자유 관절의 속도: 앞 3개는 세계 좌표 이동 속도, 뒤 3개는 몸통 좌표 회전 속도
        world_linear = data.qvel[self._free_dof : self._free_dof + 3]
        world_angular = np.zeros(3)
        mujoco.mju_rotVecQuat(world_angular, data.qvel[self._free_dof + 3 : self._free_dof + 6], quaternion)
        cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
        velocity = Velocity(
            forward=float(cos_yaw * world_linear[0] + sin_yaw * world_linear[1]),
            sideways=float(-sin_yaw * world_linear[0] + cos_yaw * world_linear[1]),
            turn=float(world_angular[2]),
        )
        position = data.xpos[self._pelvis]
        return RobotStatus(
            position=(float(position[0]), float(position[1]), float(position[2])),
            yaw=yaw,
            velocity=velocity,
            command=self._command,
            fallen=self._is_fallen(),
            pushing=self._push_until > 0,
        )

    def _is_fallen(self) -> bool:
        uprightness = -gravity_in_body(self.data.xquat[self._pelvis])[2]
        return self.data.xpos[self._pelvis][2] < FALLEN_PELVIS_HEIGHT_M or uprightness < self._min_upright

    def body_poses(self, bodies: np.ndarray) -> np.ndarray:
        """bodies마다 [x, y, z, qw, qx, qy, qz]"""
        return np.hstack([self.data.xpos[bodies], self.data.xquat[bodies]])
