"""SONIC（NVIDIA GEAR-SONIC 默认的那一版）接到测试台上：运动规划器 → 编码器 → 解码器，
每秒 50 次给 29 个关节的目标和软硬。
照它部署的 C++（g1_deploy_onnx_ref.cpp）用 Python 重写了那一圈：怎么拼观测、怎么喂规划器、新旧两段怎么接、朝向怎么对齐。
考试的速度命令换成规划器的命令，照它手柄的程序：脸朝的方向按转的速度累加，走的方向 = 命令的方向 + 脸朝的方向，
速度决定走法（慢走、走、跑）。

身体用它部署代码里的 G1（g1_29dof.xml，不带手），加上官方仿真里关节的动力学（转子惯量、阻尼、摩擦），
力矩电机换成测试台要的位置控制（SONIC 的软硬、关节上写的力矩上限），骨盆上加 IMU 和两个脚底的点（状态估计要）。
"""

import functools
import itertools
import math
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import mujoco
import nova_rt
import numpy as np
import onnxruntime

from nova_body.bench import Stairs, add_floor, add_stairs, use_bench_settings
from nova_body.policy_runner import BodySense
from nova_body.sonic_motion import (
    Motion,
    blend,
    context_from_motion,
    heading_quat,
    heading_quat_inv,
    quat_conjugate,
    quat_mul,
    quat_rotate,
    rotation_6d,
)
from nova_body.sonic_params import (
    ACTION_SCALES,
    ADAPT_STOP_RAD,
    ADAPT_TRIGGER_RAD,
    CONTROL_HZ,
    DEFAULT_ANGLES,
    DEFAULT_REPLAN_INTERVAL_S,
    FUTURE_FRAMES,
    FUTURE_STEP,
    HISTORY_FRAMES,
    INITIAL_RANDOM_SEED,
    ISAACLAB_OF_MUJOCO,
    JOINT_ARMATURE,
    JOINT_COUNT,
    JOINT_DAMPING,
    JOINT_FRICTION,
    JOINTS,
    KDS,
    KPS,
    LOOK_AHEAD_FRAMES,
    LOWER_BODY_ISAACLAB,
    MUJOCO_OF_ISAACLAB,
    PLANNER_HZ,
    READAPT_SHARE,
    RECOVER_TRIGGER_RAD,
    REPLAN_INTERVAL_S,
    SPEED_RANGES,
    STATIC_MODES,
    WRIST_FRICTION,
    WRIST_JOINTS,
    Mode,
)
from nova_body.sonic_planner import IDLE_REQUEST, Planner, PlanRequest, initial_context
from nova_body.spine import JointCommand
from nova_body.third_party import THIRD_PARTY_DIR, find_manifests, require

NAME = "sonic-default"
BODY_NAME = "unitree_g1_sonic"
WEIGHTS = "gear_sonic"
DEPLOY = "gr00t_wbc"
BODY_XML = "gear_sonic_deploy/g1/g1_29dof.xml"
SOURCE_FLOOR = "floor"
PELVIS = "pelvis"
IMU_SITE = "imu_in_pelvis"
# 骨盆上的 IMU、脚底的点：位置照 mjlab 的 G1（同一个机器人）。
IMU_POS = (0.04525, 0.0, -0.08339)
FOOT_SITES = {"left_foot": "left_ankle_roll_link", "right_foot": "right_ankle_roll_link"}
FOOT_POS = (0.04, 0.0, -0.037)
ACCELEROMETER = "imu_lin_acc"
GYRO = "imu_ang_vel"
SPATIAL_SIZE = 6
DOWN = np.array([0.0, 0.0, -1.0])
# 速度小过这个就是站着（m/s）。
STILL_SPEED_M_S = 0.05
# 编码器的输入（1762）里每一项的长度，按 observation_config.yaml 的顺序；G1 模式只填 REQUIRED 的几项，别的留 0。
ENCODER_LAYOUT = (
    ("encoder_mode_4", 4),
    ("motion_joint_positions_10frame_step5", 290),
    ("motion_joint_velocities_10frame_step5", 290),
    ("motion_root_z_position_10frame_step5", 10),
    ("motion_root_z_position", 1),
    ("motion_anchor_orientation", 6),
    ("motion_anchor_orientation_10frame_step5", 60),
    ("motion_joint_positions_lowerbody_10frame_step5", 120),
    ("motion_joint_velocities_lowerbody_10frame_step5", 120),
    ("vr_3point_local_target", 9),
    ("vr_3point_local_orn_target", 12),
    ("smpl_joints_10frame_step1", 720),
    ("smpl_anchor_orientation_10frame_step1", 60),
    ("motion_joint_positions_wrists_10frame_step1", 60),
)
ENCODER_SIZE = sum(size for _, size in ENCODER_LAYOUT)
ENCODER_OFFSETS = {
    name: sum(size for _, size in ENCODER_LAYOUT[:index]) for index, (name, _) in enumerate(ENCODER_LAYOUT)
}


