import math

import mujoco
import numpy as np
import pytest

from nova_body.body import Region, Side
from nova_body.ik import HARD, SOFT
from nova_body.motions import (
    BOX_FRONT_OF_TOES_M,
    BOX_HALF_WIDTH_M,
    BOX_REACH_S,
    DT,
    HOLD_S,
    LEAN_MARGIN_M,
    PUSH_UP_DEPTH_M,
    SQUAT_CENTER_BACK_M,
    SQUAT_CENTER_RATIO,
    SQUAT_DOWN_S,
    STAIR_RISER_M,
    SWING_HOLD_SHARE,
    Level,
    MotionBuilder,
    Track,
    _foot_turn_weight,
    _quintic,
)
from nova_body.strength import self_contacts

UP = 2


@pytest.fixture(scope="module")
def builders(nova, g1) -> dict[str, MotionBuilder]:
    """两个身体的动作。生成一次，这个文件里的测试共用。"""
    return {"Nova": MotionBuilder(nova.body), "G1": MotionBuilder(g1)}


@pytest.fixture(params=["Nova", "G1"])
def builder(request, builders) -> MotionBuilder:
    """每个身体各跑一遍。"""
    return builders[request.param]


def center_of(builder: MotionBuilder, qpos: np.ndarray) -> np.ndarray:
    data = mujoco.MjData(builder.model)
    data.qpos[:] = qpos
    mujoco.mj_kinematics(builder.model, data)
    mujoco.mj_comPos(builder.model, data)
    return data.subtree_com[builder.model.body(builder.anatomy.root).id].copy()


def angles(builder: MotionBuilder, qpos: np.ndarray, region: Region) -> np.ndarray:
    model = builder.model
    return np.array(
        [qpos[model.joint(joint.name).qposadr[0]] for joint in builder.body.joints if joint.region is region]
    )


def frame_at(motion, seconds: float):
    return motion.frames[round(seconds / DT)]


# 轨迹 ------------------------------------------------------------------------------------------------


def test_track_goes_smoothly_between_the_given_moments():
    """给几个时刻的值：中间平滑地变（正中间是一半），前面、后面停在两头的值。"""
    track = Track([(1.0, [0.0]), (3.0, [2.0])])
    assert track(0.0) == pytest.approx([0.0])
    assert track(2.0) == pytest.approx([1.0])
    assert track(5.0) == pytest.approx([2.0])
    assert track.end == 3.0


def test_track_needs_moments_in_order():
    """没有时刻、或者时刻不是从早到晚：拒绝。"""
    with pytest.raises(ValueError, match="至少要一个时刻"):
        Track([])
    with pytest.raises(ValueError, match="从早到晚"):
        Track([(2.0, 0.0), (1.0, 1.0)])


# 原地的动作 ------------------------------------------------------------------------------------------


def test_lean_moves_the_weight_to_the_toes_and_back(builder):
    """前倾：重心挪到离脚尖 3 cm 的地方，脚不动；整个动作做得出来。"""
    motion = builder.lean("lean", "倾", "")
    assert motion.feasible
    toes = max(sole[0] for sole in builder.soles.values()) + builder.body.foot_length_m / 2
    forward = center_of(builder, frame_at(motion, 1.5).qpos)
    assert forward[0] == pytest.approx(toes - LEAN_MARGIN_M, abs=2e-3)
    assert center_of(builder, motion.frames[-1].qpos)[0] == pytest.approx(builder.center[0], abs=2e-3)


