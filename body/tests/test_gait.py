import math

import numpy as np
import pytest

from nova_body.body import Side
from nova_body.gait import (
    HEEL_DOWN_SHARE,
    TOE_PATCH_M,
    Foothold,
    Timing,
    bump,
    center_of_mass_path,
    heel_raised,
    lower_envelope,
    plan_steps,
    smooth,
    swing_position,
    toe_patch,
)

DT = 0.01
FOOT = 0.26
LIFT = 0.05
TIMING = Timing(start_shift_s=0.3, single_s=0.4, double_s=0.2, end_shift_s=0.3, hold_s=0.2)
START = {Side.LEFT: np.array([0.0, 0.1, 0.0]), Side.RIGHT: np.array([0.0, -0.1, 0.0])}
STEP = 0.3


def two_steps() -> list[Foothold]:
    """左脚先迈一步，右脚再迈到左脚前面。"""
    return [
        Foothold(Side.LEFT, np.array([STEP, 0.1, 0.0])),
        Foothold(Side.RIGHT, np.array([2 * STEP, -0.1, 0.0])),
    ]


def frames_of(seconds: float) -> int:
    return round(seconds / DT)


def phase_starts() -> dict[str, int]:
    """每一段从第几帧开始：开始挪重心、第一步、两只脚着地、第二步、最后挪回中间、停着。"""
    starts, frame = {}, 0
    for name, seconds in (
        ("start", TIMING.start_shift_s),
        ("first", TIMING.single_s),
        ("double", TIMING.double_s),
        ("second", TIMING.single_s),
        ("end", TIMING.end_shift_s),
        ("hold", TIMING.hold_s),
    ):
        starts[name] = frame
        frame += frames_of(seconds)
    starts["total"] = frame
    return starts


def walk(**options) -> object:
    return plan_steps(START, two_steps(), TIMING, DT, foot_length_m=FOOT, lift_m=LIFT, **options)


# 脚步 ------------------------------------------------------------------------------------------------


def test_plan_has_one_frame_for_every_step_of_time():
    """帧数 = 每一段的时间加起来 ÷ 每一帧的时间；每一帧都有两只脚的位置、谁着地、压力中心。"""
    plan = walk()
    total = phase_starts()["total"]
    assert plan.frames == total
    for side in Side:
        assert plan.feet[side].shape == (total, 3)
        assert plan.pitches[side].shape == (total,)
        assert len(plan.patches[side]) == total
    assert plan.zmp.shape == (total, 2)
    assert plan.surface.shape == (total,)


def test_feet_take_turns_and_end_where_the_steps_say():
    """先两只脚着地，左脚抬起时右脚撑着，再两只脚着地，右脚抬起时左脚撑着；最后脚在说好的地方。"""
    plan, starts = walk(), phase_starts()
    both = frozenset(Side)
    assert plan.supports[starts["start"]] == both
    assert plan.supports[starts["first"]] == frozenset({Side.RIGHT})
    assert plan.supports[starts["double"]] == both
    assert plan.supports[starts["second"]] == frozenset({Side.LEFT})
    assert plan.supports[-1] == both
    assert plan.feet[Side.LEFT][-1] == pytest.approx([STEP, 0.1, 0.0])
    assert plan.feet[Side.RIGHT][-1] == pytest.approx([2 * STEP, -0.1, 0.0])


def test_standing_foot_does_not_move_while_the_other_swings():
    """一只脚抬起来迈的时候，撑着的那只脚一点也不动。"""
    plan, starts = walk(), phase_starts()
    standing = plan.feet[Side.RIGHT][starts["first"] : starts["double"]]
    assert np.ptp(standing, axis=0) == pytest.approx([0.0, 0.0, 0.0])


def test_swinging_foot_lifts_and_lands_softly():
    """抬起来的脚走到一半时最高（抬了 lift_m），起点和终点的速度都是 0。"""
    plan, starts = walk(), phase_starts()
    swing = plan.feet[Side.LEFT][starts["first"] : starts["double"]]
    assert swing[:, 2].max() == pytest.approx(LIFT, abs=1e-3)
    assert np.linalg.norm(swing[1] - swing[0]) < 1e-3
    assert np.linalg.norm(swing[-1] - swing[-2]) < 1e-3


def test_a_walk_needs_at_least_one_step():
    """一步都没有：拒绝。"""
    with pytest.raises(ValueError, match="至少要走一步"):
        plan_steps(START, [], TIMING, DT, foot_length_m=FOOT, lift_m=LIFT)


@pytest.mark.parametrize("field", ["heel_off_rad", "toe_landing_rad"], ids=["抬脚跟", "脚掌落地"])
def test_rejects_negative_heel_angles(field):
    """脚跟抬起的角度是负的：拒绝。"""
    with pytest.raises(ValueError, match="不能是负的"):
        walk(**{field: -0.1})


@pytest.mark.parametrize("field", ["start_shift_s", "single_s", "double_s", "end_shift_s", "hold_s"])
def test_timing_must_be_positive(field):
    """每一段的时间都要大于 0。"""
    values = {"start_shift_s": 0.3, "single_s": 0.4, "double_s": 0.2, "end_shift_s": 0.3, "hold_s": 0.2}
    values[field] = 0.0
    with pytest.raises(ValueError, match=field):
        Timing(**values)


