"""SONIC 接到测试台上的测试：两种关节顺序、软硬和动作的比例照源码；参考动作 30 Hz 换成 50 Hz、取上下文、
新旧两段混合；四元数的小工具；考试的速度命令怎么换成规划器的命令、什么时候重新规划；编码器的输入每一项放在哪；
真的在测试台上站 1 秒（要先下载 SONIC 的文件）。"""

import math

import numpy as np
import pytest

from nova_body.policy_bench import STILL, PolicyBench
from nova_body.sonic_brain import ENCODER_OFFSETS, ENCODER_SIZE, SonicBrain, needs_replan, request_for
from nova_body.sonic_motion import (
    QPOS_SIZE,
    Motion,
    blend,
    context_from_motion,
    heading_quat,
    quat_conjugate,
    quat_mul,
    quat_slerp,
    resample_50hz,
    rotation_6d,
)
from nova_body.sonic_params import (
    ACTION_SCALES,
    BLEND_FRAMES,
    ISAACLAB_OF_MUJOCO,
    JOINT_COUNT,
    JOINTS,
    KPS,
    MUJOCO_OF_ISAACLAB,
    Mode,
)
from nova_body.sonic_planner import IDLE_REQUEST, PlanRequest

IDENTITY = np.array([1.0, 0.0, 0.0, 0.0])


def yaw(angle: float) -> np.ndarray:
    return np.array([math.cos(angle / 2), 0.0, 0.0, math.sin(angle / 2)])


def walking_qpos(frames: int, speed_m_s: float = 0.5) -> np.ndarray:
    """30 Hz 的 qpos：往 +x 匀速走，朝向 0；MuJoCo 的第 j 个关节是 j / 100。"""
    qpos = np.zeros((frames, QPOS_SIZE))
    qpos[:, 0] = speed_m_s * np.arange(frames) / 30.0
    qpos[:, 2] = 0.79
    qpos[:, 3] = 1.0
    qpos[:, 7:] = np.arange(JOINT_COUNT) / 100.0
    return qpos


def constant_motion(frames: int, joint_value: float, quat: np.ndarray = IDENTITY) -> Motion:
    return Motion(
        positions=np.zeros((frames, 3)),
        quats=np.tile(quat, (frames, 1)),
        joints=np.full((frames, JOINT_COUNT), joint_value),
        velocities=np.zeros((frames, JOINT_COUNT)),
    )


def test_the_two_joint_orders_undo_each_other():
    """MuJoCo 的顺序换成 IsaacLab 的，再换回来，回到原样；两张表都是 29 个关节的排列。"""
    assert sorted(ISAACLAB_OF_MUJOCO) == sorted(MUJOCO_OF_ISAACLAB) == list(range(JOINT_COUNT))
    for mujoco_index in range(JOINT_COUNT):
        assert MUJOCO_OF_ISAACLAB[ISAACLAB_OF_MUJOCO[mujoco_index]] == mujoco_index


def test_gains_and_action_scales_follow_the_motor_armature():
    """膝（7520_22）：刚度 = 0.025101925 x (2π x 10)² ≈ 99.1，动作的比例 = 0.25 x 139 / 刚度 ≈ 0.35；
    踝用两倍的 5020 的刚度。"""
    knee, ankle = JOINTS.index("left_knee_joint"), JOINTS.index("left_ankle_pitch_joint")
    assert KPS[knee] == pytest.approx(0.025101925 * (20 * math.pi) ** 2)
    assert ACTION_SCALES[knee] == pytest.approx(0.25 * 139.0 / KPS[knee])
    assert KPS[ankle] == pytest.approx(2 * 0.003609725 * (20 * math.pi) ** 2)


def test_planner_output_is_resampled_to_50hz_in_isaaclab_order():
    """30 Hz 的 30 帧（1 秒）换成 50 帧：位置线性插值（超出最后一帧就停在那里），转速是相邻两帧的差 x 50，
    关节按 IsaacLab 的顺序排。"""
    motion = resample_50hz(walking_qpos(30))
    assert motion.frames == 50
    # 最后一帧（0.98 秒）超过了 30 Hz 的最后一帧（29/30 秒），停在那一帧。
    np.testing.assert_allclose(motion.positions[:49, 0], 0.5 * np.arange(49) / 50.0, atol=1e-9)
    assert motion.positions[49, 0] == pytest.approx(0.5 * 29 / 30)
    expected = np.array(MUJOCO_OF_ISAACLAB) / 100.0
    np.testing.assert_allclose(motion.joints[10], expected)
    np.testing.assert_allclose(motion.velocities, 0.0, atol=1e-9)


def test_the_context_comes_back_as_mujoco_qpos_at_30hz():
    """从换好的 50 Hz 的那一段取上下文：4 帧、每帧 1/30 秒，就是原来的 30 Hz 的帧，关节换回 MuJoCo 的顺序。"""
    original = walking_qpos(30)
    context = context_from_motion(resample_50hz(original), gen_frame=0)
    np.testing.assert_allclose(context, original[:4], atol=1e-9)


