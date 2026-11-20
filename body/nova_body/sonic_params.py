"""SONIC（NVIDIA GEAR-SONIC 默认的那一版）在 G1 上用的数，照它部署的源码抄的（third_party/gr00t_wbc，提交 1e1ec4f5，
Apache-2.0）：policy_parameters.hpp（关节的顺序、默认姿势、软硬、动作的比例）、localmotion_kplanner.hpp（规划器）、
g1_deploy_onnx_ref.cpp（每秒 50 次、规划器每秒 10 次、什么时候重新规划）、gamepad.hpp（每种走法的速度）。

两种关节的顺序：MuJoCo 的（模型、规划器的输出、驱动器）和 IsaacLab 的（策略的观测和动作）。
MUJOCO_OF_ISAACLAB[i]：IsaacLab 的第 i 个是 MuJoCo 的第几个（源码里叫 mujoco_to_isaaclab）；
ISAACLAB_OF_MUJOCO[i]：MuJoCo 的第 i 个是 IsaacLab 的第几个（源码里叫 isaaclab_to_mujoco）。
"""

import math
from enum import IntEnum

JOINTS = (
    "left_hip_pitch_joint",
    "left_hip_roll_joint",
    "left_hip_yaw_joint",
    "left_knee_joint",
    "left_ankle_pitch_joint",
    "left_ankle_roll_joint",
    "right_hip_pitch_joint",
    "right_hip_roll_joint",
    "right_hip_yaw_joint",
    "right_knee_joint",
    "right_ankle_pitch_joint",
    "right_ankle_roll_joint",
    "waist_yaw_joint",
    "waist_roll_joint",
    "waist_pitch_joint",
    "left_shoulder_pitch_joint",
    "left_shoulder_roll_joint",
    "left_shoulder_yaw_joint",
    "left_elbow_joint",
    "left_wrist_roll_joint",
    "left_wrist_pitch_joint",
    "left_wrist_yaw_joint",
    "right_shoulder_pitch_joint",
    "right_shoulder_roll_joint",
    "right_shoulder_yaw_joint",
    "right_elbow_joint",
    "right_wrist_roll_joint",
    "right_wrist_pitch_joint",
    "right_wrist_yaw_joint",
)
JOINT_COUNT = len(JOINTS)
ISAACLAB_OF_MUJOCO = (
    0,
    3,
    6,
    9,
    13,
    17,
    1,
    4,
    7,
    10,
    14,
    18,
    2,
    5,
    8,
    11,
    15,
    19,
    21,
    23,
    25,
    27,
    12,
    16,
    20,
    22,
    24,
    26,
    28,
)
MUJOCO_OF_ISAACLAB = (
    0,
    6,
    12,
    1,
    7,
    13,
    2,
    8,
    14,
    3,
    9,
    15,
    22,
    4,
    10,
    16,
    23,
    5,
    11,
    17,
    24,
    18,
    25,
    19,
    26,
    20,
    27,
    21,
    28,
)
# 下半身 12 个关节在 IsaacLab 顺序里的下标（站着播完时"读回机器人"只看这几个）。
LOWER_BODY_ISAACLAB = (0, 1, 3, 4, 6, 7, 9, 10, 13, 14, 17, 18)

# 默认的姿势（MuJoCo 顺序，rad）：目标 = 默认 + 动作 x 比例。
DEFAULT_ANGLES = (
    -0.312, 0.0, 0.0, 0.669, -0.363, 0.0,
    -0.312, 0.0, 0.0, 0.669, -0.363, 0.0,
    0.0, 0.0, 0.0,
    0.2, 0.2, 0.0, 0.6, 0.0, 0.0, 0.0,
    0.2, -0.2, 0.0, 0.6, 0.0, 0.0, 0.0,
)  # fmt: skip

