"""System 0 (비행 제어): 비행 속도 명령을 받아 추진기 힘으로 따라가고, 기체를 똑바로 세운다.

두뇌는 "앞으로 20m/s, 위로 5m/s, 왼쪽으로 0.5rad/s 돌기"처럼 속도만 정한다. 이 층이 물리 주기(500Hz)마다
속도 차이 → 필요한 가속 → 필요한 힘(중력 포함)을 정하고 몸 기준의 위·앞뒤·옆 추진기에 나눈다.
자세는 몸의 위쪽 축을 세계 위로 맞추는 회전 힘과 도는 빠르기를 맞추는 힘으로 지킨다.
값은 기체의 실제 질량과 관성으로 나눠 정한다 (기체를 바꿔도 같은 느낌으로 날게).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import mujoco
import numpy as np

from .mecha import ROOT_BODY, THRUSTERS

GRAVITY = 9.81
VELOCITY_GAIN = 2.0
MAX_HORIZONTAL_ACCELERATION = 15.0
MAX_CLIMB_ACCELERATION = 12.0
MAX_DESCENT_ACCELERATION = 8.0
ATTITUDE_GAIN = 16.0
ATTITUDE_DAMPING = 7.2
YAW_RATE_GAIN = 4.0
MAX_ANGULAR_ACCELERATION = 6.0
# 추진기 힘 한도 = 위 가속이 필요한 힘보다 이만큼 더 (흔들릴 때도 버티게)
THRUST_HEADROOM = 1.2
UP_AXIS = np.array([0.0, 0.0, 1.0])


@dataclass(frozen=True)
class FlightCommand:
    """기수 방향 기준 속도: 앞 m/s, 왼쪽 m/s, 위 m/s, 왼쪽으로 도는 rad/s"""

    forward: float
    sideways: float
    up: float
    turn: float

    def is_hold(self) -> bool:
        return self.forward == 0 and self.sideways == 0 and self.up == 0 and self.turn == 0

    def as_dict(self) -> dict[str, float]:
        return {"forward": self.forward, "sideways": self.sideways, "up": self.up, "turn": self.turn}


HOLD = FlightCommand(0.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True)
class MassProperties:
    mass: float
    inertia: np.ndarray

    @classmethod
    def measure(cls, model: mujoco.MjModel) -> MassProperties:
        """기체 전체의 질량과 몸통 기준 회전 관성 (자유 관절의 회전 부분 질량 행렬)"""
        data = mujoco.MjData(model)
        mujoco.mj_forward(model, data)
        root = model.body(ROOT_BODY).id
        dof = model.jnt_dofadr[model.body_jntadr[root]]
        full = np.zeros((model.nv, model.nv))
        mujoco.mj_fullM(model, data, full)
        return cls(float(model.body_subtreemass[root]), np.diag(full[dof + 3 : dof + 6, dof + 3 : dof + 6]).copy())


def thruster_ranges(properties: MassProperties) -> dict[str, tuple[float, float]]:
    mass = properties.mass
    up = mass * (GRAVITY + MAX_CLIMB_ACCELERATION) * THRUST_HEADROOM
    horizontal = mass * MAX_HORIZONTAL_ACCELERATION * THRUST_HEADROOM
    torques = properties.inertia * MAX_ANGULAR_ACCELERATION * THRUST_HEADROOM
    return {
        "thrust_up": (0.0, up),
        "thrust_forward": (-horizontal, horizontal),
        "thrust_side": (-horizontal, horizontal),
        "torque_roll": (-torques[0], torques[0]),
        "torque_pitch": (-torques[1], torques[1]),
        "torque_yaw": (-torques[2], torques[2]),
    }


def heading_of(rotation: np.ndarray) -> float:
    """몸의 앞쪽 축을 바닥에 비춘 방향 (rad)"""
    return math.atan2(rotation[1, 0], rotation[0, 0])


class FlightController:
    def __init__(self, model: mujoco.MjModel, properties: MassProperties) -> None:
        self._properties = properties
        root = model.body(ROOT_BODY).id
        self._root = root
        self._dof = model.jnt_dofadr[model.body_jntadr[root]]
        self._actuators = {name: model.actuator(name).id for name in THRUSTERS}

    def apply(self, data: mujoco.MjData, command: FlightCommand, idle: bool) -> None:
        """idle이면(착지해 쉬거나 파괴됨) 추진기를 끈다."""
        if idle:
            for actuator in self._actuators.values():
                data.ctrl[actuator] = 0.0
            return
        rotation = data.xmat[self._root].reshape(3, 3)
        force_body = rotation.T @ self._required_force(data, command, heading_of(rotation))
        torque = self._attitude_torque(data, rotation, command.turn)
        values = {
            "thrust_up": force_body[2],
            "thrust_forward": force_body[0],
            "thrust_side": force_body[1],
            "torque_roll": torque[0],
            "torque_pitch": torque[1],
            "torque_yaw": torque[2],
        }
        for name, value in values.items():
            data.ctrl[self._actuators[name]] = value

    def _required_force(self, data: mujoco.MjData, command: FlightCommand, heading: float) -> np.ndarray:
        cos_h, sin_h = math.cos(heading), math.sin(heading)
        desired = np.array(
            [
                cos_h * command.forward - sin_h * command.sideways,
                sin_h * command.forward + cos_h * command.sideways,
                command.up,
            ]
        )
        velocity = data.qvel[self._dof : self._dof + 3]
        acceleration = VELOCITY_GAIN * (desired - velocity)
        horizontal = math.hypot(acceleration[0], acceleration[1])
        if horizontal > MAX_HORIZONTAL_ACCELERATION:
            acceleration[:2] *= MAX_HORIZONTAL_ACCELERATION / horizontal
        acceleration[2] = float(np.clip(acceleration[2], -MAX_DESCENT_ACCELERATION, MAX_CLIMB_ACCELERATION))
        return self._properties.mass * (acceleration + GRAVITY * UP_AXIS)

    def _attitude_torque(self, data: mujoco.MjData, rotation: np.ndarray, turn: float) -> np.ndarray:
        # 몸 기준으로 본 세계의 위쪽. 몸의 z축을 이쪽으로 돌리는 축이 기울기 오차다.
        world_up = rotation.T @ UP_AXIS
        tilt = np.cross(UP_AXIS, world_up)
        spin = data.qvel[self._dof + 3 : self._dof + 6]
        angular = np.empty(3)
        angular[:2] = ATTITUDE_GAIN * tilt[:2] - ATTITUDE_DAMPING * spin[:2]
        angular[2] = YAW_RATE_GAIN * (turn - spin[2])
        return self._properties.inertia * angular