def test_a_new_plan_is_blended_in_over_eight_frames():
    """新的一段从 gen_frame 那里起，8 帧里从旧的换到新的：之前全是旧的，之后全是新的；长度 = gen - 现在 + 新的帧数。"""
    old, new = constant_motion(40, 0.0), constant_motion(30, 1.0, yaw(math.pi / 2))
    merged = blend(old, new, current_frame=5, gen_frame=7)
    assert merged.frames == 7 - 5 + 30
    assert merged.joints[2, 0] == 0.0
    assert merged.joints[2 + BLEND_FRAMES // 2, 0] == pytest.approx(0.5)
    assert merged.joints[2 + BLEND_FRAMES, 0] == 1.0
    np.testing.assert_allclose(merged.quats[2 + BLEND_FRAMES // 2], yaw(math.pi / 4), atol=1e-9)


def test_a_plan_that_arrives_too_late_is_dropped():
    """新的一段到得太晚，一帧都接不上：不换。"""
    assert blend(constant_motion(40, 0.0), constant_motion(3, 1.0), current_frame=20, gen_frame=10) is None


def test_quaternion_helpers():
    """只留偏航：转过的偏航不变；旋转矩阵的前两列按行展开；乘上共轭是不转；半路的 slerp 是一半的角。"""
    np.testing.assert_allclose(heading_quat(yaw(0.7)), yaw(0.7), atol=1e-12)
    np.testing.assert_allclose(rotation_6d(IDENTITY), [1, 0, 0, 1, 0, 0], atol=1e-12)
    np.testing.assert_allclose(quat_mul(yaw(0.3), quat_conjugate(yaw(0.3))), IDENTITY, atol=1e-12)
    np.testing.assert_allclose(quat_slerp(IDENTITY, yaw(1.0), 0.5), yaw(0.5), atol=1e-9)


@pytest.mark.parametrize(
    ("command", "mode", "speed"),
    [
        (STILL, Mode.IDLE, -1.0),
        ({**STILL, "lin_vel_x": 0.1}, Mode.SLOW_WALK, 0.2),
        ({**STILL, "lin_vel_x": 0.5}, Mode.SLOW_WALK, 0.5),
        ({**STILL, "lin_vel_x": 1.1}, Mode.WALK, 1.1),
        ({**STILL, "lin_vel_x": 2.0}, Mode.RUN, 2.0),
    ],
    ids=["站着", "很慢（夹到 0.2）", "慢走", "走", "跑"],
)
def test_speed_picks_the_way_of_walking(command, mode, speed):
    """速度决定走法（照手柄的程序：慢走 0.2~0.8、走 0.8~1.5、跑 1.5~3.0 m/s），速度夹在那种走法的范围里。"""
    request = request_for(command, facing_angle=0.0)
    assert (request.mode, request.speed_m_s) == (mode, pytest.approx(speed))


def test_directions_are_turned_by_the_facing_angle():
    """往左横着走、已经往左转了 90°：脸朝 +y，走的方向是 -x（命令的方向 + 脸朝的方向）。"""
    request = request_for({**STILL, "lin_vel_y": 0.5}, facing_angle=math.pi / 2)
    np.testing.assert_allclose(request.facing_direction, (0.0, 1.0, 0.0), atol=1e-12)
    np.testing.assert_allclose(request.movement_direction, (-1.0, 0.0, 0.0), atol=1e-12)


def test_when_to_replan():
    """走法、脸朝的方向变了就规划；站着的时候到了间隔也不规划；走着的时候速度变了、到了间隔就规划。"""
    walking = PlanRequest(Mode.WALK, 1.0, (1.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    assert needs_replan(walking, IDLE_REQUEST, time_to_replan=False)
    assert needs_replan(PlanRequest(Mode.IDLE, -1.0, (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)), IDLE_REQUEST, False)
    assert not needs_replan(IDLE_REQUEST, IDLE_REQUEST, time_to_replan=True)
    assert needs_replan(PlanRequest(Mode.WALK, 1.2, (1.0, 0.0, 0.0), (1.0, 0.0, 0.0)), walking, False)
    assert not needs_replan(walking, walking, time_to_replan=False)
    assert needs_replan(walking, walking, time_to_replan=True)


@pytest.mark.parametrize(
    ("command", "refused"),
    [
        ({**STILL, "lin_vel_x": 2.0}, False),
        ({**STILL, "lin_vel_x": 3.0}, False),
        ({**STILL, "lin_vel_x": 2.5, "lin_vel_y": 2.0}, True),
        ({**STILL, "lin_vel_x": -3.5}, True),
    ],
    ids=["跑", "正好是最快", "斜着比最快还快", "往后比最快还快"],
)
def test_sonic_refuses_speeds_beyond_running(command, refused):
    """SONIC 最快跑 3 m/s：再快的命令接不了（不剪），说为什么；3 m/s 以内的接得了。"""
    reason = SonicBrain().refusal(command)
    assert (reason is not None) == refused
    if refused:
        assert "最快跑 3 m/s" in reason


def test_the_encoder_input_is_laid_out_like_the_observation_config():
    """编码器的输入一共 1762 个数；G1 模式要的几项在照设置文件排出来的位置上。"""
    assert ENCODER_SIZE == 1762
    assert ENCODER_OFFSETS["motion_joint_positions_10frame_step5"] == 4
    assert ENCODER_OFFSETS["motion_joint_velocities_10frame_step5"] == 294
    assert ENCODER_OFFSETS["motion_anchor_orientation_10frame_step5"] == 601


def test_sonic_stands_on_the_bench():
    """真的在测试台上（G1、脊髓层、驱动器那一层）：SONIC 站 1 秒不倒，有了参考动作，骨盆几乎不歪，
    身上除了脚没有着地的地方。"""
    bench = PolicyBench(SonicBrain(), sensed=False)
    for _ in range(1000):
        bench.step(STILL)
    assert not bench.fallen()
    assert bench.runner.motion is not None
    assert bench.tilt_deg() < 5.0
    assert bench.body_impact_n() == 0.0, "站着只有脚着地"
