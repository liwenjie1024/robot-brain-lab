"""System 0 (운동 제어): 걷기 속도 명령을 받아 균형을 잡으며 걷도록 다리 관절에 힘을 준다.

미리 학습된 정책(Unitree G1, unitree_rl_gym)을 제어 주기(50Hz)마다 돌려 관절 목표 각도를 정하고,
물리 주기(500Hz)마다 PD 제어로 그 각도를 따라가는 힘을 낸다. 관측 값의 구성·순서·배율은 정책을 학습할 때와
같아야 한다 (upstream deploy/deploy_mujoco/deploy_mujoco.py). 하나라도 다르면 로봇이 바로 넘어진다.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
import torch
import yaml

# 정책이 배운 걸음 주기 s (upstream deploy_mujoco.py의 period와 같아야 한다)
GAIT_PERIOD_SECONDS = 0.8
# 정책 신경망이 작아 스레드를 여럿 쓰면 오히려 느려지고 물리 계산과 CPU를 다툰다.
POLICY_THREADS = 1


@dataclass(frozen=True)
class Velocity:
    """몸 기준 걷기 속도 (앞 m/s, 왼쪽 m/s, 왼쪽으로 도는 rad/s)"""

    forward: float
    sideways: float
    turn: float

    def as_array(self) -> np.ndarray:
        return np.array([self.forward, self.sideways, self.turn], dtype=np.float32)


STANDING_STILL = Velocity(0.0, 0.0, 0.0)


@dataclass(frozen=True)
class PolicyConfig:
    """정책과 함께 받은 설정 (upstream configs/g1.yaml)"""

    simulation_dt: float
    control_decimation: int
    kps: np.ndarray
    kds: np.ndarray
    default_angles: np.ndarray
    ang_vel_scale: float
    dof_pos_scale: float
    dof_vel_scale: float
    action_scale: float
    cmd_scale: np.ndarray
    num_actions: int
    num_obs: int

    @property
    def control_dt(self) -> float:
        return self.simulation_dt * self.control_decimation

    @classmethod
    def load(cls, path: Path) -> PolicyConfig:
        raw = yaml.safe_load(path.read_text("utf-8"))

        def floats(key: str) -> np.ndarray:
            return np.array(raw[key], dtype=np.float32)

        return cls(
            simulation_dt=float(raw["simulation_dt"]),
            control_decimation=int(raw["control_decimation"]),
            kps=floats("kps"),
            kds=floats("kds"),
            default_angles=floats("default_angles"),
            ang_vel_scale=float(raw["ang_vel_scale"]),
            dof_pos_scale=float(raw["dof_pos_scale"]),
            dof_vel_scale=float(raw["dof_vel_scale"]),
            action_scale=float(raw["action_scale"]),
            cmd_scale=floats("cmd_scale"),
            num_actions=int(raw["num_actions"]),
            num_obs=int(raw["num_obs"]),
        )


class Policy(Protocol):
    def __call__(self, observation: torch.Tensor) -> torch.Tensor: ...


def gravity_in_body(quaternion_wxyz: np.ndarray) -> np.ndarray:
    """몸통 기준으로 본 중력 방향 (똑바로 서 있으면 [0, 0, -1])"""
    qw, qx, qy, qz = quaternion_wxyz
    return np.array(
        [
            2 * (-qz * qx + qw * qy),
            -2 * (qz * qy + qw * qx),
            1 - 2 * (qw * qw + qz * qz),
        ],
        dtype=np.float32,
    )


@dataclass(frozen=True)
class BodySense:
    """정책에 넣을 몸의 감각 (실제 로봇이라면 IMU와 관절 엔코더가 주는 값)"""

    base_quaternion: np.ndarray
    base_angular_velocity: np.ndarray
    joint_positions: np.ndarray
    joint_velocities: np.ndarray


class WalkingController:
    """속도 명령 → 관절 목표 각도(정책) → 관절 힘(PD)."""

    def __init__(self, config: PolicyConfig, policy: Policy) -> None:
        self.config = config
        self._policy = policy
        self._last_action = np.zeros(config.num_actions, dtype=np.float32)
        self._targets = config.default_angles.copy()

    @classmethod
    def from_files(cls, config_path: Path, policy_path: Path) -> WalkingController:
        torch.set_num_threads(POLICY_THREADS)
        # upstream이 TorchScript로만 내보내 준다. torch.export로 바꿀 수 없어 사라질 때까지 이것으로 읽는다.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*torch.jit.load.*", category=FutureWarning)
            policy = torch.jit.load(str(policy_path))
        return cls(PolicyConfig.load(config_path), policy)

    def reset(self) -> None:
        self._last_action[:] = 0
        self._targets = self.config.default_angles.copy()
        # 순환 신경망(LSTM) 정책은 기억을 안에 들고 있어 처음 자세로 돌릴 때 함께 비워야 한다.
        reset_memory = getattr(self._policy, "reset_memory", None)
        if callable(reset_memory):
            reset_memory()

    def joint_torques(self, joint_positions: np.ndarray, joint_velocities: np.ndarray) -> np.ndarray:
        config = self.config
        return (self._targets - joint_positions) * config.kps - joint_velocities * config.kds

    def update_targets(self, command: Velocity, sense: BodySense, gait_time: float) -> None:
        observation = self.observation(command, sense, gait_time)
        with torch.inference_mode():
            action = self._policy(torch.from_numpy(observation).unsqueeze(0)).numpy().squeeze()
        self._last_action = action.astype(np.float32)
        self._targets = self._last_action * self.config.action_scale + self.config.default_angles

    def observation(self, command: Velocity, sense: BodySense, gait_time: float) -> np.ndarray:
        config = self.config
        phase = (gait_time % GAIT_PERIOD_SECONDS) / GAIT_PERIOD_SECONDS
        parts = [
            sense.base_angular_velocity * config.ang_vel_scale,
            gravity_in_body(sense.base_quaternion),
            command.as_array() * config.cmd_scale,
            (sense.joint_positions - config.default_angles) * config.dof_pos_scale,
            sense.joint_velocities * config.dof_vel_scale,
            self._last_action,
            np.array([np.sin(2 * np.pi * phase), np.cos(2 * np.pi * phase)]),
        ]
        observation = np.concatenate(parts).astype(np.float32)
        if observation.shape != (config.num_obs,):
            raise ValueError(f"관측 값 길이 {observation.shape[0]}가 정책이 배운 {config.num_obs}와 다릅니다")
        return observation
