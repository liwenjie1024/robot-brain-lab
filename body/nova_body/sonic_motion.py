"""SONIC 的参考动作：规划器每次生成一段（30 Hz 的 MuJoCo qpos），换成 50 Hz，和正在播的那一段混合着接上。
照它部署的源码（localmotion_kplanner.hpp 的 ResampleGeneratedSequence50Hz、UpdateContextFromMotion，
g1_deploy_onnx_ref.cpp 的 CurrentFrameAdvancement）。四元数都是 (w, x, y, z)。
"""

import math
from dataclasses import dataclass

import numpy as np

from nova_body.sonic_params import (
    BLEND_FRAMES,
    CONTEXT_FRAMES,
    CONTROL_HZ,
    JOINT_COUNT,
    MUJOCO_OF_ISAACLAB,
    PLANNER_OUTPUT_HZ,
)

QPOS_SIZE = 7 + JOINT_COUNT
# 两个四元数快要一样时 slerp 改成线性的（照源码）。
SLERP_LINEAR_DOT = 0.9995
UNIT_EPSILON = 1e-9


def quat_unit(q: np.ndarray, eps: float = UNIT_EPSILON) -> np.ndarray:
    return q / max(float(np.linalg.norm(q)), eps)


def quat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array(
        [
            aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
        ]
    )


def quat_conjugate(q: np.ndarray) -> np.ndarray:
    return np.array([q[0], -q[1], -q[2], -q[3]])


def quat_matrix(q: np.ndarray) -> np.ndarray:
    w, x, y, z = quat_unit(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def quat_rotate(q: np.ndarray, v: np.ndarray) -> np.ndarray:
    return quat_matrix(q) @ v


def heading_quat(q: np.ndarray) -> np.ndarray:
    """只留偏航：源码的做法是把 x、y 两项丢掉再归一（身体歪着时是近似的）。"""
    return quat_unit(np.array([q[0], 0.0, 0.0, q[3]]))


def heading_quat_inv(q: np.ndarray) -> np.ndarray:
    return quat_conjugate(heading_quat(q))


def quat_slerp(q0: np.ndarray, q1: np.ndarray, t: float) -> np.ndarray:
    dot = float(np.dot(q0, q1))
    if dot < 0.0:
        q1, dot = -q1, -dot
    if dot > SLERP_LINEAR_DOT:
        return quat_unit(q0 + t * (q1 - q0))
    theta = math.acos(min(1.0, dot))
    sin_theta = math.sin(theta)
    return (math.sin((1 - t) * theta) * q0 + math.sin(t * theta) * q1) / sin_theta


def rotation_6d(q: np.ndarray) -> np.ndarray:
    """旋转矩阵的前两列，按行展开成 6 个数（照源码）。"""
    return quat_matrix(q)[:, :2].reshape(-1)


@dataclass
class Motion:
    """一段 50 Hz 的参考动作：根的位置、四元数，关节的角度和转速（IsaacLab 顺序，绝对角度）。"""

    positions: np.ndarray
    quats: np.ndarray
    joints: np.ndarray
    velocities: np.ndarray

    @property
    def frames(self) -> int:
        return len(self.joints)

    def frame(self, index: int) -> int:
        """夹在这一段里（到头了就是最后一帧）。"""
        return max(0, min(index, self.frames - 1))


def resample_50hz(qpos_30hz: np.ndarray) -> Motion:
    """规划器的输出（n 帧 30 Hz 的 qpos）换成 50 Hz：位置、关节线性插值，四元数 slerp；转速 = 相邻两帧的差 x 50。"""
    count_30 = len(qpos_30hz)
    count_50 = math.floor(count_30 / PLANNER_OUTPUT_HZ * CONTROL_HZ)
    positions, quats, joints = np.zeros((count_50, 3)), np.zeros((count_50, 4)), np.zeros((count_50, JOINT_COUNT))
    isaac_columns = 7 + np.array(MUJOCO_OF_ISAACLAB)
    for frame in range(count_50):
        f30 = frame / CONTROL_HZ * PLANNER_OUTPUT_HZ
        f0 = math.floor(f30)
        f1 = min(f0 + 1, count_30 - 1)
        w1 = f30 - f0
        a, b = qpos_30hz[f0], qpos_30hz[f1]
        positions[frame] = (1 - w1) * a[:3] + w1 * b[:3]
        quats[frame] = quat_slerp(a[3:7], b[3:7], w1)
        joints[frame] = (1 - w1) * a[isaac_columns] + w1 * b[isaac_columns]
    velocities = np.zeros_like(joints)
    velocities[:-1] = np.diff(joints, axis=0) * CONTROL_HZ
    velocities[-1] = velocities[-2] if count_50 > 1 else 0.0
    return Motion(positions, quats, joints, velocities)


def context_from_motion(motion: Motion, gen_frame: int) -> np.ndarray:
    """规划器的上下文：从 gen_frame（50 Hz）起，按 30 Hz 取 4 帧，换回 MuJoCo 的 qpos。"""
    context = np.zeros((CONTEXT_FRAMES, QPOS_SIZE))
    mujoco_columns = 7 + np.array(MUJOCO_OF_ISAACLAB)
    for index in range(CONTEXT_FRAMES):
        f50 = (gen_frame / CONTROL_HZ + index / PLANNER_OUTPUT_HZ) * CONTROL_HZ
        f0 = min(math.floor(f50), motion.frames - 1)
        f1 = min(f0 + 1, motion.frames - 1)
        w1 = f50 - f0
        context[index, 3:7] = quat_slerp(motion.quats[f0], motion.quats[f1], w1)
        context[index, :3] = (1 - w1) * motion.positions[f0] + w1 * motion.positions[f1]
        context[index, mujoco_columns] = (1 - w1) * motion.joints[f0] + w1 * motion.joints[f1]
    return context


def blend(old: Motion, new: Motion, current_frame: int, gen_frame: int) -> Motion | None:
    """新规划的一段接到正在播的这一段上：以 current_frame 为第 0 帧，从 gen_frame 那里用 8 帧从旧的换到新的。
    新的来得太晚（一帧都接不上）就是 None。"""
    length = gen_frame - current_frame + new.frames
    if length <= 0:
        return None
    blend_start = max(0, gen_frame - current_frame)
    frames = np.arange(length)
    old_index = np.clip(frames + current_frame, 0, old.frames - 1)
    new_index = np.clip(frames + current_frame - gen_frame, 0, new.frames - 1)
    w_new = np.clip((frames - blend_start) / BLEND_FRAMES, 0.0, 1.0)[:, None]
    quats = np.array(
        [
            quat_slerp(old.quats[o], new.quats[n], float(w))
            for o, n, w in zip(old_index, new_index, w_new[:, 0], strict=True)
        ]
    )
    return Motion(
        positions=(1 - w_new) * old.positions[old_index] + w_new * new.positions[new_index],
        quats=quats,
        joints=(1 - w_new) * old.joints[old_index] + w_new * new.joints[new_index],
        velocities=(1 - w_new) * old.velocities[old_index] + w_new * new.velocities[new_index],
    )