# 软硬按电机的转子惯量算：刚度 = 惯量 x (2π x 10 Hz)²，阻尼 = 2 x 2 x 惯量 x (2π x 10 Hz)；
# 动作的比例 = 0.25 x 力矩上限 / 刚度。踝、腰的左右和前后用两个 5020 的刚度和阻尼。
_NATURAL_FREQ = 10 * 2.0 * math.pi
_DAMPING_RATIO = 2.0
_ARMATURE = {"5020": 0.003609725, "7520_14": 0.010177520, "7520_22": 0.025101925, "4010": 0.00425}
_EFFORT_LIMIT = {"5020": 25.0, "7520_14": 88.0, "7520_22": 139.0, "4010": 5.0}
# 每个关节（MuJoCo 顺序）：哪种电机，软硬乘几。
_MOTORS = (
    ("7520_22", 1), ("7520_22", 1), ("7520_14", 1), ("7520_22", 1), ("5020", 2), ("5020", 2),
    ("7520_22", 1), ("7520_22", 1), ("7520_14", 1), ("7520_22", 1), ("5020", 2), ("5020", 2),
    ("7520_14", 1), ("5020", 2), ("5020", 2),
    ("5020", 1), ("5020", 1), ("5020", 1), ("5020", 1), ("5020", 1), ("4010", 1), ("4010", 1),
    ("5020", 1), ("5020", 1), ("5020", 1), ("5020", 1), ("5020", 1), ("4010", 1), ("4010", 1),
)  # fmt: skip


def _stiffness(motor: str) -> float:
    return _ARMATURE[motor] * _NATURAL_FREQ**2


KPS = tuple(times * _stiffness(motor) for motor, times in _MOTORS)
KDS = tuple(times * 2.0 * _DAMPING_RATIO * _ARMATURE[motor] * _NATURAL_FREQ for motor, times in _MOTORS)
ACTION_SCALES = tuple(0.25 * _EFFORT_LIMIT[motor] / _stiffness(motor) for motor, _ in _MOTORS)

# 官方的 MuJoCo 仿真（g1_29dof_with_hand.xml）里每个关节的动力学：转子惯量、阻尼、摩擦（腕的前后、左右小一些）。
JOINT_ARMATURE = 0.01
JOINT_DAMPING = 0.05
JOINT_FRICTION = 0.2
WRIST_FRICTION = 0.1
WRIST_JOINTS = frozenset(name for name in JOINTS if "wrist_pitch" in name or "wrist_yaw" in name)

CONTROL_HZ = 50.0
PLANNER_HZ = 10.0
PLANNER_OUTPUT_HZ = 30.0
# 规划时从现在往后几帧（50 Hz）起取上下文；上下文 4 帧（30 Hz）；混合新旧两段用 8 帧。
LOOK_AHEAD_FRAMES = 2
CONTEXT_FRAMES = 4
BLEND_FRAMES = 8
DEFAULT_HEIGHT_M = 0.788740
INITIAL_RANDOM_SEED = 1234
# 规划器的"每次最多预测几段"：前 6 个开着（源码里这样设）。
ALLOWED_PRED_TOKENS = (1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0)
# 编码器、解码器看的历史和未来：10 帧；未来的每隔 5 帧（0.1 秒）。
HISTORY_FRAMES = 10
FUTURE_FRAMES = 10
FUTURE_STEP = 5
TOKEN_SIZE = 64
# 站着播完时"读回机器人"的门槛（rad，下半身平均差）和每步拉多少。
ADAPT_TRIGGER_RAD = 0.10
ADAPT_STOP_RAD = 0.05
RECOVER_TRIGGER_RAD = 0.045
READAPT_SHARE = 0.02


class Mode(IntEnum):
    """规划器的走法（V2 一共 27 种，这里只用得到这几种）。"""

    IDLE = 0
    SLOW_WALK = 1
    WALK = 2
    RUN = 3


# 每种走法的速度（m/s，手柄的程序这样夹）；重新规划的间隔（秒）。
SPEED_RANGES = {Mode.SLOW_WALK: (0.2, 0.8), Mode.WALK: (0.8, 1.5), Mode.RUN: (1.5, 3.0)}
REPLAN_INTERVAL_S = {Mode.RUN: 0.1}
DEFAULT_REPLAN_INTERVAL_S = 1.0
STATIC_MODES = frozenset({Mode.IDLE})