# 脚跟抬起来、脚掌落地 ---------------------------------------------------------------------------------


def test_trailing_heel_rises_before_the_foot_leaves_the_ground():
    """两只脚着地时，后面那只脚（右脚）的脚跟慢慢抬起来，到它抬起的那一刻抬到 heel_off_rad。"""
    heel_off = math.radians(20)
    plan, starts = walk(heel_off_rad=heel_off), phase_starts()
    rising = plan.pitches[Side.RIGHT][starts["double"] : starts["second"]]
    assert rising[0] == pytest.approx(0.0, abs=1e-3)
    assert rising[-1] == pytest.approx(heel_off)
    assert np.all(np.diff(rising) >= -1e-12)
    assert plan.pitches[Side.LEFT][starts["double"] : starts["second"]] == pytest.approx(0.0)


def test_toe_stays_on_the_ground_while_the_heel_rises():
    """脚跟抬起来的时候绕脚尖转：脚尖不动、还在地上，脚底正中间往上抬。"""
    heel_off = math.radians(20)
    plan, starts = walk(heel_off_rad=heel_off), phase_starts()
    for index in range(starts["double"], starts["second"]):
        sole, pitch = plan.feet[Side.RIGHT][index], plan.pitches[Side.RIGHT][index]
        toe = sole + FOOT / 2 * np.array([math.cos(pitch), 0.0, -math.sin(pitch)])
        assert toe == pytest.approx([FOOT / 2, -0.1, 0.0], abs=1e-9)
    assert plan.feet[Side.RIGHT][starts["second"] - 1][2] == pytest.approx(FOOT / 2 * math.sin(heel_off))


def test_only_the_front_of_a_raised_foot_holds_the_body():
    """脚跟抬起来以后，撑着的只有脚掌最前面那一条；放平的脚整只撑着。"""
    plan, starts = walk(heel_off_rad=math.radians(20)), phase_starts()
    raised = plan.patches[Side.RIGHT][starts["second"] - 1]
    flat = plan.patches[Side.LEFT][starts["second"] - 1]
    assert raised == pytest.approx((TOE_PATCH_M, FOOT / 2 - TOE_PATCH_M / 2))
    assert flat == pytest.approx((FOOT, 0.0))


def test_landing_foot_touches_down_on_its_front_and_lowers_the_heel():
    """用脚掌先落地：落地的那一刻脚跟还抬着 toe_landing_rad，两只脚着地的前一段时间里放平。"""
    landing = math.radians(20)
    plan, starts = walk(toe_landing_rad=landing), phase_starts()
    assert plan.pitches[Side.LEFT][starts["double"] - 1] == pytest.approx(landing)
    flat_from = starts["double"] + math.ceil(HEEL_DOWN_SHARE * frames_of(TIMING.double_s))
    assert plan.pitches[Side.LEFT][flat_from] == pytest.approx(0.0, abs=1e-9)
    assert plan.feet[Side.LEFT][flat_from] == pytest.approx([STEP, 0.1, 0.0])


def test_heel_raised_turns_about_the_front_of_the_patch():
    """脚跟抬起 0 度时不动；抬起来时绕踩着的那一块的最前面转，脚底正中间到那条边的距离不变。"""
    sole = np.array([1.0, 0.0, 0.2])
    patch = (0.2, 0.03)
    assert heel_raised(sole, patch, 0.0) == pytest.approx(sole)
    pivot = sole + np.array([patch[1] + patch[0] / 2, 0.0, 0.0])
    raised = heel_raised(sole, patch, math.radians(30))
    assert np.linalg.norm(raised - pivot) == pytest.approx(np.linalg.norm(sole - pivot))
    assert raised[2] > sole[2]


@pytest.mark.parametrize(
    ("patch", "expected"),
    [((0.26, 0.0), (TOE_PATCH_M, 0.13 - TOE_PATCH_M / 2)), ((0.03, 0.05), (0.03, 0.05))],
    ids=["整只脚", "比脚掌那一条还短"],
)
def test_toe_patch_is_the_front_strip(patch, expected):
    """脚掌前面那一条：踩着的那一块最前面 TOE_PATCH_M 长；踩着的比这还短，就是整块。"""
    assert toe_patch(patch) == pytest.approx(expected)


# 压力中心 --------------------------------------------------------------------------------------------


def test_pressure_center_walks_from_heel_to_the_front_of_the_standing_foot():
    """单脚撑着时，压力中心在撑着的那只脚底下，从偏脚跟挪到脚掌前面那一条的中间。"""
    plan, starts = walk(), phase_starts()
    single = plan.zmp[starts["first"] : starts["double"]]
    assert single[0, 0] < 0.0 < single[-1, 0]
    assert single[-1] == pytest.approx([FOOT / 2 - TOE_PATCH_M / 2, -0.1])
    assert np.all(np.diff(single[:, 0]) > 0)