@dataclass(frozen=True)
class SonicFiles:
    encoder: Path
    decoder: Path
    planner: Path
    body_xml: Path


def sonic_files(directory: Path = THIRD_PARTY_DIR) -> SonicFiles:
    """核对过的 SONIC 的文件（不对就报错，告诉人怎么下载）。"""
    manifests = {manifest.name: manifest for manifest in find_manifests(directory)}
    weights, deploy = require(manifests[WEIGHTS], directory), require(manifests[DEPLOY], directory)
    return SonicFiles(
        encoder=weights / "model_encoder.onnx",
        decoder=weights / "model_decoder.onnx",
        planner=weights / "planner_sonic.onnx",
        body_xml=deploy / BODY_XML,
    )


def load_sonic_body(body_xml: Path, stairs: Stairs | None = None) -> mujoco.MjModel:
    """SONIC 部署代码里的 G1，放上测试台（见模块的说明）。"""
    spec = mujoco.MjSpec.from_file(str(body_xml))
    spec.delete(spec.geom(SOURCE_FLOOR))
    use_bench_settings(spec)
    add_floor(spec)
    if stairs is not None:
        add_stairs(spec, stairs)
    joints = {joint.name: joint for joint in spec.joints}
    for name in JOINTS:
        joint = joints[name]
        joint.armature = JOINT_ARMATURE
        # MuJoCo 3.17 的阻尼是三个数（线性的、后两个是非线性的项），只用第一个。
        joint.damping = [JOINT_DAMPING, 0.0, 0.0]
        joint.frictionloss = WRIST_FRICTION if name in WRIST_JOINTS else JOINT_FRICTION
    for actuator in spec.actuators:
        index = JOINTS.index(actuator.target)
        kp, kd = KPS[index], KDS[index]
        actuator.gaintype = mujoco.mjtGain.mjGAIN_FIXED
        actuator.gainprm = [kp] + [0.0] * 9
        actuator.biastype = mujoco.mjtBias.mjBIAS_AFFINE
        actuator.biasprm = [0.0, -kp, -kd] + [0.0] * 7
        actuator.forcelimited = mujoco.mjtLimited.mjLIMITED_TRUE
        actuator.forcerange = list(joints[actuator.target].actfrcrange)
        actuator.ctrllimited = mujoco.mjtLimited.mjLIMITED_FALSE
    spec.body(PELVIS).add_site(name=IMU_SITE, pos=list(IMU_POS))
    for site, body in FOOT_SITES.items():
        spec.body(body).add_site(name=site, pos=list(FOOT_POS))
    for name, sensor_type in (
        (ACCELEROMETER, mujoco.mjtSensor.mjSENS_ACCELEROMETER),
        (GYRO, mujoco.mjtSensor.mjSENS_GYRO),
    ):
        spec.add_sensor(name=name, type=sensor_type, objtype=mujoco.mjtObj.mjOBJ_SITE, objname=IMU_SITE)
    return spec.compile()


@dataclass(frozen=True)
class RobotState:
    """控制一步时读到的：骨盆的朝向（w, x, y, z）、角速度（骨盆的坐标里）、关节的角度和转速（MuJoCo 顺序，绝对的）。"""

    base_quat: np.ndarray
    base_ang_vel: np.ndarray
    joints: np.ndarray
    velocities: np.ndarray


