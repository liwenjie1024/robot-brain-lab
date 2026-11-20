"""SONIC 的运动规划器（planner_sonic.onnx）：给它最近 4 帧的样子（上下文）、走法、速度、往哪走、脸朝哪，
它生成接下来的一段参考动作（30 Hz 的 MuJoCo qpos，最多 64 帧）。照 localmotion_kplanner(_onnx).hpp 喂。
"""

import functools
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime

from nova_body.sonic_motion import QPOS_SIZE, Motion, resample_50hz
from nova_body.sonic_params import ALLOWED_PRED_TOKENS, CONTEXT_FRAMES, DEFAULT_HEIGHT_M, JOINT_COUNT, Mode

ONNX_THREADS = 1
_DTYPES = {"tensor(float)": np.float32, "tensor(int64)": np.int64, "tensor(int32)": np.int32}
NO_HEIGHT = -1.0
# 换成 50 Hz 至少要两帧（算转速）。
MIN_FRAMES = 2
DEFAULT_SPEED = -1.0


@dataclass(frozen=True)
class PlanRequest:
    """规划器的命令：走法、速度（-1 是这种走法默认的）、往哪走、脸朝哪（都在参考动作的世界坐标里）、高低（-1 不管）。"""

    mode: Mode
    speed_m_s: float
    movement_direction: tuple[float, float, float]
    facing_direction: tuple[float, float, float]
    height_m: float = NO_HEIGHT


IDLE_REQUEST = PlanRequest(Mode.IDLE, DEFAULT_SPEED, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0))


def initial_context(joints_mujoco: np.ndarray) -> np.ndarray:
    """开始时的上下文：4 帧都在原点、朝向 0、站着的高度，关节是机器人现在的（MuJoCo 顺序）。"""
    context = np.zeros((CONTEXT_FRAMES, QPOS_SIZE))
    context[:, 2] = DEFAULT_HEIGHT_M
    context[:, 3] = 1.0
    context[:, 7:] = joints_mujoco
    return context


@functools.cache
def planner_session(onnx_path: Path) -> onnxruntime.InferenceSession:
    """规划器有 774 MB，一个进程里读一次，大家共用（会话本身不记状态）。"""
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = ONNX_THREADS
    options.inter_op_num_threads = ONNX_THREADS
    return onnxruntime.InferenceSession(str(onnx_path), sess_options=options, providers=["CPUExecutionProvider"])


class Planner:
    def __init__(self, onnx_path: Path, random_seed: int) -> None:
        self._session = planner_session(onnx_path)
        self._types = {item.name: _DTYPES[item.type] for item in self._session.get_inputs()}
        self._seed = random_seed

    def plan(self, context: np.ndarray, request: PlanRequest) -> Motion:
        """规划一段，换成 50 Hz 的参考动作。"""
        if context.shape != (CONTEXT_FRAMES, 7 + JOINT_COUNT):
            raise ValueError(f"上下文的形状要是 {(CONTEXT_FRAMES, 7 + JOINT_COUNT)}，现在是 {context.shape}")
        values = {
            "context_mujoco_qpos": context[np.newaxis],
            "target_vel": [request.speed_m_s],
            "mode": [int(request.mode)],
            "movement_direction": [request.movement_direction],
            "facing_direction": [request.facing_direction],
            "random_seed": [self._seed],
            "has_specific_target": [[0]],
            "specific_target_positions": np.zeros((1, 4, 3)),
            "specific_target_headings": np.zeros((1, 4)),
            "allowed_pred_num_tokens": [ALLOWED_PRED_TOKENS],
            "height": [request.height_m],
        }
        feed = {name: np.asarray(values[name], dtype=dtype) for name, dtype in self._types.items()}
        qpos, count = self._session.run(["mujoco_qpos", "num_pred_frames"], feed)
        frames = int(np.asarray(count).reshape(-1)[0])
        if not MIN_FRAMES <= frames <= qpos.shape[1]:
            raise ValueError(f"规划器给了 {frames} 帧，要在 {MIN_FRAMES} 到 {qpos.shape[1]} 之间")
        return resample_50hz(np.asarray(qpos[0, :frames], dtype=float))