def test_squat_goes_down_to_half_height_leaning_forward_with_the_arms_still(builder):
    """蹲到底：重心降到站着时的一半、往后 3 cm，上身往前倾；只用腿的动作，手臂一点不动；身体不插到一起；最后站回来。"""
    motion = builder.squat("squat", "蹲", "")
    assert motion.feasible
    bottom = frame_at(motion, HOLD_S + SQUAT_DOWN_S).qpos
    assert center_of(builder, bottom)[UP] == pytest.approx(SQUAT_CENTER_RATIO * builder.center[UP], abs=0.01)
    assert center_of(builder, bottom)[0] == pytest.approx(builder.center[0] - SQUAT_CENTER_BACK_M, abs=0.01)
    assert self_contacts(builder.body, [frame.qpos for frame in motion.frames]) == {}
    trunk = mujoco.MjData(builder.model)
    trunk.qpos[:] = bottom
    mujoco.mj_kinematics(builder.model, trunk)
    forward = trunk.xmat[builder.model.body(builder.anatomy.trunk).id].reshape(3, 3)[:, 0]
    assert forward[UP] < -math.sin(math.radians(20))
    for frame in motion.frames:
        assert angles(builder, frame.qpos, Region.ARM) == pytest.approx(angles(builder, builder.stand, Region.ARM))
    assert center_of(builder, motion.frames[-1].qpos) == pytest.approx(builder.center, abs=3e-3)


def test_jump_ends_moving_at_takeoff(builder):
    """跳：是运动员级的（只拿来比），停在脚离地的那一刻，那时还在往上动。"""
    motion = builder.jump("jump", "跳", "")
    assert motion.level is Level.REFERENCE
    assert not motion.ends_at_rest
    last, before = (center_of(builder, frame.qpos) for frame in (motion.frames[-1], motion.frames[-2]))
    assert (last[UP] - before[UP]) / DT > 1.0


# 走路 ------------------------------------------------------------------------------------------------


def test_short_walk_follows_the_steps_and_lifts_the_trailing_heel(builder):
    """走两步（迈一步、再把后面的脚收过来）：做得出来；后面那只脚离地以前脚跟抬了起来；最后重心在两只脚中间。"""
    motion = builder.walk("walk", "走", 0.8, "", steps=2)
    assert motion.feasible
    soles = [builder.anatomy.legs[side].sole for side in Side]
    data = mujoco.MjData(builder.model)
    pitches = []
    for frame in motion.frames:
        data.qpos[:] = frame.qpos
        mujoco.mj_kinematics(builder.model, data)
        forward = data.site_xmat[builder.model.site(soles[1]).id].reshape(3, 3)[:, 0]
        pitches.append(math.degrees(math.asin(-forward[UP])))
    assert max(pitches) > 10.0
    final = np.mean([data.site_xpos[builder.model.site(site).id] for site in soles], axis=0)
    end = center_of(builder, motion.frames[-1].qpos)
    assert end[:2] == pytest.approx(
        final[:2] + (builder.center[:2] - np.mean(list(builder.soles.values()), axis=0)[:2]), abs=0.01
    )


def test_walk_needs_at_least_two_steps(builder):
    """一步也不完整（少于 2 步）：拒绝。"""
    with pytest.raises(ValueError, match="至少走 2 步"):
        builder.walk("walk", "走", 0.8, "", steps=1)


@pytest.mark.parametrize("up", [True, False], ids=["上楼", "下楼"])
def test_two_stairs_end_on_the_step_with_the_weight_between_the_feet(builder, up):
    """上（下）两级考场的楼梯（一级 20 cm）：做得出来，身体不插到一起；
    最后两只脚都在第二级上，重心在两只脚中间的上面。"""
    motion = builder.stairs("stairs", "楼梯", up=up, description="", steps=2)
    assert motion.feasible
    assert self_contacts(builder.body, [frame.qpos for frame in motion.frames]) == {}, "抬起来的腿碰到手，手臂要让开"
    data = mujoco.MjData(builder.model)
    data.qpos[:] = motion.frames[-1].qpos
    mujoco.mj_kinematics(builder.model, data)
    mujoco.mj_comPos(builder.model, data)
    level = 2 * STAIR_RISER_M * (1 if up else -1)
    for leg in builder.anatomy.legs.values():
        assert data.site_xpos[builder.model.site(leg.sole).id][UP] == pytest.approx(level, abs=1e-3)
    end = center_of(builder, motion.frames[-1].qpos)
    assert end[UP] == pytest.approx(builder.center[UP] + level, abs=0.01)


def test_stairs_need_at_least_one_step(builder):
    """一级都不走：拒绝。"""
    with pytest.raises(ValueError, match="至少走 1 级"):
        builder.stairs("stairs", "楼梯", up=True, description="", steps=0)