def request_for(command: Mapping[str, float], facing_angle: float) -> PlanRequest:
    """考试的速度命令换成规划器的命令（照手柄的程序）：慢走 0.2~0.8 m/s、走 0.8~1.5、跑 1.5~3.0。"""
    speed = math.hypot(command["lin_vel_x"], command["lin_vel_y"])
    facing = (math.cos(facing_angle), math.sin(facing_angle), 0.0)
    if speed < STILL_SPEED_M_S:
        return PlanRequest(Mode.IDLE, -1.0, (0.0, 0.0, 0.0), facing)
    mode = next(mode for mode, (_, high) in SPEED_RANGES.items() if speed <= high or mode == Mode.RUN)
    low, high = SPEED_RANGES[mode]
    direction = math.atan2(command["lin_vel_y"], command["lin_vel_x"]) + facing_angle
    return PlanRequest(mode, min(max(speed, low), high), (math.cos(direction), math.sin(direction), 0.0), facing)


def needs_replan(request: PlanRequest, last: PlanRequest, time_to_replan: bool) -> bool:
    """什么时候重新规划（照 Planner()）：走法、脸朝的方向、高低变了；或者不是静止的走法时，速度、方向变了，到了间隔。"""
    if (
        request.mode != last.mode
        or request.facing_direction != last.facing_direction
        or request.height_m != last.height_m
    ):
        return True
    if request.mode in STATIC_MODES:
        return False
    changed = request.speed_m_s != last.speed_m_s or request.movement_direction != last.movement_direction
    return changed or (time_to_replan and request.speed_m_s != 0)