def test_pressure_center_moves_to_the_middle_at_the_end():
    """走完以后压力中心停在两只脚中间。"""
    plan = walk()
    assert plan.zmp[-1, 1] == pytest.approx(0.0)
    assert plan.zmp[-1, 0] == pytest.approx((STEP + 2 * STEP) / 2 + (FOOT / 2 - TOE_PATCH_M / 2 - 0.15 * FOOT) / 2)


# 抬起来的脚怎么走 --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rise", "higher_first"),
    [(0.4, True), (-0.4, False)],
    ids=["上楼：先抬高再往前", "下楼：先往前再落下"],
)
def test_swing_on_stairs_avoids_the_step_edges(rise, higher_first):
    """上楼时脚先抬高再往前，下楼时先往前再往下。"""
    origin, target = np.zeros(3), np.array([0.44, 0.0, rise])
    early = swing_position(origin, target, 0.4, 0.0, climbing=True)
    up_share = early[2] / rise
    forward_share = early[0] / target[0]
    assert bool(up_share > forward_share) == higher_first


def test_flat_swing_moves_forward_and_up_together():
    """平地上：往前和抬高按同一条平滑的曲线走，中间抬到最高。"""
    origin, target = np.zeros(3), np.array([0.5, 0.0, 0.0])
    middle = swing_position(origin, target, 0.5, LIFT, climbing=False)
    assert middle == pytest.approx([0.25, 0.0, LIFT])


# 重心的路 --------------------------------------------------------------------------------------------


def test_center_of_mass_stays_over_a_pressure_center_that_does_not_move():
    """压力中心不动，重心就停在它上面。"""
    zmp = np.tile([0.1, -0.05], (100, 1))
    path = center_of_mass_path(zmp, np.full(100, 0.9), DT, zmp[0], zmp[-1])
    assert path == pytest.approx(zmp, abs=1e-6)


def test_center_of_mass_path_reproduces_the_planned_pressure_center():
    """由重心的路倒算出来的压力中心（倒立摆：重心 - 加速度 ÷ ω²），大多数时候和计划的差不到 1 cm；两头停着。

    按动作里用的时间（开始挪重心 0.6 s）。换脚的那一下差得多一些：倒立摆要先往反方向挪一点才走得动。
    """
    timing = Timing(start_shift_s=0.6, single_s=0.5, double_s=0.17, end_shift_s=0.6, hold_s=0.4)
    plan = plan_steps(START, two_steps(), timing, DT, foot_length_m=FOOT, lift_m=LIFT)
    height = np.full(plan.frames, 0.9)
    start, end = plan.zmp[0], plan.zmp[-1]
    path = center_of_mass_path(plan.zmp, height, DT, start, end)
    acceleration = (path[2:] - 2 * path[1:-1] + path[:-2]) / DT**2
    error = np.linalg.norm(path[1:-1] - acceleration * 0.9 / 9.81 - plan.zmp[1:-1], axis=1)
    assert np.median(error) < 0.01
    assert np.mean(error) < 0.02
    assert path[0] == pytest.approx(start, abs=1e-3)
    assert path[-1] == pytest.approx(end, abs=1e-3)


def test_center_of_mass_path_needs_enough_frames():
    """太短了求不出：拒绝。"""
    with pytest.raises(ValueError, match="太短了"):
        center_of_mass_path(np.zeros((5, 2)), np.ones(5), DT, np.zeros(2), np.zeros(2))


# 小零件 ----------------------------------------------------------------------------------------------


def test_smooth_goes_from_zero_to_one_and_stays_there():
    """平滑的曲线：0 以下是 0，1 以上是 1，中间是 0.5。"""
    assert [smooth(-1.0), smooth(0.0), smooth(0.5), smooth(1.0), smooth(2.0)] == pytest.approx([0, 0, 0.5, 1, 1])


def test_bump_is_one_in_the_middle_and_zero_at_both_ends():
    """鼓包：两头是 0，中间是 1，外面也是 0。"""
    assert [bump(-0.5), bump(0.0), bump(0.5), bump(1.0), bump(1.5)] == pytest.approx([0, 0, 1, 0, 0])


def test_lower_envelope_never_goes_above_the_line():
    """平滑的下包络：处处不比原来的线高，原来是直线的地方还是那条直线。"""
    values = np.ones(200)
    values[80:100] = 0.7
    envelope = lower_envelope(values, 10)
    assert np.all(envelope <= values + 1e-12)
    assert envelope[:60] == pytest.approx(1.0)
    assert envelope[90] == pytest.approx(0.7)


def test_lower_envelope_is_smooth_where_the_line_jumps():
    """原来的线一下子跳下去，下包络是慢慢变下去的（每一帧变得很少）。"""
    values = np.ones(200)
    values[100:] = 0.0
    envelope = lower_envelope(values, 10)
    assert np.abs(np.diff(envelope)).max() < 0.1


def test_lower_envelope_needs_a_window():
    """窗口小于 1 帧：拒绝。"""
    with pytest.raises(ValueError, match="窗口至少 1 帧"):
        lower_envelope(np.ones(10), 0)