# 用手、跪着的动作 --------------------------------------------------------------------------------------


def test_door_pull_leans_the_body_back(builders):
    """拉门：右手拉着 50 N，重心往后挪，挪的量约是"拉力 x 把手高 ÷ 体重"。"""
    builder = builders["Nova"]
    motion = builder.pull_door("door", "门", "")
    assert motion.feasible
    pulled = center_of(builder, motion.frames[-1].qpos)
    expected = 50.0 * 1.0 / (builder.ik.mass * 9.81)
    assert builder.center[0] - pulled[0] == pytest.approx(expected, rel=0.1)


def test_lifting_a_box_reaches_in_front_of_the_thighs_first(builders):
    """搬箱子：做得出来，身体不插到一起；伸手的路上手先到把手的前后、左右（在大腿前面），再往下；两只手隔 40 cm。"""
    builder = builders["Nova"]
    motion = builder.lift_box("box", "搬", "")
    assert motion.feasible
    assert self_contacts(builder.body, [frame.qpos for frame in motion.frames]) == {}
    data = mujoco.MjData(builder.model)
    data.qpos[:] = frame_at(motion, BOX_REACH_S).qpos
    mujoco.mj_kinematics(builder.model, data)
    toe = max(toe[0] for toe in builder._toe_positions())
    for side in Side:
        palm = data.site_xpos[builder.model.site(builder.anatomy.palms[side]).id]
        expected_y = BOX_HALF_WIDTH_M if side is Side.LEFT else -BOX_HALF_WIDTH_M
        assert palm[:UP] == pytest.approx([toe + BOX_FRONT_OF_TOES_M, expected_y], abs=5e-3)


def test_push_up_from_the_knees_rests_on_knees_and_hands(builders):
    """跪着撑起来：膝盖和两只手撑着，身体沉下 12 cm 再撑起来；做得出来。"""
    builder = builders["Nova"]
    motion = builder.push_up_from_knees("pushup", "撑", "", builder.all_fours())
    assert motion.feasible
    labels = {support.label for support in motion.frames[0].supports}
    assert labels == {"左膝", "右膝", "左手", "右手"}
    heights = [center_of(builder, frame.qpos)[UP] for frame in motion.frames]
    assert heights[0] - min(heights) == pytest.approx(PUSH_UP_DEPTH_M, abs=2e-3)


def test_baseline_has_no_hands_and_cannot_kneel(builders):
    """G1 的身体描述里没有手心、膝盖的点：不做用手的、跪着的动作。Nova 都能做。"""
    assert not builders["G1"].has_hands
    assert not builders["G1"].can_kneel
    assert builders["Nova"].has_hands
    assert builders["Nova"].can_kneel


# 小零件 ----------------------------------------------------------------------------------------------


def test_foot_turn_weight_is_hard_on_the_ground_and_soft_in_the_air():
    """脚的朝向：着地时一定要对上（HARD），刚抬起时也是；抬到中间时只是软的要求（SOFT）。"""
    assert _foot_turn_weight(float("nan")) == HARD
    assert _foot_turn_weight(SWING_HOLD_SHARE / 2) == pytest.approx(HARD)
    assert _foot_turn_weight(0.5) == pytest.approx(SOFT)


def test_quintic_starts_at_rest_and_ends_with_the_given_speed():
    """五次多项式：开头停着；到 duration 时到了 end，速度是 end_speed。"""
    duration, start, end, speed = 0.2, 0.5, 0.9, 2.0
    assert _quintic(0.0, duration, start, end, end_speed=speed, end_acceleration=-9.81) == pytest.approx(start)
    assert _quintic(duration, duration, start, end, end_speed=speed, end_acceleration=-9.81) == pytest.approx(end)
    step = 1e-5
    near_end = _quintic(duration - step, duration, start, end, end_speed=speed, end_acceleration=-9.81)
    assert (end - near_end) / step == pytest.approx(speed, rel=1e-3)
    near_start = _quintic(step, duration, start, end, end_speed=speed, end_acceleration=-9.81)
    assert (near_start - start) / step == pytest.approx(0.0, abs=1e-6)