class SonicController:
    """测试台每一步（mj_step 之前）调用 step：每 20 毫秒算一次（规划器每 100 毫秒看一次要不要重新规划），
    回关节的命令。"""

    def __init__(self, model: mujoco.MjModel, spine: nova_rt.Spine, files: SonicFiles) -> None:
        self._model = model
        self._steps_per_tick = round(1.0 / (CONTROL_HZ * model.opt.timestep))
        self._ticks_per_plan = round(CONTROL_HZ / PLANNER_HZ)
        self._encoder = _session(files.encoder)
        self._decoder = _session(files.decoder)
        self._planner = Planner(files.planner, INITIAL_RANDOM_SEED)
        joint_ids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name) for name in JOINTS]
        self._qpos = np.array([model.jnt_qposadr[joint] for joint in joint_ids])
        self._qvel = np.array([model.jnt_dofadr[joint] for joint in joint_ids])
        self._root = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, PELVIS)
        self._imu = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, IMU_SITE)
        spine_names = list(spine.joint_names)
        if sorted(spine_names) != sorted(JOINTS):
            raise ValueError("脊髓层的关节和 SONIC 的 29 个关节不一样")
        self._to_spine = np.array([JOINTS.index(name) for name in spine_names])
        self._history: deque[np.ndarray] = deque(maxlen=HISTORY_FRAMES)
        self._last_action = np.zeros(JOINT_COUNT)
        self._motion: Motion | None = None
        self._pending: tuple[Motion, int] | None = None
        self._frame = 0
        self._heading: np.ndarray | None = None
        self._last_request = IDLE_REQUEST
        self._replan_s = 0.0
        self._facing_angle = 0.0
        self._mode = Mode.IDLE
        self._readapt: str | None = None
        self._readapt_targets: np.ndarray | None = None
        self._step = 0
        self._command = self._joint_command(np.array(DEFAULT_ANGLES))

    @property
    def motion(self) -> Motion | None:
        return self._motion

    def step(self, data: mujoco.MjData, command: Mapping[str, float], sense: BodySense | None = None) -> JointCommand:
        if self._step % self._steps_per_tick == 0:
            self._tick(data, command, sense, self._step // self._steps_per_tick)
        self._step += 1
        return self._command

    def _tick(self, data: mujoco.MjData, command: Mapping[str, float], sense: BodySense | None, tick: int) -> None:
        state = self._read(data, sense)
        self._facing_angle += command["ang_vel_z"] / CONTROL_HZ
        self._mode = request_for(command, self._facing_angle).mode
        if tick % self._ticks_per_plan == 0:
            self._plan(state, command)
        if self._motion is None:
            self._advance(state, step_frame=False)
        self._history.append(self._entry(state))
        token = self._run(self._encoder, self._encoder_observation(state))
        action = self._run(self._decoder, np.concatenate([token, *self._history_terms()]))
        if not np.isfinite(action).all():
            raise ValueError("SONIC 给出了不是数的动作")
        self._last_action = action
        targets = np.array(DEFAULT_ANGLES) + action[np.array(ISAACLAB_OF_MUJOCO)] * np.array(ACTION_SCALES)
        self._command = self._joint_command(targets)
        self._advance(state)

    def _read(self, data: mujoco.MjData, sense: BodySense | None) -> RobotState:
        if sense is not None and sense.base_rotation is not None:
            quat = np.zeros(4)
            mujoco.mju_mat2Quat(quat, np.asarray(sense.base_rotation).reshape(-1))
            angular = np.asarray(sense.base_ang_vel, dtype=float)
        else:
            quat = data.xquat[self._root].copy()
            velocity = np.zeros(SPATIAL_SIZE)
            mujoco.mj_objectVelocity(self._model, data, mujoco.mjtObj.mjOBJ_SITE, self._imu, velocity, 1)
            angular = velocity[:3]
        return RobotState(quat, angular, data.qpos[self._qpos].copy(), data.qvel[self._qvel].copy())

    def _plan(self, state: RobotState, command: Mapping[str, float]) -> None:
        if self._motion is None and self._pending is None:
            self._pending = (self._planner.plan(initial_context(state.joints), IDLE_REQUEST), 0)
            return
        if self._motion is None:
            return
        request = request_for(command, self._facing_angle)
        self._replan_s += 1.0 / PLANNER_HZ
        time_to_replan = self._replan_s >= REPLAN_INTERVAL_S.get(request.mode, DEFAULT_REPLAN_INTERVAL_S)
        if time_to_replan:
            self._replan_s = 0.0
        if not needs_replan(request, self._last_request, time_to_replan):
            return
        self._last_request = request
        gen_frame = self._frame + LOOK_AHEAD_FRAMES
        self._pending = (self._planner.plan(context_from_motion(self._motion, gen_frame), request), gen_frame)

    def _advance(self, state: RobotState, step_frame: bool = True) -> None:
        """换上新规划的一段（第一次直接用，以后和正在播的混合，帧号回到 0），再往前走一帧
        （照 CurrentFrameAdvancement）。
        step_frame 是 False 时只换不走（开头第一段要在算观测以前就用上）。"""
        if self._pending is not None:
            new, gen_frame = self._pending
            self._pending = None
            merged = new if self._motion is None else blend(self._motion, new, self._frame, gen_frame)
            if merged is not None:
                first = self._motion is None
                self._motion, self._frame = merged, 0
                self._readapt_targets = None
                if first:
                    self._heading = quat_mul(heading_quat(state.base_quat), heading_quat_inv(self._motion.quats[0]))
        if self._motion is None or not step_frame:
            return
        next_frame = self._frame + 1
        if next_frame >= self._motion.frames:
            next_frame = self._motion.frames - 1
            if self._mode == Mode.IDLE:
                self._readapt_idle(next_frame, state)
        self._frame = next_frame

    def _readapt_idle(self, frame: int, state: RobotState) -> None:
        """站着、参考动作播完了：下半身的目标和机器人差得多就往机器人拉，差得少就拉回原来的目标（每步 2%）。"""
        joints = self._motion.joints[frame]
        lower = np.array(LOWER_BODY_ISAACLAB)
        actual = state.joints[np.array(MUJOCO_OF_ISAACLAB)[lower]]
        if self._readapt_targets is None:
            self._readapt_targets, self._readapt = joints[lower].copy(), "idle"
        error = float(np.mean(np.abs(joints[lower] - actual)))
        if self._readapt == "idle":
            self._readapt = (
                "adapting" if error > ADAPT_TRIGGER_RAD else ("recovering" if error < RECOVER_TRIGGER_RAD else "idle")
            )
        elif self._readapt == "adapting" and error < ADAPT_STOP_RAD:
            self._readapt = "idle"
        elif self._readapt == "recovering" and error > ADAPT_TRIGGER_RAD:
            self._readapt = "adapting"
        if self._readapt == "adapting":
            joints[lower] = (1 - READAPT_SHARE) * joints[lower] + READAPT_SHARE * actual
        elif self._readapt == "recovering":
            joints[lower] = (1 - READAPT_SHARE) * joints[lower] + READAPT_SHARE * self._readapt_targets

    def _entry(self, state: RobotState) -> np.ndarray:
        """历史里的一帧：角速度、关节（IsaacLab 顺序，减默认）、转速、上一次的动作、重力的方向（骨盆的坐标里）。"""
        isaac = np.array(MUJOCO_OF_ISAACLAB)
        gravity = quat_rotate(quat_conjugate(state.base_quat), DOWN)
        joints = state.joints[isaac] - np.array(DEFAULT_ANGLES)[isaac]
        return np.concatenate([state.base_ang_vel, joints, state.velocities[isaac], self._last_action, gravity])

    def _history_terms(self) -> list[np.ndarray]:
        """10 帧的历史，旧的在前，不够的在前面补 0；分成 5 项（每项 10 帧接起来）。"""
        width = 3 + 3 * JOINT_COUNT + 3
        frames = [np.zeros(width)] * (HISTORY_FRAMES - len(self._history)) + list(self._history)
        stacked = np.array(frames)
        bounds = np.cumsum([0, 3, JOINT_COUNT, JOINT_COUNT, JOINT_COUNT, 3])
        return [stacked[:, start:end].reshape(-1) for start, end in itertools.pairwise(bounds)]

    def _encoder_observation(self, state: RobotState) -> np.ndarray:
        """编码器的输入：G1 模式（模式号 0）只填未来 10 帧（每隔 5 帧）的关节角度、转速和骨盆的朝向。"""
        observation = np.zeros(ENCODER_SIZE)
        frames = [self._motion.frame(self._frame + index * FUTURE_STEP) for index in range(FUTURE_FRAMES)]
        joints = self._motion.joints[frames].reshape(-1)
        velocities = self._motion.velocities[frames].reshape(-1)
        base_inverse = quat_conjugate(state.base_quat)
        anchors = [rotation_6d(quat_mul(base_inverse, quat_mul(self._heading, self._motion.quats[f]))) for f in frames]
        for name, values in (
            ("motion_joint_positions_10frame_step5", joints),
            ("motion_joint_velocities_10frame_step5", velocities),
            ("motion_anchor_orientation_10frame_step5", np.concatenate(anchors)),
        ):
            start = ENCODER_OFFSETS[name]
            observation[start : start + len(values)] = values
        return observation

    def _joint_command(self, targets_mujoco: np.ndarray) -> JointCommand:
        order = self._to_spine
        return JointCommand(
            position_rad=targets_mujoco[order],
            velocity_rad_s=np.zeros(JOINT_COUNT),
            stiffness_nm_per_rad=np.array(KPS)[order],
            damping_nms_per_rad=np.array(KDS)[order],
            torque_nm=np.zeros(JOINT_COUNT),
        )

    @staticmethod
    def _run(session: onnxruntime.InferenceSession, observation: np.ndarray) -> np.ndarray:
        (name,) = [item.name for item in session.get_inputs()]
        (output,) = session.run(None, {name: observation.astype(np.float32)[np.newaxis]})
        return np.asarray(output, dtype=float).reshape(-1)


@functools.cache
def _session(path: Path) -> onnxruntime.InferenceSession:
    """编码器、解码器一个进程里读一次，大家共用（会话本身不记状态）。"""
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    return onnxruntime.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])


@dataclass(frozen=True)
class SonicBrain:
    """测试台上的 SONIC：怎么建身体、默认的姿势、每一步的控制器（和练出来的策略同一个样子，PolicyBench 都能用）。"""

    third_party_dir: Path = THIRD_PARTY_DIR
    name: str = NAME
    body_name: str = BODY_NAME
    rate_hz: float = CONTROL_HZ

    def load_body(self, stairs: Stairs | None = None) -> mujoco.MjModel:
        return load_sonic_body(sonic_files(self.third_party_dir).body_xml, stairs)

    def default_positions(self) -> dict[str, float]:
        return dict(zip(JOINTS, DEFAULT_ANGLES, strict=True))

    def runner(self, model: mujoco.MjModel, spine: nova_rt.Spine) -> SonicController:
        return SonicController(model, spine, sonic_files(self.third_party_dir))

    def refusal(self, command: Mapping[str, float]) -> str | None:
        """比跑得最快的（3 m/s）还快的命令接不了（不剪）。太慢的照手柄的程序提到慢走的最慢，那是 SONIC 自己的走法。"""
        speed = math.hypot(command["lin_vel_x"], command["lin_vel_y"])
        fastest = SPEED_RANGES[Mode.RUN][1]
        if speed > fastest:
            return f"SONIC 最快跑 {fastest:g} m/s，命令要 {speed:g} m/s"
        return None
